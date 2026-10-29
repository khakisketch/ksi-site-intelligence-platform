"""Core-owned evidence validation keeps trust, worker facts, and verdict separate."""

from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from ksi_core.durable_journal import DurableJournal
from ksi_core.external_authority_currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.external_evidence import EvidenceItem, ExternalEvidenceStore, _view
from ksi_core.external_evidence_validations import (
    EvidenceMeasurementContextAuthorityPort,
    EvidenceValidationInputCapabilityPort,
    EvidenceValidationVerdict,
    ExternalEvidenceValidationInputBinding,
    ExternalEvidenceValidationRecoveryError,
    ExternalEvidenceValidationStore,
    _event_digest,
)
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicyAuthorityPort,
    PolicyAuthorityRecord,
    authorized_policy_body_digest,
)
from ksi_core.leasing import LeaseFence
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    PolicyStatus,
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence import (
    EvidenceIndependence,
    ExternalEvidenceDeclarationV1,
    ExternalEvidenceManifestV1,
    ExternalEvidenceMeasurementPayloadV1,
    ExternalEvidenceRecordV1,
    ExternalEvidenceValidationRequestV1,
    external_evidence_record_wire_dict,
)
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1

NOW = datetime(2026, 9, 9, tzinfo=UTC)


def _digest(marker: str) -> str:
    return f"sha256:{marker * 64}"


def _subject() -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="work-order-a",
        submission_id="submission-a",
        revision=1,
        submission_digest=_digest("a"),
        manifest_digest=_digest("b"),
    )


def _evidence(marker: str = "a") -> EvidenceItem:
    subject = _subject()
    declaration = ExternalEvidenceDeclarationV1(
        evidence_id=f"evidence-{marker}",
        subject=subject,
        subject_digest=subject.canonical_digest(),
        target_dsm_artifact_id="dsm-a",
        target_dsm_observed_sha256=_digest("c"),
        declared_content_digest=_digest(marker),
        declared_content_type="text/csv",
        independence=EvidenceIndependence.DECLARED,
        independence_basis="customer declared independent checkpoints",
        declared_at=NOW,
    ).sealed()
    assert declaration.declaration_digest is not None
    manifest = ExternalEvidenceManifestV1(
        evidence_manifest_id=f"manifest-{marker}",
        evidence_id=declaration.evidence_id,
        declaration_digest=declaration.declaration_digest,
        subject=subject,
        subject_digest=subject.canonical_digest(),
        target_dsm_artifact_id=declaration.target_dsm_artifact_id,
        target_dsm_observed_sha256=declaration.target_dsm_observed_sha256,
        observed_object_digest=declaration.declared_content_digest,
        observed_size_bytes=321,
        observed_content_type=declaration.declared_content_type,
        server_object_key=f"external-evidence/{marker}.csv",
        observed_at=NOW,
    ).sealed()
    return EvidenceItem(
        evidence_id=declaration.evidence_id,
        evidence_ref=f"eev-v1-{marker}",
        work_order_id=subject.work_order_id,
        submission_id=subject.submission_id,
        revision=subject.revision,
        declaration=declaration,
        object_key=manifest.server_object_key,
        manifest=manifest,
    )


