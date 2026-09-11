"""Contract tests for the non-request UDS peer-credential diagnostic probe."""

from __future__ import annotations

import hashlib
import os
import socket
import struct
import threading
import time
from collections import deque
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

import pytest
from ksi_processing_controller.external_listener_peer_probe import (
    ListenerPeerProbeUnavailable,
    probe_activated_listener_peer,
    respond_to_listener_peer_probe,
)


def test_peer_probe_returns_server_observed_worker_credentials_without_reading_frames(
    tmp_path: Path,
) -> None:
    path = tmp_path / "inspection.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    listener.listen(1)
    listener.settimeout(2)
    server_errors: list[BaseException] = []

    def server() -> None:
        try:
            connection, _address = listener.accept()
            with connection:
                assert respond_to_listener_peer_probe(
                    connection,
                    lane="INSPECTION",
                    socket_path=path,
                    expected_worker_uid=os.geteuid(),
                    expected_server_uid=os.geteuid(),
                    expected_server_gid=os.getegid(),
                    deadline_monotonic=time.monotonic() + 1,
                )
        except BaseException as exc:  # test thread must surface an unexpected server failure.
            server_errors.append(exc)

    thread = threading.Thread(target=server)
    thread.start()
    try:
        receipt = probe_activated_listener_peer(
            lane="INSPECTION",
            socket_path=path,
            expected_server_uid=os.geteuid(),
            expected_server_gid=os.getegid(),
            deadline_monotonic=time.monotonic() + 1,
        )
    finally:
        # Let the bounded accept finish before closing a successfully queued connection.
        thread.join(timeout=3)
        listener.close()
        thread.join(timeout=3)
        assert not thread.is_alive(), "peer fixture thread did not terminate"

    assert server_errors == []
    assert receipt.lane == "INSPECTION"
    assert receipt.socket_path == path
    assert receipt.observed_worker_uid == os.geteuid()
    assert receipt.observed_worker_gid == os.getegid()


def test_peer_probe_never_consumes_an_ordinary_request_frame(tmp_path: Path) -> None:
    path = tmp_path / "measurement.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    listener.listen(1)
    listener.settimeout(2)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.connect(os.fspath(path))
        client.sendall(b"ordinary-framed-request-prefix")
        connection, _address = listener.accept()
        with connection:
            assert not respond_to_listener_peer_probe(
                connection,
                lane="MEASUREMENT",
                socket_path=path,
                expected_worker_uid=os.geteuid(),
                expected_server_uid=os.geteuid(),
                expected_server_gid=os.getegid(),
                deadline_monotonic=time.monotonic() + 1,
            )
            assert connection.recv(64) == b"ordinary-framed-request-prefix"
    finally:
        client.close()
        listener.close()


def test_peer_probe_rejects_a_server_with_wrong_kernel_identity(tmp_path: Path) -> None:
    path = tmp_path / "inspection.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    listener.listen(1)
    listener.settimeout(2)

    def server() -> None:
        connection, _address = listener.accept()
        with connection, suppress(ListenerPeerProbeUnavailable):
            respond_to_listener_peer_probe(
                connection,
                lane="INSPECTION",
                socket_path=path,
                expected_worker_uid=os.geteuid(),
                expected_server_uid=os.geteuid(),
                expected_server_gid=os.getegid(),
                deadline_monotonic=time.monotonic() + 1,
            )  # The client closes immediately after rejecting the wrong daemon UID.

    thread = threading.Thread(target=server)
    thread.start()
    try:
        with pytest.raises(ListenerPeerProbeUnavailable, match="server credential"):
            probe_activated_listener_peer(
                lane="INSPECTION",
                socket_path=path,
                expected_server_uid=os.geteuid() + 1,
                expected_server_gid=os.getegid(),
                deadline_monotonic=time.monotonic() + 1,
            )
    finally:
        # Let the bounded accept finish before closing a successfully queued connection.
        thread.join(timeout=3)
        listener.close()
        thread.join(timeout=3)
        assert not thread.is_alive(), "peer fixture thread did not terminate"


