"""Durable Core queue for inspection of sealed external reconstruction bytes.

This is Core workflow authority only: it never parses a raster, promotes an
external revision to a managed ProcessingJob, or stores signed storage URLs.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Response
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ArtifactOutcome,
    ExternalArtifactInspectionReportV1,
    ExternalArtifactInspectionRequestV1,
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
    external_artifact_inspection_report_wire_dict,
    external_artifact_inspection_request_wire_dict,
)
from ksi_event_contracts.external_display_artifact import (
    SanitizedDisplayDeclarationV1,
    SanitizedDisplayReceiptV1,
    sanitized_display_receipt_wire_dict,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from pydantic import Field, ValidationError

from ksi_core.domains.artifacts.evidence import (
    DEFAULT_VIEW_TTL,
    EvidenceStorage,
    EvidenceStorageError,
)
from ksi_core.domains.external.ingress.external_reconstruction import ExternalReconstructionRevision
from ksi_core.domains.external.ingress.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    ExternalValidationPolicySelectionBudgetExceeded,
    PolicySelectionStatus,
)
from ksi_core.foundation.api_base import CamelModel
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.leasing import LeaseFence
from ksi_core.identity.auth import Permission, Principal, require_permission

_EVENT_VERSION = 1
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
_TRANSIENT_IMMEDIATE_RULE = "TRANSIENT_IMMEDIATE_RETRY_V1"
_TRANSIENT_IMMEDIATE_FAILURES = frozenset(
    {
        "TRANSIENT_STORAGE_UNAVAILABLE",
        "TRANSIENT_SERVICE_UNAVAILABLE",
        "TRANSIENT_WORKER_INTERRUPTED",
    }
)


class ExternalArtifactInspectionRecoveryError(RuntimeError):
    """Inspection journal replay is malformed, tampered, or out of order."""


class ExternalArtifactInspectionSnapshotBudgetExceeded(RuntimeError):
    """A bounded subject snapshot contains more retained attempts than permitted."""


class InspectionVerdict(StrEnum):
    ISSUED = "ISSUED"
    IDEMPOTENT = "IDEMPOTENT"
    INSPECTION_PENDING_POLICY = "INSPECTION_PENDING_POLICY"
    SUBJECT_NOT_SEALED = "SUBJECT_NOT_SEALED"
    LEASED = "LEASED"
    LEASE_FENCE_REJECTED = "LEASE_FENCE_REJECTED"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    REPORTED = "REPORTED"
    PAYLOAD_DIVERGENCE = "PAYLOAD_DIVERGENCE"
    REPORT_BINDING_REJECTED = "REPORT_BINDING_REJECTED"
    INSPECTION_FAILED_INCOMPLETE = "INSPECTION_FAILED_INCOMPLETE"
    QUEUED = "QUEUED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    QUEUE_FULL = "QUEUE_FULL"
    CONCURRENCY_LIMIT = "CONCURRENCY_LIMIT"
    DEADLINE_EXCEEDED = "DEADLINE_EXCEEDED"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"


class InspectionPhase(StrEnum):
    INSPECTION = "INSPECTION"
    DISPLAY = "DISPLAY"
    COMPLETE = "COMPLETE"
    FAILED_INCOMPLETE = "FAILED_INCOMPLETE"


@dataclass(frozen=True, slots=True)
class InspectionIssueResult:
    verdict: InspectionVerdict
    request: ExternalArtifactInspectionRequestV1 | None = None


@dataclass(frozen=True, slots=True)
class PendingExternalInspection:
    request_id: str
    issued_at: datetime
    phase: InspectionPhase


@dataclass(frozen=True, slots=True)
class PublicInspectionSnapshot:
    """Scoped, capability-free view of facts retained for one sealed revision."""

    state: str
    request: ExternalArtifactInspectionRequestV1 | None
    phase: InspectionPhase | None
    report: ExternalArtifactInspectionReportV1 | None


class ExternalInspectionFailureRequest(CamelModel):
    """Worker's bounded incomplete-attempt fact; parser output never enters Core."""

    reason: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    detail: str | None = None


class ExternalInspectionLeaseFenceView(CamelModel):
    worker_instance_id: UUID
    lease_acquisition_id: UUID
    lease_generation: int = Field(ge=1)


class ExternalInspectionPendingItemView(CamelModel):
    request_id: str
    issued_at: datetime
    phase: InspectionPhase


class ExternalInspectionPendingListView(CamelModel):
    items: list[ExternalInspectionPendingItemView]


class ExternalInspectionLeaseView(CamelModel):
    verdict: InspectionVerdict
    request: ExternalArtifactInspectionRequestV1 | None
    lease_expires_at: datetime | None
    phase: InspectionPhase | None
    fence: ExternalInspectionLeaseFenceView | None


class ExternalArtifactInputView(CamelModel):
    entry_id: str = Field(min_length=1, max_length=255)
    kind: ProcessingArtifactKind
    observed_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    observed_size_bytes: int = Field(ge=1)
    content_type: str = Field(min_length=1, max_length=255)
    download_url: str | None
    required_headers: dict[str, str]


class ExternalInspectionInputView(CamelModel):
    verdict: InspectionVerdict
    request: ExternalArtifactInspectionRequestV1 | None
    policy: ExternalValidationPolicyV1 | None
    artifacts: list[ExternalArtifactInputView]
    phase: InspectionPhase | None
    next_action: Literal["INSPECT", "SANITIZE_DISPLAY"] | None
    accepted_report: ExternalArtifactInspectionReportV1 | None


class ExternalInspectionReportView(CamelModel):
    verdict: InspectionVerdict
    report: ExternalArtifactInspectionReportV1 | None
    phase: InspectionPhase | None


class ExternalDisplayArtifactGrantView(CamelModel):
    verdict: Literal[
        "QUEUED",
        "DISPLAY_NOT_REQUIRED",
        "LEASE_FENCE_REJECTED",
        "POLICY_UNAVAILABLE",
        "DECLARATION_RECORDED",
        "DECLARATION_DIVERGENCE",
        "OBSERVATION_MISSING",
        "OBSERVATION_MISMATCH",
        "SEALED",
        "RETRY_EXHAUSTED",
        "STORAGE_UNAVAILABLE",
        "OUTPUT_LIMIT_EXCEEDED",
    ]
    phase: Literal["NOT_REQUIRED", "QUEUED", "RUNNING", "SEALED", "RETRY_EXHAUSTED"]
    declaration: SanitizedDisplayDeclarationV1 | None
    upload_url: str | None
    required_headers: dict[str, str]


class ExternalDisplayArtifactSealView(CamelModel):
    verdict: Literal[
        "QUEUED",
        "DISPLAY_NOT_REQUIRED",
        "LEASE_FENCE_REJECTED",
        "POLICY_UNAVAILABLE",
        "DECLARATION_RECORDED",
        "DECLARATION_DIVERGENCE",
        "OBSERVATION_MISSING",
        "OBSERVATION_MISMATCH",
        "SEALED",
        "RETRY_EXHAUSTED",
        "STORAGE_UNAVAILABLE",
        "OUTPUT_LIMIT_EXCEEDED",
    ]
    phase: Literal["NOT_REQUIRED", "QUEUED", "RUNNING", "SEALED", "RETRY_EXHAUSTED"]
    receipt: SanitizedDisplayReceiptV1


class ExternalInspectionOutcomeView(CamelModel):
    artifact_id: str = Field(min_length=1, max_length=255)
    outcome: ArtifactOutcome
    reason: str | None = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Z][A-Z0-9_]{0,127}$",
    )


class PublicInspectionDetailView(CamelModel):
    state: Literal[
        "INSPECTION_PENDING_SEAL",
        "INSPECTION_PENDING_POLICY",
        "INSPECTION_PENDING",
        "INSPECTION_QUEUED",
        "INSPECTION_RUNNING",
        "INSPECTION_REPORTED",
        "INSPECTION_FAILED_INCOMPLETE",
    ]
    request: ExternalArtifactInspectionRequestV1 | None
    phase: InspectionPhase | None
    outcome: list[ExternalInspectionOutcomeView] | None
    report: ExternalArtifactInspectionReportV1 | None


class PublicDisplayDetailView(CamelModel):
    state: Literal[
        "PENDING_INSPECTION",
        "PENDING_POLICY",
        "NOT_REQUIRED",
        "QUEUED",
        "RUNNING",
        "SEALED",
        "RETRY_EXHAUSTED",
    ]
    sanitized_display_ref: str | None = Field(
        ..., pattern=r"^sda-v1-[A-Za-z0-9][A-Za-z0-9_-]{0,247}$"
    )
    receipt_digest: str | None = Field(..., pattern=r"^sha256:[0-9a-f]{64}$")


class ExternalArtifactInspectionPublicView(CamelModel):
    registration_state: Literal["REGISTERED", "SEALED"]
    seal_state: Literal["UNSEALED", "SEALED"]
    inspection: PublicInspectionDetailView
    display: PublicDisplayDetailView


class ExternalSanitizedDisplayDownloadView(CamelModel):
    sanitized_display_ref: str = Field(pattern=r"^sda-v1-[A-Za-z0-9][A-Za-z0-9_-]{0,247}$")
    receipt_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    observed_derivative_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    observed_derivative_size_bytes: int = Field(ge=1)
    observed_derivative_content_type: str = Field(min_length=1, max_length=255)
    download_url: str = Field(min_length=1)
    expires_at: datetime
    required_headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class ExternalArtifactInputV1:
    entry_id: str
    kind: ProcessingArtifactKind
    observed_sha256: str
    observed_size_bytes: int
    content_type: str
    download_url: str | None
    required_headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class ExternalInspectionInputResponse:
    verdict: InspectionVerdict
    request: ExternalArtifactInspectionRequestV1 | None = None
    policy: ExternalValidationPolicyV1 | None = None
    artifacts: tuple[ExternalArtifactInputV1, ...] = ()
    phase: InspectionPhase | None = None
    next_action: str | None = None
    accepted_report: ExternalArtifactInspectionReportV1 | None = None


@dataclass(frozen=True, slots=True)
class InspectionLeaseResult:
    verdict: InspectionVerdict
    request: ExternalArtifactInspectionRequestV1 | None = None
    lease_expires_at: datetime | None = None
    phase: InspectionPhase | None = None
    fence: LeaseFence | None = None


@dataclass(frozen=True, slots=True)
class InspectionReportResult:
    verdict: InspectionVerdict
    report: ExternalArtifactInspectionReportV1 | None = None
    phase: InspectionPhase | None = None


@dataclass(frozen=True, slots=True)
class ExternalInspectionFailureV1:
    """Core-local typed incomplete-attempt fact; raw parser input is excluded."""

    reason: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", self.reason) is None:
            raise ValueError("inspection failure reason must be a typed uppercase code")

    def canonical_digest(self) -> str:
        return _digest({"reason": self.reason})

    @property
    def retry_rule_id(self) -> str | None:
        """Closed failure classification; arbitrary uppercase text never requeues."""
        return _TRANSIENT_IMMEDIATE_RULE if self.reason in _TRANSIENT_IMMEDIATE_FAILURES else None


@dataclass(slots=True)
class _Lease:
    fence: LeaseFence
    expires_at: datetime


@dataclass(slots=True)
class _InspectionRecord:
    request: ExternalArtifactInspectionRequestV1
    artifacts: tuple[_ArtifactBinding, ...]
    state: str = "QUEUED"
    lease: _Lease | None = None
    last_generation: int = 0
    acquisition_id: str | None = None
    used_acquisition_ids: set[str] = field(default_factory=set)
    attempt_count: int = 0
    failures: int = 0
    report: ExternalArtifactInspectionReportV1 | None = None
    display_required: bool = False
    terminal_reason: str | None = None


