"""Late-export native re-measurement inside the verified contained runtime.

This is a worker measurement primitive, not publication, authorization, or a
route. It reproduces the sealed V2 numeric bytes from two already-downloaded
DSM files WITHOUT inventing a new V2 analysis attempt, admission, or
authorization:

- The caller supplies the exact sealed ``CalculationIdentityV2`` plus its
  sealed ``RelativeVolumeNumericResultV2`` taken from the Core-issued
  late-export input (the old COMPLETED report, never a live fence).
- Both DSM files must already be staged locally as sealed regular files; this
  module snapshots each once into an unlinked private descriptor, verifies
  byte identity (sha/size) against the identity, and runs the owned native
  conformance already proven by the V2 lane: bounded TIFF preflight, the
  retained DSM reader (``inspect_owned_secondary_dsm``), CRS/vertical/
  transform context checks, and the shared align algorithm
  (``align_masked_dsm_difference``).
- The aligned diff plus the ORIGINAL numeric result are handed to the owned
  ``prepare_external_delta_raster_v2`` encoder, which verifies the exact
  grid, selected/common-valid coverage, finite metrics, and NaN handling
  before any native write. The old numeric report is never mutated; a
  revalidation mismatch fails closed with no publishable bytes.
- The output fd lives only inside the returned context and must not be
  journaled as a path. Cancellation/currentness loss at any stage aborts
  without bytes.

The caller must run inside its approved native resource boundary and supply a
live lease/currentness watchdog plus explicit resource caps. Local generated
tests prove bytes and protocol, never an OS sandbox claim.
"""

from __future__ import annotations

import hashlib
import math
import os
import stat
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
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
    MaskedVolumeCalculationReportV3,
)
from ksi_event_contracts.external_relative_volume_analysis import CalculationIdentityV2
from ksi_event_contracts.external_relative_volume_calculation import (
    RelativeVolumeNumericResultV2,
)
from ksi_geo_spatial.crs import assert_same_crs, normalise_crs

