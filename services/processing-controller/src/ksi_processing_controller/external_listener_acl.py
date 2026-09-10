"""Read-only ACL proof for one systemd-activated private Unix listener.

This module validates an already-created listener.  It never creates a
directory, repairs an ACL, or changes a mode.  Socket ACLs are read through a
bounded, descriptor-anchored ``lgetxattr`` path rather than ``acl_get_fd``:
the latter observes the sockfs descriptor and cannot prove the pathname node
that a distinct worker must traverse.
"""

from __future__ import annotations

import ctypes
import errno
import os
import select
import socket
import stat
import struct
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

_ACL_ACCESS = b"system.posix_acl_access"
_ACL_DEFAULT = b"system.posix_acl_default"
_ACL_VERSION = 0x0002
_ACL_XATTR_MAXIMUM_BYTES = 4096
_ACL_ENTRY_BYTES = 8

_ACL_USER_OBJ = 0x01
_ACL_USER = 0x02
_ACL_GROUP_OBJ = 0x04
_ACL_GROUP = 0x08
_ACL_MASK = 0x10
_ACL_OTHER = 0x20


class ListenerAclUnavailable(RuntimeError):
    """The pathname, its private parent, or its retained proof changed."""


@dataclass(frozen=True, slots=True)
class ListenerNodeIdentity:
    """All pathname attributes that must remain bound through dispatch."""

    device: int
    inode: int
    mode: int
    owner_uid: int
    owner_gid: int
    link_count: int
    ctime_ns: int


def _identity(node: os.stat_result) -> ListenerNodeIdentity:
    return ListenerNodeIdentity(
        device=node.st_dev,
        inode=node.st_ino,
        mode=node.st_mode,
        owner_uid=node.st_uid,
        owner_gid=node.st_gid,
        link_count=node.st_nlink,
        ctime_ns=node.st_ctime_ns,
    )


def _acl_entries(value: bytes | None) -> tuple[tuple[int, int, int], ...] | None:
    """Decode only the bounded Linux POSIX ACL xattr representation."""
    if value is None:
        return None
    if len(value) < 4 or (len(value) - 4) % _ACL_ENTRY_BYTES:
        raise ListenerAclUnavailable("listener ACL encoding is invalid")
    version = struct.unpack_from("<I", value, 0)[0]
    if version != _ACL_VERSION:
        raise ListenerAclUnavailable("listener ACL version is invalid")
    entries = tuple(
        struct.unpack_from("<HHI", value, offset)
        for offset in range(4, len(value), _ACL_ENTRY_BYTES)
    )
    if not entries or any(perms & ~0o7 for _tag, perms, _qualifier in entries):
        raise ListenerAclUnavailable("listener ACL entries are invalid")
    return entries


_libc = ctypes.CDLL(None, use_errno=True)
_lgetxattr = _libc.lgetxattr
_lgetxattr.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t)
_lgetxattr.restype = ctypes.c_ssize_t


def _anchored_acl(
    parent_fd: int, name: str, attribute: bytes
) -> tuple[tuple[int, int, int], ...] | None:
    """Bound a nofollow xattr read at a retained directory descriptor.

    ``/proc/self/fd/<fd>/<name>`` anchors directory traversal at the already
    opened parent.  ``lgetxattr`` leaves the final name unfollowed, so a
    replacement symlink cannot redirect the ACL read.
    """
    path = f"/proc/self/fd/{parent_fd}/{name}".encode()
    buffer = ctypes.create_string_buffer(_ACL_XATTR_MAXIMUM_BYTES)
    result = _lgetxattr(path, attribute, buffer, _ACL_XATTR_MAXIMUM_BYTES)
    if result < 0:
        error = ctypes.get_errno()
        if error in {errno.ENODATA, errno.ENOTSUP}:
            return None
        raise ListenerAclUnavailable("listener ACL cannot be read")
    if result > _ACL_XATTR_MAXIMUM_BYTES:
        raise ListenerAclUnavailable("listener ACL exceeds bounded read")
    return _acl_entries(buffer.raw[:result])


def _anchored_directory_acl(
    parent_fd: int, attribute: bytes
) -> tuple[tuple[int, int, int], ...] | None:
    """Read the retained directory's own ACL through its anchored ``.`` node."""
    return _anchored_acl(parent_fd, ".", attribute)


def _exact_acl(
    actual: tuple[tuple[int, int, int], ...] | None,
    expected: tuple[tuple[int, int, int], ...] | None,
    *,
    subject: str,
) -> None:
    if actual != expected:
        raise ListenerAclUnavailable(f"{subject} ACL is not exact")


