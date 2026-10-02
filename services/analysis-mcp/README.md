# KSI Analysis MCP adapter

This independently started **local stdio** process exposes six KSI Analysis API operations to one SDK-compatible MCP client. It owns no listener, persistence, calculation, policy, tenant authorization, or AI-host configuration. Core remains authoritative.

Use only with an exact Core origin and an absolute owner-protected bearer-token file supplied outside this repository. The server accepts HTTP only for a literal loopback address; every other origin must be HTTPS. Core binds AI egress checks to the authenticated `ANALYSIS_MCP_CLIENT` principal and the current Site consent; caller-controlled purpose headers do not grant access. The adapter proceeds only when Core replies `X-KSI-External-AI-Egress: ALLOWED`.

Before use, an operator must supply the Site ID and WorkArea ID and the site must already have `aiEgressAllowed=true`. The adapter cannot discover all sites or alter that consent. `ksi_create_analysis` requires a caller-supplied `idempotencyKey`; it is passed unchanged and never generated or logged.

Example configuration is intentionally declarative, not an installed Codex/Claude/ChatGPT configuration:

```text
KSI_ANALYSIS_MCP_CORE_ORIGIN=http://127.0.0.1:8080
KSI_ANALYSIS_MCP_TOKEN_FILE=/absolute/path/to/token
```

Create a dedicated environment outside the checkout; do not sync the repository's shared or main `.venv`:

```bash
KSI_MCP_VENV=/absolute/path/ksi-analysis-mcp-venv
UV_PROJECT_ENVIRONMENT="$KSI_MCP_VENV" uv sync --package ksi-analysis-mcp
```

For example, an operator can add the following **illustrative, non-installed** local stdio entry to their own Codex configuration after creating that environment. KSI does not write this file or turn on egress consent.

```toml
[mcp_servers.ksi_analysis]
command = "/absolute/path/ksi-analysis-mcp-venv/bin/ksi-analysis-mcp"
env = { KSI_ANALYSIS_MCP_CORE_ORIGIN = "https://192.0.2.10:8443", KSI_ANALYSIS_MCP_TOKEN_FILE = "/absolute/path/owner-only-core-token" }
```

The reusable workflow is deliberately narrow:

1. The operator supplies an authorized `siteId` and `workAreaId`; the Site already has `aiEgressAllowed=true`.
2. Call `ksi_list_analysis_observations` and select one registered baseline and current revision. This V1 discovery response is bounded by the adapter's 512 KiB structured-response ceiling; an oversized response fails explicitly. It is not a suitability or accuracy judgment.
3. Call `ksi_create_analysis` with those selections and a stable caller-generated `idempotencyKey`. The request uses the V2 create route while preserving the V1 selector contract. Reuse that exact key after a client restart; do not put credentials in tool arguments.
4. Poll `ksi_get_analysis` or `ksi_get_analysis_result` using the returned `analysisId`. Both return the same compact V2 detail view; `ksi_get_analysis_result` is a compatibility alias, not a separate result resource. `executionState` and `suitabilityState` are separate: a completed numeric result can remain accuracy-unverified, and a blocked/remediation state is not an official progress or settlement result.
5. Use `ksi_get_analysis_evidence` with the same ID when presenting or passing on a result. It returns a V2 evidence page with up to 32 typed items. Use `limit` and the returned `nextCursor` to continue; `ksi_list_analyses` similarly accepts `limit` up to 50 and a `cursor`. Pages retain Core-recorded inputs, references, calculations, evaluation/checkpoint facts, and limitations. Structured responses above 512 KiB fail explicitly and are never truncated.

`ksi_list_analyses` lists only the supplied Site. The adapter has no global Site/WorkArea discovery, policy mutation, arbitrary fetch, BIM editing, calculation, or listener. The repository's SDK handshake is compatibility evidence for its bundled stdio test client only; it does not configure or verify Codex, Claude, ChatGPT, or another host. Terra samples are currently unavailable, so this package has no Terra compatibility or field-accuracy claim.
