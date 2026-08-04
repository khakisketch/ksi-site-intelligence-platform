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

판정 기준은 구현 상수와 **독립적인 값**이다. 처음엔 구현의
``_MAX_SPACING_PER_ALTITUDE`` 를 그대로 썼는데, 그러면 **상한을 느슨하게 바꾸는
순간 판정 기준도 같이 느슨해져** 과거에 뚫렸던 값(3.46)으로 되돌려도 이 테스트가
통과했다(변이 실험으로 확인). 게이트가 자기 자신을 채점하면 안 된다.

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
    GeoPoint,
    RouteGenerationError,
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

# 사진 1장이 덮을 수 있다고 볼 면적의 상한 — 폭이 고도×1.5 인 정사각 footprint.
# **구현 상수를 import 하지 않는다**(위 docstring 참조): 여기서 독립적으로 정의해야
# 구현 상한이 느슨해질 때 이 테스트가 그것을 잡는다. 값을 바꾸려면 ADR-KSI-011 의
# 근거부터 바꿔야 한다.
_PLAUSIBLE_PHOTO_WIDTH_PER_ALTITUDE = 1.5


def _plausible_photo_area_m2(altitude_m: float) -> float:
    return (_PLAUSIBLE_PHOTO_WIDTH_PER_ALTITUDE * altitude_m) ** 2


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
