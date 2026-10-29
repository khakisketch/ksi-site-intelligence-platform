"""Masked-profile external volume tests with hand-derived grid values."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import ksi_change_detection.external_masked_volume as masked_volume
import numpy as np
import pytest
from ksi_change_detection.dsm_diff import DiffResult
from ksi_change_detection.external_masked_volume import (
    MaskedExternalVolumeError,
    MaskedExternalVolumeErrorReason,
    MaskedExternalVolumeZoneMeasurement,
    measure_masked_external_volume_zone,
)
from ksi_change_detection.external_volume import (
    ExternalVolumeMeasurementError,
    ExternalVolumeMeasurementErrorReason,
)
from rasterio.transform import Affine, from_origin

_TRANSFORM = from_origin(0.0, 2.0, 1.0, 1.0)
_CRS = "EPSG:5186"


def _diff(values: list[list[float]], *, valid: list[list[bool]] | None = None) -> DiffResult:
    array = np.array(values, dtype=np.float64)
    valid_array = (
        np.ones(array.shape, dtype=np.bool_) if valid is None else np.array(valid, dtype=np.bool_)
    )
    return DiffResult(
        diff_m=array,
        valid=valid_array,
        transform=_TRANSFORM,
        crs=_CRS,
        cell_area_m2=1.0,
    )


def _zone(*, left: float = 0.0, right: float = 2.0) -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [[[left, 2.0], [right, 2.0], [right, 0.0], [left, 0.0], [left, 2.0]]],
    }


def _holed_zone() -> dict[str, object]:
    # Outer 2x2 square with a hole covering the row0/col0 cell (x 0..1, y 1..2).
    return {
        "type": "Polygon",
        "coordinates": [
            [[0.0, 2.0], [2.0, 2.0], [2.0, 0.0], [0.0, 0.0], [0.0, 2.0]],
            [[0.0, 1.0], [1.0, 1.0], [1.0, 2.0], [0.0, 2.0], [0.0, 1.0]],
        ],
    }


def _mask(values: list[list[int]]) -> np.ndarray[Any, np.dtype[np.uint8]]:
    return np.array(values, dtype=np.uint8)


def _measure(
    diff: DiffResult,
    polygon: Mapping[str, Any] | None = None,
    mask: np.ndarray[Any, np.dtype[np.uint8]] | None = None,
    **overrides: Any,
) -> MaskedExternalVolumeZoneMeasurement | MaskedExternalVolumeError:
    arguments: dict[str, Any] = {
        "zone_id": "masked-zone-1",
        "from_crs": _CRS,
        "exclusion_mask": _mask([[0, 0], [0, 0]]) if mask is None else mask,
        "mask_crs": _CRS,
        "mask_transform": _TRANSFORM,
        "maximum_zone_grid_cells": 64,
    }
    arguments.update(overrides)
    return measure_masked_external_volume_zone(
        diff, dict(_zone() if polygon is None else polygon), **arguments
    )


@pytest.mark.parametrize("reason", list(ExternalVolumeMeasurementErrorReason))
def test_underlying_errors_remain_non_numeric_and_fail_closed(
    reason: ExternalVolumeMeasurementErrorReason, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even a boundary-only underlying error must not become a number or crash."""
    error = ExternalVolumeMeasurementError(reason, "underlying detail")
    monkeypatch.setattr(masked_volume, "_validate_parameters", lambda **_: error)

    result = _measure(_diff([[1.0, 1.0], [1.0, 1.0]]))
    assert isinstance(result, MaskedExternalVolumeError)
    if reason in {
        ExternalVolumeMeasurementErrorReason.INSUFFICIENT_BOUNDARY_COVERAGE,
        ExternalVolumeMeasurementErrorReason.BOUNDARY_SAMPLES_INSUFFICIENT,
    }:
        expected = MaskedExternalVolumeErrorReason.INVALID_INPUT
    else:
        expected = MaskedExternalVolumeErrorReason(reason.value)
    assert result.reason is expected
    assert result.detail == "underlying detail"
    assert result.metrics is None


