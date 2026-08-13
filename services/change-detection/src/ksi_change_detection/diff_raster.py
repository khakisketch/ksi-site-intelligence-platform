"""높이차 격자를 파일로 굳힌다 — **지도가 읽는 단 하나의 데이터 출처**.

## 왜 이 파일이 있나

체적 숫자는 ``dsm_diff.volume_delta_in_polygon`` 이 :class:`DiffResult` 에서 낸다.
히트맵도 같은 질문("어디가 얼마나 높고 낮은가")에 답하는데, 브라우저가 원본 두
장을 다시 받아 스스로 차분하면 **두 번째 진실**이 생긴다 — 재투영 방식·nodata
처리·문턱 적용 중 하나만 달라도 지도와 표가 조용히 갈리고, 그 불일치는 어느
화면에서도 보이지 않는다. 그래서 집계에 **실제로 쓴 그 배열**을 그대로 GeoTIFF
로 써서 영속한다.

## 무효 셀은 NaN 이지 0 이 아니다

``valid=False`` 는 "차이가 없다"가 아니라 **"모른다"**다(두 입력 중 한쪽이라도
nodata). 0 으로 쓰면 지도가 그 자리를 "설계대로 됐다"고 칠하고, 그것은 사용자가
확인할 방법이 없는 거짓말이다. NaN 은 화면이 3상태 범례("모름"·"문턱 미만"·
"성토/절토 필요")로 따로 그릴 수 있는 유일한 표현이다.

**문턱 미만 셀의 값은 지우지 않는다.** 집계에서 빠졌다는 사실은 리포트의
``thresholdM`` 이 말하고, 래스터에는 실제 값이 남아 있어야 화면이 "이만큼이지만
안 셌다"를 그릴 수 있다. 여기서 미리 0/NaN 으로 뭉개면 그 구분이 영영 사라진다.

## 결정성은 추정하지 않고 고정한다

같은 입력이 같은 바이트를 내야 ``DiffRasterRef.digest`` 가 재현 가능한 사실이
되고, Core 의 재해싱 확인이 의미를 갖는다. 그래서 프로파일을 열거해 고정하고
(호출부가 압축·타일 크기를 고를 여지를 주지 않는다), **같은 입력 2회 → 같은
sha256** 을 테스트가 강제한다. 2026-08-12 이 환경(rasterio 1.5.0 / GDAL 3.12.1)
실측 결과 GTiff 드라이버는 ``TIFFTAG_DATETIME``·``TIFFTAG_SOFTWARE`` 같은 시각·
버전 태그를 기본으로 쓰지 않는다(태그는 ``AREA_OR_POINT`` 뿐). 그 전제가 라이브러리
갱신으로 깨지면 :data:`NON_DETERMINISTIC_TIFF_TAGS` 를 보는 테스트가 먼저 깨진다.

``predictor=3`` 은 부동소수 전용 예측자다 — float32 차분값처럼 이웃끼리 완만하게
변하는 격자에서 deflate 압축률을 크게 올린다.

## sha256 도 여기 산다

워커가 만든 파일의 해시와 Core 가 나중에 그 객체를 다시 읽어 계산할 해시는
**같은 함수**여야 한다. 접두사 규약(``sha256:``)이 한쪽에만 있거나 한쪽이
청크 경계를 다르게 다루면 "digest 불일치"라는 가짜 사고가 난다. 그래서 래스터를
쓰는 자리 바로 옆에 둔다 — 로컬 테스트가 업로드 전에 미리 대조할 수 있다.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Final

import numpy as np
import rasterio

from ksi_change_detection.dsm_diff import DiffResult

#: GeoTIFF 쓰기 프로파일 — **호출부가 고를 수 없는 고정값**(모듈 docstring: 결정성).
#: ``nodata`` 는 NaN 이고, 그것이 "모름"의 유일한 표현이다.
DIFF_RASTER_PROFILE: Final[dict[str, Any]] = {
    "driver": "GTiff",
    "dtype": "float32",
    "count": 1,
    "nodata": float("nan"),
    "tiled": True,
    "blockxsize": 256,
    "blockysize": 256,
    "compress": "deflate",
    "zlevel": 6,
    "predictor": 3,
}

#: 값이 실리면 같은 입력이 매번 다른 바이트가 되는 TIFF 태그들. 지금은 GDAL 이
#: 쓰지 않지만(모듈 docstring 실측), 쓰기 시작하면 결정성이 조용히 깨진다.
NON_DETERMINISTIC_TIFF_TAGS: Final[tuple[str, ...]] = ("TIFFTAG_DATETIME", "TIFFTAG_SOFTWARE")

#: 해시 스트리밍 청크. 차분 래스터는 수백 MB 가 될 수 있어 통째로 올리지 않는다
#: (``processing_controller.measure.measure_image`` 와 같은 근거·같은 크기).
_HASH_CHUNK_BYTES: Final = 1024 * 1024


def write_diff_geotiff(diff: DiffResult, path: Path) -> None:
    """차분 격자를 결정적 프로파일의 GeoTIFF 로 쓴다.

    ``diff.valid`` 가 False 인 셀은 NaN 으로 나간다 — 0 이 아니다(모듈 docstring).
    값의 부호 규약은 :class:`DiffResult` 를 만든 쪽이 정한다. 설계 대비 비교
    경로에서는 ``설계 표고 − 현재 표고`` 이므로 양수 = 쌓아야 함, 음수 = 깎아야
    함이다(``run_design_conformance`` 참조).

    float64 격자를 float32 로 좁혀 쓴다. 토공 높이차의 유효 자릿수(cm)에 비해
    float32 의 상대정밀도(~1e-7)는 과분하고, 파일 크기는 절반이 된다 — 이 파일은
    브라우저가 통째로 받아 그리는 지도 데이터라 크기가 곧 체감 속도다.
    """
    values = np.where(diff.valid, diff.diff_m, np.nan).astype(np.float32)
    height, width = values.shape
    with rasterio.open(
        path,
        "w",
        height=height,
        width=width,
        crs=diff.crs,
        transform=diff.transform,
        **DIFF_RASTER_PROFILE,
    ) as dataset:
        dataset.write(values, 1)


def sha256_of_file(path: Path) -> str:
    """파일 바이트의 sha256 — ``sha256:`` 접두사가 붙은 산출물 참조 표기.

    접두사를 붙이는 쪽이 이 저장소의 **산출물 digest** 관습이다
    (``ProcessingArtifact.digest``·``DiffRasterRef.digest``). 접두사 없는 원시
    16진 표기는 파일 해시 신고값 쪽(``DesignSurface.declared.sha256``)이므로,
    그쪽과 대조할 때는 붙여서 비교하거나 떼서 비교하되 **한 방향으로만** 한다.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


__all__ = [
    "DIFF_RASTER_PROFILE",
    "NON_DETERMINISTIC_TIFF_TAGS",
    "sha256_of_file",
    "write_diff_geotiff",
]
