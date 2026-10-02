# Integration Readiness Repairs Implementation Plan

> **For agentic workers:** Use executing-plans inline, TDD per task, one independent final review. Preserve the original main/recovery/candidate; no concurrent product writers.

**Goal:** Repair IR01–05/IR08 from the approved readiness review and establish a verified local integration branch, without discarding existing WIP or claiming release acceptance.
**Architecture:** This independent worktree starts at main9edc4a1 plus an exact hash-verified copy of all314 main WIP paths. Core still owns rights/currentness; publication tooling owns self-contained schemas; test-helper packaging and compiler inputs are explicit. No default data activation, data/model migration, or new product feature.
**Tech Stack:** Python3.12, Pydantic2, pytest/mypy/Ruff; existing Dashboard TypeScript/Next/Vitest toolchain.
**Spec:** `2026-10-02-main-integration-review.md` required-follow-up and proposed sequence, `../specs/2026-09-30-spatial-data-delivery-v1-design.md`. User subsequently authorized improvements (“그렇게 개선해줘~”).

## Global Constraints
- Main314working paths/index/HEAD and old recovery/candidate evidence remain unchanged while engineering proceeds here. No branch/worktree deletion, reset, fetch, push, deployment, credential/host provisioning, or installation.
- Native DSM/ORTHO rectangles only; immutable source/grant/receipt/journal semantics and default-closed production unchanged. No authority widening or raw/managed substitution.
- EXT-VAL is not closed. Known private-bus failure and absent official samples/host/provider/customer evidence must be reported, never replaced with fake proof or skipped to claim green.
- Reuse prepared dependencies in a local no-install interpreter with candidate-first paths; verify imported source locations. Generated/ignored evidence remains private and excluded from commits.
- Do not sweep stylistic reformatting, historical A2H UI or managed2fixes into these repairs. Main promotion needs a safe dirty-WIP reconciliation decision, not automatic checkout/reset.

## Implementation contract
Requirement IDs: IR01, IR02, IR03, IR04, IR05, IR08; SDP-DATA-01 / SDP-REQ-01/02/03/05/06/07/08.
Owner module: Core delivery, event contracts/publication tooling, test support, Dashboard compiler configuration.
Acceptance criteria: all original symptoms fail first and pass after; other403/404 ineligible jobs cannot suppress eligible jobs;503/currentness/integrity still closes poll; schema references are self-contained; OpenAPI duplicate keys rejected in tests; real broad CI type gate finishes without new blanket suppression; generated Next test types cannot accumulate in the product tsconfig; original source preserved.
Contracts affected: no wire value/state schema change; fix published Analysis worker `$ref` locations/OpenAPI duplicate serialization only.
Reference assets: existing tests/source generators and prior exact reproductions; no references repository edits/imports.
Adoption decisions: use existing owner APIs; normalize new SpatialData helper imports, local checked affine API stub if needed (no install/no ignore); keep existing approved UI.
Files to change: storage_s3.py/jobs.py; owner contract tests; worker schema/OpenAPI/publication tool; SpatialData test-helper imports and package markers; narrow affine typing surface; Dashboard tsconfig/e2e harness and config regression tests.
Tests: storage/jobs/replay/currentness/HTTP; schema/OpenAPI conformance; broad mypy/Ruff/pytest; Dashboardunit/type/lint and isolated build/browser gates where prepared.
HIL or real-device assumptions: none; hardware/host/namespace/provider/customer gates stay unverified.
License/data implications: synthetic fixtures only; no downloaded sample, training, customer data or external delivery.
Rollback: local task-owned inverse changes or disable data lane; retain journals/evidence and original main WIP. Never reset shared files.
Invariants: INV020/024/051/053 remain untouched semantics; INV040 defaultclosed tested; INV050/060 preserved by exact scoped key and current-grant/worker checks; INV054/055 no activation/policy widening; INV043/061 no additional data/AI egress.

## Review Focus
- Dot/path/percent/slash organization key variants must not allow arbitrary storage keys.
- Mixed revoked and healthy jobs must not mask lane503 or immutable integrity faults; history/replay stay intact.
- Nonempty schema responses force nested reference traversal; empty-list/check_schema alone is insufficient.
- Test-fixture aliases and local dependency typing cannot make CI silently inspect different source files or hide errors.
- Next generated type paths must stay run-local; build/type checks cannot mutate product configuration or rely on stale test directories.

