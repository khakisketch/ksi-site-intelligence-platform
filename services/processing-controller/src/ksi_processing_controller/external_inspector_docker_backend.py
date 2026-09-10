"""Closed Docker-backed inspector lifecycle over the fixed inner frame protocol.

The module performs no parser classification or sanitizer semantics.  It owns
only the launcher-to-entrypoint ordering, exact attach framing, direct bounded
spooling, and host-observed runtime measurement handoff.
"""

from __future__ import annotations

import hashlib
import re
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from typing import Literal, Protocol

from ksi_event_contracts.external_artifact_validation import ArtifactInspectionOutcomeV1
from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestV1

from ksi_processing_controller.external_inspector_attempts import (
    AttemptBindingV1,
    RuntimeParentReceiptV1,
)
from ksi_processing_controller.external_inspector_container_protocol import (
    ContainerInnerFrameLimitsV1,
    ContainerInnerProtocolViolation,
    FixedContainerConfigurationV1,
    build_execute_frame,
    build_prepare_frame,
    decode_inner_frame,
    encode_inner_frame,
    validate_mount_verified_frame,
)
from ksi_processing_controller.external_inspector_docker import (
    DockerMultiplexSessionPort,
    DockerRuntimeUnavailable,
    DockerStartedRuntimeVerifierPort,
    RootlessDockerRuntimeAdapter,
)
from ksi_processing_controller.external_inspector_launcher import (
    InspectorBackendCompletedV1,
    InspectorBackendCreatedV1,
    InspectorEffectiveLimitsV1,
    InspectorLaunchRequestV1,
    InspectorStagedBytesPort,
)
from ksi_processing_controller.external_inspector_protocol import (
    DeadlineBoundedBytesReader,
    ProtocolDeadline,
)
from ksi_processing_controller.external_inspector_runtime import FixedRuntimeMeasurementV1
from ksi_processing_controller.external_inspector_staging import InspectorSealedInputPort


class DockerBackendUnavailable(DockerRuntimeUnavailable):
    """The fixed entrypoint protocol or its local runtime evidence is unavailable."""


@dataclass(frozen=True, slots=True)
class _TerminalMetadata:
    outcome: ArtifactInspectionOutcomeV1 | Literal["SANITIZED"]
    output_size_bytes: int
    output_sha256: str | None


_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_FAILED_REASON = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


