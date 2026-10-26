"""Bounded stdio MCP adapter contract tests."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import time
from contextlib import suppress
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest


def test_mcp_config_accepts_only_loopback_http_and_private_absolute_token_file(
    tmp_path: Path,
) -> None:
    """A config regression must not let the local adapter use DNS, public HTTP, or loose secrets."""
    from ksi_analysis_mcp.config import AdapterConfig, AdapterConfigurationError

    token_file = tmp_path / "token"
    token_file.write_text("test-token\n", encoding="utf-8")
    token_file.chmod(0o600)
    config = AdapterConfig.from_values(
        core_origin="http://127.0.0.1:8080", token_file=str(token_file)
    )
    assert config.core_origin == "http://127.0.0.1:8080"
    assert config.read_token() == "test-token"

    with pytest.raises(AdapterConfigurationError, match="literal IP"):
        AdapterConfig.from_values(core_origin="https://core.internal", token_file=str(token_file))
    with pytest.raises(AdapterConfigurationError, match="HTTPS"):
        AdapterConfig.from_values(core_origin="http://192.0.2.10", token_file=str(token_file))
    token_file.chmod(0o644)
    with pytest.raises(AdapterConfigurationError, match="owner-protected"):
        AdapterConfig.from_values(core_origin="http://127.0.0.1:8080", token_file=str(token_file))
    with pytest.raises(AdapterConfigurationError, match="absolute"):
        AdapterConfig.from_values(core_origin="http://127.0.0.1:8080", token_file="token")
    oversized = tmp_path / "oversized-token"
    oversized.write_bytes(b"x" * 4097 + b"\n")
    oversized.chmod(0o600)
    with pytest.raises(AdapterConfigurationError, match="invalid opaque credential"):
        AdapterConfig.from_values(
            core_origin="http://127.0.0.1:8080", token_file=str(oversized)
        ).read_token()


def test_mcp_config_never_uses_environment_proxy_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proxy variables must not turn the bounded local adapter into arbitrary network egress."""
    from ksi_analysis_mcp.config import AdapterConfig

    token_file = tmp_path / "token"
    token_file.write_text("test-token", encoding="utf-8")
    token_file.chmod(0o600)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9999")
    config = AdapterConfig.from_values(
        core_origin="https://192.0.2.10:8443", token_file=os.fspath(token_file)
    )
    assert config.http_client_kwargs()["trust_env"] is False
    assert config.http_client_kwargs()["follow_redirects"] is False


def test_mcp_v2_page_tools_accept_bounded_cursor_arguments() -> None:
    from ksi_analysis_mcp.core_client import CoreAdapterError, validate_tool_arguments

    listing = validate_tool_arguments(
        "ksi_list_analyses",
        {"siteId": "site-a", "limit": 50, "cursor": "opaque-list-cursor"},
    )
    assert listing.model_dump(by_alias=True) == {
        "siteId": "site-a",
        "limit": 50,
        "cursor": "opaque-list-cursor",
    }
    evidence = validate_tool_arguments(
        "ksi_get_analysis_evidence",
        {
            "siteId": "site-a",
            "analysisId": "analysis-a",
            "limit": 32,
            "cursor": "opaque-evidence-cursor",
        },
    )
    assert evidence.model_dump(by_alias=True) == {
        "siteId": "site-a",
        "analysisId": "analysis-a",
        "limit": 32,
        "cursor": "opaque-evidence-cursor",
    }
    for name, arguments in (
        ("ksi_list_analyses", {"siteId": "site-a", "limit": 51}),
        (
            "ksi_get_analysis_evidence",
            {"siteId": "site-a", "analysisId": "analysis-a", "limit": 33},
        ),
    ):
        with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
            validate_tool_arguments(name, arguments)


