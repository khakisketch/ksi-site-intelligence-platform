"""Surface-profile jobs: frozen admission, lease/fence, verified completion, scoped release.

A profile job reads the heights of one DSM along one *saved* line revision.  This store owns only
the state machine and the checks that make a worker's answer trustworthy; the facts it needs about
the outside world (scope, source, grant, the HEIGHT verdict, worker activation) come through
:class:`SurfaceProfileAuthorityPort`, so each is re-proved on every transition, not remembered.

## What is proved, and where

- **Admission** freezes the saved line, the exact source facts, the grant, the digests of the data
  and profile policies, the runtime and the one native pixel window a worker may read.
- **Every transition** re-proves current authority.  A frozen job is evidence of what was admitted,
  never a credential: a revoked grant or withdrawn HEIGHT verdict stops the job *and* the release.
- **Completion** is not taken on the worker's word.  Core recomputes the sample plan (pure, no
  raster read), recomputes which samples geometry alone makes unknown, and refuses a result whose
  positions, count, CRS, source bytes, read window, size or receipt differ from the frozen job.  A
  worker can still misread pixels — that is what the independent reference check is for — but it
  cannot invent another line or asset, a wider window, or a number where geometry says "outside".
- **Release** of the numbers is a separate READ proof; metadata and the receipt are visible earlier.

Nothing here reads a GeoTIFF, issues a storage URL or computes a height.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Annotated, Literal, Protocol, Self

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts._spatial_data import (
    PositiveInt,
    SpatialDataModel,
    UtcTimestamp,
    require_utc,
)
from ksi_event_contracts.measurement_feature import MeasurementFeatureRevisionV1
from ksi_event_contracts.spatial_data import (
    SpatialDataAvailabilityV1,
    SpatialDataExecutionStateV1,
    SpatialDataSourceV1,
)
from ksi_event_contracts.spatial_data_authority import SpatialDataGrantV1
from ksi_event_contracts.surface_profile import CreateSurfaceProfileV1, SurfaceProfileResultV1
from ksi_event_contracts.surface_profile_job import (
    TRANSIENT_JOB_REASONS,
    CreateSurfaceProfileJobV1,
    SurfaceProfileAttemptV1,
    SurfaceProfileFrozenJobV1,
    SurfaceProfileJobId,
    SurfaceProfileJobReasonV1,
    SurfaceProfileJobViewV1,
    SurfaceProfileLeaseRequestV1,
    SurfaceProfilePolicyV1,
    SurfaceProfileReadWindowV1,
    SurfaceProfileReceiptV1,
    SurfaceProfileResultViewV1,
    SurfaceProfileRuntimeV1,
    SurfaceProfileVerticalReferenceV1,
)
from ksi_geo_spatial.crs import normalise_crs
from ksi_geo_spatial.surface_profile import (
    SampleInvalidReason,
    SurfaceProfileError,
    SurfaceProfilePolicy,
    locate_profile_samples,
    plan_surface_profile,
)
from pydantic import Field, TypeAdapter, ValidationError, model_validator

from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.foundation.durable_journal import DurableJournal, JournalSealedError
from ksi_core.identity.auth import Permission, Principal, PrincipalKind, principal_permissions

_FEATURE_ID_RE = re.compile(r"^mf-[0-9a-f]{32}$")
_ASSET_REF_RE = re.compile(r"^ksa-v1-[0-9a-f]{64}$")
ACTIVE_STATES = frozenset({"QUEUED", "RUNNING"})
_EXECUTION_GROUP_STATES = {"ACTIVE": ACTIVE_STATES, "COMPLETED": frozenset({"COMPLETED"})}
_REASON: TypeAdapter[SurfaceProfileJobReasonV1] = TypeAdapter(SurfaceProfileJobReasonV1)


class SurfaceProfileDomainError(RuntimeError):
    """A refusal that is safe to show: a closed reason and a status, never a path or foreign id."""

    def __init__(self, reason: str, status_code: int, retryable: bool = False) -> None:
        self.reason: SurfaceProfileJobReasonV1 = _REASON.validate_python(reason)
        if type(status_code) is not int or not 400 <= status_code <= 599:
            raise ValueError("invalid failure status")
        self.status_code = status_code
        self.retryable = bool(retryable)
        super().__init__(self.reason)


class SurfaceProfileJobRecoveryError(RuntimeError):
    """The journal cannot be replayed; the store refuses to start rather than guess."""


@dataclass(frozen=True, slots=True)
class SurfaceProfileAdmission:
    """What the authority proved at admission, each part sealed and bound to the request."""

    feature: MeasurementFeatureRevisionV1
    source: SpatialDataSourceV1
    grant: SpatialDataGrantV1
    data_policy_digest: str
    height_decision_digest: str
    vertical_reference: SurfaceProfileVerticalReferenceV1
    read_window: SurfaceProfileReadWindowV1 | None


class SurfaceProfileAuthorityPort(Protocol):
    """Everything the store needs from the rest of Core, re-asked on each use."""

    coordinator: ExternalAuthorityCurrentnessCoordinator

    def require_scope(self, site_id: str, work_area_id: str, principal: Principal) -> None: ...

    def admit(
        self,
        *,
        site_id: str,
        work_area_id: str,
        request: CreateSurfaceProfileJobV1,
        principal: Principal,
        policy: SurfaceProfilePolicyV1,
        now: datetime,
    ) -> SurfaceProfileAdmission: ...

    def reprove(
        self,
        job: SurfaceProfileFrozenJobV1,
        *,
        operation: Literal["PREPARE", "READ"],
        now: datetime,
    ) -> None:
        """Raise :class:`SurfaceProfileDomainError` unless the requester may still do this."""
        ...

    def worker_is_activated(self, worker: Principal, instance_id: str, now: datetime) -> bool: ...


# ── events and projection ────────────────────────────────────────────────
class _Event(SpatialDataModel):
    job_id: SurfaceProfileJobId
    sequence: PositiveInt
    at: UtcTimestamp


class JobIssued(_Event):
    record_type: Literal["surface-profile-job.issued.v1"] = "surface-profile-job.issued.v1"
    job: SurfaceProfileFrozenJobV1

    @model_validator(mode="after")
    def _sealed(self) -> Self:
        if self.sequence != 1 or self.job_id != self.job.job_id or self.at != self.job.created_at:
            raise ValueError("issuance identity/time/sequence mismatch")
        if self.job.job_digest != self.job.canonical_digest():
            raise ValueError("job snapshot must be sealed")
        return self


class JobLeased(_Event):
    record_type: Literal["surface-profile-job.leased.v1"] = "surface-profile-job.leased.v1"
    attempt: SurfaceProfileAttemptV1


class JobRenewed(_Event):
    record_type: Literal["surface-profile-job.renewed.v1"] = "surface-profile-job.renewed.v1"
    attempt: SurfaceProfileAttemptV1


class JobStateChanged(_Event):
    record_type: Literal["surface-profile-job.state.v1"] = "surface-profile-job.state.v1"
    state: Literal["QUEUED", "FAILED", "CANCELED", "EXPIRED"]
    reason: SurfaceProfileJobReasonV1
    next_available_at: UtcTimestamp | None = None
    attempt: SurfaceProfileAttemptV1 | None = None


class JobCompleted(_Event):
    record_type: Literal["surface-profile-job.completed.v1"] = "surface-profile-job.completed.v1"
    attempt: SurfaceProfileAttemptV1
    result: SurfaceProfileResultV1
    receipt: SurfaceProfileReceiptV1


JobEvent = Annotated[
    JobIssued | JobLeased | JobRenewed | JobStateChanged | JobCompleted,
    Field(discriminator="record_type"),
]
JOB_EVENT: TypeAdapter[JobEvent] = TypeAdapter(JobEvent)


@dataclass(frozen=True, slots=True)
class JobRecord:
    job: SurfaceProfileFrozenJobV1
    sequence: int
    state: Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELED", "EXPIRED"]
    attempts: int = 0
    attempt: SurfaceProfileAttemptV1 | None = None
    reason: SurfaceProfileJobReasonV1 | None = None
    next_available_at: datetime | None = None
    completed_at: datetime | None = None
    result: SurfaceProfileResultV1 | None = None
    receipt: SurfaceProfileReceiptV1 | None = None


@dataclass(frozen=True, slots=True)
class SurfaceProfileComparisonInput:
    """Immutable completed input released after a fresh scoped READ proof."""

    job: SurfaceProfileFrozenJobV1
    result: SurfaceProfileResultV1
    receipt: SurfaceProfileReceiptV1


def _same_acquisition(a: SurfaceProfileAttemptV1, b: SurfaceProfileAttemptV1) -> bool:
    return a.fence_digest() == b.fence_digest()


def transition(record: JobRecord | None, event: JobEvent) -> JobRecord:
    """Pure, strict state machine: an impossible event is a corrupt history, not a no-op."""
    if isinstance(event, JobIssued):
        if record is not None:
            raise ValueError("job already issued")
        return JobRecord(event.job, 1, "QUEUED")
    if record is None or event.sequence != record.sequence + 1 or event.job_id != record.job.job_id:
        raise ValueError("event does not extend this job's history")
    job = record.job
    if isinstance(event, JobLeased):
        attempt = event.attempt
        if (
            record.state != "QUEUED"
            or attempt.job_id != job.job_id
            or attempt.frozen_job_digest != job.job_digest
            or attempt.attempt_number != record.attempts + 1
            or attempt.fence != attempt.attempt_number
            or attempt.attempt_number > job.policy.max_attempts
            or attempt.acquired_at != event.at
            or attempt.lease_until > job.deadline
        ):
            raise ValueError("invalid lease")
        return replace(
            record,
            sequence=event.sequence,
            state="RUNNING",
            attempts=attempt.attempt_number,
            attempt=attempt,
            next_available_at=None,
        )
    if isinstance(event, JobRenewed):
        held = record.attempt
        if (
            record.state != "RUNNING"
            or held is None
            or not _same_acquisition(event.attempt, held)
            or event.attempt.lease_until <= held.lease_until
            or event.attempt.lease_until > job.deadline
        ):
            raise ValueError("invalid renewal")
        return replace(record, sequence=event.sequence, attempt=event.attempt)
    if isinstance(event, JobStateChanged):
        if record.state not in ACTIVE_STATES:
            raise ValueError("a finished job cannot change state")
        if event.state == "QUEUED" and (
            event.next_available_at is None or record.attempts >= job.policy.max_attempts
        ):
            raise ValueError("a retry needs a backoff and an attempt left")
        return replace(
            record,
            sequence=event.sequence,
            state=event.state,
            attempt=None if event.state == "QUEUED" else record.attempt,
            reason=event.reason if event.state != "QUEUED" else None,
            next_available_at=event.next_available_at if event.state == "QUEUED" else None,
        )
    held = record.attempt
    if (
        record.state != "RUNNING"
        or held is None
        or event.attempt != held
        or not held.acquired_at <= event.at < held.lease_until
        or event.at >= job.deadline
    ):
        raise ValueError("completion needs the exact live attempt")
    return replace(
        record,
        sequence=event.sequence,
        state="COMPLETED",
        completed_at=event.at,
        result=event.result,
        receipt=event.receipt,
    )


def _hash(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


class SurfaceProfileJobStore:
    def __init__(
        self,
        journal: DurableJournal,
        *,
        authority: SurfaceProfileAuthorityPort,
        policy: SurfaceProfilePolicyV1,
        runtime: SurfaceProfileRuntimeV1,
        coordinator: ExternalAuthorityCurrentnessCoordinator,
    ) -> None:
        if authority.coordinator is not coordinator:
            raise ValueError("profile jobs need the authority to share the Core coordinator")
        for snapshot in (policy, runtime):
            sealed = type(snapshot).model_validate(snapshot.model_dump())
            if getattr(sealed, sealed._digest_field) != sealed.canonical_digest():
                raise ValueError("profile jobs require sealed explicit policy/runtime")
        self._journal = journal
        self._authority = authority
        self._policy = policy.model_copy(deep=True)
        self._runtime = runtime.model_copy(deep=True)
        self._coordinator = coordinator
        self._lock = threading.RLock()
        self._records: dict[str, JobRecord] = {}
        self._idempotency: dict[tuple[str, str, str, str, str], str] = {}
        self._by_scope: dict[tuple[str, str, str], list[str]] = {}
        try:
            for raw in journal.replay():
                event = JOB_EVENT.validate_python(raw)
                record = transition(self._records.get(event.job_id), event)
                if isinstance(event, JobIssued):
                    self._check_new(record)
                elif isinstance(event, JobCompleted):
                    self._verify_completion(
                        record.job, event.attempt, event.result, event.receipt, event.at
                    )
                self._project(record)
        except Exception as exc:
            journal.close()
            raise SurfaceProfileJobRecoveryError("invalid surface-profile job history") from exc

    # ── internals ────────────────────────────────────────────────────────
    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def uses_exact_authority(self, *, authority: SurfaceProfileAuthorityPort) -> bool:
        return self._authority is authority and authority.coordinator is self._coordinator

    def require_requester_scope(
        self, *, site_id: str, work_area_id: str, principal: Principal, permission: Permission
    ) -> None:
        self._require_requester(principal, permission)
        self._authority.require_scope(site_id, work_area_id, principal)

    @property
    def sealed_reason(self) -> str | None:
        return self._journal.sealed_reason

    @property
    def policy(self) -> SurfaceProfilePolicyV1:
        return self._policy.model_copy(deep=True)

    @contextmanager
    def _guard(self, now: datetime) -> Iterator[None]:
        require_utc(now)
        with self._coordinator.guarded_read(), self._lock:
            yield

    def _ensure_open(self) -> None:
        if self.sealed_reason is not None:
            raise SurfaceProfileDomainError("CURRENTNESS_UNAVAILABLE", 503)

    @staticmethod
    def _key(job: SurfaceProfileFrozenJobV1) -> tuple[str, str, str, str, str]:
        return (
            job.organization_id,
            job.requester_principal_id,
            job.site_id,
            job.work_area_id,
            job.idempotency_key_hash,
        )

    def _check_new(self, record: JobRecord) -> None:
        job = record.job
        if job.job_id in self._records or self._key(job) in self._idempotency:
            raise ValueError("duplicate issuance")
        if job.policy != self._policy or job.runtime != self._runtime:
            raise ValueError("job was frozen under another policy/runtime")

    def _project(self, record: JobRecord) -> None:
        job = record.job
        if job.job_id not in self._records:
            self._idempotency[self._key(job)] = job.job_id
            self._by_scope.setdefault(
                (job.organization_id, job.site_id, job.work_area_id), []
            ).append(job.job_id)
        self._records[job.job_id] = record

    def _append(self, event: JobEvent) -> JobRecord:
        self._ensure_open()
        event = JOB_EVENT.validate_python(event.model_dump())
        record = transition(self._records.get(event.job_id), event)
        if isinstance(event, JobIssued):
            self._check_new(record)
        try:
            self._journal.append(event.model_dump(by_alias=True, mode="json"))
        except JournalSealedError as exc:
            raise SurfaceProfileDomainError("CURRENTNESS_UNAVAILABLE", 503) from exc
        self._project(record)
        return record

    def _active_count(self, organization_id: str) -> int:
        return sum(
            1
            for record in self._records.values()
            if record.job.organization_id == organization_id and record.state in ACTIVE_STATES
        )

    def _queued_count(self) -> int:
        return sum(1 for record in self._records.values() if record.state == "QUEUED")

    def _requester_record(
        self, job_id: str, principal: Principal, expected_scope: tuple[str, str] | None = None
    ) -> JobRecord:
        record = self._records.get(job_id)
        if (
            record is None
            or record.job.organization_id != principal.organization_id
            or record.job.requester_principal_id != principal.principal_id
        ):
            raise SurfaceProfileDomainError("NOT_FOUND", 404)
        if (
            expected_scope is not None
            and (record.job.site_id, record.job.work_area_id) != expected_scope
        ):
            raise SurfaceProfileDomainError("NOT_FOUND", 404)
        return record

    def _expire(self, record: JobRecord, now: datetime) -> JobRecord:
        if record.state in ACTIVE_STATES and now >= record.job.deadline:
            return self._append(
                JobStateChanged(
                    job_id=record.job.job_id,
                    sequence=record.sequence + 1,
                    at=now,
                    state="EXPIRED",
                    reason="DEADLINE_EXCEEDED",
                    attempt=record.attempt,
                )
            )
        return record

    def _reclaim(self, record: JobRecord, now: datetime) -> JobRecord:
        """An expired lease requeues the job, or ends it when no attempt is left."""
        attempt = record.attempt
        if record.state != "RUNNING" or attempt is None or now < attempt.lease_until:
            return record
        job = record.job
        retry_at = now + timedelta(seconds=job.policy.min_retry_backoff_seconds)
        retry = record.attempts < job.policy.max_attempts and retry_at < job.deadline
        return self._append(
            JobStateChanged(
                job_id=job.job_id,
                sequence=record.sequence + 1,
                at=now,
                state="QUEUED" if retry else "FAILED",
                reason="LEASE_EXPIRED",
                next_available_at=retry_at if retry else None,
                attempt=attempt,
            )
        )

    def _fresh(self, record: JobRecord, now: datetime) -> JobRecord:
        return self._reclaim(self._expire(record, now), now)

    def _view(self, record: JobRecord, now: datetime) -> SurfaceProfileJobViewV1:
        job = record.job
        state = SpatialDataExecutionStateV1(record.state)
        reason = record.reason
        if record.state in ACTIVE_STATES:
            availability = SpatialDataAvailabilityV1.NOT_READY
        elif record.state == "COMPLETED":
            assert record.completed_at is not None
            if now >= record.completed_at + timedelta(seconds=job.policy.retention_seconds):
                availability = SpatialDataAvailabilityV1.RETENTION_EXPIRED
                reason = "RETENTION_EXPIRED"
            else:
                availability = SpatialDataAvailabilityV1.AVAILABLE
                try:
                    self._authority.reprove(job, operation="READ", now=now)
                except SurfaceProfileDomainError as error:
                    reason = error.reason
                    availability = {
                        "ACCESS_REVOKED": SpatialDataAvailabilityV1.ACCESS_REVOKED,
                        "ACCESS_EXPIRED": SpatialDataAvailabilityV1.ACCESS_EXPIRED,
                    }.get(error.reason, SpatialDataAvailabilityV1.UNAVAILABLE)
        else:
            availability = SpatialDataAvailabilityV1.UNAVAILABLE
        return SurfaceProfileJobViewV1(
            job_id=job.job_id,
            asset_ref=job.request.asset_ref,
            site_id=job.site_id,
            work_area_id=job.work_area_id,
            feature=job.request.feature,
            created_at=job.created_at,
            execution_state=state,
            availability=availability,
            reason=reason,
            receipt=record.receipt if record.state == "COMPLETED" else None,
        )

    # ── requester ────────────────────────────────────────────────────────
    @staticmethod
    def _require_requester(principal: Principal, permission: Permission) -> None:
        if (
            principal.kind not in (PrincipalKind.OPERATOR, PrincipalKind.SPATIAL_DATA_CLIENT)
            or principal.device_id is not None
            or permission not in principal_permissions(principal)
        ):
            # AI identities stay out until the AI egress/audit path covers this lane.
            raise SurfaceProfileDomainError("PERMISSION_DENIED", 403)

    def issue(
        self,
        *,
        site_id: str,
        work_area_id: str,
        request: CreateSurfaceProfileJobV1,
        principal: Principal,
        idempotency_key: str,
        now: datetime,
    ) -> SurfaceProfileJobViewV1:
        require_utc(now)
        self._require_requester(principal, Permission.SPATIAL_DATA_REQUEST)
        self._authority.require_scope(site_id, work_area_id, principal)
        request = CreateSurfaceProfileJobV1.model_validate(request.model_dump())
        if (
            type(idempotency_key) is not str
            or not idempotency_key
            or len(idempotency_key.encode()) > self._policy.max_idempotency_key_bytes
            or any(ord(c) < 32 or ord(c) == 127 for c in idempotency_key)
        ):
            raise SurfaceProfileDomainError("INVALID_REQUEST", 422)
        key_hash = _hash(idempotency_key.encode())
        key = (principal.organization_id, principal.principal_id, site_id, work_area_id, key_hash)
        fingerprint = request.canonical_digest()
        with self._guard(now):
            existing = self._idempotency.get(key)
            if existing is not None:
                return self._existing(existing, fingerprint, principal, now)
            self._ensure_open()
            self._lane(principal.organization_id)
        # The authority may consult remote policy: never inside the guarded commit.
        admission = self._authority.admit(
            site_id=site_id,
            work_area_id=work_area_id,
            request=request,
            principal=principal,
            policy=self._policy,
            now=now,
        )
        with self._guard(now):
            existing = self._idempotency.get(key)
            if existing is not None:
                return self._existing(existing, fingerprint, principal, now)
            self._ensure_open()
            self._lane(principal.organization_id)
            job_id = (
                "spj-"
                + _hash(
                    canonical_json_bytes({"scope": list(key), "fingerprint": fingerprint})
                ).removeprefix("sha256:")[:32]
            )
            try:
                job = SurfaceProfileFrozenJobV1(
                    job_id=job_id,
                    organization_id=principal.organization_id,
                    requester_principal_id=principal.principal_id,
                    site_id=site_id,
                    work_area_id=work_area_id,
                    request=request,
                    feature=admission.feature,
                    profile_request=CreateSurfaceProfileV1(
                        asset_ref=request.asset_ref,
                        line=admission.feature.line,
                        feature=admission.feature.ref(),
                        sample_spacing_m=request.sample_spacing_m,
                    ),
                    source=admission.source,
                    grant=admission.grant,
                    data_policy_digest=admission.data_policy_digest,
                    height_decision_digest=admission.height_decision_digest,
                    vertical_reference=admission.vertical_reference,
                    policy=self._policy,
                    runtime=self._runtime,
                    read_window=admission.read_window,
                    idempotency_key_hash=key_hash,
                    request_fingerprint=fingerprint,
                    created_at=now,
                    deadline=now + timedelta(seconds=self._policy.deadline_seconds),
                ).sealed()
            except ValidationError as exc:
                raise SurfaceProfileDomainError("INVALID_REQUEST", 422) from exc
            record = self._append(
                JobIssued(job_id=job.job_id, sequence=1, at=job.created_at, job=job)
            )
            return self._view(record, now)

    def _lane(self, organization_id: str) -> None:
        if self._active_count(organization_id) >= self._policy.max_active_jobs_per_organization:
            raise SurfaceProfileDomainError("RESOURCE_LIMIT_EXCEEDED", 429, retryable=True)
        if self._queued_count() >= self._policy.max_pending_records:
            raise SurfaceProfileDomainError("RESOURCE_LIMIT_EXCEEDED", 429, retryable=True)

    def _existing(
        self, job_id: str, fingerprint: str, principal: Principal, now: datetime
    ) -> SurfaceProfileJobViewV1:
        record = self._requester_record(job_id, principal)
        if record.job.request_fingerprint != fingerprint:
            raise SurfaceProfileDomainError("IDEMPOTENCY_CONFLICT", 409)
        return self._view(self._fresh(record, now), now)

    def get(
        self,
        *,
        job_id: str,
        principal: Principal,
        now: datetime,
        expected_scope: tuple[str, str] | None = None,
    ) -> SurfaceProfileJobViewV1:
        self._require_requester(principal, Permission.SPATIAL_DATA_READ)
        with self._guard(now):
            record = self._requester_record(job_id, principal, expected_scope)
            self._authority.require_scope(record.job.site_id, record.job.work_area_id, principal)
            return self._view(self._fresh(record, now), now)

    def list(
        self,
        *,
        site_id: str,
        work_area_id: str,
        principal: Principal,
        limit: int,
        now: datetime,
        feature_id: str | None = None,
        asset_ref: str | None = None,
        feature_revision: int | None = None,
        execution_group: str | None = None,
    ) -> tuple[SurfaceProfileJobViewV1, ...]:
        """Return this requester's newest matching jobs, applying all filters before the limit."""
        self._require_requester(principal, Permission.SPATIAL_DATA_READ)
        self._authority.require_scope(site_id, work_area_id, principal)
        if type(limit) is not int or not 1 <= limit <= self._policy.max_list_records:
            raise SurfaceProfileDomainError("INVALID_REQUEST", 422)
        if feature_id is not None and (
            type(feature_id) is not str or _FEATURE_ID_RE.fullmatch(feature_id) is None
        ):
            raise SurfaceProfileDomainError("INVALID_REQUEST", 422)
        if asset_ref is not None and (
            type(asset_ref) is not str or _ASSET_REF_RE.fullmatch(asset_ref) is None
        ):
            raise SurfaceProfileDomainError("INVALID_REQUEST", 422)
        if feature_revision is not None and (
            type(feature_revision) is not int or not 1 <= feature_revision <= 2**31 - 1
        ):
            raise SurfaceProfileDomainError("INVALID_REQUEST", 422)
        if feature_revision is not None and feature_id is None:
            raise SurfaceProfileDomainError("INVALID_REQUEST", 422)
        states = None
        if execution_group is not None:
            if type(execution_group) is not str or execution_group not in _EXECUTION_GROUP_STATES:
                raise SurfaceProfileDomainError("INVALID_REQUEST", 422)
            states = _EXECUTION_GROUP_STATES[execution_group]
        with self._guard(now):
            ids = self._by_scope.get((principal.organization_id, site_id, work_area_id), [])
            matching = []
            for job_id in reversed(ids):
                record = self._records[job_id]
                job = record.job
                if (
                    job.requester_principal_id != principal.principal_id
                    or (feature_id is not None and job.feature.feature_id != feature_id)
                    or (asset_ref is not None and job.request.asset_ref != asset_ref)
                    or (feature_revision is not None and job.feature.revision != feature_revision)
                    or (states is not None and record.state not in states)
                ):
                    continue
                current = self._fresh(record, now)
                if states is not None and current.state not in states:
                    continue
                matching.append(self._view(current, now))
                if len(matching) == limit:
                    break
            return tuple(matching)

    def result(
        self,
        *,
        job_id: str,
        principal: Principal,
        now: datetime,
        expected_scope: tuple[str, str] | None = None,
    ) -> SurfaceProfileResultViewV1:
        """The numbers.  A fresh READ proof is required every time; nothing is cached."""
        self._require_requester(principal, Permission.SPATIAL_DATA_READ)
        with self._guard(now):
            record = self._requester_record(job_id, principal, expected_scope)
            self._authority.require_scope(record.job.site_id, record.job.work_area_id, principal)
            record = self._fresh(record, now)
            if record.state != "COMPLETED" or record.result is None:
                raise SurfaceProfileDomainError("NOT_READY", 409)
            assert record.completed_at is not None
            if now >= record.completed_at + timedelta(seconds=record.job.policy.retention_seconds):
                raise SurfaceProfileDomainError("RETENTION_EXPIRED", 410)
            self._authority.reprove(record.job, operation="READ", now=now)
            return SurfaceProfileResultViewV1(job=self._view(record, now), result=record.result)

    def comparison_input(
        self,
        *,
        job_id: str,
        principal: Principal,
        now: datetime,
        expected_scope: tuple[str, str],
    ) -> SurfaceProfileComparisonInput:
        """Release one frozen job, result and receipt under the existing READ boundary."""
        self._require_requester(principal, Permission.SPATIAL_DATA_READ)
        with self._guard(now):
            return self._comparison_input_locked(
                job_id=job_id,
                principal=principal,
                now=now,
                expected_scope=expected_scope,
            )

    @contextmanager
    def comparison_release(
        self,
        *,
        baseline_job_id: str,
        current_job_id: str,
        principal: Principal,
        now: datetime,
        expected_scope: tuple[str, str],
    ) -> Iterator[tuple[SurfaceProfileComparisonInput, SurfaceProfileComparisonInput]]:
        """Hold both READ proofs and the shared authority coordinator through numeric release."""
        self._require_requester(principal, Permission.SPATIAL_DATA_READ)
        with self._guard(now):
            baseline = self._comparison_input_locked(
                job_id=baseline_job_id,
                principal=principal,
                now=now,
                expected_scope=expected_scope,
            )
            current = self._comparison_input_locked(
                job_id=current_job_id,
                principal=principal,
                now=now,
                expected_scope=expected_scope,
            )
            yield baseline, current

    def _comparison_input_locked(
        self,
        *,
        job_id: str,
        principal: Principal,
        now: datetime,
        expected_scope: tuple[str, str],
    ) -> SurfaceProfileComparisonInput:
        record = self._requester_record(job_id, principal, expected_scope)
        self._authority.require_scope(record.job.site_id, record.job.work_area_id, principal)
        record = self._fresh(record, now)
        if record.state != "COMPLETED" or record.result is None or record.receipt is None:
            raise SurfaceProfileDomainError("NOT_READY", 409)
        assert record.completed_at is not None
        if now >= record.completed_at + timedelta(seconds=record.job.policy.retention_seconds):
            raise SurfaceProfileDomainError("RETENTION_EXPIRED", 410)
        self._authority.reprove(record.job, operation="READ", now=now)
        result, receipt, job = record.result, record.receipt, record.job
        measurements = job.source.inspection.measurements
        if (
            result.result_digest is None
            or result.result_digest != result.canonical_digest()
            or receipt.receipt_digest is None
            or receipt.receipt_digest != receipt.canonical_digest()
            or receipt.result_digest != result.result_digest
            or receipt.job_id != job.job_id
            or receipt.job_digest != job.job_digest
            or receipt.artifact_id != job.source.artifact_id
            or receipt.source_digest != job.source.source_digest
            or receipt.source_sha256 != job.source.observed_sha256
            or receipt.source_size_bytes != job.source.observed_size_bytes
            or measurements is None
            or receipt.observed_crs_identifier != measurements.observed_crs_identifier
            or receipt.observed_crs_digest != measurements.observed_crs_digest
            or receipt.vertical_reference != job.vertical_reference
        ):
            raise SurfaceProfileDomainError("INTEGRITY_MISMATCH", 409)
        return SurfaceProfileComparisonInput(job=job, result=result, receipt=receipt)

    def cancel(
        self,
        *,
        job_id: str,
        principal: Principal,
        now: datetime,
        expected_scope: tuple[str, str] | None = None,
    ) -> SurfaceProfileJobViewV1:
        self._require_requester(principal, Permission.SPATIAL_DATA_REQUEST)
        with self._guard(now):
            record = self._requester_record(job_id, principal, expected_scope)
            self._authority.require_scope(record.job.site_id, record.job.work_area_id, principal)
            record = self._fresh(record, now)
            if record.state in ACTIVE_STATES:
                record = self._append(
                    JobStateChanged(
                        job_id=job_id,
                        sequence=record.sequence + 1,
                        at=now,
                        state="CANCELED",
                        reason="CANCELED_BY_REQUESTER",
                        attempt=record.attempt,
                    )
                )
            return self._view(record, now)

    # ── worker ───────────────────────────────────────────────────────────
    def _worker(self, worker: Principal, instance_id: str | None, now: datetime) -> None:
        if (
            worker.kind is not PrincipalKind.SPATIAL_DATA_WORKER
            or Permission.SPATIAL_DATA_WORK not in principal_permissions(worker)
        ):
            raise SurfaceProfileDomainError("PERMISSION_DENIED", 403)
        if instance_id is not None and not self._authority.worker_is_activated(
            worker, instance_id, now
        ):
            raise SurfaceProfileDomainError("PERMISSION_DENIED", 403)

    def _worker_attempt(
        self, worker: Principal, attempt: SurfaceProfileAttemptV1, now: datetime
    ) -> None:
        self._worker(worker, attempt.worker_instance_id, now)
        if attempt.worker_principal_id != worker.principal_id:
            raise SurfaceProfileDomainError("FENCE_CONFLICT", 409)

    def require_worker(self, *, worker: Principal, instance_id: str, now: datetime) -> None:
        with self._guard(now):
            self._worker(worker, instance_id, now)

    def _worker_record(self, job_id: str, worker: Principal) -> JobRecord:
        record = self._records.get(job_id)
        if record is None or record.job.organization_id != worker.organization_id:
            raise SurfaceProfileDomainError("NOT_FOUND", 404)
        return record

    @staticmethod
    def _live(record: JobRecord, attempt: SurfaceProfileAttemptV1, now: datetime) -> None:
        held = record.attempt
        if record.state != "RUNNING" or held is None or attempt != held:
            raise SurfaceProfileDomainError("FENCE_CONFLICT", 409)
        if now >= held.lease_until:
            raise SurfaceProfileDomainError("LEASE_EXPIRED", 409)

    def pending(
        self, *, worker: Principal, instance_id: str, limit: int, now: datetime
    ) -> tuple[SurfaceProfileFrozenJobV1, ...]:
        self._worker(worker, instance_id, now)
        if type(limit) is not int or not 1 <= limit <= self._policy.max_list_records:
            raise SurfaceProfileDomainError("INVALID_REQUEST", 422)
        with self._guard(now):
            found: list[SurfaceProfileFrozenJobV1] = []
            for record in list(self._records.values()):
                if record.job.organization_id != worker.organization_id:
                    continue
                record = self._fresh(record, now)
                if record.state == "QUEUED" and (
                    record.next_available_at is None or now >= record.next_available_at
                ):
                    found.append(record.job)
                if len(found) >= limit:
                    break
            return tuple(found)

    def lease(
        self,
        *,
        job_id: str,
        worker: Principal,
        request: SurfaceProfileLeaseRequestV1,
        now: datetime,
    ) -> SurfaceProfileAttemptV1:
        self._worker(worker, request.worker_instance_id, now)
        acquisition = _hash(request.acquisition_id.encode())
        with self._guard(now):
            record = self._fresh(self._worker_record(job_id, worker), now)
            held = record.attempt
            if (
                record.state == "RUNNING"
                and held is not None
                and held.acquisition_key_hash == acquisition
                and held.worker_instance_id == request.worker_instance_id
                and held.worker_principal_id == worker.principal_id
            ):
                return held.model_copy(deep=True)  # the same acquisition, retried
            if record.state != "QUEUED" or (
                record.next_available_at is not None and now < record.next_available_at
            ):
                raise SurfaceProfileDomainError("NOT_READY", 409)
            self._authority.reprove(record.job, operation="PREPARE", now=now)
            number = record.attempts + 1
            lease_until = min(
                now + timedelta(seconds=record.job.policy.lease_seconds), record.job.deadline
            )
            attempt = SurfaceProfileAttemptV1(
                job_id=job_id,
                frozen_job_digest=record.job.job_digest or "",
                attempt_number=number,
                fence=number,
                worker_principal_id=worker.principal_id,
                worker_instance_id=request.worker_instance_id,
                acquisition_key_hash=acquisition,
                acquired_at=now,
                lease_until=lease_until,
            ).sealed()
            record = self._append(
                JobLeased(job_id=job_id, sequence=record.sequence + 1, at=now, attempt=attempt)
            )
            assert record.attempt is not None
            return record.attempt.model_copy(deep=True)

    def renew(
        self, *, job_id: str, worker: Principal, attempt: SurfaceProfileAttemptV1, now: datetime
    ) -> SurfaceProfileAttemptV1:
        self._worker_attempt(worker, attempt, now)
        with self._guard(now):
            record = self._worker_record(job_id, worker)
            self._live(record, attempt, now)
            self._authority.reprove(record.job, operation="PREPARE", now=now)
            lease_until = min(
                now + timedelta(seconds=record.job.policy.lease_seconds), record.job.deadline
            )
            if lease_until <= attempt.lease_until:
                return attempt.model_copy(deep=True)
            renewed = attempt.model_copy(
                update={"lease_until": lease_until, "attempt_digest": None}
            )
            renewed = SurfaceProfileAttemptV1.model_validate(renewed.model_dump()).sealed()
            record = self._append(
                JobRenewed(job_id=job_id, sequence=record.sequence + 1, at=now, attempt=renewed)
            )
            assert record.attempt is not None
            return record.attempt.model_copy(deep=True)

    def worker_input_for_attempt_digest(
        self,
        *,
        job_id: str,
        worker: Principal,
        instance_id: str,
        attempt_digest: str,
        now: datetime,
    ) -> tuple[SurfaceProfileFrozenJobV1, SurfaceProfileAttemptV1]:
        with self._guard(now):
            self._worker(worker, instance_id, now)
            record = self._worker_record(job_id, worker)
            attempt = record.attempt
            if (
                attempt is None
                or attempt.worker_principal_id != worker.principal_id
                or attempt.worker_instance_id != instance_id
                or attempt.attempt_digest != attempt_digest
            ):
                raise SurfaceProfileDomainError("FENCE_CONFLICT", 409)
            self._live(record, attempt, now)
            self._authority.reprove(record.job, operation="PREPARE", now=now)
            return record.job.model_copy(deep=True), attempt.model_copy(deep=True)

    def worker_input(
        self, *, job_id: str, worker: Principal, attempt: SurfaceProfileAttemptV1, now: datetime
    ) -> SurfaceProfileFrozenJobV1:
        """The frozen job for the one live attempt — after re-proving the requester's authority."""
        self._worker_attempt(worker, attempt, now)
        with self._guard(now):
            record = self._worker_record(job_id, worker)
            self._live(record, attempt, now)
            self._authority.reprove(record.job, operation="PREPARE", now=now)
            return record.job.model_copy(deep=True)

    def fail(
        self,
        *,
        job_id: str,
        worker: Principal,
        attempt: SurfaceProfileAttemptV1,
        reason: str,
        now: datetime,
    ) -> SurfaceProfileJobViewV1:
        self._worker_attempt(worker, attempt, now)
        valid = SurfaceProfileDomainError(reason, 422).reason
        with self._guard(now):
            record = self._worker_record(job_id, worker)
            self._live(record, attempt, now)
            job = record.job
            retry_at = now + timedelta(seconds=job.policy.min_retry_backoff_seconds)
            retry = (
                valid in TRANSIENT_JOB_REASONS
                and record.attempts < job.policy.max_attempts
                and retry_at < job.deadline
            )
            record = self._append(
                JobStateChanged(
                    job_id=job_id,
                    sequence=record.sequence + 1,
                    at=now,
                    state="QUEUED" if retry else "FAILED",
                    reason=valid,
                    next_available_at=retry_at if retry else None,
                    attempt=attempt,
                )
            )
            return self._view(record, now)

    def complete(
        self,
        *,
        job_id: str,
        worker: Principal,
        attempt: SurfaceProfileAttemptV1,
        result: SurfaceProfileResultV1,
        receipt: SurfaceProfileReceiptV1,
        now: datetime,
    ) -> SurfaceProfileJobViewV1:
        self._worker_attempt(worker, attempt, now)
        with self._guard(now):
            record = self._worker_record(job_id, worker)
            if record.state == "COMPLETED":
                # A retried completion: only the identical report is acknowledged.
                if (
                    record.attempt is None
                    or attempt != record.attempt
                    or result != record.result
                    or receipt != record.receipt
                ):
                    raise SurfaceProfileDomainError("REPORT_CONFLICT", 409)
                return self._view(record, now)
            self._live(record, attempt, now)
            self._authority.reprove(record.job, operation="PREPARE", now=now)
            self._verify_completion(record.job, attempt, result, receipt, now)
            record = self._append(
                JobCompleted(
                    job_id=job_id,
                    sequence=record.sequence + 1,
                    at=now,
                    attempt=attempt,
                    result=result,
                    receipt=receipt,
                )
            )
            return self._view(record, now)

    # ── the worker's answer, checked against what Core froze ─────────────
    @staticmethod
    def _verify_completion(
        job: SurfaceProfileFrozenJobV1,
        attempt: SurfaceProfileAttemptV1,
        result: SurfaceProfileResultV1,
        receipt: SurfaceProfileReceiptV1,
        now: datetime,
    ) -> None:
        def refuse() -> SurfaceProfileDomainError:
            return SurfaceProfileDomainError("INTEGRITY_MISMATCH", 409)

        source, policy = job.source, job.policy
        measured = source.inspection.measurements
        if measured is None:
            raise refuse()
        if (
            receipt.receipt_digest != receipt.canonical_digest()
            or result.result_digest != result.canonical_digest()
            or receipt.job_id != job.job_id
            or attempt.job_id != job.job_id
            or receipt.job_digest != job.job_digest
            or receipt.source_digest != source.source_digest
            or receipt.request_digest != job.request_fingerprint
            or receipt.grant_digest != job.grant.grant_digest
            or receipt.data_policy_digest != job.data_policy_digest
            or receipt.policy_digest != policy.policy_digest
            or receipt.runtime_digest != job.runtime.runtime_digest
            or receipt.artifact_id != source.artifact_id
            or receipt.source_sha256 != source.observed_sha256
            or receipt.source_size_bytes != source.observed_size_bytes
            or receipt.observed_crs_identifier != measured.observed_crs_identifier
            or receipt.observed_crs_digest != measured.observed_crs_digest
            or receipt.vertical_reference != job.vertical_reference
            or receipt.read_window != job.read_window
            or receipt.result_digest != result.result_digest
            or receipt.window_cells_read != result.window_cells_read
            or receipt.accuracy_assessed is not False
            or not attempt.acquired_at <= receipt.prepared_at <= now
        ):
            raise refuse()
        if len(canonical_json_bytes(result.model_dump(by_alias=True, mode="json"))) > (
            policy.max_result_bytes
        ):
            raise SurfaceProfileDomainError("RESOURCE_LIMIT_EXCEEDED", 413)
        request = job.profile_request
        if (
            result.asset_ref != request.asset_ref
            or result.line_digest != request.line.digest()
            or result.feature != request.feature
            or result.volume_computed is not False
            or result.accuracy_assessed is not False
        ):
            raise refuse()
        try:
            horizontal = normalise_crs(measured.observed_crs_identifier)
            a, _, c, _, e, f = measured.transform
            spacing = request.sample_spacing_m or max(a, -e)
            plan = plan_surface_profile(
                request.line.vertices,
                vertices_crs=request.line.crs,
                horizontal_crs=horizontal,
                sample_spacing_m=spacing,
                policy=SurfaceProfilePolicy(
                    maximum_vertices=policy.maximum_vertices,
                    maximum_samples=policy.maximum_samples,
                    maximum_line_length_m=policy.maximum_line_length_m,
                    maximum_window_cells=policy.maximum_window_cells,
                    maximum_source_block_cells=policy.maximum_source_block_cells,
                ),
            )
        except (SurfaceProfileError, ValueError) as exc:
            raise refuse() from exc
        if (
            result.horizontal_crs != plan.horizontal_crs
            or result.line_length_m != plan.line_length_m
            or result.sample_spacing_m != plan.sample_spacing_m
            or len(result.samples) != len(plan.points)
        ):
            raise refuse()
        located = locate_profile_samples(
            plan,
            left=c,
            top=f,
            cell_size_x=a,
            cell_size_y=-e,
            width=measured.width,
            height=measured.height,
        )
        for index, (sample, place) in enumerate(zip(result.samples, located, strict=True)):
            if (sample.x, sample.y) != plan.points[index] or (
                sample.distance_m != plan.distances_m[index]
            ):
                raise refuse()
            if place.reason is not None:
                # Geometry alone says unknown: a number here would be invented.
                if sample.elevation_m is not None or sample.invalid_reason != place.reason.value:
                    raise refuse()
            elif sample.invalid_reason in (
                SampleInvalidReason.OUTSIDE_SURFACE.value,
                SampleInvalidReason.INSUFFICIENT_NEIGHBORS.value,
            ):
                raise refuse()  # the geometry makes this sample readable
        limit = job.read_window.cells if job.read_window is not None else 0
        if result.window_cells_read > limit:
            raise refuse()


__all__ = [
    "ACTIVE_STATES",
    "JOB_EVENT",
    "JobRecord",
    "SurfaceProfileAdmission",
    "SurfaceProfileAuthorityPort",
    "SurfaceProfileDomainError",
    "SurfaceProfileJobRecoveryError",
    "SurfaceProfileJobStore",
    "transition",
]
