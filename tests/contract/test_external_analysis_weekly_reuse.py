"""Three-epoch weekly reuse proof through Core HTTP and the actual GIS worker."""

from __future__ import annotations

import socket
import time
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import unquote

import httpx
import pytest
import uvicorn
from analysis_api_local_fixture import build_local_analysis_api_fixture
from fastapi.testclient import TestClient
from ksi_event_contracts.external_analysis_api import AnalysisObservationSelectorV1
from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient
from ksi_processing_controller.external_analysis_worker import (
    ProcessingWorkerRuntimeIdentityV1,
    run_once,
)
from ksi_processing_controller.external_object_streams import (
    ExternalObjectTransportPolicyV1,
    TrustedObjectEndpointV1,
)

type JsonValue = str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


def _json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            assert isinstance(key, str)
            result[key] = _json_value(item)
        return result
    raise AssertionError(f"unexpected non-JSON value: {type(value).__name__}")


def _json_object(value: object) -> JsonObject:
    normalized = _json_value(value)
    assert isinstance(normalized, dict)
    return normalized


def _nested(value: JsonObject, key: str) -> JsonObject:
    return _json_object(value[key])


@pytest.mark.parametrize("v2_dsm_only", [False, True])
def test_default_two_epoch_fixture_keeps_original_inspection_time(
    tmp_path: Path, v2_dsm_only: bool
) -> None:
    fixture = build_local_analysis_api_fixture(tmp_path, v2_dsm_only=v2_dsm_only)
    try:
        assert fixture.third is None
        assert len(fixture.synthetic_epoch_chronology) == 2
        assert all(
            inspection_reported_at == fixture._fixture_now
            for _capture_start, _capture_end, _sealed_at, inspection_reported_at
            in fixture.synthetic_epoch_chronology
        )
    finally:
        fixture.close()


def _request_body(
    baseline: AnalysisObservationSelectorV1, current: AnalysisObservationSelectorV1
) -> dict[str, object]:
    return {
        "baseline": baseline.model_dump(by_alias=True, mode="json"),
        "current": current.model_dump(by_alias=True, mode="json"),
    }


def _completed_analysis(
    client: httpx.Client,
    *,
    site_id: str,
    analysis_id: str,
    headers: dict[str, str],
) -> tuple[JsonObject, JsonObject, JsonObject]:
    detail_url = f"/v1/sites/{site_id}/analyses/{analysis_id}"
    for _ in range(50):
        detail = client.get(detail_url, headers=headers)
        assert detail.status_code == 200, detail.text
        if detail.json()["executionState"] == "COMPLETED":
            break
        time.sleep(0.02)
    result = client.get(detail_url + "/result", headers=headers)
    evidence = client.get(detail_url + "/evidence", headers=headers)
    assert detail.status_code == result.status_code == evidence.status_code == 200
    assert detail.json()["executionState"] == "COMPLETED"
    assert detail.json()["suitabilityState"] == "PROVISIONAL_ACCURACY_UNVERIFIED"
    assert detail.json()["result"] == result.json()["result"] == evidence.json()["result"]
    return _json_object(detail.json()), _json_object(result.json()), _json_object(evidence.json())