def test_empty_mask_reproduces_hand_calculated_cut_fill_net() -> None:
    measured = _measure(_diff([[2.0, -1.0], [0.0, 3.0]]))
    assert not isinstance(measured, MaskedExternalVolumeError)
    assert measured.original_selected_cell_count == 4
    assert measured.mask_excluded_cell_count == 0
    assert measured.effective_selected_cell_count == 4
    assert measured.common_valid_cell_count == 4
    assert measured.metrics.zone_cell_count == 4
    assert measured.metrics.common_valid_cell_count == 4
    assert measured.metrics.fill_m3 == pytest.approx(5.0)
    assert measured.metrics.cut_m3 == pytest.approx(1.0)
    assert measured.metrics.net_m3 == pytest.approx(4.0)
    assert measured.metrics.threshold_m == pytest.approx(0.0)
    assert measured.metrics.uncertainty_m3 is None
    assert measured.row_offset == 0
    assert measured.column_offset == 0
    assert measured.bounds == pytest.approx((0.0, 0.0, 2.0, 2.0))
    assert measured.delta_grid_m.shape == (2, 2)
    assert np.array_equal(
        measured.delta_grid_m, np.array([[2.0, -1.0], [0.0, 3.0]], dtype=np.float64)
    )


def test_masked_cell_is_removed_from_counts_and_volumes() -> None:
    measured = _measure(_diff([[2.0, -1.0], [0.0, 3.0]]), mask=_mask([[0, 0], [0, 1]]))
    assert not isinstance(measured, MaskedExternalVolumeError)
    assert measured.original_selected_cell_count == 4
    assert measured.mask_excluded_cell_count == 1
    assert measured.effective_selected_cell_count == 3
    assert measured.common_valid_cell_count == 3
    assert measured.metrics.zone_cell_count == 3
    assert measured.metrics.fill_m3 == pytest.approx(2.0)
    assert measured.metrics.cut_m3 == pytest.approx(1.0)
    assert measured.metrics.net_m3 == pytest.approx(1.0)
    assert measured.metrics.zone_area_m2 == pytest.approx(3.0)
    assert measured.metrics.measured_area_m2 == pytest.approx(3.0)
    assert measured.metrics.common_valid_fraction == pytest.approx(1.0)
    assert bool(measured.unavailable_mask.sum()) is False
    assert np.isnan(measured.delta_grid_m[1, 1])
    assert measured.delta_grid_m[0, 0] == pytest.approx(2.0)
    assert measured.effective_selected_mask.dtype == np.dtype(np.bool_)
    assert measured.mask_excluded_mask.dtype == np.dtype(np.bool_)


def test_hole_excludes_first_and_mask_overlap_does_not_double_count() -> None:
    # Hole removes row0/col0 (value 2.0); mask marks that same cell plus
    # row1/col1 (value 3.0).  Only the in-polygon mask cell counts.
    measured = _measure(
        _diff([[2.0, -1.0], [0.0, 3.0]]),
        _holed_zone(),
        mask=_mask([[1, 0], [0, 1]]),
    )
    assert not isinstance(measured, MaskedExternalVolumeError)
    assert measured.original_selected_cell_count == 3
    assert measured.mask_excluded_cell_count == 1
    assert measured.effective_selected_cell_count == 2
    assert measured.metrics.fill_m3 == pytest.approx(0.0)
    assert measured.metrics.cut_m3 == pytest.approx(1.0)
    assert measured.metrics.net_m3 == pytest.approx(-1.0)


def test_invalid_source_cell_blocks_unless_explicitly_excluded() -> None:
    diff = _diff([[2.0, -1.0], [0.0, 3.0]], valid=[[True, True], [False, True]])
    blocked = _measure(diff, mask=_mask([[0, 0], [0, 0]]))
    assert isinstance(blocked, MaskedExternalVolumeError)
    assert blocked.reason is MaskedExternalVolumeErrorReason.INSUFFICIENT_COMMON_VALID_COVERAGE
    assert blocked.original_selected_cell_count == 4
    assert blocked.mask_excluded_cell_count == 0
    assert blocked.effective_selected_cell_count == 4
    assert blocked.common_valid_cell_count == 3
    assert blocked.metrics is None

    rescued = _measure(diff, mask=_mask([[0, 0], [1, 0]]))
    assert not isinstance(rescued, MaskedExternalVolumeError)
    assert rescued.effective_selected_cell_count == 3
    assert rescued.metrics.fill_m3 == pytest.approx(5.0)
    assert rescued.metrics.cut_m3 == pytest.approx(1.0)


