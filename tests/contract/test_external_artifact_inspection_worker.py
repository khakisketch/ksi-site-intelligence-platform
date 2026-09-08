"""Contract tests for processing-controller's Core-authority adapter.

The ports in this file are synthetic.  They establish no Core HTTP route,
external storage fetch, parser support, identity provisioning, or sandbox run.
"""

from __future__ import annotations

import hashlib
import socket
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from typing import BinaryIO

import pytest
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    ExternalArtifactInspectionReportV1,
    ExternalArtifactInspectionRequestV1,
    ExternalInspectionMeasurementPayloadV1,
    ExternalValidationPolicyV1,
    NodataRepresentation,
    PolicyStatus,
    RasterMeasurementsV1,
    ResourceEnvelopeV1,
    SealedArtifactBindingV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller.external_artifact_inspection_worker import (
    CurrentAuthorityLost,
    ExternalArtifactInputV1,
    ExternalArtifactInspectionWorker,
    ExternalInspectionCurrentInputV1,
    ExternalInspectionNextActionV1,
    ExternalInspectionPhaseV1,
    ExternalInspectorUdsClient,
    WorkerAuthorityLimitsV1,
)
from ksi_processing_controller.external_inspector_launcher import InspectorOperationProfileDecision
from ksi_processing_controller.external_inspector_protocol import (
    InspectorLaunchRequestV1,
    InspectorLaunchResultV1,
    InspectorOperation,
    LocalLeaseFenceV1,
    ProtocolLimitsV1,
    SealedByteBindingV1,
    read_bound_bytes,
    read_launch_request_header,
    write_launch_result,
)

_WORKER_ID = "123e4567-e89b-42d3-a456-426614174000"
_ACQUISITION_ID = "123e4567-e89b-42d3-a456-426614174002"


def _digest(marker: str) -> str:
    return "sha256:" + marker * 64


def _bytes_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _subject() -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="organization-1",
        site_id="site-1",
        work_order_id="work-order-1",
        submission_id="submission-1",
        revision=1,
        submission_digest=_digest("a"),
        manifest_digest=_digest("b"),
    )


def _policy() -> ExternalValidationPolicyV1:
    envelope = ResourceEnvelopeV1(
        max_input_bytes=128,
        max_streamed_bytes=128,
        max_tiff_directories=4,
        max_tiff_entries=32,
        max_pixels=1_000,
        max_bands=4,
        max_blocks=64,
        max_decompressed_bytes=1_024,
        max_sample_bytes=1_024,
        max_geometry_vertices=64,
        max_cpu_seconds=2.0,
        max_memory_bytes=1_024,
        max_workspace_bytes=1_024,
        max_output_bytes=1_024,
        max_tenant_concurrency=1,
        max_queue_depth=4,
        max_deadline_seconds=10.0,
        lease_duration_seconds=2.0,
        max_retry_attempts=1,
    ).sealed()
    return ExternalValidationPolicyV1(
        policy_id="synthetic-policy",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=_digest("c"),
        grammar_digest=_digest("d"),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=_digest("e"),
        inspection_rule_ids=(),
        evidence_rule_ids=(),
        compatibility_mapping_digests=(),
        synthetic_test_only=True,
    ).sealed()


def _request(policy: ExternalValidationPolicyV1) -> ExternalArtifactInspectionRequestV1:
    assert policy.policy_digest is not None
    return ExternalArtifactInspectionRequestV1(
        request_id="inspection-request-1",
        subject=_subject(),
        inspection_policy_id=policy.policy_id,
        inspection_policy_version=policy.version,
        inspection_policy_digest=policy.policy_digest,
        issued_at=datetime(2026, 9, 7, tzinfo=UTC),
        idempotency_key="inspection-key-1",
    )


def _artifact(
    payload: bytes = b"sealed-ortho",
    *,
    kind: ProcessingArtifactKind = ProcessingArtifactKind.ORTHO,
    content_type: str = "image/tiff",
) -> ExternalArtifactInputV1:
    return ExternalArtifactInputV1(
        entry_id="ortho",
        kind=kind,
        observed_sha256=_bytes_digest(payload),
        observed_size_bytes=len(payload),
        content_type=content_type,
    )


