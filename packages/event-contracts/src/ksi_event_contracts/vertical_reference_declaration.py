"""A user's declaration of the vertical reference a registered DSM's heights are expressed in.

Why this exists.  A parser can only *observe* a vertical reference when the GeoTIFF carries a
compound CRS with an EPSG vertical component.  Most DSM exports do not, so their heights could
never be read even though the file is valid.  A person who exported the file usually knows the
basis ("ellipsoidal from RTK", "orthometric, KNGeoid18").  This record lets them say so.

What it is *not*.
- It is a claim, never an observation.  It lives in its own ledger and its own type, away from
  ``observed_vertical_reference``, so no consumer can read the two as one fact.  Quantitative
  comparison, relative volume and analysis readiness keep reading the observed value only.
- It does not change the registered submission, its digest or any recorded decision.  Declaring
  later is an append-only record keyed by the DSM's asset reference; a correction or a withdrawal
  is a new record, never an edit.
- Heights are metres.  There is no unit choice, because a wrong unit silently scales every value.
- It states nothing about accuracy (INV-024) and is never inferred from a file header (INV-040).
"""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, StringConstraints, model_validator

from ksi_event_contracts._spatial_data import (
    AssetRef,
    Digest,
    SpatialDataDigestModel,
    SpatialDataModel,
    Text,
    UtcTimestamp,
)
from ksi_event_contracts.vertical_reference import VerticalDatum

DeclarationId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^vrd-[0-9a-f]{32}$", min_length=36, max_length=36)
]
DeclarationStatus = Literal["ACTIVE", "WITHDRAWN"]
# Sequence is per asset; a ceiling keeps the ledger bounded and every value representable.
MAX_DECLARATIONS_PER_ASSET = 64


class DeclareVerticalReferenceV1(SpatialDataModel):
    """What the caller declares.  Scope, asset and declarant come from the authenticated request."""

    datum: VerticalDatum
    unit: Literal["metre"] = "metre"
    basis: Text
    # The sequence the caller saw as current (0 = none yet) so two people cannot silently
    # overwrite each other's declaration.
    expected_sequence: int = Field(strict=True, ge=0, le=MAX_DECLARATIONS_PER_ASSET)


class WithdrawVerticalReferenceV1(SpatialDataModel):
    """Withdraw the current declaration.  Heights can no longer be read from it."""

    expected_sequence: int = Field(strict=True, ge=1, le=MAX_DECLARATIONS_PER_ASSET)


class VerticalReferenceDeclarationV1(SpatialDataDigestModel):
    """One append-only ledger record.  The current declaration is the highest sequence."""

    _digest_field = "declaration_digest"
    declaration_id: DeclarationId
    site_id: Text
    work_area_id: Text
    asset_ref: AssetRef
    sequence: int = Field(strict=True, ge=1, le=MAX_DECLARATIONS_PER_ASSET)
    status: DeclarationStatus
    datum: VerticalDatum | None
    unit: Literal["metre"] = "metre"
    basis: Text | None
    declared_by: Text
    declared_at: UtcTimestamp
    declaration_digest: Digest | None = None

    @model_validator(mode="after")
    def _status_fixes_content(self) -> Self:
        if self.status == "ACTIVE" and (self.datum is None or self.basis is None):
            raise ValueError("an active declaration names its datum and its basis")
        if self.status == "WITHDRAWN" and (self.datum is not None or self.basis is not None):
            raise ValueError("a withdrawal carries no datum or basis")
        return self


VerticalReferenceDeclarationVerdictV1 = Literal["DECLARED", "WITHDRAWN", "REPLAYED"]


class VerticalReferenceDeclarationWriteViewV1(SpatialDataModel):
    """Result of a successful write.  ``REPLAYED`` = the same request already happened."""

    verdict: VerticalReferenceDeclarationVerdictV1
    declaration: VerticalReferenceDeclarationV1


class VerticalReferenceDeclarationStateViewV1(SpatialDataModel):
    """What is declared for one asset now, and why a read may or may not rely on it.

    ``observed`` is true when the file itself carries a vertical reference.  Then a declaration
    is not needed and is refused, so the file's own value can never be shadowed.
    """

    asset_ref: AssetRef
    observed: bool
    current: VerticalReferenceDeclarationV1 | None
    history: Annotated[
        tuple[VerticalReferenceDeclarationV1, ...], Field(max_length=MAX_DECLARATIONS_PER_ASSET)
    ]


class VerticalReferenceDeclarationRefusalV1(SpatialDataModel):
    """Typed refusal body.  No path, stack or other tenant's identifier."""

    verdict: Literal[
        "UNKNOWN_ASSET",
        "NOT_A_DSM",
        "NOT_MEASURED",
        "OBSERVED_REFERENCE_PRESENT",
        "SEQUENCE_CONFLICT",
        "NOTHING_TO_WITHDRAW",
        "TOO_MANY_DECLARATIONS",
        "IDEMPOTENCY_CONFLICT",
        "INVALID",
        "STORE_UNAVAILABLE",
    ]
    detail: Annotated[str, Field(max_length=512)] | None = None
