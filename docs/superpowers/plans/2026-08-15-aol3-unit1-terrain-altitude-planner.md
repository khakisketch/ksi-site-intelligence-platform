# AOL-3 Unit 1 — 지형추종 고도 계획기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 공간모델(DTM/DSM)에서 임의 지점의 표고를 읽는 유틸과, 그 표고로부터 웨이포인트별
안전 비행고도를 계산하는 순수 함수를 만든다 — 실제 비행 제어·KMZ 발급은 이 범위 밖이다.

**Architecture:** 두 계층으로 분리한다. `ksi_geo_spatial.terrain.TerrainGrid` 는 GeoTIFF 를 열어
지점 표고를 읽는 계층(`GeoidGrid` 와 동형 — 격자 밖은 외삽 없이 거부). `ksi_mission_planning.terrain`
은 이미 샘플링된 숫자만 받는 순수 함수 계층이다 — Core 의 공간모델 코드를 import할 수 없다는
빌드 게이트(anti-circularity gate) 때문에, 이 둘을 실제로 잇는 배선(현장→DTM 조회→샘플링)은
이번 계획에 없다(아직 소비자가 없다).

**Tech Stack:** Python 3.12 (uv workspace), numpy, rasterio, pyproj(경유: `ksi_geo_spatial.crs`), pytest

**Spec:** `docs/superpowers/specs/2026-08-15-aol3-unit1-terrain-altitude-planner-design.md`

## Global Constraints

- 테스트 실행은 `ulimit -n 8192 && uv run pytest <path> -v`(파일 핸들 제한 회피 — 이 저장소 관례).
- `ruff format --check` 는 이 저장소의 게이트가 **아니다**(CI 미실행). `uv run ruff check <path>` 는 게이트다.
- 커밋 전 관련 테스트를 실제로 실행해 통과를 확인한다(자기보고 금지).
- 두 모듈 다 순수 함수/데이터클래스다 — `assemble_app`·HTTP 서버 조립 불필요. 전부 단위/계약
  테스트 수준에서 끝난다.
- `packages/mission-planning/src/ksi_mission_planning/terrain.py` 는 `ksi_core.processing_jobs`·
  `ksi_core.spatial_model`·`processing_artifact`·`point_cloud` 문자열을 포함해서는 안 된다
  (`tests/contract/test_anti_circularity_gate.py` 가 빌드 시점에 강제한다 — 이 계획의 파일은
  그 검사에 자동으로 포함된다, 별도 등록 불필요).
- INV-014: 고도 상한 150m 는 `FlightEnvelope.max_altitude_m` 자체가 이미 강제한다 — 이 계획의
  출력은 그 봉투를 존중만 하면 된다(별도로 150 을 하드코딩하지 않는다).

---

## File Structure

| 파일 | 책임 |
|---|---|
| `packages/geo-spatial/src/ksi_geo_spatial/terrain.py` (신규) | DTM/DSM GeoTIFF 1건에서 임의 지점의 표고를 이중선형 보간으로 읽는다. `GeoidGrid` 와 동형이나, DTM/DSM 은 보통 투영좌표계(예 EPSG:5186)라 질의 지점(WGS84)을 그 좌표계로 재투영하는 단계가 추가된다. |
| `tests/contract/test_geo_spatial_terrain.py` (신규) | 위 모듈의 계약 테스트 — `test_geo_spatial_vertical.py` 와 동형 구조. |
| `packages/mission-planning/src/ksi_mission_planning/terrain.py` (신규) | 웨이포인트별 표고 샘플(이미 읽어온 값)에서 안전 비행고도·여유값·상태를 계산하는 순수 함수. |
| `tests/contract/test_terrain_altitude_planner.py` (신규) | 위 함수의 계약 테스트 — `test_reobservation_capture.py` 와 동형 구조(순수 함수·rationale 리스트 검증). |

---

## Task 1: `ksi_geo_spatial.terrain` — 지점 표고 샘플러

**Files:**
- Create: `packages/geo-spatial/src/ksi_geo_spatial/terrain.py`
- Test: `tests/contract/test_geo_spatial_terrain.py`

