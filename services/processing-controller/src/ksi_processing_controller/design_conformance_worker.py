"""설계 대비 잔량 실행기 — lease 취득부터 SUCCEEDED/FAILED 까지 (M4-A, comparison_worker 대칭).

## 순서가 게이트의 순서다

1. lease 를 잡는다(다른 워커가 같은 요청을 돌리지 못하게).
2. 입력을 받는다 — 설계면·현재 DSM 의 presigned GET + 수직기준 + 구역 + 기준값.
3. ``QUEUED`` 면 ``RUNNING`` 으로 전이한다(재개된 요청이면 이미 ``RUNNING`` 이다).
4. 계산한다(``compute_design_conformance``) — 그 안에서 설계면 바이트의 sha256 이
   검증 시점 값과 같은지 먼저 확인하고, 수직기준 계열이 다르면 계산 자체를 거부한다.
5. 계산이 만든 차분 래스터를 presigned PUT 으로 올리고, **Core 에 확인을 요청한다.**
6. 리포트를 제출한다(멱등).
7. ``SUCCEEDED`` 로 전이한다.

## 왜 "올렸다"고 말하는 것으로 끝나지 않는가

5번의 확인이 이 워커에서 가장 중요한 줄이다. 워커가 PUT 성공을 자기 입으로
보고하는 것만으로는 아무 사실도 성립하지 않는다 — Core 가 **그 객체를 직접 읽어
자기 hashlib 으로** 해시를 다시 계산해 워커의 신고와 맞을 때만 확인 시각을
돌려준다. 그 시각이 없으면 리포트의 ``diffRaster.coreVerifiedDigestAt`` 을 채울 수
없고(계약 필수), 따라서 **리포트가 만들어지지도 않는다**(:class:`_DiffRasterPublisher`
가 예외를 그대로 올린다). 리포트를 받는 쪽도 같은 재해싱을 한 번 더 한다 —
워커의 어느 실수도 "지도와 숫자가 다른 리포트"로 굳지 않는다.

## 실패는 전부 ``FAILED`` 로 수렴한다 (comparison_worker 와 동일 원칙)

어느 단계에서 예외가 나든 ``FAILED`` 전이를 시도하고 원래 예외를 다시 던진다.
재시도는 안전하다: ``designConformanceId`` 는 requestId에서 결정되고, Core는
lease generation별 candidate 객체 키와 digest-bound PUT을 내려준다. 같은 attempt의
exact retry만 같은 candidate를 쓰며 takeover된 generation은 다른 키를 쓴다.

## 이 모듈이 하지 않는 것

- **큐에서 후보를 꺼내오지 않는다.** requestId 를 인자로 받는다(runner 의 몫).
- **id 를 스스로 만들지 않는다.** ``designConformanceId``/``diffRasterId`` 는 Core 가
  준다 — 도출 규칙이 두 곳에 있으면 한쪽만 바뀌는 날 리포트가 미아가 된다.
"""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import httpx
from ksi_change_detection.run_design_conformance import (
    CurrentDsmSource,
    DesignConformanceRunError,
    DesignSource,
    compute_design_conformance,
)
from ksi_event_contracts.vertical_reference import VerticalDatumIncompatibleError
from ksi_geo_spatial.crs import CrsMismatchError, UnsupportedCrsError
from ksi_geo_spatial.vertical import GeoidUnavailableError, load_geoid_grid

from ksi_processing_controller.comparison_worker import LeaseHeartbeat
from ksi_processing_controller.core_client import (
    CoreClientError,
    DesignConformanceCoreClient,
)
from ksi_processing_controller.workspace import (
    attempt_workspace,
    cleanup_attempt_workspace,
    lease_or_compat_handle,
)

logger = logging.getLogger(__name__)

#: lease 갱신 주기(초) — 비교 워커와 같은 값·같은 이유(같은 lease 규약 위에 있다).
_HEARTBEAT_INTERVAL_SECONDS = 10.0


class DesignConformanceWorkerRunError(RuntimeError):
    """설계 대비 실행이 실패했다 — Core 에는 이미 FAILED 로 보고를 시도했다."""


