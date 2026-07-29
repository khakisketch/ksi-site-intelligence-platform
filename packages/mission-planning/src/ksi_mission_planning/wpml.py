"""DJI WPML 웨이라인 KMZ 생성 — 기체측 임무 산출물 (ADR-KSI-007).

스펙 근거: DJI Cloud-API-Doc `60.api-reference/00.dji-wpml/` (overview·template-kml·
waylines-wpml, 2026-07-29 정독). 요지:

- ``.kmz`` 는 ZIP 아카이브다. 내부에 ``template.kml``(편집 가능한 템플릿)과
  ``waylines.wpml``(실행 확정 경로)을 담는다. 최상위 폴더명 ``wpmz/`` 는 공식
  문서 텍스트로 확정하지 못한 **관례**다(문서 구조도가 이미지라 미추출) —
  H4(실기 Pilot 2 임포트 검증)에서 확정하며, 불일치 시 이 모듈만 고치면 된다.
- 두 XML 모두 루트 ``<kml xmlns=KML2.2 xmlns:wpml=http://www.dji.com/wpmz/1.0.2>``.
- 좌표계는 WGS84 고정(coordinateMode), ``coordinates`` 는 **"경도,위도" 순서**다
  (KML 표준 — 위경도 아님에 주의).
- 높이 모드 enum 이 두 파일에서 다르다: template=heightMode(EGM96/relativeToStartPoint/
  aboveGroundLevel/realTimeFollowSurface), waylines=executeHeightMode(WGS84/
  relativeToStartPoint/realTimeFollowSurface). 본 생성기는 양쪽 공통이며 지형
  데이터 없이 안전한 ``relativeToStartPoint`` 만 쓴다.
- waypoint ``index`` 는 0부터 연속 증가.

**기체 enum 을 하드코딩하지 않는다** — 문서 스냅샷의 droneEnumValue 표(60=M300,
89=M350, 77=M3E/T/M, 91=M3D/TD)에 **M4D 시리즈 값이 없다.** 추측으로 박으면
Pilot 2 가 조용히 거부/오해석할 수 있으므로 :class:`DroneProfile` 로 호출자가
명시하고, 실값은 H4 실기 검증(실제 Pilot 2 export 샘플 unzip)으로 확정한다.

KMZ 에는 서명이 없다 — 안전 게이트(고도 봉투 등)는 상류 coverage.py 가 수행하고,
Manifold 측 정책 집행은 서명된 Mission Contract 가 소유한다(이원 산출물 원칙).
"""

from __future__ import annotations

import io
import json
import math
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from xml.etree import ElementTree as ET

from ksi_mission_planning.coverage import RouteWaypoint

KML_NS = "http://www.opengis.net/kml/2.2"
WPML_NS = "http://www.dji.com/wpmz/1.0.2"

# 문서 스냅샷에서 확인된 droneEnumValue 참고표 — **M4D 시리즈 값은 미확인**(H4).
KNOWN_DRONE_ENUM_VALUES = {
    60: "Matrice 300 RTK",
    89: "Matrice 350 RTK",
    67: "Matrice 30/30T",
    77: "Mavic 3E/3T/3M",
    91: "Matrice 3D/3TD",
}

# zip 멤버 타임스탬프 고정 — 같은 입력이면 바이트 동일(재현성·digest 안정).
_FIXED_ZIP_DATETIME = (2026, 1, 1, 0, 0, 0)


class KmzBuildError(ValueError):
    """KMZ 생성 불가 — 입력 위반의 typed 실패."""


@dataclass(frozen=True, slots=True)
class DroneProfile:
    """기체·페이로드 식별 — 값의 출처는 호출자가 소유한다(H4 실기 확정 전 추측 금지)."""

    drone_enum_value: int
    drone_sub_enum_value: int
    payload_enum_value: int
    payload_position_index: int = 0

    def __post_init__(self) -> None:
        for name in ("drone_enum_value", "drone_sub_enum_value", "payload_enum_value"):
            value = getattr(self, name)
            if value < 0:
                raise KmzBuildError(f"{name} 는 음수일 수 없다 ({value!r})")
        if self.payload_position_index not in (0, 1, 2):
            raise KmzBuildError(
                f"payload_position_index 는 0/1/2 여야 한다 ({self.payload_position_index!r})"
            )


