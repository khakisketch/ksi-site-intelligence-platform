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

이 문장은 예외 **종류**를 가리지 않는다 — ``OdmError``/``httpx.HTTPError``/
``CoreClientError`` 셋으로 좁혀 잡던 예전 코드는 이 문장을 어겼다. 디스크가
찼을 때(``OSError``) 나는 예외는 이 셋 어디에도 안 걸려 이 함수를 그냥
빠져나갔고, 그러면 :class:`WorkerRunError` 로 감싸이지 않아 ``runner.py`` 의
``_try_candidates`` 가 "이번 라운드는 아무 일도 안 했다"로 오판해 **같은
작업을 다음 라운드에 그대로 다시 시도한다** — lease 는 여전히 이 워커가
쥐고 있고 job 은 여전히 ``RUNNING`` 이므로 Core 에 FAILED 로 보고되지 않고
영원히 되돈다(2026-08-13 프로젝트 두뇌 재감사 확정 발견). 그래서 여기서는
``Exception`` 전체를 잡는다 — ``KeyboardInterrupt``/``SystemExit`` 은
``BaseException`` 이라 이 그물에 안 걸리므로 프로세스 종료 신호는 그대로
전파된다.

## 작업 디렉터리는 이 작업이 끝나면 비운다

``work_dir`` 는 재구성·비교·설계면 검증·설계 대비 잔량 네 종류 작업이 전부
공유한다(프로세스당 동시에 하나만 돈다 — 아래 참조). 이 함수가 그 자리에
받은 사진·완주 아카이브를 성공이든 실패든 끝에 지우지 않으면, 재시도마다
(그리고 다음 작업마다) 새 사진이 쌓이기만 해서 영속 볼륨이 무한히 찬다
(같은 재감사 발견 — work_dir 정리 없음). 성공 시에도 지운다 — 산출물은
이미 Core/스토리지에 등록됐으므로 로컬 사본은 더 필요 없다.

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
import posixpath
import time
import zipfile
from collections.abc import Callable
from pathlib import Path

import httpx
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)

from ksi_processing_controller.capture_time import extract_capture_time
from ksi_processing_controller.core_client import (
    ArtifactSubmission,
    CoreClient,
    CoreClientError,
    MeasuredImage,
)
from ksi_processing_controller.gsd import resolve_gsd
from ksi_processing_controller.measure import measure_image
from ksi_processing_controller.odm import (
    GROUND_CONTROL_FILENAME,
    GroundControlFile,
    MaskImage,
    NodeOdmClient,
    OdmError,
    SourceImage,
    assert_engine_matches,
    assert_ground_control_matches,
    iter_archive_entry_bytes,
    plan_artifacts,
    run_to_completion,
)
from ksi_processing_controller.odm_masking import ImageDetector, build_mask_for_photo

logger = logging.getLogger(__name__)


class WorkerRunError(RuntimeError):
    """작업 실행이 실패했다 — Core 에는 이미 FAILED 로 보고를 시도했다."""


# 산출물 업로드의 Content-Type. 종류별로 나누지 않는다 — 이 값은 스토리지가
# 바이트를 되돌려줄 때 붙이는 꼬리표일 뿐이고, 산출물의 실제 형식은 계약의
# ``format`` 필드가 말한다. 여기서 kind→MIME 표를 만들면 두 곳이 서로 다른
# 진실을 말할 수 있다.
_ARTIFACT_CONTENT_TYPE = "application/octet-stream"

# 이 파이프라인이 내놓는 높이가 어느 기준의 높이인가 — **파이프라인이 자기
# 동작을 근거로 선언한다.**
#
# 왜 여기인가: 이 사실을 아는 곳은 여기뿐이다. Core 는 산출물 바이트를 읽지
# 않고, 비교 워커는 두 산출물을 받아 빼기만 한다. 그동안 이 값은 비교 워커의
# 하드코딩 상수(``comparison_worker._LEGACY_VERTICAL_DATUM``)로 살아 있었는데, 그건
# 산출물의 사실이 아니라 **소비자의 가정**이었다 — 같은 파이프라인끼리 비교하는
# 동안은 틀려도 상쇄돼 드러나지 않지만, 설계면처럼 바깥에서 들어온 높이와
# 비교하는 순간 지오이드고(한국 20~30m)가 조용히 섞인다.
#
# 왜 ``ELLIPSOIDAL_NATIVE`` 인가: ODM 은 RTK 가 준 타원체고를 그대로 흘려보낸다.
# 우리가 아는 것은 "이 높이가 타원체고임을 측정했다"가 아니라 **"변환을 하지
# 않았다"** 이고, 그 상태를 가리키는 값이 정확히 이것이다(지오이드 격자가
# 확보되면 이 값이 남아 있는 산출물이 곧 재처리 대상 목록이 된다).
# 그래서 source 도 ``PIPELINE_DECLARED`` 다 — 측정이 아니라 귀속이다.
_ODM_VERTICAL_REFERENCE = VerticalReference(
    datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
    basis=(
        "ODM 이 RTK 타원체고를 변환 없이 그대로 출력한다 — 지오이드 격자 미확보로 "
        "정표고 변환을 수행하지 않았다"
    ),
    source=VerticalReferenceSource.PIPELINE_DECLARED,
)


