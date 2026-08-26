"""Shadow DPK Flight Control static boundary gate tests.

The target PSDK archive may retain a vendor error-mapping *definition*. These
tests lock the distinction between that audited strict-symbol blocker and an
actual KSI header/direct-call regression.

ADR-KSI-021(2026-08-16) 이후로는 **이중 잠금**도 함께 고정한다 — 단계별 심볼
유니버스는 코드에, 매니페스트는 그 부분집합만. 아래 하단 절이 그 8중 방지장치를
검증한다. 이 파일 상단의 기존 시험은 **문구 하나 안 바뀐 채** 계속 통과해야
한다 — 기본 경로(allowlist 없음)가 여전히 2026-08-15 이전과 동일한 C2-S0이므로.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tools" / "edge"))

from check_shadow_flight_boundary import (  # noqa: E402
    _FLIGHT_HEADERS,
    _MAX_ALLOWED_FILES,
    _STAGE_HEADER_UNIVERSE,
    _STAGE_SYMBOL_UNIVERSE,
    PERMANENTLY_BLOCKED_HEADERS,
    PERMANENTLY_BLOCKED_PREFIXES,
    STAGE_ORDER,
    AllowlistError,
    FlightBoundaryResult,
    check_flight_boundary,
    load_flight_execution_allowlist,
    parse_flight_symbols,
    parse_objdump_direct_calls,
    scan_called_symbols,
    scan_source_roots,
    scan_source_text,
)


def test_comments_and_literals_cannot_create_a_false_flight_control_call() -> None:
    violations = scan_source_text(
        """
        // DjiFlightController_StartGoHome() is forbidden in comments too.
        const char* explanation = "DjiFlightController_StartGoHome()";
        /* #include <dji_flight_control.h> */
        void capture_only() {}
        """,
        display_path="fixture.cpp",
    )
    assert violations == ()


def test_header_and_code_call_are_both_rejected() -> None:
    violations = scan_source_text(
        """
        # include <dji_flight_controller.h>
        void unsafe() { DjiFlightController_StartGoHome(); }
        """,
        display_path="fixture.cpp",
    )
    assert violations == (
        "fixture.cpp:2: forbidden header",
        "fixture.cpp:3: forbidden direct call DjiFlightController_StartGoHome",
    )


def test_forbidden_header_names_exist_in_the_pinned_psdk_tree() -> None:
    """존재하지 않는 파일명을 막고 있으면 header 층은 영원히 발화하지 않는다.

    실제로 2026-08-15 이전 게이트가 그 상태였다(``dji_flight_control.h``, 실제
    파일명은 ``dji_flight_controller.h``). 핀된 PSDK 트리가 받아져 있을 때만
    의미가 있으므로 없으면 건너뛴다 — 이 검사 자체가 fetch 를 강제하지는 않는다.
    """
    include_dir = _ROOT / "edge" / "third_party" / "psdk" / "psdk_lib" / "include"
    if not include_dir.is_dir():
        pytest.skip(f"PSDK 트리 미존재 — fetch_psdk.py 이후에만 검사 가능 ({include_dir})")
    missing = [name for name in _FLIGHT_HEADERS if not (include_dir / name).is_file()]
    assert missing == [], f"핀된 PSDK 에 없는 header 를 막고 있다: {missing}"


def test_waypoint_mission_execution_is_inside_the_boundary() -> None:
    """ADR-KSI-020 — KMZ 임무 업로드+START 는 기체를 이륙시킨다. 경계 안이다."""
    violations = scan_source_text(
        """
        #include "dji_waypoint_v3.h"
        void fly(const uint8_t* kmz, uint32_t len) {
            DjiWaypointV3_UploadKmzFile(kmz, len);
            DjiWaypointV3_Action(DJI_WAYPOINT_V3_ACTION_START);
        }
        """,
        display_path="fixture.cpp",
    )
    assert violations == (
        "fixture.cpp:2: forbidden header",
        "fixture.cpp:4: forbidden direct call DjiWaypointV3_UploadKmzFile",
        "fixture.cpp:5: forbidden direct call DjiWaypointV3_Action",
    )


@pytest.mark.parametrize(
    ("header", "call"),
    [
        ("dji_waypoint_v2.h", "DjiWaypointV2_Start"),
        ("dji_interest_point.h", "DjiInterestPoint_Start"),
        ("dji_fts.h", "DjiFts_SelectPwmTrigger"),
    ],
)
def test_other_motion_and_termination_families_are_rejected(header: str, call: str) -> None:
    violations = scan_source_text(
        f'#include "{header}"\nvoid unsafe() {{ {call}(); }}\n',
        display_path="fixture.cpp",
    )
    assert violations == (
        "fixture.cpp:1: forbidden header",
        f"fixture.cpp:2: forbidden direct call {call}",
    )


def test_nm_and_objdump_parsers_do_not_treat_definition_as_a_call() -> None:
    symbols = parse_flight_symbols(
        "000000000005da38 T DjiFlightController_GetDjiErrorCode\n"
        "                 U DjiFlightController_StartGoHome\n"
    )
    assert symbols == (
        "DjiFlightController_GetDjiErrorCode",
        "DjiFlightController_StartGoHome",
    )
    disassembly = """
