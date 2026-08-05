"""무수정 NodeODM 컨테이너 대상 실기동 계약 (ADR-KSI-012 D1/D2).

``tests/contract/test_odm_adapter.py`` 는 포트를 가짜로 갈아끼운 계약 시험이라
**응답 형태가 실물과 같은지는 증명하지 못한다**. 그 간극에서 실제로 네 가지가
틀려 있었다(2026-08-06, NodeODM 2.2.4 / ODM 3.5.6):

1. ``/info`` 의 ``version``(NodeODM 2.2.4)과 ``engineVersion``(ODM 3.5.6)이 다른
   값인데 전자를 계약의 engineVersion 과 대조하고 있었다.
2. 산출물은 ``all.zip`` 하나로만 나온다 — 개별 asset 다운로드는 NodeODM 에 없다.
3. 에러가 HTTP 200 + ``{"error": ...}`` 로 온다 — 상태 코드로 못 가른다.
4. 중첩 asset 경로는 라우트 자체가 없어 404 HTML 이다.

## 이 파일이 확인하지 **못하는** 것

완주한 재구성의 ``all.zip`` 내용. 실제 드론 사진 수백 장이 있어야 ODM 이 완주
하고, 합성 이미지로는 데이터셋 단계에서 실패한다(그 실패 경로는 확인한다).
따라서 :func:`~ksi_processing_controller.odm.plan_artifacts` 가 실제 ODM 산출물
아카이브를 제대로 읽는지는 **아직 미검증**이고, 원장에 리스크로 남아 있다.

## 돌리는 법

    docker run -d --name ksi-nodeodm -p 127.0.0.1:3971:3000 opendronemap/nodeodm
    KSI_NODEODM_URL=http://127.0.0.1:3971 uv run pytest tests/contract/test_odm_live.py

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
)

_URL = os.environ.get("KSI_NODEODM_URL", "").rstrip("/")

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
