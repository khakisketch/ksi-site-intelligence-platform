"""Core HTTP 클라이언트 — 워커가 처리 작업 표면을 말하는 유일한 경로.

:mod:`ksi_processing_controller.odm`/``http_node_odm`` 과 같은 관용구다 —
Protocol 로 포트를 두고, httpx 구현체는 "요청을 보내고 봉투를 벗긴다"까지만
한다. 상태 판정·재시도 정책은 이 모듈 밖(:mod:`worker`)에 둔다.

## Core 가 이미 정한 것을 여기서 다시 판단하지 않는다

lease 관문·전이표·INV-051 게이트는 전부 Core(``ksi_core.processing_jobs``)
쪽에 있다. 이 클라이언트는 그 판정 결과(HTTP status + verdict 문자열)를
그대로 :class:`CoreClientError` 로 옮길 뿐, "이 verdict 면 재시도해도 될까"
같은 판단을 하지 않는다 — 그 판단은 호출자(:mod:`worker`)의 몫이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class CoreClientError(RuntimeError):
    """Core 가 성공 아닌 verdict 를 돌려줬다 — 워커가 다음 행동을 정한다.

    ``verdict`` 를 문자열로 들고 있는 이유: 워커가 재시도할지(``STORE_
    UNAVAILABLE``) 포기할지(``ILLEGAL_TRANSITION``)를 가르려면 값이 필요하다.
    이 클라이언트는 그 분기를 하지 않는다(모듈 docstring).
    """

    def __init__(self, *, what: str, verdict: str, detail: str | None) -> None:
        self.verdict = verdict
        self.detail = detail
        super().__init__(f"{what}: {verdict}" + (f" — {detail}" if detail else ""))


@dataclass(frozen=True, slots=True)
class JobInputMedia:
    media_id: str
    download_url: str


@dataclass(frozen=True, slots=True)
class JobInput:
    """``GET /input`` 을 옮긴 것 — **신고값이 없다**(source_media.py 참고)."""

    mission_id: str
    site_id: str
    status: str
    provider: str
    engine_version: str
    engine_digest: str
    execution_locus: str
    processing_params: dict[str, Any]
    source_bundle_digest: str
    media: tuple[JobInputMedia, ...]
    # 현장 등록 시점의 CRS — Core 가 site_store 에서 읽어 준다(워커·발급자가
    # 자기 신고하지 않는다). None 이면 현장 원장 이상 상태다.
    site_crs: str | None


@dataclass(frozen=True, slots=True)
class MeasuredImage:
    """워커가 실측한 값 — 신고값이 아니라 **바이트에서 잰 값**이다."""

    media_id: str
    sha256: str
    size_bytes: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class ArtifactSubmission:
    """``POST .../artifacts`` 요청 payload — 계보 앵커를 실을 자리가 없다."""

    artifact_id: str
    kind: str
    authority: str
    derived_from: tuple[str, ...]
    digest: str
    format: str
    crs: str | None
    gsd: float | None


class CoreClient(Protocol):
    """워커가 필요로 하는 Core 표면 다섯 개. 이 이상을 워커가 알 필요는 없다."""

    def acquire_lease(self, job_id: str) -> None:
        """``POST /lease``. LEASED·LEASE_RENEWED 외엔 :class:`CoreClientError`."""
        ...

    def get_input(self, job_id: str) -> JobInput:
        """``GET /input``. INPUT_READY 외엔 :class:`CoreClientError`."""
        ...

    def transition(self, job_id: str, target: str, *, detail: str | None = None) -> None:
        """``POST /transitions``. TRANSITIONED 외엔 :class:`CoreClientError`."""
        ...

    def verify_source_media(
        self, mission_id: str, measurements: list[MeasuredImage]
    ) -> None:
        """``POST /source-media/verify``. VERIFIED 외엔 :class:`CoreClientError`."""
        ...

    def register_artifact(self, job_id: str, submission: ArtifactSubmission) -> None:
        """``POST /artifacts``. ARTIFACT_REGISTERED 외엔 :class:`CoreClientError`."""
        ...


class HttpCoreClient:
    """httpx 로 Core 표면을 말한다. 판단은 하지 않는다(모듈 docstring)."""

    def __init__(self, base_url: str, *, token: str, client: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(
            headers={"Authorization": f"Bearer {token}"}, timeout=30.0
        )

    def _post(
        self, path: str, *, what: str, ok: str, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self._client.post(f"{self._base_url}{path}", json=json)
        try:
            payload = response.json()
        except ValueError as exc:
            raise CoreClientError(
                what=what, verdict="NON_JSON_RESPONSE", detail=response.text[:200]
            ) from exc
        verdict = payload.get("verdict")
        if verdict != ok:
            raise CoreClientError(what=what, verdict=str(verdict), detail=payload.get("detail"))
        return payload

    def acquire_lease(self, job_id: str) -> None:
        payload = self._post(f"/v1/processing-jobs/{job_id}/lease", what="lease", ok="LEASED")
        # 갱신도 성공이다 — ok 하나로 판정하면 재취득만 통과한다.
        if payload.get("verdict") not in {"LEASED", "LEASE_RENEWED"}:  # pragma: no cover
            raise CoreClientError(what="lease", verdict=str(payload.get("verdict")), detail=None)

    def get_input(self, job_id: str) -> JobInput:
        response = self._client.get(f"{self._base_url}/v1/processing-jobs/{job_id}/input")
        try:
            payload = response.json()
        except ValueError as exc:
            raise CoreClientError(
                what="input", verdict="NON_JSON_RESPONSE", detail=response.text[:200]
            ) from exc
        if payload.get("verdict") != "INPUT_READY":
            raise CoreClientError(
                what="input", verdict=str(payload.get("verdict")), detail=payload.get("detail")
            )
        data = payload["input"]
        return JobInput(
            mission_id=data["missionId"],
            site_id=data["siteId"],
            status=data["status"],
            provider=data["provider"],
            engine_version=data["engineVersion"],
            engine_digest=data["engineDigest"],
            execution_locus=data["executionLocus"],
            processing_params=data["processingParams"],
            source_bundle_digest=data["sourceBundleDigest"],
            site_crs=data.get("siteCrs"),
            media=tuple(
                JobInputMedia(media_id=m["mediaId"], download_url=m["downloadUrl"])
                for m in data["media"]
            ),
        )

    def transition(self, job_id: str, target: str, *, detail: str | None = None) -> None:
        self._post(
            f"/v1/processing-jobs/{job_id}/transitions",
            what=f"transition→{target}",
            ok="TRANSITIONED",
            json={"targetStatus": target, "detail": detail},
        )

    def verify_source_media(
        self, mission_id: str, measurements: list[MeasuredImage]
    ) -> None:
        self._post(
            f"/v1/missions/{mission_id}/source-media/verify",
            what="verify",
            ok="VERIFIED",
            json={
                "measurements": [
                    {
                        "mediaId": m.media_id,
                        "sha256": m.sha256,
                        "bytes": m.size_bytes,
                        "width": m.width,
                        "height": m.height,
                    }
                    for m in measurements
                ]
            },
        )

    def register_artifact(self, job_id: str, submission: ArtifactSubmission) -> None:
        self._post(
            f"/v1/processing-jobs/{job_id}/artifacts",
            what=f"artifact:{submission.artifact_id}",
            ok="ARTIFACT_REGISTERED",
            json={
                "artifactId": submission.artifact_id,
                "kind": submission.kind,
                "authority": submission.authority,
                "derivedFrom": list(submission.derived_from),
                "digest": submission.digest,
                "format": submission.format,
                "crs": submission.crs,
                "gsd": submission.gsd,
            },
        )

    def close(self) -> None:
        self._client.close()


__all__ = [
    "ArtifactSubmission",
    "CoreClient",
    "CoreClientError",
    "HttpCoreClient",
    "JobInput",
    "JobInputMedia",
    "MeasuredImage",
]
