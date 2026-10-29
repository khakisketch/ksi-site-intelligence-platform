"""Real emitted TIFF bytes must match the sealed V2 result, not a recomputation UI."""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Any

import numpy as np
import pytest
import rasterio
from ksi_change_detection.dsm_diff import DiffResult
from ksi_event_contracts.external_relative_volume_calculation import (
    RelativeVolumeCoverageWitnessV2,
    RelativeVolumeMetricsV2,
    RelativeVolumeNumericResultV2,
)
from ksi_processing_controller.external_delta_raster import (
    DeltaRasterMeasurementError,
    prepare_external_delta_raster_v2,
)
from rasterio.transform import from_origin


def _fixture() -> tuple[DiffResult, RelativeVolumeNumericResultV2]:
    diff = DiffResult(
        diff_m=np.array([[2.0, 0.0], [-1.0, 0.0]], dtype=np.float64),
        valid=np.array([[True, False], [True, True]]),
        transform=from_origin(0, 2, 1, 1),
        crs="EPSG:5186",
        cell_area_m2=1.0,
    )
    mask = base64.b64encode(bytes([0b10110000])).decode()
    zero = base64.b64encode(bytes([0])).decode()
    coverage = RelativeVolumeCoverageWitnessV2(
        rows=2,
        columns=2,
        row_offset=0,
        column_offset=0,
        selected_mask_b64=mask,
        common_valid_mask_b64=mask,
        unavailable_mask_b64=zero,
        threshold_excluded_mask_b64=zero,
        selected_cell_count=3,
        common_valid_cell_count=3,
        unavailable_cell_count=0,
        threshold_excluded_cell_count=0,
        cell_area_m2=1.0,
        selected_area_m2=3.0,
        common_valid_area_m2=3.0,
        bounds=(0.0, 0.0, 2.0, 2.0),
    ).sealed()
    numeric = RelativeVolumeNumericResultV2(
        calculation_identity_digest="sha256:" + "a" * 64,
        profile_digest="sha256:" + "b" * 64,
        metrics=RelativeVolumeMetricsV2(cut_m3=1.0, fill_m3=2.0, net_m3=1.0, threshold_m=0.0),
        coverage=coverage,
    ).sealed()
    return diff, numeric


def _prepare(diff: DiffResult, numeric: RelativeVolumeNumericResultV2, **overrides: Any) -> Any:
    return prepare_external_delta_raster_v2(
        diff=diff,
        numeric_result=numeric,
        **{
            "maximum_output_bytes": 1_000_000,
            "maximum_grid_cells": 4,
            "check_current": lambda: None,
            **overrides,
        },
    )


def test_emits_real_float64_geotiff_with_exact_cells_and_private_descriptor() -> None:
    diff, numeric = _fixture()
    original = numeric.model_dump_json()
    with _prepare(diff, numeric) as output:
        descriptor = output.fd
        assert os.fstat(descriptor).st_nlink == 0
        content = os.pread(descriptor, output.size_bytes, 0)
        assert output.sha256 == "sha256:" + hashlib.sha256(content).hexdigest()
        assert output.numeric_result_identity_digest == numeric.canonical_digest()
        assert output.coverage_witness_digest == numeric.coverage.canonical_digest()
        with rasterio.open(f"/proc/self/fd/{descriptor}") as dataset:
            values = dataset.read(1)
            assert dataset.dtypes == ("float64",)
            assert dataset.units == ("metre",)
            assert dataset.tags()["DELTA_RULE"] == "CURRENT_MINUS_BASELINE"
            assert dataset.tags()["NUMERIC_RESULT_IDENTITY_DIGEST"] == numeric.canonical_digest()
            assert str(dataset.crs) == "EPSG:5186"
            assert dataset.transform == diff.transform
            assert np.isnan(dataset.nodata)
            assert np.isnan(values[0, 1])  # unavailable/excluded is never zero
            np.testing.assert_array_equal(values[[0, 1, 1], [0, 0, 1]], [2.0, -1.0, 0.0])
    with pytest.raises(OSError):
        os.fstat(descriptor)
    assert numeric.model_dump_json() == original


def test_same_array_and_numeric_identity_produce_identical_output_bytes() -> None:
    diff, numeric = _fixture()
    with _prepare(diff, numeric) as first, _prepare(diff, numeric) as second:
        assert first.sha256 == second.sha256
        assert first.size_bytes == second.size_bytes


def test_rejects_different_array_even_when_aggregate_result_looks_plausible() -> None:
    diff, numeric = _fixture()
    diff.diff_m[0, 0] = 5.0
    with (
        pytest.raises(DeltaRasterMeasurementError, match="sealed numeric"),
        _prepare(diff, numeric),
    ):
        pytest.fail("inconsistent result was exported")


@pytest.mark.parametrize("change", ["mask", "nan", "bounds", "area"])
def test_rejects_coverage_grid_or_finite_value_mismatch(change: str) -> None:
    diff, numeric = _fixture()
    if change == "mask":
        diff.valid[0, 0] = False
    elif change == "nan":
        diff.diff_m[0, 0] = np.nan
    elif change == "bounds":
        diff = DiffResult(diff.diff_m, diff.valid, from_origin(1, 2, 1, 1), diff.crs, 1.0)
    else:
        diff = DiffResult(diff.diff_m, diff.valid, diff.transform, diff.crs, 2.0)
    with pytest.raises(DeltaRasterMeasurementError), _prepare(diff, numeric):
        pytest.fail("unverified grid was exported")


@pytest.mark.parametrize(
    "limits",
    [
        {"maximum_output_bytes": 100},
        {"maximum_grid_cells": 3},
        {"maximum_output_bytes": True},
        {"maximum_grid_cells": 0},
    ],
)
def test_resource_limits_are_explicit_and_fail_before_publication(limits: dict[str, Any]) -> None:
    diff, numeric = _fixture()
    with pytest.raises(DeltaRasterMeasurementError), _prepare(diff, numeric, **limits):
        pytest.fail("oversized output was exposed")


def test_currentness_loss_before_native_work_never_exposes_an_output() -> None:
    diff, numeric = _fixture()

    def revoked() -> None:
        raise RuntimeError("REVOKED")

    with (
        pytest.raises(RuntimeError, match="REVOKED"),
        _prepare(diff, numeric, check_current=revoked),
    ):
        pytest.fail("revoked operation was exposed")


def test_sub_float32_precision_is_not_silently_removed() -> None:
    diff, numeric = _fixture()
    precise = float(np.nextafter(2.0, 3.0))
    diff.diff_m[0, 0] = precise
    numeric = RelativeVolumeNumericResultV2(
        calculation_identity_digest=numeric.calculation_identity_digest,
        profile_digest=numeric.profile_digest,
        coverage=numeric.coverage,
        metrics=RelativeVolumeMetricsV2(
            cut_m3=1.0, fill_m3=precise, net_m3=precise - 1.0, threshold_m=0.0
        ),
    ).sealed()
    with _prepare(diff, numeric) as output, rasterio.open(f"/proc/self/fd/{output.fd}") as dataset:
        assert dataset.read(1)[0, 0] == precise
