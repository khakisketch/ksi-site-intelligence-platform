"""Fixed FD-only byte-I/O control for private external-inspector staging.

The inspector daemon is multithreaded.  A potentially blocking filesystem
operation therefore runs only in the fixed helper entrypoint started with
``posix_spawn``.  Callers never give that helper a path, command, module, or
callback: each request carries one already-open descriptor over a local
``SOCK_SEQPACKET`` control socket.

This module deliberately bounds *caller return*, not kernel I/O latency.  If a
helper cannot be proved reaped after cancellation, the descriptor and pidfd
remain quarantined and this controller closes admission instead of reusing or
cleaning the resource optimistically.
"""

from __future__ import annotations

import array
import ctypes
import errno
import os
import select
import signal
import socket
import struct
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedByteReaderPort,
    DeadlineBoundedByteSinkPort,
    ProtocolDeadline,
    ProtocolDeadlineExceeded,
    ProtocolViolation,
)


class InspectorFileIoUnavailable(ProtocolViolation):
    """The exact private descriptor cannot safely continue byte I/O."""


class _Operation(IntEnum):
    HELLO = 1
    WRITE = 2
    READ = 3
    SEAL = 4
    CLOSE = 5
    VERIFY = 6
    ERROR = 255


_CONTROL_FD: Final = 3
_MAX_CONTROL_BYTES: Final = 60 * 1024
_NONCE_BYTES: Final = 16
_FRAME_HEADER: Final = struct.Struct("!16sQBQI")
_SEAL_RECEIPT: Final = struct.Struct("!QQQIIQQ32s")
_P_PIDFD: Final = 3
_SYS_PIDFD_SEND_SIGNAL: Final = 424
_SYS_PIDFD_OPEN: Final = 434


@dataclass(frozen=True, slots=True)
class FileIoSealReceiptV1:
    """Readback evidence produced by the helper after an exact fsync."""

    device: int
    inode: int
    mode: int
    owner_uid: int
    owner_gid: int
    link_count: int
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class QuarantinedFileIoV1:
    """Exact unreaped helper ownership retained for a later recovery owner."""

    pid: int
    pidfd: int | None
    descriptor: int | None
    reason: str


class _FileIoQuarantine:
    """A process-local closed-admission latch for unreaped helper ownership."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: list[QuarantinedFileIoV1] = []

    def retain(self, entry: QuarantinedFileIoV1) -> None:
        with self._lock:
            self._entries.append(entry)

    def admission_is_closed(self) -> bool:
        with self._lock:
            return bool(self._entries)

    def entries(self) -> tuple[QuarantinedFileIoV1, ...]:
        with self._lock:
            return tuple(self._entries)


_QUARANTINE = _FileIoQuarantine()


def quarantined_file_io() -> tuple[QuarantinedFileIoV1, ...]:
    """Expose retained ownership to the daemon's recovery coordinator only."""

    return _QUARANTINE.entries()


