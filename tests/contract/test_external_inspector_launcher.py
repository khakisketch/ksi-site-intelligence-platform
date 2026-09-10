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
from ksi_processing_controller.external_geotiff_profile import external_geotiff_profile_digest_v1
from ksi_processing_controller.external_inspector_attempts import (
    AttemptBindingV1,
    PrivateStagingRootV1,
    RuntimeParentReceiptV1,
    StagingAllocationPlanV1,
    StagingAllocationReceiptV1,
    StagingFileIdentityV1,
)
from ksi_processing_controller.external_inspector_container_protocol import (
    FixedContainerConfigurationV1,
)
from ksi_processing_controller.external_inspector_launcher import (
    CatalogStartupStatusV1,
    ExternalInspectorLauncher,
    InspectorBackendCompletedV1,
    InspectorBackendCreatedV1,
    InspectorEffectiveLimitsV1,
    InspectorOperationProfileDecision,
    InspectorSandboxUnavailable,
    _AttemptRuntimeCleanupCoordinator,
)
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedByteReaderPort,
    DeadlineBoundedBytesReader,
    DeadlineBoundedDiscardingSink,
    DeadlineBoundedMemorySink,
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
from ksi_processing_controller.external_inspector_runtime import (
    CpuCounterUnitV1,
    FixedRuntimeMeasurementV1,
    RuntimeControlDispositionV1,
)
from ksi_processing_controller.external_inspector_staging import (
    InspectorReadOnlyBindV1,
    InspectorSealedInputPort,
    MappedInspectorReaderV1,
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


def _manifest(
    envelope: ResourceEnvelopeV1 | None = None, *, backend_profile_digest: str | None = None
) -> InspectorExecutionManifestV1:
    from ksi_processing_controller.external_inspector_container_protocol import (
        compiled_inner_protocol_digest_v1,
        compiled_security_profile_digest_v1,
    )

    effective_envelope = envelope or _envelope()
    assert effective_envelope.resource_envelope_digest is not None
    body = InspectorExecutionManifestBodyV1(
        image_identity=InspectorImageIdentityV1(
            oci_manifest_digest=_digest("c"), oci_config_digest=_digest("d")
        ),
        source_tree_digest=_digest("e"),
        build_provenance_digest=_digest("f"),
        sbom_digest=_digest("1"),
        inspector_protocol_digest=compiled_inner_protocol_digest_v1(),
        backend_profile_digest=backend_profile_digest or external_geotiff_profile_digest_v1(),
        security_profile_digest=compiled_security_profile_digest_v1(),
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


def _policy(
    manifest: InspectorExecutionManifestV1 | None = None,
    *,
    grammar_digest: str | None = None,
) -> ExternalValidationPolicyV1:
    actual_manifest = manifest or _manifest()
    envelope = _envelope()
    assert envelope.resource_envelope_digest == actual_manifest.body.resource_envelope_digest
    return ExternalValidationPolicyV1(
        policy_id="synthetic-policy",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=actual_manifest.parser_build_digest,
        grammar_digest=grammar_digest or external_geotiff_profile_digest_v1(),
        resource_envelope=envelope,
        resource_envelope_digest=envelope.resource_envelope_digest,
        authority_record_digest=_digest("6"),
        inspection_rule_ids=(),
        evidence_rule_ids=(),
        compatibility_mapping_digests=(),
        synthetic_test_only=True,
    ).sealed()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("inspector_protocol_digest", _digest("e"), "protocol"),
        ("security_profile_digest", _digest("f"), "security"),
    ],
)
def test_admission_rejects_unknown_signed_inner_protocol_or_security_profile(
    field: str, value: str, message: str
) -> None:
    """Signature validity cannot declare an uncompiled local runtime profile compatible."""
    manifest = _manifest()
    unknown = manifest.model_copy(
        update={
            "body": manifest.body.model_copy(
                update={
                    field: value,
                }
            )
        }
    )
    unknown = unknown.model_copy(
        update={
            "signature": unknown.signature.model_copy(
                update={"digest": unknown.body.canonical_body_digest()}
            )
        }
    )
    request = _request(_policy(unknown))
    launcher = _launcher(request, catalog=_Catalog(unknown))

    with pytest.raises(InspectorSandboxUnavailable, match=message):
        launcher.admit(request, ProcessingArtifactKind.ORTHO, "image/tiff")


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
        sink = DeadlineBoundedMemorySink()
        receipt = read_bound_bytes(
            server,
            received.sealed_byte_binding,
            _limits(),
            sink,
        )
        assert received == request
        assert b"".join(sink.chunks) == payload
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
            read_bound_bytes(
                server,
                parsed.sealed_byte_binding,
                _limits(),
                DeadlineBoundedDiscardingSink(),
            )
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

    class _LateTrailingSource:
        def __init__(self, payload: bytes, clock: _Clock) -> None:
            self._payload = payload
            self._position = 0
            self._clock = clock
            self.read_calls = 0

        def read_chunk(
            self,
            maximum_bytes: int,
            *,
            deadline: ProtocolDeadline,
            wait_is_current: Callable[[], bool] | None,
            heartbeat_interval_millis: int | None,
        ) -> bytes:
            del deadline, wait_is_current, heartbeat_interval_millis
            chunk = self._payload[self._position : self._position + maximum_bytes]
            self._position += len(chunk)
            self.read_calls += 1
            if self.read_calls == 2:
                self._clock.now = 201.5
            return chunk

        def close(self) -> None:
            return None

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
            raise ProtocolViolation("synthetic staging authority lost")
        deadline.remaining()
        self.write(chunk)
        deadline.remaining()

    def finish(self) -> None:
        self.buffer.seek(0)

    def finish_bounded(
        self,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> None:
        del heartbeat_interval_millis
        if wait_is_current is not None and not wait_is_current():
            raise ProtocolViolation("synthetic staging authority lost")
        deadline.remaining()
        self.finish()
        deadline.remaining()

    def read(self, maximum: int = -1) -> bytes:
        return self.buffer.read(maximum)

    def read_chunk(
        self,
        maximum_bytes: int,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> bytes:
        del heartbeat_interval_millis
        if wait_is_current is not None and not wait_is_current():
            raise ProtocolViolation("synthetic staging authority lost")
        deadline.remaining()
        result = self.read(maximum_bytes)
        deadline.remaining()
        return result

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


class _InputSealed:
    def __init__(self, payload: bytes, reader: MappedInspectorReaderV1) -> None:
        self.payload = payload
        self.reader = reader
        self.prepared = False
        self.aborted = False
        self.relinquished = False

    def prepare_read_only_bind(self, *, deadline_monotonic: float) -> InspectorReadOnlyBindV1:
        del deadline_monotonic
        self.prepared = True
        return InspectorReadOnlyBindV1(
            source=_InputBorrowedSource(),
            target_path="/input/artifact.tif",
            read_only=True,
            observed_sha256=_bytes_digest(self.payload),
            observed_size_bytes=len(self.payload),
            source_device=1,
            source_inode=2,
            source_owner_uid=os.geteuid(),
            source_owner_gid=os.getegid(),
            source_link_count=1,
            reader_mapping_witness=self.reader.mapping_witness,
        )

    def abort(self) -> None:
        self.aborted = True

    def relinquish_for_recovery(self) -> None:
        """Synthetic equivalent of closing retained FDs without unlinking state."""
        self.relinquished = True


class _InputBorrowedSource:
    def verify_readback(self, *, deadline_monotonic: float):  # type: ignore[no-untyped-def]
        del deadline_monotonic
        raise AssertionError("launcher test source does not verify bytes")

    def read_at(self, *, offset: int, maximum_bytes: int, deadline_monotonic: float) -> bytes:
        del offset, maximum_bytes, deadline_monotonic
        return b""

    def consume_fd(self, consumer: Callable[[int], object], *, deadline_monotonic: float) -> object:
        del deadline_monotonic
        return consumer(42)


class _InputMutable:
    def __init__(self, maximum: int, staging: _InputStaging) -> None:
        self.maximum = maximum
        self.staging = staging
        self.buffer = BytesIO()
        self.aborted = False
        self.relinquished = False

    def write(self, chunk: bytes) -> None:
        if self.buffer.tell() + len(chunk) > self.maximum:
            raise ValueError("test input staging cap exceeded")
        self.buffer.write(chunk)

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
            raise ProtocolViolation("synthetic input authority lost")
        deadline.remaining()
        self.write(chunk)
        deadline.remaining()

    def seal_for_reader(
        self,
        *,
        expected_sha256: str,
        expected_size_bytes: int,
        reader: MappedInspectorReaderV1,
        supplementary_groups: tuple[int, ...],
        deadline_monotonic: float,
    ) -> _InputSealed:
        del supplementary_groups, deadline_monotonic
        payload = self.buffer.getvalue()
        assert expected_size_bytes == len(payload)
        assert expected_sha256 == _bytes_digest(payload)
        sealed = _InputSealed(payload, reader)
        self.staging.sealed.append(sealed)
        return sealed

    def abort(self) -> None:
        self.aborted = True

    def relinquish_for_recovery(self) -> None:
        self.relinquished = True


class _InputStaging:
    def __init__(self) -> None:
        self.mutable: list[_InputMutable] = []
        self.sealed: list[_InputSealed] = []
        self.finalized: list[tuple[StagingAllocationPlanV1, StagingAllocationReceiptV1]] = []

    def private_root_identity(self) -> PrivateStagingRootV1:
        return PrivateStagingRootV1(
            device=1,
            inode=10,
            mode=0o700,
            owner_uid=os.geteuid(),
            owner_gid=os.getegid(),
        )

    def begin(self, *, maximum_bytes: int, deadline_monotonic: float) -> _InputMutable:
        del deadline_monotonic
        mutable = _InputMutable(maximum_bytes, self)
        self.mutable.append(mutable)
        return mutable

    def begin_registered(
        self,
        *,
        plan: StagingAllocationPlanV1,
        maximum_bytes: int,
        deadline_monotonic: float,
    ) -> tuple[_InputMutable, StagingAllocationReceiptV1]:
        assert plan.root == self.private_root_identity()
        mutable = self.begin(
            maximum_bytes=maximum_bytes,
            deadline_monotonic=deadline_monotonic,
        )
        receipt = StagingAllocationReceiptV1(
            marker=StagingFileIdentityV1(1, 11, 0o600, os.geteuid(), os.getegid(), 1, 1),
            directory=StagingFileIdentityV1(1, 12, 0o700, os.geteuid(), os.getegid(), 1, 0),
            artifact=StagingFileIdentityV1(1, 2, 0o600, os.geteuid(), os.getegid(), 1, 0),
        )
        return mutable, receipt

    def finalize_registered_cleanup(
        self,
        *,
        plan: StagingAllocationPlanV1,
        receipt: StagingAllocationReceiptV1,
    ) -> None:
        self.finalized.append((plan, receipt))


class _Attempts:
    """Explicit synthetic port; production receives the durable journal implementation."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def intend(self, binding: AttemptBindingV1) -> None:
        self.events.append("INTENDED")

    def staging_allocated(self, attempt_nonce: str, receipt: StagingAllocationReceiptV1) -> None:
        del attempt_nonce, receipt
        self.events.append("STAGING_ALLOCATED")

    def input_bound(self, attempt_nonce: str, **kwargs: object) -> None:
        del attempt_nonce, kwargs
        self.events.append("INPUT_BOUND")

    def runtime_parent_creating(self, attempt_nonce: str) -> None:
        del attempt_nonce
        self.events.append("RUNTIME_PARENT_CREATING")

    def container_bound(self, attempt_nonce: str, runtime_id: str) -> None:
        del attempt_nonce, runtime_id
        self.events.append("CONTAINER_BOUND")

    def runtime_parent_bound(self, attempt_nonce: str, receipt: RuntimeParentReceiptV1) -> None:
        del attempt_nonce, receipt
        self.events.append("RUNTIME_PARENT_BOUND")

    def container_creating(self, attempt_nonce: str) -> None:
        del attempt_nonce
        self.events.append("CONTAINER_CREATING")

    def cleanup_required(self, attempt_nonce: str, *, disposition: str) -> None:
        del attempt_nonce, disposition
        self.events.append("CLEANUP_REQUIRED")

    def cleanup_failed(self, attempt_nonce: str, *, reason: str) -> None:
        del attempt_nonce, reason
        self.events.append("CLEANUP_FAILED")

    def cleaned(self, attempt_nonce: str) -> None:
        del attempt_nonce
        self.events.append("CLEANED")


class _AttemptRecovery:
    """Explicit synthetic startup port; production uses the durable recovery coordinator."""

    def __init__(self, unavailable: bool = False) -> None:
        self.calls = 0
        self._unavailable = unavailable

    def recover_startup(self) -> None:
        self.calls += 1
        if self._unavailable:
            raise RuntimeError("synthetic uncertain allocation")


class _RuntimeParent:
    """Synthetic parent receipt; production uses the transient user-systemd controller."""

    def bind_before_create(
        self,
        *,
        binding: AttemptBindingV1,
        configuration: FixedContainerConfigurationV1,
    ) -> RuntimeParentReceiptV1:
        del configuration
        return RuntimeParentReceiptV1(
            unit_name=binding.systemd_slice_name,
            object_path="/org/freedesktop/systemd1/unit/synthetic",
            description="ksi-external-inspector-attempt.v1:" + binding.digest,
            slice_name=binding.systemd_base_slice,
            control_group="/synthetic/" + binding.systemd_slice_name,
            invocation_id="a" * 32,
            device=1,
            inode=2,
            controllers=("cpu", "memory", "pids"),
            cpu_counter_unit="CPU_USEC",
            baseline_cpu_counter=0,
            cpu_budget_counter=1_000_000,
        )

    def stop_exact(self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1) -> bool:
        del binding, receipt
        return True

    def adopt_if_prebound(self, *, binding: AttemptBindingV1) -> RuntimeParentReceiptV1 | None:
        del binding
        return None

    def verify_before_quiesce(
        self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1, runtime_id: str
    ) -> bool:
        del binding, receipt, runtime_id
        return True

    def verify_final_before_remove(
        self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1, runtime_id: str
    ) -> bool:
        del binding, receipt, runtime_id
        return True


class _RuntimeCleanup:
    """Explicit synthetic port; production must provide exact runtime-ID removal."""

    def __init__(self, removed: bool = True) -> None:
        self.runtime_ids: list[str] = []
        self._removed = removed

    def remove_exact(
        self,
        *,
        attempt: AttemptBindingV1,
        runtime_id: str,
        deadline_monotonic: float,
    ) -> bool:
        del attempt, deadline_monotonic
        self.runtime_ids.append(runtime_id)
        return self._removed

    def quiesce_exact(
        self,
        *,
        attempt: AttemptBindingV1,
        runtime_id: str,
        deadline_monotonic: float,
    ) -> bool:
        del attempt, runtime_id, deadline_monotonic
        return True

    def resolve_exact(self, binding: AttemptBindingV1) -> str | None:
        del binding
        return None


class _ReaderMapping:
    def __init__(self, reader: MappedInspectorReaderV1 | None = None) -> None:
        self.reader = reader or MappedInspectorReaderV1(
            container_uid=10001,
            container_gid=10001,
            host_uid=20001,
            host_gid=20001,
            mapping_witness="synthetic-mapping-v1",
        )
        self.calls: list[tuple[int, int, tuple[int, ...]]] = []

    def resolve_exact(
        self,
        *,
        runtime_uid: int,
        runtime_gid: int,
        supplementary_groups: tuple[int, ...],
        deadline_monotonic: float,
    ) -> MappedInspectorReaderV1 | None:
        del deadline_monotonic
        self.calls.append((runtime_uid, runtime_gid, supplementary_groups))
        return self.reader


class _Backend:
    def __init__(self, completed: InspectorBackendCompletedV1 | Exception) -> None:
        self.completed = completed
        self.calls: list[tuple[bytes, InspectorEffectiveLimitsV1]] = []
        self.configurations: list[FixedContainerConfigurationV1] = []
        self.created: list[InspectorBackendCreatedV1] = []

    def create(
        self,
        *,
        attempt: AttemptBindingV1,
        request: InspectorLaunchRequestV1,
        sealed_input: InspectorSealedInputPort,
        limits: InspectorEffectiveLimitsV1,
        configuration: FixedContainerConfigurationV1,
        deadline_monotonic: float,
        is_cancelled: Callable[[], bool],
    ) -> InspectorBackendCreatedV1:
        del attempt, request, sealed_input, limits, configuration, deadline_monotonic
        assert is_cancelled() is False
        created = InspectorBackendCreatedV1(runtime_id="synthetic-runtime-1")
        self.created.append(created)
        return created

    def execute(
        self,
        *,
        created: InspectorBackendCreatedV1,
        attempt: AttemptBindingV1,
        manifest: InspectorExecutionManifestV1,
        runtime_parent: RuntimeParentReceiptV1,
        output_staging: object | None,
        request: InspectorLaunchRequestV1,
        sealed_input: InspectorSealedInputPort,
        limits: InspectorEffectiveLimitsV1,
        configuration: FixedContainerConfigurationV1,
        deadline_monotonic: float,
        is_cancelled: Callable[[], bool],
        monitor_termination: Callable[[str], float],
    ) -> InspectorBackendCompletedV1:
        del attempt, manifest, runtime_parent, output_staging, request, monitor_termination
        assert is_cancelled() is False
        assert created in self.created
        assert isinstance(sealed_input, _InputSealed)
        bind = sealed_input.prepare_read_only_bind(deadline_monotonic=deadline_monotonic)
        assert bind.target_path == "/input/artifact.tif"
        self.calls.append((sealed_input.payload, limits))
        self.configurations.append(configuration)
        if isinstance(self.completed, Exception):
            raise self.completed
        return self.completed.model_copy(update={"runtime_id": "synthetic-runtime-1"})


def _backend_result(request: InspectorLaunchRequestV1) -> InspectorBackendCompletedV1:
    return InspectorBackendCompletedV1(
        inspector_build_digest=request.policy.parser_build_digest,
        outcome=ArtifactInspectionOutcomeV1(
            artifact_id=request.sealed_byte_binding.artifact_id,
            observed_sha256=request.sealed_byte_binding.observed_sha256,
            outcome=ArtifactOutcome.REJECTED,
            reason="SYNTHETIC_REJECTED",
        ),
        output=DeadlineBoundedBytesReader(BytesIO()),
        output_size_bytes=0,
        output_sha256=None,
        runtime_measurement=_runtime_measurement(),
    )


def _runtime_measurement(*, runtime_id: str = "synthetic-runtime-1") -> FixedRuntimeMeasurementV1:
    return FixedRuntimeMeasurementV1(
        runtime_id=runtime_id,
        counter_unit=CpuCounterUnitV1.CPU_USEC,
        baseline_counter=500,
        final_counter=500,
        consumed_counter=0,
        budget_counter=2_000_000,
        threshold_exceeded=False,
        disposition=RuntimeControlDispositionV1.COMPLETED,
        kill_latency_seconds=None,
    )


def _launcher(
    request: InspectorLaunchRequestV1,
    *,
    catalog: _Catalog | None = None,
    verifier: _Verifier | None = None,
    profile: _Profile | None = None,
    accounting: _Accounting | None = None,
    staging: _Staging | None = None,
    input_staging: _InputStaging | None = None,
    reader_mapping: _ReaderMapping | None = None,
    attempts: _Attempts | None = None,
    attempt_recovery: _AttemptRecovery | None = None,
    runtime_parent: _RuntimeParent | None = None,
    runtime_cleanup: _RuntimeCleanup | None = None,
    backend: _Backend | None = None,
    worker_uid: int = _WORKER_UID,
    protocol_limits: ProtocolLimitsV1 | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> ExternalInspectorLauncher:
    actual_catalog = catalog or _Catalog(_manifest())
    actual_accounting = accounting or _Accounting()
    actual_staging = staging or _Staging()
    actual_input_staging = input_staging or _InputStaging()
    actual_backend = backend or _Backend(_backend_result(request))
    return ExternalInspectorLauncher(
        required_worker_uid=worker_uid,
        catalog=actual_catalog,
        verifier=verifier or _Verifier(SignatureVerificationVerdict.VALID),
        operation_profile=profile or _Profile(),
        accounting=actual_accounting,
        staging=actual_staging,
        input_staging=actual_input_staging,
        reader_mapping=reader_mapping or _ReaderMapping(),
        attempt_journal=attempts or _Attempts(),
        attempt_recovery=attempt_recovery or _AttemptRecovery(),
        runtime_parent=runtime_parent or _RuntimeParent(),
        runtime_cleanup=runtime_cleanup or _RuntimeCleanup(),
        backend=actual_backend,
        protocol_limits=protocol_limits or _limits(),
        systemd_base_slice="ksi-inspector.slice",
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
    input_staging = _InputStaging()
    backend = _Backend(_backend_result(request))
    launcher_runtime_cleanup = _RuntimeCleanup()
    launcher = _launcher(
        request,
        accounting=accounting,
        staging=staging,
        input_staging=input_staging,
        backend=backend,
        runtime_cleanup=launcher_runtime_cleanup,
    )

    accepted, terminal = _run_handler(launcher, request, payload)

    assert accepted.result == "ACCEPTED"
    terminal.validate_for(request)
    assert backend.calls == [(payload, backend.calls[0][1])]
    assert accounting.calls == [(1, 1, len(payload))]
    assert all(reservation.released for reservation in accounting.reservations)
    assert input_staging.mutable[0].maximum == len(payload)
    assert input_staging.sealed[0].prepared is True
    assert input_staging.sealed[0].aborted is True
    assert staging.staged == []
    configuration = backend.configurations[0]
    assert configuration.runtime_uid == 10_001
    assert configuration.runtime_gid == 10_001
    assert configuration.input_mount.target_path == "/input/artifact.tif"
    assert configuration.input_mount.read_only is True
    assert configuration.extra_mounts == ()
    assert configuration.socket_mounts == ()
    assert launcher_runtime_cleanup.runtime_ids == ["synthetic-runtime-1"]


def test_launcher_durably_binds_the_exact_runtime_before_execute() -> None:
    """A create-before-ID crash is recoverable because execution starts only after binding."""

    class _OrderingBackend(_Backend):
        def __init__(self, attempts: _Attempts, completed: InspectorBackendCompletedV1) -> None:
            super().__init__(completed)
            self._attempts = attempts
            self.events_at_create: list[str] | None = None
            self.events_at_execute: list[str] | None = None

        def create(self, **kwargs: object) -> InspectorBackendCreatedV1:
            self.events_at_create = list(self._attempts.events)
            return super().create(**kwargs)  # type: ignore[arg-type]

        def execute(self, **kwargs: object) -> InspectorBackendCompletedV1:
            self.events_at_execute = list(self._attempts.events)
            return super().execute(**kwargs)  # type: ignore[arg-type]

    payload = b"bound-input"
    request = _request(_policy(), payload)
    attempts = _Attempts()
    backend = _OrderingBackend(attempts, _backend_result(request))
    launcher = _launcher(request, attempts=attempts, backend=backend)

    accepted, terminal = _run_handler(launcher, request, payload)

    assert accepted.result == "ACCEPTED"
    terminal.validate_for(request)
    assert backend.events_at_create == [
        "INTENDED",
        "STAGING_ALLOCATED",
        "INPUT_BOUND",
        "RUNTIME_PARENT_CREATING",
        "RUNTIME_PARENT_BOUND",
        "CONTAINER_CREATING",
    ]
    assert backend.events_at_execute == [
        "INTENDED",
        "STAGING_ALLOCATED",
        "INPUT_BOUND",
        "RUNTIME_PARENT_CREATING",
        "RUNTIME_PARENT_BOUND",
        "CONTAINER_CREATING",
        "CONTAINER_BOUND",
    ]


def test_launcher_records_created_runtime_before_a_post_create_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A late cancellation cannot discard a returned Engine identity before recovery owns it."""
    payload = b"bound-input"
    request = _request(_policy(), payload)
    attempts = _Attempts()
    cleanup = _RuntimeCleanup()
    cancelled = iter((False, True))
    monkeypatch.setattr(
        "ksi_processing_controller.external_inspector_launcher._SocketCancellation.is_cancelled",
        lambda _self: next(cancelled),
    )
    launcher = _launcher(
        request,
        attempts=attempts,
        runtime_cleanup=cleanup,
        backend=_Backend(_backend_result(request)),
    )

    accepted, terminal = _run_handler(launcher, request, payload)

    assert accepted.result == "ACCEPTED"
    assert terminal.result == "FAILED"
    assert attempts.events == [
        "INTENDED",
        "STAGING_ALLOCATED",
        "INPUT_BOUND",
        "RUNTIME_PARENT_CREATING",
        "RUNTIME_PARENT_BOUND",
        "CONTAINER_CREATING",
        "CONTAINER_BOUND",
        "CLEANUP_REQUIRED",
        "CLEANED",
    ]
    assert cleanup.runtime_ids == ["synthetic-runtime-1"]


def test_launcher_runs_durable_recovery_before_accepting_any_connection() -> None:
    """A startup uncertainty closes the launcher before an authenticated worker can stream bytes."""
    request = _request(_policy())
    recovery = _AttemptRecovery()

    _launcher(request, attempt_recovery=recovery)

    assert recovery.calls == 1
    with pytest.raises(InspectorSandboxUnavailable, match="recovery"):
        _launcher(request, attempt_recovery=_AttemptRecovery(unavailable=True))


def test_launcher_holds_a_completed_result_until_registered_cleanup_is_durable() -> None:
    """A backend result cannot cross the socket before its exact staging receipt reaches CLEANED."""
    payload = b"bound-input"
    request = _request(_policy(), payload)
    attempts = _Attempts()
    input_staging = _InputStaging()
    launcher = _launcher(
        request,
        attempts=attempts,
        input_staging=input_staging,
        backend=_Backend(_backend_result(request)),
    )

    accepted, terminal = _run_handler(launcher, request, payload)

    assert accepted.result == "ACCEPTED"
    terminal.validate_for(request)
    assert attempts.events == [
        "INTENDED",
        "STAGING_ALLOCATED",
        "INPUT_BOUND",
        "RUNTIME_PARENT_CREATING",
        "RUNTIME_PARENT_BOUND",
        "CONTAINER_CREATING",
        "CONTAINER_BOUND",
        "CLEANUP_REQUIRED",
        "CLEANED",
    ]
    assert len(input_staging.finalized) == 1


def test_launcher_records_one_cleanup_failure_without_restarting_cleanup() -> None:
    """A failed exact cleanup records recovery evidence without duplicating its request."""

    class _CleanupFailureInputStaging(_InputStaging):
        def finalize_registered_cleanup(
            self,
            *,
            plan: StagingAllocationPlanV1,
            receipt: StagingAllocationReceiptV1,
        ) -> None:
            super().finalize_registered_cleanup(plan=plan, receipt=receipt)
            raise RuntimeError("synthetic finalizer failure")

    payload = b"bound-input"
    request = _request(_policy(), payload)
    attempts = _Attempts()
    launcher = _launcher(
        request,
        attempts=attempts,
        input_staging=_CleanupFailureInputStaging(),
        backend=_Backend(_backend_result(request)),
    )

    accepted, terminal = _run_handler(launcher, request, payload)

    assert accepted.result == "ACCEPTED"
    assert terminal.result == "FAILED"
    assert attempts.events == [
        "INTENDED",
        "STAGING_ALLOCATED",
        "INPUT_BOUND",
        "RUNTIME_PARENT_CREATING",
        "RUNTIME_PARENT_BOUND",
        "CONTAINER_CREATING",
        "CONTAINER_BOUND",
        "CLEANUP_REQUIRED",
        "CLEANUP_FAILED",
    ]


def test_launcher_closes_admission_when_exact_runtime_removal_fails() -> None:
    """A known runtime ID cannot be replaced with a broad cleanup after its exact removal fails."""
    payload = b"bound-input"
    request = _request(_policy(), payload)
    attempts = _Attempts()
    runtime_cleanup = _RuntimeCleanup(removed=False)
    input_staging = _InputStaging()
    launcher = _launcher(
        request,
        attempts=attempts,
        runtime_cleanup=runtime_cleanup,
        input_staging=input_staging,
        backend=_Backend(_backend_result(request)),
    )

    accepted, terminal = _run_handler(launcher, request, payload)

    assert accepted.result == "ACCEPTED"
    assert terminal.result == "FAILED"
    assert runtime_cleanup.runtime_ids == ["synthetic-runtime-1"]
    assert len(input_staging.sealed) == 1
    assert input_staging.sealed[0].relinquished is True
    assert input_staging.sealed[0].aborted is False
    assert attempts.events == [
        "INTENDED",
        "STAGING_ALLOCATED",
        "INPUT_BOUND",
        "RUNTIME_PARENT_CREATING",
        "RUNTIME_PARENT_BOUND",
        "CONTAINER_CREATING",
        "CONTAINER_BOUND",
        "CLEANUP_REQUIRED",
        "CLEANUP_FAILED",
    ]
    assert launcher._is_admission_closed() is True  # noqa: SLF001 - health boundary

    rejected_client, rejected_server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        rejected_thread = threading.Thread(
            target=lambda: launcher.handle_connection(rejected_server)
        )
        rejected_thread.start()
        rejected_thread.join(timeout=2)
        assert not rejected_thread.is_alive()
        with pytest.raises(BrokenPipeError):
            write_launch_request(rejected_client, request, BytesIO(payload), _limits())
    finally:
        rejected_client.close()
        rejected_server.close()


def test_launcher_retains_parent_creation_ambiguity_before_staging_cleanup() -> None:
    """A thrown parent create never treats an absent post-failure observation as no effect."""

    class _ParentCreateAmbiguous(_RuntimeParent):
        def bind_before_create(self, **kwargs: object) -> RuntimeParentReceiptV1:
            del kwargs
            raise RuntimeError("StartTransientUnit may have created the slice")

        def adopt_if_prebound(self, *, binding: AttemptBindingV1) -> None:
            del binding
            return None

    payload = b"bound-input"
    request = _request(_policy(), payload)
    attempts = _Attempts()
    staging = _InputStaging()
    launcher = _launcher(
        request,
        attempts=attempts,
        input_staging=staging,
        runtime_parent=_ParentCreateAmbiguous(),
    )

    accepted, terminal = _run_handler(launcher, request, payload)

    assert accepted.result == "ACCEPTED"
    assert terminal.result == "FAILED"
    assert attempts.events == [
        "INTENDED",
        "STAGING_ALLOCATED",
        "INPUT_BOUND",
        "RUNTIME_PARENT_CREATING",
        "CLEANUP_REQUIRED",
        "CLEANUP_FAILED",
    ]
    assert staging.sealed[0].relinquished is True
    assert staging.sealed[0].aborted is False
    assert launcher._is_admission_closed() is True  # noqa: SLF001 - health boundary


def test_launcher_retains_container_creation_ambiguity_before_staging_cleanup() -> None:
    """An Engine exception before ID cannot retire the attempt unless exact recovery resolves it."""

    class _CreateAmbiguous(_Backend):
        def create(self, **kwargs: object) -> InspectorBackendCreatedV1:
            del kwargs
            raise RuntimeError("Engine create may have completed before inspect failed")

    class _UnresolvedCleanup(_RuntimeCleanup):
        def resolve_exact(self, binding: AttemptBindingV1) -> None:
            del binding
            return None

    payload = b"bound-input"
    request = _request(_policy(), payload)
    attempts = _Attempts()
    staging = _InputStaging()
    launcher = _launcher(
        request,
        attempts=attempts,
        input_staging=staging,
        backend=_CreateAmbiguous(_backend_result(request)),
        runtime_cleanup=_UnresolvedCleanup(),
    )

    accepted, terminal = _run_handler(launcher, request, payload)

    assert accepted.result == "ACCEPTED"
    assert terminal.result == "FAILED"
    assert attempts.events == [
        "INTENDED",
        "STAGING_ALLOCATED",
        "INPUT_BOUND",
        "RUNTIME_PARENT_CREATING",
        "RUNTIME_PARENT_BOUND",
        "CONTAINER_CREATING",
        "CLEANUP_REQUIRED",
        "CLEANUP_FAILED",
    ]
    assert staging.sealed[0].relinquished is True
    assert staging.sealed[0].aborted is False
    assert launcher._is_admission_closed() is True  # noqa: SLF001 - health boundary


def test_launcher_proves_parent_before_first_runtime_cleanup_mutation() -> None:
    """A replaced parent blocks kill/wait after CLEANUP_REQUIRED is durably appended."""

    class _RejectedParent(_RuntimeParent):
        def verify_before_quiesce(self, **kwargs: object) -> bool:
            del kwargs
            return False

    class _NoMutationCleanup(_RuntimeCleanup):
        def __init__(self) -> None:
            super().__init__()
            self.quiesce_calls = 0

        def quiesce_exact(self, **kwargs: object) -> bool:
            del kwargs
            self.quiesce_calls += 1
            return True

    payload = b"bound-input"
    request = _request(_policy(), payload)
    attempts = _Attempts()
    cleanup = _NoMutationCleanup()
    launcher = _launcher(
        request,
        attempts=attempts,
        runtime_parent=_RejectedParent(),
        runtime_cleanup=cleanup,
        backend=_Backend(_backend_result(request)),
    )

    accepted, terminal = _run_handler(launcher, request, payload)

    assert accepted.result == "ACCEPTED"
    assert terminal.result == "FAILED"
    assert cleanup.quiesce_calls == 0
    assert attempts.events[-2:] == ["CLEANUP_REQUIRED", "CLEANUP_FAILED"]
    assert launcher._is_admission_closed() is True  # noqa: SLF001 - health boundary


def test_launcher_rejects_success_when_final_parent_cpu_proof_is_over_budget() -> None:
    """A late aggregate overrun cannot publish the earlier backend-completed report."""

    class _OverBudgetParent(_RuntimeParent):
        def verify_final_before_remove(self, **kwargs: object) -> bool:
            del kwargs
            return False

    payload = b"bound-input"
    request = _request(_policy(), payload)
    attempts = _Attempts()
    cleanup = _RuntimeCleanup()
    launcher = _launcher(
        request,
        attempts=attempts,
        runtime_parent=_OverBudgetParent(),
        runtime_cleanup=cleanup,
        backend=_Backend(_backend_result(request)),
    )

    accepted, terminal = _run_handler(launcher, request, payload)

    assert accepted.result == "ACCEPTED"
    assert terminal.result == "FAILED"
    assert cleanup.runtime_ids == []
    assert attempts.events[-2:] == ["CLEANUP_REQUIRED", "CLEANUP_FAILED"]
    assert launcher._is_admission_closed() is True  # noqa: SLF001 - health boundary


def test_launcher_closes_admission_when_recording_cleanup_failure_raises() -> None:
    """An uncertain cleanup remains admission-fatal even if its failure event cannot append."""

    class _FailureEventAttempts(_Attempts):
        def cleanup_failed(self, attempt_nonce: str, *, reason: str) -> None:
            super().cleanup_failed(attempt_nonce, reason=reason)
            raise RuntimeError("synthetic failure event append error")

    payload = b"bound-input"
    request = _request(_policy(), payload)
    launcher = _launcher(
        request,
        attempts=_FailureEventAttempts(),
        runtime_cleanup=_RuntimeCleanup(removed=False),
        backend=_Backend(_backend_result(request)),
    )

    accepted, terminal = _run_handler(launcher, request, payload)

    assert accepted.result == "ACCEPTED"
    assert terminal.result == "FAILED"
    assert launcher._is_admission_closed() is True  # noqa: SLF001 - health boundary


def test_launcher_requires_a_typed_current_mapping_before_it_receives_input_bytes() -> None:
    """A signed UID without a verified host mapping cannot be treated as a usable reader."""

    class _UnavailableMapping:
        def resolve_exact(
            self,
            *,
            runtime_uid: int,
            runtime_gid: int,
            supplementary_groups: tuple[int, ...],
            deadline_monotonic: float,
        ) -> None:
            del runtime_uid, runtime_gid, supplementary_groups, deadline_monotonic
            return None

    payload = b"bound-input"
    request = _request(_policy(), payload)
    input_staging = _InputStaging()
    backend = _Backend(_backend_result(request))
    launcher = _launcher(
        request,
        input_staging=input_staging,
        reader_mapping=_UnavailableMapping(),  # type: ignore[arg-type]
        backend=backend,
    )
    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        thread = threading.Thread(target=lambda: launcher.handle_connection(server))
        thread.start()
        write_launch_request(client, request, BytesIO(payload), _limits())
        assert read_launch_result(client, _limits()).result == "FAILED"
        thread.join(timeout=2)
        assert not thread.is_alive()
    finally:
        client.close()
        server.close()
    assert input_staging.mutable == []
    assert backend.calls == []


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
        max_cpu_seconds=2.0,
    )


def test_admission_requires_policy_grammar_to_match_signed_backend_profile() -> None:
    """A signed parser image cannot be used for a different positive grammar."""
    manifest = _manifest(backend_profile_digest=_digest("5"))
    request = _request(_policy(manifest))
    launcher = _launcher(request, catalog=_Catalog(manifest))

    with pytest.raises(InspectorSandboxUnavailable, match="grammar"):
        launcher.admit(request, ProcessingArtifactKind.ORTHO, "image/tiff")


def test_admission_rejects_an_unknown_grammar_even_when_policy_and_manifest_match() -> None:
    """The approved v1 parser cannot admit a mutually agreed but unimplemented grammar."""
    unknown_profile = _digest("5")
    manifest = _manifest(backend_profile_digest=unknown_profile)
    request = _request(_policy(manifest, grammar_digest=unknown_profile))
    launcher = _launcher(request, catalog=_Catalog(manifest))

    with pytest.raises(InspectorSandboxUnavailable, match="profile"):
        launcher.admit(request, ProcessingArtifactKind.ORTHO, "image/tiff")


def test_reservation_and_staging_are_released_when_backend_fails() -> None:
    """A terminal backend error must not leak aggregate concurrency or spool capacity."""
    payload = b"bound-input"
    request = _request(_policy(), payload)
    accounting = _Accounting()
    staging = _Staging()
    input_staging = _InputStaging()
    backend = _Backend(RuntimeError("synthetic backend error"))
    launcher = _launcher(
        request,
        accounting=accounting,
        staging=staging,
        input_staging=input_staging,
        backend=backend,
    )
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
    assert staging.staged == []
    assert input_staging.sealed[0].aborted is True


def test_sanitize_reserves_and_releases_bounded_output_spool_before_writing_raw_bytes() -> None:
    """Derivative bytes need their own aggregate spool reservation and terminal cleanup."""
    payload = b"bound-input"
    sanitized = b"sanitized-output"
    request = _request(_policy(), payload, operation=InspectorOperation.SANITIZE)
    accounting = _Accounting()
    staging = _Staging()
    input_staging = _InputStaging()
    backend = _Backend(
        InspectorBackendCompletedV1(
            inspector_build_digest=request.policy.parser_build_digest,
            outcome="SANITIZED",
            output=DeadlineBoundedBytesReader(BytesIO(sanitized)),
            output_size_bytes=len(sanitized),
            output_sha256=_bytes_digest(sanitized),
            runtime_measurement=_runtime_measurement(),
        )
    )
    launcher = _launcher(
        request,
        accounting=accounting,
        staging=staging,
        input_staging=input_staging,
        backend=backend,
    )
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
    assert accounting.calls == [(1, 1, len(payload)), (0, 0, 32)]
    assert all(item.released for item in accounting.reservations)
    assert [item.aborted for item in staging.staged] == [True]
    assert input_staging.sealed[0].aborted is True


def test_output_close_failure_latches_launcher_admission_after_cleaned_response() -> None:
    """A response-owned spool close error never retries its FD or rewrites CLEANED."""

    class _CloseFailingStaged(_Staged):
        def __init__(self, buffer: BytesIO, max_bytes: int) -> None:
            super().__init__(buffer, max_bytes)
            self.abort_calls = 0

        def abort(self) -> None:
            self.abort_calls += 1
            raise OSError("synthetic close failure")

    class _CloseFailingStaging:
        def __init__(self) -> None:
            self.staged: list[_CloseFailingStaged] = []

        def begin(self, *, maximum_bytes: int, deadline_monotonic: float) -> _CloseFailingStaged:
            del deadline_monotonic
            staged = _CloseFailingStaged(BytesIO(), maximum_bytes)
            self.staged.append(staged)
            return staged

    payload = b"bound-input"
    sanitized = b"sanitized-output"
    request = _request(_policy(), payload, operation=InspectorOperation.SANITIZE)
    staging = _CloseFailingStaging()
    attempts = _Attempts()
    backend = _Backend(
        InspectorBackendCompletedV1(
            inspector_build_digest=request.policy.parser_build_digest,
            outcome="SANITIZED",
            output=DeadlineBoundedBytesReader(BytesIO(sanitized)),
            output_size_bytes=len(sanitized),
            output_sha256=_bytes_digest(sanitized),
            runtime_measurement=_runtime_measurement(),
        )
    )
    launcher = _launcher(
        request,
        staging=cast(_Staging, staging),
        attempts=attempts,
        backend=backend,
    )
    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        thread = threading.Thread(target=lambda: launcher.handle_connection(server))
        thread.start()
        write_launch_request(client, request, BytesIO(payload), _limits())
        assert read_launch_result(client, _limits()).result == "ACCEPTED"
        assert read_launch_result(client, _limits()).result == "COMPLETED"
        assert client.recv(len(sanitized)) == sanitized
        assert client.recv(1) == b""
        thread.join(timeout=2)
        assert not thread.is_alive()
    finally:
        client.close()
        server.close()

    assert staging.staged[0].abort_calls == 1
    assert attempts.events[-1] == "CLEANED"

    rejected_client, rejected_server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        rejected_thread = threading.Thread(
            target=lambda: launcher.handle_connection(rejected_server)
        )
        rejected_thread.start()
        rejected_thread.join(timeout=2)
        assert not rejected_thread.is_alive()
        with pytest.raises(BrokenPipeError):
            write_launch_request(rejected_client, request, BytesIO(payload), _limits())
        assert rejected_client.recv(1) == b""
    finally:
        rejected_client.close()
        rejected_server.close()
    assert staging.staged[0].abort_calls == 1
    assert len(staging.staged) == 1
    assert attempts.events.count("CLEANED") == 1


def test_sanitize_terminal_does_not_allocate_after_the_output_is_sealed() -> None:
    """Only the pre-EXECUTE full-cap reservation can own derivative response bytes."""

    class _Clock:
        def __init__(self) -> None:
            self.now = 100.0

        def __call__(self) -> float:
            return self.now

    payload = b"bound-input"
    sanitized = b"sanitized-output"
    request = _request(_policy(), payload, operation=InspectorOperation.SANITIZE)
    clock = _Clock()
    accounting = _Accounting()
    staging = _Staging()
    launcher = _launcher(request, accounting=accounting, staging=staging)
    completed = InspectorBackendCompletedV1(
        inspector_build_digest=request.policy.parser_build_digest,
        outcome="SANITIZED",
        output=DeadlineBoundedBytesReader(BytesIO(sanitized)),
        output_size_bytes=len(sanitized),
        output_sha256=_bytes_digest(sanitized),
        runtime_measurement=_runtime_measurement(),
    )
    staged = staging.begin(maximum_bytes=32, deadline_monotonic=100.02)
    staged.write(sanitized)
    staged.finish()
    deadline = ProtocolDeadline(20, clock)
    clock.now = 100.03

    with pytest.raises(ProtocolDeadlineExceeded, match="global wire deadline"):
        launcher._write_completed_result(  # noqa: SLF001 - direct handoff boundary
            object(),  # type: ignore[arg-type]
            request,
            completed,
            launcher.admit(request, ProcessingArtifactKind.ORTHO, "image/tiff").effective_limits,
            deadline,
            staged_output=staged,
        )

    assert accounting.calls == []


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
            created: InspectorBackendCreatedV1,
            attempt: AttemptBindingV1,
            manifest: InspectorExecutionManifestV1,
            runtime_parent: RuntimeParentReceiptV1,
            output_staging: object | None,
            request: InspectorLaunchRequestV1,
            sealed_input: InspectorSealedInputPort,
            limits: InspectorEffectiveLimitsV1,
            configuration: FixedContainerConfigurationV1,
            deadline_monotonic: float,
            is_cancelled: Callable[[], bool],
            monitor_termination: Callable[[str], float],
        ) -> InspectorBackendCompletedV1:
            del (
                created,
                attempt,
                manifest,
                runtime_parent,
                output_staging,
                request,
                sealed_input,
                limits,
                configuration,
                deadline_monotonic,
                monitor_termination,
            )
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
            DeadlineBoundedDiscardingSink(),
            monotonic=lambda: next(ticks),
        )


