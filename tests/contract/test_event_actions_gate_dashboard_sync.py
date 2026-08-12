"""Python 이벤트/트리아지 전이표 SSOT ↔ EventActions.tsx 버튼 노출 판정 대조 (P1-3).

``packages/domain/src/ksi_domain/enums`` 의 ``_ALLOWED_EVENT_TRANSITIONS``/
``_ALLOWED_TRIAGE_TRANSITIONS`` 가 정본이고
``apps/dashboard/src/app/events/[eventKey]/EventActions.tsx`` 의
``CONFIRMABLE_EVENT_STATUSES``/``ASSIGNABLE_TRIAGE_STATUSES`` 는 그 미러다.

이 파일은 원래 ``canConfirm = status === "FINDING"`` / ``canAssign = status ===
"CONFIRMED_EVENT" && triage === "NONE"`` 처럼 불리언 식으로 흩어져 있었다 — 정규식
대조가 안정적이려면 표(집합 리터럴) 형태가 필요해서 먼저 그렇게 정리한 뒤 이 게이트를
추가했다(정리 전후로 판정 결과는 동일함을 별도로 확인함 — EventStatus × TriageStatus
전 조합에서 두 집합이 각각 싱글턴이라 표현만 바뀌었을 뿐 동작은 그대로다).

``CONFIRMABLE_EVENT_STATUSES`` = "CONFIRMED_EVENT 로 전이 가능한 EventStatus 집합"
(``_ALLOWED_EVENT_TRANSITIONS`` 에서 유도). ``ASSIGNABLE_TRIAGE_STATUSES`` =
"ASSIGNED 로 전이 가능한 TriageStatus 집합"(``_ALLOWED_TRIAGE_TRANSITIONS`` 에서
유도). ``ASSIGNABLE_EVENT_STATUS``(CONFIRMED_EVENT 사건만 배정 허용)는 enums.py 의
단일 전이표가 아니라 events.py 의 EventStatus·TriageStatus 결합 규칙이라 이 게이트의
대조 대상이 아니다(그 규칙은 store 계층 소관).

``test_site_autonomy_gate_dashboard_sync.py`` 와 동일 관습이다.
"""

from __future__ import annotations

import re
from pathlib import Path

