"""Private, native-grid windows from an already measured external GeoTIFF.

This module is an import-only raster primitive.  It does not grant access to an
artifact, decide customer rights, publish a URL, or establish accuracy.  Its
caller must supply a Core-authorized exact artifact and a finite worker policy.
"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import stat
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from affine import Affine
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
    NodataRepresentation,
    ObservedVerticalReferenceV1,
    RasterMeasurementsV1,
    ResourceEnvelopeV1,
)
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from pyproj import CRS
from rasterio.enums import MaskFlags
from rasterio.windows import Window

from ksi_geo_spatial.external_native_window_geometry import (
    NativeWindowError,
    plan_external_native_window,
)
from ksi_geo_spatial.external_native_window_geometry import (
    _stable_pixel_index as _stable_pixel_index,
)

type Bounds = tuple[float, float, float, float]
type PixelWindow = tuple[int, int, int, int]
_CHUNK_BYTES = 1024 * 1024
_PROFILE = "ksi-native-window.v1"
_SUPPORTED_LAYOUTS = {
    "COG_PROFILE_V1",
    "GEOTIFF_TILED_V1",
    "GEOTIFF_STRIPED_V1",
}


@dataclass(frozen=True, slots=True)
class NativeWindowReceiptV1:
    """Private candidate facts; this record is not publication authority."""

    contract_version: str
    preparation_profile: str
    artifact_id: str
    artifact_kind: ProcessingArtifactKind
    source_sha256: str
    source_size_bytes: int
    requested_bounds: Bounds
    requested_crs_digest: str
    actual_bounds: Bounds
    pixel_window: PixelWindow
    width: int
    height: int
    transform: tuple[float, float, float, float, float, float]
    observed_crs_identifier: str
    observed_crs_digest: str
    observed_vertical_reference: ObservedVerticalReferenceV1 | None
    band_count: int
    dtype: str
    nodata_representation: NodataRepresentation
    nodata_value: float | None
    valid_pixel_count: int
    output_sha256: str
    output_size_bytes: int
    accuracy_assessed: bool


@dataclass(frozen=True, slots=True)
class NativeWindowPreparationV1:
    """The private output path and its exact, locally verified receipt."""

    output_path: Path
    receipt: NativeWindowReceiptV1


def prepare_external_native_window(
    *,
    source_path: Path,
    source_observed_sha256: str,
    source_size_bytes: int,
    inspection: ArtifactInspectionOutcomeV1,
    artifact_kind: ProcessingArtifactKind,
    requested_bounds: Bounds,
    requested_crs_digest: str,
    output_path: Path,
    envelope: ResourceEnvelopeV1,
    max_output_pixels: int,
    max_output_bytes: int,
    expected_vertical_reference_digest: str | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> NativeWindowPreparationV1:
    """Write an exact native-pixel DSM/ORTHO window to a new private path.

    The source is copied and hashed into a mode-0700 workspace before GDAL opens
    it, preventing a path substitution during decoding.  No reprojection,
    resampling, clipping, height change, or accuracy assessment is performed.
    """

    deadline = time.monotonic() + min(envelope.max_cpu_seconds, envelope.max_deadline_seconds)
    _check_cancelled(is_cancelled, deadline)
    _validate_arguments(
        source_observed_sha256=source_observed_sha256,
        source_size_bytes=source_size_bytes,
        inspection=inspection,
        artifact_kind=artifact_kind,
        requested_bounds=requested_bounds,
        requested_crs_digest=requested_crs_digest,
        output_path=output_path,
        envelope=envelope,
        max_output_pixels=max_output_pixels,
        max_output_bytes=max_output_bytes,
        expected_vertical_reference_digest=expected_vertical_reference_digest,
    )
    measurements = inspection.measurements
    assert measurements is not None
    _require_private_destination(output_path)

    source = Path(source_path)
    if source.is_symlink():
        raise NativeWindowError("SOURCE_NOT_REGULAR_FILE", "source must not be a symbolic link")
    try:
        source_info = source.stat(follow_symlinks=False)
    except OSError as exc:
        raise NativeWindowError("SOURCE_UNAVAILABLE", "measured source is unavailable") from exc
    if not stat.S_ISREG(source_info.st_mode):
        raise NativeWindowError("SOURCE_NOT_REGULAR_FILE", "source must be a regular file")
    if source_info.st_size != source_size_bytes:
        raise NativeWindowError("SOURCE_BYTES_MISMATCH", "source size differs from its binding")
    if source_size_bytes > min(envelope.max_input_bytes, envelope.max_streamed_bytes):
        raise NativeWindowError(
            "INPUT_BYTE_LIMIT_EXCEEDED", "source exceeds the finite input limit"
        )
    if source_size_bytes > envelope.max_workspace_bytes:
        raise NativeWindowError(
            "WORKSPACE_LIMIT_EXCEEDED", "source exceeds the private workspace limit"
        )

    try:
        private_dir = Path(tempfile.mkdtemp(prefix=".ksi-window-", dir=output_path.parent))
    except OSError as exc:
        raise NativeWindowError(
            "PRIVATE_WORKSPACE_UNAVAILABLE", "private workspace is unavailable"
        ) from exc
    staged_source = private_dir / "sealed-source.tif"
    candidate = private_dir / "candidate.tif"
    published = False
    try:
        actual_source_size, actual_source_digest = _copy_and_hash_source(
            source,
            staged_source,
            envelope=envelope,
            is_cancelled=is_cancelled,
            deadline=deadline,
        )
        if (
            actual_source_size != source_size_bytes
            or actual_source_digest != source_observed_sha256
        ):
            raise NativeWindowError(
                "SOURCE_BYTES_MISMATCH", "source bytes differ from the sealed binding"
            )
        _check_cancelled(is_cancelled, deadline)
        with (
            rasterio.Env(**_gdal_options(envelope)),
            rasterio.open(staged_source, "r", driver="GTiff", sharing=False) as dataset,
        ):
            _verify_source_measurements(
                dataset,
                measurements=measurements,
                artifact_kind=artifact_kind,
                requested_crs_digest=requested_crs_digest,
                expected_vertical_reference_digest=expected_vertical_reference_digest,
            )
            pixel_window, actual_bounds, output_transform = _native_window(
                requested_bounds, measurements
            )
            col_start, col_stop, row_start, row_stop = pixel_window
            output_width = col_stop - col_start
            output_height = row_stop - row_start
            output_pixels = output_width * output_height
            if output_pixels <= 0:
                raise NativeWindowError("EMPTY_PIXEL_WINDOW", "request contains no source pixel")
            if output_pixels > min(max_output_pixels, envelope.max_pixels):
                raise NativeWindowError(
                    "OUTPUT_PIXEL_LIMIT_EXCEEDED",
                    "requested window exceeds the finite pixel limit",
                )
            output_bound = min(max_output_bytes, envelope.max_output_bytes)
            _check_workspace_bound(
                source_size_bytes=source_size_bytes,
                output_pixels=output_pixels,
                bands=dataset.count,
                dtype=dataset.dtypes[0],
                max_output_bytes=output_bound,
                max_workspace_bytes=envelope.max_workspace_bytes,
            )
            valid_pixel_count = _write_native_window(
                dataset,
                candidate,
                artifact_kind=artifact_kind,
                pixel_window=pixel_window,
                output_transform=output_transform,
                measurements=measurements,
                envelope=envelope,
                is_cancelled=is_cancelled,
                deadline=deadline,
            )
        _check_cancelled(is_cancelled, deadline)
        _verify_candidate(
            candidate,
            measurements=measurements,
            artifact_kind=artifact_kind,
            width=output_width,
            height=output_height,
            transform=output_transform,
            expected_valid_pixel_count=valid_pixel_count,
            envelope=envelope,
            is_cancelled=is_cancelled,
            deadline=deadline,
        )
        candidate_size = candidate.stat().st_size
        if candidate_size <= 0 or candidate_size > min(max_output_bytes, envelope.max_output_bytes):
            raise NativeWindowError(
                "OUTPUT_BYTE_LIMIT_EXCEEDED", "candidate exceeds the finite output byte limit"
            )
        candidate_digest = _hash_path(candidate, envelope.max_output_bytes, is_cancelled, deadline)
        _check_cancelled(is_cancelled, deadline)
        os.chmod(candidate, 0o600)
        try:
            os.link(candidate, output_path)
        except FileExistsError as exc:
            raise NativeWindowError(
                "OUTPUT_ALREADY_EXISTS", "private output destination already exists"
            ) from exc
        published = True
        candidate.unlink()
        receipt = NativeWindowReceiptV1(
            contract_version="native-window-receipt.v1",
            preparation_profile=_PROFILE,
            artifact_id=inspection.artifact_id,
            artifact_kind=artifact_kind,
            source_sha256=source_observed_sha256,
            source_size_bytes=source_size_bytes,
            requested_bounds=requested_bounds,
            requested_crs_digest=requested_crs_digest,
            actual_bounds=actual_bounds,
            pixel_window=pixel_window,
            width=output_width,
            height=output_height,
            transform=output_transform,
            observed_crs_identifier=measurements.observed_crs_identifier,
            observed_crs_digest=measurements.observed_crs_digest,
            observed_vertical_reference=measurements.observed_vertical_reference,
            band_count=measurements.band_count,
            dtype=measurements.dtype,
            nodata_representation=measurements.nodata_representation,
            nodata_value=measurements.nodata_value,
            valid_pixel_count=valid_pixel_count,
            output_sha256=candidate_digest,
            output_size_bytes=candidate_size,
            accuracy_assessed=False,
        )
        return NativeWindowPreparationV1(output_path=output_path, receipt=receipt)
    except NativeWindowError:
        if published:
            _unlink_regular_file(output_path)
        raise
    except Exception as exc:
        if published:
            _unlink_regular_file(output_path)
        raise NativeWindowError(
            "RASTER_PREPARATION_FAILED", "measured raster window could not be prepared"
        ) from exc
    finally:
        try:
            shutil.rmtree(private_dir)
        except OSError as exc:
            if published:
                _unlink_regular_file(output_path)
            raise NativeWindowError(
                "PRIVATE_WORKSPACE_CLEANUP_FAILED",
                "native window staging workspace could not be removed",
            ) from exc


def _validate_arguments(
    *,
    source_observed_sha256: str,
    source_size_bytes: int,
    inspection: ArtifactInspectionOutcomeV1,
    artifact_kind: ProcessingArtifactKind,
    requested_bounds: Bounds,
    requested_crs_digest: str,
    output_path: Path,
    envelope: ResourceEnvelopeV1,
    max_output_pixels: int,
    max_output_bytes: int,
    expected_vertical_reference_digest: str | None,
) -> None:
    if artifact_kind not in {ProcessingArtifactKind.DSM, ProcessingArtifactKind.ORTHO}:
        raise NativeWindowError(
            "UNSUPPORTED_ARTIFACT_KIND", "only measured DSM and ORTHO are supported"
        )
    if inspection.outcome is not ArtifactOutcome.MEASURED or inspection.measurements is None:
        raise NativeWindowError(
            "SOURCE_NOT_MEASURED", "source must have a measured inspection outcome"
        )
    if inspection.observed_sha256 != source_observed_sha256:
        raise NativeWindowError(
            "SOURCE_BYTES_MISMATCH", "inspection does not bind the supplied source digest"
        )
    if len(requested_bounds) != 4 or not all(math.isfinite(value) for value in requested_bounds):
        raise NativeWindowError(
            "INVALID_REQUEST_BOUNDS", "request bounds must be four finite values"
        )
    xmin, ymin, xmax, ymax = requested_bounds
    if xmin >= xmax or ymin >= ymax:
        raise NativeWindowError(
            "INVALID_REQUEST_BOUNDS", "request bounds must have positive width and height"
        )
    if source_size_bytes <= 0 or max_output_pixels <= 0 or max_output_bytes <= 0:
        raise NativeWindowError(
            "INVALID_RESOURCE_LIMIT", "source and output limits must be positive"
        )
    if output_path.exists():
        raise NativeWindowError(
            "OUTPUT_ALREADY_EXISTS", "private output destination already exists"
        )
    measurements = inspection.measurements
    if measurements.layout not in _SUPPORTED_LAYOUTS:
        raise NativeWindowError(
            "UNSUPPORTED_SOURCE_PROFILE", "source layout is outside the measured GeoTIFF profile"
        )
    if artifact_kind is ProcessingArtifactKind.DSM and (
        measurements.band_count != 1 or measurements.dtype not in {"float32", "float64"}
    ):
        raise NativeWindowError("UNSUPPORTED_SOURCE_PROFILE", "DSM must be a single float band")
    if artifact_kind is ProcessingArtifactKind.ORTHO and (
        measurements.band_count not in {3, 4}
        or measurements.dtype != "uint8"
        or measurements.nodata_representation
        not in {NodataRepresentation.NONE, NodataRepresentation.MASK}
        or measurements.nodata_value is not None
    ):
        raise NativeWindowError("UNSUPPORTED_SOURCE_PROFILE", "ORTHO must be RGB or RGBA uint8")
    if measurements.width * measurements.height > envelope.max_pixels:
        raise NativeWindowError(
            "INPUT_PIXEL_LIMIT_EXCEEDED", "measured source exceeds the finite pixel limit"
        )
    if measurements.band_count > envelope.max_bands:
        raise NativeWindowError(
            "INPUT_BAND_LIMIT_EXCEEDED", "measured source exceeds the finite band limit"
        )
    if measurements.observed_crs_digest != requested_crs_digest:
        raise NativeWindowError(
            "CRS_MISMATCH", "requested CRS digest differs from the measured source CRS"
        )
    observed_vertical_digest = (
        None
        if measurements.observed_vertical_reference is None
        else measurements.observed_vertical_reference.canonical_digest()
    )
    if (
        expected_vertical_reference_digest is not None
        and expected_vertical_reference_digest != observed_vertical_digest
    ):
        raise NativeWindowError(
            "VERTICAL_REFERENCE_MISMATCH",
            "requested vertical reference differs from the measured source",
        )


def _require_private_destination(output_path: Path) -> None:
    parent = output_path.parent
    if not parent.is_dir():
        raise NativeWindowError(
            "PRIVATE_WORKSPACE_UNAVAILABLE", "output parent directory must exist"
        )
    try:
        mode = stat.S_IMODE(parent.stat().st_mode)
    except OSError as exc:
        raise NativeWindowError(
            "PRIVATE_WORKSPACE_UNAVAILABLE", "output parent is unavailable"
        ) from exc
    if mode & 0o077:
        raise NativeWindowError(
            "OUTPUT_NOT_PRIVATE", "output parent directory must be private to its owner"
        )


def _copy_and_hash_source(
    source: Path,
    destination: Path,
    *,
    envelope: ResourceEnvelopeV1,
    is_cancelled: Callable[[], bool] | None,
    deadline: float,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(source, flags)
    except OSError as exc:
        raise NativeWindowError(
            "SOURCE_UNAVAILABLE", "measured source could not be opened safely"
        ) from exc
    try:
        with (
            os.fdopen(source_fd, "rb", closefd=False) as source_file,
            destination.open("xb") as output_file,
        ):
            source_info = os.fstat(source_fd)
            if not stat.S_ISREG(source_info.st_mode):
                raise NativeWindowError("SOURCE_NOT_REGULAR_FILE", "source must be a regular file")
            while True:
                _check_cancelled(is_cancelled, deadline)
                chunk = source_file.read(_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > min(envelope.max_input_bytes, envelope.max_streamed_bytes):
                    raise NativeWindowError(
                        "INPUT_BYTE_LIMIT_EXCEEDED",
                        "streamed source exceeds the finite input limit",
                    )
                if total > envelope.max_workspace_bytes:
                    raise NativeWindowError(
                        "WORKSPACE_LIMIT_EXCEEDED", "source exceeds the private workspace limit"
                    )
                digest.update(chunk)
                output_file.write(chunk)
            output_file.flush()
            os.fsync(output_file.fileno())
            if total != source_info.st_size:
                raise NativeWindowError(
                    "SOURCE_BYTES_MISMATCH", "source changed while it was staged"
                )
    finally:
        os.close(source_fd)
    return total, "sha256:" + digest.hexdigest()


def _verify_source_measurements(
    dataset: rasterio.io.DatasetReader,
    *,
    measurements: RasterMeasurementsV1,
    artifact_kind: ProcessingArtifactKind,
    requested_crs_digest: str,
    expected_vertical_reference_digest: str | None,
) -> None:
    if dataset.driver != "GTiff" or dataset.subdatasets:
        raise NativeWindowError(
            "UNSUPPORTED_SOURCE_PROFILE", "source must be a single local GeoTIFF dataset"
        )
    if (dataset.width, dataset.height, dataset.count) != (
        measurements.width,
        measurements.height,
        measurements.band_count,
    ):
        raise NativeWindowError(
            "SOURCE_MEASUREMENTS_MISMATCH", "raster dimensions differ from inspection"
        )
    if tuple(dataset.dtypes) != (measurements.dtype,) * measurements.band_count:
        raise NativeWindowError(
            "SOURCE_MEASUREMENTS_MISMATCH", "raster dtype differs from inspection"
        )
    observed_transform = (
        float(dataset.transform.a),
        float(dataset.transform.b),
        float(dataset.transform.c),
        float(dataset.transform.d),
        float(dataset.transform.e),
        float(dataset.transform.f),
    )
    if observed_transform != measurements.transform:
        raise NativeWindowError(
            "SOURCE_MEASUREMENTS_MISMATCH", "raster transform differs from inspection"
        )
    footprint = _footprint_wkt(observed_transform, dataset.width, dataset.height)
    footprint_digest = "sha256:" + hashlib.sha256(footprint.encode("utf-8")).hexdigest()
    if footprint != measurements.footprint_wkt or footprint_digest != measurements.footprint_digest:
        raise NativeWindowError(
            "SOURCE_MEASUREMENTS_MISMATCH", "raster footprint differs from inspection"
        )
    if dataset.crs is None:
        raise NativeWindowError("SOURCE_MEASUREMENTS_MISMATCH", "measured raster CRS is absent")
    try:
        embedded = CRS.from_user_input(dataset.crs.to_wkt())
        horizontal = embedded
        if embedded.is_compound:
            horizontal_components = [
                component
                for component in embedded.sub_crs_list
                if component.is_projected or component.is_geographic
            ]
            if len(horizontal_components) != 1:
                raise ValueError("compound CRS horizontal component is ambiguous")
            horizontal = horizontal_components[0]
        epsg = horizontal.to_epsg()
        if epsg is None:
            raise ValueError("horizontal CRS has no EPSG identity")
        canonical_wkt = CRS.from_epsg(epsg).to_wkt(
            version="WKT2_2019", pretty=False, output_axis_rule=True
        )
        vertical_components = [
            component for component in embedded.sub_crs_list if component.is_vertical
        ]
        if embedded.is_compound:
            if len(vertical_components) != 1:
                raise ValueError("compound CRS vertical component is ambiguous")
            vertical_component = vertical_components[0]
            vertical_code = vertical_component.to_epsg()
            if (
                vertical_code is None
                or len(vertical_component.axis_info) != 1
                or vertical_component.axis_info[0].unit_name.lower() not in {"metre", "meter"}
            ):
                raise ValueError("vertical CRS is outside the measured raster profile")
            actual_vertical = ObservedVerticalReferenceV1(
                identifier=f"EPSG:{vertical_code}", basis=vertical_component.name
            )
        else:
            actual_vertical = None
    except Exception as exc:
        raise NativeWindowError(
            "SOURCE_MEASUREMENTS_MISMATCH", "raster CRS cannot be verified"
        ) from exc
    crs_digest = "sha256:" + hashlib.sha256(canonical_wkt.encode("utf-8")).hexdigest()
    if crs_digest != requested_crs_digest or crs_digest != measurements.observed_crs_digest:
        raise NativeWindowError(
            "CRS_MISMATCH", "raster CRS digest differs from the measured source"
        )
    if measurements.observed_crs_wkt is not None and canonical_wkt != measurements.observed_crs_wkt:
        raise NativeWindowError(
            "SOURCE_MEASUREMENTS_MISMATCH", "canonical raster CRS differs from inspection"
        )
    if actual_vertical != measurements.observed_vertical_reference:
        raise NativeWindowError(
            "VERTICAL_REFERENCE_MISMATCH", "raster vertical CRS differs from inspection"
        )
    actual_nodata = dataset.nodata
    if measurements.nodata_representation is NodataRepresentation.NAN:
        nodata_matches = actual_nodata is not None and math.isnan(float(actual_nodata))
    elif measurements.nodata_value is None:
        nodata_matches = actual_nodata is None
    else:
        nodata_matches = actual_nodata == measurements.nodata_value
    if not nodata_matches:
        raise NativeWindowError(
            "SOURCE_MEASUREMENTS_MISMATCH", "raster NoData differs from inspection"
        )
    first_band_flags = set(dataset.mask_flag_enums[0])
    has_nodata_mask = MaskFlags.nodata in first_band_flags
    has_internal_mask = MaskFlags.per_dataset in first_band_flags
    has_alpha_mask = MaskFlags.alpha in first_band_flags
    if artifact_kind is ProcessingArtifactKind.DSM:
        expected_mask = measurements.nodata_representation is NodataRepresentation.MASK
        expected_nodata_mask = measurements.nodata_representation in {
            NodataRepresentation.FINITE,
            NodataRepresentation.NAN,
        }
        if (
            has_internal_mask != expected_mask
            or has_nodata_mask != expected_nodata_mask
            or has_alpha_mask
        ):
            raise NativeWindowError(
                "SOURCE_MEASUREMENTS_MISMATCH", "DSM mask/NoData facts differ from inspection"
            )
    elif dataset.count == 4:
        # GDAL reports per_dataset ALONGSIDE alpha when the base bands share
        # the alpha band as their mask; that shared-alpha per_dataset flag is
        # not a separate internal mask. A true internal mask supersedes alpha
        # (base bands report per_dataset WITHOUT alpha) and stays refused by
        # the missing-alpha check below, matching the inspector's structural
        # mask-IFD rule that keeps the two compositions mutually exclusive.
        has_separate_internal_mask = has_internal_mask and not has_alpha_mask
        if (
            not has_alpha_mask
            or has_separate_internal_mask
            or measurements.nodata_representation is not NodataRepresentation.MASK
        ):
            raise NativeWindowError(
                "SOURCE_MEASUREMENTS_MISMATCH", "RGBA alpha mask facts differ from inspection"
            )
    elif (
        has_internal_mask != (measurements.nodata_representation is NodataRepresentation.MASK)
        or has_alpha_mask
        or has_nodata_mask
    ):
        raise NativeWindowError(
            "SOURCE_MEASUREMENTS_MISMATCH", "RGB mask facts differ from inspection"
        )
    if artifact_kind is ProcessingArtifactKind.DSM and (
        not horizontal.is_projected
        or any(axis.unit_name.lower() not in {"metre", "meter"} for axis in horizontal.axis_info)
    ):
        raise NativeWindowError(
            "UNSUPPORTED_SOURCE_PROFILE", "DSM CRS must use projected metre axes"
        )
    observed_vertical_digest = (
        None
        if measurements.observed_vertical_reference is None
        else measurements.observed_vertical_reference.canonical_digest()
    )
    if (
        expected_vertical_reference_digest is not None
        and expected_vertical_reference_digest != observed_vertical_digest
    ):
        raise NativeWindowError(
            "VERTICAL_REFERENCE_MISMATCH", "vertical reference differs from the request"
        )


def _native_window(
    request: Bounds, measurements: RasterMeasurementsV1
) -> tuple[PixelWindow, Bounds, tuple[float, float, float, float, float, float]]:
    geometry = plan_external_native_window(
        requested_bounds=request,
        measurements=measurements,
        requested_crs_digest=measurements.observed_crs_digest,
    )
    return geometry.pixel_window, geometry.actual_bounds, geometry.transform


def _check_workspace_bound(
    *,
    source_size_bytes: int,
    output_pixels: int,
    bands: int,
    dtype: str,
    max_output_bytes: int,
    max_workspace_bytes: int,
) -> None:
    item_size = np.dtype(dtype).itemsize
    estimated_output = output_pixels * (bands * item_size + 1) + 65_536
    if estimated_output > max_output_bytes:
        raise NativeWindowError(
            "OUTPUT_BYTE_LIMIT_EXCEEDED", "estimated candidate exceeds the finite byte limit"
        )
    if source_size_bytes + estimated_output > max_workspace_bytes:
        raise NativeWindowError(
            "WORKSPACE_LIMIT_EXCEEDED", "candidate and staged source exceed workspace limit"
        )


def _write_native_window(
    source: rasterio.io.DatasetReader,
    destination: Path,
    *,
    artifact_kind: ProcessingArtifactKind,
    pixel_window: PixelWindow,
    output_transform: tuple[float, ...],
    measurements: RasterMeasurementsV1,
    envelope: ResourceEnvelopeV1,
    is_cancelled: Callable[[], bool] | None,
    deadline: float,
) -> int:
    col_start, col_stop, row_start, row_stop = pixel_window
    width, height = col_stop - col_start, row_stop - row_start
    item_size = np.dtype(measurements.dtype).itemsize
    row_bytes = width * (source.count * item_size + 1)
    sample_budget = min(envelope.max_sample_bytes, max(1, envelope.max_memory_bytes // 2))
    if row_bytes > sample_budget:
        raise NativeWindowError(
            "SAMPLE_MEMORY_LIMIT_EXCEEDED", "one output row exceeds the finite sample budget"
        )
    rows_per_chunk = max(1, sample_budget // row_bytes)
    decoded_bytes = 0
    valid_pixels = 0
    affine = Affine(*output_transform[:6])
    profile: dict[str, object] = {
        "driver": "GTiff",
        "width": width,
        "height": height,
        "count": source.count,
        "dtype": measurements.dtype,
        "crs": source.crs,
        "transform": affine,
        "compress": "DEFLATE",
        "interleave": "pixel",
        "BIGTIFF": "IF_SAFER",
    }
    if measurements.nodata_representation is NodataRepresentation.NAN:
        profile["nodata"] = float("nan")
    elif measurements.nodata_value is not None:
        profile["nodata"] = measurements.nodata_value
    if width >= 16 and height >= 16:
        profile.update(tiled=True, blockxsize=256, blockysize=256)
    if measurements.dtype in {"float32", "float64"}:
        profile["predictor"] = 3
    elif measurements.dtype in {"uint8", "uint16", "int16"}:
        profile["predictor"] = 2
    try:
        with (
            rasterio.Env(**_gdal_options(envelope, internal_mask=True)),
            rasterio.open(destination, "w", **profile) as target,
        ):
            if artifact_kind is ProcessingArtifactKind.ORTHO:
                target.colorinterp = source.colorinterp
            for row in range(row_start, row_stop, rows_per_chunk):
                _check_cancelled(is_cancelled, deadline)
                count = min(rows_per_chunk, row_stop - row)
                source_window = Window(col_start, row, width, count)
                values = source.read(window=source_window)
                masks = source.dataset_mask(window=source_window)
                decoded_bytes += values.nbytes + masks.nbytes
                if decoded_bytes > envelope.max_decompressed_bytes:
                    raise NativeWindowError(
                        "DECOMPRESSED_BYTE_LIMIT_EXCEEDED",
                        "window decode exceeds finite byte limit",
                    )
                if artifact_kind is ProcessingArtifactKind.DSM:
                    invalid = masks != 255
                    if measurements.nodata_representation is NodataRepresentation.MASK:
                        target.write_mask(
                            np.where(invalid, 0, 255).astype("uint8"),
                            window=Window(0, row - row_start, width, count),
                        )
                    valid = ~invalid
                    if not np.all(np.isfinite(values[0][valid])):
                        raise NativeWindowError(
                            "INVALID_SOURCE_SAMPLE", "unmasked DSM sample is non-finite"
                        )
                else:
                    valid = masks == 255
                    if source.count == 4 and not np.all((values[3] == 0) | (values[3] == 255)):
                        raise NativeWindowError(
                            "INVALID_SOURCE_MASK", "ORTHO alpha mask is not binary"
                        )
                    if (
                        source.count == 3
                        and measurements.nodata_representation is NodataRepresentation.MASK
                    ):
                        target.write_mask(
                            np.where(valid, 255, 0).astype("uint8"),
                            window=Window(0, row - row_start, width, count),
                        )
                valid_pixels += int(np.count_nonzero(valid))
                target.write(values, window=Window(0, row - row_start, width, count))
        if valid_pixels == 0:
            raise NativeWindowError(
                "EMPTY_VALID_WINDOW", "requested window contains no valid source pixels"
            )
    except NativeWindowError:
        raise
    except Exception as exc:
        raise NativeWindowError(
            "RASTER_WRITE_FAILED", "private GeoTIFF candidate could not be written"
        ) from exc
    return valid_pixels


def _verify_candidate(
    path: Path,
    *,
    measurements: RasterMeasurementsV1,
    artifact_kind: ProcessingArtifactKind,
    width: int,
    height: int,
    transform: tuple[float, ...],
    expected_valid_pixel_count: int,
    envelope: ResourceEnvelopeV1,
    is_cancelled: Callable[[], bool] | None,
    deadline: float,
) -> None:
    """Reopen the closed candidate and verify bounded geometry and mask facts."""

    try:
        with (
            rasterio.Env(**_gdal_options(envelope)),
            rasterio.open(path, "r", driver="GTiff", sharing=False) as dataset,
        ):
            if dataset.driver != "GTiff" or dataset.subdatasets:
                raise NativeWindowError(
                    "OUTPUT_VERIFICATION_FAILED", "candidate is not one GeoTIFF dataset"
                )
            if (dataset.width, dataset.height, dataset.count) != (
                width,
                height,
                measurements.band_count,
            ):
                raise NativeWindowError(
                    "OUTPUT_VERIFICATION_FAILED", "candidate dimensions differ from the request"
                )
            actual_transform = (
                float(dataset.transform.a),
                float(dataset.transform.b),
                float(dataset.transform.c),
                float(dataset.transform.d),
                float(dataset.transform.e),
                float(dataset.transform.f),
            )
            if actual_transform != transform:
                raise NativeWindowError(
                    "OUTPUT_VERIFICATION_FAILED", "candidate transform differs from the request"
                )
            if dataset.crs is None:
                raise NativeWindowError("OUTPUT_VERIFICATION_FAILED", "candidate CRS is absent")
            crs = CRS.from_user_input(dataset.crs.to_wkt())
            horizontal = crs
            if crs.is_compound:
                horizontal = next(
                    component
                    for component in crs.sub_crs_list
                    if component.is_projected or component.is_geographic
                )
            epsg = horizontal.to_epsg()
            if epsg is None or f"EPSG:{epsg}" != measurements.observed_crs_identifier:
                raise NativeWindowError(
                    "OUTPUT_VERIFICATION_FAILED", "candidate horizontal CRS changed"
                )
            if tuple(dataset.dtypes) != (measurements.dtype,) * measurements.band_count:
                raise NativeWindowError("OUTPUT_VERIFICATION_FAILED", "candidate dtype changed")
            if measurements.nodata_representation is NodataRepresentation.NAN:
                nodata_matches = dataset.nodata is not None and math.isnan(float(dataset.nodata))
            elif measurements.nodata_value is None:
                nodata_matches = dataset.nodata is None
            else:
                nodata_matches = dataset.nodata == measurements.nodata_value
            if not nodata_matches:
                raise NativeWindowError("OUTPUT_VERIFICATION_FAILED", "candidate NoData changed")
            if artifact_kind is ProcessingArtifactKind.ORTHO and dataset.colorinterp != (
                rasterio.enums.ColorInterp.red,
                rasterio.enums.ColorInterp.green,
                rasterio.enums.ColorInterp.blue,
                *((rasterio.enums.ColorInterp.alpha,) if measurements.band_count == 4 else ()),
            ):
                raise NativeWindowError(
                    "OUTPUT_VERIFICATION_FAILED", "candidate image channel meanings changed"
                )
            valid = 0
            verify_row_bytes = width * (
                np.dtype(measurements.dtype).itemsize + 1
                if artifact_kind is ProcessingArtifactKind.DSM
                and measurements.nodata_representation is NodataRepresentation.NONE
                else 1
            )
            if verify_row_bytes > envelope.max_sample_bytes:
                raise NativeWindowError(
                    "SAMPLE_MEMORY_LIMIT_EXCEEDED",
                    "one output verification row exceeds the finite sample budget",
                )
            verify_rows_per_chunk = max(1, envelope.max_sample_bytes // verify_row_bytes)
            for row in range(0, height, verify_rows_per_chunk):
                _check_cancelled(is_cancelled, deadline)
                count = min(verify_rows_per_chunk, height - row)
                if (
                    artifact_kind is ProcessingArtifactKind.DSM
                    and measurements.nodata_representation is NodataRepresentation.NONE
                ):
                    data = dataset.read(1, window=Window(0, row, width, count))
                    mask = np.isfinite(data)
                else:
                    mask = dataset.dataset_mask(window=Window(0, row, width, count)) == 255
                valid += int(np.count_nonzero(mask))
            if valid != expected_valid_pixel_count:
                raise NativeWindowError(
                    "OUTPUT_VERIFICATION_FAILED", "candidate valid-pixel coverage changed"
                )
    except NativeWindowError:
        raise
    except Exception as exc:
        raise NativeWindowError(
            "OUTPUT_VERIFICATION_FAILED", "candidate metadata could not be verified"
        ) from exc


def _hash_path(
    path: Path,
    max_bytes: int,
    is_cancelled: Callable[[], bool] | None,
    deadline: float,
) -> str:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as source:
        while True:
            _check_cancelled(is_cancelled, deadline)
            chunk = source.read(_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise NativeWindowError(
                    "OUTPUT_BYTE_LIMIT_EXCEEDED", "candidate exceeds the finite output byte limit"
                )
            digest.update(chunk)
    if total <= 0:
        raise NativeWindowError("EMPTY_OUTPUT", "candidate output is empty")
    return "sha256:" + digest.hexdigest()


def _footprint_wkt(transform: tuple[float, ...], width: int, height: int) -> str:
    a, b, c, d, e, f = transform
    corners = ((0, 0), (width, 0), (width, height), (0, height), (0, 0))
    points: list[str] = []
    for column, row in corners:
        x = a * column + b * row + c
        y = d * column + e * row + f
        if not math.isfinite(x) or not math.isfinite(y):
            raise NativeWindowError("INVALID_SOURCE_GEOMETRY", "source footprint is non-finite")
        points.append(f"{_format_coordinate(x)} {_format_coordinate(y)}")
    return "POLYGON ((" + ", ".join(points) + "))"


def _format_coordinate(value: float) -> str:
    return "0" if value == 0.0 else format(value, ".17g")


def _check_cancelled(
    is_cancelled: Callable[[], bool] | None, deadline: float | None = None
) -> None:
    if is_cancelled is not None and is_cancelled():
        raise NativeWindowError("CANCELLED", "native window preparation was cancelled")
    if deadline is not None and time.monotonic() > deadline:
        raise NativeWindowError("DEADLINE_EXCEEDED", "native window exceeded its finite time limit")


def _gdal_options(
    envelope: ResourceEnvelopeV1,
    *,
    internal_mask: bool = False,
) -> dict[str, str | int]:
    options: dict[str, str | int] = {
        "PROJ_NETWORK": "OFF",
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_PAM_ENABLED": "NO",
        "GDAL_DRIVER_PATH": "disable",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": "",
        "GDAL_VRT_ENABLE_PYTHON": "NO",
        "GDAL_NUM_THREADS": "1",
        "GDAL_CACHEMAX": max(1, min(16, envelope.max_memory_bytes // (1024 * 1024))),
    }
    if internal_mask:
        options["GDAL_TIFF_INTERNAL_MASK"] = "YES"
    return options


def _unlink_regular_file(path: Path) -> None:
    try:
        if path.is_file() and not path.is_symlink():
            path.unlink()
    except OSError:
        pass


__all__ = [
    "NativeWindowError",
    "NativeWindowPreparationV1",
    "NativeWindowReceiptV1",
    "prepare_external_native_window",
]
