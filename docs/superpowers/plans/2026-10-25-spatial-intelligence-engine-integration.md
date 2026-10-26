# Spatial Intelligence Engine integration — 2026-10-25

Status: Local P1 integration and connected UX verified; broader task remains partial (versioned output extensions and external acceptance remain). No deployment, field, or whole-product acceptance.

## Authority and scope

The Human defined Spatial Intelligence Engine as the existing platform's internal interpretation,
evidence/readiness, deterministic spatial calculation and evidence-result layer. The subsequent Human
instruction authorizes developing the audited gaps and improving the actual UI/UX, including substantial
changes where needed. No new product, reconstruction engine, parallel database or microservice is intended.
Authority remains `docs/00_READ_FIRST.md`, the Constitution, Decision Ledger, PRD, applicable contracts,
ADR-KSI-036/037/038/039 and `DOMAIN_INVARIANTS.md`. This task does not close or reprioritize EXT-VAL.

## Revalidated starting point

- HEAD `67db22d3d3f6df79df0002a9ab10d5a71abbf6bd`, main 58 ahead of origin/main.
- Eleven pre-existing modified tracked files (Dashboard and rebaseline ledger), plus untracked
  Playwright/pnpm files are protected. Exact file snapshots and hashes:
  `~/.local/state/ksi-sie-integration-20261025/baseline.json` and `before/`.
- V3 already accepts DSM-only/ortho-only and honest unknown/partial producer/capture metadata.
- Fixed V2 analysis, calculation/evaluation history, coverage, API and MCP adapters already exist.
- The missing arbitrary-pair preflight must not be confused with the existing non-appending
  `get_current_for_read` of a retained analysis.
- WorkArea supports polygon holes. Reuse that exclusion mechanism before introducing mask inputs.
- Runtime/source/test existence is not fresh execution, OS portability, vendor or field acceptance.

## Required implementation plan

```text
Requirement IDs: SDP-REQ-01/02/04/05/06/07/08, applicable EXT-VAL, Human acceptance conditions 1–8.
Owner module: Core owns scope/admission/history; Processing Controller measures; reusable packages calculate; Dashboard and MCP consume the same Core facts.
Acceptance criteria: selected pair can be checked without execution or journal writes; precise authorized causes/remediation; unchanged strict V1/provisional V2; connected visual-first registration/selection/analysis/results/re-entry with honest failure states.
Contracts affected: additive analysis-readiness read DTO/schema/route/MCP tool, corresponding Dashboard BFF/client. Existing persisted contracts, digests and numeric policies retain their meanings.
Reference assets: incumbent source/tests, licensed Floreat evidence and existing public UI-reference studies (not shipped as registered pixels); generated DSM vectors remain explicitly synthetic.
Adoption decisions: REUSE existing ingress/inspection/assessment/calculation and geo libraries; no reference runtime imports, new service, reconstruction engine or dependency installation.
Files to change: scoped Core quantity domain and contracts/MCP/tests; actual Dashboard registration/workspace/materials/analysis components and tests; this ledger and checkout checkpoint. Exact technical file list is recorded with owner return.
Tests: targeted contracts/schema/replay/API-MCP parity and negative authorization, existing numeric/NoData vectors, Dashboard units/types/lint/build, connected desktop/mobile browser and keyboard/re-entry checks.
HIL or real-device assumptions: none. Synthetic/local software proof cannot establish field, measurement accuracy, survey or settlement acceptance.
License/data implications: no automatic cloud transfer, new data rights or vendor integration; submitted originals and attribution preserved; no shared storage/account/grant/retention mutation.
Rollback: disable additive entrypoints/read projections; retain all original bytes and immutable old results/journals. No journal rewrite, policy relaxation or deletion.
```

INV-020/024 are enforced by observed coordinate/unit and independent-evidence boundaries; INV-040/051
by honest absent/synthetic states and original/derived identity; INV-050/060/061 by current scope/egress
checks before metadata or bytes; INV-053 by unchanged numerical prerequisites and execution recheck;
INV-054/055 by retained runtime identities and finite resource envelopes, never client overrides.

## Integrated sequence

1. **P0**: map current implementation and freeze the minimal additive read contract; no redundant intake/math work.
2. **P1**: pure arbitrary-pair readiness, precise diagnostics, same-service MCP call and meaningful UI conditions/recovery.
3. **P2**: verify the existing two-epoch pipeline and necessary result/exclusion bindings. Polygon holes are existing inputs;
   separate mask inputs or changed mathematics require a new profile, not V2 reinterpretation. Delta raster publication is
   distinct from already-existing coverage outputs and needs an explicit output/security/lifecycle contract.
4. **P3**: eight-condition integrated matrix plus persistence/re-entry/revocation/restart and subsequent-epoch continuity.
   Local/Cloud common logic and Windows/macOS/Linux full-worker installation are separate verification dimensions.

## Shared read-only contract (implementation target)

`POST /v2/sites/{site_id}/work-areas/{work_area_id}/analysis-readiness` accepts only the existing two
selectors. `SITES_READ`, exact source/area grants and applicable MCP AI consent are required. It creates
no intent, assessment, execution, lease or journal event and grants no authority. Response
`analysis-readiness.v1` carries Site/WorkArea, exact selectors, current suitability, blockers/limitations,
UTC check time, nullable exact calculation identity digest and `coverageCheck=REQUIRES_WORKER_VALIDATION`.
Creation always rechecks. Old durable `ESSENTIAL_INPUT_UNAVAILABLE` remains unchanged; new diagnostics
explain its concrete prerequisite branches only after scope checks. Changes to this target must be
reconciled between Core, MCP and Dashboard before integration.

## Owners and runtime boundaries