@dataclass(frozen=True, slots=True)
class WaylineMissionConfig:
    """missionConfig 전역 파라미터 — 스펙 필수 필드만, 안전한 기본값."""

    auto_flight_speed_ms: float
    takeoff_security_height_m: float
    global_transitional_speed_ms: float
    fly_to_wayline_mode: str = "safely"
    finish_action: str = "goHome"
    exit_on_rc_lost: str = "executeLostAction"
    execute_rc_lost_action: str = "goBack"

    def __post_init__(self) -> None:
        if not (math.isfinite(self.auto_flight_speed_ms) and self.auto_flight_speed_ms > 0):
            raise KmzBuildError(
                f"auto_flight_speed_ms 는 양의 finite 여야 한다 ({self.auto_flight_speed_ms!r})"
            )
        # 스펙: takeOffSecurityHeight ∈ [1.2, 1500] (RC 운용 기준)
        if not (
            math.isfinite(self.takeoff_security_height_m)
            and 1.2 <= self.takeoff_security_height_m <= 1500.0
        ):
            raise KmzBuildError(
                f"takeoff_security_height_m 는 [1.2, 1500] 이어야 한다 "
                f"({self.takeoff_security_height_m!r})"
            )
        # 스펙: globalTransitionalSpeed ∈ (0, 15]
        if not (
            math.isfinite(self.global_transitional_speed_ms)
            and 0 < self.global_transitional_speed_ms <= 15.0
        ):
            raise KmzBuildError(
                f"global_transitional_speed_ms 는 (0, 15] 이어야 한다 "
                f"({self.global_transitional_speed_ms!r})"
            )
        if self.fly_to_wayline_mode not in ("safely", "pointToPoint"):
            raise KmzBuildError(f"fly_to_wayline_mode 미지원 값: {self.fly_to_wayline_mode!r}")
        if self.finish_action not in ("goHome", "noAction", "autoLand", "gotoFirstWaypoint"):
            raise KmzBuildError(f"finish_action 미지원 값: {self.finish_action!r}")
        if self.exit_on_rc_lost not in ("goContinue", "executeLostAction"):
            raise KmzBuildError(f"exit_on_rc_lost 미지원 값: {self.exit_on_rc_lost!r}")
        if self.execute_rc_lost_action not in ("goBack", "landing", "hover"):
            raise KmzBuildError(
                f"execute_rc_lost_action 미지원 값: {self.execute_rc_lost_action!r}"
            )


def _wpml(tag: str) -> str:
    return f"{{{WPML_NS}}}{tag}"


def _kml(tag: str) -> str:
    return f"{{{KML_NS}}}{tag}"


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    element = ET.SubElement(parent, tag)
    if text is not None:
        element.text = text
    return element


def _format_float(value: float) -> str:
    """소수 표현 고정 — repr 그대로(가역), 지수 표기 없이 스펙 파서와 호환."""
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _mission_config(parent: ET.Element, config: WaylineMissionConfig, drone: DroneProfile) -> None:
    mc = _sub(parent, _wpml("missionConfig"))
    _sub(mc, _wpml("flyToWaylineMode"), config.fly_to_wayline_mode)
    _sub(mc, _wpml("finishAction"), config.finish_action)
    _sub(mc, _wpml("exitOnRCLost"), config.exit_on_rc_lost)
    if config.exit_on_rc_lost == "executeLostAction":
        _sub(mc, _wpml("executeRCLostAction"), config.execute_rc_lost_action)
    _sub(mc, _wpml("takeOffSecurityHeight"), _format_float(config.takeoff_security_height_m))
    _sub(mc, _wpml("globalTransitionalSpeed"), _format_float(config.global_transitional_speed_ms))
    drone_info = _sub(mc, _wpml("droneInfo"))
    _sub(drone_info, _wpml("droneEnumValue"), str(drone.drone_enum_value))
    _sub(drone_info, _wpml("droneSubEnumValue"), str(drone.drone_sub_enum_value))
    payload_info = _sub(mc, _wpml("payloadInfo"))
    _sub(payload_info, _wpml("payloadEnumValue"), str(drone.payload_enum_value))
    _sub(payload_info, _wpml("payloadPositionIndex"), str(drone.payload_position_index))


