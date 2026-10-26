"""Pure projection from exact Core records to the asset description DTO.

Every value here is already stored: customer declarations come from the exact
sealed submission revision (V1/V2/V3 shapes preserved, unknowns stay null),
and raster facts come from the genuine inspection report outcome bound to the
same revision. Nothing is fetched, inferred, or invented:

- horizontal units are derived from the exact *inspected* CRS only (WKT plus
  identifier cross-check, mirroring the delivery source guards); any absence
  or mismatch yields null, never the declared CRS;
- pixel resolution is the affine axis norm with an explicit rotation flag,
  never the naive ``abs(a)``/``abs(e)`` which understates rotated rasters;
- a non-``MEASURED`` outcome yields no raster detail at all, so a DSM-only
  record without vertical/NoData facts keeps those fields null with the
  report/build binding intact.
"""

from __future__ import annotations

import math
from typing import Any

from ksi_event_contracts.external_artifact_validation import ArtifactOutcome
from ksi_event_contracts.external_reconstruction import (
    ExternalReconstructionSubmissionV1,
    ExternalReconstructionSubmissionV2,
    ExternalReconstructionSubmissionV3,
)
from ksi_event_contracts.spatial_asset_catalog import (
    SpatialAssetCatalogItemV1,
    SpatialAssetObservedVerticalReferenceV1,
)
from ksi_event_contracts.spatial_asset_description import (
    SpatialAssetCaptureProvenanceV1,
    SpatialAssetDescriptionV1,
    SpatialAssetInspectedRasterDetailV1,
    SpatialAssetPixelResolutionV1,
    SpatialAssetProducerProvenanceV1,
)
from pyproj import CRS
from pyproj.exceptions import CRSError


def horizontal_units_from_inspected_crs(*, crs_identifier: str, crs_wkt: str | None) -> str | None:
    """Return the inspected CRS horizontal unit name, or null when not exactly known.

    Both the stored WKT and the stored identifier must parse to the same
    two-axis, single-unit, non-compound projected/geographic CRS. Declared CRS
    values are never consulted here.
    """
    if crs_wkt is None:
        return None
    try:
        from_wkt = CRS.from_wkt(crs_wkt)
        if (
            len(from_wkt.axis_info) != 2
            or from_wkt.is_compound
            or from_wkt.is_geocentric
            or not (from_wkt.is_projected or from_wkt.is_geographic)
            or not from_wkt.equals(CRS.from_user_input(crs_identifier))
            or len({axis.unit_name for axis in from_wkt.axis_info}) != 1
        ):
            return None
        return from_wkt.axis_info[0].unit_name
    except CRSError:
        return None


def pixel_resolution_from_transform(
    *,
    transform: tuple[float, float, float, float, float, float],
    source_report_digest: str,
    inspector_build_digest: str,
) -> SpatialAssetPixelResolutionV1 | None:
    """Derive native pixel size from a GDAL-order affine, rotation-aware.

    ``resolution_x = hypot(a, d)`` and ``resolution_y = hypot(b, e)``; the
    rotated flag is set exactly when a shear term is nonzero. Degenerate or
    non-finite results yield null rather than a fabricated size.
    """
    a, b, _c, d, e, _f = transform
    resolution_x = math.hypot(a, d)
    resolution_y = math.hypot(b, e)
    if not (
        math.isfinite(resolution_x)
        and math.isfinite(resolution_y)
        and resolution_x > 0
        and resolution_y > 0
    ):
        return None
    return SpatialAssetPixelResolutionV1(
        source_report_digest=source_report_digest,
        inspector_build_digest=inspector_build_digest,
        resolution_x=resolution_x,
        resolution_y=resolution_y,
        transform_is_rotated=(b != 0.0 or d != 0.0),
    )


def producer_provenance_from_submission(submission: Any) -> SpatialAssetProducerProvenanceV1:
    """Project the customer producer declaration; unknowns stay null."""
    producer = submission.producer_declaration
    if isinstance(
        submission, (ExternalReconstructionSubmissionV1, ExternalReconstructionSubmissionV2)
    ):
        return SpatialAssetProducerProvenanceV1(
            producer_knowledge="DECLARED",
            software_name=producer.software_name,
            software_version=producer.software_version,
            build_identifier=producer.build_identifier,
            producer_run_identifier=producer.producer_run_identifier,
            configuration_digest=producer.configuration_digest,
            completed_at=producer.completed_at,
            source_note=None,
        )
    if isinstance(submission, ExternalReconstructionSubmissionV3):
        return SpatialAssetProducerProvenanceV1(
            producer_knowledge=producer.producer_knowledge,
            software_name=producer.software_name,
            software_version=producer.software_version,
            build_identifier=producer.build_identifier,
            producer_run_identifier=producer.producer_run_identifier,
            configuration_digest=producer.configuration_digest,
            completed_at=producer.completed_at,
            source_note=producer.source_note,
        )
    raise TypeError("unsupported external reconstruction submission version")


