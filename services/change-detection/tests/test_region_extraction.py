"""compute_change_regions 결정성 계약 — M4-E.

**결정성 계약 테스트가 핵심**(계획 확정 사항): 같은 diff 격자를 2회 추출해
region_id 집합·폴리곤 좌표열·cut/fill 값이 완전히 동일함을 강제한다. 그 위에
4-연결 vs 8-연결 대각선 접촉 분기, min_region_area_m2 미만 드롭+
filtered_region_count 반영, MAX_REGIONS 초과 시 fail-closed, hull 자체검증
실패 시 해당 영역만 폴백하는지를 커버한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from ksi_change_detection.dsm_diff import DiffResult
from ksi_change_detection.region_extraction import (
    HULL_CONSISTENCY_CHECK_FAILED,
    RegionExtractionError,
    compute_change_regions,
)
from ksi_event_contracts.change_region_report import MAX_REGIONS, ChangeRegionSetReport
from ksi_event_contracts.region_extraction_policy import RegionExtractionPolicy
from rasterio import Affine

_TRANSFORM = Affine(1.0, 0.0, 190000.0, 0.0, -1.0, 450000.0)
_NOW = datetime(2026, 8, 13, 3, 0, tzinfo=UTC)


def _policy(*, min_region_area_m2: float = 1.0, connectivity: int = 8) -> RegionExtractionPolicy:
    return RegionExtractionPolicy(
        policy_version="test-policy",
        min_region_area_m2=min_region_area_m2,
        connectivity=connectivity,  # type: ignore[arg-type]
    )


def _grid(size: int = 10) -> tuple[np.ndarray, np.ndarray]:
    diff_m = np.zeros((size, size), dtype=np.float64)
    valid = np.ones((size, size), dtype=bool)
    return diff_m, valid


def _diff(diff_m: np.ndarray, valid: np.ndarray, *, crs: str = "EPSG:5186") -> DiffResult:
    return DiffResult(
        diff_m=diff_m, valid=valid, transform=_TRANSFORM, crs=crs, cell_area_m2=1.0
    )


def _two_blob_diff() -> DiffResult:
    diff_m, valid = _grid()
    diff_m[0:2, 0:2] = 0.2  # 4 픽셀 fill
    diff_m[5:8, 5:9] = -0.3  # 12 픽셀 cut
    return _diff(diff_m, valid)


def _report(
    diff: DiffResult,
    *,
    policy: RegionExtractionPolicy | None = None,
    threshold_m: float = 0.05,
    change_region_set_id: str = "dcf-1-rex1",
) -> ChangeRegionSetReport:
    return compute_change_regions(
        diff,
        threshold_m=threshold_m,
        policy=policy or _policy(),
        change_region_set_id=change_region_set_id,
        diff_raster_id="dcf-1-diff",
        design_conformance_id="dcf-1",
        computed_at=_NOW,
    )


# ── 결정성(핵심) ─────────────────────────────────────────────────────────


def test_two_runs_on_the_same_grid_produce_identical_regions() -> None:
    diff = _two_blob_diff()
    first = _report(diff)
    second = _report(diff)

    assert [r.region_id for r in first.regions] == [r.region_id for r in second.regions]
    assert [r.polygon for r in first.regions] == [r.polygon for r in second.regions]
    assert [
        (r.volume.cut_m3, r.volume.fill_m3, r.volume.net_m3) for r in first.regions
    ] == [(r.volume.cut_m3, r.volume.fill_m3, r.volume.net_m3) for r in second.regions]
    assert [r.convex_hull_polygon for r in first.regions] == [
        r.convex_hull_polygon for r in second.regions
    ]
    assert first.filtered_region_count == second.filtered_region_count


def test_survivor_regions_are_ordered_by_ascending_label() -> None:
    diff = _two_blob_diff()
    report = _report(diff)
    assert [r.region_id for r in report.regions] == ["dcf-1-rex1-r1", "dcf-1-rex1-r2"]


# ── 값 산식 ──────────────────────────────────────────────────────────────


def test_cut_and_fill_match_the_inline_volume_formula() -> None:
    diff = _two_blob_diff()
    report = _report(diff)
    fill_region = next(r for r in report.regions if r.pixel_count == 4)
    cut_region = next(r for r in report.regions if r.pixel_count > 4)

    assert fill_region.volume.fill_m3 == pytest.approx(0.2 * 4)
    assert fill_region.volume.cut_m3 == pytest.approx(0.0)
    assert cut_region.volume.cut_m3 == pytest.approx(0.3 * 12)
    assert cut_region.volume.fill_m3 == pytest.approx(0.0)
    assert cut_region.volume.net_m3 == pytest.approx(
        cut_region.volume.fill_m3 - cut_region.volume.cut_m3
    )


def test_original_diff_values_are_not_erased_for_filtered_cells() -> None:
    """threshold 미만 셀은 diff.diff_m 에서 여전히 읽을 수 있다 — 이 함수가
    지우지 않는다(diff_raster.py '문턱 미만 셀은 지우지 않는다' 관례와 동형)."""
    diff_m, valid = _grid()
    diff_m[0, 0] = 0.3
    diff_m[9, 9] = 0.01  # threshold(0.05) 미만
    diff = _diff(diff_m, valid)
    _report(diff)
    assert diff.diff_m[9, 9] == pytest.approx(0.01)


def test_unmeasurable_ratio_is_bbox_based_not_label_based() -> None:
    """라벨 셀 자신은 마스크 구성상 전부 valid 라, bbox 로 넓혀야 구멍이 잡힌다.

    L자 모양(2개의 팔)으로 만들어 bbox 안에 라벨에 포함되지 않는 셀(팔 사이의
    빈 모서리)이 생기게 하고, 그 모서리 하나를 무효로 만든다 — 라벨 자신의
    셀만 보면 항상 0 이지만(모듈 docstring), bbox 로 보면 잡힌다.
    """
    diff_m, valid = _grid()
    diff_m[5, 5:9] = -0.3  # 가로 팔
    diff_m[5:8, 5] = -0.3  # 세로 팔 (겹치는 모서리 (5,5) 포함, L자)
    valid[7, 8] = False  # bbox(rows5-7,cols5-8) 안이지만 라벨 밖(팔 사이 빈 모서리)
    diff = _diff(diff_m, valid)
    report = _report(diff)
    assert len(report.regions) == 1
    assert report.regions[0].unmeasurable_ratio > 0.0

    fill_diff_m, fill_valid = _grid()
    fill_diff_m[0:2, 0:2] = 0.2
    fill_region = _report(_diff(fill_diff_m, fill_valid)).regions[0]
    assert fill_region.unmeasurable_ratio == pytest.approx(0.0)


def test_report_level_unmeasurable_ratio_is_footprint_wide() -> None:
    diff_m, valid = _grid(size=10)
    valid[0, 0] = False
    diff = _diff(diff_m, valid)
    report = _report(diff)
    assert report.total_cell_count == 100
    assert report.unmeasurable_cell_ratio == pytest.approx(0.01)
    assert report.unmeasurable_area_m2 == pytest.approx(1.0)


# ── 연결성 4 vs 8 ────────────────────────────────────────────────────────


def test_diagonal_touching_cells_merge_under_8_connectivity_but_split_under_4() -> None:
    diff_m, valid = _grid()
    diff_m[3, 3] = 0.2
    diff_m[4, 4] = 0.2
    diff = _diff(diff_m, valid)

    merged = _report(diff, policy=_policy(connectivity=8))
    assert len(merged.regions) == 1
    assert merged.regions[0].pixel_count == 2

    split = _report(diff, policy=_policy(connectivity=4))
    assert len(split.regions) == 2
    assert {r.pixel_count for r in split.regions} == {1}


# ── 최소 면적 필터 ───────────────────────────────────────────────────────


def test_regions_below_min_area_are_dropped_and_counted() -> None:
    diff = _two_blob_diff()
    report = _report(diff, policy=_policy(min_region_area_m2=5.0, connectivity=8))
    assert [r.pixel_count for r in report.regions] == [12]
    assert report.filtered_region_count == 1


def test_zero_survivors_is_a_valid_empty_report() -> None:
    diff_m, valid = _grid()
    diff = _diff(diff_m, valid)
    report = _report(diff)
    assert report.regions == []
    assert report.filtered_region_count == 0


# ── MAX_REGIONS fail-closed ──────────────────────────────────────────────


def test_exceeding_max_regions_raises_instead_of_truncating() -> None:
    size = 80
    diff_m, valid = _grid(size)
    # 서로 떨어진 단일 픽셀 (MAX_REGIONS + 10)개 — 8-연결에서도 서로 안 닿게 2칸씩 띈다.
    count = 0
    for row in range(0, size, 2):
        for col in range(0, size, 2):
            if count >= MAX_REGIONS + 10:
                break
            diff_m[row, col] = 0.2
            count += 1
    diff = _diff(diff_m, valid)

    with pytest.raises(RegionExtractionError, match="상한"):
        _report(diff, policy=_policy(min_region_area_m2=0.5, connectivity=8))


# ── threshold 유효성 ─────────────────────────────────────────────────────


def test_negative_threshold_is_rejected() -> None:
    diff = _two_blob_diff()
    with pytest.raises(RegionExtractionError, match="threshold_m"):
        compute_change_regions(
            diff,
            threshold_m=-0.1,
            policy=_policy(),
            change_region_set_id="s",
            diff_raster_id="d",
            design_conformance_id="dc",
            computed_at=_NOW,
        )


# ── hull 폴백 — 영역 하나의 기하 실패가 전체 응답을 죽이지 않는다 ─────────


def test_a_degenerate_region_falls_back_to_no_hull_without_failing_the_whole_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """hull 계산이 실패하면 그 영역만 aoiDraftUnavailableReason 으로 빠지고
    polygon·volume·unmeasurable_ratio 는 그대로 살아 있다."""
    import ksi_change_detection.region_extraction as region_extraction_module

    def _always_fail(*_args: object, **_kwargs: object) -> list[tuple[float, float]]:
        raise region_extraction_module.ConvexHullError("강제 실패(테스트)")

    monkeypatch.setattr(region_extraction_module, "convex_hull_2d", _always_fail)

    diff = _two_blob_diff()
    report = _report(diff)

    assert len(report.regions) == 2
    for region in report.regions:
        assert region.aoi_draft_unavailable_reason == HULL_CONSISTENCY_CHECK_FAILED
        assert region.convex_hull_polygon is None
        assert region.convex_hull_polygon_wgs84 is None
        assert region.hull_overcapture_ratio is None
        # 나머지 필드는 살아 있다.
        assert region.polygon is not None
        assert region.volume.area_m2 > 0.0


def test_hull_overcapture_ratio_is_at_least_one_for_a_convex_region() -> None:
    diff_m, valid = _grid()
    diff_m[2:6, 2:6] = 0.2  # 볼록(정사각형) 영역 — hull == 원본
    diff = _diff(diff_m, valid)
    report = _report(diff)
    assert len(report.regions) == 1
    ratio = report.regions[0].hull_overcapture_ratio
    assert ratio is not None
    assert ratio == pytest.approx(1.0, abs=1e-6)


def test_hull_overcapture_ratio_exceeds_one_for_an_l_shaped_region() -> None:
    diff_m, valid = _grid()
    # L자 모양 — 볼록이 아니므로 hull 이 실제 면적보다 넓다.
    diff_m[0:2, 0:6] = 0.2
    diff_m[0:6, 0:2] = 0.2
    diff = _diff(diff_m, valid)
    report = _report(diff)
    assert len(report.regions) == 1
    ratio = report.regions[0].hull_overcapture_ratio
    assert ratio is not None
    assert ratio > 1.0