**Interfaces:**
- Consumes: `ksi_geo_spatial.crs.normalise_crs(crs: str) -> str`, `ksi_geo_spatial.crs.reproject_point(x: float, y: float, *, from_crs: str, to_crs: str) -> tuple[float, float]`, `ksi_geo_spatial.crs.UnsupportedCrsError`, `ksi_geo_spatial.crs.ReprojectionFailedError`(둘 다 기존 모듈에 이미 있음, 수정 없음).
- Produces: `TerrainUnavailableError`(예외), `TerrainGrid`(dataclass, `from_path(path: Path) -> TerrainGrid` classmethod + `elevation_at(*, lat_deg: float, lon_deg: float) -> float` 메서드) — Task 2 는 이 타입들을 쓰지 않는다(범위 밖, 계획 헤더 참조)지만 나중에 Core 배선이 이 타입을 쓴다.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/contract/test_geo_spatial_terrain.py` 를 새로 만든다:

```python
"""지형고도 격자(DTM/DSM) 계약 — 임의 지점 표고 샘플링, fail-closed.

GeoidGrid(vertical.py)와 자매 모듈이다. 차이는 하나 — DTM/DSM 은 보통
투영좌표계(예 EPSG:5186)라 질의 지점(WGS84)을 그 좌표계로 재투영하는 단계가
있다. 그래서 이 파일은 investigate 지오이드 테스트의 격자수학 검증(픽셀중심·
이중선형·범위밖 거부)을 그대로 반복하되, 추가로 재투영·nodata 처리를 검증한다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from ksi_geo_spatial.crs import UnsupportedCrsError
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

    # 투영좌표 (200000.5, 499999.5) = 0행 0열 픽셀 중심 → 그 지점의 WGS84 좌표를
    # pyproj 로 역산하지 않고, 왕복 검증한다: reproject_point 로 얻은 위경도를
    # 다시 elevation_at 에 넣으면 같은 셀을 가리켜야 한다.
    from ksi_geo_spatial.crs import reproject_point

    lon, lat = reproject_point(200_000.5, 499_999.5, from_crs="EPSG:5186", to_crs="EPSG:4326")
    assert grid.elevation_at(lat_deg=lat, lon_deg=lon) == pytest.approx(10.0)


def test_bilinear_interpolation_between_cells(tmp_path: Path) -> None:
    """셀 중심 사이는 이중선형 — 최근접 이웃으로 대충 하지 않는다."""
    from ksi_geo_spatial.crs import reproject_point

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

    from ksi_geo_spatial.crs import reproject_point

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
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_geo_spatial_terrain.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ksi_geo_spatial.terrain'`

- [ ] **Step 3: 최소 구현 작성**

`packages/geo-spatial/src/ksi_geo_spatial/terrain.py` 를 새로 만든다:

```python
"""지형고도 격자(DTM/DSM) — 임의 지점의 표고를 이중선형 보간으로 읽는다.

``vertical.py`` 의 ``GeoidGrid`` 와 계약이 같다: 격자 밖 지점은 외삽하지 않고
거부한다(``TerrainUnavailableError``, 값을 지어내지 않는다). 차이는 하나다 —
지오이드 격자는 언제나 EPSG:4326(경위도) 기준으로 배포되지만, DTM/DSM 은
재구성 파이프라인이 내는 투영좌표계(이 저장소는 EPSG:5186 계열, INV-020)가
보통이다. 그래서 질의 지점(WGS84)을 격자 자신의 좌표계로 먼저 재투영한 뒤
같은 픽셀-중심 이중선형 보간을 적용한다.

지오이드 격자(전국 공용 1개 파일)와 달리 DTM/DSM 은 현장·작업마다 다른
파일이라 전역 싱글턴 로더를 두지 않는다 — 호출자가 그때그때
``TerrainGrid.from_path()`` 로 연다.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from numpy.typing import NDArray

from ksi_geo_spatial.crs import assert_supported_project_crs, normalise_crs, reproject_point

_QUERY_CRS = "EPSG:4326"
_CHUNK_BYTES = 1024 * 1024


class TerrainUnavailableError(RuntimeError):
    """그 지점의 지형고도를 구할 수 없다 — 0 이나 이웃 값으로 대치하지 않고 거부한다."""


