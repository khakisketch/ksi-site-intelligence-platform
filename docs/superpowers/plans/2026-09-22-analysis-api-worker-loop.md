# Analysis API and local worker-loop implementation plan

> **For agentic workers:** Execute one checked task at a time with `superpowers:executing-plans`; write and observe the focused failing test before its implementation. This packet has one source writer and requires independent review after the writer is idle. Do not commit, deploy, alter credentials, or activate production configuration.

**Plan ID:** AX-20260922

**Current status (2026-09-22):** Local software implementation and independent integration review passed; 46 reviewed paths applied to main with inherited WIP preserved. See final integration record below. The original task checklists remain the historical execution specification, not a current backlog. Product slice/Human acceptance, Terra compatibility and production activation remain open separate gates.

**Goal:** Expose one authenticated Site + WorkArea-scoped analysis request, poll, result, and evidence API that composes the completed AP/NX Core records with an opt-in local worker loop that performs the real fixed-profile calculation.

**Architecture:** The facade freezes two externally submitted revision selectors into an append-only intent before resolving their sealed subjects and delegating admission to AP and execution to NX. It owns no policy, profile, runtime, accuracy, or numeric decision. Core mounts the public and worker-only routes only when an explicitly injected AP/NX local graph is complete; the separate Processing Controller client/runner leases the exact job, consumes short-lived object capabilities through `ExternalObjectHttpByteSource`, invokes the existing real measurement callable, and reports its sealed result or failure.

**Tech stack:** Python 3.12, FastAPI/Pydantic v2, existing `DurableJournal`, AP/NX V2 contracts, `httpx`, Rasterio/GDAL, NumPy, PyProj, pytest.

**Spec:** `docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md`; `docs/architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md`; `docs/design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md`; AP-20260920 and NX-20260921 ledgers.

## Required implementation record

- **Requirement IDs:** ADR-KSI-036 D1–D6; ADR-KSI-037 D3–D4 and INV-061; first-request contract request, execution, result/evidence, retrieval, currentness, and acceptance sections; REQ-INT-101/102/104 and REQ-SEC-101.
- **Invariants enforced:** INV-017/053 by AP admission/currentness and typed blockers; INV-020 by AP/NX identity-bound CRS/vertical/unit/transform facts; INV-024 by `PROVISIONAL_ACCURACY_UNVERIFIED` plus `uncertaintyM3: null`; INV-040 by the real callable and no test/dev production fallback; INV-051/060 by sealed submitted-derived artifact and provenance references; INV-054/055 by Core-selected sealed AP/NX runtime/resource facts. The facade never treats a completed worker run as a reviewed, issued, accurate, survey, settlement, or field-accepted result.
- **Owner modules:** durable facade/API and composition in `services/core`; authenticated loop client/runner in `services/processing-controller`; API wire schema in `contracts/schemas`; focused contract/replay tests. This writer excludes UI source; AX05 carries the overall UI acceptance as a separate-owner successor, and MCP remains deferred.
- **Contracts affected:** additive API schema, shared worker transport models in `packages/event-contracts`, and explicit paths/components in `contracts/api/openapi-core.yaml`. AP/NX V2 contracts stay byte-compatible; existing V1 relative-volume routes, UDS protocol, manifest, launcher, and container protocol remain untouched.
- **Reference assets/adoption:** reuse AP `AnalysisAssessmentRequestV2`/`ExternalRelativeVolumeAnalysisStore`, NX `ExternalRelativeVolumeCalculationStore`, `ExternalObjectHttpByteSource`, and `measure_external_relative_volume_v2`. Do not import `references/` or reuse V1 execution protocol code.
- **HIL/data/license assumptions:** synthetic GeoTIFFs plus loopback object HTTP prove local software only. No Terra export support, vendor integration, field/device/HIL, RTK/GCP/absolute accuracy, customer data, new dependency, or production runtime provenance is claimed.
- **Rollback:** leave intent/AP/NX journal evidence immutable. A later change can stop injecting the opt-in local graph/routes; existing V1 behavior and historic records remain readable.

