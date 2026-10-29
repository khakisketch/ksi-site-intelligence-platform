"""Pair binding for Analysis MCP create against the actual mounted Core.

This exercises the real assembled Core app (no network listener) through an
``httpx.ASGITransport`` wrapper. The machine credential is the fixture's own
generated synthetic test identity; auth values are captured only as labels,
never raw. It asserts on actual Core responses/headers and adapter behavior:

1. Positive: a legitimate create echoes the requested Site, WorkArea,
   baseline and current selectors verbatim, with the machine-channel egress
   acknowledgment on both the preflight read and the mutation.
2. Idempotent retry: the same key/body returns the same analysis without a
   second record (ambiguous-mutation semantics preserved: retry, never a
   silent replacement request).
3. Conflict preserved: the same key with a swapped pair surfaces Core's
   ``ANALYSIS_IDEMPOTENCY_CONFLICT`` — never ``INVALID_CORE_RESPONSE`` — and
   mutates nothing further. The pair binding applies to 2xx projections only.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests" / "contract"))

from analysis_api_local_fixture import build_local_analysis_api_fixture  # noqa: E402
from test_external_analysis_activation import _write_activation  # noqa: E402

KEY = "real-core-pair-key-1"


class _RecordingTransport(httpx.AsyncBaseTransport):
    """ASGI transport that records labels and egress acknowledgments."""

    def __init__(self, app: Any, *, machine_raw: str) -> None:
        self._inner = httpx.ASGITransport(app=app)
        self._machine_raw = machine_raw
        self.requests: list[dict[str, Any]] = []
        self.acks: list[bool] = []

    def _who(self, request: httpx.Request) -> str:
        return (
            "machine"
            if request.headers.get("authorization", "") == "Bearer " + self._machine_raw
            else "unknown"
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        entry: dict[str, Any] = {
            "method": request.method,
            "path": request.url.path,
            "who": self._who(request),
        }
        if request.method == "POST":
            entry["idempotency_key"] = request.headers.get("idempotency-key")
        self.requests.append(entry)
        if request.method in ("GET", "POST") and request.url.path.endswith(
            ("analysis-observations", "analyses")
        ):
            self.acks.append(response.headers.get("X-KSI-External-AI-Egress") == "ALLOWED")
        return response


def _posts(transport: _RecordingTransport) -> list[dict[str, Any]]:
    return [r for r in transport.requests if r["method"] == "POST"]


def _active_activation_factory(tmp_path: Path) -> Any:
    """Bind the activation writer to this test's directory (closure pattern)."""

    def active_activation(config: Any, worker: Any) -> Any:
        now = datetime.now(UTC)
        return _write_activation(
            tmp_path / "mcp-pair-activation",
            bindings={
                "organization_id": "org-a",
                "policy": config.policy,
                "runtime": config.runtime,
                "resource_envelope": config.resource_envelope,
                "worker_principal": worker,
            },
            activation_fields={
                "issuedAt": (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                "validUntil": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            },
        )[2]

    return active_activation


def test_real_core_create_echoes_pair_retry_is_idempotent_conflict_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real Core positive/retry/conflict through the adapter pair binding."""
    from ksi_analysis_mcp.config import AdapterConfig
    from ksi_analysis_mcp.core_client import CoreAdapterError, CoreAnalysisClient

    fixture = build_local_analysis_api_fixture(
        tmp_path, ai_egress_allowed=True, analysis_activation=_active_activation_factory(tmp_path)
    )
    try:
        machine_raw = fixture.mcp_client_headers()["Authorization"].removeprefix("Bearer ")
        token_file = tmp_path / "token"
        token_file.write_text(machine_raw, encoding="ascii")
        token_file.chmod(0o600)
        transport = _RecordingTransport(fixture.app, machine_raw=machine_raw)
        monkeypatch.setattr(
            AdapterConfig,
            "new_http_client",
            lambda self: httpx.AsyncClient(
                transport=transport,
                base_url=self.core_origin,
                timeout=httpx.Timeout(self.timeout_seconds),
                follow_redirects=False,
                trust_env=False,
            ),
        )
        config = AdapterConfig.from_values(
            core_origin="http://127.0.0.1:9", token_file=str(token_file)
        )
        client = CoreAnalysisClient(config)
        baseline = fixture.baseline.model_dump(by_alias=True, mode="json")
        current = fixture.current.model_dump(by_alias=True, mode="json")
        args = {
            "siteId": fixture.site_id,
            "workAreaId": fixture.work_area_id,
            "baseline": baseline,
            "current": current,
            "idempotencyKey": KEY,
        }

        # 1. Positive: the created view echoes the requested scope and pair.
        result = asyncio.run(client.invoke("ksi_create_analysis", dict(args)))
        assert result["siteId"] == fixture.site_id
        assert result["workAreaId"] == fixture.work_area_id
        assert result["baseline"] == baseline
        assert result["current"] == current
        analysis_id = result["analysisId"]
        assert analysis_id
        posts = [p for p in _posts(transport) if p["path"].endswith("/analyses")]
        assert len(posts) == 1 and posts[0]["who"] == "machine"
        assert posts[0]["idempotency_key"] == KEY
        assert transport.acks and all(transport.acks)

        # 2. Idempotent retry: same key/body returns the same analysis, and
        # the durable list holds exactly one record — no silent replacement.
        retry = asyncio.run(client.invoke("ksi_create_analysis", dict(args)))
        assert retry["analysisId"] == analysis_id
        assert retry["baseline"] == baseline and retry["current"] == current
        listing = asyncio.run(
            client.invoke("ksi_list_analyses", {"siteId": fixture.site_id, "limit": 50})
        )
        assert listing["siteId"] == fixture.site_id
        assert [item["analysisId"] for item in listing["items"]] == [analysis_id]

        # 3. Conflict preserved: the same key with a swapped pair is Core's
        # idempotency conflict, not an adapter scope refusal, and the
        # journal gains no second record.
        before = len(_posts(transport))
        with pytest.raises(CoreAdapterError, match="ANALYSIS_IDEMPOTENCY_CONFLICT") as exc_info:
            asyncio.run(
                client.invoke(
                    "ksi_create_analysis",
                    {**args, "baseline": current, "current": baseline},
                )
            )
        # No raw credential material ever surfaces in the typed error.
        assert machine_raw not in str(exc_info.value)
        assert len(_posts(transport)) == before + 1
        closing = asyncio.run(
            client.invoke("ksi_list_analyses", {"siteId": fixture.site_id, "limit": 50})
        )
        assert [item["analysisId"] for item in closing["items"]] == [analysis_id]
    finally:
        fixture.close()
