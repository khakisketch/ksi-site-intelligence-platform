"""Known-answer synthetic DSMs through the existing fixed V2 worker callable.

These are local arithmetic/coverage acceptance cases, not admission, customer
export, parser containment, or field-accuracy evidence. WorkArea polygon holes
are the existing exclusion input; no separate mask contract is introduced.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from ksi_event_contracts.external_relative_volume_analysis import CalculationIdentityV2
from ksi_event_contracts.external_relative_volume_calculation import (
    RelativeVolumeCalculationFailureV2,
    RelativeVolumeCalculationReportV2,
)
from ksi_processing_controller.external_analysis_measurement import (
    measure_external_relative_volume_v2,
)
from test_external_analysis_measurement import (
    _ORIGIN_X,
    _ORIGIN_Y,
    _attempt,
    _canonical_digest,
    _identity,
    _write_dsm,
)


def _ten_metre_area(
    baseline: Path, current: Path, *, exclude_centre: bool = False
) -> CalculationIdentityV2:
    rings = [
        [
            [_ORIGIN_X, _ORIGIN_Y],
            [_ORIGIN_X, _ORIGIN_Y - 10.0],
            [_ORIGIN_X + 10.0, _ORIGIN_Y - 10.0],
            [_ORIGIN_X + 10.0, _ORIGIN_Y],
            [_ORIGIN_X, _ORIGIN_Y],
        ]
    ]
    if exclude_centre:
        rings.append(
            [
                [_ORIGIN_X + 4.0, _ORIGIN_Y - 4.0],
                [_ORIGIN_X + 6.0, _ORIGIN_Y - 4.0],
                [_ORIGIN_X + 6.0, _ORIGIN_Y - 6.0],
                [_ORIGIN_X + 4.0, _ORIGIN_Y - 6.0],
                [_ORIGIN_X + 4.0, _ORIGIN_Y - 4.0],
            ]
        )
    polygon: dict[str, object] = {"type": "Polygon", "coordinates": rings}
    return _identity(baseline, current).model_copy(
        update={
            "work_area_polygon": polygon,
            "work_area_definition_digest": _canonical_digest(
                {"workAreaId": "work-area-a", "crs": "EPSG:5186", "polygon": polygon}
            ),
            "calculation_identity_digest": None,
        }
    ).sealed()


def _measure(
    identity: CalculationIdentityV2, baseline: Path, current: Path
) -> RelativeVolumeCalculationReportV2 | RelativeVolumeCalculationFailureV2:
    return measure_external_relative_volume_v2(
        attempt=_attempt(identity),
        calculation_identity=identity,
        baseline_path=baseline,
        current_path=current,
        report_id="known-answer-synthetic-report",
        computed_at=datetime(2026, 9, 21, tzinfo=UTC),
        reported_at=datetime(2026, 9, 21, tzinfo=UTC),
    )


@pytest.mark.parametrize("case", ["uniform-rise", "local-excavation"])
def test_known_answer_100_square_metre_change_is_reproducible(
    tmp_path: Path, case: str
) -> None:
    baseline = _write_dsm(tmp_path / "baseline.tif", np.full((10, 10), 100.0))
    elevations = np.full((10, 10), 100.0)
    if case == "uniform-rise":
        elevations += 1.0
        expected_cut, expected_fill = 0.0, 100.0
    else:
        elevations[2:4, 3:6] -= 2.0
        expected_cut, expected_fill = 12.0, 0.0
    current = _write_dsm(tmp_path / "current.tif", elevations)
    identity = _ten_metre_area(baseline, current)

    first = _measure(identity, baseline, current)
    second = _measure(identity, baseline, current)

    assert isinstance(first, RelativeVolumeCalculationReportV2)
    assert isinstance(second, RelativeVolumeCalculationReportV2)
    metrics = first.numeric_result.metrics
    assert metrics.cut_m3 == expected_cut
    assert metrics.fill_m3 == expected_fill
    assert metrics.net_m3 == expected_fill - expected_cut
    assert metrics.uncertainty_m3 is None
    coverage = first.numeric_result.coverage
    assert coverage.selected_cell_count == coverage.common_valid_cell_count == 100
    assert coverage.unavailable_cell_count == coverage.threshold_excluded_cell_count == 0
    assert first.numeric_result == second.numeric_result
    assert first.report_digest == second.report_digest


def test_existing_polygon_hole_excludes_nodata_without_weakening_full_coverage(
    tmp_path: Path,
) -> None:
    baseline = _write_dsm(
        tmp_path / "baseline.tif", np.full((10, 10), 100.0), nodata=-9999.0
    )
    elevations = np.full((10, 10), 101.0)
    elevations[4:6, 4:6] = -9999.0
    current = _write_dsm(tmp_path / "current.tif", elevations, nodata=-9999.0)
    full_area = _ten_metre_area(baseline, current)
    holed_area = _ten_metre_area(baseline, current, exclude_centre=True)
    assert full_area.calculation_identity_digest != holed_area.calculation_identity_digest

    blocked = _measure(full_area, baseline, current)
    result = _measure(holed_area, baseline, current)

    assert isinstance(blocked, RelativeVolumeCalculationFailureV2)
    assert blocked.reason_code == "INSUFFICIENT_COMMON_VALID_COVERAGE"
    assert isinstance(result, RelativeVolumeCalculationReportV2)
    assert result.numeric_result.metrics.fill_m3 == 96.0
    assert result.numeric_result.metrics.cut_m3 == 0.0
    assert result.numeric_result.metrics.net_m3 == 96.0
    coverage = result.numeric_result.coverage
    assert coverage.selected_cell_count == coverage.common_valid_cell_count == 96
    assert coverage.unavailable_cell_count == coverage.threshold_excluded_cell_count == 0