def _fence() -> LocalLeaseFenceV1:
    return LocalLeaseFenceV1(
        worker_instance_id=_WORKER_ID,
        lease_acquisition_id=_ACQUISITION_ID,
        lease_generation=1,
    )


def _accepted_report(
    request: ExternalArtifactInspectionRequestV1, policy: ExternalValidationPolicyV1
) -> ExternalArtifactInspectionReportV1:
    assert policy.policy_digest is not None
    artifact = _artifact()
    binding = SealedArtifactBindingV1(
        artifact_id=artifact.entry_id, observed_sha256=artifact.observed_sha256
    )
    outcome = ArtifactInspectionOutcomeV1(
        artifact_id=artifact.entry_id,
        observed_sha256=artifact.observed_sha256,
        outcome=ArtifactOutcome.MEASURED,
        measurements=RasterMeasurementsV1(
            observed_crs_identifier="EPSG:5186",
            observed_crs_digest=_digest("1"),
            transform=(1.0, 0.0, 0.0, 0.0, -1.0, 2.0),
            footprint_wkt="POLYGON((0 0,2 0,2 2,0 2,0 0))",
            footprint_digest=_digest("2"),
            width=2,
            height=2,
            band_count=1,
            dtype="uint8",
            layout="striped",
            nodata_representation=NodataRepresentation.NONE,
            valid_pixel_count=4,
        ),
    )
    payload = ExternalInspectionMeasurementPayloadV1(
        subject_digest=request.subject.canonical_digest(),
        sealed_manifest_digest=request.subject.manifest_digest,
        inspection_policy_digest=policy.policy_digest,
        inspector_build_digest=policy.parser_build_digest,
        artifact_bindings=(binding,),
        outcomes=(outcome,),
    )
    return ExternalArtifactInspectionReportV1(
        report_id="report-1",
        request_id=request.request_id,
        subject=request.subject,
        subject_digest=request.subject.canonical_digest(),
        sealed_manifest_digest=request.subject.manifest_digest,
        inspection_policy_digest=policy.policy_digest,
        inspector_build_digest=policy.parser_build_digest,
        measurement_payload=payload,
        worker_instance_id=_WORKER_ID,
        lease_acquisition_id=_ACQUISITION_ID,
        lease_generation=1,
        reported_at=datetime(2026, 9, 7, tzinfo=UTC),
    ).sealed()


def _input(
    *,
    phase: ExternalInspectionPhaseV1 = ExternalInspectionPhaseV1.INSPECTION,
    next_action: ExternalInspectionNextActionV1 = ExternalInspectionNextActionV1.INSPECT,
    artifact: ExternalArtifactInputV1 | None = None,
    accepted_report: ExternalArtifactInspectionReportV1 | None = None,
) -> ExternalInspectionCurrentInputV1:
    policy = _policy()
    request = _request(policy)
    return ExternalInspectionCurrentInputV1(
        request=request,
        policy=policy,
        artifacts=(artifact or _artifact(),),
        phase=phase,
        next_action=next_action,
        accepted_report=accepted_report,
    )


class _Authority:
    def __init__(
        self, current: ExternalInspectionCurrentInputV1 | None, heartbeats: list[bool]
    ) -> None:
        self.current = current
        self.heartbeats = heartbeats
        self.current_calls = 0
        self.heartbeat_calls = 0

    def current_input(
        self, request_id: str, fence: LocalLeaseFenceV1, *, deadline_monotonic: float
    ) -> ExternalInspectionCurrentInputV1 | None:
        del request_id, fence, deadline_monotonic
        self.current_calls += 1
        return self.current

    def heartbeat(
        self, request_id: str, fence: LocalLeaseFenceV1, *, deadline_monotonic: float
    ) -> bool:
        del request_id, fence, deadline_monotonic
        self.heartbeat_calls += 1
        return self.heartbeats.pop(0) if self.heartbeats else False


class _ByteSource:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def open_bound_bytes(
        self, artifact: ExternalArtifactInputV1, *, deadline_monotonic: float
    ) -> BytesIO:
        del deadline_monotonic
        self.calls.append(artifact.entry_id)
        return BytesIO(self.payload)


