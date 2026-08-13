"""설계 기준면 검증 워커 — 파일을 열어 **재고**, 판정은 Core 에 맡긴다.

``measure.py`` 가 원본 사진에 대해 하는 일을 설계면 GeoTIFF 에 대해 한다:
지어낼 수 있는 값이 없도록 실제로 바이트를 읽는다. 차이는 잴 것이 많다는
것뿐이다(해시·좌표계·치수·밴드·nodata·화소크기·변환·경계·유효셀 수).

## 이 모듈이 하지 않는 것

**판정하지 않는다.** "선언과 다르다"는 결론은 전부 Core 의 몫이고
(``ksi_core.design_surfaces.evaluate_observation``), 여기서 보내는 것은 측정치
뿐이다. 그래서 이 워커는 자기가 무엇과 대조되는지 모른다 — 신고된 sha256·CRS 를
받지 않으므로(``PendingDesignSurface``) 읽지 않고 되읊는 경로 자체가 없다.

**후보를 스스로 고르지 않는다.** ``designSurfaceId`` 와 다운로드 URL 을 인자로
받는다(``worker.py``·``comparison_worker.py`` 와 동일 전제) — 큐 폴링은 runner
의 몫이다.

## 세 가지 실패를 서로 다르게 다룬다

1. **다운로드 실패**(네트워크·URL 만료·스토리지 장애) — 파일에 대한 증거가
   아니다. 예외를 그대로 올려 재시도로 보낸다. 이걸 ``UNREADABLE_RASTER`` 로
   보고하면 멀쩡한 설계면이 네트워크 사고 한 번으로 **영구 거부**된다
   (``REJECTED`` 는 종단이다).
2. **열지 못함·좌표계 없음** — 파일 자체에 대한 사실이다. Core 에
   ``verification-failure`` 로 보고하고 정상 종료한다(사유는 Core 가
   ``UNREADABLE_RASTER`` 로 고정한다).
3. **잘 열림** — 측정치를 보고한다. Core 가 ``VERIFIED``/``REJECTED`` 를 매기고,
   ``REJECTED`` 도 이 워커에게는 **성공적인 완주**다(반환값으로 알린다).
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import numpy as np
import rasterio
from pyproj import CRS as ProjCRS  # noqa: N811 -- pyproj 공식 표기(rasterio CRS 와 구분)

from ksi_processing_controller.core_client import (
    DesignSurfaceCoreClient,
    DesignSurfaceMeasurement,
)

if TYPE_CHECKING:
    from rasterio.io import DatasetReader

logger = logging.getLogger(__name__)

#: 다운로드 청크. 설계면은 수백 MB 일 수 있어 통째로 메모리에 올리지 않는다.
_CHUNK_BYTES = 1024 * 1024


class DesignSurfaceMeasurementError(RuntimeError):
    """파일을 열 수 없거나 필수 사실(좌표계)을 읽을 수 없다 — 관측 자체가 없다.

    네트워크 실패는 이 예외가 **아니다**(모듈 docstring §세 가지 실패).
    """


@dataclass(frozen=True, slots=True)
class _HorizontalAndVertical:
    """파일의 CRS 를 수평·수직 두 축으로 가른 결과."""

    horizontal: str
    vertical_epsg: int | None


def _split_crs(wkt: str) -> _HorizontalAndVertical:
    """compound CRS 면 수평·수직으로 가르고, 아니면 그대로 수평이다.

    설계면 대조의 수평 CRS 는 **수평 성분**이어야 한다 — compound CRS 파일의
    전체 표기를 그대로 보고하면 ``EPSG:5186`` 선언과 절대 일치하지 않아 정상
    파일이 ``CRS_DECLARATION_MISMATCH`` 로 거부된다.

    수직 성분은 **있으면** EPSG 코드로 싣는다. 그 코드가 무엇을 뜻하는지는 여기서
    해석하지 않는다 — 해석·판정은 Core 가 한다(``vertical_datum_from_epsg``).
    권위 코드로 환원되지 않는 성분은 ``None`` 이 아니라 그대로 못 싣는다(코드가
    없으므로) — 그 경우 수직기준 대조는 선언을 반박하지도 뒷받침하지도 않는다.
    """
    parsed = ProjCRS.from_wkt(wkt)
    if not parsed.is_compound:
        return _HorizontalAndVertical(horizontal=_authority_or_wkt(parsed, wkt), vertical_epsg=None)
    horizontal_wkt = wkt
    horizontal: str | None = None
    vertical_epsg: int | None = None
    for component in parsed.sub_crs_list:
        if component.is_vertical:
            vertical_epsg = component.to_epsg()
        elif horizontal is None:
            horizontal = _authority_or_wkt(component, component.to_wkt())
    if horizontal is None:
        horizontal = _authority_or_wkt(parsed, horizontal_wkt)
    return _HorizontalAndVertical(horizontal=horizontal, vertical_epsg=vertical_epsg)


def _authority_or_wkt(parsed: ProjCRS, fallback_wkt: str) -> str:
    """``EPSG:5186`` 형태로 — 환원되지 않으면 원문 WKT 를 그대로 보고한다.

    지어내지 않는 것이 요점이다. 권위 코드가 없는 좌표계를 억지로 가까운 코드로
    맞추면 그 순간 워커가 **판정을 한 것**이 된다. Core 가 그 문자열을 정규화하지
    못하면 ``UNSUPPORTED_CRS`` 로 거부하는 것이 정확한 결말이다.
    """
    code = parsed.to_epsg()
    if code is not None:
        return f"EPSG:{code}"
    return fallback_wkt


def _count_finite_cells(dataset: DatasetReader) -> int:
    """nodata·NaN 이 아닌 셀 수 — 블록 단위로 세어 큰 래스터도 메모리에 안 올린다."""
    total = 0
    for _, window in dataset.block_windows(1):
        block = dataset.read(1, window=window, masked=True)
        values = block.filled(np.nan).astype("float64", copy=False)
        total += int(np.isfinite(values).sum())
    return total


def measure_design_surface(path: Path) -> DesignSurfaceMeasurement:
    """설계면 GeoTIFF 1건의 실측 — 전부 이 파일에서 읽은 값이다.

    ``sha256`` 은 스트리밍으로 계산한다(``measure_image`` 관습). 나머지는
    rasterio 가 여는 데이터셋에서 그대로 읽어 옮긴다 — **"이상한 값"도 그대로
    싣는다**: 3밴드도, 유효셀 0도, 지원하지 않는 좌표계도 측정 결과일 뿐이고,
    거부는 Core 가 typed verdict 로 내린다(그래야 사용자에게 이유가 간다).
    """
    if not path.is_file():
        raise DesignSurfaceMeasurementError(f"파일이 없다: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_BYTES), b""):
            digest.update(chunk)

    try:
        dataset = rasterio.open(path)
    except Exception as exc:  # noqa: BLE001 -- rasterio/GDAL 예외 계층이 넓고 결론은 하나다
        raise DesignSurfaceMeasurementError(f"래스터를 열 수 없다({path.name}): {exc}") from exc
    with dataset:
        if dataset.crs is None:
            # 좌표계가 없는 래스터는 "선언과 다른 파일"이 아니라 **대조할 수 없는
            # 파일**이다. 빈 문자열을 관측으로 싣지 않는다(계약이 거부한다).
            raise DesignSurfaceMeasurementError(
                f"좌표계 정보가 없는 래스터다({path.name}) — 어느 좌표계인지 파일이 말하지 않는다"
            )
        crs = _split_crs(dataset.crs.to_wkt())
        transform = dataset.transform
        bounds = dataset.bounds
        nodata = dataset.nodata
        nodata_is_nan = nodata is not None and math.isnan(nodata)
        return DesignSurfaceMeasurement(
            sha256=digest.hexdigest(),
            crs=crs.horizontal,
            vertical_crs_epsg=crs.vertical_epsg,
            width=dataset.width,
            height=dataset.height,
            band_count=dataset.count,
            dtype=str(dataset.dtypes[0]),
            # NaN nodata 는 JSON 에 실을 수 없어 불리언으로 옮긴다(계약 규약).
            nodata=None if nodata is None or nodata_is_nan else float(nodata),
            nodata_is_nan=nodata_is_nan,
            # 화소 크기는 **부호 없는 크기**다 — 방향은 transform 이 그대로 든다.
            pixel_size_x_m=abs(float(transform.a)),
            pixel_size_y_m=abs(float(transform.e)),
            transform=(
                float(transform.a),
                float(transform.b),
                float(transform.c),
                float(transform.d),
                float(transform.e),
                float(transform.f),
            ),
            bounds_min_x=float(bounds.left),
            bounds_min_y=float(bounds.bottom),
            bounds_max_x=float(bounds.right),
            bounds_max_y=float(bounds.top),
            finite_cell_count=_count_finite_cells(dataset),
        )


def download_design_surface(
    download_url: str, *, destination: Path, http_client: httpx.Client
) -> None:
    """presigned GET 으로 내려받는다 — 실패는 **그대로 올린다**(모듈 docstring §1)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        http_client.stream("GET", download_url) as response,
        destination.open("wb") as handle,
    ):
        response.raise_for_status()
        for chunk in response.iter_bytes(_CHUNK_BYTES):
            handle.write(chunk)


