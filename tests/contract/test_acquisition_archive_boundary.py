"""Processing-controller platform/managed split boundary (P3 Task 3).

Proves the surviving platform lanes import no managed reconstruction module
and no acquisition package:

* The eight managed-only modules (``runner``, ``worker``, ``odm``,
  ``odm_assets``, ``http_node_odm``, ``odm_masking``, ``measure``, ``gsd``)
  are absent from the platform tree — ``find_spec`` is ``None`` and importing
  them raises ``ModuleNotFoundError`` (never a silent skip).
* A fresh subprocess under a ``find_spec``-raising deny-hook imports every
  surviving entrypoint module plus the shared lane modules and observes zero
  denied modules in ``sys.modules``. The hook's positive control
  (``ksi_mission_contracts`` is installed, so blocking it proves the hook
  fires rather than the package being missing) follows
  ``tests/contract/test_historical_managed_readers.py``.
* The package's ``[project.scripts]`` still registers exactly the seven
  platform entrypoints — ``ksi-processing-worker`` is gone with the managed
  daemon and no surviving entrypoint was renamed or repointed.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from textwrap import dedent

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_PC_SRC = REPOSITORY_ROOT / "services/processing-controller/src"
_PC_PYPROJECT = REPOSITORY_ROOT / "services/processing-controller/pyproject.toml"

# Classification table authority: Task 3 report (managed-only by
# import/entrypoint/test/Docker evidence; ambiguous modules stay).
_MANAGED_MODULES = (
    "ksi_processing_controller.runner",
    "ksi_processing_controller.worker",
    "ksi_processing_controller.odm",
    "ksi_processing_controller.odm_assets",
    "ksi_processing_controller.http_node_odm",
    "ksi_processing_controller.odm_masking",
    "ksi_processing_controller.measure",
    "ksi_processing_controller.gsd",
)

# Acquisition packages the platform lanes must never pull.
_DENIED_ACQUISITION_PREFIXES = (
    "ksi_core.acquisition",
    "ksi_mission_contracts",
    "ksi_mission_planning",
    "ksi_equipment_intelligence",
)

# Surviving console entrypoints (names) and their modules.
_SURVIVING_ENTRYPOINT_MODULES = (
    "ksi_processing_controller.external_inspector_daemon",
    "ksi_processing_controller.external_inspector_container_entrypoint",
    "ksi_processing_controller.external_measurement_container_entrypoint",
    "ksi_processing_controller.external_measurement_daemon",
    "ksi_processing_controller.external_validation_worker",
    "ksi_processing_controller.external_analysis_runner",
    "ksi_processing_controller.spatial_data_runner",
)
_SURVIVING_SCRIPTS = (
    "ksi-external-inspector-daemon",
    "ksi-external-inspector-entrypoint",
    "ksi-external-measurement-entrypoint",
    "ksi-external-measurement-daemon",
    "ksi-external-validation-worker",
    "ksi-external-analysis-worker",
    "ksi-spatial-data-worker",
)

# Shared lane modules the platform lanes build on (kept per evidence).
_SURVIVING_LANE_MODULES = (
    "ksi_processing_controller.comparison_worker",
    "ksi_processing_controller.design_conformance_worker",
    "ksi_processing_controller.design_surface_verifier",
    "ksi_processing_controller.region_extraction_worker",
    "ksi_processing_controller.checkpoint_validator",
    "ksi_processing_controller.workspace",
    "ksi_processing_controller.capture_time",
    "ksi_processing_controller.landxml",
    "ksi_processing_controller.core_client",
    "ksi_processing_controller.observability",
)

_SOURCE_ROOTS = (
    _PC_SRC,
    REPOSITORY_ROOT / "packages/event-contracts/src",
    REPOSITORY_ROOT / "packages/domain/src",
    REPOSITORY_ROOT / "packages/geo-spatial/src",
    REPOSITORY_ROOT / "packages/geo-core/src",
    REPOSITORY_ROOT / "packages/change-detection/src",
)


def test_managed_modules_are_absent_from_the_platform_tree() -> None:
    """Every managed-only module fails loudly — never silently skipped."""
    for name in _MANAGED_MODULES:
        assert importlib.util.find_spec(name) is None, name
    for name in _MANAGED_MODULES:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"{name} still imports from the platform tree")


def test_surviving_entrypoints_keep_exact_script_registrations() -> None:
    """``[project.scripts]`` keeps exactly the seven platform entrypoints."""
    scripts = tomllib.loads(_PC_PYPROJECT.read_text(encoding="utf-8"))["project"]["scripts"]
    assert sorted(scripts) == sorted(_SURVIVING_SCRIPTS), sorted(scripts)
    assert "ksi-processing-worker" not in scripts
    for module in (*_SURVIVING_ENTRYPOINT_MODULES, *_SURVIVING_LANE_MODULES):
        relative = Path(*module.split(".")).with_suffix(".py")
        assert (_PC_SRC / relative).is_file(), relative


def _run_python(script: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(root) for root in _SOURCE_ROOTS] + ([existing] if existing else [])
    )
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=180,
    )


def test_platform_lanes_import_no_managed_or_acquisition_module() -> None:
    """Fresh-process deny-hook: surviving lanes pull no managed/acquisition module."""
    denied = _MANAGED_MODULES + _DENIED_ACQUISITION_PREFIXES
    script = dedent(
        """
        import importlib.util
        import sys

        _DENIED = %r

        # Sanity first: the control module is installed, so blocking it
        # below proves the hook fires (not that the package is missing).
        assert (
            importlib.util.find_spec("ksi_mission_contracts") is not None
        ), "ksi_mission_contracts must be installed for this probe"

        class _DenyModules:
            # Python 3.12 no longer calls find_module — find_spec is the
            # supported blocker entry point. Raising here fails the import
            # loudly instead of silently skipping the module.
            def find_spec(self, name, path=None, target=None):
                if name in _DENIED or any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in _DENIED
                ):
                    raise ImportError(f"platform isolation probe denies {name}")
                return None

        sys.meta_path.insert(0, _DenyModules())
        for _module in list(sys.modules):
            assert not any(
                _module == prefix or _module.startswith(prefix + ".")
                for prefix in _DENIED
            ), _module
        # Positive control: the hook must actually fire.
        try:
            import ksi_mission_contracts  # noqa: F401
        except ImportError as exc:
            assert "platform isolation probe denies" in str(exc), exc
        else:
            raise AssertionError("deny-hook did not block ksi_mission_contracts")

        for _name in %r:
            importlib.import_module(_name)

        leaked = sorted(
            module
            for module in sys.modules
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in _DENIED
            )
        )
        assert leaked == [], leaked
        """
    ) % (denied, (*_SURVIVING_ENTRYPOINT_MODULES, *_SURVIVING_LANE_MODULES))
    completed = _run_python(script)
    assert completed.returncode == 0, completed.stdout + completed.stderr
