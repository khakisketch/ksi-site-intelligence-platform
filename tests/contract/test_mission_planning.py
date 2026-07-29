"""AOI 지오메트리·커버리지 경로·WPML/KMZ 계약 (mission-geometry-route, ADR-KSI-007).

초점: ① 잘못된 구역이 typed 로 거부되는가(fail-closed — 자기교차·T-접촉·비연속
중복·범위 초과 포함, 자율 재검토 F3) ② 생성 경로가 기하 속성(전체 커버·간격 상한·
폐루프·왕복)을 만족하는가(F6) ③ KMZ 산출물이 **스펙이 요구하는** 필수 요소를
갖추는가 — 구현이 emit 한 집합의 재확인(tautology)이 아니라 독립 목록 대조다(F7)
④ FlightEnvelope 게이트(고도·excludedVolumes) ⑤ 자원 상한(F4) ⑥ 기체 enum
비하드코딩.
"""

from __future__ import annotations

import io
import itertools
import math
import zipfile
from xml.etree import ElementTree as ET

import pytest
from ksi_geo_core.frames import (
    WGS84_EQUATORIAL_RADIUS_M,
    great_circle_distance_m,
    wgs84_to_enu,
)
from ksi_mission_contracts.models import FlightEnvelope
from ksi_mission_planning import (
    AreaOfInterest,
    DroneProfile,
    GeoPoint,
    KmzBuildError,
    RouteGenerationError,
    RouteWaypoint,
    WaylineMissionConfig,
    build_kmz,
    lawnmower_route,
    perimeter_route,
)
from pydantic import ValidationError

KML_NS = "http://www.opengis.net/kml/2.2"
WPML_NS = "http://www.dji.com/wpmz/1.0.2"
NS = {"kml": KML_NS, "wpml": WPML_NS}

# 서울 인근 기준점. 축척은 geo-core frames 와 **동일 상수**에서 유도한다(자율 재검토
# P2 — 별도 상수 111_194.9 는 R=6371km 기반이라 frames 의 6378137 과 불일치했다).
_LAT0, _LON0 = 37.5000, 127.0000
_M_PER_DEG_LAT = math.radians(1.0) * WGS84_EQUATORIAL_RADIUS_M


def _pt(east_m: float, north_m: float) -> GeoPoint:
    """기준점에서 ENU (m) 만큼 떨어진 WGS84 점 — frames 등장방형 근사와 동일 축척."""
    return GeoPoint(
        lat_deg=_LAT0 + north_m / _M_PER_DEG_LAT,
        lon_deg=_LON0 + east_m / (_M_PER_DEG_LAT * math.cos(math.radians(_LAT0))),
    )


def _rect_aoi(width_m: float = 200.0, height_m: float = 100.0) -> AreaOfInterest:
    return AreaOfInterest(
        vertices=[
            _pt(0, 0),
            _pt(width_m, 0),
            _pt(width_m, height_m),
            _pt(0, height_m),
        ]
    )


_ENVELOPE = FlightEnvelope(
    allowed_volumes=["vol-1"],
    excluded_volumes=[],
    min_altitude_m=5.0,
    max_altitude_m=120.0,
)

_DRONE = DroneProfile(drone_enum_value=99, drone_sub_enum_value=0, payload_enum_value=65534)
_CONFIG = WaylineMissionConfig(
    auto_flight_speed_ms=5.0, takeoff_security_height_m=20.0, global_transitional_speed_ms=10.0
)


# ── ① AOI fail-closed ────────────────────────────────────────────────────────


def test_aoi_rejects_fewer_than_three_vertices() -> None:
    with pytest.raises(ValidationError):
        AreaOfInterest(
            vertices=[GeoPoint(lat_deg=0, lon_deg=0), GeoPoint(lat_deg=0, lon_deg=1)]
        )


