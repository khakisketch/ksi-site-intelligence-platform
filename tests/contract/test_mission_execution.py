"""임무 실행 생애주기 — 전이표 (ADR-KSI-019 G2).

``MissionRecord`` 는 **발급 기록**이라 "이 임무가 실제로 날았는가"에 답하지 못했다.
이 파일은 그 축의 전이 규칙을 고정한다 — 저장소·API·훅은 같은 파일 뒤쪽에서 이어
검증한다.
"""

from __future__ import annotations

import pytest
from ksi_domain.enums import (
    _ALLOWED_MISSION_EXECUTION_TRANSITIONS,  # noqa: PLC2701 -- 전이표 전수 검사를 위한 의도적 내부 접근
    IllegalMissionExecutionTransitionError,
    MissionExecutionStatus,
    assert_mission_execution_transition,
    can_mission_execution_transition,
)

_ME = MissionExecutionStatus


@pytest.mark.parametrize(
    ("cur", "nxt"),
    [
        (_ME.ISSUED, _ME.DISPATCHED),
        (_ME.DISPATCHED, _ME.ACTIVATED),
        (_ME.ACTIVATED, _ME.COMPLETED),
        (_ME.ACTIVATED, _ME.ENDED_INCOMPLETE),
    ],
)
def test_forward_path_is_allowed(
    cur: MissionExecutionStatus, nxt: MissionExecutionStatus
) -> None:
    assert_mission_execution_transition(cur, nxt)
    assert can_mission_execution_transition(cur, nxt) is True


def test_skipping_forward_is_allowed() -> None:
    """[핵심] 중간 단계를 건너뛴 완료 보고를 거부하지 않는다.

    운영자가 KMZ 를 손으로 옮겨 날린 임무는 DISPATCHED·ACTIVATED 신호가 아예 없다
    (ADR-KSI-019 G3 — 실기 확인 전까지 수동 이관이 공식 경로). 그 임무의 커버리지
    보고를 실행 상태 때문에 거부하면 INV-010 의 완료 판정 권위가 이 필드로 넘어간다.
    """
    assert_mission_execution_transition(_ME.ISSUED, _ME.COMPLETED)
    assert_mission_execution_transition(_ME.ISSUED, _ME.ENDED_INCOMPLETE)
    assert_mission_execution_transition(_ME.ISSUED, _ME.ACTIVATED)
    assert_mission_execution_transition(_ME.DISPATCHED, _ME.COMPLETED)


@pytest.mark.parametrize(
    ("cur", "nxt"),
    [
        (_ME.ACTIVATED, _ME.DISPATCHED),
        (_ME.DISPATCHED, _ME.ISSUED),
        (_ME.COMPLETED, _ME.ACTIVATED),
        (_ME.COMPLETED, _ME.DISPATCHED),
        (_ME.ENDED_INCOMPLETE, _ME.ISSUED),
    ],
)
def test_backward_transition_is_refused(
    cur: MissionExecutionStatus, nxt: MissionExecutionStatus
) -> None:
    """뒤로 가는 전이는 없다 — 관측된 사실을 되돌리지 않는다."""
    with pytest.raises(IllegalMissionExecutionTransitionError):
        assert_mission_execution_transition(cur, nxt)
    assert can_mission_execution_transition(cur, nxt) is False


def test_completion_states_may_correct_each_other() -> None:
    """[핵심] COMPLETED ↔ ENDED_INCOMPLETE 는 양방향이다.

    완료 판정의 권위는 CoverageReport 원장이고(INV-010) 이 필드는 그 원장의
    **투영**이다. 나중에 접수된 보고가 결론을 바꾸면 투영도 따라가야 한다 —
    따라가지 않으면 두 표면이 서로 다른 완료를 말한다.
    """
    assert_mission_execution_transition(_ME.COMPLETED, _ME.ENDED_INCOMPLETE)
    assert_mission_execution_transition(_ME.ENDED_INCOMPLETE, _ME.COMPLETED)


def test_cancelled_is_terminal() -> None:
    """사람이 접은 임무를 시스템 신호가 되살리지 않는다."""
    for nxt in MissionExecutionStatus:
        assert can_mission_execution_transition(_ME.CANCELLED, nxt) is False


def test_completion_states_cannot_be_cancelled() -> None:
    """이미 끝난 비행을 취소할 수 없다 — 취소는 아직 안 끝난 임무에만 뜻이 있다."""
    for cur in (_ME.COMPLETED, _ME.ENDED_INCOMPLETE):
        assert can_mission_execution_transition(cur, _ME.CANCELLED) is False


def test_self_transition_is_refused() -> None:
    """같은 상태로의 전이는 없다 — 중복 신호가 원장에 빈 레코드를 쌓지 않는다."""
    for status in MissionExecutionStatus:
        assert can_mission_execution_transition(status, status) is False


def test_transition_table_covers_every_member() -> None:
    """표 완전성 — 새 멤버가 추가됐는데 표를 안 고치면 여기서 드러난다."""
    assert set(_ALLOWED_MISSION_EXECUTION_TRANSITIONS) == set(MissionExecutionStatus)


def test_in_flight_status_does_not_exist() -> None:
    """[핵심] 서버가 모르는 사실을 상태로 만들지 않는다.

    KSI 는 비행 중 텔레메트리를 받지 않는다(INV-001). "지금 날고 있다"는 서버가
    아는 사실이 아니므로 그 이름의 상태를 두지 않는다 — 두면 화면이 그 값을
    사실처럼 보여줄 자리가 생긴다.
    """
    assert not any("FLIGHT" in member.value for member in MissionExecutionStatus)
    assert not any("FLYING" in member.value for member in MissionExecutionStatus)
