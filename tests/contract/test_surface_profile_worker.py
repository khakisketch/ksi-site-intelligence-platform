"""표면 단면 워커 — 순수 계산을 계약에 옮기되 모르는 값·한도·결속을 그대로 지킨다.

합성 래스터만 쓰며 해석해로 값을 검증한다. 측량 정확도·고객 수락의 증거가 아니다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import rasterio
from ksi_event_contracts.measurement_feature import MeasurementFeatureRevisionV1, MeasurementLineV1
from ksi_event_contracts.surface_profile import (
    CreateSurfaceProfileV1,
    SurfaceProfileRefusalV1,
    SurfaceProfileResultV1,
)
from ksi_geo_spatial.crs import reproject_point
from ksi_geo_spatial.surface_profile import SurfaceProfilePolicy
from ksi_processing_controller.surface_profile_worker import read_surface_profile
from rasterio.transform import from_origin

ASSET = "ksa-v1-" + "b" * 64
ORIGIN_X, ORIGIN_Y = 200_000.0, 500_000.0
NODATA = -9999.0
POLICY = SurfaceProfilePolicy(
    maximum_vertices=50,
    maximum_samples=300,
    maximum_line_length_m=5_000.0,
    maximum_window_cells=1_000_000,
    maximum_source_block_cells=4_000_000,
)


def _write(path: Path, values: np.ndarray, *, cell: float = 1.0) -> Path:
    height, width = values.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float32",
        crs="EPSG:5186",
        nodata=NODATA,
        transform=from_origin(ORIGIN_X, ORIGIN_Y, cell, cell),
    ) as dataset:
        dataset.write(values.astype("float32"), 1)
    return path


def _plane(rows: int = 20, cols: int = 30) -> np.ndarray:
    """z = 100 + 0.5·col + 0.25·row — 이중선형 보간이 정확히 복원하는 평면."""
    row_index, col_index = np.mgrid[0:rows, 0:cols]
    return 100.0 + 0.5 * col_index + 0.25 * row_index


def _centre(col: float, row: float) -> tuple[float, float]:
    return (ORIGIN_X + col + 0.5, ORIGIN_Y - row - 0.5)


def _line(*cells: tuple[float, float], crs: str = "EPSG:5186") -> MeasurementLineV1:
    return MeasurementLineV1(crs=crs, vertices=tuple(_centre(c, r) for c, r in cells))


def _request(line: MeasurementLineV1, **overrides: object) -> CreateSurfaceProfileV1:
    return CreateSurfaceProfileV1(asset_ref=ASSET, line=line, **overrides)  # type: ignore[arg-type]


def _read(path: Path, request: CreateSurfaceProfileV1) -> SurfaceProfileResultV1:
    result = read_surface_profile(request, path, policy=POLICY)
    assert isinstance(result, SurfaceProfileResultV1), result
    return result


def test_plane_heights_and_distances_match_the_analytical_solution(tmp_path: Path) -> None:
    path = _write(tmp_path / "dsm.tif", _plane())
    result = _read(path, _request(_line((2.0, 3.0), (12.0, 3.0), (12.0, 9.0))))
    assert result.horizontal_crs == "EPSG:5186"
    assert result.line_length_m == pytest.approx(16.0)
    assert result.sample_spacing_m == 1.0
    assert result.unknown_count == 0
    for row in result.samples:
        col, row_index = row.x - ORIGIN_X - 0.5, ORIGIN_Y - row.y - 0.5
        assert row.elevation_m == pytest.approx(100.0 + 0.5 * col + 0.25 * row_index, abs=1e-4)
    assert [row.distance_m for row in result.samples][-1] == pytest.approx(16.0)
    # 선의 방향을 지킨다 — 시작점이 첫 표본, 끝점이 마지막 표본이다.
    first, last = result.samples[0], result.samples[-1]
    assert (first.x, first.y) == pytest.approx(_centre(2.0, 3.0))
    assert (last.x, last.y) == pytest.approx(_centre(12.0, 9.0))
    known = [r.elevation_m for r in result.samples if r.elevation_m is not None]
    assert result.minimum_m == pytest.approx(min(known))


def test_result_is_sealed_deterministic_and_bound_to_request(tmp_path: Path) -> None:
    path = _write(tmp_path / "dsm.tif", _plane())
    line = _line((2.0, 3.0), (12.0, 3.0))
    feature = MeasurementFeatureRevisionV1(
        feature_id="mf-" + "2" * 32,
        site_id="site",
        work_area_id="area",
        revision=4,
        name="선",
        line=line,
        line_digest=line.digest(),
        created_at=datetime(2026, 11, 17, tzinfo=UTC),
    )
    request = _request(line, feature=feature.ref())
    first, second = _read(path, request), _read(path, request)
    assert first.result_digest == first.canonical_digest() == second.result_digest
    assert (first.asset_ref, first.line_digest, first.feature) == (
        ASSET,
        line.digest(),
        feature.ref(),
    )
    assert first.volume_computed is False and first.accuracy_assessed is False


def test_nodata_hole_is_unknown_with_a_reason_never_zero(tmp_path: Path) -> None:
    values = _plane()
    values[3, 6:9] = NODATA
    result = _read(_write(tmp_path / "dsm.tif", values), _request(_line((2.0, 3.0), (14.0, 3.0))))
    assert result.unknown_count > 0
    unknown = [row for row in result.samples if row.elevation_m is None]
    assert unknown and all(row.invalid_reason is not None for row in unknown)
    assert all(row.elevation_m != 0.0 for row in result.samples)
    assert result.valid_count + result.unknown_count == len(result.samples)


def test_line_outside_the_surface_is_all_unknown_and_reads_nothing(tmp_path: Path) -> None:
    path = _write(tmp_path / "dsm.tif", _plane())
    far = MeasurementLineV1(
        crs="EPSG:5186", vertices=((ORIGIN_X + 500.0, ORIGIN_Y), (ORIGIN_X + 510.0, ORIGIN_Y))
    )
    result = _read(path, _request(far))
    assert result.valid_count == 0 and result.window_cells_read == 0
    assert (result.minimum_m, result.maximum_m) == (None, None)
    assert {row.invalid_reason for row in result.samples} == {"OUTSIDE_SURFACE"}


def test_default_spacing_is_the_grid_resolution_and_a_finer_one_is_honoured(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "dsm.tif", _plane(), cell=2.0)
    line = MeasurementLineV1(
        crs="EPSG:5186",
        vertices=((ORIGIN_X + 3.0, ORIGIN_Y - 3.0), (ORIGIN_X + 23.0, ORIGIN_Y - 3.0)),
    )
    assert _read(path, _request(line)).sample_spacing_m == 2.0
    assert _read(path, _request(line, sample_spacing_m=0.5)).sample_spacing_m == 0.5


def test_geographic_line_reads_the_same_surface_as_the_projected_line(tmp_path: Path) -> None:
    path = _write(tmp_path / "dsm.tif", _plane())
    projected = _line((2.0, 3.0), (12.0, 3.0))
    geographic = MeasurementLineV1(
        crs="EPSG:4326",
        vertices=tuple(
            reproject_point(x, y, from_crs="EPSG:5186", to_crs="EPSG:4326")
            for x, y in projected.vertices
        ),
    )
    a, b = _read(path, _request(projected)), _read(path, _request(geographic))
    assert b.line_length_m == pytest.approx(a.line_length_m, abs=1e-3)
    assert [r.elevation_m for r in b.samples] == pytest.approx(
        [r.elevation_m for r in a.samples], abs=1e-2
    )


def test_over_limit_request_is_refused_with_no_partial_values(tmp_path: Path) -> None:
    path = _write(tmp_path / "dsm.tif", _plane())
    refusal = read_surface_profile(
        _request(_line((1.0, 1.0), (28.0, 1.0)), sample_spacing_m=0.05), path, policy=POLICY
    )
    assert isinstance(refusal, SurfaceProfileRefusalV1)
    assert refusal.reason == "TOO_MANY_SAMPLES" and refusal.retryable is False


def test_unreadable_file_is_a_typed_refusal_not_an_exception(tmp_path: Path) -> None:
    broken = tmp_path / "broken.tif"
    broken.write_bytes(b"not a raster")
    refusal = read_surface_profile(_request(_line((1.0, 1.0), (5.0, 1.0))), broken, policy=POLICY)
    assert isinstance(refusal, SurfaceProfileRefusalV1)
    assert refusal.reason == "UNREADABLE_RASTER"
    assert str(broken) not in refusal.model_dump_json()


def test_policy_above_the_contract_ceiling_is_clamped_before_reading(tmp_path: Path) -> None:
    from ksi_event_contracts.surface_profile import MAX_PROFILE_SAMPLES

    path = _write(tmp_path / "dsm.tif", _plane(rows=20, cols=80))
    generous = SurfaceProfilePolicy(
        maximum_vertices=500,
        maximum_samples=MAX_PROFILE_SAMPLES + 1_000,
        maximum_line_length_m=5_000.0,
        maximum_window_cells=1_000_000,
        maximum_source_block_cells=4_000_000,
    )
    # 70 m / 0.0138 m ≈ 5 070 samples — over the contract ceiling but inside the policy.
    request = _request(_line((2.0, 3.0), (72.0, 3.0)), sample_spacing_m=0.0138)
    refusal = read_surface_profile(request, path, policy=generous)
    assert isinstance(refusal, SurfaceProfileRefusalV1)
    assert refusal.reason == "TOO_MANY_SAMPLES"


@pytest.mark.parametrize("spacing", [5e-324, 1e-300])
def test_denormal_spacing_is_a_typed_refusal(tmp_path: Path, spacing: float) -> None:
    path = _write(tmp_path / "dsm.tif", _plane())
    refusal = read_surface_profile(
        _request(_line((2.0, 3.0), (9.0, 3.0)), sample_spacing_m=spacing), path, policy=POLICY
    )
    assert isinstance(refusal, SurfaceProfileRefusalV1)
    assert refusal.reason == "TOO_MANY_SAMPLES"


def test_a_line_shorter_than_the_tolerance_is_a_typed_refusal(tmp_path: Path) -> None:
    path = _write(tmp_path / "dsm.tif", _plane())
    x, y = _centre(2.0, 3.0)
    line = MeasurementLineV1(crs="EPSG:5186", vertices=((x, y), (x + 1e-10, y)))
    refusal = read_surface_profile(_request(line), path, policy=POLICY)
    assert isinstance(refusal, SurfaceProfileRefusalV1)
    assert refusal.reason == "INVALID_LINE"


def test_complex_raster_is_a_typed_refusal(tmp_path: Path) -> None:
    path = tmp_path / "complex.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=5,
        width=5,
        count=1,
        dtype="complex64",
        crs="EPSG:5186",
        transform=from_origin(ORIGIN_X, ORIGIN_Y, 1.0, 1.0),
    ) as dataset:
        dataset.write(np.full((5, 5), 7 + 9j, dtype="complex64"), 1)
    refusal = read_surface_profile(_request(_line((1.0, 1.0), (3.0, 1.0))), path, policy=POLICY)
    assert isinstance(refusal, SurfaceProfileRefusalV1)
    assert refusal.reason == "UNSUPPORTED_RASTER"