from ksi_processing_controller.external_delta_raster import (
    MeasuredDeltaRasterV1,
    prepare_external_delta_raster_v2,
    prepare_external_delta_raster_v3,
)
from ksi_processing_controller.external_masked_volume_measurement import (
    MaskedVolumeMeasurementError,
    _decode_owned_mask,
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


class ReproductionMeasurementError(ValueError):
    """A late-export re-measurement cannot establish publishable bytes."""


def _require_watchdog(watchdog: object) -> MeasurementWatchdogV2:
    if not isinstance(watchdog, MeasurementWatchdogV2) or isinstance(watchdog, bool):
        raise ReproductionMeasurementError("RESOURCE_LIMIT_EXCEEDED")
    return watchdog


def _require_envelope(envelope: object) -> ResourceEnvelopeV1:
    if not isinstance(envelope, ResourceEnvelopeV1):
        raise ReproductionMeasurementError("RESOURCE_LIMIT_EXCEEDED")
    if (
        envelope.resource_envelope_digest is None
        or envelope.resource_envelope_digest != envelope.canonical_digest()
    ):
        raise ReproductionMeasurementError("RESOURCE_LIMIT_EXCEEDED")
    return envelope


def _require_limits(maximum_output_bytes: int, maximum_grid_cells: int) -> None:
    for name, value in (
        ("maximum_output_bytes", maximum_output_bytes),
        ("maximum_grid_cells", maximum_grid_cells),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ReproductionMeasurementError(f"explicit {name} is required")


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
    if expected_size_bytes <= 0 or expected_size_bytes > envelope_max_bytes:
        raise ReproductionMeasurementError("RESOURCE_LIMIT_EXCEEDED")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        source_fd = os.open(path, flags)
    except OSError as exc:
        raise ReproductionMeasurementError(mismatch_reason) from exc
    try:
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size != expected_size_bytes:
            raise ReproductionMeasurementError(mismatch_reason)
        with tempfile.TemporaryFile(mode="w+b") as snapshot:
            digest = hashlib.sha256()
            copied = 0
            while copied < expected_size_bytes:
                watchdog.check()
                try:
                    chunk = os.read(source_fd, min(_READ_CHUNK_BYTES, expected_size_bytes - copied))
                except OSError as exc:
                    raise ReproductionMeasurementError(mismatch_reason) from exc
                if not chunk:
                    raise ReproductionMeasurementError(mismatch_reason)
                snapshot.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
            try:
                if os.read(source_fd, 1):
                    raise ReproductionMeasurementError(mismatch_reason)
            except OSError as exc:
                raise ReproductionMeasurementError(mismatch_reason) from exc
            actual = "sha256:" + digest.hexdigest()
            snapshot.flush()
            snapshot_stat = os.fstat(snapshot.fileno())
            if (
                not stat.S_ISREG(snapshot_stat.st_mode)
                or snapshot_stat.st_nlink != 0
                or snapshot_stat.st_size != expected_size_bytes
                or actual != expected_sha256
            ):
                raise ReproductionMeasurementError(mismatch_reason)
            snapshot.seek(0)
            yield OwnedSecondaryV2(
                fd=snapshot.fileno(), size_bytes=expected_size_bytes, sha256=actual
            )
    finally:
        os.close(source_fd)


def _assert_identity_context(
    *,
    observed_crs_digest: str,
    observed_vertical_digest: str | None,
    expected_crs_digest: str,
    expected_vertical_digest: str,
    mismatch_reason: str,
) -> None:
    if (
        observed_crs_digest != expected_crs_digest
        or observed_vertical_digest != expected_vertical_digest
    ):
        raise ReproductionMeasurementError(mismatch_reason)


@contextmanager
def reproduce_external_delta_raster_v2(
    *,
    calculation_identity: CalculationIdentityV2,
    numeric_result: RelativeVolumeNumericResultV2,
    baseline_path: Path | str,
    current_path: Path | str,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
    maximum_output_bytes: int,
    maximum_grid_cells: int,
    check_current: Callable[[], None],
) -> Iterator[MeasuredDeltaRasterV1]:
    """Reproduce the sealed V2 delta bytes from two staged DSM files.

    The late-export job fence authorizes ONLY this re-measurement. No V2
    attempt is consumed, renewed, or reported here; the old COMPLETED numeric
    state is never rewritten. Any stale lease, expired capability, revoked
    source, byte mismatch, grid drift, metric drift, or cancelled guard fails
    closed with no output fd.
    """
    envelope = _require_envelope(envelope)
    watchdog = _require_watchdog(watchdog)
    _require_limits(maximum_output_bytes, maximum_grid_cells)
    if not callable(check_current):
        raise ReproductionMeasurementError("an explicit currentness guard is required")
    check_current()
    watchdog.check()
    try:
        identity = CalculationIdentityV2.model_validate(calculation_identity.model_dump())
        numeric = RelativeVolumeNumericResultV2.model_validate(numeric_result.model_dump())
    except Exception as exc:
        raise ReproductionMeasurementError("SOURCE_IDENTITY_MISMATCH") from exc
    if (
        identity.calculation_identity_digest is None
        or identity.calculation_identity_digest != identity.canonical_digest()
    ):
        raise ReproductionMeasurementError("SOURCE_IDENTITY_MISMATCH")
    if (
        numeric.numeric_result_identity_digest is None
        or numeric.numeric_result_identity_digest != numeric.canonical_digest()
        or numeric.calculation_identity_digest != identity.calculation_identity_digest
        or numeric.profile_digest != identity.policy.profile_digest
    ):
        raise ReproductionMeasurementError("SOURCE_NUMERIC_MISMATCH")
    if numeric.coverage.coverage_witness_digest is None:
        raise ReproductionMeasurementError("SOURCE_NUMERIC_MISMATCH")
    baseline_transform = identity.baseline_transform
    if (
        baseline_transform[1] != 0.0
        or baseline_transform[3] != 0.0
        or baseline_transform[0] <= 0.0
        or baseline_transform[4] >= 0.0
    ):
        raise ReproductionMeasurementError("SOURCE_IDENTITY_MISMATCH")
    baseline_p = Path(baseline_path)
    current_p = Path(current_path)
    combined = identity.baseline_dsm_observed_size_bytes + identity.current_dsm_observed_size_bytes
    if combined > envelope.max_workspace_bytes:
        raise ReproductionMeasurementError("RESOURCE_LIMIT_EXCEEDED")
    check_current()
    try:
        with (
            _owned_snapshot(
                baseline_p,
                expected_size_bytes=identity.baseline_dsm_observed_size_bytes,
                expected_sha256=identity.baseline_dsm_observed_sha256,
                envelope_max_bytes=min(envelope.max_input_bytes, envelope.max_streamed_bytes),
                watchdog=watchdog,
                mismatch_reason="BASELINE_DSM_BYTES_MISMATCH",
            ) as baseline,
            _owned_snapshot(
                current_p,
                expected_size_bytes=identity.current_dsm_observed_size_bytes,
                expected_sha256=identity.current_dsm_observed_sha256,
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
                baseline=baseline_preflight, current=current_preflight, envelope=envelope
            )
            check_current()
            observed_baseline = inspect_owned_secondary_dsm(
                baseline, envelope=envelope, watchdog=watchdog
            )
            observed_current = inspect_owned_secondary_dsm(
                current, envelope=envelope, watchdog=watchdog
            )
            import rasterio

            def _affine_tuple(path: Path) -> tuple[float, ...]:
                try:
                    with rasterio.open(path, "r", driver="GTiff") as dataset:
                        affine = dataset.transform
                except Exception as exc:
                    raise ReproductionMeasurementError("VOLUME_DSM_ALIGNMENT_FAILED") from exc
                values = (affine.a, affine.b, affine.c, affine.d, affine.e, affine.f)
                if not all(math.isfinite(v) for v in values):
                    raise ReproductionMeasurementError("VOLUME_DSM_ALIGNMENT_FAILED")
                return values

            if _affine_tuple(baseline.proc_path) != tuple(identity.baseline_transform):
                raise ReproductionMeasurementError("BASELINE_DSM_CONTEXT_MISMATCH")
            if _affine_tuple(current.proc_path) != tuple(identity.current_transform):
                raise ReproductionMeasurementError("CURRENT_DSM_CONTEXT_MISMATCH")
            _assert_identity_context(
                observed_crs_digest=observed_baseline.observed_crs_digest,
                observed_vertical_digest=observed_baseline.observed_vertical_reference_digest,
                expected_crs_digest=identity.baseline_observed_crs_digest,
                expected_vertical_digest=identity.baseline_vertical_reference_digest,
                mismatch_reason="BASELINE_DSM_CONTEXT_MISMATCH",
            )
            _assert_identity_context(
                observed_crs_digest=observed_current.observed_crs_digest,
                observed_vertical_digest=observed_current.observed_vertical_reference_digest,
                expected_crs_digest=identity.current_observed_crs_digest,
                expected_vertical_digest=identity.current_vertical_reference_digest,
                mismatch_reason="CURRENT_DSM_CONTEXT_MISMATCH",
            )
            check_current()
            try:
                diff = align_masked_dsm_difference(
                    baseline_path=baseline.proc_path,
                    current_path=current.proc_path,
                    envelope=envelope,
                    watchdog=watchdog,
                )
            except MeasurementAlgorithmIncomplete:
                raise
            except MeasurementAlgorithmError as exc:
                raise ReproductionMeasurementError(exc.reason) from exc
            check_current()
            watchdog.check()
            # The owned encoder re-verifies the exact grid, selected/
            # common-valid coverage, finite metrics, and NaN handling against
            # the ORIGINAL numeric result. No new numeric is computed here.
            try:
                with prepare_external_delta_raster_v2(
                    diff=diff,
                    numeric_result=numeric,
                    maximum_output_bytes=maximum_output_bytes,
                    maximum_grid_cells=maximum_grid_cells,
                    check_current=check_current,
                ) as measured:
                    yield measured
            except MeasurementAlgorithmIncomplete:
                raise
            except Exception as exc:
                if isinstance(exc, ReproductionMeasurementError):
                    raise
                raise ReproductionMeasurementError("DELTA_RASTER_OUTPUT_UNAVAILABLE") from exc
    except MeasurementAlgorithmIncomplete:
        raise
    except ReproductionMeasurementError:
        raise
    except Exception as exc:
        raise ReproductionMeasurementError("DELTA_REPRODUCTION_FAILED") from exc


__all__ = [
    "ReproductionMeasurementError",
    "reproduce_external_delta_raster_v2",
    "reproduce_masked_delta_raster_v3",
]


def _decode_b64_mask(raw: str, *, rows: int, columns: int) -> np.ndarray[Any, Any]:
    """Decode one lossless coverage bitmask exactly as the sealed model does."""
    import base64

    packed = base64.b64decode(raw, validate=True)
    cells = rows * columns
    if len(packed) != (cells + 7) // 8:
        raise ReproductionMeasurementError("SOURCE_NUMERIC_MISMATCH")
    return (
        np.unpackbits(np.frombuffer(packed, dtype=np.uint8), bitorder="big")[:cells]
        .reshape(rows, columns)
        .astype(np.bool_)
    )


@contextmanager
def reproduce_masked_delta_raster_v3(
    *,
    masked_identity: MaskedCalculationIdentityV3,
    report: MaskedVolumeCalculationReportV3,
    baseline_path: Path | str,
    current_path: Path | str,
    mask_path: Path | str,
    envelope: ResourceEnvelopeV1,
    watchdog: MeasurementWatchdogV2,
    maximum_output_bytes: int,
    maximum_grid_cells: int,
    check_current: Callable[[], None],
) -> Iterator[MeasuredDeltaRasterV1]:
    """Reproduce the sealed V3 delta bytes from three staged sealed files.

    The late-export job fence authorizes ONLY this re-measurement. No masked
    attempt is consumed, renewed, or reported here, no new numeric identity
    is minted, and the old COMPLETED masked report is never rewritten. The
    pure zone math (``measure_masked_external_volume_zone``) is re-run from
    the actual staged bytes and compared field-for-field against the ORIGINAL
    report — metrics, all five coverage masks, counts, cell area, bounds, and
    offsets — before the owned ``prepare_external_delta_raster_v3`` encoder
    re-verifies the array metrics and writes the private output. Any stale
    lease, expired capability, revoked source, byte mismatch, mask NoData,
    grid drift, metric drift, or cancelled guard fails closed with no output
    fd. The mask is never resampled: it must match the baseline grid exactly.
    """
    import numpy as np
    from rasterio.transform import Affine as _Affine

    envelope = _require_envelope(envelope)
    watchdog = _require_watchdog(watchdog)
    _require_limits(maximum_output_bytes, maximum_grid_cells)
    if not callable(check_current):
        raise ReproductionMeasurementError("an explicit currentness guard is required")
    check_current()
    watchdog.check()
    try:
        identity = MaskedCalculationIdentityV3.model_validate(masked_identity.model_dump())
        result = MaskedVolumeCalculationReportV3.model_validate(report.model_dump())
    except Exception as exc:
        raise ReproductionMeasurementError("SOURCE_IDENTITY_MISMATCH") from exc
    if (
        identity.masked_calculation_identity_digest is None
        or identity.masked_calculation_identity_digest != identity.canonical_digest()
    ):
        raise ReproductionMeasurementError("SOURCE_IDENTITY_MISMATCH")
    numeric = result.numeric_result
    if (
        result.report_digest is None
        or result.report_digest != result.canonical_digest()
        or result.masked_calculation_identity_digest != identity.canonical_digest()
        or numeric.numeric_result_identity_digest is None
        or numeric.numeric_result_identity_digest != numeric.canonical_digest()
        or numeric.masked_calculation_identity_digest != identity.canonical_digest()
        or numeric.masked_profile_digest != identity.masked_profile_digest
        or numeric.mask_binding_digest != identity.mask_binding_digest
    ):
        raise ReproductionMeasurementError("SOURCE_NUMERIC_MISMATCH")
    coverage = numeric.coverage
    if (
        coverage.coverage_witness_digest is None
        or coverage.coverage_witness_digest != coverage.canonical_digest()
    ):
        raise ReproductionMeasurementError("SOURCE_NUMERIC_MISMATCH")
    source = identity.source_calculation_identity
    binding: ExclusionMaskBindingV1 = identity.mask_binding
    baseline_transform = source.baseline_transform
    if (
        baseline_transform[1] != 0.0
        or baseline_transform[3] != 0.0
        or baseline_transform[0] <= 0.0
        or baseline_transform[4] >= 0.0
    ):
        raise ReproductionMeasurementError("SOURCE_IDENTITY_MISMATCH")
    baseline_p = Path(baseline_path)
    current_p = Path(current_path)
    mask_p = Path(mask_path)
    combined = (
        source.baseline_dsm_observed_size_bytes
        + source.current_dsm_observed_size_bytes
        + binding.observed_size_bytes
    )
    if combined > envelope.max_workspace_bytes:
        raise ReproductionMeasurementError("RESOURCE_LIMIT_EXCEEDED")
    check_current()
    try:
        with (
            _owned_snapshot(
                baseline_p,
                expected_size_bytes=source.baseline_dsm_observed_size_bytes,
                expected_sha256=source.baseline_dsm_observed_sha256,
                envelope_max_bytes=min(envelope.max_input_bytes, envelope.max_streamed_bytes),
                watchdog=watchdog,
                mismatch_reason="BASELINE_DSM_BYTES_MISMATCH",
            ) as baseline,
            _owned_snapshot(
                current_p,
                expected_size_bytes=source.current_dsm_observed_size_bytes,
                expected_sha256=source.current_dsm_observed_sha256,
                envelope_max_bytes=min(envelope.max_input_bytes, envelope.max_streamed_bytes),
                watchdog=watchdog,
                mismatch_reason="CURRENT_DSM_BYTES_MISMATCH",
            ) as current,
            _owned_snapshot(
                mask_p,
                expected_size_bytes=binding.observed_size_bytes,
                expected_sha256=binding.observed_sha256,
                envelope_max_bytes=min(envelope.max_input_bytes, envelope.max_streamed_bytes),
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
            check_current()
            observed_baseline = inspect_owned_secondary_dsm(
                baseline, envelope=envelope, watchdog=watchdog
            )
            observed_current = inspect_owned_secondary_dsm(
                current, envelope=envelope, watchdog=watchdog
            )
            import rasterio

            def _affine_tuple(path: Path) -> tuple[float, ...]:
                try:
                    with rasterio.open(path, "r", driver="GTiff") as dataset:
                        affine = dataset.transform
                except Exception as exc:
                    raise ReproductionMeasurementError("VOLUME_DSM_ALIGNMENT_FAILED") from exc
                values = (affine.a, affine.b, affine.c, affine.d, affine.e, affine.f)
                if not all(math.isfinite(v) for v in values):
                    raise ReproductionMeasurementError("VOLUME_DSM_ALIGNMENT_FAILED")
                return values

            if _affine_tuple(baseline.proc_path) != tuple(source.baseline_transform):
                raise ReproductionMeasurementError("BASELINE_DSM_CONTEXT_MISMATCH")
            if _affine_tuple(current.proc_path) != tuple(source.current_transform):
                raise ReproductionMeasurementError("CURRENT_DSM_CONTEXT_MISMATCH")
            if (
                observed_baseline.observed_crs_digest != source.baseline_observed_crs_digest
                or observed_current.observed_crs_digest != source.current_observed_crs_digest
            ):
                raise ReproductionMeasurementError("BASELINE_DSM_CONTEXT_MISMATCH")
            check_current()
            try:
                mask_array = _decode_owned_mask(
                    owned_mask,
                    binding=binding,
                    baseline_transform=_Affine(*source.baseline_transform),
                    baseline_crs=source.baseline_observed_crs_identifier,
                    envelope=envelope,
                    watchdog=watchdog,
                )
            except MaskedVolumeMeasurementError as exc:
                raise ReproductionMeasurementError(exc.reason) from exc
            try:
                diff = align_masked_dsm_difference(
                    baseline_path=baseline.proc_path,
                    current_path=current.proc_path,
                    envelope=envelope,
                    watchdog=watchdog,
                )
            except MeasurementAlgorithmIncomplete:
                raise
            except MeasurementAlgorithmError as exc:
                raise ReproductionMeasurementError(exc.reason) from exc
            check_current()
            watchdog.check()
            # Re-run the pure zone math from the actual staged bytes. The
            # result must equal the ORIGINAL report exactly; nothing here
            # mints a new numeric identity or authorizes any old attempt.
            rows, columns = coverage.rows, coverage.columns
            if (identity.grid_rows, identity.grid_columns) != (
                diff.diff_m.shape[0],
                diff.diff_m.shape[1],
            ):
                # The full baseline grid is the fixed measurement frame.
                raise ReproductionMeasurementError("SOURCE_IDENTITY_MISMATCH")
            if tuple(
                float(v)
                for v in (
                    diff.transform.a,
                    diff.transform.b,
                    diff.transform.c,
                    diff.transform.d,
                    diff.transform.e,
                    diff.transform.f,
                )
            ) != tuple(float(v) for v in source.baseline_transform):
                raise ReproductionMeasurementError("SOURCE_IDENTITY_MISMATCH")
            try:
                normalised_mask_crs = normalise_crs(binding.observed_crs_identifier)
                assert_same_crs(normalised_mask_crs, binding.observed_crs_identifier, diff.crs)
            except (AttributeError, TypeError, ValueError) as exc:
                raise ReproductionMeasurementError("MASK_BYTES_MISMATCH") from exc
            if mask_array.shape != diff.diff_m.shape:
                raise ReproductionMeasurementError("MASK_BYTES_MISMATCH")
            max_zone_cells = maximum_fixed_profile_zone_grid_cells(
                envelope=envelope,
                baseline_cell_count=diff.diff_m.shape[0] * diff.diff_m.shape[1],
            )
            try:
                measurement = measure_masked_external_volume_zone(
                    diff,
                    source.work_area_polygon,
                    zone_id=source.work_area_id,
                    from_crs=source.work_area_crs,
                    exclusion_mask=mask_array,
                    mask_crs=normalised_mask_crs,
                    mask_transform=_Affine(*source.baseline_transform),
                    maximum_zone_grid_cells=max_zone_cells,
                )
            except MeasurementAlgorithmIncomplete:
                raise
            except MeasurementAlgorithmError as exc:
                raise ReproductionMeasurementError(exc.reason) from exc
            if isinstance(measurement, MaskedExternalVolumeError):
                raise ReproductionMeasurementError(measurement.reason.value)
            check_current()
            watchdog.check()
            recomputed = {
                "cut": float(measurement.metrics.cut_m3),
                "fill": float(measurement.metrics.fill_m3),
                "net": float(measurement.metrics.net_m3),
            }
            if not all(
                math.isclose(
                    recomputed[name],
                    getattr(numeric.metrics, f"{name}_m3"),
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
                for name in ("cut", "fill", "net")
            ):
                raise ReproductionMeasurementError("SOURCE_NUMERIC_MISMATCH")
            if (
                measurement.row_offset != coverage.row_offset
                or measurement.column_offset != coverage.column_offset
                or measurement.original_selected_cell_count != coverage.original_selected_cell_count
                or measurement.mask_excluded_cell_count != coverage.mask_excluded_cell_count
                or measurement.effective_selected_cell_count
                != coverage.effective_selected_cell_count
                or measurement.common_valid_cell_count != coverage.common_valid_cell_count
            ):
                raise ReproductionMeasurementError("SOURCE_NUMERIC_MISMATCH")
            original_masks = {
                name: _decode_b64_mask(getattr(coverage, name), rows=rows, columns=columns)
                for name in (
                    "original_selected_mask_b64",
                    "mask_excluded_mask_b64",
                    "effective_selected_mask_b64",
                    "common_valid_mask_b64",
                    "unavailable_mask_b64",
                )
            }
            recomputed_masks = (
                measurement.original_selected_mask,
                measurement.mask_excluded_mask,
                measurement.effective_selected_mask,
                measurement.common_valid_mask,
                measurement.unavailable_mask,
            )
            if not all(
                bool(np.array_equal(recomputed, original))
                for recomputed, original in zip(
                    recomputed_masks, original_masks.values(), strict=True
                )
            ):
                raise ReproductionMeasurementError("SOURCE_NUMERIC_MISMATCH")
            cell_area = float(
                measurement.metrics.zone_area_m2 / measurement.metrics.zone_cell_count
            )
            if not math.isfinite(cell_area) or cell_area <= 0.0:
                raise ReproductionMeasurementError("SOURCE_NUMERIC_MISMATCH")
            if not math.isclose(cell_area, coverage.cell_area_m2, rel_tol=1e-12, abs_tol=1e-12):
                raise ReproductionMeasurementError("SOURCE_NUMERIC_MISMATCH")
            if tuple(measurement.bounds) != tuple(coverage.bounds):
                raise ReproductionMeasurementError("SOURCE_NUMERIC_MISMATCH")
            delta_grid = measurement.delta_grid_m
            if (
                not isinstance(delta_grid, np.ndarray)
                or delta_grid.dtype != np.dtype(np.float64)
                or delta_grid.shape != (rows, columns)
                or np.ma.isMaskedArray(delta_grid)
            ):
                raise ReproductionMeasurementError("SOURCE_NUMERIC_MISMATCH")
            # The owned encoder re-verifies the array metrics against the
            # ORIGINAL report before any native write.
            try:
                with prepare_external_delta_raster_v3(
                    masked_identity=identity,
                    report=result,
                    delta_grid_m=delta_grid,
                    maximum_output_bytes=maximum_output_bytes,
                    maximum_grid_cells=maximum_grid_cells,
                    check_current=check_current,
                ) as measured:
                    yield measured
            except MeasurementAlgorithmIncomplete:
                raise
            except Exception as exc:
                if isinstance(exc, ReproductionMeasurementError):
                    raise
                raise ReproductionMeasurementError("DELTA_RASTER_OUTPUT_UNAVAILABLE") from exc
    except MeasurementAlgorithmIncomplete:
        raise
    except ReproductionMeasurementError:
        raise
    except Exception as exc:
        raise ReproductionMeasurementError("DELTA_REPRODUCTION_FAILED") from exc
