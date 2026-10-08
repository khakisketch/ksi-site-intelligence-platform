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


REAL_DECISIONS = ROOT / "docs/audit" / "PHYSICAL_SITE_MOVE_DECISIONS_v1.csv"


def _committed_decisions() -> list[dict[str, str]]:
    """Rows of the committed move-decision manifest. Post-execution (P3 Task
    6) the manifest is read as the historical record — rebuilding it requires
    the pre-move tree, so these tests verify the EXECUTED state (archive
    bindings) instead of re-deriving decisions."""
    with REAL_DECISIONS.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == list(_tool.DECISION_COLUMNS)
        return list(reader)


def test_frozen_csv_bytes_unchanged() -> None:
    """The frozen inventory remains the byte-identical historical record."""
    assert hashlib.sha256(REAL_FROZEN.read_bytes()).hexdigest() == REAL_FROZEN_SHA256


def test_real_csv_candidate_count_and_exact_destinations() -> None:
    """194 candidates, every destination exactly ``archive/acquisition-2026/<path>``."""
    rows = _committed_decisions()
    assert len(rows) == 194
    assert len({row["path"] for row in rows}) == 194
    frozen = {row["path"]: row for row in _frozen_candidates()}
    assert len(frozen) == 194
    for row in rows:
        assert row["path"] in frozen, row["path"]
        assert row["decision"] == "MOVE", row["path"]
        assert row["destination"] == f"{ARCHIVE_PREFIX}{row['path']}", row["path"]
        assert frozen[row["path"]]["proposedDestination"] == row["destination"]


def test_real_csv_group_counts() -> None:
    """Per-group row counts are pinned: any inventory drift is a loud failure."""
    rows = _committed_decisions()
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["group"]] = counts.get(row["group"], 0) + 1
    assert counts == EXPECTED_GROUP_COUNTS
    assert sum(counts.values()) == 194


def test_real_csv_current_revision_binding() -> None:
    """Post-execution archive binding: every active source path is gone from
    HEAD and its exact destination blob carries the recorded git object and
    blob SHA256 — blob-identical execution, never working-tree bytes."""
    rows = _committed_decisions()
    head = _git_head_map()
    assert len({row["path"] for row in rows}) == 194
    for row in rows:
        path = row["path"]
        assert path not in head, f"candidate still active at HEAD: {path}"
        destination = row["destination"]
        assert destination in head, f"destination missing at HEAD: {destination}"
        mode, kind, obj = head[destination]
        assert kind == "blob", destination
        assert mode in ("100644", "100755", "120000"), destination
        assert row["git_object"] == obj, path
        assert _HEX40(row["git_object"]), path
        assert row["blob_sha256"] == _blob_sha256(obj), path
        assert _HEX64(row["blob_sha256"]), path


