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
#: 경계 판정 허용오차(픽셀 단위) — CRS 왕복 재투영은 정확히 0을 내지 않고
#: ~1e-9 수준의 부동소수 잡음을 남긴다(geometry.py 의 ``_EPSILON_M`` 과 같은
#: 이유: 실제 경계에 있는 점을 "약간 밖"으로 오판해 거부하지 않기 위해서다).
#: 실제 격자 밖 질의(오차보다 훨씬 큰 값)는 이 허용오차로 절대 통과하지 못한다.
_BOUNDARY_EPSILON = 1e-6


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
        if (
            col < -_BOUNDARY_EPSILON
            or row < -_BOUNDARY_EPSILON
            or col > cols - 1 + _BOUNDARY_EPSILON
            or row > rows - 1 + _BOUNDARY_EPSILON
        ):
            raise TerrainUnavailableError(
                f"지점 (lat={lat_deg}, lon={lon_deg}) 이 지형 격자 범위 밖이다 — 외삽하지 않는다"
            )
        # 허용오차를 통과한 경계 근접값을 정확히 [0, len-1] 로 접어 넣는다 — 안
        # 그러면 col=-1e-10 같은 값이 int(floor(...))에서 -1 이 되어 파이썬
        # 음수 인덱싱으로 **반대쪽 끝 셀**을 조용히 읽는다(전혀 다른 값).
        col = min(max(col, 0.0), float(cols - 1))
        row = min(max(row, 0.0), float(rows - 1))

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
