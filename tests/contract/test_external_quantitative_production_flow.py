"""Real Core participant proof for the externally-produced quantitative path.

Only object bytes and independently retained authority records are local test
fixtures.  The test never seeds a Core authority, monkeypatches a participant,
or uses a permissive authority provider.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.acquisition import observation_epoch_id
from ksi_core.app_assembly import assemble_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, Role
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import DigestBoundUploadCapability, ObjectStorageObservation
from ksi_core.external_evidence import EvidenceVerdict, ExternalEvidenceDeclarationIntent
from ksi_core.external_evidence_validations import EvidenceValidationVerdict
from ksi_core.external_quantitative_authority import (
    CompatibilityRuleDescriptorV1,
    ExternalQuantitativeAuthorityCatalog,
    ExternalQuantitativeCatalogAuthorityRecord,
    ExternalQuantitativeCompatibilityRecord,
)
from ksi_core.external_relative_volumes import (
    ExternalRelativeVolumeObservedReportInput,
    ExternalRelativeVolumeQueuePolicy,
    ExternalRelativeVolumeVerdict,
)
from ksi_core.external_result_workflow_config import (
    ExternalQuantitativeWorkflowParticipants,
    catalog_admission_body_digest,
    load_external_result_workflow_config,
)
from ksi_core.external_validation_policy import PolicyAuthorityRecord, authorized_policy_body_digest
from ksi_core.leasing import LeaseFence
from ksi_core.observation_work_orders import ExternalReobservationExecutionDenied
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    ExternalArtifactInspectionReportV1,
    ExternalInspectionMeasurementPayloadV1,
    ExternalValidationPolicyV1,
    NodataRepresentation,
    ObservedVerticalReferenceV1,
    PolicyStatus,
    RasterMeasurementsV1,
    ResourceEnvelopeV1,
    SealedArtifactBindingV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence import ExternalEvidenceMeasurementPayloadV1
from ksi_event_contracts.external_evidence_context import (
    ExternalEvidenceMeasurementContextV1,
    ExternalIndependenceAttestationV1,
)
from ksi_event_contracts.external_reconstruction import (
    ExternalArtifactDeclarationV1,
    ExternalReconstructionSubmissionV1,
    ExternalReconstructionSubmissionV1Input,
    ExternalReconstructionSubmissionV1Producer,
)
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeMeasurementPayloadV1,
    ExternalVolumeInputBindingV1,
    ExternalVolumeMetricsV1,
    ExternalVolumeZoneSnapshotV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_mission_contracts.models import SiteFrame

_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [0.0, 0.0]]],
}


def _digest(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class _LocalObjectStorage:
    """A byte fixture at the storage boundary, never an authority provider."""

    def __init__(self) -> None:
        self._objects: dict[str, ObjectStorageObservation] = {}
        self._bytes: dict[str, bytes] = {}

    def presigned_put(self, object_key: str, *, content_type: str, ttl: timedelta) -> str:
        del content_type, ttl
        return "https://storage.invalid/put/" + object_key

    def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
        del ttl
        return "https://storage.invalid/get/" + object_key

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        self._bytes[object_key] = data
        self._objects[object_key] = ObjectStorageObservation(
            object_key=object_key,
            exists=True,
            size_bytes=len(data),
            sha256=_digest(data),
            content_type=content_type,
        )

    def get_bytes(self, object_key: str) -> bytes:
        return self._bytes[object_key]

    def delete(self, object_key: str) -> None:
        self._bytes.pop(object_key, None)
        self._objects.pop(object_key, None)

    def presigned_put_bound_digest(
        self, object_key: str, *, content_type: str, content_digest: str, ttl: timedelta
    ) -> DigestBoundUploadCapability:
        del ttl
        return DigestBoundUploadCapability(
            upload_url="https://storage.invalid/put/" + object_key,
            required_headers={
                "Content-Type": content_type,
                "x-amz-checksum-sha256": content_digest,
            },
        )

    def observe_object(self, object_key: str) -> ObjectStorageObservation:
        return self._objects.get(
            object_key, ObjectStorageObservation(object_key=object_key, exists=False)
        )


class _RetainedCatalogAuthority:
    """Test-owned retained external record source; it resolves exact active records."""

    def __init__(self, record: ExternalQuantitativeCatalogAuthorityRecord) -> None:
        assert record.digest is not None
        self._records = {record.digest: record}
        self._retired: set[str] = set()
        self._coordinator = None

    def bind(self, coordinator):
        if self._coordinator is not None:
            raise AssertionError("catalog authority must bind one assembled coordinator")
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self):
        return self._coordinator

    def resolve(self, authority_record_digest: str, now: datetime):
        record = self._records.get(authority_record_digest)
        return record if record is not None and record.is_active_at(now) else None

    def revoke(self, authority_record_digest: str) -> None:
        self._mutate(lambda: self._records.pop(authority_record_digest, None))

    def retire(self, authority_record_digest: str) -> None:
        """Retain a record for external resolution but close its local projection."""
        self._mutate(lambda: self._retired.add(authority_record_digest))

    def restore(self, authority_record_digest: str) -> None:
        self._mutate(lambda: self._retired.discard(authority_record_digest))

    def add(self, record: ExternalQuantitativeCatalogAuthorityRecord) -> None:
        assert record.digest is not None
        self._mutate(
            lambda: (
                self._records.__setitem__(record.digest, record),
                self._retired.discard(record.digest),
            )
        )

    def _mutate(self, operation) -> None:
        if self._coordinator is None:
            operation()
            return
        with self._coordinator.mutation():
            operation()

    def is_current(self, record: ExternalQuantitativeCatalogAuthorityRecord, now: datetime) -> bool:
        return (
            record.digest is not None
            and self._records.get(record.digest) == record
            and record.digest not in self._retired
            and record.is_active_at(now)
        )


class _RetainedPolicyAuthority:
    """Exact independently retained policy authority, never an always-go provider."""

    def __init__(self) -> None:
        self._records: dict[str, PolicyAuthorityRecord] = {}

    def add(self, record: PolicyAuthorityRecord) -> None:
        assert record.digest is not None
        self._records[record.digest] = record

    def resolve(self, authority_record_digest: str, now: datetime):
        record = self._records.get(authority_record_digest)
        return record if record is not None and record.is_active_at(now) else None


class _RetainedEvidenceContextAuthority:
    """Exact retained contexts, including historical binding and all scope fields."""

    def __init__(self, now: datetime) -> None:
        self._now = now
        self._coordinator = None
        self._records: dict[str, ExternalEvidenceMeasurementContextV1] = {}

    def bind(self, coordinator):
        if self._coordinator is not None:
            raise AssertionError("context provider must bind one assembled coordinator")
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self):
        return self._coordinator

    def add(self, context: ExternalEvidenceMeasurementContextV1) -> None:
        assert context.context_digest is not None
        self._mutate(lambda: self._records.__setitem__(context.context_digest, context))

    def retained_contexts(self) -> tuple[ExternalEvidenceMeasurementContextV1, ...]:
        """Return the independently retained source records for a restart fixture."""
        return tuple(self._records.values())

    def revoke(self, context_digest: str) -> None:
        self._mutate(lambda: self._records.pop(context_digest, None))

    def _mutate(self, operation) -> None:
        if self._coordinator is None:
            operation()
            return
        with self._coordinator.mutation():
            operation()

    @staticmethod
    def _matches(
        context: ExternalEvidenceMeasurementContextV1,
        *,
        subject,
        evidence_manifest_digest: str,
        target_dsm_artifact_id: str,
        target_dsm_observed_sha256: str,
        policy_digest: str,
        now: datetime,
    ) -> bool:
        return (
            context.is_active_at(now)
            and context.subject == subject
            and context.evidence_manifest_digest == evidence_manifest_digest
            and context.target_dsm_artifact_id == target_dsm_artifact_id
            and context.target_dsm_observed_sha256 == target_dsm_observed_sha256
            and context.policy_digest == policy_digest
        )

    def resolve_for_validation(self, *, now: datetime, **binding):
        matches = [
            context
            for context in self._records.values()
            if self._matches(context, now=now, **binding)
        ]
        return matches[0] if len(matches) == 1 else None

    def resolve_historical_for_validation(
        self, *, context_digest: str, issued_at: datetime, **binding
    ):
        context = self._records.get(context_digest)
        return (
            context
            if context is not None and self._matches(context, now=issued_at, **binding)
            else None
        )

    def is_current(self, context: ExternalEvidenceMeasurementContextV1) -> bool:
        return (
            context.context_digest is not None
            and self._records.get(context.context_digest) == context
            and context.is_active_at(self._now)
        )


def _principal(organization_id: str = "org-a") -> Principal:
    return Principal(
        principal_id="operator-a",
        kind=PrincipalKind.OPERATOR,
        role=Role.FIELD_OPERATOR,
        device_id=None,
        organization_id=organization_id,
    )


def _write_private(path: Path, body: object) -> None:
    path.write_text(json.dumps(body), encoding="utf-8")
    os.chmod(path, 0o600)


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=1_000_000,
        max_streamed_bytes=1_000_000,
        max_tiff_directories=4,
        max_tiff_entries=64,
        max_pixels=1_000_000,
        max_bands=4,
        max_blocks=128,
        max_decompressed_bytes=10_000_000,
        max_sample_bytes=1_000_000,
        max_geometry_vertices=64,
        max_cpu_seconds=10.0,
        max_memory_bytes=10_000_000,
        max_workspace_bytes=10_000_000,
        max_output_bytes=1_000_000,
        max_tenant_concurrency=2,
        max_queue_depth=4,
        max_deadline_seconds=60.0,
        lease_duration_seconds=10.0,
        max_retry_attempts=2,
    ).sealed()


def _observed_vertical_reference() -> ObservedVerticalReferenceV1:
    return ObservedVerticalReferenceV1(identifier="KNGeoid2018", basis="site datum")


def _workflow(
    path: Path,
    *,
    now: datetime,
    policy_authority: _RetainedPolicyAuthority,
    context_authority: _RetainedEvidenceContextAuthority,
):
    """Load a protected real workflow config backed by retained authority records."""
    envelope = _envelope()
    body = {
        "organizationId": "org-a",
        "executionTemplates": [
            {
                "executionPolicy": {
                    "contractVersion": "external-relative-volume-execution-policy.v1",
                    "policyId": "external-volume-policy",
                    "version": 1,
                    "algorithmBuildDigest": _digest("volume-algorithm"),
                    "configDigest": _digest("volume-config"),
                    "thresholdM": 0.1,
                    "minimumCommonValidFraction": 0.8,
                    "uncertaintyMethod": "INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1",
                    "resourceEnvelopeDigest": envelope.resource_envelope_digest,
                    "authorityRecordDigest": _digest("placeholder"),
                    "syntheticTestOnly": False,
                },
                "authorizedActorIds": ["operator-a", "volume-worker"],
                "validFrom": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                "validUntil": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                "maximumZoneCellCount": 10_000,
                "maximumZoneAreaM2": 1_000_000.0,
            }
        ],
    }
    provisional = {
        "version": "external-quantitative-catalog.v1",
        "authorityRecordDigest": _digest("placeholder"),
        "body": body,
    }
    authority = ExternalQuantitativeCatalogAuthorityRecord(
        organization_id="org-a",
        catalog_body_digest=catalog_admission_body_digest(provisional),
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=now - timedelta(hours=1),
        active_until=now + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    assert authority.digest is not None
    body["executionTemplates"][0]["executionPolicy"]["authorityRecordDigest"] = authority.digest
    catalog = {
        "version": "external-quantitative-catalog.v1",
        "authorityRecordDigest": authority.digest,
        "body": body,
    }
    catalog_path = path / "catalog.json"
    config_path = path / "workflow.json"
    _write_private(catalog_path, catalog)
    _write_private(
        config_path,
        {
            "version": "external-result-workflow-config.v1",
            "authorityJournalPath": str(path / "quantitative-authority.jsonl"),
            "catalogPath": str(catalog_path),
        },
    )
    catalog_authority = _RetainedCatalogAuthority(authority)
    participants = ExternalQuantitativeWorkflowParticipants(
        catalog_authority_port=catalog_authority,
        catalog_administration_actor_id="catalog-admin",
        queue_policy=ExternalRelativeVolumeQueuePolicy(
            lease_ttl=timedelta(seconds=10),
            deadline_after_issue=timedelta(seconds=60),
            max_attempts=2,
            max_active_requests_per_organization=2,
        ),
        clock=lambda: now,
        build_catalog_authority_currentness=catalog_authority.bind,
        policy_authority_port=policy_authority,
        build_evidence_context_authority=context_authority.bind,
    )
    return (
        load_external_result_workflow_config(
            config_path,
            participants=participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
        ),
        authority,
        envelope,
        catalog_authority,
    )


def _assemble(path: Path, workflow, storage: _LocalObjectStorage):
    opened: list[DurableJournal] = []

    def journal(name: str) -> DurableJournal:
        item = DurableJournal(path / name)
        opened.append(item)
        return item

    app = assemble_app(
        path,
        journal=journal,
        opened=opened,
        edge_sync_snapshot_every=None,
        auth_registry=AuthRegistry([]),
        evidence_storage=storage,
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="test-key",
        external_result_workflow=workflow,
    )
    return app, opened


def _submission(order, label: str, *, start: datetime, end: datetime):
    ortho = b"ortho-" + label.encode()
    dsm = b"dsm-" + label.encode()
    submission = ExternalReconstructionSubmissionV1(
        submission_id="external-" + label,
        revision=1,
        organization_id="org-a",
        site_id="site-a",
        observation_epoch_id=observation_epoch_id(order),
        submitted_at=start,
        submitted_by="operator-a",
        producer_declaration=ExternalReconstructionSubmissionV1Producer(
            software_name="external-geotiff-profile.v1",
            software_version="1.0.0",
            build_identifier="external-build-1",
            producer_run_identifier="run-" + label,
            configuration_digest=_digest("config-" + label),
            completed_at=end,
        ),
        input_declaration=ExternalReconstructionSubmissionV1Input(
            raw_media_stored_by_ksi=False,
            original_retention_locus="customer_workstation",
            local_input_manifest_digest=_digest("inputs-" + label),
            image_count=2,
            capture_started_at=start,
            capture_ended_at=end,
        ),
        artifacts=(
            ExternalArtifactDeclarationV1(
                artifact_id="ortho-" + label,
                kind=ProcessingArtifactKind.ORTHO,
                file_name="ortho-" + label + ".bin",
                format="GeoTIFF",
                content_type="application/octet-stream",
                declared_sha256=hashlib.sha256(ortho).hexdigest(),
                declared_size_bytes=len(ortho),
                declared_crs="EPSG:5186",
            ),
            ExternalArtifactDeclarationV1(
                artifact_id="dsm-" + label,
                kind=ProcessingArtifactKind.DSM,
                file_name="dsm-" + label + ".bin",
                format="GeoTIFF",
                content_type="application/octet-stream",
                declared_sha256=hashlib.sha256(dsm).hexdigest(),
                declared_size_bytes=len(dsm),
                declared_crs="EPSG:5186",
            ),
        ),
    ).sealed()
    return submission, {"ortho-" + label: ortho, "dsm-" + label: dsm}


def _sealed_revision(app, order, label: str, *, start: datetime, end: datetime, storage):
    reconstruction = app.state.external_reconstruction_store
    submission, contents = _submission(order, label, start=start, end=end)
    registered = reconstruction.register(
        submission, work_order=order, registered_by="operator-a", now=start
    )
    assert registered.revision is not None
    grants = reconstruction.upload_grants(
        order.work_order_id,
        submission.submission_id,
        submission.revision,
        organization_id="org-a",
        site_id="site-a",
        storage=storage,
    )
    assert grants.grants is not None
    for grant in grants.grants:
        storage.put_bytes(
            grant.object_key,
            contents[grant.artifact_id],
            content_type="application/octet-stream",
        )
    sealed = reconstruction.seal(
        order.work_order_id,
        submission.submission_id,
        submission.revision,
        organization_id="org-a",
        site_id="site-a",
        storage=storage,
        now=end,
    )
    assert sealed.revision is not None and sealed.revision.manifest is not None
    revision = sealed.revision
    assert revision.submission.submission_digest is not None
    assert revision.manifest.manifest_digest is not None
    subject = SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id=order.work_order_id,
        submission_id=submission.submission_id,
        revision=1,
        submission_digest=revision.submission.submission_digest,
        manifest_digest=revision.manifest.manifest_digest,
    )
    return revision, subject


def _admit_policy(app, *, subjects, envelope, authority: _RetainedPolicyAuthority, now):
    template = ExternalValidationPolicyV1(
        policy_id="external-geotiff-v1",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=_digest("inspector-build-1"),
        grammar_digest=_digest("grammar-1"),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=_digest("unbound-policy-authority"),
        inspection_rule_ids=("EXTERNAL_GEOTIFF_MEASURED_V1",),
        evidence_rule_ids=("CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",),
        compatibility_mapping_digests=(CompatibilityRuleDescriptorV1().canonical_digest(),),
        synthetic_test_only=False,
    ).sealed()
    record = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=tuple(subjects),
        permitted_uses=("INSPECTION", "EVIDENCE", "RELATIVE_VOLUME"),
        authorized_actor_ids=("policy-admin",),
        active_from=now - timedelta(hours=1),
        active_until=now + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    assert record.digest is not None
    authority.add(record)
    policy = template.model_copy(
        update={"authority_record_digest": record.digest, "policy_digest": None}, deep=True
    ).sealed()
    receipt = app.state.external_validation_policy_registry.admit(
        policy, actor="policy-admin", now=now
    )
    assert receipt.status.value == "ADMITTED"
    return policy


def _inspection_report(request, policy, subject, revision, fence, *, now: datetime):
    assert revision.manifest is not None and policy.policy_digest is not None
    vertical = _observed_vertical_reference()
    outcomes = []
    bindings = []
    for entry in revision.manifest.entries:
        observed = "sha256:" + entry.observed_sha256
        bindings.append(
            SealedArtifactBindingV1(artifact_id=entry.artifact_id, observed_sha256=observed)
        )
        outcomes.append(
            ArtifactInspectionOutcomeV1(
                artifact_id=entry.artifact_id,
                observed_sha256=observed,
                outcome=ArtifactOutcome.MEASURED,
                measurements=RasterMeasurementsV1(
                    observed_crs_identifier="EPSG:5186",
                    observed_crs_wkt="PROJCRS[EPSG:5186]",
                    observed_crs_digest=_digest("observed-crs-5186"),
                    observed_vertical_reference=vertical,
                    transform=(1.0, 0.0, 0.0, 0.0, -1.0, 10.0),
                    footprint_wkt="POLYGON((0 0,10 0,10 10,0 0,0 0))",
                    footprint_digest=_digest("footprint-" + entry.artifact_id),
                    width=10,
                    height=10,
                    band_count=3 if entry.kind is ProcessingArtifactKind.ORTHO else 1,
                    dtype="uint8" if entry.kind is ProcessingArtifactKind.ORTHO else "float32",
                    layout="striped",
                    nodata_representation=NodataRepresentation.NONE,
                    valid_pixel_count=100,
                ),
            )
        )
    payload = ExternalInspectionMeasurementPayloadV1(
        subject_digest=subject.canonical_digest(),
        sealed_manifest_digest=subject.manifest_digest,
        inspection_policy_digest=policy.policy_digest,
        inspector_build_digest=policy.parser_build_digest,
        artifact_bindings=tuple(bindings),
        outcomes=tuple(outcomes),
    )
    return ExternalArtifactInspectionReportV1(
        report_id="inspection-report-" + subject.work_order_id,
        request_id=request.request_id,
        subject=subject,
        subject_digest=subject.canonical_digest(),
        sealed_manifest_digest=subject.manifest_digest,
        inspection_policy_digest=policy.policy_digest,
        inspector_build_digest=policy.parser_build_digest,
        measurement_payload=payload,
        worker_instance_id=fence.worker_instance_id,
        lease_acquisition_id=fence.lease_acquisition_id,
        lease_generation=fence.lease_generation,
        reported_at=now,
    ).sealed()


def _inspect(app, *, revision, subject, policy, now):
    inspections = app.state.external_artifact_inspection_store
    issued = inspections.issue_after_seal(subject, now=now)
    assert issued.request is not None and issued.verdict.value in {"ISSUED", "IDEMPOTENT"}
    fence = LeaseFence(str(uuid4()), str(uuid4()), 0)
    leased = inspections.claim(issued.request.request_id, fence, now, organization_id="org-a")
    assert leased.fence is not None and leased.request is not None
    report = _inspection_report(leased.request, policy, subject, revision, leased.fence, now=now)
    reported = inspections.record_report(
        leased.request.request_id, leased.fence, report, now, organization_id="org-a"
    )
    assert reported.report is not None and reported.verdict.value == "REPORTED"
    return reported.report


def _validate_evidence(
    app,
    *,
    revision,
    subject,
    policy,
    context_authority: _RetainedEvidenceContextAuthority,
    now: datetime,
    storage: _LocalObjectStorage,
    label: str = "validated",
    checkpoint_count: int = 3,
):
    evidence_store = app.state.external_evidence_store
    dsm = next(
        entry for entry in revision.manifest.entries if entry.kind is ProcessingArtifactKind.DSM
    )
    content = b"checkpoint,independent\n" + label.encode() + b",2\n"
    declared = evidence_store.declare(
        ExternalEvidenceDeclarationIntent(
            target_dsm_artifact_id=dsm.artifact_id,
            declared_content_digest=_digest(content),
            declared_content_type="application/octet-stream",
            independence_basis="Independent checkpoint survey retained outside KSI.",
        ),
        revision=revision,
        principal=_principal(),
        key="declare-evidence-" + subject.work_order_id + "-" + label,
        now=now,
    )
    assert declared.item is not None and declared.verdict is EvidenceVerdict.DECLARED
    item = declared.item
    grant = evidence_store.grant(
        item.evidence_ref,
        revision=revision,
        principal=_principal(),
        key="grant-evidence-" + subject.work_order_id + "-" + label,
        storage=storage,
        now=now,
    )
    assert grant.verdict is EvidenceVerdict.DECLARED
    storage.put_bytes(item.object_key, content, content_type="application/octet-stream")
    sealed = evidence_store.seal(
        item.evidence_ref,
        revision=revision,
        principal=_principal(),
        key="seal-evidence-" + subject.work_order_id + "-" + label,
        storage=storage,
        now=now,
    )
    assert sealed.item is not None and sealed.item.manifest is not None
    item = sealed.item
    manifest = item.manifest
    assert manifest.evidence_manifest_digest is not None and policy.policy_digest is not None
    attestation = ExternalIndependenceAttestationV1(
        attestation_id="attestation-" + subject.work_order_id + "-" + label,
        evidence_manifest_digest=manifest.evidence_manifest_digest,
        subject_digest=subject.canonical_digest(),
        target_dsm_observed_sha256=manifest.target_dsm_observed_sha256,
        confirmed_by_actor_id="independent-validator",
        confirmed_at=now - timedelta(hours=2),
        reconstruction_exclusion_basis=(
            "Independent survey was retained outside the reconstruction run."
        ),
        synthetic_test_only=False,
    ).sealed()
    context = ExternalEvidenceMeasurementContextV1(
        context_id="context-" + subject.work_order_id + "-" + label,
        subject=subject,
        evidence_manifest_digest=manifest.evidence_manifest_digest,
        evidence_observed_sha256=manifest.observed_object_digest,
        evidence_observed_size_bytes=manifest.observed_size_bytes,
        target_dsm_artifact_id=manifest.target_dsm_artifact_id,
        target_dsm_observed_sha256=manifest.target_dsm_observed_sha256,
        policy_digest=policy.policy_digest,
        measurement_execution_manifest_digest=_digest("checkpoint-runner-v1"),
        rule_id="CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",
        csv_horizontal_crs="EPSG:5186",
        csv_vertical_reference_digest=_digest("observed-vertical-kngeoid2018"),
        minimum_checkpoint_count=3,
        maximum_checkpoint_count=100,
        maximum_rmse_m=0.5,
        maximum_abs_mean_error_m=0.2,
        maximum_abs_error_m=1.0,
        independent_attestation=attestation,
        authorized_actor_ids=("independent-validator",),
        active_from=now - timedelta(hours=1),
        active_until=now + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    context_authority.add(context)
    validations = app.state.external_evidence_validation_store
    issued = validations.issue_after_seal(item.evidence_ref, now=now)
    assert issued.request is not None and issued.verdict is EvidenceValidationVerdict.ISSUED
    leased = validations.claim(
        issued.request.validation_id,
        LeaseFence(str(uuid4()), str(uuid4()), 0),
        organization_id="org-a",
        now=now,
    )
    assert leased.fence is not None
    payload = ExternalEvidenceMeasurementPayloadV1(
        validation_id=issued.request.validation_id,
        evidence_manifest_digest=issued.request.evidence_manifest_digest,
        target_dsm_observed_sha256=issued.request.target_dsm_observed_sha256,
        policy_digest=issued.request.policy_digest,
        measured_checkpoint_count=checkpoint_count,
        mean_error_m=0.1,
        mae_m=0.1,
        rmse_m=0.1,
        max_abs_error_m=0.1,
        measured_at=now,
    )
    measured = validations.record_measurement(
        issued.request.validation_id,
        leased.fence,
        payload,
        organization_id="org-a",
        now=now,
    )
    expected = (
        EvidenceValidationVerdict.VALIDATED
        if checkpoint_count >= 3
        else EvidenceValidationVerdict.REJECTED
    )
    assert measured.record is not None and measured.verdict is expected
    assert measured.record.evidence_record_digest is not None
    return measured.record


def _mapping(
    *,
    subjects,
    revisions,
    reports,
    evidence_records,
    policy,
    area,
    now,
    catalog_digest,
):
    bindings = []
    for subject, revision, report in zip(subjects, revisions, reports, strict=True):
        dsm = next(
            entry for entry in revision.manifest.entries if entry.kind is ProcessingArtifactKind.DSM
        )
        bindings.append(
            ExternalVolumeInputBindingV1(
                subject=subject,
                inspection_report_digest=report.report_digest,
                dsm_artifact_id=dsm.artifact_id,
                observed_sha256="sha256:" + dsm.observed_sha256,
                observed_size_bytes=dsm.observed_size_bytes,
                observed_crs_digest=_digest("observed-crs-5186"),
                observed_vertical_reference_digest=_observed_vertical_reference().canonical_digest(),
                captured_from=revision.submission.input_declaration.capture_started_at,
                captured_to=revision.submission.input_declaration.capture_ended_at,
            )
        )
    zone = ExternalVolumeZoneSnapshotV1(
        organization_id="org-a",
        site_id="site-a",
        work_area_id=area.work_area_id,
        polygon=area.polygon,
        crs=area.crs,
        observed_crs_digest=_digest("observed-crs-5186"),
        analysis_vertical_reference_digest=_observed_vertical_reference().canonical_digest(),
    ).sealed()
    return ExternalQuantitativeCompatibilityRecord(
        organization_id="org-a",
        site_id="site-a",
        baseline=bindings[0],
        current=bindings[1],
        zone_snapshot=zone,
        validation_policy_digest=policy.policy_digest,
        external_profile="external-geotiff-profile.v1",
        grammar_digest=policy.grammar_digest,
        inspector_build_digest=policy.parser_build_digest,
        evidence_record_digests=tuple(record.evidence_record_digest for record in evidence_records),
        execution_policy_ref=catalog_digest,
        valid_from=now - timedelta(hours=1),
        valid_until=now + timedelta(hours=1),
    ).sealed()


def test_external_quantitative_real_participants_complete_authorized_cycle_across_restart(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC).replace(microsecond=0)
    storage = _LocalObjectStorage()
    policy_authority = _RetainedPolicyAuthority()
    context_authority = _RetainedEvidenceContextAuthority(now)
    workflow, catalog_record, envelope, catalog_authority = _workflow(
        tmp_path,
        now=now,
        policy_authority=policy_authority,
        context_authority=context_authority,
    )
    app, opened = _assemble(tmp_path, workflow, storage)
    try:
        sites = app.state.site_store
        area_store = app.state.work_area_store
        orders = app.state.observation_work_order_store
        assert (
            sites.register(
                "site-a",
                "External source site",
                SiteFrame(
                    crs="EPSG:5186",
                    vertical_datum="KNGeoid2018",
                    unit="meter",
                    transform_version="1.0.0",
                ),
                organization_id="org-a",
                actor="operator-a",
                now=now - timedelta(minutes=30),
            ).record
            is not None
        )
        area_result = area_store.register(
            "site-a",
            name="Exact quantitative area",
            polygon=_POLYGON,
            crs="EPSG:5186",
            supersedes=None,
            actor="operator-a",
            now=now - timedelta(minutes=29),
        )
        assert area_result.work_area is not None
        area = area_result.work_area
        baseline_order = orders.create_work_order(
            organization_id="org-a",
            site_id="site-a",
            name="Baseline customer survey",
            work_area_ids=[area.work_area_id],
            schedule_id=None,
            actor="operator-a",
            now=now - timedelta(minutes=28),
        )
        current_order = orders.create_work_order(
            organization_id="org-a",
            site_id="site-a",
            name="Current customer survey",
            work_area_ids=[area.work_area_id],
            schedule_id=None,
            actor="operator-a",
            now=now - timedelta(minutes=27),
        )
        baseline_revision, baseline_subject = _sealed_revision(
            app,
            baseline_order,
            "baseline",
            start=now - timedelta(minutes=20),
            end=now - timedelta(minutes=15),
            storage=storage,
        )
        current_revision, current_subject = _sealed_revision(
            app,
            current_order,
            "current",
            start=now - timedelta(minutes=10),
            end=now - timedelta(minutes=5),
            storage=storage,
        )
        policy = _admit_policy(
            app,
            subjects=(baseline_subject, current_subject),
            envelope=envelope,
            authority=policy_authority,
            now=now,
        )
        baseline_report = _inspect(
            app,
            revision=baseline_revision,
            subject=baseline_subject,
            policy=policy,
            now=now,
        )
        current_report = _inspect(
            app,
            revision=current_revision,
            subject=current_subject,
            policy=policy,
            now=now,
        )
        baseline_evidence = _validate_evidence(
            app,
            revision=baseline_revision,
            subject=baseline_subject,
            policy=policy,
            context_authority=context_authority,
            now=now,
            storage=storage,
        )
        current_evidence = _validate_evidence(
            app,
            revision=current_revision,
            subject=current_subject,
            policy=policy,
            context_authority=context_authority,
            now=now,
            storage=storage,
        )
        missing_checkpoint_evidence = _validate_evidence(
            app,
            revision=baseline_revision,
            subject=baseline_subject,
            policy=policy,
            context_authority=context_authority,
            now=now,
            storage=storage,
            label="missing-checkpoint",
            checkpoint_count=1,
        )
        mapping = _mapping(
            subjects=(baseline_subject, current_subject),
            revisions=(baseline_revision, current_revision),
            reports=(baseline_report, current_report),
            evidence_records=(baseline_evidence, current_evidence),
            policy=policy,
            area=area,
            now=now,
            catalog_digest=catalog_record.digest,
        )
        catalog = app.state.external_relative_volume_mapping_authority
        assert isinstance(catalog, ExternalQuantitativeAuthorityCatalog)
        with pytest.raises(ValueError, match="external-geotiff-profile.v1"):
            replace(mapping, external_profile="ksi-odm-civil-v1", mapping_record_digest=None)
        stale_zone = mapping.zone_snapshot.model_copy(
            update={
                "polygon": {
                    "type": "Polygon",
                    "coordinates": [[[0.0, 0.0], [0.0, 9.0], [9.0, 9.0], [0.0, 0.0]]],
                },
                "definition_digest": None,
            },
            deep=True,
        ).sealed()
        assert (
            catalog.admit_mapping(
                replace(mapping, zone_snapshot=stale_zone, mapping_record_digest=None),
                actor="catalog-admin",
                now=now,
            )
            is None
        )
        assert missing_checkpoint_evidence.evidence_record_digest is not None
        assert (
            catalog.admit_mapping(
                replace(
                    mapping,
                    evidence_record_digests=(
                        missing_checkpoint_evidence.evidence_record_digest,
                        mapping.evidence_record_digests[1],
                    ),
                    mapping_record_digest=None,
                ),
                actor="catalog-admin",
                now=now,
            )
            is None
        )
        revoked_mapping = replace(
            mapping,
            valid_from=now - timedelta(minutes=59),
            mapping_record_digest=None,
        ).sealed()
        admitted_revoked = catalog.admit_mapping(revoked_mapping, actor="catalog-admin", now=now)
        assert admitted_revoked is not None and admitted_revoked.mapping_digest is not None
        early_revocation = app.state.external_use_evaluator.request_pair(
            baseline_subject,
            current_subject,
            use="RELATIVE_VOLUME",
            zone_id=area.work_area_id,
            idempotency_key="revoked-before-decision",
            principal=_principal(),
            now=now,
        )
        assert early_revocation.verdict.value == "ELIGIBLE"
        revoked_at = now + timedelta(seconds=1)
        assert catalog.revoke_mapping(
            admitted_revoked.mapping_digest, actor="catalog-admin", now=revoked_at
        )
        assert (
            catalog.activate_execution(
                decision_ref=early_revocation.decision_id,
                principal=_principal(),
                current_work_order_id=current_order.work_order_id,
                now=revoked_at,
            )
            is None
        )
        active_now = now + timedelta(seconds=2)
        with pytest.raises(ValueError, match="principal organization"):
            app.state.external_use_evaluator.request_pair(
                baseline_subject,
                current_subject,
                use="RELATIVE_VOLUME",
                zone_id=area.work_area_id,
                idempotency_key="tenant-substitution",
                principal=_principal("org-b"),
                now=now,
            )
        admitted = catalog.admit_mapping(mapping, actor="catalog-admin", now=active_now)
        assert admitted is not None and admitted.mapping_digest == mapping.mapping_digest
        superseded_area_result = area_store.register(
            "site-a",
            name="Superseded quantitative area",
            polygon=_POLYGON,
            crs="EPSG:5186",
            supersedes=None,
            actor="operator-a",
            now=active_now,
        )
        assert superseded_area_result.work_area is not None
        superseded_area = superseded_area_result.work_area
        superseded_zone = mapping.zone_snapshot.model_copy(
            update={"work_area_id": superseded_area.work_area_id, "definition_digest": None},
            deep=True,
        ).sealed()
        superseded_mapping = replace(
            mapping, zone_snapshot=superseded_zone, mapping_record_digest=None
        ).sealed()
        assert (
            catalog.admit_mapping(superseded_mapping, actor="catalog-admin", now=active_now)
            is not None
        )
        successor_area_result = area_store.register(
            "site-a",
            name="Successor quantitative area",
            polygon=_POLYGON,
            crs="EPSG:5186",
            supersedes=superseded_area.work_area_id,
            actor="operator-a",
            now=active_now,
        )
        assert successor_area_result.work_area is not None
        stale_area_decision = app.state.external_use_evaluator.request_pair(
            baseline_subject,
            current_subject,
            use="RELATIVE_VOLUME",
            zone_id=superseded_area.work_area_id,
            idempotency_key="superseded-work-area-currentness",
            principal=_principal(),
            now=active_now,
        )
        assert stale_area_decision.verdict.value == "BLOCKED"
        activation_currentness_decision = app.state.external_use_evaluator.request_pair(
            baseline_subject,
            current_subject,
            use="RELATIVE_VOLUME",
            zone_id=area.work_area_id,
            idempotency_key="activation-currentness-decision",
            principal=_principal(),
            now=active_now,
        )
        assert activation_currentness_decision.verdict.value == "ELIGIBLE"
        activation_context = context_authority.retained_contexts()[0]
        assert activation_context.context_digest is not None
        context_authority.revoke(activation_context.context_digest)
        assert (
            catalog.activate_execution(
                decision_ref=activation_currentness_decision.decision_id,
                principal=_principal(),
                current_work_order_id=current_order.work_order_id,
                now=active_now,
            )
            is None
        )
        context_authority.add(activation_context)
        decision = app.state.external_use_evaluator.request_pair(
            baseline_subject,
            current_subject,
            use="RELATIVE_VOLUME",
            zone_id=area.work_area_id,
            idempotency_key="real-quantitative-decision",
            principal=_principal(),
            now=active_now,
        )
        assert decision.verdict.value == "ELIGIBLE" and decision.decision_digest is not None
        execution = catalog.activate_execution(
            decision_ref=decision.decision_id,
            principal=_principal(),
            current_work_order_id=current_order.work_order_id,
            now=active_now,
        )
        assert execution is not None
        authority_journal = tmp_path / "quantitative-authority.jsonl"
        journal_prefix = authority_journal.read_bytes()
        for journal in reversed(opened):
            journal.close()
        activation_restart_context = _RetainedEvidenceContextAuthority(now)
        for context in context_authority.retained_contexts():
            activation_restart_context.add(context)
        activation_restart_workflow, _, _, activation_catalog_authority = _workflow(
            tmp_path,
            now=now,
            policy_authority=policy_authority,
            context_authority=activation_restart_context,
        )
        app, opened = _assemble(tmp_path, activation_restart_workflow, storage)
        assert authority_journal.read_bytes() == journal_prefix
        recovered_catalog = app.state.external_relative_volume_mapping_authority
        assert isinstance(recovered_catalog, ExternalQuantitativeAuthorityCatalog)
        recovered = recovered_catalog.resolve_for_use(
            baseline=baseline_subject,
            current=current_subject,
            zone_id=area.work_area_id,
            policy=policy,
            now=active_now,
        )
        assert (
            recovered is not None
            and recovered.compatibility_mapping_digest == mapping.mapping_digest
        )
        assert authority_journal.read_bytes() == journal_prefix
        issued = app.state.external_relative_volume_store.issue(
            principal=_principal(),
            current_work_order_id=current_order.work_order_id,
            decision_ref=decision.decision_id,
            idempotency_key="real-quantitative-volume",
            now=active_now,
        )
        assert issued.verdict is ExternalRelativeVolumeVerdict.ISSUED and issued.record is not None
        leased = app.state.external_relative_volume_store.claim(
            issued.record.request.request_id,
            organization_id="org-a",
            principal_id="volume-worker",
            fence=LeaseFence(str(uuid4()), str(uuid4()), 0),
            now=active_now,
        )
        assert leased.fence is not None and leased.record is not None
        request = leased.record.request
        payload = ExternalRelativeVolumeMeasurementPayloadV1(
            request_digest=request.request_digest,
            decision_digest=request.decision_digest,
            baseline_dsm_digest=request.baseline.observed_sha256,
            current_dsm_digest=request.current.observed_sha256,
            zone_snapshot_digest=request.zone_snapshot.canonical_digest(),
            execution_policy_digest=request.execution_policy_digest,
            algorithm_build_digest=execution.execution_policy.algorithm_build_digest,
            config_digest=execution.execution_policy.config_digest,
            metrics=ExternalVolumeMetricsV1(
                zone_cell_count=10,
                common_valid_cell_count=10,
                zone_area_m2=10.0,
                measured_area_m2=10.0,
                common_valid_fraction=1.0,
                cut_m3=1.0,
                fill_m3=5.0,
                net_m3=4.0,
                threshold_m=execution.execution_policy.threshold_m,
                uncertainty_m3=None,
                uncertainty_note=(
                    "No trusted epoch RMSE is supplied by the external evidence chain."
                ),
            ),
        )
        reported = app.state.external_relative_volume_store.record_observed_report(
            request.request_id,
            organization_id="org-a",
            principal_id="volume-worker",
            fence=leased.fence,
            observed=ExternalRelativeVolumeObservedReportInput(
                payload=payload, computed_at=active_now
            ),
            now=active_now,
        )
        assert reported.record is not None and reported.record.report is not None
        report_ref = reported.record.report.report_id
        authority_lock = authority_journal.with_suffix(authority_journal.suffix + ".lock")
        assert authority_journal.stat().st_mode & 0o777 == 0o600
        assert authority_lock.stat().st_mode & 0o777 == 0o600
        assert authority_journal.stat().st_nlink == authority_lock.stat().st_nlink == 1

        resolved_before_mutation = recovered_catalog.resolve_for_use(
            baseline=baseline_subject,
            current=current_subject,
            zone_id=area.work_area_id,
            policy=policy,
            now=active_now,
        )
        assert resolved_before_mutation is not None
        retained_context = activation_restart_context.retained_contexts()[0]
        assert retained_context.context_digest is not None
        activation_restart_context.revoke(retained_context.context_digest)
        assert not recovered_catalog.is_current_for_use(resolved_before_mutation, now=active_now)
        with recovered_catalog.guard_current(
            authority=execution, principal=_principal(), now=active_now
        ) as guarded:
            assert guarded is None
        assert (
            recovered_catalog.resolve_for_use(
                baseline=baseline_subject,
                current=current_subject,
                zone_id=area.work_area_id,
                policy=policy,
                now=active_now,
            )
            is None
        )
        activation_restart_context.add(retained_context)
        assert catalog_record.digest is not None
        activation_catalog_authority.retire(catalog_record.digest)
        assert not recovered_catalog.is_current_for_use(resolved_before_mutation, now=active_now)
        assert (
            recovered_catalog.resolve_for_use(
                baseline=baseline_subject,
                current=current_subject,
                zone_id=area.work_area_id,
                policy=policy,
                now=active_now,
            )
            is None
        )
        activation_catalog_authority.restore(catalog_record.digest)
        activation_catalog_authority.revoke(catalog_record.digest)
        assert (
            recovered_catalog.resolve_for_use(
                baseline=baseline_subject,
                current=current_subject,
                zone_id=area.work_area_id,
                policy=policy,
                now=active_now,
            )
            is None
        )
        activation_catalog_authority.add(catalog_record)
    finally:
        for journal in reversed(opened):
            journal.close()

    restarted_context = _RetainedEvidenceContextAuthority(active_now)
    for context in context_authority.retained_contexts():
        restarted_context.add(context)
    restarted_workflow, _, _, _ = _workflow(
        tmp_path,
        now=now,
        policy_authority=policy_authority,
        context_authority=restarted_context,
    )
    restarted, reopened = _assemble(tmp_path, restarted_workflow, storage)
    try:
        service = restarted.state.external_result_workflow_service
        review = service.reviews.review(
            organization_id="org-a",
            report_ref=report_ref,
            principal=_principal(),
            evaluated_at=active_now,
        )
        proposal = service.create(
            organization_id="org-a",
            report_ref=report_ref,
            target_work_area_ids=(area.work_area_id,),
            reason="Review of measured external quantity result requires a reobservation plan.",
            principal=_principal(),
            actor="operator-a",
            now=active_now,
            idempotency_key="real-quantitative-proposal",
        )
        approval = service.approve(
            organization_id="org-a",
            proposal_ref=proposal.proposal_ref,
            expected_version=proposal.version,
            principal=_principal(),
            actor="operator-a",
            now=active_now,
            idempotency_key="real-quantitative-approval",
        )
        assert approval.planning_binding.report_digest == review.report.report_digest
        assert (
            approval.approval_receipt.successor_work_order_id
            == approval.successor_work_order.work_order_id
            == approval.planning_binding.successor_work_order_id
        )
        work_order_journal = tmp_path / "observation-work-orders.jsonl"
        approval_prefix = work_order_journal.read_bytes()
        idempotent_approval = service.approve(
            organization_id="org-a",
            proposal_ref=proposal.proposal_ref,
            expected_version=proposal.version,
            principal=_principal(),
            actor="operator-a",
            now=active_now,
            idempotency_key="real-quantitative-approval",
        )
        assert idempotent_approval == approval
        assert work_order_journal.read_bytes() == approval_prefix
        with pytest.raises(ExternalReobservationExecutionDenied, match="PLANNING_ONLY"):
            restarted.state.observation_work_order_store.assert_execution_allowed(
                approval.successor_work_order
            )
        restarted_catalog = restarted.state.external_relative_volume_mapping_authority
        assert isinstance(restarted_catalog, ExternalQuantitativeAuthorityCatalog)
        resolved_before_policy_revoke = restarted_catalog.resolve_for_use(
            baseline=baseline_subject,
            current=current_subject,
            zone_id=area.work_area_id,
            policy=policy,
            now=active_now,
        )
        assert resolved_before_policy_revoke is not None
        revoked_policy = restarted.state.external_validation_policy_registry.revoke(
            policy.policy_id,
            policy.version,
            actor="policy-admin",
            now=active_now + timedelta(seconds=1),
        )
        assert revoked_policy.status.value == "REVOKED"
        assert not restarted_catalog.is_current_for_use(
            resolved_before_policy_revoke, now=active_now + timedelta(seconds=1)
        )
        assert (
            restarted.state.external_relative_volume_store.issue(
                principal=_principal(),
                current_work_order_id=current_order.work_order_id,
                decision_ref=decision.decision_id,
                idempotency_key="revoked-policy-fresh-issue",
                now=active_now + timedelta(seconds=1),
            ).verdict
            is ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
        )
        assert (
            restarted.state.external_relative_volume_store.issue(
                principal=_principal(),
                current_work_order_id=current_order.work_order_id,
                decision_ref=decision.decision_id,
                idempotency_key="real-quantitative-volume",
                now=active_now + timedelta(seconds=1),
            ).verdict
            is ExternalRelativeVolumeVerdict.ALREADY_ISSUED
        )
    finally:
        for journal in reversed(reopened):
            journal.close()