class _Evidence:
    def __init__(
        self,
        item: EvidenceItem,
        *additional_items: EvidenceItem,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        self.item = item
        self._items = {candidate.evidence_ref: candidate for candidate in (item, *additional_items)}
        self.coordinator = coordinator

    def resolve_for_validation(self, evidence_ref: str) -> EvidenceItem | None:
        return self._items.get(evidence_ref)

    def locally_matches(self, evidence_ref: str, item: EvidenceItem) -> bool:
        return self._items.get(evidence_ref) == item and item.manifest is not None

    def assert_locally_available(self) -> None:
        pass


class _PolicyAuthority(PolicyAuthorityPort):
    def __init__(self, record: PolicyAuthorityRecord) -> None:
        assert record.digest is not None
        self._record = record
        self._coordinator: ExternalAuthorityCurrentnessCoordinator | None = None

    def bind(self, coordinator: ExternalAuthorityCurrentnessCoordinator) -> _PolicyAuthority:
        self._coordinator = coordinator
        return self

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        assert self._coordinator is not None
        return self._coordinator

    def resolve(self, authority_record_digest: str, now: datetime) -> PolicyAuthorityRecord | None:
        return self._record if authority_record_digest == self._record.digest else None

    def resolve_historical(
        self, authority_record_digest: str, at: datetime
    ) -> PolicyAuthorityRecord | None:
        return (
            self._record
            if authority_record_digest == self._record.digest and self._record.is_active_at(at)
            else None
        )

    def is_current(self, authority: PolicyAuthorityRecord, now: datetime) -> bool:
        return authority == self._record and authority.is_active_at(now)


class _ContextAuthority(EvidenceMeasurementContextAuthorityPort):
    def __init__(
        self,
        context: ExternalEvidenceMeasurementContextV1 | None,
        *additional_contexts: ExternalEvidenceMeasurementContextV1,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        self.context = context
        self._coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        self._historical = {
            candidate.context_digest: candidate
            for candidate in (context, *additional_contexts)
            if candidate is not None
        }

    def resolve_for_validation(
        self,
        *,
        subject: SealedExternalSubjectV1,
        evidence_manifest_digest: str,
        target_dsm_artifact_id: str,
        target_dsm_observed_sha256: str,
        policy_digest: str,
        now: datetime,
    ) -> ExternalEvidenceMeasurementContextV1 | None:
        if self.context is None:
            return None
        return next(
            (
                candidate
                for candidate in self._historical.values()
                if (
                    candidate.subject == subject
                    and candidate.evidence_manifest_digest == evidence_manifest_digest
                    and candidate.target_dsm_artifact_id == target_dsm_artifact_id
                    and candidate.target_dsm_observed_sha256 == target_dsm_observed_sha256
                    and candidate.policy_digest == policy_digest
                )
            ),
            None,
        )

    def resolve_historical_for_validation(
        self,
        *,
        context_digest: str,
        subject: SealedExternalSubjectV1,
        evidence_manifest_digest: str,
        target_dsm_artifact_id: str,
        target_dsm_observed_sha256: str,
        policy_digest: str,
        issued_at: datetime,
    ) -> ExternalEvidenceMeasurementContextV1 | None:
        del (
            subject,
            evidence_manifest_digest,
            target_dsm_artifact_id,
            target_dsm_observed_sha256,
            policy_digest,
            issued_at,
        )
        return self._historical.get(context_digest)

    def is_current(self, context: ExternalEvidenceMeasurementContextV1) -> bool:
        return self.context is not None and context in self._historical.values()

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def withdraw(self) -> None:
        with self._coordinator.mutation():
            self.context = None


class _InputCapabilities(EvidenceValidationInputCapabilityPort):
    """Capability fixture; Core owns the returned byte identities, never the worker."""

    def issue_input(
        self,
        *,
        item: EvidenceItem,
        request: ExternalEvidenceValidationRequestV1,
        context: ExternalEvidenceMeasurementContextV1,
    ) -> tuple[ExternalEvidenceValidationInputBinding, ...]:
        del request
        assert item.manifest is not None
        return (
            ExternalEvidenceValidationInputBinding(
                role="CHECKPOINT_CSV",
                artifact_id=item.manifest.evidence_manifest_id,
                observed_sha256=_digest("a"),
                observed_size_bytes=item.manifest.observed_size_bytes,
                content_type="text/csv",
                download_url="https://storage.invalid/evidence",
                required_headers={},
            ),
            ExternalEvidenceValidationInputBinding(
                role="TARGET_DSM",
                artifact_id=context.target_dsm_artifact_id,
                observed_sha256=_digest("c"),
                observed_size_bytes=10,
                content_type="image/tiff",
                download_url="https://storage.invalid/dsm",
                required_headers={},
            ),
        )


def _policy_registry(
    tmp_path: Path,
    *,
    coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    max_queue_depth: int = 4,
    max_retry_attempts: int = 1,
    max_deadline_seconds: float = 10.0,
) -> tuple[ExternalValidationPolicyRegistry, ExternalValidationPolicyV1]:
    coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
    envelope = ResourceEnvelopeV1(
        max_input_bytes=1_024,
        max_streamed_bytes=1_024,
        max_tiff_directories=4,
        max_tiff_entries=32,
        max_pixels=1_000,
        max_bands=4,
        max_blocks=64,
        max_decompressed_bytes=8_192,
        max_sample_bytes=8_192,
        max_geometry_vertices=64,
        max_cpu_seconds=2.0,
        max_memory_bytes=16_384,
        max_workspace_bytes=16_384,
        max_output_bytes=16_384,
        max_tenant_concurrency=1,
        max_queue_depth=max_queue_depth,
        max_deadline_seconds=max_deadline_seconds,
        lease_duration_seconds=5.0,
        max_retry_attempts=max_retry_attempts,
    ).sealed()
    template = ExternalValidationPolicyV1(
        policy_id="policy-a",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=_digest("e"),
        grammar_digest=_digest("f"),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=_digest("1"),
        inspection_rule_ids=(),
        evidence_rule_ids=("CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",),
        compatibility_mapping_digests=(),
        synthetic_test_only=True,
    ).sealed()
    authority = PolicyAuthorityRecord(
        policy_id=template.policy_id,
        policy_version=template.version,
        authorized_policy_body_digest=authorized_policy_body_digest(template),
        permitted_subjects=(_subject(),),
        permitted_uses=("EVIDENCE",),
        authorized_actor_ids=("authority",),
        active_from=NOW - timedelta(minutes=1),
        active_until=NOW + timedelta(minutes=1),
        synthetic_test_only=True,
    ).sealed()
    assert authority.digest is not None
    policy = template.model_copy(
        update={"authority_record_digest": authority.digest, "policy_digest": None}, deep=True
    ).sealed()
    policy_authority = _PolicyAuthority(authority)
    registry = ExternalValidationPolicyRegistry(
        DurableJournal(tmp_path / "policy.jsonl"),
        authority_port=policy_authority,
        authority_currentness_port=policy_authority.bind(coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    registry.admit(policy, actor="authority", now=NOW)
    return registry, policy


def _context(
    item: EvidenceItem,
    policy: ExternalValidationPolicyV1,
    *,
    context_id: str = "context-a",
) -> ExternalEvidenceMeasurementContextV1:
    assert item.manifest is not None and item.manifest.evidence_manifest_digest is not None
    assert policy.policy_digest is not None
    return ExternalEvidenceMeasurementContextV1(
        context_id=context_id,
        subject=item.manifest.subject,
        evidence_manifest_digest=item.manifest.evidence_manifest_digest,
        evidence_observed_sha256=item.manifest.observed_object_digest,
        evidence_observed_size_bytes=item.manifest.observed_size_bytes,
        target_dsm_artifact_id=item.manifest.target_dsm_artifact_id,
        target_dsm_observed_sha256=item.manifest.target_dsm_observed_sha256,
        policy_digest=policy.policy_digest,
        measurement_execution_manifest_digest=_digest("9"),
        rule_id="CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",
        csv_horizontal_crs="EPSG:5186",
        csv_vertical_reference_digest=_digest("8"),
        minimum_checkpoint_count=3,
        maximum_checkpoint_count=10,
        maximum_rmse_m=0.5,
        maximum_abs_mean_error_m=0.2,
        maximum_abs_error_m=1.0,
        independent_attestation=None,
        authorized_actor_ids=("authority",),
        active_from=NOW - timedelta(minutes=1),
        active_until=NOW + timedelta(minutes=1),
        synthetic_test_only=True,
    ).sealed()


def test_validation_uses_resolved_context_and_core_adjudicates_observed_metrics(
    tmp_path: Path,
) -> None:
    item = _evidence()
    registry, policy = _policy_registry(tmp_path)
    coordinator = registry.coordinator
    context_authority = _ContextAuthority(_context(item, policy), coordinator=coordinator)
    store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "validations.jsonl"),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=context_authority,
        clock=lambda: NOW,
        coordinator=coordinator,
    )

    issued = store.issue_after_seal(item.evidence_ref, now=NOW)
    assert issued.verdict is EvidenceValidationVerdict.ISSUED
    assert issued.request is not None
    fence = LeaseFence(str(uuid4()), str(uuid4()), 0)
    leased = store.claim(issued.request.validation_id, fence, organization_id="org-a", now=NOW)
    assert leased.verdict is EvidenceValidationVerdict.LEASED
    assert leased.fence is not None
    measured = ExternalEvidenceMeasurementPayloadV1(
        validation_id=issued.request.validation_id,
        evidence_manifest_digest=issued.request.evidence_manifest_digest,
        target_dsm_observed_sha256=issued.request.target_dsm_observed_sha256,
        policy_digest=issued.request.policy_digest,
        measured_checkpoint_count=3,
        mean_error_m=0.1,
        mae_m=0.1,
        rmse_m=0.1,
        max_abs_error_m=0.1,
        measured_at=NOW,
    )
    result = store.record_measurement(
        issued.request.validation_id,
        leased.fence,
        measured,
        organization_id="org-a",
        now=NOW,
    )

    assert result.verdict is EvidenceValidationVerdict.VALIDATED
    assert result.record is not None and result.record.measurement_payload == measured
    assert store.terminal_records_for_evidence(item.evidence_ref) == (result.record,)
    projection = _view(item, terminal_records=(result.record,)).model_dump(
        by_alias=True, mode="json", exclude_none=True
    )
    assert projection["measurementSummaries"] == [
        {
            "coreVerdict": "VALIDATED",
            "measuredCheckpointCount": 3,
            "meanErrorM": 0.1,
            "maeM": 0.1,
            "rmseM": 0.1,
            "recordedAt": "2026-09-09T00:00:00Z",
        }
    ]
    assert (
        store.record_for_use(
            result.record.evidence_record_digest or "",
            subject=item.declaration.subject,
            policy_digest=issued.request.policy_digest,
        )
        is not None
    )
    assert (
        store.record_for_current_use(
            result.record.evidence_record_digest or "",
            subject=item.declaration.subject,
            policy_digest=issued.request.policy_digest,
        )
        is not None
    )
    assert (
        store.record_for_locally_current_use(
            result.record.evidence_record_digest or "",
            subject=item.declaration.subject,
            policy_digest=issued.request.policy_digest,
        )
        is not None
    )
    context_authority.context = None
    assert (
        store.record_for_current_use(
            result.record.evidence_record_digest or "",
            subject=item.declaration.subject,
            policy_digest=issued.request.policy_digest,
        )
        is None
    )


def test_analysis_scope_projection_keeps_a_payloadless_rejected_terminal_record(
    tmp_path: Path,
) -> None:
    """A known validation failure must not disappear behind the display projection."""
    item = _evidence()
    registry, policy = _policy_registry(tmp_path)
    coordinator = registry.coordinator
    context = _context(item, policy)
    store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "payloadless-rejected.jsonl"),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=_ContextAuthority(context, coordinator=coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    issued = store.issue_after_seal(item.evidence_ref, now=NOW)
    assert issued.request is not None
    leased = store.claim(
        issued.request.validation_id,
        LeaseFence(str(uuid4()), str(uuid4()), 0),
        organization_id="org-a",
        now=NOW,
    )
    assert leased.fence is not None
    rejected = store.record_incomplete_failure(
        issued.request.validation_id,
        leased.fence,
        organization_id="org-a",
        now=NOW,
        reason="WORKER_INPUT_UNREADABLE",
    )
    assert rejected.record is not None and rejected.record.measurement_payload is None
    assert item.manifest is not None and item.manifest.evidence_manifest_digest is not None
    assert policy.policy_digest is not None and context.context_digest is not None

    assert store.terminal_records_for_analysis_scope(
        subject=item.manifest.subject,
        evidence_manifest_digest=item.manifest.evidence_manifest_digest,
        target_dsm_observed_sha256=item.manifest.target_dsm_observed_sha256,
        policy_digest=policy.policy_digest,
        context_digest=context.context_digest,
    ) == (rejected.record,)


def test_worker_input_exposes_complete_policy_and_exact_byte_identities(tmp_path: Path) -> None:
    """V2 launch construction needs policy plus artifact id/hash/size, not digest guesses."""
    item = _evidence()
    assert item.manifest is not None
    manifest = item.manifest
    registry, policy = _policy_registry(tmp_path)
    coordinator = registry.coordinator
    store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "validation-input.jsonl"),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=_ContextAuthority(_context(item, policy), coordinator=coordinator),
        input_capabilities=_InputCapabilities(),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    issued = store.issue_after_seal(item.evidence_ref, now=NOW)
    assert issued.request is not None
    leased = store.claim(
        issued.request.validation_id,
        LeaseFence(str(uuid4()), str(uuid4()), 0),
        organization_id="org-a",
        now=NOW,
    )
    assert leased.fence is not None

    worker_input = store.input_for(
        issued.request.validation_id, leased.fence, organization_id="org-a"
    )

    assert worker_input.verdict is EvidenceValidationVerdict.LEASED
    assert worker_input.validation_policy == policy
    identities = [
        (binding.role, binding.artifact_id, binding.observed_size_bytes)
        for binding in worker_input.bindings
    ]
    assert identities == [
        ("CHECKPOINT_CSV", manifest.evidence_manifest_id, manifest.observed_size_bytes),
        ("TARGET_DSM", manifest.target_dsm_artifact_id, 10),
    ]


def test_validation_does_not_issue_from_a_declaration_only_context(tmp_path: Path) -> None:
    item = _evidence()
    registry, _ = _policy_registry(tmp_path)
    coordinator = registry.coordinator
    store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "closed.jsonl"),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=_ContextAuthority(None, coordinator=coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )

    assert (
        store.issue_after_seal(item.evidence_ref, now=NOW).verdict
        is EvidenceValidationVerdict.CONTEXT_UNAVAILABLE
    )


