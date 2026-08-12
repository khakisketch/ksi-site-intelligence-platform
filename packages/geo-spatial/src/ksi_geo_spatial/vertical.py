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

## 데이터 확보 상태 (2026-08-12)

**KNGeoid24 격자를 확보·검증했다** — 국토지리정보원 국토정보플랫폼 정식 취득,
GeoTIFF 변환본 ``data/geoid/KNGeoid24.tif``(저장소에 추적됨), 전국 10개 시도에
분산된 통합기준점 10점 전원 통과(최대오차 0.0401m, RMSE 0.0247m). 취득·변환·
대조 기록 전문은 ``docs/geo/GEOID_ACQUISITION.md`` 다. 이로써 risk
`geoid-grid-provenance-unverified` 의 해소 조건("정식 경로 취득 + 통합기준점
실측 대조 통과")이 충족됐고, **정표고 변환이 상용 경로에 열렸다** — 설계 대비
잔량(M4-A)이 정표고 도면을 받아 h = H + N 으로 올린 뒤 차분한다.

두 가지는 그대로다:

- **KNGeoid18 격자는 여전히 없다.** ``ORTHOMETRIC_KNGEOID2018`` 로 선언된
  높이를 KNGeoid24 격자로 되돌리지 않는다(계약 쪽
  ``_GEOID_BRIDGEABLE_ORTHOMETRIC`` 주석에 근거).
- M1 의 시점 간 상대 비교는 두 epoch 가 **같은 파이프라인의 타원체고**를
  공유한다는 전제 위에 있고, 산출물은 그 사실을
  ``verticalDatum = "ellipsoidal_native"`` 로 명시해 싣는다 — 격자가 생겼다고
  과거 산출물이 소급해서 정표고가 되지는 않는다.

## 계약·판정은 여기 살지 않는다

``VerticalDatum``·``VerticalReference``·계열 판정(``family_of``,
``assert_comparable_vertical``)의 정본은
:mod:`ksi_event_contracts.vertical_reference` 다. 그 판정들의 소비자가
Core(control plane)라서 pyproj·rasterio 를 물고 있는 이 패키지에 두면 래스터
스택이 Core 로 딸려오기 때문이다(이유 전문은 그 모듈 docstring). 이 모듈은
**기존 import 경로를 유지하기 위해 그 이름들을 재수출**하고, 지오이드 격자
보간처럼 실제 측지 연산이 필요한 것만 직접 구현한다.
"""

from __future__ import annotations

import hashlib
import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import rasterio
from ksi_event_contracts.vertical_reference import (
    UnrecognizedVerticalCrsError,
    VerticalBridge,
    VerticalDatum,
    VerticalDatumFamily,
    VerticalDatumIncompatibleError,
    VerticalReference,
    VerticalReferenceSource,
    assert_bridgeable_vertical,
    assert_comparable_vertical,
    bridge_between,
    family_of,
    vertical_datum_from_epsg,
)
from numpy.typing import NDArray

#: 격자 파일 경로를 지정하는 환경변수. 미설정이면 정표고 변환을 쓸 수 없다.
GEOID_GRID_ENV = "KSI_GEOID_GRID"


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
    #: 이 격자가 온 파일의 이름과 바이트 해시 — **변환 사실을 리포트에 남기기
    #: 위한 것**이다. "지오이드 격자로 변환했다"는 문장은 어느 격자인지 말하지
    #: 못하면 검증 불가능한 주장이고, 모델이 다르면 결과가 수 cm 어긋난다.
    #: 경로는 배포마다 다르므로 파일 이름만 남기고, 동일성은 해시가 답한다.
    source_name: str | None = None
    source_sha256: str | None = None

    @classmethod
    def from_path(cls, path: Path) -> GeoidGrid:
        with rasterio.open(path) as dataset:
            if dataset.count != 1:
                raise GeoidUnavailableError(
                    f"지오이드 격자는 단일 밴드여야 한다 (밴드 {dataset.count}개): {path}"
                )
            values = dataset.read(1).astype(np.float64)
            transform = dataset.transform
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        # rasterio Affine: (a=셀 폭, b, c=좌상단 x, d, e=셀 높이(음수), f=좌상단 y)
        return cls(
            values=values,
            origin_lon_deg=float(transform.c),
            origin_lat_deg=float(transform.f),
            cell_size_lon_deg=float(transform.a),
            # e 는 북쪽이 위인 격자에서 음수다 — 절대값이 셀 높이.
            cell_size_lat_deg=float(-transform.e),
            source_name=path.name,
            source_sha256=digest.hexdigest(),
        )

    @property
    def provenance(self) -> str:
        """"어느 격자였나" 를 사람이 읽을 한 줄 — 리포트 근거(basis)에 실린다."""
        if self.source_name is None or self.source_sha256 is None:
            return "출처가 기록되지 않은 지오이드 격자(메모리에서 직접 만든 격자)"
        return f"{self.source_name}(sha256:{self.source_sha256[:12]}…)"

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


# 재수출 포함 — 정본은 ksi_event_contracts.vertical_reference 이고(모듈 docstring),
# 여기 이름들은 기존 import 경로와 "수직축은 이 모듈에서 찾는다"는 관용을 유지하기
# 위한 것이다. 값 객체는 하나뿐이라 두 경로가 갈라질 수 없다.
__all__ = [
    "GEOID_GRID_ENV",
    "GeoidGrid",
    "GeoidUnavailableError",
    "UnrecognizedVerticalCrsError",
    "VerticalBridge",
    "VerticalDatum",
    "VerticalDatumFamily",
    "VerticalDatumIncompatibleError",
    "VerticalReference",
    "VerticalReferenceSource",
    "assert_bridgeable_vertical",
    "assert_comparable_vertical",
    "bridge_between",
    "ellipsoidal_to_orthometric",
    "family_of",
    "load_geoid_grid",
    "orthometric_to_ellipsoidal",
    "vertical_datum_from_epsg",
]