def test_aoi_rejects_nonfinite_and_out_of_range() -> None:
    with pytest.raises(ValidationError):
        GeoPoint(lat_deg=float("nan"), lon_deg=127.0)
    with pytest.raises(ValidationError):
        GeoPoint(lat_deg=91.0, lon_deg=127.0)
    with pytest.raises(ValidationError):
        GeoPoint(lat_deg=37.0, lon_deg=181.0)


def test_aoi_rejects_duplicate_consecutive_vertices() -> None:
    with pytest.raises(ValidationError, match="중복 꼭짓점"):
        AreaOfInterest(vertices=[_pt(0, 0), _pt(0, 0), _pt(100, 0), _pt(100, 100)])


def test_aoi_rejects_nonconsecutive_revisit_vertex() -> None:
    """자율 재검토 F3 재현자 — 같은 점(5,10)을 재방문하는 두-로브 링."""
    with pytest.raises(ValidationError, match="중복 꼭짓점"):
        AreaOfInterest(
            vertices=[
                _pt(0, 0),
                _pt(10, 0),
                _pt(10, 10),
                _pt(5, 10),
                _pt(5, 20),
                _pt(5, 10),
                _pt(0, 10),
            ]
        )


def test_aoi_rejects_vertex_touching_nonadjacent_edge() -> None:
    """T-접촉 — 꼭짓점 (10,0) 이 비인접 변 (0,0)-(20,0) 위에 얹힘."""
    with pytest.raises(ValidationError, match="자기교차"):
        AreaOfInterest(vertices=[_pt(0, 0), _pt(20, 0), _pt(10, 0), _pt(10, 10)])


def test_aoi_rejects_self_intersection() -> None:
    """나비넥타이(bowtie) — 변 0↔2 가 내부에서 교차한다."""
    with pytest.raises(ValidationError, match="자기교차"):
        AreaOfInterest(vertices=[_pt(0, 0), _pt(100, 100), _pt(0, 100), _pt(100, 0)])


def test_aoi_rejects_zero_area_collinear() -> None:
    with pytest.raises(ValidationError, match="면적 0"):
        AreaOfInterest(vertices=[_pt(0, 0), _pt(0, 100), _pt(0, 200)])


def test_aoi_rejects_beyond_approximation_extent() -> None:
    """등장방형 근사 유효범위(10km) 초과 — 날짜변경선 걸친 링도 같은 게이트에 잡힌다."""
    with pytest.raises(ValidationError, match="유효범위"):
        AreaOfInterest(vertices=[_pt(0, 0), _pt(30_000, 0), _pt(30_000, 100)])
    with pytest.raises(ValidationError, match="유효범위"):
        AreaOfInterest(
            vertices=[
                GeoPoint(lat_deg=0.0, lon_deg=179.9),
                GeoPoint(lat_deg=0.0, lon_deg=-179.9),
                GeoPoint(lat_deg=0.1, lon_deg=-179.9),
            ]
        )


def test_aoi_rejects_too_many_vertices() -> None:
    ring = [
        _pt(100 * math.cos(2 * math.pi * k / 300), 100 * math.sin(2 * math.pi * k / 300))
        for k in range(300)
    ]
    with pytest.raises(ValidationError):
        AreaOfInterest(vertices=ring)


def test_aoi_area_of_rect_matches_expectation() -> None:
    aoi = _rect_aoi(200.0, 100.0)
    assert aoi.area_m2() == pytest.approx(200.0 * 100.0, rel=0.01)


# ── ② 경로 기하 속성 ─────────────────────────────────────────────────────────


def test_perimeter_route_closes_loop_at_mission_altitude() -> None:
    aoi = _rect_aoi()
    route = perimeter_route(aoi, altitude_m=40.0, envelope=_ENVELOPE)

    assert len(route) == len(aoi.vertices) + 1
    assert route[0] == route[-1]
    assert all(wp.altitude_m == 40.0 for wp in route)


