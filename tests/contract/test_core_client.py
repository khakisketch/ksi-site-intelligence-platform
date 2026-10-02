"""``HttpCoreClient`` 의 verdict 번역 계약 (services/processing-controller).

``test_worker.py`` 는 ``CoreClient`` **포트**를 가짜로 갈아끼워 오케스트레이션
순서를 시험한다 — 그 가짜는 HTTP 왕복도 verdict 문자열 매칭도 하지 않는다.
그래서 ``HttpCoreClient`` 자신의 번역 로직에 있던 실제 버그가 그 테스트들을
전부 통과한 채로 남아 있었다: ``acquire_lease`` 가 처음엔 ``ok="LEASED"`` 하나만
받아들이게 짜여 있어, 정상적인 heartbeat 갱신(``LEASE_RENEWED``)마다 예외를
던졌다. 실제 Core+NodeODM 대상 완주 시도(2026-08-06)에서 ODM 폴링 도중
heartbeat 가 처음 도는 순간 곧바로 죽어서 드러났다.

대부분은 ``httpx.MockTransport`` 로 **HTTP 봉투 번역**만 검증한다 — 네트워크도
컨테이너도 없이, "Core 가 이 verdict 를 주면 클라이언트가 무엇을 하는가"를
고정한다. 다만 사람의 ``CANCELLED`` 전이는 Core 의 optional-fence parser까지
실제로 태워야 하므로, 한 회귀는 in-process Core 앱을 직접 주입한다.
"""

from __future__ import annotations

import threading
from pathlib import Path

import httpx
import pytest
import test_processing_jobs as processing_jobs  # noqa: E402 -- contract fixture reuse
from ksi_event_contracts.comparison_policy import current_comparison_policy
from ksi_event_contracts.vertical_reference import (
    VerticalDatum,
    VerticalReference,
    VerticalReferenceSource,
)
from ksi_processing_controller.comparison_worker import LeaseHeartbeat
from ksi_processing_controller.core_client import (
    ArtifactObjectBinding,
    ArtifactSubmission,
    CheckpointValidationMeasurement,
    CoreClientError,
    HttpCoreClient,
    JobInputMedia,
    MeasuredImage,
    PendingJob,
)
from ksi_processing_controller.observability import bind_correlation_id

_BASE = "http://fake-core"


def _client(handler: httpx.MockTransport) -> HttpCoreClient:
    return HttpCoreClient(_BASE, token="worker-token", client=httpx.Client(transport=handler))


