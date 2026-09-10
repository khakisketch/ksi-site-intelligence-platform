"""Immutable contracts for externally produced relative-volume measurements.

These records bind Core-issued intent to external derived DSM bytes.  They do
not authenticate callers, decide eligibility, create managed job/artifact
identity, or promote externally derived data to a managed source authority.
"""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime
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
from ksi_event_contracts.external_artifact_validation import (
    Digest,
    FactClass,
    SealedExternalSubjectV1,
    SealedZoneReferenceV1,
)
from ksi_event_contracts.work_area import assert_polygon_is_usable

_RFC3339_UTC_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T"
    r"(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|\+00:00)$"
)
_BoundedText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)
]
_LongBoundedText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4_096)
]
_FLOAT_REL_TOLERANCE = 1e-12
_FLOAT_ABS_TOLERANCE = 1e-12
_MAX_FINITE_FLOAT = 1e300


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _require_utc_datetime_wire_value(value: object, field_name: str) -> object:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or _RFC3339_UTC_TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a UTC RFC3339 date-time string or datetime")
    return value


def _require_utc(value: datetime, field_name: str) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{field_name} must be UTC")
    return value


def _assert_external_zone_coordinate_bounds(polygon: dict[str, Any]) -> None:
    """Mirror the wire schema's finite coordinate magnitude bound.

    ``assert_polygon_is_usable`` owns the general WorkArea semantics, including
    ring closure.  This external contract adds the JSON-safe finite magnitude
    limit that its published schema can enforce for all numeric coordinates.
    """
    for ring in polygon["coordinates"]:
        for position in ring:
            for value in position:
                if isinstance(value, bool) or not isinstance(value, int | float):
                    raise ValueError("zone coordinate components must be finite numbers")
                if isinstance(value, int) and abs(value) > _MAX_FINITE_FLOAT:
                    raise ValueError(
                        "zone coordinate magnitude must not exceed the external wire limit"
                    )
                if not math.isfinite(value) or abs(value) > _MAX_FINITE_FLOAT:
                    raise ValueError(
                        "zone coordinate magnitude must not exceed the external wire limit"
                    )


