"""Public native-grid data contracts, separate from quantitative analysis authority."""

import hashlib
import math
from enum import StrEnum
from typing import Annotated, Literal, Self

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import Field, StrictBool, StrictInt, StringConstraints, model_validator

from ksi_event_contracts._spatial_data import (
    MAX_COUNTER,
    AssetRef,
    Attribution,
    Bounds,
    Coordinate,
    Digest,
    PositiveInt,
    SpatialDataDigestModel,
    SpatialDataModel,
    Text,
    UtcTimestamp,
)
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    NodataRepresentation,
    ObservedVerticalReferenceV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.spatial_data_authority import (
    SpatialDataGrantV1,
    SpatialDataPolicyV1,
    SpatialDataRuntimeV1,
)

JobId = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=43,
        max_length=43,
        pattern=r"^sdj-v1-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    ),
]
NativeKind = Literal["dsm", "ortho"]
Transform = tuple[Coordinate, Coordinate, Coordinate, Coordinate, Coordinate, Coordinate]
PixelIndex = Annotated[StrictInt, Field(ge=0, le=MAX_COUNTER)]
# Adopt NativeWindowReceiptV1: (colStart, colStop, rowStart, rowStop), half-open.
PixelWindow = tuple[PixelIndex, PixelIndex, PixelIndex, PixelIndex]

SpatialDataReasonV1 = Literal[
    "PERMISSION_DENIED",
    "NOT_FOUND",
    "ACCESS_REVOKED",
    "ACCESS_EXPIRED",
    "RETENTION_EXPIRED",
    "AI_EGRESS_DENIED",
    "PROCESSING_LOCATION_DENIED",
    "GRANT_REQUIRED",
    "AMBIGUOUS_GRANT",
    "ACTIVATION_UNAVAILABLE",
    "POLICY_UNAVAILABLE",
    "SOURCE_UNSEALED",
    "SOURCE_NOT_MEASURED",
    "SOURCE_UNAVAILABLE",
    "SOURCE_NOT_REGULAR_FILE",
    "SOURCE_BYTES_MISMATCH",
    "SOURCE_MEASUREMENTS_MISMATCH",
    "UNSUPPORTED_ARTIFACT_KIND",
    "UNSUPPORTED_SOURCE_PROFILE",
    "INVALID_REQUEST_BOUNDS",
    "INVALID_RESOURCE_LIMIT",
    "CRS_MISMATCH",
    "VERTICAL_REFERENCE_MISMATCH",
    "UNSUPPORTED_GRID",
    "UNREPRESENTABLE_GRID",
    "INVALID_SOURCE_GEOMETRY",
    "REQUEST_OUTSIDE_SOURCE",
    "OUTPUT_OUTSIDE_GRANT",
    "EMPTY_PIXEL_WINDOW",
    "EMPTY_VALID_WINDOW",
    "INVALID_SOURCE_SAMPLE",
    "INVALID_SOURCE_MASK",
    "INPUT_BYTE_LIMIT_EXCEEDED",
    "INPUT_PIXEL_LIMIT_EXCEEDED",
    "INPUT_BAND_LIMIT_EXCEEDED",
    "OUTPUT_BYTE_LIMIT_EXCEEDED",
    "OUTPUT_PIXEL_LIMIT_EXCEEDED",
    "WORKSPACE_LIMIT_EXCEEDED",
    "SAMPLE_MEMORY_LIMIT_EXCEEDED",
    "DECOMPRESSED_BYTE_LIMIT_EXCEEDED",
    "PRIVATE_WORKSPACE_UNAVAILABLE",
    "PRIVATE_WORKSPACE_CLEANUP_FAILED",
    "OUTPUT_ALREADY_EXISTS",
    "OUTPUT_NOT_PRIVATE",
    "RASTER_PREPARATION_FAILED",
    "RASTER_WRITE_FAILED",
    "OUTPUT_VERIFICATION_FAILED",
    "EMPTY_OUTPUT",
    "CONCURRENCY_LIMIT_EXCEEDED",
    "IDEMPOTENCY_CONFLICT",
    "FENCE_CONFLICT",
    "LEASE_EXPIRED",
    "REPORT_CONFLICT",
    "CANCELED",
    "CANCELLED",
    "DEADLINE_EXCEEDED",
    "STORAGE_UNAVAILABLE",
    "INTEGRITY_MISMATCH",
    "CURRENTNESS_UNAVAILABLE",
    "AUDIT_UNAVAILABLE",
    "RANGE_NOT_SUPPORTED",
    "CLEANUP_FAILED",
    "NOT_READY",
    "UNAVAILABLE",
    "RETAINED_HISTORY_LIMIT_EXCEEDED",
    "RESOURCE_LIMIT_EXCEEDED",
]
SpatialDataRemediationV1 = Literal[
    "RETRY_REQUEST",
    "REQUEST_NEW_GRANT",
    "CONTACT_OPERATOR",
    "REINSPECT_SOURCE",
    "SUPPLY_SUPPORTED_SOURCE",
    "REDUCE_REQUEST",
    "REQUEST_NEW_JOB",
    "WAIT_FOR_COMPLETION",
    "CHECK_AUTHENTICATION",
    "CHECK_AI_CONSENT",
    "CHECK_PROCESSING_LOCATION",
]


