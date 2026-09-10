"""V2 opaque-primary/contained-secondary orchestration with durable exact cleanup.

No terminal bytes are emitted until CLEANED. Protocol/runtime failures close the
connection; only validated contained measurement failures have public reasons.
"""

from __future__ import annotations

import secrets
import socket
import struct
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol

from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestVerifier

from ksi_processing_controller.external_attempt_lifecycle import (
    AttemptLifecycleParentPort,
    AttemptLifecycleRuntimePort,
    AttemptRuntimeCleanupCoordinator,
    InspectorSandboxUnavailable,
    reconcile_inflight_creation,
)
from ksi_processing_controller.external_inspector_attempts import (
    RuntimeParentReceiptV1,
    StagingAllocationReceiptV1,
    StagingFileIdentityV1,
)
from ksi_processing_controller.external_inspector_container_protocol import (
    FixedContainerConfigurationV1,
    FixedRuntimeLimitsV1,
    build_fixed_container_configuration,
)
from ksi_processing_controller.external_inspector_launcher import (
    InspectorAdmissionAccountingPort,
    InspectorAdmissionReservationPort,
    InspectorAttemptRecoveryPort,
    _DeadlineBoundedInputStagingSink,
    _SocketCancellation,
)
from ksi_processing_controller.external_inspector_protocol import (
    ProtocolDeadline,
    ProtocolLimitsV1,
    _write_frame,
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
    MutableInspectorInputPort,
    ReaderMappingPort,
    RegisteredInputStagingPort,
)
from ksi_processing_controller.external_measurement_admission import (
    MeasurementAdmissionV2,
    MeasurementManifestCatalogPort,
    admit_measurement_request,
)
from ksi_processing_controller.external_measurement_attempts import (
    MeasurementAttemptBindingV2,
    MeasurementAttemptJournalV2,
    new_measurement_attempt_binding,
)
from ksi_processing_controller.external_measurement_result import build_measurement_result
from ksi_processing_controller.external_measurement_transport import MeasurementRequestReceiverV2

if TYPE_CHECKING:
    from ksi_processing_controller.external_measurement_docker_backend import (
        DockerMeasurementActiveV2,
        DockerMeasurementBackend,
    )


class MeasurementRuntimeParentPort(
    AttemptLifecycleParentPort[MeasurementAttemptBindingV2], Protocol
):
    def bind_before_create(
        self, *, binding: MeasurementAttemptBindingV2, configuration: FixedContainerConfigurationV1
    ) -> RuntimeParentReceiptV1: ...


@dataclass
class _AttemptState:
    binding: MeasurementAttemptBindingV2 | None = None
    intended: bool = False
    allocation: StagingAllocationReceiptV1 | None = None
    mutable: MutableInspectorInputPort | None = None
    sealed: InspectorSealedInputPort | None = None
    parent: RuntimeParentReceiptV1 | None = None
    runtime_id: str | None = None
    parent_creating: bool = False
    container_creating: bool = False
    coordinator: AttemptRuntimeCleanupCoordinator[MeasurementAttemptBindingV2] | None = None
    active: DockerMeasurementActiveV2 | None = None
    reservation: InspectorAdmissionReservationPort | None = None
    cleaned: bool = False
    retained: bool = False


