"""NodeODM REST 클라이언트 — :class:`~ksi_processing_controller.odm.NodeOdmClient` 구현체.

httpx 로 HTTP 를 말하는 것 외에 아무 판단도 하지 않는다. 상태 매핑·계보·신원
대조는 전부 :mod:`ksi_processing_controller.odm` 의 순수 함수들이 하고, 이
모듈은 "요청을 보내고 봉투를 벗긴다"까지다 — 그래야 그 판단들이 네트워크 없이
시험된다.

## 이 클라이언트가 실물에서 배운 것

무수정 ``opendronemap/nodeodm:latest``(NodeODM 2.2.4 / ODM 3.5.6)를 띄워
확인한 동작이다(2026-08-06):

- **에러가 HTTP 200 으로 온다.** 미지 uuid 도 준비 안 된 asset 도 200 +
  ``{"error": ...}`` 다. 그래서 ``raise_for_status()`` 만으로는 실패를 잡지
  못하고, 모든 JSON 응답이 :func:`~ksi_processing_controller.odm.unwrap_response`
  를 지난다.
- **산출물은 ``all.zip`` 하나뿐이다.** 개별 asset 이름은 ``{"error": "Invalid
  asset"}`` 이거나(``getAssetsArchivePath`` 거부) 중첩 경로면 404 HTML 이다.
- **``POST /task/new`` 는 multipart 다.** ``images`` 필드에 파일들을 싣고
  ``options`` 는 JSON 문자열 하나로 보낸다.

## 원본 사진을 이 프로세스가 통과시킨다

Core 가 준 presigned URL 에서 받아 NodeODM 으로 넘긴다. NodeODM 에 URL 을 직접
주는 경로(``/task/new`` 의 ``webhook``/zipurl)를 쓰지 않는 이유는, 그러면
presigned URL 이 엔진 컨테이너로 새서 **KSI 가 통제하지 못하는 곳에 인가가
복제**되기 때문이다(evidence.py "presigned URL 은 그 자체가 인가다").

## 검증 상태

``/info``·``/task/new``·``/task/{uuid}/info``·``/task/remove`` 와 에러 봉투는
실물 대상으로 확인했다(``tests/contract/test_odm_live.py``, NodeODM 이 없으면
skip). **완주한 재구성의 ``all.zip`` 다운로드는 아직 확인하지 못했다** — 실제
드론 사진 수백 장이 있어야 ODM 이 완주하고, 합성 이미지로는 데이터셋 단계에서
실패한다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx

from ksi_processing_controller.odm import (
    ARCHIVE_ASSET,
    NodeOdmClient,
    OdmEngineInfo,
    OdmError,
    OdmTaskState,
    SourceImage,
    unwrap_response,
)

logger = logging.getLogger(__name__)

# 업로드는 사진 수백 장이라 길고, 조회는 짧아야 워커가 빨리 죽음을 알아챈다.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=600.0, pool=10.0)


class HttpNodeOdmClient:
    """NodeODM REST 를 httpx 로 말한다. 판단은 하지 않는다."""

    def __init__(
        self,
        base_url: str,
        *,
        client: httpx.Client | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=False)

    def _get_json(self, path: str, *, what: str) -> dict[str, Any]:
        try:
            response = self._client.get(f"{self._base_url}{path}")
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise OdmError(f"{what}: 엔진에 닿지 못했다 — {exc}") from exc
        except ValueError as exc:
            # 중첩 asset 경로처럼 라우트 자체가 없으면 HTML 404 가 온다.
            raise OdmError(f"{what}: 응답이 JSON 이 아니다") from exc
        return unwrap_response(payload, what=what)

    def info(self) -> OdmEngineInfo:
        return OdmEngineInfo.from_payload(self._get_json("/info", what="/info"))

    def new_task(self, images: Sequence[SourceImage], options: dict[str, Any]) -> str:
        """원본을 받아 multipart 로 넘기고 uuid 를 돌려준다.

        presigned URL 을 NodeODM 에 넘기지 않고 이 프로세스가 바이트를 통과시킨다
        (모듈 docstring) — 인가가 엔진 컨테이너로 복제되지 않게.
        """
        if not images:
            raise OdmError("/task/new: 넘길 사진이 없다")
        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for image in images:
            try:
                fetched = self._client.get(image.download_url)
                fetched.raise_for_status()
            except httpx.HTTPError as exc:
                raise OdmError(
                    f"/task/new: 원본 {image.media_id} 를 받지 못했다 — {exc}"
                ) from exc
            files.append(("images", (image.media_id, fetched.content, "image/jpeg")))

        try:
            response = self._client.post(
                f"{self._base_url}/task/new",
                files=files,
                data={"options": json.dumps(
                    [{"name": k, "value": v} for k, v in sorted(options.items())]
                )},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise OdmError(f"/task/new: 엔진에 닿지 못했다 — {exc}") from exc
        except ValueError as exc:
            raise OdmError("/task/new: 응답이 JSON 이 아니다") from exc

        data = unwrap_response(payload, what="/task/new")
        uuid = data.get("uuid")
        if not isinstance(uuid, str) or not uuid:
            raise OdmError(f"/task/new: uuid 가 없다 — {data!r}")
        return uuid

    def task_info(self, uuid: str) -> OdmTaskState:
        return OdmTaskState.from_payload(
            self._get_json(f"/task/{uuid}/info", what=f"/task/{uuid}/info")
        )

    def download_archive(self, uuid: str, dest: Path) -> Path:
        """``all.zip`` 을 ``dest`` 로 스트리밍 저장한다.

        준비되지 않은 산출물도 **HTTP 200 + JSON 에러**로 오므로, 본문이 JSON
        이면 그것은 파일이 아니라 실패다 — 상태 코드로 가릴 수 없다.
        """
        url = f"{self._base_url}/task/{uuid}/download/{ARCHIVE_ASSET}"
        try:
            with self._client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if content_type.startswith("application/json"):
                    unwrap_response(
                        json.loads(response.read()), what=f"/task/{uuid}/download"
                    )
                    raise OdmError(f"/task/{uuid}/download: 산출물이 준비되지 않았다")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        handle.write(chunk)
        except httpx.HTTPError as exc:
            raise OdmError(f"/task/{uuid}/download: 엔진에 닿지 못했다 — {exc}") from exc
        return dest

    def remove_task(self, uuid: str) -> None:
        try:
            response = self._client.post(
                f"{self._base_url}/task/remove", json={"uuid": uuid}
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise OdmError(f"/task/remove: 엔진에 닿지 못했다 — {exc}") from exc
        except ValueError as exc:
            raise OdmError("/task/remove: 응답이 JSON 이 아니다") from exc
        unwrap_response(payload, what="/task/remove")

    def close(self) -> None:
        self._client.close()


def _assert_implements_port(client: HttpNodeOdmClient) -> NodeOdmClient:
    """구현체가 포트를 만족하는지 타입 검사가 보게 한다(런타임 호출 없음)."""
    return client


__all__ = ["DEFAULT_TIMEOUT", "HttpNodeOdmClient"]
