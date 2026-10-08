"""GSD(픽셀 표본거리) 해석 — 등록될 그 파일 자신의 아핀 변환에서 읽는가.

시험 대상은 "rasterio 를 불렀다"가 아니라 **값이 실제 픽셀 크기와 일치한다**와
**못 읽으면 지어내지 않고 건너뛴다**(INV-040) 두 가지다.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import rasterio
from ksi_processing_controller.gsd import resolve_gsd
from ksi_processing_controller.odm_assets import OdmAsset
from rasterio.transform import from_origin

# EPSG:5186 중부원점 평면좌표. change-detection/tests/test_dsm_diff.py 와 같은 관례.
_ORIGIN_X = 200_000.0
_ORIGIN_Y = 550_000.0


def _write_geotiff(
    path: Path,
    *,
    pixel_size_m: float,
    crs: str | None = "EPSG:5186",
    size: int = 4,
) -> Path:
    values = np.zeros((size, size), dtype="float32")
    kwargs: dict[str, object] = {
        "driver": "GTiff",
        "height": size,
        "width": size,
        "count": 1,
        "dtype": "float32",
    }
    if crs is not None:
        kwargs["crs"] = crs
        kwargs["transform"] = from_origin(_ORIGIN_X, _ORIGIN_Y, pixel_size_m, pixel_size_m)
    with rasterio.open(path, "w", **kwargs) as dataset:
        dataset.write(values, 1)
    return path


def _zip_with(tmp_path: Path, entries: dict[str, Path | bytes]) -> Path:
    archive_path = tmp_path / "all.zip"
    with zipfile.ZipFile(archive_path, "w") as zf:
        for entry, source in entries.items():
            if isinstance(source, Path):
                zf.write(source, entry)
            else:
                zf.writestr(entry, source)
    return archive_path


def _asset(artifact_id: str, entry: str, *, needs_gsd: bool = True) -> OdmAsset:
    return OdmAsset(
        artifact_id=artifact_id,
        archive_entry=entry,
        kind=object(),  # type: ignore[arg-type]  # resolve_gsd 는 kind 를 보지 않는다
        authority=object(),  # type: ignore[arg-type]
        derived_from=(),
        fmt="cog",
        needs_gsd=needs_gsd,
    )


def test_reads_pixel_size_from_the_geotiff_itself(tmp_path: Path) -> None:
    """5cm 픽셀로 쓴 파일에서 정확히 0.05 가 나온다."""
    tif = _write_geotiff(tmp_path / "dsm.tif", pixel_size_m=0.05)
    archive = _zip_with(tmp_path, {"odm_dem/dsm.tif": tif})

    result = resolve_gsd(archive, assets=(_asset("dsm", "odm_dem/dsm.tif"),))

    assert result == {"dsm": 0.05}


def test_only_looks_at_assets_that_declare_needs_gsd(tmp_path: Path) -> None:
    """needs_gsd=False 인 자산(카메라 포즈 등)은 애초에 보지 않는다."""
    tif = _write_geotiff(tmp_path / "dsm.tif", pixel_size_m=0.05)
    archive = _zip_with(tmp_path, {"odm_dem/dsm.tif": tif})

    result = resolve_gsd(archive, assets=(_asset("dsm", "odm_dem/dsm.tif", needs_gsd=False),))

    assert result == {}


def test_missing_archive_entry_is_skipped_not_raised(tmp_path: Path) -> None:
    """엔진 옵션에 따라 정사영상을 안 만들 수 있다 — 없는 게 정상 경로다."""
    archive = _zip_with(tmp_path, {"odm_report/report.pdf": b"x"})
    ortho_asset = _asset("orthophoto", "odm_orthophoto/odm_orthophoto.tif")

    result = resolve_gsd(archive, assets=(ortho_asset,))

    assert result == {}


def test_raster_without_crs_is_skipped_not_invented(tmp_path: Path) -> None:
    """CRS 없는 래스터의 GSD 를 지어내지 않는다(INV-040)."""
    tif = _write_geotiff(tmp_path / "dsm.tif", pixel_size_m=0.05, crs=None)
    archive = _zip_with(tmp_path, {"odm_dem/dsm.tif": tif})

    result = resolve_gsd(archive, assets=(_asset("dsm", "odm_dem/dsm.tif"),))

    assert result == {}


def test_corrupt_entry_is_skipped_not_raised(tmp_path: Path) -> None:
    """유효한 GeoTIFF 가 아닌 바이트가 그 이름으로 들어있어도 예외를 던지지 않는다."""
    archive = _zip_with(tmp_path, {"odm_dem/dsm.tif": b"not a real tiff"})

    result = resolve_gsd(archive, assets=(_asset("dsm", "odm_dem/dsm.tif"),))

    assert result == {}


def test_missing_archive_file_itself_is_skipped_not_raised(tmp_path: Path) -> None:
    """아카이브 경로 자체가 없어도(예: 상위 단계 실패) 예외 없이 빈 결과."""
    result = resolve_gsd(
        tmp_path / "does-not-exist.zip", assets=(_asset("dsm", "odm_dem/dsm.tif"),)
    )

    assert result == {}


def test_non_square_pixels_use_geometric_mean(tmp_path: Path) -> None:
    """직사각형 픽셀(드묾)은 두 축의 기하평균으로 대표한다."""
    path = tmp_path / "dsm.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:5186",
        transform=rasterio.transform.from_origin(_ORIGIN_X, _ORIGIN_Y, 0.03, 0.12),
    ) as dataset:
        dataset.write(np.zeros((4, 4), dtype="float32"), 1)
    archive = _zip_with(tmp_path, {"odm_dem/dsm.tif": path})

    result = resolve_gsd(archive, assets=(_asset("dsm", "odm_dem/dsm.tif"),))

    assert result["dsm"] == (0.03 * 0.12) ** 0.5


def test_multiple_assets_resolve_independently(tmp_path: Path) -> None:
    """한 아카이브에서 여러 래스터의 GSD 를 각각 읽는다."""
    ortho = _write_geotiff(tmp_path / "ortho.tif", pixel_size_m=0.03)
    dsm = _write_geotiff(tmp_path / "dsm.tif", pixel_size_m=0.05)
    archive = _zip_with(
        tmp_path,
        {
            "odm_orthophoto/odm_orthophoto.tif": ortho,
            "odm_dem/dsm.tif": dsm,
        },
    )
    assets = (
        _asset("orthophoto", "odm_orthophoto/odm_orthophoto.tif"),
        _asset("dsm", "odm_dem/dsm.tif"),
    )

    result = resolve_gsd(archive, assets=assets)

    assert result == {"orthophoto": 0.03, "dsm": 0.05}
