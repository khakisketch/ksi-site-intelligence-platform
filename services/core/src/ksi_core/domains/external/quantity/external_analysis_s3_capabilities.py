"""Lease-bound DSM GET capabilities for the V2 Analysis worker boundary."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal

from ksi_event_contracts.external_analysis_worker import AnalysisWorkerInputCapabilityV1
from ksi_event_contracts.external_artifact_validation import SealedExternalSubjectV1
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

from ksi_core.domains.artifacts.evidence import (
    DEFAULT_VIEW_TTL,
    EvidenceStorage,
    EvidenceStorageError,
)
from ksi_core.domains.external.ingress.external_reconstruction import ExternalReconstructionStore
from ksi_core.domains.external.quantity.external_relative_volume_calculations import (
    CalculationExecutionRecordV2,
    CalculationExecutionStatusV2,
)
from ksi_core.identity.auth import Principal, PrincipalKind


class ExternalAnalysisS3InputCapabilityIssuer:
    """Project only the exact running calculation identity into bounded URLs.

    The NX input transition has already checked AP currentness.  This adapter
    independently verifies the retained sealed reconstruction and active
    fence before it signs either object.  The worker API repeats NX's exact
    input check after this external I/O before returning the capabilities.
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
        record: CalculationExecutionRecordV2,
        *,
        attempt: object,
        principal: Principal,
        now: datetime,
    ) -> tuple[AnalysisWorkerInputCapabilityV1, AnalysisWorkerInputCapabilityV1] | None:
        identity = record.admission.calculation_identity
        active = record.active_attempt
        if (
            identity is None
            or principal.kind is not PrincipalKind.ANALYSIS_WORKER
            or principal.role is not None
            or principal.device_id is not None
            or principal.organization_id != record.organization_id
            or record.status is not CalculationExecutionStatusV2.RUNNING
            or active != attempt
            or active is None
            or active.lease_expires_at <= now
            or now >= self._deadline(record)
        ):
            return None
        bindings: tuple[
            tuple[
                Literal["BASELINE_DSM", "CURRENT_DSM"],
                SealedExternalSubjectV1,
                str,
                str,
                int,
            ],
            ...,
        ] = (
            (
                "BASELINE_DSM",
                identity.baseline_subject,
                identity.baseline_dsm_artifact_id,
                identity.baseline_dsm_observed_sha256,
                identity.baseline_dsm_observed_size_bytes,
            ),
            (
                "CURRENT_DSM",
                identity.current_subject,
                identity.current_dsm_artifact_id,
                identity.current_dsm_observed_sha256,
                identity.current_dsm_observed_size_bytes,
            ),
        )
        resolved: list[tuple[Literal["BASELINE_DSM", "CURRENT_DSM"], str, str, str, int]] = []
        for role, subject, artifact_id, observed_sha256, observed_size_bytes in bindings:
            revision = self._reconstruction.resolve_sealed_subject(subject)
            if revision is None or revision.manifest is None:
                return None
            dsm = next(
                (
                    entry
                    for entry in revision.manifest.entries
                    if entry.kind is ProcessingArtifactKind.DSM
                    and entry.artifact_id == artifact_id
                    and "sha256:" + entry.observed_sha256 == observed_sha256
                    and entry.observed_size_bytes == observed_size_bytes
                ),
                None,
            )
            if dsm is None:
                return None
            resolved.append(
                (role, dsm.object_key, artifact_id, observed_sha256, observed_size_bytes)
            )

        upper_bound = min(now + DEFAULT_VIEW_TTL, active.lease_expires_at, self._deadline(record))
        baseline = self._presign_one(*resolved[0], upper_bound=upper_bound, not_before=now)
        if baseline is None:
            return None
        current = self._presign_one(*resolved[1], upper_bound=upper_bound, not_before=baseline[1])
        if current is None:
            return None
        completed_at = self._signing_clock()
        if (
            not _is_utc(completed_at)
            or completed_at < current[1]
            or completed_at >= upper_bound
            or completed_at >= min(baseline[0].expires_at, current[0].expires_at)
        ):
            return None
        return baseline[0], current[0]

    def _presign_one(
        self,
        role: Literal["BASELINE_DSM", "CURRENT_DSM"],
        object_key: str,
        artifact_id: str,
        observed_sha256: str,
        observed_size_bytes: int,
        *,
        upper_bound: datetime,
        not_before: datetime,
    ) -> tuple[AnalysisWorkerInputCapabilityV1, datetime] | None:
        signed_at = self._signing_clock()
        if not _is_utc(signed_at) or signed_at < not_before:
            return None
        seconds = int((upper_bound - signed_at).total_seconds())
        if seconds < 1:
            return None
        ttl = timedelta(seconds=seconds)
        try:
            url = self._storage.presigned_get(object_key, ttl=ttl)
        except EvidenceStorageError:
            return None
        return (
            AnalysisWorkerInputCapabilityV1(
                role=role,
                artifact_id=artifact_id,
                observed_sha256=observed_sha256,
                observed_size_bytes=observed_size_bytes,
                download_url=url,
                required_headers={},
                expires_at=signed_at + ttl,
            ),
            signed_at,
        )

    @staticmethod
    def _deadline(record: CalculationExecutionRecordV2) -> datetime:
        return record.authorization.authorized_at + timedelta(
            seconds=record.authorization.resource_envelope.max_deadline_seconds
        )


def _is_utc(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


__all__ = ["ExternalAnalysisS3InputCapabilityIssuer"]