def test_validation_store_rejects_a_mismatched_currentness_graph(tmp_path: Path) -> None:
    coordinator = ExternalAuthorityCurrentnessCoordinator()
    registry, _ = _policy_registry(tmp_path, coordinator=coordinator)

    with pytest.raises(ValueError, match="evidence store must share"):
        ExternalEvidenceValidationStore(
            DurableJournal(tmp_path / "mismatched.jsonl"),
            evidence=ExternalEvidenceStore(
                DurableJournal(tmp_path / "evidence.jsonl"),
                coordinator=ExternalAuthorityCurrentnessCoordinator(),
            ),
            policy_registry=registry,
            coordinator=coordinator,
        )


def test_validation_request_replays_without_reasking_current_context_authority(
    tmp_path: Path,
) -> None:
    item = _evidence()
    registry, policy = _policy_registry(tmp_path)
    path = tmp_path / "restart.jsonl"
    coordinator = registry.coordinator
    authority = _ContextAuthority(_context(item, policy), coordinator=coordinator)
    issued = ExternalEvidenceValidationStore(
        DurableJournal(path),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=authority,
        clock=lambda: NOW,
        coordinator=coordinator,
    ).issue_after_seal(item.evidence_ref, now=NOW)
    assert issued.request is not None
    authority.withdraw()

    reopened = ExternalEvidenceValidationStore(
        DurableJournal(path),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=authority,
        clock=lambda: NOW,
        coordinator=coordinator,
    )

    pending = reopened.list_pending(1, organization_id="org-a")
    assert len(pending) == 1
    assert pending[0].validation_id == issued.request.validation_id


