"""External-only lane adapters retain Core fence identities without Core imports."""

from __future__ import annotations

import socket
import threading
import time
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace

import pytest
from ksi_processing_controller.external_artifact_inspection_worker import (
    CurrentAuthorityLost,
    ExternalInspectionPhaseV1,
    InspectorOperationProfileDecision,
    WorkerAuthorityLimitsV1,
)
from ksi_processing_controller.external_inspector_protocol import (
    InspectorLaunchResultV1,
    ProtocolLimitsV1,
)
from ksi_processing_controller.external_measurement_core_client import (
    MeasurementLeaseGrantV1,
    PendingMeasurementWorkV1,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectCapabilityV1,
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from ksi_processing_controller.external_validation_core_client import ExternalValidationCoreClient
from ksi_processing_controller.external_validation_lanes import (
    InspectionLaneDependencies,
    InspectionValidationLane,
    MeasurementLaneDependencies,
    MeasurementValidationLane,
)
from ksi_processing_controller.external_validation_runner import (
    ExternalLane,
    ExternalWorkLease,
    TurnOutcome,
)
from support.external_artifact_inspection_fixtures import report as inspection_report
from test_external_artifact_inspection_worker import _fence
from test_external_artifact_inspections_api import _active_scoped_app
from test_external_display_publication import _Core as _DisplayPublicationCore
from test_external_display_publication import _PutServer, _retained_context
from test_external_measurement_core_client import _completed_result, _volume_launch_with_records
from test_external_measurement_protocol import limits as measurement_limits
from test_external_validation_core_client import _CoreTestClientTransport


class _InspectionQueue:
    def __init__(self) -> None:
        self.claims: list[tuple[str, str]] = []

    def list_pending(self, *, deadline_monotonic: float, limit: int) -> tuple[object, ...]:
        assert deadline_monotonic == 10.0
        assert limit == 1
        return (SimpleNamespace(request_id="inspection-request"),)

    def claim(
        self,
        request_id: str,
        *,
        worker_instance_id: str,
        acquisition_id: str,
        deadline_monotonic: float,
    ) -> object:
        assert worker_instance_id == _fence().worker_instance_id
        assert deadline_monotonic == 10.0
        self.claims.append((request_id, acquisition_id))
        return SimpleNamespace(
            request=SimpleNamespace(request_id=request_id),
            fence=_fence().model_copy(update={"lease_acquisition_id": acquisition_id}),
        )


def test_inspection_lane_polls_and_claims_exact_request_with_runner_acquisition() -> None:
    core = _InspectionQueue()
    lane = InspectionValidationLane(
        core=core,
        worker_instance_id=_fence().worker_instance_id,
        dependencies=InspectionLaneDependencies(
            launcher=object(),
            operation_profile=object(),
            candidate_sink=object(),
            object_policy=ExternalObjectTransportPolicyV1(
                endpoints=(
                    TrustedObjectEndpointV1(origin="http://127.0.0.1:1", addresses=("127.0.0.1",)),
                ),
                max_header_bytes=256,
                max_object_bytes=256,
                max_chunk_bytes=64,
            ),
            worker_limits=WorkerAuthorityLimitsV1(
                heartbeat_interval_millis=1, max_authority_wait_millis=100
            ),
        ),
    )

    assert lane.poll(deadline_monotonic=10.0) == "inspection-request"
    lease = lane.claim(
        "inspection-request",
        "123e4567-e89b-42d3-a456-426614174099",
        deadline_monotonic=10.0,
    )

    assert lease == ExternalWorkLease(
        request_id="inspection-request",
        fence=_fence().model_copy(
            update={"lease_acquisition_id": "123e4567-e89b-42d3-a456-426614174099"}
        ),
    )
    assert core.claims == [("inspection-request", "123e4567-e89b-42d3-a456-426614174099")]


class _MeasurementQueue:
    def __init__(self) -> None:
        self.claims: list[tuple[str, str, str]] = []

    def list_pending(self, operation, *, deadline_monotonic: float, limit: int):
        assert deadline_monotonic == 10.0
        assert limit == 1
        return (PendingMeasurementWorkV1(operation, "volume-request", datetime.now(UTC)),)

    def claim(
        self, operation, request_id, *, worker_instance_id, acquisition_id, deadline_monotonic
    ):
        assert deadline_monotonic == 10.0
        self.claims.append((operation, request_id, acquisition_id))
        return MeasurementLeaseGrantV1(
            operation=operation,
            request_id=request_id,
            fence=_fence().model_copy(update={"lease_acquisition_id": acquisition_id}),
            lease_expires_at=datetime.now(UTC),
        )


def test_measurement_lane_polls_and_claims_only_its_exact_operation_and_acquisition() -> None:
    core = _MeasurementQueue()
    lane = MeasurementValidationLane(
        lane=ExternalLane.RELATIVE_VOLUME,
        operation="RELATIVE_VOLUME",
        core=core,
        worker_instance_id=_fence().worker_instance_id,
        dependencies=MeasurementLaneDependencies(
            manifest=object(),
            uds_client=object(),
            protocol_limits=ProtocolLimitsV1(
                max_header_bytes=256,
                max_chunk_bytes=64,
                max_input_bytes=256,
                max_output_bytes=256,
                max_wire_duration_millis=100,
            ),
            heartbeat_interval_millis=1,
            object_policy=ExternalObjectTransportPolicyV1(
                endpoints=(TrustedObjectEndpointV1("http://127.0.0.1:1", ("127.0.0.1",)),),
                max_header_bytes=256,
                max_object_bytes=256,
                max_chunk_bytes=64,
            ),
        ),
    )

    assert lane.poll(deadline_monotonic=10.0) == "volume-request"
    lease = lane.claim(
        "volume-request",
        "123e4567-e89b-42d3-a456-426614174099",
        deadline_monotonic=10.0,
    )

    assert lease is not None
    assert lease.fence.lease_acquisition_id == "123e4567-e89b-42d3-a456-426614174099"
    assert core.claims == [
        ("RELATIVE_VOLUME", "volume-request", "123e4567-e89b-42d3-a456-426614174099")
    ]


class _MeasurementExecutionCore:
    def __init__(self, manifest, template, object_url: str) -> None:
        self._manifest = manifest
        self._template = template
        self._object_url = object_url
        self.submitted: list[tuple[object, object]] = []
        self.incomplete: list[str] = []

    def current_input(self, operation, request_id, fence, *, attempt_nonce, deadline_monotonic):
        assert operation == "RELATIVE_VOLUME"
        assert request_id == self._template.request_id
        assert deadline_monotonic > time.monotonic()
        return self._template.model_copy(
            update={"fence": fence, "attempt_nonce": attempt_nonce, "canonical_input_digest": None}
        ).sealed()

    def heartbeat(self, operation, request_id, fence, *, deadline_monotonic):
        assert operation == "RELATIVE_VOLUME"
        return MeasurementLeaseGrantV1(
            operation=operation,
            request_id=request_id,
            fence=fence,
            lease_expires_at=datetime.now(UTC),
        )

    def capability_for(self, operation, request_id, fence, artifact):
        del operation, request_id, fence
        return ExternalObjectCapabilityV1(
            artifact=artifact, url=self._object_url, required_headers={}
        )

    def submit_result(self, launch, result, *, manifest, limits, computed_at, deadline_monotonic):
        assert manifest == self._manifest
        assert limits == measurement_limits()
        assert deadline_monotonic > time.monotonic()
        assert computed_at.tzinfo is not None
        self.submitted.append((launch, result))

    def record_incomplete_failure(
        self, operation, request_id, fence, reason, *, deadline_monotonic
    ):
        del operation, request_id, fence, deadline_monotonic
        self.incomplete.append(reason)

    def release(self, operation, request_id, fence):
        del operation, request_id, fence


class _ResultUdsClient:
    def __init__(self) -> None:
        self.calls: list[object] = []

    def execute(self, *, request, manifest, sources, deadline_monotonic, authority_is_current):
        assert authority_is_current() is True
        assert len(sources) == 2
        assert deadline_monotonic > time.monotonic()
        self.calls.append(request)
        return _completed_result(request, manifest)


def test_volume_lane_uses_two_exact_loopback_sources_then_submits_only_v2_observed_result() -> None:
    manifest, template = _volume_launch_with_records()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    port = listener.getsockname()[1]
    requests: list[bytes] = []

    def serve_objects() -> None:
        try:
            for size in (
                template.inputs[0].observed_size_bytes,
                template.inputs[1].observed_size_bytes,
            ):
                connection, _address = listener.accept()
                try:
                    requests.append(connection.recv(1_024))
                    connection.sendall(
                        f"HTTP/1.1 200 OK\r\nContent-Length: {size}\r\n\r\n".encode()
                    )
                finally:
                    connection.close()
        finally:
            listener.close()

    server = threading.Thread(target=serve_objects)
    server.start()
    try:
        core = _MeasurementExecutionCore(manifest, template, f"http://127.0.0.1:{port}/sealed")
        uds = _ResultUdsClient()
        lane = MeasurementValidationLane(
            lane=ExternalLane.RELATIVE_VOLUME,
            operation="RELATIVE_VOLUME",
            core=core,
            worker_instance_id=_fence().worker_instance_id,
            dependencies=MeasurementLaneDependencies(
                manifest=manifest,
                uds_client=uds,
                protocol_limits=measurement_limits(),
                heartbeat_interval_millis=10,
                object_policy=ExternalObjectTransportPolicyV1(
                    endpoints=(
                        TrustedObjectEndpointV1(
                            origin=f"http://127.0.0.1:{port}", addresses=("127.0.0.1",)
                        ),
                    ),
                    max_header_bytes=256,
                    max_object_bytes=1_024,
                    max_chunk_bytes=64,
                ),
            ),
            attempt_nonce_factory=lambda: "123e4567-e89b-42d3-a456-426614174099",
            clock=lambda: datetime(2026, 9, 9, tzinfo=UTC),
        )
        lease = ExternalWorkLease(request_id=template.request_id, fence=_fence())
        assert (
            lane.execute(lease, deadline_monotonic=time.monotonic() + 1, stop=Event())
            is TurnOutcome.COMPLETED
        )
    finally:
        server.join(timeout=1)
        listener.close()
    assert not server.is_alive()
    assert len(requests) == 2
    assert all(request.startswith(b"GET /sealed HTTP/1.1") for request in requests)
    assert len(uds.calls) == 1
    assert len(core.submitted) == 1
    assert core.incomplete == []


def test_measurement_second_source_open_failure_closes_first_reader_and_records_incomplete() -> (
    None
):
    manifest, template = _volume_launch_with_records()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    first_closed = threading.Event()

    def serve_first_then_remove_listener() -> None:
        connection, _address = listener.accept()
        try:
            connection.recv(1_024)
            listener.close()
            connection.sendall(
                (
                    "HTTP/1.1 200 OK\r\nContent-Length: "
                    f"{template.inputs[0].observed_size_bytes}\r\n\r\n"
                ).encode()
            )
            connection.settimeout(1)
            assert connection.recv(1) == b""
            first_closed.set()
        finally:
            connection.close()

    server = threading.Thread(target=serve_first_then_remove_listener)
    server.start()
    try:
        core = _MeasurementExecutionCore(manifest, template, f"http://127.0.0.1:{port}/sealed")
        lane = MeasurementValidationLane(
            lane=ExternalLane.RELATIVE_VOLUME,
            operation="RELATIVE_VOLUME",
            core=core,
            worker_instance_id=_fence().worker_instance_id,
            dependencies=MeasurementLaneDependencies(
                manifest=manifest,
                uds_client=_ResultUdsClient(),
                protocol_limits=measurement_limits(),
                heartbeat_interval_millis=10,
                object_policy=ExternalObjectTransportPolicyV1(
                    endpoints=(
                        TrustedObjectEndpointV1(
                            origin=f"http://127.0.0.1:{port}", addresses=("127.0.0.1",)
                        ),
                    ),
                    max_header_bytes=256,
                    max_object_bytes=1_024,
                    max_chunk_bytes=64,
                ),
            ),
            attempt_nonce_factory=lambda: "123e4567-e89b-42d3-a456-426614174099",
        )
        assert (
            lane.execute(
                ExternalWorkLease(request_id=template.request_id, fence=_fence()),
                deadline_monotonic=time.monotonic() + 1,
                stop=Event(),
            )
            is TurnOutcome.DEFERRED
        )
    finally:
        server.join(timeout=1)
        listener.close()
    assert not server.is_alive()
    assert first_closed.is_set()
    assert core.submitted == []
    assert core.incomplete == ["TRANSIENT_SERVICE_UNAVAILABLE"]


def test_display_authority_loss_does_not_send_an_inspection_incomplete_terminal() -> None:
    core = _InspectionQueue()
    incomplete: list[str] = []
    core.record_incomplete_failure = lambda request_id, fence, reason, **_kwargs: incomplete.append(
        reason
    )
    lane = InspectionValidationLane(
        core=core,
        worker_instance_id=_fence().worker_instance_id,
        dependencies=InspectionLaneDependencies(
            launcher=object(),
            operation_profile=object(),
            candidate_sink=object(),
            object_policy=ExternalObjectTransportPolicyV1(
                endpoints=(TrustedObjectEndpointV1("http://127.0.0.1:1", ("127.0.0.1",)),),
                max_header_bytes=256,
                max_object_bytes=256,
                max_chunk_bytes=64,
            ),
            worker_limits=WorkerAuthorityLimitsV1(
                heartbeat_interval_millis=1, max_authority_wait_millis=100
            ),
        ),
    )
    lease = ExternalWorkLease(request_id="inspection-request", fence=_fence())
    lane._current = lambda *_args: SimpleNamespace(phase=ExternalInspectionPhaseV1.DISPLAY)

    def lose_authority(*_args: object) -> None:
        raise CurrentAuthorityLost("display authority changed")

    lane._execute_display = lose_authority

    assert lane.execute(lease, deadline_monotonic=10.0, stop=Event()) is TurnOutcome.DEFERRED
    assert incomplete == []


def test_measurement_guard_rechecks_stop_after_heartbeat_callback() -> None:
    """A stop raised during heartbeat cannot authorize the following UDS operation."""

    manifest, launch = _volume_launch_with_records()
    stop = Event()

    class _Core:
        def heartbeat(self, operation, request_id, fence, *, deadline_monotonic):
            assert operation == "RELATIVE_VOLUME"
            assert request_id == launch.request_id
            assert deadline_monotonic > time.monotonic()
            stop.set()
            return MeasurementLeaseGrantV1(
                operation=operation,
                request_id=request_id,
                fence=fence,
                lease_expires_at=datetime.now(UTC),
            )

    lane = MeasurementValidationLane(
        lane=ExternalLane.RELATIVE_VOLUME,
        operation="RELATIVE_VOLUME",
        core=_Core(),
        worker_instance_id=_fence().worker_instance_id,
        dependencies=MeasurementLaneDependencies(
            manifest=manifest,
            uds_client=object(),
            protocol_limits=measurement_limits(),
            heartbeat_interval_millis=10,
            object_policy=ExternalObjectTransportPolicyV1(
                endpoints=(TrustedObjectEndpointV1("http://127.0.0.1:1", ("127.0.0.1",)),),
                max_header_bytes=256,
                max_object_bytes=256,
                max_chunk_bytes=64,
            ),
        ),
    )

    assert (
        lane._is_current(
            ExternalWorkLease(request_id=launch.request_id, fence=_fence()),
            time.monotonic() + 1,
            stop,
        )
        is False
    )


class _CurrentInspectionLauncher:
    def execute(self, *, request, source, **_kwargs):
        del source
        outcome = inspection_report(
            request_id=request.request.request_id,
            policy=request.policy,
            worker=request.fence.worker_instance_id,
            acquisition=request.fence.lease_acquisition_id,
            generation=request.fence.lease_generation,
        ).measurement_payload.outcomes[0]
        return InspectorLaunchResultV1.completed_inspection(
            request.attempt_nonce,
            request.canonical_input_digest,
            request.policy.parser_build_digest,
            outcome,
        )


def _display_lane_with_retained_candidate(
    sink, *, object_origin: str = "http://127.0.0.1:1"
) -> InspectionValidationLane:
    return InspectionValidationLane(
        core=object(),
        worker_instance_id=_fence().worker_instance_id,
        dependencies=InspectionLaneDependencies(
            launcher=object(),
            operation_profile=object(),
            candidate_sink=sink,
            object_policy=ExternalObjectTransportPolicyV1(
                endpoints=(
                    TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),
                ),
                max_header_bytes=4_096,
                max_object_bytes=4_096,
                max_chunk_bytes=64,
            ),
            worker_limits=WorkerAuthorityLimitsV1(
                heartbeat_interval_millis=10, max_authority_wait_millis=1_000
            ),
        ),
    )


