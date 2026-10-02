# Persistent local Analysis runtime implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Plan:** PX-20260922  
**Goal:** Allow an operator to opt into the already-assembled Core Analysis graph in a local, loopback-only development runtime using only sealed, protected configuration and explicit existing storage/workflow authority.

**Architecture:** A new Core-owned loader reads one owner-private absolute JSON file and turns its sealed policy, runtime identity, and resource envelope into the existing `ExternalAnalysisLocalGraphConfig`. The development launcher validates all opt-in inputs before reset or bootstrap, loads the existing provider/workflow pair, binds the provider receipt journal, and passes the complete graph to common assembly. The dashboard OIDC launcher only forwards operator-supplied S3 and three protected-config paths; it does not generate authority or change authentication.

**Tech Stack:** Python 3.12, FastAPI/Starlette Core assembly, Pydantic shared contracts, append-only journals, argparse, Node ESM local launcher, pytest/Vitest.

**Spec:** `docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md`, `docs/architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md`, `docs/design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md`.

## Implementation record

| Field | Record |
|---|---|
| Requirement IDs | REQ-INT-101 local configuration is explicit and protected; REQ-INT-102 supported complete graph reuses Core assembly; REQ-INT-104 blocked analysis is durable/replayable; REQ-SEC-101 local opt-in cannot create new authority, expose secrets, or bind non-loopback. |
| Owner module | `services/core` configuration/composition; `scripts/run_core_dev.py`; `apps/dashboard/scripts/run-local-oidc-stack.mjs`; owned contract/replay tests and local-runtime documentation. |
| Acceptance criteria | Valid sealed config plus explicit S3 and provider/workflow pair mounts the existing Analysis API graph; missing artifact inspection produces the existing persisted structured admission blocker (`executionState=NOT_STARTED`, suitability `BLOCKED`, `ESSENTIAL_INPUT_UNAVAILABLE`, null result and no numeric identity) that replays; no config preserves the existing development path; invalid opt-in input fails before reset/bootstrap; failed assembly closes all journals; policy replacement does not rewrite prior persisted results. |
| Contracts affected | Local-only CLI/operator configuration contract; no production environment contract, public API schema, Analysis DTO, policy semantics, or authentication-mode contract changes. |
| Reference assets | Existing `ExternalAnalysisLocalGraphConfig` and `assemble_app`; production provider/workflow assembly; protected `external_result_workflow_config` loader; Analysis HTTP/replay fixtures as tests only. |
| Adoption decisions | Load exactly `{version, policy, runtime, resourceEnvelope}`; accept only canonical sealed policy/envelope objects and no default calculation/engine data. Reuse production provider/workflow loader and receipt-journal lifecycle. Restrict an opted-in dev Core listener to a literal loopback IP. |
| Files to change | Create `services/core/src/ksi_core/composition/local_analysis_runtime_config.py`; modify `scripts/run_core_dev.py`, dashboard OIDC launcher/test, service routing README, Core module inventory, this ledger, and focused contract tests. Production assembly and dashboard UI/TSX remain untouched. |
| Tests | Loader malformed/private-file/seal tests; development assembly/CLI preflight and cleanup tests; real local registered-input blocked/replay test; OIDC launcher forwarding test; affected API sync/boundary and existing AX regression tests. |
| HIL or real-device assumptions | No HIL, device, Terra, or field data. Human confirmed Terra samples are unavailable. A fresh uploaded numeric result remains blocked on an actual supported inspection host and is not asserted or claimed. |
| License/data implications | No new runtime dependency, model, customer data, credential, external service, or vendor integration. Test-only signed material uses ephemeral local paths and is never imported by runtime. |
| Rollback | Remove the new opt-in config/flags and stop forwarding them. Existing dev defaults and production are unchanged; journals/results are append-only and no business records are seeded or rewritten. |

## Invariants and enforcement

| Invariant | Effect in this slice | Enforcement |
|---|---|---|
| INV-017 | Analysis readiness is Core-derived, never supplied by the operator config. | Config accepts only policy/runtime/resource identity; it cannot assert readiness. Existing Core state derives blocked/use status. |
| INV-018 | Observation epochs retain their capture-window semantics. | The launcher does not create, change, or seed observations; existing registration routes own epoch validation. |
| INV-020 | Coordinate reference system, vertical datum, unit, timestamp, and uncertainty remain required spatial facts. | The local config contains no coordinate values or overrides; existing artifact inspection/analysis routes reject insufficient evidence. |
| INV-053 | Quantitative comparison only uses compatible observations with recorded comparison conditions. | The complete existing Analysis graph, rather than a shortcut calculator, handles compatibility and persists blocked conditions. |
| INV-054 | Runtime identity/policy evidence remains immutable and exact. | Both policy and resource envelope must already be sealed with their canonical digests; no digest fill-in or default engine/profile exists. |
| INV-060 | Organization isolation stays with Core authentication and stores. | No tenant rewrite, seeded organization, new auth mode, or client-side authority is added; tests use matching principal/config organizations. |

