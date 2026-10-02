"""Official MCP v2 low-level stdio server for the fixed Analysis tool set."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .config import MAX_STRUCTURED_RESPONSE_BYTES, AdapterConfig
from .core_client import (
    TOOL_ARGUMENT_MODELS,
    TOOL_RESULT_MODELS,
    CoreAdapterError,
    CoreAnalysisClient,
)

_READ_TOOLS = frozenset(
    {
        "ksi_list_analysis_observations",
        "ksi_list_analyses",
        "ksi_get_analysis",
        "ksi_get_analysis_result",
        "ksi_get_analysis_evidence",
    }
)
_TOOL_DESCRIPTIONS = {
    "ksi_list_analysis_observations": (
        "List registered selectable observation revisions for one supplied Site; "
        "this does not make a suitability judgment."
    ),
    "ksi_list_analyses": "List durable Analysis records for one supplied Site.",
    "ksi_create_analysis": "Create or retry one supplied WorkArea Analysis with a caller key.",
    "ksi_get_analysis": "Read one durable Analysis state for a supplied Site.",
    "ksi_get_analysis_result": "Read one durable Analysis result state for a supplied Site.",
    "ksi_get_analysis_evidence": "Read provenance and restrictions for one supplied Analysis.",
}


def build_server(client: CoreAnalysisClient) -> Server[dict[str, Any]]:
    """Create the fixed v2 low-level server without a FastMCP compatibility layer."""

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
                    output_schema=TOOL_RESULT_MODELS[name].model_json_schema(by_alias=True),
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
        try:
            payload = await client.invoke(params.name, params.arguments)
        except CoreAdapterError as exc:
            return _error_result(exc.code)
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(serialized.encode("utf-8")) > MAX_STRUCTURED_RESPONSE_BYTES:
            return _error_result("CORE_RESPONSE_TOO_LARGE")
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=serialized)],
            structured_content=payload,
        )

    return Server(
        "ksi-analysis-mcp",
        version="0.0.1",
        instructions=(
            "Use only the six KSI Analysis tools with explicit Site and WorkArea identifiers."
        ),
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )


def _error_result(code: str) -> types.CallToolResult:
    payload = {"code": code}
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, separators=(",", ":")))],
        structured_content=payload,
        is_error=True,
    )


async def _serve() -> None:
    client = CoreAnalysisClient(AdapterConfig.from_environ())
    server = build_server(client)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    """Start one local stdio session; stdout remains reserved for MCP frames."""
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
