"""project_foot_point 입력 검증 네거티브 (반증 리뷰 2026-07-26 P0, P0-4).

이전 구현은 ``_geo_capable()``이 값의 None 여부만 확인해 NaN 위도·0 너비·범위 밖
FOV 등이 검증 없이 통과할 수 있었고, 그 결과 ``OK`` 상태와 함께 NaN 좌표를 반환할
수 있었다(fail-open). 여기서는 그 각 경로가 실제로 typed 실패로 거부됨을 확인한다.
"""

from __future__ import annotations

import math

import pytest
from ksi_geo_core.projection import ProjectionStatus, project_foot_point
from ksi_geo_core.sync import SourceQuality, TelemetrySample
from ksi_geo_core.timestamps import TimestampSet


def _sample(**overrides: float | bool | None) -> TelemetrySample:
    base: dict = {
        "drone_lat": 37.5,
        "drone_lon": 127.0,
        "altitude_rel_m": 100.0,
        "heading_deg": 0.0,
        "gimbal_pitch_deg": -90.0,
        "camera_fov_deg": 84.0,
        "zoom_factor": 1.0,
        "rtk_fixed": True,
        "source_quality": SourceQuality.FULL,
    }
    base.update(overrides)
    return TelemetrySample(ts=TimestampSet(source_ts_utc=0.0, receive_ts_utc=0.0), **base)


@pytest.mark.parametrize(("width", "height"), [(0, 1080), (1920, 0), (-1, 1080), (1920, -1)])
def test_invalid_image_dimensions_rejected(width: int, height: int) -> None:
    result = project_foot_point(960.0, 540.0, width, height, _sample())
    assert result.status is ProjectionStatus.INVALID_IMAGE_DIMENSIONS
    assert result.lat is None


@pytest.mark.parametrize("u_px", [math.nan, math.inf, -math.inf])
def test_nonfinite_pixel_rejected(u_px: float) -> None:
    result = project_foot_point(u_px, 540.0, 1920, 1080, _sample())
    assert result.status is ProjectionStatus.INVALID_PIXEL
    assert result.lat is None


@pytest.mark.parametrize("default_fov_deg", [0.0, -10.0, 180.0, 181.0, math.nan, math.inf])
def test_invalid_default_fov_rejected(default_fov_deg: float) -> None:
    sample = _sample(camera_fov_deg=None)  # default_fov_deg 경로를 강제로 태운다
    result = project_foot_point(
        960.0, 540.0, 1920, 1080, sample, default_fov_deg=default_fov_deg
    )
    assert result.status is ProjectionStatus.INVALID_INTRINSICS


@pytest.mark.parametrize("camera_fov_deg", [0.0, -5.0, 180.0, 200.0])
def test_invalid_telemetry_fov_rejected(camera_fov_deg: float) -> None:
    result = project_foot_point(960.0, 540.0, 1920, 1080, _sample(camera_fov_deg=camera_fov_deg))
    assert result.status is ProjectionStatus.INVALID_INTRINSICS


@pytest.mark.parametrize(
    "field",
    [
        "drone_lat",
        "drone_lon",
        "heading_deg",
        "gimbal_pitch_deg",
        "gimbal_roll_deg",
        "gimbal_yaw_deg",
    ],
)
@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf])
def test_nonfinite_telemetry_field_rejected(field: str, bad_value: float) -> None:
    result = project_foot_point(960.0, 540.0, 1920, 1080, _sample(**{field: bad_value}))
    assert result.status is ProjectionStatus.NONFINITE_INPUT
    assert result.lat is None


@pytest.mark.parametrize(
    ("drone_lat", "drone_lon"),
    [(91.0, 127.0), (-91.0, 127.0), (37.5, 181.0), (37.5, -181.0), (math.nan, 127.0)],
)
def test_invalid_geo_range_or_nonfinite_rejected(drone_lat: float, drone_lon: float) -> None:
    result = project_foot_point(
        960.0, 540.0, 1920, 1080, _sample(drone_lat=drone_lat, drone_lon=drone_lon)
    )
    assert result.status in (
        ProjectionStatus.INVALID_GEO_RANGE,
        ProjectionStatus.NONFINITE_INPUT,
    )
    assert result.lat is None


def test_altitude_nonfinite_rejected() -> None:
    result = project_foot_point(960.0, 540.0, 1920, 1080, _sample(altitude_rel_m=math.nan))
    assert result.status is ProjectionStatus.INVALID_ALTITUDE


def test_ok_result_always_has_finite_coordinates_confidence_and_error_radius() -> None:
    """OK 결과는 좌표·confidence·오차반경 전부가 finite여야 한다 — 여러 각도에서 재확인."""
    for pitch_deg in (-90.0, -60.0, -45.0, -30.0, -10.0):
        result = project_foot_point(960.0, 540.0, 1920, 1080, _sample(gimbal_pitch_deg=pitch_deg))
        assert result.ok, result.status
        assert result.lat is not None and math.isfinite(result.lat)
        assert result.lon is not None and math.isfinite(result.lon)
        assert result.east_m is not None and math.isfinite(result.east_m)
        assert result.north_m is not None and math.isfinite(result.north_m)
        assert math.isfinite(result.confidence)
        assert result.error_radius_m is not None and math.isfinite(result.error_radius_m)
