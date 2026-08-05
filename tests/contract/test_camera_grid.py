"""카메라 스펙 → 격자 간격 계약 (ADR-KSI-011 D2, 3순위).

이 모듈 이전에는 간격을 요청자가 적었고, 서버는 그 값이 적정한지 판단할 근거가
없었다 — 커버리지 계산이 요청자가 준 가정 위에 서서 40ha 가 사진 10장으로
발급됐다. 여기서 반증하는 것은 **간격이 실제로 요청한 중복도를 만드는가**다.

오라클은 손계산이다(구현을 다시 부르지 않는다) — 그러지 않으면 산식을 바꿔도
테스트가 같이 따라가 아무것도 못 잡는다.
"""

from __future__ import annotations

import math

import pytest
from ksi_geo_core.frames import WGS84_EQUATORIAL_RADIUS_M
from ksi_mission_contracts.models import FlightEnvelope
from ksi_mission_planning import (
    AreaOfInterest,
    CameraSpec,
    CameraSpecError,
    GeoPoint,
    RouteGenerationError,
    compute_grid_spacing,
    lawnmower_route,
)
from ksi_mission_planning.camera import (
    DEFAULT_FRONT_OVERLAP,
    DEFAULT_SIDE_OVERLAP,
    MIN_FRONT_OVERLAP,
    MIN_SIDE_OVERLAP,
    compute_gsd_m,
    footprint_m,
)

# 매핑용 기체 카메라 급 스펙(참고 구현의 테스트 오라클과 같은 규모).
# 센서 13.2mm / 초점 8.8mm / 5472×3648px — 고도 120m 에서 GSD 0.0329m/px,
# footprint 180×120m 가 나오도록 잡은 값이다.
_LAT0, _LON0 = 37.5000, 127.0000
_M_PER_DEG_LAT = math.radians(1.0) * WGS84_EQUATORIAL_RADIUS_M
_ENVELOPE = FlightEnvelope(
    allowed_volumes=["vol-1"], excluded_volumes=[], min_altitude_m=0.0, max_altitude_m=150.0
)


def _rect_aoi(width_m: float = 200.0, height_m: float = 100.0) -> AreaOfInterest:
    def pt(east: float, north: float) -> GeoPoint:
        return GeoPoint(
            lat_deg=_LAT0 + north / _M_PER_DEG_LAT,
            lon_deg=_LON0 + east / (_M_PER_DEG_LAT * math.cos(math.radians(_LAT0))),
        )

    return AreaOfInterest(
        vertices=[pt(0, 0), pt(width_m, 0), pt(width_m, height_m), pt(0, height_m)]
    )


_CAMERA = CameraSpec(
    sensor_width_mm=13.2,
    focal_length_mm=8.8,
    image_width_px=5472,
    image_height_px=3648,
)


def test_gsd_matches_hand_computed_value() -> None:
    """GSD = (센서폭_m × 고도) / (초점거리_m × 이미지폭_px) — 손계산 대조."""
    expected = (13.2 / 1000.0 * 120.0) / (8.8 / 1000.0 * 5472)
    assert compute_gsd_m(_CAMERA, 120.0) == pytest.approx(expected, rel=1e-12)


def test_footprint_matches_hand_computed_value() -> None:
    """고도 120m 에서 지상 촬영범위는 180×120m 규모다(픽셀수×GSD)."""
    across, along = footprint_m(_CAMERA, compute_gsd_m(_CAMERA, 120.0))
    assert across == pytest.approx(180.0, rel=0.01)
    assert along == pytest.approx(120.0, rel=0.01)


def test_standard_overlap_produces_expected_spacing() -> None:
    """표준 매핑(전방 0.8/측면 0.7) → 라인 54m · 사진 24m (참고 구현 오라클)."""
    grid = compute_grid_spacing(
        _CAMERA, altitude_m=120.0, front_overlap=0.8, side_overlap=0.7
    )
    assert grid.spacing_m == pytest.approx(54.0, rel=0.01)
    assert grid.capture_interval_m == pytest.approx(24.0, rel=0.01)


def test_spacing_actually_delivers_the_requested_overlap() -> None:
    """[핵심] 계산된 간격이 요청한 중복도를 **실제로** 만든다.

    간격 산식을 되돌려 중복도를 재유도한다 — 산식이 뒤집히거나 across/along 이
    바뀌면 여기서 걸린다.
    """
    for altitude in (30.0, 60.0, 120.0, 150.0):
        for front, side in ((0.8, 0.7), (0.75, 0.6), (0.6, 0.5)):
            grid = compute_grid_spacing(
                _CAMERA, altitude_m=altitude, front_overlap=front, side_overlap=side
            )
            derived_side = 1.0 - grid.spacing_m / grid.footprint_across_m
            derived_front = 1.0 - grid.capture_interval_m / grid.footprint_along_m
            assert derived_side == pytest.approx(side, abs=1e-12)
            assert derived_front == pytest.approx(front, abs=1e-12)


def test_spacing_scales_linearly_with_altitude() -> None:
    """고도가 2배면 촬영범위·간격도 2배 — 핀홀 모델의 기본 성질."""
    low = compute_grid_spacing(_CAMERA, altitude_m=50.0)
    high = compute_grid_spacing(_CAMERA, altitude_m=100.0)
    assert high.spacing_m == pytest.approx(low.spacing_m * 2, rel=1e-12)
    assert high.capture_interval_m == pytest.approx(low.capture_interval_m * 2, rel=1e-12)


