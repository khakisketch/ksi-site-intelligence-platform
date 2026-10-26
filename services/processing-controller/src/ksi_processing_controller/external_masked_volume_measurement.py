"""Contained V3 masked-volume measurement over owned DSM + mask bytes.

A callable worker primitive inside a separately verified contained runtime,
not a mount, route, or worker-activation default. The uint8 mask TIFF profile
is new: it requires its own separately verified containment and its own
bounded structural preflight
(:func:`parse_sealed_binary_mask_tiff_structure`). Nothing here claims the
already-approved DSM profile implicitly covers mask bytes; source-helper
checks below establish byte-identity and grid conformance only and must never
be read as an OS sandbox claim.

The primitive binds the actual diff full-baseline shape/affine/CRS to a sealed
``MaskedCalculationIdentityV3``, binds actual mask observed bytes (sha/size)
and grid metadata to the sealed mask binding, enforces uint8 single-band
NO_NODATA binary values with resource caps before allocation/parse, performs
no source mutation or resampling, and returns the new V3 contract plus the
actual cropped ``delta_grid_m`` for the downstream private writer (never
URLs). Generated local TIFF tests only.

Two entry points share one core:

- :func:`measure_masked_volume_v3_from_diff` — arrays already held inside
  containment (e.g. decoded from owned snapshots by this module or by
  tests driving the pure math). There is no ``is_trusted``/``userDeclared``
  boolean; every grid/CRS/identity/resource/currentness check still runs.
  Scalar, missing, or misshaped ``diff`` fields fail closed with a typed
  failure reason instead of escaping as ``AttributeError``/``IndexError``.
- :func:`measure_masked_volume_v3` — file-backed primitive that snapshots
  baseline/current/mask bytes into unlinked private descriptors, verifies
  sha/size, runs the bounded binary-mask structural preflight BEFORE any
  GDAL open, decodes, then delegates to the array core.
"""

from __future__ import annotations

import base64
import hashlib
import math
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from ksi_change_detection.dsm_diff import DiffResult
from ksi_change_detection.external_masked_volume import (
    MaskedExternalVolumeError,
    measure_masked_external_volume_zone,
)
from ksi_event_contracts.external_artifact_validation import ResourceEnvelopeV1
from ksi_event_contracts.external_masked_volume import (
    ExclusionMaskBindingV1,
    MaskedCalculationIdentityV3,
)
from ksi_event_contracts.external_masked_volume_result import (
    MaskedCoverageWitnessV3,
    MaskedVolumeCalculationFailureV3,
    MaskedVolumeCalculationReportV3,
    MaskedVolumeImpactV3,
    MaskedVolumeNumericResultV3,
)
from ksi_event_contracts.external_relative_volume_calculation import RelativeVolumeMetricsV2
from ksi_geo_spatial.crs import assert_same_crs, assert_supported_project_crs, normalise_crs
from rasterio.transform import Affine

from ksi_processing_controller.external_measurement_algorithms import (
    MeasurementAlgorithmError,
    MeasurementAlgorithmIncomplete,
    MeasurementWatchdogV2,
    OwnedSecondaryV2,
    align_masked_dsm_difference,
    inspect_owned_secondary_dsm,
    maximum_fixed_profile_zone_grid_cells,
    preflight_owned_secondary_dsm_memory,
    preflight_volume_measurement_memory,
)
from ksi_processing_controller.external_tiff_structure import (
    TiffResourceLimitError,
    TiffStructureError,
    parse_sealed_binary_mask_tiff_structure,
)

_READ_CHUNK_BYTES = 1024 * 1024
_MASK_BYTES_PER_PIXEL = 4
_MASK_WORKING_BYTES = 2 * _READ_CHUNK_BYTES
_MASK_STRUCTURE_DIRECTORY_OBJECT_BYTES = 4 * 1024
_MASK_STRUCTURE_ENTRY_OBJECT_BYTES = 128


