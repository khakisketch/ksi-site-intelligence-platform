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
import json
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


def test_aoi_rejects_polar_vertex() -> None:
    """자율 재검토 C — |위도|>80° 는 등장방형 근사 유효권 밖(극지 퇴화)."""
    with pytest.raises(ValidationError, match="극지"):
        AreaOfInterest(
            vertices=[
                GeoPoint(lat_deg=89.98, lon_deg=0.0),
                GeoPoint(lat_deg=89.98, lon_deg=0.01),
                GeoPoint(lat_deg=89.98, lon_deg=0.02),
            ]
        )


def test_aoi_accepts_camelcase_wire_format() -> None:
    """F — AreaOfInterest/GeoPoint 는 camelCase 와이어도 받는다(populate_by_name 유지)."""
    aoi = AreaOfInterest.model_validate(
        {"vertices": [{"latDeg": 0.0, "lonDeg": 0.0}, {"latDeg": 0.0, "lonDeg": 0.001},
                      {"latDeg": 0.001, "lonDeg": 0.0}]}
    )
    assert aoi.vertices[0].lat_deg == 0.0
    # 기존 snake_case 생성 경로도 무회귀로 계속 동작한다.
    assert AreaOfInterest(vertices=[_pt(0, 0), _pt(100, 0), _pt(0, 100)]).vertices[0].lat_deg


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
    result = lawnmower_route(
        _rect_aoi(200.0, 100.0), spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE
    )
    route = result.waypoints

    norths = _scan_line_norths(route)
    assert len(norths) == 5
    gaps = [b - a for a, b in itertools.pairwise(norths)]
    assert all(g == pytest.approx(20.0, rel=0.02) for g in gaps)
    # 축정렬 직사각형 — 재검토 A-2 실측 게이트가 정확히 완전 커버로 판정해야 한다.
    assert result.coverage_ratio == 1.0


def test_lawnmower_full_coverage_when_not_divisible() -> None:
    """자율 재검토 F6 — 높이 110/간격 20: 스와스(±spacing/2)가 구역 전체 [0,110] 을
    덮어야 하고, 실제 간격은 20 **이하**여야 한다(성긴 방향 이탈 금지)."""
    result = lawnmower_route(
        _rect_aoi(200.0, 110.0), spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE
    )
    route = result.waypoints

    norths = _scan_line_norths(route)
    gaps = [b - a for a, b in itertools.pairwise(norths)]
    assert all(g <= 20.0 + 1e-6 for g in gaps), f"간격 초과: {gaps}"
    assert norths[0] - 10.0 <= 1e-6, f"하단 미커버: 첫 선 {norths[0]}"
    assert norths[-1] + 10.0 >= 110.0 - 1e-6, f"상단 미커버: 끝 선 {norths[-1]}"
    assert result.coverage_ratio == 1.0


def test_lawnmower_waypoints_stay_within_aoi_bounds() -> None:
    aoi = _rect_aoi(200.0, 100.0)
    route = lawnmower_route(aoi, spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE).waypoints

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
    ).waypoints

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
    ).waypoints

    easts = sorted(
        {round(wgs84_to_enu(_LAT0, _LON0, wp.lat_deg, wp.lon_deg)[0], 6) for wp in route}
    )
    gaps = [b - a for a, b in itertools.pairwise(easts)]
    assert len(easts) >= 10, f"남북 스캔선이 동서로 분포해야 한다 (선 {len(easts)}개)"
    assert all(g <= 20.0 + 1e-6 for g in gaps)


def test_lawnmower_narrow_polygon_gets_single_center_line() -> None:
    aoi = _rect_aoi(200.0, 10.0)  # 폭 10m < spacing 20m
    route = lawnmower_route(aoi, spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE).waypoints
    assert len(route) == 2  # 중앙선 1개


def test_lawnmower_rejects_nonconvex_t_shaped_aoi() -> None:
    """자율 재검토 A-1 — T자 AOI(비볼록): 스캔선 사이/바깥 밴드 무음 미커버 위험을
    typed 로 거부한다. 줄기 x∈[10,20]·가로대 x∈[0,30] 인 T 모양(볼록 아님)."""
    aoi = AreaOfInterest(
        vertices=[
            _pt(10, 0), _pt(20, 0), _pt(20, 30), _pt(30, 30),
            _pt(30, 40), _pt(0, 40), _pt(0, 30), _pt(10, 30),
        ]
    )
    with pytest.raises(RouteGenerationError, match="NON_CONVEX_AOI"):
        lawnmower_route(aoi, spacing_m=5.0, altitude_m=40.0, envelope=_ENVELOPE)


