"""Contract regression for the frozen physical-site disposition inventory (Task 2).

The validator under test is ``tools/check_physical_site_disposition.py``. The
real baseline CSV is planning-only inventory: these tests assert it binds every
frozen Git entry exactly once and refuse hostile/malformed variants exercised
through disposable local synthetic Git fixtures (no edits to the real CSV, no
network, runnable without the full baseline history).
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.check_physical_site_disposition import (  # noqa: E402
    EXPECTED_BASELINE,
    EXPECTED_COLUMNS,
    validate_disposition_manifest,
)

REAL_MANIFEST = ROOT / "docs/audit/PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_fixture_repo(tmp_path: Path) -> Path:
    """Disposable synthetic Git fixture: one normal file, one protected-path
    file (``.ai/`` boundary) and one gitlink, committed once."""
    repo = tmp_path / "fixture-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "fixture")
    (repo / "keep.md").write_text("platform content\n", encoding="utf-8")
    (repo / ".ai").mkdir()
    (repo / ".ai" / "PRIVATE-CANARY-ZK7Q").write_text(
        "DO-NOT-DELIVER-CANARY-ZK7Q\n", encoding="utf-8"
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "fixture baseline")
    nested = tmp_path / "nested-repo"
    nested.mkdir()
    _git(nested, "init", "-q")
    _git(nested, "config", "user.email", "fixture@example.invalid")
    _git(nested, "config", "user.name", "fixture")
    (nested / "note.md").write_text("nested\n", encoding="utf-8")
    _git(nested, "add", ".")
    _git(nested, "commit", "-qm", "nested")
    nested_sha = _git(nested, "rev-parse", "HEAD")
    # Local-path fetch only (no network): materialize the foreign commit object
    # so the fixture gitlink resolves its Git type like an initialized submodule.
    _git(repo, "fetch", "-q", str(nested), "HEAD")
    _git(repo, "update-index", "--add", "--cacheinfo", "160000", nested_sha, "refs/ext")
    _git(repo, "commit", "-qm", "fixture baseline with gitlink")
    return repo


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


def _valid_fixture_rows(root: Path) -> list[dict[str, str]]:
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
            rows.append(
                {
                    "path": path,
                    "baselineCommit": baseline,
                    "gitMode": mode,
                    "gitObject": obj,
                    "sha256": _blob_sha256(root, obj),
                    "proposedDisposition": "RETAIN",
                    "proposedDestination": path,
                    "requiredBeforeAction": "Preserve verified consumer",
                }
            )
    return rows


def _check(repo: Path, manifest: Path) -> list[str]:
    """Validate against the fixture repo's own frozen commit."""
    return validate_disposition_manifest(repo, manifest, baseline=_git(repo, "rev-parse", "HEAD"))


def test_exact_baseline_coverage_and_hashes() -> None:
    """Every frozen baseline Git entry appears exactly once; normal files bind
    Git object and SHA256; protected rows carry no content hash."""
    findings = validate_disposition_manifest(ROOT, REAL_MANIFEST)
    assert findings == [], "\n".join(findings[:10])

    with REAL_MANIFEST.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2378
    assert len({row["path"] for row in rows}) == 2378

    protected = [row for row in rows if row["proposedDisposition"] == "PROTECT"]
    assert len(protected) == 82
    assert all(row["sha256"] == "" for row in protected)

    candidates = [row for row in rows if row["proposedDisposition"] == "ARCHIVE_CANDIDATE"]
    assert len(candidates) == 194
    # A candidate row is planning-only inventory, never execution approval:
    # no candidate destination may equal its current path.
    assert all(row["proposedDestination"] != row["path"] for row in candidates)


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