def _download(client: httpx.Client, url: str, dest: Path) -> None:
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_bytes(1024 * 1024):
                handle.write(chunk)


def _cleanup_work_files(
    job_id: str, paths: list[Path], now_message: Callable[[str], None]
) -> None:
    """이 작업이 ``work_dir`` 에 남긴 파일을 지운다 — 성공이든 실패든.

    지우다 나는 오류는 로그만 남기고 삼킨다. 정리 실패로 이 작업의 진짜
    결과(``SUCCEEDED``/``FAILED``)가 가려지면 안 된다 — 원래 예외를 삼키지
    않는다는 이 모듈의 규율과 같은 이유다.
    """
    for path in paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            now_message(f"[{job_id}] 작업 파일 정리 실패(무시하고 계속): {path} — {exc}")


def _upload(client: httpx.Client, url: str, archive_path: Path, entry: str) -> None:
    """아카이브 안 파일 하나를 presigned PUT 으로 흘려보낸다.

    **바이트가 Core 를 통과하지 않는다** — 포인트 클라우드는 GB 단위라 Core 를
    거치면 그 프로세스 메모리에 전량이 올라간다. 워커가 스토리지에 직접 쓴다.

    :func:`iter_archive_entry_bytes` 는 :func:`digest_archive_entry` 와 같은
    읽기 관용구라, 여기서 올라가는 바이트가 곧 등록될 digest 를 만든 바이트다.

    **Content-Length 를 명시한다 — 청크 전송으로 두면 안 된다.** httpx 는
    스트리밍 content 에 길이를 못 정하면 ``Transfer-Encoding: chunked`` 를 쓰는데,
    S3 presigned PUT URL 은 SigV4 서명이 고정 길이 payload 를 전제라 청크 인코딩을
    받아주지 않는다(``411 Length Required`` — 실측: MinIO 대상 실기동에서 확인,
    가짜 스토리지 계약 테스트는 이 차이를 볼 수 없다). zip 엔트리의
    ``file_size``(압축 해제 크기)가 실제로 흘려보낼 바이트 수와 정확히 같다.
    """
    with zipfile.ZipFile(archive_path) as archive:
        try:
            content_length = archive.getinfo(entry).file_size
        except KeyError as exc:
            raise OdmError(f"아카이브에 {entry} 가 없다") from exc
    response = client.put(
        url,
        content=iter_archive_entry_bytes(archive_path, entry),
        headers={
            "Content-Type": _ARTIFACT_CONTENT_TYPE,
            "Content-Length": str(content_length),
        },
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
    dynamic_object_detector: ImageDetector | None = None,
) -> None:
    """작업 하나를 lease 취득부터 ``SUCCEEDED``/``FAILED`` 까지 끝까지 돈다.

    실패 시 예외를 던진다(``FAILED`` 보고는 시도하되 삼키지 않는다) — 호출자
    (데몬 루프)가 재시도·알림을 정할 수 있게 원인을 그대로 넘긴다.

    ``gsd_by_artifact`` 를 생략하면(``None``) 완주한 아카이브에서
    :func:`~ksi_processing_controller.gsd.resolve_gsd` 로 **자동으로 읽는다** —
    래스터 산출물(정사영상·DSM·DTM)마다 값을 손으로 채워 넘겨야 했던 지금까지의
    호출부(테스트) 관행을 프로덕션 경로에서는 없앤다. 값을 명시적으로 넘기면
    (테스트가 그렇게 한다) 그 값을 그대로 쓰고 자동 해석을 건너뛴다 — 자동
    해석도 결국 못 읽으면 건너뛰므로(``gsd.py`` 모듈 docstring), 명시값과 자동값을
    섞어서 "일부는 지정, 나머지는 자동"으로 두지 않는다: 하나라도 명시하면
    그 dict 가 전체를 대표한다.

    ``dynamic_object_detector`` 를 생략하면(``None``, 기본값) 마스킹 없이
    지금까지와 동일하게 동작한다 — 이 매개변수는 PRD §15.2 ④(동적 객체
    마스킹)의 선택적 활성화 지점이다. 값을 주면(예: 실제 로드된
    ``DFineDetector``) 실측 단계(4번)에서 이미 로컬에 받아둔 사진마다 탐지를
    돌려 마스크를 만들고, ODM 제출(5번)에 함께 싣는다(``odm_masking`` 모듈
    docstring — 파일명 규약·폴라리티는 실물로 검증됐다). 사진 1장의 탐지
    실패는 그 사진의 마스크만 건너뛰고 작업 전체를 막지 않는다 — 마스킹은
    보조 개선이지 재구성 성공의 필요조건이 아니다.
    """
    fetch = http_client or httpx.Client(
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=600.0, pool=10.0)
    )
    own_client = http_client is None
    work_dir.mkdir(parents=True, exist_ok=True)

    now_message(f"[{job_id}] lease 취득")
    core.acquire_lease(job_id)
    job_input = core.get_input(job_id)

    # 이 작업이 work_dir 에 실제로 만든 파일 — 성공이든 실패든 finally 에서
    # 지운다. 다운로드를 시도하기 *전에* 경로를 넣는다 — 중간에 끊겨도(디스크
    # 가득·네트워크 오류) 부분 파일이 남을 수 있고, 그것도 청소 대상이다.
    downloaded_paths: list[Path] = []
    try:
        if job_input.site_crs is None:
            # 현장 원장 이상 상태 — 여기서 계속하면 crs 없는 산출물을 만들게 된다.
            # try 안에서 던져야 아래 except 가 FAILED 를 Core 에 보고한다 —
            # try 밖에서 던지면(과거 버그) 이 예외가 FAILED 전이 없이 그냥
            # 새어나가 작업이 QUEUED 에 갇히고, list_pending 이 오래된 순으로
            # 돌려주는 한 이 작업이 매 스캔마다 선두를 막아 다른 작업도 전부
            # 멈춘다.
            raise WorkerRunError(f"[{job_id}] siteCrs 가 없다 — 현장 원장 이상 상태")

        if job_input.status == "QUEUED":
            core.transition(job_id, "RUNNING")
            now_message(f"[{job_id}] RUNNING")

        # ── 4. 실측 + 보고(+ 동적 객체 탐지 — 이미 로컬에 받은 그 사진으로) ──
        measurements: list[MeasuredImage] = []
        masks: list[MaskImage] = []
        for media in job_input.media:
            local_path = work_dir / media.media_id
            downloaded_paths.append(local_path)
            _download(fetch, media.download_url, local_path)
            sha256, size, width, height = measure_image(local_path)
            capture_time = extract_capture_time(local_path)
            measurements.append(
                MeasuredImage(
                    media_id=media.media_id, sha256=sha256,
                    size_bytes=size, width=width, height=height,
                    capture_time=capture_time,
                )
            )
            if dynamic_object_detector is not None:
                try:
                    mask = build_mask_for_photo(
                        dynamic_object_detector, local_path, filename=media.media_id
                    )
                except (OSError, ValueError, RuntimeError) as exc:
                    # 사진 1장의 탐지 실패가 재구성 자체를 막지 않는다(docstring) —
                    # measure_image 와 달리 이 실패는 Core 보고 대상이 아니다
                    # (마스킹은 신고값 검증이 아니라 보조 개선이다).
                    now_message(
                        f"[{job_id}] {media.media_id} 동적 객체 탐지 실패 — "
                        f"마스크 없이 계속: {exc}"
                    )
                    mask = None
                if mask is not None:
                    masks.append(mask)
        now_message(f"[{job_id}] 실측 {len(measurements)}장 완료 — 대조 보고")
        if dynamic_object_detector is not None:
            now_message(f"[{job_id}] 동적 객체 마스크 {len(masks)}장 생성")
        core.verify_source_media(job_input.mission_id, measurements)

        # ── 4-b. 기준점 파일 — 받아서 **선언과 내용을 대조한 뒤** 넘긴다 ──
        #
        # Core 는 바이트를 안 읽으므로(ADR-KSI-010 §1) 원장의 crs 는 신고값이다.
        # 그 신고가 파일 첫 줄과 다르면 엔진은 파일을 믿고 다른 좌표계로 성과를
        # 내고, 원장에는 신고값이 남는다 — 두 값이 갈린 채로 비교까지 흘러가면
        # 그 어긋남은 화면 어디에도 안 보인다. 여기서 막는다.
        ground_control: GroundControlFile | None = None
        if job_input.ground_control is not None:
            gc_path = work_dir / GROUND_CONTROL_FILENAME
            downloaded_paths.append(gc_path)
            _download(fetch, job_input.ground_control.download_url, gc_path)
            content = gc_path.read_bytes()
            declared = job_input.ground_control.crs
            assert_ground_control_matches(content, declared_crs=declared)
            ground_control = GroundControlFile(crs=declared, content=content)
            now_message(f"[{job_id}] 기준점 파일 확인 — 좌표계 {declared}")

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
            masks=masks,
            ground_control=ground_control,
        )
        now_message(f"[{job_id}] ODM 완주 uuid={uuid}")

        # ── 6. 산출물 계보 등록 ─────────────────────────────────────────
        archive_path = work_dir / "all.zip"
        downloaded_paths.append(archive_path)
        odm.download_archive(uuid, archive_path)
        # None 이면(프로덕션 기본 경로) 완주한 아카이브 자신에서 읽는다 — 지어낸
        # 값이 아니라 등록될 그 파일의 실제 픽셀 크기다(gsd.py 모듈 docstring).
        # 명시적으로 넘겨받았으면(테스트) 그 값을 그대로 쓴다.
        resolved_gsd = (
            gsd_by_artifact if gsd_by_artifact is not None else resolve_gsd(archive_path)
        )
        reports = plan_artifacts(archive_path, crs=job_input.site_crs, gsd_by_artifact=resolved_gsd)
        registered = 0
        for report in reports:
            # ① 자리를 받고 ② 그 자리에 쓰고 ③ 그다음에 등록한다.
            # 순서가 뒤집히면 "등록됐는데 바이트가 없는" 창이 열린다. 산출물이
            # 파일 여러 개(메시+텍스처·재질)면 등록은 한 번, 업로드는 파일
            # 수만큼이다 — 주 파일을 올린 *뒤* 등록해야 "등록됐는데 주 파일이
            # 없는" 창이 없는 것처럼, 부속 파일도 전부 올린 뒤에야 등록한다
            # (mesh-multi-file-artifact-persistence — 이전엔 이 갈래 자체를
            # 등록하지 않고 건너뛰었다).
            target = core.presign_artifact_upload(
                job_id,
                artifact_id=report.artifact_id,
                content_type=_ARTIFACT_CONTENT_TYPE,
            )
            _upload(fetch, target.upload_url, archive_path, report.archive_entry)

            for aux_basename in report.auxiliary_files:
                # 부속 파일은 주 파일과 같은 아카이브 디렉터리에 있다
                # (odm.plan_artifacts 가 그 조건으로 찾은 것들이다) — 그
                # 디렉터리 + basename 으로 아카이브 내부 전체 경로를 되짚는다.
                directory = posixpath.dirname(report.archive_entry)
                aux_archive_entry = posixpath.join(directory, aux_basename)
                aux_target = core.presign_artifact_upload(
                    job_id,
                    artifact_id=report.artifact_id,
                    content_type=_ARTIFACT_CONTENT_TYPE,
                    filename=aux_basename,
                )
                _upload(fetch, aux_target.upload_url, archive_path, aux_archive_entry)

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
                    auxiliary_files=report.auxiliary_files,
                    # 좌표계가 없는 산출물(카메라 포즈·리포트)에는 수직기준을
                    # 달지 않는다 — crs 를 null 로 두는 것과 같은 이유로, 높이가
                    # 그 산출물 자체의 속성이 아닌 곳에 기준만 선언하면 소비자가
                    # 없는 것을 있다고 읽는다. 공간 산출물에는 전부 붙는다.
                    vertical_reference=(
                        _ODM_VERTICAL_REFERENCE if report.crs is not None else None
                    ),
                ),
            )
            registered += 1
        now_message(f"[{job_id}] 산출물 {registered}건 등록(바이트 포함)")

        # ── 7. 성공 보고 ────────────────────────────────────────────────
        # 계획한 수(``len(reports)``)가 아니라 **실제로 등록한 수**를 보고한다 —
        # 건너뛴 산출물이 있는데 계획 수를 적으면 원장이 없는 것을 있다고 말한다.
        core.transition(job_id, "SUCCEEDED", detail=f"산출물 {registered}건")
        now_message(f"[{job_id}] SUCCEEDED")
    except Exception as exc:  # noqa: BLE001 -- 모듈 docstring: 4~6 단계는 종류를 안 가린다.
        # verify 거부·산출물 거부처럼 **Core 가 스스로 판정을 거부한 경우**도,
        # OSError(디스크 가득 등)처럼 이 함수 바깥의 자원 문제도 전부 여기서
        # 잡는다 — 좁게 잡으면 그 예외가 WorkerRunError 로 감싸이지 않고 그냥
        # 새어나가, 호출자(runner.py)가 "이번 라운드는 아무 일도 안 했다"로
        # 오판해 FAILED 보고 없이 같은 작업을 영원히 재시도한다(모듈 docstring
        # "실패는 전부 FAILED 로 수렴한다" 참조 — 2026-08-13 확정 발견).
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
        _cleanup_work_files(job_id, downloaded_paths, now_message)
        if own_client:
            fetch.close()


__all__ = ["WorkerRunError", "run_job"]