def _leased_client(
    handler: httpx.MockTransport,
    *,
    resource_id: str = "job-1",
    work_kind: str = "processing",
) -> HttpCoreClient:
    """Acquire the required Core lease before testing a resource-scoped route."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/lease"):
            return httpx.Response(
                201,
                json={"verdict": "LEASED"},
                headers={
                    "X-KSI-Worker-Instance-Id": request.headers[
                        "X-KSI-Worker-Instance-Id"
                    ],
                    "X-KSI-Lease-Acquisition-Id": request.headers[
                        "X-KSI-Lease-Acquisition-Id"
                    ],
                    "X-KSI-Lease-Generation": "1",
                },
            )
        return handler.handle_request(request)

    client = _client(httpx.MockTransport(handle))
    if work_kind == "processing":
        client.acquire_lease(resource_id)
    elif work_kind == "comparison":
        client.acquire_comparison_lease(resource_id)
    else:  # pragma: no cover - test helper callers declare supported kinds.
        raise ValueError(f"unsupported work kind: {work_kind}")
    return client


def _json_handler(status: int, body: dict) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


def test_injected_worker_instance_identity_must_be_uuidv4() -> None:
    with pytest.raises(ValueError, match="UUIDv4"):
        HttpCoreClient(
            _BASE,
            token="worker-token",
            client=httpx.Client(transport=_json_handler(200, {})),
            worker_instance_id="11111111-1111-1111-8111-111111111111",
        )


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


def test_bound_work_correlation_is_sent_on_every_core_http_method() -> None:
    """Foreground GET/POST calls carry the runner's validated work id to Core."""
    observed: list[tuple[str, str | None]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        observed.append((request.method, request.headers.get("X-Request-Id")))
        if request.method == "GET":
            return httpx.Response(200, json={"jobs": []})
        return httpx.Response(
            201,
            json={"verdict": "LEASED", "job": {}},
            headers={
                "X-KSI-Worker-Instance-Id": request.headers["X-KSI-Worker-Instance-Id"],
                "X-KSI-Lease-Acquisition-Id": request.headers["X-KSI-Lease-Acquisition-Id"],
                "X-KSI-Lease-Generation": "1",
            },
        )

    client = _client(httpx.MockTransport(handle))
    with bind_correlation_id("mission-1-proc1"):
        assert client.list_pending() == []
        client.acquire_lease("mission-1-proc1")

    assert observed == [
        ("GET", "mission-1-proc1"),
        ("POST", "mission-1-proc1"),
    ]


def test_unbound_client_does_not_invent_a_work_correlation_header() -> None:
    observed: list[str | None] = []

    def handle(request: httpx.Request) -> httpx.Response:
        observed.append(request.headers.get("X-Request-Id"))
        return httpx.Response(200, json={"jobs": []})

    client = _client(httpx.MockTransport(handle))
    assert client.list_pending() == []
    assert observed == [None]


def test_heartbeat_rebinds_correlation_before_renewing_core_lease() -> None:
    """New threads do not inherit contextvars, so renewals must bind explicitly."""
    seen = threading.Event()
    headers: list[str | None] = []

    def handle(request: httpx.Request) -> httpx.Response:
        headers.append(request.headers.get("X-Request-Id"))
        seen.set()
        return httpx.Response(200, json={"verdict": "LEASE_RENEWED", "job": {}})

    client = _client(httpx.MockTransport(handle))
    with bind_correlation_id("mission-1-cmp1"):
        heartbeat = LeaseHeartbeat(
            lambda: client.acquire_lease("mission-1-cmp1"),
            "mission-1-cmp1",
            interval_seconds=0.01,
            now_message=lambda _message: None,
        )
        heartbeat.start()
        assert seen.wait(timeout=1.0), "heartbeat did not make its Core lease call"
        heartbeat.stop()

    assert headers == ["mission-1-cmp1"]


@pytest.mark.parametrize("malformed", ["", "contains space", "bad\nheader", "x" * 129])
def test_correlation_binding_rejects_unsafe_header_values(malformed: str) -> None:
    with pytest.raises(ValueError, match="correlation id"), bind_correlation_id(malformed):
        pass


def test_list_pending_forbidden_is_typed() -> None:
    """[음성] 사람 토큰(권한 없음)으로 부르면 403 이 CoreClientError 로 온다."""
    client = _client(_json_handler(403, {"detail": "권한이 부족하다"}))
    with pytest.raises(CoreClientError) as excinfo:
        client.list_pending()
    assert excinfo.value.verdict == "HTTP_403"


def test_checkpoint_validation_queue_and_measurement_wire_shape() -> None:
    """The worker gets only presigned inputs and sends only measured metrics."""
    captured: dict[str, object] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        import json

        if request.method == "GET":
            captured["params"] = dict(request.url.params)
            return httpx.Response(
                200,
                json={
                    "validations": [
                        {
                            "validationId": "cv-1",
                            "checkpointDownloadUrl": "https://storage/checkpoints.csv",
                            "dsmDownloadUrl": "https://storage/dsm.tif",
                            "checkpointCrs": "EPSG:5186",
                            "checkpointVerticalReference": {
                                "datum": "ellipsoidal",
                                "basis": "independent survey",
                                "source": "user_declared",
                            },
                            "dsmCrs": "EPSG:5186",
                            "dsmVerticalReference": {
                                "datum": "ellipsoidal",
                                "basis": "ODM pipeline output",
                                "source": "pipeline_declared",
                            },
                        }
                    ]
                },
            )
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"verdict": "VALIDATED"})

    client = _client(httpx.MockTransport(handle))
    queued = client.list_pending_checkpoint_validations(limit=7)
    assert queued[0].validation_id == "cv-1"
    assert queued[0].checkpoint_crs == "EPSG:5186"
    assert captured["params"] == {"status": "SEALED", "limit": "7"}
    verdict = client.report_checkpoint_validation_observation(
        "cv-1",
        CheckpointValidationMeasurement(
            checkpoint_sha256="a" * 64,
            checkpoint_size_bytes=42,
            dsm_digest="sha256:" + "b" * 64,
            dsm_crs="EPSG:5186",
            point_count=3,
            mean_error_m=0.1,
            mae_m=0.2,
            rmse_m=0.3,
            max_abs_error_m=0.4,
        ),
    )
    assert verdict == "VALIDATED"
    assert captured["path"] == "/v1/checkpoint-validations/cv-1/observations"
    assert captured["body"] == {
        "checkpointSha256": "a" * 64,
        "checkpointSizeBytes": 42,
        "dsmDigest": "sha256:" + "b" * 64,
        "dsmCrs": "EPSG:5186",
        "pointCount": 3,
        "meanErrorM": 0.1,
        "maeM": 0.2,
        "rmseM": 0.3,
        "maxAbsErrorM": 0.4,
    }


