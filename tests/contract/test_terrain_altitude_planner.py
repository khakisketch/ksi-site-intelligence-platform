"""지형추종 비행고도 계획 계약 — 순수 함수, 결정론적 (ADR-KSI-019 G6, AOL-3 Unit 1).

계산 자체가 아니라 **실패 처리**가 이 파일의 핵심이다: 지형고도를 모르는
지점은 값을 지어내지 않고, 봉투를 넘는 지점은 조용히 잘라내지 않고 거부하고,
DSM 이 없으면 여유값을 0으로 채우지 않는다 — reobservation.py 의 rationale
관례를 그대로 잇는다.
"""

from __future__ import annotations

import pytest
from ksi_mission_contracts.models import FlightEnvelope
from ksi_mission_planning.geometry import GeoPoint
from ksi_mission_planning.terrain import (
    AltitudeSegmentStatus,
    TerrainReferenceMismatch,
    WaypointTerrainSample,
    compute_altitude_profile,
)


def _envelope(*, min_altitude_m: float = 20.0, max_altitude_m: float = 120.0) -> FlightEnvelope:
    """**실제** 계약 모델을 쓴다 — Mock 이 아니다.

    이전 판은 두 필드만 흉내 내는 ``Mock`` 이었고, 그래서 봉투가 스스로 선언하는
    수직기준(``altitude_reference``)이 테스트에 아예 나타나지 않았다. 계산기가 절대
    표고를 이륙점 상대 봉투와 비교하던 결함(2026-08-15)이 리뷰를 통과한 이유가
    그것이다 — 대역이 "무엇을 비교하는지"를 가렸다.
    """
    return FlightEnvelope(
        allowed_volumes=[],
        excluded_volumes=[],
        min_altitude_m=min_altitude_m,
        max_altitude_m=max_altitude_m,
        altitude_reference="relativeToStartPoint",
    )


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
        takeoff_terrain_elevation_m=0.0,
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
    assert profile.segments[0].commanded_height_m == pytest.approx(95.0)  # 50+40+5
    assert profile.segments[1].commanded_height_m == pytest.approx(97.0)  # 52+40+5


def test_missing_terrain_data_fails_only_that_segment() -> None:
    """지형고도를 모르는 지점은 그 지점만 실패한다 — 이웃 값으로 보간하지 않는다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5000, 127.0000), terrain_elevation_m=50.0),
        WaypointTerrainSample(waypoint=_point(37.5001, 127.0000), terrain_elevation_m=None),
        WaypointTerrainSample(waypoint=_point(37.5002, 127.0000), terrain_elevation_m=54.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        takeoff_terrain_elevation_m=0.0,
        target_agl_m=40.0,
        safety_margin_m=5.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(),
        provenance="p",
    )

    assert profile.all_ok is False
    assert profile.segments[0].status is AltitudeSegmentStatus.OK
    assert profile.segments[1].status is AltitudeSegmentStatus.TERRAIN_DATA_MISSING
    assert profile.segments[1].commanded_height_m is None
    assert profile.segments[1].rationale  # 근거 없는 실패는 검토할 수 없다
    # 세 번째 지점은 두 번째의 실패에 영향받지 않는다 — 자기 지형고도로 정상 계산.
    assert profile.segments[2].status is AltitudeSegmentStatus.OK
    assert profile.segments[2].commanded_height_m == pytest.approx(99.0)  # 54+40+5


def test_altitude_beyond_the_envelope_is_rejected_not_clamped() -> None:
    """봉투를 넘는 고도는 조용히 잘라내지 않고 거부한다 — 신호를 지우지 않는다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5000, 127.0000), terrain_elevation_m=200.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        takeoff_terrain_elevation_m=0.0,
        target_agl_m=40.0,
        safety_margin_m=5.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(min_altitude_m=20.0, max_altitude_m=120.0),
        provenance="p",
    )

    assert profile.segments[0].status is AltitudeSegmentStatus.ENVELOPE_VIOLATION
    assert profile.segments[0].commanded_height_m is None
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
        takeoff_terrain_elevation_m=0.0,
        target_agl_m=40.0,
        safety_margin_m=0.0,
        max_altitude_change_ratio=0.5,
        envelope=_envelope(),
        provenance="p",
    )

    assert profile.segments[0].status is AltitudeSegmentStatus.OK
    assert profile.segments[1].status is AltitudeSegmentStatus.RATE_LIMIT_EXCEEDED
    assert profile.segments[1].commanded_height_m is None