class MaskedVolumeMeasurementError(RuntimeError):
    """Fail-closed masked measurement; carries the typed failure reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class MaskedVolumeMeasuredV3:
    """Success: sealed V3 report plus the actual cropped delta grid (NaN outside common)."""

    report: MaskedVolumeCalculationReportV3
    delta_grid_m: np.ndarray[Any, Any]
    row_offset: int
    column_offset: int


def _failure(
    *,
    masked_identity_digest: str,
    report_id: str,
    reason: str,
    failed_at: datetime,
) -> MaskedVolumeCalculationFailureV3:
    failure_id = "failure-" + hashlib.sha256(report_id.encode("utf-8")).hexdigest()[:32]
    return MaskedVolumeCalculationFailureV3(
        failure_id=failure_id,
        masked_calculation_identity_digest=masked_identity_digest,
        reason_code=reason,
        failed_at=failed_at,
    ).sealed()


def _identity_digest(identity: MaskedCalculationIdentityV3) -> str:
    digest = identity.masked_calculation_identity_digest
    if digest is None or digest != identity.canonical_digest():
        raise MaskedVolumeMeasurementError("MASKED_IDENTITY_MISMATCH")
    return digest


def _require_sealed_envelope(envelope: object) -> ResourceEnvelopeV1:
    if not isinstance(envelope, ResourceEnvelopeV1):
        raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")
    if (
        envelope.resource_envelope_digest is None
        or envelope.resource_envelope_digest != envelope.canonical_digest()
    ):
        raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")
    return envelope


def _require_watchdog(watchdog: object) -> MeasurementWatchdogV2:
    if not isinstance(watchdog, MeasurementWatchdogV2):
        raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")
    if isinstance(watchdog, bool):
        raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")
    return watchdog


def _require_timestamps(
    *, computed_at: datetime, reported_at: datetime, lease_expires_at: datetime
) -> None:
    for _label, value in (
        ("computedAt", computed_at),
        ("reportedAt", reported_at),
        ("leaseExpiresAt", lease_expires_at),
    ):
        if not isinstance(value, datetime):
            raise MaskedVolumeMeasurementError("STALE_LEASE")
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
            raise MaskedVolumeMeasurementError("STALE_LEASE")
    if computed_at > reported_at or reported_at > lease_expires_at:
        raise MaskedVolumeMeasurementError("STALE_LEASE")


def _require_diff_arrays(
    diff: object,
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], Affine, str, float]:
    """Prove diff field types and shapes before any array indexing.

    Scalar, missing, single-dimensional, or mistyped fields fail closed with a
    typed reason instead of escaping as ``AttributeError``/``IndexError``.
    """
    if not isinstance(diff, DiffResult):
        raise MaskedVolumeMeasurementError("MASKED_INPUT_MISMATCH")
    try:
        diff_m = diff.diff_m
        valid = diff.valid
        transform = diff.transform
        diff_crs = diff.crs
        cell_area = diff.cell_area_m2
    except AttributeError as exc:
        raise MaskedVolumeMeasurementError("MASKED_INPUT_MISMATCH") from exc
    if (
        not isinstance(diff_m, np.ndarray)
        or not isinstance(valid, np.ndarray)
        or diff_m.ndim != 2
        or valid.ndim != 2
        or diff_m.shape != valid.shape
        or diff_m.shape[0] <= 0
        or diff_m.shape[1] <= 0
    ):
        raise MaskedVolumeMeasurementError("MASKED_INPUT_MISMATCH")
    if diff_m.dtype != np.dtype(np.float64) or valid.dtype != np.dtype(np.bool_):
        raise MaskedVolumeMeasurementError("MASKED_INPUT_MISMATCH")
    if not isinstance(transform, Affine):
        raise MaskedVolumeMeasurementError("MASKED_INPUT_MISMATCH")
    if not isinstance(diff_crs, str) or not diff_crs.strip():
        raise MaskedVolumeMeasurementError("MASKED_INPUT_MISMATCH")
    if isinstance(cell_area, bool) or not isinstance(cell_area, (int, float)):
        raise MaskedVolumeMeasurementError("MASKED_INPUT_MISMATCH")
    cell_area_m2 = float(cell_area)
    if not math.isfinite(cell_area_m2) or cell_area_m2 <= 0.0:
        raise MaskedVolumeMeasurementError("MASKED_INPUT_MISMATCH")
    return diff_m, valid, transform, diff_crs, cell_area_m2


def _require_masked_identity(identity: object) -> MaskedCalculationIdentityV3:
    """Revalidate the caller's identity without letting shape errors escape untyped."""
    try:
        assert isinstance(identity, MaskedCalculationIdentityV3)
        validated = MaskedCalculationIdentityV3.model_validate(identity.model_dump())
    except (AssertionError, AttributeError, TypeError, ValueError) as exc:
        raise MaskedVolumeMeasurementError("MASKED_IDENTITY_MISMATCH") from exc
    return validated