def test_mcp_client_rejects_unsafe_identifiers_and_unacknowledged_or_invalid_core_json(
    tmp_path: Path,
) -> None:
    """A path traversal, missing egress proof, or malformed shared DTO must not reach an agent."""
    from ksi_analysis_mcp.config import AdapterConfig
    from ksi_analysis_mcp.core_client import (
        CoreAdapterError,
        CoreAnalysisClient,
        validate_tool_arguments,
    )

    class CoreHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.endswith("site-no-ack/analysis-observations"):
                body = b'{"items":[]}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.endswith("site-bad-encoding/analysis-observations"):
                body = b"\xff"
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
                self.end_headers()
                self.wfile.write(body)
                return
            body = b'{"notItems":[]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CoreHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "token"
    token_file.write_text("test-token", encoding="ascii")
    token_file.chmod(0o600)
    client = CoreAnalysisClient(
        AdapterConfig.from_values(
            core_origin=f"http://127.0.0.1:{server.server_port}", token_file=str(token_file)
        )
    )
    try:
        with pytest.raises(CoreAdapterError, match="CORE_EGRESS_ACKNOWLEDGMENT_MISSING"):
            asyncio.run(client.invoke("ksi_list_analysis_observations", {"siteId": "site-no-ack"}))
        with pytest.raises(CoreAdapterError, match="INVALID_CORE_RESPONSE"):
            asyncio.run(client.invoke("ksi_list_analysis_observations", {"siteId": "site-bad"}))
        with pytest.raises(CoreAdapterError, match="INVALID_CORE_RESPONSE"):
            asyncio.run(
                client.invoke("ksi_list_analysis_observations", {"siteId": "site-bad-encoding"})
            )
        for unsafe_site_id in (".", "..", "site/a", "site\x00a"):
            with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
                validate_tool_arguments("ksi_list_analyses", {"siteId": unsafe_site_id})
        with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
            validate_tool_arguments(
                "ksi_create_analysis",
                {
                    "siteId": "site-a",
                    "workAreaId": "area-a",
                    "baseline": {
                        "workOrderId": "baseline",
                        "submissionRef": "ers-v1-" + "a" * 64,
                        "revision": 1,
                    },
                    "current": {
                        "workOrderId": "current",
                        "submissionRef": "ers-v1-" + "b" * 64,
                        "revision": 1,
                    },
                },
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mcp_create_stops_before_post_when_observation_preflight_lacks_ack(
    tmp_path: Path,
) -> None:
    """The mandatory acknowledged observation preflight must precede every mutation."""
    from ksi_analysis_mcp.config import AdapterConfig
    from ksi_analysis_mcp.core_client import CoreAdapterError, CoreAnalysisClient

    post_count = 0

    class CoreHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            body = b'{"items":[]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            nonlocal post_count
            post_count += 1
            self.send_response(500)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CoreHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "token"
    token_file.write_text("test-token", encoding="ascii")
    token_file.chmod(0o600)
    client = CoreAnalysisClient(
        AdapterConfig.from_values(
            core_origin=f"http://127.0.0.1:{server.server_port}", token_file=str(token_file)
        )
    )
    arguments = {
        "siteId": "site-a",
        "workAreaId": "area-a",
        "baseline": {
            "workOrderId": "baseline",
            "submissionRef": "ers-v1-" + "a" * 64,
            "revision": 1,
        },
        "current": {
            "workOrderId": "current",
            "submissionRef": "ers-v1-" + "b" * 64,
            "revision": 1,
        },
        "idempotencyKey": "unchanged-mcp-key",
    }
    try:
        with pytest.raises(CoreAdapterError, match="CORE_EGRESS_ACKNOWLEDGMENT_MISSING"):
            asyncio.run(client.invoke("ksi_create_analysis", arguments))
        assert post_count == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mcp_create_rejects_unsafe_keys_before_network_and_preserves_valid_key(
    tmp_path: Path,
) -> None:
    """A key must be a printable header value before preflight or POST can start."""
    from ksi_analysis_mcp.config import AdapterConfig
    from ksi_analysis_mcp.core_client import CoreAdapterError, CoreAnalysisClient

    get_count = 0
    post_count = 0
    received_key: str | None = None

    class CoreHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            nonlocal get_count
            get_count += 1
            body = b'{"items":[]}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            nonlocal post_count, received_key
            post_count += 1
            received_key = self.headers.get("Idempotency-Key")
            body = b"{}"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CoreHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "token"
    token_file.write_text("test-token", encoding="ascii")
    token_file.chmod(0o600)
    client = CoreAnalysisClient(
        AdapterConfig.from_values(
            core_origin=f"http://127.0.0.1:{server.server_port}", token_file=str(token_file)
        )
    )

    def arguments(key: str) -> dict[str, object]:
        return {
            "siteId": "site-a",
            "workAreaId": "area-a",
            "baseline": {
                "workOrderId": "baseline",
                "submissionRef": "ers-v1-" + "a" * 64,
                "revision": 1,
            },
            "current": {
                "workOrderId": "current",
                "submissionRef": "ers-v1-" + "b" * 64,
                "revision": 1,
            },
            "idempotencyKey": key,
        }

    try:
        for invalid_key in ("   ", "\u00e9", "bad\rkey", "bad\nkey", " leading", "trailing "):
            with pytest.raises(CoreAdapterError, match="INVALID_TOOL_ARGUMENTS"):
                asyncio.run(client.invoke("ksi_create_analysis", arguments(invalid_key)))
        assert (get_count, post_count) == (0, 0)

        valid_key = "same printable ascii key 01"
        assert (
            asyncio.run(
                client._request("POST", "/v1/test", json_body={}, idempotency_key=valid_key)
            )
            == {}
        )
        assert received_key == valid_key
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_mcp_client_maps_transport_and_core_failures_without_raw_response_content(
    tmp_path: Path,
) -> None:
    """Redirects, caps, timeouts, and error bodies stay outside the MCP surface."""
    from ksi_analysis_mcp.config import AdapterConfig
    from ksi_analysis_mcp.core_client import CoreAdapterError, CoreAnalysisClient

    secret = "TOP_SECRET_RESPONSE_BODY"

    class CoreHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/v1/sites/timeout/"):
                time.sleep(0.1)
                body = b'{"items":[]}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
                self.end_headers()
                with suppress(BrokenPipeError):
                    self.wfile.write(body)
                return
            if self.path.startswith("/v1/sites/oversize/"):
                body = b'{"items":[]}' * 32
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.startswith("/v1/sites/wide/"):
                wide = "界" * (512 * 1024 // len("界".encode()) + 1)
                body = json.dumps({"wide": wide}, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.startswith("/v1/sites/redirect/"):
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1/other")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if self.path.startswith("/v1/sites/egress/"):
                body = b'{"detail":"AI_EGRESS_NOT_ALLOWED"}'
                self.send_response(403)
            elif self.path.startswith("/v1/sites/permission/"):
                body = b'{"detail":"permission denied"}'
                self.send_response(403)
            else:
                body = json.dumps({"detail": secret}).encode()
                self.send_response(500)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CoreHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "token"
    token_file.write_text("test-token", encoding="ascii")
    token_file.chmod(0o600)
    base = AdapterConfig.from_values(
        core_origin=f"http://127.0.0.1:{server.server_port}", token_file=str(token_file)
    )

    def invoke(site_id: str, config: AdapterConfig = base) -> CoreAdapterError:
        with pytest.raises(CoreAdapterError) as raised:
            asyncio.run(
                CoreAnalysisClient(config).invoke(
                    "ksi_list_analysis_observations", {"siteId": site_id}
                )
            )
        return raised.value

    try:
        assert invoke("timeout", replace(base, timeout_seconds=0.01)).code == "CORE_TIMEOUT"
        assert (
            invoke("oversize", replace(base, max_response_bytes=8)).code
            == "CORE_RESPONSE_TOO_LARGE"
        )
        assert invoke("redirect").code == "CORE_REDIRECT_REJECTED"
        with pytest.raises(CoreAdapterError, match="CORE_RESPONSE_TOO_LARGE"):
            asyncio.run(
                CoreAnalysisClient(replace(base, max_response_bytes=2 * 1024 * 1024)).invoke(
                    "ksi_list_analysis_observations", {"siteId": "wide"}
                )
            )
        assert invoke("egress").code == "AI_EGRESS_NOT_ALLOWED"
        assert invoke("permission").code == "CORE_PERMISSION_DENIED"
        error = invoke("server-error")
        assert error.code == "CORE_UNAVAILABLE"
        assert secret not in str(error)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_official_sdk_stdio_server_lists_only_analysis_tools_and_requires_core_ack(
    tmp_path: Path,
) -> None:
    """A missing tool, egress marker, or acknowledgement must fail this test."""
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    observed_headers: list[dict[str, str]] = []

    class CoreHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            observed_headers.append(dict(self.headers))
            if self.path != "/v1/sites/site-a/analysis-observations":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps({"items": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CoreHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "token"
    token_file.write_text("stdio-test-token", encoding="ascii")
    token_file.chmod(0o600)

    async def exercise() -> None:
        command = os.environ.get("KSI_MCP_TEST_PYTHON")
        if command is None:
            command = sys.executable
        parameters = StdioServerParameters(
            command=command,
            args=["-m", "ksi_analysis_mcp.server"],
            env={
                "KSI_ANALYSIS_MCP_CORE_ORIGIN": f"http://127.0.0.1:{server.server_port}",
                "KSI_ANALYSIS_MCP_TOKEN_FILE": str(token_file),
            },
        )
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "ksi_list_analysis_observations",
                "ksi_list_analyses",
                "ksi_create_analysis",
                "ksi_check_analysis_readiness",
                "ksi_get_analysis",
                "ksi_get_analysis_result",
                "ksi_get_analysis_evidence",
            }
            assert all(
                tool.annotations and tool.annotations.open_world_hint is False
                for tool in tools.tools
            )
            assert all(tool.output_schema is not None for tool in tools.tools)
            result = await session.call_tool("ksi_list_analysis_observations", {"siteId": "site-a"})
            assert result.is_error is False
            assert result.structured_content == {"items": []}
            denied = await session.call_tool(
                "ksi_list_analysis_observations", {"siteId": "site-not-found"}
            )
            assert denied.is_error is True
            assert denied.structured_content == {"code": "ANALYSIS_RESOURCE_NOT_FOUND"}

    try:
        asyncio.run(exercise())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    normalized_headers = {key.lower(): value for key, value in observed_headers[0].items()}
    assert "x-ksi-access-purpose" not in normalized_headers
    assert normalized_headers["authorization"] == "Bearer stdio-test-token"


def test_mcp_preserves_expected_core_conflict_codes_for_restart(tmp_path: Path) -> None:
    """Known V2 cursor/snapshot conflicts stay actionable without exposing arbitrary detail."""
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    class CoreHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/v1/sites/site-post/analysis-observations":
                body = b'{"items":[]}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-KSI-External-AI-Egress", "ALLOWED")
                self.end_headers()
                self.wfile.write(body)
                return
            detail_by_path = {
                "/v2/sites/site-list-stale/analyses?limit=50": "ANALYSIS_CURSOR_STALE",
                "/v2/sites/site-evidence-stale/analyses/analysis-a/evidence?limit=32": (
                    "ANALYSIS_EVIDENCE_CURSOR_STALE"
                ),
                "/v2/sites/site-snapshot/analyses/analysis-a": "ANALYSIS_SNAPSHOT_CHANGED",
                "/v2/sites/site-unknown/analyses?limit=50": "SECRET_INTERNAL_CONFLICT_DETAIL",
                "/v2/sites/site-idempotency/analyses?limit=50": ("ANALYSIS_IDEMPOTENCY_CONFLICT"),
                "/v1/sites/site-v1-stale/analysis-observations": "ANALYSIS_CURSOR_STALE",
            }
            detail = detail_by_path.get(self.path, "NOT_FOUND")
            body = json.dumps({"detail": detail}).encode("utf-8")
            self.send_response(409)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # noqa: N802
            body = b'{"detail":"ANALYSIS_IDEMPOTENCY_CONFLICT"}'
            self.send_response(409)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), CoreHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token_file = tmp_path / "token"
    token_file.write_text("stdio-conflict-test-token", encoding="ascii")
    token_file.chmod(0o600)

    async def exercise() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "ksi_analysis_mcp.server"],
            env={
                "KSI_ANALYSIS_MCP_CORE_ORIGIN": f"http://127.0.0.1:{server.server_port}",
                "KSI_ANALYSIS_MCP_TOKEN_FILE": str(token_file),
            },
        )
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            requests = (
                ("ksi_list_analyses", {"siteId": "site-list-stale"}, "ANALYSIS_CURSOR_STALE"),
                (
                    "ksi_get_analysis_evidence",
                    {"siteId": "site-evidence-stale", "analysisId": "analysis-a"},
                    "ANALYSIS_EVIDENCE_CURSOR_STALE",
                ),
                (
                    "ksi_get_analysis",
                    {"siteId": "site-snapshot", "analysisId": "analysis-a"},
                    "ANALYSIS_SNAPSHOT_CHANGED",
                ),
                (
                    "ksi_list_analyses",
                    {"siteId": "site-unknown"},
                    "CORE_CONFLICT",
                ),
                (
                    "ksi_list_analyses",
                    {"siteId": "site-idempotency"},
                    "CORE_CONFLICT",
                ),
                (
                    "ksi_list_analysis_observations",
                    {"siteId": "site-v1-stale"},
                    "CORE_CONFLICT",
                ),
                (
                    "ksi_create_analysis",
                    {
                        "siteId": "site-post",
                        "workAreaId": "area-a",
                        "baseline": {
                            "workOrderId": "baseline",
                            "submissionRef": "ers-v1-" + "a" * 64,
                            "revision": 1,
                        },
                        "current": {
                            "workOrderId": "current",
                            "submissionRef": "ers-v1-" + "b" * 64,
                            "revision": 1,
                        },
                        "idempotencyKey": "stable-retry-key",
                    },
                    "ANALYSIS_IDEMPOTENCY_CONFLICT",
                ),
            )
            for name, arguments, expected_code in requests:
                result = await session.call_tool(name, arguments)
                assert result.is_error is True
                assert result.structured_content == {"code": expected_code}
                assert "SECRET_INTERNAL_CONFLICT_DETAIL" not in str(result.model_dump())

    try:
        asyncio.run(exercise())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_official_sdk_runtime_token_file_failure_is_safe_typed_error(tmp_path: Path) -> None:
    """A token revoked after startup must not turn an MCP tool call into a traceback."""
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    token_file = tmp_path / "runtime-token"
    token_file.write_text("runtime-token-secret", encoding="ascii")
    token_file.chmod(0o600)

    async def exercise() -> None:
        command = os.environ.get("KSI_MCP_TEST_PYTHON")
        if command is None:
            command = sys.executable
        parameters = StdioServerParameters(
            command=command,
            args=["-m", "ksi_analysis_mcp.server"],
            env={
                "KSI_ANALYSIS_MCP_CORE_ORIGIN": "http://127.0.0.1:1",
                "KSI_ANALYSIS_MCP_TOKEN_FILE": str(token_file),
            },
        )
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            token_file.unlink()
            result = await session.call_tool("ksi_list_analysis_observations", {"siteId": "site-a"})
            assert result.is_error is True
            assert result.structured_content == {"code": "CORE_CREDENTIAL_UNAVAILABLE"}
            rendered = json.dumps(result.model_dump(mode="json"))
            assert str(token_file) not in rendered
            assert "runtime-token-secret" not in rendered
            assert "Traceback" not in rendered

    asyncio.run(exercise())


def test_mcp_create_reuses_the_real_core_result_and_evidence_after_worker_completion(
    tmp_path: Path,
) -> None:
    """An MCP retry must address the same Core calculation, never a client-side result."""
    import httpx
    import uvicorn
    from analysis_api_local_fixture import build_local_analysis_api_fixture
    from ksi_processing_controller.external_analysis_core_client import ExternalAnalysisCoreClient
    from ksi_processing_controller.external_analysis_worker import (
        ProcessingWorkerRuntimeIdentityV1,
        run_once,
    )
    from ksi_processing_controller.external_object_streams import (
        ExternalObjectTransportPolicyV1,
        TrustedObjectEndpointV1,
    )
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from test_external_analysis_activation import _write_activation

    def active_activation(config: Any, worker: Any) -> Any:
        now = datetime.now(UTC)
        return _write_activation(
            tmp_path / "mcp-active-analysis-activation",
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

    fixture = build_local_analysis_api_fixture(
        tmp_path, ai_egress_allowed=True, analysis_activation=active_activation
    )
    object_server: ThreadingHTTPServer | None = None
    object_thread: Thread | None = None
    core_server: uvicorn.Server | None = None
    core_thread: Thread | None = None
    core_socket: socket.socket | None = None
    worker: ExternalAnalysisCoreClient | None = None
    try:

        class ObjectHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                from urllib.parse import unquote

                if not self.path.startswith("/objects/"):
                    self.send_error(404)
                    return
                try:
                    body = fixture.storage.object_bytes(
                        unquote(self.path.removeprefix("/objects/"))
                    )
                except KeyError:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/tiff")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        object_server = ThreadingHTTPServer(("127.0.0.1", 0), ObjectHandler)
        object_thread = Thread(target=object_server.serve_forever, daemon=True)
        object_thread.start()
        object_origin = f"http://127.0.0.1:{object_server.server_port}"
        fixture.set_loopback_object_origin(object_origin)

        core_socket = socket.socket()
        core_socket.bind(("127.0.0.1", 0))
        core_socket.listen(128)
        core_origin = f"http://127.0.0.1:{core_socket.getsockname()[1]}"
        core_server = uvicorn.Server(
            uvicorn.Config(fixture.app, log_level="warning", access_log=False)
        )
        core_thread = Thread(target=lambda: core_server.run(sockets=[core_socket]), daemon=True)
        core_thread.start()
        for _ in range(100):
            if core_server.started:
                break
            assert core_thread.is_alive(), "local Core stopped during startup"
            time.sleep(0.02)
        assert core_server.started

        token_file = tmp_path / "mcp-token"
        token_file.write_text(
            fixture.mcp_client_headers()["Authorization"].removeprefix("Bearer "), encoding="ascii"
        )
        token_file.chmod(0o600)
        create_arguments: dict[str, object] = {
            "siteId": fixture.site_id,
            "workAreaId": fixture.work_area_id,
            "baseline": fixture.baseline.model_dump(by_alias=True, mode="json"),
            "current": fixture.current.model_dump(by_alias=True, mode="json"),
            "idempotencyKey": "mcp-real-worker-loop",
        }

        viewer_token_file = tmp_path / "viewer-token"
        viewer_token_file.write_text(
            fixture.viewer_headers()["Authorization"].removeprefix("Bearer "), encoding="ascii"
        )
        viewer_token_file.chmod(0o600)

        async def mcp_call(
            name: str,
            arguments: dict[str, object],
            *,
            token_path: Path = token_file,
            expected_error: str | None = None,
        ) -> dict[str, object]:
            parameters = StdioServerParameters(
                command=sys.executable,
                args=["-m", "ksi_analysis_mcp.server"],
                env={
                    "KSI_ANALYSIS_MCP_CORE_ORIGIN": core_origin,
                    "KSI_ANALYSIS_MCP_TOKEN_FILE": str(token_path),
                },
            )
            async with (
                stdio_client(parameters) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(name, arguments)
                assert result.is_error is (expected_error is not None)
                assert isinstance(result.structured_content, dict)
                if expected_error is not None:
                    assert result.structured_content == {"code": expected_error}
                return result.structured_content

        created = asyncio.run(mcp_call("ksi_create_analysis", create_arguments))
        analysis_id = created["analysisId"]
        assert isinstance(analysis_id, str)

        runtime_facts = fixture.app.state.external_analysis_wiring.facade._assessments._runtime
        envelope = fixture.app.state.external_analysis_wiring.calculations._resource_envelope
        worker = ExternalAnalysisCoreClient(
            base_url=core_origin,
            worker_token=fixture.worker_headers()["Authorization"].removeprefix("Bearer "),
            worker_instance_id="mcp-real-worker",
        )
        assert run_once(
            worker,
            ProcessingWorkerRuntimeIdentityV1(
                worker_executable_digest=runtime_facts.worker_executable_digest,
                worker_build_digest=runtime_facts.worker_build_digest,
                runtime_image_version=runtime_facts.runtime_image_version,
                runtime_image_oci_digest=runtime_facts.runtime_image_oci_digest,
                dependency_lock_digest=runtime_facts.dependency_lock_digest,
            ),
            ExternalObjectTransportPolicyV1(
                endpoints=(
                    TrustedObjectEndpointV1(origin=object_origin, addresses=("127.0.0.1",)),
                ),
                max_header_bytes=16_384,
                max_object_bytes=envelope.max_input_bytes,
                max_chunk_bytes=min(65_536, envelope.max_input_bytes),
            ),
        )

        via_mcp_result = asyncio.run(
            mcp_call(
                "ksi_get_analysis_result", {"siteId": fixture.site_id, "analysisId": analysis_id}
            )
        )
        via_mcp_evidence = asyncio.run(
            mcp_call(
                "ksi_get_analysis_evidence", {"siteId": fixture.site_id, "analysisId": analysis_id}
            )
        )
        with httpx.Client(base_url=core_origin, trust_env=False) as direct:
            direct_detail = direct.get(
                f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}",
                headers=fixture.operator_headers(),
            )
            direct_evidence = direct.get(
                f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
                params={"limit": 32},
                headers=fixture.operator_headers(),
            )
        assert direct_detail.status_code == 200
        assert direct_evidence.status_code == 200
        assert via_mcp_result == direct_detail.json()
        assert via_mcp_evidence == direct_evidence.json()

        viewer_result_mcp = asyncio.run(
            mcp_call(
                "ksi_get_analysis_result",
                {"siteId": fixture.site_id, "analysisId": analysis_id},
                token_path=viewer_token_file,
                expected_error="CORE_EGRESS_ACKNOWLEDGMENT_MISSING",
            )
        )
        viewer_evidence_mcp = asyncio.run(
            mcp_call(
                "ksi_get_analysis_evidence",
                {"siteId": fixture.site_id, "analysisId": analysis_id},
                token_path=viewer_token_file,
                expected_error="CORE_EGRESS_ACKNOWLEDGMENT_MISSING",
            )
        )
        viewer_headers = fixture.viewer_headers()
        with httpx.Client(base_url=core_origin, trust_env=False) as direct:
            viewer_result_http = direct.get(
                f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}",
                headers=viewer_headers,
            )
            viewer_evidence_http = direct.get(
                f"/v2/sites/{fixture.site_id}/analyses/{analysis_id}/evidence",
                params={"limit": 32},
                headers=viewer_headers,
            )
        assert viewer_result_http.status_code == 200
        assert viewer_evidence_http.status_code == 200
        assert "X-KSI-External-AI-Egress" not in viewer_result_http.headers
        assert "X-KSI-External-AI-Egress" not in viewer_evidence_http.headers
        assert viewer_result_mcp == {"code": "CORE_EGRESS_ACKNOWLEDGMENT_MISSING"}
        assert viewer_evidence_mcp == {"code": "CORE_EGRESS_ACKNOWLEDGMENT_MISSING"}

        intent_count_before_viewer_write = len(
            fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                organization_id="org-a"
            )
        )
        denied_create = asyncio.run(
            mcp_call(
                "ksi_create_analysis",
                {**create_arguments, "idempotencyKey": "viewer-cannot-create-analysis"},
                token_path=viewer_token_file,
                expected_error="CORE_EGRESS_ACKNOWLEDGMENT_MISSING",
            )
        )
        assert denied_create == {"code": "CORE_EGRESS_ACKNOWLEDGMENT_MISSING"}
        assert (
            len(
                fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                    organization_id="org-a"
                )
            )
            == intent_count_before_viewer_write
        )

        from ksi_event_contracts.site_frame import SiteFrame

        foreign_site = fixture.app.state.site_store.register(
            "site-org-b",
            "Foreign organization Analysis fixture site",
            SiteFrame(
                crs="EPSG:5186",
                vertical_datum="EGM96 height",
                unit="meter",
                transform_version="fixture-v1",
            ),
            organization_id="org-b",
            ai_egress_allowed=True,
            actor="org-b-fixture-admin",
            now=datetime.now(UTC),
        )
        assert foreign_site.record is not None
        foreign_read = asyncio.run(
            mcp_call(
                "ksi_list_analyses",
                {"siteId": "site-org-b"},
                token_path=viewer_token_file,
                expected_error="ANALYSIS_RESOURCE_NOT_FOUND",
            )
        )
        assert foreign_read == {"code": "ANALYSIS_RESOURCE_NOT_FOUND"}
        with httpx.Client(base_url=core_origin, trust_env=False) as direct:
            foreign_result_http = direct.get(
                "/v2/sites/site-org-b/analyses",
                headers=viewer_headers,
            )
        assert foreign_result_http.status_code == 404
        assert foreign_result_http.json() == {"detail": "ANALYSIS_RESOURCE_NOT_FOUND"}

        retried = asyncio.run(mcp_call("ksi_create_analysis", create_arguments))
        assert retried["analysisId"] == analysis_id
        assert retried == direct_detail.json()
        assert (
            len(
                fixture.app.state.external_analysis_wiring.intents.list_for_organization(
                    organization_id="org-a"
                )
            )
            == 1
        )
    finally:
        if worker is not None:
            worker.close()
        if core_server is not None:
            core_server.should_exit = True
        if core_thread is not None:
            core_thread.join(timeout=5)
        if core_socket is not None:
            core_socket.close()
        if object_server is not None:
            object_server.shutdown()
            object_server.server_close()
        if object_thread is not None:
            object_thread.join(timeout=2)
        fixture.close()