- Engineer `ses_e8dd5816fffe7k5fdO4nevj7lV`: Core/contracts/Analysis MCP/tests only; no Dashboard.
- Engineer `ses_e8dd0c1d1ffehUeTfbaBaT4Fae`: independent exact-asset description projection,
  ingress/catalog route + new DTO/schema/tests only. No quantity/MCP/Dashboard or shared handwritten OpenAPI edits.
- Design `ses_e8dd4fd23ffe7YJvr0KePlua4Y`: actual Dashboard UX/components/BFF/tests; no Core/contracts.
- Main: integration, runtime/evidence, parent checks, this ledger and checkpoint.
- Shared Core8074/issuer9042/Dashboard3243/storage/journals/grants/retention remain read-only.
  Existing prior-task candidate8075/9045/3244 is observation-only until ownership is explicitly reconciled.
  New task-owned isolated fixtures/builds may be started after port/identity checks; no shared restart.
- User rejection of current usability is not erased by historical test totals or prior technical closure.

## Evidence and remaining gates

Fresh implementation/test/render receipts will be appended below. Currently no new completion claim.
Actual customer exports, quantitative accuracy, three-OS installation, independent consumer hosts and
real repeated-observation/customer acceptance remain distinct from generated local evidence.

### Integration preflight and isolated runtime

- Main executed the existing numerical/WorkArea baseline: change-detection package tests +
  `test_external_analysis_measurement.py`, `test_external_relative_volume_analysis_contract.py`,
  `test_work_areas.py`: **113 passed / 1.53s**. This proves only those recorded software cases.
- Main rechecked the known shared Dashboard image/start and all14 journal hash/bytes/mtime:
  unchanged at2026-10-25T08:30Z. No production activation or protected-state repair was performed.
- Fresh read of the prior-task3244 actual product confirms expired-pixel recovery dominates the
  workspace. No original/policy/retention change follows; it is not a new recovery acceptance.
- Generated local runtime uses existing `analysis-e2e/run_core_fixture.py`, real TIFF parsing and
  fixed worker, three synthetic DSM epochs, new task-only OIDC and loopback8033/9031/3231.
  Metadata: `~/.local/state/ksi-sie-integration-20261025/generated-runtime.json`.
  Health200 and exact three-report `inspected-fixture.json` were received. This is synthetic/local
  software proof, not deployed parser containment or customer/field evidence.
- Initial runtime attempt failed closed because `/tmp/opencode` is0775/nonsticky and the authority
  loader rejects that writable ancestor. No check/permission was weakened. The second attempt uses
  a new owner-only0700 task temp root under `~/.cache/ksi-sie-20261025`; failure receipt preserved.
- The real Dashboard runs from the current working source on3231 with its own dist/compiler file.
  Main owns `build-sie` browser and generated services. Official E2E using8033/9031/3231 must wait
  until this own runtime is stopped; no other owner may restart it. Core was imported before new
  readiness/description source completion and must be freshly restarted before final acceptance.
- Before accepting UI work, prove a scoped registered date-only/unknown pair can obtain READ-only
  diagnostics even when it is absent from execution candidate options. Never trust raw URL hints,
  turn candidate membership into suitability, or issue analysis merely to inspect conditions.

### Source integration and material corrections

- Asset-description source and its self-contained schema are received. Main integrated its
  handwritten OpenAPI path with a reference to that schema and added reference-integrity coverage.
  Main ran description/catalog/publication checks: **24 passed / 4.81s**. V1 metadata remains
  unchanged; the new description is not analysis admission or an original-download capability.
- The first readiness return was **not accepted** on its initial counts. Main identified and
  the same technical owner corrected: terminal rejected inspections mislabeled as pending;
  an unguarded decision/details split; missing restricted-OIDC allowance for both new endpoints;
  V3 date-only/unknown pair coverage; actual adapter transport coverage; and untyped new-path shapes.
- A second parent source read caught a remaining negative-snapshot seam: preparation still preceded
  the guard and early blocked admissions had no currentness witness. The final implementation enters
  the shared coordinator/store guard before preparation and captures both decision and details there.
  The owner audited the path as local-memory/pure CPU only and added an old-ordering-fails regression.
  Mutating AP/create paths, legacy blocker meaning and revision allocation remain unchanged.
- Readiness now has11 owner tests, including actual registered V3 date-only/unknown selectors absent
  from execution candidates, rejected/pending distinction, OIDC own/foreign scope, snapshot mutation
  and zero-journal-delta checks. These are owner receipts, not final product acceptance.
- Main actual OIDC UI→BFF→Core request on the **old imported runtime** reproduced403 before the
  allowlist repair. That process cannot validate the final source; a new owned fixture/relogin is
  still required. A green direct-token test alone was not treated as browser integration proof.
- Main added known-answer acceptance tests in `tests/contract/test_spatial_engine_numeric_acceptance.py`:
  100m² ×1m rise =100m³ fill;6m² ×2m excavation =12m³ cut; both reproduce identical numeric/report
  digests. Existing WorkArea holes exclude4 NoData cells while keeping96/96 selected/common-valid;
  the same unholed area remains blocked by the unchanged100% coverage rule. **3 passed / 0.65s**.
  This is synthetic worker-callable proof, not real customer export or field-accuracy acceptance.
- Main Ruff over touched backend/contracts/MCP and new tests is clean; scoped mypy8 source files
  is clean; `git diff --check` is clean. A final combined backend regression is running separately
  under `~/.local/state/ksi-sie-integration-20261025/backend-final-v2/` with exact input hashes.
  Its first command failed its path preflight (wrong OIDC test basename), before running tests;
  the corrected command uses the discovered actual file paths.
- Design remains the single Dashboard writer, continuing the same UI unit after the narrow initial
  pass was rejected. Main owns final frozen-source locked build and fresh integrated browser proof.

### P2/P3 reconciliation — not silently represented as completed