def _document_root() -> tuple[ET.Element, ET.Element]:
    root = ET.Element(_kml("kml"))
    document = _sub(root, _kml("Document"))
    return root, document


def _serialize(root: ET.Element) -> bytes:
    ET.register_namespace("", KML_NS)
    ET.register_namespace("wpml", WPML_NS)
    buffer = io.BytesIO()
    ET.ElementTree(root).write(buffer, encoding="UTF-8", xml_declaration=True)
    return buffer.getvalue()


def _validate_route(route: list[RouteWaypoint]) -> float:
    """경로 검증 후 **균일 고도**를 반환한다.

    이 생성기의 높이 전략은 useGlobalHeight=1 + globalHeight 다(자율 재검토 F2):
    per-point 높이(useGlobalHeight=0)는 스펙상 ellipsoidHeight(WGS84 타원체고)가
    조건부 필수인데, 지오이드·지형 데이터 없이 이 층이 계산할 수 없는 값이다 —
    placeholder 를 넣는 대신 전역 높이 하나로 표현 가능한 경로(균일 고도)만 받고,
    비균일 고도는 typed 거부한다(현 생성기들은 모두 균일 고도를 낸다).
    """
    if len(route) < 2:
        raise KmzBuildError(f"웨이라인은 웨이포인트 2개 이상이어야 한다 (got {len(route)})")
    if len(route) > 65_536:
        raise KmzBuildError(
            f"웨이포인트 {len(route)}개 — WPML index 범위 [0, 65535] 를 넘는다"
        )
    for i, wp in enumerate(route):
        values = (wp.lat_deg, wp.lon_deg, wp.altitude_m)
        if not all(math.isfinite(v) for v in values):
            raise KmzBuildError(f"웨이포인트 {i} 에 비유한 값 ({values!r})")
        if not (-90.0 <= wp.lat_deg <= 90.0 and -180.0 <= wp.lon_deg <= 180.0):
            raise KmzBuildError(f"웨이포인트 {i} 위경도 범위 밖 ({wp.lat_deg}, {wp.lon_deg})")
    altitudes = {wp.altitude_m for wp in route}
    if len(altitudes) != 1:
        raise KmzBuildError(
            f"비균일 고도 {sorted(altitudes)!r} — 전역 높이 전략(useGlobalHeight=1)으로 "
            "표현할 수 없다(docstring 참조)"
        )
    return route[0].altitude_m


