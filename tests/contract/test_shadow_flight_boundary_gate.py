"""Shadow DPK Flight Control static boundary gate tests.

The target PSDK archive may retain a vendor error-mapping *definition*. These
tests lock the distinction between that audited strict-symbol blocker and an
actual KSI header/direct-call regression.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tools" / "edge"))

from check_shadow_flight_boundary import (  # noqa: E402
    _FLIGHT_HEADERS,
    FlightBoundaryResult,
    parse_flight_symbols,
    parse_objdump_direct_calls,
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