def _no_default_acl(parent_fd: int, name: str, *, directory: bool) -> None:
    actual = (
        _anchored_directory_acl(parent_fd, _ACL_DEFAULT)
        if directory
        else _anchored_acl(parent_fd, name, _ACL_DEFAULT)
    )
    if actual is not None:
        raise ListenerAclUnavailable("listener default ACL is forbidden")


def _worker_can_traverse(
    entries: tuple[tuple[int, int, int], ...] | None,
    node: os.stat_result,
    worker_uid: int,
) -> bool:
    """Prove traversal for this UID without guessing its group membership."""
    if worker_uid == node.st_uid:
        return bool(stat.S_IMODE(node.st_mode) & 0o100)
    if entries is None:
        mode = stat.S_IMODE(node.st_mode)
        return bool(mode & 0o010) and bool(mode & 0o001)
    mask = next((perms for tag, perms, _qualifier in entries if tag == _ACL_MASK), 0o7)
    named = [
        perms
        for tag, perms, qualifier in entries
        if tag == _ACL_USER and qualifier == worker_uid
    ]
    if named:
        # POSIX ACL selects a matching named user before group or other.
        return bool(named[-1] & mask & 0o1)
    group_entries = [
        perms
        for tag, perms, _qualifier in entries
        if tag in {_ACL_GROUP_OBJ, _ACL_GROUP}
    ]
    other = next((perms for tag, perms, _qualifier in entries if tag == _ACL_OTHER), 0)
    # Group membership is deliberately not inferred.  Every possible group
    # result and the no-group other result must permit traversal.
    return bool(other & 0o1) and bool(group_entries) and all(
        perms & mask & 0o1 for perms in group_entries
    )


def _assert_worker_path_access(
    *,
    entries: tuple[tuple[int, int, int], ...] | None,
    node: os.stat_result,
    next_node: os.stat_result | None,
    worker_uid: int,
) -> None:
    if not _worker_can_traverse(entries, node, worker_uid):
        raise ListenerAclUnavailable("listener ancestor is not traversable by worker")
    if _worker_cannot_write(entries, node, worker_uid):
        return
    # A sticky parent protects an existing launcher-owned child from a worker's
    # unlink/rename even when the worker may create unrelated entries.  It is
    # the only writable ancestor form accepted by this validator.
    if (
        next_node is None
        or not stat.S_ISVTX & node.st_mode
        or node.st_uid == worker_uid
        or next_node.st_uid == worker_uid
    ):
        raise ListenerAclUnavailable("listener ancestor worker write access is unsafe")


def _open_safe_directory_chain(
    path: Path,
    *,
    worker_uid: int,
    same_uid_fixture: bool,
) -> int:
    """Open a symlink-free path and prove the worker can safely traverse all of it.

    A root-owned ``/run``-style ``0755`` path is safe because the configured
    worker can traverse but cannot write it.  A sticky parent such as ``/tmp``
    is safe only while its next child is launcher-owned.  No pre-boundary
    component is skipped merely because a deeper private directory exists.
    """
    if not path.is_absolute():
        raise ListenerAclUnavailable("listener parent path is not absolute")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = -1
    try:
        fd = os.open("/", flags)
        previous_node = os.fstat(fd)
        previous_entries = _anchored_directory_acl(fd, _ACL_ACCESS)
        for component in path.parts[1:]:
            next_fd = -1
            try:
                next_fd = os.open(component, flags, dir_fd=fd)
                next_node = os.fstat(next_fd)
                if not stat.S_ISDIR(next_node.st_mode):
                    raise ListenerAclUnavailable("listener ancestor is not a directory")
                if not same_uid_fixture:
                    _assert_worker_path_access(
                        entries=previous_entries,
                        node=previous_node,
                        next_node=next_node,
                        worker_uid=worker_uid,
                    )
                old_fd = fd
                fd = next_fd
                next_fd = -1
                os.close(old_fd)
                previous_node = next_node
                previous_entries = _anchored_directory_acl(fd, _ACL_ACCESS)
            finally:
                if next_fd >= 0:
                    os.close(next_fd)
        if not same_uid_fixture:
            _assert_worker_path_access(
                entries=previous_entries,
                node=previous_node,
                next_node=None,
                worker_uid=worker_uid,
            )
        result = fd
        fd = -1
        return result
    finally:
        if fd >= 0:
            os.close(fd)


