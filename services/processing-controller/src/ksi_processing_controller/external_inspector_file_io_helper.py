"""Fixed child entrypoint for :mod:`external_inspector_file_io`.

It receives one FD by ``SCM_RIGHTS`` for every request and never opens a path.
The parent validates all acknowledgements before changing any byte accounting.
"""

from __future__ import annotations

import array
import ctypes
import hashlib
import os
import signal
import socket
import struct

_CONTROL_FD = 3
_MAX_CONTROL_BYTES = 60 * 1024
_FRAME_HEADER = struct.Struct("!16sQBQI")
_SEAL_RECEIPT = struct.Struct("!QQQIIQQ32s")
_HELLO = 1
_WRITE = 2
_READ = 3
_SEAL = 4
_CLOSE = 5
_VERIFY = 6
_ERROR = 255
_PR_SET_PDEATHSIG = 1


def main() -> int:
    if not _arm_parent_death_kill():
        return 3
    control = socket.socket(fileno=_CONTROL_FD)
    nonce = os.urandom(16)
    control.send(_FRAME_HEADER.pack(nonce, 0, _HELLO, 0, 0))
    while True:
        payload, ancillary, flags, _address = control.recvmsg(
            _MAX_CONTROL_BYTES + _FRAME_HEADER.size,
            socket.CMSG_SPACE(array.array("i", [0]).itemsize),
        )
        if flags & socket.MSG_TRUNC or len(payload) < _FRAME_HEADER.size:
            return 2
        frame_nonce, sequence, operation, offset, count = _FRAME_HEADER.unpack(
            payload[: _FRAME_HEADER.size]
        )
        fd = _single_received_fd(ancillary)
        try:
            if frame_nonce != nonce:
                _send_error(control, nonce, sequence)
                continue
            if operation == _CLOSE:
                if (
                    fd is not None
                    or offset != 0
                    or count != 0
                    or len(payload) != _FRAME_HEADER.size
                ):
                    _send_error(control, nonce, sequence)
                    continue
                control.send(_FRAME_HEADER.pack(nonce, sequence, _CLOSE, 0, 0))
                return 0
            if fd is None or offset < 0 or count < 0:
                _send_error(control, nonce, sequence)
                continue
            body = payload[_FRAME_HEADER.size :]
            if operation == _WRITE:
                if len(body) != count:
                    _send_error(control, nonce, sequence)
                    continue
                _write_exact(fd, body, offset)
                control.send(_FRAME_HEADER.pack(nonce, sequence, _WRITE, offset, count))
                return 0
            if operation == _READ:
                if body or count > _MAX_CONTROL_BYTES - _FRAME_HEADER.size:
                    _send_error(control, nonce, sequence)
                    continue
                chunk = os.pread(fd, count, offset)
                control.send(_FRAME_HEADER.pack(nonce, sequence, _READ, offset, len(chunk)) + chunk)
                return 0
            if operation == _SEAL:
                if body:
                    _send_error(control, nonce, sequence)
                    continue
                os.fsync(fd)
                status = os.fstat(fd)
                digest = _digest_fd(fd, status.st_size)
                if status.st_size != count:
                    _send_error(control, nonce, sequence)
                    continue
                receipt = _SEAL_RECEIPT.pack(
                    status.st_dev,
                    status.st_ino,
                    status.st_mode,
                    status.st_uid,
                    status.st_gid,
                    status.st_nlink,
                    status.st_size,
                    digest,
                )
                control.send(_FRAME_HEADER.pack(nonce, sequence, _SEAL, offset, count) + receipt)
                return 0
            if operation == _VERIFY:
                if body:
                    _send_error(control, nonce, sequence)
                    continue
                status = os.fstat(fd)
                digest = _digest_fd(fd, status.st_size)
                if status.st_size != count or os.pread(fd, 1, count):
                    _send_error(control, nonce, sequence)
                    continue
                receipt = _SEAL_RECEIPT.pack(
                    status.st_dev,
                    status.st_ino,
                    status.st_mode,
                    status.st_uid,
                    status.st_gid,
                    status.st_nlink,
                    status.st_size,
                    digest,
                )
                control.send(_FRAME_HEADER.pack(nonce, sequence, _VERIFY, offset, count) + receipt)
                return 0
            _send_error(control, nonce, sequence)
        except OSError:
            _send_error(control, nonce, sequence)
        finally:
            if fd is not None:
                os.close(fd)


def _single_received_fd(ancillary: list[tuple[int, int, bytes]]) -> int | None:
    descriptors: list[int] = []
    for level, kind, data in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            received = array.array("i")
            received.frombytes(data[: len(data) - (len(data) % received.itemsize)])
            descriptors.extend(received)
    if len(descriptors) != 1:
        for descriptor in descriptors:
            os.close(descriptor)
        return None
    return descriptors[0]


def _arm_parent_death_kill() -> bool:
    """Close the parent-death race before exposing the byte-I/O control socket."""

    original_parent = os.getppid()
    if original_parent <= 1:
        return False
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.prctl(ctypes.c_int(_PR_SET_PDEATHSIG), ctypes.c_ulong(signal.SIGKILL))
    if result != 0:
        return False
    return os.getppid() == original_parent


def _write_exact(descriptor: int, payload: bytes, offset: int) -> None:
    view = memoryview(payload)
    current = offset
    while view:
        written = os.pwrite(descriptor, view, current)
        if written <= 0:
            raise OSError("pwrite did not advance")
        current += written
        view = view[written:]


def _digest_fd(descriptor: int, size: int) -> bytes:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(65_536, size - offset), offset)
        if not chunk:
            raise OSError("readback ended before fstat size")
        digest.update(chunk)
        offset += len(chunk)
    return digest.digest()


def _send_error(control: socket.socket, nonce: bytes, sequence: int) -> None:
    control.send(_FRAME_HEADER.pack(nonce, sequence, _ERROR, 0, 0))


if __name__ == "__main__":  # pragma: no cover - exercised through posix_spawn
    raise SystemExit(main())