## Proposed contract freeze

`POST /v1/sites/{siteId}/work-areas/{workAreaId}/analyses` requires `Idempotency-Key` and accepts exactly:

```json
{
  "baseline": {"workOrderId": "wo-t0", "submissionRef": "sub-t0", "revision": 1},
  "current": {"workOrderId": "wo-t1", "submissionRef": "sub-t1", "revision": 1}
}
```

`GET /v1/sites/{siteId}/analysis-observations` is a read-only, tenant/site-scoped selector resolver. Each option exposes the three selector fields plus `observationEpochId`, capture interval, and only the submission/revision facts already visible to that principal; it neither assesses nor creates a record. Core resolves POST selectors under the authenticated organization and path Site/WorkArea into sealed subjects; callers cannot provide subjects, artifact IDs, profile/runtime/resource/algorithm digests, thresholds, accuracy assertions, evidence verdicts, or object URLs. The intent journal is required because AP takes already-resolved subjects and blocked AP records have no calculation identity: it seals the public selector digest, path scope, organization, idempotency digest, `analysisId`, and AP/NX record references. It also bridges crash-recoverable AP→NX issuance with the public request identity. It records a pre-admission block as durable history, so a restart or matching retry returns the same frozen intent; a reused idempotency key with different scope/selectors returns a conflict.

The explicit public route set is `GET /v1/sites/{siteId}/analysis-observations`; `POST /v1/sites/{siteId}/work-areas/{workAreaId}/analyses`; `GET /v1/sites/{siteId}/analyses`; `GET /v1/sites/{siteId}/analyses/{analysisId}`; `GET /v1/sites/{siteId}/analyses/{analysisId}/result`; and `GET /v1/sites/{siteId}/analyses/{analysisId}/evidence`. The POST response, list, detail, and result use one DTO. It contains `analysisId`, frozen selectors, `executionState` (`NOT_STARTED|QUEUED|RUNNING|COMPLETED|FAILED`), `suitabilityState` (`BLOCKED|REMEDIATION_REQUIRED|PROVISIONAL_ACCURACY_UNVERIFIED|EVALUATED|REASSESSMENT_REQUIRED`), `blockers[]`, AP/NX record IDs/digests, and scoped `evidenceRefs[]` with resolvable Core links. A blocker is `{code, epoch?, evidenceRef?, detail?}`; codes preserve AP/NX typed causes such as `WORK_AREA_UNAVAILABLE`, `EPOCH_SITE_MISMATCH`, `EVIDENCE_CONTEXT_UNAVAILABLE`, `CHECKPOINT_EVIDENCE_PENDING`, and the explicit epoch-resolution codes added for missing/incompatible CRS, vertical reference/unit, inspection, or DSM. `result` is present only for a current completed AP/NX report and includes the sealed metrics, coverage, limits, and evidence links; it never replaces unavailable area with zero. The detail/result/evidence GETs perform no assessment, reassessment, append, or implicit retry. A stale fact returns `REASSESSMENT_REQUIRED` with numbers withheld; a new idempotency key is the only path that records a new AP assessment.

Worker-only routes require a `PROCESSING_WORKER` principal with `PROCESSING_WORK`: list pending, lease, input, renew, report, and failure. Input contains only an active exact lease plus short-lived Core-issued byte capabilities for the two sealed DSMs; it never exposes a capability on public routes. The runner requires explicit injected worker executable/build/runtime-image/lock facts and rejects a Core identity mismatch. These inputs are local configuration assertions, not a signed-runtime or production-release proof.

## Tasks

### AX01: Durable facade intent and canonical public DTO

