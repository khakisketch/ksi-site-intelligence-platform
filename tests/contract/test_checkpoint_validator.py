"""Independent checkpoint validator: sealed CSV + DSM -> server-measured metrics.

These tests intentionally exercise a real GeoTIFF rather than a sampling mock:
the important product claim is that no uploader-provided RMSE can reach Core.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import httpx
import numpy as np
import pytest
import rasterio
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from ksi_processing_controller.checkpoint_validator import (
    CheckpointValidationError,
    parse_checkpoint_csv,
    validate_checkpoint_validation,
)
from ksi_processing_controller.core_client import (
    CheckpointValidationMeasurement,
    PendingCheckpointValidation,
)
from rasterio.transform import from_origin


def _candidate() -> PendingCheckpointValidation:
    return PendingCheckpointValidation(
        validation_id="checkpoint-validation-1",
        checkpoint_download_url="https://storage.test/checkpoints.csv",
        dsm_download_url="https://storage.test/dsm.tif",
        checkpoint_crs="EPSG:5186",
        checkpoint_vertical_reference=VerticalReference(
            datum=VerticalDatum.ELLIPSOIDAL,
            basis="independent total-station survey",
            source=VerticalReferenceSource.USER_DECLARED,
        ),
        dsm_crs="EPSG:5186",
        dsm_vertical_reference=VerticalReference(
            datum=VerticalDatum.ELLIPSOIDAL,
            basis="ODM pipeline output",
            source=VerticalReferenceSource.PIPELINE_DECLARED,
        ),
    )


class _Core:
    def __init__(self) -> None:
        self.observations: list[tuple[str, CheckpointValidationMeasurement]] = []
        self.failures: list[tuple[str, str, str | None]] = []

    def list_pending_checkpoint_validations(
        self, *, limit: int = 50
    ) -> list[PendingCheckpointValidation]:
        del limit
        return []

    def report_checkpoint_validation_observation(
        self, validation_id: str, measurement: CheckpointValidationMeasurement
    ) -> str:
        self.observations.append((validation_id, measurement))
        return "VALIDATED"

    def report_checkpoint_validation_failure(
        self, validation_id: str, *, reason: str, detail: str | None = None
    ) -> str:
        self.failures.append((validation_id, reason, detail))
        return "REJECTED"


def _write_dsm(
    path: Path,
    *,
    nodata_at_center: bool = False,
    crs: str = "EPSG:5186",
    dtype: str = "float32",
    values: np.ndarray | None = None,
    scale: float = 1.0,
    offset: float = 0.0,
) -> Path:
    if values is None:
        values = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=dtype)
    else:
        values = np.asarray(values, dtype=dtype)
    if nodata_at_center:
        values[0, 0] = np.nan
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype=dtype,
        crs=crs,
        nodata=float("nan"),
        transform=from_origin(200_000, 500_000, 1, 1),
    ) as dataset:
        dataset.write(values, 1)
        dataset.scales = (scale,)
        dataset.offsets = (offset,)
    return path


def _client(
    *, checkpoint: bytes, dsm: Path, checkpoint_status: int = 200, dsm_status: int = 200
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("checkpoints.csv"):
            return httpx.Response(checkpoint_status, content=checkpoint)
        if request.url.path.endswith("dsm.tif"):
            return httpx.Response(dsm_status, content=dsm.read_bytes())
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_strict_csv_requires_exact_header_unique_ids_and_finite_coordinates() -> None:
    points = parse_checkpoint_csv(
        b"checkpoint_id,easting_m,northing_m,elevation_m\n"
        b"cp-a,200000.5,499999.5,9\ncp-b,200001.5,499999.5,18\ncp-c,200000.5,499998.5,31\n"
    )
    assert [point.checkpoint_id for point in points] == ["cp-a", "cp-b", "cp-c"]

    with pytest.raises(CheckpointValidationError) as extra_column:
        parse_checkpoint_csv(
            b"checkpoint_id,easting_m,northing_m,elevation_m,claimed_rmse\ncp,1,2,3,0\n"
        )
    assert extra_column.value.reason.value == "INVALID_CHECKPOINT_CSV"

    with pytest.raises(CheckpointValidationError) as duplicate:
        parse_checkpoint_csv(
            b"checkpoint_id,easting_m,northing_m,elevation_m\n"
            b"cp,1,2,3\ncp,2,3,4\ncp-3,3,4,5\n"
        )
    assert duplicate.value.reason.value == "INVALID_CHECKPOINT_CSV"

    with pytest.raises(CheckpointValidationError) as nan:
        parse_checkpoint_csv(
            b"checkpoint_id,easting_m,northing_m,elevation_m\n"
            b"a,1,2,nan\nb,2,3,4\nc,3,4,5\n"
        )
    assert nan.value.reason.value == "INVALID_CHECKPOINT_CSV"

    with pytest.raises(CheckpointValidationError) as too_few:
        parse_checkpoint_csv(
            b"checkpoint_id,easting_m,northing_m,elevation_m\n"
            b"a,1,2,3\nb,2,3,4\n"
        )
    assert too_few.value.reason.value == "CHECKPOINT_COUNT_OUT_OF_RANGE"


def test_strict_csv_rejects_more_than_ten_thousand_points() -> None:
    rows = [b"checkpoint_id,easting_m,northing_m,elevation_m\n"]
    rows.extend(f"cp-{index},{index},1,2\n".encode() for index in range(10_001))
    with pytest.raises(CheckpointValidationError) as too_many:
        parse_checkpoint_csv(b"".join(rows))
    assert too_many.value.reason.value == "CHECKPOINT_COUNT_OUT_OF_RANGE"


def test_worker_measures_every_checkpoint_and_submits_deterministic_residual_metrics(
    tmp_path: Path,
) -> None:
    dsm = _write_dsm(tmp_path / "dsm.tif")
    # The first three centres are 10, 20 and 30m, so residuals are +1, +2, -1m.
    checkpoint = (
        b"checkpoint_id,easting_m,northing_m,elevation_m\n"
        b"cp-a,200000.5,499999.5,9\n"
        b"cp-b,200001.5,499999.5,18\n"
        b"cp-c,200000.5,499998.5,31\n"
    )
    core = _Core()
    work_dir = tmp_path / "work"
    with _client(checkpoint=checkpoint, dsm=dsm) as http_client:
        verdict = validate_checkpoint_validation(
            _candidate(), core=core, http_client=http_client, work_dir=work_dir
        )

    assert verdict == "VALIDATED"
    assert core.failures == []
    assert len(core.observations) == 1
    measurement = core.observations[0][1]
    assert measurement.point_count == 3
    assert measurement.mean_error_m == pytest.approx(2 / 3)
    assert measurement.mae_m == pytest.approx(4 / 3)
    assert measurement.rmse_m == pytest.approx(np.sqrt(2.0))
    assert measurement.max_abs_error_m == pytest.approx(2.0)
    assert measurement.dsm_digest.startswith("sha256:")
    assert list(work_dir.iterdir()) == []


def test_any_outside_or_nodata_point_rejects_the_entire_validation(tmp_path: Path) -> None:
    dsm = _write_dsm(tmp_path / "dsm.tif")
    checkpoint = (
        b"checkpoint_id,easting_m,northing_m,elevation_m\n"
        b"cp-a,200000.5,499999.5,10\n"
        b"cp-b,200001.5,499999.5,20\n"
        b"sensitive-point-id,200010,499999.5,0\n"
    )
    core = _Core()
    with _client(checkpoint=checkpoint, dsm=dsm) as http_client:
        verdict = validate_checkpoint_validation(
            _candidate(), core=core, http_client=http_client, work_dir=tmp_path / "work"
        )
    assert verdict == "REJECTED"
    assert core.observations == []
    assert core.failures[0][1] == "CHECKPOINT_OUTSIDE_DSM"
    assert "sensitive-point-id" not in (core.failures[0][2] or "")

    dsm_nodata = _write_dsm(tmp_path / "nodata.tif", nodata_at_center=True)
    all_inside = checkpoint.replace(
        b"sensitive-point-id,200010,499999.5,0", b"cp-c,200000.5,499998.5,30"
    )
    core = _Core()
    with _client(checkpoint=all_inside, dsm=dsm_nodata) as http_client:
        verdict = validate_checkpoint_validation(
            _candidate(), core=core, http_client=http_client, work_dir=tmp_path / "work-2"
        )
    assert verdict == "REJECTED"
    assert core.observations == []
    assert core.failures[0][1] == "DSM_NODATA_AT_CHECKPOINT"


def test_download_failure_is_retried_not_recorded_as_a_terminal_rejection(tmp_path: Path) -> None:
    dsm = _write_dsm(tmp_path / "dsm.tif")
    core = _Core()
    with (
        _client(checkpoint=b"irrelevant", dsm=dsm, checkpoint_status=503) as http_client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        validate_checkpoint_validation(
            _candidate(), core=core, http_client=http_client, work_dir=tmp_path / "work"
        )
    assert core.observations == []
    assert core.failures == []
    assert list((tmp_path / "work").iterdir()) == []


def test_oversized_checkpoint_download_is_terminal_size_rejection(tmp_path: Path) -> None:
    dsm = _write_dsm(tmp_path / "dsm.tif")
    core = _Core()
    oversized = b"x" * (5 * 1024 * 1024 + 1)
    with _client(checkpoint=oversized, dsm=dsm) as http_client:
        verdict = validate_checkpoint_validation(
            _candidate(), core=core, http_client=http_client, work_dir=tmp_path / "work"
        )
    assert verdict == "REJECTED"
    assert core.observations == []
    assert core.failures[0][1] == "CHECKPOINT_SIZE_MISMATCH"


@pytest.mark.parametrize(
    ("checkpoint_status", "dsm_status", "reason"),
    [
        (404, 200, "CHECKPOINT_OBJECT_MISSING"),
        (200, 404, "DSM_OBJECT_MISSING"),
    ],
)
def test_missing_sealed_object_is_terminal_and_does_not_poll_forever(
    checkpoint_status: int, dsm_status: int, reason: str, tmp_path: Path
) -> None:
    dsm = _write_dsm(tmp_path / "dsm.tif")
    checkpoint = (
        b"checkpoint_id,easting_m,northing_m,elevation_m\n"
        b"a,200000.5,499999.5,10\n"
        b"b,200001.5,499999.5,20\n"
        b"c,200000.5,499998.5,30\n"
    )
    core = _Core()
    with _client(
        checkpoint=checkpoint,
        dsm=dsm,
        checkpoint_status=checkpoint_status,
        dsm_status=dsm_status,
    ) as http_client:
        verdict = validate_checkpoint_validation(
            _candidate(), core=core, http_client=http_client, work_dir=tmp_path / "work"
        )
    assert verdict == "REJECTED"
    assert core.observations == []
    assert core.failures[0][1] == reason


def test_worker_rejects_unsupported_or_mismatched_project_crs(tmp_path: Path) -> None:
    checkpoint = (
        b"checkpoint_id,easting_m,northing_m,elevation_m\n"
        b"a,200000.5,499999.5,10\n"
        b"b,200001.5,499999.5,20\n"
        b"c,200000.5,499998.5,30\n"
    )

    for candidate, dsm in (
        (_candidate(), _write_dsm(tmp_path / "mismatch.tif", crs="EPSG:5187")),
        (
            replace(_candidate(), checkpoint_crs="EPSG:4326"),
            _write_dsm(tmp_path / "geographic.tif", crs="EPSG:4326"),
        ),
    ):
        core = _Core()
        with _client(checkpoint=checkpoint, dsm=dsm) as http_client:
            verdict = validate_checkpoint_validation(
                candidate,
                core=core,
                http_client=http_client,
                work_dir=tmp_path / f"work-{dsm.stem}",
            )
        assert verdict == "REJECTED"
        assert core.observations == []
        assert core.failures[0][1] == "DSM_CRS_MISMATCH"


@pytest.mark.parametrize(("scale", "offset"), [(2.0, 0.0), (1.0, 100.0)])
def test_worker_rejects_non_identity_dsm_scale_or_offset(
    scale: float, offset: float, tmp_path: Path
) -> None:
    dsm = _write_dsm(tmp_path / f"scaled-{scale}-{offset}.tif", scale=scale, offset=offset)
    checkpoint = (
        b"checkpoint_id,easting_m,northing_m,elevation_m\n"
        b"a,200000.5,499999.5,10\n"
        b"b,200001.5,499999.5,20\n"
        b"c,200000.5,499998.5,30\n"
    )
    core = _Core()
    with _client(checkpoint=checkpoint, dsm=dsm) as http_client:
        verdict = validate_checkpoint_validation(
            _candidate(), core=core, http_client=http_client, work_dir=tmp_path / "work"
        )
    assert verdict == "REJECTED"
    assert core.observations == []
    assert core.failures[0][1] == "UNSUPPORTED_DSM"


def test_worker_rejects_non_finite_residual_aggregates(tmp_path: Path) -> None:
    # Each residual is finite, but squaring 1e200 in float64 is not. The worker
    # must emit no partial or non-finite metrics.
    dsm = _write_dsm(
        tmp_path / "overflow.tif",
        dtype="float64",
        values=np.full((2, 2), 1e200, dtype=np.float64),
    )
    checkpoint = (
        b"checkpoint_id,easting_m,northing_m,elevation_m\n"
        b"a,200000.5,499999.5,0\n"
        b"b,200001.5,499999.5,0\n"
        b"c,200000.5,499998.5,0\n"
    )
    core = _Core()
    with _client(checkpoint=checkpoint, dsm=dsm) as http_client:
        verdict = validate_checkpoint_validation(
            _candidate(), core=core, http_client=http_client, work_dir=tmp_path / "work"
        )
    assert verdict == "REJECTED"
    assert core.observations == []
    assert core.failures[0][1] == "INVALID_MEASUREMENT"
