"""CPA/TTC 계산기 — 등속 외삽 기반 최근접점·충돌시각 (Phase 3, PRD RISK-004/§12.7).

닫힌 형식(등속도 가정)만 구현한다 — 가속도·회전 등 고차 운동은 이 함수의 범위
밖이다(외삽 지평선을 짧게 잡아 오차를 억제하는 것이 상위 소비자의 몫). 골든
벡터는 손으로 유도한 정확값과 대조한다(P0 계열 검증 관습).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ksi_equipment_intelligence.kinematic_state import KinematicState

Vector3 = tuple[float, float, float]


class KinematicComparisonError(ValueError):
    """CPA/TTC 계산 파라미터가 유효하지 않거나 두 상태를 비교할 수 없을 때."""


@dataclass(frozen=True, slots=True)
class ClosestApproachResult:
    """[0, horizon_s] 구간에서의 최근접 시각·거리."""

    time_s: float
    distance_m: float


def _relative_position(a: KinematicState, b: KinematicState) -> Vector3:
    if a.site_frame != b.site_frame:
        raise KinematicComparisonError(
            f"두 KinematicState 가 다른 site_frame 이다({a.site_frame!r} vs {b.site_frame!r}) "
            "— 같은 좌표계 기준으로만 상대운동을 계산할 수 있다"
        )
    return (
        a.position[0] - b.position[0],
        a.position[1] - b.position[1],
        a.position[2] - b.position[2],
    )


def _relative_velocity(a: KinematicState, b: KinematicState) -> Vector3:
    return (
        a.velocity[0] - b.velocity[0],
        a.velocity[1] - b.velocity[1],
        a.velocity[2] - b.velocity[2],
    )


def _dot(u: Vector3, w: Vector3) -> float:
    return u[0] * w[0] + u[1] * w[1] + u[2] * w[2]


def _norm(u: Vector3) -> float:
    return math.sqrt(_dot(u, u))


def _require_valid_horizon(horizon_s: float) -> None:
    if not (math.isfinite(horizon_s) and horizon_s >= 0):
        raise KinematicComparisonError(
            f"horizon_s 는 0 이상의 finite 값이어야 한다 (got {horizon_s!r})"
        )


def closest_point_of_approach(
    a: KinematicState, b: KinematicState, *, horizon_s: float
) -> ClosestApproachResult:
    """등속 외삽 하에서 [0, horizon_s] 구간의 최근접 시각·거리.

    상대속도가 0이면(둘의 velocity 가 같음) 거리가 시간에 무관하게 일정하므로
    ``time_s=0``을 반환한다 — "가장 이른 시각의 최근접"이 관습이다(재현성:
    동일 입력 → 동일 출력, 무차별한 t 선택을 피한다).

    Raises:
        KinematicComparisonError: horizon_s 가 음수·비유한이거나 두 상태의
            site_frame 이 다를 때.
    """
    _require_valid_horizon(horizon_s)
    p = _relative_position(a, b)
    v = _relative_velocity(a, b)
    v_sq = _dot(v, v)
    t_star = 0.0 if v_sq == 0.0 else max(0.0, min(horizon_s, -_dot(p, v) / v_sq))
    distance = _norm((p[0] + v[0] * t_star, p[1] + v[1] * t_star, p[2] + v[2] * t_star))
    return ClosestApproachResult(time_s=t_star, distance_m=distance)


def time_to_collision(
    a: KinematicState, b: KinematicState, *, combined_radius_m: float, horizon_s: float
) -> float | None:
    """[0, horizon_s] 구간에서 상대거리가 ``combined_radius_m`` 이하가 되는 최초 시각.

    이미 그 반경 안이면 ``0.0``을 반환한다(예측이 아니라 관측 시점의 현재
    사실). horizon_s 안에 도달하지 않으면 ``None`` — "위험 없음"이 아니라
    "이 지평선 안에서는 확인되지 않음"이다(RiskField.riskModel.
    predictionHorizonSeconds 와 짝을 이루는 스코프 한정).

    Raises:
        KinematicComparisonError: horizon_s·combined_radius_m 이 음수·비유한이거나
            두 상태의 site_frame 이 다를 때.
    """
    _require_valid_horizon(horizon_s)
    if not (math.isfinite(combined_radius_m) and combined_radius_m >= 0):
        raise KinematicComparisonError(
            f"combined_radius_m 은 0 이상의 finite 값이어야 한다 (got {combined_radius_m!r})"
        )
    p = _relative_position(a, b)
    v = _relative_velocity(a, b)
    c = _dot(p, p) - combined_radius_m * combined_radius_m
    if c <= 0.0:
        return 0.0
    a_coef = _dot(v, v)
    if a_coef == 0.0:
        return None
    b_coef = 2.0 * _dot(p, v)
    discriminant = b_coef * b_coef - 4.0 * a_coef * c
    if discriminant < 0.0:
        return None
    t_enter = (-b_coef - math.sqrt(discriminant)) / (2.0 * a_coef)
    if t_enter < 0.0 or t_enter > horizon_s:
        return None
    return t_enter


__all__ = [
    "ClosestApproachResult",
    "KinematicComparisonError",
    "closest_point_of_approach",
    "time_to_collision",
]