class _DiffRasterPublisher:
    """차분 래스터를 올리고 **Core 가 확인한 시각**을 받아 온다.

    ``run_design_conformance.DiffRasterPublisher`` 프로토콜의 구현이다. 확인이
    없으면 값을 돌려주는 대신 예외를 낸다 — 그래야 리포트가 만들어지지 않는다
    (그 모듈 docstring "왜 래스터 업로드가 이 함수 한가운데 있나").
    """

    def __init__(
        self,
        core: DesignConformanceCoreClient,
        request_id: str,
        *,
        http_client: httpx.Client,
        now_message: Callable[[str], None],
    ) -> None:
        self._core = core
        self._request_id = request_id
        self._http = http_client
        self._now_message = now_message

    def publish_diff_raster(self, path: Path, *, digest: str, size_bytes: int) -> datetime:
        target = self._core.presign_diff_raster_upload(
            self._request_id, digest=digest, size_bytes=size_bytes
        )
        upload_headers = dict(target.required_headers)
        upload_headers["Content-Type"] = target.content_type
        with path.open("rb") as handle:
            response = self._http.put(
                target.upload_url,
                content=handle,
                headers=upload_headers,
            )
        response.raise_for_status()
        # 여기까지는 **워커의 주장**이다. 다음 줄이 그것을 사실로 바꾼다 —
        # Core 가 그 객체를 직접 읽어 자기 hashlib 으로 대조하고, 다르면
        # CoreClientError(DIFF_RASTER_DIGEST_MISMATCH) 로 올라온다.
        verified_at = self._core.verify_diff_raster(
            self._request_id, digest=digest, size_bytes=size_bytes
        )
        self._now_message(
            f"[{self._request_id}] 차분 래스터 확인됨 — {digest} ({size_bytes}B)"
        )
        return verified_at


