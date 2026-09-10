"""Full-zone external volume calculation tests with hand-derived grid values."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest
from ksi_change_detection.dsm_diff import DiffResult
from ksi_change_detection.external_volume import (
    ExternalVolumeMeasurementError,
    ExternalVolumeMeasurementErrorReason,
    ExternalVolumeZoneMeasurement,
    measure_external_volume_zone,
)
from rasterio.transform import Affine, from_origin


def _diff(values: list[list[float]], *, valid: list[list[bool]] | None = None) -> DiffResult:
    array = np.array(values, dtype=np.float64)
    valid_array = (
        np.ones(array.shape, dtype=np.bool_) if valid is None else np.array(valid, dtype=np.bool_)
    )
    return DiffResult(
        diff_m=array,
        valid=valid_array,
        transform=from_origin(0.0, 2.0, 1.0, 1.0),
        crs="EPSG:5186",
        cell_area_m2=1.0,
    )


def _zone(*, left: float = 0.0, right: float = 2.0) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [[[left, 2.0], [right, 2.0], [right, 0.0], [left, 0.0], [left, 2.0]]],
    }


def _measure(
    diff: DiffResult, polygon: dict[str, object] | None = None, **overrides: Any
) -> ExternalVolumeZoneMeasurement | ExternalVolumeMeasurementError:
    arguments: dict[str, Any] = {
        "zone_id": "zone-1",
        "from_crs": "EPSG:5186",
        "threshold_m": 0.0,
        "minimum_common_valid_fraction": 1.0,
        "maximum_zone_grid_cells": 64,
        "uncertainty_note": "Independent checkpoint RMSE is unavailable for both epochs.",
    }
    arguments.update(overrides)
    return measure_external_volume_zone(diff, _zone() if polygon is None else polygon, **arguments)


def test_full_grid_reproduces_hand_calculated_cut_fill_net_and_coverage() -> None:
    """Swapping signs or using a footprint-only denominator breaks this literal 2×2 case."""
    measured = _measure(_diff([[2.0, -1.0], [0.0, 3.0]]))
    assert not isinstance(measured, ExternalVolumeMeasurementError)
    assert measured.metrics.zone_cell_count == 4
    assert measured.metrics.common_valid_cell_count == 4
    assert measured.metrics.zone_area_m2 == pytest.approx(4.0)
    assert measured.metrics.measured_area_m2 == pytest.approx(4.0)
    assert measured.metrics.common_valid_fraction == pytest.approx(1.0)
    assert measured.metrics.fill_m3 == pytest.approx(5.0)
    assert measured.metrics.cut_m3 == pytest.approx(1.0)
    assert measured.metrics.net_m3 == pytest.approx(4.0)


def test_inverted_diff_swaps_fill_and_cut() -> None:
    """The same absolute deltas reverse direction without changing coverage."""
    measured = _measure(_diff([[-2.0, 1.0], [0.0, -3.0]]))
    assert not isinstance(measured, ExternalVolumeMeasurementError)
    assert measured.metrics.fill_m3 == pytest.approx(1.0)
    assert measured.metrics.cut_m3 == pytest.approx(5.0)
    assert measured.metrics.net_m3 == pytest.approx(-4.0)


def test_missing_grid_cell_is_counted_in_coverage_and_fails_full_coverage_policy() -> None:
    """Treating nodata as a zero delta would make this unsafe request look complete."""
    measured = _measure(_diff([[2.0, -1.0], [0.0, 3.0]], valid=[[True, True], [False, True]]))
    assert isinstance(measured, ExternalVolumeMeasurementError)
    assert (
        measured.reason is ExternalVolumeMeasurementErrorReason.INSUFFICIENT_COMMON_VALID_COVERAGE
    )
    assert measured.zone_cell_count == 4
    assert measured.common_valid_cell_count == 3


def test_all_nodata_returns_typed_error_instead_of_zero_volume() -> None:
    """No common cells is missing evidence, never a measured zero."""
    measured = _measure(_diff([[0.0, 0.0], [0.0, 0.0]], valid=[[False, False], [False, False]]))
    assert isinstance(measured, ExternalVolumeMeasurementError)
    assert measured.reason is ExternalVolumeMeasurementErrorReason.EMPTY_COMMON_VALID_COVERAGE
    assert measured.metrics is None


def test_polygon_partly_outside_raster_fails_full_coverage() -> None:
    """The grid-aligned zone includes unavailable outside cells in its denominator."""
    measured = _measure(_diff([[2.0, -1.0], [0.0, 3.0]]), _zone(left=-1.0, right=2.0))
    assert isinstance(measured, ExternalVolumeMeasurementError)
    assert (
        measured.reason is ExternalVolumeMeasurementErrorReason.INSUFFICIENT_COMMON_VALID_COVERAGE
    )
    assert measured.zone_cell_count == 6
    assert measured.common_valid_cell_count == 4


def test_exact_cell_boundaries_select_exactly_four_cells() -> None:
    """Using all_touched=True would make boundary semantics drift with polygon edge placement."""
    measured = _measure(_diff([[2.0, -1.0], [0.0, 3.0]]), _zone(left=0.0, right=2.0))
    assert not isinstance(measured, ExternalVolumeMeasurementError)
    assert measured.metrics.zone_cell_count == 4


def test_budget_is_checked_before_allocating_the_full_zone_mask() -> None:
    """An oversized external polygon must not force allocation before it is refused."""
    measured = _measure(
        _diff([[0.0, 0.0], [0.0, 0.0]]),
        _zone(left=0.0, right=1_000_000.0),
        maximum_zone_grid_cells=4,
    )
    assert isinstance(measured, ExternalVolumeMeasurementError)
    assert measured.reason is ExternalVolumeMeasurementErrorReason.OVERSIZED_ZONE
    assert measured.metrics is None


def test_uncertainty_is_reported_only_when_both_epoch_rmse_values_are_available() -> None:
    """One checked epoch cannot support a relative-volume uncertainty bound."""
    diff = _diff([[2.0, -1.0], [0.0, 3.0]])
    one_sided = _measure(diff, baseline_rmse_m=0.3)
    assert not isinstance(one_sided, ExternalVolumeMeasurementError)
    assert one_sided.metrics.uncertainty_m3 is None
    both_sided = _measure(diff, baseline_rmse_m=0.3, current_rmse_m=0.4)
    assert not isinstance(both_sided, ExternalVolumeMeasurementError)
    assert both_sided.metrics.uncertainty_m3 == pytest.approx(2.0)


@pytest.mark.parametrize(
    "overrides",
    [
        {"threshold_m": math.nan},
        {"threshold_m": math.inf},
        {"minimum_common_valid_fraction": 1e999},
        {"maximum_zone_grid_cells": True},
        {"baseline_rmse_m": math.inf},
        {"current_rmse_m": -0.01},
    ],
)
def test_invalid_policy_or_rmse_input_returns_a_typed_error(
    overrides: dict[str, Any],
) -> None:
    """Non-finite and boolean inputs cannot create a numeric measurement."""
    measured = _measure(_diff([[0.0, 0.0], [0.0, 0.0]]), **overrides)
    assert isinstance(measured, ExternalVolumeMeasurementError)
    assert measured.reason is ExternalVolumeMeasurementErrorReason.INVALID_INPUT
    assert measured.metrics is None


@pytest.mark.parametrize(
    "invalid_diff",
    [
        DiffResult(
            diff_m=np.zeros((2, 2), dtype=np.float64),
            valid=np.ones((2, 2), dtype=np.bool_),
            transform=from_origin(0.0, 2.0, 1.0, 1.0),
            crs="EPSG:4326",
            cell_area_m2=1.0,
        ),
        DiffResult(
            diff_m=np.zeros((2, 2), dtype=np.float64),
            valid=np.ones((2, 2), dtype=np.bool_),
            transform=from_origin(0.0, 2.0, 1.0, 1.0),
            crs="EPSG:5186",
            cell_area_m2=2.0,
        ),
        DiffResult(
            diff_m=np.zeros((2, 2), dtype=np.float64),
            valid=np.ones((2, 2), dtype=np.float64),
            transform=from_origin(0.0, 2.0, 1.0, 1.0),
            crs="EPSG:5186",
            cell_area_m2=1.0,
        ),
        DiffResult(
            diff_m=np.zeros((2, 2), dtype=np.float64),
            valid=np.ones((2, 2), dtype=np.bool_),
            transform=Affine(1.0, 0.0, 0.0, 0.0, 0.0, 2.0),
            crs="EPSG:5186",
            cell_area_m2=1.0,
        ),
        DiffResult(
            diff_m=np.zeros((2, 2), dtype=np.float64),
            valid=np.ones((2, 2), dtype=np.bool_),
            transform=Affine(1.0, 0.1, 0.0, 0.0, -1.0, 2.0),
            crs="EPSG:5186",
            cell_area_m2=1.0,
        ),
        DiffResult(
            diff_m=np.zeros((2, 2), dtype=np.float64),
            valid=np.ones((2, 2), dtype=np.bool_),
            transform=Affine(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
            crs="EPSG:5186",
            cell_area_m2=1.0,
        ),
        DiffResult(
            diff_m=np.array([[math.nan, 0.0], [0.0, 0.0]], dtype=np.float64),
            valid=np.array([[False, True], [True, True]], dtype=np.bool_),
            transform=from_origin(0.0, 2.0, 1.0, 1.0),
            crs="EPSG:5186",
            cell_area_m2=1.0,
        ),
        DiffResult(
            diff_m=np.zeros((2, 2), dtype=np.complex128),
            valid=np.ones((2, 2), dtype=np.bool_),
            transform=from_origin(0.0, 2.0, 1.0, 1.0),
            crs="EPSG:5186",
            cell_area_m2=1.0,
        ),
        DiffResult(
            diff_m=np.zeros((2, 2), dtype=np.float64),
            valid=np.ones((2, 2), dtype=np.bool_),
            transform=from_origin(0.0, 2.0, 1.0, 1.0),
            crs="EPSG:5186",
            cell_area_m2=10**400,
        ),
    ],
)
def test_invalid_diff_grid_returns_a_typed_error_without_meter_labelled_metrics(
    invalid_diff: DiffResult,
) -> None:
    """A CRS, transform, area, or mask defect must stop before any volume arithmetic."""
    measured = _measure(invalid_diff)
    assert isinstance(measured, ExternalVolumeMeasurementError)
    assert measured.reason is ExternalVolumeMeasurementErrorReason.INVALID_INPUT
    assert measured.metrics is None


@pytest.mark.parametrize("from_crs", [None, 1, True, object(), {"epsg": 5186}])
def test_nontext_polygon_source_crs_returns_a_typed_input_error(from_crs: object) -> None:
    """A malformed source CRS must not escape projection as a raw exception."""
    measured = _measure(_diff([[0.0, 0.0], [0.0, 0.0]]), from_crs=from_crs)
    assert isinstance(measured, ExternalVolumeMeasurementError)
    assert measured.reason is ExternalVolumeMeasurementErrorReason.INVALID_INPUT
    assert measured.metrics is None
