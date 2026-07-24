"""EventStatus 상태전이 검증 테스트 (INV-031, P0-1/P0-6 강제 지점).

Detector 결과(cur=None)는 OBSERVATION으로만 진입할 수 있고, CONFIRMED_EVENT로
직행할 수 없다. DISMISSED/CONFIRMED_EVENT는 이 스키마 범위(v1.1)에서 종단 상태다.
"""

from __future__ import annotations

import pytest
from ksi_domain.enums import (
    EventStatus,
    IllegalEventTransitionError,
    assert_event_transition,
    can_event_transition,
)


@pytest.mark.parametrize(
    ("cur", "nxt"),
    [
        (None, EventStatus.OBSERVATION),
        (EventStatus.OBSERVATION, EventStatus.CANDIDATE),
        (EventStatus.OBSERVATION, EventStatus.DISMISSED),
        (EventStatus.CANDIDATE, EventStatus.EVIDENCE_COLLECTION),
        (EventStatus.CANDIDATE, EventStatus.DISMISSED),
        (EventStatus.EVIDENCE_COLLECTION, EventStatus.FINDING),
        (EventStatus.EVIDENCE_COLLECTION, EventStatus.DISMISSED),
        (EventStatus.EVIDENCE_COLLECTION, EventStatus.UNRESOLVED),
        (EventStatus.FINDING, EventStatus.CONFIRMED_EVENT),
        (EventStatus.FINDING, EventStatus.DISMISSED),
        (EventStatus.FINDING, EventStatus.UNRESOLVED),
        (EventStatus.UNRESOLVED, EventStatus.CANDIDATE),
    ],
)
def test_legal_transition_allowed(cur: EventStatus | None, nxt: EventStatus) -> None:
    assert_event_transition(cur, nxt)  # raise 없이 통과
    assert can_event_transition(cur, nxt) is True


@pytest.mark.parametrize(
    ("cur", "nxt"),
    [
        # Detector 결과가 CONFIRMED로 직행 불가 (INV-031)
        (None, EventStatus.CONFIRMED_EVENT),
        (None, EventStatus.CANDIDATE),
        # OBSERVATION → CONFIRMED_EVENT 직행 불가
        (EventStatus.OBSERVATION, EventStatus.CONFIRMED_EVENT),
        (EventStatus.OBSERVATION, EventStatus.FINDING),
        # DISMISSED → CANDIDATE 재오픈 불가 (종단 상태)
        (EventStatus.DISMISSED, EventStatus.CANDIDATE),
        (EventStatus.DISMISSED, EventStatus.OBSERVATION),
        # CONFIRMED_EVENT 는 종단 상태
        (EventStatus.CONFIRMED_EVENT, EventStatus.DISMISSED),
        (EventStatus.CONFIRMED_EVENT, EventStatus.UNRESOLVED),
        # CANDIDATE → FINDING 단계 건너뛰기 불가
        (EventStatus.CANDIDATE, EventStatus.FINDING),
        (EventStatus.CANDIDATE, EventStatus.CONFIRMED_EVENT),
        # UNRESOLVED 는 CANDIDATE 로만 복귀 (EVIDENCE_COLLECTION 직행 불가)
        (EventStatus.UNRESOLVED, EventStatus.EVIDENCE_COLLECTION),
        (EventStatus.UNRESOLVED, EventStatus.CONFIRMED_EVENT),
    ],
)
def test_illegal_transition_rejected(cur: EventStatus | None, nxt: EventStatus) -> None:
    with pytest.raises(IllegalEventTransitionError):
        assert_event_transition(cur, nxt)
    assert can_event_transition(cur, nxt) is False


def test_illegal_transition_error_is_value_error() -> None:
    """assert_event_transition 의 불법 전이 예외는 ValueError 서브클래스여야 한다."""
    with pytest.raises(ValueError):
        assert_event_transition(EventStatus.DISMISSED, EventStatus.CANDIDATE)