def test_defaults_are_the_standard_mapping_configuration() -> None:
    """기본 중복도를 안 주면 표준 매핑 구성이 쓰인다."""
    explicit = compute_grid_spacing(
        _CAMERA,
        altitude_m=80.0,
        front_overlap=DEFAULT_FRONT_OVERLAP,
        side_overlap=DEFAULT_SIDE_OVERLAP,
    )
    assert compute_grid_spacing(_CAMERA, altitude_m=80.0) == explicit


# ── fail-closed ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("front", [0.0, 0.3, MIN_FRONT_OVERLAP - 0.01, 1.0, 1.5, math.nan])
def test_insufficient_front_overlap_rejected(front: float) -> None:
    """중복도가 하한 미만이면 정합점이 부족해 재구성이 실패한다 — 계산을 안 한다."""
    with pytest.raises(CameraSpecError, match="front_overlap"):
        compute_grid_spacing(_CAMERA, altitude_m=100.0, front_overlap=front)


@pytest.mark.parametrize("side", [0.0, MIN_SIDE_OVERLAP - 0.01, 1.0, math.inf])
def test_insufficient_side_overlap_rejected(side: float) -> None:
    with pytest.raises(CameraSpecError, match="side_overlap"):
        compute_grid_spacing(_CAMERA, altitude_m=100.0, side_overlap=side)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sensor_width_mm": 0.0},
        {"sensor_width_mm": -1.0},
        {"focal_length_mm": math.nan},
        {"image_width_px": 0},
        {"image_height_px": -5},
        {"image_width_px": True},  # bool 은 int 서브클래스 — 우회 차단
    ],
)
def test_invalid_camera_spec_rejected(kwargs: dict[str, object]) -> None:
    base = {
        "sensor_width_mm": 13.2,
        "focal_length_mm": 8.8,
        "image_width_px": 5472,
        "image_height_px": 3648,
    }
    with pytest.raises(CameraSpecError):
        CameraSpec(**{**base, **kwargs})  # type: ignore[arg-type]


@pytest.mark.parametrize("altitude", [0.0, -10.0, math.nan, math.inf])
def test_invalid_altitude_rejected(altitude: float) -> None:
    with pytest.raises(CameraSpecError, match="altitude_m"):
        compute_grid_spacing(_CAMERA, altitude_m=altitude)


def test_computed_spacing_satisfies_route_generator_bounds() -> None:
    """[통합] 계산된 간격이 경로 생성기의 상한(고도×1.5)을 자연히 만족한다.

    측면 중복도 하한 0.5 면 간격은 촬영폭의 절반 이하이고, 촬영폭이 고도의 1.5배를
    넘는 카메라는 매핑에 쓰지 않는다 — 두 게이트가 서로 모순되지 않음을 고정한다.
    """
    for altitude in (20.0, 60.0, 150.0):
        grid = compute_grid_spacing(
            _CAMERA, altitude_m=altitude, front_overlap=0.6, side_overlap=0.5
        )
        assert grid.spacing_m <= 1.5 * altitude
        assert grid.capture_interval_m <= grid.spacing_m


@pytest.mark.parametrize(
    ("front", "side"),
    [
        (0.8, 0.9),   # 라인 간 겹침을 높인 정상 구성 — 대리변수 상한이 오판하던 조합
        (0.6, 0.85),
        (0.9, 0.95),
    ],
)
def test_high_side_overlap_is_issuable_via_camera(front: float, side: float) -> None:
    """[핵심] 측면 겹침이 큰 정상 구성이 대리변수 상한에 걸리지 않는다.

    ``capture ≤ spacing`` 은 촬영폭을 **정사각으로 근사**한 대리변수라, 가로가 세로보다
    긴 실제 센서(5472×3648)에서는 측면 겹침을 올리면 성립하지 않는다 — 전방 0.8·
    측면 0.9 는 사진측량으로 완전히 정상인데 spacing 6.0 < capture 8.0 이 되어 422 가
    났다(독립 재검토 C-1, 대시보드 자유입력에서 실제 도달). 카메라를 알면 서버가
    실제 중복도를 이미 강제하므로 대리변수를 적용하지 않는다.
    """
    grid = compute_grid_spacing(
        _CAMERA, altitude_m=40.0, front_overlap=front, side_overlap=side
    )
    route = lawnmower_route(
        _rect_aoi(),
        spacing_m=grid.spacing_m,
        altitude_m=40.0,
        envelope=_ENVELOPE,
        capture_interval_m=grid.capture_interval_m,
        spacing_is_camera_derived=True,
    )
    assert route.waypoints
    assert route.coverage_ratio >= 0.95


def test_proxy_bounds_still_apply_without_camera() -> None:
    """[비공허 대조] 카메라 없이 직접 지정하면 대리변수 상한은 그대로 산다."""
    with pytest.raises(RouteGenerationError, match="capture_interval_m"):
        lawnmower_route(
            _rect_aoi(),
            spacing_m=6.0,
            altitude_m=40.0,
            envelope=_ENVELOPE,
            capture_interval_m=8.0,
        )
