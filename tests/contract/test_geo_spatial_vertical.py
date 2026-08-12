"""측지 수직축 계약 — 타원체고↔정표고와 격자 부재 시 fail-closed (INV-020 수직축).

**이 파일의 핵심은 두 번째 테스트다.** 지오이드 격자가 없을 때 변환이 0 을
반환하면(즉 타원체고를 정표고라고 답하면) 한국에서 20~30m 틀린 값이 아무
경고 없이 흘러간다. 그 값은 "표고"라는 이름으로 설계 계획고와 비교되고,
비교 결과는 그럴듯해 보인다. 그래서 **없으면 없다고 거부하는 것**이 이 모듈의
존재 이유이며, 계약이 그것을 고정한다.

격자 데이터 자체는 이 저장소에 없다(risk `geoid-grid-provenance-unverified`).
따라서 보간 정확도는 합성 격자로만 검증하며, 실제 KNGeoid 격자의 정확도는
정식 취득·통합기준점 대조 이후의 별도 게이트다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from ksi_geo_spatial.vertical import (
    GeoidGrid,
    GeoidUnavailableError,
    VerticalDatum,
    ellipsoidal_to_orthometric,
    load_geoid_grid,
    orthometric_to_ellipsoidal,
)
from rasterio.transform import from_origin


def _write_grid(path: Path, values: np.ndarray) -> Path:
    """경도 126~130, 위도 34~38 범위를 덮는 합성 지오이드 격자.

    셀 크기 1도, 좌상단 원점 (126, 38). 픽셀 중심은 (126.5, 37.5) 부터다 —
    이 0.5 오프셋이 보간에서 조용히 틀리는 전형적 지점이라 테스트가 명시적으로
    픽셀 중심 좌표를 짚는다.
    """
    height, width = values.shape
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype="float64",
        crs="EPSG:4326",
        transform=from_origin(126.0, 38.0, 1.0, 1.0),
    ) as dataset:
        dataset.write(values, 1)
    return path


def test_missing_grid_refuses_instead_of_returning_zero() -> None:
    """격자가 없으면 거부한다 — 0 으로 대치하면 20~30m 가 조용히 틀린다."""
    with pytest.raises(GeoidUnavailableError):
        ellipsoidal_to_orthometric(50.0, lat_deg=37.5, lon_deg=127.5, grid=None)


def test_missing_grid_refuses_the_reverse_direction_too() -> None:
    """역변환도 같다 — 한쪽만 막으면 우회 경로가 생긴다."""
    with pytest.raises(GeoidUnavailableError):
        orthometric_to_ellipsoidal(20.0, lat_deg=37.5, lon_deg=127.5, grid=None)


def test_load_geoid_grid_returns_none_when_env_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """환경변수가 없으면 None 이다 — 없는 것을 있는 척하지 않는다."""
    monkeypatch.delenv("KSI_GEOID_GRID", raising=False)
    assert load_geoid_grid() is None


def test_load_geoid_grid_refuses_a_configured_but_missing_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """경로를 지정했는데 파일이 없으면 조용히 None 이 아니라 오류다.

    설정했다는 것은 "정표고를 쓰겠다"는 의도 표명이다. 그 의도가 오타나 배포
    누락으로 깨졌을 때 None 을 돌려주면 fail-closed 가 "격자 없음" 경로로
    빠져 원인이 가려진다.
    """
    monkeypatch.setenv("KSI_GEOID_GRID", str(tmp_path / "does-not-exist.tif"))
    with pytest.raises(GeoidUnavailableError):
        load_geoid_grid()


def test_height_at_pixel_centre_returns_the_stored_value(tmp_path: Path) -> None:
    """픽셀 중심에서는 저장값 그대로 — 0.5 오프셋이 틀리면 이웃 셀 값이 나온다."""
    values = np.array(
        [
            [10.0, 20.0, 30.0, 40.0],
            [11.0, 21.0, 31.0, 41.0],
            [12.0, 22.0, 32.0, 42.0],
            [13.0, 23.0, 33.0, 43.0],
        ]
    )
    grid = GeoidGrid.from_path(_write_grid(tmp_path / "geoid.tif", values))

    # (126.5, 37.5) = 0행 0열의 픽셀 중심.
    assert grid.height_at(lat_deg=37.5, lon_deg=126.5) == pytest.approx(10.0)
    # (127.5, 36.5) = 1행 1열.
    assert grid.height_at(lat_deg=36.5, lon_deg=127.5) == pytest.approx(21.0)


def test_height_at_midpoint_is_bilinear(tmp_path: Path) -> None:
    """셀 중심 사이는 이중선형 — 최근접 이웃으로 대충 하지 않는다."""
    values = np.array(
        [
            [0.0, 10.0],
            [20.0, 30.0],
        ]
    )
    grid = GeoidGrid.from_path(_write_grid(tmp_path / "geoid.tif", values))

    # (126.5, 37.5)=0.0 과 (127.5, 37.5)=10.0 의 중간 → 5.0
    assert grid.height_at(lat_deg=37.5, lon_deg=127.0) == pytest.approx(5.0)
    # 네 셀의 정중앙 (127.0, 37.0) → (0+10+20+30)/4 = 15.0
    assert grid.height_at(lat_deg=37.0, lon_deg=127.0) == pytest.approx(15.0)


def test_height_outside_the_grid_is_refused(tmp_path: Path) -> None:
    """격자 범위 밖은 외삽하지 않는다 — INV-023 과 같은 원칙(fail-closed)."""
    values = np.array([[1.0, 2.0], [3.0, 4.0]])
    grid = GeoidGrid.from_path(_write_grid(tmp_path / "geoid.tif", values))

    with pytest.raises(GeoidUnavailableError):
        grid.height_at(lat_deg=20.0, lon_deg=127.0)


def test_conversion_applies_the_geoid_separation(tmp_path: Path) -> None:
    """H = h - N. 부호가 뒤집히면 40m 이상 어긋난다."""
    values = np.full((2, 2), 25.0)
    grid = GeoidGrid.from_path(_write_grid(tmp_path / "geoid.tif", values))

    assert ellipsoidal_to_orthometric(
        75.0, lat_deg=37.5, lon_deg=126.5, grid=grid
    ) == pytest.approx(50.0)
    assert orthometric_to_ellipsoidal(
        50.0, lat_deg=37.5, lon_deg=126.5, grid=grid
    ) == pytest.approx(75.0)


def test_vertical_datum_values_are_explicit() -> None:
    """산출물이 어느 수직기준인지 wire 에 실릴 값 — 문자열을 지어내지 않는다."""
    assert VerticalDatum.ELLIPSOIDAL.value == "ellipsoidal"
    assert VerticalDatum.ORTHOMETRIC_KNGEOID2018.value == "orthometric_kngeoid2018"


# ---------------------------------------------------------------------------
# 실 KNGeoid24 격자 대조 (risk `geoid-grid-provenance-unverified`).
#
# 격자 파일 자체(data/geoid/KNGeoid24.tif)는 대용량 바이너리라 git에 커밋하지
# 않는다(.gitignore `/data/geoid/`) — tools/convert_geoid_grid.py 로 재생성하거나
# docs/geo/GEOID_ACQUISITION.md 의 취득 경로를 따른다. 없는 환경(CI 포함)에서는
# 이 아래 테스트 전부 skip — 위의 합성 격자 테스트들이 보간 수학 자체는 상시
# 검증하므로 skip이 "기능 미검증"은 아니다(별도 게이트, test_dfine_detector.py 와
# 같은 관례).
# ---------------------------------------------------------------------------

_REAL_KNGEOID24_PATH = Path("data/geoid/KNGeoid24.tif")

pytestmark_real_grid = pytest.mark.skipif(
    not _REAL_KNGEOID24_PATH.is_file(),
    reason=(
        "실 KNGeoid24 격자 없음 — tools/convert_geoid_grid.py 로 변환 후 실행"
        "(docs/geo/GEOID_ACQUISITION.md 취득·변환 절차 참조)"
    ),
)


@pytestmark_real_grid
def test_real_kngeoid24_grid_returns_seoul_geoid_height_in_expected_range() -> None:
    """서울시청 지점 지오이드고가 한국 상식 범위[15,35]m 안이고 실측값과 근접한지.

    기대값 23.325m 는 이 파일로 실제 변환·조회해 얻은 값을 고정한 것이다
    (KNGeoid18 공개 문헌상 같은 지점 23.31m 와 1cm 남짓 차이 — 모델 버전 개선
    범위로 타당하다). 회귀가 생기면(격자 재변환·좌표 규약 변경 등) 이 값이
    바뀐다.
    """
    grid = GeoidGrid.from_path(_REAL_KNGEOID24_PATH)
    n = grid.height_at(lat_deg=37.5665, lon_deg=126.9780)
    assert 15.0 <= n <= 35.0
    assert n == pytest.approx(23.325, abs=0.01)


@pytestmark_real_grid
def test_load_geoid_grid_via_env_wires_the_real_grid_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KSI_GEOID_GRID 가 실 파일을 가리킬 때 load_geoid_grid()→변환까지 실제로 동작.

    이것이 ``load_geoid_grid()`` 가 기대하는 "configured" 경로 메커니즘 — 파일
    경로를 코드에 하드코드하지 않고 환경변수로만 연결한다(모듈 docstring 의
    "미설정과 설정-실패를 다르게 다룬다" 설계를 그대로 통과).
    """
    monkeypatch.setenv("KSI_GEOID_GRID", str(_REAL_KNGEOID24_PATH.resolve()))
    grid = load_geoid_grid()
    assert grid is not None

    # H = h - N. 서울 부근 임의 타원체고 100.0m 로 정표고를 계산해 왕복 확인.
    h = 100.0
    orthometric = ellipsoidal_to_orthometric(h, lat_deg=37.5665, lon_deg=126.9780, grid=grid)
    assert orthometric == pytest.approx(h - 23.325, abs=0.01)
    roundtrip = orthometric_to_ellipsoidal(
        orthometric, lat_deg=37.5665, lon_deg=126.9780, grid=grid
    )
    assert roundtrip == pytest.approx(h, abs=1e-6)
