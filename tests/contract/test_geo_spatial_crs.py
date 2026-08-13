"""측지 수평축 계약 — EPSG 투영좌표계 재투영과 혼용 차단 (INV-020, ADR-KSI-016 D3).

초점 셋:

1. **재투영이 실제로 맞다** — 왕복 변환의 오차가 mm 급이어야 한다. 이 검증이
   없으면 "pyproj 를 불렀다"와 "좌표가 맞다"를 구분할 수 없다.
2. **구 측지계를 화이트리스트가 막는다** — 한국에는 Bessel 타원체 기반의 구
   좌표계(EPSG:5173~5177 계열)가 여전히 도면·성과에 남아 있다. 그 좌표를
   KGD2002 로 착각해 섞으면 **수백 미터** 오차가 조용히 들어온다. 값이 그럴듯한
   범위라 눈으로는 안 잡힌다.
3. **CRS 혼용이 비교 입구에서 거부된다** — INV-020 "CRS·수직기준이 다른
   산출물을 직접 비교·병합하지 않는다"의 강제 지점.
"""

from __future__ import annotations

import pytest
from ksi_geo_spatial.crs import (
    DEFAULT_CRS,
    SUPPORTED_PROJECT_CRS,
    CrsMismatchError,
    ReprojectionFailedError,
    UnsupportedCrsError,
    assert_same_crs,
    assert_supported_project_crs,
    reproject_geometry,
    reproject_point,
)

# 서울시청 부근 — 한국 중부원점(EPSG:5186) 적용 범위 안의 임의 지점.
_SEOUL_LON_DEG = 126.9780
_SEOUL_LAT_DEG = 37.5665


def test_default_crs_is_korea_central_belt() -> None:
    """기본값은 중부원점이다 — 현장 대부분이 이 대역에 있다."""
    assert DEFAULT_CRS == "EPSG:5186"
    assert DEFAULT_CRS in SUPPORTED_PROJECT_CRS


def test_wgs84_to_projected_roundtrip_is_millimetre_accurate() -> None:
    """왕복 오차가 mm 급이어야 재투영이 '작동한다'고 말할 수 있다."""
    x, y = reproject_point(
        _SEOUL_LON_DEG, _SEOUL_LAT_DEG, from_crs="EPSG:4326", to_crs=DEFAULT_CRS
    )
    lon, lat = reproject_point(x, y, from_crs=DEFAULT_CRS, to_crs="EPSG:4326")

    # 위경도 1e-9 도 ≈ 0.1mm. 왕복이 이보다 크게 어긋나면 변환이 손실적이다.
    assert lon == pytest.approx(_SEOUL_LON_DEG, abs=1e-9)
    assert lat == pytest.approx(_SEOUL_LAT_DEG, abs=1e-9)


def test_projected_coordinates_land_in_the_expected_numeric_range() -> None:
    """always_xy 축 순서가 뒤집히지 않았는지 값의 크기로 확인한다.

    EPSG:5186 은 원점 가정(false easting 200km · northing 600km)이 있어
    X ≈ 20만m 대, Y ≈ 55만m 대가 나온다. 축이 뒤바뀌면 두 값이 서로 바뀌어
    이 범위를 벗어난다 — pyproj 의 축 순서는 조용히 틀리는 전형적 지점이다.
    """
    x, y = reproject_point(
        _SEOUL_LON_DEG, _SEOUL_LAT_DEG, from_crs="EPSG:4326", to_crs=DEFAULT_CRS
    )
    assert 150_000.0 < x < 250_000.0
    assert 500_000.0 < y < 600_000.0


def test_bessel_era_crs_is_refused() -> None:
    """구 측지계(Bessel)는 화이트리스트 밖이다 — 섞이면 수백 미터가 틀린다."""
    with pytest.raises(UnsupportedCrsError):
        assert_supported_project_crs("EPSG:5174")


def test_unknown_crs_string_is_refused() -> None:
    """해석 불가한 문자열을 통과시키지 않는다(fail-closed)."""
    with pytest.raises(UnsupportedCrsError):
        assert_supported_project_crs("NOT-A-CRS")