def test_peer_probe_rejects_a_connect_only_listener_that_never_replies(tmp_path: Path) -> None:
    """A completed UDS connect is not a peer-credential receipt."""
    path = tmp_path / "connect-only.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    listener.listen(1)
    listener.settimeout(2)

    def server() -> None:
        connection, _address = listener.accept()
        with connection:
            time.sleep(0.15)

    thread = threading.Thread(target=server)
    thread.start()
    try:
        with pytest.raises(ListenerPeerProbeUnavailable, match="unavailable"):
            probe_activated_listener_peer(
                lane="INSPECTION",
                socket_path=path,
                expected_server_uid=os.geteuid(),
                expected_server_gid=os.getegid(),
                deadline_monotonic=time.monotonic() + 0.05,
            )
    finally:
        # Let the bounded accept finish before closing a successfully queued connection.
        thread.join(timeout=3)
        listener.close()
        thread.join(timeout=3)
        assert not thread.is_alive(), "peer fixture thread did not terminate"


def test_peer_probe_rejects_a_replayed_challenge(tmp_path: Path) -> None:
    """A receipt captured from an earlier connection cannot authenticate a new probe."""
    path = tmp_path / "replayed.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    listener.listen(2)
    listener.settimeout(2)
    previous_challenge: list[bytes] = []
    server_errors: list[BaseException] = []

    def server() -> None:
        try:
            first, first_address = listener.accept()
            with first:
                assert isinstance(first_address, bytes)
                previous_challenge.append(first_address[-24:])
            second, second_address = listener.accept()
            with second:
                assert isinstance(second_address, bytes)
                worker = second.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                second.sendall(b"KSI-PEER-RECEIPT-v1\x00" + previous_challenge[0] + worker)
        except BaseException as exc:
            server_errors.append(exc)

    thread = threading.Thread(target=server)
    thread.start()
    prior = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        prior.bind(b"\x00ksi-peer-receipt-replay-source")
        prior.connect(os.fspath(path))
        prior.close()
        with pytest.raises(ListenerPeerProbeUnavailable, match="challenge"):
            probe_activated_listener_peer(
                lane="INSPECTION",
                socket_path=path,
                expected_server_uid=os.geteuid(),
                expected_server_gid=os.getegid(),
                deadline_monotonic=time.monotonic() + 1,
            )
    finally:
        prior.close()
        # Let the bounded accept finish before closing a successfully queued connection.
        thread.join(timeout=3)
        listener.close()
        thread.join(timeout=3)
        assert not thread.is_alive(), "peer fixture thread did not terminate"

    assert server_errors == []


def test_peer_probe_rejects_a_wrong_challenge(tmp_path: Path) -> None:
    """A response that does not echo this connection's challenge is unusable."""
    path = tmp_path / "wrong-challenge.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    listener.listen(1)
    listener.settimeout(2)
    server_errors: list[BaseException] = []

    def server() -> None:
        try:
            connection, _address = listener.accept()
            with connection:
                worker = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
                connection.sendall(b"KSI-PEER-RECEIPT-v1\x00" + b"x" * 24 + worker)
        except BaseException as exc:
            server_errors.append(exc)

    thread = threading.Thread(target=server)
    thread.start()
    try:
        with pytest.raises(ListenerPeerProbeUnavailable, match="challenge"):
            probe_activated_listener_peer(
                lane="INSPECTION",
                socket_path=path,
                expected_server_uid=os.geteuid(),
                expected_server_gid=os.getegid(),
                deadline_monotonic=time.monotonic() + 1,
            )
    finally:
        # Let the bounded accept finish before closing a successfully queued connection.
        thread.join(timeout=3)
        listener.close()
        thread.join(timeout=3)
        assert not thread.is_alive(), "peer fixture thread did not terminate"

    assert server_errors == []


def test_peer_probe_rejects_a_forged_worker_credential_receipt(tmp_path: Path) -> None:
    """The client rejects a server payload that does not echo its kernel credentials."""
    path = tmp_path / "forged-worker.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    listener.listen(1)
    listener.settimeout(2)
    server_errors: list[BaseException] = []

    def server() -> None:
        try:
            connection, address = listener.accept()
            with connection:
                assert isinstance(address, bytes)
                challenge = address[-24:]
                connection.sendall(
                    b"KSI-PEER-RECEIPT-v1\x00"
                    + challenge
                    + struct.pack("3i", os.getpid(), os.geteuid() + 1, os.getegid())
                )
        except BaseException as exc:
            server_errors.append(exc)

    thread = threading.Thread(target=server)
    thread.start()
    try:
        with pytest.raises(ListenerPeerProbeUnavailable, match="worker credential"):
            probe_activated_listener_peer(
                lane="INSPECTION",
                socket_path=path,
                expected_server_uid=os.geteuid(),
                expected_server_gid=os.getegid(),
                deadline_monotonic=time.monotonic() + 1,
            )
    finally:
        # Let the bounded accept finish before closing a successfully queued connection.
        thread.join(timeout=3)
        listener.close()
        thread.join(timeout=3)
        assert not thread.is_alive(), "peer fixture thread did not terminate"

    assert server_errors == []


