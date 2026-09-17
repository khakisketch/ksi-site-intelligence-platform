"""Closed aggregate-only V2 result codec; Core retains all adjudication authority.

The launcher publishes these bytes only after its durable CLEANED event. Decoding
binds every field to the caller's sealed request and signed manifest, and reuses
the contained terminal semantic checks without exposing its private wire frame.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Self

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import Digest
from ksi_event_contracts.external_relative_volume import ExternalVolumeMetricsV1
from ksi_event_contracts.external_single_volume import ExternalSingleVolumeMetricsV1
from ksi_event_contracts.inspector_execution_manifest import InspectorExecutionManifestV1
from pydantic import ConfigDict, Field, StrictFloat, StrictInt

from ksi_processing_controller.external_inspector_protocol import (
    LocalLeaseFenceV1,
    ProtocolLimitsV1,
    ProtocolViolation,
    decode_json_frame,
)
from ksi_processing_controller.external_measurement_container_protocol import (
    MeasurementContainerFrameLimitsV2,
    build_prepare_frame_v2,
    validate_terminal_frame_v2,
)
from ksi_processing_controller.external_measurement_protocol import (
    MeasurementInputV2,
    MeasurementLaunchRequestV2,
    Text,
)


class CheckpointAggregateV2(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always", allow_inf_nan=False)
    metric_type: Literal["CHECKPOINT_VALIDATION_AGGREGATE_V2"]
    measured_checkpoint_count: StrictInt = Field(gt=0)
    mean_error_m: StrictFloat
    mae_m: StrictFloat = Field(ge=0)
    rmse_m: StrictFloat = Field(ge=0)
    max_abs_error_m: StrictFloat = Field(ge=0)


class RelativeVolumeAggregateV2(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")
    metric_type: Literal["RELATIVE_VOLUME_AGGREGATE_V2"]
    zone_id: Text
    metrics: ExternalVolumeMetricsV1


class SingleVolumeAggregateV2(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")
    metric_type: Literal["SINGLE_VOLUME_AGGREGATE_V2"]
    zone_id: Text
    metrics: ExternalSingleVolumeMetricsV1


AggregateV2 = Annotated[
    CheckpointAggregateV2 | RelativeVolumeAggregateV2 | SingleVolumeAggregateV2,
    Field(discriminator="metric_type"),
]


class MeasurementResultV2(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")
    protocol_version: Literal["external-measurement-result.v2"] = "external-measurement-result.v2"
    status: Literal["COMPLETED", "FAILED"]
    request_id: Text
    attempt_nonce: Text
    canonical_input_digest: Digest
    operation: Literal["CHECKPOINT_VALIDATION", "RELATIVE_VOLUME", "SINGLE_VOLUME"]
    execution_manifest_digest: Digest
    fence: LocalLeaseFenceV1
    inputs: tuple[MeasurementInputV2, MeasurementInputV2]
    aggregate: AggregateV2 | None
    reason: Text | None

    def validate_for(
        self,
        *,
        request: MeasurementLaunchRequestV2,
        manifest: InspectorExecutionManifestV1,
        limits: ProtocolLimitsV1,
    ) -> Self:
        try:
            result = type(self).model_validate(self.__dict__)
            request.canonical_bytes()
            prepare = build_prepare_frame_v2(request=request, manifest=manifest)
            if (
                result.request_id != request.request_id
                or result.attempt_nonce != request.attempt_nonce
                or result.canonical_input_digest != request.canonical_input_digest
                or result.operation != request.operation
                or result.execution_manifest_digest != request.execution_manifest_digest
                or result.fence != request.fence
                or result.inputs != request.inputs
            ):
                raise ValueError("result authority differs")
            terminal = {
                key: prepare[key]
                for key in (
                    "protocolVersion",
                    "requestId",
                    "attemptNonce",
                    "outerCanonicalInputDigest",
                    "prepareDigest",
                    "operation",
                    "executionManifestDigest",
                    "fence",
                )
            }
            terminal["frame"] = result.status
            if result.status == "COMPLETED":
                if result.reason is not None or result.aggregate is None:
                    raise ValueError("completed result shape differs")
                terminal["inputs"] = [
                    i.model_dump(by_alias=True, mode="json") for i in result.inputs
                ]
                terminal["aggregate"] = result.aggregate.model_dump(by_alias=True, mode="json")
            else:
                if result.aggregate is not None or result.reason is None:
                    raise ValueError("failed result shape differs")
                terminal["reason"] = result.reason
            validate_terminal_frame_v2(
                terminal,
                prepare=prepare,
                limits=MeasurementContainerFrameLimitsV2(
                    maximum_frame_bytes=limits.max_header_bytes
                ),
            )
            return result
        except (ValueError, TypeError, RecursionError) as exc:
            raise ProtocolViolation("invalid measurement result") from exc

    def canonical_bytes(
        self,
        *,
        request: MeasurementLaunchRequestV2,
        manifest: InspectorExecutionManifestV1,
        limits: ProtocolLimitsV1,
    ) -> bytes:
        result = self.validate_for(request=request, manifest=manifest, limits=limits)
        payload = canonical_json_bytes(result.model_dump(by_alias=True, mode="json"))
        if len(payload) > min(limits.max_header_bytes, limits.max_output_bytes):
            raise ProtocolViolation("measurement result exceeds frame ceiling")
        return payload


def build_measurement_result(
    *,
    terminal: dict[str, Any],
    request: MeasurementLaunchRequestV2,
    manifest: InspectorExecutionManifestV1,
    limits: ProtocolLimitsV1,
) -> MeasurementResultV2:
    try:
        prepare = build_prepare_frame_v2(request=request, manifest=manifest)
        validated = validate_terminal_frame_v2(
            terminal,
            prepare=prepare,
            limits=MeasurementContainerFrameLimitsV2(maximum_frame_bytes=limits.max_header_bytes),
        )
        result = MeasurementResultV2.model_validate(
            {
                "status": validated["frame"],
                "requestId": request.request_id,
                "attemptNonce": request.attempt_nonce,
                "canonicalInputDigest": request.canonical_input_digest,
                "operation": request.operation,
                "executionManifestDigest": request.execution_manifest_digest,
                "fence": request.fence,
                "inputs": request.inputs,
                "aggregate": validated.get("aggregate"),
                "reason": validated.get("reason"),
            }
        )
        return result.validate_for(request=request, manifest=manifest, limits=limits)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ProtocolViolation("invalid measurement terminal") from exc


def decode_measurement_result(
    payload: bytes,
    *,
    request: MeasurementLaunchRequestV2,
    manifest: InspectorExecutionManifestV1,
    limits: ProtocolLimitsV1,
) -> MeasurementResultV2:
    try:
        result = MeasurementResultV2.model_validate(decode_json_frame(payload, limits))
        if payload != result.canonical_bytes(request=request, manifest=manifest, limits=limits):
            raise ProtocolViolation("measurement result must use canonical JSON")
        return result
    except (ValueError, TypeError, RecursionError) as exc:
        raise ProtocolViolation("invalid measurement result") from exc
