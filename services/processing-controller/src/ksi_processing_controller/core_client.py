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
from ksi_event_contracts.change_detection_result import ArtifactRef, ChangeDetectionResult
from ksi_event_contracts.volume_change_report import VolumeChangeReport


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
class PendingJob:
    """워커가 다음에 잡을 후보 1건 — Core 의 ``PendingProcessingJobView`` 를 옮긴 것.

    ``mission_id``·계약 내용이 없는 것이 의도다(``PROCESSING_WORK`` 는
    ``MISSIONS_READ`` 를 포함하지 않는다 — Core 쪽 스키마 docstring 참조). lease 를
    잡은 다음에야 :meth:`CoreClient.get_input` 이 전체 사양을 준다.
    """

    job_id: str


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
    # 주 파일(digest/objectKey 가 가리키는 파일) 외 나머지 파일들의 basename —
    # 산출물이 파일 하나면 빈 튜플(mesh-multi-file-artifact-persistence).
    auxiliary_files: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArtifactUploadTarget:
    """산출물 바이트를 올릴 자리 — Core 가 정해서 내려준다.

    **워커가 객체 키를 고르지 않는다.** 고를 수 있으면 워커 토큰 하나로 버킷의
    임의 경로에 쓸 수 있고, "서버가 정한 자리에만 쓴다"를 워커 코드가 매번
    기억해야 한다.
    """

    object_key: str
    upload_url: str


@dataclass(frozen=True, slots=True)
class PendingComparisonRequest:
    """비교 워커가 다음에 잡을 후보 1건 — ``PendingJob`` 과 동형(§ 그 docstring)."""

    request_id: str


@dataclass(frozen=True, slots=True)
class ComparisonInput:
    """``GET /v1/comparison-requests/{id}/input`` 을 옮긴 것.

    ``*_url`` 은 presigned GET(바이트를 받을 자리), ``point_cloud_*``/``dsm_*``
    (``ArtifactRef | None``)는 그 바이트가 어느 (작업, 산출물)인지다 —
    ``ChangeDetectionResult``/``VolumeChangeReport`` 제출에 둘 다 필요하다.
    각 쌍이 ``None`` 이면 그 비교(변화탐지/체적)는 이 요청에서 시도하지 않는다.
    """

    request_id: str
    mission_id: str
    # 워커가 QUEUED→RUNNING 전이를 시도해도 되는지는 이 값으로만 안다 — 재개된
    # 요청(다른 워커가 이미 RUNNING 으로 바꿔 놓은 것)에 또 전이를 시도하면
    # ILLEGAL_TRANSITION 이다(worker.py 의 JobInput.status 와 동일 원칙).
    status: str
    point_cloud_baseline: ArtifactRef | None
    point_cloud_baseline_url: str | None
    point_cloud_current: ArtifactRef | None
    point_cloud_current_url: str | None
    dsm_baseline: ArtifactRef | None
    dsm_baseline_url: str | None
    dsm_current: ArtifactRef | None
    dsm_current_url: str | None
    zones: dict[str, dict[str, Any]] | None
    zone_crs: str | None


