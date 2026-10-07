"""Contract regression for the frozen physical-site disposition inventory (Task 2).

The validator under test is ``tools/check_physical_site_disposition.py``.
History-free guarantees (frozen-CSV pins, malformed-input handling) run
without any baseline Git history; complete Git-object binding is exercised on
disposable local synthetic Git fixtures (no edits to the real CSV, no
network). The real default CLI on the full checkout remains the authoritative
full-history check and is re-run independently (Task 4).
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_validator() -> Any:
    """Load the real validator tool by file location (repository dynamic-loader
    pattern): no static ``tools.`` import for checkers to double-count, and no
    lingering ``sys.path`` mutation."""
    tool_path = ROOT / "tools" / "check_physical_site_disposition.py"
    spec = importlib.util.spec_from_file_location("check_physical_site_disposition", tool_path)
    assert spec is not None and spec.loader is not None, tool_path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_tool = _load_validator()
EXPECTED_BASELINE = _tool.EXPECTED_BASELINE
EXPECTED_COLUMNS = _tool.EXPECTED_COLUMNS
validate_disposition_manifest = _tool.validate_disposition_manifest

REAL_MANIFEST = ROOT / "docs/audit/PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv"
REAL_CSV_SHA256 = "89a9baf3b1f1a593bf65af02810595cea0f677a740ceb0fdf9f2e789071639e3"
TOOL = ROOT / "tools/check_physical_site_disposition.py"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_full_fixture_repo(tmp_path: Path, *, materialize_gitlink: bool = True) -> Path:
    """Full-coverage synthetic repo: normal + executable files, an archive
    candidate, a symlink to an absent/outside canary target, a protected
    ``.ai/`` file, and a foreign gitlink (materialized only on request)."""
    import os

    repo = tmp_path / "full-fixture-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "fixture")
    (repo / "keep.md").write_text("platform content\n", encoding="utf-8")
    runner = repo / "run.sh"
    runner.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    os.chmod(runner, 0o755)
    (repo / "archive-me.md").write_text("to archive\n", encoding="utf-8")
    (repo / ".ai").mkdir()
    (repo / ".ai" / "PRIVATE-CANARY-ZK7Q").write_text(
        "DO-NOT-DELIVER-CANARY-ZK7Q\n", encoding="utf-8"
    )
    os.symlink("../CANARY-OUTSIDE-ZK7Q-target", repo / "link-to-absent")
    _git(repo, "add", ".")
    nested = tmp_path / "nested-repo"
    nested.mkdir(exist_ok=True)
    _git(nested, "init", "-q")
    _git(nested, "config", "user.email", "fixture@example.invalid")
    _git(nested, "config", "user.name", "fixture")
    (nested / "note.md").write_text("nested\n", encoding="utf-8")
    _git(nested, "add", ".")
    _git(nested, "commit", "-qm", "nested")
    nested_sha = _git(nested, "rev-parse", "HEAD")
    if materialize_gitlink:
        # Local-path fetch only (no network).
        _git(repo, "fetch", "-q", str(nested), "HEAD")
    _git(repo, "update-index", "--add", "--cacheinfo", "160000", nested_sha, "refs/ext")
    _git(repo, "commit", "-qm", "full fixture baseline")
    return repo


def _make_fixture_repo(tmp_path: Path) -> Path:
    """Standard synthetic fixture with a materialized gitlink (covers keep.md,
    the protected ``.ai/`` boundary and ``refs/ext``)."""
    return _make_full_fixture_repo(tmp_path, materialize_gitlink=True)


def _baseline_rows(root: Path) -> dict[str, tuple[str, str]]:
    """Trusted {path: (mode, object)} map straight from fixture Git history."""
    out = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    rows: dict[str, tuple[str, str]] = {}
    for entry in out.decode("utf-8").split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t")
        mode, _kind, obj = meta.split(" ")
        rows[path] = (mode, obj)
    return rows


def _blob_sha256(root: Path, obj: str) -> str:
    import hashlib

    raw = subprocess.run(
        ["git", "cat-file", "blob", obj], cwd=root, check=True, capture_output=True
    ).stdout
    return hashlib.sha256(raw).hexdigest()


def _write_manifest(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=EXPECTED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _valid_fixture_rows(
    root: Path, overrides: dict[str, tuple[str, str, str]] | None = None
) -> list[dict[str, str]]:
    """Manifest rows binding every fixture baseline entry. ``overrides`` maps
    path -> (disposition, destination, condition) for non-protected rows."""
    baseline = _git(root, "rev-parse", "HEAD")
    trusted = _baseline_rows(root)
    rows: list[dict[str, str]] = []
    for path, (mode, obj) in sorted(trusted.items()):
        if path.startswith(".ai/") or mode == "160000":
            rows.append(
                {
                    "path": path,
                    "baselineCommit": baseline,
                    "gitMode": mode,
                    "gitObject": obj,
                    "sha256": "",
                    "proposedDisposition": "PROTECT",
                    "proposedDestination": path,
                    "requiredBeforeAction": "No reads/moves; pointer/provenance only",
                }
            )
        else:
            disposition, destination, condition = (overrides or {}).get(
                path, ("RETAIN", path, "Preserve verified consumer")
            )
            rows.append(
                {
                    "path": path,
                    "baselineCommit": baseline,
                    "gitMode": mode,
                    "gitObject": obj,
                    "sha256": _blob_sha256(root, obj),
                    "proposedDisposition": disposition,
                    "proposedDestination": destination,
                    "requiredBeforeAction": condition,
                }
            )
    return rows


def _check(repo: Path, manifest: Path) -> list[str]:
    """Validate against the fixture repo's own frozen commit."""
    return validate_disposition_manifest(repo, manifest, baseline=_git(repo, "rev-parse", "HEAD"))