## Scope constraints

- Local development only. The opt-in path accepts literal loopback Core hosts only; it adds no non-loopback listener, Tailscale activation, production environment setting, worker supervisor, or network endpoint.
- OIDC remains OIDC. The change does not select DUAL authentication, make operator tokens, or alter MCP credentials.
- Workflow/provider files remain separately provisioned authority. The dashboard launcher neither creates them nor falls back to defaults.
- Analysis requires all of: local Analysis config, S3 endpoint/bucket pair, workflow config, and provider config. Either member of each pair alone is rejected before destructive startup behavior.
- Runtime code never imports test helpers, fixture modules, synthetic GeoTIFFs, or fake authority.
- The existing missing-inspection contract is an honest admission blocker:
  `executionState=NOT_STARTED` with suitability `BLOCKED` and
  `ESSENTIAL_INPUT_UNAVAILABLE`; it has no numeric result or calculation
  identity and cannot be relabeled as one.

## File structure

- `services/core/src/ksi_core/composition/local_analysis_runtime_config.py` — strict descriptor-based parse/validation and conversion into `ExternalAnalysisLocalGraphConfig`.
- `scripts/run_core_dev.py` — dev-only CLI/programmatic graph forwarding, opt-in validation, lifecycle cleanup, and loopback enforcement.
- `apps/dashboard/scripts/run-local-oidc-stack.mjs` — explicit operator argument parsing/forwarding only.
- `tests/contract/test_local_analysis_runtime_config.py` — local config security and sealing contract.
- `tests/contract/test_dev_assembly.py` — complete graph, default compatibility, pre-effects validation, journal cleanup, and actual blocked/replay acceptance.
- `apps/dashboard/test/local-oidc-stack.test.ts` — explicit forwarding/no silent defaults.
- `services/README.md` — local-only runbook, independent worker boundary, and blocked fresh-upload limit.

---

### Task LAR01: strict sealed local Analysis runtime configuration

**Files:**
- Create: `services/core/src/ksi_core/composition/local_analysis_runtime_config.py`
- Create: `tests/contract/test_local_analysis_runtime_config.py`

**Interfaces:**
- Consumes: `AnalysisPolicyV2`, `AnalysisRuntimeIdentityV2`, `ResourceEnvelopeV1`.
- Produces: `load_local_analysis_runtime_config(path: Path) -> ExternalAnalysisLocalGraphConfig` and `LocalAnalysisRuntimeConfigUnavailable(code)`.

- [x] **Step 1: Write failing tests for a valid sealed config and reject unsealed/unsafe/malformed inputs.**
- [x] **Step 2: Run the focused tests and verify failure because the local loader is absent.**
- [x] **Step 3: Implement a bounded descriptor reader, duplicate/non-finite JSON rejection, exact top-level fields, private-path checks, model validation, and canonical seal checks.**
- [x] **Step 4: Run the focused tests and verify that valid sealed values are forwarded byte-for-byte and invalid inputs fail closed.**

### Task LAR02: development Core graph assembly and safe CLI preflight

**Files:**
- Modify: `scripts/run_core_dev.py`
- Modify: `tests/contract/test_dev_assembly.py`

**Interfaces:**
- Consumes: LAR01 loader, existing `load_external_authority_provider`, `load_external_result_workflow_config`, `S3EvidenceStorage`, `assemble_app`.
- Produces: `build_dev_app(..., external_analysis_local_graph=..., external_result_workflow=..., external_authority_provider=...)` with correct ownership/cleanup; CLI flags `--local-analysis-config`, `--external-result-workflow-config`, and `--external-authority-provider-config`.

- [x] **Step 1: Write failing tests for complete graph mounting, absent-config compatibility, all-or-nothing S3/config preflight before reset, literal-loopback rejection, and failure cleanup.**
- [x] **Step 2: Run the focused tests and verify current dev assembly cannot forward the local Analysis graph/provider lifecycle.**
- [x] **Step 3: Add only the programmatic/CLI plumbing and production-equivalent provider/workflow receipt lifecycle necessary to satisfy those tests.**
- [x] **Step 4: Run the focused tests and verify startup effects occur only after all opt-in input validates and all opened journals close on failure.**