def test_altitude_change_rate_at_zero_horizontal_distance_is_rejected() -> None:
    """수평이동 없이 고도만 뛰면(중복 웨이포인트·제자리 상승) 무한 비율로 거부한다.

    회귀 시험(2026-08-16): ``horizontal_m > 0.0`` 가드가 0/0 나눗셈을 피하려다
    수평거리가 정확히 0 인 구간의 고도변화율 검사 전체를 건너뛰고 있었다.
    """
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5000, 127.0000), terrain_elevation_m=50.0),
        # 같은 좌표, 지형고도만 30m 뛴다 — 수평거리 0 이라 비율은 정의상 무한대.
        WaypointTerrainSample(waypoint=_point(37.5000, 127.0000), terrain_elevation_m=80.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        takeoff_terrain_elevation_m=0.0,
        target_agl_m=40.0,
        safety_margin_m=0.0,
        max_altitude_change_ratio=0.5,
        envelope=_envelope(),
        provenance="p",
    )

    assert profile.segments[0].status is AltitudeSegmentStatus.OK
    assert profile.segments[1].status is AltitudeSegmentStatus.RATE_LIMIT_EXCEEDED
    assert profile.segments[1].commanded_height_m is None


def test_true_duplicate_waypoint_with_no_altitude_change_is_ok() -> None:
    """수평거리도 고도변화도 0 이면(완전 중복 웨이포인트) 위반이 아니다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5000, 127.0000), terrain_elevation_m=50.0),
        WaypointTerrainSample(waypoint=_point(37.5000, 127.0000), terrain_elevation_m=50.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        takeoff_terrain_elevation_m=0.0,
        target_agl_m=40.0,
        safety_margin_m=0.0,
        max_altitude_change_ratio=0.5,
        envelope=_envelope(),
        provenance="p",
    )

    assert profile.all_ok is True
    assert profile.segments[1].status is AltitudeSegmentStatus.OK


def test_clearance_is_none_without_a_surface_sample() -> None:
    """DSM(지표고)이 없으면 여유값은 None 이다 — 0 으로 채우지 않는다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5, 127.0), terrain_elevation_m=50.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        takeoff_terrain_elevation_m=0.0,
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
        takeoff_terrain_elevation_m=0.0,
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
            takeoff_terrain_elevation_m=0.0,
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
            takeoff_terrain_elevation_m=0.0,
            target_agl_m=0.0,
            safety_margin_m=5.0,
            max_altitude_change_ratio=1.0,
            envelope=_envelope(),
            provenance="p",
        )


# --- 수직기준 회귀 (2026-08-15 결함) ------------------------------------------
#
# 이전 구현은 `지형표고 + AGL + 여유` 라는 **절대표고** 하나만 내고 그것을
# **이륙점 상대**로 정의된 비행 봉투와 직접 비교했다. 두 기준을 섞은 비교라
# 양방향으로 틀렸다. 아래 두 시험이 그 두 방향을 각각 고정한다.


