"""The parser-sandbox host probe classifies capability results fail-closed.

Pins the exact commands recorded as host evidence (user namespace, bwrap UID
mapping, network namespace) and the verdict/exit-code contract: every check
passing is the only READY; any failure keeps the parser acceptance BLOCKED with
exit 2 and names the failing check.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "tools"))

from verify_parser_sandbox_host import (  # noqa: E402 -- tools/ 를 sys.path 에 넣은 뒤에만 해석 가능
    CAPABILITIES,
    ProbeResult,
    main,
    run_capabilities,
)


def _runner_from(
    failing: set[str] | None = None, *, missing_bwrap: bool = False
) -> Callable[[Sequence[str]], ProbeResult]:
    failing = failing or set()

    def runner(command: Sequence[str]) -> ProbeResult:
        rendered = " ".join(command)
        if missing_bwrap and command[0] == "bwrap":
            return ProbeResult(127, "", "bwrap not found on PATH")
        if any(
            capability.check_id in failing and " ".join(capability.command) == rendered
            for capability in CAPABILITIES
        ):
            return ProbeResult(1, "", "setting up uid map: Permission denied")
        if command[0] == "bwrap" and command[1] == "--version":
            return ProbeResult(0, "bubblewrap 0.9.0\n", "")
        return ProbeResult(0, "", "")

    return runner


def test_probe_commands_match_the_recorded_host_evidence() -> None:
    commands = {
        capability.check_id: " ".join(capability.command) for capability in CAPABILITIES
    }
    assert commands["user-namespace"] == "unshare -Ur true"
    assert commands["bwrap-uid-map"] == "bwrap --ro-bind / / -- /bin/true"
    assert commands["bwrap-net-namespace"] == ("bwrap --unshare-net --ro-bind / / -- /bin/true")


def test_ready_host_reports_ready_and_exit_zero(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--json"], runner=_runner_from())
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verdict"] == "READY"
    assert report["failed"] == 0
    assert {item["id"] for item in report["checks"]} == {
        capability.check_id for capability in CAPABILITIES
    }


def test_uid_map_failure_blocks_with_exit_two_and_names_the_check(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--json"], runner=_runner_from({"bwrap-uid-map"}))
    assert exit_code == 2
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["verdict"] == "BLOCKED"
    failing = [item for item in report["checks"] if not item["ok"]]
    assert [item["id"] for item in failing] == ["bwrap-uid-map"]
    assert "Permission denied" in failing[0]["detail"]
    # Every other check still ran (a probe reports, it does not stop early).
    assert len(report["checks"]) == len(CAPABILITIES)
    assert "BLOCKED" in captured.err


def test_missing_bwrap_binary_is_blocked(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--json"], runner=_runner_from(missing_bwrap=True)) == 2
    report = json.loads(capsys.readouterr().out)
    bwrap_checks = [item for item in report["checks"] if item["id"].startswith("bwrap-")]
    assert bwrap_checks and all(not item["ok"] for item in bwrap_checks)


def test_optional_endpoints_participate_in_the_verdict(capsys: pytest.CaptureFixture[str]) -> None:
    def http_get(url: str) -> int:
        if url.endswith("/ready"):
            return 200
        raise ConnectionError("connection refused")

    exit_code = main(
        [
            "--json",
            "--core-url",
            "http://127.0.0.1:8051",
            "--object-origin",
            "http://127.0.0.1:9100",
        ],
        runner=_runner_from(),
        http_get=http_get,
    )
    assert exit_code == 2
    report = json.loads(capsys.readouterr().out)
    by_id = {item["id"]: item for item in report["checks"]}
    assert by_id["core-ready"]["ok"] is True
    assert by_id["object-origin"]["ok"] is False
    assert "ConnectionError" in by_id["object-origin"]["detail"]


def test_capabilities_helper_reports_details() -> None:
    results = run_capabilities(_runner_from())
    assert all(item["ok"] for item in results)
    assert results[0]["detail"] == "bubblewrap 0.9.0"