### Task LAR03: durable blocked analysis and restart evidence

**Files:**
- Reuse: existing `tests/replay/test_external_analysis_api_replay.py`
- Evidence: Lead-owned `.opencode/artifacts/analysis-local-runtime-20260922/http-*.json`

**Interfaces:**
- Consumes: LAR02 mounted graph, test-only registered artifacts with inspection intentionally absent.
- Produces: a persisted structured missing-inspection admission blocker
  (`NOT_STARTED` execution, `BLOCKED` suitability, null result) whose
  restart/replay representation is unchanged.

- [ ] **Step 1: Write the failing end-to-end local-dev test that registers real Core HTTP inputs, requests analysis with missing inspection, restarts from the same data directory, and reads the same blocker.**
- [ ] **Step 2: Run it and verify that current dev startup does not mount the opt-in complete graph.**
- **Superseded evidence:** LAR03 steps 1–2 were not performed. The Lead instead
  ran the stricter independent, real Core HTTP/S3 two-boot probe recorded below;
  it uses actual registration and sealed artifacts, leaves inspection absent, and
  establishes only the existing durable blocker contract.
- [x] **Step 3: Use only LAR02 configuration/assembly changes; do not seed business stores or add a calculator.**
- [x] **Step 4: Run the existing analysis replay suite and the independent real Core HTTP/S3 process probe, verifying a structured blocker is durable.**

### Task LAR04: OIDC launcher and operating documentation

**Files:**
- Modify: `apps/dashboard/scripts/run-local-oidc-stack.mjs`
- Modify: `apps/dashboard/test/local-oidc-stack.test.ts`
- Modify: `services/README.md`
- Modify: `docs/superpowers/plans/2026-09-22-analysis-local-runtime.md`

**Interfaces:**
- Consumes: LAR02 CLI flags.
- Produces: explicit forwarding of S3 endpoint/bucket and the three supplied absolute config paths; a local-only operator workflow.

- [x] **Step 1: Write failing launcher tests asserting explicit forwarding and rejecting incomplete opt-in values without generated authority.**
- [x] **Step 2: Run an equivalent Node source assertion and verify the existing launcher cannot forward this opt-in configuration.**
- [x] **Step 3: Implement minimal ESM parsing/forwarding and document the complete operator-provided material, loopback restriction, independent worker entrypoint, and blocked fresh-upload limitation.**
- [ ] **Step 4: Run dashboard focused tests and static checks.**

### Task LAR05: evidence and freeze

**Files:**
- Modify: `.opencode/working-state.md` only if it exists at completion.
- Modify: this ledger with factual RED/GREEN and validation evidence.

- [ ] **Step 1: Run focused loader, dev assembly, analysis replay, dashboard launcher, API-sync, and boundary checks.**
- **Partial evidence:** all listed Python/static/boundary checks ran except the
  dashboard Vitest command, which could not start because this worktree has no
  dashboard dependencies. The exact limitation and successful Node static and
  negative checks are recorded below for the Lead's post-integration run.
- [x] **Step 2: Record exact commands/results, package interpreter, owned paths, scope limits, and no-Terra/no-inspection-host status.**
- [ ] **Step 3: Freeze the owned source state with the provided artifact script and wait for independent review.**

## Coverage review

LAR01 covers protected canonical config and no defaults. LAR02 covers complete Core graph, authorization/provider lifecycle, pre-reset validation, S3 pair, and loopback. LAR03 covers the required honest persisted blocker and restart/replay without claiming numeric fresh-upload results. LAR04 covers OIDC explicit opt-in only and usable local documentation. LAR05 records exact evidence for independent review. No task changes production, publicly exposes a listener, alters API/MCP schema, creates authority, or performs field/HIL acceptance.

## Implementation evidence (2026-09-22)

- **RED:** before creation, `tests/contract/test_local_analysis_runtime_config.py`
  failed collection because `ksi_core.composition.local_analysis_runtime_config`
  did not exist. Before dev wiring, six focused cases failed because
  `build_dev_app` had no `external_analysis_local_graph` argument. Before
  launcher wiring, an equivalent Node assertion reported all five forwarded
  values absent.
- **GREEN:** with the isolated
  `/tmp/ksi-analysis-mcp-20260922/.mcp-venv/bin/python` and the task
  `run_source.py`, the loader/dev suite passed
  `31 passed in 12.47s`; existing Analysis HTTP/replay tests passed
  `13 passed in 6.72s`; execution/worker-loop regressions passed
  `20 passed in 14.21s`. `ruff check`, `mypy`, `compileall`, and
  `tools/check_core_module_boundaries.py` passed. The latter required one
  additive Core composition inventory record.
