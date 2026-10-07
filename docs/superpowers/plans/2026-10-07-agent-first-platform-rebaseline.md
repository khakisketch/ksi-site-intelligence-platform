# Agent-first platform rebaseline — discovery ledger

Date: 2026-10-07
Status: foundation approved; Tasks1–2 technically verified; Task3 neutral extraction next
Base / proposed local target: main b27e5d94b04d11e155e41d8df94c70519808a976
Workspace: current checkout, one writer; other worktrees retained unchanged.
Prior unmet goal remains closed; Human-approved new goal b13320f7 is active.

## Human intent and decisions

- Human excludes flight/autonomous acquisition from long-term product responsibility.
- Human asks to remove/archive unnecessary functionality and considers a new agent-centered build.
- Retained value: externally produced spatial-artifact registration, inspection, structured access,
  comparison and reproducible analysis for external agents/software.
- Human clarified the platform as physical-space observations → evidence-bound Site State/Change
  → people/AI/software/robots; construction is the first market, not the entire product identity.
- Human approved cleanup-first direction and then asked for long-term development through completion.
  Adopt new platform assembly with selective reuse in the existing repository, not a greenfield rewrite.
- Agent-centered means external agents use scoped API/MCP, not an embedded autonomous agent runtime.
- This approves writing the presented design, not a nonexistent written spec/plan or default goal creation.
- Written spec: [Physical Site rebaseline](../specs/2026-10-07-physical-site-platform-rebaseline-design.md).

## Architectural process checklist

- [x] Revalidate checkout branch/HEAD/status/worktrees and existing checkpoint/slice/task ledger.
- [x] Read product authority, ADR036/037/038, selected roadmap and repository routing.
- [x] Reflect Human intent; classify architectural restructuring.
- [x] Inspect focused Core/worker/MCP source and dependencies before recommending disposal.
- [x] Confirm agent-centered interpretation and select approach with Human.
- [x] Present sectioned architecture, data/error flow, preservation and acceptance design.
- [x] Obtain conversational design approval before writing detailed spec.
- [x] Write/self-review focused spec with exact scope/supersession; local delivery recorded in checkpoint.
- [x] Human reviews written spec before implementation planning.
- [x] Use writing-plans; self-review and independently verify the first foundation plan/inventory.
- [x] Human reviews written foundation plan and selects execution method.
- [ ] Execute approved stages and independently verify integrated outputs.

Visual companion is not currently needed: this is a responsibility decision, not UI.

## Read-only findings at base revision

- Constitution, Decision Ledger, PRD §1.2/§2/§23/§25/§26 and product-state future slices retain
  excluded acquisition responsibilities. Latest Human decision controls intended behavior;
  authoritative documents still need explicit reconciliation and historical scope annotations.
- Core pyproject directly depends on mission-contracts, mission-planning and equipment-intelligence.
- composition/workspace_graph.py builds acquisition connectivity and optional coordination,
  capture-quality and managed readiness alongside workspace state.
- external/ingress/spatial_asset_catalog.py:277–303 resolves assets through scoped WorkOrders,
  exact WorkArea binding and external submission history. WorkOrder is not simply obsolete flight code.
- processing-controller combines managed reconstruction and external inspection/analysis/data workers;
  separation must preserve those independent platform lanes.
- Both MCP adapters use Core authority and durable records; useful reuse candidates, not proof of
  customer-host configuration, vendor support, deployed containment or product acceptance.

## Approach alternatives

1. Recommended: new agent-first assembly, reuse tested platform capabilities, retire acquisition from
   normal routes/dependencies/build with explicit historical read/replay compatibility.
2. Incrementally prune existing assembly: less initial churn, but mixed identity/workflow persists.
3. Full greenfield rewrite: structural freedom, highest risk of losing verified security, numerical,
   lineage/replay/recovery semantics; not recommended on current evidence.

Retain candidates: identity/rights, Site/WorkArea/epoch/revisions, ingress/inspection, data delivery,
fixed analysis, durable jobs/results/evidence, API/MCP, minimal management Console.
Archive/separate candidates: Edge/DJI flight, mission planning/execution, live acquisition/perception,
managed reconstruction and tooling. This candidate list approves NO concrete removal.
Shared domain/contracts/workflow and optional BIM/change algorithms require use-based classification.

## Constraints and outstanding acceptance

