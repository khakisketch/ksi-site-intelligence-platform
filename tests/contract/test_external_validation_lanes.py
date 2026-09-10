"""External-only lane adapters retain Core fence identities without Core imports."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import Any, cast

import pytest
from ksi_event_contracts.external_artifact_validation import (
    ExternalArtifactInspectionReportV1,
    ExternalValidationPolicyV1,
)
from ksi_event_contracts.external_display_artifact import (
    SanitizedDisplayDeclarationV1,
    SanitizedDisplayReceiptV1,
)
from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestV1
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller.external_artifact_inspection_worker import (
    CurrentAuthorityLost,
    ExternalArtifactInputV1,
    ExternalInspectionCurrentInputV1,
    ExternalInspectionPhaseV1,
    ExternalInspectorLaunchContextV1,
    ExternalInspectorLaunchPort,
    InspectorOperationProfileDecision,
    InspectorWorkerOperationProfilePort,
    WorkerAuthorityLimitsV1,
)
from ksi_processing_controller.external_display_publication import (
    RetainedSanitizedCandidateOwnerPort,
)
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedByteReaderPort,
    InspectorLaunchRequestV1,
    InspectorLaunchResultV1,
    LocalLeaseFenceV1,
    ProtocolLimitsV1,
)
from ksi_processing_controller.external_measurement_client import ExternalMeasurementUdsClient
from ksi_processing_controller.external_measurement_core_client import (
    MeasurementLeaseGrantV1,
    MeasurementOperationV2,
    PendingMeasurementWorkV1,
)
from ksi_processing_controller.external_measurement_protocol import (
    MeasurementInputV2,
    MeasurementLaunchRequestV2,
)
from ksi_processing_controller.external_measurement_result import MeasurementResultV2
from ksi_processing_controller.external_object_streams import (
    ExternalObjectCapabilityV1,
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from ksi_processing_controller.external_validation_core_client import (
    ExternalDisplayUploadCapability,
    ExternalValidationCoreClient,
)
from ksi_processing_controller.external_validation_lanes import (
    InspectionCorePort,
    InspectionLaneDependencies,
    InspectionValidationLane,
    MeasurementCorePort,
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


def _replace_private_seam(target: object, name: str, replacement: object) -> None:
    """Install a test-only private seam without assigning through a typed method."""

    object.__setattr__(target, name, replacement)


class _InspectionQueue:
    def __init__(self) -> None:
        self.claims: list[tuple[str, str]] = []

    def list_pending(self, *, deadline_monotonic: float, limit: int = 50) -> tuple[object, ...]:
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

    def current_input(
        self, request_id: str, fence: LocalLeaseFenceV1, *, deadline_monotonic: float
    ) -> ExternalInspectionCurrentInputV1 | None:
        del request_id, fence, deadline_monotonic
        return None

    def heartbeat(
        self, request_id: str, fence: LocalLeaseFenceV1, *, deadline_monotonic: float
    ) -> bool:
        del request_id, fence, deadline_monotonic
        return False

    def capability_for(
        self, request_id: str, fence: LocalLeaseFenceV1, artifact: ExternalArtifactInputV1
    ) -> object:
        del request_id, fence, artifact
        raise AssertionError("not exercised by this queue test")

    def record_report(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        report: ExternalArtifactInspectionReportV1,
        *,
        deadline_monotonic: float,
    ) -> ExternalArtifactInspectionReportV1:
        del request_id, fence, report, deadline_monotonic
        raise AssertionError("not exercised by this queue test")

    def record_incomplete_failure(
        self, request_id: str, fence: LocalLeaseFenceV1, reason: str, *, deadline_monotonic: float
    ) -> object:
        del request_id, fence, reason, deadline_monotonic
        return object()

    def release(self, request_id: str, fence: LocalLeaseFenceV1) -> None:
        del request_id, fence

    def grant_display_upload(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        declaration: SanitizedDisplayDeclarationV1,
        *,
        deadline_monotonic: float,
    ) -> ExternalDisplayUploadCapability:
        del request_id, fence, declaration, deadline_monotonic
        raise AssertionError("not exercised by this queue test")

    def seal_display_upload(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        grant: ExternalDisplayUploadCapability,
        *,
        deadline_monotonic: float,
    ) -> SanitizedDisplayReceiptV1:
        del request_id, fence, grant, deadline_monotonic
        raise AssertionError("not exercised by this queue test")


def test_inspection_lane_polls_and_claims_exact_request_with_runner_acquisition() -> None:
    core = _InspectionQueue()
    lane = InspectionValidationLane(
        core=cast(InspectionCorePort, core),
        worker_instance_id=_fence().worker_instance_id,
        dependencies=InspectionLaneDependencies(
            launcher=cast(ExternalInspectorLaunchPort, object()),
            operation_profile=cast(InspectorWorkerOperationProfilePort, object()),
            candidate_sink=cast(RetainedSanitizedCandidateOwnerPort, object()),
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

    def list_pending(
        self, operation: MeasurementOperationV2, *, deadline_monotonic: float, limit: int = 50
    ) -> tuple[object, ...]:
        assert deadline_monotonic == 10.0
        assert limit == 1
        return (PendingMeasurementWorkV1(operation, "volume-request", datetime.now(UTC)),)

    def claim(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        *,
        worker_instance_id: str,
        acquisition_id: str,
        deadline_monotonic: float,
    ) -> MeasurementLeaseGrantV1:
        del worker_instance_id
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
        core=cast(MeasurementCorePort, core),
        worker_instance_id=_fence().worker_instance_id,
        dependencies=MeasurementLaneDependencies(
            manifest=_volume_launch_with_records()[0],
            uds_client=cast(ExternalMeasurementUdsClient, object()),
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
    def __init__(
        self,
        manifest: InspectorExecutionManifestV1,
        template: MeasurementLaunchRequestV2,
        object_url: str,
    ) -> None:
        self._manifest = manifest
        self._template = template
        self._object_url = object_url
        self.submitted: list[tuple[MeasurementLaunchRequestV2, MeasurementResultV2]] = []
        self.incomplete: list[str] = []

    def list_pending(
        self, operation: MeasurementOperationV2, *, deadline_monotonic: float, limit: int = 50
    ) -> tuple[object, ...]:
        del operation, deadline_monotonic, limit
        raise AssertionError("execution test does not poll")

    def claim(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        *,
        worker_instance_id: str,
        acquisition_id: str,
        deadline_monotonic: float,
    ) -> MeasurementLeaseGrantV1:
        del operation, request_id, worker_instance_id, acquisition_id, deadline_monotonic
        raise AssertionError("execution test does not claim")

    def current_input(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        fence: LocalLeaseFenceV1,
        *,
        attempt_nonce: str,
        deadline_monotonic: float,
    ) -> MeasurementLaunchRequestV2 | None:
        assert operation == "RELATIVE_VOLUME"
        assert request_id == self._template.request_id
        assert deadline_monotonic > time.monotonic()
        return self._template.model_copy(
            update={"fence": fence, "attempt_nonce": attempt_nonce, "canonical_input_digest": None}
        ).sealed()

    def heartbeat(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        fence: LocalLeaseFenceV1,
        *,
        deadline_monotonic: float,
    ) -> MeasurementLeaseGrantV1:
        assert operation == "RELATIVE_VOLUME"
        return MeasurementLeaseGrantV1(
            operation=operation,
            request_id=request_id,
            fence=fence,
            lease_expires_at=datetime.now(UTC),
        )

    def capability_for(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        fence: LocalLeaseFenceV1,
        artifact: MeasurementInputV2,
    ) -> ExternalObjectCapabilityV1:
        del operation, request_id, fence
        return ExternalObjectCapabilityV1(
            artifact=artifact, url=self._object_url, required_headers={}
        )

    def submit_result(
        self,
        launch: MeasurementLaunchRequestV2,
        result: MeasurementResultV2,
        *,
        manifest: InspectorExecutionManifestV1,
        limits: ProtocolLimitsV1,
        computed_at: datetime,
        deadline_monotonic: float,
    ) -> None:
        assert manifest == self._manifest
        assert limits == measurement_limits()
        assert deadline_monotonic > time.monotonic()
        assert computed_at.tzinfo is not None
        self.submitted.append((launch, result))

    def record_incomplete_failure(
        self,
        operation: MeasurementOperationV2,
        request_id: str,
        fence: LocalLeaseFenceV1,
        reason: str,
        *,
        deadline_monotonic: float,
    ) -> None:
        del operation, request_id, fence, deadline_monotonic
        self.incomplete.append(reason)

    def release(
        self, operation: MeasurementOperationV2, request_id: str, fence: LocalLeaseFenceV1
    ) -> None:
        del operation, request_id, fence


class _ResultUdsClient:
    def __init__(self) -> None:
        self.calls: list[MeasurementLaunchRequestV2] = []

    def execute(
        self,
        *,
        request: MeasurementLaunchRequestV2,
        manifest: InspectorExecutionManifestV1,
        sources: tuple[DeadlineBoundedByteReaderPort, DeadlineBoundedByteReaderPort],
        deadline_monotonic: float,
        authority_is_current: Callable[[], bool],
    ) -> MeasurementResultV2:
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
            core=cast(MeasurementCorePort, core),
            worker_instance_id=_fence().worker_instance_id,
            dependencies=MeasurementLaneDependencies(
                manifest=manifest,
                uds_client=cast(ExternalMeasurementUdsClient, uds),
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
            core=cast(MeasurementCorePort, core),
            worker_instance_id=_fence().worker_instance_id,
            dependencies=MeasurementLaneDependencies(
                manifest=manifest,
                uds_client=cast(ExternalMeasurementUdsClient, _ResultUdsClient()),
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
    _replace_private_seam(
        core,
        "record_incomplete_failure",
        lambda request_id, fence, reason, **_kwargs: incomplete.append(reason),
    )
    lane = InspectionValidationLane(
        core=cast(InspectionCorePort, core),
        worker_instance_id=_fence().worker_instance_id,
        dependencies=InspectionLaneDependencies(
            launcher=cast(ExternalInspectorLaunchPort, object()),
            operation_profile=cast(InspectorWorkerOperationProfilePort, object()),
            candidate_sink=cast(RetainedSanitizedCandidateOwnerPort, object()),
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
    _replace_private_seam(
        lane,
        "_current",
        lambda *_args: SimpleNamespace(phase=ExternalInspectionPhaseV1.DISPLAY),
    )

    def lose_authority(*_args: object) -> None:
        raise CurrentAuthorityLost("display authority changed")

    _replace_private_seam(lane, "_execute_display", lose_authority)

    assert lane.execute(lease, deadline_monotonic=10.0, stop=Event()) is TurnOutcome.DEFERRED
    assert incomplete == []


def test_measurement_guard_rechecks_stop_after_heartbeat_callback() -> None:
    """A stop raised during heartbeat cannot authorize the following UDS operation."""

    manifest, launch = _volume_launch_with_records()
    stop = Event()

    class _Core:
        def heartbeat(
            self,
            operation: MeasurementOperationV2,
            request_id: str,
            fence: LocalLeaseFenceV1,
            *,
            deadline_monotonic: float,
        ) -> MeasurementLeaseGrantV1:
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
        core=cast(MeasurementCorePort, _Core()),
        worker_instance_id=_fence().worker_instance_id,
        dependencies=MeasurementLaneDependencies(
            manifest=manifest,
            uds_client=cast(ExternalMeasurementUdsClient, object()),
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
    def execute(
        self,
        *,
        request: InspectorLaunchRequestV1,
        source: DeadlineBoundedByteReaderPort,
        artifact_kind: ProcessingArtifactKind,
        content_type: str,
        deadline_monotonic: float,
        authority_is_current: Callable[[], bool],
    ) -> InspectorLaunchResultV1:
        del artifact_kind, authority_is_current, content_type, deadline_monotonic, source
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
    sink: RetainedSanitizedCandidateOwnerPort, *, object_origin: str = "http://127.0.0.1:1"
) -> InspectionValidationLane:
    return InspectionValidationLane(
        core=cast(InspectionCorePort, object()),
        worker_instance_id=_fence().worker_instance_id,
        dependencies=InspectionLaneDependencies(
            launcher=cast(ExternalInspectorLaunchPort, object()),
            operation_profile=cast(InspectorWorkerOperationProfilePort, object()),
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
    tmp_path: Path,
) -> None:
    """The lane, rather than a later turn, owns a sealed candidate after SANITIZE."""

    context, sink, root = _retained_context(tmp_path, b"sanitized-derivative")
    stop = Event()
    lane = _display_lane_with_retained_candidate(sink)

    class _Worker:
        def launch_artifact_context(
            self, *_args: object, **_kwargs: object
        ) -> ExternalInspectorLaunchContextV1:
            stop.set()
            return context

    _replace_private_seam(lane, "_worker_for", lambda *_args: _Worker())
    _replace_private_seam(lane, "_is_current", lambda *_args: not stop.is_set())
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
    tmp_path: Path,
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
            def launch_artifact_context(
                self, *_args: object, **_kwargs: object
            ) -> ExternalInspectorLaunchContextV1:
                return context

        _replace_private_seam(lane, "_core", cast(InspectionCorePort, core))
        _replace_private_seam(lane, "_worker_for", lambda *_args: _Worker())
        _replace_private_seam(lane, "_is_current", lambda *_args: True)
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
    tmp_path: Path,
) -> None:
    """The sealed Core receipt, not a now-spent DISPLAY lease, completes publication."""

    payload = b"sanitized-derivative"
    context, sink, root = _retained_context(tmp_path, payload)
    with _PutServer() as put_server:
        lane = _display_lane_with_retained_candidate(
            sink, object_origin=f"http://127.0.0.1:{put_server.port}"
        )

        class _Worker:
            def launch_artifact_context(
                self, *_args: object, **_kwargs: object
            ) -> ExternalInspectorLaunchContextV1:
                return context

        _replace_private_seam(
            lane, "_core", cast(InspectionCorePort, _DisplayPublicationCore(put_server.url))
        )
        _replace_private_seam(lane, "_worker_for", lambda *_args: _Worker())
        current_checks = 0

        def is_current(*_args: object) -> bool:
            nonlocal current_checks
            current_checks += 1
            return current_checks == 1

        _replace_private_seam(lane, "_is_current", is_current)
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """KeyboardInterrupt preserves itself while the exact sealed candidate is retired."""

    context, sink, root = _retained_context(tmp_path, b"sanitized-derivative")
    lane = _display_lane_with_retained_candidate(sink)

    class _Worker:
        def launch_artifact_context(
            self, *_args: object, **_kwargs: object
        ) -> ExternalInspectorLaunchContextV1:
            return context

    class _InterruptedPublication:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def publish(self, _context: ExternalInspectorLaunchContextV1) -> None:
            raise KeyboardInterrupt("synthetic interruption")

    monkeypatch.setattr(
        "ksi_processing_controller.external_validation_lanes.ExternalDisplayPublicationWorker",
        _InterruptedPublication,
    )
    _replace_private_seam(lane, "_worker_for", lambda *_args: _Worker())
    _replace_private_seam(lane, "_is_current", lambda *_args: True)
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
    def allows(self, **_kwargs: object) -> InspectorOperationProfileDecision:
        return InspectorOperationProfileDecision.ALLOW


class _LoopbackObjectCore:
    def __init__(self, core: ExternalValidationCoreClient, object_url: str) -> None:
        self._core = core
        self._object_url = object_url

    def __getattr__(self, name: str) -> Any:
        return getattr(self._core, name)

    def capability_for(
        self, request_id: str, fence: LocalLeaseFenceV1, artifact: ExternalArtifactInputV1
    ) -> ExternalObjectCapabilityV1:
        self._core.capability_for(request_id, fence, artifact)
        return ExternalObjectCapabilityV1(
            artifact=artifact, url=self._object_url, required_headers={}
        )


def test_inspection_phase_records_complete_report_through_actual_core_and_loopback_object(
    tmp_path: Path,
) -> None:
    app, _issued_request, policy, _storage, _submission_ref = _active_scoped_app(tmp_path)
    assert isinstance(policy, ExternalValidationPolicyV1)
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
                        candidate_sink=cast(RetainedSanitizedCandidateOwnerPort, object()),
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