@pytest.mark.parametrize(
    ("checkpoint_crs", "dsm_crs", "checkpoint_source"),
    [
        ("EPSG:5186", "EPSG:5187", "user_declared"),
        ("EPSG:4326", "EPSG:4326", "user_declared"),
        ("EPSG:5186", "EPSG:5186", "pipeline_declared"),
    ],
)
def test_checkpoint_queue_rejects_non_comparable_server_snapshots(
    checkpoint_crs: str, dsm_crs: str, checkpoint_source: str
) -> None:
    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "validations": [
                    {
                        "validationId": "cv-1",
                        "checkpointDownloadUrl": "https://storage/checkpoints.csv",
                        "dsmDownloadUrl": "https://storage/dsm.tif",
                        "checkpointCrs": checkpoint_crs,
                        "checkpointVerticalReference": {
                            "datum": "ellipsoidal",
                            "basis": "survey",
                            "source": checkpoint_source,
                        },
                        "dsmCrs": dsm_crs,
                        "dsmVerticalReference": {
                            "datum": "ellipsoidal",
                            "basis": "pipeline",
                            "source": "pipeline_declared",
                        },
                    }
                ]
            },
        )

    client = _client(httpx.MockTransport(handle))
    with pytest.raises(CoreClientError) as excinfo:
        client.list_pending_checkpoint_validations()
    assert excinfo.value.verdict == "MALFORMED_PENDING_VALIDATION"


# ── lease — LEASED 와 LEASE_RENEWED 둘 다 성공이다 ───────────────────────────


def test_acquire_lease_accepts_leased() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"verdict": "LEASED", "job": {}}, headers={
            "X-KSI-Worker-Instance-Id": request.headers["X-KSI-Worker-Instance-Id"],
            "X-KSI-Lease-Acquisition-Id": request.headers["X-KSI-Lease-Acquisition-Id"],
            "X-KSI-Lease-Generation": "1",
        })
    client = _client(httpx.MockTransport(handle))
    client.acquire_lease("job-1")  # 예외 없이 통과해야 한다


def test_acquire_lease_accepts_renewed() -> None:
    """[회귀] 실물에서 잡힌 버그 — heartbeat 갱신마다 예외가 났었다."""
    calls = 0
    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            201 if calls == 1 else 200,
            json={"verdict": "LEASED" if calls == 1 else "LEASE_RENEWED", "job": {}},
            headers={
                "X-KSI-Worker-Instance-Id": request.headers["X-KSI-Worker-Instance-Id"],
                "X-KSI-Lease-Acquisition-Id": request.headers["X-KSI-Lease-Acquisition-Id"],
                "X-KSI-Lease-Generation": "1",
            },
        )
    client = _client(httpx.MockTransport(handle))
    client.acquire_lease("job-1")
    client.acquire_lease("job-1")


