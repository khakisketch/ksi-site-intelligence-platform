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

        _DENIED = ("ksi_synthetic_probe_denied_9f3",) + %r

        # P3 Task 6: the acquisition packages are archived, not installed —
        # the probe asserts their absence (archive-boundary expectation)
        # while the hook below stays as a reintroduction guard. The
        # synthetic first entry keeps a positive control that names no live
        # moving path (see below).
        assert (
            importlib.util.find_spec("ksi_mission_contracts") is None
        ), "ksi_mission_contracts must stay unimportable after archival"

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
        # Negative control: the archived package must stay unimportable
        # (absence first, hook as the reintroduction backstop).
        try:
            import ksi_mission_contracts  # noqa: F401
        except ImportError:
            pass
        else:
            raise AssertionError("archived ksi_mission_contracts became importable")
        # Synthetic positive control: this name exists on no path, so only
        # the hook's denial message proves the probe fires (never a live
        # moving path, never package absence).
        try:
            import ksi_synthetic_probe_denied_9f3  # noqa: F401
        except ImportError as exc:
            assert "platform isolation probe denies" in str(exc), exc
        else:
            raise AssertionError("deny-hook did not fire on the synthetic probe")

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


# ── Part B — Core managed-module closure (P3 Task 5) ─────────────────────────
# Decision-table authority: task-5-report.md phase (a). Every Core module that
# carried a runtime `ksi_mission_*` / `ksi_equipment_*` import, or top-level
# imported such a module, or solely wired the legacy managed assembly, lives
# under ``archive/acquisition-2026/`` after Task 5 and must be unimportable
# from the active tree. The platform profile (assembly + built app + staying
# shared factory/route helpers) must import no acquisition package.

_CORE_SRC = REPOSITORY_ROOT / "services/core/src"
_CORE_MANAGED_ABSENT = (
    # 11 recorded import sites (canonical + flat shims).
    "ksi_core.composition.production_config",
    "ksi_core.capability.runtime_api",
    "ksi_core.identity.signing_keys",
    "ksi_core.signing_keys",
    "ksi_core.domains.observations.events",
    "ksi_core.events",
    "ksi_core.domains.observations.equipment_states",
    "ksi_core.equipment_states",
    "ksi_core.domains.edge_transport.edge_dispatch",
    "ksi_core.edge_dispatch",
    "ksi_core.domains.design.region_extraction_reports",
    "ksi_core.region_extraction_reports",
    "ksi_core.domains.missions.mission_issuance",
    "ksi_core.mission_issuance",
    "ksi_core.domains.missions.mission_plans",
    "ksi_core.mission_plans",
    "ksi_core.domains.missions.mission_records",
    "ksi_core.mission_records",
    "ksi_core.domains.missions.mission_atomicity",
    "ksi_core.mission_atomicity",
    # Forced moves: top-level import of a moved module, or same managed set.
    "ksi_core.domains.missions.coverage_reports",
    "ksi_core.coverage_reports",
    "ksi_core.domains.missions.flight_artifacts",
    "ksi_core.flight_artifacts",
    "ksi_core.domains.missions.mission_execution",
    "ksi_core.mission_execution",
    "ksi_core.domains.missions",
    "ksi_core.domains.edge_transport.edge_sync",
    "ksi_core.edge_sync",
    "ksi_core.domains.edge_transport",
    "ksi_core.domains.analytics.defect_candidates",
    "ksi_core.defect_candidates",
    "ksi_core.domains.design.report_exports",
    "ksi_core.report_exports",
    "ksi_core.domains.observations.equipment_support",
    "ksi_core.equipment_support",
    "ksi_core.identity.device_attestation",
    "ksi_core.device_attestation",
    "ksi_core.capability",
    "ksi_core.capability.authority_store",
    "ksi_core.capability.registry",
    "ksi_core.capability.runtime_projection",
    "ksi_core.acquisition",
    "ksi_core.acquisition.analysis_readiness",
    "ksi_core.acquisition.api",
    "ksi_core.acquisition.capture_quality_reports",
    "ksi_core.capture_quality_reports",
    "ksi_core.acquisition.coordination",
    "ksi_core.acquisition.coordination_api",
    "ksi_core.acquisition.models",
    "ksi_core.acquisition.store",
    "ksi_core.domains.workspace",
    "ksi_core.domains.workspace.copilot",
    "ksi_core.copilot",
    "ksi_core.domains.workspace.copilot_conversations",
    "ksi_core.copilot_conversations",
    "ksi_core.domains.workspace.copilot_openai",
    "ksi_core.copilot_openai",
    "ksi_core.domains.workspace.site_workspace",
    "ksi_core.site_workspace",
    "ksi_core.composition.assembly",
    "ksi_core.composition.base_graph",
    "ksi_core.composition.workspace_graph",
    "ksi_core.composition.analysis_graph",
    "ksi_core.composition.capability_graph",
    "ksi_core.composition.production",
    "ksi_core.production",
    "ksi_core.app_assembly",
    # Managed-only route modules (sole runtime caller: legacy app_factory).
    "ksi_core.composition.routes.missions",
    "ksi_core.composition.routes.operations",
)

