"""Additive mask child-resource ingress contracts (P2 masked profile).

Independent binary exclusion-mask child resource anchored to a real sealed
reconstruction subject plus one target baseline DSM artifact.  This module is
strictly additive: it does not modify, reinterpret, or extend any frozen V1/V2
contract, journal, or numeric result.

Kind separation, read carefully:

- A mask child is ``MASK_CHILD``.  It is never a DSM epoch, a calculation
  report, a checkpoint, or a display derivative.  A declaration that names a
  report/checkpoint kind, that omits the target baseline DSM artifact, or that
  invents a mask-only epoch without a sealed reconstruction subject is
  rejected by shape.
- A declaration (``MaskChildDeclarationV1``) is client-supplied intent: which
  reconstruction subject owns the upload, which baseline DSM artifact the mask
  will be bound against, and the client-declared SHA-256/size.  It asserts no
  grid, CRS, dtype, or inspection truth.
- An observed manifest (``MaskObservedManifestV1``) is Core-sealed evidence:
  the exact observed bytes plus the grid/CRS/dtype facts Core adjudicated from
  the sealed inspection report.  Only Core creates it, and only from the
  observed worker report, never from a caller ``userDeclaredInspection`` claim.
- The narrow inspection profile (``MaskInspectionProfileV1``) names its own
  contained protocol and runtime binding explicitly.  It does not inherit the
  old float-DSM grammar, and helper byte-identity checks are never read as an
  OS sandbox claim.

Validity versus authority: sealed records are evidence, never permission.  No
model here grants admission, publication currency, revocation state, read
rights, or scope/AI-egress approval.  Core checks currentness, revocation,
scope, and AI-egress separately before any byte access.
"""

from __future__ import annotations

import hashlib
import math
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
from ksi_event_contracts.external_artifact_validation import (
    Digest,
    SealedExternalSubjectV1,
)

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_Affine = tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat]
_Bounds = tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat]


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _require_opaque_artifact_id(value: str) -> str:
    """An artifact id names protected bytes; it must not be a URL, path, or capability."""
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


