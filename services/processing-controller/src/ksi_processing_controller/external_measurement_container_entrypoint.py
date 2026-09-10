"""Fixed image entrypoint for contained external checkpoint and volume measures.

The process receives no command-line inputs.  The sole named raster is the
read-only ``/input/artifact.tif`` mount; the second sealed input is copied from
stdin into an unlinked owner-only O_TMPFILE before it can be parsed.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestBodyV1

from ksi_processing_controller.external_measurement_algorithms import (
    MeasurementAlgorithmError,
    MeasurementAlgorithmIncomplete,
    MeasurementWatchdogV2,
    inspect_owned_secondary_dsm,
    inspect_primary_dsm,
    measure_checkpoint_aggregate,
    measure_relative_volume_aggregate,
    preflight_checkpoint_measurement_memory,
    preflight_owned_secondary_dsm_memory,
    preflight_primary_dsm_memory,
    preflight_secondary_stream_memory,
    preflight_volume_measurement_memory,
    verify_owned_secondary_fd,
)
from ksi_processing_controller.external_measurement_container_protocol import (
    FIXED_PRIMARY_INPUT_PATH_V2,
    FIXED_PRIVATE_WORKSPACE_V2,
    MeasurementContainerFrameLimitsV2,
    MeasurementContainerProtocolViolation,
    build_completed_frame_v2,
    build_execute_frame_v2,
    build_failed_frame_v2,
    build_primary_mount_verified_frame,
    build_secondary_begin_frame,
    build_secondary_staged_frame,
    decode_measurement_container_frame,
    encode_measurement_container_frame,
    validate_prepare_frame_v2,
)
from ksi_processing_controller.external_measurement_protocol import MeasurementLaunchRequestV2

_FIXED_INPUT_PATH = Path(FIXED_PRIMARY_INPUT_PATH_V2)
_FIXED_WORKSPACE = Path(FIXED_PRIVATE_WORKSPACE_V2)
_COPY_CHUNK_BYTES = 1024 * 1024


class MeasurementContainerEntrypointError(RuntimeError):
    """The closed image protocol or fixed local capability is malformed."""


class MeasurementContainerEntrypointIncomplete(RuntimeError):
    """Cancellation or a terminal trailing-byte violation cannot publish a result."""


def run_measurement_container_entrypoint(
    *,
    stdin: BinaryIO,
    stdout: BinaryIO,
    artifact_path: Path = _FIXED_INPUT_PATH,
    workspace: Path = _FIXED_WORKSPACE,
    limits: MeasurementContainerFrameLimitsV2,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    """Run the closed V2 image sequence and emit only control-frame aggregates.

    Explicit streams and paths are local direct-conformance seams.  The console
    entrypoint always calls this with process standard streams and fixed paths.
    """

    _require_not_cancelled(is_cancelled)
    prepare = _read_control(stdin, limits)
    try:
        request = validate_prepare_frame_v2(prepare, expected=prepare, limits=limits)
        manifest = InspectorExecutionManifestBodyV1.model_validate(prepare["executionManifestBody"])
        if manifest.model_dump(by_alias=True, mode="json") != prepare["executionManifestBody"]:
            raise MeasurementContainerEntrypointError("manifest body is not canonical")
        envelope = request.validation_policy.resource_envelope
        if envelope is None:
            raise MeasurementContainerEntrypointError("PREPARE_V2 resource envelope is absent")
        envelope = _effective_resource_envelope(envelope, manifest)
        watchdog = MeasurementWatchdogV2.from_envelope(
            envelope,
            maximum_wall_seconds=min(
                envelope.max_deadline_seconds,
                manifest.hard_ceilings.max_wall_time_millis / 1000.0,
            ),
            is_cancelled=is_cancelled,
        )
        _require_effective_caps(request, manifest)
        output_limits = MeasurementContainerFrameLimitsV2(
            maximum_frame_bytes=min(
                limits.maximum_frame_bytes,
                envelope.max_output_bytes,
                manifest.hard_ceilings.max_output_bytes,
            )
        )
    except (MeasurementContainerProtocolViolation, TypeError, ValueError) as exc:
        raise MeasurementContainerEntrypointError("PREPARE_V2 authority is invalid") from exc

    try:
        _run_prepared(
            stdin=stdin,
            stdout=stdout,
            prepare=prepare,
            request=request,
            artifact_path=artifact_path,
            workspace=workspace,
            limits=limits,
            output_limits=output_limits,
            envelope=envelope,
            watchdog=watchdog,
        )
    except MeasurementAlgorithmIncomplete as exc:
        raise MeasurementContainerEntrypointIncomplete("contained measurement incomplete") from exc
    except MeasurementAlgorithmError as exc:
        _write_control(
            stdout,
            build_failed_frame_v2(prepare=prepare, reason=exc.reason),
            limits=output_limits,
        )


def main() -> int:
    """Run only the fixed in-image process contract without argv configuration."""

    try:
        run_measurement_container_entrypoint(
            stdin=sys.stdin.buffer,
            stdout=sys.stdout.buffer,
            artifact_path=_FIXED_INPUT_PATH,
            workspace=_FIXED_WORKSPACE,
            limits=MeasurementContainerFrameLimitsV2(maximum_frame_bytes=128 * 1024),
        )
    except (MeasurementContainerEntrypointError, MeasurementContainerEntrypointIncomplete):
        return 2
    return 0


def _run_prepared(
    *,
    stdin: BinaryIO,
    stdout: BinaryIO,
    prepare: dict[str, Any],
    request: MeasurementLaunchRequestV2,
    artifact_path: Path,
    workspace: Path,
    limits: MeasurementContainerFrameLimitsV2,
    output_limits: MeasurementContainerFrameLimitsV2,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
) -> None:
    watchdog.check()
    begin = _read_control(stdin, limits)
    expected_begin = build_secondary_begin_frame(prepare=prepare)
    if canonical_json_bytes(begin) != canonical_json_bytes(expected_begin):
        raise MeasurementContainerEntrypointError("SECONDARY_BEGIN differs from PREPARE_V2")
    preflight_secondary_stream_memory(
        expected_size_bytes=request.inputs[1].observed_size_bytes,
        envelope=envelope,
    )
    fd = _open_anonymous_spool(workspace)
    try:
        actual_size, actual_sha256 = _copy_exact_secondary(
            stdin,
            fd=fd,
            expected_size=request.inputs[1].observed_size_bytes,
            watchdog=watchdog,
        )
        if (
            actual_size != request.inputs[1].observed_size_bytes
            or actual_sha256 != request.inputs[1].observed_sha256
        ):
            raise MeasurementAlgorithmError("SECONDARY_SPOOL_DIGEST_MISMATCH")
        _write_control(
            stdout,
            build_secondary_staged_frame(
                prepare=prepare,
                actual_size_bytes=actual_size,
                actual_sha256=actual_sha256,
            ),
            limits=output_limits,
        )
        secondary = verify_owned_secondary_fd(
            fd,
            expected=request.inputs[1],
            envelope=envelope,
            watchdog=watchdog,
        )
        primary_memory = preflight_primary_dsm_memory(
            artifact_path,
            expected=request.inputs[0],
            envelope=envelope,
            watchdog=watchdog,
        )
        if request.operation == "CHECKPOINT_VALIDATION":
            assert request.evidence_context is not None
            preflight_checkpoint_measurement_memory(
                secondary_size_bytes=secondary.size_bytes,
                maximum_checkpoint_count=request.evidence_context.maximum_checkpoint_count,
                envelope=envelope,
            )
        else:
            current_memory = preflight_owned_secondary_dsm_memory(
                secondary,
                envelope=envelope,
                watchdog=watchdog,
            )
            preflight_volume_measurement_memory(
                baseline=primary_memory,
                current=current_memory,
                envelope=envelope,
            )
        primary = inspect_primary_dsm(
            artifact_path,
            expected=request.inputs[0],
            envelope=envelope,
            watchdog=watchdog,
        )
        _write_control(
            stdout,
            build_primary_mount_verified_frame(
                prepare=prepare,
                actual_size_bytes=request.inputs[0].observed_size_bytes,
                actual_sha256=request.inputs[0].observed_sha256,
            ),
            limits=output_limits,
        )
        execute = _read_control(stdin, limits)
        if canonical_json_bytes(execute) != canonical_json_bytes(
            build_execute_frame_v2(prepare=prepare)
        ):
            raise MeasurementContainerEntrypointError("EXECUTE_V2 differs from PREPARE_V2")
        if stdin.read(1):
            raise MeasurementContainerEntrypointError("trailing input follows EXECUTE_V2")
        watchdog.check()
        if request.operation == "CHECKPOINT_VALIDATION":
            aggregate = measure_checkpoint_aggregate(
                request,
                primary=primary,
                secondary=secondary,
                envelope=envelope,
                watchdog=watchdog,
            )
        else:
            current = inspect_owned_secondary_dsm(
                secondary,
                envelope=envelope,
                watchdog=watchdog,
            )
            aggregate = measure_relative_volume_aggregate(
                request,
                primary=primary,
                secondary=current,
                envelope=envelope,
                watchdog=watchdog,
            )
        _write_control(
            stdout,
            build_completed_frame_v2(
                prepare=prepare,
                input_bindings=_result_input_bindings(request),
                aggregate=aggregate,
            ),
            limits=output_limits,
        )
    finally:
        try:
            os.close(fd)
        except OSError as exc:
            raise MeasurementContainerEntrypointError("anonymous spool cleanup failed") from exc


def _require_effective_caps(
    request: MeasurementLaunchRequestV2, manifest: InspectorExecutionManifestBodyV1
) -> None:
    envelope = request.validation_policy.resource_envelope
    if envelope is None or (
        request.combined_input_bytes
        > min(
            envelope.max_input_bytes,
            envelope.max_streamed_bytes,
            manifest.hard_ceilings.max_input_bytes,
        )
        or request.inputs[1].observed_size_bytes
        > min(envelope.max_workspace_bytes, manifest.hard_ceilings.max_tmpfs_bytes)
    ):
        raise MeasurementContainerEntrypointError("combined contained input caps are exceeded")


def _effective_resource_envelope(
    envelope: ResourceEnvelopeV1, manifest: InspectorExecutionManifestBodyV1
) -> ResourceEnvelopeV1:
    """Apply the signed image memory ceiling to every contained allocation path."""

    return envelope.model_copy(
        update={
            "max_memory_bytes": min(
                envelope.max_memory_bytes,
                manifest.hard_ceilings.max_memory_bytes,
            ),
            "resource_envelope_digest": None,
        }
    ).sealed()


def _open_anonymous_spool(workspace: Path) -> int:
    try:
        state = os.lstat(workspace)
    except OSError as exc:
        raise MeasurementContainerEntrypointError("private workspace is unavailable") from exc
    if (
        not stat.S_ISDIR(state.st_mode)
        or state.st_uid != os.geteuid()
        or state.st_gid != os.getegid()
        or stat.S_IMODE(state.st_mode) != 0o700
    ):
        raise MeasurementContainerEntrypointError("private workspace identity is invalid")
    try:
        fd = os.open(workspace, os.O_TMPFILE | os.O_RDWR, 0o600)
    except (AttributeError, OSError) as exc:
        raise MeasurementContainerEntrypointError(
            "anonymous secondary spool is unavailable"
        ) from exc
    try:
        state = os.fstat(fd)
        if (
            not stat.S_ISREG(state.st_mode)
            or state.st_nlink != 0
            or stat.S_IMODE(state.st_mode) != 0o600
            or state.st_uid != os.geteuid()
            or state.st_gid != os.getegid()
        ):
            raise MeasurementContainerEntrypointError("anonymous secondary spool is invalid")
    except Exception:
        os.close(fd)
        raise
    return fd


def _copy_exact_secondary(
    stream: BinaryIO,
    *,
    fd: int,
    expected_size: int,
    watchdog: MeasurementWatchdogV2,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    written = 0
    while written < expected_size:
        watchdog.check()
        chunk = stream.read(min(_COPY_CHUNK_BYTES, expected_size - written))
        if not chunk:
            raise MeasurementContainerEntrypointError("secondary byte segment ended early")
        offset = 0
        while offset < len(chunk):
            try:
                count = os.write(fd, chunk[offset:])
            except OSError as exc:
                raise MeasurementContainerEntrypointError(
                    "anonymous secondary spool write failed"
                ) from exc
            if count <= 0:
                raise MeasurementContainerEntrypointError(
                    "anonymous secondary spool write underflow"
                )
            offset += count
        digest.update(chunk)
        written += len(chunk)
    return written, "sha256:" + digest.hexdigest()


def _result_input_bindings(request: MeasurementLaunchRequestV2) -> list[dict[str, Any]]:
    return [
        {
            "role": binding.role,
            "artifactId": binding.artifact_id,
            "observedSha256": binding.observed_sha256,
            "observedSizeBytes": binding.observed_size_bytes,
        }
        for binding in request.inputs
    ]


def _read_control(stream: BinaryIO, limits: MeasurementContainerFrameLimitsV2) -> dict[str, Any]:
    header = _read_exact(stream, 4)
    size = int.from_bytes(header, "big")
    if size > limits.maximum_frame_bytes:
        raise MeasurementContainerEntrypointError("measurement control frame exceeds cap")
    try:
        return decode_measurement_container_frame(
            header + _read_exact(stream, size), limits=limits
        )
    except MeasurementContainerProtocolViolation as exc:
        raise MeasurementContainerEntrypointError("measurement control frame is invalid") from exc


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise MeasurementContainerEntrypointError("measurement control frame ended early")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _write_control(
    stream: BinaryIO, frame: dict[str, Any], *, limits: MeasurementContainerFrameLimitsV2
) -> None:
    stream.write(encode_measurement_container_frame(frame, limits=limits))
    stream.flush()


def _require_not_cancelled(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise MeasurementContainerEntrypointIncomplete("contained measurement cancelled")


if __name__ == "__main__":  # pragma: no cover - console-script path
    raise SystemExit(main())


__all__ = [
    "MeasurementContainerEntrypointError",
    "MeasurementContainerEntrypointIncomplete",
    "main",
    "run_measurement_container_entrypoint",
]