000000000005da38 <DjiFlightController_GetDjiErrorCode>:
   5da38: d65f03c0 ret
   12345: 97ff0000 bl 5da38 <DjiFlightController_StartGoHome>
"""
    assert parse_objdump_direct_calls(disassembly) == ("DjiFlightController_StartGoHome",)


def test_vendor_definition_is_explicit_strict_gate_failure_not_direct_call() -> None:
    result = FlightBoundaryResult(defined_symbols=("DjiFlightController_GetDjiErrorCode",))
    assert result.direct_boundary_ok
    assert not result.strict_zero_symbols_ok


def test_current_ksi_source_roots_have_no_flight_control_header_or_call() -> None:
    violations = scan_source_roots(
        (
            _ROOT / "edge" / "psdk-app" / "src",
            _ROOT / "edge" / "psdk-tap" / "src",
            _ROOT / "edge" / "manifold-runtime" / "src",
            _ROOT / "edge" / "manifold-runtime" / "include",
        )
    )
    assert violations == ()


def test_psdk_worker_wires_durable_candidate_to_shadow_only_journal() -> None:
    """The deployed worker must not leave a tested supervisor disconnected."""
    source = (_ROOT / "edge" / "psdk-app" / "src" / "main.cpp").read_text(encoding="utf-8")
    assert "ArtifactVaultShadowActionJournal" in source
    assert "RecordShadowCandidates(report);" in source
    assert "shadow_supervisor_.RecordHeartbeat" in source
    assert "shadow_supervisor_.Evaluate(" in source
    assert "ActionIntentKind::kHold" in source
    assert "perception_shadow_journal_.get()" in source


# --- ADR-KSI-021 이중 잠금 — 8중 방지장치 ------------------------------------


def _write_manifest(tmp_path: Path, payload: dict) -> Path:
    manifest = tmp_path / "flight-execution-allowlist.v1.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


def _s1_entry(
    allowed_in: str = "edge/psdk-app/src/flight_execution/waypoint_v3_executor.cpp",
) -> dict:
    return {
        "symbol": "DjiWaypointV3_UploadKmzFile",
        "header": "dji_waypoint_v3.h",
        "allowedIn": [allowed_in],
        "rationale": "test",
        "evidenceRef": "test",
    }


def test_no_manifest_is_exactly_the_pre_2026_08_16_boundary() -> None:
    """1. 매니페스트 없음 = 오늘까지의 보증(C2-S0)과 동일 — 회귀 없음."""
    allowlist = load_flight_execution_allowlist(None)
    assert allowlist.stage == "C2-S0"
    assert allowlist.symbols == frozenset()
    violations = scan_source_text(
        '#include "dji_waypoint_v3.h"\nvoid f() { DjiWaypointV3_UploadKmzFile(0, 0); }\n',
        display_path="edge/psdk-app/src/flight_execution/waypoint_v3_executor.cpp",
        allowlist=allowlist,
    )
    assert violations != ()


def test_manifest_cannot_grant_a_symbol_outside_its_stage_universe(tmp_path: Path) -> None:
    """1. 단계 유니버스는 코드에 있다 — 매니페스트가 S1에서 Action(S2 전용)을 못 연다."""
    manifest = _write_manifest(
        tmp_path,
        {
            "stage": "C2-S1",
            "entries": [
                {
                    "symbol": "DjiWaypointV3_Action",  # S1 유니버스 밖
                    "header": "dji_waypoint_v3.h",
                    "allowedIn": ["edge/psdk-app/src/flight_execution/x.cpp"],
                }
            ],
        },
    )
    with pytest.raises(AllowlistError, match="유니버스 밖"):
        load_flight_execution_allowlist(manifest)


def test_stage_symbol_universe_grows_monotonically_with_action_only_at_s2() -> None:
    """1. S1 유니버스는 S2의 부분집합이고 차이는 Action 하나뿐 — 유니버스 정의 자체를 고정."""
    assert _STAGE_SYMBOL_UNIVERSE["C2-S1"] <= _STAGE_SYMBOL_UNIVERSE["C2-S2"]
    assert _STAGE_SYMBOL_UNIVERSE["C2-S2"] - _STAGE_SYMBOL_UNIVERSE["C2-S1"] == {
        "DjiWaypointV3_Action"
    }
    assert _STAGE_SYMBOL_UNIVERSE["C2-S0"] == frozenset()
    # S3·S4의 빌드 자물쇠는 S2와 동일하다(설계 원칙 ③ — 여는 건 런타임 인가뿐).
    assert _STAGE_SYMBOL_UNIVERSE["C2-S3"] == _STAGE_SYMBOL_UNIVERSE["C2-S2"]
    assert _STAGE_SYMBOL_UNIVERSE["C2-S4"] == _STAGE_SYMBOL_UNIVERSE["C2-S2"]


def test_manifest_digest_pin_forces_synchronized_edits() -> None:
    """2. 매니페스트 스키마가 바뀌면 이 시험 파일도 함께 바뀌어야 한다.

    실제 digest 대신 스키마 키 집합을 고정한다 — 키가 늘거나 줄면 이 assert가
    깨지고, 그러면 사람이 이 파일의 나머지 시험도 같이 봐야 한다는 신호가 된다.
    """
    manifest = _write_manifest(
        Path(tempfile.mkdtemp()),
        {
            "stage": "C2-S1",
            "decisionRef": "decision-psdk-flight-execution-authorization",
            "adrRef": "docs/architecture/ADR-KSI-021-staged-flight-execution-opening.md",
            "approvedBy": "test",
            "approvedAt": "2026-08-16",
            "entries": [_s1_entry()],
            "knownVendorDefinitions": ["DjiFlightController_GetDjiErrorCode"],
        },
    )
    allowlist = load_flight_execution_allowlist(manifest)
    assert allowlist.decision_ref == "decision-psdk-flight-execution-authorization"
    assert allowlist.adr_ref.endswith("ADR-KSI-021-staged-flight-execution-opening.md")
    assert allowlist.known_vendor_definitions == {"DjiFlightController_GetDjiErrorCode"}


def test_decision_and_adr_refs_are_required_fields_when_stage_is_not_s0(tmp_path: Path) -> None:
    """3·4. 결정 원장·ADR 결속 — 참조 없이 S1을 선언하면 필드 자체가 비어 있다.

    (goals.json 상태 조회는 이 게이트가 직접 하지 않는다 — 그건 CI 잡의 몫이다.
    여기서 고정하는 것은 "참조가 존재해야 로딩이 성립한다"는 스키마 계약이다.)
    """
    manifest = _write_manifest(tmp_path, {"stage": "C2-S1", "entries": [_s1_entry()]})
    allowlist = load_flight_execution_allowlist(manifest)
    assert allowlist.decision_ref == ""
    assert allowlist.adr_ref == ""
    # 빈 참조로도 로딩 자체는 되지만(스키마 위반이 아니므로), CI 잡이 이 필드를
    # 보고 결정 원장·ADR 파일 존재를 대조한다 — 그 대조는 셸 스크립트 층(별도)의 몫.


@pytest.mark.parametrize(
    "allowed_in",
    [
        "edge/manifold-runtime/src/flight_execution.cpp",
        "edge/manifold-runtime/include/ksi/edge/flight_execution.hpp",
        "edge/psdk-app/src/main.cpp",
        "edge/psdk-tap/src/mission.cpp",
    ],
)
def test_manifest_path_universe_rejects_anything_outside_flight_execution_dir(
    tmp_path: Path, allowed_in: str
) -> None:
    """5. 허용 파일은 edge/psdk-app/src/flight_execution/ 안이어야 한다.

    manifold-runtime 은 영구 0건이어야 한다 — DJI 의존 없는 그 라이브러리의
    성질이 이 경로로 깨지면 호스트 CI 전체가 PSDK를 요구하게 된다.
    """
    manifest = _write_manifest(tmp_path, {"stage": "C2-S1", "entries": [_s1_entry(allowed_in)]})
    with pytest.raises(AllowlistError, match="밖이다"):
        load_flight_execution_allowlist(manifest)


def test_manifest_file_count_is_capped(tmp_path: Path) -> None:
    """5. 허용 파일 개수 상한.

    S1 유니버스는 심볼이 하나뿐이라 파일마다 다른 항목이 되려면 대신 header
    를 달리해도 되지만, 이 저장소의 유일한 개방 헤더는 dji_waypoint_v3.h 뿐이다
    (§_STAGE_HEADER_UNIVERSE). 그래서 서로 다른 symbol(같은 유니버스 안의
    Init/UploadKmzFile 등)로 상한을 채운다 — (symbol, header) 중복 검사와
    경로 상한 검사가 서로 다른 실패를 내지 않게.
    """
    universe = sorted(_STAGE_SYMBOL_UNIVERSE["C2-S1"])
    assert len(universe) >= _MAX_ALLOWED_FILES + 1, "유니버스가 상한 시험을 채우기엔 작다"
    entries = [
        {
            "symbol": universe[i],
            "header": "dji_waypoint_v3.h",
            "allowedIn": [f"edge/psdk-app/src/flight_execution/f{i}.cpp"],
        }
        for i in range(_MAX_ALLOWED_FILES + 1)
    ]
    manifest = _write_manifest(tmp_path, {"stage": "C2-S1", "entries": entries})
    with pytest.raises(AllowlistError, match="상한"):
        load_flight_execution_allowlist(manifest)


@pytest.mark.parametrize("prefix", sorted(PERMANENTLY_BLOCKED_PREFIXES))
def test_permanently_blocked_families_are_absent_from_every_stage_universe(prefix: str) -> None:
    """6. 4계열은 어느 단계 유니버스에도 없다 — 영구 차단을 코드로 고정."""
    for stage in STAGE_ORDER:
        universe = _STAGE_SYMBOL_UNIVERSE[stage]
        assert not any(symbol.startswith(prefix) for symbol in universe), (
            f"{prefix} 가 {stage} 유니버스에 있다 — 영구 차단이 깨졌다"
        )


@pytest.mark.parametrize("header", sorted(PERMANENTLY_BLOCKED_HEADERS))
def test_permanently_blocked_headers_are_absent_from_every_stage_universe(header: str) -> None:
    for stage in STAGE_ORDER:
        assert header not in _STAGE_HEADER_UNIVERSE[stage]


@pytest.mark.parametrize("prefix", sorted(PERMANENTLY_BLOCKED_PREFIXES))
def test_permanently_blocked_families_cannot_be_granted_even_at_top_stage(
    tmp_path: Path, prefix: str
) -> None:
    """6. 매니페스트가 최상단 단계를 선언해도 4계열은 거부된다.

    실제로는 유니버스 검사가 먼저 걸린다(4계열은 어느 유니버스에도 없으므로) —
    "유니버스 밖" 판정 자체가 영구 차단의 결과이니 더 강한 증거다. 명시적
    "영구 차단" 문구는 유니버스와 무관하게 개별 심볼로도 재확인한다
    (test_permanently_blocked_families_are_absent_from_every_stage_universe).
    """
    manifest = _write_manifest(
        tmp_path,
        {
            "stage": "C2-S4",
            "entries": [
                {
                    "symbol": f"{prefix}_SomeCall",
                    "header": "dji_flight_controller.h",
                    "allowedIn": ["edge/psdk-app/src/flight_execution/x.cpp"],
                }
            ],
        },
    )
    with pytest.raises(AllowlistError, match="유니버스 밖"):
        load_flight_execution_allowlist(manifest)
    assert f"{prefix}_SomeCall".split("_", 1)[0] in PERMANENTLY_BLOCKED_PREFIXES


def test_permanent_block_check_is_reachable_not_dead_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """6(부속). 영구 차단 분기가 실제로 실행될 수 있는지 확인 — 죽은 방어선이 아니다.

    지금은 4계열이 애초에 어느 유니버스에도 없어(위 시험들이 고정) 유니버스
    검사가 항상 먼저 걸린다. 그래서 코드의 영구 차단 분기 자체는 유니버스가
    실수로 넓어졌을 때만 발화하는 **두 번째 방어선**이다 — 그 분기가 죽은
    코드가 아니라 실제로 도달 가능한지를 유니버스를 임시로 넓혀 확인한다.
    """
    import check_shadow_flight_boundary as gate

    broadened = dict(gate._STAGE_SYMBOL_UNIVERSE)
    broadened["C2-S1"] = broadened["C2-S1"] | {"DjiFlightController_StartGoHome"}
    monkeypatch.setattr(gate, "_STAGE_SYMBOL_UNIVERSE", broadened)

    manifest = _write_manifest(
        tmp_path,
        {
            "stage": "C2-S1",
            "entries": [
                {
                    "symbol": "DjiFlightController_StartGoHome",
                    "header": "dji_waypoint_v3.h",
                    "allowedIn": ["edge/psdk-app/src/flight_execution/x.cpp"],
                }
            ],
        },
    )
    with pytest.raises(AllowlistError, match="영구 차단"):
        gate.load_flight_execution_allowlist(manifest)


def test_allowlist_symbols_are_spelled_exactly_as_the_pinned_psdk_declares() -> None:
    """7. DeInit(대문자 I) 같은 오타가 allowlist를 조용히 무력화하는 것을 잡는다.

    PSDK 트리가 없으면 건너뛴다 — test_forbidden_header_names_exist_in_the_pinned_psdk_tree
    와 같은 조건.
    """
    header_path = (
        _ROOT / "edge" / "third_party" / "psdk" / "psdk_lib" / "include" / "dji_waypoint_v3.h"
    )
    if not header_path.is_file():
        pytest.skip(f"PSDK 트리 미존재 — fetch_psdk.py 이후에만 검사 가능 ({header_path})")
    declared = header_path.read_text(encoding="utf-8")
    for symbol in _STAGE_SYMBOL_UNIVERSE["C2-S2"]:
        assert f"{symbol}(" in declared, f"{symbol} 가 핀된 PSDK 헤더에 없다 — 철자 오류 의심"


def test_stale_allowlist_entry_is_reported_when_symbol_is_never_called(tmp_path: Path) -> None:
    """7(부속). 허가만 있고 실제 호출이 없는 항목 — 죽은 허가가 쌓이는 것을 경고.

    check_flight_boundary 는 이걸 실패로 승격하지 않는다(파일에 PSDK가 없는
    LOGIC_TESTS_ONLY 빌드가 기본이라서다) — 여기서는 stale_allowlist_entries
    필드에 실제로 채워지는지만 고정한다.
    """
    source_dir = tmp_path / "flight_execution"
    source_dir.mkdir()
    (source_dir / "waypoint_v3_executor.cpp").write_text(
        '#include "dji_waypoint_v3.h"\nvoid f() { DjiWaypointV3_Init(); }\n', encoding="utf-8"
    )
    manifest = _write_manifest(
        tmp_path,
        {
            "stage": "C2-S1",
            "entries": [
                {
                    "symbol": "DjiWaypointV3_Init",
                    "header": "dji_waypoint_v3.h",
                    "allowedIn": ["edge/psdk-app/src/flight_execution/waypoint_v3_executor.cpp"],
                },
                {
                    "symbol": "DjiWaypointV3_UploadKmzFile",  # 소스에서 안 부른다 — stale
                    "header": "dji_waypoint_v3.h",
                    "allowedIn": ["edge/psdk-app/src/flight_execution/waypoint_v3_executor.cpp"],
                },
            ],
        },
    )
    allowlist = load_flight_execution_allowlist(manifest)
    called = scan_called_symbols((source_dir,))
    assert called == {"DjiWaypointV3_Init"}
    stale = allowlist.unused_entries(called_symbols=called)
    assert {entry.symbol for entry in stale} == {"DjiWaypointV3_UploadKmzFile"}


def test_default_build_still_passes_without_the_allow_flag() -> None:
    """8. 기본 빌드는 candidate S1 source를 링크하지 않고 계속 S0로 남는다."""
    target = _ROOT / "edge" / "psdk-app" / "src" / "flight_execution"
    assert target.is_dir()
    assert scan_source_roots((_ROOT / "edge" / "psdk-app" / "src",)) == ()


def test_committed_upload_only_source_exactly_matches_s1_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(_ROOT)
    manifest = _ROOT / "edge" / "flight-execution-upload-only-allowlist.v1.json"
    allowlist = load_flight_execution_allowlist(manifest)
    assert allowlist.stage == "C2-S1"
    assert allowlist.symbols == {
        "DjiWaypointV3_Init",
        "DjiWaypointV3_UploadKmzFile",
        "DjiWaypointV3_DeInit",
    }
    assert "DjiWaypointV3_Action" not in allowlist.symbols
    violations = scan_source_roots(
        (Path("edge/psdk-app/src"),),
        allowlist=allowlist,
    )
    assert violations == ()
    called = scan_called_symbols((Path("edge/psdk-app/src"),))
    assert allowlist.unused_entries(called_symbols=called) == ()


def test_check_flight_boundary_wires_allowlist_through_to_scan(tmp_path: Path) -> None:
    """스캔·nm·objdump 세 층이 실제로 같은 allowlist 를 쓰는지 확인(바이너리 없이 소스 층만)."""
    source_dir = tmp_path / "flight_execution"
    source_dir.mkdir()
    (source_dir / "waypoint_v3_executor.cpp").write_text(
        '#include "dji_waypoint_v3.h"\nvoid f() { DjiWaypointV3_UploadKmzFile(0, 0); }\n',
        encoding="utf-8",
    )
    manifest = _write_manifest(
        tmp_path,
        {
            "stage": "C2-S1",
            "entries": [
                _s1_entry("edge/psdk-app/src/flight_execution/waypoint_v3_executor.cpp")
            ],
        },
    )
    allowlist = load_flight_execution_allowlist(manifest)
    result = check_flight_boundary(
        binary=tmp_path / "nonexistent",
        source_roots=(source_dir,),
        allowlist=allowlist,
    )
    # 소스 위반은 allowlist가 실제 파일 경로와 일치할 때만 사라진다 — 여기서는
    # display_path가 tmp_path 절대경로라 매니페스트의 상대경로와 다르므로 여전히
    # 위반이다(고의 — allowedIn이 저장소 상대경로 규약임을 확인하는 회귀 시험).
    assert result.source_violations != ()


# --- wrapper(verify_flight_boundary_on_built_target.sh) exit-code 회귀 ---------
#
# 예전 버전은 strict 게이트(--require-zero-defined-symbols)의 exit code를
# `|| echo ... 차단 아님` 으로 무조건 삼켰다 — 그래서 ELF에 새로 정의된
# Flight Control 심볼이 있어도 wrapper 전체는 0(PASS)으로 끝날 수 있었다. 아래
# 시험은 실제 wrapper 스크립트를 subprocess로 돌려 그 exit code를 고정한다.
# `nm`/`objdump`는 가짜 실행파일로 PATH 앞에 꽂아 결과를 통제한다 — 실물 ELF나
# aarch64 툴체인 없이도 strict 게이트의 두 경로(벤더 잡음만 / 새 심볼 있음)를
# 재현할 수 있다.

_WRAPPER = _ROOT / "tools" / "edge" / "verify_flight_boundary_on_built_target.sh"

_FAKE_NM = """#!/usr/bin/env bash
case "$1" in
  -u) cat "${KSI_TEST_NM_UNDEFINED:-/dev/null}" ;;
  --defined-only) cat "${KSI_TEST_NM_DEFINED:-/dev/null}" ;;
  *) exit 1 ;;
