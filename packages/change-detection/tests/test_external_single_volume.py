"""Boundary-base single-epoch volume with hand-derived grids."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
from ksi_change_detection.external_single_volume import (
    ExternalSingleVolumeZoneMeasurement,
    derive_boundary_base_surface,
    measure_single_volume_zone,
)
from ksi_change_detection.external_volume import (
    ExternalVolumeMeasurementError,
    ExternalVolumeMeasurementErrorReason,
)
from rasterio.transform import from_origin

# 8x8 metre grid, origin top-left (0, 8); zone covers cells rows/cols 1..6 (x,y in 1..7).
_TRANSFORM = from_origin(0.0, 8.0, 1.0, 1.0)
_ZONE: dict[str, Any] = {
    "type": "Polygon",
    "coordinates": [[[1.0, 7.0], [7.0, 7.0], [7.0, 1.0], [1.0, 1.0], [1.0, 7.0]]],
}


def _ground(*, slope_x: float = 0.0) -> np.ndarray:
    cols = np.arange(8, dtype=np.float64) + 0.5
    return 10.0 + slope_x * np.broadcast_to(cols, (8, 8)).copy()


def _with_box(ground: np.ndarray, height: float) -> np.ndarray:
    dsm = ground.copy()
    dsm[3:5, 3:5] += height  # 2x2 cells, 1 m² each
    return dsm


def _measure(dsm: np.ndarray, valid: np.ndarray | None = None, **overrides: Any):
    arguments: dict[str, Any] = {
        "transform": _TRANSFORM,
        "crs": "EPSG:5186",
        "cell_area_m2": 1.0,
        "polygon_geojson": _ZONE,
        "zone_id": "zone-1",
        "from_crs": "EPSG:5186",
        "threshold_m": 0.0,
        "minimum_common_valid_fraction": 1.0,
        "minimum_boundary_valid_fraction": 0.5,
        "maximum_zone_grid_cells": 64,
        "uncertainty_note": "single epoch: area x hypot(dsm rmse, base roughness)",
        "dsm_rmse_m": 0.05,
    }
    arguments.update(overrides)
    return measure_single_volume_zone(
        dsm, np.ones(dsm.shape, dtype=np.bool_) if valid is None else valid, **arguments
    )


def test_box_on_flat_ground_reproduces_its_volume_with_zero_roughness() -> None:
    measured = _measure(_with_box(_ground(), 3.0))
    assert isinstance(measured, ExternalSingleVolumeZoneMeasurement)
    metrics = measured.metrics
    assert metrics.zone_cell_count == 36
    assert metrics.boundary_cell_count == 20
    assert metrics.boundary_sample_count == 20
    assert metrics.fill_m3 == pytest.approx(12.0)
    assert metrics.cut_m3 == pytest.approx(0.0)
    assert metrics.base_roughness_m == pytest.approx(0.0, abs=1e-9)
    assert metrics.uncertainty_m3 == pytest.approx(36.0 * 0.05)


def test_box_on_sloped_plane_is_measured_against_the_reproduced_plane() -> None:
    """Linear interpolation of a plane's boundary reproduces the plane exactly."""
    measured = _measure(_with_box(_ground(slope_x=0.5), 3.0))
    assert isinstance(measured, ExternalSingleVolumeZoneMeasurement)
    assert measured.metrics.fill_m3 == pytest.approx(12.0, abs=1e-9)
    assert measured.metrics.cut_m3 == pytest.approx(0.0, abs=1e-9)
    assert measured.metrics.base_roughness_m == pytest.approx(0.0, abs=1e-9)


def test_pit_below_ground_is_cut_not_fill() -> None:
    measured = _measure(_with_box(_ground(), -3.0))
    assert isinstance(measured, ExternalSingleVolumeZoneMeasurement)
    assert measured.metrics.cut_m3 == pytest.approx(12.0)
    assert measured.metrics.fill_m3 == pytest.approx(0.0)
    assert measured.metrics.net_m3 == pytest.approx(-12.0)


def test_rough_boundary_raises_uncertainty_through_base_roughness() -> None:
    dsm = _with_box(_ground(), 3.0)
    dsm[1, 1:7] += 0.2  # top boundary row bumped 20 cm
    measured = _measure(dsm)
    assert isinstance(measured, ExternalSingleVolumeZoneMeasurement)
    assert measured.metrics.base_roughness_m > 0.0
    assert measured.metrics.uncertainty_m3 == pytest.approx(
        36.0 * float(np.hypot(0.05, measured.metrics.base_roughness_m))
    )


def test_nodata_boundary_below_policy_fraction_fails_closed() -> None:
    dsm = _with_box(_ground(), 3.0)
    valid = np.ones(dsm.shape, dtype=np.bool_)
    valid[1, 1:7] = False  # 6 of 20 boundary cells
    valid[6, 1:7] = False  # 12 of 20 -> fraction 0.4 < 0.5
    measured = _measure(dsm, valid)
    assert isinstance(measured, ExternalVolumeMeasurementError)
    assert measured.reason is ExternalVolumeMeasurementErrorReason.INSUFFICIENT_BOUNDARY_COVERAGE


def test_interior_nodata_is_unknown_not_zero_and_fails_full_coverage() -> None:
    dsm = _with_box(_ground(), 3.0)
    valid = np.ones(dsm.shape, dtype=np.bool_)
    valid[3, 3] = False
    measured = _measure(dsm, valid)
    assert isinstance(measured, ExternalVolumeMeasurementError)
    assert (
        measured.reason is ExternalVolumeMeasurementErrorReason.INSUFFICIENT_COMMON_VALID_COVERAGE
    )
    assert measured.common_valid_cell_count == 35


def test_zone_outside_raster_and_oversized_zone_reuse_typed_errors() -> None:
    outside = {
        "type": "Polygon",
        "coordinates": [[[20.0, 22.0], [22.0, 22.0], [22.0, 20.0], [20.0, 20.0], [20.0, 22.0]]],
    }
    measured = _measure(_ground(), polygon_geojson=outside)
    assert isinstance(measured, ExternalVolumeMeasurementError)
    assert measured.reason is ExternalVolumeMeasurementErrorReason.INSUFFICIENT_BOUNDARY_COVERAGE
    oversized = _measure(_ground(), maximum_zone_grid_cells=10)
    assert isinstance(oversized, ExternalVolumeMeasurementError)
    assert oversized.reason is ExternalVolumeMeasurementErrorReason.OVERSIZED_ZONE


def test_collinear_boundary_samples_are_insufficient() -> None:
    dsm = _ground()
    valid = np.zeros(dsm.shape, dtype=np.bool_)
    valid[1, 1:7] = True  # only the top row of the ring is valid: collinear
    surface = derive_boundary_base_surface(
        dsm,
        valid,
        transform=_TRANSFORM,
        crs="EPSG:5186",
        polygon_geojson=_ZONE,
        from_crs="EPSG:5186",
        minimum_boundary_valid_fraction=0.1,
        maximum_zone_grid_cells=64,
    )
    assert isinstance(surface, ExternalVolumeMeasurementError)
    assert surface.reason is ExternalVolumeMeasurementErrorReason.BOUNDARY_SAMPLES_INSUFFICIENT


def test_measurement_is_deterministic() -> None:
    dsm = _with_box(_ground(slope_x=0.25), 1.5)
    dsm[2, 4] += 0.3
    first, second = _measure(dsm), _measure(dsm)
    assert isinstance(first, ExternalSingleVolumeZoneMeasurement)
    assert isinstance(second, ExternalSingleVolumeZoneMeasurement)
    assert first.metrics.model_dump() == second.metrics.model_dump()
