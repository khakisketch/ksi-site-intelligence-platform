"""GSD(Ground Sample Distance, 픽셀 표본거리) 해석 — 산출물 자신의 픽셀 크기에서 읽는다.

## 왜 리포트 파싱이 아니라 래스터 자체인가

``odm_assets.py`` 모듈 docstring 은 이 값을 "엔진 리포트에서 읽어 채운다"고
예고했다. ``odm_report/stats.json`` 은 이 저장소가 아직 모델링하지 않은
진단용 파일이고(``odm_assets.py`` "매핑하지 않은 실제 산출물" 절), ODM 버전마다
필드가 바뀔 수 있어 그 파일을 파싱해 얻은 숫자가 실제로 등록될 GeoTIFF 의
픽셀 크기와 같다는 보장이 없다. **등록하려는 그 파일 자신의 아핀 변환**이
유일하게 거짓말할 수 없는 출처라, 파일 자체에서 읽는다.

## GDAL vsizip 을 직접 쓴다 — 아카이브를 통째로 메모리에 올리지 않는다

``zip://{archive}!{entry}`` URI 로 열면 GDAL 이 zip 내부를 가상 파일시스템으로
다루어 헤더(CRS·아핀 변환)만 읽는다. 오소영상처럼 수백 MB 짜리 파일도 픽셀
데이터를 디코드하지 않고 메타데이터만 본다.

## 실패하면 건너뛴다 (지어내지 않는다) — INV-040

아카이브에 그 항목이 없거나, 파일이 손상됐거나, CRS 가 없으면 이 함수는 그
산출물의 GSD 를 채우지 않는다. ``odm.plan_artifacts`` 가 이미 "GSD 없으면
건너뛴다" 원칙을 갖고 있으므로(모듈 docstring) 여기서 예외를 던지지 않고
결과 dict 에서 빼기만 한다 — 래스터 하나가 손상됐다고 재구성 전체를 실패로
만들 이유가 없다.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import rasterio
from rasterio.errors import RasterioIOError

from ksi_processing_controller.odm_assets import ODM_ASSETS, OdmAsset

logger = logging.getLogger(__name__)


def resolve_gsd(
    archive_path: Path, *, assets: Sequence[OdmAsset] = ODM_ASSETS
) -> dict[str, float]:
    """``needs_gsd=True`` 인 자산들의 GSD 를 아카이브 안 파일에서 직접 읽는다.

    반환값은 :func:`~ksi_processing_controller.odm.plan_artifacts` 의
    ``gsd_by_artifact`` 인자에 그대로 넘길 수 있는 모양이다. 읽지 못한 항목은
    결과에 아예 없다 — 호출자가 없음과 0 을 혼동하지 않게 한다.
    """
    result: dict[str, float] = {}
    for asset in assets:
        if not asset.needs_gsd:
            continue
        gsd = _read_pixel_size(archive_path, asset.archive_entry)
        if gsd is not None:
            result[asset.artifact_id] = gsd
    return result


def _read_pixel_size(archive_path: Path, entry: str) -> float | None:
    """엔트리 하나의 GSD — 두 축 픽셀 크기의 기하평균(m).

    직사각형이 아닌 픽셀(드묾)에서도 "셀 면적과 같은 정사각형의 한 변"이라는
    GSD 의 통상 정의에 맞춰 기하평균을 쓴다 — 산술평균은 그 정의와 어긋난다.
    """
    uri = f"zip://{archive_path}!{entry}"
    try:
        with rasterio.open(uri) as dataset:
            if dataset.crs is None:
                logger.warning("%s 는 CRS 가 없다 — GSD 를 지어내지 않고 건너뛴다", entry)
                return None
            x_size = abs(dataset.transform.a)
            y_size = abs(dataset.transform.e)
            if x_size <= 0 or y_size <= 0:
                logger.warning(
                    "%s 의 픽셀 크기가 0 이하다(%s, %s) — 건너뛴다", entry, x_size, y_size
                )
                return None
            return (x_size * y_size) ** 0.5
    except RasterioIOError as exc:
        # 아카이브에 그 항목이 없거나(정상 — ODM 옵션에 따라 안 만들 수 있다),
        # 파일이 손상된 경우 둘 다 여기로 온다. plan_artifacts 가 어차피 아카이브에
        # 없는 항목은 별도로 건너뛰므로, 여기서 원인을 갈라 다르게 처리할 이유가
        # 없다 — 둘 다 "이 산출물의 GSD 를 못 구했다"는 같은 결론이다.
        logger.info("%s 를 래스터로 열 수 없다 — GSD 를 건너뛴다: %s", entry, exc)
        return None


__all__ = ["resolve_gsd"]
