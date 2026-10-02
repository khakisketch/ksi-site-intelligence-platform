# Analysis MCP local adapter implementation plan

> **For agentic workers:** Required sub-skill: `superpowers:test-driven-development`. Execute these tasks in the assigned worktree; do not configure an AI host, deploy, or claim Terra compatibility.

**Goal:** Provide one local stdio MCP adapter that exposes the six already-authoritative Analysis API operations and returns the same scoped Core records or typed failure.

**Architecture:** `services/analysis-mcp` is an independently started stdio process, not a Core route or a calculation engine. It holds one bounded Core HTTP configuration and credential file, adds the explicit `X-KSI-Access-Purpose: EXTERNAL_AI` marker, and accepts a Core response only when Core acknowledges the site-scoped egress decision. Core remains the sole authority for authentication, tenant/site scope, admission, idempotency, suitability, calculation, and evidence.

**Tech stack:** Python 3.12, `mcp==2.2.0` (MIT; official v2 low-level server API), `httpx`, existing Pydantic Analysis DTOs, FastAPI/OpenAPI.

**Spec:** `docs/architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md`, `docs/design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md`

## Global constraints

- Plan ID: `MX-20260922`; task IDs: `MCP01` Core egress gate, `MCP02` stdio adapter/client, `MCP03` real local workflow, `MCP04` contract/docs/freeze.
- Invariants: INV-017/018 leave Analysis Readiness and epoch temporal evidence as Core-derived, fail-closed facts; INV-020 preserves the existing CRS/vertical/unit/timestamp/uncertainty boundary through Core’s Analysis DTO; INV-050 is narrowed here to an additional explicit external-AI egress consent before data returns; INV-053 leaves numerical comparisons to Core's frozen compatible-input/profile path; INV-054 is unchanged because this is no production runtime/image claim; INV-060 folds foreign site/resource into 404; INV-061 keeps this independent from Copilot and makes no flight/device authority.
- Exactly six tools: `ksi_list_analysis_observations`, `ksi_list_analyses`, `ksi_create_analysis`, `ksi_get_analysis`, `ksi_get_analysis_result`, `ksi_get_analysis_evidence`. No arbitrary URL fetch, work-area discovery, mathematics, policy, BIM/point-cloud viewer, Copilot, network listener, or configuration mutation.
- `idempotencyKey` is required for `ksi_create_analysis`, is passed byte-for-byte as `Idempotency-Key`, and is never logged. The tool does not create/reuse a key.
- Core permits `X-KSI-Access-Purpose: EXTERNAL_AI` only after normal bearer authentication and tenant-scoped Site lookup. Missing/foreign Site is 404, disabled consent is 403 `AI_EGRESS_NOT_ALLOWED`, another supplied purpose is typed 400, and an absent purpose preserves existing callers. A marked successful response includes `X-KSI-External-AI-Egress: ALLOWED`; the adapter rejects an unacknowledged success.
- Adapter Core origin is exact, with HTTPS for non-loopback hosts and HTTP only for literal loopback IP. It disables proxies and redirects, uses a total timeout and byte cap, reads an absolute owner-protected token file, writes protocol only to stdout, and maps allowlisted API codes to typed MCP errors without returning raw response bodies or secrets.
- Local SDK handshake is compatibility evidence for the bundled stdio test client only; it is not evidence that Codex, Claude, ChatGPT, or any configured host has been configured or verified. Terra DSM/report samples are unavailable.

## Required implementation record

| Item | Record |
|---|---|
| Requirement IDs | REQ-INT-101/102/104; REQ-SEC-101. |
| Owner module | `services/analysis-mcp/` owns only the independently started stdio adapter; `services/core/.../external_analysis_api.py` owns the additive Core purpose gate. |
| Acceptance | SDK stdio client lists exactly six tools; marked calls require Core acknowledgement; MCP create reaches the existing actual Core/worker/result/evidence loop and returns the same stored JSON as direct API; an unchanged key reuses the record. |
| Contracts affected | Additive `X-KSI-Access-Purpose` request and `X-KSI-External-AI-Egress` success headers on the six frozen Analysis paths; shared `CreateAnalysisRequestV1` and selector DTO are consumed unchanged. |
| Reference/adoption | Adopt official `mcp==2.2.0` low-level `Server` + stdio transport (MIT); no reference repository runtime code. |
| Files/tests | MCP package, bounded Core gate/OpenAPI, local fixture opt-in, `test_analysis_mcp_stdio.py`, existing Analysis API contract tests; ignored `/home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform/.opencode/artifacts/mcp-analysis-20260922/run_source.py` is the pre-existing source runner. |
| HIL/real device | None. The local GeoTIFF loopback test is software-only; Terra samples are unavailable. |
| License/data | SDK is MIT. The test uses synthetic local GeoTIFF bytes and a temporary token. Customer artifacts, secrets, and AI-host configuration are never written. |
| Rollback | Remove the opt-in MCP package and the additive declared-purpose branch/header documentation in a future approved change; do not alter immutable Analysis journals, results, or evidence. |

