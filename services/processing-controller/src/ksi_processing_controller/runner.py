"""워커 실행 진입점 — 발행된 재구성 작업·비교 요청을 사람 없이 집어서 끝까지 돈다.

## 이 모듈이 메우는 공백

``worker.py`` 는 ``run_job(job_id, ...)`` 까지만 준다 — jobId 를 **누가** 정해
주는지는 그 모듈의 책임 밖이다(모듈 docstring "큐에서 작업을 꺼내오지
않는다"). 지금까지 이 저장소에서 ``run_job`` 의 호출자는 테스트뿐이었다 —
대시보드에서 "재구성 작업 발행" 버튼을 눌러도 ``QUEUED`` 상태만 만들어질 뿐
아무도 그 작업을 집어가지 않았다. 이 모듈이 그 pull 루프다:
``GET /v1/processing-jobs``(``ksi_core.processing_jobs.ProcessingJobStore.
list_pending``) 로 후보를 물어보고, ``run_job`` 으로 끝까지 돈다.

``comparison_worker.run_comparison_request`` 도 같은 구멍을 갖고 있었다(W2) —
이 모듈이 재구성 후보를 다 돌고도 할 일이 없으면 ``GET /v1/comparison-requests``
로 비교 요청 후보도 확인한다. **새 프로세스·새 데몬이 아니다** — 같은 폴링
루프, 같은 프로세스가 두 종류 후보를 순서대로 본다(아래 "왜 별도 데몬이 아닌가").

## 왜 별도 데몬이 아닌가

비교 요청 실행은 NodeODM 이 필요 없다(Core+스토리지만 읽는다) — 그래서 별도
프로세스로 쪼갤 유혹이 있지만, 그러면 배포 단위가 둘로 늘고 "이 워커가 지금
뭘 돌리고 있는지"를 두 곳에서 봐야 한다. 재구성 후보가 없을 때만(그 라운드에
아무것도 안 돌렸을 때만) 비교 후보를 본다 — 재구성이 밀려 있으면 그쪽이
우선이다(재구성이 비교의 입력이기도 하므로 자연스러운 우선순위).

## 프로세스 하나가 한 번에 하나만 돈다

``worker.py`` 모듈 docstring과 같은 전제다 — 동시성은 프로세스를 여러 개
띄우는 것으로 얻는다(``lease`` 가 이미 그 경합을 막는다). 이 루프는 순차적으로
후보를 시도할 뿐, 스레드·비동기로 여러 작업을 동시에 잡지 않는다.

## 다른 워커에게 진 경합은 실패가 아니다

``list_pending`` 이 돌려준 후보를 다른 워커가 먼저 leased 했으면
(``LEASE_HELD_BY_ANOTHER``) 이 워커의 잘못이 아니다 — 로그만 남기고 다음
후보로 넘어간다. Core 에 아예 닿지 못하는 등 진짜 오류는 그 폴링 라운드를
빈 것으로 취급해(다음 폴링에서 재시도) 워커 프로세스 자체가 죽지 않는다 —
발행 하나가 잘못됐다고 워커 전체가 멈추면 그 뒤에 쌓인 다른 임무의 재구성도
같이 막힌다.

## 종료는 진행 중인 작업을 끊지 않는다

SIGTERM/SIGINT 는 다음 폴링 경계에서만 확인한다. ODM 재구성은 몇 시간짜리
작업이라(``worker.py`` heartbeat 관련 주석 참조) 중간에 끊으면 부분 산출물이
남거나 lease 가 만료될 때까지 그 작업을 아무도 못 건드리게 된다 — 컨테이너가
정상 종료(graceful shutdown)를 못 받고 그냥 죽어도(OOM kill·호스트 재기동 등)
lease 는 만료 시각을 지나면 저절로 회수 가능해지고, 다음 절이 그 회수를
실제로 실행한다.

## 죽은 워커의 작업은 사람 개입 없이 회수된다

``list_pending`` 은 ``QUEUED`` 뿐 아니라 **lease 가 만료된 ``RUNNING``**
작업도 후보로 돌려준다(``ProcessingJobStore.list_pending`` docstring —
``acquire_lease`` 자체가 원래 "죽은 워커의 작업은 별도 조치 없이 만료 후
회수된다"고 설계돼 있었는데, 이 pull 표면이 처음엔 ``QUEUED`` 로만 좁혀져
있어 그 회수 경로가 무의미해져 있었다). 워커 프로세스가 재구성 도중
죽으면, **다른 워커든 재시작된 같은 워커든** 다음 폴링에서 그 jobId 를 다시
``acquire_lease`` 해 처음부터 다시 돈다 — 사람이 상태를 되돌리거나 재발행할
필요가 없다. 죽기 직전에 산출물 일부를 이미 등록해 뒀다면(드문 창 — 등록
루프는 몇 시간짜리 ODM 대기보다 훨씬 짧다) 그 항목에서 ``DUPLICATE_ARTIFACT``
로 다시 ``FAILED`` 될 수 있다 — 그래도 "영원히 멈춤"보다는 낫고, 사유가
로그에 남아 사람이 개입할 신호가 된다. 부분 성공을 이어받는 것(등록된
산출물은 건너뛰고 나머지만 다시 만드는 것)은 이 모듈의 범위 밖이다.
"""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import httpx