def test_frozen_csv_static_integrity() -> None:
    """History-free pins on the frozen planning CSV: SHA256, exact columns,
    2378 unique rows, baseline refs, mode/object/digest formats, 82 PROTECT
    rows without hashes, 194 candidates with exact archive destinations."""
    assert hashlib.sha256(REAL_MANIFEST.read_bytes()).hexdigest() == REAL_CSV_SHA256, (
        "frozen CSV bytes changed"
    )

    with REAL_MANIFEST.open(newline="", encoding="utf-8") as stream:
        reader = csv.reader(stream)
        assert next(reader) == EXPECTED_COLUMNS
        rows = list(reader)
    assert len(rows) == 2378
    assert len({row[0] for row in rows}) == 2378

    import re

    hex40 = re.compile(r"[0-9a-f]{40}").fullmatch
    hex64 = re.compile(r"[0-9a-f]{64}").fullmatch
    protected = candidates = 0
    for fields in rows:
        assert len(fields) == 8, fields[0]
        path, commit, mode, obj, digest, disp, dest, cond = fields
        assert commit == EXPECTED_BASELINE and hex40(commit), path
        assert mode in ("100644", "100755", "120000", "160000"), path
        assert hex40(obj), path
        assert cond, path
        if disp == "PROTECT":
            protected += 1
            assert digest == "", path
            assert dest == path, path
        elif disp == "ARCHIVE_CANDIDATE":
            candidates += 1
            assert hex64(digest), path
            assert dest == f"archive/acquisition-2026/{path}", path
        elif disp in ("RECONCILE", "RETAIN", "RECONCILE_DOCUMENT"):
            assert hex64(digest), path
            assert dest == path, path
        else:
            raise AssertionError(f"unknown disposition {disp} at {path}")
    assert protected == 82
    assert candidates == 194


def test_synthetic_baseline_full_coverage_and_hashes(tmp_path: Path) -> None:
    """Complete Git-object binding on a valid local synthetic repo: every
    baseline entry (regular, executable, symlink link-text, candidate,
    protected file, gitlink) appears exactly once and validates clean."""
    repo = _make_full_fixture_repo(tmp_path)
    trusted = _baseline_rows(repo)
    assert trusted["run.sh"][0] == "100755"
    assert trusted["link-to-absent"][0] == "120000"
    assert trusted["refs/ext"][0] == "160000"

    rows = _valid_fixture_rows(
        repo,
        {
            "archive-me.md": (
                "ARCHIVE_CANDIDATE",
                "archive/acquisition-2026/archive-me.md",
                "Extract platform consumers first",
            )
        },
    )
    assert len(rows) == len(trusted)
    findings = _check(repo, _write_manifest(tmp_path / "full.csv", rows))
    assert findings == [], "\n".join(findings[:10])

    # Hostile mutations of the valid synthetic manifest are each refused.
    mutated = [dict(row) for row in rows]
    for row in mutated:
        if row["path"] == "archive-me.md":
            row["proposedDestination"] = "archive-me.md"
    findings = _check(repo, _write_manifest(tmp_path / "full-bad-dest.csv", mutated))
    assert any("archive-me.md" in finding for finding in findings), findings


