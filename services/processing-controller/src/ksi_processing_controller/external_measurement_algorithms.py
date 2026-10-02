"""Contained aggregate measurements over two already sealed external inputs.

This module only consumes the fixed primary mount and an owned anonymous
secondary descriptor.  It deliberately returns ordinary aggregate dictionaries
for the inner protocol; turning them into a durable report remains outside the
container boundary.
"""

from __future__ import annotations

import hashlib
import math
import os
import stat
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from ksi_change_detection.dsm_diff import DiffResult
from ksi_change_detection.external_single_volume import measure_single_volume_zone
from ksi_change_detection.external_volume import (
    ExternalVolumeMeasurementError,
    measure_external_volume_zone,
)
from ksi_domain.canonical_json import canonical_json_bytes
from ksi_event_contracts.external_artifact_validation import (
    ArtifactOutcome,
    ObservedVerticalReferenceV1,
    ResourceEnvelopeV1,
)
from ksi_event_contracts.external_evidence import EvidenceCoreVerdict
from ksi_event_contracts.processing_artifact import ProcessingArtifactKind
from ksi_geo_spatial.crs import assert_same_crs, assert_supported_project_crs
from pyproj import CRS
from rasterio.errors import RasterioError
from rasterio.warp import Resampling, reproject
from rasterio.windows import Window

from ksi_processing_controller.checkpoint_validator import (
    Checkpoint,
    CheckpointValidationError,
    _nearest_pixel,
    parse_checkpoint_csv,
)
from ksi_processing_controller.external_geotiff_inspector import (
    _measure_dataset,
    _require_base_directory,
    _require_no_subdatasets,
    inspect_synthetic_sealed_geotiff,
)
from ksi_processing_controller.external_measurement_container_protocol import (
    SINGLE_VOLUME_KNOWN_UNCERTAINTY_NOTE,
    SINGLE_VOLUME_UNKNOWN_UNCERTAINTY_NOTE,
)
from ksi_processing_controller.external_measurement_protocol import (
    MeasurementInputV2,
    MeasurementLaunchRequestV2,
)
from ksi_processing_controller.external_tiff_structure import (
    TiffResourceLimitError,
    TiffStructureV1,
    parse_sealed_tiff_structure,
)

_READ_CHUNK_BYTES = 1024 * 1024
_TIFF_PREDECODE_WORKING_BYTES = _READ_CHUNK_BYTES
_TIFF_DIRECTORY_OBJECT_BYTES = 4 * 1024
_TIFF_ENTRY_OBJECT_BYTES = 128
# Baseline/current values and masks, a source-valid copy, a resampled current
# grid, and the resulting diff coexist briefly during alignment.  Charge the
# bounded arrays before allocating them instead of trusting only pixel count.
_BASELINE_ALIGNMENT_BYTES_PER_PIXEL = 64
_CURRENT_ALIGNMENT_BYTES_PER_PIXEL = 32
_ALIGNMENT_WORKING_BYTES = 2 * _READ_CHUNK_BYTES
_CHECKPOINT_BYTES_PER_INPUT_BYTE = 8
_CHECKPOINT_BYTES_PER_ROW = 512
_CHECKPOINT_WORKING_BYTES = 2 * _READ_CHUNK_BYTES
_DIFF_RESULT_BYTES_PER_PIXEL = 16
_VOLUME_ZONE_BYTES_PER_CELL = 32
_VOLUME_ZONE_WORKING_BYTES = _READ_CHUNK_BYTES
# Target grid values/valid plus the derived difference grid and its mask.
_SINGLE_VOLUME_BYTES_PER_PIXEL = 18
# Zone masks, boundary ring, base surface, interpolation coordinates and values.
_SINGLE_VOLUME_ZONE_BYTES_PER_CELL = 96