def test_evidence_heartbeat_clamps_then_reports_the_absolute_deadline(tmp_path: Path) -> None:
    """A lease fence expiry must not hide the request's typed execution deadline."""
    item = _evidence()
    registry, policy = _policy_registry(tmp_path)
    coordinator = registry.coordinator
    store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "deadline.jsonl"),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=_ContextAuthority(_context(item, policy), coordinator=coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    issued = store.issue_after_seal(item.evidence_ref, now=NOW)
    assert issued.request is not None
    leased = store.claim(
        issued.request.validation_id,
        LeaseFence(str(uuid4()), str(uuid4()), 0),
        organization_id="org-a",
        now=NOW,
    )
    assert leased.fence is not None
    first = store.heartbeat(
        issued.request.validation_id,
        leased.fence,
        organization_id="org-a",
        now=NOW + timedelta(seconds=4),
    )
    assert first.lease_expires_at == NOW + timedelta(seconds=9)
    capped = store.heartbeat(
        issued.request.validation_id,
        leased.fence,
        organization_id="org-a",
        now=NOW + timedelta(seconds=8),
    )
    assert capped.lease_expires_at == NOW + timedelta(seconds=10)
    assert (
        store.heartbeat(
            issued.request.validation_id,
            leased.fence,
            organization_id="org-a",
            now=NOW + timedelta(seconds=10),
        ).verdict
        is EvidenceValidationVerdict.DEADLINE_EXCEEDED
    )


def test_withdrawn_context_blocks_a_pending_lease_and_a_terminal_measurement(
    tmp_path: Path,
) -> None:
    """The historical context anchor must not remain current execution authority."""
    item = _evidence()
    registry, policy = _policy_registry(tmp_path)
    coordinator = registry.coordinator
    authority = _ContextAuthority(_context(item, policy), coordinator=coordinator)
    store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "withdrawn.jsonl"),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=authority,
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    issued = store.issue_after_seal(item.evidence_ref, now=NOW)
    assert issued.request is not None
    authority.withdraw()
    assert (
        store.claim(
            issued.request.validation_id,
            LeaseFence(str(uuid4()), str(uuid4()), 0),
            organization_id="org-a",
            now=NOW,
        ).verdict
        is EvidenceValidationVerdict.CONTEXT_UNAVAILABLE
    )

    authority = _ContextAuthority(_context(item, policy), coordinator=coordinator)
    terminal_store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "withdrawn-terminal.jsonl"),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=authority,
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    terminal_issued = terminal_store.issue_after_seal(item.evidence_ref, now=NOW)
    assert terminal_issued.request is not None
    leased = terminal_store.claim(
        terminal_issued.request.validation_id,
        LeaseFence(str(uuid4()), str(uuid4()), 0),
        organization_id="org-a",
        now=NOW,
    )
    assert leased.fence is not None
    authority.withdraw()
    payload = ExternalEvidenceMeasurementPayloadV1(
        validation_id=terminal_issued.request.validation_id,
        evidence_manifest_digest=terminal_issued.request.evidence_manifest_digest,
        target_dsm_observed_sha256=terminal_issued.request.target_dsm_observed_sha256,
        policy_digest=terminal_issued.request.policy_digest,
        measured_checkpoint_count=3,
        mean_error_m=0.1,
        mae_m=0.1,
        rmse_m=0.1,
        max_abs_error_m=0.1,
        measured_at=NOW,
    )
    assert (
        terminal_store.record_measurement(
            terminal_issued.request.validation_id,
            leased.fence,
            payload,
            organization_id="org-a",
            now=NOW,
        ).verdict
        is EvidenceValidationVerdict.CONTEXT_UNAVAILABLE
    )


