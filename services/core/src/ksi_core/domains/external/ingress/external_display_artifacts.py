"""Private Core store for sanitized derivatives of external inspection reports."""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, cast

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ExternalArtifactInspectionReportV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_display_artifact import (
    SanitizedDisplayDeclarationV1,
    SanitizedDisplayReceiptV1,
    sanitized_display_declaration_wire_dict,
    sanitized_display_receipt_wire_dict,
)
from pydantic import ValidationError

from ksi_core.domains.artifacts.evidence import (
    DEFAULT_UPLOAD_TTL,
    DEFAULT_VIEW_TTL,
    DigestBoundEvidenceStorage,
    EvidenceStorageError,
    ObjectStorageObservationPort,
)
from ksi_core.domains.external.ingress.external_artifact_inspections import (
    ExternalInspectionFailureV1,
)
from ksi_core.domains.external.ingress.external_validation_policy import (
    ExternalValidationPolicyRegistry,
)
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.foundation.leasing import LeaseFence

_EVENT_VERSION = 1
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class ExternalDisplayArtifactRecoveryError(RuntimeError):
    """Display journal recovery is deliberately fail-closed."""


class DisplayPhase(StrEnum):
    NOT_REQUIRED = "NOT_REQUIRED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SEALED = "SEALED"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"


class DisplayArtifactVerdict(StrEnum):
    QUEUED = "QUEUED"
    DISPLAY_NOT_REQUIRED = "DISPLAY_NOT_REQUIRED"
    LEASE_FENCE_REJECTED = "LEASE_FENCE_REJECTED"
    POLICY_UNAVAILABLE = "POLICY_UNAVAILABLE"
    DECLARATION_RECORDED = "DECLARATION_RECORDED"
    DECLARATION_DIVERGENCE = "DECLARATION_DIVERGENCE"
    OBSERVATION_MISSING = "OBSERVATION_MISSING"
    OBSERVATION_MISMATCH = "OBSERVATION_MISMATCH"
    SEALED = "SEALED"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    STORAGE_UNAVAILABLE = "STORAGE_UNAVAILABLE"
    OUTPUT_LIMIT_EXCEEDED = "OUTPUT_LIMIT_EXCEEDED"


@dataclass(frozen=True, slots=True)
class SanitizedDisplayGrant:
    upload_url: str
    required_headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class DisplayArtifactResult:
    verdict: DisplayArtifactVerdict
    phase: DisplayPhase
    declaration: SanitizedDisplayDeclarationV1 | None = None
    receipt: SanitizedDisplayReceiptV1 | None = None
    grant: SanitizedDisplayGrant | None = None


@dataclass(frozen=True, slots=True)
class PublicDisplaySnapshot:
    """Receipt facts that are safe to project after the parent scope is checked."""

    state: DisplayPhase
    receipt: SanitizedDisplayReceiptV1 | None = None


@dataclass(frozen=True, slots=True)
class PublicDisplayDownloadBinding:
    """Exact receipt identity plus the private key needed only for presigning."""

    sanitized_display_ref: str
    receipt_digest: str
    observed_derivative_sha256: str
    observed_derivative_size_bytes: int
    observed_derivative_content_type: str
    object_key: str


@dataclass(slots=True)
class _Record:
    request_id: str
    subject: SealedExternalSubjectV1
    report_digest: str
    policy_digest: str
    build_digest: str
    max_attempts: int
    max_output_bytes: int
    phase: DisplayPhase = DisplayPhase.QUEUED
    declaration: SanitizedDisplayDeclarationV1 | None = None
    receipt: SanitizedDisplayReceiptV1 | None = None
    failures: int = 0
    last_failure_fence: LeaseFence | None = None
    last_failure_reason: str | None = None


