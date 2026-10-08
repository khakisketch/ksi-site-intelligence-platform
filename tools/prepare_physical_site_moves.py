"""Current-revision acquisition move decision manifest (P3 Task 1).

Converts the frozen disposition inventory
(``docs/audit/PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv`` at baseline
``72c526b…`` — the byte-identical historical record, never edited here) into a
CURRENT-revision decision manifest: every ``ARCHIVE_CANDIDATE`` path is bound
to its present ``HEAD`` git object and blob SHA256. The frozen baseline hash
is kept per row as reference only — candidates may legitimately differ from
the baseline (foundation/P2 changed some files); the current blob hash is the
move binding the Task 6 executor will verify.

Protected rows (``.ai/``, ``references/``) are metadata-only and never
traversed: their content is never read, hashed, or delivered.

CLI: ``python tools/prepare_physical_site_moves.py --frozen <csv>
--out-csv <csv> --out-md <md>`` exits 0 only when every candidate resolves
cleanly, 1 with safe path/reason findings otherwise. Outputs are written to
temporary siblings and atomically renamed — a failing run never leaves
partial artifacts behind. No file is moved here.

Decision semantics: ``MOVE`` means a closure path exists in this plan (the
row's ``blockers`` list the exact ids later tasks must empty); ``DEFER``
means no closure path and the file stays; ``RETAIN`` means evidence shows
platform use. The Task 6 executor applies the refined rule (see the companion
``Executor contract`` section): ``is_executable(row)`` holds when every
blocker is a known vocabulary id, every T3/T5 id verifies as closed at the
then-current HEAD against its recorded evidence, every T6 id is closed by the
Task 6 same-batch consumer/CI/deploy/docs edits (machine-checked via
consumer resolution plus a live-reference scan), and every consumer resolves
active-or-archive. The executor refuses the WHOLE batch on any hash mismatch,
unknown blocker, unverified foreign closure, unresolvable consumer, live
reference, or destination collision. At this base every candidate is ``MOVE``;
the vocabulary (and its row-level invariants) is enforced for later tasks
that may defer or retain.

Consumer-resolution rule (P3 Task 5): a recorded consumer reference is
satisfied when the path exists either active or at
``archive/acquisition-2026/<path>`` — Tasks 3/5 relocate consumers
blob-identical, so the reference bytes are unchanged. Fail-closed when the
path exists in neither place (stale manifest entry).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import io
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]

FROZEN_COLUMNS = (
    "path",
    "baselineCommit",
    "gitMode",
    "gitObject",
    "sha256",
    "proposedDisposition",
    "proposedDestination",
    "requiredBeforeAction",
)

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

Decision = Literal["MOVE", "DEFER", "RETAIN"]
DECISIONS: tuple[Decision, ...] = ("MOVE", "DEFER", "RETAIN")

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

_HEX40 = re.compile(r"[0-9a-f]{40}").fullmatch
_BLOB_MODES = frozenset({"100644", "100755", "120000"})

_CORE = "services/core/src/ksi_core"

_CORE_CONTRACTS_CONSUMERS = (
    f"{_CORE}/capability/runtime_api.py",
    f"{_CORE}/composition/production_config.py",
    f"{_CORE}/domains/design/region_extraction_reports.py",
    f"{_CORE}/domains/edge_transport/edge_dispatch.py",
    f"{_CORE}/domains/missions/mission_atomicity.py",
    f"{_CORE}/domains/missions/mission_issuance.py",
    f"{_CORE}/domains/missions/mission_plans.py",
    f"{_CORE}/domains/missions/mission_records.py",
    f"{_CORE}/identity/signing_keys.py",
)
_CORE_PLANNING_CONSUMERS = (
    f"{_CORE}/domains/design/region_extraction_reports.py",
    f"{_CORE}/domains/missions/mission_plans.py",
)
_CORE_EQUIPMENT_CONSUMERS = (
    f"{_CORE}/domains/observations/equipment_states.py",
    f"{_CORE}/domains/observations/events.py",
)

# Group prefix (longest first) -> (group, consumers, extra blockers).
# Consumers are active-tree files with verified references (imports, COPY,
# CI jobs, pin scripts, routing mentions); per-path overrides below cover
# the edge/root files whose references differ file by file.
# P3 Task 5 note: services/core/pyproject.toml was a recorded consumer of the
# three package groups at the Task 1 base, but Task 5 dropped those exact
# dependencies (commit 2e85391) — the reference is gone by design (closure,
# not relocation), so it no longer gates here. The T5:core-dep-drop blocker
# ids stay as the closure record.
_GROUP_TABLE: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "packages/mission-contracts/",
        "packages/mission-contracts",
        (*_CORE_CONTRACTS_CONSUMERS,),
        ("T5:core-dep-drop",),
    ),
    (
        "packages/mission-planning/",
        "packages/mission-planning",
        (*_CORE_PLANNING_CONSUMERS,),
        ("T5:core-dep-drop",),
    ),
    (
        "packages/equipment-intelligence/",
        "packages/equipment-intelligence",
        (*_CORE_EQUIPMENT_CONSUMERS,),
        ("T5:core-dep-drop",),
    ),
    (
        "packages/perception/",
        "packages/perception",
        (
            # P3 Task 5 note: services/processing-controller/pyproject.toml was
            # a recorded consumer at the Task 1 base, but Task 3 dropped the
            # ksi-perception dependency when the managed worker split closed
            # that edge (commit 6a00443) — the reference is gone by design,
            # not relocated, so it no longer gates here.
            "services/processing-controller/src/ksi_processing_controller/runner.py",
            "services/processing-controller/src/ksi_processing_controller/odm_masking.py",
            "Dockerfile.external-inspector",
            "Dockerfile.external-measurement",
        ),
        ("T3:worker-managed-split", "T6:ci-docker-refs"),
    ),
    (
        "services/dji-gateway/",
        "services/dji-gateway",
        ("Dockerfile.gateway", "deploy/README.md"),
        ("T6:ci-docker-refs",),
    ),
    (
        "edge/manifold-runtime/",
        "edge/manifold-runtime",
        (".github/workflows/ci.yml",),
        ("T6:ci-docker-refs",),
    ),
    (
        "edge/psdk-app/",
        "edge/psdk-app",
        (".github/workflows/ci.yml",),
        ("T6:ci-docker-refs",),
    ),
    (
        "edge/psdk-tap/",
        "edge/psdk-tap",
        (".github/workflows/ci.yml",),
        ("T6:ci-docker-refs",),
    ),
    (
        "edge/msdk-field-bridge/",
        "edge/msdk-field-bridge",
        (),
        (),
    ),
    (
        "edge/",
        "edge/root",
        (),
        (),
    ),
)

# Edge/root files with their own verified active-tree references. Files not
# listed here (the waypoint allowlist, psdk_platform.cmake) are referenced
# only inside the moving batch or by generated build output, so they carry
# no active-tree consumers.
_PATH_CONSUMERS: dict[str, tuple[str, ...]] = {
    "edge/README.md": (
        "tools/validate_repository_normalization.py",
        "docs/WORKSPACE_LAYOUT_AND_QUERY_GUIDE.md",
    ),
    "edge/docker/manifold3-build.Dockerfile": (
        ".github/workflows/ci.yml",
        "scripts/manifold/manifoldctl",
        "scripts/manifold/manifold.env.example",
        "cmake/toolchain-manifold3.cmake",
    ),
    "edge/third_party/PSDK_LOCK.yaml": (
        "scripts/check_third_party_pins.sh",
        "tools/edge/fetch_psdk.py",
        ".github/workflows/ci.yml",
    ),
}
_PATH_EXTRA_BLOCKERS: dict[str, tuple[str, ...]] = {
    "edge/docker/manifold3-build.Dockerfile": ("T6:ci-docker-refs",),
    "edge/third_party/PSDK_LOCK.yaml": ("T6:ci-docker-refs",),
}

EXPECTED_GROUP_COUNTS = {
    "edge/manifold-runtime": 71,
    "edge/psdk-tap": 29,
    "services/dji-gateway": 28,
    "edge/psdk-app": 17,
    "packages/mission-contracts": 13,
    "packages/perception": 13,
    "packages/mission-planning": 9,
    "packages/equipment-intelligence": 7,
    "edge/root": 5,
    "edge/msdk-field-bridge": 2,
}


@dataclass(frozen=True)
class MoveDecision:
    """One current-revision move decision. ``git_object``/``blob_sha256`` bind
    the CURRENT HEAD blob (the move binding); the frozen baseline hashes are
    carried in the CSV reference columns, not here."""

    path: str
    git_object: str
    blob_sha256: str
    group: str
    decision: Decision
    destination: str | None
    blockers: tuple[str, ...]
    consumers: tuple[str, ...]


class MoveDecisionError(RuntimeError):
    """Controlled fail-closed finding set. Carries path/reason text only —
    never file content bytes."""

    def __init__(self, findings: list[str]) -> None:
        super().__init__("; ".join(findings[:5]))
        self.findings = findings


def _load_checker() -> Any:
    """Reuse the frozen-inventory validator's primitives via the repository
    file-location import pattern (no static ``tools.`` import, no
    ``sys.path`` mutation). Only path/plumbing helpers are used — frozen CSV
    constants beyond the baseline hash are not imported."""
    checker_path = ROOT / "tools" / "check_physical_site_disposition.py"
    spec = importlib.util.spec_from_file_location("prepare_moves_checker", checker_path)
    assert spec is not None and spec.loader is not None, checker_path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_checker = _load_checker()


def validate_decision_row(decision: MoveDecision) -> list[str]:
    """Row-level decision invariants. Empty list is success."""
    findings: list[str] = []
    if decision.decision not in DECISIONS:
        findings.append(f"({decision.path}): unknown decision {decision.decision!r}")
        return findings
    for blocker in decision.blockers:
        if not BLOCKER_PATTERN.fullmatch(blocker):
            findings.append(
                f"({decision.path}): unknown blocker id {blocker!r}; "
                "blockers must name the closing task"
            )
    if decision.decision == "MOVE":
        if decision.destination != f"{ARCHIVE_PREFIX}{decision.path}":
            findings.append(
                f"({decision.path}): MOVE destination must be "
                f"{ARCHIVE_PREFIX}{decision.path}; got {decision.destination!r}"
            )
        if f"T6:consumer-review:{decision.path}" not in decision.blockers:
            findings.append(
                f"({decision.path}): MOVE row must carry its own "
                f"T6:consumer-review:{decision.path} blocker"
            )
    elif decision.destination is not None:
        findings.append(f"({decision.path}): {decision.decision} row must not name a destination")
    return findings


def _classify(path: str) -> tuple[str, tuple[str, ...], tuple[str, ...]] | None:
    """Map a candidate path to (group, consumers, extra blockers)."""
    for prefix, group, consumers, extra in _GROUP_TABLE:
        if path.startswith(prefix):
            if group == "edge/root":
                return (
                    group,
                    _PATH_CONSUMERS.get(path, ()),
                    _PATH_EXTRA_BLOCKERS.get(path, ()),
                )
            return (group, consumers, extra)
    return None


def _core_closure_blockers(consumers: tuple[str, ...]) -> tuple[str, ...]:
    """One ``T5:core-import-closure:<file>`` per Core consumer file."""
    return tuple(
        sorted(
            f"T5:core-import-closure:{consumer}"
            for consumer in consumers
            if consumer.startswith(_CORE) and consumer.endswith(".py")
        )
    )


def build_move_decisions(frozen_csv: Path, repo: Path) -> tuple[MoveDecision, ...]:
    """Bind every frozen ``ARCHIVE_CANDIDATE`` to its current HEAD blob.

    Raises :class:`MoveDecisionError` on any inconsistency (missing path,
    non-blob kind, unreadable blob, unknown group, bad destination,
    non-canonical spelling, decision-invariant violation). Protected rows
    are metadata-only and never traversed. Read-only: only ``git ls-tree`` /
    ``git cat-file`` against the current checkout.
    """
    try:
        raw = frozen_csv.read_bytes()
    except OSError as exc:
        raise MoveDecisionError([f"frozen inventory unreadable: {frozen_csv}: {exc}"]) from exc
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise MoveDecisionError(
            [f"frozen inventory is not UTF-8 decodable: {frozen_csv}; refused"]
        ) from None

    try:
        reader = csv.reader(text.splitlines(), strict=True)
        header = next(reader)
    except StopIteration:
        raise MoveDecisionError(["frozen inventory is empty"]) from None
    except csv.Error as exc:
        raise MoveDecisionError([f"frozen inventory CSV parse error: {exc}"]) from exc
    if list(header) != list(FROZEN_COLUMNS):
        raise MoveDecisionError(
            ["frozen inventory header must be exactly " + ",".join(FROZEN_COLUMNS)]
        ) from None

    rows: list[dict[str, str]] = []
    try:
        for fields in reader:
            if fields == []:
                continue
            if len(fields) != len(FROZEN_COLUMNS):
                raise MoveDecisionError(["frozen inventory has a malformed row; row refused"])
            rows.append(dict(zip(FROZEN_COLUMNS, (f.strip() for f in fields), strict=True)))
    except csv.Error as exc:
        raise MoveDecisionError([f"frozen inventory CSV parse error mid-file: {exc}"]) from exc

    candidates = [row for row in rows if row["proposedDisposition"] == "ARCHIVE_CANDIDATE"]
    if not candidates:
        raise MoveDecisionError(["frozen inventory names no ARCHIVE_CANDIDATE rows"])

    findings: list[str] = []
    resolved: list[tuple[dict[str, str], str, tuple[str, ...], tuple[str, ...]]] = []
    for row in candidates:
        path = row["path"]
        reason = _checker._canonical_repo_path(path)
        if reason is not None:
            findings.append(f"({path}): {reason}; row refused")
            continue
        destination = row["proposedDestination"]
        dest_reason = _checker._canonical_repo_path(destination)
        if dest_reason is not None:
            findings.append(f"({path}): destination {dest_reason}; row refused")
            continue
        if destination != f"{ARCHIVE_PREFIX}{path}":
            findings.append(
                f"({path}): candidate destination must be {ARCHIVE_PREFIX}{path}; got {destination}"
            )
            continue
        classified = _classify(path)
        if classified is None:
            findings.append(f"({path}): unknown acquisition group; row refused")
            continue
        group, consumers, extra = classified
        resolved.append((row, group, consumers, extra))
    if findings:
        raise MoveDecisionError(findings)

    # Current-revision bindings: one ls-tree over HEAD, one batch blob read.
    # Protected paths can never appear here (candidates only), so every
    # requested object is an acquisition blob by construction.
    try:
        ls_proc = subprocess.run(
            ["git", "ls-tree", "-r", "-z", "HEAD"],
            cwd=repo,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise MoveDecisionError([f"git is unavailable or failed to start: {exc}"]) from exc
    if ls_proc.returncode != 0:
        raise MoveDecisionError(["git ls-tree of HEAD failed; cannot bind revisions"])
    try:
        ls_text = ls_proc.stdout.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise MoveDecisionError(["git ls-tree output is not decodable"]) from exc
    head_map: dict[str, tuple[str, str, str]] = {}
    for entry in ls_text.split("\0"):
        if not entry:
            continue
        try:
            meta, entry_path = entry.split("\t")
            mode, kind, obj = meta.split(" ")
        except ValueError as exc:
            raise MoveDecisionError(["git ls-tree output is malformed"]) from exc
        head_map[entry_path] = (mode, kind, obj)

    wanted: dict[str, str] = {}
    for row, _group, _consumers, _extra in resolved:
        path = row["path"]
        head_entry = head_map.get(path)
        if head_entry is None:
            findings.append(f"({path}): missing at HEAD; no silent skip")
            continue
        mode, kind, obj = head_entry
        if kind != "blob" or mode not in _BLOB_MODES or not _HEX40(obj):
            findings.append(f"({path}): not a movable blob at HEAD ({mode} {kind}); row refused")
            continue
        wanted[path] = obj
    if findings:
        raise MoveDecisionError(findings)

    try:
        blobs = _checker._batch_blob_bytes(repo, set(wanted.values()))
    except (_checker._PlumbingError, OSError) as exc:
        raise MoveDecisionError([f"{exc}; no manifest produced"]) from exc

    decisions: list[MoveDecision] = []
    for row, group, consumers, extra in resolved:
        path = row["path"]
        obj = wanted[path]
        content = blobs.get(obj)
        if content is None:
            findings.append(f"({path}): HEAD blob {obj} is unreadable")
            continue
        digest = hashlib.sha256(content).hexdigest()
        blockers = (
            _core_closure_blockers(consumers)
            + tuple(sorted(extra))
            + (f"T6:consumer-review:{path}", "T6:docs-routing")
        )
        decision = MoveDecision(
            path=path,
            git_object=obj,
            blob_sha256=digest,
            group=group,
            decision="MOVE",
            destination=f"{ARCHIVE_PREFIX}{path}",
            blockers=tuple(sorted(set(blockers))),
            consumers=consumers,
        )
        row_findings = validate_decision_row(decision)
        if row_findings:
            findings.extend(row_findings)
            continue
        decisions.append(decision)
    if findings:
        raise MoveDecisionError(findings)

    decisions.sort(key=lambda decision: decision.path)
    paths = [decision.path for decision in decisions]
    if len(set(paths)) != len(paths):
        raise MoveDecisionError(["duplicate decision rows produced; refused"])
    return tuple(decisions)


def _frozen_reference_map(frozen_csv: Path) -> dict[str, tuple[str, str]]:
    """{candidate path: (baseline gitObject, baseline sha256)} for CSV
    reference columns."""
    with frozen_csv.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return {
            row["path"]: (row["gitObject"], row["sha256"])
            for row in reader
            if row["proposedDisposition"] == "ARCHIVE_CANDIDATE"
        }


def render_csv(decisions: tuple[MoveDecision, ...], frozen_csv: Path) -> str:
    """Render the decision CSV (deterministic row order, ``;``-joined lists)."""
    reference = _frozen_reference_map(frozen_csv)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(DECISION_COLUMNS)
    for decision in decisions:
        baseline_obj, baseline_digest = reference[decision.path]
        writer.writerow(
            [
                decision.path,
                decision.git_object,
                decision.blob_sha256,
                baseline_obj,
                baseline_digest,
                decision.group,
                decision.decision,
                decision.destination or "",
                ";".join(decision.blockers),
                ";".join(decision.consumers),
            ]
        )
    return buffer.getvalue()


def render_md(
    decisions: tuple[MoveDecision, ...],
    frozen_csv: Path,
    head_sha: str,
    frozen_sha256: str,
    baseline: str,
) -> str:
    """Render the decision companion document."""
    by_decision: dict[str, int] = {}
    by_group: dict[str, list[MoveDecision]] = {}
    for decision in decisions:
        by_decision[decision.decision] = by_decision.get(decision.decision, 0) + 1
        by_group.setdefault(decision.group, []).append(decision)

    out: list[str] = []
    out.append("# Physical-site move decisions (current-revision manifest)")
    out.append("")
    out.append("Current-revision move decision manifest for P3 (acquisition separation).")
    out.append(
        f"Base: current checkout HEAD `{head_sha}`. Every row binds the CURRENT "
        "HEAD git object and blob SHA256 as the move binding the Task 6 "
        "executor verifies; the frozen baseline hashes are reference only."
    )
    out.append("")
    out.append("## Frozen record (historical, unchanged)")
    out.append("")
    out.append(
        f"The frozen inventory `{frozen_csv.name}` (SHA256 `{frozen_sha256}`, "
        f"baseline `{baseline}`) remains the historical record of the 72c526b "
        "baseline. It is never edited by this plan; candidates may "
        "legitimately differ from it (foundation/P2 changed some files, e.g. "
        "mission-contracts signing/models), and the current blob hash above "
        "is authoritative for the move."
    )
    out.append("")
    out.append("## Decisions")
    out.append("")
    for name in DECISIONS:
        out.append(f"- {name}: {by_decision.get(name, 0)}")
    out.append("")
    out.append("## Per-group decisions")
    out.append("")
    out.append("| group | rows | decision | blockers (closed by) | consumers |")
    out.append("| --- | --- | --- | --- | --- |")
    for group in sorted(by_group):
        rows = by_group[group]
        blockers = sorted({b for row in rows for b in row.blockers})
        consumers = rows[0].consumers
        owners = sorted({b.split(":")[0] for b in blockers})
        out.append(
            f"| `{group}` | {len(rows)} | {rows[0].decision} "
            f"| {len(blockers)} ids ({', '.join(owners)}) "
            f"| {len(consumers)} files |"
        )
    out.append("")
    out.append("## Blocker-id legend and lifecycle")
    out.append("")
    out.append(
        "- `T3:worker-managed-split` — closed by Task 3 (managed-only worker "
        "modules leave the package; the surviving lanes keep no acquisition "
        "imports)."
    )
    out.append(
        "- `T5:core-import-closure:<core-file>` — closed by Task 5 (the named "
        "Core file no longer imports the candidate package; neutral "
        "extraction or import swap recorded per file)."
    )
    out.append(
        "- `T5:core-dep-drop` — closed by Task 5 (the three package "
        "dependencies leave `services/core/pyproject.toml`)."
    )
    out.append(
        "- `T6:consumer-review:<path>` — closed by Task 6 pre-move checks "
        "(no live reference to the path outside the archive remains; "
        "referencing tools/tests/docs updated in the same batch)."
    )
    out.append(
        "- `T6:ci-docker-refs` — closed by Task 6 pre-move checks (Dockerfile "
        "COPY/ENTRYPOINT, CI cmake/ctest jobs, pin scripts repointed)."
    )
    out.append(
        "- `T6:docs-routing` — closed by Task 6 (routing notes in "
        "`REPOSITORY_STRUCTURE.md`/`DOCUMENT_STATUS.md` updated for the move)."
    )
    out.append(
        "T3–T5 blockers are emptied by those tasks and recorded in their "
        "commits; T6 blockers are emptied by the Task 6 pre-move verification "
        "before the executor runs."
    )
    out.append("")
    out.append("## Executor contract (Task 6 — refined rule)")
    out.append("")
    out.append(
        "The executor (`tools/execute_physical_site_moves.py`) applies the "
        "refined Task 6 rule: `is_executable(row)` holds when every blocker "
        "is a known vocabulary id, every T3/T5 id verifies as closed at the "
        "then-current HEAD against its recorded evidence (dep-drop absence, "
        "import-closure absence-or-clean, managed-split absence), every T6 "
        "id is closed by the Task 6 same-batch consumer/CI/deploy/docs edits "
        "(machine-checked by consumer resolution active-or-archive plus a "
        "live-reference scan over non-docs HEAD files), and every consumer "
        "resolves active-or-archive. It re-verifies each row's "
        "`git_object`/`blob_sha256` against the then-current HEAD, performs "
        "git-tracked moves to the exact `destination` only after ALL rows "
        "validate (never partial moves), and records the "
        "inverse per move. A candidate missing at HEAD is a controlled "
        "finding (fail-closed with a clear reason) — rows are never silently "
        "skipped, and `DEFER` (file stays, no closure path) or `RETAIN` "
        "(evidence shows platform use) apply only with recorded evidence."
    )
    out.append("")
    out.append("## Consumer evidence (verified at this base)")
    out.append("")
    out.append(
        "- Core import sites: 11 files with real `from`/`import` statements "
        "against the candidate packages (9 mission-contracts, 2 "
        "mission-planning, 2 equipment-intelligence; docstring-only mentions "
        "in `sites.py`/`auth.py`/`source_media.py` are not imports and carry "
        "no blocker)."
    )
    out.append(
        "- Worker: `ksi_perception` imported only by managed-only modules "
        "`runner.py:83` and `odm_masking.py:75` (leave in Task 3); "
        "`ksi_change_detection` users are retained lanes, not candidates."
    )
    out.append(
        "- CI `edge-control-plane`/`edge-psdk-app-host`/`edge-psdk-tap`/`edge-manifold-target` "
        "jobs build the edge groups; `check_third_party_pins.sh` + "
        "`tools/edge/fetch_psdk.py` pin `PSDK_LOCK.yaml`."
    )
    out.append(
        "- Build images: `Dockerfile.external-inspector` and "
        "`Dockerfile.external-measurement` COPY `packages/perception`; "
        "`Dockerfile.gateway` runs the gateway entrypoint; "
        "`edge/docker/manifold3-build.Dockerfile` is the CI build image "
        "referenced by the manifold-target job and `manifoldctl`."
    )
    out.append(
        "- No active-tree Python module outside `services/dji-gateway` "
        "imports `ksi_dji_gateway`; `deploy/compose.yaml` names no gateway "
        "service."
    )
    out.append("")
    return "\n".join(out)


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frozen", required=True, type=Path, help="Frozen inventory CSV")
    parser.add_argument("--out-csv", required=True, type=Path, help="Decision CSV to write")
    parser.add_argument("--out-md", required=True, type=Path, help="Companion MD to write")
    parser.add_argument("--root", default=ROOT, type=Path, help="Repository checkout to bind")
    args = parser.parse_args(argv)

    try:
        decisions = build_move_decisions(args.frozen, args.root)
    except MoveDecisionError as exc:
        for finding in exc.findings:
            print(f"FAIL: {finding}")
        print(f"FAIL: {len(exc.findings)} move-decision finding(s); no manifest produced")
        return 1

    try:
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=args.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"FAIL: cannot resolve HEAD: {exc}")
        print("FAIL: 1 move-decision finding(s); no manifest produced")
        return 1
    frozen_sha256 = hashlib.sha256(args.frozen.read_bytes()).hexdigest()
    csv_text = render_csv(decisions, args.frozen)
    md_text = render_md(
        decisions,
        args.frozen,
        head_sha,
        frozen_sha256,
        _checker.EXPECTED_BASELINE,
    )
    by_decision: dict[str, int] = {}
    for decision in decisions:
        by_decision[decision.decision] = by_decision.get(decision.decision, 0) + 1
    # Fail-closed atomicity: both artifacts fully rendered and validated
    # before either path is touched; temp + rename, never partial outputs.
    _atomic_write(args.out_csv, csv_text)
    _atomic_write(args.out_md, md_text)
    summary = ", ".join(f"{name}={by_decision.get(name, 0)}" for name in DECISIONS)
    print(f"PASS: {len(decisions)} move decisions at {head_sha} ({summary}); no moves executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