def test_upload_rejects_an_unbounded_reader_before_it_can_outlive_the_deadline() -> None:
    """A legacy synchronous read cannot retain the launch thread past its deadline."""

    class _BlockingReader:
        def __init__(self) -> None:
            self.read_calls = 0

        def read(self, maximum: int = -1) -> bytes:
            del maximum
            self.read_calls += 1
            time.sleep(0.150)
            return b"bound-input"

    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    source = _BlockingReader()
    started = time.monotonic()
    try:
        with pytest.raises(ProtocolViolation, match="deadline-bounded"):
            write_launch_request(
                client,
                _request(_policy(), b"bound-input"),
                cast(DeadlineBoundedByteReaderPort, source),
                _limits(),
                deadline=ProtocolDeadline(20, time.monotonic),
                wait_is_current=lambda: True,
                heartbeat_interval_millis=5,
            )
    finally:
        client.close()
        server.close()

    assert source.read_calls == 0
    assert time.monotonic() - started < 0.100


def test_deadline_bounded_socket_reader_polls_authority_while_peer_stalls() -> None:
    """A real non-reading peer leaves no thread blocked beyond the absolute deadline."""
    import ksi_processing_controller.external_inspector_protocol as protocol

    reader_type = getattr(protocol, "DeadlineBoundedSocketReader", None)
    assert reader_type is not None, "deadline-bounded socket reader is required"

    upload, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    source_socket, stalled_peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    reader = reader_type(source_socket)
    authority_checks = 0

    def authority_is_current() -> bool:
        nonlocal authority_checks
        authority_checks += 1
        return True

    started = time.monotonic()
    try:
        with pytest.raises(ProtocolDeadlineExceeded, match="global wire deadline"):
            write_launch_request(
                upload,
                _request(_policy(), b"bound-input"),
                reader,
                _limits(),
                deadline=ProtocolDeadline(20, time.monotonic),
                wait_is_current=authority_is_current,
                heartbeat_interval_millis=5,
            )
    finally:
        reader.close()
        upload.close()
        server.close()
        stalled_peer.close()

    assert authority_checks >= 3
    assert time.monotonic() - started < 0.100