**Files:**
- Create: `services/core/src/ksi_core/domains/external/quantity/external_analysis_intents.py`
- Create: `services/core/src/ksi_core/domains/external/quantity/external_analysis_api.py`
- Create: `contracts/schemas/analysis-api.v1.json`
- Modify: `contracts/api/openapi-core.yaml`
- Create: `tests/contract/test_external_analysis_api.py`
- Modify: `services/core/src/ksi_core/domains/external/quantity/external_relative_volume_analysis.py` only for principal-scoped, presentation-only latest-record lookup required by the facade.
- Modify: `services/core/src/ksi_core/domains/external/quantity/external_relative_volume_calculations.py` only for organization-scoped pending/list lookup required by a worker route.

**Interfaces:** `AnalysisIntentStore.create_or_resume(principal, site_id, work_area_id, selectors, idempotency_key, now)` resolves sealed subjects, calls AP assessment then NX issue, and returns an immutable `AnalysisViewV1`. It uses `analysisId` as the stable internal AP/NX request reference, so recovery can reconcile (a) intent appended before AP, (b) AP appended before NX, and (c) NX appended before the intent link. Existing matching intent retries return its current projection without calling AP again. `AnalysisViewV1` is the exact public DTO defined above; `AnalysisResultV1` adds numeric data only after NX current retrieval succeeds.

- [ ] Write failing API/real-store tests for read-only observation options, valid selector freeze and `202 QUEUED`, exact idempotent retry after journal reconstruction, changed-selector idempotency conflict, organization/site denial, a missing vertical/inspection/DSM blocker recorded as `NOT_STARTED + BLOCKED`, no numeric result after reassessment, and a current completed provisional/evaluated result with scoped evidence links. Verify a `SITES_READ` caller can poll without the facade fabricating a principal or borrowing `SITES_WRITE`; stale facts return `REASSESSMENT_REQUIRED` without appending, and only a new key may reassess. Simulate recovery across each intent/AP/NX append gap and prove it resumes only the same frozen selectors and never creates a second job.
- [ ] Run: `PYTHONDONTWRITEBYTECODE=1 /home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform/.venv/bin/python /home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform/.opencode/artifacts/analysis-api-20260922/run_worktree.py pytest -p no:cacheprovider -q tests/contract/test_external_analysis_api.py` — expect RED because the facade modules/routes are absent.
- [ ] Implement the append-only intent/replay/idempotency projection and the narrow AP/NX lookup seams. Map existing AP/NX facts only; do not add policy or re-evaluate evidence in the facade. Reject extra create fields and return the same DTO for create, list, poll, result, and evidence retrieval.
- [ ] Add JSON-schema parity and static OpenAPI assertions for all six public routes, the required header, closed create body, two independent states, structured blockers, result/evidence links, and omission of worker URLs from the public schema.
- [ ] Re-run the command above plus `tests/contract/test_external_relative_volume_analysis_contract.py tests/contract/test_external_relative_volume_calculation_contract.py tests/contract/test_external_analysis_execution_integration.py`; expect GREEN.

### AX02: Opt-in Core composition and authenticated worker API

**Files:**
- Create: `services/core/src/ksi_core/domains/external/quantity/external_analysis_worker_api.py`
- Create: `packages/event-contracts/src/ksi_event_contracts/external_analysis_worker.py`
- Create: `contracts/schemas/external-analysis-worker.v1.json`
- Modify: `services/core/src/ksi_core/composition/external_graph.py`
- Modify: `services/core/src/ksi_core/composition/assembly.py`
- Modify: `services/core/src/ksi_core/composition/app_factory.py`
- Modify: `services/core/src/ksi_core/composition/routes/external.py`
- Modify: `docs/audit/CORE_R1_MODULE_MIGRATION.json`
- Create: `tests/contract/test_external_analysis_worker_api.py`
- Modify: `tests/contract/test_api_contract_sync.py` for the mounted OpenAPI/public-route allowlist only.

