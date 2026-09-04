"""Server-side validation of sealed independent checkpoints against one DSM.

The CSV carries a user attestation of its independent provenance, but it never
gets to claim an accuracy number.  This worker downloads the sealed CSV and
the immutable DSM, measures their bytes, samples *every* supplied checkpoint,
and reports only the resulting residual aggregates to Core.

Network/storage failures deliberately escape: no observation about either
file has been made, so Core must leave the validation ``SEALED`` for retry.
Conversely, a readable CSV/DSM that is malformed, incompatible, outside the
DSM, or on nodata is a deterministic typed rejection.  Partial metrics are
never emitted.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import rasterio
from ksi_event_contracts.checkpoint_validation import (
    CHECKPOINT_CSV_COLUMNS,
    CHECKPOINT_FILE_MAX_BYTES,
    CHECKPOINT_POINT_MAX,
    CHECKPOINT_POINT_MIN,
    CheckpointValidationRejectionReason,
)
from ksi_geo_spatial.crs import UnsupportedCrsError, assert_supported_project_crs
from rasterio.windows import Window

from ksi_processing_controller.core_client import (
    CheckpointValidationCoreClient,
    CheckpointValidationMeasurement,
    PendingCheckpointValidation,
)
from ksi_processing_controller.workspace import cleanup_attempt_workspace, unleased_workspace

_CHUNK_BYTES = 1024 * 1024


class CheckpointValidationError(RuntimeError):
    """A deterministic, terminal validation rejection with its Core reason."""

    def __init__(self, reason: CheckpointValidationRejectionReason, detail: str) -> None:
        self.reason = reason
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class Checkpoint:
    checkpoint_id: str
    easting_m: float
    northing_m: float
    elevation_m: float


def _download(
    url: str,
    *,
    destination: Path,
    http_client: httpx.Client,
    missing_reason: CheckpointValidationRejectionReason,
    maximum_bytes: int | None = None,
) -> tuple[str, int]:
    """Stream a presigned object to disk and return its measured hash and size.

    HTTP exceptions are intentionally not converted to a typed rejection:
    presigned URL expiry and storage outages say nothing about the sealed
    content and must be retried.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    with (
        http_client.stream("GET", url) as response,
        destination.open("wb") as handle,
    ):
        if response.status_code == 404:
            raise CheckpointValidationError(missing_reason, "sealed input object is missing")
        response.raise_for_status()
        for chunk in response.iter_bytes(_CHUNK_BYTES):
            size += len(chunk)
            if maximum_bytes is not None and size > maximum_bytes:
                raise CheckpointValidationError(
                    CheckpointValidationRejectionReason.CHECKPOINT_SIZE_MISMATCH,
                    f"checkpoint CSV exceeds {maximum_bytes} bytes",
                )
            digest.update(chunk)
            handle.write(chunk)
    return digest.hexdigest(), size


def parse_checkpoint_csv(data: bytes) -> tuple[Checkpoint, ...]:
    """Parse the deliberately small v1 CSV grammar without silently repairing it."""

    if len(data) > CHECKPOINT_FILE_MAX_BYTES:
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.CHECKPOINT_SIZE_MISMATCH,
            f"checkpoint CSV exceeds {CHECKPOINT_FILE_MAX_BYTES} bytes",
        )
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.INVALID_CHECKPOINT_CSV,
            "checkpoint CSV must be strict UTF-8",
        ) from exc

    try:
        rows = csv.reader(io.StringIO(text, newline=""))
        header = next(rows)
    except (csv.Error, StopIteration) as exc:
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.INVALID_CHECKPOINT_CSV,
            "checkpoint CSV has no valid header",
        ) from exc
    if tuple(header) != CHECKPOINT_CSV_COLUMNS:
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.INVALID_CHECKPOINT_CSV,
            "checkpoint CSV header must be exactly " + ",".join(CHECKPOINT_CSV_COLUMNS),
        )

    checkpoints: list[Checkpoint] = []
    identifiers: set[str] = set()
    try:
        for line_number, row in enumerate(rows, start=2):
            if len(row) != len(CHECKPOINT_CSV_COLUMNS):
                raise CheckpointValidationError(
                    CheckpointValidationRejectionReason.INVALID_CHECKPOINT_CSV,
                    f"checkpoint CSV line {line_number} must have exactly four columns",
                )
            checkpoint_id, raw_x, raw_y, raw_z = row
            if not checkpoint_id or checkpoint_id != checkpoint_id.strip():
                raise CheckpointValidationError(
                    CheckpointValidationRejectionReason.INVALID_CHECKPOINT_CSV,
                    f"checkpoint CSV line {line_number} has a blank or padded checkpoint_id",
                )
            if checkpoint_id in identifiers:
                raise CheckpointValidationError(
                    CheckpointValidationRejectionReason.INVALID_CHECKPOINT_CSV,
                    f"checkpoint CSV line {line_number} repeats a checkpoint_id",
                )
            try:
                x, y, z = float(raw_x), float(raw_y), float(raw_z)
            except ValueError as exc:
                raise CheckpointValidationError(
                    CheckpointValidationRejectionReason.INVALID_CHECKPOINT_CSV,
                    f"checkpoint CSV line {line_number} has a non-numeric coordinate",
                ) from exc
            if not all(math.isfinite(value) for value in (x, y, z)):
                raise CheckpointValidationError(
                    CheckpointValidationRejectionReason.INVALID_CHECKPOINT_CSV,
                    f"checkpoint CSV line {line_number} has a non-finite coordinate",
                )
            identifiers.add(checkpoint_id)
            checkpoints.append(Checkpoint(checkpoint_id, x, y, z))
            if len(checkpoints) > CHECKPOINT_POINT_MAX:
                raise CheckpointValidationError(
                    CheckpointValidationRejectionReason.CHECKPOINT_COUNT_OUT_OF_RANGE,
                    f"checkpoint CSV has more than {CHECKPOINT_POINT_MAX} points",
                )
    except csv.Error as exc:
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.INVALID_CHECKPOINT_CSV,
            f"checkpoint CSV is malformed: {exc}",
        ) from exc

    if not CHECKPOINT_POINT_MIN <= len(checkpoints) <= CHECKPOINT_POINT_MAX:
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.CHECKPOINT_COUNT_OUT_OF_RANGE,
            f"checkpoint CSV must contain {CHECKPOINT_POINT_MIN}..{CHECKPOINT_POINT_MAX} points",
        )
    return tuple(checkpoints)


