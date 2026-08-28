"""무수정 NodeODM 컨테이너 대상 실기동 계약 (ADR-KSI-012 D1/D2).

``tests/contract/test_odm_adapter.py`` 는 포트를 가짜로 갈아끼운 계약 시험이라
**응답 형태가 실물과 같은지는 증명하지 못한다**. 그 간극에서 실제로 네 가지가
틀려 있었다(2026-08-06, NodeODM 2.2.4 / ODM 3.5.6):

1. ``/info`` 의 ``version``(NodeODM 2.2.4)과 ``engineVersion``(ODM 3.5.6)이 다른
   값인데 전자를 계약의 engineVersion 과 대조하고 있었다.
2. 산출물은 ``all.zip`` 하나로만 나온다 — 개별 asset 다운로드는 NodeODM 에 없다.
3. 에러가 HTTP 200 + ``{"error": ...}`` 로 온다 — 상태 코드로 못 가른다.
4. 중첩 asset 경로는 라우트 자체가 없어 404 HTML 이다.

그리고 완주까지 돌려보니 다섯 번째가 나왔다:

5. ``cameras.json`` 은 카메라 **내부 파라미터**(focal·왜곡계수, 카메라 모델당
   1개)이지 사진별 포즈가 아니다. 실제 포즈는 ``odm_report/shots.geojson``
   (사진 1장당 feature 1개, translation·rotation)이다. 파일 이름만 보고 정한
   매핑이 틀렸고, 아카이브를 열어야만 보였다.

## 두 겹으로 나뉜다

- **엔진 계약**(URL 만 있으면 됨): ``/info``·에러 봉투·실패 전파·정리.
- **완주 계약**(사진 데이터셋 필요): 실제 ``all.zip`` 을 받아
  :func:`~ksi_processing_controller.odm.plan_artifacts` 로 읽는다. 완주에는
  중첩된 실제 드론 사진이 필요해 합성 이미지로는 대체되지 않는다.

## 돌리는 법

    docker run -d --name ksi-nodeodm -p 127.0.0.1:3971:3000 opendronemap/nodeodm
    KSI_NODEODM_URL=http://127.0.0.1:3971 uv run pytest tests/contract/test_odm_live.py

완주까지 확인하려면 사진 디렉터리를 함께 준다(20코어에서 12장 3분):

    curl -sSL -o s.tgz https://github.com/OpenDroneMap/odm_data_pacifica/archive/refs/heads/master.tar.gz
    tar xzf s.tgz
    KSI_NODEODM_URL=... KSI_ODM_IMAGES=./odm_data_pacifica-master/images \
      uv run pytest tests/contract/test_odm_live.py

환경변수가 없거나 엔진에 닿지 못하면 **skip** 한다 — CI 기본 경로를 컨테이너에
묶지 않는다. 대신 skip 사유에 그 사실을 적어, 초록불이 "확인했다"로 읽히지
않게 한다.

## 세 번째 겹 — 영속 계약(완주 + 실 스토리지 필요)

완주한 산출물이 ``plan_artifacts`` 로 매핑되는 것과, 그 바이트가 실제로 워커→
presigned PUT→MinIO→Core 등록→presigned GET 경로를 왕복해 저장·재현되는 것은
**서로 다른 주장**이다. 후자는 ``tests/contract/test_evidence_s3_live.py`` 와
같은 이름의 환경변수(``KSI_S3_ENDPOINT``/``KEY``/``SECRET``)로 실 MinIO를 함께
켜야 확인된다:

    docker run -d --name ksi-minio -p 127.0.0.1:9190:9000 \\
      -e MINIO_ROOT_USER=ksitest -e MINIO_ROOT_PASSWORD=ksitest12345 \\
      minio/minio server /data
    KSI_NODEODM_URL=... KSI_ODM_IMAGES=... \\
    KSI_S3_ENDPOINT=http://127.0.0.1:9190 KSI_S3_KEY=ksitest KSI_S3_SECRET=ksitest12345 \\
      uv run pytest tests/contract/test_odm_live.py -k persist
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from ksi_processing_controller.http_node_odm import HttpNodeOdmClient
from ksi_processing_controller.odm import (
    EngineIdentityMismatch,
    OdmError,
    OdmTaskStatus,
    SourceImage,
    assert_engine_matches,
    plan_artifacts,
)
from ksi_processing_controller.odm_assets import ODM_ASSETS

_URL = os.environ.get("KSI_NODEODM_URL", "").rstrip("/")
_IMAGES_DIR = os.environ.get("KSI_ODM_IMAGES", "")

pytestmark = pytest.mark.skipif(
    not _URL,
    reason=(
        "KSI_NODEODM_URL 미설정 — 실기동 NodeODM 대상 계약은 확인되지 않았다"
        " (docker run -p 127.0.0.1:3971:3000 opendronemap/nodeodm 후 재실행)"
    ),
)


@pytest.fixture
def client() -> HttpNodeOdmClient:
    engine = HttpNodeOdmClient(_URL)
    try:
        engine.info()
    except OdmError as exc:  # pragma: no cover - 엔진 부재 시 경로
        engine.close()
        pytest.skip(f"NodeODM 에 닿지 못했다: {exc}")
    return engine


def test_info_reports_engine_and_node_versions_separately(
    client: HttpNodeOdmClient,
) -> None:
    """[핵심] 실물이 버전을 둘 준다 — 이 사실이 어댑터 버그 하나를 만들었다."""
    info = client.info()
    assert info.engine == "odm"
    assert info.engine_version, "engineVersion 이 비어 있다"
    assert info.node_version, "version(NodeODM 자신)이 비어 있다"
    assert info.engine_version != info.node_version, (
        "두 버전이 같아지면 이 테스트가 구분을 증명하지 못한다 — "
        f"engine={info.engine_version} node={info.node_version}"
    )


def test_engine_identity_gate_uses_the_live_engine_version(
    client: HttpNodeOdmClient,
) -> None:
    """실제 엔진 버전으로는 통과하고, NodeODM 자신의 버전으로는 거부된다."""
    info = client.info()
    assert_engine_matches(info, expected_version=info.engine_version)
    with pytest.raises(EngineIdentityMismatch):
        assert_engine_matches(info, expected_version=info.node_version)


def test_unknown_uuid_is_an_error_despite_http_200(client: HttpNodeOdmClient) -> None:
    """[핵심] 미지 uuid 가 404 가 아니라 200 + {"error": ...} 다.

    상태 코드만 보는 클라이언트는 이걸 성공으로 읽는다.
    """
    with pytest.raises(OdmError, match="not found"):
        client.task_info("00000000-0000-0000-0000-000000000000")


def test_nested_asset_path_is_not_a_route(client: HttpNodeOdmClient) -> None:
    """중첩 경로 다운로드는 존재하지 않는 라우트다 — all.zip 만 있다.

    처음 설계는 asset 별 다운로드를 가정했고, 그 가정이 여기서 깨졌다.
    """
    import httpx

    response = httpx.get(
        f"{_URL}/task/00000000-0000-0000-0000-000000000000/download/odm_dem/dsm.tif",
        timeout=10.0,
    )
    assert response.status_code == 404


def _tiny_jpegs(tmp_path: Path) -> list[Path]:
    pytest.importorskip("PIL", reason="합성 이미지 생성에 Pillow 필요")
    import numpy as np
    from PIL import Image

    rng = np.random.default_rng(seed=7)
    paths = []
    for i in range(2):
        path = tmp_path / f"probe-{i}.jpg"
        Image.fromarray(
            (rng.random((64, 64, 3)) * 255).astype("uint8")
        ).save(path)
        paths.append(path)
    return paths


def test_task_lifecycle_and_failure_propagation(
    client: HttpNodeOdmClient, tmp_path: Path
) -> None:
    """제출 → 상태 조회 → 실패 사유 전달 → 정리까지 실물로 한 바퀴.

    합성 이미지 2장으로는 ODM 이 완주하지 못한다(데이터셋 단계에서 실패).
    **그 실패가 이 테스트의 대상이다** — 엔진이 준 errorMessage 를 우리가
    지어내지 않고 그대로 옮기는지, 그리고 종료 상태를 제대로 읽는지.
    완주 경로(all.zip 파싱)는 실제 드론 사진이 필요해 여기서 확인하지 않는다.
    """
    import functools
    import http.server
    import threading

    images = _tiny_jpegs(tmp_path)

    # 워커는 Core 의 presigned URL 에서 원본을 받는다 — 그 형태를 흉내내려고
    # 로컬 파일 서버를 띄운다(NodeODM 에 URL 을 직접 주지 않는 설계를 그대로 탄다).
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(tmp_path)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        uuid = client.new_task(
            [SourceImage(media_id=p.name, download_url=f"{base}/{p.name}") for p in images],
            {},
        )
        assert uuid

        state = None
        for _ in range(60):
            state = client.task_info(uuid)
            if state.status in {
                OdmTaskStatus.FAILED,
                OdmTaskStatus.COMPLETED,
                OdmTaskStatus.CANCELED,
            }:
                break
            import time

            time.sleep(2)

        assert state is not None
        assert state.status is OdmTaskStatus.FAILED, (
            f"합성 이미지 2장이 완주했다 — 이 테스트의 전제가 바뀌었다({state})"
        )
        assert state.error_message, "엔진이 실패 사유를 줬는데 우리가 버렸다"

        # 준비되지 않은 산출물도 HTTP 200 + JSON 에러다.
        with pytest.raises(OdmError):
            client.download_archive(uuid, tmp_path / "all.zip")

        client.remove_task(uuid)
        with pytest.raises(OdmError, match="not found"):
            client.task_info(uuid)
    finally:
        server.shutdown()
        client.close()


def test_mask_submission_is_accepted_and_recognized_by_the_engine(
    client: HttpNodeOdmClient, tmp_path: Path
) -> None:
    """[핵심·실물이 고쳐준 것] 동적 객체 마스크가 제출 단계에서 거부되지 않고,
    엔진이 실제로 파일명 규약(``{stem}_mask.png``)으로 사진과 매칭한다
    (odm_masking 모듈 docstring 1·2번).

    ``/task/new`` 는 여기서도 200 을 준다는 사실만으로는 마스크가 인식됐는지
    알 수 없다(모듈 docstring 3번 — 에러도 200 으로 온다) — 그래서 엔진
    콘솔 로그(``/task/{uuid}/output``, 이 어댑터의 5개 REST 포트 밖의
    디버깅 전용 side-channel)를 raw httpx 로 직접 대조한다.
    """
    import functools
    import http.server
    import threading
    import time

    import httpx
    import numpy as np
    from ksi_processing_controller.odm_masking import build_mask_image

    images = _tiny_jpegs(tmp_path)
    # render_mask_png(odm_masking.py, 실물 검증된 폴라리티)로 실제 마스크
    # 바이트를 만든다 — REST 는 내용을 검사하지 않지만, 엔진의 마스크 로더는
    # 유효한 PNG 를 기대한다(dataset.py::find_mask 는 존재만 확인하지만,
    # 그 뒤 opensfm 이 실제로 파일을 읽는다).
    regions = np.zeros((64, 64), dtype=bool)
    regions[10:40, 10:40] = True
    masks = [build_mask_image(p.name, regions) for p in images]

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(tmp_path)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        uuid = client.new_task(
            [SourceImage(media_id=p.name, download_url=f"{base}/{p.name}") for p in images],
            {},
            masks=masks,
        )
        assert uuid, "마스크를 실었다고 제출 자체가 거부되지 않는다"

        # 합성 이미지라 데이터셋/특징 단계에서 결국 실패하지만(기존 테스트와 같은
        # 전제), 그 전에 opensfm 단계가 마스크를 로드하고 로그를 남긴다.
        for _ in range(60):
            state = client.task_info(uuid)
            if state.status in {
                OdmTaskStatus.FAILED, OdmTaskStatus.COMPLETED, OdmTaskStatus.CANCELED
            }:
                break
            time.sleep(2)

        output = httpx.get(f"{_URL}/task/{uuid}/output", params={"line": 0}, timeout=10.0)
        output.raise_for_status()
        lines = output.json()
        mask_lines = [ln for ln in lines if "image mask" in ln.lower()]
        assert mask_lines, (
            f"엔진 로그에 마스크 인식 기록이 없다 — 규약이 어긋났을 수 있다: {lines}"
        )
        assert f"Found {len(masks)} image masks" in mask_lines[0], mask_lines[0]

        client.remove_task(uuid)
    finally:
        server.shutdown()
        client.close()


# ── 완주 계약 — 실제 사진이 있어야 확인된다 ──────────────────────────────────


@pytest.mark.skipif(
    not _IMAGES_DIR,
    reason=(
        "KSI_ODM_IMAGES 미설정 — 완주한 all.zip 파싱은 확인되지 않았다"
        " (중첩된 실제 드론 사진 디렉터리가 필요하다; 합성 이미지로는 ODM 이"
        " 데이터셋 단계에서 실패한다)"
    ),
)
def test_completed_reconstruction_yields_the_mapped_lineage(
    client: HttpNodeOdmClient, tmp_path: Path
) -> None:
    """[핵심] 실제로 완주한 산출물을 우리 매핑으로 읽는다.

    이 테스트가 없어서 ``cameras.json`` 오매핑이 초록불 뒤에 숨어 있었다.
    """
    import functools
    import http.server
    import threading
    import time

    images_dir = Path(_IMAGES_DIR)
    paths = sorted(
        p for p in images_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg"}
    )
    assert len(paths) >= 5, f"완주하려면 사진이 더 필요하다({len(paths)}장)"

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(images_dir)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    try:
        uuid = client.new_task(
            [SourceImage(media_id=p.name, download_url=f"{base}/{p.name}") for p in paths],
            {"dsm": True, "dtm": True, "pc-quality": "medium"},
        )
        deadline = time.monotonic() + 3600
        state = None
        while time.monotonic() < deadline:
            state = client.task_info(uuid)
            if state.status in {
                OdmTaskStatus.COMPLETED,
                OdmTaskStatus.FAILED,
                OdmTaskStatus.CANCELED,
            }:
                break
            time.sleep(15)
        assert state is not None and state.status is OdmTaskStatus.COMPLETED, (
            f"재구성이 완주하지 못했다: {state}"
        )

        archive = client.download_archive(uuid, tmp_path / "all.zip")
        reports = plan_artifacts(
            archive,
            crs="EPSG:32610",
            gsd_by_artifact={"orthophoto": 0.03, "dsm": 0.05, "dtm": 0.05},
        )

        # 매핑한 경로가 실물 아카이브에 전부 있다.
        import zipfile

        with zipfile.ZipFile(archive) as z:
            entries = set(z.namelist())
        missing = [a.archive_entry for a in ODM_ASSETS if a.archive_entry not in entries]
        assert not missing, f"매핑된 경로가 실물에 없다: {missing}"

        by_id = {r.artifact_id: r for r in reports}
        assert {"camera-poses", "point-cloud"} <= set(by_id), "원본 산출물이 빠졌다"
        assert all(r.digest.startswith("sha256:") for r in reports)
        # 계보가 단방향이다 — 부모가 자식보다 먼저 나온다.
        order = {r.artifact_id: i for i, r in enumerate(reports)}
        for report in reports:
            for parent in report.derived_from:
                assert order[parent] < order[report.artifact_id]

        client.remove_task(uuid)
    finally:
        server.shutdown()
        client.close()


# ── 영속 계약 — 완주 + 실 스토리지가 있어야 확인된다 ─────────────────────────

_S3_ENDPOINT = os.environ.get("KSI_S3_ENDPOINT", "").rstrip("/")
_S3_KEY = os.environ.get("KSI_S3_KEY", "")
_S3_SECRET = os.environ.get("KSI_S3_SECRET", "")
_S3_READY = bool(_S3_ENDPOINT and _S3_KEY and _S3_SECRET)


@pytest.mark.skipif(
    not (_IMAGES_DIR and _S3_READY),
    reason=(
        "KSI_ODM_IMAGES 와 KSI_S3_ENDPOINT/KEY/SECRET 이 모두 있어야 한다 — "
        "산출물 바이트가 실제로 워커→MinIO→Core 등록→재다운로드 경로를 왕복해"
        " 저장되는지는 확인되지 않았다(모듈 docstring '세 번째 겹' 참조)"
    ),
)
def test_completed_reconstruction_artifacts_persist_and_redownload_with_matching_digest(
    client: HttpNodeOdmClient, tmp_path: Path
) -> None:
    """[핵심] 완주 산출물의 바이트가 실제로 저장되고, 재다운로드한 바이트의
    digest 가 등록값과 정확히 일치한다.

    ``plan_artifacts`` 가 계산하는 digest 는 zip 엔트리 원본의 sha256이다(D3).
    이 값이 실제로 저장된 바이트를 가리키는지는 가짜 스토리지 계약
    테스트(``test_processing_jobs.py``)로는 증명할 수 없다 — presigned PUT 이
    청크 인코딩으로 411을 받거나, 등록된 digest와 저장된 바이트가 어긋나도
    거기서는 초록불이 켜진다. 워커 전체(``run_job``)를 실제 NodeODM·MinIO·
    Core(in-process ASGI) 조합으로 한 번 돌려야 이 간극이 드러난다.
    """
    import functools
    import hashlib
    import http.server
    import threading
    import time
    from datetime import UTC, datetime

    import boto3
    import httpx
    from botocore.config import Config
    from fastapi.testclient import TestClient
    from ksi_core.app import create_app
    from ksi_core.auth import (
        AuthRegistry,
        Principal,
        PrincipalKind,
        PrincipalTokenRecord,
        Role,
    )
    from ksi_core.durable_journal import DurableJournal
    from ksi_core.evidence import DEFAULT_UPLOAD_TTL
    from ksi_core.evidence_s3 import S3EvidenceStorage
    from ksi_core.mission_records import MissionRecord, MissionStore
    from ksi_core.processing_jobs import ProcessingJobStore
    from ksi_core.processing_profiles import KSI_ODM_CIVIL_V1_ID
    from ksi_core.sites import SiteFrame, SiteStore
    from ksi_core.source_media import (
        SourceMediaClaim,
        SourceMediaStore,
        build_source_media_object_key,
    )
    from ksi_processing_controller.core_client import HttpCoreClient
    from ksi_processing_controller.worker import run_job

    images_dir = Path(_IMAGES_DIR)
    paths = sorted(
        p for p in images_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg"}
    )
    assert len(paths) >= 5, f"완주하려면 사진이 더 필요하다({len(paths)}장)"

    bucket = "ksi-odm-live-persist"
    s3_client = boto3.client(
        "s3",
        endpoint_url=_S3_ENDPOINT,
        aws_access_key_id=_S3_KEY,
        aws_secret_access_key=_S3_SECRET,
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    )
    import contextlib

    with contextlib.suppress(Exception):  # 이미 있으면 그대로 쓴다
        s3_client.create_bucket(Bucket=bucket)
    storage = S3EvidenceStorage(bucket=bucket, client=s3_client, endpoint_url=_S3_ENDPOINT)

    now = datetime(2026, 1, 1, tzinfo=UTC)
    site_store = SiteStore(DurableJournal(tmp_path / "sites.jsonl"))
    site_frame = SiteFrame(
        crs="EPSG:5186",
        vertical_datum="ellipsoidal_native",
        transform_version="v1",
        unit="meter",
    )
    site_id = "site-odm-live-persist"
    mission_id = "mission-odm-live-persist"
    reg = site_store.register(
        site_id, "ODM live persist", site_frame, data_residency=None, actor="op-1", now=now
    )
    assert reg.verdict.value == "REGISTERED", reg

    mission_store = MissionStore(DurableJournal(tmp_path / "missions.jsonl"))
    issued_mission = mission_store.record_issuance(
        MissionRecord(
            mission_id=mission_id,
            site_id=site_id,
            mission_type="BASELINE_MAPPING",
            artifact_kind="contract",
            contract={"schemaVersion": "1.2", "missionId": mission_id},
            kmz_sha256=None,
            route_pattern=None,
            waypoint_count=None,
            planned_coverage_ratio=None,
            issued_at=now,
            issued_by="op-1",
        )
    )
    assert issued_mission.value == "RECORDED", issued_mission

    # 원본 사진을 presigned PUT 으로 실제 MinIO에 올린다 — 워커가 이 URL 에서
    # 받아 ODM 에 제출한다(로컬 파일 서버가 아니라 실 스토리지 경로).
    claims = []
    upload_client = httpx.Client(timeout=60.0)
    for p in paths:
        data = p.read_bytes()
        from PIL import Image

        with Image.open(p) as im:
            width, height = im.size
        claims.append(
            SourceMediaClaim(
                media_id=p.name,
                sha256=hashlib.sha256(data).hexdigest(),
                size_bytes=len(data),
                width=width,
                height=height,
                content_type="image/jpeg",
            )
        )
        key = build_source_media_object_key(
            site_id=site_id, mission_id=mission_id, media_id=p.name
        )
        put_url = storage.presigned_put(key, content_type="image/jpeg", ttl=DEFAULT_UPLOAD_TTL)
        put = upload_client.put(put_url, content=data, headers={"Content-Type": "image/jpeg"})
        put.raise_for_status()

    source_media_store = SourceMediaStore(
        DurableJournal(tmp_path / "source-media.jsonl"), mission_store=mission_store
    )
    batch = source_media_store.register_batch(mission_id, claims, registered_by="op-1", now=now)
    assert batch.verdict.value == "PROCESSED", batch
    sealed = source_media_store.seal(mission_id, sealed_by="op-1", now=now)
    assert sealed.verdict.value == "SEALED", sealed

    processing_job_store = ProcessingJobStore(
        DurableJournal(tmp_path / "processing-jobs.jsonl"),
        source_media_store=source_media_store,
        site_store=site_store,
    )
    spec = processing_job_store.resolve_processing_profile(KSI_ODM_CIVIL_V1_ID)
    issued_job = processing_job_store.issue(mission_id, spec, issued_by="op-1", now=now)
    assert issued_job.record is not None, issued_job
    assert issued_job.record.spec.processing_profile_id == KSI_ODM_CIVIL_V1_ID
    assert issued_job.record.spec.processing_profile_digest == spec.processing_profile_digest
    job_id = issued_job.record.job_id

    worker_token = "odm-live-persist-worker"  # noqa: S105
    reader_token = "odm-live-persist-reader"  # noqa: S105
    auth_registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(worker_token.encode()).hexdigest(),
                principal=Principal(
                    principal_id="worker-odm-live-persist",
                    kind=PrincipalKind.PROCESSING_WORKER,
                    role=None,
                    device_id=None,
                ),
            ),
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(reader_token.encode()).hexdigest(),
                principal=Principal(
                    principal_id="reader-odm-live-persist",
                    kind=PrincipalKind.OPERATOR,
                    role=Role.ADMIN,
                    device_id=None,
                ),
            ),
        ]
    )
    app = create_app(
        auth_registry=auth_registry,
        evidence_storage=storage,
        site_store=site_store,
        mission_store=mission_store,
        source_media_store=source_media_store,
        processing_job_store=processing_job_store,
    )
    worker_transport = TestClient(app, base_url="http://core.local")
    core = HttpCoreClient("http://core.local", token=worker_token, client=worker_transport)

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(images_dir)
    )
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    try:
        deadline = time.monotonic() + 3600
        run_job(
            job_id,
            core=core,
            odm=client,
            work_dir=tmp_path / "worker",
            poll_interval_seconds=15.0,
            # 이게 없으면 orthophoto/dsm/dtm 이 "GSD 필수인데 없다"로 전부
            # 조용히 건너뛰어진다(odm.plan_artifacts) — mesh-multi-file-
            # artifact-persistence 검증 전에는 이 테스트가 그 셋의 등록을
            # 요구하지 않아 드러나지 않았던 기존 공백(2026-08-08 실측 발견).
            gsd_by_artifact={"orthophoto": 0.03, "dsm": 0.05, "dtm": 0.05},
        )
        assert time.monotonic() < deadline, "제한 시간 안에 완주하지 못했다"

        job_record = processing_job_store.get(job_id)
        assert job_record is not None
        assert job_record.status.value == "SUCCEEDED", job_record.status
        assert job_record.artifacts, "완주했는데 등록된 산출물이 없다"

        reader_transport = TestClient(app, base_url="http://core.local")
        reader_transport.headers.update({"Authorization": f"Bearer {reader_token}"})
        download_client = httpx.Client(timeout=60.0)
        mesh_seen = False
        for artifact in job_record.artifacts:
            resp = reader_transport.get(
                f"/v1/processing-jobs/{job_id}/artifacts/{artifact.artifact_id}/download"
            )
            assert resp.status_code == 200, (artifact.artifact_id, resp.status_code, resp.text)
            body = resp.json()
            assert body["verdict"] == "ARTIFACT_READY", body

            if body.get("files"):
                # [mesh-multi-file-artifact-persistence] artifact.digest 는
                # 원본 아카이브 내부 경로(예: "odm_texturing/odm_textured_
                # model_geo.obj")까지 섞어 결합 해싱한 값이다
                # (odm.digest_archive_entries) — 그 경로 문자열은 워커
                # 내부(odm_assets.py)에만 있고 Core 는 알지 못한다(의도된
                # 경계: Core 는 basename 만 안다, ArtifactDownloadResponse.
                # files[].name 참고). 그래서 재다운로드만으로 그 정확한
                # digest 를 재계산할 수는 없다 — 대신 파일 개수·각 파일의
                # 실제 다운로드 가능성·내용 존재를 확인한다(더 약하지만
                # 달성 가능한 무결성 증거).
                mesh_seen = True
                assert len(body["files"]) == 1 + len(artifact.auxiliary_files), (
                    artifact.artifact_id, body["files"]
                )
                for file_view in body["files"]:
                    file_resp = download_client.get(file_view["downloadUrl"])
                    assert file_resp.status_code == 200, (
                        artifact.artifact_id, file_view["name"], file_resp.status_code
                    )
                    assert len(file_resp.content) > 0, (artifact.artifact_id, file_view["name"])
                continue

            bytes_resp = download_client.get(body["downloadUrl"])
            assert bytes_resp.status_code == 200, (artifact.artifact_id, bytes_resp.status_code)
            got_digest = "sha256:" + hashlib.sha256(bytes_resp.content).hexdigest()
            assert got_digest == artifact.digest, (
                f"{artifact.artifact_id}: 등록 digest={artifact.digest} != "
                f"재다운로드 바이트 digest={got_digest}"
            )

        assert mesh_seen, (
            "이 실행에서 mesh(다중파일) 산출물이 등록되지 않았다 — "
            "mesh-multi-file-artifact-persistence 경로가 실제로 안 탔다는 뜻이다"
        )
        orthophoto = next(
            (a for a in job_record.artifacts if a.artifact_id == "orthophoto"), None
        )
        assert orthophoto is not None, (
            "orthophoto 가 등록되지 않았다 — mesh 가 실제로 파생 부모로 실재하지 "
            "않으면(UNKNOWN_PARENT_ARTIFACT) 여기 도달하지 못한다. mesh 가 등록됐는데도 "
            "orthophoto 가 없다면 별개 원인(ODM 이 이번 재구성에서 정사영상을 안 냄 등)이다"
        )
    finally:
        server.shutdown()