class CoreClient(Protocol):
    """워커가 필요로 하는 Core 표면. 이 이상을 워커가 알 필요는 없다."""

    def list_pending(self, *, limit: int = 50) -> list[PendingJob]:
        """``GET /v1/processing-jobs``. QUEUED + lease 만료된 RUNNING(죽은 워커가
        쥐고 있던 작업), 오래된 것부터(FIFO)."""
        ...

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
        """``POST /source-media/verify``. VERIFIED·ALREADY_VERIFIED 외엔 예외."""
        ...

    def presign_artifact_upload(
        self, job_id: str, *, artifact_id: str, content_type: str, filename: str | None = None
    ) -> ArtifactUploadTarget:
        """``POST /artifacts/upload-url``. UPLOAD_READY 외엔 :class:`CoreClientError`.

        ``filename`` 은 다중 파일 산출물(mesh 등)에서 주 파일 외 나머지 각각을
        올릴 때 채운다 — ``None`` 이면 주 파일 자리(기존 동작과 동일)다.
        """
        ...

    def register_artifact(self, job_id: str, submission: ArtifactSubmission) -> None:
        """``POST /artifacts``. ARTIFACT_REGISTERED 외엔 :class:`CoreClientError`."""
        ...

    # ── W2 비교 요청(comparison_requests.py) ────────────────────────────────

    def list_pending_comparisons(self, *, limit: int = 50) -> list[PendingComparisonRequest]:
        """``GET /v1/comparison-requests``. QUEUED + lease 만료된 RUNNING, 오래된 것부터."""
        ...

    def acquire_comparison_lease(self, request_id: str) -> None:
        """``POST /comparison-requests/{id}/lease``. LEASED·LEASE_RENEWED 외엔 예외."""
        ...

    def get_comparison_input(self, request_id: str) -> ComparisonInput:
        """``GET /comparison-requests/{id}/input``. INPUT_READY 외엔 :class:`CoreClientError`."""
        ...

    def transition_comparison(
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        """``POST /comparison-requests/{id}/transitions``. TRANSITIONED 외엔 예외."""
        ...

    def submit_change_detection(self, mission_id: str, result: ChangeDetectionResult) -> None:
        """``POST /v1/missions/{id}/change-detection``. RECORDED 외엔 :class:`CoreClientError`."""
        ...

    def submit_volume_change(self, mission_id: str, report: VolumeChangeReport) -> None:
        """``POST /v1/missions/{id}/volume-changes``. RECORDED 외엔 :class:`CoreClientError`."""
        ...


class HttpCoreClient:
    """httpx 로 Core 표면을 말한다. 판단은 하지 않는다(모듈 docstring)."""

    def __init__(self, base_url: str, *, token: str, client: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=30.0)
        # ``client`` 를 주입해도(테스트 등) ``token`` 이 조용히 무시되지 않는다 —
        # 둘 다 준 호출자는 "이 토큰으로 이 클라이언트를 써라"를 뜻하지 "클라이언트가
        # 있으니 토큰은 버려라"를 뜻하지 않는다. 실기동 전까지 이 자리가 정확히
        # 거꾸로였다: 주입된 클라이언트는 인증 헤더 없이 나갔다.
        self._client.headers["Authorization"] = f"Bearer {token}"

    def _post(
        self,
        path: str,
        *,
        what: str,
        ok: str | frozenset[str],
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """``ok`` 는 문자열 하나 또는 성공으로 볼 verdict 집합이다.

        **집합을 받는 이유가 실기동에서 드러났다.** ``acquire_lease`` 가 처음엔
        ``ok="LEASED"`` 만 넘기고, 갱신(``LEASE_RENEWED``)까지 성공으로 보는
        검증은 이 함수가 이미 예외를 던진 **뒤**에 있는 죽은 코드였다 — 가짜
        ``CoreClient`` 로 짠 단위 테스트는 이 HTTP 번역 계층 자체를 우회해서
        통과했지만, 실제 Core+NodeODM 대상 완주 시도에서 heartbeat 갱신이
        일어나는 순간 곧바로 죽었다(``lease: LEASE_RENEWED`` 예외). 그래서
        판정 집합은 호출부가 아니라 이 함수가 한 번에 본다.
        """
        response = self._client.post(f"{self._base_url}{path}", json=json)
        try:
            payload = response.json()
        except ValueError as exc:
            raise CoreClientError(
                what=what, verdict="NON_JSON_RESPONSE", detail=response.text[:200]
            ) from exc
        verdict = payload.get("verdict")
        accepted = {ok} if isinstance(ok, str) else ok
        if verdict not in accepted:
            raise CoreClientError(what=what, verdict=str(verdict), detail=payload.get("detail"))
        return payload

    def list_pending(self, *, limit: int = 50) -> list[PendingJob]:
        response = self._client.get(
            f"{self._base_url}/v1/processing-jobs", params={"limit": limit}
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise CoreClientError(
                what="list-pending", verdict="NON_JSON_RESPONSE", detail=response.text[:200]
            ) from exc
        if response.status_code != 200:
            raise CoreClientError(
                what="list-pending",
                verdict=f"HTTP_{response.status_code}",
                detail=str(payload.get("detail")) if isinstance(payload, dict) else None,
            )
        return [PendingJob(job_id=item["jobId"]) for item in payload["jobs"]]

    def acquire_lease(self, job_id: str) -> None:
        self._post(
            f"/v1/processing-jobs/{job_id}/lease",
            what="lease",
            ok=frozenset({"LEASED", "LEASE_RENEWED"}),
        )

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
        # ALREADY_VERIFIED 도 성공이다 — 재시도 작업(이전 시도가 실패한 뒤
        # 새로 발급된 작업)이 같은 미션의 이미 검증된 번들에 다시 보고하면
        # 정확히 이 verdict 가 나온다(실기동에서 실제로 발생, 2026-08-06).
        self._post(
            f"/v1/missions/{mission_id}/source-media/verify",
            what="verify",
            ok=frozenset({"VERIFIED", "ALREADY_VERIFIED"}),
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

    def presign_artifact_upload(
        self, job_id: str, *, artifact_id: str, content_type: str, filename: str | None = None
    ) -> ArtifactUploadTarget:
        payload = self._post(
            f"/v1/processing-jobs/{job_id}/artifacts/upload-url",
            what=f"upload-url:{artifact_id}:{filename or '(primary)'}",
            ok="UPLOAD_READY",
            json={
                "artifactId": artifact_id,
                "contentType": content_type,
                "filename": filename,
            },
        )
        object_key = payload.get("objectKey")
        upload_url = payload.get("uploadUrl")
        if not isinstance(object_key, str) or not isinstance(upload_url, str):
            # verdict 는 UPLOAD_READY 인데 자리가 안 왔다 — 여기서 잡지 않으면
            # 다음 줄의 PUT 이 None 을 URL 로 쓴다.
            raise CoreClientError(
                what=f"upload-url:{artifact_id}",
                verdict="UPLOAD_READY",
                detail="응답에 objectKey/uploadUrl 이 없다",
            )
        return ArtifactUploadTarget(object_key=object_key, upload_url=upload_url)

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
                "auxiliaryFiles": list(submission.auxiliary_files),
            },
        )

    # ── W2 비교 요청(comparison_requests.py) ────────────────────────────────

    def list_pending_comparisons(self, *, limit: int = 50) -> list[PendingComparisonRequest]:
        response = self._client.get(
            f"{self._base_url}/v1/comparison-requests", params={"limit": limit}
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise CoreClientError(
                what="list-pending-comparisons",
                verdict="NON_JSON_RESPONSE",
                detail=response.text[:200],
            ) from exc
        if response.status_code != 200:
            raise CoreClientError(
                what="list-pending-comparisons",
                verdict=f"HTTP_{response.status_code}",
                detail=str(payload.get("detail")) if isinstance(payload, dict) else None,
            )
        return [
            PendingComparisonRequest(request_id=item["requestId"]) for item in payload["requests"]
        ]

    def acquire_comparison_lease(self, request_id: str) -> None:
        self._post(
            f"/v1/comparison-requests/{request_id}/lease",
            what="comparison-lease",
            ok=frozenset({"LEASED", "LEASE_RENEWED"}),
        )

    def get_comparison_input(self, request_id: str) -> ComparisonInput:
        response = self._client.get(f"{self._base_url}/v1/comparison-requests/{request_id}/input")
        try:
            payload = response.json()
        except ValueError as exc:
            raise CoreClientError(
                what="comparison-input", verdict="NON_JSON_RESPONSE", detail=response.text[:200]
            ) from exc
        if payload.get("verdict") != "INPUT_READY":
            raise CoreClientError(
                what="comparison-input",
                verdict=str(payload.get("verdict")),
                detail=payload.get("detail"),
            )
        data = payload["input"]

        def _ref(key: str) -> ArtifactRef | None:
            raw = data.get(key)
            if raw is None:
                return None
            return ArtifactRef(job_id=raw["jobId"], artifact_id=raw["artifactId"])

        return ComparisonInput(
            request_id=data["requestId"],
            mission_id=data["missionId"],
            status=data["status"],
            point_cloud_baseline=_ref("pointCloudBaseline"),
            point_cloud_baseline_url=data.get("pointCloudBaselineUrl"),
            point_cloud_current=_ref("pointCloudCurrent"),
            point_cloud_current_url=data.get("pointCloudCurrentUrl"),
            dsm_baseline=_ref("dsmBaseline"),
            dsm_baseline_url=data.get("dsmBaselineUrl"),
            dsm_current=_ref("dsmCurrent"),
            dsm_current_url=data.get("dsmCurrentUrl"),
            zones=data.get("zones"),
            zone_crs=data.get("zoneCrs"),
        )

    def transition_comparison(
        self, request_id: str, target: str, *, detail: str | None = None
    ) -> None:
        self._post(
            f"/v1/comparison-requests/{request_id}/transitions",
            what=f"comparison-transition→{target}",
            ok="TRANSITIONED",
            json={"targetStatus": target, "detail": detail},
        )

    def submit_change_detection(self, mission_id: str, result: ChangeDetectionResult) -> None:
        self._post(
            f"/v1/missions/{mission_id}/change-detection",
            what=f"change-detection:{result.change_detection_id}",
            ok="RECORDED",
            json=result.model_dump(by_alias=True, mode="json", exclude_none=False),
        )

    def submit_volume_change(self, mission_id: str, report: VolumeChangeReport) -> None:
        self._post(
            f"/v1/missions/{mission_id}/volume-changes",
            what=f"volume-change:{report.volume_change_id}",
            ok="RECORDED",
            json=report.model_dump(by_alias=True, mode="json", exclude_none=False),
        )

    def close(self) -> None:
        self._client.close()


__all__ = [
    "ArtifactSubmission",
    "ComparisonInput",
    "CoreClient",
    "CoreClientError",
    "HttpCoreClient",
    "JobInput",
    "JobInputMedia",
    "MeasuredImage",
    "PendingComparisonRequest",
    "PendingJob",
]