class _Launcher:
    def __init__(self, *, lose_authority_during_wait: bool = False) -> None:
        self.lose_authority_during_wait = lose_authority_during_wait
        self.requests: list[InspectorLaunchRequestV1] = []
        self.metadata: list[tuple[ProcessingArtifactKind, str]] = []

    def execute(
        self,
        *,
        request: InspectorLaunchRequestV1,
        source: BinaryIO,
        artifact_kind: ProcessingArtifactKind,
        content_type: str,
        deadline_monotonic: float,
        authority_is_current: Callable[[], bool],
    ) -> InspectorLaunchResultV1:
        del source, deadline_monotonic
        self.requests.append(request)
        self.metadata.append((artifact_kind, content_type))
        if self.lose_authority_during_wait:
            assert authority_is_current() is False
            raise CurrentAuthorityLost("authority lost while waiting for launcher")
        if request.operation is InspectorOperation.SANITIZE:
            return InspectorLaunchResultV1.completed_sanitized(
                request.attempt_nonce,
                request.canonical_input_digest,
                request.policy.parser_build_digest,
                1,
                _bytes_digest(b"x"),
            )
        outcome = ArtifactInspectionOutcomeV1(
            artifact_id=request.sealed_byte_binding.artifact_id,
            observed_sha256=request.sealed_byte_binding.observed_sha256,
            outcome=ArtifactOutcome.REJECTED,
            reason="SYNTHETIC_REJECTED",
        )
        return InspectorLaunchResultV1.completed_inspection(
            request.attempt_nonce,
            request.canonical_input_digest,
            request.policy.parser_build_digest,
            outcome,
        )


class _Profile:
    def __init__(
        self, decision: InspectorOperationProfileDecision = InspectorOperationProfileDecision.ALLOW
    ) -> None:
        self.decision = decision
        self.calls: list[tuple[ProcessingArtifactKind, str, InspectorOperation]] = []

    def allows(
        self,
        *,
        parser_build_digest: str,
        grammar_digest: str,
        artifact_kind: ProcessingArtifactKind,
        content_type: str,
        operation: InspectorOperation,
        deadline_monotonic: float,
    ) -> InspectorOperationProfileDecision:
        del parser_build_digest, grammar_digest, deadline_monotonic
        self.calls.append((artifact_kind, content_type, operation))
        return self.decision


def _worker(
    authority: _Authority,
    source: _ByteSource,
    launcher: _Launcher,
    profile: _Profile | None = None,
) -> ExternalArtifactInspectionWorker:
    return ExternalArtifactInspectionWorker(
        authority=authority,
        byte_source=source,
        launcher=launcher,
        operation_profile=profile or _Profile(),
        limits=WorkerAuthorityLimitsV1(
            heartbeat_interval_millis=50,
            max_authority_wait_millis=500,
        ),
        attempt_nonce_factory=lambda: "attempt-nonce-1",
        monotonic=lambda: 100.0,
    )


def _protocol_limits() -> ProtocolLimitsV1:
    return ProtocolLimitsV1(
        max_header_bytes=16_384,
        max_chunk_bytes=64,
        max_input_bytes=1_024,
        max_output_bytes=1_024,
        max_wire_duration_millis=1_000,
    )


def test_current_authority_and_heartbeat_are_required_before_opening_bytes() -> None:
    """Caching an old Core response or opening a capability before a fence check leaks authority."""
    source = _ByteSource(b"sealed-ortho")
    launcher = _Launcher()
    worker = _worker(_Authority(None, []), source, launcher)

    with pytest.raises(CurrentAuthorityLost):
        worker.launch_artifact("inspection-request-1", _fence(), "ortho")

    assert source.calls == []
    assert launcher.requests == []


def test_current_input_rejects_nonactive_or_unsealed_policy_before_source_authority() -> None:
    """A policy projection that cannot produce a sealed request must not reach byte access."""
    policy = (
        _policy()
        .model_copy(update={"status": PolicyStatus.REVOKED, "policy_digest": None})
        .sealed()
    )

    with pytest.raises(ValueError, match="policy"):
        ExternalInspectionCurrentInputV1(
            request=_request(policy),
            policy=policy,
            artifacts=(_artifact(),),
            phase=ExternalInspectionPhaseV1.INSPECTION,
            next_action=ExternalInspectionNextActionV1.INSPECT,
        )