def test_evidence_admission_enforces_queue_and_tenant_lease_capacity(tmp_path: Path) -> None:
    """An independent validation request cannot bypass the policy envelope."""
    first_item, second_item = _evidence("a"), _evidence("b")
    registry, policy = _policy_registry(tmp_path / "queue", max_queue_depth=1)
    queue_coordinator = registry.coordinator
    queue_store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "queue" / "validations.jsonl"),
        evidence=_Evidence(first_item, second_item, coordinator=queue_coordinator),
        policy_registry=registry,
        context_authority=_ContextAuthority(
            _context(first_item, policy),
            _context(second_item, policy),
            coordinator=queue_coordinator,
        ),
        clock=lambda: NOW,
        coordinator=queue_coordinator,
    )
    assert (
        queue_store.issue_after_seal(first_item.evidence_ref, now=NOW).verdict
        is EvidenceValidationVerdict.ISSUED
    )
    assert (
        queue_store.issue_after_seal(second_item.evidence_ref, now=NOW).verdict
        is EvidenceValidationVerdict.QUEUE_FULL
    )

    registry, policy = _policy_registry(tmp_path / "capacity")
    capacity_coordinator = registry.coordinator
    capacity_store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "capacity" / "validations.jsonl"),
        evidence=_Evidence(first_item, second_item, coordinator=capacity_coordinator),
        policy_registry=registry,
        context_authority=_ContextAuthority(
            _context(first_item, policy),
            _context(second_item, policy),
            coordinator=capacity_coordinator,
        ),
        clock=lambda: NOW,
        coordinator=capacity_coordinator,
    )
    first = capacity_store.issue_after_seal(first_item.evidence_ref, now=NOW)
    second = capacity_store.issue_after_seal(second_item.evidence_ref, now=NOW)
    assert first.request is not None and second.request is not None
    assert (
        capacity_store.claim(
            first.request.validation_id,
            LeaseFence(str(uuid4()), str(uuid4()), 0),
            organization_id="org-a",
            now=NOW,
        ).verdict
        is EvidenceValidationVerdict.LEASED
    )
    assert (
        capacity_store.claim(
            second.request.validation_id,
            LeaseFence(str(uuid4()), str(uuid4()), 0),
            organization_id="org-a",
            now=NOW,
        ).verdict
        is EvidenceValidationVerdict.CONCURRENCY_LIMIT
    )


def _terminalized_validation(
    tmp_path: Path,
) -> tuple[
    Path,
    EvidenceItem,
    ExternalValidationPolicyRegistry,
    _Evidence,
    _ContextAuthority,
    ExternalEvidenceValidationRequestV1,
    ExternalEvidenceRecordV1,
    list[dict[str, object]],
]:
    item = _evidence()
    registry, policy = _policy_registry(tmp_path / "policy")
    coordinator = registry.coordinator
    evidence = _Evidence(item, coordinator=coordinator)
    authority = _ContextAuthority(_context(item, policy), coordinator=coordinator)
    path = tmp_path / "validation.jsonl"
    store = ExternalEvidenceValidationStore(
        DurableJournal(path),
        evidence=evidence,
        policy_registry=registry,
        context_authority=authority,
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    issued = store.issue_after_seal(item.evidence_ref, now=NOW)
    assert issued.request is not None
    leased = store.claim(
        issued.request.validation_id,
        LeaseFence(str(uuid4()), str(uuid4()), 0),
        organization_id="org-a",
        now=NOW,
    )
    assert leased.fence is not None
    payload = ExternalEvidenceMeasurementPayloadV1(
        validation_id=issued.request.validation_id,
        evidence_manifest_digest=issued.request.evidence_manifest_digest,
        target_dsm_observed_sha256=issued.request.target_dsm_observed_sha256,
        policy_digest=issued.request.policy_digest,
        measured_checkpoint_count=3,
        mean_error_m=0.1,
        mae_m=0.1,
        rmse_m=0.1,
        max_abs_error_m=0.1,
        measured_at=NOW,
    )
    terminal = store.record_measurement(
        issued.request.validation_id,
        leased.fence,
        payload,
        organization_id="org-a",
        now=NOW,
    )
    assert terminal.record is not None
    events = store._journal.replay()  # noqa: SLF001 - journal is the replay contract.
    store._journal.close()  # noqa: SLF001 - reopen the exact durable history below.
    return path, item, registry, evidence, authority, issued.request, terminal.record, events


def _rehashed_second_claim(events: list[dict[str, object]]) -> dict[str, object]:
    claim = copy.deepcopy(events[1])
    claim.update(
        {
            "workerInstanceId": str(uuid4()),
            "leaseAcquisitionId": str(uuid4()),
            "leaseGeneration": 2,
        }
    )
    claim["eventDigest"] = _event_digest(claim)
    return claim


def _write_validation_events(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(event, separators=(",", ":")) + "\n" for event in events),
        encoding="utf-8",
    )


def test_replay_rejects_a_claim_after_terminal_and_retains_a_legitimate_terminal(
    tmp_path: Path,
) -> None:
    """A rehashed claim must never reopen a terminal evidence record."""
    path, item, registry, evidence, authority, request, record, events = _terminalized_validation(
        tmp_path
    )

    restarted = ExternalEvidenceValidationStore(
        DurableJournal(path),
        evidence=evidence,
        policy_registry=registry,
        context_authority=authority,
        clock=lambda: NOW,
        coordinator=registry.coordinator,
    )
    assert restarted.record_for_use(
        record.evidence_record_digest or "",
        subject=item.declaration.subject,
        policy_digest=request.policy_digest,
    ) == (record, authority.context)
    restarted._journal.close()  # noqa: SLF001 - isolate the forged replay fixture.

    forged_path = tmp_path / "terminal-reopened.jsonl"
    _write_validation_events(forged_path, [*events, _rehashed_second_claim(events)])

    with pytest.raises(ExternalEvidenceValidationRecoveryError, match="terminal"):
        ExternalEvidenceValidationStore(
            DurableJournal(forged_path),
            evidence=evidence,
            policy_registry=registry,
            context_authority=authority,
            clock=lambda: NOW,
            coordinator=registry.coordinator,
        )