def _scan_line_norths(route: list[RouteWaypoint]) -> list[float]:
    """스캔선들의 north(m) 좌표 — 기준점 기준."""
    norths = sorted(
        {
            round(wgs84_to_enu(_LAT0, _LON0, wp.lat_deg, wp.lon_deg)[1], 6)
            for wp in route
        }
    )
    return norths


def test_lawnmower_exactly_divisible_keeps_spacing() -> None:
    """높이 100/간격 20 — 정확히 나눠떨어지는 케이스: 선 5개, 간격 정확히 20."""
    route = lawnmower_route(
        _rect_aoi(200.0, 100.0), spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE
    )

    norths = _scan_line_norths(route)
    assert len(norths) == 5
    gaps = [b - a for a, b in itertools.pairwise(norths)]
    assert all(g == pytest.approx(20.0, rel=0.02) for g in gaps)


def test_lawnmower_full_coverage_when_not_divisible() -> None:
    """자율 재검토 F6 — 높이 110/간격 20: 스와스(±spacing/2)가 구역 전체 [0,110] 을
    덮어야 하고, 실제 간격은 20 **이하**여야 한다(성긴 방향 이탈 금지)."""
    route = lawnmower_route(
        _rect_aoi(200.0, 110.0), spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE
    )

    norths = _scan_line_norths(route)
    gaps = [b - a for a, b in itertools.pairwise(norths)]
    assert all(g <= 20.0 + 1e-6 for g in gaps), f"간격 초과: {gaps}"
    assert norths[0] - 10.0 <= 1e-6, f"하단 미커버: 첫 선 {norths[0]}"
    assert norths[-1] + 10.0 >= 110.0 - 1e-6, f"상단 미커버: 끝 선 {norths[-1]}"


def test_lawnmower_waypoints_stay_within_aoi_bounds() -> None:
    aoi = _rect_aoi(200.0, 100.0)
    route = lawnmower_route(aoi, spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE)

    lat_lo = min(v.lat_deg for v in aoi.vertices) - 1e-9
    lat_hi = max(v.lat_deg for v in aoi.vertices) + 1e-9
    lon_lo = min(v.lon_deg for v in aoi.vertices) - 1e-9
    lon_hi = max(v.lon_deg for v in aoi.vertices) + 1e-9
    for wp in route:
        assert lat_lo <= wp.lat_deg <= lat_hi
        assert lon_lo <= wp.lon_deg <= lon_hi


def test_lawnmower_boustrophedon_alternates_direction() -> None:
    """왕복: 인접 스캔선의 진행 방향이 반대다 — 총 이동거리를 줄이는 핵심 속성."""
    route = lawnmower_route(
        _rect_aoi(200.0, 100.0), spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE
    )

    line_count = len(route) // 2
    directions = []
    for i in range(line_count):
        start, end = route[2 * i], route[2 * i + 1]
        east, _ = wgs84_to_enu(start.lat_deg, start.lon_deg, end.lat_deg, end.lon_deg)
        directions.append(east > 0)
    for i in range(line_count - 1):
        assert directions[i] != directions[i + 1], "인접 스캔선 방향이 같다 — 왕복 위반"

    max_hop = max(
        great_circle_distance_m(
            route[i].lat_deg, route[i].lon_deg, route[i + 1].lat_deg, route[i + 1].lon_deg
        )
        for i in range(len(route) - 1)
    )
    assert max_hop < math.hypot(200.0, 100.0) * 0.95


def test_lawnmower_sweep_direction_is_math_convention() -> None:
    """자율 재검토 F8 — sweep_direction_deg=90(수학 규약: 북쪽)은 스캔선을 남북으로
    놓는다. 200m 폭에 간격 20 → 동서 방향으로 선이 분포해야 한다."""
    route = lawnmower_route(
        _rect_aoi(200.0, 100.0),
        spacing_m=20.0,
        altitude_m=40.0,
        envelope=_ENVELOPE,
        sweep_direction_deg=90.0,
    )

    easts = sorted(
        {round(wgs84_to_enu(_LAT0, _LON0, wp.lat_deg, wp.lon_deg)[0], 6) for wp in route}
    )
    gaps = [b - a for a, b in itertools.pairwise(easts)]
    assert len(easts) >= 10, f"남북 스캔선이 동서로 분포해야 한다 (선 {len(easts)}개)"
    assert all(g <= 20.0 + 1e-6 for g in gaps)


