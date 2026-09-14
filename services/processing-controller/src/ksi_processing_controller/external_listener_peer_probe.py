"""Out-of-band AF_UNIX peer-credential diagnostic receipt.

The probe is identified solely by a fresh abstract client address.  It never
reads an application request byte, so the signed inspector and measurement
wire grammars remain untouched.  A daemon may answer it only after proving its
activated listener ACL receipt for that dispatch.
"""

from __future__ import annotations

import hashlib
import os
import socket
import struct
import time
from dataclasses import dataclass
from pathlib import Path

_PREFIX = b"\x00ksi-peer-receipt-v1/"
_RESPONSE_PREFIX = b"KSI-PEER-RECEIPT-v1\x00"
_CHALLENGE_BYTES = 24
_SOCKET_BINDING_BYTES = 16
_CREDENTIAL_BYTES = struct.calcsize("3i")
_RESPONSE_BYTES = len(_RESPONSE_PREFIX) + _CHALLENGE_BYTES + _CREDENTIAL_BYTES
_LANES = {"INSPECTION": b"I", "MEASUREMENT": b"M"}


class ListenerPeerProbeUnavailable(RuntimeError):
    """The diagnostic receipt is absent, malformed, stale, or identity-mismatched."""


@dataclass(frozen=True, slots=True)
class ActivatedListenerPeerReceiptV1:
    lane: str
    socket_path: Path
    observed_worker_pid: int
    observed_worker_uid: int
    observed_worker_gid: int
    observed_server_pid: int
    observed_server_uid: int
    observed_server_gid: int


def probe_activated_listener_peer(
    *,
    lane: str,
    socket_path: Path,
    expected_server_uid: int,
    expected_server_gid: int,
    deadline_monotonic: float,
) -> ActivatedListenerPeerReceiptV1:
    """Obtain one fresh receipt as the worker without sending a request frame."""
    lane_code = _lane_code(lane)
    _validate_identity(expected_server_uid, expected_server_gid)
    challenge = os.urandom(_CHALLENGE_BYTES)
    address = _probe_address(lane_code, socket_path, challenge)
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        _set_deadline(connection, deadline_monotonic)
        connection.bind(address)
        connection.connect(os.fspath(socket_path))
        server_pid, server_uid, server_gid = _credentials(connection)
        if (
            server_pid <= 0
            or server_uid != expected_server_uid
            or server_gid != expected_server_gid
        ):
            raise ListenerPeerProbeUnavailable(
                "server credential does not match the listener owner"
            )
        response = _read_exact(connection, _RESPONSE_BYTES, deadline_monotonic)
        if response[: len(_RESPONSE_PREFIX)] != _RESPONSE_PREFIX:
            raise ListenerPeerProbeUnavailable("peer receipt response is invalid")
        offset = len(_RESPONSE_PREFIX)
        if response[offset : offset + _CHALLENGE_BYTES] != challenge:
            raise ListenerPeerProbeUnavailable("peer receipt challenge is invalid")
        worker_pid, worker_uid, worker_gid = struct.unpack_from(
            "3i", response, offset + _CHALLENGE_BYTES
        )
        if (worker_pid, worker_uid, worker_gid) != (os.getpid(), os.geteuid(), os.getegid()):
            raise ListenerPeerProbeUnavailable("server observed worker credential is invalid")
        return ActivatedListenerPeerReceiptV1(
            lane=lane,
            socket_path=socket_path,
            observed_worker_pid=worker_pid,
            observed_worker_uid=worker_uid,
            observed_worker_gid=worker_gid,
            observed_server_pid=server_pid,
            observed_server_uid=server_uid,
            observed_server_gid=server_gid,
        )
    except (OSError, struct.error, TimeoutError) as exc:
        raise ListenerPeerProbeUnavailable("peer receipt probe is unavailable") from exc
    finally:
        connection.close()


