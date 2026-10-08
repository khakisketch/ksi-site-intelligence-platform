"""Validate the current R0-R3 repository-normalization contract without mutation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "docs/audit/REPOSITORY_CLEANUP_MANIFEST_R0_R2.json"
SCHEMA_PATH = ROOT / "contracts/schemas/repository-cleanup-manifest.v1.json"
R3_MANIFEST_PATH = ROOT / "docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json"
R3_SCHEMA_PATH = ROOT / "contracts/schemas/repository-migration-manifest.v1.json"

R3_EXPECTED_MOVES = {
    "services/change-detection": "packages/change-detection",
    "services/bim-integration": "packages/bim-integration",
    "services/defect-detection": "packages/defect-detection",
}

SUPERSEDED_NAMES = (
    "02_SERVICE_BLUEPRINT_AND_UX.md",
    "ARCHITECTURE_DECISIONS_BASELINE_v2.0.md",
    "REQUIREMENTS_TRACEABILITY_BASELINE_v2.0.csv",
)
ACTIVE_AUTHORITY_PATHS = (
    "docs/00_READ_FIRST.md",
    "docs/product/PRODUCT_CONSTITUTION.md",
    "docs/product/FINAL_DECISION_LEDGER_v1.0.md",
    "docs/product/MASTER_PRD_v3.0.md",
    "docs/goals/PHASE_REGISTRY.yaml",
)
LINKED_NORMALIZATION_DOCS = (
    "README.md",
    "REPOSITORY_STRUCTURE.md",
    "apps/README.md",
    "services/README.md",
    "packages/README.md",
    # P3 Task 6: the edge top-level README moved blob-identical to its archive
    # mirror — dropped from the active-docs link gate (the archived copy is
    # historical, not a live routing doc).
    "design/README.md",
    "design-system/README.md",
    "scripts/README.md",
    "tools/README.md",
    "docs/README.md",
    "docs/00_READ_FIRST.md",
    "docs/DOCUMENT_STATUS.md",
    "docs/WORKSPACE_LAYOUT_AND_QUERY_GUIDE.md",
    "docs/architecture/ADR-KSI-033-repository-normalization-and-media-boundaries.md",
    "docs/architecture/ADR-KSI-034-service-package-runtime-boundary.md",
    "docs/architecture/02_SERVICE_BLUEPRINT_AND_UX.md",
    "docs/architecture/04_SOURCE_CODE_BOUNDARIES.md",
    "docs/architecture/ARCHITECTURE_DECISIONS_BASELINE_v2.0.md",
    "docs/audit/REPOSITORY_NAMING_AND_OWNERSHIP_AUDIT_R0_R2.md",
    "docs/design/README.md",
    "docs/hil/README.md",
    "docs/archive/ui-audit/legacy-root-captures/README.md",
    "packages/change-detection/README.md",
    "packages/bim-integration/README.md",
    "packages/defect-detection/README.md",
)
REQUIRED_STRUCTURE_PATHS = (
    "apps/dashboard/",
    "services/core/",
    "services/processing-controller/",
    "packages/change-detection/",
    "packages/bim-integration/",
    "packages/defect-detection/",
    # P3 Task 6: the gateway service and the three native edge groups moved
    # blob-identical to their archive mirrors — the required canonical path
    # is now the archive root itself (historical, not runtime or build
    # input; REPOSITORY_STRUCTURE.md records the relocation).
    "archive/acquisition-2026/",
    "contracts/",
    "packages/",
    "tests/contract/",
    "tests/replay/",
)
FORBIDDEN_R3_SERVICE_LIBRARY_PATHS = tuple(R3_EXPECTED_MOVES)
ROOT_GENERATED_DIRS = (
    "Testing",
    ".mypy_cache",
    ".playwright-mcp",
    ".pytest_cache",
    ".ruff_cache",
)
REQUIRED_OBSERVED_CANDIDATE_ACTIONS = {
    "licensed-local-geoid-source",
    "licensed-pinned-edge-sdk",
    "local-agent-and-governance-state",
    "local-model-artifacts",
    "local-python-toolchain",
    "local-secrets-and-machine-config",
    "module-local-generated-artifacts",
    "private-development-runtime-state",
}
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
GLOB_CHARACTER_RE = re.compile(r"\[[^\]]*\]|\*|\?")

# Python bytecode caches are the one generated class intentionally shared by every
# source owner. Other sourcePatterns must stay under one of the action's declared
# source roots so a cleanup declaration cannot silently grow repository-wide.
GLOBAL_GENERATED_SOURCE_PATTERNS = frozenset({"**/__pycache__/"})

# These paths belong to later evidence/HIL responsibility commits. R0-R2 may route
# to them, but its independently enforceable gate must not require their bytes.
DEFERRED_LATER_RESPONSIBILITY_PATHS = frozenset(
    {
        "docs/audit/01_CODEBASE_ARCHITECTURE_AUDIT.md",
        "docs/hil/HIL_1R_PHYSICAL_READINESS.md",
        "docs/hil/README.md",
    }
)


def _load_json(path: Path) -> dict[str, Any]:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r} in {path}")
            result[key] = value
        return result

    loaded = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_keys)
    if not isinstance(loaded, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return loaded


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _repo_path(root: Path, value: str) -> Path:
    path = Path(value.rstrip("/"))
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"manifest path must remain repository-relative: {value}")
    return root / path


def _source_pattern_probe(pattern: str) -> str:
    is_directory_pattern = pattern.endswith("/")
    components: list[str] = []
    for component in pattern.rstrip("/").split("/"):
        if component == "**":
            concrete = "ksi-normalization-probe"
        else:
            concrete = GLOB_CHARACTER_RE.sub("ksi-normalization-probe", component)
        components.append(concrete)
    if is_directory_pattern:
        components.append(".ksi-normalization-probe")
    return "/".join(components)


def _check_source_patterns(
    root: Path,
    action_id: object,
    raw_action: dict[str, Any],
    failures: list[str],
) -> None:
    sources = [
        source.rstrip("/")
        for source in raw_action.get("sources", [])
        if isinstance(source, str)
    ]
    for pattern in raw_action.get("sourcePatterns", []):
        if not isinstance(pattern, str):
            continue
        pattern_path = Path(pattern.rstrip("/"))
        if pattern_path.is_absolute() or ".." in pattern_path.parts:
            failures.append(
                f"source pattern must remain repository-relative: {action_id}: {pattern}"
            )
            continue

        owner_scoped = pattern in GLOBAL_GENERATED_SOURCE_PATTERNS or any(
            pattern.rstrip("/") == source or pattern.startswith(f"{source}/")
            for source in sources
        )
        if not owner_scoped:
            failures.append(f"source pattern is not owner-scoped: {action_id}: {pattern}")
            continue

        probe = _source_pattern_probe(pattern)
        try:
            result = subprocess.run(
                ["git", "check-ignore", "--no-index", "--quiet", "--", probe],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            failures.append(f"source pattern Git check failed: {action_id}: {pattern}: {exc}")
            continue
        if result.returncode == 1:
            failures.append(
                f"source pattern is not ignored by Git: {action_id}: {pattern}: probe={probe}"
            )
        elif result.returncode != 0:
            detail = result.stderr.strip() or f"exit {result.returncode}"
            failures.append(
                f"source pattern Git check failed: {action_id}: {pattern}: {detail}"
            )


def _check_schema(root: Path, failures: list[str]) -> dict[str, Any]:
    try:
        schema = _load_json(root / SCHEMA_PATH.relative_to(ROOT))
        manifest = _load_json(root / MANIFEST_PATH.relative_to(ROOT))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for error in sorted(validator.iter_errors(manifest), key=lambda item: list(item.path)):
            location = ".".join(str(part) for part in error.path) or "<root>"
            failures.append(f"manifest schema: {location}: {error.message}")
        return manifest
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"manifest/schema load failed: {exc}")
        return {}


def _check_r3_schema(root: Path, failures: list[str]) -> dict[str, Any]:
    try:
        schema = _load_json(root / R3_SCHEMA_PATH.relative_to(ROOT))
        manifest = _load_json(root / R3_MANIFEST_PATH.relative_to(ROOT))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        for error in sorted(validator.iter_errors(manifest), key=lambda item: list(item.path)):
            location = ".".join(str(part) for part in error.path) or "<root>"
            failures.append(f"R3 migration schema: {location}: {error.message}")
        return manifest
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"R3 migration manifest/schema load failed: {exc}")
        return {}


def _r3_migration_map(manifest: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    moves = manifest.get("moves")
    if not isinstance(moves, list):
        return result
    for entry in moves:
        if not isinstance(entry, dict):
            continue
        source = entry.get("source")
        destination = entry.get("destination")
        if isinstance(source, str) and isinstance(destination, str):
            result[source.rstrip("/")] = destination.rstrip("/")
    return result


def _existing_or_migrated_path(
    root: Path,
    value: str,
    migrated_paths: dict[str, str],
) -> Path | None:
    direct = _repo_path(root, value)
    if direct.exists():
        return direct

    normalized = value.rstrip("/")
    for source, destination in migrated_paths.items():
        if normalized == source:
            candidate = _repo_path(root, destination)
        elif normalized.startswith(f"{source}/"):
            suffix = normalized[len(source) :]
            candidate = _repo_path(root, f"{destination}{suffix}")
        else:
            continue
        if candidate.exists():
            return candidate

    # P3 acquisition separation: a reference that is gone from the active
    # tree but present under the archive mirror (archive/acquisition-2026/)
    # resolves there — relocated, not lost. This fallback asserts existence
    # under the mirror only; manifest approval lives in the move-decision
    # manifest (docs/audit/PHYSICAL_SITE_MOVE_DECISIONS_v1.csv) and the
    # Task 6 executor, not here. The historical R0-R2 manifest stays
    # byte-stable while this gate keeps proving nothing silently vanished.
    archived = _repo_path(root, f"archive/acquisition-2026/{normalized}")
    if archived.exists():
        return archived
    return None


def _check_r3_migration_paths(
    root: Path,
    manifest: dict[str, Any],
    failures: list[str],
    *,
    check_local_cleanup: bool,
) -> dict[str, str]:
    migrated_paths = _r3_migration_map(manifest)
    if migrated_paths != R3_EXPECTED_MOVES:
        failures.append(
            "R3 move map must exactly match the approved service/package boundary: "
            f"expected {R3_EXPECTED_MOVES}, got {migrated_paths}"
        )

    destinations: set[str] = set()
    for source, destination in migrated_paths.items():
        try:
            source_path = _repo_path(root, source)
            destination_path = _repo_path(root, destination)
        except ValueError as exc:
            failures.append(f"invalid R3 move path: {exc}")
            continue
        if destination in destinations:
            failures.append(f"duplicate R3 destination: {destination}")
        destinations.add(destination)
        if source_path.exists():
            failures.append(f"R3 source still exists: {source}")
        if not (destination_path / "pyproject.toml").is_file():
            failures.append(f"R3 package destination is missing pyproject.toml: {destination}")

    cleanup = manifest.get("cleanup")
    if isinstance(cleanup, list):
        for entry in cleanup:
            if not isinstance(entry, dict):
                continue
            cleanup_id = entry.get("id")
            state = entry.get("state")
            if state != "EXECUTED" and (
                check_local_cleanup or manifest.get("status") == "COMPLETE"
            ):
                failures.append(f"R3 cleanup remains PENDING: {cleanup_id}")
            for value in entry.get("sources", []):
                if isinstance(value, str):
                    try:
                        path = _repo_path(root, value)
                    except ValueError as exc:
                        failures.append(f"invalid R3 cleanup path: {cleanup_id}: {exc}")
                        continue
                    if check_local_cleanup and state == "EXECUTED" and path.exists():
                        failures.append(
                            f"executed R3 cleanup path still exists: {cleanup_id}: {value}"
                        )
            for pattern in entry.get("sourcePatterns", []):
                if not isinstance(pattern, str):
                    continue
                if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                    failures.append(f"invalid R3 cleanup pattern: {cleanup_id}: {pattern}")
                    continue
                if check_local_cleanup and state == "EXECUTED":
                    for match in root.glob(pattern):
                        failures.append(
                            f"executed R3 cleanup pattern still matches: {cleanup_id}: "
                            f"{match.relative_to(root)}"
                        )

    if manifest.get("status") == "COMPLETE":
        verification = manifest.get("verification")
        if isinstance(verification, list):
            for entry in verification:
                if not isinstance(entry, dict):
                    continue
                status = entry.get("status")
                if status not in {"PASS", "NOT_APPLICABLE"}:
                    failures.append(
                        "completed R3 migration has unresolved verification: "
                        f"{entry.get('command')}: {status}"
                    )

    for value in manifest.get("protectedPaths", []):
        if isinstance(value, str):
            try:
                protected_path = _repo_path(root, value)
            except ValueError as exc:
                failures.append(f"invalid protected path: {exc}")
                continue
            if check_local_cleanup and not protected_path.exists():
                failures.append(f"protected local path is missing: {value}")

    return migrated_paths


def _check_manifest_paths(
    root: Path,
    manifest: dict[str, Any],
    failures: list[str],
    *,
    check_local_cleanup: bool,
    migrated_paths: dict[str, str] | None = None,
) -> None:
    migrations = migrated_paths or {}
    actions = manifest.get("actions")
    if not isinstance(actions, list):
        return

    classifications: set[str] = set()
    action_ids: set[str] = set()
    for raw_action in actions:
        if not isinstance(raw_action, dict):
            continue
        action_id = raw_action.get("id")
        classification = raw_action.get("classification")
        if isinstance(action_id, str):
            if action_id in action_ids:
                failures.append(f"duplicate action id: {action_id}")
            action_ids.add(action_id)
        if isinstance(classification, str):
            classifications.add(classification)

        _check_source_patterns(root, action_id, raw_action, failures)

        for reference in raw_action.get("references", []):
            if not isinstance(reference, str):
                continue
            try:
                reference_path = _existing_or_migrated_path(root, reference, migrations)
            except ValueError as exc:
                failures.append(f"invalid action reference: {action_id}: {exc}")
                continue
            if (
                reference not in DEFERRED_LATER_RESPONSIBILITY_PATHS
                and reference_path is None
            ):
                failures.append(f"missing action reference: {action_id}: {reference}")

        source_presence = raw_action.get("sourcePresence", "REQUIRED_REPOSITORY_PATHS")
        if classification == "RETAIN" and source_presence == "REQUIRED_REPOSITORY_PATHS":
            for source in raw_action.get("sources", []):
                if not isinstance(source, str):
                    continue
                try:
                    source_path = _existing_or_migrated_path(root, source, migrations)
                except ValueError as exc:
                    failures.append(f"invalid retained source: {action_id}: {exc}")
                    continue
                if source_path is None:
                    failures.append(f"missing retained source: {action_id}: {source}")

        for artifact in raw_action.get("artifacts", []):
            if not isinstance(artifact, dict):
                continue
            source = artifact.get("source")
            destination = artifact.get("destination")
            expected_hash = artifact.get("sha256")
            if not all(isinstance(item, str) for item in (source, destination, expected_hash)):
                continue
            assert isinstance(source, str)
            assert isinstance(destination, str)
            assert isinstance(expected_hash, str)
            try:
                source_path = _repo_path(root, source)
                destination_path = _repo_path(root, destination)
            except ValueError as exc:
                failures.append(f"invalid archived artifact path: {action_id}: {exc}")
                continue
            if source_path.exists():
                failures.append(f"archived source still exists: {source}")
            if not destination_path.is_file():
                failures.append(f"archived destination missing: {destination}")
            elif _sha256(destination_path) != expected_hash:
                failures.append(f"archived destination hash mismatch: {destination}")

        if check_local_cleanup and classification == "REMOVE":
            for source in raw_action.get("sources", []):
                if not isinstance(source, str):
                    continue
                try:
                    source_path = _repo_path(root, source)
                except ValueError as exc:
                    failures.append(f"invalid removed source: {action_id}: {exc}")
                    continue
                if source_path.exists():
                    failures.append(f"removed local generated path still exists: {source}")

    expected = {"RETAIN", "CONSOLIDATE", "ARCHIVE", "REMOVE"}
    if classifications != expected:
        failures.append(
            "cleanup classification set must be exactly "
            f"{sorted(expected)}, got {sorted(classifications)}"
        )

    missing_candidate_actions = REQUIRED_OBSERVED_CANDIDATE_ACTIONS - action_ids
    if missing_candidate_actions:
        failures.append(
            "cleanup manifest omits observed candidate actions: "
            f"{sorted(missing_candidate_actions)}"
        )

    states = manifest.get("documentStates")
    if isinstance(states, list):
        for entry in states:
            if not isinstance(entry, dict):
                continue
            path = entry.get("path")
            if not isinstance(path, str):
                continue
            try:
                state_path = _repo_path(root, path)
            except ValueError as exc:
                failures.append(f"invalid document-state path: {exc}")
                continue
            if path not in DEFERRED_LATER_RESPONSIBILITY_PATHS and not state_path.exists():
                failures.append(f"document-state path missing: {path}")

    reachability = manifest.get("reachabilityAudit")
    if isinstance(reachability, list):
        for entry in reachability:
            if not isinstance(entry, dict):
                continue
            audit_id = entry.get("id")
            for field in ("paths", "dependencyEvidence", "buildEvidence", "ciEvidence"):
                for value in entry.get(field, []):
                    if not isinstance(value, str):
                        continue
                    try:
                        evidence_path = _existing_or_migrated_path(root, value, migrations)
                    except ValueError as exc:
                        failures.append(
                            f"invalid reachability path: {audit_id}.{field}: {exc}"
                        )
                        continue
                    if evidence_path is None:
                        failures.append(f"reachability path missing: {audit_id}.{field}: {value}")
            after = entry.get("after")
            if not isinstance(after, str) or not after.startswith("UNCHANGED_R0_R2"):
                failures.append(f"reachability after-state is not unchanged: {audit_id}")


def _check_structure_and_authority(root: Path, failures: list[str]) -> None:
    try:
        structure = (root / "REPOSITORY_STRUCTURE.md").read_text(encoding="utf-8")
    except OSError as exc:
        failures.append(f"repository structure unavailable: {exc}")
        return
    for required in REQUIRED_STRUCTURE_PATHS:
        if f"`{required}`" not in structure:
            failures.append(f"repository structure omits canonical path: {required}")
        if not _repo_path(root, required).exists():
            failures.append(f"canonical repository path is missing: {required}")

    for forbidden in FORBIDDEN_R3_SERVICE_LIBRARY_PATHS:
        if _repo_path(root, forbidden).exists():
            failures.append(f"import-only package regressed into services: {forbidden}")

    for relative in ACTIVE_AUTHORITY_PATHS:
        try:
            text = (root / relative).read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(f"active authority unavailable: {relative}: {exc}")
            continue
        for superseded in SUPERSEDED_NAMES:
            if superseded in text:
                failures.append(
                    f"active authority cites superseded document: {relative}: {superseded}"
                )

    boundary_path = (
        root / "docs/architecture/ADR-KSI-033-repository-normalization-and-media-boundaries.md"
    )
    try:
        boundary = boundary_path.read_text(encoding="utf-8")
    except OSError as exc:
        failures.append(f"ADR-KSI-033 unavailable: {exc}")
        return
    for required in (
        "SD/storage -> field PC -> KSI web upload",
        "Continuous central Liveview/video reception",
        "RETAIN",
        "CONSOLIDATE",
        "ARCHIVE",
        "REMOVE",
    ):
        if required not in boundary:
            failures.append(f"ADR-KSI-033 omits required decision text: {required}")


def _check_markdown_links(root: Path, failures: list[str]) -> None:
    for relative in LINKED_NORMALIZATION_DOCS:
        source = root / relative
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(f"normalization link source unavailable: {relative}: {exc}")
            continue
        for raw_target in MARKDOWN_LINK_RE.findall(text):
            target = raw_target.strip().strip("<>").split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            resolved = (source.parent / target).resolve()
            try:
                relative_target = resolved.relative_to(root.resolve()).as_posix()
            except ValueError:
                failures.append(f"link escapes repository: {relative}: {raw_target}")
                continue
            if relative_target in DEFERRED_LATER_RESPONSIBILITY_PATHS:
                continue
            if not resolved.exists():
                failures.append(f"broken normalization link: {relative}: {raw_target}")


def _check_root_hygiene(
    root: Path, failures: list[str], *, check_local_cleanup: bool
) -> None:
    for suffix in ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.html"):
        for path in root.glob(suffix):
            failures.append(f"root capture/generated asset is not canonical: {path.name}")
    for path in root.glob("generate*"):
        failures.append(f"root generator is not canonical: {path.name}")
    if check_local_cleanup:
        for name in ROOT_GENERATED_DIRS:
            if (root / name).exists():
                failures.append(f"root generated directory remains: {name}")


def validate_repository_normalization(
    root: Path = ROOT, *, check_local_cleanup: bool = False
) -> list[str]:
    """Return all current R0-R3 contract failures; an empty list is success."""

    failures: list[str] = []
    r3_manifest = _check_r3_schema(root, failures)
    migrated_paths: dict[str, str] = {}
    if r3_manifest:
        migrated_paths = _check_r3_migration_paths(
            root,
            r3_manifest,
            failures,
            check_local_cleanup=check_local_cleanup,
        )
    manifest = _check_schema(root, failures)
    if manifest:
        _check_manifest_paths(
            root,
            manifest,
            failures,
            check_local_cleanup=check_local_cleanup,
            migrated_paths=migrated_paths,
        )
    _check_structure_and_authority(root, failures)
    _check_markdown_links(root, failures)
    _check_root_hygiene(root, failures, check_local_cleanup=check_local_cleanup)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-local-cleanup",
        action="store_true",
        help="also require regenerable root cache directories to be absent",
    )
    parser.add_argument(
        "--check-r3-migration",
        action="store_true",
        help="require the approved R3 service/package migration contract (current default)",
    )
    args = parser.parse_args()
    failures = validate_repository_normalization(check_local_cleanup=args.check_local_cleanup)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: repository normalization R0-R3 contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
