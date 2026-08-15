"""지형고도 격자(DTM/DSM) 계약 — 임의 지점 표고 샘플링, fail-closed.

GeoidGrid(vertical.py)와 자매 모듈이다. 차이는 하나 — DTM/DSM 은 보통
투영좌표계(예 EPSG:5186)라 질의 지점(WGS84)을 그 좌표계로 재투영하는 단계가
있다. 그래서 이 파일은 지오이드 테스트의 격자수학 검증(픽셀중심·이중선형·
범위밖 거부)을 그대로 반복하되, 추가로 재투영·nodata 처리를 검증한다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from ksi_geo_spatial.crs import UnsupportedCrsError, reproject_point
from ksi_geo_spatial.terrain import TerrainGrid, TerrainUnavailableError
from rasterio.transform import from_origin

_NODATA = -9999.0


def _write_terrain(
    path: Path, values: np.ndarray, *, crs: str = "EPSG:5186", nodata: float | None = _NODATA
) -> Path:
    """투영좌표계(기본 EPSG:5186) 표고 래스터 — 셀 크기 1m, 원점 (200000, 500000)."""
    height, width = values.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float64",
        crs=crs,
        nodata=nodata,
        transform=from_origin(200_000.0, 500_000.0, 1.0, 1.0),
    ) as dataset:
        dataset.write(values, 1)
    return path


def test_pixel_centre_returns_the_stored_value(tmp_path: Path) -> None:
    """픽셀 중심에서는 저장값 그대로 — 재투영 오프셋이 틀리면 이웃 셀 값이 나온다."""
    values = np.array([[10.0, 20.0], [30.0, 40.0]])
    grid = TerrainGrid.from_path(_write_terrain(tmp_path / "dtm.tif", values))

    lon, lat = reproject_point(200_000.5, 499_999.5, from_crs="EPSG:5186", to_crs="EPSG:4326")
    assert grid.elevation_at(lat_deg=lat, lon_deg=lon) == pytest.approx(10.0)


def test_bilinear_interpolation_between_cells(tmp_path: Path) -> None:
    """셀 중심 사이는 이중선형 — 최근접 이웃으로 대충 하지 않는다."""
    values = np.array([[0.0, 10.0], [20.0, 30.0]])
    grid = TerrainGrid.from_path(_write_terrain(tmp_path / "dtm.tif", values))

    # 네 셀의 정중앙 투영좌표 (200001.0, 499999.0) → (0+10+20+30)/4 = 15.0
    lon, lat = reproject_point(200_001.0, 499_999.0, from_crs="EPSG:5186", to_crs="EPSG:4326")
    assert grid.elevation_at(lat_deg=lat, lon_deg=lon) == pytest.approx(15.0)


def test_point_outside_the_grid_is_refused(tmp_path: Path) -> None:
    """격자 범위 밖은 외삽하지 않는다 — INV-023 과 같은 fail-closed 원칙."""
    values = np.array([[1.0, 2.0], [3.0, 4.0]])
    grid = TerrainGrid.from_path(_write_terrain(tmp_path / "dtm.tif", values))

    with pytest.raises(TerrainUnavailableError):
        grid.elevation_at(lat_deg=10.0, lon_deg=10.0)


def test_nodata_cell_is_refused_not_treated_as_real_elevation(tmp_path: Path) -> None:
    """nodata 셀을 표고 -9999m 로 잘못 읽으면 안 된다 — 명시적으로 거부한다."""
    values = np.array([[_NODATA, 10.0], [20.0, 30.0]])
    grid = TerrainGrid.from_path(_write_terrain(tmp_path / "dtm.tif", values))

    lon, lat = reproject_point(200_000.5, 499_999.5, from_crs="EPSG:5186", to_crs="EPSG:4326")
    with pytest.raises(TerrainUnavailableError):
        grid.elevation_at(lat_deg=lat, lon_deg=lon)


def test_wgs84_raster_works_without_reprojection(tmp_path: Path) -> None:
    """래스터 자체가 이미 EPSG:4326 이면 재투영이 항등변환으로 성립해야 한다."""
    values = np.array([[10.0, 20.0], [30.0, 40.0]])
    path = tmp_path / "dtm_wgs84.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=1,
        dtype="float64",
        crs="EPSG:4326",
        nodata=_NODATA,
        transform=from_origin(126.0, 38.0, 1.0, 1.0),
    ) as dataset:
        dataset.write(values, 1)
    grid = TerrainGrid.from_path(path)

    assert grid.elevation_at(lat_deg=37.5, lon_deg=126.5) == pytest.approx(10.0)


def test_unsupported_projected_crs_is_rejected_at_load_time(tmp_path: Path) -> None:
    """구 측지계(Bessel, EPSG:5174)는 화이트리스트 밖이라 로드 시점에 거부된다."""
    values = np.array([[1.0, 2.0], [3.0, 4.0]])
    with pytest.raises(UnsupportedCrsError):
        TerrainGrid.from_path(_write_terrain(tmp_path / "dtm.tif", values, crs="EPSG:5174"))


def test_single_band_only(tmp_path: Path) -> None:
    """다중 밴드 래스터는 어느 밴드가 표고인지 모호하다 — 거부한다."""
    path = tmp_path / "multi.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=2,
        dtype="float64",
        crs="EPSG:5186",
        transform=from_origin(200_000.0, 500_000.0, 1.0, 1.0),
    ) as dataset:
        dataset.write(np.zeros((2, 2)), 1)
        dataset.write(np.zeros((2, 2)), 2)

    with pytest.raises(TerrainUnavailableError):
        TerrainGrid.from_path(path)
