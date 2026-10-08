#!/usr/bin/env python3
"""Reject flight and camera-write surfaces from the candidate MSDK Field Bridge."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

_SOURCE_SUFFIXES = {".kt", ".java"}
_FORBIDDEN = {
    "virtual-stick": re.compile(r"\bVirtualStick[A-Za-z0-9_]*\b"),
    "takeoff": re.compile(r"\b(?:startTakeOff|startTakeoff|KeyStartTakeoff)\b"),
    "landing": re.compile(r"\b(?:startLanding|KeyStartLanding)\b"),
    "rth": re.compile(r"\b(?:startGoHome|KeyStartGoHome|GoHomeAction)\b"),
    "waypoint-action": re.compile(r"\b(?:WaypointMission|WaypointAction|WaypointExecute)\w*\b"),
    "gimbal-write": re.compile(r"\b(?:GimbalAngle|GimbalRotate|setGimbal)\w*\b"),
    "capture-write": re.compile(r"\b(?:startShootPhoto|startRecordVideo|CameraModeKey)\b"),
    "media-delete": re.compile(r"\b(?:deleteMedia|deleteFile|formatStorage)\w*\b"),
}


def scan(root: Path) -> tuple[str, ...]:
    if not root.is_dir():
        return (f"{root}: MSDK bridge source root가 없다",)
    violations: list[str] = []
    sources = sorted(path for path in root.rglob("*") if path.suffix in _SOURCE_SUFFIXES)
    if not sources:
        return (f"{root}: 검사할 Kotlin/Java source가 없다",)
    for path in sources:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append(f"{path}: source를 읽을 수 없다: {exc}")
            continue
        for label, pattern in _FORBIDDEN.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                violations.append(f"{path}:{line}: forbidden {label} surface {match.group(0)}")
    return tuple(violations)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        type=Path,
        nargs="?",
        default=Path("edge/msdk-field-bridge"),
    )
    args = parser.parse_args(argv)
    violations = scan(args.root)
    if violations:
        for violation in violations:
            print(f"✗ {violation}")
        return 1
    print("✓ MSDK Field Bridge contains no flight or camera-write surface")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