def test_deadline_bounded_socket_reader_cancels_stalled_read_at_heartbeat_cadence() -> None:
    """Authority loss is observed while the real socket remains silent."""
    import ksi_processing_controller.external_inspector_protocol as protocol

    reader_type = getattr(protocol, "DeadlineBoundedSocketReader", None)
    assert reader_type is not None, "deadline-bounded socket reader is required"

    upload, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    source_socket, stalled_peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    reader = reader_type(source_socket)
    authority_checks = 0

    def authority_is_current() -> bool:
        nonlocal authority_checks
        authority_checks += 1
        return authority_checks < 4

    started = time.monotonic()
    try:
        with pytest.raises(ProtocolViolation, match="authority lost"):
            write_launch_request(
                upload,
                _request(_policy(), b"bound-input"),
                reader,
                _limits(),
                deadline=ProtocolDeadline(250, time.monotonic),
                wait_is_current=authority_is_current,
                heartbeat_interval_millis=5,
            )
    finally:
        reader.close()
        upload.close()
        server.close()
        stalled_peer.close()

    assert authority_checks >= 4
    assert time.monotonic() - started < 0.100


def test_deadline_bounded_socket_sink_cancels_when_peer_does_not_drain() -> None:
    """A real full socket buffer cannot retain raw-input staging past the deadline."""
    import ksi_processing_controller.external_inspector_protocol as protocol

    sink_type = getattr(protocol, "DeadlineBoundedSocketSink", None)
    assert sink_type is not None, "deadline-bounded socket sink is required"

    payload = b"x" * 65_536
    binding = SealedByteBindingV1(
        artifact_id="ortho",
        observed_sha256=_bytes_digest(payload),
        observed_size_bytes=len(payload),
    )
    limits = ProtocolLimitsV1(
        max_header_bytes=128,
        max_chunk_bytes=1_024,
        max_input_bytes=len(payload),
        max_output_bytes=1,
        max_wire_duration_millis=250,
    )
    sender, receiver = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    sink_socket, stalled_peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    sink_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1_024)
    sink = sink_type(sink_socket)
    sender.sendall(payload)
    sender.shutdown(socket.SHUT_WR)
    authority_checks = 0

    def authority_is_current() -> bool:
        nonlocal authority_checks
        authority_checks += 1
        return True

    started = time.monotonic()
    try:
        with pytest.raises(ProtocolDeadlineExceeded, match="global wire deadline"):
            read_bound_bytes(
                receiver,
                binding,
                limits,
                sink,
                deadline=ProtocolDeadline(20, time.monotonic),
                wait_is_current=authority_is_current,
                heartbeat_interval_millis=5,
            )
    finally:
        sink.close()
        sender.close()
        receiver.close()
        stalled_peer.close()

    assert authority_checks >= 3
    assert time.monotonic() - started < 0.100


