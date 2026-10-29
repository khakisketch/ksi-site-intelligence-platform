# KSI Analysis MCP adapter

This independently started **local stdio** process exposes seven existing Analysis operations,
three delta-publication operations and seven additive spatial-task operations to one SDK-compatible
MCP client. It owns no listener, persistence, calculation, policy, tenant authorization, or AI-host
configuration. Core remains authoritative. Existing Analysis tool shapes are unchanged.

Use only with an exact Core origin and an absolute owner-protected bearer-token file supplied outside this repository. The server accepts HTTP only for a literal loopback address; every other origin must be HTTPS. Core binds AI egress checks to the authenticated `ANALYSIS_MCP_CLIENT` principal and the current Site consent; caller-controlled purpose headers do not grant access. The adapter proceeds only when Core replies `X-KSI-External-AI-Egress: ALLOWED`.

Before use, an operator provisions explicit Site/WorkArea grants and the Site must already have
`aiEgressAllowed=true`. Users need not know these identifiers: the new task tools return **named,
already granted** candidates. They cannot discover all sites, issue credentials or alter consent.
The original `ksi_create_analysis` workflow still accepts supplied selectors and a caller-retained
`idempotencyKey`; existing integrations need not adopt tasks.

Example configuration is intentionally declarative, not an installed Codex/Claude/ChatGPT configuration:

