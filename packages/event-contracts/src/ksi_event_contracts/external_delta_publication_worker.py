"""Closed late-export worker input for one delta-publication lease.

Additive, frozen-lane safe: the V2 Analysis worker protocol and the Core
publication intent/observation/upload shapes are unchanged. This module names
the exact server-issued DSM input a late-export worker may consume for ONE
publication lease. It is the only worker input for the new output job:

- Two ordered server-issued DSM capabilities (baseline then current) bound to
  the exact sealed V2 calculation identity, never to client-supplied URLs.
- The exact sealed V2 identity plus its sealed numeric result, so the worker
  can re-measure without inventing a new analysis attempt, admission, or
  authorization. The old numeric report is evidence, never mutated here.
- The exact publication/lease binding (principal, instance, generation,
  expiries) plus the trusted source digests and grid the Core intent bound.

No model here grants authority: Core rechecks lease liveness, source
currency, policy/runtime currency, expiry, cancel/failure and scope before
issuing this input and again before accepting the observation and bytes.
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import (
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

from ksi_event_contracts._base import _CamelModel
from ksi_event_contracts.external_artifact_validation import Digest
from ksi_event_contracts.external_masked_volume import (
    ExclusionMaskBindingV1,
    MaskedCalculationIdentityV3,
)
from ksi_event_contracts.external_masked_volume_result import (
    MaskedCoverageWitnessV3,
    MaskedVolumeCalculationReportV3,
)
from ksi_event_contracts.external_relative_volume_analysis import CalculationIdentityV2
from ksi_event_contracts.external_relative_volume_calculation import (
    RelativeVolumeCoverageWitnessV2,
    RelativeVolumeNumericResultV2,
)

_Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_Opaque = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
_HeaderName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9!#$%&'*+.^_`|~-]+$",
    ),
]
_HeaderValue = Annotated[
    str, StringConstraints(strip_whitespace=False, min_length=1, max_length=8192)
]
_Url = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16384)]
_Affine = tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat]
_Bounds = tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat]


class _WorkerModel(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    return value


def _transform_digest(transform: _Affine) -> str:
    return (
        "sha256:" + hashlib.sha256(canonical_json_bytes({"transform": list(transform)})).hexdigest()
    )


class DeltaPublicationWorkerInputCapabilityV1(_WorkerModel):
    """One short-lived server-issued DSM GET bound to the sealed V2 identity."""

    role: Literal["BASELINE_DSM", "CURRENT_DSM"]
    artifact_id: _Text
    observed_sha256: Digest
    observed_size_bytes: int = Field(gt=0)
    download_url: _Url
    required_headers: dict[_HeaderName, _HeaderValue] = Field(max_length=32)
    expires_at: datetime

    @field_validator("download_url")
    @classmethod
    def _capability_url_is_http(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "\r" in value
            or "\n" in value
        ):
            raise ValueError("downloadUrl must be a credential-free HTTP(S) URL")
        return value

    @field_validator("expires_at")
    @classmethod
    def _expires_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)


class DeltaPublicationWorkerInputV1(_WorkerModel):
    """Exact server-issued late-export input for one publication lease.

    The worker must treat this as a re-measurement fence only: it authorizes
    reproducing the sealed ``numeric_result`` bytes from the two capabilities,
    never fabricating a V2 attempt/admission/authorization or treating the old
    completed attempt as live.
    """

    publication_id: _Opaque
    organization_id: _Text
    site_id: _Text
    work_area_id: _Text
    source_contract_version: Literal["external-relative-volume-calculation-report.v2"] = (
        "external-relative-volume-calculation-report.v2"
    )
    source_calculation_identity_digest: Digest
    source_numeric_result_identity_digest: Digest
    source_coverage_witness_digest: Digest
    worker_principal_id: _Text
    worker_instance_id: _Text
    lease_generation: StrictInt = Field(ge=1)
    lease_expires_at: datetime
    publication_expires_at: datetime
    grid_rows: StrictInt = Field(ge=1)
    grid_columns: StrictInt = Field(ge=1)
    transform: _Affine
    transform_digest: Digest
    grid_crs_identifier: _Text
    grid_crs_digest: Digest
    bounds: _Bounds
    calculation_identity: CalculationIdentityV2
    numeric_result: RelativeVolumeNumericResultV2
    inputs: tuple[DeltaPublicationWorkerInputCapabilityV1, DeltaPublicationWorkerInputCapabilityV1]

    @field_validator("lease_expires_at", "publication_expires_at")
    @classmethod
    def _expiry_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _binds_exact_source_lease_and_inputs(self) -> Self:
        identity = self.calculation_identity
        numeric = self.numeric_result
        if (
            identity.calculation_identity_digest is None
            or identity.calculation_identity_digest != identity.canonical_digest()
            or identity.calculation_identity_digest != self.source_calculation_identity_digest
            or identity.organization_id != self.organization_id
            or identity.site_id != self.site_id
            or identity.work_area_id != self.work_area_id
        ):
            raise ValueError("worker input identity does not bind the bound calculation")
        if (
            numeric.numeric_result_identity_digest is None
            or numeric.numeric_result_identity_digest != numeric.canonical_digest()
            or numeric.numeric_result_identity_digest != self.source_numeric_result_identity_digest
            or numeric.calculation_identity_digest != self.source_calculation_identity_digest
            or numeric.coverage.coverage_witness_digest != self.source_coverage_witness_digest
            or numeric.coverage.canonical_digest() != self.source_coverage_witness_digest
        ):
            raise ValueError("worker input numeric result does not bind the bound sources")
        coverage = numeric.coverage
        if (
            (self.grid_rows, self.grid_columns) != (coverage.rows, coverage.columns)
            or tuple(self.transform) != tuple(coverage_transform(identity, coverage))
            or self.transform_digest != _transform_digest(self.transform)
            or self.transform_digest != coverage_transform_digest(self.transform)
            or self.grid_crs_identifier != identity.baseline_observed_crs_identifier
            or self.grid_crs_digest != identity.horizontal_crs_digest
            or tuple(self.bounds) != tuple(coverage.bounds)
        ):
            raise ValueError("worker input grid does not match the sealed coverage window")
        if not all(math.isfinite(v) for v in (*self.transform, *self.bounds)):
            raise ValueError("worker input grid must be finite")
        a, b, _c, d, e, _f = self.transform
        if b != 0 or d != 0 or a <= 0 or e >= 0:
            raise ValueError("worker input grid must be native north-up")
        baseline, current = self.inputs
        if (baseline.role, current.role) != ("BASELINE_DSM", "CURRENT_DSM"):
            raise ValueError("worker inputs must be ordered baseline then current")
        expected = (
            (
                identity.baseline_dsm_artifact_id,
                identity.baseline_dsm_observed_sha256,
                identity.baseline_dsm_observed_size_bytes,
            ),
            (
                identity.current_dsm_artifact_id,
                identity.current_dsm_observed_sha256,
                identity.current_dsm_observed_size_bytes,
            ),
        )
        supplied = tuple(
            (item.artifact_id, item.observed_sha256, item.observed_size_bytes)
            for item in self.inputs
        )
        if supplied != expected:
            raise ValueError("worker capabilities do not bind the calculation identity")
        if any(item.expires_at > self.lease_expires_at for item in self.inputs) or any(
            item.expires_at > self.publication_expires_at for item in self.inputs
        ):
            raise ValueError("worker capability outlives its lease")
        if not self.lease_expires_at <= self.publication_expires_at:
            raise ValueError("lease cannot outlive its publication")
        return self


class DeltaPublicationWorkerInputResponseV1(_WorkerModel):
    input: DeltaPublicationWorkerInputV1


class DeltaPublicationMaskInputCapabilityV1(_WorkerModel):
    """Worker-only mask retrieval descriptor bound to the sealed mask binding.

    The mask bytes live in Core's protected mask byte filesystem, never in
    presignable object storage. The server mints ``download_url`` from an
    explicitly configured Core origin (never a client URL, path, or object
    key): the fixed lease-scoped ``.../mask-bytes`` route plus the opaque
    ``worker_instance_id``/``lease_generation`` query. The worker fetches it
    with its Core bearer — which is never sent to object-storage origins —
    and hash/size-verifies the bounded body against this binding before any
    decode. Any NoData representation in the mask file is a blocker.
    """

    role: Literal["EXCLUSION_MASK"] = "EXCLUSION_MASK"
    artifact_id: _Text
    observed_sha256: Digest
    observed_size_bytes: int = Field(gt=0)
    retrieval: Literal["MASK_INPUT_ROUTE"] = "MASK_INPUT_ROUTE"
    download_url: _Url
    expires_at: datetime

    @field_validator("download_url")
    @classmethod
    def _capability_url_is_http(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "\r" in value
            or "\n" in value
        ):
            raise ValueError("downloadUrl must be a credential-free HTTP(S) URL")
        return value

    @field_validator("expires_at")
    @classmethod
    def _expires_at_utc(cls, value: datetime) -> datetime:
        return _utc(value)


def _masked_coverage_transform(
    identity: MaskedCalculationIdentityV3, coverage: MaskedCoverageWitnessV3
) -> tuple[float, ...]:
    """Reproduce the worker-visible window affine from the sealed V3 sources.

    Mirrors Core's V3 witness derivation (source baseline affine translated
    by the sealed coverage offsets) without importing Core code.
    """
    source = identity.source_calculation_identity
    a, b, c, d, e, f = source.baseline_transform
    row_offset = int(coverage.row_offset)
    column_offset = int(coverage.column_offset)
    return (
        float(a),
        float(b),
        float(c + a * column_offset + b * row_offset),
        float(d),
        float(e),
        float(f + d * column_offset + e * row_offset),
    )


class DeltaPublicationMaskedWorkerInputV1(_WorkerModel):
    """Exact server-issued late-export input for one V3 publication lease.

    Covers the masked profile only: the exact sealed masked identity plus
    its sealed completed report (never a fabricated V2 numeric result), two
    ordered server-issued DSM capabilities, and the worker-only mask
    retrieval descriptor. The worker must reproduce the sealed numeric bytes
    from the three staged files without minting a new report or touching any
    V2 attempt; the old COMPLETED masked report is evidence only.
    """

    publication_id: _Opaque
    organization_id: _Text
    site_id: _Text
    work_area_id: _Text
    source_contract_version: Literal["external-masked-volume-calculation-identity.v3"] = (
        "external-masked-volume-calculation-identity.v3"
    )
    source_calculation_identity_digest: Digest
    source_numeric_result_identity_digest: Digest
    source_coverage_witness_digest: Digest
    worker_principal_id: _Text
    worker_instance_id: _Text
    lease_generation: StrictInt = Field(ge=1)
    lease_expires_at: datetime
    publication_expires_at: datetime
    grid_rows: StrictInt = Field(ge=1)
    grid_columns: StrictInt = Field(ge=1)
    transform: _Affine
    transform_digest: Digest
    grid_crs_identifier: _Text
    grid_crs_digest: Digest
    bounds: _Bounds
    masked_calculation_identity: MaskedCalculationIdentityV3
    report: MaskedVolumeCalculationReportV3
    inputs: tuple[
        DeltaPublicationWorkerInputCapabilityV1,
        DeltaPublicationWorkerInputCapabilityV1,
        DeltaPublicationMaskInputCapabilityV1,
    ]

    @field_validator("lease_expires_at", "publication_expires_at")
    @classmethod
    def _expiry_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def _binds_exact_masked_source_lease_and_inputs(self) -> Self:
        identity = self.masked_calculation_identity
        result = self.report
        numeric = result.numeric_result
        if (
            identity.masked_calculation_identity_digest is None
            or identity.masked_calculation_identity_digest != identity.canonical_digest()
            or identity.masked_calculation_identity_digest
            != self.source_calculation_identity_digest
            or identity.organization_id != self.organization_id
            or identity.site_id != self.site_id
            or identity.work_area_id != self.work_area_id
        ):
            raise ValueError("worker input identity does not bind the bound masked calculation")
        if (
            result.report_digest is None
            or result.report_digest != result.canonical_digest()
            or result.masked_calculation_identity_digest != identity.canonical_digest()
            or result.numeric_result_identity_digest != self.source_numeric_result_identity_digest
            or numeric.numeric_result_identity_digest != self.source_numeric_result_identity_digest
            or numeric.masked_calculation_identity_digest != identity.canonical_digest()
            or numeric.masked_profile_digest != identity.masked_profile_digest
            or numeric.mask_binding_digest != identity.mask_binding_digest
        ):
            raise ValueError("worker input report does not bind the bound masked sources")
        if (
            numeric.coverage.coverage_witness_digest is None
            or numeric.coverage.coverage_witness_digest != numeric.coverage.canonical_digest()
            or numeric.coverage.coverage_witness_digest != self.source_coverage_witness_digest
        ):
            raise ValueError("worker input coverage does not bind the bound coverage witness")
        coverage = numeric.coverage
        source = identity.source_calculation_identity
        if (
            (self.grid_rows, self.grid_columns) != (coverage.rows, coverage.columns)
            or tuple(self.transform) != tuple(_masked_coverage_transform(identity, coverage))
            or self.transform_digest != _transform_digest(self.transform)
            or self.grid_crs_identifier != source.baseline_observed_crs_identifier
            or self.grid_crs_digest != source.horizontal_crs_digest
            or tuple(self.bounds) != tuple(coverage.bounds)
        ):
            raise ValueError("worker input grid does not match the sealed masked coverage window")
        if not all(math.isfinite(v) for v in (*self.transform, *self.bounds)):
            raise ValueError("worker input grid must be finite")
        a, b, _c, d, e, _f = self.transform
        if b != 0 or d != 0 or a <= 0 or e >= 0:
            raise ValueError("worker input grid must be native north-up")
        baseline, current, mask = self.inputs
        if (baseline.role, current.role, mask.role) != (
            "BASELINE_DSM",
            "CURRENT_DSM",
            "EXCLUSION_MASK",
        ):
            raise ValueError("worker inputs must be ordered baseline, current, then mask")
        expected_dsm = (
            (
                source.baseline_dsm_artifact_id,
                source.baseline_dsm_observed_sha256,
                source.baseline_dsm_observed_size_bytes,
            ),
            (
                source.current_dsm_artifact_id,
                source.current_dsm_observed_sha256,
                source.current_dsm_observed_size_bytes,
            ),
        )
        supplied_dsm = tuple(
            (item.artifact_id, item.observed_sha256, item.observed_size_bytes)
            for item in (baseline, current)
        )
        if supplied_dsm != expected_dsm:
            raise ValueError("worker capabilities do not bind the source calculation identity")
        binding: ExclusionMaskBindingV1 = identity.mask_binding
        if (
            mask.artifact_id,
            mask.observed_sha256,
            mask.observed_size_bytes,
        ) != (
            binding.mask_artifact_id,
            binding.observed_sha256,
            binding.observed_size_bytes,
        ):
            raise ValueError("worker mask retrieval does not bind the sealed mask binding")
        if any(item.expires_at > self.lease_expires_at for item in self.inputs) or any(
            item.expires_at > self.publication_expires_at for item in self.inputs
        ):
            raise ValueError("worker capability outlives its lease")
        if not self.lease_expires_at <= self.publication_expires_at:
            raise ValueError("lease cannot outlive its publication")
        return self


class DeltaPublicationMaskedWorkerInputResponseV1(_WorkerModel):
    input: DeltaPublicationMaskedWorkerInputV1


_OpaqueId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._-]+$"
    ),
]


class DeltaPublicationPendingPageV1(_WorkerModel):
    """Bounded worker-visible discovery page: opaque ids only.

    The worker learns which pending publications it may attempt without any
    out-of-band id. The page carries no fences, hashes, grids, or byte
    metadata: each id must still acquire its own lease and server-issued
    input before any download. Unknown fields, oversized pages, repeated
    ids, and non-opaque ids are rejected, never repaired.
    """

    publication_ids: tuple[_OpaqueId, ...] = Field(max_length=50, min_length=0)

    @model_validator(mode="after")
    def _binds_unique_opaque_ids(self) -> Self:
        for value in self.publication_ids:
            if ".." in value:
                raise ValueError("discovery page ids must be opaque, never paths")
        if len(set(self.publication_ids)) != len(self.publication_ids):
            raise ValueError("discovery page must not repeat publication ids")
        return self


def coverage_transform(
    identity: CalculationIdentityV2, coverage: RelativeVolumeCoverageWitnessV2
) -> tuple[float, ...]:
    """Reproduce the worker-visible window affine from the sealed identity.

    Mirrors Core's V2 witness derivation (baseline affine translated by the
    sealed coverage offsets) without importing Core code.
    """
    a, b, c, d, e, f = identity.baseline_transform
    return (
        float(a),
        float(b),
        float(c + a * coverage.column_offset + b * coverage.row_offset),
        float(d),
        float(e),
        float(f + d * coverage.column_offset + e * coverage.row_offset),
    )


def coverage_transform_digest(transform: _Affine) -> str:
    return _transform_digest(transform)


__all__ = [
    "DeltaPublicationMaskInputCapabilityV1",
    "DeltaPublicationMaskedWorkerInputResponseV1",
    "DeltaPublicationMaskedWorkerInputV1",
    "DeltaPublicationPendingPageV1",
    "DeltaPublicationWorkerInputCapabilityV1",
    "DeltaPublicationWorkerInputResponseV1",
    "DeltaPublicationWorkerInputV1",
]
