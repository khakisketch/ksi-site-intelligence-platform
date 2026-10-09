"""Read-only full-record archive/recovery verification (P5 Task 1).

Disposable Git histories carry independently generated blobs and committed move
records. Corruptions target the final record so sampling cannot pass. No archived
code is imported and no real checkout source, manifest or journal is edited.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/verify_physical_site_archive.py"
PREFIX = "archive/acquisition-2026/"


def _verify(root: Path) -> dict[str, Any]:
    # An explicit assertion makes the missing behavior a test failure, not a
    # collection/import error; once present, exercise the actual tool function.
    assert TOOL.is_file(), "read-only complete-record archive checker is missing"
    spec = importlib.util.spec_from_file_location("archive_verifier_under_test", TOOL)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool.verify_archive_records(root, root / "execution.json", root / "extras.json")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout.strip()


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def archive_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "archive fixture")
    _git(root, "config", "user.email", "archive@example.invalid")
    inputs = (
        ("edge/one.txt", b"first baseline blob\n"),
        ("packages/mission-planning/second.txt", b"second baseline blob\n"),
        ("tools/edge/last.txt", b"last extra blob\n"),
    )
    for source, content in inputs:
        target = root / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "owned synthetic source baseline")
    baseline = _git(root, "rev-parse", "HEAD")
    records = []
    for source, content in inputs:
        destination = PREFIX + source
        records.append(
            {
                "path": source,
                "destination": destination,
                "git_object": _git(root, "rev-parse", f"HEAD:{source}"),
                "blob_sha256": hashlib.sha256(content).hexdigest(),
                "inverse": f"git mv {destination} {source}",
            }
        )
        target = root / destination
        target.parent.mkdir(parents=True, exist_ok=True)
        (root / source).rename(target)
    manifest = root / "decisions.csv"
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["path", "destination", "git_object", "blob_sha256", "decision"]
        )
        writer.writeheader()
        writer.writerows(
            {key: value for key, value in record.items() if key != "inverse"} | {"decision": "MOVE"}
            for record in records[:2]
        )
    _write_json(
        root / "execution.json",
        {
            "manifest": "decisions.csv",
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "head_before": baseline,
            "moves": records[:2],
        },
    )
    _write_json(root / "extras.json", records[2:])
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "archive with immutable inverse records")
    return root


def _last(root: Path) -> dict[str, str]:
    return json.loads((root / "extras.json").read_text())[0]


def _assert_last_failure(report: dict[str, Any], code: str) -> None:
    assert report["recordsChecked"] == 3
    assert len(report["records"]) == 3
    assert report["records"][-1]["failures"], report
    assert any(code in failure for failure in report["failures"]), report


def test_visits_every_record(archive_repo: Path) -> None:
    """Skipping the extras/final row must not produce a green count."""
    report = _verify(archive_repo)
    assert report["failures"] == []
    assert report["recordsChecked"] == 3
    assert [record["path"] for record in report["records"]] == [
        "edge/one.txt", "packages/mission-planning/second.txt", "tools/edge/last.txt"
    ]
    assert report["records"][-1]["destinationSha256"] == hashlib.sha256(
        b"last extra blob\n"
    ).hexdigest()
    (archive_repo / _last(archive_repo)["destination"]).write_bytes(b"corrupt final record\n")
    _assert_last_failure(_verify(archive_repo), "DESTINATION_HASH_MISMATCH")


@pytest.mark.parametrize("corruption", ["missing", "changed"])
def test_missing_or_changed_destination_fails(archive_repo: Path, corruption: str) -> None:
    destination = archive_repo / _last(archive_repo)["destination"]
    if corruption == "missing":
        destination.unlink()
    else:
        destination.write_bytes(b"not the recorded source\n")
    _assert_last_failure(
        _verify(archive_repo),
        "DESTINATION_UNREADABLE" if corruption == "missing" else "DESTINATION_HASH_MISMATCH",
    )


@pytest.mark.parametrize("corruption", ["duplicate", "escape", "absolute", "noncanonical"])
def test_duplicate_or_escaping_destination_fails(archive_repo: Path, corruption: str) -> None:
    record = _last(archive_repo)
    if corruption == "duplicate":
        record["destination"] = PREFIX + "edge/one.txt"
    else:
        record["destination"] = {
            "escape": "../outside.txt",
            "absolute": "/outside.txt",
            "noncanonical": PREFIX + "tools/edge/../last.txt",
        }[corruption]
    _write_json(archive_repo / "extras.json", [record])
    _assert_last_failure(
        _verify(archive_repo),
        "DUPLICATE_DESTINATION" if corruption == "duplicate" else "UNSAFE_DESTINATION",
    )


@pytest.mark.parametrize("corruption", ["blob", "digest", "inverse", "injection"])
def test_wrong_git_blob_or_inverse_fails(archive_repo: Path, corruption: str) -> None:
    record = _last(archive_repo)
    if corruption == "blob":
        record["git_object"] = _git(archive_repo, "rev-parse", f"HEAD:{PREFIX}edge/one.txt")
    elif corruption == "digest":
        record["blob_sha256"] = "0" * 64
    else:
        record["inverse"] += " wrong-source" if corruption == "inverse" else "; touch executed"
    _write_json(archive_repo / "extras.json", [record])
    _assert_last_failure(
        _verify(archive_repo),
        {"blob": "GIT_OBJECT_MISMATCH", "digest": "BLOB_HASH_MISMATCH"}.get(
            corruption, "INVERSE_MISMATCH"
        ),
    )
    assert not (archive_repo / "executed").exists()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*") if path.is_file() and not path.is_symlink()
    }


def test_does_not_mutate_checkout(archive_repo: Path) -> None:
    """Verification must not change manifests, index, refs, blobs or destinations."""
    before = _snapshot(archive_repo)
    status = _git(archive_repo, "status", "--porcelain")
    head = _git(archive_repo, "rev-parse", "HEAD")
    assert _verify(archive_repo)["failures"] == []
    assert _snapshot(archive_repo) == before
    assert _git(archive_repo, "status", "--porcelain") == status
    assert _git(archive_repo, "rev-parse", "HEAD") == head
    assert not (archive_repo / "tools/edge/last.txt").exists()


def test_committed_destination_edit_retains_independent_baseline_hash(archive_repo: Path) -> None:
    """HEAD divergence must fail without hiding whether the original blob survives."""
    record = _last(archive_repo)
    (archive_repo / record["destination"]).write_bytes(b"later archive adaptation\n")
    _git(archive_repo, "add", record["destination"])
    _git(archive_repo, "commit", "-qm", "explicit later historical adaptation")
    report = _verify(archive_repo)
    _assert_last_failure(report, "GIT_OBJECT_MISMATCH")
    assert report["records"][-1]["baselineSha256"] == hashlib.sha256(
        b"last extra blob\n"
    ).hexdigest()
    assert report["records"][-1]["destinationSha256"] == hashlib.sha256(
        b"later archive adaptation\n"
    ).hexdigest()


def test_previously_archived_extra_is_bound_without_rewriting_source_history(
    archive_repo: Path,
) -> None:
    """A prior extras batch can be bound at its archive path in head_before."""
    execution = archive_repo / "execution.json"
    value = json.loads(execution.read_text())
    for row in value["moves"]:
        (archive_repo / row["destination"]).rename(archive_repo / row["path"])
    _git(archive_repo, "add", ".")
    _git(archive_repo, "commit", "-qm", "extras already archived, main batch still original")
    value["head_before"] = _git(archive_repo, "rev-parse", "HEAD")
    for row in value["moves"]:
        (archive_repo / row["path"]).rename(archive_repo / row["destination"])
    _write_json(execution, value)
    _git(archive_repo, "add", ".")
    _git(archive_repo, "commit", "-qm", "main batch executed after extras")
    report = _verify(archive_repo)
    assert report["recordsChecked"] == 3
    assert report["failures"] == []


@pytest.mark.parametrize("row", [None, {}, {"path": 42}])
def test_malformed_final_record_is_visited(archive_repo: Path, row: object) -> None:
    _write_json(archive_repo / "extras.json", [row])
    _assert_last_failure(_verify(archive_repo), "MALFORMED_RECORD")


def test_record_input_symlink_cannot_supply_an_omitted_manifest(
    archive_repo: Path, tmp_path: Path,
) -> None:
    extras = archive_repo / "extras.json"
    outside = tmp_path / "outside-extras.json"
    outside.write_bytes(extras.read_bytes())
    extras.unlink()
    extras.symlink_to(outside)
    assert any(
        "extras: RECORD_FILE_UNREADABLE_OR_MALFORMED" in finding
        for finding in _verify(archive_repo)["failures"]
    )


@pytest.mark.parametrize("level", ["file", "parent"])
def test_symlink_never_supplies_destination_bytes(
    archive_repo: Path, tmp_path: Path, level: str
) -> None:
    record = _last(archive_repo)
    destination = archive_repo / record["destination"]
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "last.txt").write_bytes(b"last extra blob\n")
    destination.unlink()
    if level == "file":
        destination.symlink_to(outside / "last.txt")
    else:
        destination.parent.rmdir()
        destination.parent.symlink_to(outside, target_is_directory=True)
    _assert_last_failure(_verify(archive_repo), "DESTINATION_UNREADABLE")


@pytest.mark.parametrize("lane", ["execution", "extras"])
def test_omitted_record_fails_closed(archive_repo: Path, lane: str) -> None:
    path = archive_repo / f"{lane}.json"
    value = json.loads(path.read_text())
    if lane == "execution":
        value["moves"].pop()
    else:
        value.clear()
    _write_json(path, value)
    report = _verify(archive_repo)
    assert report["failures"]
    assert any("RECORDED_SET_MISMATCH" in item for item in report["failures"])


@pytest.mark.parametrize("lane", ["execution", "extras"])
def test_missing_or_malformed_record_file_fails_closed(archive_repo: Path, lane: str) -> None:
    path = archive_repo / f"{lane}.json"
    path.unlink()
    report = _verify(archive_repo)
    assert report["failures"]
    path.write_text("{malformed input", encoding="utf-8")
    assert _verify(archive_repo)["failures"]


def test_manifest_omission_and_baseline_substitution_fail(archive_repo: Path) -> None:
    execution = archive_repo / "execution.json"
    value = json.loads(execution.read_text())
    value["head_before"] = _git(archive_repo, "rev-parse", "HEAD")
    _write_json(execution, value)
    assert any("BASELINE_OBJECT_MISMATCH" in item for item in _verify(archive_repo)["failures"])
    (archive_repo / "decisions.csv").write_text("path,decision\n", encoding="utf-8")
    assert any("MANIFEST_HASH_MISMATCH" in item for item in _verify(archive_repo)["failures"])


@pytest.mark.parametrize("source", [".git/config", "references/private", ".dev-data/journal"])
def test_protected_source_is_refused(archive_repo: Path, source: str) -> None:
    record = _last(archive_repo)
    record["path"] = source
    record["destination"] = PREFIX + source
    record["inverse"] = f"git mv {record['destination']} {source}"
    _write_json(archive_repo / "extras.json", [record])
    _assert_last_failure(_verify(archive_repo), "UNSAFE_SOURCE")


def test_cli_emits_json_and_nonzero_for_final_record_failure(archive_repo: Path) -> None:
    assert TOOL.is_file(), "read-only complete-record archive checker is missing"
    command = [
        sys.executable, str(TOOL), "--root", str(archive_repo),
        "--execution", "execution.json", "--extras", "extras.json",
    ]
    success = subprocess.run(command, capture_output=True, text=True, check=False)
    assert success.returncode == 0, success.stderr
    assert json.loads(success.stdout)["recordsChecked"] == 3
    (archive_repo / _last(archive_repo)["destination"]).write_bytes(b"last record corruption")
    failed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert failed.returncode == 1
    _assert_last_failure(json.loads(failed.stdout), "DESTINATION_HASH_MISMATCH")