The existing fixed V2 calculation returns metrics and digest-bound coverage masks. It does **not**
publish a first-class height-difference GeoTIFF. `packages/change-detection/diff_raster.py` is reusable
writer code, but design/managed-path calls are not proof of a mounted external V2 publication route.
An ephemeral local file or client-side recomputation cannot stand in for durable Core-verified bytes.
That extension needs an additive output/storage/currentness/egress/lifecycle contract, with the V2
`current−baseline` sign explicit; it must not add fields to frozen historical report identities.

WorkArea polygon holes already supply bounded digest-bound exclusions. A separately supplied raster
mask would need a new input identity/profile, frame/NoData/hole precedence and validation contract.
Do not relax V2 common-valid coverage or silently reinterpret its calculation identity. No separate
mask input or delta-raster publication has been implemented by this P1 integration. Final reporting
must preserve these gaps and the external customer/OS/field gates rather than claiming all scope
from component test totals.

### Final integrated software checks and fresh rendered review (in progress)

- Main's first combined run was405passed/1failed: the asset unit's temporary test still expected
  route-level403 before the newly integrated scoped-operator allowance. Main corrected that test to
  the approved contract (own-area read200, foreign-area404 identical to absent-resource404), not to
  a weaker permission gate. The targeted description + actual-inspection MCP suite13passed.
- Main also extended the actual SDK stdio/real-inspected Core integration test to call the seventh
  readiness tool before creation, validate the typed result, compare the HTTP decision except its
  check timestamp, and require unchanged journals/zero intents. The NoData case explicitly proves
  readiness does not promise the later worker's coverage validation.
- Final combined backend/contract/SDK/replay/numerical run: **406 passed /224.70s**, exit0, **zero
  input-source drift**. Full command/hashes/logs: task evidence `backend-final-v3/receipt.json` and
  `pytest.log`. This includes existing strict V1/provisional V2 and real-parser local lanes.
- Locked UI toolchain receipt: Node22.18.0/Next16.3.3/Vitest4.1.11, package-lockSHA
  `b3ab46af4f40d83b069148f342cf895183053f492590a79f0c0d2f5bf9cef36d`. At the pre-review source,
  **2156 tests /209 files + lint pass** (`locked-86e84a6055`), then **build+types pass**
  (`locked-1b23516540`). Main compared all542 UI source/test hashes: identical across both runs and
  current at that boundary. No dependency install, writable host mount, deployment or shared restart.
  Initial verification snapshots failed first for an omitted test-consumed systemd manifest (fixed
  snapshot, test unchanged), then because network=none blocked the existing next/font build-time
  Google download. The subsequent isolated build allowed that existing public-font fetch; it is NOT
  described as a fully offline build. All failed receipts remain. These UI receipts precede the
  final independent-review repairs below and must be revalidated after source freeze.
- Generated runtime4 contains three actually inspected synthetic TIFF epochs **and** two additional
  genuine V3 registered/byte-sealed unknown/date-only submissions, coexisting with three execution
  candidates. The task-only launcher wraps the test runner's manifest-write seam to register the
  extra pair via real OIDC ingress handlers; byte PUT remains the existing in-memory fixture storage
  boundary. It patches no production code, route, permissions, inspection outcome or numeric policy.
  `generated-runtime.json`, `core-process.json`, private runtime `inspected-fixture.json` and
  `readiness-fixture.json` bind source/process/data. This is not customer/S3-host acceptance.
- Main actual OIDC UI→BFF→Core checks now return200/provisional, not the stale process403.
  Repeated preflight leaves all7 Core journal bytes/SHA256/mtimes unchanged and analysis count0
  (`parent-before/after-readiness.json`, `parent-ready-flow.log`, `parent-repeated-readiness.log`).
- Main explicitly requested the first analysis through the real form:202→COMPLETED, cut/fill0.01m³
  each, net0, uncertaintynull, four selected/common-valid cells;19 evidence items remain retrievable
  (`parent-first-result.json`). The second UI request uses the first current selector as its baseline
  and the third observation as current, obtains a new result identity and0.02m³ cut/fill. An initial
  automation receipt captured RUNNING/null after an async wait and is **not** completed-result proof.
  The superseding `parent-two-cycle-settled.json/log` asserts three consecutive COMPLETED/non-null
  reads, known metrics, fresh identities, unchanged first result, same WorkArea, Core newer-sibling
  link, reload persistence and exact workspace-result bridge. No result was overwritten.
- Real mixed-list unknown pair:200/BLOCKED with per-epoch capture-interval reason and precise Korean
  guidance, despite three unrelated executable candidates (`parent-unknown-pair.json/log`). Real
  OIDC viewer: both known/unknown reads200, zero execution buttons, attempted create403, exact-query
  login return (`parent-viewer-flow.json/log`). Actual metadata note rendered from the new descriptor
  route; no synthetic display pixels were substituted for unavailable data.
- Main read initial1440/390 captures itself. `parent-ready-1440.png` was accidentally a section
  capture because focus scrolled the inner main while windowY stayed0; it is **not** initial-scroll
  evidence. Correct `*-scroll0.png` reset every scroll container and record no remaining scrolls.
- Fresh independent Critic `ses_e8d985c7dffegd9XmWdSks7uHh` found no blocking security defect and five
  **material UX/trust issues**, not waived as minor: first50-only pair lookup; stale cross-asset
  provenance; declaration wording that implied verification; worker translated as a human approver;
  first-use guide burying the actual task. Design resumes the same unit for ONE bounded repair batch,
  followed by Main's final frozen-source gates and batched rendered confirmation.
- A separate parent actual-route read found the explicit workspace `analysisId` destination only
  said a number existed and linked away, unlike its default-list card which displayed metrics.
  Design `ses_e8d8f0b86ffewM8wMUG5EWhkQB` owns only `SiteWorkspaceResults.tsx` and a new focused test:
  display the same Core-provided cut/fill/net with limitations and honest small-value formatting,
  never recompute or replace the frozen inputs. The other Design owns no edits to those two files.

