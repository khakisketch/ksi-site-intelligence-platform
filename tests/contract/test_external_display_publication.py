"""Contract coverage for publication of one retained, private SANITIZE output."""

from __future__ import annotations

import hashlib
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
import test_external_validation_core_client as core_contract
from fastapi.testclient import TestClient
from ksi_core.evidence import ObjectStorageObservation
from ksi_event_contracts.external_artifact_validation import ExternalValidationPolicyV1
from ksi_event_contracts.external_display_artifact import (
    SanitizedDisplayDeclarationV1,
    SanitizedDisplayReceiptV1,
)
from ksi_processing_controller.external_artifact_inspection_worker import (
    ExternalArtifactInputV1,
    ExternalInspectionCurrentInputV1,
    ExternalInspectionNextActionV1,
    ExternalInspectionPhaseV1,
    ExternalInspectorLaunchContextV1,
    FileSystemSanitizedOutputSink,
)
from ksi_processing_controller.external_display_publication import (
    ExternalDisplayPublicationWorker,
)
from ksi_processing_controller.external_inspector_protocol import (
    BoundByteReceiptV1,
    InspectorLaunchRequestV1,
    InspectorLaunchResultV1,
    InspectorOperation,
    LocalLeaseFenceV1,
    ProtocolDeadline,
    SealedByteBindingV1,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectCapabilityPort,
    ExternalObjectCapabilityV1,
    ExternalObjectHttpByteSource,
    ExternalObjectTransportPolicyV1,
    SealedObjectByteSourceV1,
    TrustedObjectEndpointV1,
)
from ksi_processing_controller.external_validation_core_client import (
    ExternalDisplayUploadCapability,
    ExternalValidationCoreClient,
)
from test_external_artifact_inspection_worker import (
    _accepted_report,
    _artifact,
    _fence,
    _policy,
    _request,
)


