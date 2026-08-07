"""워커 오케스트레이션 — 세 경계(Core·NodeODM·측정)를 하나의 작업 실행으로 잇는다.

이 모듈이 생기기 전까지는 세 조각이 각자 옳았다: Core 표면(lease·입력수신·
검증·산출물등록·전이)도, ODM 어댑터도, 실측도 개별적으로 실기동 검증까지
마쳤다. 하지만 **그 셋을 순서대로 부르는 코드가 없었다** — 파이프라인은 부품
상태였다. :func:`run_job` 가 그 순서를 고정한다.

## 순서가 게이트의 순서다

1. lease 를 잡는다(다른 워커가 같은 작업을 돌리지 못하게).
2. 입력을 받는다 — 사양과 원본 다운로드 URL, **신고값은 없다**.
3. ``QUEUED`` 면 ``RUNNING`` 으로 전이한다.
4. 원본을 받아 실측하고(sha256·해상도) Core 에 보고한다 — 이게 통과해야
   나중에 ``SUCCEEDED`` 가 열린다.
5. 엔진 신원을 대조하고 NodeODM 에 제출·완주까지 폴링한다. 폴링 콜백에서
   lease 를 갱신한다(heartbeat) — ODM 은 몇 시간이 걸리고 lease 는 15분이다.
6. 완주한 아카이브에서 산출물 계보를 뽑아 **등록 순서대로** Core 에 올린다.
7. ``SUCCEEDED`` 로 전이한다 — 이 시점에 산출물(INV-051)과 입력 검증이 둘 다
   Core 원장에 있으므로 게이트를 통과한다.

## 실패는 전부 ``FAILED`` 로 수렴한다

4~6 어느 단계에서 예외가 나든 ``FAILED`` 전이를 시도하고 원래 예외를 다시
던진다. **전이 자체가 실패해도**(lease 만료 등) 원래 예외를 삼키지 않는다 —
호출자가 "무엇이 실제로 문제였는지"를 알아야 하고, 전이 실패는 부수 정보다.

## 이 모듈이 하지 않는 것

- **큐에서 작업을 꺼내오지 않는다.** jobId 를 인자로 받는다(Core 에 pull 표면이
  없다 — ``ksi_core.processing_jobs`` 모듈 docstring).
- **원본을 한 번만 받지 않는다.** 실측을 위해 워커가 한 번 받고, NodeODM 제출을
  위해 :class:`~ksi_processing_controller.http_node_odm.HttpNodeOdmClient` 가
  같은 URL 에서 다시 받는다. presigned URL 을 재사용해 한 번만 받는 경로는
  로컬 파일 서버 같은 중개가 필요해 복잡도가 늘고, 스토리지와 워커가 보통
  같은 인프라에 있어 재전송 비용이 낮다고 판단해 지금은 두 번을 받아들였다.
- **동시에 여러 작업을 돌리지 않는다.** 프로세스 하나가 작업 하나를 끝까지
  돈다. 동시성은 프로세스를 여러 개 띄우는 것으로 얻는다(lease 가 이미 그
  경합을 막는다).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from ksi_processing_controller.core_client import (
    ArtifactSubmission,
    CoreClient,
    CoreClientError,
    MeasuredImage,
)
from ksi_processing_controller.measure import measure_image
from ksi_processing_controller.odm import (
    NodeOdmClient,
    OdmError,
    SourceImage,
    assert_engine_matches,
    iter_archive_entry_bytes,
    plan_artifacts,
    run_to_completion,
)

logger = logging.getLogger(__name__)


class WorkerRunError(RuntimeError):
    """작업 실행이 실패했다 — Core 에는 이미 FAILED 로 보고를 시도했다."""


# 산출물 업로드의 Content-Type. 종류별로 나누지 않는다 — 이 값은 스토리지가
# 바이트를 되돌려줄 때 붙이는 꼬리표일 뿐이고, 산출물의 실제 형식은 계약의
# ``format`` 필드가 말한다. 여기서 kind→MIME 표를 만들면 두 곳이 서로 다른
# 진실을 말할 수 있다.
_ARTIFACT_CONTENT_TYPE = "application/octet-stream"


def _download(client: httpx.Client, url: str, dest: Path) -> None:
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_bytes(1024 * 1024):
                handle.write(chunk)


def _upload(client: httpx.Client, url: str, archive_path: Path, entry: str) -> None:
    """아카이브 안 파일 하나를 presigned PUT 으로 흘려보낸다.

    **바이트가 Core 를 통과하지 않는다** — 포인트 클라우드는 GB 단위라 Core 를
    거치면 그 프로세스 메모리에 전량이 올라간다. 워커가 스토리지에 직접 쓴다.

    :func:`iter_archive_entry_bytes` 는 :func:`digest_archive_entry` 와 같은
    읽기 관용구라, 여기서 올라가는 바이트가 곧 등록될 digest 를 만든 바이트다.
    """
    response = client.put(
        url,
        content=iter_archive_entry_bytes(archive_path, entry),
        headers={"Content-Type": _ARTIFACT_CONTENT_TYPE},
    )
    response.raise_for_status()


def run_job(
    job_id: str,
    *,
    core: CoreClient,
    odm: NodeOdmClient,
    work_dir: Path,
    http_client: httpx.Client | None = None,
    gsd_by_artifact: dict[str, float] | None = None,
    poll_interval_seconds: float = 10.0,
    now_message: Callable[[str], None] = logger.info,
) -> None:
    """작업 하나를 lease 취득부터 ``SUCCEEDED``/``FAILED`` 까지 끝까지 돈다.

    실패 시 예외를 던진다(``FAILED`` 보고는 시도하되 삼키지 않는다) — 호출자
    (데몬 루프)가 재시도·알림을 정할 수 있게 원인을 그대로 넘긴다.
    """
    fetch = http_client or httpx.Client(
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=600.0, pool=10.0)
    )
    own_client = http_client is None
    work_dir.mkdir(parents=True, exist_ok=True)

    now_message(f"[{job_id}] lease 취득")
    core.acquire_lease(job_id)
    job_input = core.get_input(job_id)
    if job_input.site_crs is None:
        # 현장 원장 이상 상태 — 여기서 계속하면 crs 없는 산출물을 만들게 된다.
        raise WorkerRunError(f"[{job_id}] siteCrs 가 없다 — 현장 원장 이상 상태")

    if job_input.status == "QUEUED":
        core.transition(job_id, "RUNNING")
        now_message(f"[{job_id}] RUNNING")

    try:
        # ── 4. 실측 + 보고 ──────────────────────────────────────────────
        measurements: list[MeasuredImage] = []
        for media in job_input.media:
            local_path = work_dir / media.media_id
            _download(fetch, media.download_url, local_path)
            sha256, size, width, height = measure_image(local_path)
            measurements.append(
                MeasuredImage(
                    media_id=media.media_id, sha256=sha256,
                    size_bytes=size, width=width, height=height,
                )
            )
        now_message(f"[{job_id}] 실측 {len(measurements)}장 완료 — 대조 보고")
        core.verify_source_media(job_input.mission_id, measurements)

        # ── 5. 엔진 신원 대조 + 제출 + 완주 대기 ────────────────────────
        assert_engine_matches(odm.info(), expected_version=job_input.engine_version)
        images = [
            SourceImage(media_id=m.media_id, download_url=m.download_url)
            for m in job_input.media
        ]

        def _heartbeat() -> None:
            # ODM 은 몇 시간이 걸리고 lease 는 15분이다 — 폴링마다 갱신한다.
            # **sleep 이 빠지면 안 된다.** run_to_completion 의 poll 콜백은
            # "대기 함수"라고 계약돼 있는데(odm.py docstring), 처음 구현은
            # heartbeat 만 하고 실제로 기다리지 않았다 — 그러면 폴링이 밀리초
            # 단위로 회전해 max_polls(기본 10,000)가 몇 초 만에 소진되고, 3분
            # 걸리는 실제 완주보다 먼저 "행 처리"로 오판해 실패한다. 실물
            # NodeODM 대상 완주 시도에서 실제로 이렇게 터졌다(2026-08-06).
            time.sleep(poll_interval_seconds)
            core.acquire_lease(job_id)

        uuid = run_to_completion(
            odm, images,
            expected_version=job_input.engine_version,
            options=job_input.processing_params,
            poll=_heartbeat,
        )
        now_message(f"[{job_id}] ODM 완주 uuid={uuid}")

        # ── 6. 산출물 계보 등록 ─────────────────────────────────────────
        archive_path = work_dir / "all.zip"
        odm.download_archive(uuid, archive_path)
        reports = plan_artifacts(
            archive_path, crs=job_input.site_crs, gsd_by_artifact=gsd_by_artifact
        )
        registered = 0
        for report in reports:
            if not report.is_single_file:
                # 산출물 하나가 파일 여러 개인 경우(메시+텍스처·재질) 객체 키
                # 하나에 충실히 담을 수 없다 — 대표 파일만 올리면 저장된
                # 바이트와 등록된 digest 가 어긋난다. **그래서 등록도 하지
                # 않는다**: 등록해 두면 "원장에 있는데 바이트가 없는" 산출물이
                # 생기고, 다운로드 표면이 깨진 링크를 발급한다(risk
                # mesh-auxiliary-files-not-persisted).
                now_message(
                    f"[{job_id}] {report.artifact_id} 는 파일 여러 개로 이뤄져 "
                    "객체 키 하나에 담을 수 없다 — 이번 범위에서 건너뛴다"
                )
                continue

            # ① 자리를 받고 ② 그 자리에 쓰고 ③ 그다음에 등록한다.
            # 순서가 뒤집히면 "등록됐는데 바이트가 없는" 창이 열린다.
            target = core.presign_artifact_upload(
                job_id,
                artifact_id=report.artifact_id,
                content_type=_ARTIFACT_CONTENT_TYPE,
            )
            _upload(fetch, target.upload_url, archive_path, report.archive_entry)
            core.register_artifact(
                job_id,
                ArtifactSubmission(
                    artifact_id=report.artifact_id,
                    kind=report.kind,
                    authority=report.authority,
                    derived_from=report.derived_from,
                    digest=report.digest,
                    format=report.fmt,
                    crs=report.crs,
                    gsd=report.gsd,
                ),
            )
            registered += 1
        now_message(f"[{job_id}] 산출물 {registered}건 등록(바이트 포함)")

        # ── 7. 성공 보고 ────────────────────────────────────────────────
        # 계획한 수(``len(reports)``)가 아니라 **실제로 등록한 수**를 보고한다 —
        # 건너뛴 산출물이 있는데 계획 수를 적으면 원장이 없는 것을 있다고 말한다.
        core.transition(job_id, "SUCCEEDED", detail=f"산출물 {registered}건")
        now_message(f"[{job_id}] SUCCEEDED")
    except (OdmError, httpx.HTTPError, CoreClientError) as exc:
        # verify 거부·산출물 거부처럼 **Core 가 스스로 판정을 거부한 경우**도
        # 여기서 잡는다 — 안 잡으면 그 실패가 FAILED 보고 없이 그냥 새어나간다.
        detail = str(exc)[:500]
        now_message(f"[{job_id}] 실패 — FAILED 보고 시도: {detail}")
        try:
            core.transition(job_id, "FAILED", detail=detail)
        except CoreClientError as report_exc:
            # 보고 자체가 실패해도(lease 만료 등) 원래 원인을 가리지 않는다 —
            # 부수 정보로 로그만 남기고 원래 예외를 그대로 올린다(모듈 docstring).
            now_message(f"[{job_id}] FAILED 보고도 실패(원인은 유지): {report_exc}")
        raise WorkerRunError(f"[{job_id}] 실행 실패: {exc}") from exc
    finally:
        if own_client:
            fetch.close()


__all__ = ["WorkerRunError", "run_job"]