def test_replay_rejects_terminal_replacement_after_a_rehashed_claim(tmp_path: Path) -> None:
    """A terminal result is exactly once even if every forged event is rehashed."""
    (
        _path,
        _item,
        registry,
        evidence,
        authority,
        _request,
        record,
        events,
    ) = _terminalized_validation(tmp_path)
    claim = _rehashed_second_claim(events)
    replacement = copy.deepcopy(events[2])
    replacement.update(
        {
            "workerInstanceId": claim["workerInstanceId"],
            "leaseAcquisitionId": claim["leaseAcquisitionId"],
            "leaseGeneration": claim["leaseGeneration"],
        }
    )
    old = ExternalEvidenceRecordV1.model_validate(replacement["record"])
    assert old == record and old.measurement_payload is not None
    changed_payload = old.measurement_payload.model_copy(
        update={"rmse_m": 0.2, "max_abs_error_m": 0.2}
    )
    changed_record = old.model_copy(
        update={"measurement_payload": changed_payload, "evidence_record_digest": None}, deep=True
    ).sealed()
    replacement["record"] = external_evidence_record_wire_dict(changed_record)
    replacement["eventDigest"] = _event_digest(replacement)
    forged_path = tmp_path / "terminal-replaced.jsonl"
    _write_validation_events(forged_path, [*events, claim, replacement])

    with pytest.raises(ExternalEvidenceValidationRecoveryError, match="terminal"):
        ExternalEvidenceValidationStore(
            DurableJournal(forged_path),
            evidence=evidence,
            policy_registry=registry,
            context_authority=authority,
            clock=lambda: NOW,
            coordinator=registry.coordinator,
        )


def test_replay_rejects_a_heartbeat_that_shortens_a_fenced_lease(tmp_path: Path) -> None:
    """A replayed heartbeat may retain or extend its fence, never shorten it."""
    (
        _path,
        _item,
        registry,
        evidence,
        authority,
        _request,
        _record,
        events,
    ) = _terminalized_validation(tmp_path)
    heartbeat = copy.deepcopy(events[1])
    heartbeat.update(
        {
            "kind": "external-evidence-validation-heartbeated",
            "leaseExpiresAt": (NOW + timedelta(seconds=4)).isoformat(),
        }
    )
    heartbeat["eventDigest"] = _event_digest(heartbeat)
    forged_path = tmp_path / "shortened-heartbeat.jsonl"
    _write_validation_events(forged_path, [events[0], events[1], heartbeat, events[2]])

    with pytest.raises(ExternalEvidenceValidationRecoveryError, match="heartbeat"):
        ExternalEvidenceValidationStore(
            DurableJournal(forged_path),
            evidence=evidence,
            policy_registry=registry,
            context_authority=authority,
            clock=lambda: NOW,
            coordinator=registry.coordinator,
        )


def test_expired_unleased_validation_releases_queue_capacity_and_pending_slot(
    tmp_path: Path,
) -> None:
    """An unclaimed request past its immutable deadline is no longer executable work."""
    now = [NOW]
    first, second = _evidence("a"), _evidence("b")
    registry, policy = _policy_registry(tmp_path / "policy", max_queue_depth=1)
    coordinator = registry.coordinator
    store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "validation.jsonl"),
        evidence=_Evidence(first, second, coordinator=coordinator),
        policy_registry=registry,
        context_authority=_ContextAuthority(
            _context(first, policy), _context(second, policy), coordinator=coordinator
        ),
        clock=lambda: now[0],
        coordinator=coordinator,
    )
    issued = store.issue_after_seal(first.evidence_ref, now=now[0])
    assert issued.request is not None
    now[0] += timedelta(seconds=20)

    assert store.list_pending(10, organization_id="org-a") == ()
    assert (
        store.issue_after_seal(second.evidence_ref, now=now[0]).verdict
        is EvidenceValidationVerdict.ISSUED
    )


def test_pending_validation_omits_retry_exhausted_lease_after_expiry(tmp_path: Path) -> None:
    """A lease that consumed every permitted attempt cannot starve later pending work."""
    now = [NOW]
    item = _evidence()
    registry, policy = _policy_registry(
        tmp_path / "policy", max_retry_attempts=1, max_deadline_seconds=30.0
    )
    coordinator = registry.coordinator
    store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "validation.jsonl"),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=_ContextAuthority(_context(item, policy), coordinator=coordinator),
        clock=lambda: now[0],
        coordinator=coordinator,
    )
    issued = store.issue_after_seal(item.evidence_ref, now=now[0])
    assert issued.request is not None
    assert (
        store.claim(
            issued.request.validation_id,
            LeaseFence(str(uuid4()), str(uuid4()), 0),
            organization_id="org-a",
            now=now[0],
        ).verdict
        is EvidenceValidationVerdict.LEASED
    )
    now[0] += timedelta(seconds=6)
    assert (
        store.claim(
            issued.request.validation_id,
            LeaseFence(str(uuid4()), str(uuid4()), 0),
            organization_id="org-a",
            now=now[0],
        ).verdict
        is EvidenceValidationVerdict.LEASED
    )
    now[0] += timedelta(seconds=6)

    assert store.list_pending(10, organization_id="org-a") == ()


