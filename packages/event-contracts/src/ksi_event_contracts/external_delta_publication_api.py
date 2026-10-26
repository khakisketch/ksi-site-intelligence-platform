"""Closed additive delta-publication HTTP/MCP shapes; frozen Analysis stays unchanged."""

from __future__ import annotations

import base64
import hashlib
import math
from datetime import UTC, datetime
from typing import Annotated, Literal, Self

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import (
    Field,
    StrictFloat,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import Digest
from ksi_event_contracts.external_masked_volume import DeltaRasterPublicationV1

Text = Annotated[str, StringConstraints(min_length=1, max_length=255)]
Identifier = Annotated[
    str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]
SourceVersion = Literal[
    "external-relative-volume-calculation-report.v2",
    "external-masked-volume-calculation-identity.v3",
]
Status = Literal["PENDING", "PUBLISHED", "REVOKED", "CANCELED", "FAILED"]
Affine = tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat]
Bounds = tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat]


class CreateDeltaPublicationV1(_CamelModel):
    """Sources only: Core resolves all grid/frame facts, never client declarations."""

    publication_id: Identifier
    source_calculation_identity_digest: Digest
    source_numeric_result_identity_digest: Digest
    source_coverage_witness_digest: Digest
    lifetime_seconds: StrictInt = Field(ge=1)


class DeltaPublicationPendingJobsV1(_CamelModel):
    """Bounded worker-only discovery, never content or a minted lease."""

    publication_ids: tuple[Identifier, ...] = Field(max_length=50)

    @model_validator(mode="after")
    def _unique_jobs(self) -> Self:
        if len(set(self.publication_ids)) != len(self.publication_ids):
            raise ValueError("pending publication ids must be unique")
        return self


class DeltaOutputObservationWireV1(_CamelModel):
    """Authenticated contained-worker result, not the byte-upload caller's metadata."""

    organization_id: Text
    site_id: Text
    work_area_id: Text
    source_contract_version: SourceVersion
    source_calculation_identity_digest: Digest
    source_numeric_result_identity_digest: Digest
    source_coverage_witness_digest: Digest
    publication_id: Identifier
    worker_principal_id: Text
    worker_instance_id: Text
    lease_generation: StrictInt = Field(ge=1)
    output_sha256: Digest
    output_size_bytes: StrictInt = Field(ge=1)
    grid_rows: StrictInt = Field(ge=1)
    grid_columns: StrictInt = Field(ge=1)
    transform: Affine
    transform_digest: Digest
    grid_crs_identifier: Text
    grid_crs_digest: Digest
    bounds: Bounds
    dtype: Literal["FLOAT64"]
    delta_sign: Literal["CURRENT_MINUS_BASELINE"]
    nodata_value: Literal["NAN"]
    observation_digest: Digest

    @model_validator(mode="after")
    def _binds_observed_grid_and_digest(self) -> Self:
        if not all(math.isfinite(value) for value in (*self.transform, *self.bounds)):
            raise ValueError("observed output grid must be finite")
        a, b, c, d, e, f = self.transform
        if b != 0 or d != 0 or a <= 0 or e >= 0:
            raise ValueError("observed delta grid must be native north-up")
        if not all(
            math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
            for actual, expected in zip(
                self.bounds,
                (
                    c,
                    f + e * self.grid_rows,
                    c + a * self.grid_columns,
                    f,
                ),
                strict=True,
            )
        ):
            raise ValueError("observed bounds differ from affine grid")
        transform_digest = (
            "sha256:"
            + hashlib.sha256(canonical_json_bytes({"transform": list(self.transform)})).hexdigest()
        )
        if self.transform_digest != transform_digest:
            raise ValueError("observed transform digest differs")
        raw = self.model_dump(mode="json", by_alias=True, exclude={"observation_digest"})
        if (
            self.observation_digest
            != "sha256:" + hashlib.sha256(canonical_json_bytes(raw)).hexdigest()
        ):
            raise ValueError("observed output digest differs")
        return self


class DeltaPublicationIntentViewV1(_CamelModel):
    publication_id: Text
    organization_id: Text
    site_id: Text
    work_area_id: Text
    source_contract_version: SourceVersion
    output_id: Text
    upload_fence_id: Text
    source_calculation_identity_digest: Digest
    source_numeric_result_identity_digest: Digest
    source_coverage_witness_digest: Digest
    grid_rows: StrictInt = Field(ge=1)
    grid_columns: StrictInt = Field(ge=1)
    issued_at: datetime
    expires_at: datetime
    policy_digest: Digest
    status: Status
    lease_generation: StrictInt = Field(ge=0)
    lease_holder_principal_id: Text | None
    lease_holder_instance_id: Text | None
    lease_issued_at: datetime | None
    lease_expires_at: datetime | None

    @model_validator(mode="after")
    def _binds_time_and_lease_fields(self) -> Self:
        timestamps = (self.issued_at, self.expires_at, self.lease_issued_at, self.lease_expires_at)
        if (
            any(
                value is not None
                and (value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value))
                for value in timestamps
            )
            or self.expires_at <= self.issued_at
        ):
            raise ValueError("publication times must be a positive UTC interval")
        holder = (
            self.lease_holder_principal_id,
            self.lease_holder_instance_id,
            self.lease_issued_at,
            self.lease_expires_at,
        )
        if self.lease_generation == 0:
            if any(value is not None for value in holder):
                raise ValueError("an unleased intent cannot carry worker holder fields")
        elif any(value is None for value in holder):
            raise ValueError("a leased intent must carry the exact holder and interval")
        elif (
            self.lease_issued_at is not None
            and self.lease_expires_at is not None
            and not (
                self.issued_at <= self.lease_issued_at < self.lease_expires_at <= self.expires_at
            )
        ):
            raise ValueError("upload lease must fit the publication interval")
        return self


class DeltaPublicationViewV1(_CamelModel):
    publication_id: Text
    organization_id: Text
    site_id: Text
    work_area_id: Text
    output_id: Text
    issued_at: datetime
    expires_at: datetime
    policy_digest: Digest
    status: Status
    reason: Text | None
    descriptor: DeltaRasterPublicationV1

    @model_validator(mode="after")
    def _binds_outer_scope_to_sealed_descriptor(self) -> Self:
        descriptor = self.descriptor
        if (
            descriptor.publication_digest is None
            or descriptor.publication_digest != descriptor.canonical_digest()
        ):
            raise ValueError("publication response must carry a sealed descriptor")
        if (
            self.publication_id,
            self.organization_id,
            self.site_id,
            self.work_area_id,
            self.output_id,
            self.policy_digest,
            self.issued_at,
            self.expires_at,
        ) != (
            descriptor.publication_id,
            descriptor.organization_id,
            descriptor.site_id,
            descriptor.work_area_id,
            descriptor.output_id,
            descriptor.publication_policy_digest,
            descriptor.issued_at,
            descriptor.expires_at,
        ):
            raise ValueError("publication response differs from its descriptor scope or lifetime")
        return self


class DeltaPublicationBytesV1(_CamelModel):
    publication_id: Text
    offset: StrictInt = Field(ge=0)
    content_base64: Annotated[str, StringConstraints(max_length=1_398_104)]

    @field_validator("content_base64")
    @classmethod
    def _canonical_bounded_bytes(cls, value: str) -> str:
        decoded = base64.b64decode(value, validate=True)
        if len(decoded) > 1024 * 1024 or base64.b64encode(decoded).decode("ascii") != value:
            raise ValueError("delta byte slice must be canonical base64 within one MiB")
        return value