def capture_provenance_from_submission(submission: Any) -> SpatialAssetCaptureProvenanceV1:
    """Project the customer capture/retention declaration; no time is invented."""
    declared = submission.input_declaration
    if isinstance(
        submission, (ExternalReconstructionSubmissionV1, ExternalReconstructionSubmissionV2)
    ):
        exact = declared.capture_started_at is not None or declared.capture_ended_at is not None
        return SpatialAssetCaptureProvenanceV1(
            capture_basis="EXACT_INTERVAL" if exact else "UNKNOWN",
            capture_started_at=declared.capture_started_at,
            capture_ended_at=declared.capture_ended_at,
            capture_date=None,
            raw_media_stored_by_ksi=declared.raw_media_stored_by_ksi,
            original_retention_locus=declared.original_retention_locus,
            original_retention_detail=None,
            local_input_manifest_digest=declared.local_input_manifest_digest,
            image_count=declared.image_count,
        )
    if isinstance(submission, ExternalReconstructionSubmissionV3):
        return SpatialAssetCaptureProvenanceV1(
            capture_basis=declared.capture_basis,
            capture_started_at=declared.capture_started_at,
            capture_ended_at=declared.capture_ended_at,
            capture_date=declared.capture_date,
            raw_media_stored_by_ksi=declared.raw_media_stored_by_ksi,
            original_retention_locus=declared.original_retention_locus,
            original_retention_detail=declared.original_retention_detail,
            local_input_manifest_digest=declared.local_input_manifest_digest,
            image_count=declared.image_count,
        )
    raise TypeError("unsupported external reconstruction submission version")


def raster_detail_from_snapshot(
    *, artifact_id: str, snapshot: Any
) -> SpatialAssetInspectedRasterDetailV1 | None:
    """Project full measured raster facts, or null without a MEASURED outcome."""
    report = snapshot.report if snapshot is not None else None
    if report is None or report.report_digest is None:
        return None
    outcome = next(
        (item for item in report.measurement_payload.outcomes if item.artifact_id == artifact_id),
        None,
    )
    if (
        outcome is None
        or outcome.outcome != ArtifactOutcome.MEASURED
        or outcome.measurements is None
    ):
        return None
    measured = outcome.measurements
    report_digest = report.report_digest
    build_digest = report.inspector_build_digest
    vertical = measured.observed_vertical_reference
    return SpatialAssetInspectedRasterDetailV1(
        source_report_digest=report_digest,
        inspector_build_digest=build_digest,
        observed_crs_identifier=measured.observed_crs_identifier,
        observed_crs_wkt=measured.observed_crs_wkt,
        observed_crs_digest=measured.observed_crs_digest,
        observed_vertical_reference=(
            SpatialAssetObservedVerticalReferenceV1(
                identifier=vertical.identifier,
                basis=vertical.basis,
            )
            if vertical is not None
            else None
        ),
        transform=measured.transform,
        footprint_wkt=measured.footprint_wkt,
        footprint_digest=measured.footprint_digest,
        width=measured.width,
        height=measured.height,
        band_count=measured.band_count,
        dtype=measured.dtype,
        layout=measured.layout,
        nodata_representation=measured.nodata_representation,
        nodata_value=measured.nodata_value,
        valid_pixel_count=measured.valid_pixel_count,
        horizontal_units=horizontal_units_from_inspected_crs(
            crs_identifier=measured.observed_crs_identifier,
            crs_wkt=measured.observed_crs_wkt,
        ),
        pixel_resolution=pixel_resolution_from_transform(
            transform=measured.transform,
            source_report_digest=report_digest,
            inspector_build_digest=build_digest,
        ),
    )


def build_spatial_asset_description(
    *,
    item: SpatialAssetCatalogItemV1,
    record: Any,
    snapshot: Any,
) -> SpatialAssetDescriptionV1:
    """Assemble the enriched view from the exact catalog item, revision, and snapshot."""
    submission = record.submission
    upstream_source = getattr(submission.input_declaration, "upstream_source", None)
    derivative_export = getattr(submission.input_declaration, "derivative_export", None)
    return SpatialAssetDescriptionV1(
        asset_ref=item.asset_ref,
        site_id=item.site_id,
        work_area_id=item.work_area_id,
        work_order_id=item.work_order_id,
        observation_epoch_id=item.observation_epoch_id,
        submission_ref=item.submission_ref,
        revision=item.revision,
        artifact_id=item.artifact_id,
        kind=item.kind,
        lifecycle_state=item.lifecycle_state,
        declared=item.declared,
        observed=item.observed,
        inspection=item.inspection,
        producer=producer_provenance_from_submission(submission),
        capture=capture_provenance_from_submission(submission),
        upstream_source=upstream_source,
        derivative_export=derivative_export,
        raster=raster_detail_from_snapshot(artifact_id=item.artifact_id, snapshot=snapshot),
    )
