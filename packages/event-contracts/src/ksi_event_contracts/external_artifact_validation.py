"""Immutable external-artifact inspection, policy, display, and use contracts.

These records bind declared/observed external bytes without representing a
managed ProcessingJob, source bundle, source authority, processing profile, or
Analysis Readiness.  They validate contract shape and immutable bindings only;
Core later authenticates principals, resolves tenant scope, and adjudicates
policy/evidence truth.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import (
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from ksi_event_contracts._base import _CamelModel

_DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
_RFC3339_AWARE_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)"
)

Digest = Annotated[str, Field(pattern=_DIGEST_PATTERN)]
_BoundedText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
_Reason = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]{0,127}$"
    ),
]
_Remediation = _Reason
_LongBoundedText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_096)
]


def _require_aware_datetime_wire_value(value: object, field_name: str) -> object:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or _RFC3339_AWARE_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must be a timezone-bearing RFC3339 date-time string or datetime"
        )
    return value


def _require_aware(value: datetime, field_name: str) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    if offset.total_seconds() != 0:
        raise ValueError(f"{field_name} must be UTC")
    return value


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class _FrozenExternalModel(_CamelModel):
    """Externally durable snapshots are closed, finite, and immutable."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")


class FactClass(StrEnum):
    DECLARED = "DECLARED"
    OBSERVED = "OBSERVED"
    INDEPENDENTLY_SUBSTANTIATED = "INDEPENDENTLY_SUBSTANTIATED"


class ArtifactOutcome(StrEnum):
    MEASURED = "MEASURED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REJECTED = "REJECTED"


class PolicyStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class DecisionVerdict(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class NodataRepresentation(StrEnum):
    """JSON-safe parser observation; NAN is a token, never a non-finite JSON value."""

    NONE = "NONE"
    FINITE = "FINITE"
    NAN = "NAN"
    MASK = "MASK"


class SealedExternalSubjectV1(_FrozenExternalModel):
    """Exact external revision identity; Core later proves it is in caller scope."""

    organization_id: _BoundedText
    site_id: _BoundedText
    work_order_id: _BoundedText
    submission_id: _BoundedText
    revision: StrictInt = Field(ge=1)
    submission_digest: Digest
    manifest_digest: Digest

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())


class ResourceEnvelopeV1(_FrozenExternalModel):
    """Configured finite worker limits; values are policy data, never client input."""

    max_input_bytes: StrictInt = Field(gt=0)
    max_streamed_bytes: StrictInt = Field(gt=0)
    max_tiff_directories: StrictInt = Field(gt=0)
    max_tiff_entries: StrictInt = Field(gt=0)
    max_pixels: StrictInt = Field(gt=0)
    max_bands: StrictInt = Field(gt=0)
    max_blocks: StrictInt = Field(gt=0)
    max_decompressed_bytes: StrictInt = Field(gt=0)
    max_sample_bytes: StrictInt = Field(gt=0)
    max_geometry_vertices: StrictInt = Field(gt=0)
    max_cpu_seconds: StrictFloat = Field(gt=0)
    max_memory_bytes: StrictInt = Field(gt=0)
    max_workspace_bytes: StrictInt = Field(gt=0)
    max_output_bytes: StrictInt = Field(gt=0)
    max_tenant_concurrency: StrictInt = Field(gt=0)
    max_queue_depth: StrictInt = Field(gt=0)
    max_deadline_seconds: StrictFloat = Field(gt=0)
    lease_duration_seconds: StrictFloat = Field(gt=0)
    max_retry_attempts: StrictInt = Field(gt=0)
    resource_envelope_digest: Digest | None = None

    @model_validator(mode="after")
    def _digest_matches_and_values_are_finite(self) -> ResourceEnvelopeV1:
        if not all(
            math.isfinite(value)
            for value in (
                self.max_cpu_seconds,
                self.max_deadline_seconds,
                self.lease_duration_seconds,
            )
        ):
            raise ValueError("resource duration limits must be finite")
        if (
            self.resource_envelope_digest is not None
            and self.resource_envelope_digest != self.canonical_digest()
        ):
            raise ValueError("resourceEnvelopeDigest does not match canonical resource envelope")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"resource_envelope_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ResourceEnvelopeV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"resource_envelope_digest": validated.canonical_digest()}, deep=True
        )