def test_lost_claim_response_reuses_acquisition_identity_without_self_fencing() -> None:
    """A transport retry repeats CLAIM R; it never manufactures generation N+1."""
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(
            201,
            json={"verdict": "LEASED"},
            headers={
                "X-KSI-Worker-Instance-Id": request.headers["X-KSI-Worker-Instance-Id"],
                "X-KSI-Lease-Acquisition-Id": request.headers["X-KSI-Lease-Acquisition-Id"],
                "X-KSI-Lease-Generation": "7",
            },
        )

    client = _client(httpx.MockTransport(handle))
    with pytest.raises(httpx.ReadTimeout):
        client.acquire_lease("job-1")
    handle_result = client.acquire_lease("job-1")

    assert handle_result.lease_generation == 7
    assert [request.headers["X-KSI-Lease-Mode"] for request in requests] == ["CLAIM", "CLAIM"]
    assert (
        requests[0].headers["X-KSI-Lease-Acquisition-Id"]
        == requests[1].headers["X-KSI-Lease-Acquisition-Id"]
    )


def test_new_claim_for_a_distinct_work_kind_has_no_inherited_generation() -> None:
    """Each first CLAIM starts without a fence, even on a shared client."""
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            201,
            json={"verdict": "LEASED"},
            headers={
                "X-KSI-Worker-Instance-Id": request.headers["X-KSI-Worker-Instance-Id"],
                "X-KSI-Lease-Acquisition-Id": request.headers[
                    "X-KSI-Lease-Acquisition-Id"
                ],
                "X-KSI-Lease-Generation": str(len(requests)),
            },
        )

    client = _client(httpx.MockTransport(handle))
    client.acquire_lease("job-1")
    client.acquire_comparison_lease("comparison-1")

    assert [request.headers["X-KSI-Lease-Mode"] for request in requests] == [
        "CLAIM",
        "CLAIM",
    ]
    assert [request.headers.get("X-KSI-Lease-Generation") for request in requests] == [
        None,
        None,
    ]


def test_successful_terminal_transition_retires_only_its_exact_lease() -> None:
    """Completing A cannot retire B, and A's next poll must make a fresh CLAIM."""
    requests: list[httpx.Request] = []
    initial_acquisition_ids: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/transitions"):
            return httpx.Response(200, json={"verdict": "TRANSITIONED"})

        job_id = request.url.path.split("/")[-2]
        acquisition_id = request.headers["X-KSI-Lease-Acquisition-Id"]
        initial_acquisition_ids.setdefault(job_id, acquisition_id)
        return httpx.Response(
            201 if request.headers["X-KSI-Lease-Mode"] == "CLAIM" else 200,
            json={
                "verdict": (
                    "LEASED"
                    if request.headers["X-KSI-Lease-Mode"] == "CLAIM"
                    else "LEASE_RENEWED"
                )
            },
            headers={
                "X-KSI-Worker-Instance-Id": request.headers["X-KSI-Worker-Instance-Id"],
                "X-KSI-Lease-Acquisition-Id": acquisition_id,
                "X-KSI-Lease-Generation": "1",
            },
        )

    client = _client(httpx.MockTransport(handle))
    first = client.acquire_lease("job-1")
    second = client.acquire_lease("job-2")
    client.transition("job-1", "SUCCEEDED")
    recovered = client.acquire_lease("job-1")
    renewed = client.renew_lease("job-2")

    transition = requests[2]
    assert transition.headers["X-KSI-Lease-Acquisition-Id"] == first.lease_acquisition_id
    assert transition.headers["X-KSI-Lease-Generation"] == "1"
    assert requests[3].headers["X-KSI-Lease-Mode"] == "CLAIM"
    assert recovered.lease_acquisition_id != first.lease_acquisition_id
    assert requests[4].headers["X-KSI-Lease-Mode"] == "RENEW"
    assert renewed.lease_acquisition_id == second.lease_acquisition_id