class _FrozenMaskInputModel(_CamelModel):
    """Closed mask-ingress snapshots are immutable and revalidated before use."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    def _payload(self, digest_field: str) -> dict[str, Any]:
        raw = self.model_dump(by_alias=True, mode="json")
        alias = self.__class__.model_fields[digest_field].alias or digest_field
        raw.pop(alias, None)
        return raw

    def _seal(self, digest_field: str) -> Self:
        return self.model_copy(update={digest_field: _digest(self._payload(digest_field))})

    @staticmethod
    def _require_native_north_up_grid(
        transform: _Affine,
        rows: int,
        columns: int,
        bounds: _Bounds,
    ) -> None:
        scale_x, rot_x, off_x, rot_y, scale_y, off_y = transform
        if rot_x != 0.0 or rot_y != 0.0:
            raise ValueError("grid transform must be native north-up without rotation")
        if not scale_x > 0.0 or not scale_y < 0.0:
            raise ValueError(
                "grid transform must have positive eastward and negative northward scales"
            )
        expected = (
            off_x,
            off_y + scale_y * rows,
            off_x + scale_x * columns,
            off_y,
        )
        if not all(
            math.isclose(actual, want, rel_tol=1e-12, abs_tol=1e-12)
            for actual, want in zip(bounds, expected, strict=True)
        ):
            raise ValueError("bounds must match the rows/columns affine extent")


class MaskInspectionProfileV1(_FrozenMaskInputModel):
    """Narrow uint8 binary-mask inspection profile with explicit contained binding.

    The contained protocol and runtime binding are explicit inputs: a profile
    without them is rejected, and no default is inferred.  The grammar digest
    names the separately approved mask grammar; Core must never accept the old
    float-DSM grammar digest here.
    """

    contract_version: Literal["external-mask-inspection-profile.v1"] = (
        "external-mask-inspection-profile.v1"
    )
    profile_id: Literal["KSI-MASK-INSPECTION-V1"]
    version: StrictInt = Field(ge=1)
    contained_protocol: Literal["CONTAINED_MASK_INSPECTION_V1"]
    runtime_image_version: Text
    runtime_image_oci_digest: Digest
    worker_executable_digest: Digest
    worker_build_digest: Digest
    dependency_lock_digest: Digest
    mask_grammar_digest: Digest
    mask_convention: Literal["UINT8_SINGLE_BAND_BINARY_0_KEEP_1_EXCLUDE_V1"]
    mask_nodata_rule: Literal["NO_NODATA"]
    resource_envelope_digest: Digest
    inspection_profile_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_explicit_contained_profile(self) -> Self:
        if self.inspection_profile_digest is not None and (
            self.inspection_profile_digest != self.canonical_digest()
        ):
            raise ValueError("inspection profile digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("inspection_profile_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        validated = type(self).model_validate(self.__dict__)
        return validated._seal("inspection_profile_digest")


class MaskChildDeclarationV1(_FrozenMaskInputModel):
    """Client-declared mask upload intent; asserts no grid or inspection truth.

    Anchored to a real sealed reconstruction subject plus one target baseline
    DSM artifact.  The ``childKind`` literal keeps this resource distinct from
    DSM epochs, reports, and checkpoints.  Declared SHA/size are intent only;
    Core re-proves observed bytes after the protected upload seals.
    """

    contract_version: Literal["external-mask-child-declaration.v1"] = (
        "external-mask-child-declaration.v1"
    )
    declaration_id: Text
    organization_id: Text
    site_id: Text
    work_area_id: Text
    child_kind: Literal["MASK_CHILD"]
    mask_child_id: Text
    mask_artifact_id: Text
    parent_subject: SealedExternalSubjectV1
    target_baseline_subject: SealedExternalSubjectV1
    target_baseline_dsm_artifact_id: Text
    declared_sha256: Digest
    declared_size_bytes: StrictInt = Field(gt=0)
    declaration_digest: Digest | None = None

    @field_validator("mask_artifact_id", "target_baseline_dsm_artifact_id")
    @classmethod
    def _artifact_ids_are_opaque(cls, value: str) -> str:
        return _require_opaque_artifact_id(value)

    @model_validator(mode="after")
    def _binds_declared_mask_child(self) -> Self:
        # No distinctness requirement between parent and baseline subjects: a
        # binary mask may legitimately belong to the baseline epoch itself.
        # Both subjects must still be real sealed subjects bound to the
        # declared organization/site (currentness is proven separately by the
        # Core reconstruction authority at declare/seal/read time).
        if (
            self.parent_subject.organization_id != self.organization_id
            or self.parent_subject.site_id != self.site_id
            or self.target_baseline_subject.organization_id != self.organization_id
            or self.target_baseline_subject.site_id != self.site_id
        ):
            raise ValueError(
                "mask declaration subjects must bind the declared organization and site"
            )
        if self.declaration_digest is not None and (
            self.declaration_digest != self.canonical_digest()
        ):
            raise ValueError("declaration digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("declaration_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        validated = type(self).model_validate(self.__dict__)
        return validated._seal("declaration_digest")


class MaskObservedManifestV1(_FrozenMaskInputModel):
    """Core-sealed observed-byte manifest for one mask child resource.

    Created by Core only, from the sealed inspection report's observed raster
    facts plus the sealed stored bytes.  A caller ``userDeclaredInspection``
    claim is never accepted as authority.  The binary convention is fixed:
    unsigned 8-bit, single band, ``0`` retains and ``1`` excludes; any NoData
    representation is a blocker recorded as ``NONE`` only when the worker
    proved no NoData tag and no masked pixels exist.
    """

    contract_version: Literal["external-mask-observed-manifest.v1"] = (
        "external-mask-observed-manifest.v1"
    )
    organization_id: Text
    site_id: Text
    work_area_id: Text
    child_kind: Literal["MASK_CHILD"]
    mask_child_id: Text
    mask_artifact_id: Text
    subject: SealedExternalSubjectV1
    parent_subject_digest: Digest
    target_baseline_dsm_artifact_id: Text
    target_baseline_subject_digest: Digest
    observed_sha256: Digest
    observed_size_bytes: StrictInt = Field(gt=0)
    observed_inspection_report_digest: Digest
    inspection_profile_digest: Digest
    rows: StrictInt = Field(gt=0)
    columns: StrictInt = Field(gt=0)
    transform: _Affine
    transform_digest: Digest
    observed_crs_identifier: Text
    observed_crs_digest: Digest
    dtype: Literal["UINT8"]
    band_count: Literal[1]
    retain_value: Literal[0]
    exclude_value: Literal[1]
    nodata_representation: Literal["NONE"]
    bounds: _Bounds
    manifest_digest: Digest | None = None

    @field_validator("mask_artifact_id", "target_baseline_dsm_artifact_id")
    @classmethod
    def _artifact_ids_are_opaque(cls, value: str) -> str:
        return _require_opaque_artifact_id(value)

    @field_validator("band_count", "retain_value", "exclude_value", mode="before")
    @classmethod
    def _integer_literals_reject_bool(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("boolean is not an integer literal")
        return value

    @model_validator(mode="after")
    def _binds_exact_observed_mask_bytes(self) -> Self:
        if not all(math.isfinite(item) for item in self.transform):
            raise ValueError("transform must contain only finite values")
        if self.transform_digest != _digest({"transform": list(self.transform)}):
            raise ValueError("transform digest differs from its exact affine")
        left, bottom, right, top = self.bounds
        if not all(math.isfinite(item) for item in self.bounds) or left >= right or bottom >= top:
            raise ValueError("bounds must be finite and ordered")
        self._require_native_north_up_grid(self.transform, self.rows, self.columns, self.bounds)
        if (
            self.subject.organization_id != self.organization_id
            or self.subject.site_id != self.site_id
        ):
            raise ValueError("mask subject must bind the declared organization and site")
        if self.manifest_digest is not None and (self.manifest_digest != self.canonical_digest()):
            raise ValueError("manifest digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("manifest_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        validated = type(self).model_validate(self.__dict__)
        return validated._seal("manifest_digest")


def _wire(model: _FrozenMaskInputModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=False)


def mask_inspection_profile_wire_dict(profile: MaskInspectionProfileV1) -> dict[str, Any]:
    return _wire(profile.sealed())


def mask_child_declaration_wire_dict(declaration: MaskChildDeclarationV1) -> dict[str, Any]:
    return _wire(declaration.sealed())


def mask_observed_manifest_wire_dict(manifest: MaskObservedManifestV1) -> dict[str, Any]:
    return _wire(manifest.sealed())


__all__ = [
    "MaskChildDeclarationV1",
    "MaskInspectionProfileV1",
    "MaskObservedManifestV1",
    "mask_child_declaration_wire_dict",
    "mask_inspection_profile_wire_dict",
    "mask_observed_manifest_wire_dict",
]