## Task 1: Scoped data keys and independent eligible polling
Files: `services/core/.../delivery/{storage_s3,jobs}.py`; `tests/contract/test_spatial_data_{storage,jobs}.py`.
Interfaces: consumes `Principal`, server-generated job key and existing `_current(record,now)`; produces same `_owned_key`/`pending` signatures and journal/history model.
- [x] Add dotted organization operation-matrix tests and strict invalid-key negative cases; real mixed revoked/healthy journal test plus fail-closed503 control.
- [x] Run targeted new tests: expect503/403 failures, not import errors.
- [x] Align organization key charset with actual safe identifier/encoding; skip only explicit per-record403/404 ineligibility in pending, never lane/unknown503/integrity.
- [x] Run full storage/jobs/currentness/workerAPI/replay gate; 242 passed. Commit deferred to coherent Task5 baseline.

## Task 2: Self-contained contract publication
Files: `contracts/schemas/external-analysis-worker.v1.json`, `contracts/api/openapi-core.yaml`, `tools/generate_analysis_worker_schema.py`, `tests/contract/test_contract_publication_integrity.py`.
Interfaces: consumes actual Analysis worker DTO models; produces standalone `$defs` schema with `#/$defs/...` refs; existing OpenAPI models/paths/values unchanged.
- [x] Add a valid nonempty pending-response validation and all-local-ref traversal; strict duplicate-YAML test.
- [x] Run new tests: expect `PointerToNowhere` and duplicate-key rejection.
- [x] Generate worker schema with explicit local ref template; remove only byte/value-identical duplicate component entries (refuse conflicting values).
- [x] Run publication/Analysisworker/contractsync/hostile gates and generator `--check`: 77 passed; retain both runtime lanes.

## Task 3: Real aggregate type gate
Files: SpatialData test/helper import sites, `tests/conftest.py`, narrow affine typing declaration/config; owner type tests if needed.
Interfaces: consumes existing pytest-root support and actual affine2.4API; produces the established flat helper identity and checked local typing surface (see approved ruling below).
- [x] Capture actual CI-style mypy RED and import inventory; AST regression rejects conflicting SpatialData helper namespaces.
- [x] Normalize SpatialData helper/test imports to existing flat convention and explicit replay-only helper path; no package-marker migration.
- [x] Provide minimal accurate local affine stub; verify consumed constructor/coefficient subset at runtime, no import ignores.
- [x] Run broad mypy and full authorized type cleanup: 956 sources clean, no new blanket suppression or test exclusion.
- [x] Run full collection, owner/replay tests and Ruff; replay-only277p4skip and full8154p/1 inherited host failure, no duplicate/missing helper regression.

## Task 4: Stable Dashboard compiler scope
Files: `apps/dashboard/tsconfig.json`, analysis e2e config/harness, `apps/dashboard/test/*` config regression.
Interfaces: consumes existing Next/Vitest/Playwright harness; produces durable product include/exclude plus per-run temporary tsconfig so framework mutations do not touch product config.
- [x] Add config regression: no run-ID include paths, generated test output excluded, e2e selects run-local compiler config.
- [x] Watch2config assertionsRED; inspect installed Next docs/writer and validate actual writer behavior.
- [x] Keep durable approved includes; isolate current-run types without deleting old artifacts;4compiler tests pass.
- [x] Run965Dashboardunit tests/tsc/ESLint; webpack build and5real browser scenarios passed before final review fixes; final I1/I2 browser/build recheck recorded below. Turbopack/clean-install remains unverified.

## Task 5: Verify and record committed integration candidate
- [x] Audit exact task diff versus main314 snapshot; preserve all other files/ref heads except newly created integration branch.
- [x] Run actual broad PythonCI/static/scoped/full and Dashboard gates; distinguish1knowninherited host failure and unverified clean-install/Turbopack from new regressions.
- [ ] Commit coherent local sets: governance/archive snapshot separately, coupled accumulated runtime/contracts/tests plus verified repairs together if splitting would produce invalid intermediate trees. Exclude ignored checkpoint/artifacts and sensitive/generated files; inspect exact index.
- [x] Dispatch one independent read-only final review of baseline+repair delta;2ImportantRED→GREEN, noCritical, minor dispositions below.
- [ ] Finish without advancing dirty main unless safe explicit reconciliation is established. Record verified commit/evidence, remaining blockers and next decision, no next feature/slice or native goal inferred.