@dataclass(frozen=True, slots=True)
class TerrainGrid:
    """단일 표고 래스터(DTM 또는 DSM) 1건 — 원본 좌표계 그대로 보관한다."""

    values: NDArray[np.float64]
    #: 좌상단 픽셀의 **모서리** 좌표(격자 자신의 좌표계, m 또는 도)와 셀 크기.
    origin_x: float
    origin_y: float
    cell_size_x: float
    cell_size_y: float
    #: 정규화된 좌표계 문자열(``EPSG:n``) — EPSG:4326 이 아니면 투영좌표계
    #: 화이트리스트(INV-020)를 통과한 값만 여기 온다.
    crs: str
    source_name: str | None = None
    source_sha256: str | None = None

    @classmethod
    def from_path(cls, path: Path) -> TerrainGrid:
        with rasterio.open(path) as dataset:
            if dataset.count != 1:
                raise TerrainUnavailableError(
                    f"지형 격자는 단일 밴드여야 한다 (밴드 {dataset.count}개): {path}"
                )
            if dataset.crs is None:
                raise TerrainUnavailableError(
                    f"좌표계 정보가 없는 래스터다 — 어느 좌표계인지 파일이 말하지 않는다: {path}"
                )
            crs_wkt = dataset.crs.to_wkt()
            values = dataset.read(1).astype(np.float64)
            nodata = dataset.nodata
            transform = dataset.transform

        normalised = normalise_crs(crs_wkt)
        crs = normalised if normalised == _QUERY_CRS else assert_supported_project_crs(normalised)

        if nodata is not None and not math.isnan(nodata):
            values = np.where(np.isclose(values, nodata), np.nan, values)

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
                digest.update(chunk)

        return cls(
            values=values,
            origin_x=float(transform.c),
            origin_y=float(transform.f),
            cell_size_x=float(transform.a),
            # e 는 북쪽이 위인 격자에서 음수다 — 절대값이 셀 높이.
            cell_size_y=float(-transform.e),
            crs=crs,
            source_name=path.name,
            source_sha256=digest.hexdigest(),
        )

    def elevation_at(self, *, lat_deg: float, lon_deg: float) -> float:
        """그 지점의 표고(m). 격자 밖·nodata 면 거부한다(외삽·대치 금지).

        **픽셀 중심 기준으로 보간한다**(``GeoidGrid.height_at`` 과 동일 이유 —
        래스터 원점은 좌상단 픽셀의 *모서리*라 0.5 셀 보정이 필요하다).
        """
        x, y = reproject_point(lon_deg, lat_deg, from_crs=_QUERY_CRS, to_crs=self.crs)

        rows, cols = self.values.shape
        col = (x - self.origin_x) / self.cell_size_x - 0.5
        row = (self.origin_y - y) / self.cell_size_y - 0.5

        if not (math.isfinite(col) and math.isfinite(row)):
            raise TerrainUnavailableError(
                f"격자 좌표를 계산할 수 없다 (lat={lat_deg}, lon={lon_deg})"
            )
        if col < 0.0 or row < 0.0 or col > cols - 1 or row > rows - 1:
            raise TerrainUnavailableError(
                f"지점 (lat={lat_deg}, lon={lon_deg}) 이 지형 격자 범위 밖이다 — 외삽하지 않는다"
            )

        col0 = int(math.floor(col))
        row0 = int(math.floor(row))
        col1 = min(col0 + 1, cols - 1)
        row1 = min(row0 + 1, rows - 1)
        fx = col - col0
        fy = row - row0

        top = self.values[row0, col0] * (1.0 - fx) + self.values[row0, col1] * fx
        bottom = self.values[row1, col0] * (1.0 - fx) + self.values[row1, col1] * fx
        value = top * (1.0 - fy) + bottom * fy

        if not math.isfinite(float(value)):
            raise TerrainUnavailableError(
                f"지점 (lat={lat_deg}, lon={lon_deg}) 에 유효한 표고가 없다 "
                "(nodata 구멍이거나 인접 셀 중 하나가 nodata)"
            )
        return float(value)


