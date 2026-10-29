"""Credential-rotation binding against the actual mounted Core.

This exercises the real assembled Core app (no network listener) through an
``httpx.ASGITransport`` wrapper that rotates a private synthetic token file
immediately after the actual acknowledged machine GET completes. The machine
and human credentials are the fixture's own generated synthetic test
identities; auth values are captured only as labels, never raw. The test
asserts on actual Core responses/headers and the durable task journal:
exactly one machine-principal task exists, a static human token creates
zero tasks, and idempotent retry with the same key/body returns the same
task without a second record.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tests" / "contract"))

from analysis_api_local_fixture import build_local_analysis_api_fixture  # noqa: E402

KEY = "real-core-race-key-1"


class _RotationTransport(httpx.AsyncBaseTransport):
    """ASGI transport that rotates the token file after the acked machine GET."""

    def __init__(
        self,
        app: Any,
        *,
        token_file: Path,
        machine_raw: str,
        human_raw: str,
    ) -> None:
        self._inner = httpx.ASGITransport(app=app)
        self._token_file = token_file
        self._machine_raw = machine_raw
        self._human_raw = human_raw
        self.requests: list[dict[str, Any]] = []
        self.bodies: dict[str, Any] = {}
        self.get_acks: list[bool] = []
        self.rotated = False

    def _who(self, request: httpx.Request) -> str:
        auth = request.headers.get("authorization", "")
        if auth == "Bearer " + self._machine_raw:
            return "machine"
        if auth == "Bearer " + self._human_raw:
            return "human"
        return "unknown"

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        who = self._who(request)
        entry: dict[str, Any] = {
            "method": request.method,
            "path": request.url.path,
            "who": who,
        }
        if request.method == "POST":
            entry["idempotency_key"] = request.headers.get("idempotency-key")
            try:
                entry["body"] = json.loads(request.content.decode("utf-8"))
            except (ValueError, UnicodeError):
                entry["body"] = None
        self.requests.append(entry)
        if request.method == "GET" and request.url.path.endswith(
            "/analysis-observations"
        ):
            self.get_acks.append(
                response.headers.get("X-KSI-External-AI-Egress") == "ALLOWED"
            )
            if (
                not self.rotated
                and response.status_code == 200
                and response.headers.get("X-KSI-External-AI-Egress") == "ALLOWED"
            ):
                # The actual machine GET is acknowledged by real Core; rotate
                # the file now, in the exact TOCTOU window before the POST.
                self._token_file.write_text(self._human_raw, encoding="ascii")
                self._token_file.chmod(0o600)
                self.rotated = True
        return response


def _posts(transport: _RotationTransport) -> list[dict[str, Any]]:
    return [r for r in transport.requests if r["method"] == "POST"]


def test_real_core_rotation_keeps_machine_task_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rotation after the real acked GET cannot divert the POST to human."""
    from ksi_analysis_mcp.config import AdapterConfig
    from ksi_analysis_mcp.core_client import CoreAdapterError, CoreAnalysisClient
    from ksi_core.auth import PrincipalKind

    fixture = build_local_analysis_api_fixture(tmp_path, ai_egress_allowed=True)
    try:
        machine_raw = fixture.mcp_client_headers()["Authorization"].removeprefix(
            "Bearer "
        )
        human_raw = fixture.operator_headers()["Authorization"].removeprefix("Bearer ")
        token_file = tmp_path / "token"
        token_file.write_text(machine_raw, encoding="ascii")
        token_file.chmod(0o600)
        transport = _RotationTransport(
            fixture.app,
            token_file=token_file,
            machine_raw=machine_raw,
            human_raw=human_raw,
        )
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
            core_origin="http://127.0.0.1:9",
            token_file=str(token_file),
            console_origin="http://localhost:3000",
        )
        client = CoreAnalysisClient(config)
        args = {
            "siteId": fixture.site_id,
            "idempotencyKey": KEY,
            "request": {"purpose": "OBSERVED_CHANGE"},
        }

        # 1. Rotation run: the file holds the human token by the time the
        # POST would be sent, but the snapshot must keep the POST on machine.
        result = asyncio.run(client.invoke("ksi_create_spatial_task", dict(args)))
        assert transport.rotated is True
        assert transport.get_acks == [True], transport.get_acks
        posts = _posts(transport)
        assert len(posts) == 1, transport.requests
        assert posts[0]["who"] == "machine"
        assert posts[0]["idempotency_key"] == KEY
        assert posts[0]["body"]["purpose"] == "OBSERVED_CHANGE"

        # 2. Durable Core state: exactly one record, created by the machine
        # principal — the rotated human credential mutated nothing.
        store = fixture.app.state.spatial_tasks
        assert len(store._records) == 1
        record = next(iter(store._records.values()))
        assert record.task.site_id == fixture.site_id
        assert record.task.task_id == result["task"]["taskId"]
        assert record.creator_kind == PrincipalKind.ANALYSIS_MCP_CLIENT.value
        assert record.creator_kind != PrincipalKind.OPERATOR.value

        # 3. Idempotent retry with the same key/body returns the same task
        # and writes no second record.
        token_file.write_text(machine_raw, encoding="ascii")
        token_file.chmod(0o600)
        retry = asyncio.run(client.invoke("ksi_create_spatial_task", dict(args)))
        assert retry["task"]["taskId"] == result["task"]["taskId"]
        assert len(store._records) == 1

        # 4. Static human token: the acknowledged preflight is refused, so
        # Core sees zero POSTs and the journal gains zero tasks.
        token_file.write_text(human_raw, encoding="ascii")
        token_file.chmod(0o600)
        before = len(_posts(transport))
        with pytest.raises(CoreAdapterError) as exc_info:
            asyncio.run(
                client.invoke(
                    "ksi_create_spatial_task",
                    {**args, "idempotencyKey": "real-core-human-key-9"},
                )
            )
        assert exc_info.value.code == "CORE_EGRESS_ACKNOWLEDGMENT_MISSING"
        assert "analysis-local-fixture" not in str(exc_info.value)
        assert len(_posts(transport)) == before
        assert len(store._records) == 1
    finally:
        fixture.close()