def test_deadline_bounded_socket_sink_cancels_stalled_write_at_heartbeat_cadence() -> None:
    """Authority loss stops a real full sink buffer without waiting for peer drain."""
    import ksi_processing_controller.external_inspector_protocol as protocol

    sink_type = getattr(protocol, "DeadlineBoundedSocketSink", None)
    assert sink_type is not None, "deadline-bounded socket sink is required"

    payload = b"x" * 65_536
    binding = SealedByteBindingV1(
        artifact_id="ortho",
        observed_sha256=_bytes_digest(payload),
        observed_size_bytes=len(payload),
    )
    limits = ProtocolLimitsV1(
        max_header_bytes=128,
        max_chunk_bytes=1_024,
        max_input_bytes=len(payload),
        max_output_bytes=1,
        max_wire_duration_millis=250,
    )
    sender, receiver = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    sink_socket, stalled_peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    sink_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1_024)
    sink = sink_type(sink_socket)
    sender.sendall(payload)
    sender.shutdown(socket.SHUT_WR)
    authority_checks = 0

    def authority_is_current() -> bool:
        nonlocal authority_checks
        authority_checks += 1
        return authority_checks < 10

    started = time.monotonic()
    try:
        with pytest.raises(ProtocolViolation, match="authority lost"):
            read_bound_bytes(
                receiver,
                binding,
                limits,
                sink,
                deadline=ProtocolDeadline(250, time.monotonic),
                wait_is_current=authority_is_current,
                heartbeat_interval_millis=5,
            )
    finally:
        sink.close()
        sender.close()
        receiver.close()
        stalled_peer.close()

    assert authority_checks >= 10
    assert time.monotonic() - started < 0.100


