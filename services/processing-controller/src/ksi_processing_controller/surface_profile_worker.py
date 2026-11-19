"""Run one bounded surface-profile read over an already-authorised local raster.

This adapter only maps the pure ``ksi_geo_spatial.surface_profile`` calculation onto the
``surface-profile.v1`` contract.  Resolving an asset reference to verified bytes, the caller's
site/work-area grant, AI-egress consent and the policy limits are the caller's gates — this
function never opens a path it was not handed and never widens a limit it was given.
"""

from __future__ import annotations

import hashlib
import os
import stat
import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import rasterio
from ksi_event_contracts.measurement_feature import MAX_LINE_VERTICES
from ksi_event_contracts.surface_profile import (
    MAX_PROFILE_SAMPLES,
    CreateSurfaceProfileV1,
    SurfaceProfileRefusalV1,
    SurfaceProfileResultV1,
    SurfaceProfileSampleV1,
)
from ksi_event_contracts.surface_profile_job import (
    SurfaceProfileFrozenJobV1,
    SurfaceProfileJobReasonV1,
)

if TYPE_CHECKING:
    from ksi_geo_spatial.surface_profile import (
        ProfileSourceFacts,
        SurfaceProfilePlan,
        SurfaceProfilePolicy,
    )
from ksi_geo_spatial.external_native_window import verify_external_surface_profile_source
from ksi_geo_spatial.external_native_window_geometry import NativeWindowError


class SurfaceProfileWorkerError(RuntimeError):
    def __init__(self, reason: SurfaceProfileJobReasonV1) -> None:
        self.reason = reason
        super().__init__(reason)


def _verify_read_window(
    job: SurfaceProfileFrozenJobV1,
    source: ProfileSourceFacts,
    plan: SurfaceProfilePlan,
    dataset: rasterio.DatasetReader,
    raster_path: Path,
) -> None:
    from ksi_geo_spatial.surface_profile import profile_window_geometry
    from rasterio.enums import MaskFlags

    measured = job.source.inspection.measurements
    assert measured is not None
    window = profile_window_geometry(measured, plan)
    allowed = job.read_window
    if window is None or allowed is None:
        raise SurfaceProfileWorkerError("LINE_OUTSIDE_SURFACE")
    if window.pixel_window != allowed.pixel_window or window.actual_bounds != allowed.actual_bounds:
        raise SurfaceProfileWorkerError("OUTPUT_OUTSIDE_GRANT")

    # A narrow read can still decode multiple whole TIFF storage blocks.
    item_size = np.dtype(measured.dtype).itemsize
    col0, col1, row0, row1 = window.pixel_window
    block_columns = (col1 - 1) // source.block_cols - col0 // source.block_cols + 1
    block_rows = (row1 - 1) // source.block_rows - row0 // source.block_rows + 1
    data_block_count = block_columns * block_rows

    def covered_axis_bytes(
        start: int, stop: int, block_size: int, extent: int, *, tiled: bool
    ) -> int:
        first, last = start // block_size, (stop - 1) // block_size
        block_count = last - first + 1
        if tiled:
            return block_count * block_size
        return min((last + 1) * block_size, extent) - first * block_size

    data_tiled = bool(dataset.profile.get("tiled", False))
    data_cols = covered_axis_bytes(col0, col1, source.block_cols, source.width, tiled=data_tiled)
    data_rows = covered_axis_bytes(row0, row1, source.block_rows, source.height, tiled=data_tiled)
    decoded_bytes = data_cols * data_rows * item_size
    block_count = data_block_count

    # Rasterio returns the window mask as one byte per sample. If it is backed by an
    # internal mask IFD, separately account for every intersecting mask storage block.
    window_mask_bytes = allowed.cells
    if MaskFlags.per_dataset in set(dataset.mask_flag_enums[0]):
        try:
            from ksi_processing_controller.external_tiff_structure import (
                TiffResourceLimitError,
                read_base_mask_block_geometry,
            )

            mask = read_base_mask_block_geometry(
                raster_path,
                max_directories=job.policy.resource_envelope.max_tiff_directories,
                max_entries=job.policy.resource_envelope.max_tiff_entries,
            )
        except TiffResourceLimitError as error:
            raise SurfaceProfileWorkerError("RESOURCE_LIMIT_EXCEEDED") from error
        except (OSError, ValueError) as error:
            raise SurfaceProfileWorkerError("SOURCE_MEASUREMENTS_MISMATCH") from error
        if (
            measured.width * measured.height > job.policy.maximum_source_block_cells
            and mask.block_width * mask.block_height > job.policy.maximum_source_block_cells
        ):
            raise SurfaceProfileWorkerError("SOURCE_BLOCK_TOO_LARGE")
        mask_cols = covered_axis_bytes(col0, col1, mask.block_width, mask.width, tiled=mask.tiled)
        mask_rows = covered_axis_bytes(row0, row1, mask.block_height, mask.height, tiled=mask.tiled)
        mask_block_columns = (col1 - 1) // mask.block_width - col0 // mask.block_width + 1
        mask_block_rows = (row1 - 1) // mask.block_height - row0 // mask.block_height + 1
        block_count += mask_block_columns * mask_block_rows
        decoded_bytes += mask_cols * mask_rows

    decoded_bytes += window_mask_bytes
    envelope = job.policy.resource_envelope
    if (
        allowed.cells * (item_size + 1) > envelope.max_sample_bytes
        or block_count > envelope.max_blocks
        or decoded_bytes > envelope.max_decompressed_bytes
    ):
        raise SurfaceProfileWorkerError("RESOURCE_LIMIT_EXCEEDED")