def test_lawnmower_narrow_polygon_gets_single_center_line() -> None:
    aoi = _rect_aoi(200.0, 10.0)  # 폭 10m < spacing 20m
    route = lawnmower_route(aoi, spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE)
    assert len(route) == 2  # 중앙선 1개


# ── ③ FlightEnvelope·자원 게이트 ─────────────────────────────────────────────


@pytest.mark.parametrize("bad_altitude", [4.9, 120.1, float("nan"), float("inf")])
def test_routes_reject_altitude_outside_envelope(bad_altitude: float) -> None:
    aoi = _rect_aoi()
    with pytest.raises(RouteGenerationError):
        perimeter_route(aoi, altitude_m=bad_altitude, envelope=_ENVELOPE)
    with pytest.raises(RouteGenerationError):
        lawnmower_route(aoi, spacing_m=20.0, altitude_m=bad_altitude, envelope=_ENVELOPE)


def test_routes_reject_envelope_with_excluded_volumes() -> None:
    """경로 기하는 volume 회피를 보증할 수 없다 — 조용한 무시 대신 거부(F5)."""
    envelope = FlightEnvelope(
        allowed_volumes=["vol-1"],
        excluded_volumes=["crane-zone"],
        min_altitude_m=5.0,
        max_altitude_m=120.0,
    )
    with pytest.raises(RouteGenerationError, match="excludedVolumes"):
        perimeter_route(_rect_aoi(), altitude_m=40.0, envelope=envelope)


@pytest.mark.parametrize("bad_spacing", [0.0, -5.0, 0.05, float("nan"), float("inf")])
def test_lawnmower_rejects_bad_spacing(bad_spacing: float) -> None:
    """하한 0.1m — 미인증 입력의 스캔선 수 폭발(OOM, F4) 차단."""
    with pytest.raises(RouteGenerationError):
        lawnmower_route(_rect_aoi(), spacing_m=bad_spacing, altitude_m=40.0, envelope=_ENVELOPE)


def test_lawnmower_rejects_waypoint_count_explosion() -> None:
    """간격 하한 위에서도 선 수가 WPML index 상한을 넘으면 할당 전에 거부(F4)."""
    aoi = _rect_aoi(200.0, 9_000.0)
    with pytest.raises(RouteGenerationError, match="상한"):
        # sweep_direction_deg=0 고정 — 자동 방향(긴 변 따라)이 선 수를 줄여
        # 게이트를 피해가지 않게, 9km 축을 가로지르는 스캔을 강제한다.
        lawnmower_route(
            aoi, spacing_m=0.1, altitude_m=40.0, envelope=_ENVELOPE, sweep_direction_deg=0.0
        )


# ── ④ WPML/KMZ 산출물 — 스펙 대조 ────────────────────────────────────────────


def _route() -> list[RouteWaypoint]:
    return lawnmower_route(_rect_aoi(), spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE)


def test_kmz_contains_standard_members() -> None:
    kmz = build_kmz(_route(), drone=_DRONE, config=_CONFIG)
    with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
        assert set(archive.namelist()) == {
            "wpmz/template.kml",
            "wpmz/waylines.wpml",
            "wpmz/res/",
        }


def _parse_kmz_member(kmz: bytes, name: str) -> ET.Element:
    with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
        return ET.fromstring(archive.read(name))