def test_v2_three_epoch_weekly_reuse_uses_fresh_pair_authority_and_replays_exact_results(
    tmp_path: Path,
) -> None:
    fixture = build_local_analysis_api_fixture(
        tmp_path,
        v2_dsm_only=True,
        include_third_epoch=True,
    )
    assert fixture.third is not None
    chronology = fixture.synthetic_epoch_chronology
    assert len(chronology) == 3
    lease = fixture._inspection_policy.resource_envelope.lease_duration_seconds
    assert fixture.synthetic_policy_admitted_at is not None
    previous_inspection = None
    previous_capture_end = None
    for capture_start, capture_end, sealed_at, inspection_reported_at in chronology:
        assert capture_start < capture_end < fixture._fixture_now
        assert capture_end <= sealed_at <= inspection_reported_at
        assert fixture.synthetic_policy_admitted_at <= inspection_reported_at
        if previous_capture_end is not None:
            assert previous_capture_end < capture_start
        if previous_inspection is not None:
            assert (inspection_reported_at - previous_inspection).total_seconds() > lease
        previous_capture_end = capture_end
        previous_inspection = inspection_reported_at
    object_server: ThreadingHTTPServer | None = None
    object_thread: Thread | None = None
    core_server: uvicorn.Server | None = None
    core_thread: Thread | None = None
    core_socket: socket.socket | None = None
    worker_client: ExternalAnalysisCoreClient | None = None
    replay_fixture = None
    fixture_closed = False
    try:

        class LoopbackObjectHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if not self.path.startswith("/objects/"):
                    self.send_error(404)
                    return
                try:
                    payload = fixture.storage.object_bytes(
                        unquote(self.path.removeprefix("/objects/"))
                    )
                except KeyError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/tiff")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        object_server = ThreadingHTTPServer(("127.0.0.1", 0), LoopbackObjectHandler)
        object_thread = Thread(target=object_server.serve_forever, daemon=True)
        object_thread.start()
        object_origin = f"http://127.0.0.1:{object_server.server_port}"
        fixture.set_loopback_object_origin(object_origin)

        listen_socket = socket.socket()
        core_socket = listen_socket
        listen_socket.bind(("127.0.0.1", 0))
        listen_socket.listen(128)
        core_origin = f"http://127.0.0.1:{listen_socket.getsockname()[1]}"
        server = uvicorn.Server(
            uvicorn.Config(fixture.app, log_level="warning", access_log=False)
        )
        core_server = server
        core_thread = Thread(target=lambda: server.run(sockets=[listen_socket]), daemon=True)
        core_thread.start()
        for _ in range(100):
            if core_server.started:
                break
            assert core_thread.is_alive(), "local Core server stopped during startup"
            time.sleep(0.02)
        assert core_server.started

        runtime_facts = fixture.app.state.external_analysis_wiring.facade._assessments._runtime
        envelope = fixture.app.state.external_analysis_wiring.calculations._resource_envelope
        runtime = ProcessingWorkerRuntimeIdentityV1(
            worker_executable_digest=runtime_facts.worker_executable_digest,
            worker_build_digest=runtime_facts.worker_build_digest,
            runtime_image_version=runtime_facts.runtime_image_version,
            runtime_image_oci_digest=runtime_facts.runtime_image_oci_digest,
            dependency_lock_digest=runtime_facts.dependency_lock_digest,
        )
        transport = ExternalObjectTransportPolicyV1(
            endpoints=(
                TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),
            ),
            max_header_bytes=16_384,
            max_object_bytes=envelope.max_input_bytes,
            max_chunk_bytes=min(65_536, envelope.max_input_bytes),
        )
        headers = fixture.operator_headers()
        analysis_url = (
            f"/v1/sites/{fixture.site_id}/work-areas/{fixture.work_area_id}/analyses"
        )
        t0_t1_body = _request_body(fixture.baseline, fixture.current)
        t1_t2_body = _request_body(fixture.current, fixture.third)

        with httpx.Client(base_url=core_origin, trust_env=False) as operator:
            first_request_at = datetime.now(UTC)
            assert fixture._fixture_now <= first_request_at
            assert all(item[3] <= first_request_at for item in chronology)
            first_created = operator.post(
                analysis_url,
                headers={**headers, "Idempotency-Key": "weekly-reuse-t0-t1"},
                json=t0_t1_body,
            )
            assert first_created.status_code == 202, first_created.text
            first_id = first_created.json()["analysisId"]
            assert first_created.json()["baseline"] == t0_t1_body["baseline"]
            assert first_created.json()["current"] == t0_t1_body["current"]
            assert first_created.json()["executionState"] == "QUEUED"
            assert run_once(
                worker_client := ExternalAnalysisCoreClient(
                    base_url=core_origin,
                    worker_token=fixture.worker_headers()["Authorization"].removeprefix(
                        "Bearer "
                    ),
                    worker_instance_id="weekly-reuse-worker",
                ),
                runtime,
                transport,
            )
            first_detail, first_result, first_evidence = _completed_analysis(
                operator,
                site_id=fixture.site_id,
                analysis_id=first_id,
                headers=headers,
            )
            first_payload = _nested(first_result, "result")
            assert _nested(first_payload, "metrics") == {
                "cutM3": pytest.approx(0.01),
                "fillM3": pytest.approx(0.01),
                "netM3": pytest.approx(0.0),
                "thresholdM": 0.0,
                "uncertaintyM3": None,
            }

            reused_key = operator.post(
                analysis_url,
                headers={**headers, "Idempotency-Key": "weekly-reuse-t0-t1"},
                json=t1_t2_body,
            )
            assert reused_key.status_code == 409, reused_key.text

            second_created = operator.post(
                analysis_url,
                headers={**headers, "Idempotency-Key": "weekly-reuse-t1-t2"},
                json=t1_t2_body,
            )
            assert second_created.status_code == 202, second_created.text
            second_id = second_created.json()["analysisId"]
            assert second_id != first_id
            assert second_created.json()["baseline"] == t1_t2_body["baseline"]
            assert second_created.json()["current"] == t1_t2_body["current"]
            assert second_created.json()["executionState"] == "QUEUED"
            assert run_once(worker_client, runtime, transport)
            second_detail, second_result, second_evidence = _completed_analysis(
                operator,
                site_id=fixture.site_id,
                analysis_id=second_id,
                headers=headers,
            )
            assert not run_once(worker_client, runtime, transport)

            assert first_detail["workAreaId"] == second_detail["workAreaId"] == (
                fixture.work_area_id
            )
            first_calculation = _nested(first_evidence, "calculation")
            second_calculation = _nested(second_evidence, "calculation")
            first_baseline = _nested(first_evidence, "baseline")
            first_current = _nested(first_evidence, "current")
            second_baseline = _nested(second_evidence, "baseline")
            second_current = _nested(second_evidence, "current")
            assert first_calculation["workAreaDefinitionDigest"] == (
                second_calculation["workAreaDefinitionDigest"]
            )
            assert first_calculation["policy"] == second_calculation["policy"]
            assert first_calculation["runtime"] == second_calculation["runtime"]
            assert first_current["selector"] == second_baseline["selector"]
            assert first_current["observedSha256"] == second_baseline["observedSha256"]
            assert first_current["inputDigest"] == second_baseline["inputDigest"]
            assert first_baseline["inspectionReportDigest"] == (
                fixture.synthetic_inspection_report_digests[0]
            )
            assert first_current["inspectionReportDigest"] == (
                fixture.synthetic_inspection_report_digests[1]
            )
            assert second_baseline["inspectionReportDigest"] == (
                fixture.synthetic_inspection_report_digests[1]
            )
            assert second_current["inspectionReportDigest"] == (
                fixture.synthetic_inspection_report_digests[2]
            )
            assert first_baseline["inputDigest"] != first_current["inputDigest"]
            assert second_baseline["inputDigest"] != second_current["inputDigest"]

            first_authority = _nested(first_detail, "authority")
            second_authority = _nested(second_detail, "authority")
            assert first_authority["admissionId"] != second_authority["admissionId"]
            assert first_authority["admissionDigest"] != second_authority["admissionDigest"]
            assert first_authority["calculationIdentityDigest"] != second_authority[
                "calculationIdentityDigest"
            ]
            assert first_authority["calculationRequestId"] != second_authority[
                "calculationRequestId"
            ]
            assert first_calculation["calculationId"] != second_calculation["calculationId"]
            first_payload = _nested(first_result, "result")
            second_payload = _nested(second_result, "result")
            assert first_payload["resultId"] != second_payload["resultId"]
            assert first_payload["reportDigest"] != second_payload["reportDigest"]
            assert first_payload["numericResultIdentityDigest"] != second_payload[
                "numericResultIdentityDigest"
            ]
            second_metrics = _nested(second_payload, "metrics")
            assert second_metrics["fillM3"] == pytest.approx(0.02)
            assert second_metrics["cutM3"] == pytest.approx(0.02)

            first_after_second = _completed_analysis(
                operator,
                site_id=fixture.site_id,
                analysis_id=first_id,
                headers=headers,
            )
            assert first_after_second == (first_detail, first_result, first_evidence)

        worker_client.close()
        worker_client = None
        core_server.should_exit = True
        core_thread.join(timeout=10)
        assert not core_thread.is_alive()
        core_server = None
        core_thread = None
        core_socket.close()
        core_socket = None
        fixture.close()
        fixture_closed = True

        replay_fixture = build_local_analysis_api_fixture(tmp_path, replay_of=fixture)
        replay_http = TestClient(replay_fixture.app)
        for analysis_id, prior_detail, prior_result, prior_evidence in (
            (first_id, first_detail, first_result, first_evidence),
            (second_id, second_detail, second_result, second_evidence),
        ):
            replay_detail = replay_http.get(
                f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}",
                headers=replay_fixture.operator_headers(),
            )
            replay_result = replay_http.get(
                f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/result",
                headers=replay_fixture.operator_headers(),
            )
            replay_evidence = replay_http.get(
                f"/v1/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
                headers=replay_fixture.operator_headers(),
            )
            assert (
                replay_detail.status_code
                == replay_result.status_code
                == replay_evidence.status_code
                == 200
            )
            assert replay_detail.json() == prior_detail
            assert replay_result.json() == prior_result
            assert replay_evidence.json() == prior_evidence
        replay_fixture.close()
        replay_fixture = None
    finally:
        if worker_client is not None:
            worker_client.close()
        if core_server is not None:
            core_server.should_exit = True
        if core_thread is not None:
            core_thread.join(timeout=10)
            assert not core_thread.is_alive()
        if core_socket is not None:
            core_socket.close()
        if object_server is not None:
            object_server.shutdown()
            object_server.server_close()
        if object_thread is not None:
            object_thread.join(timeout=10)
            assert not object_thread.is_alive()
        if replay_fixture is not None:
            replay_fixture.close()
        if not fixture_closed:
            fixture.close()
