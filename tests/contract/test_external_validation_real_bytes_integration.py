"""Real-byte software coverage for the external inspection and measurement seams.

The HTTP and UDS endpoints here are test-owned transports.  They exercise no
container launcher, systemd, rootless engine, deployed service, or device.
"""

from __future__ import annotations

import os
import socket
import struct
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pytest
import test_external_measurement_container_entrypoint as measurement_contract
import test_external_validation_runner_integration as runner_contract
from fastapi.testclient import TestClient
from ksi_processing_controller.external_inspector_container_entrypoint import (
    run_container_entrypoint,
)
from ksi_processing_controller.external_inspector_container_protocol import (
    build_execute_frame,
    encode_inner_frame,
)
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedBytesReader,
    DeadlineBoundedMemorySink,
    ProtocolLimitsV1,
)
from ksi_processing_controller.external_measurement_client import (
    ExternalMeasurementUdsClient,
    FixedMeasurementUdsConnector,
    MeasurementSocketIdentityV2,
)
from ksi_processing_controller.external_measurement_container_entrypoint import (
    run_measurement_container_entrypoint,
)
from ksi_processing_controller.external_measurement_container_protocol import (
    MeasurementContainerFrameLimitsV2,
    build_execute_frame_v2,
    build_prepare_frame_v2,
    build_secondary_begin_frame,
    decode_measurement_container_frame,
    encode_measurement_container_frame,
)
from ksi_processing_controller.external_measurement_core_client import (
    ExternalMeasurementCoreClient,
    MeasurementOperationV2,
)
from ksi_processing_controller.external_measurement_result import build_measurement_result
from ksi_processing_controller.external_measurement_transport import MeasurementRequestReceiverV2
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from ksi_processing_controller.external_validation_core_client import ExternalValidationCoreClient
from ksi_processing_controller.external_validation_lanes import (
    MeasurementLaneDependencies,
    MeasurementValidationLane,
)
from ksi_processing_controller.external_validation_runner import (
    ExternalLane,
    TurnOutcome,
)
from test_external_artifact_inspection_worker import _fence
from test_external_inspector_container_entrypoint import _decode_output, _prepare
from test_external_measurement_container_entrypoint import _write_compound_dsm
from test_external_measurement_protocol import limits as measurement_limits
from test_external_relative_volumes import _WORKER_TOKEN as _VOLUME_WORKER_TOKEN
from test_external_sanitized_raster import _write_rgba
from test_external_validation_core_client import _CoreTestClientTransport


class _EntrypointMeasurementUdsServer:
    """One bounded UDS exchange whose terminal comes from the real V2 entrypoint."""

    def __init__(
        self, *, path: Path, manifest: Any, root: Path, corrupt_secondary: bool = False
    ) -> None:
        self._manifest, self._root, self._corrupt_secondary = manifest, root, corrupt_secondary
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(str(path))
        path.chmod(0o600)
        self._listener.listen(1)
        self._listener.settimeout(0.1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve)
        self.errors: list[BaseException] = []
        self.terminal: dict[str, Any] | None = None

    def __enter__(self) -> _EntrypointMeasurementUdsServer:
        self._thread.start()
        return self

    def __exit__(self, kind: object, *_args: object) -> None:
        self._stop.set()
        self._listener.close()
        self._thread.join(timeout=2)
        assert not self._thread.is_alive(), "owned measurement UDS server did not stop"
        if kind is None and self.errors:
            raise self.errors[0]

    def _serve(self) -> None:
        limits = ProtocolLimitsV1(
            max_header_bytes=128_000,
            max_chunk_bytes=4_096,
            max_input_bytes=4_000_000,
            max_output_bytes=4_000_000,
            max_wire_duration_millis=20_000,
        )
        try:
            while not self._stop.is_set():
                try:
                    connection, _address = self._listener.accept()
                except TimeoutError:
                    continue
                with connection:
                    receiver = MeasurementRequestReceiverV2(
                        connection,
                        limits,
                        wait_is_current=lambda: True,
                        heartbeat_interval_millis=10,
                    )
                    request = receiver.read_header()
                    primary, secondary = DeadlineBoundedMemorySink(), DeadlineBoundedMemorySink()
                    receiver.read_primary(primary)
                    receiver.read_secondary(secondary)
                    assert receiver.complete
                    primary_path = self._root / "primary.tif"
                    primary_path.write_bytes(b"".join(primary.chunks))
                    secondary_bytes = b"".join(secondary.chunks)
                    if self._corrupt_secondary:
                        secondary_bytes = secondary_bytes[:-1] + bytes([secondary_bytes[-1] ^ 1])
                    workspace = self._root / "workspace"
                    workspace.mkdir(mode=0o700)
                    frames = MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128_000)
                    prepare = build_prepare_frame_v2(request=request, manifest=self._manifest)
                    stdout = BytesIO()
                    run_measurement_container_entrypoint(
                        stdin=BytesIO(
                            encode_measurement_container_frame(prepare, limits=frames)
                            + encode_measurement_container_frame(
                                build_secondary_begin_frame(prepare=prepare), limits=frames
                            )
                            + secondary_bytes
                            + encode_measurement_container_frame(
                                build_execute_frame_v2(prepare=prepare), limits=frames
                            )
                        ),
                        stdout=stdout,
                        artifact_path=primary_path,
                        workspace=workspace,
                        limits=frames,
                    )
                    self.terminal = _terminal_frame(stdout, frames)
                    result = build_measurement_result(
                        terminal=self.terminal,
                        request=request,
                        manifest=self._manifest,
                        limits=limits,
                    )
                    payload = result.canonical_bytes(
                        request=request, manifest=self._manifest, limits=limits
                    )
                    connection.sendall(struct.pack(">I", len(payload)) + payload)
                    connection.shutdown(socket.SHUT_WR)
                    return
        except OSError as exc:
            if not self._stop.is_set() and self._listener.fileno() >= 0:
                self.errors.append(exc)
        except BaseException as exc:
            self.errors.append(exc)


