"""Removal boundary for the owner-triggered civil live-processing workflow.

Task 3 retired the NodeODM live reconstruction chain. The workflow file is
gone with it: the live job executed a pinned NodeODM image against
owner-approved photo bytes and ran ``tests/contract/test_odm_live.py``,
which has no live-tree copy (only the archived historical record). No valid
non-ODM verification remained in the workflow, so the file itself was
removed instead of being kept as an empty shell.

This guard fails locally if the workflow — or any live-contract execution
like it — is reintroduced under any workflow file name.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"
_RETIRED_WORKFLOW = _WORKFLOWS_DIR / "civil-live-contracts.yml"

# Markers of the retired live reconstruction execution. The pinned digests
# stay listed so a reintroduction under a new file name still trips the gate.
_RETIRED_LIVE_MARKERS = (
    "opendronemap/nodeodm",
    "test_odm_live",
    "KSI_ODM_IMAGES",
    "KSI_NODEODM_URL",
    "LIVE_CONTRACTS_SKIPPED",
    "fixture-gate",
)


def _workflow_files() -> list[Path]:
    return sorted(
        path
        for path in _WORKFLOWS_DIR.glob("*.yml")
        if path.is_file()
    )


def test_civil_live_contracts_workflow_is_removed() -> None:
    """The NodeODM live workflow file itself is gone — not emptied, removed."""
    assert not _RETIRED_WORKFLOW.exists(), (
        "civil-live-contracts.yml must stay removed: its only live jobs were "
        "the pinned NodeODM/MinIO live reconstruction contracts"
    )


def test_no_workflow_runs_nodeodm_live_contracts() -> None:
    """No remaining workflow may run the retired live reconstruction execution."""
    files = _workflow_files()
    assert files, "expected at least one workflow file to guard"
    for path in files:
        text = path.read_text(encoding="utf-8")
        for marker in _RETIRED_LIVE_MARKERS:
            assert marker not in text, f"{path.name} reintroduces {marker}"


def test_live_odm_contract_test_has_no_live_tree_copy() -> None:
    """The workflow's test subject lives only in the archive, never the live tree."""
    live_test = (
        Path(__file__).resolve().parents[2] / "tests" / "contract" / "test_odm_live.py"
    )
    assert not live_test.exists(), (
        "tests/contract/test_odm_live.py must not exist in the live tree: "
        "the live reconstruction chain is retired"
    )


def test_remaining_workflows_still_parse_as_yaml() -> None:
    """Keep an untested manual workflow from becoming invalid YAML."""
    for path in _workflow_files():
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(workflow, dict), path.name
