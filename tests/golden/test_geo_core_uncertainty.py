"""불확실성 단조성 검증 (P0-4, INV-021).

geo-core 자체 golden vector가 없는 대신, project_foot_point를 통해 confidence·
error_radius_m이 "지평선에 가까워질수록·거리가 멀어질수록" 비증가/비감소함을
파라미터 스윕으로 검증한다 — legacy_compat 회귀만으로는 단조성이 보장되지 않는다
(회귀는 개별 점만 확인, 여기는 그 사이 궤적을 확인).
"""

from __future__ import annotations

from itertools import pairwise

from ksi_geo_core.projection import project_foot_point
from ksi_geo_core.sync import SourceQuality, TelemetrySample
from ksi_geo_core.timestamps import TimestampSet


def _sample(*, pitch_deg: float, altitude_rel_m: float = 100.0) -> TelemetrySample:
    return TelemetrySample(
        ts=TimestampSet(source_ts_utc=0.0, receive_ts_utc=0.0, capture_ts_utc=0.0),
        drone_lat=37.5,
        drone_lon=127.0,
        altitude_rel_m=altitude_rel_m,
        heading_deg=0.0,
        gimbal_pitch_deg=pitch_deg,
        camera_fov_deg=84.0,
        zoom_factor=1.0,
        rtk_fixed=True,
        source_quality=SourceQuality.FULL,
    )


def test_confidence_nonincreasing_as_gimbal_approaches_horizon() -> None:
    """pitch: -90(nadir) → -1(거의 수평) 스윕 — confidence는 비증가해야 한다."""
    pitches = [-90.0, -80.0, -60.0, -45.0, -30.0, -15.0, -5.0, -2.0, -1.0]
    results = [project_foot_point(960.0, 540.0, 1920, 1080, _sample(pitch_deg=p)) for p in pitches]
    assert all(r.ok for r in results), [r.status for r in results]

    confidences = [r.confidence for r in results]
    for earlier, later in pairwise(confidences):
        assert later <= earlier + 1e-9, confidences


def test_error_radius_nondecreasing_as_gimbal_approaches_horizon() -> None:
    """같은 스윕에서 error_radius_m은 비감소해야 한다(confidence와 반대 방향의 단조성)."""
    pitches = [-90.0, -80.0, -60.0, -45.0, -30.0, -15.0, -5.0, -2.0, -1.0]
    results = [project_foot_point(960.0, 540.0, 1920, 1080, _sample(pitch_deg=p)) for p in pitches]
    assert all(r.ok for r in results)

    radii = [r.error_radius_m for r in results]
    for earlier, later in pairwise(radii):
        assert later is not None and earlier is not None
        assert later >= earlier - 1e-9, radii


def test_confidence_nonincreasing_as_altitude_increases_at_fixed_pitch() -> None:
    """고도만 증가(같은 완만한 pitch) → 수평거리/고도 비가 커지므로 confidence 비증가."""
    altitudes = [50.0, 100.0, 200.0, 400.0, 800.0]
    results = [
        project_foot_point(960.0, 540.0, 1920, 1080, _sample(pitch_deg=-45.0, altitude_rel_m=a))
        for a in altitudes
    ]
    assert all(r.ok for r in results)

    confidences = [r.confidence for r in results]
    for earlier, later in pairwise(confidences):
        assert later <= earlier + 1e-9, confidences


def test_confidence_lowest_just_before_horizon_rejection() -> None:
    """거부(ABOVE_HORIZON) 직전 각도의 confidence가 스윕 전체에서 최저여야 한다."""
    pitches = [-90.0, -45.0, -10.0, -3.0, -1.0, -0.5]
    results = [project_foot_point(960.0, 540.0, 1920, 1080, _sample(pitch_deg=p)) for p in pitches]
    assert all(r.ok for r in results)
    confidences = [r.confidence for r in results]
    assert confidences[-1] == min(confidences)
