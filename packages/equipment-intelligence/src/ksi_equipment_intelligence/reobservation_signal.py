"""Active Reobservation 권고 신호 (Phase 3, PRD RISK-005/§13.5) — Core 는 신호만
발행한다, Viewpoint 선택·비행 행동은 만들지 않는다.

## Control boundary (프로젝트 CLAUDE.md, PRD §14.2)

"Edge: Receding Horizon Local Plan, Next Best View, Rejoin Plan" — Active
Perception 의 실제 Viewpoint 선택·점수화(§13.3)·행동 템플릿(§13.4, HOLD_AND_ZOOM
등)은 전부 Edge/Manifold 소관이다. 이 모듈은 phase-2 Spatial Refresh Backbone 의
``CoverageReportView.recoveryRecommended``(coverage_report.py)와 동일한 패턴을
따른다 — **권고 신호 불리언 하나**만 낸다. 자동으로 재관찰을 트리거하거나
Viewpoint·비행좌표를 만들지 않는다 — 그건 LLM/Core 가 하면 안 되는 일이다
(CLAUDE.md Control boundaries: "LLM must not emit executable flight coordinates
or bypass safety policy").

## 왜 position uncertainty 만 보는가

PRD §13.5 "정보 부족 처리"는 다섯 조건(카메라 해상도·위치 경계·가림·장비 부품
Pose·이벤트 문맥)을 나열하지만, 이 모듈이 가진 typed 데이터
(:class:`~ksi_equipment_intelligence.kinematic_state.KinematicState`.
position_covariance)로 직접 판정 가능한 것은 "위치 경계 불확실"뿐이다. 나머지
넷은 이 계약이 담지 않는 정보(카메라 메타데이터·가림 마스크·이벤트 컨텍스트)라
지어내지 않는다 — 그 신호들을 담는 계약이 생기면 이 함수에 조건을 추가한다.
"""

from __future__ import annotations

import math

from ksi_equipment_intelligence.kinematic_state import KinematicState


def position_uncertainty_m(state: KinematicState) -> float:
    """position_covariance 대각합의 제곱근 — 위치 불확실성의 스칼라 요약(RMS 반경 근사).

    3×3 공분산의 trace(분산의 합)는 좌표축 회전에 불변이라 site_frame 방향에
    의존하지 않는 요약이 된다. 개별 성분(예: x축만 불확실성이 큰 경우)을
    가리지만, "재관찰이 필요한가"라는 이진 판단에는 스칼라 문턱이 필요하다.
    """
    trace = (
        state.position_covariance[0]
        + state.position_covariance[4]
        + state.position_covariance[8]
    )
    return math.sqrt(max(0.0, trace))


def needs_active_reobservation(
    *,
    equipment_state: KinematicState,
    subject_state: KinematicState,
    position_uncertainty_threshold_m: float,
) -> bool:
    """[RISK-005] 위치 불확실성이 문턱을 넘으면 재관찰을 권고한다.

    ``True`` 는 "Edge/Manifold 가 Active Perception(§13)으로 이 개체를 다시
    관측하는 것을 고려하라"는 신호일 뿐이다 — 이 함수는 **어떤** Viewpoint 로
    재관측할지 정하지 않는다(Edge 의 Next Best View 소관, PRD §14.2). 두 상태 중
    하나라도 문턱을 넘으면 True — 장비·대상 어느 쪽 위치가 불확실해도 CPA/TTC
    자체의 신뢰도가 흔들리기 때문이다.

    Raises:
        ValueError: ``position_uncertainty_threshold_m`` 이 음수·비유한.
    """
    if not (
        math.isfinite(position_uncertainty_threshold_m)
        and position_uncertainty_threshold_m >= 0
    ):
        raise ValueError(
            "position_uncertainty_threshold_m 은 0 이상의 finite 값이어야 한다 "
            f"(got {position_uncertainty_threshold_m!r})"
        )
    return (
        position_uncertainty_m(equipment_state) > position_uncertainty_threshold_m
        or position_uncertainty_m(subject_state) > position_uncertainty_threshold_m
    )


__all__ = ["needs_active_reobservation", "position_uncertainty_m"]
