"""``HttpCoreClient`` 의 verdict 번역 계약 (services/processing-controller).

``test_worker.py`` 는 ``CoreClient`` **포트**를 가짜로 갈아끼워 오케스트레이션
순서를 시험한다 — 그 가짜는 HTTP 왕복도 verdict 문자열 매칭도 하지 않는다.
그래서 ``HttpCoreClient`` 자신의 번역 로직에 있던 실제 버그가 그 테스트들을
전부 통과한 채로 남아 있었다: ``acquire_lease`` 가 처음엔 ``ok="LEASED"`` 하나만
받아들이게 짜여 있어, 정상적인 heartbeat 갱신(``LEASE_RENEWED``)마다 예외를
던졌다. 실제 Core+NodeODM 대상 완주 시도(2026-08-06)에서 ODM 폴링 도중
heartbeat 가 처음 도는 순간 곧바로 죽어서 드러났다.

이 파일은 ``httpx.MockTransport`` 로 **HTTP 봉투 번역**만 검증한다 — 네트워크도
컨테이너도 없이, "Core 가 이 verdict 를 주면 클라이언트가 무엇을 하는가"를
고정한다.
"""

from __future__ import annotations

import httpx
import pytest
from ksi_processing_controller.core_client import (
    ArtifactSubmission,
    CoreClientError,
    HttpCoreClient,
    JobInputMedia,
    MeasuredImage,
    PendingJob,
)

_BASE = "http://fake-core"


def _client(handler: httpx.MockTransport) -> HttpCoreClient:
    return HttpCoreClient(_BASE, token="worker-token", client=httpx.Client(transport=handler))


def _json_handler(status: int, body: dict) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


# ── list_pending ─────────────────────────────────────────────────────────


def test_list_pending_parses_job_ids_in_order() -> None:
    client = _client(
        _json_handler(
            200,
            {
                "jobs": [
                    {"jobId": "job-1", "issuedAt": "2026-08-10T00:00:00Z"},
                    {"jobId": "job-2", "issuedAt": "2026-08-10T00:00:01Z"},
                ]
            },
        )
    )
    assert client.list_pending() == [PendingJob(job_id="job-1"), PendingJob(job_id="job-2")]


def test_list_pending_empty_is_not_an_error() -> None:
    client = _client(_json_handler(200, {"jobs": []}))
    assert client.list_pending() == []


def test_list_pending_sends_limit_as_query_param() -> None:
    captured: dict = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["limit"] = request.url.params.get("limit")
        return httpx.Response(200, json={"jobs": []})

    client = _client(httpx.MockTransport(handle))
    client.list_pending(limit=7)
    assert captured["limit"] == "7"


def test_list_pending_forbidden_is_typed() -> None:
    """[음성] 사람 토큰(권한 없음)으로 부르면 403 이 CoreClientError 로 온다."""
    client = _client(_json_handler(403, {"detail": "권한이 부족하다"}))
    with pytest.raises(CoreClientError) as excinfo:
        client.list_pending()
    assert excinfo.value.verdict == "HTTP_403"


# ── lease — LEASED 와 LEASE_RENEWED 둘 다 성공이다 ───────────────────────────


def test_acquire_lease_accepts_leased() -> None:
    client = _client(_json_handler(201, {"verdict": "LEASED", "job": {}}))
    client.acquire_lease("job-1")  # 예외 없이 통과해야 한다


def test_acquire_lease_accepts_renewed() -> None:
    """[회귀] 실물에서 잡힌 버그 — heartbeat 갱신마다 예외가 났었다."""
    client = _client(_json_handler(200, {"verdict": "LEASE_RENEWED", "job": {}}))
    client.acquire_lease("job-1")  # 예외 없이 통과해야 한다


def test_acquire_lease_rejects_held_by_another() -> None:
    client = _client(
        _json_handler(409, {"verdict": "LEASE_HELD_BY_ANOTHER", "detail": "다른 워커"})
    )
    with pytest.raises(CoreClientError) as excinfo:
        client.acquire_lease("job-1")
    assert excinfo.value.verdict == "LEASE_HELD_BY_ANOTHER"
    assert excinfo.value.detail == "다른 워커"


# ── input ────────────────────────────────────────────────────────────────


def test_get_input_parses_the_full_shape() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "verdict": "INPUT_READY",
                "input": {
                    "jobId": "job-1", "missionId": "mission-1", "siteId": "site-1",
                    "status": "RUNNING", "provider": "odm", "engineVersion": "3.5.6",
                    "engineDigest": "sha256:" + "a" * 64, "executionLocus": "ksi_server_gpu",
                    "processingParams": {"pc-quality": "medium"},
                    "sourceBundleDigest": "sha256:" + "b" * 64,
                    "imageCount": 2, "siteCrs": "EPSG:32610",
                    "media": [
                        {
                            "mediaId": "img-1.jpg", "objectKey": "k1",
                            "downloadUrl": "http://s/1", "expiresAt": "2026-08-06T00:00:00Z",
                        }
                    ],
                },
            },
        )

    client = _client(httpx.MockTransport(handle))
    job_input = client.get_input("job-1")
    assert job_input.mission_id == "mission-1"
    assert job_input.site_crs == "EPSG:32610"
    assert job_input.media == (
        JobInputMedia(media_id="img-1.jpg", download_url="http://s/1"),
    )


def test_get_input_refuses_job_not_active() -> None:
    client = _client(
        _json_handler(409, {"verdict": "JOB_NOT_ACTIVE", "detail": "이미 끝난 작업"})
    )
    with pytest.raises(CoreClientError) as excinfo:
        client.get_input("job-1")
    assert excinfo.value.verdict == "JOB_NOT_ACTIVE"


