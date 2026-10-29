"""Tenant scope-echo binding for Analysis MCP read/mutation responses.

Core remains authoritative for grants, consent and rights on every request.
This suite proves the adapter's own projection boundary: a Core response that
echoes a *different* Site, WorkArea, Analysis or selector pair than the caller
asked for must fail closed with ``INVALID_CORE_RESPONSE`` and the foreign
payload must never become MCP structured output for the external AI host.

Note: detail GETs address ``/v2/sites/{site}/analyses/{analysis}`` with no
WorkArea in the request, so the adapter binds Site+Analysis there; the
WorkArea projection stays Core-owned (Core builds the view from the same
scoped intent). The evidence page model likewise carries no Site echo, so
only the Analysis binding is checkable on that lane.

Real loopback HTTP only (no external network). Auth values are generated
fixture labels only, never real credentials. The stub always sends the
machine-channel ``X-KSI-External-AI-Egress: ALLOWED`` header so the tests
isolate the scope-echo seam from the egress seam.
"""

from __future__ import annotations

import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

SITE = "site-a"
AREA = "area-a"
ANALYSIS = "an-1"
FOREIGN_SITE = "site-evil"
FOREIGN_AREA = "area-evil"
FOREIGN_ANALYSIS = "an-evil"

BASELINE = {
    "workOrderId": "wo-1",
    "submissionRef": "ers-v1-" + "11" * 32,
    "revision": 1,
}
CURRENT = {
    "workOrderId": "wo-1",
    "submissionRef": "ers-v1-" + "22" * 32,
    "revision": 2,
}
FOREIGN_BASELINE = {
    "workOrderId": "wo-9",
    "submissionRef": "ers-v1-" + "99" * 32,
    "revision": 9,
}
FOREIGN_CURRENT = {
    "workOrderId": "wo-9",
    "submissionRef": "ers-v1-" + "88" * 32,
    "revision": 9,
}


def _analysis_view(
    site: str = SITE,
    area: str = AREA,
    analysis_id: str = ANALYSIS,
    baseline: dict[str, Any] = BASELINE,
    current: dict[str, Any] = CURRENT,
) -> dict[str, Any]:
    return {
        "analysisId": analysis_id,
        "siteId": site,
        "workAreaId": area,
        "baseline": baseline,
        "current": current,
        "executionState": "QUEUED",
        "suitabilityState": "REMEDIATION_REQUIRED",
        "blockers": [],
        "result": None,
        "evidenceRevision": 1,
        "evidenceDigest": "sha256:" + "ee" * 32,
        "evidenceHref": f"/v2/sites/{site}/analyses/{analysis_id}/evidence",
        "coverageHref": None,
        "createdAt": "2026-10-26T00:00:00Z",
    }


def _list_item(
    site: str = SITE, area: str = AREA, analysis_id: str = ANALYSIS
) -> dict[str, Any]:
    return {
        "analysisId": analysis_id,
        "siteId": site,
        "workAreaId": area,
        "executionState": "QUEUED",
        "suitabilityState": "REMEDIATION_REQUIRED",
        "createdAt": "2026-10-26T00:00:00Z",
        "resultId": None,
        "metrics": None,
        "limitationCount": 0,
        "analysisHref": f"/v2/sites/{site}/analyses/{analysis_id}",
        "newerSiblingAnalysisIds": [],
    }


def _evidence_page(analysis_id: str = ANALYSIS) -> dict[str, Any]:
    return {
        "analysisId": analysis_id,
        "evidenceRevision": 1,
        "evidenceDigest": "sha256:" + "ee" * 32,
        "items": [],
        "nextCursor": None,
    }


def _readiness(
    site: str = SITE,
    area: str = AREA,
    baseline: dict[str, Any] = BASELINE,
    current: dict[str, Any] = CURRENT,
) -> dict[str, Any]:
    return {
        "contractVersion": "analysis-readiness.v1",
        "siteId": site,
        "workAreaId": area,
        "baseline": baseline,
        "current": current,
        "suitabilityState": "BLOCKED",
        "blockers": [{"code": "RECONSTRUCTION_NOT_SEALED"}],
        "checkedAt": "2026-10-26T00:00:00Z",
        "calculationIdentityDigest": None,
        "coverageCheck": "REQUIRES_WORKER_VALIDATION",
    }


def _serve(
    tmp_path: Path, responder: Any
) -> tuple[Any, ThreadingHTTPServer, Thread]:
    from ksi_analysis_mcp.config import AdapterConfig
    from ksi_analysis_mcp.core_client import CoreAnalysisClient

    token_file = tmp_path / "token"
    token_file.write_text("test-token", encoding="ascii")
    token_file.chmod(0o600)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            self._send(responder("GET", self.path))

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            self._send(responder("POST", self.path), status=202)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = CoreAnalysisClient(
        AdapterConfig.from_values(
            core_origin=f"http://127.0.0.1:{server.server_port}",
            token_file=str(token_file),
        )
    )
    return client, server, thread


