"""매핑 커버리지 주장의 속성 테스트 — "사진은 적은데 커버는 높다"를 무작위로 찾는다.

이 결함 클래스는 **세 번 연속으로 '닫았다'→'뚫렸다'** 를 반복했다:

1. `captureIntervalM` 만 막았더니 `spacingM` 축으로 우회됐다.
2. `spacingM ≤ 고도×3.46`(물리 상한)으로 막았더니 **고도 축**으로 우회됐다 —
   고도 87m·spacing 300 이면 2ha 구역이 사진 2장·coverageRatio 1.0 으로 발급됐다.
3. 상한을 운용 기준(고도×1.5)으로 바꿔 지금은 막힌다.

세 번 다 "특정 입력 하나를 막는 회귀 테스트"는 통과했는데 **다른 축이 열려 있었다.**
그래서 예시 기반이 아니라 **속성**으로 고정한다: 어떤 조합이든 발급된 lawnmower
경로가 높은 커버(≥0.95)를 주장하면, 사진 1장이 감당하는 면적이 그 고도에서
그럴듯한 촬영 면적을 넘지 않아야 한다.

판정 기준을 정하는 것이 이 테스트의 전부다. 두 번 틀렸다:

1. 처음엔 구현 상수(``_MAX_SPACING_PER_ALTITUDE``)를 import 했다 — 상한을 느슨하게
   바꾸면 기준도 같이 느슨해져, 과거에 뚫렸던 값(3.46)으로 되돌려도 통과했다.
2. 그래서 같은 숫자(1.5)를 독립 상수로 복제했는데, **그건 구조적으로 실패할 수
   없는 기준이었다.** 증명: 어느 분기에서든 ``면적 ≤ spacing × span`` 이고
   ``사진수 > span / capture`` 이므로 ``장당 면적 < spacing × capture``, 그리고
   구현이 ``spacing ≤ 1.5·고도``·``capture ≤ spacing`` 을 강제하므로 항상
   ``장당 면적 < (1.5·고도)²`` 다. 임계값이 도달 불가능한 상한이었다.

지금 기준은 **참고 구현의 사진측량 산식**에서 온다(``references/repos/ksi-terra``
``flightplan/gsd.py``·``grid.py``, 읽기 전용 참고). 그 모델에서 촬영폭은
고도×1.5(중복도 0 기준)이고, 표준 매핑(전방 0.8/측면 0.7)은 장당 약
``0.09 × 고도²`` 를 덮는다. 여기서는 그보다 훨씬 관대한
``_MAX_AREA_PER_PHOTO_PER_ALT2`` 를 쓴다 — 표준의 몇 배까지는 허용하되 "어떤
매핑 구성으로도 설명 안 되는" 밀도만 잡는다.

시드는 고정이다 — 실패가 재현되지 않으면 디버깅할 수 없다.
"""

from __future__ import annotations

import math
import random

import pytest
from ksi_geo_core.frames import WGS84_EQUATORIAL_RADIUS_M
from ksi_mission_contracts.models import FlightEnvelope
from ksi_mission_planning import (
    AreaOfInterest,
    CameraSpec,
    GeoPoint,
    RouteGenerationError,
    compute_grid_spacing,
    lawnmower_route,
)
from pydantic import ValidationError

_LAT0, _LON0 = 37.5000, 127.0000
_M_PER_DEG_LAT = math.radians(1.0) * WGS84_EQUATORIAL_RADIUS_M
_ENVELOPE = FlightEnvelope(
    allowed_volumes=["vol-1"],
    excluded_volumes=[],
    min_altitude_m=0.0,
    max_altitude_m=150.0,
)

# 사진 1장이 덮어도 되는 면적 / 고도². 참고 구현의 표준 매핑은 0.09 이고, 여기서는
# 그 **3배**까지 허용한다(전방·측면 중복도를 대폭 낮춘 느슨한 구성까지 포용).
# 이보다 성기면 어떤 중복도 조합으로도 설명되지 않는다.
#
# 구현 상수에서 유도하지 않는다 — 유도하면 상한을 올릴 때 기준도 같이 올라가
# 게이트가 자기를 채점한다(실제로 두 번 그렇게 틀렸다, 위 docstring 참조).
_MAX_AREA_PER_PHOTO_PER_ALT2 = 0.27