@dataclass(frozen=True, slots=True)
class _ArtifactBinding:
    """Private durable source binding; never exposed as a worker capability."""

    entry_id: str
    kind: ProcessingArtifactKind
    observed_sha256: str
    observed_size_bytes: int
    content_type: str
    object_key: str


class SealedExternalReconstructionSnapshotPort(Protocol):
    """Read-only ingress boundary used only after Core has sealed a revision."""

    def sealed_revisions_snapshot(self) -> tuple[ExternalReconstructionRevision, ...]: ...


def _digest(payload: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def _event_digest(event: Mapping[str, object]) -> str:
    return _digest({key: value for key, value in event.items() if key != "eventDigest"})


def _wire_time(value: datetime) -> str:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError("time must be UTC timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str) or _UTC_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a strict UTC RFC3339 timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _wire_time(parsed)
    return parsed


def _required_string(raw: Mapping[str, object], field: str) -> str:
    value = raw[field]
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _fence_wire(fence: LeaseFence) -> dict[str, object]:
    if not fence.is_well_formed():
        raise ValueError("lease fence must hold UUIDv4 ids and positive generation")
    return {
        "workerInstanceId": fence.worker_instance_id,
        "leaseAcquisitionId": fence.lease_acquisition_id,
        "leaseGeneration": fence.lease_generation,
    }


def _fence_from_event(raw: Mapping[str, object]) -> LeaseFence:
    generation = raw["leaseGeneration"]
    if type(generation) is not int:
        raise ValueError("leaseGeneration must be an integer")
    fence = LeaseFence(str(raw["workerInstanceId"]), str(raw["leaseAcquisitionId"]), generation)
    if not fence.is_well_formed():
        raise ValueError("lease fence is malformed")
    return fence


class ExternalArtifactInspectionStore:
    """Append-only inspection request, lease, retry, and report projection."""

    def __init__(
        self,
        journal: DurableJournal,
        *,
        policy_registry: ExternalValidationPolicyRegistry,
        external_reconstruction: SealedExternalReconstructionSnapshotPort,
        storage: EvidenceStorage | None = None,
        display_store: Any | None = None,
        clock: Callable[[], datetime] | None = None,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        self._journal = journal
        self._policy_registry = policy_registry
        self._external_reconstruction = external_reconstruction
        self._storage = storage
        self._display_store = display_store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        self._records: dict[str, _InspectionRecord] = {}
        self._record_ids_by_subject_digest: dict[str, list[str]] = {}
        self._requests_by_natural_key: dict[tuple[object, ...], str] = {}
        self._lock = threading.RLock()
        if coordinator is not None and policy_registry.coordinator is not self._coordinator:
            raise ValueError("inspection policy registry must share currentness coordinator")
        if (
            coordinator is not None
            and display_store is not None
            and display_store.coordinator is not self._coordinator
        ):
            raise ValueError("inspection display store must share currentness coordinator")
        try:
            for raw in journal.replay():
                self._apply(raw)
        except BaseException as exc:
            journal.close()
            if isinstance(exc, ExternalArtifactInspectionRecoveryError):
                raise
            raise ExternalArtifactInspectionRecoveryError(
                f"external artifact inspection replay failed: {exc}"
            ) from exc
        if display_store is not None:
            display_store.bind_mutation_guard(self._commit_display_mutation)
            self._reconcile_display_after_replay()

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def issue_after_seal(
        self, subject: SealedExternalSubjectV1, now: datetime
    ) -> InspectionIssueResult:
        """Issue once for an actual sealed ingress revision and one active policy."""
        _wire_time(now)
        artifacts = self._sealed_artifacts_for(subject)
        if artifacts is None:
            return InspectionIssueResult(InspectionVerdict.SUBJECT_NOT_SEALED)
        selection = self._policy_registry.select_for_inspection(subject)
        if selection.status is not PolicySelectionStatus.ACTIVE or selection.policy is None:
            return InspectionIssueResult(InspectionVerdict.INSPECTION_PENDING_POLICY)
        policy = selection.policy
        assert policy.policy_digest is not None
        if policy.resource_envelope is None:
            return InspectionIssueResult(InspectionVerdict.INSPECTION_PENDING_POLICY)
        natural_key = self._natural_key(subject, policy.policy_digest)
        # Authority resolution above may call an injected port.  The final
        # durable projection shares the use-evaluator coordinator so a guarded
        # decision snapshot cannot race a newly issued inspection request.
        with self._coordinator.mutation(), self._lock:
            retained = self._policy_registry.resolve(policy.policy_digest)
            if retained.status is not PolicySelectionStatus.ACTIVE or retained.policy != policy:
                return InspectionIssueResult(InspectionVerdict.INSPECTION_PENDING_POLICY)
            existing_id = self._requests_by_natural_key.get(natural_key)
            if existing_id is not None:
                return InspectionIssueResult(
                    InspectionVerdict.IDEMPOTENT, self._records[existing_id].request
                )
            queue_depth = sum(
                1
                for record in self._records.values()
                if record.request.subject.organization_id == subject.organization_id
                and record.state == "QUEUED"
            )
            if queue_depth >= policy.resource_envelope.max_queue_depth:
                return InspectionIssueResult(InspectionVerdict.QUEUE_FULL)
            request = self._new_request(subject, policy, now)
            event: dict[str, object] = {
                "kind": "external-artifact-inspection-issued",
                "version": _EVENT_VERSION,
                "issuedAt": _wire_time(now),
                "request": external_artifact_inspection_request_wire_dict(request),
                "subject": subject.model_dump(by_alias=True, mode="json"),
                "policyDigest": policy.policy_digest,
                "naturalKey": list(natural_key),
                "artifacts": [self._artifact_wire(item) for item in artifacts],
            }
            event["eventDigest"] = _event_digest(event)
            try:
                self._append_apply(event)
            except JournalSealedError:
                return InspectionIssueResult(InspectionVerdict.STORAGE_UNAVAILABLE)
            return InspectionIssueResult(InspectionVerdict.ISSUED, request)

    def reconcile_sealed(self, now: datetime) -> int:
        """Find every sealed ingress revision; only current active policies issue work."""
        _wire_time(now)
        count = 0
        for revision in self._sealed_snapshot():
            candidate = self._subject_from_revision(revision)
            if (
                candidate is not None
                and self.issue_after_seal(candidate, now).verdict is InspectionVerdict.ISSUED
            ):
                count += 1
        self._reconcile_display_after_replay()
        return count

    def list_pending(
        self, limit: int, *, organization_id: str | None = None
    ) -> tuple[PendingExternalInspection, ...]:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        now = self._clock()
        _wire_time(now)
        with self._lock:
            records = tuple(self._records.values())
        candidates: list[PendingExternalInspection] = []
        for record in records:
            if not self._in_organization(record, organization_id):
                continue
            expired_or_queued = record.state == "QUEUED" or (
                record.state == "RUNNING"
                and record.lease is not None
                and now >= record.lease.expires_at
            )
            if expired_or_queued:
                candidates.append(
                    PendingExternalInspection(
                        record.request.request_id,
                        record.request.issued_at,
                        InspectionPhase.INSPECTION,
                    )
                )
            elif (
                record.state == "REPORTED"
                and record.lease is not None
                and now >= record.lease.expires_at
                and self._display_is_unfinished(record.request.request_id)
            ):
                candidates.append(
                    PendingExternalInspection(
                        record.request.request_id, record.request.issued_at, InspectionPhase.DISPLAY
                    )
                )
        return tuple(sorted(candidates, key=lambda item: (item.issued_at, item.request_id))[:limit])

    def public_snapshot(self, subject: SealedExternalSubjectV1) -> PublicInspectionSnapshot:
        """Return only retained inspection facts for one exact sealed subject.

        This read never issues a request.  A missing current inspection policy is
        deliberately distinguishable from a queued request so callers cannot
        infer that reading the revision scheduled worker work.
        """
        selection = self._policy_registry.select_for_inspection(subject)
        current_digest = selection.policy.policy_digest if selection.policy is not None else None
        with self._lock:
            candidates = tuple(
                record
                for record in self._records.values()
                if record.request.subject == subject
                and (
                    current_digest is None
                    or record.request.inspection_policy_digest == current_digest
                )
            )
            record = candidates[-1] if candidates else None
            if record is None:
                return PublicInspectionSnapshot(
                    (
                        InspectionVerdict.INSPECTION_PENDING_POLICY.value
                        if selection.status is PolicySelectionStatus.INSPECTION_PENDING_POLICY
                        else "INSPECTION_PENDING"
                    ),
                    None,
                    None,
                    None,
                )
            if record.report is not None:
                return PublicInspectionSnapshot(
                    "INSPECTION_REPORTED",
                    record.request,
                    self._phase_for_record(record),
                    record.report,
                )
            if record.terminal_reason is not None or record.state == "FAILED":
                return PublicInspectionSnapshot(
                    "INSPECTION_FAILED_INCOMPLETE",
                    record.request,
                    InspectionPhase.FAILED_INCOMPLETE,
                    None,
                )
            return PublicInspectionSnapshot(
                f"INSPECTION_{record.state}",
                record.request,
                InspectionPhase.INSPECTION,
                None,
            )

    def public_snapshot_bounded(
        self,
        subject: SealedExternalSubjectV1,
        *,
        max_records: int,
        max_retained_policies: int | None = None,
        max_policy_records: int | None = None,
    ) -> PublicInspectionSnapshot:
        """Return detached exact-subject evidence; never schedule or truncate inspection work.

        With no active selection this returns no retained report: a report bound
        to a non-active policy generation is historical evidence, never this
        subject's current inspection.

        This is a preflight snapshot, not byte authorization. Delivery must repeat
        ``report_for_locally_current_use`` under the shared currentness guard.
        """
        if max_policy_records is not None:
            if max_retained_policies is not None:
                raise ValueError("supply exactly one inspection policy budget")
            max_retained_policies = max_policy_records
        if (
            type(max_records) is not int
            or max_records < 1
            or type(max_retained_policies) is not int
            or max_retained_policies < 1
        ):
            raise ValueError("inspection snapshot limits must be positive integers")
        try:
            selection = self._policy_registry.select_for_inspection_bounded(
                subject, max_retained_policies=max_retained_policies
            )
        except ExternalValidationPolicySelectionBudgetExceeded as exc:
            raise ExternalArtifactInspectionSnapshotBudgetExceeded(
                "inspection policy source budget exceeded"
            ) from exc
        if selection.policy is None:
            # No active selection means no currently usable measurement to
            # surface. Delivery then classifies one candidate as
            # SOURCE_NOT_MEASURED (suppressible in AI discovery) instead of
            # failing a whole listing on a stale per-asset report, and the
            # catalog projects the current pending state; the retained report
            # remains retrievable through the dedicated historical lookups.
            return PublicInspectionSnapshot(
                (
                    InspectionVerdict.INSPECTION_PENDING_POLICY.value
                    if selection.status is PolicySelectionStatus.INSPECTION_PENDING_POLICY
                    else "INSPECTION_PENDING"
                ),
                None,
                None,
                None,
            )
        current_digest = selection.policy.policy_digest
        with self._lock:
            record_ids = self._record_ids_by_subject_digest.get(subject.canonical_digest(), ())
            if len(record_ids) > max_records:
                raise ExternalArtifactInspectionSnapshotBudgetExceeded(
                    "inspection record source budget exceeded"
                )
            candidates = tuple(
                self._records[request_id]
                for request_id in record_ids
                if self._records[request_id].request.inspection_policy_digest == current_digest
            )
            record = candidates[-1] if candidates else None
            if record is None:
                return PublicInspectionSnapshot(
                    (
                        InspectionVerdict.INSPECTION_PENDING_POLICY.value
                        if selection.status is PolicySelectionStatus.INSPECTION_PENDING_POLICY
                        else "INSPECTION_PENDING"
                    ),
                    None,
                    None,
                    None,
                )
            request = record.request.model_copy(deep=True)
            if record.report is not None:
                return PublicInspectionSnapshot(
                    "INSPECTION_REPORTED",
                    request,
                    self._phase_for_record(record),
                    record.report.model_copy(deep=True),
                )
            if record.terminal_reason is not None or record.state == "FAILED":
                return PublicInspectionSnapshot(
                    "INSPECTION_FAILED_INCOMPLETE", request, InspectionPhase.FAILED_INCOMPLETE, None
                )
            return PublicInspectionSnapshot(
                f"INSPECTION_{record.state}", request, InspectionPhase.INSPECTION, None
            )

    def retained_report_bounded(
        self,
        subject: SealedExternalSubjectV1,
        *,
        report_digest: str,
        max_records: int,
    ) -> ExternalArtifactInspectionReportV1 | None:
        """Exact bounded detached history, not authorization; no policy-port resolution."""
        if type(max_records) is not int or max_records < 1:
            raise ValueError("max_records must be a positive integer")
        with self._lock:
            ids = self._record_ids_by_subject_digest.get(subject.canonical_digest(), ())
            if len(ids) > max_records:
                raise ExternalArtifactInspectionSnapshotBudgetExceeded(
                    "inspection record source budget exceeded"
                )
            for request_id in ids:
                record = self._records[request_id]
                if record.report is not None and record.report.report_digest == report_digest:
                    return record.report.model_copy(deep=True)
        return None

    def locally_retained_state_digest_bounded(
        self, subject: SealedExternalSubjectV1, *, max_records: int
    ) -> str | None:
        """Bounded exact-subject retained inspection state fingerprint.

        Deterministic digest over the bounded retained request/report/state
        bindings for one exact sealed subject: a newly added report or request
        changes the fingerprint. Read-only under the owner lock; no worker,
        storage, remote authority, or policy-port resolution, and no payload
        or denied counts exposed. Returns None when this store or its policy
        registry is sealed (fail closed); budget overage raises.
        The fingerprint detects local mutation only: it is not authority, not
        an eligibility guarantee, and never a substitute for the genuine
        currentness recheck before any handoff.
        """
        if type(max_records) is not int or max_records < 1:
            raise ValueError("max_records must be a positive integer")
        with self._lock:
            if self.sealed_reason is not None or self._policy_registry.sealed_reason is not None:
                return None
            ids = self._record_ids_by_subject_digest.get(subject.canonical_digest(), ())
            if len(ids) > max_records:
                raise ExternalArtifactInspectionSnapshotBudgetExceeded(
                    "inspection record source budget exceeded"
                )
            bindings: list[list[str | None]] = []
            for request_id in sorted(ids):
                record = self._records[request_id]
                report = record.report
                bindings.append(
                    [
                        request_id,
                        record.request.inspection_policy_digest,
                        report.report_digest if report is not None else None,
                        report.inspection_policy_digest if report is not None else None,
                        record.state,
                        record.terminal_reason,
                    ]
                )
            return (
                "sha256:"
                + hashlib.sha256(
                    canonical_json_bytes(
                        {"subject": subject.canonical_digest(), "records": bindings}
                    )
                ).hexdigest()
            )

    def data_report_for_locally_current_use(
        self,
        subject: SealedExternalSubjectV1,
        expected_report: ExternalArtifactInspectionReportV1,
        *,
        now: datetime,
    ) -> ExternalArtifactInspectionReportV1 | None:
        """O(1) exact retained-report recheck; no worker/storage/remote authority resolution.

        The caller retains the shared coordinator through its check-and-commit.
        Legacy independently coordinated metadata assemblies cannot serve this gate.
        """
        _wire_time(now)
        if self._policy_registry.coordinator is not self._coordinator:
            return None
        with self._coordinator.guarded_read(), self._lock:
            if self.sealed_reason is not None or self._policy_registry.sealed_reason is not None:
                return None
            record = self._records.get(expected_report.request_id)
            if (
                record is None
                or record.request.subject != subject
                or record.report != expected_report
                or record.report is None
                or record.request.inspection_policy_digest
                != expected_report.inspection_policy_digest
            ):
                return None
            if not self._policy_registry.locally_current_use_permitted(
                record.request.inspection_policy_digest,
                use="INSPECTION",
                subjects=(subject,),
                at=now,
            ):
                return None
            return record.report.model_copy(deep=True)

    def historical_report(
        self,
        subject: SealedExternalSubjectV1,
        *,
        report_digest: str,
        policy_digest: str,
    ) -> ExternalArtifactInspectionReportV1 | None:
        """Resolve retained immutable report history without current selection."""
        with self._lock:
            for record in self._records.values():
                report = record.report
                if (
                    report is not None
                    and record.request.subject == subject
                    and report.report_digest == report_digest
                    and report.inspection_policy_digest == policy_digest
                ):
                    return report
        return None

    def report_for_locally_current_use(
        self,
        subject: SealedExternalSubjectV1,
        expected_report: ExternalArtifactInspectionReportV1,
        *,
        now: datetime,
    ) -> ExternalArtifactInspectionReportV1 | None:
        """Final local inspection recheck for a caller holding the coordinator.

        ``public_snapshot`` deliberately selects live policy and is therefore
        only safe before a final currentness guard.  This companion compares a
        retained report to the preflight snapshot and checks local policy state
        without another policy selection or any worker/storage operation.
        """
        _wire_time(now)
        with self._coordinator.guarded_read(), self._lock:
            matching = next(
                (
                    record
                    for record in self._records.values()
                    if record.request.subject == subject and record.report == expected_report
                ),
                None,
            )
            if matching is None or not self._policy_is_locally_current(matching, now):
                return None
            return matching.report

    def historical_display_receipt(
        self,
        subject: SealedExternalSubjectV1,
        *,
        report_digest: str,
        receipt_digest: str,
        policy_digest: str,
    ) -> SanitizedDisplayReceiptV1 | None:
        """Resolve a receipt chain from retained report state, never current policy."""
        if self._display_store is None:
            return None
        report = self.historical_report(
            subject, report_digest=report_digest, policy_digest=policy_digest
        )
        if report is None:
            return None
        snapshot = self._display_store.public_snapshot(
            report.request_id,
            subject_digest=subject.canonical_digest(),
            report_digest=report_digest,
            policy_digest=policy_digest,
        )
        receipt = snapshot.receipt if snapshot is not None else None
        return receipt if receipt is not None and receipt.receipt_digest == receipt_digest else None

    @staticmethod
    def _in_organization(record: _InspectionRecord, organization_id: str | None) -> bool:
        return organization_id is None or record.request.subject.organization_id == organization_id

    def belongs_to_organization(self, request_id: str, organization_id: str) -> bool:
        """Non-disclosing ownership predicate for a worker's opaque request id."""
        with self._lock:
            record = self._records.get(request_id)
            return record is not None and self._in_organization(record, organization_id)

    def public_display_state(self, subject: SealedExternalSubjectV1) -> tuple[str, Any | None]:
        """Return receipt state for the current exact report/policy chain only."""
        if self._display_store is None:
            return "PENDING_INSPECTION", None
        with self._lock:
            records = tuple(
                record
                for record in self._records.values()
                if record.request.subject == subject and record.report is not None
            )
            record = records[-1] if records else None
            if record is None:
                return "PENDING_INSPECTION", None
        if not self._policy_is_current(record):
            return "PENDING_POLICY", None
        with self._lock:
            record = self._records.get(record.request.request_id)
            if record is None or record.report is None:
                return "PENDING_INSPECTION", None
            assert record.report is not None
            request_id = record.request.request_id
            subject_digest = record.report.subject_digest
            report_digest = record.report.report_digest
            policy_digest = record.report.inspection_policy_digest
        snapshot = self._display_store.public_snapshot(
            request_id,
            subject_digest=subject_digest,
            report_digest=report_digest,
            policy_digest=policy_digest,
        )
        if snapshot is None:
            return "PENDING_INSPECTION", None
        return snapshot.state.value, snapshot.receipt

    def public_display_download_binding(
        self, subject: SealedExternalSubjectV1, sanitized_display_ref: str
    ) -> Any | None:
        """Resolve a current receipt binding; presigning happens separately without locks."""
        if self._display_store is None:
            return None
        with self._lock:
            records = tuple(
                record
                for record in self._records.values()
                if record.request.subject == subject and record.report is not None
            )
            record = records[-1] if records else None
            if record is None:
                return None
        if not self._policy_is_current(record):
            return None
        with self._lock:
            record = self._records.get(record.request.request_id)
            if record is None or record.report is None:
                return None
            assert record.report is not None
            request_id = record.request.request_id
            subject_digest = record.report.subject_digest
            report_digest = record.report.report_digest
            policy_digest = record.report.inspection_policy_digest
        return self._display_store.public_download_binding(
            request_id,
            subject_digest=subject_digest,
            report_digest=report_digest,
            policy_digest=policy_digest,
            sanitized_display_ref=sanitized_display_ref,
        )

    def presign_public_display_download(self, binding: Any) -> str | None:
        if self._display_store is None:
            return None
        return self._display_store.presign_public_download(binding)

    def claim(
        self,
        request_id: str,
        fence: LeaseFence,
        now: datetime,
        *,
        organization_id: str | None = None,
    ) -> InspectionLeaseResult:
        _wire_time(now)
        if not fence.has_valid_ids() or fence.lease_generation < 0:
            return InspectionLeaseResult(InspectionVerdict.LEASE_FENCE_REJECTED)
        with self._lock:
            preflight = self._records.get(request_id)
            if preflight is None or not self._in_organization(preflight, organization_id):
                return InspectionLeaseResult(InspectionVerdict.NOT_FOUND)
        preflight_display = self._display_is_unfinished(request_id)
        if not self._policy_is_current(preflight) or (
            preflight.report is not None
            and preflight_display
            and not self._display_policy_is_current(preflight)
        ):
            return InspectionLeaseResult(InspectionVerdict.POLICY_UNAVAILABLE, preflight.request)
        with self._coordinator.mutation(), self._lock:
            record = self._records.get(request_id)
            if record is None or not self._in_organization(record, organization_id):
                return InspectionLeaseResult(InspectionVerdict.NOT_FOUND)
            display_unfinished = self._display_is_unfinished(request_id)
            if not self._policy_is_locally_current(record, now):
                return InspectionLeaseResult(InspectionVerdict.POLICY_UNAVAILABLE, record.request)
            if (
                record.report is not None
                and display_unfinished
                and not self._display_policy_is_locally_current(record, now)
            ):
                return InspectionLeaseResult(InspectionVerdict.POLICY_UNAVAILABLE, record.request)
            if (
                record.terminal_reason is not None
                or record.state == "FAILED"
                or (record.state == "REPORTED" and not display_unfinished)
            ):
                return InspectionLeaseResult(InspectionVerdict.NOT_FOUND, record.request)
            phase = (
                InspectionPhase.DISPLAY
                if record.state == "REPORTED"
                else InspectionPhase.INSPECTION
            )
            policy = self._policy_for(record)
            if policy is None or policy.resource_envelope is None:
                return InspectionLeaseResult(InspectionVerdict.POLICY_UNAVAILABLE, record.request)
            if now >= self._deadline(record, policy):
                self._record_exhaustion(record, "DEADLINE_EXCEEDED", now)
                return InspectionLeaseResult(InspectionVerdict.DEADLINE_EXCEEDED, record.request)
            current = record.lease
            if current is not None and now < current.expires_at:
                if current.fence == fence or (
                    fence.has_valid_ids()
                    and fence.lease_generation == 0
                    and current.fence.worker_instance_id == fence.worker_instance_id
                    and current.fence.lease_acquisition_id == fence.lease_acquisition_id
                ):
                    return InspectionLeaseResult(
                        InspectionVerdict.LEASED,
                        record.request,
                        current.expires_at,
                        phase,
                        current.fence,
                    )
                return InspectionLeaseResult(InspectionVerdict.LEASE_FENCE_REJECTED, record.request)
            if not fence.has_valid_ids() or fence.lease_generation != 0:
                return InspectionLeaseResult(InspectionVerdict.LEASE_FENCE_REJECTED, record.request)
            if fence.lease_acquisition_id in record.used_acquisition_ids:
                return InspectionLeaseResult(InspectionVerdict.LEASE_FENCE_REJECTED, record.request)
            accepted_fence = LeaseFence(
                fence.worker_instance_id,
                fence.lease_acquisition_id,
                record.last_generation + 1,
            )
            if record.attempt_count >= 1 + policy.resource_envelope.max_retry_attempts:
                self._record_exhaustion(record, "RETRY_EXHAUSTED", now)
                return InspectionLeaseResult(InspectionVerdict.RETRY_EXHAUSTED, record.request)
            active_for_organization = sum(
                1
                for candidate in self._records.values()
                if candidate is not record
                and candidate.request.subject.organization_id
                == record.request.subject.organization_id
                and candidate.lease is not None
                and now < candidate.lease.expires_at
            )
            if active_for_organization >= policy.resource_envelope.max_tenant_concurrency:
                return InspectionLeaseResult(InspectionVerdict.CONCURRENCY_LIMIT, record.request)
            expires_at = min(
                now + timedelta(seconds=policy.resource_envelope.lease_duration_seconds),
                self._deadline(record, policy),
            )
            event: dict[str, object] = {
                "kind": "external-artifact-inspection-claimed",
                "version": _EVENT_VERSION,
                "requestId": request_id,
                **_fence_wire(accepted_fence),
                "leaseExpiresAt": _wire_time(expires_at),
            }
            event["eventDigest"] = _event_digest(event)
            try:
                self._append_apply(event)
            except JournalSealedError:
                return InspectionLeaseResult(InspectionVerdict.STORAGE_UNAVAILABLE, record.request)
            return InspectionLeaseResult(
                InspectionVerdict.LEASED,
                record.request,
                expires_at,
                phase,
                accepted_fence,
            )

    def input_for(
        self, request_id: str, fence: LeaseFence, *, organization_id: str | None = None
    ) -> ExternalInspectionInputResponse:
        now = self._clock()
        _wire_time(now)
        with self._lock:
            preflight = self._records.get(request_id)
            if preflight is None or not self._in_organization(preflight, organization_id):
                return ExternalInspectionInputResponse(InspectionVerdict.NOT_FOUND)
        if not self._policy_is_current(preflight) or (
            preflight.report is not None and not self._display_policy_is_current(preflight)
        ):
            return ExternalInspectionInputResponse(
                InspectionVerdict.POLICY_UNAVAILABLE, request=preflight.request
            )
        with self._coordinator.guarded_read(), self._lock:
            record = self._records.get(request_id)
            if record is None or not self._in_organization(record, organization_id):
                return ExternalInspectionInputResponse(InspectionVerdict.NOT_FOUND)
            if not self._policy_is_locally_current(record, now):
                return ExternalInspectionInputResponse(
                    InspectionVerdict.POLICY_UNAVAILABLE, request=record.request
                )
            if record.report is not None and not self._display_policy_is_locally_current(
                record, now
            ):
                return ExternalInspectionInputResponse(
                    InspectionVerdict.POLICY_UNAVAILABLE, request=record.request
                )
            if record.terminal_reason == "DEADLINE_EXCEEDED":
                return ExternalInspectionInputResponse(
                    InspectionVerdict.DEADLINE_EXCEEDED, request=record.request
                )
            if not self.has_current_fence(request_id, fence, now):
                return ExternalInspectionInputResponse(
                    InspectionVerdict.LEASE_FENCE_REJECTED, request=record.request
                )
            policy = self._policy_for(record)
            if policy is None:
                return ExternalInspectionInputResponse(
                    InspectionVerdict.POLICY_UNAVAILABLE, request=record.request
                )
            if now >= self._deadline(record, policy):
                return ExternalInspectionInputResponse(
                    InspectionVerdict.DEADLINE_EXCEEDED, request=record.request
                )
            if record.report is not None and not self._display_is_unfinished(request_id):
                return ExternalInspectionInputResponse(
                    InspectionVerdict.NOT_FOUND, request=record.request
                )
            artifacts = record.artifacts
            request = record.request
            accepted_report = record.report
        projected: list[ExternalArtifactInputV1] = []
        for artifact in artifacts:
            url: str | None = None
            if self._storage is not None:
                try:
                    url = self._storage.presigned_get(artifact.object_key, ttl=DEFAULT_VIEW_TTL)
                except EvidenceStorageError:
                    return ExternalInspectionInputResponse(
                        InspectionVerdict.STORAGE_UNAVAILABLE, request=record.request
                    )
            projected.append(
                ExternalArtifactInputV1(
                    artifact.entry_id,
                    artifact.kind,
                    artifact.observed_sha256,
                    artifact.observed_size_bytes,
                    artifact.content_type,
                    url,
                    {},
                )
            )
        with self._coordinator.guarded_read(), self._lock:
            commit_now = self._clock()
            _wire_time(commit_now)
            record = self._records.get(request_id)
            if record is None or not self._in_organization(record, organization_id):
                return ExternalInspectionInputResponse(InspectionVerdict.NOT_FOUND)
            if record.request != request or record.report != accepted_report:
                return ExternalInspectionInputResponse(
                    InspectionVerdict.LEASE_FENCE_REJECTED, request=record.request
                )
            if not self._policy_is_locally_current(record, commit_now):
                return ExternalInspectionInputResponse(
                    InspectionVerdict.POLICY_UNAVAILABLE, request=record.request
                )
            if record.report is not None and not self._display_policy_is_locally_current(
                record, commit_now
            ):
                return ExternalInspectionInputResponse(
                    InspectionVerdict.POLICY_UNAVAILABLE, request=record.request
                )
            if record.terminal_reason == "DEADLINE_EXCEEDED":
                return ExternalInspectionInputResponse(
                    InspectionVerdict.DEADLINE_EXCEEDED, request=record.request
                )
            if not self.has_current_fence(request_id, fence, commit_now):
                return ExternalInspectionInputResponse(
                    InspectionVerdict.LEASE_FENCE_REJECTED, request=record.request
                )
            current_policy = self._policy_for(record)
            if current_policy is None:
                return ExternalInspectionInputResponse(
                    InspectionVerdict.POLICY_UNAVAILABLE, request=record.request
                )
            if commit_now >= self._deadline(record, current_policy):
                return ExternalInspectionInputResponse(
                    InspectionVerdict.DEADLINE_EXCEEDED, request=record.request
                )
            if accepted_report is not None and not self._display_is_unfinished(request_id):
                return ExternalInspectionInputResponse(
                    InspectionVerdict.NOT_FOUND, request=record.request
                )
        return ExternalInspectionInputResponse(
            InspectionVerdict.LEASED,
            request,
            current_policy,
            tuple(projected),
            InspectionPhase.DISPLAY if accepted_report is not None else InspectionPhase.INSPECTION,
            "SANITIZE_DISPLAY" if accepted_report is not None else "INSPECT",
            accepted_report,
        )

    def heartbeat(
        self,
        request_id: str,
        fence: LeaseFence,
        now: datetime,
        *,
        organization_id: str | None = None,
    ) -> InspectionLeaseResult:
        _wire_time(now)
        with self._lock:
            preflight = self._records.get(request_id)
            if preflight is None or not self._in_organization(preflight, organization_id):
                return InspectionLeaseResult(InspectionVerdict.NOT_FOUND)
        if not self._policy_is_current(preflight) or (
            preflight.report is not None and not self._display_policy_is_current(preflight)
        ):
            return InspectionLeaseResult(InspectionVerdict.POLICY_UNAVAILABLE, preflight.request)
        with self._coordinator.mutation(), self._lock:
            record = self._records.get(request_id)
            if record is None or not self._in_organization(record, organization_id):
                return InspectionLeaseResult(InspectionVerdict.NOT_FOUND)
            if not self._policy_is_locally_current(record, now):
                return InspectionLeaseResult(InspectionVerdict.POLICY_UNAVAILABLE, record.request)
            if record.report is not None and not self._display_policy_is_locally_current(
                record, now
            ):
                return InspectionLeaseResult(InspectionVerdict.POLICY_UNAVAILABLE, record.request)
            if not self.has_current_fence(request_id, fence, now):
                return InspectionLeaseResult(InspectionVerdict.LEASE_FENCE_REJECTED, record.request)
            policy = self._policy_for(record)
            if policy is None or policy.resource_envelope is None:
                return InspectionLeaseResult(InspectionVerdict.POLICY_UNAVAILABLE, record.request)
            if now >= self._deadline(record, policy):
                return InspectionLeaseResult(InspectionVerdict.DEADLINE_EXCEEDED, record.request)
            expires_at = min(
                now + timedelta(seconds=policy.resource_envelope.lease_duration_seconds),
                self._deadline(record, policy),
            )
            event: dict[str, object] = {
                "kind": "external-artifact-inspection-heartbeat",
                "version": _EVENT_VERSION,
                "requestId": request_id,
                **_fence_wire(fence),
                "leaseExpiresAt": _wire_time(expires_at),
            }
            event["eventDigest"] = _event_digest(event)
            self._append_apply(event)
            return InspectionLeaseResult(
                InspectionVerdict.LEASED,
                record.request,
                expires_at,
                self._phase_for_record(record),
                fence,
            )

    def record_report(
        self,
        request_id: str,
        fence: LeaseFence,
        report: ExternalArtifactInspectionReportV1,
        now: datetime,
        *,
        organization_id: str | None = None,
    ) -> InspectionReportResult:
        _wire_time(now)
        sealed = report.sealed()
        with self._lock:
            preflight = self._records.get(request_id)
            if preflight is None or not self._in_organization(preflight, organization_id):
                return InspectionReportResult(InspectionVerdict.NOT_FOUND)
        if not self._policy_is_current(preflight) or (
            preflight.report is not None and not self._display_policy_is_current(preflight)
        ):
            return InspectionReportResult(InspectionVerdict.POLICY_UNAVAILABLE)
        with self._coordinator.mutation(), self._lock:
            record = self._records.get(request_id)
            if record is None or not self._in_organization(record, organization_id):
                return InspectionReportResult(InspectionVerdict.NOT_FOUND)
            if record.report is not None:
                if not self._policy_is_locally_current(record, now):
                    return InspectionReportResult(InspectionVerdict.POLICY_UNAVAILABLE)
                if not self._display_policy_is_locally_current(record, now):
                    return InspectionReportResult(InspectionVerdict.POLICY_UNAVAILABLE)
                if not self.has_current_fence(request_id, fence, now):
                    return InspectionReportResult(InspectionVerdict.LEASE_FENCE_REJECTED)
                return InspectionReportResult(
                    InspectionVerdict.REPORTED
                    if record.report.report_digest == sealed.report_digest
                    else InspectionVerdict.PAYLOAD_DIVERGENCE,
                    record.report,
                    self._phase_for_record(record),
                )
            if not self._policy_is_locally_current(record, now):
                return InspectionReportResult(InspectionVerdict.POLICY_UNAVAILABLE)
            if not self.has_current_fence(request_id, fence, now):
                return InspectionReportResult(InspectionVerdict.LEASE_FENCE_REJECTED)
            policy = self._policy_for(record)
            if policy is None or now >= self._deadline(record, policy):
                return InspectionReportResult(InspectionVerdict.DEADLINE_EXCEEDED)
            if not self._report_matches(record, fence, sealed):
                return InspectionReportResult(InspectionVerdict.REPORT_BINDING_REJECTED)
            display_required = self._requires_display(record, sealed, now)
            event: dict[str, object] = {
                "kind": "external-artifact-inspection-reported",
                "version": _EVENT_VERSION,
                "requestId": request_id,
                "subjectDigest": sealed.subject_digest,
                "policyDigest": sealed.inspection_policy_digest,
                "reportDigest": sealed.report_digest,
                "measurementPayloadDigest": sealed.measurement_payload_digest,
                "displayRequired": display_required,
                **_fence_wire(fence),
                "recordedAt": _wire_time(now),
                "report": external_artifact_inspection_report_wire_dict(sealed),
            }
            event["eventDigest"] = _event_digest(event)
            try:
                self._append_apply(event)
            except JournalSealedError:
                return InspectionReportResult(InspectionVerdict.STORAGE_UNAVAILABLE)
        self._queue_display_if_eligible(sealed, now)
        with self._lock:
            current = self._records[request_id]
            phase = self._phase_for_record(current)
        return InspectionReportResult(InspectionVerdict.REPORTED, sealed, phase)

    def record_incomplete_failure(
        self,
        request_id: str,
        fence: LeaseFence,
        failure: ExternalInspectionFailureV1,
        now: datetime,
        *,
        organization_id: str | None = None,
    ) -> InspectionReportResult:
        _wire_time(now)
        with self._lock:
            preflight = self._records.get(request_id)
            if preflight is None or not self._in_organization(preflight, organization_id):
                return InspectionReportResult(InspectionVerdict.NOT_FOUND)
        if not self._policy_is_current(preflight):
            return InspectionReportResult(InspectionVerdict.POLICY_UNAVAILABLE)
        with self._coordinator.mutation(), self._lock:
            record = self._records.get(request_id)
            if record is None or not self._in_organization(record, organization_id):
                return InspectionReportResult(InspectionVerdict.NOT_FOUND)
            if record.report is not None or record.state != "RUNNING":
                return InspectionReportResult(InspectionVerdict.REPORT_BINDING_REJECTED)
            if not self._policy_is_locally_current(record, now):
                return InspectionReportResult(InspectionVerdict.POLICY_UNAVAILABLE)
            if not self.has_current_fence(request_id, fence, now):
                return InspectionReportResult(InspectionVerdict.LEASE_FENCE_REJECTED)
            policy = self._policy_for(record)
            if policy is None or policy.resource_envelope is None:
                return InspectionReportResult(InspectionVerdict.POLICY_UNAVAILABLE)
            failures = record.failures + 1
            rule_id = failure.retry_rule_id
            recognized_rule = (
                rule_id if rule_id is not None and rule_id in policy.inspection_rule_ids else None
            )
            exhausted = (
                recognized_rule is None
                or record.attempt_count >= 1 + policy.resource_envelope.max_retry_attempts
                or now >= self._deadline(record, policy)
            )
            event: dict[str, object] = {
                "kind": "external-artifact-inspection-incomplete",
                "version": _EVENT_VERSION,
                "requestId": request_id,
                "failure": {"reason": failure.reason},
                "failureDigest": failure.canonical_digest(),
                "failureCount": failures,
                "attemptCount": record.attempt_count,
                "policyDigest": record.request.inspection_policy_digest,
                "retryRuleId": recognized_rule,
                "nextEligibleAt": _wire_time(now),
                "retryExhausted": exhausted,
                **_fence_wire(fence),
                "recordedAt": _wire_time(now),
            }
            event["eventDigest"] = _event_digest(event)
            self._append_apply(event)
            return InspectionReportResult(
                InspectionVerdict.INSPECTION_FAILED_INCOMPLETE
                if exhausted
                else InspectionVerdict.QUEUED,
                phase=InspectionPhase.FAILED_INCOMPLETE
                if exhausted
                else InspectionPhase.INSPECTION,
            )

    def has_current_fence(self, request_id: str, fence: LeaseFence, now: datetime) -> bool:
        if not fence.is_well_formed():
            return False
        with self._lock:
            record = self._records.get(request_id)
            policy = self._policy_for(record) if record is not None else None
            return (
                record is not None
                and record.terminal_reason is None
                and record.lease is not None
                and record.lease.fence == fence
                and now < record.lease.expires_at
                and policy is not None
                and now < self._deadline(record, policy)
            )

    def _commit_display_mutation(
        self,
        request_id: str,
        fence: LeaseFence,
        report_digest: str,
        commit: Callable[[datetime, int, ExternalValidationPolicyV1], Any],
    ) -> Any | None:
        """Serialize final display authorization with the inspection lease.

        The nested callback is the sole intentional cross-store lock order:
        inspection then display.  It must only append/re-fetch display state;
        storage observation and signed capability creation stay outside both
        locks, so a takeover or revocation during I/O is checked at commit.
        """
        # ``select_for_use`` may call the injected policy authority.  Resolve
        # it before taking the shared coordinator, then compare only retained
        # policy state in the nested inspection/display commit below.
        with self._lock:
            record = self._records.get(request_id)
            if (
                record is None
                or record.state != "REPORTED"
                or record.report is None
                or record.report.report_digest != report_digest
                or record.lease is None
                or record.lease.fence != fence
            ):
                return None
            subject = record.request.subject
            policy_digest = record.request.inspection_policy_digest
        selected = self._policy_registry.select_for_use("DISPLAY", (subject,))
        if (
            selected.status is not PolicySelectionStatus.ACTIVE
            or selected.policy is None
            or selected.policy.policy_digest != policy_digest
        ):
            return None
        with self._coordinator.mutation(), self._lock:
            commit_now = self._clock()
            _wire_time(commit_now)
            record = self._records.get(request_id)
            if (
                record is None
                or record.state != "REPORTED"
                or record.report is None
                or record.report.report_digest != report_digest
                or record.lease is None
                or record.lease.fence != fence
            ):
                return None
            policy = self._policy_for(record)
            retained = self._policy_registry.resolve(record.request.inspection_policy_digest)
            if (
                policy is None
                or commit_now >= record.lease.expires_at
                or commit_now >= self._deadline(record, policy)
                or retained.status is not PolicySelectionStatus.ACTIVE
                or retained.policy != policy
            ):
                return None
            return commit(commit_now, record.attempt_count, policy)

    @staticmethod
    def _deadline(record: _InspectionRecord, policy: ExternalValidationPolicyV1) -> datetime:
        assert policy.resource_envelope is not None
        return record.request.issued_at + timedelta(
            seconds=policy.resource_envelope.max_deadline_seconds
        )

    def _new_request(
        self, subject: SealedExternalSubjectV1, policy: ExternalValidationPolicyV1, now: datetime
    ) -> ExternalArtifactInspectionRequestV1:
        assert policy.policy_digest is not None
        identity = _digest(
            {
                "domain": "ksi.external-artifact-inspection-request.v1",
                "subject": subject.canonical_digest(),
                "policyDigest": policy.policy_digest,
            }
        )
        return ExternalArtifactInspectionRequestV1(
            request_id="eai-v1-" + identity.removeprefix("sha256:"),
            subject=subject,
            inspection_policy_id=policy.policy_id,
            inspection_policy_version=policy.version,
            inspection_policy_digest=policy.policy_digest,
            issued_at=now,
            idempotency_key=identity,
        )

    def _sealed_snapshot(self) -> tuple[ExternalReconstructionRevision, ...]:
        return self._external_reconstruction.sealed_revisions_snapshot()

    def _sealed_artifacts_for(
        self, subject: SealedExternalSubjectV1
    ) -> tuple[_ArtifactBinding, ...] | None:
        for revision in self._sealed_snapshot():
            candidate = self._subject_from_revision(revision)
            if candidate == subject:
                artifacts = self._artifacts_from_revision(revision)
                return artifacts if artifacts else None
        return None

    @staticmethod
    def _subject_from_revision(
        revision: ExternalReconstructionRevision,
    ) -> SealedExternalSubjectV1 | None:
        submission, manifest = revision.submission, revision.manifest
        if (
            submission.submission_digest is None
            or manifest is None
            or manifest.manifest_digest is None
        ):
            return None
        return SealedExternalSubjectV1(
            organization_id=submission.organization_id,
            site_id=submission.site_id,
            work_order_id=revision.work_order_id,
            submission_id=submission.submission_id,
            revision=submission.revision,
            submission_digest=submission.submission_digest,
            manifest_digest=manifest.manifest_digest,
        )

    @staticmethod
    def _artifacts_from_revision(
        revision: ExternalReconstructionRevision,
    ) -> tuple[_ArtifactBinding, ...]:
        if revision.manifest is None:
            return ()
        artifacts: list[_ArtifactBinding] = []
        for item in revision.manifest.entries:
            observed = "sha256:" + item.observed_sha256
            if _DIGEST_RE.fullmatch(observed) is None:
                return ()
            artifacts.append(
                _ArtifactBinding(
                    item.artifact_id,
                    item.kind,
                    observed,
                    item.observed_size_bytes,
                    item.observed_content_type,
                    item.object_key,
                )
            )
        return tuple(sorted(artifacts, key=lambda item: item.entry_id))

    @staticmethod
    def _artifact_wire(artifact: _ArtifactBinding) -> dict[str, object]:
        return {
            "entryId": artifact.entry_id,
            "kind": artifact.kind.value,
            "observedSha256": artifact.observed_sha256,
            "observedSizeBytes": artifact.observed_size_bytes,
            "contentType": artifact.content_type,
            "objectKey": artifact.object_key,
        }

    @staticmethod
    def _artifact_from_wire(raw: object) -> _ArtifactBinding:
        if not isinstance(raw, Mapping) or set(raw) != {
            "entryId",
            "kind",
            "observedSha256",
            "observedSizeBytes",
            "contentType",
            "objectKey",
        }:
            raise ValueError("inspection artifact event fields are not exact")
        if (
            type(raw["observedSizeBytes"]) is not int
            or raw["observedSizeBytes"] < 1
            or not isinstance(raw["objectKey"], str)
        ):
            raise ValueError("inspection artifact event values are malformed")
        return _ArtifactBinding(
            str(raw["entryId"]),
            ProcessingArtifactKind(str(raw["kind"]).lower()),
            str(raw["observedSha256"]),
            raw["observedSizeBytes"],
            str(raw["contentType"]),
            str(raw["objectKey"]),
        )

    @staticmethod
    def _natural_key(subject: SealedExternalSubjectV1, policy_digest: str) -> tuple[object, ...]:
        """Bind idempotence to the full sealed revision, not mutable labels alone."""
        return (
            subject.organization_id,
            subject.site_id,
            subject.work_order_id,
            subject.submission_id,
            subject.revision,
            subject.submission_digest,
            subject.manifest_digest,
            policy_digest,
        )

    def _policy_for(self, record: _InspectionRecord) -> ExternalValidationPolicyV1 | None:
        resolved = self._policy_registry.resolve(record.request.inspection_policy_digest)
        return resolved.policy if resolved.policy is not None else None

    def _policy_is_current(self, record: _InspectionRecord) -> bool:
        selected = self._policy_registry.select_for_inspection(record.request.subject)
        return (
            selected.status is PolicySelectionStatus.ACTIVE
            and selected.policy is not None
            and selected.policy.policy_digest == record.request.inspection_policy_digest
        )

    def _policy_is_locally_current(self, record: _InspectionRecord, now: datetime) -> bool:
        """Check retained lifecycle state without another authority-port read."""
        resolved = self._policy_registry.resolve(record.request.inspection_policy_digest)
        return (
            resolved.status is PolicySelectionStatus.ACTIVE
            and resolved.policy is not None
            and resolved.policy.policy_digest == record.request.inspection_policy_digest
            and self._policy_registry.locally_current_use_permitted(
                record.request.inspection_policy_digest,
                use="INSPECTION",
                subjects=(record.request.subject,),
                at=now,
            )
        )

    def _display_policy_is_current(self, record: _InspectionRecord) -> bool:
        selected = self._policy_registry.select_for_use("DISPLAY", (record.request.subject,))
        return (
            selected.status is PolicySelectionStatus.ACTIVE
            and selected.policy is not None
            and selected.policy.policy_digest == record.request.inspection_policy_digest
        )

    def _display_policy_is_locally_current(self, record: _InspectionRecord, now: datetime) -> bool:
        return self._policy_is_locally_current(
            record, now
        ) and self._policy_registry.locally_current_use_permitted(
            record.request.inspection_policy_digest,
            use="DISPLAY",
            subjects=(record.request.subject,),
            at=now,
        )

    def _report_matches(
        self,
        record: _InspectionRecord,
        fence: LeaseFence,
        report: ExternalArtifactInspectionReportV1,
    ) -> bool:
        policy = self._policy_for(record)
        if (
            policy is None
            or report.request_id != record.request.request_id
            or report.subject != record.request.subject
            or report.subject_digest != record.request.subject.canonical_digest()
            or report.inspection_policy_digest != record.request.inspection_policy_digest
            or report.inspector_build_digest != policy.parser_build_digest
        ):
            return False
        if (report.worker_instance_id, report.lease_acquisition_id, report.lease_generation) != (
            fence.worker_instance_id,
            fence.lease_acquisition_id,
            fence.lease_generation,
        ):
            return False
        bindings = {(item.entry_id, item.observed_sha256) for item in record.artifacts}
        report_bindings = {
            (item.artifact_id, item.observed_sha256)
            for item in report.measurement_payload.artifact_bindings
        }
        return bindings == report_bindings and self._measured_rasters_match_declarations(
            record, report
        )

    @staticmethod
    def _measured_rasters_match_declarations(
        record: _InspectionRecord, report: ExternalArtifactInspectionReportV1
    ) -> bool:
        """Keep only measured layouts compatible with their sealed declared raster kind.

        An inspector may record the existing typed ``UNSUPPORTED_RASTER`` rejection for
        a mismatched source. Core never upgrades or rewrites that worker outcome; this
        guard only prevents retaining a conflicting ``MEASURED`` fact.
        """
        outcomes = {item.artifact_id: item for item in report.measurement_payload.outcomes}
        for artifact in record.artifacts:
            outcome = outcomes.get(artifact.entry_id)
            if outcome is None or outcome.outcome is not ArtifactOutcome.MEASURED:
                continue
            measurements = outcome.measurements
            if measurements is None:
                return False
            dtype = measurements.dtype.casefold()
            if artifact.kind is ProcessingArtifactKind.ORTHO and (
                measurements.band_count not in {3, 4} or dtype != "uint8"
            ):
                return False
            if artifact.kind is ProcessingArtifactKind.DSM and (
                measurements.band_count != 1 or dtype not in {"float32", "float64"}
            ):
                return False
        return True

    def _requires_display(
        self,
        record: _InspectionRecord,
        report: ExternalArtifactInspectionReportV1,
        recorded_at: datetime,
    ) -> bool:
        measured_ortho = any(
            item.kind is ProcessingArtifactKind.ORTHO and outcome.outcome.value == "MEASURED"
            for item in record.artifacts
            for outcome in report.measurement_payload.outcomes
            if outcome.artifact_id == item.entry_id
        )
        return measured_ortho and self._policy_registry.historical_use_permitted(
            record.request.inspection_policy_digest,
            use="DISPLAY",
            subjects=(report.subject,),
            at=recorded_at,
        )

    def _queue_display_if_eligible(
        self, report: ExternalArtifactInspectionReportV1, now: datetime
    ) -> None:
        if self._display_store is None:
            return
        with self._lock:
            record = self._records.get(report.request_id)
            if record is None or not record.display_required:
                return
        policy = self._policy_for(record)
        if policy is not None and policy.resource_envelope is not None:
            try:
                self._display_store.ensure_after_report(
                    report,
                    display_permitted=True,
                    measured_ortho=True,
                    max_retry_attempts=policy.resource_envelope.max_retry_attempts,
                    max_output_bytes=policy.resource_envelope.max_output_bytes,
                    now=now,
                )
            except Exception:
                # The immutable report remains accepted; later reconciliation repairs display work.
                return

    def _display_is_unfinished(self, request_id: str) -> bool:
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.terminal_reason is not None or not record.display_required:
                return False
            if self._display_store is None:
                return True
        return str(self._display_store.phase_for(request_id)) in {
            "NOT_REQUIRED",
            "QUEUED",
            "RUNNING",
        }

    def _phase_for_record(self, record: _InspectionRecord) -> InspectionPhase:
        if record.report is None:
            return InspectionPhase.INSPECTION
        if record.report is not None and self._display_is_unfinished(record.request.request_id):
            return InspectionPhase.DISPLAY
        return InspectionPhase.COMPLETE

    def _reconcile_display_after_replay(self) -> None:
        if self._display_store is None:
            return
        with self._lock:
            reports = tuple(
                record.report for record in self._records.values() if record.report is not None
            )
        for report in reports:
            assert report is not None
            self._queue_display_if_eligible(report, self._clock())

    def _record_exhaustion(self, record: _InspectionRecord, reason: str, now: datetime) -> None:
        """Make pre-claim deadline/budget exhaustion durable and non-pending."""
        if record.terminal_reason is not None:
            return
        event: dict[str, object] = {
            "kind": "external-artifact-inspection-exhausted",
            "version": _EVENT_VERSION,
            "requestId": record.request.request_id,
            "reason": reason,
            "policyDigest": record.request.inspection_policy_digest,
            "attemptCount": record.attempt_count,
            "exhaustedAt": _wire_time(now),
        }
        event["eventDigest"] = _event_digest(event)
        try:
            self._append_apply(event)
        except JournalSealedError:
            return

    def _append_apply(self, event: dict[str, object]) -> None:
        self._journal.append(event)
        self._apply(event)

    def _apply(self, raw: Mapping[str, Any]) -> None:
        try:
            kind = raw.get("kind")
            if kind == "external-artifact-inspection-issued":
                self._apply_issue(raw)
            elif kind in {
                "external-artifact-inspection-claimed",
                "external-artifact-inspection-heartbeat",
            }:
                self._apply_lease(raw)
            elif kind == "external-artifact-inspection-reported":
                self._apply_report(raw)
            elif kind == "external-artifact-inspection-incomplete":
                self._apply_incomplete(raw)
            elif kind == "external-artifact-inspection-exhausted":
                self._apply_exhausted(raw)
            else:
                raise ValueError("unknown inspection event kind")
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ExternalArtifactInspectionRecoveryError(
                f"external artifact inspection event is invalid: {exc}"
            ) from exc

    @staticmethod
    def _require_event(raw: Mapping[str, object], fields: set[str], kind: str) -> None:
        if (
            set(raw) != fields
            or raw.get("kind") != kind
            or type(raw.get("version")) is not int
            or raw["version"] != _EVENT_VERSION
        ):
            raise ValueError("inspection event fields/version are invalid")
        digest = raw.get("eventDigest")
        if (
            not isinstance(digest, str)
            or _DIGEST_RE.fullmatch(digest) is None
            or digest != _event_digest(raw)
        ):
            raise ValueError("inspection event digest is invalid")

    def _apply_issue(self, raw: Mapping[str, object]) -> None:
        self._require_event(
            raw,
            {
                "kind",
                "version",
                "eventDigest",
                "issuedAt",
                "request",
                "subject",
                "policyDigest",
                "naturalKey",
                "artifacts",
            },
            "external-artifact-inspection-issued",
        )
        request = ExternalArtifactInspectionRequestV1.model_validate(raw["request"])
        subject = SealedExternalSubjectV1.model_validate(raw["subject"])
        if (
            request.subject != subject
            or request.inspection_policy_digest != raw["policyDigest"]
            or not isinstance(raw["naturalKey"], list)
            or len(raw["naturalKey"]) != 8
        ):
            raise ValueError("inspection issue binding is invalid")
        key = self._natural_key(subject, request.inspection_policy_digest)
        if (
            tuple(raw["naturalKey"]) != key
            or request.request_id in self._records
            or key in self._requests_by_natural_key
            or not isinstance(raw["artifacts"], list)
        ):
            raise ValueError("inspection issue natural key is invalid")
        artifacts = tuple(self._artifact_from_wire(item) for item in raw["artifacts"])
        if not artifacts or len({item.entry_id for item in artifacts}) != len(artifacts):
            raise ValueError("inspection issue artifacts are invalid")
        sealed_artifacts = self._sealed_artifacts_for(subject)
        if sealed_artifacts is None or artifacts != sealed_artifacts:
            raise ValueError("inspection issue artifacts do not match sealed ingress")
        _parse_time(raw["issuedAt"], "issuedAt")
        self._records[request.request_id] = _InspectionRecord(request, artifacts)
        self._record_ids_by_subject_digest.setdefault(subject.canonical_digest(), []).append(
            request.request_id
        )
        self._requests_by_natural_key[key] = request.request_id

    def _apply_lease(self, raw: Mapping[str, object]) -> None:
        kind = str(raw.get("kind"))
        self._require_event(
            raw,
            {
                "kind",
                "version",
                "eventDigest",
                "requestId",
                "workerInstanceId",
                "leaseAcquisitionId",
                "leaseGeneration",
                "leaseExpiresAt",
            },
            kind,
        )
        record = self._records.get(_required_string(raw, "requestId"))
        if record is None or record.state not in {"QUEUED", "RUNNING", "REPORTED"}:
            raise ValueError("inspection lease is out of order")
        fence, expires = (
            _fence_from_event(raw),
            _parse_time(raw["leaseExpiresAt"], "leaseExpiresAt"),
        )
        policy = self._policy_for(record)
        if policy is None or expires > self._deadline(record, policy):
            raise ValueError("inspection lease exceeds its pinned absolute deadline")
        if kind.endswith("claimed"):
            if (
                fence.lease_generation != record.last_generation + 1
                or fence.lease_acquisition_id in record.used_acquisition_ids
            ):
                raise ValueError("inspection claim fence is not next")
            record.last_generation, record.acquisition_id = (
                fence.lease_generation,
                fence.lease_acquisition_id,
            )
            record.attempt_count += 1
            record.used_acquisition_ids.add(fence.lease_acquisition_id)
        elif record.lease is None or record.lease.fence != fence:
            raise ValueError("inspection heartbeat fence is stale")
        if record.report is None:
            record.state = "RUNNING"
        record.lease = _Lease(fence, expires)

    def _apply_report(self, raw: Mapping[str, object]) -> None:
        self._require_event(
            raw,
            {
                "kind",
                "version",
                "eventDigest",
                "requestId",
                "subjectDigest",
                "policyDigest",
                "reportDigest",
                "measurementPayloadDigest",
                "displayRequired",
                "workerInstanceId",
                "leaseAcquisitionId",
                "leaseGeneration",
                "recordedAt",
                "report",
            },
            "external-artifact-inspection-reported",
        )
        record = self._records.get(_required_string(raw, "requestId"))
        if record is None or record.report is not None or record.state != "RUNNING":
            raise ValueError("inspection report is out of order")
        fence = _fence_from_event(raw)
        recorded_at = _parse_time(raw["recordedAt"], "recordedAt")
        policy = self._policy_for(record)
        if (
            record.lease is None
            or record.lease.fence != fence
            or recorded_at >= record.lease.expires_at
            or policy is None
            or recorded_at >= self._deadline(record, policy)
        ):
            raise ValueError("inspection report lease is stale")
        report = ExternalArtifactInspectionReportV1.model_validate(raw["report"]).sealed()
        if not self._report_matches(record, fence, report) or any(
            raw[key] != value
            for key, value in {
                "subjectDigest": report.subject_digest,
                "policyDigest": report.inspection_policy_digest,
                "reportDigest": report.report_digest,
                "measurementPayloadDigest": report.measurement_payload_digest,
            }.items()
        ):
            raise ValueError("inspection report binding is invalid")
        display_required = raw["displayRequired"]
        if type(display_required) is not bool or display_required != self._requires_display(
            record, report, recorded_at
        ):
            raise ValueError("inspection report display requirement is invalid")
        record.report, record.state, record.display_required = (
            report,
            "REPORTED",
            display_required,
        )

    def _apply_incomplete(self, raw: Mapping[str, object]) -> None:
        self._require_event(
            raw,
            {
                "kind",
                "version",
                "eventDigest",
                "requestId",
                "failure",
                "failureDigest",
                "failureCount",
                "attemptCount",
                "policyDigest",
                "retryRuleId",
                "nextEligibleAt",
                "retryExhausted",
                "workerInstanceId",
                "leaseAcquisitionId",
                "leaseGeneration",
                "recordedAt",
            },
            "external-artifact-inspection-incomplete",
        )
        record = self._records.get(_required_string(raw, "requestId"))
        if record is None or record.report is not None or record.state != "RUNNING":
            raise ValueError("inspection incomplete failure is out of order")
        fence = _fence_from_event(raw)
        if not isinstance(raw["failure"], Mapping):
            raise ValueError("inspection failure payload is invalid")
        failure = ExternalInspectionFailureV1(str(raw["failure"].get("reason")))
        count, exhausted = raw["failureCount"], raw["retryExhausted"]
        attempt_count = raw["attemptCount"]
        rule_id = raw["retryRuleId"]
        policy = self._policy_for(record)
        recorded_at = _parse_time(raw["recordedAt"], "recordedAt")
        if (
            record.lease is None
            or record.lease.fence != fence
            or recorded_at >= record.lease.expires_at
            or policy is None
            or policy.resource_envelope is None
            or type(count) is not int
            or count != record.failures + 1
            or type(attempt_count) is not int
            or attempt_count != record.attempt_count
            or raw["policyDigest"] != record.request.inspection_policy_digest
            or raw["failureDigest"] != failure.canonical_digest()
            or (rule_id is not None and not isinstance(rule_id, str))
            or raw["nextEligibleAt"] != _wire_time(recorded_at)
            or type(exhausted) is not bool
            or exhausted
            != (
                rule_id != failure.retry_rule_id
                or rule_id not in policy.inspection_rule_ids
                or attempt_count >= 1 + policy.resource_envelope.max_retry_attempts
                or recorded_at >= self._deadline(record, policy)
            )
        ):
            raise ValueError("inspection failure event is invalid")
        record.failures, record.lease = count, None
        record.state = "FAILED" if exhausted else "QUEUED"

    def _apply_exhausted(self, raw: Mapping[str, object]) -> None:
        self._require_event(
            raw,
            {
                "kind",
                "version",
                "eventDigest",
                "requestId",
                "reason",
                "policyDigest",
                "attemptCount",
                "exhaustedAt",
            },
            "external-artifact-inspection-exhausted",
        )
        record = self._records.get(_required_string(raw, "requestId"))
        if record is None or record.terminal_reason is not None:
            raise ValueError("inspection exhaustion is out of order")
        policy = self._policy_for(record)
        exhausted_at = _parse_time(raw["exhaustedAt"], "exhaustedAt")
        if (
            policy is None
            or policy.resource_envelope is None
            or raw["policyDigest"] != record.request.inspection_policy_digest
            or type(raw["attemptCount"]) is not int
            or raw["attemptCount"] != record.attempt_count
            or raw["reason"] not in {"DEADLINE_EXCEEDED", "RETRY_EXHAUSTED"}
            or (
                raw["reason"] == "DEADLINE_EXCEEDED"
                and exhausted_at < self._deadline(record, policy)
            )
            or (
                raw["reason"] == "RETRY_EXHAUSTED"
                and record.attempt_count < 1 + policy.resource_envelope.max_retry_attempts
            )
        ):
            raise ValueError("inspection exhaustion event is invalid")
        record.terminal_reason, record.lease = str(raw["reason"]), None
        if record.report is None:
            record.state = "FAILED"


def _require_scoped_work_order(work_orders: Any, work_order_id: str, principal: Principal) -> Any:
    """INV-060: derive organization/Site/WorkArea scope from the WorkOrder.

    The organization comes from the authenticated principal, never the body.
    The order's Site must be granted and every WorkArea of the order must be
    granted. An order with no WorkArea anchor fails closed for area-restricted
    principals — ``set() <= grants`` would otherwise pass vacuously with no
    resource proving the scope. Mismatches fold into the same non-disclosing
    404 as a missing order.
    """
    order = work_orders.get(work_order_id, organization_id=principal.organization_id)
    if order is None:
        raise HTTPException(404, "EXTERNAL_RECONSTRUCTION_NOT_FOUND")
    if principal.allowed_site_ids is not None and order.site_id not in principal.allowed_site_ids:
        raise HTTPException(404, "EXTERNAL_RECONSTRUCTION_NOT_FOUND")
    areas = getattr(order, "work_area_ids", None) or ()
    if principal.allowed_work_area_ids is not None and (
        not areas or not set(areas).issubset(principal.allowed_work_area_ids)
    ):
        raise HTTPException(404, "EXTERNAL_RECONSTRUCTION_NOT_FOUND")
    return order


def mount_external_artifact_inspections(
    app: FastAPI,
    store: ExternalArtifactInspectionStore,
    *,
    reconstruction: Any,
    work_orders: Any,
    display_store: Any | None = None,
) -> None:
    """Mount private worker work and the scoped human inspection projection."""
    router = APIRouter(prefix="/v1/internal/external-validation", tags=["external-validation"])
    worker = require_permission(Permission.PROCESSING_WORK)
    read = require_permission(Permission.SITES_READ)

    def fence_from_headers(
        worker_instance_id: str | None = Header(default=None, alias="X-KSI-Worker-Instance-Id"),
        lease_acquisition_id: str | None = Header(default=None, alias="X-KSI-Lease-Acquisition-Id"),
        lease_generation: str | None = Header(default=None, alias="X-KSI-Lease-Generation"),
    ) -> LeaseFence:
        if worker_instance_id is None or lease_acquisition_id is None or lease_generation is None:
            raise HTTPException(422, "LEASE_FENCE_REQUIRED")
        try:
            fence = LeaseFence(worker_instance_id, lease_acquisition_id, int(lease_generation))
        except ValueError as exc:
            raise HTTPException(422, "LEASE_FENCE_INVALID") from exc
        if not fence.has_valid_ids() or fence.lease_generation < 0:
            raise HTTPException(422, "LEASE_FENCE_INVALID")
        return fence

    def request_wire(request: ExternalArtifactInspectionRequestV1 | None) -> dict[str, Any] | None:
        return external_artifact_inspection_request_wire_dict(request) if request else None

    def fence_wire(fence: LeaseFence | None) -> dict[str, object] | None:
        if fence is None:
            return None
        return {
            "workerInstanceId": fence.worker_instance_id,
            "leaseAcquisitionId": fence.lease_acquisition_id,
            "leaseGeneration": fence.lease_generation,
        }

    def lease_wire(result: InspectionLeaseResult) -> dict[str, object]:
        return {
            "verdict": result.verdict.value,
            "request": request_wire(result.request),
            "leaseExpiresAt": _wire_time(result.lease_expires_at)
            if result.lease_expires_at is not None
            else None,
            "phase": result.phase.value if result.phase is not None else None,
            "fence": fence_wire(result.fence),
        }

    def input_wire(result: ExternalInspectionInputResponse) -> dict[str, object]:
        return {
            "verdict": result.verdict.value,
            "request": request_wire(result.request),
            "policy": result.policy.model_dump(by_alias=True, mode="json")
            if result.policy is not None
            else None,
            "artifacts": [
                {
                    "entryId": artifact.entry_id,
                    "kind": artifact.kind.value,
                    "observedSha256": artifact.observed_sha256,
                    "observedSizeBytes": artifact.observed_size_bytes,
                    "contentType": artifact.content_type,
                    "downloadUrl": artifact.download_url,
                    "requiredHeaders": artifact.required_headers,
                }
                for artifact in result.artifacts
            ],
            "phase": result.phase.value if result.phase is not None else None,
            "nextAction": result.next_action,
            "acceptedReport": external_artifact_inspection_report_wire_dict(result.accepted_report)
            if result.accepted_report is not None
            else None,
        }

    def report_wire(result: InspectionReportResult) -> dict[str, object]:
        return {
            "verdict": result.verdict.value,
            "report": external_artifact_inspection_report_wire_dict(result.report)
            if result.report is not None
            else None,
            "phase": result.phase.value if result.phase is not None else None,
        }

    def worker_error(verdict: InspectionVerdict) -> None:
        status = {
            InspectionVerdict.NOT_FOUND: 404,
            InspectionVerdict.STORAGE_UNAVAILABLE: 503,
            InspectionVerdict.LEASE_FENCE_REJECTED: 409,
            InspectionVerdict.POLICY_UNAVAILABLE: 409,
            InspectionVerdict.PAYLOAD_DIVERGENCE: 409,
            InspectionVerdict.REPORT_BINDING_REJECTED: 422,
            InspectionVerdict.DEADLINE_EXCEEDED: 409,
            InspectionVerdict.RETRY_EXHAUSTED: 409,
            InspectionVerdict.CONCURRENCY_LIMIT: 409,
            InspectionVerdict.INSPECTION_FAILED_INCOMPLETE: 409,
        }.get(verdict)
        if status is not None:
            raise HTTPException(status, verdict.value)

    def set_lease_headers(response: Response, result: InspectionLeaseResult) -> None:
        if result.fence is None:
            return
        response.headers["X-KSI-Worker-Instance-Id"] = result.fence.worker_instance_id
        response.headers["X-KSI-Lease-Acquisition-Id"] = result.fence.lease_acquisition_id
        response.headers["X-KSI-Lease-Generation"] = str(result.fence.lease_generation)

    @router.get("/inspections", response_model=ExternalInspectionPendingListView)
    def list_inspections(
        limit: int = Query(default=50, ge=1, le=100),
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> dict[str, list[dict[str, object]]]:
        return {
            "items": [
                {
                    "requestId": item.request_id,
                    "issuedAt": _wire_time(item.issued_at),
                    "phase": item.phase.value,
                }
                for item in store.list_pending(limit, organization_id=principal.organization_id)
            ]
        }

    @router.post("/inspections/{request_id}/lease", response_model=ExternalInspectionLeaseView)
    def lease_inspection(
        request_id: str,
        response: Response,
        fence: LeaseFence = Depends(fence_from_headers),  # noqa: B008
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> dict[str, object]:
        result = store.claim(
            request_id,
            fence,
            datetime.now(UTC),
            organization_id=principal.organization_id,
        )
        worker_error(result.verdict)
        set_lease_headers(response, result)
        return lease_wire(result)

    @router.get("/inspections/{request_id}/input", response_model=ExternalInspectionInputView)
    def inspection_input(
        request_id: str,
        fence: LeaseFence = Depends(fence_from_headers),  # noqa: B008
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> dict[str, object]:
        result = store.input_for(request_id, fence, organization_id=principal.organization_id)
        worker_error(result.verdict)
        return input_wire(result)

    @router.post("/inspections/{request_id}/heartbeat", response_model=ExternalInspectionLeaseView)
    def heartbeat_inspection(
        request_id: str,
        response: Response,
        fence: LeaseFence = Depends(fence_from_headers),  # noqa: B008
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> dict[str, object]:
        result = store.heartbeat(
            request_id,
            fence,
            datetime.now(UTC),
            organization_id=principal.organization_id,
        )
        worker_error(result.verdict)
        set_lease_headers(response, result)
        return lease_wire(result)

    @router.post("/inspections/{request_id}/report", response_model=ExternalInspectionReportView)
    def report_inspection(
        request_id: str,
        report: ExternalArtifactInspectionReportV1,
        fence: LeaseFence = Depends(fence_from_headers),  # noqa: B008
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> dict[str, object]:
        result = store.record_report(
            request_id,
            fence,
            report,
            datetime.now(UTC),
            organization_id=principal.organization_id,
        )
        worker_error(result.verdict)
        return report_wire(result)

    @router.post(
        "/inspections/{request_id}/incomplete-failure",
        response_model=ExternalInspectionReportView,
    )
    def incomplete_inspection(
        request_id: str,
        failure: ExternalInspectionFailureRequest,
        fence: LeaseFence = Depends(fence_from_headers),  # noqa: B008
        principal: Principal = Depends(worker),  # noqa: B008
    ) -> dict[str, object]:
        result = store.record_incomplete_failure(
            request_id,
            fence,
            ExternalInspectionFailureV1(failure.reason),
            datetime.now(UTC),
            organization_id=principal.organization_id,
        )
        worker_error(result.verdict)
        return report_wire(result)

    if display_store is not None:

        def display_error(result: Any) -> None:
            status = {
                "DISPLAY_NOT_REQUIRED": 404,
                "LEASE_FENCE_REJECTED": 409,
                "DECLARATION_DIVERGENCE": 422,
                "OUTPUT_LIMIT_EXCEEDED": 422,
                "OBSERVATION_MISSING": 422,
                "OBSERVATION_MISMATCH": 422,
                "STORAGE_UNAVAILABLE": 503,
                "RETRY_EXHAUSTED": 409,
                "POLICY_UNAVAILABLE": 409,
            }.get(result.verdict.value)
            if status is not None:
                raise HTTPException(status, result.verdict.value)

        def display_scope(request_id: str, principal: Principal) -> None:
            if not store.belongs_to_organization(request_id, principal.organization_id):
                raise HTTPException(404, "EXTERNAL_RECONSTRUCTION_NOT_FOUND")

        @router.post(
            "/inspections/{request_id}/display-artifacts/upload-grants",
            response_model=ExternalDisplayArtifactGrantView,
        )
        def display_upload_grant(
            request_id: str,
            declaration: SanitizedDisplayDeclarationV1,
            fence: LeaseFence = Depends(fence_from_headers),  # noqa: B008
            principal: Principal = Depends(worker),  # noqa: B008
        ) -> dict[str, object]:
            display_scope(request_id, principal)
            result = display_store.grant(request_id, declaration, fence, now=datetime.now(UTC))
            display_error(result)
            return {
                "verdict": result.verdict.value,
                "phase": result.phase.value,
                "declaration": result.declaration.model_dump(by_alias=True, mode="json")
                if result.declaration is not None
                else None,
                "uploadUrl": result.grant.upload_url if result.grant is not None else None,
                "requiredHeaders": (
                    result.grant.required_headers if result.grant is not None else {}
                ),
            }

        @router.post(
            "/inspections/{request_id}/display-artifacts/{display_id}/seal",
            response_model=ExternalDisplayArtifactSealView,
        )
        def seal_display(
            request_id: str,
            display_id: str,
            fence: LeaseFence = Depends(fence_from_headers),  # noqa: B008
            principal: Principal = Depends(worker),  # noqa: B008
        ) -> dict[str, object]:
            display_scope(request_id, principal)
            if not display_store.matches_declared_display_id(request_id, display_id):
                raise HTTPException(404, "EXTERNAL_RECONSTRUCTION_NOT_FOUND")
            result = display_store.seal(request_id, fence, now=datetime.now(UTC))
            display_error(result)
            if result.receipt is None or result.receipt.display_id != display_id:
                raise HTTPException(404, "EXTERNAL_RECONSTRUCTION_NOT_FOUND")
            return {
                "verdict": result.verdict.value,
                "phase": result.phase.value,
                "receipt": sanitized_display_receipt_wire_dict(result.receipt),
            }

    public = APIRouter(prefix="/v1/observation-work-orders", tags=["external-validation"])
    public_base = (
        "/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}"
    )

    def revision_for(
        work_order_id: str, submission_ref: str, revision: int, principal: Principal
    ) -> ExternalReconstructionRevision:
        order = _require_scoped_work_order(work_orders, work_order_id, principal)
        submission_id = reconstruction.resolve_submission_ref(
            work_order_id,
            submission_ref,
            organization_id=principal.organization_id,
            site_id=order.site_id,
        )
        record = (
            reconstruction.get(
                work_order_id,
                submission_id,
                revision,
                organization_id=principal.organization_id,
                site_id=order.site_id,
            )
            if submission_id is not None
            else None
        )
        if record is None:
            raise HTTPException(404, "EXTERNAL_RECONSTRUCTION_NOT_FOUND")
        return record

    @public.get(public_base + "/inspection", response_model=ExternalArtifactInspectionPublicView)
    def inspection_view(
        work_order_id: str,
        submission_ref: str,
        revision: int,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> dict[str, object]:
        record = revision_for(work_order_id, submission_ref, revision, principal)
        subject = store._subject_from_revision(record)  # noqa: SLF001 -- exact sealed-store bridge
        if subject is None:
            return {
                "registrationState": "REGISTERED",
                "sealState": "UNSEALED",
                "inspection": {
                    "state": "INSPECTION_PENDING_SEAL",
                    "request": None,
                    "phase": None,
                    "outcome": None,
                    "report": None,
                },
                "display": {
                    "state": "PENDING_INSPECTION",
                    "sanitizedDisplayRef": None,
                    "receiptDigest": None,
                },
            }
        snapshot = store.public_snapshot(subject)
        report = snapshot.report
        display_state, display_receipt = store.public_display_state(subject)
        return {
            "registrationState": "SEALED",
            "sealState": "SEALED",
            "inspection": {
                "state": snapshot.state,
                "request": (
                    external_artifact_inspection_request_wire_dict(snapshot.request)
                    if snapshot.request is not None
                    else None
                ),
                "phase": snapshot.phase.value if snapshot.phase is not None else None,
                "outcome": (
                    [
                        {
                            "artifactId": item.artifact_id,
                            "outcome": item.outcome.value,
                            "reason": item.reason,
                        }
                        for item in report.measurement_payload.outcomes
                    ]
                    if report is not None
                    else None
                ),
                "report": (
                    external_artifact_inspection_report_wire_dict(report)
                    if report is not None
                    else None
                ),
            },
            "display": {
                "state": display_state,
                "sanitizedDisplayRef": (
                    display_receipt.sanitized_display_ref if display_receipt is not None else None
                ),
                "receiptDigest": (
                    display_receipt.receipt_digest if display_receipt is not None else None
                ),
            },
        }

    @public.get(
        public_base + "/display-artifacts/{sanitized_display_ref}/download",
        response_model=ExternalSanitizedDisplayDownloadView,
    )
    def download_display_artifact(
        work_order_id: str,
        submission_ref: str,
        revision: int,
        sanitized_display_ref: str,
        principal: Principal = Depends(read),  # noqa: B008
    ) -> dict[str, object]:
        record = revision_for(work_order_id, submission_ref, revision, principal)
        subject = store._subject_from_revision(record)  # noqa: SLF001 -- exact sealed-store bridge
        if subject is None:
            raise HTTPException(404, "EXTERNAL_RECONSTRUCTION_NOT_FOUND")
        binding = store.public_display_download_binding(subject, sanitized_display_ref)
        if binding is None:
            raise HTTPException(404, "EXTERNAL_RECONSTRUCTION_NOT_FOUND")
        issued_at = datetime.now(UTC)
        download_url = store.presign_public_display_download(binding)
        if download_url is None:
            raise HTTPException(503, "EXTERNAL_DISPLAY_STORAGE_UNAVAILABLE")
        current = store.public_display_download_binding(subject, sanitized_display_ref)
        if current != binding:
            raise HTTPException(404, "EXTERNAL_RECONSTRUCTION_NOT_FOUND")
        return {
            "sanitizedDisplayRef": binding.sanitized_display_ref,
            "receiptDigest": binding.receipt_digest,
            "observedDerivativeSha256": binding.observed_derivative_sha256,
            "observedDerivativeSizeBytes": binding.observed_derivative_size_bytes,
            "observedDerivativeContentType": binding.observed_derivative_content_type,
            "downloadUrl": download_url,
            "expiresAt": _wire_time(issued_at + DEFAULT_VIEW_TTL),
            "requiredHeaders": {},
        }

    app.state.external_artifact_inspection_store = store
    app.state.external_display_artifact_store = display_store
    app.include_router(router)
    app.include_router(public)


__all__ = [
    "ExternalArtifactInputV1",
    "ExternalArtifactInspectionRecoveryError",
    "ExternalArtifactInspectionStore",
    "ExternalInspectionFailureV1",
    "ExternalInspectionInputResponse",
    "InspectionIssueResult",
    "InspectionLeaseResult",
    "InspectionPhase",
    "InspectionReportResult",
    "InspectionVerdict",
    "PendingExternalInspection",
    "mount_external_artifact_inspections",
]