__all__ = ["TerrainGrid", "TerrainUnavailableError"]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_geo_spatial_terrain.py -v`
Expected: PASS(7건 전부)

- [ ] **Step 5: lint**

Run: `uv run ruff check packages/geo-spatial/src/ksi_geo_spatial/terrain.py tests/contract/test_geo_spatial_terrain.py`
Expected: `All checks passed!`

- [ ] **Step 6: 커밋**

```bash
git add packages/geo-spatial/src/ksi_geo_spatial/terrain.py tests/contract/test_geo_spatial_terrain.py
git commit -m "feat(geo-spatial): sample DTM/DSM elevation at a point, fail-closed"
```

---

## Task 2: `ksi_mission_planning.terrain` — 지형추종 고도 계획기

**Files:**
- Create: `packages/mission-planning/src/ksi_mission_planning/terrain.py`
- Test: `tests/contract/test_terrain_altitude_planner.py`

**Interfaces:**
- Consumes: `ksi_geo_core.frames.great_circle_distance_m(lat1_deg, lon1_deg, lat2_deg, lon2_deg) -> float`(기존, 수정 없음), `ksi_mission_planning.geometry.GeoPoint`(기존, `lat_deg`/`lon_deg` 필드), `ksi_mission_contracts.models.FlightEnvelope`(기존, `min_altitude_m`/`max_altitude_m` 필드, `TYPE_CHECKING` 아래에서만 import — 순환 회피, `reobservation.py` 관례 동일).
- Produces: `AltitudeSegmentStatus`(StrEnum: `OK`/`TERRAIN_DATA_MISSING`/`ENVELOPE_VIOLATION`/`RATE_LIMIT_EXCEEDED`), `WaypointTerrainSample`(dataclass), `WaypointAltitudePlan`(dataclass), `TerrainAltitudeProfile`(dataclass), `compute_altitude_profile(*, samples, target_agl_m, safety_margin_m, max_altitude_change_ratio, envelope, provenance) -> TerrainAltitudeProfile`. **Task 1 의 `TerrainGrid`/`TerrainUnavailableError` 를 이 파일이 import하지 않는다** — `WaypointTerrainSample.terrain_elevation_m`/`surface_elevation_m` 은 이미 샘플링된 `float | None` 이다(계획 헤더의 범위 제약 참조).

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/contract/test_terrain_altitude_planner.py` 를 새로 만든다:

```python
"""지형추종 비행고도 계획 계약 — 순수 함수, 결정론적 (ADR-KSI-019 G6, AOL-3 Unit 1).

계산 자체가 아니라 **실패 처리**가 이 파일의 핵심이다: 지형고도를 모르는
지점은 값을 지어내지 않고, 봉투를 넘는 지점은 조용히 잘라내지 않고 거부하고,
DSM 이 없으면 여유값을 0으로 채우지 않는다 — reobservation.py 의 rationale
관례를 그대로 잇는다.
"""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from ksi_mission_planning.geometry import GeoPoint
from ksi_mission_planning.terrain import (
    AltitudeSegmentStatus,
    TerrainAltitudeProfile,
    WaypointAltitudePlan,
    WaypointTerrainSample,
    compute_altitude_profile,
)


def _envelope(*, min_altitude_m: float = 20.0, max_altitude_m: float = 120.0) -> Mock:
    """FlightEnvelope 대역 — 이 함수가 실제로 읽는 두 필드만 흉내 낸다."""
    envelope = Mock()
    envelope.min_altitude_m = min_altitude_m
    envelope.max_altitude_m = max_altitude_m
    return envelope


def _point(lat_deg: float, lon_deg: float) -> GeoPoint:
    return GeoPoint(lat_deg=lat_deg, lon_deg=lon_deg)


def test_normal_path_is_all_ok() -> None:
    """정상 경로 — 전 구간 OK, 계산된 고도가 지형고도+목표AGL+여유값과 같다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5000, 127.0000), terrain_elevation_m=50.0),
        WaypointTerrainSample(waypoint=_point(37.5001, 127.0000), terrain_elevation_m=52.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        target_agl_m=40.0,
        safety_margin_m=5.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(),
        provenance="job-epoch-1",
    )

    assert profile.all_ok is True
    assert profile.provenance == "job-epoch-1"
    assert len(profile.segments) == 2
    assert profile.segments[0].status is AltitudeSegmentStatus.OK
    assert profile.segments[0].commanded_altitude_m == pytest.approx(95.0)  # 50+40+5
    assert profile.segments[1].commanded_altitude_m == pytest.approx(97.0)  # 52+40+5


def test_missing_terrain_data_fails_only_that_segment() -> None:
    """지형고도를 모르는 지점은 그 지점만 실패한다 — 이웃 값으로 보간하지 않는다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5000, 127.0000), terrain_elevation_m=50.0),
        WaypointTerrainSample(waypoint=_point(37.5001, 127.0000), terrain_elevation_m=None),
        WaypointTerrainSample(waypoint=_point(37.5002, 127.0000), terrain_elevation_m=54.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        target_agl_m=40.0,
        safety_margin_m=5.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(),
        provenance="p",
    )

    assert profile.all_ok is False
    assert profile.segments[0].status is AltitudeSegmentStatus.OK
    assert profile.segments[1].status is AltitudeSegmentStatus.TERRAIN_DATA_MISSING
    assert profile.segments[1].commanded_altitude_m is None
    assert profile.segments[1].rationale  # 근거 없는 실패는 검토할 수 없다
    # 세 번째 지점은 두 번째의 실패에 영향받지 않는다 — 자기 지형고도로 정상 계산.
    assert profile.segments[2].status is AltitudeSegmentStatus.OK
    assert profile.segments[2].commanded_altitude_m == pytest.approx(99.0)  # 54+40+5


def test_altitude_beyond_the_envelope_is_rejected_not_clamped() -> None:
    """봉투를 넘는 고도는 조용히 잘라내지 않고 거부한다 — 신호를 지우지 않는다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5000, 127.0000), terrain_elevation_m=200.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        target_agl_m=40.0,
        safety_margin_m=5.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(min_altitude_m=20.0, max_altitude_m=120.0),
        provenance="p",
    )

    assert profile.segments[0].status is AltitudeSegmentStatus.ENVELOPE_VIOLATION
    assert profile.segments[0].commanded_altitude_m is None
    assert "245" in profile.segments[0].rationale[0] or "245.0" in profile.segments[0].rationale[0]


def test_altitude_change_rate_beyond_ratio_is_rejected() -> None:
    """이웃 지점 대비 고도변화가 비율 상한을 넘으면 거부한다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.50000, 127.00000), terrain_elevation_m=50.0),
        # ~11.1m 북쪽, 지형고도가 30m 뛴다 — 비율 상한 0.5 를 크게 넘는다(30/11.1≈2.7).
        WaypointTerrainSample(waypoint=_point(37.50010, 127.00000), terrain_elevation_m=80.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        target_agl_m=40.0,
        safety_margin_m=0.0,
        max_altitude_change_ratio=0.5,
        envelope=_envelope(),
        provenance="p",
    )

    assert profile.segments[0].status is AltitudeSegmentStatus.OK
    assert profile.segments[1].status is AltitudeSegmentStatus.RATE_LIMIT_EXCEEDED
    assert profile.segments[1].commanded_altitude_m is None


def test_clearance_is_none_without_a_surface_sample() -> None:
    """DSM(지표고)이 없으면 여유값은 None 이다 — 0 으로 채우지 않는다."""
    samples = [
        WaypointTerrainSample(waypoint=_point(37.5, 127.0), terrain_elevation_m=50.0),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        target_agl_m=40.0,
        safety_margin_m=5.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(),
        provenance="p",
    )

    assert profile.segments[0].clearance_m is None


def test_clearance_is_computed_when_a_surface_sample_is_given() -> None:
    """DSM 이 있으면 여유값 = 계획고도 - 지표고."""
    samples = [
        WaypointTerrainSample(
            waypoint=_point(37.5, 127.0), terrain_elevation_m=50.0, surface_elevation_m=60.0
        ),
    ]

    profile = compute_altitude_profile(
        samples=samples,
        target_agl_m=40.0,
        safety_margin_m=5.0,
        max_altitude_change_ratio=1.0,
        envelope=_envelope(),
        provenance="p",
    )

    # 계획고도 = 50+40+5 = 95, 여유값 = 95-60 = 35.
    assert profile.segments[0].clearance_m == pytest.approx(35.0)


def test_empty_samples_is_rejected() -> None:
    """빈 경로의 고도 계획은 정의되지 않는다 — 조용히 빈 결과를 내지 않는다."""
    with pytest.raises(ValueError, match="samples"):
        compute_altitude_profile(
            samples=[],
            target_agl_m=40.0,
            safety_margin_m=5.0,
            max_altitude_change_ratio=1.0,
            envelope=_envelope(),
            provenance="p",
        )


def test_non_positive_target_agl_is_rejected() -> None:
    with pytest.raises(ValueError, match="target_agl_m"):
        compute_altitude_profile(
            samples=[WaypointTerrainSample(waypoint=_point(37.5, 127.0), terrain_elevation_m=50.0)],
            target_agl_m=0.0,
            safety_margin_m=5.0,
            max_altitude_change_ratio=1.0,
            envelope=_envelope(),
            provenance="p",
        )
```