def test_display_lane_aborts_the_actual_private_candidate_when_stop_follows_sanitize(
    tmp_path,
) -> None:
    """The lane, rather than a later turn, owns a sealed candidate after SANITIZE."""

    context, sink, root = _retained_context(tmp_path, b"sanitized-derivative")
    stop = Event()
    lane = _display_lane_with_retained_candidate(sink)

    class _Worker:
        def launch_artifact_context(self, *_args, **_kwargs):
            stop.set()
            return context

    lane._worker_for = lambda *_args: _Worker()
    lane._is_current = lambda *_args: not stop.is_set()
    lease = ExternalWorkLease(
        request_id=context.current.request.request_id,
        fence=context.launch_request.fence,
    )

    with pytest.raises(CurrentAuthorityLost, match="cancelled"):
        lane._execute_display(
            context.current,
            lease,
            time.monotonic() + 1,
            stop,
        )

    assert not sink._active
    assert not sink._sealed
    assert not sink._uncertain
    assert list(root.iterdir()) == []


def test_display_lane_retries_the_same_actual_private_candidate_after_grant_response_loss(
    tmp_path,
) -> None:
    """A retryable grant response loss retries one retained O_TMPFILE candidate."""

    payload = b"sanitized-derivative"
    context, sink, root = _retained_context(tmp_path, payload)
    with _PutServer() as put_server:
        core = _DisplayPublicationCore(put_server.url)
        core.fail_next_grant = True
        lane = _display_lane_with_retained_candidate(
            sink, object_origin=f"http://127.0.0.1:{put_server.port}"
        )

        class _Worker:
            def launch_artifact_context(self, *_args, **_kwargs):
                return context

        lane._core = core
        lane._worker_for = lambda *_args: _Worker()
        lane._is_current = lambda *_args: True
        lease = ExternalWorkLease(
            request_id=context.current.request.request_id,
            fence=context.launch_request.fence,
        )

        lane._execute_display(
            context.current,
            lease,
            time.monotonic() + 1,
            Event(),
        )

        assert core.declarations[0] == core.declarations[1]
        assert put_server.body == payload
    assert not sink._active
    assert not sink._sealed
    assert not sink._uncertain
    assert list(root.iterdir()) == []