def _worker_cannot_write(
    entries: tuple[tuple[int, int, int], ...] | None,
    node: os.stat_result,
    worker_uid: int,
) -> bool:
    """Reject every ACL class that could grant an unknown worker write access."""
    if worker_uid == node.st_uid:
        return not bool(stat.S_IMODE(node.st_mode) & 0o200)
    if entries is None:
        mode = stat.S_IMODE(node.st_mode)
        return not bool(mode & 0o020) and not bool(mode & 0o002)
    mask = next((perms for tag, perms, _qualifier in entries if tag == _ACL_MASK), 0o7)
    named_worker = [
        perms
        for tag, perms, qualifier in entries
        if tag == _ACL_USER and qualifier == worker_uid
    ]
    if named_worker:
        return not bool(named_worker[-1] & mask & 0o2)
    # Without a pinned group list, every owning or named group class and the
    # other class must deny writes.  The ACL mask limits the group class.
    group_entries = [
        perms
        for tag, perms, _qualifier in entries
        if tag in {_ACL_GROUP_OBJ, _ACL_GROUP}
    ]
    other = next((perms for tag, perms, _qualifier in entries if tag == _ACL_OTHER), 0)
    return (
        bool(group_entries)
        and all(not (perms & mask & 0o2) for perms in group_entries)
        and not bool(other & 0o2)
    )


