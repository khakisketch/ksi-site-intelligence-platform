"""Admission-only local UDS launcher for a future external-inspector backend.

No listener, filesystem provisioning, Docker client, subprocess, parser, or
fallback backend lives here.  Every operational dependency is an injected port
and every unavailable dependency closes admission.
"""

from __future__ import annotations

import hashlib
import select
import socket
import struct
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, BinaryIO, Literal, Protocol

from ksi_event_contracts.external_artifact_validation import ArtifactInspectionOutcomeV1
from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionManifestV1,
    InspectorExecutionManifestVerifier,
    SignatureVerificationVerdict,
    validate_inspector_execution_binding,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from ksi_processing_controller.external_inspector_protocol import (
    InspectorFailureReason,
    InspectorLaunchRequestV1,
    InspectorLaunchResultV1,
    InspectorOperation,
    ProtocolDeadline,
    ProtocolDeadlineExceeded,
    ProtocolLimitsV1,
    ProtocolViolation,
    read_bound_bytes,
    read_launch_request_header,
    write_launch_result,
)


class InspectorSandboxUnavailable(RuntimeError):
    """A required local trust, profile, capacity, or backend port is unavailable."""


class _TerminalFrameEmitted(RuntimeError):
    """An I/O failure followed a terminal frame, so no second terminal frame is legal."""


class CatalogStartupStatusV1(BaseModel):
    """Provisioned catalog state; all three facts are mandatory and fail closed."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    readable: StrictBool
    trust_root_configured: StrictBool
    catalog_identity_verified: StrictBool

    @property
    def available(self) -> bool:
        return self.readable and self.trust_root_configured and self.catalog_identity_verified


class InspectorOperationProfileDecision(StrEnum):
    """Trusted worker profile answer; no MIME-only default exists."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    UNAVAILABLE = "UNAVAILABLE"


class InspectorEffectiveLimitsV1(BaseModel):
    """Intersection of an immutable policy envelope and signed hard ceilings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_input_bytes: StrictInt = Field(gt=0)
    max_memory_bytes: StrictInt = Field(gt=0)
    max_workspace_bytes: StrictInt = Field(gt=0)
    max_output_bytes: StrictInt = Field(gt=0)
    max_wall_time_millis: StrictInt = Field(gt=0)
    max_pids: StrictInt = Field(gt=0)
    cpu_period_micros: StrictInt = Field(gt=0)
    cpu_quota_micros: StrictInt = Field(gt=0)
    max_log_bytes: StrictInt = Field(gt=0)


class InspectorBackendCompletedV1(BaseModel):
    """Opaque backend output that must be rechecked before it crosses UDS."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    inspector_build_digest: str
    outcome: ArtifactInspectionOutcomeV1 | Literal["SANITIZED"]
    output: Any
    output_size_bytes: StrictInt = Field(ge=0)
    output_sha256: str | None = None

    @model_validator(mode="after")
    def _result_shape_is_staged_later(self) -> InspectorBackendCompletedV1:
        if not callable(getattr(self.output, "read", None)):
            raise ValueError("backend output must be a readable binary stream")
        return self


class InspectorManifestCatalogPort(Protocol):
    def startup_status(self) -> CatalogStartupStatusV1: ...

    def resolve_exact(
        self, *, parser_build_digest: str, resource_envelope_digest: str
    ) -> InspectorExecutionManifestV1 | None: ...

    def is_revoked(self, manifest: InspectorExecutionManifestV1) -> bool: ...


class InspectorOperationProfilePort(Protocol):
    """Worker-side trusted profile selection; it does not alter the UDS wire contract."""

    def allows(
        self,
        *,
        parser_build_digest: str,
        grammar_digest: str,
        artifact_kind: ProcessingArtifactKind,
        content_type: str,
        operation: InspectorOperation,
    ) -> InspectorOperationProfileDecision: ...