def test_all_masked_returns_typed_error() -> None:
    measured = _measure(_diff([[2.0, -1.0], [0.0, 3.0]]), mask=_mask([[1, 1], [1, 1]]))
    assert isinstance(measured, MaskedExternalVolumeError)
    assert measured.reason is MaskedExternalVolumeErrorReason.ALL_MASKED
    assert measured.original_selected_cell_count == 4
    assert measured.mask_excluded_cell_count == 4
    assert measured.effective_selected_cell_count == 0
    assert measured.metrics is None


def test_empty_zone_returns_typed_error() -> None:
    # A sliver between cell centers selects no baseline-grid cell at all.
    sliver = {
        "type": "Polygon",
        "coordinates": [[[0.1, 0.2], [0.2, 0.2], [0.2, 0.1], [0.1, 0.1], [0.1, 0.2]]],
    }
    measured = _measure(_diff([[2.0, -1.0], [0.0, 3.0]]), sliver)
    assert isinstance(measured, MaskedExternalVolumeError)
    assert measured.reason is MaskedExternalVolumeErrorReason.EMPTY_ZONE
    assert measured.metrics is None


def test_fully_outside_polygon_has_no_common_valid_cells() -> None:
    # The grid-aligned window still selects its own bounds cell, but that cell
    # is outside the difference raster, so it is unavailable, not zero.
    measured = _measure(
        _diff([[2.0, -1.0], [0.0, 3.0]]),
        {
            "type": "Polygon",
            "coordinates": [[[10.0, 10.0], [11.0, 10.0], [11.0, 9.0], [10.0, 9.0], [10.0, 10.0]]],
        },
    )
    assert isinstance(measured, MaskedExternalVolumeError)
    assert measured.reason is MaskedExternalVolumeErrorReason.EMPTY_COMMON_VALID_COVERAGE
    assert measured.metrics is None


@pytest.mark.parametrize(
    "bad_mask",
    [
        np.array([[0, 2], [0, 0]], dtype=np.uint8),
        np.array([[0, 255], [0, 0]], dtype=np.uint8),
        np.array([[0.0, 0.0], [0.0, 0.0]], dtype=np.float64),
        np.array([[False, False], [False, False]], dtype=np.bool_),
        np.array([[0, 0], [0, 0]], dtype=np.int32),
        np.array([0, 0, 0, 0], dtype=np.uint8),
        np.array([[0, 0, 0], [0, 0, 0]], dtype=np.uint8),
    ],
)
def test_nonbinary_nodata_wrongdtype_or_shape_mask_rejected(
    bad_mask: np.ndarray[Any, Any],
) -> None:
    """No resampling and no automatic float/bool cast: exact uint8 binary only."""
    measured = _measure(_diff([[2.0, -1.0], [0.0, 3.0]]), mask=bad_mask)
    assert isinstance(measured, MaskedExternalVolumeError)
    assert measured.reason is MaskedExternalVolumeErrorReason.INVALID_INPUT
    assert measured.metrics is None


def test_masked_array_mask_rejected_as_nodata() -> None:
    bad = np.ma.array([[0, 0], [0, 0]], dtype=np.uint8, mask=[[False, True], [False, False]])
    measured = _measure(_diff([[2.0, -1.0], [0.0, 3.0]]), mask=bad)
    assert isinstance(measured, MaskedExternalVolumeError)
    assert measured.reason is MaskedExternalVolumeErrorReason.INVALID_INPUT


def test_mask_transform_mismatch_rejected() -> None:
    measured = _measure(
        _diff([[2.0, -1.0], [0.0, 3.0]]),
        mask_transform=Affine(1.0, 0.0, 0.5, 0.0, -1.0, 2.0),
    )
    assert isinstance(measured, MaskedExternalVolumeError)
    assert measured.reason is MaskedExternalVolumeErrorReason.INVALID_INPUT


