"""V3 masked-volume result contracts and the contained measurement primitive."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import rasterio
from jsonschema import Draft202012Validator
from ksi_change_detection.dsm_diff import DiffResult
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ObservedVerticalReferenceV1,
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_masked_volume import (
    ExclusionMaskBindingV1,
    MaskedCalculationIdentityV3,
    MaskedRelativeVolumeProfileV3,
)
from ksi_event_contracts.external_masked_volume_result import (
    MaskedVolumeCalculationFailureV3,
    masked_volume_calculation_report_wire_dict,
    masked_volume_numeric_result_wire_dict,
)
from ksi_event_contracts.external_relative_volume_analysis import (
    AnalysisPolicyV2,
    CalculationIdentityV2,
)
from ksi_event_contracts.external_relative_volume_calculation import RelativeVolumeMetricsV2
from ksi_processing_controller.external_masked_volume_measurement import (
    MaskedVolumeMeasuredV3,
    MaskedVolumeMeasurementError,
    measure_masked_volume_v3,
    measure_masked_volume_v3_from_diff,
)
from ksi_processing_controller.external_measurement_algorithms import MeasurementWatchdogV2
from pyproj import CRS
from rasterio.transform import Affine, from_origin

_ORIGIN_X = 200_000.0
_ORIGIN_Y = 550_000.0
_NATIVE_TRANSFORM = (1.0, 0.0, _ORIGIN_X, 0.0, -1.0, _ORIGIN_Y)
_COMPOUND_CRS = CRS.from_user_input("EPSG:5186+5773")


def _digest(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical_digest(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _subject(label: str) -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="order-" + label,
        submission_id="submission-" + label,
        revision=1,
        submission_digest=_digest("submission-" + label),
        manifest_digest=_digest("manifest-" + label),
    )


def _full_polygon() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [_ORIGIN_X, _ORIGIN_Y],
                [_ORIGIN_X, _ORIGIN_Y - 4.0],
                [_ORIGIN_X + 4.0, _ORIGIN_Y - 4.0],
                [_ORIGIN_X + 4.0, _ORIGIN_Y],
                [_ORIGIN_X, _ORIGIN_Y],
            ]
        ],
    }


def _holed_polygon() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [_ORIGIN_X, _ORIGIN_Y],
                [_ORIGIN_X, _ORIGIN_Y - 4.0],
                [_ORIGIN_X + 4.0, _ORIGIN_Y - 4.0],
                [_ORIGIN_X + 4.0, _ORIGIN_Y],
                [_ORIGIN_X, _ORIGIN_Y],
            ],
            [
                [_ORIGIN_X + 1.0, _ORIGIN_Y - 1.0],
                [_ORIGIN_X + 3.0, _ORIGIN_Y - 1.0],
                [_ORIGIN_X + 3.0, _ORIGIN_Y - 3.0],
                [_ORIGIN_X + 1.0, _ORIGIN_Y - 3.0],
                [_ORIGIN_X + 1.0, _ORIGIN_Y - 1.0],
            ],
        ],
    }


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=4_000_000,
        max_streamed_bytes=4_000_000,
        max_tiff_directories=8,
        max_tiff_entries=128,
        max_pixels=1_000_000,
        max_bands=4,
        max_blocks=512,
        max_decompressed_bytes=20_000_000,
        max_sample_bytes=4_000_000,
        max_geometry_vertices=64,
        max_cpu_seconds=30.0,
        max_memory_bytes=50_000_000,
        max_workspace_bytes=50_000_000,
        max_output_bytes=1_000_000,
        max_tenant_concurrency=2,
        max_queue_depth=4,
        max_deadline_seconds=60.0,
        lease_duration_seconds=10.0,
        max_retry_attempts=2,
    ).sealed()


def _watchdog(envelope: ResourceEnvelopeV1) -> MeasurementWatchdogV2:
    return MeasurementWatchdogV2.from_envelope(envelope)


def _v2_policy() -> AnalysisPolicyV2:
    return AnalysisPolicyV2(
        policy_id="relative-volume-v2",
        version=2,
        profile_id="KSI-GIS-RELATIVE-VOLUME-V2",
        profile_digest=_digest("profile"),
        algorithm_digest=_digest("algorithm"),
        config_digest=_digest("config"),
        baseline_grid_rule="BASELINE_NATIVE_NORTH_UP_AFFINE_V1",
        current_elevation_resampling="BILINEAR",
        current_mask_resampling="NEAREST",
        work_area_rasterization="CELL_CENTER",
        minimum_common_valid_fraction=1.0,
        threshold_m=0.0,
        cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
        delta_rule="CURRENT_MINUS_BASELINE",
        uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
    ).sealed()


def _v2_identity(
    polygon: dict[str, object],
    *,
    baseline_sha: str,
    current_sha: str,
    baseline_size: int = 1,
    current_size: int = 1,
) -> CalculationIdentityV2:
    vertical = ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")
    horizontal_wkt = CRS.from_epsg(5186).to_wkt(
        version="WKT2_2019", pretty=False, output_axis_rule=True
    )
    horizontal_digest = _digest(horizontal_wkt)
    return CalculationIdentityV2(
        calculation_id="calculation-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        work_area_polygon=polygon,
        work_area_crs="EPSG:5186",
        work_area_definition_digest=_canonical_digest(
            {"workAreaId": "work-area-a", "crs": "EPSG:5186", "polygon": polygon}
        ),
        baseline_subject=_subject("baseline"),
        current_subject=_subject("current"),
        baseline_capture_started_at=datetime(2026, 9, 19, tzinfo=UTC),
        baseline_capture_ended_at=datetime(2026, 9, 19, 1, tzinfo=UTC),
        current_capture_started_at=datetime(2026, 9, 20, tzinfo=UTC),
        current_capture_ended_at=datetime(2026, 9, 20, 1, tzinfo=UTC),
        baseline_dsm_artifact_id="dsm-baseline",
        current_dsm_artifact_id="dsm-current",
        baseline_input_digest=_digest("baseline-input"),
        current_input_digest=_digest("current-input"),
        baseline_dsm_observed_sha256=baseline_sha,
        current_dsm_observed_sha256=current_sha,
        baseline_dsm_observed_size_bytes=baseline_size,
        current_dsm_observed_size_bytes=current_size,
        baseline_observed_crs_identifier="EPSG:5186",
        current_observed_crs_identifier="EPSG:5186",
        baseline_observed_crs_digest=horizontal_digest,
        current_observed_crs_digest=horizontal_digest,
        baseline_projected_unit="metre",
        current_projected_unit="metre",
        baseline_vertical_reference=vertical,
        current_vertical_reference=vertical,
        baseline_vertical_reference_digest=vertical.canonical_digest(),
        current_vertical_reference_digest=vertical.canonical_digest(),
        baseline_vertical_unit="metre",
        current_vertical_unit="metre",
        baseline_vertical_unit_provenance="OBSERVED_VERTICAL_CRS_AXIS",
        current_vertical_unit_provenance="OBSERVED_VERTICAL_CRS_AXIS",
        baseline_inspection_report_digest=_digest("baseline-report"),
        current_inspection_report_digest=_digest("current-report"),
        baseline_inspection_policy_digest=_digest("baseline-inspection-policy"),
        current_inspection_policy_digest=_digest("current-inspection-policy"),
        baseline_inspector_build_digest=_digest("baseline-inspector"),
        current_inspector_build_digest=_digest("current-inspector"),
        baseline_transform_digest=_canonical_digest({"transform": list(_NATIVE_TRANSFORM)}),
        current_transform_digest=_canonical_digest({"transform": list(_NATIVE_TRANSFORM)}),
        baseline_transform=_NATIVE_TRANSFORM,
        current_transform=_NATIVE_TRANSFORM,
        horizontal_crs_digest=horizontal_digest,
        vertical_reference_digest=vertical.canonical_digest(),
        policy=_v2_policy(),
        worker_executable_digest=_digest("worker"),
        worker_build_digest=_digest("build"),
        runtime_image_version="2.0.0",
        runtime_image_oci_digest=_digest("oci"),
        dependency_lock_digest=_digest("lock"),
    ).sealed()


def _mask_binding(*, observed_sha256: str, observed_size_bytes: int) -> ExclusionMaskBindingV1:
    left, bottom = _ORIGIN_X, _ORIGIN_Y - 4.0
    right, top = _ORIGIN_X + 4.0, _ORIGIN_Y
    return ExclusionMaskBindingV1(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        subject=_subject("mask"),
        mask_artifact_id="mask-artifact-1",
        observed_sha256=observed_sha256,
        observed_size_bytes=observed_size_bytes,
        observed_inspection_report_digest=_digest("mask-report"),
        rows=4,
        columns=4,
        transform=_NATIVE_TRANSFORM,
        transform_digest=_canonical_digest({"transform": list(_NATIVE_TRANSFORM)}),
        observed_crs_identifier="EPSG:5186",
        observed_crs_digest=_digest(
            CRS.from_epsg(5186).to_wkt(version="WKT2_2019", pretty=False, output_axis_rule=True)
        ),
        dtype="UINT8",
        band_count=1,
        retain_value=0,
        exclude_value=1,
        nodata_representation="NONE",
        bounds=(left, bottom, right, top),
    ).sealed()


def _masked_identity(
    polygon: dict[str, object],
    *,
    baseline_sha: str,
    current_sha: str,
    mask_sha: str,
    mask_size: int = 1,
) -> MaskedCalculationIdentityV3:
    from ksi_event_contracts.external_masked_volume import MaskedCalculationIdentityV3

    source = _v2_identity(polygon, baseline_sha=baseline_sha, current_sha=current_sha)
    mask = _mask_binding(observed_sha256=mask_sha, observed_size_bytes=mask_size)
    profile = MaskedRelativeVolumeProfileV3(
        policy_id="masked-relative-volume-v3",
        version=3,
        profile_id="KSI-GIS-MASKED-RELATIVE-VOLUME-V3",
        profile_digest=_digest("masked-profile"),
        algorithm_digest=_digest("masked-algorithm"),
        config_digest=_digest("masked-config"),
        baseline_grid_rule="EXACT_BASELINE_GRID",
        current_elevation_resampling="BILINEAR",
        current_mask_resampling="NEAREST",
        work_area_rasterization="CELL_CENTER",
        exclusion_precedence="WORKAREA_HOLES_THEN_MASK",
        mask_convention="UINT8_SINGLE_BAND_BINARY_0_KEEP_1_EXCLUDE_V1",
        mask_nodata_rule="NO_NODATA",
        minimum_common_valid_fraction=1.0,
        threshold_m=0.0,
        cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
        delta_rule="CURRENT_MINUS_BASELINE",
        uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
    ).sealed()
    return MaskedCalculationIdentityV3(
        masked_calculation_id="masked-calculation-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        source_calculation_identity=source,
        source_calculation_identity_digest=source.canonical_digest(),
        mask_binding=mask,
        mask_binding_digest=mask.canonical_digest(),
        profile=profile,
        masked_profile_digest=profile.canonical_digest(),
        grid_rows=4,
        grid_columns=4,
        horizontal_crs_digest=mask.observed_crs_digest,
    ).sealed()


def _known_diff(*, invalid: tuple[int, int] | None = None) -> DiffResult:
    """Hand-derived 4x4 diff: fill +1 on three cells, cut -2 on one cell."""
    delta = np.zeros((4, 4), dtype=np.float64)
    delta[0, 1] = 1.0
    delta[1, 0] = 1.0
    delta[1, 1] = 1.0
    delta[2, 2] = -2.0
    valid = np.ones((4, 4), dtype=np.bool_)
    if invalid is not None:
        valid[invalid] = False
    return DiffResult(
        diff_m=delta,
        valid=valid,
        transform=Affine(*_NATIVE_TRANSFORM),
        crs="EPSG:5186",
        cell_area_m2=1.0,
    )


def _known_mask() -> np.ndarray:
    mask = np.zeros((4, 4), dtype=np.uint8)
    mask[0, 1] = 1  # exclude one +1 fill cell
    return mask


def _measure_from_diff(
    diff: DiffResult,
    mask: np.ndarray,
    identity: MaskedCalculationIdentityV3,
    envelope: ResourceEnvelopeV1,
    *,
    report_id: str = "report-1",
) -> object:
    return measure_masked_volume_v3_from_diff(
        masked_identity=identity,
        diff=diff,
        exclusion_mask=mask,
        mask_crs="EPSG:5186",
        mask_transform=Affine(*_NATIVE_TRANSFORM),
        envelope=envelope,
        watchdog=_watchdog(envelope),
        lease_expires_at=datetime(2026, 9, 22, tzinfo=UTC),
        report_id=report_id,
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )


def test_known_answer_masked_numbers_and_impact() -> None:
    """Masked fill 2 / cut 2 / net 0; unmasked fill 3 / cut 2 / net 1; excluded fill 1."""
    envelope = _envelope()
    identity = _masked_identity(
        _full_polygon(),
        baseline_sha=_digest("b"),
        current_sha=_digest("c"),
        mask_sha=_digest("m"),
    )
    diff, mask = _known_diff(), _known_mask()
    diff_bytes, mask_bytes = diff.diff_m.tobytes(), mask.tobytes()
    outcome = _measure_from_diff(diff, mask, identity, envelope)
    assert isinstance(outcome, MaskedVolumeMeasuredV3)
    numeric = outcome.report.numeric_result
    assert (
        numeric.metrics.fill_m3,
        numeric.metrics.cut_m3,
        numeric.metrics.net_m3,
    ) == (2.0, 2.0, 0.0)
    assert numeric.impact.unmasked_impact_known is True
    assert (
        numeric.impact.unmasked_fill_m3,
        numeric.impact.unmasked_cut_m3,
        numeric.impact.unmasked_net_m3,
    ) == (3.0, 2.0, 1.0)
    assert (
        numeric.impact.excluded_fill_m3,
        numeric.impact.excluded_cut_m3,
        numeric.impact.excluded_net_m3,
    ) == (1.0, 0.0, 1.0)
    coverage = numeric.coverage
    assert (
        coverage.original_selected_cell_count,
        coverage.mask_excluded_cell_count,
        coverage.effective_selected_cell_count,
        coverage.common_valid_cell_count,
        coverage.unavailable_cell_count,
    ) == (16, 1, 15, 15, 0)
    assert coverage.original_selected_area_m2 == 16.0
    assert coverage.effective_selected_area_m2 == 15.0
    # Cropped delta grid carries NaN on the excluded cell, never an invented zero.
    assert outcome.delta_grid_m.shape == (4, 4)
    assert bool(np.isnan(outcome.delta_grid_m[0, 1]))
    assert outcome.delta_grid_m[1, 1] == 1.0
    assert diff.diff_m.tobytes() == diff_bytes and mask.tobytes() == mask_bytes


def test_holes_exclude_first_and_source_nodata_fails_closed() -> None:
    """Hole cells never enter the original zone; missing source is not mask-excluded."""
    envelope = _envelope()
    identity = _masked_identity(
        _holed_polygon(),
        baseline_sha=_digest("b"),
        current_sha=_digest("c"),
        mask_sha=_digest("m"),
    )
    outcome = _measure_from_diff(_known_diff(), _known_mask(), identity, envelope)
    assert isinstance(outcome, MaskedVolumeMeasuredV3)
    coverage = outcome.report.numeric_result.coverage
    # 4x4 grid minus 4 hole cells; mask excludes one of the remaining 12.
    assert coverage.original_selected_cell_count == 12
    assert coverage.effective_selected_cell_count == 11
    assert coverage.common_valid_cell_count == 11

    bad = _measure_from_diff(
        _known_diff(invalid=(1, 0)), _known_mask(), identity, envelope, report_id="report-2"
    )
    assert isinstance(bad, MaskedVolumeCalculationFailureV3)
    assert bad.reason_code == "MASKED_INSUFFICIENT_COMMON_VALID"


def test_source_nodata_inside_excluded_region_yields_unknown_impact() -> None:
    """Original zone missing values make the full unmasked impact UNKNOWN (null, never 0)."""
    envelope = _envelope()
    identity = _masked_identity(
        _full_polygon(),
        baseline_sha=_digest("b"),
        current_sha=_digest("c"),
        mask_sha=_digest("m"),
    )
    outcome = _measure_from_diff(_known_diff(invalid=(0, 1)), _known_mask(), identity, envelope)
    assert isinstance(outcome, MaskedVolumeMeasuredV3)
    impact = outcome.report.numeric_result.impact
    assert impact.unmasked_impact_known is False
    assert impact.unmasked_cut_m3 is None and impact.excluded_fill_m3 is None
    # Masked numbers still derive from the fully valid effective zone.
    assert outcome.report.numeric_result.metrics.fill_m3 == 2.0


def test_mask_values_rejected_and_padding_rejected() -> None:
    envelope = _envelope()
    identity = _masked_identity(
        _full_polygon(),
        baseline_sha=_digest("b"),
        current_sha=_digest("c"),
        mask_sha=_digest("m"),
    )
    illegal = _known_mask()
    illegal[3, 3] = 2
    outcome = _measure_from_diff(_known_diff(), illegal, identity, envelope)
    assert isinstance(outcome, MaskedVolumeCalculationFailureV3)
    assert outcome.reason_code == "MASKED_INPUT_MISMATCH"

    numeric = _measure_from_diff(_known_diff(), _known_mask(), identity, envelope)
    assert isinstance(numeric, MaskedVolumeMeasuredV3)
    from ksi_event_contracts.external_masked_volume_result import MaskedCoverageWitnessV3

    padded = numeric.report.numeric_result.coverage.model_dump(by_alias=True)
    padded.update(
        {
            "rows": 4,
            "columns": 3,
            "originalSelectedMaskB64": "//8=",  # 0xFF 0xFF: low 4 padding bits set
            "maskExcludedMaskB64": "AAA=",
            "effectiveSelectedMaskB64": "//8=",
            "commonValidMaskB64": "//8=",
            "unavailableMaskB64": "AAA=",
            "originalSelectedCellCount": 12,
            "maskExcludedCellCount": 0,
            "effectiveSelectedCellCount": 12,
            "commonValidCellCount": 12,
            "unavailableCellCount": 0,
            "coverageWitnessDigest": None,
        }
    )
    with pytest.raises(ValueError, match="padding"):
        MaskedCoverageWitnessV3.model_validate(padded)


def test_exact_digest_replay_and_cross_scope_mismatch() -> None:
    envelope = _envelope()
    identity = _masked_identity(
        _full_polygon(),
        baseline_sha=_digest("b"),
        current_sha=_digest("c"),
        mask_sha=_digest("m"),
    )
    first = _measure_from_diff(_known_diff(), _known_mask(), identity, envelope)
    second = _measure_from_diff(_known_diff(), _known_mask(), identity, envelope)
    assert isinstance(first, MaskedVolumeMeasuredV3) and isinstance(second, MaskedVolumeMeasuredV3)
    assert first.report.report_digest == second.report.report_digest
    assert first.report.numeric_result.canonical_digest() == (
        second.report.numeric_result.canonical_digest()
    )

    tampered = identity.model_dump(by_alias=True)
    tampered["maskedCalculationIdentityDigest"] = _digest("other")
    with pytest.raises(ValueError, match="masked identity digest"):
        MaskedCalculationIdentityV3.model_validate(tampered)

    # A sealed identity with a wrong mask sha stays sealed; the byte-level
    # mismatch is proven by the file-backed path (see the sha-mismatch check
    # below) and by grid/CRS binding mismatches here.
    mismatch = measure_masked_volume_v3_from_diff(
        masked_identity=identity,
        diff=_known_diff(),
        exclusion_mask=_known_mask(),
        mask_crs="EPSG:5187",
        mask_transform=Affine(*_NATIVE_TRANSFORM),
        envelope=envelope,
        watchdog=_watchdog(envelope),
        lease_expires_at=datetime(2026, 9, 22, tzinfo=UTC),
        report_id="report-x",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    assert isinstance(mismatch, MaskedVolumeCalculationFailureV3)


def test_stale_lease_and_cancel_fail_closed() -> None:
    from ksi_processing_controller.external_measurement_algorithms import (
        MeasurementAlgorithmIncomplete,
    )

    envelope = _envelope()
    identity = _masked_identity(
        _full_polygon(),
        baseline_sha=_digest("b"),
        current_sha=_digest("c"),
        mask_sha=_digest("m"),
    )
    stale = measure_masked_volume_v3_from_diff(
        masked_identity=identity,
        diff=_known_diff(),
        exclusion_mask=_known_mask(),
        mask_crs="EPSG:5186",
        mask_transform=Affine(*_NATIVE_TRANSFORM),
        envelope=envelope,
        watchdog=_watchdog(envelope),
        lease_expires_at=datetime(2026, 9, 20, tzinfo=UTC),
        report_id="report-stale",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    assert isinstance(stale, MaskedVolumeCalculationFailureV3)
    assert stale.reason_code == "STALE_LEASE"

    with pytest.raises(MeasurementAlgorithmIncomplete):
        measure_masked_volume_v3_from_diff(
            masked_identity=identity,
            diff=_known_diff(),
            exclusion_mask=_known_mask(),
            mask_crs="EPSG:5186",
            mask_transform=Affine(*_NATIVE_TRANSFORM),
            envelope=envelope,
            watchdog=MeasurementWatchdogV2.from_envelope(envelope, is_cancelled=lambda: True),
            lease_expires_at=datetime(2026, 9, 22, tzinfo=UTC),
            report_id="report-cancel",
            computed_at=datetime(2026, 9, 21, tzinfo=UTC),
            reported_at=datetime(2026, 9, 21, tzinfo=UTC),
        )


def test_file_backed_measurement_binds_actual_bytes_and_rejects_mask_nodata(
    tmp_path: Path,
) -> None:
    """Real local TIFFs: DSM bytes + uint8 mask bind the sealed identity; nodata mask rejected."""
    baseline_values = np.full((4, 4), 100.0)
    current_values = baseline_values + _known_diff().diff_m
    transform = from_origin(_ORIGIN_X, _ORIGIN_Y, 1.0, 1.0)
    baseline_path = tmp_path / "baseline.tif"
    current_path = tmp_path / "current.tif"
    mask_path = tmp_path / "mask.tif"
    with rasterio.open(
        baseline_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float64",
        crs=_COMPOUND_CRS,
        transform=transform,
    ) as dataset:
        dataset.write(baseline_values, 1)
    with rasterio.open(
        current_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float64",
        crs=_COMPOUND_CRS,
        transform=transform,
    ) as dataset:
        dataset.write(current_values, 1)
    with rasterio.open(
        mask_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint8",
        crs="EPSG:5186",
        transform=transform,
    ) as dataset:
        dataset.write(_known_mask(), 1)

    envelope = _envelope()
    identity = _masked_identity(
        _full_polygon(),
        baseline_sha=_digest(baseline_path.read_bytes()),
        current_sha=_digest(current_path.read_bytes()),
        mask_sha=_digest(mask_path.read_bytes()),
        mask_size=mask_path.stat().st_size,
    )
    # Patch DSM sizes into a re-sealed identity bound to actual byte sizes.
    source_payload = identity.source_calculation_identity.model_dump(by_alias=True)
    source_payload["baselineDsmObservedSizeBytes"] = baseline_path.stat().st_size
    source_payload["currentDsmObservedSizeBytes"] = current_path.stat().st_size
    source_payload["calculationIdentityDigest"] = None
    resealed_source = CalculationIdentityV2.model_validate(source_payload).sealed()
    payload = identity.model_dump(by_alias=True)
    payload["sourceCalculationIdentity"] = resealed_source.model_dump(by_alias=True)
    payload["sourceCalculationIdentityDigest"] = resealed_source.canonical_digest()
    payload["maskedCalculationIdentityDigest"] = None
    identity = MaskedCalculationIdentityV3.model_validate(payload).sealed()

    outcome = measure_masked_volume_v3(
        masked_identity=identity,
        baseline_path=baseline_path,
        current_path=current_path,
        mask_path=mask_path,
        envelope=envelope,
        watchdog=_watchdog(envelope),
        lease_expires_at=datetime(2026, 9, 22, tzinfo=UTC),
        report_id="report-file",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    assert isinstance(outcome, MaskedVolumeMeasuredV3)
    assert outcome.report.numeric_result.metrics.fill_m3 == 2.0
    assert outcome.delta_grid_m.shape == (4, 4)

    nodata_mask_path = tmp_path / "mask-nodata.tif"
    with rasterio.open(
        nodata_mask_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint8",
        crs="EPSG:5186",
        transform=transform,
        nodata=0,
    ) as dataset:
        dataset.write(_known_mask(), 1)
    nodata_identity = _masked_identity(
        _full_polygon(),
        baseline_sha=_digest(baseline_path.read_bytes()),
        current_sha=_digest(current_path.read_bytes()),
        mask_sha=_digest(nodata_mask_path.read_bytes()),
        mask_size=nodata_mask_path.stat().st_size,
    )
    source_payload = nodata_identity.source_calculation_identity.model_dump(by_alias=True)
    source_payload["baselineDsmObservedSizeBytes"] = baseline_path.stat().st_size
    source_payload["currentDsmObservedSizeBytes"] = current_path.stat().st_size
    source_payload["calculationIdentityDigest"] = None
    resealed_source = CalculationIdentityV2.model_validate(source_payload).sealed()
    payload = nodata_identity.model_dump(by_alias=True)
    payload["sourceCalculationIdentity"] = resealed_source.model_dump(by_alias=True)
    payload["sourceCalculationIdentityDigest"] = resealed_source.canonical_digest()
    payload["maskedCalculationIdentityDigest"] = None
    nodata_identity = MaskedCalculationIdentityV3.model_validate(payload).sealed()
    rejected = measure_masked_volume_v3(
        masked_identity=nodata_identity,
        baseline_path=baseline_path,
        current_path=current_path,
        mask_path=nodata_mask_path,
        envelope=envelope,
        watchdog=_watchdog(envelope),
        lease_expires_at=datetime(2026, 9, 22, tzinfo=UTC),
        report_id="report-nodata",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    assert isinstance(rejected, MaskedVolumeCalculationFailureV3)
    # The structural preflight rejects the NoData tag before any GDAL open.
    assert rejected.reason_code == "MASK_BYTES_MISMATCH"

    wrong_sha_identity = _masked_identity(
        _full_polygon(),
        baseline_sha=_digest(baseline_path.read_bytes()),
        current_sha=_digest(current_path.read_bytes()),
        mask_sha=_digest("different-mask-bytes"),
        mask_size=mask_path.stat().st_size,
    )
    source_payload = wrong_sha_identity.source_calculation_identity.model_dump(by_alias=True)
    source_payload["baselineDsmObservedSizeBytes"] = baseline_path.stat().st_size
    source_payload["currentDsmObservedSizeBytes"] = current_path.stat().st_size
    source_payload["calculationIdentityDigest"] = None
    resealed_source = CalculationIdentityV2.model_validate(source_payload).sealed()
    payload = wrong_sha_identity.model_dump(by_alias=True)
    payload["sourceCalculationIdentity"] = resealed_source.model_dump(by_alias=True)
    payload["sourceCalculationIdentityDigest"] = resealed_source.canonical_digest()
    payload["maskedCalculationIdentityDigest"] = None
    wrong_sha_identity = MaskedCalculationIdentityV3.model_validate(payload).sealed()
    sha_mismatch = measure_masked_volume_v3(
        masked_identity=wrong_sha_identity,
        baseline_path=baseline_path,
        current_path=current_path,
        mask_path=mask_path,
        envelope=envelope,
        watchdog=_watchdog(envelope),
        lease_expires_at=datetime(2026, 9, 22, tzinfo=UTC),
        report_id="report-sha",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    assert isinstance(sha_mismatch, MaskedVolumeCalculationFailureV3)
    assert sha_mismatch.reason_code == "MASK_BYTES_MISMATCH"


def test_v2_leaf_invariance_and_result_schema() -> None:
    """The V2 metric leaf is unchanged; the V3 result validates against its own schema."""
    metrics = RelativeVolumeMetricsV2(
        cut_m3=2.0, fill_m3=2.0, net_m3=0.0, threshold_m=0.0, uncertainty_m3=None
    )
    assert metrics.net_m3 == 0.0
    envelope = _envelope()
    identity = _masked_identity(
        _full_polygon(),
        baseline_sha=_digest("b"),
        current_sha=_digest("c"),
        mask_sha=_digest("m"),
    )
    outcome = _measure_from_diff(_known_diff(), _known_mask(), identity, envelope)
    assert isinstance(outcome, MaskedVolumeMeasuredV3)
    assert outcome.report.contract_version == "external-masked-volume-calculation-report.v3"
    assert outcome.report.numeric_result.contract_version == (
        "external-masked-volume-numeric-result.v3"
    )
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "contracts/schemas/external-masked-volume-result.v3.json"
    )
    validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
    numeric_wire = masked_volume_numeric_result_wire_dict(outcome.report.numeric_result)
    report_wire = masked_volume_calculation_report_wire_dict(outcome.report)
    assert not list(validator.iter_errors(numeric_wire))
    assert not list(validator.iter_errors(report_wire))
    assert not list(
        validator.iter_errors(
            outcome.report.numeric_result.coverage.model_dump(by_alias=True, mode="json")
        )
    )
    relaxed = json.loads(json.dumps(numeric_wire))
    relaxed["metrics"]["thresholdM"] = 0.1
    assert list(validator.iter_errors(relaxed))


def _write_valid_dsms(tmp_path: Path) -> tuple[Path, Path]:
    """Write the canonical 4x4 DSM pair used by the file-backed preflight tests."""
    baseline_values = np.full((4, 4), 100.0)
    current_values = baseline_values + _known_diff().diff_m
    transform = from_origin(_ORIGIN_X, _ORIGIN_Y, 1.0, 1.0)
    baseline_path = tmp_path / "baseline.tif"
    current_path = tmp_path / "current.tif"
    with rasterio.open(
        baseline_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float64",
        crs=_COMPOUND_CRS,
        transform=transform,
    ) as dataset:
        dataset.write(baseline_values, 1)
    with rasterio.open(
        current_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float64",
        crs=_COMPOUND_CRS,
        transform=transform,
    ) as dataset:
        dataset.write(current_values, 1)
    return baseline_path, current_path


def _no_gdal_rasterio(message: str) -> object:
    """Stub the measurement module's rasterio reference so any GDAL open fails loudly."""
    from types import SimpleNamespace

    def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError(message)

    return SimpleNamespace(open=_boom, Env=rasterio.Env)


