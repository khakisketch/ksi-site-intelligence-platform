"""One bounded cleanup pass over durable exact-target obligations, never source keys."""

from datetime import datetime, timedelta
from time import monotonic
from uuid import uuid4

from ksi_core.domains.external.delivery.audit import SpatialDataAuditEventV1, SpatialDataAuditStore
from ksi_core.domains.external.delivery.errors import SpatialDataDomainError
from ksi_core.domains.external.delivery.job_projection import CleanupHandle
from ksi_core.domains.external.delivery.jobs import SpatialDataJobStore
from ksi_core.domains.external.delivery.storage import SpatialDataStoragePort
from ksi_core.domains.external.delivery.storage_types import SpatialDataObjectObservation


def _audit(
    audit: SpatialDataAuditStore,
    handle: CleanupHandle,
    action: str,
    now: datetime,
    reason: str | None = None,
) -> None:
    job, output = handle.job, handle.output
    audit.append(
        SpatialDataAuditEventV1.model_validate(
            dict(
                event_id=str(uuid4()),
                session_id=handle.cleanup_id,
                organization_id=job.organization_id,
                principal_id=job.requester_principal_id,
                site_id=job.site_id,
                work_area_id=job.work_area_id,
                job_id=job.job_id,
                at=now,
                action=action,
                expected_size_bytes=output.receipt.output_size_bytes,
                output_sha256=output.receipt.output_sha256,
                sent_bytes=0,
                reason=reason,
            )
        ).sealed()
    )


def run_spatial_data_cleanup_once(
    *,
    jobs: SpatialDataJobStore,
    storage: SpatialDataStoragePort,
    audit: SpatialDataAuditStore,
    now: datetime,
) -> int:
    """Retire only after complete exact inventory and acknowledged deletions.

    Storage owns the bounded SDK operation supervisor. This pass rechecks finite
    durable cleanup leases before and after I/O; it cannot promise hard host-I/O
    deadlines or recall an already in-flight authorized delete.
    """
    if audit.policy != jobs.policy:
        raise ValueError("exact cleanup audit policy required")
    initial = monotonic()
    completed = 0
    candidates = jobs.cleanup_pending(limit=jobs.policy.max_pending_records, now=now)

    def current() -> datetime:
        return now + timedelta(seconds=monotonic() - initial)

    for candidate in candidates:
        handle = jobs.reserve_cleanup(candidate=candidate, now=current())
        if handle is None:
            continue
        audit_started = False
        retired = False
        try:
            _audit(audit, handle, "CLEANUP_STARTED", current())
            audit_started = True
            jobs.require_cleanup(handle=handle, now=current())
            versions = storage.list_owned_versions(
                candidate.target, limit=candidate.policy.max_list_records
            )
            if (
                type(versions) is not tuple
                or len(versions) > candidate.policy.max_list_records
                or any(type(version) is not SpatialDataObjectObservation for version in versions)
                or len({version.version_id for version in versions}) != len(versions)
                or any(version.object_key != candidate.target.object_key for version in versions)
            ):
                raise SpatialDataDomainError("INTEGRITY_MISMATCH", 503)
            for version in versions:
                jobs.require_cleanup(handle=handle, now=current())
                storage.delete_owned_version(candidate.target, version.version_id)
                jobs.require_cleanup(handle=handle, now=current())
            jobs.finish_cleanup(handle=handle, now=current())
            retired = True
            _audit(audit, handle, "CLEANUP_COMPLETED", current())
            completed += 1
        except Exception as exc:
            if retired:
                raise  # Durable retirement stands; unavailable trailing audit is visible.
            reason = (
                exc.reason if isinstance(exc, SpatialDataDomainError) else "STORAGE_UNAVAILABLE"
            )
            jobs.finish_cleanup(handle=handle, now=current(), reason=reason)
            if audit_started:
                # An unavailable audit is surfaced, not silently treated as cleaned.
                _audit(audit, handle, "CLEANUP_FAILED", current(), reason)
    return completed
