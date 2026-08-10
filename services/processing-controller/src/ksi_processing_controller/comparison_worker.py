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

from ksi_processing_controller.core_client import ComparisonInput, CoreClient, CoreClientError

logger = logging.getLogger(__name__)

# M1 의 유일한 엔진(ODM)은 구조화된 지오이드 변환을 내지 않는다 — 재구성 워커가
# 등록하는 DSM 이 항상 이 수직기준이다(run_volume_change.py 모듈 docstring,
# 기존 test_volume_change_end_to_end.py 가 이미 이 문자열 리터럴을 쓰는 것과
# 동일 관용구 — ksi-geo-spatial 을 새 의존으로 끌어오지 않는다).
_VERTICAL_DATUM = "ellipsoidal_native"


class ComparisonWorkerRunError(RuntimeError):
    """비교 요청 실행이 실패했다 — Core 에는 이미 FAILED 로 보고를 시도했다."""


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


def run_comparison_request(
    request_id: str,
    *,
    core: CoreClient,
    work_dir: Path,
    http_client: httpx.Client | None = None,
    now_message: Callable[[str], None] = logger.info,
) -> None:
    """비교 요청 하나를 lease 취득부터 ``SUCCEEDED``/``FAILED`` 까지 끝까지 돈다.

    실패 시 예외를 던진다(``FAILED`` 보고는 시도하되 삼키지 않는다) — 호출자
    (데몬 루프)가 재시도·알림을 정할 수 있게 원인을 그대로 넘긴다.
    """
    fetch = http_client or httpx.Client(
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=600.0, pool=10.0)
    )
    own_client = http_client is None
    work_dir.mkdir(parents=True, exist_ok=True)

    now_message(f"[{request_id}] lease 취득")
    core.acquire_comparison_lease(request_id)
    comparison_input = core.get_comparison_input(request_id)

    if comparison_input.status == "QUEUED":
        core.transition_comparison(request_id, "RUNNING")
        now_message(f"[{request_id}] RUNNING")

    try:
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
                    ),
                    current=ArtifactSource(
                        ref=comparison_input.dsm_current,
                        download_url=comparison_input.dsm_current_url,
                    ),
                    zones=comparison_input.zones,
                    zone_crs=comparison_input.zone_crs,
                    vertical_datum=_VERTICAL_DATUM,
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
    except (ChangeDetectionRunError, VolumeChangeRunError, httpx.HTTPError, CoreClientError) as exc:
        detail = str(exc)[:500]
        now_message(f"[{request_id}] 실패 — FAILED 보고 시도: {detail}")
        try:
            core.transition_comparison(request_id, "FAILED", detail=detail)
        except CoreClientError as report_exc:
            now_message(f"[{request_id}] FAILED 보고도 실패(원인은 유지): {report_exc}")
        raise ComparisonWorkerRunError(f"[{request_id}] 실행 실패: {exc}") from exc
    finally:
        if own_client:
            fetch.close()


__all__ = ["ComparisonWorkerRunError", "run_comparison_request"]
