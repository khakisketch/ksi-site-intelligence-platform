#!/usr/bin/env python3
"""Validate supplied candidate credentials before preparing empty data directories.

No secret or signing key is generated, replaced, reowned, or repaired here.
Missing operator provisioning is a startup failure, not permission to bootstrap.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from pathlib import Path

# P3 Task 5: Mission signing retired to archive/acquisition-2026/ — the platform
# profile never reads signing keys, so this validator keeps only the manifest
# shape/file checks below; cryptographic key verification retired with the
# archived ksi_core.signing_keys module (T6 dispositions this tool).

RUNTIME_UID = 10001
RUNTIME_GID = 10001
STATE_ROOTS = (
    Path("/state/data"),
    Path("/state/identity"),
)


def _runtime_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, RUNTIME_UID, RUNTIME_GID)
    path.chmod(0o700)


def _runtime_can_access(node: os.stat_result, owner_bit: int) -> bool:
    if node.st_uid == RUNTIME_UID:
        return bool(node.st_mode & owner_bit)
    if node.st_gid == RUNTIME_GID:
        return bool(node.st_mode & (owner_bit >> 3))
    return bool(node.st_mode & (owner_bit >> 6))


def _open_parent(path: Path) -> int:
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe path")
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parent.parts[1:]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
            node = os.fstat(descriptor)
            if (
                not _runtime_can_access(node, stat.S_IXUSR)
                or node.st_uid not in {0, RUNTIME_UID}
                or (node.st_mode & 0o022 and not node.st_mode & stat.S_ISVTX)
            ):
                raise ValueError("runtime cannot traverse protected credential directory")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _supplied_file(path: Path, *, private: bool) -> bytes:
    try:
        parent = _open_parent(path)
        try:
            descriptor = os.open(
                path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
            )
        finally:
            os.close(parent)
        try:
            node = os.fstat(descriptor)
            if (
                not stat.S_ISREG(node.st_mode)
                or node.st_nlink != 1
                or node.st_uid not in ({RUNTIME_UID} if private else {0, RUNTIME_UID})
                or not _runtime_can_access(node, stat.S_IRUSR)
                or node.st_mode & (0o077 if private else 0o022)
                or not 0 < node.st_size <= 16_384
            ):
                raise ValueError("unsafe credential file")
            raw = os.read(descriptor, 16_385)
            after = os.fstat(descriptor)
            if len(raw) != node.st_size or (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns
            ) != (node.st_size, node.st_mtime_ns, node.st_ctime_ns):
                raise ValueError("credential changed during validation")
            return raw
        finally:
            os.close(descriptor)
    except (OSError, ValueError) as exc:
        raise RuntimeError("candidate requires pre-provisioned protected credential files") from exc


def _secret(path: Path) -> None:
    raw = _supplied_file(path, private=True)
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise RuntimeError("candidate credential must be UTF-8") from exc
    if len(text) < 32 or "\x00" in text:
        raise RuntimeError("candidate credential is empty or malformed")


def _signing_key_set(path: Path) -> None:
    try:
        snapshot = {"keys.json": _supplied_file(path / "keys.json", private=False)}
        manifest = json.loads(snapshot["keys.json"])
        active = manifest["active"]
        keys = manifest["keys"]
        if not isinstance(keys, list) or not keys:
            raise ValueError("missing keys")
        for entry in keys:
            key_id = entry["keyId"]
            if (
                not isinstance(key_id, str)
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", key_id) is None
            ):
                raise ValueError("invalid key identity")
            public_name = f"{key_id}.public.pem"
            snapshot[public_name] = _supplied_file(path / public_name, private=False)
            if key_id == active:
                private_name = f"{key_id}.private.pem"
                snapshot[private_name] = _supplied_file(path / private_name, private=True)
        # P3 Task 5: cryptographic key verification retired with archived
        # ksi_core.signing_keys (platform never reads signing keys) — manifest
        # shape/file checks above stay; the non-mutation re-read below stays.
        for name, raw in snapshot.items():
            if _supplied_file(path / name, private=name.endswith(".private.pem")) != raw:
                raise ValueError("credential changed during semantic validation")
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "candidate signing key set is missing or invalid; refusing bootstrap"
        ) from exc


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    _secret(Path("/state/secrets/dashboard-session.secret"))
    _secret(Path("/state/secrets/oidc-client.secret"))
    _signing_key_set(Path("/state/signing"))
    if args.validate_only:
        print("external reconstruction candidate supplied credentials verified (read-only)")
        return
    for path in STATE_ROOTS:
        _runtime_directory(path)
    print("external reconstruction candidate supplied credentials verified")


if __name__ == "__main__":
    main()