@pytest.mark.parametrize(
    ("peer_lane", "bound_socket_name"),
    [(b"M", "inspection.sock"), (b"I", "other.sock")],
    ids=["wrong-lane", "wrong-socket-binding"],
)
def test_daemon_rejects_peer_probe_with_wrong_lane_or_socket_binding(
    tmp_path: Path, peer_lane: bytes, bound_socket_name: str
) -> None:
    """The daemon only trusts the exact lane and listener identity it activated."""
    path = tmp_path / "inspection.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    listener.listen(1)
    listener.settimeout(2)
    server_errors: list[BaseException] = []

    def server() -> None:
        try:
            connection, _address = listener.accept()
            with connection, pytest.raises(
                ListenerPeerProbeUnavailable, match="lane or socket binding"
            ):
                respond_to_listener_peer_probe(
                    connection,
                    lane="INSPECTION",
                    socket_path=path,
                    expected_worker_uid=os.geteuid(),
                    expected_server_uid=os.geteuid(),
                    expected_server_gid=os.getegid(),
                    deadline_monotonic=time.monotonic() + 1,
                )
        except BaseException as exc:
            server_errors.append(exc)

    thread = threading.Thread(target=server)
    thread.start()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        binding_path = tmp_path / bound_socket_name
        binding = hashlib.sha256(os.fsencode(binding_path)).digest()[:16]
        client.bind(b"\x00ksi-peer-receipt-v1/" + peer_lane + binding + b"x" * 24)
        client.connect(os.fspath(path))
    finally:
        client.close()
        # Let the bounded accept finish before closing a successfully queued connection.
        thread.join(timeout=3)
        listener.close()
        thread.join(timeout=3)
        assert not thread.is_alive(), "peer fixture thread did not terminate"

    assert server_errors == []


@pytest.mark.parametrize(
    ("lane", "daemon_kind"),
    [("INSPECTION", "inspector"), ("MEASUREMENT", "measurement")],
)
def test_daemon_answers_peer_probe_after_acl_reproof_without_launcher_dispatch(
    tmp_path: Path, lane: str, daemon_kind: str
) -> None:
    """The diagnostic lane does not enter a signed request parser or backend graph."""
    from ksi_processing_controller.external_inspector_daemon import (
        ExternalInspectorSystemdDaemon,
        SystemdActivatedListenerConfigV1,
        prove_activated_listener,
    )
    from ksi_processing_controller.external_measurement_daemon import (
        ExternalMeasurementSystemdDaemon,
    )

    path = tmp_path / f"{lane.lower()}.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(os.fspath(path))
    path.chmod(0o600)
    listener.listen(1)
    listener.settimeout(2)
    receipt = prove_activated_listener(
        listener,
        SystemdActivatedListenerConfigV1(path, os.geteuid()),
        required_worker_uid=os.geteuid(),
        deadline_monotonic=time.monotonic() + 1,
    )
    dispatched: list[socket.socket] = []

    class Launcher:
        def handle_connection(self, connection: socket.socket) -> None:
            dispatched.append(connection)
            connection.close()

    daemon_type = (
        ExternalInspectorSystemdDaemon
        if daemon_kind == "inspector"
        else ExternalMeasurementSystemdDaemon
    )
    daemon = daemon_type(
        listener=receipt.listener,
        launcher=cast(Any, Launcher()),
        preaccepted=deque(receipt.preaccepted),
        activated_listener=receipt,
        proof_timeout_millis=500,
    )
    errors: list[BaseException] = []

    def serve() -> None:
        try:
            daemon.serve_once()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        response = probe_activated_listener_peer(
            lane=lane,
            socket_path=path,
            expected_server_uid=os.geteuid(),
            expected_server_gid=os.getegid(),
            deadline_monotonic=time.monotonic() + 1,
        )
    finally:
        daemon.close()
        # Let the bounded accept finish before closing a successfully queued connection.
        thread.join(timeout=3)
        listener.close()
        thread.join(timeout=3)
        assert not thread.is_alive(), "daemon fixture thread did not terminate"

    assert errors == []
    assert response.observed_worker_uid == os.geteuid()
    assert dispatched == []
