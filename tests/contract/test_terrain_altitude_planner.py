"""지형추종 비행고도 계획 계약 — 순수 함수, 결정론적 (ADR-KSI-019 G6, AOL-3 Unit 1).

계산 자체가 아니라 **실패 처리**가 이 파일의 핵심이다: 지형고도를 모르는
지점은 값을 지어내지 않고, 봉투를 넘는 지점은 조용히 잘라내지 않고 거부하고,
DSM 이 없으면 여유값을 0으로 채우지 않는다 — reobservation.py 의 rationale
관례를 그대로 잇는다.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from ksi_mission_planning.geometry import GeoPoint
from ksi_mission_planning.terrain import (
    AltitudeSegmentStatus,
    WaypointTerrainSample,
    compute_altitude_profile,
)


def _envelope(*, min_altitude_m: float = 20.0, max_altitude_m: float = 120.0) -> Mock:
    """FlightEnvelope 대역 — 이 함수가 실제로 읽는 두 필드만 흉내 낸다."""
    envelope = Mock()
    envelope.min_altitude_m = min_altitude_m
    envelope.max_altitude_m = max_altitude_m
    return envelope


def _point(lat_deg: float, lon_deg: float) -> GeoPoint:
    return GeoPoint(lat_deg=lat_deg, lon_deg=lon_deg)


def test_normal_path_is_all_ok() -> None:
    """정상 경로 — 전 구간 OK, 계산된 고도가 지형고도+목표AGL+여유값과 같다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5000, 127.0000), terrain_elevation_m=50.0),
        WaypointTerrainSample(waypoint=_point(37.5001, 127.0000), terrain_elevation_m=52.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        target_agl_m=40.0,
        safety_margin_m=5.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(),
        provenance="job-epoch-1",
    )

    assert profile.all_ok is True
    assert profile.provenance == "job-epoch-1"
    assert len(profile.segments) == 2
    assert profile.segments[0].status is AltitudeSegmentStatus.OK
    assert profile.segments[0].commanded_altitude_m == pytest.approx(95.0)  # 50+40+5
    assert profile.segments[1].commanded_altitude_m == pytest.approx(97.0)  # 52+40+5


def test_missing_terrain_data_fails_only_that_segment() -> None:
    """지형고도를 모르는 지점은 그 지점만 실패한다 — 이웃 값으로 보간하지 않는다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5000, 127.0000), terrain_elevation_m=50.0),
        WaypointTerrainSample(waypoint=_point(37.5001, 127.0000), terrain_elevation_m=None),
        WaypointTerrainSample(waypoint=_point(37.5002, 127.0000), terrain_elevation_m=54.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        target_agl_m=40.0,
        safety_margin_m=5.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(),
        provenance="p",
    )

    assert profile.all_ok is False
    assert profile.segments[0].status is AltitudeSegmentStatus.OK
    assert profile.segments[1].status is AltitudeSegmentStatus.TERRAIN_DATA_MISSING
    assert profile.segments[1].commanded_altitude_m is None
    assert profile.segments[1].rationale  # 근거 없는 실패는 검토할 수 없다
    # 세 번째 지점은 두 번째의 실패에 영향받지 않는다 — 자기 지형고도로 정상 계산.
    assert profile.segments[2].status is AltitudeSegmentStatus.OK
    assert profile.segments[2].commanded_altitude_m == pytest.approx(99.0)  # 54+40+5


def test_altitude_beyond_the_envelope_is_rejected_not_clamped() -> None:
    """봉투를 넘는 고도는 조용히 잘라내지 않고 거부한다 — 신호를 지우지 않는다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5000, 127.0000), terrain_elevation_m=200.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        target_agl_m=40.0,
        safety_margin_m=5.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(min_altitude_m=20.0, max_altitude_m=120.0),
        provenance="p",
    )

    assert profile.segments[0].status is AltitudeSegmentStatus.ENVELOPE_VIOLATION
    assert profile.segments[0].commanded_altitude_m is None
    assert "245" in profile.segments[0].rationale[0]


def test_altitude_change_rate_beyond_ratio_is_rejected() -> None:
    """이웃 지점 대비 고도변화가 비율 상한을 넘으면 거부한다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.50000, 127.00000), terrain_elevation_m=50.0),
        # ~11.1m 북쪽, 지형고도가 30m 뛴다 — 비율 상한 0.5 를 크게 넘는다(30/11.1≈2.7).
        WaypointTerrainSample(waypoint=_point(37.50010, 127.00000), terrain_elevation_m=80.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        target_agl_m=40.0,
        safety_margin_m=0.0,
        max_altitude_change_ratio=0.5,
        envelope=_envelope(),
        provenance="p",
    )

    assert profile.segments[0].status is AltitudeSegmentStatus.OK
    assert profile.segments[1].status is AltitudeSegmentStatus.RATE_LIMIT_EXCEEDED
    assert profile.segments[1].commanded_altitude_m is None


def test_clearance_is_none_without_a_surface_sample() -> None:
    """DSM(지표고)이 없으면 여유값은 None 이다 — 0 으로 채우지 않는다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5, 127.0), terrain_elevation_m=50.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        target_agl_m=40.0,
        safety_margin_m=5.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(),
        provenance="p",
    )

    assert profile.segments[0].clearance_m is None


def test_clearance_is_computed_when_a_surface_sample_is_given() -> None:
    """DSM 이 있으면 여유값 = 계획고도 - 지표고."""
    samples = [
        WaypointTerrainSample(
            waypoint=_point(37.5, 127.0), terrain_elevation_m=50.0, surface_elevation_m=60.0
        ),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        target_agl_m=40.0,
        safety_margin_m=5.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(),
        provenance="p",
    )

    # 계획고도 = 50+40+5 = 95, 여유값 = 95-60 = 35.
    assert profile.segments[0].clearance_m == pytest.approx(35.0)


def test_empty_samples_is_rejected() -> None:
    """빈 경로의 고도 계획은 정의되지 않는다 — 조용히 빈 결과를 내지 않는다."""
    with pytest.raises(ValueError, match="samples"):
        compute_altitude_profile(
            samples=[],
            target_agl_m=40.0,
            safety_margin_m=5.0,
            max_altitude_change_ratio=1.0,
            envelope=_envelope(),
            provenance="p",
        )


def test_non_positive_target_agl_is_rejected() -> None:
    with pytest.raises(ValueError, match="target_agl_m"):
        compute_altitude_profile(
            samples=[WaypointTerrainSample(waypoint=_point(37.5, 127.0), terrain_elevation_m=50.0)],
            target_agl_m=0.0,
            safety_margin_m=5.0,
            max_altitude_change_ratio=1.0,
            envelope=_envelope(),
            provenance="p",
        )