Preserve V1/V2 semantics, current authorization/AI egress, exact source/revision/digest bindings,
historical results/journals, finite resources, replay/recovery and truthful typed blockers.
INV-020/024/040/050/051/053/054/055/060/061 constrain migration; acquisition-specific applicability
requires explicit scope mapping, not weakened historical safety rules.
Before destructive moves, a manifest must bind source paths/revision/hashes, disposition, dependency
evidence, tests/build/CI/deployment references, historical read/replay support and rollback.
Private data, credentials, raw HIL and ignored runtime state must not enter a tracked archive.
Permitted real customer exports/rights and actual operational environment remain absent: acceptance
is open, not cleared by a rewrite. No code/schema/config/dependency change, removal, install or delivery.

## Recovery and written-spec stage

- Interruption was a provider transport failure on a skill call; no implementation was lost.
- Revalidated main b27e5d9 and pending discovery ledger; other worktrees unchanged.
- Native goal queried: prior goal unmet/blocked, not active; no resume/create performed.
- Spec proposes archive outside live workspace globs, file-level dependency/hash manifest before moves,
  platform-only assembly, explicit historical readers and separate real-world acceptance gates.
- Self-review: no placeholders, scope contradiction or implicit new endpoint/format support;
  file-level moves belong to the later implementation plan and manifest, not inferred by directory name.
- Independent test-runner `ses_eea4eabe8ffejgpl6xLVPvGPnM`: read-only Git/link/whitespace/status/
  safeguard checks passed. Spec has201lines,9uniqueRB acceptance rows, no placeholders;
  2local links across both documents resolve. No tracked runtime/config/schema/lock delta.
- Spec SHA256 `14ded50b47f2cb363f0ddf1c8edb00d85b147b3de358a38a266a5d63b388a97c`.
  Receipt: `/tmp/opencode/physical-site-rebaseline-spec-verify/receipt.md` (temporary local evidence).
- Runtime tests/builds/customer acceptance not run or claimed. Written-spec approval still required;
  new goal mode proposed for approved cleanup/development only, not created or resumed automatically.

## 2026-10-07 written approval and planning stage (supersedes prior pending status)

- Human: “서면 설계와 목표 모드 사용을 승인합니다.” Approval binds committed72c526b spec
  SHA14ded50b47f2cb363f0ddf1c8edb00d85b147b3de358a38a266a5d63b388a97c.
  Original spec review header is preserved as written-stage history; this approval governs its status.
- Native goal b13320f7-eb7e-448c-b755-e3d3360dca92 created active:14days/1000auto turns/no token cap;
  old ef9e2d2c remains unmet. Goal scope and approval/real-world/external-effect gates are unchanged.
- Planning baseline main72c526b clean; no runtime changes. New dependency findings:
  SiteFrame in mission-contracts, Site AOI in mission-planning; external epoch helper imported via
  acquisition.__init__, which eagerly imports its runtime modules. Neutral extraction precedes moves.
- [Foundation plan](2026-10-07-physical-site-rebaseline-foundation.md) covers first independently
  testable slice: authority/inventory/neutral primitives. Platform-only assembly/archive/UI are dependent
  successor plans, not approved code changes inferred from this planning stage.
- Planning-only draft: `docs/audit/PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv` records2378
  tracked entries at72c526b,194archive candidates and exact destination proposals. No moves permitted
  by these labels; mixed entries require consumer review. Protected rows contain object pointers only.
- Written implementation-plan approval and execution method selection remain pending.

## Foundation plan verification (planning, not implementation)

- Self-review covers the5Review Focus cases and exact neutral type/geometry/epoch interfaces.
  Full RB-01..09 coverage is explicitly staged; first plan does not pretend to finish runtime/archive/UI.
- Independent test-runner `ses_eea290cb6ffefEUGm3wz5nx4kt`, commands
  `python3 /tmp/opencode/physical-site-foundation-plan-verify/verify_csv.py` and `verify_paths.py`:
 20/20CSV checks passed;2378unique baseline rows,194candidates,82protected pointer rows,
  2296nonprotected blob hashes match;23modify/9existing test-tool/9create paths reconcile.
- Three local links resolve; Git scope/status checks pass; approved spec hash unchanged.
  Original `git diff --check` covered tracked changes only; the then-untracked CSV was not included.
  Foundation plan SHA256`fdfe035d5109aa86d26c8fc44c58d210f4c5e11c46ca4d0d9fe92a50d5c4794b`;
  Original CRLF CSV SHA256`92ad04350b2fe4a02106d30764c6c8c6f4c10193a6af36322cafadfe3279c1d0`.