def test_duplicate_missing_and_unknown_rows_are_refused(tmp_path: Path) -> None:
    repo = _make_fixture_repo(tmp_path)
    baseline = _git(repo, "rev-parse", "HEAD")

    rows = _valid_fixture_rows(repo)
    assert _check(repo, _write_manifest(tmp_path / "ok.csv", rows)) == []

    duplicated = rows + [dict(rows[0])]
    findings = _check(repo, _write_manifest(tmp_path / "dup.csv", duplicated))
    assert any("duplicate" in finding for finding in findings), findings

    dropped = [row for row in rows if row["path"] != "keep.md"]
    findings = _check(repo, _write_manifest(tmp_path / "drop.csv", dropped))
    assert any("keep.md" in finding and "omit" in finding for finding in findings), findings

    extra = rows + [
        {
            "path": "invented.md",
            "baselineCommit": baseline,
            "gitMode": "100644",
            "gitObject": "0" * 40,
            "sha256": "0" * 64,
            "proposedDisposition": "RETAIN",
            "proposedDestination": "invented.md",
            "requiredBeforeAction": "x",
        }
    ]
    findings = _check(repo, _write_manifest(tmp_path / "extra.csv", extra))
    assert any("invented.md" in finding for finding in findings), findings


def test_absolute_and_parent_paths_are_refused(tmp_path: Path) -> None:
    repo = _make_fixture_repo(tmp_path)
    baseline = _git(repo, "rev-parse", "HEAD")
    trusted = _baseline_rows(repo)
    mode, obj = trusted["keep.md"]

    def _row(path: str) -> dict[str, str]:
        return {
            "path": path,
            "baselineCommit": baseline,
            "gitMode": mode,
            "gitObject": obj,
            "sha256": _blob_sha256(repo, obj),
            "proposedDisposition": "RETAIN",
            "proposedDestination": path,
            "requiredBeforeAction": "x",
        }

    for hostile in (
        "/etc/passwd",
        "../escape.md",
        "a/../../escape.md",
        "./keep.md",
        "sub//keep.md",
    ):
        manifest = _write_manifest(tmp_path / "hostile.csv", [_row(hostile)])
        findings = _check(repo, manifest)
        assert findings, hostile
        assert any("keep.md" in finding or hostile in finding for finding in findings), findings


def test_candidate_requires_archive_destination_and_condition(tmp_path: Path) -> None:
    repo = _make_fixture_repo(tmp_path)
    baseline = _git(repo, "rev-parse", "HEAD")
    trusted = _baseline_rows(repo)
    mode, obj = trusted["keep.md"]

    def _candidate(destination: str, condition: str) -> dict[str, str]:
        return {
            "path": "keep.md",
            "baselineCommit": baseline,
            "gitMode": mode,
            "gitObject": obj,
            "sha256": _blob_sha256(repo, obj),
            "proposedDisposition": "ARCHIVE_CANDIDATE",
            "proposedDestination": destination,
            "requiredBeforeAction": condition,
        }

    def _manifest_with(name: str, candidate: dict[str, str]) -> Path:
        rows = [row for row in _valid_fixture_rows(repo) if row["path"] != "keep.md"]
        rows.append(candidate)
        return _write_manifest(tmp_path / name, rows)

    ok = _manifest_with(
        "candidate-ok.csv",
        _candidate("archive/acquisition-2026/keep.md", "Extract platform consumers first"),
    )
    assert _check(repo, ok) == []

    bad_destination = _manifest_with("candidate-dest.csv", _candidate("keep.md", "x"))
    findings = _check(repo, bad_destination)
    assert any("destination" in finding for finding in findings), findings

    bad_condition = _manifest_with(
        "candidate-cond.csv",
        _candidate("archive/acquisition-2026/keep.md", ""),
    )
    findings = _check(repo, bad_condition)
    assert any(
        "condition" in finding or "requiredBeforeAction" in finding for finding in findings
    ), findings