from ksi_processing_controller.comparison_worker import (
    ComparisonWorkerRunError,
    run_comparison_request,
)
from ksi_processing_controller.core_client import CoreClient, CoreClientError, HttpCoreClient
from ksi_processing_controller.http_node_odm import HttpNodeOdmClient
from ksi_processing_controller.observability import (
    bind_correlation_id,
    configure_structured_logging,
)
from ksi_processing_controller.odm import NodeOdmClient
from ksi_processing_controller.worker import WorkerRunError, run_job

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_SECONDS = 15.0
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 10.0


def _try_reconstruction_candidates(
    *,
    core: CoreClient,
    odm: NodeOdmClient,
    work_dir: Path,
    heartbeat_interval_seconds: float,
    http_client: httpx.Client | None,
    now_message: Callable[[str], None],
) -> bool:
    try:
        pending = core.list_pending()
    except Exception:  # noqa: BLE001 -- Core 장애로 워커 프로세스가 죽으면 안 된다
        logger.exception("대기 작업 목록을 가져오지 못했다 — 다음 폴링에서 재시도한다")
        return False

    for candidate in pending:
        # 이 후보를 처리하는 동안의 모든 로그 줄(아래 now_message 호출은 물론
        # run_job 내부의 logger.* 호출까지)에 jobId 가 correlation id 로
        # 실린다 — now_message 문자열 접두사 ``f"[{job_id}] ..."`` 는 사람이
        # 읽을 땐 같은 정보지만 로그 수집기가 필드로 걸러 찾을 수는 없었다.
        with bind_correlation_id(candidate.job_id):
            try:
                run_job(
                    candidate.job_id,
                    core=core,
                    odm=odm,
                    work_dir=work_dir,
                    http_client=http_client,
                    poll_interval_seconds=heartbeat_interval_seconds,
                    now_message=now_message,
                )
                return True
            except CoreClientError as exc:
                if exc.verdict == "LEASE_HELD_BY_ANOTHER":
                    now_message(f"[{candidate.job_id}] 다른 워커가 이미 쥐고 있다 — 다음 후보로")
                else:
                    now_message(
                        f"[{candidate.job_id}] lease 취득 전 Core 오류 — 다음 후보로: {exc}"
                    )
                continue
            except WorkerRunError as exc:
                now_message(f"[{candidate.job_id}] 실패(Core 에 FAILED 보고 시도됨): {exc}")
                return True
            except Exception:  # noqa: BLE001 -- 예기치 못한 버그 하나가 워커 전체를 죽이지 않는다
                logger.exception("[%s] 예기치 못한 오류 — 다음 후보로 넘어간다", candidate.job_id)
                continue
    return False


