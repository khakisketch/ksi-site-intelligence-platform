"""TriageStatus 상태전이 검증 테스트 (MASTER_PRD §17.2, ADR-KSI-008 §4 2-enum 분리).

EventStatus(edge 산출물 상태)와 분리된 서버측 전용 워크플로다. 배정 이후 전이는
대응 사건의 EventStatus == CONFIRMED_EVENT 인 사건에만 허용된다(집행은 저장소
계층 — 이 모듈은 TriageStatus 값 자체의 전이 적법성만 검증한다).
"""

from __future__ import annotations

import pytest
from ksi_domain.enums import (
    _ALLOWED_TRIAGE_TRANSITIONS,  # noqa: PLC2701 -- 전이표 전수 검사를 위한 의도적 내부 접근
    IllegalTriageTransitionError,
    TriageStatus,
    assert_triage_transition,
    can_triage_transition,
)


@pytest.mark.parametrize(
    ("cur", "nxt"),
    [
        (TriageStatus.NONE, TriageStatus.ASSIGNED),
        (TriageStatus.ASSIGNED, TriageStatus.ACTION_IN_PROGRESS),
        (TriageStatus.ACTION_IN_PROGRESS, TriageStatus.REINSPECTION_REQUESTED),
        (TriageStatus.ACTION_IN_PROGRESS, TriageStatus.RESOLVED),
        (TriageStatus.REINSPECTION_REQUESTED, TriageStatus.ACTION_IN_PROGRESS),
        (TriageStatus.REINSPECTION_REQUESTED, TriageStatus.RESOLVED),
        (TriageStatus.RESOLVED, TriageStatus.CLOSED),
    ],
)
def test_legal_transition_allowed(cur: TriageStatus, nxt: TriageStatus) -> None:
    assert_triage_transition(cur, nxt)  # raise 없이 통과
    assert can_triage_transition(cur, nxt) is True


@pytest.mark.parametrize(
    ("cur", "nxt"),
    [
        # NONE 은 ASSIGNED 를 건너뛰고 진행 단계로 직행 불가
        (TriageStatus.NONE, TriageStatus.ACTION_IN_PROGRESS),
        (TriageStatus.NONE, TriageStatus.RESOLVED),
        (TriageStatus.NONE, TriageStatus.CLOSED),
        # ASSIGNED 는 ACTION_IN_PROGRESS 를 건너뛰고 RESOLVED 직행 불가
        (TriageStatus.ASSIGNED, TriageStatus.RESOLVED),
        (TriageStatus.ASSIGNED, TriageStatus.REINSPECTION_REQUESTED),
        (TriageStatus.ASSIGNED, TriageStatus.CLOSED),
        # ACTION_IN_PROGRESS 는 CLOSED 로 직행 불가 (RESOLVED 경유 필수)
        (TriageStatus.ACTION_IN_PROGRESS, TriageStatus.CLOSED),
        (TriageStatus.ACTION_IN_PROGRESS, TriageStatus.ASSIGNED),
        # REINSPECTION_REQUESTED 는 CLOSED 로 직행 불가
        (TriageStatus.REINSPECTION_REQUESTED, TriageStatus.CLOSED),
        (TriageStatus.REINSPECTION_REQUESTED, TriageStatus.ASSIGNED),
        # RESOLVED 는 진행 단계로 재오픈 불가 (CLOSED 만 허용)
        (TriageStatus.RESOLVED, TriageStatus.ACTION_IN_PROGRESS),
        (TriageStatus.RESOLVED, TriageStatus.REINSPECTION_REQUESTED),
        (TriageStatus.RESOLVED, TriageStatus.ASSIGNED),
        # CLOSED 는 종단 상태 — 어떤 재오픈도 거부
        (TriageStatus.CLOSED, TriageStatus.RESOLVED),
        (TriageStatus.CLOSED, TriageStatus.ACTION_IN_PROGRESS),
        (TriageStatus.CLOSED, TriageStatus.ASSIGNED),
        (TriageStatus.CLOSED, TriageStatus.NONE),
    ],
)
def test_illegal_transition_rejected(cur: TriageStatus, nxt: TriageStatus) -> None:
    with pytest.raises(IllegalTriageTransitionError):
        assert_triage_transition(cur, nxt)
    assert can_triage_transition(cur, nxt) is False


def test_illegal_transition_error_is_value_error() -> None:
    """assert_triage_transition 의 불법 전이 예외는 ValueError 서브클래스여야 한다."""
    with pytest.raises(ValueError):
        assert_triage_transition(TriageStatus.CLOSED, TriageStatus.RESOLVED)


def test_closed_is_terminal() -> None:
    """CLOSED 는 종단 상태 — 전이표에서 빈 set 을 가진다."""
    assert _ALLOWED_TRIAGE_TRANSITIONS[TriageStatus.CLOSED] == set()


def test_transition_table_keys_cover_every_status() -> None:
    """전이표 키 전수 == TriageStatus 전수(누락 상태 없음)."""
    assert set(_ALLOWED_TRIAGE_TRANSITIONS.keys()) == set(TriageStatus)
