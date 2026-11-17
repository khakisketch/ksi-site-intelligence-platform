"""단면 요청자 HTTP 경계. 실제 원장과 계산, 좁은 권한 대역을 사용한다.

실제 소유자의 조립 증거는 별도 HTTP 통합 시험이 담당한다.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.identity.auth import AuthRegistry, PrincipalKind, PrincipalTokenRecord, mount_auth
from surface_profile_job_fixture import (
    AREA,
    NOW,
    SITE,
    issue_request,
    profile_policy,
    requester,
    worker,
)
from test_surface_profile_jobs import Lane

AUTH = {"Authorization": "Bearer profile-reader", "Idempotency-Key": "profile-http"}
BASE = f"/v1/sites/{SITE}/work-areas/{AREA}/surface-profile-jobs"


def mounted_profile(
    path: Path,
    *,
    limits: Any = None,
    requester_kind: PrincipalKind = PrincipalKind.OPERATOR,
    scoped: bool = False,
    policy_overrides: dict[str, Any] | None = None,
) -> tuple[TestClient, SimpleNamespace]:
    from ksi_core.domains.external.delivery.surface_profile_api import (
        SurfaceProfileHttpLimits,
        build_surface_profile_router,
    )

    envelope = (
        profile_policy()
        .resource_envelope.model_copy(
            update={"max_input_bytes": 1_000_000, "resource_envelope_digest": None}
        )
        .sealed()
    )
    lane = Lane(path, resource_envelope=envelope, **(policy_overrides or {}))
    graph = SimpleNamespace(lane=lane, now=NOW)
    reader = requester()
    if scoped or requester_kind is not PrincipalKind.OPERATOR:
        reader = replace(
            reader, allowed_site_ids=frozenset({SITE}), allowed_work_area_ids=frozenset({AREA})
        )
    if requester_kind is not PrincipalKind.OPERATOR:
        reader = replace(reader, kind=requester_kind, role=None)
    registry = AuthRegistry(
        [
            PrincipalTokenRecord(
                token_sha256=hashlib.sha256(token.encode()).hexdigest(), principal=principal
            )
            for token, principal in (
                ("profile-reader", reader),
                ("profile-other-worker", worker("other-worker")),
                ("profile-foreign-worker", worker("foreign-worker", "foreign-org")),
                ("profile-worker", worker()),
                (
                    "profile-foreign",
                    replace(
                        requester(), principal_id="foreign-reader", organization_id="foreign-org"
                    ),
                ),
            )
        ]
    )
    graph.registry = registry
    app = FastAPI()
    mount_auth(app, registry)
    graph.limits = limits or SurfaceProfileHttpLimits(
        request_max_bytes=4096, complete_max_bytes=500_000, timeout_seconds=1.0
    )
    app.include_router(
        build_surface_profile_router(jobs=lane.store, limits=graph.limits, clock=lambda: graph.now)
    )
    graph.app = app
    return TestClient(app), graph


def request_body(**overrides: Any) -> dict[str, Any]:
    return issue_request(**overrides).model_dump(by_alias=True, mode="json")


def test_issue_retry_list_and_cancel_keep_the_same_job_and_hide_numbers(tmp_path: Path) -> None:
    client, _ = mounted_profile(tmp_path)
    first = client.post(BASE, headers=AUTH, json=request_body())
    retry = client.post(BASE, headers=AUTH, json=request_body())
    assert first.status_code == retry.status_code == 200
    assert first.json() == retry.json()
    job_url = BASE + "/" + first.json()["jobId"]
    assert client.get(job_url, headers=AUTH).json() == first.json()
    assert client.get(BASE, headers=AUTH).json()["items"] == [first.json()]
    assert client.get(job_url + "/result", headers=AUTH).status_code == 409
    canceled = client.post(job_url + "/cancel", headers=AUTH)
    assert canceled.status_code == 200
    assert canceled.json()["executionState"] == "CANCELED"
    assert "samples" not in canceled.text and "source" not in canceled.json()
    assert canceled.headers["cache-control"] == "private, no-store"


def test_the_list_filters_by_line_and_rejects_a_malformed_filter(tmp_path: Path) -> None:
    client, _ = mounted_profile(tmp_path)
    job = client.post(BASE, headers=AUTH, json=request_body()).json()
    mine = job["feature"]["featureId"]
    assert client.get(BASE, params={"limit": 1, "feature_id": mine}, headers=AUTH).json()[
        "items"
    ] == [job]
    assert (
        client.get(BASE, params={"feature_id": "mf-" + "9" * 32}, headers=AUTH).json()["items"]
        == []
    )
    for bad in ("x", "mf-" + "G" * 32, "mf-" + "1" * 80):
        response = client.get(BASE, params={"feature_id": bad}, headers=AUTH)
        assert response.status_code == 422, bad


@pytest.mark.parametrize("kind", [PrincipalKind.OPERATOR, PrincipalKind.SPATIAL_DATA_CLIENT])
def test_scoped_requester_lane_is_explicitly_allowed(tmp_path: Path, kind: PrincipalKind) -> None:
    client, _ = mounted_profile(tmp_path, requester_kind=kind, scoped=True)
    response = client.post(BASE, headers=AUTH, json=request_body())
    assert response.status_code == 200
    assert client.get(BASE, headers=AUTH).status_code == 200


def test_mcp_identity_cannot_enter_any_requester_route(tmp_path: Path) -> None:
    client, graph = mounted_profile(tmp_path, requester_kind=PrincipalKind.SPATIAL_DATA_MCP_CLIENT)
    job_id = graph.lane.issue().job_id
    for method, suffix in (
        ("POST", ""),
        ("GET", ""),
        ("GET", "/" + job_id),
        ("GET", "/" + job_id + "/result"),
        ("POST", "/" + job_id + "/cancel"),
    ):
        response = client.request(method, BASE + suffix, headers=AUTH, content=b"{hostile")
        assert response.status_code == 403


@pytest.mark.parametrize("field", ["organizationId", "line", "policy", "url", "outputPath"])
def test_requester_cannot_inject_scope_geometry_or_storage(tmp_path: Path, field: str) -> None:
    client, _ = mounted_profile(tmp_path)
    response = client.post(BASE, headers=AUTH, json={**request_body(), field: "private-injection"})
    assert response.status_code == 422 and response.json()["reason"] == "INVALID_REQUEST"
    assert "private-injection" not in response.text
    assert client.get(BASE, headers=AUTH).json()["items"] == []


@pytest.mark.parametrize(
    "content,extra",
    [
        (b'{"assetRef":"secret-a","assetRef":"secret-b"}', {}),
        (b'{"sampleSpacingM":NaN}', {}),
        (b'{"sampleSpacingM":Infinity}', {}),
        (b'{"x":1}', {"Content-Encoding": "gzip"}),
        (b'{"x":1}', {"Content-Length": "not-an-integer"}),
        (b"x" * 4097, {}),
        (b"{}", {"Content-Type": "text/plain"}),
    ],
)
def test_hostile_json_is_bounded_and_does_not_echo_inputs(
    tmp_path: Path,
    content: bytes,
    extra: dict[str, str],
) -> None:
    client, _ = mounted_profile(tmp_path)
    response = client.post(
        BASE, content=content, headers={**AUTH, "Content-Type": "application/json", **extra}
    )
    assert response.status_code == 422
    assert response.json()["reason"] == "INVALID_REQUEST"
    assert "secret-" not in response.text
    assert client.get(BASE, headers=AUTH).json()["items"] == []


def test_foreign_or_wrong_path_cannot_disclose_or_cancel_a_job(tmp_path: Path) -> None:
    client, graph = mounted_profile(tmp_path)
    job_id = client.post(BASE, headers=AUTH, json=request_body()).json()["jobId"]
    path = BASE + "/" + job_id
    missing = BASE + "/spj-" + "0" * 32
    foreign = {"Authorization": "Bearer profile-foreign"}
    assert client.get(path, headers=foreign).status_code == 404
    assert client.get(path, headers=foreign).json() == client.get(missing, headers=foreign).json()
    wrong_path = path.replace(AREA, "wrong-area")
    before = (graph.lane.tmp / "jobs.jsonl").read_bytes()
    assert client.post(wrong_path + "/cancel", headers=AUTH).status_code == 404
    assert (graph.lane.tmp / "jobs.jsonl").read_bytes() == before
    assert client.get(path, headers=AUTH).json()["executionState"] == "QUEUED"


@pytest.mark.parametrize("authorization,expected", [(None, 401), ("profile-worker", 403)])
def test_authentication_and_role_precede_hostile_body(
    tmp_path: Path,
    authorization: str | None,
    expected: int,
) -> None:
    client, _ = mounted_profile(tmp_path)
    headers = {"Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = "Bearer " + authorization
    response = client.post(BASE, headers=headers, content=b"\xff" * 8000)
    assert response.status_code == expected


def test_credential_revoked_during_body_cannot_issue_a_job(tmp_path: Path) -> None:
    client, graph = mounted_profile(tmp_path)
    payload = json.dumps(request_body()).encode()

    async def send() -> Any:
        async def stream() -> Any:
            yield payload[:1]
            graph.app.state.auth_registry = AuthRegistry([])
            yield payload[1:]

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=graph.app), base_url="http://profile.test"
        ) as requester_client:
            return await requester_client.post(
                BASE, content=stream(), headers={**AUTH, "Content-Type": "application/json"}
            )

    try:
        response = asyncio.run(send())
        assert response.status_code == 401
    finally:
        graph.app.state.auth_registry = graph.registry
    assert client.get(BASE, headers=AUTH).json()["items"] == []


def test_slow_body_is_refused_without_issuance(tmp_path: Path) -> None:
    from ksi_core.domains.external.delivery.surface_profile_api import SurfaceProfileHttpLimits

    client, graph = mounted_profile(tmp_path, limits=SurfaceProfileHttpLimits(4096, 500_000, 0.01))

    async def send() -> Any:
        async def stream() -> Any:
            yield b"{"
            await asyncio.sleep(0.05)
            yield b"}"

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=graph.app), base_url="http://profile.test"
        ) as requester_client:
            return await requester_client.post(
                BASE, content=stream(), headers={**AUTH, "Content-Type": "application/json"}
            )

    assert asyncio.run(send()).status_code == 422
    assert client.get(BASE, headers=AUTH).json()["items"] == []