class _AttachedProtocolReader:
    """Bounded byte-stream decoder above Docker's independently chunked stdout.

    Docker multiplex frame boundaries are transport details.  The inner BE32
    control frames may be split or coalesced, while SANITIZE bytes are copied
    from the same bounded stream without allocating a peer-declared output.
    """

    def __init__(
        self,
        session: DockerMultiplexSessionPort,
        *,
        limits: ContainerInnerFrameLimitsV1,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session = session
        self._limits = limits
        self._stdout = bytearray()
        self._stderr_observed = 0
        self._eof = False
        self._transport_chunk_cap = 2 * (limits.maximum_frame_bytes + 4)
        self._monotonic = monotonic

    def read_control(self, *, deadline_monotonic: float) -> dict[str, object]:
        while True:
            if len(self._stdout) >= 4:
                length = struct.unpack(">I", self._stdout[:4])[0]
                if length > self._limits.maximum_frame_bytes:
                    raise DockerBackendUnavailable("fixed container control frame exceeds its cap")
                total = 4 + length
                if len(self._stdout) >= total:
                    encoded = bytes(self._stdout[:total])
                    del self._stdout[:total]
                    return decode_inner_frame(encoded, limits=self._limits)
            if self._eof:
                if self._stdout:
                    raise DockerBackendUnavailable("fixed container control frame is truncated")
                raise DockerBackendUnavailable("fixed container ended before its required frame")
            self._read_transport_chunk(
                maximum_stdout_bytes=self._transport_chunk_cap,
                deadline_monotonic=deadline_monotonic,
            )

    def copy_exact_output(
        self,
        *,
        target: InspectorStagedBytesPort,
        expected_size: int,
        expected_sha256: str,
        deadline_monotonic: float,
        is_cancelled: Callable[[], bool],
    ) -> None:
        remaining = expected_size
        digest = hashlib.sha256()
        while remaining:
            if not self._stdout:
                if self._eof:
                    raise DockerBackendUnavailable("SANITIZE container output ended early")
                self._read_transport_chunk(
                    maximum_stdout_bytes=min(self._transport_chunk_cap, remaining),
                    deadline_monotonic=deadline_monotonic,
                )
                if not self._stdout:
                    continue
            take = min(remaining, len(self._stdout))
            chunk = bytes(self._stdout[:take])
            del self._stdout[:take]
            target.write_chunk(
                chunk,
                deadline=ProtocolDeadline.at_expires_at(deadline_monotonic, self._monotonic),
                wait_is_current=lambda: not is_cancelled(),
                heartbeat_interval_millis=50,
            )
            digest.update(chunk)
            remaining -= len(chunk)
        if "sha256:" + digest.hexdigest() != expected_sha256:
            raise DockerBackendUnavailable("SANITIZE container output digest differs")

    def require_eof(self, *, deadline_monotonic: float) -> None:
        if self._stdout:
            raise DockerBackendUnavailable("fixed container attach stream has trailing bytes")
        while not self._eof:
            self._read_transport_chunk(
                maximum_stdout_bytes=1,
                deadline_monotonic=deadline_monotonic,
            )
            if self._stdout:
                raise DockerBackendUnavailable("fixed container attach stream has trailing bytes")

    def _read_transport_chunk(
        self, *, maximum_stdout_bytes: int, deadline_monotonic: float
    ) -> None:
        frame = self._session.read_frame(
            maximum_stdout_bytes=maximum_stdout_bytes,
            maximum_stderr_bytes=self._limits.maximum_stderr_bytes - self._stderr_observed,
            deadline_monotonic=deadline_monotonic,
        )
        if frame is None:
            self._eof = True
            return
        stream, payload = frame
        if stream == 1:
            if not payload:
                raise DockerBackendUnavailable("fixed container stdout frame is empty")
            self._stdout.extend(payload)
            return
        if stream != 2:
            raise DockerBackendUnavailable("Docker attach stream kind is invalid")
        self._stderr_observed += len(payload)
        if self._stderr_observed > self._limits.maximum_stderr_bytes:
            raise DockerBackendUnavailable("fixed container stderr exceeds its cap")


class DockerRuntimeMeasurementPort(Protocol):
    """Host-only cgroup controller; never accepts resource data from the image."""

    def start(
        self,
        *,
        runtime_id: str,
        attempt: AttemptBindingV1,
        runtime_parent: RuntimeParentReceiptV1,
        configuration: FixedContainerConfigurationV1,
        deadline_monotonic: float,
        is_cancelled: Callable[[], bool],
        monitor_termination: Callable[[str], float],
    ) -> DockerActiveMeasurementPort: ...


class DockerActiveMeasurementPort(Protocol):
    """Retained measurement lifetime from post-start proof through final pre-remove accounting."""

    def finalized_measurement(self) -> FixedRuntimeMeasurementV1: ...

    def close(self) -> None: ...


class DockerInspectorBackend:
    """Concrete Engine create/attach/start/wait lifecycle for one recorded attempt."""

    def __init__(
        self,
        *,
        runtime: RootlessDockerRuntimeAdapter,
        started_runtime: DockerStartedRuntimeVerifierPort,
        measurements: DockerRuntimeMeasurementPort,
        frame_limits: ContainerInnerFrameLimitsV1,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._runtime = runtime
        self._started_runtime = started_runtime
        self._measurements = measurements
        self._frame_limits = frame_limits
        self._monotonic = monotonic

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
        del request, sealed_input, limits
        if is_cancelled():
            raise DockerBackendUnavailable("runtime create cancelled")
        runtime_id = self._runtime.create_exact(
            configuration=configuration,
            binding=attempt,
            deadline_monotonic=deadline_monotonic,
        )
        return InspectorBackendCreatedV1(runtime_id=runtime_id)

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
    ) -> InspectorBackendCompletedV1:
        del sealed_input
        if is_cancelled():
            raise DockerBackendUnavailable("runtime execution cancelled")
        prepare = build_prepare_frame(
            attempt_nonce=request.attempt_nonce,
            outer_canonical_input_digest=request.canonical_input_digest,
            operation=request.operation.value,
            sealed_byte_binding=request.sealed_byte_binding.model_dump(by_alias=True, mode="json"),
            policy=request.policy,
            manifest=manifest,
            admitted_backend_profile_digest=attempt.backend_profile_digest,
            admitted_security_profile_digest=attempt.security_profile_digest,
            admitted_inner_protocol_digest=attempt.inspector_protocol_digest,
        )
        session = self._runtime.attach_exact(
            created.runtime_id, deadline_monotonic=deadline_monotonic
        )
        attached = _AttachedProtocolReader(
            session, limits=self._frame_limits, monotonic=self._monotonic
        )
        measurement_session: DockerActiveMeasurementPort | None = None
        try:
            session.send_stdin(
                encode_inner_frame(prepare, limits=self._frame_limits),
                deadline_monotonic=deadline_monotonic,
            )
            self._runtime.start_after_container_bound(
                runtime_id=created.runtime_id,
                configuration=configuration,
                binding=attempt,
                deadline_monotonic=deadline_monotonic,
            )
            self._started_runtime.verify_exact(
                runtime_id=created.runtime_id,
                runtime_parent=runtime_parent,
                configuration=configuration,
                deadline_monotonic=deadline_monotonic,
            )
            measurement_session = self._measurements.start(
                runtime_id=created.runtime_id,
                attempt=attempt,
                runtime_parent=runtime_parent,
                configuration=configuration,
                deadline_monotonic=deadline_monotonic,
                is_cancelled=is_cancelled,
                monitor_termination=monitor_termination,
            )
            mount = attached.read_control(deadline_monotonic=deadline_monotonic)
            validate_mount_verified_frame(
                mount,
                prepare=prepare,
                artifact_id=request.sealed_byte_binding.artifact_id,
                actual_size_bytes=request.sealed_byte_binding.observed_size_bytes,
                actual_sha256=request.sealed_byte_binding.observed_sha256,
            )
            if is_cancelled():
                raise DockerBackendUnavailable("runtime execution cancelled")
            session.send_stdin(
                encode_inner_frame(build_execute_frame(prepare=prepare), limits=self._frame_limits),
                deadline_monotonic=deadline_monotonic,
            )
            terminal = attached.read_control(deadline_monotonic=deadline_monotonic)
            maximum_output_bytes = configuration.output_bytes
            if request.operation.value == "SANITIZE":
                maximum_output_bytes = min(limits.max_output_bytes, configuration.output_bytes)
            metadata = _validate_terminal(
                terminal=terminal,
                prepare=prepare,
                manifest=manifest,
                operation=request.operation.value,
                maximum_output_bytes=maximum_output_bytes,
            )
            output_size = metadata.output_size_bytes
            output_sha256 = metadata.output_sha256
            if request.operation.value == "SANITIZE":
                if output_sha256 is None:
                    raise DockerBackendUnavailable("SANITIZE output lacks exact SHA-256")
                if output_staging is None:
                    raise DockerBackendUnavailable("private SANITIZE output spool is unavailable")
                attached.copy_exact_output(
                    target=output_staging,
                    expected_size=output_size,
                    expected_sha256=output_sha256,
                    deadline_monotonic=deadline_monotonic,
                    is_cancelled=is_cancelled,
                )
                # The raw derivative bytes share the same stdout byte stream
                # as the terminal frame.  Drain that exact reader before the
                # spool becomes logically sealed, so coalesced or later
                # stdout/stderr bytes cannot escape the protocol cap.
                attached.require_eof(deadline_monotonic=deadline_monotonic)
                output_staging.finish_bounded(
                    deadline=ProtocolDeadline.at_expires_at(deadline_monotonic, self._monotonic),
                    wait_is_current=lambda: not is_cancelled(),
                    heartbeat_interval_millis=50,
                )
                retain = getattr(output_staging, "retain_for_response", None)
                if callable(retain):
                    retain()
            else:
                attached.require_eof(deadline_monotonic=deadline_monotonic)
            waited = self._runtime.wait_exact(
                created.runtime_id, deadline_monotonic=deadline_monotonic
            )
            if waited.get("StatusCode") != 0:
                raise DockerBackendUnavailable("fixed container exited without success")
            measurement = measurement_session.finalized_measurement()
            measurement_session = None
            return InspectorBackendCompletedV1(
                inspector_build_digest=manifest.parser_build_digest,
                outcome=metadata.outcome,
                output=DeadlineBoundedBytesReader(BytesIO()),
                output_size_bytes=output_size,
                output_sha256=output_sha256,
                output_spooled=request.operation.value == "SANITIZE",
                runtime_id=created.runtime_id,
                runtime_measurement=measurement,
            )
        except ContainerInnerProtocolViolation as exc:
            raise DockerBackendUnavailable("fixed container protocol is invalid") from exc
        finally:
            if measurement_session is not None:
                measurement_session.close()
            session.close()


def _read_inner_stdout(
    session: DockerMultiplexSessionPort,
    *,
    limits: ContainerInnerFrameLimitsV1,
    deadline_monotonic: float,
) -> dict[str, object]:
    return _AttachedProtocolReader(session, limits=limits).read_control(
        deadline_monotonic=deadline_monotonic
    )


def _validate_terminal(
    *,
    terminal: dict[str, object],
    prepare: dict[str, object],
    manifest: InspectorExecutionManifestV1,
    operation: str,
    maximum_output_bytes: int | None = None,
) -> _TerminalMetadata:
    for key in ("attemptNonce", "outerCanonicalInputDigest", "prepareDigest", "operation"):
        if terminal.get(key) != prepare.get(key):
            raise DockerBackendUnavailable("fixed container terminal binding differs from PREPARE")
    if terminal.get("protocolVersion") != "inspector-container.v1":
        raise DockerBackendUnavailable("fixed container protocol version differs")
    common = {
        "protocolVersion",
        "frame",
        "attemptNonce",
        "outerCanonicalInputDigest",
        "prepareDigest",
        "operation",
    }
    if terminal.get("frame") == "FAILED":
        reason = terminal.get("reason")
        if (
            set(terminal) != common | {"reason"}
            or not isinstance(reason, str)
            or _FAILED_REASON.fullmatch(reason) is None
        ):
            raise DockerBackendUnavailable("fixed container failure terminal is invalid")
        raise DockerBackendUnavailable("fixed container reported a typed failure")
    if terminal.get("frame") != "COMPLETED":
        raise DockerBackendUnavailable("fixed container terminal frame is invalid")
    if terminal.get("inspectorBuildDigest") != manifest.parser_build_digest:
        raise DockerBackendUnavailable("fixed container build binding differs")
    output_size = terminal.get("outputSizeBytes")
    if type(maximum_output_bytes) is not int or maximum_output_bytes <= 0:
        raise DockerBackendUnavailable("effective output cap is unavailable")
    if type(output_size) is not int or output_size < 0:
        raise DockerBackendUnavailable("fixed container output size is invalid")
    if operation == "INSPECT":
        if set(terminal) != common | {"inspectorBuildDigest", "outcome", "outputSizeBytes"}:
            raise DockerBackendUnavailable("fixed container terminal fields are not closed")
        if output_size != 0:
            raise DockerBackendUnavailable("INSPECT container returned derivative bytes")
        try:
            outcome = ArtifactInspectionOutcomeV1.model_validate(terminal.get("outcome"))
        except Exception as exc:
            raise DockerBackendUnavailable("fixed container inspection outcome is invalid") from exc
        return _TerminalMetadata(
            outcome=outcome,
            output_size_bytes=0,
            output_sha256=None,
        )
    output_sha256 = terminal.get("outputSha256")
    if (
        set(terminal)
        != common | {"inspectorBuildDigest", "outcome", "outputSizeBytes", "outputSha256"}
        or terminal.get("outcome") != "SANITIZED"
        or output_size <= 0
        or output_size > maximum_output_bytes
        or not isinstance(output_sha256, str)
        or _SHA256.fullmatch(output_sha256) is None
    ):
        raise DockerBackendUnavailable("SANITIZE container terminal binding is invalid")
    return _TerminalMetadata(
        outcome="SANITIZED",
        output_size_bytes=output_size,
        output_sha256=output_sha256,
    )


def _require_attach_eof(
    session: DockerMultiplexSessionPort,
    *,
    limits: ContainerInnerFrameLimitsV1,
    deadline_monotonic: float,
) -> None:
    """Compatibility seam for direct local transport tests.

    The concrete backend retains one reader across phases; this helper only
    proves a freshly supplied stream has a clean transport EOF.
    """
    _AttachedProtocolReader(session, limits=limits).require_eof(
        deadline_monotonic=deadline_monotonic
    )


__all__ = [
    "DockerActiveMeasurementPort",
    "DockerBackendUnavailable",
    "DockerInspectorBackend",
    "DockerRuntimeMeasurementPort",
]
