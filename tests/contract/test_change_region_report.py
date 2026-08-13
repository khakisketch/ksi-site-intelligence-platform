"""ChangeRegionSetReport 계약 — 참조 일치·threshold 일치·hull 비율 하한 (M4-E).

초점 셋:

1. **regionId 중복 금지** — 같은 영역이 두 번 실리면 집계가 조용히 두 배가 된다.
2. **threshold 가 한 값이다** — 영역의 ``volume.thresholdM`` 이 리포트의
   ``thresholdM`` 과 갈리면 범례와 집계가 다른 기준을 말한다
   (``design_conformance_report.py`` 와 같은 근거).
3. **hullOvercaptureRatio 하한** — 볼록 껍질은 원본보다 좁을 수 없다(0.999 이상).
4. **aoiDraftUnavailableReason 이 있으면 hull 필드는 전부 null** — 절반만
   실으면 화면이 그 절반을 유효한 값으로 읽는다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ksi_event_contracts.change_region_report import ChangeRegion, ChangeRegionSetReport
from ksi_event_contracts.region_extraction_policy import current_region_extraction_policy
from ksi_event_contracts.volume_change_report import ZoneVolumeDelta
from pydantic import ValidationError

_NOW = datetime(2026, 8, 13, 3, 0, tzinfo=UTC)
_POLICY = current_region_extraction_policy()
_THRESHOLD_M = 0.05

_POLYGON = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]],
}


def _volume(**overrides: object) -> ZoneVolumeDelta:
    payload: dict[str, object] = {
        "zone_id": "r-1",
        "cut_m3": 3.0,
        "fill_m3": 1.0,
        "net_m3": -2.0,
        "area_m2": 4.0,
        "threshold_m": _THRESHOLD_M,
        "uncertainty_m3": None,
        "uncertainty_note": "설계 대비 잔량 diffRaster 에서 파생됐다 — 오차한계가 없다",
    }
    payload.update(overrides)
    return ZoneVolumeDelta(**payload)  # type: ignore[arg-type]


def _region(**overrides: object) -> ChangeRegion:
    payload: dict[str, object] = {
        "region_id": "r-1",
        "volume": _volume(),
        "pixel_count": 4,
        "polygon": _POLYGON,
        "convex_hull_polygon": _POLYGON,
        "convex_hull_polygon_wgs84": {
            "type": "Polygon",
            "coordinates": [
                [[127.0, 37.0], [127.001, 37.0], [127.001, 37.001], [127.0, 37.001], [127.0, 37.0]]
            ],
        },
        "hull_overcapture_ratio": 1.0,
        "aoi_draft_unavailable_reason": None,
        "unmeasurable_ratio": 0.0,
    }
    payload.update(overrides)
    return ChangeRegion(**payload)  # type: ignore[arg-type]


def _report(**overrides: object) -> ChangeRegionSetReport:
    payload: dict[str, object] = {
        "change_region_set_id": "dcf-1-rex1",
        "design_conformance_id": "dcf-1",
        "diff_raster_id": "dcf-1-diff",
        "crs": "EPSG:5186",
        "threshold_m": _THRESHOLD_M,
        "extraction_policy": _POLICY,
        "regions": [_region()],
        "filtered_region_count": 0,
        "unmeasurable_cell_ratio": 0.0,
        "unmeasurable_area_m2": 0.0,
        "total_cell_count": 100,
        "computed_at": _NOW,
    }
    payload.update(overrides)
    return ChangeRegionSetReport(**payload)  # type: ignore[arg-type]


def test_a_well_formed_report_round_trips() -> None:
    report = _report()
    dumped = report.model_dump(by_alias=True, mode="json")
    restored = ChangeRegionSetReport.model_validate(dumped)
    assert restored == report


def test_zero_regions_is_valid() -> None:
    report = _report(regions=[], filtered_region_count=0)
    assert report.regions == []


def test_computed_at_must_be_tz_aware() -> None:
    with pytest.raises(ValidationError, match="tz-aware"):
        _report(computed_at=datetime(2026, 8, 13, 3, 0))  # naive


def test_duplicate_region_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="regionId"):
        _report(regions=[_region(region_id="r-1"), _region(region_id="r-1")])


def test_region_threshold_must_match_the_report_threshold() -> None:
    with pytest.raises(ValidationError, match="thresholdM"):
        _report(regions=[_region(volume=_volume(threshold_m=0.10))])


def test_hull_overcapture_ratio_below_lower_bound_is_rejected() -> None:
    with pytest.raises(ValidationError, match="hullOvercaptureRatio"):
        _report(regions=[_region(hull_overcapture_ratio=0.5)])


def test_hull_overcapture_ratio_at_exactly_the_floating_point_floor_is_accepted() -> None:
    report = _report(regions=[_region(hull_overcapture_ratio=0.999)])
    assert report.regions[0].hull_overcapture_ratio == pytest.approx(0.999)


def test_non_finite_hull_overcapture_ratio_is_rejected() -> None:
    with pytest.raises(ValidationError, match="finite"):
        _report(regions=[_region(hull_overcapture_ratio=float("inf"))])


def test_hull_fields_must_all_be_null_when_the_draft_is_unavailable() -> None:
    with pytest.raises(ValidationError, match="aoiDraftUnavailableReason"):
        _region(
            aoi_draft_unavailable_reason="HULL_CONSISTENCY_CHECK_FAILED",
            convex_hull_polygon=_POLYGON,
        )


def test_a_region_can_legitimately_have_no_hull_draft() -> None:
    region = _region(
        aoi_draft_unavailable_reason="HULL_CONSISTENCY_CHECK_FAILED",
        convex_hull_polygon=None,
        convex_hull_polygon_wgs84=None,
        hull_overcapture_ratio=None,
    )
    assert region.aoi_draft_unavailable_reason == "HULL_CONSISTENCY_CHECK_FAILED"


def test_max_regions_constant_is_five_hundred() -> None:
    from ksi_event_contracts.change_region_report import MAX_REGIONS

    assert MAX_REGIONS == 500


def test_extraction_policy_defaults_match_the_current_policy_function() -> None:
    policy = current_region_extraction_policy()
    assert policy.min_region_area_m2 > 0
    assert policy.connectivity in (4, 8)
