"""Bounded, no-follow, identity-pinned reads of immutable operator artifacts."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from threading import RLock


class OperatorArtifactUnavailable(ValueError):
    """A fixed artifact is unsafe, replaced, oversized, or unavailable."""


class BoundedOperatorArtifact:
    """Share this instance from preflight through runtime; no mutable path fallback."""

    def __init__(self, path: Path, *, maximum_bytes: int) -> None:
        if not path.is_absolute() or ".." in path.parts or maximum_bytes <= 0:
            raise ValueError("fixed absolute artifact path and positive bound required")
        self._path = path
        self._maximum_bytes = maximum_bytes
        self._identity: tuple[int | str, ...] | None = None
        self._lock = RLock()

    def read(self) -> bytes:
        with self._lock:
            try:
                descriptor = self._open_no_follow()
                try:
                    before = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or before.st_uid not in {0, os.geteuid()}
                        or before.st_mode & 0o7133
                        or before.st_nlink != 1
                        or before.st_size > self._maximum_bytes
                    ):
                        raise OperatorArtifactUnavailable("operator artifact node rejected")
                    parts: list[bytes] = []
                    total = 0
                    while total <= self._maximum_bytes:
                        chunk = os.read(descriptor, min(65536, self._maximum_bytes + 1 - total))
                        if not chunk:
                            break
                        parts.append(chunk)
                        total += len(chunk)
                    contents = b"".join(parts)
                    after = os.fstat(descriptor)
                    # Reopen every parent without following symlinks as well as the leaf.
                    current_fd = self._open_no_follow()
                    try:
                        current = os.fstat(current_fd)
                    finally:
                        os.close(current_fd)
                    if (
                        total > self._maximum_bytes
                        or total != before.st_size
                        or _node_identity(before) != _node_identity(after)
                        or _node_identity(before) != _node_identity(current)
                    ):
                        raise OperatorArtifactUnavailable("operator artifact changed while read")
                    identity: tuple[int | str, ...] = (
                        *_node_identity(before),
                        hashlib.sha256(contents).hexdigest(),
                    )
                    if self._identity is not None and identity != self._identity:
                        raise OperatorArtifactUnavailable(
                            "operator artifact replaced after preflight"
                        )
                    self._identity = identity
                    return contents
                finally:
                    os.close(descriptor)
            except OSError as exc:
                raise OperatorArtifactUnavailable("operator artifact unavailable") from exc

    def _open_no_follow(self) -> int:
        parent = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in self._path.parts[1:-1]:
                child = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=parent,
                )
                os.close(parent)
                parent = child
            return os.open(
                self._path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=parent,
            )
        finally:
            os.close(parent)


def _node_identity(node: os.stat_result) -> tuple[int, ...]:
    return (
        node.st_dev,
        node.st_ino,
        node.st_uid,
        node.st_gid,
        node.st_mode,
        node.st_nlink,
        node.st_size,
        node.st_mtime_ns,
        node.st_ctime_ns,
    )
