"""Private, inode-bound sealed input staging for the inspector launcher.

The implementation deliberately has no UID arithmetic, chown fallback, or
world/group permission fallback.  A caller must supply a current mapping and a
port that both grants and verifies the exact named-reader ACL.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
import threading
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ksi_processing_controller.external_inspector_attempts import (
    PrivateStagingRootV1,
    StagingAllocationPlanV1,
    StagingAllocationReceiptV1,
    StagingFileIdentityV1,
)


class InspectorStagingUnavailable(RuntimeError):
    """Identity, mapping, ACL, or private-filesystem state failed closed."""


class SealedByteIdentityMismatch(ValueError):
    """The streamed bytes do not equal the Core-observed sealed byte binding."""


class RegisteredStagingRecoveryDispositionV1(StrEnum):
    """Recovery either removes only proven owned nodes or retains every uncertain node."""

    CLEANED = "CLEANED"
    OWNERSHIP_UNCERTAIN = "OWNERSHIP_UNCERTAIN"


@dataclass(frozen=True, slots=True)
class MappedInspectorReaderV1:
    container_uid: int
    container_gid: int
    host_uid: int
    host_gid: int
    mapping_witness: str

    def __post_init__(self) -> None:
        identity_values = (
            self.container_uid,
            self.container_gid,
            self.host_uid,
            self.host_gid,
        )
        if any(type(value) is not int or value < 0 for value in identity_values):
            raise ValueError("reader UID/GID mapping values must be non-negative integers")
        if not isinstance(self.mapping_witness, str) or not self.mapping_witness:
            raise ValueError("reader mapping witness is required")


@dataclass(frozen=True, slots=True)
class InspectorReadOnlyBindV1:
    """A live, borrowed input capability; it cannot be used after owner cleanup."""

    source: InspectorBorrowedSourcePort
    target_path: str
    read_only: bool
    observed_sha256: str
    observed_size_bytes: int
    source_device: int
    source_inode: int
    source_owner_uid: int
    source_owner_gid: int
    source_link_count: int
    reader_mapping_witness: str


class InspectorBorrowedSourcePort(Protocol):
    """Opaque access to the retained inode for the duration of one backend call."""

    def read_at(self, *, offset: int, maximum_bytes: int) -> bytes: ...

    def consume_fd(self, consumer: Callable[[int], object]) -> object: ...


class ReaderMappingPort(Protocol):
    def resolve_exact(
        self,
        *,
        runtime_uid: int,
        runtime_gid: int,
        supplementary_groups: tuple[int, ...],
        deadline_monotonic: float,
    ) -> MappedInspectorReaderV1 | None: ...


class NamedReaderAclPort(Protocol):
    def grant_exact(
        self,
        *,
        source_fd: int,
        traversal_fds: tuple[int, int],
        reader: MappedInspectorReaderV1,
        deadline_monotonic: float,
    ) -> bool: ...

    def verifies_exact(
        self,
        *,
        source_fd: int,
        traversal_fds: tuple[int, int],
        reader: MappedInspectorReaderV1,
        deadline_monotonic: float,
    ) -> bool: ...

    def revoke_exact(
        self,
        *,
        source_fd: int,
        traversal_fds: tuple[int, int],
        reader: MappedInspectorReaderV1,
        deadline_monotonic: float,
    ) -> bool: ...

    def verifies_private_directory(self, *, directory_fd: int) -> bool: ...

    def retire_private_directory(self, *, directory_fd: int) -> bool: ...

    def grant_leaf_exact(
        self,
        *,
        source_fd: int,
        attempt_fd: int,
        reader: MappedInspectorReaderV1,
        deadline_monotonic: float,
    ) -> bool: ...

    def revoke_leaf_exact(
        self,
        *,
        source_fd: int,
        attempt_fd: int,
        reader: MappedInspectorReaderV1,
        deadline_monotonic: float,
    ) -> bool: ...

    def retire_recovered_leaf_acl(
        self,
        *,
        source_fd: int,
        attempt_fd: int,
    ) -> bool: ...


class InputStagingPort(Protocol):
    def begin(
        self,
        *,
        maximum_bytes: int,
        deadline_monotonic: float,
    ) -> MutableInspectorInputPort: ...


class RegisteredInputStagingPort(InputStagingPort, Protocol):
    """Task 4A path: a journaled plan is the only source of allocation names."""

    def private_root_identity(self) -> PrivateStagingRootV1: ...

    def begin_registered(
        self,
        *,
        plan: StagingAllocationPlanV1,
        maximum_bytes: int,
        deadline_monotonic: float,
    ) -> tuple[MutableInspectorInputPort, StagingAllocationReceiptV1]: ...

    def finalize_registered_cleanup(
        self,
        *,
        plan: StagingAllocationPlanV1,
        receipt: StagingAllocationReceiptV1,
    ) -> None: ...


class MutableInspectorInputPort(Protocol):
    def write(self, chunk: bytes) -> None: ...

    def seal_for_reader(
        self,
        *,
        expected_sha256: str,
        expected_size_bytes: int,
        reader: MappedInspectorReaderV1,
        supplementary_groups: tuple[int, ...],
        deadline_monotonic: float,
    ) -> InspectorSealedInputPort: ...

    def abort(self) -> None: ...

    def relinquish_for_recovery(self) -> None:
        """Close owned descriptors while preserving recorded paths for journal recovery."""


class InspectorSealedInputPort(Protocol):
    def prepare_read_only_bind(self, *, deadline_monotonic: float) -> InspectorReadOnlyBindV1: ...

    def abort(self) -> None: ...

    def relinquish_for_recovery(self) -> None:
        """Close owned descriptors while preserving recorded paths for journal recovery."""


@dataclass(frozen=True, slots=True)
class _Identity:
    device: int
    inode: int
    mode: int
    owner_uid: int
    owner_gid: int
    link_count: int
    size: int

    @classmethod
    def from_stat(cls, value: os.stat_result) -> _Identity:
        return cls(
            device=value.st_dev,
            inode=value.st_ino,
            mode=value.st_mode,
            owner_uid=value.st_uid,
            owner_gid=value.st_gid,
            link_count=value.st_nlink,
            size=value.st_size,
        )


@dataclass(slots=True)
class _RootReaderLease:
    reader: MappedInspectorReaderV1
    count: int


class _RootReaderLeaseRegistry:
    """Process-local ownership of one shared root traversal ACL per reader.

    Each sealed attempt receives distinct file and attempt-directory ACLs.  A
    root grant is shared only when the full signed reader mapping is identical,
    and it is reset only by the last live lease.  Startup recovery begins
    before admission, so it uses its separate exact recovery retirement path.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._leases: dict[tuple[int, int], _RootReaderLease] = {}

    def grant(
        self,
        *,
        source_fd: int,
        root_fd: int,
        attempt_fd: int,
        reader: MappedInspectorReaderV1,
        acl: NamedReaderAclPort,
        deadline_monotonic: float,
    ) -> bool:
        key = _root_lease_key(root_fd)
        with self._lock:
            existing = self._leases.get(key)
            if existing is None:
                if not acl.grant_exact(
                    source_fd=source_fd,
                    traversal_fds=(root_fd, attempt_fd),
                    reader=reader,
                    deadline_monotonic=deadline_monotonic,
                ):
                    return False
                self._leases[key] = _RootReaderLease(reader=reader, count=1)
                return True
            if existing.reader != reader:
                return False
            if not acl.grant_leaf_exact(
                source_fd=source_fd,
                attempt_fd=attempt_fd,
                reader=reader,
                deadline_monotonic=deadline_monotonic,
            ):
                return False
            existing.count += 1
            return True

    def revoke(
        self,
        *,
        source_fd: int,
        root_fd: int,
        attempt_fd: int,
        reader: MappedInspectorReaderV1,
        acl: NamedReaderAclPort,
        deadline_monotonic: float,
    ) -> bool:
        key = _root_lease_key(root_fd)
        with self._lock:
            existing = self._leases.get(key)
            if existing is None or existing.reader != reader or existing.count <= 0:
                return False
            if existing.count == 1:
                if not acl.revoke_exact(
                    source_fd=source_fd,
                    traversal_fds=(root_fd, attempt_fd),
                    reader=reader,
                    deadline_monotonic=deadline_monotonic,
                ):
                    return False
                del self._leases[key]
                return True
            if not acl.revoke_leaf_exact(
                source_fd=source_fd,
                attempt_fd=attempt_fd,
                reader=reader,
                deadline_monotonic=deadline_monotonic,
            ):
                return False
            existing.count -= 1
            return True

    def abandon_for_recovery(self, *, root_fd: int, reader: MappedInspectorReaderV1) -> None:
        """Forget a no-longer-live descriptor owner without changing the ACL."""
        key = _root_lease_key(root_fd)
        with self._lock:
            existing = self._leases.get(key)
            if existing is not None and existing.reader == reader:
                del self._leases[key]