def _terminal_frame(stdout: BytesIO, limits: MeasurementContainerFrameLimitsV2) -> dict[str, Any]:
    raw, terminal = stdout.getvalue(), None
    while raw:
        size = int.from_bytes(raw[:4], "big")
        terminal = decode_measurement_container_frame(raw[: 4 + size], limits=limits)
        raw = raw[4 + size :]
    assert terminal is not None
    return terminal


def _real_byte_envelope() -> Any:
    from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1

    return ResourceEnvelopeV1(
        max_input_bytes=4_000_000,
        max_streamed_bytes=4_000_000,
        max_tiff_directories=32,
        max_tiff_entries=2_048,
        max_pixels=2_000_000,
        max_bands=4,
        max_blocks=2_048,
        max_decompressed_bytes=40_000_000,
        max_sample_bytes=40_000_000,
        max_geometry_vertices=64,
        max_cpu_seconds=5.0,
        max_memory_bytes=40_000_000,
        max_workspace_bytes=4_000_000,
        max_output_bytes=4_000_000,
        max_tenant_concurrency=1,
        max_queue_depth=4,
        max_deadline_seconds=5.0,
        lease_duration_seconds=5.0,
        max_retry_attempts=1,
    ).sealed()


def _measurement_lane(
    *,
    lane: ExternalLane,
    operation: MeasurementOperationV2,
    core: ExternalMeasurementCoreClient,
    manifest: Any,
    socket_path: Path,
    object_origin: str,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> MeasurementValidationLane:
    limits = ProtocolLimitsV1(
        max_header_bytes=128_000,
        max_chunk_bytes=4_096,
        max_input_bytes=4_000_000,
        max_output_bytes=4_000_000,
        max_wire_duration_millis=20_000,
    )
    return MeasurementValidationLane(
        lane=lane,
        operation=operation,
        core=core,
        worker_instance_id=_fence().worker_instance_id,
        dependencies=MeasurementLaneDependencies(
            manifest=manifest,
            uds_client=ExternalMeasurementUdsClient(
                connector=FixedMeasurementUdsConnector(
                    MeasurementSocketIdentityV2(
                        path=socket_path,
                        owner_uid=os.geteuid(),
                        owner_gid=os.getegid(),
                        mode=0o600,
                        launcher_uid=os.geteuid(),
                    )
                ),
                protocol_limits=limits,
                heartbeat_interval_millis=10,
            ),
            protocol_limits=limits,
            heartbeat_interval_millis=10,
            object_policy=ExternalObjectTransportPolicyV1(
                endpoints=(
                    TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),
                ),
                max_header_bytes=128_000,
                max_object_bytes=4_000_000,
                max_chunk_bytes=4_096,
            ),
        ),
        attempt_nonce_factory=lambda: str(_fence().lease_acquisition_id),
        clock=clock,
    )