class BoundedFileIo(DeadlineBoundedByteSinkPort, DeadlineBoundedByteReaderPort):
    """One fixed helper lifetime for one already-open private descriptor.

    ``written_bytes`` changes only after a matching nonce/sequence/offset/count
    acknowledgement.  The helper is intentionally unable to name or reopen a
    filesystem object.
    """

    def __init__(self, *, descriptor: int, maximum_bytes: int) -> None:
        if type(descriptor) is not int or descriptor < 0:
            raise ValueError("file I/O requires an open descriptor")
        if type(maximum_bytes) is not int or maximum_bytes <= 0:
            raise ValueError("file I/O requires a positive byte cap")
        if _QUARANTINE.admission_is_closed():
            raise InspectorFileIoUnavailable("unreaped file I/O ownership closes admission")
        self._descriptor = descriptor
        self._maximum_bytes = maximum_bytes
        self._written_bytes = 0
        self._offset = 0
        self._sequence = 0
        self._nonce: bytes | None = None
        self._control: socket.socket | None = None
        self._pid: int | None = None
        self._pidfd: int | None = None
        self._sealed = False
        self._closed = False
        self._quarantined = False
        self._lock = threading.RLock()

    @property
    def written_bytes(self) -> int:
        return self._written_bytes

    @property
    def is_quarantined(self) -> bool:
        return self._quarantined

    def write_chunk(
        self,
        chunk: bytes,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> None:
        if not isinstance(chunk, bytes) or not chunk:
            raise InspectorFileIoUnavailable("file I/O requires non-empty byte chunks")
        with self._lock:
            self._require_open()
            if self._sealed or self._written_bytes + len(chunk) > self._maximum_bytes:
                raise InspectorFileIoUnavailable("file I/O write exceeds its exact bound")
            position = 0
            while position < len(chunk):
                part = chunk[position : position + _maximum_payload_bytes()]
                offset = self._offset
                self._request(
                    _Operation.WRITE,
                    offset=offset,
                    count=len(part),
                    payload=part,
                    deadline=deadline,
                    wait_is_current=wait_is_current,
                    heartbeat_interval_millis=heartbeat_interval_millis,
                )
                # Only an exact ACK reaches this line.
                self._offset += len(part)
                self._written_bytes += len(part)
                position += len(part)

    def read_chunk(
        self,
        maximum_bytes: int,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> bytes:
        if type(maximum_bytes) is not int or maximum_bytes <= 0:
            raise InspectorFileIoUnavailable("file I/O read bound is invalid")
        with self._lock:
            self._require_open()
            payload = self._request(
                _Operation.READ,
                offset=self._offset,
                count=min(maximum_bytes, _maximum_payload_bytes()),
                payload=b"",
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
            if len(payload) > maximum_bytes:
                raise InspectorFileIoUnavailable("file I/O helper exceeded read bound")
            self._offset += len(payload)
            return payload

    def read_at(
        self,
        *,
        offset: int,
        maximum_bytes: int,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> bytes:
        """PREAD an explicit offset without changing the sequential response cursor."""
        if (
            type(offset) is not int
            or offset < 0
            or type(maximum_bytes) is not int
            or maximum_bytes < 0
        ):
            raise InspectorFileIoUnavailable("file I/O explicit read bounds are invalid")
        if maximum_bytes == 0:
            return b""
        with self._lock:
            self._require_open()
            return self._request(
                _Operation.READ,
                offset=offset,
                count=min(maximum_bytes, _maximum_payload_bytes()),
                payload=b"",
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )

    def seal(
        self,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> FileIoSealReceiptV1:
        with self._lock:
            self._require_open()
            if self._sealed:
                raise InspectorFileIoUnavailable("file I/O descriptor is already sealed")
            payload = self._request(
                _Operation.SEAL,
                offset=0,
                count=self._written_bytes,
                payload=b"",
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
            if len(payload) != _SEAL_RECEIPT.size:
                raise InspectorFileIoUnavailable("file I/O seal acknowledgement is malformed")
            device, inode, mode, uid, gid, links, size, digest = _SEAL_RECEIPT.unpack(payload)
            if size != self._written_bytes:
                raise InspectorFileIoUnavailable(
                    "file I/O seal size does not match acknowledged bytes"
                )
            self._sealed = True
            return FileIoSealReceiptV1(
                device=device,
                inode=inode,
                mode=mode,
                owner_uid=uid,
                owner_gid=gid,
                link_count=links,
                size_bytes=size,
                sha256="sha256:" + digest.hex(),
            )

    def rewind(self) -> None:
        """Reset only the parent-side PREAD offset after a successful final seal."""

        with self._lock:
            self._require_open()
            if not self._sealed:
                raise InspectorFileIoUnavailable("file I/O descriptor is not sealed")
            self._offset = 0

    def verify_readback(
        self,
        *,
        expected_size_bytes: int,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> FileIoSealReceiptV1:
        """Return full PREAD digest/identity evidence without changing descriptor state."""
        if type(expected_size_bytes) is not int or expected_size_bytes < 0:
            raise InspectorFileIoUnavailable("file I/O expected readback size is invalid")
        with self._lock:
            self._require_open()
            payload = self._request(
                _Operation.VERIFY,
                offset=0,
                count=expected_size_bytes,
                payload=b"",
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
            if len(payload) != _SEAL_RECEIPT.size:
                raise InspectorFileIoUnavailable("file I/O readback acknowledgement is malformed")
            device, inode, mode, uid, gid, links, size, digest = _SEAL_RECEIPT.unpack(payload)
            if size != expected_size_bytes:
                raise InspectorFileIoUnavailable("file I/O readback size does not match request")
            return FileIoSealReceiptV1(
                device=device,
                inode=inode,
                mode=mode,
                owner_uid=uid,
                owner_gid=gid,
                link_count=links,
                size_bytes=size,
                sha256="sha256:" + digest.hex(),
            )

    def close(self) -> None:
        """Terminate and nonblocking-reap only this helper; never extend a request."""

        with self._lock:
            if self._closed or self._quarantined:
                return
            self._closed = True
            self._terminate_and_reap(reason="caller closed file I/O helper")

    def _request(
        self,
        operation: _Operation,
        *,
        offset: int,
        count: int,
        payload: bytes,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> bytes:
        self._validate_wait(wait_is_current, heartbeat_interval_millis)
        self._ensure_started(
            deadline=deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )
        nonce = self._nonce
        control = self._control
        if nonce is None or control is None:
            raise InspectorFileIoUnavailable("file I/O helper is unavailable")
        self._sequence += 1
        sequence = self._sequence
        frame = _FRAME_HEADER.pack(nonce, sequence, int(operation), offset, count) + payload
        try:
            self._send_frame(
                control,
                frame,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
            reply = self._receive_frame(
                control,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
        except (ProtocolDeadlineExceeded, ProtocolViolation):
            self._terminate_and_reap(reason="file I/O request lost deadline or authority")
            raise
        if len(reply) < _FRAME_HEADER.size:
            self._terminate_and_reap(reason="malformed file I/O acknowledgement")
            raise InspectorFileIoUnavailable("file I/O acknowledgement is malformed")
        (
            reply_nonce,
            reply_sequence,
            reply_operation,
            reply_offset,
            reply_count,
        ) = _FRAME_HEADER.unpack(reply[: _FRAME_HEADER.size])
        body = reply[_FRAME_HEADER.size :]
        if reply_operation == int(_Operation.ERROR):
            self._terminate_and_reap(reason="file I/O helper rejected its request")
            raise InspectorFileIoUnavailable("file I/O helper rejected its request")
        if (
            reply_nonce != nonce
            or reply_sequence != sequence
            or reply_operation != int(operation)
            or reply_offset != offset
            or (operation is not _Operation.READ and reply_count != count)
            or (operation is _Operation.READ and reply_count > count)
        ):
            self._terminate_and_reap(reason="file I/O acknowledgement did not match request")
            raise InspectorFileIoUnavailable("file I/O acknowledgement did not match request")
        if operation is _Operation.WRITE and body:
            self._terminate_and_reap(reason="file I/O write acknowledgement carried bytes")
            raise InspectorFileIoUnavailable("file I/O write acknowledgement is malformed")
        # EOF is represented by an exact ACK with a zero count.
        if operation is _Operation.READ and len(body) != reply_count:
            self._terminate_and_reap(reason="file I/O read acknowledgement is malformed")
            raise InspectorFileIoUnavailable("file I/O read acknowledgement is malformed")
        self._reap_after_success(
            deadline=deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )
        return body

    def _ensure_started(
        self,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> None:
        if self._control is not None:
            raise InspectorFileIoUnavailable("file I/O helper lifetime did not finish")
        if _QUARANTINE.admission_is_closed():
            raise InspectorFileIoUnavailable("unreaped file I/O ownership closes admission")
        if wait_is_current is not None and not wait_is_current():
            raise ProtocolViolation("authority lost before fixed file I/O helper start")
        deadline.remaining()
        parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        parent.setblocking(False)
        child_fd = child.fileno()
        try:
            actions = _fixed_helper_file_actions(child_fd)
            pid = os.posix_spawn(
                sys.executable,
                (
                    sys.executable,
                    "-m",
                    "ksi_processing_controller.external_inspector_file_io_helper",
                ),
                _closed_helper_environment(),
                file_actions=actions,
            )
            # Ownership begins at spawn, before a pidfd can be obtained. No file FD
            # has been sent through SCM_RIGHTS during this startup interval.
            self._pid = pid
            self._control = parent
            pidfd = _pidfd_open(pid)
        except Exception as exc:
            parent.close()
            child.close()
            self._terminate_and_reap(reason="fixed helper pidfd acquisition failed")
            raise InspectorFileIoUnavailable("fixed file I/O helper cannot start") from exc
        child.close()
        self._control = parent
        self._pid = pid
        self._pidfd = pidfd
        try:
            hello = self._receive_frame(
                parent,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
            if len(hello) != _FRAME_HEADER.size:
                raise InspectorFileIoUnavailable("fixed file I/O helper greeting is malformed")
            nonce, sequence, operation, offset, count = _FRAME_HEADER.unpack(hello)
            if sequence != 0 or operation != int(_Operation.HELLO) or offset != 0 or count != 0:
                raise InspectorFileIoUnavailable("fixed file I/O helper greeting is invalid")
            self._nonce = nonce
        except Exception:
            self._terminate_and_reap(reason="fixed file I/O helper did not become ready")
            raise

    def _send_frame(
        self,
        control: socket.socket,
        frame: bytes,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> None:
        ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [self._descriptor]))]
        while True:
            self._wait_for_control(
                control,
                readable=False,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
            try:
                sent = control.sendmsg([frame], ancillary)
            except BlockingIOError:
                continue
            if sent != len(frame):
                raise InspectorFileIoUnavailable("file I/O control packet was partial")
            return

    def _receive_frame(
        self,
        control: socket.socket,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> bytes:
        while True:
            self._wait_for_control(
                control,
                readable=True,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )
            try:
                payload = control.recv(_MAX_CONTROL_BYTES + _FRAME_HEADER.size + _SEAL_RECEIPT.size)
            except BlockingIOError:
                continue
            if not payload:
                raise InspectorFileIoUnavailable("fixed file I/O helper closed control")
            return payload

    def _wait_for_control(
        self,
        control: socket.socket,
        *,
        readable: bool,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> None:
        self._validate_wait(wait_is_current, heartbeat_interval_millis)
        while True:
            if wait_is_current is not None and not wait_is_current():
                raise ProtocolViolation("authority lost while waiting for fixed file I/O")
            timeout = deadline.remaining()
            if heartbeat_interval_millis is not None:
                timeout = min(timeout, heartbeat_interval_millis / 1_000)
            readable_fds, writable_fds, _ = select.select(
                [control] if readable else [], [control] if not readable else [], [], timeout
            )
            if readable_fds or writable_fds:
                return
            if wait_is_current is not None:
                if not wait_is_current():
                    raise ProtocolViolation("authority lost while waiting for fixed file I/O")
                continue
            deadline.remaining()

    @staticmethod
    def _validate_wait(
        wait_is_current: Callable[[], bool] | None, heartbeat_interval_millis: int | None
    ) -> None:
        if wait_is_current is not None and (
            type(heartbeat_interval_millis) is not int or heartbeat_interval_millis <= 0
        ):
            raise ValueError("heartbeat_interval_millis must be positive with a wait guard")

    def _terminate_and_reap(self, *, reason: str) -> None:
        control, self._control = self._control, None
        if control is not None:
            control.close()
        pid, pidfd = self._pid, self._pidfd
        self._pid = None
        self._pidfd = None
        if pid is None:
            return
        if pidfd is None:
            # Closing control causes the fixed child to exit without ever receiving
            # an artifact FD. Do not signal a numeric PID without a pidfd: another
            # reaper could make that identity unsafe. Retain unreaped ownership.
            try:
                reaped_pid, _status = os.waitpid(pid, os.WNOHANG)
            except OSError:
                reaped_pid = 0
            if reaped_pid == pid:
                return
            self._quarantined = True
            _QUARANTINE.retain(
                QuarantinedFileIoV1(pid=pid, pidfd=None, descriptor=None, reason=reason)
            )
            return
        _pidfd_send_kill(pidfd)
        if _waitid_pidfd_nonblocking(pidfd):
            os.close(pidfd)
            return
        self._quarantined = True
        _QUARANTINE.retain(
            QuarantinedFileIoV1(pid=pid, pidfd=pidfd, descriptor=self._descriptor, reason=reason)
        )

    def _reap_after_success(
        self,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> None:
        """Prove the one-operation helper exited before its ACK becomes state."""

        pidfd = self._pidfd
        if pidfd is None:
            raise InspectorFileIoUnavailable("file I/O helper pidfd is unavailable")
        try:
            while True:
                if wait_is_current is not None and not wait_is_current():
                    raise ProtocolViolation("authority lost while reaping fixed file I/O")
                timeout = deadline.remaining()
                if heartbeat_interval_millis is not None:
                    timeout = min(timeout, heartbeat_interval_millis / 1_000)
                readable, _, _ = select.select([pidfd], [], [], timeout)
                if readable and _waitid_pidfd_nonblocking(pidfd):
                    os.close(pidfd)
                    self._pidfd = None
                    self._pid = None
                    control, self._control = self._control, None
                    if control is not None:
                        control.close()
                    self._nonce = None
                    return
                if wait_is_current is not None:
                    if not wait_is_current():
                        raise ProtocolViolation("authority lost while reaping fixed file I/O")
                    continue
                deadline.remaining()
        except (ProtocolDeadlineExceeded, ProtocolViolation):
            self._terminate_and_reap(reason="file I/O helper did not reap within current authority")
            raise

    def _require_open(self) -> None:
        if self._closed or self._quarantined:
            raise InspectorFileIoUnavailable("file I/O ownership is no longer mutable")


def _maximum_payload_bytes() -> int:
    return _MAX_CONTROL_BYTES - _FRAME_HEADER.size


def _fixed_helper_file_actions(child_fd: int) -> list[tuple[int, int, int] | tuple[int, int]]:
    """Close inherited process descriptors before exposing only the control socket."""

    actions: list[tuple[int, int, int] | tuple[int, int]] = []
    for descriptor in _open_descriptor_numbers():
        if descriptor >= _CONTROL_FD and descriptor != child_fd:
            actions.append((os.POSIX_SPAWN_CLOSE, descriptor))
    if child_fd != _CONTROL_FD:
        actions.append((os.POSIX_SPAWN_DUP2, child_fd, _CONTROL_FD))
        actions.append((os.POSIX_SPAWN_CLOSE, child_fd))
    return actions


def _open_descriptor_numbers() -> tuple[int, ...]:
    """Return the Linux descriptor snapshot required by the pidfd helper contract."""

    try:
        return tuple(int(entry) for entry in os.listdir("/proc/self/fd") if entry.isdecimal())
    except OSError as exc:
        raise InspectorFileIoUnavailable("cannot enumerate helper descriptor inheritance") from exc


def _closed_helper_environment() -> dict[str, str]:
    """The helper receives no caller-provided environment or import target."""

    return {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"}


def _pidfd_open(pid: int) -> int:
    libc = ctypes.CDLL(None, use_errno=True)
    descriptor = libc.syscall(_SYS_PIDFD_OPEN, ctypes.c_int(pid), ctypes.c_uint(0))
    if descriptor < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return int(descriptor)


def _pidfd_send_kill(pidfd: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.syscall(
        _SYS_PIDFD_SEND_SIGNAL,
        ctypes.c_int(pidfd),
        ctypes.c_int(signal.SIGKILL),
        ctypes.c_void_p(),
        ctypes.c_uint(0),
    )
    if result < 0 and ctypes.get_errno() not in {errno.ESRCH}:
        return


def _waitid_pidfd_nonblocking(pidfd: int) -> bool:
    try:
        return os.waitid(_P_PIDFD, pidfd, os.WEXITED | os.WNOHANG) is not None
    except (ChildProcessError, OSError, ValueError):
        return False


__all__ = [
    "BoundedFileIo",
    "FileIoSealReceiptV1",
    "InspectorFileIoUnavailable",
    "QuarantinedFileIoV1",
    "quarantined_file_io",
]