- Receipt/scripts under `/tmp/opencode/physical-site-foundation-plan-verify/` are temporary local
  verification witnesses, not customer/runtime/build evidence. No product tests/build/GUI run here.
- No source/schema/config/lock changes; inventory is planning-only. Proceed only after plan review;
  recommended sequential developer/reviewer method, final independent test-runner.

## Staged whitespace correction

- `git diff --cached --check` returned2 with2379CSV trailing-whitespace findings before commit.
  Root cause: standard-library CSV default CRLF, not changed paths, classification or content hashes.
- Converted only CSV line endings to LF; parsed header and all2378data rows are identical.
  New CSV SHA256`89a9baf3b1f1a593bf65af02810595cea0f677a740ceb0fdf9f2e789071639e3`.
  Diagnostic witness: `/tmp/opencode/physical-site-foundation-plan-verify/newline-repair.json`.
- Independent runner `ses_eea290cb6ffefEUGm3wz5nx4kt` rechecked the staged artifacts:
  `git diff --cached --check` and `git diff --check` exit0; working files equal the index;
  `python3 /tmp/opencode/physical-site-foundation-plan-verify/verify_csv.py` passes20/20 with
  all2296nonprotected blob hashes verified,2378unique paths and194archive candidates. CSV has no CR;
  all3links resolve; staged scope is exactly3planning docs. Receipt: `receipt-staged.json` in the
  same temporary evidence directory. Prior receipt is retained with this explicit correction.
- This correction changes neither approved spec nor foundation plan, and authorizes no implementation.
  Written-plan approval and method selection remain the next Human decision; no product completion.

## 2026-10-07 foundation execution approval (supersedes pending gate above)

- Rendered Human decision: “승인·분리 실행 (Recommended)” for the foundation plan at738b4a9.
  Plan SHA256`fdfe035d5109aa86d26c8fc44c58d210f4c5e11c46ca4d0d9fe92a50d5c4794b`.
  Sequential developer per task, fresh task reviewer, Primary integration/Git, independent final
  test-runner. Scope remains Tasks1–4 only; no physical archive/removal or visual implementation.
- Workspace/base/local target: existing current checkout/main738b4a950e6b202a3a65982cea570e3a2ba4c8b7;
  one writer at a time. Other worktrees untouched. Native goal b13320f7 remains active/full-scope.
- Applicable stages: subagent-driven-development, TDD, using-git-worktrees safety checks,
  verification-before-completion; independent reviewer/test-runner. No new model choice or installation.
- Ruling: use the approved current checkout, not a new worktree — adopted single-writer workspace
  policy and written spec explicitly choose current main; no concurrent implementation or checkout
  protection need. If wrong, task-owned local commits can be reversed through a reviewed inverse change.

### Preflight task/interface scan

| Tasks | Producer/consumer or internal check | Finding / handling |
| --- | --- | --- |
| 1 | Authority routing tests vs ADR039/docs; unchanged historical evidence vs new responsibility | Coherent; distinguish historical applicability from current runtime removal |
| 2 | Frozen CSV vs validator and hostile fixtures | Coherent; baseline is72c526b even after new commits; validate Git blobs, not changing checkout bytes |
| 3 | Neutral types/epoch helper vs exact aliases and wire/replay tests | Coherent; new module ownership must enter existing module inventory; old dependencies remain until successor |
| 4 | Task1–3 integrated evidence vs whole-cleanup acceptance | Foundation-only technical evidence; no RB-03..09/customer closure claim |
| 1 → 2 | Current responsibility vs candidate group explanations | No blanket archive authority; frozen inventory is an input, not a move list |
| 1 → 3 | Approved platform boundary vs shared primitives in historical flight packages | Preserve class/module identity, serialized fields and exact epoch bytes |
| 2 → 3 | Baseline hashes vs legitimate extraction edits | No stale-working-tree comparison; future move manifest needs a fresh revision/hash |
| 1/2/3 → 4 | Durable task evidence, current revision and affected tests/builds | Shared ledger/checkpoint only Primary writes; final independent checks target integrated state |

### Implementation contract before source changes