Remaining acceptance: receive both Design repairs; verify actual diffs; rerun final locked UI gates;
read actual initial1440/390 views and keyboard/axe/reentry; independently review only the repair
delta; recheck protected shared runtime/journals; reconcile all genuine unsupported/external gates.
No product/EXT-VAL/customer/OS/field acceptance or production activation is declared.

### Final reception — 2026-10-25T10:12Z

**Locally delivered:** additive exact-asset description; pure arbitrary-pair readiness; the seventh
Analysis MCP tool; scoped OIDC/BFF/client wiring; precise per-epoch recovery; readable first-use
selection; read-only viewer access; stable result/evidence/re-entry/next-observation continuity;
and actual Core quantities at the explicit workspace-result destination. The engine remains the
existing Core/worker/library system. No new reconstruction engine, service, dependency or numerical
policy was introduced.

- Both Design units are received. Main added six independent provenance-binding regressions
  (loadedA→B404, lateA afterB, wrong asset/site/area echoes, malformed producer/capture) in
  `apps/dashboard/test/asset-provenance-binding.test.tsx`; all pass. First-use hierarchy was verified
  from actual1440×900 and390×844 initial views: both native baseline/current controls are fully
  visible above the mobile bottom navigation. Help follows the task in a collapsed disclosure.
- The first final browser sweep reached all workflow assertions but **failed** its final axe gate
  on invalid `dl > div > details` grouping in the unknown-pair/viewer states. It remains a failed
  receipt (`final-integration.log`), not a passed end-to-end total. Two mechanical `dd` wrappers
  repaired the semantic issue; targeted panel73 tests/lint pass. No visual, state or policy change.
- After that repair, `final-settled-confirmation.json/log` passes: both actual UI-created records
  are COMPLETED/provisional with non-null results and null uncertainty; known0.01 and0.02m³ cut/fill;
  distinct identities, three consecutive stable reads, same-area continuation,19 matching evidence
  items, reload stability, precise viewer unknown-pair read and no execution controls, and actual
  workspace0.02m³ values. The original sweep also exercised actual viewer forbidden-create403.
- Five final WCAG-tag axe scans report **zero violations** (viewer unknown at1440/390, completed390,
  workspace result1440/390). The tool's incomplete checks (`aria-prohibited-attr`, `color-contrast`,
  `duplicate-id-aria` in some states) are retained; a physical screen-reader walk was not run.
  This is automated/keyboard/local verification, **not** a WCAG conformance certificate.
- Main personally read the final first-use and confirmed result/unknown-viewer captures. Screens:
  `final-first-use-{1440,390}-scroll0.png`, `confirmed-workspace-result-{1440,390}-scroll0.png`,
  `confirmed-viewer-unknown-{1440,390}-scroll0.png` in the task evidence root. These are real
  connected synthetic-fixture renders, not detached mockups or substituted production imagery.
- Fresh Critic repair-delta review resolves M1–M5, the explicit-result quantity gap and the serious
  definition-list defect by source/regressions/rendered proof; no required material finding remains
  in this local P1/UX scope. Its report still called the then-running final locked run pending;
  Main subsequently received and read the actual successful terminal receipt below.
- **Final exact-source locked UI gates:** `locked-4a18107eea/{receipt.json,gates.log,source-manifest.json}`:
  **2169 tests /211 files, lint, production build and typecheck all exit0**, no input-source drift.
  Existing public-font build fetch is allowed in the isolated container; no dependency install.
  Backend **406passed** and scoped Ruff/mypy receipts remain source-valid; `git diff --check` clean.
- `final-source-provenance.json` confirms zero changes since the backend406 receipt, zero UI changes
  since final locked gates, zero changes to the live Core's imported source, and preservation of the
  pre-existing modified rebaseline ledger. HEAD remains67db22d3; changes are uncommitted/unpushed.
- Final protection check at10:11Z: shared Dashboard image/start and all14 protected journal
  bytes/hashes/mtimes are unchanged. No shared Core/issuer/Dashboard/storage restart or deployment.

**Runtime continuity:** task-owned runtime5 is on3231/8033/9031, private root
`~/.cache/ksi-sie-20261025/ksi-analysis-e2e-b94d156ca5366da1`; metadata/process hashes and launcher
are in `~/.local/state/ksi-sie-integration-20261025/`. It is a temporary synthetic verification
preview, not the shared production UI. Runtime4 was gracefully stopped and its public synthetic
journals/manifests retained in `runtime-attempt4-public-evidence/`; no secrets were copied there.

**Still open — not hidden by local success:** first-class delta-GeoTIFF publication and independent
mask inputs require additive output/lifecycle/security and input-profile contracts respectively;
only existing polygon-hole exclusions are delivered. Actual retained customer exports, independent
consumer hosts, Windows/macOS full-worker installation, field/accuracy and customer repeated-use
acceptance remain unverified. Real Floreat pixel recovery retains its original containment,
versioning and expired-output constraints. EXT-VAL and product-state/milestone history are unchanged.
The next integrated outcome is those versioned extension contracts and permitted external validation,
not reimplementation of the now-verified P1 or relaxation of frozen V2.

### 2026-10-26 combined candidate and P2 decision boundary

The existing uncommitted P1 is now also integrated with the later viewer-first UI in isolated
`integration/viewer-first-20261026`. This is a preserved-source snapshot, not a main merge or
production activation. Current verification and whole-scope limits are in the existing
[Console work entry](../../ledger/work/2026-10-26-console.md): backend406, locked UI2225, actual
two-cycle synthetic browser/worker completion, native mobile modality, user-controlled global menu,
non-overlapping panels and the corrected capture-option identity regression. Do not replace or
erase the original2026-10-25 receipts above; the deployed image still omits the combined SIE UI.

**P2 contract proposal, not an implemented capability or new authority:**