def build_template_kml(
    route: list[RouteWaypoint],
    *,
    drone: DroneProfile,
    config: WaylineMissionConfig,
    capture_at_waypoints: bool = False,
) -> bytes:
    """template.kml — 편집 가능한 waypoint 템플릿 (heightMode=relativeToStartPoint).

    스펙 필수 전역값(globalHeight·gimbalPitchMode·globalWaypointTurnMode·
    globalWaypointHeadingParam)을 모두 넣고, 웨이포인트는 전역값을 참조만 한다
    (useGlobal*=1) — 참조 대상 없는 useGlobal 플래그(자율 재검토 F2)를 만들지
    않는다. 요소 순서: 공식 샘플과 대조해 **실제로 확인한 것은
    waylineCoordinateSysParam → autoFlightSpeed 두 원소의 상대 순서뿐**이다(코드가
    그 순서를 지킨다). Folder 하위 나머지 요소들의 전체 순서가 공식 샘플과
    완전히 일치하는지는 미확인이다 — "전체 순서가 샘플과 같다"는 과잉 주장은
    하지 않는다(자율 재검토 D-4 정정. XSD 가 순서 무관 스키마일 가능성도 있어
    필수 여부 자체가 미확정 — H4 실기(Pilot 2 export 샘플 unzip)에서 확정).

    Args:
        capture_at_waypoints: True 면 :func:`build_waylines_wpml` 과 **동일한**
            촬영 actionGroup 을 각 Placemark 에 동봉한다(자율 재검토 D-3) — 한
            KMZ 의 template.kml·waylines.wpml 두 파일이 같은 임무를 기술하지
            않으면(예: waylines 만 촬영하고 template 은 안 하면) 편집기에서 연
            template.kml 이 실제 실행 내용과 어긋나 보인다.
    """
    altitude_m = _validate_route(route)
    root, document = _document_root()
    _mission_config(document, config, drone)

    folder = _sub(document, _kml("Folder"))
    _sub(folder, _wpml("templateType"), "waypoint")
    _sub(folder, _wpml("templateId"), "0")
    coord_param = _sub(folder, _wpml("waylineCoordinateSysParam"))
    _sub(coord_param, _wpml("coordinateMode"), "WGS84")
    _sub(coord_param, _wpml("heightMode"), "relativeToStartPoint")
    _sub(folder, _wpml("autoFlightSpeed"), _format_float(config.auto_flight_speed_ms))
    _sub(folder, _wpml("globalHeight"), _format_float(altitude_m))
    _sub(folder, _wpml("globalWaypointTurnMode"), "toPointAndStopWithDiscontinuityCurvature")
    # 스펙 조건부 필수는 Continuity 계열뿐이나, 공식 template 샘플(raw 확인)이
    # Discontinuity 모드에서도 0 을 동봉한다 — 샘플 정합 유지(H4 확정 항목).
    _sub(folder, _wpml("globalUseStraightLine"), "0")
    _sub(folder, _wpml("gimbalPitchMode"), "manual")
    heading = _sub(folder, _wpml("globalWaypointHeadingParam"))
    _sub(heading, _wpml("waypointHeadingMode"), "followWayline")
    # waypointHeadingPathMode 는 무조건 필수(공식 표 raw 확인 — 재검토 blocker #1).
    _sub(heading, _wpml("waypointHeadingPathMode"), "followBadArc")

    for index, wp in enumerate(route):
        placemark = _sub(folder, _kml("Placemark"))
        point = _sub(placemark, _kml("Point"))
        _sub(point, _kml("coordinates"), f"{_format_float(wp.lon_deg)},{_format_float(wp.lat_deg)}")
        _sub(placemark, _wpml("index"), str(index))
        _sub(placemark, _wpml("useGlobalHeight"), "1")
        _sub(placemark, _wpml("useGlobalSpeed"), "1")
        _sub(placemark, _wpml("useGlobalHeadingParam"), "1")
        _sub(placemark, _wpml("useGlobalTurnParam"), "1")
        if capture_at_waypoints:
            _append_capture_action_group(placemark, index=index, drone=drone)

    return _serialize(root)