Requirement IDs: RB-01 and inventory part of RB-02; preserve SDP-REQ-01/02/04/06 and INV-020/024/040/050/051/053/054/055/060/061.
Owner module: product/governance docs; tools/tests; event-contracts/geo-core/Core observations.
Acceptance criteria: approved foundation plan Tasks1–4; target responsibility aligned, baseline inventory fail-closed, neutral primitives exact and independently verified.
Contracts affected: no new public wire contract; unchanged SiteFrame/AOI serialization and ObservationEpoch identity; invariant applicability annotations only.
Reference assets: current KSI-owned source/tests and frozen CSV; reference submodules remain read-only and untraversed.
Adoption decisions: RETAIN existing verified platform behavior; EXTRACT shared primitives; label acquisition historical/out-of-product without moving sources.
Files to change: exact Task1/2/3 file lists in approved foundation plan; Primary-only ledger/checkpoint/cache.
Tests: scoped red/green + normalization gates, geometry/Site/external epoch/replay, static/lock/package checks; independent integrated final suite.
HIL or real-device assumptions: none; no device/vendor/field support claim.
License/data implications: existing owned code only, no new dependency versions or customer samples; protect private state and original rights.
Rollback: reviewed inverse of task-owned commits only; no journal/schema migration, reset, broad cleanup or source moves.

### Execution progress

- Task1: started at738b4a9. Baseline `.venv/bin/python -m pytest tests/contract/test_repository_normalization.py -q`:17passed, exit0.
- Tasks2–4: pending; plan approval remains valid without per-task confirmation.

Current execution checklist (supersedes the dated start line above):
- [x] Task1 authority alignment — reviewed and independently verified at085144f.
- [x] Task2 frozen disposition — reviewed and independently verified at99bf45d.
- [ ] Task3 neutral primitives/epoch identity.
- [ ] Task4 integrated foundation verification/successor planning (whole goal remains open).

### Task1 review/fix round1

- Developer `ses_eea043ab5ffe8W2QLJVJrLesFn`, commit37efe3b:18docs/test files; author RED4failed,
  GREEN4passed; boundary+normalization21passed, validatorPASS, Ruff clean; phase2 journey1passed.
- Reviewer `ses_ee9fbc1d8ffeRi2mFB6qZ6qAM4`: routing/preservation safe; fix required for16/18
  excluded IDs and checking historical Milestones rather than each current Next-slice marker.
  Current report is not integrated verification. Primary records commands here; final independent
  runner will check the actual revised source. Author red receipts need retention in scratch evidence.
- Primary confirmed additional load-bearing gaps in actual authority: Constitution still defines
  only external reconstruction data; PRD§23.1 still says autonomous patrol is this product's duty,
  §3/§25/§26 leave flight goals/long-term completion active. Correct within approved RB-01/Task1 scope.
- Primary confirmed shallow-CI risk: checkout uses default fetch depth while new tests call
  `git show 738b4a9`. Freeze baseline section/status digests in the test instead; no history/network
  prerequisite and no permissive skip. This preserves baseline comparison without copying old data.
- Ruling: keep external reconstruction release open as KSI derived-result ingress/inspection/customer
  acceptance only, not customer reconstruction execution — ADR036/approved spec preserve these gates.
  Acquisition-only TrackA/B must be explicitly out-of-product in Next slices despite BLOCKED history;
  blocked alone does not remove a future product obligation. If wrong, only task-owned applicability
  notes/tests need inverse correction; historical status/acceptance and runtime remain untouched.

### Task1 technical closure / Task2 handoff

- Fix commit085144f followed scoped re-review by `ses_ee9fbc1d8ffeRi2mFB6qZ6qAM4`: all important
  findings addressed, no new Critical/Important issues. Native Git-history dependency removed from
  tests;20excluded future items checked per Next-slice line; Physical Site definition shared by
  Constitution/PRD; current acquisition-only responsibilities/completion marked historical.
- Independent test-runner `ses_ee9ef4120ffeFcMTR2E9994ctv` at085144fdab3c813daa201bff64ba2e140696fc2f:
  `.venv/bin/python -m pytest tests/contract/test_physical_site_product_boundary.py tests/contract/test_repository_normalization.py tests/contract/test_phase2_unified_journey.py -q`
  →46passed/0failed/0skipped/0warnings. Normalization validatorPASS, changed-test RuffPASS,
  `git diff --check`exit0, no introduced broken links. Independent baseline738b4a9 check confirms
  original milestone/current-slice digests and all34registry status/state entries match.
