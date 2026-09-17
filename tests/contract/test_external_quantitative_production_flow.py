"""Real Core participant proof for the externally-produced quantitative path.

Only object bytes and independently retained authority records are local test
fixtures.  The test never seeds a Core authority, monkeypatches a participant,
or uses a permissive authority provider.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from ksi_core.acquisition import observation_epoch_id
from ksi_core.app_assembly import assemble_app
from ksi_core.auth import AuthRegistry, Principal, PrincipalKind, PrincipalTokenRecord, Role
from ksi_core.domains.external.quantity.external_single_volume_authority import (
    SingleVolumeCompatibilityRuleDescriptorV1,
)
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
from ksi_core.external_reconstruction import build_external_reconstruction_submission_ref
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
from ksi_domain.canonical_json import canonical_json_bytes
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
from ksi_event_contracts.external_single_volume import (
    ExternalSingleVolumeMeasurementPayloadV1,
    ExternalSingleVolumeMetricsV1,
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


def _workflow_material(
    path: Path, *, now: datetime
) -> tuple[ExternalQuantitativeCatalogAuthorityRecord, ResourceEnvelopeV1, Path]:
    """Write owner-private catalog/config bytes without selecting an authority port."""
    envelope = _envelope()
    body: dict[str, Any] = {
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


def _signed_provider_config(
    path: Path,
    *,
    now: datetime,
    catalog_authority: ExternalQuantitativeCatalogAuthorityRecord,
) -> tuple[Path, Ed25519PrivateKey]:
    """Create test-owned signing material; it is never release authority."""
    assert catalog_authority.digest is not None
    signer = Ed25519PrivateKey.generate()
    public_key = path / "authority-bundle.pem"
    public_key.write_bytes(
        signer.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    os.chmod(public_key, 0o600)
    _write_private(
        path / "authority-keys.json",
        {
            "version": "external-authority-key-registry.v1",
            "keys": [
                {
                    "keyId": "test-authority-key-1",
                    "role": "AUTHORITY_BUNDLE",
                    "algorithm": "Ed25519",
                    "status": "ACTIVE",
                    "publicKeyFile": public_key.name,
                    "notBefore": (now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                    "notAfter": (now + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
                }
            ],
        },
    )
    snapshot_path = path / "authority-snapshot.json"
    _write_signed_provider_snapshot(
        snapshot_path,
        signer,
        {
            "version": "external-authority-provider-snapshot.v1",
            "organizationId": "org-a",
            "sequence": 1,
            "previousSnapshotDigest": None,
            "issuedAt": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
            "validUntil": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "keyId": "test-authority-key-1",
            "catalogAuthorities": {
                "records": [catalog_authority.event_payload()],
                "currentDigests": [catalog_authority.digest],
            },
            "policyAuthorities": {"records": [], "currentDigests": []},
            "evidenceContexts": {"records": [], "currentDigests": []},
            "quantitativeAdministration": {"actions": []},
        },
    )
    config_path = path / "external-authority-provider.json"
    _write_private(
        config_path,
        {
            "version": "external-authority-provider-config.v1",
            "organizationId": "org-a",
            "keyRegistryPath": str(path / "authority-keys.json"),
            "snapshotPath": str(snapshot_path),
            "catalogAdministrationActorId": "catalog-admin",
            "leaseTtlSeconds": 10,
            "deadlineAfterIssueSeconds": 60,
            "maxAttempts": 2,
            "maxActiveRequestsPerOrganization": 2,
        },
    )
    return config_path, signer


def _write_signed_provider_snapshot(
    path: Path, signer: Ed25519PrivateKey, snapshot: dict[str, object]
) -> str:
    signed = canonical_json_bytes(
        {
            "domain": "ksi.external-authority-provider-snapshot.v1",
            "snapshot": snapshot,
        }
    )
    _write_private(
        path,
        {
            **snapshot,
            "signature": base64.b64encode(signer.sign(signed)).decode("ascii"),
        },
    )
    return _digest(signed)


def _replace_signed_provider_snapshot(
    path: Path, signer: Ed25519PrivateKey, changes: dict[str, object]
) -> str:
    current = json.loads(path.read_text(encoding="utf-8"))
    snapshot = {key: value for key, value in current.items() if key != "signature"} | changes
    return _write_signed_provider_snapshot(path, signer, snapshot)


def _signed_policy_admission(
    *,
    subjects: tuple[SealedExternalSubjectV1, SealedExternalSubjectV1],
    envelope: ResourceEnvelopeV1,
    now: datetime,
) -> tuple[ExternalValidationPolicyV1, PolicyAuthorityRecord, dict[str, object]]:
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
        compatibility_mapping_digests=(
            CompatibilityRuleDescriptorV1().canonical_digest(),
            SingleVolumeCompatibilityRuleDescriptorV1().canonical_digest(),
        ),
        synthetic_test_only=False,
    ).sealed()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=subjects,
        permitted_uses=("INSPECTION", "EVIDENCE", "RELATIVE_VOLUME", "SINGLE_VOLUME"),
        authorized_actor_ids=("policy-admin",),
        active_from=now - timedelta(hours=1),
        active_until=now + timedelta(hours=1),
        synthetic_test_only=False,
    ).sealed()
    assert authority.digest is not None
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    return (
        policy,
        authority,
        {
            "actionId": "signed-provider-admit-policy",
            "kind": "ADMIT_POLICY",
            "effectiveAt": now.isoformat().replace("+00:00", "Z"),
            "actorId": "policy-admin",
            "policy": policy.model_dump(by_alias=True, mode="json"),
        },
    )


def _workflow(
    path: Path,
    *,
    now: datetime,
    policy_authority: _RetainedPolicyAuthority,
    context_authority: _RetainedEvidenceContextAuthority,
) -> Any:
    """Load a protected real workflow config backed by retained authority records."""
    authority, envelope, config_path = _workflow_material(path, now=now)
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


def _restarted_policy_authority(source: _RetainedPolicyAuthority) -> _RetainedPolicyAuthority:
    restarted = _RetainedPolicyAuthority()
    for record in source.retained_records():
        restarted.add(record)
    return restarted


def _assemble(
    path: Path,
    workflow: Any,
    storage: _LocalObjectStorage,
    *,
    auth_registry: AuthRegistry | None = None,
) -> tuple[Any, list[DurableJournal]]:
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
        auth_registry=auth_registry or AuthRegistry([]),
        evidence_storage=storage,
        mission_signing_key=Ed25519PrivateKey.generate(),
        mission_signing_key_id="test-key",
        external_result_workflow=workflow,
    )
    return app, opened


_OPERATOR_TOKEN = "single-volume-operator"  # noqa: S105 - deterministic test token
_WORKER_TOKEN = "single-volume-worker"  # noqa: S105 - deterministic test token


def _worker_principal() -> Principal:
    return Principal(
        principal_id="worker-principal",
        kind=PrincipalKind.PROCESSING_WORKER,
        role=None,
        device_id=None,
        organization_id="org-a",
    )


def _assert_single_report_reads(
    client: TestClient, report_ref: str, *, expected_digest: str | None
) -> str:
    """The merged site history and the exact single report both serve the sealed report."""

    headers = {"Authorization": f"Bearer {_OPERATOR_TOKEN}"}
    history = client.get("/v1/sites/site-a/external-volume-reports", headers=headers)
    assert history.status_code == 200, history.text
    rows = [item for item in history.json()["items"] if item["reportRef"] == report_ref]
    assert len(rows) == 1, history.text
    assert rows[0]["state"] == "AVAILABLE", rows[0]
    assert rows[0]["result"]["kind"] == "EXTERNAL_SINGLE_VOLUME"
    exact = client.get(f"/v1/external-single-volume-reports/{report_ref}", headers=headers)
    assert exact.status_code == 200, exact.text
    digest = exact.json()["report"]["reportDigest"]
    assert isinstance(digest, str) and digest.startswith("sha256:")
    assert rows[0]["result"]["reportDigest"] == digest
    if expected_digest is not None:
        assert digest == expected_digest
    return digest


def _operator_registry() -> AuthRegistry:
    return AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_OPERATOR_TOKEN.encode()).hexdigest(),
                principal=_principal(),
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(_WORKER_TOKEN.encode()).hexdigest(),
                principal=_worker_principal(),
            ),
        ]
    )


def _request_single_volume_over_http(
    app: Any, *, work_order_id: str, submission_id: str, zone_id: str
) -> dict[str, Any]:
    submission_ref = build_external_reconstruction_submission_ref(
        organization_id="org-a", work_order_id=work_order_id, submission_id=submission_id
    )
    path = (
        f"/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/"
        f"{submission_ref}/revisions/1/use-decisions"
    )
    headers = {"Authorization": f"Bearer {_OPERATOR_TOKEN}"}
    client = TestClient(app)
    response = client.post(
        path + "/single-volume",
        json={"zoneId": zone_id},
        headers={**headers, "Idempotency-Key": "signed-provider-single-volume"},
    )
    assert response.status_code == 201, response.text
    decision = response.json()["decision"]
    retry = client.post(
        path + "/single-volume",
        json={"zoneId": zone_id},
        headers={**headers, "Idempotency-Key": "signed-provider-single-volume"},
    )
    assert retry.status_code == 201 and retry.json()["decision"] == decision
    conflict = client.post(
        path + "/single-volume",
        json={"zoneId": "another-zone"},
        headers={**headers, "Idempotency-Key": "signed-provider-single-volume"},
    )
    assert conflict.status_code == 409, conflict.text
    read = client.get(f"{path}/{decision['decisionId']}", headers=headers)
    assert read.status_code == 200 and read.json()["decision"] == decision
    return cast(dict[str, Any], decision)


def _close_journals(journals: list[DurableJournal]) -> None:
    for journal in reversed(journals):
        journal.close()


def _register_signed_provider_site_and_area(app: Any, *, now: datetime) -> Any:
    assert (
        app.state.site_store.register(
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
    registered = app.state.work_area_store.register(
        "site-a",
        name="Signed provider quantitative area",
        polygon=_POLYGON,
        crs="EPSG:5186",
        supersedes=None,
        actor="operator-a",
        now=now - timedelta(minutes=29),
    )
    assert registered.work_area is not None
    return registered.work_area


# Both fixture epochs are Core-VALIDATED with rmse_m=0.1, so the worker must
# report the independent-epoch RSS area bound exactly as the production
# measurement container does (measured area 10 m2).
_KNOWN_UNCERTAINTY_NOTE = "Independent validated checkpoint RMSE was used for both epochs."
_EPOCH_RSS_UNCERTAINTY_M3 = 10.0 * math.hypot(0.1, 0.1)


def _volume_payload(request: Any, execution: Any, *, now: datetime) -> Any:
    return ExternalRelativeVolumeMeasurementPayloadV1(
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
            uncertainty_m3=_EPOCH_RSS_UNCERTAINTY_M3,
            uncertainty_note=_KNOWN_UNCERTAINTY_NOTE,
        ),
    )


def _submission(order: Any, label: str, *, start: datetime, end: datetime) -> Any:
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


def _sealed_revision(
    app: Any,
    order: Any,
    label: str,
    *,
    start: datetime,
    end: datetime,
    storage: Any,
) -> Any:
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


def _inspection_report(
    request: Any,
    policy: Any,
    subject: Any,
    revision: Any,
    fence: LeaseFence,
    *,
    now: datetime,
) -> Any:
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


def _inspect(app: Any, *, revision: Any, subject: Any, policy: Any, now: datetime) -> Any:
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


def _seal_evidence(
    app: Any,
    *,
    revision: Any,
    subject: Any,
    now: datetime,
    storage: _LocalObjectStorage,
    label: str,
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
    return sealed.item


def _evidence_context(
    item: Any,
    *,
    subject: Any,
    policy: Any,
    now: datetime,
    label: str,
) -> ExternalEvidenceMeasurementContextV1:
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


def _record_evidence_validation(
    app: Any,
    *,
    item: Any,
    now: datetime,
    checkpoint_count: int,
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
) -> Any:
    item = _seal_evidence(
        app,
        revision=revision,
        subject=subject,
        now=now,
        storage=storage,
        label=label,
    )
    context_authority.add(
        _evidence_context(item, subject=subject, policy=policy, now=now, label=label)
    )
    return _record_evidence_validation(app, item=item, now=now, checkpoint_count=checkpoint_count)


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
        activation_restart_policy_authority = _restarted_policy_authority(policy_authority)
        activation_restart_workflow, _, _, activation_catalog_authority = _workflow(
            tmp_path,
            now=now,
            policy_authority=activation_restart_policy_authority,
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
                uncertainty_m3=_EPOCH_RSS_UNCERTAINTY_M3,
                uncertainty_note=_KNOWN_UNCERTAINTY_NOTE,
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
    restarted_policy_authority = _restarted_policy_authority(policy_authority)
    restarted_workflow, _, _, _ = _workflow(
        tmp_path,
        now=now,
        policy_authority=restarted_policy_authority,
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
        with pytest.raises(
            ExternalReobservationExecutionDenied, match="EXTERNAL_RECONSTRUCTION_ONLY"
        ):
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


def test_signed_provider_drives_complete_external_relative_volume_lifecycle(
    tmp_path: Path,
) -> None:
    """Only signed post-seal authority records can drive the real Core lifecycle."""
    from ksi_core.external_authority_provider import load_external_authority_provider

    now = datetime.now(UTC).replace(microsecond=0)
    clock_now = [now]
    storage = _LocalObjectStorage()
    catalog_record, envelope, workflow_config_path = _workflow_material(tmp_path, now=now)
    provider_config_path, signer = _signed_provider_config(
        tmp_path, now=now, catalog_authority=catalog_record
    )
    provider = load_external_authority_provider(provider_config_path, clock=lambda: clock_now[0])
    workflow = load_external_result_workflow_config(
        workflow_config_path,
        participants=provider.participants,
        input_capability_issuer=lambda *_args, **_kwargs: None,
    )
    app, opened = _assemble(tmp_path, workflow, storage, auth_registry=_operator_registry())
    receipts = DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
    try:
        provider.bind_receipt_journal(receipts)
        provider.attach_app(app)
        area = _register_signed_provider_site_and_area(app, now=now)
        orders = app.state.observation_work_order_store
        baseline_order = orders.create_work_order(
            organization_id="org-a",
            site_id="site-a",
            name="Signed provider baseline survey",
            work_area_ids=[area.work_area_id],
            schedule_id=None,
            actor="operator-a",
            now=now - timedelta(minutes=28),
        )
        current_order = orders.create_work_order(
            organization_id="org-a",
            site_id="site-a",
            name="Signed provider current survey",
            work_area_ids=[area.work_area_id],
            schedule_id=None,
            actor="operator-a",
            now=now - timedelta(minutes=27),
        )
        baseline_revision, baseline_subject = _sealed_revision(
            app,
            baseline_order,
            "signed-provider-baseline",
            start=now - timedelta(minutes=20),
            end=now - timedelta(minutes=15),
            storage=storage,
        )
        current_revision, current_subject = _sealed_revision(
            app,
            current_order,
            "signed-provider-current",
            start=now - timedelta(minutes=10),
            end=now - timedelta(minutes=5),
            storage=storage,
        )
        policy, policy_authority, policy_action = _signed_policy_admission(
            subjects=(baseline_subject, current_subject), envelope=envelope, now=now
        )
        first_digest = provider.status()["snapshotDigest"]
        assert isinstance(first_digest, str) and policy_authority.digest is not None
        policy_digest = _replace_signed_provider_snapshot(
            tmp_path / "authority-snapshot.json",
            signer,
            {
                "sequence": 2,
                "previousSnapshotDigest": first_digest,
                "issuedAt": now.isoformat().replace("+00:00", "Z"),
                "policyAuthorities": {
                    "records": [policy_authority.event_payload()],
                    "currentDigests": [policy_authority.digest],
                },
                "quantitativeAdministration": {"actions": [policy_action]},
            },
        )
        assert provider.reload_and_reconcile(now=now)["snapshotDigest"] == policy_digest
        baseline_report = _inspect(
            app, revision=baseline_revision, subject=baseline_subject, policy=policy, now=now
        )
        current_report = _inspect(
            app, revision=current_revision, subject=current_subject, policy=policy, now=now
        )
        baseline_item = _seal_evidence(
            app,
            revision=baseline_revision,
            subject=baseline_subject,
            now=now,
            storage=storage,
            label="signed-provider-baseline",
        )
        current_item = _seal_evidence(
            app,
            revision=current_revision,
            subject=current_subject,
            now=now,
            storage=storage,
            label="signed-provider-current",
        )
        contexts = (
            _evidence_context(
                baseline_item,
                subject=baseline_subject,
                policy=policy,
                now=now,
                label="signed-provider-baseline",
            ),
            _evidence_context(
                current_item,
                subject=current_subject,
                policy=policy,
                now=now,
                label="signed-provider-current",
            ),
        )
        assert all(context.context_digest is not None for context in contexts)
        contexts_digest = _replace_signed_provider_snapshot(
            tmp_path / "authority-snapshot.json",
            signer,
            {
                "sequence": 3,
                "previousSnapshotDigest": policy_digest,
                "issuedAt": now.isoformat().replace("+00:00", "Z"),
                "evidenceContexts": {
                    "records": [
                        context.model_dump(by_alias=True, mode="json") for context in contexts
                    ],
                    "currentDigests": [context.context_digest for context in contexts],
                },
                "quantitativeAdministration": {"actions": [policy_action]},
            },
        )
        assert provider.reload_and_reconcile(now=now)["snapshotDigest"] == contexts_digest
        baseline_evidence = _record_evidence_validation(
            app, item=baseline_item, now=now, checkpoint_count=3
        )
        current_evidence = _record_evidence_validation(
            app, item=current_item, now=now, checkpoint_count=3
        )
        assert catalog_record.digest is not None
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
        assert mapping.mapping_digest is not None
        mapping_action = {
            "actionId": "signed-provider-admit-mapping",
            "kind": "ADMIT_MAPPING",
            "effectiveAt": now.isoformat().replace("+00:00", "Z"),
            "actorId": "catalog-admin",
            "mapping": {
                "mappingRecordDigest": mapping.mapping_digest,
                **mapping.canonical_payload(),
            },
        }
        single = _single_mapping(
            subject=current_subject,
            revision=current_revision,
            report=current_report,
            evidence_record=current_evidence,
            policy=policy,
            area=area,
            now=now,
            catalog_digest=catalog_record.digest,
        )
        single_action = {
            "actionId": "signed-provider-admit-single-mapping",
            "kind": "ADMIT_SINGLE_MAPPING",
            "effectiveAt": now.isoformat().replace("+00:00", "Z"),
            "actorId": "catalog-admin",
            "mapping": {
                "mappingRecordDigest": single.mapping_digest,
                **single.canonical_payload(),
            },
        }
        mapping_digest = _replace_signed_provider_snapshot(
            tmp_path / "authority-snapshot.json",
            signer,
            {
                "sequence": 4,
                "previousSnapshotDigest": contexts_digest,
                "issuedAt": now.isoformat().replace("+00:00", "Z"),
                "quantitativeAdministration": {
                    "actions": [policy_action, mapping_action, single_action]
                },
            },
        )
        assert provider.reload_and_reconcile(now=now)["snapshotDigest"] == mapping_digest
        decision = app.state.external_use_evaluator.request_pair(
            baseline_subject,
            current_subject,
            use="RELATIVE_VOLUME",
            zone_id=area.work_area_id,
            idempotency_key="signed-provider-decision",
            principal=_principal(),
            now=now,
        )
        assert decision.verdict.value == "ELIGIBLE" and decision.decision_digest is not None
        single_decision = _request_single_volume_over_http(
            app,
            work_order_id=current_order.work_order_id,
            submission_id=current_subject.submission_id,
            zone_id=area.work_area_id,
        )
        assert single_decision["contractVersion"] == "external-single-volume-decision.v1"
        assert single_decision["verdict"] == "ELIGIBLE", single_decision
        assert single_decision["zone"]["zoneId"] == area.work_area_id
        assert single_decision["compatibilityMappingDigest"] == single.mapping_digest
        assert single_decision["evidenceRecordDigests"] == [current_evidence.evidence_record_digest]
        active_now = now + timedelta(seconds=1)
        catalog = app.state.external_relative_volume_mapping_authority
        assert isinstance(catalog, ExternalQuantitativeAuthorityCatalog)
        execution = catalog.activate_execution(
            decision_ref=decision.decision_id,
            principal=_principal(),
            current_work_order_id=current_order.work_order_id,
            now=active_now,
        )
        assert execution is not None
        single_client = TestClient(app)
        single_issue = single_client.post(
            f"/v1/observation-work-orders/{current_order.work_order_id}/single-volume-requests",
            headers={
                "Authorization": f"Bearer {_OPERATOR_TOKEN}",
                "Idempotency-Key": "signed-provider-single-volume-issue",
            },
            json={"decisionRef": single_decision["decisionId"]},
        )
        assert single_issue.status_code == 201, single_issue.text
        assert single_issue.json()["verdict"] == "ISSUED", single_issue.text
        single_request_ref = single_issue.json()["request"]["requestRef"]
        assert single_request_ref.startswith("external-single-volume-")
        single_store = app.state.external_single_volume_store
        single_issued_record = single_store.get(single_request_ref, organization_id="org-a")
        assert single_issued_record is not None
        single_claimed = single_store.claim(
            single_request_ref,
            organization_id="org-a",
            principal_id="worker-principal",
            fence=LeaseFence(str(uuid4()), str(uuid4()), 0),
            now=single_issued_record.issued_at,
        )
        assert single_claimed.verdict is ExternalRelativeVolumeVerdict.LEASED
        assert single_claimed.fence is not None and single_claimed.record is not None
        single_fence = single_claimed.fence
        single_fence_headers = {
            "X-KSI-Worker-Instance-Id": single_fence.worker_instance_id,
            "X-KSI-Lease-Acquisition-Id": single_fence.lease_acquisition_id,
            "X-KSI-Lease-Generation": str(single_fence.lease_generation),
        }
        single_worker_input = single_client.get(
            f"/v1/internal/external-validation/single-volumes/{single_request_ref}/input",
            headers={"Authorization": f"Bearer {_WORKER_TOKEN}", **single_fence_headers},
        )
        assert single_worker_input.status_code == 200, single_worker_input.text
        assert single_worker_input.json()["verdict"] == "INPUT_READY", single_worker_input.text
        single_input = single_worker_input.json()["input"]
        assert single_input["request"]["contractVersion"] == "external-single-volume-request.v1"
        assert [item["role"] for item in single_input["inputs"]] == [
            "TARGET_DSM",
            "CHECKPOINT_CSV",
        ]
        assert single_input["evidenceRecord"]["measurementPayload"]["rmseM"] == 0.1
        assert (
            single_input["executionPolicy"]["baseSurfaceMethod"]
            == "BOUNDARY_LINEAR_INTERPOLATION_V1"
        )
        assert len(single_input["inputs"]) == 2
        assert all(item["downloadUrl"] for item in single_input["inputs"])
        single_record = single_store.get(single_request_ref, organization_id="org-a")
        assert single_record is not None and single_record.request.request_digest is not None
        single_authority = single_record.authority
        assert single_authority.target_rmse_m == 0.1
        single_measured_area = 40.0
        single_base_roughness = 0.02
        assert single_authority.target_rmse_m is not None
        single_uncertainty = single_measured_area * math.hypot(
            single_base_roughness, single_authority.target_rmse_m
        )
        single_metrics = ExternalSingleVolumeMetricsV1(
            zone_cell_count=40,
            common_valid_cell_count=40,
            zone_area_m2=40.0,
            measured_area_m2=single_measured_area,
            common_valid_fraction=1.0,
            cut_m3=0.0,
            fill_m3=12.0,
            net_m3=12.0,
            threshold_m=single_authority.execution_policy.threshold_m,
            uncertainty_m3=single_uncertainty,
            uncertainty_note=(
                "Independent validated checkpoint RMSE was used for the single epoch."
            ),
            base_roughness_m=single_base_roughness,
            boundary_cell_count=20,
            boundary_sample_count=20,
            boundary_valid_fraction=1.0,
        )
        assert single_metrics.threshold_m == 0.0
        assert single_metrics.common_valid_fraction >= 0.8
        assert single_metrics.boundary_valid_fraction >= 0.5
        assert single_metrics.zone_cell_count <= single_authority.maximum_zone_cell_count
        assert single_metrics.zone_area_m2 <= single_authority.maximum_zone_area_m2
        single_payload = ExternalSingleVolumeMeasurementPayloadV1(
            request_digest=single_record.request.request_digest,
            decision_digest=single_authority.decision_digest,
            target_dsm_digest=single_authority.target.observed_sha256,
            zone_snapshot_digest=single_authority.zone_snapshot.canonical_digest(),
            execution_policy_digest=single_authority.execution_policy.canonical_digest(),
            algorithm_build_digest=single_authority.execution_policy.algorithm_build_digest,
            config_digest=single_authority.execution_policy.config_digest,
            metrics=single_metrics,
        )
        single_report_response = single_client.post(
            f"/v1/internal/external-validation/single-volumes/{single_request_ref}/report",
            headers={"Authorization": f"Bearer {_WORKER_TOKEN}", **single_fence_headers},
            json={
                "payload": single_payload.model_dump(by_alias=True, mode="json"),
                "computedAt": single_record.issued_at.isoformat().replace("+00:00", "Z"),
            },
        )
        assert single_report_response.status_code == 201, single_report_response.text
        single_report_ref = single_report_response.json()["request"]["reportRef"]
        assert single_report_ref.startswith("external-single-volume-report-")
        single_request_digest = single_record.request.request_digest
        single_report_digest = _assert_single_report_reads(
            single_client, single_report_ref, expected_digest=None
        )
        _close_journals(opened)
        opened = []
        receipts.close()

        clock_now[0] = active_now
        provider = load_external_authority_provider(
            provider_config_path, clock=lambda: clock_now[0]
        )
        workflow = load_external_result_workflow_config(
            workflow_config_path,
            participants=provider.participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
        )
        app, opened = _assemble(tmp_path, workflow, storage, auth_registry=_operator_registry())
        receipts = DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
        provider.bind_receipt_journal(receipts)
        provider.attach_app(app)
        replayed_single = app.state.external_use_decision_store.get_scoped(
            single_decision["decisionId"], principal=_principal(), site_id="site-a"
        )
        assert replayed_single is not None
        assert replayed_single.decision_digest == single_decision["decisionDigest"]
        issued = app.state.external_relative_volume_store.issue(
            principal=_principal(),
            current_work_order_id=current_order.work_order_id,
            decision_ref=decision.decision_id,
            idempotency_key="signed-provider-volume",
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
        report = app.state.external_relative_volume_store.record_observed_report(
            request.request_id,
            organization_id="org-a",
            principal_id="volume-worker",
            fence=leased.fence,
            observed=ExternalRelativeVolumeObservedReportInput(
                payload=_volume_payload(request, execution, now=active_now), computed_at=active_now
            ),
            now=active_now,
        )
        assert report.record is not None and report.record.report is not None
        report_ref = report.record.report.report_id
        single_resolved = app.state.external_single_volume_store.resolve_historical_report_ref(
            single_report_ref, organization_id="org-a", now=active_now
        )
        assert single_resolved is not None
        assert single_resolved.request.request_digest == single_request_digest
        assert single_resolved.report.report_id == single_report_ref
        assert (
            app.state.external_result_read_projector.single_volumes
            is app.state.external_single_volume_store
        )
        _assert_single_report_reads(
            TestClient(app), single_report_ref, expected_digest=single_report_digest
        )
        _close_journals(opened)
        opened = []
        receipts.close()

        provider = load_external_authority_provider(
            provider_config_path, clock=lambda: clock_now[0]
        )
        workflow = load_external_result_workflow_config(
            workflow_config_path,
            participants=provider.participants,
            input_capability_issuer=lambda *_args, **_kwargs: None,
        )
        app, opened = _assemble(tmp_path, workflow, storage, auth_registry=_operator_registry())
        receipts = DurableJournal(tmp_path / "external-authority-provider-receipts.jsonl")
        provider.bind_receipt_journal(receipts)
        provider.attach_app(app)
        service = app.state.external_result_workflow_service
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
            reason="Signed external result requires a planning-only successor.",
            principal=_principal(),
            actor="operator-a",
            now=active_now,
            idempotency_key="signed-provider-proposal",
        )
        approval = service.approve(
            organization_id="org-a",
            proposal_ref=proposal.proposal_ref,
            expected_version=proposal.version,
            principal=_principal(),
            actor="operator-a",
            now=active_now,
            idempotency_key="signed-provider-approval",
        )
        assert approval.planning_binding.report_digest == review.report.report_digest
        with pytest.raises(
            ExternalReobservationExecutionDenied,
            match="EXTERNAL_RECONSTRUCTION_ONLY",
        ):
            app.state.observation_work_order_store.assert_execution_allowed(
                approval.successor_work_order
            )
        resolved = app.state.external_relative_volume_mapping_authority.resolve_for_use(
            baseline=baseline_subject,
            current=current_subject,
            zone_id=area.work_area_id,
            policy=policy,
            now=active_now,
        )
        assert resolved is not None
        revoke_at = active_now + timedelta(seconds=1)
        revoke_action = {
            "actionId": "signed-provider-revoke-policy",
            "kind": "REVOKE_POLICY",
            "effectiveAt": revoke_at.isoformat().replace("+00:00", "Z"),
            "actorId": "policy-admin",
            "policyId": policy.policy_id,
            "policyVersion": policy.version,
        }
        revoked_digest = _replace_signed_provider_snapshot(
            tmp_path / "authority-snapshot.json",
            signer,
            {
                "sequence": 5,
                "previousSnapshotDigest": mapping_digest,
                "issuedAt": revoke_at.isoformat().replace("+00:00", "Z"),
                "quantitativeAdministration": {"actions": [revoke_action]},
            },
        )
        clock_now[0] = revoke_at
        assert provider.reload_and_reconcile(now=revoke_at)["snapshotDigest"] == revoked_digest
        assert not app.state.external_relative_volume_mapping_authority.is_current_for_use(
            resolved, now=revoke_at
        )
        assert (
            app.state.external_relative_volume_store.issue(
                principal=_principal(),
                current_work_order_id=current_order.work_order_id,
                decision_ref=decision.decision_id,
                idempotency_key="signed-provider-revoked-fresh-issue",
                now=revoke_at,
            ).verdict
            is ExternalRelativeVolumeVerdict.AUTHORITY_UNAVAILABLE
        )
    finally:
        receipts.close()
        _close_journals(opened)