# Staying shared surfaces the platform profile exercises without managed state.
_PLATFORM_IMPORT_SURFACE = (
    "ksi_core.composition.platform_assembly",
    "ksi_core.composition.platform_production",
    "ksi_core.composition.app_factory",
    "ksi_core.composition.assembly_validation",
    "ksi_core.composition.local_analysis_runtime_config",
    "ksi_core.composition.routes.external",
    "ksi_core.composition.routes.identity_work",
    "ksi_core.composition.routes.processing",
)

_DENIED_CORE_ACQUISITION_PREFIXES = (
    "ksi_mission_contracts",
    "ksi_mission_planning",
    "ksi_equipment_intelligence",
)

_CORE_SOURCE_ROOTS = (
    _CORE_SRC,
    REPOSITORY_ROOT / "packages/event-contracts/src",
    REPOSITORY_ROOT / "packages/domain/src",
    REPOSITORY_ROOT / "packages/geo-core/src",
    REPOSITORY_ROOT / "packages/geo-spatial/src",
    REPOSITORY_ROOT / "packages/change-detection/src",
)


def _active_spec(name: str) -> bool:
    """True when `name` resolves in the active tree.

    `find_spec` raises ModuleNotFoundError (instead of returning None) when a
    parent package is gone entirely — that is absence too, and the loudest kind.
    """
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def test_core_managed_modules_are_absent_from_the_active_tree() -> None:
    """Every moved Core managed module fails loudly — never silently skipped."""
    for name in _CORE_MANAGED_ABSENT:
        assert not _active_spec(name), name
    for name in _CORE_MANAGED_ABSENT:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"{name} still imports from the active tree")


# ── Part C — Task 6 archived acquisition package roots ─────────────────────
# Decision authority: docs/audit/PHYSICAL_SITE_MOVE_DECISIONS_v1.csv groups
# packages/{mission-contracts,mission-planning,perception,
# equipment-intelligence} + services/dji-gateway (194 MOVE rows, all
# executed). Every root below — plus representative deep paths, which fail
# through the missing parent — must be unimportable from the active tree.
_TASK6_ARCHIVED_MODULE_ROOTS = (
    "ksi_mission_contracts",
    "ksi_mission_contracts.models",
    "ksi_mission_contracts.signing",
    "ksi_mission_planning",
    "ksi_mission_planning.geometry",
    "ksi_mission_planning.coverage",
    "ksi_equipment_intelligence",
    "ksi_equipment_intelligence.risk_field",
    "ksi_equipment_intelligence.kinematic_state",
    "ksi_perception",
    "ksi_perception.pipeline",
    "ksi_perception.recorded_pipeline",
    "ksi_dji_gateway",
    "ksi_dji_gateway.gateway",
    "ksi_dji_gateway.runner",
)


def test_task6_archived_package_roots_are_absent_from_the_active_tree() -> None:
    """Every archived acquisition package root fails loudly — never silently
    skipped (RB-08 explicit separation)."""
    for name in _TASK6_ARCHIVED_MODULE_ROOTS:
        assert not _active_spec(name), name
    for name in _TASK6_ARCHIVED_MODULE_ROOTS:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        raise AssertionError(f"{name} still imports from the active tree")


