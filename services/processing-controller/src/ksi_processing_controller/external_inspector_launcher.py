"""Admission-only local UDS launcher for a future external-inspector backend.

No listener, filesystem provisioning, Docker client, subprocess, parser, or
fallback backend lives here.  Every operational dependency is an injected port
and every unavailable dependency closes admission.
"""

from __future__ import annotations

import hashlib
import secrets
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

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ArtifactInspectionOutcomeV1
from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionManifestV1,
    InspectorExecutionManifestVerifier,
    SignatureVerificationVerdict,
    validate_inspector_execution_binding,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    model_validator,
)

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
    FixedRuntimeLimitsV1,
    build_fixed_container_configuration,
    compiled_inner_protocol_digest_v1,
    compiled_security_profile_digest_v1,
)
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
from ksi_processing_controller.external_inspector_runtime import (
    CpuCounterUnitV1,
    FixedRuntimeMeasurementV1,
    RuntimeControlDispositionV1,
    cpu_seconds_to_counter_budget,
)
from ksi_processing_controller.external_inspector_staging import (
    InspectorSealedInputPort,
    MappedInspectorReaderV1,
    ReaderMappingPort,
    RegisteredInputStagingPort,
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
    max_cpu_seconds: StrictFloat = Field(gt=0)


class InspectorBackendCompletedV1(BaseModel):
    """Opaque backend output that must be rechecked before it crosses UDS."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    inspector_build_digest: str
    outcome: ArtifactInspectionOutcomeV1 | Literal["SANITIZED"]
    output: Any
    output_size_bytes: StrictInt = Field(ge=0)
    output_sha256: str | None = None
    output_spooled: StrictBool = False
    runtime_id: str | None = None
    runtime_measurement: FixedRuntimeMeasurementV1

    @model_validator(mode="after")
    def _result_shape_is_staged_later(self) -> InspectorBackendCompletedV1:
        if not callable(getattr(self.output, "read", None)):
            raise ValueError("backend output must be a readable binary stream")
        return self


class InspectorBackendCreatedV1(BaseModel):
    """Exact runtime identity returned after create/inspect but before start."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    runtime_id: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


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


class _InspectorAbortablePort(Protocol):
    def abort(self) -> None: ...


class _InspectorRetainablePort(_InspectorAbortablePort, Protocol):
    def relinquish_for_recovery(self) -> None: ...


class InspectorStagingPort(Protocol):
    def begin(
        self, *, maximum_bytes: int, deadline_monotonic: float
    ) -> InspectorStagedBytesPort: ...


class InspectorBackendPort(Protocol):
    """Closed backend lifecycle: durable ID binding separates create from execution."""

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
    ) -> InspectorBackendCreatedV1: ...

    def execute(
        self,
        *,
        created: InspectorBackendCreatedV1,
        attempt: AttemptBindingV1,
        manifest: InspectorExecutionManifestV1,
        runtime_parent: RuntimeParentReceiptV1,
        output_staging: InspectorStagedBytesPort | None,
        request: InspectorLaunchRequestV1,
        sealed_input: InspectorSealedInputPort,
        limits: InspectorEffectiveLimitsV1,
        configuration: FixedContainerConfigurationV1,
        deadline_monotonic: float,
        is_cancelled: Callable[[], bool],
        monitor_termination: Callable[[str], float],
    ) -> InspectorBackendCompletedV1: ...


class InspectorAttemptJournalPort(Protocol):
    """No production fallback: every admitted byte stream has a durable local attempt."""

    def intend(self, binding: AttemptBindingV1) -> None: ...

    def staging_allocated(
        self, attempt_nonce: str, receipt: StagingAllocationReceiptV1
    ) -> None: ...

    def input_bound(
        self,
        attempt_nonce: str,
        *,
        artifact: StagingFileIdentityV1,
        observed_size_bytes: int,
        observed_sha256: str,
        reader_mapping_witness: str,
    ) -> None: ...

    def runtime_parent_creating(self, attempt_nonce: str) -> None: ...

    def container_bound(self, attempt_nonce: str, runtime_id: str) -> None: ...

    def runtime_parent_bound(self, attempt_nonce: str, receipt: RuntimeParentReceiptV1) -> None: ...

    def container_creating(self, attempt_nonce: str) -> None: ...

    def cleanup_required(self, attempt_nonce: str, *, disposition: str) -> None: ...

    def cleanup_failed(self, attempt_nonce: str, *, reason: str) -> None: ...

    def cleaned(self, attempt_nonce: str) -> None: ...


class InspectorAttemptRecoveryPort(Protocol):
    """A production launcher begins only after exact durable recovery succeeds."""

    def recover_startup(self) -> None: ...


class InspectorRuntimeParentPort(Protocol):
    """Create and prove the journaled user-systemd parent before Docker create."""

    def bind_before_create(
        self,
        *,
        binding: AttemptBindingV1,
        configuration: FixedContainerConfigurationV1,
    ) -> RuntimeParentReceiptV1: ...

    def adopt_if_prebound(self, *, binding: AttemptBindingV1) -> RuntimeParentReceiptV1 | None: ...

    def stop_exact(self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1) -> bool: ...

    def verify_before_quiesce(
        self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1, runtime_id: str
    ) -> bool: ...

    def verify_final_before_remove(
        self, *, binding: AttemptBindingV1, receipt: RuntimeParentReceiptV1, runtime_id: str
    ) -> bool: ...


