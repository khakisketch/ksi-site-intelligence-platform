"""Display-derivative identity vs stable source identity (no measurement authority).

This module owns ONLY the identity records for regenerable display derivatives
of an already-sealed spatial-data SOURCE, plus the explicit pair-registration
record (or explicit NONE) that gates cross-epoch spatial comparison.

Normative split (display/LOD contract proposal 2026-10-21, section 2):

- SOURCE identity is stable and borrowed entirely from existing contracts
  (``assetRef`` / sealed byte digest / observed CRS digest / revision /
  inspection report digest). Display work never mutates it.
- A display derivative is a pure function of (SOURCE identity + display
  parameters + validity-rule versions + permission binding). Its
  ``derivativeId`` is ``sha256`` over the canonical payload, computed exactly
  the way this package already computes digests (``SpatialDataDigestModel``).

What this module does NOT do (deliberate non-goals):

- No registration METHOD: ``PairRegistrationV1`` records an asserted
  registration with its evidence digests, or an explicit NONE. It performs no
  survey-grade inference and weakens no INV-053/INV-020 gate.
- No LOD pyramid table, no per-interaction budget, no cache service: a level
  is a pinned integer plus a versioned table/kernel id, nothing more.
- No new purpose (GAP-05 review pending): permission reuses the existing
  ``SpatialDataPurposeV1`` values only.
- No composite ready/status/verified flag: ``DisplaySpatialViewV1`` carries
  ONLY the representation fact (AVAILABLE | NOT_READY | UNRENDERABLE), using
  the audit-proposal vocabulary. It never restates validation suitability.

Invariants touched: INV-020 (CRS binding is borrowed, never re-guessed),
INV-053 (equal CRS is not registration evidence), INV-060 (permission binds
grant/policy/purpose/principal-hash; no shared-cache authority is created).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, StrictFloat, StrictInt, model_validator

from ksi_event_contracts._spatial_data import (
    MAX_COUNTER,
    AssetRef,
    Bounds,
    Coordinate,
    Digest,
    PositiveInt,
    SpatialDataDigestModel,
    SpatialDataModel,
    Text,
    UtcTimestamp,
)
from ksi_event_contracts.spatial_data import (
    JobId,
    PixelWindow,
    SpatialDataPurposeV1,
    Transform,
)

LodLevel = Annotated[StrictInt, Field(ge=0, le=MAX_COUNTER)]
NonNegativeFloat = Annotated[StrictFloat, Field(ge=0)]
PositiveFloat = Annotated[StrictFloat, Field(gt=0)]


class DisplayDerivativeSourceV1(SpatialDataModel):
    """Stable SOURCE pins, borrowed field-for-field from existing contracts."""

    asset_ref: AssetRef
    observed_sha256: Digest
    observed_crs_digest: Digest
    revision: PositiveInt
    inspection_report_digest: Digest


class DisplayDerivativeWindowV1(SpatialDataModel):
    """Native-grid window, copied from a verified receipt (never re-rounded)."""

    pixel_window: PixelWindow
    actual_bounds: Bounds
    grid_transform: Transform


class DisplayLodV1(SpatialDataModel):
    """Pinned level-of-detail selection (pins only; no pyramid table here)."""

    level: LodLevel
    lod_table_version: Text
    resampling_kernel_id: Text
    target_metres_per_pixel: PositiveFloat


class DisplayStyleV1(SpatialDataModel):
    """Pinned colour/validity presentation policy (pins only; no registry here)."""

    band_mapping_id: Text
    colour_ramp_id: Text
    colour_ramp_version: PositiveInt
    stretch_id: Text
    stretch_version: PositiveInt
    no_data_mask_rule_id: Text
    unit_label_id: Text
    vertical_basis_statement_id: Text


class DisplayValidityV1(SpatialDataModel):
    """Pinned valid-area/mask policy versions governing on-screen semantics."""

    mask_source_digest: Digest
    valid_area_rule_version: Text
    excluded_rule_version: Text


class PairRegistrationStatusV1(StrEnum):
    """Closed registration claim vocabulary.

    There is deliberately NO member meaning "registered without evidence":
    REGISTERED is only constructible with non-empty ``evidenceDigests``
    (fail-closed validator on ``PairRegistrationV1``).
    """

    REGISTERED = "REGISTERED"
    UNREGISTERED = "UNREGISTERED"


class PairRegistrationV1(SpatialDataModel):
    """Asserted cross-epoch pair registration with its own evidence binding.

    This record ASSERTS a registration claim; it performs no registration
    method and no survey-grade inference. Equal CRS alone never satisfies
    this record: construction requires explicit evidence for REGISTERED.
    """

    baseline_asset_ref: AssetRef
    current_asset_ref: AssetRef
    method_id: Text
    method_version: PositiveInt
    transform_parameters: tuple[Coordinate, ...] = Field(min_length=1, max_length=64)
    valid_area_rule_version: Text
    registration_error_metres: NonNegativeFloat | None = None
    status: PairRegistrationStatusV1
    evidence_digests: tuple[Digest, ...] = Field(default=(), max_length=64)

    @model_validator(mode="after")
    def _fail_closed_registration_evidence(self) -> Self:
        if self.baseline_asset_ref == self.current_asset_ref:
            raise ValueError("pair registration requires two distinct asset refs")
        if self.status is PairRegistrationStatusV1.REGISTERED:
            if len(self.evidence_digests) < 1:
                raise ValueError("REGISTERED requires non-empty evidence digests")
        else:
            if len(self.evidence_digests) != 0:
                raise ValueError("UNREGISTERED must carry no evidence digests")
        return self


class PairRegistrationNoneV1(SpatialDataModel):
    """Explicit, non-optional marker for "no registration evidence".

    Absent registration is a TYPED record here, never a missing field or a
    null: a derivative always states either its registration or NONE, so
    "equal CRS" can never be misread as registered.
    """

    registration_kind: Literal["NONE"] = "NONE"
    statement: Text


DisplayRegistration = PairRegistrationV1 | PairRegistrationNoneV1


class DisplayPermissionV1(SpatialDataModel):
    """Rights binding every display byte remains under (no new purpose)."""

    grant_digest: Digest
    policy_digest: Digest
    purpose: SpatialDataPurposeV1
    prepared_for_principal_hash: Digest


class DisplayProvenanceV1(SpatialDataModel):
    """Which bounded preparation produced these bytes (identity only)."""

    prepare_job_id: JobId
    receipt_digest: Digest
    prepared_at: UtcTimestamp
    worker_build_digest: Digest


class DisplayDerivativeV1(SpatialDataDigestModel):
    """Content-addressed identity of one regenerable display derivative.

    Identical pinned inputs reproduce an identical ``derivativeId``; any
    changed pin (source bytes, revision, CRS digest, window, LOD, style,
    validity, registration, permission) yields a different id. Results bind
    SOURCE fields only, never this id.
    """

    _digest_field = "derivative_id"
    source: DisplayDerivativeSourceV1
    window: DisplayDerivativeWindowV1
    lod: DisplayLodV1
    style: DisplayStyleV1
    validity: DisplayValidityV1
    registration: DisplayRegistration
    permission: DisplayPermissionV1
    provenance: DisplayProvenanceV1
    derivative_id: Digest | None = None

    @model_validator(mode="after")
    def _registration_binds_this_source(self) -> Self:
        if isinstance(self.registration, PairRegistrationV1) and self.source.asset_ref not in (
            self.registration.baseline_asset_ref,
            self.registration.current_asset_ref,
        ):
            raise ValueError("pair registration must include this derivative source")
        return self


class DisplaySpatialViewV1(StrEnum):
    """Representation fact ONLY: never a validation-suitability statement."""

    AVAILABLE = "AVAILABLE"
    NOT_READY = "NOT_READY"
    UNRENDERABLE = "UNRENDERABLE"


class DisplayDerivativeBindingV1(SpatialDataModel):
    """Core-projected typed facts about one derivative (no composite flag).

    Deliberately flat and narrow: the derivative id, the SOURCE identity an
    existing analysis result references, the bounded job/receipt that produced
    the bytes, and the representation state. No ready/status/verified roll-up,
    no suitability restatement.
    """

    derivative_id: Digest
    source_digest: Digest
    prepare_job_id: JobId
    receipt_digest: Digest
    spatial_view: DisplaySpatialViewV1
