"""Contract regression for the R0-R2 repository structure and cleanup decisions."""

import json
import os
import shlex
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
_check_manifest_paths = import_module(
    "tools.validate_repository_normalization"
)._check_manifest_paths


def _generated_pattern_manifest(
    pattern: str, *, sources: list[str] | None = None
) -> dict[str, Any]:
    return {
        "actions": [
            {
                "id": "generated",
                "classification": "RETAIN",
                "sources": sources or ["owner/"],
                "sourcePatterns": [pattern],
                "references": [],
                "artifacts": [],
            },
            {"id": "consolidated", "classification": "CONSOLIDATE"},
            {"id": "archived", "classification": "ARCHIVE"},
            {"id": "removed", "classification": "REMOVE", "sources": []},
        ]
    }


def _initialize_git_root(root: Path, ignore_rule: str | None = None) -> None:
    subprocess.run(["git", "init", "--quiet", str(root)], check=True)
    if ignore_rule is not None:
        (root / ".gitignore").write_text(ignore_rule, encoding="utf-8")


def test_repository_normalization_contract() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/validate_repository_normalization.py")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_ci_normalization_step_uses_portable_default_contract() -> None:
    """Keep clean-clone CI separate from the operator-local cleanup audit."""

    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["gates"]["steps"]
    normalization_steps = [
        step
        for step in steps
        if step.get("name") == "repository normalization contract"
    ]
    assert len(normalization_steps) == 1

    assert shlex.split(normalization_steps[0]["run"]) == [
        "uv",
        "run",
        "--locked",
        "python",
        "tools/validate_repository_normalization.py",
    ]


def test_ci_provisions_pinned_psdk_fixture_before_pytest() -> None:
    """Make the public pinned KMZ fixture available to the full test gate."""

    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["gates"]["steps"]
    provisioning_steps = [
        step
        for step in steps
        if step.get("name") == "PSDK fixture provisioning and pin verification"
    ]
    assert len(provisioning_steps) == 1

    assert [
        shlex.split(line)
        for line in provisioning_steps[0]["run"].splitlines()
        if line.strip()
    ] == [
        ["uv", "run", "--locked", "python", "tools/edge/fetch_psdk.py"],
        ["uv", "run", "--locked", "bash", "scripts/check_third_party_pins.sh"],
    ]

    pytest_steps = [step for step in steps if step.get("name") == "pytest"]
    assert len(pytest_steps) == 1
    assert steps.index(provisioning_steps[0]) < steps.index(pytest_steps[0])