1. **Delta publication** should be a separately versioned, digest-bound derived artifact referencing
   the exact immutable calculation and both source revisions. Sign is explicitly `current−baseline`;
   grid/frame, selected/common-valid coverage, holes and NoData stay those of the calculation.
   It must not be reconstructed from aggregate metrics, added into an old report's digest body,
   treated as an accuracy certificate or served through an unguarded original/download URL.
   Output creation/replay/currentness, organization/site/area/AI egress checks, bounded byte size,
   protected storage, policy-owned expiry and revocation require an explicit publication contract.
   No new lifetime, sharing grant or format approval is inferred from the existing coverage route.
2. **Independent mask inputs** change the quantitative selection identity. They therefore need an
   explicit new calculation profile, sealed mask digest/source binding and a defined binary exclusion
   convention, exact grid/CRS agreement, NoData handling and polygon-hole precedence. No silent
   resampling, filling, treating missing pixels as0, relaxing100% common-valid coverage, or mutation
   of historical V2 identities is permitted. Existing polygon holes remain the only delivered
   exclusion mechanism until that profile is selected and its policy authority is valid.
3. **Necessary scope/contract choice:** retain existing V2+polygon holes for the first pilot and
   deliver versioned delta publication first, or include the independent mask profile in the same
   release (additional numerical/input-security acceptance). This affects result meaning and pilot
   scope, so it is a product-owner choice, not an agent silently discarding approved remaining work.
   Either path still requires the publication contract and unchanged real-data/host/customer gates.

No new endpoint, export worker, mask capability, signed policy value or production permission is
created by this proposal. All already approved implementation remains in force; only the unresolved
quantitative extension semantics and release sequencing are brought back for an explicit decision.

### P2 execution choice — Human confirmed 2026-10-26

The Human selected **새 프로필로 분리 (Recommended)**: retain all V2 identities/results; implement
delta GeoTIFF as a separate evidence-bound derived output and independent mask inputs under a new
calculation profile. Exact grid only; mask NoData is a blocker; record the exclusions and their
numeric impact. This closes the scope choice above, not signed deployment policy/data/host gates.

Implementation boundaries for this continuation:

- Add separate immutable mask/profile/calculation/output contracts; no new fields or reinterpretation
  of frozen V2 contracts, journals or numeric results. Producers/consumers remain Core, worker,
  API/MCP and Console, and retained records are permanent consumers.
- Mask convention: uint8 single-band binary0=retain,1=exclude. Invalid/nonbinary/NoData input blocks;
  exact baseline shape/affine/CRS only, no resampling. Polygon holes exclude first; report the full
  original WorkArea, independently excluded cells and final effective selected cells separately.
  Remaining selected cells still require100%common-valid coverage; an empty effective zone blocks.
- The new profile retains current−baseline, zero threshold, metre-axis prerequisites and null
  uncertainty unless a separately approved assessment says otherwise. A V2 binding may be retained
  as source evidence, but it is never the masked calculation's identity or admission authority.
- Raster output is derived from the actual validated delta array, not aggregate metrics. Inactive,
  expired or revoked publications grant no bytes. Scope/currentness/AI-egress checks precede output
  access. Lifetime and byte/resource ceilings remain explicit policy inputs, not guessed defaults.
- Ownership: Build integrates/owns shared docs and routes. New pure math may be delegated within
  change-detection; new immutable models/schemas may be delegated within event-contracts. Workers
  parse only through the retained contained/bounded path. No shared runtime/production mutation.
- Verify hostile masks/frame mismatches/holes/NoData/empty and oversized zones, known answers,
  digest identities, old V2 schema/replay regression, Core scope/revocation/replay and actual
  synthetic local worker/output bytes before claiming a mounted capability. No customer accuracy claim.
- No new reference code/dependency/data rights/device assumptions. Rollback disables new entrypoints
  and retains old V2 behavior and immutable new records; no migration/deletion of historical data.

### P2 implementation in progress — revalidated 2026-10-26

The previous P2 proposal/Console whole-scope table's “decision required” status is superseded by the
Human choice above. There is no new pilot-scope or contract-approval stop. The measurement/model
foundation is committed as `131e5e29` after P1 `d20379cd`; the guarded delta protocol/API models,
MCP and result-bound export consumers are committed as `a0e40cb6`. Later composition/worker/mask
integration remains uncommitted.
No new route is enabled by default and no deployment occurred.

- New strict mask/profile/identity and V3 coverage/result/impact contracts, pure masked math and
  byte-bound contained measurement primitives are implemented. They preserve V2 identities and
  make unmasked impact null when excluded source cells are unknown. Software tests are synthetic;
  separately authorized mask runtime/host containment is not established by importable primitives.
- Additive UINT8 mask TIFF preflight shares directory/entry/block/overlap/allocation safeguards
  without widening the old DSM/RGB parser. Mask NoData/extra IFDs are rejected before native decode.
- V2 measurement → private FLOAT64 delta retains the original V2 report bytes. Separate V3 writer
  consumes the actual V3 measured array/report, never a fabricated V2 numeric result. Fresh combined
  writer/measurement checks:44 passed; native output SHA/cells/NaN exclusion, metre/sign/identity tags,
  private descriptor lifetime, deterministic bytes, resource/currentness failures and V3 identity
  mismatch covered in `tests/contract/test_external_masked_delta_raster.py` and adjacent tests.
- Core publication lane's first delivery was not accepted: scoped-human checks, read currentness,
  worker ownership, integrity and source-version defects were identified and corrected by its owner.
  Trusted output-observation binding and bounded read/storage hardening are now under follow-up;
  no fake authority port is counted as actual production authorization.
- Independent mask child ingress and new V3 admission/lease/three-input execution workstream is
  active. A successful unmasked V2 numeric result is not a prerequisite for V3 admission.