def test_inspection_uses_only_current_sealed_fields_and_never_filename_or_capability() -> None:
    """A source URL, header, or filename must not become a runtime input."""
    current = _input()
    source = _ByteSource(b"sealed-ortho")
    launcher = _Launcher()
    authority = _Authority(current, [True, True])
    result = _worker(authority, source, launcher).launch_artifact(
        current.request.request_id, _fence(), "ortho"
    )

    assert result.result == "COMPLETED"
    assert source.calls == ["ortho"]
    assert launcher.metadata == [(ProcessingArtifactKind.ORTHO, "image/tiff")]
    launch = launcher.requests[0]
    assert launch.operation is InspectorOperation.INSPECT
    assert launch.request == current.request
    assert launch.subject == current.request.subject
    assert launch.policy == current.policy
    assert launch.sealed_byte_binding.artifact_id == "ortho"
    assert "url" not in repr(launch).lower()
    assert authority.current_calls == 2  # before launch and before returning success


def test_sanitize_requires_display_phase_retained_measured_ortho_and_exact_binding() -> None:
    """A DISPLAY takeover may sanitize only the exact report-backed ORTHO, never a new input."""
    policy = _policy()
    request = _request(policy)
    report = _accepted_report(request, policy)
    current = ExternalInspectionCurrentInputV1(
        request=request,
        policy=policy,
        artifacts=(_artifact(),),
        phase=ExternalInspectionPhaseV1.DISPLAY,
        next_action=ExternalInspectionNextActionV1.SANITIZE_DISPLAY,
        accepted_report=report,
    )
    source = _ByteSource(b"sealed-ortho")
    launcher = _Launcher()
    result = _worker(_Authority(current, [True, True]), source, launcher).launch_artifact(
        request.request_id, _fence(), "ortho"
    )

    assert result.result == "COMPLETED"
    assert launcher.requests[0].operation is InspectorOperation.SANITIZE

    missing_report = ExternalInspectionCurrentInputV1(
        request=request,
        policy=policy,
        artifacts=(_artifact(),),
        phase=ExternalInspectionPhaseV1.DISPLAY,
        next_action=ExternalInspectionNextActionV1.SANITIZE_DISPLAY,
        accepted_report=None,
    )
    denied_source = _ByteSource(b"sealed-ortho")
    with pytest.raises(CurrentAuthorityLost, match="retained"):
        _worker(_Authority(missing_report, [True]), denied_source, _Launcher()).launch_artifact(
            request.request_id, _fence(), "ortho"
        )
    assert denied_source.calls == []


@pytest.mark.parametrize(
    "kind",
    [ProcessingArtifactKind.DTM, ProcessingArtifactKind.MESH, ProcessingArtifactKind.POINT_CLOUD],
)
def test_worker_rejects_unapproved_inspection_kinds_before_source_open(
    kind: ProcessingArtifactKind,
) -> None:
    """All manifest entries must not silently expand the approved raster lane."""
    current = _input(artifact=_artifact(kind=kind))
    source = _ByteSource(b"sealed-ortho")
    with pytest.raises(CurrentAuthorityLost, match="operation"):
        _worker(_Authority(current, [True]), source, _Launcher()).launch_artifact(
            current.request.request_id, _fence(), "ortho"
        )
    assert source.calls == []


def test_lost_heartbeat_during_launcher_wait_cancels_and_cannot_return_success() -> None:
    """A stale fence after a local result must close the attempt, not return it."""
    current = _input()
    source = _ByteSource(b"sealed-ortho")
    launcher = _Launcher(lose_authority_during_wait=True)
    authority = _Authority(current, [True, False])

    with pytest.raises(CurrentAuthorityLost, match="authority lost"):
        _worker(authority, source, launcher).launch_artifact(
            current.request.request_id, _fence(), "ortho"
        )
    assert authority.current_calls == 1
    assert authority.heartbeat_calls == 2


def test_mime_is_not_a_profile_default_and_denial_happens_before_byte_source_open() -> None:
    """Synthetic image/tiff never becomes a production parser support claim by itself."""
    current = _input(artifact=_artifact(content_type="application/octet-stream"))
    source = _ByteSource(b"sealed-ortho")

    with pytest.raises(CurrentAuthorityLost, match="profile"):
        _worker(
            _Authority(current, []),
            source,
            _Launcher(),
            profile=_Profile(InspectorOperationProfileDecision.DENY),
        ).launch_artifact(current.request.request_id, _fence(), "ortho")

    assert source.calls == []


