#!/usr/bin/env python3
"""Validate the deterministic Core R1 module-routing inventory.

The checker deliberately enforces only the relocation boundaries this slice can
prove.  It does not infer a whole-domain DAG: existing cross-domain imports
remain recorded baseline shape until their later owner slice relocates them.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TypeGuard

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPOSITORY_ROOT / "docs/audit/CORE_R1_MODULE_MIGRATION.json"
DEFAULT_MODULE_ROOT = REPOSITORY_ROOT / "services/core/src"
COMPOSITION_MODULES = frozenset(
    {
        "ksi_core.app",
        "ksi_core.app_assembly",
        "ksi_core.production",
    }
)
MIGRATION_STATUSES = frozenset(
    {
        "RETAIN",
        "T1_MOVED",
        "T1_NEW_INERT_PACKAGE",
        "T2_MOVED",
        "T2_NEW_INERT_PACKAGE",
        "T2_PLANNED",
        "T3_PLANNED",
        "T3_MOVED",
        "T3_NEW_INERT_PACKAGE",
        "T3_NEW_MODULE",
        "T5_PLANNED",
        "T5_MOVED",
        "T5_NEW_INERT_PACKAGE",
        "T5_NEW_MODULE",
    }
)
MIGRATION_STATUSES_WITH_PLANNED_TARGETS = MIGRATION_STATUSES - {"T5_PLANNED"}
RETENTION_MODULE = "ksi_core.foundation.retention"
RETENTION_RUNTIME_DOMAIN_IMPORTS = ("ksi_core.evidence",)
RETENTION_TYPE_DOMAIN_IMPORTS = ("ksi_core.evidence", "ksi_core.events")
FOUNDATION_ALLOWLIST_FIELDS = (
    "permittedFoundationRuntimeImports",
    "permittedFoundationTypeImports",
)


class _ImportVisitor(ast.NodeVisitor):
    def __init__(
        self, current_module: str, current_is_package: bool, known_modules: frozenset[str]
    ) -> None:
        current_parts = current_module.split(".")
        self._current_package = current_parts if current_is_package else current_parts[:-1]
        self._known_modules = known_modules
        self._type_checking_depth = 0
        self.imports: list[tuple[str, bool]] = []

    def visit_If(self, node: ast.If) -> None:  # noqa: N802
        is_type_checking = (
            isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
            or isinstance(node.test, ast.Attribute)
            and isinstance(node.test.value, ast.Name)
            and node.test.value.id == "typing"
            and node.test.attr == "TYPE_CHECKING"
        )
        if is_type_checking:
            self._type_checking_depth += 1
        for statement in node.body:
            self.visit(statement)
        if is_type_checking:
            self._type_checking_depth -= 1
        for statement in node.orelse:
            self.visit(statement)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            self.imports.append((alias.name, self._type_checking_depth > 0))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        target = self._resolve_from_target(node)
        if target is not None:
            type_only = self._type_checking_depth > 0
            self.imports.append((target, type_only))
            for alias in node.names:
                member_target = f"{target}.{alias.name}"
                if alias.name != "*" and member_target in self._known_modules:
                    self.imports.append((member_target, type_only))

    def _resolve_from_target(self, node: ast.ImportFrom) -> str | None:
        if node.level == 0:
            return node.module
        base = self._current_package[: len(self._current_package) - (node.level - 1)]
        if not base:
            return node.module
        if node.module is None:
            return ".".join(base)
        return ".".join((*base, *node.module.split(".")))


def _read_inventory(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"cannot read inventory {path}: {exc}"]
    if not isinstance(raw, dict):
        return None, ["inventory root must be an object"]
    if raw.get("schemaVersion") != 1:
        return None, ["inventory schemaVersion must be 1"]
    if raw.get("ownerModule") != "services/core":
        return None, ["inventory ownerModule must be services/core"]
    if not isinstance(raw.get("modules"), list):
        return None, ["inventory modules must be an array"]
    return raw, []


def _nonempty_string(value: Any) -> TypeGuard[str]:
    return isinstance(value, str) and bool(value)


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return duplicates


def _cross_record_collisions(
    records: Iterable[dict[str, Any]], fields: tuple[str, ...]
) -> set[str]:
    record_indexes_by_value: dict[str, set[int]] = {}
    for index, record in enumerate(records):
        for field in fields:
            value = record.get(field)
            if _nonempty_string(value):
                record_indexes_by_value.setdefault(value, set()).add(index)
    return {value for value, indexes in record_indexes_by_value.items() if len(indexes) > 1}


def _validate_foundation_allowlists(record: dict[str, Any], errors: list[str]) -> None:
    module_name = record["activeCanonicalModule"]
    if module_name != RETENTION_MODULE:
        if any(field in record for field in FOUNDATION_ALLOWLIST_FIELDS):
            errors.append(
                f"foundation import allowlists are reserved for {RETENTION_MODULE}: {module_name}"
            )
        return
    if record.get("permittedFoundationRuntimeImports") != list(RETENTION_RUNTIME_DOMAIN_IMPORTS):
        errors.append("retention runtime foundation allowlist must equal: ksi_core.evidence")
    if record.get("permittedFoundationTypeImports") != list(RETENTION_TYPE_DOMAIN_IMPORTS):
        errors.append(
            "retention type foundation allowlist must equal: ksi_core.evidence, ksi_core.events"
        )


def _validate_planned_routing_fields(index: int, record: dict[str, Any], errors: list[str]) -> None:
    status = record["migrationStatus"]
    if status in MIGRATION_STATUSES_WITH_PLANNED_TARGETS:
        required = ("plannedCanonicalModule", "plannedPath")
        missing = [field for field in required if not _nonempty_string(record.get(field))]
        if missing:
            errors.append(f"modules[{index}] missing planned routing fields: {', '.join(missing)}")
        elif not record["plannedPath"].endswith(".py"):
            errors.append(f"modules[{index}] plannedPath must name a Python file")
        return
    if record.get("plannedCanonicalModule") is not None or record.get("plannedPath") is not None:
        errors.append(
            f"modules[{index}] T5_PLANNED must defer plannedCanonicalModule and plannedPath"
        )
    if not _nonempty_string(record.get("plannedDestination")):
        errors.append(f"modules[{index}] T5_PLANNED requires plannedDestination")


def _is_domain_boundary(owner: str) -> bool:
    return owner == "domains" or owner.startswith("domains/")


def _is_domain_import(module_name: str, module_by_name: dict[str, dict[str, Any]]) -> bool:
    if module_name == "ksi_core.domains" or module_name.startswith("ksi_core.domains."):
        return True
    record = module_by_name.get(module_name)
    return record is not None and _is_domain_boundary(str(record.get("ownerBoundary", "")))


def _validate_inventory_shape(
    inventory: dict[str, Any], module_root: Path
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    errors: list[str] = []
    modules: list[dict[str, Any]] = []
    for index, record in enumerate(inventory["modules"]):
        if not isinstance(record, dict):
            errors.append(f"modules[{index}] must be an object")
            continue
        required = (
            "sourceModule",
            "activeCanonicalModule",
            "activePath",
            "ownerBoundary",
            "migrationStatus",
        )
        missing = [field for field in required if not _nonempty_string(record.get(field))]
        if missing:
            errors.append(f"modules[{index}] missing required fields: {', '.join(missing)}")
            continue
        if record["migrationStatus"] not in MIGRATION_STATUSES:
            errors.append(f"modules[{index}] unknown migrationStatus: {record['migrationStatus']}")
            continue
        if not record["activePath"].endswith(".py"):
            errors.append(f"modules[{index}] activePath must name a Python file")
            continue
        if record.get("legacyModule") is not None and not _nonempty_string(record["legacyModule"]):
            errors.append(f"modules[{index}] legacyModule must be a nonempty string or null")
        if record.get("legacyPath") is not None and not _nonempty_string(record["legacyPath"]):
            errors.append(f"modules[{index}] legacyPath must be a nonempty string or null")
        if (record.get("legacyModule") is None) != (record.get("legacyPath") is None):
            errors.append(f"modules[{index}] legacyModule and legacyPath must appear together")
        _validate_planned_routing_fields(index, record, errors)
        _validate_foundation_allowlists(record, errors)
        modules.append(record)

    for field, label in (
        ("sourceModule", "duplicate source module"),
        ("activeCanonicalModule", "duplicate active canonical module"),
        ("activePath", "duplicate active path"),
        ("plannedCanonicalModule", "duplicate planned canonical module"),
        ("plannedPath", "duplicate planned path"),
    ):
        duplicates = _duplicates(
            record[field] for record in modules if _nonempty_string(record.get(field))
        )
        errors.extend(f"{label}: {value}" for value in sorted(duplicates))

    for value in sorted(
        _cross_record_collisions(
            modules,
            (
                "sourceModule",
                "legacyModule",
                "activeCanonicalModule",
                "plannedCanonicalModule",
            ),
        )
    ):
        errors.append(f"cross-record module collision: {value}")
    for value in sorted(
        _cross_record_collisions(
            modules,
            ("legacyPath", "activePath", "plannedPath"),
        )
    ):
        errors.append(f"cross-record path collision: {value}")
    for field, label in (
        ("legacyModule", "duplicate legacy module"),
        ("legacyPath", "duplicate legacy path"),
    ):
        duplicates = _duplicates(
            record[field] for record in modules if _nonempty_string(record.get(field))
        )
        errors.extend(f"{label}: {value}" for value in sorted(duplicates))

    expected_paths = {record["activePath"] for record in modules}
    expected_paths.update(record["legacyPath"] for record in modules if record.get("legacyPath"))
    actual_paths = {
        path.relative_to(module_root).as_posix()
        for path in (module_root / "ksi_core").rglob("*.py")
    }
    missing_entries = actual_paths - expected_paths
    stale_entries = expected_paths - actual_paths
    if missing_entries:
        errors.append(
            "missing inventory entries for source paths: " + ", ".join(sorted(missing_entries))
        )
    if stale_entries:
        errors.append(
            "inventory paths absent from source tree: " + ", ".join(sorted(stale_entries))
        )

    module_by_name: dict[str, dict[str, Any]] = {}
    for record in modules:
        for field in ("sourceModule", "activeCanonicalModule", "legacyModule"):
            module_name = record.get(field)
            if _nonempty_string(module_name):
                module_by_name[module_name] = record
    return modules, module_by_name, errors


def _validate_boundaries(
    modules: Iterable[dict[str, Any]], module_by_name: dict[str, dict[str, Any]], module_root: Path
) -> list[str]:
    errors: list[str] = []
    known_modules = frozenset(module_by_name)
    for record in modules:
        sources = [(record["activeCanonicalModule"], record["activePath"])]
        if record.get("legacyPath"):
            sources.append((record["legacyModule"], record["legacyPath"]))
        for module_name, relative_path in sources:
            source_path = module_root / relative_path
            try:
                tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            except (OSError, SyntaxError) as exc:
                errors.append(f"cannot parse {relative_path}: {exc}")
                continue
            visitor = _ImportVisitor(
                module_name,
                relative_path.endswith("/__init__.py"),
                known_modules,
            )
            visitor.visit(tree)
            owner_boundary = record["ownerBoundary"]
            for imported_module, type_only in visitor.imports:
                if owner_boundary == "foundation" and _is_domain_import(
                    imported_module, module_by_name
                ):
                    allowed = (
                        RETENTION_TYPE_DOMAIN_IMPORTS
                        if type_only and record["activeCanonicalModule"] == RETENTION_MODULE
                        else RETENTION_RUNTIME_DOMAIN_IMPORTS
                        if record["activeCanonicalModule"] == RETENTION_MODULE
                        else frozenset()
                    )
                    if imported_module not in allowed:
                        edge_kind = "type-only" if type_only else "runtime"
                        errors.append(
                            "foundation module imports a domain "
                            f"({edge_kind}): {module_name} -> {imported_module}"
                        )
                if _is_domain_boundary(str(owner_boundary)) and (
                    imported_module in COMPOSITION_MODULES
                    or imported_module.startswith("ksi_core.composition")
                ):
                    errors.append(
                        f"domain module imports composition: {module_name} -> {imported_module}"
                    )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--module-root", type=Path, default=DEFAULT_MODULE_ROOT)
    arguments = parser.parse_args(argv)

    inventory, errors = _read_inventory(arguments.inventory)
    if inventory is not None:
        modules, module_by_name, shape_errors = _validate_inventory_shape(
            inventory, arguments.module_root
        )
        errors.extend(shape_errors)
        if not shape_errors:
            errors.extend(_validate_boundaries(modules, module_by_name, arguments.module_root))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    assert inventory is not None
    print(f"Core R1 module boundaries OK: {len(inventory['modules'])} inventory records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