def test_inner_prepare_mount_and_execute_frames_are_canonical_and_closed() -> None:
    """The Docker entrypoint receives only admitted immutable authority and sealed bytes."""
    from ksi_processing_controller.external_inspector_container_protocol import (
        ContainerInnerFrameLimitsV1,
        ContainerInnerProtocolViolation,
        build_execute_frame,
        build_prepare_frame,
        decode_inner_frame,
        encode_inner_frame,
        validate_mount_verified_frame,
        validate_prepare_frame,
    )

    manifest = _manifest()
    policy = _policy(manifest)
    request = _request(policy)
    limits = ContainerInnerFrameLimitsV1(maximum_frame_bytes=32_768, maximum_stderr_bytes=512)
    prepare = build_prepare_frame(
        attempt_nonce=request.attempt_nonce,
        outer_canonical_input_digest=request.canonical_input_digest,
        operation=request.operation.value,
        sealed_byte_binding=request.sealed_byte_binding.model_dump(by_alias=True, mode="json"),
        policy=policy,
        manifest=manifest,
        admitted_backend_profile_digest=manifest.body.backend_profile_digest,
        admitted_security_profile_digest=manifest.body.security_profile_digest,
        admitted_inner_protocol_digest=manifest.body.inspector_protocol_digest,
    )

    encoded = encode_inner_frame(prepare, limits=limits)
    assert decode_inner_frame(encoded, limits=limits) == prepare
    validate_prepare_frame(prepare, expected=prepare, limits=limits)
    validate_mount_verified_frame(
        {
            "protocolVersion": "inspector-container.v1",
            "frame": "MOUNT_VERIFIED",
            "attemptNonce": request.attempt_nonce,
            "outerCanonicalInputDigest": request.canonical_input_digest,
            "prepareDigest": prepare["prepareDigest"],
            "artifactId": request.sealed_byte_binding.artifact_id,
            "actualSizeBytes": request.sealed_byte_binding.observed_size_bytes,
            "actualSha256": request.sealed_byte_binding.observed_sha256,
        },
        prepare=prepare,
        artifact_id=request.sealed_byte_binding.artifact_id,
        actual_size_bytes=request.sealed_byte_binding.observed_size_bytes,
        actual_sha256=request.sealed_byte_binding.observed_sha256,
    )
    assert build_execute_frame(prepare=prepare)["frame"] == "EXECUTE"

    altered = dict(prepare)
    altered["operation"] = "SANITIZE"
    with pytest.raises(ContainerInnerProtocolViolation, match="PREPARE"):
        validate_prepare_frame(altered, expected=prepare, limits=limits)
    with pytest.raises(ContainerInnerProtocolViolation, match="length"):
        decode_inner_frame(encoded + b"trailing", limits=limits)