def _pack_mask(mask: np.ndarray[Any, Any]) -> str:
    packed = np.packbits(mask.reshape(-1), bitorder="big").tobytes()
    return base64.b64encode(packed).decode("ascii")
    packed = np.packbits(mask.reshape(-1), bitorder="big").tobytes()
    return base64.b64encode(packed).decode("ascii")


def _mask_failure_reason(reason: str) -> str:
    mapping = {
        "INVALID_INPUT": "MASKED_INPUT_MISMATCH",
        "INVALID_ZONE": "MASKED_ZONE_MISMATCH",
        "EMPTY_ZONE": "MASKED_EMPTY_ZONE",
        "ALL_MASKED": "MASKED_ALL_EXCLUDED",
        "OVERSIZED_ZONE": "RESOURCE_LIMIT_EXCEEDED",
        "EMPTY_COMMON_VALID_COVERAGE": "MASKED_EMPTY_COMMON_VALID",
        "INSUFFICIENT_COMMON_VALID_COVERAGE": "MASKED_INSUFFICIENT_COMMON_VALID",
    }
    return mapping.get(reason, "MASKED_INPUT_MISMATCH")


@contextmanager
def _owned_snapshot(
    path: Path,
    *,
    expected_size_bytes: int,
    expected_sha256: str,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
    mismatch_reason: str,
) -> Iterator[OwnedSecondaryV2]:
    """Copy a trusted regular source once into an unlinked private descriptor."""
    if expected_size_bytes <= 0 or expected_size_bytes > min(
        envelope.max_input_bytes, envelope.max_streamed_bytes
    ):
        raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        source_fd = os.open(path, flags)
    except OSError as exc:
        raise MaskedVolumeMeasurementError(mismatch_reason) from exc
    try:
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size != expected_size_bytes:
            raise MaskedVolumeMeasurementError(mismatch_reason)
        with tempfile.TemporaryFile(mode="w+b") as snapshot:
            digest = hashlib.sha256()
            copied = 0
            while copied < expected_size_bytes:
                watchdog.check()
                try:
                    chunk = os.read(source_fd, min(_READ_CHUNK_BYTES, expected_size_bytes - copied))
                except OSError as exc:
                    raise MaskedVolumeMeasurementError(mismatch_reason) from exc
                if not chunk:
                    raise MaskedVolumeMeasurementError(mismatch_reason)
                snapshot.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
            try:
                if os.read(source_fd, 1):
                    raise MaskedVolumeMeasurementError(mismatch_reason)
            except OSError as exc:
                raise MaskedVolumeMeasurementError(mismatch_reason) from exc
            actual_sha256 = "sha256:" + digest.hexdigest()
            snapshot.flush()
            snapshot_stat = os.fstat(snapshot.fileno())
            if (
                not stat.S_ISREG(snapshot_stat.st_mode)
                or snapshot_stat.st_nlink != 0
                or snapshot_stat.st_size != expected_size_bytes
                or actual_sha256 != expected_sha256
            ):
                raise MaskedVolumeMeasurementError(mismatch_reason)
            snapshot.seek(0)
            yield OwnedSecondaryV2(
                fd=snapshot.fileno(), size_bytes=expected_size_bytes, sha256=actual_sha256
            )
    finally:
        os.close(source_fd)


@contextmanager
def _offline_gdal_environment() -> Iterator[None]:
    with rasterio.Env(
        PROJ_NETWORK="OFF",
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_PAM_ENABLED="NO",
        GDAL_DRIVER_PATH="disable",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS="",
    ):
        yield


def _require_mask_structure_memory(envelope: ResourceEnvelopeV1, size_bytes: int) -> None:
    """Charge the mask header parse plus its decoded working set before any open."""
    required = (
        2 * size_bytes
        + envelope.max_tiff_directories * _MASK_STRUCTURE_DIRECTORY_OBJECT_BYTES
        + envelope.max_tiff_entries * _MASK_STRUCTURE_ENTRY_OBJECT_BYTES
        + _MASK_WORKING_BYTES
    )
    if required > envelope.max_memory_bytes:
        raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")