**Interfaces:** `ksi_event_contracts.external_analysis_worker` owns strict request/response wire models for the six worker operations, so Processing Controller imports no Core implementation model. `build_external_analysis_worker_router(intents, calculations, capability_issuer)` provides authenticated `GET /v1/internal/analysis-jobs`, `POST /{analysisId}:lease`, `GET /{analysisId}/input`, `POST /{analysisId}:renew`, `POST /{analysisId}:report`, and `POST /{analysisId}:failure`. `ExternalAnalysisGraph` is injected only when AP, NX, a shared coordinator, trusted runtime identity, a sealed resource envelope, evidence storage, and an object-capability issuer are supplied by the common/dev assembly.

- [ ] Write failing route tests that authenticate a worker, obtain one exact fence and two capability-bound byte inputs, reject expired/stale/cross-tenant fences and non-worker principals, and prove public callers cannot see internal paths or capability URLs.
- [ ] Run the AX01 launcher command with `tests/contract/test_external_analysis_worker_api.py tests/contract/test_api_contract_sync.py`; expect RED because the route/graph is absent.
- [ ] Implement opt-in graph construction, exact dependency/coordinator identity checks, scoped capability issuance, and worker routes that delegate directly to NX. Leave `composition/production.py`, production environment parsing, deployment files, and all V1 mounts unchanged; missing injected local graph means no Analysis API routes.
- [ ] Re-run the focused tests and prove the existing V1 relative-volume OpenAPI/protocol tests remain green.

### AX03: Processing Controller authenticated client and real run-once/poll loop

**Files:**
- Create: `services/processing-controller/src/ksi_processing_controller/external_analysis_core_client.py`
- Create: `services/processing-controller/src/ksi_processing_controller/external_analysis_worker.py`
- Create: `services/processing-controller/src/ksi_processing_controller/external_analysis_runner.py`
- Modify: `services/processing-controller/pyproject.toml` to add an explicit local-only console script.
- Create: `tests/contract/test_external_analysis_worker_loop.py`

**Interfaces:** `ExternalAnalysisCoreClient` performs only the six authenticated worker operations. `run_once(client, runtime_identity, transport_policy, now)` lists, leases, retrieves bounded inputs, renews during byte reads/measurement, runs `measure_external_relative_volume_v2`, then reports the sealed report or typed failure; `poll()` repeats run-once without concurrency. `main()` requires explicit Core URL, worker token/identity, runtime/build evidence, and static transport allow-list; absent values are configuration errors.

- [ ] Write a failing loopback integration test using a real Core test app, real authenticated HTTP client, two real 2×2 GeoTIFF byte objects served from an explicit loopback origin, and the existing `ExternalObjectHttpByteSource`. Assert `QUEUED → RUNNING → COMPLETED`, hand-checked cut/fill/net and coverage witness, report retrieval through the public API, and byte-capability expiry/worker-runtime mismatch becoming sealed failures without a numeric result.
- [ ] Run the focused loop test through the baseline22 launcher; expect RED because the client/runner is absent.
- [ ] Implement the bounded client/runner. Treat HTTP/lease/currentness/object transport/measurement faults as typed failure reports only while the fence is current; never create a mock calculation, fall back to a V1 client/protocol, or fabricate runtime evidence. The CLI is separate from existing `runner.py` and has no production default configuration.
- [ ] Re-run the loop test with `tests/contract/test_external_analysis_measurement.py tests/contract/test_external_analysis_execution_integration.py`; expect GREEN.

### AX04: Replay, compatibility, and review freeze

**Files:**
- Create: `tests/replay/test_external_analysis_api_replay.py`
- Modify: `docs/superpowers/plans/2026-09-22-analysis-api-worker-loop.md` only to record actual RED/GREEN results and freeze evidence.