class ExternalMeasurementLauncher:
    def __init__(
        self,
        *,
        required_worker_uid: int,
        catalog: MeasurementManifestCatalogPort,
        verifier: InspectorExecutionManifestVerifier,
        accounting: InspectorAdmissionAccountingPort,
        input_staging: RegisteredInputStagingPort,
        reader_mapping: ReaderMappingPort,
        attempt_journal: MeasurementAttemptJournalV2,
        attempt_recovery: InspectorAttemptRecoveryPort,
        runtime_parent: MeasurementRuntimeParentPort,
        runtime_cleanup: AttemptLifecycleRuntimePort[MeasurementAttemptBindingV2],
        backend: DockerMeasurementBackend,
        protocol_limits: ProtocolLimitsV1,
        systemd_base_slice: str,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(required_worker_uid) is not int or required_worker_uid < 0:
            raise ValueError("worker UID must be a nonnegative integer")
        if not systemd_base_slice.endswith(".slice") or "/" in systemd_base_slice:
            raise ValueError("fixed systemd base slice is required")
        self._uid = required_worker_uid
        self._catalog = catalog
        self._verifier = verifier
        self._accounting = accounting
        self._staging = input_staging
        self._mapping = reader_mapping
        self._journal = attempt_journal
        self._parent = runtime_parent
        self._runtime = runtime_cleanup
        self._backend = backend
        self._limits = ProtocolLimitsV1.model_validate(protocol_limits.__dict__)
        self._slice = systemd_base_slice
        self._monotonic = monotonic
        self._health_lock = threading.Lock()
        self._closed = False
        self._quarantine: list[_AttemptState] = []
        try:
            attempt_recovery.recover_startup()
        except Exception as exc:
            raise InspectorSandboxUnavailable("measurement recovery unavailable") from exc

    def _latch(self) -> None:
        with self._health_lock:
            self._closed = True

    def _available(self) -> bool:
        with self._health_lock:
            return not self._closed

    def _retain(self, state: _AttemptState) -> None:
        # Keep ownership (including accounting) even if a retain operation fails.
        if not state.retained:
            state.retained = True
            with self._health_lock:
                self._quarantine.append(state)
                self._closed = True
            if state.sealed is not None:
                state.sealed.relinquish_for_recovery()
            elif state.mutable is not None:
                state.mutable.relinquish_for_recovery()

    def _coordinator(
        self, state: _AttemptState, deadline: ProtocolDeadline
    ) -> AttemptRuntimeCleanupCoordinator[MeasurementAttemptBindingV2]:
        if state.coordinator is None:
            if state.binding is None or state.parent is None or state.runtime_id is None:
                raise InspectorSandboxUnavailable("exact runtime identity unavailable")
            state.coordinator = AttemptRuntimeCleanupCoordinator(
                journal=self._journal,
                runtime_parent=self._parent,
                runtime_cleanup=self._runtime,
                latch_admission_closed=self._latch,
                attempt=state.binding,
                receipt=state.parent,
                runtime_id=state.runtime_id,
                cleanup_deadline_monotonic=deadline.expires_at,
            )
        return state.coordinator

    def _cleanup(
        self, state: _AttemptState, deadline: ProtocolDeadline, *, disposition: str
    ) -> None:
        if state.cleaned or not state.intended:
            return
        assert state.binding is not None
        if state.runtime_id is not None:
            self._coordinator(state, deadline).quiesce_and_remove(disposition=disposition)
        else:
            self._journal.cleanup_required(state.binding.attempt_nonce, disposition=disposition)
        if state.parent is not None and not self._parent.stop_exact(
            binding=state.binding, receipt=state.parent
        ):
            raise InspectorSandboxUnavailable("exact parent cleanup unavailable")
        if state.sealed is not None:
            state.sealed.abort()
            state.sealed = None
        elif state.mutable is not None:
            state.mutable.abort()
            state.mutable = None
        if state.allocation is None:
            raise InspectorSandboxUnavailable("registered allocation receipt unavailable")
        self._staging.finalize_registered_cleanup(
            plan=state.binding.staging, receipt=state.allocation
        )
        self._journal.cleaned(state.binding.attempt_nonce)
        state.cleaned = True

    def _failure(self, state: _AttemptState, deadline: ProtocolDeadline) -> None:
        if not state.intended or state.cleaned:
            if state.binding is not None and not state.intended:
                self._latch()
            return
        assert state.binding is not None
        try:
            uncertain, state.runtime_id, state.parent = reconcile_inflight_creation(
                attempt=state.binding,
                journal=self._journal,
                runtime_parent_port=self._parent,
                runtime_cleanup=self._runtime,
                latch_admission_closed=self._latch,
                retain_for_recovery=lambda: self._retain(state),
                runtime_id=state.runtime_id,
                runtime_parent=state.parent,
                parent_creating=state.parent_creating,
                container_creating=state.container_creating,
            )
            if uncertain:
                return
            self._cleanup(state, deadline, disposition="BACKEND_FAILED")
        except Exception:
            self._latch()
            with suppress(Exception):
                self._retain(state)
            with suppress(Exception):
                self._journal.cleanup_failed(
                    state.binding.attempt_nonce, reason="REGISTERED_CLEANUP_UNAVAILABLE"
                )

    def handle_connection(self, connection: socket.socket) -> None:
        state = _AttemptState()
        cancellation = _SocketCancellation(connection)
        authority_check: Callable[[], object] | None = None
        authority_lost = threading.Event()

        def execution_is_cancelled() -> bool:
            if authority_lost.is_set() or not self._available() or cancellation.is_cancelled():
                return True
            if authority_check is not None:
                try:
                    # The catalog's pinned bounded read and signature/revocation
                    # checks share the original request deadline. Never renew it
                    # or let transient authority loss revive this attempt.
                    authority_check()
                except Exception:
                    authority_lost.set()
                    return True
            # A monitor may record loss while this admission is in flight.
            # Its sticky verdict always wins over an older successful read.
            return authority_lost.is_set() or not self._available() or cancellation.is_cancelled()

        receiver = MeasurementRequestReceiverV2(
            connection,
            self._limits,
            wait_is_current=lambda: not execution_is_cancelled(),
            heartbeat_interval_millis=25,
            monotonic=self._monotonic,
        )
        deadline = receiver.deadline
        try:
            if not self._available():
                return
            peer = connection.getsockopt(
                socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")
            )
            if struct.unpack("3i", peer)[1] != self._uid:
                return
            request = receiver.read_header()

            def admit() -> MeasurementAdmissionV2:
                return admit_measurement_request(
                    request,
                    catalog=self._catalog,
                    verifier=self._verifier,
                    limits=self._limits,
                    deadline=deadline,
                )

            admission = admit()
            authority_check = admit
            limits = admission.effective_limits
            receiver.restrict_total_duration_millis(limits.max_wall_time_millis)
            state.reservation = self._accounting.reserve(
                request_units=1,
                concurrency_units=1,
                spool_bytes=request.inputs[0].observed_size_bytes,
                deadline_monotonic=deadline.expires_at,
            )
            deadline.remaining()
            if state.reservation is None:
                raise InspectorSandboxUnavailable("measurement capacity unavailable")
            reader = self._mapping.resolve_exact(
                runtime_uid=admission.manifest.body.runtime_uid,
                runtime_gid=admission.manifest.body.runtime_gid,
                supplementary_groups=admission.manifest.body.supplementary_groups,
                deadline_monotonic=deadline.expires_at,
            )
            deadline.remaining()
            if not isinstance(reader, MappedInspectorReaderV1):
                raise InspectorSandboxUnavailable("signed reader mapping unavailable")
            fixed_limits = FixedRuntimeLimitsV1(
                **{
                    name: getattr(limits, name)
                    for name in (
                        "max_memory_bytes",
                        "max_workspace_bytes",
                        "max_output_bytes",
                        "max_wall_time_millis",
                        "max_pids",
                        "cpu_period_micros",
                        "cpu_quota_micros",
                        "max_log_bytes",
                        "max_cpu_seconds",
                    )
                }
            )
            state.binding = new_measurement_attempt_binding(
                request=request,
                manifest=admission.manifest,
                root=self._staging.private_root_identity(),
                systemd_base_slice=self._slice,
                cpu_budget_counter=cpu_seconds_to_counter_budget(
                    limits.max_cpu_seconds, CpuCounterUnitV1.CPU_USEC
                ),
                allocation_nonce=secrets.token_hex(16),
            )
            self._journal.intend(state.binding)
            state.intended = True
            state.mutable, state.allocation = self._staging.begin_registered(
                plan=state.binding.staging,
                maximum_bytes=request.inputs[0].observed_size_bytes,
                deadline_monotonic=deadline.expires_at,
            )
            self._journal.staging_allocated(request.attempt_nonce, state.allocation)
            receiver.read_primary(_DeadlineBoundedInputStagingSink(state.mutable))
            state.sealed = state.mutable.seal_for_reader(
                expected_sha256=request.inputs[0].observed_sha256,
                expected_size_bytes=request.inputs[0].observed_size_bytes,
                reader=reader,
                supplementary_groups=admission.manifest.body.supplementary_groups,
                deadline_monotonic=deadline.expires_at,
            )
            state.mutable = None
            bind = state.sealed.prepare_read_only_bind(deadline_monotonic=deadline.expires_at)
            self._journal.input_bound(
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
            refreshed = admit()
            configuration = build_fixed_container_configuration(
                manifest=refreshed.manifest,
                limits=fixed_limits,
                input_bind=state.sealed.prepare_read_only_bind(
                    deadline_monotonic=deadline.expires_at
                ),
            )
            self._journal.runtime_parent_creating(request.attempt_nonce)
            state.parent_creating = True
            state.parent = self._parent.bind_before_create(
                binding=state.binding, configuration=configuration
            )
            self._journal.runtime_parent_bound(request.attempt_nonce, state.parent)
            state.parent_creating = False
            admit()
            self._journal.container_creating(request.attempt_nonce)
            state.container_creating = True
            created = self._backend.create(
                request=request,
                binding=state.binding,
                manifest=refreshed.manifest,
                configuration=configuration,
                staged_input=state.sealed,
                deadline_monotonic=deadline.expires_at,
            )
            state.runtime_id = created.runtime_id
            self._journal.container_bound(request.attempt_nonce, state.runtime_id)
            state.container_creating = False
            coordinator = self._coordinator(state, deadline)
            admit()
            state.active = self._backend.open_started(
                request=request,
                binding=state.binding,
                manifest=refreshed.manifest,
                configuration=configuration,
                staged_input=state.sealed,
                runtime_id=state.runtime_id,
                effective_limits=limits,
                runtime_parent=state.parent,
                monitor_termination=coordinator.terminate_from_monitor,
                is_cancelled=execution_is_cancelled,
                deadline_monotonic=deadline.expires_at,
            )
            receiver.read_secondary(state.active.secondary_sink)
            cancellation.start_monitor(deadline)
            completed = state.active.complete()
            deadline.remaining()
            admit()
            if not isinstance(completed.runtime_measurement, FixedRuntimeMeasurementV1):
                raise InspectorSandboxUnavailable("final host measurement unavailable")
            measurement = replace(completed.runtime_measurement)
            if (
                measurement.runtime_id != state.runtime_id
                or measurement.counter_unit is not configuration.cpu_counter_unit
                or measurement.budget_counter != configuration.cpu_budget_counter
                or measurement.threshold_exceeded
                or measurement.disposition is not RuntimeControlDispositionV1.COMPLETED
            ):
                raise InspectorSandboxUnavailable("final host measurement differs")
            result_limits = self._limits.model_copy(
                update={"max_output_bytes": limits.max_output_bytes}
            )
            result = build_measurement_result(
                terminal=completed.terminal,
                request=request,
                manifest=refreshed.manifest,
                limits=result_limits,
            )
            payload = result.canonical_bytes(
                request=request, manifest=refreshed.manifest, limits=result_limits
            )
            state.active.close()
            state.active = None
            self._cleanup(state, deadline, disposition="BACKEND_COMPLETED")
            deadline.remaining()
            admit()
            _write_frame(
                connection,
                payload,
                self._limits,
                deadline,
                wait_is_current=lambda: not execution_is_cancelled(),
                heartbeat_interval_millis=25,
            )
        except Exception:
            self._failure(state, deadline)
        finally:
            cancellation.stop_monitor()
            if state.active is not None:
                try:
                    state.active.close()
                except Exception:
                    self._latch()
            if state.reservation is not None and not state.retained:
                with suppress(Exception):
                    state.reservation.release()
            with suppress(OSError):
                connection.close()