def test_lawnmower_rejects_coverage_below_minimum_for_sheared_parallelogram() -> None:
    """자율 재검토 A-2 — 볼록(전단 평행사변형)이어도 sweep 방향이 도형과 어긋나면
    (여기서는 sweep 을 0 으로 강제, 즉 전단축과 나란하지 않은 스캔선) 대면적
    미커버가 나고 실측 게이트가 이를 잡는다. 볼록성만으로는 보증이 부족함을
    보이는 회귀 고정."""
    aoi = AreaOfInterest(
        vertices=[_pt(0, 0), _pt(200, 0), _pt(400, 40), _pt(200, 40)]
    )
    with pytest.raises(RouteGenerationError, match="COVERAGE_BELOW_MINIMUM"):
        lawnmower_route(
            aoi, spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE, sweep_direction_deg=0.0
        )


def test_lawnmower_slightly_misaligned_sweep_passes_gate_below_full_coverage() -> None:
    """자율 재검토 A-2 — 명시 sweep 을 축정렬에서 2° 어긋내면 커버 비율이 1.0
    미만으로 떨어지되(모서리 미세 결손) 하한(0.95) 이상은 유지돼 통과한다 —
    게이트가 완전무결이 아니라 일반영역 하한만 강제함을 보인다. (해석적 정확
    계산 기준 5° 는 0.9497 로 하한 밖이다 — 격자 샘플링은 이를 통과시켰었다.
    재검증 후 각도를 2°(정확값 0.9995)로 조정.)"""
    from ksi_mission_planning.coverage import _MIN_COVERAGE_RATIO

    result = lawnmower_route(
        _rect_aoi(200.0, 100.0),
        spacing_m=20.0,
        altitude_m=40.0,
        envelope=_ENVELOPE,
        sweep_direction_deg=2.0,
    )
    assert _MIN_COVERAGE_RATIO <= result.coverage_ratio < 1.0, result.coverage_ratio


def test_lawnmower_misaligned_sweep_just_below_floor_rejected() -> None:
    """정확 계산 경계 고정 — 같은 도형에서 sweep 5° 는 정확값 0.9497 로 하한(0.95)
    바로 아래다. 샘플링 시절엔 과대평가로 통과하던 각도가 이제 거부된다.

    하한과의 여유가 6m²/20000m² 수준의 knife-edge 라(최종 반증 F-4), 통과/거부
    여부만 보면 무관한 변경에 조용히 반전될 수 있다 — **수치 자체**를 메시지에서
    회수해 고정한다."""
    with pytest.raises(
        RouteGenerationError, match=r"COVERAGE_BELOW_MINIMUM.*0\.9497"
    ):
        lawnmower_route(
            _rect_aoi(200.0, 100.0),
            spacing_m=20.0,
            altitude_m=40.0,
            envelope=_ENVELOPE,
            sweep_direction_deg=5.0,
        )


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


def test_lawnmower_fold_boundary_worst_case_keeps_full_coverage() -> None:
    """재검토 B — 과거 문턱(usable<=0.1)이 접던 최악값 height=spacing+0.1: 지금은
    접지 않고 선 2개를 유지해 커버가 수학적으로 완전해야 한다(ratio==1.0, 양끝
    미커버 없음). 축정렬 직사각형이라 실측도 정확히 1.0 이 나온다."""
    result = lawnmower_route(
        _rect_aoi(200.0, 20.1), spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE
    )
    norths = _scan_line_norths(result.waypoints)
    assert len(norths) == 2, f"선 2개가 유지돼야 한다: {norths}"
    assert norths[0] - 10.0 <= 1e-6, f"하단 미커버: {norths[0]}"
    assert norths[-1] + 10.0 >= 20.1 - 1e-6, f"상단 미커버: {norths[-1]}"
    assert result.coverage_ratio == 1.0


# ── ④ WPML/KMZ 산출물 — 스펙 대조 ────────────────────────────────────────────


def _route() -> list[RouteWaypoint]:
    return lawnmower_route(
        _rect_aoi(), spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE
    ).waypoints