esac
"""

_FAKE_OBJDUMP = """#!/usr/bin/env bash
cat "${KSI_TEST_OBJDUMP:-/dev/null}"
"""


def _install_fake_binutils(bin_dir: Path) -> None:
    """nm/objdump(및 aarch64 변형)를 가짜 스크립트로 깐다 — 내용은 env var로 넘긴다."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    nm_path = bin_dir / "nm"
    nm_path.write_text(_FAKE_NM, encoding="utf-8")
    nm_path.chmod(nm_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    for name in ("objdump", "aarch64-linux-gnu-objdump", "llvm-objdump"):
        objdump_path = bin_dir / name
        objdump_path.write_text(_FAKE_OBJDUMP, encoding="utf-8")
        objdump_path.chmod(
            objdump_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
        )


def _run_wrapper(
    tmp_path: Path,
    *,
    defined_symbols_output: str,
    undefined_symbols_output: str = "",
    objdump_output: str = "",
    allowlist: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    if shutil.which("bash") is None:
        pytest.skip("bash unavailable in this environment")

    build_dir = tmp_path / "build-manifold3"
    build_dir.mkdir()
    candidate = build_dir / "fake_target"
    candidate.write_bytes(b"\x7fELF" + b"\x00" * 16)
    candidate.chmod(candidate.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    fake_bin_dir = tmp_path / "fake-bin"
    _install_fake_binutils(fake_bin_dir)

    defined_file = tmp_path / "nm_defined.txt"
    defined_file.write_text(defined_symbols_output, encoding="utf-8")
    undefined_file = tmp_path / "nm_undefined.txt"
    undefined_file.write_text(undefined_symbols_output, encoding="utf-8")
    objdump_file = tmp_path / "objdump.txt"
    objdump_file.write_text(objdump_output, encoding="utf-8")

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["KSI_TEST_NM_DEFINED"] = str(defined_file)
    env["KSI_TEST_NM_UNDEFINED"] = str(undefined_file)
    env["KSI_TEST_OBJDUMP"] = str(objdump_file)
    if allowlist is None:
        env.pop("KSI_FLIGHT_EXECUTION_ALLOWLIST", None)
    else:
        env["KSI_FLIGHT_EXECUTION_ALLOWLIST"] = str(allowlist)

    return subprocess.run(
        ["bash", str(_WRAPPER), str(build_dir)],
        cwd=_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_wrapper_passes_when_elf_has_only_known_vendor_noise(tmp_path: Path) -> None:
    """DjiFlightController_GetDjiErrorCode 하나만 정의돼 있으면 strict 게이트도 통과해야 한다."""
    completed = _run_wrapper(
        tmp_path,
        defined_symbols_output=(
            "0000000000000000 T DjiFlightController_GetDjiErrorCode\n"
        ),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "strict 게이트 통과" in completed.stdout
    assert "기본·strict 안전경계 게이트를 통과했다" in completed.stdout


def test_wrapper_fails_when_a_new_flight_control_symbol_is_defined(tmp_path: Path) -> None:
    """회귀 시험: 알려진 벤더 잡음 외 새 Flight Control 심볼은 wrapper 전체를 실패시켜야 한다.

    수정 전에는 strict 게이트의 exit code가 `|| echo ... 차단 아님` 으로 항상
    버려졌다 — 그래서 이 시나리오(기본 게이트는 통과하지만 strict 게이트가
    새 심볼 때문에 실패)에서도 wrapper 전체가 exit 0(PASS)이었다. 이 시험은
    exit code가 실제로 비영(1)이 되는 것을 고정한다.
    """
    completed = _run_wrapper(
        tmp_path,
        defined_symbols_output=(
            "0000000000000000 T DjiFlightController_GetDjiErrorCode\n"
            "0000000000000010 T DjiFlightController_StartGoHome\n"
        ),
    )
    combined = completed.stdout + completed.stderr
    assert completed.returncode == 1, combined
    assert "기본 게이트 통과" in completed.stdout  # 기본 게이트는 여전히 통과(직접호출/헤더 없음)
    assert "strict 안전경계 게이트 실패" in combined
    assert "strict zero-symbol gate failed" in combined
    assert "DjiFlightController_StartGoHome" in combined


def test_wrapper_accepts_only_committed_s1_symbols_with_exact_allowlist(
    tmp_path: Path,
) -> None:
    manifest = _ROOT / "edge" / "flight-execution-upload-only-allowlist.v1.json"
    completed = _run_wrapper(
        tmp_path,
        defined_symbols_output=(
            "0000000000000000 T DjiFlightController_GetDjiErrorCode\n"
            "0000000000000010 T DjiWaypointV3_Init\n"
            "0000000000000020 T DjiWaypointV3_UploadKmzFile\n"
            "0000000000000030 T DjiWaypointV3_DeInit\n"
        ),
        allowlist=manifest,
    )
    combined = completed.stdout + completed.stderr
    assert completed.returncode == 0, combined
    assert "기본 S0 진단(판정 제외)" in completed.stdout
    assert "allowlist strict 게이트 통과" in completed.stdout
    assert "allowlist non-strict·strict 안전경계 게이트를 통과했다" in completed.stdout


def test_wrapper_rejects_waypoint_action_even_with_s1_allowlist(tmp_path: Path) -> None:
    manifest = _ROOT / "edge" / "flight-execution-upload-only-allowlist.v1.json"
    completed = _run_wrapper(
        tmp_path,
        defined_symbols_output=(
            "0000000000000000 T DjiFlightController_GetDjiErrorCode\n"
            "0000000000000010 T DjiWaypointV3_Init\n"
            "0000000000000020 T DjiWaypointV3_UploadKmzFile\n"
            "0000000000000030 T DjiWaypointV3_DeInit\n"
            "0000000000000040 T DjiWaypointV3_Action\n"
        ),
        allowlist=manifest,
    )
    combined = completed.stdout + completed.stderr
    assert completed.returncode == 1, combined
    assert "allowlist strict 안전경계 게이트 실패" in combined
    assert "DjiWaypointV3_Action" in combined