- Remaining Build integration: inspect those deliveries; real Core source/authority/egress/output
  adapters and publication handshake; explicit optional composition + exact auth route allowlists;
  closed API/MCP/Console consumption; actual generated-mask/DSM→V3→delta→guarded bytes/replay proof.

Integration follow-through (same authorized task, still in progress):

- Actual retained Core AP/NX journals now back the V2 delta source resolver. The integration test
  measures generated DSM bytes, accepts the immutable numeric report, validates the actual emitted
  TIFF through the worker-side observation seam, and publishes/reads only after a new purpose-bound
  synthetic signature and output lease. Source-evidence revocation denies subsequent reads. The
  synthetic signing key is temporary test material, never customer or deployment authority.
- This actual Core integration exposed a compatibility error absent from small aligned fixtures:
  frozen coverage windows may include unselected border cells outside the original DSM rectangle.
  Delta writers now preserve those cells as NaN padding and still reject any selected cell outside
  the byte-bound baseline. No V2 numeric record, coverage witness or digest is changed.
- Publication receipts are distinct from byte uploads and require the exact pinned worker/lease,
  current source/activation and matching observed grid/hash/size. Raw uploads alone grant neither
  format nor availability. Fresh API work uses closed source-only requests, bounded JSON/raw streams,
  explicit observation acceptance and guarded byte slices; it remains optional, not deployed.
- Latest stable math/model/measurement/parser set:229 passed (explicit integration imports). Fresh
  publication/source/receipt set:78 passed before the new closed API consumer wiring. These are
  functional software checks, not product acceptance. Real Core mask adapters, late delta-reproduction
  worker, additive MCP operations and guarded Console export status are actively assigned; Build owns
  composition/auth/schema integration and final real-rendered acceptance.

2026-10-27 integration revalidation (same task, no deployment):

- Explicit delta common composition and exact MCP/OIDC consumer route allowlists are connected;
  absent config still mounts no extension. Closed source-only API, actual worker output acceptance,
  bounded raw upload/read, successful revoke response and rejected-byte conflicts are exercised.
  New policy attempt caps are constrained by the configured envelope. The combined API/contract/
  composition/receipt plus incumbent Analysis HTTP set passed **46** checks after those fixes.
- The late V2 publication worker now has a task-owned live-loopback Core/object HTTP proof through
  `run_delta_publication_job`; original completed NX report bytes stay unchanged. Pending-job
  discovery/driver and independent V3 late publication wiring remain in integration.
- Additive MCP verification passed **17/17**, including the official SDK stdio child explicitly
  bootstrapped from this checkout's source (no unsafe environment inheritance or environment install).
- Export UI hardening delivery includes exact response validation, source-change cancellation,
  expiry precedence, pre/post guarded metadata checks and verified two-chunk assembly. Parent result
  binding/config plus incumbent page/panel tests passed **114** and TypeScript; the UI owner's full
  suite reported **2,295**. Real-rendered composed acceptance is still pending on a fresh P2 runtime.
- Mask-family admission/runtime/activation and immutable byte-journal/storage defects found during
  source review are assigned for correction before mounting. The actual masked HTTP/composition and
  Console workflow are still implementation work, not unavailable external authority.

Rendered delta verification (fresh task-owned Core8036 / Console3234; synthetic only):

- The actual Console user action created a publication; bounded worker discovery found the opaque id
  and the late-output worker published it. The browser downloaded **525,191 bytes** through two guarded
  BFF slices (524,288 + 903). File SHA-256 matched the descriptor; current metadata was checked before
  and after assembly. The original V2 numeric result stayed visible and unchanged.
- Desktop 1440px / mobile 390px showed the numeric result and separate output state without horizontal
  overflow. Mobile write restriction and read/download access remained distinct. Keyboard focus and
  Enter/Escape on the permission explanation caused no additional mutation.
- A simulated typed-expiry response exposed a stale green availability badge during download. It was
  corrected and rechecked in the rendered component: the descriptor/download action disappears and
  expiry is shown without changing the numeric result. Typed-expiry and forbidden branches in these
  captures are **simulated HTTP responses**, not customer events or Core state changes.
- Exact receipt and screenshots: `/tmp/opencode/ksi-integration-20261026/p2-preview/rendered-verification.json`
  and `browser-download-receipt.json`. That running Core predates the latest typed-disposition and
  lapsed-lease discovery changes; fresh tests cover those fixes. A final all-lane re-import is pending.
  Dev font-preload warnings and expected unavailable-read 404s are disclosed, not a clean-production
  console claim. The focused UI/source-binding set subsequently passed **94**, with TypeScript clean.

Mask authority corrections now preserve provisional accuracy, bind all five execution runtime pins
and the actual signed activation record, reject immutable-byte overwrite/symlink/journal tamper, and
accept only the designated inspection worker at the worker seam. Baseline-parent mask children are
allowed; the earlier distinct-parent restriction had no approved basis and was removed. The new V3
source adapter passed **9** genuine-but-synthetic source/currentness checks without any V2 NX result.
Optional masked mounting, actual inspection/calculation transport, source-context/BFF/Console wiring,
V3 late-output transport and their composed acceptance are still active integration work.

Subsequent whole-Console check: **2,376 tests / 228 files passed**, including the new selected-AP
source binding and masked-result/export composition; TypeScript passed. The isolated worktree's
`node_modules` symlink resolves into main, outside Turbopack's configured root, so the default build
failed at Next-package resolution (the package exists; no install was run). The documented
`next build --webpack` path compiled, typechecked and generated all routes successfully. Standalone
tracing warned that **27 linked-dependency files** lie outside its trace root: this is compilation
evidence, **not a portable release artifact**. No shared dependency/configuration was changed; the
build's two run-local tsconfig include additions were removed without changing the original entries.

### P2 common-lane integration — 2026-10-27 verification

