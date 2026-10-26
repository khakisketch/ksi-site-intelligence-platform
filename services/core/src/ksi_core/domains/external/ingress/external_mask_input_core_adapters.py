"""Genuine Core adapters for mask-child ingress (P2, additive).

``CoreMaskReconstructionAuthority`` resolves subjects and baseline-DSM anchors
against the REAL sealed reconstruction/inspection/WorkArea stores sharing one
currentness coordinator: ``resolve_sealed_subject`` for both subjects, exact
DSM manifest entry (kind ``dsm``) scoped to the sealed subject, the live
``public_snapshot`` inspection report with a MEASURED outcome for that exact
artifact SHA, and the ACTIVE WorkArea in the same site.  Nothing is trusted
from caller claims; a missing or mismatched record resolves to ``None`` and
the caller fails closed.

``CoreMaskProfileActivation`` pins the exact sealed narrow inspection profile
plus the independent masked profile digest, runtime digests, resource
envelope, organization, and designated worker, then verifies the real
purpose-separated extension activation (``MASKED_ANALYSIS_V3``) on every
check via :func:`is_quantitative_extension_current`.  An old V2 activation
shape (no purpose) can never satisfy it, and a caller-declared profile
digest that differs from the pin fails closed.  No test mode exists; tests
mint temporary keys explicitly labelled not-for-release.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ArtifactOutcome,
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_mask_input import MaskInspectionProfileV1
from ksi_event_contracts.external_mask_input_report import MaskObservationReportV1  # noqa: F401
from ksi_event_contracts.external_masked_execution import (
    MaskedExecutionRuntimeV3,
    masked_execution_runtime_digest,
)
from ksi_event_contracts.external_quantitative_extension_activation import (
    MASKED_ANALYSIS_PURPOSE,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

from ksi_core.domains.external.ingress.external_artifact_inspections import (
    ExternalArtifactInspectionStore,
)
from ksi_core.domains.external.ingress.external_mask_input_store import (
    BaselineDsmAnchor,
    MaskProfileActivationPort,
    MaskReconstructionAuthorityPort,
)
from ksi_core.domains.external.ingress.external_reconstruction import (
    ExternalReconstructionStore,
)
from ksi_core.domains.external.quantity.external_quantitative_extension_activation import (
    is_quantitative_extension_current,
)
from ksi_core.domains.sites.work_areas import WorkAreaStatus, WorkAreaStore
from ksi_core.foundation.currentness import ExternalAuthorityCurrentnessCoordinator
from ksi_core.identity.auth import Principal, PrincipalKind, principal_permissions


def _require_utc(now: datetime, description: str) -> None:
    if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
        raise ValueError(f"{description} requires a UTC-aware time")


_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _digest(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def masked_inspection_runtime_digest(profile: MaskInspectionProfileV1) -> str:
    """Closed 5-field contained-inspector binding plus the mask grammar digest.

    The exact inspector image that may observe mask bytes is the one the
    pinned inspection profile names; no other runtime can produce an accepted
    narrow report.
    """
    sealed = MaskInspectionProfileV1.model_validate(profile.model_dump(by_alias=True))
    if (
        sealed.inspection_profile_digest is None
        or sealed.inspection_profile_digest != sealed.canonical_digest()
    ):
        raise ValueError("inspection profile must be sealed")
    return _digest(
        {
            "workerExecutableDigest": sealed.worker_executable_digest,
            "workerBuildDigest": sealed.worker_build_digest,
            "runtimeImageVersion": sealed.runtime_image_version,
            "runtimeImageOciDigest": sealed.runtime_image_oci_digest,
            "dependencyLockDigest": sealed.dependency_lock_digest,
            "maskGrammarDigest": sealed.mask_grammar_digest,
        }
    )


def _transform_digest(
    transform: tuple[float, float, float, float, float, float],
) -> str:
    import hashlib as _hl

    from ksi_domain.canonical_json import canonical_json_bytes as _cjb

    return "sha256:" + _hl.sha256(_cjb({"transform": list(transform)})).hexdigest()


class CoreMaskReconstructionAuthority(MaskReconstructionAuthorityPort):
    """Real subject/anchor resolution over sealed Core reconstruction state."""

    label = "core-reconstruction-authority"

    def __init__(
        self,
        *,
        reconstruction: ExternalReconstructionStore,
        inspections: ExternalArtifactInspectionStore,
        work_areas: WorkAreaStore,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        if not isinstance(reconstruction, ExternalReconstructionStore):
            raise ValueError("mask authority requires the real reconstruction store")
        if not isinstance(inspections, ExternalArtifactInspectionStore):
            raise ValueError("mask authority requires the real inspection store")
        if not isinstance(work_areas, WorkAreaStore):
            raise ValueError("mask authority requires the real WorkArea store")
        shared = coordinator or reconstruction.coordinator
        for name, participant in (
            ("reconstruction", reconstruction),
            ("inspections", inspections),
            ("work areas", work_areas),
        ):
            if participant.coordinator is not shared:
                raise ValueError(f"mask authority {name} must share one coordinator")
        self._reconstruction = reconstruction
        self._inspections = inspections
        self._work_areas = work_areas
        self._coordinator = shared

    @property
    def coordinator(self) -> ExternalAuthorityCurrentnessCoordinator:
        return self._coordinator

    def is_subject_current(
        self,
        *,
        subject: SealedExternalSubjectV1,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        now: datetime,
    ) -> bool:
        _require_utc(now, "mask subject currentness")
        with self._coordinator.guarded_read():
            revision = self._reconstruction.resolve_sealed_subject(subject)
            if revision is None or revision.manifest is None:
                return False
            if (
                revision.submission.organization_id != organization_id
                or revision.submission.site_id != site_id
            ):
                return False
            area = self._work_areas.get(work_area_id)
            return not (
                area is None or area.site_id != site_id or area.status is not WorkAreaStatus.ACTIVE
            )

    def fetch_baseline_anchor(
        self,
        *,
        organization_id: str,
        site_id: str,
        work_area_id: str,
        baseline_subject: SealedExternalSubjectV1,
        dsm_artifact_id: str,
    ) -> BaselineDsmAnchor | None:
        with self._coordinator.guarded_read():
            revision = self._reconstruction.resolve_sealed_subject(baseline_subject)
            if revision is None or revision.manifest is None:
                return None
            if (
                revision.submission.organization_id != organization_id
                or revision.submission.site_id != site_id
            ):
                return None
            area = self._work_areas.get(work_area_id)
            if area is None or area.site_id != site_id or area.status is not WorkAreaStatus.ACTIVE:
                return None
            dsm_entries = [
                entry
                for entry in revision.manifest.entries
                if entry.kind is ProcessingArtifactKind.DSM and entry.artifact_id == dsm_artifact_id
            ]
            if len(dsm_entries) != 1:
                return None
            dsm = dsm_entries[0]
            snapshot = self._inspections.public_snapshot(baseline_subject)
            report = snapshot.report
            if report is None or report.report_digest is None:
                return None
            expected_sha = "sha256:" + dsm.observed_sha256
            outcome = next(
                (
                    item
                    for item in report.measurement_payload.outcomes
                    if item.artifact_id == dsm_artifact_id
                ),
                None,
            )
            if (
                outcome is None
                or outcome.outcome is not ArtifactOutcome.MEASURED
                or outcome.measurements is None
                or outcome.observed_sha256 != expected_sha
            ):
                return None
            measurements = outcome.measurements
            if measurements.width <= 0 or measurements.height <= 0:
                return None
            raw_transform = tuple(measurements.transform)
            if len(raw_transform) != 6:
                return None
            grid_transform: tuple[float, float, float, float, float, float] = (
                float(raw_transform[0]),
                float(raw_transform[1]),
                float(raw_transform[2]),
                float(raw_transform[3]),
                float(raw_transform[4]),
                float(raw_transform[5]),
            )
            return BaselineDsmAnchor(
                baseline_subject_digest=baseline_subject.canonical_digest(),
                dsm_artifact_id=dsm_artifact_id,
                rows=measurements.height,
                columns=measurements.width,
                observed_sha256=expected_sha,
                observed_size_bytes=dsm.observed_size_bytes,
                transform=grid_transform,
                transform_digest=_transform_digest(measurements.transform),
                crs_identifier=measurements.observed_crs_identifier,
                crs_digest=measurements.observed_crs_digest,
            )


class CoreMaskProfileActivation(MaskProfileActivationPort):
    """Real narrow-profile activation over the purpose-separated signed loader.

    The pinned inspection profile carries its own contained worker binding
    (the five runtime fields plus the mask grammar); the lane runtime digest
    additionally binds the independent masked execution worker, profile, and
    envelope.  The single activation authorizes exactly this lane runtime.
    """

    label = "core-mask-profile-activation"

    def __init__(
        self,
        *,
        activation_path: Path,
        verification_keys_path: Path,
        organization_id: str,
        pinned_profile: MaskInspectionProfileV1,
        pinned_masked_profile_digest: str,
        pinned_execution_runtime: MaskedExecutionRuntimeV3,
        pinned_envelope: ResourceEnvelopeV1,
        designated_worker: Principal,
        coordinator: ExternalAuthorityCurrentnessCoordinator | None = None,
    ) -> None:
        if not isinstance(activation_path, Path) or not isinstance(verification_keys_path, Path):
            raise ValueError("mask profile activation requires explicit file paths")
        if not organization_id:
            raise ValueError("mask profile activation requires an explicit organization")
        sealed_profile = MaskInspectionProfileV1.model_validate(
            pinned_profile.model_dump(by_alias=True)
        )
        if (
            sealed_profile.inspection_profile_digest is None
            or sealed_profile.inspection_profile_digest != sealed_profile.canonical_digest()
        ):
            raise ValueError("mask profile activation requires a sealed pinned profile")
        sealed_runtime = MaskedExecutionRuntimeV3.model_validate(
            pinned_execution_runtime.model_dump(by_alias=True)
        )
        if (
            sealed_runtime.runtime_digest is None
            or sealed_runtime.runtime_digest != sealed_runtime.canonical_digest()
        ):
            raise ValueError("mask profile activation requires a sealed pinned execution runtime")
        sealed_envelope = ResourceEnvelopeV1.model_validate(
            pinned_envelope.model_dump(by_alias=True)
        )
        if (
            sealed_envelope.resource_envelope_digest is None
            or sealed_envelope.resource_envelope_digest != sealed_envelope.canonical_digest()
        ):
            raise ValueError("mask profile activation requires a sealed pinned envelope")
        if _DIGEST_RE.fullmatch(pinned_masked_profile_digest) is None:
            raise ValueError("mask profile activation requires a valid masked profile digest")
        if (
            designated_worker.kind is not PrincipalKind.ANALYSIS_WORKER
            or designated_worker.organization_id != organization_id
        ):
            raise ValueError("mask profile activation requires the designated organization worker")
        _ = principal_permissions(designated_worker)
        self._activation_path = activation_path
        self._verification_keys_path = verification_keys_path
        self._organization_id = organization_id
        self._pinned_profile = sealed_profile.model_copy(deep=True)
        self._pinned_masked_profile_digest = pinned_masked_profile_digest
        self._pinned_execution_runtime = sealed_runtime.model_copy(deep=True)
        self._pinned_envelope = sealed_envelope.model_copy(deep=True)
        self._designated_worker = designated_worker
        self._coordinator = coordinator

    @property
    def designated_worker(self) -> Principal:
        """The designated organization worker this lane authorizes."""
        return self._designated_worker

    def _inspection_runtime_digest(self) -> str:
        # Closed 5-field contained-inspector binding from the pinned profile.
        return masked_inspection_runtime_digest(self._pinned_profile)

    def _lane_runtime_digest(self) -> str:
        # The single lane runtime the activation authorizes: exact new
        # execution worker plus masked profile, envelope, and inspection
        # profile digests.  Never a V2 runtime.
        return masked_execution_runtime_digest(
            self._pinned_execution_runtime,
            self._pinned_masked_profile_digest,
            self._pinned_envelope.canonical_digest(),
            self._pinned_profile.canonical_digest(),
        )

    def is_profile_active(
        self,
        *,
        profile_digest: str,
        resource_envelope_digest: str,
        contained_runtime_digest: str,
        inspector_build_digest: str,
        now: datetime,
    ) -> bool:
        if profile_digest != self._pinned_profile.canonical_digest():
            return False
        if resource_envelope_digest != self._pinned_envelope.canonical_digest():
            return False
        if contained_runtime_digest != self._inspection_runtime_digest():
            return False
        if inspector_build_digest != self._pinned_profile.worker_build_digest:
            return False
        return is_quantitative_extension_current(
            self._activation_path,
            self._verification_keys_path,
            organization_id=self._organization_id,
            purpose=MASKED_ANALYSIS_PURPOSE,
            policy_digest=self._pinned_masked_profile_digest,
            runtime_digest=self._lane_runtime_digest(),
            resource_envelope_digest=self._pinned_envelope.canonical_digest(),
            worker_principal=self._designated_worker,
            now=now,
            coordinator=self._coordinator,
        )


__all__ = [
    "CoreMaskProfileActivation",
    "CoreMaskReconstructionAuthority",
    "masked_inspection_runtime_digest",
]
