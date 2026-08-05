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