def test_pending_validation_omits_expired_records_but_keeps_live_records(tmp_path: Path) -> None:
    """Pending enumeration filters each request by its own immutable deadline."""
    now = [NOW]
    expired, live = _evidence("a"), _evidence("b")
    registry, policy = _policy_registry(tmp_path / "policy")
    coordinator = registry.coordinator
    store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "validation.jsonl"),
        evidence=_Evidence(expired, live, coordinator=coordinator),
        policy_registry=registry,
        context_authority=_ContextAuthority(
            _context(expired, policy), _context(live, policy), coordinator=coordinator
        ),
        clock=lambda: now[0],
        coordinator=coordinator,
    )
    first = store.issue_after_seal(expired.evidence_ref, now=now[0])
    assert first.request is not None
    now[0] += timedelta(seconds=20)
    second = store.issue_after_seal(live.evidence_ref, now=now[0])
    assert second.request is not None

    pending_ids = [
        pending.validation_id for pending in store.list_pending(10, organization_id="org-a")
    ]
    assert pending_ids == [second.request.validation_id]


def test_pending_validation_lists_only_the_latest_issuance_per_context_key(
    tmp_path: Path,
) -> None:
    """A superseded context generation must not starve the queue behind it.

    Only one context can be current for a (subject, evidence manifest, target
    DSM, policy) key, so a record issued under an earlier generation answers
    CONTEXT_UNAVAILABLE for every claim while still occupying the queue head.
    The pending list keeps the newest issuance per key and drops the older one
    without consulting the context authority (which the recovery path may no
    longer be able to answer for).
    """
    item = _evidence()
    registry, policy = _policy_registry(tmp_path, max_deadline_seconds=120.0)
    path = tmp_path / "restart.jsonl"
    coordinator = registry.coordinator
    context_a = _context(item, policy)
    context_b = _context(item, policy, context_id="context-b")
    assert context_a.context_digest != context_b.context_digest

    first = ExternalEvidenceValidationStore(
        DurableJournal(path),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=_ContextAuthority(context_a, coordinator=coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    superseded = first.issue_after_seal(item.evidence_ref, now=NOW)
    assert superseded.request is not None
    assert [pending.validation_id for pending in first.list_pending(10)] == [
        superseded.request.validation_id
    ]
    del first  # release the journal writer lock before reopening the path

    second = ExternalEvidenceValidationStore(
        DurableJournal(path),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        # Both contexts stay historically resolvable for replay; the first
        # entry is the one the store resolves as current.
        context_authority=_ContextAuthority(context_b, context_a, coordinator=coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    issued = second.issue_after_seal(item.evidence_ref, now=NOW + timedelta(seconds=30))
    assert issued.request is not None
    assert issued.request.validation_id != superseded.request.validation_id

    assert [pending.validation_id for pending in second.list_pending(10)] == [
        issued.request.validation_id
    ]


class _SwitchableContextAuthority(EvidenceMeasurementContextAuthorityPort):
    """Authority with one explicitly movable resolved context generation."""

    def __init__(self, *, coordinator: ExternalAuthorityCurrentnessCoordinator) -> None:
        self.current: ExternalEvidenceMeasurementContextV1 | None = None
        self._historical: dict[str, ExternalEvidenceMeasurementContextV1] = {}
        self._coordinator = coordinator

    def adopt(self, context: ExternalEvidenceMeasurementContextV1) -> None:
        digest = context.context_digest
        assert digest is not None
        with self._coordinator.mutation():
            self._historical[digest] = context
            self.current = context

    def resolve_for_validation(
        self,
        *,
        subject: SealedExternalSubjectV1,
        evidence_manifest_digest: str,
        target_dsm_artifact_id: str,
        target_dsm_observed_sha256: str,
        policy_digest: str,
        now: datetime,
    ) -> ExternalEvidenceMeasurementContextV1 | None:
        del now
        candidate = self.current
        if candidate is None:
            return None
        if (
            candidate.subject == subject
            and candidate.evidence_manifest_digest == evidence_manifest_digest
            and candidate.target_dsm_artifact_id == target_dsm_artifact_id
            and candidate.target_dsm_observed_sha256 == target_dsm_observed_sha256
            and candidate.policy_digest == policy_digest
        ):
            return candidate
        return None

    def resolve_historical_for_validation(
        self,
        *,
        context_digest: str,
        subject: SealedExternalSubjectV1,
        evidence_manifest_digest: str,
        target_dsm_artifact_id: str,
        target_dsm_observed_sha256: str,
        policy_digest: str,
        issued_at: datetime,
    ) -> ExternalEvidenceMeasurementContextV1 | None:
        del subject, evidence_manifest_digest, target_dsm_artifact_id
        del target_dsm_observed_sha256, policy_digest, issued_at
        return self._historical.get(context_digest)

    def is_current(self, context: ExternalEvidenceMeasurementContextV1) -> bool:
        return context == self.current

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator


def test_pending_list_follows_the_context_a_refused_claim_resolved(tmp_path: Path) -> None:
    """A refused claim teaches the queue which generation is actually live.

    Issuance order alone would keep the newest record in front even after the
    authority settles on an older generation, starving the runnable one.  The
    store therefore records the generation the refused claim heard from the
    authority and prefers it in the next pending projection.
    """
    item = _evidence()
    registry, policy = _policy_registry(tmp_path, max_deadline_seconds=120.0)
    context_a = _context(item, policy)
    context_b = _context(item, policy, context_id="context-b")
    assert context_a.context_digest != context_b.context_digest
    path = tmp_path / "restart.jsonl"
    coordinator = registry.coordinator
    authority = _SwitchableContextAuthority(coordinator=coordinator)

    authority.adopt(context_a)
    first = ExternalEvidenceValidationStore(
        DurableJournal(path),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=authority,
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    record_a = first.issue_after_seal(item.evidence_ref, now=NOW).request
    assert record_a is not None
    del first  # release the journal writer lock before reopening the path

    authority.adopt(context_b)
    store = ExternalEvidenceValidationStore(
        DurableJournal(path),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=authority,
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    record_b = store.issue_after_seal(item.evidence_ref, now=NOW + timedelta(seconds=30)).request
    assert record_b is not None
    assert record_b.validation_id != record_a.validation_id
    assert [pending.validation_id for pending in store.list_pending(10)] == [
        record_b.validation_id
    ]

    # The authority settles back on the older generation: issuance order alone
    # still shows the now-stale newer record.
    authority.adopt(context_a)
    assert [pending.validation_id for pending in store.list_pending(10)] == [
        record_b.validation_id
    ]

    refusal = store.claim(
        record_b.validation_id,
        LeaseFence(str(uuid4()), str(uuid4()), 0),
        organization_id="org-a",
        now=NOW + timedelta(seconds=31),
    )
    assert refusal.verdict is EvidenceValidationVerdict.CONTEXT_UNAVAILABLE

    # The refused claim taught the store that context A is live, so the runnable
    # record takes the queue head and can be leased.
    assert [pending.validation_id for pending in store.list_pending(10)] == [
        record_a.validation_id
    ]
    leased = store.claim(
        record_a.validation_id,
        LeaseFence(str(uuid4()), str(uuid4()), 0),
        organization_id="org-a",
        now=NOW + timedelta(seconds=32),
    )
    assert leased.verdict is EvidenceValidationVerdict.LEASED
    assert leased.fence is not None


def test_concurrent_fresh_admission_after_expiry_respects_released_queue_boundary(
    tmp_path: Path,
) -> None:
    """One fresh request claims the released slot; concurrent peers still observe its envelope."""
    now = [NOW]
    expired, first, second = _evidence("a"), _evidence("b"), _evidence("c")
    registry, policy = _policy_registry(tmp_path / "policy", max_queue_depth=1)
    coordinator = registry.coordinator
    store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "validation.jsonl"),
        evidence=_Evidence(expired, first, second, coordinator=coordinator),
        policy_registry=registry,
        context_authority=_ContextAuthority(
            _context(expired, policy),
            _context(first, policy),
            _context(second, policy),
            coordinator=coordinator,
        ),
        clock=lambda: now[0],
        coordinator=coordinator,
    )
    assert (
        store.issue_after_seal(expired.evidence_ref, now=now[0]).verdict
        is EvidenceValidationVerdict.ISSUED
    )
    now[0] += timedelta(seconds=20)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda evidence_ref: store.issue_after_seal(evidence_ref, now=now[0]),
                (first.evidence_ref, second.evidence_ref),
            )
        )

    assert {result.verdict for result in results} == {
        EvidenceValidationVerdict.ISSUED,
        EvidenceValidationVerdict.QUEUE_FULL,
    }
    pending = store.list_pending(10, organization_id="org-a")
    assert len(pending) == 1
    assert pending[0].validation_id != ""


def test_evidence_generation_zero_response_loss_retry_returns_existing_grant(
    tmp_path: Path,
) -> None:
    item = _evidence()
    registry, policy = _policy_registry(tmp_path)
    coordinator = registry.coordinator
    store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "response-loss.jsonl"),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=_ContextAuthority(_context(item, policy), coordinator=coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    issued = store.issue_after_seal(item.evidence_ref, now=NOW)
    assert issued.request is not None
    initial = LeaseFence(str(uuid4()), str(uuid4()), 0)
    first = store.claim(issued.request.validation_id, initial, organization_id="org-a", now=NOW)
    assert first.verdict is EvidenceValidationVerdict.LEASED
    assert first.fence is not None
    retry = store.claim(issued.request.validation_id, initial, organization_id="org-a", now=NOW)
    assert retry.verdict is EvidenceValidationVerdict.LEASED
    assert retry.fence == first.fence
    assert retry.lease_expires_at == first.lease_expires_at
    assert [entry["kind"] for entry in store._journal.replay()].count(  # noqa: SLF001
        "external-evidence-validation-claimed"
    ) == 1


def test_evidence_generation_zero_retry_rejects_foreign_or_expired_acquisition(
    tmp_path: Path,
) -> None:
    item = _evidence()
    registry, policy = _policy_registry(tmp_path)
    coordinator = registry.coordinator
    store = ExternalEvidenceValidationStore(
        DurableJournal(tmp_path / "response-loss-negative.jsonl"),
        evidence=_Evidence(item, coordinator=coordinator),
        policy_registry=registry,
        context_authority=_ContextAuthority(_context(item, policy), coordinator=coordinator),
        clock=lambda: NOW,
        coordinator=coordinator,
    )
    issued = store.issue_after_seal(item.evidence_ref, now=NOW)
    assert issued.request is not None
    initial = LeaseFence(str(uuid4()), str(uuid4()), 0)
    assert (
        store.claim(issued.request.validation_id, initial, organization_id="org-a", now=NOW).verdict
        is EvidenceValidationVerdict.LEASED
    )
    assert (
        store.claim(
            issued.request.validation_id,
            LeaseFence(str(uuid4()), initial.lease_acquisition_id, 0),
            organization_id="org-a",
            now=NOW,
        ).verdict
        is EvidenceValidationVerdict.LEASE_FENCE_REJECTED
    )
    # A previously granted acquisition remains consumed after expiry and cannot
    # become a fresh claim by replaying its generation-zero transport retry.
    assert (
        store.claim(
            issued.request.validation_id,
            initial,
            organization_id="org-a",
            now=NOW + timedelta(seconds=6),
        ).verdict
        is EvidenceValidationVerdict.LEASE_FENCE_REJECTED
    )
    assert (
        store.claim(
            issued.request.validation_id,
            LeaseFence(str(uuid4()), str(uuid4()), True),
            organization_id="org-a",
            now=NOW,
        ).verdict
        is EvidenceValidationVerdict.LEASE_FENCE_REJECTED
    )
