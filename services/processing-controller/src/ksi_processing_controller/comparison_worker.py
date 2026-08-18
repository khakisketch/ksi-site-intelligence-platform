"""비교 요청 실행기 — lease 취득부터 SUCCEEDED/FAILED 까지 (W2, worker.py 대칭).

## 순서가 게이트의 순서다 (worker.py 와 동일 구조)

1. lease 를 잡는다(다른 워커가 같은 요청을 돌리지 못하게).
2. 입력을 받는다 — presigned URL + 그 산출물이 어느 (작업, 산출물)인지(``ArtifactRef``).
3. ``QUEUED`` 면 ``RUNNING`` 으로 전이한다(재개된 요청이면 이미 ``RUNNING`` 이라
   건너뛴다 — ``ComparisonInput.status`` 로만 판정한다, ``JobInput.status`` 와 동형).
4. point_cloud 쌍이 둘 다 있으면 C2C 변화탐지를 계산해 제출한다.
5. dsm 쌍 + 구역이 전부 있으면 체적 변화를 계산해 제출한다.
6. 시도한 계산이 하나라도 있으면(요약이 비지 않았으면) ``SUCCEEDED`` 로 전이한다.

생성 시점엔 어느 쪽도 시도하지 않는 요청(둘 다 조건 미충족)은 여기 도달하지
않는다 — ``ComparisonRequestStore.create()`` 가 이미 ``NOTHING_TO_COMPARE`` 로
요청 생성 자체를 거부한다(``ksi_core.comparison_requests`` 모듈 docstring).
하지만 생성 이후 입력이 사라질 수 있다(산출물 회수 등) — 그때 4~5 를 둘 다
건너뛰면 요약이 빈 채로 남는다. 그 경우도 ``SUCCEEDED`` 로 보내지 않는다
(아래 "실패는 전부 FAILED 로 수렴한다"와 같은 원칙 — 계산 안 한 성공은 없다).

## 실패는 전부 ``FAILED`` 로 수렴한다 (worker.py 와 동일 원칙)

4~5 어느 단계에서 예외가 나든 ``FAILED`` 전이를 시도하고 원래 예외를 다시
던진다. 한쪽 계산(예: 변화탐지)이 이미 성공적으로 제출된 뒤 다른 쪽(체적)이
실패해도 요청 전체를 ``FAILED`` 로 본다 — 제출은 멱등이므로(``changeDetectionId``/
``volumeChangeId`` 를 ``requestId`` 로 결정적으로 고정, 대표자 확정 사항) 재시도가
이미 성공한 부분을 다시 올려도 Core 가 같은 내용으로 멱등 처리한다. 부분 성공을
별도 상태로 표현하지 않는다 — 이 store 의 상태기계에 QUEUED/RUNNING/SUCCEEDED/
FAILED 넷뿐이다(``comparison_requests.py`` 의 ``_ALLOWED_TRANSITIONS``).

## 이 모듈이 하지 않는 것

- **큐에서 후보를 꺼내오지 않는다.** requestId 를 인자로 받는다(worker.py 와 동일).
- **동시에 여러 요청을 돌리지 않는다.** 동시성은 프로세스를 여러 개 띄우는
  것으로 얻는다(lease 가 경합을 막는다) — worker.py 와 동일 전제.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
from ksi_change_detection.run_change_detection import (
    ChangeDetectionRunError,
    compute_and_submit_change_detection,
)
from ksi_change_detection.run_volume_change import (
    ArtifactSource,
    VolumeChangeRunError,
    compute_and_submit,
)
from ksi_event_contracts.vertical_reference import (
    VerticalDatumIncompatibleError,
    assert_comparable_vertical,
)
from ksi_geo_spatial.crs import CrsMismatchError, UnsupportedCrsError

from ksi_processing_controller.core_client import ComparisonInput, CoreClient, CoreClientError

logger = logging.getLogger(__name__)

#: **레거시 대체값** — 정본이 아니다.
#:
#: 이 상수는 원래 "M1 의 유일한 엔진(ODM)은 지오이드 변환을 내지 않으니 DSM 은
#: 항상 타원체고다"라는 워커의 **가정**이었고, 그 가정이 그대로 리포트의
#: ``verticalDatum`` 이 됐다. 지금은 산출물이 자기 수직기준을 스스로 선언하므로
#: (``ProcessingArtifact.verticalReference``, v1.2) 정본은 산출물 쪽에 있다.
#:
#: 이 값이 남아 있는 이유는 하나다 — 수직기준 개념 이전에 등록된 M1/M2 산출물이
#: 실재하고, 그것들의 비교를 소급해서 못 하게 만들지 않기로 했기 때문이다.
#: 그 경우에만 쓰이고, 쓰일 때마다 경고를 남긴다(:func:`_resolve_vertical_datum`).
_LEGACY_VERTICAL_DATUM = "ellipsoidal_native"


#: lease 갱신 주기(초). Core 의 lease TTL 은 15분이고(``processing_jobs.
#: DEFAULT_LEASE_TTL``) 여기 계산은 자료 크기에 따라 그보다 오래 걸릴 수 있다.
#: runner.py 의 재구성 heartbeat 와 같은 값을 쓴다(``_DEFAULT_HEARTBEAT_
#: INTERVAL_SECONDS``) — 두 워커가 같은 lease 규약 위에 있으므로 주기를 다르게
#: 둘 이유가 없다.
_HEARTBEAT_INTERVAL_SECONDS = 10.0


class ComparisonWorkerRunError(RuntimeError):
    """비교 요청 실행이 실패했다 — Core 에는 이미 FAILED 로 보고를 시도했다."""


class LeaseHeartbeat:
    """계산이 도는 동안 lease 를 주기적으로 갱신한다.

    ## 왜 갱신 호출을 인자로 받는가

    설계 대비 워커(``design_conformance_worker``)가 같은 필요를 갖는다 — 자료를
    내려받고 차분하고 올리는 직선 코드라 갱신할 자리가 없다는 성질까지 같다.
    두 워커가 부르는 Core 메서드만 다르므로(``acquire_comparison_lease`` vs
    ``acquire_design_conformance_lease``) 그 한 줄을 호출자가 준다 — 이 클래스가
    특정 Core Protocol 에 묶이면 두 벌이 되고, 그러면 "갱신 실패로 계산을 죽이지
    않는다"는 판단도 두 벌이 된다.

    ## 왜 재구성 워커와 모양이 다른가

    ``worker.py`` 는 ODM 완주를 **폴링**하므로 그 루프 안에서 갱신할 수 있다
    (``run_to_completion(poll=...)``). 비교 계산은 폴링 지점이 없는 직선 코드다
    (내려받고, KD-tree 를 돌리고, 제출한다) — 갱신할 자리가 아예 없어서 별도
    스레드로 둔다. 계산 함수들에 콜백을 뚫는 대안은 ``ksi-change-detection``
    의 순수 계산 API 에 워커의 관심사(lease)를 섞는 일이라 택하지 않았다.

    ## 갱신 실패로 계산을 죽이지 않는다

    갱신이 실패하는 경우는 둘이다 — 일시적 Core 장애(다음 tick 에 회복된다)와
    lease 를 이미 뺏긴 경우(회복 불가). 둘을 여기서 가르지 않는다: 어느 쪽이든
    **계산은 끝까지 돌리고**, 뺏긴 것이 사실이라면 마지막
    ``transition_comparison`` 이 ``LEASE_HELD_BY_ANOTHER`` 로 거부하며 그때
    FAILED 로 수렴한다. 중간에 끊으면 이미 제출한 부분 결과와 상태가 어긋난다.

    ## context manager 가 아닌 이유

    갱신 구간이 기존 ``try/except/finally`` 와 정확히 같아서, ``with`` 로
    감싸면 계산 본문 전체를 한 단 더 들여쓰게 된다 — 그 재들여쓰기가 diff 를
    실제 변경보다 크게 만든다. ``start()``/``stop()`` 을 그 ``try``/``finally``
    에 그대로 얹는다.
    """

    def __init__(
        self,
        renew: Callable[[], None],
        label: str,
        *,
        interval_seconds: float,
        now_message: Callable[[str], None],
        thread_name_prefix: str = "lease",
    ) -> None:
        self._renew = renew
        self._label = label
        self._interval_seconds = interval_seconds
        self._now_message = now_message
        self._thread_name_prefix = thread_name_prefix
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _beat(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            try:
                self._renew()
            except Exception as exc:  # noqa: BLE001 -- 클래스 docstring: 갱신 실패로 계산을 죽이지 않는다
                self._now_message(f"[{self._label}] lease 갱신 실패(계산은 계속) — {exc}")

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._beat,
            name=f"{self._thread_name_prefix}-{self._label}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            # 갱신 한 번이 왕복 중일 수 있다 — 그 왕복만 기다린다(무한 대기 금지).
            self._thread.join(timeout=self._interval_seconds)


def _change_detection_ready(comparison_input: ComparisonInput) -> bool:
    return (
        comparison_input.point_cloud_baseline is not None
        and comparison_input.point_cloud_baseline_url is not None
        and comparison_input.point_cloud_current is not None
        and comparison_input.point_cloud_current_url is not None
    )


def _volume_change_ready(comparison_input: ComparisonInput) -> bool:
    return (
        comparison_input.dsm_baseline is not None
        and comparison_input.dsm_baseline_url is not None
        and comparison_input.dsm_current is not None
        and comparison_input.dsm_current_url is not None
        and bool(comparison_input.zones)
        and comparison_input.zone_crs is not None
    )


def _resolve_vertical_datum(comparison_input: ComparisonInput) -> str:
    """이 체적 비교 결과가 **어느 수직기준의 높이차**인가 — 리포트에 실을 값.

    산출물이 스스로 선언한 값이 정본이다. 둘 다 선언돼 있으면 계열 일치를
    :func:`assert_comparable_vertical` 로 판정한 뒤 그 datum 을 쓴다.

    ## 미상(None)은 실패가 아니라 레거시 경로다

    수직기준이 기록되기 전에 등록된 산출물이 실재한다. 그 비교를 소급해서
    거부하면 이미 나온 M1/M2 결과를 재현할 수 없게 된다 — 둘 중 하나라도
    ``None`` 이면 예전과 **정확히 같은 값**(:data:`_LEGACY_VERTICAL_DATUM`)을
    쓰고 경고를 남긴다. 값이 바뀌지 않으므로 기존 리포트와 새 리포트가
    갈라지지 않는다.

    (설계면 대비 비교는 반대로 fail-closed 다 — 그쪽은 선언된 기준이 없으면
    아예 숫자를 내지 않는다. 여기서 관대한 이유는 두 입력이 **같은
    파이프라인이 만든 같은 종류의 산출물**이라 레거시 대체값이 실제로 맞기
    때문이고, 설계면은 외부에서 들어와 그 전제가 성립하지 않기 때문이다.)

    ## 계열이 같아도 datum 이 다르면 숫자를 내지 않는다

    ``VolumeChangeReport.verticalDatum`` 은 값 하나다. 두 입력의 datum 이
    실제로 다르면(예: ``ellipsoidal`` vs ``ellipsoidal_native``) 어느 쪽을
    적어도 그 리포트는 절반은 거짓이 된다 — 한쪽을 골라 적는 대신 실패한다.
    epoch DSM 두 장은 같은 재구성 파이프라인에서 나오므로 이 경우는 정상
    운용에서 발생하지 않는다: 발생했다면 전제가 깨진 것이고, 그때 조용히
    한쪽을 고르는 것이 가장 위험하다.
    """
    baseline = comparison_input.dsm_baseline_vertical_reference
    current = comparison_input.dsm_current_vertical_reference
    if baseline is None or current is None:
        logger.warning(
            "수직기준 미기록 산출물 — 레거시 상수로 대체: requestId=%s, datum=%s",
            comparison_input.request_id,
            _LEGACY_VERTICAL_DATUM,
        )
        return _LEGACY_VERTICAL_DATUM
    # 계열이 다르면 VerticalDatumIncompatibleError — 아래 except 가 FAILED 로
    # 수렴시킨다(이 모듈의 "실패는 전부 FAILED 로 수렴한다" 원칙).
    assert_comparable_vertical(baseline, current)
    if baseline.datum is not current.datum:
        raise VolumeChangeRunError(
            "두 산출물의 수직기준이 서로 다르다 — 하나의 verticalDatum 으로 적을 수 "
            f"없다: baseline={baseline.datum.value}, current={current.datum.value}"
        )
    return baseline.datum.value


def run_comparison_request(
    request_id: str,
    *,
    core: CoreClient,
    work_dir: Path,
    http_client: httpx.Client | None = None,
    now_message: Callable[[str], None] = logger.info,
    heartbeat_interval_seconds: float = _HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    """비교 요청 하나를 lease 취득부터 ``SUCCEEDED``/``FAILED`` 까지 끝까지 돈다.

    실패 시 예외를 던진다(``FAILED`` 보고는 시도하되 삼키지 않는다) — 호출자
    (데몬 루프)가 재시도·알림을 정할 수 있게 원인을 그대로 넘긴다.

    계산이 도는 동안 lease 는 ``heartbeat_interval_seconds`` 마다 갱신된다
    (``_lease_heartbeat``) — 자료가 크면 계산이 lease TTL(15분)을 넘길 수 있고,
    그때 갱신이 없으면 다른 워커가 같은 요청을 집어가 중복 계산이 벌어지고
    이쪽의 최종 전이는 ``LEASE_HELD_BY_ANOTHER`` 로 거부돼 **성공한 계산이
    FAILED 로 보고된다**.
    """
    fetch = http_client
    own_client = http_client is None
    now_message(f"[{request_id}] lease 취득")
    core.acquire_comparison_lease(request_id)
    comparison_input = core.get_comparison_input(request_id)

    if comparison_input.status == "QUEUED":
        core.transition_comparison(request_id, "RUNNING")
        now_message(f"[{request_id}] RUNNING")

    # lease 갱신은 여기서부터다 — 위(입력 조회·RUNNING 전이)는 왕복 몇 번이라
    # TTL 을 위협하지 않고, 아래가 몇 분~수십 분짜리다. 정지는 finally 에서 한다.
    heartbeat: LeaseHeartbeat | None = None
    heartbeat_started = False
    try:
        if fetch is None:
            fetch = httpx.Client(
                timeout=httpx.Timeout(connect=10.0, read=120.0, write=600.0, pool=10.0)
            )
        heartbeat = LeaseHeartbeat(
            lambda: core.acquire_comparison_lease(request_id),
            request_id,
            interval_seconds=heartbeat_interval_seconds,
            now_message=now_message,
            thread_name_prefix="cmp-lease",
        )
        heartbeat.start()
        heartbeat_started = True
        # 실행 소유권(RUNNING)을 확립한 뒤부터의 파일 I/O는 모두 아래 except로
        # 수렴한다. mkdir을 try 밖에 두면 디스크 오류 하나로 요청이 영구 RUNNING이다.
        work_dir.mkdir(parents=True, exist_ok=True)
        computed_at = datetime.now(UTC)
        summaries: list[str] = []

        if _change_detection_ready(comparison_input):
            assert comparison_input.point_cloud_baseline is not None  # noqa: S101
            assert comparison_input.point_cloud_baseline_url is not None  # noqa: S101
            assert comparison_input.point_cloud_current is not None  # noqa: S101
            assert comparison_input.point_cloud_current_url is not None  # noqa: S101
            try:
                cd_result = compute_and_submit_change_detection(
                    sink=core,
                    mission_id=comparison_input.mission_id,
                    change_detection_id=request_id,
                    baseline=comparison_input.point_cloud_baseline,
                    baseline_download_url=comparison_input.point_cloud_baseline_url,
                    current=comparison_input.point_cloud_current,
                    current_download_url=comparison_input.point_cloud_current_url,
                    computed_at=computed_at,
                    http_client=fetch,
                    # 함수 기본값이 아니라 **이 요청의 스냅샷**을 쓴다 — 그래야
                    # 원장에 적힌 기준값이 실제로 쓴 값이 된다(모듈 docstring).
                    distance_threshold_m=comparison_input.policy.distance_threshold_m,
                    work_dir=work_dir,
                )
                summaries.append(
                    f"변화탐지 후보 {cd_result.candidate_count}/{cd_result.point_count}"
                )
            except CoreClientError as exc:
                if exc.verdict != "DUPLICATE_RESULT_ID":
                    raise
                # changeDetectionId 는 이 요청(requestId)만 만들 수 있는 결정적 값이다
                # — 이 id 로 DUPLICATE 가 나올 수 있는 유일한 경우는 이전 시도(재시작·
                # 부분실패 후 재시도)가 이미 성공 제출한 것뿐이다. 유일하게 달라질 수
                # 있는 필드는 computed_at(재계산 시각)이고 계산 결과(과학)는 입력이
                # 불변이라 항상 같다 — 안전하게 "이미 됐다"로 넘어간다.
                now_message(f"[{request_id}] 변화탐지 이미 기록됨(재시도, 안전) — {exc}")
                summaries.append("변화탐지 이미 기록됨(재시도)")

        if _volume_change_ready(comparison_input):
            assert comparison_input.dsm_baseline is not None  # noqa: S101
            assert comparison_input.dsm_baseline_url is not None  # noqa: S101
            assert comparison_input.dsm_current is not None  # noqa: S101
            assert comparison_input.dsm_current_url is not None  # noqa: S101
            assert comparison_input.zones is not None  # noqa: S101
            assert comparison_input.zone_crs is not None  # noqa: S101
            try:
                vol_report = compute_and_submit(
                    sink=core,
                    mission_id=comparison_input.mission_id,
                    volume_change_id=request_id,
                    baseline=ArtifactSource(
                        ref=comparison_input.dsm_baseline,
                        download_url=comparison_input.dsm_baseline_url,
                        # **검사점 잔차만** 흘린다(INV-024). accuracy.rmse 는 GCP
                        # 피팅 잔차라 절대정확도가 아니고, 그걸 여기 꽂으면
                        # "검증 없는 수치가 진짜 오차한계처럼 실리는" 위반이
                        # 그대로 재도입된다. 이 자리는 예전에 늘 None 이었고,
                        # 그래서 uncertaintyM3 계산 경로가 존재하면서도 한 번도
                        # 실행된 적이 없었다(2026-08-18 배선).
                        rmse_m=comparison_input.dsm_baseline_checkpoint_rmse_m,
                    ),
                    current=ArtifactSource(
                        ref=comparison_input.dsm_current,
                        download_url=comparison_input.dsm_current_url,
                        rmse_m=comparison_input.dsm_current_checkpoint_rmse_m,
                    ),
                    zones=comparison_input.zones,
                    zone_crs=comparison_input.zone_crs,
                    vertical_datum=_resolve_vertical_datum(comparison_input),
                    computed_at=computed_at,
                    http_client=fetch,
                    # 위 변화탐지와 같은 이유 — 스냅샷된 기준값으로 잰다.
                    threshold_m=comparison_input.policy.volume_threshold_m,
                    work_dir=work_dir,
                )
                summaries.append(f"체적 순변화 {vol_report.total_net_m3:.2f}m³")
            except CoreClientError as exc:
                if exc.verdict != "DUPLICATE_REPORT_ID":
                    raise
                # volumeChangeId 도 changeDetectionId 와 같은 이유로 이 요청만 만들 수
                # 있는 결정적 값이다 — 위 주석과 동일 근거.
                now_message(f"[{request_id}] 체적 리포트 이미 기록됨(재시도, 안전) — {exc}")
                summaries.append("체적 리포트 이미 기록됨(재시도)")

        if not summaries:
            # 생성 시점엔 변화탐지·체적 중 하나가 준비돼 있었으니(모듈 docstring
            # "어느 쪽도 시도하지 않는 요청은 여기 도달하지 않는다" — Core 의
            # NOTHING_TO_COMPARE 게이트) 여기 온 요청은 원래 계산할 거리가 있었다.
            # 그런데 위 두 게이트를 모두 못 지났다는 건 입력이 생성 이후 사라졌다는
            # 뜻이다(예: 산출물 회수, presign 대상 소실). 이걸 그냥 SUCCEEDED 로
            # 넘기면 "계산 안 했는데 성공"이 되어 화면엔 "완료"가 뜨고 결과는
            # 없다(INV-040 — 겉만 성공인 상태 금지). 아무것도 계산 못 했으면
            # 실패로 보고한다 — 아래 except 가 FAILED 전이 + 재던지기를 맡는다.
            raise ChangeDetectionRunError(
                "비교할 자료를 받지 못했습니다 — 점군/높이자료 확인 필요"
            )

        detail = "; ".join(summaries)
        core.transition_comparison(request_id, "SUCCEEDED", detail=detail)
        now_message(f"[{request_id}] SUCCEEDED — {detail}")
    except (
        ChangeDetectionRunError,
        VolumeChangeRunError,
        # INV-020 좌표계 검증(run_change_detection.py/dsm_diff.py)이 raise 하는
        # 그대로의 예외 — ChangeDetectionRunError/VolumeChangeRunError 로 감싸지
        # 않는다(그쪽 모듈들의 기존 관례와 동형). 여기서 잡지 않으면 "실패는 전부
        # FAILED 로 수렴한다"는 이 모듈의 원칙이 CRS 불일치에서만 깨져 워커가
        # 그대로 죽는다.
        CrsMismatchError,
        UnsupportedCrsError,
        # 수직축 판정(_resolve_vertical_datum)의 거부 — 위 CRS 예외들과 같은
        # 자리·같은 이유다(수평축이 아니라 수직축이라는 것만 다르다). 잡지
        # 않으면 워커가 그대로 죽고 요청은 RUNNING 에 남는다.
        VerticalDatumIncompatibleError,
        httpx.HTTPError,
        CoreClientError,
        # mkdir/download/write/upload의 로컬 파일 I/O 실패도 RUNNING 이후 실패다.
        # 이를 놓치면 프로세스만 죽고 Core 요청은 RUNNING에 고착된다(INV-040).
        OSError,
    ) as exc:
        detail = str(exc)[:500]
        now_message(f"[{request_id}] 실패 — FAILED 보고 시도: {detail}")
        try:
            core.transition_comparison(request_id, "FAILED", detail=detail)
        except CoreClientError as report_exc:
            now_message(f"[{request_id}] FAILED 보고도 실패(원인은 유지): {report_exc}")
        raise ComparisonWorkerRunError(f"[{request_id}] 실행 실패: {exc}") from exc
    finally:
        # 최종 전이(SUCCEEDED/FAILED)까지 lease 를 쥔 채로 두고 그 뒤에 멈춘다 —
        # 전이 직전에 멈추면 그 사이에 TTL 이 지나 전이가 거부될 수 있다.
        if heartbeat_started and heartbeat is not None:
            heartbeat.stop()
        if own_client and fetch is not None:
            fetch.close()


__all__ = ["ComparisonWorkerRunError", "LeaseHeartbeat", "run_comparison_request"]
