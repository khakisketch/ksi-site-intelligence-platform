"""Contract tests for processing-controller's Core-authority adapter.

The ports in this file are synthetic.  They establish no Core HTTP route,
external storage fetch, parser support, identity provisioning, or sandbox run.
"""

from __future__ import annotations

import hashlib
import socket
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

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
    ExternalArtifactByteSourcePort,
    ExternalArtifactInputV1,
    ExternalArtifactInspectionWorker,
    ExternalInspectionCurrentInputV1,
    ExternalInspectionNextActionV1,
    ExternalInspectionPhaseV1,
    ExternalInspectorUdsClient,
    FileSystemSanitizedOutputSink,
    InspectionAssemblyIncomplete,
    WorkerAuthorityLimitsV1,
    _PrivateSanitizedOutputTransaction,
    assemble_complete_measurement_payload,
)
from ksi_processing_controller.external_inspector_launcher import InspectorOperationProfileDecision
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedByteReaderPort,
    DeadlineBoundedBytesReader,
    DeadlineBoundedDiscardingSink,
    InspectorLaunchRequestV1,
    InspectorLaunchResultV1,
    InspectorOperation,
    LocalLeaseFenceV1,
    ProtocolDeadline,
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


class _DeadlineBoundedTestSink:
    """Synthetic private transaction with the same bounded-sink contract as production."""

    def write_chunk(
        self,
        chunk: bytes,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> None:
        del heartbeat_interval_millis
        if wait_is_current is not None and not wait_is_current():
            raise RuntimeError("authority lost")
        deadline.remaining()
        self.write(chunk, deadline_monotonic=deadline.expires_at)  # type: ignore[attr-defined]
        if wait_is_current is not None and not wait_is_current():
            raise RuntimeError("authority lost")
        deadline.remaining()


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
            band_count=3,
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


class _ByteSource(ExternalArtifactByteSourcePort):
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def open_bound_bytes(
        self,
        artifact: ExternalArtifactInputV1,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> DeadlineBoundedByteReaderPort:
        del deadline, wait_is_current, heartbeat_interval_millis
        self.calls.append(artifact.entry_id)
        return DeadlineBoundedBytesReader(BytesIO(self.payload))


class _Launcher:
    def __init__(self, *, lose_authority_during_wait: bool = False) -> None:
        self.lose_authority_during_wait = lose_authority_during_wait
        self.requests: list[InspectorLaunchRequestV1] = []
        self.metadata: list[tuple[ProcessingArtifactKind, str]] = []
        self.aborted_private_candidates: list[InspectorLaunchRequestV1] = []

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

    def abort_private_candidate(self, request: InspectorLaunchRequestV1) -> None:
        self.aborted_private_candidates.append(request)


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


def test_worker_rejects_a_legacy_source_factory_before_its_blocking_open_runs() -> None:
    """A raw source factory cannot retain a worker while its synchronous open sleeps."""

    class _LegacyBlockingSource:
        def __init__(self) -> None:
            self.open_calls = 0

        def open_bound_bytes(self, *args: object, **kwargs: object) -> BytesIO:
            del args, kwargs
            self.open_calls += 1
            time.sleep(0.150)
            return BytesIO(b"sealed-ortho")

    source = _LegacyBlockingSource()
    started = time.monotonic()
    with pytest.raises(TypeError, match="deadline-bounded source opening"):
        ExternalArtifactInspectionWorker(
            authority=_Authority(_input(), [True]),
            byte_source=source,  # type: ignore[arg-type] - deliberate legacy source factory
            launcher=_Launcher(),
            operation_profile=_Profile(),
            limits=WorkerAuthorityLimitsV1(
                heartbeat_interval_millis=50,
                max_authority_wait_millis=500,
            ),
            attempt_nonce_factory=lambda: "attempt-nonce-1",
        )

    assert source.open_calls == 0
    assert time.monotonic() - started < 0.100


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


def test_sanitize_launch_context_retains_the_original_terminal_deadline_and_guard() -> None:
    """Display publication receives the exact completed launch without changing the old facade."""
    policy = _policy()
    request = _request(policy)
    current = ExternalInspectionCurrentInputV1(
        request=request,
        policy=policy,
        artifacts=(_artifact(),),
        phase=ExternalInspectionPhaseV1.DISPLAY,
        next_action=ExternalInspectionNextActionV1.SANITIZE_DISPLAY,
        accepted_report=_accepted_report(request, policy),
    )
    source = _ByteSource(b"sealed-ortho")
    launcher = _Launcher()
    context = _worker(_Authority(current, [True, True]), source, launcher).launch_artifact_context(
        request.request_id, _fence(), "ortho"
    )

    assert context.terminal.result == "COMPLETED"
    assert context.terminal.outcome == "SANITIZED"
    assert context.launch_request == launcher.requests[0]
    assert context.current == current
    assert context.artifact == current.artifacts[0]
    assert context.deadline.expires_at == 100.5

    terminal = _worker(
        _Authority(current, [True, True]), _ByteSource(b"sealed-ortho"), _Launcher()
    ).launch_artifact(request.request_id, _fence(), "ortho")
    assert terminal == context.terminal


def test_context_uses_callers_absolute_deadline_and_stop_aware_retained_guard() -> None:
    """A lane cannot let an inner worker renew its turn or keep running after stop."""

    current = _input()
    stop = threading.Event()
    observed: dict[str, object] = {}

    class _StopAwareLauncher(_Launcher):
        def execute(self, **kwargs):
            observed["deadline"] = kwargs["deadline_monotonic"]
            stop.set()
            observed["guard_after_stop"] = kwargs["authority_is_current"]()
            raise CurrentAuthorityLost("synthetic stop during launch")

    with pytest.raises(CurrentAuthorityLost, match="synthetic stop"):
        _worker(
            _Authority(current, [True] * 10), _ByteSource(b"sealed-ortho"), _StopAwareLauncher()
        ).launch_artifact_context(
            current.request.request_id,
            _fence(),
            "ortho",
            deadline_monotonic=100.05,
            authority_is_current=lambda: not stop.is_set(),
        )

    assert observed == {"deadline": 100.05, "guard_after_stop": False}


def test_sanitize_rejects_a_retained_report_with_a_non_ortho_measurement_model() -> None:
    """Server kind and stored measurement shape both gate a future derivative request."""
    policy = _policy()
    request = _request(policy)
    report = _accepted_report(request, policy)
    artifact = _artifact()
    mismatched_outcome = ArtifactInspectionOutcomeV1(
        artifact_id=artifact.entry_id,
        observed_sha256=artifact.observed_sha256,
        outcome=ArtifactOutcome.MEASURED,
        measurements=_measurements(bands=1, dtype="float32"),
    )
    mismatched_payload = report.measurement_payload.model_copy(
        update={"outcomes": (mismatched_outcome,)}
    )
    mismatched_report = report.model_copy(
        update={
            "measurement_payload": mismatched_payload,
            "measurement_payload_digest": None,
            "report_digest": None,
        }
    ).sealed()
    current = ExternalInspectionCurrentInputV1(
        request=request,
        policy=policy,
        artifacts=(artifact,),
        phase=ExternalInspectionPhaseV1.DISPLAY,
        next_action=ExternalInspectionNextActionV1.SANITIZE_DISPLAY,
        accepted_report=mismatched_report,
    )
    source = _ByteSource(b"sealed-ortho")

    with pytest.raises(CurrentAuthorityLost, match="measurement model"):
        _worker(_Authority(current, [True]), source, _Launcher()).launch_artifact(
            request.request_id, _fence(), artifact.entry_id
        )
    assert source.calls == []


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


def test_worker_callback_rechecks_the_full_projection_not_only_the_live_fence() -> None:
    """A renewed lease cannot retain a candidate for a changed report/policy projection."""

    current = _input()
    changed = _input(
        phase=ExternalInspectionPhaseV1.DISPLAY,
        next_action=ExternalInspectionNextActionV1.SANITIZE_DISPLAY,
    )
    source = _ByteSource(b"sealed-ortho")
    authority = _Authority(current, [True, True])

    class _ProjectionChangingLauncher(_Launcher):
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
            del request, source, artifact_kind, content_type, deadline_monotonic
            authority.current = changed
            assert authority_is_current() is False
            raise CurrentAuthorityLost("full authority projection changed")

    with pytest.raises(CurrentAuthorityLost, match="projection changed"):
        _worker(authority, source, _ProjectionChangingLauncher()).launch_artifact(
            current.request.request_id, _fence(), "ortho"
        )
    assert authority.current_calls == 2  # initial projection and the callback recheck
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


def test_uds_client_seals_sanitized_raw_bytes_in_a_private_transaction() -> None:
    """No result-bound byte becomes a handoff until its private transaction has finished."""

    class _Sink(_DeadlineBoundedTestSink):
        def __init__(self) -> None:
            self.chunks: list[bytes] = []
            self.deadlines: list[float] = []
            self.finished: InspectorLaunchResultV1 | None = None
            self.aborted = False

        def begin(
            self,
            request: InspectorLaunchRequestV1,
            *,
            maximum_bytes: int,
            deadline_monotonic: float,
        ) -> _Sink:
            assert request.sealed_byte_binding.artifact_id == "ortho"
            assert maximum_bytes > 0
            self.deadlines.append(deadline_monotonic)
            return self

        def write(self, chunk: bytes, *, deadline_monotonic: float) -> None:
            self.chunks.append(chunk)
            self.deadlines.append(deadline_monotonic)

        def finish(self, terminal: InspectorLaunchResultV1, *, deadline_monotonic: float) -> None:
            self.finished = terminal
            self.deadlines.append(deadline_monotonic)

        def abort(self) -> None:
            self.aborted = True

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
                DeadlineBoundedDiscardingSink(),
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
    connector_calls: list[tuple[float, int]] = []

    def connect(
        deadline_monotonic: float,
        *,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> socket.socket:
        connector_calls.append((deadline_monotonic, heartbeat_interval_millis))
        assert wait_is_current() is True
        return client_socket

    client = ExternalInspectorUdsClient(
        connect=connect,
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
    assert connector_calls and connector_calls[0][1] == 10
    assert terminal.result == "COMPLETED"
    assert b"".join(sink.chunks) == output
    assert sink.deadlines
    assert sink.finished == terminal
    assert sink.aborted is False


def test_uds_client_aborts_actual_private_otmpfile_candidate_on_keyboard_interrupt(
    tmp_path: Path,
) -> None:
    """A BaseException after seal retires the exact anonymous candidate before it escapes."""

    class _InterruptedTransaction:
        def __init__(self, transaction: object) -> None:
            self._transaction = transaction

        def write_chunk(
            self,
            chunk: bytes,
            *,
            deadline: ProtocolDeadline,
            wait_is_current: Callable[[], bool] | None,
            heartbeat_interval_millis: int | None,
        ) -> None:
            self._transaction.write_chunk(  # type: ignore[attr-defined]
                chunk,
                deadline=deadline,
                wait_is_current=wait_is_current,
                heartbeat_interval_millis=heartbeat_interval_millis,
            )

        def finish(self, terminal: InspectorLaunchResultV1, *, deadline_monotonic: float) -> None:
            self._transaction.finish(  # type: ignore[attr-defined]
                terminal, deadline_monotonic=deadline_monotonic
            )
            raise KeyboardInterrupt("owned test interruption")

        def abort(self) -> None:
            self._transaction.abort()  # type: ignore[attr-defined]

    class _InterruptedSink:
        def __init__(self, root: Path) -> None:
            self.actual = FileSystemSanitizedOutputSink(private_root=root)

        def begin(
            self,
            request: InspectorLaunchRequestV1,
            *,
            maximum_bytes: int,
            deadline_monotonic: float,
        ) -> _InterruptedTransaction:
            return _InterruptedTransaction(
                self.actual.begin(
                    request,
                    maximum_bytes=maximum_bytes,
                    deadline_monotonic=deadline_monotonic,
                )
            )

    policy = _policy()
    payload = b"sealed-ortho"
    output = b"sanitized-output"
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
        attempt_nonce="interrupt-attempt",
    )
    client_socket, server_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)

    def serve() -> None:
        try:
            received = read_launch_request_header(server_socket, _protocol_limits())
            read_bound_bytes(
                server_socket,
                received.sealed_byte_binding,
                _protocol_limits(),
                DeadlineBoundedDiscardingSink(),
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
        finally:
            server_socket.close()

    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    thread = threading.Thread(target=serve)
    thread.start()
    sink = _InterruptedSink(root)
    client = ExternalInspectorUdsClient(
        connect=lambda deadline, **_kwargs: client_socket,
        protocol_limits=_protocol_limits(),
        sanitized_output_sink=sink,
        heartbeat_interval_millis=10,
    )
    with pytest.raises(KeyboardInterrupt, match="owned test interruption"):
        client.execute(
            request=request,
            source=BytesIO(payload),
            artifact_kind=ProcessingArtifactKind.ORTHO,
            content_type="image/tiff",
            deadline_monotonic=time.monotonic() + 0.5,
            authority_is_current=lambda: True,
        )
    thread.join(timeout=1)
    assert not thread.is_alive()
    retry = sink.actual.begin(
        request, maximum_bytes=1_024, deadline_monotonic=time.monotonic() + 0.5
    )
    retry.abort()
    assert list(root.iterdir()) == []


def test_uds_client_aborts_private_candidate_after_short_raw_stream() -> None:
    """A declared header cannot retain a partial candidate when the raw body ends early."""

    class _Sink(_DeadlineBoundedTestSink):
        def __init__(self) -> None:
            self.chunks: list[bytes] = []
            self.finished = False
            self.aborted = False

        def begin(
            self,
            request: InspectorLaunchRequestV1,
            *,
            maximum_bytes: int,
            deadline_monotonic: float,
        ) -> _Sink:
            del request, maximum_bytes, deadline_monotonic
            return self

        def write(self, chunk: bytes, *, deadline_monotonic: float) -> None:
            del deadline_monotonic
            self.chunks.append(chunk)

        def finish(self, terminal: InspectorLaunchResultV1, *, deadline_monotonic: float) -> None:
            del terminal, deadline_monotonic
            self.finished = True

        def abort(self) -> None:
            self.aborted = True

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
    client_socket, server_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)

    def serve() -> None:
        try:
            received = read_launch_request_header(server_socket, _protocol_limits())
            read_bound_bytes(
                server_socket,
                received.sealed_byte_binding,
                _protocol_limits(),
                DeadlineBoundedDiscardingSink(),
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
                    4,
                    _bytes_digest(b"full"),
                ),
                _protocol_limits(),
            )
            server_socket.sendall(b"cut")
            server_socket.shutdown(socket.SHUT_WR)
        finally:
            server_socket.close()

    thread = threading.Thread(target=serve)
    thread.start()
    sink = _Sink()
    client = ExternalInspectorUdsClient(
        connect=lambda deadline, **_kwargs: client_socket,
        protocol_limits=_protocol_limits(),
        sanitized_output_sink=sink,
        heartbeat_interval_millis=10,
    )
    with pytest.raises(CurrentAuthorityLost, match="UDS launch failed closed"):
        client.execute(
            request=request,
            source=BytesIO(payload),
            artifact_kind=ProcessingArtifactKind.ORTHO,
            content_type="image/tiff",
            deadline_monotonic=__import__("time").monotonic() + 0.5,
            authority_is_current=lambda: True,
        )
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert sink.chunks == [b"cut"]
    assert sink.finished is False
    assert sink.aborted is True


def test_uds_client_aborts_private_candidate_when_fence_changes_after_private_seal() -> None:
    """A fenced candidate cannot survive even a post-seal authority loss before return."""

    class _Sink(_DeadlineBoundedTestSink):
        def __init__(self) -> None:
            self.aborted = False
            self.finished = False
            self.authority_current = True

        def begin(
            self,
            request: InspectorLaunchRequestV1,
            *,
            maximum_bytes: int,
            deadline_monotonic: float,
        ) -> _Sink:
            del request, maximum_bytes, deadline_monotonic
            return self

        def write(self, chunk: bytes, *, deadline_monotonic: float) -> None:
            del chunk, deadline_monotonic

        def finish(self, terminal: InspectorLaunchResultV1, *, deadline_monotonic: float) -> None:
            del terminal, deadline_monotonic
            self.finished = True
            self.authority_current = False

        def abort(self) -> None:
            self.aborted = True

    policy = _policy()
    payload = b"sealed-ortho"
    output = b"full"
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
    client_socket, server_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)

    def serve() -> None:
        try:
            received = read_launch_request_header(server_socket, _protocol_limits())
            read_bound_bytes(
                server_socket,
                received.sealed_byte_binding,
                _protocol_limits(),
                DeadlineBoundedDiscardingSink(),
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
        finally:
            server_socket.close()

    thread = threading.Thread(target=serve)
    thread.start()
    sink = _Sink()
    client = ExternalInspectorUdsClient(
        connect=lambda deadline, **_kwargs: client_socket,
        protocol_limits=_protocol_limits(),
        sanitized_output_sink=sink,
        heartbeat_interval_millis=10,
    )
    with pytest.raises(CurrentAuthorityLost, match="private candidate seal"):
        client.execute(
            request=request,
            source=BytesIO(payload),
            artifact_kind=ProcessingArtifactKind.ORTHO,
            content_type="image/tiff",
            deadline_monotonic=__import__("time").monotonic() + 0.5,
            authority_is_current=lambda: sink.authority_current,
        )
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert sink.finished is True
    assert sink.aborted is True


def test_worker_retires_the_real_private_candidate_after_the_client_returns_stale_authority(
    tmp_path: Path,
) -> None:
    """The worker owns the candidate through its final retained-authority check."""

    policy = _policy()
    request = _request(policy)
    current = ExternalInspectionCurrentInputV1(
        request=request,
        policy=policy,
        artifacts=(_artifact(),),
        phase=ExternalInspectionPhaseV1.DISPLAY,
        next_action=ExternalInspectionNextActionV1.SANITIZE_DISPLAY,
        accepted_report=_accepted_report(request, policy),
    )
    authority = _Authority(current, [True] * 100)
    private_root = tmp_path / "private"
    private_root.mkdir(mode=0o700)
    private_root.chmod(0o700)
    sink = FileSystemSanitizedOutputSink(private_root=private_root)
    client_socket, server_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    output = b"x"

    def serve() -> None:
        try:
            received = read_launch_request_header(server_socket, _protocol_limits())
            read_bound_bytes(
                server_socket,
                received.sealed_byte_binding,
                _protocol_limits(),
                DeadlineBoundedDiscardingSink(),
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
        finally:
            server_socket.close()

    thread = threading.Thread(target=serve)
    thread.start()
    client = ExternalInspectorUdsClient(
        connect=lambda deadline, **_kwargs: client_socket,
        protocol_limits=_protocol_limits(),
        sanitized_output_sink=sink,
        heartbeat_interval_millis=10,
    )

    class _PostClientAuthorityLoss:
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
            result = client.execute(
                request=request,
                source=source,
                artifact_kind=artifact_kind,
                content_type=content_type,
                deadline_monotonic=deadline_monotonic,
                authority_is_current=authority_is_current,
            )
            authority.current = None
            return result

        def abort_private_candidate(self, launch: InspectorLaunchRequestV1) -> None:
            client.abort_private_candidate(launch)

    worker = ExternalArtifactInspectionWorker(
        authority=authority,
        byte_source=_ByteSource(b"sealed-ortho"),
        launcher=_PostClientAuthorityLoss(),
        operation_profile=_Profile(),
        limits=WorkerAuthorityLimitsV1(
            heartbeat_interval_millis=50,
            max_authority_wait_millis=1_000,
        ),
        attempt_nonce_factory=lambda: "attempt-nonce-1",
    )

    with pytest.raises(CurrentAuthorityLost, match="current authority input"):
        worker.launch_artifact(request.request_id, _fence(), "ortho")
    thread.join(timeout=1)
    assert not thread.is_alive()
    assert not sink._active
    assert not sink._sealed
    assert not sink._uncertain
    assert list(private_root.iterdir()) == []


def test_failed_private_candidate_abort_latches_cleanup_uncertainty(tmp_path: Path) -> None:
    """A close uncertainty is retained and blocks admission without retrying its FD."""

    class _FailingStaged:
        def __init__(self) -> None:
            self.abort_calls = 0

        def abort(self) -> None:
            self.abort_calls += 1
            raise RuntimeError("synthetic descriptor close uncertainty")

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
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    sink = FileSystemSanitizedOutputSink(private_root=root)
    staged = _FailingStaged()
    key = (request.attempt_nonce, request.canonical_input_digest)
    transaction = _PrivateSanitizedOutputTransaction(owner=sink, key=key, staged=staged)
    sink._active[key] = transaction

    with pytest.raises(RuntimeError, match="close uncertainty"):
        transaction.abort()
    assert key not in sink._active
    assert sink._uncertain[key] is transaction
    with pytest.raises(CurrentAuthorityLost, match="remains uncertain"):
        transaction.abort()
    assert staged.abort_calls == 1
    with pytest.raises(CurrentAuthorityLost, match="uncertainty closes admission"):
        sink.begin(request, maximum_bytes=1_024, deadline_monotonic=1.0)
    with pytest.raises(CurrentAuthorityLost, match="uncertainty remains"):
        sink.abort_all()
    assert staged.abort_calls == 1


def test_private_candidate_abort_is_exactly_once_when_two_cleanup_paths_race(
    tmp_path: Path,
) -> None:
    """Concurrent cleanup cannot close a descriptor twice after its number may be reused."""

    class _BlockingStaged:
        def __init__(self) -> None:
            self.abort_calls = 0
            self.entered = threading.Event()
            self.release = threading.Event()

        def abort(self) -> None:
            self.abort_calls += 1
            self.entered.set()
            assert self.release.wait(timeout=1)

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
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    sink = FileSystemSanitizedOutputSink(private_root=root)
    staged = _BlockingStaged()
    key = (request.attempt_nonce, request.canonical_input_digest)
    transaction = _PrivateSanitizedOutputTransaction(owner=sink, key=key, staged=staged)
    sink._active[key] = transaction
    first = threading.Thread(target=transaction.abort)
    second = threading.Thread(target=transaction.abort)
    first.start()
    assert staged.entered.wait(timeout=1)
    second.start()
    staged.release.set()
    first.join(timeout=1)
    second.join(timeout=1)

    assert not first.is_alive()
    assert not second.is_alive()
    assert staged.abort_calls == 1
    assert not sink._active
    assert not sink._sealed
    assert not sink._uncertain


def test_filesystem_transaction_sink_keeps_only_an_opaque_private_candidate(
    tmp_path: Path,
) -> None:
    """Local O_TMPFILE behavior has no receipt or publication API."""
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
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    sink = FileSystemSanitizedOutputSink(private_root=root)
    output = b"sanitized-output"
    deadline_monotonic = time.monotonic() + 1.0
    transaction = sink.begin(
        request,
        maximum_bytes=1_024,
        deadline_monotonic=deadline_monotonic,
    )
    transaction.write(output, deadline_monotonic=deadline_monotonic)
    transaction.finish(
        InspectorLaunchResultV1.completed_sanitized(
            request.attempt_nonce,
            request.canonical_input_digest,
            request.policy.parser_build_digest,
            len(output),
            _bytes_digest(output),
        ),
        deadline_monotonic=deadline_monotonic,
    )

    with pytest.raises(CurrentAuthorityLost, match="already exists"):
        sink.begin(request, maximum_bytes=1_024, deadline_monotonic=deadline_monotonic)
    assert list(root.iterdir()) == []
    assert not any(
        name in dir(FileSystemSanitizedOutputSink) for name in ("read", "receipt", "handoff")
    )

    sink.abort_attempt(request)
    replacement = sink.begin(request, maximum_bytes=1_024, deadline_monotonic=deadline_monotonic)
    replacement.abort()


def test_uds_client_stops_a_chunked_upload_when_authority_is_lost() -> None:
    """Losing the fence between upload chunks must prevent later sealed bytes reaching the peer."""

    class _Sink(_DeadlineBoundedTestSink):
        def write(self, chunk: bytes, *, deadline_monotonic: float) -> None:
            del chunk, deadline_monotonic

    class _SlowUploadSource:
        def __init__(self, payload: bytes) -> None:
            self._source = BytesIO(payload)
            self.read_calls = 0
            self.authority_is_current = True

        def read_chunk(
            self,
            maximum_bytes: int,
            *,
            deadline: ProtocolDeadline,
            wait_is_current: Callable[[], bool] | None,
            heartbeat_interval_millis: int | None,
        ) -> bytes:
            del deadline, wait_is_current, heartbeat_interval_millis
            chunk = self._source.read(maximum_bytes)
            self.read_calls += 1
            if self.read_calls == 2:
                self.authority_is_current = False
            return chunk

        def close(self) -> None:
            self._source.close()

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
        connect=lambda deadline, **_kwargs: client_socket,
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

    class _LateByteSource(ExternalArtifactByteSourcePort):
        def __init__(self, clock: _Clock) -> None:
            self._clock = clock
            self.returned: DeadlineBoundedBytesReader | None = None

        def open_bound_bytes(
            self,
            artifact: ExternalArtifactInputV1,
            *,
            deadline: ProtocolDeadline,
            wait_is_current: Callable[[], bool],
            heartbeat_interval_millis: int,
        ) -> DeadlineBoundedByteReaderPort:
            del artifact, deadline, wait_is_current, heartbeat_interval_millis
            self.returned = DeadlineBoundedBytesReader(BytesIO(b"sealed-ortho"))
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
    assert source.returned.is_closed is True
    assert launcher.requests == []


def _measurements(*, bands: int, dtype: str) -> RasterMeasurementsV1:
    return RasterMeasurementsV1(
        observed_crs_identifier="EPSG:5186",
        observed_crs_digest=_digest("1"),
        transform=(1.0, 0.0, 0.0, 0.0, -1.0, 2.0),
        footprint_wkt="POLYGON((0 0,2 0,2 2,0 2,0 0))",
        footprint_digest=_digest("2"),
        width=2,
        height=2,
        band_count=bands,
        dtype=dtype,
        layout="GEOTIFF_TILED_V1",
        nodata_representation=NodataRepresentation.MASK,
        valid_pixel_count=4,
    )


def test_worker_rejects_measurement_that_does_not_match_the_declared_artifact_kind() -> None:
    """A raw-model classification cannot override the sealed Core artifact kind."""

    class _MismatchedModelLauncher(_Launcher):
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
            del source, artifact_kind, content_type, deadline_monotonic, authority_is_current
            return InspectorLaunchResultV1.completed_inspection(
                request.attempt_nonce,
                request.canonical_input_digest,
                request.policy.parser_build_digest,
                ArtifactInspectionOutcomeV1(
                    artifact_id=request.sealed_byte_binding.artifact_id,
                    observed_sha256=request.sealed_byte_binding.observed_sha256,
                    outcome=ArtifactOutcome.MEASURED,
                    measurements=_measurements(bands=1, dtype="float32"),
                ),
            )

    current = _input()
    result = _worker(
        _Authority(current, [True, True]),
        _ByteSource(b"sealed-ortho"),
        _MismatchedModelLauncher(),
    ).launch_artifact(current.request.request_id, _fence(), "ortho")

    assert isinstance(result.outcome, ArtifactInspectionOutcomeV1)
    assert result.outcome.outcome is ArtifactOutcome.REJECTED
    assert result.outcome.reason == "UNSUPPORTED_RASTER"
    assert result.outcome.measurements is None


def test_complete_assembly_keeps_examined_bad_dsm_and_measured_ortho() -> None:
    """One optional artifact rejection cannot erase an independently measured ORTHO."""
    ortho = _artifact()
    dsm = ExternalArtifactInputV1(
        entry_id="dsm",
        kind=ProcessingArtifactKind.DSM,
        observed_sha256=_bytes_digest(b"sealed-dsm"),
        observed_size_bytes=len(b"sealed-dsm"),
        content_type="image/tiff",
    )
    current = _input().model_copy(update={"artifacts": (ortho, dsm)})

    def inspect(artifact: ExternalArtifactInputV1) -> ArtifactInspectionOutcomeV1:
        if artifact.entry_id == "dsm":
            return ArtifactInspectionOutcomeV1(
                artifact_id=artifact.entry_id,
                observed_sha256=artifact.observed_sha256,
                outcome=ArtifactOutcome.REJECTED,
                reason="UNMASKED_NONFINITE_SAMPLE",
            )
        return ArtifactInspectionOutcomeV1(
            artifact_id=artifact.entry_id,
            observed_sha256=artifact.observed_sha256,
            outcome=ArtifactOutcome.MEASURED,
            measurements=_measurements(bands=3, dtype="uint8"),
        )

    payload = assemble_complete_measurement_payload(
        current=current,
        fence=_fence(),
        inspect_one=inspect,
        authority_is_current=lambda fence: fence == _fence(),
    )

    assert [outcome.artifact_id for outcome in payload.outcomes] == ["dsm", "ortho"]
    assert payload.outcomes[0].reason == "UNMASKED_NONFINITE_SAMPLE"
    assert payload.outcomes[1].outcome is ArtifactOutcome.MEASURED


def test_complete_assembly_discards_measurements_when_server_kind_differs() -> None:
    """Entrypoint classification cannot silently override the sealed server artifact kind."""
    current = _input()
    artifact = current.artifacts[0]
    payload = assemble_complete_measurement_payload(
        current=current,
        fence=_fence(),
        inspect_one=lambda _artifact: ArtifactInspectionOutcomeV1(
            artifact_id=artifact.entry_id,
            observed_sha256=artifact.observed_sha256,
            outcome=ArtifactOutcome.MEASURED,
            measurements=_measurements(bands=1, dtype="float32"),
        ),
        authority_is_current=lambda _fence: True,
    )

    assert payload.outcomes[0].outcome is ArtifactOutcome.REJECTED
    assert payload.outcomes[0].reason == "UNSUPPORTED_RASTER"
    assert payload.outcomes[0].measurements is None


def test_complete_assembly_returns_no_partial_payload_after_cancellation() -> None:
    """Cancelling after one examination must not invent outcomes for the remaining input."""
    ortho = _artifact()
    dsm = ExternalArtifactInputV1(
        entry_id="dsm",
        kind=ProcessingArtifactKind.DSM,
        observed_sha256=_bytes_digest(b"sealed-dsm"),
        observed_size_bytes=len(b"sealed-dsm"),
        content_type="image/tiff",
    )
    current = _input().model_copy(update={"artifacts": (ortho, dsm)})
    examined: list[str] = []

    def inspect(artifact: ExternalArtifactInputV1) -> ArtifactInspectionOutcomeV1:
        examined.append(artifact.entry_id)
        return ArtifactInspectionOutcomeV1(
            artifact_id=artifact.entry_id,
            observed_sha256=artifact.observed_sha256,
            outcome=ArtifactOutcome.REJECTED,
            reason="SYNTHETIC_REJECTED",
        )

    with pytest.raises(InspectionAssemblyIncomplete, match="cancelled"):
        assemble_complete_measurement_payload(
            current=current,
            fence=_fence(),
            inspect_one=inspect,
            authority_is_current=lambda _fence: True,
            is_cancelled=lambda: bool(examined),
        )
    assert examined == ["dsm"]