@pytest.mark.parametrize("trigger", ["CPU_LIMIT_EXCEEDED", "DEADLINE_EXCEEDED", "CANCELLED"])
def test_launcher_monitor_callback_journals_proves_then_quiesces_once_before_failure(
    trigger: str,
) -> None:
    """The concrete monitor callback cannot kill a bound runtime outside launcher cleanup order."""

    order: list[str] = []

    class _OrderedAttempts(_Attempts):
        def cleanup_required(self, attempt_nonce: str, *, disposition: str) -> None:
            super().cleanup_required(attempt_nonce, disposition=disposition)
            order.append("journal")

    class _OrderedParent(_RuntimeParent):
        def verify_before_quiesce(self, **kwargs: object) -> bool:
            del kwargs
            order.append("parent-before")
            return True

        def verify_final_before_remove(self, **kwargs: object) -> bool:
            del kwargs
            order.append("parent-final")
            return True

    class _OrderedCleanup(_RuntimeCleanup):
        def quiesce_exact(self, **kwargs: object) -> bool:
            del kwargs
            order.append("kill-wait")
            return True

        def remove_exact(self, **kwargs: object) -> bool:
            del kwargs
            order.append("remove")
            return True

    class _MonitorBackend(_Backend):
        def __init__(self, completed: InspectorBackendCompletedV1) -> None:
            super().__init__(completed)
            self.monitor_entered = False

        def execute(
            self, *, monitor_termination: Callable[[str], float], **kwargs: object
        ) -> InspectorBackendCompletedV1:
            self.monitor_entered = True
            assert monitor_termination(trigger) >= 0.0
            raise InspectorSandboxUnavailable("synthetic monitor termination")

    payload = b"bound-input"
    request = _request(_policy(), payload)
    backend = _MonitorBackend(_backend_result(request))
    launcher = _launcher(
        request,
        attempts=_OrderedAttempts(),
        runtime_parent=_OrderedParent(),
        runtime_cleanup=_OrderedCleanup(),
        backend=backend,
    )

    accepted, terminal = _run_handler(launcher, request, payload)

    assert accepted.result == "ACCEPTED"
    assert terminal.result == "FAILED"
    assert backend.monitor_entered is True
    assert order == ["journal", "parent-before", "kill-wait", "parent-final", "remove"]