def test_lost_terminal_response_keeps_the_lease_for_an_exact_retry() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/transitions"):
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(
            201 if len(requests) == 1 else 200,
            json={"verdict": "LEASED" if len(requests) == 1 else "LEASE_RENEWED"},
            headers={
                "X-KSI-Worker-Instance-Id": request.headers["X-KSI-Worker-Instance-Id"],
                "X-KSI-Lease-Acquisition-Id": request.headers[
                    "X-KSI-Lease-Acquisition-Id"
                ],
                "X-KSI-Lease-Generation": "1",
            },
        )

    client = _client(httpx.MockTransport(handle))
    lease = client.acquire_lease("job-1")
    with pytest.raises(httpx.ReadTimeout):
        client.transition("job-1", "FAILED")
    renewed = client.renew_lease("job-1")

    assert requests[1].headers["X-KSI-Lease-Acquisition-Id"] == lease.lease_acquisition_id
    assert requests[1].headers["X-KSI-Lease-Generation"] == "1"
    assert requests[2].headers["X-KSI-Lease-Mode"] == "RENEW"
    assert renewed == lease


def test_intermediate_artifact_registration_keeps_its_processing_lease() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/artifacts"):
            return httpx.Response(201, json={"verdict": "ARTIFACT_REGISTERED"})
        return httpx.Response(
            201 if len(requests) == 1 else 200,
            json={"verdict": "LEASED" if len(requests) == 1 else "LEASE_RENEWED"},
            headers={
                "X-KSI-Worker-Instance-Id": request.headers["X-KSI-Worker-Instance-Id"],
                "X-KSI-Lease-Acquisition-Id": request.headers[
                    "X-KSI-Lease-Acquisition-Id"
                ],
                "X-KSI-Lease-Generation": "1",
            },
        )

    client = _client(httpx.MockTransport(handle))
    lease = client.acquire_lease("job-1")
    client.register_artifact(
        "job-1",
        ArtifactSubmission(
            artifact_id="artifact-1",
            kind="point_cloud",
            authority="source",
            derived_from=(),
            digest="sha256:" + "a" * 64,
            format="las",
            crs="EPSG:5186",
            gsd=None,
        ),
    )
    client.renew_lease("job-1")

    assert requests[1].headers["X-KSI-Lease-Acquisition-Id"] == lease.lease_acquisition_id
    assert requests[1].headers["X-KSI-Lease-Generation"] == "1"
    assert requests[2].headers["X-KSI-Lease-Mode"] == "RENEW"


def test_stale_renew_closes_local_handle_and_next_poll_uses_a_new_claim() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 2:
            return httpx.Response(
                409,
                json={"verdict": "STALE_LEASE_GENERATION", "detail": "superseded"},
            )
        return httpx.Response(
            201,
            json={"verdict": "LEASED"},
            headers={
                "X-KSI-Worker-Instance-Id": request.headers[
                    "X-KSI-Worker-Instance-Id"
                ],
                "X-KSI-Lease-Acquisition-Id": request.headers[
                    "X-KSI-Lease-Acquisition-Id"
                ],
                "X-KSI-Lease-Generation": "1" if len(requests) == 1 else "3",
            },
        )

    client = _client(httpx.MockTransport(handle))
    first = client.acquire_lease("job-1")
    with pytest.raises(CoreClientError, match="STALE_LEASE_GENERATION"):
        client.renew_lease("job-1")
    recovered = client.acquire_lease("job-1")

    assert [request.headers["X-KSI-Lease-Mode"] for request in requests] == [
        "CLAIM",
        "RENEW",
        "CLAIM",
    ]
    assert recovered.lease_generation == 3
    assert recovered.lease_acquisition_id != first.lease_acquisition_id


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

    client = _leased_client(httpx.MockTransport(handle))
    job_input = client.get_input("job-1")
    assert job_input.mission_id == "mission-1"
    assert job_input.site_crs == "EPSG:32610"
    assert job_input.media == (
        JobInputMedia(media_id="img-1.jpg", download_url="http://s/1"),
    )


def test_get_input_refuses_job_not_active() -> None:
    client = _leased_client(
        _json_handler(409, {"verdict": "JOB_NOT_ACTIVE", "detail": "이미 끝난 작업"})
    )
    with pytest.raises(CoreClientError) as excinfo:
        client.get_input("job-1")
    assert excinfo.value.verdict == "JOB_NOT_ACTIVE"


