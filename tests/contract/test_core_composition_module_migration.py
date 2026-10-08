"""Core R1 T5 composition extraction compatibility contracts.

Fresh interpreter checks prove legacy entrypoints replace themselves with the
canonical composition module rather than leaving a second patchable namespace.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORE_SOURCE_ROOT = REPOSITORY_ROOT / "services/core/src"

LEGACY_ALIASES = (
    ("ksi_core.app", "ksi_core.composition.app_factory"),
    # P3 Task 5: app_assembly/production entrypoints retired to
    # archive/acquisition-2026/ with their canonical composition modules.
)

CANONICAL_MODULES = (
    "ksi_core.composition.app_factory",
    "ksi_core.composition.assembly_validation",
    "ksi_core.composition.routes.identity_work",
    "ksi_core.composition.routes.external",
    "ksi_core.composition.routes.processing",
    # P3 Task 5: assembly/base_graph/workspace_graph/analysis_graph/
    # capability_graph/production_config/production retired to the archive.
    "ksi_core.composition.external_graph",
    "ksi_core.composition.runtime_surfaces",
)


def _run_python(script: str) -> None:
    environment = os.environ.copy()
    existing_python_path = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(CORE_SOURCE_ROOT), existing_python_path) if part
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize("legacy, canonical", LEGACY_ALIASES)
@pytest.mark.parametrize("import_order", ("canonical-first", "legacy-first"))
def test_legacy_composition_entrypoints_share_one_canonical_module_object(
    legacy: str, canonical: str, import_order: str
) -> None:
    """A copied entrypoint would split test-patched assembly/production globals."""
    first, second = (
        (canonical, legacy) if import_order == "canonical-first" else (legacy, canonical)
    )
    _run_python(
        dedent(
            f"""
            import importlib
            import sys

            importlib.import_module({first!r})
            importlib.import_module({second!r})
            legacy = importlib.import_module({legacy!r})
            canonical = importlib.import_module({canonical!r})
            assert legacy is canonical
            assert sys.modules[{legacy!r}] is canonical
            assert sys.modules[{canonical!r}] is canonical
            assert canonical.__file__.replace("\\\\", "/").endswith(
                {canonical.replace(".", "/")!r} + ".py"
            )
            """
        )
    )


def test_composition_entrypoints_keep_pinned_patch_globals_on_the_canonical_module() -> None:
    """Moving a patch seam would hide a changed assembly sequence from its callers."""
    # P3 Task 5: assembly/production patch-seam asserts retired with the
    # archived managed composition (archive-internal per the T3 precedent).
    _run_python(
        dedent(
            """
            import importlib

            app = importlib.import_module("ksi_core.app")
            assert app.create_app is importlib.import_module(
                "ksi_core.composition.app_factory"
            ).create_app
            assert app._ASSEMBLY_REQUIREMENTS is importlib.import_module(
                "ksi_core.composition.assembly_validation"
            )._ASSEMBLY_REQUIREMENTS
            """
        )
    )


def test_composition_module_inventory_is_complete() -> None:
    """An omitted extraction module would leave hidden composition in a shim."""
    _run_python(
        dedent(
            f"""
            import importlib

            for name in {CANONICAL_MODULES!r}:
                module = importlib.import_module(name)
                assert module.__file__ is not None
            """
        )
    )
