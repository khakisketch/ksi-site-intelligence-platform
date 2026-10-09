"""Read-only, complete-record verification of the P3 acquisition archive.

Checks both execution schemas, committed record-set completeness, the pinned
decision manifest, baseline/HEAD Git bindings, destination bytes and exact inverse
pairs. Never imports archived code, executes an inverse, writes a file or performs
network/recovery operations. Missing Git history or unreadable input is a failure,
not an empty success. Findings contain paths/hashes/reason codes, never blob bytes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shlex
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "archive/acquisition-2026/"
_PROTECTED = {
    ".git", ".ai", ".dev-data", ".worktrees", ".venv", ".claude", ".codex",
    ".opencode", ".superpowers", ".agents", "references", "download", "hil_raw_logs", "models",
}
_HEX40 = re.compile(r"[0-9a-f]{40}").fullmatch
_HEX64 = re.compile(r"[0-9a-f]{64}").fullmatch
_FIELDS = {"path", "destination", "git_object", "blob_sha256", "inverse"}


def _safe_relative(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    parts = value.split("/")
    return (
        not any(part in ("", ".", "..") for part in parts)
        and not any(ord(char) < 32 for char in value)
        and parts[0] not in _PROTECTED
    )


def _relative(root: Path, path: Path) -> str:
    relative = str(path.relative_to(root)) if path.is_absolute() else path.as_posix()
    if not _safe_relative(relative):
        raise ValueError("unsafe input path")
    return relative


def _read_file(root: Path, relative: str) -> bytes:
    """Open every component without following links; refuse special files too."""
    if not _safe_relative(relative):
        raise ValueError("unsafe input path")
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(root, directory_flags)
    try:
        parts = relative.split("/")
        for part in parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=directory)
            os.close(directory)
            directory = child
        leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(leaf, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("not a regular file")
            return stream.read()
    finally:
        os.close(directory)


def _git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, check=False, timeout=60
    )
    if completed.returncode:
        raise ValueError("Git binding unavailable")
    return completed.stdout


def _tree(root: Path, revision: str) -> dict[str, tuple[str, str, str]]:
    entries = _git(root, "ls-tree", "-r", "-z", "--full-tree", revision).split(b"\0")
    result = {}
    for entry in entries:
        if entry:
            metadata, path = entry.decode("utf-8", errors="strict").split("\t", 1)
            mode, kind, obj = metadata.split(" ")
            result[path] = (mode, kind, obj)
    return result


def _rows(payload: object, lane: str) -> list[object]:
    if lane == "execution":
        if not isinstance(payload, dict) or not isinstance(payload.get("moves"), list):
            raise ValueError("execution must contain a moves array")
        return list(payload["moves"])
    if not isinstance(payload, list):
        raise ValueError("extras must be an array")
    return list(payload)


def _verify_record(
    root: Path,
    row: object,
    lane: str,
    index: int,
    head: dict[str, tuple[str, str, str]],
    baseline: dict[str, tuple[str, str, str]],
    seen_sources: set[str],
    seen_destinations: set[str],
    blob_hashes: dict[str, str],
) -> tuple[dict[str, object], list[str]]:
    findings: list[str] = []
    result: dict[str, object] = {
        "recordSet": lane, "recordIndex": index,
        "baselineSha256": None, "destinationSha256": None, "failures": findings,
    }
    if not isinstance(row, dict) or set(row) != _FIELDS:
        findings.append("MALFORMED_RECORD")
        return result, findings
    if not all(isinstance(value, str) for value in row.values()):
        findings.append("MALFORMED_RECORD")
        return result, findings
    source, destination, obj, digest = (
        row["path"], row["destination"], row["git_object"], row["blob_sha256"]
    )
    result.update(path=source, destination=destination, gitObject=obj, expectedSha256=digest)
    safe_source = _safe_relative(source) and not source.startswith("archive/")
    safe_destination = _safe_relative(destination) and destination == PREFIX + source
    if not safe_source:
        findings.append("UNSAFE_SOURCE")
    if not safe_destination:
        findings.append("UNSAFE_DESTINATION")
    if source in seen_sources:
        findings.append("DUPLICATE_SOURCE")
    if destination in seen_destinations:
        findings.append("DUPLICATE_DESTINATION")
    seen_sources.add(source)
    seen_destinations.add(destination)
    try:
        inverse = shlex.split(row["inverse"])
    except ValueError:
        inverse = []
    if inverse != ["git", "mv", destination, source]:
        findings.append("INVERSE_MISMATCH")
    if not _HEX40(obj) or not _HEX64(digest):
        findings.append("MALFORMED_HASH")
    # Never use untrusted/private paths or an unbound object to read blob bytes.
    if not safe_source or not safe_destination or "MALFORMED_HASH" in findings:
        return result, findings
    if source in head or os.path.lexists(root / source):
        findings.append("SOURCE_REINTRODUCED")
    destination_entry = head.get(destination)
    regular = destination_entry is not None and destination_entry[:2] in (
        ("100644", "blob"), ("100755", "blob")
    )
    if not regular or destination_entry is None or destination_entry[2] != obj:
        findings.append("GIT_OBJECT_MISMATCH")
    # 54 extras were moved before head_before; their already-archived baseline
    # binding is explicit, not a forged original-path claim. Main rows require
    # the original source at the recorded pre-execution commit.
    baseline_entry = baseline.get(source)
    if lane == "extras" and baseline_entry is None:
        baseline_entry = baseline.get(destination)
    baseline_bound = baseline_entry is not None and baseline_entry[:2] in (
        ("100644", "blob"), ("100755", "blob")
    ) and baseline_entry[2] == obj
    if not baseline_bound:
        findings.append("BASELINE_OBJECT_MISMATCH")
    if baseline_bound:
        if obj not in blob_hashes:
            blob_hashes[obj] = hashlib.sha256(_git(root, "cat-file", "blob", obj)).hexdigest()
        result["baselineSha256"] = blob_hashes[obj]
        if blob_hashes[obj] != digest:
            findings.append("BLOB_HASH_MISMATCH")
    try:
        measured = hashlib.sha256(_read_file(root, destination)).hexdigest()
        result["destinationSha256"] = measured
        if measured != digest:
            findings.append("DESTINATION_HASH_MISMATCH")
    except (OSError, ValueError):
        findings.append("DESTINATION_UNREADABLE")
    return result, findings


def verify_archive_records(root: Path, execution: Path, extras: Path) -> dict[str, object]:
    """Visit all supplied records, return findings, and never mutate the checkout.

    Record-set completeness is checked against tracked HEAD records, not a count
    asserted by the input itself. The execution's pinned decision CSV additionally
    covers every MOVE row. This does not audit unrecorded/earlier P3 move batches.
    """
    failures: list[str] = []
    records: list[dict[str, object]] = []
    report: dict[str, object] = {
        "recordsChecked": 0, "recordsExpected": 0, "failures": failures,
        "records": records, "inputSha256": {},
    }
    input_hashes: dict[str, str] = {}
    report["inputSha256"] = input_hashes
    root = root.absolute()
    try:
        head = _tree(root, "HEAD")
        report["head"] = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        failures.append("GIT_HEAD_UNAVAILABLE")
        return report
    batches: dict[str, list[object]] = {}
    execution_payload: dict[str, object] = {}
    expected_count = 0
    for lane, path in (("execution", execution), ("extras", extras)):
        try:
            relative = _relative(root, path)
            raw = _read_file(root, relative)
            payload = json.loads(raw)
            batches[lane] = _rows(payload, lane)
            input_hashes[lane] = hashlib.sha256(raw).hexdigest()
            if lane == "execution" and isinstance(payload, dict):
                execution_payload = payload
            entry = head.get(relative)
            if entry is None or entry[:2] != ("100644", "blob"):
                raise ValueError("committed record-set unavailable")
            committed = json.loads(_git(root, "cat-file", "blob", entry[2]))
            expected = _rows(committed, lane)
            expected_count += len(expected)
            if batches[lane] != expected:
                failures.append(f"{lane}: RECORDED_SET_MISMATCH")
            if not batches[lane]:
                failures.append(f"{lane}: EMPTY_RECORD_SET")
        except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
            failures.append(f"{lane}: RECORD_FILE_UNREADABLE_OR_MALFORMED")
    report["recordsExpected"] = expected_count
    baseline: dict[str, tuple[str, str, str]] = {}
    baseline_sha = execution_payload.get("head_before")
    try:
        if not isinstance(baseline_sha, str) or not _HEX40(baseline_sha):
            raise ValueError("missing baseline commit")
        if _git(root, "cat-file", "-t", baseline_sha).strip() != b"commit":
            raise ValueError("baseline is not a commit")
        baseline = _tree(root, baseline_sha)
        report["baselineCommit"] = baseline_sha
    except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
        failures.append("BASELINE_UNAVAILABLE")
    try:
        manifest_name = execution_payload.get("manifest")
        if not _safe_relative(manifest_name) or not isinstance(manifest_name, str):
            raise ValueError("unsafe manifest")
        manifest_bytes = _read_file(root, manifest_name)
        input_hashes["manifest"] = hashlib.sha256(manifest_bytes).hexdigest()
        if input_hashes["manifest"] != execution_payload.get("manifest_sha256"):
            failures.append("MANIFEST_HASH_MISMATCH")
        csv_rows = list(csv.DictReader(io.StringIO(manifest_bytes.decode("utf-8")), strict=True))
        keys = ("path", "destination", "git_object", "blob_sha256")
        move_bindings = [
            tuple(row.get(key) for key in keys) for row in csv_rows if row.get("decision") == "MOVE"
        ]
        execution_bindings = [
            tuple(row.get(key) for key in keys)
            for row in batches.get("execution", []) if isinstance(row, dict)
        ]
        if not move_bindings or sorted(move_bindings) != sorted(execution_bindings):
            failures.append("MANIFEST_RECORD_SET_MISMATCH")
    except (OSError, ValueError, UnicodeError, csv.Error, TypeError):
        failures.append("MANIFEST_UNREADABLE_OR_MALFORMED")
    seen_sources: set[str] = set()
    seen_destinations: set[str] = set()
    blob_hashes: dict[str, str] = {}
    for lane, rows in batches.items():
        for index, row in enumerate(rows):
            try:
                result, findings = _verify_record(
                    root, row, lane, index, head, baseline,
                    seen_sources, seen_destinations, blob_hashes,
                )
            except (OSError, ValueError, UnicodeError, subprocess.TimeoutExpired):
                findings = ["RECORD_BINDING_UNAVAILABLE"]
                result = {"recordSet": lane, "recordIndex": index, "failures": findings}
            records.append(result)
            failures.extend(f"{lane}[{index}]: {finding}" for finding in findings)
    report["recordsChecked"] = len(records)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--execution", type=Path, default=Path(
        "docs/audit/PHYSICAL_SITE_MOVE_EXECUTION_v1.json"
    ))
    parser.add_argument("--extras", type=Path, default=Path(
        "docs/audit/PHYSICAL_SITE_MOVE_EXECUTION_EXTRAS_v1.json"
    ))
    args = parser.parse_args(argv)
    report = verify_archive_records(args.root, args.execution, args.extras)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
