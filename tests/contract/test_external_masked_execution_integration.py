"""Actual generated-byte V3 masked path: GeoTIFF/mask -> binding -> dispatch -> report.

Synthetic local GeoTIFFs only (small 4x4 grids).  No customer, field, or
production data.  All remaining host scope is labelled synthetic/not-field.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import rasterio
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_masked_execution import (
    MaskedExecutionAttemptV3,
    MaskedExecutionAuthorizationV3,
    MaskedWorkerInputV3,
)
from ksi_event_contracts.external_masked_volume import (
    ExclusionMaskBindingV1,
    MaskedCalculationIdentityV3,
    MaskedRelativeVolumeProfileV3,
)
from ksi_event_contracts.external_relative_volume_analysis import (
    AnalysisPolicyV2,
    CalculationIdentityV2,
)
from ksi_processing_controller.external_masked_execution_dispatch import (
    MaskedDispatchInputsV3,
    dispatch_masked_execution_v3,
)
from ksi_processing_controller.external_measurement_algorithms import MeasurementWatchdogV2
from pyproj import CRS
from rasterio.transform import from_origin

ORIGIN_X = 200000.0
ORIGIN_Y = 550000.0
NATIVE_TRANSFORM = (1.0, 0.0, ORIGIN_X, 0.0, -1.0, ORIGIN_Y)
COMPOUND_CRS = CRS.from_user_input("EPSG:5186+5773")
NOW = datetime(2026, 10, 26, tzinfo=UTC)


def _digest(value: str | bytes) -> str:
    raw = value.encode() if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _canonical_digest(value: dict[str, object]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _subject(label: str) -> SealedExternalSubjectV1:
    return SealedExternalSubjectV1(
        organization_id="org-a",
        site_id="site-a",
        work_order_id="order-" + label,
        submission_id="submission-" + label,
        revision=1,
        submission_digest=_digest("submission-" + label),
        manifest_digest=_digest("manifest-" + label),
    )


def _polygon() -> dict[str, object]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [ORIGIN_X, ORIGIN_Y],
                [ORIGIN_X, ORIGIN_Y - 4.0],
                [ORIGIN_X + 4.0, ORIGIN_Y - 4.0],
                [ORIGIN_X + 4.0, ORIGIN_Y],
                [ORIGIN_X, ORIGIN_Y],
            ]
        ],
    }


def _envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=4000000,
        max_streamed_bytes=4000000,
        max_tiff_directories=8,
        max_tiff_entries=128,
        max_pixels=1000000,
        max_bands=4,
        max_blocks=512,
        max_decompressed_bytes=20000000,
        max_sample_bytes=4000000,
        max_geometry_vertices=64,
        max_cpu_seconds=30.0,
        max_memory_bytes=50000000,
        max_workspace_bytes=50000000,
        max_output_bytes=1000000,
        max_tenant_concurrency=2,
        max_queue_depth=4,
        max_deadline_seconds=60.0,
        lease_duration_seconds=600.0,
        max_retry_attempts=2,
    ).sealed()


def _write_geotiffs(tmp_path: Path):
    """Write synthetic baseline/current float64 DSMs plus a uint8 binary mask."""
    transform = from_origin(ORIGIN_X, ORIGIN_Y, 1.0, 1.0)
    baseline_values = np.full((4, 4), 100.0)
    # Known diff: +1 on three cells, -2 on one cell (same known-answer shape).
    diff = np.zeros((4, 4), dtype=np.float64)
    diff[0, 1] = 1.0
    diff[1, 0] = 1.0
    diff[1, 1] = 1.0
    diff[2, 2] = -2.0
    current_values = baseline_values + diff
    mask = np.zeros((4, 4), dtype=np.uint8)
    mask[0, 1] = 1  # exclude one +1 fill cell
    baseline_path = tmp_path / "baseline.tif"
    current_path = tmp_path / "current.tif"
    mask_path = tmp_path / "mask.tif"
    with rasterio.open(
        baseline_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float64",
        crs=COMPOUND_CRS,
        transform=transform,
    ) as dataset:
        dataset.write(baseline_values, 1)
    with rasterio.open(
        current_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float64",
        crs=COMPOUND_CRS,
        transform=transform,
    ) as dataset:
        dataset.write(current_values, 1)
    with rasterio.open(
        mask_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint8",
        crs="EPSG:5186",
        transform=transform,
    ) as dataset:
        dataset.write(mask, 1)
    return baseline_path, current_path, mask_path


def _masked_identity(
    baseline_path: Path, current_path: Path, mask_path: Path
) -> MaskedCalculationIdentityV3:
    from ksi_event_contracts.external_artifact_validation import ObservedVerticalReferenceV1

    vertical = ObservedVerticalReferenceV1(identifier="EPSG:5773", basis="EGM96 height")
    horizontal_wkt = CRS.from_epsg(5186).to_wkt(
        version="WKT2_2019", pretty=False, output_axis_rule=True
    )
    horizontal_digest = _digest(horizontal_wkt)
    source = CalculationIdentityV2(
        calculation_id="calculation-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        work_area_polygon=_polygon(),
        work_area_crs="EPSG:5186",
        work_area_definition_digest=_canonical_digest(
            {"workAreaId": "work-area-a", "crs": "EPSG:5186", "polygon": _polygon()}
        ),
        baseline_subject=_subject("baseline"),
        current_subject=_subject("current"),
        baseline_capture_started_at=datetime(2026, 9, 19, tzinfo=UTC),
        baseline_capture_ended_at=datetime(2026, 9, 19, 1, tzinfo=UTC),
        current_capture_started_at=datetime(2026, 9, 20, tzinfo=UTC),
        current_capture_ended_at=datetime(2026, 9, 20, 1, tzinfo=UTC),
        baseline_dsm_artifact_id="dsm-baseline",
        current_dsm_artifact_id="dsm-current",
        baseline_input_digest=_digest("baseline-input"),
        current_input_digest=_digest("current-input"),
        baseline_dsm_observed_sha256=_digest(baseline_path.read_bytes()),
        current_dsm_observed_sha256=_digest(current_path.read_bytes()),
        baseline_dsm_observed_size_bytes=baseline_path.stat().st_size,
        current_dsm_observed_size_bytes=current_path.stat().st_size,
        baseline_observed_crs_identifier="EPSG:5186",
        current_observed_crs_identifier="EPSG:5186",
        baseline_observed_crs_digest=horizontal_digest,
        current_observed_crs_digest=horizontal_digest,
        baseline_projected_unit="metre",
        current_projected_unit="metre",
        baseline_vertical_reference=vertical,
        current_vertical_reference=vertical,
        baseline_vertical_reference_digest=vertical.canonical_digest(),
        current_vertical_reference_digest=vertical.canonical_digest(),
        baseline_vertical_unit="metre",
        current_vertical_unit="metre",
        baseline_vertical_unit_provenance="OBSERVED_VERTICAL_CRS_AXIS",
        current_vertical_unit_provenance="OBSERVED_VERTICAL_CRS_AXIS",
        baseline_inspection_report_digest=_digest("baseline-report"),
        current_inspection_report_digest=_digest("current-report"),
        baseline_inspection_policy_digest=_digest("baseline-policy"),
        current_inspection_policy_digest=_digest("current-policy"),
        baseline_inspector_build_digest=_digest("baseline-inspector"),
        current_inspector_build_digest=_digest("current-inspector"),
        baseline_transform_digest=_canonical_digest({"transform": list(NATIVE_TRANSFORM)}),
        current_transform_digest=_canonical_digest({"transform": list(NATIVE_TRANSFORM)}),
        baseline_transform=NATIVE_TRANSFORM,
        current_transform=NATIVE_TRANSFORM,
        horizontal_crs_digest=horizontal_digest,
        vertical_reference_digest=vertical.canonical_digest(),
        policy=AnalysisPolicyV2(
            policy_id="relative-volume-v2",
            version=2,
            profile_id="KSI-GIS-RELATIVE-VOLUME-V2",
            profile_digest=_digest("profile"),
            algorithm_digest=_digest("algorithm"),
            config_digest=_digest("config"),
            baseline_grid_rule="BASELINE_NATIVE_NORTH_UP_AFFINE_V1",
            current_elevation_resampling="BILINEAR",
            current_mask_resampling="NEAREST",
            work_area_rasterization="CELL_CENTER",
            minimum_common_valid_fraction=1.0,
            threshold_m=0.0,
            cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
            delta_rule="CURRENT_MINUS_BASELINE",
            uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
        ).sealed(),
        worker_executable_digest=_digest("worker"),
        worker_build_digest=_digest("build"),
        runtime_image_version="2.0.0",
        runtime_image_oci_digest=_digest("oci"),
        dependency_lock_digest=_digest("lock"),
    ).sealed()
    left, bottom = ORIGIN_X, ORIGIN_Y - 4.0
    right, top = ORIGIN_X + 4.0, ORIGIN_Y
    # The mask binding is the Core-sealed observed manifest projection: exact
    # observed bytes plus the exact baseline grid (synthetic, not field).
    binding = ExclusionMaskBindingV1(
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        subject=_subject("mask"),
        mask_artifact_id="mask-artifact-1",
        observed_sha256=_digest(mask_path.read_bytes()),
        observed_size_bytes=mask_path.stat().st_size,
        observed_inspection_report_digest=_digest("mask-report"),
        rows=4,
        columns=4,
        transform=NATIVE_TRANSFORM,
        transform_digest=_canonical_digest({"transform": list(NATIVE_TRANSFORM)}),
        observed_crs_identifier="EPSG:5186",
        observed_crs_digest=horizontal_digest,
        dtype="UINT8",
        band_count=1,
        retain_value=0,
        exclude_value=1,
        nodata_representation="NONE",
        bounds=(left, bottom, right, top),
    ).sealed()
    profile = MaskedRelativeVolumeProfileV3(
        policy_id="masked-relative-volume-v3",
        version=3,
        profile_id="KSI-GIS-MASKED-RELATIVE-VOLUME-V3",
        profile_digest=_digest("masked-profile"),
        algorithm_digest=_digest("masked-algorithm"),
        config_digest=_digest("masked-config"),
        baseline_grid_rule="EXACT_BASELINE_GRID",
        current_elevation_resampling="BILINEAR",
        current_mask_resampling="NEAREST",
        work_area_rasterization="CELL_CENTER",
        exclusion_precedence="WORKAREA_HOLES_THEN_MASK",
        mask_convention="UINT8_SINGLE_BAND_BINARY_0_KEEP_1_EXCLUDE_V1",
        mask_nodata_rule="NO_NODATA",
        minimum_common_valid_fraction=1.0,
        threshold_m=0.0,
        cell_area_rule="ABSOLUTE_AFFINE_DETERMINANT",
        delta_rule="CURRENT_MINUS_BASELINE",
        uncertainty_method="NONE_UNCERTAINTY_M3_NULL_V1",
    ).sealed()
    return MaskedCalculationIdentityV3(
        masked_calculation_id="masked-calculation-1",
        organization_id="org-a",
        site_id="site-a",
        work_area_id="work-area-a",
        source_calculation_identity=source,
        source_calculation_identity_digest=source.canonical_digest(),
        mask_binding=binding,
        mask_binding_digest=binding.canonical_digest(),
        profile=profile,
        masked_profile_digest=profile.canonical_digest(),
        grid_rows=4,
        grid_columns=4,
        horizontal_crs_digest=binding.observed_crs_digest,
    ).sealed()


def test_actual_bytes_binding_attempt_report_and_replay(tmp_path: Path) -> None:
    """End-to-end synthetic: sealed mask -> new binding -> new attempt -> numeric report."""
    baseline_path, current_path, mask_path = _write_geotiffs(tmp_path)
    envelope = _envelope()
    identity = _masked_identity(baseline_path, current_path, mask_path)
    # New V3 authorization/attempt envelope (fence fields live here, not in the report).
    authorization = MaskedExecutionAuthorizationV3(
        authorization_id="authorization-1",
        organization_id="org-a",
        masked_calculation_identity_digest=identity.canonical_digest(),
        masked_profile_digest=identity.masked_profile_digest,
        mask_binding_digest=identity.mask_binding_digest,
        source_calculation_identity_digest=identity.source_calculation_identity_digest,
        admission_digest=_digest("admission"),
        activation_digest=_digest("activation"),
        worker_principal_id="analysis-worker-1",
        resource_envelope=envelope,
        resource_envelope_digest=envelope.canonical_digest(),
        authorized_at=datetime(2026, 10, 26, 1, tzinfo=UTC),
    ).sealed()
    attempt = MaskedExecutionAttemptV3(
        attempt_id="attempt-1",
        authorization=authorization,
        authorization_digest=authorization.canonical_digest(),
        worker_instance_id="masked-worker-instance-1",
        lease_acquisition_id="lease-1",
        lease_generation=1,
        issued_at=datetime(2026, 10, 26, 2, tzinfo=UTC),
        lease_expires_at=datetime(2026, 10, 26, 3, tzinfo=UTC),
    ).sealed()
    expiry = datetime(2026, 10, 26, 2, 30, tzinfo=UTC)
    source = identity.source_calculation_identity
    binding = identity.mask_binding
    worker_input = MaskedWorkerInputV3(
        masked_request_id="request-1",
        attempt=attempt,
        masked_calculation_identity=identity,
        inputs=(
            {
                "role": "BASELINE_DSM",
                "artifactId": source.baseline_dsm_artifact_id,
                "observedSha256": source.baseline_dsm_observed_sha256,
                "observedSizeBytes": source.baseline_dsm_observed_size_bytes,
                "expiresAt": expiry,
            },
            {
                "role": "CURRENT_DSM",
                "artifactId": source.current_dsm_artifact_id,
                "observedSha256": source.current_dsm_observed_sha256,
                "observedSizeBytes": source.current_dsm_observed_size_bytes,
                "expiresAt": expiry,
            },
            {
                "role": "EXCLUSION_MASK",
                "artifactId": binding.mask_artifact_id,
                "observedSha256": binding.observed_sha256,
                "observedSizeBytes": binding.observed_size_bytes,
                "expiresAt": expiry,
            },
        ),  # type: ignore[arg-type]
    )
    outcome = dispatch_masked_execution_v3(
        worker_input=worker_input,
        files=MaskedDispatchInputsV3(
            baseline_path=baseline_path, current_path=current_path, mask_path=mask_path
        ),
        envelope=envelope,
        watchdog=MeasurementWatchdogV2.from_envelope(envelope),
        lease_expires_at=datetime(2026, 10, 26, 3, tzinfo=UTC),
        report_id="report-1",
        computed_at=datetime(2026, 10, 26, 2, 5, tzinfo=UTC),
        reported_at=datetime(2026, 10, 26, 2, 6, tzinfo=UTC),
    )
    assert outcome.report is not None and outcome.failure is None
    numeric = outcome.report.numeric_result
    # Known answer: masked fill 2 / cut 2 / net 0; unmasked fill 3 / cut 2 / net 1.
    assert (numeric.metrics.fill_m3, numeric.metrics.cut_m3, numeric.metrics.net_m3) == (
        2.0,
        2.0,
        0.0,
    )
    assert numeric.impact.unmasked_impact_known is True
    assert (numeric.impact.unmasked_fill_m3, numeric.impact.unmasked_cut_m3) == (3.0, 2.0)
    coverage = numeric.coverage
    assert (
        coverage.original_selected_cell_count,
        coverage.mask_excluded_cell_count,
        coverage.effective_selected_cell_count,
        coverage.common_valid_cell_count,
    ) == (16, 1, 15, 15)
    # Deterministic replay: the same bytes produce the same sealed digests.
    second = dispatch_masked_execution_v3(
        worker_input=worker_input,
        files=MaskedDispatchInputsV3(
            baseline_path=baseline_path, current_path=current_path, mask_path=mask_path
        ),
        envelope=envelope,
        watchdog=MeasurementWatchdogV2.from_envelope(envelope),
        lease_expires_at=datetime(2026, 10, 26, 3, tzinfo=UTC),
        report_id="report-1",
        computed_at=datetime(2026, 10, 26, 2, 5, tzinfo=UTC),
        reported_at=datetime(2026, 10, 26, 2, 6, tzinfo=UTC),
    )
    assert second.report is not None
    assert second.report.report_digest == outcome.report.report_digest
    # Adversarial: a NoData mask is rejected without producing numeric output.
    nodata_path = tmp_path / "mask-nodata.tif"
    transform = from_origin(ORIGIN_X, ORIGIN_Y, 1.0, 1.0)
    mask_array = np.zeros((4, 4), dtype=np.uint8)
    mask_array[0, 1] = 1
    with rasterio.open(
        nodata_path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="uint8",
        crs="EPSG:5186",
        transform=transform,
        nodata=0,
    ) as dataset:
        dataset.write(mask_array, 1)
    nodata_outcome = dispatch_masked_execution_v3(
        worker_input=worker_input,
        files=MaskedDispatchInputsV3(
            baseline_path=baseline_path, current_path=current_path, mask_path=nodata_path
        ),
        envelope=envelope,
        watchdog=MeasurementWatchdogV2.from_envelope(envelope),
        lease_expires_at=datetime(2026, 10, 26, 3, tzinfo=UTC),
        report_id="report-nodata",
        computed_at=datetime(2026, 10, 26, 2, 5, tzinfo=UTC),
        reported_at=datetime(2026, 10, 26, 2, 6, tzinfo=UTC),
    )
    assert nodata_outcome.report is None and nodata_outcome.failure is not None