def _file_identity_for(
    baseline_path: Path, current_path: Path, mask_path: Path
) -> MaskedCalculationIdentityV3:
    identity = _masked_identity(
        _full_polygon(),
        baseline_sha=_digest(baseline_path.read_bytes()),
        current_sha=_digest(current_path.read_bytes()),
        mask_sha=_digest(mask_path.read_bytes()),
        mask_size=mask_path.stat().st_size,
    )
    source_payload = identity.source_calculation_identity.model_dump(by_alias=True)
    source_payload["baselineDsmObservedSizeBytes"] = baseline_path.stat().st_size
    source_payload["currentDsmObservedSizeBytes"] = current_path.stat().st_size
    source_payload["calculationIdentityDigest"] = None
    resealed_source = CalculationIdentityV2.model_validate(source_payload).sealed()
    payload = identity.model_dump(by_alias=True)
    payload["sourceCalculationIdentity"] = resealed_source.model_dump(by_alias=True)
    payload["sourceCalculationIdentityDigest"] = resealed_source.canonical_digest()
    payload["maskedCalculationIdentityDigest"] = None
    return MaskedCalculationIdentityV3.model_validate(payload).sealed()


def test_masked_diff_rejects_malformed_diff_fields_without_escapes() -> None:
    """Scalar, missing, 1-D, or mistyped diff fields fail closed with typed reasons."""
    envelope = _envelope()
    identity = _masked_identity(
        _full_polygon(),
        baseline_sha=_digest("b"),
        current_sha=_digest("c"),
        mask_sha=_digest("m"),
    )

    def attempt(diff: object, **overrides: object) -> object:
        kwargs: dict[str, object] = {
            "masked_identity": identity,
            "diff": diff,
            "exclusion_mask": _known_mask(),
            "mask_crs": "EPSG:5186",
            "mask_transform": Affine(*_NATIVE_TRANSFORM),
            "envelope": envelope,
            "watchdog": _watchdog(envelope),
            "lease_expires_at": datetime(2026, 9, 22, tzinfo=UTC),
            "report_id": "report-malformed",
            "computed_at": datetime(2026, 9, 21, tzinfo=UTC),
            "reported_at": datetime(2026, 9, 21, tzinfo=UTC),
        }
        kwargs.update(overrides)
        return measure_masked_volume_v3_from_diff(**kwargs)  # type: ignore[arg-type]

    base = _known_diff()
    malformed = [
        None,
        "not-a-diff",
        DiffResult(
            diff_m=np.zeros((4, 4)),  # wrong dtype, valid missing below
            valid=None,  # type: ignore[arg-type]
            transform=Affine(*_NATIVE_TRANSFORM),
            crs="EPSG:5186",
            cell_area_m2=1.0,
        ),
        DiffResult(
            diff_m=np.zeros(16),  # 1-D: shape[1] would IndexError without the ndim gate
            valid=np.ones(16, dtype=np.bool_),
            transform=Affine(*_NATIVE_TRANSFORM),
            crs="EPSG:5186",
            cell_area_m2=1.0,
        ),
        DiffResult(
            diff_m=[[0.0] * 4] * 4,  # type: ignore[arg-type]  # not an ndarray at all
            valid=np.ones((4, 4), dtype=np.bool_),
            transform=Affine(*_NATIVE_TRANSFORM),
            crs="EPSG:5186",
            cell_area_m2=1.0,
        ),
        DiffResult(
            diff_m=base.diff_m,
            valid=base.valid,
            transform=(1.0, 0.0, 0.0, 0.0, -1.0, 0.0),  # not an Affine
            crs="EPSG:5186",
            cell_area_m2=1.0,
        ),
        DiffResult(
            diff_m=base.diff_m,
            valid=base.valid,
            transform=Affine(*_NATIVE_TRANSFORM),
            crs="",  # empty CRS string
            cell_area_m2=1.0,
        ),
        DiffResult(
            diff_m=base.diff_m,
            valid=base.valid,
            transform=Affine(*_NATIVE_TRANSFORM),
            crs="EPSG:5186",
            cell_area_m2=float("nan"),
        ),
        DiffResult(
            diff_m=base.diff_m,
            valid=base.valid,
            transform=Affine(*_NATIVE_TRANSFORM),
            crs="EPSG:5186",
            cell_area_m2="1.0",  # type: ignore[arg-type]
        ),
    ]
    for index, bad_diff in enumerate(malformed):
        outcome = attempt(bad_diff, report_id=f"report-malformed-{index}")
        assert isinstance(outcome, MaskedVolumeCalculationFailureV3), bad_diff
        assert outcome.reason_code in {
            "MASKED_INPUT_MISMATCH",
            "MASKED_IDENTITY_MISMATCH",
        }

    masked_array = np.ma.masked_array(_known_mask(), mask=np.zeros((4, 4), dtype=bool))
    outcome = attempt(_known_diff(), exclusion_mask=masked_array, report_id="report-ma")
    assert isinstance(outcome, MaskedVolumeCalculationFailureV3)
    assert outcome.reason_code == "MASK_NODATA_REJECTED"

    with pytest.raises(MaskedVolumeMeasurementError):
        measure_masked_volume_v3_from_diff(
            masked_identity="not-an-identity",  # type: ignore[arg-type]
            diff=_known_diff(),
            exclusion_mask=_known_mask(),
            mask_crs="EPSG:5186",
            mask_transform=Affine(*_NATIVE_TRANSFORM),
            envelope=envelope,
            watchdog=_watchdog(envelope),
            lease_expires_at=datetime(2026, 9, 22, tzinfo=UTC),
            report_id="report-identity",
            computed_at=datetime(2026, 9, 21, tzinfo=UTC),
            reported_at=datetime(2026, 9, 21, tzinfo=UTC),
        )


