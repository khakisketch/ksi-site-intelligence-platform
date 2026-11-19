"""단면 일꾼 한 건의 실행: 실제 loopback 객체 서버, 실제 Core 라우터, 실제 래스터 계산.

Core 소유자(자료·grant·HEIGHT)는 단위 시험용 좁은 대역이다. 실제 소유자와의 통합은
HTTP 통합 시험이 따로 증명한다. 이 시험은 OS 수준 격리와 자원 한도를 증명하지 않는다.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
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
    ObservedVerticalReferenceV1,
)
from ksi_event_contracts.surface_profile_job import SurfaceProfileActivationV1
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)
from ksi_processing_controller.surface_profile_core_client import SurfaceProfileCoreClient
from ksi_processing_controller.surface_profile_runner import run_once
from spatial_data_fixture import make_grant, make_source
from surface_profile_job_fixture import (
    ORG,
    ORIGIN_X,
    ORIGIN_Y,
    compute_generated_profile,
    feature_revision,
    inspect_generated_profile_raster,
    line,
    profile_policy,
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

    core_root = tmp_path / "core"
    core_root.mkdir()
    client, graph = mounted_profile(core_root, policy_overrides=policy_overrides)
    data = raster.read_bytes()
    sha = "sha256:" + hashlib.sha256(data).hexdigest()
    measurements = inspect_generated_profile_raster(raster)
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
    a, _, c, _, e, f = measurements.transform
    graph.lane.authority.grant = make_grant(
        allowed_bounds=(c, f + e * measurements.height, c + a * measurements.width, f),
        observed_crs_digest=measurements.observed_crs_digest,
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
        compute=compute_generated_profile,
    )


def issue(graph: Any, *, feature: Any = None) -> str:
    body = request_body(**({"feature": feature.ref()} if feature is not None else {}))
    response = graph.http.post(BASE, headers=AUTH, json=body)
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
        state = view(graph, job_id)
        assert state["executionState"] == "COMPLETED", state["reason"]
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


def test_a_job_on_a_declared_vertical_reference_runs_and_the_receipt_says_so(
    tmp_path: Path,
) -> None:
    """파일에 수직 기준이 없어도 선언 위에서 읽고, 영수증이 선언임을 그대로 되풀이한다."""
    from surface_profile_job_fixture import declared_vertical

    raster = write_raster(tmp_path / "dsm.tif", observed_vertical=False)
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster, claimed={"observed_vertical_reference": None})
        graph.lane.authority.declared = declared_vertical()
        job_id = issue(graph)
        assert run(graph) is True
        state = view(graph, job_id)
        assert state["executionState"] == "COMPLETED", state["reason"]
        vertical = state["receipt"]["verticalReference"]
        assert vertical["provenance"] == "DECLARED" and vertical["observed"] is None
        assert vertical["declared"]["unit"] == "metre"
        assert vertical["declared"]["declarationId"] == "vrd-" + "1" * 32
        released = graph.http.get(BASE + "/" + job_id + "/result", headers=AUTH)
        assert released.status_code == 200, released.text
        assert released.json()["job"]["receipt"]["verticalReference"] == vertical


def test_a_job_on_a_file_observation_says_observed_and_names_no_declaration(
    tmp_path: Path,
) -> None:
    raster = write_raster(tmp_path / "dsm.tif")
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster)
        job_id = issue(graph)
        assert run(graph) is True
        vertical = view(graph, job_id)["receipt"]["verticalReference"]
        assert vertical["provenance"] == "OBSERVED" and vertical["declared"] is None
        assert vertical["observed"]["identifier"] == "EPSG:5773"


def test_an_internal_masked_tiled_dsm_keeps_the_observed_profile_values(tmp_path: Path) -> None:
    raster = write_raster(tmp_path / "masked.tif", internal_mask=True, tiled=True)
    envelope = (
        profile_policy()
        .resource_envelope.model_copy(
            update={
                "max_input_bytes": 1_000_000,
                "max_streamed_bytes": 1_000_000,
                "max_decompressed_bytes": 1_000_000,
                "max_sample_bytes": 1_000_000,
                "max_workspace_bytes": 4_000_000,
                "resource_envelope_digest": None,
            }
        )
        .sealed()
    )
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster, policy_overrides={"resource_envelope": envelope})
        job_id = issue(graph)
        assert run(graph) is True
        state = view(graph, job_id)
        assert (state["executionState"], state["reason"]) == ("COMPLETED", None)
        response = graph.http.get(BASE + "/" + job_id + "/result", headers=AUTH)
        assert response.status_code == 200, response.text
        samples = response.json()["result"]["samples"]
        assert samples[0]["invalidReason"] == "NODATA"
        for sample in samples[1:]:
            expected = (
                100.0 + 0.5 * (sample["x"] - ORIGIN_X - 0.5) + 0.25 * (ORIGIN_Y - sample["y"] - 0.5)
            )
            assert sample["elevationM"] == pytest.approx(expected, abs=1e-4)


@pytest.mark.parametrize(
    ("limit", "value"),
    [("max_blocks", 1), ("max_decompressed_bytes", 1200), ("max_sample_bytes", 350)],
)
def test_internal_mask_window_bytes_and_blocks_count_toward_signed_limits(
    tmp_path: Path, limit: str, value: int
) -> None:
    raster = write_raster(tmp_path / "masked.tif", internal_mask=True, tiled=True)
    envelope = (
        profile_policy()
        .resource_envelope.model_copy(
            update={
                limit: value,
                "max_input_bytes": 1_000_000,
                "max_streamed_bytes": 1_000_000,
                "resource_envelope_digest": None,
            }
        )
        .sealed()
    )
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster, policy_overrides={"resource_envelope": envelope})
        job_id = issue(graph)
        assert run(graph) is True
        failed = view(graph, job_id)
        assert (failed["executionState"], failed["reason"]) == ("FAILED", "RESOURCE_LIMIT_EXCEEDED")
        assert failed["receipt"] is None


@pytest.mark.parametrize(
    ("max_decompressed_bytes", "expected_state", "expected_reason"),
    [(2000, "FAILED", "RESOURCE_LIMIT_EXCEEDED"), (3002, "COMPLETED", None)],
)
def test_narrow_read_inside_internal_mask_strips_uses_full_strip_decode_bytes(
    tmp_path: Path,
    max_decompressed_bytes: int,
    expected_state: str,
    expected_reason: str | None,
) -> None:
    raster = write_raster(tmp_path / "strip-mask.tif", internal_mask=True)
    envelope = (
        profile_policy()
        .resource_envelope.model_copy(
            update={
                "max_decompressed_bytes": max_decompressed_bytes,
                "max_sample_bytes": 1_000_000,
                "max_input_bytes": 1_000_000,
                "max_streamed_bytes": 1_000_000,
                "resource_envelope_digest": None,
            }
        )
        .sealed()
    )
    narrow_feature = feature_revision(saved=line((10, 4), (10.1, 4)))
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster, policy_overrides={"resource_envelope": envelope})
        graph.lane.authority.feature = narrow_feature
        job_id = issue(graph, feature=narrow_feature)
        assert run(graph) is True
        state = view(graph, job_id)
        assert (state["executionState"], state["reason"]) == (
            expected_state,
            expected_reason,
        )
        if expected_state == "FAILED":
            assert state["receipt"] is None
        else:
            response = graph.http.get(BASE + "/" + job_id + "/result", headers=AUTH)
            assert response.status_code == 200, response.text
            first = response.json()["result"]["samples"][0]
            expected = (
                100.0 + 0.5 * (first["x"] - ORIGIN_X - 0.5) + 0.25 * (ORIGIN_Y - first["y"] - 0.5)
            )
            assert first["elevationM"] == pytest.approx(expected, abs=1e-4)


def test_a_reported_vertical_datum_must_also_be_present_in_the_staged_file(tmp_path: Path) -> None:
    raster = write_raster(tmp_path / "horizontal.tif", observed_vertical=False)
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(
            tmp_path,
            origin,
            raster,
            claimed={
                "observed_vertical_reference": ObservedVerticalReferenceV1(
                    identifier="EPSG:5773", basis="EGM96 height"
                )
            },
        )
        job_id = issue(graph)
        assert run(graph)
        state = view(graph, job_id)
        assert (state["executionState"], state["reason"]) == (
            "FAILED",
            "SOURCE_MEASUREMENTS_MISMATCH",
        )
        assert state["receipt"] is None


@pytest.mark.parametrize(
    "limit", ["max_workspace_bytes", "max_sample_bytes", "max_decompressed_bytes"]
)
def test_resource_budget_refuses_a_read_and_releases_its_private_workspace(
    tmp_path: Path, limit: str
) -> None:
    raster = write_raster(tmp_path / "original.tif")
    envelope = (
        profile_policy()
        .resource_envelope.model_copy(
            update={limit: 16, "max_input_bytes": 1_000_000, "resource_envelope_digest": None}
        )
        .sealed()
    )
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster, policy_overrides={"resource_envelope": envelope})
        job_id = issue(graph)
        assert run(graph)
        state = view(graph, job_id)
        assert (state["executionState"], state["reason"]) == ("FAILED", "RESOURCE_LIMIT_EXCEEDED")
        assert state["receipt"] is None
        assert list(graph.workspace.iterdir()) == []


def test_sealed_size_above_transport_limit_is_refused_before_contacting_storage(
    tmp_path: Path,
) -> None:
    raster = write_raster(tmp_path / "original.tif")
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster)
        graph.transport = replace(
            graph.transport, max_object_bytes=raster.stat().st_size - 1, max_chunk_bytes=128
        )
        job_id = issue(graph)
    assert run(graph)
    state = view(graph, job_id)
    assert (state["executionState"], state["reason"]) == ("FAILED", "RESOURCE_LIMIT_EXCEEDED")
    assert state["receipt"] is None
    assert list(graph.workspace.iterdir()) == []


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
    ("claimed", "reason"),
    [
        ({"width": 31}, "SOURCE_MEASUREMENTS_MISMATCH"),
        ({"height": 21}, "SOURCE_MEASUREMENTS_MISMATCH"),
        ({"transform": (2.0, 0.0, ORIGIN_X, 0.0, -2.0, ORIGIN_Y)}, "SOURCE_MEASUREMENTS_MISMATCH"),
        (
            {"transform": (1.0, 0.0, ORIGIN_X + 1.0, 0.0, -1.0, ORIGIN_Y)},
            "SOURCE_MEASUREMENTS_MISMATCH",
        ),
        ({"dtype": "float64"}, "SOURCE_MEASUREMENTS_MISMATCH"),
        ({"observed_crs_identifier": "EPSG:5179"}, "SOURCE_MEASUREMENTS_MISMATCH"),
        ({"observed_crs_digest": "sha256:" + "1" * 64}, "CRS_MISMATCH"),
        ({"footprint_wkt": "POLYGON ((0 0, 1 0, 1 1, 0 0))"}, "SOURCE_MEASUREMENTS_MISMATCH"),
        ({"footprint_digest": "sha256:" + "2" * 64}, "SOURCE_MEASUREMENTS_MISMATCH"),
        ({"nodata_value": -1.0}, "SOURCE_MEASUREMENTS_MISMATCH"),
    ],
)
def test_file_facts_must_match_the_sealed_measurements_even_when_bytes_match(
    tmp_path: Path, claimed: dict[str, Any], reason: str
) -> None:
    raster = write_raster(tmp_path / "dsm.tif")
    with object_server({"bytes": raster.read_bytes()}) as origin:
        graph = lane(tmp_path, origin, raster, claimed=claimed)
        job_id = issue(graph)
        assert run(graph) is True
        failed = view(graph, job_id)
        assert (failed["executionState"], failed["reason"]) == ("FAILED", reason)


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