def _canonical_digest(payload: Mapping[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


def _event_digest(event: Mapping[str, object]) -> str:
    return _canonical_digest({key: value for key, value in event.items() if key != "eventDigest"})


def _wire_time(value: datetime) -> str:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError("time must be UTC timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value: object, field: str) -> datetime:
    if not isinstance(value, str) or _UTC_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be strict UTC RFC3339")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    _wire_time(result)
    return result


def _required_string(raw: Mapping[str, object], field: str) -> str:
    value = raw[field]
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    return value


def _fence_fields(fence: LeaseFence) -> dict[str, object]:
    if not fence.is_well_formed():
        raise ValueError("lease fence must hold UUIDv4 ids and positive generation")
    return {
        "workerInstanceId": fence.worker_instance_id,
        "leaseAcquisitionId": fence.lease_acquisition_id,
        "leaseGeneration": fence.lease_generation,
    }


def _fence(raw: Mapping[str, object]) -> LeaseFence:
    generation = raw["leaseGeneration"]
    if type(generation) is not int:
        raise ValueError("lease generation is not strict integer")
    result = LeaseFence(str(raw["workerInstanceId"]), str(raw["leaseAcquisitionId"]), generation)
    if not result.is_well_formed():
        raise ValueError("invalid display lease fence")
    return result


class ExternalDisplayArtifactStore:
    """Private sanitized display declaration/receipt journal.

    The inspection store owns fence lifetimes. The callback is run outside this
    lock, so the two append-only journals intentionally have no atomic claim.
    """

    def __init__(
        self,
        journal: DurableJournal,
        *,
        policy_registry: ExternalValidationPolicyRegistry,
        storage: DigestBoundEvidenceStorage | ObjectStorageObservationPort,
        clock: Callable[[], datetime] | None = None,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        self._journal = journal
        self._policy_registry = policy_registry
        self._storage = storage
        self._clock = clock or (lambda: datetime.now(UTC))
        self._coordinator = coordinator or ExternalAuthorityCurrentnessCoordinator()
        if coordinator is not None and policy_registry.coordinator is not self._coordinator:
            raise ValueError("display policy registry must share currentness coordinator")
        self._records: dict[str, _Record] = {}
        self._mutation_guard: Callable[..., DisplayArtifactResult | None] | None = None
        self._lock = threading.RLock()
        try:
            for event in journal.replay():
                self._apply(event)
        except BaseException as exc:
            journal.close()
            if isinstance(exc, ExternalDisplayArtifactRecoveryError):
                raise
            raise ExternalDisplayArtifactRecoveryError(
                f"display journal replay failed: {exc}"
            ) from exc

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def bind_mutation_guard(self, guard: Callable[..., DisplayArtifactResult | None]) -> None:
        """Install the inspection-owned commit closure for durable display writes.

        The callback is deliberately invoked with no display lock held.  Its
        implementation owns the only permitted nested order: inspection lock
        first, then this store's lock inside the supplied commit callback.
        """
        self._mutation_guard = guard

    def phase_for(self, request_id: str) -> DisplayPhase:
        with self._lock:
            record = self._records.get(request_id)
            return record.phase if record is not None else DisplayPhase.NOT_REQUIRED

    def matches_declared_display_id(self, request_id: str, display_id: str) -> bool:
        """Check the sealed worker path ID before an HTTP route can mutate a receipt."""
        with self._lock:
            record = self._records.get(request_id)
            return (
                record is not None
                and record.declaration is not None
                and record.declaration.display_id == display_id
            )

    def public_snapshot(
        self,
        request_id: str,
        *,
        subject_digest: str,
        report_digest: str,
        policy_digest: str,
    ) -> PublicDisplaySnapshot | None:
        """Read a receipt state only when every immutable parent binding matches."""
        with self._lock:
            record = self._records.get(request_id)
            if (
                record is None
                or record.subject.canonical_digest() != subject_digest
                or record.report_digest != report_digest
                or record.policy_digest != policy_digest
            ):
                return None
            return PublicDisplaySnapshot(record.phase, record.receipt)

    def public_download_binding(
        self,
        request_id: str,
        *,
        subject_digest: str,
        report_digest: str,
        policy_digest: str,
        sanitized_display_ref: str,
    ) -> PublicDisplayDownloadBinding | None:
        """Resolve one opaque receipt to a private presign target under the store lock."""
        if re.fullmatch(r"sda-v1-[0-9a-f]{64}", sanitized_display_ref) is None:
            return None
        snapshot = self.public_snapshot(
            request_id,
            subject_digest=subject_digest,
            report_digest=report_digest,
            policy_digest=policy_digest,
        )
        receipt = snapshot.receipt if snapshot is not None else None
        if snapshot is None or snapshot.state is not DisplayPhase.SEALED or receipt is None:
            return None
        if receipt.sanitized_display_ref != sanitized_display_ref or receipt.receipt_digest is None:
            return None
        with self._lock:
            record = self._records.get(request_id)
            if record is None or record.declaration is None or record.receipt != receipt:
                return None
            return PublicDisplayDownloadBinding(
                receipt.sanitized_display_ref,
                receipt.receipt_digest,
                receipt.observed_derivative_sha256,
                receipt.observed_derivative_size_bytes,
                receipt.observed_derivative_content_type,
                self._object_key(record.declaration),
            )

    def presign_public_download(self, binding: PublicDisplayDownloadBinding) -> str | None:
        """Create a short-lived capability without retaining it in a durable journal."""
        try:
            return cast(Any, self._storage).presigned_get(binding.object_key, ttl=DEFAULT_VIEW_TTL)
        except (AttributeError, EvidenceStorageError):
            return None

    def ensure_after_report(
        self,
        report: ExternalArtifactInspectionReportV1,
        *,
        display_permitted: bool,
        measured_ortho: bool,
        max_retry_attempts: int,
        max_output_bytes: int,
        now: datetime,
    ) -> DisplayPhase:
        """Durably make display work eligible only after report acceptance."""
        _wire_time(now)
        report = report.sealed()
        if not display_permitted or not measured_ortho:
            return DisplayPhase.NOT_REQUIRED
        if type(max_retry_attempts) is not int or max_retry_attempts < 1:
            raise ValueError("retry budget must be a positive policy value")
        if type(max_output_bytes) is not int or max_output_bytes < 1:
            raise ValueError("display output limit must be a positive policy value")
        # This is the one display mutation that is not entered through the
        # inspection-owned lease callback.  It must therefore join the shared
        # authority coordinator directly before its journal projection.
        with self._coordinator.mutation(), self._lock:
            existing = self._records.get(report.request_id)
            if existing is not None:
                if (
                    existing.report_digest != report.report_digest
                    or existing.policy_digest != report.inspection_policy_digest
                ):
                    raise ExternalDisplayArtifactRecoveryError("display report binding diverges")
                return existing.phase
            event: dict[str, object] = {
                "kind": "external-display-artifact-queued",
                "version": _EVENT_VERSION,
                "requestId": report.request_id,
                "subject": report.subject.model_dump(by_alias=True, mode="json"),
                "sourceSubjectDigest": report.subject_digest,
                "sourceReportDigest": report.report_digest,
                "policyDigest": report.inspection_policy_digest,
                "inspectorBuildDigest": report.inspector_build_digest,
                "maxRetryAttempts": max_retry_attempts,
                "maxOutputBytes": max_output_bytes,
                "queuedAt": _wire_time(now),
            }
            event["eventDigest"] = _event_digest(event)
            self._append_apply(event)
            return DisplayPhase.QUEUED

    def grant(
        self,
        request_id: str,
        declaration: SanitizedDisplayDeclarationV1,
        fence: LeaseFence,
        *,
        now: datetime,
    ) -> DisplayArtifactResult:
        """Record declaration before a transient digest-bound upload grant."""
        _wire_time(now)
        record = self._record(request_id)
        if record is None:
            return self._result(request_id, DisplayArtifactVerdict.DISPLAY_NOT_REQUIRED)
        declaration = declaration.sealed()
        if not self._matches_declaration(record, declaration):
            return self._result(request_id, DisplayArtifactVerdict.DECLARATION_DIVERGENCE)
        if declaration.declared_derivative_size_bytes > record.max_output_bytes:
            return self._result(request_id, DisplayArtifactVerdict.OUTPUT_LIMIT_EXCEEDED)
        committed = self._run_mutation_guard(
            request_id,
            fence,
            record.report_digest,
            lambda commit_now, _attempt_count, _policy: self._commit_grant(
                request_id, declaration, fence, commit_now
            ),
        )
        if committed is None:
            return self._result(request_id, DisplayArtifactVerdict.LEASE_FENCE_REJECTED)
        if committed.verdict is not DisplayArtifactVerdict.DECLARATION_RECORDED:
            return committed
        persisted_declaration = committed.declaration
        if persisted_declaration is None:
            return self._result(request_id, DisplayArtifactVerdict.STORAGE_UNAVAILABLE)
        try:
            capability = cast(DigestBoundEvidenceStorage, self._storage).presigned_put_bound_digest(
                self._object_key(persisted_declaration),
                content_type=persisted_declaration.declared_derivative_content_type,
                content_digest=persisted_declaration.declared_derivative_sha256,
                ttl=DEFAULT_UPLOAD_TTL,
            )
        except (AttributeError, EvidenceStorageError):
            return self._result(request_id, DisplayArtifactVerdict.STORAGE_UNAVAILABLE)
        return DisplayArtifactResult(
            DisplayArtifactVerdict.DECLARATION_RECORDED,
            self.phase_for(request_id),
            declaration=persisted_declaration,
            grant=SanitizedDisplayGrant(capability.upload_url, dict(capability.required_headers)),
        )

    def _commit_grant(
        self,
        request_id: str,
        declaration: SanitizedDisplayDeclarationV1,
        fence: LeaseFence,
        commit_now: datetime,
    ) -> DisplayArtifactResult:
        """Append only while the inspection-owned guard is live."""
        with self._lock:
            current = self._records.get(request_id)
            if current is None:
                return self._result(request_id, DisplayArtifactVerdict.DISPLAY_NOT_REQUIRED)
            if not self._matches_declaration(current, declaration):
                return self._result(request_id, DisplayArtifactVerdict.DECLARATION_DIVERGENCE)
            if declaration.declared_derivative_size_bytes > current.max_output_bytes:
                return self._result(request_id, DisplayArtifactVerdict.OUTPUT_LIMIT_EXCEEDED)
            if current.phase in {DisplayPhase.SEALED, DisplayPhase.RETRY_EXHAUSTED}:
                return self._result(request_id, DisplayArtifactVerdict.RETRY_EXHAUSTED)
            if current.declaration is None:
                event: dict[str, object] = {
                    "kind": "external-display-artifact-issued",
                    "version": _EVENT_VERSION,
                    "requestId": request_id,
                    "displayId": declaration.display_id,
                    "sourceSubjectDigest": declaration.source_subject_digest,
                    "sourceReportDigest": declaration.source_report_digest,
                    "policyDigest": declaration.policy_digest,
                    "inspectorBuildDigest": declaration.inspector_build_digest,
                    "declaredDerivativeSha256": declaration.declared_derivative_sha256,
                    "declaredDerivativeSizeBytes": declaration.declared_derivative_size_bytes,
                    "declaredDerivativeContentType": declaration.declared_derivative_content_type,
                    **_fence_fields(fence),
                    "issuedAt": _wire_time(commit_now),
                    "declaration": sanitized_display_declaration_wire_dict(declaration),
                }
                event["eventDigest"] = _event_digest(event)
                try:
                    self._append_apply(event)
                except JournalSealedError:
                    return self._result(request_id, DisplayArtifactVerdict.STORAGE_UNAVAILABLE)
            elif current.declaration.declaration_digest != declaration.declaration_digest:
                return self._result(request_id, DisplayArtifactVerdict.DECLARATION_DIVERGENCE)
            persisted = self._records[request_id].declaration
            return DisplayArtifactResult(
                DisplayArtifactVerdict.DECLARATION_RECORDED,
                self._records[request_id].phase,
                declaration=persisted,
            )

    def seal(self, request_id: str, fence: LeaseFence, *, now: datetime) -> DisplayArtifactResult:
        """HEAD exact bytes, then append an opaque receipt that reveals no storage key."""
        _wire_time(now)
        record = self._record(request_id)
        if record is None or record.declaration is None:
            return self._result(request_id, DisplayArtifactVerdict.DISPLAY_NOT_REQUIRED)
        if record.receipt is not None:
            guarded = self._run_mutation_guard(
                request_id,
                fence,
                record.report_digest,
                lambda _commit_now, _attempt_count, _policy: self._result(
                    request_id, DisplayArtifactVerdict.SEALED
                ),
            )
            return (
                guarded
                if guarded is not None
                else self._result(request_id, DisplayArtifactVerdict.LEASE_FENCE_REJECTED)
            )
        declaration = record.declaration
        try:
            observed = cast(ObjectStorageObservationPort, self._storage).observe_object(
                self._object_key(declaration)
            )
        except (AttributeError, EvidenceStorageError):
            return self._result(request_id, DisplayArtifactVerdict.STORAGE_UNAVAILABLE)
        if not observed.exists:
            return self._result(request_id, DisplayArtifactVerdict.OBSERVATION_MISSING)
        if (
            observed.object_key != self._object_key(declaration)
            or observed.sha256 != declaration.declared_derivative_sha256
            or observed.size_bytes != declaration.declared_derivative_size_bytes
            or observed.content_type != declaration.declared_derivative_content_type
        ):
            return self._result(request_id, DisplayArtifactVerdict.OBSERVATION_MISMATCH)
        committed = self._run_mutation_guard(
            request_id,
            fence,
            record.report_digest,
            lambda commit_now, _attempt_count, _policy: self._commit_seal(
                request_id, declaration, fence, observed, commit_now
            ),
        )
        if committed is None:
            return self._result(request_id, DisplayArtifactVerdict.LEASE_FENCE_REJECTED)
        return committed

    def _commit_seal(
        self,
        request_id: str,
        declaration: SanitizedDisplayDeclarationV1,
        fence: LeaseFence,
        observed: Any,
        commit_now: datetime,
    ) -> DisplayArtifactResult:
        """Re-fetch declaration after storage I/O before the immutable receipt append."""
        with self._lock:
            current = self._records.get(request_id)
            if current is None or current.declaration is None:
                return self._result(request_id, DisplayArtifactVerdict.DISPLAY_NOT_REQUIRED)
            if current.receipt is not None:
                return self._result(request_id, DisplayArtifactVerdict.SEALED)
            if current.phase is DisplayPhase.RETRY_EXHAUSTED:
                return self._result(request_id, DisplayArtifactVerdict.RETRY_EXHAUSTED)
            if current.declaration.declaration_digest != declaration.declaration_digest:
                return self._result(request_id, DisplayArtifactVerdict.DECLARATION_DIVERGENCE)
            if (
                observed.object_key != self._object_key(current.declaration)
                or observed.sha256 != current.declaration.declared_derivative_sha256
                or observed.size_bytes != current.declaration.declared_derivative_size_bytes
                or observed.content_type != current.declaration.declared_derivative_content_type
            ):
                return self._result(request_id, DisplayArtifactVerdict.OBSERVATION_MISMATCH)
            declaration_digest = current.declaration.declaration_digest
            if declaration_digest is None:
                return self._result(request_id, DisplayArtifactVerdict.DECLARATION_DIVERGENCE)
            receipt = SanitizedDisplayReceiptV1(
                display_id=current.declaration.display_id,
                request_id=request_id,
                declaration_digest=declaration_digest,
                source_subject_digest=current.declaration.source_subject_digest,
                source_report_digest=current.declaration.source_report_digest,
                policy_digest=current.declaration.policy_digest,
                inspector_build_digest=current.declaration.inspector_build_digest,
                observed_derivative_sha256=observed.sha256,
                observed_derivative_size_bytes=observed.size_bytes,
                observed_derivative_content_type=observed.content_type,
                sanitized_display_ref=self._display_ref(current.declaration),
                sealed_at=commit_now,
            ).sealed()
            event: dict[str, object] = {
                "kind": "external-display-artifact-sealed",
                "version": _EVENT_VERSION,
                "requestId": request_id,
                "displayId": receipt.display_id,
                "declarationDigest": receipt.declaration_digest,
                "sourceSubjectDigest": receipt.source_subject_digest,
                "sourceReportDigest": receipt.source_report_digest,
                "policyDigest": receipt.policy_digest,
                "inspectorBuildDigest": receipt.inspector_build_digest,
                "observedDerivativeSha256": receipt.observed_derivative_sha256,
                "observedDerivativeSizeBytes": receipt.observed_derivative_size_bytes,
                "observedDerivativeContentType": receipt.observed_derivative_content_type,
                **_fence_fields(fence),
                "sealedAt": _wire_time(commit_now),
                "receipt": sanitized_display_receipt_wire_dict(receipt),
            }
            event["eventDigest"] = _event_digest(event)
            try:
                self._append_apply(event)
            except JournalSealedError:
                return self._result(request_id, DisplayArtifactVerdict.STORAGE_UNAVAILABLE)
        return self._result(request_id, DisplayArtifactVerdict.SEALED)

    def record_failure(
        self, request_id: str, fence: LeaseFence, reason: str, *, now: datetime
    ) -> DisplayArtifactResult:
        """Bounded retry failure; exhaustion retains the report and no receipt."""
        _wire_time(now)
        failure = ExternalInspectionFailureV1(reason)
        record = self._record(request_id)
        if record is None:
            return self._result(request_id, DisplayArtifactVerdict.DISPLAY_NOT_REQUIRED)
        committed = self._run_mutation_guard(
            request_id,
            fence,
            record.report_digest,
            lambda commit_now, attempt_count, policy: self._commit_failure(
                request_id, fence, failure, attempt_count, policy, commit_now
            ),
        )
        if committed is None:
            return self._result(request_id, DisplayArtifactVerdict.LEASE_FENCE_REJECTED)
        return committed

    def _commit_failure(
        self,
        request_id: str,
        fence: LeaseFence,
        failure: ExternalInspectionFailureV1,
        attempt_count: int,
        policy: Any,
        commit_now: datetime,
    ) -> DisplayArtifactResult:
        with self._lock:
            record = self._records.get(request_id)
            if record is None:
                return self._result(request_id, DisplayArtifactVerdict.DISPLAY_NOT_REQUIRED)
            if record.phase in {DisplayPhase.SEALED, DisplayPhase.RETRY_EXHAUSTED}:
                return self._result(request_id, DisplayArtifactVerdict.RETRY_EXHAUSTED)
            if record.last_failure_fence == fence and record.last_failure_reason == failure.reason:
                return self._result(request_id, DisplayArtifactVerdict.QUEUED)
            envelope = policy.resource_envelope
            if envelope is None or policy.policy_digest != record.policy_digest:
                return self._result(request_id, DisplayArtifactVerdict.POLICY_UNAVAILABLE)
            rule_id = failure.retry_rule_id
            recognized_rule = (
                rule_id if rule_id is not None and rule_id in policy.inspection_rule_ids else None
            )
            exhausted = (
                recognized_rule is None
                or attempt_count >= 1 + envelope.max_retry_attempts
            )
            event: dict[str, object] = {
                "kind": "external-display-artifact-failed",
                "version": _EVENT_VERSION,
                "requestId": request_id,
                "reason": failure.reason,
                "failureDigest": failure.canonical_digest(),
                "failureCount": record.failures + 1,
                "attemptCount": attempt_count,
                "policyDigest": record.policy_digest,
                "retryRuleId": recognized_rule,
                "nextEligibleAt": _wire_time(commit_now),
                "retryExhausted": exhausted,
                **_fence_fields(fence),
                "recordedAt": _wire_time(commit_now),
            }
            event["eventDigest"] = _event_digest(event)
            try:
                self._append_apply(event)
            except JournalSealedError:
                return self._result(request_id, DisplayArtifactVerdict.STORAGE_UNAVAILABLE)
            return self._result(
                request_id,
                (
                    DisplayArtifactVerdict.RETRY_EXHAUSTED
                    if exhausted
                    else DisplayArtifactVerdict.QUEUED
                ),
            )

    def _record(self, request_id: str) -> _Record | None:
        with self._lock:
            return self._records.get(request_id)

    def _result(self, request_id: str, verdict: DisplayArtifactVerdict) -> DisplayArtifactResult:
        record = self._record(request_id)
        return DisplayArtifactResult(
            verdict,
            record.phase if record else DisplayPhase.NOT_REQUIRED,
            record.declaration if record else None,
            record.receipt if record else None,
        )

    def _run_mutation_guard(
        self,
        request_id: str,
        fence: LeaseFence,
        report_digest: str,
        commit: Callable[..., DisplayArtifactResult],
    ) -> DisplayArtifactResult | None:
        """Cross-store mutation gate; storage I/O and presigning never enter it."""
        if self._mutation_guard is None:
            return None
        return self._mutation_guard(request_id, fence, report_digest, commit)

    @staticmethod
    def _matches_declaration(record: _Record, value: SanitizedDisplayDeclarationV1) -> bool:
        return (
            value.declaration_digest is not None
            and value.request_id == record.request_id
            and value.source_subject_digest == record.subject.canonical_digest()
            and value.source_report_digest == record.report_digest
            and value.policy_digest == record.policy_digest
            and value.inspector_build_digest == record.build_digest
        )

    @staticmethod
    def _object_key(declaration: SanitizedDisplayDeclarationV1) -> str:
        assert declaration.declaration_digest is not None
        return (
            "external-sanitized-display/v1/"
            + hashlib.sha256(declaration.declaration_digest.encode("ascii")).hexdigest()
        )

    @staticmethod
    def _display_ref(declaration: SanitizedDisplayDeclarationV1) -> str:
        assert declaration.declaration_digest is not None
        return (
            "sda-v1-"
            + hashlib.sha256(
                (declaration.request_id + "\0" + declaration.declaration_digest).encode("ascii")
            ).hexdigest()
        )

    def _append_apply(self, event: dict[str, object]) -> None:
        self._journal.append(event)
        self._apply(event)

    @staticmethod
    def _require_event(raw: Mapping[str, object], expected: set[str], kind: str) -> None:
        if (
            set(raw) != expected
            or raw.get("kind") != kind
            or type(raw.get("version")) is not int
            or raw["version"] != _EVENT_VERSION
        ):
            raise ValueError("display event fields/version are invalid")
        if raw.get("eventDigest") != _event_digest(raw):
            raise ValueError("display event digest is invalid")

    def _apply(self, raw: Mapping[str, Any]) -> None:
        try:
            kind = raw.get("kind")
            if kind == "external-display-artifact-queued":
                self._apply_queued(raw)
            elif kind == "external-display-artifact-issued":
                self._apply_issued(raw)
            elif kind == "external-display-artifact-sealed":
                self._apply_sealed(raw)
            elif kind == "external-display-artifact-failed":
                self._apply_failed(raw)
            else:
                raise ValueError("unknown display event kind")
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise ExternalDisplayArtifactRecoveryError(f"display event invalid: {exc}") from exc

    def _apply_queued(self, raw: Mapping[str, object]) -> None:
        self._require_event(
            raw,
            {
                "kind",
                "version",
                "eventDigest",
                "requestId",
                "subject",
                "sourceSubjectDigest",
                "sourceReportDigest",
                "policyDigest",
                "inspectorBuildDigest",
                "maxRetryAttempts",
                "maxOutputBytes",
                "queuedAt",
            },
            "external-display-artifact-queued",
        )
        if (
            not isinstance(raw["requestId"], str)
            or raw["requestId"] in self._records
            or not isinstance(raw["subject"], Mapping)
            or type(raw["maxRetryAttempts"]) is not int
            or raw["maxRetryAttempts"] < 1
            or type(raw["maxOutputBytes"]) is not int
            or raw["maxOutputBytes"] < 1
        ):
            raise ValueError("display queue event is malformed")
        subject = SealedExternalSubjectV1.model_validate(raw["subject"])
        request_id = _required_string(raw, "requestId")
        report_digest = _required_string(raw, "sourceReportDigest")
        policy_digest = _required_string(raw, "policyDigest")
        build_digest = _required_string(raw, "inspectorBuildDigest")
        if raw["sourceSubjectDigest"] != subject.canonical_digest() or not all(
            _DIGEST_RE.fullmatch(value) for value in (report_digest, policy_digest, build_digest)
        ):
            raise ValueError("display queue binding invalid")
        _parse_time(raw["queuedAt"], "queuedAt")
        self._records[request_id] = _Record(
            request_id,
            subject,
            report_digest,
            policy_digest,
            build_digest,
            raw["maxRetryAttempts"],
            raw["maxOutputBytes"],
        )

    def _apply_issued(self, raw: Mapping[str, object]) -> None:
        expected = {
            "kind",
            "version",
            "eventDigest",
            "requestId",
            "displayId",
            "sourceSubjectDigest",
            "sourceReportDigest",
            "policyDigest",
            "inspectorBuildDigest",
            "declaredDerivativeSha256",
            "declaredDerivativeSizeBytes",
            "declaredDerivativeContentType",
            "workerInstanceId",
            "leaseAcquisitionId",
            "leaseGeneration",
            "issuedAt",
            "declaration",
        }
        self._require_event(raw, expected, "external-display-artifact-issued")
        record = self._records.get(_required_string(raw, "requestId"))
        if (
            record is None
            or record.declaration is not None
            or record.phase in {DisplayPhase.SEALED, DisplayPhase.RETRY_EXHAUSTED}
        ):
            raise ValueError("display declaration is out of order")
        _fence(raw)
        declaration = SanitizedDisplayDeclarationV1.model_validate(raw["declaration"]).sealed()
        fields = {
            "displayId": declaration.display_id,
            "sourceSubjectDigest": declaration.source_subject_digest,
            "sourceReportDigest": declaration.source_report_digest,
            "policyDigest": declaration.policy_digest,
            "inspectorBuildDigest": declaration.inspector_build_digest,
            "declaredDerivativeSha256": declaration.declared_derivative_sha256,
            "declaredDerivativeSizeBytes": declaration.declared_derivative_size_bytes,
            "declaredDerivativeContentType": declaration.declared_derivative_content_type,
        }
        if not self._matches_declaration(record, declaration) or any(
            raw[key] != value for key, value in fields.items()
        ):
            raise ValueError("display declaration binding invalid")
        _parse_time(raw["issuedAt"], "issuedAt")
        record.declaration, record.phase = declaration, DisplayPhase.RUNNING

    def _apply_sealed(self, raw: Mapping[str, object]) -> None:
        expected = {
            "kind",
            "version",
            "eventDigest",
            "requestId",
            "displayId",
            "declarationDigest",
            "sourceSubjectDigest",
            "sourceReportDigest",
            "policyDigest",
            "inspectorBuildDigest",
            "observedDerivativeSha256",
            "observedDerivativeSizeBytes",
            "observedDerivativeContentType",
            "workerInstanceId",
            "leaseAcquisitionId",
            "leaseGeneration",
            "sealedAt",
            "receipt",
        }
        self._require_event(raw, expected, "external-display-artifact-sealed")
        record = self._records.get(_required_string(raw, "requestId"))
        if (
            record is None
            or record.declaration is None
            or record.receipt is not None
            or record.phase is DisplayPhase.RETRY_EXHAUSTED
        ):
            raise ValueError("display seal is out of order")
        _fence(raw)
        receipt = SanitizedDisplayReceiptV1.model_validate(raw["receipt"]).sealed()
        sealed_at = _parse_time(raw["sealedAt"], "sealedAt")
        duplicated = {
            "displayId": receipt.display_id,
            "declarationDigest": receipt.declaration_digest,
            "sourceSubjectDigest": receipt.source_subject_digest,
            "sourceReportDigest": receipt.source_report_digest,
            "policyDigest": receipt.policy_digest,
            "inspectorBuildDigest": receipt.inspector_build_digest,
            "observedDerivativeSha256": receipt.observed_derivative_sha256,
            "observedDerivativeSizeBytes": receipt.observed_derivative_size_bytes,
            "observedDerivativeContentType": receipt.observed_derivative_content_type,
        }
        if (
            receipt.request_id != record.request_id
            or receipt.declaration_digest != record.declaration.declaration_digest
            or receipt.source_subject_digest != record.subject.canonical_digest()
            or receipt.source_report_digest != record.report_digest
            or receipt.policy_digest != record.policy_digest
            or receipt.inspector_build_digest != record.build_digest
            or receipt.observed_derivative_sha256
            != record.declaration.declared_derivative_sha256
            or receipt.observed_derivative_size_bytes
            != record.declaration.declared_derivative_size_bytes
            or receipt.observed_derivative_content_type
            != record.declaration.declared_derivative_content_type
            or receipt.sealed_at != sealed_at
            or any(raw[key] != value for key, value in duplicated.items())
        ):
            raise ValueError("display receipt binding invalid")
        record.receipt, record.phase = receipt, DisplayPhase.SEALED

    def _apply_failed(self, raw: Mapping[str, object]) -> None:
        expected = {
            "kind",
            "version",
            "eventDigest",
            "requestId",
            "reason",
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
        }
        self._require_event(raw, expected, "external-display-artifact-failed")
        record = self._records.get(_required_string(raw, "requestId"))
        if record is None or record.phase in {DisplayPhase.SEALED, DisplayPhase.RETRY_EXHAUSTED}:
            raise ValueError("display failure out of order")
        fence = _fence(raw)
        failure = ExternalInspectionFailureV1(_required_string(raw, "reason"))
        policy = self._policy_registry.resolve(record.policy_digest).policy
        if (
            policy is None
            or policy.resource_envelope is None
            or type(raw["failureCount"]) is not int
            or raw["failureCount"] != record.failures + 1
            or type(raw["attemptCount"]) is not int
            or raw["attemptCount"] < 1
            or raw["attemptCount"] > 1 + policy.resource_envelope.max_retry_attempts
            or raw["policyDigest"] != record.policy_digest
            or raw["failureDigest"] != failure.canonical_digest()
            or (
                raw["retryRuleId"] is not None
                and not isinstance(raw["retryRuleId"], str)
            )
            or raw["nextEligibleAt"] != raw["recordedAt"]
            or type(raw["retryExhausted"]) is not bool
            or raw["retryExhausted"]
            != (
                failure.retry_rule_id != raw["retryRuleId"]
                or raw["retryRuleId"] not in policy.inspection_rule_ids
                or raw["attemptCount"] >= 1 + policy.resource_envelope.max_retry_attempts
            )
        ):
            raise ValueError("display failure binding invalid")
        _parse_time(raw["recordedAt"], "recordedAt")
        _parse_time(raw["nextEligibleAt"], "nextEligibleAt")
        record.failures = raw["failureCount"]
        record.last_failure_fence, record.last_failure_reason = fence, failure.reason
        record.phase = (
            DisplayPhase.RETRY_EXHAUSTED if raw["retryExhausted"] else DisplayPhase.QUEUED
        )


__all__ = [
    "DisplayArtifactResult",
    "DisplayArtifactVerdict",
    "DisplayPhase",
    "ExternalDisplayArtifactRecoveryError",
    "ExternalDisplayArtifactStore",
    "SanitizedDisplayGrant",
]
