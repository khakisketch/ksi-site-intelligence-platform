"""Bounded full-zone math for externally produced relative-volume inputs.

This import-only module has no durable authority.  It measures a Core-bound
request's already aligned difference grid and returns an explicit typed error
when an external zone cannot be measured without inventing coverage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from numbers import Real
from typing import Any

import numpy as np
from ksi_event_contracts.external_relative_volume import ExternalVolumeMetricsV1
from ksi_event_contracts.work_area import assert_polygon_is_usable
from ksi_geo_spatial.crs import (
    assert_supported_project_crs,
    normalise_crs,
    reproject_geometry,
)
from rasterio import features, windows
from rasterio.errors import RasterioError
from rasterio.transform import Affine, array_bounds

from ksi_change_detection.dsm_diff import DiffResult, _same_frame


class ExternalVolumeMeasurementErrorReason(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_ZONE = "INVALID_ZONE"
    EMPTY_ZONE = "EMPTY_ZONE"
    OVERSIZED_ZONE = "OVERSIZED_ZONE"
    EMPTY_COMMON_VALID_COVERAGE = "EMPTY_COMMON_VALID_COVERAGE"
    INSUFFICIENT_COMMON_VALID_COVERAGE = "INSUFFICIENT_COMMON_VALID_COVERAGE"
    INSUFFICIENT_BOUNDARY_COVERAGE = "INSUFFICIENT_BOUNDARY_COVERAGE"
    BOUNDARY_SAMPLES_INSUFFICIENT = "BOUNDARY_SAMPLES_INSUFFICIENT"


@dataclass(frozen=True, slots=True)
class ExternalVolumeMeasurementError:
    """Fail-closed result with no numeric metrics."""

    reason: ExternalVolumeMeasurementErrorReason
    detail: str
    zone_cell_count: int | None = None
    common_valid_cell_count: int | None = None
    metrics: None = None


@dataclass(frozen=True, slots=True)
class ExternalVolumeZoneMeasurement:
    """Detailed metrics for one full baseline-grid zone."""

    zone_id: str
    metrics: ExternalVolumeMetricsV1


@dataclass(frozen=True, slots=True)
class ExternalVolumeZoneCoverageMeasurement:
    """Fixed-profile metrics plus lossless masks on the complete zone window.

    The caller owns serialising the masks.  Arrays are intentionally returned
    only by this import-only algorithm, never by the pre-existing V1 metric
    surface, so the latter's wire behavior remains unchanged.
    """

    zone_id: str
    metrics: ExternalVolumeMetricsV1
    row_offset: int
    column_offset: int
    selected_mask: np.ndarray[Any, np.dtype[np.bool_]]
    common_valid_mask: np.ndarray[Any, np.dtype[np.bool_]]
    unavailable_mask: np.ndarray[Any, np.dtype[np.bool_]]
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class _ValidatedParameters:
    zone_id: str
    threshold_m: float
    minimum_common_valid_fraction: float
    maximum_zone_grid_cells: int
    baseline_rmse_m: float | None
    current_rmse_m: float | None


@dataclass(frozen=True, slots=True)
class _ValidatedDiffGrid:
    """The only baseline grid shape supported by the full-zone window algorithm."""

    transform: Affine
    crs: str
    cell_area_m2: float


def _error(
    reason: ExternalVolumeMeasurementErrorReason,
    detail: str,
    *,
    zone_cell_count: int | None = None,
    common_valid_cell_count: int | None = None,
) -> ExternalVolumeMeasurementError:
    return ExternalVolumeMeasurementError(
        reason=reason,
        detail=detail,
        zone_cell_count=zone_cell_count,
        common_valid_cell_count=common_valid_cell_count,
    )


def _finite_float(value: object) -> float | None:
    if not isinstance(value, Real) or isinstance(value, bool):
        return None
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _validate_parameters(
    *,
    zone_id: object,
    threshold_m: object,
    minimum_common_valid_fraction: object,
    maximum_zone_grid_cells: object,
    baseline_rmse_m: object,
    current_rmse_m: object,
) -> _ValidatedParameters | ExternalVolumeMeasurementError:
    if not isinstance(zone_id, str) or not zone_id.strip():
        return _error(ExternalVolumeMeasurementErrorReason.INVALID_INPUT, "zone_id must be text")
    finite_threshold = _finite_float(threshold_m)
    if finite_threshold is None or finite_threshold < 0.0:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "threshold_m must be a finite number greater than or equal to zero",
        )
    finite_minimum_coverage = _finite_float(minimum_common_valid_fraction)
    if finite_minimum_coverage is None or not 0.0 < finite_minimum_coverage <= 1.0:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "minimum_common_valid_fraction must be finite and in (0, 1]",
        )
    if (
        isinstance(maximum_zone_grid_cells, bool)
        or not isinstance(maximum_zone_grid_cells, int)
        or maximum_zone_grid_cells <= 0
    ):
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "maximum_zone_grid_cells must be a positive integer and not bool",
        )
    finite_rmses: list[float | None] = []
    for name, rmse in (
        ("baseline_rmse_m", baseline_rmse_m),
        ("current_rmse_m", current_rmse_m),
    ):
        finite_rmse = None if rmse is None else _finite_float(rmse)
        if (
            finite_rmse is None
            and rmse is not None
            or (finite_rmse is not None and finite_rmse < 0.0)
        ):
            return _error(
                ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
                f"{name} must be None or a finite number greater than or equal to zero",
            )
        finite_rmses.append(finite_rmse)
    return _ValidatedParameters(
        zone_id=zone_id,
        threshold_m=finite_threshold,
        minimum_common_valid_fraction=finite_minimum_coverage,
        maximum_zone_grid_cells=maximum_zone_grid_cells,
        baseline_rmse_m=finite_rmses[0],
        current_rmse_m=finite_rmses[1],
    )


def _validate_diff_grid(diff: object) -> _ValidatedDiffGrid | ExternalVolumeMeasurementError:
    """Reject malformed direct ``DiffResult`` input before it can produce metre values."""
    if not isinstance(diff, DiffResult):
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "diff must be a DiffResult",
        )
    if not isinstance(diff.diff_m, np.ndarray) or not isinstance(diff.valid, np.ndarray):
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "DiffResult diff_m and valid must be numpy arrays",
        )
    if diff.diff_m.ndim != 2 or diff.valid.ndim != 2 or diff.valid.shape != diff.diff_m.shape:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "DiffResult must contain equal-shape 2D arrays",
        )
    if (
        not np.issubdtype(diff.diff_m.dtype, np.number)
        or np.issubdtype(diff.diff_m.dtype, np.complexfloating)
        or np.issubdtype(diff.diff_m.dtype, np.bool_)
        or not bool(np.isfinite(diff.diff_m).all())
    ):
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "DiffResult diff_m must be a finite real numeric array",
        )
    if diff.valid.dtype != np.dtype(np.bool_):
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "DiffResult valid must be a boolean array",
        )
    if not isinstance(diff.crs, str):
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "DiffResult crs must be a supported projected-meter CRS string",
        )
    try:
        crs = assert_supported_project_crs(diff.crs)
    except (AttributeError, TypeError, ValueError) as exc:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            f"DiffResult crs is not a supported projected-meter CRS: {exc}",
        )
    if not isinstance(diff.transform, Affine):
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "DiffResult transform must be an Affine",
        )
    coefficients = (
        diff.transform.a,
        diff.transform.b,
        diff.transform.c,
        diff.transform.d,
        diff.transform.e,
        diff.transform.f,
    )
    if any(_finite_float(value) is None for value in coefficients):
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "DiffResult transform coefficients must be finite",
        )
    if diff.transform.b != 0.0 or diff.transform.d != 0.0:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "DiffResult transform rotation or shear is unsupported",
        )
    if diff.transform.a <= 0.0 or diff.transform.e >= 0.0:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "DiffResult transform must be north-up with positive x and negative y scale",
        )
    determinant = diff.transform.a * diff.transform.e - diff.transform.b * diff.transform.d
    if not math.isfinite(determinant) or determinant == 0.0:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "DiffResult transform must be finite and invertible",
        )
    derived_cell_area_m2 = abs(determinant)
    reported_cell_area_m2 = _finite_float(diff.cell_area_m2)
    if (
        reported_cell_area_m2 is None
        or reported_cell_area_m2 <= 0.0
        or not math.isclose(
            reported_cell_area_m2,
            derived_cell_area_m2,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
    ):
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "DiffResult cell_area_m2 must be finite, positive, and agree with the affine "
            "determinant",
        )
    return _ValidatedDiffGrid(
        transform=diff.transform,
        crs=crs,
        cell_area_m2=derived_cell_area_m2,
    )


def _full_window(
    geometry: dict[str, Any], transform: Affine, maximum_zone_grid_cells: int
) -> tuple[int, int, int, int] | ExternalVolumeMeasurementError:
    try:
        left, bottom, right, top = features.bounds(geometry)
        if not all(_finite_float(value) is not None for value in (left, bottom, right, top)):
            return _error(
                ExternalVolumeMeasurementErrorReason.INVALID_ZONE,
                "zone bounds are non-finite",
            )
        window = windows.from_bounds(left, bottom, right, top, transform=transform)
        values = (window.col_off, window.row_off, window.width, window.height)
        if not all(_finite_float(value) is not None for value in values):
            return _error(
                ExternalVolumeMeasurementErrorReason.INVALID_ZONE,
                "zone grid window is non-finite",
            )
        col_start = math.floor(window.col_off)
        row_start = math.floor(window.row_off)
        col_stop = math.ceil(window.col_off + window.width)
        row_stop = math.ceil(window.row_off + window.height)
    except (RasterioError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_ZONE,
            f"zone bounds cannot be converted to the baseline grid: {exc}",
        )
    width = col_stop - col_start
    height = row_stop - row_start
    if width <= 0 or height <= 0:
        return _error(ExternalVolumeMeasurementErrorReason.EMPTY_ZONE, "zone has no grid cells")
    # The multiplication happens before any mask allocation.  Python ints keep
    # the check exact even when hostile coordinates imply enormous extents.
    if width * height > maximum_zone_grid_cells:
        return _error(
            ExternalVolumeMeasurementErrorReason.OVERSIZED_ZONE,
            "full baseline-grid zone exceeds maximum_zone_grid_cells",
        )
    return row_start, row_stop, col_start, col_stop


def _masked_full_zone(
    geometry: dict[str, Any],
    *,
    transform: Affine,
    row_start: int,
    row_stop: int,
    col_start: int,
    col_stop: int,
) -> np.ndarray[Any, np.dtype[np.bool_]] | ExternalVolumeMeasurementError:
    try:
        local_transform = transform * Affine.translation(col_start, row_start)
        return features.geometry_mask(
            [geometry],
            out_shape=(row_stop - row_start, col_stop - col_start),
            transform=local_transform,
            invert=True,
            all_touched=False,
        )
    except (RasterioError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_ZONE,
            f"zone cannot be rasterized on the baseline grid: {exc}",
        )


def measure_external_volume_zone(
    diff: DiffResult,
    polygon_geojson: dict[str, Any],
    *,
    zone_id: str,
    from_crs: str,
    threshold_m: float,
    minimum_common_valid_fraction: float,
    maximum_zone_grid_cells: int,
    uncertainty_note: str,
    baseline_rmse_m: float | None = None,
    current_rmse_m: float | None = None,
) -> ExternalVolumeZoneMeasurement | ExternalVolumeMeasurementError:
    """Measure a polygon against the complete baseline-grid zone, or fail closed.

    Unlike the managed compatibility helper, cells selected by the zone but
    outside the supplied difference raster remain in the coverage denominator.
    This makes an incomplete external raster explicitly insufficient instead
    of silently measuring only its footprint.
    """
    parameter_error = _validate_parameters(
        zone_id=zone_id,
        threshold_m=threshold_m,
        minimum_common_valid_fraction=minimum_common_valid_fraction,
        maximum_zone_grid_cells=maximum_zone_grid_cells,
        baseline_rmse_m=baseline_rmse_m,
        current_rmse_m=current_rmse_m,
    )
    if isinstance(parameter_error, ExternalVolumeMeasurementError):
        return parameter_error
    parameters = parameter_error

    validated_grid = _validate_diff_grid(diff)
    if isinstance(validated_grid, ExternalVolumeMeasurementError):
        return validated_grid
    if not isinstance(from_crs, str) or not from_crs.strip():
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "from_crs must be a non-empty CRS string",
        )

    try:
        source_crs = normalise_crs(from_crs)
        assert_polygon_is_usable(polygon_geojson, crs=source_crs)
        geometry = (
            polygon_geojson
            if _same_frame(source_crs, validated_grid.crs)
            else reproject_geometry(
                polygon_geojson,
                from_crs=source_crs,
                to_crs=validated_grid.crs,
            )
        )
        assert_polygon_is_usable(geometry, crs=validated_grid.crs)
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_ZONE,
            f"zone geometry is invalid or cannot be projected: {exc}",
        )

    window = _full_window(
        geometry,
        validated_grid.transform,
        parameters.maximum_zone_grid_cells,
    )
    if isinstance(window, ExternalVolumeMeasurementError):
        return window
    row_start, row_stop, col_start, col_stop = window
    zone_mask = _masked_full_zone(
        geometry,
        transform=validated_grid.transform,
        row_start=row_start,
        row_stop=row_stop,
        col_start=col_start,
        col_stop=col_stop,
    )
    if isinstance(zone_mask, ExternalVolumeMeasurementError):
        return zone_mask

    zone_cell_count = int(zone_mask.sum())
    if zone_cell_count == 0:
        return _error(
            ExternalVolumeMeasurementErrorReason.EMPTY_ZONE,
            "zone selects no baseline-grid cell centers",
        )

    available = np.zeros(zone_mask.shape, dtype=np.bool_)
    delta = np.zeros(zone_mask.shape, dtype=np.float64)
    source_row_start = max(0, row_start)
    source_row_stop = min(diff.diff_m.shape[0], row_stop)
    source_col_start = max(0, col_start)
    source_col_stop = min(diff.diff_m.shape[1], col_stop)
    if source_row_start < source_row_stop and source_col_start < source_col_stop:
        target_rows = slice(source_row_start - row_start, source_row_stop - row_start)
        target_cols = slice(source_col_start - col_start, source_col_stop - col_start)
        source_rows = slice(source_row_start, source_row_stop)
        source_cols = slice(source_col_start, source_col_stop)
        available[target_rows, target_cols] = diff.valid[source_rows, source_cols]
        delta[target_rows, target_cols] = diff.diff_m[source_rows, source_cols]

    common_mask = zone_mask & available
    common_valid_cell_count = int(common_mask.sum())
    if common_valid_cell_count == 0:
        return _error(
            ExternalVolumeMeasurementErrorReason.EMPTY_COMMON_VALID_COVERAGE,
            "zone has no common valid DSM cells",
            zone_cell_count=zone_cell_count,
            common_valid_cell_count=common_valid_cell_count,
        )
    common_valid_fraction = common_valid_cell_count / zone_cell_count
    if common_valid_fraction < parameters.minimum_common_valid_fraction:
        return _error(
            ExternalVolumeMeasurementErrorReason.INSUFFICIENT_COMMON_VALID_COVERAGE,
            "common valid DSM coverage is below the supplied policy minimum",
            zone_cell_count=zone_cell_count,
            common_valid_cell_count=common_valid_cell_count,
        )

    common_delta = delta[common_mask]
    counted = np.abs(common_delta) >= parameters.threshold_m
    fill_m3 = float(
        common_delta[counted & (common_delta > 0.0)].sum() * validated_grid.cell_area_m2
    )
    cut_m3 = float(
        -common_delta[counted & (common_delta < 0.0)].sum() * validated_grid.cell_area_m2
    )
    zone_area_m2 = float(zone_cell_count * validated_grid.cell_area_m2)
    measured_area_m2 = float(common_valid_cell_count * validated_grid.cell_area_m2)
    uncertainty_m3 = None
    if parameters.baseline_rmse_m is not None and parameters.current_rmse_m is not None:
        uncertainty_m3 = measured_area_m2 * math.hypot(
            parameters.baseline_rmse_m, parameters.current_rmse_m
        )
    try:
        metrics = ExternalVolumeMetricsV1(
            zone_cell_count=zone_cell_count,
            common_valid_cell_count=common_valid_cell_count,
            zone_area_m2=zone_area_m2,
            measured_area_m2=measured_area_m2,
            common_valid_fraction=common_valid_fraction,
            cut_m3=cut_m3,
            fill_m3=fill_m3,
            net_m3=fill_m3 - cut_m3,
            threshold_m=parameters.threshold_m,
            uncertainty_m3=uncertainty_m3,
            uncertainty_note=uncertainty_note,
        )
    except ValueError as exc:
        return _error(ExternalVolumeMeasurementErrorReason.INVALID_INPUT, str(exc))
    return ExternalVolumeZoneMeasurement(zone_id=parameters.zone_id, metrics=metrics)


def measure_fixed_profile_external_volume_zone(
    diff: DiffResult,
    polygon_geojson: dict[str, Any],
    *,
    zone_id: str,
    from_crs: str,
    maximum_zone_grid_cells: int,
) -> ExternalVolumeZoneCoverageMeasurement | ExternalVolumeMeasurementError:
    """Measure the non-relaxable V2 profile and retain its complete mask facts.

    This has the same grid, interpolation-independent full-zone selection and
    coverage denominator as :func:`measure_external_volume_zone`, but fixes
    the approved values ``threshold_m=0`` and ``minimum_common_valid_fraction=1``.
    Exact-zero deltas are valid common cells and affect neither cut nor fill;
    they are not threshold exclusions.
    """
    parameter_error = _validate_parameters(
        zone_id=zone_id,
        threshold_m=0.0,
        minimum_common_valid_fraction=1.0,
        maximum_zone_grid_cells=maximum_zone_grid_cells,
        baseline_rmse_m=None,
        current_rmse_m=None,
    )
    if isinstance(parameter_error, ExternalVolumeMeasurementError):
        return parameter_error
    parameters = parameter_error
    validated_grid = _validate_diff_grid(diff)
    if isinstance(validated_grid, ExternalVolumeMeasurementError):
        return validated_grid
    if not isinstance(from_crs, str) or not from_crs.strip():
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "from_crs must be a non-empty CRS string",
        )
    try:
        source_crs = normalise_crs(from_crs)
        assert_polygon_is_usable(polygon_geojson, crs=source_crs)
        geometry = (
            polygon_geojson
            if _same_frame(source_crs, validated_grid.crs)
            else reproject_geometry(
                polygon_geojson,
                from_crs=source_crs,
                to_crs=validated_grid.crs,
            )
        )
        assert_polygon_is_usable(geometry, crs=validated_grid.crs)
    except (AttributeError, TypeError, ValueError, OverflowError) as exc:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_ZONE,
            f"zone geometry is invalid or cannot be projected: {exc}",
        )
    window = _full_window(geometry, validated_grid.transform, parameters.maximum_zone_grid_cells)
    if isinstance(window, ExternalVolumeMeasurementError):
        return window
    row_start, row_stop, col_start, col_stop = window
    selected = _masked_full_zone(
        geometry,
        transform=validated_grid.transform,
        row_start=row_start,
        row_stop=row_stop,
        col_start=col_start,
        col_stop=col_stop,
    )
    if isinstance(selected, ExternalVolumeMeasurementError):
        return selected
    selected_cell_count = int(selected.sum())
    if selected_cell_count == 0:
        return _error(
            ExternalVolumeMeasurementErrorReason.EMPTY_ZONE,
            "zone selects no baseline-grid cell centers",
        )
    available = np.zeros(selected.shape, dtype=np.bool_)
    delta = np.zeros(selected.shape, dtype=np.float64)
    source_row_start = max(0, row_start)
    source_row_stop = min(diff.diff_m.shape[0], row_stop)
    source_col_start = max(0, col_start)
    source_col_stop = min(diff.diff_m.shape[1], col_stop)
    if source_row_start < source_row_stop and source_col_start < source_col_stop:
        target_rows = slice(source_row_start - row_start, source_row_stop - row_start)
        target_cols = slice(source_col_start - col_start, source_col_stop - col_start)
        source_rows = slice(source_row_start, source_row_stop)
        source_cols = slice(source_col_start, source_col_stop)
        available[target_rows, target_cols] = diff.valid[source_rows, source_cols]
        delta[target_rows, target_cols] = diff.diff_m[source_rows, source_cols]
    common = selected & available
    unavailable = selected & ~available
    common_valid_cell_count = int(common.sum())
    if common_valid_cell_count == 0:
        return _error(
            ExternalVolumeMeasurementErrorReason.EMPTY_COMMON_VALID_COVERAGE,
            "zone has no common valid DSM cells",
            zone_cell_count=selected_cell_count,
            common_valid_cell_count=0,
        )
    if common_valid_cell_count != selected_cell_count:
        return _error(
            ExternalVolumeMeasurementErrorReason.INSUFFICIENT_COMMON_VALID_COVERAGE,
            "fixed profile requires every selected zone cell to be commonly valid",
            zone_cell_count=selected_cell_count,
            common_valid_cell_count=common_valid_cell_count,
        )
    common_delta = delta[common]
    fill_m3 = float(common_delta[common_delta > 0.0].sum() * validated_grid.cell_area_m2)
    cut_m3 = float(-common_delta[common_delta < 0.0].sum() * validated_grid.cell_area_m2)
    zone_area_m2 = float(selected_cell_count * validated_grid.cell_area_m2)
    try:
        metrics = ExternalVolumeMetricsV1(
            zone_cell_count=selected_cell_count,
            common_valid_cell_count=common_valid_cell_count,
            zone_area_m2=zone_area_m2,
            measured_area_m2=zone_area_m2,
            common_valid_fraction=1.0,
            cut_m3=cut_m3,
            fill_m3=fill_m3,
            net_m3=fill_m3 - cut_m3,
            threshold_m=0.0,
            uncertainty_m3=None,
            uncertainty_note="Fixed V2 profile does not calculate uncertaintyM3.",
        )
    except ValueError as exc:
        return _error(ExternalVolumeMeasurementErrorReason.INVALID_INPUT, str(exc))
    local_transform = validated_grid.transform * Affine.translation(col_start, row_start)
    try:
        left, bottom, right, top = (
            float(value)
            for value in array_bounds(selected.shape[0], selected.shape[1], local_transform)
        )
        bounds = (left, bottom, right, top)
    except (TypeError, ValueError, OverflowError) as exc:
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            f"zone bounds cannot be represented: {exc}",
        )
    if not all(math.isfinite(value) for value in bounds):
        return _error(
            ExternalVolumeMeasurementErrorReason.INVALID_INPUT,
            "zone bounds cannot be represented as finite values",
        )
    return ExternalVolumeZoneCoverageMeasurement(
        zone_id=parameters.zone_id,
        metrics=metrics,
        row_offset=row_start,
        column_offset=col_start,
        selected_mask=selected,
        common_valid_mask=common,
        unavailable_mask=unavailable,
        bounds=bounds,
    )


__all__ = [
    "ExternalVolumeMeasurementError",
    "ExternalVolumeMeasurementErrorReason",
    "ExternalVolumeZoneCoverageMeasurement",
    "ExternalVolumeZoneMeasurement",
    "measure_fixed_profile_external_volume_zone",
    "measure_external_volume_zone",
]