## Pre-flight and rulings
- Shared interface1: Task1 produces unchanged key/pending API; Tasks2/3 consume unchanged contract/test identities. No wire incompatibility required.
- Shared interface2: Task3 canonicalizes tests; Task1/2 test imports must use canonical form from the outset.
- Shared interface3: Task4 must isolate compiler config before Task5 build/browser checks to avoid regenerating the reviewed tsconfig defect.
- Ruling: execute the already approved repair sequence inline, not ask for another plan approval — no new scope/design decisions; cost if wrong: repair/task boundary can be reviewed before main promotion.
- Ruling: create a new preserved integration worktree rather than alter the frozen candidate/recovery — original evidence remains exact; cost: additional local disk/metadata, retained not pruned.
- Ruling: old managed2fixes/older UI and scale/visual redesign debt remain separate, not automatic adoption — cost: retained managed issues and UI evidence gates still open.
- Follow-up Human decision: after unblocking mypy exposed685errors/55files, Human explicitly chose full type-debt cleanup, not a narrow repair claiming CI green. Most errors are test annotation/dynamic JSON/Optional facts;5are in catalog product types. No blanket-ignore/test exclusion authorized.
- Ruling: Task3 uses established flat test-helper convention (not package markers) to avoid unrelated legacy namespace migration; pytest root explicitly inserts contract helper path so replay-only runs also resolve. Cost: test-only path setup remains necessary.
- Task4/T5 browser finding: actual Core returns completed/reassessment-required with no current
  result, but list refresh leaves the prior detail and evidence cache displayed. This blocks the
  agreed browser parity gate (ADR-KSI-037 D3/D4/D5, first-request contract acceptance).
  Requirement IDs: IR05 verification / existing Analysis current-suitability parity.
  Owner module: Dashboard AnalysisRequestPanel; acceptance: focus/terminal refresh hides superseded
  numeric detail/evidence immediately and fetches current selected detail, including failed fetch.
  Contracts affected: none. Reference assets: existing V2 panel/Core browser test (REFERENCE_ONLY).
  Adoption decisions: retain approved UI/layout, repair cached-state synchronization only.
  Files to change: AnalysisRequestPanel.tsx and analysis-request-panel.test.tsx.
  Tests: focused RED→GREEN, full Dashboard unit/type/lint/build and actual OIDC/Core/worker browser.
  Invariants: INV024 accuracy honesty, INV040 no fallback numbers, INV060 existing scope preserved;
  enforced by removing contradicted cached projection and fetching via existing authenticated BFF.
  HIL/real-device assumptions: none. License/data: existing synthetic fixtures only.
  Rollback: task-owned inverse patch; no journal/calculation mutation or new screen/design.

## Final independent review and disposition

- One read-only aggregate review checked the326-path candidate and77-path repair delta against
  the approved plan/spec. No Critical finding;2Important cache paths and5Minor observations.
  It reviewed the large carried OpenAPI change structurally, not every line, and performed only
  bounded independent schema/key/config checks; it did not rerun the complete suites or inspect images.
- I1: cached terminal detail remained visible during selection-triggered refetch. New unit case
  watchedRED→GREEN. Selecting a cached item now retires its detail before I/O; fresh validated POST
  detail is retained. Selected cards without current detail do not fall back to old summary numbers.
- I2: unsuccessful current-detail refetch retained prior numbers/evidence. New unit case
  watchedRED→GREEN. Only the still-selected exact generation retires detail/evidence and keeps the
  error/retry surface; pending evidence is fenced/aborted to prevent asynchronous resurrection.
- Final review fix-pass gate:965Dashboard tests/127files, nonincremental tsc and ESLint pass;
  post-review webpackbuild and all5actualbrowser scenarios also pass; mypy956sources and Ruff pass.
  Python sources did not change in this UI-only fix pass; the audited
  guarded full run remains8154passed/1inherited failure/121skipped/98warnings (766.48s), not green CI.