def test_uds_client_validates_sanitized_raw_bytes_and_eof_through_required_sink() -> None:
    """The client forwards only result-bound raw bytes to an injected bounded sink."""

    class _Sink:
        def __init__(self) -> None:
            self.chunks: list[bytes] = []
            self.deadlines: list[float] = []

        def write(self, chunk: bytes, *, deadline_monotonic: float) -> None:
            self.chunks.append(chunk)
            self.deadlines.append(deadline_monotonic)

    policy = _policy()
    payload = b"sealed-ortho"
    request = InspectorLaunchRequestV1.seal(
        operation=InspectorOperation.SANITIZE,
        request=_request(policy),
        fence=_fence(),
        subject=_subject(),
        sealed_byte_binding=SealedByteBindingV1(
            artifact_id="ortho",
            observed_sha256=_bytes_digest(payload),
            observed_size_bytes=len(payload),
        ),
        policy=policy,
        attempt_nonce="attempt-nonce-1",
    )
    output = b"sanitized-output"
    client_socket, server_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    errors: list[BaseException] = []

    def serve() -> None:
        try:
            received = read_launch_request_header(server_socket, _protocol_limits())
            read_bound_bytes(
                server_socket,
                received.sealed_byte_binding,
                _protocol_limits(),
                lambda _: None,
            )
            write_launch_result(
                server_socket,
                InspectorLaunchResultV1.accepted(received.attempt_nonce),
                _protocol_limits(),
            )
            write_launch_result(
                server_socket,
                InspectorLaunchResultV1.completed_sanitized(
                    received.attempt_nonce,
                    received.canonical_input_digest,
                    received.policy.parser_build_digest,
                    len(output),
                    _bytes_digest(output),
                ),
                _protocol_limits(),
            )
            server_socket.sendall(output)
            server_socket.shutdown(socket.SHUT_WR)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            server_socket.close()

    thread = threading.Thread(target=serve)
    thread.start()
    sink = _Sink()
    client = ExternalInspectorUdsClient(
        connect=lambda deadline: client_socket,
        protocol_limits=_protocol_limits(),
        sanitized_output_sink=sink,
        heartbeat_interval_millis=10,
    )
    try:
        terminal = client.execute(
            request=request,
            source=BytesIO(payload),
            artifact_kind=ProcessingArtifactKind.ORTHO,
            content_type="application/octet-stream",
            deadline_monotonic=__import__("time").monotonic() + 0.5,
            authority_is_current=lambda: True,
        )
    finally:
        thread.join(timeout=1)
    assert not errors
    assert not thread.is_alive()
    assert terminal.result == "COMPLETED"
    assert b"".join(sink.chunks) == output
    assert sink.deadlines


def test_uds_client_stops_a_chunked_upload_when_authority_is_lost() -> None:
    """Losing the fence between upload chunks must prevent later sealed bytes reaching the peer."""

    class _Sink:
        def write(self, chunk: bytes, *, deadline_monotonic: float) -> None:
            del chunk, deadline_monotonic

    class _SlowUploadSource(BytesIO):
        def __init__(self, payload: bytes) -> None:
            super().__init__(payload)
            self.read_calls = 0
            self.authority_is_current = True

        def read(self, size: int | None = -1) -> bytes:
            chunk = super().read(-1 if size is None else size)
            self.read_calls += 1
            if self.read_calls == 2:
                self.authority_is_current = False
            return chunk

    policy = _policy()
    payload = b"a" * 128
    request = InspectorLaunchRequestV1.seal(
        operation=InspectorOperation.INSPECT,
        request=_request(policy),
        fence=_fence(),
        subject=_subject(),
        sealed_byte_binding=SealedByteBindingV1(
            artifact_id="ortho",
            observed_sha256=_bytes_digest(payload),
            observed_size_bytes=len(payload),
        ),
        policy=policy,
        attempt_nonce="attempt-nonce-1",
    )
    client_socket, server_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    received: list[InspectorLaunchRequestV1] = []
    uploaded = bytearray()
    errors: list[BaseException] = []

    def serve() -> None:
        try:
            received.append(read_launch_request_header(server_socket, _protocol_limits()))
            while chunk := server_socket.recv(64):
                uploaded.extend(chunk)
        except BaseException as exc:  # pragma: no cover - surfaced below
            errors.append(exc)
        finally:
            server_socket.close()

    thread = threading.Thread(target=serve)
    thread.start()
    source = _SlowUploadSource(payload)
    client = ExternalInspectorUdsClient(
        connect=lambda deadline: client_socket,
        protocol_limits=_protocol_limits(),
        sanitized_output_sink=_Sink(),
        heartbeat_interval_millis=10,
    )
    with pytest.raises(CurrentAuthorityLost, match="UDS launch failed closed"):
        client.execute(
            request=request,
            source=source,
            artifact_kind=ProcessingArtifactKind.ORTHO,
            content_type="image/tiff",
            deadline_monotonic=__import__("time").monotonic() + 0.5,
            authority_is_current=lambda: source.authority_is_current,
        )
    thread.join(timeout=1)

    assert not errors
    assert not thread.is_alive()
    assert received == [request]
    assert source.read_calls == 2
    assert uploaded == payload[:64]


