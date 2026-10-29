"""MCP v2 low-level stdio server for the fixed Analysis tool set."""

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
from .delta_publications import MAX_DELTA_BYTES_RESPONSE_BYTES

_READ_TOOLS = frozenset(
    {
        "ksi_list_spatial_task_sites",
        "ksi_get_spatial_task",
        "ksi_get_spatial_task_options",
        "ksi_check_spatial_task",
        "ksi_list_analysis_observations",
        "ksi_list_analyses",
        "ksi_check_analysis_readiness",
        "ksi_get_analysis",
        "ksi_get_analysis_result",
        "ksi_get_analysis_evidence",
        "ksi_get_delta_publication",
        "ksi_read_delta_publication_bytes",
    }
)
_STRUCTURED_CEILINGS = {
    "ksi_read_delta_publication_bytes": MAX_DELTA_BYTES_RESPONSE_BYTES,
}
_TOOL_DESCRIPTIONS = {
    "ksi_list_spatial_task_sites": (
        "Find named Sites within provisioned scope and AI consent; page with nextOffset."
    ),
    "ksi_create_spatial_task": (
        "Start/resume a durable user task. Use CLARIFY only for ambiguous purpose; OBSERVED_CHANGE "
        "means two-observation terrain change, never design remaining quantity or today's target. "
        "Reuse an explicitly shared area/pair. Otherwise return selectionHref on the configured "
        "Console origin (not Core) for authenticated map selection; the link grants no access."
    ),
    "ksi_get_spatial_task": (
        "Resume the SAME task after Console selection or when the user says selection is done. "
        "Read saved purpose, area, observations and linked Core result. No coordinate copying."
    ),
    "ksi_get_spatial_task_options": (
        "Read named allowed areas and dated observations for this task. Page observations "
        "with nextOffset. Ask only about ambiguity; do not invent IDs, dates or coordinates."
    ),
    "ksi_select_spatial_task": (
        "Save explicitly chosen purpose/area/ordered observation pair with expectedRevision. "
        "Full replacement: retain existing inputs deliberately. AI proposals are drafts; "
        "do not guess ambiguous boundaries. Unsupported purposes stay unsupported."
    ),
    "ksi_check_spatial_task": (
        "Fresh read-only Core readiness for the saved selection; never execution permission."
    ),
    "ksi_run_spatial_task": (
        "Run the user's observed-change task with saved exact selections and expectedRevision. "
        "Core rechecks scope, consent, activation and analysis conditions. Reuse taskId on retry; "
        "Inspect blockers/result and evidence; never invent quantities or settlement accuracy."
    ),
    "ksi_list_analysis_observations": (
        "List registered selectable observation revisions for one supplied Site; "
        "this does not make a suitability judgment."
    ),
    "ksi_list_analyses": "List durable Analysis records for one supplied Site.",
    "ksi_create_analysis": "Create or retry one supplied WorkArea Analysis with a caller key.",
    "ksi_check_analysis_readiness": (
        "Check read-only suitability for one supplied WorkArea selector pair; "
        "this creates no record and grants no execution authority."
    ),
    "ksi_get_analysis": "Read one durable Analysis state for a supplied Site.",
    "ksi_get_analysis_result": "Read one durable Analysis result state for a supplied Site.",
    "ksi_get_analysis_evidence": "Read provenance and restrictions for one supplied Analysis.",
    "ksi_create_delta_publication": (
        "Request one source-bound delta-publication intent for a supplied WorkArea; "
        "Core resolves all grid facts from the bound sources."
    ),
    "ksi_get_delta_publication": (
        "Read one published delta-publication descriptor for a supplied WorkArea."
    ),
    "ksi_read_delta_publication_bytes": (
        "Read one bounded opaque byte chunk of a published delta output; "
        "bytes are passed through, never recomputed or parsed."
    ),
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
        ceiling = _STRUCTURED_CEILINGS.get(params.name, MAX_STRUCTURED_RESPONSE_BYTES)
        if len(serialized.encode("utf-8")) > ceiling:
            return _error_result("CORE_RESPONSE_TOO_LARGE")
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=serialized)],
            structured_content=payload,
        )

    return Server(
        "ksi-analysis-mcp",
        version="0.0.1",
        instructions=(
            "Use closed KSI tools. Start with named scoped Sites and a durable task when "
            "the user does not know IDs. Preserve taskId across authenticated Console selection. "
            "No embedded map is advertised; hosts without UI support use selectionHref and resume. "
            "The six established tools keep their frozen shapes; ksi_check_analysis_readiness "
            "is the additive read-only preflight. The three delta-publication tools are "
            "closed additive external-consumer reads/creates that pass opaque worker bytes "
            "through without recomputation."
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
