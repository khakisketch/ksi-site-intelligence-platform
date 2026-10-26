"""Exact single-asset metadata description for one sealed customer artifact.

This is an additive read projection over the exact stores behind the V1
spatial-asset catalog: it reuses the same asset identity (``assetRef``),
lifecycle, declared/observed/inspection facts and Core scope checks, and only
enriches them with already-stored provenance (producer/capture declarations
from the exact submission revision, including V3 unknown-producer and
date-only/unknown-capture honesty) and already-inspected raster detail
(band/dtype/layout/NoData/valid pixels, CRS-derived horizontal units, and
rotation-aware pixel resolution).

It creates no new asset registry, identity, parser, policy, or analysis
status. ``kind`` stays a customer declaration (``SEMANTIC_KIND_IS_DECLARED``),
analysis stays ``NOT_EVALUATED``, and this endpoint grants no byte storage or
download. File-read metadata is not physical datum or producer truth. Missing
facts stay null with their fact class and genuine report/build bindings;
nothing is invented (no fabricated ``"unknown"`` strings, no midnight
timestamps, no unread source fetches).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Final, Literal

from pydantic import Field, StrictFloat, StrictInt, StringConstraints

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import NodataRepresentation
from ksi_event_contracts.external_reconstruction import (
    ExternalDerivativeExportV3,
    ExternalUpstreamSourceReferenceV3,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_event_contracts.spatial_asset_catalog import (
    SpatialAssetDeclaredFactsV1,
    SpatialAssetInspectionV1,
    SpatialAssetLifecycleStateV1,
    SpatialAssetObservedFactsV1,
    SpatialAssetObservedVerticalReferenceV1,
)

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_Digest = Annotated[str, StringConstraints(pattern=r"^sha256:[0-9a-f]{64}$")]
_AssetRef = Annotated[str, StringConstraints(pattern=r"^ksa-v1-[0-9a-f]{64}$")]
_CrsText = Annotated[str, StringConstraints(min_length=1, max_length=8192)]
_WktText = Annotated[str, StringConstraints(min_length=1, max_length=65536)]
_UnitText = Annotated[str, StringConstraints(min_length=1, max_length=256)]
_NoteText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]

_LIMITATIONS: Final = (
    "SEMANTIC_KIND_IS_DECLARED",
    "ANALYSIS_NOT_EVALUATED",
    "NO_ORIGINAL_STORAGE_OR_DOWNLOAD_FROM_THIS_ENDPOINT",
)


class SpatialAssetProducerProvenanceV1(_CamelModel):
    """Who the customer says produced the bytes. A declaration, never KSI observation.

    V1/V2 submissions always carry a software name and version, so their
    knowledge is ``DECLARED`` by construction. V3 carries its own explicit
    ``producerKnowledge`` (``DECLARED``/``PARTIAL``/``UNKNOWN``) with nulls for
    unknown parts; the fabricated label ``"unknown"`` never appears here.
    """

    fact_class: Literal["DECLARED"] = "DECLARED"
    producer_knowledge: Literal["DECLARED", "PARTIAL", "UNKNOWN"]
    software_name: _Text | None = None
    software_version: _Text | None = None
    build_identifier: _Text | None = None
    producer_run_identifier: _Text | None = None
    configuration_digest: _Digest | None = None
    completed_at: datetime | None = None
    source_note: _NoteText | None = None


class SpatialAssetCaptureProvenanceV1(_CamelModel):
    """What the customer declares about capture timing and original retention.

    Exact intervals stay strict datetimes only when the submission carries
    both bounds; a known calendar date without time stays date-only; unknown
    timing carries no date or timestamps at all. Raw capture bytes are never
    stored by KSI (``rawMediaStoredByKsi`` is always false); the locus says
    where the customer claims the originals live.
    """

    fact_class: Literal["DECLARED"] = "DECLARED"
    capture_basis: Literal["EXACT_INTERVAL", "DATE_ONLY", "UNKNOWN"]
    capture_started_at: datetime | None = None
    capture_ended_at: datetime | None = None
    capture_date: date | None = None
    raw_media_stored_by_ksi: Literal[False] = False
    original_retention_locus: Literal["customer_workstation", "upstream_source", "unknown"]
    original_retention_detail: _NoteText | None = None
    local_input_manifest_digest: _Digest | None = None
    image_count: StrictInt | None = Field(default=None, ge=1, le=10_000_000)


class SpatialAssetPixelResolutionV1(_CamelModel):
    """Native pixel size derived from the inspected affine transform.

    Resolution is the axis norm (``hypot(a, d)`` / ``hypot(b, e)`` for GDAL
    order ``(a, b, c, d, e, f)``), never the naive ``abs(a)``/``abs(e)`` which
    understates rotated rasters. ``transform_is_rotated`` is set exactly when
    the inspected shear terms are nonzero. Values are expressed in
    ``horizontal_units`` of the enclosing raster detail; when units are
    unknown the numbers still describe pixel geometry, not meters.
    """

    fact_class: Literal["INSPECTED"] = "INSPECTED"
    source_report_digest: _Digest
    inspector_build_digest: _Digest
    resolution_x: StrictFloat = Field(gt=0)
    resolution_y: StrictFloat = Field(gt=0)
    transform_is_rotated: bool


class SpatialAssetInspectedRasterDetailV1(_CamelModel):
    """Full measured raster facts tied to their exact inspection report and build.

    Present only for a ``MEASURED`` outcome. A DSM without observed vertical
    reference keeps ``observedVerticalReference`` null; horizontal units are
    derived from the exact inspected CRS only (never the declared CRS) and
    stay null when the inspected CRS is absent or unresolvable.
    """

    fact_class: Literal["INSPECTED"] = "INSPECTED"
    source_report_digest: _Digest
    inspector_build_digest: _Digest
    observed_crs_identifier: _CrsText
    observed_crs_wkt: _WktText | None = None
    observed_crs_digest: _Digest
    observed_vertical_reference: SpatialAssetObservedVerticalReferenceV1 | None = None
    transform: tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat]
    footprint_wkt: _WktText
    footprint_digest: _Digest
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)
    band_count: StrictInt = Field(gt=0)
    dtype: _Text
    layout: _Text
    nodata_representation: NodataRepresentation
    nodata_value: StrictFloat | None = None
    valid_pixel_count: StrictInt = Field(ge=0)
    horizontal_units: _UnitText | None = None
    pixel_resolution: SpatialAssetPixelResolutionV1 | None = None


class SpatialAssetDescriptionV1(_CamelModel):
    """Exact enriched metadata view for one catalog asset reference."""

    contract_version: Literal["spatial-asset-description.v1"] = "spatial-asset-description.v1"
    asset_ref: _AssetRef
    site_id: _Text
    work_area_id: _Text
    work_order_id: _Text
    observation_epoch_id: _Text
    submission_ref: Annotated[str, StringConstraints(pattern=r"^ers-v1-[0-9a-f]{64}$")]
    revision: int = Field(ge=1)
    artifact_id: _Text
    kind: ProcessingArtifactKind
    semantic_kind_note: Literal["SEMANTIC_KIND_IS_DECLARED"] = "SEMANTIC_KIND_IS_DECLARED"
    lifecycle_state: SpatialAssetLifecycleStateV1
    declared: SpatialAssetDeclaredFactsV1
    observed: SpatialAssetObservedFactsV1 | None = None
    inspection: SpatialAssetInspectionV1
    producer: SpatialAssetProducerProvenanceV1
    capture: SpatialAssetCaptureProvenanceV1
    upstream_source: ExternalUpstreamSourceReferenceV3 | None = None
    derivative_export: ExternalDerivativeExportV3 | None = None
    raster: SpatialAssetInspectedRasterDetailV1 | None = None
    data_access: Literal["NOT_AVAILABLE_FROM_CATALOG"] = "NOT_AVAILABLE_FROM_CATALOG"
    analysis_status: Literal["NOT_EVALUATED"] = "NOT_EVALUATED"
    limitations: tuple[
        Literal[
            "SEMANTIC_KIND_IS_DECLARED",
            "ANALYSIS_NOT_EVALUATED",
            "NO_ORIGINAL_STORAGE_OR_DOWNLOAD_FROM_THIS_ENDPOINT",
        ],
        ...,
    ] = _LIMITATIONS
    supported_actions: tuple[Literal["VIEW_METADATA"], ...] = ("VIEW_METADATA",)


__all__ = [
    "SpatialAssetCaptureProvenanceV1",
    "SpatialAssetDescriptionV1",
    "SpatialAssetInspectedRasterDetailV1",
    "SpatialAssetPixelResolutionV1",
    "SpatialAssetProducerProvenanceV1",
]
