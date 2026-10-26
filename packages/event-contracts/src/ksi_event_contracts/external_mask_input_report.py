"""Narrow binary-mask observation report (P2 mask ingress, additive).

The old ``ExternalArtifactInspectionReportV1`` grammar describes DSM/ortho
raster products and has no UINT8 binary-mask inspection path.  This module
defines the only mask-inspection evidence Core accepts for a mask child:
a contained-runtime observation of one sealed binary-mask TIFF.  It is never
a DSM report, never an ortho report, and never a caller ``userDeclared``
claim.

A ``MaskObservationReportV1`` binds exactly one mask artifact's observed
bytes plus the observed grid/CRS/dtype facts the contained inspector proved
with the bounded binary-mask parser
(:func:`parse_sealed_binary_mask_tiff_structure`) and strict single-band
uint8 NO_NODATA binary checks.  Any NoData representation (including 0/1
nodata), any non-binary value, any multi-band or non-uint8 sample model, or
any grid that is not the exact expected baseline grid fails closed in the
primitive before this record is sealed.

Validity versus authority: a sealed report is evidence, never permission.
Core checks the inspection profile's separate activation, the reconstruction
subjects' currentness, the baseline anchor grid, the protected byte proof,
and caller scope before constructing the observed manifest.  Helper
byte-identity checks are never read as an OS sandbox claim.
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime
from typing import Annotated, Any, Literal, Self

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
from ksi_event_contracts.external_artifact_validation import Digest, SealedExternalSubjectV1

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_Affine = tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat]
_Bounds = tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat]


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _require_opaque_artifact_id(value: str) -> str:
    lowered = value.lower()
    if (
        "://" in value
        or value.startswith(("/", "\\"))
        or ".." in value
        or "\\" in value
        or "\n" in value
        or "\r" in value
        or lowered.startswith(("http:", "https:", "s3:", "file:", "cap:"))
    ):
        raise ValueError(
            "artifactId must be an opaque identifier, never a URL, path, or capability"
        )
    return value


class _FrozenMaskObservationModel(_CamelModel):
    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    def _payload(self, digest_field: str) -> dict[str, Any]:
        raw = self.model_dump(by_alias=True, mode="json")
        alias = self.__class__.model_fields[digest_field].alias or digest_field
        raw.pop(alias, None)
        return raw

    def _seal(self, digest_field: str) -> Self:
        return self.model_copy(update={digest_field: _digest(self._payload(digest_field))})


class MaskObservationMeasurementsV1(_FrozenMaskObservationModel):
    """Contained-runtime observed facts for one binary-mask TIFF, evidence only."""

    observed_crs_identifier: Text
    observed_crs_digest: Digest
    transform: _Affine
    transform_digest: Digest
    width: StrictInt = Field(gt=0)
    height: StrictInt = Field(gt=0)
    band_count: Literal[1]
    dtype: Literal["UINT8"]
    nodata_representation: Literal["NONE"]
    bounds: _Bounds

    @field_validator("band_count", mode="before")
    @classmethod
    def _band_count_rejects_bool(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("boolean is not an integer literal")
        return value

    @model_validator(mode="after")
    def _binds_exact_binary_grid(self) -> Self:
        if not all(math.isfinite(item) for item in self.transform):
            raise ValueError("transform must contain only finite values")
        if self.transform_digest != _digest({"transform": list(self.transform)}):
            raise ValueError("transform digest differs from its exact affine")
        left, bottom, right, top = self.bounds
        if not all(math.isfinite(item) for item in self.bounds) or left >= right or bottom >= top:
            raise ValueError("bounds must be finite and ordered")
        scale_x, rot_x, _off_x, rot_y, scale_y, _off_y = self.transform
        if rot_x != 0.0 or rot_y != 0.0:
            raise ValueError("mask grid must be native north-up without rotation")
        if not scale_x > 0.0 or not scale_y < 0.0:
            raise ValueError("mask grid must have positive eastward and negative northward scales")
        expected = (
            self.transform[2],
            self.transform[5] + scale_y * self.height,
            self.transform[2] + scale_x * self.width,
            self.transform[5],
        )
        if not all(
            math.isclose(actual, want, rel_tol=1e-12, abs_tol=1e-12)
            for actual, want in zip(self.bounds, expected, strict=True)
        ):
            raise ValueError("bounds must match the observed rows/columns affine extent")
        return self


class MaskObservationReportV1(_FrozenMaskObservationModel):
    """Sealed contained-runtime observation of one mask child artifact."""

    contract_version: Literal["external-mask-observation-report.v1"] = (
        "external-mask-observation-report.v1"
    )
    report_id: Text
    mask_child_id: Text
    organization_id: Text
    site_id: Text
    work_area_id: Text
    subject: SealedExternalSubjectV1
    subject_digest: Digest
    mask_artifact_id: Text
    observed_sha256: Digest
    observed_size_bytes: StrictInt = Field(gt=0)
    inspection_profile_digest: Digest
    contained_runtime_digest: Digest
    inspector_build_digest: Digest
    measurements: MaskObservationMeasurementsV1
    reported_at: datetime
    report_digest: Digest | None = None

    @field_validator("reported_at")
    @classmethod
    def _reported_at_is_utc(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError("reportedAt must be UTC")
        return value

    @model_validator(mode="after")
    def _binds_exact_observed_mask(self) -> Self:
        _require_opaque_artifact_id(self.mask_artifact_id)
        if self.subject_digest != self.subject.canonical_digest():
            raise ValueError("subject digest does not bind the sealed subject")
        if (
            self.subject.organization_id != self.organization_id
            or self.subject.site_id != self.site_id
        ):
            raise ValueError("observation subject must bind the declared organization and site")
        if self.report_digest is not None and self.report_digest != self.canonical_digest():
            raise ValueError("report digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("report_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        validated = type(self).model_validate(self.__dict__)
        return validated._seal("report_digest")


def _wire(model: _FrozenMaskObservationModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=False)


def mask_observation_report_wire_dict(report: MaskObservationReportV1) -> dict[str, Any]:
    return _wire(report.sealed())


__all__ = [
    "MaskObservationMeasurementsV1",
    "MaskObservationReportV1",
    "mask_observation_report_wire_dict",
]
