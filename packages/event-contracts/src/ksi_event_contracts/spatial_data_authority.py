"""Distinct rights/policy/runtime bindings; none of these grant themselves authority."""

from __future__ import annotations

from typing import Literal, Self

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import Field, field_validator, model_validator

from ksi_event_contracts._spatial_data import (
    AssetRef,
    Attribution,
    Bounds,
    Digest,
    Origin,
    PositiveInt,
    PositiveSeconds,
    SpatialDataDigestModel,
    Text,
    UtcTimestamp,
    require_utc,
)
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.processing_job import ExecutionLocus


class SpatialDataPolicyV1(SpatialDataDigestModel):
    _digest_field = "policy_digest"
    policy_id: Text
    revision: PositiveInt
    resource_envelope: ResourceEnvelopeV1
    max_output_pixels: PositiveInt
    max_output_bytes: PositiveInt
    stream_chunk_bytes: PositiveInt
    max_stream_bytes: PositiveInt
    stream_deadline_seconds: PositiveSeconds
    max_active_jobs_per_organization: PositiveInt
    max_active_downloads_per_organization: PositiveInt
    max_pending_records: PositiveInt
    max_list_records: PositiveInt
    max_snapshot_bytes: PositiveInt
    max_json_bytes: PositiveInt
    max_idempotency_key_bytes: PositiveInt
    lease_seconds: PositiveSeconds
    max_attempts: PositiveInt
    min_retry_backoff_seconds: PositiveSeconds
    max_retry_backoff_seconds: PositiveSeconds
    retention_seconds: PositiveSeconds
    max_cleanup_attempts: PositiveInt
    cleanup_deadline_seconds: PositiveSeconds
    policy_digest: Digest | None = None

    @model_validator(mode="after")
    def _finite_cross_field_envelope(self) -> Self:
        env = self.resource_envelope
        if env.resource_envelope_digest != env.canonical_digest():
            raise ValueError("policy requires an explicitly sealed resource envelope")
        if self.stream_chunk_bytes > min(self.max_output_bytes, self.max_stream_bytes):
            raise ValueError("chunk exceeds output/stream budget")
        if self.max_output_bytes > min(env.max_output_bytes, self.max_stream_bytes):
            raise ValueError("output exceeds envelope/stream budget")
        if self.max_output_pixels > env.max_pixels:
            raise ValueError("output pixels exceed envelope")
        if self.lease_seconds > env.max_deadline_seconds:
            raise ValueError("lease exceeds job deadline")
        if self.max_attempts > env.max_retry_attempts:
            raise ValueError("attempts exceed envelope")
        if self.max_active_jobs_per_organization > env.max_tenant_concurrency:
            raise ValueError("job concurrency exceeds envelope")
        if self.max_pending_records > env.max_queue_depth:
            raise ValueError("pending records exceed envelope queue")
        if self.min_retry_backoff_seconds > self.max_retry_backoff_seconds:
            raise ValueError("retry backoff bounds reversed")
        if self.max_json_bytes > self.max_snapshot_bytes:
            raise ValueError("JSON exceeds snapshot budget")
        # Parent staging + child's immutable copy + candidate + reserved download spools.
        required = 2 * env.max_input_bytes + self.max_output_bytes * (
            1 + self.max_active_downloads_per_organization
        )
        if required > env.max_workspace_bytes:
            raise ValueError("workspace cannot cover staging, candidate and download reservations")
        return self


class SpatialDataGrantV1(SpatialDataDigestModel):
    _digest_field = "grant_digest"
    grant_id: Text
    revision: PositiveInt
    organization_id: Text
    beneficiary_principal_id: Text
    asset_ref: AssetRef
    site_id: Text
    work_area_id: Text
    allowed_bounds: Bounds
    observed_crs_digest: Digest
    operations: tuple[Literal["PREPARE", "READ"], ...] = Field(
        min_length=1, max_length=2, json_schema_extra={"uniqueItems": True}
    )
    purposes: tuple[Literal["GENERAL_DATA_USE", "EXTERNAL_AI"], ...] = Field(
        min_length=1, max_length=2, json_schema_extra={"uniqueItems": True}
    )
    processing_location: ExecutionLocus
    license_provenance_digest: Digest
    attribution: Attribution
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp
    policy_digest: Digest
    grant_digest: Digest | None = None

    @field_validator("operations", "purposes")
    @classmethod
    def _unique_rights(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("rights must be unique")
        return values

    @model_validator(mode="after")
    def _positive_validity(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("grant validity must have positive duration")
        return self

    def is_current_at(self, now: UtcTimestamp) -> bool:
        record = type(self).model_validate(self.__dict__)
        return record.valid_from <= require_utc(now) < record.valid_until


class SpatialDataRevocationV1(SpatialDataDigestModel):
    _digest_field = "revocation_digest"
    grant_id: Text
    revision: PositiveInt
    organization_id: Text
    grant_digest: Digest
    revoked_at: UtcTimestamp
    reason: Text
    revocation_digest: Digest | None = None


class SpatialDataRuntimeV1(SpatialDataDigestModel):
    _digest_field = "runtime_digest"
    preparation_profile: Literal["ksi-native-window.v1"] = "ksi-native-window.v1"
    executable_digest: Digest
    build_digest: Digest
    runtime_image: Text
    runtime_image_version: Text
    runtime_image_digest: Digest
    dependency_lock_digest: Digest
    runtime_digest: Digest | None = None


class SpatialDataActivationV1(SpatialDataDigestModel):
    _digest_field = "activation_digest"
    activation_id: Text
    organization_id: Text
    worker_principal_id: Text
    worker_instance_id: Text
    preparation_profile: Literal["ksi-native-window.v1"] = "ksi-native-window.v1"
    policy_digest: Digest
    runtime_digest: Digest
    trusted_endpoint_origins: tuple[Origin, ...] = Field(
        min_length=1, max_length=16, json_schema_extra={"uniqueItems": True}
    )
    valid_from: UtcTimestamp
    valid_until: UtcTimestamp
    activation_digest: Digest | None = None

    @model_validator(mode="after")
    def _positive_unique_scope(self) -> Self:
        if self.valid_until <= self.valid_from:
            raise ValueError("activation validity must have positive duration")
        if len(set(self.trusted_endpoint_origins)) != len(self.trusted_endpoint_origins):
            raise ValueError("activation origins must be unique")
        return self

    def is_current_at(self, now: UtcTimestamp) -> bool:
        record = type(self).model_validate(self.__dict__)
        return record.valid_from <= require_utc(now) < record.valid_until

    def signing_bytes(self) -> bytes:
        record = type(self).model_validate(self.__dict__)
        return canonical_json_bytes(
            {
                "domain": "ksi-spatial-data-activation.v1",
                "payload": record.model_dump(by_alias=True, mode="json"),
            }
        )