- [ ] Write failing replay/race tests for an altered selector/idempotency binding, forged blocker/record reference, stale worker report after a renewed lease, duplicated report/failure, complete interior intent-journal corruption, and torn final intent record recovery. Assert durable state and public DTOs, never mocked call counts.
- [ ] Run the replay test through baseline22; expect RED for the missing intent/replay rules.
- [ ] Implement only the missing strict intent event validation and idempotent recovery checks. Preserve existing torn-tail recovery and reject complete interior corruption.
- [ ] Run the authorized focused suite through `analysis-api-20260922/run_worktree.py`: AX01/AX02/AX03 tests, AP/NX contract and integration tests, replay test, `ruff check` on changed Python files, `mypy` on changed Core/worker modules, `python tools/check_core_module_boundaries.py`, `tests/contract/test_api_contract_sync.py`, and `git diff --check`. Record exact pass/fail counts; no full suite claim unless it is actually run.
- [ ] Freeze the final changed-path hashes and baseline22 diff for independent review. Do not commit, push, merge, deploy, or claim HIL/field/production acceptance.

### AX05: UI successor after DTO freeze (separate owner/worktree)

**Ownership:** This backend writer makes no Dashboard changes. Once AX01’s static schema/OpenAPI and DTO tests are accepted, the Lead assigns a UI worker its own worktree.

**Acceptance handoff:** The Operations Console must fetch the observation options endpoint, submit the frozen selector-only POST with an idempotency key, and poll the canonical detail/result/evidence endpoints. Its blocked, reassessment, provisional, evaluated, failed, and completed displays must show the same `analysisId`, typed blockers, limitations, numbers only when returned by Core, and resolvable evidence references. A browser integration test uses an explicit local fixture app and real HTTP routes; it must not inject a production mock/fallback. MCP remains deferred.

## Plan self-review

AX01 freezes the approved selector-only contract and preserves typed AP/NX blockers without granting the facade policy or numeric authority. Its durable intent is justified by public scoped selectors, blocked resolution, and recoverable AP→NX linkage. AX02 provides a fail-closed local graph, event-contract worker boundary, and authentication boundary while preserving V1 surfaces and keeping production unconfigured. AX03 proves the required actual software loop with byte-bound GeoTIFF inputs and no fabricated runtime provenance. AX04 proves restart/replay/fence behavior and freezes only verified local evidence. AX05 carries the approved same-API UI acceptance forward under a separate writer; MCP remains deferred.

## Execution record — 2026-09-22

- **AX01/AX02 Core status:** implemented and ready for independent Core review. The public DTO/schema and six paths remain frozen; the worker wire file remains the Lead-frozen `f021ebfbaf1e7ee7adfaf2ac8275063549f1efc87c6e576997869feb76a8b96d`.
- **Durability/currentness additions:** intent replay deep-copies mutable public DTOs; AP→NX crash recovery resumes only the frozen intent; public GETs do not append. A stale AP preserves the recorded NX execution state while withholding result data. NX read-only current projection now reports `EXECUTION_DEADLINE_EXPIRED` or `EXECUTION_RETRY_EXHAUSTED` for unfinished non-runnable records; the facade maps that Core verdict to fixed public `FAILED` with a typed blocker. Completed records remain available after their execution deadline when AP is current. A linked NX record with a different AP calculation identity fails closed.
- **AX03 ownership/dependency:** Processing Controller source and its worker-loop contract test transferred to `analysis_processing_worker` in `/tmp/ksi-analysis-worker-20260922`. Core owns `test_external_analysis_http_integration.py`; it ran the frozen v1 Processing client/runner against real Core HTTP, authenticated worker routes, real loopback object HTTP, and real 2×2 GeoTIFF bytes. It verified `POST → run_once → COMPLETED`, equal detail/result/evidence payload results, worker-client restart with no pending work, and a distinct Core journal reconstruction returning the same result/evidence. The recorded v1 loop is local software evidence only. Processing review found unrelated bounded-resource fixes; final combined execution must be repeated when the next Processing freeze is supplied.
- **Static/boundary additions:** `contracts/api/openapi-core.yaml` contains the frozen public and internal worker paths/components; `contracts/schemas/external-analysis-worker.v1.json` is additive. `CORE_R1_MODULE_MIGRATION.json` now inventories the four new Core quantity modules so the module boundary check covers them.
- **Validation actually run:**
  - `run_worktree.py pytest -p no:cacheprovider -q -k 'not combined_frozen' ...analysis intents/api/api-contract/worker-api/http-integration/execution-integration` — **31 passed, 1 deselected**.
  - `run_worktree.py pytest -p no:cacheprovider -q tests/contract/test_api_contract_sync.py` — **36 passed**.
  - `run_worktree.py pytest -p no:cacheprovider -q tests/contract/test_external_relative_volume_analysis_contract.py tests/contract/test_external_relative_volume_calculation_contract.py tests/contract/test_external_analysis_execution_integration.py` — **13 passed**.
  - `run_combined_source.py pytest -p no:cacheprovider -q tests/contract/test_external_analysis_http_integration.py::test_combined_frozen_worker_completes_real_core_http_loop_over_loopback_objects` — **1 passed** against Processing v1 freeze.
  - `ruff check` on owned Core/event-contract/test files — passed; `mypy` on ten changed Core files with explicit worktree `MYPYPATH` — passed; `python tools/check_core_module_boundaries.py` — **148 records, passed**; `git diff --check` — passed.
