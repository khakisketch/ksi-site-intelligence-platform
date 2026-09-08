"""Synthetic contract fixtures for external-artifact queue tests only.

They establish no parser, producer, capacity, tenant, or deployment evidence.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ksi_core.evidence import DigestBoundUploadCapability, ObjectStorageObservation
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    ExternalArtifactInspectionReportV1,
    ExternalInspectionMeasurementPayloadV1,
    ExternalValidationPolicyV1,
    NodataRepresentation,
    PolicyStatus,
    RasterMeasurementsV1,
    ResourceEnvelopeV1,
    SealedArtifactBindingV1,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_reconstruction import (
    ExternalArtifactDeclarationV1,
    ExternalReconstructionManifestEntryV1,
    ExternalReconstructionManifestV1,
    ExternalReconstructionSubmissionV1,
    ExternalReconstructionSubmissionV1Input,
    ExternalReconstructionSubmissionV1Producer,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind

NOW = datetime(2026, 9, 7, tzinfo=UTC)
WORKER_A = "123e4567-e89b-42d3-a456-426614174000"
WORKER_B = "123e4567-e89b-42d3-a456-426614174001"
ACQUISITION = "123e4567-e89b-42d3-a456-426614174002"
ACQUISITION_B = "123e4567-e89b-42d3-a456-426614174003"
ACQUISITION_C = "123e4567-e89b-42d3-a456-426614174004"


def digest(marker: str) -> str:
    return f"sha256:{marker * 64}"


def subject() -> SealedExternalSubjectV1:
    submission = sealed_submission()
    manifest = sealed_manifest()
    assert submission.submission_digest is not None
    assert manifest.manifest_digest is not None
    return SealedExternalSubjectV1(
        organization_id=submission.organization_id,
        site_id=submission.site_id,
        work_order_id="work-order-1",
        submission_id=submission.submission_id,
        revision=submission.revision,
        submission_digest=submission.submission_digest,
        manifest_digest=manifest.manifest_digest,
    )


def envelope() -> ResourceEnvelopeV1:
    return ResourceEnvelopeV1(
        max_input_bytes=1024,
        max_streamed_bytes=1024,
        max_tiff_directories=4,
        max_tiff_entries=32,
        max_pixels=1000,
        max_bands=4,
        max_blocks=64,
        max_decompressed_bytes=8192,
        max_sample_bytes=8192,
        max_geometry_vertices=64,
        max_cpu_seconds=2.0,
        max_memory_bytes=16384,
        max_workspace_bytes=16384,
        max_output_bytes=16384,
        max_tenant_concurrency=1,
        max_queue_depth=4,
        max_deadline_seconds=10.0,
        lease_duration_seconds=4.0,
        max_retry_attempts=2,
    ).sealed()


def policy_template() -> ExternalValidationPolicyV1:
    limits = envelope()
    return ExternalValidationPolicyV1(
        policy_id="policy-1",
        version=1,
        status=PolicyStatus.ACTIVE,
        parser_build_digest=digest("d"),
        grammar_digest=digest("e"),
        resource_envelope=limits,
        resource_envelope_digest=limits.resource_envelope_digest,
        authority_record_digest=digest("f"),
        inspection_rule_ids=("TRANSIENT_IMMEDIATE_RETRY_V1",),
        evidence_rule_ids=("synthetic-test-rule",),
        compatibility_mapping_digests=(),
        synthetic_test_only=True,
    ).sealed()


def report(
    *,
    request_id: str,
    policy: ExternalValidationPolicyV1,
    worker: str = WORKER_A,
    acquisition: str = ACQUISITION,
    generation: int = 1,
    marker: str = "c",
) -> ExternalArtifactInspectionReportV1:
    sealed_subject = subject()
    assert policy.policy_digest is not None
    binding = SealedArtifactBindingV1(artifact_id="ortho", observed_sha256=digest("c"))
    payload = ExternalInspectionMeasurementPayloadV1(
        subject_digest=sealed_subject.canonical_digest(),
        sealed_manifest_digest=sealed_subject.manifest_digest,
        inspection_policy_digest=policy.policy_digest,
        inspector_build_digest=policy.parser_build_digest,
        artifact_bindings=(binding,),
        outcomes=(
            ArtifactInspectionOutcomeV1(
                artifact_id="ortho",
                observed_sha256=binding.observed_sha256,
                outcome=ArtifactOutcome.MEASURED,
                measurements=RasterMeasurementsV1(
                    observed_crs_identifier="EPSG:5186",
                    observed_crs_digest=digest(marker),
                    transform=(1.0, 0.0, 0.0, 0.0, -1.0, 2.0),
                    footprint_wkt="POLYGON((0 0,2 0,2 2,0 2,0 0))",
                    footprint_digest=digest(marker),
                    width=2,
                    height=2,
                    band_count=1,
                    dtype="uint8",
                    layout="striped",
                    nodata_representation=NodataRepresentation.NONE,
                    valid_pixel_count=4,
                ),
            ),
        ),
    )
    return ExternalArtifactInspectionReportV1(
        report_id=f"inspection-report-{marker}",
        request_id=request_id,
        subject=sealed_subject,
        subject_digest=sealed_subject.canonical_digest(),
        sealed_manifest_digest=sealed_subject.manifest_digest,
        inspection_policy_digest=policy.policy_digest,
        inspector_build_digest=policy.parser_build_digest,
        measurement_payload=payload,
        worker_instance_id=worker,
        lease_acquisition_id=acquisition,
        lease_generation=generation,
        reported_at=NOW,
    ).sealed()


def sealed_submission() -> ExternalReconstructionSubmissionV1:
    return ExternalReconstructionSubmissionV1(
        submission_id="submission-1",
        revision=1,
        organization_id="organization-1",
        site_id="site-1",
        observation_epoch_id="obs-epoch-1",
        submitted_at=NOW,
        submitted_by="operator-1",
        producer_declaration=ExternalReconstructionSubmissionV1Producer(
            software_name="Mapper",
            software_version="1",
            build_identifier=None,
            producer_run_identifier=None,
            configuration_digest=None,
            completed_at=None,
        ),
        input_declaration=ExternalReconstructionSubmissionV1Input(
            raw_media_stored_by_ksi=False,
            original_retention_locus="customer_workstation",
        ),
        artifacts=(
            ExternalArtifactDeclarationV1(
                artifact_id="ortho",
                kind=ProcessingArtifactKind.ORTHO,
                file_name="ortho.tif",
                format="GeoTIFF",
                content_type="application/octet-stream",
                declared_sha256="c" * 64,
                declared_size_bytes=12,
            ),
        ),
    ).sealed()


def sealed_manifest() -> ExternalReconstructionManifestV1:
    submission = sealed_submission()
    object_key = "external-reconstruction/v1/synthetic-ortho"
    manifest = ExternalReconstructionManifestV1.from_submission(
        submission,
        manifest_id="manifest-1",
        observed_at=NOW,
        observed_by_service="synthetic-storage",
        organization_id=submission.organization_id,
        site_id=submission.site_id,
        observation_epoch_id=submission.observation_epoch_id,
        entries=(
            ExternalReconstructionManifestEntryV1(
                artifact_id="ortho",
                kind=ProcessingArtifactKind.ORTHO,
                object_key=object_key,
                observed_sha256="c" * 64,
                observed_size_bytes=12,
                observed_content_type="application/octet-stream",
            ),
        ),
    )
    return manifest


class SyntheticStorage:
    """Storage-shaped test double; signed URLs/headers stay out of journal assertions."""

    def __init__(self) -> None:
        self.objects: dict[str, ObjectStorageObservation] = {}
        self.last_put_key: str | None = None

    def presigned_get(self, object_key: str, *, ttl: timedelta) -> str:
        del ttl
        return f"https://storage.invalid/get/{object_key}"

    def presigned_put(self, object_key: str, *, content_type: str, ttl: timedelta) -> str:
        del content_type, ttl
        return f"https://storage.invalid/put/{object_key}"

    def put_bytes(self, object_key: str, data: bytes, *, content_type: str) -> None:
        self.objects[object_key] = ObjectStorageObservation(
            object_key=object_key,
            exists=True,
            size_bytes=len(data),
            sha256=None,
            content_type=content_type,
        )

    def get_bytes(self, object_key: str) -> bytes:
        raise KeyError(object_key)

    def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)

    def presigned_put_bound_digest(
        self, object_key: str, *, content_type: str, content_digest: str, ttl: timedelta
    ) -> DigestBoundUploadCapability:
        del ttl
        self.last_put_key = object_key
        return DigestBoundUploadCapability(
            upload_url=f"https://storage.invalid/put/{object_key}",
            required_headers={
                "Content-Type": content_type,
                "x-amz-checksum-sha256": content_digest,
            },
        )

    def observe_object(self, object_key: str) -> ObjectStorageObservation:
        return self.objects.get(
            object_key, ObjectStorageObservation(object_key=object_key, exists=False)
        )


SyntheticObservation = ObjectStorageObservation