def test_mask_crs_mismatch_rejected() -> None:
    measured = _measure(
        _diff([[2.0, -1.0], [0.0, 3.0]]),
        mask_crs="EPSG:4326",
    )
    assert isinstance(measured, MaskedExternalVolumeError)
    assert measured.reason is MaskedExternalVolumeErrorReason.INVALID_INPUT


def test_mask_crs_and_transform_must_be_well_formed() -> None:
    for overrides in (
        {"mask_crs": ""},
        {"mask_crs": None},
        {"mask_transform": "EPSG:5186"},
    ):
        measured = _measure(_diff([[0.0, 0.0], [0.0, 0.0]]), **overrides)
        assert isinstance(measured, MaskedExternalVolumeError)
        assert measured.reason is MaskedExternalVolumeErrorReason.INVALID_INPUT


def test_oversized_zone_refused_before_allocation() -> None:
    measured = _measure(
        _diff([[0.0, 0.0], [0.0, 0.0]]),
        _zone(left=0.0, right=1_000_000.0),
        maximum_zone_grid_cells=4,
    )
    assert isinstance(measured, MaskedExternalVolumeError)
    assert measured.reason is MaskedExternalVolumeErrorReason.OVERSIZED_ZONE
    assert measured.metrics is None


def test_partly_outside_polygon_reports_unavailable_instead_of_zero() -> None:
    measured = _measure(_diff([[2.0, -1.0], [0.0, 3.0]]), _zone(left=-1.0, right=2.0))
    assert isinstance(measured, MaskedExternalVolumeError)
    assert measured.reason is MaskedExternalVolumeErrorReason.INSUFFICIENT_COMMON_VALID_COVERAGE
    assert measured.original_selected_cell_count == 6
    assert measured.mask_excluded_cell_count == 0
    assert measured.effective_selected_cell_count == 6
    assert measured.common_valid_cell_count == 4


def test_malformed_polygon_rejected() -> None:
    measured = _measure(
        _diff([[0.0, 0.0], [0.0, 0.0]]),
        {"type": "Polygon", "coordinates": [[[0.0, 0.0], [1.0, 1.0], [0.0, 0.0]]]},
    )
    assert isinstance(measured, MaskedExternalVolumeError)
    assert measured.reason is MaskedExternalVolumeErrorReason.INVALID_ZONE
    assert measured.metrics is None


def test_inputs_are_not_mutated() -> None:
    diff = _diff([[2.0, -1.0], [0.0, 3.0]])
    mask = _mask([[0, 0], [0, 1]])
    diff_before = diff.diff_m.copy()
    valid_before = diff.valid.copy()
    mask_before = mask.copy()
    measured = _measure(diff, mask=mask)
    assert not isinstance(measured, MaskedExternalVolumeError)
    assert np.array_equal(diff.diff_m, diff_before)
    assert np.array_equal(diff.valid, valid_before)
    assert np.array_equal(mask, mask_before)
    assert mask.dtype == np.dtype(np.uint8)


def test_repeated_calls_are_deterministic() -> None:
    diff = _diff([[2.0, -1.0], [0.0, 3.0]])
    mask = _mask([[0, 0], [0, 1]])
    first = _measure(diff, mask=mask)
    second = _measure(diff, mask=mask)
    assert not isinstance(first, MaskedExternalVolumeError)
    assert not isinstance(second, MaskedExternalVolumeError)
    assert first.metrics == second.metrics
    assert np.array_equal(first.delta_grid_m, second.delta_grid_m, equal_nan=True)
    assert np.array_equal(first.effective_selected_mask, second.effective_selected_mask)
    assert first.bounds == second.bounds


def test_v1_v2_behavior_is_unchanged_by_masked_import() -> None:
    """Importing the masked profile must not alter the frozen V1/V2 surfaces."""
    from ksi_change_detection import external_volume

    assert "measure_masked_external_volume_zone" not in external_volume.__all__
    assert external_volume.__all__ == [
        "ExternalVolumeMeasurementError",
        "ExternalVolumeMeasurementErrorReason",
        "ExternalVolumeZoneCoverageMeasurement",
        "ExternalVolumeZoneMeasurement",
        "measure_fixed_profile_external_volume_zone",
        "measure_external_volume_zone",
    ]