# DJI WPML 스펙(Cloud-API-Doc 20.template-kml.md)이 waypoint 템플릿에 요구하는
# 필수 요소 — 구현과 무관하게 스펙에서 독립적으로 옮긴 목록(자율 재검토 F7:
# 구현이 emit 한 집합의 재확인은 누락을 원리상 못 잡는다).
_SPEC_TEMPLATE_MISSION_CONFIG = (
    "flyToWaylineMode",
    "finishAction",
    "exitOnRCLost",
    "takeOffSecurityHeight",
    "globalTransitionalSpeed",
)
_SPEC_TEMPLATE_FOLDER = (
    "templateType",
    "templateId",
    "autoFlightSpeed",
    "globalHeight",
    "globalWaypointTurnMode",
    "gimbalPitchMode",
)


def test_template_kml_carries_spec_required_elements() -> None:
    kmz = build_kmz(_route(), drone=_DRONE, config=_CONFIG)
    root = _parse_kmz_member(kmz, "wpmz/template.kml")

    mc = root.find("kml:Document/wpml:missionConfig", NS)
    assert mc is not None
    for tag in _SPEC_TEMPLATE_MISSION_CONFIG:
        assert mc.find(f"wpml:{tag}", NS) is not None, f"missionConfig.{tag} 누락(스펙 필수)"
    assert mc.find("wpml:droneInfo/wpml:droneEnumValue", NS) is not None
    assert mc.find("wpml:payloadInfo/wpml:payloadEnumValue", NS) is not None

    folder = root.find("kml:Document/kml:Folder", NS)
    assert folder is not None
    for tag in _SPEC_TEMPLATE_FOLDER:
        assert folder.find(f"wpml:{tag}", NS) is not None, f"Folder.{tag} 누락(스펙 필수)"
    assert folder.findtext("wpml:templateType", namespaces=NS) == "waypoint"
    coord = folder.find("wpml:waylineCoordinateSysParam", NS)
    assert coord is not None
    assert coord.findtext("wpml:coordinateMode", namespaces=NS) == "WGS84"
    assert coord.findtext("wpml:heightMode", namespaces=NS) == "relativeToStartPoint"
    heading = folder.find("wpml:globalWaypointHeadingParam", NS)
    assert heading is not None, (
        "globalWaypointHeadingParam 누락 — useGlobalHeadingParam=1 의 참조 대상"
    )
    assert heading.findtext("wpml:waypointHeadingMode", namespaces=NS) is not None


def test_template_useglobal_flags_have_global_definitions() -> None:
    """useGlobal*=1 플래그가 참조하는 전역값이 실제로 존재한다(F2 의 재발 방지)."""
    kmz = build_kmz(_route(), drone=_DRONE, config=_CONFIG)
    root = _parse_kmz_member(kmz, "wpmz/template.kml")
    folder = root.find("kml:Document/kml:Folder", NS)
    assert folder is not None

    flag_to_global = {
        "useGlobalHeight": "wpml:globalHeight",
        "useGlobalTurnParam": "wpml:globalWaypointTurnMode",
        "useGlobalHeadingParam": "wpml:globalWaypointHeadingParam",
        "useGlobalSpeed": "wpml:autoFlightSpeed",
    }
    placemarks = folder.findall("kml:Placemark", NS)
    assert placemarks
    for placemark in placemarks:
        for flag, global_tag in flag_to_global.items():
            if placemark.findtext(f"wpml:{flag}", namespaces=NS) == "1":
                assert folder.find(global_tag, NS) is not None, (
                    f"{flag}=1 인데 {global_tag} 전역 정의가 없다"
                )