# Roots whose *active* (non-archived) Python files must never reach into
# ``archive/**`` — not via import, not via a dynamic load, not via a
# filesystem path handed to a loader. ``archive/`` itself is excluded by
# definition (it is the record, not a runtime input).
_ARCHIVE_SCAN_ROOTS = ("services", "packages", "tools", "deploy", "tests")

# Call names treated as filesystem/dynamic loaders for the path-based rule.
# Log/error/message calls are deliberately absent: mentioning the archive in
# prose is not reaching into it.
_ARCHIVE_LOAD_CALLS = frozenset(
    {
        "open",
        "Path",
        "spec_from_file_location",
        "SourceFileLoader",
        "exec_module",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "mkdir",
        "exists",
        "is_file",
        "is_dir",
        "glob",
        "rglob",
        "iterdir",
        "unlink",
        "rename",
        "replace",
        "symlink_to",
        "readlink",
        "resolve",
        "stat",
        "chmod",
        "chown",
        "remove",
        "removedirs",
        "makedirs",
        "listdir",
        "scandir",
        "walk",
        "copy",
        "copy2",
        "copytree",
        "move",
        "__import__",
        "import_module",
        "find_spec",
        "exec",
        "eval",
    }
)


def _is_archive_reference(value: str) -> bool:
    return (
        value == "archive"
        or value.startswith("archive.")
        or value.startswith("archive/")
        or "/archive/" in value
    )


# Pinned archive-load exemptions (RB-08 explicit, never silent). The scanner
# below sees direct archive literals in import/load calls only — a path built
# via a module constant / ``Path`` division and then handed to a loader by
# variable name is out of its view. Each such reach is listed here with its
# reason instead; the pin test below fails on any silent addition or removal.
_ARCHIVE_LOAD_EXEMPTIONS = {
    "tests/contract/test_deploy_env_contract.py": (
        "deploy-contract reference read of the archived "
        "gateway.config.example.json: the archive path is built via Path "
        "division into a variable, so the literal-in-call scanner cannot "
        "see it (documented here instead of widening the scanner into "
        "dataflow tracking)"
    ),
}


def _archive_violations_in_source(source: str, fname: str) -> list[str]:
    """All ``archive/**`` reaches in one source unit (import/dynamic/path-load)."""
    import ast

    out: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "archive" or alias.name.startswith("archive."):
                    out.append(f"{fname}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "archive" or module.startswith("archive."):
                out.append(f"{fname}:{node.lineno}: from {module} import ...")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                call_name = func.id
            elif isinstance(func, ast.Attribute):
                call_name = func.attr
            else:
                continue
            if call_name not in _ARCHIVE_LOAD_CALLS:
                continue
            for arg in (*node.args, *(kw.value for kw in node.keywords)):
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and _is_archive_reference(arg.value)
                ):
                    out.append(f"{fname}:{node.lineno}: {call_name}({arg.value[:70]!r})")
    return out