class ExternalValidationPolicyV1(_FrozenExternalModel):
    """Policy snapshot, never evidence truth or a configurable verified escape."""

    contract_version: Literal["external-validation-policy.v1"] = "external-validation-policy.v1"
    policy_id: _BoundedText
    version: StrictInt = Field(ge=1)
    status: PolicyStatus
    parser_build_digest: Digest
    grammar_digest: Digest
    resource_envelope: ResourceEnvelopeV1 | None = None
    resource_envelope_digest: Digest | None = None
    authority_record_digest: Digest | None = None
    inspection_rule_ids: tuple[_BoundedText, ...] = Field(max_length=64)
    evidence_rule_ids: tuple[_BoundedText, ...] = Field(max_length=64)
    compatibility_mapping_digests: tuple[Digest, ...] = Field(max_length=64)
    synthetic_test_only: StrictBool = False
    policy_digest: Digest | None = None

    @model_validator(mode="after")
    def _active_policy_has_explicit_envelope_and_authority(self) -> ExternalValidationPolicyV1:
        if self.status is PolicyStatus.ACTIVE:
            if self.resource_envelope is None or self.resource_envelope_digest is None:
                raise ValueError(
                    "ACTIVE policy requires a resource envelope and resourceEnvelopeDigest"
                )
            if self.authority_record_digest is None:
                raise ValueError("ACTIVE policy requires authorityRecordDigest")
        if self.resource_envelope is not None:
            sealed_envelope = ResourceEnvelopeV1.model_validate(
                self.resource_envelope.__dict__
            ).sealed()
            if self.resource_envelope_digest != sealed_envelope.resource_envelope_digest:
                raise ValueError("resourceEnvelopeDigest must bind the supplied resourceEnvelope")
        elif self.resource_envelope_digest is not None:
            raise ValueError("resourceEnvelopeDigest requires resourceEnvelope")
        if self.policy_digest is not None and self.policy_digest != self.canonical_digest():
            raise ValueError("policyDigest does not match canonical policy content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"policy_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalValidationPolicyV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"policy_digest": validated.canonical_digest()}, deep=True
        )


class ExternalArtifactInspectionRequestV1(_FrozenExternalModel):
    """Core-issued inspection intent without a client resource envelope."""

    contract_version: Literal["external-artifact-inspection-request.v1"] = (
        "external-artifact-inspection-request.v1"
    )
    request_id: _BoundedText
    subject: SealedExternalSubjectV1
    inspection_policy_id: _BoundedText
    inspection_policy_version: StrictInt = Field(ge=1)
    inspection_policy_digest: Digest
    issued_at: datetime
    idempotency_key: _BoundedText

    @field_validator("issued_at", mode="before")
    @classmethod
    def _issued_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_aware_datetime_wire_value(value, "issuedAt")

    @field_validator("issued_at")
    @classmethod
    def _issued_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "issuedAt")


class SealedArtifactBindingV1(_FrozenExternalModel):
    artifact_id: _BoundedText
    observed_sha256: Digest


class ObservedVerticalReferenceV1(_FrozenExternalModel):
    """Parser-observed vertical identifier/basis, distinct from a user declaration."""

    identifier: _LongBoundedText
    basis: _LongBoundedText