def test_real_dsm_csv_bytes_flow_from_core_capabilities_to_measured_terminal_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Synthetic terminal values cannot satisfy these hand-derived aggregate assertions."""

    baseline, current, target = (
        tmp_path / name for name in ("base.tif", "current.tif", "target.tif")
    )
    values = np.full((16, 16), 10.0, dtype=np.float32)
    current_values, target_values = values.copy(), values.copy()
    current_values[0, 0], current_values[0, 1] = 9.0, 15.0
    target_values[0, 1], target_values[1, 0] = 20.0, 30.0
    for path, pixels in ((baseline, values), (current, current_values), (target, target_values)):
        _write_compound_dsm(path, pixels)
    checkpoint_csv = (
        b"checkpoint_id,easting_m,northing_m,elevation_m\n"
        b"a,200000.5,499999.5,9\n"
        b"b,200001.5,499999.5,18\n"
        b"c,200000.5,499998.5,31\n"
    )
    checkpoint_socket, volume_socket = tmp_path / "checkpoint.sock", tmp_path / "volume.sock"
    with runner_contract._FiniteObjectGetServer(
        {
            "/checkpoint-target": target.read_bytes(),
            "/checkpoint-csv": checkpoint_csv,
            "/volume-base": baseline.read_bytes(),
            "/volume-current": current.read_bytes(),
        }
    ) as objects:
        (
            checkpoint_app,
            checkpoint_store,
            _checkpoint_id,
            checkpoint_manifest,
            volume_app,
            volume_store,
            volume_id,
            volume_manifest,
        ) = runner_contract._actual_measurement_core_apps(
            tmp_path / "core",
            checkpoint_bodies=(target.read_bytes(), checkpoint_csv),
            volume_bodies=(baseline.read_bytes(), current.read_bytes()),
            objects=objects,
            monkeypatch=monkeypatch,
            resource_envelope=_real_byte_envelope(),
        )
        checkpoint_root, volume_root = tmp_path / "checkpoint-uds", tmp_path / "volume-uds"
        checkpoint_root.mkdir(mode=0o700)
        volume_root.mkdir(mode=0o700)
        with (
            _EntrypointMeasurementUdsServer(
                path=checkpoint_socket, manifest=checkpoint_manifest, root=checkpoint_root
            ) as checkpoint_uds,
            _EntrypointMeasurementUdsServer(
                path=volume_socket, manifest=volume_manifest, root=volume_root
            ) as volume_uds,
            TestClient(checkpoint_app) as checkpoint_http,
            TestClient(volume_app) as volume_http,
            ExternalValidationCoreClient(
                base_url="https://checkpoint.invalid",
                bearer_token=runner_contract._RUNNER_CHECKPOINT_TOKEN,
                transport=_CoreTestClientTransport(checkpoint_http),
            ) as checkpoint_shared,
            ExternalValidationCoreClient(
                base_url="https://volume.invalid",
                bearer_token=_VOLUME_WORKER_TOKEN,
                transport=_CoreTestClientTransport(volume_http),
            ) as volume_shared,
        ):
            checkpoint_core = ExternalMeasurementCoreClient(core_client=checkpoint_shared)
            volume_core = ExternalMeasurementCoreClient(core_client=volume_shared)
            try:
                for lane in (
                    _measurement_lane(
                        lane=ExternalLane.CHECKPOINT,
                        operation="CHECKPOINT_VALIDATION",
                        core=checkpoint_core,
                        manifest=checkpoint_manifest,
                        socket_path=checkpoint_socket,
                        object_origin=objects.origin,
                    ),
                    _measurement_lane(
                        lane=ExternalLane.RELATIVE_VOLUME,
                        operation="RELATIVE_VOLUME",
                        core=volume_core,
                        manifest=volume_manifest,
                        socket_path=volume_socket,
                        object_origin=objects.origin,
                        clock=lambda: datetime(2026, 9, 9, tzinfo=UTC),
                    ),
                ):
                    deadline = time.monotonic() + 20
                    request_id = lane.poll(deadline_monotonic=deadline)
                    assert request_id is not None
                    lease = lane.claim(
                        request_id,
                        str(uuid4()),
                        deadline_monotonic=deadline,
                    )
                    assert lease is not None
                    assert (
                        lane.execute(
                            lease,
                            deadline_monotonic=deadline,
                            stop=threading.Event(),
                        )
                        is TurnOutcome.COMPLETED
                    )
                    lane.release(lease)
            finally:
                checkpoint_core.close()
                volume_core.close()

    records = checkpoint_store.terminal_records_for_evidence("eev-v1-a")
    assert len(records) == 1 and records[0].measurement_payload is not None
    measured = records[0].measurement_payload
    assert measured.measured_checkpoint_count == 3
    assert measured.mean_error_m == pytest.approx(2 / 3)
    assert measured.mae_m == pytest.approx(4 / 3)
    assert measured.rmse_m == pytest.approx(2**0.5)
    assert measured.max_abs_error_m == pytest.approx(2.0)
    volume_record = volume_store.get(volume_id, organization_id="org-a")
    assert volume_record is not None and volume_record.report is not None
    assert volume_record.report.payload.metrics.cut_m3 == pytest.approx(1.0)
    assert volume_record.report.payload.metrics.fill_m3 == pytest.approx(5.0)
    assert volume_record.report.payload.metrics.net_m3 == pytest.approx(4.0)
    assert checkpoint_uds.terminal is not None and checkpoint_uds.terminal["frame"] == "COMPLETED"
    assert volume_uds.terminal is not None and volume_uds.terminal["frame"] == "COMPLETED"


def test_real_entrypoints_keep_inspection_and_corrupt_measurement_bytes_fail_closed(
    tmp_path: Path,
) -> None:
    """A real ORTHO is measured; in-UDS corruption after request binding carries no aggregate."""

    ortho, workspace = tmp_path / "ortho.tif", tmp_path / "inspector-work"
    workspace.mkdir(mode=0o700)
    _write_rgba(ortho)
    prepare, inspector_limits = _prepare(ortho, operation="INSPECT")
    inspector_stdout = BytesIO()
    run_container_entrypoint(
        stdin=BytesIO(
            encode_inner_frame(prepare, limits=inspector_limits)
            + encode_inner_frame(build_execute_frame(prepare=prepare), limits=inspector_limits)
        ),
        stdout=inspector_stdout,
        artifact_path=ortho,
        workspace=workspace,
        limits=inspector_limits,
    )
    _mount, inspection_terminal, raw = _decode_output(inspector_stdout, inspector_limits)
    assert inspection_terminal["frame"] == "COMPLETED"
    inspection_outcome = inspection_terminal["outcome"]
    assert isinstance(inspection_outcome, dict)
    assert inspection_outcome["outcome"] == "MEASURED"
    assert raw == b""

    primary = tmp_path / "primary.tif"
    _write_compound_dsm(primary, np.full((16, 16), 10.0, dtype=np.float32))
    checkpoint_csv = (
        b"checkpoint_id,easting_m,northing_m,elevation_m\n"
        b"a,200000.5,499999.5,10\n"
        b"b,200001.5,499999.5,10\n"
        b"c,200000.5,499998.5,10\n"
    )
    manifest, request = measurement_contract._checkpoint_request(
        primary=primary, checkpoint_csv=checkpoint_csv
    )
    socket_path, root = tmp_path / "corrupt.sock", tmp_path / "corrupt-uds"
    root.mkdir(mode=0o700)
    with _EntrypointMeasurementUdsServer(
        path=socket_path, manifest=manifest, root=root, corrupt_secondary=True
    ) as uds:
        client = ExternalMeasurementUdsClient(
            connector=FixedMeasurementUdsConnector(
                MeasurementSocketIdentityV2(
                    path=socket_path,
                    owner_uid=os.geteuid(),
                    owner_gid=os.getegid(),
                    mode=0o600,
                    launcher_uid=os.geteuid(),
                )
            ),
            protocol_limits=measurement_limits().model_copy(
                update={"max_input_bytes": 4_000_000, "max_wire_duration_millis": 20_000}
            ),
            heartbeat_interval_millis=10,
        )
        result = client.execute(
            request=request,
            manifest=manifest,
            sources=(
                DeadlineBoundedBytesReader(BytesIO(primary.read_bytes())),
                DeadlineBoundedBytesReader(BytesIO(checkpoint_csv)),
            ),
            deadline_monotonic=time.monotonic() + 10,
            authority_is_current=lambda: True,
        )
    assert result.status == "FAILED"
    assert result.reason == "SECONDARY_SPOOL_DIGEST_MISMATCH"
    assert result.aggregate is None
    assert uds.terminal is not None and uds.terminal["reason"] == "SECONDARY_SPOOL_DIGEST_MISMATCH"