class InspectorAdmissionReservationPort(Protocol):
    def release(self) -> None: ...


class InspectorAdmissionAccountingPort(Protocol):
    """Reserves one request/worker and exact spool ownership before input reception."""

    def reserve(
        self,
        *,
        request_units: int,
        concurrency_units: int,
        spool_bytes: int,
        deadline_monotonic: float,
    ) -> InspectorAdmissionReservationPort | None: ...


class InspectorStagedBytesPort(Protocol):
    """Bounded staging handle; implementations may use only approved future Task 3 storage."""

    def write(self, chunk: bytes) -> None: ...

    def finish(self) -> None: ...

    def read(self, maximum: int = -1) -> bytes: ...

    def abort(self) -> None: ...


class InspectorStagingPort(Protocol):
    def begin(
        self, *, maximum_bytes: int, deadline_monotonic: float
    ) -> InspectorStagedBytesPort: ...


class InspectorBackendPort(Protocol):
    """A future backend receives only opaque staged bytes and fixed effective limits."""

    def execute(
        self,
        *,
        request: InspectorLaunchRequestV1,
        staged_input: InspectorStagedBytesPort,
        limits: InspectorEffectiveLimitsV1,
        deadline_monotonic: float,
        is_cancelled: Callable[[], bool],
    ) -> InspectorBackendCompletedV1: ...


@dataclass(frozen=True, slots=True)
class InspectorAdmissionV1:
    manifest: InspectorExecutionManifestV1
    effective_limits: InspectorEffectiveLimitsV1


class _SocketCancellation:
    """Cancellation is cooperative for ports and forceful only for the owned UDS socket."""

    def __init__(self, connection: socket.socket) -> None:
        self._connection = connection
        self._cancelled = threading.Event()
        self._stop_monitor = threading.Event()
        self._monitor: threading.Thread | None = None

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def cancel(self) -> None:
        if self._cancelled.is_set():
            return
        self._cancelled.set()
        with suppress(OSError):
            self._connection.close()

    def start_monitor(self, deadline: ProtocolDeadline) -> None:
        """Watch only full local peer loss or deadline, not the expected SHUT_WR EOF."""
        if self._monitor is not None:
            raise RuntimeError("UDS cancellation monitor already started")
        poller = select.poll()
        poller.register(
            self._connection.fileno(), select.POLLHUP | select.POLLERR | select.POLLNVAL
        )

        def monitor() -> None:
            while not self._stop_monitor.is_set():
                try:
                    timeout_millis = max(1, min(50, int(deadline.remaining() * 1_000)))
                except ProtocolDeadlineExceeded:
                    self.cancel()
                    return
                try:
                    events = poller.poll(timeout_millis)
                except OSError:
                    if not self._stop_monitor.is_set():
                        self.cancel()
                    return
                if events:
                    self.cancel()
                    return

        self._monitor = threading.Thread(
            target=monitor, name="external-inspector-uds-cancellation", daemon=True
        )
        self._monitor.start()

    def stop_monitor(self) -> None:
        self._stop_monitor.set()
        if self._monitor is not None:
            self._monitor.join(timeout=0.1)


