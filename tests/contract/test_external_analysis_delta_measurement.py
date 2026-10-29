"""The optional artifact is emitted from the very array used by the V2 worker."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import rasterio
from ksi_event_contracts.external_relative_volume_calculation import (
    RelativeVolumeCalculationFailureV2,
    RelativeVolumeCalculationReportV2,
)
from ksi_processing_controller.external_analysis_delta_measurement import (
    measure_external_relative_volume_with_delta_v2,
)
from ksi_processing_controller.external_analysis_measurement import (
    measure_external_relative_volume_v2,
)
from test_external_analysis_measurement import _attempt, _identity, _write_dsm


def _inputs(tmp_path: Path) -> dict[str, Any]:
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((2, 2), 100.0))
    current = _write_dsm(tmp_path / "current.tif", np.array([[101.0, 99.0], [100.0, 100.0]]))
    identity = _identity(baseline, current)
    return {
        "attempt": _attempt(identity),
        "calculation_identity": identity,
        "baseline_path": baseline,
        "current_path": current,
        "report_id": "report-1",
        "computed_at": datetime(2026, 9, 21, tzinfo=UTC),
        "reported_at": datetime(2026, 9, 21, tzinfo=UTC),
    }


def test_actual_source_tiffs_emit_delta_without_changing_any_v2_report_byte(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    original = measure_external_relative_volume_v2(**inputs)
    assert isinstance(original, RelativeVolumeCalculationReportV2)
    with measure_external_relative_volume_with_delta_v2(
        **inputs,
        maximum_delta_output_bytes=1_000_000,
        check_current=lambda: None,
    ) as measured:
        assert measured.report.model_dump_json() == original.model_dump_json()
        assert measured.delta_failure_code is None
        assert measured.delta is not None
        descriptor = measured.delta.fd
        with rasterio.open(f"/proc/self/fd/{descriptor}") as dataset:
            np.testing.assert_array_equal(dataset.read(1), [[1.0, -1.0], [0.0, 0.0]])
        assert (
            measured.delta.numeric_result_identity_digest == original.numeric_result_identity_digest
        )
    with pytest.raises(OSError):
        os.fstat(descriptor)


def test_derived_output_cap_failure_is_separate_from_the_numeric_result(
    tmp_path: Path,
) -> None:
    inputs = _inputs(tmp_path)
    original = measure_external_relative_volume_v2(**inputs)
    with measure_external_relative_volume_with_delta_v2(
        **inputs,
        maximum_delta_output_bytes=100,
        check_current=lambda: None,
    ) as measured:
        assert measured.report.model_dump_json() == original.model_dump_json()
        assert measured.delta is None
        assert measured.delta_failure_code == "DELTA_RASTER_OUTPUT_UNAVAILABLE"


def test_mismatched_original_bytes_never_produce_a_delta(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    _write_dsm(inputs["current_path"], np.full((2, 2), 500.0))
    with measure_external_relative_volume_with_delta_v2(
        **inputs,
        maximum_delta_output_bytes=1_000_000,
        check_current=lambda: None,
    ) as measured:
        assert isinstance(measured.report, RelativeVolumeCalculationFailureV2)
        assert measured.delta is None


def test_explicit_currentness_loss_exposes_no_private_bytes(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)

    def revoked() -> None:
        raise RuntimeError("PUBLICATION_AUTHORITY_REVOKED")

    with (
        pytest.raises(RuntimeError, match="REVOKED"),
        measure_external_relative_volume_with_delta_v2(
            **inputs,
            maximum_delta_output_bytes=1_000_000,
            check_current=revoked,
        ),
    ):
        pytest.fail("revoked output escaped")


@pytest.mark.parametrize("cap", [True, 0, 1_000_001])
def test_delta_policy_cannot_exceed_the_original_execution_envelope(
    tmp_path: Path, cap: bool | int
) -> None:
    with (
        pytest.raises(ValueError, match="Core-authorized"),
        measure_external_relative_volume_with_delta_v2(
            **_inputs(tmp_path),
            maximum_delta_output_bytes=cap,
            check_current=lambda: None,
        ),
    ):
        pytest.fail("unbound policy cap accepted")
