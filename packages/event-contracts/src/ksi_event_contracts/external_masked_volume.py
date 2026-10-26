"""Additive masked-volume contracts: independent binary exclusion masks and delta output.

This module is strictly additive. It does not modify, reinterpret, or extend any
frozen V1/V2 contract, journal, or numeric result. V2 calculation identities and
results keep their exact meanings; polygon holes remain the only delivered V2
exclusion mechanism.

Validity versus authority, read carefully:

- These models establish contract *validity* only: closed shapes, finite
  numbers, UTC timestamps, sealed digest bindings, and exact cross-model
  identity matches. A sealed record is *evidence*, never permission.
- No model here grants execution admission, publication currency, revocation
  state, read rights, or scope/egress approval. Core checks currentness,
  revocation, scope, and AI-egress separately before any byte access.
- A sealed ``CalculationIdentityV2`` embedded in a masked identity is retained
  as *source evidence* of the unmasked grid the mask was bound against. Its
  embedded V2 policy is source evidence too, never the masked calculation's
  admission authorization.
- A sealed ``DeltaRasterPublicationV1`` is an immutable descriptor of derived
  bytes. It is evidence only; it cannot assert that the publication is current,
  unrevoked, or readable by any caller.
- An observed inspection-report digest binds the worker-observed inspection
  outcome. A caller-declared inspection claim is never accepted as authority;
  only Core adjudicates inspection truth.
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
from ksi_event_contracts.external_artifact_validation import (
    Digest,
    SealedExternalSubjectV1,
)
from ksi_event_contracts.external_relative_volume_analysis import CalculationIdentityV2

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
_OpaqueOutputId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        # Character set only; the dot-dot escape is rejected separately by
        # _require_opaque_output_id because pydantic-core regex has no lookahead.
        pattern=r"^[A-Za-z0-9._-]+$",
    ),
]
_Affine = tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat, StrictFloat]
_Bounds = tuple[StrictFloat, StrictFloat, StrictFloat, StrictFloat]


def _digest(payload: dict[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _require_opaque_output_id(value: str) -> str:
    """An output id names protected bytes; it must not be a URL, path, or capability."""
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
        raise ValueError("outputId must be an opaque identifier, never a URL, path, or capability")
    return value


class _FrozenMaskedVolumeModel(_CamelModel):
    """Closed masked-volume snapshots are immutable and revalidated before use."""

    model_config = ConfigDict(frozen=True, revalidate_instances="always")

    def _payload(self, digest_field: str) -> dict[str, Any]:
        raw = self.model_dump(by_alias=True, mode="json")
        alias = self.__class__.model_fields[digest_field].alias or digest_field
        raw.pop(alias, None)
        return raw

    def _seal(self, digest_field: str) -> Self:
        return self.model_copy(update={digest_field: _digest(self._payload(digest_field))})

    @staticmethod
    def _require_utc(value: datetime, name: str) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise ValueError(f"{name} must be UTC")
        return value

    @staticmethod
    def _require_finite_bound_transform(
        transform: _Affine,
        transform_digest: str,
    ) -> None:
        if not all(math.isfinite(item) for item in transform):
            raise ValueError("transform must contain only finite values")
        if transform_digest != _digest({"transform": list(transform)}):
            raise ValueError("transform digest differs from its exact affine")

    @staticmethod
    def _require_native_north_up_grid(
        transform: _Affine,
        rows: int,
        columns: int,
        bounds: _Bounds,
    ) -> None:
        """Exact native north-up grid with bounds derived from the affine and shape.

        Rotation/shear is forbidden (``b == d == 0``), eastward pixel width must
        be positive and northward pixel height negative. Bounds must equal the
        affine-derived extent ``(c, f+e*rows, c+a*columns, f)``; a merely ordered
        box cannot bless a mismatched grid.
        """
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

    @staticmethod
    def _require_finite_ordered_bounds(bounds: _Bounds) -> None:
        left, bottom, right, top = bounds
        if not all(math.isfinite(item) for item in bounds) or left >= right or bottom >= top:
            raise ValueError("bounds must be finite and ordered")

    @staticmethod
    def _reject_bool(value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("boolean is not an integer literal")
        return value


class ExclusionMaskBindingV1(_FrozenMaskedVolumeModel):
    """Sealed binding of one independently supplied binary exclusion mask file.

    The mask bytes themselves live in an external file bound here by exact
    observed SHA-256 and byte size; this record carries no pixel data. The
    binary convention is fixed: unsigned 8-bit, single band, ``0`` retains a
    cell and ``1`` excludes it. Any NoData representation in the mask file is
    a blocker, never a fill value: the worker must reject such input.
    """

    contract_version: Literal["external-masked-volume-exclusion-mask-binding.v1"] = (
        "external-masked-volume-exclusion-mask-binding.v1"
    )
    organization_id: Text
    site_id: Text
    work_area_id: Text
    subject: SealedExternalSubjectV1
    mask_artifact_id: Text
    observed_sha256: Digest
    observed_size_bytes: StrictInt = Field(gt=0)
    observed_inspection_report_digest: Digest
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
    mask_binding_digest: Digest | None = None

    @field_validator("band_count", "retain_value", "exclude_value", mode="before")
    @classmethod
    def _integer_literals_reject_bool(cls, value: Any) -> Any:
        return _FrozenMaskedVolumeModel._reject_bool(value)

    @model_validator(mode="after")
    def _binds_exact_observed_mask_file(self) -> Self:
        self._require_finite_bound_transform(self.transform, self.transform_digest)
        self._require_finite_ordered_bounds(self.bounds)
        self._require_native_north_up_grid(self.transform, self.rows, self.columns, self.bounds)
        if (
            self.subject.organization_id != self.organization_id
            or self.subject.site_id != self.site_id
        ):
            raise ValueError("mask subject must bind the declared organization and site")
        if self.mask_binding_digest is not None and (
            self.mask_binding_digest != self.canonical_digest()
        ):
            raise ValueError("mask binding digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("mask_binding_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        validated = type(self).model_validate(self.__dict__)
        return validated._seal("mask_binding_digest")


class MaskedRelativeVolumeProfileV3(_FrozenMaskedVolumeModel):
    """The masked calculation profile's mathematical identity, without any result.

    A sealed profile describes *how* a masked calculation is computed. It is
    not, and cannot carry, a signed admission or execution authorization: Core
    issues admission separately, and no default authorization is inferred from
    a sealed profile.
    """

    contract_version: Literal["external-masked-relative-volume-profile.v3"] = (
        "external-masked-relative-volume-profile.v3"
    )
    policy_id: Text
    version: StrictInt = Field(ge=1)
    profile_id: Literal["KSI-GIS-MASKED-RELATIVE-VOLUME-V3"]
    profile_digest: Digest
    algorithm_digest: Digest
    config_digest: Digest
    baseline_grid_rule: Literal["EXACT_BASELINE_GRID"]
    current_elevation_resampling: Literal["BILINEAR"]
    current_mask_resampling: Literal["NEAREST"]
    work_area_rasterization: Literal["CELL_CENTER"]
    exclusion_precedence: Literal["WORKAREA_HOLES_THEN_MASK"]
    mask_convention: Literal["UINT8_SINGLE_BAND_BINARY_0_KEEP_1_EXCLUDE_V1"]
    mask_nodata_rule: Literal["NO_NODATA"]
    minimum_common_valid_fraction: StrictFloat
    threshold_m: StrictFloat
    cell_area_rule: Literal["ABSOLUTE_AFFINE_DETERMINANT"]
    delta_rule: Literal["CURRENT_MINUS_BASELINE"]
    uncertainty_method: Literal["NONE_UNCERTAINTY_M3_NULL_V1"]
    masked_profile_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_fixed_masked_profile(self) -> Self:
        if self.minimum_common_valid_fraction != 1.0:
            raise ValueError("masked profile requires 100% common valid coverage")
        if self.threshold_m != 0.0:
            raise ValueError("masked profile requires a zero threshold")
        if not math.isfinite(self.minimum_common_valid_fraction) or not math.isfinite(
            self.threshold_m
        ):
            raise ValueError("masked profile numeric values must be finite")
        if self.masked_profile_digest is not None and (
            self.masked_profile_digest != self.canonical_digest()
        ):
            raise ValueError("masked profile digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("masked_profile_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        validated = type(self).model_validate(self.__dict__)
        return validated._seal("masked_profile_digest")


class MaskedCalculationIdentityV3(_FrozenMaskedVolumeModel):
    """The immutable, non-numeric identity of one future masked calculation.

    The embedded V2 identity is *source evidence* of the unmasked grid the
    mask was bound against; its embedded V2 policy is source evidence too, not
    the masked calculation's admission authority. The sealed masked digest is
    always distinct from the V2 identity digest: no masked calculation may use
    the original V2 identity as its result key.
    """

    contract_version: Literal["external-masked-volume-calculation-identity.v3"] = (
        "external-masked-volume-calculation-identity.v3"
    )
    masked_calculation_id: Text
    organization_id: Text
    site_id: Text
    work_area_id: Text
    source_calculation_identity: CalculationIdentityV2
    source_calculation_identity_digest: Digest
    mask_binding: ExclusionMaskBindingV1
    mask_binding_digest: Digest
    profile: MaskedRelativeVolumeProfileV3
    masked_profile_digest: Digest
    grid_rows: StrictInt = Field(gt=0)
    grid_columns: StrictInt = Field(gt=0)
    horizontal_crs_digest: Digest
    masked_calculation_identity_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_sealed_source_mask_and_profile(self) -> Self:
        source = self.source_calculation_identity
        if source.calculation_identity_digest is None or (
            source.calculation_identity_digest != source.canonical_digest()
        ):
            raise ValueError("masked source calculation identity must be sealed")
        if self.source_calculation_identity_digest != source.calculation_identity_digest:
            raise ValueError("source calculation identity digest does not bind the source identity")
        mask = self.mask_binding
        if mask.mask_binding_digest is None or (
            mask.mask_binding_digest != mask.canonical_digest()
        ):
            raise ValueError("exclusion mask binding must be sealed")
        if self.mask_binding_digest != mask.mask_binding_digest:
            raise ValueError("mask binding digest does not bind the supplied mask binding")
        profile = self.profile
        if profile.masked_profile_digest is None or (
            profile.masked_profile_digest != profile.canonical_digest()
        ):
            raise ValueError("masked profile must be sealed")
        if self.masked_profile_digest != profile.masked_profile_digest:
            raise ValueError("masked profile digest does not bind the supplied profile")
        if (
            self.organization_id,
            self.site_id,
            self.work_area_id,
        ) != (
            source.organization_id,
            source.site_id,
            source.work_area_id,
        ) or (
            self.organization_id,
            self.site_id,
            self.work_area_id,
        ) != (
            mask.organization_id,
            mask.site_id,
            mask.work_area_id,
        ):
            raise ValueError(
                "masked identity, source identity, and mask binding must share "
                "organization, site, and work area in order"
            )
        if mask.transform_digest != source.baseline_transform_digest:
            raise ValueError("mask grid must bind the exact baseline transform digest")
        if mask.observed_crs_identifier != source.baseline_observed_crs_identifier:
            raise ValueError(
                "mask grid CRS identifier must match the source baseline observed identifier"
            )
        if (
            mask.observed_crs_digest != source.horizontal_crs_digest
            or self.horizontal_crs_digest != source.horizontal_crs_digest
            or self.horizontal_crs_digest != mask.observed_crs_digest
        ):
            raise ValueError("mask grid CRS must bind the source horizontal CRS digest")
        if self.grid_rows != mask.rows or self.grid_columns != mask.columns:
            raise ValueError("masked grid dimensions must equal the sealed mask dimensions")
        if self.masked_calculation_identity_digest is not None and (
            self.masked_calculation_identity_digest != self.canonical_digest()
        ):
            raise ValueError("masked identity digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("masked_calculation_identity_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        validated = type(self).model_validate(self.__dict__)
        return validated._seal("masked_calculation_identity_digest")


class DeltaRasterPublicationV1(_FrozenMaskedVolumeModel):
    """Immutable descriptor of derived delta-raster bytes, evidence only.

    The raster is derived from the actual validated delta array
    (``CURRENT_MINUS_BASELINE``), never reconstructed from aggregate metrics.
    The descriptor carries an opaque protected output id plus the observed
    output SHA-256 and size; it carries no URL, path, or capability, and it
    asserts no currency, revocation state, or read right. Float width is fixed
    to ``FLOAT64``: a 32-bit float cannot hold metre-scale elevation deltas
    over large grids without metric drift. Lifetime is an explicit
    issued/expires UTC interval; expiry, revocation, scope, and AI-egress are
    checked by Core before any byte access, not by this descriptor.
    """

    contract_version: Literal["external-masked-volume-delta-publication.v1"] = (
        "external-masked-volume-delta-publication.v1"
    )
    publication_id: Text
    organization_id: Text
    site_id: Text
    work_area_id: Text
    source_contract_version: Literal[
        "external-relative-volume-calculation-report.v2",
        "external-masked-volume-calculation-identity.v3",
    ]
    source_calculation_identity_digest: Digest
    source_numeric_result_identity_digest: Digest
    source_coverage_witness_digest: Digest
    delta_sign: Literal["CURRENT_MINUS_BASELINE"]
    grid_rows: StrictInt = Field(gt=0)
    grid_columns: StrictInt = Field(gt=0)
    transform: _Affine
    transform_digest: Digest
    grid_crs_identifier: Text
    grid_crs_digest: Digest
    bounds: _Bounds
    vertical_unit: Literal["metre"]
    dtype: Literal["FLOAT64"]
    output_id: _OpaqueOutputId
    output_sha256: Digest
    output_size_bytes: StrictInt = Field(gt=0)
    issued_at: datetime
    expires_at: datetime
    publication_policy_digest: Digest
    publication_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_exact_derived_output(self) -> Self:
        self._require_finite_bound_transform(self.transform, self.transform_digest)
        self._require_finite_ordered_bounds(self.bounds)
        self._require_native_north_up_grid(
            self.transform, self.grid_rows, self.grid_columns, self.bounds
        )
        _require_opaque_output_id(self.output_id)
        self._require_utc(self.issued_at, "issuedAt")
        self._require_utc(self.expires_at, "expiresAt")
        if self.expires_at <= self.issued_at:
            raise ValueError("expiresAt must be after issuedAt")
        if self.publication_digest is not None and (
            self.publication_digest != self.canonical_digest()
        ):
            raise ValueError("publication digest differs from its exact content")
        return self

    def canonical_payload(self) -> dict[str, Any]:
        return self._payload("publication_digest")

    def canonical_digest(self) -> str:
        return _digest(self.canonical_payload())

    def sealed(self) -> Self:
        validated = type(self).model_validate(self.__dict__)
        return validated._seal("publication_digest")


def _wire(model: _FrozenMaskedVolumeModel) -> dict[str, Any]:
    return model.model_dump(by_alias=True, mode="json", exclude_none=False)


def exclusion_mask_binding_wire_dict(binding: ExclusionMaskBindingV1) -> dict[str, Any]:
    """Return the sealed wire dict of an exclusion mask binding."""
    return _wire(binding.sealed())


def masked_relative_volume_profile_wire_dict(
    profile: MaskedRelativeVolumeProfileV3,
) -> dict[str, Any]:
    """Return the sealed wire dict of a masked relative-volume profile."""
    return _wire(profile.sealed())


def masked_calculation_identity_wire_dict(
    identity: MaskedCalculationIdentityV3,
) -> dict[str, Any]:
    """Return the sealed wire dict of a masked calculation identity."""
    return _wire(identity.sealed())


def delta_raster_publication_wire_dict(
    publication: DeltaRasterPublicationV1,
) -> dict[str, Any]:
    """Return the sealed wire dict of a delta raster publication descriptor."""
    return _wire(publication.sealed())


__all__ = [
    "DeltaRasterPublicationV1",
    "ExclusionMaskBindingV1",
    "MaskedCalculationIdentityV3",
    "MaskedRelativeVolumeProfileV3",
    "delta_raster_publication_wire_dict",
    "exclusion_mask_binding_wire_dict",
    "masked_calculation_identity_wire_dict",
    "masked_relative_volume_profile_wire_dict",
]
