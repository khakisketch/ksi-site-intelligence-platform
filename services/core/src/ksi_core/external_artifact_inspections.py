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
from typing import Any, Protocol

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalArtifactInspectionReportV1,
    ExternalArtifactInspectionRequestV1,
    ExternalValidationPolicyV1,
    SealedExternalSubjectV1,
    external_artifact_inspection_report_wire_dict,
    external_artifact_inspection_request_wire_dict,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from pydantic import ValidationError

from ksi_core.durable_journal import DurableJournal, JournalSealedError
from ksi_core.evidence import DEFAULT_VIEW_TTL, EvidenceStorage, EvidenceStorageError
from ksi_core.external_reconstruction import ExternalReconstructionRevision
from ksi_core.external_validation_policy import (
    ExternalValidationPolicyRegistry,
    PolicySelectionStatus,
)
from ksi_core.leasing import LeaseFence

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
    ) -> None:
        self._journal = journal
        self._policy_registry = policy_registry
        self._external_reconstruction = external_reconstruction
        self._storage = storage
        self._display_store = display_store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._records: dict[str, _InspectionRecord] = {}
        self._requests_by_natural_key: dict[tuple[object, ...], str] = {}
        self._lock = threading.RLock()
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
        with self._lock:
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

    def list_pending(self, limit: int) -> tuple[PendingExternalInspection, ...]:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit must be a positive integer")
        now = self._clock()
        _wire_time(now)
        with self._lock:
            records = tuple(self._records.values())
        candidates: list[PendingExternalInspection] = []
        for record in records:
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

    def claim(self, request_id: str, fence: LeaseFence, now: datetime) -> InspectionLeaseResult:
        _wire_time(now)
        if not fence.has_valid_ids() or fence.lease_generation < 0:
            return InspectionLeaseResult(InspectionVerdict.LEASE_FENCE_REJECTED)
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return InspectionLeaseResult(InspectionVerdict.NOT_FOUND)
            display_unfinished = self._display_is_unfinished(request_id)
            if not self._policy_is_current(record):
                return InspectionLeaseResult(InspectionVerdict.POLICY_UNAVAILABLE, record.request)
            if (
                record.report is not None
                and display_unfinished
                and not self._display_policy_is_current(record)
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

    def input_for(self, request_id: str, fence: LeaseFence) -> ExternalInspectionInputResponse:
        now = self._clock()
        _wire_time(now)
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return ExternalInspectionInputResponse(InspectionVerdict.NOT_FOUND)
            if not self._policy_is_current(record):
                return ExternalInspectionInputResponse(
                    InspectionVerdict.POLICY_UNAVAILABLE, request=record.request
                )
            if record.report is not None and not self._display_policy_is_current(record):
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
        with self._lock:
            commit_now = self._clock()
            _wire_time(commit_now)
            record = self._records.get(request_id)
            if record is None:
                return ExternalInspectionInputResponse(InspectionVerdict.NOT_FOUND)
            if record.request != request or record.report != accepted_report:
                return ExternalInspectionInputResponse(
                    InspectionVerdict.LEASE_FENCE_REJECTED, request=record.request
                )
            if not self._policy_is_current(record):
                return ExternalInspectionInputResponse(
                    InspectionVerdict.POLICY_UNAVAILABLE, request=record.request
                )
            if record.report is not None and not self._display_policy_is_current(record):
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

    def heartbeat(self, request_id: str, fence: LeaseFence, now: datetime) -> InspectionLeaseResult:
        _wire_time(now)
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return InspectionLeaseResult(InspectionVerdict.NOT_FOUND)
            if not self._policy_is_current(record):
                return InspectionLeaseResult(InspectionVerdict.POLICY_UNAVAILABLE, record.request)
            if record.report is not None and not self._display_policy_is_current(record):
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
    ) -> InspectionReportResult:
        _wire_time(now)
        sealed = report.sealed()
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return InspectionReportResult(InspectionVerdict.NOT_FOUND)
            if record.report is not None:
                if not self._policy_is_current(record):
                    return InspectionReportResult(InspectionVerdict.POLICY_UNAVAILABLE)
                if not self._display_policy_is_current(record):
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
            if not self._policy_is_current(record):
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
    ) -> InspectionReportResult:
        _wire_time(now)
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return InspectionReportResult(InspectionVerdict.NOT_FOUND)
            if record.report is not None or record.state != "RUNNING":
                return InspectionReportResult(InspectionVerdict.REPORT_BINDING_REJECTED)
            if not self._policy_is_current(record):
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
        with self._lock:
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
            selected = self._policy_registry.select_for_use("DISPLAY", (record.request.subject,))
            if (
                policy is None
                or commit_now >= record.lease.expires_at
                or commit_now >= self._deadline(record, policy)
                or selected.status is not PolicySelectionStatus.ACTIVE
                or selected.policy is None
                or selected.policy.policy_digest != record.request.inspection_policy_digest
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

    def _display_policy_is_current(self, record: _InspectionRecord) -> bool:
        selected = self._policy_registry.select_for_use("DISPLAY", (record.request.subject,))
        return (
            selected.status is PolicySelectionStatus.ACTIVE
            and selected.policy is not None
            and selected.policy.policy_digest == record.request.inspection_policy_digest
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
        return bindings == report_bindings

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
            if (
                record is None
                or record.terminal_reason is not None
                or not record.display_required
            ):
                return False
            if self._display_store is None:
                return True
        return str(self._display_store.phase_for(request_id)) in {
            "NOT_REQUIRED",
            "QUEUED",
            "RUNNING",
        }

    def _phase_for_record(self, record: _InspectionRecord) -> InspectionPhase:
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

    def _record_exhaustion(
        self, record: _InspectionRecord, reason: str, now: datetime
    ) -> None:
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
]
