"""단면 일꾼 한 건의 실행: 실제 loopback 객체 서버, 실제 Core 라우터, 실제 래스터 계산.

Core 소유자(자료·grant·HEIGHT)는 단위 시험용 좁은 대역이다. 실제 소유자와의 통합은
HTTP 통합 시험이 따로 증명한다. 이 시험은 OS 수준 격리와 자원 한도를 증명하지 않는다.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from ksi_event_contracts.external_artifact_validation import (
    ArtifactInspectionOutcomeV1,
    ArtifactOutcome,
)
from ksi_event_contracts.surface_profile_job import SurfaceProfileActivationV1
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from ksi_processing_controller.surface_profile_core_client import SurfaceProfileCoreClient
from ksi_processing_controller.surface_profile_runner import run_once
from spatial_data_fixture import make_source
from surface_profile_job_fixture import (
    ORG,
    ORIGIN_X,
    ORIGIN_Y,
    measured_source,
    write_raster,
)
from test_surface_profile_api import AUTH, BASE, mounted_profile, request_body
from test_surface_profile_worker_api import ProfileStorage

TOKEN = "profile-worker"  # noqa: S105 -- 시험용 자격


class _Bridge(httpx.BaseTransport):
    """https 주소로 만든 클라이언트를 조립된 Core 앱으로 연결한다(네트워크 없음)."""

    def __init__(self, core: TestClient) -> None:
        self._core = core

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path + ("?" + request.url.query.decode() if request.url.query else "")
        response = self._core.request(
            request.method, path, content=request.read(), headers=dict(request.headers)
        )
        return httpx.Response(
            response.status_code,
            headers=response.headers,
            content=response.content,
            request=request,
        )


@contextmanager
def object_server(payload: dict[str, Any]) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if payload.get("down") or self.path != "/source":
                self.send_error(503 if payload.get("down") else 404)
                return
            body = payload["bytes"]
            self.send_response(200)
            self.send_header("Content-Type", "image/tiff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def lane(
    tmp_path: Path,
    origin: str,
    raster: Path,
    *,
    claimed: dict[str, Any] | None = None,
    policy_overrides: dict[str, Any] | None = None,
) -> Any:
    from ksi_core.domains.external.delivery.surface_profile_worker_api import (
        build_surface_profile_worker_router,
    )

    client, graph = mounted_profile(tmp_path, policy_overrides=policy_overrides)
    data = raster.read_bytes()
    sha = "sha256:" + hashlib.sha256(data).hexdigest()
    base = measured_source()
    measurements = base.inspection.measurements
    if claimed:
        measurements = measurements.model_copy(update=claimed)
    graph.lane.authority.source = make_source(
        observed_sha256=sha,
        observed_size_bytes=len(data),
        inspection=ArtifactInspectionOutcomeV1(
            artifact_id="artifact-local",
            observed_sha256=sha,
            outcome=ArtifactOutcome.MEASURED,
            measurements=measurements,
        ),
        observed_crs_units="metre",
    )
    graph.storage = ProfileStorage()
    graph.storage.origin = origin
    policy, runtime = graph.lane.policy, graph.lane.runtime
    graph.activation = SurfaceProfileActivationV1(
        activation_id="runner-activation",
        organization_id=ORG,
        worker_principal_id="worker-local",
        worker_instance_id="instance-1",
        policy_digest=policy.policy_digest or "",
        runtime_digest=runtime.runtime_digest or "",
        trusted_endpoint_origins=(origin,),
        valid_from=graph.now - timedelta(minutes=1),
        valid_until=graph.now + timedelta(hours=1),
    ).sealed()
    graph.app.include_router(
        build_surface_profile_worker_router(
            jobs=graph.lane.store,
            limits=graph.limits,
            clock=lambda: graph.now,
            storage=graph.storage,
            activation=graph.activation,
        )
    )
    graph.http = client
    graph.core = SurfaceProfileCoreClient(
        base_url="https://core.invalid",
        token=TOKEN,
        activation=graph.activation,
        policy=policy,
        runtime=runtime,
        clock=lambda: graph.now,
        maximum_response_bytes=1_000_000,
        maximum_request_bytes=500_000,
        request_timeout_seconds=5.0,
        transport=_Bridge(client),
    )
    graph.transport = ExternalObjectTransportPolicyV1(
        endpoints=(TrustedObjectEndpointV1(origin=origin, addresses=("127.0.0.1",)),),
        max_header_bytes=16_384,
        max_object_bytes=1_000_000,
        max_chunk_bytes=65_536,
    )
    graph.workspace = tmp_path / "private"
    graph.workspace.mkdir(mode=0o700)
    return graph


def run(graph: SimpleNamespace) -> bool:
    return run_once(
        core=graph.core,
        transport_policy=graph.transport,
        clock=lambda: graph.now,
        workspace_root=graph.workspace,
        heartbeat_millis=100,
    )


def issue(graph: Any) -> str:
    response = graph.http.post(BASE, headers=AUTH, json=request_body())
    assert response.status_code == 200, response.text
    return response.json()["jobId"]


def view(graph: Any, job_id: str) -> dict[str, Any]:
    return graph.http.get(BASE + "/" + job_id, headers=AUTH).json()


def test_worker_reads_sealed_bytes_and_reports_the_analytic_surface(tmp_path: Path) -> None:
    raster = write_raster(tmp_path / "dsm.tif")
    payload = {"bytes": raster.read_bytes()}
    with object_server(payload) as origin:
        graph = lane(tmp_path, origin, raster)
        job_id = issue(graph)
        assert run(graph) is True
        assert view(graph, job_id)["executionState"] == "COMPLETED"
        released = graph.http.get(BASE + "/" + job_id + "/result", headers=AUTH)
        assert released.status_code == 200, released.text
        samples = released.json()["result"]["samples"]
        assert len(samples) > 5
        for sample in samples:
            expected = (
                100.0 + 0.5 * (sample["x"] - ORIGIN_X - 0.5) + 0.25 * (ORIGIN_Y - sample["y"] - 0.5)
            )
            assert sample["elevationM"] == pytest.approx(expected, abs=1e-4)
        assert run(graph) is False  # 대기 중인 작업이 없다


def test_bytes_that_differ_from_the_sealed_digest_fail_the_job_without_a_result(
    tmp_path: Path,
) -> None:
    raster = write_raster(tmp_path / "dsm.tif")
    tampered = bytearray(raster.read_bytes())
    tampered[-1] ^= 0xFF
    with object_server({"bytes": bytes(tampered)}) as origin:
        graph = lane(tmp_path, origin, raster)
        job_id = issue(graph)
        assert run(graph) is True
        failed = view(graph, job_id)
        assert (failed["executionState"], failed["reason"]) == ("FAILED", "SOURCE_BYTES_MISMATCH")
        assert graph.http.get(BASE + "/" + job_id + "/result", headers=AUTH).status_code == 409


@pytest.mark.parametrize(
    "claimed",
    [
        {"width": 31},
        {"height": 21},
        {"transform": (2.0, 0.0, ORIGIN_X, 0.0, -2.0, ORIGIN_Y)},
        {"observed_crs_identifier": "EPSG:5179"},
    ],
)
def test_file_facts_must_match_the_sealed_measurements_even_when_bytes_match(
    tmp_path: Path, claimed: dict[str, Any]
) -> None:
    raster = write_raster(tmp_path / "dsm.tif")
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster, claimed=claimed)
        job_id = issue(graph)
        assert run(graph) is True
        failed = view(graph, job_id)
        assert (failed["executionState"], failed["reason"]) == (
            "FAILED",
            "SOURCE_MEASUREMENTS_MISMATCH",
        )


def test_an_unreachable_object_store_requeues_the_job_without_a_result(tmp_path: Path) -> None:
    raster = write_raster(tmp_path / "dsm.tif")
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster)
        job_id = issue(graph)
    # 서버를 닫은 뒤 실행하므로 연결 자체가 실패한다. 전송 장애만 재시도 대상이다.
    assert run(graph) is True
    queued = view(graph, job_id)
    assert queued["executionState"] == "QUEUED"
    assert graph.http.get(BASE + "/" + job_id + "/result", headers=AUTH).status_code == 409


def test_a_calculation_refusal_fails_the_job_with_its_own_reason_and_no_partial_numbers(
    tmp_path: Path,
) -> None:
    raster = write_raster(tmp_path / "dsm.tif")
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster, policy_overrides={"maximum_source_block_cells": 10})
        job_id = issue(graph)
        assert run(graph) is True
        failed = view(graph, job_id)
        assert (failed["executionState"], failed["reason"]) == ("FAILED", "SOURCE_BLOCK_TOO_LARGE")
        assert graph.http.get(BASE + "/" + job_id + "/result", headers=AUTH).status_code == 409
