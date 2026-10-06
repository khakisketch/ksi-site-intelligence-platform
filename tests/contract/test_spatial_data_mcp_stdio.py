"""Stdio contract tests for the spatial-data MCP adapter (RED first)."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import spatial_data_mcp_fixture as fixture
from spatial_data_mcp_fixture import LoopbackCore, json_response

fixture.ensure_source_path()

SITE = "site-a"
AREA = "area-a"
ASSET = "ksa-v1-" + "a" * 64
JOB = "sdj-v1-12345678-1234-1234-1234-1234567890ab"

EXPECTED_TOOLS = {
    "ksi_list_spatial_data_assets",
    "ksi_get_spatial_data_asset",
    "ksi_create_spatial_data_request",
    "ksi_list_spatial_data_requests",
    "ksi_get_spatial_data_request",
    "ksi_cancel_spatial_data_request",
}
READ_TOOLS = EXPECTED_TOOLS - {
    "ksi_create_spatial_data_request",
    "ksi_cancel_spatial_data_request",
}


def _job_view() -> dict[str, Any]:
    return {
        "jobId": JOB,
        "assetRef": ASSET,
        "siteId": SITE,
        "workAreaId": AREA,
        "createdAt": "2026-10-06T00:00:00Z",
        "executionState": "QUEUED",
        "availability": "NOT_READY",
    }


def _server_env(config: Path) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"}
    }
    env["PYTHONPATH"] = os.fspath(fixture.PACKAGE_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _start_parameters(config: Path) -> Any:
    from mcp.client.stdio import StdioServerParameters

    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "ksi_spatial_data_mcp.server", f"--config={config}"],
        env=_server_env(config),
    )


def _responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
    clean = path.split("?", 1)[0]
    has_query = "?" in path
    if "/sites/gone/" in clean:
        return json_response({"reason": "NOT_FOUND"}, status=404, ack=False)
    if clean.endswith("/cancel"):
        assert method == "POST"
        return json_response(_job_view())
    if "/spatial-data-requests/" in clean and method == "GET" and not has_query:
        return json_response(_job_view())
    if clean.endswith("/spatial-data-requests"):
        if method == "POST":
            return json_response(_job_view(), status=201)
        return json_response({"items": [_job_view()]})
    if "/spatial-data-assets/" in clean:
        from test_spatial_data_mcp_client import _asset_view

        return json_response(_asset_view())
    if clean.endswith("/spatial-data-assets"):
        return json_response({"items": []})
    return json_response({"reason": "NOT_FOUND"}, status=404, ack=False)


def test_stdio_lists_exact_tools_and_serves_calls() -> None:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    core = LoopbackCore(_responder).start()
    try:
        token = fixture.write_token("stdio-basic-token")
        config = fixture.write_adapter_config(
            f"stdio-basic-{time.time_ns()}.json",
            origin=core.origin,
            token_path=token,
        )

        async def exercise() -> None:
            async with (
                stdio_client(_start_parameters(config)) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                assert {tool.name for tool in tools.tools} == EXPECTED_TOOLS
                for tool in tools.tools:
                    assert tool.input_schema is not None
                    assert tool.output_schema is not None
                    assert tool.annotations is not None
                    assert tool.annotations.open_world_hint is False
                    assert tool.annotations.read_only_hint is (tool.name in READ_TOOLS)
                result = await session.call_tool(
                    "ksi_list_spatial_data_assets",
                    {"siteId": SITE, "workAreaId": AREA},
                )
                assert result.is_error is False
                assert result.structured_content is not None
                assert result.structured_content["items"] == []
                assert result.structured_content.get("nextCursor") is None
                created = await session.call_tool(
                    "ksi_create_spatial_data_request",
                    {
                        "siteId": SITE,
                        "workAreaId": AREA,
                        "assetRef": ASSET,
                        "requestedBounds": [0.0, 0.0, 4.0, 4.0],
                        "observedCrsDigest": "sha256:" + "b" * 64,
                        "idempotencyKey": "stdio-key-a",
                    },
                )
                assert created.is_error is False
                assert created.structured_content is not None
                assert created.structured_content["jobId"] == JOB
                denied = await session.call_tool(
                    "ksi_get_spatial_data_asset",
                    {"siteId": "gone", "workAreaId": AREA, "assetRef": ASSET},
                )
                assert denied.is_error is True
                assert denied.structured_content is not None
                assert denied.structured_content["code"] == "NOT_FOUND"
                assert "remediation" in denied.structured_content
                unknown = await session.call_tool("ksi_no_such_tool", {})
                assert unknown.is_error is True
                assert unknown.structured_content is not None
                assert unknown.structured_content["code"] == "UNKNOWN_TOOL"

        asyncio.run(exercise())
    finally:
        core.close()


def test_stdio_advertised_schemas_match_strict_payloads() -> None:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    core = LoopbackCore(_responder).start()
    try:
        token = fixture.write_token("stdio-schema-token")
        config = fixture.write_adapter_config(
            f"stdio-schema-{time.time_ns()}.json",
            origin=core.origin,
            token_path=token,
        )

        async def exercise() -> None:
            async with (
                stdio_client(_start_parameters(config)) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                advertised = {tool.name: tool for tool in tools.tools}
                assert set(advertised) == EXPECTED_TOOLS
                total = len(json.dumps([t.model_dump(mode="json") for t in tools.tools]))
                # Control-frame analysis: advertised schemas must fit the same
                # owner structured-response budget as tool results.
                assert total < 131072
                scope_props = {"siteId", "workAreaId"}
                list_props = set(
                    advertised["ksi_list_spatial_data_assets"].input_schema["properties"]
                )
                assert list_props == (scope_props | {"limit", "cursor"})
                detail_props = set(
                    advertised["ksi_get_spatial_data_asset"].input_schema["properties"]
                )
                assert detail_props == (scope_props | {"assetRef"})
                create_props = set(
                    advertised["ksi_create_spatial_data_request"].input_schema["properties"]
                )
                assert create_props == (
                    scope_props
                    | {"assetRef", "requestedBounds", "observedCrsDigest", "idempotencyKey"}
                )
                assert "purpose" not in create_props
                assert "resolutionMode" not in create_props
                for tool in tools.tools:
                    assert tool.input_schema.get("additionalProperties") is False
                    output = tool.output_schema
                    assert output is not None and "anyOf" in output
                bad = await session.call_tool(
                    "ksi_create_spatial_data_request",
                    {
                        "siteId": SITE,
                        "workAreaId": AREA,
                        "assetRef": ASSET,
                        "requestedBounds": [0.0, 0.0, 4.0, 4.0],
                        "observedCrsDigest": "sha256:" + "b" * 64,
                    },
                )
                assert bad.is_error is True
                assert bad.structured_content is not None
                assert bad.structured_content["code"] == "INVALID_TOOL_ARGUMENTS"

        asyncio.run(exercise())
    finally:
        core.close()


def test_stdio_large_success_becomes_safe_error_and_no_secrets_leak() -> None:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    secret = "STDIO_LOOPBACK_SECRET"

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        if path.split("?", 1)[0].endswith("/spatial-data-assets"):
            from test_spatial_data_mcp_client import _asset_view

            items = [_asset_view() for _ in range(6)]
            return json_response({"items": items})
        return json_response({"detail": secret}, status=500, ack=False)

    core = LoopbackCore(responder).start()
    try:
        token = fixture.write_token("stdio-large-token")
        config = fixture.write_adapter_config(
            f"stdio-large-{time.time_ns()}.json",
            origin=core.origin,
            token_path=token,
            overrides={"maxStructuredResponseBytes": 2048},
        )

        async def exercise() -> dict[str, Any]:
            async with (
                stdio_client(_start_parameters(config)) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(
                    "ksi_list_spatial_data_assets",
                    {"siteId": SITE, "workAreaId": AREA},
                )
                assert result.is_error is True
                assert result.structured_content is not None
                assert result.structured_content["code"] == "CORE_RESPONSE_TOO_LARGE"
                rendered = json.dumps(result.model_dump(mode="json"))
                assert secret not in rendered
                assert "Traceback" not in rendered
                return result.structured_content

        structured = asyncio.run(exercise())
        assert structured["code"] == "CORE_RESPONSE_TOO_LARGE"
    finally:
        core.close()


def test_stdio_revoked_token_is_safe_typed_error() -> None:
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client

    core = LoopbackCore(_responder).start()
    try:
        token = fixture.write_token("stdio-revoke-token", "revocable-secret-value")
        config = fixture.write_adapter_config(
            f"stdio-revoke-{time.time_ns()}.json",
            origin=core.origin,
            token_path=token,
        )

        async def exercise() -> None:
            async with (
                stdio_client(_start_parameters(config)) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                token.unlink()
                result = await session.call_tool(
                    "ksi_list_spatial_data_assets",
                    {"siteId": SITE, "workAreaId": AREA},
                )
                assert result.is_error is True
                assert result.structured_content is not None
                assert result.structured_content["code"] == "CONFIGURATION_UNAVAILABLE"
                rendered = json.dumps(result.model_dump(mode="json"))
                assert "revocable-secret-value" not in rendered
                assert str(token) not in rendered
                assert "Traceback" not in rendered

        asyncio.run(exercise())
    finally:
        core.close()


def test_server_main_rejects_bad_startup_without_secrets_or_traceback() -> None:
    argv = [
        sys.executable,
        "-m",
        "ksi_spatial_data_mcp.server",
        "--config=/nonexistent/protected.json",
    ]
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KSI_SPATIAL_DATA_MCP")
    }
    env["PYTHONPATH"] = os.fspath(fixture.PACKAGE_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    completed = subprocess.run(argv, capture_output=True, text=True, timeout=60, env=env)
    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "Traceback" not in completed.stderr
    assert "/nonexistent/protected.json" not in completed.stderr
    assert "CONFIGURATION_UNAVAILABLE" in completed.stderr


def _raw_session(
    config: Path,
    sends: list[bytes],
    *,
    expect_lines: int,
    timeout: float = 30.0,
) -> tuple[list[bytes], int | None, str]:
    """Speak raw JSON-RPC to the real stdio server and capture actual frames."""
    import select

    argv = [sys.executable, "-m", "ksi_spatial_data_mcp.server", f"--config={config}"]
    proc = subprocess.Popen(
        argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_server_env(config),
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    try:
        for payload in sends:
            proc.stdin.write(payload + b"\n")
        proc.stdin.flush()
        lines: list[bytes] = []
        deadline = time.monotonic() + timeout
        while len(lines) < expect_lines and time.monotonic() < deadline:
            ready, _, _ = select.select(
                [proc.stdout], [], [], max(0.0, deadline - time.monotonic())
            )
            if not ready:
                break
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        _, stderr = proc.communicate()
    return lines, proc.returncode, stderr.decode("utf-8", "replace")


def _raw_request(method: str, params: dict[str, Any], request_id: Any) -> bytes:
    return json.dumps(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    ).encode("utf-8")


def _raw_notification(method: str, params: dict[str, Any]) -> bytes:
    return json.dumps({"jsonrpc": "2.0", "method": method, "params": params}).encode("utf-8")


def _initialize_script() -> list[bytes]:
    return [
        _raw_request(
            "initialize",
            {
                "protocolVersion": "2026-07-28",
                "capabilities": {},
                "clientInfo": {"name": "raw-probe", "version": "1"},
            },
            1,
        ),
        _raw_notification("notifications/initialized", {}),
    ]


def _loopback_origin() -> LoopbackCore:
    return LoopbackCore(
        lambda method, path, headers, body: json_response({"items": []}),
    ).start()


def test_raw_stdout_gap_backslash_payload_refused() -> None:
    """An estimate-passing backslash payload must never emit an oversized frame."""
    from test_spatial_data_mcp_client import _asset_view

    budget = 131072
    items: list[dict[str, Any]] = []
    while len(items) < 40:
        candidate = _asset_view(attribution="\\" * 1400 + "é" * 200)
        probe = json.dumps({"items": [*items, candidate]}, separators=(",", ":")).encode("utf-8")
        if len(probe) > 66000:
            break
        items.append(candidate)
        current = json.dumps({"items": items}, separators=(",", ":")).encode("utf-8")
        if len(current) >= 60000:
            break
    structured = json.dumps({"items": items}, separators=(",", ":")).encode("utf-8")
    assert 60000 <= len(structured) <= 66000
    # The old estimate (2*len + 1024 + name) passes this payload; only actual
    # escaped duplication plus the RPC envelope crosses the owner budget.
    assert 2 * len(structured) + 1100 <= budget

    core = LoopbackCore(
        lambda method, path, headers, body: json_response({"items": items}),
    ).start()
    try:
        token = fixture.write_token("stdio-gap-token")
        config = fixture.write_adapter_config(
            f"stdio-gap-{time.time_ns()}.json",
            origin=core.origin,
            token_path=token,
        )
        sends = _initialize_script()
        sends.append(
            _raw_request(
                "tools/call",
                {
                    "name": "ksi_list_spatial_data_assets",
                    "arguments": {"siteId": SITE, "workAreaId": AREA, "limit": 200},
                },
                2,
            )
        )
        lines, _, stderr = _raw_session(config, sends, expect_lines=2)
        assert len(lines) == 2
        for line in lines:
            assert len(line) <= budget
        refused = json.loads(lines[1].decode("utf-8"))
        assert refused["id"] == 2
        assert refused["result"]["isError"] is True
        assert refused["result"]["structuredContent"]["code"] == "CORE_RESPONSE_TOO_LARGE"
        assert "Traceback" not in stderr
    finally:
        core.close()


def test_raw_stdout_long_request_id_bounded() -> None:
    """A very long request id is echoed, so it must stay inside the budget."""
    import select as _select

    budget = 131072
    core = _loopback_origin()
    try:
        token = fixture.write_token("stdio-long-id-token")
        config = fixture.write_adapter_config(
            f"stdio-long-id-{time.time_ns()}.json",
            origin=core.origin,
            token_path=token,
        )
        argv = [sys.executable, "-m", "ksi_spatial_data_mcp.server", f"--config={config}"]
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_server_env(config),
        )
        assert proc.stdin is not None and proc.stdout is not None
        try:
            for payload in _initialize_script():
                proc.stdin.write(payload + b"\n")
            proc.stdin.write(
                _raw_request(
                    "tools/call",
                    {
                        "name": "ksi_list_spatial_data_assets",
                        "arguments": {"siteId": SITE, "workAreaId": AREA},
                    },
                    "id-" + "9" * 5000,
                )
                + b"\n"
            )
            proc.stdin.flush()
            lines: list[bytes] = []
            deadline = time.monotonic() + 15.0
            while len(lines) < 2 and time.monotonic() < deadline:
                ready, _, _ = _select.select(
                    [proc.stdout], [], [], max(0.0, deadline - time.monotonic())
                )
                if not ready:
                    break
                line = proc.stdout.readline()
                if not line:
                    break
                lines.append(line)
            assert len(lines) == 2
            for line in lines:
                assert len(line) <= budget
            healthy = json.loads(lines[1].decode("utf-8"))
            assert healthy["id"] == "id-" + "9" * 5000
            assert healthy["result"]["isError"] is False
            assert len(lines[1]) > 5000
            # The killer id cannot fit any frame: the session closes itself.
            try:
                proc.stdin.write(
                    _raw_request(
                        "tools/call",
                        {
                            "name": "ksi_list_spatial_data_assets",
                            "arguments": {"siteId": SITE, "workAreaId": AREA},
                        },
                        "id-" + "9" * 200000,
                    )
                    + b"\n"
                )
                proc.stdin.flush()
            except BrokenPipeError:
                pass
            try:
                returncode = proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                raise AssertionError("server did not close on oversized id") from None
            assert returncode != 0
            tail: list[bytes] = []
            while True:
                ready, _, _ = _select.select([proc.stdout], [], [], 1.0)
                if not ready:
                    break
                line = proc.stdout.readline()
                if not line:
                    break
                tail.append(line)
            for line in lines + tail:
                assert len(line) <= budget
            _, stderr = proc.communicate()
            failed = stderr.decode("utf-8", "replace")
            assert "Traceback" not in failed
            assert "CORE_RESPONSE_TOO_LARGE" in failed
        finally:
            if proc.poll() is None:
                proc.kill()
    finally:
        core.close()


def test_raw_stdout_small_budget_list_tools_closes_safely() -> None:
    """Control responses obey the same owner budget as tool results."""
    budget = 2048
    core = _loopback_origin()
    try:
        token = fixture.write_token("stdio-small-list-token")
        config = fixture.write_adapter_config(
            f"stdio-small-list-{time.time_ns()}.json",
            origin=core.origin,
            token_path=token,
            overrides={"maxStructuredResponseBytes": budget},
        )
        sends = _initialize_script()
        sends.append(_raw_request("tools/list", {}, 2))
        lines, returncode, stderr = _raw_session(config, sends, expect_lines=2)
        assert len(lines) == 1
        assert len(lines[0]) <= budget
        assert returncode is not None and returncode != 0
        assert "Traceback" not in stderr
        assert "CORE_RESPONSE_TOO_LARGE" in stderr
    finally:
        core.close()


def test_raw_stdout_tiny_budget_closes_at_handshake() -> None:
    """A budget that cannot fit any frame closes before partial JSON."""
    budget = 64
    core = _loopback_origin()
    try:
        token = fixture.write_token("stdio-tiny-token")
        config = fixture.write_adapter_config(
            f"stdio-tiny-{time.time_ns()}.json",
            origin=core.origin,
            token_path=token,
            overrides={"maxStructuredResponseBytes": budget},
        )
        sends = _initialize_script()
        lines, returncode, stderr = _raw_session(config, sends, expect_lines=1)
        for line in lines:
            assert len(line) <= budget
        assert returncode is not None and returncode != 0
        assert "Traceback" not in stderr
        assert "CORE_RESPONSE_TOO_LARGE" in stderr
    finally:
        core.close()


def test_raw_stdout_malformed_protocol_frame_bounded() -> None:
    """A malformed inbound frame yields a bounded error and a live session."""
    budget = 131072
    core = _loopback_origin()
    try:
        token = fixture.write_token("stdio-malformed-token")
        config = fixture.write_adapter_config(
            f"stdio-malformed-{time.time_ns()}.json",
            origin=core.origin,
            token_path=token,
        )
        sends = [b"this is not json-rpc"]
        sends.extend(_initialize_script())
        sends.append(_raw_request("tools/list", {}, 2))
        # The malformed frame yields no response line; the session stays live.
        lines, _, stderr = _raw_session(config, sends, expect_lines=2)
        assert len(lines) == 2
        for line in lines:
            assert len(line) <= budget
        listed = json.loads(lines[1].decode("utf-8"))
        assert {tool["name"] for tool in listed["result"]["tools"]} == EXPECTED_TOOLS
        assert "Traceback" not in stderr
    finally:
        core.close()


def _pipe_writer(limit_bytes: int) -> tuple[Any, int, int]:
    import os as _os

    from ksi_spatial_data_mcp.server import _BoundedBinaryWriter

    reader, writer = _os.pipe()
    return _BoundedBinaryWriter(writer, limit_bytes), reader, writer


def _drainoneshot(reader: int, expected: int, timeout: float = 5.0) -> bytes:
    import os as _os
    import select as _select

    received = bytearray()
    deadline = time.monotonic() + timeout
    while len(received) < expected and time.monotonic() < deadline:
        ready, _, _ = _select.select([reader], [], [], max(0.0, deadline - time.monotonic()))
        if not ready:
            break
        chunk = _os.read(reader, 65536)
        if not chunk:
            break
        received.extend(chunk)
    return bytes(received)


def _close_quietly(descriptor: int) -> None:
    import contextlib
    import os as _os

    with contextlib.suppress(OSError):
        _os.close(descriptor)


def test_writer_loops_short_writes_to_full_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """A partial pipe write must loop until the whole frame is out."""
    import os as _os

    writer, reader, handle = _pipe_writer(131072)
    try:
        real_write = _os.write

        def short_write(descriptor: int, data: bytes) -> int:
            return real_write(descriptor, bytes(data)[:7])

        monkeypatch.setattr(_os, "write", short_write)
        line = b'{"jsonrpc":"2.0","id":1,"result":{}}\n'
        writer.write(line)
        assert _drainoneshot(reader, len(line)) == line
    finally:
        _close_quietly(reader)
        _close_quietly(handle)


def test_writer_retries_interrupted_write(monkeypatch: pytest.MonkeyPatch) -> None:
    """EINTR must retry, never drop the frame or leak the signal error."""
    import os as _os

    writer, reader, handle = _pipe_writer(131072)
    try:
        real_write = _os.write
        calls = 0

        def eintr_write(descriptor: int, data: bytes) -> int:
            nonlocal calls
            calls += 1
            if calls <= 2:
                raise InterruptedError()
            return real_write(descriptor, data)

        monkeypatch.setattr(_os, "write", eintr_write)
        line = b'{"jsonrpc":"2.0","id":2,"result":{}}\n'
        writer.write(line)
        assert _drainoneshot(reader, len(line)) == line
        assert calls == 3
    finally:
        _close_quietly(reader)
        _close_quietly(handle)


def test_writer_refuses_midline_accumulation() -> None:
    """An over-budget line is refused while accumulating, before growth."""
    from ksi_spatial_data_mcp.server import FrameBudgetExceeded

    writer, reader, handle = _pipe_writer(100)
    try:
        with pytest.raises(FrameBudgetExceeded):
            writer.write(b"x" * 200)
    finally:
        _close_quietly(reader)
        _close_quietly(handle)


def test_writer_close_discards_unterminated_tail() -> None:
    """Close must never emit an unterminated partial frame."""
    import os as _os

    writer, reader, handle = _pipe_writer(131072)
    try:
        writer.write(b'{"partial":true')
        writer.close()
        _os.set_blocking(reader, False)
        try:
            assert _os.read(reader, 65536) == b""
        finally:
            _os.set_blocking(reader, True)
    finally:
        _close_quietly(reader)
        _close_quietly(handle)


def test_writer_stalled_transport_closes_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport that never becomes writable closes instead of hanging."""
    import select as _select

    from ksi_spatial_data_mcp.server import FrameBudgetExceeded

    writer, reader, handle = _pipe_writer(131072)
    try:

        def stalled_write(descriptor: int, data: bytes) -> int:
            raise BlockingIOError()

        def never_ready(
            reads: list[int], writes: list[int], errors: list[int], timeout: float = 0
        ) -> tuple[list[int], list[int], list[int]]:
            return ([], [], [])

        import os as _os

        monkeypatch.setattr(_os, "write", stalled_write)
        monkeypatch.setattr(_select, "select", never_ready)
        with pytest.raises(FrameBudgetExceeded):
            writer.write(b'{"jsonrpc":"2.0","id":3,"result":{}}\n')
    finally:
        _close_quietly(reader)
        _close_quietly(handle)