class SpatialDataPurposeV1(StrEnum):
    GENERAL_DATA_USE = "GENERAL_DATA_USE"
    EXTERNAL_AI = "EXTERNAL_AI"


class SpatialDataExecutionStateV1(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"


class SpatialDataAvailabilityV1(StrEnum):
    NOT_READY = "NOT_READY"
    AVAILABLE = "AVAILABLE"
    ACCESS_REVOKED = "ACCESS_REVOKED"
    ACCESS_EXPIRED = "ACCESS_EXPIRED"
    RETENTION_EXPIRED = "RETENTION_EXPIRED"
    UNAVAILABLE = "UNAVAILABLE"


class SpatialDataRequestV1(SpatialDataModel):
    asset_ref: AssetRef
    requested_bounds: Bounds
    observed_crs_digest: Digest
    resolution_mode: Literal["NATIVE"]
    purpose: SpatialDataPurposeV1

    def canonical_digest(self) -> str:
        record = type(self).model_validate(self.__dict__)
        return (
            "sha256:"
            + hashlib.sha256(
                canonical_json_bytes(record.model_dump(by_alias=True, mode="json"))
            ).hexdigest()
        )


def _capture_interval(start: UtcTimestamp | None, end: UtcTimestamp | None) -> None:
    if start is None and end is None:
        return
    if start is None or end is None or end < start:
        raise ValueError("declared capture interval must have both ordered UTC endpoints")


def _native_profile(kind: str, dtype: str, bands: int, transform: Transform) -> None:
    if (kind == "dsm" and (dtype not in {"float32", "float64"} or bands != 1)) or (
        kind == "ortho" and (dtype != "uint8" or bands not in {3, 4})
    ):
        raise ValueError("unsupported native DSM/ORTHO band profile")
    a, b, _, d, e, _ = transform
    if a <= 0 or e >= 0 or b != 0 or d != 0:
        raise ValueError("native output requires a north-up unrotated grid")


class SpatialDataSourceV1(SpatialDataDigestModel):
    """Binding shape only: Core must authenticate the actual sealed inspection."""

    _digest_field = "source_digest"
    asset_ref: AssetRef
    site_id: Text
    work_area_id: Text
    work_order_id: Text
    epoch_id: Text
    submission_ref: Text
    revision: PositiveInt
    artifact_id: Text
    artifact_kind: NativeKind
    sealed_subject: SealedExternalSubjectV1
    observed_sha256: Digest
    observed_size_bytes: PositiveInt
    inspection: ArtifactInspectionOutcomeV1
    inspection_report_digest: Digest
    inspector_build_digest: Digest
    work_area_boundary_digest: Digest
    observed_crs_units: Text
    capture_started_at: UtcTimestamp | None = None
    capture_ended_at: UtcTimestamp | None = None
    producer_processed_at: UtcTimestamp | None = None
    declaration_recorded_at: UtcTimestamp
    source_digest: Digest | None = None

    @model_validator(mode="after")
    def _exact_measured_subject(self) -> Self:
        subject = self.sealed_subject
        if (self.site_id, self.work_order_id, self.revision) != (
            subject.site_id,
            subject.work_order_id,
            subject.revision,
        ):
            raise ValueError("source scope/revision must bind sealed subject")
        inspected = self.inspection
        if (self.artifact_id, self.observed_sha256) != (
            inspected.artifact_id,
            inspected.observed_sha256,
        ):
            raise ValueError("source bytes/artifact must bind inspection")
        if inspected.outcome is not ArtifactOutcome.MEASURED or inspected.measurements is None:
            raise ValueError("source must bind a MEASURED inspection")
        measured = inspected.measurements
        if measured.layout not in {"COG_PROFILE_V1", "GEOTIFF_TILED_V1", "GEOTIFF_STRIPED_V1"}:
            raise ValueError("source layout is outside native GeoTIFF profile")
        _native_profile(self.artifact_kind, measured.dtype, measured.band_count, measured.transform)
        _capture_interval(self.capture_started_at, self.capture_ended_at)
        return self


class SpatialDataFrozenJobV1(SpatialDataDigestModel):
    _digest_field = "job_digest"
    job_id: JobId
    organization_id: Text
    requester_principal_id: Text
    site_id: Text
    work_area_id: Text
    request: SpatialDataRequestV1
    source: SpatialDataSourceV1
    grant: SpatialDataGrantV1
    policy: SpatialDataPolicyV1
    runtime: SpatialDataRuntimeV1
    idempotency_key_hash: Digest
    request_fingerprint: Digest
    created_at: UtcTimestamp
    deadline: UtcTimestamp
    job_digest: Digest | None = None

    @model_validator(mode="after")
    def _full_snapshots_bind_scope_request_and_policy(self) -> Self:
        for snapshot in (self.source, self.grant, self.policy, self.runtime):
            if getattr(snapshot, snapshot._digest_field) != snapshot.canonical_digest():
                raise ValueError("frozen job requires fully sealed snapshots")
        source, grant = self.source, self.grant
        if (self.organization_id, self.site_id, self.work_area_id) != (
            source.sealed_subject.organization_id,
            source.site_id,
            source.work_area_id,
        ):
            raise ValueError("job scope must match exact source scope")
        if (self.organization_id, self.requester_principal_id, self.site_id, self.work_area_id) != (
            grant.organization_id,
            grant.beneficiary_principal_id,
            grant.site_id,
            grant.work_area_id,
        ):
            raise ValueError("job beneficiary/scope must match grant")
        if self.request.asset_ref != source.asset_ref or grant.asset_ref != source.asset_ref:
            raise ValueError("request and grant must bind exact asset")
        if self.request_fingerprint != self.request.canonical_digest():
            raise ValueError("request fingerprint does not bind normalized body")
        if grant.policy_digest != self.policy.policy_digest:
            raise ValueError("grant must bind frozen policy")
        measurements = source.inspection.measurements
        if measurements is None:
            raise ValueError("frozen source must have measured raster facts")
        if (
            self.request.observed_crs_digest != measurements.observed_crs_digest
            or self.request.observed_crs_digest != grant.observed_crs_digest
            or self.request.purpose not in grant.purposes
            or "PREPARE" not in grant.operations
        ):
            raise ValueError("request CRS/purpose/operation must match source and grant")
        if not grant.is_current_at(self.created_at):
            raise ValueError("grant must be current at admission timestamp")
        if (
            not 0
            < (self.deadline - self.created_at).total_seconds()
            <= (self.policy.resource_envelope.max_deadline_seconds)
        ):
            raise ValueError("job deadline exceeds finite envelope")
        return self


class SpatialDataAttemptV1(SpatialDataDigestModel):
    _digest_field = "attempt_digest"
    job_id: JobId
    frozen_job_digest: Digest
    attempt_number: PositiveInt
    fence: PositiveInt
    worker_principal_id: Text
    worker_instance_id: Text
    acquisition_key_hash: Digest
    acquired_at: UtcTimestamp
    lease_until: UtcTimestamp
    attempt_digest: Digest | None = None

    @model_validator(mode="after")
    def _positive_lease(self) -> Self:
        if self.lease_until <= self.acquired_at:
            raise ValueError("lease interval must have positive duration")
        return self

    def fence_digest(self) -> str:
        """Stable acquisition identity; renewable lease still binds the full payload hash."""
        record = type(self).model_validate(self.__dict__)
        payload = record.model_dump(
            by_alias=True, mode="json", exclude={"attempt_digest", "lease_until"}
        )
        return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class SpatialDataReceiptV1(SpatialDataDigestModel):
    _digest_field = "receipt_digest"
    job_id: JobId
    job_digest: Digest
    source_digest: Digest
    request_digest: Digest
    preparation_profile: Literal["ksi-native-window.v1"] = "ksi-native-window.v1"
    runtime_digest: Digest
    policy_digest: Digest
    grant_digest: Digest
    artifact_id: Text
    artifact_kind: NativeKind
    source_sha256: Digest
    source_size_bytes: PositiveInt
    requested_bounds: Bounds
    requested_crs_digest: Digest
    actual_bounds: Bounds
    pixel_window: PixelWindow
    width: PositiveInt
    height: PositiveInt
    transform: Transform
    source_transform: Transform
    source_resolution: tuple[Coordinate, Coordinate]
    observed_crs_identifier: Text
    observed_crs_digest: Digest
    observed_vertical_reference: ObservedVerticalReferenceV1 | None = None
    band_count: PositiveInt
    dtype: Literal["float32", "float64", "uint8"]
    nodata_representation: NodataRepresentation
    nodata_value: Coordinate | None = None
    valid_pixel_count: PositiveInt
    output_sha256: Digest
    output_size_bytes: PositiveInt
    accuracy_assessed: Annotated[StrictBool, Field(json_schema_extra={"const": False})]
    prepared_at: UtcTimestamp
    declaration_recorded_at: UtcTimestamp
    timestamp_provenance: Literal["SUBMISSION_DECLARATION"] = "SUBMISSION_DECLARATION"
    capture_started_at: UtcTimestamp | None = None
    capture_ended_at: UtcTimestamp | None = None
    producer_processed_at: UtcTimestamp | None = None
    attribution: Attribution
    modification_notice: Attribution
    limitations: tuple[Text, ...] = Field(max_length=16)
    receipt_digest: Digest | None = None

    @model_validator(mode="after")
    def _consistent_native_output(self) -> Self:
        if self.accuracy_assessed:
            raise ValueError("data preparation does not assess accuracy")
        _native_profile(self.artifact_kind, self.dtype, self.band_count, self.transform)
        c0, c1, r0, r1 = self.pixel_window
        if (self.width, self.height) != (c1 - c0, r1 - r0):
            raise ValueError("output dimensions must bind native pixel window")
        _native_profile(self.artifact_kind, self.dtype, self.band_count, self.source_transform)
        a, _, c, _, e, f = self.source_transform
        if self.source_resolution != (a, -e):
            raise ValueError("native output resolution must preserve observed source resolution")
        # Keep original native source edges. Translating the output affine first and
        # adding width can round differently by one ULP; no tolerance authorizes pixels.
        expected = (c + a * c0, f + e * r1, c + a * c1, f + e * r0)
        if not all(math.isfinite(x) for x in expected) or expected != self.actual_bounds:
            raise ValueError("output bounds must bind exact source pixel-edge geometry")
        if self.transform != (a, 0.0, expected[0], 0.0, e, expected[3]):
            raise ValueError("output affine must preserve exact source step and crop origin")
        xmin, ymin, xmax, ymax = self.actual_bounds
        x0, y0, x1, y1 = self.requested_bounds
        if not (xmin <= x0 < x1 <= xmax and ymin <= y0 < y1 <= ymax):
            raise ValueError("requested bounds must lie inside actual output bounds")
        if self.observed_crs_digest != self.requested_crs_digest:
            raise ValueError("native output cannot change CRS")
        if self.valid_pixel_count > self.width * self.height:
            raise ValueError("valid pixels cannot exceed output grid")
        if self.nodata_representation is NodataRepresentation.FINITE:
            if self.nodata_value is None:
                raise ValueError("finite nodata representation requires finite value")
        elif self.nodata_value is not None:
            raise ValueError("nodata value requires finite nodata representation")
        if self.observed_vertical_reference is None and (
            "UNKNOWN_VERTICAL_REFERENCE" not in self.limitations
        ):
            raise ValueError("unknown vertical reference must remain explicit")
        _capture_interval(self.capture_started_at, self.capture_ended_at)
        return self


class SpatialDataJobViewV1(SpatialDataModel):
    job_id: JobId
    asset_ref: AssetRef
    site_id: Text
    work_area_id: Text
    created_at: UtcTimestamp
    execution_state: SpatialDataExecutionStateV1
    availability: SpatialDataAvailabilityV1
    reason: SpatialDataReasonV1 | None = None
    remediation: tuple[SpatialDataRemediationV1, ...] = Field(default=(), max_length=16)
    receipt: SpatialDataReceiptV1 | None = None

    @model_validator(mode="after")
    def _receipt_matches_execution(self) -> Self:
        if (self.execution_state is SpatialDataExecutionStateV1.COMPLETED) != (
            self.receipt is not None
        ):
            raise ValueError("only COMPLETED execution has an immutable receipt")
        if self.receipt is not None and (
            self.receipt.job_id != self.job_id
            or self.receipt.receipt_digest != self.receipt.canonical_digest()
        ):
            raise ValueError("public receipt must be sealed and bound to this job")
        if self.availability is SpatialDataAvailabilityV1.AVAILABLE and self.receipt is None:
            raise ValueError("bytes cannot be available before completion")
        return self


class SpatialDataPageV1(SpatialDataModel):
    items: tuple[SpatialDataJobViewV1, ...] = Field(max_length=200)
    next_cursor: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2048)] | (
        None
    ) = None


class SpatialDataErrorV1(SpatialDataModel):
    reason: SpatialDataReasonV1
    message: Text
    retryable: StrictBool
    remediation: tuple[SpatialDataRemediationV1, ...] = Field(min_length=1, max_length=16)