def test_active_tree_has_no_archive_imports_or_loads() -> None:
    """No active file reaches into ``archive/**`` via direct archive literals
    in import/load calls — except the reaches pinned in
    ``_ARCHIVE_LOAD_EXEMPTIONS``, each with a recorded reason. (Name/Path-
    division indirection is out of the scanner's view by design; see the
    exemption map.)"""
    violations: list[str] = []
    for root in _ARCHIVE_SCAN_ROOTS:
        for path in sorted((REPOSITORY_ROOT / root).rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            relative = str(path.relative_to(REPOSITORY_ROOT))
            if relative in _ARCHIVE_LOAD_EXEMPTIONS:
                continue
            violations.extend(
                _archive_violations_in_source(path.read_text(encoding="utf-8"), relative)
            )
    assert not violations, "active tree reaches into archive/**:\n" + "\n".join(violations)


def test_archive_load_exemptions_are_exactly_documented() -> None:
    """The exemption set is pinned: no silent additions, no silent removals."""
    assert set(_ARCHIVE_LOAD_EXEMPTIONS) == {"tests/contract/test_deploy_env_contract.py"}
    for fname, reason in _ARCHIVE_LOAD_EXEMPTIONS.items():
        assert reason.strip(), fname
        assert (REPOSITORY_ROOT / fname).is_file(), fname


def test_archive_scanner_fires_on_a_violating_snippet() -> None:
    """Non-vacuous gate: the scanner above must catch every banned form."""
    snippet = (
        "import archive.acquisition_2026.x\n"
        "from archive.acquisition_2026.y import z\n"
        "from pathlib import Path\n"
        'p = Path("archive/acquisition-2026/tests/contract/test_x.py")\n'
        'exec(open("archive/acquisition-2026/w.py").read())\n'
    )
    found = _archive_violations_in_source(snippet, "<synthetic>")
    assert len(found) == 4, found
    assert any(": import archive." in item for item in found), found
    assert any(": from archive." in item for item in found), found
    assert any("Path(" in item for item in found), found
    assert any("open(" in item for item in found), found


def test_core_source_tree_has_no_acquisition_package_imports() -> None:
    """No active Core file imports an acquisition package (AST gate, all levels)."""
    import ast

    violations: list[str] = []
    for path in sorted((_CORE_SRC / "ksi_core").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if any(
                    name == prefix or name.startswith(prefix + ".")
                    for prefix in _DENIED_CORE_ACQUISITION_PREFIXES
                ):
                    violations.append(f"{path.relative_to(REPOSITORY_ROOT)}:{node.lineno}: {name}")
    assert not violations, "active Core still imports acquisition packages:\n" + "\n".join(
        violations
    )


def _run_core_python(script: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(root) for root in _CORE_SOURCE_ROOTS] + ([existing] if existing else [])
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


def test_platform_app_imports_no_acquisition_package() -> None:
    """Fresh-process deny-hook: platform boot pulls no acquisition package."""
    denied = (*_DENIED_CORE_ACQUISITION_PREFIXES, "archive")
    script = dedent(
        """
        import importlib.util
        import sys
        import tempfile
        from pathlib import Path

        _DENIED = ("ksi_synthetic_probe_denied_9f3",) + %r

        # P3 Task 6: the acquisition packages are archived, not installed —
        # the probe asserts their absence (archive-boundary expectation)
        # while the hook below stays as a reintroduction guard. The
        # synthetic first entry keeps a positive control that names no live
        # moving path (see below).
        assert (
            importlib.util.find_spec("ksi_mission_contracts") is None
        ), "ksi_mission_contracts must stay unimportable after archival"

        class _DenyModules:
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
        # Negative control: the archived package must stay unimportable
        # (absence first, hook as the reintroduction backstop).
        try:
            import ksi_mission_contracts  # noqa: F401
        except ImportError:
            pass
        else:
            raise AssertionError("archived ksi_mission_contracts became importable")
        # Synthetic positive control: this name exists on no path, so only
        # the hook's denial message proves the probe fires (never a live
        # moving path, never package absence).
        try:
            import ksi_synthetic_probe_denied_9f3  # noqa: F401
        except ImportError as exc:
            assert "platform isolation probe denies" in str(exc), exc
        else:
            raise AssertionError("deny-hook did not fire on the synthetic probe")

        # Archive control: no archive package exists on the path, so a bare
        # import fails with ModuleNotFoundError — only the hook's denial
        # message proves the probe covers the archive prefix too.
        try:
            import archive.acquisition_2026  # noqa: F401
        except ImportError as exc:
            assert "platform isolation probe denies" in str(exc), exc
        else:
            raise AssertionError("deny-hook did not block archive")

        for _name in %r:
            importlib.import_module(_name)

        # Build the platform app: lazy route mounts must not pull acquisition.
        from ksi_core.composition.platform_assembly import assemble_platform_app
        from ksi_core.foundation.durable_journal import DurableJournal
        from ksi_core.identity.auth import AuthRegistry

        _tmp = Path(tempfile.mkdtemp())
        _opened = []

        def _journal(name):
            _item = DurableJournal(_tmp / name)
            _opened.append(_item)
            return _item

        class _Storage:
            pass

        _app = assemble_platform_app(
            _tmp,
            journal=_journal,
            opened=_opened,
            auth_registry=AuthRegistry([]),
            evidence_storage=_Storage(),
        )
        assert _app is not None

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
    ) % (denied, _PLATFORM_IMPORT_SURFACE)
    completed = _run_core_python(script)
    assert completed.returncode == 0, completed.stdout + completed.stderr
