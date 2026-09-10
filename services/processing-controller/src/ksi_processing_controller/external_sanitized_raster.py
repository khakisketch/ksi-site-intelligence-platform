"""Deterministic private ORTHO derivative construction for the fixed container entrypoint.

The sanitizer is intentionally narrow: it accepts a byte-identified, already
measured RGB/RGBA ORTHO and writes a fresh RGB COG with a binary internal mask.
It never copies source metadata and does not attempt to repair, resample, crop,
or otherwise reinterpret source pixels.  The caller owns the private workspace
and is responsible for retaining the resulting bytes until its transaction has
completed; this module never publishes a path or receipt.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    RasterMeasurementsV1,
    ResourceEnvelopeV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from rasterio.enums import ColorInterp, Resampling
from rasterio.shutil import copy as rio_copy

from ksi_processing_controller.external_geotiff_inspector import (
    SyntheticGeoTiffInspectionIncomplete,
    inspect_synthetic_sealed_geotiff,
)
from ksi_processing_controller.external_tiff_structure import parse_sealed_tiff_structure


class SanitizedRasterError(RuntimeError):
    """The private derivative did not retain the exact allowed ORTHO facts."""


@dataclass(frozen=True, slots=True)
class SanitizedRasterResultV1:
    """Private candidate binding; it is not an authority, publication, or receipt."""

    output_size_bytes: int
    output_sha256: str
    measurements: RasterMeasurementsV1


def sanitize_measured_ortho(
    *,
    source_path: Path,
    source_observed_sha256: str,
    artifact_id: str,
    output_path: Path,
    envelope: ResourceEnvelopeV1,
    is_cancelled: Callable[[], bool] | None = None,
) -> SanitizedRasterResultV1:
    """Create and verify a fresh private COG from one measured ORTHO input.

    The source scan is repeated in the same closed parser profile before any
    decoder-derived bytes are emitted.  A failed write or re-verification
    removes only the candidate created by this invocation.
    """

    _require_not_cancelled(is_cancelled)
    source = _require_measured_ortho(
        source_path=source_path,
        source_observed_sha256=source_observed_sha256,
        artifact_id=artifact_id,
        envelope=envelope,
        is_cancelled=is_cancelled,
    )
    _require_private_output_parent(output_path.parent)
    if output_path.exists():
        raise SanitizedRasterError("private sanitizer destination already exists")

    candidate_directory = Path(tempfile.mkdtemp(prefix=".sanitize-", dir=output_path.parent))
    intermediate = candidate_directory / "intermediate.tif"
    candidate = candidate_directory / "candidate.tif"
    try:
        _write_exact_rgb_with_mask(
            source_path=source_path,
            destination=intermediate,
            envelope=envelope,
            is_cancelled=is_cancelled,
        )
        _require_not_cancelled(is_cancelled)
        _build_fixed_source_overviews(intermediate, is_cancelled=is_cancelled)
        _require_not_cancelled(is_cancelled)
        _materialize_fixed_mask_overviews(
            intermediate,
            envelope=envelope,
            is_cancelled=is_cancelled,
        )
        _require_not_cancelled(is_cancelled)
        _write_deterministic_cog(intermediate, candidate)
        _require_not_cancelled(is_cancelled)
        candidate_result = verify_sanitized_ortho(
            source_path=source_path,
            source_observed_sha256=source_observed_sha256,
            artifact_id=artifact_id,
            output_path=candidate,
            envelope=envelope,
            expected_source_measurements=source.measurements,
            is_cancelled=is_cancelled,
        )
        os.replace(candidate, output_path)
        _fsync_directory(output_path.parent)
        return candidate_result
    except Exception:
        _unlink_if_regular(output_path)
        raise
    finally:
        shutil.rmtree(candidate_directory, ignore_errors=True)


def verify_sanitized_ortho(
    *,
    source_path: Path,
    source_observed_sha256: str,
    artifact_id: str,
    output_path: Path,
    envelope: ResourceEnvelopeV1,
    expected_output_sha256: str | None = None,
    expected_source_measurements: RasterMeasurementsV1 | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> SanitizedRasterResultV1:
    """Reopen the candidate and require exact full-resolution derivative facts."""

    _require_not_cancelled(is_cancelled)
    source_outcome = _require_measured_ortho(
        source_path=source_path,
        source_observed_sha256=source_observed_sha256,
        artifact_id=artifact_id,
        envelope=envelope,
        is_cancelled=is_cancelled,
    )
    source_measurements = expected_source_measurements or source_outcome.measurements
    assert source_measurements is not None
    output_digest = _digest_file(output_path, envelope.max_output_bytes)
    if expected_output_sha256 is not None and output_digest != expected_output_sha256:
        raise SanitizedRasterError("candidate digest differs from its declared binding")
    output_outcome = inspect_synthetic_sealed_geotiff(
        output_path,
        artifact_id=artifact_id,
        observed_sha256=output_digest,
        artifact_kind=ProcessingArtifactKind.ORTHO,
        envelope=envelope,
        is_cancelled=is_cancelled,
    )
    if (
        output_outcome.outcome is not ArtifactOutcome.MEASURED
        or output_outcome.measurements is None
    ):
        raise SanitizedRasterError("candidate is not a measured ORTHO")
    output_measurements = output_outcome.measurements
    _require_sanitized_measurements(source_measurements, output_measurements)
    _require_exact_full_resolution_pixels_and_mask(
        source_path=source_path,
        output_path=output_path,
        is_cancelled=is_cancelled,
    )
    _require_fresh_overviews(
        output_path=output_path,
        envelope=envelope,
        is_cancelled=is_cancelled,
    )
    _require_no_source_metadata(output_path)
    return SanitizedRasterResultV1(
        output_size_bytes=output_path.stat().st_size,
        output_sha256=output_digest,
        measurements=output_measurements,
    )


def _require_measured_ortho(
    *,
    source_path: Path,
    source_observed_sha256: str,
    artifact_id: str,
    envelope: ResourceEnvelopeV1,
    is_cancelled: Callable[[], bool] | None,
) -> ArtifactInspectionOutcomeV1:
    outcome = inspect_synthetic_sealed_geotiff(
        source_path,
        artifact_id=artifact_id,
        observed_sha256=source_observed_sha256,
        artifact_kind=ProcessingArtifactKind.ORTHO,
        envelope=envelope,
        is_cancelled=is_cancelled,
    )
    if outcome.outcome is not ArtifactOutcome.MEASURED or outcome.measurements is None:
        reason = outcome.reason or "UNSUPPORTED_RASTER"
        raise SanitizedRasterError(f"source ORTHO is not measurable: {reason}")
    return outcome


def _write_exact_rgb_with_mask(
    *,
    source_path: Path,
    destination: Path,
    envelope: ResourceEnvelopeV1,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    """Materialize RGB/mask without carrying tags or source file layout forward."""

    with (
        rasterio.Env(
            PROJ_NETWORK="OFF",
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            GDAL_PAM_ENABLED="NO",
            GDAL_DRIVER_PATH="disable",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS="",
            GDAL_TIFF_INTERNAL_MASK="YES",
            GDAL_NUM_THREADS="1",
        ),
        rasterio.open(source_path, "r", driver="GTiff") as source,
    ):
        profile = {
            "driver": "GTiff",
            "width": source.width,
            "height": source.height,
            "count": 3,
            "dtype": "uint8",
            "crs": source.crs,
            "transform": source.transform,
            "tiled": True,
            "blockxsize": 512,
            "blockysize": 512,
            "compress": "DEFLATE",
            "predictor": 2,
            "interleave": "pixel",
            "photometric": "RGB",
            "BIGTIFF": "IF_SAFER",
            "NUM_THREADS": "1",
            "SPARSE_OK": "FALSE",
        }
        with rasterio.open(destination, "w", **profile) as target:
            for _, window in source.block_windows(1):
                _require_not_cancelled(is_cancelled)
                rgb = source.read((1, 2, 3), window=window)
                if source.count == 4:
                    alpha = source.read(4, window=window)
                    valid = alpha == 255
                else:
                    valid = source.read_masks(1, window=window) == 255
                rgb[:, ~valid] = 0
                target.write(rgb, window=window)
                target.write_mask(np.where(valid, 255, 0).astype(np.uint8), window=window)


def _write_deterministic_cog(intermediate: Path, candidate: Path) -> None:
    """Use GDAL's COG writer with every sanitizer-controlled creation option fixed."""

    with rasterio.Env(
        PROJ_NETWORK="OFF",
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_PAM_ENABLED="NO",
        GDAL_DRIVER_PATH="disable",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS="",
        GDAL_TIFF_INTERNAL_MASK="YES",
        GDAL_NUM_THREADS="1",
    ):
        rio_copy(
            intermediate,
            candidate,
            driver="COG",
            BLOCKSIZE=512,
            COMPRESS="DEFLATE",
            PREDICTOR=2,
            RESAMPLING="AVERAGE",
            OVERVIEW_RESAMPLING="AVERAGE",
            NUM_THREADS=1,
            BIGTIFF="IF_SAFER",
            SPARSE_OK="FALSE",
            GEOTIFF_VERSION="1.1",
            OVERVIEWS="FORCE_USE_EXISTING",
        )


