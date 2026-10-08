"""Reusable fully assembled local Analysis API fixture for HTTP/browser tests.

It is test-only.  The fixture supplies explicit local runtime material and
actual GeoTIFF bytes; it neither reads production configuration nor claims a
signed release/runtime proof.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.domains.external.ingress.external_reconstruction import (
    build_external_reconstruction_submission_ref,
)
from ksi_core.domains.observations.epoch_identity import observation_epoch_id
from ksi_core.durable_journal import DurableJournal
from ksi_core.evidence import DigestBoundUploadCapability, ObjectStorageObservation
from ksi_core.external_evidence import EvidenceVerdict, ExternalEvidenceDeclarationIntent
from ksi_core.external_evidence_validations import EvidenceValidationVerdict
from ksi_core.external_quantitative_authority import (
    CompatibilityRuleDescriptorV1,
    ExternalQuantitativeCatalogAuthorityRecord,
    ExternalQuantitativeCompatibilityRecord,
)
from ksi_core.external_relative_volumes import ExternalRelativeVolumeQueuePolicy
from ksi_core.external_result_workflow_config import (
    ExternalQuantitativeWorkflowParticipants,
    catalog_admission_body_digest,
    load_external_result_workflow_config,
)
from ksi_core.external_validation_policy import PolicyAuthorityRecord, authorized_policy_body_digest
from ksi_core.leasing import LeaseFence
from ksi_event_contracts.external_analysis_api import AnalysisObservationSelectorV1
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
    ExternalReconstructionSubmissionV2,
)
from ksi_event_contracts.external_relative_volume import (
    ExternalVolumeInputBindingV1,
    ExternalVolumeZoneSnapshotV1,
)
from ksi_event_contracts.observation_work_order import ObservationWorkOrderExecutionMode
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.site_frame import SiteFrame
from pyproj import CRS
from rasterio.io import MemoryFile
from rasterio.transform import Affine, from_origin

# ── Retired-helper inlines (P3 Task 5) ───────────────────────────────
# Copied verbatim from tests/contract/test_external_quantitative_production_flow.py
# (archived blob-identical with the legacy assembly it is built on). These
# builders are external-lane-only (no managed store, no signing key) and keep
# serving the staying analysis-lane fixtures below.


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


class _RetainedPolicyAuthority:
    """Exact independently retained policy authority, never an always-go provider."""

    def __init__(self) -> None:
        self._records: dict[str, PolicyAuthorityRecord] = {}
        self._coordinator: Any = None

    def bind(self, coordinator: Any) -> _RetainedPolicyAuthority:
        if self._coordinator is not None:
            raise AssertionError("policy provider must bind one assembled coordinator")
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self) -> Any:
        return self._coordinator

    def add(self, record: PolicyAuthorityRecord) -> None:
        assert record.digest is not None
        self._records[record.digest] = record

    def retained_records(self) -> tuple[PolicyAuthorityRecord, ...]:
        return tuple(self._records.values())

    def resolve(self, authority_record_digest: str, now: datetime) -> Any:
        record = self._records.get(authority_record_digest)
        return record if record is not None and record.is_active_at(now) else None

    def resolve_historical(self, authority_record_digest: str, at: datetime) -> Any:
        record = self._records.get(authority_record_digest)
        return record if record is not None and record.is_active_at(at) else None

    def is_current(self, authority: PolicyAuthorityRecord, now: datetime) -> bool:
        return (
            authority.digest is not None
            and self._records.get(authority.digest) == authority
            and authority.is_active_at(now)
        )


class _RetainedCatalogAuthority:
    """Test-owned retained external record source; it resolves exact active records."""

    def __init__(self, record: ExternalQuantitativeCatalogAuthorityRecord) -> None:
        assert record.digest is not None
        self._records = {record.digest: record}
        self._retired: set[str] = set()
        self._coordinator = None

    def bind(self, coordinator: Any) -> Any:
        if self._coordinator is not None:
            raise AssertionError("catalog authority must bind one assembled coordinator")
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self) -> Any:
        return self._coordinator

    def resolve(self, authority_record_digest: str, now: datetime) -> Any:
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
        digest = record.digest

        def add_record() -> None:
            self._records[digest] = record
            self._retired.discard(digest)

        self._mutate(add_record)

    def _mutate(self, operation: Any) -> None:
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


class _RetainedEvidenceContextAuthority:
    """Exact retained contexts, including historical binding and all scope fields."""

    def __init__(self, now: datetime) -> None:
        self._now = now
        self._coordinator = None
        self._records: dict[str, ExternalEvidenceMeasurementContextV1] = {}

    def bind(self, coordinator: Any) -> Any:
        if self._coordinator is not None:
            raise AssertionError("context provider must bind one assembled coordinator")
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self) -> Any:
        return self._coordinator

    def add(self, context: ExternalEvidenceMeasurementContextV1) -> None:
        assert context.context_digest is not None
        self._mutate(lambda: self._records.__setitem__(context.context_digest, context))

    def retained_contexts(self) -> tuple[ExternalEvidenceMeasurementContextV1, ...]:
        """Return the independently retained source records for a restart fixture."""
        return tuple(self._records.values())

    def revoke(self, context_digest: str) -> None:
        self._mutate(lambda: self._records.pop(context_digest, None))

    def _mutate(self, operation: Any) -> None:
        if self._coordinator is None:
            operation()
            return
        with self._coordinator.mutation():
            operation()

    @staticmethod
    def _matches(
        context: ExternalEvidenceMeasurementContextV1,
        *,
        subject: Any,
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

    def resolve_for_validation(self, *, now: datetime, **binding: Any) -> Any:
        matches = [
            context
            for context in self._records.values()
            if self._matches(context, now=now, **binding)
        ]
        return matches[0] if len(matches) == 1 else None

    def resolve_historical_for_validation(
        self, *, context_digest: str, issued_at: datetime, **binding: Any
    ) -> Any:
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


def _workflow_material(
    path: Path,
    *,
    now: datetime,
    organization_id: str = "org-a",
    catalog_active_for: timedelta = timedelta(hours=1),
) -> tuple[ExternalQuantitativeCatalogAuthorityRecord, ResourceEnvelopeV1, Path]:
    """Write owner-private catalog/config bytes without selecting an authority port."""
    envelope = _envelope()
    body: dict[str, Any] = {
        "organizationId": organization_id,
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
                "validUntil": (now + catalog_active_for).isoformat().replace("+00:00", "Z"),
                "maximumZoneCellCount": 10_000,
                "maximumZoneAreaM2": 1_000_000.0,
            }
        ],
        "singleExecutionTemplates": [
            {
                "executionPolicy": {
                    "contractVersion": "external-single-volume-execution-policy.v1",
                    "policyId": "single-policy-a",
                    "version": 1,
                    "algorithmBuildDigest": _digest("single-algorithm"),
                    "configDigest": _digest("single-config"),
                    "thresholdM": 0.0,
                    "minimumCommonValidFraction": 0.8,
                    "minimumBoundaryValidFraction": 0.5,
                    "uncertaintyMethod": "SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1",
                    "baseSurfaceMethod": "BOUNDARY_LINEAR_INTERPOLATION_V1",
                    "resourceEnvelopeDigest": envelope.resource_envelope_digest,
                    "authorityRecordDigest": _digest("placeholder"),
                    "syntheticTestOnly": False,
                },
                "authorizedActorIds": ["operator-a", "worker-principal"],
                "validFrom": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                "validUntil": (now + catalog_active_for).isoformat().replace("+00:00", "Z"),
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
        organization_id=organization_id,
        catalog_body_digest=catalog_admission_body_digest(provisional),
        authorized_administration_actor_ids=("catalog-admin",),
        active_from=now - timedelta(hours=1),
        active_until=now + catalog_active_for,
        synthetic_test_only=False,
    ).sealed()
    assert authority.digest is not None
    body["executionTemplates"][0]["executionPolicy"]["authorityRecordDigest"] = authority.digest
    body["singleExecutionTemplates"][0]["executionPolicy"]["authorityRecordDigest"] = (
        authority.digest
    )
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
    return authority, envelope, config_path


def _workflow(
    path: Path,
    *,
    now: datetime,
    organization_id: str = "org-a",
    policy_authority: _RetainedPolicyAuthority,
    context_authority: _RetainedEvidenceContextAuthority,
) -> Any:
    """Load a protected real workflow config backed by retained authority records."""
    authority, envelope, config_path = _workflow_material(
        path,
        now=now,
        organization_id=organization_id,
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
        build_policy_authority_currentness=policy_authority.bind,
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


def _evidence_context(
    item: Any,
    *,
    subject: Any,
    policy: Any,
    now: datetime,
    label: str,
    independent: bool = True,
) -> ExternalEvidenceMeasurementContextV1:
    manifest = item.manifest
    assert manifest.evidence_manifest_digest is not None and policy.policy_digest is not None
    attestation = (
        ExternalIndependenceAttestationV1(
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
        if independent
        else None
    )
    return ExternalEvidenceMeasurementContextV1(
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
        csv_vertical_reference_digest=_observed_vertical_reference().canonical_digest(),
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


def _submission(
    order: Any,
    label: str,
    *,
    start: datetime,
    end: datetime,
    dsm_bytes: bytes | None = None,
) -> Any:
    ortho = b"ortho-" + label.encode()
    dsm = dsm_bytes or b"dsm-" + label.encode()
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


def _sealed_revision(
    app: Any,
    order: Any,
    label: str,
    *,
    start: datetime,
    end: datetime,
    storage: Any,
    dsm_bytes: bytes | None = None,
) -> Any:
    reconstruction = app.state.external_reconstruction_store
    submission, contents = _submission(
        order, label, start=start, end=end, dsm_bytes=dsm_bytes
    )
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


def _record_evidence_validation(
    app: Any,
    *,
    item: Any,
    now: datetime,
    checkpoint_count: int,
    organization_id: str = "org-a",
) -> Any:
    validations = app.state.external_evidence_validation_store
    issued = validations.issue_after_seal(item.evidence_ref, now=now)
    assert issued.request is not None and issued.verdict in {
        EvidenceValidationVerdict.ISSUED,
        EvidenceValidationVerdict.IDEMPOTENT,
    }
    leased = validations.claim(
        issued.request.validation_id,
        LeaseFence(str(uuid4()), str(uuid4()), 0),
        organization_id=organization_id,
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
        organization_id=organization_id,
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


def _seal_evidence(
    app: Any,
    *,
    revision: Any,
    subject: Any,
    now: datetime,
    storage: _LocalObjectStorage,
    label: str,
    organization_id: str = "org-a",
) -> Any:
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
        principal=_principal(organization_id),
        key="declare-evidence-" + subject.work_order_id + "-" + label,
        now=now,
    )
    assert declared.item is not None and declared.verdict is EvidenceVerdict.DECLARED
    item = declared.item
    grant = evidence_store.grant(
        item.evidence_ref,
        revision=revision,
        principal=_principal(organization_id),
        key="grant-evidence-" + subject.work_order_id + "-" + label,
        storage=storage,
        now=now,
    )
    assert grant.verdict is EvidenceVerdict.DECLARED
    storage.put_bytes(item.object_key, content, content_type="application/octet-stream")
    sealed = evidence_store.seal(
        item.evidence_ref,
        revision=revision,
        principal=_principal(organization_id),
        key="seal-evidence-" + subject.work_order_id + "-" + label,
        storage=storage,
        now=now,
    )
    assert sealed.item is not None and sealed.item.manifest is not None
    return sealed.item


def _observed_vertical_reference() -> ObservedVerticalReferenceV1:
    return ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")


def _inspection_report(
    request: Any,
    policy: Any,
    subject: Any,
    revision: Any,
    fence: LeaseFence,
    *,
    now: datetime,
    transform: tuple[float, float, float, float, float, float] | None = None,
    vertical_reference: ObservedVerticalReferenceV1 | None = None,
    observed_crs_digest: str | None = None,
) -> Any:
    assert revision.manifest is not None and policy.policy_digest is not None
    vertical = vertical_reference or _observed_vertical_reference()
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
                    observed_crs_digest=observed_crs_digest or _digest("observed-crs-5186"),
                    observed_vertical_reference=vertical,
                    transform=transform or (1.0, 0.0, 0.0, 0.0, -1.0, 10.0),
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


def _inspect(
    app: Any,
    *,
    revision: Any,
    subject: Any,
    policy: Any,
    now: datetime,
    transform: tuple[float, float, float, float, float, float] | None = None,
    vertical_reference: ObservedVerticalReferenceV1 | None = None,
    observed_crs_digest: str | None = None,
) -> Any:
    inspections = app.state.external_artifact_inspection_store
    issued = inspections.issue_after_seal(subject, now=now)
    assert issued.request is not None and issued.verdict.value in {"ISSUED", "IDEMPOTENT"}
    fence = LeaseFence(str(uuid4()), str(uuid4()), 0)
    leased = inspections.claim(issued.request.request_id, fence, now, organization_id="org-a")
    assert leased.fence is not None and leased.request is not None
    report = _inspection_report(
        leased.request,
        policy,
        subject,
        revision,
        leased.fence,
        now=now,
        transform=transform,
        vertical_reference=vertical_reference,
        observed_crs_digest=observed_crs_digest,
    )
    reported = inspections.record_report(
        leased.request.request_id, leased.fence, report, now, organization_id="org-a"
    )
    assert reported.report is not None and reported.verdict.value == "REPORTED"
    return reported.report


def _validate_evidence(
    app: Any,
    *,
    revision: Any,
    subject: Any,
    policy: Any,
    context_authority: _RetainedEvidenceContextAuthority,
    now: datetime,
    storage: _LocalObjectStorage,
    label: str = "validated",
    checkpoint_count: int = 3,
    independent: bool = True,
    organization_id: str = "org-a",
) -> Any:
    item = _seal_evidence(
        app,
        revision=revision,
        subject=subject,
        now=now,
        storage=storage,
        label=label,
        organization_id=organization_id,
    )
    context_authority.add(
        _evidence_context(
            item, subject=subject, policy=policy, now=now, label=label, independent=independent
        )
    )
    return _record_evidence_validation(
        app,
        item=item,
        now=now,
        checkpoint_count=checkpoint_count,
        organization_id=organization_id,
    )


def _admit_policy(
    app: Any,
    *,
    subjects: Any,
    envelope: Any,
    authority: _RetainedPolicyAuthority,
    now: datetime,
) -> Any:
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


def _mapping(
    *,
    subjects: Any,
    revisions: Any,
    reports: Any,
    evidence_records: Any,
    policy: Any,
    area: Any,
    now: datetime,
    catalog_digest: str,
) -> Any:
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


def _single_mapping(
    *,
    subject: Any,
    revision: Any,
    report: Any,
    evidence_record: Any,
    policy: Any,
    area: Any,
    now: datetime,
    catalog_digest: str,
) -> Any:
    from ksi_core.domains.external.quantity.external_single_volume_authority import (
        ExternalSingleVolumeCompatibilityRecord,
    )

    dsm = next(
        entry for entry in revision.manifest.entries if entry.kind is ProcessingArtifactKind.DSM
    )
    target = ExternalVolumeInputBindingV1(
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
    zone = ExternalVolumeZoneSnapshotV1(
        organization_id="org-a",
        site_id="site-a",
        work_area_id=area.work_area_id,
        polygon=area.polygon,
        crs=area.crs,
        observed_crs_digest=_digest("observed-crs-5186"),
        analysis_vertical_reference_digest=_observed_vertical_reference().canonical_digest(),
    ).sealed()
    return ExternalSingleVolumeCompatibilityRecord(
        organization_id="org-a",
        site_id="site-a",
        target=target,
        zone_snapshot=zone,
        validation_policy_digest=policy.policy_digest,
        external_profile="external-geotiff-profile.v1",
        grammar_digest=policy.grammar_digest,
        inspector_build_digest=policy.parser_build_digest,
        evidence_record_digests=(evidence_record.evidence_record_digest,),
        execution_policy_ref=catalog_digest,
        valid_from=now - timedelta(hours=1),
        valid_until=now + timedelta(hours=1),
    ).sealed()



_OPERATOR_TOKEN = "analysis-local-fixture-operator"
_WORKER_TOKEN = "analysis-local-fixture-worker"
_VALIDATION_WORKER_TOKEN = "analysis-local-fixture-validation-worker"
_VIEWER_TOKEN = "analysis-local-fixture-viewer"
_MCP_CLIENT_TOKEN = "analysis-local-fixture-mcp-client"
_MCP_OTHER_AREA_TOKEN = "analysis-local-fixture-mcp-other-area"


def _geotiff_with_measured_spatial_case(
    values: np.ndarray, *, transform: Any, crs: str, nodata: float | None = None
) -> bytes:
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=values.shape[0],
            width=values.shape[1],
            count=1,
            dtype="float64",
            crs=CRS.from_user_input(crs),
            transform=transform,
            nodata=nodata,
        ) as dataset:
            dataset.write(values, 1)
        return memory.read()


class LoopbackObjectStorage(_LocalObjectStorage):
    """Test storage with real retained bytes and an explicitly set loopback URL origin."""

    def __init__(self) -> None:
        super().__init__()
        self._loopback_origin: str | None = None

    def set_loopback_origin(self, origin: str) -> None:
        if not origin.startswith("http://127.0.0.1:"):
            raise ValueError(
                "local Analysis fixture only permits an explicit loopback object origin"
            )
        self._loopback_origin = origin.rstrip("/")

    def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
        del ttl
        if self._loopback_origin is None:
            # Setup helpers may resolve input capabilities while sealing the
            # fixture.  That URL is never given to a worker before the test
            # configures its own loopback server.
            return "http://127.0.0.1:0/objects/" + quote(object_key, safe="")
        return self._loopback_origin + "/objects/" + quote(object_key, safe="")

    def object_bytes(self, object_key: str) -> bytes:
        return self.get_bytes(object_key)


@dataclass(slots=True)
class LocalAnalysisApiFixture:
    """Assembled local graph, scoped selectors, and test credentials without token logging."""

    app: FastAPI
    opened: list[DurableJournal]
    storage: LoopbackObjectStorage
    site_id: str
    work_area_id: str
    organization_id: str
    baseline: AnalysisObservationSelectorV1
    current: AnalysisObservationSelectorV1
    third: AnalysisObservationSelectorV1 | None
    v2_dsm_only: bool
    failed_checkpoint_current: bool
    failed_checkpoint_baseline: bool
    passed_and_failed_checkpoint_current: bool
    passed_checkpoint_epochs: tuple[str, ...]
    synthetic_inspection_report_digests: tuple[str, ...] = field(repr=False)
    synthetic_epoch_chronology: tuple[
        tuple[datetime, datetime, datetime, datetime], ...
    ] = field(repr=False)
    synthetic_policy_admitted_at: datetime = field(repr=False)
    _current_revision: Any = field(repr=False)
    _current_subject: Any = field(repr=False)
    _baseline_revision: Any = field(repr=False)
    _baseline_subject: Any = field(repr=False)
    _third_revision: Any = field(repr=False)
    _third_subject: Any = field(repr=False)
    _inspection_policy: Any = field(repr=False)
    _inspector_manifest: Any = field(repr=False)
    real_inspection: bool
    malformed_current_dsm: bool
    current_dsm_spatial_case: str
    _fixture_now: datetime = field(repr=False)
    _operator_token: str = field(repr=False)
    _worker_token: str = field(repr=False)
    _validation_worker_token: str = field(repr=False)
    _viewer_token: str = field(repr=False)
    _mcp_client_token: str = field(repr=False)
    _mcp_other_area_token: str = field(repr=False)
    _context_authority: _RetainedEvidenceContextAuthority = field(repr=False)
    _retained_policy_records: tuple[PolicyAuthorityRecord, ...] = field(repr=False)
    _retained_contexts: tuple[ExternalEvidenceMeasurementContextV1, ...] = field(repr=False)

    def operator_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self._operator_token}

    def worker_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self._worker_token}

    def validation_worker_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self._validation_worker_token}

    def viewer_headers(self) -> dict[str, str]:
        """Return a scoped read-only credential for authorization-boundary tests."""
        return {"Authorization": "Bearer " + self._viewer_token}

    def mcp_client_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self._mcp_client_token}

    def mcp_other_area_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer " + self._mcp_other_area_token}

    def set_loopback_object_origin(self, origin: str) -> None:
        self.storage.set_loopback_origin(origin)

    def revoke_evidence_context(self, context_digest: str) -> None:
        """Test-only currentness mutation for exact AP/NX transition coverage."""
        self._context_authority.revoke(context_digest)

    def restore_evidence_context(self, context_digest: str) -> None:
        """Restore one initially retained test context without inventing a record."""
        context = next(
            (
                item
                for item in self._retained_contexts
                if getattr(item, "context_digest", None) == context_digest
            ),
            None,
        )
        if context is None:
            raise LookupError("fixture context is not retained")
        self._context_authority.add(context)

    def append_failed_current_checkpoint_evaluation(self) -> Any:
        """Append a later Core REJECTED evaluation for the exact current DSM bytes."""
        if not self.v2_dsm_only:
            raise ValueError("late checkpoint evaluation requires the V2 DSM-only fixture")
        now = max(
            datetime.now(UTC).replace(microsecond=0),
            self._fixture_now + timedelta(seconds=1),
        )
        record = _validate_evidence(
            self.app,
            revision=self._current_revision,
            subject=self._current_subject,
            policy=self._inspection_policy,
            context_authority=self._context_authority,
            now=now,
            storage=self.storage,
            label="analysis-local-current-late-rejected-checkpoint",
            checkpoint_count=1,
            organization_id=self.organization_id,
        )
        self._retained_contexts = self._context_authority.retained_contexts()
        return record

    def close(self) -> None:
        for journal in reversed(self.opened):
            journal.close()


def _register_and_seal_v2_dsm(
    client: TestClient,
    app: FastAPI,
    order: Any,
    label: str,
    *,
    start: datetime,
    end: datetime,
    storage: LoopbackObjectStorage,
    dsm_bytes: bytes,
    organization_id: str = "org-a",
) -> tuple[Any, SealedExternalSubjectV1]:
    """Exercise V2 HTTP registration and shared digest-bound upload/seal routes."""
    candidate, contents = _submission(
        order, label, start=start, end=end, dsm_bytes=dsm_bytes
    )
    wire = candidate.model_dump(by_alias=True, mode="json")
    wire["contractVersion"] = "external-reconstruction-submission.v2"
    wire["submittedBy"] = "analysis-local-operator"
    wire["organizationId"] = organization_id
    wire["artifacts"] = [artifact for artifact in wire["artifacts"] if artifact["kind"] == "dsm"]
    wire["submissionDigest"] = ExternalReconstructionSubmissionV2.digest_for_wire(wire)

    v2_path = (
        f"/v1/observation-work-orders/{order.work_order_id}/"
        "external-reconstruction-submissions-v2"
    )
    registered = client.post(
        v2_path,
        headers={"Authorization": "Bearer " + _OPERATOR_TOKEN},
        json=wire,
    )
    assert registered.status_code == 201, registered.text
    response_body = registered.json()
    assert response_body["submission"]["contractVersion"] == (
        "external-reconstruction-submission.v2"
    )
    assert [item["kind"] for item in response_body["submission"]["artifacts"]] == ["dsm"]

    submission_ref = response_body["submissionRef"]
    shared_path = (
        f"/v1/observation-work-orders/{order.work_order_id}/"
        f"external-reconstruction-submissions/{submission_ref}/revisions/1"
    )
    fetched = client.get(shared_path, headers={"Authorization": "Bearer " + _OPERATOR_TOKEN})
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["submission"] == response_body["submission"]
    grants = client.post(
        shared_path + "/upload-grants",
        headers={"Authorization": "Bearer " + _OPERATOR_TOKEN},
    )
    assert grants.status_code == 200, grants.text
    assert len(grants.json()["grants"]) == 1
    grant = grants.json()["grants"][0]
    assert grant["artifactId"] == response_body["submission"]["artifacts"][0]["artifactId"]
    storage.put_bytes(
        grant["objectKey"],
        contents[grant["artifactId"]],
        content_type="application/octet-stream",
    )
    sealed = client.post(
        shared_path + "/seal",
        headers={"Authorization": "Bearer " + _OPERATOR_TOKEN},
    )
    assert sealed.status_code == 200, sealed.text
    assert [entry["kind"] for entry in sealed.json()["manifest"]["entries"]] == ["dsm"]

    record = app.state.external_reconstruction_store.get(
        order.work_order_id,
        candidate.submission_id,
        1,
        organization_id=organization_id,
        site_id="site-a",
    )
    assert record is not None and record.manifest is not None
    assert record.submission.submission_digest == wire["submissionDigest"]
    subject = SealedExternalSubjectV1(
        organization_id=organization_id,
        site_id="site-a",
        work_order_id=order.work_order_id,
        submission_id=candidate.submission_id,
        revision=1,
        submission_digest=record.submission.submission_digest,
        manifest_digest=record.manifest.manifest_digest,
    )
    return record, subject


def build_local_analysis_api_fixture(
    tmp_path: Path,
    *,
    v2_dsm_only: bool | None = None,
    include_third_epoch: bool | None = None,
    failed_checkpoint_current: bool = False,
    failed_checkpoint_baseline: bool = False,
    passed_and_failed_checkpoint_current: bool = False,
    passed_checkpoint_epochs: tuple[str, ...] = (),
    ai_egress_allowed: bool = False,
    retained_policy_records: tuple[PolicyAuthorityRecord, ...] = (),
    retained_contexts: tuple[ExternalEvidenceMeasurementContextV1, ...] = (),
    replay_of: LocalAnalysisApiFixture | None = None,
    real_inspection: bool = False,
    malformed_current_dsm: bool = False,
    current_dsm_spatial_case: str = "VALID",
    organization_id: str | None = None,
    analysis_activation: Any = None,
) -> LocalAnalysisApiFixture:
    """Seed inspected/sealed epochs backed by real 2×2 GeoTIFF bytes for local API tests."""
    if replay_of is not None:
        if organization_id is not None and organization_id != replay_of.organization_id:
            raise ValueError("replay fixture must preserve its source organization")
        if retained_policy_records or retained_contexts:
            raise ValueError("replay fixture retains its source policy/context records itself")
        if v2_dsm_only is not None and v2_dsm_only != replay_of.v2_dsm_only:
            raise ValueError("replay fixture must preserve its source reconstruction contract")
        if include_third_epoch is not None and include_third_epoch != (replay_of.third is not None):
            raise ValueError("replay fixture must preserve its source observation epochs")
        if failed_checkpoint_current and not replay_of.failed_checkpoint_current:
            raise ValueError("replay fixture cannot add a failed checkpoint evaluation")
        if failed_checkpoint_baseline and not replay_of.failed_checkpoint_baseline:
            raise ValueError("replay fixture cannot add a failed checkpoint evaluation")
        if (
            passed_and_failed_checkpoint_current
            and not replay_of.passed_and_failed_checkpoint_current
        ):
            raise ValueError("replay fixture cannot add checkpoint evaluations")
        if not set(passed_checkpoint_epochs).issubset(replay_of.passed_checkpoint_epochs):
            raise ValueError("replay fixture cannot add checkpoint evaluations")
        if real_inspection and not replay_of.real_inspection:
            raise ValueError("replay fixture cannot change its inspection evidence source")
        if malformed_current_dsm and not replay_of.malformed_current_dsm:
            raise ValueError("replay fixture cannot change its sealed DSM bytes")
        if (
            current_dsm_spatial_case != "VALID"
            and current_dsm_spatial_case != replay_of.current_dsm_spatial_case
        ):
            raise ValueError("replay fixture cannot change its sealed DSM spatial metadata")
        v2_dsm_only = replay_of.v2_dsm_only
        include_third_epoch = replay_of.third is not None
        failed_checkpoint_current = replay_of.failed_checkpoint_current
        failed_checkpoint_baseline = replay_of.failed_checkpoint_baseline
        passed_and_failed_checkpoint_current = replay_of.passed_and_failed_checkpoint_current
        passed_checkpoint_epochs = replay_of.passed_checkpoint_epochs
        real_inspection = replay_of.real_inspection
        malformed_current_dsm = replay_of.malformed_current_dsm
        current_dsm_spatial_case = replay_of.current_dsm_spatial_case
        organization_id = replay_of.organization_id
        retained_policy_records = replay_of._retained_policy_records
        retained_contexts = replay_of._retained_contexts
    elif v2_dsm_only is None:
        v2_dsm_only = False
    if organization_id is None:
        organization_id = "org-a"
    if organization_id != "org-a" and not v2_dsm_only:
        raise ValueError("non-default organization fixture requires the V2 DSM-only fixture")
    if include_third_epoch is None:
        include_third_epoch = False
    if include_third_epoch and not v2_dsm_only:
        raise ValueError("third epoch reuse requires the V2 DSM-only fixture")
    if (
        failed_checkpoint_current
        or failed_checkpoint_baseline
        or passed_and_failed_checkpoint_current
        or passed_checkpoint_epochs
    ) and not v2_dsm_only:
        raise ValueError("checkpoint evaluation requires the V2 DSM-only fixture")
    if set(passed_checkpoint_epochs) - {"BASELINE", "CURRENT"}:
        raise ValueError("passed checkpoint epochs must be BASELINE and/or CURRENT")
    if len(set(passed_checkpoint_epochs)) != len(passed_checkpoint_epochs):
        raise ValueError("passed checkpoint epochs must be unique")
    if passed_checkpoint_epochs and (
        failed_checkpoint_current
        or failed_checkpoint_baseline
        or passed_and_failed_checkpoint_current
    ):
        raise ValueError("passed and failed checkpoint fixture modes cannot be combined")
    if real_inspection and not v2_dsm_only:
        raise ValueError("real inspection integration requires the V2 DSM-only fixture")
    if malformed_current_dsm and not real_inspection:
        raise ValueError("malformed DSM fixture requires real byte inspection")
    if current_dsm_spatial_case not in {
        "VALID",
        "MISSING_VERTICAL_REFERENCE",
        "HORIZONTAL_CRS_MISMATCH",
        "NON_OVERLAPPING_GRID",
        "ROTATED_OVERLAPPING_GRID",
        "OVERLAPPING_CURRENT_NODATA_CELL",
    }:
        raise ValueError("unsupported current DSM spatial case")
    if current_dsm_spatial_case != "VALID" and not (v2_dsm_only and real_inspection):
        raise ValueError("spatial DSM fixture variants require real V2 byte inspection")
    if current_dsm_spatial_case != "VALID" and malformed_current_dsm:
        raise ValueError("spatial DSM variants cannot also be malformed")
    now = datetime.now(UTC).replace(microsecond=0)
    storage = LoopbackObjectStorage()
    policy_authority = _RetainedPolicyAuthority()
    context_authority = _RetainedEvidenceContextAuthority(now)
    for record in retained_policy_records:
        policy_authority.add(record)
    for context in retained_contexts:
        context_authority.add(context)
    workflow, _catalog, envelope, _catalog_authority = _workflow(
        tmp_path,
        now=now,
        policy_authority=policy_authority,
        context_authority=context_authority,
        organization_id=organization_id,
    )
    operator = Principal(
        principal_id="analysis-local-operator",
        kind=PrincipalKind.OPERATOR,
        role=Role.ADMIN,
        device_id=None,
        organization_id=organization_id,
    )
    worker = Principal(
        principal_id="analysis-local-worker",
        kind=PrincipalKind.ANALYSIS_WORKER,
        role=None,
        device_id=None,
        organization_id=organization_id,
    )
    validation_worker = Principal(
        principal_id="analysis-local-validation-worker",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id=organization_id,
    )
    viewer = Principal(
        principal_id="analysis-local-viewer",
        kind=PrincipalKind.OPERATOR,
        role=Role.VIEWER,
        device_id=None,
        organization_id="org-a",
    )
    mcp_client = Principal(
        principal_id="analysis-local-mcp-client",
        kind=PrincipalKind.ANALYSIS_MCP_CLIENT,
        role=None,
        device_id=None,
        organization_id=organization_id,
        allowed_site_ids=frozenset({"site-a"}),
        allowed_work_area_ids=frozenset({"wa-site-a-0001"}),
    )
    mcp_other_area = Principal(
        principal_id="analysis-local-mcp-other-area-client",
        kind=PrincipalKind.ANALYSIS_MCP_CLIENT,
        role=None,
        device_id=None,
        organization_id=organization_id,
        allowed_site_ids=frozenset({"site-a"}),
        allowed_work_area_ids=frozenset({"wa-site-a-9999"}),
    )
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_OPERATOR_TOKEN.encode()).hexdigest(),
                principal=operator,
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_WORKER_TOKEN.encode()).hexdigest(), principal=worker
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_VALIDATION_WORKER_TOKEN.encode()).hexdigest(),
                principal=validation_worker,
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_VIEWER_TOKEN.encode()).hexdigest(), principal=viewer
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_MCP_CLIENT_TOKEN.encode()).hexdigest(),
                principal=mcp_client,
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_MCP_OTHER_AREA_TOKEN.encode()).hexdigest(),
                principal=mcp_other_area,
            ),
        ]
    )
    # Local import: test_external_analysis_http_integration imports shared
    # builders from this fixture module (P3 Task 5 relocation) — top-level
    # import here would be circular.
    from test_external_analysis_http_integration import (  # noqa: PLC0415
        _assemble_local_analysis_app,
        _local_graph_config,
    )

    local_graph_config = _local_graph_config(envelope)
    if callable(analysis_activation):
        analysis_activation = analysis_activation(local_graph_config, worker)
    app, opened = _assemble_local_analysis_app(
        tmp_path,
        workflow=workflow,
        storage=storage,
        config=local_graph_config,
        auth_registry=registry,
        analysis_activation=analysis_activation,
    )
    assert isinstance(app, FastAPI)
    try:
        if replay_of is not None:
            return LocalAnalysisApiFixture(
                app=app,
                opened=opened,
                storage=storage,
                site_id=replay_of.site_id,
                work_area_id=replay_of.work_area_id,
                organization_id=replay_of.organization_id,
                baseline=replay_of.baseline.model_copy(deep=True),
                current=replay_of.current.model_copy(deep=True),
                third=(replay_of.third.model_copy(deep=True) if replay_of.third else None),
                v2_dsm_only=replay_of.v2_dsm_only,
                failed_checkpoint_current=replay_of.failed_checkpoint_current,
                failed_checkpoint_baseline=replay_of.failed_checkpoint_baseline,
                passed_and_failed_checkpoint_current=(
                    replay_of.passed_and_failed_checkpoint_current
                ),
                passed_checkpoint_epochs=replay_of.passed_checkpoint_epochs,
                synthetic_inspection_report_digests=(
                    replay_of.synthetic_inspection_report_digests
                ),
                synthetic_epoch_chronology=replay_of.synthetic_epoch_chronology,
                synthetic_policy_admitted_at=replay_of.synthetic_policy_admitted_at,
                _current_revision=replay_of._current_revision,
                _current_subject=replay_of._current_subject,
                _baseline_revision=replay_of._baseline_revision,
                _baseline_subject=replay_of._baseline_subject,
                _third_revision=replay_of._third_revision,
                _third_subject=replay_of._third_subject,
                _inspection_policy=replay_of._inspection_policy,
                _inspector_manifest=replay_of._inspector_manifest,
                real_inspection=replay_of.real_inspection,
                malformed_current_dsm=replay_of.malformed_current_dsm,
                current_dsm_spatial_case=replay_of.current_dsm_spatial_case,
                _fixture_now=replay_of._fixture_now,
                _operator_token=_OPERATOR_TOKEN,
                _worker_token=_WORKER_TOKEN,
                _validation_worker_token=_VALIDATION_WORKER_TOKEN,
                _viewer_token=_VIEWER_TOKEN,
                _mcp_client_token=_MCP_CLIENT_TOKEN,
                _mcp_other_area_token=_MCP_OTHER_AREA_TOKEN,
                _context_authority=context_authority,
                _retained_policy_records=policy_authority.retained_records(),
                _retained_contexts=context_authority.retained_contexts(),
            )
        site_registration = app.state.site_store.register(
            "site-a",
            "Local Analysis API fixture site",
            SiteFrame(
                crs="EPSG:5186",
                vertical_datum="EGM96 height",
                unit="meter",
                transform_version="fixture-v1",
            ),
            organization_id=organization_id,
            ai_egress_allowed=ai_egress_allowed,
            actor=operator.principal_id,
            now=now - timedelta(minutes=30),
        )
        assert (
            site_registration.record is not None
            or app.state.site_store.get_scoped("site-a", organization_id) is not None
        )
        transform = from_origin(_ORIGIN_X, _ORIGIN_Y, 0.1, 0.1)
        polygon = {
            "type": "Polygon",
            "coordinates": [
                [
                    [_ORIGIN_X - 0.01, _ORIGIN_Y + 0.01],
                    [_ORIGIN_X - 0.01, _ORIGIN_Y - 0.2],
                    [_ORIGIN_X + 0.2, _ORIGIN_Y - 0.2],
                    [_ORIGIN_X + 0.2, _ORIGIN_Y + 0.01],
                    [_ORIGIN_X - 0.01, _ORIGIN_Y + 0.01],
                ]
            ],
        }
        area_result = app.state.work_area_store.register(
            "site-a",
            name="Local Analysis fixture area",
            polygon=polygon,
            crs="EPSG:5186",
            supersedes=None,
            actor=operator.principal_id,
            now=now - timedelta(minutes=29),
        )
        assert area_result.work_area is not None
        area = area_result.work_area
        orders = app.state.observation_work_order_store
        execution_mode = (
            ObservationWorkOrderExecutionMode.EXTERNAL_RECONSTRUCTION
            if v2_dsm_only
            else ObservationWorkOrderExecutionMode.MANAGED_ACQUISITION
        )

        def create_observation_order(label: str, created_at: datetime) -> Any:
            return orders.create_work_order(
                organization_id=organization_id,
                site_id="site-a",
                name="Local Analysis " + label,
                work_area_ids=[area.work_area_id],
                schedule_id=None,
                execution_mode=execution_mode,
                idempotency_key=("local-analysis-" + label if v2_dsm_only else None),
                actor=operator.principal_id,
                now=created_at,
            )

        baseline_order = create_observation_order("baseline", now - timedelta(minutes=28))
        current_order = create_observation_order("current", now - timedelta(minutes=27))
        third_order = (
            create_observation_order("third", now - timedelta(minutes=26))
            if include_third_epoch
            else None
        )
        baseline_bytes = _geotiff_bytes(np.full((2, 2), 100.0), transform=transform)
        current_values = np.array([[101.0, 99.0], [100.0, 100.0]])
        if malformed_current_dsm:
            current_bytes = b"malformed-current-dsm"
        elif current_dsm_spatial_case == "VALID":
            current_bytes = _geotiff_bytes(current_values, transform=transform)
        else:
            current_crs = {
                "MISSING_VERTICAL_REFERENCE": "EPSG:5186",
                "HORIZONTAL_CRS_MISMATCH": "EPSG:32652+5773",
                "NON_OVERLAPPING_GRID": "EPSG:5186+5773",
                "ROTATED_OVERLAPPING_GRID": "EPSG:5186+5773",
                "OVERLAPPING_CURRENT_NODATA_CELL": "EPSG:5186+5773",
            }[current_dsm_spatial_case]
            current_transform = transform
            if current_dsm_spatial_case == "NON_OVERLAPPING_GRID":
                current_transform = from_origin(
                    _ORIGIN_X + 1000.0, _ORIGIN_Y + 1000.0, 0.1, 0.1
                )
            elif current_dsm_spatial_case == "ROTATED_OVERLAPPING_GRID":
                current_transform = Affine(
                    0.1,
                    0.025,
                    _ORIGIN_X - 0.01,
                    0.025,
                    -0.1,
                    _ORIGIN_Y + 0.01,
                )
            current_nodata = None
            if current_dsm_spatial_case == "OVERLAPPING_CURRENT_NODATA_CELL":
                current_values[0, 0] = -9999.0
                current_nodata = -9999.0
            current_bytes = _geotiff_with_measured_spatial_case(
                current_values,
                transform=current_transform,
                crs=current_crs,
                nodata=current_nodata,
            )
        third_bytes = _geotiff_bytes(
            np.array([[103.0, 97.0], [100.0, 100.0]]), transform=transform
        )
        if v2_dsm_only:
            with TestClient(app) as ingress_client:
                baseline_revision, baseline_subject = _register_and_seal_v2_dsm(
                    ingress_client,
                    app,
                    baseline_order,
                    "analysis-local-baseline",
                    start=now - timedelta(minutes=20),
                    end=now - timedelta(minutes=15),
                    storage=storage,
                    dsm_bytes=baseline_bytes,
                    organization_id=organization_id,
                )
                current_revision, current_subject = _register_and_seal_v2_dsm(
                    ingress_client,
                    app,
                    current_order,
                    "analysis-local-current",
                    start=now - timedelta(minutes=10),
                    end=now - timedelta(minutes=5),
                    storage=storage,
                    dsm_bytes=current_bytes,
                    organization_id=organization_id,
                )
                if third_order is not None:
                    third_revision, third_subject = _register_and_seal_v2_dsm(
                        ingress_client,
                        app,
                        third_order,
                        "analysis-local-third",
                        start=now - timedelta(minutes=4),
                        end=now - timedelta(minutes=2),
                        storage=storage,
                        dsm_bytes=third_bytes,
                        organization_id=organization_id,
                    )
                else:
                    third_revision, third_subject = None, None
        else:
            baseline_revision, baseline_subject = _sealed_revision(
                app,
                baseline_order,
                "analysis-local-baseline",
                start=now - timedelta(minutes=20),
                end=now - timedelta(minutes=15),
                storage=storage,
                dsm_bytes=baseline_bytes,
            )
            current_revision, current_subject = _sealed_revision(
                app,
                current_order,
                "analysis-local-current",
                start=now - timedelta(minutes=10),
                end=now - timedelta(minutes=5),
                storage=storage,
                dsm_bytes=current_bytes,
            )
            if third_order is not None:
                third_revision, third_subject = _sealed_revision(
                    app,
                    third_order,
                    "analysis-local-third",
                    start=now - timedelta(minutes=4),
                    end=now - timedelta(minutes=2),
                    storage=storage,
                    dsm_bytes=third_bytes,
                )
            else:
                third_revision, third_subject = None, None
        epoch_pairs = [
            (baseline_revision, baseline_subject),
            (current_revision, current_subject),
        ]
        if third_revision is not None and third_subject is not None:
            epoch_pairs.append((third_revision, third_subject))
        policy_admitted_at = datetime.now(UTC) if include_third_epoch else now
        inspector_manifest = None
        if real_inspection:
            from ksi_processing_controller.external_geotiff_profile import (
                external_geotiff_profile_digest_v1,
            )
            from test_external_inspector_container_entrypoint import _manifest

            inspector_manifest = _manifest(envelope)
            template = ExternalValidationPolicyV1(
                policy_id="external-geotiff-v1",
                version=1,
                status=PolicyStatus.ACTIVE,
                parser_build_digest=inspector_manifest.parser_build_digest,
                grammar_digest=external_geotiff_profile_digest_v1(),
                resource_envelope=envelope,
                resource_envelope_digest=envelope.resource_envelope_digest,
                authority_record_digest=_digest("unbound-real-inspector-authority"),
                inspection_rule_ids=("EXTERNAL_GEOTIFF_MEASURED_V1",),
                evidence_rule_ids=("CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",),
                compatibility_mapping_digests=(CompatibilityRuleDescriptorV1().canonical_digest(),),
                synthetic_test_only=False,
            ).sealed()
            authority_record = PolicyAuthorityRecord(
                policy_id=template.policy_id,
                policy_version=template.version,
                authorized_policy_body_digest=authorized_policy_body_digest(template),
                permitted_subjects=tuple(subject for _revision, subject in epoch_pairs),
                permitted_uses=("INSPECTION", "EVIDENCE", "RELATIVE_VOLUME"),
                authorized_actor_ids=("policy-admin",),
                active_from=policy_admitted_at - timedelta(hours=1),
                active_until=policy_admitted_at + timedelta(hours=1),
                synthetic_test_only=False,
            ).sealed()
            assert authority_record.digest is not None
            policy_authority.add(authority_record)
            inspection_policy = template.model_copy(
                update={
                    "authority_record_digest": authority_record.digest,
                    "policy_digest": None,
                },
                deep=True,
            ).sealed()
            admitted = app.state.external_validation_policy_registry.admit(
                inspection_policy, actor="policy-admin", now=policy_admitted_at
            )
            assert admitted.status.value == "ADMITTED"
        else:
            inspection_policy = _admit_policy(
                app,
                subjects=tuple(subject for _revision, subject in epoch_pairs),
                envelope=envelope,
                authority=policy_authority,
                now=policy_admitted_at,
            )
        inspection_resource_envelope = inspection_policy.resource_envelope
        assert inspection_resource_envelope is not None
        vertical = ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")
        horizontal_digest = _digest(
            CRS.from_epsg(5186).to_wkt(version="WKT2_2019", pretty=False, output_axis_rule=True)
        )
        inspection_report_digests: list[str] = []
        epoch_chronology: list[tuple[datetime, datetime, datetime, datetime]] = []
        inspection_spacing = timedelta(
            seconds=inspection_resource_envelope.lease_duration_seconds + 1
        )
        for index, (revision, subject) in enumerate(epoch_pairs):
            if real_inspection:
                capture_start = revision.submission.input_declaration.capture_started_at
                capture_end = revision.submission.input_declaration.capture_ended_at
                if capture_start is None or capture_end is None or revision.manifest is None:
                    raise AssertionError(
                        "fixture epoch must have capture bounds and a sealed manifest"
                    )
                epoch_chronology.append(
                    (capture_start, capture_end, revision.manifest.observed_at, policy_admitted_at)
                )
                continue
            if include_third_epoch:
                if index:
                    time.sleep(inspection_spacing.total_seconds())
                inspection_now = datetime.now(UTC)
            else:
                # Preserve the original two-epoch fixture clock exactly for V1 and V2.
                inspection_now = now
            report = _inspect(
                app,
                revision=revision,
                subject=subject,
                policy=inspection_policy,
                now=inspection_now,
                transform=tuple(transform)[:6],
                vertical_reference=vertical,
                observed_crs_digest=horizontal_digest,
            )
            # This synthetic helper records a Core report; it does not read or
            # independently validate the underlying artifact bytes.
            inspection_report_digests.append(report.report_digest)
            capture_start = revision.submission.input_declaration.capture_started_at
            capture_end = revision.submission.input_declaration.capture_ended_at
            if capture_start is None or capture_end is None or revision.manifest is None:
                raise AssertionError("fixture epoch must have capture bounds and a sealed manifest")
            epoch_chronology.append(
                (capture_start, capture_end, revision.manifest.observed_at, report.reported_at)
            )
            if not v2_dsm_only:
                _validate_evidence(
                    app,
                    revision=revision,
                    subject=subject,
                    policy=inspection_policy,
                    context_authority=context_authority,
                    now=inspection_now,
                    storage=storage,
                    label="analysis-local-" + subject.submission_id,
                    organization_id=organization_id,
                )
            elif failed_checkpoint_baseline and subject == baseline_subject:
                # This test helper deliberately records a failed Core verdict
                # from synthetic checkpoint metrics; it is not field survey evidence.
                rejected = _validate_evidence(
                    app,
                    revision=revision,
                    subject=subject,
                    policy=inspection_policy,
                    context_authority=context_authority,
                    now=inspection_now,
                    storage=storage,
                    label="analysis-local-baseline-rejected-checkpoint",
                    checkpoint_count=1,
                    organization_id=organization_id,
                )
                assert rejected.core_verdict.value == "REJECTED"
                assert rejected.core_reason == "CHECKPOINT_COUNT_OUT_OF_RANGE"
            elif subject == baseline_subject and "BASELINE" in passed_checkpoint_epochs:
                # Generated checkpoint bytes exercise Core validation without
                # claiming survey or field accuracy evidence.
                passed = _validate_evidence(
                    app,
                    revision=revision,
                    subject=subject,
                    policy=inspection_policy,
                    context_authority=context_authority,
                    now=inspection_now,
                    storage=storage,
                    label="analysis-local-baseline-passed-checkpoint",
                    checkpoint_count=3,
                    organization_id=organization_id,
                )
                assert passed.core_verdict.value == "VALIDATED"
                assert passed.core_reason is None
            elif subject == current_subject and "CURRENT" in passed_checkpoint_epochs:
                # Generated checkpoint bytes exercise Core validation without
                # claiming survey or field accuracy evidence.
                passed = _validate_evidence(
                    app,
                    revision=revision,
                    subject=subject,
                    policy=inspection_policy,
                    context_authority=context_authority,
                    now=inspection_now,
                    storage=storage,
                    label="analysis-local-current-passed-checkpoint",
                    checkpoint_count=3,
                    organization_id=organization_id,
                )
                assert passed.core_verdict.value == "VALIDATED"
                assert passed.core_reason is None
            elif (failed_checkpoint_current or passed_and_failed_checkpoint_current) and (
                subject == current_subject
            ):
                if passed_and_failed_checkpoint_current:
                    accepted = _validate_evidence(
                        app,
                        revision=revision,
                        subject=subject,
                        policy=inspection_policy,
                        context_authority=context_authority,
                        now=inspection_now,
                        storage=storage,
                        label="analysis-local-current-passed-checkpoint",
                        checkpoint_count=3,
                        organization_id=organization_id,
                    )
                    assert accepted.core_verdict.value == "VALIDATED"
                # This test helper deliberately records a failed Core verdict
                # from synthetic checkpoint metrics; it is not field survey evidence.
                rejected = _validate_evidence(
                    app,
                    revision=revision,
                    subject=subject,
                    policy=inspection_policy,
                    context_authority=context_authority,
                    now=inspection_now,
                    storage=storage,
                    label="analysis-local-current-rejected-checkpoint",
                    checkpoint_count=1,
                    organization_id=organization_id,
                )
                assert rejected.core_verdict.value == "REJECTED"
                assert rejected.core_reason == "CHECKPOINT_COUNT_OUT_OF_RANGE"
        return LocalAnalysisApiFixture(
            app=app,
            opened=opened,
            storage=storage,
            site_id="site-a",
            work_area_id=area.work_area_id,
            organization_id=organization_id,
            baseline=AnalysisObservationSelectorV1(
                work_order_id=baseline_order.work_order_id,
                submission_ref=build_external_reconstruction_submission_ref(
                    organization_id=organization_id,
                    work_order_id=baseline_order.work_order_id,
                    submission_id=baseline_subject.submission_id,
                ),
                revision=baseline_subject.revision,
            ),
            current=AnalysisObservationSelectorV1(
                work_order_id=current_order.work_order_id,
                submission_ref=build_external_reconstruction_submission_ref(
                    organization_id=organization_id,
                    work_order_id=current_order.work_order_id,
                    submission_id=current_subject.submission_id,
                ),
                revision=current_subject.revision,
            ),
            third=(
                AnalysisObservationSelectorV1(
                    work_order_id=third_order.work_order_id,
                    submission_ref=build_external_reconstruction_submission_ref(
                        organization_id=organization_id,
                        work_order_id=third_order.work_order_id,
                        submission_id=third_subject.submission_id,
                    ),
                    revision=third_subject.revision,
                )
                if third_order is not None and third_subject is not None
                else None
            ),
            v2_dsm_only=v2_dsm_only,
            failed_checkpoint_current=failed_checkpoint_current,
            failed_checkpoint_baseline=failed_checkpoint_baseline,
            passed_and_failed_checkpoint_current=passed_and_failed_checkpoint_current,
            passed_checkpoint_epochs=passed_checkpoint_epochs,
            synthetic_inspection_report_digests=tuple(inspection_report_digests),
            synthetic_epoch_chronology=tuple(epoch_chronology),
            synthetic_policy_admitted_at=policy_admitted_at,
            _current_revision=current_revision,
            _current_subject=current_subject,
            _baseline_revision=baseline_revision,
            _baseline_subject=baseline_subject,
            _third_revision=third_revision,
            _third_subject=third_subject,
            _inspection_policy=inspection_policy,
            _inspector_manifest=inspector_manifest,
            real_inspection=real_inspection,
            malformed_current_dsm=malformed_current_dsm,
            current_dsm_spatial_case=current_dsm_spatial_case,
            _fixture_now=now,
            _operator_token=_OPERATOR_TOKEN,
            _worker_token=_WORKER_TOKEN,
            _validation_worker_token=_VALIDATION_WORKER_TOKEN,
            _viewer_token=_VIEWER_TOKEN,
            _mcp_client_token=_MCP_CLIENT_TOKEN,
            _mcp_other_area_token=_MCP_OTHER_AREA_TOKEN,
            _context_authority=context_authority,
            _retained_policy_records=policy_authority.retained_records(),
            _retained_contexts=context_authority.retained_contexts(),
        )
    except BaseException:
        for journal in reversed(opened):
            journal.close()
        raise


__all__ = ["LocalAnalysisApiFixture", "LoopbackObjectStorage", "build_local_analysis_api_fixture"]

_KNOWN_UNCERTAINTY_NOTE = "Independent validated checkpoint RMSE was used for both epochs."
_EPOCH_RSS_UNCERTAINTY_M3 = 10.0 * math.hypot(0.1, 0.1)


def _restarted_policy_authority(source: _RetainedPolicyAuthority) -> _RetainedPolicyAuthority:
    restarted = _RetainedPolicyAuthority()
    for record in source.retained_records():
        restarted.add(record)
    return restarted


# ── Retired-helper inlines (P3 Task 5): pure GeoTIFF builders ─────────
# Copied verbatim from tests/contract/test_external_analysis_execution_integration.py
# (archived blob-identical with the legacy harness of its single test).


_ORIGIN_X = 200_000.0


_ORIGIN_Y = 550_000.0


def _geotiff_bytes(values: np.ndarray, *, transform: Affine | None = None) -> bytes:
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=values.shape[0],
            width=values.shape[1],
            count=1,
            dtype="float64",
            crs=CRS.from_user_input("EPSG:5186+5773"),
            transform=transform or from_origin(_ORIGIN_X, _ORIGIN_Y, 1.0, 1.0),
        ) as dataset:
            dataset.write(values, 1)
        return memory.read()