---

### Task MCP01: Core’s explicit external-AI egress gate

**Files:**
- Modify: `services/core/src/ksi_core/domains/external/quantity/external_analysis_api.py`
- Modify: `contracts/api/openapi-core.yaml`
- Modify: `tests/contract/test_external_analysis_api.py`
- Modify: `tests/contract/analysis_api_local_fixture.py`

**Interfaces:** Existing six routes accept optional `X-KSI-Access-Purpose`. For exact `EXTERNAL_AI`, scoped successful calls emit `X-KSI-External-AI-Egress: ALLOWED`; no header is emitted for ordinary callers.

- [x] Write focused HTTP tests showing disabled consent produces 403 before a create can append, foreign site remains 404, an unknown purpose is 400, and an allowed read/create returns the acknowledgment header.
- [x] Observe the focused gate test fail before the gate/header implementation, then make it green.
- [x] Add one router-local gate that uses the existing Site store through the facade after principal authentication and before every facade operation; reuse it on all six paths and document the optional request/response headers in OpenAPI.
- [x] Add an explicit `ai_egress_allowed` fixture option defaulting to false; run the focused tests and existing Analysis API contract tests.

### Task MCP02: Bounded stdio MCP adapter

**Files:**
- Create: `services/analysis-mcp/pyproject.toml`
- Create: `services/analysis-mcp/README.md`
- Create: `services/analysis-mcp/src/ksi_analysis_mcp/__init__.py`
- Create: `services/analysis-mcp/src/ksi_analysis_mcp/config.py`
- Create: `services/analysis-mcp/src/ksi_analysis_mcp/core_client.py`
- Create: `services/analysis-mcp/src/ksi_analysis_mcp/server.py`
- Create: `tests/contract/test_analysis_mcp_stdio.py`

**Interfaces:** `ksi-analysis-mcp = ksi_analysis_mcp.server:main`; environment supplies only an exact Core origin and absolute token-file path. Tool input is closed Pydantic-shaped JSON and tool output is the exact JSON returned by Core.

- [x] Write subprocess stdio tests that initialize the official SDK server, list exactly six tools with correct read/mutation annotations, call a read tool, require `idempotencyKey` for create, and prove malformed URL/token file/redirect/oversized body/unacknowledged success produce safe typed failures.
- [x] Observe the new stdio test fail with no package/entrypoint before implementation.
- [x] Implement config validation, a non-following `httpx` client with `trust_env=False`, capped streaming decode, allowlisted status mapping, explicit acknowledgement check, shared output DTO validation/schema declaration, and an official v2 low-level stdio server registering only the six tools.
- [x] Run the stdio tests until green; SDK client verifies the exact list, structured success, and typed `is_error` failure. The process has no non-protocol stdout writes.

### Task MCP03: Same-record local end-to-end workflow

**Files:**
- Modify: `tests/contract/test_analysis_mcp_stdio.py`
- Create: `.opencode/artifacts/mcp-analysis-20260922/run_source.py` (ignored helper only)

**Interfaces:** The existing explicit local Analysis fixture accepts `ai_egress_allowed=True`. The test starts real Core HTTP, loopback object HTTP, the MCP stdio process, and the real Processing worker; it compares direct API and MCP result/evidence JSON.

- [x] Write an integration test that creates through MCP, completes through the real worker, verifies direct API/result/evidence parity, starts a second SDK stdio session with the same key, and verifies the same calculation request plus no second intent.
- [x] Observe its initial missing-adapter failure before implementation.
- [x] Reuse the existing synthetic GeoTIFF fixture with explicit opt-in egress; do not alter fixture defaults or Core processing behavior.
- [x] Run that workflow plus tenant/read-only/key-conflict/no-ack negative cases and existing AX regression tests.

### Task MCP04: Contract evidence and handoff

**Files:**
- Modify: `uv.lock`
- Modify: `tests/contract/test_api_contract_sync.py` only if its exact static OpenAPI expectation requires the additive headers
- Modify: this plan with actual check evidence

