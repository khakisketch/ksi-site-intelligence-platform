"""One receiver owns the complete ordered transaction and absolute time budget."""

import socket
import struct

import pytest
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedMemorySink,
    ProtocolViolation,
)
from ksi_processing_controller.external_measurement_protocol import MeasurementLaunchRequestV2
from ksi_processing_controller.external_measurement_transport import MeasurementRequestReceiverV2
from test_external_measurement_transport import fixture_request, limits


def wire(request: MeasurementLaunchRequestV2, data: tuple[bytes, bytes]) -> bytes:
    header = request.canonical_bytes()
    return struct.pack("!I", len(header)) + header + b"".join(data)


@pytest.mark.parametrize(
    "wrong",
    [
        "secondary_first",
        "primary_before_header",
        "header_twice",
        "primary_twice",
        "secondary_twice",
    ],
)
def test_receiver_rejects_out_of_sequence_calls(wrong: str) -> None:
    request, data = fixture_request()
    client, server = socket.socketpair()
    try:
        client.sendall(wire(request, data))
        client.shutdown(socket.SHUT_WR)
        receiver = MeasurementRequestReceiverV2(
            server, limits(), wait_is_current=lambda: True, heartbeat_interval_millis=10
        )
        sink = DeadlineBoundedMemorySink()
        if wrong not in {"secondary_first", "primary_before_header"}:
            receiver.read_header()
        if wrong in {"primary_twice", "secondary_twice"}:
            receiver.read_primary(sink)
        if wrong == "secondary_twice":
            receiver.read_secondary(sink)
        with pytest.raises(ProtocolViolation, match="sequence"):
            if wrong == "header_twice":
                receiver.read_header()
            elif wrong in {"secondary_first", "secondary_twice"}:
                receiver.read_secondary(sink)
            else:
                receiver.read_primary(sink)
        assert receiver.complete is False
    finally:
        client.close()
        server.close()


def test_receiver_reuses_original_absolute_deadline_after_staging_pause() -> None:
    request, data = fixture_request()
    clock = [0.0]
    client, server = socket.socketpair()
    try:
        client.sendall(wire(request, data))
        client.shutdown(socket.SHUT_WR)
        receiver = MeasurementRequestReceiverV2(
            server,
            limits(),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
            monotonic=lambda: clock[0],
        )
        assert receiver.read_header() == request
        receiver.read_primary(DeadlineBoundedMemorySink())
        clock[0] = 0.101
        with pytest.raises(ProtocolViolation):
            receiver.read_secondary(DeadlineBoundedMemorySink())
        assert not receiver.complete
        with pytest.raises(ProtocolViolation, match="sequence"):
            receiver.read_secondary(DeadlineBoundedMemorySink())
    finally:
        client.close()
        server.close()


@pytest.mark.parametrize("trailing", [b"", b"x"])
def test_receiver_acceptance_requires_secondary_and_terminal_eof(trailing: bytes) -> None:
    request, data = fixture_request()
    client, server = socket.socketpair()
    try:
        client.sendall(wire(request, data) + trailing)
        client.shutdown(socket.SHUT_WR)
        receiver = MeasurementRequestReceiverV2(
            server, limits(), wait_is_current=lambda: True, heartbeat_interval_millis=10
        )
        receiver.read_header()
        receiver.read_primary(DeadlineBoundedMemorySink())
        assert not receiver.complete
        if trailing:
            with pytest.raises(ProtocolViolation):
                receiver.read_secondary(DeadlineBoundedMemorySink())
            assert not receiver.complete
        else:
            receipt = receiver.read_secondary(DeadlineBoundedMemorySink())
            assert receipt.observed_sha256 == request.inputs[1].observed_sha256
            assert receiver.complete
    finally:
        client.close()
        server.close()
