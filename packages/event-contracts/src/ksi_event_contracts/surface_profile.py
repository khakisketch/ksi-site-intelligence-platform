"""Height-along-a-line request/result.  Reads one registered surface; claims no volume or accuracy.

Elevation is the bilinear value of the exact registered grid at pixel centres.  A sample that
cannot be read (outside the surface, within half a cell of its edge, NoData) is ``null`` with a
reason — never ``0``, a neighbour value or a straight line across the gap.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal, Self

from pydantic import Field, StrictFloat, model_validator

from ksi_event_contracts._spatial_data import (
    MAX_COUNTER,
    AssetRef,
    Coordinate,
    Digest,
    SpatialDataDigestModel,
    SpatialDataModel,
)
from ksi_event_contracts.measurement_feature import (
    CrsIdentifier,
    MeasurementFeatureRefV1,
    MeasurementLineV1,
)

# Representation ceiling; the worker policy bounds the real read and refuses over-limit input.
MAX_PROFILE_SAMPLES = 5000

NonNegativeMetres = Annotated[StrictFloat, Field(ge=0.0, allow_inf_nan=False)]
PositiveMetres = Annotated[StrictFloat, Field(gt=0.0, allow_inf_nan=False)]

SampleInvalidReasonV1 = Literal["OUTSIDE_SURFACE", "INSUFFICIENT_NEIGHBORS", "NODATA"]
SurfaceProfileRefusalReasonV1 = Literal[
    "INVALID_LINE",
    "INVALID_SAMPLING",
    "TOO_MANY_VERTICES",
    "TOO_MANY_SAMPLES",
    "LINE_TOO_LONG",
    "UNSUPPORTED_CRS",
    "REPROJECTION_FAILED",
    "CRS_MISMATCH",
    "UNREADABLE_RASTER",
    "UNSUPPORTED_RASTER",
    "SOURCE_BLOCK_TOO_LARGE",
    "WINDOW_TOO_LARGE",
    "PLAN_MISMATCH",
]


class CreateSurfaceProfileV1(SpatialDataModel):
    """One read of one exact asset along one line.  Choosing a line or a date sends nothing;
    this request is the explicit act that asks for the read."""

    asset_ref: AssetRef
    line: MeasurementLineV1
    feature: MeasurementFeatureRefV1 | None = None
    # ``None`` = the grid's own resolution.  A finer spacing never adds real resolution.
    sample_spacing_m: PositiveMetres | None = None

    @model_validator(mode="after")
    def _feature_binds_line(self) -> Self:
        if self.feature is not None and self.feature.line_digest != self.line.digest():
            raise ValueError("feature.lineDigest must bind the requested line")
        return self


class SurfaceProfileSampleV1(SpatialDataModel):
    index: int = Field(strict=True, ge=0, lt=MAX_PROFILE_SAMPLES)
    distance_m: NonNegativeMetres
    x: Coordinate
    y: Coordinate
    elevation_m: Coordinate | None
    invalid_reason: SampleInvalidReasonV1 | None

    @model_validator(mode="after")
    def _unknown_carries_a_reason(self) -> Self:
        if (self.elevation_m is None) != (self.invalid_reason is not None):
            raise ValueError(
                "a sample has an elevation or an invalid reason, never both or neither"
            )
        return self


class SurfaceProfileResultV1(SpatialDataDigestModel):
    _digest_field = "result_digest"
    asset_ref: AssetRef
    line_digest: Digest
    feature: MeasurementFeatureRefV1 | None = None
    horizontal_crs: CrsIdentifier
    line_length_m: PositiveMetres
    sample_spacing_m: PositiveMetres
    # 0 = nothing was read (every sample was outside the surface).
    window_cells_read: Annotated[int, Field(strict=True, ge=0, le=MAX_COUNTER)]
    samples: Annotated[
        tuple[SurfaceProfileSampleV1, ...], Field(min_length=2, max_length=MAX_PROFILE_SAMPLES)
    ]
    valid_count: Annotated[int, Field(strict=True, ge=0)]
    unknown_count: Annotated[int, Field(strict=True, ge=0)]
    minimum_m: Coordinate | None
    maximum_m: Coordinate | None
    elevation_meaning: Literal["GRID_BILINEAR_AT_PIXEL_CENTRES"] = "GRID_BILINEAR_AT_PIXEL_CENTRES"
    distance_meaning: Literal["PLANAR_ALONG_LINE_IN_GRID_CRS"] = "PLANAR_ALONG_LINE_IN_GRID_CRS"
    volume_computed: Literal[False] = False
    accuracy_assessed: Literal[False] = False
    result_digest: Digest | None = None

    @model_validator(mode="after")
    def _consistent_samples(self) -> Self:
        rows = self.samples
        if [row.index for row in rows] != list(range(len(rows))):
            raise ValueError("sample indices must be contiguous from 0")
        distances = [row.distance_m for row in rows]
        if distances[0] != 0.0 or any(
            b <= a for a, b in zip(distances, distances[1:], strict=False)
        ):
            raise ValueError("distances must start at 0 and strictly increase")
        if not math.isclose(distances[-1], self.line_length_m, rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError("the last sample must sit at the line end")
        known = [row.elevation_m for row in rows if row.elevation_m is not None]
        if self.valid_count != len(known) or self.unknown_count != len(rows) - len(known):
            raise ValueError("validCount and unknownCount must count the samples")
        if not known:
            if self.minimum_m is not None or self.maximum_m is not None:
                raise ValueError("no known elevation means no minimum or maximum")
        elif self.minimum_m != min(known) or self.maximum_m != max(known):
            raise ValueError("minimum and maximum must come from the known samples only")
        if self.feature is not None and self.feature.line_digest != self.line_digest:
            raise ValueError("feature.lineDigest must equal lineDigest")
        return self


class SurfaceProfileRefusalV1(SpatialDataModel):
    """Typed, bounded refusal — no path, exception text or partial values."""

    reason: SurfaceProfileRefusalReasonV1
    retryable: Literal[False] = False
