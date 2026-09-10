"""Bounded, authenticated external report history keeps unavailable records visible."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from external_product_loop_fixture import build_graph, record_measurement, seed_original
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ksi_core.auth import AuthRegistry, mount_auth
from ksi_core.external_result_workflow_api import build_external_result_workflow_router
from test_external_result_review_proposals import _NOW, _TOKEN, _token_record


def _client(graph) -> TestClient:
    app = FastAPI()
    mount_auth(app, AuthRegistry([_token_record()]))
    app.include_router(
        build_external_result_workflow_router(
            graph.volumes,
            graph.service,
            clock=lambda: _NOW,
        )
    )
    return TestClient(app)


def test_scoped_history_and_exact_detail_retain_unavailable_source_rows(tmp_path: Path) -> None:
    graph = build_graph(tmp_path, seed_original(tmp_path))
    try:
        report = record_measurement(graph)
        headers = {"Authorization": f"Bearer {_TOKEN}"}
        with _client(graph) as client:
            history = client.get(
                "/v1/sites/site-a/external-relative-volume-reports?limit=1", headers=headers
            )
            assert history.status_code == 200, history.text
            history_body = history.json()
            assert history_body["nextCursor"] is None
            assert len(history_body["items"]) == 1
            item = history_body["items"][0]
            assert item["reportRef"] == report.report_id
            assert item["state"] == "AVAILABLE"
            assert item["result"] is not None
            assert item["result"]["reportRef"] == report.report_id
            assert item["result"]["reportDigest"] == report.report_digest
            assert item["result"]["currentWorkOrderId"] == graph.source.authority.current_work_order_id
            assert item["result"]["measurementStatus"] == "SUCCEEDED"
            exact = client.get(
                f"/v1/sites/site-a/observations/{report.report_id}", headers=headers
            )
            assert exact.status_code == 200, exact.text
            assert exact.json()["state"] == "AVAILABLE"
            assert exact.json()["result"]["reportRef"] == report.report_id

            assert client.get(
                f"/v1/sites/site-other/observations/{report.report_id}", headers=headers
            ).status_code == 404
            assert client.get(
                "/v1/sites/site-a/external-relative-volume-reports?after=unknown-report&limit=1",
                headers=headers,
            ).status_code == 404

            graph.volumes._authority_port.historical_authority = replace(  # noqa: SLF001
                graph.history.authority, decision_id="historical-source-withdrawn"
            )
            unavailable = client.get(
                "/v1/sites/site-a/external-relative-volume-reports?limit=1", headers=headers
            )
            assert unavailable.status_code == 200, unavailable.text
            assert unavailable.json() == {
                "items": [
                    {
                        "reportRef": report.report_id,
                        "state": "HISTORICAL_SOURCE_UNAVAILABLE",
                        "result": None,
                    }
                ],
                "nextCursor": None,
            }
            exact_unavailable = client.get(
                f"/v1/sites/site-a/observations/{report.report_id}", headers=headers
            )
            assert exact_unavailable.status_code == 200
            assert exact_unavailable.json() == {
                "state": "HISTORICAL_SOURCE_UNAVAILABLE",
                "result": None,
            }
    finally:
        graph.close()