def _structure_base_dimensions(structure: Any) -> tuple[int, int]:
    """Read base width/height from the already-parsed first directory, pre-GDAL."""
    try:
        base = structure.directories[0]
        byte_order = "<" if structure.byte_order == "II" else ">"
        width_values = base.entries[256].integers(byte_order)
        height_values = base.entries[257].integers(byte_order)
        if len(width_values) != 1 or len(height_values) != 1:
            raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
        return int(width_values[0]), int(height_values[0])
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH") from exc


def _decode_owned_mask(
    owned: OwnedSecondaryV2,
    *,
    binding: ExclusionMaskBindingV1,
    baseline_transform: Affine,
    baseline_crs: str,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
) -> np.ndarray[Any, Any]:
    """Decode owned mask bytes with strict uint8 single-band NO_NODATA binary checks.

    The bounded binary-mask structural preflight runs BEFORE any GDAL open:
    IFD/entry/block/allocation/external-metadata limits, the exact UINT8
    single-band raw model, single base directory, and NoData rejection are all
    decided by the parser. The GDAL checks afterwards re-enforce nodata,
    internal mask flags, and binary values on the decoded view.
    """
    watchdog.check()
    if owned.size_bytes <= 0 or owned.size_bytes > min(
        envelope.max_input_bytes, envelope.max_streamed_bytes
    ):
        raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")
    _require_mask_structure_memory(envelope, owned.size_bytes)
    try:
        structure = parse_sealed_binary_mask_tiff_structure(owned.proc_path, envelope)
    except TiffResourceLimitError as exc:
        raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED") from exc
    except (OSError, TiffStructureError, ValueError) as exc:
        raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH") from exc
    structure_width, structure_height = _structure_base_dimensions(structure)
    if structure_width != binding.columns or structure_height != binding.rows:
        raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
    if structure_width * structure_height > envelope.max_pixels:
        raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")
    try:
        with _offline_gdal_environment(), rasterio.open(
            owned.proc_path, "r", driver="GTiff"
        ) as dataset:
            if dataset.subdatasets:
                raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
            if dataset.width <= 0 or dataset.height <= 0:
                raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
            if dataset.width * dataset.height > envelope.max_pixels:
                raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")
            if dataset.count > envelope.max_bands:
                raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")
            if (
                dataset.width * dataset.height * _MASK_BYTES_PER_PIXEL + _MASK_WORKING_BYTES
                > envelope.max_memory_bytes
            ):
                raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")
            if dataset.count != 1:
                raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
            if dataset.dtypes != ("uint8",):
                raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
            # Any NoData representation is a blocker: nodata 0/1 can never be
            # treated as keep/exclude, and internal mask flags are rejected too.
            if dataset.nodata is not None:
                raise MaskedVolumeMeasurementError("MASK_NODATA_REJECTED")
            if dataset.width != binding.columns or dataset.height != binding.rows:
                raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
            if dataset.transform != baseline_transform:
                raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
            try:
                crs_object = dataset.crs
                if crs_object is None:
                    raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
                mask_crs = assert_supported_project_crs(crs_object.to_string())
                assert_same_crs(mask_crs, baseline_crs, binding.observed_crs_identifier)
            except ValueError as exc:
                raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH") from exc
            if dataset.scales != (1.0,) or dataset.offsets != (0.0,):
                raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
            gcps, _ = dataset.gcps
            if gcps or dataset.tags(ns="GEOLOCATION"):
                raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
            actual_masks = dataset.read_masks(1)
            if bool((actual_masks != 255).any()):
                raise MaskedVolumeMeasurementError("MASK_NODATA_REJECTED")
            watchdog.check()
            values = dataset.read(1, masked=False)
    except MaskedVolumeMeasurementError:
        raise
    except (OSError, ValueError) as exc:
        raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH") from exc
    if not isinstance(values, np.ndarray) or values.dtype != np.dtype(np.uint8) or values.ndim != 2:
        raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
    unique = np.unique(values)
    if unique.size == 0 or bool(((unique != 0) & (unique != 1)).any()):
        raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
    if values.shape != (binding.rows, binding.columns):
        raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
    return values


