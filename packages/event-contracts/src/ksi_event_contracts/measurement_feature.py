"""Saved measurement line: immutable revisions bound to a work area, no result authority.

A feature revision only fixes *where* a line is.  It grants no read permission beyond the
parent work area's current one, carries no elevation, and an edit is a new revision — a
result that was computed from revision N stays bound to revision N.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal, Self

from ksi_domain.canonical_json import canonical_json_bytes
from pydantic import AfterValidator, Field, StringConstraints, model_validator

from ksi_event_contracts._spatial_data import (
    Coordinate,
    Digest,
    SpatialDataDigestModel,
    SpatialDataModel,
    Text,
    UtcTimestamp,
)

# Representation ceiling, not an operational budget: the worker policy is stricter and
# a request over the policy is refused, never coarsened.
MAX_LINE_VERTICES = 256

FeatureId = Annotated[
    str, StringConstraints(strict=True, pattern=r"^mf-[0-9a-f]{32}$", min_length=35, max_length=35)
]
CrsIdentifier = Annotated[str, StringConstraints(strict=True, pattern=r"^EPSG:[1-9][0-9]{0,5}$")]
ProfileVertexV1 = Annotated[tuple[Coordinate, Coordinate], Field(min_length=2, max_length=2)]


def _distinct(value: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    if len(set(value)) < 2:
        raise ValueError("a line needs at least two distinct vertices")
    return value


class MeasurementLineV1(SpatialDataModel):
    """Vertices in the stated CRS: x,y in metres for a projected CRS, lon,lat for EPSG:4326."""

    crs: CrsIdentifier
    vertices: Annotated[
        tuple[ProfileVertexV1, ...],
        Field(min_length=2, max_length=MAX_LINE_VERTICES),
        AfterValidator(_distinct),
    ]

    def digest(self) -> str:
        """Digest of the geometry alone, so a result can prove which line it read."""
        payload = self.model_dump(by_alias=True, mode="json")
        return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class MeasurementFeatureRefV1(SpatialDataModel):
    """Exact revision a request or result is bound to."""

    feature_id: FeatureId
    revision: int = Field(strict=True, ge=1, le=2**31 - 1)
    line_digest: Digest


class MeasurementFeatureRevisionV1(SpatialDataDigestModel):
    _digest_field = "revision_digest"
    feature_id: FeatureId
    site_id: Text
    work_area_id: Text
    revision: int = Field(strict=True, ge=1, le=2**31 - 1)
    name: Text
    kind: Literal["LINE"] = "LINE"
    line: MeasurementLineV1
    line_digest: Digest
    created_at: UtcTimestamp
    revision_digest: Digest | None = None

    @model_validator(mode="after")
    def _line_digest_binds_geometry(self) -> Self:
        if self.line_digest != self.line.digest():
            raise ValueError("lineDigest must bind the stored geometry")
        return self

    def ref(self) -> MeasurementFeatureRefV1:
        return MeasurementFeatureRefV1(
            feature_id=self.feature_id, revision=self.revision, line_digest=self.line_digest
        )


class CreateMeasurementFeatureV1(SpatialDataModel):
    """New feature, revision 1.  Scope comes from the authenticated work area, not the body."""

    work_area_id: Text
    name: Text
    line: MeasurementLineV1


class ReviseMeasurementFeatureV1(SpatialDataModel):
    """Edit = new revision; the caller names the revision it edited so a stale edit conflicts."""

    expected_revision: int = Field(strict=True, ge=1, le=2**31 - 1)
    name: Text
    line: MeasurementLineV1
