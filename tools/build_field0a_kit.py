"""FIELD-0a 킷 재생성 — 기존 킷의 경로·설정은 그대로, 기종·페이로드 값만 바꾼다.

B 파일(직전 제품값 99/0/65534)에서 경로·속도·고도를 읽어 A 파일(현행 제품값
100/0/98)을 만든다. 촬영 액션 포함, 나머지 내용은 두 파일이 완전히 같다.
zip 타임스탬프가 고정돼 있어(같은 입력 → 같은 바이트) 재현 가능하다.

실행: uv run python tools/build_field0a_kit.py
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from ksi_mission_planning.coverage import RouteWaypoint
from ksi_mission_planning.wpml import DroneProfile, WaylineMissionConfig, build_kmz

KIT_DIR = Path(__file__).resolve().parent.parent / "docs" / "hil" / "field0a-kit"
SOURCE = KIT_DIR / "KSI-FIELD0A-B-droneEnum-99-payload-65534.kmz"
TARGET = KIT_DIR / "KSI-FIELD0A-A-droneEnum-100-payload-98.kmz"

WPML = "{http://www.dji.com/wpmz/1.0.2}"
KML = "{http://www.opengis.net/kml/2.2}"

# 현행 제품값 — 정본: DJI Cloud API Product Support 표(2026-08-18 확인).
M4D = DroneProfile(drone_enum_value=100, drone_sub_enum_value=0, payload_enum_value=98)


def _text(root: ET.Element, path: str) -> str:
    node = root.find(path)
    if node is None or node.text is None:
        raise SystemExit(f"원본 킷에서 {path} 를 찾지 못했다")
    return node.text


def main() -> None:
    with zipfile.ZipFile(SOURCE) as archive:
        waylines = ET.fromstring(archive.read("wpmz/waylines.wpml"))

    route: list[RouteWaypoint] = []
    for placemark in waylines.iter(f"{KML}Placemark"):
        lon, lat = _text(placemark, f"{KML}Point/{KML}coordinates").split(",")
        height = _text(placemark, f"{WPML}executeHeight")
        route.append(
            RouteWaypoint(lat_deg=float(lat), lon_deg=float(lon), altitude_m=float(height))
        )

    config = WaylineMissionConfig(
        auto_flight_speed_ms=float(_text(waylines, f".//{WPML}autoFlightSpeed")),
        takeoff_security_height_m=float(_text(waylines, f".//{WPML}takeOffSecurityHeight")),
        global_transitional_speed_ms=float(_text(waylines, f".//{WPML}globalTransitionalSpeed")),
    )

    TARGET.write_bytes(build_kmz(route, drone=M4D, config=config, capture_at_waypoints=True))
    print(f"생성: {TARGET.name} (웨이포인트 {len(route)}개)")


if __name__ == "__main__":
    main()
