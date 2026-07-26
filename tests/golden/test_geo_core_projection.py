"""geo-core 투영 골든 회귀 (P0-4).

``packages/test-vectors/vectors/legacy_compat/geo_projection.json`` 의
``project_foot_point`` API 케이스(15개) + ``ksi_correctness/geo_projection_analytic.json``(6개)
+ ``ksi_correctness/enu_wgs84_roundtrip.json``(4개)를 회귀한다.

``geo_projection.json`` 의 ``zone_*`` 5케이스(``LiveGeoProjector.project`` API)는
**의도적으로 제외**한다 — ZoneLayer(폴리곤 내/외 판정)는 P0-4 범위가 아니다
(``ksi_geo_core.projection`` 모듈 docstring의 "KSI Site Intelligence 범위" 참고,
Master PRD DEC-026·§12.6: 고정 정책구역은 Fallback, 동적 위험은 Risk Field(Phase 3)로 대체).
누락이 아니라 명시적 스코프 결정임을 여기 남긴다 — 조용히 빠뜨리지 않는다.
"""

from __future__ import annotations

import math

import pytest
from ksi_geo_core.frames import enu_to_wgs84, wgs84_to_enu
from ksi_geo_core.projection import ProjectionStatus, project_foot_point
from ksi_geo_core.sync import SourceQuality, TelemetrySample
from ksi_geo_core.timestamps import TimestampSet
from ksi_test_vectors.loader import VectorCase, load_vector_file

_ZONE_CASE_IDS = {
    "zone_inside_large_hazard_zone",
    "zone_outside_far_hazard_zone",
    "zone_near_boundary_within_error_radius",
    "zone_geo_unavailable_no_telemetry",
    "zone_geo_low_confidence_degraded_quality",
}


def _telemetry_sample(raw: dict) -> TelemetrySample:
    ts = raw["timestamp_utc"]
    return TelemetrySample(
        ts=TimestampSet(source_ts_utc=ts, receive_ts_utc=ts, capture_ts_utc=ts),
        drone_lat=raw["drone_lat"],
        drone_lon=raw["drone_lon"],
        altitude_msl_m=raw["altitude_msl_m"],
        altitude_rel_m=raw["altitude_rel_m"],
        heading_deg=raw["heading_deg"],
        gimbal_pitch_deg=raw["gimbal_pitch_deg"],
        gimbal_yaw_deg=raw["gimbal_yaw_deg"],
        gimbal_roll_deg=raw["gimbal_roll_deg"],
        camera_fov_deg=raw["camera_fov_deg"],
        zoom_factor=raw["zoom_factor"],
        rtk_fixed=raw["rtk_fixed"],
        gnss_accuracy_m=raw["gnss_accuracy_m"],
        source_quality=SourceQuality(raw["source_quality"]),
    )


def _assert_close(actual: float, expected: float, *, abs_tol: float, rel_tol: float) -> None:
    assert math.isclose(actual, expected, abs_tol=abs_tol, rel_tol=rel_tol), (
        f"actual={actual!r} expected={expected!r} abs_tol={abs_tol} rel_tol={rel_tol}"
    )


_LEGACY_VECTOR = load_vector_file("legacy_compat", "geo_projection")
_PROJECTION_CASES = [c for c in _LEGACY_VECTOR.cases if c.id not in _ZONE_CASE_IDS]
assert len(_PROJECTION_CASES) == 15, "project_foot_point 케이스 수 변경 감지 — skip 목록 재검토"


@pytest.mark.parametrize("case", _PROJECTION_CASES, ids=lambda c: c.id)
def test_legacy_compat_project_foot_point(case: VectorCase) -> None:
    inp = case.input
    sample = _telemetry_sample(inp["telemetry"])
    result = project_foot_point(
        inp["u_px"],
        inp["v_px"],
        inp["width"],
        inp["height"],
        sample,
        default_fov_deg=inp["default_fov_deg"],
        fov_is_diagonal=inp["fov_is_diagonal"],
    )
    expected = case.output

    assert result.status.value == expected["reason"], case.description
    if expected["available"]:
        tol = _LEGACY_VECTOR.tolerance
        for field_name, expected_value in (
            ("lat", expected["lat"]),
            ("lon", expected["lon"]),
            ("east_m", expected["east_m"]),
            ("north_m", expected["north_m"]),
            ("geo_confidence", expected["geo_confidence"]),
            ("error_radius_m", expected["error_radius_m"]),
        ):
            actual_value = {
                "lat": result.lat,
                "lon": result.lon,
                "east_m": result.east_m,
                "north_m": result.north_m,
                "geo_confidence": result.confidence,
                "error_radius_m": result.error_radius_m,
            }[field_name]
            abs_tol, rel_tol = tol.for_field(field_name)
            assert actual_value is not None
            _assert_close(actual_value, expected_value, abs_tol=abs_tol, rel_tol=rel_tol)
    else:
        assert result.lat is None
        assert result.confidence == 0.0