- **Core freeze inputs:** baseline `9edc4a18e873e356f5cfea7d69437f1fb5e11acd`; public DTO source `a3d09391bfeef4f07ddd49fadfd22127b1ec6dd024b73a24721812899282c09a`; public JSON schema `0a796704d73aecd977037d0e4b6b2b74ded8103f2e924230114757b60f220cb6`; worker JSON schema `21b02659a4b24444ec50005d4a2f4575c78bae901ecef9cfb0474a2ccb541fa5`. The public DTO source received only a Ruff import-format correction after the first freeze computation; Lead compared it with the UI baseline and confirmed no public schema or semantic delta. No commit, deployment, production activation, field, HIL, or accuracy claim has been made.
- **Independent-review bundle:** a sorted `sha256sum` stream over the Core-owned OpenAPI/schema/inventory files; the two event-contract DTO files; four composition files; six quantity files; and the eight named API/fixture/contract tests has digest `555d9c8bd2d5dabffc89480abb497f2075e35e2ba75da9fb19041892c2fdaa55`. The path set is the exact Core-facing files named in AX01/AX02 plus `external_analysis_s3_capabilities.py`, `external_relative_volume_calculations.py`, `test_external_analysis_execution_integration.py`, and `test_external_analysis_http_integration.py`; it excludes all Processing Controller source.

### Core review v1 correction record — 2026-09-22

- **Reviewer corrections implemented:** active final NX retries remain pending until lease expiry/deadline; worker discovery skips expired queued work and validates the sealed AP↔NX identity before calculation-ID deduplication, so a forged prefix cannot hide a valid alias. Worker mutations retain the same identity guard. The public evidence response additively projects sealed calculation/work-area/policy/runtime facts, epoch inspection references, and recorded evaluation/fact authority; provisional result limitations contain only recorded `UNASSESSED` reason codes. Existing public fields and the scalar `authority` object remain compatible.
- **Contract/replay hardening:** static JSON Schema and OpenAPI now contain the additive evidence shapes, normal `if/then` state constraints, and the 255-character idempotency header limit. Selector inequality remains documented and enforced by DTO/HTTP runtime validation. Intent replay now requires exact integer event versions, string identity/scope primitives, and lowercase `sha256:` digests; it rejects forged/rebound links and complete interior corruption while DurableJournal alone recovers an unnewline-terminated tail. The real NX execution integration verifies stale renewed-attempt rejection and idempotent duplicate report/failure delivery.
- **Correction validation actually run:** `run_worktree.py pytest -p no:cacheprovider -q -k 'not combined_frozen_worker_completes_real_core_http_loop_over_loopback_objects'` over AX intent/API/API-contract/worker/HTTP/execution/AP-NX/replay tests — **55 passed, 1 deselected**; `run_worktree.py pytest -p no:cacheprovider -q tests/contract/test_api_contract_sync.py` — **36 passed**. `ruff check` on correction sources/tests, explicit-`MYPYPATH` `mypy` on 11 Core/event-contract modules, `python tools/check_core_module_boundaries.py` (**148 records**), and `git diff --check` passed. The excluded combined test imports Processing-only source absent from this Core worktree; Lead will run it against frozen Processing v4 in the combined integration tree.
- **Review status:** this correction state supersedes the earlier Core bundle. The sorted `sha256sum` stream over the prior Core-owned review path set plus `tests/replay/test_external_analysis_api_replay.py` is `b2b50a00e06cf6e1a406e6c9f310e56f799c0ae7f3b28cf31d3ffd1a2d69e518` at baseline `9edc4a18e873e356f5cfea7d69437f1fb5e11acd`; it excludes this ledger, checkpoint, and all Processing source. No mixed-source, production, signed-runtime, HIL, field, or accuracy claim is added.