def test_repository_normalization_contract_passes_from_exact_git_index(
    tmp_path: Path,
) -> None:
    """Catch gates that accidentally consume unstaged later-responsibility WIP."""

    index_tree = tmp_path / "index-tree"
    index_tree.mkdir()
    checkout = subprocess.run(
        ["git", "checkout-index", "--all", f"--prefix={index_tree}{os.sep}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert checkout.returncode == 0, checkout.stdout + checkout.stderr
    _initialize_git_root(index_tree)

    validator = index_tree / "tools/validate_repository_normalization.py"
    result = subprocess.run(
        [sys.executable, str(validator)],
        cwd=index_tree,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_root_python_tool_caches_are_ignored_by_git() -> None:
    missing_rules: list[str] = []
    for cache_path in (".mypy_cache", ".pytest_cache", ".ruff_cache"):
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", f"{cache_path}/.probe"],
            cwd=ROOT,
            check=False,
        )
        if result.returncode != 0:
            missing_rules.append(cache_path)
    assert missing_rules == []


def test_cleanup_manifest_covers_observed_sensitive_and_generated_candidates() -> None:
    manifest = json.loads(
        (ROOT / "docs/audit/REPOSITORY_CLEANUP_MANIFEST_R0_R2.json").read_text(
            encoding="utf-8"
        )
    )
    action_ids = {action["id"] for action in manifest["actions"]}
    required_ids = {
        "licensed-local-geoid-source",
        "licensed-pinned-edge-sdk",
        "local-agent-and-governance-state",
        "local-model-artifacts",
        "local-python-toolchain",
        "local-secrets-and-machine-config",
        "module-local-generated-artifacts",
        "private-development-runtime-state",
    }
    assert required_ids <= action_ids


def test_structure_keeps_ksi_safety_as_a_separate_product_concept() -> None:
    structure = (ROOT / "REPOSITORY_STRUCTURE.md").read_text(encoding="utf-8")
    normalized = " ".join(structure.split())
    assert "KSI Safety" in normalized
    assert "separate multi-sensor real-time safety operations product concept" in normalized
    assert "does not absorb the Site Intelligence safety-patrol Mission type" in normalized


def test_recorded_generated_patterns_do_not_require_local_artifacts_to_remain(
    tmp_path: Path,
) -> None:
    _initialize_git_root(tmp_path, "/missing/node_modules/\n")
    failures: list[str] = []
    manifest = _generated_pattern_manifest(
        "missing/node_modules/", sources=["missing/"]
    )

    _check_manifest_paths(tmp_path, manifest, failures, check_local_cleanup=False)

    assert not any("source pattern has no current match" in item for item in failures)


def test_source_patterns_reject_absolute_and_parent_escape(tmp_path: Path) -> None:
    """Catch manifest globs that can probe outside the repository."""

    failures: list[str] = []
    manifest = _generated_pattern_manifest("/absolute/cache/")
    manifest["actions"][0]["sourcePatterns"].append("owner/../escape/")

    _check_manifest_paths(tmp_path, manifest, failures, check_local_cleanup=False)

    assert any(
        "source pattern must remain repository-relative: generated: /absolute/cache/"
        in item
        for item in failures
    )
    assert any(
        "source pattern must remain repository-relative: generated: owner/../escape/"
        in item
        for item in failures
    )


def test_source_patterns_reject_scope_outside_declared_owner(tmp_path: Path) -> None:
    """Catch ignored globs that silently expand beyond their declared owner roots."""

    _initialize_git_root(tmp_path, "/other/cache/\n")
    failures: list[str] = []
    manifest = _generated_pattern_manifest("other/cache/")

    _check_manifest_paths(tmp_path, manifest, failures, check_local_cleanup=False)

    assert any(
        "source pattern is not owner-scoped: generated: other/cache/" in item
        for item in failures
    )


def test_source_patterns_reject_concrete_probe_not_ignored_by_git(
    tmp_path: Path,
) -> None:
    """Catch generated-path declarations that Git would still admit to a commit."""

    _initialize_git_root(tmp_path)
    failures: list[str] = []
    manifest = _generated_pattern_manifest("owner/cache/")

    _check_manifest_paths(tmp_path, manifest, failures, check_local_cleanup=False)

    assert any(
        "source pattern is not ignored by Git: generated: owner/cache/" in item
        for item in failures
    )


def test_source_patterns_accept_owner_scoped_ignored_probe(tmp_path: Path) -> None:
    """Protect owner-local generated paths without requiring artifacts to exist."""

    _initialize_git_root(tmp_path, "/owner/cache/\n")
    failures: list[str] = []
    manifest = _generated_pattern_manifest("owner/cache/")

    _check_manifest_paths(tmp_path, manifest, failures, check_local_cleanup=False)

    assert not any("source pattern" in item for item in failures)


def test_source_patterns_allow_only_justified_global_python_cache_pattern(
    tmp_path: Path,
) -> None:
    """Catch arbitrary repository-wide globs while retaining Python bytecode hygiene."""

    _initialize_git_root(tmp_path, "__pycache__/\n")
    failures: list[str] = []
    manifest = _generated_pattern_manifest("**/__pycache__/")

    _check_manifest_paths(tmp_path, manifest, failures, check_local_cleanup=False)

    assert not any("source pattern" in item for item in failures)


def test_actual_manifest_marks_local_retained_sources_optional_for_clean_clone(
    tmp_path: Path,
) -> None:
    manifest = json.loads(
        (ROOT / "docs/audit/REPOSITORY_CLEANUP_MANIFEST_R0_R2.json").read_text(
            encoding="utf-8"
        )
    )
    actions = {action["id"]: action for action in manifest["actions"]}
    optional_local_ids = {
        "licensed-local-geoid-source",
        "licensed-pinned-edge-sdk",
        "local-agent-and-governance-state",
        "local-model-artifacts",
        "local-python-toolchain",
        "local-secrets-and-machine-config",
        "private-development-runtime-state",
        "private-field-and-hil-originals",
    }
    for action_id in optional_local_ids:
        assert actions[action_id]["sourcePresence"] == "OPTIONAL_LOCAL_PATHS"

    failures: list[str] = []
    _check_manifest_paths(tmp_path, manifest, failures, check_local_cleanup=False)

    for action_id in optional_local_ids:
        prefix = f"missing retained source: {action_id}:"
        assert not any(item.startswith(prefix) for item in failures)
