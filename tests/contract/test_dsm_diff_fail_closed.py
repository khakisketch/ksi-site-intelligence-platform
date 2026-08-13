"""volume_delta_in_polygon 의 fail-closed 지점 — 재투영 실패가 DsmDiffError 로 나온다.

2026-08-13 프로젝트 두뇌 재감사 확정 발견(critical)의 회귀 방지. 좌표 재투영이
유한하지 않은 값(inf/nan)을 내면 ``geometry_mask`` 로 가기 전에 여기서 잡아야
한다 — 안 잡으면 폴리곤 일부 꼭짓점만 실패했을 때 rasterio 가 남은 꼭짓점만으로
"정상 종료"해 실제 구역의 일부만 잰 값이 오류 없이 나간다.
"""

from __future__ import annotations

import numpy as np
import pytest
from ksi_change_detection.dsm_diff import DiffResult, DsmDiffError, volume_delta_in_polygon
from rasterio.transform import from_origin

# 서울시청 부근 — 한국 중부원점(EPSG:5186) 적용 범위 안의 임의 지점.
_SEOUL_LON_DEG = 126.9780
_SEOUL_LAT_DEG = 37.5665


def _diff_result() -> DiffResult:
    diff_m = np.full((10, 10), 0.5, dtype=np.float64)
    valid = np.ones((10, 10), dtype=np.bool_)
    return DiffResult(
        diff_m=diff_m,
        valid=valid,
        transform=from_origin(200_000.0, 551_000.0, 1.0, 1.0),
        crs="EPSG:5186",
        cell_area_m2=1.0,
    )


def test_a_swapped_lat_lon_vertex_is_refused_not_silently_partial() -> None:
    """꼭짓점 하나만 위경도가 뒤바뀌어도 전체 구역을 거부한다.

    실측 재현: (lon=37.5665, lat=126.978) — 위도가 ±90 범위 밖이라 pyproj 가
    (inf, inf) 를 낸다. 옛 코드는 이 값을 그대로 셀 좌표로 써 남은 꼭짓점만으로
    도형을 그렸다(실제 구역의 28%만 잰 값이 오류 없이 나갔다).
    """
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [_SEOUL_LON_DEG, _SEOUL_LAT_DEG],
                [_SEOUL_LON_DEG + 0.001, _SEOUL_LAT_DEG],
                [_SEOUL_LAT_DEG, _SEOUL_LON_DEG],  # 뒤바뀐 꼭짓점
                [_SEOUL_LON_DEG, _SEOUL_LAT_DEG],
            ]
        ],
    }
    with pytest.raises(DsmDiffError, match="래스터 격자에 올릴 수 없다"):
        volume_delta_in_polygon(
            _diff_result(),
            polygon,
            zone_id="zone-bad",
            from_crs="EPSG:4326",
            threshold_m=0.05,
            uncertainty_note="테스트",
        )
