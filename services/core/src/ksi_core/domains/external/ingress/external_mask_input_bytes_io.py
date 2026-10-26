"""Minimal private filesystem helpers for mask-child byte storage (P2, additive).

Server-keyed objects only: every path is derived by Core from organization,
site, child, and artifact identifiers (never a caller path), and every open
uses ``O_NOFOLLOW`` with descriptor-relative traversal from a pinned root,
so a symlink planted between a check and an open cannot redirect the byte
binding.  The store root itself is pinned by walking every ancestor from
``/`` with ``O_NOFOLLOW``: an ancestor symlink, an unowned ancestor, or a
group/other-writable ancestor gap (outside a sticky parent holding an
owner child) fails closed at pin time, as does a non-exact-``0700`` or
foreign-owned root.  No existing shared module is modified or widened; these
helpers belong to the mask lane.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import stat
from pathlib import Path

_SAFE_COMPONENT_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
)


def check_safe_component(value: str, description: str) -> str:
    """Reject URLs, paths, escapes, and non-identifier characters."""
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValueError(f"{description} is not a safe object-key component")
    if (
        any(char not in _SAFE_COMPONENT_CHARS for char in value)
        or value in {".", ".."}
        or value.startswith(("/", "\\"))
        or ".." in value
        or "\\" in value
        or "\n" in value
        or "\r" in value
        or "://" in value
    ):
        raise ValueError(f"{description} must be an opaque identifier, never a path or URL")
    lowered = value.lower()
    if lowered.startswith(("http:", "https:", "s3:", "file:", "cap:")):
        raise ValueError(f"{description} must be an opaque identifier, never a path or URL")
    return value


def pin_owner_private_root(root: Path) -> int:
    """Pin an owner-private 0700 store root against ancestor substitution.

    Equivalent in force to the proven delivery-layer root pin: ``root`` must
    be absolute and free of ``..``; every ancestor from ``/`` is opened with
    ``O_NOFOLLOW`` and must be owned by root-or-euid without group/other
    writable gaps (unless the parent is sticky and the child is euid-owned);
    the leaf itself must be an exact-``0700`` directory owned by euid.
    Returns the pinned open directory descriptor; the caller owns its
    lifetime (close is idempotent via :func:`os.close` + ``EBADF`` tolerance
    at the call site).
    """
    if not isinstance(root, Path) or not root.is_absolute():
        raise ValueError("mask store root must be an absolute path")
    if ".." in root.parts or "." in root.parts[1:]:
        raise ValueError("mask store root must not contain dot segments")
    if len(root.parts) < 2:
        raise ValueError("mask store root must not be the filesystem root")
    descriptors: list[int] = []
    try:
        current = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as exc:
        raise ValueError(f"cannot pin mask store root: {exc}") from exc
    descriptors.append(current)
    try:
        for part in root.parts[1:]:
            previous = os.fstat(current)
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=current,
                )
            except OSError as exc:
                raise ValueError(f"cannot pin mask store root: {exc}") from exc
            descriptors.append(child)
            entry = os.fstat(child)
            if entry.st_uid not in (0, os.geteuid()) or (
                previous.st_mode & 0o022
                and not (previous.st_mode & stat.S_ISVTX and entry.st_uid == os.geteuid())
            ):
                raise ValueError("substitutable mask store ancestor")
            current = child
        leaf = os.fstat(current)
        if (
            not stat.S_ISDIR(leaf.st_mode)
            or stat.S_IMODE(leaf.st_mode) != 0o700
            or leaf.st_uid != os.geteuid()
        ):
            raise ValueError("mask store root must be an owner-private 0700 directory")
        descriptors.remove(current)
        for descriptor in descriptors:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        return current
    except BaseException:
        for descriptor in descriptors:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        raise


def ensure_private_dir(path: Path) -> None:
    """Create a 0700 directory or fail when an existing one is not exactly 0700.

    Kept for test-only setup of scratch roots; the store itself pins via
    :func:`pin_owner_private_root`.
    """
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise ValueError("mask store root is unavailable") from exc
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(file_stat.st_mode) or stat.S_IMODE(file_stat.st_mode) != 0o700:
            raise ValueError("mask store root must be a private 0700 directory")
    finally:
        os.close(descriptor)


def _open_subdir(parent_fd: int, name: str) -> int:
    try:
        return os.open(
            name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd
        )
    except OSError as exc:
        raise ValueError("mask object directory is unavailable") from exc


def _require_owned_private_dir(descriptor: int, description: str) -> None:
    try:
        file_stat = os.fstat(descriptor)
    except OSError as exc:
        raise ValueError(f"mask {description} is unavailable") from exc
    if (
        not stat.S_ISDIR(file_stat.st_mode)
        or stat.S_IMODE(file_stat.st_mode) != 0o700
        or file_stat.st_uid != os.geteuid()
    ):
        raise ValueError(f"mask {description} must be an owner-private 0700 directory")


def mkdirs_below(root_fd: int, parts: tuple[str, ...]) -> int:
    """Create nested 0700 euid-owned directories below an open root; returns the leaf fd.

    The caller owns the returned descriptor.  Each component is already
    validated by :func:`check_safe_component` at key construction.  A
    pre-existing component with the wrong mode, owner, or file type fails
    closed instead of being adopted.
    """
    current = os.dup(root_fd)
    try:
        for part in parts:
            try:
                os.mkdir(part, 0o700, dir_fd=current)
            except FileExistsError:
                pass
            except OSError as exc:
                raise ValueError("mask object directory is unavailable") from exc
            child = _open_subdir(current, part)
            os.close(current)
            current = child
            _require_owned_private_dir(current, "object directory")
        return current
    except BaseException:
        os.close(current)
        raise


def open_dirs_below(root_fd: int, parts: tuple[str, ...]) -> int:
    """Walk nested directories without creating anything; returns the leaf fd.

    The caller owns the returned descriptor.  Any missing component, symlink,
    non-directory, or wrongly owned/moded directory fails closed instead of
    materializing store layout.
    """
    current = os.dup(root_fd)
    try:
        for part in parts:
            child = _open_subdir(current, part)
            os.close(current)
            current = child
            _require_owned_private_dir(current, "object directory")
        return current
    except BaseException:
        os.close(current)
        raise


def open_for_create(dir_fd: int, name: str) -> int:
    """Open a new regular file exclusively; never follow, never truncate."""
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=dir_fd,
        )
    except FileExistsError as exc:
        raise FileExistsError("mask staging object already exists") from exc
    except OSError as exc:
        raise ValueError("mask staging object is unavailable") from exc
    try:
        file_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_nlink != 1
            or stat.S_IMODE(file_stat.st_mode) != 0o600
            or file_stat.st_uid != os.geteuid()
        ):
            raise ValueError("mask staging object is not a private regular file")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def open_for_read(dir_fd: int, name: str) -> int:
    """Open an existing regular file without following symlinks."""
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=dir_fd)
    except OSError as exc:
        raise ValueError("mask sealed object is unavailable") from exc
    try:
        file_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_nlink != 1
            or stat.S_IMODE(file_stat.st_mode) != 0o600
            or file_stat.st_uid != os.geteuid()
        ):
            raise ValueError("mask sealed object is not a private single-link regular file")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def write_all(descriptor: int, data: bytes, *, maximum: int) -> int:
    """Write every byte with fsync; fail closed on short writes or cap breach."""
    if len(data) > maximum:
        raise ValueError("mask bytes exceed the finite byte cap")
    view = memoryview(data)
    written = 0
    while written < len(data):
        try:
            count = os.write(descriptor, view[written:])
        except OSError as exc:
            raise ValueError("mask byte write failed") from exc
        if count <= 0:
            raise ValueError("mask byte write made no progress")
        written += count
    try:
        os.fsync(descriptor)
    except OSError as exc:
        raise ValueError("mask byte fsync failed") from exc
    return written


def hash_fd(descriptor: int, *, maximum: int) -> tuple[str, int]:
    """Hash a descriptor with pread (no offset races); cap the stream."""
    digest = hashlib.sha256()
    total = 0
    offset = 0
    while True:
        try:
            chunk = os.pread(descriptor, 1024 * 1024, offset)
        except OSError as exc:
            raise ValueError("mask byte hash read failed") from exc
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise ValueError("mask bytes exceed the finite byte cap")
        digest.update(chunk)
        offset += len(chunk)
    return "sha256:" + digest.hexdigest(), total


__all__ = [
    "check_safe_component",
    "ensure_private_dir",
    "hash_fd",
    "mkdirs_below",
    "open_dirs_below",
    "open_for_create",
    "open_for_read",
    "pin_owner_private_root",
    "write_all",
]
