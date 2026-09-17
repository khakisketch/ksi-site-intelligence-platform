"""Closed inner protocol for the two-input contained measurement image.

The outer runtime transports the second sealed object as opaque bytes.  This
module deliberately models only the image-side exchange: one canonical
``PREPARE_V2`` frame, an exact secondary byte segment, then fixed control
frames and an aggregate-only terminal record.  It has no Docker, UDS, storage,
or Core authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from typing import Any

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_evidence import EvidenceCoreVerdict
from ksi_event_contracts.external_relative_volume import ExternalVolumeMetricsV1
from ksi_event_contracts.external_single_volume import ExternalSingleVolumeMetricsV1
from ksi_event_contracts.inspector_execution_manifest import (
    InspectorExecutionManifestBodyV1,
    InspectorExecutionManifestV1,
)

from ksi_processing_controller.external_measurement_protocol import (
    MeasurementLaunchRequestV2,
    compiled_measurement_backend_profile_digest_v2,
    compiled_measurement_protocol_digest_v2,
)

MEASUREMENT_INNER_PROTOCOL_VERSION_V2 = "external-measurement-container.v2"
FIXED_PRIMARY_INPUT_PATH_V2 = "/input/artifact.tif"
FIXED_PRIVATE_WORKSPACE_V2 = "/work"

_PREPARE_FIELDS = frozenset(
    {
        "protocolVersion",
        "frame",
        "requestId",
        "attemptNonce",
        "outerCanonicalInputDigest",
        "operation",
        "fence",
        "measurementRequest",
        "executionManifestBody",
        "executionManifestDigest",
        "prepareDigest",
    }
)
_TERMINAL_BASE_FIELDS = frozenset(
    {
        "protocolVersion",
        "frame",
        "requestId",
        "attemptNonce",
        "outerCanonicalInputDigest",
        "prepareDigest",
        "operation",
        "executionManifestDigest",
        "fence",
    }
)
_CHECKPOINT_AGGREGATE_FIELDS = frozenset(
    {
        "metricType",
        "measuredCheckpointCount",
        "meanErrorM",
        "maeM",
        "rmseM",
        "maxAbsErrorM",
    }
)
_VOLUME_AGGREGATE_FIELDS = frozenset({"metricType", "zoneId", "metrics"})
_VOLUME_METRIC_FIELDS = frozenset(
    {
        "zoneCellCount",
        "commonValidCellCount",
        "zoneAreaM2",
        "measuredAreaM2",
        "commonValidFraction",
        "cutM3",
        "fillM3",
        "netM3",
        "thresholdM",
        "uncertaintyM3",
        "uncertaintyNote",
    }
)
_TERMINAL_FAILURE_REASONS = frozenset(
    {
        "RESOURCE_LIMIT_EXCEEDED",
        "SECONDARY_SPOOL_UNAVAILABLE",
        "SECONDARY_SPOOL_IDENTITY_MISMATCH",
        "SECONDARY_SPOOL_UNREADABLE",
        "SECONDARY_SPOOL_UNDERFLOW",
        "SECONDARY_SPOOL_DIGEST_MISMATCH",
        "PRIMARY_DSM_REJECTED",
        "SECONDARY_DSM_REJECTED",
        "SECONDARY_DSM_UNSUPPORTED",
        "OPERATION_BINDING_MISMATCH",
        "CHECKPOINT_CRS_MISMATCH",
        "CHECKPOINT_VERTICAL_REFERENCE_MISMATCH",
        "INVALID_CHECKPOINT_CSV",
        "CHECKPOINT_COUNT_OUT_OF_RANGE",
        "INVALID_CHECKPOINT_MEASUREMENT",
        "DSM_NODATA_AT_CHECKPOINT",
        "CHECKPOINT_OUTSIDE_DSM",
        "VOLUME_RASTER_CONTEXT_MISMATCH",
        "VOLUME_CRS_MISMATCH",
        "VOLUME_DSM_ALIGNMENT_FAILED",
        "EMPTY_COMMON_VALID_COVERAGE",
        "UNMASKED_NONFINITE_SAMPLE",
        "VOLUME_EVIDENCE_BINDING_MISMATCH",
        "INVALID_INPUT",
        "INVALID_ZONE",
        "EMPTY_ZONE",
        "OVERSIZED_ZONE",
        "INSUFFICIENT_COMMON_VALID_COVERAGE",
        "INSUFFICIENT_BOUNDARY_COVERAGE",
        "BOUNDARY_SAMPLES_INSUFFICIENT",
    }
)
_SINGLE_VOLUME_METRIC_FIELDS = _VOLUME_METRIC_FIELDS | {
    "baseRoughnessM",
    "boundaryCellCount",
    "boundarySampleCount",
    "boundaryValidFraction",
}
SINGLE_VOLUME_KNOWN_UNCERTAINTY_NOTE = (
    "Validated target-epoch checkpoint RMSE and boundary base roughness were used."
)
SINGLE_VOLUME_UNKNOWN_UNCERTAINTY_NOTE = (
    "Independent target-epoch checkpoint RMSE is unavailable; uncertainty is unknown."
)
_KNOWN_UNCERTAINTY_NOTE = "Independent validated checkpoint RMSE was used for both epochs."
_UNKNOWN_UNCERTAINTY_NOTE = "Independent checkpoint RMSE is unavailable for one or both epochs."


class MeasurementContainerProtocolViolation(ValueError):
    """A measurement-image control frame is malformed, unbound, or reordered."""


@dataclass(frozen=True, slots=True)
class MeasurementContainerFrameLimitsV2:
    """Finite bound for every JSON control frame; raw bytes have their own bind."""

    maximum_frame_bytes: int

    def __post_init__(self) -> None:
        if type(self.maximum_frame_bytes) is not int or self.maximum_frame_bytes <= 0:
            raise ValueError("measurement frame cap must be a positive integer")


def build_prepare_frame_v2(
    *, request: MeasurementLaunchRequestV2, manifest: InspectorExecutionManifestV1
) -> dict[str, Any]:
    """Create the one complete inner authority frame from sealed outer records."""

    request = MeasurementLaunchRequestV2.model_validate(request.__dict__)
    manifest = InspectorExecutionManifestV1.model_validate(manifest.__dict__)
    manifest_digest = manifest.canonical_body_digest()
    if (
        request.canonical_input_digest is None
        or request.execution_manifest_digest != manifest_digest
        or request.validation_policy.resource_envelope is None
        or request.validation_policy.resource_envelope_digest
        != manifest.body.resource_envelope_digest
    ):
        raise MeasurementContainerProtocolViolation("PREPARE authority bindings differ")
    frame: dict[str, Any] = {
        "protocolVersion": MEASUREMENT_INNER_PROTOCOL_VERSION_V2,
        "frame": "PREPARE_V2",
        "requestId": request.request_id,
        "attemptNonce": request.attempt_nonce,
        "outerCanonicalInputDigest": request.canonical_input_digest,
        "operation": request.operation,
        "fence": request.fence.model_dump(by_alias=True, mode="json"),
        "measurementRequest": request.model_dump(by_alias=True, mode="json"),
        "executionManifestBody": manifest.body.model_dump(by_alias=True, mode="json"),
        "executionManifestDigest": manifest_digest,
    }
    frame["prepareDigest"] = _canonical_digest(frame)
    return frame


def validate_prepare_frame_v2(
    frame: dict[str, Any],
    *,
    expected: dict[str, Any],
    limits: MeasurementContainerFrameLimitsV2,
) -> MeasurementLaunchRequestV2:
    """Require exact canonical equality and revalidate nested sealed authority."""

    _require_prepare_shape(frame)
    decoded = decode_measurement_container_frame(
        encode_measurement_container_frame(frame, limits=limits), limits=limits
    )
    if not _strict_json_equal(decoded, frame) or (
        canonical_json_bytes(frame) != canonical_json_bytes(expected)
    ):
        raise MeasurementContainerProtocolViolation("PREPARE_V2 differs from admitted authority")
    body = {key: value for key, value in frame.items() if key != "prepareDigest"}
    if frame["prepareDigest"] != _canonical_digest(body):
        raise MeasurementContainerProtocolViolation("PREPARE_V2 digest is invalid")
    try:
        request = MeasurementLaunchRequestV2.model_validate(frame["measurementRequest"])
        manifest_body = InspectorExecutionManifestBodyV1.model_validate(
            frame["executionManifestBody"]
        )
    except (TypeError, ValueError) as exc:
        raise MeasurementContainerProtocolViolation(
            "PREPARE_V2 nested authority is invalid"
        ) from exc
    if request.canonical_input_digest is None or (
        request.model_dump(by_alias=True, mode="json") != frame["measurementRequest"]
    ):
        raise MeasurementContainerProtocolViolation(
            "PREPARE_V2 request is not canonical and sealed"
        )
    if (
        frame["requestId"] != request.request_id
        or frame["attemptNonce"] != request.attempt_nonce
        or frame["outerCanonicalInputDigest"] != request.canonical_input_digest
        or frame["operation"] != request.operation
        or not _strict_json_equal(
            frame["fence"], request.fence.model_dump(by_alias=True, mode="json")
        )
        or frame["executionManifestDigest"] != request.execution_manifest_digest
        or not _strict_json_equal(
            manifest_body.model_dump(by_alias=True, mode="json"), frame["executionManifestBody"]
        )
        or manifest_body.canonical_body_digest() != request.execution_manifest_digest
        or manifest_body.inspector_protocol_digest != compiled_measurement_protocol_digest_v2()
        or manifest_body.backend_profile_digest != compiled_measurement_backend_profile_digest_v2()
    ):
        raise MeasurementContainerProtocolViolation("PREPARE_V2 request echoes differ")
    return request


def build_secondary_begin_frame(*, prepare: dict[str, Any]) -> dict[str, Any]:
    """Bind the following raw byte segment to the already sealed second input."""

    request = _prepared_request(prepare)
    secondary = request.inputs[1]
    return {
        "protocolVersion": MEASUREMENT_INNER_PROTOCOL_VERSION_V2,
        "frame": "SECONDARY_BEGIN",
        "attemptNonce": request.attempt_nonce,
        "outerCanonicalInputDigest": request.canonical_input_digest,
        "prepareDigest": prepare["prepareDigest"],
        "role": secondary.role,
        "artifactId": secondary.artifact_id,
        "expectedSizeBytes": secondary.observed_size_bytes,
        "expectedSha256": secondary.observed_sha256,
    }


def build_secondary_staged_frame(
    *, prepare: dict[str, Any], actual_size_bytes: int, actual_sha256: str
) -> dict[str, Any]:
    """Echo the single anonymous spool binding after all bytes are accounted for."""

    request = _prepared_request(prepare)
    secondary = request.inputs[1]
    if (
        actual_size_bytes != secondary.observed_size_bytes
        or actual_sha256 != secondary.observed_sha256
    ):
        raise MeasurementContainerProtocolViolation("secondary bytes differ from PREPARE_V2")
    return {
        "protocolVersion": MEASUREMENT_INNER_PROTOCOL_VERSION_V2,
        "frame": "SECONDARY_STAGED",
        "attemptNonce": request.attempt_nonce,
        "outerCanonicalInputDigest": request.canonical_input_digest,
        "prepareDigest": prepare["prepareDigest"],
        "role": secondary.role,
        "artifactId": secondary.artifact_id,
        "actualSizeBytes": actual_size_bytes,
        "actualSha256": actual_sha256,
    }


def build_primary_mount_verified_frame(
    *, prepare: dict[str, Any], actual_size_bytes: int, actual_sha256: str
) -> dict[str, Any]:
    """Echo the one fixed read-only primary mount after byte verification."""

    request = _prepared_request(prepare)
    primary = request.inputs[0]
    if actual_size_bytes != primary.observed_size_bytes or actual_sha256 != primary.observed_sha256:
        raise MeasurementContainerProtocolViolation("primary mount differs from PREPARE_V2")
    return {
        "protocolVersion": MEASUREMENT_INNER_PROTOCOL_VERSION_V2,
        "frame": "PRIMARY_MOUNT_VERIFIED",
        "attemptNonce": request.attempt_nonce,
        "outerCanonicalInputDigest": request.canonical_input_digest,
        "prepareDigest": prepare["prepareDigest"],
        "role": primary.role,
        "artifactId": primary.artifact_id,
        "actualSizeBytes": actual_size_bytes,
        "actualSha256": actual_sha256,
    }


def build_execute_frame_v2(*, prepare: dict[str, Any]) -> dict[str, Any]:
    """EXECUTE_V2 adds no authority beyond the validated prepare frame."""

    request = _prepared_request(prepare)
    return {
        "protocolVersion": MEASUREMENT_INNER_PROTOCOL_VERSION_V2,
        "frame": "EXECUTE_V2",
        "requestId": request.request_id,
        "attemptNonce": request.attempt_nonce,
        "outerCanonicalInputDigest": request.canonical_input_digest,
        "prepareDigest": prepare["prepareDigest"],
        "operation": request.operation,
        "fence": request.fence.model_dump(by_alias=True, mode="json"),
    }


def build_completed_frame_v2(
    *, prepare: dict[str, Any], input_bindings: list[dict[str, Any]], aggregate: dict[str, Any]
) -> dict[str, Any]:
    """Build a bounded aggregate-only terminal frame from fixed execution bindings."""

    request = _prepared_request(prepare)
    frame = _terminal_base(request=request, prepare=prepare) | {
        "frame": "COMPLETED",
        "inputs": input_bindings,
        "aggregate": aggregate,
    }
    _validate_terminal_frame(request=request, prepare=prepare, frame=frame)
    return frame


def build_failed_frame_v2(*, prepare: dict[str, Any], reason: str) -> dict[str, Any]:
    """Typed failures retain authority echoes and deliberately contain no metrics."""

    request = _prepared_request(prepare)
    frame = _terminal_base(request=request, prepare=prepare) | {
        "frame": "FAILED",
        "reason": reason,
    }
    _validate_terminal_frame(request=request, prepare=prepare, frame=frame)
    return frame


def validate_terminal_frame_v2(
    frame: dict[str, Any],
    *,
    prepare: dict[str, Any],
    limits: MeasurementContainerFrameLimitsV2,
) -> dict[str, Any]:
    """Validate an untrusted terminal frame against its admitted PREPARE_V2.

    The outer backend must call this after framing/canonical decoding and before
    it treats a container result as an aggregate measurement.  It intentionally
    accepts neither report-shaped data nor unbounded/raw namespaces.
    """

    request = validate_prepare_frame_v2(prepare, expected=prepare, limits=limits)
    decoded = decode_measurement_container_frame(
        encode_measurement_container_frame(frame, limits=limits), limits=limits
    )
    if not _strict_json_equal(decoded, frame):
        raise MeasurementContainerProtocolViolation("terminal frame is not canonical")
    _validate_terminal_frame(request=request, prepare=prepare, frame=frame)
    return frame


def encode_measurement_container_frame(
    frame: dict[str, Any], *, limits: MeasurementContainerFrameLimitsV2
) -> bytes:
    """Encode exactly one canonical BE32 JSON control frame."""

    payload = canonical_json_bytes(frame)
    if len(payload) > limits.maximum_frame_bytes:
        raise MeasurementContainerProtocolViolation("measurement control frame exceeds cap")
    return struct.pack(">I", len(payload)) + payload


def decode_measurement_container_frame(
    payload: bytes, *, limits: MeasurementContainerFrameLimitsV2
) -> dict[str, Any]:
    """Decode one closed BE32 canonical-JSON control frame without trailing bytes."""

    if len(payload) < 4:
        raise MeasurementContainerProtocolViolation("measurement frame header is truncated")
    length = struct.unpack(">I", payload[:4])[0]
    if length > limits.maximum_frame_bytes or len(payload) != 4 + length:
        raise MeasurementContainerProtocolViolation("measurement frame length is invalid")
    try:
        frame = json.loads(payload[4:])
        is_canonical = isinstance(frame, dict) and canonical_json_bytes(frame) == payload[4:]
    except (
        json.JSONDecodeError,
        TypeError,
        UnicodeDecodeError,
        UnicodeEncodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise MeasurementContainerProtocolViolation("measurement frame JSON is invalid") from exc
    if not is_canonical:
        raise MeasurementContainerProtocolViolation("measurement frame JSON is not canonical")
    return frame


def _terminal_base(
    *, request: MeasurementLaunchRequestV2, prepare: dict[str, Any]
) -> dict[str, Any]:
    return {
        "protocolVersion": MEASUREMENT_INNER_PROTOCOL_VERSION_V2,
        "requestId": request.request_id,
        "attemptNonce": request.attempt_nonce,
        "outerCanonicalInputDigest": request.canonical_input_digest,
        "prepareDigest": prepare["prepareDigest"],
        "operation": request.operation,
        "executionManifestDigest": request.execution_manifest_digest,
        "fence": request.fence.model_dump(by_alias=True, mode="json"),
    }


def _require_exact_result_bindings(
    request: MeasurementLaunchRequestV2, bindings: list[dict[str, Any]]
) -> None:
    expected = [
        {
            "role": item.role,
            "artifactId": item.artifact_id,
            "observedSha256": item.observed_sha256,
            "observedSizeBytes": item.observed_size_bytes,
        }
        for item in request.inputs
    ]
    if (
        type(bindings) is not list
        or len(bindings) != len(expected)
        or any(
            type(actual) is not dict
            or set(actual) != set(expected_item)
            or any(
                type(actual[key]) is not type(expected_item[key])
                or actual[key] != expected_item[key]
                for key in expected_item
            )
            for actual, expected_item in zip(bindings, expected, strict=True)
        )
    ):
        raise MeasurementContainerProtocolViolation(
            "terminal input bindings differ from PREPARE_V2"
        )


def _prepared_request(prepare: dict[str, Any]) -> MeasurementLaunchRequestV2:
    _require_prepare_shape(prepare)
    try:
        request = MeasurementLaunchRequestV2.model_validate(prepare["measurementRequest"])
    except (TypeError, ValueError) as exc:
        raise MeasurementContainerProtocolViolation("PREPARE_V2 request is invalid") from exc
    if request.canonical_input_digest is None:
        raise MeasurementContainerProtocolViolation("PREPARE_V2 request is unsealed")
    if (
        prepare["requestId"] != request.request_id
        or prepare["attemptNonce"] != request.attempt_nonce
        or prepare["outerCanonicalInputDigest"] != request.canonical_input_digest
        or prepare["operation"] != request.operation
        or not _strict_json_equal(
            prepare["fence"], request.fence.model_dump(by_alias=True, mode="json")
        )
        or prepare["executionManifestDigest"] != request.execution_manifest_digest
    ):
        raise MeasurementContainerProtocolViolation("PREPARE_V2 request echoes differ")
    return request


def _require_prepare_shape(prepare: dict[str, Any]) -> None:
    if (
        not isinstance(prepare, dict)
        or set(prepare) != _PREPARE_FIELDS
        or prepare.get("protocolVersion") != MEASUREMENT_INNER_PROTOCOL_VERSION_V2
        or prepare.get("frame") != "PREPARE_V2"
        or any(
            not isinstance(prepare.get(field), str)
            for field in (
                "requestId",
                "attemptNonce",
                "outerCanonicalInputDigest",
                "operation",
                "executionManifestDigest",
                "prepareDigest",
            )
        )
        or not isinstance(prepare.get("fence"), dict)
        or not isinstance(prepare.get("measurementRequest"), dict)
        or not isinstance(prepare.get("executionManifestBody"), dict)
    ):
        raise MeasurementContainerProtocolViolation("PREPARE_V2 frame shape is invalid")


def _validate_terminal_frame(
    *, request: MeasurementLaunchRequestV2, prepare: dict[str, Any], frame: dict[str, Any]
) -> None:
    if not isinstance(frame, dict):
        raise MeasurementContainerProtocolViolation("terminal frame shape is invalid")
    frame_kind = frame.get("frame")
    if not isinstance(frame_kind, str) or frame_kind not in {"COMPLETED", "FAILED"}:
        raise MeasurementContainerProtocolViolation("terminal frame shape is invalid")
    expected = _terminal_base(request=request, prepare=prepare)
    for key, value in expected.items():
        if key not in frame or not _strict_json_equal(frame[key], value):
            raise MeasurementContainerProtocolViolation("terminal authority echoes differ")
    if frame_kind == "FAILED":
        if set(frame) != _TERMINAL_BASE_FIELDS | {"reason"}:
            raise MeasurementContainerProtocolViolation("terminal failed fields are not closed")
        reason = frame["reason"]
        if not isinstance(reason, str) or reason not in _TERMINAL_FAILURE_REASONS:
            raise MeasurementContainerProtocolViolation("terminal failure reason is invalid")
        return
    if set(frame) != _TERMINAL_BASE_FIELDS | {"inputs", "aggregate"}:
        raise MeasurementContainerProtocolViolation("terminal completed fields are not closed")
    _require_exact_result_bindings(request, frame["inputs"])
    _require_terminal_aggregate(request, frame["aggregate"])


def _require_terminal_aggregate(request: MeasurementLaunchRequestV2, aggregate: Any) -> None:
    if not isinstance(aggregate, dict):
        raise MeasurementContainerProtocolViolation("terminal aggregate is invalid")
    if request.operation == "CHECKPOINT_VALIDATION":
        _require_checkpoint_aggregate(request, aggregate)
    elif request.operation == "SINGLE_VOLUME":
        _require_single_volume_aggregate(request, aggregate)
    else:
        _require_volume_aggregate(request, aggregate)


def _require_single_volume_aggregate(
    request: MeasurementLaunchRequestV2, aggregate: dict[str, Any]
) -> None:
    single = request.single_volume_request
    execution = request.single_volume_execution_policy
    if (
        single is None
        or execution is None
        or set(aggregate) != _VOLUME_AGGREGATE_FIELDS
        or aggregate.get("metricType") != "SINGLE_VOLUME_AGGREGATE_V2"
        or aggregate.get("zoneId") != single.zone_snapshot.work_area_id
        or type(aggregate.get("metrics")) is not dict
        or set(aggregate["metrics"]) != _SINGLE_VOLUME_METRIC_FIELDS
    ):
        raise MeasurementContainerProtocolViolation("terminal single-volume aggregate is invalid")
    try:
        metrics = ExternalSingleVolumeMetricsV1.model_validate(aggregate["metrics"])
    except (TypeError, ValueError) as exc:
        raise MeasurementContainerProtocolViolation(
            "terminal single-volume aggregate is invalid"
        ) from exc
    if (
        metrics.model_dump(by_alias=True, mode="json") != aggregate["metrics"]
        or metrics.threshold_m != execution.threshold_m
        or metrics.common_valid_fraction < execution.minimum_common_valid_fraction
        or metrics.boundary_valid_fraction < execution.minimum_boundary_valid_fraction
    ):
        raise MeasurementContainerProtocolViolation(
            "terminal single-volume aggregate is inconsistent"
        )
    rmse = terminal_target_rmse(request)
    if rmse is None:
        if (
            metrics.uncertainty_m3 is not None
            or metrics.uncertainty_note != SINGLE_VOLUME_UNKNOWN_UNCERTAINTY_NOTE
        ):
            raise MeasurementContainerProtocolViolation(
                "terminal single-volume aggregate is inconsistent"
            )
        return
    expected = metrics.measured_area_m2 * math.hypot(metrics.base_roughness_m, rmse)
    if (
        metrics.uncertainty_m3 is None
        or not math.isclose(metrics.uncertainty_m3, expected, rel_tol=1e-12, abs_tol=1e-12)
        or metrics.uncertainty_note != SINGLE_VOLUME_KNOWN_UNCERTAINTY_NOTE
    ):
        raise MeasurementContainerProtocolViolation(
            "terminal single-volume aggregate is inconsistent"
        )


def terminal_target_rmse(request: MeasurementLaunchRequestV2) -> float | None:
    """The one bound target-epoch RMSE, or ``None`` when it is not VALIDATED."""
    single = request.single_volume_request
    records = request.volume_evidence_records
    if single is None or len(records) != 1:
        raise MeasurementContainerProtocolViolation(
            "terminal single-volume aggregate is inconsistent"
        )
    record = records[0]
    payload = record.measurement_payload
    if (
        record.subject_digest != single.target.subject.canonical_digest()
        or record.target_dsm_observed_sha256 != single.target.observed_sha256
        or record.policy_digest != request.validation_policy.policy_digest
    ):
        raise MeasurementContainerProtocolViolation(
            "terminal single-volume aggregate is inconsistent"
        )
    if record.core_verdict is not EvidenceCoreVerdict.VALIDATED or payload is None:
        return None
    return payload.rmse_m


def _require_checkpoint_aggregate(
    request: MeasurementLaunchRequestV2, aggregate: dict[str, Any]
) -> None:
    context = request.evidence_context
    if context is None or set(aggregate) != _CHECKPOINT_AGGREGATE_FIELDS:
        raise MeasurementContainerProtocolViolation("terminal checkpoint aggregate is invalid")
    count = aggregate.get("measuredCheckpointCount")
    values = tuple(aggregate[field] for field in ("meanErrorM", "maeM", "rmseM", "maxAbsErrorM"))
    if (
        aggregate.get("metricType") != "CHECKPOINT_VALIDATION_AGGREGATE_V2"
        or type(count) is not int
        or not context.minimum_checkpoint_count <= count <= context.maximum_checkpoint_count
        or any(type(value) is not float or not math.isfinite(value) for value in values)
    ):
        raise MeasurementContainerProtocolViolation("terminal checkpoint aggregate is invalid")
    mean, mae, rmse, maximum = (float(value) for value in values)
    tolerance = 1e-12
    if abs(mean) > mae + tolerance or mae > rmse + tolerance or rmse > maximum + tolerance:
        raise MeasurementContainerProtocolViolation("terminal checkpoint aggregate is inconsistent")


def _require_volume_aggregate(
    request: MeasurementLaunchRequestV2, aggregate: dict[str, Any]
) -> None:
    volume = request.volume_request
    execution = request.volume_execution_policy
    if (
        volume is None
        or execution is None
        or set(aggregate) != _VOLUME_AGGREGATE_FIELDS
        or aggregate.get("metricType") != "RELATIVE_VOLUME_AGGREGATE_V2"
        or aggregate.get("zoneId") != volume.zone_snapshot.work_area_id
        or type(aggregate.get("metrics")) is not dict
        or set(aggregate["metrics"]) != _VOLUME_METRIC_FIELDS
    ):
        raise MeasurementContainerProtocolViolation("terminal volume aggregate is invalid")
    try:
        metrics = ExternalVolumeMetricsV1.model_validate(aggregate["metrics"])
    except (TypeError, ValueError) as exc:
        raise MeasurementContainerProtocolViolation("terminal volume aggregate is invalid") from exc
    if (
        metrics.model_dump(by_alias=True, mode="json") != aggregate["metrics"]
        or metrics.threshold_m != execution.threshold_m
        or execution.uncertainty_method != "INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1"
        or metrics.common_valid_fraction < execution.minimum_common_valid_fraction
        or metrics.measured_area_m2 < metrics.zone_area_m2 * execution.minimum_common_valid_fraction
    ):
        raise MeasurementContainerProtocolViolation("terminal volume aggregate is inconsistent")
    rmses = _terminal_epoch_rmses(request)
    if rmses is None:
        if (
            metrics.uncertainty_m3 is not None
            or metrics.uncertainty_note != _UNKNOWN_UNCERTAINTY_NOTE
        ):
            raise MeasurementContainerProtocolViolation("terminal volume aggregate is inconsistent")
        return
    expected_uncertainty = metrics.measured_area_m2 * math.hypot(*rmses)
    if (
        metrics.uncertainty_m3 is None
        or not math.isclose(
            metrics.uncertainty_m3,
            expected_uncertainty,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        or metrics.uncertainty_note != _KNOWN_UNCERTAINTY_NOTE
    ):
        raise MeasurementContainerProtocolViolation("terminal volume aggregate is inconsistent")


def _terminal_epoch_rmses(request: MeasurementLaunchRequestV2) -> tuple[float, float] | None:
    volume = request.volume_request
    records = request.volume_evidence_records
    if not records:
        return None
    if volume is None or len(records) != 2:
        raise MeasurementContainerProtocolViolation("terminal volume aggregate is inconsistent")
    rmses: list[float] = []
    for record, binding in zip(records, (volume.baseline, volume.current), strict=True):
        payload = record.measurement_payload
        if (
            record.core_verdict is not EvidenceCoreVerdict.VALIDATED
            or payload is None
            or record.subject_digest != binding.subject.canonical_digest()
            or record.target_dsm_observed_sha256 != binding.observed_sha256
            or record.policy_digest != request.validation_policy.policy_digest
        ):
            raise MeasurementContainerProtocolViolation("terminal volume aggregate is inconsistent")
        rmses.append(payload.rmse_m)
    return rmses[0], rmses[1]


def _canonical_digest(value: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _strict_json_equal(left: Any, right: Any) -> bool:
    """Compare decoded JSON facts without Python's bool/int equivalence loophole."""

    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _strict_json_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _strict_json_equal(actual, expected)
            for actual, expected in zip(left, right, strict=True)
        )
    return left == right


__all__ = [
    "FIXED_PRIMARY_INPUT_PATH_V2",
    "FIXED_PRIVATE_WORKSPACE_V2",
    "MEASUREMENT_INNER_PROTOCOL_VERSION_V2",
    "MeasurementContainerFrameLimitsV2",
    "MeasurementContainerProtocolViolation",
    "build_completed_frame_v2",
    "build_execute_frame_v2",
    "build_failed_frame_v2",
    "build_prepare_frame_v2",
    "build_primary_mount_verified_frame",
    "build_secondary_begin_frame",
    "build_secondary_staged_frame",
    "decode_measurement_container_frame",
    "encode_measurement_container_frame",
    "validate_prepare_frame_v2",
    "validate_terminal_frame_v2",
]
