"""Python 자율승인 게이트 SSOT ↔ 대시보드 TS 미러 대조 (ADR-KSI-015 D2).

``packages/domain/src/ksi_domain/enums.requires_autonomy_approval`` 가 정본이고
``apps/dashboard/src/lib/core-api/siteAutonomyGate.ts`` 는 그 미러다. 서버가 최종
권위지만(403 은 서버가 검사한다) 대시보드는 관리자 전용 대상을 **미리 숨겨** 서버
403 을 마지막 단계에서 만나지 않게 한다 — 두 판정이 갈리면 그 목적이 깨진다.

``test_mission_site_status_gate_dashboard_sync.py`` 와 동일 관습이다(TS 소스를
정규식으로 파싱해 Python SSOT 와 대조, 정본이 Python 이므로 Python 쪽에서 돌린다).

**간선 쌍 기준을 대조한다.** 목적지 상태만 비교하면 이 게이트에서 가장 틀리기 쉬운
지점(``PATROL_ACTIVE → PATROL_READY`` 순찰 복귀가 관리자 전용으로 잘못 막히는 것)을
그대로 통과시킨다 — 그래서 SiteStatus 전 조합을 전수 대조한다.
"""

from __future__ import annotations

import re
from itertools import product
from pathlib import Path

from ksi_domain.enums import SiteStatus, requires_autonomy_approval

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD_GATE = (
    _REPO_ROOT / "apps" / "dashboard" / "src" / "lib" / "core-api" / "siteAutonomyGate.ts"
)

_GATED_SET_BLOCK = re.compile(
    r"AUTONOMY_APPROVAL_GATED_TRANSITIONS:\s*ReadonlySet<string>\s*=\s*new Set\(\[([\s\S]*?)\]\);"
)
_EDGE_LITERAL = re.compile(r'"(\w+)->(\w+)"')
# TS 미러가 SUSPENDED 두 갈래를 정적 표 밖에서 따로 처리한다는 사실 자체도 대조
# 대상이다 — 이 분기를 지우면 운영중단이 아무나 누를 수 있게 되는데 정적 표 대조만
# 해서는 드러나지 않는다.
_SUSPENDED_BRANCH = re.compile(
    r'if\s*\(\s*nxt\s*===\s*"SUSPENDED"\s*\|\|\s*cur\s*===\s*"SUSPENDED"\s*\)\s*return true;'
)


def _parse_gated_edges(source: str) -> set[tuple[str, str]]:
    """``AUTONOMY_APPROVAL_GATED_TRANSITIONS`` 리터럴 → {(from, to)} 집합."""
    block = _GATED_SET_BLOCK.search(source)
    assert block is not None, (
        "siteAutonomyGate.ts 에서 AUTONOMY_APPROVAL_GATED_TRANSITIONS 리터럴을 찾지 "
        "못했다 — 파서가 소스 변경을 못 따라간다"
    )
    return set(_EDGE_LITERAL.findall(block.group(1)))


def _ts_requires_autonomy_approval(
    cur: SiteStatus, nxt: SiteStatus, *, gated: set[tuple[str, str]], has_suspended_branch: bool
) -> bool:
    """TS 미러의 판정 로직을 그대로 재현한다(세 갈래)."""
    if has_suspended_branch and (
        nxt is SiteStatus.SUSPENDED or cur is SiteStatus.SUSPENDED
    ):
        return True
    return (cur.value, nxt.value) in gated


def test_parser_reads_a_non_empty_edge_set_of_valid_site_statuses() -> None:
    """공허 방지 — 파서가 실제로 뭔가를 읽었는지, 나온 값들이 진짜 SiteStatus 인지."""
    edges = _parse_gated_edges(_DASHBOARD_GATE.read_text(encoding="utf-8"))
    assert edges, "TS 간선 집합을 하나도 못 읽었다 — 파서가 깨졌다"

    known = {status.value for status in SiteStatus}
    for cur, nxt in edges:
        assert cur in known, f"알 수 없는 출발 SiteStatus: {cur}"
        assert nxt in known, f"알 수 없는 도착 SiteStatus: {nxt}"


