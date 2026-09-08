"""Attempt-scoped local workspace ownership for every controller work kind."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ksi_processing_controller.core_client import LeaseHandle


class UnsafeWorkspaceError(RuntimeError):
    """A local workspace path is existing, linked, or otherwise not exclusive."""


def attempt_workspace(work_root: Path, handle: LeaseHandle) -> Path:
    """Create the only writable path for a fenced processing attempt.

    Layout is exactly ``<work_root>/<work_kind>/<job_id>/<worker_instance_id>/
    <lease_generation>/``.  The generation leaf must be new and is mode 0700;
    a pre-existing or symlinked leaf is never reused.  This makes stale
    attempts and concurrent worker processes unable to write one another's
    ``all.zip`` (or any other temporary name).
    """
    root = work_root.resolve(strict=False)
    if work_root.is_symlink() or (work_root.exists() and not work_root.is_dir()):
        raise UnsafeWorkspaceError(f"unsafe work root: {work_root}")
    parent = root / handle.work_kind / handle.resource_id / handle.worker_instance_id
    # Identifiers originate in Core and are header/UUID validated, but still
    # keep the path construction defensive for a malformed fake/test client.
    if any(part in {"", ".", ".."} or "/" in part for part in (
        handle.work_kind, handle.resource_id, handle.worker_instance_id,
    )):
        raise UnsafeWorkspaceError("unsafe workspace identity component")
    candidates = (
        root,
        root / handle.work_kind,
        root / handle.work_kind / handle.resource_id,
        parent,
    )
    for candidate in candidates:
        if candidate.is_symlink():
            raise UnsafeWorkspaceError(f"symlinked workspace component: {candidate}")
    parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not parent.is_dir() or parent.is_symlink():
        raise UnsafeWorkspaceError(f"unsafe workspace parent: {parent}")
    leaf = parent / str(handle.lease_generation)
    try:
        leaf.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise UnsafeWorkspaceError(f"attempt workspace already exists: {leaf}") from exc
    os.chmod(leaf, 0o700)
    return leaf


def cleanup_attempt_workspace(work_root: Path, attempt_dir: Path) -> None:
    """Remove only this attempt and then harmless empty namespace parents."""
    root = work_root.resolve(strict=False)
    try:
        attempt_dir.relative_to(root)
    except ValueError as exc:
        raise UnsafeWorkspaceError(f"attempt escapes work root: {attempt_dir}") from exc
    if attempt_dir.is_symlink():
        raise UnsafeWorkspaceError(f"refusing to clean symlink: {attempt_dir}")
    shutil.rmtree(attempt_dir, ignore_errors=False)
    # Do not recursively delete a shared root: only remove empty namespace
    # components belonging to this completed attempt.
    current = attempt_dir.parent
    while current != root:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def unleased_workspace(work_root: Path, *, work_kind: str, resource_id: str) -> Path:
    """Safe namespace for read/observe workers that deliberately have no lease."""
    from uuid import uuid4

    return attempt_workspace(
        work_root,
        LeaseHandle(
            work_kind=work_kind,
            resource_id=resource_id,
            worker_instance_id=str(uuid4()),
            lease_acquisition_id=str(uuid4()),
            lease_generation=1,
        ),
    )


def lease_or_compat_handle(
    value: LeaseHandle | None, *, work_kind: str, resource_id: str
) -> LeaseHandle:
    """Keep pre-fencing in-process test doubles usable during migration only."""
    if isinstance(value, LeaseHandle):
        return value
    from uuid import uuid4

    return LeaseHandle(
        work_kind=work_kind,
        resource_id=resource_id,
        worker_instance_id=str(uuid4()),
        lease_acquisition_id=str(uuid4()),
        lease_generation=1,
    )


__all__ = [
    "UnsafeWorkspaceError",
    "attempt_workspace",
    "cleanup_attempt_workspace",
    "lease_or_compat_handle",
    "unleased_workspace",
]
