"""Closed Docker transport for the contained external-measurement V2 grammar.

This adapter neither interprets input bytes nor owns any runtime teardown.  The
launcher journals creation and supplies the one primary mount; this module
transports the secondary directly to the fixed container's anonymous spool.
"""

from __future__ import annotations

import copy
import hashlib
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestV1

from ksi_processing_controller.external_inspector_attempts import RuntimeParentReceiptV1
from ksi_processing_controller.external_inspector_container_protocol import (
    FixedContainerConfigurationV1,
)
from ksi_processing_controller.external_inspector_docker import (
    DockerMultiplexSessionPort,
    DockerRuntimeUnavailable,
    DockerStartedRuntimeVerifierPort,
    RootlessDockerRuntimeAdapter,
)
from ksi_processing_controller.external_inspector_launcher import (
    InspectorBackendCreatedV1,
    InspectorEffectiveLimitsV1,
)
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedByteSinkPort,
    ProtocolDeadline,
    ProtocolViolation,
)
from ksi_processing_controller.external_inspector_runtime import (
    FixedRuntimeMeasurementV1,
    RuntimeControlUnavailable,
    cpu_seconds_to_counter_budget,
)
from ksi_processing_controller.external_measurement_attempts import MeasurementAttemptBindingV2
from ksi_processing_controller.external_measurement_container_protocol import (
    MeasurementContainerFrameLimitsV2,
    MeasurementContainerProtocolViolation,
    build_execute_frame_v2,
    build_prepare_frame_v2,
    build_primary_mount_verified_frame,
    build_secondary_begin_frame,
    build_secondary_staged_frame,
    decode_measurement_container_frame,
    encode_measurement_container_frame,
    validate_terminal_frame_v2,
)
from ksi_processing_controller.external_measurement_protocol import MeasurementLaunchRequestV2


class DockerMeasurementBackendUnavailable(DockerRuntimeUnavailable):
    """The fixed V2 measurement runtime has no valid local execution evidence."""


class DockerRuntimeMeasurementPort(Protocol):
    """Host-only cgroup measurement; image-reported resource data is never accepted."""

    def start(
        self,
        *,
        runtime_id: str,
        attempt: MeasurementAttemptBindingV2,
        runtime_parent: RuntimeParentReceiptV1,
        configuration: FixedContainerConfigurationV1,
        deadline_monotonic: float,
        is_cancelled: Callable[[], bool],
        monitor_termination: Callable[[str], float],
    ) -> DockerActiveMeasurementPort: ...


class DockerActiveMeasurementPort(Protocol):
    """The retained monitor is finalized only after clean attach EOF and wait(0)."""

    def finalized_measurement(self) -> FixedRuntimeMeasurementV1: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class MeasurementBackendCompletedV2:
    """Validated inner terminal and host proof, still internal to the launcher."""

    terminal: dict[str, object]
    runtime_measurement: FixedRuntimeMeasurementV1