def _build_fixed_source_overviews(
    intermediate: Path,
    *,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    """Materialize the exact ceil-reduction chain before COG layout serialization.

    The COG driver otherwise rounds odd dimensions while synthesizing its own
    overviews.  Supplying explicit base-image factors makes the driver's COG
    serialization preserve the closed profile's ceil geometry.  GDAL's average
    resampler has separate validity-mask semantics, so the physical mask IFDs
    are replaced explicitly below with this profile's nearest binary chain.
    """

    with (
        rasterio.Env(
            PROJ_NETWORK="OFF",
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            GDAL_PAM_ENABLED="NO",
            GDAL_DRIVER_PATH="disable",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS="",
            GDAL_TIFF_INTERNAL_MASK="YES",
            GDAL_NUM_THREADS="1",
        ),
        rasterio.open(intermediate, "r+") as dataset,
    ):
        factors = _fixed_overview_factors(dataset.width, dataset.height)
        if not factors:
            return
        _require_not_cancelled(is_cancelled)
        dataset.build_overviews(factors, Resampling.average)
        dataset.update_tags(ns="rio_overview", resampling="average")
        _require_not_cancelled(is_cancelled)


def _materialize_fixed_mask_overviews(
    intermediate: Path,
    *,
    envelope: ResourceEnvelopeV1,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    """Materialize the fixed physical image/mask overview chain before COG copy.

    GDAL creates the cumulative image factors from the base and reduces masks
    with its validity semantics.  Both differ from the closed chain at later
    odd-sized levels, where every image level must average its predecessor and
    every binary mask level must nearest-sample its predecessor.  We overwrite
    the already allocated IFDs, so the later COG copy only serializes the
    established chain and receives no alternate overview route.
    """

    pairs = _physical_overview_pairs(intermediate, envelope)
    if not pairs:
        return
    previous_image_index: int | None = None
    previous_mask_index: int | None = None
    previous_width: int | None = None
    previous_height: int | None = None
    with rasterio.Env(
        PROJ_NETWORK="OFF",
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_PAM_ENABLED="NO",
        GDAL_DRIVER_PATH="disable",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS="",
        GDAL_TIFF_INTERNAL_MASK="YES",
        GDAL_NUM_THREADS="1",
    ):
        for image_index, mask_index, width, height in pairs:
            _require_not_cancelled(is_cancelled)
            if previous_mask_index is None:
                source_image_name = str(intermediate)
                source_mask_name = str(intermediate)
            else:
                assert previous_image_index is not None
                source_image_name = f"GTIFF_DIR:{previous_image_index}:{intermediate}"
                source_mask_name = f"GTIFF_DIR:{previous_mask_index}:{intermediate}"
            with (
                rasterio.open(source_image_name, "r", driver="GTiff") as source_image,
                rasterio.open(source_mask_name, "r", driver="GTiff") as source_mask,
                rasterio.open(
                    f"GTIFF_DIR:{image_index}:{intermediate}",
                    "r+",
                    driver="GTiff",
                    IGNORE_COG_LAYOUT_BREAK="YES",
                ) as target_image,
            ):
                if (
                    target_image.count != 3
                    or target_image.width != width
                    or target_image.height != height
                ):
                    raise SanitizedRasterError("generated physical image overview is inconsistent")
                _overwrite_average_image_overview(
                    source_image=source_image,
                    source_mask=source_mask,
                    source_mask_is_dataset_mask=previous_mask_index is None,
                    target_image=target_image,
                    is_cancelled=is_cancelled,
                )
            with (
                rasterio.open(source_mask_name, "r", driver="GTiff") as source_mask,
                rasterio.open(
                    f"GTIFF_DIR:{mask_index}:{intermediate}",
                    "r+",
                    driver="GTiff",
                    IGNORE_COG_LAYOUT_BREAK="YES",
                ) as target_mask,
            ):
                if (
                    target_mask.count != 1
                    or target_mask.width != width
                    or target_mask.height != height
                ):
                    raise SanitizedRasterError("generated physical mask overview is inconsistent")
                if previous_width is not None and previous_height is not None:
                    if width != (previous_width + 1) // 2 or height != (previous_height + 1) // 2:
                        raise SanitizedRasterError(
                            "generated mask overview chain is not factor-two ceil"
                        )
                elif (
                    width != (source_mask.width + 1) // 2 or height != (source_mask.height + 1) // 2
                ):
                    raise SanitizedRasterError(
                        "generated mask overview chain is not factor-two ceil"
                    )
                _overwrite_nearest_mask_overview(
                    source_mask=source_mask,
                    source_is_dataset_mask=previous_mask_index is None,
                    target_mask=target_mask,
                    is_cancelled=is_cancelled,
                )
            previous_image_index = image_index
            previous_mask_index = mask_index
            previous_width = width
            previous_height = height


def _physical_overview_pairs(
    path: Path,
    envelope: ResourceEnvelopeV1,
) -> list[tuple[int, int, int, int]]:
    """Return physical image/mask IFD pairs in the raw TIFF overview order."""

    structure = parse_sealed_tiff_structure(path, envelope)
    byte_order = "<" if structure.byte_order == "II" else ">"
    image_overviews: list[tuple[int, int, int]] = []
    mask_overviews: dict[tuple[int, int], int] = {}
    for index, directory in enumerate(structure.directories, start=1):
        subtype_entry = directory.entries.get(254)
        subtype = 0 if subtype_entry is None else subtype_entry.integers(byte_order)[0]
        width_values = directory.entries[256].integers(byte_order)
        height_values = directory.entries[257].integers(byte_order)
        if len(width_values) != 1 or len(height_values) != 1:
            raise SanitizedRasterError("generated overview dimensions are ambiguous")
        dimensions = (width_values[0], height_values[0])
        if subtype == 1:
            image_overviews.append((index, *dimensions))
        elif subtype == 5:
            if dimensions in mask_overviews:
                raise SanitizedRasterError("generated mask overview dimensions are ambiguous")
            mask_overviews[dimensions] = index
    pairs: list[tuple[int, int, int, int]] = []
    for image_index, width, height in image_overviews:
        mask_index = mask_overviews.get((width, height))
        if mask_index is None:
            raise SanitizedRasterError("generated overview has no physical mask IFD")
        pairs.append((image_index, mask_index, width, height))
    if len(pairs) != len(mask_overviews):
        raise SanitizedRasterError("generated mask IFD chain differs from image overview chain")
    return pairs


def _overwrite_nearest_mask_overview(
    *,
    source_mask: rasterio.io.DatasetReader,
    source_is_dataset_mask: bool,
    target_mask: rasterio.io.DatasetWriter,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    """Write one factor-two ceil nearest binary mask IFD without full-image buffering."""

    block = 64
    for row_offset in range(0, target_mask.height, block):
        for column_offset in range(0, target_mask.width, block):
            _require_not_cancelled(is_cancelled)
            height = min(block, target_mask.height - row_offset)
            width = min(block, target_mask.width - column_offset)
            source_rows = _nearest_source_indices(
                source_size=source_mask.height,
                destination_size=target_mask.height,
                destination_offset=row_offset,
                count=height,
            )
            source_columns = _nearest_source_indices(
                source_size=source_mask.width,
                destination_size=target_mask.width,
                destination_offset=column_offset,
                count=width,
            )
            source_window = rasterio.windows.Window(
                int(source_columns[0]),
                int(source_rows[0]),
                int(source_columns[-1] - source_columns[0] + 1),
                int(source_rows[-1] - source_rows[0] + 1),
            )
            if source_is_dataset_mask:
                source_values = source_mask.read_masks(1, window=source_window)
            else:
                source_values = source_mask.read(1, window=source_window) * 255
            nearest = _nearest_binary_mask(
                source_values,
                source_rows=source_rows,
                source_columns=source_columns,
                source_window=source_window,
            )
            target_mask.write(
                nearest,
                1,
                window=rasterio.windows.Window(column_offset, row_offset, width, height),
            )


def _overwrite_average_image_overview(
    *,
    source_image: rasterio.io.DatasetReader,
    source_mask: rasterio.io.DatasetReader,
    source_mask_is_dataset_mask: bool,
    target_image: rasterio.io.DatasetWriter,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    """Write one average-color level from the immediately preceding IFD."""

    block = 64
    for row_offset in range(0, target_image.height, block):
        for column_offset in range(0, target_image.width, block):
            _require_not_cancelled(is_cancelled)
            height = min(block, target_image.height - row_offset)
            width = min(block, target_image.width - column_offset)
            output_window = rasterio.windows.Window(column_offset, row_offset, width, height)
            source_window = _average_source_window(
                base_width=source_image.width,
                base_height=source_image.height,
                overview_width=target_image.width,
                overview_height=target_image.height,
                output_column=column_offset,
                output_row=row_offset,
                output_width=width,
                output_height=height,
            )
            if source_mask_is_dataset_mask:
                mask = source_mask.read_masks(1, window=source_window)
            else:
                mask = source_mask.read(1, window=source_window) * 255
            averaged = _average_rgb(
                source_image.read((1, 2, 3), window=source_window),
                mask,
                source_window=source_window,
                base_width=source_image.width,
                base_height=source_image.height,
                overview_width=target_image.width,
                overview_height=target_image.height,
                output_column=column_offset,
                output_row=row_offset,
                output_width=width,
                output_height=height,
            )
            target_image.write(averaged, window=output_window)


def _fixed_overview_factors(width: int, height: int) -> list[int]:
    """Return the profile's cumulative factor-2 ceil chain through 512 pixels."""

    factors: list[int] = []
    current_width, current_height = width, height
    factor = 1
    while current_width > 512 or current_height > 512:
        factor *= 2
        factors.append(factor)
        current_width = (current_width + 1) // 2
        current_height = (current_height + 1) // 2
    return factors


def _require_sanitized_measurements(
    source: RasterMeasurementsV1,
    output: RasterMeasurementsV1,
) -> None:
    if (
        output.band_count != 3
        or output.dtype != "uint8"
        or output.layout != "COG_PROFILE_V1"
        or output.nodata_representation.value != "MASK"
        or output.nodata_value is not None
    ):
        raise SanitizedRasterError(
            "candidate sample model or layout differs from sanitizer profile"
        )
    for attribute in (
        "observed_crs_identifier",
        "observed_crs_wkt",
        "observed_crs_digest",
        "observed_vertical_reference",
        "transform",
        "footprint_wkt",
        "footprint_digest",
        "width",
        "height",
        "valid_pixel_count",
    ):
        if getattr(output, attribute) != getattr(source, attribute):
            raise SanitizedRasterError(f"candidate changed source {attribute}")


def _require_exact_full_resolution_pixels_and_mask(
    *,
    source_path: Path,
    output_path: Path,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    with (
        rasterio.Env(
            PROJ_NETWORK="OFF",
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            GDAL_PAM_ENABLED="NO",
            GDAL_DRIVER_PATH="disable",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS="",
        ),
        rasterio.open(source_path, "r", driver="GTiff") as source,
        rasterio.open(output_path, "r", driver="GTiff") as output,
    ):
        if (
            output.count != 3
            or output.dtypes != ("uint8", "uint8", "uint8")
            or tuple(output.colorinterp) != (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
            or output.width != source.width
            or output.height != source.height
            or output.transform != source.transform
            or output.crs != source.crs
        ):
            raise SanitizedRasterError("candidate changed the full-resolution raster model")
        for _, window in source.block_windows(1):
            _require_not_cancelled(is_cancelled)
            source_rgb = source.read((1, 2, 3), window=window)
            if source.count == 4:
                valid = source.read(4, window=window) == 255
            else:
                valid = source.read_masks(1, window=window) == 255
            expected = source_rgb.copy()
            expected[:, ~valid] = 0
            output_rgb = output.read((1, 2, 3), window=window)
            output_mask = output.read_masks(1, window=window)
            if not np.array_equal(expected, output_rgb):
                raise SanitizedRasterError("candidate changed a valid pixel")
            if not np.array_equal(output_mask, np.where(valid, 255, 0).astype(np.uint8)):
                raise SanitizedRasterError("candidate changed the binary mask")


def _require_no_source_metadata(output_path: Path) -> None:
    with (
        rasterio.Env(GDAL_PAM_ENABLED="NO"),
        rasterio.open(output_path, "r", driver="GTiff") as output,
    ):
        tags = output.tags()
        if any(key.upper().startswith("STATISTICS_") for key in tags):
            raise SanitizedRasterError("candidate retained statistics metadata")
        if any(key.casefold() == "producer_note" for key in tags):
            raise SanitizedRasterError("candidate retained source metadata")


def _require_fresh_overviews(
    *,
    output_path: Path,
    envelope: ResourceEnvelopeV1,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    """Verify the fixed average-color and nearest-binary-mask overview policy.

    The scanner already visits every physical IFD.  This output-only comparison
    additionally proves that those IFDs are fresh derivatives of this candidate
    rather than arbitrary alternate-resolution pixels.
    """

    structure = parse_sealed_tiff_structure(output_path, envelope)
    byte_order = "<" if structure.byte_order == "II" else ">"
    image_overviews: list[int] = []
    mask_overviews: dict[tuple[int, int], int] = {}
    for index, directory in enumerate(structure.directories, start=1):
        subtype_entry = directory.entries.get(254)
        subtype = 0 if subtype_entry is None else subtype_entry.integers(byte_order)[0]
        if subtype == 1:
            image_overviews.append(index)
        elif subtype == 5:
            width = directory.entries[256].integers(byte_order)
            height = directory.entries[257].integers(byte_order)
            if len(width) != 1 or len(height) != 1:
                raise SanitizedRasterError("candidate mask overview dimensions are ambiguous")
            mask_overviews[(width[0], height[0])] = index
    with (
        rasterio.Env(
            PROJ_NETWORK="OFF",
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            GDAL_PAM_ENABLED="NO",
            GDAL_DRIVER_PATH="disable",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS="",
        ),
        rasterio.open(output_path, "r", driver="GTiff") as base,
    ):
        factors = tuple(base.overviews(1))
        if len(image_overviews) != len(factors):
            raise SanitizedRasterError("candidate overview directory chain differs from its base")
        previous_image_index: int | None = None
        previous_mask_index: int | None = None
        previous_factor = 1
        for index, factor in zip(image_overviews, factors, strict=True):
            with rasterio.open(f"GTIFF_DIR:{index}:{output_path}", "r", driver="GTiff") as overview:
                mask_index = mask_overviews.get((overview.width, overview.height))
                if mask_index is None:
                    raise SanitizedRasterError("candidate lacks a physical binary mask overview")
                with rasterio.open(
                    f"GTIFF_DIR:{mask_index}:{output_path}", "r", driver="GTiff"
                ) as mask_overview:
                    if previous_image_index is None or previous_mask_index is None:
                        _require_fixed_overview_pixels(
                            source_image=base,
                            source_mask=lambda window: base.read_masks(1, window=window),
                            overview=overview,
                            mask_overview=mask_overview,
                            local_factor=factor,
                            is_cancelled=is_cancelled,
                        )
                    else:
                        if factor % previous_factor:
                            raise SanitizedRasterError(
                                "candidate overview factors are not integral"
                            )
                        with (
                            rasterio.open(
                                f"GTIFF_DIR:{previous_image_index}:{output_path}",
                                "r",
                                driver="GTiff",
                            ) as previous_image,
                            rasterio.open(
                                f"GTIFF_DIR:{previous_mask_index}:{output_path}",
                                "r",
                                driver="GTiff",
                            ) as previous_mask,
                        ):
                            _require_fixed_overview_pixels(
                                source_image=previous_image,
                                source_mask=lambda window: (
                                    previous_mask.read(1, window=window) * 255
                                ),
                                overview=overview,
                                mask_overview=mask_overview,
                                local_factor=factor // previous_factor,
                                is_cancelled=is_cancelled,
                            )
                previous_image_index = index
                previous_mask_index = mask_index
                previous_factor = factor


def _require_fixed_overview_pixels(
    *,
    source_image: rasterio.io.DatasetReader,
    source_mask: Callable[[rasterio.windows.Window], np.ndarray],
    overview: rasterio.io.DatasetReader,
    mask_overview: rasterio.io.DatasetReader,
    local_factor: int,
    is_cancelled: Callable[[], bool] | None,
) -> None:
    if local_factor < 2 or overview.count != 3 or mask_overview.count != 1:
        raise SanitizedRasterError("candidate overview model is outside the fixed sanitizer policy")
    block = 64
    for row_offset in range(0, overview.height, block):
        for column_offset in range(0, overview.width, block):
            _require_not_cancelled(is_cancelled)
            height = min(block, overview.height - row_offset)
            width = min(block, overview.width - column_offset)
            output_window = rasterio.windows.Window(column_offset, row_offset, width, height)
            image_source_window = _average_source_window(
                base_width=source_image.width,
                base_height=source_image.height,
                overview_width=overview.width,
                overview_height=overview.height,
                output_column=column_offset,
                output_row=row_offset,
                output_width=width,
                output_height=height,
            )
            source_rgb = source_image.read((1, 2, 3), window=image_source_window)
            image_mask = source_mask(image_source_window)
            expected_rgb = _average_rgb(
                source_rgb,
                image_mask,
                source_window=image_source_window,
                base_width=source_image.width,
                base_height=source_image.height,
                overview_width=overview.width,
                overview_height=overview.height,
                output_column=column_offset,
                output_row=row_offset,
                output_width=width,
                output_height=height,
            )
            if local_factor != 2:
                raise SanitizedRasterError("candidate mask overview reduction is not factor-two")
            source_rows = _nearest_source_indices(
                source_size=source_image.height,
                destination_size=overview.height,
                destination_offset=row_offset,
                count=height,
            )
            source_columns = _nearest_source_indices(
                source_size=source_image.width,
                destination_size=overview.width,
                destination_offset=column_offset,
                count=width,
            )
            mask_source_window = rasterio.windows.Window(
                int(source_columns[0]),
                int(source_rows[0]),
                int(source_columns[-1] - source_columns[0] + 1),
                int(source_rows[-1] - source_rows[0] + 1),
            )
            expected_mask = _nearest_binary_mask(
                source_mask(mask_source_window),
                source_rows=source_rows,
                source_columns=source_columns,
                source_window=mask_source_window,
            )
            if not np.array_equal(overview.read(window=output_window), expected_rgb):
                raise SanitizedRasterError(
                    "candidate overview is not a fresh average-color derivative"
                )
            if not np.array_equal(mask_overview.read(1, window=output_window), expected_mask):
                raise SanitizedRasterError(
                    "candidate mask overview is not a fresh nearest-mask derivative"
                )


def _average_source_window(
    *,
    base_width: int,
    base_height: int,
    overview_width: int,
    overview_height: int,
    output_column: int,
    output_row: int,
    output_width: int,
    output_height: int,
) -> rasterio.windows.Window:
    """Bound one output block's fractional-source coverage for GDAL AVERAGE."""

    column_start = output_column * base_width // overview_width
    column_end = -(-((output_column + output_width) * base_width) // overview_width)
    row_start = output_row * base_height // overview_height
    row_end = -(-((output_row + output_height) * base_height) // overview_height)
    return rasterio.windows.Window(
        column_start,
        row_start,
        column_end - column_start,
        row_end - row_start,
    )


def _average_rgb(
    values: np.ndarray,
    mask: np.ndarray,
    *,
    source_window: rasterio.windows.Window,
    base_width: int,
    base_height: int,
    overview_width: int,
    overview_height: int,
    output_column: int,
    output_row: int,
    output_width: int,
    output_height: int,
) -> np.ndarray:
    output = np.empty((3, output_height, output_width), dtype=np.uint8)
    for row in range(output_height):
        global_row = output_row + row
        row_start = global_row * base_height / overview_height
        row_end = (global_row + 1) * base_height / overview_height
        source_rows = range(int(np.floor(row_start)), int(np.ceil(row_end)))
        for column in range(output_width):
            global_column = output_column + column
            column_start = global_column * base_width / overview_width
            column_end = (global_column + 1) * base_width / overview_width
            source_columns = range(int(np.floor(column_start)), int(np.ceil(column_end)))
            weighted_sum = np.zeros(3, dtype=np.float64)
            weight = 0.0
            for source_row in source_rows:
                row_weight = min(row_end, source_row + 1) - max(row_start, source_row)
                if row_weight <= 0:
                    continue
                local_row = source_row - int(source_window.row_off)
                for source_column in source_columns:
                    column_weight = min(column_end, source_column + 1) - max(
                        column_start, source_column
                    )
                    if column_weight <= 0:
                        continue
                    local_column = source_column - int(source_window.col_off)
                    if mask[local_row, local_column] != 255:
                        continue
                    contribution = row_weight * column_weight
                    weighted_sum += values[:, local_row, local_column] * contribution
                    weight += contribution
            if weight == 0:
                output[:, row, column] = 0
            else:
                output[:, row, column] = np.floor(weighted_sum / weight + 0.5).astype(np.uint8)
    return output


def _nearest_source_indices(
    *,
    source_size: int,
    destination_size: int,
    destination_offset: int,
    count: int,
) -> np.ndarray:
    """Return GDAL NEAREST indices using exact integer arithmetic.

    The profile's factor-two chain has ceil dimensions.  Its final pixels are
    therefore selected by the actual source/destination dimension ratio, not a
    simple stride, as implemented by GDAL 3.12's nearest overview path.
    """

    if (
        source_size <= 0
        or destination_size <= 0
        or destination_offset < 0
        or count <= 0
        or destination_offset > destination_size - count
    ):
        raise SanitizedRasterError("candidate mask overview has invalid nearest dimensions")
    destinations = np.arange(destination_offset, destination_offset + count, dtype=np.int64)
    indices = (2 * destinations * source_size + destination_size) // (2 * destination_size)
    if indices[0] < 0 or indices[-1] >= source_size:
        raise SanitizedRasterError("candidate mask overview maps outside its full-resolution base")
    return indices


def _nearest_binary_mask(
    mask: np.ndarray,
    *,
    source_rows: np.ndarray,
    source_columns: np.ndarray,
    source_window: rasterio.windows.Window,
) -> np.ndarray:
    local_rows = source_rows - int(source_window.row_off)
    local_columns = source_columns - int(source_window.col_off)
    if (
        local_rows[0] < 0
        or local_columns[0] < 0
        or local_rows[-1] >= mask.shape[0]
        or local_columns[-1] >= mask.shape[1]
    ):
        raise SanitizedRasterError("candidate mask overview maps outside its source window")
    return (mask[np.ix_(local_rows, local_columns)] == 255).astype(np.uint8)


def _digest_file(path: Path, maximum_bytes: int) -> str:
    try:
        state = path.stat()
    except OSError as exc:
        raise SanitizedRasterError("candidate is unavailable") from exc
    if not path.is_file() or state.st_size <= 0 or state.st_size > maximum_bytes:
        raise SanitizedRasterError("candidate exceeds its finite output envelope")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _require_private_output_parent(parent: Path) -> None:
    try:
        parent.stat()
    except OSError as exc:
        raise SanitizedRasterError("private sanitizer workspace is unavailable") from exc
    if not parent.is_dir():
        raise SanitizedRasterError("private sanitizer workspace is not a directory")


def _unlink_if_regular(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_not_cancelled(is_cancelled: Callable[[], bool] | None) -> None:
    if is_cancelled is not None and is_cancelled():
        raise SyntheticGeoTiffInspectionIncomplete("sanitizer cancelled")


__all__ = [
    "SanitizedRasterError",
    "SanitizedRasterResultV1",
    "sanitize_measured_ortho",
    "verify_sanitized_ortho",
]
