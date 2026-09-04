"""변화 영역 자동 추출 실행기 — lease 취득부터 SUCCEEDED/FAILED 까지 (M4-E).

``design_conformance_worker.py`` 와 같은 골격(lease → ``/input`` → ``RUNNING``
→ 계산 → 제출 → ``SUCCEEDED``, 실패는 ``FAILED`` 로 수렴)을 따르되, **이 워커는
이번 세션에 이미 고친 더 나은 패턴을 처음부터 적용한다**:

## 작업 파일은 성공·실패 관계없이 지운다

``work_dir`` 을 다른 세 종류 작업(재구성·비교·설계 대비 잔량)과 공유한다.
``worker.py`` 의 ``downloaded_paths`` 추적 + ``finally`` 정리 관용구를 그대로
따른다 — 다운로드를 시도하기 **전에** 경로를 목록에 넣어, 중간에 끊겨도
(디스크 가득·네트워크 오류) 남는 부분 파일까지 정리 대상으로 잡는다.
``design_conformance_worker.py`` 의 ``shutil.rmtree(raster_path.parent, ...)``
패턴(계산 함수가 만든 임시 디렉터리를 통째로 지우는 방식)보다 ``worker.py`` 의
이 패턴이 더 명확하다 — 이 워커는 다운로드할 파일이 하나뿐이라 그 경로 하나만
알면 충분하고, 계산 계층(``run_region_extraction``)이 임시 디렉터리를 스스로
만들지 않게 해 소유권이 한 곳(이 워커)에만 있다.

## 실패는 전부 ``FAILED`` 로 수렴한다

``worker.py`` 모듈 docstring의 재감사 발견(2026-08-13)과 같은 이유로, 좁은
예외 목록이 아니라 이 함수가 하는 일(lease·입력조회·전이·계산·제출) 전체에서
나는 예외를 폭넓게 잡는다(``OSError`` 포함) — 좁게 잡으면 그 예외가
:class:`RegionExtractionWorkerRunError` 로 감싸이지 않고 새어나가 ``runner.py``
의 ``_try_candidates`` 가 "이번 라운드는 아무 일도 안 했다"로 오판해 같은
요청을 ``FAILED`` 보고 없이 무한 재시도한다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
from ksi_change_detection.run_region_extraction import run_region_extraction

from ksi_processing_controller.comparison_worker import LeaseHeartbeat
from ksi_processing_controller.core_client import CoreClientError, RegionExtractionCoreClient
from ksi_processing_controller.workspace import (
    attempt_workspace,
    cleanup_attempt_workspace,
    lease_or_compat_handle,
)

logger = logging.getLogger(__name__)

#: lease 갱신 주기(초) — 다른 세 워커와 같은 값·같은 이유(같은 lease 규약 위에 있다).
_HEARTBEAT_INTERVAL_SECONDS = 10.0


class RegionExtractionWorkerRunError(RuntimeError):
    """변화 영역 추출 실행이 실패했다 — Core 에는 이미 FAILED 로 보고를 시도했다."""


def _cleanup_downloaded_paths(
    paths: list[Path], request_id: str, now_message: Callable[[str], None]
) -> None:
    """이 요청이 ``work_dir`` 에 남긴 파일을 지운다 — 성공이든 실패든(모듈 docstring).

    지우다 나는 오류는 로그만 남기고 삼킨다 — 정리 실패로 이 요청의 진짜 결과
    (``SUCCEEDED``/``FAILED``)가 가려지면 안 된다(``worker.py``
    ``_cleanup_work_files`` 와 같은 규율).
    """
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            now_message(f"[{request_id}] 작업 파일 정리 실패(무시하고 계속): {path} — {exc}")


def run_region_extraction_request(
    request_id: str,
    *,
    core: RegionExtractionCoreClient,
    work_dir: Path,
    http_client: httpx.Client | None = None,
    now_message: Callable[[str], None] = logger.info,
    heartbeat_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    """변화 영역 추출 요청 하나를 lease 취득부터 ``SUCCEEDED``/``FAILED`` 까지 끝까지 돈다.

    실패 시 예외를 던진다(``FAILED`` 보고는 시도하되 삼키지 않는다) — 호출자
    (데몬 루프)가 재시도·알림을 정할 수 있게 원인을 그대로 넘긴다.
    """
    fetch = http_client or httpx.Client(
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=600.0, pool=10.0)
    )
    own_client = http_client is None
    now_message(f"[{request_id}] lease 취득")
    lease = lease_or_compat_handle(
        core.acquire_region_extraction_lease(request_id),
        work_kind="region-extraction", resource_id=request_id,
    )
    attempt_dir = attempt_workspace(work_dir, lease)
    extraction_input = core.get_region_extraction_input(request_id)

    if extraction_input.status == "QUEUED":
        core.transition_region_extraction(request_id, "RUNNING")
        now_message(f"[{request_id}] RUNNING")

    heartbeat = LeaseHeartbeat(
        lambda: getattr(
            core, "renew_region_extraction_lease", core.acquire_region_extraction_lease
        )(request_id),
        request_id,
        interval_seconds=heartbeat_interval_seconds,
        now_message=now_message,
        thread_name_prefix="rex-lease",
    )
    heartbeat.start()

    # 다운로드를 시도하기 *전에* 경로를 목록에 넣는다 — 부분 파일도 청소 대상이다
    # (모듈 docstring, worker.py 와 같은 관용구).
    raster_path = attempt_dir / f"{extraction_input.diff_raster_id}.tif"
    downloaded_paths: list[Path] = [raster_path]
    try:
        report = run_region_extraction(
            change_region_set_id=extraction_input.change_region_set_id,
            design_conformance_id=extraction_input.design_conformance_id,
            diff_raster_id=extraction_input.diff_raster_id,
            diff_raster_url=extraction_input.diff_raster_url,
            diff_raster_ref=extraction_input.diff_raster,
            raster_path=raster_path,
            threshold_m=extraction_input.threshold_m,
            extraction_policy=extraction_input.extraction_policy,
            computed_at=datetime.now(UTC),
            http_client=fetch,
        )
        try:
            core.submit_region_extraction(extraction_input.mission_id, report)
        except CoreClientError as exc:
            if exc.verdict != "DUPLICATE_REPORT_ID":
                raise
            # changeRegionSetId 는 이 요청만 만들 수 있는 결정적 값이다 — 이
            # id 로 DUPLICATE 가 나올 수 있는 경우는 이전 시도가 이미 성공
            # 제출한 것뿐이다(design_conformance_worker 와 같은 근거).
            now_message(f"[{request_id}] 리포트 이미 기록됨(재시도, 안전) — {exc}")

        detail = (
            f"변화 영역 {len(report.regions)}개 추출"
            f"(걸러짐 {report.filtered_region_count}개)"
        )
        core.transition_region_extraction(request_id, "SUCCEEDED", detail=detail)
        now_message(f"[{request_id}] SUCCEEDED — {detail}")
    except Exception as exc:  # noqa: BLE001 -- 모듈 docstring: 종류를 안 가린다
        detail = str(exc)[:500]
        now_message(f"[{request_id}] 실패 — FAILED 보고 시도: {detail}")
        try:
            core.transition_region_extraction(request_id, "FAILED", detail=detail)
        except CoreClientError as report_exc:
            now_message(f"[{request_id}] FAILED 보고도 실패(원인은 유지): {report_exc}")
        raise RegionExtractionWorkerRunError(f"[{request_id}] 실행 실패: {exc}") from exc
    finally:
        # 최종 전이까지 lease 를 쥔 채로 두고 그 뒤에 멈춘다(다른 세 워커와 동일).
        heartbeat.stop()
        _cleanup_downloaded_paths(downloaded_paths, request_id, now_message)
        if own_client:
            fetch.close()
        try:
            cleanup_attempt_workspace(work_dir, attempt_dir)
        except OSError as exc:
            now_message(f"[{request_id}] attempt workspace 정리 실패(무시하고 계속): {exc}")


__all__ = ["RegionExtractionWorkerRunError", "run_region_extraction_request"]