- Both optional lanes now use the actual common platform factory and exact AP/Site/reconstruction/
  inspection/WorkArea/currentness objects. Missing configuration still mounts neither lane. Distinct
  purpose signatures and explicit runtime/envelope/worker pins remain required; no production factory
  silently enables the extension. V2 and V3 source routing is record-derived, ambiguity denies.
- First masked execution is now verified over genuine loopback HTTP: human declaration/upload →
  worker discovery/inspection → Core seal → human source-only V3 request → worker discovery/lease →
  direct DSM capabilities + protected mask bytes → native worker dispatch → Core report acceptance.
  Generated 4×4 proof: original16, excluded1, effective/common-valid15, unavailable0; fill2/cut2/net0,
  provisional admission retained. No completed V2 numeric report or borrowed V2 attempt authorizes it.
- The critical human-issuer/worker confusion is corrected: the required designated Analysis worker,
  not the human issuer, is sealed into V3 execution authorization and checked through every transition.
  Runtime/envelope/activation mismatch is rejected before object download/native decoding. Mask byte
  windows use the pinned private root and same descriptor for full-hash proof and bounded window.
- Inspection failures are fenced, terminal and visible: deterministic input rejection is REJECTED;
  unexpected IO is FAILED; both leave the immutable input bytes intact and cannot revive a lease.
  Human status reads no longer infer endless pending from a null manifest. Report time is within the
  live inspection lease. Typed failure/status models remain separate from frozen V2.
- Mixed export queues are version-filtered **before** lease/limit: the V2 drain cannot consume a V3
  retry and vice versa. Genuine mixed-lane proof publishes each independently and retains both source
  numeric reports byte-identically. Expired leases remain rediscoverable within signed retry caps.
- Console source selection binds current evidence pages to their selected analysis/revision/digest,
  with an explicit read-only source-evidence action. V3 export uses only the AVAILABLE V3 result's
  exact three digests; non-AVAILABLE/denied inspection callbacks clear stale export availability.
  Session continuity stores only opaque child/request ids scoped to organization/principal/site/area/
  source, and resumes only by explicit guarded Core reads; no file, credential or capability URL persists.
- A fresh combined backend run passed **372**, zero deselection; updated full Dashboard suite passed
  **2,401 / 229 files**, TypeScript and scoped ESLint passed. Mypy passed **34 changed/new source modules**;
  changed/new Python Ruff passed. These are software evidence, not customer or sandbox acceptance.
- Actual common-fixture boot exposed an early TestClient lifespan shutdown during DSM seeding: the
  seeding transport now closes without ending the future live app's lifespan. The regression confirms
  `/ready` remains true until actual application shutdown closes owned descriptors. Failed startup
  receipts are retained separately; no journal or permission gate was bypassed.
- Actual browser declaration exposed a null-digest construction seam: Core now seals the validated
  declaration intent before the store (whose sealed-input rule is unchanged). Tampered provided digests
  still fail 422 without journal growth. Browser upload-to-result/output and rejection recovery are
  the final composed verification in progress, not an unavailable external authority.

### P2 final local acceptance reconciliation — 2026-10-27

The composed local outcome above is now verified, not left at individual module handoffs. The actual
common-factory preview (Core8037 / issuer9034 / Console3235) accepted a browser-uploaded generated mask,
discovered and inspected it through the first worker, accepted the user's separate V3 calculation,
and published/downloaded its separate V3 delta through the late-output worker. The browser file is
**525,191 bytes**, two slices **524,288 + 903**, SHA-256
`54fc22bfd49d1fe77e63b26cddd825ee52e7fdc800368f950dacd497a257c582`; metadata was checked before/after
assembly. FLOAT64 native readback has exactly3 finite selected cells (`-1,0,+1`) and9 NaNs, retaining
excluded/unselected cells as NaN. The source V2 result remained byte-equivalent as parsed JSON.

Actual browser tests also uploaded a NoData-tagged mask: the real inspector rejected it, Core retained
REJECTED status, calculation/upload actions disappeared, and a corrected fresh child subsequently
reached AVAILABLE. The rejected record stayed terminal. Reload plus explicit scoped restore made zero
mask/calculation/publication mutations. Desktop1440/mobile390 first and result views, small positive
areas0.04/0.03m² and keyboard disclosures were inspected; no horizontal overflow. This finite-input
browser record does not replace the separate unknown-impact/NaN fixture evidence.

The actual composed checks corrected three interface gaps missed by hand-made fixtures: unsealed
declaration construction, missing browser upload-verification headers, and legitimate signed padded
coverage offsets(-1,-1). Real public contract payloads now cover the latter. BFF upload forwarding is
pull-based and cancels its source on rejection/timeout; ambiguous declaration/calculation retries retain
their exact intent ids. Accepting a new mask draft clears stale result/export presentation without
changing the old Core record. Positive sub-square-metre areas no longer display as zero.

Final verification: **372 backend contract/replay/integration tests**, zero deselection; **2,413 Dashboard
tests /231 files**, TypeScript and scoped ESLint; **34 Python source modules mypy**, changed/new Python
Ruff. Source-bound MCP/official SDK stdio **17/17**. Final Webpack compilation/typecheck/route generation
passed after render fixes; the default Turbopack/shared-symlink and27-file standalone tracing limits
remain disclosed above. No portable release artifact is claimed.

Durable non-secret actual-render/native-byte receipts and captures:
`~/.local/state/ksi-console-ia-20261025/integration-20261026/p2-masked-20261027/manifest.json` and
`masked-rendered-verification.json`; V2-only export evidence remains under the sibling
`p2-delta-20261027/`. Failed startup/harness/development receipts remain in the task scratch root,
not counted as product passes. Original main patch and16 original untracked inputs were hash-verified
unchanged; the unrelated child stash-apply was narrowly repaired with original stash and bytes retained.