def test_display_lane_accepts_the_authoritative_terminal_receipt_after_display_phase_ends(
    tmp_path,
) -> None:
    """The sealed Core receipt, not a now-spent DISPLAY lease, completes publication."""

    payload = b"sanitized-derivative"
    context, sink, root = _retained_context(tmp_path, payload)
    with _PutServer() as put_server:
        lane = _display_lane_with_retained_candidate(
            sink, object_origin=f"http://127.0.0.1:{put_server.port}"
        )

        class _Worker:
            def launch_artifact_context(self, *_args, **_kwargs):
                return context

        lane._core = _DisplayPublicationCore(put_server.url)
        lane._worker_for = lambda *_args: _Worker()
        current_checks = 0

        def is_current(*_args) -> bool:
            nonlocal current_checks
            current_checks += 1
            return current_checks == 1

        lane._is_current = is_current
        lease = ExternalWorkLease(
            request_id=context.current.request.request_id,
            fence=context.launch_request.fence,
        )

        lane._execute_display(
            context.current,
            lease,
            time.monotonic() + 1,
            Event(),
        )

        assert put_server.body == payload
    assert current_checks == 1
    assert not sink._active
    assert not sink._sealed
    assert not sink._uncertain
    assert list(root.iterdir()) == []


def test_display_lane_aborts_the_actual_private_candidate_on_base_exception(
    tmp_path, monkeypatch
) -> None:
    """KeyboardInterrupt preserves itself while the exact sealed candidate is retired."""

    context, sink, root = _retained_context(tmp_path, b"sanitized-derivative")
    lane = _display_lane_with_retained_candidate(sink)

    class _Worker:
        def launch_artifact_context(self, *_args, **_kwargs):
            return context

    class _InterruptedPublication:
        def __init__(self, **_kwargs) -> None:
            pass

        def publish(self, _context) -> None:
            raise KeyboardInterrupt("synthetic interruption")

    monkeypatch.setattr(
        "ksi_processing_controller.external_validation_lanes.ExternalDisplayPublicationWorker",
        _InterruptedPublication,
    )
    lane._worker_for = lambda *_args: _Worker()
    lane._is_current = lambda *_args: True
    lease = ExternalWorkLease(
        request_id=context.current.request.request_id,
        fence=context.launch_request.fence,
    )

    with pytest.raises(KeyboardInterrupt, match="synthetic interruption"):
        lane._execute_display(
            context.current,
            lease,
            time.monotonic() + 1,
            Event(),
        )

    assert not sink._active
    assert not sink._sealed
    assert not sink._uncertain
    assert list(root.iterdir()) == []


