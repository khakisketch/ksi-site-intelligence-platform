"""우리 KMZ 와 **DJI 공식 샘플**의 차이를 게이트로 고정한다.

## 왜 이 파일이 있나

이 저장소가 만드는 웨이라인 파일을 실기가 읽어본 적이 0회다. "이 요소는 없어도
된다"는 판단은 전부 문서 해석이었고, 문서가 침묵하는 지점에서는 동전 던지기였다.
2026-08-15 에 핀된 PSDK 안의 공식 샘플을 처음 풀어 대조했더니 우리가 안 내던
요소가 여러 개 나왔다(risk ``kmz-format-never-diffed-against-dji-sample``).

그 대조는 **한 번 하고 끝나면 의미가 없다.** 생성기를 고칠 때마다 다시 벌어지기
때문이다. 그래서 대조 자체를 테스트로 만든다: 남은 차이는 아래 목록이 전부여야
하고, 새 차이가 생기면 실패한다.

공식 샘플은 이 저장소가 가진 **유일한 "DJI 가 실제로 만든 웨이라인 파일"** 이다.
정답표는 아니지만, 어떤 요소가 있어도 되는지에 대해서는 이보다 나은 근거가 없다.

## 이 게이트가 증명하지 않는 것

샘플과 같다고 해서 M4D Pilot 2 가 받는다는 뜻이 아니다. 샘플은 다른 기종·다른
WPML 버전(1.0.3)에서 나온 파일이다. 실기 수용은 FIELD-0a 만이 답한다 —
``docs/hil/FIELD_0A_CHECKLIST.md``.
"""

from __future__ import annotations

import io
import zipfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from ksi_mission_planning.coverage import RouteWaypoint
from ksi_mission_planning.wpml import DroneProfile, WaylineMissionConfig, build_kmz

_ROOT = Path(__file__).resolve().parents[2]
_OFFICIAL_SAMPLE = (
    _ROOT
    / "edge/third_party/psdk/samples/sample_c/module_sample/waypoint_v3"
    / "waypoint_file/waypoint_v3_test_file.kmz"
)
_MEMBERS = ("wpmz/template.kml", "wpmz/waylines.wpml")

# 샘플에는 있는데 우리는 안 내는 요소 — **왜 안 내는지**가 값이다.
_ABSENT_FROM_OURS: dict[str, str] = {
    "actionGroup/actionTrigger/actionTriggerParam": (
        "샘플의 다른 트리거 종류(시간·거리 간격)에만 딸린 파라미터다. 우리 트리거는 "
        "reachPoint 하나뿐이고 거기엔 파라미터가 없다"
    ),
    "actionGroup/action/actionActuatorFuncParam/focalLength": (
        "줌 액션 전용 — 매핑은 줌을 쓰지 않는다"
    ),
    "actionGroup/action/actionActuatorFuncParam/isUseFocalFactor": "같은 줌 액션 전용",
    "actionGroup/action/actionActuatorFuncParam/focusX": (
        "포커스 액션 전용 — 우리는 초점을 조작하지 않는다"
    ),
    "actionGroup/action/actionActuatorFuncParam/focusY": "포커스 액션 전용",
    "actionGroup/action/actionActuatorFuncParam/focusRegionWidth": "포커스 액션 전용",
    "actionGroup/action/actionActuatorFuncParam/focusRegionHeight": "포커스 액션 전용",
    "actionGroup/action/actionActuatorFuncParam/isPointFocus": "포커스 액션 전용",
    "actionGroup/action/actionActuatorFuncParam/isInfiniteFocus": "포커스 액션 전용",
}

# 우리만 내는 요소 — **왜 내는지**가 값이다.
_ABSENT_FROM_SAMPLE: dict[str, str] = {
    "waypointHeadingPathMode": (
        "공식 표는 무조건 필수라 하는데 샘플에는 없다. 증거가 서로 어긋나는 유일한 "
        "항목이라 '표가 필수라 한 쪽'을 남긴다 — FIELD-0a 임포트가 가른다"
    ),
    "actionGroup/action/actionActuatorFuncParam/payloadLensIndex": (
        "샘플은 렌즈를 아예 지정하지 않는다. M4D 는 렌즈가 여럿이라 지정 없이는 "
        "어느 렌즈로 찍을지가 기체 기본값에 맡겨진다"
    ),
    "actionGroup/action/actionActuatorFuncParam/gimbalHeadingYawBase": (
        "짐벌을 nadir 로 돌리는 액션의 파라미터다. 샘플의 액션 구성이 우리와 달라 "
        "비교 대상이 없고, 공식 표에는 있다"
    ),
}


def _element_paths(payload: bytes) -> Counter[str]:
    root = ET.fromstring(payload)
    found: Counter[str] = Counter()

    def walk(element: ET.Element, prefix: str) -> None:
        path = f"{prefix}/{element.tag.split('}')[-1]}"
        found[path] += 1
        for child in element:
            walk(child, path)

    walk(root, "")
    return found