- [ ] **Step 2: 테스트가 실패하는지 확인**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_terrain_altitude_planner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ksi_mission_planning.terrain'`

- [ ] **Step 3: 최소 구현 작성**

`packages/mission-planning/src/ksi_mission_planning/terrain.py` 를 새로 만든다:

```python
"""지형추종 비행고도 계획 — 순수 함수 (ADR-KSI-019 G6, AOL-3 Unit 1).

## 왜 순수 함수이고 무엇을 모르는가

``reobservation.py`` 와 같은 이유로 이 패키지에 산다 — 판정 규칙은 Core 의
저장소·HTTP 표면과 무관하다. 게다가 여기는 **구조적으로 더 강하게** 그렇다:
``tests/contract/test_anti_circularity_gate.py`` 가 이 패키지 전체에서
``ksi_core.processing_jobs``·``ksi_core.spatial_model``·``processing_artifact``·
``point_cloud`` 문자열을 금지한다(ADR-KSI-019 D3 반순환 불변식). 그래서 이
모듈은 "현장에 DTM 이 있는가"를 절대 스스로 묻지 않는다 — 호출자가 이미 읽어온
표고값(:class:`WaypointTerrainSample`)만 받는다.

## 무엇을 하지 않는가

실제 비행 명령·KMZ 발급과 이어지지 않는다(``wpml.py`` 는 지금 웨이포인트마다
다른 고도를 거부하도록 이미 짜여 있다 — 그 파일은 이 계획의 범위 밖이다).
장애물 회피·동적 재계획도 아니다 — 이 계층의 출력은 사전 계획 데이터일 뿐이다.

## 고도변화율을 왜 "수평거리 대비 비율"로 표현하는가

이 저장소 어디에도 상승·하강률(m/s) 제약이 없고, 이 계층은 속도 데이터를 갖지
않는다(``WaylineParams.autoFlightSpeedMs`` 는 수평 속도다). 시간 기반 제약을
흉내 내려면 속도 가정을 지어내야 하므로, 대신 기하학적으로 검증 가능한 값
(수평거리 대비 고도변화 비율)을 쓴다 — ADR-KSI-011 D3 의 간격 상한과 같은 지위의
**정책값**이다(물리 증명이 아니라 보수적 시작점).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from ksi_geo_core.frames import great_circle_distance_m

from ksi_mission_planning.geometry import GeoPoint

if TYPE_CHECKING:
    from ksi_mission_contracts.models import FlightEnvelope


class AltitudeSegmentStatus(StrEnum):
    """세그먼트 1개(웨이포인트 1개)의 판정 — 네 가지뿐이다."""

    OK = "OK"
    #: 이 지점의 지형고도를 모른다(보간·추정하지 않는다).
    TERRAIN_DATA_MISSING = "TERRAIN_DATA_MISSING"
    #: 계산된 고도가 비행 봉투 [min,max] 밖 — 조용히 잘라내지 않고 거부한다.
    ENVELOPE_VIOLATION = "ENVELOPE_VIOLATION"
    #: 이전 지점 대비 고도변화가 수평거리 대비 상한을 넘는다.
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"


@dataclass(frozen=True, slots=True)
class WaypointTerrainSample:
    """웨이포인트 1개 + 이미 읽어온 표고값 — 이 모듈은 이 값을 어떻게 구했는지 모른다."""

    waypoint: GeoPoint
    #: DTM 표고(m). 그 지점을 몰라서 못 구했으면 None(0 이나 이웃값으로 채우지 않는다).
    terrain_elevation_m: float | None
    #: DSM 표고(m, 선택) — 있으면 여유값(clearance) 계산에 쓴다.
    surface_elevation_m: float | None = None


@dataclass(frozen=True, slots=True)
class WaypointAltitudePlan:
    """웨이포인트 1개의 계산 결과 — 값과 판정 근거를 함께 들고 다닌다."""

    waypoint: GeoPoint
    terrain_elevation_m: float | None
    #: 지형고도 + 목표 지상고 + 안전여유. status 가 OK 일 때만 값이 있다.
    commanded_altitude_m: float | None
    #: commanded_altitude_m - surface_elevation_m. DSM 이 없으면 None.
    clearance_m: float | None
    status: AltitudeSegmentStatus
    #: 사람이 읽는 근거 문장 — 실패도 성공도 이유 없이 나오지 않는다.
    rationale: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TerrainAltitudeProfile:
    """경로 전체의 계산 결과."""

    segments: tuple[WaypointAltitudePlan, ...]
    #: 이 표고값들이 어느 공간모델/작업물에서 왔는지 — 계산에 관여하지 않고 통과만 한다.
    provenance: str
    #: 전 세그먼트가 OK 일 때만 참 — 호출자가 즉시 판단할 수 있게.
    all_ok: bool


def compute_altitude_profile(
    *,
    samples: Sequence[WaypointTerrainSample],
    target_agl_m: float,
    safety_margin_m: float,
    max_altitude_change_ratio: float,
    envelope: FlightEnvelope,
    provenance: str,
) -> TerrainAltitudeProfile:
    """경로의 각 지점에서 안전한 지형추종 고도를 계산한다 — 순수 함수.

    Raises:
        ValueError: ``samples`` 가 비었거나, ``target_agl_m``/``max_altitude_change_ratio``
            가 양수가 아니거나, ``safety_margin_m`` 이 음수일 때.
    """
    if not samples:
        raise ValueError("samples 는 비어 있을 수 없다 — 빈 경로의 고도 계획은 정의되지 않는다")
    if target_agl_m <= 0.0:
        raise ValueError(f"target_agl_m 은 양수여야 한다: {target_agl_m}")
    if safety_margin_m < 0.0:
        raise ValueError(f"safety_margin_m 은 음수일 수 없다: {safety_margin_m}")
    if max_altitude_change_ratio <= 0.0:
        raise ValueError(
            f"max_altitude_change_ratio 는 양수여야 한다: {max_altitude_change_ratio}"
        )

    segments: list[WaypointAltitudePlan] = []
    previous: WaypointAltitudePlan | None = None

    for sample in samples:
        if sample.terrain_elevation_m is None:
            segment = WaypointAltitudePlan(
                waypoint=sample.waypoint,
                terrain_elevation_m=None,
                commanded_altitude_m=None,
                clearance_m=None,
                status=AltitudeSegmentStatus.TERRAIN_DATA_MISSING,
                rationale=("이 지점의 지형고도를 모른다 — 값을 지어내지 않는다",),
            )
            segments.append(segment)
            previous = segment
            continue

        commanded = sample.terrain_elevation_m + target_agl_m + safety_margin_m

        if commanded < envelope.min_altitude_m or commanded > envelope.max_altitude_m:
            segment = WaypointAltitudePlan(
                waypoint=sample.waypoint,
                terrain_elevation_m=sample.terrain_elevation_m,
                commanded_altitude_m=None,
                clearance_m=None,
                status=AltitudeSegmentStatus.ENVELOPE_VIOLATION,
                rationale=(
                    f"계산된 고도 {commanded:.1f}m 가 비행 봉투 "
                    f"[{envelope.min_altitude_m:.1f}, {envelope.max_altitude_m:.1f}]m 밖이다 — "
                    "지형 때문에 이 지점은 이 목표 지상고로 날 수 없다",
                ),
            )
            segments.append(segment)
            previous = segment
            continue

        if (
            previous is not None
            and previous.status is AltitudeSegmentStatus.OK
            and previous.commanded_altitude_m is not None
        ):
            horizontal_m = great_circle_distance_m(
                previous.waypoint.lat_deg,
                previous.waypoint.lon_deg,
                sample.waypoint.lat_deg,
                sample.waypoint.lon_deg,
            )
            altitude_delta_m = abs(commanded - previous.commanded_altitude_m)
            if (
                horizontal_m > 0.0
                and altitude_delta_m / horizontal_m > max_altitude_change_ratio
            ):
                segment = WaypointAltitudePlan(
                    waypoint=sample.waypoint,
                    terrain_elevation_m=sample.terrain_elevation_m,
                    commanded_altitude_m=None,
                    clearance_m=None,
                    status=AltitudeSegmentStatus.RATE_LIMIT_EXCEEDED,
                    rationale=(
                        f"이전 지점 대비 고도변화 {altitude_delta_m:.1f}m / 수평거리 "
                        f"{horizontal_m:.1f}m 가 상한 {max_altitude_change_ratio} 를 넘는다",
                    ),
                )
                segments.append(segment)
                previous = segment
                continue

        clearance = (
            commanded - sample.surface_elevation_m
            if sample.surface_elevation_m is not None
            else None
        )
        segment = WaypointAltitudePlan(
            waypoint=sample.waypoint,
            terrain_elevation_m=sample.terrain_elevation_m,
            commanded_altitude_m=commanded,
            clearance_m=clearance,
            status=AltitudeSegmentStatus.OK,
            rationale=(
                f"지형고도 {sample.terrain_elevation_m:.1f}m + 목표 지상고 "
                f"{target_agl_m:.1f}m + 안전여유 {safety_margin_m:.1f}m = {commanded:.1f}m",
            ),
        )
        segments.append(segment)
        previous = segment

    return TerrainAltitudeProfile(
        segments=tuple(segments),
        provenance=provenance,
        all_ok=all(s.status is AltitudeSegmentStatus.OK for s in segments),
    )


__all__ = [
    "AltitudeSegmentStatus",
    "TerrainAltitudeProfile",
    "WaypointAltitudePlan",
    "WaypointTerrainSample",
    "compute_altitude_profile",
]
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_terrain_altitude_planner.py -v`
Expected: PASS(9건 전부)