def _compute_impact(
    *,
    measurement: Any,
    diff: DiffResult,
    excluded_cell_count: int,
) -> MaskedVolumeImpactV3:
    """Derive unmasked-vs-masked impact; unknown stays null when original lacks source values."""
    rows = int(measurement.effective_selected_mask.shape[0])
    columns = int(measurement.effective_selected_mask.shape[1])
    row = int(measurement.row_offset)
    column = int(measurement.column_offset)
    valid_window = np.zeros((rows, columns), dtype=np.bool_)
    values_window = np.zeros((rows, columns), dtype=np.float64)
    source_row_start = max(0, row)
    source_row_stop = min(diff.diff_m.shape[0], row + rows)
    source_col_start = max(0, column)
    source_col_stop = min(diff.diff_m.shape[1], column + columns)
    if source_row_start < source_row_stop and source_col_start < source_col_stop:
        target_rows = slice(source_row_start - row, source_row_stop - row)
        target_cols = slice(source_col_start - column, source_col_stop - column)
        valid_window[target_rows, target_cols] = diff.valid[
            source_row_start:source_row_stop, source_col_start:source_col_stop
        ]
        values_window[target_rows, target_cols] = diff.diff_m[
            source_row_start:source_row_stop, source_col_start:source_col_stop
        ]
    original = measurement.original_selected_mask
    original_unavailable = int((original & ~valid_window).sum())
    if original_unavailable != 0:
        return MaskedVolumeImpactV3(
            unmasked_impact_known=False,
            excluded_cell_count=excluded_cell_count,
            unmasked_cut_m3=None,
            unmasked_fill_m3=None,
            unmasked_net_m3=None,
            excluded_cut_m3=None,
            excluded_fill_m3=None,
            excluded_net_m3=None,
        )
    original_values = values_window[original]
    if original_values.size == 0 or not bool(np.isfinite(original_values).all()):
        return MaskedVolumeImpactV3(
            unmasked_impact_known=False,
            excluded_cell_count=excluded_cell_count,
            unmasked_cut_m3=None,
            unmasked_fill_m3=None,
            unmasked_net_m3=None,
            excluded_cut_m3=None,
            excluded_fill_m3=None,
            excluded_net_m3=None,
        )
    cell_area = float(diff.cell_area_m2)
    unmasked_fill = float(original_values[original_values > 0.0].sum() * cell_area)
    unmasked_cut = float(-original_values[original_values < 0.0].sum() * cell_area)
    excluded_values = values_window[measurement.mask_excluded_mask]
    excluded_fill = float(excluded_values[excluded_values > 0.0].sum() * cell_area)
    excluded_cut = float(-excluded_values[excluded_values < 0.0].sum() * cell_area)
    for value in (unmasked_fill, unmasked_cut, excluded_fill, excluded_cut):
        if not math.isfinite(value):
            raise MaskedVolumeMeasurementError("MASKED_ARITHMETIC_MISMATCH")
    return MaskedVolumeImpactV3(
        unmasked_impact_known=True,
        excluded_cell_count=excluded_cell_count,
        unmasked_cut_m3=unmasked_cut,
        unmasked_fill_m3=unmasked_fill,
        unmasked_net_m3=unmasked_fill - unmasked_cut,
        excluded_cut_m3=excluded_cut,
        excluded_fill_m3=excluded_fill,
        excluded_net_m3=excluded_fill - excluded_cut,
    )


