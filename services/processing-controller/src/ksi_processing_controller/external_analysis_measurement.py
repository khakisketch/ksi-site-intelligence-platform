"""Unmounted V2 fixed-profile relative-volume measurement over owned DSM bytes.

This callable is deliberately not a daemon, transport handler, V1 protocol
adapter or public surface.  Core later owns execution lifecycle; the worker
only consumes an already fenced attempt and returns one sealed report or a
sealed typed failure.
"""

from __future__ import annotations

import base64
import hashlib
import math
import os
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from ksi_change_detection.external_volume import (
    ExternalVolumeMeasurementError,
    measure_fixed_profile_external_volume_zone,
)
from ksi_event_contracts.external_relative_volume_analysis import CalculationIdentityV2
from ksi_event_contracts.external_relative_volume_calculation import (
    AnalysisExecutionAttemptV2,
    RelativeVolumeCalculationFailureV2,
    RelativeVolumeCalculationReportV2,
    RelativeVolumeCoverageWitnessV2,
    RelativeVolumeMetricsV2,
    RelativeVolumeNumericResultV2,
)

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

_READ_CHUNK_BYTES = 1024 * 1024


class _CalculationInputError(RuntimeError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _failure(
    *,
    attempt: AnalysisExecutionAttemptV2,
    report_id: str,
    reason: str,
    failed_at: datetime,
) -> RelativeVolumeCalculationFailureV2:
    failure_id = "failure-" + hashlib.sha256(report_id.encode("utf-8")).hexdigest()[:32]
    return RelativeVolumeCalculationFailureV2(
        failure_id=failure_id,
        attempt=attempt,
        attempt_digest=attempt.canonical_digest(),
        reason_code=reason,
        failed_at=failed_at,
    ).sealed()


@contextmanager
def _owned_snapshot(
    path: Path,
    *,
    expected_size_bytes: int,
    expected_sha256: str,
    envelope_max_bytes: int,
    watchdog: MeasurementWatchdogV2,
    mismatch_reason: str,
) -> Iterator[OwnedSecondaryV2]:
    """Copy a trusted regular source once into an unlinked private descriptor.

    The same anonymous bytes are hashed, parsed and measured through
    ``/proc/self/fd``.  A mutable pathname is never checked then reopened.
    """
    if expected_size_bytes <= 0 or expected_size_bytes > envelope_max_bytes:
        raise _CalculationInputError("RESOURCE_LIMIT_EXCEEDED")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        source_fd = os.open(path, flags)
    except OSError as exc:
        raise _CalculationInputError(mismatch_reason) from exc
    try:
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size != expected_size_bytes:
            raise _CalculationInputError(mismatch_reason)
        with tempfile.TemporaryFile(mode="w+b") as snapshot:
            digest = hashlib.sha256()
            copied = 0
            while copied < expected_size_bytes:
                watchdog.check()
                try:
                    chunk = os.read(source_fd, min(_READ_CHUNK_BYTES, expected_size_bytes - copied))
                except OSError as exc:
                    raise _CalculationInputError(mismatch_reason) from exc
                if not chunk:
                    raise _CalculationInputError(mismatch_reason)
                snapshot.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
            # A source that grows after its expected bytes is also not the
            # sealed artifact; reject rather than accepting a prefix.
            try:
                if os.read(source_fd, 1):
                    raise _CalculationInputError(mismatch_reason)
            except OSError as exc:
                raise _CalculationInputError(mismatch_reason) from exc
            actual_sha256 = "sha256:" + digest.hexdigest()
            snapshot.flush()
            snapshot_stat = os.fstat(snapshot.fileno())
            if (
                not stat.S_ISREG(snapshot_stat.st_mode)
                or snapshot_stat.st_nlink != 0
                or snapshot_stat.st_size != expected_size_bytes
                or actual_sha256 != expected_sha256
            ):
                raise _CalculationInputError(mismatch_reason)
            snapshot.seek(0)
            yield OwnedSecondaryV2(
                fd=snapshot.fileno(),
                size_bytes=expected_size_bytes,
                sha256=actual_sha256,
            )
    finally:
        os.close(source_fd)


def _affine_tuple(path: Path) -> tuple[float, float, float, float, float, float]:
    try:
        with rasterio.open(path, "r", driver="GTiff") as dataset:
            affine = dataset.transform
    except (OSError, rasterio.errors.RasterioError, ValueError) as exc:
        raise _CalculationInputError("VOLUME_DSM_ALIGNMENT_FAILED") from exc
    values = (affine.a, affine.b, affine.c, affine.d, affine.e, affine.f)
    if not all(math.isfinite(value) for value in values):
        raise _CalculationInputError("VOLUME_DSM_ALIGNMENT_FAILED")
    return values


def _pack_mask(mask: np.ndarray[tuple[int, ...], np.dtype[np.bool_]]) -> str:
    packed = np.packbits(mask.reshape(-1), bitorder="big").tobytes()
    return base64.b64encode(packed).decode("ascii")


def _assert_attempt_identity(
    attempt: AnalysisExecutionAttemptV2, calculation_identity: CalculationIdentityV2
) -> None:
    if (
        calculation_identity.calculation_identity_digest is None
        or calculation_identity.calculation_identity_digest
        != calculation_identity.canonical_digest()
        or attempt.authorization.calculation_identity_digest
        != calculation_identity.calculation_identity_digest
    ):
        raise _CalculationInputError("EXECUTION_BINDING_MISMATCH")
    baseline = calculation_identity.baseline_transform
    if baseline[1] != 0.0 or baseline[3] != 0.0 or baseline[0] <= 0.0 or baseline[4] >= 0.0:
        raise _CalculationInputError("BASELINE_AFFINE_NOT_NORTH_UP")


def _assert_observed_dsm_context(
    *,
    observed_crs_digest: str,
    observed_vertical_reference_digest: str | None,
    transform: tuple[float, float, float, float, float, float],
    expected_crs_digest: str,
    expected_vertical_reference_digest: str,
    expected_transform: tuple[float, float, float, float, float, float],
    mismatch_reason: str,
) -> None:
    if (
        observed_crs_digest != expected_crs_digest
        or observed_vertical_reference_digest != expected_vertical_reference_digest
        or transform != expected_transform
    ):
        raise _CalculationInputError(mismatch_reason)


def _require_combined_input_workspace(
    *, baseline_size_bytes: int, current_size_bytes: int, envelope_max_workspace_bytes: int
) -> None:
    """Reject two concurrent immutable snapshots before either is allocated."""
    if (
        baseline_size_bytes <= 0
        or current_size_bytes <= 0
        or baseline_size_bytes + current_size_bytes > envelope_max_workspace_bytes
    ):
        raise _CalculationInputError("RESOURCE_LIMIT_EXCEEDED")


def _require_work_area_vertex_budget(
    polygon: dict[str, Any], *, maximum_vertices: int
) -> None:
    """Bound the already-sealed polygon before any rasterization allocation."""
    coordinates = polygon.get("coordinates")
    if not isinstance(coordinates, list):
        raise _CalculationInputError("RESOURCE_LIMIT_EXCEEDED")
    vertex_count = 0
    for ring in coordinates:
        if not isinstance(ring, list):
            raise _CalculationInputError("RESOURCE_LIMIT_EXCEEDED")
        vertex_count += len(ring)
        if vertex_count > maximum_vertices:
            raise _CalculationInputError("RESOURCE_LIMIT_EXCEEDED")


def measure_external_relative_volume_v2(
    *,
    attempt: AnalysisExecutionAttemptV2,
    calculation_identity: CalculationIdentityV2,
    baseline_path: Path,
    current_path: Path,
    report_id: str,
    computed_at: datetime,
    reported_at: datetime,
    maximum_wall_seconds: float | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> RelativeVolumeCalculationReportV2 | RelativeVolumeCalculationFailureV2:
    """Measure exactly one sealed V2 identity without launching a worker runtime."""
    try:
        _assert_attempt_identity(attempt, calculation_identity)
        if reported_at > attempt.lease_expires_at:
            raise _CalculationInputError("STALE_LEASE")
        envelope = attempt.authorization.resource_envelope
        if maximum_wall_seconds is not None:
            if (
                isinstance(maximum_wall_seconds, bool)
                or not isinstance(maximum_wall_seconds, (int, float))
                or not math.isfinite(maximum_wall_seconds)
                or maximum_wall_seconds <= 0
            ):
                raise _CalculationInputError("RESOURCE_LIMIT_EXCEEDED")
            maximum_wall_seconds = min(maximum_wall_seconds, envelope.max_deadline_seconds)
        if is_cancelled is not None and not callable(is_cancelled):
            raise _CalculationInputError("RESOURCE_LIMIT_EXCEEDED")
        watchdog = MeasurementWatchdogV2.from_envelope(
            envelope,
            maximum_wall_seconds=maximum_wall_seconds,
            is_cancelled=is_cancelled,
        )
        _require_combined_input_workspace(
            baseline_size_bytes=calculation_identity.baseline_dsm_observed_size_bytes,
            current_size_bytes=calculation_identity.current_dsm_observed_size_bytes,
            envelope_max_workspace_bytes=envelope.max_workspace_bytes,
        )
        with (
            _owned_snapshot(
                baseline_path,
                expected_size_bytes=calculation_identity.baseline_dsm_observed_size_bytes,
                expected_sha256=calculation_identity.baseline_dsm_observed_sha256,
                envelope_max_bytes=min(envelope.max_input_bytes, envelope.max_streamed_bytes),
                watchdog=watchdog,
                mismatch_reason="BASELINE_DSM_BYTES_MISMATCH",
            ) as baseline,
            _owned_snapshot(
                current_path,
                expected_size_bytes=calculation_identity.current_dsm_observed_size_bytes,
                expected_sha256=calculation_identity.current_dsm_observed_sha256,
                envelope_max_bytes=min(envelope.max_input_bytes, envelope.max_streamed_bytes),
                watchdog=watchdog,
                mismatch_reason="CURRENT_DSM_BYTES_MISMATCH",
            ) as current,
        ):
            baseline_preflight = preflight_owned_secondary_dsm_memory(
                baseline, envelope=envelope, watchdog=watchdog
            )
            current_preflight = preflight_owned_secondary_dsm_memory(
                current, envelope=envelope, watchdog=watchdog
            )
            preflight_volume_measurement_memory(
                baseline=baseline_preflight,
                current=current_preflight,
                envelope=envelope,
            )
            observed_baseline = inspect_owned_secondary_dsm(
                baseline, envelope=envelope, watchdog=watchdog
            )
            observed_current = inspect_owned_secondary_dsm(
                current, envelope=envelope, watchdog=watchdog
            )
            _assert_observed_dsm_context(
                observed_crs_digest=observed_baseline.observed_crs_digest,
                observed_vertical_reference_digest=observed_baseline.observed_vertical_reference_digest,
                transform=_affine_tuple(baseline.proc_path),
                expected_crs_digest=calculation_identity.baseline_observed_crs_digest,
                expected_vertical_reference_digest=(
                    calculation_identity.baseline_vertical_reference_digest
                ),
                expected_transform=calculation_identity.baseline_transform,
                mismatch_reason="BASELINE_DSM_CONTEXT_MISMATCH",
            )
            _assert_observed_dsm_context(
                observed_crs_digest=observed_current.observed_crs_digest,
                observed_vertical_reference_digest=observed_current.observed_vertical_reference_digest,
                transform=_affine_tuple(current.proc_path),
                expected_crs_digest=calculation_identity.current_observed_crs_digest,
                expected_vertical_reference_digest=(
                    calculation_identity.current_vertical_reference_digest
                ),
                expected_transform=calculation_identity.current_transform,
                mismatch_reason="CURRENT_DSM_CONTEXT_MISMATCH",
            )
            _require_work_area_vertex_budget(
                calculation_identity.work_area_polygon,
                maximum_vertices=envelope.max_geometry_vertices,
            )
            diff = align_masked_dsm_difference(
                baseline_path=baseline.proc_path,
                current_path=current.proc_path,
                envelope=envelope,
                watchdog=watchdog,
            )
            measurement = measure_fixed_profile_external_volume_zone(
                diff,
                calculation_identity.work_area_polygon,
                zone_id=calculation_identity.work_area_id,
                from_crs=calculation_identity.work_area_crs,
                maximum_zone_grid_cells=maximum_fixed_profile_zone_grid_cells(
                    envelope=envelope,
                    baseline_cell_count=(
                        baseline_preflight.width * baseline_preflight.height
                    ),
                ),
            )
            if isinstance(measurement, ExternalVolumeMeasurementError):
                raise _CalculationInputError(measurement.reason.value)
            watchdog.check()
            coverage = RelativeVolumeCoverageWitnessV2(
                rows=int(measurement.selected_mask.shape[0]),
                columns=int(measurement.selected_mask.shape[1]),
                row_offset=measurement.row_offset,
                column_offset=measurement.column_offset,
                selected_mask_b64=_pack_mask(measurement.selected_mask),
                common_valid_mask_b64=_pack_mask(measurement.common_valid_mask),
                unavailable_mask_b64=_pack_mask(measurement.unavailable_mask),
                threshold_excluded_mask_b64=_pack_mask(
                    np.zeros(measurement.selected_mask.shape, dtype=np.bool_)
                ),
                selected_cell_count=measurement.metrics.zone_cell_count,
                common_valid_cell_count=measurement.metrics.common_valid_cell_count,
                unavailable_cell_count=(
                    measurement.metrics.zone_cell_count
                    - measurement.metrics.common_valid_cell_count
                ),
                threshold_excluded_cell_count=0,
                cell_area_m2=abs(
                    calculation_identity.baseline_transform[0]
                    * calculation_identity.baseline_transform[4]
                    - calculation_identity.baseline_transform[1]
                    * calculation_identity.baseline_transform[3]
                ),
                selected_area_m2=measurement.metrics.zone_area_m2,
                common_valid_area_m2=measurement.metrics.measured_area_m2,
                bounds=measurement.bounds,
            ).sealed()
            calculation_identity_digest = calculation_identity.calculation_identity_digest
            assert calculation_identity_digest is not None
            numeric = RelativeVolumeNumericResultV2(
                calculation_identity_digest=calculation_identity_digest,
                profile_digest=calculation_identity.policy.profile_digest,
                metrics=RelativeVolumeMetricsV2(
                    cut_m3=measurement.metrics.cut_m3,
                    fill_m3=measurement.metrics.fill_m3,
                    net_m3=measurement.metrics.net_m3,
                    threshold_m=0.0,
                    uncertainty_m3=None,
                ),
                coverage=coverage,
            ).sealed()
            report = RelativeVolumeCalculationReportV2(
                report_id=report_id,
                attempt=attempt,
                attempt_digest=attempt.canonical_digest(),
                numeric_result=numeric,
                numeric_result_identity_digest=numeric.canonical_digest(),
                computed_at=computed_at,
                reported_at=reported_at,
            ).sealed()
            if (
                len(report.model_dump_json(by_alias=True).encode("utf-8"))
                > envelope.max_output_bytes
            ):
                raise _CalculationInputError("RESOURCE_LIMIT_EXCEEDED")
            return report
    except MeasurementAlgorithmIncomplete:
        return _failure(
            attempt=attempt,
            report_id=report_id,
            reason="MEASUREMENT_INCOMPLETE",
            failed_at=reported_at,
        )
    except MeasurementAlgorithmError as exc:
        return _failure(
            attempt=attempt,
            report_id=report_id,
            reason=exc.reason,
            failed_at=reported_at,
        )
    except _CalculationInputError as exc:
        return _failure(
            attempt=attempt,
            report_id=report_id,
            reason=exc.reason,
            failed_at=reported_at,
        )


__all__ = ["measure_external_relative_volume_v2"]
