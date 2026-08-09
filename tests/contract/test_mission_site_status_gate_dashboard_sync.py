"""Python 게이트 SSOT ↔ 대시보드 TS 미러 대조 (독립 재검토 D6, ADR-KSI-014 D4).

``packages/domain/src/ksi_domain/mission_gating.MISSION_TYPE_ALLOWED_SITE_STATUSES``
가 정본이고 ``apps/dashboard/src/lib/core-api/missionSiteGate.ts`` 는 그 미러다
(ADR-KSI-014 D4 — "표가 갈리면 대시보드가 '발급 가능'이라 보여준 것을 서버가
409로 거부하는 회귀가 가능하다", "이중유지 리스크: 자동 대조 게이트는 이번
범위에 없다"). 이 파일이 그 자동 대조 게이트다.

``tests/contract/test_api_contract_sync.py`` 의 ``test_dashboard_types_match_
contract_schemas``(TS 소스를 정규식으로 파싱해 Python 값과 대조)와 동일 관습을
재사용한다 — 정본이 Python(도메인 패키지)이므로 Python 쪽에서 돌린다(그 파일이
이미 이 저장소 전체에서 "TS 를 파싱해 Python SSOT 와 대조"를 채택한 선례다).
"""

from __future__ import annotations

import re
from pathlib import Path

from ksi_domain.enums import MissionType, SiteStatus
from ksi_domain.mission_gating import MISSION_TYPE_ALLOWED_SITE_STATUSES

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD_GATE = (
    _REPO_ROOT / "apps" / "dashboard" / "src" / "lib" / "core-api" / "missionSiteGate.ts"
)

_CONST_ARRAY = re.compile(r"const (\w+): readonly SiteStatus\[\]\s*=\s*\[([^\]]*)\];")
_STRING_LITERAL = re.compile(r'"(\w+)"')
_TABLE_BLOCK = re.compile(
    r"MISSION_TYPE_ALLOWED_SITE_STATUSES:\s*Record<MissionType,\s*readonly SiteStatus\[\]>"
    r"\s*=\s*\{([\s\S]*?)\n\};"
)
_TABLE_ENTRY = re.compile(r"^\s*(\w+):\s*(\[[^\]]*\]|\w+),?\s*$", re.MULTILINE)


def _parse_named_arrays(source: str) -> dict[str, set[str]]:
    """``const NAME: readonly SiteStatus[] = [...]`` 선언들 → {NAME: 값 집합}."""
    return {name: set(_STRING_LITERAL.findall(body)) for name, body in _CONST_ARRAY.findall(source)}


def _parse_gate_table(source: str) -> dict[str, set[str]]:
    """``MISSION_TYPE_ALLOWED_SITE_STATUSES`` 리터럴을 {missionType: 허용 상태 집합}로.

    각 값은 named 배열 참조(``AUTONOMOUS_READY`` 처럼 그 식별자 하나) 또는 인라인
    배열(문자열 리터럴·``...NAME`` 스프레드 혼합, 예: ``UNIFIED_SITE_SURVEY``)이다.
    """
    named = _parse_named_arrays(source)
    table_match = _TABLE_BLOCK.search(source)
    assert table_match is not None, "MISSION_TYPE_ALLOWED_SITE_STATUSES 리터럴을 찾지 못했다"

    table: dict[str, set[str]] = {}
    for mission_type, value in _TABLE_ENTRY.findall(table_match.group(1)):
        value = value.strip()
        if not value.startswith("["):
            table[mission_type] = named[value]
            continue
        values: set[str] = set()
        for token in value.strip("[]").split(","):
            token = token.strip()
            if not token:
                continue
            if token.startswith("..."):
                values |= named[token.removeprefix("...")]
            else:
                literal = _STRING_LITERAL.match(token)
                assert literal is not None, f"파싱 불가 토큰: {token!r}"
                values.add(literal.group(1))
        table[mission_type] = values
    return table


def test_parser_reads_a_non_empty_table_of_valid_site_statuses() -> None:
    """공허 방지 — 파서가 실제로 뭔가를 읽었는지, 나온 값들이 진짜 SiteStatus 인지."""
    source = _DASHBOARD_GATE.read_text(encoding="utf-8")
    ts_table = _parse_gate_table(source)
    assert ts_table, "TS 표를 하나도 못 읽었다 — 파서가 깨졌다(정규식이 소스 변경을 못 따라감)"

    known = {status.value for status in SiteStatus}
    for mission_type, values in ts_table.items():
        assert values, f"{mission_type} 의 허용 상태 집합이 비어 있다 — 파싱 실패 의심"
        unknown = values - known
        assert not unknown, f"{mission_type}: 알 수 없는 SiteStatus 값 {unknown}"


def test_dashboard_mission_site_gate_matches_python_ssot() -> None:
    """[핵심] 대시보드 미러 표가 Python SSOT 와 MissionType 8종 전수 일치해야 한다.

    갈리면 두 방향으로 실패 모드가 갈린다 — 대시보드가 더 허용적이면 위저드가
    "발급 가능"이라 보여준 것을 서버가 409 로 거부하고(사용자가 이미 채운 입력을
    잃는다), 대시보드가 더 보수적이면 서버는 허용하는데 위저드가 조용히 선택지를
    숨긴다(정당한 작업이 UI 에서 막힌다).
    """
    ts_table = _parse_gate_table(_DASHBOARD_GATE.read_text(encoding="utf-8"))

    assert set(ts_table) == {mt.value for mt in MissionType}, (
        "대시보드 표가 MissionType 전 멤버를 커버하지 않는다 — 새 MissionType 이 "
        f"추가됐으면 missionSiteGate.ts 도 같이 갱신하라. 대시보드 표: {sorted(ts_table)}"
    )

    mismatches: list[str] = []
    for mission_type, py_allowed in MISSION_TYPE_ALLOWED_SITE_STATUSES.items():
        py_values = {status.value for status in py_allowed}
        ts_values = ts_table[mission_type.value]
        if py_values != ts_values:
            mismatches.append(
                f"{mission_type.value}: 서버(SSOT)에만 {sorted(py_values - ts_values)} / "
                f"대시보드에만 {sorted(ts_values - py_values)}"
            )

    assert not mismatches, (
        "대시보드 missionSiteGate.ts 가 서버 SSOT(mission_gating.py) 와 갈라졌다 — "
        f"ADR-KSI-014 D4 이중유지 리스크가 실현됐다(구현을 바꿨으면 미러도 같이 "
        f"바꿔라): {mismatches}"
    )
