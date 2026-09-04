"""Shared, fenced worker lease primitives.

Authentication identifies the caller for audit and organisation visibility; it
never identifies a lease owner.  A lease owner is a :class:`LeaseFence`, made
up of a process instance, a durable CLAIM/acquisition id, and a monotonic
generation.  Stores retain the journal/locking responsibility; this module is
deliberately pure so every work ledger applies the same fencing rule.

The ``worker_id`` spelling is retained as a compatibility alias for journal
records written before worker correctness TASK-1.  Such records are generation
zero and remain readable, but a generation-zero identity is not a valid new
worker fence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from ksi_event_contracts.processing_job import ProcessingJobStatus


@dataclass(frozen=True, slots=True)
class LeaseFence:
    """The only identity permitted to renew or mutate a leased work item."""

    worker_instance_id: str
    lease_acquisition_id: str
    lease_generation: int

    def has_valid_ids(self) -> bool:
        try:
            worker = UUID(self.worker_instance_id)
            acquisition = UUID(self.lease_acquisition_id)
            return (
                worker.version == 4
                and acquisition.version == 4
                and str(worker) == self.worker_instance_id
                and str(acquisition) == self.lease_acquisition_id
            )
        except (ValueError, AttributeError):
            return False

    def is_well_formed(self) -> bool:
        """Accept UUIDv4 process/acquisition ids and a positive generation."""
        if self.lease_generation < 1:
            return False
        return self.has_valid_ids()


class LeaseMode(StrEnum):
    CLAIM = "CLAIM"
    RENEW = "RENEW"


@dataclass(frozen=True, slots=True)
class JobLease:
    """A durable lease projection.

    ``worker_id`` is the historical serialized name.  In new records it is
    always the worker *instance* id, never the bearer-token principal.
    """

    worker_id: str
    granted_at: datetime
    expires_at: datetime
    lease_acquisition_id: str | None = None
    lease_generation: int = 0
    authenticated_actor_id: str | None = None

    @property
    def worker_instance_id(self) -> str:
        return self.worker_id

    @property
    def fence(self) -> LeaseFence | None:
        if self.lease_acquisition_id is None or self.lease_generation < 1:
            return None
        return LeaseFence(self.worker_id, self.lease_acquisition_id, self.lease_generation)

    def is_active(self, now: datetime) -> bool:
        return now < self.expires_at

    def held_by(self, worker_id: str, now: datetime) -> bool:
        """Legacy helper.  New mutable paths must pass ``LeaseFence``."""
        return self.is_active(now) and self.worker_id == worker_id


class LeaseDenialReason(StrEnum):
    MISSING_OR_EXPIRED = "missing_or_expired"
    HELD_BY_ANOTHER = "held_by_another"
    STALE_ACQUISITION = "stale_acquisition"
    STALE_GENERATION = "stale_generation"
    INVALID_FENCE = "invalid_fence"


def check_lease(
    lease: JobLease | None,
    *,
    now: datetime,
    fence: LeaseFence | None = None,
    worker_id: str | None = None,
    authenticated_actor_id: str | None = None,
) -> LeaseDenialReason | None:
    """Check an active lease.

    ``worker_id`` is legacy read compatibility only.  New routes/stores pass a
    full fence, which prevents two processes sharing one credential from being
    mistaken for one owner and fences delayed mutations from old generations.
    """
    if lease is None or not lease.is_active(now):
        return LeaseDenialReason.MISSING_OR_EXPIRED
    if fence is not None:
        if not fence.is_well_formed():
            return LeaseDenialReason.INVALID_FENCE
        if lease.worker_instance_id != fence.worker_instance_id:
            return LeaseDenialReason.HELD_BY_ANOTHER
        if lease.lease_acquisition_id != fence.lease_acquisition_id:
            return LeaseDenialReason.STALE_ACQUISITION
        if lease.lease_generation != fence.lease_generation:
            return LeaseDenialReason.STALE_GENERATION
        if (
            lease.authenticated_actor_id is not None
            and authenticated_actor_id != lease.authenticated_actor_id
        ):
            return LeaseDenialReason.HELD_BY_ANOTHER
        return None
    if worker_id is None:
        return LeaseDenialReason.INVALID_FENCE
    if lease.worker_id != worker_id:
        return LeaseDenialReason.HELD_BY_ANOTHER
    return None


def is_claimable(status: ProcessingJobStatus, lease: JobLease | None, now: datetime) -> bool:
    if status is ProcessingJobStatus.QUEUED:
        return True
    return status is ProcessingJobStatus.RUNNING and (lease is None or not lease.is_active(now))


def next_lease(
    *,
    now: datetime,
    ttl: timedelta,
    worker_id: str | None = None,
    worker_instance_id: str | None = None,
    lease_acquisition_id: str | None = None,
    lease_generation: int = 0,
    authenticated_actor_id: str | None = None,
    granted_at: datetime | None = None,
) -> JobLease:
    """Build a lease; callers choose the generation under their store lock."""
    instance_id = worker_instance_id if worker_instance_id is not None else worker_id
    if instance_id is None:
        raise ValueError("worker_instance_id is required")
    return JobLease(
        worker_id=instance_id,
        granted_at=granted_at if granted_at is not None else now,
        expires_at=now + ttl,
        lease_acquisition_id=lease_acquisition_id,
        lease_generation=lease_generation,
        authenticated_actor_id=authenticated_actor_id,
    )


def lease_raw_fields(*, lease: JobLease, mode: LeaseMode) -> dict[str, object]:
    """Canonical new-format journal fields; legacy reader accepts absent ones."""
    return {
        "workerId": lease.worker_instance_id,
        "workerInstanceId": lease.worker_instance_id,
        "leaseAcquisitionId": lease.lease_acquisition_id,
        "leaseGeneration": lease.lease_generation,
        "authenticatedActorId": lease.authenticated_actor_id,
        "leaseMode": mode.value,
        "renewal": mode is LeaseMode.RENEW,
    }


__all__ = [
    "JobLease",
    "LeaseDenialReason",
    "LeaseFence",
    "LeaseMode",
    "check_lease",
    "is_claimable",
    "lease_raw_fields",
    "next_lease",
]