def test_dashboard_mirror_keeps_the_suspended_branch() -> None:
    """SUSPENDED 두 갈래는 정적 표 밖 분기다 — 지워지면 정적 표 대조로는 안 잡힌다."""
    source = _DASHBOARD_GATE.read_text(encoding="utf-8")
    assert _SUSPENDED_BRANCH.search(source) is not None, (
        "siteAutonomyGate.ts 의 SUSPENDED 분기(`nxt === \"SUSPENDED\" || cur === "
        '"SUSPENDED"`)가 사라졌다 — 운영중단 진입·복귀가 관리자 전용에서 풀린다'
    )


def test_dashboard_autonomy_gate_matches_python_ssot_for_every_transition() -> None:
    """[핵심] SiteStatus 전 조합에서 두 판정이 일치해야 한다.

    갈리면 두 방향으로 실패 모드가 다르다 — 대시보드가 더 허용적이면 현장운영자에게
    선택지를 보여주고 서버가 403 으로 거부하고(사용자가 입력을 잃는다), 대시보드가
    더 보수적이면 서버는 허용하는데 UI 가 조용히 선택지를 숨긴다(정당한 작업이
    막힌다 — ``PATROL_ACTIVE → PATROL_READY`` 순찰 복귀가 정확히 이 경우다).
    """
    source = _DASHBOARD_GATE.read_text(encoding="utf-8")
    gated = _parse_gated_edges(source)
    has_suspended_branch = _SUSPENDED_BRANCH.search(source) is not None

    mismatches: list[str] = []
    for cur, nxt in product(SiteStatus, SiteStatus):
        py = requires_autonomy_approval(cur, nxt)
        ts = _ts_requires_autonomy_approval(
            cur, nxt, gated=gated, has_suspended_branch=has_suspended_branch
        )
        if py != ts:
            mismatches.append(
                f"{cur.value}->{nxt.value}: 서버(SSOT)={py} / 대시보드={ts}"
            )

    assert not mismatches, (
        "대시보드 siteAutonomyGate.ts 가 서버 SSOT(enums.requires_autonomy_approval) 와 "
        f"갈라졌다 — 구현을 바꿨으면 미러도 같이 바꿔라: {mismatches}"
    )


def test_patrol_return_is_not_gated_in_either_side() -> None:
    """회귀 방지 — 이 게이트에서 가장 틀리기 쉬운 간선을 이름으로 못박는다.

    ``PATROL_READY`` 로 들어오는 정적 간선이 둘이라(정식 승인·순찰 복귀) 목적지
    상태만 보고 가르면 순찰이 끝날 때마다 관리자를 기다리게 된다. 전수 대조가 이미
    덮지만, 그 사실이 실패 메시지에서 바로 보이도록 별도 테스트로 남긴다.
    """
    source = _DASHBOARD_GATE.read_text(encoding="utf-8")
    gated = _parse_gated_edges(source)
    has_suspended_branch = _SUSPENDED_BRANCH.search(source) is not None

    assert not requires_autonomy_approval(SiteStatus.PATROL_ACTIVE, SiteStatus.PATROL_READY), (
        "PATROL_ACTIVE->PATROL_READY(순찰 후 복귀)가 서버에서 관리자 전용이 됐다"
    )
    assert not _ts_requires_autonomy_approval(
        SiteStatus.PATROL_ACTIVE,
        SiteStatus.PATROL_READY,
        gated=gated,
        has_suspended_branch=has_suspended_branch,
    ), "PATROL_ACTIVE->PATROL_READY(순찰 후 복귀)가 대시보드에서 관리자 전용이 됐다"

    # 대칭 확인 — 같은 목적지의 다른 간선은 양쪽 모두 게이트되어야 한다.
    assert requires_autonomy_approval(
        SiteStatus.PROVISIONAL_AUTONOMY, SiteStatus.PATROL_READY
    ), "PROVISIONAL_AUTONOMY->PATROL_READY(정식 순찰 승인)가 게이트에서 풀렸다"
    assert _ts_requires_autonomy_approval(
        SiteStatus.PROVISIONAL_AUTONOMY,
        SiteStatus.PATROL_READY,
        gated=gated,
        has_suspended_branch=has_suspended_branch,
    ), "대시보드에서 PROVISIONAL_AUTONOMY->PATROL_READY 가 게이트에서 풀렸다"
