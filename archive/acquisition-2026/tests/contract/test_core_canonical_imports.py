"""Canonical domain imports and retained acquisition cycle-breakers."""

from __future__ import annotations

import ast
import itertools
import json
import subprocess
import sys
from importlib.util import resolve_name
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "services/core/src/ksi_core"
ACQUISITION_CYCLE = (
    "ksi_core.acquisition.analysis_readiness",
    "ksi_core.acquisition.capture_quality_reports",
    "ksi_core.acquisition.coordination",
)


@pytest.mark.parametrize("owner", ("domains", "acquisition", "capability"))
def test_canonical_owners_do_not_import_moved_legacy_modules(owner: str) -> None:
    inventory = json.loads((ROOT / "docs/audit/CORE_R1_MODULE_MIGRATION.json").read_text())
    legacy = {record["legacyModule"] for record in inventory["modules"] if "legacyModule" in record}
    violations: list[str] = []
    paths = sorted((CORE / owner).rglob("*.py"))
    assert paths
    for path in paths:
        relative = path.relative_to(CORE.parent).with_suffix("")
        package = ".".join(relative.parts[:-1])
        for node in ast.walk(ast.parse(path.read_text())):
            imports: list[str] = []
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    base = resolve_name("." * node.level + base, package)
                imports = [base, *(f"{base}.{alias.name}" for alias in node.names)]
            else:
                continue
            for name in imports:
                if name in legacy:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {name}")
    assert not violations, "Canonical owners still import compatibility paths:\n" + "\n".join(
        violations
    )


@pytest.mark.parametrize("order", tuple(itertools.permutations(ACQUISITION_CYCLE)))
def test_acquisition_cycle_import_orders_remain_valid(order: tuple[str, ...]) -> None:
    script = (
        "import importlib\n"
        f"for name in {order!r}: importlib.import_module(name)\n"
        "assert importlib.import_module('ksi_core.capture_quality_reports') is "
        "importlib.import_module('ksi_core.acquisition.capture_quality_reports')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