def verify_design_surface(
    design_surface_id: str,
    *,
    download_url: str,
    core: DesignSurfaceCoreClient,
    http_client: httpx.Client,
    work_dir: Path,
) -> str:
    """설계면 1건을 내려받아 재고 보고한다. 반환값은 **Core 의 판정**이다.

    ``download_url`` 을 인자로 받는 이유: 그 URL 은 검증 대기 목록
    (``GET /v1/design-surfaces``)이 함께 주는 값이라, 여기서 다시 조회하면
    같은 것을 두 번 묻게 된다. Core 에는 "id 하나로 URL 만 재발급하는" 표면이
    없다(그런 표면을 새로 열면 워커 토큰의 열람 범위가 대기 큐 밖으로 넓어진다).

    반환값은 ``VERIFIED``/``REJECTED``/``ALREADY_JUDGED`` 중 하나다 — 거부도
    이 함수에게는 정상 완주다(모듈 docstring §3).
    """
    local_path = work_dir / f"{design_surface_id}.tif"
    download_design_surface(download_url, destination=local_path, http_client=http_client)
    try:
        measurement = measure_design_surface(local_path)
    except DesignSurfaceMeasurementError as exc:
        logger.warning("설계면을 읽지 못했다: designSurfaceId=%s (%s)", design_surface_id, exc)
        core.report_design_surface_verification_failure(design_surface_id, detail=str(exc))
        return "REJECTED"
    verdict = core.report_design_surface_observation(design_surface_id, measurement)
    logger.info(
        "설계면 검증 보고 완료: designSurfaceId=%s verdict=%s", design_surface_id, verdict
    )
    return verdict


__all__ = [
    "DesignSurfaceMeasurementError",
    "download_design_surface",
    "measure_design_surface",
    "verify_design_surface",
]