from ksi_domain.enums import (
    _ALLOWED_EVENT_TRANSITIONS,  # noqa: PLC2701 -- 전이표 전수 대조를 위한 의도적 내부 접근
    _ALLOWED_TRIAGE_TRANSITIONS,  # noqa: PLC2701 -- 전이표 전수 대조를 위한 의도적 내부 접근
    EventStatus,
    TriageStatus,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EVENT_ACTIONS = (
    _REPO_ROOT / "apps" / "dashboard" / "src" / "app" / "events" / "[eventKey]" / "EventActions.tsx"
)

_STRING_LITERAL = re.compile(r'"(\w+)"')


def _parse_readonly_set(source: str, *, const_name: str, ts_type: str) -> set[str]:
    """``const NAME: ReadonlySet<TYPE> = new Set([...]);`` 리터럴 → 값 집합."""
    pattern = re.compile(
        rf"{const_name}:\s*ReadonlySet<{ts_type}>\s*=\s*new Set\(\[([^\]]*)\]\);"
    )
    match = pattern.search(source)
    assert match is not None, (
        f"EventActions.tsx 에서 {const_name} 리터럴을 찾지 못했다 — "
        "파서가 소스 변경을 못 따라간다"
    )
    return set(_STRING_LITERAL.findall(match.group(1)))


def test_parser_reads_both_sets_non_empty_and_valid() -> None:
    """공허 방지 — 파서가 두 집합을 실제로 읽었는지, 값들이 진짜 Enum 멤버인지."""
    source = _EVENT_ACTIONS.read_text(encoding="utf-8")
    confirmable = _parse_readonly_set(
        source, const_name="CONFIRMABLE_EVENT_STATUSES", ts_type="EventStatus"
    )
    assignable = _parse_readonly_set(
        source, const_name="ASSIGNABLE_TRIAGE_STATUSES", ts_type="TriageStatus"
    )
    assert confirmable, "CONFIRMABLE_EVENT_STATUSES 를 하나도 못 읽었다 — 파서가 깨졌다"
    assert assignable, "ASSIGNABLE_TRIAGE_STATUSES 를 하나도 못 읽었다 — 파서가 깨졌다"

    known_events = {status.value for status in EventStatus}
    known_triage = {status.value for status in TriageStatus}
    assert confirmable <= known_events, f"알 수 없는 EventStatus: {confirmable - known_events}"
    assert assignable <= known_triage, f"알 수 없는 TriageStatus: {assignable - known_triage}"


def test_confirmable_event_statuses_match_python_ssot() -> None:
    """[핵심] '확정 버튼을 보이는 상태' 집합이 CONFIRMED_EVENT 로 전이 가능한
    EventStatus 집합(서버 SSOT)과 정확히 일치해야 한다.

    갈리면 두 방향으로 실패 모드가 다르다 — 대시보드가 더 허용적이면 사용자가
    확정을 눌러 서버 409(IllegalEventTransitionError)를 받고, 더 보수적이면 정당한
    확정이 버튼 자체가 없어 막힌다.
    """
    source = _EVENT_ACTIONS.read_text(encoding="utf-8")
    ts_confirmable = _parse_readonly_set(
        source, const_name="CONFIRMABLE_EVENT_STATUSES", ts_type="EventStatus"
    )

    mismatches: list[str] = []
    for status in EventStatus:
        py_confirmable = EventStatus.CONFIRMED_EVENT in _ALLOWED_EVENT_TRANSITIONS.get(
            status, set()
        )
        ts_result = status.value in ts_confirmable
        if py_confirmable != ts_result:
            mismatches.append(f"{status.value}: 서버(SSOT)={py_confirmable} / 대시보드={ts_result}")

    assert not mismatches, (
        "대시보드 EventActions.tsx 의 CONFIRMABLE_EVENT_STATUSES 가 서버 SSOT"
        f"(enums._ALLOWED_EVENT_TRANSITIONS) 와 갈라졌다 — 구현을 바꿨으면 미러도 같이 "
        f"바꿔라: {mismatches}"
    )


def test_assignable_triage_statuses_match_python_ssot() -> None:
    """[핵심] '배정 패널을 보이는 트리아지 상태' 집합이 ASSIGNED 로 전이 가능한
    TriageStatus 집합(서버 SSOT)과 정확히 일치해야 한다.

    갈리면 대시보드가 더 허용적일 때 사용자가 배정을 눌러 서버
    409(IllegalTriageTransitionError)를 받고, 더 보수적이면 정당한 배정이 패널
    자체가 없어 막힌다.
    """
    source = _EVENT_ACTIONS.read_text(encoding="utf-8")
    ts_assignable = _parse_readonly_set(
        source, const_name="ASSIGNABLE_TRIAGE_STATUSES", ts_type="TriageStatus"
    )

    mismatches: list[str] = []
    for status in TriageStatus:
        py_assignable = TriageStatus.ASSIGNED in _ALLOWED_TRIAGE_TRANSITIONS.get(status, set())
        ts_result = status.value in ts_assignable
        if py_assignable != ts_result:
            mismatches.append(f"{status.value}: 서버(SSOT)={py_assignable} / 대시보드={ts_result}")

    assert not mismatches, (
        "대시보드 EventActions.tsx 의 ASSIGNABLE_TRIAGE_STATUSES 가 서버 SSOT"
        f"(enums._ALLOWED_TRIAGE_TRANSITIONS) 와 갈라졌다 — 구현을 바꿨으면 미러도 같이 "
        f"바꿔라: {mismatches}"
    )
