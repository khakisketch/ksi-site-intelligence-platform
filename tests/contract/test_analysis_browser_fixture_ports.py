"""A second local fixture must not restart or reuse the incumbent test rig."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest


def _runner() -> ModuleType:
    source = Path(__file__).resolve().parents[2] / "apps/dashboard/analysis-e2e/run_core_fixture.py"
    spec = importlib.util.spec_from_file_location("fixture_ports_test_runner", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("offset", [0, 1, 1000])
def test_fixture_accepts_only_a_complete_explicit_loopback_port_set(
    monkeypatch: pytest.MonkeyPatch, offset: int
) -> None:
    monkeypatch.setattr(sys, "argv", ["fixture", "--data-dir", "/unused",
        "--run-id", "0" * 64, "--client-secret-file", "/unused/secret",
        "--dashboard-origin", f"http://localhost:{3231 + offset}",
        "--core-port", str(8033 + offset), "--issuer-port", str(9031 + offset),
        "--port-offset", str(offset)])
    assert _runner()._arguments().port_offset == offset


@pytest.mark.parametrize("extra", [
    ["--dashboard-origin", "https://example.org:3231"],
    ["--dashboard-origin", "http://localhost:3231@evil.test"],
    ["--dashboard-origin", "http://localhost:3231/callback"],
    ["--port-offset", "1"],
    ["--core-port", "8034"],
    ["--port-offset", "-1"],
    ["--port-offset", "1001"],
])
def test_fixture_rejects_foreign_origin_or_partial_port_migration(
    monkeypatch: pytest.MonkeyPatch, extra: list[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["fixture", "--data-dir", "/unused",
        "--run-id", "0" * 64, "--client-secret-file", "/unused/secret",
        "--dashboard-origin", "http://localhost:3231", *extra])
    with pytest.raises(SystemExit):
        _runner()._arguments()
