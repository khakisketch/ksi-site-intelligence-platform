"""Pure validated transitions, used identically before live append and during replay."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from urllib.parse import quote

from ksi_event_contracts.spatial_data import (
    SpatialDataAttemptV1,
    SpatialDataFrozenJobV1,
    SpatialDataReasonV1,
    SpatialDataReceiptV1,
)
from ksi_event_contracts.spatial_data_authority import SpatialDataPolicyV1
from ksi_event_contracts.spatial_data_worker import SpatialDataUploadDeclarationV1
from ksi_geo_spatial.external_native_window_geometry import plan_external_native_window

from ksi_core.domains.external.delivery.job_events import (
    JobCleanupChanged,
    JobCompleted,
    JobEvent,
    JobIssued,
    JobLeased,
    JobOutputReserved,
    JobRenewed,
    JobStateChanged,
)
from ksi_core.domains.external.delivery.storage_types import (
    SpatialDataObjectObservation,
    SpatialDataOutputTarget,
)

ACTIVE = frozenset({"QUEUED", "RUNNING"})
TRANSIENT = frozenset({"STORAGE_UNAVAILABLE"})


@dataclass(frozen=True)
class OwnedOutput:
    target: SpatialDataOutputTarget
    receipt: SpatialDataReceiptV1
    upload_digest: str
    observation: SpatialDataObjectObservation | None = None
    cleanup: CleanupStatus | None = None


@dataclass(frozen=True)
class CleanupStatus:
    cleanup_id: str
    attempt_number: int
    state: str
    started_at: datetime
    updated_at: datetime
    reason: SpatialDataReasonV1 | None = None


@dataclass(frozen=True)
class CleanupHandle:
    job: SpatialDataFrozenJobV1
    output: OwnedOutput
    cleanup_id: str
    attempt_number: int
    started_at: datetime


def cleanup_ready_at(record: JobRecord, fence: str) -> datetime:
    owned = record.outputs[fence]
    ready = owned.target.expires_at
    if fence == record.accepted_fence:
        assert record.completed_at is not None
        ready = max(
            ready, record.completed_at + timedelta(seconds=record.job.policy.retention_seconds)
        )
    elif (
        record.state == "RUNNING"
        and record.attempt is not None
        and fence == record.attempt.fence_digest()
    ):
        ready = max(ready, record.attempt.lease_until)
    return ready


@dataclass(frozen=True)
class CleanupCandidate:
    target: SpatialDataOutputTarget
    observation: SpatialDataObjectObservation | None
    ready_at: datetime
    policy: SpatialDataPolicyV1


@dataclass(frozen=True)
class DownloadOutput:
    job: SpatialDataFrozenJobV1
    target: SpatialDataOutputTarget
    observation: SpatialDataObjectObservation
    receipt: SpatialDataReceiptV1


@dataclass(frozen=True)
class JobRecord:
    job: SpatialDataFrozenJobV1
    sequence: int
    updated_at: datetime
    state: str = "QUEUED"
    reason: SpatialDataReasonV1 | None = None
    attempt: SpatialDataAttemptV1 | None = None
    acquisitions: frozenset[str] = frozenset()
    next_available_at: datetime | None = None
    outputs: dict[str, OwnedOutput] = field(default_factory=dict)
    accepted_fence: str | None = None
    completed_at: datetime | None = None


def owned_key(job: SpatialDataFrozenJobV1, attempt: SpatialDataAttemptV1) -> str:
    organization = quote(job.organization_id, safe="")
    return f"spatial-data/v1/{organization}/{job.job_id}/{attempt.fence_digest()[7:]}/result.tif"


def validate_receipt(
    job: SpatialDataFrozenJobV1,
    attempt: SpatialDataAttemptV1,
    receipt: SpatialDataReceiptV1,
    *,
    now: datetime,
) -> None:
    receipt = SpatialDataReceiptV1.model_validate(receipt.model_dump())
    source = job.source
    measured = source.inspection.measurements
    assert measured is not None
    geometry = plan_external_native_window(
        requested_bounds=job.request.requested_bounds,
        measurements=measured,
        requested_crs_digest=job.request.observed_crs_digest,
    )
    c0, c1, r0, r1 = geometry.pixel_window
    expected = {
        "job_id": job.job_id,
        "job_digest": job.job_digest,
        "request_digest": job.request.canonical_digest(),
        "artifact_id": source.artifact_id,
        "source_digest": source.source_digest,
        "policy_digest": job.policy.policy_digest,
        "grant_digest": job.grant.grant_digest,
        "runtime_digest": job.runtime.runtime_digest,
        "artifact_kind": source.artifact_kind,
        "source_sha256": source.observed_sha256,
        "source_size_bytes": source.observed_size_bytes,
        "requested_bounds": job.request.requested_bounds,
        "requested_crs_digest": job.request.observed_crs_digest,
        "actual_bounds": geometry.actual_bounds,
        "pixel_window": geometry.pixel_window,
        "width": c1 - c0,
        "height": r1 - r0,
        "transform": geometry.transform,
        "source_transform": measured.transform,
        "source_resolution": (measured.transform[0], -measured.transform[4]),
        "observed_crs_identifier": measured.observed_crs_identifier,
        "observed_crs_digest": measured.observed_crs_digest,
        "observed_vertical_reference": measured.observed_vertical_reference,
        "band_count": measured.band_count,
        "dtype": measured.dtype,
        "capture_started_at": source.capture_started_at,
        "capture_ended_at": source.capture_ended_at,
        "producer_processed_at": source.producer_processed_at,
        "declaration_recorded_at": source.declaration_recorded_at,
        "attribution": job.grant.attribution,
    }
    if (
        receipt.receipt_digest != receipt.canonical_digest()
        or any(getattr(receipt, key) != value for key, value in expected.items())
        or not attempt.acquired_at <= receipt.prepared_at <= now
        or receipt.output_size_bytes > job.policy.max_output_bytes
        or receipt.width * receipt.height > job.policy.max_output_pixels
        or receipt.valid_pixel_count > measured.valid_pixel_count
    ):
        raise ValueError("receipt does not bind exact frozen job and bounded output")


def transition(current: JobRecord | None, event: JobEvent) -> JobRecord:
    if isinstance(event, JobIssued):
        if current is not None:
            raise ValueError("duplicate job issuance")
        job = event.job
        measured = job.source.inspection.measurements
        assert measured is not None
        geometry = plan_external_native_window(
            requested_bounds=job.request.requested_bounds,
            measurements=measured,
            requested_crs_digest=job.request.observed_crs_digest,
        )
        c0, c1, r0, r1 = geometry.pixel_window
        left, bottom, right, top = job.grant.allowed_bounds
        if (c1 - c0) * (r1 - r0) > job.policy.max_output_pixels or any(
            xmin < left or ymin < bottom or xmax > right or ymax > top
            for xmin, ymin, xmax, ymax in (job.request.requested_bounds, geometry.actual_bounds)
        ):
            raise ValueError("issuance exceeds frozen grid/expanded-cell rights")
        return JobRecord(event.job.model_copy(deep=True), event.sequence, event.at)
    if current is None or event.sequence != current.sequence + 1 or event.at < current.updated_at:
        raise ValueError("missing job or out-of-order transition")
    job = current.job
    if event.job_id != job.job_id:
        raise ValueError("event identity mismatch")
    result = replace(current, sequence=event.sequence, updated_at=event.at)
    if isinstance(event, JobLeased):
        attempt = event.attempt
        previous = current.attempt
        if (
            current.state not in ACTIVE
            or event.at >= job.deadline
            or current.next_available_at is not None
            and event.at < current.next_available_at
            or current.state == "RUNNING"
            and previous is not None
            and event.at < previous.lease_until
            or attempt.job_id != job.job_id
            or attempt.frozen_job_digest != job.job_digest
            or attempt.attempt_digest != attempt.canonical_digest()
            or attempt.acquired_at != event.at
            or attempt.lease_until > job.deadline
            or attempt.lease_until > event.at + timedelta(seconds=job.policy.lease_seconds)
            or attempt.lease_until > job.grant.valid_until
            or attempt.attempt_number != (previous.attempt_number + 1 if previous else 1)
            or attempt.fence != (previous.fence + 1 if previous else 1)
            or attempt.attempt_number > job.policy.max_attempts
            or attempt.acquisition_key_hash in current.acquisitions
        ):
            raise ValueError("invalid acquisition transition")
        return replace(
            result,
            state="RUNNING",
            reason=None,
            attempt=attempt.model_copy(deep=True),
            acquisitions=current.acquisitions | {attempt.acquisition_key_hash},
            next_available_at=None,
        )
    if isinstance(event, JobRenewed):
        old, new = current.attempt, event.attempt
        if (
            current.state != "RUNNING"
            or old is None
            or event.at >= old.lease_until
            or new.attempt_digest != new.canonical_digest()
            or new.fence_digest() != old.fence_digest()
            or new.lease_until < old.lease_until
            or new.lease_until > job.deadline
            or new.lease_until > job.grant.valid_until
            or new.lease_until > event.at + timedelta(seconds=job.policy.lease_seconds)
        ):
            raise ValueError("invalid renewal transition")
        return replace(result, attempt=new.model_copy(deep=True))
    if isinstance(event, JobStateChanged):
        if current.state not in ACTIVE:
            raise ValueError("terminal state is immutable")
        if event.state in {"FAILED", "QUEUED"}:
            if event.attempt is not None:
                if (
                    current.state != "RUNNING"
                    or event.attempt != current.attempt
                    or event.attempt.attempt_digest != event.attempt.canonical_digest()
                    or event.at >= min(event.attempt.lease_until, job.deadline)
                ):
                    raise ValueError("failure must bind a live exact worker fence")
            elif (
                event.state != "FAILED"
                or event.reason != "LEASE_EXPIRED"
                or current.attempt is None
                or event.at < current.attempt.lease_until
                or current.attempt.attempt_number < job.policy.max_attempts
            ):
                raise ValueError("unfenced failure is only exhausted expired lease recovery")
        elif event.attempt is not None:
            raise ValueError("Core cancellation/deadline events are not worker failures")
        if event.state == "QUEUED":
            if (
                current.state != "RUNNING"
                or current.attempt is None
                or event.reason not in TRANSIENT
                or current.attempt.attempt_number >= job.policy.max_attempts
                or event.next_available_at is None
                or event.next_available_at >= job.deadline
                or not event.at + timedelta(seconds=job.policy.min_retry_backoff_seconds)
                <= event.next_available_at
                <= event.at + timedelta(seconds=job.policy.max_retry_backoff_seconds)
            ):
                raise ValueError("invalid bounded transport retry")
        elif event.next_available_at is not None:
            raise ValueError("terminal state cannot schedule a retry")
        if event.state == "EXPIRED" and (
            event.at < job.deadline or event.reason != "DEADLINE_EXCEEDED"
        ):
            raise ValueError("invalid deadline expiry")
        if event.state == "CANCELED" and event.reason != "CANCELED":
            raise ValueError("invalid cancellation")
        return replace(
            result,
            state=event.state,
            reason=event.reason,
            next_available_at=event.next_available_at,
        )
    if isinstance(event, JobCleanupChanged):
        owned = current.outputs.get(event.fence_digest)
        if owned is None or event.at < cleanup_ready_at(current, event.fence_digest):
            raise ValueError("cleanup lacks expired exact ownership")
        previous_cleanup = owned.cleanup
        policy = job.policy
        if event.state == "STARTED":
            if (
                event.reason is not None
                or event.attempt_number
                != (previous_cleanup.attempt_number + 1 if previous_cleanup else 1)
                or event.attempt_number > policy.max_cleanup_attempts
                or previous_cleanup is not None
                and (
                    previous_cleanup.state == "COMPLETED"
                    or previous_cleanup.cleanup_id == event.cleanup_id
                    or previous_cleanup.state == "STARTED"
                    and event.at
                    < previous_cleanup.started_at
                    + timedelta(seconds=policy.cleanup_deadline_seconds)
                    or previous_cleanup.state == "FAILED"
                    and event.at
                    < previous_cleanup.updated_at
                    + timedelta(seconds=policy.min_retry_backoff_seconds)
                )
            ):
                raise ValueError("cleanup retry/capacity/fence invalid")
            status = CleanupStatus(
                event.cleanup_id, event.attempt_number, event.state, event.at, event.at
            )
        else:
            if (
                previous_cleanup is None
                or previous_cleanup.state != "STARTED"
                or (previous_cleanup.cleanup_id, previous_cleanup.attempt_number)
                != (event.cleanup_id, event.attempt_number)
                or (event.state == "FAILED") != (event.reason is not None)
                or event.state == "COMPLETED"
                and event.at
                >= previous_cleanup.started_at + timedelta(seconds=policy.cleanup_deadline_seconds)
            ):
                raise ValueError("cleanup completion/failure lacks live reserved fence")
            status = replace(
                previous_cleanup, state=event.state, updated_at=event.at, reason=event.reason
            )
        return replace(
            result, outputs={**current.outputs, event.fence_digest: replace(owned, cleanup=status)}
        )
    if (
        current.state != "RUNNING"
        or current.attempt is None
        or event.at >= min(current.attempt.lease_until, job.deadline)
    ):
        raise ValueError("output event outside live execution fence")
    attempt = current.attempt
    fence = attempt.fence_digest()
    if isinstance(event, JobOutputReserved):
        validate_receipt(job, attempt, event.receipt, now=event.at)
        if (
            fence in current.outputs
            or event.object_key != owned_key(job, attempt)
            or not event.at
            < event.expires_at
            <= min(attempt.lease_until, job.deadline, job.grant.valid_until)
        ):
            raise ValueError("invalid owned output target")
        declaration = SpatialDataUploadDeclarationV1(
            attempt=attempt,
            receipt=event.receipt,
            sha256=event.receipt.output_sha256,
            size_bytes=event.receipt.output_size_bytes,
            content_type="image/tiff",
        ).sealed()
        if event.upload_digest != declaration.upload_digest:
            raise ValueError("upload declaration digest mismatch")
        assert event.receipt.receipt_digest is not None
        target = SpatialDataOutputTarget(
            event.object_key, job.job_id, fence, event.receipt.receipt_digest, event.expires_at
        )
        reservation = OwnedOutput(target, event.receipt.model_copy(deep=True), event.upload_digest)
        return replace(result, outputs={**current.outputs, fence: reservation})
    if isinstance(event, JobCompleted):
        owned = current.outputs.get(fence)
        observation = SpatialDataObjectObservation(
            event.object_key, event.version_id, event.size_bytes, event.sha256, event.content_type
        )
        if (
            owned is None
            or event.upload_digest != owned.upload_digest
            or observation.object_key != owned.target.object_key
            or observation.size_bytes != owned.receipt.output_size_bytes
            or observation.sha256 != owned.receipt.output_sha256
        ):
            raise ValueError("completion lacks matching owned target and exact observed bytes")
        return replace(
            result,
            state="COMPLETED",
            reason=None,
            accepted_fence=fence,
            completed_at=event.at,
            outputs={**current.outputs, fence: replace(owned, observation=observation)},
        )
    raise ValueError("unknown job event")