# ── transition ───────────────────────────────────────────────────────────


def test_transition_success() -> None:
    client = _leased_client(_json_handler(200, {"verdict": "TRANSITIONED", "job": {}}))
    client.transition("job-1", "RUNNING")  # 예외 없이 통과해야 한다


def test_transition_unbacked_success_is_typed() -> None:
    client = _leased_client(
        _json_handler(409, {"verdict": "UNBACKED_SUCCESS", "detail": "산출물 없음"})
    )
    with pytest.raises(CoreClientError) as excinfo:
        client.transition("job-1", "SUCCEEDED")
    assert excinfo.value.verdict == "UNBACKED_SUCCESS"


def test_admin_cancel_omits_all_lease_identity_headers_in_real_core(tmp_path: Path) -> None:
    """Operator cancellation reaches Core without a malformed partial worker fence."""
    app_client = processing_jobs._client(tmp_path)  # noqa: SLF001 -- contract fixture reuse
    job_id = app_client.post(
        f"/v1/missions/{processing_jobs._MISSION_ID}/processing-jobs",  # noqa: SLF001
        json=processing_jobs._issue_payload(),  # noqa: SLF001
    ).json()["job"]["jobId"]
    for header in (
        "X-KSI-Worker-Instance-Id",
        "X-KSI-Lease-Acquisition-Id",
        "X-KSI-Lease-Generation",
    ):
        app_client.headers.pop(header, None)

    client = HttpCoreClient(
        "http://core.test",
        token=processing_jobs._ADMIN_TOKEN,  # noqa: SLF001
        client=app_client,
    )
    client.transition(job_id, "CANCELLED")

    response = app_client.get(f"/v1/processing-jobs/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"


# ── verify ───────────────────────────────────────────────────────────────


def test_verify_success() -> None:
    client = _leased_client(_json_handler(201, {"verdict": "VERIFIED", "bundle": {}}))
    client.verify_source_media(
        "job-1",
        [MeasuredImage(media_id="a.jpg", sha256="0" * 64, size_bytes=1, width=1, height=1)],
    )


def test_verify_accepts_already_verified() -> None:
    """[회귀] 실물에서 잡힌 버그 — 재시도 작업이 이미 검증된 번들에 다시 보고하면 예외가 났었다.

    verify 는 jobId로 lease를 결속한다. 첫 시도가 실패한 뒤 새 작업이
    발급되면(같은 미션) 이미 검증된 번들에 다시 실측을 보고하게 되고, 그때
    Core 는 ALREADY_VERIFIED 로 답한다 — 이것도 성공이다.
    """
    client = _leased_client(
        _json_handler(200, {"verdict": "ALREADY_VERIFIED", "bundle": {}})
    )
    client.verify_source_media(
        "job-1",
        [MeasuredImage(media_id="a.jpg", sha256="0" * 64, size_bytes=1, width=1, height=1)],
    )  # 예외 없이 통과해야 한다


def test_verify_mismatch_is_typed() -> None:
    client = _leased_client(
        _json_handler(422, {"verdict": "MISMATCH", "detail": "어긋남", "mismatched": ["a.jpg"]})
    )
    with pytest.raises(CoreClientError) as excinfo:
        client.verify_source_media(
            "job-1",
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

    client = _leased_client(httpx.MockTransport(handle))
    client.verify_source_media(
        "job-1",
        [MeasuredImage(media_id="a.jpg", sha256="f" * 64, size_bytes=999, width=10, height=20)],
    )
    measurement = captured["body"]["measurements"][0]
    assert measurement == {
        "mediaId": "a.jpg", "sha256": "f" * 64, "bytes": 999, "width": 10, "height": 20,
        "captureTime": {"capturedAt": None, "source": "NONE", "status": "UNAVAILABLE"},
    }


# ── artifact ─────────────────────────────────────────────────────────────


def test_register_artifact_success() -> None:
    client = _leased_client(
        _json_handler(201, {"verdict": "ARTIFACT_REGISTERED", "artifact": {}})
    )
    client.register_artifact(
        "job-1",
        ArtifactSubmission(
            artifact_id="point-cloud", kind="point_cloud", authority="source",
            derived_from=(), digest="sha256:" + "a" * 64, format="laz",
            crs="EPSG:32610", gsd=None,
        ),
    )


def test_register_artifact_bindings_match_the_core_request_model() -> None:
    """Real serialized bytes must satisfy Core, not just a capture-only transport."""
    import json

    from ksi_core.processing_jobs import ProcessingArtifactRequest

    captured: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(201, json={"verdict": "ARTIFACT_REGISTERED", "artifact": {}})

    def binding(name: str) -> ArtifactObjectBinding:
        return ArtifactObjectBinding(
            name=name, object_key=f"objects/{name}", sha256="sha256:" + "b" * 64,
            size_bytes=10, content_type="application/octet-stream",
        )

    client = _leased_client(httpx.MockTransport(handle))
    client.register_artifact(
        "job-1",
        ArtifactSubmission(
            artifact_id="mesh", kind="mesh", authority="derived", derived_from=("point-cloud",),
            digest="sha256:" + "b" * 64, format="obj", crs=None, gsd=None,
            auxiliary_files=("model.mtl",), primary_object=binding("model.obj"),
            auxiliary_objects=(binding("model.mtl"),),
        ),
    )
    request = ProcessingArtifactRequest.model_validate(captured[0])
    assert request.primary_object.object_key == "objects/model.obj"
    assert set(request.auxiliary_objects) == {"model.mtl"}
    assert request.auxiliary_objects["model.mtl"].object_key == "objects/model.mtl"


def test_register_artifact_does_not_send_a_lineage_anchor_field() -> None:
    """[핵심] 요청 본문에 sourceDigest/jobId 를 실을 자리가 없다 — Core 가 원장에서 채운다."""
    captured: dict = {}

    def handle(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(201, json={"verdict": "ARTIFACT_REGISTERED"})

    client = _leased_client(httpx.MockTransport(handle))
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


def test_register_artifact_sends_vertical_reference_only_when_declared() -> None:
    """[핵심] 수직기준을 모르면 그 키를 아예 보내지 않는다 — 옛 워커의 payload 와
    바이트가 같다. 알면 근거·귀속까지 통째로 보낸다(datum 하나만 보내지 않는다)."""
    bodies: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        import json

        bodies.append(json.loads(request.content))
        return httpx.Response(201, json={"verdict": "ARTIFACT_REGISTERED"})

    def submission(reference: VerticalReference | None) -> ArtifactSubmission:
        return ArtifactSubmission(
            artifact_id="dsm", kind="dsm", authority="derived", derived_from=("point-cloud",),
            digest="sha256:" + "d" * 64, format="cog", crs="EPSG:5186", gsd=0.05,
            vertical_reference=reference,
        )

    client = _leased_client(httpx.MockTransport(handle))
    client.register_artifact("job-1", submission(None))
    client.register_artifact(
        "job-1",
        submission(
            VerticalReference(
                datum=VerticalDatum.ELLIPSOIDAL_NATIVE,
                basis="ODM 이 RTK 타원체고를 변환 없이 그대로 출력",
                source=VerticalReferenceSource.PIPELINE_DECLARED,
            )
        ),
    )
    assert "verticalReference" not in bodies[0]
    assert bodies[1]["verticalReference"] == {
        "datum": "ellipsoidal_native",
        "basis": "ODM 이 RTK 타원체고를 변환 없이 그대로 출력",
        "source": "pipeline_declared",
    }


def test_register_artifact_contract_violation_is_typed() -> None:
    client = _leased_client(
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


# ── get_comparison_input: 수직기준 전달 ──────────────────────────────────


def _comparison_input_body(vertical_reference: dict | None) -> dict:
    return {
        "verdict": "INPUT_READY",
        "input": {
            "requestId": "mission-1-cmp1",
            "missionId": "mission-1",
            "status": "QUEUED",
            "policy": current_comparison_policy().model_dump(by_alias=True, mode="json"),
            "pointCloudBaseline": None, "pointCloudBaselineUrl": None,
            "pointCloudCurrent": None, "pointCloudCurrentUrl": None,
            "dsmBaseline": {"jobId": "job-a", "artifactId": "dsm"},
            "dsmBaselineUrl": "https://fake-storage/baseline.tif",
            "dsmCurrent": {"jobId": "job-b", "artifactId": "dsm"},
            "dsmCurrentUrl": "https://fake-storage/current.tif",
            "zones": None, "zoneCrs": None,
            "dsmBaselineVerticalReference": vertical_reference,
            "dsmCurrentVerticalReference": vertical_reference,
        },
    }


def test_comparison_input_parses_the_declared_vertical_references() -> None:
    """산출물이 선언한 수직기준이 워커까지 값 그대로 도달한다 — 워커가 리포트의
    verticalDatum 을 상수로 가정하지 않게 하는 유일한 경로다."""
    client = _leased_client(
        _json_handler(
            200,
            _comparison_input_body(
                {
                    "datum": "ellipsoidal_native",
                    "basis": "ODM 이 RTK 타원체고를 변환 없이 그대로 출력",
                    "source": "pipeline_declared",
                }
            ),
        ),
        resource_id="mission-1-cmp1",
        work_kind="comparison",
    )
    comparison_input = client.get_comparison_input("mission-1-cmp1")
    reference = comparison_input.dsm_baseline_vertical_reference
    assert reference is not None
    assert reference.datum is VerticalDatum.ELLIPSOIDAL_NATIVE
    assert reference.source is VerticalReferenceSource.PIPELINE_DECLARED
    assert comparison_input.dsm_current_vertical_reference == reference


def test_comparison_input_keeps_a_missing_vertical_reference_as_none() -> None:
    """[회귀] 수직기준 미상(옛 산출물)은 None 으로 남는다 — 클라이언트가 어떤
    기본값도 채우지 않는다(채우면 워커의 레거시 경고가 영영 안 뜬다)."""
    client = _leased_client(
        _json_handler(200, _comparison_input_body(None)),
        resource_id="mission-1-cmp1",
        work_kind="comparison",
    )
    comparison_input = client.get_comparison_input("mission-1-cmp1")
    assert comparison_input.dsm_baseline_vertical_reference is None
    assert comparison_input.dsm_current_vertical_reference is None


# ── 공통: NON_JSON_RESPONSE ──────────────────────────────────────────────


def test_non_json_response_is_typed_not_a_raw_parse_error() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/lease"):
            return httpx.Response(
                201,
                json={"verdict": "LEASED"},
                headers={
                    "X-KSI-Worker-Instance-Id": request.headers["X-KSI-Worker-Instance-Id"],
                    "X-KSI-Lease-Acquisition-Id": request.headers[
                        "X-KSI-Lease-Acquisition-Id"
                    ],
                    "X-KSI-Lease-Generation": "1",
                },
            )
        return httpx.Response(502, text="<html>bad gateway</html>")

    client = _leased_client(httpx.MockTransport(handle))
    with pytest.raises(CoreClientError) as excinfo:
        client.transition("job-1", "FAILED")
    assert excinfo.value.verdict == "NON_JSON_RESPONSE"


def test_bearer_token_is_sent() -> None:
    captured: dict = {}

    def handle(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        if request.url.path.endswith("/lease"):
            return httpx.Response(
                201,
                json={"verdict": "LEASED"},
                headers={
                    "X-KSI-Worker-Instance-Id": request.headers["X-KSI-Worker-Instance-Id"],
                    "X-KSI-Lease-Acquisition-Id": request.headers[
                        "X-KSI-Lease-Acquisition-Id"
                    ],
                    "X-KSI-Lease-Generation": "1",
                },
            )
        return httpx.Response(200, json={"verdict": "TRANSITIONED"})

    client = HttpCoreClient(
        _BASE,
        token="secret-worker-token",
        client=httpx.Client(transport=httpx.MockTransport(handle)),
    )
    client.acquire_lease("job-1")
    client.transition("job-1", "FAILED")
    assert captured["auth"] == "Bearer secret-worker-token"