class InspectorRuntimeCleanupPort(Protocol):
    """Remove only a runtime ID recorded by this launcher attempt; no inventory is exposed."""

    def resolve_exact(self, binding: AttemptBindingV1) -> str | None: ...

    def quiesce_exact(
        self,
        *,
        attempt: AttemptBindingV1,
        runtime_id: str,
        deadline_monotonic: float,
    ) -> bool: ...

    def remove_exact(
        self,
        *,
        attempt: AttemptBindingV1,
        runtime_id: str,
        deadline_monotonic: float,
    ) -> bool: ...


class _AttemptRuntimeCleanupCoordinator:
    """The only launcher-owned mutation path shared by monitor and foreground cleanup."""

    _MONITOR_REASONS = {"CPU_LIMIT_EXCEEDED", "DEADLINE_EXCEEDED", "CANCELLED"}

    def __init__(
        self,
        *,
        journal: InspectorAttemptJournalPort,
        runtime_parent: InspectorRuntimeParentPort,
        runtime_cleanup: InspectorRuntimeCleanupPort,
        latch_admission_closed: Callable[[], None],
        attempt: AttemptBindingV1,
        receipt: RuntimeParentReceiptV1,
        runtime_id: str,
        cleanup_deadline_monotonic: float,
    ) -> None:
        self._journal = journal
        self._runtime_parent = runtime_parent
        self._runtime_cleanup = runtime_cleanup
        self._latch_admission_closed = latch_admission_closed
        self._attempt = attempt
        self._receipt = receipt
        self._runtime_id = runtime_id
        self._cleanup_deadline_monotonic = cleanup_deadline_monotonic
        self._lock = threading.RLock()
        self._cleanup_required_recorded = False
        self._quiesced = False
        self._removed = False
        self._failed = False
        self._failure_recorded = False

    @property
    def cleanup_required_recorded(self) -> bool:
        with self._lock:
            return self._cleanup_required_recorded

    @property
    def failure_recorded(self) -> bool:
        with self._lock:
            return self._failure_recorded

    @property
    def cleanup_complete(self) -> bool:
        with self._lock:
            return self._removed

    def terminate_from_monitor(self, reason: str) -> float:
        if reason not in self._MONITOR_REASONS:
            self._failure("runtime monitor reason is invalid")
        started = time.monotonic()
        self.quiesce(disposition="MONITOR_" + reason)
        return time.monotonic() - started

    def quiesce(self, *, disposition: str) -> None:
        with self._lock:
            if self._failed:
                raise InspectorSandboxUnavailable("exact runtime cleanup is unavailable")
            try:
                if not self._cleanup_required_recorded:
                    self._journal.cleanup_required(
                        self._attempt.attempt_nonce, disposition=disposition
                    )
                    self._cleanup_required_recorded = True
                if self._quiesced:
                    return
                if not self._runtime_parent.verify_before_quiesce(
                    binding=self._attempt,
                    receipt=self._receipt,
                    runtime_id=self._runtime_id,
                ):
                    raise InspectorSandboxUnavailable("exact runtime parent proof is unavailable")
                if not self._runtime_cleanup.quiesce_exact(
                    attempt=self._attempt,
                    runtime_id=self._runtime_id,
                    deadline_monotonic=self._cleanup_deadline_monotonic,
                ):
                    raise InspectorSandboxUnavailable("exact runtime quiesce is unavailable")
                if not self._runtime_parent.verify_final_before_remove(
                    binding=self._attempt,
                    receipt=self._receipt,
                    runtime_id=self._runtime_id,
                ):
                    raise InspectorSandboxUnavailable(
                        "exact runtime final measurement is unavailable"
                    )
                self._quiesced = True
            except Exception as exc:
                self._failure("exact runtime cleanup is unavailable")
                raise InspectorSandboxUnavailable("exact runtime cleanup is unavailable") from exc

    def remove_after_quiesce(self) -> None:
        with self._lock:
            if self._failed:
                raise InspectorSandboxUnavailable("exact runtime cleanup is unavailable")
            try:
                if not self._quiesced:
                    raise InspectorSandboxUnavailable("exact runtime is not quiesced")
                if self._removed:
                    return
                if not self._runtime_cleanup.remove_exact(
                    attempt=self._attempt,
                    runtime_id=self._runtime_id,
                    deadline_monotonic=self._cleanup_deadline_monotonic,
                ):
                    raise InspectorSandboxUnavailable("exact runtime cleanup is unavailable")
                self._removed = True
            except Exception as exc:
                self._failure("exact runtime cleanup is unavailable")
                raise InspectorSandboxUnavailable("exact runtime cleanup is unavailable") from exc

    def quiesce_and_remove(self, *, disposition: str) -> None:
        self.quiesce(disposition=disposition)
        self.remove_after_quiesce()

    def _failure(self, message: str) -> None:
        self._failed = True
        self._latch_admission_closed()
        if self._cleanup_required_recorded and not self._failure_recorded:
            self._failure_recorded = True
            with suppress(Exception):
                self._journal.cleanup_failed(
                    self._attempt.attempt_nonce, reason="EXACT_RUNTIME_CLEANUP_UNAVAILABLE"
                )
        del message


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
        input_staging: RegisteredInputStagingPort,
        reader_mapping: ReaderMappingPort,
        attempt_journal: InspectorAttemptJournalPort,
        attempt_recovery: InspectorAttemptRecoveryPort,
        runtime_parent: InspectorRuntimeParentPort,
        runtime_cleanup: InspectorRuntimeCleanupPort,
        backend: InspectorBackendPort,
        protocol_limits: ProtocolLimitsV1,
        systemd_base_slice: str,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(required_worker_uid) is not int or required_worker_uid < 0:
            raise ValueError("required_worker_uid must be a non-negative integer")
        if (
            not isinstance(systemd_base_slice, str)
            or not systemd_base_slice
            or "/" in systemd_base_slice
            or not systemd_base_slice.endswith(".slice")
        ):
            raise ValueError("systemd_base_slice must be a configured slice unit name")
        self._required_worker_uid = required_worker_uid
        self._catalog = catalog
        self._verifier = verifier
        self._operation_profile = operation_profile
        self._accounting = accounting
        self._staging = staging
        self._input_staging = input_staging
        self._reader_mapping = reader_mapping
        self._attempt_journal = attempt_journal
        self._attempt_recovery = attempt_recovery
        self._runtime_parent = runtime_parent
        self._runtime_cleanup = runtime_cleanup
        self._backend = backend
        self._protocol_limits = protocol_limits
        self._systemd_base_slice = systemd_base_slice
        self._monotonic = monotonic
        # A response-owned anonymous spool has no durable retry target.  Once
        # closing it fails, accept no more work from this daemon instance.
        self._admission_health_lock = threading.Lock()
        self._admission_closed = False
        try:
            self._attempt_recovery.recover_startup()
        except Exception as exc:
            raise InspectorSandboxUnavailable("durable attempt recovery is unavailable") from exc

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
        if request.policy.grammar_digest != manifest.body.backend_profile_digest:
            raise InspectorSandboxUnavailable(
                "policy grammar digest does not match signed backend profile"
            )
        if request.policy.grammar_digest != external_geotiff_profile_digest_v1():
            raise InspectorSandboxUnavailable(
                "signed backend profile is not external-geotiff-profile.v1"
            )
        if manifest.body.inspector_protocol_digest != compiled_inner_protocol_digest_v1():
            raise InspectorSandboxUnavailable(
                "signed inspector protocol is not implemented by this launcher"
            )
        if manifest.body.security_profile_digest != compiled_security_profile_digest_v1():
            raise InspectorSandboxUnavailable(
                "signed inspector security profile is not implemented by this launcher"
            )
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
            max_cpu_seconds=envelope.max_cpu_seconds,
        )
        if request.sealed_byte_binding.observed_size_bytes > effective.max_input_bytes:
            raise ProtocolViolation("input exceeds signed and policy-clamped admission cap")
        return InspectorAdmissionV1(manifest=manifest, effective_limits=effective)

    def handle_connection(self, connection: socket.socket) -> None:
        """Handle one already-accepted AF_UNIX connection; no listener is created here."""
        if self._is_admission_closed():
            self._close_quietly(connection)
            return
        if not self._peer_is_authorized(connection):
            self._close_quietly(connection)
            return
        deadline = ProtocolDeadline(self._protocol_limits.max_wire_duration_millis, self._monotonic)
        request: InspectorLaunchRequestV1 | None = None
        input_reservation: InspectorAdmissionReservationPort | None = None
        output_reservation: InspectorAdmissionReservationPort | None = None
        staged_output: InspectorStagedBytesPort | None = None
        mutable_input = None
        sealed_input: InspectorSealedInputPort | None = None
        attempt: AttemptBindingV1 | None = None
        allocation: StagingAllocationReceiptV1 | None = None
        runtime_id: str | None = None
        runtime_parent: RuntimeParentReceiptV1 | None = None
        runtime_coordinator: _AttemptRuntimeCleanupCoordinator | None = None
        attempt_cleaned = False
        cleanup_required_recorded = False
        runtime_cleanup_attempted = False
        runtime_cleanup_complete = False
        runtime_parent_creating = False
        container_creating = False
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
            reader = self._resolve_reader_mapping(admission, deadline)
            root = self._input_staging.private_root_identity()
            attempt = self._new_attempt_binding(
                request, admission.manifest, root, admission.effective_limits
            )
            self._attempt_journal.intend(attempt)
            mutable_input, allocation = self._input_staging.begin_registered(
                plan=attempt.staging,
                maximum_bytes=request.sealed_byte_binding.observed_size_bytes,
                deadline_monotonic=deadline.expires_at,
            )
            self._attempt_journal.staging_allocated(request.attempt_nonce, allocation)
            deadline.remaining()
            read_bound_bytes(
                connection,
                request.sealed_byte_binding,
                self._protocol_limits,
                mutable_input.write,
                maximum_bytes=admission.effective_limits.max_input_bytes,
                deadline=deadline,
            )
            sealed_input = mutable_input.seal_for_reader(
                expected_sha256=request.sealed_byte_binding.observed_sha256,
                expected_size_bytes=request.sealed_byte_binding.observed_size_bytes,
                reader=reader,
                supplementary_groups=admission.manifest.body.supplementary_groups,
                deadline_monotonic=deadline.expires_at,
            )
            mutable_input = None
            deadline.remaining()
            bind = sealed_input.prepare_read_only_bind(deadline_monotonic=deadline.expires_at)
            self._attempt_journal.input_bound(
                request.attempt_nonce,
                artifact=StagingFileIdentityV1(
                    device=bind.source_device,
                    inode=bind.source_inode,
                    mode=0o600,
                    owner_uid=bind.source_owner_uid,
                    owner_gid=bind.source_owner_gid,
                    link_count=bind.source_link_count,
                    size=bind.observed_size_bytes,
                ),
                observed_size_bytes=bind.observed_size_bytes,
                observed_sha256=bind.observed_sha256,
                reader_mapping_witness=bind.reader_mapping_witness,
            )
            refreshed = self._admit_wire_request(request, deadline)
            if (
                refreshed.manifest.canonical_body_digest()
                != admission.manifest.canonical_body_digest()
            ):
                raise InspectorSandboxUnavailable("manifest changed after sealed input binding")
            write_launch_result(
                connection,
                InspectorLaunchResultV1.accepted(request.attempt_nonce),
                self._protocol_limits,
                deadline=deadline,
            )
            cancellation.start_monitor(deadline)
            # This is immediately before the fixed backend's create operation.
            refreshed = self._admit_wire_request(request, deadline)
            if (
                refreshed.manifest.canonical_body_digest()
                != admission.manifest.canonical_body_digest()
            ):
                raise InspectorSandboxUnavailable("manifest changed before runtime create")
            runtime_bind = sealed_input.prepare_read_only_bind(
                deadline_monotonic=deadline.expires_at
            )
            runtime_configuration = build_fixed_container_configuration(
                manifest=refreshed.manifest,
                limits=self._fixed_runtime_limits(refreshed.effective_limits),
                input_bind=runtime_bind,
            )
            self._attempt_journal.runtime_parent_creating(request.attempt_nonce)
            runtime_parent_creating = True
            runtime_parent = self._runtime_parent.bind_before_create(
                binding=attempt,
                configuration=runtime_configuration,
            )
            self._attempt_journal.runtime_parent_bound(request.attempt_nonce, runtime_parent)
            runtime_parent_creating = False
            self._attempt_journal.container_creating(request.attempt_nonce)
            container_creating = True
            created = self._backend.create(
                attempt=attempt,
                request=request,
                sealed_input=sealed_input,
                limits=admission.effective_limits,
                configuration=runtime_configuration,
                deadline_monotonic=deadline.expires_at,
                is_cancelled=cancellation.is_cancelled,
            )
            runtime_id = created.runtime_id
            self._attempt_journal.container_bound(request.attempt_nonce, runtime_id)
            container_creating = False
            runtime_coordinator = _AttemptRuntimeCleanupCoordinator(
                journal=self._attempt_journal,
                runtime_parent=self._runtime_parent,
                runtime_cleanup=self._runtime_cleanup,
                latch_admission_closed=self._latch_admission_closed,
                attempt=attempt,
                receipt=runtime_parent,
                runtime_id=runtime_id,
                cleanup_deadline_monotonic=deadline.expires_at,
            )
            deadline.remaining()
            if cancellation.is_cancelled():
                raise InspectorSandboxUnavailable("connection cancelled during runtime create")
            if request.operation is InspectorOperation.SANITIZE:
                output_reservation = self._accounting.reserve(
                    request_units=0,
                    concurrency_units=0,
                    spool_bytes=admission.effective_limits.max_output_bytes,
                    deadline_monotonic=deadline.expires_at,
                )
                deadline.remaining()
                if output_reservation is None:
                    raise InspectorSandboxUnavailable(
                        "aggregate SANITIZE output spool capacity unavailable"
                    )
                staged_output = self._staging.begin(
                    maximum_bytes=admission.effective_limits.max_output_bytes,
                    deadline_monotonic=deadline.expires_at,
                )
                deadline.remaining()
            backend_result = self._backend.execute(
                created=created,
                attempt=attempt,
                manifest=refreshed.manifest,
                runtime_parent=runtime_parent,
                output_staging=staged_output,
                request=request,
                sealed_input=sealed_input,
                limits=admission.effective_limits,
                configuration=runtime_configuration,
                deadline_monotonic=deadline.expires_at,
                is_cancelled=cancellation.is_cancelled,
                monitor_termination=runtime_coordinator.terminate_from_monitor,
            )
            deadline.remaining()
            if cancellation.is_cancelled():
                raise InspectorSandboxUnavailable("connection cancelled during backend execution")
            if backend_result.runtime_id != runtime_id:
                raise InspectorSandboxUnavailable("backend result runtime ID does not match create")
            measurement = backend_result.runtime_measurement
            if measurement.runtime_id != runtime_id:
                raise InspectorSandboxUnavailable(
                    "runtime measurement ID does not match runtime ID"
                )
            if (
                measurement.counter_unit is not runtime_configuration.cpu_counter_unit
                or measurement.budget_counter != runtime_configuration.cpu_budget_counter
                or measurement.threshold_exceeded
                or measurement.disposition is not RuntimeControlDispositionV1.COMPLETED
            ):
                raise InspectorSandboxUnavailable(
                    "runtime CPU measurement is not an accepted final fact"
                )
            if request.operation is InspectorOperation.SANITIZE:
                if staged_output is None:
                    raise InspectorSandboxUnavailable(
                        "private SANITIZE output spool is unavailable"
                    )
                self._seal_sanitize_output(
                    request,
                    backend_result,
                    staged_output,
                    admission.effective_limits,
                    deadline,
                )
            runtime_coordinator.quiesce_and_remove(disposition="BACKEND_COMPLETED")
            cleanup_required_recorded = runtime_coordinator.cleanup_required_recorded
            runtime_cleanup_attempted = True
            runtime_cleanup_complete = runtime_coordinator.cleanup_complete
            self._finish_registered_cleanup(
                attempt,
                allocation,
                sealed_input=sealed_input,
                mutable_input=None,
                runtime_parent=runtime_parent,
                deadline_monotonic=deadline.expires_at,
            )
            attempt_cleaned = True
            sealed_input = None
            self._write_completed_result(
                connection,
                request,
                backend_result,
                admission.effective_limits,
                deadline,
                staged_output=staged_output,
            )
        except _TerminalFrameEmitted:
            pass
        except (InspectorSandboxUnavailable, ProtocolViolation, ProtocolDeadlineExceeded):
            if attempt is not None and not attempt_cleaned:
                uncertain, runtime_id, runtime_parent = self._reconcile_inflight_creation(
                    attempt,
                    runtime_id=runtime_id,
                    runtime_parent=runtime_parent,
                    parent_creating=runtime_parent_creating,
                    container_creating=container_creating,
                    sealed_input=sealed_input,
                    mutable_input=mutable_input,
                )
                if uncertain:
                    sealed_input = None
                    mutable_input = None
                    self._write_failure_if_identified(connection, request, deadline)
                    return
                self._cleanup_after_failure(
                    attempt,
                    allocation,
                    sealed_input,
                    mutable_input,
                    runtime_id=runtime_id,
                    runtime_parent=runtime_parent,
                    deadline_monotonic=deadline.expires_at,
                    cleanup_required_recorded=cleanup_required_recorded,
                    runtime_cleanup_attempted=runtime_cleanup_attempted,
                    runtime_cleanup_complete=runtime_cleanup_complete,
                    runtime_coordinator=runtime_coordinator,
                )
                sealed_input = None
                mutable_input = None
            self._write_failure_if_identified(connection, request, deadline)
        except Exception:
            if attempt is not None and not attempt_cleaned:
                uncertain, runtime_id, runtime_parent = self._reconcile_inflight_creation(
                    attempt,
                    runtime_id=runtime_id,
                    runtime_parent=runtime_parent,
                    parent_creating=runtime_parent_creating,
                    container_creating=container_creating,
                    sealed_input=sealed_input,
                    mutable_input=mutable_input,
                )
                if uncertain:
                    sealed_input = None
                    mutable_input = None
                    self._write_failure_if_identified(connection, request, deadline)
                    return
                self._cleanup_after_failure(
                    attempt,
                    allocation,
                    sealed_input,
                    mutable_input,
                    runtime_id=runtime_id,
                    runtime_parent=runtime_parent,
                    deadline_monotonic=deadline.expires_at,
                    cleanup_required_recorded=cleanup_required_recorded,
                    runtime_cleanup_attempted=runtime_cleanup_attempted,
                    runtime_cleanup_complete=runtime_cleanup_complete,
                    runtime_coordinator=runtime_coordinator,
                )
                sealed_input = None
                mutable_input = None
            self._write_failure_if_identified(connection, request, deadline)
        finally:
            cancellation.stop_monitor()
            if sealed_input is not None:
                self._abort_quietly(sealed_input)
            elif mutable_input is not None:
                self._abort_quietly(mutable_input)
            if input_reservation is not None:
                self._release_quietly(input_reservation)
            if staged_output is not None:
                self._abort_output_and_latch_health(staged_output)
            if output_reservation is not None:
                self._release_quietly(output_reservation)
            self._close_quietly(connection)

    def _new_attempt_binding(
        self,
        request: InspectorLaunchRequestV1,
        manifest: InspectorExecutionManifestV1,
        root: PrivateStagingRootV1,
        limits: InspectorEffectiveLimitsV1,
    ) -> AttemptBindingV1:
        owner = request.fence.worker_instance_id
        stable = hashlib.sha256(request.attempt_nonce.encode("utf-8")).hexdigest()[:32]
        allocation_binding = (
            "sha256:"
            + hashlib.sha256(
                canonical_json_bytes(
                    {
                        "attemptNonce": request.attempt_nonce,
                        "canonicalInputDigest": request.canonical_input_digest,
                        "owner": owner,
                        "manifest": manifest.canonical_body_digest(),
                    }
                )
            ).hexdigest()
        )
        plan = StagingAllocationPlanV1(
            attempt_nonce=request.attempt_nonce,
            binding_digest=allocation_binding,
            owner=owner,
            allocation_nonce=secrets.token_hex(16),
            root=root,
            staging_name=f"attempt-{stable}",
            artifact_leaf="artifact",
            provisional_marker_name=f".attempt-{stable}.provisional",
            committed_marker_name=f".attempt-{stable}.committed",
        )
        body = manifest.body
        return AttemptBindingV1(
            attempt_nonce=request.attempt_nonce,
            canonical_input_digest=request.canonical_input_digest,
            operation=request.operation.value,
            owner=owner,
            container_name=f"external-inspector-{stable}",
            systemd_slice_name=f"ksi-inspector-a{stable}.slice",
            systemd_base_slice=self._systemd_base_slice,
            execution_manifest_digest=manifest.canonical_body_digest(),
            parser_build_digest=manifest.parser_build_digest,
            oci_manifest_digest=body.image_identity.oci_manifest_digest,
            oci_config_digest=body.image_identity.oci_config_digest,
            backend_profile_digest=body.backend_profile_digest,
            security_profile_digest=body.security_profile_digest,
            resource_envelope_digest=body.resource_envelope_digest,
            inspector_protocol_digest=body.inspector_protocol_digest,
            cpu_budget_counter=cpu_seconds_to_counter_budget(
                limits.max_cpu_seconds, CpuCounterUnitV1.CPU_USEC
            ),
            staging=plan,
        )

    @staticmethod
    def _fixed_runtime_limits(limits: InspectorEffectiveLimitsV1) -> FixedRuntimeLimitsV1:
        return FixedRuntimeLimitsV1(
            max_memory_bytes=limits.max_memory_bytes,
            max_workspace_bytes=limits.max_workspace_bytes,
            max_output_bytes=limits.max_output_bytes,
            max_wall_time_millis=limits.max_wall_time_millis,
            max_pids=limits.max_pids,
            cpu_period_micros=limits.cpu_period_micros,
            cpu_quota_micros=limits.cpu_quota_micros,
            max_log_bytes=limits.max_log_bytes,
            max_cpu_seconds=limits.max_cpu_seconds,
        )

    def _finish_registered_cleanup(
        self,
        attempt: AttemptBindingV1,
        allocation: StagingAllocationReceiptV1 | None,
        *,
        sealed_input: InspectorSealedInputPort | None,
        mutable_input: _InspectorRetainablePort | None,
        runtime_parent: RuntimeParentReceiptV1 | None,
        deadline_monotonic: float,
    ) -> None:
        if runtime_parent is not None and not self._runtime_parent.stop_exact(
            binding=attempt, receipt=runtime_parent
        ):
            raise InspectorSandboxUnavailable("exact runtime parent cleanup is unavailable")
        if sealed_input is not None:
            sealed_input.abort()
        elif mutable_input is not None:
            mutable_input.abort()
        if allocation is None:
            raise InspectorSandboxUnavailable("registered allocation lacks a durable receipt")
        self._input_staging.finalize_registered_cleanup(plan=attempt.staging, receipt=allocation)
        self._attempt_journal.cleaned(attempt.attempt_nonce)

    def _remove_exact_runtime(
        self,
        attempt: AttemptBindingV1,
        runtime_id: str,
        *,
        deadline_monotonic: float,
    ) -> None:
        if not self._runtime_cleanup.remove_exact(
            attempt=attempt,
            runtime_id=runtime_id,
            deadline_monotonic=deadline_monotonic,
        ):
            raise InspectorSandboxUnavailable("exact runtime cleanup is unavailable")

    def _quiesce_exact_runtime(
        self,
        attempt: AttemptBindingV1,
        runtime_id: str,
        *,
        runtime_parent: RuntimeParentReceiptV1 | None,
        deadline_monotonic: float,
    ) -> None:
        if runtime_parent is None or not self._runtime_parent.verify_before_quiesce(
            binding=attempt, receipt=runtime_parent, runtime_id=runtime_id
        ):
            raise InspectorSandboxUnavailable("exact runtime parent proof is unavailable")
        if not self._runtime_cleanup.quiesce_exact(
            attempt=attempt,
            runtime_id=runtime_id,
            deadline_monotonic=deadline_monotonic,
        ):
            raise InspectorSandboxUnavailable("exact runtime quiesce is unavailable")
        if not self._runtime_parent.verify_final_before_remove(
            binding=attempt, receipt=runtime_parent, runtime_id=runtime_id
        ):
            raise InspectorSandboxUnavailable("exact runtime final measurement is unavailable")

    def _cleanup_after_failure(
        self,
        attempt: AttemptBindingV1,
        allocation: StagingAllocationReceiptV1 | None,
        sealed_input: InspectorSealedInputPort | None,
        mutable_input: _InspectorRetainablePort | None,
        *,
        runtime_id: str | None,
        runtime_parent: RuntimeParentReceiptV1 | None,
        deadline_monotonic: float,
        cleanup_required_recorded: bool,
        runtime_cleanup_attempted: bool,
        runtime_cleanup_complete: bool,
        runtime_coordinator: _AttemptRuntimeCleanupCoordinator | None,
    ) -> None:
        cleanup_uncertain = False
        try:
            if not cleanup_required_recorded and runtime_coordinator is None:
                self._attempt_journal.cleanup_required(
                    attempt.attempt_nonce, disposition="BACKEND_FAILED"
                )
            if runtime_id is not None:
                if runtime_coordinator is not None:
                    runtime_coordinator.quiesce_and_remove(disposition="BACKEND_FAILED")
                    cleanup_required_recorded = runtime_coordinator.cleanup_required_recorded
                    runtime_cleanup_attempted = True
                    runtime_cleanup_complete = runtime_coordinator.cleanup_complete
                elif runtime_cleanup_attempted and not runtime_cleanup_complete:
                    cleanup_uncertain = True
                    self._relinquish_for_recovery(sealed_input, mutable_input)
                    self._attempt_journal.cleanup_failed(
                        attempt.attempt_nonce, reason="EXACT_RUNTIME_CLEANUP_UNAVAILABLE"
                    )
                    return
                elif not runtime_cleanup_attempted:
                    try:
                        self._quiesce_exact_runtime(
                            attempt,
                            runtime_id,
                            runtime_parent=runtime_parent,
                            deadline_monotonic=deadline_monotonic,
                        )
                        self._remove_exact_runtime(
                            attempt, runtime_id, deadline_monotonic=deadline_monotonic
                        )
                    except Exception:
                        cleanup_uncertain = True
                        self._relinquish_for_recovery(sealed_input, mutable_input)
                        self._attempt_journal.cleanup_failed(
                            attempt.attempt_nonce, reason="EXACT_RUNTIME_CLEANUP_UNAVAILABLE"
                        )
                        return
            self._finish_registered_cleanup(
                attempt,
                allocation,
                sealed_input=sealed_input,
                mutable_input=mutable_input,
                runtime_parent=runtime_parent,
                deadline_monotonic=deadline_monotonic,
            )
        except Exception:
            cleanup_uncertain = True
            if runtime_id is not None:
                self._relinquish_for_recovery(sealed_input, mutable_input)
            if runtime_coordinator is None or not runtime_coordinator.failure_recorded:
                with suppress(Exception):
                    self._attempt_journal.cleanup_failed(
                        attempt.attempt_nonce, reason="REGISTERED_CLEANUP_UNAVAILABLE"
                    )
        finally:
            if cleanup_uncertain:
                self._latch_admission_closed()

    def _reconcile_inflight_creation(
        self,
        attempt: AttemptBindingV1,
        *,
        runtime_id: str | None,
        runtime_parent: RuntimeParentReceiptV1 | None,
        parent_creating: bool,
        container_creating: bool,
        sealed_input: InspectorSealedInputPort | None,
        mutable_input: _InspectorRetainablePort | None,
    ) -> tuple[bool, str | None, RuntimeParentReceiptV1 | None]:
        """Persist an exact observed create outcome, or retain it as unresolved.

        Both external creates have a durable intent before the call.  A thrown
        call has no negative proof, so only a freshly verified exact resource
        may advance to its receipt/ID.  All other outcomes retain staging for
        startup recovery and latch future admission closed.
        """
        if parent_creating:
            try:
                observed_parent = self._runtime_parent.adopt_if_prebound(binding=attempt)
            except Exception:
                return self._retain_creation_ambiguity(
                    attempt,
                    disposition="RUNTIME_PARENT_CREATE_AMBIGUOUS",
                    sealed_input=sealed_input,
                    mutable_input=mutable_input,
                )
            if observed_parent is None:
                return self._retain_creation_ambiguity(
                    attempt,
                    disposition="RUNTIME_PARENT_CREATE_AMBIGUOUS",
                    sealed_input=sealed_input,
                    mutable_input=mutable_input,
                )
            try:
                self._attempt_journal.runtime_parent_bound(attempt.attempt_nonce, observed_parent)
            except Exception:
                return self._retain_creation_ambiguity(
                    attempt,
                    disposition="RUNTIME_PARENT_CREATE_AMBIGUOUS",
                    sealed_input=sealed_input,
                    mutable_input=mutable_input,
                )
            runtime_parent = observed_parent
        if container_creating:
            try:
                observed_runtime_id = self._runtime_cleanup.resolve_exact(attempt)
            except Exception:
                return self._retain_creation_ambiguity(
                    attempt,
                    disposition="CONTAINER_CREATE_AMBIGUOUS",
                    sealed_input=sealed_input,
                    mutable_input=mutable_input,
                )
            if observed_runtime_id is None:
                return self._retain_creation_ambiguity(
                    attempt,
                    disposition="CONTAINER_CREATE_AMBIGUOUS",
                    sealed_input=sealed_input,
                    mutable_input=mutable_input,
                )
            try:
                self._attempt_journal.container_bound(attempt.attempt_nonce, observed_runtime_id)
            except Exception:
                return self._retain_creation_ambiguity(
                    attempt,
                    disposition="CONTAINER_CREATE_AMBIGUOUS",
                    sealed_input=sealed_input,
                    mutable_input=mutable_input,
                )
            runtime_id = observed_runtime_id
        return False, runtime_id, runtime_parent

    def _retain_creation_ambiguity(
        self,
        attempt: AttemptBindingV1,
        *,
        disposition: str,
        sealed_input: InspectorSealedInputPort | None,
        mutable_input: _InspectorRetainablePort | None,
    ) -> tuple[bool, None, None]:
        try:
            self._attempt_journal.cleanup_required(
                attempt.attempt_nonce, disposition=disposition
            )
            self._attempt_journal.cleanup_failed(
                attempt.attempt_nonce, reason="EXACT_CREATE_OUTCOME_UNAVAILABLE"
            )
        finally:
            self._relinquish_for_recovery(sealed_input, mutable_input)
            self._latch_admission_closed()
        return True, None, None

    @staticmethod
    def _relinquish_for_recovery(
        sealed_input: InspectorSealedInputPort | None,
        mutable_input: _InspectorRetainablePort | None,
    ) -> None:
        if sealed_input is not None:
            sealed_input.relinquish_for_recovery()
        elif mutable_input is not None:
            mutable_input.relinquish_for_recovery()

    def _write_completed_result(
        self,
        connection: socket.socket,
        request: InspectorLaunchRequestV1,
        backend: InspectorBackendCompletedV1,
        limits: InspectorEffectiveLimitsV1,
        deadline: ProtocolDeadline,
        *,
        staged_output: InspectorStagedBytesPort | None,
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
        if staged_output is None:
            raise InspectorSandboxUnavailable("private SANITIZE output spool is unavailable")
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

    def _seal_sanitize_output(
        self,
        request: InspectorLaunchRequestV1,
        backend: InspectorBackendCompletedV1,
        staged_output: InspectorStagedBytesPort,
        limits: InspectorEffectiveLimitsV1,
        deadline: ProtocolDeadline,
    ) -> None:
        if (
            backend.outcome != "SANITIZED"
            or backend.output_size_bytes <= 0
            or backend.output_size_bytes > limits.max_output_bytes
            or backend.output_sha256 is None
        ):
            raise ProtocolViolation(
                "SANITIZE output exceeds effective limits or lacks exact binding"
            )
        if request.operation is not InspectorOperation.SANITIZE:
            raise ProtocolViolation("INSPECT backend returned derivative bytes")
        if backend.output_spooled:
            observed_size = getattr(staged_output, "size_bytes", None)
            observed_sha256 = getattr(staged_output, "sha256", None)
            if (
                observed_size != backend.output_size_bytes
                or observed_sha256 != backend.output_sha256
            ):
                raise ProtocolViolation("pre-spooled SANITIZE output binding is invalid")
        else:
            observed = self._copy_exact_output(
                backend.output, staged_output, backend.output_size_bytes, deadline
            )
            if observed != backend.output_sha256:
                raise ProtocolViolation("SANITIZE output SHA-256 mismatch")
            staged_output.finish()
            transfer = getattr(staged_output, "retain_for_response", None)
            if callable(transfer):
                transfer()
        deadline.remaining()

    def _resolve_reader_mapping(
        self, admission: InspectorAdmissionV1, deadline: ProtocolDeadline
    ) -> MappedInspectorReaderV1:
        deadline.remaining()
        try:
            reader = self._reader_mapping.resolve_exact(
                runtime_uid=admission.manifest.body.runtime_uid,
                runtime_gid=admission.manifest.body.runtime_gid,
                supplementary_groups=admission.manifest.body.supplementary_groups,
                deadline_monotonic=deadline.expires_at,
            )
        except Exception as exc:
            raise InspectorSandboxUnavailable(
                "signed runtime reader mapping is unavailable"
            ) from exc
        deadline.remaining()
        if not isinstance(reader, MappedInspectorReaderV1):
            raise InspectorSandboxUnavailable("signed runtime reader mapping is unavailable")
        return reader

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
    def _abort_quietly(staged: _InspectorAbortablePort) -> None:
        with suppress(Exception):
            staged.abort()

    def _abort_output_and_latch_health(self, staged: InspectorStagedBytesPort) -> None:
        """Close the response-owned spool once and fail future admission on error.

        The completed response and durable CLEANED event are already final by
        this point.  Retrying a close can target a recycled descriptor, while
        attempting another journal transition would rewrite that final event.
        """
        try:
            staged.abort()
        except Exception:
            self._latch_admission_closed()

    def _latch_admission_closed(self) -> None:
        with self._admission_health_lock:
            self._admission_closed = True

    def _is_admission_closed(self) -> bool:
        with self._admission_health_lock:
            return self._admission_closed

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
    "InspectorBackendCreatedV1",
    "InspectorBackendCompletedV1",
    "InspectorEffectiveLimitsV1",
    "InspectorOperationProfileDecision",
    "InspectorSandboxUnavailable",
]