- Minor deferred M1: evidence-load start may clear an unrelated list/detail error; no numeric
  integrity impact. M2: same-user TOCTOU around reused test-only compiler file; uid/mode/symlink
  checks remain, but this is not a hardened runtime authority boundary.
- Minor no-change M3/M4/M5: exact per-record403/404 omission set is deliberately fail-closed;
  affine stub deliberately exposes only verified consumed operations; worker bundle root remains
  `additionalProperties:false` and pending bodies validate through their endpoint `$defs` model.
- Ruling: declined release/acceptance, field/HIL/provider/license/customer and remote CI judgment
  remain explicit unverified gates — local software evidence cannot close them; cost: no release claim.
- Ruling: declined dirty-main reconciliation/merge judgment is resolved by retaining main314WIP
  unchanged — no local main promotion or cleanup; cost: candidate is committed separately only.
- Ruling: commit coupled accumulated source/contracts/tests/governance as one coherent snapshot,
  not broken intermediate commits — current documentation names contracts/routes absent at old HEAD;
  original314-path provenance and77repairdelta audit distinguish carried work from repairs.
  Cost: larger atomic baseline rather than narrow cherry-pickable history.
- Ruling: declined Turbopack/clean-install judgment stays unverified; supported webpack is used only
  for prepared-environment verification — cost: cannot claim default clean-checkout Next CI passed.
- Ruling: declined throughput/quota/SLA/performance judgment remains outside this task; no product
  value changes or numeric operational promises — cost: no load/scale readiness claim.
- Ruling: declined V1/V2semantic parity is bounded by existing contract/conformance tests and actual
  browser shared-state checks, not a claim that different wire shapes are equal; cost: full legacy
  client compatibility remains separately testable.

## Verified evidence boundaries

- Existing `test_synthetic_staging_contract.py` invokes `uv run` internally; during the first full
  run it unexpectedly synchronized this candidate's local `.venv`. Therefore the intended no-install
  method did not hold for the entire task. No external delivery/host setup or original-main mutation
  occurred. Subsequent commands explicitly set UV_NO_SYNC/offline/no-Python-download guards.
- Actual first fullrun result was8134passed/15failed/127skipped. Fourteen
  candidate setup failures (prepared SDK sample, module symlink Git probe and bwrap dependency
  availability) were resolved only in ignored candidate inputs. Recheck77passed/1knownfailure;
  guarded complete rerun8154passed/1knownfailure/121skipped, without excluding or suppressing tests.
- Remaining failure: `tests/contract/test_external_runtime_deployment_contract.py::test_private_bus_rejects_hard_link_and_detects_substitution`.
  Exact test/bootstrap bytes match preserved main, whose pre-repair run had the same failure.
  This bounded task does not modify host/security setup or waive that gate.
- Prepared public PSDK input matches pin9af08536df36 and all5declared hashes; no fetch or vendor
  compatibility/field claim. Original main314hashes/status/index/HEAD, old82refs/44worktree records,
  priorcandidate100, recovery repair freeze and other215baseline paths pass the preservation audit.
- Guarded lockcheckoffline/schema-check/module-boundary173/normalization/runtime-imagepins,
  referenceguards/pins/PSDKhashes/diffcheck pass. Replay-only277passed/4skipped. Scoped326-file
  secret-shaped literal scan reported0matches (not a complete security audit).
- Actual5browser scenarios use loopback OIDC authentication, Core/worker/real generated TIFFs:
  normal + viewer-readonly + weekly t0→t1/t1→t2reuse + missing vertical reference + overlapping NoData.
  They do not establish customer data acceptance, quantitative accuracy or real-device behavior.
- Index audit: exactly326candidate paths, all staged blobs SHA256-matched to the verified snapshot;
  no checkpoints, ignored evidence, secrets, dependency trees or reference gitlinks staged. Repo hygiene
  passes. Default `git diff --cached --check` reports inherited whitespace in6byte-identical original
  WIP files (Markdown hard breaks and one EOF blank); retained rather than sweeping preserved history.
  Unstaged repair diff check passes; the default staged check is not claimed green.