def _bytes_digest(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


class _PutServer:
    """One owned loopback PUT endpoint retaining only its synthetic request bytes."""

    def __init__(self, *, reply: bool = True) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(1)
        self._socket.settimeout(2.0)
        self.port = int(self._socket.getsockname()[1])
        self.body = b""
        self._reply = reply
        self._failure: BaseException | None = None
        self._thread = threading.Thread(target=self._serve, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/owned-upload"

    def __enter__(self) -> _PutServer:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._thread.join(timeout=2.0)
        self._socket.close()
        if self._thread.is_alive():
            raise AssertionError("owned loopback PUT server did not stop")
        if self._failure is not None:
            raise self._failure

    def _serve(self) -> None:
        try:
            connection, _ = self._socket.accept()
            with connection:
                received = bytearray()
                while b"\r\n\r\n" not in received:
                    chunk = connection.recv(4_096)
                    if not chunk:
                        raise AssertionError("loopback PUT closed before headers")
                    received.extend(chunk)
                headers, body = bytes(received).split(b"\r\n\r\n", 1)
                content_length = next(
                    int(line.split(b":", 1)[1].strip())
                    for line in headers.split(b"\r\n")
                    if line.lower().startswith(b"content-length:")
                )
                while len(body) < content_length:
                    chunk = connection.recv(4_096)
                    if not chunk:
                        raise AssertionError("loopback PUT closed before bound bytes")
                    body += chunk
                self.body = body
                if self._reply:
                    connection.sendall(b"HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n")
        except BaseException as exc:  # surfaced synchronously by __exit__
            self._failure = exc


class _BoundedLoopbackPut:
    """Uses the real bounded PUT implementation against this test's loopback endpoint."""

    def __init__(self, server: _PutServer) -> None:
        self._policy = ExternalObjectTransportPolicyV1(
            endpoints=(
                TrustedObjectEndpointV1(
                    origin=f"http://127.0.0.1:{server.port}", addresses=("127.0.0.1",)
                ),
            ),
            max_header_bytes=4_096,
            max_object_bytes=4_096,
            max_chunk_bytes=64,
        )

    def put_bound_bytes(
        self,
        capability: object,
        sealed_source: SealedObjectByteSourceV1,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> BoundByteReceiptV1:
        # Each declaration is a fresh private capability.  The real HTTP PUT
        # implementation remains the code that consumes the opaque reader.
        owned_capability = cast(ExternalObjectCapabilityV1, capability)
        artifact = owned_capability.artifact
        url = owned_capability.url
        headers = owned_capability.required_headers
        transport = ExternalObjectHttpByteSource(
            capabilities=(ExternalObjectCapabilityV1(artifact, url, headers),),
            policy=self._policy,
        )
        return transport.put_bound_bytes(
            capability,
            sealed_source,
            deadline=deadline,
            wait_is_current=wait_is_current,
            heartbeat_interval_millis=heartbeat_interval_millis,
        )


class _Core:
    def __init__(self, url: str) -> None:
        self._url = url
        self.declarations: list[SanitizedDisplayDeclarationV1] = []
        self.seal_calls = 0
        self.fail_next_grant = False
        self.fail_next_seal = False

    def grant_display_upload(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        declaration: SanitizedDisplayDeclarationV1,
        *,
        deadline_monotonic: float,
    ) -> ExternalDisplayUploadCapability:
        del request_id, fence, deadline_monotonic
        self.declarations.append(declaration)
        if self.fail_next_grant:
            self.fail_next_grant = False
            from ksi_processing_controller.external_validation_core_client import (
                ExternalCoreClientError,
            )

            raise ExternalCoreClientError("INVALID_CORE_RESPONSE")
        return ExternalDisplayUploadCapability(declaration, self._url, {"x-owned-upload": "yes"})

    def seal_display_upload(
        self,
        request_id: str,
        fence: LocalLeaseFenceV1,
        grant: ExternalDisplayUploadCapability,
        *,
        deadline_monotonic: float,
    ) -> SanitizedDisplayReceiptV1:
        del request_id, fence, deadline_monotonic
        self.seal_calls += 1
        if self.fail_next_seal:
            self.fail_next_seal = False
            from ksi_processing_controller.external_validation_core_client import (
                ExternalCoreClientError,
            )

            raise ExternalCoreClientError("INVALID_CORE_RESPONSE")
        declaration = grant.declaration
        assert declaration.declaration_digest is not None
        return SanitizedDisplayReceiptV1(
            display_id=declaration.display_id,
            request_id=declaration.request_id,
            declaration_digest=declaration.declaration_digest,
            source_subject_digest=declaration.source_subject_digest,
            source_report_digest=declaration.source_report_digest,
            policy_digest=declaration.policy_digest,
            inspector_build_digest=declaration.inspector_build_digest,
            observed_derivative_sha256=declaration.declared_derivative_sha256,
            observed_derivative_size_bytes=declaration.declared_derivative_size_bytes,
            observed_derivative_content_type=declaration.declared_derivative_content_type,
            sanitized_display_ref="sda-v1-owned-receipt",
            sealed_at=datetime(2026, 9, 9, tzinfo=UTC),
        ).sealed()


def _retained_context(
    tmp_path: Path, payload: bytes, *, guard: Callable[[], bool] | None = None
) -> tuple[ExternalInspectorLaunchContextV1, FileSystemSanitizedOutputSink, Path]:
    policy = _policy()
    request = _request(policy)
    artifact = _artifact()
    report = _accepted_report(request, policy)
    current = ExternalInspectionCurrentInputV1(
        request=request,
        policy=policy,
        artifacts=(artifact,),
        phase=ExternalInspectionPhaseV1.DISPLAY,
        next_action=ExternalInspectionNextActionV1.SANITIZE_DISPLAY,
        accepted_report=report,
    )
    launch = InspectorLaunchRequestV1.seal(
        operation=InspectorOperation.SANITIZE,
        request=request,
        fence=_fence(),
        subject=request.subject,
        sealed_byte_binding=SealedByteBindingV1(
            artifact_id=artifact.entry_id,
            observed_sha256=artifact.observed_sha256,
            observed_size_bytes=artifact.observed_size_bytes,
        ),
        policy=policy,
        attempt_nonce="retained-sanitize-attempt",
    )
    terminal = InspectorLaunchResultV1.completed_sanitized(
        launch.attempt_nonce,
        launch.canonical_input_digest,
        policy.parser_build_digest,
        len(payload),
        _bytes_digest(payload),
    )
    root = tmp_path / "anonymous-staging"
    root.mkdir(mode=0o700)
    root.chmod(0o700)
    sink = FileSystemSanitizedOutputSink(private_root=root)
    deadline = time.monotonic() + 2.0
    transaction = sink.begin(launch, maximum_bytes=4_096, deadline_monotonic=deadline)
    transaction.write(payload, deadline_monotonic=deadline)
    transaction.finish(terminal, deadline_monotonic=deadline)
    return (
        ExternalInspectorLaunchContextV1(
            current=current,
            artifact=artifact,
            launch_request=launch,
            terminal=terminal,
            deadline=ProtocolDeadline.at_expires_at(deadline, time.monotonic),
            authority_is_current=(lambda: True) if guard is None else guard,
            heartbeat_interval_millis=10,
        ),
        sink,
        root,
    )


class _ObservedPrivateCandidatePut:
    """Consumes only the opaque reader, then supplies a synthetic Core storage observation."""

    def __init__(self, storage: Any, expected: bytes) -> None:
        self._storage = storage
        self._expected = expected
        self.polls = 0

    def put_bound_bytes(
        self,
        capability: object,
        sealed_source: SealedObjectByteSourceV1,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> BoundByteReceiptV1:
        del heartbeat_interval_millis
        assert wait_is_current()
        self.polls += 1
        observed = bytearray()
        while chunk := sealed_source.reader.read_chunk(
            8, deadline=deadline, wait_is_current=wait_is_current, heartbeat_interval_millis=10
        ):
            observed.extend(chunk)
        assert wait_is_current()
        self.polls += 1
        assert bytes(observed) == self._expected
        artifact = cast(
            ExternalArtifactInputV1, cast(ExternalObjectCapabilityPort, capability).artifact
        )
        assert self._storage.last_put_key is not None
        self._storage.objects[self._storage.last_put_key] = ObjectStorageObservation(
            object_key=self._storage.last_put_key,
            exists=True,
            size_bytes=len(observed),
            sha256=_bytes_digest(bytes(observed)),
            content_type=artifact.content_type,
        )
        return BoundByteReceiptV1(
            observed_sha256=_bytes_digest(bytes(observed)), observed_size_bytes=len(observed)
        )


def _actual_core_context(
    tmp_path: Path,
    *,
    client: ExternalValidationCoreClient,
    guard_client: ExternalValidationCoreClient | None,
    request_id: str,
    fence: LocalLeaseFenceV1,
    payload: bytes,
) -> tuple[
    ExternalInspectorLaunchContextV1,
    FileSystemSanitizedOutputSink,
    list[tuple[bool, ExternalInspectionPhaseV1 | None]],
]:
    current = client.current_input(request_id, fence, deadline_monotonic=time.monotonic() + 2)
    assert current is not None
    assert current.phase is ExternalInspectionPhaseV1.DISPLAY
    artifact = next(item for item in current.artifacts if item.kind.value == "ortho")
    launch = InspectorLaunchRequestV1.seal(
        operation=InspectorOperation.SANITIZE,
        request=current.request,
        fence=fence,
        subject=current.request.subject,
        sealed_byte_binding=SealedByteBindingV1(
            artifact_id=artifact.entry_id,
            observed_sha256=artifact.observed_sha256,
            observed_size_bytes=artifact.observed_size_bytes,
        ),
        policy=current.policy,
        attempt_nonce="actual-core-display-publication",
    )
    terminal = InspectorLaunchResultV1.completed_sanitized(
        launch.attempt_nonce,
        launch.canonical_input_digest,
        current.policy.parser_build_digest,
        len(payload),
        _bytes_digest(payload),
    )
    root = tmp_path / "actual-core-private-staging"
    root.mkdir(mode=0o700)
    sink = FileSystemSanitizedOutputSink(private_root=root)
    # The deadline becomes the launch context's wire budget and must therefore
    # cover the whole publication flow (private candidate put, Core
    # declaration/retry, seal and every currentness check), not just the local
    # file transaction.  A hosted runner intermittently exceeded the previous
    # 2 s bound mid-flow (run 38724342684); 30 s keeps the bound real while
    # tolerating runner scheduling.
    deadline = time.monotonic() + 30.0
    transaction = sink.begin(launch, maximum_bytes=4_096, deadline_monotonic=deadline)
    transaction.write(payload, deadline_monotonic=deadline)
    transaction.finish(terminal, deadline_monotonic=deadline)
    polls: list[tuple[bool, ExternalInspectionPhaseV1 | None]] = []

    def is_current() -> bool:
        if guard_client is None:
            return True
        live = guard_client.heartbeat(request_id, fence, deadline_monotonic=deadline)
        latest = (
            guard_client.current_input(request_id, fence, deadline_monotonic=deadline)
            if live
            else None
        )
        polls.append((live, latest.phase if latest is not None else None))
        return live and latest == current

    return (
        ExternalInspectorLaunchContextV1(
            current=current,
            artifact=artifact,
            launch_request=launch,
            terminal=terminal,
            deadline=ProtocolDeadline.at_expires_at(deadline),
            authority_is_current=is_current,
            heartbeat_interval_millis=10,
        ),
        sink,
        polls,
    )


class _NeverPut:
    def put_bound_bytes(
        self,
        capability: object,
        sealed_source: SealedObjectByteSourceV1,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool],
        heartbeat_interval_millis: int,
    ) -> BoundByteReceiptV1:
        del capability, sealed_source, deadline, wait_is_current, heartbeat_interval_millis
        raise AssertionError("Core failure must prevent object PUT")


def test_publish_reads_retained_anonymous_candidate_and_returns_only_core_receipt(
    tmp_path: Path,
) -> None:
    payload = b"owned-sanitized-display-bytes"
    context, sink, root = _retained_context(tmp_path, payload)

    with _PutServer() as server:
        receipt = ExternalDisplayPublicationWorker(
            core=_Core(server.url),
            candidate_opener=sink,
            object_transport=_BoundedLoopbackPut(server),
        ).publish(context)

    assert receipt.sanitized_display_ref == "sda-v1-owned-receipt"
    assert receipt.observed_derivative_sha256 == _bytes_digest(payload)
    assert server.body == payload
    assert list(root.iterdir()) == []
    assert "127.0.0.1" not in repr(receipt)


def test_retry_after_lost_grant_reuses_the_same_retained_derivative(tmp_path: Path) -> None:
    payload = b"retry-after-grant-response-loss"
    context, sink, root = _retained_context(tmp_path, payload)

    core = _Core("http://127.0.0.1:1/not-reached")
    core.fail_next_grant = True
    with pytest.raises(Exception, match="INVALID_CORE_RESPONSE"):
        ExternalDisplayPublicationWorker(
            core=core, candidate_opener=sink, object_transport=_NeverPut()
        ).publish(context)

    with _PutServer() as server:
        core._url = server.url
        receipt = ExternalDisplayPublicationWorker(
            core=core,
            candidate_opener=sink,
            object_transport=_BoundedLoopbackPut(server),
        ).publish(context)

    assert receipt.observed_derivative_sha256 == _bytes_digest(payload)
    assert server.body == payload
    assert core.declarations == [core.declarations[0], core.declarations[0]]
    assert list(root.iterdir()) == []


def test_retry_after_lost_put_response_reuses_bytes_from_offset_zero(tmp_path: Path) -> None:
    payload = b"retry-after-put-response-loss"
    context, sink, root = _retained_context(tmp_path, payload)

    with _PutServer(reply=False) as lost_response:
        core = _Core(lost_response.url)
        with pytest.raises(Exception, match="UNEXPECTED_HEADER_EOF"):
            ExternalDisplayPublicationWorker(
                core=core,
                candidate_opener=sink,
                object_transport=_BoundedLoopbackPut(lost_response),
            ).publish(context)
    assert lost_response.body == payload

    with _PutServer() as retry:
        core._url = retry.url
        receipt = ExternalDisplayPublicationWorker(
            core=core,
            candidate_opener=sink,
            object_transport=_BoundedLoopbackPut(retry),
        ).publish(context)

    assert receipt.observed_derivative_size_bytes == len(payload)
    assert retry.body == payload
    assert core.declarations == [core.declarations[0], core.declarations[0]]
    assert list(root.iterdir()) == []


def test_retry_after_lost_seal_response_adjudicates_the_same_declaration_without_a_second_put(
    tmp_path: Path,
) -> None:
    payload = b"retry-after-seal-response-loss"
    context, sink, root = _retained_context(tmp_path, payload)

    with _PutServer() as server:
        core = _Core(server.url)
        core.fail_next_seal = True
        receipt = ExternalDisplayPublicationWorker(
            core=core,
            candidate_opener=sink,
            object_transport=_BoundedLoopbackPut(server),
        ).publish(context)

    assert receipt.observed_derivative_sha256 == _bytes_digest(payload)
    assert server.body == payload
    assert core.declarations == [core.declarations[0]]
    assert core.seal_calls == 2
    assert list(root.iterdir()) == []


def test_tampered_terminal_is_rejected_before_grant_and_retires_candidate(tmp_path: Path) -> None:
    payload = b"terminal-must-stay-strict"
    context, sink, _ = _retained_context(tmp_path, payload)
    expected_terminal = InspectorLaunchResultV1.model_validate(context.terminal.__dict__)
    object.__setattr__(context.terminal, "output_size_bytes", True)
    core = _Core("http://127.0.0.1:1/not-reached")

    from ksi_processing_controller.external_artifact_inspection_worker import CurrentAuthorityLost
    from ksi_processing_controller.external_display_publication import (
        ExternalDisplayPublicationError,
    )

    with pytest.raises(ExternalDisplayPublicationError, match="INVALID_LAUNCH_CONTEXT"):
        ExternalDisplayPublicationWorker(
            core=core, candidate_opener=sink, object_transport=_NeverPut()
        ).publish(context)
    assert core.declarations == []
    with pytest.raises(CurrentAuthorityLost):
        sink.open_private_candidate(
            context.launch_request,
            expected_terminal,
            deadline=ProtocolDeadline(1_000, time.monotonic),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )


def test_late_fence_and_terminal_mutation_retires_the_original_candidate(tmp_path: Path) -> None:
    payload = b"launch-cleanup-identity-must-be-retained"
    context, sink, _ = _retained_context(tmp_path, payload)
    original_launch = InspectorLaunchRequestV1.model_validate(context.launch_request.__dict__)
    original_terminal = InspectorLaunchResultV1.model_validate(context.terminal.__dict__)
    changed_fence = _fence().model_copy(update={"lease_generation": 2})
    changed_launch = InspectorLaunchRequestV1.seal(
        operation=InspectorOperation.SANITIZE,
        request=original_launch.request,
        fence=changed_fence,
        subject=original_launch.subject,
        sealed_byte_binding=original_launch.sealed_byte_binding,
        policy=original_launch.policy,
        attempt_nonce="late-mutated-attempt",
    )
    changed_terminal = InspectorLaunchResultV1.completed_sanitized(
        changed_launch.attempt_nonce,
        changed_launch.canonical_input_digest,
        changed_launch.policy.parser_build_digest,
        len(payload),
        _bytes_digest(payload),
    )
    object.__setattr__(context, "launch_request", changed_launch)
    object.__setattr__(context, "terminal", changed_terminal)
    core = _Core("http://127.0.0.1:1/not-reached")

    from ksi_processing_controller.external_artifact_inspection_worker import CurrentAuthorityLost
    from ksi_processing_controller.external_display_publication import (
        ExternalDisplayPublicationError,
    )

    with pytest.raises(ExternalDisplayPublicationError, match="INVALID_LAUNCH_CONTEXT"):
        ExternalDisplayPublicationWorker(
            core=core, candidate_opener=sink, object_transport=_NeverPut()
        ).publish(context)
    assert core.declarations == []
    with pytest.raises(CurrentAuthorityLost):
        sink.open_private_candidate(
            original_launch,
            original_terminal,
            deadline=ProtocolDeadline(1_000, time.monotonic),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )


def test_stale_authority_retires_candidate_before_core_or_object_io(tmp_path: Path) -> None:
    payload = b"guard-must-remain-captured"
    context, sink, _ = _retained_context(tmp_path, payload, guard=lambda: False)
    core = _Core("http://127.0.0.1:1/not-reached")

    from ksi_processing_controller.external_artifact_inspection_worker import CurrentAuthorityLost

    with pytest.raises(CurrentAuthorityLost):
        ExternalDisplayPublicationWorker(
            core=core, candidate_opener=sink, object_transport=_NeverPut()
        ).publish(context)
    assert core.declarations == []
    with pytest.raises(CurrentAuthorityLost):
        sink.open_private_candidate(
            context.launch_request,
            context.terminal,
            deadline=ProtocolDeadline(1_000, time.monotonic),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )


@pytest.mark.parametrize("mutation", ["artifact", "report", "policy"])
def test_mutated_display_authority_never_reaches_core_and_retires_original_candidate(
    tmp_path: Path, mutation: str
) -> None:
    payload = b"current-display-authority-must-remain-sealed"
    context, sink, _ = _retained_context(tmp_path, payload)
    original_launch = InspectorLaunchRequestV1.model_validate(context.launch_request.__dict__)
    original_terminal = InspectorLaunchResultV1.model_validate(context.terminal.__dict__)
    if mutation == "artifact":
        object.__setattr__(
            context,
            "artifact",
            context.artifact.model_copy(update={"observed_sha256": "sha256:" + "f" * 64}),
        )
    elif mutation == "report":
        assert context.current.accepted_report is not None
        changed_report = context.current.accepted_report.model_copy(
            update={"report_id": "report-2", "report_digest": None}
        ).sealed()
        object.__setattr__(
            context,
            "current",
            context.current.model_copy(update={"accepted_report": changed_report}),
        )
    else:
        object.__setattr__(
            context,
            "current",
            context.current.model_copy(
                update={
                    "policy": context.current.policy.model_copy(
                        update={"parser_build_digest": "sha256:" + "f" * 64}
                    )
                }
            ),
        )
    core = _Core("http://127.0.0.1:1/not-reached")

    from ksi_processing_controller.external_artifact_inspection_worker import CurrentAuthorityLost
    from ksi_processing_controller.external_display_publication import (
        ExternalDisplayPublicationError,
    )

    with pytest.raises(ExternalDisplayPublicationError, match="INVALID_LAUNCH_CONTEXT"):
        ExternalDisplayPublicationWorker(
            core=core, candidate_opener=sink, object_transport=_NeverPut()
        ).publish(context)
    assert core.declarations == []
    with pytest.raises(CurrentAuthorityLost):
        sink.open_private_candidate(
            original_launch,
            original_terminal,
            deadline=ProtocolDeadline(1_000, time.monotonic),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )


def test_expired_original_deadline_retires_candidate_before_core_or_object_io(
    tmp_path: Path,
) -> None:
    payload = b"deadline-is-not-extended-for-display-publication"
    context, sink, _ = _retained_context(tmp_path, payload)
    original_launch = InspectorLaunchRequestV1.model_validate(context.launch_request.__dict__)
    original_terminal = InspectorLaunchResultV1.model_validate(context.terminal.__dict__)

    class _Clock:
        now = 10.0

        def __call__(self) -> float:
            return self.now

    clock = _Clock()
    context = replace(context, deadline=ProtocolDeadline(100, clock))
    clock.now = 10.2
    core = _Core("http://127.0.0.1:1/not-reached")

    from ksi_processing_controller.external_artifact_inspection_worker import CurrentAuthorityLost

    with pytest.raises(CurrentAuthorityLost):
        ExternalDisplayPublicationWorker(
            core=core, candidate_opener=sink, object_transport=_NeverPut()
        ).publish(context)
    assert core.declarations == []
    with pytest.raises(CurrentAuthorityLost):
        sink.open_private_candidate(
            original_launch,
            original_terminal,
            deadline=ProtocolDeadline(1_000, time.monotonic),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )


def test_upload_discrepancy_never_reaches_core_seal_and_retires_candidate(tmp_path: Path) -> None:
    payload = b"upload-receipt-must-bind-candidate"
    context, sink, _ = _retained_context(tmp_path, payload)
    core = _Core("http://127.0.0.1:1/not-reached")

    class _WrongReceiptPut:
        def put_bound_bytes(
            self,
            capability: object,
            sealed_source: SealedObjectByteSourceV1,
            *,
            deadline: ProtocolDeadline,
            wait_is_current: Callable[[], bool],
            heartbeat_interval_millis: int,
        ) -> BoundByteReceiptV1:
            del capability, sealed_source, deadline, wait_is_current, heartbeat_interval_millis
            return BoundByteReceiptV1(
                observed_sha256="sha256:" + "0" * 64,
                observed_size_bytes=len(payload),
            )

    from ksi_processing_controller.external_artifact_inspection_worker import CurrentAuthorityLost
    from ksi_processing_controller.external_display_publication import (
        ExternalDisplayPublicationError,
    )

    with pytest.raises(ExternalDisplayPublicationError, match="DISPLAY_UPLOAD_RECEIPT_MISMATCH"):
        ExternalDisplayPublicationWorker(
            core=core, candidate_opener=sink, object_transport=_WrongReceiptPut()
        ).publish(context)
    assert core.seal_calls == 0
    with pytest.raises(CurrentAuthorityLost):
        sink.open_private_candidate(
            context.launch_request,
            context.terminal,
            deadline=ProtocolDeadline(1_000, time.monotonic),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )


def test_base_exception_from_core_still_retires_the_private_candidate(tmp_path: Path) -> None:
    payload = b"base-exception-must-not-leak-candidate"
    context, sink, _ = _retained_context(tmp_path, payload)

    class _InterruptingCore:
        def grant_display_upload(
            self,
            request_id: str,
            fence: LocalLeaseFenceV1,
            declaration: SanitizedDisplayDeclarationV1,
            *,
            deadline_monotonic: float,
        ) -> ExternalDisplayUploadCapability:
            del request_id, fence, declaration, deadline_monotonic
            raise KeyboardInterrupt

        def seal_display_upload(
            self,
            request_id: str,
            fence: LocalLeaseFenceV1,
            grant: ExternalDisplayUploadCapability,
            *,
            deadline_monotonic: float,
        ) -> SanitizedDisplayReceiptV1:
            del request_id, fence, grant, deadline_monotonic
            raise AssertionError("Core seal must not run")

    from ksi_processing_controller.external_artifact_inspection_worker import CurrentAuthorityLost

    with pytest.raises(KeyboardInterrupt):
        ExternalDisplayPublicationWorker(
            core=_InterruptingCore(), candidate_opener=sink, object_transport=_NeverPut()
        ).publish(context)
    with pytest.raises(CurrentAuthorityLost):
        sink.open_private_candidate(
            context.launch_request,
            context.terminal,
            deadline=ProtocolDeadline(1_000, time.monotonic),
            wait_is_current=lambda: True,
            heartbeat_interval_millis=10,
        )


def test_actual_core_octet_stream_input_declares_a_fixed_tiff_derivative(tmp_path: Path) -> None:
    """Core's generic source MIME does not alter the sealed sanitized derivative MIME."""
    app, request_id, policy, _storage, _submission_ref = core_contract._active_scoped_app(tmp_path)
    policy = cast(ExternalValidationPolicyV1, policy)

    with TestClient(app) as core, core_contract._assembled_client(core) as client:
        lease = client.claim(
            request_id,
            worker_instance_id=_fence().worker_instance_id,
            acquisition_id=_fence().lease_acquisition_id,
            deadline_monotonic=time.monotonic() + 2,
        )
        client.record_report(
            request_id,
            lease.fence,
            core_contract.inspection_report(request_id=request_id, policy=policy),
            deadline_monotonic=time.monotonic() + 2,
        )
        context, sink, _polls = _actual_core_context(
            tmp_path,
            client=client,
            guard_client=None,
            request_id=request_id,
            fence=lease.fence,
            payload=b"actual-core-octet-stream-sanitized-output",
        )
        assert context.artifact.content_type == "application/octet-stream"

        try:
            declaration = ExternalDisplayPublicationWorker._declaration_for(context)
        finally:
            sink.abort_attempt(context.launch_request)

    assert declaration.declared_derivative_content_type == "image/tiff"


def test_actual_core_returns_the_exact_receipt_after_display_becomes_terminal(
    tmp_path: Path,
) -> None:
    """The sealed receipt, rather than the spent DISPLAY lease, adjudicates completion."""
    app, request_id, policy, storage, _submission_ref = core_contract._active_scoped_app(tmp_path)
    policy = cast(ExternalValidationPolicyV1, policy)
    payload = b"actual-core-terminal-receipt"

    with TestClient(app) as core, core_contract._assembled_client(core) as client:
        lease = client.claim(
            request_id,
            worker_instance_id=_fence().worker_instance_id,
            acquisition_id=_fence().lease_acquisition_id,
            deadline_monotonic=time.monotonic() + 2,
        )
        client.record_report(
            request_id,
            lease.fence,
            core_contract.inspection_report(request_id=request_id, policy=policy),
            deadline_monotonic=time.monotonic() + 2,
        )
        context, sink, polls = _actual_core_context(
            tmp_path,
            client=client,
            guard_client=client,
            request_id=request_id,
            fence=lease.fence,
            payload=payload,
        )
        object_put = _ObservedPrivateCandidatePut(storage, payload)

        receipt = ExternalDisplayPublicationWorker(
            core=client, candidate_opener=sink, object_transport=object_put
        ).publish(context)

        assert receipt.observed_derivative_sha256 == _bytes_digest(payload)
        assert receipt.observed_derivative_content_type == "image/tiff"
        assert object_put.polls >= 2
        assert len(polls) >= 4
        assert polls and all(
            live and phase is ExternalInspectionPhaseV1.DISPLAY for live, phase in polls
        )
        assert not client.heartbeat(
            request_id, lease.fence, deadline_monotonic=time.monotonic() + 2
        )


def test_actual_core_retries_a_lost_seal_response_with_the_same_declaration(tmp_path: Path) -> None:
    """One uncertain seal is adjudicated by Core's exact terminal receipt, not a new grant."""
    app, request_id, policy, storage, _submission_ref = core_contract._active_scoped_app(tmp_path)
    policy = cast(ExternalValidationPolicyV1, policy)
    payload = b"actual-core-lost-seal-response"

    with TestClient(app) as core:
        transport = core_contract._CoreTestClientTransport(core)
        with (
            ExternalValidationCoreClient(
                base_url="https://core.invalid",
                bearer_token="worker-token",
                transport=transport,
                monotonic=lambda: 0.0,
            ) as client,
            core_contract._assembled_client(core) as guard_client,
        ):
            lease = client.claim(
                request_id,
                worker_instance_id=_fence().worker_instance_id,
                acquisition_id=_fence().lease_acquisition_id,
                deadline_monotonic=time.monotonic() + 2,
            )
            client.record_report(
                request_id,
                lease.fence,
                core_contract.inspection_report(request_id=request_id, policy=policy),
                deadline_monotonic=time.monotonic() + 2,
            )
            context, sink, polls = _actual_core_context(
                tmp_path,
                client=client,
                guard_client=guard_client,
                request_id=request_id,
                fence=lease.fence,
                payload=payload,
            )
            object_put = _ObservedPrivateCandidatePut(storage, payload)
            transport.drop_next_suffix = "/seal"

            receipt = ExternalDisplayPublicationWorker(
                core=client, candidate_opener=sink, object_transport=object_put
            ).publish(context)

            assert receipt.observed_derivative_sha256 == _bytes_digest(payload)
            assert receipt.declaration_digest is not None
            assert object_put.polls >= 2
            assert polls and all(
                live and phase is ExternalInspectionPhaseV1.DISPLAY for live, phase in polls
            )
            assert not guard_client.heartbeat(
                request_id, lease.fence, deadline_monotonic=time.monotonic() + 2
            )


def test_actual_core_failed_poll_after_grant_blocks_put_and_retires_candidate(
    tmp_path: Path,
) -> None:
    """A failed retained poll clears the declaration before private bytes move."""
    app, request_id, policy, _storage, _submission_ref = core_contract._active_scoped_app(tmp_path)
    policy = cast(ExternalValidationPolicyV1, policy)
    payload = b"actual-core-failed-poll"

    class _GrantThenDropInput:
        def __init__(self, client: ExternalValidationCoreClient, transport: Any) -> None:
            self._client = client
            self._transport = transport
            self.seal_calls = 0

        def grant_display_upload(
            self,
            request_id: str,
            fence: LocalLeaseFenceV1,
            declaration: SanitizedDisplayDeclarationV1,
            *,
            deadline_monotonic: float,
        ) -> ExternalDisplayUploadCapability:
            grant = self._client.grant_display_upload(
                request_id, fence, declaration, deadline_monotonic=deadline_monotonic
            )
            self._transport.drop_next_suffix = "/input"
            return grant

        def seal_display_upload(
            self,
            request_id: str,
            fence: LocalLeaseFenceV1,
            grant: ExternalDisplayUploadCapability,
            *,
            deadline_monotonic: float,
        ) -> SanitizedDisplayReceiptV1:
            del request_id, fence, grant, deadline_monotonic
            self.seal_calls += 1
            raise AssertionError("failed poll reached Core seal")

    with TestClient(app) as core:
        transport = core_contract._CoreTestClientTransport(core)
        with ExternalValidationCoreClient(
            base_url="https://core.invalid",
            bearer_token="worker-token",
            transport=transport,
            monotonic=lambda: 0.0,
        ) as client:
            lease = client.claim(
                request_id,
                worker_instance_id=_fence().worker_instance_id,
                acquisition_id=_fence().lease_acquisition_id,
                deadline_monotonic=time.monotonic() + 2,
            )
            client.record_report(
                request_id,
                lease.fence,
                core_contract.inspection_report(request_id=request_id, policy=policy),
                deadline_monotonic=time.monotonic() + 2,
            )
            context, sink, _polls = _actual_core_context(
                tmp_path,
                client=client,
                guard_client=client,
                request_id=request_id,
                fence=lease.fence,
                payload=payload,
            )
            guarded_core = _GrantThenDropInput(client, transport)

            from ksi_processing_controller.external_artifact_inspection_worker import (
                CurrentAuthorityLost,
            )

            with pytest.raises(CurrentAuthorityLost):
                ExternalDisplayPublicationWorker(
                    core=guarded_core, candidate_opener=sink, object_transport=_NeverPut()
                ).publish(context)
            assert guarded_core.seal_calls == 0
            with pytest.raises(CurrentAuthorityLost):
                sink.open_private_candidate(
                    context.launch_request,
                    context.terminal,
                    deadline=ProtocolDeadline(1_000, time.monotonic),
                    wait_is_current=lambda: True,
                    heartbeat_interval_millis=10,
                )
