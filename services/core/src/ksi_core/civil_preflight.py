"""Fail-closed civil quantitative-comparison preflight (REQ-INT-104, INV-053).

The calculation workers still validate bytes at execution time.  This module
closes the earlier, cheaper boundary: Core must not create a quantitative
request when the two epochs are not known to be comparable.  Comparison and
design-conformance request stores call these pure functions, and the HTTP
preflight surface returns the same typed reason to the Dashboard.

Historical jobs remain readable.  A historical job without a versioned
processing profile is deliberately *not* upgraded from its old engine fields;
it is classified as ``LEGACY_UNMANAGED`` by ``ProcessingJobStore`` and is not a
candidate for a new quantitative result.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ksi_event_contracts.design_surface import (
    KSI_LANDXML_TIN_PARSER_VERSION,
    DesignSurface,
    DesignSurfaceStatus,
)
from ksi_event_contracts.processing_artifact import (
    ProcessingArtifact,
    ProcessingArtifactKind,
)
from ksi_geo_spatial.crs import normalise_crs
from ksi_geo_spatial.tin_surface import CANONICAL_TIN_NORMALIZATION_PROFILE

from ksi_core.processing_jobs import authoritative_artifacts

if TYPE_CHECKING:
    from ksi_core.processing_jobs import ProcessingJobRecord


class CivilPreflightReason(StrEnum):
    """Stable machine reasons exposed by every civil quantitative ingress."""

    ANALYSIS_NOT_READY = "ANALYSIS_NOT_READY"
    PROCESSING_PROFILE_UNKNOWN = "PROCESSING_PROFILE_UNKNOWN"
    PROCESSING_PROFILE_MISMATCH = "PROCESSING_PROFILE_MISMATCH"
    NO_COMMON_ARTIFACT_FAMILY = "NO_COMMON_ARTIFACT_FAMILY"
    SOURCE_LINEAGE_GAP = "SOURCE_LINEAGE_GAP"
    CRS_MISMATCH = "CRS_MISMATCH"
    VERTICAL_REFERENCE_MISMATCH = "VERTICAL_REFERENCE_MISMATCH"
    DESIGN_SURFACE_NOT_VERIFIED = "DESIGN_SURFACE_NOT_VERIFIED"
    DESIGN_NORMALIZATION_MISMATCH = "DESIGN_NORMALIZATION_MISMATCH"


@dataclass(frozen=True, slots=True)
class CivilPreflightResult:
    """One deterministic allow/block decision.

    Only the first blocker is returned.  The check order is stable and follows
    the remediation dependency: readiness, profile, source lineage, horizontal
    frame, then vertical frame.  Showing downstream failures before their
    inputs are trustworthy would send an operator to fix the wrong thing.
    """

    compatible: bool
    reason: CivilPreflightReason | None = None
    detail: str | None = None

    @classmethod
    def allowed(cls) -> CivilPreflightResult:
        return cls(compatible=True)

    @classmethod
    def blocked(cls, reason: CivilPreflightReason, detail: str) -> CivilPreflightResult:
        return cls(compatible=False, reason=reason, detail=detail)


# The callback is injected by Core assembly so the comparison store does not
# reach into WorkOrder/Coverage/Quality journals by itself.
AnalysisReadinessCheck = Callable[[str], tuple[bool, str | None]]

# GeoTIFF ingress is already canonical raster data, so it has no TIN parser
# profile.  It still needs a named normalization basis to prevent progress
# code from treating an absent value as implicit compatibility.
DIRECT_GEOTIFF_NORMALIZATION_PROFILE = "ksi-direct-geotiff-v1"


def _enum_value(value: object) -> str | None:
    raw = getattr(value, "value", value)
    return raw if isinstance(raw, str) else None


def _profile(job: ProcessingJobRecord) -> tuple[str, str] | None:
    classification = _enum_value(getattr(job, "processing_profile_classification", None))
    profile_id = getattr(job, "processing_profile_id", None)
    profile_digest = getattr(job, "processing_profile_digest", None)
    if (
        classification != "VERSIONED"
        or not isinstance(profile_id, str)
        or not profile_id
        or not isinstance(profile_digest, str)
        or not profile_digest.startswith("sha256:")
    ):
        return None
    return profile_id, profile_digest


def _lineage_is_complete(job: ProcessingJobRecord, artifacts: Iterable[ProcessingArtifact]) -> bool:
    source_digest = getattr(job.input, "source_bundle_digest", None)
    if not isinstance(source_digest, str) or not source_digest.startswith("sha256:"):
        return False
    # Core writes every artifact lineage from the job's sealed input.  A gap or
    # mismatch means the output cannot be proven to belong to this epoch.
    return all(artifact.lineage.source_digest == source_digest for artifact in artifacts)


def _artifact(job: ProcessingJobRecord, kind: ProcessingArtifactKind) -> ProcessingArtifact | None:
    return next((item for item in authoritative_artifacts(job) if item.kind is kind), None)


def common_comparable_artifact_families(
    baseline: ProcessingJobRecord,
    current: ProcessingJobRecord,
) -> frozenset[ProcessingArtifactKind]:
    """Return quantitative families with authoritative artifacts in both epochs."""

    comparable = {
        ProcessingArtifactKind.POINT_CLOUD,
        ProcessingArtifactKind.DSM,
    }
    baseline_kinds = {artifact.kind for artifact in authoritative_artifacts(baseline)}
    current_kinds = {artifact.kind for artifact in authoritative_artifacts(current)}
    return frozenset(comparable & baseline_kinds & current_kinds)


def _same_crs(left: str | None, right: str | None) -> bool:
    if left is None or right is None:
        return False
    try:
        return normalise_crs(left) == normalise_crs(right)
    except ValueError:
        return False


def preflight_single_epoch(
    job: ProcessingJobRecord,
    *,
    analysis_readiness: AnalysisReadinessCheck | None,
    artifacts: Iterable[ProcessingArtifact] | None = None,
) -> CivilPreflightResult:
    """Validate one epoch before it participates in a quantitative result."""

    if analysis_readiness is None:
        return CivilPreflightResult.blocked(
            CivilPreflightReason.ANALYSIS_NOT_READY,
            "Analysis Readiness projection이 조립되지 않아 분석 가능 여부를 확인할 수 없다",
        )
    try:
        ready, readiness_detail = analysis_readiness(job.mission_id)
    except Exception:  # pragma: no cover - defensive adapter boundary
        ready, readiness_detail = False, "Analysis Readiness 조회에 실패했다"
    if not ready:
        return CivilPreflightResult.blocked(
            CivilPreflightReason.ANALYSIS_NOT_READY,
            readiness_detail or f"임무 {job.mission_id!r} 의 Analysis Readiness가 READY가 아니다",
        )

    if _profile(job) is None:
        return CivilPreflightResult.blocked(
            CivilPreflightReason.PROCESSING_PROFILE_UNKNOWN,
            "처리 프로필 ID와 canonical digest가 원장에 고정되지 않은 epoch다. "
            "LEGACY_UNMANAGED 결과는 조회할 수 있지만 새 정량 비교에는 쓸 수 없다",
        )

    relevant = tuple(authoritative_artifacts(job) if artifacts is None else artifacts)
    if not relevant or not _lineage_is_complete(job, relevant):
        return CivilPreflightResult.blocked(
            CivilPreflightReason.SOURCE_LINEAGE_GAP,
            "처리 산출물과 봉인된 원본 번들의 digest 계보가 완전하게 결속되지 않았다",
        )
    return CivilPreflightResult.allowed()


def preflight_epoch_pair(
    baseline: ProcessingJobRecord,
    current: ProcessingJobRecord,
    *,
    analysis_readiness: AnalysisReadinessCheck | None,
) -> CivilPreflightResult:
    """Require two epochs to share one reproducible quantitative basis."""

    for label, job in (("baseline", baseline), ("current", current)):
        result = preflight_single_epoch(job, analysis_readiness=analysis_readiness)
        if not result.compatible:
            detail = result.detail or "비교 가능성 근거가 없다"
            return CivilPreflightResult.blocked(
                result.reason or CivilPreflightReason.SOURCE_LINEAGE_GAP,
                f"{label} epoch: {detail}",
            )

    baseline_profile = _profile(baseline)
    current_profile = _profile(current)
    # The single-epoch checks above guarantee both values, but retain the
    # branch so this pure function stays fail-closed if its helpers change.
    if baseline_profile is None or current_profile is None:
        return CivilPreflightResult.blocked(
            CivilPreflightReason.PROCESSING_PROFILE_UNKNOWN,
            "두 epoch 중 처리 프로필이 원장에 고정되지 않은 항목이 있다",
        )
    if baseline_profile[1] != current_profile[1]:
        return CivilPreflightResult.blocked(
            CivilPreflightReason.PROCESSING_PROFILE_MISMATCH,
            "두 epoch의 processingProfileDigest가 다르다. v1은 동일 digest만 자동 비교한다",
        )

    if not common_comparable_artifact_families(baseline, current):
        return CivilPreflightResult.blocked(
            CivilPreflightReason.NO_COMMON_ARTIFACT_FAMILY,
            "두 epoch에 공통으로 존재하는 point_cloud 또는 dsm 산출물 계열이 없다",
        )

    for kind, label in (
        (ProcessingArtifactKind.POINT_CLOUD, "point_cloud"),
        (ProcessingArtifactKind.DSM, "dsm"),
    ):
        left = _artifact(baseline, kind)
        right = _artifact(current, kind)
        # Missing pairs are handled by the request's existing eligibility
        # logic.  Here we only reject a pair that would otherwise be used.
        if left is not None and right is not None and not _same_crs(left.crs, right.crs):
            return CivilPreflightResult.blocked(
                CivilPreflightReason.CRS_MISMATCH,
                f"{label} 산출물의 CRS가 다르거나 해석할 수 없다 "
                f"(baseline={left.crs!r}, current={right.crs!r})",
            )

    baseline_dsm = _artifact(baseline, ProcessingArtifactKind.DSM)
    current_dsm = _artifact(current, ProcessingArtifactKind.DSM)
    if (
        baseline_dsm is not None
        and current_dsm is not None
        and (
            baseline_dsm.vertical_reference is None
            or current_dsm.vertical_reference is None
            or baseline_dsm.vertical_reference != current_dsm.vertical_reference
        )
    ):
        return CivilPreflightResult.blocked(
            CivilPreflightReason.VERTICAL_REFERENCE_MISMATCH,
            "두 DSM의 수직기준이 미상이거나 서로 다르다. 기준을 추정해 채우지 않는다",
        )

    return CivilPreflightResult.allowed()


def preflight_design_surface(surface: DesignSurface) -> CivilPreflightResult:
    """Validate the canonical design raster and, for LandXML, its derivation."""

    if surface.status is not DesignSurfaceStatus.VERIFIED or surface.observed is None:
        return CivilPreflightResult.blocked(
            CivilPreflightReason.DESIGN_SURFACE_NOT_VERIFIED,
            "설계면이 VERIFIED가 아니거나 canonical GeoTIFF 관측 근거가 없다",
        )
    if surface.format == "landxml":
        lineage = surface.source_lineage
        if (
            lineage is None
            or lineage.source_sha256 != surface.declared.sha256
            or lineage.surface_selector != surface.surface_selector
            or lineage.parser_version != KSI_LANDXML_TIN_PARSER_VERSION
            or lineage.normalization_profile != CANONICAL_TIN_NORMALIZATION_PROFILE
            or lineage.canonical_sha256 != surface.observed.sha256
        ):
            return CivilPreflightResult.blocked(
                CivilPreflightReason.DESIGN_NORMALIZATION_MISMATCH,
                "LandXML 원본·Surface selector·파서 버전·0.5m 정규화 프로필·"
                "canonical GeoTIFF digest 계보가 현재 표준과 일치하지 않는다",
            )
    return CivilPreflightResult.allowed()


def design_normalization_anchor(surface: DesignSurface) -> tuple[str, str, str]:
    """Return ``(revision, normalization profile, canonical digest)``.

    Callers must run :func:`preflight_design_surface` first.  The function is
    intentionally total for both supported ingress formats so a quantitative
    request never records ``None`` and later guesses what it meant.
    """

    if surface.observed is None:
        raise ValueError("canonical design surface observation is required")
    if surface.format == "landxml":
        if surface.source_lineage is None:
            raise ValueError("LandXML design surface lineage is required")
        profile = surface.source_lineage.normalization_profile
    else:
        profile = DIRECT_GEOTIFF_NORMALIZATION_PROFILE
    return surface.revision, profile, surface.observed.sha256


__all__ = [
    "AnalysisReadinessCheck",
    "CivilPreflightReason",
    "CivilPreflightResult",
    "DIRECT_GEOTIFF_NORMALIZATION_PROFILE",
    "common_comparable_artifact_families",
    "design_normalization_anchor",
    "preflight_epoch_pair",
    "preflight_design_surface",
    "preflight_single_epoch",
]
