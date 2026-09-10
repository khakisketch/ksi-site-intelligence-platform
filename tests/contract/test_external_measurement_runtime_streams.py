"""V2 can terminate stdin without discarding its terminal result or renewing time."""

import socket
import struct
import time
from typing import cast

import pytest
from ksi_processing_controller.external_inspector_docker import (
    DockerRuntimeUnavailable,
    UnixSocketDockerMultiplexSession,
)
from ksi_processing_controller.external_inspector_protocol import (
    ProtocolDeadline,
    ProtocolViolation,
)
from ksi_processing_controller.external_measurement_transport import MeasurementRequestReceiverV2
from test_external_measurement_transport import limits


def test_half_close_preserves_stdout_and_rejects_later_stdin() -> None:
    client, engine = socket.socketpair()
    session = UnixSocketDockerMultiplexSession(client)
    deadline = time.monotonic() + 1
    try:
        session.send_stdin(b"EXECUTE", deadline_monotonic=deadline)
        session.finish_stdin(deadline_monotonic=deadline)
        session.finish_stdin(deadline_monotonic=deadline)
        assert engine.recv(16) == b"EXECUTE"
        assert engine.recv(1) == b""
        engine.sendall(b"\x01\x00\x00\x00" + struct.pack("!I", 2) + b"ok")
        assert session.read_frame(
            maximum_stdout_bytes=4, maximum_stderr_bytes=0, deadline_monotonic=deadline
        ) == (1, b"ok")
        with pytest.raises(DockerRuntimeUnavailable):
            session.send_stdin(b"extra", deadline_monotonic=deadline)
        session.close()
        with pytest.raises(DockerRuntimeUnavailable):
            session.finish_stdin(deadline_monotonic=deadline)
    finally:
        session.close()
        engine.close()


def test_expired_stdin_finish_does_not_half_close() -> None:
    client, engine = socket.socketpair()
    session = UnixSocketDockerMultiplexSession(client)
    try:
        with pytest.raises(DockerRuntimeUnavailable):
            session.finish_stdin(deadline_monotonic=time.monotonic() - 1)
        session.send_stdin(b"x", deadline_monotonic=time.monotonic() + 1)
        assert engine.recv(1) == b"x"
    finally:
        session.close()
        engine.close()


def test_absolute_clamp_never_renews_original_budget() -> None:
    clock = [0.0]
    deadline = ProtocolDeadline(100, lambda: clock[0])
    clock[0] = 0.03
    deadline.cap_expires_at(0.05)
    assert deadline.expires_at == 0.05
    deadline.cap_expires_at(0.09)
    assert deadline.expires_at == 0.05
    clock[0] = 0.051
    with pytest.raises(ProtocolViolation):
        deadline.remaining()


@pytest.mark.parametrize("invalid", [True, float("inf"), float("nan"), "0.1"])
def test_absolute_clamp_rejects_invalid_expiry(invalid: object) -> None:
    deadline = ProtocolDeadline(100, lambda: 0.0)
    with pytest.raises(ValueError):
        deadline.cap_expires_at(cast(float, invalid))
    assert deadline.expires_at == 0.1


def test_receiver_cap_includes_elapsed_header_time() -> None:
    clock = [0.0]
    client, server = socket.socketpair()
    try:
        receiver = MeasurementRequestReceiverV2(
            server,
            limits(),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
            monotonic=lambda: clock[0],
        )
        clock[0] = 0.03
        receiver.restrict_total_duration_millis(50)
        assert receiver.deadline.expires_at == 0.05
        receiver.restrict_total_duration_millis(100)
        assert receiver.deadline.expires_at == 0.05
    finally:
        client.close()
        server.close()