def test_writer_never_grows_pending_over_limit() -> None:
    """Pending must stay within budget even at refusal: 1B + 1024B vs 32B."""
    from ksi_spatial_data_mcp.server import FrameBudgetExceeded

    writer, reader, handle = _pipe_writer(32)
    try:
        writer.write(b"x")
        assert len(writer._pending) == 1
        with pytest.raises(FrameBudgetExceeded):
            writer.write(b"y" * 1024)
        assert len(writer._pending) <= 32
    finally:
        _close_quietly(reader)
        _close_quietly(handle)


def test_writer_trickle_stall_hits_total_frame_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A writable-flapping trickle must hit the total frame deadline."""
    import os as _os
    import time as _time

    from ksi_spatial_data_mcp.server import FrameBudgetExceeded

    writer, reader, handle = _pipe_writer(131072)
    try:
        real_write = _os.write
        now = [1000.0]
        calls = 0

        def trickle_write(descriptor: int, data: bytes) -> int:
            nonlocal calls
            calls += 1
            now[0] += 0.02
            return real_write(descriptor, bytes(data)[:1])

        monkeypatch.setattr(_os, "write", trickle_write)
        monkeypatch.setattr(_time, "monotonic", lambda: now[0])
        with pytest.raises(FrameBudgetExceeded):
            writer.write(b'{"jsonrpc":"2.0","id":4,"result":"' + b"z" * 400 + b'"}\n')
        assert calls >= 2
    finally:
        _close_quietly(reader)
        _close_quietly(handle)


def test_writer_preserves_legal_multiframe_chunk() -> None:
    """One write carrying several legal frames emits every frame in order."""
    writer, reader, handle = _pipe_writer(100)
    try:
        writer.write(b'{"a":1}\n{"b":2}\n{"c":3}\n')
        assert _drainoneshot(reader, len(b'{"a":1}\n{"b":2}\n{"c":3}\n')) == (
            b'{"a":1}\n{"b":2}\n{"c":3}\n'
        )
    finally:
        _close_quietly(reader)
        _close_quietly(handle)


def test_writer_slow_trickle_completes_within_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Steady slow progress below the deadline still delivers the frame."""
    import os as _os

    writer, reader, handle = _pipe_writer(131072)
    try:
        real_write = _os.write

        def slow_write(descriptor: int, data: bytes) -> int:
            return real_write(descriptor, bytes(data)[:1])

        monkeypatch.setattr(_os, "write", slow_write)
        line = b'{"jsonrpc":"2.0","id":5,"result":{}}\n'
        writer.write(line)
        assert _drainoneshot(reader, len(line)) == line
    finally:
        _close_quietly(reader)
        _close_quietly(handle)


