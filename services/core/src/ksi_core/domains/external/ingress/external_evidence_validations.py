"""Fenced Core lifecycle for independently adjudicated external evidence.

This ledger never reads CSV or raster bytes.  It records the authority that
permits a contained worker to inspect the exact sealed CSV and DSM, then
adjudicates only its bounded observed aggregate payload.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Protocol

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Response
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_evidence import (
    EvidenceCoreVerdict,
    ExternalEvidenceManifestV1,
    ExternalEvidenceMeasurementPayloadV1,
    ExternalEvidenceRecordV1,
    ExternalEvidenceValidationRequestV1,
    external_evidence_record_wire_dict,
    external_evidence_validation_request_wire_dict,
)
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1
from pydantic import Field

from ksi_core.domains.artifacts.evidence import (
    DEFAULT_VIEW_TTL,
    EvidenceStorage,
    EvidenceStorageError,
)
from ksi_core.domains.external.ingress.external_evidence import EvidenceItem
from ksi_core.domains.external.ingress.external_reconstruction import ExternalReconstructionStore
from ksi_core.domains.external.ingress.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicySelectionStatus,
)
from ksi_core.foundation.api_base import CamelModel
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.leasing import LeaseFence
from ksi_core.identity.auth import Permission, Principal, require_permission

_VERSION = 1
_DIGEST = "sha256:"


class ExternalEvidenceValidationRecoveryError(RuntimeError):
    """The evidence-validation journal cannot be replayed as exact history."""


class EvidenceValidationVerdict(StrEnum):
    ISSUED = "ISSUED"
    IDEMPOTENT = "IDEMPOTENT"
    EVIDENCE_NOT_SEALED = "EVIDENCE_NOT_SEALED"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    CONTEXT_UNAVAILABLE = "CONTEXT_UNAVAILABLE"
    CONTEXT_BINDING_REJECTED = "CONTEXT_BINDING_REJECTED"
    LEASED = "LEASED"
    LEASE_FENCE_REJECTED = "LEASE_FENCE_REJECTED"
    NOT_FOUND = "NOT_FOUND"
    INPUT_UNAVAILABLE = "INPUT_UNAVAILABLE"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    PAYLOAD_DIVERGENCE = "PAYLOAD_DIVERGENCE"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    QUEUE_FULL = "QUEUE_FULL"
    CONCURRENCY_LIMIT = "CONCURRENCY_LIMIT"


class EvidenceValidationPhase(StrEnum):
    QUEUED = "QUEUED"
    LEASED = "LEASED"
    TERMINAL = "TERMINAL"


class SealedEvidenceValidationPort(Protocol):
    """Closed bridge to the sealed external-evidence ledger."""

    def resolve_for_validation(self, evidence_ref: str) -> EvidenceItem | None: ...


class EvidenceMeasurementContextAuthorityPort(Protocol):
    """Independent current and historical context authority.

    Current authority mutations share the Core coordinator.  Historical
    resolution is intentionally separate: replay proves the exact immutable
    context body without treating the validation journal as its own source of
    authority.
    """

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator: ...

    def resolve_for_validation(
        self,
        *,
        subject: SealedExternalSubjectV1,
        evidence_manifest_digest: str,
        target_dsm_artifact_id: str,
        target_dsm_observed_sha256: str,
        policy_digest: str,
        now: datetime,
    ) -> ExternalEvidenceMeasurementContextV1 | None: ...

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
    ) -> ExternalEvidenceMeasurementContextV1 | None: ...

    def is_current(self, context: ExternalEvidenceMeasurementContextV1) -> bool: ...


class EvidenceValidationInputCapabilityPort(Protocol):
    """Creates worker-only, short lived, exact CSV/DSM input capabilities."""

    def issue_input(
        self,
        *,
        item: EvidenceItem,
        request: ExternalEvidenceValidationRequestV1,
        context: ExternalEvidenceMeasurementContextV1,
    ) -> tuple[ExternalEvidenceValidationInputBinding, ...] | None: ...


class _NoContextAuthority:
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
        return None

    def is_current(self, context: ExternalEvidenceMeasurementContextV1) -> bool:
        return False


class CoreEvidenceValidationInputCapabilities(EvidenceValidationInputCapabilityPort):
    """Issue worker-only bindings after resolving the exact sealed CSV and DSM."""

    def __init__(
        self, *, reconstruction: ExternalReconstructionStore, storage: EvidenceStorage
    ) -> None:
        self._reconstruction = reconstruction
        self._storage = storage

    def issue_input(
        self,
        *,
        item: EvidenceItem,
        request: ExternalEvidenceValidationRequestV1,
        context: ExternalEvidenceMeasurementContextV1,
    ) -> tuple[ExternalEvidenceValidationInputBinding, ...] | None:
        manifest = item.manifest
        if (
            manifest is None
            or manifest.evidence_manifest_digest != request.evidence_manifest_digest
        ):
            return None
        revision = self._reconstruction.resolve_sealed_subject(manifest.subject)
        if revision is None or revision.manifest is None:
            return None
        # The artifact id and digest are distinct.  The exact context carries
        # the approved id while the request carries its observed digest.
        dsm = next(
            (
                entry
                for entry in revision.manifest.entries
                if entry.artifact_id == context.target_dsm_artifact_id
                and "sha256:" + entry.observed_sha256 == request.target_dsm_observed_sha256
            ),
            None,
        )
        if (
            dsm is None
            or context.evidence_observed_sha256 != manifest.observed_object_digest
            or context.evidence_observed_size_bytes != manifest.observed_size_bytes
        ):
            return None
        try:
            evidence_url = self._storage.presigned_get(item.object_key, ttl=DEFAULT_VIEW_TTL)
            dsm_url = self._storage.presigned_get(dsm.object_key, ttl=DEFAULT_VIEW_TTL)
        except EvidenceStorageError:
            return None
        return (
            ExternalEvidenceValidationInputBinding(
                role="CHECKPOINT_CSV",
                artifact_id=manifest.evidence_manifest_id,
                observed_sha256=manifest.observed_object_digest,
                observed_size_bytes=manifest.observed_size_bytes,
                content_type=manifest.observed_content_type,
                download_url=evidence_url,
                required_headers={},
            ),
            ExternalEvidenceValidationInputBinding(
                role="TARGET_DSM",
                artifact_id=dsm.artifact_id,
                observed_sha256=request.target_dsm_observed_sha256,
                observed_size_bytes=dsm.observed_size_bytes,
                content_type=dsm.observed_content_type,
                download_url=dsm_url,
                required_headers={},
            ),
        )


@dataclass(frozen=True, slots=True)
class ExternalEvidenceValidationInputBinding:
    """Capability-bearing worker input; never part of the durable journal."""

    role: str
    artifact_id: str
    observed_sha256: str
    observed_size_bytes: int
    content_type: str
    download_url: str
    required_headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class EvidenceValidationIssueResult:
    verdict: EvidenceValidationVerdict
    request: ExternalEvidenceValidationRequestV1 | None = None


@dataclass(frozen=True, slots=True)
class PendingEvidenceValidation:
    validation_id: str
    issued_at: datetime


@dataclass(frozen=True, slots=True)
class EvidenceValidationLeaseResult:
    verdict: EvidenceValidationVerdict
    request: ExternalEvidenceValidationRequestV1 | None = None
    fence: LeaseFence | None = None
    lease_expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EvidenceValidationInputResult:
    verdict: EvidenceValidationVerdict
    request: ExternalEvidenceValidationRequestV1 | None = None
    context: ExternalEvidenceMeasurementContextV1 | None = None
    bindings: tuple[ExternalEvidenceValidationInputBinding, ...] = ()
    validation_policy: ExternalValidationPolicyV1 | None = None


@dataclass(frozen=True, slots=True)
class EvidenceValidationMeasurementResult:
    verdict: EvidenceValidationVerdict
    record: ExternalEvidenceRecordV1 | None = None


class ExternalEvidenceValidationLeaseFenceView(CamelModel):
    worker_instance_id: str
    lease_acquisition_id: str
    lease_generation: int


class ExternalEvidenceValidationPendingView(CamelModel):
    validation_id: str
    issued_at: datetime


class ExternalEvidenceValidationPendingListView(CamelModel):
    items: list[ExternalEvidenceValidationPendingView]


class ExternalEvidenceValidationLeaseView(CamelModel):
    verdict: EvidenceValidationVerdict
    request: ExternalEvidenceValidationRequestV1 | None = None
    fence: ExternalEvidenceValidationLeaseFenceView | None = None
    lease_expires_at: datetime | None = None


class ExternalEvidenceValidationInputBindingView(CamelModel):
    role: str
    artifact_id: str
    observed_sha256: str
    observed_size_bytes: int
    content_type: str
    download_url: str
    required_headers: dict[str, str]


class ExternalEvidenceValidationInputView(CamelModel):
    verdict: EvidenceValidationVerdict
    request: ExternalEvidenceValidationRequestV1 | None = None
    context: ExternalEvidenceMeasurementContextV1 | None = None
    validation_policy: ExternalValidationPolicyV1 | None = None
    bindings: list[ExternalEvidenceValidationInputBindingView]


class ExternalEvidenceValidationMeasurementView(CamelModel):
    verdict: EvidenceValidationVerdict
    record: ExternalEvidenceRecordV1 | None = None


class ExternalEvidenceValidationFailureRequest(CamelModel):
    reason: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")


@dataclass(slots=True)
class _Lease:
    fence: LeaseFence
    expires_at: datetime


@dataclass(slots=True)
class _Record:
    evidence_ref: str
    request: ExternalEvidenceValidationRequestV1
    context: ExternalEvidenceMeasurementContextV1
    item: EvidenceItem
    phase: EvidenceValidationPhase = EvidenceValidationPhase.QUEUED
    lease: _Lease | None = None
    last_generation: int = 0
    used_acquisition_ids: set[str] | None = None
    attempts: int = 0
    result: ExternalEvidenceRecordV1 | None = None

    def __post_init__(self) -> None:
        if self.used_acquisition_ids is None:
            self.used_acquisition_ids = set()


def _digest(value: Mapping[str, object]) -> str:
    return _DIGEST + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _event_digest(value: Mapping[str, object]) -> str:
    return _digest({key: item for key, item in value.items() if key != "eventDigest"})


def _wire_time(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("time must be UTC-aware")
    return value.isoformat()


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _wire_time(parsed)
    return parsed


def _fence_wire(fence: LeaseFence) -> dict[str, object]:
    return {
        "workerInstanceId": fence.worker_instance_id,
        "leaseAcquisitionId": fence.lease_acquisition_id,
        "leaseGeneration": fence.lease_generation,
    }


def _fence_from_wire(raw: Mapping[str, object]) -> LeaseFence:
    generation = raw["leaseGeneration"]
    if type(generation) is not int:
        raise ValueError("lease generation is invalid")
    fence = LeaseFence(str(raw["workerInstanceId"]), str(raw["leaseAcquisitionId"]), generation)
    if not fence.is_well_formed():
        raise ValueError("lease fence is invalid")
    return fence


class ExternalEvidenceValidationStore:
    """Current-policy, fenced lifecycle for one sealed evidence manifest."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        evidence: SealedEvidenceValidationPort,
        policy_registry: ExternalValidationPolicyRegistry,
        context_authority: EvidenceMeasurementContextAuthorityPort | None = None,
        input_capabilities: EvidenceValidationInputCapabilityPort | None = None,
        clock: Callable[[], datetime] | None = None,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        if coordinator is not None:
            for name, dependency in (
                ("evidence store", evidence),
                ("validation policy registry", policy_registry),
            ):
                if getattr(dependency, "coordinator", None) is not coordinator:
                    raise ValueError(f"{name} must share currentness coordinator")
            if context_authority is not None and context_authority.coordinator is not coordinator:
                raise ValueError("measurement context authority must share currentness coordinator")
        self._journal = journal
        self._evidence = evidence
        self._policy_registry = policy_registry
        self._context_authority = context_authority or _NoContextAuthority()
        self._input_capabilities = input_capabilities
        self._clock = clock or (lambda: datetime.now(UTC))
        self._coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        self._records: dict[str, _Record] = {}
        self._natural: dict[tuple[str, str, str], str] = {}
        self._lock = threading.RLock()
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            journal.close()
            if isinstance(exc, ExternalEvidenceValidationRecoveryError):
                raise
            raise ExternalEvidenceValidationRecoveryError(
                f"external evidence validation replay failed: {exc}"
            ) from exc

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    def issue_after_seal(
        self, evidence_ref: str, *, now: datetime
    ) -> EvidenceValidationIssueResult:
        """Resolve fresh policy/context before emitting one immutable request."""
        _wire_time(now)
        item = self._evidence.resolve_for_validation(evidence_ref)
        if item is None or item.manifest is None:
            return EvidenceValidationIssueResult(EvidenceValidationVerdict.EVIDENCE_NOT_SEALED)
        manifest = item.manifest
        selection = self._policy_registry.select_for_use("EVIDENCE", (manifest.subject,))
        policy = selection.policy
        if selection.status is not PolicySelectionStatus.ACTIVE or policy is None:
            return EvidenceValidationIssueResult(EvidenceValidationVerdict.POLICY_UNAVAILABLE)
        context = self._context_authority.resolve_for_validation(
            subject=manifest.subject,
            evidence_manifest_digest=manifest.evidence_manifest_digest or "",
            target_dsm_artifact_id=manifest.target_dsm_artifact_id,
            target_dsm_observed_sha256=manifest.target_dsm_observed_sha256,
            policy_digest=policy.policy_digest or "",
            now=now,
        )
        if context is None:
            return EvidenceValidationIssueResult(EvidenceValidationVerdict.CONTEXT_UNAVAILABLE)
        if not self._context_binds(context, item, policy, now):
            return EvidenceValidationIssueResult(EvidenceValidationVerdict.CONTEXT_BINDING_REJECTED)
        assert (
            manifest.evidence_manifest_digest is not None
            and policy.policy_digest is not None
            and context.context_digest is not None
        )
        historical_context = self._context_authority.resolve_historical_for_validation(
            context_digest=context.context_digest,
            subject=manifest.subject,
            evidence_manifest_digest=manifest.evidence_manifest_digest,
            target_dsm_artifact_id=manifest.target_dsm_artifact_id,
            target_dsm_observed_sha256=manifest.target_dsm_observed_sha256,
            policy_digest=policy.policy_digest,
            issued_at=now,
        )
        if historical_context != context:
            return EvidenceValidationIssueResult(EvidenceValidationVerdict.CONTEXT_BINDING_REJECTED)
        natural = (
            manifest.evidence_manifest_digest,
            policy.policy_digest,
            context.context_digest,
        )
        request = ExternalEvidenceValidationRequestV1(
            validation_id=(
                "external-evidence-validation-"
                + hashlib.sha256("\0".join(natural).encode()).hexdigest()[:32]
            ),
            evidence_manifest_digest=manifest.evidence_manifest_digest,
            subject_digest=manifest.subject_digest,
            target_dsm_observed_sha256=manifest.target_dsm_observed_sha256,
            policy_id=policy.policy_id,
            policy_version=policy.version,
            policy_digest=policy.policy_digest,
            issued_at=now,
            idempotency_key="evidence-seal:" + evidence_ref,
        )
        with self._coordinator.mutation(), self._lock:
            existing_id = self._natural.get(natural)
            if existing_id is not None:
                return EvidenceValidationIssueResult(
                    EvidenceValidationVerdict.IDEMPOTENT, self._records[existing_id].request
                )
            current_policy = self._policy_for_request(request)
            if (
                current_policy is None
                or not self._context_authority.is_current(context)
                or not self._context_binds(context, item, current_policy, now)
            ):
                return EvidenceValidationIssueResult(EvidenceValidationVerdict.CONTEXT_UNAVAILABLE)
            queue_depth = sum(
                1
                for candidate in self._records.values()
                if (
                    self._is_pending_execution(candidate, now)
                    and candidate.item.declaration.subject.organization_id
                    == item.declaration.subject.organization_id
                )
            )
            assert current_policy.resource_envelope is not None
            if queue_depth >= current_policy.resource_envelope.max_queue_depth:
                return EvidenceValidationIssueResult(EvidenceValidationVerdict.QUEUE_FULL)
            raw: dict[str, object] = {
                "kind": "external-evidence-validation-issued",
                "version": _VERSION,
                "evidenceRef": evidence_ref,
                "request": external_evidence_validation_request_wire_dict(request),
                "context": context.model_dump(by_alias=True, mode="json"),
            }
            raw["eventDigest"] = _event_digest(raw)
            try:
                self._append_apply(raw, item=item, historical_context=context)
            except JournalSealedError:
                return EvidenceValidationIssueResult(EvidenceValidationVerdict.STORAGE_UNAVAILABLE)
            return EvidenceValidationIssueResult(EvidenceValidationVerdict.ISSUED, request)

    def list_pending(
        self, limit: int, *, organization_id: str | None = None
    ) -> tuple[PendingEvidenceValidation, ...]:
        if limit < 1:
            raise ValueError("limit must be positive")
        now = self._clock()
        with self._lock:
            return tuple(
                PendingEvidenceValidation(record.request.validation_id, record.request.issued_at)
                for record in self._records.values()
                if self._is_pending_execution(record, now)
                and (
                    organization_id is None
                    or record.item.declaration.subject.organization_id == organization_id
                )
            )[:limit]

    def claim(
        self,
        validation_id: str,
        fence: LeaseFence,
        *,
        organization_id: str | None,
        now: datetime,
    ) -> EvidenceValidationLeaseResult:
        _wire_time(now)
        if type(fence.lease_generation) is not int:
            return EvidenceValidationLeaseResult(EvidenceValidationVerdict.LEASE_FENCE_REJECTED)
        with self._lock:
            record = self._scoped(validation_id, organization_id)
            if record is None:
                return EvidenceValidationLeaseResult(EvidenceValidationVerdict.NOT_FOUND)
            if record.phase is EvidenceValidationPhase.TERMINAL:
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.NOT_FOUND, record.request
                )
            request = record.request
        if not self._current(record, now):
            return EvidenceValidationLeaseResult(
                EvidenceValidationVerdict.CONTEXT_UNAVAILABLE, request
            )
        with self._coordinator.mutation(), self._lock:
            record = self._scoped(validation_id, organization_id)
            if record is None or record.phase is EvidenceValidationPhase.TERMINAL:
                return EvidenceValidationLeaseResult(EvidenceValidationVerdict.NOT_FOUND, request)
            if not self._locally_current(record, now):
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.CONTEXT_UNAVAILABLE, record.request
                )
            if record.lease is not None and now < record.lease.expires_at:
                if record.lease.fence == fence or (
                    fence.has_valid_ids()
                    and fence.lease_generation == 0
                    and record.lease.fence.worker_instance_id == fence.worker_instance_id
                    and record.lease.fence.lease_acquisition_id == fence.lease_acquisition_id
                ):
                    return EvidenceValidationLeaseResult(
                        EvidenceValidationVerdict.LEASED,
                        record.request,
                        record.lease.fence,
                        record.lease.expires_at,
                    )
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.LEASE_FENCE_REJECTED, record.request
                )
            if not fence.has_valid_ids() or fence.lease_generation != 0:
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.LEASE_FENCE_REJECTED, record.request
                )
            assert record.used_acquisition_ids is not None
            if fence.lease_acquisition_id in record.used_acquisition_ids:
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.LEASE_FENCE_REJECTED, record.request
                )
            policy = self._policy_for(record)
            if policy is None or policy.resource_envelope is None:
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.POLICY_UNAVAILABLE, record.request
                )
            deadline = self._deadline(record, policy)
            if now >= deadline:
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.DEADLINE_EXCEEDED, record.request
                )
            if record.attempts >= 1 + policy.resource_envelope.max_retry_attempts:
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.RETRY_EXHAUSTED, record.request
                )
            active_for_organization = sum(
                1
                for candidate in self._records.values()
                if (
                    candidate.item.declaration.subject.organization_id
                    == record.item.declaration.subject.organization_id
                    and candidate.lease is not None
                    and now < candidate.lease.expires_at
                )
            )
            if active_for_organization >= policy.resource_envelope.max_tenant_concurrency:
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.CONCURRENCY_LIMIT, record.request
                )
            accepted = LeaseFence(
                fence.worker_instance_id, fence.lease_acquisition_id, record.last_generation + 1
            )
            expires = min(
                now + timedelta(seconds=policy.resource_envelope.lease_duration_seconds), deadline
            )
            raw: dict[str, object] = {
                "kind": "external-evidence-validation-claimed",
                "version": _VERSION,
                "validationId": validation_id,
                **_fence_wire(accepted),
                "leaseExpiresAt": _wire_time(expires),
            }
            raw["eventDigest"] = _event_digest(raw)
            try:
                self._append_apply(raw)
            except JournalSealedError:
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.STORAGE_UNAVAILABLE, record.request
                )
            return EvidenceValidationLeaseResult(
                EvidenceValidationVerdict.LEASED, record.request, accepted, expires
            )

    def heartbeat(
        self,
        validation_id: str,
        fence: LeaseFence,
        *,
        organization_id: str | None,
        now: datetime,
    ) -> EvidenceValidationLeaseResult:
        _wire_time(now)
        with self._lock:
            record = self._scoped(validation_id, organization_id)
            if record is None:
                return EvidenceValidationLeaseResult(EvidenceValidationVerdict.NOT_FOUND)
            request = record.request
            policy = self._policy_for(record)
            if policy is not None and now >= self._deadline(record, policy):
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.DEADLINE_EXCEEDED, record.request
                )
            if not self._has_current_fence(record, fence, now):
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.LEASE_FENCE_REJECTED, record.request
                )
        if not self._current(record, now):
            return EvidenceValidationLeaseResult(
                EvidenceValidationVerdict.CONTEXT_UNAVAILABLE, request
            )
        with self._coordinator.mutation(), self._lock:
            record = self._scoped(validation_id, organization_id)
            if record is None:
                return EvidenceValidationLeaseResult(EvidenceValidationVerdict.NOT_FOUND)
            policy = self._policy_for(record)
            if policy is not None and now >= self._deadline(record, policy):
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.DEADLINE_EXCEEDED, record.request
                )
            if not self._has_current_fence(record, fence, now):
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.LEASE_FENCE_REJECTED, record.request
                )
            if not self._locally_current(record, now):
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.CONTEXT_UNAVAILABLE, record.request
                )
            policy = self._policy_for(record)
            if policy is None or policy.resource_envelope is None:
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.POLICY_UNAVAILABLE, record.request
                )
            deadline = self._deadline(record, policy)
            if now >= deadline:
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.DEADLINE_EXCEEDED, record.request
                )
            expires = min(
                now + timedelta(seconds=policy.resource_envelope.lease_duration_seconds), deadline
            )
            raw: dict[str, object] = {
                "kind": "external-evidence-validation-heartbeated",
                "version": _VERSION,
                "validationId": validation_id,
                **_fence_wire(fence),
                "leaseExpiresAt": _wire_time(expires),
            }
            raw["eventDigest"] = _event_digest(raw)
            try:
                self._append_apply(raw)
            except JournalSealedError:
                return EvidenceValidationLeaseResult(
                    EvidenceValidationVerdict.STORAGE_UNAVAILABLE, record.request
                )
            return EvidenceValidationLeaseResult(
                EvidenceValidationVerdict.LEASED, record.request, fence, expires
            )

    def input_for(
        self, validation_id: str, fence: LeaseFence, *, organization_id: str | None
    ) -> EvidenceValidationInputResult:
        now = self._clock()
        with self._lock:
            record = self._scoped(validation_id, organization_id)
            if record is None:
                return EvidenceValidationInputResult(EvidenceValidationVerdict.NOT_FOUND)
            if not self._has_current_fence(record, fence, now):
                return EvidenceValidationInputResult(
                    EvidenceValidationVerdict.LEASE_FENCE_REJECTED, record.request
                )
            if self._input_capabilities is None:
                return EvidenceValidationInputResult(
                    EvidenceValidationVerdict.INPUT_UNAVAILABLE, record.request
                )
            item, request, context = record.item, record.request, record.context
        if not self._current(record, now):
            return EvidenceValidationInputResult(
                EvidenceValidationVerdict.CONTEXT_UNAVAILABLE, request
            )
        with self._coordinator.guarded_read(), self._lock:
            record = self._scoped(validation_id, organization_id)
            policy = self._policy_for(record) if record is not None else None
            if (
                record is None
                or policy is None
                or now >= self._deadline(record, policy)
                or not self._locally_current(record, now)
                or not self._has_current_fence(record, fence, now)
            ):
                return EvidenceValidationInputResult(
                    EvidenceValidationVerdict.LEASE_FENCE_REJECTED, request
                )
        bindings = self._input_capabilities.issue_input(item=item, request=request, context=context)
        if bindings is None:
            return EvidenceValidationInputResult(
                EvidenceValidationVerdict.INPUT_UNAVAILABLE, request
            )
        commit_now = self._clock()
        with self._coordinator.guarded_read(), self._lock:
            record = self._scoped(validation_id, organization_id)
            policy = self._policy_for(record) if record is not None else None
            if (
                record is None
                or record.request != request
                or record.context != context
                or policy is None
                or commit_now >= self._deadline(record, policy)
                or not self._locally_current(record, commit_now)
                or not self._has_current_fence(record, fence, commit_now)
            ):
                return EvidenceValidationInputResult(
                    EvidenceValidationVerdict.LEASE_FENCE_REJECTED, request
                )
        return EvidenceValidationInputResult(
            EvidenceValidationVerdict.LEASED,
            request,
            context,
            bindings,
            policy,
        )

    def record_measurement(
        self,
        validation_id: str,
        fence: LeaseFence,
        payload: ExternalEvidenceMeasurementPayloadV1,
        *,
        organization_id: str | None,
        now: datetime,
    ) -> EvidenceValidationMeasurementResult:
        _wire_time(now)
        with self._lock:
            record = self._scoped(validation_id, organization_id)
            if record is None:
                return EvidenceValidationMeasurementResult(EvidenceValidationVerdict.NOT_FOUND)
            if record.result is not None:
                if record.result.measurement_payload == payload:
                    return EvidenceValidationMeasurementResult(
                        EvidenceValidationVerdict(record.result.core_verdict.value), record.result
                    )
                return EvidenceValidationMeasurementResult(
                    EvidenceValidationVerdict.PAYLOAD_DIVERGENCE
                )
            if not self._has_current_fence(record, fence, now):
                return EvidenceValidationMeasurementResult(
                    EvidenceValidationVerdict.LEASE_FENCE_REJECTED
                )
        # Trusted evidence/policy ports are deliberately called before the
        # currentness coordinator. The final guarded block only uses local
        # projections and holds through the terminal journal append.
        if not self._current(record, now):
            return EvidenceValidationMeasurementResult(
                EvidenceValidationVerdict.CONTEXT_UNAVAILABLE
            )
        with self._coordinator.guarded_read(), self._lock:
            record = self._scoped(validation_id, organization_id)
            if record is None:
                return EvidenceValidationMeasurementResult(EvidenceValidationVerdict.NOT_FOUND)
            if record.result is not None:
                if record.result.measurement_payload == payload:
                    return EvidenceValidationMeasurementResult(
                        EvidenceValidationVerdict(record.result.core_verdict.value), record.result
                    )
                return EvidenceValidationMeasurementResult(
                    EvidenceValidationVerdict.PAYLOAD_DIVERGENCE
                )
            if not self._has_current_fence(record, fence, now):
                return EvidenceValidationMeasurementResult(
                    EvidenceValidationVerdict.LEASE_FENCE_REJECTED
                )
            policy = self._policy_for(record)
            if policy is None or now >= self._deadline(record, policy):
                return EvidenceValidationMeasurementResult(
                    EvidenceValidationVerdict.DEADLINE_EXCEEDED
                )
            if not self._locally_current(record, now):
                return EvidenceValidationMeasurementResult(
                    EvidenceValidationVerdict.CONTEXT_UNAVAILABLE
                )
            verdict, reason = self._adjudicate(record, payload)
            evidence_record = ExternalEvidenceRecordV1(
                evidence_record_id="external-evidence-record-"
                + hashlib.sha256(validation_id.encode()).hexdigest()[:32],
                validation_id=validation_id,
                subject_digest=record.request.subject_digest,
                evidence_manifest_digest=record.request.evidence_manifest_digest,
                target_dsm_observed_sha256=record.request.target_dsm_observed_sha256,
                policy_digest=record.request.policy_digest,
                measurement_payload=payload,
                core_verdict=verdict,
                core_reason=reason,
                core_recorded_at=now,
            ).sealed()
            raw: dict[str, object] = {
                "kind": "external-evidence-validation-terminal",
                "version": _VERSION,
                "validationId": validation_id,
                **_fence_wire(fence),
                "record": external_evidence_record_wire_dict(evidence_record),
            }
            raw["eventDigest"] = _event_digest(raw)
            try:
                self._append_apply(raw)
            except JournalSealedError:
                return EvidenceValidationMeasurementResult(
                    EvidenceValidationVerdict.STORAGE_UNAVAILABLE
                )
            return EvidenceValidationMeasurementResult(
                EvidenceValidationVerdict(verdict.value), evidence_record
            )

    def record_incomplete_failure(
        self,
        validation_id: str,
        fence: LeaseFence,
        *,
        organization_id: str | None,
        now: datetime,
        reason: str,
    ) -> EvidenceValidationMeasurementResult:
        if not reason or reason != reason.strip() or not reason.isupper():
            raise ValueError("failure reason must be a typed uppercase code")
        _wire_time(now)
        with self._coordinator.guarded_read(), self._lock:
            record = self._scoped(validation_id, organization_id)
            if record is None:
                return EvidenceValidationMeasurementResult(EvidenceValidationVerdict.NOT_FOUND)
            if record.result is not None:
                return EvidenceValidationMeasurementResult(
                    EvidenceValidationVerdict.REJECTED, record.result
                )
            if not self._has_current_fence(record, fence, now):
                return EvidenceValidationMeasurementResult(
                    EvidenceValidationVerdict.LEASE_FENCE_REJECTED
                )
            policy = self._policy_for(record)
            if policy is None or now >= self._deadline(record, policy):
                return EvidenceValidationMeasurementResult(
                    EvidenceValidationVerdict.DEADLINE_EXCEEDED
                )
            evidence_record = ExternalEvidenceRecordV1(
                evidence_record_id="external-evidence-record-"
                + hashlib.sha256(validation_id.encode()).hexdigest()[:32],
                validation_id=validation_id,
                subject_digest=record.request.subject_digest,
                evidence_manifest_digest=record.request.evidence_manifest_digest,
                target_dsm_observed_sha256=record.request.target_dsm_observed_sha256,
                policy_digest=record.request.policy_digest,
                core_verdict=EvidenceCoreVerdict.REJECTED,
                core_reason=reason,
                core_recorded_at=now,
            ).sealed()
            raw: dict[str, object] = {
                "kind": "external-evidence-validation-terminal",
                "version": _VERSION,
                "validationId": validation_id,
                **_fence_wire(fence),
                "record": external_evidence_record_wire_dict(evidence_record),
            }
            raw["eventDigest"] = _event_digest(raw)
            try:
                self._append_apply(raw)
            except JournalSealedError:
                return EvidenceValidationMeasurementResult(
                    EvidenceValidationVerdict.STORAGE_UNAVAILABLE
                )
            return EvidenceValidationMeasurementResult(
                EvidenceValidationVerdict.REJECTED, evidence_record
            )

    def record_for_use(
        self, record_digest: str, *, subject: SealedExternalSubjectV1, policy_digest: str
    ) -> tuple[ExternalEvidenceRecordV1, ExternalEvidenceMeasurementContextV1] | None:
        """Private next-stage resolver; validates history without making it current."""
        with self._lock:
            for record in self._records.values():
                result = record.result
                if (
                    result is not None
                    and result.evidence_record_digest == record_digest
                    and result.core_verdict is EvidenceCoreVerdict.VALIDATED
                    and record.item.manifest is not None
                    and record.item.manifest.subject == subject
                    and result.policy_digest == policy_digest
                ):
                    return result, record.context
        return None

    def record_for_current_use(
        self, record_digest: str, *, subject: SealedExternalSubjectV1, policy_digest: str
    ) -> tuple[ExternalEvidenceRecordV1, ExternalEvidenceMeasurementContextV1] | None:
        """Resolve one retained result only if its exact authority remains current.

        The first source and policy reads deliberately occur before the shared
        coordinator: either may be backed by an independent authority port.
        The guarded recheck uses only retained Core projections before handing
        a result to a new downstream use.
        """
        now = self._clock()
        with self._lock:
            matching = next(
                (
                    record
                    for record in self._records.values()
                    if (
                        record.result is not None
                        and record.result.evidence_record_digest == record_digest
                        and record.result.core_verdict is EvidenceCoreVerdict.VALIDATED
                        and record.item.manifest is not None
                        and record.item.manifest.subject == subject
                        and record.result.policy_digest == policy_digest
                    )
                ),
                None,
            )
            if matching is None or matching.result is None:
                return None
            snapshot_item, snapshot_result, snapshot_context = (
                matching.item,
                matching.result,
                matching.context,
            )
        current_item = self._evidence.resolve_for_validation(matching.evidence_ref)
        selected = self._policy_registry.select_for_use("EVIDENCE", (subject,))
        current_context = (
            self._context_authority.resolve_for_validation(
                subject=subject,
                evidence_manifest_digest=snapshot_result.evidence_manifest_digest,
                target_dsm_artifact_id=(
                    snapshot_item.manifest.target_dsm_artifact_id
                    if snapshot_item.manifest is not None
                    else ""
                ),
                target_dsm_observed_sha256=snapshot_result.target_dsm_observed_sha256,
                policy_digest=policy_digest,
                now=now,
            )
            if snapshot_item.manifest is not None
            else None
        )
        if (
            current_item != snapshot_item
            or selected.status is not PolicySelectionStatus.ACTIVE
            or selected.policy is None
            or selected.policy.policy_digest != policy_digest
            or current_context != snapshot_context
            or not self._context_binds(snapshot_context, snapshot_item, selected.policy, now)
        ):
            return None
        with self._coordinator.guarded_read(), self._lock:
            # Only retained projections are touched under the final guard.
            resolved = self._records.get(snapshot_result.validation_id)
            policy = self._policy_for(resolved) if resolved is not None else None
            if (
                resolved is None
                or resolved.item != snapshot_item
                or resolved.result != snapshot_result
                or resolved.context != snapshot_context
                or policy is None
                or policy.policy_digest != policy_digest
                or not self._context_binds(snapshot_context, snapshot_item, policy, now)
            ):
                return None
            return snapshot_result, snapshot_context

    def sealed_evidence_object_for(
        self, record_digest: str, *, subject: SealedExternalSubjectV1, policy_digest: str
    ) -> tuple[str, ExternalEvidenceManifestV1] | None:
        """Return the sealed evidence object key/manifest behind one VALIDATED record.

        Read-only projection for a worker capability issuer that already holds
        current launch authority; it grants no use by itself.
        """
        with self._lock:
            for record in self._records.values():
                result = record.result
                manifest = record.item.manifest
                if (
                    result is not None
                    and manifest is not None
                    and result.evidence_record_digest == record_digest
                    and result.core_verdict is EvidenceCoreVerdict.VALIDATED
                    and manifest.subject == subject
                    and result.policy_digest == policy_digest
                    and manifest.evidence_manifest_digest == result.evidence_manifest_digest
                ):
                    return record.item.object_key, manifest
        return None

    def record_for_locally_current_use(
        self, record_digest: str, *, subject: SealedExternalSubjectV1, policy_digest: str
    ) -> tuple[ExternalEvidenceRecordV1, ExternalEvidenceMeasurementContextV1] | None:
        """Final retained-projection check for a caller already holding the coordinator.

        This deliberately performs no evidence, policy-authority, context-authority
        resolution, storage, or WorkOrder callback.  The caller must have completed
        ``record_for_current_use`` before entering its final coordinator guard.
        """
        now = self._clock()
        with self._coordinator.guarded_read(), self._lock:
            matching = next(
                (
                    record
                    for record in self._records.values()
                    if (
                        record.result is not None
                        and record.result.evidence_record_digest == record_digest
                        and record.result.core_verdict is EvidenceCoreVerdict.VALIDATED
                        and record.item.manifest is not None
                        and record.item.manifest.subject == subject
                        and record.result.policy_digest == policy_digest
                    )
                ),
                None,
            )
            if matching is None or matching.result is None:
                return None
            policy = self._policy_for(matching)
            if (
                policy is None
                or policy.policy_digest != policy_digest
                or not self._policy_registry.locally_current_use_permitted(
                    policy_digest,
                    use="EVIDENCE",
                    subjects=(subject,),
                    at=now,
                )
                or not self._context_authority.is_current(matching.context)
                or not self._context_binds(matching.context, matching.item, policy, now)
            ):
                return None
            return matching.result, matching.context

    def validated_record_digests_for(
        self, *, subject: SealedExternalSubjectV1, policy_digest: str
    ) -> tuple[str, ...]:
        """Return only retained validated-record identities for an exact scope.

        The next-stage evaluator must still resolve each digest through
        :meth:`record_for_current_use`; this bounded index is not authority.
        """
        with self._lock:
            return tuple(
                result.evidence_record_digest
                for record in self._records.values()
                if (
                    (result := record.result) is not None
                    and result.core_verdict is EvidenceCoreVerdict.VALIDATED
                    and result.evidence_record_digest is not None
                    and record.item.manifest is not None
                    and record.item.manifest.subject == subject
                    and result.policy_digest == policy_digest
                )
            )

    def terminal_records_for_evidence(
        self, evidence_ref: str
    ) -> tuple[ExternalEvidenceRecordV1, ...]:
        """Return occurred terminal measurements for the scoped human projection.

        This is historical disclosure only.  It deliberately returns no
        capability, object key, context, worker identity, or current-use
        authority; callers must project the bounded aggregates they display.
        """
        with self._lock:
            return tuple(
                result
                for record in self._records.values()
                if (
                    record.evidence_ref == evidence_ref
                    and (result := record.result) is not None
                    and result.measurement_payload is not None
                )
            )

    def _context_binds(
        self,
        context: ExternalEvidenceMeasurementContextV1,
        item: EvidenceItem,
        policy: ExternalValidationPolicyV1,
        now: datetime,
    ) -> bool:
        manifest = item.manifest
        return bool(
            manifest
            and context.context_digest == context.canonical_digest()
            and context.is_active_at(now)
            and context.subject == manifest.subject
            and context.evidence_manifest_digest == manifest.evidence_manifest_digest
            and context.evidence_observed_sha256 == manifest.observed_object_digest
            and context.evidence_observed_size_bytes == manifest.observed_size_bytes
            and context.target_dsm_artifact_id == manifest.target_dsm_artifact_id
            and context.target_dsm_observed_sha256 == manifest.target_dsm_observed_sha256
            and context.policy_digest == policy.policy_digest
            and context.rule_id in policy.evidence_rule_ids
        )

    def _policy_for(self, record: _Record) -> ExternalValidationPolicyV1 | None:
        selected = self._policy_registry.resolve(record.request.policy_digest)
        policy = selected.policy
        return policy if selected.status is PolicySelectionStatus.ACTIVE else None

    def _is_pending_execution(self, record: _Record, now: datetime) -> bool:
        """Whether a request can still consume a queue or pending-work slot.

        The policy snapshot remains historical evidence; its immutable envelope
        bounds admission even after a later policy lifecycle change.  We do not
        manufacture a terminal/revocation event merely to remove expired work
        from the operational queue projection.
        """
        if record.phase is EvidenceValidationPhase.TERMINAL:
            return False
        policy = self._historical_policy_for_request(record.request)
        if policy is None or policy.resource_envelope is None:
            return False
        if now >= self._deadline(record, policy):
            return False
        if record.attempts >= 1 + policy.resource_envelope.max_retry_attempts:
            return False
        return record.lease is None or now >= record.lease.expires_at

    def _current(self, record: _Record, now: datetime) -> bool:
        item = self._evidence.resolve_for_validation(record.evidence_ref)
        manifest = record.item.manifest
        if item is None or manifest is None or item.manifest != manifest:
            return False
        selected = self._policy_registry.select_for_use("EVIDENCE", (manifest.subject,))
        policy = selected.policy
        context = (
            self._context_authority.resolve_for_validation(
                subject=manifest.subject,
                evidence_manifest_digest=record.request.evidence_manifest_digest,
                target_dsm_artifact_id=manifest.target_dsm_artifact_id,
                target_dsm_observed_sha256=record.request.target_dsm_observed_sha256,
                policy_digest=record.request.policy_digest,
                now=now,
            )
            if (
                selected.status is PolicySelectionStatus.ACTIVE
                and policy is not None
                and policy.policy_digest == record.request.policy_digest
            )
            else None
        )
        return bool(
            selected.status is PolicySelectionStatus.ACTIVE
            and policy is not None
            and policy.policy_digest == record.request.policy_digest
            and context == record.context
            and self._context_binds(record.context, record.item, policy, now)
        )

    def _locally_current(self, record: _Record, now: datetime) -> bool:
        """Final no-I/O currentness check while the coordinator is held."""
        policy = self._policy_for(record)
        manifest = record.item.manifest
        return bool(
            manifest is not None
            and policy is not None
            and policy.policy_digest == record.request.policy_digest
            and self._policy_registry.locally_current_use_permitted(
                record.request.policy_digest,
                use="EVIDENCE",
                subjects=(manifest.subject,),
                at=now,
            )
            and self._context_authority.is_current(record.context)
            and self._context_binds(record.context, record.item, policy, now)
        )

    def _scoped(self, validation_id: str, organization_id: str | None) -> _Record | None:
        record = self._records.get(validation_id)
        if record is None:
            return None
        if (
            organization_id is not None
            and record.item.declaration.subject.organization_id != organization_id
        ):
            return None
        return record

    @staticmethod
    def _has_current_fence(record: _Record, fence: LeaseFence, now: datetime) -> bool:
        return (
            record.lease is not None
            and now < record.lease.expires_at
            and record.lease.fence == fence
        )

    @staticmethod
    def _deadline(record: _Record, policy: ExternalValidationPolicyV1) -> datetime:
        assert policy.resource_envelope is not None
        return record.request.issued_at + timedelta(
            seconds=policy.resource_envelope.max_deadline_seconds
        )

    def _adjudicate(
        self, record: _Record, payload: ExternalEvidenceMeasurementPayloadV1
    ) -> tuple[EvidenceCoreVerdict, str | None]:
        context = record.context
        if (
            payload.validation_id != record.request.validation_id
            or payload.evidence_manifest_digest != record.request.evidence_manifest_digest
            or payload.target_dsm_observed_sha256 != record.request.target_dsm_observed_sha256
            or payload.policy_digest != record.request.policy_digest
        ):
            return EvidenceCoreVerdict.REJECTED, "MEASUREMENT_BINDING_INVALID"
        if (
            not context.minimum_checkpoint_count
            <= payload.measured_checkpoint_count
            <= context.maximum_checkpoint_count
        ):
            return EvidenceCoreVerdict.REJECTED, "CHECKPOINT_COUNT_OUT_OF_RANGE"
        if abs(payload.mean_error_m) > context.maximum_abs_mean_error_m:
            return EvidenceCoreVerdict.REJECTED, "MEAN_ERROR_EXCEEDED"
        if payload.rmse_m > context.maximum_rmse_m:
            return EvidenceCoreVerdict.REJECTED, "RMSE_EXCEEDED"
        if payload.max_abs_error_m > context.maximum_abs_error_m:
            return EvidenceCoreVerdict.REJECTED, "MAX_ABS_ERROR_EXCEEDED"
        return EvidenceCoreVerdict.VALIDATED, None

    def _append_apply(
        self,
        raw: dict[str, object],
        *,
        item: EvidenceItem | None = None,
        historical_context: ExternalEvidenceMeasurementContextV1 | None = None,
    ) -> None:
        self._journal.append(raw)
        self._apply(raw, item=item, historical_context=historical_context)

    def _apply(
        self,
        raw: object,
        *,
        item: EvidenceItem | None = None,
        historical_context: ExternalEvidenceMeasurementContextV1 | None = None,
    ) -> None:
        try:
            if not isinstance(raw, dict) or raw.get("eventDigest") != _event_digest(raw):
                raise ValueError("event digest is invalid")
            if type(raw.get("version")) is not int or raw["version"] != _VERSION:
                raise ValueError("event version is invalid")
            kind = raw.get("kind")
            if kind == "external-evidence-validation-issued":
                self._apply_issued(raw, item=item, historical_context=historical_context)
            elif kind == "external-evidence-validation-claimed":
                self._apply_claimed(raw)
            elif kind == "external-evidence-validation-heartbeated":
                self._apply_heartbeated(raw)
            elif kind == "external-evidence-validation-terminal":
                self._apply_terminal(raw)
            else:
                raise ValueError("unknown event kind")
        except (KeyError, TypeError, ValueError) as exc:
            raise ExternalEvidenceValidationRecoveryError(str(exc)) from exc

    def _apply_issued(
        self,
        raw: dict[str, Any],
        *,
        item: EvidenceItem | None,
        historical_context: ExternalEvidenceMeasurementContextV1 | None,
    ) -> None:
        expected = {"kind", "version", "eventDigest", "evidenceRef", "request", "context"}
        if set(raw) != expected:
            raise ValueError("issued event is not exact")
        evidence_ref = str(raw["evidenceRef"])
        item = item or self._evidence.resolve_for_validation(evidence_ref)
        if item is None:
            raise ValueError("issued evidence is unavailable")
        request = ExternalEvidenceValidationRequestV1.model_validate(raw["request"])
        context = ExternalEvidenceMeasurementContextV1.model_validate(raw["context"])
        if request.validation_id in self._records or item.manifest is None:
            raise ValueError("duplicate or unsealed validation request")
        policy = self._historical_policy_for_request(request)
        if policy is None or not self._context_binds(context, item, policy, request.issued_at):
            raise ValueError("issued authority binding is invalid")
        manifest = item.manifest
        assert manifest is not None
        if (
            context.context_digest is None
            or request.evidence_manifest_digest != manifest.evidence_manifest_digest
            or request.subject_digest != manifest.subject_digest
            or request.target_dsm_observed_sha256 != manifest.target_dsm_observed_sha256
            or request.policy_id != policy.policy_id
            or request.policy_version != policy.version
            or request.policy_digest != policy.policy_digest
            or request.idempotency_key != "evidence-seal:" + evidence_ref
        ):
            raise ValueError("issued request binding is invalid")
        historical_context = historical_context or (
            self._context_authority.resolve_historical_for_validation(
                context_digest=context.context_digest,
                subject=manifest.subject,
                evidence_manifest_digest=request.evidence_manifest_digest,
                target_dsm_artifact_id=manifest.target_dsm_artifact_id,
                target_dsm_observed_sha256=request.target_dsm_observed_sha256,
                policy_digest=request.policy_digest,
                issued_at=request.issued_at,
            )
        )
        if historical_context != context:
            raise ValueError("issued context historical anchor is invalid")
        natural = (
            request.evidence_manifest_digest,
            request.policy_digest,
            context.context_digest,
        )
        expected_id = (
            "external-evidence-validation-"
            + hashlib.sha256("\0".join(natural).encode()).hexdigest()[:32]
        )
        if request.validation_id != expected_id:
            raise ValueError("issued validation identity is invalid")
        if natural in self._natural:
            raise ValueError("duplicate validation natural key")
        self._records[request.validation_id] = _Record(evidence_ref, request, context, item)
        self._natural[natural] = request.validation_id

    def _apply_claimed(self, raw: dict[str, Any]) -> None:
        expected = {
            "kind",
            "version",
            "eventDigest",
            "validationId",
            "workerInstanceId",
            "leaseAcquisitionId",
            "leaseGeneration",
            "leaseExpiresAt",
        }
        if set(raw) != expected:
            raise ValueError("claimed event is not exact")
        record = self._records[str(raw["validationId"])]
        if record.phase is EvidenceValidationPhase.TERMINAL or record.result is not None:
            raise ValueError("terminal validation cannot be claimed")
        if record.phase not in {EvidenceValidationPhase.QUEUED, EvidenceValidationPhase.LEASED}:
            raise ValueError("claimed validation predecessor phase is invalid")
        fence = _fence_from_wire(raw)
        expires = _parse_time(raw["leaseExpiresAt"], "leaseExpiresAt")
        policy = self._historical_policy_for_request(record.request)
        if fence.lease_generation != record.last_generation + 1:
            raise ValueError("lease generation is not monotonic")
        if (
            policy is None
            or expires <= record.request.issued_at
            or expires > self._deadline(record, policy)
        ):
            raise ValueError("evidence validation lease exceeds absolute deadline")
        assert record.used_acquisition_ids is not None
        if fence.lease_acquisition_id in record.used_acquisition_ids:
            raise ValueError("lease acquisition is reused")
        if record.lease is not None and expires <= record.lease.expires_at:
            raise ValueError("claimed validation does not follow the prior lease")
        record.lease = _Lease(fence, expires)
        record.last_generation = fence.lease_generation
        record.used_acquisition_ids.add(fence.lease_acquisition_id)
        record.attempts += 1
        record.phase = EvidenceValidationPhase.LEASED

    def _apply_heartbeated(self, raw: dict[str, Any]) -> None:
        expected = {
            "kind",
            "version",
            "eventDigest",
            "validationId",
            "workerInstanceId",
            "leaseAcquisitionId",
            "leaseGeneration",
            "leaseExpiresAt",
        }
        if set(raw) != expected:
            raise ValueError("heartbeat event is not exact")
        record = self._records[str(raw["validationId"])]
        if record.phase is not EvidenceValidationPhase.LEASED or record.result is not None:
            raise ValueError("terminal validation cannot be heartbeated")
        fence = _fence_from_wire(raw)
        if record.lease is None or record.lease.fence != fence:
            raise ValueError("heartbeat fence is stale")
        expires = _parse_time(raw["leaseExpiresAt"], "leaseExpiresAt")
        policy = self._historical_policy_for_request(record.request)
        if policy is None or expires > self._deadline(record, policy):
            raise ValueError("evidence validation heartbeat exceeds absolute deadline")
        if expires < record.lease.expires_at:
            raise ValueError("evidence validation heartbeat shortens the current lease")
        record.lease = _Lease(fence, expires)

    def _apply_terminal(self, raw: dict[str, Any]) -> None:
        expected = {
            "kind",
            "version",
            "eventDigest",
            "validationId",
            "workerInstanceId",
            "leaseAcquisitionId",
            "leaseGeneration",
            "record",
        }
        if set(raw) != expected:
            raise ValueError("terminal event is not exact")
        record = self._records[str(raw["validationId"])]
        if record.phase is not EvidenceValidationPhase.LEASED or record.result is not None:
            raise ValueError("terminal validation already has a result")
        fence = _fence_from_wire(raw)
        result = ExternalEvidenceRecordV1.model_validate(raw["record"])
        policy = self._historical_policy_for_request(record.request)
        if (
            record.lease is None
            or record.lease.fence != fence
            or result.validation_id != record.request.validation_id
            or result.evidence_record_id
            != "external-evidence-record-"
            + hashlib.sha256(record.request.validation_id.encode()).hexdigest()[:32]
            or result.subject_digest != record.request.subject_digest
            or result.evidence_manifest_digest != record.request.evidence_manifest_digest
            or result.target_dsm_observed_sha256 != record.request.target_dsm_observed_sha256
            or result.policy_digest != record.request.policy_digest
            or result.core_recorded_at < record.request.issued_at
            or result.core_recorded_at >= record.lease.expires_at
            or policy is None
            or result.core_recorded_at >= self._deadline(record, policy)
        ):
            raise ValueError("terminal binding is invalid")
        if result.evidence_record_digest != result.canonical_digest():
            raise ValueError("terminal record is unsealed")
        if result.measurement_payload is not None:
            expected_verdict, expected_reason = self._adjudicate(record, result.measurement_payload)
            if result.core_verdict is not expected_verdict or result.core_reason != expected_reason:
                raise ValueError("terminal Core adjudication is invalid")
        elif result.core_verdict is not EvidenceCoreVerdict.REJECTED:
            raise ValueError("incomplete terminal verdict is invalid")
        record.result = result
        record.phase = EvidenceValidationPhase.TERMINAL
        record.lease = None

    def _policy_for_request(
        self, request: ExternalEvidenceValidationRequestV1
    ) -> ExternalValidationPolicyV1 | None:
        resolved = self._policy_registry.resolve(request.policy_digest)
        policy = resolved.policy
        if (
            resolved.status is not PolicySelectionStatus.ACTIVE
            or policy is None
            or policy.policy_id != request.policy_id
            or policy.version != request.policy_version
        ):
            return None
        return policy

    def _historical_policy_for_request(
        self, request: ExternalEvidenceValidationRequestV1
    ) -> ExternalValidationPolicyV1 | None:
        """Resolve retained exact policy content without reopening current authority."""
        resolved = self._policy_registry.resolve(request.policy_digest)
        policy = resolved.policy
        if (
            policy is None
            or policy.policy_digest != request.policy_digest
            or policy.policy_id != request.policy_id
            or policy.version != request.policy_version
        ):
            return None
        return policy