| Approved requirement / remaining boundary | Live disposition |
|---|---|
| Viewer-first 공간/자료; list/form-first 업무/결과/검토; user-controlled navigation | P1 retained; no new Home/theme/global IA change |
| Frozen V2 contracts/results and existing replay | Preserved; named V2 contract/schema diff from P1 is empty; original numeric result unchanged through actual V3 flow |
| Independent exact-grid UINT8 masks, holes-first exclusions, strict validity, unknown-impact honesty | Implemented and verified at synthetic local/software scope; native containment is separate |
| Core ingress/admission/currentness, protected bytes, actual first worker and retry/replay | Implemented and verified, including designated principal, five runtime pins and signed new-purpose activation |
| Separate V2/V3 output publication, discovery, bounded guarded file reads, MCP/Console consumers | Implemented and verified at local generated/official SDK scope; external AI-host installation not inferred |
| Actual Console declaration→inspection→V3 result→delta download; rejection/recovery/resume | Verified through actual common factory, not manually copied mounts or substituted success replies |
| Production policy/runtime/envelope signing, installed host containment, portable release artifact | Signing/host gates remain BLOCKED / unverified; same-platform Dashboard package relocation is verified in the follow-up below, not a signed/full-platform release |
| Permitted retained customer inputs, EPSG:7850/vertical evidence, independent consumer hosts, field/quantitative/repeated-use customer acceptance | BLOCKED / unavailable; no imagery, accuracy, Terra or customer acceptance invented |
| Main merge, push, production/TLS/cloud/billing/account mutation; Home/global IA/theme | Not performed or newly authorized; original main work remains protected |

Local P2 development/integration is complete at the evidence scope above. Whole product/customer/
deployment acceptance is **not** complete: the next goal-serving acceptance requires the actual signed
deployment/runtime/host and permitted customer/consumer inputs, not another synthetic fixture pass or
another request for the Human to repeat “다음 진행”. Historical F-03/Task5a/5c closure stays within its
recorded synthetic/authorized-host scope and is not reopened or promoted by this work.

Only unavailable signing/provisioning, deployment-host proof, retained permitted customer data and
field/consumer/customer acceptance remain external. Continue independently actionable local code;
do not turn those gates into an implementation-completion claim or an invented approval request.

### Dashboard standalone package follow-up — 2026-10-27

Human approved continuing with isolated package validation; no merge, push, shared dependency
installation, production/TLS, account, signing or existing preview-server changes were authorized
or performed. Base: `b9dc81ea578aa3b889b5c117ed0c24c42e7c7794` on the same integration worktree.

The original Webpack standalone copied outside the checkout failed with `Cannot find module 'next'`.
Its27-file warning was real: the app-local tracing root excluded the linked dependencies. A shared
build-root helper now picks the nearest common parent of the app and real `node_modules` for both
Turbopack and NFT. Normal app-local/Docker layouts remain unchanged. Both compiler paths now finish
without the omission warning. Webpack additionally omitted four pnpm resolver aliases despite
including their target bytes; the package builder restores only aliases to already traced targets,
not an unbounded dependency copy or a hand-maintained missing-file patch.

`package:standalone` validates trace presence/bytes and relocatable links, rejects build-time `.env`
files and existing/overlapping output, preserves the generated nested layout, copies static/public
assets and retains the production-profile guard via `start.mjs`. `verify:standalone` copies the
package again outside the checkout, strips inherited credentials/Node path overrides, and confines
CommonJS resolution to that copy. It checks login200, all referenced JS/CSS200 (Turbopack12 /
Webpack11 assets), protected page307, unauthenticated malformed-JSON BFF POST401, retained public
asset307 and incomplete EXTERNAL_VM rejection. Core is deliberately unreachable. This diagnostic
guard is **not** an OS sandbox or native-host containment claim.

The stricter run-local compiler included generated route types and exposed a pre-existing `/field`
optional-whole-props signature error. Removing its default `{}` argument preserves runtime behavior;
direct component tests now pass `{}` as Next does. The prior final-build compiler excluded
`test-results`, including its generated types: its compilation/static/source checks remain evidence,
but do not establish the generated-route-type check. Both new complete builds include those types
and pass. Final Dashboard suite: **2,425 tests /232 files**, including12 new packaging regressions;
generated-type-inclusive `tsc`, changed-source ESLint and `git diff --check` pass. Full ESLint exits0
with7 pre-existing warnings in unchanged evidence/delta-test files (no new warnings). Backend
contracts are unchanged, not relabeled as newly rerun tests.

An actual externally located Turbopack package also rendered the existing configured-local-OIDC
login at1440×900 and390×844: primary CTA visible/unobscured, mobile keyboard focus visible, no
horizontal overflow or failed resource responses. No login/issuer registration was mutated and
this is not an authenticated end-to-end packaged workflow claim. Only the new packaged preview3240
and verification browsers were stopped; the existing P2/Core/issuer previews were not restarted.

Durable non-secret logs, source/package manifests, two same-platform package archives, smoke
receipts and captures: `~/.local/state/ksi-console-ia-20261025/integration-20261026/standalone-20261027/`.
`main-protection.json` rechecks the protected original main patch and16 original untracked inputs
against their prior hashes: unchanged. No main merge, push or deployment occurred.
Scratch preserves failed attempts at `/tmp/opencode/ksi-standalone-20261027/`. Actual environment:
**Linux ARM64, Node24.19.0, installed Next16.4.2**. This closes the linked-worktree default-build and
local relocation defect, **not** Docker's Node22 Alpine/locked-version proof, a signed platform
release, production activation, independent native containment, permitted retained customer data,
CRS/vertical/field accuracy, external consumer-host or customer acceptance. V2/V3 semantics and the
viewer-first UI are unchanged. Those genuine external/target-environment gates still prevent
whole-product/deployment acceptance; historical F-03/Task5a/5c scope is unchanged.