class MeasurementAlgorithmError(RuntimeError):
    """A typed contained measurement failure which has no partial aggregate."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class MeasurementAlgorithmIncomplete(RuntimeError):
    """Cancellation or a signed runtime budget expiry cannot publish a result."""


@dataclass(frozen=True, slots=True)
class OwnedSecondaryV2:
    """An already verified O_TMPFILE descriptor; its path is derived only locally."""

    fd: int
    size_bytes: int
    sha256: str

    @property
    def proc_path(self) -> Path:
        return Path(f"/proc/self/fd/{self.fd}")


@dataclass(frozen=True, slots=True)
class ObservedDsmV2:
    """The limited raster facts required by the two contained algorithms."""

    path: Path
    crs: str
    observed_crs_digest: str
    observed_vertical_reference_digest: str | None


@dataclass(frozen=True, slots=True)
class DsmMemoryPreflightV2:
    """Raw TIFF and decoder capacity admitted before any raster sample read."""

    width: int
    height: int
    source_size_bytes: int


@dataclass(frozen=True, slots=True)
class MeasurementWatchdogV2:
    """Per-call monotonic and CPU budgets inherited from signed resource limits."""

    started_monotonic: float
    started_cpu_seconds: float
    maximum_wall_seconds: float
    maximum_cpu_seconds: float
    is_cancelled: Callable[[], bool] | None = None

    @classmethod
    def from_envelope(
        cls,
        envelope: ResourceEnvelopeV1,
        *,
        maximum_wall_seconds: float | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> MeasurementWatchdogV2:
        wall = (
            envelope.max_deadline_seconds if maximum_wall_seconds is None else maximum_wall_seconds
        )
        if not math.isfinite(wall) or wall <= 0.0:
            raise MeasurementAlgorithmError("RESOURCE_LIMIT_EXCEEDED")
        return cls(
            started_monotonic=time.monotonic(),
            started_cpu_seconds=time.process_time(),
            maximum_wall_seconds=wall,
            maximum_cpu_seconds=envelope.max_cpu_seconds,
            is_cancelled=is_cancelled,
        )

    def check(self) -> None:
        if self.is_cancelled is not None and self.is_cancelled():
            raise MeasurementAlgorithmIncomplete("measurement cancelled")
        if (
            time.monotonic() - self.started_monotonic > self.maximum_wall_seconds
            or time.process_time() - self.started_cpu_seconds > self.maximum_cpu_seconds
        ):
            raise MeasurementAlgorithmIncomplete("measurement resource deadline reached")


def verify_owned_secondary_fd(
    fd: int,
    *,
    expected: MeasurementInputV2,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
) -> OwnedSecondaryV2:
    """Verify an anonymous regular spool before using its derived proc descriptor.

    The descriptor is never reconstructed from a caller path.  The procfs path
    is created only after its regular-file, unlinked, owner, mode, size, and
    byte identity are all confirmed.
    """

    watchdog.check()
    try:
        state = os.fstat(fd)
    except OSError as exc:
        raise MeasurementAlgorithmError("SECONDARY_SPOOL_UNAVAILABLE") from exc
    if (
        not stat.S_ISREG(state.st_mode)
        or state.st_nlink != 0
        or stat.S_IMODE(state.st_mode) != 0o600
        or state.st_uid != os.geteuid()
        or state.st_gid != os.getegid()
        or state.st_size != expected.observed_size_bytes
        or state.st_size > min(envelope.max_workspace_bytes, envelope.max_streamed_bytes)
    ):
        raise MeasurementAlgorithmError("SECONDARY_SPOOL_IDENTITY_MISMATCH")
    digest = hashlib.sha256()
    offset = 0
    while offset < state.st_size:
        watchdog.check()
        try:
            chunk = os.pread(fd, min(_READ_CHUNK_BYTES, state.st_size - offset), offset)
        except OSError as exc:
            raise MeasurementAlgorithmError("SECONDARY_SPOOL_UNREADABLE") from exc
        if not chunk:
            raise MeasurementAlgorithmError("SECONDARY_SPOOL_UNDERFLOW")
        digest.update(chunk)
        offset += len(chunk)
    actual = "sha256:" + digest.hexdigest()
    if actual != expected.observed_sha256:
        raise MeasurementAlgorithmError("SECONDARY_SPOOL_DIGEST_MISMATCH")
    return OwnedSecondaryV2(fd=fd, size_bytes=state.st_size, sha256=actual)


def preflight_secondary_stream_memory(
    *, expected_size_bytes: int, envelope: ResourceEnvelopeV1
) -> None:
    """Reserve the maximum raw-secondary copy/hash buffer before stdin reads."""

    _require_memory_capacity(
        envelope,
        min(_READ_CHUNK_BYTES, expected_size_bytes),
    )


def preflight_primary_dsm_memory(
    path: Path,
    *,
    expected: MeasurementInputV2,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
) -> DsmMemoryPreflightV2:
    """Reserve raw TIFF/parser/decoder capacity before primary pixel reads."""

    return _preflight_dsm_memory(
        path,
        expected_size_bytes=expected.observed_size_bytes,
        envelope=envelope,
        watchdog=watchdog,
        rejection_reason="PRIMARY_DSM_REJECTED",
    )


def preflight_owned_secondary_dsm_memory(
    secondary: OwnedSecondaryV2,
    *,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
) -> DsmMemoryPreflightV2:
    """Reserve raw TIFF/parser/decoder capacity before secondary pixel reads."""

    return _preflight_dsm_memory(
        secondary.proc_path,
        expected_size_bytes=secondary.size_bytes,
        envelope=envelope,
        watchdog=watchdog,
        rejection_reason="SECONDARY_DSM_REJECTED",
    )


def preflight_checkpoint_measurement_memory(
    *,
    secondary_size_bytes: int,
    maximum_checkpoint_count: int,
    envelope: ResourceEnvelopeV1,
) -> None:
    """Reserve CSV parse/materialization/residual capacity before raster decode."""

    _require_checkpoint_memory(
        envelope=envelope,
        secondary_size_bytes=secondary_size_bytes,
        maximum_checkpoint_count=maximum_checkpoint_count,
    )


def preflight_volume_measurement_memory(
    *,
    baseline: DsmMemoryPreflightV2,
    current: DsmMemoryPreflightV2,
    envelope: ResourceEnvelopeV1,
) -> None:
    """Reserve both grids, their live alignment state, and later zone workspace."""

    _require_alignment_memory(
        envelope=envelope,
        baseline_width=baseline.width,
        baseline_height=baseline.height,
        current_width=current.width,
        current_height=current.height,
    )
    _maximum_zone_grid_cells(
        envelope=envelope,
        baseline_cell_count=baseline.width * baseline.height,
    )


def maximum_fixed_profile_zone_grid_cells(
    *, envelope: ResourceEnvelopeV1, baseline_cell_count: int
) -> int:
    """Return the remaining full-zone capacity after retained diff arrays.

    The V2 profile retains three boolean coverage masks in addition to the
    regular zone selection and delta buffers. The existing conservative V1
    zone charge is the shared floor; V2 callers apply their own additional
    witness charge before allocating a full WorkArea window.
    """
    available_bytes = (
        envelope.max_memory_bytes
        - baseline_cell_count * _DIFF_RESULT_BYTES_PER_PIXEL
        - _VOLUME_ZONE_WORKING_BYTES
    )
    v2_zone_bytes_per_cell = _VOLUME_ZONE_BYTES_PER_CELL + 3
    if available_bytes < v2_zone_bytes_per_cell:
        raise MeasurementAlgorithmError("RESOURCE_LIMIT_EXCEEDED")
    return min(envelope.max_pixels, available_bytes // v2_zone_bytes_per_cell)


def preflight_single_volume_measurement_memory(
    *, target: DsmMemoryPreflightV2, envelope: ResourceEnvelopeV1
) -> None:
    """Reserve the target grid, its derived difference and later zone workspace."""

    _single_volume_zone_grid_cells(envelope=envelope, cell_count=target.width * target.height)


def inspect_primary_dsm(
    path: Path,
    *,
    expected: MeasurementInputV2,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
) -> ObservedDsmV2:
    """Use the retained V1 primary profile for the one named read-only mount."""

    watchdog.check()
    outcome = inspect_synthetic_sealed_geotiff(
        path,
        artifact_id=expected.artifact_id,
        observed_sha256=expected.observed_sha256,
        artifact_kind=ProcessingArtifactKind.DSM,
        envelope=envelope,
        is_cancelled=lambda: _watchdog_cancelled(watchdog),
    )
    if outcome.outcome is not ArtifactOutcome.MEASURED or outcome.measurements is None:
        raise MeasurementAlgorithmError("PRIMARY_DSM_REJECTED")
    measurements = outcome.measurements
    return ObservedDsmV2(
        path=path,
        crs=measurements.observed_crs_identifier,
        observed_crs_digest=measurements.observed_crs_digest,
        observed_vertical_reference_digest=_vertical_digest(
            measurements.observed_vertical_reference
        ),
    )


def inspect_owned_secondary_dsm(
    secondary: OwnedSecondaryV2,
    *,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
) -> ObservedDsmV2:
    """Run the full V1 DSM grammar over a verified anonymous descriptor.

    The V1 top-level helper also requires a named single-link sealed file, which
    is intentionally incompatible with an O_TMPFILE.  This contained adapter
    retains the verified descriptor and invokes the same parser, raw-directory,
    profile, mask/overview, and bounded decode checks before any volume pixels
    are read.
    """

    watchdog.check()
    path = secondary.proc_path
    try:
        structure = parse_sealed_tiff_structure(path, envelope)
        with _offline_gdal_environment(), rasterio.open(path, "r", driver="GTiff") as dataset:
            _require_no_subdatasets(dataset)
            _require_base_directory(structure, dataset)
            measurements = _measure_dataset(
                dataset,
                path,
                ProcessingArtifactKind.DSM,
                envelope,
                structure,
                lambda: _watchdog_cancelled(watchdog),
            )
    except MeasurementAlgorithmIncomplete:
        raise
    except TiffResourceLimitError as exc:
        raise MeasurementAlgorithmError("RESOURCE_LIMIT_EXCEEDED") from exc
    except (OSError, RasterioError, ValueError) as exc:
        raise MeasurementAlgorithmError("SECONDARY_DSM_REJECTED") from exc
    return ObservedDsmV2(
        path=path,
        crs=measurements.observed_crs_identifier,
        observed_crs_digest=measurements.observed_crs_digest,
        observed_vertical_reference_digest=_vertical_digest(
            measurements.observed_vertical_reference
        ),
    )


def measure_checkpoint_aggregate(
    request: MeasurementLaunchRequestV2,
    *,
    primary: ObservedDsmV2,
    secondary: OwnedSecondaryV2,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
) -> dict[str, Any]:
    """Measure every strict CSV checkpoint against the fixed primary DSM."""

    if request.operation != "CHECKPOINT_VALIDATION" or request.evidence_context is None:
        raise MeasurementAlgorithmError("OPERATION_BINDING_MISMATCH")
    context = request.evidence_context
    if request.inputs[1].role != "CHECKPOINT_CSV":
        raise MeasurementAlgorithmError("OPERATION_BINDING_MISMATCH")
    expected_crs = assert_supported_project_crs(context.csv_horizontal_crs)
    if assert_supported_project_crs(primary.crs) != expected_crs:
        raise MeasurementAlgorithmError("CHECKPOINT_CRS_MISMATCH")
    if (
        primary.observed_vertical_reference_digest is None
        or primary.observed_vertical_reference_digest != context.csv_vertical_reference_digest
    ):
        raise MeasurementAlgorithmError("CHECKPOINT_VERTICAL_REFERENCE_MISMATCH")
    _require_checkpoint_memory(
        envelope=envelope,
        secondary_size_bytes=secondary.size_bytes,
        maximum_checkpoint_count=context.maximum_checkpoint_count,
    )
    try:
        checkpoints = parse_checkpoint_csv(_read_owned_bytes(secondary, watchdog=watchdog))
    except CheckpointValidationError as exc:
        raise MeasurementAlgorithmError("INVALID_CHECKPOINT_CSV") from exc
    if not context.minimum_checkpoint_count <= len(checkpoints) <= context.maximum_checkpoint_count:
        raise MeasurementAlgorithmError("CHECKPOINT_COUNT_OUT_OF_RANGE")
    residuals = _checkpoint_residuals(primary.path, checkpoints, watchdog=watchdog)
    values = np.asarray(residuals, dtype=np.float64)
    absolute = np.abs(values)
    metrics = (
        float(np.mean(values, dtype=np.float64)),
        float(np.mean(absolute, dtype=np.float64)),
        float(math.sqrt(float(np.mean(values * values, dtype=np.float64)))),
        float(np.max(absolute)),
    )
    if not all(math.isfinite(value) for value in metrics):
        raise MeasurementAlgorithmError("INVALID_CHECKPOINT_MEASUREMENT")
    return {
        "metricType": "CHECKPOINT_VALIDATION_AGGREGATE_V2",
        "measuredCheckpointCount": len(residuals),
        "meanErrorM": metrics[0],
        "maeM": metrics[1],
        "rmseM": metrics[2],
        "maxAbsErrorM": metrics[3],
    }


def measure_relative_volume_aggregate(
    request: MeasurementLaunchRequestV2,
    *,
    primary: ObservedDsmV2,
    secondary: ObservedDsmV2,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
) -> dict[str, Any]:
    """Measure current-minus-baseline with internal masks and full-zone coverage."""

    if (
        request.operation != "RELATIVE_VOLUME"
        or request.volume_request is None
        or request.volume_execution_policy is None
        or request.inputs[1].role != "CURRENT_DSM"
    ):
        raise MeasurementAlgorithmError("OPERATION_BINDING_MISMATCH")
    volume_request = request.volume_request
    if (
        primary.observed_crs_digest != volume_request.baseline.observed_crs_digest
        or secondary.observed_crs_digest != volume_request.current.observed_crs_digest
        or primary.observed_vertical_reference_digest
        != volume_request.baseline.observed_vertical_reference_digest
        or secondary.observed_vertical_reference_digest
        != volume_request.current.observed_vertical_reference_digest
    ):
        raise MeasurementAlgorithmError("VOLUME_RASTER_CONTEXT_MISMATCH")
    try:
        assert_same_crs(primary.crs, secondary.crs, volume_request.zone_snapshot.crs)
    except ValueError as exc:
        raise MeasurementAlgorithmError("VOLUME_CRS_MISMATCH") from exc
    diff = align_masked_dsm_difference(
        baseline_path=primary.path,
        current_path=secondary.path,
        envelope=envelope,
        watchdog=watchdog,
    )
    policy = request.volume_execution_policy
    rmse = _validated_epoch_rmses(request)
    result = measure_external_volume_zone(
        diff,
        volume_request.zone_snapshot.polygon,
        zone_id=volume_request.zone_snapshot.work_area_id,
        from_crs=volume_request.zone_snapshot.crs,
        threshold_m=policy.threshold_m,
        minimum_common_valid_fraction=policy.minimum_common_valid_fraction,
        maximum_zone_grid_cells=_maximum_zone_grid_cells(
            envelope=envelope,
            baseline_cell_count=diff.diff_m.shape[0] * diff.diff_m.shape[1],
        ),
        uncertainty_note=(
            "Independent validated checkpoint RMSE was used for both epochs."
            if rmse is not None
            else "Independent checkpoint RMSE is unavailable for one or both epochs."
        ),
        baseline_rmse_m=None if rmse is None else rmse[0],
        current_rmse_m=None if rmse is None else rmse[1],
    )
    if isinstance(result, ExternalVolumeMeasurementError):
        raise MeasurementAlgorithmError(result.reason.value)
    metrics = result.metrics
    return {
        "metricType": "RELATIVE_VOLUME_AGGREGATE_V2",
        "zoneId": result.zone_id,
        "metrics": metrics.model_dump(by_alias=True, mode="json"),
    }


def measure_single_volume_aggregate(
    request: MeasurementLaunchRequestV2,
    *,
    primary: ObservedDsmV2,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
) -> dict[str, Any]:
    """Measure the target DSM against its zone-boundary base surface."""

    single = request.single_volume_request
    policy = request.single_volume_execution_policy
    if (
        request.operation != "SINGLE_VOLUME"
        or single is None
        or policy is None
        or request.inputs[0].role != "TARGET_DSM"
        or request.inputs[1].role != "CHECKPOINT_CSV"
    ):
        raise MeasurementAlgorithmError("OPERATION_BINDING_MISMATCH")
    target = single.target
    zone = single.zone_snapshot
    if (
        primary.observed_crs_digest != target.observed_crs_digest
        or primary.observed_vertical_reference_digest != target.observed_vertical_reference_digest
    ):
        raise MeasurementAlgorithmError("VOLUME_RASTER_CONTEXT_MISMATCH")
    try:
        assert_same_crs(primary.crs, zone.crs)
    except ValueError as exc:
        raise MeasurementAlgorithmError("VOLUME_CRS_MISMATCH") from exc
    try:
        with (
            _offline_gdal_environment(),
            rasterio.open(primary.path, "r", driver="GTiff") as dataset,
        ):
            values, valid = _read_valid_dsm(dataset, watchdog=watchdog)
            transform = dataset.transform
    except RasterioError as exc:
        raise MeasurementAlgorithmError("PRIMARY_DSM_REJECTED") from exc
    watchdog.check()
    rmse = _validated_target_rmse(request)
    result = measure_single_volume_zone(
        values,
        valid,
        transform=transform,
        crs=primary.crs,
        cell_area_m2=abs(transform.a * transform.e - transform.b * transform.d),
        polygon_geojson=zone.polygon,
        zone_id=zone.work_area_id,
        from_crs=zone.crs,
        threshold_m=policy.threshold_m,
        minimum_common_valid_fraction=policy.minimum_common_valid_fraction,
        minimum_boundary_valid_fraction=policy.minimum_boundary_valid_fraction,
        maximum_zone_grid_cells=_single_volume_zone_grid_cells(
            envelope=envelope, cell_count=int(values.size)
        ),
        uncertainty_note=(
            SINGLE_VOLUME_KNOWN_UNCERTAINTY_NOTE
            if rmse is not None
            else SINGLE_VOLUME_UNKNOWN_UNCERTAINTY_NOTE
        ),
        dsm_rmse_m=rmse,
    )
    watchdog.check()
    if isinstance(result, ExternalVolumeMeasurementError):
        raise MeasurementAlgorithmError(result.reason.value)
    return {
        "metricType": "SINGLE_VOLUME_AGGREGATE_V2",
        "zoneId": result.zone_id,
        "metrics": result.metrics.model_dump(by_alias=True, mode="json"),
    }


def _validated_target_rmse(request: MeasurementLaunchRequestV2) -> float | None:
    single = request.single_volume_request
    records = request.volume_evidence_records
    if single is None or len(records) != 1:
        raise MeasurementAlgorithmError("VOLUME_EVIDENCE_BINDING_MISMATCH")
    record = records[0]
    if (
        record.subject_digest != single.target.subject.canonical_digest()
        or record.target_dsm_observed_sha256 != single.target.observed_sha256
        or record.policy_digest != request.validation_policy.policy_digest
    ):
        raise MeasurementAlgorithmError("VOLUME_EVIDENCE_BINDING_MISMATCH")
    payload = record.measurement_payload
    if record.core_verdict is not EvidenceCoreVerdict.VALIDATED or payload is None:
        return None
    return payload.rmse_m


def _single_volume_zone_grid_cells(*, envelope: ResourceEnvelopeV1, cell_count: int) -> int:
    available_bytes = (
        envelope.max_memory_bytes
        - cell_count * _SINGLE_VOLUME_BYTES_PER_PIXEL
        - _VOLUME_ZONE_WORKING_BYTES
    )
    if available_bytes < _SINGLE_VOLUME_ZONE_BYTES_PER_CELL:
        raise MeasurementAlgorithmError("RESOURCE_LIMIT_EXCEEDED")
    return min(envelope.max_pixels, available_bytes // _SINGLE_VOLUME_ZONE_BYTES_PER_CELL)


def align_masked_dsm_difference(
    *,
    baseline_path: Path,
    current_path: Path,
    envelope: ResourceEnvelopeV1 | None,
    watchdog: MeasurementWatchdogV2,
) -> DiffResult:
    """Align a current DSM to the baseline grid without converting masks to values."""

    if envelope is None:
        raise MeasurementAlgorithmError("RESOURCE_LIMIT_EXCEEDED")
    try:
        with (
            _offline_gdal_environment(),
            rasterio.open(baseline_path, "r", driver="GTiff") as baseline,
            rasterio.open(current_path, "r", driver="GTiff") as current,
        ):
            _require_contained_dsm(baseline, envelope=envelope, watchdog=watchdog)
            _require_contained_dsm(current, envelope=envelope, watchdog=watchdog)
            _require_alignment_memory(
                envelope=envelope,
                baseline_width=baseline.width,
                baseline_height=baseline.height,
                current_width=current.width,
                current_height=current.height,
            )
            base_crs, _, _ = _observed_dsm_references(baseline)
            current_crs, _, _ = _observed_dsm_references(current)
            crs = assert_same_crs(base_crs, current_crs)
            base_values, base_valid = _read_valid_dsm(baseline, watchdog=watchdog)
            current_values, current_valid = _read_valid_dsm(current, watchdog=watchdog)
            current_source = np.where(current_valid, current_values, np.nan)
            current_on_base = np.full(base_values.shape, np.nan, dtype=np.float64)
            current_valid_on_base = np.zeros(base_values.shape, dtype=np.uint8)
            reproject(
                source=current_source,
                destination=current_on_base,
                src_transform=current.transform,
                src_crs=current.crs,
                dst_transform=baseline.transform,
                dst_crs=baseline.crs,
                src_nodata=np.nan,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
            reproject(
                source=current_valid.astype(np.uint8),
                destination=current_valid_on_base,
                src_transform=current.transform,
                src_crs=current.crs,
                dst_transform=baseline.transform,
                dst_crs=baseline.crs,
                src_nodata=0,
                dst_nodata=0,
                resampling=Resampling.nearest,
            )
            transform = baseline.transform
    except MeasurementAlgorithmIncomplete:
        raise
    except MeasurementAlgorithmError:
        raise
    except (OSError, RasterioError, ValueError) as exc:
        raise MeasurementAlgorithmError("VOLUME_DSM_ALIGNMENT_FAILED") from exc
    watchdog.check()
    valid = base_valid & (current_valid_on_base == 1) & np.isfinite(current_on_base)
    if not bool(valid.any()):
        raise MeasurementAlgorithmError("EMPTY_COMMON_VALID_COVERAGE")
    diff = np.zeros(base_values.shape, dtype=np.float64)
    diff[valid] = current_on_base[valid] - base_values[valid]
    return DiffResult(
        diff_m=diff,
        valid=valid,
        transform=transform,
        crs=crs,
        cell_area_m2=abs(transform.a * transform.e - transform.b * transform.d),
    )


def _checkpoint_residuals(
    path: Path, checkpoints: tuple[Checkpoint, ...], *, watchdog: MeasurementWatchdogV2
) -> list[float]:
    try:
        with _offline_gdal_environment(), rasterio.open(path, "r", driver="GTiff") as dataset:
            residuals: list[float] = []
            for point in checkpoints:
                watchdog.check()
                row, col = _nearest_pixel(dataset, x=point.easting_m, y=point.northing_m)
                value = dataset.read(1, window=Window(col, row, 1, 1), masked=True)[0, 0]
                if np.ma.is_masked(value) or not math.isfinite(float(value)):
                    raise MeasurementAlgorithmError("DSM_NODATA_AT_CHECKPOINT")
                residual = float(value) - point.elevation_m
                if not math.isfinite(residual):
                    raise MeasurementAlgorithmError("INVALID_CHECKPOINT_MEASUREMENT")
                residuals.append(residual)
            return residuals
    except MeasurementAlgorithmError:
        raise
    except CheckpointValidationError as exc:
        raise MeasurementAlgorithmError("CHECKPOINT_OUTSIDE_DSM") from exc
    except (OSError, RasterioError, ValueError) as exc:
        raise MeasurementAlgorithmError("PRIMARY_DSM_REJECTED") from exc


def _read_owned_bytes(secondary: OwnedSecondaryV2, *, watchdog: MeasurementWatchdogV2) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < secondary.size_bytes:
        watchdog.check()
        try:
            chunk = os.pread(
                secondary.fd, min(_READ_CHUNK_BYTES, secondary.size_bytes - offset), offset
            )
        except OSError as exc:
            raise MeasurementAlgorithmError("SECONDARY_SPOOL_UNREADABLE") from exc
        if not chunk:
            raise MeasurementAlgorithmError("SECONDARY_SPOOL_UNDERFLOW")
        chunks.append(chunk)
        offset += len(chunk)
    return b"".join(chunks)


def _preflight_dsm_memory(
    path: Path,
    *,
    expected_size_bytes: int,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
    rejection_reason: str,
) -> DsmMemoryPreflightV2:
    """Bound raw parser and decoded-sample capacity before a Rasterio sample read.

    The retained V1 inspector owns complete profile conformance, but it
    intentionally does not consume the contained measurement memory ceiling.
    This adapter reserves enough for its byte materialization, bounded TIFF
    metadata, and every allowed decoded sample before invoking that inspector.
    """

    watchdog.check()
    try:
        state = path.stat()
    except OSError as exc:
        raise MeasurementAlgorithmError(rejection_reason) from exc
    if state.st_size != expected_size_bytes:
        raise MeasurementAlgorithmError(rejection_reason)
    _require_memory_capacity(
        envelope,
        2 * expected_size_bytes
        + envelope.max_tiff_directories * _TIFF_DIRECTORY_OBJECT_BYTES
        + envelope.max_tiff_entries * _TIFF_ENTRY_OBJECT_BYTES,
    )
    try:
        structure = parse_sealed_tiff_structure(path, envelope)
        width, height = _base_grid_dimensions(structure)
        if width * height > envelope.max_pixels:
            raise TiffResourceLimitError("base image dimensions exceed the finite policy envelope")
        _require_memory_capacity(
            envelope,
            2 * expected_size_bytes
            + _tiff_structure_memory_bytes(structure)
            + structure.estimated_decompressed_bytes
            + _TIFF_PREDECODE_WORKING_BYTES,
        )
    except MeasurementAlgorithmError:
        raise
    except TiffResourceLimitError as exc:
        raise MeasurementAlgorithmError("RESOURCE_LIMIT_EXCEEDED") from exc
    except (OSError, ValueError) as exc:
        raise MeasurementAlgorithmError(rejection_reason) from exc
    return DsmMemoryPreflightV2(
        width=width,
        height=height,
        source_size_bytes=expected_size_bytes,
    )


def _base_grid_dimensions(structure: TiffStructureV1) -> tuple[int, int]:
    byte_order = "<" if structure.byte_order == "II" else ">"
    bases = []
    for directory in structure.directories:
        subtype_entry = directory.entries.get(254)
        subtype = (0,) if subtype_entry is None else subtype_entry.integers(byte_order)
        if subtype == (0,):
            bases.append(directory)
    if len(bases) != 1:
        raise ValueError("TIFF requires exactly one base directory")
    width = _single_tiff_integer(bases[0], 256, byte_order)
    height = _single_tiff_integer(bases[0], 257, byte_order)
    if width <= 0 or height <= 0:
        raise ValueError("TIFF base dimensions must be positive")
    return width, height


def _single_tiff_integer(directory: Any, tag: int, byte_order: str) -> int:
    entry = directory.entries.get(tag)
    if entry is None:
        raise ValueError(f"TIFF base tag {tag} is absent")
    values = entry.integers(byte_order)
    if len(values) != 1:
        raise ValueError(f"TIFF base tag {tag} must be singular")
    return values[0]


def _tiff_structure_memory_bytes(structure: TiffStructureV1) -> int:
    return sum(
        _TIFF_DIRECTORY_OBJECT_BYTES + len(directory.entries) * _TIFF_ENTRY_OBJECT_BYTES
        for directory in structure.directories
    )


def _require_memory_capacity(envelope: ResourceEnvelopeV1, required_bytes: int) -> None:
    if required_bytes > envelope.max_memory_bytes:
        raise MeasurementAlgorithmError("RESOURCE_LIMIT_EXCEEDED")


def _require_alignment_memory(
    *,
    envelope: ResourceEnvelopeV1,
    baseline_width: int,
    baseline_height: int,
    current_width: int,
    current_height: int,
) -> None:
    """Charge all source/destination/mask arrays before any full-grid allocation."""

    required = (
        baseline_width * baseline_height * _BASELINE_ALIGNMENT_BYTES_PER_PIXEL
        + current_width * current_height * _CURRENT_ALIGNMENT_BYTES_PER_PIXEL
        + _ALIGNMENT_WORKING_BYTES
    )
    _require_memory_capacity(envelope, required)


def _require_checkpoint_memory(
    *,
    envelope: ResourceEnvelopeV1,
    secondary_size_bytes: int,
    maximum_checkpoint_count: int,
) -> None:
    """Charge CSV materialization, parsed rows, residual vectors, and work buffers."""

    required = (
        secondary_size_bytes * _CHECKPOINT_BYTES_PER_INPUT_BYTE
        + maximum_checkpoint_count * _CHECKPOINT_BYTES_PER_ROW
        + _CHECKPOINT_WORKING_BYTES
    )
    _require_memory_capacity(envelope, required)


def _maximum_zone_grid_cells(*, envelope: ResourceEnvelopeV1, baseline_cell_count: int) -> int:
    """Keep the retained diff and full-zone masks within the same memory ceiling."""

    available_bytes = (
        envelope.max_memory_bytes
        - baseline_cell_count * _DIFF_RESULT_BYTES_PER_PIXEL
        - _VOLUME_ZONE_WORKING_BYTES
    )
    if available_bytes < _VOLUME_ZONE_BYTES_PER_CELL:
        raise MeasurementAlgorithmError("RESOURCE_LIMIT_EXCEEDED")
    return min(envelope.max_pixels, available_bytes // _VOLUME_ZONE_BYTES_PER_CELL)


def _require_contained_dsm(
    dataset: rasterio.io.DatasetReader,
    *,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
) -> None:
    watchdog.check()
    if (
        dataset.driver != "GTiff"
        or dataset.subdatasets
        or dataset.count != 1
        or dataset.dtypes not in {("float32",), ("float64",)}
        or dataset.width <= 0
        or dataset.height <= 0
        or dataset.width * dataset.height > envelope.max_pixels
        or dataset.count > envelope.max_bands
        or dataset.scales != (1.0,)
        or dataset.offsets != (0.0,)
        or dataset.transform.is_degenerate
        or not all(math.isfinite(value) for value in tuple(dataset.transform)[:6])
    ):
        raise MeasurementAlgorithmError("SECONDARY_DSM_UNSUPPORTED")
    gcps, _ = dataset.gcps
    if gcps or dataset.tags(ns="GEOLOCATION"):
        raise MeasurementAlgorithmError("SECONDARY_DSM_UNSUPPORTED")


def _read_valid_dsm(
    dataset: rasterio.io.DatasetReader, *, watchdog: MeasurementWatchdogV2
) -> tuple[np.ndarray[Any, np.dtype[np.float64]], np.ndarray[Any, np.dtype[np.bool_]]]:
    values = np.empty((dataset.height, dataset.width), dtype=np.float64)
    valid = np.zeros((dataset.height, dataset.width), dtype=np.bool_)
    for _, window in dataset.block_windows(1):
        watchdog.check()
        raw = dataset.read(1, window=window, masked=False).astype(np.float64)
        mask = dataset.read_masks(1, window=window) == 255
        nodata = dataset.nodata
        if nodata is not None:
            if math.isnan(float(nodata)):
                mask &= ~np.isnan(raw)
            else:
                mask &= raw != float(nodata)
        if not np.all(np.isfinite(raw[mask])):
            raise MeasurementAlgorithmError("UNMASKED_NONFINITE_SAMPLE")
        row = slice(int(window.row_off), int(window.row_off + window.height))
        col = slice(int(window.col_off), int(window.col_off + window.width))
        values[row, col] = raw
        valid[row, col] = mask & np.isfinite(raw)
    return values, valid


def _observed_dsm_references(
    dataset: rasterio.io.DatasetReader,
) -> tuple[str, str, str | None]:
    if dataset.crs is None or not dataset.crs.to_wkt():
        raise MeasurementAlgorithmError("SECONDARY_DSM_UNSUPPORTED")
    embedded = CRS.from_user_input(dataset.crs.to_wkt())
    if embedded.is_compound:
        horizontal = [
            item for item in embedded.sub_crs_list if item.is_projected or item.is_geographic
        ]
        vertical = [item for item in embedded.sub_crs_list if item.is_vertical]
        if len(horizontal) != 1 or len(vertical) != 1:
            raise MeasurementAlgorithmError("SECONDARY_DSM_UNSUPPORTED")
        vertical_crs = vertical[0]
        vertical_code = vertical_crs.to_epsg()
        if (
            vertical_code is None
            or len(vertical_crs.axis_info) != 1
            or vertical_crs.axis_info[0].unit_name.lower() not in {"metre", "meter"}
        ):
            raise MeasurementAlgorithmError("SECONDARY_DSM_UNSUPPORTED")
        vertical_digest = _vertical_digest(
            ObservedVerticalReferenceV1(identifier=f"EPSG:{vertical_code}", basis=vertical_crs.name)
        )
        horizontal_crs = horizontal[0]
    else:
        horizontal_crs = embedded
        vertical_digest = None
    code = horizontal_crs.to_epsg()
    if code is None:
        raise MeasurementAlgorithmError("SECONDARY_DSM_UNSUPPORTED")
    resolved = CRS.from_epsg(code)
    if not horizontal_crs.equals(resolved):
        raise MeasurementAlgorithmError("SECONDARY_DSM_UNSUPPORTED")
    crs = assert_supported_project_crs(f"EPSG:{code}")
    wkt = resolved.to_wkt(version="WKT2_2019", pretty=False, output_axis_rule=True)
    return crs, _text_digest(wkt), vertical_digest


def _validated_epoch_rmses(request: MeasurementLaunchRequestV2) -> tuple[float, float] | None:
    records = request.volume_evidence_records
    if not records:
        return None
    if len(records) != 2 or request.volume_request is None:
        raise MeasurementAlgorithmError("VOLUME_EVIDENCE_BINDING_MISMATCH")
    rmses: list[float] = []
    for record, binding in zip(
        records,
        (request.volume_request.baseline, request.volume_request.current),
        strict=True,
    ):
        if (
            record.subject_digest != binding.subject.canonical_digest()
            or record.target_dsm_observed_sha256 != binding.observed_sha256
            or record.policy_digest != request.validation_policy.policy_digest
        ):
            raise MeasurementAlgorithmError("VOLUME_EVIDENCE_BINDING_MISMATCH")
        payload = record.measurement_payload
        if record.core_verdict is not EvidenceCoreVerdict.VALIDATED or payload is None:
            return None
        rmses.append(payload.rmse_m)
    return rmses[0], rmses[1]


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


def _vertical_digest(reference: ObservedVerticalReferenceV1 | None) -> str | None:
    if reference is None:
        return None
    return (
        "sha256:"
        + hashlib.sha256(
            canonical_json_bytes(reference.model_dump(by_alias=True, mode="json"))
        ).hexdigest()
    )


def _text_digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _watchdog_cancelled(watchdog: MeasurementWatchdogV2) -> bool:
    watchdog.check()
    return False


__all__ = [
    "MeasurementAlgorithmError",
    "MeasurementAlgorithmIncomplete",
    "MeasurementWatchdogV2",
    "ObservedDsmV2",
    "OwnedSecondaryV2",
    "align_masked_dsm_difference",
    "inspect_owned_secondary_dsm",
    "inspect_primary_dsm",
    "measure_checkpoint_aggregate",
    "measure_relative_volume_aggregate",
    "verify_owned_secondary_fd",
]
