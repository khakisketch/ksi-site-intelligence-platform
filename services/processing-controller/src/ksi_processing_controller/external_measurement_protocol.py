"""Separate V2 authority-bound two-input protocol; V1 grammar is untouched.

The launcher transports opaque bytes only. A volume algorithmBuildDigest means
exactly the signed execution manifest canonical digest in this protocol; the
old validation policy parserBuildDigest continues to identify source inspection.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, Literal, Self

from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import (
    Digest,
    ExternalValidationPolicyV1,
    PolicyStatus,
)
from ksi_event_contracts.external_evidence import (
    ExternalEvidenceRecordV1,
    ExternalEvidenceValidationRequestV1,
)
from ksi_event_contracts.external_evidence_context import ExternalEvidenceMeasurementContextV1
from ksi_event_contracts.external_relative_volume import (
    ExternalRelativeVolumeExecutionPolicyV1,
    ExternalRelativeVolumeRequestV1,
)
from pydantic import ConfigDict, Field, StrictInt, StringConstraints, model_validator

from ksi_processing_controller.external_inspector_protocol import (
    LocalLeaseFenceV1,
    ProtocolLimitsV1,
    ProtocolViolation,
    decode_json_frame,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class MeasurementInputV2(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")
    role: Literal["TARGET_DSM", "CHECKPOINT_CSV", "BASELINE_DSM", "CURRENT_DSM"]
    artifact_id: Text
    observed_sha256: Digest
    observed_size_bytes: StrictInt = Field(gt=0)


class MeasurementLaunchRequestV2(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")
    protocol_version: Literal["external-measurement-launch.v2"] = "external-measurement-launch.v2"
    operation: Literal["CHECKPOINT_VALIDATION", "RELATIVE_VOLUME"]
    inputs: tuple[MeasurementInputV2, MeasurementInputV2]
    validation_policy: ExternalValidationPolicyV1
    checkpoint_request: ExternalEvidenceValidationRequestV1 | None
    evidence_context: ExternalEvidenceMeasurementContextV1 | None
    volume_request: ExternalRelativeVolumeRequestV1 | None
    volume_execution_policy: ExternalRelativeVolumeExecutionPolicyV1 | None
    volume_evidence_records: tuple[ExternalEvidenceRecordV1, ...] = Field(max_length=64)
    fence: LocalLeaseFenceV1
    attempt_nonce: Text
    canonical_input_digest: Digest | None = None

    @model_validator(mode="after")
    def _exact_bindings(self) -> Self:
        policy = self.validation_policy
        if (
            policy.status is not PolicyStatus.ACTIVE
            or policy.policy_digest is None
            or policy.resource_envelope is None
            or policy.resource_envelope_digest is None
        ):
            raise ValueError("measurement requires a sealed ACTIVE validation resource policy")
        if self.combined_input_bytes > min(
            policy.resource_envelope.max_input_bytes,
            policy.resource_envelope.max_streamed_bytes,
        ):
            raise ValueError("combined input bytes exceed policy ceiling")
        if self.inputs[1].observed_size_bytes > policy.resource_envelope.max_workspace_bytes:
            raise ValueError("secondary spool exceeds private workspace ceiling")
        if self.operation == "CHECKPOINT_VALIDATION":
            self._checkpoint_bindings()
        else:
            self._volume_bindings()
        if self.canonical_input_digest is not None and self.canonical_input_digest != self.digest():
            raise ValueError("measurement launch canonical digest differs")
        return self

    def _checkpoint_bindings(self) -> None:
        request, context = self.checkpoint_request, self.evidence_context
        if (
            request is None
            or context is None
            or self.volume_request is not None
            or self.volume_execution_policy is not None
            or self.volume_evidence_records
        ):
            raise ValueError("checkpoint operation has conflicting request fields")
        if context.context_digest is None or context.context_digest != context.canonical_digest():
            raise ValueError("checkpoint context must be sealed")
        policy = self.validation_policy
        primary, secondary = self.inputs
        if (
            (primary.role, secondary.role) != ("TARGET_DSM", "CHECKPOINT_CSV")
            or primary.artifact_id != context.target_dsm_artifact_id
            or primary.observed_sha256 != context.target_dsm_observed_sha256
            or secondary.observed_sha256 != context.evidence_observed_sha256
            or secondary.observed_size_bytes != context.evidence_observed_size_bytes
            or request.evidence_manifest_digest != context.evidence_manifest_digest
            or request.subject_digest != context.subject.canonical_digest()
            or request.target_dsm_observed_sha256 != primary.observed_sha256
            or request.policy_digest != context.policy_digest
            or context.policy_digest != policy.policy_digest
            or request.policy_id != policy.policy_id
            or request.policy_version != policy.version
            or context.rule_id not in policy.evidence_rule_ids
            or not context.is_active_at(request.issued_at)
        ):
            raise ValueError("checkpoint input/context/policy bindings differ")

    def _volume_bindings(self) -> None:
        request, execution = self.volume_request, self.volume_execution_policy
        if (
            request is None
            or execution is None
            or self.checkpoint_request is not None
            or self.evidence_context is not None
        ):
            raise ValueError("volume operation has conflicting request fields")
        if (
            request.request_digest is None
            or execution.policy_digest is None
            or request.execution_policy_digest != execution.policy_digest
            or request.validation_policy_digest != self.validation_policy.policy_digest
            or execution.resource_envelope_digest != self.validation_policy.resource_envelope_digest
        ):
            raise ValueError("volume execution bindings differ")
        for supplied, expected, role in zip(
            self.inputs,
            (request.baseline, request.current),
            ("BASELINE_DSM", "CURRENT_DSM"),
            strict=True,
        ):
            if (
                supplied.role != role
                or supplied.artifact_id != expected.dsm_artifact_id
                or supplied.observed_sha256 != expected.observed_sha256
                or supplied.observed_size_bytes != expected.observed_size_bytes
            ):
                raise ValueError("ordered volume input bindings differ")
        if (
            self.volume_evidence_records
            and tuple(record.evidence_record_digest for record in self.volume_evidence_records)
            != request.evidence_record_digests
        ):
            raise ValueError("ordered volume uncertainty evidence differs")
        if self.volume_evidence_records and len(self.volume_evidence_records) != 2:
            raise ValueError("volume uncertainty requires one evidence record per ordered epoch")
        for record, binding in zip(
            self.volume_evidence_records, (request.baseline, request.current), strict=False
        ):
            if (
                record.evidence_record_digest is None
                or record.evidence_record_digest != record.canonical_digest()
            ):
                raise ValueError("volume uncertainty record must be sealed")
            if (
                record.subject_digest != binding.subject.canonical_digest()
                or record.target_dsm_observed_sha256 != binding.observed_sha256
                or record.policy_digest != self.validation_policy.policy_digest
            ):
                raise ValueError("volume evidence record differs from its ordered epoch or policy")

    @property
    def combined_input_bytes(self) -> int:
        return sum(binding.observed_size_bytes for binding in self.inputs)

    @property
    def execution_manifest_digest(self) -> str:
        if self.evidence_context is not None:
            return self.evidence_context.measurement_execution_manifest_digest
        assert self.volume_execution_policy is not None
        return self.volume_execution_policy.algorithm_build_digest

    @property
    def request_id(self) -> str:
        if self.checkpoint_request is not None:
            return self.checkpoint_request.validation_id
        assert self.volume_request is not None
        return self.volume_request.request_id

    def canonical_body(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"canonical_input_digest"})

    def digest(self) -> str:
        return "sha256:" + hashlib.sha256(canonical_json_bytes(self.canonical_body())).hexdigest()

    def sealed(self) -> Self:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"canonical_input_digest": validated.digest()}, deep=True
        )

    def canonical_bytes(self) -> bytes:
        validated = type(self).model_validate(self.__dict__)
        if validated.canonical_input_digest is None:
            raise ProtocolViolation("unsealed measurement header")
        return canonical_json_bytes(validated.model_dump(by_alias=True, mode="json"))


def decode_measurement_header(
    payload: bytes, limits: ProtocolLimitsV1
) -> MeasurementLaunchRequestV2:
    request = MeasurementLaunchRequestV2.model_validate(decode_json_frame(payload, limits))
    if request.canonical_input_digest is None:
        raise ProtocolViolation("unsealed measurement header")
    if request.combined_input_bytes > limits.max_input_bytes:
        raise ProtocolViolation("combined measurement bytes exceed local protocol ceiling")
    if payload != request.canonical_bytes():
        raise ProtocolViolation("measurement header must use exact canonical JSON bytes")
    return request


def compiled_measurement_protocol_body_v2() -> dict[str, Any]:
    schema = MeasurementLaunchRequestV2.model_json_schema(by_alias=True)
    schema["properties"]["canonicalInputDigest"] = {
        "type": "string",
        "pattern": r"^sha256:[0-9a-f]{64}$",
    }
    schema["required"].append("canonicalInputDigest")
    return {
        "contractVersion": "external-measurement-protocol.v2",
        "canonicalization": "ksi-domain-canonical-json-bytes.v1",
        "outerHeader": schema,
        "outerBytes": "PRIMARY_THEN_SECONDARY_EXACT_HASHED_BYTES_THEN_EOF",
        "innerSequence": [
            "PREPARE_V2",
            "SECONDARY_BEGIN",
            "SECONDARY_EXACT_BYTES",
            "SECONDARY_STAGED",
            "PRIMARY_MOUNT_VERIFIED",
            "EXECUTE_V2",
            "COMPLETED_OR_FAILED",
            "EOF",
        ],
        "innerControl": "BE32_LENGTH_CANONICAL_JSON",
        "primaryMount": "/input/artifact.tif",
        "secondary": "ANONYMOUS_PRIVATE_WORKSPACE_SPOOL",
        "stdout": "BOUNDED_AGGREGATE_CONTROL_ONLY",
        "stderr": "BOUNDED_AND_EMPTY_AT_TERMINAL",
    }


def compiled_measurement_protocol_digest_v2() -> str:
    return (
        "sha256:"
        + hashlib.sha256(canonical_json_bytes(compiled_measurement_protocol_body_v2())).hexdigest()
    )


def compiled_volume_config_digest_v2() -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {
                    "algorithm": "EXTERNAL_BASELINE_GRID_VOLUME_V2",
                    "alignment": "BASELINE_GRID_BILINEAR_WITH_MASKED_NODATA",
                    "zoneCoverage": "FULL_ZONE_CELL_CENTERS_INCLUDING_OUTSIDE_RASTERS",
                    "cutFill": "ABS_NEGATIVE_AND_POSITIVE_AFTER_POLICY_THRESHOLD",
                    "uncertainty": "INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1",
                }
            )
        ).hexdigest()
    )


def compiled_measurement_backend_profile_digest_v2() -> str:
    from ksi_processing_controller.external_geotiff_profile import (
        external_geotiff_profile_digest_v1,
    )

    return (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(
                {
                    "contractVersion": "external-measurement-backend-profile.v2",
                    "rasterGrammarDigest": external_geotiff_profile_digest_v1(),
                    "checkpointRule": "CHECKPOINT_NEAREST_PIXEL_LOWER_TIE_V1",
                    "volumeConfigDigest": compiled_volume_config_digest_v2(),
                    "hostParser": False,
                    "secondaryHostMount": False,
                }
            )
        ).hexdigest()
    )
