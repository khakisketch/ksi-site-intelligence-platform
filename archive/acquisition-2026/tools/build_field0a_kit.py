"""FIELD-0a 킷 재생성 — 경로·속도·고도는 그대로, 물어볼 변수만 바꾼 파일 3개.

이 킷의 목적은 "우리 비행파일을 실기가 받는가"를 **한 번의 현장 세션으로** 알아
내는 것이다. 임포트가 거부됐을 때 무엇을 바꿔야 하는지 모르면 세션을 다시 잡아야
하고, 그건 사람과 기체를 다시 모으는 일이다. 그래서 셋을 함께 만든다.

| 파일 | 바꾼 것 | 답하는 질문 |
|---|---|---|
| A | 기종 100 / 페이로드 98, WPML 1.0.2 | 현행 제품값 그대로 받는가 |
| B | 기종 99 / 페이로드 65534, WPML 1.0.2 | 거부가 기종값 때문인가 |
| C | A 와 같고 WPML 1.0.3 | 거부가 네임스페이스 버전 때문인가 |

셋 다 경로 80 웨이포인트·고도 40m·촬영 액션 포함으로 완전히 같다.

**C 만 후처리한다.** 생성기의 제품 기본값은 Cloud API WPML 문서가 말하는 1.0.2 고,
공식 샘플(핀된 PSDK)은 1.0.3 이다. 어느 쪽이 M4D Pilot 2 의 기준인지는 아직
모른다 — 그래서 제품 코드를 바꾸는 대신 이 도구가 바이트 수준에서 네임스페이스만
갈아 끼운 시험용 변형을 하나 더 낸다.

zip 타임스탬프가 고정돼 있어 같은 입력이면 같은 바이트다.

실행: uv run python tools/build_field0a_kit.py
"""

from __future__ import annotations

import hashlib
import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from ksi_mission_planning.coverage import RouteWaypoint
from ksi_mission_planning.wpml import (
    WPML_NS,
    DroneProfile,
    WaylineMissionConfig,
    build_kmz,
)

KIT_DIR = Path(__file__).resolve().parents[3] / "docs" / "hil" / "field0a-kit"
SOURCE = KIT_DIR / "KSI-FIELD0A-B-droneEnum-99-payload-65534.kmz"
CHECKSUM_MANIFEST = KIT_DIR / "SHA256SUMS"

WPML = "{http://www.dji.com/wpmz/1.0.2}"
KML = "{http://www.opengis.net/kml/2.2}"

# 현행 제품값 — 정본: DJI Cloud API Product Support 표(2026-08-18 확인).
M4D = DroneProfile(drone_enum_value=100, drone_sub_enum_value=0, payload_enum_value=98)
# 직전 제품값 — 2026-08-18 이전에 발급된 KMZ 와 같은 값이다.
PREVIOUS = DroneProfile(drone_enum_value=99, drone_sub_enum_value=0, payload_enum_value=65534)

# 킷 파일의 createTime — 고정값이라 재생성해도 바이트가 같다. 이 파일은 현장
# 시험용이지 실제 임무가 아니므로 발급 시각이라는 의미를 담지 않는다.
KIT_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)

SAMPLE_NAMESPACE = "http://www.dji.com/wpmz/1.0.3"

# File names are an operator-facing FIELD-0a contract.  Keep this one tuple as
# the authority for both the generated files and SHA-256 manifest so a newly
# added trial variant cannot silently be omitted from the handoff kit.
KIT_FILE_NAMES = (
    "KSI-FIELD0A-A-droneEnum-100-payload-98.kmz",
    "KSI-FIELD0A-B-droneEnum-99-payload-65534.kmz",
    "KSI-FIELD0A-C-droneEnum-100-wpml-1.0.3.kmz",
)


def _text(root: ET.Element, path: str) -> str:
    node = root.find(path)
    if node is None or node.text is None:
        raise SystemExit(f"원본 킷에서 {path} 를 찾지 못했다")
    return node.text


def _read_source() -> tuple[list[RouteWaypoint], WaylineMissionConfig]:
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
    return route, config


def _rewrite_namespace(kmz: bytes, namespace: str) -> bytes:
    """KMZ 안 두 XML 의 wpml 네임스페이스 URI 만 바꾼다.

    제품 생성기를 건드리지 않는 이유는 이게 **가설 하나를 시험하는 변형**이기
    때문이다. 어느 버전이 맞는지 실기가 알려주면 그때 생성기를 고친다.
    """
    source = io.BytesIO(kmz)
    target = io.BytesIO()
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(
        target, "w", compression=zipfile.ZIP_DEFLATED
    ) as rewritten:
        for item in original.infolist():
            payload = original.read(item.filename)
            if item.filename.endswith((".kml", ".wpml")):
                payload = payload.replace(WPML_NS.encode(), namespace.encode())
            copied = zipfile.ZipInfo(item.filename, date_time=item.date_time)
            copied.compress_type = item.compress_type
            rewritten.writestr(copied, payload)
    return target.getvalue()


def build_variants() -> dict[str, bytes]:
    """Build every FIELD-0a trial file without mutating the worktree.

    Tests call this twice to keep the actual trial artifacts byte-stable.  The
    only input timestamp is :data:`KIT_CREATED_AT`; wall-clock time must never
    leak into a field kit because the SHA-256 handoff record would then change
    for an identical trial.
    """
    route, config = _read_source()

    def variant(drone: DroneProfile) -> bytes:
        return build_kmz(
            route,
            drone=drone,
            config=config,
            capture_at_waypoints=True,
            created_at=KIT_CREATED_AT,
        )

    variant_a = variant(M4D)
    variant_b = variant(PREVIOUS)
    variant_c = _rewrite_namespace(variant_a, SAMPLE_NAMESPACE)
    return dict(
        zip(
            KIT_FILE_NAMES,
            (variant_a, variant_b, variant_c),
            strict=True,
        )
    )


def checksum_manifest(variants: dict[str, bytes]) -> str:
    """Return the portable ``sha256sum``-style manifest for the kit."""
    if set(variants) != set(KIT_FILE_NAMES):
        raise ValueError("FIELD-0a 변형 파일 집합이 고정 목록과 다르다")
    return "".join(
        f"{hashlib.sha256(variants[name]).hexdigest()}  {name}\n" for name in KIT_FILE_NAMES
    )


def main() -> None:
    variants = build_variants()

    for name, payload in variants.items():
        (KIT_DIR / name).write_bytes(payload)
        print(f"생성: {name} ({len(payload)} bytes, sha256={hashlib.sha256(payload).hexdigest()})")
    CHECKSUM_MANIFEST.write_text(checksum_manifest(variants), encoding="utf-8")
    print(f"체크섬 기록: {CHECKSUM_MANIFEST.name}")


if __name__ == "__main__":
    main()