@pytest.mark.parametrize("case_id", sorted(_ZONE_CASE_IDS))
def test_zone_decision_cases_deferred(case_id: str) -> None:
    """ZoneLayer는 P0-4 범위 밖 — 존재는 확인하되 실행은 의도적으로 skip."""
    _LEGACY_VECTOR.case(case_id)  # 벡터에 여전히 존재하는지만 확인(KeyError면 즉시 실패)
    pytest.skip(
        f"{case_id}: LiveGeoProjector.project(ZoneLayer)는 P0-4 범위 밖 "
        "(Master PRD DEC-026·§12.6 — Risk Field(Phase 3)로 대체 예정, 모듈 docstring 참고)"
    )


_ANALYTIC_VECTOR = load_vector_file("ksi_correctness", "geo_projection_analytic")
_HORIZON_CASE_ID = "horizon_ray_no_intersection_must_be_rejected"
_ANALYTIC_GEOMETRY_CASES = [c for c in _ANALYTIC_VECTOR.cases if c.id != _HORIZON_CASE_ID]


@pytest.mark.parametrize("case", _ANALYTIC_GEOMETRY_CASES, ids=lambda c: c.id)
def test_analytic_ground_intersection_geometry(case: VectorCase) -> None:
    """직각삼각형 항등식 — 순수 삼각비로 project_foot_point와 독립적으로 검산."""
    altitude_m = case.input["altitude_m"]
    down_deg = case.input["down_angle_from_horizontal_deg"]
    tol = _ANALYTIC_VECTOR.tolerance

    if "half_hfov_deg" in case.input:
        edge_offset = altitude_m * math.tan(math.radians(case.input["half_hfov_deg"]))
        _assert_close(
            edge_offset, case.output["edge_ray_ground_offset_m"], abs_tol=tol.abs, rel_tol=tol.rel
        )
        return

    theta = math.radians(down_deg)
    horizontal_offset_m = altitude_m / math.tan(theta)
    slant_distance_m = altitude_m / math.sin(theta)
    _assert_close(
        horizontal_offset_m, case.output["horizontal_offset_m"], abs_tol=tol.abs, rel_tol=tol.rel
    )
    _assert_close(
        slant_distance_m, case.output["slant_distance_m"], abs_tol=tol.abs, rel_tol=tol.rel
    )


def test_analytic_horizon_ray_rejected_by_project_foot_point() -> None:
    """analytic 벡터의 '수평 광선은 발산' 사실을 실제 project_foot_point로도 확인."""
    sample = TelemetrySample(
        ts=TimestampSet(source_ts_utc=0.0, receive_ts_utc=0.0, capture_ts_utc=0.0),
        drone_lat=37.5,
        drone_lon=127.0,
        altitude_rel_m=100.0,
        heading_deg=0.0,
        gimbal_pitch_deg=0.0,  # 완전 수평
        source_quality=SourceQuality.FULL,
    )
    result = project_foot_point(960.0, 540.0, 1920, 1080, sample)
    assert result.status is ProjectionStatus.ABOVE_HORIZON


_ROUNDTRIP_VECTOR = load_vector_file("ksi_correctness", "enu_wgs84_roundtrip")


@pytest.mark.parametrize("case", _ROUNDTRIP_VECTOR.cases, ids=lambda c: c.id)
def test_enu_wgs84_roundtrip(case: VectorCase) -> None:
    tol = _ROUNDTRIP_VECTOR.tolerance
    inp, expected = case.input, case.output

    lat, lon = enu_to_wgs84(inp["origin_lat"], inp["origin_lon"], inp["east_m"], inp["north_m"])
    abs_lat, rel_lat = tol.for_field("lat")
    abs_lon, rel_lon = tol.for_field("lon")
    _assert_close(lat, expected["lat"], abs_tol=abs_lat, rel_tol=rel_lat)
    _assert_close(lon, expected["lon"], abs_tol=abs_lon, rel_tol=rel_lon)

    east_back, north_back = wgs84_to_enu(inp["origin_lat"], inp["origin_lon"], lat, lon)
    _assert_close(east_back, expected["round_trip_east_m"], abs_tol=1e-6, rel_tol=1e-9)
    _assert_close(north_back, expected["round_trip_north_m"], abs_tol=1e-6, rel_tol=1e-9)

    abs_e, _ = tol.for_field("round_trip_error_east_m")
    abs_n, _ = tol.for_field("round_trip_error_north_m")
    east_budget = max(abs_e, expected["round_trip_error_east_m"] * 2 + 1e-9)
    north_budget = max(abs_n, expected["round_trip_error_north_m"] * 2 + 1e-9)
    assert abs(east_back - inp["east_m"]) <= east_budget
    assert abs(north_back - inp["north_m"]) <= north_budget
