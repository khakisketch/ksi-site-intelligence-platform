"""DSM 차분 기반 구역 체적 — 손계산이 재현되는가 (ADR-KSI-016 D3).

이 파일의 시험 대상은 "rasterio 를 불렀다"가 아니라 **숫자가 맞다**이다. 합성
DSM 두 장을 만들어 사람이 암산할 수 있는 형상(한 변 10m, 1m 상승 → 100m³)을
넣고 그 값이 그대로 나오는지 본다. 체적 계산은 부호 하나만 뒤집혀도 결과가
그럴듯한 채로 틀리는 종류의 코드라, 골든 값 없이는 "돈다"와 "맞다"를 구분할 수
없다.

CRS 혼용 거부는 INV-020 의 강제 지점이다 — 좌표계가 다른 두 래스터를 빼면
셀이 엉뚱하게 대응되고, 결과는 여전히 숫자다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from ksi_change_detection.dsm_diff import (
    DsmDiffError,
    align_and_diff,
    volume_delta_in_polygon,
)
from ksi_geo_spatial.crs import CrsMismatchError, UnsupportedCrsError
from rasterio.transform import from_origin

# EPSG:5186 중부원점 평면좌표. 셀 1m × 1m, 20×20 격자.
_ORIGIN_X = 200_000.0
_ORIGIN_Y = 550_000.0
_CELL_M = 1.0
_SIZE = 20


def _write_dsm(
    path: Path,
    values: np.ndarray,
    *,
    crs: str = "EPSG:5186",
    origin_x: float = _ORIGIN_X,
    origin_y: float = _ORIGIN_Y,
    nodata: float | None = None,
) -> Path:
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
        transform=from_origin(origin_x, origin_y, _CELL_M, _CELL_M),
        nodata=nodata,
    ) as dataset:
        dataset.write(values, 1)
    return path


def _flat(value: float = 100.0) -> np.ndarray:
    return np.full((_SIZE, _SIZE), value, dtype=np.float64)


def _square_polygon(*, size_m: float) -> dict[str, object]:
    """좌상단 원점에서 시작하는 정사각 폴리곤 (래스터와 같은 좌표계)."""
    x0, y0 = _ORIGIN_X, _ORIGIN_Y
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [x0, y0],
                [x0 + size_m, y0],
                [x0 + size_m, y0 - size_m],
                [x0, y0 - size_m],
                [x0, y0],
            ]
        ],
    }


_NO_RMSE_NOTE = "검사점 RMSE 없음"


def test_uniform_rise_reproduces_the_hand_calculation(tmp_path: Path) -> None:
    """[골든] 10m × 10m 구역이 1m 올라가면 성토 100m³."""
    baseline = _write_dsm(tmp_path / "base.tif", _flat(100.0))
    current = _write_dsm(tmp_path / "curr.tif", _flat(101.0))

    diff = align_and_diff(baseline, current)
    zone = volume_delta_in_polygon(
        diff,
        _square_polygon(size_m=10.0),
        zone_id="zone-0",
        from_crs="EPSG:5186",
        threshold_m=0.05,
        uncertainty_note=_NO_RMSE_NOTE,
    )

    assert zone.fill_m3 == pytest.approx(100.0)
    assert zone.cut_m3 == pytest.approx(0.0)
    assert zone.net_m3 == pytest.approx(100.0)
    assert zone.area_m2 == pytest.approx(100.0)


def test_uniform_drop_is_cut_not_negative_fill(tmp_path: Path) -> None:
    """부호 규약 — 깎인 것은 cut 이고 fill 은 0 이다(음수 fill 이 아니다)."""
    baseline = _write_dsm(tmp_path / "base.tif", _flat(100.0))
    current = _write_dsm(tmp_path / "curr.tif", _flat(99.5))

    zone = volume_delta_in_polygon(
        align_and_diff(baseline, current),
        _square_polygon(size_m=10.0),
        zone_id="zone-0",
        from_crs="EPSG:5186",
        threshold_m=0.05,
        uncertainty_note=_NO_RMSE_NOTE,
    )

    assert zone.cut_m3 == pytest.approx(50.0)
    assert zone.fill_m3 == pytest.approx(0.0)
    assert zone.net_m3 == pytest.approx(-50.0)


def test_cut_and_fill_are_reported_separately_not_netted_away(tmp_path: Path) -> None:
    """[핵심] 같은 구역에서 깎고 쌓았으면 순증가 0 이어도 둘 다 남는다.

    net 만 보면 "아무 일도 없었다"로 읽히지만 실제로는 흙이 움직였다 —
    토공 진척은 그 움직임의 양이지 순증감이 아니다.
    """
    baseline = _write_dsm(tmp_path / "base.tif", _flat(100.0))
    values = _flat(100.0)
    values[0:10, 0:5] = 101.0  # 왼쪽 절반 1m 상승
    values[0:10, 5:10] = 99.0  # 오른쪽 절반 1m 하강
    current = _write_dsm(tmp_path / "curr.tif", values)

    zone = volume_delta_in_polygon(
        align_and_diff(baseline, current),
        _square_polygon(size_m=10.0),
        zone_id="zone-0",
        from_crs="EPSG:5186",
        threshold_m=0.05,
        uncertainty_note=_NO_RMSE_NOTE,
    )

    assert zone.fill_m3 == pytest.approx(50.0)
    assert zone.cut_m3 == pytest.approx(50.0)
    assert zone.net_m3 == pytest.approx(0.0)


def test_changes_below_the_threshold_are_not_counted(tmp_path: Path) -> None:
    """재구성 노이즈 수준의 표고차는 변화가 아니다."""
    baseline = _write_dsm(tmp_path / "base.tif", _flat(100.0))
    current = _write_dsm(tmp_path / "curr.tif", _flat(100.02))

    zone = volume_delta_in_polygon(
        align_and_diff(baseline, current),
        _square_polygon(size_m=10.0),
        zone_id="zone-0",
        from_crs="EPSG:5186",
        threshold_m=0.05,
        uncertainty_note=_NO_RMSE_NOTE,
    )

    assert zone.fill_m3 == pytest.approx(0.0)
    assert zone.cut_m3 == pytest.approx(0.0)


def test_mismatched_crs_is_refused(tmp_path: Path) -> None:
    """[핵심 음성] 좌표계가 다른 두 래스터를 빼지 않는다 (INV-020).

    빼면 셀이 엉뚱하게 대응되고, 결과는 여전히 그럴듯한 숫자다.
    """
    baseline = _write_dsm(tmp_path / "base.tif", _flat(100.0), crs="EPSG:5186")
    current = _write_dsm(tmp_path / "curr.tif", _flat(101.0), crs="EPSG:5187")

    with pytest.raises(CrsMismatchError):
        align_and_diff(baseline, current)


def test_unsupported_crs_is_refused_even_when_both_epochs_match(tmp_path: Path) -> None:
    """[핵심 음성][회귀 2026-08-11] 두 시점이 서로 '같은' 좌표계라도, 그 좌표계가
    지원 화이트리스트 밖(다른 대륙의 UTM 존 등)이면 거부한다.

    ``assert_same_crs`` 는 두 값이 같은지만 본다 — 둘 다 틀렸으면 그냥 통과한다.
    실 개발 서버 종단 실행에서 두 재구성 산출물이 나란히 EPSG:32617(북미 동부
    UTM 존, 한국 현장과 무관)로 태깅된 채 통과해 900만 점의 99.9995%가 변화
    후보로 잡히고 평균 90m 하강이라는 물리적으로 말이 안 되는 결과가 나왔다
    (실 실행 기록: candidateRatio=0.9999950012855028, netM3=-13,972,214.75).
    화이트리스트가 이 정확한 실패를 막기 위해 이미 존재했지만 이 호출 경로에
    배선돼 있지 않았다."""
    baseline = _write_dsm(tmp_path / "base.tif", _flat(100.0), crs="EPSG:32617")
    current = _write_dsm(tmp_path / "curr.tif", _flat(101.0), crs="EPSG:32617")

    with pytest.raises(UnsupportedCrsError):
        align_and_diff(baseline, current)


def test_non_overlapping_rasters_are_refused(tmp_path: Path) -> None:
    """[음성] 겹치지 않는 두 시점은 비교 대상이 아니다 — 0 을 돌려주지 않는다."""
    baseline = _write_dsm(tmp_path / "base.tif", _flat(100.0))
    current = _write_dsm(
        tmp_path / "curr.tif", _flat(101.0), origin_x=_ORIGIN_X + 10_000.0
    )

    with pytest.raises(DsmDiffError):
        align_and_diff(baseline, current)


def test_nodata_cells_are_excluded_from_the_volume(tmp_path: Path) -> None:
    """[핵심] 값이 없는 셀은 0 이 아니라 '모름'이다.

    nodata 를 0 으로 읽으면 그 셀에서 100m 짜리 절토가 생긴다.
    """
    baseline = _write_dsm(tmp_path / "base.tif", _flat(100.0), nodata=-9999.0)
    values = _flat(101.0)
    values[0:10, 0:5] = -9999.0  # 구역 절반이 nodata
    current = _write_dsm(tmp_path / "curr.tif", values, nodata=-9999.0)

    zone = volume_delta_in_polygon(
        align_and_diff(baseline, current),
        _square_polygon(size_m=10.0),
        zone_id="zone-0",
        from_crs="EPSG:5186",
        threshold_m=0.05,
        uncertainty_note=_NO_RMSE_NOTE,
    )

    # 유효한 절반(50 셀 × 1m)만 집계된다.
    assert zone.fill_m3 == pytest.approx(50.0)
    assert zone.area_m2 == pytest.approx(50.0)


def test_polygon_outside_the_raster_is_refused(tmp_path: Path) -> None:
    """[음성] 래스터 밖 구역은 '변화 0' 이 아니라 잴 수 없는 것이다."""
    baseline = _write_dsm(tmp_path / "base.tif", _flat(100.0))
    current = _write_dsm(tmp_path / "curr.tif", _flat(101.0))
    far = {
        "type": "Polygon",
        "coordinates": [
            [
                [_ORIGIN_X + 50_000, _ORIGIN_Y],
                [_ORIGIN_X + 50_010, _ORIGIN_Y],
                [_ORIGIN_X + 50_010, _ORIGIN_Y - 10],
                [_ORIGIN_X + 50_000, _ORIGIN_Y],
            ]
        ],
    }

    with pytest.raises(DsmDiffError):
        volume_delta_in_polygon(
            align_and_diff(baseline, current),
            far,
            zone_id="zone-0",
            from_crs="EPSG:5186",
            threshold_m=0.05,
            uncertainty_note=_NO_RMSE_NOTE,
        )


def test_uncertainty_needs_both_epochs_verified(tmp_path: Path) -> None:
    """[핵심 정직성] 한쪽만 검증된 RMSE 로는 오차한계를 말하지 않는다 (INV-024)."""
    baseline = _write_dsm(tmp_path / "base.tif", _flat(100.0))
    current = _write_dsm(tmp_path / "curr.tif", _flat(101.0))
    diff = align_and_diff(baseline, current)
    polygon = _square_polygon(size_m=10.0)

    only_one = volume_delta_in_polygon(
        diff, polygon, zone_id="z", from_crs="EPSG:5186", threshold_m=0.05,
        baseline_rmse_m=0.03, current_rmse_m=None,
        uncertainty_note=_NO_RMSE_NOTE,
    )
    assert only_one.uncertainty_m3 is None
    assert only_one.uncertainty_note

    both = volume_delta_in_polygon(
        diff, polygon, zone_id="z", from_crs="EPSG:5186", threshold_m=0.05,
        baseline_rmse_m=0.03, current_rmse_m=0.04,
        uncertainty_note=_NO_RMSE_NOTE,
    )
    assert both.uncertainty_m3 is not None
    assert both.uncertainty_m3 > 0.0


def test_polygon_in_wgs84_is_reprojected(tmp_path: Path) -> None:
    """AOI 는 WGS84 로 들어오고 래스터는 투영좌표계다 — 그 변환이 정상 경로다."""
    from ksi_geo_spatial.crs import reproject_point

    baseline = _write_dsm(tmp_path / "base.tif", _flat(100.0))
    current = _write_dsm(tmp_path / "curr.tif", _flat(101.0))

    # 래스터 좌상단을 WGS84 로 되돌려 그 근방 폴리곤을 만든다.
    lon, lat = reproject_point(
        _ORIGIN_X + 5.0, _ORIGIN_Y - 5.0, from_crs="EPSG:5186", to_crs="EPSG:4326"
    )
    d = 0.00002  # 약 2m
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat - d]]
        ],
    }

    zone = volume_delta_in_polygon(
        align_and_diff(baseline, current),
        polygon,
        zone_id="zone-0",
        from_crs="EPSG:4326",
        threshold_m=0.05,
        uncertainty_note=_NO_RMSE_NOTE,
    )
    assert zone.area_m2 > 0.0
    assert zone.fill_m3 > 0.0
