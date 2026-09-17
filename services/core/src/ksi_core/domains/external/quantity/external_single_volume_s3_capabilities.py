"""Fail-closed S3 GET capabilities for leased external single-volume work.

Two capabilities are issued for the exact running lease: the target DSM from
the sealed reconstruction manifest and the exact sealed checkpoint CSV behind
the one bound evidence record.  No bearer URL is persisted.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

from ksi_core.domains.artifacts.evidence import (
    DEFAULT_VIEW_TTL,
    EvidenceStorage,
    EvidenceStorageError,
)
from ksi_core.domains.external.ingress.external_evidence_validations import (
    ExternalEvidenceValidationStore,
)
from ksi_core.domains.external.ingress.external_reconstruction import ExternalReconstructionStore
from ksi_core.domains.external.quantity.external_relative_volumes import (
    ExternalRelativeVolumeInputCapability,
    ExternalRelativeVolumeStatus,
)
from ksi_core.domains.external.quantity.external_single_volumes import (
    ExternalSingleVolumeRecord,
    SingleVolumeWorkerLaunchMaterial,
)
from ksi_core.foundation.leasing import LeaseFence, check_lease
from ksi_core.identity.auth import Principal, PrincipalKind


class ExternalSingleVolumeS3InputCapabilityIssuer:
    """Issue ``(TARGET_DSM, CHECKPOINT_CSV)`` GET capabilities for one exact lease."""

    def __init__(
        self,
        *,
        reconstruction: ExternalReconstructionStore,
        evidence_validations: ExternalEvidenceValidationStore,
        storage: EvidenceStorage,
        signing_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._reconstruction = reconstruction
        self._evidence_validations = evidence_validations
        self._storage = storage
        self._signing_clock = signing_clock or (lambda: datetime.now(UTC))

    def __call__(
        self,
        record: ExternalSingleVolumeRecord,
        material: SingleVolumeWorkerLaunchMaterial,
        *,
        fence: LeaseFence,
        principal: Principal,
        now: datetime,
    ) -> tuple[ExternalRelativeVolumeInputCapability, ExternalRelativeVolumeInputCapability] | None:
        authority = record.authority
        request = record.request
        target = authority.target
        evidence_record = material.evidence_record
        context = material.evidence_context
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
            or request.target != target
            or request.evidence_record_digests != (evidence_record.evidence_record_digest,)
            or check_lease(
                record.lease,
                fence=fence,
                authenticated_actor_id=principal.principal_id,
                now=now,
            )
            is not None
        ):
            return None
        revision = self._reconstruction.resolve_sealed_subject(target.subject)
        if revision is None or revision.manifest is None:
            return None
        dsm = next(
            (
                entry
                for entry in revision.manifest.entries
                if entry.kind is ProcessingArtifactKind.DSM
                and entry.artifact_id == target.dsm_artifact_id
                and "sha256:" + entry.observed_sha256 == target.observed_sha256
                and entry.observed_size_bytes == target.observed_size_bytes
            ),
            None,
        )
        evidence_object = self._evidence_validations.sealed_evidence_object_for(
            request.evidence_record_digests[0],
            subject=target.subject,
            policy_digest=request.validation_policy_digest,
        )
        if dsm is None or evidence_object is None:
            return None
        evidence_key, manifest = evidence_object
        if (
            manifest.evidence_manifest_digest != evidence_record.evidence_manifest_digest
            or manifest.observed_object_digest != context.evidence_observed_sha256
            or manifest.observed_size_bytes != context.evidence_observed_size_bytes
            or manifest.target_dsm_observed_sha256 != target.observed_sha256
        ):
            return None
        assert record.lease is not None  # check_lease above establishes this.
        upper_bound = min(
            now + DEFAULT_VIEW_TTL,
            record.lease.expires_at,
            record.deadline_at,
            authority.valid_until,
        )
        first = self._presign_one(
            role="TARGET_DSM", object_key=dsm.object_key, upper_bound=upper_bound, not_before=now
        )
        if first is None:
            return None
        target_capability, first_clock = first
        second = self._presign_one(
            role="CHECKPOINT_CSV",
            object_key=evidence_key,
            upper_bound=upper_bound,
            not_before=first_clock,
        )
        if second is None:
            return None
        evidence_capability, second_clock = second
        completed_at = self._signing_clock()
        if (
            not _trusted_utc(completed_at)
            or completed_at < second_clock
            or completed_at >= upper_bound
            or completed_at >= min(target_capability.expires_at, evidence_capability.expires_at)
        ):
            return None
        return target_capability, evidence_capability

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


__all__ = ["ExternalSingleVolumeS3InputCapabilityIssuer"]