def measure_masked_volume_v3_from_diff(
    *,
    masked_identity: MaskedCalculationIdentityV3,
    diff: DiffResult,
    exclusion_mask: np.ndarray[Any, Any],
    mask_crs: str,
    mask_transform: Affine,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
    lease_expires_at: datetime,
    report_id: str,
    computed_at: datetime,
    reported_at: datetime,
) -> MaskedVolumeMeasuredV3 | MaskedVolumeCalculationFailureV3:
    """Measure already-held arrays inside containment; every check still runs."""
    try:
        envelope = _require_sealed_envelope(envelope)
        watchdog = _require_watchdog(watchdog)
        watchdog.check()
        identity = _require_masked_identity(masked_identity)
        identity_digest = _identity_digest(identity)
        _require_timestamps(
            computed_at=computed_at, reported_at=reported_at, lease_expires_at=lease_expires_at
        )
        if not isinstance(report_id, str) or not report_id.strip() or len(report_id) > 255:
            raise MaskedVolumeMeasurementError("MASKED_INPUT_MISMATCH")
        diff_m, valid, transform, diff_crs, _diff_cell_area_m2 = _require_diff_arrays(diff)
        source = identity.source_calculation_identity
        expected_shape = (identity.grid_rows, identity.grid_columns)
        if (diff_m.shape[0], diff_m.shape[1]) != expected_shape:
            raise MaskedVolumeMeasurementError("MASKED_IDENTITY_MISMATCH")
        actual_transform = (
            transform.a,
            transform.b,
            transform.c,
            transform.d,
            transform.e,
            transform.f,
        )
        if tuple(float(v) for v in actual_transform) != tuple(
            float(v) for v in source.baseline_transform
        ):
            raise MaskedVolumeMeasurementError("MASKED_IDENTITY_MISMATCH")
        try:
            assert_same_crs(diff_crs, source.baseline_observed_crs_identifier)
        except ValueError as exc:
            raise MaskedVolumeMeasurementError("MASKED_IDENTITY_MISMATCH") from exc
        baseline_cells = diff_m.shape[0] * diff_m.shape[1]
        max_zone_cells = maximum_fixed_profile_zone_grid_cells(
            envelope=envelope, baseline_cell_count=baseline_cells
        )
        binding = identity.mask_binding
        if not isinstance(mask_crs, str) or not isinstance(mask_transform, Affine):
            raise MaskedVolumeMeasurementError("MASKED_INPUT_MISMATCH")
        try:
            normalised_mask_crs = normalise_crs(mask_crs)
            assert_same_crs(normalised_mask_crs, binding.observed_crs_identifier, diff_crs)
        except (AttributeError, TypeError, ValueError) as exc:
            raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH") from exc
        if mask_transform != transform:
            raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
        if np.ma.isMaskedArray(exclusion_mask):
            raise MaskedVolumeMeasurementError("MASK_NODATA_REJECTED")
        if (
            not isinstance(exclusion_mask, np.ndarray)
            or exclusion_mask.dtype != np.dtype(np.uint8)
            or exclusion_mask.ndim != 2
            or exclusion_mask.shape != (diff.diff_m.shape[0], diff.diff_m.shape[1])
        ):
            raise MaskedVolumeMeasurementError("MASK_BYTES_MISMATCH")
        if exclusion_mask.shape[0] * exclusion_mask.shape[1] > envelope.max_pixels:
            raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")
        watchdog.check()
        measurement = measure_masked_external_volume_zone(
            diff,
            source.work_area_polygon,
            zone_id=source.work_area_id,
            from_crs=source.work_area_crs,
            exclusion_mask=exclusion_mask,
            mask_crs=normalised_mask_crs,
            mask_transform=mask_transform,
            maximum_zone_grid_cells=max_zone_cells,
        )
        if isinstance(measurement, MaskedExternalVolumeError):
            raise MaskedVolumeMeasurementError(_mask_failure_reason(measurement.reason.value))
        watchdog.check()
        cell_area = float(measurement.metrics.zone_area_m2 / measurement.metrics.zone_cell_count)
        if not math.isfinite(cell_area) or cell_area <= 0.0:
            raise MaskedVolumeMeasurementError("MASKED_ARITHMETIC_MISMATCH")
        impact = _compute_impact(
            measurement=measurement,
            diff=diff,
            excluded_cell_count=int(measurement.mask_excluded_cell_count),
        )
        coverage = MaskedCoverageWitnessV3(
            rows=int(measurement.original_selected_mask.shape[0]),
            columns=int(measurement.original_selected_mask.shape[1]),
            row_offset=int(measurement.row_offset),
            column_offset=int(measurement.column_offset),
            original_selected_mask_b64=_pack_mask(measurement.original_selected_mask),
            mask_excluded_mask_b64=_pack_mask(measurement.mask_excluded_mask),
            effective_selected_mask_b64=_pack_mask(measurement.effective_selected_mask),
            common_valid_mask_b64=_pack_mask(measurement.common_valid_mask),
            unavailable_mask_b64=_pack_mask(measurement.unavailable_mask),
            original_selected_cell_count=int(measurement.original_selected_cell_count),
            mask_excluded_cell_count=int(measurement.mask_excluded_cell_count),
            effective_selected_cell_count=int(measurement.effective_selected_cell_count),
            common_valid_cell_count=int(measurement.common_valid_cell_count),
            unavailable_cell_count=int(measurement.unavailable_mask.sum()),
            cell_area_m2=cell_area,
            original_selected_area_m2=float(
                measurement.original_selected_cell_count * cell_area
            ),
            effective_selected_area_m2=float(
                measurement.effective_selected_cell_count * cell_area
            ),
            common_valid_area_m2=float(measurement.common_valid_cell_count * cell_area),
            bounds=measurement.bounds,
        ).sealed()
        numeric = MaskedVolumeNumericResultV3(
            masked_calculation_identity_digest=identity_digest,
            masked_profile_digest=identity.masked_profile_digest,
            mask_binding_digest=identity.mask_binding_digest,
            metrics=RelativeVolumeMetricsV2(
                cut_m3=measurement.metrics.cut_m3,
                fill_m3=measurement.metrics.fill_m3,
                net_m3=measurement.metrics.net_m3,
                threshold_m=0.0,
                uncertainty_m3=None,
            ),
            coverage=coverage,
            impact=impact,
        ).sealed()
        report = MaskedVolumeCalculationReportV3(
            report_id=report_id,
            masked_calculation_identity_digest=identity_digest,
            numeric_result=numeric,
            numeric_result_identity_digest=numeric.canonical_digest(),
            computed_at=computed_at,
            reported_at=reported_at,
        ).sealed()
        if len(report.model_dump_json(by_alias=True).encode("utf-8")) > envelope.max_output_bytes:
            raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")
        return MaskedVolumeMeasuredV3(
            report=report,
            delta_grid_m=measurement.delta_grid_m.copy(),
            row_offset=int(measurement.row_offset),
            column_offset=int(measurement.column_offset),
        )
    except MaskedVolumeMeasurementError as exc:
        reason = exc.reason
        digest = getattr(masked_identity, "masked_calculation_identity_digest", None)
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise
        return _failure(
            masked_identity_digest=digest,
            report_id=report_id if isinstance(report_id, str) and report_id else "report-unknown",
            reason=reason,
            failed_at=reported_at
            if isinstance(reported_at, datetime)
            else datetime.now().astimezone(),
        )
    except MeasurementAlgorithmIncomplete:
        raise
    except MeasurementAlgorithmError as exc:
        reason = exc.reason if isinstance(exc.reason, str) else "MASKED_INPUT_MISMATCH"
        digest = getattr(masked_identity, "masked_calculation_identity_digest", None)
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise
        return _failure(
            masked_identity_digest=digest,
            report_id=report_id if isinstance(report_id, str) and report_id else "report-unknown",
            reason=reason,
            failed_at=reported_at
            if isinstance(reported_at, datetime)
            else datetime.now().astimezone(),
        )


