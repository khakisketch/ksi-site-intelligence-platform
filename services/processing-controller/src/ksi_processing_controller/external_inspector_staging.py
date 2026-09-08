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
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class InspectorStagingUnavailable(RuntimeError):
    """Identity, mapping, ACL, or private-filesystem state failed closed."""


class SealedByteIdentityMismatch(ValueError):
    """The streamed bytes do not equal the Core-observed sealed byte binding."""


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


class InputStagingPort(Protocol):
    def begin(
        self,
        *,
        maximum_bytes: int,
        deadline_monotonic: float,
    ) -> MutableInspectorInputPort: ...


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


class InspectorSealedInputPort(Protocol):
    def prepare_read_only_bind(self, *, deadline_monotonic: float) -> InspectorReadOnlyBindV1: ...

    def abort(self) -> None: ...


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
                )
            else:
                with suppress(OSError):
                    os.close(root)
            if isinstance(exc, InspectorStagingUnavailable):
                raise
            raise InspectorStagingUnavailable(
                "exclusive private input staging is unavailable"
            ) from exc

    def _open_private_root(self) -> int:
        try:
            self._private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
            state = os.lstat(self._private_root)
            if (
                not stat.S_ISDIR(state.st_mode)
                or state.st_mode & 0o077
                or state.st_uid != os.geteuid()
                or state.st_gid != os.getegid()
            ):
                raise InspectorStagingUnavailable("input staging root is not private")
            return os.open(self._private_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as exc:
            raise InspectorStagingUnavailable("private input staging root is unavailable") from exc


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
            if not self._acl.grant_exact(
                source_fd=readonly_fd,
                traversal_fds=(self._root_fd, self._attempt_fd),
                reader=reader,
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
            )
            readonly_fd = None
            self._root_fd = None
            self._attempt_fd = None
            return sealed
        except Exception:
            if readonly_fd is not None:
                with suppress(OSError):
                    os.close(readonly_fd)
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
            )
        else:
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
        if readonly_fd is not None:
            with suppress(OSError):
                os.close(readonly_fd)
        root_fd, self._root_fd = self._root_fd, None
        attempt_fd, self._attempt_fd = self._attempt_fd, None
        if root_fd is not None and attempt_fd is not None:
            _cleanup_exact(
                root_fd,
                attempt_fd,
                self._attempt_name,
                self._identity,
                self._attempt_identity,
            )
        else:
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


def _require_owned_private_regular(identity: _Identity, *, allow_acl_mask: bool = False) -> None:
    if not stat.S_ISREG(identity.mode):
        raise InspectorStagingUnavailable("staged input is not a regular file")
    if identity.link_count != 1:
        raise InspectorStagingUnavailable("staged input has a hardlink")
    if identity.owner_uid != os.geteuid() or identity.owner_gid != os.getegid():
        raise InspectorStagingUnavailable("staged input owner differs from the launcher identity")
    if identity.mode & 0o007 or (identity.mode & 0o070 and not allow_acl_mask):
        raise InspectorStagingUnavailable("staged input is readable by group or world")


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
) -> None:
    try:
        try:
            if file_identity is not None:
                current = _Identity.from_stat(
                    os.stat("artifact", dir_fd=attempt_fd, follow_symlinks=False)
                )
                if _same_inode(current, file_identity):
                    os.unlink("artifact", dir_fd=attempt_fd)
        except FileNotFoundError:
            pass
    finally:
        with suppress(OSError):
            os.close(attempt_fd)
        try:
            current_attempt = _Identity.from_stat(
                os.stat(attempt_name, dir_fd=root_fd, follow_symlinks=False)
            )
            if (
                current_attempt.device == attempt_identity.device
                and current_attempt.inode == attempt_identity.inode
            ):
                os.rmdir(attempt_name, dir_fd=root_fd)
        except OSError:
            pass
        with suppress(OSError):
            os.close(root_fd)


__all__ = [
    "FileSystemInputStaging",
    "InputStagingPort",
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
    "ReaderMappingPort",
    "SealedByteIdentityMismatch",
]