def test_writer_unread_pipe_closes_safely() -> None:
    """A full pipe with no reader closes instead of dropping bytes silently."""
    import os as _os

    from ksi_spatial_data_mcp.server import FrameBudgetExceeded, _BoundedBinaryWriter

    read_end, write_end = _os.pipe()
    os.set_blocking(write_end, False)
    try:
        writer = _BoundedBinaryWriter(write_end, 200000)
        started = time.monotonic()
        with pytest.raises(FrameBudgetExceeded):
            writer.write(b'{"jsonrpc":"2.0","id":6,"result":"' + b"q" * 100000 + b'"}\n')
        assert time.monotonic() - started < 10.0
    finally:
        _close_quietly(read_end)
        _close_quietly(write_end)


def test_raw_stdin_oversize_line_closes_safely() -> None:
    """An inbound line over the representation budget closes without reflection."""
    budget = 131072
    marker = "INBOUND-MARKER-7f3a9c"
    core = _loopback_origin()
    try:
        token = fixture.write_token("stdio-inbound-token")
        config = fixture.write_adapter_config(
            f"stdio-inbound-{time.time_ns()}.json",
            origin=core.origin,
            token_path=token,
        )
        giant = b"NOTJSON-" + marker.encode("ascii") + b"-" + b"y" * 200000
        assert len(giant) + 1 > budget
        argv = [sys.executable, "-m", "ksi_spatial_data_mcp.server", f"--config={config}"]
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_server_env(config),
        )
        assert proc.stdin is not None and proc.stdout is not None
        try:
            import select as _select

            try:
                proc.stdin.write(giant + b"\n")
                for payload in _initialize_script():
                    proc.stdin.write(payload + b"\n")
                proc.stdin.flush()
            except BrokenPipeError:
                # The server already closed itself mid-write: the expected path.
                pass
            # The oversize line must refuse before any response is emitted;
            # stdin stays open to prove the server closes itself. (A ready
            # stdout with immediate EOF is the closed session, not a frame.)
            ready, _, _ = _select.select([proc.stdout], [], [], 5.0)
            if ready:
                assert proc.stdout.readline() == b"", (
                    "oversize inbound line produced a stdout frame"
                )
            try:
                returncode = proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                raise AssertionError("server did not close itself on oversize input") from None
            assert returncode != 0
            _, stderr = proc.communicate()
            failed = stderr.decode("utf-8", "replace")
            assert marker not in failed
            assert "Traceback" not in failed
            assert "CORE_RESPONSE_TOO_LARGE" in failed
        finally:
            if proc.poll() is None:
                proc.kill()
    finally:
        core.close()


