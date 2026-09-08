"""Contract tests for the local external-inspector UDS admission boundary.

These are synthetic byte/port tests.  They do not provision an identity, a
catalog, a Docker daemon, a parser profile, or a sandbox.
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import cast

import pytest
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    ExternalArtifactInspectionRequestV1,
    ExternalValidationPolicyV1,
    PolicyStatus,
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionHardCeilingsV1,
    InspectorExecutionManifestBodyV1,
    InspectorExecutionManifestSignatureV1,
    InspectorExecutionManifestV1,
    InspectorImageIdentityV1,
    InspectorSecurityProfileV1,
    SignatureVerificationVerdict,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_processing_controller.external_inspector_launcher import (
    CatalogStartupStatusV1,
    ExternalInspectorLauncher,
    InspectorBackendCompletedV1,
    InspectorEffectiveLimitsV1,
    InspectorOperationProfileDecision,
    InspectorSandboxUnavailable,
    InspectorStagedBytesPort,
)
from ksi_processing_controller.external_inspector_protocol import (
    InspectorLaunchRequestV1,
    InspectorLaunchResultV1,
    InspectorOperation,
    LocalLeaseFenceV1,
    ProtocolDeadline,
    ProtocolDeadlineExceeded,
    ProtocolLimitsV1,
    ProtocolViolation,
    SealedByteBindingV1,
    decode_json_frame,
    read_bound_bytes,
    read_launch_request_header,
    read_launch_result,
    write_launch_request,
)
from pydantic import ValidationError

_WORKER_UID = os.getuid()
_WORKER_ID = "123e4567-e89b-42d3-a456-426614174000"
_ACQUISITION_ID = "123e4567-e89b-42d3-a456-426614174002"


def _digest(marker: str) -> str:
    return "sha256:" + marker * 64


def _bytes_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _limits() -> ProtocolLimitsV1:
    return ProtocolLimitsV1(
        max_header_bytes=16_384,
        max_chunk_bytes=128,
        max_input_bytes=4_096,
        max_output_bytes=4_096,
        max_wire_duration_millis=2_000,
    )


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


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=64,
        max_streamed_bytes=48,
        max_tiff_directories=4,
        max_tiff_entries=32,
        max_pixels=1_000,
        max_bands=4,
        max_blocks=64,
        max_decompressed_bytes=1_024,
        max_sample_bytes=1_024,
        max_geometry_vertices=64,
        max_cpu_seconds=2.0,
        max_memory_bytes=80,
        max_workspace_bytes=72,
        max_output_bytes=40,
        max_tenant_concurrency=1,
        max_queue_depth=4,
        max_deadline_seconds=3.0,
        lease_duration_seconds=2.0,
        max_retry_attempts=1,
    ).sealed()


def _manifest(envelope: ResourceEnvelopeV1 | None = None) -> InspectorExecutionManifestV1:
    effective_envelope = envelope or _envelope()
    assert effective_envelope.resource_envelope_digest is not None
    body = InspectorExecutionManifestBodyV1(
        image_identity=InspectorImageIdentityV1(
            oci_manifest_digest=_digest("c"), oci_config_digest=_digest("d")
        ),
        source_tree_digest=_digest("e"),
        build_provenance_digest=_digest("f"),
        sbom_digest=_digest("1"),
        inspector_protocol_digest=_digest("2"),
        backend_profile_digest=_digest("3"),
        security_profile_digest=_digest("4"),
        resource_envelope_digest=effective_envelope.resource_envelope_digest,
        backend="DEDICATED_ROOTLESS_DOCKER_V1",
        runtime_uid=10001,
        runtime_gid=10001,
        runtime_environment=(
            ("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR"),
            ("GDAL_DRIVER_PATH", "disable"),
            ("GDAL_PAM_ENABLED", "NO"),
            ("PROJ_NETWORK", "OFF"),
            ("PYTHONDONTWRITEBYTECODE", "1"),
        ),
        security_profile=InspectorSecurityProfileV1(),
        hard_ceilings=InspectorExecutionHardCeilingsV1(
            max_input_bytes=40,
            max_memory_bytes=64,
            max_tmpfs_bytes=60,
            max_pids=17,
            cpu_period_micros=100_000,
            cpu_quota_micros=50_000,
            max_wall_time_millis=2_000,
            max_log_bytes=2_048,
            max_output_bytes=32,
        ),
    )
    return InspectorExecutionManifestV1(
        body=body,
        signature=InspectorExecutionManifestSignatureV1(
            algorithm="Ed25519",
            key_id="synthetic-test-key",
            digest=body.canonical_body_digest(),
            signature=base64.b64encode(b"x" * 64).decode("ascii"),
        ),
    )


def _policy(manifest: InspectorExecutionManifestV1 | None = None) -> ExternalValidationPolicyV1:
    actual_manifest = manifest or _manifest()
    envelope = _envelope()
    assert envelope.resource_envelope_digest == actual_manifest.body.resource_envelope_digest
    return ExternalValidationPolicyV1(
        policy_id="synthetic-policy",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=actual_manifest.parser_build_digest,
        grammar_digest=_digest("5"),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=_digest("6"),
        inspection_rule_ids=(),
        evidence_rule_ids=(),
        compatibility_mapping_digests=(),
        synthetic_test_only=True,
    ).sealed()


def _request(
    policy: ExternalValidationPolicyV1,
    payload: bytes = b"sealed-bytes",
    *,
    operation: InspectorOperation = InspectorOperation.INSPECT,
) -> InspectorLaunchRequestV1:
    assert policy.policy_digest is not None
    request = ExternalArtifactInspectionRequestV1(
        request_id="inspection-request-1",
        subject=_subject(),
        inspection_policy_id=policy.policy_id,
        inspection_policy_version=policy.version,
        inspection_policy_digest=policy.policy_digest,
        issued_at=datetime(2026, 9, 7, tzinfo=UTC),
        idempotency_key="inspection-key-1",
    )
    return InspectorLaunchRequestV1.seal(
        operation=operation,
        request=request,
        fence=LocalLeaseFenceV1(
            worker_instance_id=_WORKER_ID,
            lease_acquisition_id=_ACQUISITION_ID,
            lease_generation=1,
        ),
        subject=request.subject,
        sealed_byte_binding=SealedByteBindingV1(
            artifact_id="ortho",
            observed_sha256=_bytes_digest(payload),
            observed_size_bytes=len(payload),
        ),
        policy=policy,
        attempt_nonce="attempt-nonce-1",
    )


def test_request_digest_binds_the_closed_canonical_body_and_revalidates_nested_models() -> None:
    """Dropping a request field or accepting a substituted nested policy must change/reject it."""
    request = _request(_policy())

    wire = request.wire_dict()
    assert set(wire) == {
        "protocolVersion",
        "operation",
        "request",
        "fence",
        "subject",
        "sealedByteBinding",
        "policy",
        "attemptNonce",
        "canonicalInputDigest",
    }
    body = dict(wire)
    digest = body.pop("canonicalInputDigest")
    expected = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    assert digest == expected

    mutated = dict(wire)
    mutated["canonicalInputDigest"] = _digest("0")
    with pytest.raises(ValidationError, match="canonicalInputDigest"):
        InspectorLaunchRequestV1.model_validate(mutated)

    extra = dict(wire)
    extra["downloadUrl"] = "https://forbidden.invalid/object"
    with pytest.raises(ValidationError):
        InspectorLaunchRequestV1.model_validate(extra)


def test_framed_raw_input_requires_exact_count_hash_and_sender_eof() -> None:
    """A short, altered, or trailing raw payload must not reach the staging callback."""
    payload = b"exact-sealed-input"
    request = _request(_policy(), payload)
    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        write_launch_request(client, request, BytesIO(payload), _limits())
        received = read_launch_request_header(server, _limits())
        chunks: list[bytes] = []
        receipt = read_bound_bytes(
            server,
            received.sealed_byte_binding,
            _limits(),
            chunks.append,
        )
        assert received == request
        assert b"".join(chunks) == payload
        assert receipt.observed_sha256 == _bytes_digest(payload)
        assert receipt.observed_size_bytes == len(payload)
    finally:
        client.close()
        server.close()

    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        header = request.canonical_bytes()
        client.sendall(struct.pack(">I", len(header)) + header + payload + b"trailing")
        client.shutdown(socket.SHUT_WR)
        parsed = read_launch_request_header(server, _limits())
        with pytest.raises(ProtocolViolation, match="trailing"):
            read_bound_bytes(server, parsed.sealed_byte_binding, _limits(), lambda _: None)
    finally:
        client.close()
        server.close()


def test_json_decoder_rejects_duplicate_nonfinite_and_unknown_frame_values() -> None:
    """Permissive JSON would permit ambiguous digest inputs or noncanonical durable values."""
    with pytest.raises(ProtocolViolation, match="duplicate"):
        decode_json_frame(b'{"x":1,"x":2}', _limits())
    with pytest.raises(ProtocolViolation, match="non-finite"):
        decode_json_frame(b'{"x":NaN}', _limits())
    with pytest.raises(ProtocolViolation, match="non-finite"):
        decode_json_frame(b'{"x":1e999}', _limits())
    with pytest.raises(ProtocolViolation, match="non-finite"):
        decode_json_frame(b'{"nested":[{"x":-1e999}]}', _limits())
    assert decode_json_frame(b'{"finite":1e3}', _limits()) == {"finite": 1_000.0}
    with pytest.raises(ProtocolViolation, match="object"):
        decode_json_frame(b"[]", _limits())


def test_upload_send_retries_heartbeat_and_keeps_the_original_absolute_deadline() -> None:
    """A blocked partial socket send must poll authority without extending its first deadline."""

    class _Clock:
        def __init__(self) -> None:
            self.now = 100.0

        def __call__(self) -> float:
            return self.now

    class _TimeoutThenPartialSocket:
        def __init__(self, clock: _Clock) -> None:
            self._clock = clock
            self.send_calls = 0
            self.timeouts: list[float] = []

        def settimeout(self, timeout: float) -> None:
            self.timeouts.append(timeout)

        def send(self, payload: bytes) -> int:
            del payload
            self.send_calls += 1
            if self.send_calls == 1:
                self._clock.now = 100.05
                raise TimeoutError
            if self.send_calls == 2:
                self._clock.now = 101.01
                return 1
            raise AssertionError("deadline retry must not start a new upload clock")

    clock = _Clock()
    deadline = ProtocolDeadline(1_000, clock)
    connection = _TimeoutThenPartialSocket(clock)
    authority_checks = 0

    def authority_is_current() -> bool:
        nonlocal authority_checks
        authority_checks += 1
        return True

    with pytest.raises(ProtocolDeadlineExceeded, match="global wire deadline"):
        write_launch_request(
            connection,  # type: ignore[arg-type]
            _request(_policy(), b"bound-input"),
            BytesIO(b"bound-input"),
            _limits(),
            deadline=deadline,
            monotonic=clock,
            wait_is_current=authority_is_current,
            heartbeat_interval_millis=100,
        )

    assert connection.timeouts == [0.1, 0.1]
    assert authority_checks >= 3
    assert deadline.expires_at == 101.0


def test_upload_rejects_a_deadline_elapsed_during_the_final_full_send() -> None:
    """A final successful send cannot authorize the subsequent trailing read or half-close."""

    class _Clock:
        def __init__(self) -> None:
            self.now = 100.0

        def __call__(self) -> float:
            return self.now

    class _LateFinalSendSocket:
        def __init__(self, clock: _Clock) -> None:
            self._clock = clock
            self.send_calls = 0
            self.shutdown_called = False

        def settimeout(self, timeout: float) -> None:
            del timeout

        def send(self, payload: bytes) -> int:
            self.send_calls += 1
            if self.send_calls == 2:
                self._clock.now = 101.1
            return len(payload)

        def shutdown(self, how: int) -> None:
            del how
            self.shutdown_called = True

    clock = _Clock()
    connection = _LateFinalSendSocket(clock)
    with pytest.raises(ProtocolDeadlineExceeded, match="global wire deadline"):
        write_launch_request(
            connection,  # type: ignore[arg-type]
            _request(_policy(), b"bound-input"),
            BytesIO(b"bound-input"),
            _limits(),
            deadline=ProtocolDeadline(1_000, clock),
            monotonic=clock,
        )

    assert connection.send_calls == 2
    assert connection.shutdown_called is False


def test_upload_rejects_a_deadline_elapsed_during_the_trailing_source_read() -> None:
    """A late EOF probe cannot proceed to digest acceptance or sender half-close."""

    class _Clock:
        def __init__(self) -> None:
            self.now = 200.0

        def __call__(self) -> float:
            return self.now

    class _CompleteSocket:
        def __init__(self) -> None:
            self.shutdown_called = False

        def settimeout(self, timeout: float) -> None:
            del timeout

        def send(self, payload: bytes) -> int:
            return len(payload)

        def shutdown(self, how: int) -> None:
            del how
            self.shutdown_called = True

    class _LateTrailingSource(BytesIO):
        def __init__(self, payload: bytes, clock: _Clock) -> None:
            super().__init__(payload)
            self._clock = clock
            self.read_calls = 0

        def read(self, size: int | None = -1) -> bytes:
            chunk = super().read(-1 if size is None else size)
            self.read_calls += 1
            if self.read_calls == 2:
                self._clock.now = 201.5
            return chunk

    clock = _Clock()
    connection = _CompleteSocket()
    source = _LateTrailingSource(b"bound-input", clock)
    with pytest.raises(ProtocolDeadlineExceeded, match="global wire deadline"):
        write_launch_request(
            connection,  # type: ignore[arg-type]
            _request(_policy(), b"bound-input"),
            source,
            _limits(),
            deadline=ProtocolDeadline(1_000, clock),
            monotonic=clock,
        )

    assert source.read_calls == 2
    assert connection.shutdown_called is False


@pytest.mark.parametrize(
    "raw",
    [
        {
            "protocolVersion": "inspector-launch.v1",
            "result": "ACCEPTED",
            "attemptNonce": "attempt-nonce-1",
            "canonicalInputDigest": None,
        },
        {
            "protocolVersion": "inspector-launch.v1",
            "result": "FAILED",
            "attemptNonce": "attempt-nonce-1",
            "reason": "INSPECTOR_UNAVAILABLE",
            "outputSha256": None,
        },
        {
            "protocolVersion": "inspector-launch.v1",
            "result": "COMPLETED",
            "attemptNonce": "attempt-nonce-1",
            "canonicalInputDigest": _digest("a"),
            "inspectorBuildDigest": _digest("b"),
            "outcome": {
                "artifactId": "ortho",
                "observedSha256": _digest("c"),
                "outcome": "REJECTED",
                "reason": "SYNTHETIC_REJECTED",
            },
            "outputSizeBytes": 0,
            "outputSha256": None,
        },
        {
            "protocolVersion": "inspector-launch.v1",
            "result": "COMPLETED",
            "attemptNonce": "attempt-nonce-1",
            "canonicalInputDigest": _digest("a"),
            "inspectorBuildDigest": _digest("b"),
            "outcome": {
                "artifactId": "ortho",
                "observedSha256": _digest("c"),
                "outcome": "REJECTED",
                "reason": "SYNTHETIC_REJECTED",
            },
            "outputSizeBytes": 0,
            "reason": None,
        },
    ],
)
def test_read_launch_result_rejects_explicit_nulls_outside_its_exact_variant(
    raw: dict[str, object],
) -> None:
    """A null-only forbidden field must not masquerade as an omitted wire member."""
    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        payload = canonical_json_bytes(raw)
        client.sendall(struct.pack(">I", len(payload)) + payload)
        with pytest.raises(ProtocolViolation, match="exact variant"):
            read_launch_result(server, _limits())
    finally:
        client.close()
        server.close()


def test_result_variants_are_closed_and_bind_operation_specific_output_shape() -> None:
    """An INSPECT result carrying derivative bytes or an unbound completion is invalid."""
    request = _request(_policy())
    accepted = InspectorLaunchResultV1.accepted(request.attempt_nonce)
    assert accepted.wire_dict() == {
        "protocolVersion": "inspector-launch.v1",
        "result": "ACCEPTED",
        "attemptNonce": request.attempt_nonce,
    }

    outcome = ArtifactInspectionOutcomeV1(
        artifact_id="ortho",
        observed_sha256=request.sealed_byte_binding.observed_sha256,
        outcome=ArtifactOutcome.REJECTED,
        reason="SYNTHETIC_REJECTED",
    )
    completed = InspectorLaunchResultV1.completed_inspection(
        request.attempt_nonce,
        request.canonical_input_digest,
        request.policy.parser_build_digest,
        outcome,
    )
    completed.validate_for(request)

    invalid = completed.wire_dict()
    invalid["outputSizeBytes"] = 1
    invalid["outputSha256"] = _digest("1")
    with pytest.raises(ValidationError, match="INSPECT"):
        InspectorLaunchResultV1.model_validate(invalid)


class _Catalog:
    def __init__(
        self,
        manifest: InspectorExecutionManifestV1 | None,
        *,
        status: CatalogStartupStatusV1 | None = None,
        revoked: bool | None = False,
    ) -> None:
        self.manifest = manifest
        self.status = status or CatalogStartupStatusV1(
            readable=True, trust_root_configured=True, catalog_identity_verified=True
        )
        self.revoked = revoked

    def startup_status(self) -> CatalogStartupStatusV1:
        return self.status

    def resolve_exact(
        self, *, parser_build_digest: str, resource_envelope_digest: str
    ) -> InspectorExecutionManifestV1 | None:
        if self.manifest is None:
            return None
        if (
            self.manifest.parser_build_digest != parser_build_digest
            or self.manifest.body.resource_envelope_digest != resource_envelope_digest
        ):
            return None
        return self.manifest

    def is_revoked(self, manifest: InspectorExecutionManifestV1) -> bool:
        assert manifest is self.manifest
        return cast(bool, self.revoked)


def test_catalog_preserves_an_unknown_revocation_value_for_fail_closed_admission() -> None:
    """Changing an unavailable revocation fact to a boolean must not let admission accept it."""
    manifest = _manifest()
    catalog = _Catalog(manifest, revoked=None)

    assert cast(object, catalog.is_revoked(manifest)) is None


class _Verifier:
    def __init__(self, verdict: SignatureVerificationVerdict) -> None:
        self.verdict = verdict

    def verify(
        self, payload: bytes, signature: InspectorExecutionManifestSignatureV1
    ) -> SignatureVerificationVerdict:
        del payload, signature
        return self.verdict


class _Profile:
    def __init__(
        self, verdict: InspectorOperationProfileDecision = InspectorOperationProfileDecision.ALLOW
    ) -> None:
        self.verdict = verdict
        self.calls: list[tuple[str, str, ProcessingArtifactKind, str, InspectorOperation]] = []

    def allows(
        self,
        *,
        parser_build_digest: str,
        grammar_digest: str,
        artifact_kind: ProcessingArtifactKind,
        content_type: str,
        operation: InspectorOperation,
    ) -> InspectorOperationProfileDecision:
        self.calls.append(
            (parser_build_digest, grammar_digest, artifact_kind, content_type, operation)
        )
        return self.verdict


@dataclass
class _Reservation:
    released: bool = False

    def release(self) -> None:
        self.released = True


class _Accounting:
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[tuple[int, int, int]] = []
        self.reservations: list[_Reservation] = []

    def reserve(
        self,
        *,
        request_units: int,
        concurrency_units: int,
        spool_bytes: int,
        deadline_monotonic: float,
    ) -> _Reservation | None:
        del deadline_monotonic
        self.calls.append((request_units, concurrency_units, spool_bytes))
        if not self.allow:
            return None
        reservation = _Reservation()
        self.reservations.append(reservation)
        return reservation


class _Staged:
    def __init__(self, buffer: BytesIO, max_bytes: int) -> None:
        self.buffer = buffer
        self.max_bytes = max_bytes
        self.aborted = False

    def write(self, chunk: bytes) -> None:
        if self.buffer.tell() + len(chunk) > self.max_bytes:
            raise ValueError("test staging cap exceeded")
        self.buffer.write(chunk)

    def finish(self) -> None:
        self.buffer.seek(0)

    def read(self, maximum: int = -1) -> bytes:
        return self.buffer.read(maximum)

    def abort(self) -> None:
        self.aborted = True


class _Staging:
    def __init__(self) -> None:
        self.staged: list[_Staged] = []

    def begin(self, *, maximum_bytes: int, deadline_monotonic: float) -> _Staged:
        del deadline_monotonic
        staged = _Staged(BytesIO(), maximum_bytes)
        self.staged.append(staged)
        return staged


class _Backend:
    def __init__(self, completed: InspectorBackendCompletedV1 | Exception) -> None:
        self.completed = completed
        self.calls: list[tuple[bytes, InspectorEffectiveLimitsV1]] = []

    def execute(
        self,
        *,
        request: InspectorLaunchRequestV1,
        staged_input: InspectorStagedBytesPort,
        limits: InspectorEffectiveLimitsV1,
        deadline_monotonic: float,
        is_cancelled: Callable[[], bool],
    ) -> InspectorBackendCompletedV1:
        del request, deadline_monotonic
        assert is_cancelled() is False
        self.calls.append((staged_input.read(), limits))
        if isinstance(self.completed, Exception):
            raise self.completed
        return self.completed


def _backend_result(request: InspectorLaunchRequestV1) -> InspectorBackendCompletedV1:
    return InspectorBackendCompletedV1(
        inspector_build_digest=request.policy.parser_build_digest,
        outcome=ArtifactInspectionOutcomeV1(
            artifact_id=request.sealed_byte_binding.artifact_id,
            observed_sha256=request.sealed_byte_binding.observed_sha256,
            outcome=ArtifactOutcome.REJECTED,
            reason="SYNTHETIC_REJECTED",
        ),
        output=BytesIO(),
        output_size_bytes=0,
        output_sha256=None,
    )


def _launcher(
    request: InspectorLaunchRequestV1,
    *,
    catalog: _Catalog | None = None,
    verifier: _Verifier | None = None,
    profile: _Profile | None = None,
    accounting: _Accounting | None = None,
    staging: _Staging | None = None,
    backend: _Backend | None = None,
    worker_uid: int = _WORKER_UID,
    protocol_limits: ProtocolLimitsV1 | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> ExternalInspectorLauncher:
    actual_catalog = catalog or _Catalog(_manifest())
    actual_accounting = accounting or _Accounting()
    actual_staging = staging or _Staging()
    actual_backend = backend or _Backend(_backend_result(request))
    return ExternalInspectorLauncher(
        required_worker_uid=worker_uid,
        catalog=actual_catalog,
        verifier=verifier or _Verifier(SignatureVerificationVerdict.VALID),
        operation_profile=profile or _Profile(),
        accounting=actual_accounting,
        staging=actual_staging,
        backend=actual_backend,
        protocol_limits=protocol_limits or _limits(),
        monotonic=monotonic,
    )


def _run_handler(
    launcher: ExternalInspectorLauncher,
    request: InspectorLaunchRequestV1,
    payload: bytes,
) -> tuple[InspectorLaunchResultV1, InspectorLaunchResultV1]:
    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    errors: list[BaseException] = []

    def run() -> None:
        try:
            launcher.handle_connection(server)
        except BaseException as exc:  # pragma: no cover - asserted through result/cleanup below
            errors.append(exc)
        finally:
            server.close()

    thread = threading.Thread(target=run)
    thread.start()
    try:
        write_launch_request(client, request, BytesIO(payload), _limits())
        accepted = read_launch_result(client, _limits())
        terminal = read_launch_result(client, _limits())
        assert client.recv(1) == b""
    finally:
        client.close()
        thread.join(timeout=2)
    assert not thread.is_alive()
    assert not errors
    return accepted, terminal


def test_launcher_uses_os_peer_before_read_then_admits_exact_bound_input() -> None:
    """Moving peer admission after header parsing would disclose/load untrusted request data."""
    payload = b"bound-input"
    request = _request(_policy(), payload)
    accounting = _Accounting()
    staging = _Staging()
    backend = _Backend(_backend_result(request))
    launcher = _launcher(request, accounting=accounting, staging=staging, backend=backend)

    accepted, terminal = _run_handler(launcher, request, payload)

    assert accepted.result == "ACCEPTED"
    terminal.validate_for(request)
    assert backend.calls == [(payload, backend.calls[0][1])]
    assert accounting.calls == [(1, 1, len(payload))]
    assert all(reservation.released for reservation in accounting.reservations)
    assert staging.staged[0].max_bytes == len(payload)
    assert staging.staged[0].aborted is True


class _RecvTrackingSocket:
    def __init__(self, wrapped: socket.socket) -> None:
        self.wrapped = wrapped
        self.recv_calls = 0

    def getsockopt(self, level: int, option: int, buffer_size: int | None = None) -> int | bytes:
        if buffer_size is None:
            return self.wrapped.getsockopt(level, option)
        return self.wrapped.getsockopt(level, option, buffer_size)

    def recv(self, buffer_size: int, flags: int = 0) -> bytes:
        self.recv_calls += 1
        return self.wrapped.recv(buffer_size, flags)

    def close(self) -> None:
        self.wrapped.close()


def test_unknown_os_peer_is_closed_without_receiving_a_header() -> None:
    """A request-supplied UID or header read before SO_PEERCRED would bypass admission."""
    request = _request(_policy())
    launcher = _launcher(request, worker_uid=_WORKER_UID + 1)
    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    tracked = _RecvTrackingSocket(server)
    try:
        launcher.handle_connection(tracked)  # type: ignore[arg-type]
        assert tracked.recv_calls == 0
        assert client.recv(1) == b""
    finally:
        client.close()
        tracked.close()


def test_late_catalog_status_stops_admission_before_later_catalog_or_verifier_ports() -> None:
    """A late startup-status return must prevent resolver, revocation, and verifier use."""

    class _Clock:
        def __init__(self) -> None:
            self.now = 100.0

        def __call__(self) -> float:
            return self.now

    class _LateStartupCatalog(_Catalog):
        def __init__(self, clock: _Clock) -> None:
            super().__init__(_manifest())
            self._clock = clock
            self.resolve_calls = 0
            self.revocation_calls = 0

        def startup_status(self) -> CatalogStartupStatusV1:
            self._clock.now = 100.03
            return super().startup_status()

        def resolve_exact(
            self, *, parser_build_digest: str, resource_envelope_digest: str
        ) -> InspectorExecutionManifestV1 | None:
            self.resolve_calls += 1
            return super().resolve_exact(
                parser_build_digest=parser_build_digest,
                resource_envelope_digest=resource_envelope_digest,
            )

        def is_revoked(self, manifest: InspectorExecutionManifestV1) -> bool:
            self.revocation_calls += 1
            return super().is_revoked(manifest)

    class _TrackingVerifier(_Verifier):
        def __init__(self) -> None:
            super().__init__(SignatureVerificationVerdict.VALID)
            self.calls = 0

        def verify(
            self, payload: bytes, signature: InspectorExecutionManifestSignatureV1
        ) -> SignatureVerificationVerdict:
            self.calls += 1
            return super().verify(payload, signature)

    clock = _Clock()
    request = _request(_policy())
    catalog = _LateStartupCatalog(clock)
    verifier = _TrackingVerifier()
    launcher = _launcher(
        request,
        catalog=catalog,
        verifier=verifier,
        protocol_limits=ProtocolLimitsV1(
            max_header_bytes=16_384,
            max_chunk_bytes=128,
            max_input_bytes=4_096,
            max_output_bytes=4_096,
            max_wire_duration_millis=20,
        ),
        monotonic=clock,
    )

    with pytest.raises(ProtocolDeadlineExceeded, match="global wire deadline"):
        launcher.admit(request, ProcessingArtifactKind.ORTHO, "image/tiff")

    assert catalog.resolve_calls == 0
    assert catalog.revocation_calls == 0
    assert verifier.calls == 0


def test_direct_admission_rejects_a_profile_return_after_its_existing_deadline() -> None:
    """A public admit call cannot return ALLOW after its profile port consumes its deadline."""

    class _Clock:
        def __init__(self) -> None:
            self.now = 200.0

        def __call__(self) -> float:
            return self.now

    class _LateProfile(_Profile):
        def __init__(self, clock: _Clock) -> None:
            super().__init__()
            self._clock = clock

        def allows(
            self,
            *,
            parser_build_digest: str,
            grammar_digest: str,
            artifact_kind: ProcessingArtifactKind,
            content_type: str,
            operation: InspectorOperation,
        ) -> InspectorOperationProfileDecision:
            self._clock.now = 200.03
            return super().allows(
                parser_build_digest=parser_build_digest,
                grammar_digest=grammar_digest,
                artifact_kind=artifact_kind,
                content_type=content_type,
                operation=operation,
            )

    clock = _Clock()
    request = _request(_policy())
    launcher = _launcher(
        request,
        profile=_LateProfile(clock),
        protocol_limits=ProtocolLimitsV1(
            max_header_bytes=16_384,
            max_chunk_bytes=128,
            max_input_bytes=4_096,
            max_output_bytes=4_096,
            max_wire_duration_millis=20,
        ),
        monotonic=clock,
    )

    with pytest.raises(ProtocolDeadlineExceeded, match="global wire deadline"):
        launcher.admit(request, ProcessingArtifactKind.ORTHO, "image/tiff")


@pytest.mark.parametrize(
    "catalog,verifier",
    [
        (
            _Catalog(
                _manifest(),
                status=CatalogStartupStatusV1(
                    readable=False, trust_root_configured=True, catalog_identity_verified=True
                ),
            ),
            _Verifier(SignatureVerificationVerdict.VALID),
        ),
        (_Catalog(None), _Verifier(SignatureVerificationVerdict.VALID)),
        (_Catalog(_manifest(), revoked=True), _Verifier(SignatureVerificationVerdict.VALID)),
        (_Catalog(_manifest(), revoked=None), _Verifier(SignatureVerificationVerdict.VALID)),
        (_Catalog(_manifest()), _Verifier(SignatureVerificationVerdict.INVALID)),
    ],
)
def test_launcher_fails_closed_for_catalog_or_signature_unavailability(
    catalog: _Catalog, verifier: _Verifier
) -> None:
    """Unreadable, unknown, revoked, or unverifiable manifests cannot admit a backend call."""
    request = _request(_policy())
    launcher = _launcher(request, catalog=catalog, verifier=verifier)

    with pytest.raises(InspectorSandboxUnavailable):
        launcher.admit(request, ProcessingArtifactKind.ORTHO, "image/tiff")


def test_admission_clamps_signed_and_policy_limits_before_staging_or_backend() -> None:
    """Using policy values above hard ceilings would silently create a larger sandbox envelope."""
    request = _request(_policy(), b"x" * 41)
    accounting = _Accounting()
    launcher = _launcher(request, accounting=accounting)

    with pytest.raises(ProtocolViolation, match="input"):
        launcher.admit(request, ProcessingArtifactKind.ORTHO, "image/tiff")
    assert accounting.calls == []

    admitted = launcher.admit(
        _request(_policy(), b"x" * 10), ProcessingArtifactKind.ORTHO, "image/tiff"
    )
    assert admitted.effective_limits == InspectorEffectiveLimitsV1(
        max_input_bytes=40,
        max_memory_bytes=64,
        max_workspace_bytes=60,
        max_output_bytes=32,
        max_wall_time_millis=2_000,
        max_pids=17,
        cpu_period_micros=100_000,
        cpu_quota_micros=50_000,
        max_log_bytes=2_048,
    )


def test_reservation_and_staging_are_released_when_backend_fails() -> None:
    """A terminal backend error must not leak aggregate concurrency or spool capacity."""
    payload = b"bound-input"
    request = _request(_policy(), payload)
    accounting = _Accounting()
    staging = _Staging()
    backend = _Backend(RuntimeError("synthetic backend error"))
    launcher = _launcher(request, accounting=accounting, staging=staging, backend=backend)
    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        thread = threading.Thread(target=lambda: launcher.handle_connection(server))
        thread.start()
        write_launch_request(client, request, BytesIO(payload), _limits())
        assert read_launch_result(client, _limits()).result == "ACCEPTED"
        assert read_launch_result(client, _limits()).result == "FAILED"
        thread.join(timeout=2)
        assert not thread.is_alive()
    finally:
        client.close()
        server.close()
    assert all(item.released for item in accounting.reservations)
    assert staging.staged[0].aborted is True


def test_sanitize_reserves_and_releases_bounded_output_spool_before_writing_raw_bytes() -> None:
    """Derivative bytes need their own aggregate spool reservation and terminal cleanup."""
    payload = b"bound-input"
    sanitized = b"sanitized-output"
    request = _request(_policy(), payload, operation=InspectorOperation.SANITIZE)
    accounting = _Accounting()
    staging = _Staging()
    backend = _Backend(
        InspectorBackendCompletedV1(
            inspector_build_digest=request.policy.parser_build_digest,
            outcome="SANITIZED",
            output=BytesIO(sanitized),
            output_size_bytes=len(sanitized),
            output_sha256=_bytes_digest(sanitized),
        )
    )
    launcher = _launcher(request, accounting=accounting, staging=staging, backend=backend)
    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        thread = threading.Thread(target=lambda: launcher.handle_connection(server))
        thread.start()
        write_launch_request(client, request, BytesIO(payload), _limits())
        assert read_launch_result(client, _limits()).result == "ACCEPTED"
        terminal = read_launch_result(client, _limits())
        terminal.validate_for(request)
        assert client.recv(len(sanitized)) == sanitized
        assert client.recv(1) == b""
        thread.join(timeout=2)
        assert not thread.is_alive()
    finally:
        client.close()
        server.close()
    assert accounting.calls == [(1, 1, len(payload)), (0, 0, len(sanitized))]
    assert all(item.released for item in accounting.reservations)
    assert [item.aborted for item in staging.staged] == [True, True]


def test_late_sanitize_output_reservation_is_released_before_staging_begins() -> None:
    """A late reserve return must release its spool token before any later output work."""

    class _Clock:
        def __init__(self) -> None:
            self.now = 100.0

        def __call__(self) -> float:
            return self.now

    class _LateOutputAccounting(_Accounting):
        def __init__(self, clock: _Clock) -> None:
            super().__init__()
            self._clock = clock

        def reserve(
            self,
            *,
            request_units: int,
            concurrency_units: int,
            spool_bytes: int,
            deadline_monotonic: float,
        ) -> _Reservation | None:
            reservation = super().reserve(
                request_units=request_units,
                concurrency_units=concurrency_units,
                spool_bytes=spool_bytes,
                deadline_monotonic=deadline_monotonic,
            )
            self._clock.now = 100.03
            return reservation

    payload = b"bound-input"
    sanitized = b"sanitized-output"
    request = _request(_policy(), payload, operation=InspectorOperation.SANITIZE)
    clock = _Clock()
    accounting = _LateOutputAccounting(clock)
    staging = _Staging()
    launcher = _launcher(request, accounting=accounting, staging=staging)
    completed = InspectorBackendCompletedV1(
        inspector_build_digest=request.policy.parser_build_digest,
        outcome="SANITIZED",
        output=BytesIO(sanitized),
        output_size_bytes=len(sanitized),
        output_sha256=_bytes_digest(sanitized),
    )
    admission = launcher.admit(request, ProcessingArtifactKind.ORTHO, "image/tiff")

    with pytest.raises(ProtocolDeadlineExceeded, match="global wire deadline"):
        launcher._write_completed_result(  # noqa: SLF001 - direct resource-ownership boundary
            object(),  # type: ignore[arg-type]
            request,
            completed,
            admission.effective_limits,
            ProtocolDeadline(20, clock),
        )

    assert len(accounting.reservations) == 1
    assert accounting.reservations[0].released is True
    assert staging.staged == []


def test_policy_wall_cap_can_only_shorten_the_already_started_global_deadline() -> None:
    """Manifest admission cannot reset a header-started deadline after expensive setup."""
    ticks = iter((100.0, 100.4))
    deadline = ProtocolDeadline(5_000, monotonic=lambda: next(ticks))

    deadline.cap_duration_millis(1_000)

    assert deadline.expires_at == pytest.approx(101.4)


def test_client_full_close_cancels_backend_through_the_owned_uds_socket() -> None:
    """Expected sender half-close is distinct from a later full peer close during backend work."""

    class _CancellationAwareBackend(_Backend):
        def __init__(self, completed: InspectorBackendCompletedV1) -> None:
            super().__init__(completed)
            self.started = threading.Event()
            self.finished = threading.Event()
            self.saw_cancel = False

        def execute(
            self,
            *,
            request: InspectorLaunchRequestV1,
            staged_input: InspectorStagedBytesPort,
            limits: InspectorEffectiveLimitsV1,
            deadline_monotonic: float,
            is_cancelled: Callable[[], bool],
        ) -> InspectorBackendCompletedV1:
            del request, staged_input, limits, deadline_monotonic
            self.started.set()
            until = time.monotonic() + 0.5
            while time.monotonic() < until:
                if is_cancelled():
                    self.saw_cancel = True
                    self.finished.set()
                    raise RuntimeError("cooperative backend cancelled")
                time.sleep(0.01)
            self.finished.set()
            assert not isinstance(self.completed, Exception)
            return self.completed

    payload = b"bound-input"
    request = _request(_policy(), payload)
    backend = _CancellationAwareBackend(_backend_result(request))
    launcher = _launcher(request, backend=backend)
    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        thread = threading.Thread(target=lambda: launcher.handle_connection(server))
        thread.start()
        write_launch_request(client, request, BytesIO(payload), _limits())
        assert read_launch_result(client, _limits()).result == "ACCEPTED"
        assert backend.started.wait(timeout=0.2)
        client.close()
        assert backend.finished.wait(timeout=0.3)
        thread.join(timeout=1)
        assert not thread.is_alive()
    finally:
        client.close()
        server.close()
    assert backend.saw_cancel is True


def test_bound_reader_enforces_one_global_deadline_instead_of_resetting_per_chunk() -> None:
    """Resetting the timeout after each slow chunk would permit an unbounded slowloris input."""

    class _SlowSocket:
        def __init__(self) -> None:
            self.values = [b"a", b"b", b"c"]

        def settimeout(self, timeout: float) -> None:
            del timeout

        def recv(self, maximum: int) -> bytes:
            del maximum
            return self.values.pop(0) if self.values else b""

    ticks = iter((0.0, 0.4, 0.8, 1.2))
    binding = SealedByteBindingV1(
        artifact_id="ortho", observed_sha256=_bytes_digest(b"abc"), observed_size_bytes=3
    )
    with pytest.raises(ProtocolDeadlineExceeded):
        read_bound_bytes(
            _SlowSocket(),  # type: ignore[arg-type]
            binding,
            ProtocolLimitsV1(
                max_header_bytes=16,
                max_chunk_bytes=1,
                max_input_bytes=3,
                max_output_bytes=1,
                max_wire_duration_millis=1_000,
            ),
            lambda _: None,
            monotonic=lambda: next(ticks),
        )