class RasterMeasurementsV1(_FrozenExternalModel):
    """Worker-observed raster facts, never a compatibility or accuracy assertion."""

    observed_crs_identifier: _LongBoundedText
    observed_crs_wkt: _LongBoundedText | None = None
    observed_crs_digest: Digest
    observed_vertical_reference: ObservedVerticalReferenceV1 | None = None
    transform: tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat]
    footprint_wkt: _LongBoundedText
    footprint_digest: Digest
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)
    band_count: StrictInt = Field(gt=0)
    dtype: _BoundedText
    layout: _BoundedText
    nodata_representation: NodataRepresentation
    nodata_value: StrictFloat | None = None
    valid_pixel_count: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def _finite_transform_and_valid_coverage(self) -> RasterMeasurementsV1:
        if not all(math.isfinite(value) for value in self.transform):
            raise ValueError("transform must contain only finite values")
        if self.nodata_representation is NodataRepresentation.FINITE:
            if self.nodata_value is None or not math.isfinite(self.nodata_value):
                raise ValueError("FINITE nodataRepresentation requires a finite nodataValue")
        elif self.nodata_value is not None:
            raise ValueError("nodataValue is allowed only with FINITE nodataRepresentation")
        if self.valid_pixel_count > self.width * self.height:
            raise ValueError("validPixelCount cannot exceed raster pixel count")
        return self


class ArtifactInspectionOutcomeV1(_FrozenExternalModel):
    artifact_id: _BoundedText
    observed_sha256: Digest
    outcome: ArtifactOutcome
    reason: _Reason | None = None
    measurements: RasterMeasurementsV1 | None = None

    @model_validator(mode="after")
    def _outcome_has_exact_evidence_shape(self) -> ArtifactInspectionOutcomeV1:
        if self.outcome is ArtifactOutcome.MEASURED:
            if self.measurements is None or self.reason is not None:
                raise ValueError("MEASURED requires measurements and no reason")
        elif self.outcome in {
            ArtifactOutcome.NOT_APPLICABLE,
            ArtifactOutcome.REJECTED,
        } and (self.measurements is not None or self.reason is None):
            raise ValueError(f"{self.outcome.value} requires typed reason and no measurements")
        return self


class ExternalInspectionMeasurementPayloadV1(_FrozenExternalModel):
    """Canonical worker payload; envelope execution facts live on the report instead."""

    fact_class: Literal[FactClass.OBSERVED] = FactClass.OBSERVED
    subject_digest: Digest
    sealed_manifest_digest: Digest
    inspection_policy_digest: Digest
    inspector_build_digest: Digest
    artifact_bindings: tuple[SealedArtifactBindingV1, ...] = Field(min_length=1, max_length=8)
    outcomes: tuple[ArtifactInspectionOutcomeV1, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def _one_outcome_for_each_bound_artifact(self) -> ExternalInspectionMeasurementPayloadV1:
        bindings = {
            binding.artifact_id: binding.observed_sha256 for binding in self.artifact_bindings
        }
        outcomes = {outcome.artifact_id: outcome.observed_sha256 for outcome in self.outcomes}
        if len(bindings) != len(self.artifact_bindings):
            raise ValueError("artifactBindings must have unique artifactId values")
        if len(outcomes) != len(self.outcomes):
            raise ValueError("outcomes must have one outcome per artifactId")
        if bindings != outcomes:
            raise ValueError("outcomes must bind every artifactId and observedSha256 exactly once")
        object.__setattr__(
            self,
            "artifact_bindings",
            tuple(sorted(self.artifact_bindings, key=lambda item: item.artifact_id)),
        )
        object.__setattr__(
            self,
            "outcomes",
            tuple(sorted(self.outcomes, key=lambda item: item.artifact_id)),
        )
        return self

    def canonical_payload(self) -> dict[str, Any]:
        payload = self.model_dump(by_alias=True, mode="json")
        payload["artifactBindings"] = sorted(
            payload["artifactBindings"], key=lambda item: item["artifactId"]
        )
        payload["outcomes"] = sorted(payload["outcomes"], key=lambda item: item["artifactId"])
        return payload

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())


