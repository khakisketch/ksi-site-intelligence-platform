"""Strict additive AI/MCP projection over native-grid delivery, not a V1 rewrite.

Consumes the frozen V1 output shapes (``spatial_data`` job/request/receipt views and
``_spatial_data`` value types) and projects only the grant-filtered metadata an
authenticated ``SPATIAL_DATA_MCP_CLIENT`` may discover.  This module creates no new
job authority, worker capability, storage key, raster bytes, or accuracy claim, and it
does not extend ``SpatialDataReasonV1`` or the V1 journal.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, Field, StrictBool, StringConstraints, model_validator

from ksi_event_contracts._spatial_data import (
    AssetRef,
    Attribution,
    Bounds,
    Coordinate,
    Digest,
    PositiveInt,
    SpatialDataModel,
    Text,
    UtcTimestamp,
)
from ksi_event_contracts.external_artifact_validation import ObservedVerticalReferenceV1
from ksi_event_contracts.spatial_data import (
    JobId,
    NativeKind,
    SpatialDataAvailabilityV1,
    SpatialDataExecutionStateV1,
    SpatialDataJobViewV1,
    SpatialDataReasonV1,
    SpatialDataRemediationV1,
    Transform,
    _capture_interval,
    _native_profile,
)

# AI reads reuse the closed V1 reason vocabulary plus one cursor-conflict code for
# grant/consent-bound pagination.  The old V1 enum itself is untouched.
SpatialDataAiReasonV1 = SpatialDataReasonV1 | Literal["SPATIAL_DATA_CURSOR_STALE"]

# Currently permitted data operations advertised on a discovered asset.  A grant that
# lacks PREPARE exposes metadata and READ without advertising preparation.
SpatialDataAiOperationV1 = Literal["READ", "PREPARE"]

# Closed adapter failure vocabulary: the Task4 stdio adapter codes plus every reason
# an AI/Core response may already carry.  No raw Core body, path, or exception text.
SpatialDataMcpAdapterCodeV1 = Literal[
    "UNKNOWN_TOOL",
    "INVALID_TOOL_ARGUMENTS",
    "CONFIGURATION_UNAVAILABLE",
    "CORE_UNAVAILABLE",
    "CORE_TIMEOUT",
    "CORE_RESPONSE_TOO_LARGE",
    "INVALID_CORE_RESPONSE",
    "AI_EGRESS_UNACKNOWLEDGED",
    "CONCURRENCY_LIMIT_EXCEEDED",
]
SpatialDataMcpErrorCodeV1 = SpatialDataMcpAdapterCodeV1 | SpatialDataAiReasonV1

_RelativePath = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2048)]

# Route-segment representation matching the Core identity convention: first
# character alphanumeric (excludes "."/"-" dot-segments), total length <= 255.
# Disclosure of `..`, `/`, query/fragment markers, or percent-encoded traversal
# in a descriptor scope is rejected even when the supplied relativePath is the
# exact canonical f-string of that hostile segment.  Old V1 job/source fields
# keep their `Text` representation unchanged.
_ROUTE_SEGMENT_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,254}$"
_ROUTE_SEGMENT_RE = re.compile(_ROUTE_SEGMENT_PATTERN)


def _route_segment(value: str) -> str:
    # Fullmatch discipline (not `match`+`$`, which tolerates one trailing newline)
    # mirrors the Core `is_path_safe_identifier` convention without importing Core.
    if _ROUTE_SEGMENT_RE.fullmatch(value) is None:
        raise ValueError("scope segment must be a route-safe identifier")
    return value


RouteSegment = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=255, pattern=_ROUTE_SEGMENT_PATTERN),
    AfterValidator(_route_segment),
]


class SpatialDataAssetViewV1(SpatialDataModel):
    """Grant-filtered projection of one sealed DSM/ORTHO source for AI discovery."""

    asset_ref: AssetRef
    site_id: Text
    work_area_id: Text
    work_order_id: Text
    epoch_id: Text
    submission_ref: Text
    revision: PositiveInt
    artifact_kind: NativeKind
    lifecycle_state: Literal["SEALED", "SUPERSEDED"]
    observed_sha256: Digest
    observed_size_bytes: PositiveInt
    inspection_report_digest: Digest
    inspector_build_digest: Digest
    observed_crs_identifier: Text
    observed_crs_digest: Digest
    observed_crs_units: Text
    observed_vertical_reference: ObservedVerticalReferenceV1 | None = None
    transform: Transform
    resolution: tuple[Coordinate, Coordinate]
    band_count: PositiveInt
    dtype: Literal["float32", "float64", "uint8"]
    permitted_bounds: Bounds
    capture_started_at: UtcTimestamp | None = None
    capture_ended_at: UtcTimestamp | None = None
    producer_processed_at: UtcTimestamp | None = None
    declaration_recorded_at: UtcTimestamp
    timestamp_provenance: Literal["SUBMISSION_DECLARATION"] = "SUBMISSION_DECLARATION"
    permitted_operations: tuple[SpatialDataAiOperationV1, ...] = Field(min_length=1, max_length=2)
    restrictions: tuple[SpatialDataReasonV1, ...] = Field(default=(), max_length=16)
    attribution: Attribution
    modification_notice: Attribution
    accuracy_assessed: Annotated[StrictBool, Field(json_schema_extra={"const": False})]
    analysis_status: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"

    @model_validator(mode="after")
    def _consistent_native_projection(self) -> Self:
        if self.accuracy_assessed:
            raise ValueError("data preparation does not assess accuracy")
        # Reuse the sibling V1 helpers directly: the AI projection must never
        # silently diverge from source/receipt admission (Primary ruling on M1).
        _native_profile(self.artifact_kind, self.dtype, self.band_count, self.transform)
        a, _, _, _, e, _ = self.transform
        if self.resolution != (a, -e):
            raise ValueError("projection resolution must preserve observed source resolution")
        if len(set(self.permitted_operations)) != len(self.permitted_operations):
            raise ValueError("permitted operations must be unique")
        _capture_interval(self.capture_started_at, self.capture_ended_at)
        return self


class SpatialDataAssetPageV1(SpatialDataModel):
    items: tuple[SpatialDataAssetViewV1, ...] = Field(max_length=200)
    next_cursor: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2048)] | (
        None
    ) = None
    page_complete: StrictBool = True


class SpatialDataFileReferenceV1(SpatialDataModel):
    """Structured descriptor of the canonical Core file route, not a capability URL."""

    reference_version: Literal["spatial-data-file-reference.v1"] = "spatial-data-file-reference.v1"
    site_id: RouteSegment
    work_area_id: RouteSegment
    job_id: JobId
    method: Literal["GET"] = "GET"
    relative_path: _RelativePath
    output_sha256: Digest
    output_size_bytes: PositiveInt
    authentication_required: Annotated[StrictBool, Field(json_schema_extra={"const": True})] = True
    range_supported: Annotated[StrictBool, Field(json_schema_extra={"const": False})] = False

    @model_validator(mode="after")
    def _canonical_route_only(self) -> Self:
        if not self.authentication_required:
            raise ValueError("file delivery always requires authentication")
        if self.range_supported:
            raise ValueError("file delivery does not support ranges")
        canonical = (
            f"/v1/sites/{self.site_id}/work-areas/{self.work_area_id}"
            f"/spatial-data-requests/{self.job_id}/file"
        )
        if self.relative_path != canonical:
            raise ValueError("file reference must use the canonical Core file route")
        return self


class SpatialDataMcpJobViewV1(SpatialDataModel):
    """Exact V1 job plus an optional file descriptor backed by its sealed receipt."""

    job: SpatialDataJobViewV1
    file_reference: SpatialDataFileReferenceV1 | None = None

    @model_validator(mode="after")
    def _reference_binds_completed_available_receipt(self) -> Self:
        reference = self.file_reference
        if reference is None:
            return self
        job = self.job
        receipt = job.receipt
        if (
            job.execution_state is not SpatialDataExecutionStateV1.COMPLETED
            or job.availability is not SpatialDataAvailabilityV1.AVAILABLE
            or receipt is None
        ):
            raise ValueError("file reference requires a COMPLETED and AVAILABLE receipt")
        if (reference.site_id, reference.work_area_id, reference.job_id) != (
            job.site_id,
            job.work_area_id,
            job.job_id,
        ) or (reference.output_sha256, reference.output_size_bytes) != (
            receipt.output_sha256,
            receipt.output_size_bytes,
        ):
            raise ValueError("file reference must bind the authorized job receipt")
        return self


class SpatialDataAiErrorV1(SpatialDataModel):
    """Safe typed AI refusal; the message carries no raw Core body, path, or secret."""

    reason: SpatialDataAiReasonV1
    message: Text
    retryable: StrictBool
    remediation: tuple[SpatialDataRemediationV1, ...] = Field(min_length=1, max_length=16)


class SpatialDataMcpErrorV1(SpatialDataModel):
    """Closed adapter error envelope: code plus bounded existing remediation values."""

    code: SpatialDataMcpErrorCodeV1
    remediation: tuple[SpatialDataRemediationV1, ...] = Field(min_length=1, max_length=16)