class ExternalInspectorLauncher:
    """Pure connection handler; deployment is responsible for any UDS listener/identity."""

    def __init__(
        self,
        *,
        required_worker_uid: int,
        catalog: InspectorManifestCatalogPort,
        verifier: InspectorExecutionManifestVerifier,
        operation_profile: InspectorOperationProfilePort,
        accounting: InspectorAdmissionAccountingPort,
        staging: InspectorStagingPort,
        backend: InspectorBackendPort,
        protocol_limits: ProtocolLimitsV1,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(required_worker_uid) is not int or required_worker_uid < 0:
            raise ValueError("required_worker_uid must be a non-negative integer")
        self._required_worker_uid = required_worker_uid
        self._catalog = catalog
        self._verifier = verifier
        self._operation_profile = operation_profile
        self._accounting = accounting
        self._staging = staging
        self._backend = backend
        self._protocol_limits = protocol_limits
        self._monotonic = monotonic

    def admit(
        self,
        request: InspectorLaunchRequestV1,
        artifact_kind: ProcessingArtifactKind,
        content_type: str,
    ) -> InspectorAdmissionV1:
        """Validate catalog/trust/ceilings plus the worker's trusted operation profile.

        Kind/content-type are intentionally not UDS fields.  The authenticated
        worker applies this required profile before writing the fixed wire DTO;
        the launcher independently validates all representable request bindings.
        """
        deadline = ProtocolDeadline(self._protocol_limits.max_wire_duration_millis, self._monotonic)
        admission = self._admit_wire_request(request, deadline)
        if not isinstance(content_type, str) or not content_type.strip():
            raise ProtocolViolation("content type must be a non-empty trusted input projection")
        if request.operation is InspectorOperation.INSPECT:
            if artifact_kind not in {ProcessingArtifactKind.ORTHO, ProcessingArtifactKind.DSM}:
                raise ProtocolViolation("operation is not approved for artifact kind")
        elif artifact_kind is not ProcessingArtifactKind.ORTHO:
            raise ProtocolViolation("SANITIZE is approved only for ORTHO")
        deadline.remaining()
        try:
            decision = self._operation_profile.allows(
                parser_build_digest=request.policy.parser_build_digest,
                grammar_digest=request.policy.grammar_digest,
                artifact_kind=artifact_kind,
                content_type=content_type,
                operation=request.operation,
            )
        except Exception as exc:
            raise InspectorSandboxUnavailable("trusted operation profile is unavailable") from exc
        deadline.remaining()
        if decision is not InspectorOperationProfileDecision.ALLOW:
            raise InspectorSandboxUnavailable("trusted operation profile denied launch")
        return admission

    def _admit_wire_request(
        self, request: InspectorLaunchRequestV1, deadline: ProtocolDeadline
    ) -> InspectorAdmissionV1:
        deadline.remaining()
        try:
            status = self._catalog.startup_status()
        except Exception as exc:
            raise InspectorSandboxUnavailable(
                "manifest catalog startup status unavailable"
            ) from exc
        deadline.remaining()
        if not isinstance(status, CatalogStartupStatusV1) or not status.available:
            raise InspectorSandboxUnavailable("manifest catalog/trust root is unavailable")
        envelope = request.policy.resource_envelope
        if envelope is None or request.policy.resource_envelope_digest is None:
            raise InspectorSandboxUnavailable("sealed resource envelope is unavailable")
        deadline.remaining()
        try:
            manifest = self._catalog.resolve_exact(
                parser_build_digest=request.policy.parser_build_digest,
                resource_envelope_digest=request.policy.resource_envelope_digest,
            )
        except Exception as exc:
            raise InspectorSandboxUnavailable("manifest catalog lookup failed") from exc
        deadline.remaining()
        if manifest is None:
            raise InspectorSandboxUnavailable("exact signed manifest is unavailable")
        deadline.remaining()
        try:
            revoked = self._catalog.is_revoked(manifest)
        except Exception as exc:
            raise InspectorSandboxUnavailable("manifest revocation state unavailable") from exc
        deadline.remaining()
        if revoked is not False:
            raise InspectorSandboxUnavailable("manifest revocation state is not confirmed current")
        deadline.remaining()
        try:
            verdict = self._verifier.verify(manifest.canonical_body_bytes(), manifest.signature)
        except Exception as exc:
            raise InspectorSandboxUnavailable("manifest signature verifier unavailable") from exc
        deadline.remaining()
        if verdict is not SignatureVerificationVerdict.VALID:
            raise InspectorSandboxUnavailable("manifest signature is not valid")
        try:
            validate_inspector_execution_binding(request.policy, manifest)
        except Exception as exc:
            raise InspectorSandboxUnavailable(
                "policy and manifest bindings are inconsistent"
            ) from exc
        hard = manifest.body.hard_ceilings
        try:
            wall_from_policy = int(envelope.max_deadline_seconds * 1_000)
        except (OverflowError, ValueError) as exc:
            raise InspectorSandboxUnavailable(
                "policy deadline cannot form a finite wall limit"
            ) from exc
        if wall_from_policy <= 0:
            raise InspectorSandboxUnavailable("policy deadline cannot form a positive wall limit")
        effective = InspectorEffectiveLimitsV1(
            max_input_bytes=min(
                envelope.max_input_bytes, envelope.max_streamed_bytes, hard.max_input_bytes
            ),
            max_memory_bytes=min(envelope.max_memory_bytes, hard.max_memory_bytes),
            max_workspace_bytes=min(envelope.max_workspace_bytes, hard.max_tmpfs_bytes),
            max_output_bytes=min(envelope.max_output_bytes, hard.max_output_bytes),
            max_wall_time_millis=min(wall_from_policy, hard.max_wall_time_millis),
            max_pids=hard.max_pids,
            cpu_period_micros=hard.cpu_period_micros,
            cpu_quota_micros=hard.cpu_quota_micros,
            max_log_bytes=hard.max_log_bytes,
        )
        if request.sealed_byte_binding.observed_size_bytes > effective.max_input_bytes:
            raise ProtocolViolation("input exceeds signed and policy-clamped admission cap")
        return InspectorAdmissionV1(manifest=manifest, effective_limits=effective)

    def handle_connection(self, connection: socket.socket) -> None:
        """Handle one already-accepted AF_UNIX connection; no listener is created here."""
        if not self._peer_is_authorized(connection):
            self._close_quietly(connection)
            return
        deadline = ProtocolDeadline(self._protocol_limits.max_wire_duration_millis, self._monotonic)
        request: InspectorLaunchRequestV1 | None = None
        input_reservation: InspectorAdmissionReservationPort | None = None
        staged_input: InspectorStagedBytesPort | None = None
        cancellation = _SocketCancellation(connection)
        try:
            request = read_launch_request_header(
                connection, self._protocol_limits, deadline=deadline
            )
            admission = self._admit_wire_request(request, deadline)
            deadline.remaining()
            deadline.cap_duration_millis(admission.effective_limits.max_wall_time_millis)
            input_reservation = self._accounting.reserve(
                request_units=1,
                concurrency_units=1,
                spool_bytes=request.sealed_byte_binding.observed_size_bytes,
                deadline_monotonic=deadline.expires_at,
            )
            deadline.remaining()
            if input_reservation is None:
                raise InspectorSandboxUnavailable(
                    "aggregate request/concurrency/spool capacity unavailable"
                )
            staged_input = self._staging.begin(
                maximum_bytes=request.sealed_byte_binding.observed_size_bytes,
                deadline_monotonic=deadline.expires_at,
            )
            deadline.remaining()
            read_bound_bytes(
                connection,
                request.sealed_byte_binding,
                self._protocol_limits,
                staged_input.write,
                maximum_bytes=admission.effective_limits.max_input_bytes,
                deadline=deadline,
            )
            staged_input.finish()
            deadline.remaining()
            write_launch_result(
                connection,
                InspectorLaunchResultV1.accepted(request.attempt_nonce),
                self._protocol_limits,
                deadline=deadline,
            )
            cancellation.start_monitor(deadline)
            backend_result = self._backend.execute(
                request=request,
                staged_input=staged_input,
                limits=admission.effective_limits,
                deadline_monotonic=deadline.expires_at,
                is_cancelled=cancellation.is_cancelled,
            )
            deadline.remaining()
            if cancellation.is_cancelled():
                raise InspectorSandboxUnavailable("connection cancelled during backend execution")
            self._write_completed_result(
                connection, request, backend_result, admission.effective_limits, deadline
            )
        except _TerminalFrameEmitted:
            pass
        except (InspectorSandboxUnavailable, ProtocolViolation, ProtocolDeadlineExceeded):
            self._write_failure_if_identified(connection, request, deadline)
        except Exception:
            self._write_failure_if_identified(connection, request, deadline)
        finally:
            cancellation.stop_monitor()
            if staged_input is not None:
                self._abort_quietly(staged_input)
            if input_reservation is not None:
                self._release_quietly(input_reservation)
            self._close_quietly(connection)

    def _write_completed_result(
        self,
        connection: socket.socket,
        request: InspectorLaunchRequestV1,
        backend: InspectorBackendCompletedV1,
        limits: InspectorEffectiveLimitsV1,
        deadline: ProtocolDeadline,
    ) -> None:
        if backend.inspector_build_digest != request.policy.parser_build_digest:
            raise ProtocolViolation("backend build digest does not match signed manifest binding")
        if isinstance(backend.outcome, ArtifactInspectionOutcomeV1):
            if request.operation is not InspectorOperation.INSPECT:
                raise ProtocolViolation("SANITIZE backend returned inspection outcome")
            if backend.output_size_bytes != 0 or backend.output_sha256 is not None:
                raise ProtocolViolation("INSPECT backend returned derivative bytes")
            if backend.output.read(1):
                raise ProtocolViolation("INSPECT backend output stream is non-empty")
            deadline.remaining()
            result = InspectorLaunchResultV1.completed_inspection(
                request.attempt_nonce,
                request.canonical_input_digest,
                backend.inspector_build_digest,
                backend.outcome,
            )
            result.validate_for(request)
            write_launch_result(connection, result, self._protocol_limits, deadline=deadline)
            try:
                deadline.remaining()
                connection.shutdown(socket.SHUT_WR)
            except (OSError, ProtocolViolation) as exc:
                raise _TerminalFrameEmitted from exc
            return
        if request.operation is not InspectorOperation.SANITIZE or backend.outcome != "SANITIZED":
            raise ProtocolViolation("backend terminal outcome does not match requested operation")
        if (
            backend.output_size_bytes <= 0
            or backend.output_size_bytes > limits.max_output_bytes
            or backend.output_sha256 is None
        ):
            raise ProtocolViolation(
                "SANITIZE output exceeds effective limits or lacks exact binding"
            )
        output_reservation = self._accounting.reserve(
            request_units=0,
            concurrency_units=0,
            spool_bytes=backend.output_size_bytes,
            deadline_monotonic=deadline.expires_at,
        )
        staged_output: InspectorStagedBytesPort | None = None
        try:
            deadline.remaining()
            if output_reservation is None:
                raise InspectorSandboxUnavailable(
                    "aggregate SANITIZE output spool capacity unavailable"
                )
            staged_output = self._staging.begin(
                maximum_bytes=backend.output_size_bytes, deadline_monotonic=deadline.expires_at
            )
            deadline.remaining()
            observed = self._copy_exact_output(
                backend.output, staged_output, backend.output_size_bytes, deadline
            )
            if observed != backend.output_sha256:
                raise ProtocolViolation("SANITIZE output SHA-256 mismatch")
            staged_output.finish()
            deadline.remaining()
            result = InspectorLaunchResultV1.completed_sanitized(
                request.attempt_nonce,
                request.canonical_input_digest,
                backend.inspector_build_digest,
                backend.output_size_bytes,
                backend.output_sha256,
            )
            result.validate_for(request)
            write_launch_result(connection, result, self._protocol_limits, deadline=deadline)
            try:
                self._write_exact_staged_output(
                    connection, staged_output, backend.output_size_bytes, deadline
                )
                deadline.remaining()
                connection.shutdown(socket.SHUT_WR)
            except (OSError, ProtocolViolation) as exc:
                raise _TerminalFrameEmitted from exc
        finally:
            if staged_output is not None:
                self._abort_quietly(staged_output)
            if output_reservation is not None:
                self._release_quietly(output_reservation)

    def _copy_exact_output(
        self,
        source: BinaryIO,
        target: InspectorStagedBytesPort,
        size: int,
        deadline: ProtocolDeadline,
    ) -> str:
        digest = hashlib.sha256()
        remaining = size
        while remaining:
            deadline.remaining()
            chunk = source.read(min(remaining, self._protocol_limits.max_chunk_bytes))
            deadline.remaining()
            if not isinstance(chunk, bytes) or not chunk:
                raise ProtocolViolation("unexpected EOF in SANITIZE output")
            if len(chunk) > remaining:
                raise ProtocolViolation("SANITIZE output exceeded declared bound")
            digest.update(chunk)
            target.write(chunk)
            deadline.remaining()
            remaining -= len(chunk)
        deadline.remaining()
        trailing = source.read(1)
        deadline.remaining()
        if trailing:
            raise ProtocolViolation("trailing SANITIZE output bytes")
        return "sha256:" + digest.hexdigest()

    def _write_exact_staged_output(
        self,
        connection: socket.socket,
        staged: InspectorStagedBytesPort,
        size: int,
        deadline: ProtocolDeadline,
    ) -> None:
        remaining = size
        while remaining:
            deadline.remaining()
            chunk = staged.read(min(remaining, self._protocol_limits.max_chunk_bytes))
            deadline.remaining()
            if not isinstance(chunk, bytes) or not chunk:
                raise ProtocolViolation("staged SANITIZE output ended early")
            if len(chunk) > remaining:
                raise ProtocolViolation("staged SANITIZE output exceeded exact bound")
            try:
                connection.settimeout(deadline.remaining())
                connection.sendall(chunk)
            except TimeoutError as exc:
                raise ProtocolDeadlineExceeded("global wire deadline exceeded") from exc
            deadline.remaining()
            remaining -= len(chunk)
        deadline.remaining()
        trailing = staged.read(1)
        deadline.remaining()
        if trailing:
            raise ProtocolViolation("staged SANITIZE output has trailing bytes")

    def _peer_is_authorized(self, connection: socket.socket) -> bool:
        if not hasattr(socket, "SO_PEERCRED"):
            return False
        try:
            raw = connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
            )
            _pid, uid, _gid = struct.unpack("3i", raw)
        except (OSError, struct.error):
            return False
        return uid == self._required_worker_uid

    @staticmethod
    def _abort_quietly(staged: InspectorStagedBytesPort) -> None:
        with suppress(Exception):
            staged.abort()

    @staticmethod
    def _release_quietly(reservation: InspectorAdmissionReservationPort) -> None:
        with suppress(Exception):
            reservation.release()

    def _write_failure_if_identified(
        self,
        connection: socket.socket,
        request: InspectorLaunchRequestV1 | None,
        deadline: ProtocolDeadline,
    ) -> None:
        if request is None:
            return
        try:
            write_launch_result(
                connection,
                InspectorLaunchResultV1.failed(
                    request.attempt_nonce, InspectorFailureReason.INSPECTOR_UNAVAILABLE
                ),
                self._protocol_limits,
                deadline=deadline,
            )
            deadline.remaining()
            connection.shutdown(socket.SHUT_WR)
        except Exception:
            pass

    @staticmethod
    def _close_quietly(connection: socket.socket) -> None:
        with suppress(OSError):
            connection.close()


__all__ = [
    "CatalogStartupStatusV1",
    "ExternalInspectorLauncher",
    "InspectorAdmissionV1",
    "InspectorBackendCompletedV1",
    "InspectorEffectiveLimitsV1",
    "InspectorOperationProfileDecision",
    "InspectorSandboxUnavailable",
]
