"""compute_survey_regions 계약 — 2시점 DSM 전수 조사 진입점 (Task 1).

설계 경로(``test_region_extraction.py``)와 공유 코어(``_extract``)를 쓰므로
여기서는 **조사 진입점의 차이**만 강제한다: ``design_conformance_id`` 없이
호출 가능, 문턱값은 정책 안에서만 옴, 계보 앵커는 ``survey:<surveyId>``,
유효 셀 없는 입력은 fail-closed. 라벨링·면적 필터·MAX 상한·cut/fill 산식의
동작은 설계 경로와 같은 코어이므로, 조사 출력에 대해서도 합성 diff 로 직접
확인한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from ksi_change_detection.dsm_diff import DiffResult, volume_delta_in_polygon
from ksi_change_detection.region_extraction import (
    RegionExtractionError,
    compute_survey_regions,
)
from ksi_event_contracts.change_region_report import MAX_REGIONS, ChangeRegionSetReport
from ksi_event_contracts.survey_extraction_policy import (
    SURVEY_EXTRACTION_POLICY_VERSION,
    SurveyExtractionPolicy,
    current_survey_extraction_policy,
)
from rasterio import Affine

_TRANSFORM = Affine(1.0, 0.0, 190000.0, 0.0, -1.0, 450000.0)
_NOW = datetime(2026, 11, 12, 0, 0, tzinfo=UTC)


def _policy(**overrides: object) -> SurveyExtractionPolicy:
    base: dict[str, object] = {
        "policy_version": "test-survey-policy",
        "threshold_m": 0.05,
        "min_region_area_m2": 1.0,
        "connectivity": 8,
    }
    base.update(overrides)
    return SurveyExtractionPolicy(**base)  # type: ignore[arg-type]


def _diff(diff_m: np.ndarray, valid: np.ndarray) -> DiffResult:
    return DiffResult(
        diff_m=diff_m, valid=valid, transform=_TRANSFORM, crs="EPSG:5186",
        cell_area_m2=1.0,
    )


def _two_blob_diff() -> DiffResult:
    diff_m = np.zeros((10, 10), dtype=np.float64)
    valid = np.ones((10, 10), dtype=bool)
    diff_m[0:2, 0:2] = 0.2  # 4 픽셀 fill
    diff_m[5:8, 5:9] = -0.3  # 12 픽셀 cut
    return _diff(diff_m, valid)


def _survey(
    diff: DiffResult,
    *,
    policy: SurveyExtractionPolicy | None = None,
    change_region_set_id: str = "srv-1-sex1",
    survey_id: str = "srv-1",
) -> ChangeRegionSetReport:
    return compute_survey_regions(
        diff,
        policy=policy or _policy(),
        change_region_set_id=change_region_set_id,
        survey_id=survey_id,
        diff_raster_id="srv-1-diff",
        computed_at=_NOW,
    )


# ── 진입점 차이 ────────────────────────────────────────────────────────────


def test_survey_runs_without_design_conformance_id_and_anchors_to_survey() -> None:
    report = _survey(_two_blob_diff())
    assert len(report.regions) == 2
    assert report.design_conformance_id == "survey:srv-1"
    assert report.diff_raster_id == "srv-1-diff"


def test_threshold_comes_from_the_policy_not_a_separate_argument() -> None:
    report = _survey(_two_blob_diff(), policy=_policy(threshold_m=0.25))
    # 0.2 fill blob 은 문턱 아래라 사라지고, 0.3 cut blob 만 남는다.
    assert [r.pixel_count for r in report.regions] == [12]
    assert report.threshold_m == pytest.approx(0.25)
    assert all(r.volume.threshold_m == pytest.approx(0.25) for r in report.regions)


def test_extraction_policy_snapshot_records_the_survey_values() -> None:
    policy = _policy(min_region_area_m2=2.0, connectivity=4)
    report = _survey(_two_blob_diff(), policy=policy)
    assert report.extraction_policy.policy_version == "test-survey-policy"
    assert report.extraction_policy.min_region_area_m2 == pytest.approx(2.0)
    assert report.extraction_policy.connectivity == 4


def test_empty_survey_id_is_rejected() -> None:
    with pytest.raises(RegionExtractionError, match="survey_id"):
        _survey(_two_blob_diff(), survey_id="")


def test_default_survey_policy_uses_the_survey_version() -> None:
    policy = current_survey_extraction_policy()
    assert policy.policy_version == SURVEY_EXTRACTION_POLICY_VERSION
    assert policy.threshold_m >= 0.0
    assert policy.min_region_area_m2 > 0.0


# ── 전수 스캔 동작 ─────────────────────────────────────────────────────────


def test_two_runs_on_the_same_grid_produce_identical_regions() -> None:
    diff = _two_blob_diff()
    first = _survey(diff)
    second = _survey(diff)
    assert [r.region_id for r in first.regions] == [r.region_id for r in second.regions]
    assert [r.region_id for r in first.regions] == ["srv-1-sex1-r1", "srv-1-sex1-r2"]
    assert [r.polygon for r in first.regions] == [r.polygon for r in second.regions]
    assert [
        (r.volume.cut_m3, r.volume.fill_m3, r.volume.net_m3) for r in first.regions
    ] == [(r.volume.cut_m3, r.volume.fill_m3, r.volume.net_m3) for r in second.regions]


def test_regions_below_min_area_are_dropped_and_counted() -> None:
    report = _survey(_two_blob_diff(), policy=_policy(min_region_area_m2=5.0))
    assert [r.pixel_count for r in report.regions] == [12]
    assert report.filtered_region_count == 1


def test_valid_diff_without_change_is_a_valid_empty_report() -> None:
    diff_m = np.zeros((10, 10), dtype=np.float64)
    valid = np.ones((10, 10), dtype=bool)
    report = _survey(_diff(diff_m, valid))
    assert report.regions == []
    assert report.filtered_region_count == 0


def test_all_nodata_diff_is_fail_closed_not_zero_change() -> None:
    diff_m = np.zeros((10, 10), dtype=np.float64)
    valid = np.zeros((10, 10), dtype=bool)
    with pytest.raises(RegionExtractionError, match="유효 셀"):
        _survey(_diff(diff_m, valid))


def test_exceeding_max_regions_raises_instead_of_truncating() -> None:
    size = 80
    diff_m = np.zeros((size, size), dtype=np.float64)
    valid = np.ones((size, size), dtype=bool)
    count = 0
    for row in range(0, size, 2):
        for col in range(0, size, 2):
            if count >= MAX_REGIONS + 10:
                break
            diff_m[row, col] = 0.2
            count += 1
    with pytest.raises(RegionExtractionError, match="상한"):
        _survey(_diff(diff_m, valid), policy=_policy(min_region_area_m2=0.5))


# ── cut/fill 산식이 volume_delta_in_polygon 과 일치 ─────────────────────────


def _rect_polygon(*, row0: int, row1: int, col0: int, col1: int) -> dict[str, object]:
    """셀 경계에 정확히 맞닿는 직사각형 — 픽셀 선택이 라벨과 1:1 이어야 한다."""
    x0, y0 = 190000.0, 450000.0
    return {
        "type": "Polygon",
        "coordinates": [[
            [x0 + col0, y0 - row0],
            [x0 + col1, y0 - row0],
            [x0 + col1, y0 - row1],
            [x0 + col0, y0 - row1],
            [x0 + col0, y0 - row0],
        ]],
    }


def test_per_label_cut_and_fill_match_volume_delta_in_polygon() -> None:
    diff_m = np.zeros((10, 10), dtype=np.float64)
    valid = np.ones((10, 10), dtype=bool)
    diff_m[2:5, 3:7] = 0.25  # 12 픽셀 fill 직사각형
    diff_m[6:8, 0:2] = -0.4  # 4 픽셀 cut 직사각형
    diff = _diff(diff_m, valid)
    report = _survey(diff)
    assert len(report.regions) == 2

    for region in report.regions:
        assert region.convex_hull_polygon is not None  # 직사각형은 hull 이 살아 있다

    fill_region = next(r for r in report.regions if r.volume.fill_m3 > 0)
    cut_region = next(r for r in report.regions if r.volume.cut_m3 > 0)

    expected_fill = volume_delta_in_polygon(
        diff,
        _rect_polygon(row0=2, row1=5, col0=3, col1=7),  # type: ignore[arg-type]
        zone_id="fill",
        from_crs="EPSG:5186",
        threshold_m=0.05,
        uncertainty_note="test",
    )
    expected_cut = volume_delta_in_polygon(
        diff,
        _rect_polygon(row0=6, row1=8, col0=0, col1=2),  # type: ignore[arg-type]
        zone_id="cut",
        from_crs="EPSG:5186",
        threshold_m=0.05,
        uncertainty_note="test",
    )
    assert fill_region.volume.fill_m3 == pytest.approx(expected_fill.fill_m3)
    assert fill_region.volume.cut_m3 == pytest.approx(expected_fill.cut_m3)
    assert fill_region.volume.net_m3 == pytest.approx(expected_fill.net_m3)
    assert cut_region.volume.cut_m3 == pytest.approx(expected_cut.cut_m3)
    assert cut_region.volume.fill_m3 == pytest.approx(expected_cut.fill_m3)
    assert cut_region.volume.net_m3 == pytest.approx(expected_cut.net_m3)