def run_design_conformance_request(
    request_id: str,
    *,
    core: DesignConformanceCoreClient,
    work_dir: Path,
    http_client: httpx.Client | None = None,
    now_message: Callable[[str], None] = logger.info,
    heartbeat_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    """설계 대비 요청 하나를 lease 취득부터 ``SUCCEEDED``/``FAILED`` 까지 끝까지 돈다.

    실패 시 예외를 던진다(``FAILED`` 보고는 시도하되 삼키지 않는다) — 호출자
    (데몬 루프)가 재시도·알림을 정할 수 있게 원인을 그대로 넘긴다.
    """
    fetch = http_client
    own_client = http_client is None
    now_message(f"[{request_id}] lease 취득")
    lease = lease_or_compat_handle(
        core.acquire_design_conformance_lease(request_id),
        work_kind="design-conformance", resource_id=request_id,
    )
    conformance_input = core.get_design_conformance_input(request_id)

    if conformance_input.status == "QUEUED":
        core.transition_design_conformance(request_id, "RUNNING")
        now_message(f"[{request_id}] RUNNING")

    try:
        attempt_dir = attempt_workspace(work_dir, lease)
    except OSError as exc:
        detail = str(exc)[:500]
        with suppress(CoreClientError):
            core.transition_design_conformance(request_id, "FAILED", detail=detail)
        raise DesignConformanceWorkerRunError(f"[{request_id}] 실행 실패: {exc}") from exc

    heartbeat: LeaseHeartbeat | None = None
    heartbeat_started = False
    raster_path: Path | None = None
    try:
        if fetch is None:
            fetch = httpx.Client(
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=600.0, pool=10.0)
            )
        heartbeat = LeaseHeartbeat(
            lambda: getattr(
                core, "renew_design_conformance_lease", core.acquire_design_conformance_lease
            )(request_id),
            request_id,
            interval_seconds=heartbeat_interval_seconds,
            now_message=now_message,
            thread_name_prefix="dcf-lease",
        )
        heartbeat.start()
        heartbeat_started = True
        # RUNNING 이후 작업 디렉터리 생성도 실행 실패 경계 안에 둔다. 디스크 오류가
        # try 밖에서 나면 요청이 FAILED로 수렴하지 못하고 영구 RUNNING에 남는다.
        # 격자 적재는 try 안이다 — 설정이 깨졌으면(경로는 있는데 파일이 없음)
        # ``load_geoid_grid`` 가 던지고, 그 실패도 FAILED 로 수렴해야 한다.
        # 미설정이면 None 이고, 그건 "정표고를 안 쓴다"는 정상 상태다. 계산 쪽이
        # 변환이 필요한데 None 인 경우에만 거부한다(run_design_conformance).
        geoid_grid = load_geoid_grid()
        report, raster_path = compute_design_conformance(
            design_conformance_id=conformance_input.design_conformance_id,
            diff_raster_id=conformance_input.diff_raster_id,
            current_dsm=CurrentDsmSource(
                ref=conformance_input.current,
                download_url=conformance_input.current_url,
                vertical_reference=conformance_input.current_vertical_reference,
            ),
            design=DesignSource(
                design_surface_id=conformance_input.design_surface_id,
                sha256=conformance_input.design_surface_sha256,
                download_url=conformance_input.design_surface_url,
                vertical_reference=conformance_input.design_vertical_reference,
            ),
            zones=conformance_input.zones,
            zone_crs=conformance_input.zone_crs,
            # 함수 기본값이 아니라 **이 요청의 스냅샷**을 쓴다 — 그래야 원장에
            # 적힌 기준값이 실제로 쓴 값이 된다(comparison_worker 와 같은 근거).
            policy=conformance_input.policy,
            computed_at=datetime.now(UTC),
            geoid_grid=geoid_grid,
            http_client=fetch,
            publish_diff_raster=_DiffRasterPublisher(
                core, request_id, http_client=fetch, now_message=now_message
            ),
            work_dir=attempt_dir,
        )
        try:
            core.submit_design_conformance(conformance_input.mission_id, report)
        except CoreClientError as exc:
            if exc.verdict != "DUPLICATE_REPORT_ID":
                raise
            # designConformanceId 는 이 요청만 만들 수 있는 결정적 값이다 — 이
            # id 로 DUPLICATE 가 나올 수 있는 경우는 이전 시도가 이미 성공 제출한
            # 것뿐이고, 그 리포트는 Core 가 래스터를 재해싱해 확인한 것이다.
            # 달라질 수 있는 필드는 computed_at 뿐이라 안전하게 넘어간다.
            now_message(f"[{request_id}] 리포트 이미 기록됨(재시도, 안전) — {exc}")

        detail = f"설계 대비 순 성토 필요 {report.total_net_m3:.2f}m³ ({len(report.zones)}개 구역)"
        core.transition_design_conformance(request_id, "SUCCEEDED", detail=detail)
        now_message(f"[{request_id}] SUCCEEDED — {detail}")
    except (
        DesignConformanceRunError,
        # INV-020 좌표계 검증(dsm_diff.py)과 수직축 판정이 raise 하는 그대로의
        # 예외 — 여기서 잡지 않으면 "실패는 전부 FAILED 로 수렴한다"는 원칙이
        # 그 두 경우에만 깨져 워커가 죽고 요청은 RUNNING 에 남는다.
        CrsMismatchError,
        UnsupportedCrsError,
        VerticalDatumIncompatibleError,
        # 격자가 없거나(설정 누락) 현장이 격자 범위 밖이면 변환을 못 한다 —
        # **위의 VerticalDatumIncompatibleError 와 다른 사실**이고, detail 로
        # 원장·화면에 그대로 남아 둘이 구분된다("격자를 붙여라" vs "이 도면은
        # 이 산출물과 이을 수 없다").
        GeoidUnavailableError,
        httpx.HTTPError,
        CoreClientError,
        # mkdir/download/write/upload에서 발생하는 로컬 파일 I/O 실패.
        OSError,
    ) as exc:
        detail = str(exc)[:500]
        now_message(f"[{request_id}] 실패 — FAILED 보고 시도: {detail}")
        try:
            core.transition_design_conformance(request_id, "FAILED", detail=detail)
        except CoreClientError as report_exc:
            # Core 가 이미 FAILED 로 보낸 뒤일 수 있다(digest 불일치는 리포트
            # 수신 경로가 그 자리에서 요청을 끝낸다) — 그때 이 전이는
            # ILLEGAL_TRANSITION 이고, 그건 실패가 아니라 이미 끝났다는 뜻이다.
            now_message(f"[{request_id}] FAILED 보고도 실패(원인은 유지): {report_exc}")
        raise DesignConformanceWorkerRunError(f"[{request_id}] 실행 실패: {exc}") from exc
    finally:
        # 최종 전이까지 lease 를 쥔 채로 두고 그 뒤에 멈춘다(비교 워커와 동일).
        if heartbeat_started and heartbeat is not None:
            heartbeat.stop()
        if raster_path is not None:
            # 계산 함수의 계약: 래스터 파일 정리는 호출자 몫이다(업로드 뒤에도
            # 워커가 그 바이트를 다시 볼 수 있어야 해서 그쪽이 지우지 않는다).
            shutil.rmtree(raster_path.parent, ignore_errors=True)
        if own_client and fetch is not None:
            fetch.close()
        try:
            cleanup_attempt_workspace(work_dir, attempt_dir)
        except OSError as exc:
            now_message(f"[{request_id}] attempt workspace 정리 실패(무시하고 계속): {exc}")


__all__ = ["DesignConformanceWorkerRunError", "run_design_conformance_request"]