def _assert_matching_crs(*, checkpoint_crs: str, dataset: rasterio.io.DatasetReader) -> str:
    if dataset.crs is None:
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.UNSUPPORTED_DSM,
            "DSM has no CRS",
        )
    try:
        declared = assert_supported_project_crs(checkpoint_crs)
        observed = assert_supported_project_crs(dataset.crs.to_wkt())
    except UnsupportedCrsError as exc:
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.DSM_CRS_MISMATCH,
            "checkpoint CRS or DSM CRS is not a supported project CRS",
        ) from exc
    if observed != declared:
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.DSM_CRS_MISMATCH,
            "checkpoint CRS does not match the DSM CRS",
        )
    return observed


def _nearest_pixel(dataset: rasterio.io.DatasetReader, *, x: float, y: float) -> tuple[int, int]:
    """Choose the closest pixel centre using a deterministic lower-index tie break."""

    # Pixel coordinates are measured from the upper-left *corner*; centres are
    # (col + .5, row + .5).  Evaluating the surrounding centre candidates in
    # map coordinates also keeps the rule meaningful for rotated affine DSMs.
    col_coord, row_coord = (~dataset.transform) * (x, y)
    if not (0.0 <= col_coord < dataset.width and 0.0 <= row_coord < dataset.height):
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.CHECKPOINT_OUTSIDE_DSM,
            "checkpoint lies outside the DSM extent",
        )
    initial_col = math.floor(col_coord - 0.5)
    initial_row = math.floor(row_coord - 0.5)
    candidates: list[tuple[float, int, int]] = []
    for row in range(initial_row - 1, initial_row + 3):
        for col in range(initial_col - 1, initial_col + 3):
            if not (0 <= row < dataset.height and 0 <= col < dataset.width):
                continue
            center_x, center_y = dataset.transform * (col + 0.5, row + 0.5)
            candidates.append(((center_x - x) ** 2 + (center_y - y) ** 2, row, col))
    if not candidates:
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.CHECKPOINT_OUTSIDE_DSM,
            "checkpoint lies outside the DSM extent",
        )
    # ``row,col`` makes exact half-way choices reproducible across platforms.
    _, row, col = min(candidates, key=lambda item: (item[0], item[1], item[2]))
    return row, col


def _sample_residuals(
    dataset: rasterio.io.DatasetReader, checkpoints: tuple[Checkpoint, ...]
) -> list[float]:
    if dataset.count != 1:
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.UNSUPPORTED_DSM,
            "DSM must have exactly one band",
        )
    dtype = np.dtype(dataset.dtypes[0])
    if not np.issubdtype(dtype, np.number) or np.issubdtype(dtype, np.complexfloating):
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.UNSUPPORTED_DSM,
            "DSM band must contain real numeric elevations",
        )
    if dataset.scales != (1.0,) or dataset.offsets != (0.0,):
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.UNSUPPORTED_DSM,
            "DSM v1 requires identity band scale and offset",
        )
    if dataset.transform.is_degenerate or not all(
        math.isfinite(value) for value in tuple(dataset.transform)[:6]
    ):
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.UNSUPPORTED_DSM,
            "DSM has a degenerate or non-finite affine transform",
        )
    residuals: list[float] = []
    for point_number, point in enumerate(checkpoints, start=1):
        try:
            row, col = _nearest_pixel(dataset, x=point.easting_m, y=point.northing_m)
        except CheckpointValidationError as exc:
            raise CheckpointValidationError(
                exc.reason, f"checkpoint row {point_number}: {exc}"
            ) from exc
        value = dataset.read(1, window=Window(col, row, 1, 1), masked=True)[0, 0]
        if np.ma.is_masked(value) or not math.isfinite(float(value)):
            raise CheckpointValidationError(
                CheckpointValidationRejectionReason.DSM_NODATA_AT_CHECKPOINT,
                f"checkpoint row {point_number}: DSM has nodata at the selected pixel",
            )
        residual = float(value) - point.elevation_m
        if not math.isfinite(residual):
            raise CheckpointValidationError(
                CheckpointValidationRejectionReason.INVALID_MEASUREMENT,
                f"checkpoint row {point_number}: residual is not finite",
            )
        residuals.append(residual)
    return residuals


