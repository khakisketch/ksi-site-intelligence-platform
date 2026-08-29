"""Independent checkpoint validation bound to one immutable DSM artifact.

The uploader declares where the checkpoint coordinates came from, but never
declares an RMSE.  A trusted processing worker reads the sealed CSV and DSM
bytes, measures both digests, samples every checkpoint, and reports the
residual aggregates.  Core owns the terminal verdict and journal projection.

This is the missing producer for the existing INV-024 uncertainty path.  It
does not turn an operational relative-volume result into a cadastral or
contract-payment survey: independence is operator-attested and field
acceptance remains a separate gate.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, StringConstraints, field_validator, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.change_detection_result import ArtifactRef
from ksi_event_contracts.design_surface import SHA256_HEX_PATTERN
from ksi_event_contracts.vertical_reference import VerticalReference, VerticalReferenceSource

CHECKPOINT_CSV_CONTENT_TYPE = "text/csv"
CHECKPOINT_CSV_COLUMNS = (
    "checkpoint_id",
    "easting_m",
    "northing_m",
    "elevation_m",
)
CHECKPOINT_FILE_MAX_BYTES = 5 * 1024 * 1024
CHECKPOINT_POINT_MIN = 3
CHECKPOINT_POINT_MAX = 10_000
CHECKPOINT_VALIDATION_PROFILE_ID = "ksi-dsm-checkpoint-nearest-v1"

_PROFILE_SPEC: dict[str, Any] = {
    "columns": list(CHECKPOINT_CSV_COLUMNS),
    "encoding": "utf-8",
    "interpolation": "nearest-pixel-center",
    "invalidPointPolicy": "reject-entire-validation",
    "maxFileBytes": CHECKPOINT_FILE_MAX_BYTES,
    "maxPointCount": CHECKPOINT_POINT_MAX,
    "minPointCount": CHECKPOINT_POINT_MIN,
    "profileId": CHECKPOINT_VALIDATION_PROFILE_ID,
    "rasterBandCount": 1,
    "rasterScaleOffsetPolicy": "identity-only",
}
_PROFILE_BYTES = json.dumps(
    _PROFILE_SPEC, ensure_ascii=False, sort_keys=True, separators=(",", ":")
).encode("utf-8")
CHECKPOINT_VALIDATION_PROFILE_DIGEST = "sha256:" + hashlib.sha256(_PROFILE_BYTES).hexdigest()

_NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CheckpointValidationStatus(StrEnum):
    REGISTERED = "REGISTERED"
    SEALED = "SEALED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class CheckpointValidationRejectionReason(StrEnum):
    CHECKPOINT_DIGEST_MISMATCH = "CHECKPOINT_DIGEST_MISMATCH"
    CHECKPOINT_SIZE_MISMATCH = "CHECKPOINT_SIZE_MISMATCH"
    CHECKPOINT_OBJECT_MISSING = "CHECKPOINT_OBJECT_MISSING"
    DSM_DIGEST_MISMATCH = "DSM_DIGEST_MISMATCH"
    DSM_OBJECT_MISSING = "DSM_OBJECT_MISSING"
    DSM_CRS_MISMATCH = "DSM_CRS_MISMATCH"
    INVALID_CHECKPOINT_CSV = "INVALID_CHECKPOINT_CSV"
    CHECKPOINT_COUNT_OUT_OF_RANGE = "CHECKPOINT_COUNT_OUT_OF_RANGE"
    CHECKPOINT_OUTSIDE_DSM = "CHECKPOINT_OUTSIDE_DSM"
    DSM_NODATA_AT_CHECKPOINT = "DSM_NODATA_AT_CHECKPOINT"
    UNREADABLE_DSM = "UNREADABLE_DSM"
    UNSUPPORTED_DSM = "UNSUPPORTED_DSM"
    INVALID_MEASUREMENT = "INVALID_MEASUREMENT"


class CheckpointFileDeclared(_CamelModel):
    """Operator declaration attached to the sealed CSV; none is measured truth."""

    filename: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=SHA256_HEX_PATTERN)
    size_bytes: int = Field(ge=1, le=CHECKPOINT_FILE_MAX_BYTES)
    crs: _NonBlank
    vertical_reference: VerticalReference
    independent_from_processing_attested: Literal[True]
    independence_basis: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
    ]

    @field_validator("filename")
    @classmethod
    def _filename_is_plain_csv(cls, value: str) -> str:
        if value != value.strip() or "/" in value or "\\" in value or value in {".", ".."}:
            raise ValueError("filename 은 경로가 아닌 단일 파일명이어야 한다")
        if not value.lower().endswith(".csv"):
            raise ValueError("검사점 v1 입력은 .csv 파일만 허용한다")
        return value

    @model_validator(mode="after")
    def _vertical_reference_is_user_declared(self) -> CheckpointFileDeclared:
        if self.vertical_reference.source is not VerticalReferenceSource.USER_DECLARED:
            raise ValueError(
                "checkpoint verticalReference.source 는 user_declared 여야 한다"
            )
        return self


class CheckpointValidationObserved(_CamelModel):
    """Measurements produced by the trusted worker after reading both inputs."""

    checkpoint_sha256: str = Field(pattern=SHA256_HEX_PATTERN)
    checkpoint_size_bytes: int = Field(ge=1, le=CHECKPOINT_FILE_MAX_BYTES)
    dsm_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    dsm_crs: _NonBlank
    point_count: int = Field(ge=CHECKPOINT_POINT_MIN, le=CHECKPOINT_POINT_MAX)
    mean_error_m: float
    mae_m: float = Field(ge=0.0)
    rmse_m: float = Field(ge=0.0)
    max_abs_error_m: float = Field(ge=0.0)
    measured_at: datetime
    measured_by: _NonBlank

    @model_validator(mode="after")
    def _metrics_are_self_consistent(self) -> CheckpointValidationObserved:
        if self.measured_at.tzinfo is None:
            raise ValueError("measuredAt 은 tz-aware 여야 한다")
        metrics = (
            self.mean_error_m,
            self.mae_m,
            self.rmse_m,
            self.max_abs_error_m,
        )
        if not all(math.isfinite(value) for value in metrics):
            raise ValueError("검사점 잔차 통계는 모두 finite 여야 한다")
        tolerance = 1e-12
        if abs(self.mean_error_m) > self.rmse_m + tolerance:
            raise ValueError("abs(meanErrorM) 은 rmseM 보다 클 수 없다")
        if self.mae_m > self.rmse_m + tolerance:
            raise ValueError("maeM 은 rmseM 보다 클 수 없다")
        if self.rmse_m > self.max_abs_error_m + tolerance:
            raise ValueError("rmseM 은 maxAbsErrorM 보다 클 수 없다")
        return self


class CheckpointValidation(_CamelModel):
    """Immutable journal projection for one checkpoint CSV against one DSM."""

    schema_version: Literal["1.0"] = "1.0"
    validation_id: _NonBlank
    organization_id: _NonBlank
    mission_id: _NonBlank
    site_id: _NonBlank
    dsm: ArtifactRef
    dsm_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    dsm_crs: _NonBlank
    dsm_vertical_reference: VerticalReference
    declared: CheckpointFileDeclared
    validation_profile_id: Literal["ksi-dsm-checkpoint-nearest-v1"] = (
        "ksi-dsm-checkpoint-nearest-v1"
    )
    validation_profile_digest: Literal[
        "sha256:be58e685bc92e5aa82003a03da1eb489b44db983b0838c4117afb538879b9b6c"
    ] = "sha256:be58e685bc92e5aa82003a03da1eb489b44db983b0838c4117afb538879b9b6c"
    status: CheckpointValidationStatus
    registered_at: datetime
    registered_by: _NonBlank
    sealed_at: datetime | None = None
    observed: CheckpointValidationObserved | None = None
    rejection_reason: CheckpointValidationRejectionReason | None = None
    rejection_detail: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _state_is_complete(self) -> CheckpointValidation:
        if self.registered_at.tzinfo is None:
            raise ValueError("registeredAt 은 tz-aware 여야 한다")
        if self.sealed_at is not None and self.sealed_at.tzinfo is None:
            raise ValueError("sealedAt 은 tz-aware 여야 한다")
        if self.status is CheckpointValidationStatus.REGISTERED:
            if (
                self.sealed_at is not None
                or self.observed is not None
                or self.rejection_reason is not None
                or self.rejection_detail is not None
            ):
                raise ValueError("REGISTERED 는 seal/observation/rejection 을 가질 수 없다")
        elif self.status is CheckpointValidationStatus.SEALED:
            if (
                self.sealed_at is None
                or self.observed is not None
                or self.rejection_reason is not None
                or self.rejection_detail is not None
            ):
                raise ValueError("SEALED 는 sealedAt 만 가져야 한다")
        elif self.status is CheckpointValidationStatus.VALIDATED:
            if (
                self.sealed_at is None
                or self.observed is None
                or self.rejection_reason is not None
                or self.rejection_detail is not None
            ):
                raise ValueError("VALIDATED 는 sealedAt+observed 가 필요하고 rejection 은 없다")
        elif self.status is CheckpointValidationStatus.REJECTED and (
            self.sealed_at is None or self.rejection_reason is None
        ):
            raise ValueError("REJECTED 는 sealedAt+rejectionReason 이 필요하다")
        return self


def checkpoint_validation_wire_dict(record: CheckpointValidation) -> dict[str, Any]:
    """Canonical JSON-compatible representation used by journal and API."""

    return record.model_dump(by_alias=True, mode="json", exclude_none=False)


__all__ = [
    "CHECKPOINT_CSV_COLUMNS",
    "CHECKPOINT_CSV_CONTENT_TYPE",
    "CHECKPOINT_FILE_MAX_BYTES",
    "CHECKPOINT_POINT_MAX",
    "CHECKPOINT_POINT_MIN",
    "CHECKPOINT_VALIDATION_PROFILE_DIGEST",
    "CHECKPOINT_VALIDATION_PROFILE_ID",
    "CheckpointFileDeclared",
    "CheckpointValidation",
    "CheckpointValidationObserved",
    "CheckpointValidationRejectionReason",
    "CheckpointValidationStatus",
    "checkpoint_validation_wire_dict",
]
