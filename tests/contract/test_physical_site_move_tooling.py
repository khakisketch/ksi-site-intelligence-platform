"""Contract tests for the current-revision acquisition move decision tool (P3 Task 1).

The tool under test is ``tools/prepare_physical_site_moves.py``. It converts
the frozen disposition inventory
(``docs/audit/PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv`` at baseline
``72c526b…`` — the historical record, never edited) into a CURRENT-revision
move decision manifest binding each ``ARCHIVE_CANDIDATE`` path to its present
``HEAD`` git object and blob SHA256. No file is moved here.

History-free vocabulary checks run without Git history; current-revision
binding is exercised against the real checkout ``HEAD`` (read-only plumbing)
and against disposable local synthetic Git fixtures (no edits to the real
CSV, no network).
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_tool() -> Any:
    """Load the real decision tool by file location (repository dynamic-loader
    pattern): no static ``tools.`` import for checkers to double-count, and no
    lingering ``sys.path`` mutation."""
    tool_path = ROOT / "tools" / "prepare_physical_site_moves.py"
    spec = importlib.util.spec_from_file_location("prepare_physical_site_moves", tool_path)
    assert spec is not None and spec.loader is not None, tool_path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_tool = _load_tool()
MoveDecision = _tool.MoveDecision
MoveDecisionError = _tool.MoveDecisionError
build_move_decisions = _tool.build_move_decisions
BLOCKER_PATTERN = _tool.BLOCKER_PATTERN
EXPECTED_GROUP_COUNTS = _tool.EXPECTED_GROUP_COUNTS
TOOL = ROOT / "tools" / "prepare_physical_site_moves.py"

REAL_FROZEN = ROOT / "docs/audit" / "PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv"
REAL_FROZEN_SHA256 = "89a9baf3b1f1a593bf65af02810595cea0f677a740ceb0fdf9f2e789071639e3"
REAL_FROZEN_BASELINE = "72c526ba7b6d423443d9733d1189fccd8b47ada6"
ARCHIVE_PREFIX = "archive/acquisition-2026/"

_HEX40 = re.compile(r"[0-9a-f]{40}").fullmatch
_HEX64 = re.compile(r"[0-9a-f]{64}").fullmatch


def _git_head_map() -> dict[str, tuple[str, str, str]]:
    """{path: (mode, kind, object)} straight from the real checkout HEAD."""
    out = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    rows: dict[str, tuple[str, str, str]] = {}
    for entry in out.decode("utf-8").split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t")
        mode, kind, obj = meta.split(" ")
        rows[path] = (mode, kind, obj)
    return rows


def _blob_sha256(obj: str) -> str:
    raw = subprocess.run(
        ["git", "cat-file", "blob", obj],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    return hashlib.sha256(raw).hexdigest()


def _frozen_candidates() -> list[dict[str, str]]:
    with REAL_FROZEN.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return [row for row in reader if row["proposedDisposition"] == "ARCHIVE_CANDIDATE"]


def test_frozen_csv_bytes_unchanged() -> None:
    """The frozen inventory remains the byte-identical historical record."""
    assert hashlib.sha256(REAL_FROZEN.read_bytes()).hexdigest() == REAL_FROZEN_SHA256


def test_real_csv_candidate_count_and_exact_destinations() -> None:
    """194 candidates, every destination exactly ``archive/acquisition-2026/<path>``."""
    decisions = build_move_decisions(REAL_FROZEN, ROOT)
    assert len(decisions) == 194
    assert len({decision.path for decision in decisions}) == 194
    frozen = {row["path"]: row for row in _frozen_candidates()}
    assert len(frozen) == 194
    for decision in decisions:
        assert decision.path in frozen, decision.path
        assert decision.decision == "MOVE", decision.path
        assert decision.destination == f"{ARCHIVE_PREFIX}{decision.path}", decision.path
        assert frozen[decision.path]["proposedDestination"] == decision.destination


def test_real_csv_group_counts() -> None:
    """Per-group row counts are pinned: any inventory drift is a loud failure."""
    decisions = build_move_decisions(REAL_FROZEN, ROOT)
    counts: dict[str, int] = {}
    for decision in decisions:
        counts[decision.group] = counts.get(decision.group, 0) + 1
    assert counts == EXPECTED_GROUP_COUNTS
    assert sum(counts.values()) == 194


def test_real_csv_current_revision_binding() -> None:
    """Every decision binds the CURRENT HEAD object and blob SHA256 — never a
    stale baseline hash, never working-tree bytes."""
    decisions = build_move_decisions(REAL_FROZEN, ROOT)
    head = _git_head_map()
    by_path = {decision.path: decision for decision in decisions}
    assert len(by_path) == 194
    for path, decision in by_path.items():
        assert path in head, f"candidate missing at HEAD: {path}"
        mode, kind, obj = head[path]
        assert kind == "blob", path
        assert mode in ("100644", "100755", "120000"), path
        assert decision.git_object == obj, path
        assert _HEX40(decision.git_object), path
        assert decision.blob_sha256 == _blob_sha256(obj), path
        assert _HEX64(decision.blob_sha256), path


def test_real_csv_decision_vocabulary_and_blockers() -> None:
    """Decision vocabulary enforced; every MOVE carries its exact closure
    blockers including its own per-path consumer-review id."""
    decisions = build_move_decisions(REAL_FROZEN, ROOT)
    for decision in decisions:
        assert decision.decision in ("MOVE", "DEFER", "RETAIN"), decision.path
        for blocker in decision.blockers:
            assert BLOCKER_PATTERN.fullmatch(blocker), (decision.path, blocker)
        if decision.decision == "MOVE":
            assert decision.destination == f"{ARCHIVE_PREFIX}{decision.path}"
            assert f"T6:consumer-review:{decision.path}" in decision.blockers
            assert len(decision.blockers) > 1, decision.path
        else:
            assert decision.destination is None, decision.path
    package_groups = {
        "packages/mission-contracts",
        "packages/mission-planning",
        "packages/equipment-intelligence",
        "packages/perception",
    }
    for decision in decisions:
        if decision.group in package_groups:
            assert "T5:core-dep-drop" in decision.blockers or (
                "T3:worker-managed-split" in decision.blockers
            ), decision.path
    contracts_rows = [d for d in decisions if d.group == "packages/mission-contracts"]
    assert contracts_rows, "expected mission-contracts MOVE rows"
    assert any(
        b.startswith("T5:core-import-closure:services/core/src/ksi_core/")
        for d in contracts_rows
        for b in d.blockers
    )


def _resolve_consumer(consumer: str, head: dict[str, tuple[str, str, str]]) -> str:
    """P3 Task 5 consumer-resolution rule: a recorded consumer reference is
    satisfied when the path exists either active or at
    ``archive/acquisition-2026/<path>`` (Tasks 3/5 relocate consumers
    blob-identical, so the reference bytes are unchanged). Fail-closed on
    neither: a consumer missing in both places is a stale manifest entry."""
    if consumer in head:
        return consumer
    archived = ARCHIVE_PREFIX + consumer
    assert archived in head, f"stale consumer reference: {consumer}"
    return archived


def test_real_csv_consumers_are_real_references() -> None:
    """Every recorded consumer file exists at HEAD (active or archived) and
    really references the group it gates (import, COPY, job, or routing mention)."""
    decisions = build_move_decisions(REAL_FROZEN, ROOT)
    head = _git_head_map()
    group_tokens = {
        "packages/mission-contracts": ("ksi_mission_contracts", "ksi-mission-contracts"),
        "packages/mission-planning": ("ksi_mission_planning", "ksi-mission-planning"),
        "packages/equipment-intelligence": (
            "ksi_equipment_intelligence",
            "ksi-equipment-intelligence",
        ),
        "packages/perception": ("ksi_perception", "ksi-perception", "packages/perception"),
        "services/dji-gateway": ("ksi_dji_gateway", "ksi-dji-gateway", "dji-gateway"),
        "edge/manifold-runtime": ("manifold-runtime", "manifold_runtime"),
        "edge/psdk-app": ("psdk-app", "psdk_app"),
        "edge/psdk-tap": ("psdk-tap", "psdk_tap"),
        "edge/msdk-field-bridge": ("msdk-field-bridge", "msdk_field_bridge"),
        "edge/root": ("edge/", "PSDK_LOCK", "psdk_platform", "manifold3-build"),
    }
    seen_consumers = 0
    for decision in decisions:
        tokens = group_tokens[decision.group]
        for consumer in decision.consumers:
            resolved = _resolve_consumer(consumer, head)
            raw = subprocess.run(
                ["git", "cat-file", "blob", head[resolved][2]],
                cwd=ROOT,
                check=True,
                capture_output=True,
            ).stdout.decode("utf-8", errors="replace")
            assert any(token in raw for token in tokens), (decision.path, consumer)
            seen_consumers += 1
    assert seen_consumers > 0, "expected recorded consumer evidence"


def test_decision_row_invariants_unit() -> None:
    """Row-level invariants hold for constructed values too (covers the
    DEFER/RETAIN vocabulary with no real rows at this base)."""
    validate = _tool.validate_decision_row
    ok = MoveDecision(
        path="edge/psdk-app/x.c",
        git_object="0" * 40,
        blob_sha256="f" * 64,
        group="edge/psdk-app",
        decision="MOVE",
        destination=f"{ARCHIVE_PREFIX}edge/psdk-app/x.c",
        blockers=("T6:consumer-review:edge/psdk-app/x.c", "T6:ci-docker-refs"),
        consumers=("ci.yml",),
    )
    assert validate(ok) == []
    deferred = MoveDecision(
        path="edge/psdk-app/x.c",
        git_object="0" * 40,
        blob_sha256="f" * 64,
        group="edge/psdk-app",
        decision="DEFER",
        destination=None,
        blockers=(),
        consumers=(),
    )
    assert validate(deferred) == []
    bad_destination = MoveDecision(
        path="edge/psdk-app/x.c",
        git_object="0" * 40,
        blob_sha256="f" * 64,
        group="edge/psdk-app",
        decision="MOVE",
        destination="elsewhere/x.c",
        blockers=("T6:consumer-review:edge/psdk-app/x.c",),
        consumers=(),
    )
    assert validate(bad_destination) != []
    bad_blocker = MoveDecision(
        path="edge/psdk-app/x.c",
        git_object="0" * 40,
        blob_sha256="f" * 64,
        group="edge/psdk-app",
        decision="MOVE",
        destination=f"{ARCHIVE_PREFIX}edge/psdk-app/x.c",
        blockers=("someday:maybe",),
        consumers=(),
    )
    assert validate(bad_blocker) != []


# --- Synthetic local git fixtures (no network, no real-CSV edits) ---


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_fixture_repo(tmp_path: Path) -> Path:
    """Synthetic repo with grouped acquisition files, a platform file, a
    protected ``.ai/`` canary (metadata-only) and a foreign gitlink."""
    repo = tmp_path / "move-fixture-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "fixture")
    (repo / "edge" / "psdk-app").mkdir(parents=True)
    (repo / "edge" / "psdk-app" / "app.c").write_text("acquisition\n", encoding="utf-8")
    (repo / "packages" / "mission-contracts").mkdir(parents=True)
    (repo / "packages" / "mission-contracts" / "models.py").write_text(
        "contract\n", encoding="utf-8"
    )
    (repo / "services" / "other").mkdir(parents=True)
    (repo / "services" / "other" / "x.py").write_text("other\n", encoding="utf-8")
    (repo / "keep.py").write_text("platform\n", encoding="utf-8")
    (repo / ".ai").mkdir()
    (repo / ".ai" / "PRIVATE-CANARY-QM4X").write_text(
        "DO-NOT-DELIVER-CANARY-QM4X\n", encoding="utf-8"
    )
    _git(repo, "add", ".")
    nested = tmp_path / "move-nested-repo"
    nested.mkdir(exist_ok=True)
    _git(nested, "init", "-q")
    _git(nested, "config", "user.email", "fixture@example.invalid")
    _git(nested, "config", "user.name", "fixture")
    (nested / "note.md").write_text("nested\n", encoding="utf-8")
    _git(nested, "add", ".")
    _git(nested, "commit", "-qm", "nested")
    _git(repo, "fetch", "-q", str(nested), "HEAD")
    _git(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        "160000",
        _git(nested, "rev-parse", "HEAD"),
        "refs/ext",
    )
    _git(repo, "commit", "-qm", "move fixture baseline")
    return repo


def _fixture_head_map(repo: Path) -> dict[str, tuple[str, str, str]]:
    out = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    rows: dict[str, tuple[str, str, str]] = {}
    for entry in out.decode("utf-8").split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t")
        mode, kind, obj = meta.split(" ")
        rows[path] = (mode, kind, obj)
    return rows


def _write_frozen(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(_tool.FROZEN_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _frozen_row(
    repo: Path,
    path: str,
    *,
    disposition: str = "ARCHIVE_CANDIDATE",
    destination: str | None = None,
    baseline: str | None = None,
) -> dict[str, str]:
    head = _git(repo, "rev-parse", "HEAD")
    trusted = _fixture_head_map(repo)
    mode, _kind, obj = trusted[path]
    raw = subprocess.run(
        ["git", "cat-file", "blob", obj], cwd=repo, check=True, capture_output=True
    ).stdout
    return {
        "path": path,
        "baselineCommit": baseline or head,
        "gitMode": mode,
        "gitObject": obj,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "proposedDisposition": disposition,
        "proposedDestination": destination or f"{ARCHIVE_PREFIX}{path}",
        "requiredBeforeAction": "Extract platform consumers first",
    }


def _protect_row(repo: Path, path: str) -> dict[str, str]:
    trusted = _fixture_head_map(repo)
    mode, _kind, obj = trusted[path]
    return {
        "path": path,
        "baselineCommit": _git(repo, "rev-parse", "HEAD"),
        "gitMode": mode,
        "gitObject": obj,
        "sha256": "",
        "proposedDisposition": "PROTECT",
        "proposedDestination": path,
        "requiredBeforeAction": "No reads/moves; pointer/provenance only",
    }


def _ok_fixture_manifest(repo: Path) -> list[dict[str, str]]:
    return [
        _frozen_row(repo, "edge/psdk-app/app.c"),
        _frozen_row(repo, "packages/mission-contracts/models.py"),
        _frozen_row(repo, "keep.py", disposition="RETAIN", destination="keep.py"),
        _protect_row(repo, ".ai/PRIVATE-CANARY-QM4X"),
    ]


def test_synthetic_current_revision_binding(tmp_path: Path) -> None:
    """Candidates resolve against the fixture HEAD; protected rows stay
    metadata-only and their bytes never leak into decisions or findings."""
    repo = _make_fixture_repo(tmp_path)
    manifest = _write_frozen(tmp_path / "frozen.csv", _ok_fixture_manifest(repo))
    decisions = build_move_decisions(manifest, repo)
    assert len(decisions) == 2
    trusted = _fixture_head_map(repo)
    for decision in decisions:
        assert decision.decision == "MOVE"
        assert decision.destination == f"{ARCHIVE_PREFIX}{decision.path}"
        assert decision.git_object == trusted[decision.path][2]
    assert "CANARY-QM4X" not in repr(decisions)


def test_synthetic_missing_path_is_controlled(tmp_path: Path) -> None:
    """A candidate absent at HEAD is a fail-closed finding naming the path —
    never a silent skip, never a partial manifest."""
    repo = _make_fixture_repo(tmp_path)
    rows = _ok_fixture_manifest(repo)
    ghost = dict(rows[0])
    ghost["path"] = "edge/psdk-app/ghost.c"
    ghost["proposedDestination"] = f"{ARCHIVE_PREFIX}edge/psdk-app/ghost.c"
    rows.append(ghost)
    manifest = _write_frozen(tmp_path / "ghost.csv", rows)
    with pytest.raises(MoveDecisionError) as excinfo:
        build_move_decisions(manifest, repo)
    assert any("ghost.c" in finding for finding in excinfo.value.findings)


def test_synthetic_unknown_group_is_controlled(tmp_path: Path) -> None:
    """A candidate outside every mapped acquisition group is refused."""
    repo = _make_fixture_repo(tmp_path)
    rows = _ok_fixture_manifest(repo)
    rows.append(_frozen_row(repo, "services/other/x.py"))
    manifest = _write_frozen(tmp_path / "group.csv", rows)
    with pytest.raises(MoveDecisionError) as excinfo:
        build_move_decisions(manifest, repo)
    assert any("services/other/x.py" in finding for finding in excinfo.value.findings)


def test_synthetic_nonblob_candidate_is_controlled(tmp_path: Path) -> None:
    """A candidate that is not a blob at HEAD (foreign gitlink) is refused."""
    repo = _make_fixture_repo(tmp_path)
    rows = _ok_fixture_manifest(repo)
    link = _protect_row(repo, "refs/ext")
    link["proposedDisposition"] = "ARCHIVE_CANDIDATE"
    link["proposedDestination"] = f"{ARCHIVE_PREFIX}refs/ext"
    rows.append(link)
    manifest = _write_frozen(tmp_path / "gitlink.csv", rows)
    with pytest.raises(MoveDecisionError) as excinfo:
        build_move_decisions(manifest, repo)
    assert any("refs/ext" in finding for finding in excinfo.value.findings)


def test_synthetic_bad_destination_is_controlled(tmp_path: Path) -> None:
    """A candidate whose recorded destination is not the exact archive path is
    refused — destinations are move-only and exact."""
    repo = _make_fixture_repo(tmp_path)
    rows = _ok_fixture_manifest(repo)
    for row in rows:
        if row["path"] == "edge/psdk-app/app.c":
            row["proposedDestination"] = "edge/psdk-app/app.c"
    manifest = _write_frozen(tmp_path / "dest.csv", rows)
    with pytest.raises(MoveDecisionError) as excinfo:
        build_move_decisions(manifest, repo)
    assert any("app.c" in finding for finding in excinfo.value.findings)


def test_cli_writes_csv_and_md_on_real_checkout(tmp_path: Path) -> None:
    """The real CLI binds all 194 rows and writes both artifacts with the
    required companion sections."""
    out_csv = tmp_path / "decisions.csv"
    out_md = tmp_path / "decisions.md"
    completed = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--frozen",
            str(REAL_FROZEN),
            "--out-csv",
            str(out_csv),
            "--out-md",
            str(out_md),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Traceback" not in completed.stderr
    with out_csv.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == list(_tool.DECISION_COLUMNS)
        rows = list(reader)
    assert len(rows) == 194
    for row in rows:
        assert row["destination"] == f"{ARCHIVE_PREFIX}{row['path']}", row["path"]
        assert _HEX40(row["git_object"]), row["path"]
        assert _HEX64(row["blob_sha256"]), row["path"]
        assert _HEX40(row["baseline_git_object"]), row["path"]
        assert _HEX64(row["baseline_sha256"]), row["path"]
    text = out_md.read_text(encoding="utf-8")
    for required in (
        "current-revision",
        REAL_FROZEN_BASELINE,
        REAL_FROZEN_SHA256,
        "blocker",
        "executor",
        "T6:consumer-review",
        "edge/manifold-runtime",
        "packages/mission-contracts",
        "services/dji-gateway",
    ):
        assert required in text, required


def test_cli_failure_writes_nothing(tmp_path: Path) -> None:
    """A failing CLI run exits 1, prints findings, and never writes partial
    outputs — pre-existing artifacts stay byte-identical."""
    repo = _make_fixture_repo(tmp_path)
    rows = _ok_fixture_manifest(repo)
    ghost = dict(rows[0])
    ghost["path"] = "edge/psdk-app/ghost.c"
    ghost["proposedDestination"] = f"{ARCHIVE_PREFIX}edge/psdk-app/ghost.c"
    rows.append(ghost)
    manifest = _write_frozen(tmp_path / "ghost.csv", rows)
    out_csv = tmp_path / "nope.csv"
    out_md = tmp_path / "nope.md"
    out_csv.write_text("PREVIOUS-CONTENT", encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "--frozen",
            str(manifest),
            "--out-csv",
            str(out_csv),
            "--out-md",
            str(out_md),
            "--root",
            str(repo),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1, completed.stdout
    assert "Traceback" not in completed.stderr, completed.stderr
    assert "ghost.c" in completed.stdout
    assert out_csv.read_text(encoding="utf-8") == "PREVIOUS-CONTENT"
    assert not out_md.exists()


def test_loader_leaves_sys_path_unchanged() -> None:
    """Fresh-process guard: importing this test module must not mutate
    ``sys.path`` (no lingering insertion that would re-create a dual
    ``tools.``/standalone module identity for static checkers)."""
    probe_path = repr(str(Path(__file__).resolve()))
    probe = (
        "import sys, importlib.util; "
        "before = list(sys.path); "
        f"spec = importlib.util.spec_from_file_location('probe_target', {probe_path}); "
        "module = importlib.util.module_from_spec(spec); "
        "spec.loader.exec_module(module); "
        "added = [p for p in sys.path if p not in before]; "
        "assert not added, added; "
        "print('PATH_CLEAN')"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "PATH_CLEAN" in completed.stdout, completed.stdout