def test_assert_same_crs_refuses_mixed_frames() -> None:
    """INV-020 강제 — 서로 다른 좌표계 산출물의 직접 비교를 입구에서 막는다."""
    with pytest.raises(CrsMismatchError):
        assert_same_crs("EPSG:5186", "EPSG:4326")


def test_assert_same_crs_normalises_case_and_returns_the_canonical_value() -> None:
    """대소문자 차이는 혼용이 아니다 — 같은 좌표계를 다르다고 거부하면 안 된다."""
    assert assert_same_crs("EPSG:5186", "epsg:5186") == "EPSG:5186"


def test_assert_same_crs_refuses_an_empty_call() -> None:
    """비교할 값이 없는데 '같다'고 답하지 않는다."""
    with pytest.raises(ValueError):
        assert_same_crs()


def test_reproject_geometry_converts_polygon_rings() -> None:
    """AOI 폴리곤이 DSM 좌표계로 옮겨져야 래스터 마스킹에 쓸 수 있다."""
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [_SEOUL_LON_DEG, _SEOUL_LAT_DEG],
                [_SEOUL_LON_DEG + 0.001, _SEOUL_LAT_DEG],
                [_SEOUL_LON_DEG + 0.001, _SEOUL_LAT_DEG + 0.001],
                [_SEOUL_LON_DEG, _SEOUL_LAT_DEG],
            ]
        ],
    }
    converted = reproject_geometry(polygon, from_crs="EPSG:4326", to_crs=DEFAULT_CRS)

    assert converted["type"] == "Polygon"
    ring = converted["coordinates"][0]
    assert len(ring) == len(polygon["coordinates"][0])
    for x, y in ring:
        assert 150_000.0 < x < 250_000.0
        assert 500_000.0 < y < 600_000.0


def test_reproject_point_refuses_a_non_finite_result_instead_of_returning_inf() -> None:
    """2026-08-13 프로젝트 두뇌 재감사 확정 발견의 회귀 방지 — 유일한 critical 등급.

    pyproj 는 기본값으로 변환 불가 지점을 예외 대신 (inf, inf) 로 돌려준다.
    경도·위도가 뒤바뀐 좌표(위도 자리에 126.978 같은 범위 밖 값)가 실제로 그
    입력이다 — 옛 코드는 이 값을 그대로 반환했고, 폴리곤 꼭짓점 중 일부만
    이렇게 실패하면 rasterio 가 남은 꼭짓점만으로 도형을 그려 "정상 종료"해
    실제 구역의 일부만 잰 값이 오류 없이 나갔다.
    """
    with pytest.raises(ReprojectionFailedError):
        # x=37.5665(경도치고는 그럴듯하다), y=126.978 — 위도 범위(±90) 밖이라
        # pyproj 가 (inf, inf) 를 낸다(실측 확인).
        reproject_point(37.5665, 126.9780, from_crs="EPSG:4326", to_crs=DEFAULT_CRS)


def test_reproject_geometry_propagates_the_non_finite_refusal() -> None:
    """폴리곤 꼭짓점 하나만 실패해도 전체를 거부한다 — 일부만 조용히 통과시키지 않는다."""
    polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [_SEOUL_LON_DEG, _SEOUL_LAT_DEG],
                [_SEOUL_LON_DEG + 0.001, _SEOUL_LAT_DEG],
                [37.5665, 126.9780],  # 이 한 점만 위경도가 뒤바뀌었다
                [_SEOUL_LON_DEG, _SEOUL_LAT_DEG],
            ]
        ],
    }
    with pytest.raises(ReprojectionFailedError):
        reproject_geometry(polygon, from_crs="EPSG:4326", to_crs=DEFAULT_CRS)


def test_reproject_geometry_refuses_unsupported_geometry_type() -> None:
    """다룰 줄 모르는 지오메트리를 조용히 통과시키지 않는다."""
    with pytest.raises(ValueError):
        reproject_geometry(
            {"type": "GeometryCollection", "geometries": []},
            from_crs="EPSG:4326",
            to_crs=DEFAULT_CRS,
        )
