# KSI Analysis MCP adapter

This independently started **local stdio** process exposes seven existing Analysis operations plus three additive delta-publication operations to one SDK-compatible MCP client. It owns no listener, persistence, calculation, policy, tenant authorization, or AI-host configuration. Core remains authoritative.

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
3. Call `ksi_check_analysis_readiness` with `siteId`, `workAreaId`, `baseline` and `current` to inspect the exact pair without starting work. This read-only tool accepts no idempotency key, creates no analysis or journal record, and returns current suitability, per-epoch blockers, limitations and `checkedAt`. An otherwise scoped registered pair can be checked even when unknown capture timing excludes it from execution candidates. `coverageCheck=REQUIRES_WORKER_VALIDATION` always means actual common-mask validation is still required; the response grants no execution authority.
4. When the caller intends to execute, call `ksi_create_analysis` with those selections and a stable caller-generated `idempotencyKey`. Core rechecks all conditions; a previous readiness response is not an admission token. The request uses the V2 create route while preserving the V1 selector contract. Reuse that exact key after a client restart; do not put credentials in tool arguments.
5. Poll `ksi_get_analysis` or `ksi_get_analysis_result` using the returned `analysisId`. Both return the same compact V2 detail view; `ksi_get_analysis_result` is a compatibility alias, not a separate result resource. `executionState` and `suitabilityState` are separate: a completed numeric result can remain accuracy-unverified, and a blocked/remediation state is not an official progress or settlement result.
6. Use `ksi_get_analysis_evidence` with the same ID when presenting or passing on a result. It returns a V2 evidence page with up to 32 typed items. Use `limit` and the returned `nextCursor` to continue; `ksi_list_analyses` similarly accepts `limit` up to 50 and a `cursor`. Pages retain Core-recorded inputs, references, calculations, evaluation/checkpoint facts, and limitations. Structured responses above 512 KiB fail explicitly and are never truncated.

`ksi_list_analyses` lists only the supplied Site. The adapter has no global Site/WorkArea discovery, policy mutation, arbitrary fetch, BIM editing, calculation, or listener. The repository's SDK handshake is compatibility evidence for its bundled stdio test client only; it does not configure or verify Codex, Claude, ChatGPT, or another host. Terra samples are currently unavailable, so this package has no Terra compatibility or field-accuracy claim.

## Separate delta output (explicit Core extension required)

`ksi_create_delta_publication` sends a caller-retained opaque `publicationId`, the exact calculation,
numeric-result and coverage-witness digests, and an explicit `lifetimeSeconds`. It sends no grid,
coordinate, policy, source URL or original imagery. Core derives those facts from its current source
records and separately signed output policy/runtime. A completed numeric result does not itself
authorize this output job; an unmounted or unavailable lane returns an error, never a fake file.

`ksi_get_delta_publication` reads the guarded published descriptor. `ksi_read_delta_publication_bytes`
reads only an explicit `offset`/`length` slice (at most 1 MiB), using canonical base64. Each request
rechecks Core's scoped machine identity and Site AI-egress consent and requires the same
`X-KSI-External-AI-Egress: ALLOWED` acknowledgment as the existing Analysis operations. Response scope,
source echoes and byte ranges are checked; no arbitrary URL fetch or TIFF decoding is exposed.
Unavailable reads do not prove a pending job: the output may instead be expired, revoked or blocked.

These operations do not modify the numeric result or bypass the separate publication lifetime,
activation, input-rights or worker-host gates. The generated loopback/SDK tests prove local protocol
behavior, not an installed external AI host, production activation or customer accuracy.