class ExternalArtifactInspectionReportV1(_FrozenExternalModel):
    """Fenced worker report; only its measurement payload is independently hashed."""

    contract_version: Literal["external-artifact-inspection-report.v1"] = (
        "external-artifact-inspection-report.v1"
    )
    report_id: _BoundedText
    request_id: _BoundedText
    subject: SealedExternalSubjectV1
    subject_digest: Digest
    sealed_manifest_digest: Digest
    inspection_policy_digest: Digest
    inspector_build_digest: Digest
    measurement_payload: ExternalInspectionMeasurementPayloadV1
    measurement_payload_digest: Digest | None = None
    worker_instance_id: _BoundedText
    lease_acquisition_id: _BoundedText
    lease_generation: StrictInt = Field(ge=1)
    reported_at: datetime
    report_digest: Digest | None = None

    @field_validator("reported_at", mode="before")
    @classmethod
    def _reported_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_aware_datetime_wire_value(value, "reportedAt")

    @field_validator("reported_at")
    @classmethod
    def _reported_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "reportedAt")

    @field_validator("worker_instance_id", "lease_acquisition_id")
    @classmethod
    def _lease_identifiers_are_canonical_uuid4(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except ValueError as exc:
            raise ValueError("lease identifiers must be canonical UUIDv4 strings") from exc
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("lease identifiers must be canonical UUIDv4 strings")
        return value

    @model_validator(mode="after")
    def _binds_its_exact_payload(self) -> ExternalArtifactInspectionReportV1:
        if self.subject_digest != self.subject.canonical_digest():
            raise ValueError("subjectDigest must bind subject")
        if self.sealed_manifest_digest != self.subject.manifest_digest:
            raise ValueError("sealedManifestDigest must bind subject.manifestDigest")
        payload = self.measurement_payload
        expected = {
            "subjectDigest": self.subject_digest,
            "sealedManifestDigest": self.sealed_manifest_digest,
            "inspectionPolicyDigest": self.inspection_policy_digest,
            "inspectorBuildDigest": self.inspector_build_digest,
        }
        actual = {
            "subjectDigest": payload.subject_digest,
            "sealedManifestDigest": payload.sealed_manifest_digest,
            "inspectionPolicyDigest": payload.inspection_policy_digest,
            "inspectorBuildDigest": payload.inspector_build_digest,
        }
        if actual != expected:
            raise ValueError(
                "measurementPayload must bind the report subject, manifest, policy, and build"
            )
        if self.measurement_payload_digest is not None and (
            self.measurement_payload_digest != self.measurement_payload_canonical_digest()
        ):
            raise ValueError("measurementPayloadDigest does not match canonical measurementPayload")
        if self.report_digest is not None and self.report_digest != self.canonical_digest():
            raise ValueError("reportDigest does not match canonical report content")
        return self

    @property
    def fact_class(self) -> FactClass:
        return FactClass.OBSERVED

    def measurement_payload_canonical_digest(self) -> str:
        return self.measurement_payload.canonical_digest()

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"report_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalArtifactInspectionReportV1:
        validated = type(self).model_validate(self.__dict__)
        with_payload_digest = validated.model_copy(
            update={"measurement_payload_digest": validated.measurement_payload_canonical_digest()},
            deep=True,
        )
        return with_payload_digest.model_copy(
            update={"report_digest": with_payload_digest.canonical_digest()}, deep=True
        )


class ExternalUseDecisionV1(_FrozenExternalModel):
    """Core's immutable one-subject decision; facts are references, not promotions."""

    contract_version: Literal["external-use-decision.v1"] = "external-use-decision.v1"
    decision_id: _BoundedText
    subject: SealedExternalSubjectV1
    subject_digest: Digest
    use: Literal["DISPLAY", "HEIGHT"]
    policy_digest: Digest | None = None
    inspection_report_digest: Digest | None = None
    evidence_record_digests: tuple[Digest, ...] = Field(max_length=64)
    sanitized_display_receipt_digest: Digest | None = None
    verdict: DecisionVerdict
    reasons: tuple[_Reason, ...] = Field(min_length=1, max_length=32)
    remediations: tuple[_Remediation, ...] = Field(min_length=1, max_length=32)
    decided_at: datetime
    decision_digest: Digest | None = None

    @field_validator("decided_at", mode="before")
    @classmethod
    def _decided_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_aware_datetime_wire_value(value, "decidedAt")

    @field_validator("decided_at")
    @classmethod
    def _decided_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "decidedAt")

    @model_validator(mode="after")
    def _binds_one_exact_subject_and_display(self) -> ExternalUseDecisionV1:
        if self.subject_digest != self.subject.canonical_digest():
            raise ValueError("subjectDigest must bind subject")
        if self.verdict is not DecisionVerdict.BLOCKED:
            if self.policy_digest is None:
                raise ValueError("non-BLOCKED decision requires policyDigest")
            if self.inspection_report_digest is None:
                raise ValueError("non-BLOCKED decision requires inspectionReportDigest")
        if (
            self.use == "DISPLAY"
            and self.verdict is not DecisionVerdict.BLOCKED
            and self.sanitized_display_receipt_digest is None
        ):
            raise ValueError("non-BLOCKED DISPLAY requires sanitizedDisplayReceiptDigest")
        if self.use == "HEIGHT" and self.sanitized_display_receipt_digest is not None:
            raise ValueError("HEIGHT must not bind a sanitizedDisplayReceiptDigest")
        if self.decision_digest is not None and self.decision_digest != self.canonical_digest():
            raise ValueError("decisionDigest does not match canonical decision content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"decision_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalUseDecisionV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"decision_digest": validated.canonical_digest()}, deep=True
        )


