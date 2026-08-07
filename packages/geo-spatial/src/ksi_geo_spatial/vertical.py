"""수직기준 — 타원체고↔정표고 변환 (INV-020 수직축).

## 두 높이는 다른 것이다

GNSS/RTK 가 직접 주는 높이는 **타원체고**(h) — 지구 타원체 표면으로부터의
거리다. 도면·설계·측량 성과가 쓰는 "표고"는 **정표고**(H) — 지오이드(평균
해수면에 가까운 등포텐셜면)로부터의 높이다. 둘의 차이가 **지오이드고**(N)이고,
관계는 ``H = h - N`` 이다.

한국에서 N 은 대략 20~30m 다. 즉 타원체고를 표고라고 부르는 순간 **20~30m
틀린다.** 문제는 그 값이 여전히 그럴듯한 범위라 화면에서도 계산에서도 이상해
보이지 않는다는 점이다.

## 그래서 없으면 거부한다

지오이드고는 격자 데이터(KNGeoid 등)로만 구할 수 있다. 격자가 없을 때
``N = 0`` 으로 두는 구현은 "변환했다"고 답하면서 실제로는 아무것도 하지 않은
것이며, 결과가 20~30m 틀린 채 "표고"라는 이름으로 흘러간다. 이 모듈은 그
경로를 만들지 않는다 — 격자가 없으면 :class:`GeoidUnavailableError` 다.
INV-023(Geo 투영은 외삽하지 않는다, 신뢰 불가 조건에서 typed 실패)과 같은
원칙이다.

## 데이터 확보 상태 (2026-08-07)

**KNGeoid18 격자 파일은 이 저장소에 없다.** 참고 저장소(ksi-terra)의 취득
기록에 따르면 다운로드 경위가 회색지대이고(로그인 UX 와 실제 서버 응답이
불일치), 통합기준점 실측 대조가 5점 중 3점만 허용 오차를 통과해 정확도 검증이
미완이다. 따라서:

- **정식 취득 경로와 정확도가 확인되기 전까지 정표고 변환을 상용 경로에서
  쓰지 않는다** (risk `geoid-grid-provenance-unverified`).
- M1 의 시점 간 상대 비교는 두 epoch 가 **같은 파이프라인의 타원체고**를
  공유한다는 전제로만 성립하며, 산출물에는 그 사실을
  ``verticalDatum = "ellipsoidal_native"`` 로 명시해 싣는다.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy as np
import rasterio
from numpy.typing import NDArray

#: 격자 파일 경로를 지정하는 환경변수. 미설정이면 정표고 변환을 쓸 수 없다.
GEOID_GRID_ENV = "KSI_GEOID_GRID"


class VerticalDatum(StrEnum):
    """산출물이 어느 수직기준인지 — wire 계약에 실리는 값.

    ``ELLIPSOIDAL_NATIVE`` 는 "재구성 엔진이 낸 타원체고를 변환 없이 그대로
    쓴다"는 뜻이다. ``ELLIPSOIDAL`` 과 굳이 나눈 이유는, 전자가 **의도적으로
    선택한 기준**이 아니라 **변환을 하지 못해 남은 상태**임을 소비자가 구분할
    수 있어야 하기 때문이다 — 나중에 격자가 확보되면 이 값이 남아 있는
    산출물이 곧 재처리 대상 목록이 된다.
    """

    ELLIPSOIDAL = "ellipsoidal"
    ELLIPSOIDAL_NATIVE = "ellipsoidal_native"
    ORTHOMETRIC_KNGEOID2018 = "orthometric_kngeoid2018"


class GeoidUnavailableError(RuntimeError):
    """지오이드고를 구할 수 없다 — 0 으로 대치하지 않고 거부한다."""


@dataclass(frozen=True, slots=True)
class GeoidGrid:
    """지오이드고 격자 — 경위도에서 N 을 이중선형 보간으로 읽는다.

    격자는 EPSG:4326(경위도) 기준을 전제한다. KNGeoid 를 포함한 국가 지오이드
    모델이 이 형태로 배포되고, 투영좌표계 격자를 다뤄야 할 일이 실제로 생기면
    그때 명시적으로 확장한다(지금 추측으로 일반화하지 않는다).
    """

    values: NDArray[np.float64]
    #: 좌상단 픽셀의 **모서리** 경도·위도와 셀 크기(도).
    origin_lon_deg: float
    origin_lat_deg: float
    cell_size_lon_deg: float
    cell_size_lat_deg: float

    @classmethod
    def from_path(cls, path: Path) -> GeoidGrid:
        with rasterio.open(path) as dataset:
            if dataset.count != 1:
                raise GeoidUnavailableError(
                    f"지오이드 격자는 단일 밴드여야 한다 (밴드 {dataset.count}개): {path}"
                )
            values = dataset.read(1).astype(np.float64)
            transform = dataset.transform
        # rasterio Affine: (a=셀 폭, b, c=좌상단 x, d, e=셀 높이(음수), f=좌상단 y)
        return cls(
            values=values,
            origin_lon_deg=float(transform.c),
            origin_lat_deg=float(transform.f),
            cell_size_lon_deg=float(transform.a),
            # e 는 북쪽이 위인 격자에서 음수다 — 절대값이 셀 높이.
            cell_size_lat_deg=float(-transform.e),
        )

    def height_at(self, *, lat_deg: float, lon_deg: float) -> float:
        """그 지점의 지오이드고 N (m). 격자 밖이면 거부한다(외삽 금지).

        **픽셀 중심 기준으로 보간한다.** 래스터의 원점은 좌상단 픽셀의
        *모서리*이므로, 값이 대표하는 위치인 중심으로 옮기려면 0.5 셀을 빼야
        한다. 이 오프셋을 빠뜨리면 결과가 반 셀만큼 밀리는데, 격자 간격이 큰
        지오이드 모델에서는 그 밀림이 수십 cm 오차가 된다.
        """
        rows, cols = self.values.shape

        # 모서리 기준 픽셀 좌표 → 중심 기준으로 0.5 이동.
        col = (lon_deg - self.origin_lon_deg) / self.cell_size_lon_deg - 0.5
        row = (self.origin_lat_deg - lat_deg) / self.cell_size_lat_deg - 0.5

        if not (math.isfinite(col) and math.isfinite(row)):
            raise GeoidUnavailableError(
                f"격자 좌표를 계산할 수 없다 (lat={lat_deg}, lon={lon_deg})"
            )
        if col < 0.0 or row < 0.0 or col > cols - 1 or row > rows - 1:
            raise GeoidUnavailableError(
                f"지점 (lat={lat_deg}, lon={lon_deg}) 이 지오이드 격자 범위 밖이다 — "
                "외삽하지 않는다"
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
            raise GeoidUnavailableError(
                f"지오이드 격자가 (lat={lat_deg}, lon={lon_deg}) 에서 유한하지 않은 "
                "값을 준다 (nodata 구멍일 수 있다)"
            )
        return float(value)


def load_geoid_grid() -> GeoidGrid | None:
    """환경변수로 지정된 격자를 읽는다. 미설정이면 ``None``.

    **미설정과 설정-실패를 다르게 다룬다.** 미설정은 "정표고를 안 쓴다"는
    정상 상태라 ``None`` 이고, 경로를 지정했는데 파일이 없거나 못 읽는 것은
    배포·설정이 깨진 것이라 오류다 — 후자를 ``None`` 으로 삼키면 fail-closed
    가 "격자 없음" 경로로 빠져 원인이 가려진다.
    """
    configured = os.environ.get(GEOID_GRID_ENV, "").strip()
    if not configured:
        return None

    path = Path(configured)
    if not path.is_file():
        raise GeoidUnavailableError(
            f"{GEOID_GRID_ENV} 가 {configured} 를 가리키는데 파일이 없다 — "
            "정표고를 쓰겠다고 설정해 놓고 격자가 없는 상태다"
        )
    try:
        return GeoidGrid.from_path(path)
    except GeoidUnavailableError:
        raise
    except Exception as exc:  # rasterio 계열 오류를 이 모듈의 타입으로 좁힌다
        raise GeoidUnavailableError(f"지오이드 격자를 읽지 못했다: {configured}") from exc


def _separation(grid: GeoidGrid | None, *, lat_deg: float, lon_deg: float) -> float:
    if grid is None:
        raise GeoidUnavailableError(
            "지오이드 격자가 없어 정표고 변환을 수행할 수 없다 — N=0 으로 대치하면 "
            f"한국에서 20~30m 가 조용히 틀린다. {GEOID_GRID_ENV} 설정 필요"
        )
    return grid.height_at(lat_deg=lat_deg, lon_deg=lon_deg)


def ellipsoidal_to_orthometric(
    h_m: float, *, lat_deg: float, lon_deg: float, grid: GeoidGrid | None
) -> float:
    """타원체고 → 정표고 (``H = h - N``)."""
    return h_m - _separation(grid, lat_deg=lat_deg, lon_deg=lon_deg)


def orthometric_to_ellipsoidal(
    height_m: float, *, lat_deg: float, lon_deg: float, grid: GeoidGrid | None
) -> float:
    """정표고 → 타원체고 (``h = H + N``)."""
    return height_m + _separation(grid, lat_deg=lat_deg, lon_deg=lon_deg)


__all__ = [
    "GEOID_GRID_ENV",
    "GeoidGrid",
    "GeoidUnavailableError",
    "VerticalDatum",
    "ellipsoidal_to_orthometric",
    "load_geoid_grid",
    "orthometric_to_ellipsoidal",
]