def read_surface_profile(
    request: CreateSurfaceProfileV1,
    raster_path: Path,
    *,
    policy: SurfaceProfilePolicy,
    frozen_job: SurfaceProfileFrozenJobV1 | None = None,
) -> SurfaceProfileResultV1 | SurfaceProfileRefusalV1:
    """Sealed result for the exact request line, or a typed refusal with no partial values."""
    from ksi_geo_spatial.surface_profile import (
        SurfaceProfileError,
        inspect_profile_source,
        open_profile_raster,
        plan_surface_profile,
        sample_surface_profile,
    )
    from rasterio.errors import RasterioIOError

    # The result contract has its own ceilings.  Apply them as limits *before* reading, so a
    # generous policy refuses over-ceiling input up front instead of failing after the read.
    policy = replace(
        policy,
        maximum_samples=min(policy.maximum_samples, MAX_PROFILE_SAMPLES),
        maximum_vertices=min(policy.maximum_vertices, MAX_LINE_VERTICES),
    )
    try:
        with open_profile_raster(raster_path) as dataset:
            source = inspect_profile_source(dataset)
            if frozen_job is not None:
                measured = frozen_job.source.inspection.measurements
                assert measured is not None
                try:
                    verify_external_surface_profile_source(dataset, measurements=measured)
                except NativeWindowError as error:
                    if error.reason == "CRS_MISMATCH":
                        raise SurfaceProfileWorkerError("CRS_MISMATCH") from error
                    if error.reason == "UNSUPPORTED_SOURCE_PROFILE":
                        raise SurfaceProfileWorkerError("UNSUPPORTED_RASTER") from error
                    raise SurfaceProfileWorkerError("SOURCE_MEASUREMENTS_MISMATCH") from error
            spacing = request.sample_spacing_m or source.ground_sample_distance_m
            plan = plan_surface_profile(
                request.line.vertices,
                vertices_crs=request.line.crs,
                horizontal_crs=source.horizontal_crs,
                sample_spacing_m=spacing,
                policy=policy,
            )
            if frozen_job is not None:
                _verify_read_window(frozen_job, source, plan, dataset, raster_path)
            profile = sample_surface_profile(dataset, plan, policy=policy)
    except RasterioIOError:
        return SurfaceProfileRefusalV1(reason="UNREADABLE_RASTER")
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


def compute_verified_surface_profile(
    job: SurfaceProfileFrozenJobV1, source_path: Path
) -> SurfaceProfileResultV1:
    """Read only the staged inode whose bytes and grid agree with Core's frozen input."""
    from ksi_geo_spatial.surface_profile import SurfaceProfilePolicy

    source = job.source
    policy = job.policy
    env = policy.resource_envelope
    size = source.observed_size_bytes
    if size > min(env.max_input_bytes, env.max_streamed_bytes, env.max_workspace_bytes):
        raise SurfaceProfileWorkerError("RESOURCE_LIMIT_EXCEEDED")
    fd = os.open(source_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as staged:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != size:
            raise SurfaceProfileWorkerError("SOURCE_BYTES_MISMATCH")
        remaining = size
        digest = hashlib.sha256()
        while remaining:
            chunk = staged.read(min(remaining, 65_536))
            if not chunk:
                raise SurfaceProfileWorkerError("SOURCE_BYTES_MISMATCH")
            digest.update(chunk)
            remaining -= len(chunk)
        if staged.read(1) or "sha256:" + digest.hexdigest() != source.observed_sha256:
            raise SurfaceProfileWorkerError("SOURCE_BYTES_MISMATCH")
        staged.seek(0)
        # Keep a single GDAL dataset on the verified inode for both its metadata and samples.
        # The launcher is responsible for the read-only input mount.
        descriptor_root = "/proc/self/fd" if sys.platform == "linux" else "/dev/fd"
        outcome = read_surface_profile(
            CreateSurfaceProfileV1(
                asset_ref=job.profile_request.asset_ref,
                line=job.profile_request.line,
                feature=job.profile_request.feature,
                sample_spacing_m=job.profile_request.sample_spacing_m,
            ),
            Path(descriptor_root) / str(fd),
            policy=SurfaceProfilePolicy(
                maximum_vertices=policy.maximum_vertices,
                maximum_samples=policy.maximum_samples,
                maximum_line_length_m=policy.maximum_line_length_m,
                maximum_window_cells=policy.maximum_window_cells,
                maximum_source_block_cells=policy.maximum_source_block_cells,
            ),
            frozen_job=job,
        )
        if isinstance(outcome, SurfaceProfileRefusalV1):
            raise SurfaceProfileWorkerError(outcome.reason)
        return outcome