class _FrozenExternalRelativeVolumeModel(_CamelModel):
    """Closed snapshots are immutable and revalidated before wire serialization."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")


class ExternalVolumeZoneSnapshotV1(_FrozenExternalRelativeVolumeModel):
    """Immutable copy of one WorkArea geometry without mutable WorkArea status fields."""

    contract_version: Literal["external-volume-zone-snapshot.v1"] = (
        "external-volume-zone-snapshot.v1"
    )
    organization_id: _BoundedText
    site_id: _BoundedText
    work_area_id: _BoundedText
    revision: Literal[1] = 1
    polygon: dict[str, Any]
    crs: _BoundedText
    observed_crs_digest: Digest
    analysis_vertical_reference_digest: Digest
    definition_digest: Digest | None = None

    @model_validator(mode="after")
    def _has_closed_finite_geometry_and_matching_definition(self) -> ExternalVolumeZoneSnapshotV1:
        assert_polygon_is_usable(self.polygon, crs=self.crs)
        _assert_external_zone_coordinate_bounds(self.polygon)
        if self.definition_digest is not None and (
            self.definition_digest != self._definition_canonical_digest_unchecked()
        ):
            raise ValueError("definitionDigest does not match the canonical zone definition")
        return self

    def _definition_canonical_payload_unchecked(self) -> dict[str, Any]:
        return {
            "domain": "external-volume-zone-definition.v1",
            "organizationId": self.organization_id,
            "siteId": self.site_id,
            "workAreaId": self.work_area_id,
            "revision": self.revision,
            "polygon": self.polygon,
            "crs": self.crs,
        }

    def _definition_canonical_digest_unchecked(self) -> str:
        return _digest(self._definition_canonical_payload_unchecked())

    def definition_canonical_payload(self) -> dict[str, Any]:
        validated = type(self).model_validate(self.__dict__)
        return validated._definition_canonical_payload_unchecked()

    def definition_canonical_digest(self) -> str:
        return _digest(self.definition_canonical_payload())

    def _canonical_payload_unchecked(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, mode="json")

    def canonical_payload(self) -> dict[str, Any]:
        validated = type(self).model_validate(self.__dict__)
        return validated._canonical_payload_unchecked()

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> ExternalVolumeZoneSnapshotV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"definition_digest": validated._definition_canonical_digest_unchecked()},
            deep=True,
        )

    def to_zone_reference(self) -> SealedZoneReferenceV1:
        sealed = self.sealed()
        assert sealed.definition_digest is not None
        return SealedZoneReferenceV1(
            zone_id=sealed.work_area_id,
            revision=sealed.revision,
            definition_digest=sealed.definition_digest,
            observed_crs_digest=sealed.observed_crs_digest,
            observed_vertical_reference_digest=sealed.analysis_vertical_reference_digest,
        )


class ExternalRelativeVolumeExecutionPolicyV1(_FrozenExternalRelativeVolumeModel):
    """Versioned execution limits; authority is always supplied, never defaulted."""

    contract_version: Literal["external-relative-volume-execution-policy.v1"] = (
        "external-relative-volume-execution-policy.v1"
    )
    policy_id: _BoundedText
    version: StrictInt = Field(ge=1)
    algorithm_build_digest: Digest
    config_digest: Digest
    threshold_m: StrictFloat = Field(ge=0.0, le=_MAX_FINITE_FLOAT)
    minimum_common_valid_fraction: StrictFloat = Field(gt=0.0, le=1.0)
    uncertainty_method: Literal["INDEPENDENT_EPOCH_RSS_AREA_BOUND_V1"]
    resource_envelope_digest: Digest
    authority_record_digest: Digest
    synthetic_test_only: StrictBool
    policy_digest: Digest | None = None

    @model_validator(mode="after")
    def _has_finite_policy_numbers_and_matching_digest(
        self,
    ) -> ExternalRelativeVolumeExecutionPolicyV1:
        if not (
            math.isfinite(self.threshold_m) and math.isfinite(self.minimum_common_valid_fraction)
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

    def sealed(self) -> ExternalRelativeVolumeExecutionPolicyV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"policy_digest": validated._canonical_digest_unchecked()}, deep=True
        )


class ExternalVolumeInputBindingV1(_FrozenExternalRelativeVolumeModel):
    """Observed DSM bytes and capture interval supplied later by Core evidence resolution."""

    subject: SealedExternalSubjectV1
    inspection_report_digest: Digest
    dsm_artifact_id: _BoundedText
    observed_sha256: Digest
    observed_size_bytes: StrictInt = Field(gt=0)
    observed_crs_digest: Digest
    observed_vertical_reference_digest: Digest
    captured_from: datetime
    captured_to: datetime

    @field_validator("captured_from", "captured_to", mode="before")
    @classmethod
    def _timestamps_are_utc_wire_values(cls, value: object, info: Any) -> object:
        return _require_utc_datetime_wire_value(value, info.field_name)

    @field_validator("captured_from", "captured_to")
    @classmethod
    def _timestamps_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _require_utc(value, info.field_name)

    @model_validator(mode="after")
    def _capture_interval_is_ordered(self) -> ExternalVolumeInputBindingV1:
        if self.captured_from >= self.captured_to:
            raise ValueError("capturedFrom must be earlier than capturedTo")
        return self


class ExternalRelativeVolumeRequestV1(_FrozenExternalRelativeVolumeModel):
    """Core-issued intent; this model only binds claims and does not declare ELIGIBLE."""

    contract_version: Literal["external-relative-volume-request.v1"] = (
        "external-relative-volume-request.v1"
    )
    request_id: _BoundedText
    current_work_order_id: _BoundedText
    decision_id: _BoundedText
    decision_digest: Digest
    baseline: ExternalVolumeInputBindingV1
    current: ExternalVolumeInputBindingV1
    evidence_record_digests: tuple[Digest, ...] = Field(min_length=1, max_length=64)
    validation_policy_digest: Digest
    execution_policy_digest: Digest
    zone_snapshot: ExternalVolumeZoneSnapshotV1
    issued_at: datetime
    idempotency_key: _BoundedText
    request_digest: Digest | None = None

    @field_validator("issued_at", mode="before")
    @classmethod
    def _issued_at_is_utc_wire_value(cls, value: object) -> object:
        return _require_utc_datetime_wire_value(value, "issuedAt")

    @field_validator("issued_at")
    @classmethod
    def _issued_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "issuedAt")

    @model_validator(mode="after")
    def _binds_one_site_and_compatible_external_inputs(self) -> ExternalRelativeVolumeRequestV1:
        baseline_subject = self.baseline.subject
        current_subject = self.current.subject
        zone = self.zone_snapshot
        if current_subject.work_order_id != self.current_work_order_id:
            raise ValueError("current.subject.workOrderId must equal currentWorkOrderId")
        if baseline_subject.canonical_digest() == current_subject.canonical_digest():
            raise ValueError("baseline and current subjects must be distinct")
        if len(set(self.evidence_record_digests)) != len(self.evidence_record_digests):
            raise ValueError("evidenceRecordDigests must be unique")
        if {
            baseline_subject.organization_id,
            current_subject.organization_id,
            zone.organization_id,
        } != {zone.organization_id}:
            raise ValueError("baseline, current, and zone must have the same organizationId")
        if {baseline_subject.site_id, current_subject.site_id, zone.site_id} != {zone.site_id}:
            raise ValueError("baseline, current, and zone must have the same siteId")
        if self.baseline.observed_crs_digest != self.current.observed_crs_digest:
            raise ValueError("baseline and current DSM observedCrsDigest must match")
        if self.baseline.captured_to > self.current.captured_from:
            raise ValueError(
                "baseline.capturedTo must be earlier than or equal to current.capturedFrom"
            )
        if (
            self.baseline.observed_vertical_reference_digest
            != zone.analysis_vertical_reference_digest
            or self.current.observed_vertical_reference_digest
            != zone.analysis_vertical_reference_digest
        ):
            raise ValueError(
                "both DSM vertical references must match zone analysis vertical reference"
            )
        sealed_zone = zone.sealed()
        if zone.definition_digest != sealed_zone.definition_digest:
            raise ValueError("zoneSnapshot must carry its canonical definitionDigest")
        if (
            self.request_digest is not None
            and self.request_digest != self._canonical_digest_unchecked()
        ):
            raise ValueError("requestDigest does not match canonical relative-volume request")
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

    def sealed(self) -> ExternalRelativeVolumeRequestV1:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_copy(
            update={"request_digest": validated._canonical_digest_unchecked()}, deep=True
        )


class ExternalVolumeMetricsV1(_FrozenExternalRelativeVolumeModel):
    """Auditable, finite full-zone coverage and volume arithmetic."""

    zone_cell_count: StrictInt = Field(gt=0)
    common_valid_cell_count: StrictInt = Field(gt=0)
    zone_area_m2: StrictFloat = Field(gt=0.0, le=_MAX_FINITE_FLOAT)
    measured_area_m2: StrictFloat = Field(gt=0.0, le=_MAX_FINITE_FLOAT)
    common_valid_fraction: StrictFloat = Field(gt=0.0, le=1.0)
    cut_m3: StrictFloat = Field(ge=0.0, le=_MAX_FINITE_FLOAT)
    fill_m3: StrictFloat = Field(ge=0.0, le=_MAX_FINITE_FLOAT)
    net_m3: StrictFloat = Field(ge=-_MAX_FINITE_FLOAT, le=_MAX_FINITE_FLOAT)
    threshold_m: StrictFloat = Field(ge=0.0, le=_MAX_FINITE_FLOAT)
    uncertainty_m3: StrictFloat | None = Field(default=None, ge=0.0, le=_MAX_FINITE_FLOAT)
    uncertainty_note: _LongBoundedText

    @model_validator(mode="after")
    def _has_consistent_finite_coverage_and_volume(self) -> ExternalVolumeMetricsV1:
        finite_values: tuple[float, ...] = (
            self.zone_area_m2,
            self.measured_area_m2,
            self.common_valid_fraction,
            self.cut_m3,
            self.fill_m3,
            self.net_m3,
            self.threshold_m,
        )
        if self.uncertainty_m3 is not None:
            finite_values += (self.uncertainty_m3,)
        if not all(math.isfinite(value) for value in finite_values):
            raise ValueError("relative-volume metrics must be finite")
        if self.common_valid_cell_count > self.zone_cell_count:
            raise ValueError("commonValidCellCount cannot exceed zoneCellCount")
        expected_fraction = self.common_valid_cell_count / self.zone_cell_count
        if not math.isclose(
            self.common_valid_fraction,
            expected_fraction,
            rel_tol=_FLOAT_REL_TOLERANCE,
            abs_tol=_FLOAT_ABS_TOLERANCE,
        ):
            raise ValueError("commonValidFraction must match commonValidCellCount / zoneCellCount")
        expected_measured_area = self.common_valid_cell_count * (
            self.zone_area_m2 / self.zone_cell_count
        )
        if not math.isclose(
            self.measured_area_m2,
            expected_measured_area,
            rel_tol=_FLOAT_REL_TOLERANCE,
            abs_tol=_FLOAT_ABS_TOLERANCE,
        ):
            raise ValueError("measuredAreaM2 must match common valid cell area")
        if not math.isclose(
            self.net_m3,
            self.fill_m3 - self.cut_m3,
            rel_tol=_FLOAT_REL_TOLERANCE,
            abs_tol=_FLOAT_ABS_TOLERANCE,
        ):
            raise ValueError("netM3 must equal fillM3 - cutM3")
        return self


class ExternalRelativeVolumeMeasurementPayloadV1(_FrozenExternalRelativeVolumeModel):
    """Deterministic observed measurement content, excluding worker and fence facts."""

    fact_class: Literal[FactClass.OBSERVED] = FactClass.OBSERVED
    request_digest: Digest
    decision_digest: Digest
    baseline_dsm_digest: Digest
    current_dsm_digest: Digest
    zone_snapshot_digest: Digest
    execution_policy_digest: Digest
    algorithm_build_digest: Digest
    config_digest: Digest
    metrics: ExternalVolumeMetricsV1

    def canonical_payload(self) -> dict[str, Any]:
        validated = type(self).model_validate(self.__dict__)
        return validated.model_dump(by_alias=True, mode="json")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())


class ExternalRelativeVolumeReportV1(_FrozenExternalRelativeVolumeModel):
    """Fenced worker report whose payload is independently canonicalized."""

    contract_version: Literal["external-relative-volume-report.v1"] = (
        "external-relative-volume-report.v1"
    )
    report_id: _BoundedText
    request_id: _BoundedText
    request_digest: Digest
    payload: ExternalRelativeVolumeMeasurementPayloadV1
    measurement_payload_digest: Digest | None = None
    worker_instance_id: _BoundedText
    lease_acquisition_id: _BoundedText
    lease_generation: StrictInt = Field(ge=1)
    computed_at: datetime
    reported_at: datetime
    report_digest: Digest | None = None

    @field_validator("computed_at", "reported_at", mode="before")
    @classmethod
    def _report_timestamps_are_utc_wire_values(cls, value: object, info: Any) -> object:
        return _require_utc_datetime_wire_value(value, info.field_name)

    @field_validator("computed_at", "reported_at")
    @classmethod
    def _report_timestamps_are_utc(cls, value: datetime, info: Any) -> datetime:
        return _require_utc(value, info.field_name)

    @field_validator("worker_instance_id", "lease_acquisition_id")
    @classmethod
    def _lease_identifiers_are_canonical_uuid4(cls, value: str) -> str:
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
    def _binds_payload_request_and_fence_order(self) -> ExternalRelativeVolumeReportV1:
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
            raise ValueError("reportDigest does not match canonical relative-volume report")
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

    def sealed(self) -> ExternalRelativeVolumeReportV1:
        validated = type(self).model_validate(self.__dict__)
        with_payload_digest = validated.model_copy(
            update={"measurement_payload_digest": validated.measurement_payload_canonical_digest()},
            deep=True,
        )
        return with_payload_digest.model_copy(
            update={"report_digest": with_payload_digest._canonical_digest_unchecked()}, deep=True
        )


def _wire(model: _FrozenExternalRelativeVolumeModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=False)


def external_volume_zone_snapshot_wire_dict(
    zone_snapshot: ExternalVolumeZoneSnapshotV1,
) -> dict[str, Any]:
    return _wire(zone_snapshot.sealed())


def external_relative_volume_execution_policy_wire_dict(
    policy: ExternalRelativeVolumeExecutionPolicyV1,
) -> dict[str, Any]:
    return _wire(policy.sealed())


def external_relative_volume_request_wire_dict(
    request: ExternalRelativeVolumeRequestV1,
) -> dict[str, Any]:
    return _wire(request.sealed())


def external_relative_volume_report_wire_dict(
    report: ExternalRelativeVolumeReportV1,
) -> dict[str, Any]:
    return _wire(report.sealed())


__all__ = [
    "ExternalRelativeVolumeExecutionPolicyV1",
    "ExternalRelativeVolumeMeasurementPayloadV1",
    "ExternalRelativeVolumeReportV1",
    "ExternalRelativeVolumeRequestV1",
    "ExternalVolumeInputBindingV1",
    "ExternalVolumeMetricsV1",
    "ExternalVolumeZoneSnapshotV1",
    "external_relative_volume_execution_policy_wire_dict",
    "external_relative_volume_report_wire_dict",
    "external_relative_volume_request_wire_dict",
    "external_volume_zone_snapshot_wire_dict",
]