def mount_external_evidence_validations(
    app: FastAPI, store: ExternalEvidenceValidationStore
) -> None:
    """Mount the worker-only evidence-validation plane; no human route writes facts."""
    router = APIRouter(prefix="/v1/internal/external-validation", tags=["external-validation"])
    worker = require_permission(Permission.PROCESSING_WORK)

    def fence_from_headers(
        worker_instance_id: str = Header(alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str = Header(alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: int = Header(alias="X-KSI-Lease-Generation"),
    ) -> LeaseFence:
        return LeaseFence(worker_instance_id, lease_acquisition_id, lease_generation)

    def raise_worker_error(verdict: EvidenceValidationVerdict) -> None:
        status = {
            EvidenceValidationVerdict.NOT_FOUND: 404,
            EvidenceValidationVerdict.LEASE_FENCE_REJECTED: 409,
            EvidenceValidationVerdict.POLICY_UNAVAILABLE: 409,
            EvidenceValidationVerdict.CONTEXT_UNAVAILABLE: 409,
            EvidenceValidationVerdict.CONTEXT_BINDING_REJECTED: 409,
            EvidenceValidationVerdict.INPUT_UNAVAILABLE: 503,
            EvidenceValidationVerdict.PAYLOAD_DIVERGENCE: 409,
            EvidenceValidationVerdict.RETRY_EXHAUSTED: 409,
            EvidenceValidationVerdict.DEADLINE_EXCEEDED: 409,
            EvidenceValidationVerdict.QUEUE_FULL: 409,
            EvidenceValidationVerdict.CONCURRENCY_LIMIT: 409,
            EvidenceValidationVerdict.STORAGE_UNAVAILABLE: 503,
        }.get(verdict)
        if status is not None:
            raise HTTPException(status, verdict.value)

    def lease_view(result: EvidenceValidationLeaseResult) -> ExternalEvidenceValidationLeaseView:
        fence = result.fence
        return ExternalEvidenceValidationLeaseView(
            verdict=result.verdict,
            request=result.request,
            fence=(
                ExternalEvidenceValidationLeaseFenceView(
                    worker_instance_id=fence.worker_instance_id,
                    lease_acquisition_id=fence.lease_acquisition_id,
                    lease_generation=fence.lease_generation,
                )
                if fence is not None
                else None
            ),
            lease_expires_at=result.lease_expires_at,
        )

    @router.get("/evidence-validations", response_model=ExternalEvidenceValidationPendingListView)
    def list_evidence_validations(
        limit: int = Query(default=50, ge=1, le=100),
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> ExternalEvidenceValidationPendingListView:
        return ExternalEvidenceValidationPendingListView(
            items=[
                ExternalEvidenceValidationPendingView(
                    validation_id=item.validation_id,
                    issued_at=item.issued_at,
                )
                for item in store.list_pending(limit, organization_id=principal.organization_id)
            ]
        )

    @router.post(
        "/evidence-validations/{validation_id}/lease",
        response_model=ExternalEvidenceValidationLeaseView,
    )
    def lease_evidence_validation(
        validation_id: str,
        response: Response,
        fence: LeaseFence = Depends(fence_from_headers),  # noqa: B008
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> ExternalEvidenceValidationLeaseView:
        result = store.claim(
            validation_id,
            fence,
            organization_id=principal.organization_id,
            now=datetime.now(UTC),
        )
        raise_worker_error(result.verdict)
        if result.fence is not None:
            response.headers["X-KSI-Worker-Instance-Id"] = result.fence.worker_instance_id
            response.headers["X-KSI-Lease-Acquisition-Id"] = result.fence.lease_acquisition_id
            response.headers["X-KSI-Lease-Generation"] = str(result.fence.lease_generation)
        return lease_view(result)

    @router.get(
        "/evidence-validations/{validation_id}/input",
        response_model=ExternalEvidenceValidationInputView,
    )
    def evidence_validation_input(
        validation_id: str,
        fence: LeaseFence = Depends(fence_from_headers),  # noqa: B008
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> ExternalEvidenceValidationInputView:
        result = store.input_for(validation_id, fence, organization_id=principal.organization_id)
        raise_worker_error(result.verdict)
        return ExternalEvidenceValidationInputView(
            verdict=result.verdict,
            request=result.request,
            context=result.context,
            validation_policy=result.validation_policy,
            bindings=[
                ExternalEvidenceValidationInputBindingView(
                    role=binding.role,
                    artifact_id=binding.artifact_id,
                    observed_sha256=binding.observed_sha256,
                    observed_size_bytes=binding.observed_size_bytes,
                    content_type=binding.content_type,
                    download_url=binding.download_url,
                    required_headers=binding.required_headers,
                )
                for binding in result.bindings
            ],
        )

    @router.post(
        "/evidence-validations/{validation_id}/heartbeat",
        response_model=ExternalEvidenceValidationLeaseView,
    )
    def heartbeat_evidence_validation(
        validation_id: str,
        response: Response,
        fence: LeaseFence = Depends(fence_from_headers),  # noqa: B008
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> ExternalEvidenceValidationLeaseView:
        result = store.heartbeat(
            validation_id,
            fence,
            organization_id=principal.organization_id,
            now=datetime.now(UTC),
        )
        raise_worker_error(result.verdict)
        if result.fence is not None:
            response.headers["X-KSI-Worker-Instance-Id"] = result.fence.worker_instance_id
            response.headers["X-KSI-Lease-Acquisition-Id"] = result.fence.lease_acquisition_id
            response.headers["X-KSI-Lease-Generation"] = str(result.fence.lease_generation)
        return lease_view(result)

    @router.post(
        "/evidence-validations/{validation_id}/measurement",
        response_model=ExternalEvidenceValidationMeasurementView,
    )
    def submit_evidence_measurement(
        validation_id: str,
        payload: ExternalEvidenceMeasurementPayloadV1,
        fence: LeaseFence = Depends(fence_from_headers),  # noqa: B008
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> ExternalEvidenceValidationMeasurementView:
        result = store.record_measurement(
            validation_id,
            fence,
            payload,
            organization_id=principal.organization_id,
            now=datetime.now(UTC),
        )
        raise_worker_error(result.verdict)
        return ExternalEvidenceValidationMeasurementView(
            verdict=result.verdict, record=result.record
        )

    @router.post(
        "/evidence-validations/{validation_id}/incomplete-failure",
        response_model=ExternalEvidenceValidationMeasurementView,
    )
    def incomplete_evidence_validation(
        validation_id: str,
        failure: ExternalEvidenceValidationFailureRequest,
        fence: LeaseFence = Depends(fence_from_headers),  # noqa: B008
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> ExternalEvidenceValidationMeasurementView:
        result = store.record_incomplete_failure(
            validation_id,
            fence,
            organization_id=principal.organization_id,
            now=datetime.now(UTC),
            reason=failure.reason,
        )
        raise_worker_error(result.verdict)
        return ExternalEvidenceValidationMeasurementView(
            verdict=result.verdict, record=result.record
        )

    app.state.external_evidence_validation_store = store
    app.include_router(router)


__all__ = [
    "EvidenceMeasurementContextAuthorityPort",
    "CoreEvidenceValidationInputCapabilities",
    "EvidenceValidationInputCapabilityPort",
    "EvidenceValidationIssueResult",
    "EvidenceValidationLeaseResult",
    "EvidenceValidationMeasurementResult",
    "EvidenceValidationPhase",
    "EvidenceValidationVerdict",
    "ExternalEvidenceValidationInputBinding",
    "ExternalEvidenceValidationRecoveryError",
    "ExternalEvidenceValidationStore",
    "PendingEvidenceValidation",
    "SealedEvidenceValidationPort",
    "mount_external_evidence_validations",
]