def _child_tags(payload: bytes, path: str) -> list[str]:
    """``path`` 가 가리키는 **첫** 요소의 자식 태그 순서."""
    root = ET.fromstring(payload)
    steps = path.split("/")[1:]
    assert steps[0] == root.tag.split("}")[-1], f"{path} 의 최상위가 문서 루트와 다르다"
    node: ET.Element | None = root
    for step in steps[1:]:
        assert node is not None
        node = next((c for c in node if c.tag.split("}")[-1] == step), None)
    assert node is not None, f"{path} 를 찾지 못했다"
    return [child.tag.split("}")[-1] for child in node]


def _ours() -> dict[str, bytes]:
    route = [
        RouteWaypoint(lat_deg=37.5 + index * 0.0002, lon_deg=127.0, altitude_m=40.0)
        for index in range(4)
    ]
    kmz = build_kmz(
        route,
        drone=DroneProfile(drone_enum_value=100, drone_sub_enum_value=0, payload_enum_value=98),
        config=WaylineMissionConfig(
            auto_flight_speed_ms=5.0,
            takeoff_security_height_m=20.0,
            global_transitional_speed_ms=10.0,
        ),
        capture_at_waypoints=True,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with zipfile.ZipFile(io.BytesIO(kmz)) as archive:
        return {name: archive.read(name) for name in _MEMBERS}


def _sample() -> dict[str, bytes]:
    with zipfile.ZipFile(_OFFICIAL_SAMPLE) as archive:
        return {name: archive.read(name) for name in _MEMBERS}


def _matches(path: str, suffixes: dict[str, str]) -> bool:
    return any(path.endswith(f"/{suffix}") for suffix in suffixes)


@pytest.mark.parametrize("member", _MEMBERS)
def test_every_element_the_official_sample_writes_is_either_written_or_explained(
    member: str,
) -> None:
    """샘플에 있는데 우리가 안 내는 요소는 **이유가 적힌 것만** 허용된다."""
    sample = _element_paths(_sample()[member])
    ours = _element_paths(_ours()[member])

    unexplained = sorted(
        path for path in sample if path not in ours and not _matches(path, _ABSENT_FROM_OURS)
    )
    assert unexplained == [], (
        f"{member}: 공식 샘플이 쓰는데 우리는 안 쓰고, 왜 안 쓰는지도 안 적힌 요소다.\n"
        f"{chr(10).join(unexplained)}\n"
        "생성기에 넣거나, 넣지 않을 근거를 _ABSENT_FROM_OURS 에 적어라. "
        "목록에 한 줄 추가하는 것이 아니라 **근거**를 적는 것이 이 게이트의 요구다."
    )


@pytest.mark.parametrize("member", _MEMBERS)
def test_every_element_we_add_beyond_the_sample_is_explained(member: str) -> None:
    """우리만 내는 요소도 이유가 있어야 한다 — 샘플에 없는 것을 넣는 쪽이 더 위험하다."""
    sample = _element_paths(_sample()[member])
    ours = _element_paths(_ours()[member])

    unexplained = sorted(
        path for path in ours if path not in sample and not _matches(path, _ABSENT_FROM_SAMPLE)
    )
    assert unexplained == [], (
        f"{member}: 공식 샘플에 없는 요소를 우리가 낸다. 근거가 없으면 빼라.\n"
        f"{chr(10).join(unexplained)}"
    )


@pytest.mark.parametrize("member", _MEMBERS)
@pytest.mark.parametrize("container", ["/kml/Document/Folder", "/kml/Document/Folder/Placemark"])
def test_shared_elements_keep_the_official_sample_order(member: str, container: str) -> None:
    """양쪽에 다 있는 요소들의 **상대 순서**가 샘플과 같다.

    순서가 유효성에 영향을 주는지는 미확인이다(XSD 를 못 봤다). 영향을 준다면
    알려진 수용 사례의 순서가 정답이고, 영향을 안 준다면 이 테스트는 무해하다.
    """
    sample_tags = _child_tags(_sample()[member], container)
    our_tags = _child_tags(_ours()[member], container)
    shared = set(sample_tags) & set(our_tags)

    def order(tags: list[str]) -> list[str]:
        # 웨이포인트 수가 서로 다르므로 반복되는 태그(Placemark)는 **첫 등장**만 센다.
        seen: list[str] = []
        for tag in tags:
            if tag in shared and tag not in seen:
                seen.append(tag)
        return seen

    assert order(our_tags) == order(sample_tags), (
        f"{member} {container}: 공유 요소 순서가 공식 샘플과 다르다"
    )


def test_the_reasons_are_actually_written() -> None:
    """빈 문자열로 게이트를 통과시키는 우회를 막는다."""
    for path, reason in (*_ABSENT_FROM_OURS.items(), *_ABSENT_FROM_SAMPLE.items()):
        assert reason.strip(), f"{path} 의 근거가 비어 있다"


def test_the_pinned_official_sample_is_actually_there() -> None:
    """샘플이 사라지면 위 게이트들이 조용히 통과할 수 있다 — 그것부터 막는다."""
    assert _OFFICIAL_SAMPLE.is_file(), f"공식 샘플이 없다: {_OFFICIAL_SAMPLE}"
    with zipfile.ZipFile(_OFFICIAL_SAMPLE) as archive:
        assert set(_MEMBERS) <= set(archive.namelist())