def _append_capture_action_group(
    placemark: ET.Element, *, index: int, drone: DroneProfile
) -> None:
    """웨이포인트 도달 시 nadir 촬영 actionGroup (2026-07-29 대표자 승인 — 매핑 기본).

    파라미터 태그명·enum 값은 공식 40.common-element.md **raw 표에서 직접 확인**했다:
    gimbalHeadingYawBase 는 열거값이 north 하나뿐이고, gimbalRotateMode=absoluteAngle·
    payloadLensIndex(wide 등)도 표에 명시돼 있다(재검토 blocker #2 정정 — 이전
    "표가 값 목록을 싣지 않는다"는 근거는 요약 경유의 오류였다).
    """
    group = _sub(placemark, _wpml("actionGroup"))
    _sub(group, _wpml("actionGroupId"), str(index))
    _sub(group, _wpml("actionGroupStartIndex"), str(index))
    _sub(group, _wpml("actionGroupEndIndex"), str(index))
    _sub(group, _wpml("actionGroupMode"), "sequence")
    trigger = _sub(group, _wpml("actionTrigger"))
    _sub(trigger, _wpml("actionTriggerType"), "reachPoint")

    action_id = 0
    if index == 0:
        # 첫 웨이포인트에서 짐벌을 nadir(-90°)로 — 이후 웨이포인트는 유지된 자세로 촬영.
        gimbal = _sub(group, _wpml("action"))
        _sub(gimbal, _wpml("actionId"), str(action_id))
        _sub(gimbal, _wpml("actionActuatorFunc"), "gimbalRotate")
        param = _sub(gimbal, _wpml("actionActuatorFuncParam"))
        _sub(param, _wpml("payloadPositionIndex"), str(drone.payload_position_index))
        _sub(param, _wpml("gimbalHeadingYawBase"), "north")
        _sub(param, _wpml("gimbalRotateMode"), "absoluteAngle")
        _sub(param, _wpml("gimbalPitchRotateEnable"), "1")
        _sub(param, _wpml("gimbalPitchRotateAngle"), "-90")
        _sub(param, _wpml("gimbalRollRotateEnable"), "0")
        _sub(param, _wpml("gimbalRollRotateAngle"), "0")
        _sub(param, _wpml("gimbalYawRotateEnable"), "0")
        _sub(param, _wpml("gimbalYawRotateAngle"), "0")
        _sub(param, _wpml("gimbalRotateTimeEnable"), "0")
        _sub(param, _wpml("gimbalRotateTime"), "0")
        action_id += 1

    photo = _sub(group, _wpml("action"))
    _sub(photo, _wpml("actionId"), str(action_id))
    _sub(photo, _wpml("actionActuatorFunc"), "takePhoto")
    param = _sub(photo, _wpml("actionActuatorFuncParam"))
    _sub(param, _wpml("payloadPositionIndex"), str(drone.payload_position_index))
    _sub(param, _wpml("fileSuffix"), "ksi")
    _sub(param, _wpml("payloadLensIndex"), "wide")
    # "1"(전역값 사용)이면 참조 대상 전역 payloadParam 이 필요한데, 이 생성기는
    # 어느 파일에도 그런 전역을 내지 않는다 — F2 와 동일 클래스의 dangling 참조가
    # 된다. 지역 payloadLensIndex(위)가 실제 권위이므로 "0"으로 명시한다
    # (자율 재검토 D-1).
    _sub(param, _wpml("useGlobalPayloadLensIndex"), "0")


def build_waylines_wpml(
    route: list[RouteWaypoint],
    *,
    drone: DroneProfile,
    config: WaylineMissionConfig,
    capture_at_waypoints: bool = False,
) -> bytes:
    """waylines.wpml — 실행 확정 웨이라인 (executeHeightMode=relativeToStartPoint).

    요소 순서는 공식 샘플(templateId → executeHeightMode → waylineId →
    autoFlightSpeed)을 따르고, ``waypointTurnDampingDist`` 는 공식 샘플이 이 turn
    mode 에서도 넣으므로 0 으로 동봉한다(H4 실기에서 수용 확인). ``useStraightLine``
    은 넣지 않는다 — 스펙 조건부 필수 대상이 Continuity 계열 turn mode 뿐이고 공식
    샘플에도 없다(자율 재검토 정정).

    Args:
        capture_at_waypoints: True 면 각 웨이포인트 도달 시 nadir 촬영 actionGroup
            을 동봉한다(매핑 계열 기본 — 격자만 날고 사진 0장인 산출물 방지).
    """
    _validate_route(route)
    root, document = _document_root()
    _mission_config(document, config, drone)

    folder = _sub(document, _kml("Folder"))
    _sub(folder, _wpml("templateId"), "0")
    _sub(folder, _wpml("executeHeightMode"), "relativeToStartPoint")
    _sub(folder, _wpml("waylineId"), "0")
    _sub(folder, _wpml("autoFlightSpeed"), _format_float(config.auto_flight_speed_ms))

    for index, wp in enumerate(route):
        placemark = _sub(folder, _kml("Placemark"))
        point = _sub(placemark, _kml("Point"))
        _sub(point, _kml("coordinates"), f"{_format_float(wp.lon_deg)},{_format_float(wp.lat_deg)}")
        _sub(placemark, _wpml("index"), str(index))
        _sub(placemark, _wpml("executeHeight"), _format_float(wp.altitude_m))
        _sub(placemark, _wpml("waypointSpeed"), _format_float(config.auto_flight_speed_ms))
        heading = _sub(placemark, _wpml("waypointHeadingParam"))
        _sub(heading, _wpml("waypointHeadingMode"), "followWayline")
        _sub(heading, _wpml("waypointHeadingPathMode"), "followBadArc")
        turn = _sub(placemark, _wpml("waypointTurnParam"))
        _sub(turn, _wpml("waypointTurnMode"), "toPointAndStopWithDiscontinuityCurvature")
        # 공식 waylines 샘플(raw 확인)이 Discontinuity 모드에서도 0 을 동봉한다.
        _sub(turn, _wpml("waypointTurnDampingDist"), "0")
        if capture_at_waypoints:
            _append_capture_action_group(placemark, index=index, drone=drone)

    return _serialize(root)