def test_worker_rejects_a_current_input_that_returns_after_its_absolute_deadline() -> None:
    """A late final Core projection cannot return an already-completed launcher result."""

    class _Clock:
        def __init__(self) -> None:
            self.now = 100.0

        def __call__(self) -> float:
            return self.now

    class _LateFinalAuthority(_Authority):
        def __init__(self, current: ExternalInspectionCurrentInputV1, clock: _Clock) -> None:
            super().__init__(current, [True, True])
            self._clock = clock

        def current_input(
            self, request_id: str, fence: LocalLeaseFenceV1, *, deadline_monotonic: float
        ) -> ExternalInspectionCurrentInputV1 | None:
            current = super().current_input(
                request_id, fence, deadline_monotonic=deadline_monotonic
            )
            if self.current_calls == 2:
                self._clock.now = 101.5
            return current

    clock = _Clock()
    current = _input()
    worker = ExternalArtifactInspectionWorker(
        authority=_LateFinalAuthority(current, clock),
        byte_source=_ByteSource(b"sealed-ortho"),
        launcher=_Launcher(),
        operation_profile=_Profile(),
        limits=WorkerAuthorityLimitsV1(
            heartbeat_interval_millis=50,
            max_authority_wait_millis=500,
        ),
        attempt_nonce_factory=lambda: "attempt-nonce-1",
        monotonic=clock,
    )

    with pytest.raises(CurrentAuthorityLost, match="deadline"):
        worker.launch_artifact(current.request.request_id, _fence(), "ortho")


def test_worker_closes_a_late_returned_byte_source_before_launcher_invocation() -> None:
    """A source returned after the fence deadline belongs to the worker until it is closed."""

    class _Clock:
        def __init__(self) -> None:
            self.now = 100.0

        def __call__(self) -> float:
            return self.now

    class _LateByteSource:
        def __init__(self, clock: _Clock) -> None:
            self._clock = clock
            self.returned: BytesIO | None = None

        def open_bound_bytes(
            self, artifact: ExternalArtifactInputV1, *, deadline_monotonic: float
        ) -> BytesIO:
            del artifact, deadline_monotonic
            self.returned = BytesIO(b"sealed-ortho")
            self._clock.now = 101.5
            return self.returned

    clock = _Clock()
    current = _input()
    source = _LateByteSource(clock)
    launcher = _Launcher()
    worker = ExternalArtifactInspectionWorker(
        authority=_Authority(current, [True]),
        byte_source=source,
        launcher=launcher,
        operation_profile=_Profile(),
        limits=WorkerAuthorityLimitsV1(
            heartbeat_interval_millis=50,
            max_authority_wait_millis=500,
        ),
        attempt_nonce_factory=lambda: "attempt-nonce-1",
        monotonic=clock,
    )

    with pytest.raises(CurrentAuthorityLost, match="deadline"):
        worker.launch_artifact(current.request.request_id, _fence(), "ortho")

    assert source.returned is not None
    assert source.returned.closed is True
    assert launcher.requests == []
