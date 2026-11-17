"""Run one bounded surface-profile read over an already-authorised local raster.

This adapter only maps the pure ``ksi_geo_spatial.surface_profile`` calculation onto the
``surface-profile.v1`` contract.  Resolving an asset reference to verified bytes, the caller's
site/work-area grant, AI-egress consent and the policy limits are the caller's gates — this
function never opens a path it was not handed and never widens a limit it was given.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ksi_event_contracts.measurement_feature import MAX_LINE_VERTICES
from ksi_event_contracts.surface_profile import (
    MAX_PROFILE_SAMPLES,
    CreateSurfaceProfileV1,
    SurfaceProfileRefusalV1,
    SurfaceProfileResultV1,
    SurfaceProfileSampleV1,
)
from ksi_geo_spatial.surface_profile import (
    SurfaceProfileError,
    SurfaceProfilePolicy,
    inspect_profile_source,
    plan_surface_profile,
    sample_surface_profile,
)


def read_surface_profile(
    request: CreateSurfaceProfileV1,
    raster_path: Path,
    *,
    policy: SurfaceProfilePolicy,
) -> SurfaceProfileResultV1 | SurfaceProfileRefusalV1:
    """Sealed result for the exact request line, or a typed refusal with no partial values."""
    # The result contract has its own ceilings.  Apply them as limits *before* reading, so a
    # generous policy refuses over-ceiling input up front instead of failing after the read.
    policy = replace(
        policy,
        maximum_samples=min(policy.maximum_samples, MAX_PROFILE_SAMPLES),
        maximum_vertices=min(policy.maximum_vertices, MAX_LINE_VERTICES),
    )
    try:
        source = inspect_profile_source(raster_path)
        spacing = request.sample_spacing_m or source.ground_sample_distance_m
        plan = plan_surface_profile(
            request.line.vertices,
            vertices_crs=request.line.crs,
            horizontal_crs=source.horizontal_crs,
            sample_spacing_m=spacing,
            policy=policy,
        )
        profile = sample_surface_profile(raster_path, plan, policy=policy)
    except SurfaceProfileError as error:
        return SurfaceProfileRefusalV1(reason=error.reason.value)
    elevations = [row.elevation_m for row in profile.samples if row.elevation_m is not None]
    return SurfaceProfileResultV1(
        asset_ref=request.asset_ref,
        line_digest=request.line.digest(),
        feature=request.feature,
        horizontal_crs=plan.horizontal_crs,
        line_length_m=plan.line_length_m,
        sample_spacing_m=plan.sample_spacing_m,
        window_cells_read=profile.window_cells_read,
        samples=tuple(
            SurfaceProfileSampleV1(
                index=row.index,
                distance_m=row.distance_m,
                x=row.x,
                y=row.y,
                elevation_m=row.elevation_m,
                invalid_reason=row.invalid_reason.value if row.invalid_reason else None,
            )
            for row in profile.samples
        ),
        valid_count=len(elevations),
        unknown_count=len(profile.samples) - len(elevations),
        minimum_m=min(elevations) if elevations else None,
        maximum_m=max(elevations) if elevations else None,
    ).sealed()