def build_kmz(
    route: list[RouteWaypoint],
    *,
    drone: DroneProfile,
    config: WaylineMissionConfig,
    capture_at_waypoints: bool = False,
    pair_manifest: Mapping[str, str] | None = None,
) -> bytes:
    """template.kml + waylines.wpml 을 ``wpmz/`` 아래 담은 KMZ(zip) 바이트.

    Args:
        capture_at_waypoints: True 면 template.kml·waylines.wpml 양쪽 모두에
            동일한 촬영 actionGroup 을 동봉한다(자율 재검토 D-3 — 두 파일이 같은
            임무를 기술하게 한다).
        pair_manifest: 주어지면 ``wpmz/res/ksi-mission-pair.json`` 로 기록한다
            (``sort_keys``·``ensure_ascii=False``·컴팩트 separators) — 이 KMZ 와
            짝을 이루는 서명된 Mission Contract 식별 정보(이원 산출물 원칙,
            ADR-KSI-007) 등 호출자가 원하는 문자열 키/값을 그대로 담는다. **DJI
            Pilot 2 가 ``res/`` 의 잉여 파일(기존 빈 디렉터리 엔트리 외의 실제
            파일)을 수용하는지는 H4 실기 미확인**이다(기존 빈 res/ 동봉과 같은
            리스크 계열 — 불확실하면 이 인자를 생략하고 짝 식별은 KMZ 밖(계약
            응답 등)에서 전달하라).
    """
    template = build_template_kml(
        route, drone=drone, config=config, capture_at_waypoints=capture_at_waypoints
    )
    waylines = build_waylines_wpml(
        route, drone=drone, config=config, capture_at_waypoints=capture_at_waypoints
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in (("wpmz/template.kml", template), ("wpmz/waylines.wpml", waylines)):
            info = zipfile.ZipInfo(name, date_time=_FIXED_ZIP_DATETIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
        # res/ 는 공식 overview 가 "route file format standard 의 일부"로 명시하는
        # 폴더다 — 참조 이미지를 안 쓰더라도 빈 디렉터리 엔트리를 동봉한다(부재가
        # 임포트 거부 사유가 될 가능성에 대한 보험, H4 에서 확정).
        res_dir = zipfile.ZipInfo("wpmz/res/", date_time=_FIXED_ZIP_DATETIME)
        archive.writestr(res_dir, b"")
        if pair_manifest is not None:
            manifest_payload = json.dumps(
                dict(pair_manifest),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            manifest_info = zipfile.ZipInfo(
                "wpmz/res/ksi-mission-pair.json", date_time=_FIXED_ZIP_DATETIME
            )
            manifest_info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(manifest_info, manifest_payload)
    return buffer.getvalue()
