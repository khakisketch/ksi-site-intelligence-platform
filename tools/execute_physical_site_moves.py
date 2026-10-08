"""Fail-closed batch executor for acquisition source moves (P3 Task 6).

Reads a move-decision manifest (``docs/audit/PHYSICAL_SITE_MOVE_DECISIONS_v1.csv``
as produced by ``tools/prepare_physical_site_moves.py``) and relocates every
``MOVE`` row to its exact ``archive/acquisition-2026/<path>`` destination with
``git mv`` mechanics. Dry-run is the default; ``--apply`` performs the moves.

Executor semantics (refined Task 6 rule — reconciles the Task 1 shorthand
"refuses any row with a non-empty blockers tuple", which predates the T6
closure step): ``is_executable(row)`` holds when every blocker is a known
vocabulary id AND every T3/T5 id verifies as closed at the current HEAD
against its recorded evidence AND every T6 id is closed by this task's
same-batch consumer/CI/deploy/docs edits (machine-checked below) AND every
consumer resolves active-or-archive. The executor refuses the WHOLE batch —
no partial moves, tree unchanged — on any hash mismatch, unknown blocker id,
unverified foreign (T3/T5) closure, unresolvable consumer, live reference to
a moving path outside the batch/archive/docs, destination collision, unknown
decision, or malformed/hostile manifest row.

Closure evidence verified at HEAD for the known-closed foreign ids:

* ``T5:core-dep-drop`` — ``services/core/pyproject.toml`` names none of the
  three closed package dependencies.
* ``T5:core-import-closure:<file>`` — ``<file>`` is absent from the active
  tree (archived/moved by Task 5) or its active blob contains none of the
  acquisition import tokens.
* ``T3:worker-managed-split`` — the managed-only importer modules
  (``runner.py``, ``odm_masking.py``) are absent from the active tree.

T6 ids (closed by this task's batch, machine-checked here):

* ``T6:consumer-review:<path>`` — must name the row's own path; no live
  (non-batch, non-archive, non-docs) HEAD file references the row path or
  its group directory.
* ``T6:ci-docker-refs`` / ``T6:docs-routing`` — covered by the same
  live-reference check over the row path plus its group directory prefix
  (docs/``*.md`` hits are tolerated as intentional historical mentions; the
  manifest machinery files and the P4-owned ``apps/dashboard/`` transitional
  paths are explicitly exempt — never silent; the routing-note edits
  themselves are human-reviewed in the same commit batch).

Atomicity: ALL rows are validated before ANY move. ``--apply`` then performs
every ``git mv`` and writes a durable inverse record
(``docs/audit/PHYSICAL_SITE_MOVE_EXECUTION_v1.json`` by default) listing per
row the path, destination, pre-move blob hashes and the exact inverse
command. Post-move, each destination blob object is re-verified identical to
the pre-move binding (blob-identical moves only).

CLI: ``python tools/execute_physical_site_moves.py --manifest <decision-csv>
[--apply] [--root <repo>] [--inverse <json>]``. Exit 0 on PASS/completion, 1
with ``FAIL:`` findings otherwise (never a traceback on a controlled refusal).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DECISION_COLUMNS = (
    "path",
    "git_object",
    "blob_sha256",
    "baseline_git_object",
    "baseline_sha256",
    "group",
    "decision",
    "destination",
    "blockers",
    "consumers",
)

ARCHIVE_PREFIX = "archive/acquisition-2026/"

BLOCKER_PATTERN = re.compile(
    r"(?:"
    r"T3:worker-managed-split"
    r"|T5:core-import-closure:services/core/src/ksi_core/[A-Za-z0-9_/.-]+\.py"
    r"|T5:core-dep-drop"
    r"|T6:consumer-review:[A-Za-z0-9_./-]+"
    r"|T6:ci-docker-refs"
    r"|T6:docs-routing"
    r")"
)

_DECISIONS = ("MOVE", "DEFER", "RETAIN")
_HEX40 = re.compile(r"[0-9a-f]{40}").fullmatch
_HEX64 = re.compile(r"[0-9a-f]{64}").fullmatch
_BLOB_MODES = frozenset({"100644", "100755", "120000"})

# Group directory prefixes whose live references gate T6 closure. The
# edge/root group has no shared prefix (its rows carry exact-path consumers
# only), so it is intentionally absent here.
_DIR_PREFIX_GROUPS = (
    "edge/manifold-runtime",
    "edge/psdk-app",
    "edge/psdk-tap",
    "edge/msdk-field-bridge",
    "services/dji-gateway",
    "packages/mission-contracts",
    "packages/mission-planning",
    "packages/perception",
    "packages/equipment-intelligence",
)

# Path prefixes exempt from the live-reference scan (explicit, never silent):
# manifest machinery carries moving paths as decision/fixture data without
# importing or building them (covered by its own contract tests); the Console
# is P4-owned and must not be edited here (plan Global Constraints), so its
# acquisition-screen references ride as recorded transitional state until P4.
_MACHINERY_PATHS = (
    "tools/prepare_physical_site_moves.py",
    "tools/execute_physical_site_moves.py",
    "tests/contract/test_physical_site_move_tooling.py",
)
_TRANSITIONAL_PREFIXES = ("apps/dashboard/",)


def _is_exempt_hit(path: str) -> bool:
    if _is_docs_mention(path):
        return True
    if path in _MACHINERY_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _TRANSITIONAL_PREFIXES)


# Acquisition import tokens proving a T5 import-closure is NOT yet closed.
_ACQUISITION_IMPORT_TOKENS = (
    "ksi_mission_contracts",
    "ksi_mission_planning",
    "ksi_equipment_intelligence",
    "ksi_perception",
    "ksi_dji_gateway",
)

# Exact evidence for the T3 managed split: these importers must be gone.
_T3_MANAGED_IMPORTERS = (
    "services/processing-controller/src/ksi_processing_controller/runner.py",
    "services/processing-controller/src/ksi_processing_controller/odm_masking.py",
)

_CORE_PYPROJECT = "services/core/pyproject.toml"
_CLOSED_CORE_DEPS = (
    "ksi-mission-contracts",
    "ksi-mission-planning",
    "ksi-equipment-intelligence",
)


@dataclass(frozen=True)
class PlanRow:
    """One validated manifest row ready for move planning."""

    path: str
    git_object: str
    blob_sha256: str
    group: str
    destination: str
    blockers: tuple[str, ...]
    consumers: tuple[str, ...]


class MoveExecutionError(RuntimeError):
    """Controlled fail-closed finding set (path/reason text only)."""

    def __init__(self, findings: list[str]) -> None:
        super().__init__("; ".join(findings[:5]))
        self.findings = findings


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", *args], cwd=repo, check=False, capture_output=True
        )
    except OSError as exc:
        raise MoveExecutionError([f"git is unavailable or failed to start: {exc}"]) from exc


def _head_map(repo: Path) -> dict[str, tuple[str, str, str]]:
    """{path: (mode, kind, object)} from the current checkout HEAD."""
    proc = _run_git(repo, "ls-tree", "-r", "-z", "HEAD")
    if proc.returncode != 0:
        raise MoveExecutionError(["git ls-tree of HEAD failed; cannot verify bindings"])
    try:
        text = proc.stdout.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise MoveExecutionError(["git ls-tree output is not decodable"]) from exc
    rows: dict[str, tuple[str, str, str]] = {}
    for entry in text.split("\0"):
        if not entry:
            continue
        try:
            meta, path = entry.split("\t")
            mode, kind, obj = meta.split(" ")
        except ValueError as exc:
            raise MoveExecutionError(["git ls-tree output is malformed"]) from exc
        rows[path] = (mode, kind, obj)
    return rows


def _batch_blobs(repo: Path, objects: set[str]) -> dict[str, bytes]:
    """Read every requested blob in one ``git cat-file --batch`` call."""
    if not objects:
        return {}
    proc = subprocess.run(
        ["git", "cat-file", "--batch"],
        input="".join(f"{obj}\n" for obj in sorted(objects)).encode("ascii"),
        cwd=repo,
        check=False,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise MoveExecutionError(["git cat-file --batch failed; cannot verify bindings"])
    out: dict[str, bytes] = {}
    stream = proc.stdout
    pos = 0
    wanted = set(objects)
    while wanted:
        header_end = stream.find(b"\n", pos)
        if header_end < 0:
            raise MoveExecutionError(["git cat-file --batch output is truncated"])
        header = stream[pos:header_end].decode("ascii", errors="strict")
        parts = header.split(" ")
        if len(parts) != 3 or parts[1] != "blob":
            raise MoveExecutionError([f"git object is not a readable blob: {parts[0]}"])
        obj, _kind, size = parts
        start = header_end + 1
        end = start + int(size)
        out[obj] = stream[start:end]
        pos = end + 1  # trailing newline after content
        wanted.discard(obj)
    return out


def _canonical_relpath(value: str) -> str | None:
    """Return a refusal reason, or None when ``value`` is a safe repo path."""
    if not value or value.startswith("/") or "\x00" in value:
        return "not a relative repo path"
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "not a canonical repo path"
    if value.startswith(".git/") or value == ".git":
        return "must not touch git internals"
    return None


def _load_manifest(manifest: Path) -> list[dict[str, str]]:
    try:
        raw = manifest.read_bytes()
    except OSError as exc:
        raise MoveExecutionError([f"manifest unreadable: {manifest}: {exc}"]) from exc
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise MoveExecutionError(
            [f"manifest is not UTF-8 decodable: {manifest}; refused"]
        ) from None
    try:
        reader = csv.reader(text.splitlines(), strict=True)
        header = next(reader)
    except StopIteration:
        raise MoveExecutionError(["manifest is empty"]) from None
    except csv.Error as exc:
        raise MoveExecutionError([f"manifest CSV parse error: {exc}"]) from exc
    if list(header) != list(DECISION_COLUMNS):
        raise MoveExecutionError(
            ["manifest header must be exactly " + ",".join(DECISION_COLUMNS)]
        ) from None
    rows: list[dict[str, str]] = []
    try:
        for fields in reader:
            if fields == []:
                continue
            if len(fields) != len(DECISION_COLUMNS):
                raise MoveExecutionError(["manifest has a malformed row; row refused"])
            rows.append(
                dict(zip(DECISION_COLUMNS, (f.strip() for f in fields), strict=True))
            )
    except csv.Error as exc:
        raise MoveExecutionError([f"manifest CSV parse error mid-file: {exc}"]) from exc
    if not rows:
        raise MoveExecutionError(["manifest names no rows"])
    paths = [row["path"] for row in rows]
    if len(set(paths)) != len(paths):
        raise MoveExecutionError(["duplicate manifest rows produced; refused"])
    return rows


def _verify_foreign_closure(
    blocker: str, head: dict[str, tuple[str, str, str]], blobs: dict[str, bytes]
) -> str | None:
    """Return a refusal reason when a T3/T5 blocker is NOT verifiably closed."""
    if blocker == "T5:core-dep-drop":
        entry = head.get(_CORE_PYPROJECT)
        if entry is None:
            return f"{blocker}: cannot verify closure ({_CORE_PYPROJECT} missing at HEAD)"
        _mode, kind, obj = entry
        if kind != "blob" or obj not in blobs:
            return f"{blocker}: cannot verify closure (unreadable {_CORE_PYPROJECT})"
        text = blobs[obj].decode("utf-8", errors="replace")
        leaked = [dep for dep in _CLOSED_CORE_DEPS if dep in text]
        if leaked:
            return f"{blocker}: not closed (still declares {', '.join(leaked)})"
        return None
    if blocker.startswith("T5:core-import-closure:"):
        consumer = blocker[len("T5:core-import-closure:"):]
        entry = head.get(consumer)
        if entry is None:
            return None  # archived/moved by Task 5: closure holds
        _mode, kind, obj = entry
        if kind != "blob" or obj not in blobs:
            return f"{blocker}: cannot verify closure (unreadable {consumer})"
        text = blobs[obj].decode("utf-8", errors="replace")
        leaked = [tok for tok in _ACQUISITION_IMPORT_TOKENS if tok in text]
        if leaked:
            return f"{blocker}: not closed ({consumer} still imports {', '.join(leaked)})"
        return None
    if blocker == "T3:worker-managed-split":
        present = [path for path in _T3_MANAGED_IMPORTERS if path in head]
        if present:
            return f"{blocker}: not closed (still active: {', '.join(present)})"
        return None
    return f"{blocker}: unknown foreign blocker; refused"


def _live_reference_tokens(row: PlanRow) -> tuple[str, ...]:
    tokens = [row.path]
    if row.group in _DIR_PREFIX_GROUPS:
        tokens.append(row.group + "/")
    return tuple(tokens)


def _grep_files(repo: Path, tokens: list[str], scope: list[str]) -> list[str]:
    """Fixed-string ``git grep -l`` over HEAD; returns plain repo paths (the
    ``HEAD:`` rev prefix git prepends is stripped). A token occurrence
    immediately prefixed by ``archive/acquisition-2026/`` names the move
    DESTINATION, not a live reference, and is excluded via a PCRE lookbehind.
    Raises on git failure; empty list means no match (git exit 1)."""
    patterns = [f"(?<!{re.escape(ARCHIVE_PREFIX)}){re.escape(token)}" for token in tokens]
    proc = _run_git(
        repo, "grep", "-l", "-I", "-P",
        *sum((["-e", pattern] for pattern in patterns), []),
        "HEAD", "--", *scope,
    )
    if proc.returncode == 1:
        return []
    if proc.returncode != 0:
        raise MoveExecutionError(["git grep for live references failed"])
    return [
        line.removeprefix("HEAD:")
        for line in proc.stdout.decode("utf-8", errors="replace").splitlines()
        if line
    ]


def _is_docs_mention(path: str) -> bool:
    return path.startswith("docs/") or path.endswith(".md")


def _find_live_references(
    repo: Path, rows: list[PlanRow], batch_paths: set[str]
) -> list[str]:
    """Name rows still referenced by live HEAD files. Exempt hits are the
    manifest machinery itself (decision/fixture data, never a build input),
    the P4-owned Console transitional paths, and docs historical mentions —
    all explicit, never silent."""
    tokens: list[str] = []
    for row in rows:
        tokens.extend(_live_reference_tokens(row))
    unique = sorted(set(tokens))
    union_hits = _grep_files(repo, unique, [".", ":!archive"])
    union_files = [
        line for line in union_hits
        if line not in batch_paths and not _is_exempt_hit(line)
    ]
    if not union_files:
        return []
    findings: list[str] = []
    for row in rows:
        for token in _live_reference_tokens(row):
            for line in _grep_files(repo, [token], union_files):
                if line not in batch_paths and not _is_exempt_hit(line):
                    findings.append(
                        f"({row.path}): live reference to {token!r} in {line}; "
                        "T6 consumer closure incomplete"
                    )
                    break
        if len(findings) >= 10:
            findings.append(f"... and more; {len(rows)} rows under review")
            break
    return findings


def plan_moves(manifest: Path, repo: Path) -> tuple[PlanRow, ...]:
    """Validate the WHOLE batch. Raises :class:`MoveExecutionError` (tree
    untouched) on any hash mismatch, unknown state, missing consumer,
    unverified foreign closure, or live reference."""
    rows = _load_manifest(manifest)
    findings: list[str] = []
    for row in rows:
        for key in ("path", "destination"):
            reason = _canonical_relpath(row[key])
            if reason is not None:
                findings.append(f"({row[key]}): {reason}; row refused")
        if row["decision"] not in _DECISIONS:
            findings.append(f"({row['path']}): unknown decision {row['decision']!r}")
        if row["decision"] == "MOVE" and row["destination"] != f"{ARCHIVE_PREFIX}{row['path']}":
            findings.append(
                f"({row['path']}): MOVE destination must be "
                f"{ARCHIVE_PREFIX}{row['path']}; got {row['destination']!r}"
            )
        for blocker in ([b for b in row["blockers"].split(";") if b] if row["blockers"] else []):
            if not BLOCKER_PATTERN.fullmatch(blocker):
                findings.append(f"({row['path']}): unknown blocker id {blocker!r}")
    if findings:
        raise MoveExecutionError(findings)

    moves = [row for row in rows if row["decision"] == "MOVE"]
    if not moves:
        raise MoveExecutionError(["manifest names no MOVE rows; nothing to execute"])

    head = _head_map(repo)
    needed_objects = {head[p][2] for p in {*_T3_MANAGED_IMPORTERS, _CORE_PYPROJECT} if p in head}
    for row in moves:
        entry = head.get(row["path"])
        if entry is not None:
            needed_objects.add(entry[2])
    blobs = _batch_blobs(repo, needed_objects)
    # Blobs needed for T5 import-closure evidence: active consumer files.
    closure_files = set()
    for row in moves:
        for blocker in ([b for b in row["blockers"].split(";") if b] if row["blockers"] else []):
            if blocker.startswith("T5:core-import-closure:"):
                target = blocker[len("T5:core-import-closure:"):]
                if target in head:
                    closure_files.add(head[target][2])
    if closure_files - set(blobs):
        blobs.update(_batch_blobs(repo, closure_files - set(blobs)))

    planned: list[PlanRow] = []
    for row in moves:
        path = row["path"]
        entry = head.get(path)
        if entry is None:
            findings.append(f"({path}): missing at HEAD; no silent skip")
            continue
        mode, kind, obj = entry
        if kind != "blob" or mode not in _BLOB_MODES or not _HEX40(obj):
            findings.append(f"({path}): not a movable blob at HEAD ({mode} {kind}); refused")
            continue
        if obj != row["git_object"]:
            findings.append(
                f"({path}): git object mismatch (manifest {row['git_object']}, HEAD {obj}); refused"
            )
            continue
        content = blobs.get(obj)
        if content is None:
            findings.append(f"({path}): HEAD blob {obj} is unreadable")
            continue
        if hashlib.sha256(content).hexdigest() != row["blob_sha256"]:
            findings.append(f"({path}): blob SHA256 mismatch; refused")
            continue
        if not _HEX40(row["git_object"]) or not _HEX64(row["blob_sha256"]):
            findings.append(f"({path}): manifest hashes are not hex; refused")
            continue
        if row["destination"] in head:
            findings.append(f"({path}): destination {row['destination']} already exists; refused")
            continue
        blockers = tuple(b for b in row["blockers"].split(";") if b) if row["blockers"] else ()
        for blocker in blockers:
            if blocker.startswith("T3:") or blocker.startswith("T5:"):
                reason = _verify_foreign_closure(blocker, head, blobs)
                if reason is not None:
                    findings.append(f"({path}): {reason}")
            elif blocker.startswith("T6:"):
                if blocker.startswith("T6:consumer-review:"):
                    named = blocker[len("T6:consumer-review:"):]
                    if named != path:
                        findings.append(
                            f"({path}): consumer-review blocker names {named!r}; refused"
                        )
                elif blocker not in ("T6:ci-docker-refs", "T6:docs-routing"):
                    findings.append(f"({path}): unknown T6 blocker {blocker!r}; refused")
            else:  # pragma: no cover — vocabulary check above already refused these
                findings.append(f"({path}): unknown blocker id {blocker!r}")
        consumers = tuple(c for c in row["consumers"].split(";") if c) if row["consumers"] else ()
        for consumer in consumers:
            reason = _canonical_relpath(consumer)
            if reason is not None:
                findings.append(f"({path}): consumer ({consumer}): {reason}")
            elif consumer not in head and f"{ARCHIVE_PREFIX}{consumer}" not in head:
                findings.append(f"({path}): stale consumer reference: {consumer}")
        planned.append(
            PlanRow(
                path=path,
                git_object=obj,
                blob_sha256=hashlib.sha256(content).hexdigest(),
                group=row["group"],
                destination=row["destination"],
                blockers=blockers,
                consumers=consumers,
            )
        )
    if findings:
        raise MoveExecutionError(findings)

    batch_paths = {row.path for row in planned}
    findings.extend(_find_live_references(repo, planned, batch_paths))
    if findings:
        raise MoveExecutionError(findings)
    planned.sort(key=lambda item: item.path)
    return tuple(planned)


def apply_moves(repo: Path, planned: tuple[PlanRow, ...]) -> list[dict[str, str]]:
    """Perform every ``git mv`` (parents created first) and re-verify each
    destination blob object is identical to the pre-move binding."""
    records: list[dict[str, str]] = []
    for item in planned:
        destination = repo / item.destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        proc = _run_git(repo, "mv", item.path, item.destination)
        if proc.returncode != 0:
            raise MoveExecutionError(
                [
                    f"({item.path}): git mv failed: "
                    f"{proc.stderr.decode('utf-8', errors='replace')[:200]}"
                ]
            )
        records.append(
            {
                "path": item.path,
                "destination": item.destination,
                "git_object": item.git_object,
                "blob_sha256": item.blob_sha256,
                "inverse": f"git mv {item.destination} {item.path}",
            }
        )
    # Post-move truth comes from the index (HEAD is still pre-move state).
    staged: dict[str, str] = {}
    proc = _run_git(repo, "ls-files", "-s", "-z")
    if proc.returncode != 0:
        raise MoveExecutionError(["git ls-files failed; cannot verify post-move state"])
    for entry in proc.stdout.decode("utf-8", errors="strict").split("\0"):
        if not entry:
            continue
        meta, path = entry.split("\t")
        _mode, obj, _stage = meta.split(" ")
        staged[path] = obj
    for item in planned:
        if staged.get(item.destination) != item.git_object:
            raise MoveExecutionError(
                [f"({item.path}): post-move blob mismatch at {item.destination}; tree needs review"]
            )
        if item.path in staged:
            raise MoveExecutionError(
                [f"({item.path}): source still staged after move; tree needs review"]
            )
    return records


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path, help="Decision CSV to execute")
    parser.add_argument("--apply", action="store_true", help="Perform the moves (default: dry-run)")
    parser.add_argument("--root", default=ROOT, type=Path, help="Repository checkout to operate on")
    parser.add_argument(
        "--inverse",
        default=ROOT / "docs" / "audit" / "PHYSICAL_SITE_MOVE_EXECUTION_v1.json",
        type=Path,
        help="Inverse-record JSON to write on --apply",
    )
    args = parser.parse_args(argv)

    try:
        planned = plan_moves(args.manifest, args.root)
    except MoveExecutionError as exc:
        for finding in exc.findings:
            print(f"FAIL: {finding}")
        print(f"FAIL: {len(exc.findings)} move-execution finding(s); tree unchanged")
        return 1

    left = sum(1 for _ in _load_manifest(args.manifest) if True) - len(planned)
    if not args.apply:
        print(
            f"PASS: {len(planned)} move(s) validated against HEAD "
            f"({left} non-MOVE row(s) left in place); dry-run, tree unchanged"
        )
        return 0

    try:
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=args.root, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: cannot resolve HEAD: {exc}")
        print("FAIL: 1 move-execution finding(s); tree unchanged")
        return 1
    try:
        records = apply_moves(args.root, planned)
    except MoveExecutionError as exc:
        for finding in exc.findings:
            print(f"FAIL: {finding}")
        print("FAIL: move phase failed after validation; tree needs review")
        return 1
    _atomic_write_json(
        args.inverse,
        {
            "manifest": str(args.manifest),
            "manifest_sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
            "head_before": head_sha,
            "moves": records,
        },
    )
    print(f"PASS: {len(records)} move(s) executed blob-identical; inverse record at {args.inverse}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