_ROOT_READER_LEASES = _RootReaderLeaseRegistry()


class FileSystemInputStaging:
    """Create one attempt directory and one exclusive 0600 regular input file."""

    def __init__(
        self,
        *,
        private_root: Path,
        reader_mapping: ReaderMappingPort,
        acl: NamedReaderAclPort,
    ) -> None:
        self._private_root = private_root
        self._reader_mapping = reader_mapping
        self._acl = acl

    def begin(self, *, maximum_bytes: int, deadline_monotonic: float) -> MutableInspectorInput:
        if type(maximum_bytes) is not int or maximum_bytes <= 0:
            raise InspectorStagingUnavailable("input staging requires a positive finite byte cap")
        root = self._open_private_root()
        attempt_name = "attempt-" + secrets.token_hex(16)
        attempt_fd: int | None = None
        writer_fd: int | None = None
        attempt_identity: _Identity | None = None
        file_identity: _Identity | None = None
        try:
            os.mkdir(attempt_name, 0o700, dir_fd=root)
            attempt_identity = _Identity.from_stat(
                os.stat(attempt_name, dir_fd=root, follow_symlinks=False)
            )
            attempt_fd = os.open(
                attempt_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=root,
            )
            if _Identity.from_stat(os.fstat(attempt_fd)) != attempt_identity:
                raise InspectorStagingUnavailable("private attempt directory identity changed")
            writer_fd = os.open(
                "artifact",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=attempt_fd,
            )
            file_identity = _Identity.from_stat(os.fstat(writer_fd))
            _require_owned_private_regular(file_identity)
            return MutableInspectorInput(
                root_fd=root,
                attempt_fd=attempt_fd,
                attempt_name=attempt_name,
                writer_fd=writer_fd,
                created_identity=file_identity,
                attempt_identity=attempt_identity,
                maximum_bytes=maximum_bytes,
                reader_mapping=self._reader_mapping,
                acl=self._acl,
                registered_allocation=False,
            )
        except Exception as exc:
            if writer_fd is not None:
                with suppress(OSError):
                    os.close(writer_fd)
            if attempt_fd is not None and attempt_identity is not None:
                _cleanup_exact(
                    root,
                    attempt_fd,
                    attempt_name,
                    file_identity,
                    attempt_identity,
                    strict_name_identity=False,
                )
            else:
                with suppress(OSError):
                    os.close(root)
            if isinstance(exc, InspectorStagingUnavailable):
                raise
            raise InspectorStagingUnavailable(
                "exclusive private input staging is unavailable"
            ) from exc

    def private_root_identity(self) -> PrivateStagingRootV1:
        """Capture the private root identity that durable INTENDED must bind."""
        root = self._open_private_root()
        try:
            identity = _Identity.from_stat(os.fstat(root))
            self._require_private_root(identity, root)
            return PrivateStagingRootV1(
                device=identity.device,
                inode=identity.inode,
                # POSIX ACL masks can reflect an active named traversal entry
                # as 0710.  INTENDED always binds the underlying owner-only
                # private-root contract, never that transient mask bit.
                mode=0o700,
                owner_uid=identity.owner_uid,
                owner_gid=identity.owner_gid,
            )
        finally:
            _close_if_open(root)

    def finish_recovery(self) -> None:
        """Retire a shared traversal ACL after startup recovered every record."""
        root = self._open_private_root()
        try:
            identity = _Identity.from_stat(os.fstat(root))
            mode = identity.mode & 0o777
            if mode == 0o700:
                return
            if mode != 0o710 or not self._acl.retire_private_directory(directory_fd=root):
                raise InspectorStagingUnavailable("recovered root ACL retirement is unavailable")
            retired = _Identity.from_stat(os.fstat(root))
            if (retired.mode & 0o777) != 0o700:
                raise InspectorStagingUnavailable("recovered root ACL retirement is unavailable")
            self._require_private_root(retired, root)
        finally:
            _close_if_open(root)

    def begin_registered(
        self,
        *,
        plan: StagingAllocationPlanV1,
        maximum_bytes: int,
        deadline_monotonic: float,
    ) -> tuple[MutableInspectorInput, StagingAllocationReceiptV1]:
        """Allocate exactly the marker/directory/file names recorded before byte reception."""
        del deadline_monotonic
        if type(maximum_bytes) is not int or maximum_bytes <= 0:
            raise InspectorStagingUnavailable("input staging requires a positive finite byte cap")
        root = self._open_private_root()
        attempt_fd: int | None = None
        writer_fd: int | None = None
        marker_fd: int | None = None
        attempt_identity: _Identity | None = None
        artifact_identity: _Identity | None = None
        marker_identity: _Identity | None = None
        try:
            root_identity = _Identity.from_stat(os.fstat(root))
            if not _matches_root(root_identity, plan.root):
                raise InspectorStagingUnavailable("registered staging root identity changed")
            marker_fd = os.open(
                plan.provisional_marker_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=root,
            )
            _write_all(marker_fd, plan.marker_bytes)
            os.fsync(marker_fd)
            provisional = _Identity.from_stat(os.fstat(marker_fd))
            _require_owned_private_regular(provisional)
            os.link(
                plan.provisional_marker_name,
                plan.committed_marker_name,
                src_dir_fd=root,
                dst_dir_fd=root,
                follow_symlinks=False,
            )
            os.fsync(root)
            os.unlink(plan.provisional_marker_name, dir_fd=root)
            os.fsync(root)
            marker_identity = _Identity.from_stat(
                os.stat(plan.committed_marker_name, dir_fd=root, follow_symlinks=False)
            )
            _require_owned_private_regular(marker_identity)
            os.close(marker_fd)
            marker_fd = None
            verified_marker_fd = os.open(
                plan.committed_marker_name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=root,
            )
            try:
                if _digest_fd(verified_marker_fd) != plan.marker_sha256:
                    raise InspectorStagingUnavailable("registered staging marker digest changed")
            finally:
                _close_if_open(verified_marker_fd)
            os.mkdir(plan.staging_name, 0o700, dir_fd=root)
            attempt_identity = _Identity.from_stat(
                os.stat(plan.staging_name, dir_fd=root, follow_symlinks=False)
            )
            _require_owned_private_directory(attempt_identity)
            attempt_fd = os.open(
                plan.staging_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=root,
            )
            if _Identity.from_stat(os.fstat(attempt_fd)) != attempt_identity:
                raise InspectorStagingUnavailable("registered staging directory identity changed")
            writer_fd = os.open(
                plan.artifact_leaf,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=attempt_fd,
            )
            artifact_identity = _Identity.from_stat(os.fstat(writer_fd))
            _require_owned_private_regular(artifact_identity)
            os.fsync(writer_fd)
            os.fsync(attempt_fd)
            os.fsync(root)
            receipt = StagingAllocationReceiptV1(
                marker=_staging_identity(marker_identity),
                directory=_staging_identity(attempt_identity),
                artifact=_staging_identity(artifact_identity),
            )
            mutable = MutableInspectorInput(
                root_fd=root,
                attempt_fd=attempt_fd,
                attempt_name=plan.staging_name,
                writer_fd=writer_fd,
                created_identity=artifact_identity,
                attempt_identity=attempt_identity,
                maximum_bytes=maximum_bytes,
                reader_mapping=self._reader_mapping,
                acl=self._acl,
                registered_allocation=True,
            )
            root = -1
            attempt_fd = None
            writer_fd = None
            return mutable, receipt
        except Exception as exc:
            _close_if_open(writer_fd)
            _close_if_open(marker_fd)
            if root >= 0 and attempt_fd is not None and attempt_identity is not None:
                _cleanup_exact(
                    root,
                    attempt_fd,
                    plan.staging_name,
                    artifact_identity,
                    attempt_identity,
                    strict_name_identity=True,
                )
                root = -1
            if root >= 0 and marker_identity is not None:
                _unlink_exact(root, plan.committed_marker_name, marker_identity)
            _close_if_open(root if root >= 0 else None)
            if isinstance(exc, InspectorStagingUnavailable):
                raise
            raise InspectorStagingUnavailable(
                "registered input staging allocation is unavailable"
            ) from exc

    def finalize_registered_cleanup(
        self,
        *,
        plan: StagingAllocationPlanV1,
        receipt: StagingAllocationReceiptV1,
    ) -> None:
        """Retire only the committed marker after sealed-owner cleanup removed exact children."""
        root = self._open_private_root()
        try:
            if not _matches_root(_Identity.from_stat(os.fstat(root)), plan.root):
                raise InspectorStagingUnavailable("registered staging root identity changed")
            try:
                os.stat(plan.staging_name, dir_fd=root, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise InspectorStagingUnavailable(
                    "registered staging directory remains after cleanup"
                )
            marker = _Identity.from_stat(
                os.stat(plan.committed_marker_name, dir_fd=root, follow_symlinks=False)
            )
            if not _matches_staging_identity(marker, receipt.marker):
                raise InspectorStagingUnavailable(
                    "registered marker identity changed before cleanup"
                )
            marker_fd = os.open(
                plan.committed_marker_name,
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=root,
            )
            try:
                if _digest_fd(marker_fd) != plan.marker_sha256:
                    raise InspectorStagingUnavailable(
                        "registered marker digest changed before cleanup"
                    )
            finally:
                _close_if_open(marker_fd)
            os.unlink(plan.committed_marker_name, dir_fd=root)
            os.fsync(root)
        except OSError as exc:
            raise InspectorStagingUnavailable("registered staging cleanup is unavailable") from exc
        finally:
            _close_if_open(root)

    def recover_registered(
        self,
        *,
        plan: StagingAllocationPlanV1,
        receipt: StagingAllocationReceiptV1 | None,
    ) -> RegisteredStagingRecoveryDispositionV1:
        """Recover only this recorded allocation; unexpected identities are retained.

        This method does not enumerate the root. A caller records returned uncertainty
        durably and closes admission, rather than widening cleanup to path prefixes.
        """
        try:
            root = self._open_private_root()
        except InspectorStagingUnavailable:
            return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
        try:
            if not _matches_root(_Identity.from_stat(os.fstat(root)), plan.root):
                return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
            provisional_present = _identity_at(root, plan.provisional_marker_name)
            committed_present = _identity_at(root, plan.committed_marker_name)
            provisional = _registered_marker_identity(
                root, plan.provisional_marker_name, plan, expected_links=None
            )
            committed = _registered_marker_identity(
                root, plan.committed_marker_name, plan, expected_links=None
            )
            if (provisional_present is not None and provisional is None) or (
                committed_present is not None and committed is None
            ):
                return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
            directory = _identity_at(root, plan.staging_name)
            if provisional is None and committed is None and directory is None:
                return self._recovery_cleaned(root)
            if provisional is not None:
                if committed is None:
                    if directory is not None or provisional.link_count != 1:
                        return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
                    _unlink_registered_marker(root, plan.provisional_marker_name, provisional)
                    return self._recovery_cleaned(root)
                if (
                    not _same_registered_marker(provisional, committed)
                    or provisional.link_count != 2
                    or committed.link_count != 2
                ):
                    return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
                os.unlink(plan.provisional_marker_name, dir_fd=root)
                os.fsync(root)
                committed = _registered_marker_identity(
                    root, plan.committed_marker_name, plan, expected_links=1
                )
                if committed is None:
                    return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
            if committed is None or committed.link_count != 1:
                return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
            if receipt is not None and not _matches_staging_identity(committed, receipt.marker):
                return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
            if directory is None:
                _unlink_registered_marker(root, plan.committed_marker_name, committed)
                return self._recovery_cleaned(root)
            if receipt is not None and not _matches_staging_identity(directory, receipt.directory):
                return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
            _require_owned_private_directory(directory, allow_acl_mask=True)
            if not self._recover_registered_directory(root, plan, directory, receipt):
                return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
            committed = _registered_marker_identity(
                root, plan.committed_marker_name, plan, expected_links=1
            )
            if committed is None:
                return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
            _unlink_registered_marker(root, plan.committed_marker_name, committed)
            return self._recovery_cleaned(root)
        except (InspectorStagingUnavailable, OSError):
            return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
        finally:
            _close_if_open(root)

    def _recover_registered_directory(
        self,
        root_fd: int,
        plan: StagingAllocationPlanV1,
        directory: _Identity,
        receipt: StagingAllocationReceiptV1 | None,
    ) -> bool:
        directory_fd: int | None = None
        try:
            directory_fd = os.open(
                plan.staging_name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=root_fd,
            )
            if _Identity.from_stat(os.fstat(directory_fd)) != directory:
                return False
            children = os.listdir(directory_fd)
            if any(child != plan.artifact_leaf for child in children):
                return False
            artifact = _identity_at(directory_fd, plan.artifact_leaf)
            if artifact is not None:
                _require_owned_private_regular(artifact, allow_acl_mask=True)
                if receipt is not None and not _matches_registered_artifact(
                    artifact, receipt.artifact
                ):
                    return False
                artifact_fd = os.open(
                    plan.artifact_leaf,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=directory_fd,
                )
                try:
                    if (artifact.mode & 0o777) != 0o600 and (
                        not self._acl.retire_recovered_leaf_acl(
                            source_fd=artifact_fd,
                            attempt_fd=directory_fd,
                        )
                    ):
                        return False
                finally:
                    _close_if_open(artifact_fd)
                os.unlink(plan.artifact_leaf, dir_fd=directory_fd)
                os.fsync(directory_fd)
            elif receipt is not None:
                return False
            _close_if_open(directory_fd)
            directory_fd = None
            current_directory = _identity_at(root_fd, plan.staging_name)
            if current_directory is None or not _same_inode(current_directory, directory):
                return False
            os.rmdir(plan.staging_name, dir_fd=root_fd)
            os.fsync(root_fd)
            return True
        except (InspectorStagingUnavailable, OSError):
            return False
        finally:
            _close_if_open(directory_fd)

    def _open_private_root(self) -> int:
        try:
            self._private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            state = os.lstat(self._private_root)
            if not stat.S_ISDIR(state.st_mode):
                raise InspectorStagingUnavailable("input staging root is not private")
            root = os.open(self._private_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                self._require_private_root(_Identity.from_stat(os.fstat(root)), root)
                return root
            except Exception:
                _close_if_open(root)
                raise
        except OSError as exc:
            raise InspectorStagingUnavailable("private input staging root is unavailable") from exc

    def _recovery_cleaned(self, root_fd: int) -> RegisteredStagingRecoveryDispositionV1:
        """Keep a proved shared root grant until the startup sweep completes."""
        try:
            identity = _Identity.from_stat(os.fstat(root_fd))
            mode = identity.mode & 0o777
            if mode not in {0o700, 0o710}:
                return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN
            self._require_private_root(identity, root_fd)
            return RegisteredStagingRecoveryDispositionV1.CLEANED
        except (InspectorStagingUnavailable, OSError):
            return RegisteredStagingRecoveryDispositionV1.OWNERSHIP_UNCERTAIN

    def _require_private_root(self, identity: _Identity, root_fd: int) -> None:
        if (
            not stat.S_ISDIR(identity.mode)
            or identity.owner_uid != os.geteuid()
            or identity.owner_gid != os.getegid()
        ):
            raise InspectorStagingUnavailable("input staging root is not private")
        mode = identity.mode & 0o777
        if mode == 0o700:
            return
        verifier = getattr(self._acl, "verifies_private_directory", None)
        if mode == 0o710 and callable(verifier) and verifier(directory_fd=root_fd) is True:
            return
        raise InspectorStagingUnavailable("input staging root is not private")


class OutputSpoolStateV1(StrEnum):
    """The anonymous sanitizer response has one launcher-owned descriptor lifetime."""

    OPEN = "OPEN"
    SEALED = "SEALED"
    RESPONSE_OWNED = "RESPONSE_OWNED"
    CLOSED = "CLOSED"
    ABORTED = "ABORTED"


class FileSystemOutputStaging:
    """Anonymous private SANITIZE spool; it has no durable pathname or recovery target."""

    def __init__(self, *, private_root: Path) -> None:
        self._private_root = private_root

    def begin(self, *, maximum_bytes: int, deadline_monotonic: float) -> _PrivateOutputStaged:
        del deadline_monotonic
        if type(maximum_bytes) is not int or maximum_bytes <= 0:
            raise InspectorStagingUnavailable("private output spool requires a positive cap")
        tmpfile = getattr(os, "O_TMPFILE", 0)
        if tmpfile == 0:
            raise InspectorStagingUnavailable("anonymous private output spool is unavailable")
        root = self._open_private_root()
        descriptor: int | None = None
        try:
            descriptor = os.open(
                ".",
                tmpfile | os.O_RDWR | os.O_CLOEXEC,
                0o600,
                dir_fd=root,
            )
            identity = _Identity.from_stat(os.fstat(descriptor))
            _require_owned_private_anonymous_regular(identity)
            return _PrivateOutputStaged(
                root_fd=root,
                descriptor=descriptor,
                identity=identity,
                maximum_bytes=maximum_bytes,
            )
        except Exception as exc:
            _close_if_open(descriptor)
            _close_if_open(root)
            if isinstance(exc, InspectorStagingUnavailable):
                raise
            raise InspectorStagingUnavailable(
                "anonymous private output spool is unavailable"
            ) from exc

    def _open_private_root(self) -> int:
        try:
            root = os.open(self._private_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise InspectorStagingUnavailable("private output root is unavailable") from exc
        try:
            _require_owned_private_directory(_Identity.from_stat(os.fstat(root)))
        except Exception:
            _close_if_open(root)
            raise
        return root


class _PrivateOutputStaged:
    """One unlinked O_TMPFILE response, bounded and retained only by its descriptor."""

    def __init__(
        self,
        *,
        root_fd: int,
        descriptor: int,
        identity: _Identity,
        maximum_bytes: int,
    ) -> None:
        self._root_fd: int | None = root_fd
        self._descriptor: int | None = descriptor
        self._identity = identity
        self._maximum_bytes = maximum_bytes
        self._written = 0
        self._sha256: str | None = None
        self._state = OutputSpoolStateV1.OPEN

    @property
    def state(self) -> OutputSpoolStateV1:
        return self._state

    @property
    def size_bytes(self) -> int:
        if self._state not in {OutputSpoolStateV1.SEALED, OutputSpoolStateV1.RESPONSE_OWNED}:
            raise InspectorStagingUnavailable("private output spool is not sealed")
        return self._written

    @property
    def sha256(self) -> str:
        if self._sha256 is None:
            raise InspectorStagingUnavailable("private output spool is not sealed")
        return self._sha256

    def write(self, chunk: bytes) -> None:
        if self._descriptor is None or self._state is not OutputSpoolStateV1.OPEN:
            raise InspectorStagingUnavailable("private output spool is no longer writable")
        if not isinstance(chunk, bytes) or self._written + len(chunk) > self._maximum_bytes:
            raise InspectorStagingUnavailable("private output spool exceeds its bound")
        view = memoryview(chunk)
        while view:
            try:
                written = os.write(self._descriptor, view)
            except OSError as exc:
                raise InspectorStagingUnavailable(
                    "private output spool write is unavailable"
                ) from exc
            if written <= 0:
                raise InspectorStagingUnavailable("private output spool write did not advance")
            view = view[written:]
        self._written += len(chunk)

    def finish(self) -> None:
        if self._descriptor is None or self._state is not OutputSpoolStateV1.OPEN:
            raise InspectorStagingUnavailable("private output spool cannot be sealed")
        current = _Identity.from_stat(os.fstat(self._descriptor))
        _require_owned_private_anonymous_regular(current)
        if not _same_file_except_size(current, self._identity):
            raise InspectorStagingUnavailable("private output spool descriptor changed before seal")
        try:
            os.fsync(self._descriptor)
            self._sha256 = _digest_fd(self._descriptor)
            os.lseek(self._descriptor, 0, os.SEEK_SET)
        except OSError as exc:
            raise InspectorStagingUnavailable("private output spool seal is unavailable") from exc
        self._identity = current
        self._state = OutputSpoolStateV1.SEALED

    def retain_for_response(self) -> _PrivateOutputStaged:
        if self._descriptor is None or self._state is not OutputSpoolStateV1.SEALED:
            raise InspectorStagingUnavailable("private output spool is not sealed for response")
        _require_owned_private_anonymous_regular(_Identity.from_stat(os.fstat(self._descriptor)))
        self._state = OutputSpoolStateV1.RESPONSE_OWNED
        return self

    def read(self, maximum: int = -1) -> bytes:
        if self._descriptor is None or self._state not in {
            OutputSpoolStateV1.SEALED,
            OutputSpoolStateV1.RESPONSE_OWNED,
        }:
            raise InspectorStagingUnavailable("private output spool is not readable")
        if type(maximum) is not int or maximum < -1:
            raise InspectorStagingUnavailable("private output spool read bound is invalid")
        try:
            return os.read(self._descriptor, self._written if maximum == -1 else maximum)
        except OSError as exc:
            raise InspectorStagingUnavailable("private output spool read is unavailable") from exc

    def abort(self) -> None:
        if self._state in {OutputSpoolStateV1.CLOSED, OutputSpoolStateV1.ABORTED}:
            return
        descriptor, self._descriptor = self._descriptor, None
        root, self._root_fd = self._root_fd, None
        previous = self._state
        self._state = OutputSpoolStateV1.ABORTED
        close_error: OSError | None = None
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                close_error = exc
        if root is not None:
            try:
                os.close(root)
            except OSError as exc:
                close_error = close_error or exc
        self._state = (
            OutputSpoolStateV1.CLOSED
            if previous is OutputSpoolStateV1.RESPONSE_OWNED
            else OutputSpoolStateV1.ABORTED
        )
        if close_error is not None:
            raise InspectorStagingUnavailable(
                "private output spool close is unavailable"
            ) from close_error


class MutableInspectorInput:
    """A writer that can transition exactly once to a retained sealed input."""

    def __init__(
        self,
        *,
        root_fd: int,
        attempt_fd: int,
        attempt_name: str,
        writer_fd: int,
        created_identity: _Identity,
        attempt_identity: _Identity,
        maximum_bytes: int,
        reader_mapping: ReaderMappingPort,
        acl: NamedReaderAclPort,
        registered_allocation: bool,
    ) -> None:
        self._root_fd: int | None = root_fd
        self._attempt_fd: int | None = attempt_fd
        self._attempt_name = attempt_name
        self._writer_fd: int | None = writer_fd
        self._created_identity = created_identity
        self._attempt_identity = attempt_identity
        self._maximum_bytes = maximum_bytes
        self._written = 0
        self._reader_mapping = reader_mapping
        self._acl = acl
        self._registered_allocation = registered_allocation
        self._finished = False

    def write(self, chunk: bytes) -> None:
        if self._writer_fd is None or self._finished:
            raise InspectorStagingUnavailable("input staging writer is no longer mutable")
        if (
            not isinstance(chunk, bytes)
            or not chunk
            or self._written + len(chunk) > self._maximum_bytes
        ):
            raise SealedByteIdentityMismatch("input stream exceeds its exact sealed byte bound")
        view = memoryview(chunk)
        while view:
            written = os.write(self._writer_fd, view)
            if written <= 0:
                raise InspectorStagingUnavailable("input staging write did not advance")
            view = view[written:]
        self._written += len(chunk)

    def seal_for_reader(
        self,
        *,
        expected_sha256: str,
        expected_size_bytes: int,
        reader: MappedInspectorReaderV1,
        supplementary_groups: tuple[int, ...],
        deadline_monotonic: float,
    ) -> InspectorSealedInput:
        if self._writer_fd is None or self._finished:
            raise InspectorStagingUnavailable("input staging cannot be sealed twice")
        if self._root_fd is None or self._attempt_fd is None:
            raise InspectorStagingUnavailable("input staging ownership was already retired")
        readonly_fd: int | None = None
        try:
            if expected_size_bytes != self._written or expected_size_bytes > self._maximum_bytes:
                raise SealedByteIdentityMismatch(
                    "streamed input byte count differs from sealed binding"
                )
            os.fsync(self._writer_fd)
            os.close(self._writer_fd)
            self._writer_fd = None
            readonly_fd = os.open(
                "artifact",
                os.O_RDONLY | os.O_NOFOLLOW,
                dir_fd=self._attempt_fd,
            )
            identity = _Identity.from_stat(os.fstat(readonly_fd))
            _require_owned_private_regular(identity)
            if not _same_file_except_size(identity, self._created_identity):
                raise InspectorStagingUnavailable(
                    "sealed input inode identity changed before reader binding"
                )
            observed_digest = _digest_fd(readonly_fd)
            if observed_digest != expected_sha256:
                raise SealedByteIdentityMismatch(
                    "streamed input digest differs from sealed binding"
                )
            if not _ROOT_READER_LEASES.grant(
                source_fd=readonly_fd,
                root_fd=self._root_fd,
                attempt_fd=self._attempt_fd,
                reader=reader,
                acl=self._acl,
                deadline_monotonic=deadline_monotonic,
            ):
                raise InspectorStagingUnavailable("exact mapped reader ACL is unavailable")
            self._finished = True
            sealed = InspectorSealedInput(
                root_fd=self._root_fd,
                attempt_fd=self._attempt_fd,
                attempt_name=self._attempt_name,
                readonly_fd=readonly_fd,
                identity=identity,
                attempt_identity=self._attempt_identity,
                observed_sha256=observed_digest,
                reader=reader,
                supplementary_groups=supplementary_groups,
                reader_mapping=self._reader_mapping,
                acl=self._acl,
                registered_allocation=self._registered_allocation,
            )
            readonly_fd = None
            self._root_fd = None
            self._attempt_fd = None
            return sealed
        except Exception:
            if readonly_fd is not None:
                with suppress(OSError):
                    os.close(readonly_fd)
            with suppress(Exception):
                self.abort()
            raise

    def abort(self) -> None:
        writer_fd, self._writer_fd = self._writer_fd, None
        if writer_fd is not None:
            with suppress(OSError):
                os.close(writer_fd)
        root_fd, self._root_fd = self._root_fd, None
        attempt_fd, self._attempt_fd = self._attempt_fd, None
        if root_fd is not None and attempt_fd is not None:
            _cleanup_exact(
                root_fd,
                attempt_fd,
                self._attempt_name,
                self._created_identity,
                self._attempt_identity,
                strict_name_identity=self._registered_allocation,
            )
        else:
            _close_if_open(attempt_fd)
            _close_if_open(root_fd)

    def relinquish_for_recovery(self) -> None:
        """Retire descriptors without unlinking a durable registered allocation."""
        writer_fd, self._writer_fd = self._writer_fd, None
        if writer_fd is not None:
            with suppress(OSError):
                os.close(writer_fd)
        attempt_fd, self._attempt_fd = self._attempt_fd, None
        root_fd, self._root_fd = self._root_fd, None
        _close_if_open(attempt_fd)
        _close_if_open(root_fd)


class InspectorSealedInput:
    """Opaque sealed capability retained until the backend returns or is cancelled."""

    def __init__(
        self,
        *,
        root_fd: int,
        attempt_fd: int,
        attempt_name: str,
        readonly_fd: int,
        identity: _Identity,
        attempt_identity: _Identity,
        observed_sha256: str,
        reader: MappedInspectorReaderV1,
        supplementary_groups: tuple[int, ...],
        reader_mapping: ReaderMappingPort,
        acl: NamedReaderAclPort,
        registered_allocation: bool,
    ) -> None:
        self._root_fd: int | None = root_fd
        self._attempt_fd: int | None = attempt_fd
        self._attempt_name = attempt_name
        self._readonly_fd: int | None = readonly_fd
        self._identity = identity
        self._attempt_identity = attempt_identity
        self._observed_sha256 = observed_sha256
        self._reader = reader
        self._supplementary_groups = supplementary_groups
        self._reader_mapping = reader_mapping
        self._acl = acl
        self._registered_allocation = registered_allocation

    def prepare_read_only_bind(self, *, deadline_monotonic: float) -> InspectorReadOnlyBindV1:
        if self._readonly_fd is None:
            raise InspectorStagingUnavailable("sealed input has already been aborted")
        if self._root_fd is None or self._attempt_fd is None:
            raise InspectorStagingUnavailable("sealed input directory ownership was retired")
        current_reader = self._reader_mapping.resolve_exact(
            runtime_uid=self._reader.container_uid,
            runtime_gid=self._reader.container_gid,
            supplementary_groups=self._supplementary_groups,
            deadline_monotonic=deadline_monotonic,
        )
        if current_reader != self._reader:
            raise InspectorStagingUnavailable("mapped reader identity is unavailable or stale")
        _require_exact_descriptor_identity(self._readonly_fd, self._identity)
        if _digest_fd(self._readonly_fd) != self._observed_sha256:
            raise InspectorStagingUnavailable("sealed input digest changed before runtime bind")
        if not self._acl.verifies_exact(
            source_fd=self._readonly_fd,
            traversal_fds=(self._root_fd, self._attempt_fd),
            reader=self._reader,
            deadline_monotonic=deadline_monotonic,
        ):
            raise InspectorStagingUnavailable("mapped reader ACL is unavailable or stale")
        return InspectorReadOnlyBindV1(
            source=InspectorBorrowedSource(self),
            target_path="/input/artifact.tif",
            read_only=True,
            observed_sha256=self._observed_sha256,
            observed_size_bytes=self._identity.size,
            source_device=self._identity.device,
            source_inode=self._identity.inode,
            source_owner_uid=self._identity.owner_uid,
            source_owner_gid=self._identity.owner_gid,
            source_link_count=self._identity.link_count,
            reader_mapping_witness=self._reader.mapping_witness,
        )

    def abort(self) -> None:
        readonly_fd, self._readonly_fd = self._readonly_fd, None
        root_fd, self._root_fd = self._root_fd, None
        attempt_fd, self._attempt_fd = self._attempt_fd, None
        revoke_failed = False
        if readonly_fd is not None and root_fd is not None and attempt_fd is not None:
            try:
                if not _ROOT_READER_LEASES.revoke(
                    source_fd=readonly_fd,
                    root_fd=root_fd,
                    attempt_fd=attempt_fd,
                    reader=self._reader,
                    acl=self._acl,
                    deadline_monotonic=0.0,
                ):
                    revoke_failed = True
            except Exception:
                revoke_failed = True
        if readonly_fd is not None:
            with suppress(OSError):
                os.close(readonly_fd)
        if revoke_failed:
            # Retain the exact nodes for the durable recovery path; deleting
            # after an unproven ACL transition could leave a shared root grant.
            _close_if_open(attempt_fd)
            _close_if_open(root_fd)
            raise InspectorStagingUnavailable("mapped reader ACL retirement is unavailable")
        if root_fd is not None and attempt_fd is not None:
            _cleanup_exact(
                root_fd,
                attempt_fd,
                self._attempt_name,
                self._identity,
                self._attempt_identity,
                strict_name_identity=self._registered_allocation,
            )
        else:
            _close_if_open(attempt_fd)
            _close_if_open(root_fd)

    def relinquish_for_recovery(self) -> None:
        """Retire descriptors without unlinking a durable registered allocation."""
        readonly_fd, self._readonly_fd = self._readonly_fd, None
        if readonly_fd is not None:
            with suppress(OSError):
                os.close(readonly_fd)
        attempt_fd, self._attempt_fd = self._attempt_fd, None
        root_fd, self._root_fd = self._root_fd, None
        if root_fd is not None:
            _ROOT_READER_LEASES.abandon_for_recovery(root_fd=root_fd, reader=self._reader)
        _close_if_open(attempt_fd)
        _close_if_open(root_fd)

    def _live_descriptor(self) -> int:
        """Return the FD only while its sealed owner remains live and unchanged."""
        if self._readonly_fd is None:
            raise InspectorStagingUnavailable("sealed input capability is no longer live")
        _require_exact_descriptor_identity(self._readonly_fd, self._identity)
        if _digest_fd(self._readonly_fd) != self._observed_sha256:
            raise InspectorStagingUnavailable("sealed input digest changed during runtime use")
        return self._readonly_fd


class InspectorBorrowedSource:
    """Capability facade that never publishes a durable descriptor number."""

    def __init__(self, owner: InspectorSealedInput) -> None:
        self._owner = owner

    def read_at(self, *, offset: int, maximum_bytes: int) -> bytes:
        if (
            type(offset) is not int
            or offset < 0
            or type(maximum_bytes) is not int
            or maximum_bytes < 0
        ):
            raise InspectorStagingUnavailable("borrowed input read bounds are invalid")
        return os.pread(self._owner._live_descriptor(), maximum_bytes, offset)

    def consume_fd(self, consumer: Callable[[int], object]) -> object:
        """Pass the current FD to a synchronous adapter without storing it in the bind object."""
        if not callable(consumer):
            raise InspectorStagingUnavailable("borrowed input consumer is required")
        return consumer(self._owner._live_descriptor())


def _digest_fd(file_descriptor: int) -> str:
    os.lseek(file_descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while chunk := os.read(file_descriptor, 65_536):
        digest.update(chunk)
    os.lseek(file_descriptor, 0, os.SEEK_SET)
    return "sha256:" + digest.hexdigest()


def _root_lease_key(root_fd: int) -> tuple[int, int]:
    identity = _Identity.from_stat(os.fstat(root_fd))
    if not stat.S_ISDIR(identity.mode):
        raise InspectorStagingUnavailable("reader ACL root is not a directory")
    return identity.device, identity.inode


def _require_owned_private_anonymous_regular(identity: _Identity) -> None:
    if not stat.S_ISREG(identity.mode) or identity.link_count != 0:
        raise InspectorStagingUnavailable("anonymous output spool is not an unlinked regular file")
    if identity.owner_uid != os.geteuid() or identity.owner_gid != os.getegid():
        raise InspectorStagingUnavailable(
            "anonymous output spool owner differs from launcher identity"
        )
    if (identity.mode & 0o777) != 0o600:
        raise InspectorStagingUnavailable("anonymous output spool mode is not exactly 0600")


def _require_owned_private_regular(identity: _Identity, *, allow_acl_mask: bool = False) -> None:
    if not stat.S_ISREG(identity.mode):
        raise InspectorStagingUnavailable("staged input is not a regular file")
    if identity.link_count != 1:
        raise InspectorStagingUnavailable("staged input has a hardlink")
    if identity.owner_uid != os.geteuid() or identity.owner_gid != os.getegid():
        raise InspectorStagingUnavailable("staged input owner differs from the launcher identity")
    if identity.mode & 0o007 or (identity.mode & 0o070 and not allow_acl_mask):
        raise InspectorStagingUnavailable("staged input is readable by group or world")


def _require_owned_private_directory(identity: _Identity, *, allow_acl_mask: bool = False) -> None:
    allowed_modes = {0o700}
    if allow_acl_mask:
        allowed_modes.add(0o710)
    if not stat.S_ISDIR(identity.mode) or (identity.mode & 0o777) not in allowed_modes:
        raise InspectorStagingUnavailable("staging directory is not private")
    if identity.owner_uid != os.geteuid() or identity.owner_gid != os.getegid():
        raise InspectorStagingUnavailable("staging directory owner differs from launcher identity")


def _staging_identity(identity: _Identity) -> StagingFileIdentityV1:
    return StagingFileIdentityV1(
        device=identity.device,
        inode=identity.inode,
        mode=identity.mode & 0o777,
        owner_uid=identity.owner_uid,
        owner_gid=identity.owner_gid,
        link_count=identity.link_count,
        size=identity.size,
    )


def _matches_root(identity: _Identity, expected: PrivateStagingRootV1) -> bool:
    mode = identity.mode & 0o777
    return (
        identity.device,
        identity.inode,
        mode,
        identity.owner_uid,
        identity.owner_gid,
    ) == (
        expected.device,
        expected.inode,
        expected.mode,
        expected.owner_uid,
        expected.owner_gid,
    ) or (
        expected.mode == 0o700
        and mode == 0o710
        and (
            identity.device,
            identity.inode,
            identity.owner_uid,
            identity.owner_gid,
        )
        == (
            expected.device,
            expected.inode,
            expected.owner_uid,
            expected.owner_gid,
        )
    )


def _matches_staging_identity(identity: _Identity, expected: StagingFileIdentityV1) -> bool:
    exact = (
        identity.device,
        identity.inode,
        identity.mode & 0o777,
        identity.owner_uid,
        identity.owner_gid,
        identity.link_count,
        identity.size,
    ) == (
        expected.device,
        expected.inode,
        expected.mode,
        expected.owner_uid,
        expected.owner_gid,
        expected.link_count,
        expected.size,
    )
    return exact or (
        expected.mode & 0o777 == 0o700
        and identity.mode & 0o777 == 0o710
        and (
            identity.device,
            identity.inode,
            identity.owner_uid,
            identity.owner_gid,
            identity.link_count,
            identity.size,
        )
        == (
            expected.device,
            expected.inode,
            expected.owner_uid,
            expected.owner_gid,
            expected.link_count,
            expected.size,
        )
    )


def _write_all(file_descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(file_descriptor, view)
        if written <= 0:
            raise InspectorStagingUnavailable("registered staging marker write did not advance")
        view = view[written:]


def _identity_at(directory_fd: int, name: str) -> _Identity | None:
    try:
        return _Identity.from_stat(os.stat(name, dir_fd=directory_fd, follow_symlinks=False))
    except FileNotFoundError:
        return None


def _registered_marker_identity(
    root_fd: int,
    name: str,
    plan: StagingAllocationPlanV1,
    *,
    expected_links: int | None,
) -> _Identity | None:
    identity = _identity_at(root_fd, name)
    if identity is None:
        return None
    if (
        not stat.S_ISREG(identity.mode)
        or identity.owner_uid != os.geteuid()
        or identity.owner_gid != os.getegid()
        or identity.mode & 0o077
        or identity.link_count not in {1, 2}
    ):
        return None
    if (identity.mode & 0o777) != 0o600:
        return None
    if expected_links is not None and identity.link_count != expected_links:
        return None
    marker_fd: int | None = None
    try:
        marker_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=root_fd)
        if _Identity.from_stat(os.fstat(marker_fd)) != identity:
            return None
        if identity.size != len(plan.marker_bytes) or _digest_fd(marker_fd) != plan.marker_sha256:
            return None
        return identity
    except OSError:
        return None
    finally:
        _close_if_open(marker_fd)


def _same_registered_marker(left: _Identity, right: _Identity) -> bool:
    return left == right


def _matches_registered_artifact(identity: _Identity, expected: StagingFileIdentityV1) -> bool:
    return (
        identity.device,
        identity.inode,
        identity.owner_uid,
        identity.owner_gid,
        identity.link_count,
    ) == (
        expected.device,
        expected.inode,
        expected.owner_uid,
        expected.owner_gid,
        expected.link_count,
    ) and stat.S_ISREG(identity.mode)


def _unlink_registered_marker(root_fd: int, name: str, expected: _Identity) -> None:
    current = _identity_at(root_fd, name)
    if current != expected:
        raise InspectorStagingUnavailable("registered marker identity changed during cleanup")
    os.unlink(name, dir_fd=root_fd)
    os.fsync(root_fd)


def _unlink_exact(root_fd: int, name: str, expected: _Identity) -> None:
    try:
        observed = _Identity.from_stat(os.stat(name, dir_fd=root_fd, follow_symlinks=False))
        if _same_inode(observed, expected):
            os.unlink(name, dir_fd=root_fd)
            os.fsync(root_fd)
    except OSError:
        pass


def _same_file_except_size(left: _Identity, right: _Identity) -> bool:
    return (
        left.device,
        left.inode,
        left.mode,
        left.owner_uid,
        left.owner_gid,
        left.link_count,
    ) == (
        right.device,
        right.inode,
        right.mode,
        right.owner_uid,
        right.owner_gid,
        right.link_count,
    )


def _same_inode(left: _Identity, right: _Identity) -> bool:
    return left.device == right.device and left.inode == right.inode


def _require_exact_descriptor_identity(readonly_fd: int, expected: _Identity) -> None:
    descriptor_identity = _Identity.from_stat(os.fstat(readonly_fd))
    # A named-user POSIX ACL can cause the kernel to reflect the ACL mask in
    # st_mode (for example 0600 -> 0640).  The ACL port below is the authority
    # for that single group-class permission; all inode identity properties
    # remain exact and are checked before the borrowed FD is exposed.
    if not _same_sealed_file(descriptor_identity, expected):
        raise InspectorStagingUnavailable(
            "sealed input descriptor identity changed before runtime bind"
        )
    _require_owned_private_regular(descriptor_identity, allow_acl_mask=True)


def _same_sealed_file(left: _Identity, right: _Identity) -> bool:
    return (
        left.device,
        left.inode,
        stat.S_IFMT(left.mode),
        left.owner_uid,
        left.owner_gid,
        left.link_count,
        left.size,
    ) == (
        right.device,
        right.inode,
        stat.S_IFMT(right.mode),
        right.owner_uid,
        right.owner_gid,
        right.link_count,
        right.size,
    )


def _close_if_open(file_descriptor: int | None) -> None:
    if file_descriptor is not None:
        with suppress(OSError):
            os.close(file_descriptor)


def _cleanup_exact(
    root_fd: int,
    attempt_fd: int,
    attempt_name: str,
    file_identity: _Identity | None,
    attempt_identity: _Identity,
    *,
    strict_name_identity: bool,
) -> None:
    try:
        try:
            if _Identity.from_stat(os.fstat(attempt_fd)) != attempt_identity:
                if strict_name_identity:
                    raise InspectorStagingUnavailable(
                        "staging directory identity changed during cleanup"
                    )
                return
            if file_identity is not None:
                current = _identity_at(attempt_fd, "artifact")
                if current is None or not _matches_cleanup_artifact(
                    current,
                    file_identity,
                    require_link_count=strict_name_identity,
                ):
                    if strict_name_identity:
                        raise InspectorStagingUnavailable(
                            "staged artifact identity changed during cleanup"
                        )
                    return
                os.unlink("artifact", dir_fd=attempt_fd)
                os.fsync(attempt_fd)
            elif os.listdir(attempt_fd):
                raise InspectorStagingUnavailable("unexpected child exists during staging cleanup")
        finally:
            _close_if_open(attempt_fd)
        current_attempt = _identity_at(root_fd, attempt_name)
        if current_attempt != attempt_identity:
            if strict_name_identity:
                raise InspectorStagingUnavailable(
                    "staging directory identity changed during cleanup"
                )
            return
        os.rmdir(attempt_name, dir_fd=root_fd)
        os.fsync(root_fd)
    except OSError as exc:
        raise InspectorStagingUnavailable("exact staging cleanup is unavailable") from exc
    finally:
        _close_if_open(root_fd)


def _matches_cleanup_artifact(
    current: _Identity, expected: _Identity, *, require_link_count: bool
) -> bool:
    if (
        current.device,
        current.inode,
        stat.S_IFMT(current.mode),
        current.owner_uid,
        current.owner_gid,
    ) != (
        expected.device,
        expected.inode,
        stat.S_IFMT(expected.mode),
        expected.owner_uid,
        expected.owner_gid,
    ):
        return False
    if require_link_count and current.link_count != expected.link_count:
        return False
    return stat.S_ISREG(current.mode)


__all__ = [
    "FileSystemInputStaging",
    "FileSystemOutputStaging",
    "InputStagingPort",
    "RegisteredInputStagingPort",
    "InspectorReadOnlyBindV1",
    "InspectorBorrowedSource",
    "InspectorBorrowedSourcePort",
    "InspectorSealedInput",
    "InspectorSealedInputPort",
    "InspectorStagingUnavailable",
    "MappedInspectorReaderV1",
    "MutableInspectorInput",
    "MutableInspectorInputPort",
    "NamedReaderAclPort",
    "OutputSpoolStateV1",
    "ReaderMappingPort",
    "SealedByteIdentityMismatch",
]