- [x] Add only the `mcp==2.2.0` workspace package dependency and lock resolution; the reviewed lock delta adds eleven packages and changes/removes no locked existing package.
- [x] Run API contract synchronization, focused Core/MCP tests, static checks, and the reproducible source helper.
- [x] Record final freeze content hashes in the guarded external review manifest after this ledger update; rollback remains removal of this opt-in adapter package and the additive Core purpose branch while retaining immutable Analysis journals/results.

## Implementation evidence

- Isolated environment: `UV_PROJECT_ENVIRONMENT=/tmp/ksi-analysis-mcp-20260922/.mcp-venv uv sync --all-packages`. This dedicated task environment is separate from the shared/main `.venv`, which was not used or changed.
- Default developer install proof: `UV_PROJECT_ENVIRONMENT=/tmp/ksi-analysis-mcp-20260922/.mcp-default-venv uv sync --dry-run` resolved the locked editable `ksi-analysis-mcp==0.0.1`; no environment was created or changed by this dry run.
- Source runner: every test command below uses `/home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform/.opencode/artifacts/mcp-analysis-20260922/run_source.py`, which prepends `/tmp/ksi-analysis-mcp-20260922/{packages,services}/*/src`. The stdio subprocess uses that task environment's `os.sys.executable`, so it imports the assigned checkout rather than `main`.
- `.../.mcp-venv/bin/python -m ruff check services/analysis-mcp services/core/src/ksi_core/domains/external/quantity/external_analysis_api.py tests/contract/test_analysis_mcp_stdio.py tests/contract/analysis_api_local_fixture.py tests/contract/test_external_analysis_api.py tests/contract/test_external_analysis_api_contract.py` — pass.
- `.../.mcp-venv/bin/python -m mypy services/analysis-mcp/src` — `Success: no issues found in 4 source files`.
- `... run_source.py pytest -q tests/contract/test_analysis_mcp_stdio.py` — `7 passed` (SDK stdio handshake/list/error, constrained transport, and actual Core/object/worker same-record workflow).
- `... run_source.py pytest -q tests/contract/test_external_analysis_api.py tests/contract/test_external_analysis_api_contract.py tests/contract/test_external_analysis_execution_integration.py tests/contract/test_external_analysis_http_integration.py tests/contract/test_external_analysis_intents.py tests/contract/test_external_analysis_measurement.py tests/contract/test_external_analysis_worker_api.py tests/contract/test_external_analysis_worker_loop.py` — `73 passed`.
- `... run_source.py pytest -q tests/contract/test_api_contract_sync.py tests/contract/test_external_relative_volume_analysis_contract.py tests/contract/test_external_relative_volume_calculation_contract.py tests/replay/test_external_analysis_api_replay.py` — `56 passed`.
- Independent review correction: the new targeted tests first reproduced two v3 failures: a deleted runtime token file escaped as `AdapterConfigurationError`, and whitespace/non-ASCII/CR-LF idempotency keys could reach transport. `CoreAnalysisClient` now maps only runtime `AdapterConfigurationError` from token reading to `CORE_CREDENTIAL_UNAVAILABLE`; `CreateAnalysisArguments` accepts only printable ASCII keys that are nonblank and have no leading/trailing ASCII spaces, without normalizing accepted values. The official SDK subprocess regression asserts `isError` carries only the stable credential code without its path, token, or traceback, and the header regression asserts invalid keys make no preflight/POST while a valid key reaches Core unchanged.
- Second review correction: leading/trailing ASCII-space keys were RED because h11 would otherwise reject them after preflight. They now fail argument validation with zero HTTP calls; interior spaces remain accepted and are forwarded byte-for-byte. `... run_source.py pytest -q tests/contract/test_analysis_mcp_stdio.py` — `9 passed`; the added edge-space regression was RED before the correction and GREEN afterward. `mypy services/analysis-mcp/src` and the focused `ruff check` command above pass unchanged.

## Initial implementation limits (before actual-host follow-up)

- This proves only a local official SDK v2.2.0 stdio client and synthetic Core/GeoTIFF/worker path. The documented Codex block is illustrative and was not installed; Codex, Claude, ChatGPT, other hosts, production identity, deployment, Tailscale, and real customer data were not exercised.
- Terra DSM/report samples remain unavailable. No Terra format compatibility, field accuracy, settlement, progress, HIL, device, or robotic-action claim is made.
- Final exact path/content hashes are in `/home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform/.opencode/artifacts/mcp-analysis-20260922/freeze-v5.json` and its paired `review-v5.patch` (generated only after this ledger was fixed).