@dataclass(slots=True)
class ActivatedListenerAccessReceipt:
    """Retains the private parent descriptor and re-proves each dispatch."""

    socket_path: Path
    expected_owner_uid: int
    expected_owner_gid: int
    required_worker_uid: int
    parent_fd: int
    parent_identity: ListenerNodeIdentity
    socket_identity: ListenerNodeIdentity
    _closed: bool = False

    @classmethod
    def establish(
        cls,
        listener: socket.socket,
        *,
        socket_path: Path,
        expected_owner_uid: int,
        required_worker_uid: int,
        deadline_monotonic: float,
        pending: deque[socket.socket],
    ) -> ActivatedListenerAccessReceipt:
        if type(required_worker_uid) is not int or required_worker_uid < 0:
            raise ListenerAclUnavailable("required worker UID is invalid")
        parent_fd = -1
        try:
            parent_fd = _open_safe_directory_chain(
                socket_path.parent,
                worker_uid=required_worker_uid,
                same_uid_fixture=required_worker_uid == expected_owner_uid,
            )
            receipt = cls(
                socket_path=socket_path,
                expected_owner_uid=expected_owner_uid,
                expected_owner_gid=os.getegid(),
                required_worker_uid=required_worker_uid,
                parent_fd=parent_fd,
                parent_identity=_identity(os.fstat(parent_fd)),
                socket_identity=cls._socket_identity(parent_fd, socket_path.name),
            )
            receipt.reprove(listener, deadline_monotonic=deadline_monotonic, pending=pending)
            return receipt
        except BaseException:
            if parent_fd >= 0:
                os.close(parent_fd)
            raise

    @staticmethod
    def _socket_identity(parent_fd: int, name: str) -> ListenerNodeIdentity:
        return _identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))

    def _verify_parent(self) -> None:
        current_parent_fd = _open_safe_directory_chain(
            self.socket_path.parent,
            worker_uid=self.required_worker_uid,
            same_uid_fixture=self.required_worker_uid == self.expected_owner_uid,
        )
        try:
            if _identity(os.fstat(current_parent_fd)) != self.parent_identity:
                raise ListenerAclUnavailable("listener parent pathname changed")
        finally:
            os.close(current_parent_fd)
        parent = os.fstat(self.parent_fd)
        if _identity(parent) != self.parent_identity or not stat.S_ISDIR(parent.st_mode):
            raise ListenerAclUnavailable("listener parent identity changed")
        if parent.st_uid != self.expected_owner_uid or parent.st_gid != self.expected_owner_gid:
            raise ListenerAclUnavailable("listener parent owner changed")
        if self.required_worker_uid == self.expected_owner_uid:
            _exact_acl(
                _anchored_directory_acl(self.parent_fd, _ACL_ACCESS),
                None,
                subject="same-UID listener parent",
            )
            if stat.S_IMODE(parent.st_mode) != 0o700:
                raise ListenerAclUnavailable("same-UID listener parent mode is unsafe")
        else:
            _exact_acl(
                _anchored_directory_acl(self.parent_fd, _ACL_ACCESS),
                (
                    (_ACL_USER_OBJ, 0o7, 0xFFFFFFFF),
                    (_ACL_USER, 0o1, self.required_worker_uid),
                    (_ACL_GROUP_OBJ, 0o0, 0xFFFFFFFF),
                    (_ACL_MASK, 0o1, 0xFFFFFFFF),
                    (_ACL_OTHER, 0o0, 0xFFFFFFFF),
                ),
                subject="distinct-worker listener parent",
            )
            if stat.S_IMODE(parent.st_mode) != 0o710:
                raise ListenerAclUnavailable("distinct-worker listener parent mode is unsafe")
        _no_default_acl(self.parent_fd, ".", directory=True)

    def _verify_socket(self) -> None:
        node = os.stat(self.socket_path.name, dir_fd=self.parent_fd, follow_symlinks=False)
        if _identity(node) != self.socket_identity or not stat.S_ISSOCK(node.st_mode):
            raise ListenerAclUnavailable("listener node identity changed")
        if node.st_uid != self.expected_owner_uid or node.st_gid != self.expected_owner_gid:
            raise ListenerAclUnavailable("listener node owner changed")
        if node.st_nlink != 1:
            raise ListenerAclUnavailable("listener node link count is unsafe")
        if self.required_worker_uid == self.expected_owner_uid:
            _exact_acl(
                _anchored_acl(self.parent_fd, self.socket_path.name, _ACL_ACCESS),
                None,
                subject="same-UID listener socket",
            )
            if stat.S_IMODE(node.st_mode) != 0o600:
                raise ListenerAclUnavailable("same-UID listener socket mode is unsafe")
        else:
            _exact_acl(
                _anchored_acl(self.parent_fd, self.socket_path.name, _ACL_ACCESS),
                (
                    (_ACL_USER_OBJ, 0o6, 0xFFFFFFFF),
                    (_ACL_USER, 0o6, self.required_worker_uid),
                    (_ACL_GROUP_OBJ, 0o0, 0xFFFFFFFF),
                    (_ACL_MASK, 0o6, 0xFFFFFFFF),
                    (_ACL_OTHER, 0o0, 0xFFFFFFFF),
                ),
                subject="distinct-worker listener socket",
            )
            if stat.S_IMODE(node.st_mode) != 0o660:
                raise ListenerAclUnavailable("distinct-worker listener socket mode is unsafe")
        _no_default_acl(self.parent_fd, self.socket_path.name, directory=False)

    def reprove(
        self,
        listener: socket.socket,
        *,
        deadline_monotonic: float,
        pending: deque[socket.socket],
    ) -> None:
        """Bind pathname ACLs and a fresh SO_PEERCRED nonce before dispatch."""
        if self._closed:
            raise ListenerAclUnavailable("listener access receipt is closed")
        if time.monotonic() >= deadline_monotonic:
            raise ListenerAclUnavailable("listener proof deadline elapsed")
        if (
            listener.family != socket.AF_UNIX
            or listener.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
            or listener.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) != 1
            or listener.getsockname() != os.fspath(self.socket_path)
            or not stat.S_ISSOCK(os.fstat(listener.fileno()).st_mode)
        ):
            raise ListenerAclUnavailable("listener descriptor is not exact")
        self._verify_parent()
        self._verify_socket()
        nonce = b"\x00ksi-inspector-proof-" + os.urandom(24).hex().encode("ascii")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.bind(nonce)
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise ListenerAclUnavailable("listener proof deadline elapsed")
            probe.settimeout(remaining)
            probe.connect(os.fspath(self.socket_path))
            while True:
                remaining = deadline_monotonic - time.monotonic()
                if remaining <= 0 or not select.select([listener], [], [], remaining)[0]:
                    raise ListenerAclUnavailable("listener probe did not return")
                connection, address = listener.accept()
                if address == nonce:
                    with connection:
                        credentials = struct.unpack(
                            "3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                        )
                        if credentials != (os.getpid(), os.geteuid(), os.getegid()):
                            raise ListenerAclUnavailable("listener probe peer differs")
                    break
                pending.append(connection)
                if len(pending) >= 128:
                    raise ListenerAclUnavailable("listener pending connection cap exceeded")
        self._verify_parent()
        self._verify_socket()
        current = os.lstat(self.socket_path)
        if _identity(current) != self.socket_identity or time.monotonic() >= deadline_monotonic:
            raise ListenerAclUnavailable("listener pathname changed during proof")

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            os.close(self.parent_fd)
