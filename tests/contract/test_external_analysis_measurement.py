"""Real-byte proof for the unmounted fixed-profile V2 measurement callable."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import rasterio
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ObservedVerticalReferenceV1,
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_relative_volume_analysis import (
    AdmissionDispositionV2,
    AdmissionV2,
    AnalysisPolicyV2,
    CalculationIdentityV2,
)
from ksi_event_contracts.external_relative_volume_calculation import (
    AnalysisExecutionAttemptV2,
    AnalysisExecutionAuthorizationV2,
    RelativeVolumeCalculationFailureV2,
    RelativeVolumeCalculationReportV2,
)
from ksi_processing_controller.external_analysis_measurement import (
    measure_external_relative_volume_v2,
)
from pyproj import CRS
from rasterio.transform import Affine, from_origin

_ORIGIN_X = 200_000.0
_ORIGIN_Y = 550_000.0
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


def _policy() -> AnalysisPolicyV2:
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


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=1_000_000,
        max_streamed_bytes=1_000_000,
        max_tiff_directories=4,
        max_tiff_entries=64,
        max_pixels=1_000_000,
        max_bands=4,
        max_blocks=128,
        max_decompressed_bytes=10_000_000,
        max_sample_bytes=1_000_000,
        max_geometry_vertices=64,
        max_cpu_seconds=10.0,
        max_memory_bytes=10_000_000,
        max_workspace_bytes=10_000_000,
        max_output_bytes=1_000_000,
        max_tenant_concurrency=2,
        max_queue_depth=4,
        max_deadline_seconds=60.0,
        lease_duration_seconds=10.0,
        max_retry_attempts=2,
    ).sealed()


def _write_dsm(
    path: Path,
    values: np.ndarray,
    *,
    nodata: float | None = None,
    transform: Affine | None = None,
) -> Path:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=values.shape[0],
        width=values.shape[1],
        count=1,
        dtype="float64",
        crs=_COMPOUND_CRS,
        transform=transform or from_origin(_ORIGIN_X, _ORIGIN_Y, 1.0, 1.0),
        nodata=nodata,
    ) as dataset:
        dataset.write(values, 1)
    return path


def _identity(
    baseline: Path,
    current: Path,
    *,
    baseline_transform: tuple[float, float, float, float, float, float] | None = None,
    current_transform: tuple[float, float, float, float, float, float] | None = None,
) -> CalculationIdentityV2:
    vertical = ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")
    native_transform = (1.0, 0.0, _ORIGIN_X, 0.0, -1.0, _ORIGIN_Y)
    baseline_transform = baseline_transform or native_transform
    current_transform = current_transform or native_transform
    horizontal_wkt = CRS.from_epsg(5186).to_wkt(
        version="WKT2_2019", pretty=False, output_axis_rule=True
    )
    horizontal_digest = _digest(horizontal_wkt)
    policy = _policy()
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [_ORIGIN_X, _ORIGIN_Y],
                [_ORIGIN_X, _ORIGIN_Y - 2.0],
                [_ORIGIN_X + 2.0, _ORIGIN_Y - 2.0],
                [_ORIGIN_X + 2.0, _ORIGIN_Y],
                [_ORIGIN_X, _ORIGIN_Y],
            ]
        ],
    }
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
        baseline_dsm_observed_sha256=_digest(baseline.read_bytes()),
        current_dsm_observed_sha256=_digest(current.read_bytes()),
        baseline_dsm_observed_size_bytes=baseline.stat().st_size,
        current_dsm_observed_size_bytes=current.stat().st_size,
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
        baseline_transform_digest=_canonical_digest({"transform": list(baseline_transform)}),
        current_transform_digest=_canonical_digest({"transform": list(current_transform)}),
        baseline_transform=baseline_transform,
        current_transform=current_transform,
        horizontal_crs_digest=horizontal_digest,
        vertical_reference_digest=vertical.canonical_digest(),
        policy=policy,
        worker_executable_digest=_digest("worker"),
        worker_build_digest=_digest("build"),
        runtime_image_version="2.0.0",
        runtime_image_oci_digest=_digest("oci"),
        dependency_lock_digest=_digest("lock"),
    ).sealed()


def _attempt(
    identity: CalculationIdentityV2, *, envelope: ResourceEnvelopeV1 | None = None
) -> AnalysisExecutionAttemptV2:
    admission = AdmissionV2(
        admission_id="admission-1",
        calculation_identity=identity,
        evaluation_revisions=(),
        disposition=AdmissionDispositionV2.ADMIT_PROVISIONAL,
        reason_codes=("CHECKPOINT_EVIDENCE_ABSENT",),
        assessed_at=datetime(2026, 9, 21, tzinfo=UTC),
    ).sealed()
    authorization = AnalysisExecutionAuthorizationV2(
        authorization_id="authorization-1",
        organization_id="org-a",
        calculation_identity_digest=identity.canonical_digest(),
        admission_digest=admission.canonical_digest(),
        resource_envelope=envelope or _envelope(),
        resource_envelope_digest=(envelope or _envelope()).canonical_digest(),
        authorized_at=datetime(2026, 9, 21, tzinfo=UTC),
    ).sealed()
    return AnalysisExecutionAttemptV2(
        attempt_id="attempt-1",
        authorization=authorization,
        authorization_digest=authorization.canonical_digest(),
        worker_instance_id="worker-1",
        lease_acquisition_id="lease-1",
        lease_generation=1,
        issued_at=datetime(2026, 9, 21, tzinfo=UTC),
        lease_expires_at=datetime(2026, 9, 21, 0, 1, tzinfo=UTC),
    ).sealed()


def test_fixed_profile_measures_actual_geotiff_bytes_and_preserves_full_zone_mask(
    tmp_path: Path,
) -> None:
    """Wrong sign, masked NoData, or a partial zone would change this hand-derived result."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    current = _write_dsm(
        tmp_path / "current.tif", np.array([[101.0, 99.0], [100.0, 100.0]])
    )
    identity = _identity(baseline, current)

    result = measure_external_relative_volume_v2(
        attempt=_attempt(identity),
        calculation_identity=identity,
        baseline_path=baseline,
        current_path=current,
        report_id="report-1",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert isinstance(result, RelativeVolumeCalculationReportV2)
    assert result.numeric_result.metrics.fill_m3 == 1.0
    assert result.numeric_result.metrics.cut_m3 == 1.0
    assert result.numeric_result.metrics.net_m3 == 0.0
    assert result.numeric_result.coverage.selected_cell_count == 4
    assert result.numeric_result.coverage.common_valid_cell_count == 4
    assert result.numeric_result.coverage.unavailable_cell_count == 0
    assert result.numeric_result.coverage.selected_mask_b64 == "8A=="


def test_fixed_profile_returns_no_numeric_report_when_full_zone_coverage_is_missing(
    tmp_path: Path,
) -> None:
    """Turning a missing cell into zero would incorrectly publish a partial measurement."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0), nodata=-9999.0)
    current = _write_dsm(
        tmp_path / "current.tif",
        np.array([[101.0, -9999.0], [100.0, 100.0]]),
        nodata=-9999.0,
    )
    identity = _identity(baseline, current)

    result = measure_external_relative_volume_v2(
        attempt=_attempt(identity),
        calculation_identity=identity,
        baseline_path=baseline,
        current_path=current,
        report_id="report-2",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert isinstance(result, RelativeVolumeCalculationFailureV2)
    assert result.reason_code == "INSUFFICIENT_COMMON_VALID_COVERAGE"


def test_fixed_profile_rejects_bytes_that_do_not_match_sealed_current_identity(
    tmp_path: Path,
) -> None:
    """A path replacement after Core sealing must not be measured under the former digest."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    current = _write_dsm(tmp_path / "current.tif", np.full((2, 2), 101.0))
    identity = _identity(baseline, current)
    _write_dsm(current, np.full((2, 2), 102.0))

    result = measure_external_relative_volume_v2(
        attempt=_attempt(identity),
        calculation_identity=identity,
        baseline_path=baseline,
        current_path=current,
        report_id="report-3",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert isinstance(result, RelativeVolumeCalculationFailureV2)
    assert result.reason_code == "CURRENT_DSM_BYTES_MISMATCH"


def test_fixed_profile_rejects_two_owned_snapshots_before_workspace_allocation(
    tmp_path: Path,
) -> None:
    """Per-file limits cannot admit two immutable copies beyond workspace policy."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    current = _write_dsm(tmp_path / "current.tif", np.full((2, 2), 101.0))
    identity = _identity(baseline, current)
    constrained = _envelope().model_copy(
        update={
            "max_workspace_bytes": baseline.stat().st_size + current.stat().st_size - 1,
            "resource_envelope_digest": None,
        }
    ).sealed()

    result = measure_external_relative_volume_v2(
        attempt=_attempt(identity, envelope=constrained),
        calculation_identity=identity,
        baseline_path=baseline,
        current_path=current,
        report_id="report-workspace-limit",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert isinstance(result, RelativeVolumeCalculationFailureV2)
    assert result.reason_code == "RESOURCE_LIMIT_EXCEEDED"


def test_fixed_profile_rejects_work_area_beyond_sealed_geometry_cap(
    tmp_path: Path,
) -> None:
    """The worker must cap polygon work before it asks Rasterio to rasterize."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    current = _write_dsm(tmp_path / "current.tif", np.full((2, 2), 101.0))
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [_ORIGIN_X, _ORIGIN_Y],
                [_ORIGIN_X, _ORIGIN_Y - 1.0],
                [_ORIGIN_X, _ORIGIN_Y - 2.0],
                [_ORIGIN_X + 2.0, _ORIGIN_Y - 2.0],
                [_ORIGIN_X + 2.0, _ORIGIN_Y],
                [_ORIGIN_X, _ORIGIN_Y],
            ]
        ],
    }
    identity = _identity(baseline, current).model_copy(
        update={
            "work_area_polygon": polygon,
            "work_area_definition_digest": _canonical_digest(
                {"workAreaId": "work-area-a", "crs": "EPSG:5186", "polygon": polygon}
            ),
            "calculation_identity_digest": None,
        }
    ).sealed()
    constrained = _envelope().model_copy(
        update={"max_geometry_vertices": 5, "resource_envelope_digest": None}
    ).sealed()

    result = measure_external_relative_volume_v2(
        attempt=_attempt(identity, envelope=constrained),
        calculation_identity=identity,
        baseline_path=baseline,
        current_path=current,
        report_id="report-geometry-limit",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert isinstance(result, RelativeVolumeCalculationFailureV2)
    assert result.reason_code == "RESOURCE_LIMIT_EXCEEDED"


def test_fixed_profile_rejects_nonfinite_or_outside_zone_cells_without_numeric_output(
    tmp_path: Path,
) -> None:
    """NaN, infinity, and an unavailable full WorkArea denominator cannot become zero fill."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    current_nonfinite = _write_dsm(
        tmp_path / "current-nonfinite.tif",
        np.array([[101.0, np.nan], [np.inf, 100.0]]),
    )
    nonfinite_identity = _identity(baseline, current_nonfinite)
    nonfinite = measure_external_relative_volume_v2(
        attempt=_attempt(nonfinite_identity),
        calculation_identity=nonfinite_identity,
        baseline_path=baseline,
        current_path=current_nonfinite,
        report_id="report-nonfinite",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    assert isinstance(nonfinite, RelativeVolumeCalculationFailureV2)
    assert nonfinite.reason_code == "SECONDARY_DSM_REJECTED"

    current = _write_dsm(tmp_path / "current.tif", np.full((2, 2), 101.0))
    outside = _identity(baseline, current).model_copy(
        update={
            "work_area_polygon": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [_ORIGIN_X + 10.0, _ORIGIN_Y - 10.0],
                        [_ORIGIN_X + 10.0, _ORIGIN_Y - 12.0],
                        [_ORIGIN_X + 12.0, _ORIGIN_Y - 12.0],
                        [_ORIGIN_X + 12.0, _ORIGIN_Y - 10.0],
                        [_ORIGIN_X + 10.0, _ORIGIN_Y - 10.0],
                    ]
                ],
            },
            "work_area_definition_digest": _canonical_digest(
                {
                    "workAreaId": "work-area-a",
                    "crs": "EPSG:5186",
                    "polygon": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [_ORIGIN_X + 10.0, _ORIGIN_Y - 10.0],
                                [_ORIGIN_X + 10.0, _ORIGIN_Y - 12.0],
                                [_ORIGIN_X + 12.0, _ORIGIN_Y - 12.0],
                                [_ORIGIN_X + 12.0, _ORIGIN_Y - 10.0],
                                [_ORIGIN_X + 10.0, _ORIGIN_Y - 10.0],
                            ]
                        ],
                    },
                }
            ),
            "calculation_identity_digest": None,
        }
    ).sealed()
    outside_result = measure_external_relative_volume_v2(
        attempt=_attempt(outside),
        calculation_identity=outside,
        baseline_path=baseline,
        current_path=current,
        report_id="report-outside",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    assert isinstance(outside_result, RelativeVolumeCalculationFailureV2)
    assert outside_result.reason_code in {
        "EMPTY_COMMON_VALID_COVERAGE",
        "INSUFFICIENT_COMMON_VALID_COVERAGE",
    }


def test_fixed_profile_accepts_rotated_current_but_rejects_rotated_baseline(
    tmp_path: Path,
) -> None:
    """Only the baseline is the fixed north-up grid; current pixels are resampled."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    rotated_current_affine = Affine(1.0, 0.1, _ORIGIN_X - 1.0, 0.0, -1.0, _ORIGIN_Y + 1.0)
    current = _write_dsm(
        tmp_path / "current.tif",
        np.full((4, 4), 101.0),
        transform=rotated_current_affine,
    )
    current_transform = tuple(rotated_current_affine)[:6]
    rotated_current_identity = _identity(
        baseline, current, current_transform=current_transform
    )
    resampled = measure_external_relative_volume_v2(
        attempt=_attempt(rotated_current_identity),
        calculation_identity=rotated_current_identity,
        baseline_path=baseline,
        current_path=current,
        report_id="report-rotated-current",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    assert isinstance(resampled, RelativeVolumeCalculationReportV2)
    assert resampled.numeric_result.metrics.fill_m3 > 0.0

    rotated_baseline_identity = _identity(
        baseline,
        current,
        baseline_transform=current_transform,
        current_transform=current_transform,
    )
    rejected = measure_external_relative_volume_v2(
        attempt=_attempt(rotated_baseline_identity),
        calculation_identity=rotated_baseline_identity,
        baseline_path=baseline,
        current_path=current,
        report_id="report-rotated-baseline",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    assert isinstance(rejected, RelativeVolumeCalculationFailureV2)
    assert rejected.reason_code == "BASELINE_AFFINE_NOT_NORTH_UP"


def test_fixed_profile_rejects_crs_and_vertical_context_substitution(
    tmp_path: Path,
) -> None:
    """Worker parser facts must match the identity, even when trusted bytes still match."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    current = _write_dsm(tmp_path / "current.tif", np.full((2, 2), 101.0))
    identity = _identity(baseline, current)
    wrong_crs = _digest("different-observed-horizontal-crs")
    crs_identity = identity.model_copy(
        update={
            "baseline_observed_crs_digest": wrong_crs,
            "current_observed_crs_digest": wrong_crs,
            "horizontal_crs_digest": wrong_crs,
            "calculation_identity_digest": None,
        }
    ).sealed()
    crs_result = measure_external_relative_volume_v2(
        attempt=_attempt(crs_identity),
        calculation_identity=crs_identity,
        baseline_path=baseline,
        current_path=current,
        report_id="report-crs-context",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    assert isinstance(crs_result, RelativeVolumeCalculationFailureV2)
    assert crs_result.reason_code == "BASELINE_DSM_CONTEXT_MISMATCH"

    wrong_vertical = ObservedVerticalReferenceV1(
        identifier="EPSG:5703", basis="NAVD88 height"
    )
    vertical_digest = wrong_vertical.canonical_digest()
    vertical_identity = identity.model_copy(
        update={
            "baseline_vertical_reference": wrong_vertical,
            "current_vertical_reference": wrong_vertical,
            "baseline_vertical_reference_digest": vertical_digest,
            "current_vertical_reference_digest": vertical_digest,
            "vertical_reference_digest": vertical_digest,
            "calculation_identity_digest": None,
        }
    ).sealed()
    vertical_result = measure_external_relative_volume_v2(
        attempt=_attempt(vertical_identity),
        calculation_identity=vertical_identity,
        baseline_path=baseline,
        current_path=current,
        report_id="report-vertical-context",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )
    assert isinstance(vertical_result, RelativeVolumeCalculationFailureV2)
    assert vertical_result.reason_code == "BASELINE_DSM_CONTEXT_MISMATCH"


def test_fixed_profile_rejects_report_exceeding_sealed_output_ceiling(tmp_path: Path) -> None:
    """A complete numeric calculation cannot escape through an oversized report payload."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    current = _write_dsm(tmp_path / "current.tif", np.full((2, 2), 101.0))
    identity = _identity(baseline, current)
    constrained = _envelope().model_copy(
        update={"max_output_bytes": 1, "resource_envelope_digest": None}
    ).sealed()

    result = measure_external_relative_volume_v2(
        attempt=_attempt(identity, envelope=constrained),
        calculation_identity=identity,
        baseline_path=baseline,
        current_path=current,
        report_id="report-output-limit",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )

    assert isinstance(result, RelativeVolumeCalculationFailureV2)
    assert result.reason_code == "RESOURCE_LIMIT_EXCEEDED"


def test_fixed_profile_cancellation_returns_no_numeric_result(tmp_path: Path) -> None:
    """A lost outer lease must stop the real callable before it can publish numbers."""
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    current = _write_dsm(tmp_path / "current.tif", np.full((2, 2), 101.0))
    identity = _identity(baseline, current)

    result = measure_external_relative_volume_v2(
        attempt=_attempt(identity),
        calculation_identity=identity,
        baseline_path=baseline,
        current_path=current,
        report_id="report-cancelled",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
        maximum_wall_seconds=1.0,
        is_cancelled=lambda: True,
    )

    assert isinstance(result, RelativeVolumeCalculationFailureV2)
    assert result.reason_code == "MEASUREMENT_INCOMPLETE"