class _AttachedMeasurementReaderV2:
    """Read only closed V2 BE32 controls across independently framed Docker stdout."""

    def __init__(
        self,
        session: DockerMultiplexSessionPort,
        *,
        frame_limits: MeasurementContainerFrameLimitsV2,
        maximum_control_bytes: int,
    ) -> None:
        if type(maximum_control_bytes) is not int or maximum_control_bytes <= 0:
            raise DockerMeasurementBackendUnavailable("effective V2 control cap is unavailable")
        self._session = session
        self._frame_limits = frame_limits
        self._maximum_control_bytes = maximum_control_bytes
        self._stdout = bytearray()
        self._stdout_observed = 0
        self._eof = False

    def read_control(self, *, deadline_monotonic: float) -> dict[str, Any]:
        while True:
            if len(self._stdout) >= 4:
                size = struct.unpack(">I", self._stdout[:4])[0]
                if size > self._frame_limits.maximum_frame_bytes:
                    raise DockerMeasurementBackendUnavailable("V2 control frame exceeds its cap")
                total = 4 + size
                if len(self._stdout) >= total:
                    encoded = bytes(self._stdout[:total])
                    del self._stdout[:total]
                    try:
                        return decode_measurement_container_frame(
                            encoded, limits=self._frame_limits
                        )
                    except MeasurementContainerProtocolViolation as exc:
                        raise DockerMeasurementBackendUnavailable(
                            "V2 container control frame is invalid"
                        ) from exc
            if self._eof:
                if self._stdout:
                    raise DockerMeasurementBackendUnavailable("V2 control frame is truncated")
                raise DockerMeasurementBackendUnavailable(
                    "V2 container ended before its control frame"
                )
            self._read_transport_chunk(deadline_monotonic=deadline_monotonic)

    def require_eof(self, *, deadline_monotonic: float) -> None:
        if self._stdout:
            raise DockerMeasurementBackendUnavailable("V2 attach stream has trailing stdout")
        while not self._eof:
            self._read_transport_chunk(deadline_monotonic=deadline_monotonic)
            if self._stdout:
                raise DockerMeasurementBackendUnavailable("V2 attach stream has trailing stdout")

    def _read_transport_chunk(self, *, deadline_monotonic: float) -> None:
        remaining = self._maximum_control_bytes - self._stdout_observed
        if remaining < 0:
            raise DockerMeasurementBackendUnavailable(
                "V2 control output exceeds its cumulative cap"
            )
        frame = self._session.read_frame(
            # Docker's port requires a positive cap. At exact consumption, one
            # byte is enough to distinguish clean EOF from forbidden trailing
            # stdout; any such byte remains outside the accepted budget below.
            maximum_stdout_bytes=remaining if remaining > 0 else 1,
            # The contained protocol has no stderr namespace.  A finite cap
            # keeps the Docker port valid, and any emitted byte is rejected.
            maximum_stderr_bytes=1,
            deadline_monotonic=deadline_monotonic,
        )
        if frame is None:
            self._eof = True
            return
        stream, payload = frame
        if stream == 2:
            raise DockerMeasurementBackendUnavailable("V2 container emitted forbidden stderr")
        if stream != 1 or not payload:
            raise DockerMeasurementBackendUnavailable("V2 Docker attach frame is invalid")
        self._stdout_observed += len(payload)
        if self._stdout_observed > self._maximum_control_bytes:
            raise DockerMeasurementBackendUnavailable(
                "V2 control output exceeds its cumulative cap"
            )
        self._stdout.extend(payload)


class _SecondarySinkV2:
    """One direct bounded stdin segment; it cannot open or name a host file."""

    def __init__(
        self,
        session: DockerMultiplexSessionPort,
        *,
        expected_size_bytes: int,
        expected_sha256: str,
        deadline_monotonic: float,
        is_cancelled: Callable[[], bool],
    ) -> None:
        self._session = session
        self._expected_size_bytes = expected_size_bytes
        self._expected_sha256 = expected_sha256
        self._deadline_monotonic = deadline_monotonic
        self._is_cancelled = is_cancelled
        self._size = 0
        self._digest = hashlib.sha256()
        self._closed = False

    def write_chunk(
        self,
        chunk: bytes,
        *,
        deadline: ProtocolDeadline,
        wait_is_current: Callable[[], bool] | None,
        heartbeat_interval_millis: int | None,
    ) -> None:
        del heartbeat_interval_millis
        if self._closed:
            raise DockerMeasurementBackendUnavailable("V2 secondary stream is already closed")
        if not isinstance(chunk, bytes) or not chunk:
            raise DockerMeasurementBackendUnavailable("V2 secondary stream chunk is invalid")
        if deadline.expires_at > self._deadline_monotonic:
            raise DockerMeasurementBackendUnavailable("V2 secondary stream deadline was extended")
        deadline.remaining()
        if self._is_cancelled() or (wait_is_current is not None and not wait_is_current()):
            raise DockerMeasurementBackendUnavailable("V2 secondary stream authority was lost")
        next_size = self._size + len(chunk)
        if next_size > self._expected_size_bytes:
            raise DockerMeasurementBackendUnavailable("V2 secondary stream exceeds its sealed size")
        self._session.send_stdin(
            chunk,
            deadline_monotonic=min(deadline.expires_at, self._deadline_monotonic),
        )
        self._digest.update(chunk)
        self._size = next_size

    def require_exact_input(self) -> None:
        self._closed = True
        if (
            self._size != self._expected_size_bytes
            or "sha256:" + self._digest.hexdigest() != self._expected_sha256
        ):
            raise DockerMeasurementBackendUnavailable(
                "V2 secondary stream differs from its sealed input"
            )

    def close(self) -> None:
        self._closed = True