- Required original spec/plan bytes unchanged. No runtime/schema/lock/UI edits or path moves.
  Receipt and exact files/commands: `/tmp/opencode/physical-site-foundation-task1-verify/receipt.json`.
- Task1: complete technically (commits738b4a9..085144f, reviewed and independently checked).
  Whole RB-01..09 cleanup, customer acceptance and external delivery remain open; final Task4
  still checks integrated foundation revision. No claim that archive/assembly/Console is complete.
- Nonblocking review observations retained for final review: author fix1 witness labels base37efe3b,
  resolved by actual independent head085144f receipt; END-OF-PRD fallback over-binds the preserved
  governance-section digest (may be narrowed to next top-level section if future authorized PRD edits).
- Next Task2 owns only frozen-inventory validator/tests/companion report. It consumes ADR039 and
  unchanged baseline72c526b CSV; neither current authority nor Task1 tests are its edit targets.

### Task2 review/fix round1

- Developer `ses_ee9e6c75effeJumGp4R6KL7idx` commit0285448:3new files. Author tests7passed,
  normalization-adjacent24passed; real CLI exit0, hostile digest CLI exit1; Ruff/format/whitespace clean.
- Reviewer `ses_ee9dad85cffe8XUxw0e5hL8VES`: safe no-move/protected-metadata-only structure;
  Important malformed UTF8/CSV error paths escape promised list-of-findings interface. Add controlled
  failure mapping and tests; batch failures/uninitialized gitlinks/symlink/header coverage noted.
- Primary confirmed CI integration blocker at test145–149: real CSV test requires old Git objects,
  but `.github/workflows/ci.yml` gates checkout has default depth1. Author shallow-CI claim was too broad.
- Ruling: keep the fail-closed CLI's full-history prerequisite and independently run its real2378-row
  verification locally; make always-running pytest coverage use immutable real-CSV hash/structure pins
  plus real local Git fixtures for validator binding semantics. No CI fetch/install/config changes or
  silent skip; prove the pytest file works in a minimal shallow local clone with no old baseline object.
  If wrong, a fixture/CSV regression could require a stronger CI maintenance gate; standalone real-object
  verification remains mandatory for this slice and is not relabelled as shallow-CI object verification.

### Task2 technical closure / Task3 handoff

- Fix99bf45d and scoped re-review `ses_ee9dad85cffe8XUxw0e5hL8VES`: all required findings
  addressed, no new Critical/Important issue; controlled malformed CSV/UTF8/Git error findings,
  trusted protection boundaries, symlink linktext and absent foreign gitlink coverage. CLI still
  verifies full frozen objects without executing moves; pytest never skips for absent old history.
- Independent runner `ses_ee9c83fb8ffeS6oza1KzEMmaIV` at99bf45d1a0c7d50b63ce8be6ee69d58503f8e17b:
  `.venv/bin/python -m pytest tests/contract/test_physical_site_disposition.py tests/contract/test_repository_normalization.py -q`
  →29passed/0failed/0skipped/0warnings (12+17). Both disposition CLI on actual CSV and normalization
  validator exit0; Ruff check/format and tracked/index whitespace checks exit0.
- CSV SHA89a9baf3 unchanged;2378unique rows exactly match baseline72c526b tree metadata,
  194candidate destinations/conditions and82protected pointer rows. Real CLI validates all
  nonprotected frozen blob digests; no protected content or symlink targets traversed. Spec/plan unchanged.
- Minimal prepared shallow checkout, required3file hashes equal99bf45d and72c526b absent:
  absolute existing `.venv/bin/python -m pytest .../test_physical_site_disposition.py -q`
  →12passed/0skip. Hostile digest copy CLI exit1; real CSV unchanged and no archive created.
  Receipts/exact commands/files: `/tmp/opencode/physical-site-foundation-task2-verify/` files00–18.
- Reviewer Minor arithmetic ruled resolved from independent result: old24included7old+17normalization,
  final29is12new+17. Missing combined author log is superseded by fresh independent run, not inferred PASS.
- Task2 technically complete at0c12b2b..99bf45d (3owned new files). Per-file consumer/move closure
  remains explicit successor work; candidates/RECONCILE are not move or delete approval.
- Task3 consumes unchanged authority/CSV. It owns plan-listed neutral SiteFrame/AOI/epoch extraction,
  direct dependency/lock/module-inventory and README changes. Preserve old aliases and literal wire,
  schema, geometry and epoch vectors; no app-factory redesign, journal migration or archive move.