def test_mask_structural_preflight_rejects_before_any_gdal_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed mask bytes never reach the native decoder; the parser gate decides."""
    baseline_path, current_path = _write_valid_dsms(tmp_path)
    envelope = _envelope()
    # (payload, expected typed reason): bad magic fails the header gate while a
    # huge entry count trips the bounded directory cap; both pre-GDAL.
    cases = [
        (b"NOPE\x00\x00\x00\x00", "MASK_BYTES_MISMATCH"),
        (b"II*\x00\x08\x00\x00\x00\xff\xff", "RESOURCE_LIMIT_EXCEEDED"),
        (b"II*\x00", "MASK_BYTES_MISMATCH"),
    ]
    for index, (payload, expected_reason) in enumerate(cases):
        bad_mask_path = tmp_path / f"mask-bad-{index}.tif"
        bad_mask_path.write_bytes(payload)
        identity = _file_identity_for(baseline_path, current_path, bad_mask_path)
        monkeypatch.setattr(
            "ksi_processing_controller.external_masked_volume_measurement.rasterio",
            _no_gdal_rasterio("mask preflight must reject before any GDAL mask open"),
        )
        outcome = measure_masked_volume_v3(
            masked_identity=identity,
            baseline_path=baseline_path,
            current_path=current_path,
            mask_path=bad_mask_path,
            envelope=envelope,
            watchdog=_watchdog(envelope),
            lease_expires_at=datetime(2026, 9, 22, tzinfo=UTC),
            report_id=f"report-preflight-{index}",
            computed_at=datetime(2026, 9, 21, tzinfo=UTC),
            reported_at=datetime(2026, 9, 21, tzinfo=UTC),
        )
        assert isinstance(outcome, MaskedVolumeCalculationFailureV3)
        assert outcome.reason_code == expected_reason


def test_mask_sample_model_rejected_by_structure_not_decoder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A float32 single-band file is structurally not a binary mask, pre-GDAL."""
    baseline_path, current_path = _write_valid_dsms(tmp_path)
    float_mask_path = tmp_path / "mask-float.tif"
    transform = from_origin(_ORIGIN_X, _ORIGIN_Y, 1.0, 1.0)
    with rasterio.open(
        float_mask_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:5186",
        transform=transform,
    ) as dataset:
        dataset.write(np.zeros((4, 4), dtype=np.float32), 1)
    identity = _file_identity_for(baseline_path, current_path, float_mask_path)
    envelope = _envelope()

    monkeypatch.setattr(
        "ksi_processing_controller.external_masked_volume_measurement.rasterio",
        _no_gdal_rasterio("float mask must not reach the GDAL decoder"),
    )
    outcome = measure_masked_volume_v3(
        masked_identity=identity,
        baseline_path=baseline_path,
        current_path=current_path,
        mask_path=float_mask_path,
        envelope=envelope,
        watchdog=_watchdog(envelope),
        lease_expires_at=datetime(2026, 9, 22, tzinfo=UTC),
        report_id="report-float-mask",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    assert isinstance(outcome, MaskedVolumeCalculationFailureV3)
    assert outcome.reason_code == "MASK_BYTES_MISMATCH"