def test_waylines_wpml_indices_continuous_and_coordinates_lon_lat_order() -> None:
    route = _route()
    kmz = build_kmz(route, drone=_DRONE, config=_CONFIG)
    root = _parse_kmz_member(kmz, "wpmz/waylines.wpml")

    folder = root.find("kml:Document/kml:Folder", NS)
    assert folder is not None
    assert folder.findtext("wpml:executeHeightMode", namespaces=NS) == "relativeToStartPoint"

    placemarks = folder.findall("kml:Placemark", NS)
    assert len(placemarks) == len(route)
    for expected_index, (placemark, wp) in enumerate(zip(placemarks, route, strict=True)):
        assert placemark.findtext("wpml:index", namespaces=NS) == str(expected_index)
        coords = placemark.findtext("kml:Point/kml:coordinates", namespaces=NS)
        assert coords is not None
        lon_text, lat_text = coords.split(",")
        # 경도,위도 순서(KML 표준) — 뒤바뀌면 기체가 아프리카로 간다
        assert float(lon_text) == pytest.approx(wp.lon_deg, abs=1e-9)
        assert float(lat_text) == pytest.approx(wp.lat_deg, abs=1e-9)
        assert placemark.findtext("wpml:executeHeight", namespaces=NS) is not None
        assert placemark.findtext("wpml:waypointSpeed", namespaces=NS) is not None
        heading = placemark.find("wpml:waypointHeadingParam", NS)
        assert heading is not None
        turn = placemark.find("wpml:waypointTurnParam", NS)
        assert turn is not None
        assert turn.findtext("wpml:waypointTurnDampingDist", namespaces=NS) is not None
        # useStraightLine 은 Continuity 계열 turn mode 전용 — 여기서는 없어야 한다
        assert placemark.find("wpml:useStraightLine", NS) is None


def test_drone_enum_flows_from_profile_not_hardcoded() -> None:
    """M4D enum 미확정(H4) — 프로파일 값이 그대로 실려야 하고, 소스에 기체값
    하드코딩이 없어야 한다."""
    kmz = build_kmz(_route(), drone=_DRONE, config=_CONFIG)
    for member in ("wpmz/template.kml", "wpmz/waylines.wpml"):
        root = _parse_kmz_member(kmz, member)
        drone_info = root.find("kml:Document/wpml:missionConfig/wpml:droneInfo", NS)
        assert drone_info is not None
        assert drone_info.findtext("wpml:droneEnumValue", namespaces=NS) == "99"


def test_kmz_is_deterministic() -> None:
    route = _route()
    assert build_kmz(route, drone=_DRONE, config=_CONFIG) == build_kmz(
        route, drone=_DRONE, config=_CONFIG
    )


def test_kmz_rejects_single_waypoint_and_bad_config() -> None:
    single = [RouteWaypoint(lat_deg=_LAT0, lon_deg=_LON0, altitude_m=40.0)]
    with pytest.raises(KmzBuildError):
        build_kmz(single, drone=_DRONE, config=_CONFIG)
    with pytest.raises(KmzBuildError):
        WaylineMissionConfig(
            auto_flight_speed_ms=5.0,
            takeoff_security_height_m=1.0,  # < 1.2 스펙 위반
            global_transitional_speed_ms=10.0,
        )
    with pytest.raises(KmzBuildError):
        WaylineMissionConfig(
            auto_flight_speed_ms=5.0,
            takeoff_security_height_m=20.0,
            global_transitional_speed_ms=16.0,  # > 15 스펙 위반
        )


def test_kmz_rejects_nonuniform_altitude_route() -> None:
    """전역 높이 전략(useGlobalHeight=1)은 균일 고도만 표현 가능 — 비균일은 거부."""
    route = [
        RouteWaypoint(lat_deg=_LAT0, lon_deg=_LON0, altitude_m=40.0),
        RouteWaypoint(lat_deg=_LAT0 + 0.001, lon_deg=_LON0, altitude_m=50.0),
    ]
    with pytest.raises(KmzBuildError, match="비균일"):
        build_kmz(route, drone=_DRONE, config=_CONFIG)


def test_drone_profile_rejects_invalid_values() -> None:
    with pytest.raises(KmzBuildError):
        DroneProfile(drone_enum_value=-1, drone_sub_enum_value=0, payload_enum_value=1)
    with pytest.raises(KmzBuildError):
        DroneProfile(
            drone_enum_value=99,
            drone_sub_enum_value=0,
            payload_enum_value=1,
            payload_position_index=7,
        )