def respond_to_listener_peer_probe(
    connection: socket.socket,
    *,
    lane: str,
    socket_path: Path,
    expected_worker_uid: int,
    expected_server_uid: int,
    expected_server_gid: int,
    deadline_monotonic: float,
) -> bool:
    """Answer only a fresh exact probe; ordinary request bytes remain unread."""
    lane_code = _lane_code(lane)
    _validate_identity(expected_worker_uid)
    _validate_identity(expected_server_uid, expected_server_gid)
    if os.geteuid() != expected_server_uid or os.getegid() != expected_server_gid:
        raise ListenerPeerProbeUnavailable("daemon identity does not match the listener owner")
    peer_address = connection.getpeername()
    expected_prefix = _PREFIX + lane_code + _socket_binding(socket_path)
    if not isinstance(peer_address, bytes) or not peer_address.startswith(_PREFIX):
        return False
    if len(peer_address) != len(expected_prefix) + _CHALLENGE_BYTES:
        raise ListenerPeerProbeUnavailable("peer receipt address is malformed")
    if peer_address[: len(expected_prefix)] != expected_prefix:
        raise ListenerPeerProbeUnavailable("peer receipt lane or socket binding is invalid")
    worker_pid, worker_uid, worker_gid = _credentials(connection)
    if worker_pid <= 0 or worker_uid != expected_worker_uid or worker_gid < 0:
        raise ListenerPeerProbeUnavailable("peer receipt worker credential is invalid")
    challenge = peer_address[-_CHALLENGE_BYTES:]
    _set_deadline(connection, deadline_monotonic)
    try:
        connection.sendall(
            _RESPONSE_PREFIX + challenge + struct.pack("3i", worker_pid, worker_uid, worker_gid)
        )
    except (OSError, struct.error, TimeoutError) as exc:
        raise ListenerPeerProbeUnavailable("peer receipt response is unavailable") from exc
    return True


def _lane_code(lane: str) -> bytes:
    try:
        return _LANES[lane]
    except KeyError as exc:
        raise ListenerPeerProbeUnavailable("peer receipt lane is invalid") from exc


def _socket_binding(socket_path: Path) -> bytes:
    return hashlib.sha256(os.fsencode(socket_path)).digest()[:_SOCKET_BINDING_BYTES]


def _probe_address(lane_code: bytes, socket_path: Path, challenge: bytes) -> bytes:
    if len(challenge) != _CHALLENGE_BYTES:
        raise ListenerPeerProbeUnavailable("peer receipt challenge is invalid")
    return _PREFIX + lane_code + _socket_binding(socket_path) + challenge


def _credentials(connection: socket.socket) -> tuple[int, int, int]:
    if not hasattr(socket, "SO_PEERCRED"):
        raise ListenerPeerProbeUnavailable("SO_PEERCRED is unavailable")
    try:
        raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, _CREDENTIAL_BYTES)
        return struct.unpack("3i", raw)
    except (OSError, struct.error) as exc:
        raise ListenerPeerProbeUnavailable("peer credential is unavailable") from exc


def _set_deadline(connection: socket.socket, deadline_monotonic: float) -> None:
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise ListenerPeerProbeUnavailable("peer receipt deadline elapsed")
    connection.settimeout(remaining)


def _read_exact(connection: socket.socket, expected: int, deadline_monotonic: float) -> bytes:
    chunks: list[bytes] = []
    observed = 0
    while observed < expected:
        _set_deadline(connection, deadline_monotonic)
        chunk = connection.recv(expected - observed)
        if not chunk:
            raise ListenerPeerProbeUnavailable("peer receipt response ended early")
        chunks.append(chunk)
        observed += len(chunk)
    return b"".join(chunks)


def _validate_identity(uid: int, gid: int | None = None) -> None:
    if type(uid) is not int or uid < 0 or (gid is not None and (type(gid) is not int or gid < 0)):
        raise ListenerPeerProbeUnavailable("peer receipt identity is invalid")


__all__ = [
    "ActivatedListenerPeerReceiptV1",
    "ListenerPeerProbeUnavailable",
    "probe_activated_listener_peer",
    "respond_to_listener_peer_probe",
]