def test_kmz_contains_standard_members() -> None:
    kmz = build_kmz(_route(), drone=_DRONE, config=_CONFIG)
    with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
        assert set(archive.namelist()) == {
            "wpmz/template.kml",
            "wpmz/waylines.wpml",
            "wpmz/res/",
        }


def test_build_kmz_pair_manifest_round_trips() -> None:
    """W2 인터페이스 계약 E — pair_manifest 는 wpmz/res/ksi-mission-pair.json 로
    왕복(zip 재파싱 후 내용 일치)한다. sort_keys·컴팩트 separators·
    ensure_ascii=False 를 원본 바이트 대조로 확인한다(한글 값 포함)."""
    manifest = {"missionContractId": "mc-001", "kmzSha256": "deadbeef", "label": "한글값"}
    kmz = build_kmz(_route(), drone=_DRONE, config=_CONFIG, pair_manifest=manifest)
    with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
        assert "wpmz/res/ksi-mission-pair.json" in archive.namelist()
        raw = archive.read("wpmz/res/ksi-mission-pair.json")

    assert json.loads(raw) == manifest
    expected = json.dumps(
        manifest, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    assert raw == expected


def test_build_kmz_without_pair_manifest_omits_pair_file() -> None:
    kmz = build_kmz(_route(), drone=_DRONE, config=_CONFIG)
    with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
        assert "wpmz/res/ksi-mission-pair.json" not in archive.namelist()


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
    # 공식 표(raw) 기준 무조건 필수 — 재검토 blocker #1 의 회귀 고정
    assert heading.findtext("wpml:waypointHeadingPathMode", namespaces=NS) is not None


def test_template_useglobal_flags_have_global_definitions() -> None:
    """useGlobal*=1 플래그가 참조하는 전역값이 실제로 존재한다(F2 의 재발 방지) —
    capture_at_waypoints=True 로 template.kml 에도 실리는 actionGroup(재검토 D-3)
    까지 포함한다. useGlobalPayloadLensIndex 는 참조할 전역 payloadParam 이 이
    생성기 어디에도 없으므로(D-1), 앞으로 실수로 "1"이 나오면 이 테스트가 즉시
    잡는다(D-2 회귀 가드)."""
    kmz = build_kmz(_route(), drone=_DRONE, config=_CONFIG, capture_at_waypoints=True)
    root = _parse_kmz_member(kmz, "wpmz/template.kml")
    folder = root.find("kml:Document/kml:Folder", NS)
    assert folder is not None

    flag_to_global = {
        "useGlobalHeight": "wpml:globalHeight",
        "useGlobalTurnParam": "wpml:globalWaypointTurnMode",
        "useGlobalHeadingParam": "wpml:globalWaypointHeadingParam",
        "useGlobalSpeed": "wpml:autoFlightSpeed",
        # 지역 payloadLensIndex 가 권위이고(D-1) 이 생성기는 어떤 전역
        # payloadParam 도 emit 하지 않는다 — "1" 이 나오면 아래 태그(존재하지
        # 않음)가 없어 즉시 실패해야 한다.
        "useGlobalPayloadLensIndex": "wpml:globalPayloadLensIndex",
    }
    placemarks = folder.findall("kml:Placemark", NS)
    assert placemarks
    for placemark in placemarks:
        for flag, global_tag in flag_to_global.items():
            # .// — useGlobalPayloadLensIndex 는 Placemark 직계가 아니라
            # actionGroup/action/actionActuatorFuncParam 아래 중첩돼 있다.
            for match in placemark.findall(f".//wpml:{flag}", NS):
                if match.text == "1":
                    assert folder.find(global_tag, NS) is not None, (
                        f"{flag}=1 인데 {global_tag} 전역 정의가 없다"
                    )


def test_template_and_waylines_capture_actions_are_equivalent() -> None:
    """자율 재검토 D-3 — capture_at_waypoints=True 면 template.kml 과
    waylines.wpml 이 웨이포인트별로 **동일한** actionGroup 을 담는다. 한 KMZ 의
    두 파일이 서로 다른 임무를 기술하면(예: waylines 만 촬영) 편집기에서 보는
    template 과 실제 실행 내용이 어긋난다."""
    kmz = build_kmz(_route(), drone=_DRONE, config=_CONFIG, capture_at_waypoints=True)
    template_root = _parse_kmz_member(kmz, "wpmz/template.kml")
    waylines_root = _parse_kmz_member(kmz, "wpmz/waylines.wpml")

    def _action_groups(root: ET.Element) -> list[ET.Element | None]:
        placemarks = root.findall("kml:Document/kml:Folder/kml:Placemark", NS)
        return [pm.find("wpml:actionGroup", NS) for pm in placemarks]

    template_groups = _action_groups(template_root)
    waylines_groups = _action_groups(waylines_root)
    assert template_groups, "캡처 켠 상태인데 template.kml 에 actionGroup 이 없다"
    assert len(template_groups) == len(waylines_groups)

    for i, (t_group, w_group) in enumerate(zip(template_groups, waylines_groups, strict=True)):
        assert t_group is not None, f"template 웨이포인트 {i} 에 actionGroup 없음"
        assert w_group is not None, f"waylines 웨이포인트 {i} 에 actionGroup 없음"
        t_xml = ET.tostring(t_group, encoding="unicode")
        w_xml = ET.tostring(w_group, encoding="unicode")
        assert t_xml == w_xml, f"웨이포인트 {i} 의 actionGroup 이 template/waylines 사이에 다르다"


# DJI WPML 스펙(Cloud-API-Doc 21.waylines-wpml.md)이 waylines Folder 에 요구하는
# 필수 요소 — template 쪽과 같은 F7 방법론(구현과 무관한 독립 목록).
_SPEC_WAYLINES_FOLDER = (
    "templateId",
    "executeHeightMode",
    "waylineId",
    "autoFlightSpeed",
)


def test_waylines_wpml_carries_spec_required_folder_elements() -> None:
    """자율 재검토 D-5 — F7 방법론을 waylines Folder 에도 적용(독립 목록 대조)."""
    kmz = build_kmz(_route(), drone=_DRONE, config=_CONFIG)
    root = _parse_kmz_member(kmz, "wpmz/waylines.wpml")
    folder = root.find("kml:Document/kml:Folder", NS)
    assert folder is not None
    for tag in _SPEC_WAYLINES_FOLDER:
        assert folder.find(f"wpml:{tag}", NS) is not None, f"Folder.{tag} 누락(스펙 필수)"


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
        assert heading.findtext("wpml:waypointHeadingPathMode", namespaces=NS) is not None
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


def test_drone_profile_all_four_fields_flow_without_hardcoding() -> None:
    """자율 재검토 D-6 — DroneProfile 4필드(drone_enum_value·drone_sub_enum_value·
    payload_enum_value·payload_position_index) 전부가, missionConfig 뿐 아니라
    촬영 action(payloadPositionIndex, capture_at_waypoints=True)까지 그대로
    흘러야 한다. _DRONE(기본 픽스처)이 0 값 위주라 우연히 통과할 여지를 없애기
    위해 넷 다 서로 다른 비영값을 쓴다."""
    distinctive_drone = DroneProfile(
        drone_enum_value=91,
        drone_sub_enum_value=3,
        payload_enum_value=77,
        payload_position_index=2,
    )
    kmz = build_kmz(
        _route(), drone=distinctive_drone, config=_CONFIG, capture_at_waypoints=True
    )
    for member in ("wpmz/template.kml", "wpmz/waylines.wpml"):
        root = _parse_kmz_member(kmz, member)
        drone_info = root.find("kml:Document/wpml:missionConfig/wpml:droneInfo", NS)
        assert drone_info is not None
        assert drone_info.findtext("wpml:droneEnumValue", namespaces=NS) == "91"
        assert drone_info.findtext("wpml:droneSubEnumValue", namespaces=NS) == "3"
        payload_info = root.find("kml:Document/wpml:missionConfig/wpml:payloadInfo", NS)
        assert payload_info is not None
        assert payload_info.findtext("wpml:payloadEnumValue", namespaces=NS) == "77"
        assert payload_info.findtext("wpml:payloadPositionIndex", namespaces=NS) == "2"

        placemark = root.find("kml:Document/kml:Folder/kml:Placemark", NS)
        assert placemark is not None
        for action_param in placemark.findall(".//wpml:actionActuatorFuncParam", NS):
            payload_position = action_param.findtext(
                "wpml:payloadPositionIndex", namespaces=NS
            )
            assert payload_position == "2", (
                f"{member} action payloadPositionIndex 가 프로파일과 다르다: "
                f"{payload_position}"
            )


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


def test_capture_actions_present_when_enabled_and_absent_otherwise() -> None:
    """매핑 촬영 기본(2026-07-29 대표자 승인) — capture 켜면 모든 웨이포인트에
    takePhoto actionGroup, 첫 웨이포인트에만 gimbalRotate(nadir). 끄면 전무."""
    route = _route()
    with_capture = build_kmz(route, drone=_DRONE, config=_CONFIG, capture_at_waypoints=True)
    root = _parse_kmz_member(with_capture, "wpmz/waylines.wpml")
    placemarks = root.findall("kml:Document/kml:Folder/kml:Placemark", NS)
    assert placemarks
    for i, placemark in enumerate(placemarks):
        group = placemark.find("wpml:actionGroup", NS)
        assert group is not None, f"웨이포인트 {i} 에 actionGroup 없음"
        # 스펙 필수 4형제(actionGroupId/Start/End/Mode) + trigger
        for tag in ("actionGroupId", "actionGroupStartIndex", "actionGroupEndIndex",
                    "actionGroupMode"):
            assert group.findtext(f"wpml:{tag}", namespaces=NS) is not None
        assert (
            group.findtext("wpml:actionTrigger/wpml:actionTriggerType", namespaces=NS)
            == "reachPoint"
        )
        funcs = [
            a.findtext("wpml:actionActuatorFunc", namespaces=NS)
            for a in group.findall("wpml:action", NS)
        ]
        assert "takePhoto" in funcs, f"웨이포인트 {i} 에 takePhoto 없음"
        assert ("gimbalRotate" in funcs) == (i == 0), f"gimbalRotate 배치 오류 (웨이포인트 {i})"
        # takePhoto 필수 파라미터(공식 40.common-element 표)
        photo = next(
            a for a in group.findall("wpml:action", NS)
            if a.findtext("wpml:actionActuatorFunc", namespaces=NS) == "takePhoto"
        )
        for tag in ("payloadPositionIndex", "fileSuffix", "payloadLensIndex",
                    "useGlobalPayloadLensIndex"):
            assert photo.findtext(
                f"wpml:actionActuatorFuncParam/wpml:{tag}", namespaces=NS
            ) is not None, f"takePhoto 파라미터 {tag} 누락"
        # 자율 재검토 D-1 — 지역 payloadLensIndex 가 권위다. 참조 대상 전역이
        # 없으므로 "1"(전역 사용)이면 dangling 참조가 된다(F2 와 동일 클래스).
        assert (
            photo.findtext(
                "wpml:actionActuatorFuncParam/wpml:useGlobalPayloadLensIndex", namespaces=NS
            )
            == "0"
        ), f"웨이포인트 {i} useGlobalPayloadLensIndex 가 dangling 참조(1)를 가리킨다"

    without = build_kmz(route, drone=_DRONE, config=_CONFIG)
    root = _parse_kmz_member(without, "wpmz/waylines.wpml")
    assert not root.findall("kml:Document/kml:Folder/kml:Placemark/wpml:actionGroup", NS)


def test_segments_intersect_touch_branch_actually_fires() -> None:
    """재검토 #3 — 기존 T-접촉 링 테스트는 proper 분기로도 잡힌다. 여기서는 orient
    부호가 같은쪽(d3=0, d4<0)이라 **epsilon/_on_segment 분기로만** 잡히는 접촉을
    직접 검증한다: p=(0,0)-(20,0) 위에 q 의 시작점 (10,0)이 얹히고 q 는 아래로."""
    from ksi_mission_planning.geometry import _segments_intersect

    assert _segments_intersect((0.0, 0.0), (20.0, 0.0), (10.0, 0.0), (5.0, -5.0))
    # 대조군: 같은 형상에서 q 를 선분 밖으로 옮기면 교차 아님
    assert not _segments_intersect((0.0, 0.0), (20.0, 0.0), (25.0, 0.0), (30.0, -5.0))


def test_gimbal_rotate_uses_spec_enum_values() -> None:
    """재검토 blocker #2 회귀 고정 — gimbalHeadingYawBase 열거값은 north 뿐이다."""
    kmz = build_kmz(_route(), drone=_DRONE, config=_CONFIG, capture_at_waypoints=True)
    root = _parse_kmz_member(kmz, "wpmz/waylines.wpml")
    gimbal_params = [
        a.find("wpml:actionActuatorFuncParam", NS)
        for a in root.findall(".//wpml:action", NS)
        if a.findtext("wpml:actionActuatorFunc", namespaces=NS) == "gimbalRotate"
    ]
    assert gimbal_params, "gimbalRotate 액션이 없다"
    for param in gimbal_params:
        assert param is not None
        assert param.findtext("wpml:gimbalHeadingYawBase", namespaces=NS) == "north"
        assert param.findtext("wpml:gimbalRotateMode", namespaces=NS) == "absoluteAngle"


# 공식 40.common-element.md raw 표 기준 gimbalRotate actionActuatorFuncParam 필수
# 11필드 — 구현과 무관한 독립 목록(F7 방법론, 재검토 D-6: 기존 테스트는 enum 값
# 2개(YawBase·RotateMode)만 봤다).
_SPEC_GIMBAL_ROTATE_PARAM_FIELDS = (
    "payloadPositionIndex",
    "gimbalHeadingYawBase",
    "gimbalRotateMode",
    "gimbalPitchRotateEnable",
    "gimbalPitchRotateAngle",
    "gimbalRollRotateEnable",
    "gimbalRollRotateAngle",
    "gimbalYawRotateEnable",
    "gimbalYawRotateAngle",
    "gimbalRotateTimeEnable",
    "gimbalRotateTime",
)


def test_gimbal_rotate_param_has_all_eleven_required_fields() -> None:
    """자율 재검토 D-6 — gimbalRotate 필수 11필드 완전성(독립 목록 대조)."""
    kmz = build_kmz(_route(), drone=_DRONE, config=_CONFIG, capture_at_waypoints=True)
    root = _parse_kmz_member(kmz, "wpmz/waylines.wpml")
    gimbal_params = [
        a.find("wpml:actionActuatorFuncParam", NS)
        for a in root.findall(".//wpml:action", NS)
        if a.findtext("wpml:actionActuatorFunc", namespaces=NS) == "gimbalRotate"
    ]
    assert gimbal_params, "gimbalRotate 액션이 없다"
    assert len(_SPEC_GIMBAL_ROTATE_PARAM_FIELDS) == 11
    for param in gimbal_params:
        assert param is not None
        for field in _SPEC_GIMBAL_ROTATE_PARAM_FIELDS:
            assert param.findtext(f"wpml:{field}", namespaces=NS) is not None, (
                f"gimbalRotate 파라미터 {field} 누락(스펙 필수 11필드)"
            )


def test_near_equal_height_and_spacing_collapses_to_single_line() -> None:
    """재검토 경계 케이스 — 폭이 spacing+ε(부동소수 잡음 수준, ``_FOLD_EPSILON_M``
    미만)이면 스캔선 2개가 아니라 중앙선 1개로 접힌다(동일 좌표 웨이포인트 쌍
    방지). ``_FOLD_EPSILON_M`` 이상은 재검토 B 로 더 이상 접지 않으므로(선 2개
    유지가 커버를 수학적으로 보존한다), 문턱보다 확실히 작은 ε 을 쓴다."""
    aoi = _rect_aoi(200.0, 20.0 + 1e-9)
    route = lawnmower_route(aoi, spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE).waypoints
    assert len(route) == 2


def test_fold_branch_shear_shape_rejected_by_exact_coverage() -> None:
    """재검증 P1 회귀 — 접기 분기(spacing≥높이) × 전단 도형. 격자 샘플링은 이
    조합에서 행이 1줄로 붕괴해 실커버 0.667 을 1.0 으로 보고했다(거짓 증명서로
    201 발급). 해석적 정확 계산은 0.6667 로 재고 거부해야 한다."""
    aoi = AreaOfInterest(vertices=[_pt(0, 0), _pt(30, 0), _pt(70, 20), _pt(40, 20)])
    with pytest.raises(RouteGenerationError, match=r"COVERAGE_BELOW_MINIMUM.*0\.6667"):
        lawnmower_route(
            aoi, spacing_m=60.0, altitude_m=40.0, envelope=_ENVELOPE, sweep_direction_deg=0.0
        )


def test_fold_branch_full_coverage_not_falsely_rejected_no_spacing_cliff() -> None:
    """재검증 P2 회귀 — spacing 이 AOI 높이보다 훨씬 크면 격자 샘플링은 행 0줄로
    붕괴해 완전 커버 임무를 0.0 으로 거부했고, 79.9→통과/80.0→거부 절벽이 있었다.
    정확 계산에서는 둘 다 1.0 으로 통과한다(중앙선 1개의 ±spacing/2 스와스가
    높이 10m 를 전부 덮는다)."""
    for spacing in (79.9, 80.0):
        result = lawnmower_route(
            _rect_aoi(200.0, 10.0), spacing_m=spacing, altitude_m=40.0, envelope=_ENVELOPE
        )
        assert result.coverage_ratio == 1.0, f"spacing={spacing}"
        assert len(result.waypoints) == 2


def test_generated_routes_stay_inside_convex_aoi_polygon() -> None:
    """criteria 'AOI 내부'를 bbox 가 아니라 **폴리곤 내부**로 검증한다(재검토 R4 —
    기존엔 bbox 검사뿐이라 전단 도형에서 폴리곤 밖 이탈을 원리상 못 잡았다).

    볼록 AOI 에서 웨이포인트가 전부 내부/경계면, 볼록성에 의해 연결 세그먼트도
    내부다 — 웨이포인트와 인접 웨이포인트 중점 모두를 부호 외적으로 판정한다."""
    corners = [(0.0, 0.0), (200.0, 0.0), (230.0, 90.0), (30.0, 90.0)]  # CCW 전단
    aoi = AreaOfInterest(vertices=[_pt(e, n) for e, n in corners])

    def to_enu(lat_deg: float, lon_deg: float) -> tuple[float, float]:
        return (
            (lon_deg - _LON0) * _M_PER_DEG_LAT * math.cos(math.radians(_LAT0)),
            (lat_deg - _LAT0) * _M_PER_DEG_LAT,
        )

    def inside(px: float, py: float, tol_m: float = 1e-3) -> bool:
        n = len(corners)
        for i in range(n):
            ax, ay = corners[i]
            bx, by = corners[(i + 1) % n]
            cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
            if cross < -tol_m * math.hypot(bx - ax, by - ay):
                return False
        return True

    lawn = lawnmower_route(aoi, spacing_m=15.0, altitude_m=40.0, envelope=_ENVELOPE).waypoints
    peri = perimeter_route(aoi, altitude_m=40.0, envelope=_ENVELOPE)
    for label, route in (("lawnmower", lawn), ("perimeter", peri)):
        points = [to_enu(w.lat_deg, w.lon_deg) for w in route]
        for i, (px, py) in enumerate(points):
            assert inside(px, py), f"{label} 웨이포인트 {i} 가 AOI 폴리곤 밖: ({px:.3f},{py:.3f})"
        for i in range(len(points) - 1):
            mx = (points[i][0] + points[i + 1][0]) / 2.0
            my = (points[i][1] + points[i + 1][1]) / 2.0
            assert inside(mx, my), f"{label} 세그먼트 {i} 중점이 AOI 폴리곤 밖"


# ── 진행방향(along-track) 촬영 간격 — 전방 중첩 0 결함 (risk mapping-forward-overlap-zero) ──


def _along_track_gaps(route: list[RouteWaypoint]) -> list[float]:
    """같은 스캔선(동일 north) 위 이웃 웨이포인트 사이의 진행방향 거리(m)."""
    by_line: dict[float, list[float]] = {}
    for wp in route:
        east, north = wgs84_to_enu(_LAT0, _LON0, wp.lat_deg, wp.lon_deg)
        by_line.setdefault(round(north, 6), []).append(east)
    gaps: list[float] = []
    for easts in by_line.values():
        ordered = sorted(easts)
        gaps.extend(b - a for a, b in itertools.pairwise(ordered))
    return gaps


def test_without_capture_interval_scan_line_has_only_endpoints() -> None:
    """[기준선] 간격을 주지 않으면 스캔선당 2점 — 이게 전방 중첩 0 의 실체다."""
    route = lawnmower_route(
        _rect_aoi(200.0, 100.0), spacing_m=20.0, altitude_m=40.0, envelope=_ENVELOPE
    ).waypoints

    per_line: dict[float, int] = {}
    for wp in route:
        _east, north = wgs84_to_enu(_LAT0, _LON0, wp.lat_deg, wp.lon_deg)
        per_line[round(north, 6)] = per_line.get(round(north, 6), 0) + 1
    assert set(per_line.values()) == {2}


def test_capture_interval_fills_scan_line_within_requested_gap() -> None:
    """[핵심] 촬영 간격을 주면 스캔선 위 이웃 간격이 요청값을 **넘지 않는다**.

    넘는 방향의 이탈은 곧 중첩 부족이고, 중첩 부족은 비행이 끝난 뒤 재구성이
    실패할 때에야 드러난다 — spacing 과 같은 '조밀해지는 방향만 허용' 규약이다.
    """
    interval = 15.0
    route = lawnmower_route(
        _rect_aoi(200.0, 100.0),
        spacing_m=20.0,
        altitude_m=40.0,
        envelope=_ENVELOPE,
        capture_interval_m=interval,
    ).waypoints

    gaps = _along_track_gaps(route)
    assert gaps, "스캔선 위 이웃 쌍이 없다 — 채워지지 않았다"
    assert all(g <= interval + 1e-6 for g in gaps), f"간격 초과: {max(gaps)}"
    # 200m 스캔선을 15m 간격으로 채우면 선당 구간 14개(=ceil(200/15)) — 끝점 2개
    # 뿐이던 과거(구간 1개)와 확실히 구별된다.
    assert len(gaps) >= 14


def test_capture_interval_covers_scan_line_ends() -> None:
    """끝점이 빠지면 AOI 경계 밴드가 재구성에서 잘린다 — 끝점은 항상 포함한다."""
    route = lawnmower_route(
        _rect_aoi(200.0, 100.0),
        spacing_m=20.0,
        altitude_m=40.0,
        envelope=_ENVELOPE,
        capture_interval_m=15.0,
    ).waypoints

    easts = [wgs84_to_enu(_LAT0, _LON0, wp.lat_deg, wp.lon_deg)[0] for wp in route]
    assert min(easts) == pytest.approx(0.0, abs=1e-3)
    assert max(easts) == pytest.approx(200.0, abs=1e-3)


def test_capture_interval_preserves_boustrophedon_direction() -> None:
    """채워 넣은 점이 왕복 순서를 깨면 기체가 스캔선을 지그재그로 되돌아간다."""
    route = lawnmower_route(
        _rect_aoi(200.0, 100.0),
        spacing_m=50.0,
        altitude_m=40.0,
        envelope=_ENVELOPE,
        capture_interval_m=50.0,
    ).waypoints

    lines: list[list[float]] = []
    current_north: float | None = None
    for wp in route:
        east, north = wgs84_to_enu(_LAT0, _LON0, wp.lat_deg, wp.lon_deg)
        key = round(north, 6)
        if key != current_north:
            lines.append([])
            current_north = key
        lines[-1].append(east)
    directions = [line[-1] - line[0] > 0 for line in lines if len(line) > 1]
    assert len(directions) >= 2
    for previous, nxt in itertools.pairwise(directions):
        assert previous != nxt, f"왕복이 아니다: {directions}"


def test_capture_interval_longer_than_line_keeps_endpoints() -> None:
    """구간보다 긴 간격은 끝점 2장으로 이미 조건을 만족한다 — 억지로 쪼개지 않는다."""
    # sweep 을 동서로 고정 — 자동 선택은 긴 변(북남)을 고르므로 스캔선이 세로가 된다.
    route = lawnmower_route(
        _rect_aoi(50.0, 100.0),
        spacing_m=20.0,
        altitude_m=40.0,
        envelope=_ENVELOPE,
        sweep_direction_deg=0.0,
        capture_interval_m=500.0,
    ).waypoints

    gaps = _along_track_gaps(route)
    assert gaps
    assert all(g == pytest.approx(50.0, abs=1e-3) for g in gaps)


@pytest.mark.parametrize("value", [0.0, -1.0, float("nan"), 0.05])
def test_invalid_capture_interval_rejected(value: float) -> None:
    with pytest.raises(RouteGenerationError, match="capture_interval_m"):
        lawnmower_route(
            _rect_aoi(200.0, 100.0),
            spacing_m=20.0,
            altitude_m=40.0,
            envelope=_ENVELOPE,
            capture_interval_m=value,
        )