def test_raw_stdin_deep_line_stays_bounded() -> None:
    """A deeply nested inbound frame stays bounded with no traceback."""
    budget = 131072
    core = _loopback_origin()
    try:
        token = fixture.write_token("stdio-deep-inbound-token")
        config = fixture.write_adapter_config(
            f"stdio-deep-inbound-{time.time_ns()}.json",
            origin=core.origin,
            token_path=token,
        )
        nested = ("[" * 3000 + "]" * 3000).encode("ascii")
        deep_call = (
            b'{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":'
            b'"ksi_list_spatial_data_assets","arguments":{"siteId":"'
            + SITE.encode("ascii")
            + b'","workAreaId":"'
            + AREA.encode("ascii")
            + b'","cursor":'
            + nested
            + b"}}}"
        )
        assert len(deep_call) + 1 <= budget
        sends = _initialize_script()
        sends.append(deep_call)
        sends.append(_raw_request("tools/list", {}, 8))
        lines, returncode, stderr = _raw_session(config, sends, expect_lines=3)
        for line in lines:
            assert len(line) <= budget
        assert "Traceback" not in stderr
        assert b"[" * 100 not in b"".join(lines)
        if returncode == 0 or returncode is None:
            listed = json.loads(lines[-1].decode("utf-8"))
            assert {tool["name"] for tool in listed["result"]["tools"]} == EXPECTED_TOOLS
    finally:
        core.close()


