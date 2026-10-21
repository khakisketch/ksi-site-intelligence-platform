"""Server-owned read projection for the SWX-1 ordinary-entry question.

Which observations exist for a Site/WorkArea, which asset versions each has,
what is view-available, and which observation is the ordinary-entry default.
The client must not invent quality ranking, dates, versions, or eligibility.

This module introduces no new identity, no new eligibility computation, and no
byte authority. Every fact is projected from existing Core sources:

- observation grouping: existing ``observationEpochId`` (deterministic
  organization/WorkOrder/cycle identity, never a date bucket);
- per-version identity/lifecycle/observed facts: existing
  ``SpatialAssetCatalog`` items (submission/ref/revision/artifact identity);
- inspection facts: existing ``ExternalArtifactInspectionStore`` bounded
  snapshots (``public_snapshot_bounded``);
- display readiness: existing ``public_display_state`` receipt state
  (``SEALED`` receipt only; never a quantitative verdict);
- chronological candidacy: the exact-interval predicate shape already used by
  ``ExternalAnalysisFacade.observation_options`` (capture interval required,
  UTC, positive) — date-only/unknown stay browsable but excluded.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import Field, StringConstraints

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
_DeclaredHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_AssetRef = Annotated[str, StringConstraints(pattern=r"^ksa-v1-[0-9a-f]{64}$")]
_SubmissionRef = Annotated[str, StringConstraints(pattern=r"^ers-v1-[0-9a-f]{64}$")]
_Cursor = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
_EpochId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_SCOPE_NOTE: Final = (
    "Register one WorkOrder per WorkArea for workspace attribution; multi-area records are omitted."
)


class WorkspaceCapturePrecisionV1(StrEnum):
    EXACT_INTERVAL = "EXACT_INTERVAL"
    DATE_ONLY = "DATE_ONLY"
    UNKNOWN = "UNKNOWN"


class WorkspaceChronologyReasonV1(StrEnum):
    EXACT_INTERVAL_CANDIDATE = "EXACT_INTERVAL_CANDIDATE"
    DATE_ONLY_NOT_ORDERABLE = "DATE_ONLY_NOT_ORDERABLE"
    UNKNOWN_CAPTURE_NOT_ORDERABLE = "UNKNOWN_CAPTURE_NOT_ORDERABLE"
    CAPTURE_CONFLICT_NOT_ORDERABLE = "CAPTURE_CONFLICT_NOT_ORDERABLE"


class WorkspaceEntryDefaultReasonV1(StrEnum):
    LATEST_EXACT_VIEW_AVAILABLE = "LATEST_EXACT_VIEW_AVAILABLE"
    NO_OBSERVATIONS = "NO_OBSERVATIONS"
    NO_VIEW_AVAILABLE_OBSERVATION = "NO_VIEW_AVAILABLE_OBSERVATION"
    NO_EXACT_CAPTURE_CANDIDATE = "NO_EXACT_CAPTURE_CANDIDATE"
    CAPTURE_TIE_AMBIGUOUS = "CAPTURE_TIE_AMBIGUOUS"


class WorkspaceDisplayStateV1(StrEnum):
    SEALED = "SEALED"
    NOT_SEALED = "NOT_SEALED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


class WorkspaceCaptureFactsV1(_CamelModel):
    """Declared capture timing at its real precision; never synthesized."""

    fact_class: Literal["DECLARED_CAPTURE"] = "DECLARED_CAPTURE"
    precision: WorkspaceCapturePrecisionV1
    capture_started_at: datetime | None = None
    capture_ended_at: datetime | None = None
    capture_date: date | None = None


class WorkspaceAssetVersionViewV1(_CamelModel):
    """One exact artifact version with separately typed disposition facts."""

    asset_ref: _AssetRef
    submission_ref: _SubmissionRef
    revision: int = Field(ge=1)
    artifact_id: _Text
    kind: ProcessingArtifactKind
    lifecycle_state: Literal["UNSEALED", "SEALED", "SUPERSEDED"]
    capture: WorkspaceCaptureFactsV1
    declared_crs: str | None = Field(default=None, max_length=8192)
    declared_vertical_reference_present: bool
    declared_gsd_m: float | None = Field(default=None, gt=0)
    submitted_at: datetime
    observed_sha256: _DeclaredHash | None = None
    observed_size_bytes: int | None = Field(default=None, ge=1)
    observed_at: datetime | None = None
    inspection_state: _Text
    inspection_outcome: Literal["MEASURED", "NOT_APPLICABLE", "REJECTED"] | None = None
    inspection_reason: str | None = Field(default=None, min_length=1, max_length=128)
    inspected_raster_available: bool
    display_state: WorkspaceDisplayStateV1
    display_ready: bool
    chronology: WorkspaceChronologyReasonV1
    chronology_candidate: bool
    quantitative_eligibility: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"


class WorkspaceObservationViewV1(_CamelModel):
    """One observation (one exact epoch identity) with its asset versions."""

    observation_epoch_id: _EpochId
    work_order_id: _Text
    capture: WorkspaceCaptureFactsV1
    capture_sources_agree: bool
    versions: tuple[WorkspaceAssetVersionViewV1, ...] = Field(min_length=1, max_length=400)
    view_available: bool
    view_unavailable_reason: str | None = Field(default=None, min_length=1, max_length=128)
    view_asset_ref: _AssetRef | None = None
    newer_revision_pending: bool
    newer_revision_state: str | None = Field(default=None, min_length=1, max_length=128)
    chronology_candidate: bool
    has_sealed_version: bool


class WorkspaceEntryDefaultV1(_CamelModel):
    """The single server-decided ordinary-entry observation, or an explicit reason."""

    observation_epoch_id: _EpochId | None = None
    view_asset_ref: _AssetRef | None = None
    reason: WorkspaceEntryDefaultReasonV1
    detail: _Text
    tied_observation_epoch_ids: tuple[_EpochId, ...] = ()


class SiteSpatialWorkspacePageV1(_CamelModel):
    contract_version: Literal["site-spatial-workspace-page.v1"] = "site-spatial-workspace-page.v1"
    site_id: _Text
    work_area_id: _Text
    scope_policy: Literal["SINGLE_WORK_AREA_WORK_ORDERS_ONLY"] = (
        "SINGLE_WORK_AREA_WORK_ORDERS_ONLY"
    )
    scope_note: Literal[
        "Register one WorkOrder per WorkArea for workspace attribution; "
        "multi-area records are omitted."
    ] = _SCOPE_NOTE
    observations: tuple[WorkspaceObservationViewV1, ...] = Field(max_length=50)
    entry_default: WorkspaceEntryDefaultV1
    next_cursor: _Cursor | None = None
    has_more: bool


__all__ = [
    "SiteSpatialWorkspacePageV1",
    "WorkspaceAssetVersionViewV1",
    "WorkspaceCaptureFactsV1",
    "WorkspaceCapturePrecisionV1",
    "WorkspaceChronologyReasonV1",
    "WorkspaceDisplayStateV1",
    "WorkspaceEntryDefaultReasonV1",
    "WorkspaceEntryDefaultV1",
    "WorkspaceObservationViewV1",
]
