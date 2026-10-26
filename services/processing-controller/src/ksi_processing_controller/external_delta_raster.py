"""Bounded, private FLOAT64 delta output from an already validated V2 array.

This is a worker measurement primitive, not publication or authorization. It
never opens customer inputs, invents a URL, changes a numeric result, or keeps
bytes after its context closes. The caller must run inside its approved native
resource boundary and supply a live lease/currentness watchdog.
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
from dataclasses import dataclass

import numpy as np
import rasterio
from ksi_change_detection.dsm_diff import DiffResult
from ksi_event_contracts.external_masked_volume import MaskedCalculationIdentityV3
from ksi_event_contracts.external_masked_volume_result import MaskedVolumeCalculationReportV3
from ksi_event_contracts.external_relative_volume_calculation import RelativeVolumeNumericResultV2
from ksi_geo_spatial.crs import assert_supported_project_crs
from rasterio.transform import Affine, array_bounds
from rasterio.windows import Window

_BLOCK = 256
_CHUNK = 1024 * 1024


class DeltaRasterMeasurementError(ValueError):
    """An exact bounded output cannot be established; no publishable bytes."""


@dataclass(frozen=True, slots=True)
class MeasuredDeltaRasterV1:
    """Anonymous descriptor owned only for the surrounding context lifetime."""

    fd: int
    size_bytes: int
    sha256: str
    rows: int
    columns: int
    transform: tuple[float, float, float, float, float, float]
    crs: str
    calculation_identity_digest: str
    numeric_result_identity_digest: str
    coverage_witness_digest: str


def _positive_limit(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DeltaRasterMeasurementError("explicit positive resource limits are required")


def _affine_tuple(transform: Affine) -> tuple[float, float, float, float, float, float]:
    return (transform.a, transform.b, transform.c, transform.d, transform.e, transform.f)


def _preflight_output_grid(
    rows: int, columns: int, *, maximum_grid_cells: int, maximum_output_bytes: int
) -> None:
    _positive_limit(maximum_grid_cells)
    _positive_limit(maximum_output_bytes)
    if rows * columns > maximum_grid_cells:
        raise DeltaRasterMeasurementError("delta grid exceeds the explicit cell budget")
    tiles = ((rows + _BLOCK - 1) // _BLOCK) * ((columns + _BLOCK - 1) // _BLOCK)
    worst_case_bytes = tiles * _BLOCK * _BLOCK * 8 + 262_144 + tiles * 32
    if worst_case_bytes > maximum_output_bytes or worst_case_bytes >= 2**32:
        raise DeltaRasterMeasurementError("delta output exceeds the explicit byte budget")


@contextmanager
def prepare_external_delta_raster_v2(
    *,
    diff: DiffResult,
    numeric_result: RelativeVolumeNumericResultV2,
    maximum_output_bytes: int,
    maximum_grid_cells: int,
    check_current: Callable[[], None],
) -> Iterator[MeasuredDeltaRasterV1]:
    """Retain exact current−baseline values; outside coverage is NaN, not zero.

    The coverage and finite arithmetic must reproduce the sealed numeric record
    before any native write. Fixed uncompressed tiled output admits a conservative
    byte preflight (including padded tiles), rather than hoping compression fits.
    File-size enforcement still belongs to the caller's contained worker limits.
    """
    _positive_limit(maximum_output_bytes)
    _positive_limit(maximum_grid_cells)
    if not callable(check_current):
        raise DeltaRasterMeasurementError("a currentness watchdog is required")
    check_current()
    # Revalidation rejects model_copy bypasses and mutated nested arrays/records.
    numeric = RelativeVolumeNumericResultV2.model_validate(numeric_result.model_dump())
    if numeric.numeric_result_identity_digest is None:
        raise DeltaRasterMeasurementError("numeric result must be sealed")
    coverage = numeric.coverage
    rows, columns = coverage.rows, coverage.columns
    # Each padded FLOAT64 tile is fixed-size; reserve TIFF directory/metadata
    # overhead separately and bound the tile offset/size tables explicitly.
    _preflight_output_grid(
        rows,
        columns,
        maximum_grid_cells=maximum_grid_cells,
        maximum_output_bytes=maximum_output_bytes,
    )
    if (
        not isinstance(diff, DiffResult)
        or not isinstance(diff.diff_m, np.ndarray)
        or not isinstance(diff.valid, np.ndarray)
        or diff.diff_m.ndim != 2
        or diff.valid.shape != diff.diff_m.shape
        or diff.valid.dtype != np.dtype(np.bool_)
        or diff.diff_m.dtype != np.dtype(np.float64)
        or not isinstance(diff.transform, Affine)
    ):
        raise DeltaRasterMeasurementError("delta must be an exact FLOAT64 baseline grid")
    transform = diff.transform
    if (
        not all(math.isfinite(value) for value in _affine_tuple(transform))
        or transform.b != 0
        or transform.d != 0
        or transform.a <= 0
        or transform.e >= 0
    ):
        raise DeltaRasterMeasurementError("delta grid must be finite native north-up affine")
    crs = assert_supported_project_crs(diff.crs)
    cell_area = abs(transform.a * transform.e)
    if (
        not math.isfinite(diff.cell_area_m2)
        or not math.isclose(cell_area, diff.cell_area_m2, rel_tol=1e-12, abs_tol=1e-12)
        or not math.isclose(cell_area, coverage.cell_area_m2, rel_tol=1e-12, abs_tol=1e-12)
    ):
        raise DeltaRasterMeasurementError("delta cell area differs from sealed coverage")
    row, column = coverage.row_offset, coverage.column_offset
    out_transform = transform * Affine.translation(column, row)
    if not np.allclose(
        array_bounds(rows, columns, out_transform), coverage.bounds, rtol=0, atol=1e-9
    ):
        raise DeltaRasterMeasurementError("delta window differs from sealed coverage bounds")
    packed = base64.b64decode(coverage.common_valid_mask_b64, validate=True)
    selected = (
        np.unpackbits(np.frombuffer(packed, dtype=np.uint8), bitorder="big")[: rows * columns]
        .reshape(rows, columns)
        .astype(np.bool_)
    )
    # Retain a private snapshot so a later caller-side array mutation cannot
    # change cells between the numeric check and native block writes.
    # The frozen coverage witness is the full rasterized polygon window, not
    # necessarily a subset of the input's bounding rectangle. Rounding or holes
    # can add unselected border cells. Preserve that window as NaN padding;
    # selected cells outside the actual baseline remain an error, never filled.
    values = np.full((rows, columns), np.nan, dtype=np.float64)
    valid = np.zeros((rows, columns), dtype=np.bool_)
    source_row, source_column = max(0, row), max(0, column)
    end_row = min(diff.diff_m.shape[0], row + rows)
    end_column = min(diff.diff_m.shape[1], column + columns)
    if end_row > source_row and end_column > source_column:
        target = (
            slice(source_row - row, end_row - row),
            slice(source_column - column, end_column - column),
        )
        source = (slice(source_row, end_row), slice(source_column, end_column))
        values[target] = diff.diff_m[source]
        valid[target] = diff.valid[source]
    if not bool(valid[selected].all()) or not bool(np.isfinite(values[selected]).all()):
        raise DeltaRasterMeasurementError("sealed selected cells lack finite validated deltas")
    selected_values = values[selected]
    fill = float(selected_values[selected_values > 0].sum() * cell_area)
    cut = float(-selected_values[selected_values < 0].sum() * cell_area)
    if not all(
        math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
        for actual, expected in (
            (fill, numeric.metrics.fill_m3),
            (cut, numeric.metrics.cut_m3),
            (fill - cut, numeric.metrics.net_m3),
        )
    ):
        raise DeltaRasterMeasurementError(
            "delta array does not reproduce the sealed numeric result"
        )
    check_current()
    with _prepare_verified_delta_output(
        values=values,
        selected=selected,
        out_transform=out_transform,
        crs=crs,
        calculation_digest=numeric.calculation_identity_digest,
        numeric_digest=numeric.numeric_result_identity_digest,
        coverage_digest=coverage.canonical_digest(),
        maximum_output_bytes=maximum_output_bytes,
        maximum_grid_cells=maximum_grid_cells,
        check_current=check_current,
    ) as output:
        yield output


@contextmanager
def _prepare_verified_delta_output(
    *,
    values: np.ndarray,
    selected: np.ndarray,
    out_transform: Affine,
    crs: str,
    calculation_digest: str,
    numeric_digest: str,
    coverage_digest: str,
    maximum_output_bytes: int,
    maximum_grid_cells: int,
    check_current: Callable[[], None],
) -> Iterator[MeasuredDeltaRasterV1]:
    """Shared encoder only; versioned wrappers retain separate numeric semantics."""
    rows, columns = values.shape
    _preflight_output_grid(
        rows,
        columns,
        maximum_grid_cells=maximum_grid_cells,
        maximum_output_bytes=maximum_output_bytes,
    )
    check_current()
    with tempfile.TemporaryFile(mode="w+b") as output:
        descriptor_path = f"/proc/self/fd/{output.fileno()}"
        with rasterio.open(
            descriptor_path,
            "w",
            driver="GTiff",
            dtype="float64",
            count=1,
            width=columns,
            height=rows,
            crs=crs,
            transform=out_transform,
            nodata=float("nan"),
            tiled=True,
            blockxsize=_BLOCK,
            blockysize=_BLOCK,
            compress="none",
            BIGTIFF="NO",
        ) as dataset:
            dataset.units = ("metre",)
            dataset.descriptions = ("Current minus baseline elevation change",)
            dataset.update_tags(
                DELTA_RULE="CURRENT_MINUS_BASELINE",
                NUMERIC_RESULT_IDENTITY_DIGEST=numeric_digest,
                COVERAGE_WITNESS_DIGEST=coverage_digest,
            )
            for start in range(0, rows, _BLOCK):
                check_current()
                end = min(rows, start + _BLOCK)
                block = np.where(selected[start:end], values[start:end], np.nan)
                dataset.write(block, 1, window=Window(0, start, columns, end - start))
        output.flush()
        metadata = os.fstat(output.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 0
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or not 0 < metadata.st_size <= maximum_output_bytes
        ):
            raise DeltaRasterMeasurementError("private output identity/byte budget is invalid")
        digest = hashlib.sha256()
        output.seek(0)
        while chunk := output.read(_CHUNK):
            check_current()
            digest.update(chunk)
        output.seek(0)
        check_current()
        yield MeasuredDeltaRasterV1(
            fd=output.fileno(),
            size_bytes=metadata.st_size,
            sha256="sha256:" + digest.hexdigest(),
            rows=rows,
            columns=columns,
            transform=_affine_tuple(out_transform),
            crs=crs,
            calculation_identity_digest=calculation_digest,
            numeric_result_identity_digest=numeric_digest,
            coverage_witness_digest=coverage_digest,
        )


@contextmanager
def prepare_external_delta_raster_v3(
    *,
    masked_identity: MaskedCalculationIdentityV3,
    report: MaskedVolumeCalculationReportV3,
    delta_grid_m: np.ndarray,
    maximum_output_bytes: int,
    maximum_grid_cells: int,
    check_current: Callable[[], None],
) -> Iterator[MeasuredDeltaRasterV1]:
    """Encode a V3 result without fabricating a V2 numeric identity or witness."""
    _positive_limit(maximum_output_bytes)
    _positive_limit(maximum_grid_cells)
    if not callable(check_current):
        raise DeltaRasterMeasurementError("a currentness watchdog is required")
    check_current()
    identity = MaskedCalculationIdentityV3.model_validate(masked_identity.model_dump())
    result = MaskedVolumeCalculationReportV3.model_validate(report.model_dump())
    numeric = result.numeric_result
    if (
        identity.masked_calculation_identity_digest is None
        or result.report_digest is None
        or numeric.numeric_result_identity_digest is None
        or numeric.masked_calculation_identity_digest != identity.canonical_digest()
        or numeric.masked_profile_digest != identity.profile.canonical_digest()
        or numeric.mask_binding_digest != identity.mask_binding.canonical_digest()
    ):
        raise DeltaRasterMeasurementError("V3 numeric result does not bind the masked identity")
    coverage = numeric.coverage
    rows, columns = coverage.rows, coverage.columns
    _preflight_output_grid(
        rows,
        columns,
        maximum_grid_cells=maximum_grid_cells,
        maximum_output_bytes=maximum_output_bytes,
    )
    if (
        not isinstance(delta_grid_m, np.ndarray)
        or delta_grid_m.dtype != np.dtype(np.float64)
        or delta_grid_m.shape != (rows, columns)
        or np.ma.isMaskedArray(delta_grid_m)
    ):
        raise DeltaRasterMeasurementError("V3 delta must be the exact cropped FLOAT64 array")
    row, column = coverage.row_offset, coverage.column_offset
    base_transform = Affine(*identity.source_calculation_identity.baseline_transform)
    transform = base_transform * Affine.translation(column, row)
    if not np.allclose(array_bounds(rows, columns, transform), coverage.bounds, rtol=0, atol=1e-9):
        raise DeltaRasterMeasurementError("V3 output differs from its coverage bounds")
    packed = base64.b64decode(coverage.common_valid_mask_b64, validate=True)
    selected = (
        np.unpackbits(np.frombuffer(packed, dtype=np.uint8), bitorder="big")[: rows * columns]
        .reshape(rows, columns)
        .astype(np.bool_)
    )
    # As with V2, an unselected NaN border may extend beyond the baseline.
    # No effective selected cell may leave the byte-bound source grid.
    source_row, source_column = max(0, row), max(0, column)
    end_row = min(identity.grid_rows, row + rows)
    end_column = min(identity.grid_columns, column + columns)
    within_baseline = np.zeros((rows, columns), dtype=np.bool_)
    if end_row > source_row and end_column > source_column:
        within_baseline[
            source_row - row : end_row - row, source_column - column : end_column - column
        ] = True
    if bool((selected & ~within_baseline).any()):
        raise DeltaRasterMeasurementError("V3 selected coverage leaves the bound baseline grid")
    values = delta_grid_m.copy()
    if not bool(np.array_equal(np.isfinite(values), selected)) or bool(np.isinf(values).any()):
        raise DeltaRasterMeasurementError("V3 excluded or unavailable cells must remain NaN")
    cell_area = abs(transform.a * transform.e)
    if not math.isclose(cell_area, coverage.cell_area_m2, rel_tol=1e-12, abs_tol=1e-12):
        raise DeltaRasterMeasurementError("V3 cell area differs from sealed coverage")
    finite = values[selected]
    cut = float(-finite[finite < 0].sum() * cell_area)
    fill = float(finite[finite > 0].sum() * cell_area)
    if not all(
        math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)
        for actual, expected in (
            (cut, numeric.metrics.cut_m3),
            (fill, numeric.metrics.fill_m3),
            (fill - cut, numeric.metrics.net_m3),
        )
    ):
        raise DeltaRasterMeasurementError("V3 output array differs from its numeric metrics")
    with _prepare_verified_delta_output(
        values=values,
        selected=selected,
        out_transform=transform,
        crs=identity.source_calculation_identity.baseline_observed_crs_identifier,
        calculation_digest=identity.canonical_digest(),
        numeric_digest=numeric.canonical_digest(),
        coverage_digest=coverage.canonical_digest(),
        maximum_output_bytes=maximum_output_bytes,
        maximum_grid_cells=maximum_grid_cells,
        check_current=check_current,
    ) as output:
        yield output