def test_raw_deadline_timeout_is_safe_error() -> None:
    """A stalled Core call fails as a bounded safe error, not a hang."""

    def responder(method: str, path: str, headers: dict[str, str], body: bytes) -> Any:
        time.sleep(10)
        return json_response({"items": []})

    core = LoopbackCore(responder).start()
    try:
        token = fixture.write_token("stdio-deadline-token")
        config = fixture.write_adapter_config(
            f"stdio-deadline-{time.time_ns()}.json",
            origin=core.origin,
            token_path=token,
            overrides={"callDeadlineSeconds": 1.0, "readTimeoutSeconds": 5.0},
        )
        sends = _initialize_script()
        sends.append(
            _raw_request(
                "tools/call",
                {
                    "name": "ksi_list_spatial_data_assets",
                    "arguments": {"siteId": SITE, "workAreaId": AREA},
                },
                9,
            )
        )
        lines, _, stderr = _raw_session(config, sends, expect_lines=2, timeout=20.0)
        assert len(lines) == 2
        for line in lines:
            assert len(line) <= 131072
        timed_out = json.loads(lines[1].decode("utf-8"))
        assert timed_out["result"]["isError"] is True
        assert timed_out["result"]["structuredContent"]["code"] == "CORE_TIMEOUT"
        assert "Traceback" not in stderr
    finally:
        core.close()