- [ ] **Step 5: 반순환 게이트가 여전히 통과하는지 확인** (이 계획에서 가장 중요한 회귀 검사)

Run: `ulimit -n 8192 && uv run pytest tests/contract/test_anti_circularity_gate.py -v`
Expected: PASS — 새 파일이 금지 문자열을 하나도 포함하지 않는다.

- [ ] **Step 6: lint**

Run: `uv run ruff check packages/mission-planning/src/ksi_mission_planning/terrain.py tests/contract/test_terrain_altitude_planner.py`
Expected: `All checks passed!`

- [ ] **Step 7: mypy**

Run: `uv run mypy packages/mission-planning/src/ksi_mission_planning/terrain.py packages/geo-spatial/src/ksi_geo_spatial/terrain.py`
Expected: `Success: no issues found`

- [ ] **Step 8: 전체 회귀(두 신규 파일이 다른 걸 안 깼는지)**

Run: `ulimit -n 8192 && uv run pytest -q`
Expected: 기존 3322 passed 에 이번에 추가한 16건(Task1 7 + Task2 9)이 더해진 수만큼 증가, 실패 0.

- [ ] **Step 9: 커밋**

```bash
git add packages/mission-planning/src/ksi_mission_planning/terrain.py tests/contract/test_terrain_altitude_planner.py
git commit -m "feat(mission-planning): compute a terrain-following altitude profile"
```

---

## Self-Review 기록

- **스펙 커버리지**: 스펙의 두 컴포넌트·5개 계산규칙·고도변화율 표현 방식·범위 밖 항목 전부
  Task 1/2 에 반영됨. 스펙에 없던 것 하나를 계획 단계에서 발견해 반영했다 —
  DTM/DSM 은 지오이드 격자와 달리 보통 투영좌표계라 재투영 단계가 필요하다는 것과, nodata
  센티널 값이 표고로 잘못 읽히지 않게 마스킹하는 것(스펙 자체는 "GeoidGrid 와 동형"이라고만
  했었다 — 이 계획이 그 차이를 구체화했다).
- **자리표시자 스캔**: 없음 — 모든 단계에 실행 가능한 전체 코드가 있다.
- **타입 일관성**: `WaypointTerrainSample`/`WaypointAltitudePlan`/`TerrainAltitudeProfile`
  필드명이 Task 2 안에서 정의·테스트·구현 전부 동일하다. Task 1 의 `TerrainGrid`/
  `TerrainUnavailableError` 는 Task 2 가 import하지 않는다(의도됨, Interfaces 절 참조).
