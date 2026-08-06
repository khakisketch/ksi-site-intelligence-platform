"""Active Reobservation 권고 신호 (Phase 3, PRD RISK-005/§13.5) — Core 는
불리언 신호만 낸다는 control boundary 가 실제로 지켜지는지, 그리고 그 판정
로직(위치 불확실성 문턱)이 정확한지 검증한다.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import pytest
from ksi_equipment_intelligence.kinematic_state import KinematicState
from ksi_equipment_intelligence.reobservation_signal import (
    needs_active_reobservation,
    position_uncertainty_m,
)

_NOW = datetime(2026, 8, 6, 12, 0, 0, tzinfo=UTC)


def _state(*, entity_id: str, position_covariance: list[float]) -> KinematicState:
    return KinematicState(
        entity_id=entity_id,
        observed_at=_NOW,
        site_frame="site-001",
        position=[0.0, 0.0, 0.0],
        position_covariance=position_covariance,
        velocity=[0.0, 0.0, 0.0],
        velocity_covariance=[0.0] * 9,
        source_class="Excavator",
    )


def _diag_covariance(sigma_x2: float, sigma_y2: float, sigma_z2: float) -> list[float]:
    return [sigma_x2, 0, 0, 0, sigma_y2, 0, 0, 0, sigma_z2]


# ── position_uncertainty_m ────────────────────────────────────────────────────


def test_uncertainty_is_sqrt_of_trace() -> None:
    """대각 공분산 (4, 9, 0) — trace=13, sqrt(13) 이 정확값(손계산)."""
    state = _state(entity_id="e", position_covariance=_diag_covariance(4.0, 9.0, 0.0))
    assert position_uncertainty_m(state) == pytest.approx(math.sqrt(13.0))


def test_zero_covariance_gives_zero_uncertainty() -> None:
    state = _state(entity_id="e", position_covariance=[0.0] * 9)
    assert position_uncertainty_m(state) == pytest.approx(0.0)


def test_off_diagonal_terms_do_not_affect_trace() -> None:
    """trace 는 대각 성분만의 합이다 — 비대각 공분산이 있어도 무관하다."""
    cov = [1.0, 0.5, 0.0, 0.5, 1.0, 0.0, 0.0, 0.0, 1.0]  # trace=3
    state = _state(entity_id="e", position_covariance=cov)
    assert position_uncertainty_m(state) == pytest.approx(math.sqrt(3.0))


# ── needs_active_reobservation ────────────────────────────────────────────────


def test_low_uncertainty_both_states_no_recommendation() -> None:
    equipment = _state(entity_id="eq", position_covariance=_diag_covariance(0.01, 0.01, 0.01))
    subject = _state(entity_id="su", position_covariance=_diag_covariance(0.01, 0.01, 0.01))
    assert (
        needs_active_reobservation(
            equipment_state=equipment, subject_state=subject, position_uncertainty_threshold_m=1.0
        )
        is False
    )


def test_high_equipment_uncertainty_triggers_recommendation() -> None:
    equipment = _state(entity_id="eq", position_covariance=_diag_covariance(100.0, 0.0, 0.0))
    subject = _state(entity_id="su", position_covariance=_diag_covariance(0.01, 0.01, 0.01))
    assert (
        needs_active_reobservation(
            equipment_state=equipment, subject_state=subject, position_uncertainty_threshold_m=1.0
        )
        is True
    )


def test_high_subject_uncertainty_alone_also_triggers() -> None:
    """장비 쪽이 정확해도 대상(작업자 등) 쪽이 불확실하면 여전히 권고한다 —
    CPA/TTC 신뢰도는 둘 중 약한 쪽을 따른다."""
    equipment = _state(entity_id="eq", position_covariance=_diag_covariance(0.01, 0.01, 0.01))
    subject = _state(entity_id="su", position_covariance=_diag_covariance(100.0, 0.0, 0.0))
    assert (
        needs_active_reobservation(
            equipment_state=equipment, subject_state=subject, position_uncertainty_threshold_m=1.0
        )
        is True
    )


def test_boundary_at_exact_threshold_is_not_recommended() -> None:
    """엄격 부등호(>)다 — 정확히 문턱과 같으면 아직 권고하지 않는다."""
    equipment = _state(entity_id="eq", position_covariance=_diag_covariance(1.0, 0.0, 0.0))
    subject = _state(entity_id="su", position_covariance=[0.0] * 9)
    assert (
        needs_active_reobservation(
            equipment_state=equipment, subject_state=subject, position_uncertainty_threshold_m=1.0
        )
        is False
    )


def test_negative_threshold_rejected() -> None:
    equipment = _state(entity_id="eq", position_covariance=[0.0] * 9)
    subject = _state(entity_id="su", position_covariance=[0.0] * 9)
    with pytest.raises(ValueError, match="position_uncertainty_threshold_m"):
        needs_active_reobservation(
            equipment_state=equipment, subject_state=subject, position_uncertainty_threshold_m=-1.0
        )


def test_non_finite_threshold_rejected() -> None:
    equipment = _state(entity_id="eq", position_covariance=[0.0] * 9)
    subject = _state(entity_id="su", position_covariance=[0.0] * 9)
    with pytest.raises(ValueError, match="position_uncertainty_threshold_m"):
        needs_active_reobservation(
            equipment_state=equipment,
            subject_state=subject,
            position_uncertainty_threshold_m=float("nan"),
        )


def test_return_type_is_plain_bool_not_a_command() -> None:
    """[control boundary] 반환값은 단순 bool 이지 Viewpoint·비행좌표가 아니다 —
    이 함수의 반환 타입 자체가 '신호만 낸다'는 계약을 강제한다."""
    equipment = _state(entity_id="eq", position_covariance=_diag_covariance(100.0, 0.0, 0.0))
    subject = _state(entity_id="su", position_covariance=[0.0] * 9)
    result = needs_active_reobservation(
        equipment_state=equipment, subject_state=subject, position_uncertainty_threshold_m=1.0
    )
    assert type(result) is bool
