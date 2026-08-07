"""CPA/TTC 골든 벡터 (Phase 3, PRD RISK-004) — 손으로 유도한 정확값과 대조한다
(P0 계열 검증 관습, MASTER_PRD §12.7 예측 지표).

두 KinematicState 의 등속 외삽 하 상대운동을 손 계산으로 미리 유도해두고, 계산기
출력이 그 값과 정확히(또는 pytest.approx) 일치하는지 본다 — "그럴듯한 코드"가
아니라 "맞는 산술"을 증명한다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from ksi_equipment_intelligence.cpa_ttc import (
    KinematicComparisonError,
    closest_point_of_approach,
    observation_gap_s,
    time_to_collision,
)
from ksi_equipment_intelligence.kinematic_state import KinematicState

_NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
_COV3 = [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]
# 아래 골든벡터는 전부 동일 _NOW 를 쓴다 — 시간창 게이트는 이 값과 무관하게
# 통과한다(그 게이트 자체는 "관측 시각차" 절의 전용 테스트가 고정한다).
_MAX_GAP_S = 1.0


def _state(
    *, entity_id: str, position: list[float], velocity: list[float], site_frame: str = "site-001"
) -> KinematicState:
    return KinematicState(
        entity_id=entity_id,
        observed_at=_NOW,
        site_frame=site_frame,
        position=position,
        position_covariance=_COV3,
        velocity=velocity,
        velocity_covariance=_COV3,
        source_class="Excavator",
    )


# ── closest_point_of_approach ────────────────────────────────────────────────


def test_head_on_approach_reaches_zero_distance_at_t5() -> None:
    """A@(0,0,0) v=(1,0,0), B@(10,0,0) v=(-1,0,0) — 손계산: t_cpa=5s, distance=0.

    상대위치 p=(-10,0,0), 상대속도 v=(2,0,0). t*=-p·v/|v|²=20/4=5.
    p(5)=(-10+2*5,0,0)=(0,0,0) → distance 0.
    """
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    result = closest_point_of_approach(a, b, horizon_s=100.0, max_observation_gap_s=_MAX_GAP_S)
    assert result.time_s == pytest.approx(5.0)
    assert result.distance_m == pytest.approx(0.0, abs=1e-9)


def test_perpendicular_pass_through_origin() -> None:
    """A@(0,-10,0) v=(0,1,0), B 정지@(0,0,0) — 손계산: t_cpa=10s, distance=0."""
    a = _state(entity_id="a", position=[0.0, -10.0, 0.0], velocity=[0.0, 1.0, 0.0])
    b = _state(entity_id="b", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    result = closest_point_of_approach(a, b, horizon_s=100.0, max_observation_gap_s=_MAX_GAP_S)
    assert result.time_s == pytest.approx(10.0)
    assert result.distance_m == pytest.approx(0.0, abs=1e-9)


def test_horizon_clamps_cpa_time_before_actual_closest_point() -> None:
    """위 시나리오를 horizon_s=5 로 자르면 t=5 시점 거리(=5m)에서 멈춘다.

    p(5)=(0,-10+5,0)=(0,-5,0) → distance 5.
    """
    a = _state(entity_id="a", position=[0.0, -10.0, 0.0], velocity=[0.0, 1.0, 0.0])
    b = _state(entity_id="b", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    result = closest_point_of_approach(a, b, horizon_s=5.0, max_observation_gap_s=_MAX_GAP_S)
    assert result.time_s == pytest.approx(5.0)
    assert result.distance_m == pytest.approx(5.0)


def test_zero_relative_velocity_reports_time_zero_and_constant_distance() -> None:
    """같은 속도로 나란히 이동 — 거리가 시간에 무관하게 일정하므로 t=0 이 관습."""
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[1.0, 1.0, 0.0])
    b = _state(entity_id="b", position=[5.0, 0.0, 0.0], velocity=[1.0, 1.0, 0.0])
    result = closest_point_of_approach(a, b, horizon_s=100.0, max_observation_gap_s=_MAX_GAP_S)
    assert result.time_s == pytest.approx(0.0)
    assert result.distance_m == pytest.approx(5.0)


def test_moving_apart_reports_closest_at_t_zero() -> None:
    """이미 벌어지는 중이면 미래에 더 가까워질 일이 없다 — CPA 는 t=0(현재)."""
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[5.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    result = closest_point_of_approach(a, b, horizon_s=100.0, max_observation_gap_s=_MAX_GAP_S)
    assert result.time_s == pytest.approx(0.0)
    assert result.distance_m == pytest.approx(5.0)


def test_cpa_rejects_negative_horizon() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[1.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    with pytest.raises(KinematicComparisonError, match="horizon_s"):
        closest_point_of_approach(a, b, horizon_s=-1.0, max_observation_gap_s=_MAX_GAP_S)


def test_cpa_rejects_non_finite_horizon() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[1.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    with pytest.raises(KinematicComparisonError, match="horizon_s"):
        closest_point_of_approach(
            a, b, horizon_s=float("inf"), max_observation_gap_s=_MAX_GAP_S
        )


def test_cpa_rejects_mismatched_site_frame() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    b = _state(
        entity_id="b", position=[1.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0], site_frame="site-002"
    )
    with pytest.raises(KinematicComparisonError, match="site_frame"):
        closest_point_of_approach(a, b, horizon_s=10.0, max_observation_gap_s=_MAX_GAP_S)


# ── time_to_collision ─────────────────────────────────────────────────────────


def test_head_on_ttc_matches_hand_derivation() -> None:
    """위 head-on 시나리오, combined_radius=1 — 손계산: t_enter=4.5s.

    a=|v|²=4, b=2(p·v)=2*(-10*2)=-40, c=|p|²-1=99.
    disc=1600-1584=16, sqrt=4. t=(40-4)/8=4.5.
    검산: p(4.5)=(-10+2*4.5,0,0)=(-1,0,0), |p|=1 = radius. ✓
    """
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    ttc = time_to_collision(
        a,
        b,
        combined_radius_m=1.0,
        horizon_s=100.0,
        max_observation_gap_s=_MAX_GAP_S,
    )
    assert ttc == pytest.approx(4.5)


def test_already_within_radius_returns_zero() -> None:
    """현재 거리(0.5m) < combined_radius(1.0m) — 예측이 아니라 현재 사실, TTC=0."""
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[0.5, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    ttc = time_to_collision(
        a,
        b,
        combined_radius_m=1.0,
        horizon_s=10.0,
        max_observation_gap_s=_MAX_GAP_S,
    )
    assert ttc == pytest.approx(0.0)


def test_no_relative_motion_and_outside_radius_never_collides() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[10.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    assert (
        time_to_collision(
            a,
            b,
            combined_radius_m=1.0,
            horizon_s=1000.0,
            max_observation_gap_s=_MAX_GAP_S,
        )
        is None
    )


def test_moving_apart_never_collides() -> None:
    """멀어지는 중이면 discriminant 는 실수여도 근이 전부 과거(음수) — None."""
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[5.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    assert (
        time_to_collision(
            a,
            b,
            combined_radius_m=1.0,
            horizon_s=100.0,
            max_observation_gap_s=_MAX_GAP_S,
        )
        is None
    )


def test_paths_never_come_within_radius_returns_none() -> None:
    """평행 이동이 반경 밖을 스쳐 지나간다 — discriminant<0."""
    a = _state(entity_id="a", position=[0.0, -100.0, 0.0], velocity=[0.0, 1.0, 0.0])
    b = _state(entity_id="b", position=[50.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    assert (
        time_to_collision(
            a,
            b,
            combined_radius_m=1.0,
            horizon_s=1000.0,
            max_observation_gap_s=_MAX_GAP_S,
        )
        is None
    )


def test_collision_beyond_horizon_returns_none() -> None:
    """head-on(t_enter=4.5s) 인데 horizon 을 4.0 으로 자르면 지평선 밖 — None."""
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    assert (
        time_to_collision(
            a,
            b,
            combined_radius_m=1.0,
            horizon_s=4.0,
            max_observation_gap_s=_MAX_GAP_S,
        )
        is None
    )


def test_collision_within_horizon_returns_value() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    ttc = time_to_collision(
        a,
        b,
        combined_radius_m=1.0,
        horizon_s=4.5,
        max_observation_gap_s=_MAX_GAP_S,
    )
    assert ttc == pytest.approx(4.5)


def test_ttc_rejects_negative_radius() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[1.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    with pytest.raises(KinematicComparisonError, match="combined_radius_m"):
        time_to_collision(
            a,
            b,
            combined_radius_m=-1.0,
            horizon_s=10.0,
            max_observation_gap_s=_MAX_GAP_S,
        )


def test_ttc_rejects_mismatched_site_frame() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    b = _state(
        entity_id="b", position=[1.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0], site_frame="site-002"
    )
    with pytest.raises(KinematicComparisonError, match="site_frame"):
        time_to_collision(
            a,
            b,
            combined_radius_m=1.0,
            horizon_s=10.0,
            max_observation_gap_s=_MAX_GAP_S,
        )


# ── 두 상태는 "동시각"이어야 한다 (risk cpa-ttc-observed-at-mismatch-unchecked) ──
#
# 상대운동 계산은 두 상태가 같은 순간의 것이라고 가정하는데, 그 가정을 아무도
# 검사하지 않으면 10분 전 굴착기 위치와 방금 작업자 위치로 "TTC 2.1초"가 나온다.
# 값은 전부 유효 범위라 어떤 화면에서도 이상해 보이지 않는다.


def _state_at(when: datetime, *, entity_id: str, position: list[float]) -> KinematicState:
    return KinematicState(
        entity_id=entity_id,
        observed_at=when,
        site_frame="site-001",
        position=position,
        position_covariance=_COV3,
        velocity=[1.0, 0.0, 0.0],
        velocity_covariance=_COV3,
        source_class="Excavator",
    )


def test_cpa_rejects_states_observed_too_far_apart() -> None:
    a = _state_at(_NOW, entity_id="a", position=[0.0, 0.0, 0.0])
    stale = _state_at(_NOW - timedelta(minutes=10), entity_id="b", position=[10.0, 0.0, 0.0])
    with pytest.raises(KinematicComparisonError, match="observed_at"):
        closest_point_of_approach(a, stale, horizon_s=100.0, max_observation_gap_s=1.0)


def test_ttc_rejects_states_observed_too_far_apart() -> None:
    a = _state_at(_NOW, entity_id="a", position=[0.0, 0.0, 0.0])
    stale = _state_at(_NOW - timedelta(minutes=10), entity_id="b", position=[10.0, 0.0, 0.0])
    with pytest.raises(KinematicComparisonError, match="observed_at"):
        time_to_collision(
            a, stale, combined_radius_m=1.0, horizon_s=100.0, max_observation_gap_s=1.0
        )


def test_gap_exactly_at_limit_is_accepted() -> None:
    """경계는 포함이다 — 허용창과 정확히 같은 시간차를 거부하지 않는다."""
    a = _state_at(_NOW, entity_id="a", position=[0.0, 0.0, 0.0])
    b = _state_at(_NOW - timedelta(seconds=2), entity_id="b", position=[10.0, 0.0, 0.0])
    result = closest_point_of_approach(a, b, horizon_s=100.0, max_observation_gap_s=2.0)
    assert result.distance_m >= 0.0


def test_gap_direction_does_not_matter() -> None:
    """어느 쪽이 오래됐든 같은 판정 — 시간차는 절댓값이다."""
    a = _state_at(_NOW, entity_id="a", position=[0.0, 0.0, 0.0])
    stale = _state_at(_NOW - timedelta(seconds=30), entity_id="b", position=[10.0, 0.0, 0.0])
    for first, second in ((a, stale), (stale, a)):
        with pytest.raises(KinematicComparisonError, match="observed_at"):
            closest_point_of_approach(
                first, second, horizon_s=100.0, max_observation_gap_s=1.0
            )


@pytest.mark.parametrize("bad_gap", [-1.0, float("nan"), float("inf")])
def test_invalid_max_observation_gap_is_rejected(bad_gap: float) -> None:
    a = _state_at(_NOW, entity_id="a", position=[0.0, 0.0, 0.0])
    b = _state_at(_NOW, entity_id="b", position=[10.0, 0.0, 0.0])
    with pytest.raises(KinematicComparisonError, match="max_observation_gap_s"):
        closest_point_of_approach(a, b, horizon_s=100.0, max_observation_gap_s=bad_gap)


def test_observation_gap_s_is_absolute() -> None:
    a = _state_at(_NOW, entity_id="a", position=[0.0, 0.0, 0.0])
    b = _state_at(_NOW - timedelta(seconds=7.5), entity_id="b", position=[1.0, 0.0, 0.0])
    assert observation_gap_s(a, b) == 7.5
    assert observation_gap_s(b, a) == 7.5