def _plausible_photo_area_m2(altitude_m: float) -> float:
    return _MAX_AREA_PER_PHOTO_PER_ALT2 * altitude_m**2


def _pt(east_m: float, north_m: float) -> GeoPoint:
    return GeoPoint(
        lat_deg=_LAT0 + north_m / _M_PER_DEG_LAT,
        lon_deg=_LON0 + east_m / (_M_PER_DEG_LAT * math.cos(math.radians(_LAT0))),
    )


def _vertices(kind: str, width: float, height: float) -> list[GeoPoint]:
    if kind == "rect":
        return [_pt(0, 0), _pt(width, 0), _pt(width, height), _pt(0, height)]
    if kind == "triangle":
        return [_pt(0, 0), _pt(width, 0), _pt(width / 2, height)]
    if kind == "trapezoid":
        return [_pt(0, 0), _pt(width, 0), _pt(width * 0.7, height), _pt(width * 0.3, height)]
    if kind == "parallelogram":
        return [
            _pt(0, 0),
            _pt(width, 0),
            _pt(width + height * 0.8, height),
            _pt(height * 0.8, height),
        ]
    raise AssertionError(kind)


_SHAPES = ("rect", "triangle", "trapezoid", "parallelogram")
_WIDTHS = (20.0, 50.0, 100.0, 200.0, 400.0, 800.0, 2000.0)
_HEIGHTS = (5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0)
_ALTITUDES = (5.0, 10.0, 20.0, 40.0, 60.0, 87.0, 100.0, 150.0)
# 상한 경계(고도 150 → 225)를 정확히·아슬아슬하게 포함한다.
_SPACINGS = (0.5, 1.0, 5.0, 10.0, 20.0, 50.0, 60.0, 90.0, 150.0, 224.9, 225.0, 300.0)
_SWEEPS = (None, 0.0, 30.0, 45.0, 90.0, 137.0)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "알려진 미해소 결함 — 원장 risk `coverage-ratio-not-photogrammetric`. "
        "실측: 2000×200m(40ha) AOI 를 고도 150·spacing 225·interval 225 로 요청하면 "
        "웨이포인트 10개(장당 4ha)에 coverageRatio 1.0 으로 발급된다. 상한을 네 번 "
        "고쳐봤지만 카메라 촬영폭을 모르는 한 요청이 자기 커버리지 증명서를 쓰는 "
        "구조는 닫히지 않는다. 실제 폐쇄(CameraSpec 도입)는 ADR-KSI-011 D3 로 "
        "반영됐고 **카메라 경로에서는 닫혔다** — 그 증거가 아래 "
        "test_camera_derived_route_never_underphotographs 다. 이 xfail 이 고정하는 "
        "것은 **간격 직접 지정 경로가 여전히 열려 있다**는 사실이다(카메라 미확정 "
        "환경용으로 남겨둔 경로). "
        "strict=True — 그 결정이 반영돼 이 테스트가 통과하기 시작하면 여기서 실패해 "
        "마커 제거를 강제한다."
    ),
)
@pytest.mark.parametrize("seed", [20260805, 7, 99])
def test_issued_mapping_route_never_claims_coverage_it_cannot_photograph(seed: int) -> None:
    """[핵심 속성] 발급된 매핑 경로는 촬영할 수 없는 커버를 주장하지 않는다."""
    rng = random.Random(seed)
    issued = 0
    violations: list[str] = []

    for _ in range(4000):
        kind = rng.choice(_SHAPES)
        width, height = rng.choice(_WIDTHS), rng.choice(_HEIGHTS)
        altitude = rng.choice(_ALTITUDES)
        spacing = rng.choice(_SPACINGS)
        interval = rng.choice((0.5, 1.0, 5.0, 10.0, 20.0, 50.0, spacing, spacing * 0.99))
        sweep = rng.choice(_SWEEPS)
        try:
            aoi = AreaOfInterest(vertices=_vertices(kind, width, height))
            result = lawnmower_route(
                aoi,
                spacing_m=spacing,
                altitude_m=altitude,
                envelope=_ENVELOPE,
                sweep_direction_deg=sweep,
                capture_interval_m=interval,
            )
        except (RouteGenerationError, ValidationError):
            continue  # 거부는 이 속성의 관심사가 아니다 — 발급된 것만 본다
        issued += 1

        if result.coverage_ratio < 0.95:
            continue
        per_photo = aoi.area_m2() / len(result.waypoints)
        if per_photo > _plausible_photo_area_m2(altitude):
            violations.append(
                f"{kind} {width}x{height}m alt={altitude} spacing={spacing} "
                f"interval={interval} sweep={sweep} → 웨이포인트 {len(result.waypoints)}개, "
                f"coverage={result.coverage_ratio:.4f}, 장당 {per_photo:.0f}m² "
                f"(그럴듯한 상한 {_plausible_photo_area_m2(altitude):.0f}m²)"
            )

    # 공허 방지 — 실제로 상당수가 발급돼야 위 검사에 의미가 있다.
    assert issued >= 500, f"발급된 조합이 너무 적다({issued}) — 속성 테스트가 공허하다"
    assert not violations, (
        "촬영할 수 없는 커버를 주장하는 조합이 발급된다 — 이 결함은 세 번 재발했다. "
        "상한을 바꿨다면 그 근거를 ADR-KSI-011 에 적어라:\n" + "\n".join(violations[:5])
    )


