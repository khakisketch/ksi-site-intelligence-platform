"""Real local UDS identity and bounded V2 result framing."""

import os
import socket

import pytest
from ksi_processing_controller.external_inspector_protocol import (
    ProtocolDeadline,
    ProtocolViolation,
)
from ksi_processing_controller.external_measurement_client import (
    FixedMeasurementUdsConnector,
    MeasurementSocketIdentityV2,
)


def connector(path, uid=None):
    return FixedMeasurementUdsConnector(
        MeasurementSocketIdentityV2(
            path=path,
            owner_uid=os.getuid(),
            owner_gid=os.getgid(),
            mode=0o600,
            launcher_uid=os.getuid() if uid is None else uid,
        )
    )


@pytest.mark.parametrize(
    "failure", [None, "peer", "mode", "cancel", "expired", "symlink", "truthy"]
)
def test_actual_uds_connector_requires_owned_socket_and_live_authority(tmp_path, failure):
    path = tmp_path / "measurement.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    os.chmod(path, 0o600)
    listener.listen(1)
    target = path
    if failure == "mode":
        os.chmod(path, 0o666)
    if failure == "symlink":
        target = tmp_path / "alias.sock"
        target.symlink_to(path)
    value = connector(target, os.getuid() + 1 if failure == "peer" else None)
    clock = [0.0]
    deadline = ProtocolDeadline(1000, lambda: clock[0])
    if failure == "expired":
        clock[0] = 2.0
    try:
        if failure is None:
            connection = value.connect(
                deadline=deadline, wait_is_current=lambda: True, heartbeat_interval_millis=10
            )
            peer, _ = listener.accept()
            connection.close()
            peer.close()
        else:
            with pytest.raises((ProtocolViolation, TimeoutError)):
                value.connect(
                    deadline=deadline,
                    wait_is_current=lambda: "yes" if failure == "truthy" else failure != "cancel",
                    heartbeat_interval_millis=10,
                )
    finally:
        listener.close()


@pytest.mark.parametrize("failure", [None, "trailing", "wrong_request", "missing_eof", "authority"])
def test_client_owns_one_deadline_and_requires_bound_terminal_eof(tmp_path, failure):
    import hashlib
    import struct
    import threading
    import time
    from io import BytesIO

    from ksi_processing_controller.external_inspector_protocol import (
        DeadlineBoundedMemorySink,
        ProtocolDeadlineExceeded,
    )
    from ksi_processing_controller.external_measurement_client import ExternalMeasurementUdsClient
    from ksi_processing_controller.external_measurement_container_protocol import (
        build_failed_frame_v2,
        build_prepare_frame_v2,
    )
    from ksi_processing_controller.external_measurement_result import build_measurement_result
    from ksi_processing_controller.external_measurement_transport import (
        MeasurementRequestReceiverV2,
    )
    from test_external_measurement_protocol import limits, measurement_manifest_request

    manifest, request = measurement_manifest_request()
    data = (b"baseline", b"current")
    inputs = tuple(
        item.model_copy(
            update={
                "observed_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "observed_size_bytes": len(raw),
            }
        )
        for item, raw in zip(request.inputs, data, strict=True)
    )
    bindings = [
        binding.model_copy(
            update={
                "observed_sha256": item.observed_sha256,
                "observed_size_bytes": item.observed_size_bytes,
            }
        )
        for binding, item in zip(
            (request.volume_request.baseline, request.volume_request.current), inputs, strict=True
        )
    ]
    volume = request.volume_request.model_copy(
        update={"baseline": bindings[0], "current": bindings[1], "request_digest": None}
    ).sealed()
    request = request.model_copy(
        update={"inputs": inputs, "volume_request": volume, "canonical_input_digest": None}
    ).sealed()
    terminal = build_failed_frame_v2(
        prepare=build_prepare_frame_v2(request=request, manifest=manifest),
        reason="INSUFFICIENT_COMMON_VALID_COVERAGE",
    )
    result = build_measurement_result(
        terminal=terminal, request=request, manifest=manifest, limits=limits()
    )
    payload = result.canonical_bytes(request=request, manifest=manifest, limits=limits())
    if failure == "wrong_request":
        payload = payload.replace(request.request_id.encode(), b"foreign-request")
    path = tmp_path / "client.sock"
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    os.chmod(path, 0o600)
    listener.listen(1)
    stop = threading.Event()
    cancel = threading.Event()
    errors = []

    def server():
        connection, _ = listener.accept()
        try:
            receiver = MeasurementRequestReceiverV2(
                connection, limits(), wait_is_current=lambda: True, heartbeat_interval_millis=10
            )
            received = receiver.read_header()
            assert received == request
            receiver.read_primary(DeadlineBoundedMemorySink())
            receiver.read_secondary(DeadlineBoundedMemorySink())
            if failure == "authority":
                cancel.set()
            connection.sendall(
                struct.pack(">I", len(payload)) + payload + (b"x" if failure == "trailing" else b"")
            )
            if failure == "missing_eof":
                stop.wait(0.5)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            errors.append(exc)
        finally:
            connection.close()

    thread = threading.Thread(target=server)
    thread.start()
    client = ExternalMeasurementUdsClient(
        connector=connector(path), protocol_limits=limits(), heartbeat_interval_millis=10
    )
    started = time.monotonic()
    try:
        if failure is None:
            assert (
                client.execute(
                    request=request,
                    manifest=manifest,
                    sources=tuple(BytesIO(raw) for raw in data),
                    deadline_monotonic=started + 0.3,
                    authority_is_current=lambda: not cancel.is_set(),
                )
                == result
            )
        else:
            with pytest.raises((ProtocolViolation, ProtocolDeadlineExceeded)):
                client.execute(
                    request=request,
                    manifest=manifest,
                    sources=tuple(BytesIO(raw) for raw in data),
                    deadline_monotonic=started + 0.15,
                    authority_is_current=lambda: not cancel.is_set(),
                )
        assert time.monotonic() - started < 0.45
    finally:
        stop.set()
        thread.join(1)
        listener.close()
    assert not thread.is_alive() and not errors
