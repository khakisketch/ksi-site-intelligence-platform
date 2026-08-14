"""Shadow DPK Flight Control static boundary gate tests.

The target PSDK archive may retain a vendor error-mapping *definition*. These
tests lock the distinction between that audited strict-symbol blocker and an
actual KSI header/direct-call regression.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tools" / "edge"))

from check_shadow_flight_boundary import (  # noqa: E402
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
        # include <dji_flight_control.h>
        void unsafe() { DjiFlightController_StartGoHome(); }
        """,
        display_path="fixture.cpp",
    )
    assert violations == (
        "fixture.cpp:2: forbidden header",
        "fixture.cpp:3: forbidden direct call DjiFlightController_StartGoHome",
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