def test_protected_gitlinks_are_not_traversed(tmp_path: Path) -> None:
    repo = _make_fixture_repo(tmp_path)
    rows = _valid_fixture_rows(repo)
    manifest = _write_manifest(tmp_path / "protected.csv", rows)
    findings = _check(repo, manifest)
    assert findings == [], findings
    # The private canary bytes must never leak into validator output.
    assert "CANARY-ZK7Q" not in "\n".join(findings)

    # A hostile label must not promote an ordinary source into PROTECT to
    # bypass content hashing.
    promoted = [dict(row) for row in rows]
    for row in promoted:
        if row["path"] == "keep.md":
            row["proposedDisposition"] = "PROTECT"
            row["sha256"] = ""
    findings = _check(repo, _write_manifest(tmp_path / "promoted.csv", promoted))
    assert any("keep.md" in finding and "PROTECT" in finding for finding in findings), findings

    # Nor may a protected source be relabeled to smuggle out a content hash.
    demoted = [dict(row) for row in rows]
    for row in demoted:
        if row["path"] == "refs/ext":
            row["proposedDisposition"] = "RETAIN"
            row["sha256"] = "0" * 64
            row["proposedDestination"] = "refs/ext"
    findings = _check(repo, _write_manifest(tmp_path / "demoted.csv", demoted))
    assert any("refs/ext" in finding for finding in findings), findings


def test_stale_object_or_digest_is_refused(tmp_path: Path) -> None:
    repo = _make_fixture_repo(tmp_path)
    rows = _valid_fixture_rows(repo)

    stale_object = [dict(row) for row in rows]
    for row in stale_object:
        if row["path"] == "keep.md":
            row["gitObject"] = "0" * 40
    findings = _check(repo, _write_manifest(tmp_path / "stale-obj.csv", stale_object))
    assert any("keep.md" in finding for finding in findings), findings

    stale_digest = [dict(row) for row in rows]
    for row in stale_digest:
        if row["path"] == "keep.md":
            row["sha256"] = "f" * 64
    findings = _check(repo, _write_manifest(tmp_path / "stale-digest.csv", stale_digest))
    assert any("keep.md" in finding for finding in findings), findings

    wrong_baseline = [dict(row) for row in rows]
    for row in wrong_baseline:
        if row["path"] == "keep.md":
            row["baselineCommit"] = "0" * 40
    findings = _check(repo, _write_manifest(tmp_path / "stale-commit.csv", wrong_baseline))
    assert any("keep.md" in finding for finding in findings), findings


def test_missing_baseline_history_fails_clearly(tmp_path: Path) -> None:
    """A manifest whose baseline commit is absent locally (e.g. shallow CI)
    fails with an explicit prerequisite message, never a silent skip."""
    manifest = _write_manifest(
        tmp_path / "nostory.csv",
        [
            {
                "path": "keep.md",
                "baselineCommit": EXPECTED_BASELINE,
                "gitMode": "100644",
                "gitObject": "0" * 40,
                "sha256": "0" * 64,
                "proposedDisposition": "RETAIN",
                "proposedDestination": "keep.md",
                "requiredBeforeAction": "x",
            }
        ],
    )
    findings = validate_disposition_manifest(tmp_path, manifest)
    assert findings, "absent baseline history must fail, not pass or skip"
    assert any(EXPECTED_BASELINE in finding for finding in findings), findings


