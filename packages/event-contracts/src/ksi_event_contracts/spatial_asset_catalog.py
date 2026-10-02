"""Bounded read contracts for customer-owned spatial artifact metadata."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import Field, StrictFloat, StrictInt, StringConstraints

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_reconstruction import ExternalDeclaredVerticalReferenceV1
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
_DeclaredHash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_AssetRef = Annotated[str, StringConstraints(pattern=r"^ksa-v1-[0-9a-f]{64}$")]
_Cursor = Annotated[str, StringConstraints(min_length=1, max_length=1024)]
_SCOPE_NOTE: Final = (
    "Register one WorkOrder per WorkArea for catalog attribution; multi-area records are omitted."
)


class SpatialAssetLifecycleStateV1(StrEnum):
    UNSEALED = "UNSEALED"
    SEALED = "SEALED"
    SUPERSEDED = "SUPERSEDED"


class SpatialAssetDeclaredFactsV1(_CamelModel):
    """Customer-supplied metadata. It must never be presented as measured fact."""

    fact_class: Literal["DECLARED"] = "DECLARED"
    file_name: _Text
    format: _Text
    content_type: _Text
    sha256: _DeclaredHash
    size_bytes: int = Field(ge=1, le=2**63 - 1)
    crs: str | None = Field(default=None, max_length=8192)
    vertical_reference: ExternalDeclaredVerticalReferenceV1 | None = None
    gsd_m: float | None = Field(default=None, gt=0)
    submitted_at: datetime
    producer_completed_at: datetime | None = None
    capture_started_at: datetime | None = None
    capture_ended_at: datetime | None = None


class SpatialAssetObservedFactsV1(_CamelModel):
    """Core-sealed byte observations; storage paths and capabilities are excluded."""

    fact_class: Literal["OBSERVED"] = "OBSERVED"
    manifest_digest: _Digest
    observed_at: datetime
    sha256: _DeclaredHash
    size_bytes: int = Field(ge=1, le=2**63 - 1)
    content_type: _Text


class SpatialAssetObservedVerticalReferenceV1(_CamelModel):
    identifier: Annotated[str, StringConstraints(min_length=1, max_length=8192)]
    basis: Annotated[str, StringConstraints(min_length=1, max_length=8192)]


class SpatialAssetInspectedRasterFactsV1(_CamelModel):
    """Measured raster geometry tied to its exact inspection report and build."""

    fact_class: Literal["INSPECTED"] = "INSPECTED"
    source_report_digest: _Digest
    inspector_build_digest: _Digest
    observed_crs_identifier: Annotated[str, StringConstraints(min_length=1, max_length=8192)]
    observed_crs_wkt: Annotated[str, StringConstraints(min_length=1, max_length=65536)] | None = (
        None
    )
    observed_crs_digest: _Digest
    observed_vertical_reference: SpatialAssetObservedVerticalReferenceV1 | None = None
    transform: tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat]
    footprint_wkt: Annotated[str, StringConstraints(min_length=1, max_length=65536)]
    footprint_digest: _Digest
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)


class SpatialAssetInspectionV1(_CamelModel):
    """Compact inspection status, never an analysis or accuracy conclusion."""

    state: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    report_digest: _Digest | None = None
    outcome: Literal["MEASURED", "NOT_APPLICABLE", "REJECTED"] | None = None
    reason: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    inspector_build_digest: _Digest | None = None
    raster: SpatialAssetInspectedRasterFactsV1 | None = None


class SpatialAssetCatalogItemV1(_CamelModel):
    asset_ref: _AssetRef
    site_id: _Text
    work_area_id: _Text
    work_order_id: _Text
    observation_epoch_id: _Text
    submission_ref: Annotated[str, StringConstraints(pattern=r"^ers-v1-[0-9a-f]{64}$")]
    revision: int = Field(ge=1)
    artifact_id: _Text
    kind: ProcessingArtifactKind
    lifecycle_state: SpatialAssetLifecycleStateV1
    declared: SpatialAssetDeclaredFactsV1
    observed: SpatialAssetObservedFactsV1 | None = None
    inspection: SpatialAssetInspectionV1
    data_access: Literal["NOT_AVAILABLE_FROM_CATALOG"] = "NOT_AVAILABLE_FROM_CATALOG"
    analysis_status: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    supported_actions: tuple[Literal["VIEW_METADATA"], ...] = ("VIEW_METADATA",)


class SpatialAssetCatalogPageV1(_CamelModel):
    contract_version: Literal["spatial-asset-catalog-page.v1"] = "spatial-asset-catalog-page.v1"
    site_id: _Text
    work_area_id: _Text
    scope_policy: Literal["SINGLE_WORK_AREA_WORK_ORDERS_ONLY"] = "SINGLE_WORK_AREA_WORK_ORDERS_ONLY"
    scope_note: Literal[
        "Register one WorkOrder per WorkArea for catalog attribution; "
        "multi-area records are omitted."
    ] = _SCOPE_NOTE
    assets: tuple[SpatialAssetCatalogItemV1, ...] = Field(max_length=50)
    next_cursor: _Cursor | None = None
    has_more: bool


class SpatialAssetCatalogDetailV1(SpatialAssetCatalogItemV1):
    """The exact same fact projection used in list pages."""
