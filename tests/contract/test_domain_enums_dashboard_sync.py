"""Python 도메인 Enum 값 집합 SSOT ↔ 대시보드 TS ``as const`` 배열 대조 (P1-3).

``packages/domain/src/ksi_domain/enums`` 의 ``SiteStatus``/``EventStatus``/
``TriageStatus``/``MissionType``/``Severity`` 가 정본이고
``apps/dashboard/src/lib/core-api/types.ts`` 의 ``SITE_STATUSES``/``EVENT_STATUSES``/
``TRIAGE_STATUSES``/``MISSION_TYPES``/``EVENT_SEVERITIES`` 는 그 미러다.

``tests/contract/test_api_contract_sync.py`` 의
``test_dashboard_types_match_contract_schemas`` 는 ``interface`` 의 **필드 집합만**
비교하고 이런 ``const ... as const`` **값 목록**은 보지 않는다 — 이 파일이 그 빈틈을
메운다. 정본이 Python(도메인 패키지)이므로 Python 쪽에서 돌린다
(``test_site_autonomy_gate_dashboard_sync.py`` 와 동일 관습 — TS 소스를 정규식으로
파싱해 Python SSOT 와 대조).

값 집합이 갈리면: 서버에만 있는 값은 대시보드가 그 상태를 받았을 때 타입이 좁아
런타임 오류 없이 조용히 처리를 놓칠 수 있고, 대시보드에만 있는 값은 존재하지 않는
상태를 선택지로 보여줄 수 있다.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

from ksi_domain.enums import (
    EventStatus,
    MissionExecutionStatus,
    MissionType,
    Severity,
    SiteStatus,
    TriageStatus,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DASHBOARD_TYPES = _REPO_ROOT / "apps" / "dashboard" / "src" / "lib" / "core-api" / "types.ts"

_CONST_ARRAY = re.compile(r"export const (\w+) = \[([^\]]*)\] as const;")
_STRING_LITERAL = re.compile(r'"(\w+)"')

# (TS `as const` 배열 이름, Python SSOT enum)
_ENUM_ARRAY_MAP: tuple[tuple[str, type[StrEnum]], ...] = (
    ("SITE_STATUSES", SiteStatus),
    ("EVENT_STATUSES", EventStatus),
    ("TRIAGE_STATUSES", TriageStatus),
    ("MISSION_TYPES", MissionType),
    ("EVENT_SEVERITIES", Severity),
    ("MISSION_EXECUTION_STATUSES", MissionExecutionStatus),
)


def _parse_const_arrays(source: str) -> dict[str, set[str]]:
    """``export const NAME = [...] as const;`` 선언들 → {NAME: 값 집합}."""
    return {name: set(_STRING_LITERAL.findall(body)) for name, body in _CONST_ARRAY.findall(source)}


def test_parser_reads_every_mapped_array_non_empty() -> None:
    """공허 방지 — 파서가 표의 모든 배열을 찾았고 비어있지 않은지."""
    ts_arrays = _parse_const_arrays(_DASHBOARD_TYPES.read_text(encoding="utf-8"))
    for array_name, _enum_cls in _ENUM_ARRAY_MAP:
        assert array_name in ts_arrays, (
            f"types.ts 에서 {array_name} `as const` 배열을 찾지 못했다 — "
            "파서가 소스 변경을 못 따라간다"
        )
        assert ts_arrays[array_name], f"{array_name} 값 집합이 비어 있다 — 파싱 실패 의심"


def test_dashboard_enum_value_arrays_match_python_ssot() -> None:
    """[핵심] 표의 각 Enum 값 집합이 Python SSOT 와 정확히 일치해야 한다."""
    ts_arrays = _parse_const_arrays(_DASHBOARD_TYPES.read_text(encoding="utf-8"))

    mismatches: list[str] = []
    for array_name, enum_cls in _ENUM_ARRAY_MAP:
        py_values = {member.value for member in enum_cls}
        ts_values = ts_arrays.get(array_name, set())
        if py_values != ts_values:
            mismatches.append(
                f"{array_name}: 서버(SSOT)에만 {sorted(py_values - ts_values)} / "
                f"대시보드에만 {sorted(ts_values - py_values)}"
            )

    assert not mismatches, (
        "대시보드 types.ts 의 `as const` 배열이 서버 SSOT(ksi_domain.enums) 와 "
        f"갈라졌다 — 구현을 바꿨으면 미러도 같이 바꿔라: {mismatches}"
    )


def test_spatial_model_states_mirror_matches_core_ssot() -> None:
    """``SpatialModelState`` 는 도메인 패키지가 아니라 Core 소유라 별도로 대조한다.

    이 파일의 원칙(정본이 Python 쪽)은 같지만 import 출처가 다르다 —
    ``ksi_core.spatial_model`` 은 서비스 계층이고, 그 판정이 도메인 enum 이 아닌
    이유는 처리 작업 원장 위의 파생이기 때문이다(ADR-KSI-019 G1).
    """
    from ksi_core.spatial_model import SpatialModelState

    ts_arrays = _parse_const_arrays(_DASHBOARD_TYPES.read_text(encoding="utf-8"))

    assert "SPATIAL_MODEL_STATES" in ts_arrays, (
        "types.ts 에서 SPATIAL_MODEL_STATES `as const` 배열을 찾지 못했다"
    )
    assert ts_arrays["SPATIAL_MODEL_STATES"] == {m.value for m in SpatialModelState}, (
        "공간모델 상태 미러가 Core SSOT 와 갈라졌다 — 서버에만 있는 값은 화면이 "
        "조용히 놓치고, 화면에만 있는 값은 존재하지 않는 상태를 보여준다"
    )
