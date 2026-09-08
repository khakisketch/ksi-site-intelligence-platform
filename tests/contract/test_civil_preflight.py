"""REQ-INT-104 / INV-053 quantitative compatibility reason codes."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ksi_core.civil_preflight import (
    CivilPreflightReason,
    preflight_design_surface,
    preflight_epoch_pair,
)
from ksi_core.processing_jobs import ProcessingJobRecord
from ksi_event_contracts.design_surface import (
    KSI_LANDXML_TIN_PARSER_VERSION,
    DesignSurfaceSourceLineage,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from ksi_geo_spatial.tin_surface import CANONICAL_TIN_NORMALIZATION_PROFILE
from test_comparison_requests import _Fixture as ComparisonFixture
from test_design_conformance_requests import Fixture as DesignFixture


def _pair(tmp_path: Path) -> tuple[ProcessingJobRecord, ProcessingJobRecord]:
    fixture = ComparisonFixture(tmp_path)
    baseline = fixture.jobs.get(fixture.baseline_job_id)
    current = fixture.jobs.get(fixture.current_job_id)
    assert baseline is not None and current is not None
    return baseline, current


def _ready(_mission_id: str) -> tuple[bool, str | None]:
    return True, None


def test_analysis_readiness_is_a_typed_blocker(tmp_path: Path) -> None:
    baseline, current = _pair(tmp_path)
    result = preflight_epoch_pair(
        baseline,
        current,
        analysis_readiness=lambda _mission_id: (False, "quality gap"),
    )
    assert result.reason is CivilPreflightReason.ANALYSIS_NOT_READY


def test_legacy_unmanaged_profile_is_a_typed_blocker(tmp_path: Path) -> None:
    baseline, current = _pair(tmp_path)
    legacy = replace(
        baseline,
        spec=replace(
            baseline.spec,
            processing_profile_id=None,
            processing_profile_digest=None,
        ),
    )
    result = preflight_epoch_pair(legacy, current, analysis_readiness=_ready)
    assert result.reason is CivilPreflightReason.PROCESSING_PROFILE_UNKNOWN


def test_profile_digest_mismatch_is_a_typed_blocker(tmp_path: Path) -> None:
    baseline, current = _pair(tmp_path)
    changed = replace(
        current,
        spec=replace(
            current.spec,
            processing_profile_digest="sha256:" + "f" * 64,
        ),
    )
    result = preflight_epoch_pair(baseline, changed, analysis_readiness=_ready)
    assert result.reason is CivilPreflightReason.PROCESSING_PROFILE_MISMATCH


def test_disjoint_epoch_artifact_families_are_a_typed_blocker(tmp_path: Path) -> None:
    baseline, current = _pair(tmp_path)
    baseline_point_cloud = next(
        artifact
        for artifact in baseline.artifacts
        if artifact.kind is ProcessingArtifactKind.POINT_CLOUD
    )
    current_dsm = next(
        artifact
        for artifact in current.artifacts
        if artifact.kind is ProcessingArtifactKind.DSM
    )

    result = preflight_epoch_pair(
        replace(baseline, artifacts=(baseline_point_cloud,)),
        replace(current, artifacts=(current_dsm,)),
        analysis_readiness=_ready,
    )

    assert result.reason is CivilPreflightReason.NO_COMMON_ARTIFACT_FAMILY


def test_source_lineage_gap_is_a_typed_blocker(tmp_path: Path) -> None:
    baseline, current = _pair(tmp_path)
    first = baseline.artifacts[0]
    forged = first.model_copy(
        update={
            "lineage": first.lineage.model_copy(
                update={"source_digest": "sha256:" + "0" * 64}
            )
        }
    )
    changed = replace(baseline, artifacts=(forged, *baseline.artifacts[1:]))
    result = preflight_epoch_pair(changed, current, analysis_readiness=_ready)
    assert result.reason is CivilPreflightReason.SOURCE_LINEAGE_GAP


def test_crs_mismatch_is_a_typed_blocker(tmp_path: Path) -> None:
    baseline, current = _pair(tmp_path)
    artifacts = tuple(
        artifact.model_copy(update={"crs": "EPSG:5187"})
        if artifact.kind is ProcessingArtifactKind.DSM
        else artifact
        for artifact in current.artifacts
    )
    result = preflight_epoch_pair(
        baseline,
        replace(current, artifacts=artifacts),
        analysis_readiness=_ready,
    )
    assert result.reason is CivilPreflightReason.CRS_MISMATCH


def test_vertical_reference_mismatch_is_a_typed_blocker(tmp_path: Path) -> None:
    baseline, current = _pair(tmp_path)
    different = VerticalReference(
        datum=VerticalDatum.ORTHOMETRIC_KNGEOID2024,
        basis="independent orthometric fixture",
        source=VerticalReferenceSource.PIPELINE_DECLARED,
    )
    artifacts = tuple(
        artifact.model_copy(update={"vertical_reference": different})
        if artifact.kind is ProcessingArtifactKind.DSM
        else artifact
        for artifact in current.artifacts
    )
    result = preflight_epoch_pair(
        baseline,
        replace(current, artifacts=artifacts),
        analysis_readiness=_ready,
    )
    assert result.reason is CivilPreflightReason.VERTICAL_REFERENCE_MISMATCH


def test_unverified_design_surface_is_a_typed_blocker(tmp_path: Path) -> None:
    fixture = DesignFixture(tmp_path, seal_only=True)
    surface = fixture.surfaces.get(fixture.design_surface_id)
    assert surface is not None
    result = preflight_design_surface(surface)
    assert result.reason is CivilPreflightReason.DESIGN_SURFACE_NOT_VERIFIED


def test_landxml_lineage_mismatch_is_a_typed_blocker(tmp_path: Path) -> None:
    fixture = DesignFixture(tmp_path)
    surface = fixture.surfaces.get(fixture.design_surface_id)
    assert surface is not None
    # model_copy deliberately represents a journal tamper that the public
    # contract would never construct: LandXML without its immutable lineage.
    forged = surface.model_copy(
        update={"format": "landxml", "surface_selector": "Finished Grade"}
    )
    result = preflight_design_surface(forged)
    assert result.reason is CivilPreflightReason.DESIGN_NORMALIZATION_MISMATCH


def test_landxml_parser_version_mismatch_is_a_typed_blocker(tmp_path: Path) -> None:
    fixture = DesignFixture(tmp_path)
    surface = fixture.surfaces.get(fixture.design_surface_id)
    assert surface is not None and surface.observed is not None
    lineage = DesignSurfaceSourceLineage(
        source_sha256=surface.declared.sha256,
        surface_selector="Finished Grade",
        parser_version=KSI_LANDXML_TIN_PARSER_VERSION + "-tampered",
        normalization_profile=CANONICAL_TIN_NORMALIZATION_PROFILE,
        canonical_sha256=surface.observed.sha256,
    )
    forged = surface.model_copy(
        update={
            "format": "landxml",
            "surface_selector": "Finished Grade",
            "source_lineage": lineage,
        }
    )

    result = preflight_design_surface(forged)

    assert result.reason is CivilPreflightReason.DESIGN_NORMALIZATION_MISMATCH