### Core review v2 correction record — 2026-09-22

- **Discovery eligibility:** before a worker list row enters calculation-ID deduplication or consumes the page limit, Core now reads AP `latest_current_for_execution` with the sealed NX calculation identity and organization. It requires the returned current admission to equal the NX record admission and identity; it passes no fabricated principal. The existing NX lease path remains the final concurrent fence. Expired queued records remain filtered and expired RUNNING records remain discoverable for takeover only when their AP admission is still current.
- **Regression/validation:** a stale-first/runnable-second `limit=1` route test proves the stale row is omitted and that the currentness seam is called for each candidate; the existing forged-prefix/dedup and expired-RUNNING takeover cases remain green. `run_worktree.py pytest -p no:cacheprovider -q` over worker discovery, AP/NX execution currentness, and HTTP fixture tests (excluding the transferred-Processing combined test) — **11 passed, 1 deselected**. Ruff over every frozen Python path, targeted worker-router mypy, and `git diff --check` passed. The previously reported HTTP test `E501` is formatted.
- **Review status:** frozen Core path-set hash is `f853041d3a6f24e6b73b531c437372375fef2726d52eaa30dbd3f9f6a617e6e2` at baseline `9edc4a18e873e356f5cfea7d69437f1fb5e11acd`; the path set excludes this ledger/checkpoint and Processing source. Prior **55 passed, 1 deselected**, static-sync **36 passed**, mypy, and boundary evidence remain valid except where superseded above.

### Core review v3 correction record — 2026-09-22

- **Crash recovery:** a same-key POST now links an already-issued NX record when the intent-link append was interrupted. It verifies the returned calculation organization and sealed AP calculation identity before appending the one-way link; NX's valid identity-deduplicated request ID may differ from `analysisId`. GET remains read-only. The real fixture forces the exact crash, reconstructs all Core journals, verifies one AP assessment and one NX issued event, then proves the same public request links, discovers, and leases the original job. A focused facade test rejects forged organization/identity recovery before linking.
- **Equivalent alias currentness:** AP's existing execution witness now accepts an optional exact sealed admission for record-bound transitions. It preflights that admission's own immutable request and, under the shared coordinator, requires the newest same-organization/calculation-identity admission to have the same AP suitability key. Thus a second selector-identical public intent may link its one NX request and run, while a newly recorded unavailable/rejected/remediated AP fact fails closed. The default newest-record witness remains unchanged for new issuance and terminal/completed reads. NX uses exact mode for unfinished `QUEUED`/`RUNNING` discovery, lease, renew, input, report, and failure paths; `COMPLETED` public reads retain default-latest compatible-evaluation result reuse and `FAILED` remains terminal/default.
- **Focused real-fixture regressions:** two idempotency keys produce separate public IDs but one NX request; the second alias leases, reads inputs, and renews. A foreign organization or forged sealed admission has no exact witness. A revoked evidence context records an inequivalent third AP admission, rejects discovery/renewal, and remains rejected after the mutable context is restored until a fresh equivalent AP admission is appended; that fresh record restores renewal. The v4 combined worker test adds queued aliases, a post-completion compatible alias with no second worker run, and Core replay checks for all alias result projections.
- **Validation actually run:**
  - `run_worktree.py pytest -p no:cacheprovider -q` over intent/API/API-contract/worker/HTTP (excluding transferred-Processing combined), execution integration, AP/NX contracts, and replay — **59 passed, 1 deselected** (one existing TestClient deprecation warning).
  - `run_combined_source.py pytest -p no:cacheprovider -q tests/contract/test_external_analysis_http_integration.py::test_combined_frozen_worker_completes_real_core_http_loop_over_loopback_objects` — **1 passed** against frozen Processing v4: real authenticated Core HTTP, loopback object bytes, GeoTIFF measurement, aliases, worker restart, and Core journal replay.
  - `run_worktree.py pytest -p no:cacheprovider -q tests/contract/test_api_contract_sync.py` — **36 passed** (one existing TestClient deprecation warning). `ruff check` on changed Core/test paths, explicit-`MYPYPATH` `mypy` on the four changed Core modules, and `git diff --check` passed.
