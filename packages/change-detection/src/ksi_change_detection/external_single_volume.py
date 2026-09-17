"""Single-epoch (stockpile) volume against a boundary-derived base surface.

Import-only, no durable authority.  The base surface is the linear
interpolation of the DSM elevation sampled on the zone boundary ring; cells
the interpolation cannot reach are unknown, never zero.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from ksi_event_contracts.external_single_volume import ExternalSingleVolumeMetricsV1
from ksi_event_contracts.work_area import assert_polygon_is_usable
from ksi_geo_spatial.crs import assert_supported_project_crs, normalise_crs, reproject_geometry
from rasterio.transform import Affine
from scipy.interpolate import LinearNDInterpolator

from ksi_change_detection.dsm_diff import DiffResult, _same_frame
from ksi_change_detection.external_volume import (
    ExternalVolumeMeasurementError,
    ExternalVolumeMeasurementErrorReason,
    _error,
    _full_window,
    _masked_full_zone,
    measure_external_volume_zone,
)


@dataclass(frozen=True, slots=True)
class BoundaryBaseSurface:
    """Base elevations on the zone window grid plus the boundary facts behind them."""

    base_m: np.ndarray
    valid: np.ndarray
    row_start: int
    col_start: int
    boundary_cell_count: int
    boundary_sample_count: int
    boundary_valid_fraction: float
    base_roughness_m: float


@dataclass(frozen=True, slots=True)
class ExternalSingleVolumeZoneMeasurement:
    zone_id: str
    metrics: ExternalSingleVolumeMetricsV1


def _grid_geometry(
    polygon_geojson: dict[str, Any], *, from_crs: str, grid_crs: str
) -> dict[str, Any] | ExternalVolumeMeasurementError:
    try:
        source = normalise_crs(from_crs)
        target = assert_supported_project_crs(grid_crs)
        assert_polygon_is_usable(polygon_geojson, crs=source)
        geometry = (
            polygon_geojson
            if _same_frame(source, target)
            else reproject_geometry(polygon_geojson, from_crs=source, to_crs=target)
        )
        assert_polygon_is_usable(geometry, crs=target)
        return geometry
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_ZONE,
            f"zone geometry is invalid or cannot be projected: {exc}",
        )


def _boundary_ring(zone: np.ndarray) -> np.ndarray:
    """Zone cells with at least one 4-neighbour outside the zone."""
    padded = np.pad(zone, 1, constant_values=False)
    interior = zone & padded[:-2, 1:-1] & padded[2:, 1:-1] & padded[1:-1, :-2] & padded[1:-1, 2:]
    return zone & ~interior


def derive_boundary_base_surface(
    dsm_m: np.ndarray,
    valid: np.ndarray,
    *,
    transform: Affine,
    crs: str,
    polygon_geojson: dict[str, Any],
    from_crs: str,
    minimum_boundary_valid_fraction: float,
    maximum_zone_grid_cells: int,
) -> BoundaryBaseSurface | ExternalVolumeMeasurementError:
    if (
        not isinstance(dsm_m, np.ndarray)
        or not isinstance(valid, np.ndarray)
        or dsm_m.ndim != 2
        or valid.shape != dsm_m.shape
        or valid.dtype != np.dtype(np.bool_)
    ):
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "dsm and valid must be equal-shape 2D arrays",
        )
    if not (0.0 < float(minimum_boundary_valid_fraction) <= 1.0):
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "minimum_boundary_valid_fraction must be in (0, 1]",
        )
    geometry = _grid_geometry(polygon_geojson, from_crs=from_crs, grid_crs=crs)
    if isinstance(geometry, ExternalVolumeMeasurementError):
        return geometry
    window = _full_window(geometry, transform, maximum_zone_grid_cells)
    if isinstance(window, ExternalVolumeMeasurementError):
        return window
    row_start, row_stop, col_start, col_stop = window
    zone = _masked_full_zone(
        geometry,
        transform=transform,
        row_start=row_start,
        row_stop=row_stop,
        col_start=col_start,
        col_stop=col_stop,
    )
    if isinstance(zone, ExternalVolumeMeasurementError):
        return zone
    if not zone.any():
        return _error(
            ExternalVolumeMeasurementErrorReason.EMPTY_ZONE, "zone selects no grid cell centers"
        )

    # DSM validity on the window grid; cells outside the raster stay invalid.
    window_valid = np.zeros(zone.shape, dtype=np.bool_)
    window_dsm = np.zeros(zone.shape, dtype=np.float64)
    r0, r1 = max(0, row_start), min(dsm_m.shape[0], row_stop)
    c0, c1 = max(0, col_start), min(dsm_m.shape[1], col_stop)
    if r0 < r1 and c0 < c1:
        window_valid[r0 - row_start : r1 - row_start, c0 - col_start : c1 - col_start] = valid[
            r0:r1, c0:c1
        ]
        window_dsm[r0 - row_start : r1 - row_start, c0 - col_start : c1 - col_start] = dsm_m[
            r0:r1, c0:c1
        ]

    ring = _boundary_ring(zone)
    boundary_cell_count = int(ring.sum())
    samples = ring & window_valid
    boundary_sample_count = int(samples.sum())
    boundary_valid_fraction = boundary_sample_count / boundary_cell_count
    if boundary_valid_fraction < minimum_boundary_valid_fraction:
        return _error(
            ExternalVolumeMeasurementErrorReason.INSUFFICIENT_BOUNDARY_COVERAGE,
            "valid boundary elevation coverage is below the supplied policy minimum",
            zone_cell_count=int(zone.sum()),
        )
    rows, cols = np.nonzero(samples)  # row-major order: deterministic
    xs, ys = transform * (cols + col_start + 0.5, rows + row_start + 0.5)
    points = np.column_stack((np.asarray(xs, dtype=np.float64), np.asarray(ys, dtype=np.float64)))
    z = window_dsm[rows, cols]
    centered = points - points.mean(axis=0)
    if boundary_sample_count < 3 or np.linalg.matrix_rank(centered, tol=1e-9) < 2:
        return _error(
            ExternalVolumeMeasurementErrorReason.BOUNDARY_SAMPLES_INSUFFICIENT,
            "boundary samples must span a plane (at least three non-collinear cells)",
        )
    design = np.column_stack((points, np.ones(boundary_sample_count)))
    coefficients, *_ = np.linalg.lstsq(design, z, rcond=None)
    residual = z - design @ coefficients
    base_roughness_m = float(math.sqrt(float(np.mean(residual * residual))))

    zone_rows, zone_cols = np.nonzero(zone)
    zx, zy = transform * (zone_cols + col_start + 0.5, zone_rows + row_start + 0.5)
    interpolated = LinearNDInterpolator(points, z)(
        np.column_stack((np.asarray(zx, dtype=np.float64), np.asarray(zy, dtype=np.float64)))
    )
    base = np.zeros(zone.shape, dtype=np.float64)
    base_valid = np.zeros(zone.shape, dtype=np.bool_)
    reachable = np.isfinite(interpolated)
    base[zone_rows[reachable], zone_cols[reachable]] = interpolated[reachable]
    base_valid[zone_rows[reachable], zone_cols[reachable]] = True
    return BoundaryBaseSurface(
        base_m=base,
        valid=base_valid,
        row_start=row_start,
        col_start=col_start,
        boundary_cell_count=boundary_cell_count,
        boundary_sample_count=boundary_sample_count,
        boundary_valid_fraction=boundary_valid_fraction,
        base_roughness_m=base_roughness_m,
    )


def measure_single_volume_zone(
    dsm_m: np.ndarray,
    valid: np.ndarray,
    *,
    transform: Affine,
    crs: str,
    cell_area_m2: float,
    polygon_geojson: dict[str, Any],
    zone_id: str,
    from_crs: str,
    threshold_m: float,
    minimum_common_valid_fraction: float,
    minimum_boundary_valid_fraction: float,
    maximum_zone_grid_cells: int,
    uncertainty_note: str,
    dsm_rmse_m: float | None,
) -> ExternalSingleVolumeZoneMeasurement | ExternalVolumeMeasurementError:
    surface = derive_boundary_base_surface(
        dsm_m,
        valid,
        transform=transform,
        crs=crs,
        polygon_geojson=polygon_geojson,
        from_crs=from_crs,
        minimum_boundary_valid_fraction=minimum_boundary_valid_fraction,
        maximum_zone_grid_cells=maximum_zone_grid_cells,
    )
    if isinstance(surface, ExternalVolumeMeasurementError):
        return surface
    diff = np.zeros(dsm_m.shape, dtype=np.float64)
    diff_valid = np.zeros(dsm_m.shape, dtype=np.bool_)
    height, width = surface.base_m.shape
    r0, r1 = max(0, surface.row_start), min(dsm_m.shape[0], surface.row_start + height)
    c0, c1 = max(0, surface.col_start), min(dsm_m.shape[1], surface.col_start + width)
    if r0 < r1 and c0 < c1:
        local = (
            slice(r0 - surface.row_start, r1 - surface.row_start),
            slice(c0 - surface.col_start, c1 - surface.col_start),
        )
        target = (slice(r0, r1), slice(c0, c1))
        both = surface.valid[local] & valid[target]
        diff_valid[target] = both
        diff[target] = np.where(both, dsm_m[target] - surface.base_m[local], 0.0)
    measured = measure_external_volume_zone(
        DiffResult(
            diff_m=diff, valid=diff_valid, transform=transform, crs=crs, cell_area_m2=cell_area_m2
        ),
        polygon_geojson,
        zone_id=zone_id,
        from_crs=from_crs,
        threshold_m=threshold_m,
        minimum_common_valid_fraction=minimum_common_valid_fraction,
        maximum_zone_grid_cells=maximum_zone_grid_cells,
        uncertainty_note=uncertainty_note,
        baseline_rmse_m=surface.base_roughness_m,
        current_rmse_m=dsm_rmse_m,
    )
    if isinstance(measured, ExternalVolumeMeasurementError):
        return measured
    try:
        metrics = ExternalSingleVolumeMetricsV1(
            **measured.metrics.model_dump(),
            base_roughness_m=surface.base_roughness_m,
            boundary_cell_count=surface.boundary_cell_count,
            boundary_sample_count=surface.boundary_sample_count,
            boundary_valid_fraction=surface.boundary_valid_fraction,
        )
    except ValueError as exc:
        return _error(ExternalVolumeMeasurementErrorReason.INVALID_INPUT, str(exc))
    return ExternalSingleVolumeZoneMeasurement(zone_id=zone_id, metrics=metrics)


__all__ = [
    "BoundaryBaseSurface",
    "ExternalSingleVolumeZoneMeasurement",
    "derive_boundary_base_surface",
    "measure_single_volume_zone",
]