## Coverage review

MCP01 enforces INV-050/060 at the Core boundary without changing absent-header clients. MCP02 enforces bounded transport, explicit idempotency, and the no-new-authority boundary. MCP03 proves the single durable Core result path with real local HTTP, worker, GeoTIFF, and stdio protocol. MCP04 keeps the generated contract and dependency evidence reproducible. No task changes Terra support, a real AI-host configuration, production authentication, deployment, device control, or the current product slice.

## Lead integration evidence — 2026-09-22

- Authoritative task record is now this main-checkout ledger. The isolated worktree copy is historical implementation evidence. Local software task is implemented and verified; product-state/EXT-VAL and Human slice acceptance are unchanged.
- Independent read-only review of frozen v5: PASS (`.opencode/artifacts/mcp-analysis-20260922/integration-review-v5.md`). Previous typed-error and header-validation findings were corrected and re-reviewed.
- Guarded application copied exactly 16 reviewed paths from `freeze-v5.json`; all other 2,132-baseline entries outside that delta were checked unchanged. Main HEAD remains `9edc4a18e873e356f5cfea7d69437f1fb5e11acd`; no commit or deployment.
- Main-source verification: `run_main.py pytest -q` on MCP stdio, external Analysis API, API contract, HTTP integration, API sync, and Analysis replay suites: **86 passed in 49.76s**, exit 0. Log: `.opencode/artifacts/mcp-analysis-20260922/main-validation-v5.log`.
- Parent imports were asserted under main. Both SDK stdio child paths used the main-source Python wrapper; its MCP/contracts import origins were separately verified. The dedicated task environment supplies dependencies only; the shared main `.venv` was not modified.
- Main `git diff --check` passed. All 16 applied content hashes matched the reviewed freeze before this factual ledger append; non-task inherited hashes remained unchanged.
- Actual Codex/Claude/ChatGPT host activation, production credential provisioning/deployment, Tailscale, customer data, and Terra DSM/report compatibility remain untested. User explicitly reports Terra samples unavailable. No product slice completion or field-accuracy claim.
- Next operational acceptance: configure an explicitly selected local AI host and authorized test identity against the verified stack, then demonstrate the same request/result flow. Terra acceptance remains a separate gate requiring real two-epoch samples and reports.

## Actual Codex host follow-up — 2026-09-22

User approved proceeding to the stated next step: actual Codex MCP request/result validation. This evidence supersedes only the earlier “actual Codex untested” limit for the local synthetic workflow. No product source or persistent host configuration was changed.

- Reused the existing synthetic GeoTIFF/common Core fixture and actual measurement worker. Protected fixture authority files ran in an owner-only temporary directory; the first artifact-directory setup was rejected by existing ancestor-permission checks, and no security check was bypassed or relaxed.
- Two real `codex exec --ignore-user-config --ephemeral` sessions, invocation-scoped MCP settings, read-only workspace. Existing configured model `gpt-6-astra`/`low` was retained. Observed CLI version `0.155.1`; version/path/hash were recorded after execution, not as launch-time attestation. Existing ChatGPT login was used; the Core principal was a temporary synthetic fixture operator.
- First session: observation list → create → detail, resulting in `QUEUED`. Lead ran the actual fixed-profile worker once. Second fresh session: analysis list → result → evidence → identical create retry, resulting in `COMPLETED`.
- Raw events show **7 successful MCP calls across all 6 tools**, both CLI processes exit 0, stderr empty, and no shell/tool activity beyond KSI MCP. MCP result and evidence JSON exactly equal direct Core API responses.
- Retry arguments, Analysis ID, calculation request ID and stored result remain identical; durable intent count is one.
- Independent evidence review: **ACCEPTED for actual local Codex two-session synthetic workflow only**. Record: `.opencode/artifacts/codex-mcp-acceptance-20260922/evidence-review.md`.
- Evidence directory also contains raw events, direct API JSON, `asserted-evidence.json`, and `evidence-manifest.json`. Before this factual ledger update, all 2,140 repository baseline file hashes were unchanged. Temporary bearer-token file was removed and harness-owned servers exited. `git diff --check` passed.
- No persistent Codex setup, production identity, remote CI, deployment, Tailscale, Claude/ChatGPT host, Terra real-artifact, field-accuracy, or Human product-slice acceptance follows. Terra samples remain unavailable. No commit/push/PR or deployment.
- Remaining acceptance: separately scoped persistent/operator environment and real Terra two-epoch data/report validation. Product-state/EXT-VAL remains unchanged.
