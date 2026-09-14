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
    ("ksi_core.app_assembly", "ksi_core.composition.assembly"),
    ("ksi_core.production", "ksi_core.composition.production"),
)

CANONICAL_MODULES = (
    "ksi_core.composition.app_factory",
    "ksi_core.composition.assembly_validation",
    "ksi_core.composition.routes.identity_work",
    "ksi_core.composition.routes.external",
    "ksi_core.composition.routes.operations",
    "ksi_core.composition.routes.missions",
    "ksi_core.composition.routes.processing",
    "ksi_core.composition.assembly",
    "ksi_core.composition.base_graph",
    "ksi_core.composition.external_graph",
    "ksi_core.composition.workspace_graph",
    "ksi_core.composition.analysis_graph",
    "ksi_core.composition.capability_graph",
    "ksi_core.composition.runtime_surfaces",
    "ksi_core.composition.production_config",
    "ksi_core.composition.production",
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
                {canonical.replace('.', '/')!r} + ".py"
            )
            """
        )
    )


def test_composition_entrypoints_keep_pinned_patch_globals_on_the_canonical_module() -> None:
    """Moving a patch seam would hide a changed assembly sequence from its callers."""
    _run_python(
        dedent(
            """
            import importlib

            app = importlib.import_module("ksi_core.app")
            assembly = importlib.import_module("ksi_core.app_assembly")
            production = importlib.import_module("ksi_core.production")
            assert app.create_app is importlib.import_module(
                "ksi_core.composition.app_factory"
            ).create_app
            assert app._ASSEMBLY_REQUIREMENTS is importlib.import_module(
                "ksi_core.composition.assembly_validation"
            )._ASSEMBLY_REQUIREMENTS
            assert assembly.create_app is importlib.import_module(
                "ksi_core.composition.assembly"
            ).create_app
            assert assembly.ObservationWorkOrderStore is importlib.import_module(
                "ksi_core.composition.assembly"
            ).ObservationWorkOrderStore
            assert assembly.ExternalAuthorityCurrentnessCoordinator is importlib.import_module(
                "ksi_core.composition.assembly"
            ).ExternalAuthorityCurrentnessCoordinator
            assert production.datetime is importlib.import_module(
                "ksi_core.composition.production"
            ).datetime
            assert production.assemble_app is importlib.import_module(
                "ksi_core.composition.production"
            ).assemble_app
            """
        )
    )


def test_app_assembly_import_keeps_site_workspace_lazy() -> None:
    """Importing assembly alone must not open the optional workspace graph."""
    _run_python(
        dedent(
            """
            import importlib
            import sys

            importlib.import_module("ksi_core.app_assembly")
            assert "ksi_core.site_workspace" not in sys.modules
            assert "ksi_core.domains.workspace.site_workspace" not in sys.modules
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