def _try_comparison_candidates(
    *,
    core: CoreClient,
    work_dir: Path,
    http_client: httpx.Client | None,
    now_message: Callable[[str], None],
) -> bool:
    """비교 요청 후보를 순서대로 시도한다 — ``_try_reconstruction_candidates`` 와
    동형 처리(NodeODM 이 필요 없다는 것만 다르다, 모듈 docstring)."""
    try:
        pending = core.list_pending_comparisons()
    except Exception:  # noqa: BLE001 -- Core 장애로 워커 프로세스가 죽으면 안 된다
        logger.exception("대기 비교 요청 목록을 가져오지 못했다 — 다음 폴링에서 재시도한다")
        return False

    for candidate in pending:
        with bind_correlation_id(candidate.request_id):
            try:
                run_comparison_request(
                    candidate.request_id,
                    core=core,
                    work_dir=work_dir,
                    http_client=http_client,
                    now_message=now_message,
                )
                return True
            except CoreClientError as exc:
                if exc.verdict == "LEASE_HELD_BY_ANOTHER":
                    now_message(
                        f"[{candidate.request_id}] 다른 워커가 이미 쥐고 있다 — 다음 후보로"
                    )
                else:
                    now_message(
                        f"[{candidate.request_id}] lease 취득 전 Core 오류 — 다음 후보로: {exc}"
                    )
                continue
            except ComparisonWorkerRunError as exc:
                now_message(f"[{candidate.request_id}] 실패(Core 에 FAILED 보고 시도됨): {exc}")
                return True
            except Exception:  # noqa: BLE001 -- 예기치 못한 버그 하나가 워커 전체를 죽이지 않는다
                logger.exception(
                    "[%s] 예기치 못한 오류 — 다음 후보로 넘어간다", candidate.request_id
                )
                continue
    return False


def run_pending_batch(
    *,
    core: CoreClient,
    odm: NodeOdmClient,
    work_dir: Path,
    heartbeat_interval_seconds: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    http_client: httpx.Client | None = None,
    now_message: Callable[[str], None] = logger.info,
) -> bool:
    """대기 목록에서 후보를 순서대로 시도해 하나를 끝까지 돈다.

    재구성 후보(``GET /v1/processing-jobs``)를 먼저 본다 — 전부 소진해도
    아무것도 못 돌렸으면(``False``) 비교 요청 후보(``GET /v1/comparison-requests``)
    도 본다(모듈 docstring "왜 별도 데몬이 아닌가"). 반환값은 "이번 라운드에
    실제로 무언가를 하나 돌렸는가"다 — 성공(SUCCEEDED)이든 워커가 스스로
    실패로 끝냈든(``WorkerRunError``/``ComparisonWorkerRunError``, 이미 Core 에
    ``FAILED`` 보고를 시도했다) 상관없이 ``True`` 다. **다른 워커에게 lease 를
    뺏겼거나 Core 가 후보 하나에 대해 오류를 낸 것은 이 워커가 아무 일도 안 한
    것과 같으므로** 다음 후보로 넘어간다 — 재구성·비교 두 목록을 전부 소진해도
    아무것도 못 돌렸으면 ``False`` (호출자가 대기할 시간이다).

    ``http_client`` 는 시험 주입용이다(``run_job``/``run_comparison_request`` 가
    이미 받는 자리를 그대로 통과시킨다) — 생략하면(프로덕션 기본 경로) 각자
    실제 ``httpx.Client`` 를 스스로 만든다.
    """
    ran = _try_reconstruction_candidates(
        core=core,
        odm=odm,
        work_dir=work_dir,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
        http_client=http_client,
        now_message=now_message,
    )
    if ran:
        return True
    return _try_comparison_candidates(
        core=core, work_dir=work_dir, http_client=http_client, now_message=now_message
    )


