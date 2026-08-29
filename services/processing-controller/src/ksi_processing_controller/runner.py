"""워커 실행 진입점 — 발행된 일감 네 종류를 사람 없이 집어서 끝까지 돈다.

## 이 모듈이 메우는 공백

``worker.py`` 는 ``run_job(job_id, ...)`` 까지만 준다 — jobId 를 **누가** 정해
주는지는 그 모듈의 책임 밖이다(모듈 docstring "큐에서 작업을 꺼내오지
않는다"). 지금까지 이 저장소에서 ``run_job`` 의 호출자는 테스트뿐이었다 —
대시보드에서 "재구성 작업 발행" 버튼을 눌러도 ``QUEUED`` 상태만 만들어질 뿐
아무도 그 작업을 집어가지 않았다. 이 모듈이 그 pull 루프다:
``GET /v1/processing-jobs``(``ksi_core.processing_jobs.ProcessingJobStore.
list_pending``) 로 후보를 물어보고, ``run_job`` 으로 끝까지 돈다.

비교 요청(W2)·설계면 검증·설계 대비 잔량(M4-A) 워커도 같은 구멍을 갖고 있었다 —
이 모듈이 한 종류를 다 돌고도 할 일이 없으면 다음 종류의 대기 목록을 본다.
**새 프로세스·새 데몬이 아니다** — 같은 폴링 루프, 같은 프로세스가 네 종류
후보를 순서대로 본다(우선순위와 그 근거는 :func:`run_pending_batch` docstring).

## 왜 별도 데몬이 아닌가

뒤의 셋은 NodeODM 이 필요 없다(Core+스토리지만 읽는다) — 그래서 별도 프로세스로
쪼갤 유혹이 있지만, 그러면 배포 단위가 넷으로 늘고 "이 워커가 지금 뭘 돌리고
있는지"를 네 곳에서 봐야 한다. 한 종류에서 하나를 돌렸으면 그 라운드는 거기서
끝나고, 아무것도 못 돌렸을 때만 다음 종류를 본다.

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

# dfine.py 모듈 최상단은 torch/transformers 를 끌어오지 않는다(둘 다
# load_dfine_detector 내부의 지연 import 다) — 그래서 이 top-level import 는
# ksi-perception 의 base 의존만으로 안전하다(pyproject.toml 주석 "torch/transformers
# 는 끌려오지 않는다"). torch 가 실제로 필요해지는 시점은 감지기를 실제로
# 돌릴 때뿐이고, 그마저도 로드 시점에 typed RUNTIME_MISSING 으로 갈린다.
from ksi_perception.dfine import load_dfine_detector

from ksi_processing_controller.checkpoint_validator import validate_checkpoint_validation
from ksi_processing_controller.comparison_worker import (
    ComparisonWorkerRunError,
    run_comparison_request,
)
from ksi_processing_controller.core_client import (
    CoreClientError,
    HttpCoreClient,
    PendingCheckpointValidation,
    PendingComparisonRequest,
    PendingDesignConformanceRequest,
    PendingDesignSurface,
    PendingJob,
    PendingRegionExtractionRequest,
    WorkerCoreClient,
)
from ksi_processing_controller.design_conformance_worker import (
    DesignConformanceWorkerRunError,
    run_design_conformance_request,
)
from ksi_processing_controller.design_surface_verifier import verify_design_surface
from ksi_processing_controller.http_node_odm import HttpNodeOdmClient
from ksi_processing_controller.observability import (
    bind_correlation_id,
    configure_structured_logging,
)
from ksi_processing_controller.odm import NodeOdmClient
from ksi_processing_controller.odm_masking import ImageDetector
from ksi_processing_controller.region_extraction_worker import (
    RegionExtractionWorkerRunError,
    run_region_extraction_request,
)
from ksi_processing_controller.worker import WorkerRunError, run_job

logger = logging.getLogger(__name__)

_DEFAULT_POLL_INTERVAL_SECONDS = 15.0
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 10.0


def _try_candidates[Candidate](
    kind_label: str,
    *,
    list_fn: Callable[[], list[Candidate]],
    id_of: Callable[[Candidate], str],
    run_fn: Callable[[Candidate], None],
    ran_but_failed: tuple[type[Exception], ...],
    now_message: Callable[[str], None],
) -> bool:
    """한 종류의 대기 후보를 순서대로 시도한다 — 모든 worker queue가 공유하는 골격.

    원래 재구성·비교 두 벌이 같은 모양으로 반복하고 있었고, 여기에 설계면 검증과
    설계 대비 잔량과 후속 queue가 더해졌다. 각자 들고 있으면 "lease 경합은
    실패가 아니다"·"예기치 못한 버그가 워커를 죽이지 않는다" 같은 **판단**이 네
    모든 곳에 복제된다 — 골격만 여기 두고, 종류마다 다른 것(무엇을 조회하고 무엇을
    돌리는가)은 인자로 받는다.

    ``ran_but_failed`` 는 "**돌리기는 했고 워커가 스스로 실패로 끝냈다**"는
    도메인 예외들이다(그 워커가 이미 Core 에 FAILED 보고를 시도했다) — 그건 이
    라운드에 일을 한 것이므로 ``True`` 다. 반대로 lease 경합·Core 오류·예기치
    못한 버그는 **아무 일도 안 한 것**이라 다음 후보로 넘어간다.

    반환값은 "이번 라운드에 실제로 하나를 돌렸는가"다.
    """
    try:
        pending = list_fn()
    except Exception:  # noqa: BLE001 -- Core 장애로 워커 프로세스가 죽으면 안 된다
        logger.exception("%s 대기 목록을 가져오지 못했다 — 다음 폴링에서 재시도한다", kind_label)
        return False

    for candidate in pending:
        candidate_id = id_of(candidate)
        # 이 후보를 처리하는 동안의 모든 로그 줄(아래 now_message 호출은 물론
        # 워커 내부의 logger.* 호출까지)에 id 가 correlation id 로 실린다 —
        # now_message 문자열 접두사 ``f"[{id}] ..."`` 는 사람이 읽을 땐 같은
        # 정보지만 로그 수집기가 필드로 걸러 찾을 수는 없었다.
        with bind_correlation_id(candidate_id):
            try:
                run_fn(candidate)
                return True
            except CoreClientError as exc:
                if exc.verdict == "LEASE_HELD_BY_ANOTHER":
                    now_message(f"[{candidate_id}] 다른 워커가 이미 쥐고 있다 — 다음 후보로")
                else:
                    now_message(f"[{candidate_id}] lease 취득 전 Core 오류 — 다음 후보로: {exc}")
                continue
            except ran_but_failed as exc:
                now_message(f"[{candidate_id}] 실패(Core 에 FAILED 보고 시도됨): {exc}")
                return True
            except Exception:  # noqa: BLE001 -- 예기치 못한 버그 하나가 워커 전체를 죽이지 않는다
                logger.exception("[%s] 예기치 못한 오류 — 다음 후보로 넘어간다", candidate_id)
                continue
    return False


def run_pending_batch(
    *,
    core: WorkerCoreClient,
    odm: NodeOdmClient,
    work_dir: Path,
    heartbeat_interval_seconds: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    http_client: httpx.Client | None = None,
    now_message: Callable[[str], None] = logger.info,
    dynamic_object_detector: ImageDetector | None = None,
) -> bool:
    """대기 목록에서 후보를 순서대로 시도해 하나를 끝까지 돈다.

    ``dynamic_object_detector`` 는 재구성 후보(``_run_reconstruction``)에만
    의미가 있다 — 비교·설계면 검증·설계 대비 잔량은 이미 완주한 산출물을
    읽을 뿐 사진을 새로 ODM 에 올리지 않으므로 마스킹과 무관하다. 생략하면
    (``None``, 기본값) :func:`~ksi_processing_controller.worker.run_job` 도
    같은 기본값으로 마스킹 없이 돈다 — 회귀 없음.

    ## 폴링 우선순위

    재구성 → 설계면 검증 → 검사점 검증 → 두 시점 비교 → 설계 대비 잔량 → 변화 영역 추출

    한 라운드에 하나만 돌리므로 순서가 곧 지연 배분이다. 근거는 다섯:

    1. **재구성이 먼저다.** 나머지의 입력(DSM·점군)을 만드는 것이 재구성이고,
       밀려 있으면 그 뒤 전부가 굶는다(기존 판단 유지 — 이 순서를 바꾸면 M1/M2
       지연 특성이 달라진다).
    2. **설계면 검증이 그 다음이다.** 파일 하나를 해시하는 초 단위 작업인데,
       그 결과가 없으면 사용자는 설계 대비 요청을 **만들 수조차 없다**(Core 가
       VERIFIED 설계면만 받는다). 값싸면서 사람을 막고 있는 일을 분 단위 계산
       뒤로 미루면, 업로드 직후 피드백이라는 검증 단계의 존재 이유가 사라진다.
    3. **검사점 검증은 비교보다 앞이다.** 두 파일을 읽는 짧은 작업이고, 서버가
       계산한 RMSE가 먼저 있어야 뒤 비교의 불확실성 값이 근거를 갖는다. 읽기
       장애는 SEALED로 남겨 재시도하고, CSV/DSM의 결정적 결함만 typed rejection
       으로 끝낸다.
    4. **비교가 설계 대비보다 앞이다.** 둘 다 분 단위 계산이라 어느 쪽을 먼저
       둬도 처리량은 같지만, 기존 경로(M1/M2)의 지연 특성을 새 기능이 밀어내지
       않게 둔다 — 새로 들어온 쪽이 기다리는 편이 회귀가 아니다.
    5. **변화 영역 추출이 가장 뒤다(M4-E).** 이 요청은 설계 대비 잔량 리포트가
       이미 기록된 뒤에만 만들어질 수 있고(생성 게이트 ``UNKNOWN_DESIGN_
       CONFORMANCE``), 계산 자체도 이미 있는 diffRaster 를 다시 읽는 값싼
       후처리다 — 새 기능이 기존 경로의 지연 특성을 밀어내지 않게 가장 뒤에 둔다.

    반환값은 "이번 라운드에 실제로 무언가를 하나 돌렸는가"다 — 성공이든 워커가
    스스로 실패로 끝냈든(이미 Core 에 ``FAILED`` 보고를 시도했다) ``True`` 다.
    **다른 워커에게 lease 를 뺏겼거나 Core 가 후보 하나에 대해 오류를 낸 것은 이
    워커가 아무 일도 안 한 것과 같으므로** 다음 후보로 넘어간다 — 여섯 목록을
    전부 소진해도 아무것도 못 돌렸으면 ``False``(호출자가 대기할 시간이다).

    ``http_client`` 는 시험 주입용이다(각 워커가 이미 받는 자리를 그대로
    통과시킨다) — 생략하면(프로덕션 기본 경로) 각자 실제 ``httpx.Client`` 를
    스스로 만든다.
    """

    def _run_reconstruction(candidate: PendingJob) -> None:
        run_job(
            candidate.job_id,
            core=core,
            odm=odm,
            work_dir=work_dir,
            http_client=http_client,
            poll_interval_seconds=heartbeat_interval_seconds,
            now_message=now_message,
            dynamic_object_detector=dynamic_object_detector,
        )

    def _run_design_surface_verification(candidate: PendingDesignSurface) -> None:
        # 이 워커만 http_client 를 필수로 받는다(다운로드 전용이라 스스로 만들
        # 자리가 없다) — 주입이 없으면 이 한 건을 위해 만들고 그 자리에서 닫는다.
        client = http_client or httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=600.0, pool=10.0)
        )
        try:
            verify_design_surface(
                candidate.design_surface_id,
                download_url=candidate.download_url,
                core=core,
                http_client=client,
                work_dir=work_dir,
                source_format=candidate.source_format,
                surface_selector=candidate.surface_selector,
                declared_crs=candidate.declared_crs,
                normalization_upload_url=candidate.normalization_upload_url,
            )
        finally:
            if http_client is None:
                client.close()

    def _run_checkpoint_validation(candidate: PendingCheckpointValidation) -> None:
        client = http_client or httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=600.0, pool=10.0)
        )
        try:
            validate_checkpoint_validation(
                candidate,
                core=core,
                http_client=client,
                work_dir=work_dir,
            )
        finally:
            if http_client is None:
                client.close()

    def _run_comparison(candidate: PendingComparisonRequest) -> None:
        run_comparison_request(
            candidate.request_id,
            core=core,
            work_dir=work_dir,
            http_client=http_client,
            now_message=now_message,
        )

    def _run_design_conformance(candidate: PendingDesignConformanceRequest) -> None:
        run_design_conformance_request(
            candidate.request_id,
            core=core,
            work_dir=work_dir,
            http_client=http_client,
            now_message=now_message,
        )

    def _run_region_extraction(candidate: PendingRegionExtractionRequest) -> None:
        run_region_extraction_request(
            candidate.request_id,
            core=core,
            work_dir=work_dir,
            http_client=http_client,
            now_message=now_message,
        )

    if _try_candidates(
        "재구성 작업",
        list_fn=core.list_pending,
        id_of=lambda c: c.job_id,
        run_fn=_run_reconstruction,
        ran_but_failed=(WorkerRunError,),
        now_message=now_message,
    ):
        return True
    if _try_candidates(
        "설계면 검증",
        list_fn=core.list_pending_design_surfaces,
        id_of=lambda c: c.design_surface_id,
        run_fn=_run_design_surface_verification,
        # 이 워커에는 "돌렸지만 실패"가 없다 — 파일을 열지 못한 것은 Core 에
        # 정상 보고되는 결말이고(REJECTED), 그 밖의 실패는 네트워크·Core 오류라
        # 아무 일도 안 한 것이다(다음 후보로).
        ran_but_failed=(),
        now_message=now_message,
    ):
        return True
    if _try_candidates(
        "독립 검사점 검증",
        list_fn=core.list_pending_checkpoint_validations,
        id_of=lambda c: c.validation_id,
        run_fn=_run_checkpoint_validation,
        # 결정적 CSV/DSM 결함은 validator 가 Core 에 직접 typed rejection 으로
        # 기록하고 정상 종료한다. 네트워크/스토리지 오류는 예외로 남겨 SEALED
        # 상태에서 재시도하므로 여기서 '실행 실패'로 분류하지 않는다.
        ran_but_failed=(),
        now_message=now_message,
    ):
        return True
    if _try_candidates(
        "두 시점 비교",
        list_fn=core.list_pending_comparisons,
        id_of=lambda c: c.request_id,
        run_fn=_run_comparison,
        ran_but_failed=(ComparisonWorkerRunError,),
        now_message=now_message,
    ):
        return True
    if _try_candidates(
        "설계 대비 잔량",
        list_fn=core.list_pending_design_conformances,
        id_of=lambda c: c.request_id,
        run_fn=_run_design_conformance,
        ran_but_failed=(DesignConformanceWorkerRunError,),
        now_message=now_message,
    ):
        return True
    return _try_candidates(
        "변화 영역 추출",
        list_fn=core.list_pending_region_extractions,
        id_of=lambda c: c.request_id,
        run_fn=_run_region_extraction,
        ran_but_failed=(RegionExtractionWorkerRunError,),
        now_message=now_message,
    )


def run_forever(
    *,
    core: WorkerCoreClient,
    odm: NodeOdmClient,
    work_dir: Path,
    poll_interval_seconds: float = _DEFAULT_POLL_INTERVAL_SECONDS,
    heartbeat_interval_seconds: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    http_client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
    should_stop: Callable[[], bool] = lambda: False,
    now_message: Callable[[str], None] = logger.info,
    dynamic_object_detector: ImageDetector | None = None,
) -> None:
    """``should_stop()`` 이 참이 될 때까지 :func:`run_pending_batch` 를 반복한다.

    한 라운드에서 작업을 하나 돌렸으면(``True``) 대기열에 더 있을 수 있으니
    바로 다음 라운드로 넘어간다 — 돌린 게 없을 때만 ``poll_interval_seconds``
    만큼 쉰다. 그래야 밀린 QUEUED 작업들이 폴링 간격만큼씩 지연되며 순서대로
    빠지지 않고, 빈 상태에서는 Core 를 쉬지 않고 두드리지 않는다.

    ``dynamic_object_detector`` 는 그대로 :func:`run_pending_batch` 로,
    거기서 다시 재구성 후보에만 :func:`~ksi_processing_controller.worker.run_job`
    으로 흘러간다(PRD §15.2 ④ 선택적 활성화 지점 — 생략하면 회귀 없음).
    """
    while not should_stop():
        ran = run_pending_batch(
            core=core,
            odm=odm,
            work_dir=work_dir,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            http_client=http_client,
            now_message=now_message,
            dynamic_object_detector=dynamic_object_detector,
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


_DYNAMIC_OBJECT_MODEL_DIR_ENV = "KSI_WORKER_DYNAMIC_OBJECT_MODEL_DIR"


def _load_dynamic_object_detector_from_env() -> ImageDetector | None:
    """``KSI_WORKER_DYNAMIC_OBJECT_MODEL_DIR`` — 동적 객체 마스킹의 선택적 스위치
    (PRD §15.2 ④, ``worker.py::run_job`` 의 ``dynamic_object_detector`` 주입 지점).

    **기본은 꺼짐이다.** torch·모델 가중치가 모든 배포에 있는 게 아니다
    (``ksi-perception`` 은 base 의존이라 이 값을 안 주면 torch 는 끝까지
    import 되지 않는다 — 위 top-level import 주석 참고). 미설정이면(``None``
    또는 빈 문자열) ``None`` 을 돌려준다 — 지금까지와 완전히 동일한 동작.

    **설정했는데 로드가 실패하면 워커 기동 자체를 거부한다(fail-closed).**
    ``production.py``/``_require_env`` 와 같은 정신이다: "미설정 시 기본 꺼짐"과
    "명시적으로 켰는데 조용히 꺼진 채 도는 것"은 다른 사안이다 — 후자를
    허용하면 운영자가 "이 배포는 사람·차량을 지운다"고 믿고 있는데 실제로는
    한 번도 지운 적 없는 상태가, 로그를 뒤지지 않는 한 구분되지 않는다. 그래서
    이 값이 있는 한 로드 실패는 경고로 넘기지 않고 즉시 ``RuntimeError`` 다 —
    운영자는 경로를 고치거나, 마스킹을 정말 원치 않으면 이 변수 자체를 지운다.
    (반대로 사진 1장의 탐지 실패는 ``run_job`` 안에서 경고만 남기고 계속한다
    — 그건 이미 켜진 마스킹이 부분적으로 못 하는 경우이지, 마스킹을 켤 수
    있는지 자체가 불확실한 경우가 아니다.)
    """
    raw = os.environ.get(_DYNAMIC_OBJECT_MODEL_DIR_ENV)
    if not raw:
        return None
    local_dir = Path(raw)
    if not local_dir.is_dir():
        raise RuntimeError(
            f"{_DYNAMIC_OBJECT_MODEL_DIR_ENV}={raw!r} 는 존재하는 디렉터리가 아니다 — "
            "tools/fetch_model.py 로 모델을 먼저 받는다"
        )
    result = load_dfine_detector(local_dir=local_dir)
    if not result.ok:
        raise RuntimeError(
            f"{_DYNAMIC_OBJECT_MODEL_DIR_ENV}={raw!r} 로 동적 객체 탐지기 로드 실패"
            f"({result.status}): {result.detail} — 마스킹을 켜려면 이 경로를 고치고, "
            f"원치 않으면 {_DYNAMIC_OBJECT_MODEL_DIR_ENV} 를 설정하지 않는다"
        )
    assert result.detector is not None
    return result.detector


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
    # 미설정이면 None(마스킹 없음, 회귀 없음) — 설정했는데 로드 실패면 여기서
    # RuntimeError 로 워커 기동 자체가 거부된다(fail-closed, 함수 docstring).
    dynamic_object_detector = _load_dynamic_object_detector_from_env()

    core = HttpCoreClient(core_base_url, token=core_token)
    odm = HttpNodeOdmClient(nodeodm_base_url)

    stop_event = threading.Event()

    def _handle_signal(signum: int, frame: object) -> None:
        del frame
        logger.info("신호 %s 수신 — 진행 중인 작업을 마친 뒤 다음 폴링에서 종료한다", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # 운영자가 로그만 보고 "지금 이 배포가 사람·차량을 지우는 배포인가"를 알 수
    # 있어야 한다 — masking=on/off 를 기존 시작 로그 줄에 얹는다.
    masking_state = "on" if dynamic_object_detector is not None else "off"
    logger.info(
        "워커 시작 — core=%s nodeodm=%s work_dir=%s poll=%ss heartbeat=%ss masking=%s",
        core_base_url, nodeodm_base_url, work_dir, poll_interval_seconds,
        heartbeat_interval_seconds, masking_state,
    )
    try:
        run_forever(
            core=core,
            odm=odm,
            work_dir=work_dir,
            poll_interval_seconds=poll_interval_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            should_stop=stop_event.is_set,
            dynamic_object_detector=dynamic_object_detector,
        )
    finally:
        core.close()
        odm.close()
    logger.info("워커 종료")
    raise SystemExit(0)


if __name__ == "__main__":
    main()


__all__ = ["run_forever", "run_pending_batch", "main"]