def test_malformed_bytes_quotes_and_oversize_fields_are_controlled_findings(
    tmp_path: Path,
) -> None:
    """Binary/quote/oversize manifests return ``list[str]`` findings — never a
    traceback — and the real CLI exits 1 in finding format."""
    binary = tmp_path / "binary.csv"
    binary.write_bytes(b"path,baselineCommit\n\xff\xfe\x00binary\n")
    findings = validate_disposition_manifest(tmp_path, binary)
    assert isinstance(findings, list) and findings, findings
    assert any("UTF-8" in finding for finding in findings), findings

    quoted = tmp_path / "quoted.csv"
    quoted.write_text(
        ",".join(EXPECTED_COLUMNS)
        + '\nkeep.md,"unclosed quote,100644,'
        + "0" * 40
        + ","
        + "0" * 64
        + ",RETAIN,keep.md,x\n",
        encoding="utf-8",
    )
    findings = validate_disposition_manifest(tmp_path, quoted)
    assert isinstance(findings, list) and findings, findings
    assert any("CSV parse" in finding for finding in findings), findings

    oversize = tmp_path / "oversize.csv"
    big = "x" * (csv.field_size_limit() + 1024)
    oversize.write_text(
        ",".join(EXPECTED_COLUMNS)
        + f"\nkeep.md,{EXPECTED_BASELINE},100644,"
        + "0" * 40
        + ","
        + "0" * 64
        + ",RETAIN,keep.md,"
        + big
        + "\n",
        encoding="utf-8",
    )
    findings = validate_disposition_manifest(tmp_path, oversize)
    assert isinstance(findings, list) and findings, findings
    assert any("CSV parse" in finding for finding in findings), findings

    # Real CLI on the binary manifest: exit 1, finding format, no traceback.
    completed = subprocess.run(
        [sys.executable, str(TOOL), "--manifest", str(binary)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1, completed.stdout
    assert "Traceback" not in completed.stderr, completed.stderr
    assert "no moves authorized" in completed.stdout, completed.stdout


def test_unavailable_git_and_truncated_plumbing_fail_clearly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing git and corrupt plumbing output yield findings, never a false
    pass, an exception, or leaked content. Faults are injected around the real
    subprocess transport; validator parsing/handling stays real."""
    repo = _make_fixture_repo(tmp_path)
    rows = _valid_fixture_rows(repo)
    manifest = _write_manifest(tmp_path / "ok.csv", rows)
    baseline = _git(repo, "rev-parse", "HEAD")

    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("PATH", str(empty_bin))
    findings = validate_disposition_manifest(repo, manifest, baseline=baseline)
    assert isinstance(findings, list) and findings, findings
    assert any("git" in finding.lower() for finding in findings), findings

    monkeypatch.undo()
    real_run = subprocess.run

    def _truncate_batch(*args: Any, **kwargs: Any) -> Any:
        completed = real_run(*args, **kwargs)
        if args[0][:3] == ["git", "cat-file", "--batch"]:
            completed.stdout = completed.stdout[:5]
        return completed

    monkeypatch.setattr(subprocess, "run", _truncate_batch)
    findings = validate_disposition_manifest(repo, manifest, baseline=baseline)
    assert isinstance(findings, list) and findings, findings
    assert "CANARY-ZK7Q" not in "\n".join(findings), findings


def test_unmaterialized_gitlink_and_symlink_are_metadata_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A foreign gitlink commit absent locally passes by Git metadata only,
    and a symlink binds its link text while its (absent, outside) target is
    never read. Content-object requests are observed on the real helper."""
    repo = _make_full_fixture_repo(tmp_path, materialize_gitlink=False)
    trusted = _baseline_rows(repo)
    assert trusted["refs/ext"][0] == "160000"
    assert trusted["link-to-absent"][0] == "120000"
    assert not (repo / "../CANARY-OUTSIDE-ZK7Q-target").exists()

    requested: list[str] = []
    real_run = subprocess.run

    def _observe(*args: Any, **kwargs: Any) -> Any:
        if args[0][:3] == ["git", "cat-file", "--batch"] and kwargs.get("input"):
            requested.append(kwargs["input"].decode("ascii", errors="replace"))
        return real_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _observe)
    rows = _valid_fixture_rows(
        repo,
        {
            "archive-me.md": (
                "ARCHIVE_CANDIDATE",
                "archive/acquisition-2026/archive-me.md",
                "Extract platform consumers first",
            )
        },
    )
    findings = _check(repo, _write_manifest(tmp_path / "meta-only.csv", rows))
    assert findings == [], "\n".join(findings[:10])

    content_objects = " ".join(requested)
    gitlink_obj = trusted["refs/ext"][1]
    assert gitlink_obj not in content_objects, "gitlink content was requested"
    protected_obj = trusted[".ai/PRIVATE-CANARY-ZK7Q"][1]
    assert protected_obj not in content_objects, "protected content was requested"
    assert "CANARY-ZK7Q" not in "\n".join(findings), findings


def test_duplicate_and_malformed_headers_are_refused(tmp_path: Path) -> None:
    """Duplicate, reordered, or extended headers are refused as findings."""
    repo = _make_fixture_repo(tmp_path)
    rows = _valid_fixture_rows(repo)

    def _with_header(header: list[str]) -> Path:
        path = tmp_path / "header.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(header)
            for row in rows:
                writer.writerow([row[column] for column in header if column in row])
        return path

    duplicated = EXPECTED_COLUMNS + ["path"]
    findings = _check(repo, _with_header(duplicated))
    assert any("header" in finding for finding in findings), findings

    reordered = list(reversed(EXPECTED_COLUMNS))
    findings = _check(repo, _with_header(reordered))
    assert any("header" in finding for finding in findings), findings

    extended = EXPECTED_COLUMNS + ["extra"]
    path = tmp_path / "extended.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(extended)
        for row in rows:
            writer.writerow([row.get(column, "x") for column in extended])
    findings = _check(repo, path)
    assert any("header" in finding for finding in findings), findings


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
