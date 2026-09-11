"""Fail-closed S3 GET capabilities for leased external relative-volume work.

This adapter owns no authority and persists no bearer URLs.  It only projects
two already-sealed DSM identities into short-lived storage capabilities after
locally rechecking the running worker record supplied by Core.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

from ksi_core.auth import Principal, PrincipalKind
from ksi_core.evidence import DEFAULT_VIEW_TTL, EvidenceStorage, EvidenceStorageError
from ksi_core.external_reconstruction import ExternalReconstructionStore
from ksi_core.external_relative_volumes import (
    ExternalRelativeVolumeInputCapability,
    ExternalRelativeVolumeRecord,
    ExternalRelativeVolumeStatus,
)
from ksi_core.leasing import LeaseFence, check_lease


class ExternalRelativeVolumeS3InputCapabilityIssuer:
    """Issue ordered DSM GET capabilities only for the exact active worker lease.

    ``EvidenceStorage.presigned_get`` deliberately returns only a URL, so Core
    cannot inspect the S3 signing timestamp.  ``expires_at`` is therefore the
    issuer wall-clock projection for its integer-second request TTL, not an
    assertion about an opaque remote signer's clock.
    """

    def __init__(
        self,
        *,
        reconstruction: ExternalReconstructionStore,
        storage: EvidenceStorage,
        signing_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._reconstruction = reconstruction
        self._storage = storage
        self._signing_clock = signing_clock or (lambda: datetime.now(UTC))

    def __call__(
        self,
        record: ExternalRelativeVolumeRecord,
        *,
        fence: LeaseFence,
        principal: Principal,
        now: datetime,
    ) -> tuple[ExternalRelativeVolumeInputCapability, ExternalRelativeVolumeInputCapability] | None:
        authority = record.authority
        request = record.request
        if (
            principal.kind is not PrincipalKind.PROCESSING_WORKER
            or principal.role is not None
            or principal.device_id is not None
            or principal.organization_id != authority.organization_id
            or principal.principal_id not in authority.authorized_actor_ids
            or authority.synthetic_test_only
            or authority.execution_policy.synthetic_test_only
            or record.status is not ExternalRelativeVolumeStatus.RUNNING
            or now >= record.deadline_at
            or not authority.is_current_at(now)
            or request.current_work_order_id != authority.current_work_order_id
            or request.baseline != authority.baseline
            or request.current != authority.current
            or check_lease(
                record.lease,
                fence=fence,
                authenticated_actor_id=principal.principal_id,
                now=now,
            )
            is not None
        ):
            return None

        bindings = (("BASELINE_DSM", authority.baseline), ("CURRENT_DSM", authority.current))
        resolved: list[tuple[str, str]] = []
        for role, binding in bindings:
            revision = self._reconstruction.resolve_sealed_subject(binding.subject)
            if revision is None or revision.manifest is None:
                return None
            dsm = next(
                (
                    entry
                    for entry in revision.manifest.entries
                    if entry.kind is ProcessingArtifactKind.DSM
                    and entry.artifact_id == binding.dsm_artifact_id
                    and "sha256:" + entry.observed_sha256 == binding.observed_sha256
                    and entry.observed_size_bytes == binding.observed_size_bytes
                ),
                None,
            )
            if dsm is None:
                return None
            resolved.append((role, dsm.object_key))

        assert record.lease is not None  # check_lease above establishes this.
        upper_bound = min(
            now + DEFAULT_VIEW_TTL,
            record.lease.expires_at,
            record.deadline_at,
            authority.valid_until,
        )
        first = self._presign_one(
            role=resolved[0][0],
            object_key=resolved[0][1],
            upper_bound=upper_bound,
            not_before=now,
        )
        if first is None:
            return None
        baseline, first_clock = first
        second = self._presign_one(
            role=resolved[1][0],
            object_key=resolved[1][1],
            upper_bound=upper_bound,
            not_before=first_clock,
        )
        if second is None:
            return None
        current, second_clock = second
        completed_at = self._signing_clock()
        if (
            not _trusted_utc(completed_at)
            or completed_at < second_clock
            or completed_at >= upper_bound
            or completed_at >= min(baseline.expires_at, current.expires_at)
        ):
            return None
        return baseline, current

    def _presign_one(
        self,
        *,
        role: str,
        object_key: str,
        upper_bound: datetime,
        not_before: datetime,
    ) -> tuple[ExternalRelativeVolumeInputCapability, datetime] | None:
        signing_now = self._signing_clock()
        if not _trusted_utc(signing_now) or signing_now < not_before:
            return None
        seconds = int((upper_bound - signing_now).total_seconds())
        if seconds < 1:
            return None
        ttl = timedelta(seconds=seconds)
        try:
            url = self._storage.presigned_get(object_key, ttl=ttl)
        except EvidenceStorageError:
            return None
        return (
            ExternalRelativeVolumeInputCapability(
                role=role,
                download_url=url,
                required_headers={},
                expires_at=signing_now + ttl,
            ),
            signing_now,
        )


def _trusted_utc(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


__all__ = ["ExternalRelativeVolumeS3InputCapabilityIssuer"]