class SealedZoneReferenceV1(_FrozenExternalModel):
    zone_id: _BoundedText
    revision: StrictInt = Field(ge=1)
    definition_digest: Digest
    observed_crs_digest: Digest
    observed_vertical_reference_digest: Digest


class ExternalPairUseDecisionV1(_FrozenExternalModel):
    """Core's immutable pair decision; Core resolves referenced receipt provenance separately."""

    contract_version: Literal["external-pair-use-decision.v1"] = "external-pair-use-decision.v1"
    decision_id: _BoundedText
    baseline_subject: SealedExternalSubjectV1
    baseline_subject_digest: Digest
    current_subject: SealedExternalSubjectV1
    current_subject_digest: Digest
    use: Literal["VISUAL_COMPARISON", "RELATIVE_VOLUME"]
    policy_digest: Digest | None = None
    baseline_inspection_report_digest: Digest | None = None
    current_inspection_report_digest: Digest | None = None
    baseline_sanitized_display_receipt_digest: Digest | None = None
    current_sanitized_display_receipt_digest: Digest | None = None
    evidence_record_digests: tuple[Digest, ...] = Field(max_length=64)
    zone: SealedZoneReferenceV1 | None = None
    verdict: DecisionVerdict
    reasons: tuple[_Reason, ...] = Field(min_length=1, max_length=32)
    remediations: tuple[_Remediation, ...] = Field(min_length=1, max_length=32)
    decided_at: datetime
    decision_digest: Digest | None = None

    @field_validator("decided_at", mode="before")
    @classmethod
    def _decided_at_is_datetime_wire_value(cls, value: object) -> object:
        return _require_aware_datetime_wire_value(value, "decidedAt")

    @field_validator("decided_at")
    @classmethod
    def _decided_at_is_aware(cls, value: datetime) -> datetime:
        return _require_aware(value, "decidedAt")

    @model_validator(mode="after")
    def _binds_ordered_pair_and_use_specific_zone(self) -> ExternalPairUseDecisionV1:
        if self.baseline_subject_digest != self.baseline_subject.canonical_digest():
            raise ValueError("baselineSubjectDigest must bind baselineSubject")
        if self.current_subject_digest != self.current_subject.canonical_digest():
            raise ValueError("currentSubjectDigest must bind currentSubject")
        if self.baseline_subject_digest == self.current_subject_digest:
            raise ValueError("ordered pair requires distinct baseline and current subjects")
        if self.verdict is not DecisionVerdict.BLOCKED:
            if self.policy_digest is None:
                raise ValueError("non-BLOCKED decision requires policyDigest")
            if self.baseline_inspection_report_digest is None:
                raise ValueError(
                    "non-BLOCKED decision requires baselineInspectionReportDigest"
                )
            if self.current_inspection_report_digest is None:
                raise ValueError(
                    "non-BLOCKED decision requires currentInspectionReportDigest"
                )
        if self.use == "VISUAL_COMPARISON" and self.verdict is not DecisionVerdict.BLOCKED:
            if self.baseline_sanitized_display_receipt_digest is None:
                raise ValueError(
                    "non-BLOCKED VISUAL_COMPARISON requires "
                    "baselineSanitizedDisplayReceiptDigest"
                )
            if self.current_sanitized_display_receipt_digest is None:
                raise ValueError(
                    "non-BLOCKED VISUAL_COMPARISON requires "
                    "currentSanitizedDisplayReceiptDigest"
                )
        if self.use == "RELATIVE_VOLUME" and (
            self.baseline_sanitized_display_receipt_digest is not None
            or self.current_sanitized_display_receipt_digest is not None
        ):
            raise ValueError("RELATIVE_VOLUME must not bind sanitized display receipts")
        if (
            self.use == "RELATIVE_VOLUME"
            and self.verdict is not DecisionVerdict.BLOCKED
            and self.zone is None
        ):
            raise ValueError("non-BLOCKED RELATIVE_VOLUME requires an exact zone")
        if self.use == "VISUAL_COMPARISON" and self.zone is not None:
            raise ValueError("VISUAL_COMPARISON must not carry a zone")
        if self.decision_digest is not None and self.decision_digest != self.canonical_digest():
            raise ValueError("decisionDigest does not match canonical decision content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"decision_digest"})

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalPairUseDecisionV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"decision_digest": validated.canonical_digest()}, deep=True
        )


