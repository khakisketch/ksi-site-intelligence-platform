"""Core R1 module relocation contracts.

Each probe executes in a fresh interpreter so Python's module cache cannot hide an
import-order or legacy-alias defect.  The production break these tests catch is a
wrapper/re-export or copied module that stops old callers from sharing canonical
state with the relocated implementation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORE_SOURCE_ROOT = REPOSITORY_ROOT / "services/core/src"
INVENTORY_PATH = REPOSITORY_ROOT / "docs/audit/CORE_R1_MODULE_MIGRATION.json"
CHECKER_PATH = REPOSITORY_ROOT / "tools/check_core_module_boundaries.py"

MODULE_ALIASES = (
    ("ksi_core.api_base", "ksi_core.foundation.api_base"),
    ("ksi_core.durable_journal", "ksi_core.foundation.durable_journal"),
    ("ksi_core.identifiers", "ksi_core.foundation.identifiers"),
    ("ksi_core.leasing", "ksi_core.foundation.leasing"),
    ("ksi_core.metrics", "ksi_core.foundation.metrics"),
    ("ksi_core.observability", "ksi_core.foundation.observability"),
    ("ksi_core.retention", "ksi_core.foundation.retention"),
    ("ksi_core.external_authority_currentness", "ksi_core.foundation.currentness"),
    ("ksi_core.auth", "ksi_core.identity.auth"),
    ("ksi_core.oidc", "ksi_core.identity.oidc"),
    ("ksi_core.signing_keys", "ksi_core.identity.signing_keys"),
    ("ksi_core.device_attestation", "ksi_core.identity.device_attestation"),
)


def _canonical_file(module_name: str) -> Path:
    return CORE_SOURCE_ROOT / Path(*module_name.split(".")).with_suffix(".py")


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


def _require_t1_targets() -> None:
    missing = [
        str(_canonical_file(canonical))
        for _, canonical in MODULE_ALIASES
        if not _canonical_file(canonical).is_file()
    ]
    assert not missing, "T1 canonical module files are absent: " + ", ".join(missing)


@pytest.mark.parametrize("legacy, canonical", MODULE_ALIASES)
@pytest.mark.parametrize("import_order", ("canonical-first", "legacy-first"))
def test_legacy_and_canonical_imports_share_one_module_object(
    legacy: str, canonical: str, import_order: str
) -> None:
    _require_t1_targets()
    first, second = (
        (canonical, legacy) if import_order == "canonical-first" else (legacy, canonical)
    )
    expected_path = str(_canonical_file(canonical))
    _run_python(
        dedent(
            f"""
            import importlib
            import sys
            from pathlib import Path

            importlib.import_module({first!r})
            importlib.import_module({second!r})
            legacy = importlib.import_module({legacy!r})
            canonical = importlib.import_module({canonical!r})
            assert legacy is canonical
            assert sys.modules[{legacy!r}] is canonical
            assert sys.modules[{canonical!r}] is canonical
            parent = importlib.import_module("ksi_core")
            assert getattr(parent, {legacy.rsplit(".", 1)[1]!r}) is canonical
            assert Path(canonical.__file__).resolve() == Path({expected_path!r}).resolve()
            """
        )
    )


def test_legacy_journal_monkeypatch_changes_the_canonical_journal_globals() -> None:
    _require_t1_targets()
    _run_python(
        dedent(
            """
            import importlib
            from pathlib import Path
            import tempfile

            legacy = importlib.import_module("ksi_core.durable_journal")
            canonical = importlib.import_module("ksi_core.foundation.durable_journal")
            assert legacy is canonical

            def broken_write(_fd, _data):
                raise OSError("legacy alias injection")

            legacy._WRITE = broken_write
            with tempfile.TemporaryDirectory() as temporary_directory:
                journal = canonical.DurableJournal(Path(temporary_directory) / "journal.jsonl")
                try:
                    try:
                        journal.append({"record": 1})
                    except canonical.JournalSealedError:
                        pass
                    else:
                        raise AssertionError(
                            "legacy global mutation did not reach canonical append"
                        )
                finally:
                    journal.close()
            """
        )
    )


def test_canonical_journal_keeps_single_writer_append_and_replay_behavior() -> None:
    _require_t1_targets()
    _run_python(
        dedent(
            """
            from pathlib import Path
            import tempfile

            from ksi_core.foundation.durable_journal import DurableJournal, JournalRecoveryError

            with tempfile.TemporaryDirectory() as temporary_directory:
                journal_path = Path(temporary_directory) / "journal.jsonl"
                first = DurableJournal(journal_path)
                first.append({"sequence": 1})
                try:
                    DurableJournal(journal_path)
                except JournalRecoveryError:
                    pass
                else:
                    raise AssertionError("second writer was accepted")
                first.close()

                reopened = DurableJournal(journal_path)
                assert reopened.replay() == [{"sequence": 1}]
                reopened.append({"sequence": 2})
                assert reopened.replay() == [{"sequence": 1}, {"sequence": 2}]
                reopened.close()
            """
        )
    )


def test_identity_alias_preserves_principal_permission_and_legacy_pickle_lookup() -> None:
    _require_t1_targets()
    _run_python(
        dedent(
            """
            import importlib
            import pickle

            legacy = importlib.import_module("ksi_core.auth")
            canonical = importlib.import_module("ksi_core.identity.auth")
            assert legacy is canonical
            assert legacy.Principal is canonical.Principal
            assert legacy.Permission is canonical.Permission

            principal = canonical.Principal(
                principal_id="operator-1",
                kind=canonical.PrincipalKind.OPERATOR,
                role=canonical.Role.VIEWER,
                device_id=None,
            )
            assert canonical.Permission.SITES_READ in canonical.principal_permissions(principal)

            # The pre-relocation pickle named ksi_core.auth.Principal.  Temporarily
            # using that historical reference creates a representative old payload;
            # the production class metadata itself is never changed by the migration.
            original_module = canonical.Principal.__module__
            canonical.Principal.__module__ = "ksi_core.auth"
            try:
                historical_payload = pickle.dumps(principal)
            finally:
                canonical.Principal.__module__ = original_module
            restored = pickle.loads(historical_payload)
            assert type(restored) is canonical.Principal
            assert restored == principal
            """
        )
    )


def _run_checker(inventory_path: Path, module_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(CHECKER_PATH),
            "--inventory",
            str(inventory_path),
            "--module-root",
            str(module_root),
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )


def test_boundary_checker_rejects_inventory_and_new_dependency_violations(
    tmp_path: Path,
) -> None:
    _require_t1_targets()
    assert CHECKER_PATH.is_file(), "Core R1 boundary checker is absent"
    assert INVENTORY_PATH.is_file(), "Core R1 ownership inventory is absent"

    baseline = _run_checker(INVENTORY_PATH, CORE_SOURCE_ROOT)
    assert baseline.returncode == 0, baseline.stdout + baseline.stderr

    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

    duplicate_target = tmp_path / "duplicate-target.json"
    duplicate_inventory = json.loads(json.dumps(inventory))
    movable = [entry for entry in duplicate_inventory["modules"] if entry["activeCanonicalModule"]]
    movable[1]["activeCanonicalModule"] = movable[0]["activeCanonicalModule"]
    duplicate_target.write_text(json.dumps(duplicate_inventory), encoding="utf-8")
    duplicate_result = _run_checker(duplicate_target, CORE_SOURCE_ROOT)
    assert duplicate_result.returncode != 0
    assert "duplicate active canonical module" in duplicate_result.stderr

    missing_owned_module = tmp_path / "missing-owned-module.json"
    missing_inventory = json.loads(json.dumps(inventory))
    missing_inventory["modules"] = missing_inventory["modules"][:-1]
    missing_owned_module.write_text(json.dumps(missing_inventory), encoding="utf-8")
    missing_result = _run_checker(missing_owned_module, CORE_SOURCE_ROOT)
    assert missing_result.returncode != 0
    assert "missing inventory entries" in missing_result.stderr

    copied_module_root = tmp_path / "source"
    shutil.copytree(CORE_SOURCE_ROOT / "ksi_core", copied_module_root / "ksi_core")

    foundation_violation = copied_module_root / "ksi_core/foundation/identifiers.py"
    foundation_violation.write_text(
        foundation_violation.read_text(encoding="utf-8")
        + "\nfrom ksi_core.sites import SiteStore\n",
        encoding="utf-8",
    )
    foundation_result = _run_checker(INVENTORY_PATH, copied_module_root)
    assert foundation_result.returncode != 0
    assert "foundation module imports a domain" in foundation_result.stderr

    domain_violation = copied_module_root / "ksi_core/sites.py"
    domain_violation.write_text(
        domain_violation.read_text(encoding="utf-8") + "\nfrom ksi_core.app import create_app\n",
        encoding="utf-8",
    )
    domain_result = _run_checker(INVENTORY_PATH, copied_module_root)
    assert domain_result.returncode != 0
    assert "domain module imports composition" in domain_result.stderr

    # Legacy cross-domain imports are recorded baseline shape, not an invented DAG.
    foundation_violation.write_text(
        foundation_violation.read_text(encoding="utf-8").replace(
            "\nfrom ksi_core.sites import SiteStore\n", "\n"
        ),
        encoding="utf-8",
    )
    domain_violation.write_text(
        domain_violation.read_text(encoding="utf-8").replace(
            "from ksi_core.app import create_app", "from ksi_core.mission_plans import MissionPlan"
        ),
        encoding="utf-8",
    )
    allowed_legacy_result = _run_checker(INVENTORY_PATH, copied_module_root)
    assert allowed_legacy_result.returncode == 0, (
        allowed_legacy_result.stdout + allowed_legacy_result.stderr
    )


@pytest.mark.parametrize(
    ("relative_path", "import_statement"),
    (
        ("foundation/identifiers.py", "from ksi_core import sites\n"),
        ("foundation/identifiers.py", "from .. import sites\n"),
        ("foundation/__init__.py", "from .. import sites\n"),
    ),
)
def test_boundary_checker_rejects_known_package_member_domain_imports(
    tmp_path: Path, relative_path: str, import_statement: str
) -> None:
    """Resolve only inventory-known module members, including package-relative imports."""
    _require_t1_targets()
    copied_module_root = tmp_path / "source"
    shutil.copytree(CORE_SOURCE_ROOT / "ksi_core", copied_module_root / "ksi_core")

    source_path = copied_module_root / "ksi_core" / relative_path
    source_path.write_text(
        source_path.read_text(encoding="utf-8") + "\n" + import_statement,
        encoding="utf-8",
    )

    result = _run_checker(INVENTORY_PATH, copied_module_root)

    assert result.returncode != 0
    assert "foundation module imports a domain" in result.stderr


@pytest.mark.parametrize(
    ("mutation", "expected_errors"),
    (
        ("missing-source-module", ("missing required fields: sourceModule",)),
        (
            "duplicate-planned-target",
            ("duplicate planned canonical module", "duplicate planned path"),
        ),
        ("invalid-migration-status", ("unknown migrationStatus",)),
        ("cross-record-module-collision", ("cross-record module collision",)),
    ),
)
def test_boundary_checker_rejects_invalid_routing_inventory_fields(
    tmp_path: Path, mutation: str, expected_errors: tuple[str, ...]
) -> None:
    _require_t1_targets()
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    records = inventory["modules"]

    if mutation == "missing-source-module":
        del records[0]["sourceModule"]
    elif mutation == "duplicate-planned-target":
        records[1]["plannedCanonicalModule"] = records[0]["plannedCanonicalModule"]
        records[1]["plannedPath"] = records[0]["plannedPath"]
    elif mutation == "invalid-migration-status":
        records[0]["migrationStatus"] = "T9_IMAGINARY"
    elif mutation == "cross-record-module-collision":
        records[0]["sourceModule"] = records[3]["activeCanonicalModule"]
    else:
        raise AssertionError(f"unexpected test mutation: {mutation}")

    candidate_path = tmp_path / f"{mutation}.json"
    candidate_path.write_text(json.dumps(inventory), encoding="utf-8")
    result = _run_checker(candidate_path, CORE_SOURCE_ROOT)

    assert result.returncode != 0
    for expected_error in expected_errors:
        assert expected_error in result.stderr


def test_boundary_checker_does_not_allow_foundation_import_self_authorization(
    tmp_path: Path,
) -> None:
    _require_t1_targets()
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    identifiers = next(
        record
        for record in inventory["modules"]
        if record["activeCanonicalModule"] == "ksi_core.foundation.identifiers"
    )
    identifiers["permittedFoundationRuntimeImports"] = ["ksi_core.sites"]
    candidate_path = tmp_path / "self-authorized-foundation-import.json"
    candidate_path.write_text(json.dumps(inventory), encoding="utf-8")

    copied_module_root = tmp_path / "source"
    shutil.copytree(CORE_SOURCE_ROOT / "ksi_core", copied_module_root / "ksi_core")
    identifiers_path = copied_module_root / "ksi_core/foundation/identifiers.py"
    identifiers_path.write_text(
        identifiers_path.read_text(encoding="utf-8") + "\nfrom ksi_core.sites import SiteStore\n",
        encoding="utf-8",
    )

    result = _run_checker(candidate_path, copied_module_root)

    assert result.returncode != 0
    assert "foundation import allowlists are reserved" in result.stderr


@pytest.mark.parametrize(
    ("relative_path", "added_import", "expected_error"),
    (
        (
            "ksi_core/foundation/identifiers.py",
            "import ksi_core.domains",
            "foundation module imports a domain",
        ),
        (
            "ksi_core/domains/__init__.py",
            "from ksi_core.app import create_app",
            "domain module imports composition",
        ),
    ),
)
def test_boundary_checker_rejects_domain_root_edges(
    tmp_path: Path, relative_path: str, added_import: str, expected_error: str
) -> None:
    copied_module_root = tmp_path / "source"
    shutil.copytree(
        CORE_SOURCE_ROOT / "ksi_core",
        copied_module_root / "ksi_core",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    source = copied_module_root / relative_path
    source.write_text(source.read_text(encoding="utf-8") + f"\n{added_import}\n", encoding="utf-8")
    result = _run_checker(INVENTORY_PATH, copied_module_root)
    assert result.returncode != 0
    assert expected_error in result.stderr