def measure_masked_volume_v3(
    *,
    masked_identity: MaskedCalculationIdentityV3,
    baseline_path: Path | str,
    current_path: Path | str,
    mask_path: Path | str,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
    lease_expires_at: datetime,
    report_id: str,
    computed_at: datetime,
    reported_at: datetime,
) -> MaskedVolumeMeasuredV3 | MaskedVolumeCalculationFailureV3:
    """File-backed contained primitive: snapshot, verify, decode, then measure.

    ``baseline_path``/``current_path``/``mask_path`` must be already-staged
    local sealed files; this module never mounts, routes, or activates a
    worker. DSM discovery reuses the retained owned-secondary inspector;
    mask decoding is the strict uint8 single-band NO_NODATA binary check.
    """
    try:
        envelope = _require_sealed_envelope(envelope)
        watchdog = _require_watchdog(watchdog)
        watchdog.check()
        identity = _require_masked_identity(masked_identity)
        _identity_digest(identity)
        _require_timestamps(
            computed_at=computed_at, reported_at=reported_at, lease_expires_at=lease_expires_at
        )
        source = identity.source_calculation_identity
        binding = identity.mask_binding
        baseline_p = Path(baseline_path)
        current_p = Path(current_path)
        mask_p = Path(mask_path)
        combined = (
            source.baseline_dsm_observed_size_bytes
            + source.current_dsm_observed_size_bytes
            + binding.observed_size_bytes
        )
        if combined > envelope.max_workspace_bytes:
            raise MaskedVolumeMeasurementError("RESOURCE_LIMIT_EXCEEDED")
        with (
            _owned_snapshot(
                baseline_p,
                expected_size_bytes=source.baseline_dsm_observed_size_bytes,
                expected_sha256=source.baseline_dsm_observed_sha256,
                envelope=envelope,
                watchdog=watchdog,
                mismatch_reason="BASELINE_DSM_BYTES_MISMATCH",
            ) as baseline,
            _owned_snapshot(
                current_p,
                expected_size_bytes=source.current_dsm_observed_size_bytes,
                expected_sha256=source.current_dsm_observed_sha256,
                envelope=envelope,
                watchdog=watchdog,
                mismatch_reason="CURRENT_DSM_BYTES_MISMATCH",
            ) as current,
            _owned_snapshot(
                mask_p,
                expected_size_bytes=binding.observed_size_bytes,
                expected_sha256=binding.observed_sha256,
                envelope=envelope,
                watchdog=watchdog,
                mismatch_reason="MASK_BYTES_MISMATCH",
            ) as owned_mask,
        ):
            baseline_preflight = preflight_owned_secondary_dsm_memory(
                baseline, envelope=envelope, watchdog=watchdog
            )
            current_preflight = preflight_owned_secondary_dsm_memory(
                current, envelope=envelope, watchdog=watchdog
            )
            preflight_volume_measurement_memory(
                baseline=baseline_preflight, current=current_preflight, envelope=envelope
            )
            observed_baseline = inspect_owned_secondary_dsm(
                baseline, envelope=envelope, watchdog=watchdog
            )
            observed_current = inspect_owned_secondary_dsm(
                current, envelope=envelope, watchdog=watchdog
            )
            if (
                observed_baseline.observed_crs_digest != source.baseline_observed_crs_digest
                or observed_current.observed_crs_digest != source.current_observed_crs_digest
            ):
                raise MaskedVolumeMeasurementError("BASELINE_DSM_CONTEXT_MISMATCH")
            mask_array = _decode_owned_mask(
                owned_mask,
                binding=binding,
                baseline_transform=Affine(*source.baseline_transform),
                baseline_crs=source.baseline_observed_crs_identifier,
                envelope=envelope,
                watchdog=watchdog,
            )
            diff = align_masked_dsm_difference(
                baseline_path=baseline.proc_path,
                current_path=current.proc_path,
                envelope=envelope,
                watchdog=watchdog,
            )
            return measure_masked_volume_v3_from_diff(
                masked_identity=identity,
                diff=diff,
                exclusion_mask=mask_array,
                mask_crs=binding.observed_crs_identifier,
                mask_transform=Affine(*source.baseline_transform),
                envelope=envelope,
                watchdog=watchdog,
                lease_expires_at=lease_expires_at,
                report_id=report_id,
                computed_at=computed_at,
                reported_at=reported_at,
            )
    except MaskedVolumeMeasurementError as exc:
        digest = getattr(masked_identity, "masked_calculation_identity_digest", None)
        if not isinstance(digest, str) or not digest.startswith("sha256:"):
            raise
        if not isinstance(lease_expires_at, datetime):
            raise
        failed_at = reported_at if isinstance(reported_at, datetime) else lease_expires_at
        return _failure(
            masked_identity_digest=digest,
            report_id=report_id if isinstance(report_id, str) and report_id else "report-unknown",
            reason=exc.reason,
            failed_at=failed_at,
        )
    except (MeasurementAlgorithmIncomplete, MeasurementAlgorithmError):
        raise


__all__ = [
    "MaskedVolumeMeasuredV3",
    "MaskedVolumeMeasurementError",
    "measure_masked_volume_v3",
    "measure_masked_volume_v3_from_diff",
]