def _wire(model: _FrozenExternalModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=False)


def external_artifact_inspection_request_wire_dict(
    request: ExternalArtifactInspectionRequestV1,
) -> dict[str, Any]:
    return _wire(ExternalArtifactInspectionRequestV1.model_validate(request.__dict__))


def external_artifact_inspection_report_wire_dict(
    report: ExternalArtifactInspectionReportV1,
) -> dict[str, Any]:
    return _wire(report.sealed())


def external_validation_policy_wire_dict(policy: ExternalValidationPolicyV1) -> dict[str, Any]:
    return _wire(policy.sealed())


def external_use_decision_wire_dict(decision: ExternalUseDecisionV1) -> dict[str, Any]:
    return _wire(decision.sealed())


def external_pair_use_decision_wire_dict(decision: ExternalPairUseDecisionV1) -> dict[str, Any]:
    return _wire(decision.sealed())


__all__ = [
    "ArtifactInspectionOutcomeV1",
    "ArtifactOutcome",
    "DecisionVerdict",
    "Digest",
    "ExternalArtifactInspectionReportV1",
    "ExternalArtifactInspectionRequestV1",
    "ExternalInspectionMeasurementPayloadV1",
    "ExternalPairUseDecisionV1",
    "ExternalUseDecisionV1",
    "ExternalValidationPolicyV1",
    "FactClass",
    "NodataRepresentation",
    "PolicyStatus",
    "ObservedVerticalReferenceV1",
    "RasterMeasurementsV1",
    "ResourceEnvelopeV1",
    "SealedArtifactBindingV1",
    "SealedExternalSubjectV1",
    "SealedZoneReferenceV1",
    "external_artifact_inspection_report_wire_dict",
    "external_artifact_inspection_request_wire_dict",
    "external_pair_use_decision_wire_dict",
    "external_use_decision_wire_dict",
    "external_validation_policy_wire_dict",
]
