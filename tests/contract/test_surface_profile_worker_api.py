"""일꾼 HTTP의 입력 결속·현재 attempt·완료 경계. 실제 소유자 조립은 별도 시험한다."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from ksi_event_contracts.surface_profile_job import SurfaceProfileFrozenJobV1
from surface_profile_job_fixture import genuine_answer
from test_surface_profile_api import AUTH, BASE, mounted_profile, request_body

WORKER_BASE = "/v1/internal/surface-profile-jobs"
WORKER = {
    "Authorization": "Bearer profile-worker",
    "X-Surface-Profile-Worker-Instance-Id": "instance-1",
}
DIGEST_HEADER = "X-Surface-Profile-Attempt-Digest"


def worker_mounted(path: Path, **kwargs: Any) -> tuple[Any, Any]:
    from ksi_core.domains.external.delivery.surface_profile_worker_api import (
        build_surface_profile_worker_router,
    )

    client, graph = mounted_profile(path, **kwargs)
    graph.app.include_router(
        build_surface_profile_worker_router(
            jobs=graph.lane.store,
            limits=graph.limits,
            clock=lambda: graph.now,
        )
    )
    return client, graph


def test_worker_round_trip_uses_current_digest_and_releases_only_verified_result(
    tmp_path: Path,
) -> None:
    client, graph = worker_mounted(tmp_path)
    job_id = client.post(BASE, json=request_body(), headers=AUTH).json()["jobId"]
    page = client.get(WORKER_BASE, headers=WORKER)
    assert page.status_code == 200 and page.json() == {"items": [{"jobId": job_id}]}
    job_url = WORKER_BASE + "/" + job_id
    leased = client.post(
        job_url + "/lease",
        headers=WORKER,
        json={
            "workerInstanceId": "instance-1",
            "acquisitionId": "http-acquisition",
        },
    )
    assert leased.status_code == 200
    attempt = leased.json()["attempt"]
    old_headers = {**WORKER, DIGEST_HEADER: attempt["attemptDigest"]}
    first_input = client.get(job_url + "/input", headers=old_headers)
    assert first_input.status_code == 200
    graph.now += timedelta(seconds=1)
    renewed = client.post(job_url + "/renew", headers=old_headers, json={"attempt": attempt})
    assert renewed.status_code == 200
    attempt = renewed.json()["attempt"]
    assert client.get(job_url + "/input", headers=old_headers).status_code == 409
    headers = {**WORKER, DIGEST_HEADER: attempt["attemptDigest"]}
    current = client.get(job_url + "/input", headers=headers)
    assert current.status_code == 200
    job = SurfaceProfileFrozenJobV1.model_validate(current.json()["input"])
    result, receipt = genuine_answer(job, graph.lane.raster, graph.now)
    completed = client.post(
        job_url + "/complete",
        headers=headers,
        json={
            "attempt": attempt,
            "result": result.model_dump(by_alias=True, mode="json"),
            "receipt": receipt.model_dump(by_alias=True, mode="json"),
        },
    )
    assert completed.status_code == 200 and "samples" not in completed.text
    released = client.get(BASE + "/" + job_id + "/result", headers=AUTH)
    assert released.status_code == 200
    assert released.json()["result"] == result.model_dump(by_alias=True, mode="json")


@pytest.mark.parametrize("operation", ["renew", "complete", "failure"])
def test_another_worker_cannot_use_a_copied_live_attempt(tmp_path: Path, operation: str) -> None:
    client, graph = worker_mounted(tmp_path)
    job_id = client.post(BASE, json=request_body(), headers=AUTH).json()["jobId"]
    url = WORKER_BASE + "/" + job_id
    attempt = client.post(
        url + "/lease",
        headers=WORKER,
        json={
            "workerInstanceId": "instance-1",
            "acquisitionId": "a1",
        },
    ).json()["attempt"]
    graph.now += timedelta(seconds=1)
    headers = {
        **WORKER,
        "Authorization": "Bearer profile-other-worker",
        DIGEST_HEADER: attempt["attemptDigest"],
    }
    body = {"attempt": attempt}
    if operation == "complete":
        job = SurfaceProfileFrozenJobV1.model_validate(
            client.get(
                url + "/input", headers={**WORKER, DIGEST_HEADER: attempt["attemptDigest"]}
            ).json()["input"]
        )
        result, receipt = genuine_answer(job, graph.lane.raster, graph.now)
        body.update(
            result=result.model_dump(by_alias=True, mode="json"),
            receipt=receipt.model_dump(by_alias=True, mode="json"),
        )
    elif operation == "failure":
        body.update(reason="UNSUPPORTED_RASTER", retryable=False)
    response = client.post(url + "/" + operation, headers=headers, json=body)
    assert response.status_code == 409
    assert client.get(BASE + "/" + job_id, headers=AUTH).json()["executionState"] == "RUNNING"


def leased_job(path: Path, **kwargs: Any) -> tuple[Any, Any, str, dict[str, Any], dict[str, str]]:
    client, graph = worker_mounted(path, **kwargs)
    job_id = client.post(BASE, json=request_body(), headers=AUTH).json()["jobId"]
    url = WORKER_BASE + "/" + job_id
    attempt = client.post(
        url + "/lease",
        headers=WORKER,
        json={
            "workerInstanceId": "instance-1",
            "acquisitionId": "a1",
        },
    ).json()["attempt"]
    return client, graph, url, attempt, {**WORKER, DIGEST_HEADER: attempt["attemptDigest"]}


def completed_body(client: Any, graph: Any, url: str, attempt: Any, headers: Any) -> dict[str, Any]:
    job = SurfaceProfileFrozenJobV1.model_validate(
        client.get(url + "/input", headers=headers).json()["input"]
    )
    result, receipt = genuine_answer(job, graph.lane.raster, graph.now)
    return {
        "attempt": attempt,
        "result": result.model_dump(by_alias=True, mode="json"),
        "receipt": receipt.model_dump(by_alias=True, mode="json"),
    }


def test_pending_requires_activation_and_never_returns_frozen_input(tmp_path: Path) -> None:
    client, graph = worker_mounted(tmp_path)
    client.post(BASE, headers=AUTH, json=request_body())
    graph.lane.authority.activated = False
    assert client.get(WORKER_BASE, headers=WORKER).status_code == 403
    assert (
        client.get(
            WORKER_BASE, headers={**WORKER, "Authorization": "Bearer profile-reader"}
        ).status_code
        == 403
    )


def test_failure_retries_with_a_new_fence_then_stops_on_permanent_failure(tmp_path: Path) -> None:
    client, graph, url, attempt, headers = leased_job(tmp_path)
    first = client.post(
        url + "/failure",
        headers=headers,
        json={
            "attempt": attempt,
            "reason": "STORAGE_UNAVAILABLE",
            "retryable": True,
        },
    )
    assert first.status_code == 200 and first.json()["executionState"] == "QUEUED"
    assert client.get(url + "/input", headers=headers).status_code == 409
    assert client.get(WORKER_BASE, headers=WORKER).json()["items"] == []
    graph.now += timedelta(seconds=2)
    second = client.post(
        url + "/lease",
        headers=WORKER,
        json={
            "workerInstanceId": "instance-1",
            "acquisitionId": "a2",
        },
    ).json()["attempt"]
    assert second["fence"] == attempt["fence"] + 1
    assert client.get(url + "/input", headers=headers).status_code == 409
    final = client.post(
        url + "/failure",
        headers={**WORKER, DIGEST_HEADER: second["attemptDigest"]},
        json={"attempt": second, "reason": "UNSUPPORTED_RASTER", "retryable": False},
    )
    assert final.status_code == 200 and final.json()["executionState"] == "FAILED"


@pytest.mark.parametrize(
    "reason,retryable",
    [("/private/path", False), ("STORAGE_UNAVAILABLE", False), ("UNSUPPORTED_RASTER", True)],
)
def test_failure_vocabulary_and_retry_policy_cannot_be_overridden(
    tmp_path: Path,
    reason: str,
    retryable: bool,
) -> None:
    client, _, url, attempt, headers = leased_job(tmp_path)
    response = client.post(
        url + "/failure",
        headers=headers,
        json={"attempt": attempt, "reason": reason, "retryable": retryable},
    )
    assert response.status_code == 422 and "/private/path" not in response.text


def test_foreign_worker_cannot_distinguish_existing_and_missing_jobs(tmp_path: Path) -> None:
    client, _, url, _, headers = leased_job(tmp_path)
    foreign = {**headers, "Authorization": "Bearer profile-foreign-worker"}
    found = client.get(url + "/input", headers=foreign)
    absent = client.get(WORKER_BASE + "/spj-" + "0" * 32 + "/input", headers=foreign)
    assert found.status_code == absent.status_code == 404
    assert found.json() == absent.json()


def test_cancel_withdraws_worker_input_and_numeric_read(tmp_path: Path) -> None:
    client, _, url, _, headers = leased_job(tmp_path)
    public_url = BASE + "/" + url.rsplit("/", 1)[1]
    assert client.post(public_url + "/cancel", headers=AUTH).status_code == 200
    assert client.get(url + "/input", headers=headers).status_code == 409
    assert client.get(public_url + "/result", headers=AUTH).status_code == 409


def test_complete_uses_its_own_larger_bounded_json_budget(tmp_path: Path) -> None:
    import json

    from ksi_event_contracts.surface_profile_job import SurfaceProfileReceiptV1

    client, graph, url, attempt, headers = leased_job(tmp_path)
    body = completed_body(client, graph, url, attempt, headers)
    receipt = SurfaceProfileReceiptV1.model_validate(body["receipt"])
    body["receipt"] = (
        receipt.model_copy(
            update={
                "attribution": "s" * 4096,
                "receipt_digest": None,
            }
        )
        .sealed()
        .model_dump(by_alias=True, mode="json")
    )
    assert len(json.dumps(body).encode()) > graph.limits.request_max_bytes
    completed = client.post(url + "/complete", headers=headers, json=body)
    assert completed.status_code == 200
    assert client.post(url + "/complete", headers=headers, json=body).json() == completed.json()
    graph.lane.authority.deny["READ"] = "ACCESS_REVOKED"
    public_url = BASE + "/" + attempt["jobId"]
    assert client.get(public_url + "/result", headers=AUTH).status_code == 403
    assert client.get(public_url, headers=AUTH).json()["availability"] == "ACCESS_REVOKED"


def test_numeric_result_size_limit_is_separate_from_envelope_limit(tmp_path: Path) -> None:
    client, graph, url, attempt, headers = leased_job(
        tmp_path, policy_overrides={"max_result_bytes": 100}
    )
    response = client.post(
        url + "/complete",
        headers=headers,
        json=completed_body(client, graph, url, attempt, headers),
    )
    assert response.status_code == 413
    assert response.json()["reason"] == "RESOURCE_LIMIT_EXCEEDED"
    assert (
        client.get(BASE + "/" + attempt["jobId"], headers=AUTH).json()["executionState"]
        == "RUNNING"
    )


def test_oversized_completion_is_rejected_before_model_validation(tmp_path: Path) -> None:
    client, graph, url, attempt, headers = leased_job(tmp_path)
    response = client.post(
        url + "/complete",
        headers={**headers, "Content-Type": "application/json"},
        content=b"x" * (graph.limits.complete_max_bytes + 1),
    )
    assert response.status_code == 422
    assert (
        client.get(BASE + "/" + attempt["jobId"], headers=AUTH).json()["executionState"]
        == "RUNNING"
    )


def test_worker_credential_revoked_during_completion_cannot_commit(tmp_path: Path) -> None:
    import asyncio
    import json

    import httpx
    from ksi_core.identity.auth import AuthRegistry

    client, graph, url, attempt, headers = leased_job(tmp_path)
    payload = json.dumps(completed_body(client, graph, url, attempt, headers)).encode()

    async def send() -> Any:
        async def stream() -> Any:
            yield payload[:1]
            graph.app.state.auth_registry = AuthRegistry([])
            yield payload[1:]

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=graph.app), base_url="http://profile.test"
        ) as worker_client:
            return await worker_client.post(
                url + "/complete",
                content=stream(),
                headers={**headers, "Content-Type": "application/json"},
            )

    try:
        assert asyncio.run(send()).status_code == 401
    finally:
        graph.app.state.auth_registry = graph.registry
    assert (
        client.get(BASE + "/" + attempt["jobId"], headers=AUTH).json()["executionState"]
        == "RUNNING"
    )


@pytest.mark.parametrize("operation", ["lease", "renew", "complete", "failure"])
def test_worker_activation_check_precedes_body_parsing(tmp_path: Path, operation: str) -> None:
    client, graph, url, _, headers = leased_job(tmp_path)
    graph.lane.authority.activated = False
    response = client.post(
        url + "/" + operation,
        content=b"\xff" * 10_000,
        headers={**headers, "Content-Type": "application/json"},
    )
    assert response.status_code == 403