class DockerMeasurementActiveV2:
    """One started V2 runtime. Closing releases local handles only; no teardown occurs here."""

    def __init__(
        self,
        *,
        session: DockerMultiplexSessionPort,
        reader: _AttachedMeasurementReaderV2,
        measurement: DockerActiveMeasurementPort,
        secondary_sink: _SecondarySinkV2,
        prepare: dict[str, Any],
        request: MeasurementLaunchRequestV2,
        runtime: RootlessDockerRuntimeAdapter,
        runtime_id: str,
        frame_limits: MeasurementContainerFrameLimitsV2,
        deadline_monotonic: float,
        is_cancelled: Callable[[], bool],
    ) -> None:
        self._session = session
        self._reader = reader
        self._measurement: DockerActiveMeasurementPort | None = measurement
        self.secondary_sink: DeadlineBoundedByteSinkPort = secondary_sink
        self._secondary_sink = secondary_sink
        self._prepare = prepare
        self._request = request
        self._runtime = runtime
        self._runtime_id = runtime_id
        self._frame_limits = frame_limits
        self._deadline_monotonic = deadline_monotonic
        self._is_cancelled = is_cancelled
        self._completed = False
        self._closed = False

    def complete(self) -> MeasurementBackendCompletedV2:
        if self._closed or self._completed:
            raise DockerMeasurementBackendUnavailable("V2 runtime is not active")
        if self._is_cancelled():
            self.close()
            raise DockerMeasurementBackendUnavailable("V2 runtime execution was cancelled")
        try:
            self._secondary_sink.require_exact_input()
            secondary = self._reader.read_control(deadline_monotonic=self._deadline_monotonic)
            completed = self._finalize_if_failed(secondary)
            if completed is not None:
                return completed
            _require_exact_control(
                secondary,
                build_secondary_staged_frame(
                    prepare=self._prepare,
                    actual_size_bytes=self._request.inputs[1].observed_size_bytes,
                    actual_sha256=self._request.inputs[1].observed_sha256,
                ),
            )
            primary = self._reader.read_control(deadline_monotonic=self._deadline_monotonic)
            completed = self._finalize_if_failed(primary)
            if completed is not None:
                return completed
            _require_exact_control(
                primary,
                build_primary_mount_verified_frame(
                    prepare=self._prepare,
                    actual_size_bytes=self._request.inputs[0].observed_size_bytes,
                    actual_sha256=self._request.inputs[0].observed_sha256,
                ),
            )
            if self._is_cancelled():
                raise DockerMeasurementBackendUnavailable("V2 runtime execution was cancelled")
            self._session.send_stdin(
                encode_measurement_container_frame(
                    build_execute_frame_v2(prepare=self._prepare), limits=self._frame_limits
                ),
                deadline_monotonic=self._deadline_monotonic,
            )
            self._session.finish_stdin(deadline_monotonic=self._deadline_monotonic)
            terminal = self._reader.read_control(deadline_monotonic=self._deadline_monotonic)
            return self._finalize_terminal(terminal)
        except Exception:
            self.close()
            raise

    def _finalize_if_failed(self, control: dict[str, Any]) -> MeasurementBackendCompletedV2 | None:
        if control.get("frame") != "FAILED":
            return None
        return self._finalize_terminal(control)

    def _finalize_terminal(self, terminal: dict[str, Any]) -> MeasurementBackendCompletedV2:
        try:
            validated_terminal = validate_terminal_frame_v2(
                terminal, prepare=self._prepare, limits=self._frame_limits
            )
        except MeasurementContainerProtocolViolation as exc:
            raise DockerMeasurementBackendUnavailable("V2 container terminal is invalid") from exc
        self._reader.require_eof(deadline_monotonic=self._deadline_monotonic)
        waited = self._runtime.wait_exact(
            self._runtime_id, deadline_monotonic=self._deadline_monotonic
        )
        if type(waited.get("StatusCode")) is not int or waited["StatusCode"] != 0:
            raise DockerMeasurementBackendUnavailable("V2 container exited without success")
        if self._is_cancelled():
            raise DockerMeasurementBackendUnavailable("V2 runtime execution was cancelled")
        measurement = self._measurement
        if measurement is None:
            raise DockerMeasurementBackendUnavailable("V2 host measurement was already closed")
        runtime_measurement = measurement.finalized_measurement()
        self._measurement = None
        self._completed = True
        return MeasurementBackendCompletedV2(
            terminal=copy.deepcopy(validated_terminal), runtime_measurement=runtime_measurement
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._secondary_sink.close()
        measurement = self._measurement
        self._measurement = None
        try:
            if measurement is not None:
                measurement.close()
        finally:
            self._session.close()


class DockerMeasurementBackend:
    """Create separately, then start the exact V2 grammar after durable binding."""

    def __init__(
        self,
        *,
        runtime: RootlessDockerRuntimeAdapter,
        started_runtime: DockerStartedRuntimeVerifierPort,
        measurements: DockerRuntimeMeasurementPort,
        frame_limits: MeasurementContainerFrameLimitsV2,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(monotonic):
            raise ValueError("V2 backend monotonic clock is required")
        self._runtime = runtime
        self._started_runtime = started_runtime
        self._measurements = measurements
        self._frame_limits = frame_limits
        self._monotonic = monotonic

    def create(
        self,
        *,
        request: MeasurementLaunchRequestV2,
        binding: MeasurementAttemptBindingV2,
        manifest: InspectorExecutionManifestV1,
        configuration: FixedContainerConfigurationV1,
        staged_input: object,
        deadline_monotonic: float,
    ) -> InspectorBackendCreatedV1:
        del staged_input
        _require_active_deadline(deadline_monotonic, monotonic=self._monotonic)
        _validate_request_binding(request=request, binding=binding, manifest=manifest)
        _validate_configuration(
            request=request, binding=binding, manifest=manifest, configuration=configuration
        )
        runtime_id = self._runtime.create_exact(
            configuration=configuration,
            binding=binding,
            deadline_monotonic=deadline_monotonic,
        )
        return InspectorBackendCreatedV1(runtime_id=runtime_id)

    def open_started(
        self,
        *,
        request: MeasurementLaunchRequestV2,
        binding: MeasurementAttemptBindingV2,
        manifest: InspectorExecutionManifestV1,
        configuration: FixedContainerConfigurationV1,
        staged_input: object,
        runtime_id: str,
        effective_limits: InspectorEffectiveLimitsV1,
        runtime_parent: RuntimeParentReceiptV1,
        monitor_termination: Callable[[str], float],
        is_cancelled: Callable[[], bool],
        deadline_monotonic: float,
    ) -> DockerMeasurementActiveV2:
        del staged_input
        _require_active_deadline(deadline_monotonic, monotonic=self._monotonic)
        if is_cancelled():
            raise DockerMeasurementBackendUnavailable("V2 runtime start was cancelled")
        _validate_request_binding(request=request, binding=binding, manifest=manifest)
        _validate_configuration(
            request=request, binding=binding, manifest=manifest, configuration=configuration
        )
        _validate_effective_limits(
            request=request,
            manifest=manifest,
            configuration=configuration,
            effective_limits=effective_limits,
        )
        prepare = build_prepare_frame_v2(request=request, manifest=manifest)
        session = self._runtime.attach_exact(runtime_id, deadline_monotonic=deadline_monotonic)
        measurement: DockerActiveMeasurementPort | None = None
        try:
            session.send_stdin(
                encode_measurement_container_frame(prepare, limits=self._frame_limits),
                deadline_monotonic=deadline_monotonic,
            )
            session.send_stdin(
                encode_measurement_container_frame(
                    build_secondary_begin_frame(prepare=prepare), limits=self._frame_limits
                ),
                deadline_monotonic=deadline_monotonic,
            )
            if is_cancelled():
                raise DockerMeasurementBackendUnavailable("V2 runtime start was cancelled")
            self._runtime.start_after_container_bound(
                runtime_id=runtime_id,
                configuration=configuration,
                binding=binding,
                deadline_monotonic=deadline_monotonic,
            )
            self._started_runtime.verify_exact(
                runtime_id=runtime_id,
                runtime_parent=runtime_parent,
                configuration=configuration,
                deadline_monotonic=deadline_monotonic,
            )
            if is_cancelled():
                raise DockerMeasurementBackendUnavailable("V2 runtime start was cancelled")
            measurement = self._measurements.start(
                runtime_id=runtime_id,
                attempt=binding,
                runtime_parent=runtime_parent,
                configuration=configuration,
                deadline_monotonic=deadline_monotonic,
                is_cancelled=is_cancelled,
                monitor_termination=monitor_termination,
            )
            maximum_control_bytes = min(
                configuration.output_bytes, effective_limits.max_output_bytes
            )
            return DockerMeasurementActiveV2(
                session=session,
                reader=_AttachedMeasurementReaderV2(
                    session,
                    frame_limits=self._frame_limits,
                    maximum_control_bytes=maximum_control_bytes,
                ),
                measurement=measurement,
                secondary_sink=_SecondarySinkV2(
                    session,
                    expected_size_bytes=request.inputs[1].observed_size_bytes,
                    expected_sha256=request.inputs[1].observed_sha256,
                    deadline_monotonic=deadline_monotonic,
                    is_cancelled=is_cancelled,
                ),
                prepare=prepare,
                request=request,
                runtime=self._runtime,
                runtime_id=runtime_id,
                frame_limits=self._frame_limits,
                deadline_monotonic=deadline_monotonic,
                is_cancelled=is_cancelled,
            )
        except MeasurementContainerProtocolViolation as exc:
            if measurement is not None:
                measurement.close()
            session.close()
            raise DockerMeasurementBackendUnavailable("V2 prepare framing is invalid") from exc
        except Exception:
            if measurement is not None:
                measurement.close()
            session.close()
            raise


def _require_exact_control(actual: dict[str, Any], expected: dict[str, Any]) -> None:
    if canonical_json_bytes(actual) != canonical_json_bytes(expected):
        raise DockerMeasurementBackendUnavailable(
            "V2 container control echo differs from authority"
        )


def _require_active_deadline(deadline_monotonic: float, *, monotonic: Callable[[], float]) -> None:
    if type(deadline_monotonic) not in (int, float):
        raise DockerMeasurementBackendUnavailable("V2 runtime deadline is unavailable")
    try:
        ProtocolDeadline.at_expires_at(deadline_monotonic, monotonic=monotonic).remaining()
    except (ProtocolViolation, ValueError) as exc:
        raise DockerMeasurementBackendUnavailable("V2 runtime deadline is unavailable") from exc


def _validate_request_binding(
    *,
    request: MeasurementLaunchRequestV2,
    binding: MeasurementAttemptBindingV2,
    manifest: InspectorExecutionManifestV1,
) -> None:
    request.canonical_bytes()
    if (
        request.operation != binding.operation
        or request.attempt_nonce != binding.attempt_nonce
        or request.fence.worker_instance_id != binding.owner
        or binding.staging.attempt_nonce != binding.attempt_nonce
        or binding.staging.owner != binding.owner
        or request.canonical_input_digest != binding.canonical_input_digest
        or request.execution_manifest_digest != manifest.canonical_body_digest()
        or binding.execution_manifest_digest != manifest.canonical_body_digest()
        or binding.algorithm_build_digest != request.execution_manifest_digest
        or binding.primary_input != request.inputs[0]
        or binding.secondary_input != request.inputs[1]
        or binding.oci_manifest_digest != manifest.body.image_identity.oci_manifest_digest
        or binding.oci_config_digest != manifest.body.image_identity.oci_config_digest
        or binding.backend_profile_digest != manifest.body.backend_profile_digest
        or binding.security_profile_digest != manifest.body.security_profile_digest
        or binding.resource_envelope_digest != manifest.body.resource_envelope_digest
        or binding.inspector_protocol_digest != manifest.body.inspector_protocol_digest
    ):
        raise DockerMeasurementBackendUnavailable("V2 request, binding, or manifest differs")


def _validate_configuration(
    *,
    request: MeasurementLaunchRequestV2,
    binding: MeasurementAttemptBindingV2,
    manifest: InspectorExecutionManifestV1,
    configuration: FixedContainerConfigurationV1,
) -> None:
    if (
        configuration.image_manifest_digest != binding.oci_manifest_digest
        or configuration.image_config_digest != binding.oci_config_digest
        or configuration.image_manifest_digest != manifest.body.image_identity.oci_manifest_digest
        or configuration.image_config_digest != manifest.body.image_identity.oci_config_digest
        or configuration.runtime_uid != manifest.body.runtime_uid
        or configuration.runtime_gid != manifest.body.runtime_gid
        or configuration.runtime_environment != manifest.body.runtime_environment
        or configuration.input_mount.observed_sha256 != request.inputs[0].observed_sha256
        or configuration.input_mount.observed_size_bytes != request.inputs[0].observed_size_bytes
        or configuration.cpu_budget_counter != binding.cpu_budget_counter
    ):
        raise DockerMeasurementBackendUnavailable("V2 fixed runtime configuration differs")
    _validate_signed_resource_bounds(
        request=request, manifest=manifest, configuration=configuration
    )


def _validate_effective_limits(
    *,
    request: MeasurementLaunchRequestV2,
    manifest: InspectorExecutionManifestV1,
    configuration: FixedContainerConfigurationV1,
    effective_limits: InspectorEffectiveLimitsV1,
) -> None:
    _validate_signed_effective_limits(
        request=request, manifest=manifest, effective_limits=effective_limits
    )
    if (
        request.combined_input_bytes > effective_limits.max_input_bytes
        or configuration.memory_bytes != effective_limits.max_memory_bytes
        or configuration.tmpfs_bytes != effective_limits.max_workspace_bytes
        or configuration.output_bytes != effective_limits.max_output_bytes
        or configuration.wall_time_millis != effective_limits.max_wall_time_millis
        or configuration.pids != effective_limits.max_pids
        or configuration.cpu_period_micros != effective_limits.cpu_period_micros
        or configuration.cpu_quota_micros != effective_limits.cpu_quota_micros
        or configuration.log_bytes != effective_limits.max_log_bytes
    ):
        raise DockerMeasurementBackendUnavailable("V2 effective limits differ from fixed runtime")
    try:
        expected_cpu_budget = cpu_seconds_to_counter_budget(
            effective_limits.max_cpu_seconds, configuration.cpu_counter_unit
        )
    except RuntimeControlUnavailable as exc:
        raise DockerMeasurementBackendUnavailable(
            "V2 effective CPU limit differs from fixed runtime"
        ) from exc
    if expected_cpu_budget != configuration.cpu_budget_counter:
        raise DockerMeasurementBackendUnavailable(
            "V2 effective CPU limit differs from fixed runtime"
        )


def _validate_signed_resource_bounds(
    *,
    request: MeasurementLaunchRequestV2,
    manifest: InspectorExecutionManifestV1,
    configuration: FixedContainerConfigurationV1,
) -> None:
    """Reject a fixed host configuration above request/manifest authority before Docker."""

    envelope = request.validation_policy.resource_envelope
    if envelope is None:
        raise DockerMeasurementBackendUnavailable("V2 signed resource authority is unavailable")
    hard = manifest.body.hard_ceilings
    try:
        policy_wall_millis = int(envelope.max_deadline_seconds * 1_000)
        policy_cpu_budget = cpu_seconds_to_counter_budget(
            envelope.max_cpu_seconds, configuration.cpu_counter_unit
        )
    except (OverflowError, RuntimeControlUnavailable, ValueError) as exc:
        raise DockerMeasurementBackendUnavailable(
            "V2 signed resource authority is unavailable"
        ) from exc
    if (
        policy_wall_millis <= 0
        or request.combined_input_bytes
        > min(
            envelope.max_input_bytes,
            envelope.max_streamed_bytes,
            hard.max_input_bytes,
        )
        or configuration.memory_bytes > min(envelope.max_memory_bytes, hard.max_memory_bytes)
        or configuration.tmpfs_bytes > min(envelope.max_workspace_bytes, hard.max_tmpfs_bytes)
        or configuration.output_bytes > min(envelope.max_output_bytes, hard.max_output_bytes)
        or configuration.wall_time_millis > min(policy_wall_millis, hard.max_wall_time_millis)
        or configuration.pids > hard.max_pids
        or configuration.cpu_period_micros != hard.cpu_period_micros
        or configuration.cpu_quota_micros != hard.cpu_quota_micros
        or configuration.log_bytes > hard.max_log_bytes
        or configuration.cpu_budget_counter > policy_cpu_budget
    ):
        raise DockerMeasurementBackendUnavailable(
            "V2 fixed runtime exceeds signed resource authority"
        )


def _validate_signed_effective_limits(
    *,
    request: MeasurementLaunchRequestV2,
    manifest: InspectorExecutionManifestV1,
    effective_limits: InspectorEffectiveLimitsV1,
) -> None:
    """Validate the admission intersection without treating caller agreement as authority."""

    envelope = request.validation_policy.resource_envelope
    if envelope is None:
        raise DockerMeasurementBackendUnavailable("V2 signed resource authority is unavailable")
    hard = manifest.body.hard_ceilings
    try:
        policy_wall_millis = int(envelope.max_deadline_seconds * 1_000)
    except (OverflowError, ValueError) as exc:
        raise DockerMeasurementBackendUnavailable(
            "V2 signed resource authority is unavailable"
        ) from exc
    if (
        policy_wall_millis <= 0
        or effective_limits.max_input_bytes
        > min(
            envelope.max_input_bytes,
            envelope.max_streamed_bytes,
            hard.max_input_bytes,
        )
        or effective_limits.max_memory_bytes > min(envelope.max_memory_bytes, hard.max_memory_bytes)
        or effective_limits.max_workspace_bytes
        > min(envelope.max_workspace_bytes, hard.max_tmpfs_bytes)
        or effective_limits.max_output_bytes > min(envelope.max_output_bytes, hard.max_output_bytes)
        or effective_limits.max_wall_time_millis
        > min(policy_wall_millis, hard.max_wall_time_millis)
        or effective_limits.max_pids > hard.max_pids
        or effective_limits.cpu_period_micros != hard.cpu_period_micros
        or effective_limits.cpu_quota_micros != hard.cpu_quota_micros
        or effective_limits.max_log_bytes > hard.max_log_bytes
        or effective_limits.max_cpu_seconds > envelope.max_cpu_seconds
    ):
        raise DockerMeasurementBackendUnavailable(
            "V2 effective limits exceed signed resource authority"
        )


__all__ = [
    "DockerActiveMeasurementPort",
    "DockerMeasurementActiveV2",
    "DockerMeasurementBackend",
    "DockerMeasurementBackendUnavailable",
    "DockerRuntimeMeasurementPort",
    "MeasurementBackendCompletedV2",
]