# ── transition ───────────────────────────────────────────────────────────


def test_transition_success() -> None:
    client = _client(_json_handler(200, {"verdict": "TRANSITIONED", "job": {}}))
    client.transition("job-1", "RUNNING")  # 예외 없이 통과해야 한다


def test_transition_unbacked_success_is_typed() -> None:
    client = _client(
        _json_handler(409, {"verdict": "UNBACKED_SUCCESS", "detail": "산출물 없음"})
    )
    with pytest.raises(CoreClientError) as excinfo:
        client.transition("job-1", "SUCCEEDED")
    assert excinfo.value.verdict == "UNBACKED_SUCCESS"


# ── verify ───────────────────────────────────────────────────────────────


def test_verify_success() -> None:
    client = _client(_json_handler(201, {"verdict": "VERIFIED", "bundle": {}}))
    client.verify_source_media(
        "mission-1",
        [MeasuredImage(media_id="a.jpg", sha256="0" * 64, size_bytes=1, width=1, height=1)],
    )


def test_verify_accepts_already_verified() -> None:
    """[회귀] 실물에서 잡힌 버그 — 재시도 작업이 이미 검증된 번들에 다시 보고하면 예외가 났었다.

    verify 는 작업이 아니라 **미션** 단위다. 첫 시도가 실패한 뒤 새 작업이
    발급되면(같은 미션) 이미 검증된 번들에 다시 실측을 보고하게 되고, 그때
    Core 는 ALREADY_VERIFIED 로 답한다 — 이것도 성공이다.
    """
    client = _client(_json_handler(200, {"verdict": "ALREADY_VERIFIED", "bundle": {}}))
    client.verify_source_media(
        "mission-1",
        [MeasuredImage(media_id="a.jpg", sha256="0" * 64, size_bytes=1, width=1, height=1)],
    )  # 예외 없이 통과해야 한다


def test_verify_mismatch_is_typed() -> None:
    client = _client(
        _json_handler(422, {"verdict": "MISMATCH", "detail": "어긋남", "mismatched": ["a.jpg"]})
    )
    with pytest.raises(CoreClientError) as excinfo:
        client.verify_source_media(
            "mission-1",
            [MeasuredImage(media_id="a.jpg", sha256="0" * 64, size_bytes=1, width=1, height=1)],
        )
    assert excinfo.value.verdict == "MISMATCH"


def test_verify_sends_measured_values_not_reissued_claims() -> None:
    """[핵심] 워커가 실측한 값이 그대로 요청 본문에 실린다 — 다른 값으로 안 바뀐다."""
    captured: dict = {}

    def handle(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"verdict": "VERIFIED"})

    client = _client(httpx.MockTransport(handle))
    client.verify_source_media(
        "mission-1",
        [MeasuredImage(media_id="a.jpg", sha256="f" * 64, size_bytes=999, width=10, height=20)],
    )
    measurement = captured["body"]["measurements"][0]
    assert measurement == {
        "mediaId": "a.jpg", "sha256": "f" * 64, "bytes": 999, "width": 10, "height": 20,
    }


# ── artifact ─────────────────────────────────────────────────────────────


def test_register_artifact_success() -> None:
    client = _client(_json_handler(201, {"verdict": "ARTIFACT_REGISTERED", "artifact": {}}))
    client.register_artifact(
        "job-1",
        ArtifactSubmission(
            artifact_id="point-cloud", kind="point_cloud", authority="source",
            derived_from=(), digest="sha256:" + "a" * 64, format="laz",
            crs="EPSG:32610", gsd=None,
        ),
    )


def test_register_artifact_does_not_send_a_lineage_anchor_field() -> None:
    """[핵심] 요청 본문에 sourceDigest/jobId 를 실을 자리가 없다 — Core 가 원장에서 채운다."""
    captured: dict = {}

    def handle(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"verdict": "ARTIFACT_REGISTERED"})

    client = _client(httpx.MockTransport(handle))
    client.register_artifact(
        "job-1",
        ArtifactSubmission(
            artifact_id="mesh", kind="mesh", authority="derived",
            derived_from=("point-cloud",), digest="sha256:" + "b" * 64, format="obj",
            crs="EPSG:32610", gsd=None,
        ),
    )
    assert set(captured["body"]) == {
        "artifactId", "kind", "authority", "derivedFrom", "digest", "format", "crs", "gsd",
        "auxiliaryFiles",
    }


def test_register_artifact_contract_violation_is_typed() -> None:
    client = _client(
        _json_handler(422, {"verdict": "ARTIFACT_CONTRACT_VIOLATION", "detail": "gsd 필수"})
    )
    with pytest.raises(CoreClientError) as excinfo:
        client.register_artifact(
            "job-1",
            ArtifactSubmission(
                artifact_id="dsm", kind="dsm", authority="derived",
                derived_from=("point-cloud",), digest="sha256:" + "c" * 64, format="cog",
                crs="EPSG:32610", gsd=None,
            ),
        )
    assert excinfo.value.verdict == "ARTIFACT_CONTRACT_VIOLATION"


# ── 공통: NON_JSON_RESPONSE ──────────────────────────────────────────────


def test_non_json_response_is_typed_not_a_raw_parse_error() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    client = _client(httpx.MockTransport(handle))
    with pytest.raises(CoreClientError) as excinfo:
        client.transition("job-1", "FAILED")
    assert excinfo.value.verdict == "NON_JSON_RESPONSE"


def test_bearer_token_is_sent() -> None:
    captured: dict = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"verdict": "TRANSITIONED"})

    client = HttpCoreClient(
        _BASE,
        token="secret-worker-token",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    client.transition("job-1", "FAILED")
    assert captured["auth"] == "Bearer secret-worker-token"
