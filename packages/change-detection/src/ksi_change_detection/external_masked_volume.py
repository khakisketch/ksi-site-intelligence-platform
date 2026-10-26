"""Masked-profile external volume math for independently supplied exclusion rasters.

This import-only module has no durable authority.  It measures a Core-bound
request's already aligned difference grid against a WorkArea polygon with an
independently supplied binary exclusion mask, and returns an explicit typed
error when the masked zone cannot be measured without inventing coverage.

The fixed V2 profile (``measure_fixed_profile_external_volume_zone``) is
never reinterpreted here: polygon holes exclude first, the mask only removes
cells from the already hole-selected set, and the surviving effective cells
still require 100% common-valid coverage.  The mask never enters
``diff.valid`` and therefore can never be read as complete coverage.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import numpy as np
from ksi_event_contracts.external_relative_volume import ExternalVolumeMetricsV1
from ksi_event_contracts.work_area import assert_polygon_is_usable
from ksi_geo_spatial.crs import normalise_crs, reproject_geometry
from rasterio.transform import Affine, array_bounds

from ksi_change_detection.dsm_diff import DiffResult, _same_frame
from ksi_change_detection.external_volume import (
    ExternalVolumeMeasurementError,
    _full_window,
    _masked_full_zone,
    _validate_diff_grid,
    _validate_parameters,
)


class MaskedExternalVolumeErrorReason(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    INVALID_ZONE = "INVALID_ZONE"
    EMPTY_ZONE = "EMPTY_ZONE"
    ALL_MASKED = "ALL_MASKED"
    OVERSIZED_ZONE = "OVERSIZED_ZONE"
    EMPTY_COMMON_VALID_COVERAGE = "EMPTY_COMMON_VALID_COVERAGE"
    INSUFFICIENT_COMMON_VALID_COVERAGE = "INSUFFICIENT_COMMON_VALID_COVERAGE"


@dataclass(frozen=True, slots=True)
class MaskedExternalVolumeError:
    """Fail-closed result with no numeric metrics."""

    reason: MaskedExternalVolumeErrorReason
    detail: str
    original_selected_cell_count: int | None = None
    mask_excluded_cell_count: int | None = None
    effective_selected_cell_count: int | None = None
    common_valid_cell_count: int | None = None
    metrics: None = None


@dataclass(frozen=True, slots=True)
class MaskedExternalVolumeZoneMeasurement:
    """Fixed-threshold masked-profile metrics plus lossless window facts.

    ``delta_grid_m`` is cropped to the same full baseline-grid window as the
    masks and carries ``NaN`` on every cell that is not a final effective
    common-valid cell, so unknown or excluded cells can never be exported as
    zero-valued claims.  The caller owns serialising the arrays.
    """

    zone_id: str
    metrics: ExternalVolumeMetricsV1
    row_offset: int
    column_offset: int
    original_selected_cell_count: int
    mask_excluded_cell_count: int
    effective_selected_cell_count: int
    common_valid_cell_count: int
    original_selected_mask: np.ndarray[Any, np.dtype[np.bool_]]
    mask_excluded_mask: np.ndarray[Any, np.dtype[np.bool_]]
    effective_selected_mask: np.ndarray[Any, np.dtype[np.bool_]]
    common_valid_mask: np.ndarray[Any, np.dtype[np.bool_]]
    unavailable_mask: np.ndarray[Any, np.dtype[np.bool_]]
    delta_grid_m: np.ndarray[Any, np.dtype[np.float64]]
    bounds: tuple[float, float, float, float]


def _fail(
    reason: MaskedExternalVolumeErrorReason,
    detail: str,
    *,
    original_selected_cell_count: int | None = None,
    mask_excluded_cell_count: int | None = None,
    effective_selected_cell_count: int | None = None,
    common_valid_cell_count: int | None = None,
) -> MaskedExternalVolumeError:
    return MaskedExternalVolumeError(
        reason=reason,
        detail=detail,
        original_selected_cell_count=original_selected_cell_count,
        mask_excluded_cell_count=mask_excluded_cell_count,
        effective_selected_cell_count=effective_selected_cell_count,
        common_valid_cell_count=common_valid_cell_count,
    )


def _as_v1_error_reason(reason: MaskedExternalVolumeErrorReason) -> str:
    return reason.value


def _validate_mask(
    *,
    exclusion_mask: object,
    mask_crs: object,
    mask_transform: object,
    diff_shape: tuple[int, int],
    diff_transform: Affine,
    diff_crs: str,
) -> tuple[np.ndarray[Any, np.dtype[np.uint8]], str] | MaskedExternalVolumeError:
    """Reject any mask that is not an exact uint8 binary full-baseline grid."""
    if not isinstance(mask_crs, str) or not mask_crs.strip():
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            "mask_crs must be a non-empty CRS string",
        )
    if not isinstance(mask_transform, Affine):
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            "mask_transform must be an Affine",
        )
    if mask_transform != diff_transform:
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            "mask_transform must exactly equal the baseline grid transform (no resampling)",
        )
    try:
        normalised_mask_crs = normalise_crs(mask_crs)
    except (AttributeError, TypeError, ValueError) as exc:
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            f"mask_crs is not a usable CRS string: {exc}",
        )
    if not _same_frame(normalised_mask_crs, diff_crs):
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            "mask_crs must match the baseline grid CRS (no reprojection)",
        )
    if np.ma.isMaskedArray(exclusion_mask):
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            "exclusion_mask must not carry masked/NoData cells",
        )
    if not isinstance(exclusion_mask, np.ndarray):
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            "exclusion_mask must be a numpy array",
        )
    if exclusion_mask.dtype != np.dtype(np.uint8):
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            "exclusion_mask must have uint8 dtype exactly (no float/bool/int cast)",
        )
    if exclusion_mask.ndim != 2:
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            "exclusion_mask must be a 2D array",
        )
    if exclusion_mask.shape != diff_shape:
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            "exclusion_mask must have exactly the baseline grid shape (no resampling)",
        )
    values = np.unique(exclusion_mask)
    if values.size == 0 or bool(((values != 0) & (values != 1)).any()):
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            "exclusion_mask values must be only 0 (retain) or 1 (exclude)",
        )
    return exclusion_mask, normalised_mask_crs


def measure_masked_external_volume_zone(
    diff: DiffResult,
    polygon_geojson: dict[str, Any],
    *,
    zone_id: str,
    from_crs: str,
    exclusion_mask: np.ndarray[Any, np.dtype[np.uint8]],
    mask_crs: str,
    mask_transform: Affine,
    maximum_zone_grid_cells: int,
) -> MaskedExternalVolumeZoneMeasurement | MaskedExternalVolumeError:
    """Measure a polygon after binary mask exclusion, or fail closed.

    Polygon holes exclude first: the mask only removes cells from the already
    hole-selected set and is never consulted for cells the polygon did not
    select.  The surviving effective cells still require 100% common-valid
    coverage at fixed ``threshold_m=0`` with null uncertainty.  Nothing here
    mutates ``diff`` or ``exclusion_mask``.
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
        return _fail(
            MaskedExternalVolumeErrorReason(_as_v1_error_reason(parameter_error.reason)),
            parameter_error.detail,
        )
    parameters = parameter_error

    validated_grid = _validate_diff_grid(diff)
    if isinstance(validated_grid, ExternalVolumeMeasurementError):
        return _fail(
            MaskedExternalVolumeErrorReason(_as_v1_error_reason(validated_grid.reason)),
            validated_grid.detail,
        )
    if not isinstance(from_crs, str) or not from_crs.strip():
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            "from_crs must be a non-empty CRS string",
        )

    mask_result = _validate_mask(
        exclusion_mask=exclusion_mask,
        mask_crs=mask_crs,
        mask_transform=mask_transform,
        diff_shape=(diff.diff_m.shape[0], diff.diff_m.shape[1]),
        diff_transform=validated_grid.transform,
        diff_crs=validated_grid.crs,
    )
    if isinstance(mask_result, MaskedExternalVolumeError):
        return mask_result
    mask_array, _ = mask_result

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
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_ZONE,
            f"zone geometry is invalid or cannot be projected: {exc}",
        )

    window = _full_window(geometry, validated_grid.transform, parameters.maximum_zone_grid_cells)
    if isinstance(window, ExternalVolumeMeasurementError):
        return _fail(
            MaskedExternalVolumeErrorReason(_as_v1_error_reason(window.reason)),
            window.detail,
        )
    row_start, row_stop, col_start, col_stop = window

    original = _masked_full_zone(
        geometry,
        transform=validated_grid.transform,
        row_start=row_start,
        row_stop=row_stop,
        col_start=col_start,
        col_stop=col_stop,
    )
    if isinstance(original, ExternalVolumeMeasurementError):
        return _fail(
            MaskedExternalVolumeErrorReason(_as_v1_error_reason(original.reason)),
            original.detail,
        )
    original_selected = original.copy()
    original_cell_count = int(original_selected.sum())
    if original_cell_count == 0:
        return _fail(
            MaskedExternalVolumeErrorReason.EMPTY_ZONE,
            "zone selects no baseline-grid cell centers",
        )

    # The mask lives on the full baseline grid; the window may extend beyond
    # it.  Cells outside the grid have no mask value and stay non-excluded so
    # they surface as unavailable instead of silently vanishing.
    mask_excluded = np.zeros(original_selected.shape, dtype=np.bool_)
    source_row_start = max(0, row_start)
    source_row_stop = min(diff.diff_m.shape[0], row_stop)
    source_col_start = max(0, col_start)
    source_col_stop = min(diff.diff_m.shape[1], col_stop)
    has_overlap = source_row_start < source_row_stop and source_col_start < source_col_stop
    if has_overlap:
        target_rows = slice(source_row_start - row_start, source_row_stop - row_start)
        target_cols = slice(source_col_start - col_start, source_col_stop - col_start)
        source_rows = slice(source_row_start, source_row_stop)
        source_cols = slice(source_col_start, source_col_stop)
        mask_excluded[target_rows, target_cols] = mask_array[source_rows, source_cols] == 1
    mask_excluded_in_zone = original_selected & mask_excluded
    mask_excluded_cell_count = int(mask_excluded_in_zone.sum())

    effective = original_selected & ~mask_excluded_in_zone
    effective_cell_count = int(effective.sum())
    if effective_cell_count == 0:
        return _fail(
            MaskedExternalVolumeErrorReason.ALL_MASKED,
            "exclusion mask removes every selected zone cell",
            original_selected_cell_count=original_cell_count,
            mask_excluded_cell_count=mask_excluded_cell_count,
            effective_selected_cell_count=0,
            common_valid_cell_count=0,
        )

    available = np.zeros(effective.shape, dtype=np.bool_)
    work_delta = np.zeros(effective.shape, dtype=np.float64)
    if has_overlap:
        available[target_rows, target_cols] = diff.valid[source_rows, source_cols]
        work_delta[target_rows, target_cols] = diff.diff_m[source_rows, source_cols]

    common = effective & available
    unavailable = effective & ~available
    common_valid_cell_count = int(common.sum())
    if common_valid_cell_count == 0:
        return _fail(
            MaskedExternalVolumeErrorReason.EMPTY_COMMON_VALID_COVERAGE,
            "effective zone has no common valid DSM cells",
            original_selected_cell_count=original_cell_count,
            mask_excluded_cell_count=mask_excluded_cell_count,
            effective_selected_cell_count=effective_cell_count,
            common_valid_cell_count=0,
        )
    if common_valid_cell_count != effective_cell_count:
        return _fail(
            MaskedExternalVolumeErrorReason.INSUFFICIENT_COMMON_VALID_COVERAGE,
            "masked profile requires every effective selected zone cell to be commonly valid",
            original_selected_cell_count=original_cell_count,
            mask_excluded_cell_count=mask_excluded_cell_count,
            effective_selected_cell_count=effective_cell_count,
            common_valid_cell_count=common_valid_cell_count,
        )

    common_delta = work_delta[common]
    fill_m3 = float(common_delta[common_delta > 0.0].sum() * validated_grid.cell_area_m2)
    cut_m3 = float(-common_delta[common_delta < 0.0].sum() * validated_grid.cell_area_m2)
    zone_area_m2 = float(effective_cell_count * validated_grid.cell_area_m2)
    try:
        metrics = ExternalVolumeMetricsV1(
            zone_cell_count=effective_cell_count,
            common_valid_cell_count=common_valid_cell_count,
            zone_area_m2=zone_area_m2,
            measured_area_m2=zone_area_m2,
            common_valid_fraction=1.0,
            cut_m3=cut_m3,
            fill_m3=fill_m3,
            net_m3=fill_m3 - cut_m3,
            threshold_m=0.0,
            uncertainty_m3=None,
            uncertainty_note="Masked external profile does not calculate uncertaintyM3.",
        )
    except ValueError as exc:
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            str(exc),
            original_selected_cell_count=original_cell_count,
            mask_excluded_cell_count=mask_excluded_cell_count,
            effective_selected_cell_count=effective_cell_count,
            common_valid_cell_count=common_valid_cell_count,
        )

    delta_grid = np.full(effective.shape, np.nan, dtype=np.float64)
    delta_grid[common] = work_delta[common]

    local_transform = validated_grid.transform * Affine.translation(col_start, row_start)
    try:
        left, bottom, right, top = (
            float(value)
            for value in array_bounds(effective.shape[0], effective.shape[1], local_transform)
        )
        bounds = (left, bottom, right, top)
    except (TypeError, ValueError, OverflowError) as exc:
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            f"zone bounds cannot be represented: {exc}",
        )
    if not all(math.isfinite(value) for value in bounds):
        return _fail(
            MaskedExternalVolumeErrorReason.INVALID_INPUT,
            "zone bounds cannot be represented as finite values",
        )

    return MaskedExternalVolumeZoneMeasurement(
        zone_id=parameters.zone_id,
        metrics=metrics,
        row_offset=row_start,
        column_offset=col_start,
        original_selected_cell_count=original_cell_count,
        mask_excluded_cell_count=mask_excluded_cell_count,
        effective_selected_cell_count=effective_cell_count,
        common_valid_cell_count=common_valid_cell_count,
        original_selected_mask=original_selected,
        mask_excluded_mask=mask_excluded_in_zone,
        effective_selected_mask=effective,
        common_valid_mask=common,
        unavailable_mask=unavailable,
        delta_grid_m=delta_grid,
        bounds=bounds,
    )


__all__ = [
    "MaskedExternalVolumeError",
    "MaskedExternalVolumeErrorReason",
    "MaskedExternalVolumeZoneMeasurement",
    "measure_masked_external_volume_zone",
]
