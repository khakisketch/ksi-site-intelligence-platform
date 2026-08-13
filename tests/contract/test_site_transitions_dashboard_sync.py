"""Python 현장 상태 전이표 SSOT ↔ 대시보드 TS 미러 대조 (P1-3).

``packages/domain/src/ksi_domain/enums._ALLOWED_SITE_TRANSITIONS`` 가 정본이고
``apps/dashboard/src/app/sites/[siteId]/SiteTransitionActions.tsx`` 의
``ALLOWED_SITE_TRANSITIONS`` 는 그 미러다(``SiteTransitionActions.tsx:10`` 주석이
정확히 이 SSOT 를 못박아 두었지만, 이 파일 이전에는 그 약속을 강제하는 게 없었다).
서버가 최종 권위지만(전이는 서버가 재검증한다) 대시보드는 이 표로 선택지를 미리
좁힌다 — 두 표가 갈리면, 서버에만 있는 간선은 대시보드에서 영원히 버튼이 안 보이고
(정당한 전이가 막힘), 대시보드에만 있는 간선은 사용자가 눌러서 서버 409 를 받는다.

``test_site_autonomy_gate_dashboard_sync.py`` 와 동일 관습이다(TS 소스를 정규식으로
파싱해 Python SSOT 와 대조, 정본이 Python 이므로 Python 쪽에서 돌린다). SUSPENDED 는
정적 표에 간선이 없다(동적 resume 규칙 — 두 쪽 다 빈 배열/빈 집합으로 표현된다).
"""

from __future__ import annotations

import re
from itertools import product
from pathlib import Path

from ksi_domain.enums import (
    _ALLOWED_SITE_TRANSITIONS,  # noqa: PLC2701 -- 전이표 전수 대조를 위한 의도적 내부 접근
    SiteStatus,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD_ACTIONS = (
    _REPO_ROOT
    / "apps"
    / "dashboard"
    / "src"
    / "app"
    / "sites"
    / "[siteId]"
    / "SiteTransitionActions.tsx"
)

_TABLE_BLOCK = re.compile(
    r"ALLOWED_SITE_TRANSITIONS:\s*Record<SiteStatus,\s*SiteStatus\[\]>\s*=\s*\{([\s\S]*?)\n\};"
)
_ENTRY = re.compile(r"^\s*(\w+):\s*\[([^\]]*)\],?\s*$", re.MULTILINE)
_STRING_LITERAL = re.compile(r'"(\w+)"')


def _parse_allowed_transitions(source: str) -> dict[str, set[str]]:
    """``ALLOWED_SITE_TRANSITIONS`` 리터럴 → {from: {to, ...}} 집합."""
    block = _TABLE_BLOCK.search(source)
    assert block is not None, (
        "SiteTransitionActions.tsx 에서 ALLOWED_SITE_TRANSITIONS 리터럴을 찾지 "
        "못했다 — 파서가 소스 변경을 못 따라간다"
    )
    table: dict[str, set[str]] = {}
    for cur, body in _ENTRY.findall(block.group(1)):
        table[cur] = set(_STRING_LITERAL.findall(body))
    return table


def test_parser_reads_a_non_empty_table_of_valid_site_statuses() -> None:
    """공허 방지 — 파서가 실제로 뭔가를 읽었는지, 나온 값들이 진짜 SiteStatus 인지."""
    source = _DASHBOARD_ACTIONS.read_text(encoding="utf-8")
    ts_table = _parse_allowed_transitions(source)
    assert ts_table, "TS 전이표를 하나도 못 읽었다 — 파서가 깨졌다"

    known = {status.value for status in SiteStatus}
    for cur, targets in ts_table.items():
        assert cur in known, f"알 수 없는 출발 SiteStatus: {cur}"
        unknown = targets - known
        assert not unknown, f"{cur}: 알 수 없는 도착 SiteStatus {unknown}"


def test_dashboard_site_transitions_cover_every_site_status() -> None:
    """대시보드 표가 SiteStatus 10종 전부를 키로 가져야 한다(빈 배열이라도)."""
    ts_table = _parse_allowed_transitions(_DASHBOARD_ACTIONS.read_text(encoding="utf-8"))
    assert set(ts_table) == {status.value for status in SiteStatus}, (
        "대시보드 ALLOWED_SITE_TRANSITIONS 가 SiteStatus 전 멤버를 커버하지 않는다 — "
        f"새 SiteStatus 가 추가/삭제됐으면 SiteTransitionActions.tsx 도 같이 갱신하라. "
        f"대시보드 표 키: {sorted(ts_table)}"
    )


def test_dashboard_site_transitions_match_python_ssot_for_every_pair() -> None:
    """[핵심] SiteStatus 전 조합에서 두 판정이 일치해야 한다.

    갈리면 두 방향으로 실패 모드가 다르다 — 서버에만 있는 간선은 대시보드가
    영원히 숨기고(정당한 전이가 UI 에서 막힘), 대시보드에만 있는 간선은 사용자가
    눌러서 서버 409(IllegalSiteTransitionError)를 받는다(입력을 잃는다).
    """
    ts_table = _parse_allowed_transitions(_DASHBOARD_ACTIONS.read_text(encoding="utf-8"))

    mismatches: list[str] = []
    for cur, nxt in product(SiteStatus, SiteStatus):
        py_allowed = nxt in _ALLOWED_SITE_TRANSITIONS.get(cur, set())
        ts_allowed = nxt.value in ts_table.get(cur.value, set())
        if py_allowed != ts_allowed:
            mismatches.append(
                f"{cur.value}->{nxt.value}: 서버(SSOT)={py_allowed} / 대시보드={ts_allowed}"
            )

    assert not mismatches, (
        "대시보드 SiteTransitionActions.tsx 의 ALLOWED_SITE_TRANSITIONS 가 서버 SSOT"
        f"(enums._ALLOWED_SITE_TRANSITIONS) 와 갈라졌다 — 구현을 바꿨으면 미러도 같이 "
        f"바꿔라: {mismatches}"
    )


def test_suspended_has_no_static_outgoing_edge_on_either_side() -> None:
    """회귀 방지 — SUSPENDED 이탈은 동적 resume 규칙이지 정적 표 간선이 아니다.

    양쪽 다 SUSPENDED 키가 빈 집합/빈 배열이어야 한다. 여기에 정적 간선이 하나라도
    생기면 저장소가 기억한 진입 직전 상태 이외의 목적지로 "우회 복귀"가 열린다.
    """
    ts_table = _parse_allowed_transitions(_DASHBOARD_ACTIONS.read_text(encoding="utf-8"))

    assert _ALLOWED_SITE_TRANSITIONS[SiteStatus.SUSPENDED] == set(), (
        "서버 SSOT 에 SUSPENDED 발 정적 간선이 생겼다 — resume 은 동적 규칙이어야 한다"
    )
    assert ts_table[SiteStatus.SUSPENDED.value] == set(), (
        "대시보드 표에 SUSPENDED 발 정적 간선이 생겼다 — resume 은 동적 규칙이어야 한다"
    )