```text
KSI_ANALYSIS_MCP_CORE_ORIGIN=http://127.0.0.1:8080
KSI_ANALYSIS_MCP_TOKEN_FILE=/absolute/path/to/token
# Required only for spatial-task handoff tools; no default or caller-supplied redirect:
KSI_ANALYSIS_MCP_CONSOLE_ORIGIN=http://localhost:3000
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

## Question → map selection → same-task resume

1. `ksi_list_spatial_task_sites` returns named candidates only from explicitly provisioned Site grants
   with current consent (32/page, `nextOffset`). Ask for a Site only when ambiguous; never invent IDs.
2. `ksi_create_spatial_task` takes `siteId`, a stable `idempotencyKey` and `request`. Use
   `purpose=OBSERVED_CHANGE` for **two-observation terrain change**, or `CLARIFY` if the meaning is
   ambiguous. `DESIGN_REMAINING` and `DAILY_TARGET` remain unsupported — no implicit substitution.
   Reuse an explicitly shared `workAreaId` and exact `inputs={baseline,current}` when known.
3. `ksi_get_spatial_task_options` takes `siteId`/`taskId`. It returns named existing areas and dated,
   area-attributed observations (32 observations/page; use `nextOffset`). Choose an explicitly named
   unambiguous area with `ksi_select_spatial_task`, or give the user the returned `selectionUrl`.
   This points to the configured **Console**, not Core, and requires a separate human login and
   current selection permissions. No token, storage URL or coordinate copying is involved.
4. The Console shows the registered boundary and ordered observation dates. It can save **area only**
   before choosing observations, or preserve the exact pair. A no-UI host can tell the user:
   “Open this selection link, save, then say ‘선택했어’.” No embedded MCP Apps map or automatic
   cross-browser/host callback is advertised. Below1024px, current desktop-only mutation UX remains.
5. `ksi_get_spatial_task` resumes the **same** saved task; do not restart the question or reconstruct
   coordinates. `ksi_select_spatial_task` accepts a full replacement `request` with `expectedRevision`,
   purpose, area and optional exact inputs. Conflicting concurrent selections are409, not last-write-wins.
6. `ksi_check_spatial_task` takes `request={expectedRevision}` and invokes the existing read-only
   Analysis readiness for the saved selection. It writes no task/analysis/worker journal and grants
   no execution permission. Explain blockers and actual capture dates, not guessed quantities.
7. On the user's execution intent, `ksi_run_spatial_task` uses the same task/revision. Core rechecks
   grants, consent, activation and Analysis conditions. It durably reserves selection, then uses the
   existing idempotent Analysis create. A crash between journals resumes one Analysis. Selection is
   locked after reservation; changed bounds/pair require a new task, not mutation of past results.
8. Read `ksi_get_spatial_task` for the current linked Analysis V2 result. The task's Console page keeps
   the registered boundary and exact pair beside Core-returned quantities and valid-range counts;
   it does not pretend to render a valid/excluded-cell distribution layer. `analysisHref` opens the
   same existing detailed result/evidence; original tools still work with `task.analysisId`.
   A failure/blocker never becomes a fabricated zero, quantity or field-accuracy claim.

Task links expire after7days; results/evidence are not deleted by that expiry. Retained capacity is
bounded (2048 tasks/org, 10000 total, 128 revisions/task). Both reservation/link revisions must fit
before Analysis creation; a revision-limit refusal starts no Analysis. Exhausted history fails closed; no
implicit cleanup/eviction is introduced. External clients read only their own tasks. Human selection
intersects current human grants with the creator's original area ceiling; external resume rechecks
the client's **current** grants and consent. A newly registered WorkArea does not widen those grants
or the retained ceiling. New scope requires separate provisioning and a new task; the adapter does
not issue that authorization. Links and task IDs are not capabilities.

The Console origin is exact operator configuration (HTTPS, or loopback HTTP including `localhost`),
not a tool argument. Without it handoff tools fail `CONSOLE_ORIGIN_REQUIRED` **before mutation**.
Mutating tools first require an acknowledged machine-channel read, so a mistakenly configured human
credential cannot cause a task mutation and only then fail the egress acknowledgment. Each tool
invocation snapshots its token once and uses that same token for the read and the subsequent POST;
the next invocation reads the file again. The read is not an authorization grant: Core independently
rechecks current scope, consent and rights on the POST. This protects the adapter's own calls only;
it cannot detect a server-side remapping of the same opaque token to another principal.

Analysis and delta creation perform the existing bounded Site observation read before their POST.
If this read is unavailable, unacknowledged, or exceeds the adapter response limit, no creation is
attempted, even if a direct Core request might otherwise succeed. A lost POST response still does not
prove whether Core accepted it: retry the same body and original key, task revision or publication ID
as applicable, rather than silently starting a different request. A malformed or scope-mismatched 2xx,
or a missing egress acknowledgment, after a POST likewise does not prove the mutation was rejected:
treat it like a lost reply — retain the exact original body, key, task revision or publication ID and
the same token identity, and do not automatically replay the intent under a new actor or key.

Contracts: `contracts/schemas/external-spatial-task.v1.json`, the additive paths in
`contracts/api/openapi-core.yaml`, and `ksi_event_contracts.external_spatial_task`.
Local generated TIFF/actual parser/worker/stdio/restart tests are in
`tests/contract/test_external_spatial_tasks.py`. Actual external-host setup, remote/public access,
customer data/accuracy and production deployment remain unverified and are not configured here.

## Original explicit-selector workflow (unchanged)

1. The operator supplies an authorized `siteId` and `workAreaId`; the Site already has `aiEgressAllowed=true`.
2. Call `ksi_list_analysis_observations` and select one registered baseline and current revision. This V1 discovery response is bounded by the adapter's 512 KiB structured-response ceiling; an oversized response fails explicitly. It is not a suitability or accuracy judgment.
3. Call `ksi_check_analysis_readiness` with `siteId`, `workAreaId`, `baseline` and `current` to inspect the exact pair without starting work. This read-only tool accepts no idempotency key, creates no analysis or journal record, and returns current suitability, per-epoch blockers, limitations and `checkedAt`. An otherwise scoped registered pair can be checked even when unknown capture timing excludes it from execution candidates. `coverageCheck=REQUIRES_WORKER_VALIDATION` always means actual common-mask validation is still required; the response grants no execution authority.
4. When the caller intends to execute, call `ksi_create_analysis` with those selections and a stable caller-generated `idempotencyKey`. Core rechecks all conditions; a previous readiness response is not an admission token. The request uses the V2 create route while preserving the V1 selector contract. Reuse that exact key after a client restart; do not put credentials in tool arguments.
5. Poll `ksi_get_analysis` or `ksi_get_analysis_result` using the returned `analysisId`. Both return the same compact V2 detail view; `ksi_get_analysis_result` is a compatibility alias, not a separate result resource. `executionState` and `suitabilityState` are separate: a completed numeric result can remain accuracy-unverified, and a blocked/remediation state is not an official progress or settlement result.
6. Use `ksi_get_analysis_evidence` with the same ID when presenting or passing on a result. It returns a V2 evidence page with up to 32 typed items. Use `limit` and the returned `nextCursor` to continue; `ksi_list_analyses` similarly accepts `limit` up to 50 and a `cursor`. Pages retain Core-recorded inputs, references, calculations, evaluation/checkpoint facts, and limitations. Structured responses above 512 KiB fail explicitly and are never truncated.

`ksi_list_analyses` lists only the supplied Site. The adapter has no unrestricted Site/WorkArea
discovery, policy mutation, arbitrary fetch, BIM editing, calculation, or listener. The repository's
SDK handshake is evidence for its selected local SDK client, not setup/support of an external AI
host. Terra samples remain unavailable; no Terra compatibility or field-accuracy claim is made.

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
