#!/usr/bin/env python3
"""Fail closed when a pinned PSDK archive cannot expose upload without Action.

The static linker selects archive members, not individual functions.  A source
allowlist therefore is insufficient when ``UploadKmzFile`` and a forbidden
Waypoint symbol live in the same member.  This tool records that object-level
fact without extracting, rewriting, stripping, or otherwise modifying the DJI
SDK archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

_REQUIRED_SYMBOLS = frozenset(
    {"DjiWaypointV3_Init", "DjiWaypointV3_UploadKmzFile", "DjiWaypointV3_DeInit"}
)
_FORBIDDEN_SYMBOL = "DjiWaypointV3_Action"
_NM_LINE = re.compile(
    r"^(?P<archive>.+\.a):(?P<member>[^:]+):[0-9A-Fa-f]+\s+"
    r"(?P<binding>[A-Za-z])\s+(?P<symbol>DjiWaypointV3_[A-Za-z0-9_]+)$"
)


@dataclass(frozen=True)
class SymbolLocation:
    member: str
    binding: str


@dataclass(frozen=True)
class ArchiveAudit:
    status: str
    reason_codes: tuple[str, ...]
    sdk_version: str | None
    archive_sha256: str | None
    selected_members: tuple[str, ...]
    required_symbols: dict[str, tuple[SymbolLocation, ...]]
    retained_waypoint_symbols: dict[str, tuple[SymbolLocation, ...]]
    unexpected_symbols: tuple[str, ...]
    flight_action_started: bool = False
    camera_write: bool = False


class LockError(ValueError):
    """The small set of required PSDK lock fields is absent or ambiguous."""


def _single_lock_value(text: str, key: str) -> str:
    values: list[str] = []
    pattern = re.compile(rf"^\s*{re.escape(key)}:\s*([^#\n]+)", re.MULTILINE)
    for match in pattern.finditer(text):
        values.append(match.group(1).strip().strip('"\''))
    if len(values) != 1 or not values[0]:
        raise LockError(f"PSDK lock must contain exactly one {key}")
    return values[0]


def read_lock(lock_path: Path) -> tuple[str, str, str]:
    text = lock_path.read_text(encoding="utf-8")
    return (
        _single_lock_value(text, "observed_version"),
        _single_lock_value(text, "library_path"),
        _single_lock_value(text, "library_sha256_on_device"),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_nm_locations(output: str) -> dict[str, tuple[SymbolLocation, ...]]:
    locations: dict[str, list[SymbolLocation]] = {}
    for raw_line in output.splitlines():
        match = _NM_LINE.match(raw_line.strip())
        if match is None:
            continue
        symbol = match.group("symbol")
        locations.setdefault(symbol, []).append(
            SymbolLocation(member=match.group("member"), binding=match.group("binding"))
        )
    return {
        symbol: tuple(sorted(items, key=lambda item: (item.member, item.binding)))
        for symbol, items in sorted(locations.items())
    }


def audit_archive(*, lock_path: Path, psdk_root: Path, nm_tool: str = "nm") -> ArchiveAudit:
    try:
        sdk_version, library_rel, expected_sha256 = read_lock(lock_path)
    except (OSError, UnicodeError, LockError) as exc:
        return ArchiveAudit(
            status="UNAVAILABLE",
            reason_codes=(f"LOCK_INVALID:{exc}",),
            sdk_version=None,
            archive_sha256=None,
            selected_members=(),
            required_symbols={},
            retained_waypoint_symbols={},
            unexpected_symbols=(),
        )

    archive = psdk_root / library_rel
    if archive.is_symlink() or not archive.is_file():
        return ArchiveAudit(
            status="UNAVAILABLE",
            reason_codes=("PINNED_ARCHIVE_MISSING_OR_SYMLINK",),
            sdk_version=sdk_version,
            archive_sha256=None,
            selected_members=(),
            required_symbols={},
            retained_waypoint_symbols={},
            unexpected_symbols=(),
        )
    actual_sha256 = _sha256(archive)
    if actual_sha256 != expected_sha256:
        return ArchiveAudit(
            status="UNAVAILABLE",
            reason_codes=("PINNED_ARCHIVE_SHA256_MISMATCH",),
            sdk_version=sdk_version,
            archive_sha256=actual_sha256,
            selected_members=(),
            required_symbols={},
            retained_waypoint_symbols={},
            unexpected_symbols=(),
        )

    completed = subprocess.run(
        [nm_tool, "-A", "--defined-only", str(archive)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return ArchiveAudit(
            status="UNAVAILABLE",
            reason_codes=("NM_FAILED",),
            sdk_version=sdk_version,
            archive_sha256=actual_sha256,
            selected_members=(),
            required_symbols={},
            retained_waypoint_symbols={},
            unexpected_symbols=(),
        )

    locations = parse_nm_locations(completed.stdout)
    required_locations = {symbol: locations.get(symbol, ()) for symbol in sorted(_REQUIRED_SYMBOLS)}
    missing = tuple(symbol for symbol, items in required_locations.items() if not items)
    if missing:
        return ArchiveAudit(
            status="UNAVAILABLE",
            reason_codes=tuple(f"REQUIRED_SYMBOL_MISSING:{symbol}" for symbol in missing),
            sdk_version=sdk_version,
            archive_sha256=actual_sha256,
            selected_members=(),
            required_symbols=required_locations,
            retained_waypoint_symbols={},
            unexpected_symbols=(),
        )

    selected_members = tuple(
        sorted({item.member for items in required_locations.values() for item in items})
    )
    retained = {
        symbol: tuple(item for item in items if item.member in selected_members)
        for symbol, items in locations.items()
        if any(item.member in selected_members for item in items)
    }
    unexpected = tuple(sorted(set(retained) - _REQUIRED_SYMBOLS))
    reasons: list[str] = []
    if _FORBIDDEN_SYMBOL in unexpected:
        reasons.append("ACTION_COLOCATED_WITH_UPLOAD")
    if unexpected:
        reasons.append("UNEXPECTED_WAYPOINT_SYMBOLS_IN_SELECTED_MEMBER")
    status = "BLOCKED" if reasons else "READY"
    return ArchiveAudit(
        status=status,
        reason_codes=tuple(reasons),
        sdk_version=sdk_version,
        archive_sha256=actual_sha256,
        selected_members=selected_members,
        required_symbols=required_locations,
        retained_waypoint_symbols=retained,
        unexpected_symbols=unexpected,
    )


def _json_payload(audit: ArchiveAudit) -> str:
    return json.dumps(asdict(audit), sort_keys=True, separators=(",", ":"))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parents[2]
    parser.add_argument(
        "--lock",
        type=Path,
        default=repo_root / "edge" / "third_party" / "PSDK_LOCK.yaml",
    )
    parser.add_argument(
        "--psdk-root",
        type=Path,
        default=repo_root / "edge" / "third_party" / "psdk",
    )
    parser.add_argument("--nm", default="nm")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args(argv)
    audit = audit_archive(lock_path=args.lock, psdk_root=args.psdk_root, nm_tool=args.nm)
    if args.format == "json":
        print(_json_payload(audit))
    else:
        print(f"status={audit.status} sdk={audit.sdk_version or 'unknown'}")
        for reason in audit.reason_codes:
            print(f"reason={reason}")
        print(f"selected_members={','.join(audit.selected_members) or '-'}")
        print(f"unexpected_symbols={','.join(audit.unexpected_symbols) or '-'}")
    if audit.status == "READY":
        return 0
    if audit.status == "BLOCKED":
        return 2
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
