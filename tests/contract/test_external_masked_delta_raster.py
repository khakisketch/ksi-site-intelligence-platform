"""Actual V3 numeric output, never a fabricated V2 record, drives exported cells."""

from __future__ import annotations

import hashlib
import os

import numpy as np
import pytest
import rasterio
from ksi_processing_controller.external_delta_raster import (
    DeltaRasterMeasurementError,
    prepare_external_delta_raster_v3,
)
from ksi_processing_controller.external_masked_volume_measurement import MaskedVolumeMeasuredV3
from test_external_masked_volume_measurement import (
    _digest,
    _envelope,
    _full_polygon,
    _known_diff,
    _known_mask,
    _masked_identity,
    _measure_from_diff,
)


def _measured(*, invalid=None):
    identity = _masked_identity(
        _full_polygon(),
        baseline_sha=_digest("b"),
        current_sha=_digest("c"),
        mask_sha=_digest("m"),
    )
    outcome = _measure_from_diff(_known_diff(invalid=invalid), _known_mask(), identity, _envelope())
    assert isinstance(outcome, MaskedVolumeMeasuredV3)
    return identity, outcome


def _prepare(identity, outcome, **overrides):
    return prepare_external_delta_raster_v3(
        **{
            "masked_identity": identity,
            "report": outcome.report,
            "delta_grid_m": outcome.delta_grid_m,
            "maximum_output_bytes": 1_000_000,
            "maximum_grid_cells": 16,
            "check_current": lambda: None,
            **overrides,
        }
    )


def test_actual_v3_measured_grid_emits_private_float64_cells_and_v3_digests():
    identity, measured = _measured()
    original = measured.report.model_dump_json()
    with _prepare(identity, measured) as output:
        fd = output.fd
        assert os.fstat(fd).st_nlink == 0
        assert (
            output.sha256
            == "sha256:" + hashlib.sha256(os.pread(fd, output.size_bytes, 0)).hexdigest()
        )
        numeric = measured.report.numeric_result
        assert output.calculation_identity_digest == identity.canonical_digest()
        assert (
            output.calculation_identity_digest
            != identity.source_calculation_identity.canonical_digest()
        )
        assert output.numeric_result_identity_digest == numeric.canonical_digest()
        assert output.coverage_witness_digest == numeric.coverage.canonical_digest()
        with rasterio.open(f"/proc/self/fd/{fd}") as dataset:
            np.testing.assert_array_equal(dataset.read(1), measured.delta_grid_m)
            assert dataset.dtypes == ("float64",)
            assert dataset.units == ("metre",)
            assert dataset.tags()["DELTA_RULE"] == "CURRENT_MINUS_BASELINE"
            assert dataset.tags()["NUMERIC_RESULT_IDENTITY_DIGEST"] == numeric.canonical_digest()
            assert dataset.tags()["COVERAGE_WITNESS_DIGEST"] == numeric.coverage.canonical_digest()
    with pytest.raises(OSError):
        os.fstat(fd)
    assert measured.report.model_dump_json() == original


def test_unknown_unmasked_impact_never_invents_an_excluded_zero_cell():
    identity, measured = _measured(invalid=(0, 1))
    assert not measured.report.numeric_result.impact.unmasked_impact_known
    with (
        _prepare(identity, measured) as output,
        rasterio.open(f"/proc/self/fd/{output.fd}") as dataset,
    ):
        assert np.isnan(dataset.read(1)[0, 1])
        assert measured.report.numeric_result.impact.excluded_fill_m3 is None


def test_v3_repeated_outputs_are_byte_identical():
    identity, measured = _measured()
    with _prepare(identity, measured) as first, _prepare(identity, measured) as second:
        assert (first.sha256, first.size_bytes) == (second.sha256, second.size_bytes)


@pytest.mark.parametrize(
    "change", ["excluded-zero", "valid-nan", "metric-drift", "float32", "shape", "masked-array"]
)
def test_v3_rejects_arrays_that_do_not_match_exact_coverage_and_numeric_result(change):
    identity, measured = _measured()
    array = measured.delta_grid_m.copy()
    if change == "excluded-zero":
        array[0, 1] = 0.0
    elif change == "valid-nan":
        array[1, 1] = np.nan
    elif change == "metric-drift":
        array[1, 1] = 20.0
    elif change == "float32":
        array = array.astype(np.float32)
    elif change == "shape":
        array = array[:2]
    else:
        array = np.ma.array(array, mask=False)
    with (
        pytest.raises(DeltaRasterMeasurementError),
        _prepare(identity, measured, delta_grid_m=array),
    ):
        pytest.fail("an unbound V3 grid was exposed")


def test_v3_wrong_mask_identity_cannot_reuse_a_valid_numeric_report():
    identity, measured = _measured()
    other = _masked_identity(
        _full_polygon(),
        baseline_sha=_digest("b"),
        current_sha=_digest("c"),
        mask_sha=_digest("different-mask"),
    )
    assert other.canonical_digest() != identity.canonical_digest()
    with pytest.raises(DeltaRasterMeasurementError, match="bind"), _prepare(other, measured):
        pytest.fail("a report was rebound to another mask")


def test_v3_private_snapshot_cannot_be_changed_by_later_caller_mutation():
    identity, measured = _measured()
    expected = measured.delta_grid_m.copy()
    calls = 0

    def mutate_after_validation():
        nonlocal calls
        calls += 1
        if calls == 2:
            measured.delta_grid_m[1, 1] = 123.0

    with (
        _prepare(identity, measured, check_current=mutate_after_validation) as output,
        rasterio.open(f"/proc/self/fd/{output.fd}") as dataset,
    ):
        np.testing.assert_array_equal(dataset.read(1), expected)


@pytest.mark.parametrize("cap", [{"maximum_grid_cells": 15}, {"maximum_output_bytes": 100}])
def test_v3_resource_cap_never_exposes_an_output(cap):
    identity, measured = _measured()
    with pytest.raises(DeltaRasterMeasurementError), _prepare(identity, measured, **cap):
        pytest.fail("an oversized V3 output was exposed")


def test_v3_currentness_failure_aborts_before_an_output_is_exposed():
    identity, measured = _measured()

    def revoked():
        raise RuntimeError("REVOKED")

    with (
        pytest.raises(RuntimeError, match="REVOKED"),
        _prepare(identity, measured, check_current=revoked),
    ):
        pytest.fail("revoked V3 output was exposed")


def test_v3_output_byte_cap_is_checked_before_unpacking_or_copying_grid(monkeypatch):
    identity, measured = _measured()

    def must_not_decode(*args, **kwargs):
        pytest.fail("output allocation preceded its explicit byte-cap preflight")

    monkeypatch.setattr(
        "ksi_processing_controller.external_delta_raster.np.unpackbits", must_not_decode
    )
    with (
        pytest.raises(DeltaRasterMeasurementError, match="byte budget"),
        _prepare(identity, measured, maximum_output_bytes=100),
    ):
        pytest.fail("oversized output was exposed")
