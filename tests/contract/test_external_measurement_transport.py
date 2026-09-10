"""Real UDS two-stream binding with shared deadlines and no raster interpretation."""

from __future__ import annotations

import hashlib
import socket
import time
from io import BytesIO

import pytest
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedMemorySink,
    ProtocolDeadline,
    ProtocolLimitsV1,
    ProtocolViolation,
)
from ksi_processing_controller.external_measurement_protocol import MeasurementInputV2
from ksi_processing_controller.external_measurement_transport import (
    MeasurementRequestReceiverV2,
    _read_measurement_input,
    write_measurement_request,
)
from test_external_measurement_protocol import launch_volume


def fixture_request():
    request = launch_volume()
    data = (b"baseline opaque bytes", b"current opaque bytes")
    volume = request.volume_request
    bindings = tuple(
        binding.model_copy(
            update={
                "observed_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "observed_size_bytes": len(raw),
            }
        )
        for binding, raw in zip((volume.baseline, volume.current), data, strict=True)
    )
    volume = volume.model_copy(
        update={"baseline": bindings[0], "current": bindings[1], "request_digest": None}
    ).sealed()
    inputs = tuple(
        MeasurementInputV2(
            role=original.role,
            artifact_id=binding.dsm_artifact_id,
            observed_sha256=binding.observed_sha256,
            observed_size_bytes=binding.observed_size_bytes,
        )
        for original, binding in zip(request.inputs, bindings, strict=True)
    )
    return request.model_copy(
        update={"inputs": inputs, "volume_request": volume, "canonical_input_digest": None}
    ).sealed(), data


def limits():
    return ProtocolLimitsV1(
        max_header_bytes=262144,
        max_chunk_bytes=4,
        max_input_bytes=1024,
        max_output_bytes=262144,
        max_wire_duration_millis=100,
    )


@pytest.mark.parametrize(
    "mutation", ["valid", "short_primary", "short_secondary", "hash", "trailing", "role_reversal"]
)
def test_two_opaque_inputs_exact_read(mutation: str) -> None:
    request, data = fixture_request()
    payload = b"".join(data)
    if mutation == "short_primary":
        payload = data[0][:-1]
    elif mutation == "short_secondary":
        payload = payload[:-1]
    elif mutation == "hash":
        payload = b"x" + payload[1:]
    elif mutation == "trailing":
        payload += b"x"
    elif mutation == "role_reversal":
        payload = data[1] + data[0]
    client, server = socket.socketpair()
    try:
        client.sendall(payload)
        client.shutdown(socket.SHUT_WR)
        sinks = (DeadlineBoundedMemorySink(), DeadlineBoundedMemorySink())
        deadline = ProtocolDeadline(100, time.monotonic)

        def receive():
            return tuple(
                _read_measurement_input(
                    server,
                    request,
                    index,
                    limits(),
                    sink,
                    deadline=deadline,
                    wait_is_current=lambda: True,
                    heartbeat_interval_millis=10,
                )
                for index, sink in enumerate(sinks)
            )

        if mutation == "valid":
            receipts = receive()
            assert tuple(receipt.observed_sha256 for receipt in receipts) == tuple(
                item.observed_sha256 for item in request.inputs
            )
            assert tuple(b"".join(sink.chunks) for sink in sinks) == data
        else:
            with pytest.raises(ProtocolViolation):
                receive()
    finally:
        client.close()
        server.close()


def test_writer_reader_roundtrip_and_canonical_header() -> None:
    request, data = fixture_request()
    client, server = socket.socketpair()
    try:
        write_measurement_request(
            client,
            request,
            (BytesIO(data[0]), BytesIO(data[1])),
            limits(),
            deadline=ProtocolDeadline(100, time.monotonic),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )
        receiver = MeasurementRequestReceiverV2(
            server, limits(), wait_is_current=lambda: True, heartbeat_interval_millis=10
        )
        assert receiver.read_header() == request
        for receive, raw in zip(
            (receiver.read_primary, receiver.read_secondary), data, strict=True
        ):
            sink = DeadlineBoundedMemorySink()
            receive(sink)
            assert b"".join(sink.chunks) == raw
        assert receiver.complete
    finally:
        client.close()
        server.close()


def test_no_eof_or_revoked_authority_never_accepts_input() -> None:
    request, data = fixture_request()
    client, server = socket.socketpair()
    try:
        client.sendall(data[1])
        started = time.monotonic()
        with pytest.raises(ProtocolViolation):
            _read_measurement_input(
                server,
                request,
                1,
                limits(),
                DeadlineBoundedMemorySink(),
                deadline=ProtocolDeadline(20, time.monotonic),
                wait_is_current=lambda: True,
                heartbeat_interval_millis=5,
            )
        assert time.monotonic() - started < 0.15
        with pytest.raises(ProtocolViolation):
            write_measurement_request(
                client,
                request,
                (BytesIO(data[0]), BytesIO(data[1])),
                limits(),
                deadline=ProtocolDeadline(100, time.monotonic),
                wait_is_current=lambda: False,
                heartbeat_interval_millis=5,
            )
    finally:
        client.close()
        server.close()