def _measure(
    *,
    checkpoint_path: Path,
    checkpoint_sha256: str,
    checkpoint_size_bytes: int,
    dsm_path: Path,
    dsm_digest: str,
    checkpoint_crs: str,
) -> CheckpointValidationMeasurement:
    checkpoints = parse_checkpoint_csv(checkpoint_path.read_bytes())
    try:
        dataset = rasterio.open(dsm_path)
    except Exception as exc:  # rasterio/GDAL exception hierarchy is intentionally broad
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.UNREADABLE_DSM,
            f"DSM cannot be opened: {exc}",
        ) from exc
    with dataset:
        dsm_crs = _assert_matching_crs(checkpoint_crs=checkpoint_crs, dataset=dataset)
        residuals = _sample_residuals(dataset, checkpoints)
    values = np.asarray(residuals, dtype=np.float64)
    mean_error = float(np.mean(values, dtype=np.float64))
    absolute = np.abs(values)
    with np.errstate(over="ignore", invalid="ignore"):
        metrics = (
            mean_error,
            float(np.mean(absolute, dtype=np.float64)),
            float(math.sqrt(float(np.mean(values * values, dtype=np.float64)))),
            float(np.max(absolute)),
        )
    if not all(math.isfinite(value) for value in metrics):
        raise CheckpointValidationError(
            CheckpointValidationRejectionReason.INVALID_MEASUREMENT,
            "checkpoint residual aggregates are not finite",
        )
    return CheckpointValidationMeasurement(
        checkpoint_sha256=checkpoint_sha256,
        checkpoint_size_bytes=checkpoint_size_bytes,
        dsm_digest=f"sha256:{dsm_digest}",
        dsm_crs=dsm_crs,
        point_count=len(residuals),
        mean_error_m=metrics[0],
        mae_m=metrics[1],
        rmse_m=metrics[2],
        max_abs_error_m=metrics[3],
    )


def validate_checkpoint_validation(
    candidate: PendingCheckpointValidation,
    *,
    core: CheckpointValidationCoreClient,
    http_client: httpx.Client,
    work_dir: Path,
) -> str:
    """Complete one SEALED validation, or leave it SEALED when storage is unavailable."""

    attempt_dir = unleased_workspace(
        work_dir, work_kind="checkpoint-validation", resource_id=candidate.validation_id
    )
    checkpoint_path = attempt_dir / f"{candidate.validation_id}.checkpoints.csv"
    dsm_path = attempt_dir / f"{candidate.validation_id}.dsm.tif"
    try:
        checkpoint_sha256, checkpoint_size_bytes = _download(
            candidate.checkpoint_download_url,
            destination=checkpoint_path,
            http_client=http_client,
            missing_reason=CheckpointValidationRejectionReason.CHECKPOINT_OBJECT_MISSING,
            maximum_bytes=CHECKPOINT_FILE_MAX_BYTES,
        )
        dsm_digest, _ = _download(
            candidate.dsm_download_url,
            destination=dsm_path,
            http_client=http_client,
            missing_reason=CheckpointValidationRejectionReason.DSM_OBJECT_MISSING,
        )
        measurement = _measure(
            checkpoint_path=checkpoint_path,
            checkpoint_sha256=checkpoint_sha256,
            checkpoint_size_bytes=checkpoint_size_bytes,
            dsm_path=dsm_path,
            dsm_digest=dsm_digest,
            checkpoint_crs=candidate.checkpoint_crs,
        )
    except CheckpointValidationError as exc:
        return core.report_checkpoint_validation_failure(
            candidate.validation_id,
            reason=exc.reason.value,
            detail=str(exc)[:500],
        )
    finally:
        checkpoint_path.unlink(missing_ok=True)
        dsm_path.unlink(missing_ok=True)
        cleanup_attempt_workspace(work_dir, attempt_dir)
    return core.report_checkpoint_validation_observation(candidate.validation_id, measurement)


__all__ = [
    "Checkpoint",
    "CheckpointValidationError",
    "parse_checkpoint_csv",
    "validate_checkpoint_validation",
]
