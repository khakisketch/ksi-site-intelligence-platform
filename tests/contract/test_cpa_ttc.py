"""CPA/TTC 골든 벡터 (Phase 3, PRD RISK-004) — 손으로 유도한 정확값과 대조한다
(P0 계열 검증 관습, MASTER_PRD §12.7 예측 지표).

두 KinematicState 의 등속 외삽 하 상대운동을 손 계산으로 미리 유도해두고, 계산기
출력이 그 값과 정확히(또는 pytest.approx) 일치하는지 본다 — "그럴듯한 코드"가
아니라 "맞는 산술"을 증명한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ksi_equipment_intelligence.cpa_ttc import (
    KinematicComparisonError,
    closest_point_of_approach,
    time_to_collision,
)
from ksi_equipment_intelligence.kinematic_state import KinematicState

_NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)
_COV3 = [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]


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
    result = closest_point_of_approach(a, b, horizon_s=100.0)
    assert result.time_s == pytest.approx(5.0)
    assert result.distance_m == pytest.approx(0.0, abs=1e-9)


def test_perpendicular_pass_through_origin() -> None:
    """A@(0,-10,0) v=(0,1,0), B 정지@(0,0,0) — 손계산: t_cpa=10s, distance=0."""
    a = _state(entity_id="a", position=[0.0, -10.0, 0.0], velocity=[0.0, 1.0, 0.0])
    b = _state(entity_id="b", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    result = closest_point_of_approach(a, b, horizon_s=100.0)
    assert result.time_s == pytest.approx(10.0)
    assert result.distance_m == pytest.approx(0.0, abs=1e-9)


def test_horizon_clamps_cpa_time_before_actual_closest_point() -> None:
    """위 시나리오를 horizon_s=5 로 자르면 t=5 시점 거리(=5m)에서 멈춘다.

    p(5)=(0,-10+5,0)=(0,-5,0) → distance 5.
    """
    a = _state(entity_id="a", position=[0.0, -10.0, 0.0], velocity=[0.0, 1.0, 0.0])
    b = _state(entity_id="b", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    result = closest_point_of_approach(a, b, horizon_s=5.0)
    assert result.time_s == pytest.approx(5.0)
    assert result.distance_m == pytest.approx(5.0)


def test_zero_relative_velocity_reports_time_zero_and_constant_distance() -> None:
    """같은 속도로 나란히 이동 — 거리가 시간에 무관하게 일정하므로 t=0 이 관습."""
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[1.0, 1.0, 0.0])
    b = _state(entity_id="b", position=[5.0, 0.0, 0.0], velocity=[1.0, 1.0, 0.0])
    result = closest_point_of_approach(a, b, horizon_s=100.0)
    assert result.time_s == pytest.approx(0.0)
    assert result.distance_m == pytest.approx(5.0)


def test_moving_apart_reports_closest_at_t_zero() -> None:
    """이미 벌어지는 중이면 미래에 더 가까워질 일이 없다 — CPA 는 t=0(현재)."""
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[5.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    result = closest_point_of_approach(a, b, horizon_s=100.0)
    assert result.time_s == pytest.approx(0.0)
    assert result.distance_m == pytest.approx(5.0)


def test_cpa_rejects_negative_horizon() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[1.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    with pytest.raises(KinematicComparisonError, match="horizon_s"):
        closest_point_of_approach(a, b, horizon_s=-1.0)


def test_cpa_rejects_non_finite_horizon() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[1.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    with pytest.raises(KinematicComparisonError, match="horizon_s"):
        closest_point_of_approach(a, b, horizon_s=float("inf"))


def test_cpa_rejects_mismatched_site_frame() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    b = _state(
        entity_id="b", position=[1.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0], site_frame="site-002"
    )
    with pytest.raises(KinematicComparisonError, match="site_frame"):
        closest_point_of_approach(a, b, horizon_s=10.0)


# ── time_to_collision ─────────────────────────────────────────────────────────


def test_head_on_ttc_matches_hand_derivation() -> None:
    """위 head-on 시나리오, combined_radius=1 — 손계산: t_enter=4.5s.

    a=|v|²=4, b=2(p·v)=2*(-10*2)=-40, c=|p|²-1=99.
    disc=1600-1584=16, sqrt=4. t=(40-4)/8=4.5.
    검산: p(4.5)=(-10+2*4.5,0,0)=(-1,0,0), |p|=1 = radius. ✓
    """
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    ttc = time_to_collision(a, b, combined_radius_m=1.0, horizon_s=100.0)
    assert ttc == pytest.approx(4.5)


def test_already_within_radius_returns_zero() -> None:
    """현재 거리(0.5m) < combined_radius(1.0m) — 예측이 아니라 현재 사실, TTC=0."""
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[0.5, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    ttc = time_to_collision(a, b, combined_radius_m=1.0, horizon_s=10.0)
    assert ttc == pytest.approx(0.0)


def test_no_relative_motion_and_outside_radius_never_collides() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[10.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    assert time_to_collision(a, b, combined_radius_m=1.0, horizon_s=1000.0) is None


def test_moving_apart_never_collides() -> None:
    """멀어지는 중이면 discriminant 는 실수여도 근이 전부 과거(음수) — None."""
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[5.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    assert time_to_collision(a, b, combined_radius_m=1.0, horizon_s=100.0) is None


def test_paths_never_come_within_radius_returns_none() -> None:
    """평행 이동이 반경 밖을 스쳐 지나간다 — discriminant<0."""
    a = _state(entity_id="a", position=[0.0, -100.0, 0.0], velocity=[0.0, 1.0, 0.0])
    b = _state(entity_id="b", position=[50.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    assert time_to_collision(a, b, combined_radius_m=1.0, horizon_s=1000.0) is None


def test_collision_beyond_horizon_returns_none() -> None:
    """head-on(t_enter=4.5s) 인데 horizon 을 4.0 으로 자르면 지평선 밖 — None."""
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    assert time_to_collision(a, b, combined_radius_m=1.0, horizon_s=4.0) is None


def test_collision_within_horizon_returns_value() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[1.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[10.0, 0.0, 0.0], velocity=[-1.0, 0.0, 0.0])
    ttc = time_to_collision(a, b, combined_radius_m=1.0, horizon_s=4.5)
    assert ttc == pytest.approx(4.5)


def test_ttc_rejects_negative_radius() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    b = _state(entity_id="b", position=[1.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    with pytest.raises(KinematicComparisonError, match="combined_radius_m"):
        time_to_collision(a, b, combined_radius_m=-1.0, horizon_s=10.0)


def test_ttc_rejects_mismatched_site_frame() -> None:
    a = _state(entity_id="a", position=[0.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0])
    b = _state(
        entity_id="b", position=[1.0, 0.0, 0.0], velocity=[0.0, 0.0, 0.0], site_frame="site-002"
    )
    with pytest.raises(KinematicComparisonError, match="site_frame"):
        time_to_collision(a, b, combined_radius_m=1.0, horizon_s=10.0)
