"""Sealed single-epoch (stockpile) volume contracts.

This family sits beside ``external_relative_volume`` and never extends it: one
sealed DSM epoch is measured against a base surface derived from the zone
boundary.  Models bind claims only; Core resolves eligibility and authority
before any request exists, and the worker reports observed metrics only.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, StrictBool, StrictFloat, StrictInt, field_validator, model_validator

from ksi_event_contracts.external_artifact_validation import (
    DecisionVerdict,
    Digest,
    FactClass,
    SealedExternalSubjectV1,
    SealedZoneReferenceV1,
    _Reason,
    _Remediation,
)
from ksi_event_contracts.external_relative_volume import (
    _FLOAT_ABS_TOLERANCE,
    _FLOAT_REL_TOLERANCE,
    _MAX_FINITE_FLOAT,
    ExternalVolumeInputBindingV1,
    ExternalVolumeMetricsV1,
    ExternalVolumeZoneSnapshotV1,
    _BoundedText,
    _digest,
    _FrozenExternalRelativeVolumeModel,
    _require_utc,
    _require_utc_datetime_wire_value,
)

SINGLE_VOLUME_USE = "SINGLE_VOLUME"
SINGLE_VOLUME_UNCERTAINTY_METHOD = "SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1"
SINGLE_VOLUME_BASE_SURFACE_METHOD = "BOUNDARY_LINEAR_INTERPOLATION_V1"


class ExternalSingleVolumeDecisionV1(_FrozenExternalRelativeVolumeModel):
    """Core's immutable single-subject SINGLE_VOLUME decision.

    A non-BLOCKED decision binds the current policy, the MEASURED inspection
    report, exactly one independently attested evidence record, the immutable
    zone reference and the admitted single mapping.  A BLOCKED decision binds
    none of them so a later reader cannot mistake a blocker for authority.
    """

    contract_version: Literal["external-single-volume-decision.v1"] = (
        "external-single-volume-decision.v1"
    )
    decision_id: _BoundedText
    subject: SealedExternalSubjectV1
    subject_digest: Digest
    use: Literal["SINGLE_VOLUME"] = "SINGLE_VOLUME"
    policy_digest: Digest | None = None
    inspection_report_digest: Digest | None = None
    evidence_record_digests: tuple[Digest, ...] = Field(max_length=64)
    zone: SealedZoneReferenceV1 | None = None
    compatibility_mapping_digest: Digest | None = None
    verdict: DecisionVerdict
    reasons: tuple[_Reason, ...] = Field(min_length=1, max_length=32)
    remediations: tuple[_Remediation, ...] = Field(min_length=1, max_length=32)
    decided_at: datetime
    decision_digest: Digest | None = None

    @field_validator("decided_at", mode="before")
    @classmethod
    def _decided_at_is_wire_value(cls, value: object) -> object:
        return _require_utc_datetime_wire_value(value, "decidedAt")

    @field_validator("decided_at")
    @classmethod
    def _decided_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "decidedAt")

    @model_validator(mode="after")
    def _binds_subject_and_use_specific_authority(self) -> ExternalSingleVolumeDecisionV1:
        if self.subject_digest != self.subject.canonical_digest():
            raise ValueError("subjectDigest must bind subject")
        if len(set(self.evidence_record_digests)) != len(self.evidence_record_digests):
            raise ValueError("evidenceRecordDigests must be unique")
        if self.verdict is DecisionVerdict.BLOCKED:
            if (
                self.compatibility_mapping_digest is not None
                or self.zone is not None
                or self.evidence_record_digests
            ):
                raise ValueError("BLOCKED SINGLE_VOLUME must not bind zone, mapping or evidence")
        else:
            if self.policy_digest is None or self.inspection_report_digest is None:
                raise ValueError(
                    "non-BLOCKED decision requires policyDigest and inspectionReportDigest"
                )
            if len(self.evidence_record_digests) != 1:
                raise ValueError("non-BLOCKED SINGLE_VOLUME requires exactly one evidence record")
            if self.zone is None:
                raise ValueError("non-BLOCKED SINGLE_VOLUME requires an exact zone")
            if self.compatibility_mapping_digest is None:
                raise ValueError("non-BLOCKED SINGLE_VOLUME requires compatibilityMappingDigest")
        if (
            self.decision_digest is not None
            and self.decision_digest != self._canonical_digest_unchecked()
        ):
            raise ValueError("decisionDigest does not match canonical single-volume decision")
        return self

    def _canonical_payload_unchecked(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"decision_digest"})

    def canonical_payload(self) -> dict[str, Any]:
        validated = type(self).model_validate(self.__dict__)
        return validated._canonical_payload_unchecked()

    def _canonical_digest_unchecked(self) -> str:
        return _digest(self._canonical_payload_unchecked())

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalSingleVolumeDecisionV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"decision_digest": validated._canonical_digest_unchecked()}, deep=True
        )


class ExternalSingleVolumeExecutionPolicyV1(_FrozenExternalRelativeVolumeModel):
    """Versioned single-epoch execution limits; authority is always supplied."""

    contract_version: Literal["external-single-volume-execution-policy.v1"] = (
        "external-single-volume-execution-policy.v1"
    )
    policy_id: _BoundedText
    version: StrictInt = Field(ge=1)
    algorithm_build_digest: Digest
    config_digest: Digest
    threshold_m: StrictFloat = Field(ge=0.0, le=_MAX_FINITE_FLOAT)
    minimum_common_valid_fraction: StrictFloat = Field(gt=0.0, le=1.0)
    minimum_boundary_valid_fraction: StrictFloat = Field(gt=0.0, le=1.0)
    uncertainty_method: Literal["SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1"]
    base_surface_method: Literal["BOUNDARY_LINEAR_INTERPOLATION_V1"]
    resource_envelope_digest: Digest
    authority_record_digest: Digest
    synthetic_test_only: StrictBool
    policy_digest: Digest | None = None

    @model_validator(mode="after")
    def _finite_numbers_and_matching_digest(self) -> ExternalSingleVolumeExecutionPolicyV1:
        if not all(
            math.isfinite(value)
            for value in (
                self.threshold_m,
                self.minimum_common_valid_fraction,
                self.minimum_boundary_valid_fraction,
            )
        ):
            raise ValueError("execution policy numeric values must be finite")
        if (
            self.policy_digest is not None
            and self.policy_digest != self._canonical_digest_unchecked()
        ):
            raise ValueError("policyDigest does not match canonical execution policy")
        return self

    def _canonical_payload_unchecked(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"policy_digest"})

    def canonical_payload(self) -> dict[str, Any]:
        validated = type(self).model_validate(self.__dict__)
        return validated._canonical_payload_unchecked()

    def _canonical_digest_unchecked(self) -> str:
        return _digest(self._canonical_payload_unchecked())

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalSingleVolumeExecutionPolicyV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"policy_digest": validated._canonical_digest_unchecked()}, deep=True
        )


class ExternalSingleVolumeRequestV1(_FrozenExternalRelativeVolumeModel):
    """Core-issued single-epoch intent; binds claims and declares no eligibility."""

    contract_version: Literal["external-single-volume-request.v1"] = (
        "external-single-volume-request.v1"
    )
    request_id: _BoundedText
    current_work_order_id: _BoundedText
    decision_id: _BoundedText
    decision_digest: Digest
    target: ExternalVolumeInputBindingV1
    evidence_record_digests: tuple[Digest, ...] = Field(min_length=1, max_length=1)
    validation_policy_digest: Digest
    execution_policy_digest: Digest
    zone_snapshot: ExternalVolumeZoneSnapshotV1
    issued_at: datetime
    idempotency_key: _BoundedText
    request_digest: Digest | None = None

    @field_validator("issued_at", mode="before")
    @classmethod
    def _issued_at_is_wire_value(cls, value: object) -> object:
        return _require_utc_datetime_wire_value(value, "issuedAt")

    @field_validator("issued_at")
    @classmethod
    def _issued_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "issuedAt")

    @model_validator(mode="after")
    def _binds_one_site_and_compatible_input(self) -> ExternalSingleVolumeRequestV1:
        subject, zone = self.target.subject, self.zone_snapshot
        if len(self.evidence_record_digests) != 1:
            raise ValueError("evidenceRecordDigests must carry exactly one record")
        if subject.work_order_id != self.current_work_order_id:
            raise ValueError("target.subject.workOrderId must equal currentWorkOrderId")
        if subject.organization_id != zone.organization_id or subject.site_id != zone.site_id:
            raise ValueError("target and zone must share organizationId and siteId")
        if self.target.observed_crs_digest != zone.observed_crs_digest:
            raise ValueError("target DSM observedCrsDigest must match zone observedCrsDigest")
        if (
            self.target.observed_vertical_reference_digest
            != zone.analysis_vertical_reference_digest
        ):
            raise ValueError(
                "target DSM vertical reference must match zone analysis vertical reference"
            )
        if zone.definition_digest != zone.sealed().definition_digest:
            raise ValueError("zoneSnapshot must carry its canonical definitionDigest")
        if (
            self.request_digest is not None
            and self.request_digest != self._canonical_digest_unchecked()
        ):
            raise ValueError("requestDigest does not match canonical single-volume request")
        return self

    def _canonical_payload_unchecked(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"request_digest"})

    def canonical_payload(self) -> dict[str, Any]:
        validated = type(self).model_validate(self.__dict__)
        return validated._canonical_payload_unchecked()

    def _canonical_digest_unchecked(self) -> str:
        return _digest(self._canonical_payload_unchecked())

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalSingleVolumeRequestV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"request_digest": validated._canonical_digest_unchecked()}, deep=True
        )


class ExternalSingleVolumeMetricsV1(ExternalVolumeMetricsV1):
    """Relative volume metrics plus the boundary-base facts that bound them."""

    base_roughness_m: StrictFloat = Field(ge=0.0, le=_MAX_FINITE_FLOAT)
    boundary_cell_count: StrictInt = Field(gt=0)
    boundary_sample_count: StrictInt = Field(ge=3)
    boundary_valid_fraction: StrictFloat = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _boundary_facts_are_consistent(self) -> ExternalSingleVolumeMetricsV1:
        if not math.isfinite(self.base_roughness_m):
            raise ValueError("baseRoughnessM must be finite")
        if self.boundary_sample_count > self.boundary_cell_count:
            raise ValueError("boundarySampleCount cannot exceed boundaryCellCount")
        expected = self.boundary_sample_count / self.boundary_cell_count
        if not math.isclose(
            self.boundary_valid_fraction,
            expected,
            rel_tol=_FLOAT_REL_TOLERANCE,
            abs_tol=_FLOAT_ABS_TOLERANCE,
        ):
            raise ValueError(
                "boundaryValidFraction must match boundarySampleCount / boundaryCellCount"
            )
        return self


class ExternalSingleVolumeMeasurementPayloadV1(_FrozenExternalRelativeVolumeModel):
    """Deterministic observed measurement content, excluding worker and fence facts."""

    fact_class: Literal[FactClass.OBSERVED] = FactClass.OBSERVED
    request_digest: Digest
    decision_digest: Digest
    target_dsm_digest: Digest
    zone_snapshot_digest: Digest
    execution_policy_digest: Digest
    algorithm_build_digest: Digest
    config_digest: Digest
    metrics: ExternalSingleVolumeMetricsV1

    def canonical_payload(self) -> dict[str, Any]:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_dump(by_alias=True, mode="json")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())


class ExternalSingleVolumeReportV1(_FrozenExternalRelativeVolumeModel):
    """Fenced worker report whose payload is independently canonicalized."""

    contract_version: Literal["external-single-volume-report.v1"] = (
        "external-single-volume-report.v1"
    )
    report_id: _BoundedText
    request_id: _BoundedText
    request_digest: Digest
    payload: ExternalSingleVolumeMeasurementPayloadV1
    measurement_payload_digest: Digest | None = None
    worker_instance_id: _BoundedText
    lease_acquisition_id: _BoundedText
    lease_generation: StrictInt = Field(ge=1)
    computed_at: datetime
    reported_at: datetime
    report_digest: Digest | None = None

    @field_validator("computed_at", "reported_at", mode="before")
    @classmethod
    def _timestamps_are_wire_values(cls, value: object, info: Any) -> object:
        return _require_utc_datetime_wire_value(value, info.field_name)

    @field_validator("computed_at", "reported_at")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _require_utc(value, info.field_name)

    @field_validator("worker_instance_id", "lease_acquisition_id")
    @classmethod
    def _lease_identifiers_are_uuid4(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except ValueError as exc:
            raise ValueError(
                "worker and lease identifiers must be canonical UUIDv4 strings"
            ) from exc
        if parsed.version != 4 or str(parsed) != value:
            raise ValueError("worker and lease identifiers must be canonical UUIDv4 strings")
        return value

    @model_validator(mode="after")
    def _binds_payload_request_and_fence_order(self) -> ExternalSingleVolumeReportV1:
        if self.computed_at > self.reported_at:
            raise ValueError("computedAt must be earlier than or equal to reportedAt")
        if self.payload.request_digest != self.request_digest:
            raise ValueError("payload.requestDigest must match requestDigest")
        if self.measurement_payload_digest is not None and (
            self.measurement_payload_digest != self.payload.canonical_digest()
        ):
            raise ValueError("measurementPayloadDigest does not match canonical payload")
        if (
            self.report_digest is not None
            and self.report_digest != self._canonical_digest_unchecked()
        ):
            raise ValueError("reportDigest does not match canonical single-volume report")
        return self

    def measurement_payload_canonical_digest(self) -> str:
        return self.payload.canonical_digest()

    def _canonical_payload_unchecked(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json", exclude={"report_digest"})

    def canonical_payload(self) -> dict[str, Any]:
        validated = type(self).model_validate(self.__dict__)
        return validated._canonical_payload_unchecked()

    def _canonical_digest_unchecked(self) -> str:
        return _digest(self._canonical_payload_unchecked())

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalSingleVolumeReportV1:
        validated = type(self).model_validate(self.__dict__)
        with_payload = validated.model_copy(
            update={"measurement_payload_digest": validated.payload.canonical_digest()},
            deep=True,
        )
        return with_payload.model_copy(
            update={"report_digest": with_payload._canonical_digest_unchecked()}, deep=True
        )


def _wire(model: _FrozenExternalRelativeVolumeModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=False)


def external_single_volume_decision_wire_dict(
    decision: ExternalSingleVolumeDecisionV1,
) -> dict[str, Any]:
    return _wire(decision.sealed())


def external_single_volume_execution_policy_wire_dict(
    policy: ExternalSingleVolumeExecutionPolicyV1,
) -> dict[str, Any]:
    return _wire(policy.sealed())


def external_single_volume_request_wire_dict(
    request: ExternalSingleVolumeRequestV1,
) -> dict[str, Any]:
    return _wire(request.sealed())


def external_single_volume_report_wire_dict(
    report: ExternalSingleVolumeReportV1,
) -> dict[str, Any]:
    return _wire(report.sealed())


__all__ = [
    "SINGLE_VOLUME_BASE_SURFACE_METHOD",
    "SINGLE_VOLUME_UNCERTAINTY_METHOD",
    "SINGLE_VOLUME_USE",
    "ExternalSingleVolumeDecisionV1",
    "ExternalSingleVolumeExecutionPolicyV1",
    "ExternalSingleVolumeMeasurementPayloadV1",
    "ExternalSingleVolumeMetricsV1",
    "ExternalSingleVolumeReportV1",
    "ExternalSingleVolumeRequestV1",
    "external_single_volume_decision_wire_dict",
    "external_single_volume_execution_policy_wire_dict",
    "external_single_volume_report_wire_dict",
    "external_single_volume_request_wire_dict",
]