# ── 카메라 경로 (ADR-KSI-011 D3) — 이쪽은 xfail 이 아니다 ────────────────────
#
# 위 속성이 직접 지정 경로에서 여전히 깨진다는 것과, 카메라 경로에서는 **닫힌다**는
# 것은 별개의 사실이다. 후자를 증거 없이 주장하지 않기 위해 같은 속성을 카메라
# 입력으로 한 번 더 돈다(독립 재검토 지적).

_CAMERA = CameraSpec(
    sensor_width_mm=13.2, focal_length_mm=8.8, image_width_px=5472, image_height_px=3648
)
_OVERLAPS = ((0.6, 0.5), (0.65, 0.55), (0.8, 0.7), (0.9, 0.8), (0.85, 0.6))


@pytest.mark.parametrize("seed", [20260805, 7, 99])
def test_camera_derived_route_never_underphotographs(seed: int) -> None:
    """[핵심 속성] 카메라로 계산한 경로는 사진이 부족한 채 커버를 주장하지 않는다.

    판정 기준을 **실제 촬영면적**으로 둔다 — 사진 1장이 담당하는 면적이 그 사진이
    실제로 덮는 면적을 넘으면 겹침이 음수라는 뜻이고, 그건 어떤 재구성도 성립하지
    않는다. 이 기준은 카메라에서 나오므로 구현 상한과 독립이다.
    """
    rng = random.Random(seed)
    issued = 0
    violations: list[str] = []

    for _ in range(2000):
        kind = rng.choice(_SHAPES)
        width, height = rng.choice(_WIDTHS), rng.choice(_HEIGHTS)
        altitude = rng.choice(_ALTITUDES)
        front, side = rng.choice(_OVERLAPS)
        sweep = rng.choice(_SWEEPS)
        grid = compute_grid_spacing(
            _CAMERA, altitude_m=altitude, front_overlap=front, side_overlap=side
        )
        try:
            aoi = AreaOfInterest(vertices=_vertices(kind, width, height))
            result = lawnmower_route(
                aoi,
                spacing_m=grid.spacing_m,
                altitude_m=altitude,
                envelope=_ENVELOPE,
                sweep_direction_deg=sweep,
                capture_interval_m=grid.capture_interval_m,
                spacing_is_camera_derived=True,
            )
        except (RouteGenerationError, ValidationError):
            continue
        issued += 1
        if result.coverage_ratio < 0.95:
            continue
        per_photo = aoi.area_m2() / len(result.waypoints)
        photo_area = grid.footprint_across_m * grid.footprint_along_m
        if per_photo > photo_area:
            violations.append(
                f"{kind} {width}x{height}m alt={altitude} 겹침 {front}/{side} → "
                f"웨이포인트 {len(result.waypoints)}개, 장당 {per_photo:.0f}m² > "
                f"촬영면적 {photo_area:.0f}m²"
            )

    assert issued >= 300, f"발급된 조합이 너무 적다({issued}) — 속성 테스트가 공허하다"
    assert not violations, "카메라 경로가 사진보다 넓은 면적을 담당한다:\n" + "\n".join(
        violations[:5]
    )