def test_monitor_and_fast_normal_completion_share_one_exact_cleanup_sequence() -> None:
    """A monitor callback racing normal completion cannot duplicate cleanup effects."""

    order: list[str] = []
    request = _request(_policy(), b"bound-input")
    launcher = _launcher(request)
    admission = launcher.admit(request, ProcessingArtifactKind.ORTHO, "image/tiff")
    attempt = launcher._new_attempt_binding(
        request,
        _manifest(),
        PrivateStagingRootV1(1, 2, 0o700, 1000, 1000),
        admission.effective_limits,
    )
    receipt = _RuntimeParent().bind_before_create(
        binding=attempt,
        configuration=cast(FixedContainerConfigurationV1, object()),
    )

    class _OrderedAttempts(_Attempts):
        def cleanup_required(self, attempt_nonce: str, *, disposition: str) -> None:
            super().cleanup_required(attempt_nonce, disposition=disposition)
            order.append("journal")

    class _OrderedParent(_RuntimeParent):
        def verify_before_quiesce(self, **kwargs: object) -> bool:
            del kwargs
            order.append("parent-before")
            return True

        def verify_final_before_remove(self, **kwargs: object) -> bool:
            del kwargs
            order.append("parent-final")
            return True

    class _OrderedCleanup(_RuntimeCleanup):
        def quiesce_exact(self, **kwargs: object) -> bool:
            del kwargs
            order.append("kill-wait")
            return True

        def remove_exact(self, **kwargs: object) -> bool:
            del kwargs
            order.append("remove")
            return True

    coordinator = _AttemptRuntimeCleanupCoordinator(
        journal=_OrderedAttempts(),
        runtime_parent=_OrderedParent(),
        runtime_cleanup=_OrderedCleanup(),
        latch_admission_closed=lambda: order.append("admission-off"),
        attempt=attempt,
        receipt=receipt,
        runtime_id="synthetic-runtime-1",
        cleanup_deadline_monotonic=time.monotonic() + 1.0,
    )
    barrier = threading.Barrier(3)
    failures: list[BaseException] = []

    def monitor() -> None:
        try:
            barrier.wait(timeout=1.0)
            coordinator.terminate_from_monitor("CPU_LIMIT_EXCEEDED")
        except BaseException as exc:  # pragma: no cover - asserted after joining
            failures.append(exc)

    def normal_completion() -> None:
        try:
            barrier.wait(timeout=1.0)
            coordinator.quiesce_and_remove(disposition="BACKEND_COMPLETED")
        except BaseException as exc:  # pragma: no cover - asserted after joining
            failures.append(exc)

    monitor_thread = threading.Thread(target=monitor)
    normal_thread = threading.Thread(target=normal_completion)
    monitor_thread.start()
    normal_thread.start()
    barrier.wait(timeout=1.0)
    monitor_thread.join(timeout=1.0)
    normal_thread.join(timeout=1.0)

    assert not monitor_thread.is_alive()
    assert not normal_thread.is_alive()
    assert failures == []
    assert order == ["journal", "parent-before", "kill-wait", "parent-final", "remove"]
    assert coordinator.cleanup_complete is True
