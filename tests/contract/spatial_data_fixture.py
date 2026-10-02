"""Explicit small local spatial-data authority; never production defaults."""

from datetime import UTC, datetime, timedelta
from typing import Any

from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    RasterMeasurementsV1,
    ResourceEnvelopeV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.spatial_data import (
    SpatialDataAttemptV1,
    SpatialDataFrozenJobV1,
    SpatialDataReceiptV1,
    SpatialDataRequestV1,
    SpatialDataSourceV1,
)
from ksi_event_contracts.spatial_data_authority import (
    SpatialDataActivationV1,
    SpatialDataGrantV1,
    SpatialDataPolicyV1,
    SpatialDataRevocationV1,
    SpatialDataRuntimeV1,
)

NOW = datetime(2026, 10, 1, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
ASSET = "ksa-v1-" + "b" * 64
JOB_ID = "sdj-v1-00000000-0000-4000-8000-000000000001"


def make_envelope(**overrides: Any) -> ResourceEnvelopeV1:
    payload: dict[str, Any] = dict(
        max_input_bytes=4096,
        max_streamed_bytes=4096,
        max_tiff_directories=8,
        max_tiff_entries=128,
        max_pixels=4096,
        max_bands=4,
        max_blocks=64,
        max_decompressed_bytes=32768,
        max_sample_bytes=32768,
        max_geometry_vertices=32,
        max_cpu_seconds=10.0,
        max_memory_bytes=1_048_576,
        max_workspace_bytes=32768,
        max_output_bytes=8192,
        max_tenant_concurrency=2,
        max_queue_depth=8,
        max_deadline_seconds=30.0,
        lease_duration_seconds=5.0,
        max_retry_attempts=3,
    )
    payload.update(overrides)
    return ResourceEnvelopeV1(**payload).sealed()


def make_request(**overrides: Any) -> SpatialDataRequestV1:
    payload: dict[str, Any] = dict(
        asset_ref=ASSET,
        requested_bounds=(0, 0, 1, 1),
        observed_crs_digest=DIGEST,
        resolution_mode="NATIVE",
        purpose="GENERAL_DATA_USE",
    )
    payload.update(overrides)
    return SpatialDataRequestV1(**payload)


def make_policy(**overrides: Any) -> SpatialDataPolicyV1:
    payload: dict[str, Any] = dict(
        policy_id="local-test-only",
        revision=1,
        resource_envelope=make_envelope(),
        max_output_pixels=1024,
        max_output_bytes=4096,
        stream_chunk_bytes=512,
        max_stream_bytes=4096,
        stream_deadline_seconds=10.0,
        max_active_jobs_per_organization=2,
        max_active_downloads_per_organization=2,
        max_pending_records=8,
        max_list_records=8,
        max_snapshot_bytes=1_048_576,
        max_json_bytes=65536,
        max_idempotency_key_bytes=255,
        lease_seconds=5.0,
        max_attempts=3,
        min_retry_backoff_seconds=1.0,
        max_retry_backoff_seconds=5.0,
        retention_seconds=3600.0,
        max_cleanup_attempts=3,
        cleanup_deadline_seconds=10.0,
    )
    payload.update(overrides)
    return SpatialDataPolicyV1(**payload).sealed()


def make_grant(**overrides: Any) -> SpatialDataGrantV1:
    payload: dict[str, Any] = dict(
        grant_id="local-grant",
        revision=1,
        organization_id="org-local",
        beneficiary_principal_id="reader-local",
        asset_ref=ASSET,
        site_id="site-local",
        work_area_id="area-local",
        allowed_bounds=(0, 0, 10, 10),
        observed_crs_digest=DIGEST,
        operations=("PREPARE", "READ"),
        purposes=("GENERAL_DATA_USE",),
        processing_location="site_onprem",
        license_provenance_digest=DIGEST,
        attribution="Synthetic local fixture; no accuracy claim",
        valid_from=NOW,
        valid_until=NOW + timedelta(hours=1),
        policy_digest=make_policy().policy_digest,
    )
    payload.update(overrides)
    return SpatialDataGrantV1(**payload).sealed()


def make_runtime(**overrides: Any) -> SpatialDataRuntimeV1:
    payload: dict[str, Any] = dict(
        preparation_profile="ksi-native-window.v1",
        executable_digest=DIGEST,
        build_digest=DIGEST,
        runtime_image="registry.invalid/ksi-worker:local-test",
        runtime_image_version="local-test",
        runtime_image_digest=DIGEST,
        dependency_lock_digest=DIGEST,
    )
    payload.update(overrides)
    return SpatialDataRuntimeV1(**payload).sealed()


def make_activation(**overrides: Any) -> SpatialDataActivationV1:
    payload: dict[str, Any] = dict(
        activation_id="local-activation",
        organization_id="org-local",
        worker_principal_id="worker-local",
        worker_instance_id="instance-local",
        preparation_profile="ksi-native-window.v1",
        policy_digest=make_policy().policy_digest,
        runtime_digest=make_runtime().runtime_digest,
        trusted_endpoint_origins=("https://store.invalid",),
        valid_from=NOW,
        valid_until=NOW + timedelta(hours=1),
    )
    payload.update(overrides)
    return SpatialDataActivationV1(**payload).sealed()


def make_revocation(**overrides: Any) -> SpatialDataRevocationV1:
    grant = make_grant()
    payload: dict[str, Any] = dict(
        grant_id=grant.grant_id,
        revision=grant.revision,
        organization_id=grant.organization_id,
        grant_digest=grant.grant_digest,
        revoked_at=NOW,
        reason="OWNER_REVOKED",
    )
    payload.update(overrides)
    return SpatialDataRevocationV1(**payload).sealed()


def make_measurements(**overrides: Any) -> RasterMeasurementsV1:
    # Shape-only fixture. Runtime source tests must run the genuine inspector.
    payload: dict[str, Any] = dict(
        observed_crs_identifier="EPSG:7850",
        observed_crs_digest=DIGEST,
        transform=(1.0, 0.0, 0.0, 0.0, -1.0, 10.0),
        footprint_wkt="POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))",
        footprint_digest=DIGEST,
        width=10,
        height=10,
        band_count=1,
        dtype="float32",
        layout="GEOTIFF_STRIPED_V1",
        nodata_representation="NONE",
        valid_pixel_count=100,
    )
    payload.update(overrides)
    return RasterMeasurementsV1(**payload)


def make_source(**overrides: Any) -> SpatialDataSourceV1:
    subject = SealedExternalSubjectV1(
        organization_id="org-local",
        site_id="site-local",
        work_order_id="order-local",
        submission_id="submission-local",
        revision=1,
        submission_digest=DIGEST,
        manifest_digest=DIGEST,
    )
    payload: dict[str, Any] = dict(
        asset_ref=ASSET,
        site_id=subject.site_id,
        work_area_id="area-local",
        work_order_id=subject.work_order_id,
        epoch_id="epoch-local",
        submission_ref="ref-local",
        revision=subject.revision,
        artifact_id="artifact-local",
        artifact_kind="dsm",
        sealed_subject=subject,
        observed_sha256=DIGEST,
        observed_size_bytes=4096,
        inspection=ArtifactInspectionOutcomeV1(
            artifact_id="artifact-local",
            observed_sha256=DIGEST,
                outcome=ArtifactOutcome.MEASURED,
            measurements=make_measurements(),
        ),
        inspection_report_digest=DIGEST,
        inspector_build_digest=DIGEST,
        work_area_boundary_digest=DIGEST,
        observed_crs_units="metre",
        declaration_recorded_at=NOW,
    )
    payload.update(overrides)
    return SpatialDataSourceV1(**payload).sealed()


def make_job(**overrides: Any) -> SpatialDataFrozenJobV1:
    payload: dict[str, Any] = dict(
        job_id=JOB_ID,
        organization_id="org-local",
        requester_principal_id="reader-local",
        site_id="site-local",
        work_area_id="area-local",
        request=make_request(),
        source=make_source(),
        grant=make_grant(),
        policy=make_policy(),
        runtime=make_runtime(),
        idempotency_key_hash=DIGEST,
        request_fingerprint=make_request().canonical_digest(),
        created_at=NOW,
        deadline=NOW + timedelta(seconds=30),
    )
    payload.update(overrides)
    return SpatialDataFrozenJobV1(**payload).sealed()


def make_attempt(**overrides: Any) -> SpatialDataAttemptV1:
    payload: dict[str, Any] = dict(
        job_id=JOB_ID,
        frozen_job_digest=make_job().job_digest,
        attempt_number=1,
        fence=1,
        worker_principal_id="worker-local",
        worker_instance_id="instance-local",
        acquisition_key_hash=DIGEST,
        acquired_at=NOW,
        lease_until=NOW + timedelta(seconds=5),
    )
    payload.update(overrides)
    return SpatialDataAttemptV1(**payload).sealed()


def make_receipt(**overrides: Any) -> SpatialDataReceiptV1:
    job = make_job()
    payload: dict[str, Any] = dict(
        job_id=JOB_ID,
        job_digest=job.job_digest,
        source_digest=job.source.source_digest,
        request_digest=job.request.canonical_digest(),
        preparation_profile="ksi-native-window.v1",
        runtime_digest=job.runtime.runtime_digest,
        policy_digest=job.policy.policy_digest,
        grant_digest=job.grant.grant_digest,
        artifact_id="artifact-local",
        artifact_kind="dsm",
        source_sha256=DIGEST,
        source_size_bytes=4096,
        requested_bounds=(0, 0, 1, 1),
        requested_crs_digest=DIGEST,
        actual_bounds=(0, 0, 1, 1),
        pixel_window=(0, 1, 9, 10),
        width=1,
        height=1,
        transform=(1.0, 0.0, 0.0, 0.0, -1.0, 1.0),
        source_resolution=(1.0, 1.0),
        source_transform=make_measurements().transform,
        observed_crs_identifier="EPSG:7850",
        observed_crs_digest=DIGEST,
        band_count=1,
        dtype="float32",
        nodata_representation="NONE",
        valid_pixel_count=1,
        output_sha256="sha256:" + "c" * 64,
        output_size_bytes=128,
        accuracy_assessed=False,
        prepared_at=NOW + timedelta(seconds=2),
        declaration_recorded_at=NOW,
        attribution="Synthetic local fixture",
        modification_notice="Native rectangular crop",
        limitations=("UNKNOWN_VERTICAL_REFERENCE",),
    )
    payload.update(overrides)
    return SpatialDataReceiptV1(**payload).sealed()