def _stop(server: ThreadingHTTPServer, thread: Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.mark.parametrize(
    ("tool", "args", "foreign_payload"),
    [
        (
            "ksi_get_analysis",
            {"siteId": SITE, "analysisId": ANALYSIS},
            _analysis_view(site=FOREIGN_SITE),
        ),
        (
            "ksi_get_analysis_result",
            {"siteId": SITE, "analysisId": ANALYSIS},
            _analysis_view(site=FOREIGN_SITE),
        ),
        (
            "ksi_get_analysis",
            {"siteId": SITE, "analysisId": ANALYSIS},
            _analysis_view(site=FOREIGN_SITE, analysis_id=FOREIGN_ANALYSIS),
        ),
        pytest.param(
            "ksi_get_analysis",
            {"siteId": SITE, "analysisId": ANALYSIS},
            _analysis_view(analysis_id=FOREIGN_ANALYSIS),
            id="get-same-site-foreign-id",
        ),
        pytest.param(
            "ksi_get_analysis_result",
            {"siteId": SITE, "analysisId": ANALYSIS},
            _analysis_view(analysis_id=FOREIGN_ANALYSIS),
            id="get-result-same-site-foreign-id",
        ),
        (
            "ksi_list_analyses",
            {"siteId": SITE, "limit": 50},
            {"siteId": FOREIGN_SITE, "items": [], "nextCursor": None},
        ),
        (
            "ksi_list_analyses",
            {"siteId": SITE, "limit": 50},
            {
                "siteId": SITE,
                "items": [_list_item(site=FOREIGN_SITE)],
                "nextCursor": None,
            },
        ),
        (
            "ksi_get_analysis_evidence",
            {"siteId": SITE, "analysisId": ANALYSIS, "limit": 32},
            _evidence_page(analysis_id=FOREIGN_ANALYSIS),
        ),
        (
            "ksi_check_analysis_readiness",
            {
                "siteId": SITE,
                "workAreaId": AREA,
                "baseline": BASELINE,
                "current": CURRENT,
            },
            _readiness(site=FOREIGN_SITE),
        ),
        (
            "ksi_check_analysis_readiness",
            {
                "siteId": SITE,
                "workAreaId": AREA,
                "baseline": BASELINE,
                "current": CURRENT,
            },
            _readiness(area=FOREIGN_AREA),
        ),
        (
            "ksi_check_analysis_readiness",
            {
                "siteId": SITE,
                "workAreaId": AREA,
                "baseline": BASELINE,
                "current": CURRENT,
            },
            _readiness(baseline=FOREIGN_BASELINE),
        ),
        (
            "ksi_create_analysis",
            {
                "siteId": SITE,
                "workAreaId": AREA,
                "baseline": BASELINE,
                "current": CURRENT,
                "idempotencyKey": "scope-key-1",
            },
            _analysis_view(area=FOREIGN_AREA),
        ),
        (
            "ksi_create_analysis",
            {
                "siteId": SITE,
                "workAreaId": AREA,
                "baseline": BASELINE,
                "current": CURRENT,
                "idempotencyKey": "scope-key-2",
            },
            _analysis_view(baseline=FOREIGN_BASELINE),
        ),
        (
            "ksi_create_analysis",
            {
                "siteId": SITE,
                "workAreaId": AREA,
                "baseline": BASELINE,
                "current": CURRENT,
                "idempotencyKey": "scope-key-3",
            },
            _analysis_view(current=FOREIGN_CURRENT),
        ),
    ],
)
def test_foreign_scope_echo_fails_closed(
    tmp_path: Path, tool: str, args: dict[str, Any], foreign_payload: dict[str, Any]
) -> None:
    """A Core echo for another tenant scope never becomes MCP output."""
    from ksi_analysis_mcp.core_client import CoreAdapterError

    def responder(method: str, path: str) -> dict[str, Any]:
        if path.endswith("/analysis-observations"):
            return {"items": []}
        return foreign_payload

    client, server, thread = _serve(tmp_path, responder)
    try:
        with pytest.raises(CoreAdapterError, match="INVALID_CORE_RESPONSE"):
            asyncio.run(client.invoke(tool, dict(args)))
    finally:
        _stop(server, thread)


@pytest.mark.parametrize(
    ("tool", "args", "honest_payload"),
    [
        (
            "ksi_get_analysis",
            {"siteId": SITE, "analysisId": ANALYSIS},
            _analysis_view(),
        ),
        (
            "ksi_get_analysis_result",
            {"siteId": SITE, "analysisId": ANALYSIS},
            _analysis_view(),
        ),
        (
            "ksi_list_analyses",
            {"siteId": SITE, "limit": 50},
            {"siteId": SITE, "items": [_list_item()], "nextCursor": None},
        ),
        (
            "ksi_get_analysis_evidence",
            {"siteId": SITE, "analysisId": ANALYSIS, "limit": 32},
            _evidence_page(),
        ),
        (
            "ksi_check_analysis_readiness",
            {
                "siteId": SITE,
                "workAreaId": AREA,
                "baseline": BASELINE,
                "current": CURRENT,
            },
            _readiness(),
        ),
        (
            "ksi_create_analysis",
            {
                "siteId": SITE,
                "workAreaId": AREA,
                "baseline": BASELINE,
                "current": CURRENT,
                "idempotencyKey": "scope-key-honest",
            },
            _analysis_view(),
        ),
    ],
)
def test_honest_scope_echo_passes_through(
    tmp_path: Path, tool: str, args: dict[str, Any], honest_payload: dict[str, Any]
) -> None:
    """The same-scope Core echo the boundary keeps working stays usable."""

    def responder(method: str, path: str) -> dict[str, Any]:
        if path.endswith("/analysis-observations"):
            return {"items": []}
        return honest_payload

    client, server, thread = _serve(tmp_path, responder)
    try:
        result = asyncio.run(client.invoke(tool, dict(args)))
        assert result["siteId"] == SITE if "siteId" in result else True
        if tool == "ksi_get_analysis_evidence":
            assert result["analysisId"] == ANALYSIS
    finally:
        _stop(server, thread)