def test_high_elevation_site_does_not_silently_command_a_far_higher_flight() -> None:
    """오통과 방향 — 표고가 높은 현장에서 조용히 통과하면 실제 지상고가 몇 배가 된다.

    표고 112m 현장에서 지상고 30m 를 원한다. 절대표고로는 142m 이고 규제 상한
    150m 안이라 예전 구현은 통과시켰다 — 그런데 기체는 그 값을 **이륙점 기준**
    으로 받으므로 실제로는 지상 142m 를 난다(의도의 4.7배, 규제 위반).
    """
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5, 127.0), terrain_elevation_m=112.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        takeoff_terrain_elevation_m=112.0,  # 같은 현장에서 이륙한다
        target_agl_m=30.0,
        safety_margin_m=0.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(min_altitude_m=20.0, max_altitude_m=150.0),
        provenance="p",
    )

    segment = profile.segments[0]
    assert segment.status is AltitudeSegmentStatus.OK
    # 기체에 실리는 값은 30m 다 — 142m 가 아니다.
    assert segment.commanded_height_m == pytest.approx(30.0)
    # 절대표고는 따로 보존된다(DSM 여유값 계산용).
    assert segment.absolute_elevation_m == pytest.approx(142.0)


def test_high_elevation_site_can_still_plan_a_legal_low_flight() -> None:
    """오거부 방향 — 표고 130m 현장은 예전 구현에서 30m 비행조차 계획할 수 없었다.

    130+30 = 160 > 150 이라 ENVELOPE_VIOLATION 이 났다. 실제로는 지상 30m 로
    완전히 합법인 비행이다. 한국 토목현장 상당수가 이 표고대에 있다.
    """
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5, 127.0), terrain_elevation_m=130.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        takeoff_terrain_elevation_m=130.0,
        target_agl_m=30.0,
        safety_margin_m=0.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(min_altitude_m=20.0, max_altitude_m=150.0),
        provenance="p",
    )

    assert profile.all_ok is True
    assert profile.segments[0].commanded_height_m == pytest.approx(30.0)


def test_terrain_following_tracks_terrain_relative_to_the_takeoff_point() -> None:
    """지형이 오르면 명령값도 같은 만큼 오른다 — 지상고는 일정하게 유지된다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5000, 127.0), terrain_elevation_m=100.0),
        WaypointTerrainSample(waypoint=_point(37.5010, 127.0), terrain_elevation_m=110.0),
        WaypointTerrainSample(waypoint=_point(37.5020, 127.0), terrain_elevation_m=95.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        takeoff_terrain_elevation_m=100.0,
        target_agl_m=40.0,
        safety_margin_m=0.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(min_altitude_m=10.0, max_altitude_m=150.0),
        provenance="p",
    )

    assert profile.all_ok is True
    heights = [s.commanded_height_m for s in profile.segments]
    assert heights == [pytest.approx(40.0), pytest.approx(50.0), pytest.approx(35.0)]
    # 지상고는 어느 지점에서나 목표값 그대로다 — 지형추종의 정의.
    for segment, sample in zip(profile.segments, samples, strict=True):
        assert sample.terrain_elevation_m is not None
        assert segment.absolute_elevation_m is not None
        assert segment.absolute_elevation_m - sample.terrain_elevation_m == pytest.approx(40.0)


def test_envelope_declaring_another_vertical_reference_is_refused() -> None:
    """봉투가 다른 수직기준을 선언하면 계산하지 않는다 — 조용히 섞지 않는다."""

    class _OtherReferenceEnvelope:
        min_altitude_m = 20.0
        max_altitude_m = 150.0
        altitude_reference = "absoluteOrthometric"

    with pytest.raises(TerrainReferenceMismatch, match="absoluteOrthometric"):
        compute_altitude_profile(
            samples=[WaypointTerrainSample(waypoint=_point(37.5, 127.0), terrain_elevation_m=50.0)],
            takeoff_terrain_elevation_m=50.0,
            target_agl_m=30.0,
            safety_margin_m=0.0,
            max_altitude_change_ratio=1.0,
            envelope=_OtherReferenceEnvelope(),  # type: ignore[arg-type]
            provenance="p",
        )
