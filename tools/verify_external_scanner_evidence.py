#!/usr/bin/env python3
"""Validate exact runtime scanner bytes; never issue security or execution authority.

Native Grype support is a reviewed format profile, not a synthesized scanner
envelope. Database paths/URLs and producer configuration are never dereferenced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_BYTES = 16 * 1024 * 1024


class ScannerEvidenceError(ValueError):
    """Only a safe reason code is exposed, never scanner configuration/content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("SCANNER_EVIDENCE_BLOCKED: " + code)


def _identity(node: os.stat_result) -> tuple[int, ...]:
    return (node.st_dev, node.st_ino, node.st_size, node.st_mtime_ns, node.st_ctime_ns)


def _open_parent(path: Path) -> int:
    if not path.is_absolute() or ".." in path.parts or not path.name:
        raise ScannerEvidenceError("INPUT_PATH")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(path.anchor, flags)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_bound_payload(path: Path, sha256: str, size: int) -> bytes:
    parent_fd: int | None = None
    fd: int | None = None
    try:
        parent_fd = _open_parent(path)
        fd = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            dir_fd=parent_fd,
        )
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= _MAX_BYTES:
            raise ScannerEvidenceError("INPUT_FILE")
        if before.st_size != size:
            raise ScannerEvidenceError("INPUT_SIZE")
        chunks = []
        remaining = size
        while remaining:
            chunk = os.read(fd, min(remaining, 1024 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(fd)
        named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            len(payload) != size
            or _identity(before) != _identity(after)
            or not stat.S_ISREG(named.st_mode)
            or _identity(named) != _identity(after)
        ):
            raise ScannerEvidenceError("INPUT_CHANGED")
        if "sha256:" + hashlib.sha256(payload).hexdigest() != sha256:
            raise ScannerEvidenceError("INPUT_HASH")
        return payload
    except OSError as error:
        raise ScannerEvidenceError("INPUT_FILE") from error
    finally:
        if fd is not None:
            os.close(fd)
        if parent_fd is not None:
            os.close(parent_fd)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScannerEvidenceError("JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ScannerEvidenceError("JSON_NONFINITE")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ScannerEvidenceError("JSON_NONFINITE")
    return result


def _text(value: object) -> bool:
    return isinstance(value, str) and len(value) > 0


def _native_profile(value: dict[str, Any], image_id: str | None) -> str:
    descriptor = value.get("descriptor")
    source = value.get("source")
    matches = value.get("matches")
    if not isinstance(descriptor, dict) or not isinstance(source, dict):
        raise ScannerEvidenceError("NATIVE_PROFILE")
    db = descriptor.get("db")
    if not isinstance(db, dict):
        raise ScannerEvidenceError("NATIVE_PROFILE")
    status = db.get("status")
    if (
        descriptor.get("name") != "grype"
        or descriptor.get("version") != "0.120.0"
        or not _text(descriptor.get("timestamp"))
        or not isinstance(descriptor.get("configuration"), dict)
        or not isinstance(status, dict)
        or status.get("valid") is not True
        or status.get("schemaVersion") != "v6.1.10"
        or not _text(status.get("built"))
        or not isinstance(db.get("providers"), dict)
    ):
        raise ScannerEvidenceError("NATIVE_PROFILE")
    target = source.get("target")
    if (
        source.get("type") != "image"
        or not isinstance(target, dict)
        or image_id is None
        or target.get("imageID") != image_id
    ):
        raise ScannerEvidenceError("NATIVE_IMAGE")
    if not isinstance(matches, list):
        raise ScannerEvidenceError("NATIVE_MATCHES")
    for match in matches:
        if not isinstance(match, dict):
            raise ScannerEvidenceError("NATIVE_MATCHES")
        vulnerability = match.get("vulnerability")
        artifact = match.get("artifact")
        if (
            not isinstance(vulnerability, dict)
            or not isinstance(artifact, dict)
            or not _text(vulnerability.get("id"))
            or not _text(vulnerability.get("severity"))
            or not _text(artifact.get("name"))
            or not _text(artifact.get("version"))
        ):
            raise ScannerEvidenceError("NATIVE_MATCHES")
    if "ignoredMatches" in value and not isinstance(value["ignoredMatches"], list):
        raise ScannerEvidenceError("NATIVE_MATCHES")
    return "grype-0.120.0"


def verify_scanner_evidence(
    path: Path, *, expected_sha256: str, expected_bytes: int, expected_image_id: str | None,
) -> str:
    """Validate one raw payload; the return value is a format, not an approval."""
    if (
        not isinstance(expected_sha256, str)
        or _DIGEST.fullmatch(expected_sha256) is None
        or type(expected_bytes) is not int
        or not 0 < expected_bytes <= _MAX_BYTES
        or (
            expected_image_id is not None
            and (
                not isinstance(expected_image_id, str)
                or _DIGEST.fullmatch(expected_image_id) is None
            )
        )
    ):
        raise ScannerEvidenceError("EXPECTED_BINDING")
    payload = _read_bound_payload(path, expected_sha256, expected_bytes)
    try:
        value = json.loads(
            payload.decode("utf-8"), object_pairs_hook=_unique_object,
            parse_constant=_reject_constant, parse_float=_finite_float,
        )
    except ScannerEvidenceError:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        raise ScannerEvidenceError("JSON_SYNTAX") from error
    if not isinstance(value, dict):
        raise ScannerEvidenceError("JSON_ROOT")
    source = value.get("source")
    # Legacy envelopes may carry unrelated source annotations. Grype's
    # descriptor or structured source fields identify the native family;
    # malformed native candidates still cannot fall back to legacy.
    native = "descriptor" in value or (
        isinstance(source, dict) and ("type" in source or "target" in source)
    )
    if native:
        if "scanner" in value:
            raise ScannerEvidenceError("AMBIGUOUS_FORMAT")
        return _native_profile(value, expected_image_id)
    scanner = value.get("scanner")
    if not isinstance(scanner, dict) or not all(
        _text(scanner.get(key)) for key in ("name", "schemaVersion")
    ):
        raise ScannerEvidenceError("LEGACY_PROFILE")
    return "legacy"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--bytes", type=int, required=True)
    parser.add_argument("--image-id")
    args = parser.parse_args(argv)
    try:
        profile = verify_scanner_evidence(
            args.path, expected_sha256=args.sha256, expected_bytes=args.bytes,
            expected_image_id=args.image_id,
        )
    except ScannerEvidenceError as error:
        print(str(error), file=sys.stderr)
        return 1
    print("SCANNER_EVIDENCE_VALIDATED: " + profile + "; no security or execution approval")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
