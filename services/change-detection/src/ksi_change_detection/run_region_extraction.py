"""변화 영역 자동 추출의 얇은 조립 계층 — 다운로드부터 계산까지, 제출은 하지 않는다 (M4-E).

``run_design_conformance.py`` 와 같은 자리다: Core 의 ``/input`` 이 준
(presigned diff-raster URL, thresholdM, extractionPolicy, changeRegionSetId,
designConformanceId) 을 받아 다운로드 → :func:`~ksi_change_detection.
diff_raster.read_diff_geotiff` → :func:`~ksi_change_detection.region_
extraction.compute_change_regions` 까지만 하고, 제출은 호출자(워커)의
몫으로 남긴다 — id 를 스스로 만들지 않는다, 큐에서 후보를 꺼내오지 않는다는
이 저장소의 기존 원칙을 그대로 지킨다.

``raster_path`` 는 호출자가 정한다(이 함수가 스스로 임시 디렉터리를 만들지
않는다) — 워커가 그 경로를 성공·실패 관계없이 정리할 책임을 지므로(``work_dir``
공유 원칙, ``worker.py`` 모듈 docstring), 다운로드 전에 이미 그 경로를 알고
있어야 한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from ksi_change_detection.diff_raster import read_diff_geotiff
from ksi_change_detection.download_errors import download_failure_detail
from ksi_change_detection.region_extraction import compute_change_regions

if TYPE_CHECKING:
    from datetime import datetime

    from ksi_event_contracts.change_region_report import ChangeRegionSetReport
    from ksi_event_contracts.design_conformance_report import DiffRasterRef
    from ksi_event_contracts.region_extraction_policy import RegionExtractionPolicy


class RegionExtractionRunError(RuntimeError):
    """변화 영역 추출 실행이 실패했다 — 다운로드·계산 중 하나가 성립하지 않았다."""


def run_region_extraction(
    *,
    change_region_set_id: str,
    design_conformance_id: str,
    diff_raster_id: str,
    diff_raster_url: str,
    diff_raster_ref: DiffRasterRef,
    raster_path: Path,
    threshold_m: float,
    extraction_policy: RegionExtractionPolicy,
    computed_at: datetime,
    http_client: httpx.Client,
) -> ChangeRegionSetReport:
    """diff 래스터를 받아 변화 영역을 추출한다(제출하지 않는다).

    Args:
        change_region_set_id: 결과 리포트의 id — 요청 id 에서 결정적으로 도출된
            값을 호출자가 넘긴다(이 함수가 만들면 재실행마다 다른 리포트가 된다).
        design_conformance_id: 이 diffRaster 를 낸 설계 대비 잔량 리포트 id.
        diff_raster_id: 원본 리포트가 이미 갖고 있는 차분 래스터 자산 id —
            새로 만들지 않고 그대로 싣는다(이 함수는 새 래스터를 쓰지 않는다).
        diff_raster_url: 그 래스터를 받을 presigned GET.
        diff_raster_ref: 이미 검증된 참조 — crs·transform·cell_area_m2 를
            여기서 그대로 가져온다(``read_diff_geotiff`` 모듈 docstring).
        raster_path: 다운로드해 쓸 로컬 경로. 정리는 호출자의 몫이다.
        threshold_m: 집계 문턱(원본 리포트의 ``diffRaster.thresholdM``).
        extraction_policy: 이 계산이 쓸 추출 기준값(policy-owned — Core 의
            ``current_region_extraction_policy()`` 스냅샷).
        computed_at: 결정성을 위해 인자로 받는다(``compute_design_conformance``
            관습).
        http_client: 스토리지 바이트를 받는 클라이언트.

    Raises:
        RegionExtractionRunError: 다운로드가 실패했다.
        DiffRasterReadError: 받은 파일의 크기가 ``diff_raster_ref`` 와 다르다.
        RegionExtractionError: 집계 계층의 실패(``compute_change_regions``).
    """
    _download(http_client, diff_raster_url, raster_path)
    diff = read_diff_geotiff(raster_path, ref=diff_raster_ref)
    return compute_change_regions(
        diff,
        threshold_m=threshold_m,
        policy=extraction_policy,
        change_region_set_id=change_region_set_id,
        diff_raster_id=diff_raster_id,
        design_conformance_id=design_conformance_id,
        computed_at=computed_at,
    )


def _download(client: httpx.Client, url: str, dest: Path) -> None:
    """스토리지에서 받아 파일로 쓴다 — 실패 메시지에 presigned 서명을 남기지 않는다
    (``run_design_conformance._download`` 와 대칭, ``download_errors`` 모듈 docstring)."""
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            with dest.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    handle.write(chunk)
    except httpx.HTTPStatusError as exc:
        raise RegionExtractionRunError(
            download_failure_detail(
                what="차분 래스터", url=url, cause=f"HTTP {exc.response.status_code}"
            )
        ) from exc
    except httpx.HTTPError as exc:
        raise RegionExtractionRunError(
            download_failure_detail(
                what="차분 래스터", url=url, cause=f"{type(exc).__name__}: {exc}"
            )
        ) from exc


__all__ = ["RegionExtractionRunError", "run_region_extraction"]
