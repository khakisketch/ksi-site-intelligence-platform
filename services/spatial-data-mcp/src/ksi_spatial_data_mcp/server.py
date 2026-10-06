"""Official MCP v2 low-level stdio server for the fixed spatial-data tool set."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import select
import sys
import threading
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, NoReturn

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .config import AdapterConfig, AdapterConfigurationError
from .core_client import CoreAdapterError, CoreSpatialDataClient, remediation_for
from .tool_models import TOOL_ARGUMENT_MODELS, TOOL_ERROR_MODEL, TOOL_RESULT_MODELS

# Conservative envelope allowance for the in-callback pre-check: request id,
# method framing, resultType/_meta/serverInfo stamps the framework adds. The
# normative boundary is the writer below, which measures actual bytes; this
# only decides safe-error-first versus emit-and-verify.
_PROTOCOL_OVERHEAD_BYTES = 8192

# Safe code emitted when an actually serialized frame cannot fit the owner
# structured-response budget.
_FRAME_BUDGET_CODE = "CORE_RESPONSE_TOO_LARGE"


class FrameBudgetExceeded(RuntimeError):
    """One stdout frame exceeded the owner budget; the session must close."""

    def __init__(self) -> None:
        super().__init__(_FRAME_BUDGET_CODE)
        self.code = _FRAME_BUDGET_CODE


def _full_write(fd: int, data: bytes | bytearray) -> None:
    """Loop a blocking descriptor until every byte is out.

    Retries EINTR, follows short counts, and treats a zero return as a dead
    transport instead of silently dropping the tail.
    """
    view = memoryview(bytes(data))
    while view:
        try:
            count = os.write(fd, view)
        except InterruptedError:
            continue
        if count <= 0:
            raise OSError("write returned no bytes")
        view = view[count:]


class LineOverBudget(Exception):
    """One protocol line exceeded its owner budget before completion."""


def _split_bounded(pending: bytearray, view: memoryview, limit_bytes: int) -> list[bytes]:
    """Split newline-terminated lines without ever overgrowing the buffer.

    The incoming chunk is scanned in newline-aware slices bounded by the
    remaining line budget; the pending fragment is extended only with bytes
    that keep it within budget, and only complete lines within budget are
    returned. Anything over budget raises before any further byte is
    buffered or emitted. Callers map the refusal to their session-close path.
    """
    lines: list[bytes] = []
    pos, size = 0, len(view)
    while pos < size:
        allowance = limit_bytes - len(pending)
        take = min(size - pos, allowance + 1)
        window = bytes(view[pos : pos + take])
        newline = window.find(b"\n")
        if newline < 0:
            if take < size - pos:
                raise LineOverBudget()
            tail = size - pos
            if len(pending) + tail > limit_bytes:
                raise LineOverBudget()
            pending.extend(view[pos:])
            return lines
        piece = newline + 1
        if piece > allowance:
            raise LineOverBudget()
        pending.extend(view[pos : pos + piece])
        lines.append(bytes(pending))
        pending.clear()
        pos += piece
    return lines


class _BoundedBinaryWriter(io.RawIOBase):
    """Line-buffered binary sink enforcing the owner budget on actual bytes.

    Each newline-terminated frame is measured exactly as it will hit the
    wire — JSON-RPC bytes plus the newline, including request ids and the
    re-escaped duplicated TextContent — and is either written whole or
    refused whole. An over-budget line is refused as soon as the accumulation
    alone exceeds the budget, before further growth. Refusal closes the
    session wires, emits only the safe code to stderr, and raises, so the
    session closes with no partial JSON, no truncation, and no
    framework-rendered fallback on stdout. A transport stall or mid-frame
    death closes the same way; partial bytes already on the wire can never
    be recalled and are never claimed complete.
    """

    def __init__(
        self,
        wire_fd: int,
        limit_bytes: int,
        stall_timeout: float = 1.0,
        inbound_fds: tuple[int, ...] = (),
        frame_timeout: float = 5.0,
    ) -> None:
        self._wire_fd = wire_fd
        self._limit_bytes = limit_bytes
        self._stall_timeout = stall_timeout
        self._inbound_fds = inbound_fds
        # Total per-frame deadline; defaults to the fixture call deadline
        # while production always passes the configured callDeadlineSeconds.
        self._frame_timeout = frame_timeout
        self._pending = bytearray()

    def writable(self) -> bool:
        return True

    def write(self, data: bytes | bytearray) -> int:  # type: ignore[override]
        try:
            lines = _split_bounded(self._pending, memoryview(data), self._limit_bytes)
        except LineOverBudget:
            self._refuse()
        for line in lines:
            self._write_frame(line)
        return len(data)

    def _write_frame(self, line: bytes) -> None:
        """Full-write loop with a monotonic total frame deadline.

        The deadline runs from the configured call deadline and never resets:
        EINTR retries, short writes, and writable-flapping trickles all
        consume the same budget. Per-wait selects use min(pool timeout,
        remaining). A dead transport (zero/stall/timeout) closes safely;
        partial bytes already emitted are never recalled nor claimed complete.
        """
        deadline = time.monotonic() + self._frame_timeout
        view = memoryview(line)
        while view:
            if time.monotonic() >= deadline:
                self._refuse_midframe()
            try:
                count = os.write(self._wire_fd, view)
            except InterruptedError:
                continue
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._wait_writable(remaining):
                    self._refuse_midframe()
                continue
            if count <= 0:
                self._refuse_midframe()
            view = view[count:]

    def _wait_writable(self, remaining: float) -> bool:
        _, writable, _ = select.select([], [self._wire_fd], [], min(self._stall_timeout, remaining))
        return bool(writable)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        try:
            # The pending buffer holds solely an unterminated fragment by
            # construction (complete lines flush eagerly in write): discard
            # it. An unterminated tail is never a complete frame.
            self._pending.clear()
        finally:
            with suppress(OSError):
                os.close(self._wire_fd)
            super().close()

    def _release_wires(self) -> None:
        for descriptor in self._inbound_fds:
            with suppress(OSError):
                os.close(descriptor)

    def _refuse(self) -> NoReturn:
        self._release_wires()
        with suppress(OSError):
            os.write(2, f"ksi-spatial-data-mcp: {_FRAME_BUDGET_CODE}\n".encode("ascii"))
        raise FrameBudgetExceeded()

    def _refuse_midframe(self) -> NoReturn:
        # Partial bytes may already be on the wire, so no stdout error frame
        # is possible without corrupting framing: emit only the stderr code
        # and close. The truncated line is never claimed complete.
        self._release_wires()
        with suppress(OSError):
            os.write(2, f"ksi-spatial-data-mcp: {_FRAME_BUDGET_CODE}\n".encode("ascii"))
        raise FrameBudgetExceeded()


_INBOUND_CHUNK_BYTES = 65536


def _refuse_inbound() -> NoReturn:
    """Refuse an over-budget inbound line: stderr code only, then hard close.

    The session cannot continue once an unbounded frame arrived, and the
    pump thread cannot raise into the main task, so the process exits
    without emitting anything to stdout. Unbuffered stderr write only.
    """
    with suppress(OSError):
        os.write(2, f"ksi-spatial-data-mcp: {_FRAME_BUDGET_CODE}\n".encode("ascii"))
    os._exit(1)


def _pump_inbound(stdin_fd: int, pipe_fd: int, limit_bytes: int) -> None:
    """Daemon: move stdin to the SDK pipe enforcing the per-line inbound budget.

    Reads bounded chunks (no mass allocation), splits newline-terminated
    protocol frames, and delivers only frames within the configured
    representation budget (maxRequestBytes — no new quota). The 64KB pipe
    itself bounds in-flight input as natural backpressure. EOF relays as EOF
    for a clean shutdown. This thread's only unbounded wait is the session's
    own stdin; it is a daemon and dies with the process.
    """
    pending = bytearray()
    try:
        while True:
            # Bound each read to what can still fit the current line: one
            # byte past the remaining budget is enough to prove overage.
            allowance = limit_bytes - len(pending)
            try:
                chunk = os.read(stdin_fd, min(_INBOUND_CHUNK_BYTES, allowance + 1))
            except (OSError, ValueError):
                break
            if not chunk:
                break
            try:
                lines = _split_bounded(pending, memoryview(chunk), limit_bytes)
            except LineOverBudget:
                _refuse_inbound()
            for line in lines:
                _full_write(pipe_fd, line)
    finally:
        with suppress(OSError):
            os.close(pipe_fd)


@asynccontextmanager
async def _bounded_stdio(
    client: CoreSpatialDataClient,
) -> AsyncIterator[tuple[Any, Any]]:
    """Serve stdio with every frame measured against configured budgets.

    Outgoing frames go through the bounded writer (owner
    maxStructuredResponseBytes, exact per-line bytes); incoming protocol
    frames go through a bounded pump thread (owner maxRequestBytes per line,
    chunked reads, natural pipe backpressure) before the official SDK sees
    them. fd 1 points at stderr (as the official transport does), so stray
    writes miss the wire. Fatal paths release every session wire first so
    thread-blocked SDK readers can unwind, then close with the safe code.
    """
    config = client.config
    try:
        wire_fd = os.dup(1)
        restore_fd = os.dup(1)
    except OSError as exc:
        raise CoreAdapterError("CONFIGURATION_UNAVAILABLE") from exc
    try:
        os.dup2(2, 1)
        os.set_blocking(wire_fd, False)
        inbound_reader, inbound_writer = os.pipe()
    except OSError as exc:
        for descriptor in (wire_fd, restore_fd):
            with suppress(OSError):
                os.close(descriptor)
        raise CoreAdapterError("CONFIGURATION_UNAVAILABLE") from exc
    sink = _BoundedBinaryWriter(
        wire_fd,
        config.max_structured_response_bytes,
        config.pool_timeout_seconds,
        inbound_fds=(inbound_reader, inbound_writer),
        frame_timeout=config.call_deadline_seconds,
    )
    pump = threading.Thread(
        target=_pump_inbound,
        args=(0, inbound_writer, config.max_request_bytes),
        daemon=True,
        name="ksi-spatial-data-stdin-pump",
    )
    try:
        # RawIOBase is the correct runtime base (TextIOWrapper buffers it
        # itself); the ignore covers only the stubs' Buffer expectation.
        text = io.TextIOWrapper(sink, encoding="utf-8", newline="\n")  # type: ignore[type-var]
        stdout_stream = anyio.wrap_file(text)
        # Stored stream (closed explicitly at teardown), not one-shot file use.
        stdin_text = io.TextIOWrapper(
            open(inbound_reader, "rb"),  # noqa: SIM115
            encoding="utf-8",
            errors="replace",
        )
        stdin_stream = anyio.wrap_file(stdin_text)
        pump.start()
        try:
            async with stdio_server(stdin=stdin_stream, stdout=stdout_stream) as streams:
                yield streams
        except BaseException:
            # Release session wires so thread-blocked SDK readers, writers,
            # and the pump can unwind; the original exception propagates.
            for descriptor in (inbound_reader, inbound_writer):
                with suppress(OSError):
                    os.close(descriptor)
            raise
        finally:
            with suppress(OSError, ValueError):
                await stdout_stream.aclose()
            with suppress(OSError, ValueError):
                await stdin_stream.aclose()
    finally:
        with suppress(OSError):
            os.dup2(restore_fd, 1)
        with suppress(OSError):
            os.close(restore_fd)


_READ_TOOLS = frozenset(
    {
        "ksi_list_spatial_data_assets",
        "ksi_get_spatial_data_asset",
        "ksi_list_spatial_data_requests",
        "ksi_get_spatial_data_request",
    }
)
_MUTATION_TOOLS = frozenset(
    {
        "ksi_create_spatial_data_request",
        "ksi_cancel_spatial_data_request",
    }
)
_TOOL_DESCRIPTIONS = {
    "ksi_list_spatial_data_assets": (
        "List grant-filtered native DSM/orthophoto assets for one supplied Site and WorkArea."
    ),
    "ksi_get_spatial_data_asset": (
        "Read one granted asset projection for a supplied Site, WorkArea, and assetRef."
    ),
    "ksi_create_spatial_data_request": (
        "Request one native-grid rectangle with a caller idempotency key; "
        "the adapter always supplies NATIVE resolution and EXTERNAL_AI purpose."
    ),
    "ksi_list_spatial_data_requests": (
        "List durable preparation jobs for one supplied Site and WorkArea."
    ),
    "ksi_get_spatial_data_request": (
        "Read one durable job plus its deterministic file reference when completed."
    ),
    "ksi_cancel_spatial_data_request": (
        "Cancel one durable job for a supplied Site, WorkArea, and jobId."
    ),
}


def _frame_upper_bound(serialized: bytes) -> int:
    """Conservative in-callback pre-check: payload twice (the duplicated text),
    plus every character the outer JSON-RPC serialization must escape (each
    quote/backslash gains a byte; controls and non-ASCII gain up to eight),
    plus the protocol envelope allowance. This only decides safe-error-first
    versus emit-and-verify; the writer measures the actual frame exactly.
    """
    text = serialized.decode("utf-8")
    escapable = 0
    for character in text:
        ordinal = ord(character)
        if character == '"' or character == chr(92):
            escapable += 1
        elif ordinal < 0x20 or ordinal > 0x7E:
            escapable += 8
    return 2 * len(serialized) + escapable + _PROTOCOL_OVERHEAD_BYTES


def _error_result(code: str, remediation: tuple[str, ...] | None = None) -> types.CallToolResult:
    try:
        payload_model = TOOL_ERROR_MODEL.model_validate(
            {
                "code": code,
                "remediation": list(remediation)
                if remediation is not None
                else list(remediation_for(code)),
            }
        )
    except Exception:
        payload_model = TOOL_ERROR_MODEL.model_validate(
            {"code": "INVALID_CORE_RESPONSE", "remediation": ["CONTACT_OPERATOR"]}
        )
    payload = payload_model.model_dump(by_alias=True, mode="json")
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=serialized)],
        structured_content=payload,
        is_error=True,
    )


def build_server(client: CoreSpatialDataClient) -> Server[dict[str, Any]]:
    """Create the fixed v2 low-level server without a FastMCP compatibility layer."""
    limit_bytes = client.config.max_structured_response_bytes

    def _output_schema(name: str) -> dict[str, Any]:
        # Hoist nested $defs to the top level so the advertised schema is a
        # standalone JSON Schema: refs of the form '#/$defs/...' resolve
        # against this document, not against an anyOf branch.
        definitions: dict[str, Any] = {}
        branches: list[dict[str, Any]] = []
        for model in (TOOL_RESULT_MODELS[name], TOOL_ERROR_MODEL):
            schema = model.model_json_schema(by_alias=True)
            for key, definition in schema.pop("$defs", {}).items():
                if key in definitions and definitions[key] != definition:
                    raise ValueError(f"conflicting schema definition: {key}")
                definitions[key] = definition
            branches.append(schema)
        output: dict[str, Any] = {"type": "object", "anyOf": branches}
        if definitions:
            output["$defs"] = definitions
        return output

    async def list_tools(
        _context: Any, _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        tools: list[types.Tool] = []
        for name, model in TOOL_ARGUMENT_MODELS.items():
            read_only = name in _READ_TOOLS
            tools.append(
                types.Tool(
                    name=name,
                    description=_TOOL_DESCRIPTIONS[name],
                    input_schema=model.model_json_schema(by_alias=True),
                    output_schema=_output_schema(name),
                    annotations=types.ToolAnnotations(
                        read_only_hint=read_only,
                        destructive_hint=False,
                        idempotent_hint=True,
                        open_world_hint=False,
                    ),
                )
            )
        return types.ListToolsResult(tools=tools)

    async def call_tool(_context: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        # Callbacks never raise for budget: the bounded writer is the exact
        # boundary, so an oversized frame closes the session there instead of
        # delegating rendering to a framework fallback.
        try:
            payload = await client.invoke(params.name, params.arguments)
        except CoreAdapterError as exc:
            return _error_result(exc.code, exc.remediation)
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if _frame_upper_bound(serialized.encode("utf-8")) > limit_bytes:
            return _error_result("CORE_RESPONSE_TOO_LARGE")
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=serialized)],
            structured_content=payload,
        )

    assert set(TOOL_ARGUMENT_MODELS) == set(TOOL_RESULT_MODELS) == set(_TOOL_DESCRIPTIONS)
    assert set(TOOL_ARGUMENT_MODELS) == _READ_TOOLS | _MUTATION_TOOLS
    return Server(
        "ksi-spatial-data-mcp",
        version="0.0.1",
        instructions=(
            "Use only the six KSI spatial-data tools with explicit Site and WorkArea "
            "identifiers. Tools transfer metadata and file references only, never "
            "raster bytes, credentials, or storage locations."
        ),
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


def _parse_config_path(argv: list[str]) -> Path:
    parser = argparse.ArgumentParser(prog="ksi-spatial-data-mcp")
    parser.add_argument("--config", required=True)
    parsed, unknown = parser.parse_known_args(argv)
    if unknown:
        raise AdapterConfigurationError("only --config is accepted")
    config = parsed.config
    if type(config) is not str or not config.startswith("/") or config != config.strip():
        raise AdapterConfigurationError("config path must be absolute")
    return Path(config)


def _load_client(config_path: Path) -> CoreSpatialDataClient:
    return CoreSpatialDataClient(AdapterConfig.from_file(config_path))


async def _serve(client: CoreSpatialDataClient) -> None:
    server = build_server(client)
    async with _bounded_stdio(client) as (
        read_stream,
        write_stream,
    ):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def _flatten_group(exc: BaseExceptionGroup) -> list[BaseException]:
    leaves: list[BaseException] = []
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop()
        if isinstance(current, BaseExceptionGroup):
            stack.extend(current.exceptions)
        else:
            leaves.append(current)
    return leaves


def _stderr_code(code: str) -> None:
    with suppress(OSError, ValueError):
        sys.stderr.write(f"ksi-spatial-data-mcp: {code}\n")
        sys.stderr.flush()


def main(argv: list[str] | None = None) -> None:
    """Start one local stdio session; stdout remains reserved for MCP frames."""
    try:
        client = _load_client(_parse_config_path(sys.argv[1:] if argv is None else argv))
    except AdapterConfigurationError:
        print("ksi-spatial-data-mcp: CONFIGURATION_UNAVAILABLE", file=sys.stderr)
        raise SystemExit(2) from None
    try:
        asyncio.run(_serve(client))
    except (KeyboardInterrupt, asyncio.CancelledError):
        _stderr_code("CANCELLED")
        raise SystemExit(130) from None
    except BaseExceptionGroup as exc:
        # anyio task-group failures arrive grouped: sanitize to a safe
        # stderr closure without tracebacks or reflected values, while
        # preserving cancellation.
        leaves = _flatten_group(exc)
        if all(isinstance(leaf, (KeyboardInterrupt, asyncio.CancelledError)) for leaf in leaves):
            _stderr_code("CANCELLED")
            raise SystemExit(130) from None
        if all(
            isinstance(leaf, (FrameBudgetExceeded, BrokenPipeError, OSError)) for leaf in leaves
        ):
            # Budget codes are already on stderr (or the pipe is dead).
            raise SystemExit(1) from None
        _stderr_code("CORE_UNAVAILABLE")
        raise SystemExit(1) from None
    except FrameBudgetExceeded:
        # The bounded writer already emitted the safe code to stderr and
        # refused the frame; exit closes the call/session with no partial
        # JSON and no framework-rendered fallback on stdout.
        raise SystemExit(1) from None
    except BrokenPipeError:
        # The client is gone; nothing remains to answer.
        raise SystemExit(1) from None
    except CoreAdapterError as exc:
        # An owner frame limit cannot fit even the safe error envelope:
        # close with a safe stderr code instead of partial JSON.
        _stderr_code(exc.code)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