- **Review status:** baseline remains `9edc4a18e873e356f5cfea7d69437f1fb5e11acd`. The sorted `sha256sum` stream over the same Core review path set used for v2 is `7b5d22a5b2c77f157ec57dc99490662271ebff52e367cb7c63f2ab445ec5c217`; it excludes this ledger, checkpoint, and all Processing source. No public DTO/wire/schema path changed, no production configuration was activated, and no signed-runtime, HIL, field, or accuracy claim is added.

### Final Lead integration and main verification — 2026-09-22

- **Authoritative current record:** this main-checkout ledger now owns AX-20260922 resumption. Isolated worktree copies and earlier packet labels are historical evidence; `.opencode/working-state.md` points here. No product-state reprioritization or slice closure occurred.
- **Reviewed implementation:** Core `review-freeze-v4.json` (26 paths), UI `ui-freeze-v8.json` (13 paths), Processing `processing-freeze-v4.json` (7 paths), all independent PASS. Combined `integration-freeze-v2.json` covers 46 paths; patch SHA-256 `e96f19a5120fc8969f558c7e6635b4fee2514aff4ba459e7d14a40dae4e29952`. `integration-review-v2.md` independently closes crash recovery, equivalent duplicate authority and repeated polling findings; 37 Python and 43 UI checks passed. No open review finding remains for this frozen delta.
- **Lead combined verification:** 125 Python checks passed (one existing TestClient deprecation warning); 41 focused UI checks passed. The final browser used real Core HTTP, real synthetic GeoTIFF objects and a separately launched Processing CLI. It observed five successful QUEUED responses, then completion before any reload, equal API/result/evidence data, and zero page errors. Desktop/mobile captures and browser result are retained in the ignored artifact directory. Synthetic EVALUATED data, cut/fill 0.01 m³ and net 0, establish software behavior only.
- **Main application:** guarded copy applied only the reviewed 46 paths after all component and integration reviews passed. All 2,100 baseline hashes were checked before copy; unrelated inherited files, including foreign dashboard tsconfig and A2H ledger WIP, remain unchanged. On main, real HTTP/worker/currentness/restart/replay checks passed **22 tests**, and the UI suite passed **41 tests**. Frozen implementation hashes were rechecked after tests. This final factual ledger update is the only post-freeze content change.
- **Evidence location:** `.opencode/artifacts/analysis-api-20260922/`: `main-applied-v2.json`, `integration-python-v2.log`, `main-python-v2.log`, `integration-review-v2.md`, `browser-parity-result.json`, and component reviews/manifests. Artifacts are local/ignored; this durable ledger records their scoped results without treating local evidence as deployed or customer acceptance.
- **Remaining separate gates:** Terra actual DSM export metadata and two-epoch registration validation; customer/metrology acceptance; signed production runtime/deployment activation; MCP adapter after this API path. Existing V1 APIs remain. No commit, push, PR, merge, deployment, credential/device action or native goal was performed. All test-owned browser/Core/worker servers were stopped.
