"""Fail-closed validator for the frozen physical-site disposition inventory.

Compares a disposition manifest against frozen Git objects at
``EXPECTED_BASELINE`` — never against edited working-tree files, never by
executing moves. Protected rows (private ``.ai/`` state, ``references/``
foreign pins and gitlinks) are verified by Git metadata only; their content
is never read, hashed, delivered or traversed. Symlink rows bind the link-text
bytes, never the target.

CLI: ``python tools/check_physical_site_disposition.py --manifest <csv>``
exits 0 only when every check passes, 1 with safe path/reason findings
otherwise. Findings never carry file content bytes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_BASELINE = "72c526ba7b6d423443d9733d1189fccd8b47ada6"
EXPECTED_COLUMNS = [
    "path",
    "baselineCommit",
    "gitMode",
    "gitObject",
    "sha256",
    "proposedDisposition",
    "proposedDestination",
    "requiredBeforeAction",
]
ALLOWED_DISPOSITIONS = frozenset(
    {"PROTECT", "RECONCILE", "RETAIN", "RECONCILE_DOCUMENT", "ARCHIVE_CANDIDATE"}
)
ALLOWED_MODES = frozenset({"100644", "100755", "120000", "160000"})
ARCHIVE_PREFIX = "archive/acquisition-2026/"

_HEX40_RE = re.compile(r"[0-9a-f]{40}")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")

_MISSING_EXAMPLE_LIMIT = 10


class _PlumbingError(RuntimeError):
    """Controlled Git/manifest-plumbing failure. Carries path/reason text only —
    never file content bytes — so it converts to a safe finding, not a crash."""


def _trusted_protected(path: str, mode: str) -> bool:
    """Protection derived from trusted baseline path/type boundaries only.

    Never from the manifest's own ``proposedDisposition`` label: a hostile row
    must not promote an ordinary source into PROTECT to bypass content hashing,
    nor demote a protected source to smuggle out a content hash.
    """
    if mode == "160000":
        return True
    return path in (".ai", "references") or path.startswith((".ai/", "references/"))


def _canonical_repo_path(value: str) -> str | None:
    """Return the failure reason, or None when the path is canonical and safe.

    Checked before any Git/filesystem content lookup so hostile metadata can
    neither traverse private content nor escape the repository.
    """
    if not value or "\0" in value:
        return "empty or NUL-containing path"
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return f"absolute path is refused: {value}"
    if "\\" in value:
        return f"backslash path is refused: {value}"
    posix = PurePosixPath(value)
    if posix.is_absolute() or ".." in posix.parts or "." in posix.parts:
        return f"non-canonical (dot or parent) path is refused: {value}"
    if value != posix.as_posix() or "//" in value or value.endswith("/"):
        return f"non-canonical path spelling is refused: {value}"
    if value.startswith(".git/") or value == ".git":
        return f"git-internals path is refused: {value}"
    return None


def _run_git(root: Path, args: list[str], stdin: bytes | None = None) -> bytes:
    """Run one read-only git plumbing command; map transport faults to
    controlled findings instead of escaping exceptions."""
    try:
        completed = subprocess.run(
            ["git", *args],
            input=stdin,
            cwd=root,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise _PlumbingError(f"git is unavailable or failed to start: {exc}") from exc
    return completed.stdout


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise _PlumbingError(f"git is unavailable or failed to start: {exc}") from exc


def _trusted_baseline_map(
    root: Path, failures: list[str], baseline: str
) -> dict[str, tuple[str, str]] | None:
    """Frozen {path: (mode, object)} map from ``git ls-tree`` at ``baseline``.

    Returns None when the baseline history is unavailable; the caller must fail
    clearly in that case — no automatic fetch, no silent skip. The ``baseline``
    ref itself is validated before any Git invocation.
    """
    if not _HEX40_RE.fullmatch(baseline):
        failures.append(f"malformed baseline ref {baseline!r}; Git was not invoked")
        return None
    probe = _git(root, "cat-file", "-e", baseline)
    if probe.returncode != 0:
        failures.append(
            f"baseline commit {baseline} is not present in local Git history "
            f"(root: {root}); clone with full history and rerun — no automatic fetch is performed"
        )
        return None
    result = _git(root, "ls-tree", "-r", "-z", baseline)
    if result.returncode != 0:
        failures.append(f"git ls-tree of baseline {baseline} failed; cannot verify inventory")
        return None
    try:
        text = result.stdout.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise _PlumbingError(f"git ls-tree output is not decodable: {exc}") from exc
    trusted: dict[str, tuple[str, str]] = {}
    try:
        for entry in text.split("\0"):
            if not entry:
                continue
            meta, path = entry.split("\t")
            mode, _kind, obj = meta.split(" ")
            trusted[path] = (mode, obj)
    except ValueError as exc:
        raise _PlumbingError(f"git ls-tree output is truncated or malformed: {exc}") from exc
    return trusted


def _batch_object_types(root: Path, objects: set[str]) -> dict[str, str]:
    """{object: git type} via one ``cat-file --batch-check`` process (metadata only)."""
    if not objects:
        return {}
    blob_input = "".join(f"{obj}\n" for obj in sorted(objects))
    stdout = _run_git(root, ["cat-file", "--batch-check"], stdin=blob_input.encode("ascii"))
    types: dict[str, str] = {}
    try:
        text = stdout.decode("ascii", errors="strict")
    except UnicodeError as exc:
        raise _PlumbingError(f"git batch-check output is not decodable: {exc}") from exc
    for line in text.splitlines():
        parts = line.split(" ")
        if len(parts) >= 2 and parts[1] != "missing":
            types[parts[0]] = parts[1]
    return types


def _batch_blob_bytes(root: Path, objects: set[str]) -> dict[str, bytes]:
    """{object: raw blob bytes} via one ``cat-file --batch`` process.

    Used only for non-protected regular files and symlink link text. Protected
    objects are never passed here, so their content is never read.
    """
    if not objects:
        return {}
    ordered = sorted(objects)
    blob_input = "".join(f"{obj}\n" for obj in ordered)
    raw = _run_git(root, ["cat-file", "--batch"], stdin=blob_input.encode("ascii"))
    blobs: dict[str, bytes] = {}
    pos = 0
    try:
        for _ in ordered:
            header_end = raw.index(b"\n", pos)
            header = raw[pos:header_end].decode("ascii", errors="strict")
            parts = header.split(" ")
            if parts[-1] == "missing":
                continue
            if len(parts) < 3 or parts[1] != "blob":
                raise _PlumbingError(
                    "git batch output is truncated or malformed; cannot verify content bindings"
                )
            size = int(parts[2])
            start = header_end + 1
            blobs[parts[0]] = raw[start : start + size]
            pos = start + size + 1
    except (ValueError, UnicodeError) as exc:
        raise _PlumbingError(
            "git batch output is truncated or undecodable; cannot verify content bindings"
        ) from exc
    return blobs


def validate_disposition_manifest(
    root: Path, manifest: Path, *, baseline: str = EXPECTED_BASELINE
) -> list[str]:
    """Return all inventory findings; an empty list is success.

    ``baseline`` pins the frozen commit every row must reference (default: the
    approved inventory baseline). Unit fixtures pass their synthetic commit;
    production use keeps the default. Read-only: only ``git cat-file`` /
    ``git ls-tree`` against frozen objects. Never reads working-tree files,
    never dereferences submodules, symlinks or credentials, never executes moves.
    """
    failures: list[str] = []

    try:
        raw_manifest = manifest.read_bytes()
    except OSError as exc:
        return [f"manifest unreadable: {manifest}: {exc}"]
    try:
        text = raw_manifest.decode("utf-8", errors="strict")
    except UnicodeError:
        return [
            f"manifest is not UTF-8 decodable: {manifest}; "
            "binary or malformed bytes refused without inspection"
        ]

    try:
        reader = csv.reader(text.splitlines(), strict=True)
        header = next(reader)
    except StopIteration:
        return ["manifest is empty; expected header: " + ",".join(EXPECTED_COLUMNS)]
    except csv.Error as exc:
        return [f"manifest CSV parse error in header: {exc}; strict parsing, no repair"]
    if header != EXPECTED_COLUMNS:
        return [
            "manifest header must be exactly "
            + ",".join(EXPECTED_COLUMNS)
            + f"; got: {','.join(header)}"
        ]

    rows: list[dict[str, str]] = []
    seen_paths: dict[str, int] = {}
    try:
        for lineno, fields in enumerate(reader, start=2):
            if fields == []:
                continue
            if len(fields) != len(EXPECTED_COLUMNS):
                failures.append(f"row {lineno}: malformed field count {len(fields)}; row refused")
                continue
            row = dict(zip(EXPECTED_COLUMNS, (field.strip() for field in fields), strict=True))
            rows.append(row)
            if row["path"] in seen_paths:
                failures.append(f"duplicate manifest row for path: {row['path']}; rows refused")
            else:
                seen_paths[row["path"]] = lineno
    except csv.Error as exc:
        return failures + [f"manifest CSV parse error mid-file: {exc}; strict parsing, no repair"]

    # Baseline refs are validated before any Git invocation so malformed refs
    # can never reach the plumbing layer; rejected rows are skipped below.
    ref_rejected: set[int] = set()
    for index, row in enumerate(rows):
        if row["baselineCommit"] != baseline or not _HEX40_RE.fullmatch(row["baselineCommit"]):
            failures.append(
                f"row {seen_paths[row['path']]} ({row['path']}): wrong baseline ref "
                f"{row['baselineCommit']!r}; row refused"
            )
            ref_rejected.add(index)

    try:
        trusted = _trusted_baseline_map(root, failures, baseline)
    except _PlumbingError as exc:
        return failures + [f"{exc}; no moves authorized"]
    if trusted is None:
        return failures

    # Content bindings are resolved only after path/mode/label pre-checks pass
    # for a row, so hostile metadata cannot trigger a content lookup.
    pending_hashes: dict[str, str] = {}
    for index, row in enumerate(rows):
        if index in ref_rejected:
            continue
        lineno = seen_paths[row["path"]]
        path, commit = row["path"], row["baselineCommit"]
        mode, obj = row["gitMode"], row["gitObject"]
        digest, disposition = row["sha256"], row["proposedDisposition"]
        destination, condition = row["proposedDestination"], row["requiredBeforeAction"]

        reason = _canonical_repo_path(path)
        if reason is not None:
            failures.append(f"row {lineno}: {reason}; row refused")
            continue
        dest_reason = _canonical_repo_path(destination)
        if dest_reason is not None:
            failures.append(f"row {lineno} ({path}): destination {dest_reason}; row refused")
            continue
        if commit != baseline or not _HEX40_RE.fullmatch(commit):
            failures.append(f"row {lineno} ({path}): wrong baseline ref {commit!r}; row refused")
            continue
        if mode not in ALLOWED_MODES or not _HEX40_RE.fullmatch(obj):
            failures.append(
                f"row {lineno} ({path}): malformed mode/object {mode}/{obj}; row refused"
            )
            continue
        if disposition not in ALLOWED_DISPOSITIONS:
            failures.append(
                f"row {lineno} ({path}): unknown disposition {disposition!r}; row refused"
            )
            continue
        if not condition:
            failures.append(
                f"row {lineno} ({path}): empty requiredBeforeAction; "
                "a blocking condition is required"
            )
            continue

        entry = trusted.get(path)
        if entry is None:
            failures.append(f"row {lineno} ({path}): unknown path, not in baseline {baseline}")
            continue
        trusted_mode, trusted_obj = entry
        if mode != trusted_mode or obj != trusted_obj:
            failures.append(
                f"row {lineno} ({path}): stale mode/object {mode}/{obj}; "
                f"baseline has {trusted_mode}/{trusted_obj}"
            )
            continue

        must_protect = _trusted_protected(path, trusted_mode)
        claims_protect = disposition == "PROTECT"
        if claims_protect and not must_protect:
            failures.append(
                f"row {lineno} ({path}): untrusted PROTECT label on ordinary source; "
                "protection derives from baseline path/type boundaries, not labels"
            )
            continue
        if must_protect and not claims_protect:
            failures.append(
                f"row {lineno} ({path}): protected baseline source labeled {disposition}; "
                "protected sources stay PROTECT with metadata-only verification"
            )
            continue

        if disposition == "ARCHIVE_CANDIDATE":
            if destination != f"{ARCHIVE_PREFIX}{path}":
                failures.append(
                    f"row {lineno} ({path}): candidate destination must be "
                    f"{ARCHIVE_PREFIX}{path}; got {destination}"
                )
                continue
        elif destination != path:
            failures.append(
                f"row {lineno} ({path}): non-candidate destination must equal path; "
                f"got {destination}"
            )
            continue

        if must_protect:
            if digest:
                failures.append(
                    f"row {lineno} ({path}): protected row must not deliver a content hash"
                )
        else:
            if not _HEX64_RE.fullmatch(digest):
                failures.append(f"row {lineno} ({path}): malformed sha256 digest; row refused")
                continue
            pending_hashes[path] = obj

    checked = set(seen_paths)
    missing = sorted(set(trusted) - checked)
    if missing:
        examples = ", ".join(missing[:_MISSING_EXAMPLE_LIMIT])
        failures.append(
            f"manifest omits {len(missing)} baseline entries "
            f"(e.g. {examples}); inventory is incomplete"
        )

    if failures:
        return failures

    # All structural/binding pre-checks passed: verify Git object types
    # (metadata only) and content digests of non-protected rows.
    try:
        needed_types = {obj for _mode, obj in trusted.values()}
        object_types = _batch_object_types(root, needed_types)
    except _PlumbingError as exc:
        return failures + [f"{exc}; no moves authorized"]
    for row in rows:
        path = row["path"]
        trusted_mode, trusted_obj = trusted[path]
        expected_type = "commit" if trusted_mode == "160000" else "blob"
        actual_type = object_types.get(trusted_obj)
        if actual_type != expected_type:
            if expected_type == "commit" and actual_type is None:
                # Foreign submodule commit: verify Git metadata only, never
                # fetch or traverse the referenced repository.
                continue
            failures.append(
                f"({path}): baseline object {trusted_obj} has Git type "
                f"{actual_type!r}; expected {expected_type!r} — local baseline "
                "history is incomplete; clone with full history (no automatic fetch)"
            )
    if failures:
        return failures

    try:
        blobs = _batch_blob_bytes(root, set(pending_hashes.values()))
    except _PlumbingError as exc:
        return failures + [f"{exc}; no moves authorized"]
    for row in rows:
        path = row["path"]
        if path not in pending_hashes:
            continue
        content = blobs.get(pending_hashes[path])
        if content is None:
            failures.append(f"({path}): baseline blob {pending_hashes[path]} is unreadable")
            continue
        actual = hashlib.sha256(content).hexdigest()
        if actual != row["sha256"]:
            failures.append(
                f"({path}): stale sha256 digest; manifest {row['sha256']} != object {actual}"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path, help="Disposition CSV to validate")
    parser.add_argument(
        "--root",
        default=ROOT,
        type=Path,
        help="Repository root holding the baseline Git history",
    )
    args = parser.parse_args()
    failures = validate_disposition_manifest(args.root, args.manifest)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"FAIL: {len(failures)} disposition finding(s); no moves authorized")
        return 1
    print(f"PASS: disposition inventory binds {EXPECTED_BASELINE}; no moves executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