def test_real_csv_decision_vocabulary_and_blockers() -> None:
    """Decision vocabulary enforced; every MOVE carries its exact closure
    blockers including its own per-path consumer-review id (historical record
    of the closure this task executed)."""
    rows = _committed_decisions()
    for row in rows:
        assert row["decision"] in ("MOVE", "DEFER", "RETAIN"), row["path"]
        blockers = [b for b in row["blockers"].split(";") if b]
        for blocker in blockers:
            assert BLOCKER_PATTERN.fullmatch(blocker), (row["path"], blocker)
        if row["decision"] == "MOVE":
            assert row["destination"] == f"{ARCHIVE_PREFIX}{row['path']}"
            assert f"T6:consumer-review:{row['path']}" in blockers
            assert len(blockers) > 1, row["path"]
        else:
            assert not row["destination"], row["path"]
    package_groups = {
        "packages/mission-contracts",
        "packages/mission-planning",
        "packages/equipment-intelligence",
        "packages/perception",
    }
    for row in rows:
        if row["group"] in package_groups:
            blockers = [b for b in row["blockers"].split(";") if b]
            assert "T5:core-dep-drop" in blockers or (
                "T3:worker-managed-split" in blockers
            ), row["path"]
    contracts_rows = [r for r in rows if r["group"] == "packages/mission-contracts"]
    assert contracts_rows, "expected mission-contracts MOVE rows"
    assert any(
        b.startswith("T5:core-import-closure:services/core/src/ksi_core/")
        for r in contracts_rows
        for b in [b for b in r["blockers"].split(";") if b]
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
    really references the group it gates (import, COPY, job, or routing mention)
    — EXCEPT the consumers Task 6 intentionally closed: their references were
    removed by the same-batch closure edits (edge CI jobs retired to the
    historical route; perception COPY dropped from the retained images), so
    the recorded reference now resolves but no longer matches. That closed set
    is explicit here (never silent) and bound to the Task 6 closure commits."""
    # P3 Task 6 closure record: (consumer, groups whose token it no longer
    # carries). Commits ad220a9 (test/tooling archival) and 4148cb7 (consumer
    # closures) own the removals; the executor's live-reference scan enforces
    # the other direction (no live file may still name a moving path).
    task6_closed = {
        ".github/workflows/ci.yml": {
            "edge/manifold-runtime",
            "edge/psdk-app",
            "edge/psdk-tap",
        },
        "Dockerfile.external-inspector": {"packages/perception"},
        "Dockerfile.external-measurement": {"packages/perception"},
        # The normalization validator no longer names any edge/root token:
        # the moved dirs left REQUIRED_STRUCTURE_PATHS (now the archive root)
        # and the edge README left the linked-docs gate. Manifest references
        # still resolve through the validator's archive fallback at runtime.
        "tools/validate_repository_normalization.py": {"edge/root"},
    }
    # Prior-task closures (references removed by design in Tasks 3/5, not
    # relocated): the three package dependencies left services/core/
    # pyproject.toml (Task 5 commit 2e85391) and ksi-perception left the
    # worker pyproject (Task 3 commit 6a00443). The committed manifest keeps
    # them as the historical consumer record; the T5/T3 blocker ids are the
    # closure evidence.
    prior_closed = {
        "services/core/pyproject.toml": {
            "packages/equipment-intelligence",
            "packages/mission-contracts",
            "packages/mission-planning",
        },
        "services/processing-controller/pyproject.toml": {"packages/perception"},
    }
    decisions = _committed_decisions()
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
    seen_closed = 0
    for decision in decisions:
        tokens = group_tokens[decision["group"]]
        consumers = [c for c in decision["consumers"].split(";") if c]
        for consumer in consumers:
            resolved = _resolve_consumer(consumer, head)
            raw = subprocess.run(
                ["git", "cat-file", "blob", head[resolved][2]],
                cwd=ROOT,
                check=True,
                capture_output=True,
            ).stdout.decode("utf-8", errors="replace")
            if any(token in raw for token in tokens):
                seen_consumers += 1
                continue
            assert decision["group"] in task6_closed.get(
                consumer, set()
            ) | prior_closed.get(consumer, set()), (
                decision["path"],
                consumer,
            )
            seen_closed += 1
    assert seen_consumers > 0, "expected recorded consumer evidence"
    assert seen_closed > 0, "expected the recorded Task 6 closures"


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


def test_cli_refuses_rebuild_after_execution(tmp_path: Path) -> None:
    """Post-execution the decision tool fail-closes on the real checkout: the
    candidates are gone from HEAD, so rebuilding refuses with controlled
    findings (never a partial manifest, never a traceback). The committed
    manifest stays the historical record."""
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
    assert completed.returncode == 1, completed.stdout + completed.stderr
    assert "Traceback" not in completed.stderr, completed.stderr
    assert "missing at HEAD" in completed.stdout, completed.stdout
    assert not out_csv.exists()
    assert not out_md.exists()


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


# --- Executor: tools/execute_physical_site_moves.py (P3 Task 6) ---
#
# Refined Task 6 rule under test: ``is_executable(row)`` holds when every
# blocker is a known vocabulary id, every T3/T5 id verifies as closed at HEAD
# against its recorded evidence, every T6 id is closed by the same-batch
# edits (machine-checked via consumer resolution + live-reference scan), and
# every consumer resolves active-or-archive. The executor refuses the WHOLE
# batch — never partial moves — on hash mismatch, unknown blocker,
# unverified foreign closure, stale consumer, live reference, destination
# collision, or a hostile manifest. Dry-run is the default.


def _load_executor() -> Any:
    """Load the real batch executor by file location (same dynamic-loader
    pattern as the decision tool: no static ``tools.`` import)."""
    tool_path = ROOT / "tools" / "execute_physical_site_moves.py"
    spec = importlib.util.spec_from_file_location("execute_physical_site_moves", tool_path)
    assert spec is not None and spec.loader is not None, tool_path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_exec = _load_executor()
EXEC_TOOL = ROOT / "tools" / "execute_physical_site_moves.py"


def _exec_repo(tmp_path: Path, files: dict[str, str], name: str = "exec-repo") -> Path:
    repo = tmp_path / name
    repo.mkdir(exist_ok=False)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "fixture")
    for relative, content in files.items():
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "executor fixture baseline")
    return repo


def _head_binding(repo: Path, path: str) -> tuple[str, str]:
    """(git object, blob SHA256) for ``path`` at the fixture HEAD."""
    entry = _git(repo, "ls-tree", "HEAD", path)
    mode, kind, obj = entry.split("\t")[0].split(" ")
    assert kind == "blob", entry
    raw = subprocess.run(
        ["git", "cat-file", "blob", obj], cwd=repo, check=True, capture_output=True
    ).stdout
    import hashlib as _hashlib

    return obj, _hashlib.sha256(raw).hexdigest()


def _write_decision_manifest(
    path: Path,
    repo: Path,
    specs: list[tuple[str, tuple[str, ...], tuple[str, ...]]],
    *,
    decision: str = "MOVE",
    tamper: dict[str, str] | None = None,
) -> Path:
    """Write an executor decision CSV for ``specs`` of
    (path, blockers, consumers) bound to the fixture HEAD."""
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(_exec.DECISION_COLUMNS))
        writer.writeheader()
        for rel, blockers, consumers in specs:
            obj, digest = _head_binding(repo, rel)
            row = {
                "path": rel,
                "git_object": obj,
                "blob_sha256": digest,
                "baseline_git_object": obj,
                "baseline_sha256": digest,
                "group": "edge/root",
                "decision": decision,
                "destination": f"{ARCHIVE_PREFIX}{rel}",
                "blockers": ";".join(blockers),
                "consumers": ";".join(consumers),
            }
            if tamper and rel in tamper:
                row.update(tamper[rel])
            writer.writerow(row)
    return path


def _run_executor(
    manifest: Path, repo: Path, inverse: Path, *, apply: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(EXEC_TOOL),
            "--manifest",
            str(manifest),
            "--root",
            str(repo),
            "--inverse",
            str(inverse),
            *(["--apply"] if apply else []),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _tree_unchanged(repo: Path) -> None:
    assert _git(repo, "status", "--porcelain") == "", "tree must be unchanged"
    assert not (repo / "archive").exists(), "no archive side-effects on refusal"


def test_executor_dry_run_performs_no_change(tmp_path: Path) -> None:
    """Dry-run (default, no ``--apply``) validates but moves nothing and
    writes no inverse record."""
    repo = _exec_repo(tmp_path, {"victim.txt": "move me\n", "other.txt": "stay\n"})
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv", repo, [("victim.txt", (), ())]
    )
    inverse = tmp_path / "inverse.json"
    completed = _run_executor(manifest, repo, inverse)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Traceback" not in completed.stderr
    assert "dry-run, tree unchanged" in completed.stdout
    _tree_unchanged(repo)
    assert (repo / "victim.txt").read_text(encoding="utf-8") == "move me\n"
    assert not inverse.exists()


def test_executor_hash_mismatch_refuses_the_whole_batch(tmp_path: Path) -> None:
    """One tampered blob hash refuses every row — the valid row is not moved
    either (never partial moves)."""
    repo = _exec_repo(tmp_path, {"a.txt": "aaa\n", "b.txt": "bbb\n"})
    obj_b, _digest_b = _head_binding(repo, "b.txt")
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv",
        repo,
        [("a.txt", (), ()), ("b.txt", (), ())],
        tamper={"a.txt": {"blob_sha256": "0" * 64}},
    )
    completed = _run_executor(manifest, repo, tmp_path / "inverse.json")
    assert completed.returncode == 1, completed.stdout
    assert "Traceback" not in completed.stderr
    assert "a.txt" in completed.stdout
    _tree_unchanged(repo)
    assert (repo / "b.txt").read_text(encoding="utf-8") == "bbb\n"


def test_executor_unknown_blocker_refuses(tmp_path: Path) -> None:
    repo = _exec_repo(tmp_path, {"victim.txt": "move me\n"})
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv", repo, [("victim.txt", ("T9:someday",), ())]
    )
    completed = _run_executor(manifest, repo, tmp_path / "inverse.json")
    assert completed.returncode == 1, completed.stdout
    assert "unknown blocker" in completed.stdout
    _tree_unchanged(repo)


def test_executor_unverified_foreign_blocker_refuses(tmp_path: Path) -> None:
    """A T5 dep-drop claim with no verifiable evidence (no Core pyproject at
    HEAD) is an unverified foreign closure — the batch is refused."""
    repo = _exec_repo(tmp_path, {"victim.txt": "move me\n"})
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv", repo, [("victim.txt", ("T5:core-dep-drop",), ())]
    )
    completed = _run_executor(manifest, repo, tmp_path / "inverse.json")
    assert completed.returncode == 1, completed.stdout
    assert "T5:core-dep-drop" in completed.stdout
    _tree_unchanged(repo)


def test_executor_verified_foreign_closure_allows(tmp_path: Path) -> None:
    """The same T5 dep-drop id passes once its closure evidence holds at HEAD
    (Core pyproject names none of the closed dependencies)."""
    repo = _exec_repo(
        tmp_path,
        {
            "victim.txt": "move me\n",
            "services/core/pyproject.toml": "[project]\nname = 'ksi-core'\n",
        },
    )
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv", repo, [("victim.txt", ("T5:core-dep-drop",), ())]
    )
    completed = _run_executor(manifest, repo, tmp_path / "inverse.json")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _tree_unchanged(repo)


def test_executor_live_reference_refuses(tmp_path: Path) -> None:
    """An active non-docs file still naming the moving path keeps the T6
    consumer-review blocker open — the whole batch is refused."""
    repo = _exec_repo(
        tmp_path, {"victim.txt": "move me\n", "live.py": "REF = 'victim.txt'\n"}
    )
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv",
        repo,
        [("victim.txt", ("T6:consumer-review:victim.txt",), ())],
    )
    completed = _run_executor(manifest, repo, tmp_path / "inverse.json")
    assert completed.returncode == 1, completed.stdout
    assert "live.py" in completed.stdout
    _tree_unchanged(repo)


def test_executor_docs_mention_is_tolerated(tmp_path: Path) -> None:
    """Docs/``*.md`` hits are intentional historical mentions, not live
    references — they do not block the batch."""
    repo = _exec_repo(
        tmp_path, {"victim.txt": "move me\n", "notes.md": "moved victim.txt here\n"}
    )
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv",
        repo,
        [("victim.txt", ("T6:consumer-review:victim.txt",), ())],
    )
    completed = _run_executor(manifest, repo, tmp_path / "inverse.json")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    _tree_unchanged(repo)


def test_executor_stale_consumer_refuses(tmp_path: Path) -> None:
    repo = _exec_repo(tmp_path, {"victim.txt": "move me\n"})
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv", repo, [("victim.txt", (), ("ghost/consumer.py",))]
    )
    completed = _run_executor(manifest, repo, tmp_path / "inverse.json")
    assert completed.returncode == 1, completed.stdout
    assert "stale consumer" in completed.stdout
    _tree_unchanged(repo)


def test_executor_misnamed_consumer_review_refuses(tmp_path: Path) -> None:
    repo = _exec_repo(tmp_path, {"victim.txt": "move me\n"})
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv",
        repo,
        [("victim.txt", ("T6:consumer-review:other.txt",), ())],
    )
    completed = _run_executor(manifest, repo, tmp_path / "inverse.json")
    assert completed.returncode == 1, completed.stdout
    _tree_unchanged(repo)


def test_executor_destination_collision_refuses(tmp_path: Path) -> None:
    repo = _exec_repo(tmp_path, {"victim.txt": "move me\n"})
    target = repo / "archive" / "acquisition-2026" / "victim.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("already here\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "pre-existing destination")
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv", repo, [("victim.txt", (), ())]
    )
    completed = _run_executor(manifest, repo, tmp_path / "inverse.json")
    assert completed.returncode == 1, completed.stdout
    assert "already exists" in completed.stdout
    assert (repo / "victim.txt").read_text(encoding="utf-8") == "move me\n"


def test_executor_hostile_manifest_refuses(tmp_path: Path) -> None:
    """A traversal path in a hostile manifest leaves the tree unchanged."""
    repo = _exec_repo(tmp_path, {"victim.txt": "move me\n"})
    manifest = tmp_path / "hostile.csv"
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(_exec.DECISION_COLUMNS))
        writer.writeheader()
        writer.writerow(
            {
                "path": "../evil.txt",
                "git_object": "0" * 40,
                "blob_sha256": "f" * 64,
                "baseline_git_object": "0" * 40,
                "baseline_sha256": "f" * 64,
                "group": "edge/root",
                "decision": "MOVE",
                "destination": f"{ARCHIVE_PREFIX}../evil.txt",
                "blockers": "",
                "consumers": "",
            }
        )
    completed = _run_executor(manifest, repo, tmp_path / "inverse.json")
    assert completed.returncode == 1, completed.stdout
    _tree_unchanged(repo)
    assert not (tmp_path / "evil.txt").exists()


def test_executor_apply_moves_and_inverse_round_trips(tmp_path: Path) -> None:
    """``--apply`` moves every row blob-identical, writes the durable inverse
    record, and the recorded inverses restore the exact pre-move bytes."""
    repo = _exec_repo(tmp_path, {"a.txt": "aaa\n", "sub/b.txt": "bbb\n"})
    before = {
        rel: (repo / rel).read_bytes() for rel in ("a.txt", "sub/b.txt")
    }
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv",
        repo,
        [("a.txt", (), ()), ("sub/b.txt", (), ())],
    )
    inverse = tmp_path / "inverse.json"
    completed = _run_executor(manifest, repo, inverse, apply=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "inverse record" in completed.stdout
    for rel in ("a.txt", "sub/b.txt"):
        assert not (repo / rel).exists(), rel
        moved = repo / ARCHIVE_PREFIX / rel
        assert moved.read_bytes() == before[rel], rel
    import json as _json

    record = _json.loads(inverse.read_text(encoding="utf-8"))
    assert record["manifest_sha256"] == (
        __import__("hashlib").sha256(manifest.read_bytes()).hexdigest()
    )
    assert len(record["moves"]) == 2
    for entry in record["moves"]:
        assert set(entry) == {
            "path",
            "destination",
            "git_object",
            "blob_sha256",
            "inverse",
        }
        assert entry["destination"] == f"{ARCHIVE_PREFIX}{entry['path']}"
    for entry in record["moves"]:
        done = subprocess.run(
            ["git", "mv", entry["destination"], entry["path"]],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0
    for rel, content in before.items():
        assert (repo / rel).read_bytes() == content, rel


def test_executor_machinery_and_console_exemptions_are_explicit(tmp_path: Path) -> None:
    """Manifest machinery paths and P4-owned Console paths are explicitly
    exempt from the live-reference scan (documented in the tool, never
    silent) — their mentions do not block the batch."""
    repo = _exec_repo(
        tmp_path,
        {
            "victim.txt": "move me\n",
            "tools/prepare_physical_site_moves.py": "DATA = 'victim.txt'\n",
            "apps/dashboard/src/view.ts": "REF = 'victim.txt'\n",
        },
    )
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv",
        repo,
        [("victim.txt", ("T6:consumer-review:victim.txt",), ())],
    )
    completed = _run_executor(manifest, repo, tmp_path / "inverse.json")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert set(_exec._MACHINERY_PATHS) == {
        "tools/prepare_physical_site_moves.py",
        "tools/execute_physical_site_moves.py",
        "tests/contract/test_physical_site_move_tooling.py",
    }
    assert _exec._TRANSITIONAL_PREFIXES == ("apps/dashboard/",)


def test_executor_destination_reference_is_not_a_live_reference(tmp_path: Path) -> None:
    """Naming the archived destination (``archive/acquisition-2026/<path>``)
    is the correct post-move spelling — it must not block the batch."""
    repo = _exec_repo(
        tmp_path,
        {
            "victim.txt": "move me\n",
            "route.py": "DEST = 'archive/acquisition-2026/victim.txt'\n",
        },
    )
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv",
        repo,
        [("victim.txt", ("T6:consumer-review:victim.txt",), ())],
    )
    completed = _run_executor(manifest, repo, tmp_path / "inverse.json")
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_executor_historical_route_exemption_is_explicit(tmp_path: Path) -> None:
    """The bounded historical workflow operates on archived content by design
    — its references are the sanctioned, explicitly listed exception."""
    repo = _exec_repo(
        tmp_path,
        {
            "victim.txt": "move me\n",
            ".github/workflows/historical-archive.yml": "uses 'victim.txt'\n",
        },
    )
    manifest = _write_decision_manifest(
        tmp_path / "moves.csv",
        repo,
        [("victim.txt", ("T6:consumer-review:victim.txt",), ())],
    )
    completed = _run_executor(manifest, repo, tmp_path / "inverse.json")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert _exec._HISTORICAL_ROUTE_PATHS == (".github/workflows/historical-archive.yml",)
