"""매핑 커버리지 주장의 속성 테스트.

직접 ``spacingM`` 입력은 카메라 footprint·초점거리·해상도·중복도 근거가 없어서,
기하 생성기가 계산하는 스와스 비율을 사진측량 coverage claim으로 승격할 수 없다.
Core 발급 경로는 CameraSpec에서 서버가 계산한 격자에만 ``plannedCoverageRatio``를
붙인다. 수동 간격은 기존 복구/진단 호환 경로로 남되 그 값은 항상 ``null``이다.

CameraSpec 경로에서는 독립적인 실제 촬영면적 속성으로 사진 부족 경로가 발급되지
않는지 검증한다. 시드는 고정이다 — 실패가 재현되지 않으면 디버깅할 수 없다.
"""

from __future__ import annotations

import math
import random

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ksi_core.mission_plans import MissionPlanRequest, build_mission_plan
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


def _direct_spacing_plan_request(
    *,
    mission_id: str,
    aoi: AreaOfInterest,
    altitude_m: float,
    spacing_m: float,
    interval_m: float,
    sweep_direction_deg: float | None,
) -> MissionPlanRequest:
    """Build a real Core issuance request using the legacy low-level spacing path."""
    return MissionPlanRequest.model_validate(
        {
            "contract": {
                "missionId": mission_id,
                "siteId": "site-coverage-property",
                "missionType": "BASELINE_MAPPING",
                "siteFrame": {
                    "crs": "EPSG:5186",
                    "verticalDatum": "KNGeoid2018",
                    "unit": "meter",
                    "transformVersion": "1.0.0",
                },
                "flightEnvelope": {
                    "allowedVolumes": ["vol-coverage-property"],
                    "excludedVolumes": [],
                    "minAltitudeM": 0.0,
                    "maxAltitudeM": 150.0,
                },
                "objectives": ["coverage property"],
                "viewpointPolicyId": "vp-coverage-property",
                "riskPolicyPackId": "risk-coverage-property",
                "fallbackPolicyId": "fallback-coverage-property",
                "capturePolicyId": "capture-coverage-property",
            },
            "aoi": {
                "vertices": [point.model_dump(by_alias=True) for point in aoi.vertices],
            },
            "route": {
                "altitudeM": altitude_m,
                "spacingM": spacing_m,
                "captureIntervalM": interval_m,
                "sweepDirectionDeg": sweep_direction_deg,
            },
            "drone": {"droneEnumValue": 99, "droneSubEnumValue": 0, "payloadEnumValue": 65534},
            "wayline": {
                "autoFlightSpeedMs": 5.0,
                "takeoffSecurityHeightM": 20.0,
                "globalTransitionalSpeedMs": 10.0,
            },
        }
    )


_SHAPES = ("rect", "triangle", "trapezoid", "parallelogram")
_WIDTHS = (20.0, 50.0, 100.0, 200.0, 400.0, 800.0, 2000.0)
_HEIGHTS = (5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0)
_ALTITUDES = (5.0, 10.0, 20.0, 40.0, 60.0, 87.0, 100.0, 150.0)
# 상한 경계(고도 150 → 225)를 정확히·아슬아슬하게 포함한다.
_SPACINGS = (0.5, 1.0, 5.0, 10.0, 20.0, 50.0, 60.0, 90.0, 150.0, 224.9, 225.0, 300.0)
_SWEEPS = (None, 0.0, 30.0, 45.0, 90.0, 137.0)


@pytest.mark.parametrize("seed", [20260805, 7, 99])
def test_direct_spacing_route_never_becomes_a_photogrammetric_coverage_claim(seed: int) -> None:
    """[핵심 속성] 수동 spacing 기하는 Core의 planned coverage claim이 될 수 없다.

    40ha를 사진 10장으로 덮었다고 계산하는 기하 결과 자체는 전문가 복구 경로에서
    필요할 수 있다. 하지만 CameraSpec에서 나온 footprint/overlap이 없으면 그 값은
    발급 응답·원장에 실릴 수 없다. 시드별 대량 입력으로 고도·spacing·간격 축을
    바꿔도 이 경계가 열리지 않는지 고정한다.
    """
    rng = random.Random(seed)
    issued = 0
    private_key = Ed25519PrivateKey.generate()

    for attempt in range(30):
        kind = rng.choice(_SHAPES)
        width, height = rng.choice(_WIDTHS), rng.choice(_HEIGHTS)
        altitude = rng.choice(_ALTITUDES)
        spacing = rng.choice(_SPACINGS)
        interval = rng.choice((0.5, 1.0, 5.0, 10.0, 20.0, 50.0, spacing, spacing * 0.99))
        sweep = rng.choice(_SWEEPS)
        try:
            aoi = AreaOfInterest(vertices=_vertices(kind, width, height))
            # First keep the same independent geometry rejection domain as the former
            # property test, then exercise the actual Core issuance boundary below.
            lawnmower_route(
                aoi, spacing_m=spacing, altitude_m=altitude, envelope=_ENVELOPE,
                sweep_direction_deg=sweep, capture_interval_m=interval,
            )
        except (RouteGenerationError, ValidationError):
            continue  # 거부는 이 속성의 관심사가 아니다 — 발급된 것만 본다
        result = build_mission_plan(
            _direct_spacing_plan_request(
                mission_id=f"coverage-direct-{seed}-{attempt}",
                aoi=aoi,
                altitude_m=altitude,
                spacing_m=spacing,
                interval_m=interval,
                sweep_direction_deg=sweep,
            ),
            private_key=private_key,
            key_id="coverage-property-key",
        )
        issued += 1
        assert result["plannedCoverageRatio"] is None

    # 공허 방지 — 실제로 상당수가 발급돼야 위 검사에 의미가 있다.
    assert issued >= 5, f"발급된 조합이 너무 적다({issued}) — 속성 테스트가 공허하다"


# ── CameraSpec 경로 (ADR-KSI-011 D3) ────────────────────────────────────────
#
# 직접 spacing 경로는 Core가 claim을 만들지 않고, CameraSpec 경로는 실제 촬영면적
# 속성을 만족해야 한다. 두 경계를 독립적으로 고정한다.

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
