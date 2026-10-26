"""Closed HTTP wire for the optional masked (P2) lane: ingress, V3 execution, handoff.

Additive only.  These models carry HTTP request/response shapes for the new
routers; they create no authority.  Sealed domain records embedded here
(declarations, narrow reports, admissions, V3 numeric reports) are validated
by their own contracts and adjudicated by Core stores at every transition.
No model here accepts URLs, filesystem paths, caller grids, caller profiles,
or registry truth: the client sends opaque ids plus digests, Core resolves
every byte/grid/profile fact from sealed state.

Handoff discipline for the late delta publication lane (parent-owned route):
``MaskedDeltaSourceRefV1`` sends the source calculation identity plus the
mask child only.  Grid, profile, and registry facts are never caller truth;
the delta route resolves them through the Core-bound identity and the
sealed mask manifest behind its own new publication lease.  A completed
masked attempt is never borrowed as a delta read permission.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import Field, StrictInt, StringConstraints, field_validator, model_validator

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import (
    Digest,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_mask_input import (
    MaskChildDeclarationV1,
    MaskInspectionProfileV1,
    MaskObservedManifestV1,
)
from ksi_event_contracts.external_mask_input_report import MaskObservationReportV1
from ksi_event_contracts.external_masked_execution import (
    MaskedAdmissionV3,
    MaskedExecutionAttemptV3,
)
from ksi_event_contracts.external_masked_volume_result import (
    MaskedVolumeCalculationFailureV3,
    MaskedVolumeCalculationReportV3,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
OpaqueId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
DigestText = Digest

MASKED_ATTEMPT_DIGEST_HEADER = "X-Masked-Attempt-Digest"
MASKED_WORKER_INSTANCE_ID_HEADER = "X-Masked-Worker-Instance-Id"
MASKED_INSPECTION_LEASE_ID_HEADER = "X-Masked-Inspection-Lease-Id"

_MASKED_STATUS = Literal["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELED"]
_MASKED_DISPOSITION = Literal[
    "AVAILABLE",
    "REASSESSMENT_REQUIRED",
    "PENDING",
    "FAILED",
    "CANCELED",
    "EXECUTION_DEADLINE_EXPIRED",
    "EXECUTION_RETRY_EXHAUSTED",
]


def _require_opaque(value: str, name: str) -> str:
    """An opaque id names protected bytes; never a URL, path, or capability."""
    lowered = value.lower()
    if (
        "://" in value
        or value.startswith(("/", "\\"))
        or ".." in value
        or "\\" in value
        or "\n" in value
        or "\r" in value
        or lowered.startswith(("http:", "https:", "s3:", "file:", "cap:"))
    ):
        raise ValueError(f"{name} must be an opaque identifier, never a URL, path, or capability")
    return value


def _require_utc(value: datetime, name: str) -> datetime:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise ValueError(f"{name} must be UTC")
    return value


class _MaskedApiModel(_CamelModel):
    """Frozen HTTP wire; revalidated before Core use."""


class MaskUploadGrantRequestV1(_MaskedApiModel):
    """Bounded raw-upload grant intent; Core mints the server object key."""

    mask_artifact_id: OpaqueId
    subject_digest: DigestText
    declared_sha256: DigestText
    declared_size_bytes: StrictInt = Field(gt=0)
    ttl_seconds: StrictInt = Field(default=3600, ge=1, le=24 * 3600)

    @field_validator("mask_artifact_id")
    @classmethod
    def _artifact_is_opaque(cls, value: str) -> str:
        return _require_opaque(value, "maskArtifactId")


class MaskUploadGrantViewV1(_MaskedApiModel):
    """Issued grant: id plus expiry only.  No object key, path, or URL leaves Core."""

    grant_id: Text
    mask_child_id: Text
    mask_artifact_id: Text
    expires_at: datetime

    @field_validator("mask_artifact_id")
    @classmethod
    def _artifact_is_opaque(cls, value: str) -> str:
        return _require_opaque(value, "maskArtifactId")

    @field_validator("expires_at")
    @classmethod
    def _expires_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "expiresAt")


class MaskUploadSealViewV1(_MaskedApiModel):
    """Sealed upload receipt: observed byte identity only, no path."""

    mask_child_id: Text
    mask_artifact_id: Text
    observed_sha256: DigestText
    observed_size_bytes: StrictInt = Field(gt=0)

    @field_validator("mask_artifact_id")
    @classmethod
    def _artifact_is_opaque(cls, value: str) -> str:
        return _require_opaque(value, "maskArtifactId")


class MaskChildViewV1(_MaskedApiModel):
    """Declared intent plus the Core-sealed observed manifest (when sealed)."""

    declaration: MaskChildDeclarationV1
    manifest: MaskObservedManifestV1 | None = None


class MaskSealViewV1(_MaskedApiModel):
    """Worker-sealed manifest receipt (no declaration re-read is required)."""

    manifest: MaskObservedManifestV1


class MaskSourceContextViewV1(_MaskedApiModel):
    """Core-resolved declaration anchor for one sealed AP source identity.

    Sealed source copies Core rechecks at declare/seal/bind time; this view
    creates no admission and asserts no numeric result.  The Console builds
    only opaque ids plus hash/size from it — the grid always comes from the
    Core anchor, never from user input.  ``maxMaskBytes`` is the explicit
    native envelope cap (``min(maxInputBytes, maxStreamedBytes)``); no
    retention is guessed.  Provisional sources stay provisional here.
    """

    source_calculation_identity_digest: DigestText
    baseline_subject: SealedExternalSubjectV1
    current_subject: SealedExternalSubjectV1
    baseline_dsm_artifact_id: OpaqueId
    masked_profile_digest: DigestText
    inspection_profile_digest: DigestText
    max_mask_bytes: StrictInt = Field(gt=0)
    max_mask_pixels: StrictInt = Field(gt=0)
    source_disposition: Literal["ADMIT_PROVISIONAL", "ADMIT_EVALUATED"]
    assessed_at: datetime

    @field_validator("baseline_dsm_artifact_id")
    @classmethod
    def _artifact_is_opaque(cls, value: str) -> str:
        return _require_opaque(value, "baselineDsmArtifactId")

    @field_validator("assessed_at")
    @classmethod
    def _assessed_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "assessedAt")


class MaskInspectionLeaseRequestV1(_MaskedApiModel):
    """Server-issued inspection job request: exact byte/subject/anchor identity.

    The worker supplies the sealed subject copies Core must bind; Core
    resolves the baseline anchor grid itself and returns the expected grid
    facts the contained inspector must prove.  No caller grid is accepted.
    """

    site_id: Text
    work_area_id: Text
    mask_artifact_id: OpaqueId
    subject_digest: DigestText
    baseline_subject: SealedExternalSubjectV1
    baseline_dsm_artifact_id: OpaqueId
    inspection_profile_digest: DigestText
    worker_instance_id: Text
    lease_acquisition_id: Text

    @field_validator("mask_artifact_id", "baseline_dsm_artifact_id")
    @classmethod
    def _artifacts_are_opaque(cls, value: str) -> str:
        return _require_opaque(value, "artifactId")


class MaskInspectionLeaseViewV1(_MaskedApiModel):
    """Fenced inspection job plus the exact expected grid from the anchor."""

    lease_id: Text
    mask_child_id: Text
    worker_instance_id: Text
    lease_acquisition_id: Text
    issued_at: datetime
    expires_at: datetime
    expected_rows: StrictInt = Field(gt=0)
    expected_columns: StrictInt = Field(gt=0)
    expected_transform: tuple[float, float, float, float, float, float]
    expected_transform_digest: DigestText
    expected_crs_identifier: Text
    expected_crs_digest: DigestText

    @field_validator("issued_at", "expires_at")
    @classmethod
    def _lease_times_are_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "lease time")


class MaskInspectionReportRequestV1(_MaskedApiModel):
    """Fenced narrow report: live lease binding plus sealed worker evidence."""

    lease_id: Text
    worker_instance_id: Text
    report: MaskObservationReportV1
    inspection_profile: MaskInspectionProfileV1


MaskInspectionFailureReasonV1 = Literal[
    "MASK_NODATA_REJECTED",
    "MASK_BYTES_MISMATCH",
    "MASK_RESOURCE_EXCEEDED",
    "MASK_INSPECTION_FAILED",
]
"""Closed worker-observed failure reason (no raw paths or native traces).