class _AllowInspectionProfile:
    def allows(self, **_kwargs):
        return InspectorOperationProfileDecision.ALLOW


class _LoopbackObjectCore:
    def __init__(self, core: ExternalValidationCoreClient, object_url: str) -> None:
        self._core = core
        self._object_url = object_url

    def __getattr__(self, name: str):
        return getattr(self._core, name)

    def capability_for(self, request_id, fence, artifact):
        self._core.capability_for(request_id, fence, artifact)
        return ExternalObjectCapabilityV1(
            artifact=artifact, url=self._object_url, required_headers={}
        )


def test_inspection_phase_records_complete_report_through_actual_core_and_loopback_object(
    tmp_path,
) -> None:
    app, _issued_request, policy, _storage, _submission_ref = _active_scoped_app(tmp_path)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    server_errors: list[BaseException] = []

    def serve_object() -> None:
        connection, _address = listener.accept()
        try:
            connection.recv(1_024)
            connection.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 12\r\n\r\n")
        except BaseException as exc:  # pragma: no cover - surfaced below
            server_errors.append(exc)
        finally:
            connection.close()

    server = threading.Thread(target=serve_object)
    server.start()
    try:
        from fastapi.testclient import TestClient

        with TestClient(app) as core_app:
            transport = _CoreTestClientTransport(core_app)
            with ExternalValidationCoreClient(
                base_url="https://core.invalid",
                bearer_token="worker-token",
                transport=transport,
            ) as client:
                lane = InspectionValidationLane(
                    core=_LoopbackObjectCore(client, f"http://127.0.0.1:{port}/sealed"),
                    worker_instance_id=_fence().worker_instance_id,
                    dependencies=InspectionLaneDependencies(
                        launcher=_CurrentInspectionLauncher(),
                        operation_profile=_AllowInspectionProfile(),
                        candidate_sink=object(),
                        object_policy=ExternalObjectTransportPolicyV1(
                            endpoints=(
                                TrustedObjectEndpointV1(
                                    origin=f"http://127.0.0.1:{port}",
                                    addresses=("127.0.0.1",),
                                ),
                            ),
                            max_header_bytes=256,
                            max_object_bytes=64,
                            max_chunk_bytes=16,
                        ),
                        worker_limits=WorkerAuthorityLimitsV1(
                            heartbeat_interval_millis=10, max_authority_wait_millis=1_000
                        ),
                    ),
                    report_id_factory=lambda: "123e4567-e89b-42d3-a456-426614174099",
                    clock=lambda: datetime.now(UTC),
                )
                deadline = time.monotonic() + 1
                request_id = lane.poll(deadline_monotonic=deadline)
                assert request_id is not None
                lease = lane.claim(
                    request_id,
                    _fence().lease_acquisition_id,
                    deadline_monotonic=deadline,
                )
                assert lease is not None
                transport.drop_next_suffix = "/report"
                # This narrow report-retry contract deliberately exercises
                # only the INSPECTION phase.  Public report-to-DISPLAY
                # continuation is covered through the production lane and
                # owned UDS in the runner integration contract.
                lane._execute_inspection(lane._current(lease, deadline), lease, deadline, Event())
                current = client.current_input(request_id, lease.fence, deadline_monotonic=deadline)
                assert current is not None
                assert current.phase is ExternalInspectionPhaseV1.DISPLAY
                assert current.accepted_report is not None
                assert current.accepted_report.inspection_policy_digest == policy.policy_digest
    finally:
        listener.close()
        server.join(timeout=1)
    assert not server.is_alive()
    assert server_errors == []