def run_forever(
    *,
    core: CoreClient,
    odm: NodeOdmClient,
    work_dir: Path,
    poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    heartbeat_interval_seconds: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    http_client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] = lambda: False,
    now_message: Callable[[str], None] = logger.info,
) -> None:
    """``should_stop()`` 이 참이 될 때까지 :func:`run_pending_batch` 를 반복한다.

    한 라운드에서 작업을 하나 돌렸으면(``True``) 대기열에 더 있을 수 있으니
    바로 다음 라운드로 넘어간다 — 돌린 게 없을 때만 ``poll_interval_seconds``
    만큼 쉰다. 그래야 밀린 QUEUED 작업들이 폴링 간격만큼씩 지연되며 순서대로
    빠지지 않고, 빈 상태에서는 Core 를 쉬지 않고 두드리지 않는다.
    """
    while not should_stop():
        ran = run_pending_batch(
            core=core,
            odm=odm,
            work_dir=work_dir,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            http_client=http_client,
            now_message=now_message,
        )
        if not ran:
            sleep(poll_interval_seconds)


def _require_env(name: str) -> str:
    """production.py 와 같은 fail-closed 관용구 — 값이 없으면 즉시 거부한다."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} 환경변수가 필요하다 — 워커는 기본값으로 넘어가지 않는다")
    return value


def _positive_float_env(name: str, *, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name}={raw!r} 는 숫자여야 한다") from exc
    if value <= 0:
        raise RuntimeError(f"{name}={raw!r} 는 0보다 커야 한다")
    return value


def main() -> NoReturn:
    """CLI 진입점 — ``uv run ksi-processing-worker`` (``[project.scripts]``)."""
    # 기본은 JSON(Dockerfile.worker 가 이 스크립트의 유일한 컨테이너 진입점이다
    # — production.py 와 같은 이유). 터미널에서 직접 돌려보며 눈으로 읽을 때는
    # KSI_WORKER_LOG_FORMAT=text 로 run_core_dev.py 와 같은 한 줄 형식을 쓴다.
    configure_structured_logging(
        level=os.environ.get("KSI_WORKER_LOG_LEVEL", "INFO"),
        json_format=os.environ.get("KSI_WORKER_LOG_FORMAT", "json").strip().lower() != "text",
    )

    core_base_url = _require_env("KSI_WORKER_CORE_BASE_URL")
    core_token = _require_env("KSI_WORKER_CORE_TOKEN")
    nodeodm_base_url = _require_env("KSI_WORKER_NODEODM_BASE_URL")
    # run_job() 이 이 경로를 mkdir(parents=True, exist_ok=True) 로 직접 만든다 —
    # 여기서 존재를 미리 요구하지 않는다(스크래치 공간이라 볼륨을 반드시
    # 미리 마련할 이유가 없다, Core 의 KSI_CORE_DATA_DIR 와는 성격이 다르다).
    work_dir = Path(_require_env("KSI_WORKER_WORK_DIR"))
    poll_interval_seconds = _positive_float_env(
        "KSI_WORKER_POLL_INTERVAL_SECONDS", default=_DEFAULT_POLL_INTERVAL_SECONDS
    )
    heartbeat_interval_seconds = _positive_float_env(
        "KSI_WORKER_HEARTBEAT_INTERVAL_SECONDS", default=_DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    )

    core = HttpCoreClient(core_base_url, token=core_token)
    odm = HttpNodeOdmClient(nodeodm_base_url)

    stop_event = threading.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        del frame
        logger.info("신호 %s 수신 — 진행 중인 작업을 마친 뒤 다음 폴링에서 종료한다", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info(
        "워커 시작 — core=%s nodeodm=%s work_dir=%s poll=%ss heartbeat=%ss",
        core_base_url, nodeodm_base_url, work_dir, poll_interval_seconds,
        heartbeat_interval_seconds,
    )
    try:
        run_forever(
            core=core,
            odm=odm,
            work_dir=work_dir,
            poll_interval_seconds=poll_interval_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            should_stop=stop_event.is_set,
        )
    finally:
        core.close()
        odm.close()
    logger.info("워커 종료")
    raise SystemExit(0)


if __name__ == "__main__":
    main()


__all__ = ["run_forever", "run_pending_batch", "main"]