Deterministic rejections (NoData, non-binary/wrong-grid bytes, resource
caps) mean the caller must fix the file under a fresh child.  The generic
``MASK_INSPECTION_FAILED`` covers unexpected worker IO; the bytes stay
untouched either way and numeric content is never produced.
"""

MaskInspectionTerminalStatusV1 = Literal["REJECTED", "FAILED"]

_MASK_REJECTED_REASONS: tuple[str, ...] = (
    "MASK_NODATA_REJECTED",
    "MASK_BYTES_MISMATCH",
    "MASK_RESOURCE_EXCEEDED",
)


def inspection_failure_status_for(reason_code: str) -> MaskInspectionTerminalStatusV1:
    """Deterministic rejections close the child; unexpected IO fails it."""
    return "REJECTED" if reason_code in _MASK_REJECTED_REASONS else "FAILED"


class MaskInspectionFailureRequestV1(_MaskedApiModel):
    """Fenced worker failure: live lease binding plus one closed reason."""

    lease_id: Text
    worker_instance_id: Text
    inspection_profile_digest: DigestText
    reason_code: MaskInspectionFailureReasonV1


class MaskInspectionFailureViewV1(_MaskedApiModel):
    """Terminal inspection outcome (never revived, never numeric)."""

    mask_child_id: Text
    status: MaskInspectionTerminalStatusV1
    reason_code: MaskInspectionFailureReasonV1
    failed_at: datetime

    @field_validator("failed_at")
    @classmethod
    def _failed_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "failedAt")


MaskInspectionStatusV1 = Literal["PENDING", "RUNNING", "COMPLETED", "REJECTED", "FAILED"]


class MaskInspectionStatusViewV1(_MaskedApiModel):
    """Human-readable inspection state: manifest or terminal failure wins.

    ``PENDING`` means announced without an outcome yet (bytes may still be
    unsealed); ``RUNNING`` a live lease; ``COMPLETED`` a sealed manifest;
    ``REJECTED``/``FAILED`` the terminal worker failure with its reason.
    """

    mask_child_id: Text
    site_id: Text
    work_area_id: Text
    status: MaskInspectionStatusV1
    reason_code: MaskInspectionFailureReasonV1 | None = None
    checked_at: datetime
    manifest_digest: DigestText | None = None

    @field_validator("checked_at")
    @classmethod
    def _checked_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "checkedAt")

    @model_validator(mode="after")
    def _binds_status_to_outcome(self) -> Self:
        if self.status in ("REJECTED", "FAILED"):
            if self.reason_code is None:
                raise ValueError("a terminal inspection state must carry its reason")
        elif self.reason_code is not None:
            raise ValueError("only a terminal inspection state carries a reason")
        if self.status == "COMPLETED" and self.manifest_digest is None:
            raise ValueError("a completed inspection must bind its sealed manifest")
        if self.status != "COMPLETED" and self.manifest_digest is not None:
            raise ValueError("only a completed inspection binds a manifest")
        return self


class MaskedCalculationCreateRequestV1(_MaskedApiModel):
    """Create a V3 calculation from Core-resolved source evidence plus mask child.

    Only digests and opaque ids travel here.  Core constructs the masked
    identity itself from the current AP assessment plus the current sealed
    mask manifest via ``bind_identity``; no V2 numeric result is required
    and none is accepted as the masked result key.
    """

    masked_calculation_id: OpaqueId
    source_calculation_identity_digest: DigestText
    mask_child_id: OpaqueId
    request_id: OpaqueId
    idempotency_key: Text

    @field_validator("masked_calculation_id", "mask_child_id", "request_id")
    @classmethod
    def _ids_are_opaque(cls, value: str) -> str:
        return _require_opaque(value, "identifier")


class MaskedCalculationCreatedViewV1(_MaskedApiModel):
    """Issued V3 calculation: fenced identity plus its admission."""

    request_id: Text
    masked_calculation_identity_digest: DigestText
    status: _MASKED_STATUS
    admission: MaskedAdmissionV3


class MaskedCalculationDetailViewV1(_MaskedApiModel):
    """Current V3 view: fresh disposition, admission, and numeric report when available."""

    request_id: Text
    organization_id: Text
    site_id: Text
    work_area_id: Text
    masked_calculation_identity_digest: DigestText
    status: _MASKED_STATUS
    disposition: _MASKED_DISPOSITION
    admission: MaskedAdmissionV3 | None = None
    report: MaskedVolumeCalculationReportV3 | None = None

    @model_validator(mode="after")
    def _available_carries_numeric(self) -> Self:
        if self.disposition == "AVAILABLE" and self.report is None:
            raise ValueError("an AVAILABLE masked calculation must carry its numeric report")
        if self.disposition != "AVAILABLE" and self.report is not None:
            raise ValueError("only an AVAILABLE masked calculation carries a numeric report")
        return self


class MaskedCalculationMutationViewV1(_MaskedApiModel):
    """Fenced worker mutation receipt: request plus its live attempt."""

    request_id: Text
    status: _MASKED_STATUS
    attempt: MaskedExecutionAttemptV3 | None = None


class MaskedLeaseRequestV1(_MaskedApiModel):
    worker_instance_id: Text
    lease_acquisition_id: Text


class MaskedReportRequestV1(_MaskedApiModel):
    attempt: MaskedExecutionAttemptV3
    report: MaskedVolumeCalculationReportV3


class MaskedFailureRequestV1(_MaskedApiModel):
    attempt: MaskedExecutionAttemptV3
    failure: MaskedVolumeCalculationFailureV3


class MaskedRenewRequestV1(_MaskedApiModel):
    attempt: MaskedExecutionAttemptV3


class MaskInspectionPendingItemV1(_MaskedApiModel):
    """One announced child with sealed bytes but no sealed manifest yet."""

    mask_child_id: Text
    site_id: Text
    work_area_id: Text
    declaration: MaskChildDeclarationV1


class MaskInspectionPendingListV1(_MaskedApiModel):
    """Bounded worker-only inspection discovery (up to 50)."""

    items: tuple[MaskInspectionPendingItemV1, ...] = Field(max_length=50)


class MaskedCalculationPendingItemV1(_MaskedApiModel):
    """One Core-bound V3 calculation awaiting or reclaimable by a worker."""

    request_id: Text
    masked_calculation_identity_digest: DigestText
    execution_state: Literal["QUEUED", "RUNNING"]
    issued_at: datetime

    @field_validator("issued_at")
    @classmethod
    def _issued_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, "issuedAt")


class MaskedCalculationPendingListV1(_MaskedApiModel):
    """Bounded worker-only calculation discovery (up to 50)."""

    items: tuple[MaskedCalculationPendingItemV1, ...] = Field(max_length=50)


class MaskedBytesSliceViewV1(_MaskedApiModel):
    """Bounded protected-bytes slice: canonical base64, never a path or URL."""

    artifact_id: Text
    offset: StrictInt = Field(ge=0)
    content_base64: Annotated[
        str,
        StringConstraints(max_length=1_398_104),
    ]

    @field_validator("artifact_id")
    @classmethod
    def _artifact_is_opaque(cls, value: str) -> str:
        return _require_opaque(value, "artifactId")

    @field_validator("content_base64")
    @classmethod
    def _slice_is_canonical_bounded(cls, value: str) -> str:
        import base64 as _base64

        try:
            decoded = _base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("content must be canonical base64") from exc
        if len(decoded) > 1024 * 1024 or _base64.b64encode(decoded).decode("ascii") != value:
            raise ValueError("byte slice must be canonical base64 within one MiB")
        return value


class MaskedDeltaSourceRefV1(_MaskedApiModel):
    """Late-publication handoff: source identity plus mask child only.

    The parent delta route resolves every grid/profile/registry fact itself
    through the Core-bound masked identity and the sealed mask manifest
    behind its own new publication lease.  Caller grid/profile truth is
    never accepted here.
    """

    source_calculation_identity_digest: DigestText
    source_numeric_result_identity_digest: DigestText
    source_coverage_witness_digest: DigestText
    mask_child_id: OpaqueId

    @field_validator("mask_child_id")
    @classmethod
    def _child_is_opaque(cls, value: str) -> str:
        return _require_opaque(value, "maskChildId")


__all__ = [
    "MASKED_ATTEMPT_DIGEST_HEADER",
    "MASKED_INSPECTION_LEASE_ID_HEADER",
    "MASKED_WORKER_INSTANCE_ID_HEADER",
    "MaskChildViewV1",
    "MaskInspectionFailureReasonV1",
    "MaskInspectionFailureRequestV1",
    "MaskInspectionFailureViewV1",
    "MaskInspectionLeaseRequestV1",
    "MaskInspectionLeaseViewV1",
    "MaskInspectionPendingItemV1",
    "MaskInspectionPendingListV1",
    "MaskInspectionReportRequestV1",
    "MaskInspectionStatusV1",
    "MaskInspectionStatusViewV1",
    "MaskInspectionTerminalStatusV1",
    "MaskSealViewV1",
    "MaskSourceContextViewV1",
    "MaskUploadGrantRequestV1",
    "MaskUploadGrantViewV1",
    "MaskUploadSealViewV1",
    "MaskedBytesSliceViewV1",
    "MaskedCalculationCreateRequestV1",
    "MaskedCalculationCreatedViewV1",
    "MaskedCalculationDetailViewV1",
    "MaskedCalculationMutationViewV1",
    "MaskedCalculationPendingItemV1",
    "MaskedCalculationPendingListV1",
    "MaskedDeltaSourceRefV1",
    "MaskedFailureRequestV1",
    "MaskedLeaseRequestV1",
    "MaskedRenewRequestV1",
    "MaskedReportRequestV1",
    "inspection_failure_status_for",
]
