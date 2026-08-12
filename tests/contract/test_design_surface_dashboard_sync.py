"""설계 기준면 상태·거부 사유 SSOT ↔ 대시보드 미러 대조 (M4-A 9단계).

정본은 두 곳이다:

- ``ksi_event_contracts.design_surface.DesignSurfaceStatus`` — 자산의 생애 4상태
- ``ksi_core.design_surfaces.DesignSurfaceRejectionReason`` — 거부 사유 8종

미러는 ``apps/dashboard`` 의 ``types.ts``(``as const`` 값 배열)와
``labels.ts``(한국어 문구 표)다. 관습은 ``test_domain_enums_dashboard_sync.py`` ·
``test_site_transitions_dashboard_sync.py`` 와 같다 — TS 소스를 정규식으로 파싱해
Python SSOT 와 대조하고, 정본이 Python 이므로 Python 쪽에서 돌린다.

**갈렸을 때 무슨 일이 일어나는가.** 서버에만 있는 값은 화면에서 빈 칸이나 raw
코드로 뜬다 — 사용자는 설계면이 왜 거부됐는지 알 길이 없고, 고쳐 올릴 방법도
모른 채 막힌다(이 기능에서 가장 나쁜 실패다: 파일은 이미 올라갔고 되돌릴 수도
없다). 대시보드에만 있는 값은 영원히 도달하지 않는 죽은 문구다.

TS 쪽 완전성(Record 의 키 누락)은 tsc 가 잡지만, tsc 는 **enum 값 자체가 서버와
같은지**는 모른다 — 그 빈틈이 이 파일의 자리다.
"""

from __future__ import annotations

import re
from pathlib import Path

from ksi_core.design_surfaces import DesignSurfaceRejectionReason
from ksi_event_contracts.design_surface import DesignSurfaceStatus

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD = _REPO_ROOT / "apps" / "dashboard" / "src" / "lib" / "core-api"
_TYPES_TS = _DASHBOARD / "types.ts"
_LABELS_TS = _DASHBOARD / "labels.ts"

_CONST_ARRAY = re.compile(r"export const (\w+) = \[([^\]]*)\] as const;")
_STRING_LITERAL = re.compile(r'"(\w+)"')

#: ``export const X: Record<...> = { KEY: ..., }`` 블록의 최상위 키를 읽는다.
#: 값이 객체든 문자열이든 상관없이 **키만** 본다 — 문구의 내용은 사람이 정하고,
#: 이 게이트가 강제하는 것은 "빠진 것이 없는가"다.
_LABEL_BLOCK = re.compile(r"export const (\w+): Record<[^=]*=\s*\{(.*?)\n\};", re.DOTALL)
_TOP_LEVEL_KEY = re.compile(r"^  \"?([A-Z][A-Z0-9_]*)\"?:", re.MULTILINE)


def _parse_const_arrays(source: str) -> dict[str, set[str]]:
    return {name: set(_STRING_LITERAL.findall(body)) for name, body in _CONST_ARRAY.findall(source)}


def _parse_label_keys(source: str) -> dict[str, set[str]]:
    return {name: set(_TOP_LEVEL_KEY.findall(body)) for name, body in _LABEL_BLOCK.findall(source)}


def test_parser_reads_both_arrays_and_both_label_tables() -> None:
    """공허 방지 — 파서가 네 구조를 전부 찾았고 비어 있지 않은지.

    이 테스트가 없으면 소스 형태가 바뀌어 파서가 아무것도 못 읽는 순간 아래
    대조들이 전부 조용히 통과한다(빈 집합끼리는 항상 같다).
    """
    arrays = _parse_const_arrays(_TYPES_TS.read_text(encoding="utf-8"))
    labels = _parse_label_keys(_LABELS_TS.read_text(encoding="utf-8"))
    for name in ("DESIGN_SURFACE_STATUSES", "DESIGN_SURFACE_REJECTION_REASONS"):
        assert arrays.get(name), f"types.ts 에서 {name} `as const` 배열을 읽지 못했다"
    for name in ("DESIGN_SURFACE_STATUS_LABEL", "DESIGN_SURFACE_REJECTION_LABEL"):
        assert labels.get(name), f"labels.ts 에서 {name} 표를 읽지 못했다"


def test_dashboard_design_surface_status_values_match_ssot() -> None:
    """[핵심] 상태 4종의 값 집합이 계약 SSOT 와 정확히 일치해야 한다."""
    arrays = _parse_const_arrays(_TYPES_TS.read_text(encoding="utf-8"))
    py_values = {member.value for member in DesignSurfaceStatus}
    ts_values = arrays["DESIGN_SURFACE_STATUSES"]
    assert py_values == ts_values, (
        "설계면 상태가 갈라졌다 — 서버(SSOT)에만 "
        f"{sorted(py_values - ts_values)} / 대시보드에만 {sorted(ts_values - py_values)}"
    )


def test_dashboard_rejection_reason_values_match_ssot() -> None:
    """[핵심] 거부 사유 8종의 값 집합이 Core SSOT 와 정확히 일치해야 한다."""
    arrays = _parse_const_arrays(_TYPES_TS.read_text(encoding="utf-8"))
    py_values = {member.value for member in DesignSurfaceRejectionReason}
    ts_values = arrays["DESIGN_SURFACE_REJECTION_REASONS"]
    assert py_values == ts_values, (
        "설계면 거부 사유가 갈라졌다 — 서버(SSOT)에만 "
        f"{sorted(py_values - ts_values)} / 대시보드에만 {sorted(ts_values - py_values)}. "
        "사유가 하나 늘었는데 문구가 없으면 사용자는 왜 거부됐는지 알 수 없다"
    )


def test_every_status_and_reason_has_a_korean_label() -> None:
    """[핵심] 두 라벨 표가 전 멤버를 덮어야 한다 — 화면에 빈 칸이 생기지 않게."""
    labels = _parse_label_keys(_LABELS_TS.read_text(encoding="utf-8"))

    status_keys = labels["DESIGN_SURFACE_STATUS_LABEL"]
    missing_status = {member.value for member in DesignSurfaceStatus} - status_keys
    assert not missing_status, f"labels.ts 에 문구가 없는 설계면 상태: {sorted(missing_status)}"

    reason_keys = labels["DESIGN_SURFACE_REJECTION_LABEL"]
    missing_reason = {member.value for member in DesignSurfaceRejectionReason} - reason_keys
    assert not missing_reason, (
        f"labels.ts 에 문구가 없는 거부 사유: {sorted(missing_reason)} — "
        "사용자는 무엇을 고쳐 다시 올려야 하는지 알 수 없다"
    )