- **Independent process evidence:** the Lead-owned
  `.opencode/artifacts/analysis-local-runtime-20260922/http-probe-run.log`
  records two actual `run_core_dev.py` boots with real S3 registration of
  two orthophoto+DSM exports. The same record/evidence and same-key
  `analysisId` survived restart:
  `http-restart-proof.json` reports `sameResult=true`,
  `sameEvidence=true`, two sealed revisions, and
  `numericCompletion=false`. The persisted response is the existing honest
  missing-inspection admission blocker, not a fabricated worker result.
- **Review remediation:** the v1 independent source review found that the
  loader accepted a regular descriptor after its initial metadata check without
  proving a stable byte count and post-read metadata. A deterministic same-owner
  in-place replacement regression first failed because the loader returned the
  original graph (`DID NOT RAISE`). The loader now requires a nonzero bounded
  initial `st_size`, exactly that many bytes at EOF, and unchanged
  size/mtime/ctime/mode/uid/gid/link-count after reading. The new focused test
  passed (`13 passed in 0.34s`). This invalidates v1; v2 is the review target.
- **Not run locally:** dashboard Vitest could not start because this assigned
  worktree has no `apps/dashboard/node_modules` (`vitest: not found`).
  `node --check` and two direct negative invocations passed: incomplete
  five-input forwarding and a relative protected config path both fail before
  local stack startup. The reused MCP venv also cannot make the unchanged
  production closure provenance test meaningful because its child process
  drops `PYTHONPATH` and imports editable packages from the old MCP
  worktree; its two `in_repo > 0` assertions failed while the actual
  Core/worker closure and forbidden/dev-token checks passed. These are
  environment limitations, not pass evidence.


## Main integration and bounded acceptance (2026-09-22)

- Independent v2 source review passed after the stable-read correction.
  The Lead applied exactly nine frozen paths with the guarded apply script;
  all inherited baseline files outside this delta, including foreign WIP,
  retained their hashes. No commit, push, deployment, or product-slice closure.
- Main command: `.venv/bin/python -m pytest -q
  tests/contract/test_local_analysis_runtime_config.py
  tests/contract/test_dev_assembly.py
  tests/contract/test_external_analysis_http_integration.py
  tests/replay/test_external_analysis_api_replay.py
  tests/contract/test_external_analysis_execution_integration.py
  tests/contract/test_external_analysis_worker_loop.py
  tests/contract/test_api_contract_sync.py
  tests/contract/test_production_profile_gate.py`:
  **110 passed in 72.89s**. This closes the two earlier interpreter-provenance
  failures using the actual main environment; no production gate was weakened.
- Dashboard: `npm test -- test/local-oidc-stack.test.ts`, **2 passed**.
  Core module-boundary checker: **149 inventory records**, PASS.
  `git diff --check`: PASS. The earlier worktree-only Vitest limitation is resolved.
- Final real-process probe explicitly selected main using `KSI_PX_SOURCE`.
  `main-probe-manifest.json` froze source/harness hashes before execution.
  A fresh private Core data directory and fresh owned S3 bucket were used.
  Two actual CLI boots passed; both orthophoto/DSM revisions were uploaded
  and sealed through HTTP. Full result, evidence and sealed revision responses
  match exactly after restart; a same-key retry retains the Analysis ID.
- The result remains `NOT_STARTED` / `BLOCKED` with
  `ESSENTIAL_INPUT_UNAVAILABLE` and null numeric result. This is evidence of
  durable admission handling, not numeric completion or accuracy acceptance.
- Independent evidence review: **ACCEPTED for this bounded final-main local
  runtime claim only**. Artifacts are under
  `.opencode/artifacts/analysis-local-runtime-20260922/`:
  `review-v2.md`, `applied-v2.json`, `main-verification.json`,
  `main-probe-manifest.json`, `http-created.json`, `http-restarted.json`,
  `http-probe-run.log`, `px-evidence-review.md`, and `cleanup.json`.
- The owned temporary MinIO container and S3 credential file were removed.
  Other running services were untouched. This factual ledger append follows
  the frozen source review and verification; executable source is unchanged.

**Remaining boundary:** actual supported artifact-inspection host and worker
integration is needed before claiming a fresh-upload numeric result. Terra
samples remain unavailable. Actual user/OIDC browser operation, remote CI,
deployment, Tailscale, HIL and field accuracy are not accepted by this slice.
The EXT-VAL product slice and Human end-to-end acceptance remain open.
