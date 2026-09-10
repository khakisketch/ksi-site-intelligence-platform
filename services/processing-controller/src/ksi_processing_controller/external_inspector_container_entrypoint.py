"""Fixed in-image entrypoint for the closed external-inspector protocol.

This is the sole production decoder caller.  It accepts no command-line input,
uses only the fixed mounted artifact and private workspace paths, and exchanges
the narrow canonical frame sequence with the Task 4A Docker backend.  It has no
Core, UDS, daemon, Docker, or host-identity authority.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO

import rasterio
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    ExternalValidationPolicyV1,
    PolicyStatus,
    ResourceEnvelopeV1,
)
from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestBodyV1
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from rasterio._err import CPLE_BaseError
from rasterio.enums import ColorInterp
from rasterio.errors import RasterioError

from ksi_processing_controller.external_geotiff_inspector import inspect_synthetic_sealed_geotiff
from ksi_processing_controller.external_geotiff_profile import external_geotiff_profile_digest_v1
from ksi_processing_controller.external_inspector_container_protocol import (
    ContainerInnerFrameLimitsV1,
    ContainerInnerProtocolViolation,
    build_execute_frame,
    compiled_inner_protocol_digest_v1,
    compiled_security_profile_digest_v1,
    decode_inner_frame,
    encode_inner_frame,
    validate_prepare_frame,
)
from ksi_processing_controller.external_inspector_protocol import SealedByteBindingV1
from ksi_processing_controller.external_sanitized_raster import (
    SanitizedRasterError,
    sanitize_measured_ortho,
)

_PROTOCOL_VERSION = "inspector-container.v1"
_FIXED_INPUT_PATH = Path("/input/artifact.tif")
_FIXED_WORKSPACE = Path("/work")
_FAILED_REASONS = frozenset(
    {
        "UNSUPPORTED_RASTER",
        "MALFORMED_TIFF",
        "AMBIGUOUS_GEOREFERENCE",
        "UNSAFE_EXTERNAL_REFERENCE",
        "RESOURCE_LIMIT_EXCEEDED",
        "UNMASKED_NONFINITE_SAMPLE",
        "SANITIZER_FAILED",
    }
)


class ContainerEntrypointError(RuntimeError):
    """The closed entrypoint protocol or fixed local candidate is invalid."""


class ContainerEntrypointIncomplete(RuntimeError):
    """Cancellation stays request-level and cannot produce a terminal artifact outcome."""


def run_container_entrypoint(
    *,
    stdin: BinaryIO,
    stdout: BinaryIO,
    artifact_path: Path = _FIXED_INPUT_PATH,
    workspace: Path = _FIXED_WORKSPACE,
    limits: ContainerInnerFrameLimitsV1,
    is_cancelled: Callable[[], bool] | None = None,
) -> None:
    """Execute exactly PREPARE -> MOUNT_VERIFIED -> EXECUTE -> terminal -> EOF.

    ``stdin`` and ``stdout`` are explicit only for local direct conformance
    tests.  The executable entrypoint always supplies the process standard
    streams and the two fixed container paths.
    """

    _require_not_cancelled(is_cancelled)
    prepare = _read_control(stdin, limits)
    context = _validate_prepared_context(prepare, limits)
    actual_size, actual_sha256 = _mounted_artifact_binding(
        artifact_path,
        expected=context.binding,
        envelope=context.envelope,
    )
    _write_control(
        stdout,
        {
            "protocolVersion": _PROTOCOL_VERSION,
            "frame": "MOUNT_VERIFIED",
            "attemptNonce": context.prepare["attemptNonce"],
            "outerCanonicalInputDigest": context.prepare["outerCanonicalInputDigest"],
            "prepareDigest": context.prepare["prepareDigest"],
            "artifactId": context.binding.artifact_id,
            "actualSizeBytes": actual_size,
            "actualSha256": actual_sha256,
        },
        limits,
    )
    _require_not_cancelled(is_cancelled)
    execute = _read_control(stdin, limits)
    expected_execute = build_execute_frame(prepare=context.prepare)
    if canonical_json_bytes(execute) != canonical_json_bytes(expected_execute):
        raise ContainerEntrypointError("EXECUTE frame differs from PREPARE")
    _require_not_cancelled(is_cancelled)

    if context.operation == "INSPECT":
        _run_inspect(
            stdout=stdout,
            context=context,
            artifact_path=artifact_path,
            limits=limits,
            is_cancelled=is_cancelled,
        )
        return
    _run_sanitize(
        stdout=stdout,
        context=context,
        artifact_path=artifact_path,
        workspace=workspace,
        limits=limits,
        is_cancelled=is_cancelled,
    )


def main() -> int:
    """Run only the fixed container process contract; caller-selected argv is forbidden."""

    limits = ContainerInnerFrameLimitsV1(
        maximum_frame_bytes=128 * 1024,
        maximum_stderr_bytes=0,
    )
    try:
        run_container_entrypoint(
            stdin=sys.stdin.buffer,
            stdout=sys.stdout.buffer,
            artifact_path=_FIXED_INPUT_PATH,
            workspace=_FIXED_WORKSPACE,
            limits=limits,
        )
    except (ContainerEntrypointError, ContainerEntrypointIncomplete):
        return 2
    return 0


class _PreparedContext:
    __slots__ = ("binding", "envelope", "manifest", "operation", "policy", "prepare")

    binding: SealedByteBindingV1
    envelope: ResourceEnvelopeV1
    manifest: InspectorExecutionManifestBodyV1
    operation: str
    policy: ExternalValidationPolicyV1
    prepare: dict[str, Any]

    def __init__(
        self,
        *,
        prepare: dict[str, Any],
        binding: SealedByteBindingV1,
        policy: ExternalValidationPolicyV1,
        manifest: InspectorExecutionManifestBodyV1,
    ) -> None:
        self.prepare = prepare
        self.binding = binding
        self.policy = policy
        self.manifest = manifest
        envelope = policy.resource_envelope
        if envelope is None:
            raise ContainerEntrypointError("PREPARE has no finite resource envelope")
        self.envelope = envelope
        self.operation = prepare["operation"]


def _validate_prepared_context(
    prepare: dict[str, Any], limits: ContainerInnerFrameLimitsV1
) -> _PreparedContext:
    expected_fields = {
        "protocolVersion",
        "frame",
        "attemptNonce",
        "outerCanonicalInputDigest",
        "operation",
        "sealedByteBinding",
        "policy",
        "executionManifestBody",
        "executionManifestDigest",
        "prepareDigest",
    }
    if set(prepare) != expected_fields:
        raise ContainerEntrypointError("PREPARE fields are not closed")
    try:
        validate_prepare_frame(prepare, expected=prepare, limits=limits)
        policy = ExternalValidationPolicyV1.model_validate(prepare["policy"])
        manifest = InspectorExecutionManifestBodyV1.model_validate(
            prepare["executionManifestBody"]
        )
        binding = SealedByteBindingV1.model_validate(prepare["sealedByteBinding"])
    except (ContainerInnerProtocolViolation, TypeError, ValueError) as exc:
        raise ContainerEntrypointError("PREPARE frame is invalid") from exc
    if (
        policy.model_dump(by_alias=True, mode="json") != prepare["policy"]
        or manifest.model_dump(by_alias=True, mode="json") != prepare["executionManifestBody"]
        or binding.model_dump(by_alias=True, mode="json") != prepare["sealedByteBinding"]
    ):
        raise ContainerEntrypointError("PREPARE nested records are not canonical")
    if (
        prepare["protocolVersion"] != _PROTOCOL_VERSION
        or prepare["frame"] != "PREPARE"
        or not isinstance(prepare["attemptNonce"], str)
        or not isinstance(prepare["outerCanonicalInputDigest"], str)
        or prepare["operation"] not in {"INSPECT", "SANITIZE"}
    ):
        raise ContainerEntrypointError("PREPARE shape is invalid")
    if (
        policy.status is not PolicyStatus.ACTIVE
        or policy.resource_envelope is None
        or policy.resource_envelope_digest is None
        or policy.resource_envelope.resource_envelope_digest != policy.resource_envelope_digest
        or policy.parser_build_digest != manifest.canonical_body_digest()
        or prepare["executionManifestDigest"] != manifest.canonical_body_digest()
        or policy.grammar_digest != external_geotiff_profile_digest_v1()
        or manifest.backend_profile_digest != external_geotiff_profile_digest_v1()
        or manifest.security_profile_digest != compiled_security_profile_digest_v1()
        or manifest.inspector_protocol_digest != compiled_inner_protocol_digest_v1()
        or policy.resource_envelope_digest != manifest.resource_envelope_digest
        or manifest.backend != "DEDICATED_ROOTLESS_DOCKER_V1"
    ):
        raise ContainerEntrypointError("PREPARE bindings do not match the fixed profile")
    envelope = policy.resource_envelope
    if (
        binding.observed_size_bytes > envelope.max_input_bytes
        or binding.observed_size_bytes > envelope.max_streamed_bytes
        or binding.observed_size_bytes > manifest.hard_ceilings.max_input_bytes
    ):
        raise ContainerEntrypointError("PREPARE input binding exceeds finite limits")
    return _PreparedContext(
        prepare=prepare,
        binding=binding,
        policy=policy,
        manifest=manifest,
    )


def _run_inspect(
    *,
    stdout: BinaryIO,
    context: _PreparedContext,
    artifact_path: Path,
    limits: ContainerInnerFrameLimitsV1,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    try:
        kind = _classify_raw_model(artifact_path)
        outcome = inspect_synthetic_sealed_geotiff(
            artifact_path,
            artifact_id=context.binding.artifact_id,
            observed_sha256=context.binding.observed_sha256,
            artifact_kind=kind,
            envelope=context.envelope,
            is_cancelled=is_cancelled,
        )
    except _InputRejected as exc:
        outcome = ArtifactInspectionOutcomeV1(
            artifact_id=context.binding.artifact_id,
            observed_sha256=context.binding.observed_sha256,
            outcome=ArtifactOutcome.REJECTED,
            reason=exc.reason,
        )
    _write_control(
        stdout,
        _completed_frame(context=context, outcome=outcome, output_size_bytes=0),
        limits,
    )


def _run_sanitize(
    *,
    stdout: BinaryIO,
    context: _PreparedContext,
    artifact_path: Path,
    workspace: Path,
    limits: ContainerInnerFrameLimitsV1,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    try:
        kind = _classify_raw_model(artifact_path)
        if kind is not ProcessingArtifactKind.ORTHO:
            _write_failed(stdout, context=context, reason="UNSUPPORTED_RASTER", limits=limits)
            return
        _require_empty_private_workspace(workspace)
        candidate = workspace / "sanitized-ortho.tif"
        result = sanitize_measured_ortho(
            source_path=artifact_path,
            source_observed_sha256=context.binding.observed_sha256,
            artifact_id=context.binding.artifact_id,
            output_path=candidate,
            envelope=context.envelope,
            is_cancelled=is_cancelled,
        )
        if result.output_size_bytes > min(
            context.envelope.max_output_bytes,
            context.manifest.hard_ceilings.max_output_bytes,
        ):
            raise SanitizedRasterError("candidate exceeds fixed output ceiling")
        _write_control(
            stdout,
            _completed_frame(
                context=context,
                outcome="SANITIZED",
                output_size_bytes=result.output_size_bytes,
                output_sha256=result.output_sha256,
            ),
            limits,
        )
        _write_exact_candidate(stdout, candidate, result, is_cancelled=is_cancelled)
    except _InputRejected as exc:
        _write_failed(stdout, context=context, reason=exc.reason, limits=limits)
    except SanitizedRasterError:
        _write_failed(stdout, context=context, reason="SANITIZER_FAILED", limits=limits)
    finally:
        _unlink_private_candidate(workspace / "sanitized-ortho.tif")


def _completed_frame(
    *,
    context: _PreparedContext,
    outcome: ArtifactInspectionOutcomeV1 | str,
    output_size_bytes: int,
    output_sha256: str | None = None,
) -> dict[str, Any]:
    frame: dict[str, Any] = {
        "protocolVersion": _PROTOCOL_VERSION,
        "frame": "COMPLETED",
        "attemptNonce": context.prepare["attemptNonce"],
        "outerCanonicalInputDigest": context.prepare["outerCanonicalInputDigest"],
        "prepareDigest": context.prepare["prepareDigest"],
        "operation": context.operation,
        "inspectorBuildDigest": context.manifest.canonical_body_digest(),
        "outcome": outcome
        if isinstance(outcome, str)
        else outcome.model_dump(by_alias=True, mode="json"),
        "outputSizeBytes": output_size_bytes,
    }
    if output_sha256 is not None:
        frame["outputSha256"] = output_sha256
    return frame


def _write_failed(
    stdout: BinaryIO, *, context: _PreparedContext, reason: str, limits: ContainerInnerFrameLimitsV1
) -> None:
    if reason not in _FAILED_REASONS:
        raise ContainerEntrypointError("entrypoint failed reason is not closed")
    _write_control(
        stdout,
        {
            "protocolVersion": _PROTOCOL_VERSION,
            "frame": "FAILED",
            "attemptNonce": context.prepare["attemptNonce"],
            "outerCanonicalInputDigest": context.prepare["outerCanonicalInputDigest"],
            "prepareDigest": context.prepare["prepareDigest"],
            "operation": context.operation,
            "reason": reason,
        },
        limits,
    )


def _classify_raw_model(artifact_path: Path) -> ProcessingArtifactKind:
    try:
        with rasterio.Env(
            PROJ_NETWORK="OFF",
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            GDAL_PAM_ENABLED="NO",
            GDAL_DRIVER_PATH="disable",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS="",
        ), rasterio.open(artifact_path, "r", driver="GTiff") as dataset:
            if (
                dataset.count in {3, 4}
                and dataset.dtypes == ("uint8",) * dataset.count
                and tuple(dataset.colorinterp)
                == (
                    (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
                    if dataset.count == 3
                    else (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha)
                )
            ):
                return ProcessingArtifactKind.ORTHO
            if dataset.count == 1 and dataset.dtypes in {("float32",), ("float64",)}:
                return ProcessingArtifactKind.DSM
    except (CPLE_BaseError, OSError, RasterioError, ValueError) as exc:
        raise _InputRejected("MALFORMED_TIFF") from exc
    raise _InputRejected("UNSUPPORTED_RASTER")


def _mounted_artifact_binding(
    path: Path,
    *,
    expected: SealedByteBindingV1,
    envelope: ResourceEnvelopeV1,
) -> tuple[int, str]:
    try:
        state = os.lstat(path)
    except OSError as exc:
        raise ContainerEntrypointError("mounted artifact is unavailable") from exc
    if not stat.S_ISREG(state.st_mode) or state.st_size != expected.observed_size_bytes:
        raise ContainerEntrypointError("mounted artifact identity differs from PREPARE")
    if state.st_size > min(envelope.max_input_bytes, envelope.max_streamed_bytes):
        raise ContainerEntrypointError("mounted artifact exceeds finite input caps")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise ContainerEntrypointError("mounted artifact cannot be read") from exc
    actual = "sha256:" + digest.hexdigest()
    if actual != expected.observed_sha256:
        raise ContainerEntrypointError("mounted artifact digest differs from PREPARE")
    return state.st_size, actual


def _read_control(stdin: BinaryIO, limits: ContainerInnerFrameLimitsV1) -> dict[str, Any]:
    header = _read_exact(stdin, 4)
    size = int.from_bytes(header, "big")
    if size > limits.maximum_frame_bytes:
        raise ContainerEntrypointError("container control frame exceeds its cap")
    try:
        return decode_inner_frame(header + _read_exact(stdin, size), limits=limits)
    except ContainerInnerProtocolViolation as exc:
        raise ContainerEntrypointError("container control frame is invalid") from exc


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise ContainerEntrypointError("container control frame ended early")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _write_control(
    stdout: BinaryIO,
    frame: dict[str, Any],
    limits: ContainerInnerFrameLimitsV1,
) -> None:
    stdout.write(encode_inner_frame(frame, limits=limits))
    stdout.flush()


def _write_exact_candidate(
    stdout: BinaryIO,
    candidate: Path,
    result: Any,
    *,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    digest = hashlib.sha256()
    written = 0
    try:
        with candidate.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                _require_not_cancelled(is_cancelled)
                stdout.write(chunk)
                digest.update(chunk)
                written += len(chunk)
        stdout.flush()
    except OSError as exc:
        raise ContainerEntrypointError("private candidate cannot be streamed") from exc
    actual = "sha256:" + digest.hexdigest()
    if written != result.output_size_bytes or actual != result.output_sha256:
        raise ContainerEntrypointError("private candidate changed before streaming")


def _require_empty_private_workspace(workspace: Path) -> None:
    try:
        state = os.lstat(workspace)
    except OSError as exc:
        raise ContainerEntrypointError("private workspace is unavailable") from exc
    if (
        not stat.S_ISDIR(state.st_mode)
        or state.st_uid != os.geteuid()
        or stat.S_IMODE(state.st_mode) != 0o700
        or any(workspace.iterdir())
    ):
        raise ContainerEntrypointError("private workspace is not an empty owner-only directory")


def _unlink_private_candidate(candidate: Path) -> None:
    try:
        state = os.lstat(candidate)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise ContainerEntrypointError("private candidate cleanup is unavailable") from exc
    if not stat.S_ISREG(state.st_mode):
        raise ContainerEntrypointError("private workspace candidate identity is uncertain")
    try:
        candidate.unlink()
    except OSError as exc:
        raise ContainerEntrypointError("private candidate cleanup failed") from exc


def _require_not_cancelled(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise ContainerEntrypointIncomplete("container entrypoint cancelled")


class _InputRejected(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


if __name__ == "__main__":  # pragma: no cover - console-script path
    raise SystemExit(main())


__all__ = [
    "ContainerEntrypointError",
    "ContainerEntrypointIncomplete",
    "main",
    "run_container_entrypoint",
]
