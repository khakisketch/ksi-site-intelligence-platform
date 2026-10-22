# Agent-first platform rebaseline — discovery ledger

Date: 2026-10-07
Status: Foundation reviewed/independently checked with broad type gate open; P2 written-review pending
Base / proposed local target: main b27e5d94b04d11e155e41d8df94c70519808a976
Workspace: current checkout, one writer; other worktrees retained unchanged.
Prior unmet goal remains closed; Human-approved new goal b13320f7 is active.

> 2026-10-14 routing note: pre-2026-10-09 wording in this ledger's header/early foundation sections
> (planning-recipe and execution-method choices, delegated Developer/Test Runner/Reviewer/CE seats,
> goal-mode notes) is dated history under `2026-10-09-site-harness-mapping.md`. Current approval and
> progress live in the dated sections below and in Git; references to retired roles anywhere in this
> ledger are historical evidence, not current execution steps. Originals remain unrewritten.

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
- [x] Execute foundation stages and record independent integrated checks; broad type gate remains open.

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
- [x] Task3 neutral primitives/epoch identity — reviewed; integrated source/installed evidence atf12857c.
- [x] Task4 integrated checks/successor handoff recorded; broad type gate unpassed, whole goal open.

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

### Task3 implementation checkpoint and bounded continuation

- Developer `ses_ee9c248b9ffecm5ogk69JOhXn9` started atf44175b, stopped at harness step limit,
  not a product blocker.17task-owned files pending (13modified/4new), no commit or lock refresh yet.
  Author reports new22tests GREEN, scoped215passed, geometry/signature168passed; these are
  implementation-state reports, not independent integrated evidence. Retained witnesses in task3-logs.
- Primary inspected actual diff: mechanical AOI copy and exact legacy alias, neutral epoch helper,
  Site/ingress import swaps, dependency/README/inventory updates; no physical archive/move.
- Ruling: also declare direct `ksi-event-contracts` in mission-contracts/pyproject.toml. The required
  legacy SiteFrame re-export now imports that package; undeclared reliance on the root all-packages
  environment would break installed consumers. This adds an existing workspace dependency only,
  not a new third-party version or product contract; lock/package closure must confirm it.
- Exact-config discrepancy found before commit: event-contracts `_CamelModel` adds
  `allow_inf_nan=False`, unlike the captured original SiteFrame config. “No float fields” is not
  exact configuration preservation. Use a neutral self-contained BaseModel config identical to the
  legacy class and assert the complete captured config, rather than silently accepting a delta.
- Continuation contract: finish only remaining Task3 verification/lock/self-review/report/commit;
  pin captured AOI/GeoPoint schemas in durable tests, modern fresh-process denial for neutral
  acquisition/mission imports, ingress acquisition denial separately. No broader digest/app rewrite;
  transitive ingress signing/helper flight coupling belongs source-bound successor planning.

### Task3 review / Task4 integrated verification handoff

- Developer bounded continuation `ses_ee9c248b9ffecm5ogk69JOhXn9` completeda47fa7f,18ownedfiles:
  neutral SiteFrame/AOI/epoch, legacy aliases, Site/ingress imports,3existing workspace dependency
  edges, moduleinventory and READMEs/test/lock. Exact-config delta corrected before commit.
- Fresh reviewer `ses_ee9b04bf3ffejhr9jbjCViYezl`: SpecPASS/qualityGOOD, no Critical/Important.
  Independently compares original geometry→newgeometry (import reorder only),3literal epoch
  SHA256 vectors,5-key original model config,6added lock lines/no third-party drift and legacy chains.
- Evidence limits: initial RED file retains only14FAILED lines and22failed summary; reasons for
  two owner-independent test failures not retained. Do not claim a fully witnessed22-case TDD run.
  Author217scoped/213geometry and uv/Ruff prose lacks full receipts; independent Task4 will run
  current exact commands and a clean test-only pre-extraction control where feasible (no runtime revert).
- Ingress runtime closure witness now reports no acquisition/mission/flight imports. This narrow
  ingress result does not prove app, workers, signing helpers or complete installed Core independence.
- Task3 source review complete atf44175b..a47fa7f; technical milestone remains pending independent
  integrated checks. Primary checkpoint/status corrected from “uncommitted”; only this ledger is pending.
- Task4 independent runner owns scratch/evidence only: new foundation/scoped histories/OIDC/data/MCP/
  real inspection Analysis + affected replay/full configured Python suite; static/lock and local built
  artifact/source closure using existing isolated Hatchling, without installs into shared environments.
  Full RB-03..09, physical archive, Console, real customer/operational acceptance remain open.

### P2 source-bound plan prepared during Task4 verification

- Draft [Platform Core assembly](2026-10-07-platform-core-assembly.md) binds maina47fa7f and9
  load-bearing source SHA256 snapshots. Four tasks: exact neutral payload helpers; explicit external-only
  graph/routes; fail-closed separate production entrypoint without flight credentials; actual generated
  HTTP/worker/history/revocation and independent closure. Current managed assembly and journal bytes stay.
- Planning-only Primary self-review covers spec/requirement staging, exact existing types/functions,
 5Review Focus cases,4task producer/consumer interfaces, existing test paths, no placeholders and deferred
  worker/build/archive/Console gates. Read-only receipt/script: `/tmp/opencode/physical-site-core-plan-self-review/`.
- Probe correction: initial verifier's case-sensitive `real customer` failed against actual `Real customer`
  wording; casefolded verifier fixes its own guard only. No plan/product semantics changed to hide a defect.
- P2 is written-review pending, not successor implementation authorization. Preserve Human's already
  selected sequential developer/reviewer method; request only this dependent plan's scope/behavior review.
- Final foundation reviewer `ses_ee996b6baffecEQk6xj8FS5Ayw` reviews actual738b4a9..a47fa7f separately
  from runner `ses_ee9a885b6ffeulMkKsll8Ao9Df`. Both own scratch only; no duplicated suite or concurrent code.

### Final foundation review adjudication (independent verification still pending)

- Full report `final-review.md` read: entire7commit/40file diff inspected, specPASS/qualityGOOD,
  no Critical/code Important. Its Important is the existing Task4 integrated evidence gate, not a new
  implementation defect; keep milestone open until independent results. Reviewer accepts but independently
  assesses shallow-CI split, direct legacy dependency and exact SiteFrame config rationale.
- Report sometimes cites review-package line offsets as source lines. Primary resolved actual loci:
  `test_physical_site_product_boundary.py:235` EOF fallback; `sites.py:30,486` old-owner docstrings;
  validator`:257` field stripping; disposition test`:20` global import path addition.
- Ruling: defer these4Minors to their next owned change — EOF section pin is overly broad but preserves
  current evidence; old module remains a working alias; padded fields still bind exact frozen objects in
  a no-action validator; pytest path pollution has no observed failing flow and fresh-process isolation
  tests do not rely on it. Changing tested source for polish would require another affected revision check.
  Cost if wrong: broader future PRD pin/incorrect owner guidance/too-tolerant padded inventory input or
  sibling-test contamination; retain explicit follow-up, no security/contract weakening authorized.
- Receipt Minors: initial full22caseRED remains unknown, never retroactively asserted. Current24GREEN
  and independent literal evidence are distinct. Missing scoped/static prose is addressed only by fresh
  Task4 current-revision checks, not by accepting author numbers.
- Cannot-verify routing: current tests/static/lock/build and actual CSV/object check→Task4 runner;
  per-path move consumer closure→P3 (current companion provides group evidence, not actionable moves);
  original completeRED→unrecoverable historical witness limit, nonblocking current technical evidence.
- Declined-to-judge disposition: P2 draft→Primary written-plan self-review/Human gate; working ledger→
  Primary+independent docs delta verification; Task4→runner; customer/device/HIL/containment→open external
  gates; runtime/worker/archive/Console→successors; protected inputs→never inspected or copied. Narrow
  ingress import closure is not app/package independence. No visual output is claimed in this slice.

### Task4 partial independent evidence / bounded continuation

- Runner `ses_ee9a885b6ffeulMkKsll8Ao9Df` completed A/B at actualmaina47fa7f/tree836f3478 before
  harness step-budget stop. This is not a pytest failure or product blocker; remaining C/D are unrun.
- Primary inspected actual logs: scoped93files `.venv/bin/python -m pytest -q -p no:cacheprovider`
  (argv `filelists/batchA-argv.txt`)→2159passed/53warnings/exit0; bare configured
  `.venv/bin/python -m pytest -q`→9092passed/122skipped/102warnings/exit0 (1046.35s).
  Process-localumask022/HOME=/home/ksi/PYTHONDONTWRITEBYTECODE=1; logs0600. Receipt root:
  `/tmp/opencode/physical-site-foundation-final-verify/`, logs`batchA-pytest.log`/`batchB-fullsuite.log`;
 18ownedTask3SHA256 snapshots in`source-snapshots/task3-sha256.txt`.
- Scope includes actual inspection Analysis/MCP, external history/OIDC, data/replay, signature/geometry
  and module inventory. The configured active tests include retained managed packages/services; no
  scope reduction or HIL/real-model/host acceptance inferred from122skips. Warning categories include
  ifcopenshell destructor/fork deprecations, not silently counted as new code failures or removed.
- During A/B, Primary authored the P2 plan and ledger only; runner explicitly observed that untracked
  doc change. Tracked runtime/tests/lock remain the tested revision; no P2 implementation ran.
- Resume contract C only: write durable scratch A/B partial receipt first, run remaining static/lock/
  inventory/mechanical source checks with full logs; do not re-run passed A/B or include build work in
  the same oversized assignment. D follows separately using existing prepared isolated builder.
- Independent P2 planning checker `ses_ee990eea8ffeug2pzaFxffW7A6` similarly stopped at step budget
  after matching9hashes/18existingtests/5proposedtests/currenttypes/helpers/byteoracle. Its receipt and
  remaining named-route enum checks are incomplete; prose PASS does not close this documentation check.
  Resume only those remaining checks+receipt, with no full foundation suite duplication.

### Task4 C-stage finding adjudication / final fix1

- C1Ruff/lock/frozenCSV/normalization/Core180records/whitespace pass; actual receipts
  `receipts/batchC-receipt.md` and `logs/C1-ruff.log`..`C8-independent-source-checks.log`.
  Byte/config/geometry comparisons and18Task3hashes remain unchanged. BatchD is not yet run.
- Broad `.venv/bin/mypy packages services tests tools` exits2: unresolved flat`customer_v2`
  helper and new standalone validator's duplicate module mapping; scope-with-consumer-tests exits1
  for flat`_site_lifecycle`. Neither command is a PASS, even if Task3 modules show no diagnostic.
- Ruling: reject runner's blanket “pre-existing/notTask3, do not fix” classification for duplicate
  validator mapping. Foundation contains Task2 too; tool/test were added in0285448 and CI's exact
  target command detects the new namespace edge. Correct this introduced defect within approved scope.
  Missing flat helpers are separately evaluated against unchanged pre-foundation source, not assumed
  new or fixed by changing CI flags/ignores. If wrong, only the small test import amendment costs rework.
- Cause: root`tools/` standalone discovery and new static`from tools...` import give one source two
  mypy names. Existing normalization test dynamically imports its tool. Use that compatible loader
  pattern and restore/avoid global`sys.path` mutation, which also closes final-review Minor4.
- Fix contract: only disposition test loading + fresh-process path-preservation regression;
  exact validator/CSV/hostile semantics remain. Capture duplicate/static and path-leak RED before
  correction, GREEN/scoped/shallow checks after; full final independent suite belongs Task4 at new head.
  Brief `final-fix-1-brief.md`; no P2 or UI/runtime/CI/config/manifest change. No full-suite re-run at the
  old revision simply to recover a step budget; revision-affecting fix requires fresh final evidence.
- P2 planning checker bounded resume completed17/17source/path/type/route/interface/scope checks,
  SHA0aa779b4 unchanged. Receipt `/tmp/opencode/physical-site-core-plan-verify/receipt.md`;
  written-plan validation only, not Human approval or runtime evidence.

### Final fix1 revision / remaining independent checks

- Task2 developer `ses_ee9e6c75effeJumGp4R6KL7idx` committedf12857c (one disposition test file,
 55added/10removed): dynamic file-location loader, no global path insertion; original12hostile/pin
  tests remain and one fresh-process path-preservation check added. Type annotations only elsewhere
  in that test. No tool/CSV/CI/runtime/lock/P2 change.
- Author completeRED duplicate diagnostic/path-leak witness→GREEN scopedmypy2files,30pytest
  (13+17), shallow13/0skip, Ruff/format/whitespace. Full witnesses`final-fix1-logs/` and report read;
  these author checks are not independent final completion evidence.
- Scoped final-review resume `ses_ee996b6baffecEQk6xj8FS5Ayw`: duplicate finding ADDRESSED and
  previousMinor4 ADDRESSED; no new Critical/Important. Report`final-fix-1-review.md` read. Remaining
  Minors1–3 and historicalRED receipts stay explicitly scoped/deferred; unrelated normalization test
  path insertion is not silently “fixed” by this change.
- Final independent contract: runner tests/static at integratedf12857c, fresh full configured suite
  because a shared test import changed; passeda47fa7f93file/scope result remains historical, not re-run
  by budget recovery. Another test-runner owns only independent offline package D closure. Separate
  scratch ownership, no product writers or suite duplication; local-wheel isolated target only and
  existing builder/third-party environment, no new dependency installation/network/production switch.
- If broad mypy still fails on unchanged flat fixture imports, preserve exact current diagnostics and
  baseline file hashes, verify task-owned scopes independently and report the gate as unpassed. Do not
  infer failure-free CI or widen this foundation fix into unrelated customer-fixture refactoring.

### Finalf12857c independent tests/static received; package harness recovery

- Runner `ses_ee9a885b6ffeulMkKsll8Ao9Df`, receipt`receipts/E-final-receipt.md` read:
  scopeddisposition/normalization30passed/0skip/warning; bareconfiguredfull9093passed/122skipped/
  102warnings,exit0 (1038.11s). One additional test is the path-preservation regression; old9092
  remains oldrevision evidence. HEAD/tree145cd2c and18Task3hashes unchanged pre/post.
- All12foundationchanged Python files independently pass scopedmypy; broadRuff, offline162package
  lockcheck, actual2378row frozenCLI, R0–R3normalization/Core180record gates and whitespace pass.
- Broad unchangedCI mypy now completes instead of duplicate-module abort:109errors/14files,
  checked1012,exit1. Primary read actual full log.14diagnostic files hash-identical to738b4a9 and
  none foundation-owned; categories include flat imports, missing annotations, duplicate fixture
  definition and dict/argument typing. This supports inherited-issue triage but file-hash identity
  alone is not a historic same-environment diagnostic comparison. Broadgate remains unpassed;
  no claim of zero regressions/all109baseline diagnostics conclusively re-run. No global ignore added.
- Package runner `ses_ee97a5c02ffeboH75jXBcHuTB8` stopped after its own verifier crash:
  sixoffline sdist/wheel builds andfour sdist→wheel rebuilds exit0, outputs/logs preserved at
  `/tmp/opencode/physical-site-foundation-package-verify/`. Source/archive/install proof still pending.
- Primary inspected driver, finding verification-harness defects before replay: leftover `.decode()`
  onstr; wrong source/wheel/sdist relative-key mapping; empty RECORD hash needs bounded handling;
  a deny-all probe cannot then import the deliberately denied legacy modules. Comparisons must fail
  the verifier, not merely print mismatches. These are not observed product/build failures.
- Recovery contract: preserve completed10build commands/artifacts andresume only verification/install/
  separatefreshneutral, ingress and legacy probes. Correct scratchdriver andretain full receipts before
  stopping; no rebuild/replay, product source/CI/lock mutation, network or shared dependency install.

### Foundation technical handoff (not whole-goal/product acceptance)

- Package runner `ses_ee97a5c02ffeboH75jXBcHuTB8` completes D at
  `f12857c7f178967017458057d4fd59538ff091bd`. Six packages built offline sdist+wheel;
  four changed wheels rebuilt from sdist, all ten commands exit0 without build replay after
  harness repair. 360 source files (354 Python modules and six `py.typed` markers)
  match source/sdist/wheel bytes. Direct RECORD
  hashes/sizes validate; the four rebuilt RECORD hash maps equal direct wheels.
  All18Task3source hashes remain unchanged. Receipts/scripts/command logs:
  `/tmp/opencode/physical-site-foundation-package-verify/receipt.md` and `receipt_supplement.md`.
- Build command shape from retained logs: `uv build <package> --python <prepared-builder>
  --no-build-isolation --no-sources --no-config --no-python-downloads --offline
  --out-dir <owned-output> --sdist --wheel`; each of domain/event-contracts/geo-core/
  mission-contracts/mission-planning/Core has its own exact argv and exit receipt.
  Existing builder: Python3.12.13/Hatchling1.32.4; uv0.11.15. No shared environment mutation.
- All six METADATA workspace edges equal current lock. Core still has seven workspace
  dependencies including mission-contracts/mission-planning/equipment-intelligence;
  build success does NOT establish platform-only runtime or build independence.

Built wheel SHA256s (all version0.0.1, `py3-none-any`; temporary artifacts, not published):

| Wheel package | SHA256 |
| --- | --- |
| ksi-domain | `b864ee823ee494c28e6068c3af8b7a3e5914a936c9be68c58c916e24f9772b2f` |
| ksi-event-contracts | `175b1f6e8de27168eb3b1b938b684404555474b5eb9b984be517bbf34cfee570` |
| ksi-geo-core | `96fb705913b586965fb6c23002cff6140a93199d1693f0f7b0f1ece56a6686c3` |
| ksi-mission-contracts | `6df10397990cbcf0b7ec5ec140cfd9ff5c005d21c6d0694e5d66857f32f76435` |
| ksi-mission-planning | `0545e14dc5c72ac4ae8d52dcacf5399f9acded72581d05fcd7b7199e61cd48b6` |
| ksi-core | `966c84b1c4d43875094c3bbcaa23a09ee47302fc88dfa90918755d35a05db8d6` |

- Installed only these six local wheels offline/no-deps/no-index into a new verified-empty
  owned target, using existing root third-party dependencies read-only. Fresh `python -I`
  neutral probe denies acquisition+mission; ingress probe denies acquisition. Exact wire,
  schemas, area and epoch vectors are preserved, with changed modules resolved from the target.
- Primary inspected actual scripts and corrected the initial “both orders” overclaim:
  the first legacy probe reused cached imports. Two supplemental distinct fresh `-I` children
  now prove neutral→legacy AND legacy→neutral; every SiteFrame/AOI/epoch and legacy
  geometry/models/readiness module resolves inside the installed target. Aliases/helper limits
  and exact five-key SiteFrame config hold. `receipt_supplement.md` distinguishes the three
  original probes from the two fresh-order probes. No rebuild/reinstall/product mutation.
- Evidence limits: existing third-party/unchanged editable-site dependencies may resolve other
  modules. No self-contained production image, platform-only boot, customer/vendor/host/device/
  accuracy acceptance. Five source READMEs occur in sdist/not wheel; mission-planning has none.
  Supplemental empty directory hashes are NOT file evidence; use source/archive/RECORD and
  actual module-origin checks above. Broad mypy remains failed; all109diagnostics have not
  been independently reproduced on the pre-foundation environment merely by comparing file hashes.
- Foundation implementation/review/integrated checks and supported artifacts are recorded;
  original spec/plan/CSV bytes are unchanged. Approved scope covers RB-01 and the inventory
  portion of RB-02 only. RB-03..09 retain runtime, historical-reader, worker/archive/CI/UI/customer
  gates. Full Python9093passed/122skipped/102warnings; changed12Pythonfilemypy/Ruff pass;
  global mypy109errors/14unchangedfiles remains explicitly unpassed. No whole-goal completion.
- Remaining nonblocking Minors: boundary-test EOF overbinding; Site AOI old-owner docstrings;
  validator padded-field normalization. Disposition-test global path leak and duplicate static
  identity are fixed. Original full22caseRED remains historical unknown, not reconstructed.
- Successor P2 plan rebound to actualf12857c (nine runtime hashes unchanged), with status-only
  disclosure; final document hash/delta verification follows below. Proposed scope: neutral digest
  helpers → external-only graph/WorkOrder admission → separate fail-closed production entrypoint
  without Mission key/device prerequisites → generated HTTP/worker/replay proof. Keep current
  managed entrypoint/records; no physical archive/UI/deploy. Human written-plan review is required
  before implementation; already-selected sequential developer/reviewer method is preserved.
- Product-state receives only approved bounded-work linkage. CurrentSlice/EXT-VAL/milestones/
  customer acceptance are NOT closed or reprioritized. Native goalb13320f7 stays open; prior goal
  is not revived. Local code is committed atf12857c; task-owned evidence/plan docs are pending commit.

### Written-plan handoff verification and approval waiting

- Final P2 draft SHA256 is
  `7b9c470b0651ba44e8e09e95c53d6a0d00e9eef8364f5fdfae69e5dda1f8974d`.
  Independent doc runner `ses_ee9429a44ffePCh0H75ziEw1bF` verifies its nine source hashes,
  four tasks/five Review Focus cases, new-file targets, deferred scope and written-review gate.
  Replacing only its Status line with the exact prior text reproduces independently verified
  SHA0aa779b4; no implementation requirements changed in the baseline/status update.
- Final staged scope: this ledger, disposition companion, product-state linkage and new P2 plan.
  Approved spec/plan/CSV hashes unchanged; added links resolve; product-state Archive-onward,
  Milestones and Current slice remain byte-identical to f12857c. No runtime/tests/lock change.
- Doc-gate command `.venv/bin/python -m pytest -q -p no:cacheprovider
  tests/contract/test_physical_site_product_boundary.py tests/contract/test_physical_site_disposition.py
  tests/contract/test_repository_normalization.py` →58passed, exit0, no skips/warnings.
  Receipt: `/tmp/opencode/physical-site-foundation-doc-handoff-verify/receipt.md`.
- Doc verifier step limit first exhausted on recovering a known Status string; bounded continuation
  used the actual prior line rather than snapshot/object-store exploration. This was a handoff issue,
  not a product failure, and did not warrant full-suite/build replay or another scope.
- Count correction: D's `srcfiles` metric counts all non-cache source files, not only Python.
  Actual counts11/55/10/11/8/265 total360; Python10/54/9/10/7/264 total354, plus one `py.typed`
  per package. Corrected the ledger's inaccurate “360 Python modules” label. The active verifier
  is `verify.py` (all source files), not the failed original `driver.py`; original package bytes
  are unchanged. The same independent doc runner confirms the corrected360/354+6 counts,
  receipt equality, staged scope/whitespace and administrative handoff delta; prior58testPASS
  and the other32checks are retained. This closes the count assertion, not the broad type gate.
- Final-review Important “integrated evidence pending” is resolved by E/D checks and this handoff;
  this is not a claim that the failed broad type-check gate or customer/product acceptance passed.
  No new task-owned code finding remains; Minors/receipt limits above are retained.
- Stop/next contract: after local task-owned docs commit, wait for Human written review of P2's
  opt-in runtime/profile behavior, using the already-approved sequential execution method.
  No automatic P2 source changes, repeated probes, goal closure or inferred archive/UI/deployment
  authorization. Real customer data/rights/operations and broad type diagnostics remain open.

### P2 written approval and execution start (2026-10-08)

- Human approved the Core assembly plan at its committed SHA
  `7b9c470b0651ba44e8e09e95c53d6a0d00e9eef8364f5fdfae69e5dda1f8974d` (main15ed73e) with the
  already-selected sequential developer/reviewer/independent-runner method
  (rendered decision “계획 승인·기존 방식 실행”). Approved scope/behavior is the plan as written:
  neutral digest helpers; opt-in external-only platform graph/routes; omitted or managed
  WorkOrder mode rejected422`EXTERNAL_RECONSTRUCTION_REQUIRED`; separate fail-closed production
  entrypoint without Mission key/device prerequisites; generated HTTP/worker/restart evidence.
  Excluded: physical archive/removal, UI/Console, deployment, credentials, new dependencies.
  Broad mypy109errors/14unchangedfiles remains open and is not a P2 gate.
- Execution workspace: current checkout/main, one writer (foundation workspace ruling extended;
  no new worktree, per spec §8 “Local target remains current main”). SDD workspace
  `.superpowers/sdd/2026-10-07-platform-core-assembly/` holds the preflight scan table and
  per-task dispatch ledger; durable decisions stay in this ledger.
- Task1 “Exact neutral serialization helpers” dispatched after plan approval; base15ed73e.
  Tasks2–4 remain pending; no source change occurred before this approval entry.
- Task1 complete: developer `ses_ee91b7661ffefnxY64lz9z3c35` committed `f7779e9`
  (`refactor: share exact payload digest helpers outside flight`;8owned files). Byte-exact
  relocation to`ksi_domain.signed_payload`; legacy`ksi_mission_contracts.signing` re-exports the
  same function objects;4Core consumers swapped only after confirming real use; oracle/Unicode/
  error-type vectors, fresh-process deny-hook and identity tests. Author evidence: RED10missing-
  module→GREEN scopedmatrix343pass; Ruff/mypy scoped clean; no lock change. Task reviewer
  `ses_ee8e9cc8affeVoEzHecYaKj1Ed`: specPASS/qualityApproved, noCritical/Important;2Minors
  deferred (consumer docstring still cites legacy path; one `.encode()` default-arg inconsistency).
  Full suite/static remain Task4; commit`15ed73e..f7779e9` is task-owned. Dispatch cache:
  `.superpowers/sdd/2026-10-07-platform-core-assembly/`. Next Task2 base`f7779e9`.
- Task2 complete: developer `ses_ee8e71a34ffe10wtYNYRg7ihF7` committed `1bc76b5`
  (`feat: assemble explicit external-only platform Core`;7owned files: restricted router flag+
  gating, new platform_graph/app/assembly,11test contract file, additive inventory/README).
  First attempt stopped at harness step limit with mid-edit tree; bounded continuation preserved/
  finished it without reset. Author evidence:newtest11pass; scoped10-filematrix204pass; Ruff/format+
  scopedmypy clean; core module boundariesOK183records. Task reviewer
  `ses_ee8d5187effeSWKUYHVCrX3D3I`: specPASS/qualityApproved,noCritical/Important;4Minors deferred
  to final review (storage field typedAny; create_platform_app auth optional vs brief required;
  operations-rejection test covers2/5 surfaces; Analysis/data happy-path wiring untested).
  Ruling: accept pre-existing `EXTERNAL_OPERATIONS_ONLY`→409 store semantics (verified
  observation_work_orders.py:1108,:2232) and optional `processing_job_store=None` mount argument
  (sites.py:1202-1207). Next Task3 base`1bc76b5`.
- Task3 complete: developer `ses_ee8d307d5ffeVTYbG7BBmaVrFF` committed `6b6fc08`
  (`feat: add fail-closed platform Core production entrypoint`;8owned files: new
  foundation/config_values,composition/runtime_config,composition/platform_production,23test file;
  re-export-only edits to assembly/production_config; additive inventory/README). Step-limit stop
  recovered by bounded continuation; formatting ruling applied (new files formatted; pre-existing
  legacy format-uncleanliness untouched). Author evidence: REDmissing-module→GREEN23; matrix253+
  profile49pass; Ruff/scopedmypy clean; boundariesOK186records. Task reviewer
  `ses_ee8c5473effetd7Kt9QEjlznEv`: specPASS/qualityApproved, noCritical/Important/Minor;
  structural same-object re-exports, validation-before-side-effects order, no-Mission/device
  requirement, non-vacuous deny-boot test and complete journal close-on-failure all verified
  in-diff. `production.py`/Docker/Compose confirmed absent from the diff. Next Task4 base`6b6fc08`.
- Task4 complete: developer `ses_ee8c3f712ffeJtC6M2nDy5R0AX` committed `26b3c5d`
  (`test: add platform Core generated-flow and replay coverage`;3files:+1947). Two harness
  step-limit stops recovered by bounded continuations; uncommitted work preserved, no reset.
  Author evidence: platform-factory integration7/7 (HTTP external order→two sealed V2 DSM
  revisions→real byte inspection→analysis worker transport→region receipt→same-area follow-up;
  negatives wrong-profile422/stale-digest422/changed-bytes422; extra-journal trace; route
  inventory without flight/managed mutation); replay2/2 (restart history under exact grants;
  corrupt/unknown journal fail-closed); scoped267passed; Ruff clean; no source changes.
- Final whole-P2 review `ses_ee8ac5871ffetB3IcpErhDzXHp` and independent closure runner
  `ses_ee8ac5874ffeI1uEwO3U0xUveU` (full configured suite/static/gates/offline artifact closure;
  scratch`/tmp/opencode/physical-site-p2-final-verify/`) run in parallel. Milestone closure awaits
  their receipts; no product acceptance/customer/runtime-independence inference from task tests.
- Final whole-P2 review `ses_ee8ac5871ffetB3IcpErhDzXHp`: specPASS/qualityApprove-with-Minors,
  noCritical/Important; report`final-review.md` read. Rulings: Q1 V1 submission ingress to
  retained managed rows accepted as-is (registration ingress≠execution; oracle restricted set
  exactly implemented; a new mode gate would exceed approved scope → P5 follow-up candidate);
  Q2 `allow_expired=True`/`allow_historical_catalog_binding=True` parity directly verified
  (platform_production.py:134,150,156 == production.py:206,231,237). MinorsM1–M4 backlog;
  Task2 “Analysis/data happy-path untested” closed by Task4 worker+region-receipt coverage.
  Integrated full-suite/static/artifact results pending from independent runner
  `ses_ee8ac5874ffeI1uEwO3U0xUveU`; do not poll.
- P2 integrated suite at26b3c5d (runner scratch `/tmp/opencode/physical-site-p2-final-verify/`):
  scoped1023passed; full configured run9145passed/122skipped/102warnings/1failed (24m34s under
  machine load). The single failure
  `test_external_analysis_worker_loop.py::test_run_once_joins_a_timed_out_measurement_renewal_before_the_next_core_call`
  is ENVIRONMENT-INDUCED, not a P2 regression: P2 touched neither the test nor its import chain
  (`git log f12857c..HEAD` empty for those paths); Primary control experiment ran the same test from
  an extracted f12857c tree with the same venv under the same machine conditions → 3/3 identical
  failures (direct26b3c5d run:4/4). Machine load avg≈21.5 since00:03KST from18 orphaned
  `node -e while(true){...}` processes (ppid1, user tmux-spawn scope, ~48GB RSS; cgroup
  `cpu.max=max`, `nr_throttled=0` → plain contention, not quota). Both revisions passed the same
  test under earlier low-load full runs. Backlog: timing-sensitive test hardening; one clean
  full-suite pass under normal machine load remains a bounded open check, not a P2 defect.
- Runner final message was provider-corrupted and stopped before receipt/static/gates/artifact
  batches; bounded continuation dispatched on the same session. No P2 completion claim until the
  receipt and remaining batches land.
- P2 closure batches completed at26b3c5d (receipt`/tmp/opencode/physical-site-p2-final-verify/receipt.md`
  read): scoped1023passed; static: broad mypy118errors/16files → +9 diagnostics exactly in the2new
  P2 test files, scoped15modules clean, Ruff clean; gates7/7 exit0 (lock162, disposition,
  normalization, boundaries186, whitespace); offline artifact closure: domain/mission-contracts/Core
  built offline and all15changed modules byte-identical source↔sdist↔wheel with valid RECORDs.
  No product-source error, no new dependency. Full-suite environmental failure adjudicated (above).
- P2 typing fix round: developer `ses_ee8c3f712ffeJtC6M2nDy5R0AX` committed `8aaba33`
  (`test: tidy platform Core test typing`;2test files,+12/−8) closing the +9 broad-mypy diagnostics;
  annotation/narrowing/guard only, net−1 `type: ignore`, no assertion/skip changes. Scoped re-review
  `ses_ee8880181ffe6PkTxzlzI30LtD`: all findings ADDRESSED, no new Critical/Important;3Minor
  observations (route-inventory narrowing excludes non-Route entries—intent preserved; assert
  rewording AttributeError→AssertionError on unexpected-missing; tool-run counts not diff-verifiable
  → assigned to the independent re-run). Independent re-verification at8aaba33 dispatched as a
  fresh bounded runner session (ses_ee8880176ffeTu9wzA9CFhIAnE); P2 closure awaits its receipt.
- P2 final re-verification at8aaba33 (receipt §2x read): scoped13passed (11+2); broad mypy
  109errors/14files with both fixed files absent (+9delta closed); ruff/whitespace clean; narrow-mypy
  exit1 explained as search-path `import-not-found` in3unrelated untouched files that are0-error
  under the broad run. HEAD/tree unchanged by the run.
- P2 “Platform Core Assembly” TECHNICAL CLOSURE (not whole-goal/product acceptance): whole-P2 review
  PASS+Minors noCritical/Important; independent suite9145pass (+1environment-induced failure
  adjudicated by pre-P2 control under load), static baseline restored, gates7/7, offline artifact
  bytes identical; typing fix reviewed+re-verified. Open/bounded: one clean full-suite pass under
  normal machine load (18 non-task node spinners since00:03, not ours); broad mypy109/14
  pre-existing;MinorsM1–M4 + timing-test hardening in backlog; P4 Console; real customer/operational
  acceptance. P3 written plan drafted; its two verifier-found coupling discrepancies were applied;
  current SHA256`671b16c25b1342d1d148893fa50b5bda9f2e0875847d45b357f29b25cef7664f` (per the updated
  entry below); Human written review remains the P3 execution gate.
- P3 verifier scratch incident (2026-10-08 02:47): the verifier created
  `/tmp/opencode/physical-site-p3-plan-verify/` mode0600 with no traverse bit (the prompt's "0600"
  instruction was ambiguous for a directory); Primary chmod`700`, verifier remained alive and
  completed with its full per-check result in the session record. Any pre-repair write attempts
  would have failed with EACCES; the receipt path was later observed absent (external cleanup) —
  the verifier's completed result above is the evidence.

### P3 planning discovery (2026-10-08)

- Next stage per spec§8-3 and P2-deferred successor: worker/build/CI/tooling archive separation.
  Read-only discovery completed at main4c57996; measured facts and the open-decision list are in
  `.superpowers/sdd/2026-10-08-worker-archive-p3/notes.md` (planning inputs, not decisions).
- Key facts:194ARCHIVE_CANDIDATEs in8groups (edge124, dji-gateway28, packages42 — mission-contracts13/
  mission-planning9/perception13/equipment-intelligence7). All package/gateway groups have live
  consumer blockers (11Core import files incl. missions/capability/edge_transport/equipment — an
  earlier `grep -l` list of14 included docstring-only citations; pc ksi_perception in
  runner.py:83+odm_masking.py:75, both managed-only; change-detection retained by named use incl.
  active region extraction). CI edge jobs,
  legacy Dockerfile CMD (`ksi_core.production:build_production_app`), `ruff check .` whole-repo
  target and Docker contexts (`COPY . .`, `.dockerignore` without archive) are the build-side items
  to separate.
- Drafting the P3 written plan next; no source change, move or approval exists yet. Human
  written-plan review remains the execution gate for P3.
- P3 draft written: [Acquisition separation, worker split and source archive](2026-10-08-acquisition-separation-and-archive.md)
  (DRAFT FOR WRITTEN REVIEW;7tasks: current-revision move decisions → historical readers →
  worker split → platform boot/CI switch → Core dependency closure → physical moves/CI/lock/docs →
  independent closure). Independent verifier `ses_ee8990618ffeZ92sq5rKNCt2pH` completed PARTIAL
  (receipt reported at`/tmp/opencode/physical-site-p3-plan-verify/receipt.md`; the scratch dir was
  later observed absent — result preserved in the session record): header/links/SHA/CSV counts,
  placeholder scan, internal consistency and scope checks PASS; exactly two coupling discrepancies
  — (1) Core import files are11 not12, (2) `ksi_perception` is imported by`runner.py:83` and
  `odm_masking.py:75`. Both were applied by Primary on2026-10-08 (all locations incl. notes/ledger),
  and the corrected file differs from the verified bytes only by these fixes. Current
  SHA256`671b16c25b1342d1d148893fa50b5bda9f2e0875847d45b357f29b25cef7664f`. Human review remains
  the P3 execution gate; no P3 execution started.

### P3 written approval and execution start (2026-10-08)

- Human approved the P3 acquisition-separation plan at SHA`671b16c25b1342d1d148893fa50b5bda9f2e087
  5847d45b357f29b25cef7664f` (main576536d) with the retained sequential developer/reviewer/
  independent-runner method (rendered decision “계획 승인·기존 방식 실행”). Approved scope is the
  plan as written: move decisions → readers → worker split → boot/CI switch → Core dependency
  closure → physical moves/CI/lock/docs → independent closure. Excluded: deletion (moves only),
  Console/UI (P4), deployment, credentials, new dependencies.
- Independent plan verification completed before approval (PARTIAL with exactly the two coupling
  discrepancies — Core imports11 and ksi_perception in2sites — both applied verbatim; the corrected
  file differs from the verified bytes only by those fixes).
- Workspace: current checkout/main, one writer; SDD workspace
  `.superpowers/sdd/2026-10-08-acquisition-separation-and-archive/`.
- Rulings before dispatch: (a) move ownership — T3 executes the worker managed-module moves, T5 the
  Core managed-module moves (with their import swaps), T6 executes the194candidate-group moves and
  verifies/completes every manifest row; the T1 manifest is the single move authority. (b) T3/T4
  share `deploy/compose.yaml` and `.github/workflows/ci.yml` sequentially — T4 preserves T3's worker
  edits and T6 preserves both when restructuring CI. (c) T2 read-path wiring (if any) precedes T5
  and is preserved by it. (d) The plan file keeps its reviewed bytes; this ledger governs approval.
- Task1 dispatched after this entry; Tasks2–7 to follow in order.
- Task1 complete: developer `ses_ee65f0632ffek07tOTmBp4Qy5W` committed `3f61cf9`
  (`feat: add current-revision acquisition move decisions`;4files:+1533). The194-row manifest binds
  the current revision (current git object/blob SHA + baseline refs), exact destinations, MOVE/DEFER/
  RETAIN vocabulary with task-referenced blocker ids, fail-closed CLI with atomic writes, protected
  rows metadata-only; primitives reused via the file-location loader. Author evidence:45passed
  incl15new; frozen-CSV CLI control unchanged; ruff/format/scopedmypy clean;10/10cross-group
  spot-check. Reviewer `ses_ee6575535ffefI0h6I6d4CZpWX`: spec✅/qualityApproved, noCritical/Important;
  5Minors deferred to final review (joint CSV+MD atomicity; frozen out-path guard; edge/root
  consumer-token weakness; baseline refs unvalidated-by-design; MD arithmetic wording). ⚠️resolved:
  `manifold.env` is ignored and `manifold.env.example` is tracked+referenced. Next Task2 base3f61cf9.
- Task2 complete: developer `ses_ee655ad55ffeUTnobvLF0pByRQ` committed `86e2ef6`+`abd026f`
  (`test: pin historical managed-result readers…`/`test: harden…`;new720line test file, no wiring).
  Reviewer `ses_ee650b44dffeDl05k00IqjHXV8` round1 Needs-fixes → fix → scoped re-review ALL
  ADDRESSED. Accepted posture: managed job/artifact HTTP reads stay unwired — controller verified
  the runtime chain is mission-free TODAY (`import ksi_core.processing_jobs` →0 `ksi_mission*`), the
  author's original reason was false and is corrected, and the real end-state constraint is that
  managed reads depend on the T5-archived mission/managed domain with no active platform consumer.
  Hardened: `find_spec` denier+positive control, runtime-chain proof, managed-row409/no-500 pin,
  exact identifier bytes; store-level replay byte-identical. 403passed combined; ruff/mypy clean;
  Minors backlog. Ruling correction (a′): the194-row manifest governs T6 candidate moves; T3/T5
  sets are governed by their classification tables (blob-hash-bound records+inverse notes), T6
  verifies-completes. Next Task3 base`abd026f`.
- Task3 complete: developer `ses_ee64c7745ffe7sTNc20v6lxDS3` committed `6a00443`+`e12d697`
  (`refactor: split managed reconstruction out of the platform worker`/`test: restore lane closure
  gate coverage`). Reviewer `ses_ee6419125ffe39AmTAkXoR0X3T` round1 Approved+1Important →
  fix → scoped re-review ADDRESSED. 17 blob-identical renames (8pc src modules+8managed tests+
  Dockerfile.worker) to `archive/acquisition-2026/**`; pc pyproject drops the managed script+
  `ksi-perception` (lock2-line pc-only diff); `deploy/compose.yaml` worker service/volume removed;
  boundary tests3 (`test_acquisition_archive_boundary.py` with `find_spec` denier+positive control);
  pins baseline closed for the retired Dockerfile; `archive/**` ruff exclude + `.dockerignore`
  archive exclusion applied in-task (controller ruling; T4 verifies); INV-040 lane closure gate
  restored (e12d697). Counts: boundary3/keep-lane232/platform+replay56/entrypoint166/production-
  gate9/comparison19/pins+evidence+packaging18+90+11; scopedmypy clean; `ruff check .` clean; lock
  green. Deferred: compose.vm worker overlay stub (VM owner), pre-existing format-unclean test,
  boundary-file collection-time dependency note. Next Task4 base`e12d697`.
- Task3 closure correction: T3's matrix missed `test_repository_normalization`; its manifest
  `processing-leaf-boundaries.dependencyEvidence` still pointed at the moved files, so the gate was
  RED after`6a00443`. Discovered in T4 and fixed in`93bf8b5` (R0_R2 2-path swap to archive
  destinations; validator PASS both modes;17/17). Lesson recorded: moves that touch
  manifest-referenced paths must run the normalization gate in-task.
- Task4 complete: developer `ses_ee63d7ccdffejY2a0B1JM7dZ0q` committed `2a2cbe6`+`93bf8b5`
  (`build: boot the platform profile and separate archive inputs`/`chore: sync R0-R2 manifest…`).
  Reviewer `ses_ee6371b90ffeGVNH1wJ6DW0pyX` Approved noCritical/Important;3Minors backlog (env
  denied-check pattern hardening; one-directional SSOT check; deploy README OIDC shorthand).
  Dockerfile CMD = platform factory (exact); ci.yml smoke single-token switch with locked flags
  intact; compose core drops only Mission key/device mounts; `test_platform_boot_switch.py`
  config-as-data fail-closed; env docs/tests aligned to actual factory requirements; touch-check
  recorded; Docker daemon unavailable locally (CI-only) disclosed. Next Task5 base`93bf8b5`.
- Task5 implemented+committed: developer `ses_ee6361cafffecA9p3eo5kJNX2R` committed `2e85391`
  (`refactor: close Core acquisition dependencies onto the archive boundary`;237files:158
  blob-identical renames=71product+87tests,73adapted,6new archive records) + `997f3c1`
  (`fix: resolve move-tooling consumers against the post-closure tree`). Five bounded continuations
  across a harness/server restart preserved staged work throughout (no reset). Full bare suite
  **6690passed/113skipped/100warnings/exit0**; gates green (`ruff check .`, lock exact6-line drop,
  scoped mypy, normalization trio, boundaries140records, pins/evidence/disposition). The11recorded
  Core import sites are closed; Core drops the3candidate package deps; platform imports zero
  acquisition code (boundary AST scan + deny-hook with positive control); readers stay active.
  Root-cause fixes recorded: app_factory archived-import removal (no archive import even guarded),
  identity_work capability branch removal, routes/{missions,operations} archival, phase3 audit tool
  archival, move-tool consumer active-or-archive rule. Consequences recorded: orphaned T3 worker
  lanes→T6, Console seed fixture→P4/P6, `create_app` retired-in-place, retention events path
  fail-closed. Task reviewer `ses_ee5e2a49fffekWZFa3VS5ydz25` verdict **Needs fixes** — Important:
  (1) the archived HIL tool was edited inside its rename (95% similarity; the blob-identical claim
  is false for it); (2) boundary gates do not enforce the `archive/**` import prohibition
  (AST/deny scope = the3acquisition packages only); (3) `create_app` does not fail loudly — archived
  params are accepted and silently dropped; (4) retention tools keep guarded
  `from ksi_core.events import EventStore` instead of explicit absence. Minors: mcp-identity
  retired-route absence assert; production-test identity narrowing; checker COMPOSITION_MODULES
  comment. Fix round1 dispatched on the same developer session; Task6 dispatch after adjudication.
- Task5 COMPLETE (all review findings closed): fix round1 `3dc3541` (`test: enforce the archive
  boundary and fail-closed retired params`;7files,+258/−33: HIL tool restored blob-identical +
  separate fail-loud shim; committed archive AST+deny-hook gate with positive controls; 25+1
  create_app retired-param guards proven firing; retention tools explicit absence) and fix round2
  `2c5f380` (`fix: guard the retired capability projector param`;2lines). Scoped re-reviews: all
  findings ADDRESSED, no new breakage. Final full suite **6692passed/113skipped/100warnings/exit0**.
  Task5 commits:2e85391+997f3c1+3dc3541+2c5f380. Next Task6 base`2c5f380`.
- Task6 implemented+committed: developer `ses_ee5b4dcf8ffevic1IKB7qHeWYA` committed the executor
  (`27c0599`) + 54 extra closures (`ad220a9`) + consumer closures (`4148cb7`,`581b402`,`2f42628`,
  `13feb20`) + group moves a–g (`dce5ee4`+`e6e740a`,`1553c3f`,`42ff431`,`d23f020`,`ebac3ac`,
  `5d47471`,`c5763af`) + pyproject/lock (`89d644b`;162→157) + boundary Part C (`676f237`) + T1
  post-exec verification (`790471b`) + field-kit extras (`8160ca8`,`dc9d681`,`a5b3e95`).
  194/194 manifest moves + 57 extra closures blob-identical with inverse records
  (`docs/audit/PHYSICAL_SITE_MOVE_EXECUTION_v1.json`;`task-6-evidence/extra-moves-54.json`);
  CI edge jobs removed + `historical-archive.yml` (workflow_dispatch only); deploy/docs closures;
  FULL bare suite **5995passed/30skipped/0failed**; gates green (frozen bytes unchanged,
  normalization trio, boundaries, pins/evidence/disposition, ruff check ., collect-only, mypy15,
  diff-check). Cache-limited offline re-resolution finding recorded with pristine-worktree proof;
  Task7 needs a fresh `uv sync`/online lock in its own environment. Report task-6-report.md.
  Task reviewer dispatching; Task7 after adjudication.
- Task6 COMPLETE (all review findings closed): fix `621dc91` (`docs: track the extras inverse record
  and close the compose note`;6files,+486/−14: tracked
  `docs/audit/PHYSICAL_SITE_MOVE_EXECUTION_EXTRAS_v1.json` with57 records; compose-sweep test across
  the four compose files; synthetic boundary positive controls; executor/normalization notes
  narrowed). Scoped re-review: all findings ADDRESSED, no new breakage. Task6 commits end at
  `621dc91`; full suite5995passed/30skipped/0failed at`a5b3e95`. Next: Task7 whole-P3 review +
  independent runner closure.
- Task7a whole-P3 review `ses_ee57c45e5ffe9QL9Es0NmWQOi9` COMPLETE (report final-p3-review.md):
  SPEC-ALIGNED/APPROVED-WITH-FOLLOW-UPS, no Critical. I-1 (boundary scanner blind spot on the
  archived-config read at `tests/contract/test_deploy_env_contract.py:165`) → fix `545f5a0`
  (`test: make the archive-load exemption explicit`;1file,+33/−4, pinned exemption + exact-set pin
  + truthful wording) → scoped re-review ADDRESSED, no new breakage. I-2 resolved: inventory
  186→140 in`2e85391` (46 pruned; the T5 report's "44/142" was an arithmetic error) — report-only
  correction, no code change. 7Minors backlog; residual triage: orphaned lanes→P5, Console→P4,
  prose→backlog, venv/cache-limited lock→T7 environmental note.
- Task7b independent runner `ses_ee57c45e3ffeek4zyRQXFQ6KRr` RUNNING (full suite in progress;
  scratch `/tmp/opencode/physical-site-p3-final-verify/`); P3 close awaits its receipt.
- Task7 COMPLETE — P3 TECHNICAL CLOSURE (not product acceptance): runner receipt
  `/tmp/opencode/physical-site-p3-final-verify/receipt.md`: affected275passed; full suite
  **5996passed/30skipped/98warnings/exit0**; ruff clean; broad mypy109/14 exact pre-P3 baseline
  (0 new); scoped mypy product19+tools8 clean; gates lock157/disposition/normalization×2/
  boundaries140/whitespace; archive8/8 sampled rows,432files, archived imports fail, factories
  import, AST scan clean; delta re-covered at final HEAD`ad7687f`; no-mutation evidence clean.
  Open gates: P4 Console (design-owned), P5 whole RB-01..09 + first-flow remaining gaps, real
  customer t0/t1/t2/rights/operational acceptance; backlog Minors + environment notes (offline
  lock cache limitation; venv dangling editables; env-flaky worker-loop test under load;
  DEPLOYMENT.md masking prose; orphaned T3 worker lanes → P5). P3 does not close the product.
- P4 written plan drafted: [Operations Console cleanup](2026-10-08-operations-console-cleanup-p4.md)
  (DRAFT FOR WRITTEN REVIEW; base89d4187). Discovery: nav7items/screens/API-proxies17/lib-references48
  inventoried; design path = existing OpenDesign project “KSI Operations Console” bound to the real
  `apps/dashboard` folder (scenario`od-code-migration`; stale snapshot + failed status noted; no
  active context — use the explicit project id). Tasks: decision inventory → design-run cleanup →
  functional verification (tsc/eslint/vitest/build + Playwright 390/768/1440 with the platform
  server) → design-owned rendered review → independent closure (RB-07). No app edits yet.
- P4 plan verification (ses_ee5622eb1ffelywuiA62IyXOjR) PARTIAL → corrections applied: authority
  for RETIRE/KEEP is the PLATFORM PROFILE's mounted route set (adjudicated the three cross-check
  flags against actual code — `event_store` retired-guarded→Console `/events` retires;
  `checkpoint-validations` platform-unmounted→Console retire with note; `/v1/missions/*` also
  carries source-media routes and `phase34.ts` uses managed-era endpoints→Task 1 per-endpoint
  resolution/repoint); minor inventory fixes (`portfolio.ts` file, `assets/**`, `field/**` subdirs);
  indicative 45–50 file count noted. Corrected plan SHA
  `c7fd91dfa78dea4069824237cba7fff84b2895a347e9210054188b6785d29070`. Human written review
  requested; no app edits yet.
- P4 written approval and execution start (2026-10-08): Human approved the P4 plan at SHA
  `c7fd91df…` (rendered decision “계획 승인·기존 방식 실행”). Method retained: decision inventory →
  design-workspace cleanup run (OpenDesign “KSI Operations Console”, real folder) → Build functional
  verification (tsc/eslint/vitest/build + Playwright 390/768/1440) → design-owned rendered review →
  independent closure. T1 dispatching; the design run starts only after T1's scope contract lands.
  No app edits before T1.
- T1 complete: `cedeb27` (`docs: add P4 console cleanup decisions`;128-route platform inventory +
  KEEP/RETIRE/REPOINT tables + flag resolutions); reviewer ses_ee542ccc7ffekbr4QQOIIA5dQy Approved
  (3 Minors backlog; one becomes a T2 re-grep).
- T2 design run STARTED: runId `be0e572f-c436-4789-a5ba-9db322b99cd5` (project6edb22d8, plugin
  od-code-migration, snapshot d21bad9c, agent codex, workspace folder-backed in-place
  writeback). Polling get_run; no cancel/substitute; first start attempt was a 422 plugin-input
  validation error (requestId 4eafaf95 not consumed); successful requestId 9000fd20.
  Studio: http://127.0.0.1:7456/projects/6edb22d8-bd56-43df-9e13-521a30700925/conversations/19f0ddcd-7561-4aa4-a9ca-e8c2c0af1f3b

### P4 resume / functional integration findings (2026-10-08)

- Git revalidated: current checkout `main` at `9a3bab1ba710d0c8925cf3ae8bd8e301e425a9cf`,
  empty index, 198 pending paths (197 Dashboard + local Core runner); no foreign worktree changed.
  Task-owned patch and source snapshot preserved at `/tmp/opencode/p4-resume-20261008/`.
- T2 initial run terminated `succeeded/no_artifact`; direct-source output is provisional, not a
  completed visual deliverable. It exceeded KEEP/REPOINT on Home/sites/site detail. Refinement
  `27219b21-5f69-4ead-b7fd-f6e124ed7264` restored ADR-025 hierarchy/carousel, F08 table and surviving
  workspace tabs. Host tsc/eslint/build passed; Vitest 758/100 passed before later E2E/runner edits.
  Separate design-owned rendered review and final independent verification remain required.
- T3 last whole E2E run: 27 failed / 26 passed / 19 skipped (`/tmp/p4-e2e3.log`). Actual Home and Work
  rendered zero rows, so these failures are not ruled stale assertions. No screenshot baseline accepted.
- Root-cause proof: seeded platform assembled with an unrestricted generated opaque ADMIN returns
  5 sites/4 WorkOrders. The same seeded bytes, copied to an isolated probe directory (not reopened
  under a running journal writer), with the actual local OIDC mapping return 0/0 and site-detail404.
  Mapping resolves `local-admin` → `org-local-pilot`, but both explicit resource allowlists are empty.
  `sites.py:1018` and corresponding WorkOrder scope filtering correctly enforce that denial.
- T3 Ruling: repair only the local test harness with an opt-in, exact synthetic fixture scope;
  preserve default empty grants, production subject registry, tenant filtering and scope checks.
  No wildcard, grants inferred from arbitrary ledgers, live customer grant or Core endpoint added.
  Cost if wrong: fixture scope may drift; real assembly tests bind the literal resource IDs and
  ensure the empty-organization account and unrelated resources remain undisclosed.
- Implementation contract (bounded harness repair): Requirement IDs RB-07 / REQ-SEC-101;
  owner `scripts/run_core_dev.py` + contract tests, with design-owned Dashboard fixture/stack/test
  wiring handed off sequentially. Acceptance: explicit fixture-enabled OIDC sees 5 sites, four
  non-executable historical WorkOrders and one explicit external-ingress WorkOrder; no-flag and
  empty-organization scopes stay empty; retired endpoints remain absent;
  unconfigured evidence storage issues no usable upload/read capability. Contracts affected: none.
  References: local issuer accounts, current platform assembly and scope contracts (ADOPT, not copy
  acquisition authority). Files: runner + `tests/contract/test_core_dev_platform.py`; Dashboard
  seed/stack/E2E repairs by the design workspace. Tests: scoped pytest + actual OIDC/browser flows.
  Invariants: INV-040 (no production mock), INV-060 (evidence capability fails closed); tenant/scope
  nondisclosure enforced by unchanged Core with negative controls. HIL/device: not applicable.
  Rights: owned synthetic fixtures only. Rollback: inverse task-owned source diff; no real data move.
- Product binding rechecked: existing representative project `6edb22d8-bd56-43df-9e13-521a30700925`
  / KSI Operations Console; actual source `apps/dashboard` (metadata.baseDir/resolvedDir match).
  Temporary actual-product server `http://localhost:3241/` on this host, Core8041/issuer9041,
  tailnet disabled; reuse this runtime, not an artifact preview. Design Studio URL above is separate.
  Brand/token source remains `src/app/globals.css` and approved components; no new visual direction.
- Other open findings: seed currently defaults to managed mode; external-decision endpoint404;
  site title regression; empty-state assertion drift; blank-body capture path unidentified;
  dead S3 placeholder is not proven fail-closed. Diagnose each separately; do not weaken tests.
- Developer dispatch provider/privacy errors produced no implementation. Build owns the bounded
  nonvisual recovery; design retains Console source/rendered review ownership. P5 written-plan
  gate, customer rights/operational acceptance and external delivery remain open, not reprioritized.
- Runner RED→GREEN: `tests/contract/test_core_dev_platform.py` first 9failed/1passed (missing opt-in
  and unavailable-storage port) → 10passed/1.45s after bounded runner changes. Exact fixture grants
  cover the five literal `e2e-site-*` IDs and first `wa-{site}-0001` only; loopback/OIDC-only flag.
  Missing S3 now raises EvidenceStorageError before network/signing, rather than pointing at9000.
- Fixture correction ruling: retain the existing four synthetic managed-era WorkOrders only as
  non-executable historical read fixtures; add one EXTERNAL_RECONSTRUCTION WorkOrder through the
  real store with an idempotency key, APPROVED/OPEN and no Mission/ProcessingJob. External work
  cannot be fabricated with managed status transitions (`record_status` correctly denies them).
  This preserves history coverage while adding the normal ingress state, not new runtime behavior.
  New test expects5orders/oneexternal/context200 and currently fails on4orders (fixture-red.log).
- Blank capture diagnosed independently: `/hil/pilot-bridge` deliberately returns bodyless404 via
  unchanged `proxy.ts:94` (curl404/0bytes and real-browser response-code failure). Capture must
  assert this negative transport contract instead of insisting it is a visible product screen;
  do not enable HIL, add a fake page or weaken real surviving-screen render assertions.
- T2c bounded nonvisual Console recovery is commissioned next under the same representative design
  project/scenario. RequestId `3bf86c8f-957d-4a1b-bcda-97d1e631ec0b`; owned paths = seed/stack/E2E,
  named metadata (no layout restyle), run report. Build owns runner/tests/ledgers, no concurrent writer.
  Existing product runtime stays3241 until a deliberate same-target restart applies the new flag.
  Separate T4 rendered review remains pending; this recovery is not a substitute for that review.
- T2c RUN STARTED `dfaccd15-ebed-4846-8bc8-c51f6ff7f609` (request3bf86c8f, snapshot77cf51e2,
  same representative project, folder-backed/in-place writeback verified in run metadata). In flight;
  no cancellation/replacement. Stage skills: bounded code-migration pipeline; Build systematic-debugging,
  test-driven-development, executing-plans, playwright-cli. T4 review skill remains a later distinct stage.
- Additional host evidence before T2c writes land: OIDC auth/route/history/detail/evidence scope
  regressions69passed/7.29s; runner negatives10passed/1deselected (the one positive deliberately
  awaits the extra external fixture); scoped mypy2files clean after explicit EvidenceStorage port
  annotation; Ruff and diff-check clean. Added boot check rejects opening S3 client/credential chain
  while `/ready` remains200. None of these replace T3 integrated browser or T5 independent final checks.
- Resume limitation: no pre-P4 live capture folder exists. Four retained Home regression baselines
  are available under `apps/dashboard/e2e/__screenshots__`; label them as retained baselines, not
  newly captured before views. Existing `p4-cleanup-evidence/after` shots were captured under the
  defective empty scopes and must not be passed off as corrected populated-state evidence.
- Preserved security gap for the successor: current scoped OIDC allowlist permits reads/normal
  external WorkOrder ingress but not Site create/update or pending-external-decisions/team endpoints.
  This harness fix must NOT open those routes or substitute unrestricted authority. Report and test
  denied/unavailable states; P5 first-flow gap analysis must distinguish mounted routes from actual
  principal reachability before any approved security extension. No endpoint/permission expansion here.

### P4 T3 corrected-scope verification (2026-10-08)

- T2c `dfaccd15` terminal succeeded/source-direct (`no_artifact`); actual Dashboard fixture/wrapper/
  E2E/report diff inspected. No new managed artifact or visually accepted deliverable is inferred.
  Same real folder; narrow flag only when seed option is present; four clearly labeled historical
  records plus one real store-created EXTERNAL_RECONSTRUCTION APPROVED/OPEN row. Host signed-JWT
  assembly check `uv run --no-sync pytest -q tests/contract/test_core_dev_platform.py` now **11passed**.
- Host same-target test stack was gracefully restarted (exact task-owned PID), reusing issuer state,
  ports3241/8041/9041 and Dashboard dist `.next-p4-resume`, with fresh owned generated Core data at
  `/tmp/opencode/p4-resume-20261008/live-corrected/core`. No tailnet/security change; no second writer.
- Actual browser `p4-resume` reads Home5sites and the restored carousel, Sites5, named Site title,
  site work-order tab and explicit external work detail via UI links. Self-assignment POST200 showed
  `담당 · 내 작업` and persisted after reload. Cleared through the UI and reloaded to `미배정` after
  the test; no arbitrary journal reset. An initial assertion used the wrong label, not a product error.
- Optional external measurement request lists returned404 under this unconfigured workflow. The UI
  retained its unavailable error rather than inventing success/empty results. No endpoint added.
- After T2c host checks: tsc/eslint/Next build exit0; Vitest **758passed/100files** (logs under
  `/tmp/opencode/p4-resume-20261008/*-post-recovery.log`). Not independent final-P4 receipts.
- Actual corrected captures: `apps/dashboard/p4-cleanup-evidence/corrected-scope/` contains24views
  (8screens ×390/768/1440). `source-snapshot.json` binds HEAD9a3bab1 +240required-file SHA256;
  `render-checks.json` and `render-sha256.json` bind captures. No horizontal overflow; all24 axe
  runs returned0violations; no uncaught page JavaScript errors. Work details have two H1s (shell+
  work name), which axe does not flag; send to the design reviewer, not silently call it compliant.
  The captures do not yet cover empty/loading/focus or inner-container scroll depth.
- Independent bounded harness verifier dispatched `ses_ee453090affe182AvSPWygYfVk`; owns no files,
  no live stack, no dependencies, tests synthetic temporary state. Required-file hashes + actual
  commands/results + full active Python suite requested. Receipt remains pending until returned.
- Current full Dashboard E2E rerun uses `/tmp/opencode/p4-resume-20261008/p4-live.playwright.config.mts`,
  importing the repo config but reusing the owned3241 runtime (no duplicate server). It intentionally
  leaves the external/staging flag unset, so meaningful fixture checks remain enabled. No baseline
  refresh; expected retained baseline differences are reported, not masked. Log `e2e-live.log`.
- Design review routing discovery: `design-review` is only a catalog/upstream-install descriptor,
  not a bundled executable full workflow. Use the actually bundled `web-design-guidelines` pinned
  rules in the separate rendered-review stage, with actual captures/behavior inputs; no upstream
  installation or source-only acceptance. Review must confirm reading the input images.
- E2E runner correction: the first temporary ESM import exposed the repository config under
  `.default`; without unwrapping it the19-test run used an unnamed1280viewport (8failed/7passed).
  These are NOT the target-viewport receipt. Corrected wrapper guards4projects and `--list` confirms
  76tests/5files at390/768/1024/1440. Real rerun: **16failed/45passed/15skipped**, exit1, 1.4min.
  Remaining families (4each): empty title queried as heading although shared EmptyState emits<p>;
  site `다음 행동` assertion despite the displayed platform next-action link; known MANAGED historical
  context queried as UNVERIFIED; retained Home baseline differences. Touch/focus/axe/captures/external
  registration UI passed at their applicable widths. Failures are not hidden or globally skipped.
- T4 frozen input bundle `apps/dashboard/p4-cleanup-evidence/t4-inputs-v1/`:36screenshots
  (12screens ×390/768/1440), keyboard focus3, actual loading under client CDP throttle3, external
  detail bottom-scroll3, empty home/sites/work9, foreign-site denied3, keyboard carousel-next with
  normal/reduced motion6, retained Home baselines4. Total67PNGs;88input hashes in `input-sha256.json`.
  All actual states use the same source snapshot (240required files unchanged). Generated fixtures
  only; no auth trace/cookie/session data included. Empty-org login→denied URL and default fixture
  login restored through the actual issuer UI. No fabricated server-success response. Logs redact
  transient auth query. Review limitations: baselines are historical, other before views unavailable.
- Project-level commissioning conditions VERIFIED for representative project6edb22d8: (1) latest
  T2c real-folder write/read/remove probe, real-source path and in-place writeback; (2) same-session
  notifier binding verified after resume, plus actual terminal retrieval by explicit poll fallback;
  (3) actual source diff +240SHA snapshot, host build/tests + actual-product rendered/functional
  verification above. These are evidence for this target/session, not inferred from its name.
  Build owns commissioning/polling/validation/reporting; Human need not operate the design workspace.
- T4 next request `69da03fd-3c69-4a6b-9890-14d2dc841299`: existing code-migration scenario + bundled
  `web-design-guidelines` (distinct review stage), real-source/image preflight mandatory. Design owns
  analyze→bounded refinement→render-review loop and fixed/open defect handoff. Build validates
  the actual revision/render/evidence and engineering contracts, not a duplicate aesthetic review.
  E2E corrections may target only the observed three stale families with exact approved behaviors;
  no baseline refresh until design-rendered review resolves the actual differences.
- Independent harness receipt received `ses_ee453090affe182AvSPWygYfVk`, path
  `/tmp/opencode/p4-harness-independent-verify/receipt.md` (archive SHA256a9a0c9fe). Bounded11passed,
  OIDC74passed (same69 +5coverage), rootRuff clean, scopedmypy2clean; full active Python
  **10failed/5998passed/30skipped**, exit1. Four required-file hashes identical before/after; main9a3bab1,
  pending202paths, no stack/data/code mutation. Not final P4/UI closure.
- Full-suite findings are acceptance work, not waived:5P4 stale sync assertions read the retired
  EventActions.tsx/missionSiteGate.ts (3+2), so their current target no longer exists; decide a
  nonvacuous replacement boundary gate while preserving domain/replay history. Other5 reject unsafe
  group-writable temporary dirs under hostumask0002 in unchanged deployment/API tests; safe-umask
  control and durable fixture fix needed, with production security checks unchanged. The earlier
  timing-sensitive worker-renewal test PASSED this receipt. No all-green full-suite claim.
- T4 RUNNING `27425391-48df-4cdf-a823-68939ee69836` (request69da03fd, snapshote35b2205,
  same folder-backed/in-place representative project). Poll/notification handoff active; no replay.
- T3 Ruling / test-consumer closure: retire only the two now-orphaned Python→TS EventActions/
  MissionSiteGate mirrors (5cases), with exact baseline9a3bab1/SHA recovery in decision doc§7.
  Replace obsolete UI-mirror obligations with actual platform HTTP read/mutation absence tests
  and retained browser route checks. Domain enums/graphs, Site-autonomy mirror, historical replay
  and schema sync remain active; no archive edit/import, production semantics or skip introduced.
  Cost if wrong: a legitimate retained reader could lose its mirror check; the absent UI targets,
  mounted-route authority and named retained checks demonstrate these two consumers retired.
- Bounded test-repair contract: RB-07/RB-09; owner root contract tests, no app writer conflict.
  Files: the two retired mirrors; `test_core_dev_platform.py` negative read/mutation paths;
  `test_analysis_pilot_deployment.py` safe generated candidate directories+unsafe controls;
  `test_external_analysis_api.py` two0700owned fixture roots. API/contracts/runtime/archive untouched.
  Invariants: INV-040/060 and tenant/currentness/consent preserved by real component tests; no HIL.
  Verification: selected regressions underumask0002, surviving sync/domain checks, rootRuff,
  independent full Python on integrated state. Rights=owned synthetic; rollback exact inverse diff.
- Safe-fixture RED→GREEN: new group-writable-umask candidate test failed UNSAFE_DIRECTORY (1failed,
  3negative controls passed); the existing external-AI identity test also failed under explicit0002.
  Candidate/AI fixture roots now explicitly0700; production deploy/Core security code unchanged.
  First rerun found a helper nested-parent regression (second/authority missing), corrected by
  creating the owned candidate base0700. Complete two-file rerun under0002 exited0 (log
  `private-fixture-green.log`); root suite and independent final receipt remain to run.
- Python closure independent rerun assigned to existing Test Runner
  `ses_ee453090affe182AvSPWygYfVk`, receipt target `/tmp/opencode/p4-python-consumer-verify/`.
  It binds the actual modified Python sources, preserves ambient umask, reruns scoped82/OIDC74,
  rootRuff/scopedmypy/fullPython; no live stack or source mutation, disjoint from T4 app writer.
- Resume evidence: main9a3bab1, empty index,211pending paths; T4 still in-flight. Prepared provisional
  whole-P4 recovery/diff snapshot under `/tmp/opencode/p4-resume-20261008/review-package/`:
  208source/contract paths,158deleted, original SHA256 atfb3310a. Not a final reviewer snapshot
  while the design writer is active; final sources must be rebound before dispatch/verification.
- Ruling: correct T1's OrthophotoOverlay KEEP classification rather than restore a dead managed
  component — baseline source explicitly fetches retired `/api/processing-jobs/*/download`, not
  the external-display routes asserted by the inventory. Decision doc§8 records RETIRE for the
  two wrappers and KEEP for ExternalSanitizedOrthophoto/report-safe derivative/shared raster code.
  External authorized viewing and its consent/byte boundaries are preserved; local unconfigured
  storage remains unverified for real-byte image display. Cost if wrong: losing a legitimate reader;
  actual callers/endpoints above establish which historical wrapper and current reader differ.
- Independent Python consumer closure receipt received and read: session
  `ses_ee453090affe182AvSPWygYfVk`, `/tmp/opencode/p4-python-consumer-verify/receipt.md`, archive
  SHA256`fa724eaec8d09e96f3e545d79f02b68e4874647ac1937f492fbd91e641bb05e6`.
  Actual main9a3bab1 + pending output, ambientumask0002; scoped82/OIDC74/rootRuff/scopedmypy2
  clean; **full active Python6013passed/30skipped/0failed**, exit0,738.57s. Timing worker19passed.
  Six bound sources unchanged: runner`ed8168c7`, Coredevtest`5ae49f87`, deploytest`fee10d1d`,
  APItest`79a7a432`, seed`61343806`, stack`9260020b`. No production admission relaxation.
  Delta +5collected = retire5orphaned mirror cases +6real retired-route controls +4private-fixture
  controls. This is independent nonvisual closure, not final UI/design/product acceptance.
- T4 run27425391 terminal succeeded/source-direct,17.5min. Actual report
  `apps/dashboard/p4-cleanup-render-review.md` confirms all67PNGs visually opened,88input+240source
  hashes matched, pinned guidelines read, real-folder probe. Eight changed source/test hashes
  matched on host. Bounded fixes: emptySites single registration CTA/current truthful copy,
  skip-link geometry, work detailH1→H2 and deniedSiteH2→H1; stale E2E families corrected without
  baseline refresh. Inner renderer could not reach host; edited screens explicitly PROVISIONAL.
- Evidence correction: prior24-view corrected-scope capture had0axe findings, but extended36-view
  T4 inputs actually contain3moderate `page-has-heading-one` findings on direct analysis404 state.
  Previous ledger/commission summary claiming all36zero was wrong; report followed actual JSON.
  No test threshold/baseline/security relaxation is used to hide that discrepancy.
- Post-T4 host tsc/eslint/Vitest/build all exit0 (`post-t4-checks/commands.json`); actual source
  capture bundle `apps/dashboard/p4-cleanup-evidence/t4-post-v1/` binds237current UI/E2Efiles +
  **59actual settled states**,63input hashes. Includes all36primaryviews,3externalbottom views,
  8keyboard(firstTab vs explicit-focus geometry) views and12empty/denied views. All59axes return0,
  uncaught pageerrors0, foreignSite name not leaked. This does NOT close the following defects.
- T4-SKIP-01 regression found in actual browser: firstTab now reaches desktop sidebar Search at
 1024/1440 because the skip link moved after that navigation in DOM. Mobile/tablet still firstTab
  skip. Existing E2E `키보드는...` reproduced RED atdesktop1440 (`t4-keyboard-red.log`,1failed).
  Desired: first keyboard action skips navigation AND focused geometry does not overlap sidebar;
  do not replace Tab with `.focus()` or weaken either assertion. Route repair back to design.
- T4-ANALYSIS-ROUTE-02 root cause: same authenticated fixture gets work-areas200 and both
  analysis-observations/analyses404; real Site workspace access succeeds. Local runner has no
  analysis graph configuration (`external_analysis_local_graph=None`), so platform_graph§183–199
  and routes/external§254–275 intentionally mount no Analysis routes. Analysis page groups
  getSite+child reads in Promise.all and turns ANY child404 into Site notFound. This confuses
  optional configuration unavailability with denied Site; no grant/policy/activation change needed.
  Desired: establish Site access first; preserve genuine Site404 nondisclosure; child errors show
  typed unavailable/error, not empty analyses or a false Site denial. Existing observation-history
  page demonstrates this separation. Repair stays in Console source/tests, not Core/config.
- All previously loading-required captures now settled: observation-history displays its actual
  error state; external-work lower reads show comparison-list unavailable + single-volume not
  configured. Two expected request-list404s remain recorded, not invented empty/success states.
- Next bounded refinement request `660d6b56-a914-435c-b8b7-eb921f93d599`: real-source237SHA+
 59postT4PNGs63inputSHA + prior review report/focusRED/root-cause evidence. Design owns keyboard
  contract repair, analysis error boundary and rendered re-review; no new direction/permissions/
  backend or baseline refresh. Build supplies post-edit actual renders before design closure.
- Bounded refinement commissioned as run`7d2ade64-85b0-4e28-971c-9637b0adf847`,
  request`660d6b56-a914-435c-b8b7-eb921f93d599`, existing source-bound project6edb22d8,
  scenario`od-code-migration` + bundled`web-design-guidelines`; source-direct actual app folder.
  Notifier tracking confirmed for this session, wake permission unpaused. At resume main9a3bab1,
  empty index,214pending paths, approved spec/plan hashes unchanged. P5 drafting only while
  refinement owns app sources; no successor execution, direction/baseline/security change.
- P5 written proposal prepared (planning ONLY):
  [integrated rebaseline verification](2026-10-08-physical-site-rebaseline-integrated-verification-p5.md),
  SHA256`4119e5d1dca5f89c6f6c1edbb9880289c183d7529b03f53f45224a51fbfe374a`;
  5tasks/31unchecked steps, self-reviewed against unchanged approved spec/RB matrix. Exact-path/
  whitespace checks clean. No P5 implementation/approval: needs final P4 technical closure and
  Human written-plan review. Proposal distinguishes current Analysis SDK platform factory from
  Spatial Data SDK router-only fixture, all251archive-record verification from8sampled rows,
  prepared local checks from unverified fresh environment/image/CI/customer acceptance.
- T4 refinement7d2ade64 terminal/source-direct,14.5min; report Round2 confirms real-folder probe,
  237prior source+63input hashes matched and all59PNGs read. Narrow edits: shell firstTab order,
  access-first Analysis child error boundary, observation visibleH1→H2, page/E2E regression checks.
  All5reported current file hashes match host. Inner Vitest lacked its sandbox native binding;
  host post-refinement tsc/eslint/Vitest/build all exit0, **761tests/100files** (100 is unchanged).
- Host four-width E2E post-refinement: **63passed/10failed/15skipped**, log
  `/tmp/opencode/p4-resume-20261008/post-refinement-e2e.log`. Keyboard real firstTab+Enter+route
  focus checks PASS at all4widths; analysis Site context/unavailable body works, but its new E2E
  fails before reaching later assertions because no H1 exists. Desktop Site-action query resolves
  2legitimate same-destination links (header + observation section). Remaining4Home screenshot
  mismatches still use untouched historical baselines. No hidden skip, threshold/mask change.
- Frozen Round2 render bundle `apps/dashboard/p4-cleanup-evidence/t4-round2-render-v1/`:
  **353required source hashes**, **68settled actual states**, **80PNGs/84input entries**. Source
  manifest`a81dd1fb…`; input manifest`47c37799…`; required sources unchanged through capture.
  Includes actual gateway-click analysis arrival, all primary views, lower-scroll focused-skip,
  four-width real firstTab/Enter, both motion settings, empty/foreignSite+foreignAnalysis states;
  copies of4exactPlaywright Home actual+diff images and4retained references (no auth trace).
  UncaughtJS0/overflow0. Three moderate heading-one findings remain on actualanalysis; foreign
  Site names remain undisclosed. Current denialSite has2H1s (not an axe violation), recorded.
- Defect root causes from actual source/browser: `resolvePageTitle` omits `/sites/{id}/analysis`,
  so client-aware MainPageTitle returnsnull; page visible title isH2. The earlier generic denied
  H1 now duplicates the known Site shellH1 on `/sites/{id}`. Require coherent one-H1 normal/error/
  denied states without restoring foreignnames, fake headings or weakening count assertions.
  The Site CTA test should distinguish actual header/section intent or a design-adjudicated
  duplicate; `.first()` or relaxed count alone is not acceptance. No new visual direction.
- Next bounded Round3 action request`57673c0b-679a-4608-86a4-52255d033edf`: design reads all actual
  Round2 images/diffs, closes measured firstTab/access/observation-heading findings, repairs
  missing analysis heading/denied heading consistency and meaningful CTA selector. Explicit
  source/image-bound Home baseline adjudication requested; do not refresh before that decision.
- Round3 commissioned as run`a3547beb-4890-47cf-9d68-df365964a40c`, existing same-source project/
  code-edit scenario+bundled review skill, no alternative runtime. Notifier tracking+wake verified.
- Whole-P4 read-only engineering Reviewer `ses_ee4028f40ffem3gKb3OgmH4DBp` assigned immutable
  `/tmp/opencode/p4-resume-20261008/whole-p4-review-v1/`: base89d4187, actual9a3bab1+pending,
  520current/deleted-baseline records (restored only to package, not real checkout); actual diff,
  new files, scoped receipts and concrete known-open design findings. Reviewer does not replace
  design aesthetic/render review. Final source changes from Round3 must be supplied as a narrow
  delta to the same reviewer before engineering closure. Source ownership remains one writer.
- Whole-P4 frozen engineering review received/read: Reviewer`ses_ee4028f40ffem3gKb3OgmH4DBp`,
  `whole-p4-review-v1/reviewer-report.md`. No newly discovered wrong consumer retirement, dead
  runtime call, auth/tenant/security regression, fabricated result/storage bypass or fixture
  concealment in the frozen revision. Four Important closure findings match the known Round3
  list (analysis heading, CTA ambiguity, Home baseline, denied heading); final delta/render/runner
  still required. Four Minor groups are recorded, not blanket authority to extend cleanup.
- Ruling: Home baseline adoption is a source/render-bound design adjudication + mechanical
  transfer within the already approved no-restyle P4 path, NOT a new mandatory Human gate as
  suggested in the reviewer report. Human acceptance stays separate/open; new direction or
  unapproved layout changes still require a decision. Cost if wrong: adopting a visual drift;
  mitigate by exact four-width candidates/source hashes/approved hierarchy, no threshold/mask
  relaxation and design-owned review. Report neither reviewer advice nor technical closure as
  Human acceptance.
- Ruling: reviewer§Important-1's absent-analysis-H1 finding stands; absent title-map entries alone
  do not prove missing H1 on spatial assets/redirects (actual-assets captures have1H1/noaxe).
  Its§Important-3 denied-analysis explanation is corrected: generic segment not-found supplies
  the existing H1, not an invented alternative shell branch. Preserve measured evidence; do not
  add generic unknown-path titles or broaden fixes from route names alone.
- Reviewer Minor-1 split by actual impact: unreachable coming-soon `data` config is harmless
  backlog; visible `/more` copy still teaching retired flight/connection/recovery scope violates
  P4 truthful surviving-menu guidance and is regraded as a bounded required copy fix (design-
  owned). It will be added at the next rendered-review stage after Round3 terminates; no concurrent
  run/Build-side UI edit. Cost if misgraded: minor rework, not a new product feature. Capture/review
  actual More before/after, preserve only real fleet/support destination and no new capability claim.
- Deferred nonblocking minors: dead managed-era epoch helper exports, unused retired-route type/
  comments, invisible progress-redirect metadata title. Keep in backlog/next-baseline gap map;
  no opportunistic source/type sweep. Declined checks: supply actual Vitest log761/100 to final
  delta; pixels remain design-owned; post-package drift/independent final runner remain pending;
  P5 scope/config/rights limitations remain explicit, not P4 defects or new execution authority.

### P4 Round3 verification and bounded closure refinement — 2026-10-09 resume

- Git revalidated: main`9a3bab1ba710d0c8925cf3ae8bd8e301e425a9cf`,216pending paths/empty index;
  same current checkout, foreign worktrees untouched, approved spec/P4-plan/P5-proposal hashes
  unchanged. Goal b13320f7 active; P5 proposal remains unapproved. No new product authority.
- Run`a3547beb` terminal source-direct: exactly7reported SHA match current files and other346
  required source hashes unchanged; seven-record set digest`3add6b6e…`. Actual80image reads and
 84input checks reported; narrow known-route title, generic denialH2 and default-tab redundant
  header action repairs confirmed against actual diff. No Core/grants/policy/brand/token edits.
- Design Round3 explicitly adjudicated all4exact Home candidate/diff/prior PNGs and unchanged
  Home required-source hashes. Mechanically adopted only those4candidate bytes into their existing
  `e2e/__screenshots__/home-{project}.png` paths, with preimage and adopted SHA checked and inverse
  references preserved in frozen Round2 bundle; no thresholds/masks changed. Exact adoption record:
  `apps/dashboard/p4-cleanup-evidence/t4-round3-render-v1/baseline-adoption.json`.
- Host postRound3 typecheck/eslint/Vitest/build all exit0; **761tests/100files**. Four-project
  authenticated E2E **69passed/4failed/15skipped** (`post-round3-e2e.log`). All4Home comparisons and
  default Site action tests now pass. Four analysis tests progress past headings/context and fail
  on an ambiguous global alert locator, not absent error: actual error alert inside main plus
  Next route announcer outside main. Actual browser confirms mainAlerts1/allAlerts2. Scope the
  assertion to the meaningful main error region and retain exact error/nofakezero/noretry/heading
  assertions; do not remove the route announcer, use `.first()` or weaken the count/content check.
- New frozen changed-source renders `t4-round3-render-v1`: **353required hashes,28settled PNGs,
  35input entries**, sourceSHA`31411b52…`, final inputSHA`13665187…`; all sources unchanged during
  capture. Analysis mainH1/context/error and Site/analysis/observation denial now correct; default
  Site action is uniquely visible at all4widths with exact unchanged destination. UncaughtJS0,
  overflow0; genuine foreign Site names absent. Access-side data/permissions are unchanged.
- Two remaining browser REDs captured before any next source edit: denied-assets has0H1 and3
  moderate heading-one findings at390/768/1440; More still explicitly teaches retired flight/
  connection/recovery at those3widths. The shared not-found H2 correction exposes spatial-assets'
  previously mixed ownership (page-owned H1, no recognized shell title); not a Core denial defect.
  Require one coherent H1 in accessible and denied asset states, exact recognized route only,
  generic non-disclosing denialH2 and unchanged page visual classes/data. More requires truthful
  surviving support guidance only, no new capability/help/runtime behavior. Browser RED record:
  `rendered-regression-red.json`; no unit-test success inferred from the inner unavailable binding.
- Next concrete review/refinement action request`3361c134-1ed2-4664-86d9-90e0dfc14537`:
  review actual28images/current353source; close prior heading/CTA findings with changed renders;
  fix asset heading ownership + More copy + main-scoped alert query only, add meaningful regression
  assertions and report exact changed hashes. Design owns all app edits and visual review; Build
  supplies new changed-source captures afterwards. No arbitrary cap, no new design direction,
  no P5 work or unapproved dependency/runtime operation.
- Round4 started as`241aceb5-fa71-42de-96d6-57c800f5f36f`; same-source code-edit scenario+bundled
  review skill, notifier tracking/wake unpaused confirmed. Source authority and one writer unchanged.
  Six Python/seed/launcher SHA rechecked against independent ses_ee453090 receipt: all6identical;
  both retired consumers/tests still absent. Reuse only that unchanged nonvisual verification scope;
  the pending final Dashboard/E2E checks remain independent and cannot inherit Python closure.
- Late notifier for historical`dfaccd15` was resolved via authoritative status/message; it is
  the already-consumed fixture recovery, not the current refinement. Its metadata reports
  `od-owned/baseDir:null` despite the inner absolute-folder edit report; do not call that metadata
  proof of source-direct binding. Actual fixture/launcher bytes and six independent receipt SHAs
  remain verified; current`241aceb5` is explicitly folder-backed/in-place. No replay, rebind,
  copy substitution, cancellation or new execution was inferred from the late notification.
- Late historical`27425391` notification likewise resolved: message/report is the already-read
  Round1 review, superseded by Round2/3 actual-source render evidence. Its generic `od-owned`
  metadata is not source-link proof; original actual image/file checks and required-file hashes
  remain the evidence. Current Round4 writer still running/tracked; no old-stage replay or
  second writer, no baseline decision reversal from this historical message.

### P4 Round4 source verification and final-render handoff — 2026-10-09

- Run`241aceb5` authoritative terminal succeeded, explicitly folder-backed/user-local/in-place at
  actual Dashboard folder. Final message/report read: no new entry artifact (source-direct), six
  source/test edits, rendered status provisional. Inner typecheck/targeted ESLint pass; inner Vitest
  unavailable binding remains honestly unrun, not substituted by source inference.
- Actual six-file SHA verified against report; set digest`87ababc8428515c90686388a61ef536c964d0c5cceb7310b34c6e08964bad35f`.
  Previous353source snapshot differs only in those six,347others unchanged. Approved spec/P4/P5
  hashes unchanged. Current main9a3bab1,222pending paths/empty index, foreign worktrees untouched.
- Changes inspected: exact spatial-assets title-map entry + page-owned title H1→H2 retaining all
  classes/text/data; More introductory sentence only; main-scoped unique analysis alert query;
  literal route-title and accessible/denied asset + truthful support E2E assertions. No policy,
  endpoint, Site-access, permission/grant, catalog, storage, tokens or backend edit in this round.
- New `t4-round4-render-v1/source-snapshot.json` SHA`4a66cec660015bd20262cbf6513ba7f136d6ddb7fc17cf5540deea615c1fa3bd`
  binds353required files before/after actual host capture. **18settled states/18PNG** at390/768/1440:
  accessible assets (directURL+reload), More, analysis (actual gateway click), denied assets/Site/
  analysis. All18 exactly1H1; denied states generic/no foreign Site name; More old promise absent,
  exact fleet-support link/limitation retained; main analysis alert1. UncaughtJS/API/console0,
  overflow0, allaxe violations0. Capture script/check JSON retained, no credentials/session traces.
  This is engineering evidence, not design-rendered closure; design must read matching images.
- T5 independent Test Runner assignment: final353source-bound Dashboard tsc/eslint/fullVitest/build
  and actual-platform four-project E2E on existing localhost3241/Core8041/issuer9041 only; no second
  stack or policy activation, no baseline refresh/threshold/mask changes. Verify six unchanged Python/
  seed/launcher receipt SHA and keep prior6013/30/0 scope distinct. Actual skip reasons and final
  source/revision/command/result receipt required. Source is frozen during verification; Primary
  handles durable records/Git, design may only write its rendered-review report at this stage.
- Independent Dashboard seat`ses_ee3df17b2ffeY4zF1AdKMuolcq` launched on that frozen source.
  Final design review request`f2554be5-58d7-4881-aeca-4ca56f7f0452` uses the same exact353files,
  `t4-round4-render-v1/input-sha256.json` SHA`f67e28d2f236dcbf296358467e637ff3318d578b230a5ab19cb8ec3c95ac30e3`
  (22entries/18PNGs plus captures/script/source and copied prior report). Report-only ownership:
  design may create `apps/dashboard/p4-cleanup-final-render-review.md`; no source/test/config edit
  while Test Runner verifies. New defects are reported with exact state/impact/desired result, not
  silently repaired concurrently. Functional test closure and human acceptance remain separate.
- Final report-only design run`75d5f901-c555-47e9-a754-2d69bb1b03de` started with those inputs.
  Independent Runner's first return was malformed closing markup; actual task logs showed
  tsc/eslint exit0, Vitest762tests/100files exit0 and build exit0 plus353pre-SHA PASS, but no E2E/
  post-source/receipt. Resumed the same seat only for unfinished verification, not rerunning
  completed checks or changing model/install/runtime. Completion remains unclaimed pending receipt.

### P4 final visual review passed; independent E2E uncovered test-flow defects — 2026-10-09

- Report-only design`75d5f901` terminal; actual new report
  `apps/dashboard/p4-cleanup-final-render-review.md` SHA`5635f47bc2979adfd38358bb0a2f7a708be5709fc78b9c33c1aa8c14260ecc19`
  read in full. It confirms image-capable reads of all18named PNGs +22input/353source SHA matches,
  no remaining design-owned defect in requested scope; stable findings06/07 fixed with exact
  renders,03/04 reconfirmed,05/01/02/Home reuse documented against unchanged-source evidence.
  Independent functional verification explicitly pending, not conflated with design or Human
  acceptance. Outer independently rechecked all353source/22input hashes; no source/report mutation.
  Daemon artifact list contains51rolling capture outputs with an entry-missing verdict, not a
  new UI generation; task output is the actual report and its source-bound rendered findings.
- Independent seat`ses_ee3df17b2` reached tool step limit after actual commands and post-SHA checks;
  no receipt.md written. Read its actual logs/results: tsc0/eslint0 (one no-unused expression
  warning on evidence capture script,0errors), Vitest**762/100**0, build0; authenticated4-project
  E2E **69passed/8failed/15skipped**, exit1/flaky0. Pre/post353SHA and six-file set digest match,
  HEAD constant;223status paths differ only by final design report. This is a real failed check,
  not a pass inferred from partial agent output; structured summary/logs are durable below.
- Root causes independently confirmed against spec/source/error traces, two cases ×all4widths:
  `T5-OBS-ALERT-QUERY-09`: line189 unscoped observation alert sees main error + Next announcer;
  previously hidden behind failing analysis assertion. `T5-WORKSPACE-RETURN-10`: new asset-route
  heading assertions at294–298 change the URL, then five-tab workspace assertions run on asset
  detail which intentionally has no SiteHeader. Actual asset-heading/context assertions passed.
  Neither grants a product-layout fix or assertion removal. Repair main-scoped single visible
  observation error and exercise the real asset-return link before all unchanged workspace checks.
- E2E skip names/reasons read from actual JSON: two desktop coarse-pointer cases; one1024capture
  case (approved390/768/1440 only); twelve Phase2-staging cases (flag off). No blanket fixture skip,
  baseline refresh or weakened masks/counts. Keep15explicit skips distinct from requiredP4green.
- Durable RED bundle `apps/dashboard/p4-cleanup-evidence/t5-e2e-red-v1` has7bound inputs,
  manifestSHA`5c9420b47ad44bfb9fa32dea1fe596b238a48966a40dc4fefaa4b5b13095e8a6`, actual E2E log,
  full762Vitest/build/type/lint logs + source/findings binding. No auth traces/result JSON copied.
- Next bounded test-only correction request`3d354dc7-d6a5-4bb0-8a6b-a1c3b0d18af7`:
  only `e2e/operations-console.spec.ts` + its repair report, no UI/source/style/backend/data edit.
  Existing design disposition stays valid for unchanged UI; final verification rebinds the changed
  test file. Step-limited TestRunner is not blindly continued; use a fresh compact independent
  verification seat after the concrete test repair. No new scope/installation or P5 execution.
- Test-only code-edit run`fca2bf41-e2b8-407d-bf25-96e925b535b9` started; no active independent
  tester/source writer. One spec + repair report only; UI/layout/rendered findings remain unchanged.
- Test-only`fca2bf41` terminal, actual report/diff inspected: operations spec SHA
  `20d8a4f4390a68de3bc9125e0e1a745adc28f7db1a47dfd57e8eec6474b4fda9`, only9added/1replaced
  assertion lines. Main observation error count1/visible/typedcopy retained; real unique
  `현장으로 돌아가기` link exacthref+click+workspaceURL now precedes unchanged5tab checks.
  Same-class scan finds no unscoped alert in that spec; no assertion/skip/threshold removal.
  Other352required files byte-identical; design report/input/UI source unchanged. Lint scoped0
  is not final E2E evidence. Report `apps/dashboard/p4-cleanup-e2e-repair.md` preserves RED/limits.
- Final verification snapshot `t5-final-source-v1/source-snapshot.json` SHA
  `8256911ce314281e04e2b3b57852033d54d1e07333bfc46106a8fafa66701a1c` binds353current files and
  explicitly bridges the one nonvisual E2E delta to the unchanged Round4 visual snapshot/report.
  Fresh independent Runner assignment repeats full5commands with one compact receipt driver;
  no previous pass is silently promoted to post-repair evidence. Final engineering review follows
  this exact delta and actual receipt; closure/source commit still pending.
- Evidence-label reconciliation: full E2E capture spec line7 defaults `P4_CAPTURE_PHASE` to
  `before` and writes51current-source PNGs in that rolling folder; its name is not a chronological
  pre-P4 proof. Added `p4-cleanup-evidence/README.md` routing to immutable Round2/3/4 inputs and
  exact before/after defect states. No capture source/config change during final verification,
  no false fresh-preP4 claim or Home oracle change. Rolling files may change during E2E; neither
  required353source nor frozen rendered-input manifests include them.
- Fresh final seat`ses_ee3cff067ffenNG7tq5WksJSvI` assigned the new353snapshot, all5actual commands,
  exact4projects and final receipt/skip reasons; logs under `/tmp/opencode/p4-final-dashboard-verify-v2`.
  One serial local driver recommended to avoid step-limit overhead; no forced role/model change,
  no overlapping source writer. Primary prepares the frozen narrow engineering delta only.
- Existing whole-P4 Reviewer`ses_ee4028f40ffem3gKb3OgmH4DBp` received final narrow immutable delta
  `/tmp/opencode/p4-resume-20261008/whole-p4-final-delta-v1`,87files/inputSHA
  `822a00610c5eee9cf2ec2337c41e353f44f590f6cf32d909a3b9424305bf8ace`:14changed original records
  (9source/test,4HomePNG,1round report),2newreport-onlyfiles;505other prior records unchanged/
  still deleted, mutable ledger excluded. No unreviewed new code;328line text delta, not whole
  1.2MiB replay. Final Runner receipt is independent/in-flight; Reviewer may return code findings
  with that evidence gap rather than poll/duplicate tests. Primary must bind actual receipt before
  technical closure. No source writer and no second design-generation stage.
- Defect origin tags (tracking, not quota): `T4-SKIP-01`, `T4-ANALYSIS-ROUTE-02`,
  `T4-ANALYSIS-H1-03`, `T4-DENIED-H1-04`, `T4-ASSET-DENIAL-H1-06` originate from self actual-browser
  verification, confirmed/refined by design review; `T4-SITE-CTA-QUERY-05` and
  `T4-ANALYSIS-ALERT-QUERY-08` originate from self host E2E/error diagnosis; `T4-MORE-COPY-07`
  originates from Reviewer (regraded by self); `T5-OBS-ALERT-QUERY-09` and
  `T5-WORKSPACE-RETURN-10` originate from independent Test Runner. Design owns visual disposition,
  not these contribution labels. Prior reports/evidence preserve actual findings and uncertainty.

### P4 final technical verification — 2026-10-09 (local commit pending)

- Fresh independent Test Runner`ses_ee3cff067ffenNG7tq5WksJSvI` actual final receipt consumed,
  then its descriptive attestation corrected by the same seat without rerunning/changing results.
  Tested main`9a3bab1ba710d0c8925cf3ae8bd8e301e425a9cf` + pending task-owned P4; all353pre/post
  hashes match final snapshot`8256911c…`,352unchanged from design-reviewed UI (one E2E-only delta).
  HEAD constant,0source mutation. Actual E2E JSON/log independently inspected by Primary.
- Five commands, actual exit0: `tsc --noEmit`, `eslint .`, `npm test`, `npm run build`,
  `playwright test --config=/tmp/opencode/p4-resume-20261008/p4-live.playwright.config.mts
  --output=/tmp/opencode/p4-final-dashboard-verify-v2/e2e-results --reporter=list,json`.
  **Vitest762tests/100files; E2E92collected =77passed/0failed/15skipped/0flaky**,23cases per named
 390/768/1024/1440 project. Existing15conditional skip reasons fully preserved in the receipt.
  ESLint0errors/1warning on immutable capture evidence JS (not production, nonblocking).
- Defect09/10 GREEN on all4projects after observed independent RED8failures, with unchanged
  headings/error/CTA/five-tab assertions and no new skips/masks/thresholds. Real UI return click,
  auth/direct URL/reload, populated/empty-org/history/external-work/retired404/keyboard flows pass.
  Relevant actual views contain no fabricated success/zero/currentness/accuracy assertion.
- Final whole-P4 Reviewer`ses_ee4028f40ffem3gKb3OgmH4DBp` report SHA
  `2180a202b17e92e5c5c1632355e9a1cfd7955f437b91768f6b83734fd64743d3` consumed: all4original
  Important findings closed, no new findings; accepted scope rulings applied. Its sole remaining
  functional-receipt gap is now closed by the actual fresh receipt on matching source. Design
  report`5635f47b…` remains independent/passed; Human acceptance remains OPEN, not inferred.
- Durable verification bundle `apps/dashboard/p4-cleanup-evidence/verification/` contains actual
  final receipt SHA`e6267cebe7e6d49eb4b6c9a70d7a2241460b0c9e46e859f3141869f52596718d`,5commandlogs,
  actual case/skip summary, prior Python receipt and first/final engineering reports; manifestSHA
  `8b67f1f3696ea6380e0b49b2ac5ff02b0327dbdebed4ddd760749caf6f2b5b53`.
  Reused six-SHA-identical Python6013/30/0 +scoped82/OIDC74/Ruff/mypy is explicit, not a rerun.
  No trace, session storage, cookie or credential files copied. Test artifact writes to rolling
  capture folder disclosed; existing3241 accessed by E2E, never started/stopped/duplicated here.
- Plan execution evidence: T1inventory/disposition cedeb27; T2actualsource cleanup + bounded
  refinements; T3actualplatform/auth/reload/responsive checks; T4design-owned actual-render review
  with stable fixed/open list (required residual0); T5whole-P4 engineering review + fresh independent
  checks above. P4 technical verification achieved; task-owned local Git commit/reconciliation next.
  Approved plan/spec hashes remain frozen (checkbox/status history not silently rewritten).
- Boundary judgment: P4's goal-serving cleanup is met locally; further dead-helper/type/metadata
  polish is not needed for this outcome and stays backlog. Recommended next authorized decision is
  the existing focused P5 written proposal (SHA4119e5d1…), not more UI iteration or new runtime
  contracts. P5 execution is still unapproved. No claim of wholeRB-01..09/firstcustomerflow/release,
  real external byte display/measurement accuracy/operational acceptance; data/rights gates remain.
- Ruling (origin self, index audit): preserve immutable evidence bytes instead of trimming generated
  stdout/context snapshots or intentional Markdown hard breaks to manufacture a clean full-index
  whitespace result. Full `git diff --cached --check` returns2 on29evidence/report files only;
  production/test/config +task-doc scoped check returns0. No Git setting, lint/test configuration,
  threshold or source changed. Cost if wrong: poorer text diffs; mitigate with exact path-bounded
  audit and retained hashes, never claiming the full-index check passed. Task-owned699paths staged;
  proposal/checkpoint/auth/trace/foreign files excluded. Local commit next, P5 still unapproved.

### P4 technical closure and P5 written-review handoff — 2026-10-09

- Task-owned source/evidence committed locally on agreed main as
  `7f44d11967e9b31524e7f2bbe0ef466c98ad5aec` (`refactor(dashboard): retire acquisition console
  surfaces and verify platform flows`):699paths,17059insertions/24054deletions including explicit
  evidence. Actual699index paths inspected; no checkpoint, credentials/trace, foreign worktree,
  P5 proposal, package install or unrelated work included. Commit exit0; only untracked P5 draft
  remained afterwards. No branch/worktree transfer, push, deployment or history rewrite.
- **P4 Tasks1–5 technically CLOSED locally** at that source commit: mounted-route disposition,
  surviving platform Console + provenance/denial/error behavior, real login/reload/four-viewport
  flow, design-owned source-bound render review and whole-P4 engineering + independent final
  verification. Tested9a3bab1+pending content equals the352committed members of snapshot8256911c
  (the353rd entry is ignored local bytecode, clarified below); commit changes revision identity,
  not reviewed/tested source bytes. Required P4 defects01–10
  fixed/closed with origin and RED/revision/render/check evidence above; deferred minors stay open.
- Usable level: actual local login → populated Sites → five-tab workspace → work orders/external
  registration and history/support surfaces, with deliberate retired-route404/redirect and truthful
  unavailable optional analysis/result/storage states. It is not a configured measurement/customer
  pipeline; no real-byte display or customer-data/accuracy/operational acceptance is claimed.
- Product-state records only this bounded technical result and successor link; current EXT-VAL
  slice, milestone history and Human/customer acceptance remain unchanged. Protected/foreign
  worktrees retained, current checkout kept; there is no task-created worktree to delete.
- [P5 written proposal](2026-10-08-physical-site-rebaseline-integrated-verification-p5.md) remains
  SHA`4119e5d1dca5f89c6f6c1edbb9880289c183d7529b03f53f45224a51fbfe374a`,5tasks/31unchecked
  steps, **unapproved/unexecuted**. Commit as proposal/documentation only; written Human review is
  the next execution gate. P4 closure grants no archive/MCP/policy/runtime activation or new data
  rights. Goal remains incomplete pending that approval and eventual permitted t0/t1/t2 data/
  operational inputs; do not invent more cleanup or silently start P5 to avoid a genuine gate.
- Closeout resume check: actual main7f44d11/index empty;353required source SHA match final tested
  snapshot; receipt e6267ceb/approved P4 c7fd91df/P5 proposal4119e5d1 unchanged. Only ledger and
  product-state doc edits plus the untracked exact P5 proposal remain; checkpoint replaced to
  remove stale in-flight/uncommitted-source claims. Approval-waiting is the next task state, not a
  new execution mandate. Original frozen P4/P5 headers/checkboxes retain their drafting snapshot;
  approval and technical closure authority is this ledger, not their historical base prose.
- Independent doc-only closeout check by the same final Test Runner`ses_ee3cff067` at7f44d11:
  exact3doc diff/empty index, doc whitespace0, ledger7/product-state10 relative links resolve;
  P5 exact4119e5d1 has5task headings/31unchecked/0checked steps. Product-state's historical
  milestones/current slice/next/backlog suffix is byte-identical and prior Goal lines preserved.
  Receipt `/tmp/opencode/p4-record-closeout-20261009/receipt.md`; no Dashboard rerun or source edit.
- Finding(origin Test Runner), independently reproduced by Primary: the frozen353-entry source
  manifest accidentally includes `apps/dashboard/e2e/fixtures/__pycache__/seed_operations_console.cpython-312.pyc`
  SHA`0128b0f0c5482c45748945c98619defc59ffc90a65b343886aa5ff1cd24c6d6e`, ignored by
  `.gitignore:21:__pycache__/`. Actual workspace353/353 match; Git7f44d11 contains352/352matching
  required source/asset blobs and omits that cache intentionally. This is manifest over-inclusion,
  not lost implementation or changed tested bytes. Correct the current closure claim; do not claim
  all353entries are committed or that a fresh checkout contains the cache. No pyc force-add,
  deletion, regeneration, frozen-manifest rewrite or test weakening. Future portable binding must
  separate generated artifacts; preserved hashes retain what the local design/test seats read.
  Ruling: disclose the one local-artifact exception and retain exact immutable review evidence —
  keeps tested source identity without treating cache as a deliverable; cost if wrong is an
  overbroad completeness claim, mitigated by explicit352Git/353workspace counts and exact path.
- Current-session design-notifier recovery check: final review75d5f901 and test-only repairfca2bf41
  are terminal/delivered, not active writers. One old requested record has no run ID because its
  pre-generation request failed422 for missing plugin inputs (before corrected initial P4 run);
  it is not an in-flight run and was not replayed. Other sessions/projects were not changed.

### P5 written approval and execution binding — 2026-10-09

- Human answered the written P5 review question **“P5 실행 승인 (Recommended)”** for
  [the exact five-task plan](2026-10-08-physical-site-rebaseline-integrated-verification-p5.md),
  SHA256 `4119e5d1dca5f89c6f6c1edbb9880289c183d7529b03f53f45224a51fbfe374a`.
  This is actual approval, not inferred from goal continuation. Existing sequential/local execution,
  independent final Reviewer/Test Runner and task-owned local commits remain selected. New contracts,
  installs, policy/grant activation, push/deploy and customer-data transfer remain excluded.
- Actual execution base/target: current checkout on `main`,
  `1dac44aeca503221f924687ea1631e10d7cdcc86`; tracked/untracked status and index were clean.
  P4 source/evidence closure is `7f44d11967e9b31524e7f2bbe0ef466c98ad5aec`. No new worktree
  needed for one sequential writer; four foreign worktrees remain untouched. Prior goal stays unmet;
  current goal `b13320f7` is verified active. The frozen P5 proposal header/checkboxes preserve the
  drafting snapshot; approval/execution status is owned here and in the scoped skill ledger.
- Task binding: RB-02/08/09 first; tools/tests owner; read-only full-record Git/blob/destination/inverse
  verification with disposable generated Git fixtures. Only new checker/tests plus these execution
  records are written. No wire contract, historical manifest, archive source, live journal or dependency
  changes. Rollback is a reviewed task-owned inverse commit, never reset/clean or recorded shell execution.
- Invariant binding: Task1 enforces truthful evidence/non-placeholder conclusions (INV-040) and protects
  private/foreign paths; it changes no runtime invariant. Tasks2–3 verify INV-020/024/050/051/053/054/055/
  060/061 through existing spatial/provenance/numerical/resource/image/authorization/consent contracts.
  Tasks4–5 preserve those meanings and customer/EXT-VAL acceptance while recording exact verification limits.
- Pre-flight: Task1 JSON/count/hash output feeds Task3; Task2 actual-platform IDs/digests/receipts feed
  Tasks3–4; P4 frozen source/render/runner receipts and Task4 gap map feed Task5. Interfaces agree.
  Ruling: retain frozen plan bytes and apply actual approved base/P4 closure from this ledger rather
  than its pre-closure drafting prose — avoids replaying completed P4; cost if wrong is stale status
  routing, mitigated by explicit source SHA and this approval record.
- Skill progress/briefs: `.superpowers/sdd/2026-10-08-physical-site-rebaseline-integrated-verification-p5/`.
  Task1 is IN PROGRESS; Tasks2–5 pending. No P5 completion, customer acceptance or external delivery claimed.

### P5 Task1 full-record audit and recovery findings — 2026-10-09

- New read-only checker `tools/verify_physical_site_archive.py` and disposable-Git controls
  `tests/contract/test_physical_site_archive_verification.py`: missing-tool **23failed** (intended
  assertion RED, not collection error) → **23passed**; final suite with added completeness/link/input
  controls **29passed/exit0**. A separate self-found evidence bug hid the baseline hash when HEAD
  diverged: `test_committed_destination_edit_retains_independent_baseline_hash` failed `None` versus
  original SHA (RED) → baseline-bound object is independently hashed (GREEN). No archive imports,
  recorded inverse execution, source moves, writes by the checker or network access.
- Real report at base1dac44a: **251checked/251expected**, **251original Git blob hashes match**,
  **249current destination hashes match**, exit1 with four explicit findings on exactly two rows.
  Report SHA256 `4f84e25292dee0418ce812b95c61e1775df1fc88b409d7b804dbbb4ac2e364dc`, scoped skill
  `task-1-real-archive.json`. Original main/extras manifests remain SHA7fa85601/a1867fad; no omissions,
  duplicates, unsafe path/inverse, source reintroduction or lost baseline blob reported.
- Finding(origin self, **P5-ARCH-01 OPEN as strict current-destination hash gate**): P3 commit
  `dc9d681` explicitly adapted two field-kit archive paths after the blob-identical move8160ca8:
  `tools/build_field0a_kit.py` (`KIT_DIR` parents[3]) and `tests/contract/test_field0a_kit.py`
  (root parents[4], archive-only package/tool roots). Both current destination Git object/hash differ
  from the immutable inverse record. This is recorded historical adaptation, not missing originals.
  The blanket P3 “57extras blob-identical” phrase is accurate at move time, not for final destinations;
  its later adaptation was not covered by the prior sampled audit. Preserve that dated statement and
  correct the current completeness claim here, not the frozen record.
  - Tool: original blob78940f46/SHA`abc3d8b606a23c3e636366726a0faf872ae763c41000bd01e7e19f46a9be156a`;
    current blob5546e57a/SHA`5cfaac4fdac7019258f5eebf9b180f77ccefe33cb40d48be1621218504f22459`.
  - Test: original blob015db511/SHA`65a1efc2b47ca44f5dcc1e6aef498cd4f6c582f4e3a4df97e07180f28f8318e9`;
    current bloba9c3893c/SHA`03d522ef54408fe1228f7b5a60c5c7344e63b50e8aec5dfe5223fe178a70c2f8`.
- Ruling: keep strict failure and disclose both historical adaptations; do not normalize current
  destinations, rewrite frozen inverse hashes or silently allowlist exceptions — the approved plan
  says report actual discrepancies without rewriting evidence. Cost if wrong: RB-02's strict hash gate
  remains open unnecessarily; final review can distinguish retained/recoverable history from a new
  archive-repair decision, without claiming the checker passed.
- Independent recovery primitive (not checker-derived): `git cat-file blob` materialized **12original
  blobs** into owned disposable `/tmp/opencode/p5-archive-recovery-e70p86tb/original-blobs/`: one for
  each of10actual decision groups plus both adapted fields. All12SHA256 match the recorded original;
  no real path restored, no live journal opened, no archived code/import/inverse executed. Receipt
  SHA256 `cef1ffb919ff2f327d7d529ce48043e7415357ef8662e5b72f2a401dd6554338`.
- Existing disposition/move-tooling/archive-boundary/normalization set **71passed/exit0**; frozen
  disposition CLI exit0; new2files Ruff exit0 and scoped mypy **2files clean/exit0** (unused test-only
  ignore removed, no configuration change). Full active Python is running once under ambient umask
  (`uv run --no-sync pytest -q -p no:cacheprovider`); no Task1 completion yet. Task2 preparation only
  while waiting, no replay of P4 and no approved-scope expansion.

### P5 Task1 tooling commit / Task2 execution binding — 2026-10-09

- Checker and controls only committed as `268678921286f42203fe4410eb8d8edeb89f4028`
  (2new files,634lines); manifests/spec/plan and archive sources unchanged. Fresh combined
  tooling/boundary run **100passed/exit0**; skill Task1 completion rerun **29passed/exit0**.
  This closes the verification-tool deliverable using the plan's explicit discrepancy-report branch,
  not RB-02's strict destination gate or the whole P5/goal. Full Python author run remains pending;
  Task5's independent integrated run is still required.
- Task2 base `2686789`; initial existing seven-file platform/history/SDK/replay set
  **46passed/exit0** (`task-2-baseline.log`,74.04s). Actual `analysis_api_local_fixture.py`
  uses the platform factory; `Task5AiCoreLane.mount` in spatial-data MCP fixtures constructs a
  router-only `FastAPI`. Preserve both evidence levels, add the missing platform SDK/storage seam
  rather than replace lower-level coverage.
- Test contract: full platform app, exact generated SDK Site/WorkArea scopes and opt-in consent,
  unchanged default fixture auth, real inspected DSMs and bounded worker byte transport. No production
  source/grants/activation changes; no customer data. A missing platform SDK principal/AI grant,
  missing full-byte download participant or different Core result/receipt must fail the new tests.

### P5 Task2 reproduced SDK seam findings — 2026-10-09

- Author full Python result received: **6042passed/30skipped/98warnings/0failed**,741.87s,
  `uv run --no-sync pytest -q -p no:cacheprovider`; source state was1dac44a + exact committed Task1
  checker/tests1bfa9351/f8ab90ec (now2686789), not final Task2 integration. Log SHA256
  `be3e79adc9e82b31c51e5802d9b68cf80701a7980ec7aacb38260bbbd8c25ae7`. No P5 final/full-build claim.
- New named SDK tests first failed at the actual missing harness seams: Analysis returned
  `CORE_AUTHENTICATION_FAILED`; Spatial Data had no download participant. Added only opt-in
  generated exact-site/area principals, consent at Site registration, signed test activation,
  exact current-asset AI grant, connected byte storage and owned private worker/spool. Default
  fixture scopes/consent stay unchanged. Setup typo (nonexistent consent setter) was diagnosed
  against SiteStore's actual registration API and corrected in test wiring, not production.
- **P5-SDK-01 (origin self, reproduced, repair pending):** after harness wiring the Analysis
  parity test passes; Spatial Data SDK CREATE returns503 `AUDIT_UNAVAILABLE`. Independent probe
  confirmed open/unsealed journals, real discovery200 and direct jobs.issue success. Actual
  `composition/routes/external.py:51` passes jobs/grants/sources/downloads/clock but omits
  `egress=spatial_data.ai_egress`; asset routes correctly bind it. Public issue's `ai_only()` therefore
  closes the path despite complete verified mounted AI wiring. This is a preserved-contract routing
  regression that router-only tests cannot expose, not missing rights or a new endpoint.
- Narrow repair binding: RB-03/04/06; Core composition owner; add only that existing verified egress
  participant to the existing builder call. Existing SDK test is RED at CREATE, no assertion weakened;
  affected SDK negatives/full assembly checks must pass. INV-040/060/061 are enforced by the existing
  Core AI gate; grants/permissions/consent/default activation/wire models remain unchanged. Required
  source addition is `services/core/src/ksi_core/composition/routes/external.py`; rollback task-owned
  inverse commit. No HIL, vendor, customer, install or external-effect implication.
- Task2 Ruling: Spatial Data's worker client is HTTPS-only. Keep that production boundary; a
  test-only HTTPX forwarding transport invokes the same real loopback platform HTTP server and real
  source/output byte endpoints, never generated success responses. The parser launcher is the
  existing generated local sandbox seam, not production containment proof. Cost if wrong: TLS/host
  containment may remain broken; those gates stay explicitly UNVERIFIED and require scoped host checks.

### P5 Task2 scoped verification snapshot — 2026-10-09

- **P5-SDK-01 fixed in pending source**, one existing-participant argument only. Positive SDK tests
  now pass through `assemble_platform_app`: Analysis SDK/HTTP use the same result/evidence/analysis ID,
  epochs bind observed source/report hashes; Data SDK/HTTP use the same job/receipt and a separate HTTP
  consumer verifies the downloaded hash/size, 2×2 pixels `[[101,99],[100,100]]`, EPSG:5186+5773,
  transform `[0.1,0,200000,0,-0.1,550000]`, mask255/NoDataNone and empty worker workspace. SDK
  results contain no forbidden byte/link/key fields. Cut/fill0.01/net0/uncertaintyNone stay provisional;
  the separate existing cut1/fill5/net+4/uncertainty±5m³ oracle remains untouched.
- Additional causal negative: `test_platform_spatial_ai_routes_refuse_missing_site_consent`, with
  only our egress argument removed, failed503/AUDIT_UNAVAILABLE rather than403/AI_EGRESS_DENIED.
  Restoring the one argument makes asset/list/create/get/cancel deny typed403 without acknowledgement,
  metadata publication or PUT; default Site consent remains false. This is regression evidence, not
  a production consent setter or grant change.
- Harness diagnostics, not product defects: the metadata-only fixture's1MiB cap failed real decoder
  import (isolated probe `MemoryError`); after using the existing finite1GiB SDK budget the native
  parser refused the4KiB output cap below its64KiB overhead reservation. Existing generated SDK lane
  memory/output/workspace budgets now reused, source/pixel bounds unchanged. LocalVersionProvider's
  PUT seam requires its genuine job store to prove durable reservation; the actual assembled store
  is bound after assembly, not a fabricated record. No production memory/policy/storage changes.
- Fresh seven-file matrix **49passed/0failed/exit0** (85.65s), including original negative rights,
  grant expiry/replacement/ambiguity/READ-only, revoked bytes midstream/no partial success, cancellation,
  history/currentness and replay controls. `task-2-final-matrix.log` SHA256
  `b9c433d079165d3f8390cd3d77bfbf9758460463da8888f29e416bcd2406c7c5`.
  Ruff exit0; scoped mypy2files clean/exit0. No endpoint, schema, permission or live activation changed.
- Tested pending source on main2686789: test SHA256
  `c731f2619edd35461d8482c032813844b45eb3a4dd4fcb035d9e9dc6583be854`; route SHA256
  `d8c06899f07dfcf3f3472083c6bfbc7fc75a8a683a628f3aa5f3e2747fe85c86`.
  Full author Python started as background `sh_11e840a30001kLnLSkdapZ2s4o`; wait notification,
  no polling. Task2 remains uncommitted/in progress until full result; Task3 preparation only meanwhile.

### P5 Task3 evidence work alongside full author run — 2026-10-09

- Ruling: collect/read-only static/type/entrypoint/classification evidence and draft the Task3 audit
  while Task2's full author run finishes — one writer, stable tested Task2 source and independent
  checks; no Task2 completion or changed contracts inferred. Cost if wrong: stale verification;
  bind every receipt to the two source hashes and recheck affected evidence after any code change.
  Task3 base2686789 + pending Task2; only its named audit output is added, close/commit follows Task2.
- Prepared gate set7commands all exit0: offline lock157packages, Ruff, boundaries140records,
  static image pins, normalization×2, frozen disposition. Broad mypy fails109errors/14files;
  immutable pre-P5 source control1dac44a under the same prepared toolchain fails identically
  (`file,message` multiset,0added/0removed). Scoped changed2files clean. Count alone was not used
  to prove the older pre-P3 diagnostics:3of14diagnostic-producing files differ since8aaba33.
- Entrypoint/config/recovery/boundary17-file matrix264pass/2warnings/exit0; retained6utility
  files79pass/2warnings/exit0. Initial wrong test filename produced exit4/no tests and is excluded
  from coverage; corrected from actual registered-entrypoint imports. Supported imports and
  deny-hook controls run; no live credentials/config/listener identity/image/installation.
- Read-only installed metadata:17KSI distributions,5dangling retired editable roots. Actual old
  source/.pth targets are absent and deny-hook tests remain closed; this is not a fresh environment.
- AST/literal/entrypoint trace: checkpoint aggregate helper is active via external_measurement_algorithms;
  comparison/design/region/verifier/LandXML wrappers are retained import-only historical/unwired
  utilities with named tests/helper consumers, not active current external jobs. No additional move,
  deletion or producer revival. Audit `docs/audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md`
  records exact uses, commands, hashes and separate failed/unverified gates.
- P5-COMP-01 (origin self, OPEN): base deploy/compose.yaml still has unprofiled NodeODM and historical
  ksi-odm volume; vm override also references it. No platform worker consumer. It is a retained mixed
  template, not acquisition-free default deployment; external candidate Compose is separate/no NodeODM.
  Leave template/volume untouched and propose a bounded default-template/volume-preservation decision,
  not a new reconstruction service or implicit Docker execution.

### P5 Tasks2–3 stable local evidence boundary — 2026-10-09

- Full author Python notification consumed: **6045passed/30skipped/98warnings/0failed/exit0**,
  751.23s; log SHA256`0e8885760d74fe25a6b6c9d39aec6f8a3e64df07765c45d07e18a30c10abf695`.
  Both final source hashes remained c731f261/d8c06899; only those2source paths were staged,
  staged diff/whitespace verified, committed locally as`c5cca2a` (no push/deploy).
  Post-commit required seven-file Task2 matrix **49passed/exit0**,87.66s; skill marks Task2 complete.
  This closes the local preservation/repair deliverable, not customer exports/host/TLS/accuracy.
- Task3 evidence uses that exact unchanged source state. Seven prepared/static commands0,
  entrypoint264pass/retained79pass, scoped4changed Python files clean. Broad mypy109/14FAIL remains
  identical to the immutable pre-P5 source control; fresh dependency/image/CI/host gates remain
  UNVERIFIED. Audit currently IN PROGRESS only because routing and final independent closeout
  follow in Tasks4–5; Task3's evidence deliverable is ready for local commit, not RB08 closure.

### P5 Task4 routing and first-flow binding — 2026-10-09

- Task3 was locally committed e21e0fe and skill final33tests passed; its deliverable is the truthful
  gate/classification report, not RB08 success. Task4 basee21e0fe, current main/one writer.
  Requirements RB-01/02/07/09; docs owner only. Contracts/invariants and frozen product milestones,
  Current slice, registry status/state, spec/plan approval hashes, P4 source/images/tokens preserved.
  No HIL/customer/vendor/data implications. Rollback reviewed inverse of task-owned doc commit.
- Found stale actual routing: Gateway/Edge current-owner paths, Core signing/device/managed shims,
  initial09-30pause, P4pending Console, old S3three-draft fixtures and “kept worker” reachability.
  Correct only named active README/routing/status/roadmap files; archived instructions are provenance
  only, not authority. The registry's literal PAUSED_BY_USER is a frozen dated status; comments and
  execution/evidence links distinguish current bounded approvals without replacing its status map.
- Ruling: P4 required353workspace/352Git hashes match; reuse exact design/functional evidence for
  unchanged source — allowed Task5 path, no new UI source or aesthetic judgment — cost if wrong:
  runtime/auth environment drift not caught; all3old evidence URLs now fail ConnectError and that
  limitation is explicit. No server restart/substitute preview. Only Dashboard README is edited,
  outside the P4 source snapshot. Product binding/source/entry/ports/tokens/reports recorded in audit§6.
- Final P4 rendered report5635f47b confirms18actual PNGs and0required residual defects plus named
  earlier keyboard/CTA/Home/edge-state bindings. Independent P4 receipte6267ceb establishes
  tsc/lint/build0,762unit/77E2E/15explicit skips/0fail/0flaky, not configured full-byte analysis.
- First-flow audit§6 maps Core HTTP/SDK vs Console vs input/acceptance: scoped OIDC Site POST remains
  denied by auth.py602/901; WorkArea POST is already audited623 and exact new grants are not automatic;
  sdk excludes human admin/admission deliberately. Current dev storage fails closed without S3 and
  Analysis/workflow graph is opt-in. SDK/API real-byte results and repeated areas are implemented;
  configured full Console/result/repeated customer flow remains unverified. No allowlist, endpoint,
  policy, grant or storage configuration change under P5.
- Proposed successor direction only: standalone default template+separately authorized fresh boot
  evidence before feature expansion. Actual NodeODM mixed template and strict adaptation gate remain
  open. F-01 Site bootstrap/grant decision, F-02protected storage/workers, F-03graph authority, F-04
  permittedt0/t1/t2/rights/oneconsumer+host/customer2cycle remain explicit. No new formats/general
  State/feed/remote transport or competing product objective. Final independent Task5 before handoff.
- Fresh Task4 routing4-file matrix **69passed/exit0**,4.17s; R3 validator0;145localMarkdown+2YAML
  paths resolve. P4 sources unchanged353/353, frozen spec/plan/move manifests unchanged;
  milestone/Currentslice/registry-status pin tests pass. Receiptc476d7e6; whitespace check0.

### P5 Task5 independent-check assignment — 2026-10-09

- Task4 doc-only commit`efae2af` (16named paths); post-commit routing69pass/exit0,4.25s.
  Task5 base`efae2af197b9b68107111ce720882cfb2d70fe91`; whole-P5 range1dac44a..efae2af.
- Authorized final seats: one read-only whole-P5 Reviewer and independent Test Runner in parallel;
  disjoint output-only scratch directories, no product/checkpoint/index/Git/runtime writes, installs,
  accounts, browser-login changes or further agents. Existing source/toolchain only. Primary owns
  common documents and any separately justified in-scope repair; no shared source writers.
- Freeze all whole-P5 changed source/docs plus pending assignment-ledger hash. Reviewer examines
  actual diff/contracts/five named review-focus cases and evidence gaps, not an aesthetic re-review.
  Runner tests full active Python under ambient umask, Task1/2/routing gates, archive CLI and
  scoped/broad/pre-P5 type comparison. Expected failures (strict2archive/109type) remain failures,
  not implicit waiver. P4 evidence reuse requires353matching source and actual capture/report hashes;
  current product server is offline, no new Dashboardsource/runtime change or restart is authorized.
- During seats, no product/test/source/approved docs change. Safe successor preparation may read
  scope/constraints or draft in owned scratch only. Final RB matrix and durable receipt reconciliation
  follow actual returned evidence; mandatory output/access failures are not complete/green.

### P5 Task5 independent failure / bounded routing repair — 2026-10-09

- Whole-P5 Reviewer `ses_ee156b61dffeI89kzc3v8ZTeRl` reviewed actual1dac44a..efae2af and all20
  frozen hashes; no Critical/Important source finding, two evidence-hygiene minors. Report SHA256
  `7bcb406a7ce74ff8e8d4af724b24f4790a96e1207c42985cb88b71f22f13dd08`. This source review did
  not execute the full suite and is not whole-P5 completion or acceptance.
- Independent Runner `ses_ee156b5ceffehSDBcByFl6bqRv` reached its tool-step limit after actual
  full Python **1failed/6044passed/30skipped/98warnings/exit1**,750.60s, ambientumask0002/Python3.12.13.
  Log SHA256 `3b892cad9b81687989dfc2232903b704577244d721bf5749dab6f68cc568d730` under
  `/tmp/opencode/p5-independent-test-20261009/10-full-pytest.log`. This supersedes any suggestion
  that the Task2 author6045pass run proves final Task4 integration. Prepared static6commands0,
  checker29pass/routing69pass/SDK49pass remain separately valid; outstanding type/archive/P4/link
  checks were not run. Primary rehashed all20files and inspected actual Git status after the seat:
  no mismatch or source mutation; only the existing Task5 assignment ledger was pending.
- **P5-ROUTE-01 (origin independent Test Runner, Important, repair in progress):** Task4efae2af
  removed the historical Edge provenance link from `docs/WORKSPACE_LAYOUT_AND_QUERY_GUIDE.md`.
  Immutable move-decision CSV row2 still names this document as `edge/README.md`'s consumer;
  `test_real_csv_consumers_are_real_references` reads committed HEAD and fails at line283.
  Primary independently reproduced exactly this assertion RED. No runtime/API regression is implied,
  but this is a real preserved-consumer/evidence closure regression, not an environmental skip.
- Repair binding: RB-02/09, docs owner; restore one explicit **historical provenance-only** link in
  the query guide, retaining root AGENTS/active-ledger authority and the current-owner table. No test,
  allowlist, CSV/inverse manifest, archive source, identity, API, UI or invariant change. INV-040's
  truthful evidence and all preserved invariants remain enforced by unchanged gates. No HIL/data/
  license/external effect. Rollback reviewed inverse of the task-owned doc commit only.
- Ruling: retain the useful archived-document provenance reference rather than add a new exception
  to the test's closed-consumer map or rewrite historical manifest evidence — preserves traceability
  without authoritative archive delegation. Cost if wrong: readers may mistake history for instructions;
  explicit historical-only label/root authority and existing boundary tests mitigate. The HEAD-aware
  witness must be checked against the actual committed repair, not an uncommitted file-only pass.
- The step limit is a verification-seat resource limit, not a product failure/permission grant.
  Preserve actual partial logs; after the concrete repair, assign a compact independent completion
  driver for the affected full suite plus only unfinished checks. Reuse unchanged SDK/static/source
  results instead of blindly repeating all completed commands. P6 stays proposal-only in owned scratch.
- Precommit witness used isolated candidateGit tree`8acc23ec` (realHEAD/index unchanged): the exact
  unchanged test passed1/1 with only query-guide tree delta, SHA256
  `412441630ea6c1861355be93b2ecd607a4e172f50d0fd2639b0fbb866921dd1a`. Three incomplete fixture-setup
  attempts (missing dynamic tool files/CSV) are separately retained and excluded from product RED/
  GREEN evidence. Their resolved cause was copied input closure, not another product fix. Actual
  committed-HEAD/full-suite checks still follow; no archive/manifest/test bytes changed.
- Actual repair/partial-evidence commit`eeea71c`: three doc paths only, query-guide candidate bytes
  unchanged; actual committed-HEAD witness/move-tooling + four routing/boundary files **99passed/exit0**,
  6.32s. P5-ROUTE-01's narrow witness is GREEN; full repaired-revision closure still pending.
- Compact independent completion assignment: new Test Runner on`eeea71c` plus this assignment prose;
  one owned scratch driver collects the repaired full suite and unfinished link/archive recovery/scoped
  and broad/control type/P4 hash-reuse checks. Reuse the first Runner's SDK49/checker29/static6 only
  on unchanged relevant hashes; do not duplicate them blindly. Record complete pre/post SHA/status,
  exact commands/exits/logs and all failed/unverified gates in one receipt. No product edits, further
  agents, installation, runtime/browser restart, credential/grant/activation, Docker/CI/external action.

### P5 Task5 completion receipt / second independent failure — 2026-10-09

- Completion Runner `ses_ee121ef3affedxIjP1C4dYGOvs` returned all required driver outputs;
  optional additional cause probing reached the seat step limit. Receipt SHA256
  `8a72834e56dedf7ddc917bea8ea9659ab3ccd6915222a79835ef58ce0d1500ce` under
  `/tmp/opencode/p5-independent-completion-20261009/`. Primary verified actual receipt/log hashes,
  all20post-input hashes, `eeea71c` HEAD and unchanged sole pending assignment-ledger bytes.
  No product/test/document/checkpoint/index mutation by Runner; ambient umask0002 unchanged.
- Fresh full suite remains **FAILED: 1failed/6044passed/30skipped/98warnings**,751.92s/exit1,
  log SHA256`e3a2a5ddd7a6eb29d05b8e33ad7368f213ba3ece82778d5c31c39a6da0bd1ded`.
  P5-ROUTE-01's committed-HEAD witness passed. New **P5-OBS-01 (origin independent Test Runner,
  OPEN)**: `test_spatial_data_mcp_workflow_example.py::test_workflow_example_requests_polls_persists_and_downloads`
  failed at `_wait_for_job`'s AI list observer,409 instead of200 while the subprocess creates its job.
  Runner's isolated3/3passes demonstrate intermittent observation, not a root cause or waiver.
  Do not rerun the whole suite blindly or call it green; trace the exact refusal and reproduce the
  preserved-contract interleaving before choosing an in-scope harness/contract repair.
- Fresh remaining checks: archive strict exit1/251checked/251original/249destination, same four
  findings only; twelve original blobs independently materialized/hash-matched. Scoped4-file mypy0;
  broad109errors/14files/exit1 matches pre-P5 control with0added/removed. Markdown146links/0broken,
  both required YAML evidence paths exist. Unchanged P4 source353/input22(18PNGs)/design/runner/log
  hashes match; reuse77E2E/15explicit skips/0fail/0flaky, not a fresh/live browser run.
- SDK49/checker29/routing69/static6 are explicit unchanged-input **REUSED** evidence. Receipt's
  full-suite `warnings` parser field17 counts warning-summary entries; actual pytest summary says98
  warnings and remains the authoritative count. Strict archive, broad types, fresh environment/host,
  actual customer rights/data/first-flow and successor approval gates remain open. Task5 not closed.

- P5-OBS-01 cause verified by controlled real-HTTP interleaving: prepare an empty AI job page,
  issue one genuine Core POST on the same generated lane before publication, then send the page.
  Actual result409/`REPORT_CONFLICT`, no AI acknowledgement or protected items; fresh AI page200,
  existing authenticated worker pending queue200 with the exact issued ID. Original `_wait_for_job`
  deterministically raises on this interleaving. Probe receipt
  `/tmp/opencode/p5-obs01-investigation-20261009/probe-receipt.json` binds original testb1a75f2b,
  metadata-responseca94a50b and egress9f259b32. Two probe setup failures (missing test-support path,
  group-writable shared scratch rejected by spool gate) are excluded; no gate was weakened.
  Private generated roots under sticky `/tmp` preserve the same spool protections as pytest.
- Authority/pattern: approved data-MCP plan`2026-10-06-spatial-data-mcp-v1.md` Task2Step4 requires
  exact projection-drift409 rather than stale metadata. `metadata_response.py:355-356` and
  `ai_egress.py:214-223` enforce it; the whole-suite failure is a test-orchestration assumption,
  not proof of a broken delivery guard. Its consumer workflow itself uses CREATE/GET, not this list.
- Bounded repair binding: RequirementsRB-04/06/09; owner`tests/contract/`; acceptance deterministic
  overlappingGET/POST witness RED→GREEN, preserved AI409/noack negative, existing example real SDK/
  worker/download/same-key/refusal coverage and independent full suite. Contracts affected:none.
  Reference: existing real generated lane and authenticated worker pending route. Adoption: retain
  unchanged product API/SDK/response/currentness and use worker identity only in private test dispatch.
  Files: `tests/contract/test_spatial_data_mcp_workflow_example.py` plus existing evidence records.
  INV-040 is enforced by real responses/bytes; INV-060/061 by unchanged distinct worker/AI permissions,
  scopes/consent/currentness/ack gates and negative tests. No HIL/vendor/customer/license/rights change.
  Rollback: reviewed inverse of the task-owned test-only repair; no data/index/history reset.
- Ruling: replace only the private worker observer's AI-list use with the **existing worker pending
  queue**, exact generated worker token/instance and same finite deadline — no ADMIN stand-in, generic
  conflict retry, 409 waiver, longer sleep, consumer downgrade, policy/grant or product change. Cost if
  wrong: readiness could mask AI-list regression; deterministicAI409/noack and retainedSDKlist negatives
  explicitly protect that boundary. Keep the original200/ID/result/byte assertions strict.

- Deterministic regression `test_worker_observer_handles_issue_between_empty_read_and_send`
  reproduced **RED409/200** with the original observer; companion
  `test_ai_job_page_refuses_issue_between_empty_read_and_send` passed the unchanged protected409/noack
  control. Repair uses `SPATIAL_DATA_WORKER` and exact activation instance on the existing pending
  route; original SDK CREATE/GET/receipt/download/idempotency/refusal assertions remain unchanged.
  Scoped final four-file workflow/AI-egress/worker-API/SDK-HTTP matrix **122passed/exit0**,46.85s;
  test SHA256`525b754ed0ba8810bc71213ac08cbc1b8fc2ca30e22104d2583a99b0f9396c5a`.
  Receipt SHA256`64c92c94e7e8742906d2f159f981bd5eb3bf1475f48afba1ed0138715d60104a` at
  `/tmp/opencode/p5-obs01-investigation-20261009/repair-receipt.json` binds RED/GREEN logs and source.
  Changed-file Ruff0/whitespace0; scoped test+explicit native-window example module mypy2clean.
  Bare single-file mypy reports one unresolved flat example import identically before/after; no new
  diagnostic. One wrong explicit-module path command exited2/no checking and is excluded. The broad
  gate remains failed109/14, not made green by this scoped command.
- Narrow observer witness is fixed locally, **not integrated completion**; commit this test/evidence
  revision before freezing and assigning the affected independent full suite. Do not rerun unchanged
  archive/type controls or P4/browser work unnecessarily; verify reused-input hashes. No source writer
  overlaps that final run. Preserve both genuine independent failed-suite logs and their causes.

- Observer repair/evidence committed locally as`a8f6e93` (three task-owned paths, staged whitelist/
  whitespace checked). Final independent assignment is only the affected full active Python suite,
  whole Ruff and broad-type delta against the already-matched control, plus pre/post frozen-source/
  Git/receipt hashes. Required source is this actual commit plus assignment-only ledger prose;
  freeze21whole-P5 paths. Earlier archive/recovery/path/P4/static/SDK evidence may be reused only on
  unchanged inputs; do not duplicate the completed twelve-minute suite merely to sample timing.
  Test Runner remains read-only with one compact driver/receipt, no further agents or product/docs/
  checkpoint/index/HEAD writes, installs, runtime/browser/Docker/CI/credentials/grant/policy/external
  changes. If any test fails, return exact test, assertion and safe reason/trace; no waiver or fix.

### P5 final independent receipt recovery and full-objective adjudication — 2026-10-09

- Resumed actual checkout: `main` `a8f6e938c8a8c633983f12792973dcdb24aaecd6`, only the10-line
  final-assignment prose pending, clean index; four foreign worktrees unchanged/untouched. Native
  goal `b13320f7` verified active with its full objective; prior unmet goal is not resumed.
- One-shot interrupted-handoff recovery found the existing final Runner's **finished** receipt,
  timestamp2026-10-09T05:06:35Z, SHA256
  `124a13d45083eec069ffa245253497fc2bbaae433ec89712d54f36df30a577de` at
  `/tmp/opencode/p5-observer-independent-final-20261009/receipt.json`. No progress polling, duplicate
  test or new Runner was started. Earlier waiting summaries are superseded by the actual completed
  artifact; the missing completion notification is not evidence that the suite still runs.
- Runner `ses_ee103b8c0ffeHhl4qT8rAFSozC` actually ran
  `uv run --no-sync pytest -q -p no:cacheprovider`: **6047passed/30skipped/98warnings/0failed/exit0**,
  754.96s (driver wall756.39s), ambientumask0002/Python3.12.13. Raw log SHA256
  `6bccdbc2e3ad9da4b3cb49476ecc411e4598d04bc791f9cc4e8347572c2b8fc9`. Both routing and deterministic
  observer/AI409 controls are included; previous `efae2af` and `eeea71c` failed runs remain RED
  historical evidence. Configured30skips are still omitted coverage, not successful tests.
- Final wholeRuff exit0, log82b3e6a6; explicit workflow+native-window example scoped mypy2files
  clean/exit0, logf9b031e5. Broad`uv run --no-sync mypy packages services tests tools` still
  **FAILED109errors/14files/753checked**, log546479e8; independent pre-P5 error `(file,message)`
  multiset added0/removed0. Two extra note-hint lines are not new errors or a broad pass. Final receipt
  pre/post21frozen inputs, HEAD, sole pending assignment bytes and19reused inputs match unchanged.
- Primary reception `/tmp/opencode/p5-final-evidence-reception.json` SHA256
  `6d4fc44d1a0e8aa6a12645ea17b34f58d01bcb7f24232f3d9699bfdd99ddeb18` verifies actual final/prior/
  repair/control/report hashes, all21+19inputs,251destinations/originalGitblobs and12recovered scratch
  blobs. Strict archive remains251original/249destination,2adaptations/4findings/exit1, not waived.
  P4source353workspace/352Git,22render inputs/18PNGs and10verification inputs match; reuse prior
  design5635f47b/receipt e6267ceb/77E2E/15explicit skips, not fresh/live browser evidence. One reception
  adapter label/path mismatch was corrected against the JSON schema; no product/source mutation.
- Whole-P5 source report7bcb406a and finaldeltaf08feaa8 received; no required residual findings.
  Adjudication: review-declined execution is now owned by the actual independent final receipt;
  archive/recovery hashes are independently received; aesthetic judgment stays with the P4 design
  report; missing fresh dependency/image/CI/TLS/host/customer/rights/first-flow inputs stay OPEN.
  Deferred MIN-1 review-diff context options and MIN-2 quiet SDK per-test output remain hygiene-only.
- Self-origin evidence-hygiene limit: Task3 seven static logs match reception33bb1ff5, actual
  entrypoint264/2warnings and utility79/2warnings tails rehashed, and the seven registered worker
  entries are source-bound. Quiet artifacts do not preserve complete17/6-file argv; no historical
  command is invented or repeated to manufacture proof. Final configured6047suite is separate.
- Full-objective checklist and all RB-01..09 dispositions are durable in
  [integrated audit](../../audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md) §§7–9. Local
  authority/parity/history/security/unchanged-Console evidence is distinguished from strict archive
  failure, mixed defaultNodeODM, broad types and fresh runtime/CI/host gaps. The real first experience
  remains Site/WorkArea→permittedt0/t1→compatible pair→evidence-bound change/blocker→same-area t1/t2
  with one selected actual consumer. F01bootstrap/grant ownership and F02–04permitted data/rights/
  protectedstorage/graph/workers/host/customer acceptance are not replaced with generated fixtures.
- P5 Task5 record-closeout binding: only this ledger, the integrated audit, product-state summary and
  the written successor proposal; ignored checkpoint/skill progress never committed. No source,
  template, tests, dependencies, contracts, state, credentials, permissions, UI or archive writer.
  Preserve spec14ded50b/P5plan4119e5d1, milestones/Current slice/registry status and originals. Run
  affected69routing+30move-tooling consumer checks and link/whitespace/hash/scope checks; inspect
  actual index and locally commit only those4records before claiming the report deliverable closed.

### P6 canonical written proposal — approval waiting, not implementation

- [Two-task P6 proposal](2026-10-09-platform-only-default-deployment-template.md), SHA256
  `ccee1d92c440e342d0d504902ad06ef782148d66455db321a54bade3d0707425`, transferred from the source-bound
  scratch proposalfa8b0362 after actual P5 receipt recovery/reception. The transfer updates final
  evidence/status and explicitly names the VM interpolation test; scope/preservation values unchanged.
  Proposed changes only: remove unused NodeODM from base/VM, preserve historicalksi-odm and all other
  service/executableDockerfile settings, reconcile active docs/VM/image assertions, independent local
  checks. No optional managed runtime, new API/format/policy/auth or operational assembly.
- Canonical self-review38read-only checks/0failures/13exactinputs/sevenservice semantic hashes,
  original volume maps/executableDockerfile/spec/snapshot/existing test targets and written gates.
  Receipt `/tmp/opencode/p6-canonical-source-review.json` SHA256
  `eaa99e4a305cd445ccbb95fed7d2824d7e7f6e31750a43d891b88f8e078ffbd4` (latest reconciliation after
  the product-state summary was added). Initial scratch adapter's Git status-prefix parser was
  corrected; actual scope is the4named pending records/proposal, not foreign work.
  No proposed P6 test, Compose CLI, container, sync/install/runtime action was run.
- Self-review against approved spec: §§2/6/8/9 default-runtime subset→Task1; revision/independent/
  truthful handoff→Task2; all other RB/customer gates excluded explicitly, not claimed satisfied.
  Shared Task1→Task2 service/volume/source snapshot interfaces agree. Existing VM Dashboard/Caddy
  additions, four long-running network checks, safe!resetloader and historicaldigest controls retained.
- **Human written review is required** for this exact plan before implementation; preserve the already
  chosen sequential execution method, do not reopen its selection. Recommended next authorized
  engineering slice only after that review. P6 approval does not authorize fresh sync/image/boot/CI,
  live grant/policy activation, deployment/customer transfer/contact or close archive/first-flow gates.
- Full-goal remaining owners: Human/build/ops for exact isolated fresh environment effects; Human/
  lineageowner for adaptation-lineage decision; Human/security/product for F01bootstrap/grants;
  Human/customer/ops for F02–04permittedt0/t1/t2/rights/protected configuration/selectedconsumer+host
  and actual two-cycle acceptance. Technical P5 report closure is not whole-goal success, product
  slice/EXT-VAL acceptance or external delivery. No successor execution inferred from continuation.

- Closeout preparation checks on `a8f6e93`+these record-only changes: exact five-file
  product-boundary/disposition/normalization/archive-boundary/move-tooling command
  `uv run --no-sync pytest -q -p no:cacheprovider tests/contract/test_physical_site_product_boundary.py tests/contract/test_physical_site_disposition.py tests/contract/test_repository_normalization.py tests/contract/test_acquisition_archive_boundary.py tests/contract/test_physical_site_move_tooling.py`
  **99passed/exit0**,6.35s; whitespace exit0. Read-only record-check receipt1a998939 verifies154local
  Markdown links/0broken,18non-record frozen inputs, immutable spec/P5plan, preserved product-state
  Milestones/Current slice/Backlog and exact4record-only scope; no P6implementation exists. That
  receipt is a precommit record snapshot, not the later postcommit state. Commit only those4paths;
  verify the actual committed HEAD's affected consumer checks and final record snapshot afterward.

### P5 local verification-report closure / P6 written-review gate

- Record/proposal-only local commit `7bc76934b1ecc9ccd90fff93e492a8833b587559`: exactly4named
  paths, staged whitelist/workspace equality/whitespace checked, index/checkpoint/secrets and foreign
  work excluded. No source/test/template/runtime/permission change or external action. Actual
  committed-HEAD five-file consumer/routing command above **99passed/exit0**,6.24s; log SHA256
  `895e50530986ca98d631eb10f904236660a151b742d9890e4b102074a770b8e0` at
  `/tmp/opencode/p5-closeout-postcommit-99.log`. Git was clean afterward.
- Final record reception SHA256 `43a14e0da794d0581c827d4096fbc08fe81d09c476715a0c040dfcb3fc6225c8`
  at `/tmp/opencode/p5-closeout-final-record-check.json` binds actual `7bc7693`, four record hashes,
 154valid local links/0broken,18unchanged non-record frozen inputs, exact unmodifiedspec/P5plan/
  product Milestones/Current slice/Backlog and P6planSHAccee1d92/no implementation. This paragraph
  and the audit's final status are receipt-only follow-up metadata; source/consumer links do not change.
- **Tasks1–5 local P5 verification/report deliverable is CLOSED**, using its explicit discrepancy/
  unverified-report path, not an archive/type/runtime waiver or whole-cleanup acceptance. Independent
  source `a8f6e93` full6047/30/98/0 + Ruff/scoped-types, whole/delta review, preserved failures,
  source-bound P4 reuse, all RB rows and full-objective/owner checklist are reconciled. Scoped
  engineering usability: existing generated actual-platform register/inspect/Analysis/data/API-MCP/
  history/recovery paths can be exercised in the prepared environment; production/realcustomer and
  configured successful Console data/result loop remain unverified.
- Deferred hygiene: MIN-1 record diff-context options, MIN-2 retain SDK per-test output, and self-origin
  Task3 missing full17/6argv. No retrofitted command, new source sweep or duplicate full test. Four
  foreign worktrees, immutable original archive and private state remain preserved; no task-created
  workspace requires removal. Evidence scratch is kept rather than discarded before Human review.
- **Next is Human written review of P6ccee1d92**, preserving the sequential method. Until that actual
  approval, no P6 implementation or automatic retry is authorized. Remaining full-goal gates and
  responsible owners above stay OPEN; local report closure does not reduce or complete the objective,
  close EXT-VAL/customer/operational acceptance, or deliver externally.

### P6 written execution approval and preflight — 2026-10-09

- Human answered **“P6 실행 승인 (Recommended)”** after reviewing the linked two-task
  [P6 plan](2026-10-09-platform-only-default-deployment-template.md), SHA256
  `ccee1d92c440e342d0d504902ad06ef782148d66455db321a54bade3d0707425`. This is actual approval,
  not inferred from goal continuation or the frozen proposal header. Preserve sequential inline
  execution and independent final Reviewer/Test Runner; no new runtime/install/CI/deploy/grant effects.
- Base/target: original checkout `main` `a0daa32bca28e894ee2bedc25479d578e95c31a6`, clean index/
  tracked state before approval prose; four foreign worktrees retained. Current native goalb13320f7
  verified active, full objective unchanged. P5 report sourcea8f6e93/records7bc7693+metadataa0daa32.
- Thirteen exact proposed-input hashes match the approved plan; scoped preflight snapshot
  `.superpowers/sdd/2026-10-09-platform-only-default-deployment-template/task-1-inputs.json`, SHA256
  `dbc60b0237b68d80089a25cc3a540e538633e67863d4ab176f90bacf3370ccca`. Docker CLI is present;
  prepared example-only Compose config may run through the named test. Broken/missing Compose
  plugin is a genuine capability failure, not permission to install or create an environmental skip.
- Implementation contract: RB03/08/P5-COMP-01; owner deploy templates/comments/current ops prose
  and the three named contract tests; no service/API/schema/permission/profile/data-format change.
  INV040 truthful failure/unverified reporting and INV054 pinned references/historical digest controls
  enforced; INV020/024/050/051/053/055/060/061 preserved by unchanged engines/auth/state/contracts.
  Existing volume identities and all remaining service maps/executable Dockerfile lines are frozen.
  No customer/license transfer, reconstruction engine execution or HIL assumption; rollback is a
  reviewed inverse task-owned local change, never reset, live lifecycle or volume deletion.
- Preflight Task1→Task2: actual source/semantic dictionaries, named volumes and Dockerfile snapshot
  are the independent verification inputs; one writer, no conflicting interfaces. Static tagged-YAML
  loader recognizes only existing!reset. Existing VM and image-reference assertions must be reconciled
  with the authorized service removal, retaining Caddy-only ports/networks and historical NodeODM pin.
- Execution checklist and artifact-level results stay in the task's ignored skill ledger; this parent
  ledger owns approval, durable rulings/source/verification and remaining full-goal gates. Task1 starts
  with service/mount RED witnesses and pre-change preservation controls, not production edits first.

### P6 Task1 RED/GREEN and revision-bound release control

- Actual pre-removal witnesses: new template matrix2failed/8passed (NodeODM service/mount, not a
  loader error); expanded static+actual Compose+pin matrix4failed/9passed/0.15s, raw RED log SHA256
  `ad1340e27aeeed2b57802637b23b1d9cae6c1a22ec00e2ea02f06e0e9e4811c5`. VM config actually merged
  the original NodeODM; canonical historical digest control already passed. Eight preservation controls
  passed before removal. Minimal removal gave the same13selected checks **13passed/exit0/0.14s**.
- Source changes: only NodeODM service in base/VM, comments/current startup prose and the three
  named tests. Seven remaining service dictionaries, named-volume maps and executableDockerfile
  preserved; historicalksi-odm declaration remains unused. Current docs require protected OIDC subject
  registry and distinguish optional trusted Analysis/external configuration from local SpatialData
  assembly; old keys/acquisition/Copilot/backup/staging procedures explicitly historical/evidence-only.
- First complete nine-target Task1 matrix **1failed/126passed/7.98s**, logSHA
  `dd789f3caf2c1e8cf20d7deb96f47eb155d2dd513546de5aca052fb2d84c5b0a`. Failure is the unchanged
  `test_stage_consumes_the_canonical_generator_output_without_legacy_manifest_fields`: release
  generator snapshots GitHEAD a0daa32 while stage validator scans the edited worktree. Read-only
  probe121b9ef0 proves committed10references versus working9, only historicalcanonicalNodeODM removed,
  zero added refs. Generator, release schema, pin CLI and runtime-stage script are unchanged.
- Task1 Ruling (self-origin evidence/order issue): preserve exact release/source guards and bind the
  full matrix to the actual committed candidate rather than modifying its read-only contracts/test
  or pretending the uncommitted run passed — a local reversible commit is needed for HEAD/worktree
  identity convergence, as with the already-planned HEAD-aware consumer gate — cost if wrong:
  candidate remains provisional with a failing gate and needs bounded repair; no deployment/exposure.
  Do not mark Task1 complete until the actual committed matrix is green. This is not a security waiver.
- Preparation: pinCLI0, scopedmypy3clean; initial new-test8E501linewrap findings fixed without semantic
  change and scopedRuff now0. Exact10task-owned paths (nine Task1 files+this approval/evidence ledger),
  17local Markdown links/0broken and whitespace0; eight read-only contract/tool/env/lock inputs match
  HEAD. No sync/install/image lifecycle/CI/credentials/volume or service operation. Commit candidate,
  then immediately run unchanged full Task1 matrix/pins against that real revision before Task2 freeze.

### P6 Task1 committed checks / Task2 independent freeze

- Candidate commit `12547470e5c1abfa2a5b232995429a6c0bf4bb25` contains exactly the10whitelisted
  paths; staged bytes/index/whitespace inspected. Same exact nine-target Task1 matrix at actual HEAD
  **127passed/exit0/7.70s**, including unchanged canonical release producer/consumer and committed
  move-tooling. Runtime pin CLI exit0. The release/source mismatch closes by correct revision binding,
  not a schema/script/test change, stashed source or false-clean Git override by Primary.
- Task1 local template/test/doc output is complete; full independent P6 verification/review is still
  required. Actual example-only Compose config proves the five-service merged graph, private VM
  networks and Caddy-only80/443 publication; no live image/container/volume operation. Existing
  service maps, executableDockerfile and historical-volume names pass frozen preservation controls.
- Task2 assignment: one read-only source Reviewer over a0daa32..1254747 and approved spec/plan;
  independent Test Runner at1254747 plus only these record-status/assignment changes. Freeze current
  required-file hashes before dispatch; no product/doc/index/HEAD writer while checks run. Test Runner
  owns actual commands/results/ambientumask and pre/post hashes, not an author summary. Fullpytest,
  exactTask1matrix/normalization/pins, offline lock/boundaries/R3, Ruff, scoped3/broad-control mypy,
  strictarchive251/249 and P4matching-input reuse are required; no duplicate full run or live browser.
- Security/material/external gates unchanged: no install/sync/pull/build/up/run/deploy/CI/grant/
  credentials/equipment/customer action. Failed109type/2archive and unverified fresh runtime/host/
  first-customer gates remain explicit. Reviewer findings are advice; actual affected checks and Primary
  receipt audit decide scoped technical closure. Native full goal and EXT-VAL acceptance remain OPEN.

### P6 independent receipt reception and local adjudication — 2026-10-09

- Test Runner `ses_ee09b654effe528h8QkONWb2F0` completed all11commands at source
  `12547470e5c1abfa2a5b232995429a6c0bf4bb25`. Its initial return exhausted its step budget after
  execution, before the final receipt. Same-seat continuation finished only hashes/links/source-state/
  evidence finalization; no test/tool/full-suite replay. Receipt finalized `2026-10-09T07:02:30Z`:
  `/tmp/opencode/p6-independent-verification-20261009/receipt.json`, SHA256
  `58a17d1f2c001df8bee1532389b07808df7ae50236a8ffab95dddfcd12ca5510`.
- Pre/post HEAD1254747, empty index, ambientumask0002 and exactly3record-status paths matched;
  pendingdiffSHA `92b52945cdda19384ed22df8ea41a9915f4347f467d3fe8ac05245341cf77bb2` and
  all45snapshot inputs matched pre/post. SnapshotSHA
  `b8574812b191d3c08ab75e9110f33299f8938824d5ad45fe08f6e474ab08ef42`. No source/doc writer
  overlapped execution/finalization. The receipt is point-in-time evidence, not a future-HEAD claim.

Exact independent commands/results (raw logs in the same narrow directory as the receipt):

| ID / actual command | Actual exit/result | Raw log SHA256 |
| --- | --- | --- |
| 01 `uv run --no-sync pytest -q -p no:cacheprovider -rs` | 0; **6058passed/30skipped/98warnings/0failed**,753.84s pytest/755.46s driver | `f233165ce1fa2d9998af679ccdde7cee074a8eebdff32b394a5b2cc8588b717c` |
| 02 `uv run --no-sync pytest -q tests/contract/test_platform_deployment_template.py tests/contract/test_vm_deployment_contract.py tests/contract/test_deploy_env_contract.py tests/contract/test_runtime_image_pins.py tests/contract/test_release_evidence.py tests/contract/test_external_runtime_deployment_contract.py::test_release_image_binding_accepts_the_canonical_nodeodm_digest_only_exception tests/contract/test_acquisition_archive_boundary.py tests/contract/test_platform_boot_switch.py tests/contract/test_physical_site_move_tooling.py` | 0;127passed/7.71s | `84ea953d2fc6f4e7fb2298feaeec882038aca2ed5e27794d0d07adb7734a0e58` |
| 03 `uv run --no-sync pytest -q tests/contract/test_repository_normalization.py tests/contract/test_runtime_image_pins.py` | 0;37passed/0.76s | `58f961c52e25edfb35a65a3466333aa09b155d2d633179c681d427450ed160f3` |
| 04 `uv lock --offline --check` | 0;157packages | `2b0b79c2a879b42cb8b3d1713d265d83991e20075b94451232bc8bf6d1fa3acc` |
| 05 `uv run --no-sync python tools/check_core_module_boundaries.py` | 0;140inventory records | `0483fb03a7ccab5e3bc6c01600e182cda5866ac03a3d9b6e4697d5d2fe870634` |
| 06 `uv run --no-sync python tools/validate_repository_normalization.py --check-r3-migration` | 0;R0–R3contract | `3e23f59a39681d7997bc7a7c45a275c3fe433e7a2ec6cb92ec928de88621c052` |
| 07 `uv run --no-sync python tools/check_runtime_image_pins.py` | 0 | `56faa80feaa8d7183e05394773ae966a87f0499f59e26bab13339e17393d5db3` |
| 08 `uv run --no-sync ruff check .` | 0 | `fe9902ddda7cef3ceeb61d97ca27dd2152aab325a6f6c7397267e2bcb4e49123` |
| 09 `uv run --no-sync mypy --follow-imports=silent tests/contract/test_platform_deployment_template.py tests/contract/test_vm_deployment_contract.py tests/contract/test_runtime_image_pins.py` | 0;3files clean | `546b16bf1a4c12f0e5d38bfec54284d7d3928dff359c1a905039f504e1b412ed` |
| 10 `uv run --no-sync mypy packages services tests tools` | **1/FAILED**;109errors/14files;0added/0removed error multiset | `8f38d6ac3be4f58538076fe33a7c09767f2d1937e13bf5ae56b84ef5715edf65` |
| 11 `uv run --no-sync python tools/verify_physical_site_archive.py --root . --execution docs/audit/PHYSICAL_SITE_MOVE_EXECUTION_v1.json --extras docs/audit/PHYSICAL_SITE_MOVE_EXECUTION_EXTRAS_v1.json` | **1/FAILED**;251original/249destination matches;2adaptation rows/4findings | `e85b106b60949c8fcd93648a716681d7c9fb063c53a6a3c402ebd907f8885c22` |

- Thirty skips are coverage not exercised, not passes. Raw `-rs` records28events/30tests: S3-live10
  (one aggregated3case event), optionalmodel12, historical geo-golden5, genuinebundle1, realstream1,
  root-onlyACL1. Receipt `skip_buckets` counts events (S3=8), not weighted tests; Primary's raw-log
  reception records the weighted count10. No Docker/Compose skip: the example-only merge test ran.
- Same broad controlSHA `546479e8501427592ac20d842058ad7c424a76171e0b7f72898052cf5d4378ef`:
  exact `(file,message)` error Counter identical, not just109count equality. Archive extras55/56 retain
  both `GIT_OBJECT_MISMATCH` and `DESTINATION_HASH_MISMATCH`; original manifests/strict tool unchanged.
- Seven service semantic hashes, all named-volume maps and executableDockerfile hash match plan/base.
  Relative-links38/0broken. P4matching353workspace/352Git/22render inputs(18PNGs)/10verification inputs
  and report5635f47b are **REUSED**, not fresh browser/design/build evidence or real-customer flow.
- Whole-P6 Reviewer `ses_ee09cd9e1ffenXB2pcw4yOVJOD` read the actual ten-path diff/factory/contract
  bindings and five review focuses;0Critical/0Important/3Minor. Report
  `/tmp/opencode/p6-independent-review-20261009/P6-REVIEW-20261009.md`, SHA256
  `d5aaa400e21d76e00cca6b9daeeb50650fa7ef45527e03bf917b44fdfb9f3fa4`. No test/Compose/pixel execution
  claimed by Reviewer. It recomputed key snapshot entries only; Runner/Primary matched all45.
- Primary reception `/tmp/opencode/p6-primary-evidence-reception.json`, SHA256
  `1f5bfc9ec0b8cd9a2c9c0887583d74814bea81f7c3ad4ca94dfc80cd4a42d189`, verified actual receipt/report/
  all11logs/all45inputs/pendingdiff, broad Counter and strict findings. This is reception, no replay.

#### Final source-review disposition and set-aside rulings

After actual prose/source inspection, all three findings remain nonblocking Minor; no product/source
repair is inferred from optional advice. Historical no-execution/no-delete warnings already apply.

- Final: minor (deferred), **P6-M01** (origin Reviewer): `docs/ops/DEPLOYMENT.md:265` has the historical
  regenerable-cache line without a repeated inline no-delete qualifier. Current§0 and historical§1–9
  warning expressly prohibit applying it to extant unique volumes. Follow-up prose improvement only.
- Final: minor (deferred), **P6-M02** (origin Reviewer): `docs/ops/VM_DEPLOYMENT_READINESS.md:81–95`
  retains imperative wording below a no-execution historical header. Future record-polish should use
  descriptive historical voice; no script/lifecycle or current recovery promotion is authorized.
- Final: minor (deferred), **P6-M03** (origin Reviewer): canonical-digest test diagnostic `line=1`
  follows the exact approved plan and affects only a hypothetical violation location; it is not a
  lookup, pin exception or passing guard. Future optional test-triage annotation may name real line76.

Each Reviewer “Declined to judge” item is adjudicated in its reported order:

1. Final: Ruling: execution/types/archive/P4hashes — use independent Runner's actual terminal logs and
   source-bound receipt above, not Reviewer counts — cost if wrong: technical closure must reopen.
2. Final: Ruling: fresh sync/images/boot/CI/host/TLS/UDS/ACL — remain UNVERIFIED; P6 excludes effects —
   cost if wrong: independent build/run readiness remains unproved, never a production-ready claim.
3. Final: Ruling: permittedt0/t1/t2/rights/grants/accuracy/customer acceptance — retain F01–04 and
   actual two-cycle requirement; do not substitute generated fixtures — cost if wrong: product goal unmet.
4. Final: Ruling: `.env.example` historical fields — keep exact file-map exclusion plus current warning;
   no provisioned files/mounts inferred — cost if wrong: future ops preparation must resolve stale inputs.
5. Final: Ruling: external/synthetic candidate Compose — unchanged separate scopes, not proof of current
   default/VM readiness — cost if wrong: later candidate verification remains needed, no lifecycle now.
6. Final: Ruling: analysis-pilot NodeODM/cache — retained historical/out-of-default evidence, not a new
   platform dependency or cleanup target — cost if wrong: independent future audit, never silent deletion.
7. Final: Ruling: precommit release refusal — accept read-only10→9probe plus actual committed127/full6058
   passing unchanged guard — cost if wrong: source-bound release evidence gate reopens, no waiver.
8. Final: Ruling: P4pixels/mobile/aesthetics — unchanged-source prior design/functional evidence only;
   no new visual judgment, runtime or real-byte claim — cost if wrong: changed-source design review needed.
9. Final: Ruling: final3record prose — Primary checks scoped diffs/links/frozen milestone and acceptance
   fields, then affected committed-HEAD consumers — cost if wrong: repair those records before closure.
10. Final: Ruling: signed-Mission/device semantics — historical invariants stay immutable; no acquisition
    execution or safety promotion — cost if wrong: historical contract/replay verification remains required.

- Task2 Ruling: step-limit recovery continues the same Runner only for missing finalization, reuses
  matching terminal outputs and runs scoped final record checks instead of replaying the755second
  suite — why: actual commands are complete and source unchanged — cost if wrong: incomplete evidence
  would block closure; immutable logs/pre/post/input checks are the control, not a guessed pass.
- Local record closeout owns only parent ledger/audit/product-state; ignored checkpoint/skill outputs
  stay uncommitted. No task-created worktree exists; four foreign worktrees and narrow scratch evidence
  are preserved for review, no broad cleanup. Full objective/RB02/03/08/EXT-VAL/customer/operational
  acceptance remains OPEN; source-bound local report closure is not product acceptance or delivery.

### P6 local deliverable closure / remaining authorization boundary

- P6's two approved tasks are technically complete locally: acquisition-free default/VM template,
  unchanged state/service/runtime/contract identities and independent source/software/static evidence
  with failed/unverified gates explicitly preserved. This closes P5-COMP-01's declarative graph gap,
  not RB03/08fresh execution or the full goal/customer/EXT-VAL acceptance.
- Fresh scoped record checks:42nonrecord inputs/11rawlogs matched; spec/approved P5/P6 plans and
  pre-P6 ledger history unchanged;38relative links/0broken and whitespace0; product milestones/current
  slice/acceptance/backlog bytes unchanged. Check receiptSHA
  `f72e4213e79cc0c0a279043159935a39dbdb3d2d660ef6dc41f0075d466791f6`.
- Affected record-consumer command at1254747 + only3final record paths:
  `uv run --no-sync pytest -q -p no:cacheprovider tests/contract/test_physical_site_product_boundary.py tests/contract/test_physical_site_disposition.py tests/contract/test_repository_normalization.py tests/contract/test_acquisition_archive_boundary.py tests/contract/test_physical_site_move_tooling.py`
  → **99passed/exit0/6.65s**, logSHA
  `b054eda15449751545844247d79093038b236b659e692493a8ea065383a2b7b3`.
  The local closeout commit contains exactly3record paths; final HEAD/clean-index/checkpoint and
  committed-HEAD consumer reception follow this checked record revision, not a repeated full suite.
- Finishing uses the already authorized original checkout/local main target, no menu/new merge/push
  permission and no foreign-worktree cleanup. Narrow ignored proof is retained for review; its hashes,
  sanitized results and limits are durable above. No dependency/runtime/image/CI/credential/data/
  device/customer effect occurred; local commit is not external delivery.
- Remaining goal-serving work requires its real input/decision rather than fixture repetition:
  isolated fresh dependency/image/boot authorization and prepared capability (Human/build/ops),
  append-only adaptation-lineage decision (Human/lineage), scoped Site/WorkArea-bootstrap ownership
  (Human/security/product), permitted same-Site t0/t1/t2/rights plus selected consumer/host and protected
  runtime configuration (Human/customer/ops). Fresh build/run is the next recommended evidence gate;
  an exact isolated-environment plan and explicit effect approval are required before running it.
  No successor implementation, runtime setup, blanket grant or product-state reprioritization is inferred.

### P6 committed receipt / P7 isolated-verification written proposal — 2026-10-09

- P6 record closeout is committed locally at `4a0a08ed1f47b5e66b2b0a42d7f3f2ea0936c9bb`:
  exactly parent-ledger/integrated-audit/product-state, tracked/index clean; source remains1254747.
  Committed record check `/tmp/opencode/p6-final-committed-record-check.json`, SHA256
  `e4c502c3608de34ec09113f31a4c6fa37e1fa3ee7b5caebedbfb7708dd248e2d`:42stable inputs/11logs/
  38links0broken, spec/plans/history/milestones/slice/backlog unchanged. Actual five-file record-consumer
  command from the preceding closeout ran at committed4a0a08e: **99passed/exit0/6.36s**;
  rawlogSHA `4a506f277a8d6b8fc20b97849b42979a330c6058929e46072e45ae2c8043529b`, receiptSHA
  `b1d97ed714ad609a03d3699b5d9651e376ad3fca72156d70d15f719c4c0e1aae`. These point-in-time
  receipts do not claim future record HEADs or a fresh runtime/full-suite rerun.
- `writing-plans` produced the [P7 isolated fresh-verification proposal](2026-10-09-isolated-fresh-platform-verification.md),
  SHA256 `fba7776eb022ffb3e87f7c062f25cfb4f98a18bbb5311d786a48aff568f18909`.
  **Approval waiting; NOT approved/executed.** Preserve the already selected sequential inline method
  and independent final Reviewer/Test Runner. No goal continuation or P6 closure grants these effects.
  Execution approval/progress is recorded in the dated P7 sections below (e.g. the 2026-10-09 P7
  written execution/effect approval); this bullet remains a frozen snapshot.
- Frozen intended source:4a0a08e, same product files as1254747; new report/status commits do not change
  that source binding. Three tasks: fresh locked Python environment/full/static evidence; three unchanged
  Core/inspector/measurement candidate images; isolated three-service Core/MinIO boot plus real TCP
  auth/tenant/idempotency/journal/storage restart evidence. Inspector/measurement checks are import/
  packaging only, not signed production workers, numerical execution or host-containment acceptance.
- Required separate effect approval is exact/bounded: one clean task-owned detached worktree,
  new scratch environment/cache, public fixed-source package/image/apt downloads, three local builds,
  synthetic TTL24h credentials and new project-owned volumes/network/containers, loopback-only dynamic
  ports, controlled restart and owned-container/network teardown. No host/CLI/Python install, old `.venv`
  mutation, private credential copying, existing state/grant change, daemon restart, registry/CI/push/
  production deployment, image/volume prune or customer/device operation. Cold estimate1–3h,60GiB
  storage headroom/32GiB RAM prerequisite;4h safety rail. Shared-daemon base blobs/cache are disclosed,
  not a pristine-host claim. No scratch/worktree/image/runtime has been created for P7 while drafting.
- Self-review against spec14ded50b §§2–4/6/8–10: five contamination/private-input/ownership/persistence/
  readiness failure classes have task assertions; explicit source/receipt/image/resource interfaces;
  three tasks and28required sections/boundaries,17actual input files unchanged,2plan links valid.
  uv configuration research identified that `--no-config` would drop project rules: proposed explicit
  config preserves filesystem settings and unchanged workspace/source metadata; native flag/config
  acceptance remains a preflight, not an assumed successful sync. Docker CLI metadata is prepared
  aarch64/uv0.11.15/Compose5.2.0/local socket; daemon/build reachability remains UNVERIFIED.
- P7 can add RB03boot/RB08fresh-install-build/RB09 evidence only; activation/data/Analysis paths,
  broad109type/strict2archive failures, F01OIDC bootstrap/grants and F02–04permitted same-Site epochs/
  rights/consumer+host/configuration/repeat customer acceptance stay OPEN. One synthetic Site/object
  restart is not the full first experience or a substitute for customer `t0/t1`→`t1/t2`. No milestone,
  current slice, backlog priority, product/EXT-VAL acceptance or native goal closure is inferred.
- Next decision: Human written review of planSHAfba7776e plus its listed download/install/build/boot/
  temporary-credential effects. Recommendation: approve this bounded verification plan, preserving
  the selected execution method; do not broaden it to production setup or resolve unrelated rights/
  bootstrap/lineage decisions implicitly. Before approval, no successor implementation or meaningful
  runtime trial is authorized; do not repeat old fixture suites merely to manufacture progress.
- Proposal reception at4a0a08e + only the new plan/three status records:42frozen nonrecord inputs
  match; prior ledger/audit and milestone/slice/backlog bytes preserved;37local links0broken.
  `/tmp/opencode/p7-proposal-check-before-commit.json`, SHA256
  `950dcf1e53302a3824cd886e368153ea0b5506af38eca405e2c2570571884d16`.
  Same five-file record-consumer argv recorded above → **99passed/exit0/6.37s**,
  `/tmp/opencode/p7-proposal-record-consumers.log`, SHA256
  `de25cad15987f1566092d6fe7d26a133606008838c00e1a7b2f979f15a940289`.
  This verifies planning records, not any proposed install/build/runtime command; the full suite
  remains the received source-bound P6 evidence and is not repeated for a documentation proposal.

### P7 written execution/effect approval — 2026-10-09

- Human answered **“P7 실행 승인 (Recommended)”** to the rendered written-review question for
  [the exact P7 plan](2026-10-09-isolated-fresh-platform-verification.md), SHA256
  `fba7776eb022ffb3e87f7c062f25cfb4f98a18bbb5311d786a48aff568f18909`, recorded at0b31edb.
  This explicitly approves the plan's bounded detached worktree, new locked scratch/image dependency
  downloads/installs, three local image builds, synthetic temporary credentials and isolated Core/storage
  boot/restart/owned-container-network teardown. Existing environment/state/grant protection and all
  no-host-install/no-publication/no-production/no-device/customer boundaries remain unchanged.
- Preserve sequential inline execution and independent final Reviewer/Test Runner; no execution-method
  re-selection. Frozen product source remains4a0a08e, local integration target original main. First action
  is resource/capability preflight; unavailable prepared capability or60GiB/32GiB headroom is a reported
  blocker, not permission to install tools, prune other work or change approved pins/security controls.
- Task1 Ruling: this is immutable-source verification, not production implementation; use the plan's
  real installation/import/test assertions rather than an artificial TDD failure — approved plan explicitly
  states that distinction — cost if wrong: a source change would require its own scoped RED/GREEN repair
  authorization and new source binding, not be hidden in this trial. No product code repair is authorized.

### P7 Task1 independent RED reception / P7-A1 environment proposal — 2026-10-09

- Owned detached source4a0a08e and original main6f37758 remained tracked/index clean during Runner
  `ses_ee03ac8ecffeiQiwqe5B9bZN9f`;2751source blobs/3uninitialized gitlinks/18original environment
  metadata matched. FreezeSHA `bbfa47ae62063c3ac57137f254bee10506783a8f1c635c9c6143054445ce60dc`;
  independent receiptSHA `3ec8f175cd88b006dec6276e5e63e41642840e9aa26d6acb21ebd231bdfedfdc`,
  Primary receptionSHA `50bf94f1f471046c256a09358625d7b592624ee6f74fe292052135ff61fcf5b2`.
- Fresh lock157/exit0; sync101installed/6.55s/exit0; metadata101dists/12new editables/7workers/
  3Core-MCP imports/18old witnesses/exit0. First ambient offline compatibility check is excluded;
  controlled minimal-env lock with empty cache is the qualifying proof. Original5dangling editable
  roots remain untouched; the freshly installed environment has none.
- All seven independent commands ran once (exact argv in immutable receipt/driver). Actual full:
  **59failed/5999passed/30skipped/98warnings/707.87s**, rawlogSHA
  `ebdd443924ee66d89c888a52c358833d50c8da26793997e3ba97ead8e1038e5e`. **NOT complete/passing**.
  Boundaries/R3/pins/wholeRuff/scoped3mypy exit0. Broad mypy exit1,109errors/14files and exact
  0added/0removed `(file,message)` Counter versus prior control546479e8;754checked source files vs753
  is recorded, not used to waive a diagnostic. Raw skip coverage is unchanged and not accepted work.
- Every failed traceback is FileNotFoundError at isolated `HOME/.cache`; affected modules:
  spatial-data MCP client15/config15/stdio12/HTTP9/workflow5, platform HTTP2, AI job snapshot1.
  `spatial_data_mcp_fixture._caller_cache` deliberately requires an existing owned non-writable cache.
  P7 setup did not create it. Warning98 is not a test: actual JUnit6088cases=5999+59+30; Runner's initial
  report line68 “6186” accidentally sums warnings too. Original receipt/report/log/XML stay immutable;
  this correction is canonical and the next receipt must use actual test cases.
- Actual protected-reader cause probe refused a0700directory/0600synthetic file below the approved
  `/tmp/opencode/...` root: `AdapterConfigurationError: protected ancestry is group- or world-writable`.
  It checks **every ancestor**, so merely creating `HOME/.cache` below `/tmp` would not solve it.
  Cause probeSHA `d8c7addcaf2bcdb4d68c3598ca288e00c7bf63ec37251d69da733b6d53090246`;
  directory-metadata-only inspection confirms `/home/ksi/.cache` ancestry real/root-or-user-owned/
  non-group-world-writable. No original directory mode/content or product guard has been changed.
- **P7-A1 proposal — approval pending:** create exactly
  `/home/ksi/.cache/ksi-p7-home-34cc796826d6` mode0700 and its own `.cache` mode0700; use it as
  isolated HOME for the repaired Task1 runs. No copied profile/token/config, no existing home/cache
  permission/content changes, no original `.venv` use. Other environment/cache/log/image paths stay
  under the original P7 scratch root; source/lock/pins/API/security rules stay fixed. Only task-generated
  synthetic fixture files may use the new private HOME; retain proof and remove only that proven-owned
  new namespace at scoped cleanup. This is a bounded new write location outside the original approved
  scratch root, so Human approval is required rather than silently changing the plan.
- Recommended after P7-A1 approval: one named failed test RED under the old environment; create
  only that new protected HOME; verify the same case GREEN plus all seven affected modules; independent
  Runner rechecks full active suite **once after this real environment repair**, preserving first failed
  log/receipt and unaffected static/type outputs. This is defect→repair→reverification, not blind replay
  or a source/permission waiver. Task1 remains unfinished until actual repaired evidence arrives.
- Task2 Ruling: Dockerfile-specific ignores override root ignores and whitelist `src/**`;226new host
  bytecode files would enter external image contexts after imports/tests. Build from an additional
  **tracked-only mechanical export of the same4a0a08e** under approved scratch `build-context` rather
  than dirty-by-cache live checkout;2751blob/mode checks match,3gitlinks remain uninitialized, no bytecode/
  Git/private state in export. Archive tarSHA `a7a33248f4c95efdd6c648ae6440e5ce9d3d2306877f2e02b4e7410482cef246`,
  clean-lane argv manifestSHA `05d858da3c5048330192188aa822103fdff39640057d3ec862fac745dbc04c33`.
  Dockerfiles/ignores/source are unchanged — why: prevent local cache contamination without deleting
  runner artifacts or editing products — cost if wrong: identity proof rejects candidate input/output.
- Task2 source/install identity is independently usable; a failed Task1 suite is not waived by images.
  Buildx0.35.0 is prepared; three unique candidate tags did not pre-exist. No build/probe/boot/temporary
  runtime credential effect has occurred yet. P7-A1 is the current material decision; safe independent
  image preparation may continue, and all customer/production/strictarchive/broadtype gates remain OPEN.

### P7-A1 approved secure synthetic HOME — 2026-10-09

- Human answered **“P7-A1 승인 (Recommended)”** to the exact new-path/effect question: create only
  `/home/ksi/.cache/ksi-p7-home-34cc796826d6` and its `.cache`, both0700, and use that fresh namespace
  as HOME for affected tests and one independent full-suite revalidation. This supplements approved
  planSHAfba7776e; the frozen plan/spec/first failed logs/receipt remain unchanged.
- No original home/cache directory permission or existing file content changes; no copied profiles,
  credentials or environment; no product/test/guard/lock/pin modifications. Keep all other P7 scratch
  locations. Revalidate the real non-symlink/root-or-caller-owned/non-writable ancestry before creation;
  unknown/pre-existing target is a blocker, not permission to reuse/chmod it.
- Source-bound named old-environment RED → fresh secure HOME only → same GREEN and seven affected
  modules → independent full active suite once. Reuse same-revision static/type outputs; Task1 remains
  unfinished until actual GREEN receipt, broad109/14 remains FAILED. Approved independent Task2 builds
  may proceed on exact tracked-only source; never equate them with Task1/customer/production acceptance.
- A1 named test `test_spatial_data_mcp_config.py::test_from_file_accepts_private_loopback_config_and_rereads_rotated_token`
  actually reproduced RED1failed/0.08s (logSHA `b778470065608afcca32fc6f113fcce6f4a864991a83e019d542883da2b21687`),
  then new HOME0700/own.cache0700 alone yielded GREEN1passed/0.05s (logSHA
  `5b19689a97d618d5cdfce632de67285a8efa3c57100a80350a5bb7ca9e05ae34`). Actual unchanged
  protected reader accepts the new ancestry and synthetic0600bytes (logSHA
  `383e37cbdab1713c92ca364c3c96cbbb9903336ed205d364bca44eb0ce6025a8`); original guard untouched.
  Supplementary profileSHA `81e57815debc440ee78e42bd0877053f6e2ee5093fd9ab60468b8e51a084b62d`
  binds new directory inode/uid/ancestry and full minimal environment; initial freeze remains immutable.
- A1 affected-seven-module command was interrupted by Primary's too-short120s foreground tool timeout.
  Partial log has129progress dots, no terminal result/XML/remaining process; **not a passed or failed
  product gate**. Exact command was the new-env Python `-m pytest -q -p no:cacheprovider -rs
  --junitxml=$RUN/a1-affected.xml` and the seven modules listed above in that order. Preserve partial
  logSHA `d1f0ac31ea5acf0cfcddf7c97d4ce0e383ffd2ea5dd5766e3e42ea540e94cf98` and single interruption
  diagnostic; source/checks/environment were not repaired further in response to the tool timeout.
- Task1 Ruling: do not replay this incomplete affected command just for a receipt; the already approved
  independent **full once after A1 repair** includes all seven modules. Require the Runner to assert
  every first-failed node and every affected module is collected and green in its final full/JUnit report.
  Why: terminal revision-bound full coverage is stronger than duplicating129unreported assertions;
  cost if wrong: missing node/module coverage leaves Task1 unfinished. Use background/long command
  timeout and completion notification, never poll/replay. Unaffected static/type outputs remain reused.

### P7 Tasks1–2 evidence received / P7-A2 runtime-origin decision — 2026-10-09

- A1 independent repaired full ran once at immutable4a0a08e: **6058passed/30skipped/98warnings/
  0failed/765.16s**, exit0. All59first-failed IDs and seven affected modules130cases are collected/green;
  total6088cases, exact old/new skip-node/reason multiset unchanged. No product/test/guard/lock/pin
  repair or full-suite replay for receipts. Broad109/14/0delta remains FAILED, five static/scoped checks
  reused at the identical source. ReceiptSHA
  `24b862244663ea4f1fbc37e7afcb9ea68e1cb6b53529f98faa0b9e097f5741a3`, fullLogSHA
  `084d08246527d2c381baf037c502848f03936da400cd6293993faf7619cc11c9`, XMLSHA
  `5245bf47b062e9481056a85e76036b183b075305d79f50544253ed38d6db7edb`, Primary receptionSHA
  `1b297a72949c46ab2706612078bea80f107dcb26f8ec3722cba8a6e356771b63`. Source2751blobs/
  3uninitialized gitlinks/18original metadata/12neweditables and original944b231clean matched.
- Task2 source-bound nativeARM64 builds/inspect/import-controls: **9commands/9exit0**, receiptSHA
  `705308e1c4ac7bb9d472387dd27514f3e0ba1924dd07487e2a73c54dd502bced`.
  Core image617c3b95/inspectorf1d42c1b/measurement0dae5061; exact full IDs/log/argv in receipt.
  Actual corresponding UIDs10001/10003/10004; source433/178/178files match; read-only root,
  CapEff0/no-new-privileges, networknone/onlylo,4GiB/256PIDs/2CPU verified. All three owned probe
  containers were removed. Candidates retained locally, base blobs may be reused in shared daemon;
  no registry push, signed worker/job, runtime activation, customer/accuracy or release claim.
- Task3 scratch config exit0/sanitized configSHA
  `06736ea860b07533d37f1a386d9023f883e22af38bb242f6c0d561483827c031`; three-services/new-only
  resource declarations checked. Synthetic opaque operator/viewer/foreign-viewer digests have24h
  expiry; raw test/storage secrets remain0600below0700scratch, no copied private configuration.
  Exact existing BusyBox/MinIO pinned pulls and init/MinIO start completed; init chown ran only against
  new labeled data volume, exit0. No Core startup, Site mutation or S3 byte persistence trial yet.
- Startup driver then stopped at actual MinIO port resolution: `NetworkSettings.Ports[9000/tcp]`
  isnull despite requested `HostConfig.PortBindings=127.0.0.1:0`. Selected internal bridge is healthy
  and actual host→owned private-IP `/minio/health/ready` read returned200. This is observed selected-
  daemon behavior, not a product-source defect or an assertion that YAML implies published ports.
  DiagnosisSHA `9b4262d6507fa204d780e9581d3bf2247ef659414007640e3fb79e99c16e843a` preserves
  all seven terminal startup commands and source/project/resource identity. Do not blindly rerun
  startup or weaken `internal:true`/loopback/firewall/security controls to hide the mismatch.
- **P7-A2 proposal — NOT yet approved:** preserve the existing private `internal:true` network and
  exact three-service graph; remove only the scratch Core/MinIO port-publication requests using an
  additional `compose.a2.override.yaml` (`ports: !override []` for both). Verify real TCP from the
  same prepared Docker host using the verified owned containers' current private bridge IPs instead
  of claiming a localhost published endpoint. Re-resolve exact container/network identity after restart.
  Keep Core/MinIO/init limits, Core read-only/cap-drop/no-new-privileges, factory/image, credentials,
  tenant/auth semantics and existing owned volumes unchanged; no new service, proxy, public/tailnet
  listener, external route, egress-enabling network or host firewall/daemon modification.
- P7-A2 would explicitly replace **only this trial's loopback-origin acceptance** with host→owned-
  internal-IP TCP evidence. It would **not** verify published localhost ports or the production network,
  and internal-network inspection plus host success is not a complete external-denial/kernel proof.
  Reuse current owned init/MinIO/data/object/network resources after matching their labels/IDs; any
  recreated trial container must retain those exact owned volumes and approved controls. Continue
  missing bucket/byte/Core/auth/restart steps only; retain first failed startup/logs/config unchanged.
  No product Compose/Dockerfile, source, signature/Analysis policy, remote consumer, data rights or
  customer acceptance change follows. Human decision required because approved endpoint contract differs.
- Recommended: approve this stronger no-published-port trial origin; do not enable runtime external
  networking or add a proxy just to retain a localhost-shaped URL. Without that approval, Task3
  remains blocked and owned trial shutdown/final source/evidence review can still proceed. Tasks1–2
  evidence is usable locally; final report/review/Task3 and whole-goal/customer/EXT-VAL remain OPEN.

### P7 rail 만료 / owned trial shutdown / 기록 매핑 — 2026-10-09

- 승인된 4-hour rail(08:16:47.942470Z + 4h)이 2026-10-09T12:16:47.942470Z에 만료됐고 P7-A2는
  미승인이라 Task3은 blocked 상태다. 승인 계획의 teardown 범위(owned 컨테이너/네트워크만)로 실제
  정리: minio `fd6a3f6c352b3d3a23bc47e6b7c8ab1cbf0c48061f0d178dec0aa80389e0ebd6`(healthy→stop/
  removed), init-volumes `7cd96e263cd3c0023d77e7c859ef163b94290e5e73ede808f7765e428e81308c`
  (exited→removed), network `ksi-p7-34cc796826d6_default`
  (`9d00c7d34eeea4856e25191cbd1f1116e344e95709a139404aef2313a485b298`) removed.
- 보존: volumes `ksi-p7-34cc796826d6_ksi-data`/`_ksi-objects`, 후보 이미지3건(Core`617c3b95b509`/
  inspector`f1d42c1b8153`/measurement`0dae50617e84`), scratch receipts/logs/config, 전용 HOME,
  trial worktree. `down -v`/prune/기존 리소스 삭제 없음.
- Task3 재개는 별도 rail + P7-A2 결정이 필요하다. 하네스 기록 매핑(1회) 결과는
  docs/superpowers/plans/2026-10-09-site-harness-mapping.md에 있다. 기존 계획·Spec·PRD 문구는
  재작성하지 않았고 Goal `active`는 inert로만 표기한다.

### F-01 결정 제안 — 2026-10-09

- 첫-flow 온보딩을 막는 F-01(Site bootstrap·WorkArea grant 소유권) 결정 제안서를 작성했다:
  docs/superpowers/plans/2026-10-09-f01-site-bootstrap-and-grant-ownership.md
  (D1 Site 생성 권한, D2 WorkArea grant level, D3 완료 증거; 권장 2안+B안).
- 근거는 실제 코드/계약 pin이다: auth.py:901-910 검토된 route matrix(`POST /v1/sites` 부재),
  test_oidc_route_scope.py:224-250 403 pin, registry v1 명시 배열(oidc_subject_registry.py:20-29,
  104-107), work_areas.py:554-559/605-610 creator lockout, boot-time registry 로드
  (platform_production.py:83,173). 코드·route·registry·grant는 변경하지 않았다(실행 아님).
- Human 결정 후 상세 구현 계획(파일/테스트/작업 분해)을 작성해 실행한다. P7-A2/rail,
  F-02..04, customer/EXT-VAL 게이트는 그대로 OPEN이다.

### F-01 승인 반영과 계약 개선(v2) — 2026-10-09 (resume)

- Human 승인: "2안 + B안 승인. D3 완료 증거도 제안 그대로 진행하면 됩니다."
  같은 메시지에서 GPT가 제시한 조건 2건(① site-level grant는 동일 Site 내부 WorkArea에만 상속,
  다른 Site·Org로 비전파 ② org-admin capability 최초 발급은 KSI가 통제·감사)의 검토를 지시했다.
- 검토·지시: 두 조건은 타당했다. 보강 5건(C1 same-Site 상속·scope-only, C2 capability 수명주기
  (발급·변경·회수) KSI 통제, C3 신규 Site 생성자 접근 확정, C4 D3 부정 테스트, C5 ADMIN 서술
  정정)을 제안했고 Human이 "그래요 권장되는방향으로 개선해주세요"로 채택을 지시했다.
- 반영: [F-01 제안 v2](2026-10-09-f01-site-bootstrap-and-grant-ownership.md)를 ff3a5d0으로
  커밋했다(product-state 동반 갱신; v1은 159e7c5). C3 확정 요지: `allowedSiteIds: null`(자기 org
  전체)은 capability와 분리된 KSI 발급 결정이고, 생성 행위 자체는 scope를 확대하지 않는다
  (per-site grant 레코드 없음). 회수는 registry 재발급/REVOKED, 반영은 재시작 절차, org 전체
  모드의 개별 site 제외 불가(잔여 한계 → C안 후속).
- 이 기록은 코드·route·registry·grant 변경이 아니다. 다음: 상세 구현 계획 작성 → Human 승인 → 실행.

### F-01 상세 구현 계획 승인 — 2026-10-10

- Human(직접)의 승인 순서: (1) "이견 없습니다. F-01 v2 기준으로 상세 구현 계획 작성으로 진행해도
  됩니다"와 명시 fail-closed 조건(명시 null / 명시 배열 / 필드 누락·invalid 는 거부 또는 v1
  semantics, 구버전 fallback 이 null=org 전체로 승격 금지), (2) 계획 범위 지시(registry v2
  parser/schema, 명시적 site-scope marker, org-admin capability 조건부 Site 생성 route,
  same-Site WorkArea 상속, 발급·변경·회수 semantics, v1 및 일반 operator 비회귀, D3 (a)–(f)
  실제 OIDC 수용 검증, rollback), (3) "승인 게이트를 거친 다음 코드 작업" 지시.
- 교차 조직 siteId 존재 노출 방지 결정(Human 선택, 2026-10-10): 신규 v2 bootstrap 은 **서버 발급
  Site ID** 를 사용한다. 기존 v1/opaque client-ID 계약과 저장된 ID 는 불변.
- 상세 계획 산출물: `/home/ksi/.opencode/plan/2026-10-10-0103-feat-f01-bootstrap-grant-implementation-plan.md`
  (SHA256 `cbba7fe5924a4caca810b9c52a476d212222a133e6282dd70dde44d12ba649ca`; repo 밖 승인용 계획) —
  U1–U7, KTD1–KTD8, 보호 registry v2, capability 조건부 경계, 서버 발급 ID+멱등성, same-Site 상속
  소비자, 실제 OIDC/DUAL·browser·restart D3 증거, v1 scope 512 한계 초과 시 rollback 거부,
  Org당 기본 1,000 상한.
- Human 승인(2026-10-10, 직접): "상세 계획 승인" — 승인 범위 U1–U7·서버 발급 ID/멱등성·1,000 상한·
  compatible-reader rollback. live 발급·배포·새 network origin, P7-A2, F-02..04 는 별도 게이트 유지.
- provenance 정정: 위 2026-10-09 "F-01 승인 반영과 계약 개선(v2)" 항목의 "Human 승인" 인용문은
  Human 이 전달한 GPT 응답 문구를 포함한다 — 그 문구 자체는 독립 Human 승인 근거로 사용하지 않는다.
  실제 직접 승인은 (a) "그래요 권장되는방향으로 개선해주세요"(C1–C5 반영), (b) 2026-10-10 상세 계획
  승인이다. 과거 기록 문장은 지우거나 재작성하지 않는다.

### F-01 구현·U6 로컬 합성 수용(D3) — 2026-10-10

- 구현: 레지스트리 v2(fail-closed 문법·marker·조건부 POST /v1/sites·whoami metadata), 서버 발급
  Site ID + (org, principal, requestKey) durable binding(멱등 201·409 conflict·404 hidden), Org당
  기본 1,000 상한, same-Site 상속 소비자(work_areas fallback·supersedes fold·analysis selector),
  pilot preflight v2, dev runner --oidc-subject-registry-file, dashboard 판정/BFF/화면(wizard는
  OpenDesign Local Codex 실행 결과를 검수 반영). 커밋 159698b(core)·bb1c4bf(dashboard).
- 검증: full active Python 6143passed/30skipped/0failed(12m38s), 신규·기존 oidc/auth/production/
  pilot/core-dev contract tests green, dashboard vitest772/tsc/lint/build green.
- U6 실행(사전 대상 확인 후): 격리 loopback 스택(issuer9071/Core8071/dashboard3235, tailscale
  disabled; 기존 systemd dev 스택 무접촉) + 보호 v2 registry(0700 dir/0600, ~/.cache — /tmp/opencode
  직접 배치는 loader의 unsafe ancestor 거부로 올바르게 실패했고 보호 경로로 이동).
  D3 결과: mapped wizard(현장 ID 없음) → 서버 발급 site-c6095357-…(201, actor local-admin,
  journal binding 1건) → WorkArea wa-…-0001 즉시 사용(201) → 재시작 후 동일 ID 재현 → 동일 키
  재시도 201 같은 ID(멱등) → capability 제거 403+조회 유지 → scope 축소(목록0/상세404/숨겨진
  재시도404) → 재발급 가시성 복귀+같은 ID → REVOKED 401 → v1 파일 가시성 유지·bootstrap 403.
- 증거: apps/dashboard/f01-bootstrap-evidence/verification/(receipt.md, 캡처 12, journal 사본,
  registry 단계 파일, MANIFEST.sha256; HAR 70MB는 scratch 경로+해시만). ADR-KSI-040 기록.
- 한계(명시): DUAL 스택·교차 org 브라우저 계정 전환·모바일 캡처·위조 claim/area 주입은 in-process
  계약 테스트로만(스택 미실행); 화면 디자인 리뷰는 별도 디자인 소유 단계(미실시); production/
  RB03·08·TLS/UDS/ACL/CI/AMD64·P7-A2/Task3·F-02..04·고객/EXT-VAL은 OPEN 유지. 이 PASS는 로컬
  합성 수용이며 고객/현장/배포/정확도 수용이 아니다.

### F-01 후속 — e2e 스펙·디자인 리뷰 단계 — 2026-10-10

- 반복 스펙: apps/dashboard/e2e/f01-site-bootstrap.spec.ts(KSI_F01_E2E=1 + 외부 스택 base URL
  게이트; desktop-1024/1440만) — 새 격리 스택에서 각 ~10s 통과. 비활성 사유의 인뷰포트 단언 포함.
- 디자인 리뷰(디자인 소유, OpenDesign 프로젝트): 1차(plan-design-review, codex) 8–9/10 +
  "01 캡처 하단 잘림" 1건. 독립 검증: 표준 데스크톱 뷰포트(1024×900/1440×1000)에서 사유 문구는
  인뷰포트(e2e 단언 통과) — 잘림은 1280×633 캡처 뷰포트 아티팩트이며 F-01이 바꾼 레이아웃이 아니다.
  신선 컨텍스트 대체 리뷰는 claude CLI 미인증(AGENT_AUTH_REQUIRED)·gemini-2.5 종료·antigravity
  무출력·gemini-3.1 잔액 일시중지로 OPEN이며, 재개 옵션(로그인/충전)은 사용자 결정 사안이다.
  1차 리뷰는 같은 native thread 재개·도구 로그 제한이라는 공개된 한계를 가진 유일한 사용 가능 증거다.
- 주의: 새 --dashboard-dist-dir로 `next dev` 실행 시 apps/dashboard/tsconfig.json에 생성 경로가
  추가된다(커밋 전 제거).

### F-01 종결 및 F-02~04 착수 결정 — 2026-10-10 (Human, 직접)

- 디자인 재리뷰: **(c) 현 기록 수용으로 종결** — 1차 리뷰(8–9/10)와 캡처 뷰포트 아티팩트
  검증으로 충분하며, 별도 충전·재실행은 하지 않는다(제품 개발 병목으로 두지 않는다).
- F-01은 669df6d의 수용 증거 기준으로 고정한다. 이후 변경은 F-02~04와 섞지 않는다.
- P7-A2/Task3: F-02~04의 직접 선행조건이 아님(검토 결과 — P7은 fresh 환경/이미지 증거 트랙으로
  현재 제품 경로와 독립) → 현 종결(blocked·trial 정리 완료) 상태를 유지한다. 직접 의존성이
  확인될 경우에만 해당 범위만 별도 제안한다.
- 다음 우선순위: **F-02~04 입력 착수** — 외부 산출물 등록 → 적합성 검사 → Analysis API →
  실제 워커 실행 → Result/Evidence 저장 → 외부 소비를 **실제(Terra 계열) 자료 기준**으로
  완주하는 경로를 닫는 데 집중한다. 필요한 고객측 입력 목록과 우리측 준비 항목은
  docs/superpowers/plans/2026-10-10-f02-04-first-flow-input-checklist.md에 기록한다.

### F-02~04 입력 착수 — 환경 준비 1단계(실바이트 레인) — 2026-10-10

- 입력 목록·순서는 docs/superpowers/plans/2026-10-10-f02-04-first-flow-input-checklist.md에 기록
  (고객측 A~E: real Terra 계열 t0/t1(+t2) ortho/DSM·CRS/수직기준·캡처시각, 권리/동의/거주, 검사점
  CSV(정량), 소비자+호스트 1개, 수용 참여).
- 우리측 준비 1단계 실행(synthetic, 로컬 격리): 캐시된 MinIO 컨테이너(loopback 9100) + Core dev
  (`--s3-endpoint/--s3-bucket` + boto3 체인)으로 **등록→upload-grant(MinIO presign)→실제 PUT
  (ortho·dsm)→seal SEALED**까지 성공. inspection 조회는 `INSPECTION_PENDING_POLICY`(=F-03 보호
  구성 필요)로 정직하게 드러남. 컨테이너/프로세스는 종료·제거, 포트 비움.
- 증거(보존): /tmp/opencode/f02-prep-20261010-194828/evidence/rehearsal-01..04.txt 실패→성공 순
  (sha256 1bcf90e2…/c53d8f54…/fda0d002…/8d96373e…), 재실행 스크립트 scripts/rehearse_f02.py.
  이는 synthetic 환경 검증이며 고객 자료·형식 호환·정확도·수용 증거가 아니다.
- 다음: F-03 보호 구성(합성 로컬 Analysis runtime/activation/workflow-provider + 검사 lane
  policy/authority) → synthetic 검사→분석→결과 리허설; 이후 실제 자료 입력 시 같은 환경에서 완주.

### F-03 준비 1단계 — 보호 Analysis 구성·production factory 부팅 검증 — 2026-10-10

- 합성 보호 material(서명 Analysis activation trio: sealed policy/runtime/envelope + Ed25519 서명 +
  검증키 registry + ADMIN/ANALYSIS_WORKER/PROCESSING_WORKER 토큰) 생성기로 생성 후, **production
  factory**(uvicorn `build_platform_production_app`)를 로컬 부팅해 검증: `/ready` 200, analysis 계열
  route 12·external-reconstruction route 15 마운트, 더미 create가 **404 ANALYSIS_RESOURCE_NOT_FOUND**
  (503 ACTIVATION_EXPIRED 아님 = 서명 activation 실제 수용), `/ready/external-authority` 404
  (workflow/provider pair 미구성 — 정직한 중간 상태).
- 관측: 보호 파일 로더가 그룹 쓰기 가능 조상(`/tmp/opencode`)을 `CONFIG_FILE`로 거부(fail-closed) →
  material을 `~/.cache/ksi-f03-*`(0700/0600)로 이전해 통과.
- 증거(prep dir `/tmp/opencode/f02-prep-20261010-194828/`): `evidence/f03-material-01.json`
  (e73145fc…), `evidence/f03-boot-01.md`(d6244698…), `evidence/f03-core-2.log`(7b0b3b4b…),
  생성기 `scripts/gen_f03_material.py`. **synthetic이며 activation/수용 증거가 아니다.**
  컨테이너/프로세스 정리, 포트 비움.
- 남음(F-03 phase 2+): workflow/provider pair(서명 snapshot의 policy/catalog authority record) +
  workflow config → 검사 정책 admit → inspector lane(로컬 합성 한정) → `ksi-external-analysis-worker`
  실행 → 결과/증거 → 소비자 E2E. 실제 자료(체크리스트 A~E) 도착 시 같은 환경에서 완주.

### F-03 phase 2 — synthetic evidence 기록; parser sandbox acceptance OPEN (2026-10-11)

#### 실행 환경 게이트 — `PARSER_SANDBOX_UNAVAILABLE` (2026-10-12)

- 상태: **호스트 capability blocker**. 제품 버그가 아니며 제품 코드, sandbox contract,
  fail-closed 동작을 변경하지 않는다.
- host evidence: `bwrap` binary present (`/usr/bin/bwrap`, 0.9.0); user namespace unavailable
  (`unshare -Ur true` → `Operation not permitted`); UID mapping denied
  (`bwrap --ro-bind / / -- /bin/true` → `setting up uid map: Permission denied`);
  network namespace unavailable (`bwrap --unshare-net ...` → `Failed RTM_NEWADDR: Operation not permitted`).
- 결과: parser execution **BLOCKED**; fallback **NONE**; product behavior **FAIL-CLOSED**.
  root 우회, `--unshare-*` 제거, sandbox 없는 parser 실행, host security 설정 변경은 하지 않는다.
- 이 호스트에서 확인 가능한 범위는 입력/권한/lease, 파일 전달, policy/manifest/digest,
  parser 실행 전 launch 조건 및 그 회귀 테스트다. sandbox 내부 parser 실행과 filesystem/network
  격리, parser 성공에서 `VALIDATED`를 거쳐 Analysis→Result/Evidence→review로 이어지는 단일
  chain은 확인되지 않았다. 아래 synthetic inspector/Analysis/review 기록은 개별 관측 증거로
  보존하되 parser containment acceptance 또는 synthetic end-to-end 완료 증거로 승격하지 않는다.
- 정식 acceptance gate: bwrap user namespace/UID mapping이 허용된 별도 검증 호스트에서 **동일한
  artifact·policy·manifest**로 기존 설계를 실행하고, sandbox 격리 관측 → parser launch → `VALIDATED`
  → Analysis worker → Result/Evidence → review까지 완주한다. 그 전까지 parser 이후 gate는 OPEN이다.
  호스트 capability와 무관한 F-03/F-04 작업은 별도로 진행 가능하다.

- 기존 `DEFERRED`는 `_checkpoint_launch`의 binding 판정 실패가 아니었다. 보존된
  request/context/policy를 재구성한 결과 **pre-execution binding check PASS**; 새 live request에서도
  role 순서를 정규화한 15개 binding 판정 전부 참이었다. 이는 bwrap 안 parser 프로세스의 실행
  증거가 아니다. 최초 UDS 실패는 prep harness workspace 재사용(`FileExistsError`), 이어진 두 실패는
  잘못된 `measurementExecutionManifestDigest`와 DSM footprint 밖 CSV 좌표였다. 제품 fail-closed
  판정은 변경하지 않았다. prep harness에 매 실행 고유 workspace, actual canonical manifest digest,
  2×2 DSM 셀 중심 좌표를 적용해 해결.
- 실제 live Core+MinIO 및 worker 경로에서 checkpoint CSV 3점의 `COMPLETED`→Core `VALIDATED`
  기록 확인. policy7 pair: `obs-work-00000008` validation
  `external-evidence-validation-de6dac1a409530e0c1ed761dfa226a9d`, evidence-record digest
  `sha256:ad0570e405033428c4122b002cd0350a140ae5150ea56e0732eb67272d40c3a5`;
  `obs-work-00000009` validation `external-evidence-validation-54783769143d9b7526a39a032c5b171d`,
  evidence-record digest `sha256:7ce5e96ab1ee4a4319e2a5229707fe5fcea5f3895ddd950f17d5ffa0344d9b47`.
  둘 다 DSM digest `sha256:601400a33deea10f6…`와 checkpoint evidence digest에 바인딩되고
  3-point RMSE/MAE/max error = 0.0m. 두 epoch의 policy7 inspector lane도 Core에 `MEASURED`(2×2,
  EPSG:5186/5773)로 기록됨; 이 기록만으로 bwrap containment를 입증하지 않는다. 세부 worker input/terminal evidence는
  `/tmp/opencode/f02-prep-20261010-194828/evidence/f03-rootcause-checkpoint-retry5-live.txt`,
  `f03-pair-checkpoint8.txt`, `f03-pair-checkpoint9.txt`, `f03-pair-inspection7-retry2.txt`.
- 정합성을 위해 WorkArea `wa-f03-flow-site-0002/0003`를 DSM footprint와 동일한 EPSG:5186 범위로
  구성하고 RGB ortho + DSM을 포함한 sealed pair `obs-work-00000012/13`를 사용했다. inspection
  결과 둘 다 `MEASURED`; checkpoint CSV 실제 worker/Core 결과 둘 다 `VALIDATED`(3점 RMSE/MAE/max
  error 0.0m; record digests `sha256:e1f1d7…` / `sha256:4b522e…`). synthetic independence
  attestation이다.
- Mapping은 policy v10의 rule allow-list + 새 카탈로그 authority로 서명 admit했다. 구 catalog
  authority mapping과 새 mapping이 동시 active였던 동안 evaluator는 모호성을 fail-closed로 막았고,
  이전 mapping을 서명 `REVOKE_MAPPING`으로 폐기한 뒤 fresh pair decision이 `ELIGIBLE`이며 새
  mapping digest `sha256:b7a2e802…`를 바인딩함을 확인했다. WorkArea footprint mismatch 및 old-map
  ambiguity 모두 harness setup/authority history 이슈; 제품 코드는 변경하지 않았다.
- 실제 Analysis worker CLI가 `analysis-v1-33bb91af966a1b2d56099d1f8122abec`를 처리해 COMPLETED.
  Result: net 0.0 m³, selected/common-valid 4/4 cells, report digest
  `sha256:717593ee15e8329bdabf71c800b800f29790f048786a39177c2dc79bdcafbf59`; evidence 조회에서
  baseline/current input digests `sha256:f38d51…` / `sha256:9c534a…`, profile `KSI-GIS-RELATIVE-VOLUME-V2`
  및 calculation identity 확인. Review target에 결합된 ACK receipt
  `sha256:e71f759b0a25a4b188cdadf6728617b76d67f218ebc6442ad00b5086636df46a`는 synthetic rehearsal
  전용(`reviewerId=f03-admin`); 정확도 검증·현장 승인·settlement/customer acceptance가 아님.
  같은 idempotency key 재POST는 같은 COMPLETED analysis ID를 반환했다.
- 첫 Analysis attempt의 실제 실패는 fixture `maxMemoryBytes=100000`이 worker 고정 TIFF predecode
  작업공간 1 MiB보다 작아 난 `RESOURCE_LIMIT_EXCEEDED`; validation 완화 없이 로컬 synthetic
  finite envelope를 8 MiB로 재설정하고 새 signed activation으로 bound했다. deterministic calculation
  ID가 failure terminal을 재사용해 새 aligned WorkArea definition으로 새 ID를 발급했다.
- 별도 relative-volume-request API에도 2026-10-11 request
  `external-relative-volume-27d4373b0c6ca8da31809a3ed21acc63`를 발급했으나, 이 API/worker path는
  Analysis worker job과 별개이며 deadline 경과 후에도 read view가 QUEUED다. 분석 E2E acceptance에
  포함시키지 않았고 새 실행 시 유효 deadline과 authorized worker 필요. synthetic evidence는
  `/tmp/opencode/f02-prep-20261010-194828/evidence/`; A–E/Terra/customer/production acceptance 미완료.
  위 `PARSER_SANDBOX_UNAVAILABLE` 때문에 이 단계를 parser부터 review까지 이어진 synthetic E2E
  완료로 주장하지 않는다.

### F-03 준비 2단계 — 서명 정책 인정·검사 실측 (당시 진행 기록; 후속 완주는 위 항목) — 2026-10-11

- 서명 스냅샷 체인으로 검사 정책 인정 성공: seq1(카탈로그)→seq2..(정책 v1→v4→v5, 정확한 sealed
  subject 묶음)→reload→`PROVIDER_CONFIGURED`, 검사 상태 `INSPECTION_PENDING_POLICY`→`QUEUED`.
  체인 헤드는 영수증 원장이 정본이다(오프라인 로드 digest가 아님 — 직접 확인된 함정).
- **검사 lane 실측 성공(핵심)**: suite-shaped 실 GeoTIFF(2×2, EPSG:5186+5773) 2 에폭을 live Core+
  실 MinIO에서 핀드 프로파일 lane으로 측정 → **MEASURED ×2**(2×2·4px·EPSG:5186/5773, 리포트
  digest 기록). 정책 envelope/deadline(600s)·manifest·parser digest 삼위일치가 전제다(1s 테스트
  envelope·누락 manifest가 막은 함정 3건도 기록).
- 증거(checkpoint CSV) 선언→grant→실바이트 PUT→seal ×2 완료, 컨텍스트 서명 인정 후 검증 요청
  2건 발행됨.
- **열림**: checkpoint `_checkpoint_launch` 바인딩 점검 실패 → DEFERRED → 불완전 기록. 다음 단계는
  새 에폭+새 증거+즉시 구동에서 전체 input body 덤프 후 직접 `_checkpoint_launch` 호출로 어긋난
  필드를 특정한다(후보: `is_active_at(issued_at)`·subject 정합·sealed() 교차검사).
- 증거(prep dir `/tmp/opencode/f02-prep-20261010-194828/evidence/`): f03-lane-1[4-8]*, f03-checkpoint-0*,
  f03-admit-0*, f03-contexts-02, 정책/스냅샷 버전 기록. 스택·컨테이너 정리, 포트 비움.
  **synthetic이며 수용 증거가 아니다.**

### DJI/Manifold 잔여 참조 정리 — 사용자 지시 (2026-10-12)

사용자 재확인: Manifold·DJI/PSDK 장비는 제품 책임 밖(ADR-KSI-039, DOCUMENT_STATUS ACTIVE).
런타임/서비스 계층은 이미 제거돼 있다(`services/dji-gateway` 없음, platform factory 미mount,
main CI 비빌드, 경계 테스트 2종). 이번 지시로 남은 잔여물 중 안전한 범위를 정리했다.

- 제거(로컬, Git 밖): `edge/` 1.3GB/2,347 files — build-asan 등 CMake 빌드 트리, fetched PSDK
  vendor SDK 클론(`edge/third_party/psdk`), 로컬 전용 `dji_sdk_app_info.h` 2개; `scripts/manifold/
  manifold.env`(로컬 SSH 설정, 템플릿은 archive에 있음). 모두 git-ignored 로컬 잔재로 재생성 가능.
- 제거(tracked, dead code): `apps/dashboard/src/lib/aircraft.ts`(M4D enum/카메라 SSOT — P4 위저드
  제거 후 importer 0) 및 `apps/dashboard/src/lib/core-api/types.ts` 취득 타입 9종
  (AcquisitionCapability, AcquisitionDeploymentProfileV1, CapabilityReceiptV1, ConnectivitySnapshotV1,
  AcquisitionReadinessView, AcquisitionRunStage, AcquisitionNextAction, GatewayOperationReceiptV1,
  AcquisitionProgressView). disposition CSV의 RECONCILE("File-level consumer review; no blanket
  move or removal")에 대한 소비자 전수 확인(src/test/e2e/Python tests 0건) 후 제거.
- 정정: `services/README.md` deployable-units에서 존재하지 않는 `dji-gateway/` 행 제거 및 누락된
  `spatial-data-mcp/` 행 추가.
- 검증: `scripts/check_repo_hygiene.sh` OK; 대상 contract 71 passed(repo-hygiene·대시보드 sync 3종·
  product boundary·아카이브 경계·역사 reader); dashboard eslint 0 errors(기존 p4-evidence warning 1),
  `tsc --noEmit`·vitest 772/772 passed; `git diff --check` clean.
- 보존(변경 없음, ADR-KSI-039/DOCUMENT_STATUS): `archive/acquisition-2026/`(432 files, 8.2MB) +
  dispatch-only `historical-archive.yml`, 역사 문서(docs/dji·docs/edge·docs/hil)와 HIL 도구·테스트
  (tools/hil·tests/hil·contracts/hil, 39 tracked), 취득 계약 스키마(mission-contract/action-intent/
  acquisition-deployment-profile/mission-dispatch-envelope/asyncapi-edge), ADR 결정 이력, RETAIN
  판정된 capability/spike 모듈.
- 사용자 결정(2026-10-12): **보존 유지** — archive·HIL·역사 문서·계약 이력은 그대로 두고 잔여 참조의
  '역사적·비제품' 표기만 강화했다. `docs/DOCUMENT_STATUS.md`에 취득/device HIL family
  (docs/hil·docs/dji·docs/edge·tools/hil·tests/hil·contracts/hil) HISTORICAL/OUT-OF-PRODUCT 행 추가 및
  HIL route index를 active 표에서 해당 historical로 이동, contracts 행에 역사 계약 family 명시,
  `docs/hil/README.md` 헤더를 retained(out-of-product)로 갱신. 완전 삭제는 하지 않으며 ADR-KSI-039의
  "verified successor move까지 보류" 조항이 그대로 유지된다.

### F-04 소비자 준비 1단계 — Analysis MCP 실 스택 read (synthetic) — 2026-10-12

- 소비자 클라이언트로 `services/analysis-mcp`(저장소 설치형 stdio 어댑터)를 선택했다. 원본
  F-03 스택(8092)은 그대로 두고 `f03/core-data`·`provider` 복사본(보호 경로
  `~/.cache/ksi-f04-20261012`, 0700)으로 별도 Core(8093, production factory)를 구동하고,
  토큰 registry에 ANALYSIS_MCP_CLIENT principal(사이트/WorkArea grant)을 추가했다.
- deny 대조(복사본 consent=false): `ksi_list_analyses` → `AI_EGRESS_NOT_ALLOWED`(fail-closed).
  allow(복사본 `aiEgressAllowed=true`): tool 6종 노출, read 5건 성공 — `ksi_get_analysis`/
  `_result`가 COMPLETED·`REASSESSMENT_REQUIRED`·evidenceDigest `sha256:f34f75b2…`; evidence
  22 items에 F-03 기록과 일치하는 baseline/current input digest(`f38d51…`/`9c534a…`),
  checkpoint fact(`e1f1d7…`/`4b522e…`), CALCULATION_IDENTITY `cal-v2-0a5fc421465da9512ce82f4c573ce773`,
  reportDigest `sha256:717593ee…` 포함.
- Learning: MCP client의 WorkArea grant는 subset 의미 — WorkOrder의 `work_area_ids` 전체가
  grant에 없으면 목록 0건/단건 404. 좁은 grant 시도 증거(`mcp-allow-narrow-scope.json`) 보존.
- 경계: synthetic 소비자 read 준비 증거일 뿐 parser→VALIDATED→Analysis chain·정확도·고객 수용·
  배포 증거가 아니다(`PARSER_SANDBOX_UNAVAILABLE` 유지). 원본 스택/데이터/tokens 불변, 8093은
  종료·포트 비움.
- 증거: `/tmp/opencode/f04-consumer-20261012/evidence/`(SUMMARY.md, mcp-deny 77a59091…,
  narrow 4a9b4632…, allow a1321c0c…), `~/.cache/ksi-f04-20261012/`(core-*.log). scripts:
  launch_core_f04.py, drive_mcp.py.

### Stage-1 라이브 UI 검증 — 합성 스택 브라우저 패스 (2026-10-12)

- 구성: 원본 F-03 스택(8092)은 그대로 두고 `f03/core-data`·provider 복사본(보호 경로
  `~/.cache/ksi-ui-20261012`)으로 **OIDC issuer(9041) + production factory Core(8041) +
  Console next dev(3241)**을 띄웠다. OIDC registry v1은 local-admin/field-operator/viewer를
  org-a `f03-flow-site`에, 빈 조직 관리자를 org-local-empty에 매핑했다. dev 러너는 만료
  snapshot에서 부팅하지 못해(allow_expired는 production 전용) production factory를 사용했다.
- 검증(데스크톱 1440/모바일 390): 홈→현장→작업/분석/외부 결과 흐름; 분석 목록·상세·근거가
  Core와 일치(완료/실패/재평가 필요; 근거 22항목, reportDigest `sha256:717593ee…` 포함);
  작업 상세의 검사·검증 집계(VALIDATED·3점 0m) 일치; 저장·재조회(작업 배정 유지, 신규 외부
  작업 `obs-work-00000014` 생성→목록 반영); 계정별 게이팅(운영자/열람자/빈 조직); 키보드
  스킵링크; axe 0 violations(홈 color-contrast incomplete 7건은 수동 확인 대상).
- 수정(범위 한정): ① `ExternalEvidencePanel` revision 버튼의 모바일 가로 오버플로(390px에서
  +359px) — wrap 클래스로 해소(전 페이지 overflow 0 확인). ② 외부 관측 이력 빈 상태 문구에
  "분석 기록·근거는 현장 분석에서 확인" 안내 추가. dashboard tsc/lint/vitest 772 passed.
- **결정 필요 — scoped Console 신원의 route 표면 공백 4건**: ① `GET /v1/external-decisions/pending`
  (홈 주의 원장 저하) ② `GET .../relative-volume-requests` ③ `GET .../single-volume-requests`
  (작업 상세 패널 상시 오류) ④ `POST /v1/sites/{site_id}/transitions`(현장 운영자 403; F-01
  §4(f)가 transitions/AOI/roster를 의도적 403 유지로 문서화 — UI는 SITES_WRITE만 보고 노출).
  ①②③은 F-01 allowlist에 없어 403이며, 열기 위해서는 same-site grant 검증을 붙인 검토된 추가가
  필요하다(단순 allowlist 확장 금지 지침). ④는 F-01 매트릭스 유지 시 UI 노출 정리가 맞다.
- 신선한 컨텍스트 사용성 리뷰(스크린샷 16장 소비): 현장 담당자 기준 must-fix로 모바일 등록
  차단 안내, 403 패널의 거짓 재시도 문구, "완료+재평가 필요" 혼합 표기·원문 코드 노출,
  외부 결과 이력과 분석 목록의 발견 경로 분리를 지적했다(상세는 같은 회차 보고·증거).
- 경계: synthetic 전용. parser sandbox→VALIDATED 정량 E2E는 OPEN이며 이 패스는 이를 주장하지
  않는다. 실자료 A–E·고객 수용·배포는 미검증.
- 증거: `/tmp/opencode/ksi-ui-20261012/evidence/`(스크린샷 17장), 로그
  `/tmp/opencode/ksi-ui-20261012/logs/{issuer,core,dashboard}.log`, 런북
  `docs/ops/UI_VERIFICATION_STACK_RUNBOOK.md`.

### Stage-1 후속 — 디자인 작업 공간 UI 수정·검증 (2026-10-12)

- UI/UX 수정은 연결된 Console 작업 공간(baseDir=apps/dashboard)에서 수행했다: 화면 8파일 + 테스트
  7파일(커밋 b409cdc). ① 분석 카드: "실행 완료" 표기 + "계산은 완료됐습니다. 현장 적합성은 재평가가
  필요합니다." + 차단·제한·사유 코드의 한국어 라벨(원문 코드는 API·근거에 유지). ② 외부 관측 이력
  빈 상태에 '현장 분석' 링크. ③ 위저드: 필수 입력 안내 3종 + 작업구역 이름 대체 표시. ④ 작업
  상세·등록·운영의 모바일 경계 안내를 "노트북에서 같은 계정으로 … 이어가세요"로 구체화(노트북 전용
  경계 유지). ⑤ 외부 요청 목록: 401/403에는 재시도 버튼을 숨기고 로그인/권한 안내, 5xx·네트워크는
  기존 재시도 유지. ⑥ 홈 부분 오류 안내에 '현장 전체' 링크.
- 검증(개발 측): tsc·eslint 0 errors, vitest 777/777(신규 5), 라이브 브라우저 데스크톱+390px에서
  변경 문구 확인 및 6개 화면 overflow 0; 캡처 `after-*.png` 5장.
- 렌더 리뷰: 디자인 작업 공간의 실행 샌드박스가 로컬 주소·테스트 러너 접근을 막아 자체 렌더 리뷰를
  수행하지 못했다. 호출자가 실제 캡처를 제공해 **다른 에이전트의 새 네이티브 컨텍스트**로 디자인
  리뷰를 별도 의뢰했다(결과·이미지 소비 증거는 도착 시 기록). 1차 의뢰(Claude)는
  `AGENT_AUTH_REQUIRED`로 실패했고, 인증된 다른 로컬 에이전트로 재의뢰했다.
- Core 변경(커밋 c9ff294) CE 코드 리뷰: 5인(정확성·표준·테스트·보안·적대) — **P1 1건 confirmed**
  (검토 대기 목록 필터가 helper 단위 테스트로만 고정되고 HTTP 레벨 검증이 없음, protected subject:
  authorization-authentication) + 테스트 갭·잔여 리스크(중복 가드·detail route 무가드·부분 grant
  미검증). 후속: HTTP 레벨 pending-decisions 테스트 보강 — **완료**(필터 unwiring 변이에서 실패 확인).
- 독립 디자인 리뷰(다른 에이전트의 새 네이티브 컨텍스트, 캡처 9장 실제 소비) → open 결함 6건
  (상1·중2·하3). "회귀"로 보고된 외부 이력 링크 소실은 호출자가 캡처를 직접 열어 **사실 아님**을
  확인했다(링크 정상). 디자인 작업 공간 수정 라운드에서 6건 fixed + 중복 안내 제거에 따른 테스트
  계약 1건 갱신(커밋 0e723fb). 개발 측 검증: tsc·eslint 0 errors, vitest 777/777, 라이브에서 실패
  카드 안내·카드 제목(작업구역·시각)·요청 버튼 비활성+힌트·모바일 안내 1회·위저드 단일 열·6화면
  overflow 0 확인; 캡처 `after2-*`. 재리뷰: 4/6 fixed(상·중 전부), 2건은 캡처 누락/오류로 재캡처 후
  마무리 라운드에서 3/4 fixed — 최종 **상·중 결함 전부 fixed**, 남은 open은 [하] 모바일 "운영 중"
  배지 정렬(수정 라운드 이전부터 존재; 디자인 작업 공간 후속).
- 권한 회귀 테스트 보강(커밋 e26345a, CE 테스트 갭 후속): volume 목록의 한쪽 grant 차원·부분
  area 겹침(부분집합 아님)·site 불일치·의존성 부재 fail-closed·legacy 조기 반환을 단위로, volume
  상세 route의 mapped 403(legacy는 404)과 교차 조직 pending 비노출을 HTTP로 고정했다.
- 라이브 핵심 흐름(2026-10-12, synthetic): ① 파일 등록 성공 — 합성 GeoTIFF 391/391 bytes 전송 →
  봉인 재구성 rev 1 등록 → 새로고침 후 유지. ② 파일 등록 실패 — GeoTIFF 헤더 불량 파일에 정직한
  안내 + 등록 버튼 비활성. ③ 신규 분석 차단 — Core 503 `ANALYSIS_ACTIVATION_UNAVAILABLE`(환경
  게이트)에 UI는 성공을 주장하지 않고 멱등 재시도·보류 취소를 제공하며 새로고침 후에도 유지.
  ④ 검토 저장 지속성은 미검증 — AWAITING_REVIEW 보고서가 없어(완료 측정 필요) 별도 게이트로 남긴다.
- 발견(디자인 후속 후보): 분석 요청의 지속적 503(활성화 게이트)에도 UI는 "중단된 요청" 일반 문구만
  보여준다 — Core 사유(활성화 필요)를 구분해 안내하면 재시도 루프를 줄일 수 있다.
- 병합: `feat/stage1-live-ui-verification` → main fast-forward(커밋 a18e2af, 2026-10-12), push 없음;
  브랜치 보존. 최종 게이트(2026-10-13, main 전체 contract 스위트): 5470 passed·25 skipped·0 failed.
- 디자인 후속 2건(2026-10-13): ① 모바일 작업 운영 헤더를 단일 행으로 정리하고 상태 배지 좌측 인셋
  제거(우측 인셋 유지) ② 분석 요청의 지속적 503을 활성화 게이트로 구분 — 보류 배너·오류에 활성화
  전용 안내(UNAVAILABLE/EXPIRED) 표시. 테스트 +3, vitest 780·tsc·eslint 0 errors, 라이브 확인
  (새 안내 문구·배지 배치, 캡처 `after4-*`). ③ 컴팩트 판정이 잔여 결함을 발견: 활성화 안내가
  새로고침 후 일반 문구로 되돌아감(플래그가 메모리 상태) → 보류 시도 저장 v2로 차단 코드를 보존
  (커밋 20061a8), 라이브 503→새로고침에서 활성화 안내 유지 확인(vitest 784, 캡처 `after5-*`).
- F-04 2-cycle 스크립트(커밋 af91151): `scripts/rehearse_two_cycle_external_flow.py` — idempotent
  work order→context→v1 register(canonical digest, submittedBy=whoami)→grants→PUT→seal→inspection,
  이어서 pair analysis. 실검증(DUAL 스택, f03-admin-token): t0/t1 봉인(`ers-v1-78c33d…`/`44e94e…`),
  INSPECTION_PENDING_POLICY·503 ANALYSIS_ACTIVATION_EXPIRED 게이트 보고(exit 2), 재실행은 기존
  work order·SEALED 제출을 재사용. 생성 데이터가 UI(작업 상세·분석 셀렉터)에 표시됨을 확인.
- 검토 지속성 blocker(2026-10-13): Console의 리뷰 쓰기는 volume report가 있을 때만 노출되며,
  보고서 생성에는 measurement lane(`ksi-external-validation-worker` config + inspection/measurement
  UDS identity + 서명 measurement manifest·revocation·trusted keys, HTTPS Core origin) 구성이
  필요한데 한 번도 구성된 적 없다 → 완료 측정 확보 시로 OPEN 유지(구체 요건 기록).
- Measurement lane 시도(2026-10-13, 복사 스택): 검토 지속성 검증을 위해 복사 스택(9051/8051/3251,
  Stage-1 무접촉)을 세우고 F-03 레인 선례(인프로세스 레인 + 실제 UDS 측정 피어)로 보고서 생성을
  시도했다. 확정된 게이트 체인: ① provider 스냅샷 만료 → 보존된 서명 키로 seq 25 갱신(현재 유효)
  ② 카탈로그 창·매핑·스냅샷(seq 26) 재서명 후 `/v1/operations/external-authority/reload`가
  `BLOCKED` — 매핑 승인이 **evidence context 만료**로 거부됨(`admit_mapping` →
  `_current_participants` None) ③ 따라서 실행 재활성화·새 요청·보고서 생성 불가. 생산 워커는 별도로
  HTTPS origin + UDS identity를 요구한다. → 남은 요건: F-03 세대 합성 evidence/policy/context 자재를
  현재 창으로 재생성(gen_f03_* 생성기) 후 매핑→실행→스냅샷 체인 재실행.
  ④ 정책/컨텍스트 창 연장 시도가 더 깊은 결합을 확정했다: 정책 **본문**이 자신의 authority record
  다이제스트를 담고 있어(`authorityRecordDigest`) 레코드 창을 새로 서명하면 본문 다이제스트가 바뀌고,
  이는 컨텍스트 `policyDigest` → **evidence record `policyDigest`** → 매핑까지 연쇄한다. 즉 창 연장만
  으로는 불가하고 F-03 자재 체인(정책 본문→레코드→컨텍스트→검사점 evidence→매핑)을 **처음부터 재생성**
  해야 한다(라이브 레인 재실행 포함). 복사 스택은 원래 F-03 기준선으로 복원했다(Stage-1 파일 재복사,
  seq 24·receipts 24 일치, 기동 확인). 자산:
  `/tmp/opencode/ksi-f04-review-20261013/{copy_stack.py,refresh_snapshot.py,refresh_authority.py,
  drive_measurement.py}`(워크스트림 지속 시 scripts/ 승격 검토).
- 경계: synthetic 전용; parser sandbox 정량 E2E·실자료 A–E·고객 수용은 계속 OPEN.

### F-03 체인 재생성 — Console 검토 지속성 로컬 폐쇄 — 2026-10-13 (synthetic, 복사 스택)

- 목표: 전 항목의 검토 지속성 게이트(정책/컨텍스트/검사점 evidence 창 만료)를 체인 **전체 재생성**으로
  폐쇄했다. 복사 스택(9051/8051/3251)만 사용 — Stage-1(9041/8041/3241)·원 F-03 자재 무접촉.
- 재생성 순서(합성): 정책 authority record R'(현재 창) → 정책 v11(`external-geotiff-v1@11`,
  `authorityRecordDigest=R'`) → evidence 컨텍스트 ×2(`policyDigest=v11`) → 카탈로그 권위(현재 창) →
  스냅샷 seq 25(ADMIT_POLICY)+부팅 → 검사 레인 ×2 **MEASURED**(정책 v11, report `66ef0aae…`/`cb9305bb…`)
  → 체크포인트 레인 ×2 **VALIDATED**(evidence record `c976a7d6…`/`22f6bbf6…`) → 매핑 재승인
  (`9619bbcde3499cca…`, executionPolicyRef=카탈로그 C‴) → pair decision **ELIGIBLE** → 상대물량 요청
  `external-relative-volume-69b1a106…` → 측정 레인(RELATIVE_VOLUME) **COMPLETED** → report
  `external-relative-volume-report-ae2d5e64…`(`sha256:da0337c2…`, net 0.0 m³, common-valid 4/4=100%,
  uncertainty ±0 m³) → **Console 검토 쓰기 201**(review `err-v1-0894a51a…`, digest `sha256:9015c31c…`,
  reviewedAt 2026-10-13T04:37:20Z, authority actors `f03-admin`).
  지속성: 새로고침 후 유지 → **Core 재기동 후에도 유지**(동일 13:37 기록, 관측 페이지 병기).
- 재생성에서 확정된 게이트·조치(전부 합성 복사 자료 범위):
  ① reload 중 새 컨텍스트는 *다음* reload에 발행된다(부팅과 달리 historical 폴백이 직전 게재 세대만
  조회) — bump reload(seq 27)로 발행했다.
  ② 체크포인트 레인 UDS 픽스처는 1회용 — 2건 연속 실행 시 2번째가 TRANSIENT로 REJECTED(불변 기록) →
  order-13은 새 컨텍스트 r2 재발행 후 VALIDATED(정직한 재시도 경로).
  ③ F-03 `gen_f03_provider.py`의 카탈로그 실행 envelope(`digest("f03-synthetic-resource-envelope")`)가
  검증 정책 envelope(`c5dca416…`)와 달라 `_policy_matches`(정책↔실행 envelope 동일 요구)가 영구
  불가였다 → 복사 카탈로그를 검증 envelope로 정합화.
  ④ 같은 생성기의 `algorithmBuildDigest=digest("volume-algorithm")`는 PREPARE_V2가 요구하는 측정
  manifest body digest와 불일치 — `_manifest_for_resource_envelope(c5dca416…)`=`1d061713…`로 정합화.
  카탈로그 바인딩은 Core 부팅 시점이라 라운드마다 재기동+매핑 재승인이 필요했고, 동시 active 매핑
  모호성은 서명 `REVOKE_MAPPING`으로 해소했다(F-03 선례).
  ⑤ **인증 allowlist 공백(신규 발견)**: Console(OIDC 매핑 신원) 검토 플로우가 volume 단건 요청 GET
  403·review POST 403으로 막혀 있었다. Human 승인(2026-10-13) 후
  `_OIDC_SCOPED_OPERATOR_ROUTE_ALLOWLIST`에 4개 route 추가(relative/single 단건 GET, relative/single
  report reviews POST) — 핸들러의 WorkOrder grant·review source authority 검사는 그대로다(allowlisted
  `/shares`와 동일 자세). `test_oidc_route_scope.py`의 "detail stay closed" 계약을 "도달하되 핸들러가
  404/409로 fail-closed"로 갱신.
  ⑥ 작업지시 12/13의 `workAreaIds=["wa-…-0001"]`와 분석 구역 `wa-…-0002` 불일치로 scoped 신원은
  보고서/관측 페이지가 404 — **복사 스택 한정**으로 Console 계정을 v2 registry null scope(비스코프)로
  조정해 검증했다. 실자료에서는 작업지시 구역과 분석 구역 일치가 자재 정합성 요건이다.
- 제품 변경(커밋 b4a3905·6c3cc3b, main): `services/core/src/ksi_core/identity/auth.py`(+4 route),
  `tests/contract/test_oidc_route_scope.py`·`test_oidc_external_detail_scope.py`·
  `test_oidc_external_history_scope.py`(구 403 경계 → 도달+핸들러 404/409 계약). 관련 OIDC/volume 계약
  file set 재실행 green; 전체 contract 스위트 최종 **5470 passed·25 skipped·0 failed**(2026-10-13,
  선행 기준선과 동일 수 — 첫 실행에서 남은 구 경계 1건을 6c3cc3b로 정렬).
- 승격·정리: 체인 창 만료 대응을 `tools/regenerate_external_validation_chain.py`로 승격(기록→본문→
  컨텍스트→카탈로그→스냅샷 재생성, receipt head 연속성 fail-closed, real loader preflight, `--check-only`;
  계약 테스트 `tests/contract/test_regenerate_external_validation_chain.py` 4건). 증거는
  `apps/dashboard/f04-review-evidence/`(README+SUMMARY+캡처 3장)로 승격했고 prep/레인 스크립트는
  /tmp 참조를 유지한다. `apps/dashboard/tsconfig.json`의 `.next-f04-review` 타입 루트는 개발 서버
  규약대로 커밋한다(선행 `.next-accept`/`.next-p4-resume`과 동일).
- 2-cycle 리허설 재드라이런(2026-10-13, 복사 스택·재생성 체인): 리허설 전용 opaque 신원
  `f04-rehearsal-admin`(복사 tokens-ui에만 추가, OIDC와 disjoint)로 실행 — 새 페어 wo17/18 등록→grant→
  PUT→seal **SEALED**, 검사는 기존과 동일한 `INSPECTION_PENDING_POLICY`(정책 subject allowlist 불포함)
  ×2, 분석은 503 `ANALYSIS_ACTIVATION_EXPIRED`(activation `validUntil 2026-10-11T19:04Z` 만료) —
  **exit 2, 새 게이트/회귀 없음**, 재실행은 409→기존 SEALED 제출 재사용(멱등). 관찰: 같은
  Idempotency-Key라도 principal이 다르면 새 work order가 생성된다(액터 스코프). 로그
  `/tmp/opencode/ksi-f04-review-20261013/evidence/rehearsal-2cycle-rerun.log`.
  exit 0까지 남은 provisioning: ① 정책 레코드에 리허설/실자료 subject 추가(버전 범프는 검토 스탠드
  매핑·evidence 체인을 무효화하므로 **별도 스택** 필요) ② 분석 activation 재서명(원 F-03 자재는 불변,
  복사본으로 전환) ③ 검사 레인 실행 ④ 분석 워커 경로. 실자료 A–E 도착 시 동일 순서가 요건이 된다 —
  [F-02~04 체크리스트](2026-10-10-f02-04-first-flow-input-checklist.md) §3에 확정 기록. 복사 검토
  스탠드(9051/8051/3251)는 **유지**(증거 기준; 창 만료 후 live 해석은 열화될 수 있으나 리뷰·저널·repo
  증거는 내구). 앞으로 정책 버전을 올리는 검증은 별도 스택에서 한다.
- 검증 준비·소품질 폐쇄(2026-10-13): ① parser-sandbox 검증 호스트 요건+프로브 —
  `tools/verify_parser_sandbox_host.py`(기록된 실측 명령 고정, exit 0=READY/2=BLOCKED, 계약 테스트 6건) +
  `docs/ops/PARSER_SANDBOX_HOST_REQUIREMENTS.md`(DOCUMENT_STATUS 등재; 현 호스트 실측 **BLOCKED** —
  bwrap present만 PASS). ② 고객 자료 요청 문안을 F-02~04 체크리스트 §6에 확정(발송 대기). ③ 대시보드
  소품질 2건: 음의 0 표기 제거(요청/관측/요약/단일 체적의 로컬 `toLocaleString` 을 `formatNumberKo`
  SSOT로 통합) + 요청 목록·선택 줄의 원문 ISO 제거(`formatKoreanDateTime`). 라이브 검증(복사 스택):
  요청 목록 "2026. 10. 13. 12:18"·관측 표 "0 m³"; 대시보드 vitest **788**·tsc/eslint 0. 캡처
  `/tmp/opencode/ksi-f04-review-20261013/evidence/c-*.png`.
- P5 기술 게이트 폐쇄(2026-10-13): ① **broad mypy 109/14 → 0/760**(`uv run --no-sync mypy packages
  services tests tools` → Success, 760 files) — 내 몫(체인 도구·프로브 20건) 포함 15개 파일의 타입
  공백 정리(주석·cast·`mypy_path`에 `examples/analysis`·`examples/spatial-data` 추가, shim private
  재수출, 중복 `_make_guard` 제거). ② **strict archive gate → exit 0(251/251)** — 두 post-move
  adaptation(`build_field0a_kit.py`/`test_field0a_kit.py`, 커밋 `dc9d681` "reviewed adaptation")을
  P5 감사의 방향대로 **append-only adaptation-lineage**로 기록
  (`docs/audit/PHYSICAL_SITE_MOVE_ADAPTATIONS_v1.json`, 원본 inverse 해시·레코드 불변)하고 검증기를
  `--adaptations`로 확장 — 승인된 커밋의 blob과 일치할 때만 두 finding을 수용, 이후 무단 수정은 다시
  실패. 계약 테스트 3건 추가(수용/위조·미기록 인덱스/부재·malformed). DOCUMENT_STATUS·
  REPOSITORY_STRUCTURE의 "blob-identical" 문구도 lineage로 정합화.
- parser-sandbox 검증 호스트 — **로컬 QEMU VM 구성·프로브 READY**(2026-10-13): 신선한 noble VM에서도
  raw `unshare -Ur` 실패가 재현됐다 — Ubuntu 24.04 기본 `kernel.apparmor_restrict_unprivileged_userns=1`
  이 unconfined userns을 막지만 **bwrap에는 자체 AppArmor 프로파일로 userns을 허용**한다(표준 프로파일
  `abi 4.0`+`userns,` 로드 후 uid-map·net-ns 모두 PASS 확인; cloud 이미지는 프로파일이 없어 실패).
  프로브를 이 실제 요건에 맞게 수정(`unshare -Ur`=informational, bwrap checks가 READY 결정; 계약
  테스트 7건)하고, qemu+AAVMF UEFI+cloud-init VM 레시피를
  `docs/ops/PARSER_SANDBOX_HOST_REQUIREMENTS.md`에 기록했다. VM 격리 관측: unprivileged bwrap →
  uid 1000·`FS_HOME_HIDDEN`·`FS_WRITE_DENIED`·`NET_BLOCKED`; hardened 패턴(sudo bwrap+setpriv) →
  uid/gid 10001·`CapBnd 0`·`NoNewPrivs 1`. 증거
  `/tmp/opencode/ksi-f04-review-20261013/evidence/vm-sandbox-capability-20261013.txt`(+serial.log).
  남은 것: 이 호스트에서 실제 parser launch(inspector/rootless-docker stack) → `VALIDATED` 이후 체인.
- push·CI·AMD64 실측(2026-10-13): ⑤ origin(khakisketch)으로 **main push 완료**(203커밋,
  `9edc4a1..5c7a875`). ④ CI는 **실행 불가** — GitHub Actions `enabled:false` + 계정 결제 실패로 과거
  main push 런들도 전부 동일 실패("recent account payments have failed"). AMD64: binfmt/qemu-user
  등록 + `ksi-utest-amd64` 실행(`uname -m` → `x86_64`) 확인; inspector 이미지의 **amd64 에뮬레이션
  빌드는 snapshot.debian.org OpenPGP 서명 실패로 중단**(외부 스냅샷 문제, arm64 레이어는 캐시로 생존).
  amd64 실빌드는 실 amd64 호스트 또는 고정 스냅샷 필요 시 OPEN 유지.
- 대시보드 개발 재개 — A3 구현(2026-10-13, 선구현): [경험 개선 원장](2026-09-17-dashboard-experience-improvements.md)
  A3(F03) 로컬 구현 — 네이티브 파일 입력 3곳(정사영상·DSM·검사점 CSV)을 공유 `FilePickerField`
  (한국어 트리거+sr-only 입력, 브라우저 로케일 chrome 제거)로 교체, datetime 3곳(마감·촬영 시작/종료)에
  한국어 에코(`formatKoreanDateTime`) 추가. 중복 안내 절반은 현 HEAD에서 **재현 불가**(라이브 DOM 0건;
  감사 캡처의 스택 안내는 픽스처 상태)로 종결 기록, C3(F14 설계 업로드)는 P4에서 화면 제거로 obsolete.
  게이트: vitest **792**(+4)·tsc/eslint/build 0; 라이브 `fileTriggers=2·nativeVisibleInputs=0`+에코 확인;
  캡처 `/tmp/opencode/ksi-f04-review-20261013/evidence/a3-korean-file-picker.png`. 독립/디자인 리뷰는
  계획 프로토콜대로 배치 대기.
- 대시보드 B1(날짜/수치 표기 SSOT) 구현(2026-10-13, 선구현): `lib/number-format.ts` 신설
  (`formatNumberKo` 이동 + `formatSignificantKo`·`formatCountKo`·`formatBytesKo`), `phase34-labels`
  재수출로 호환 유지. 원시 `toLocaleString` 15곳(헤더 인식·업로드/해시·분석 패널·공간자산·geotiff
  overlay·워크플로 리포트 지표) SSOT 전환 + 공간자산 관측 시각 `formatKoreanDateTime`. grep-audit 잔여
  **0**(SSOT 모듈 제외); 감사 변형(`2026.8.25.`/`2026.8.25.09:40`)은 현 HEAD에 없음. 게이트:
  vitest **798**(+6)·tsc/eslint 0. 독립 리뷰 배치 대기.
- 대시보드 C1(하단 내비 안전영역, F06) 구현·검증(2026-10-13): 390×844 표준 뷰포트에서는 가림이
  재현되지 않았으나, safe-area 34px 주입으로 Home에서 내비 91px > 본문 여백 64px, 마지막 텍스트
  11px 가림을 재현. `globals.css`의 행 높이·안전영역·clearance 토큰을 `layout.tsx`와
  `MobileBottomNav.tsx`가 공유해 본문 여백을 내비와 동기화. 모바일 E2E가 Home/Sites/Field/작업 상세
  4개 경로에서 34px inset·본문 clearance를 검사. E2E 2/2, vitest **798**, ESLint/tsc/build 통과;
  1440px에서 내비 숨김·본문 여백 0 확인. 오래된 Home 스냅샷은 10-12 unavailable-lane 문구를
  반영해 갱신. 신선한 390/1440 캡처는 `/tmp/opencode/ksi-f04-review-20261013/evidence/c1-*`;
  Design Specialist 독립 리뷰 pass. 실제 iPhone 미검증, 안전영역은 브라우저에서 모의.
- 대시보드 C2(관측 경로 선택, F13) 완료(2026-10-13): 카드의 명시적 `✓ 선택됨`/`aria-pressed`
  (기존 commit `2061411`)을 재검증하고, 폼 h2를 선택 경로와 같은 `외부 산출물 등록`으로 통일
  (`외부 산출물 작업`에서 수정). 1440에서 카드·폼 제목 일치, 390에서 기존 `노트북에서 계속`
  경계 유지. 선택 상태 테스트 6/6, 전체 vitest **798**, ESLint/tsc/isolated build 통과;
  fresh desktop/mobile 캡처 `.../evidence/c2-observation-path-{desktop-1440,mobile-390}-final.png`;
  independent Design Specialist 리뷰 pass. API/도메인 계약 불변.
- 대시보드 C4/F16 단계 레일 시각 확인: 1024×900·1440×1000에서 세 라벨이 230px 레일 안에
  한 줄로 표시되고 잘리지 않음; 768×1024·390×844에서는 승인된 `노트북에서 계속` 경계 확인.
  캡처 `/tmp/opencode/c4-f16-{1024,1440,768,390}.png`. tailnet HTTP 시각 캡처에는
  `crypto.randomUUID`가 없어 `crypto.getRandomValues()` 기반 UUID v4 fallback을 등록 위저드에
  추가함(무작위 품질·API·권한 계약 불변). fallback 단위 테스트 2/2, 전체 Dashboard Vitest
  **799/799**, tsc·production build 통과. 변경 파일 ESLint clean; 전체 ESLint는 오류 0, 별개
  `p4-cleanup-evidence/t4-round4-render-v1/capture-script.js:1` 경고 1건. 격리 E2E는
  기본 원장 principal에 등록 capability가 없어 의도된 권한 거부 화면에서 멈춤; 권한을 바꾸거나
  Site를 제출하지 않았으며 실제 authorized 등록 수용은 미검증으로 유지.
- 증거: `/tmp/opencode/ksi-f04-review-20261013/evidence/{review-before-restart.png,
  review-after-core-restart.png, observations-page.png}`; 상태/다이제스트
  `/tmp/opencode/ksi-f04-review-20261013/chain-phase1-state.json`; 재생성·레인 스크립트 동 디렉터리
  (`regen_chain_phase1.py, regen_context_r2.py, bump_and_reload.py, fix_catalog_and_mapping.py,
  fix_catalog_round2.py, regen_mapping.py, revoke_stale_mapping2.py, drive_inspection_lane2.py,
  drive_checkpoint_lane2.py, drive_measurement.py`).
- 경계: synthetic 전용. 이 폐쇄는 합성 복사 스택의 Console 검토 지속성이며 parser sandbox 정량 E2E,
  실자료 A–E, 검증 호스트, 고객/EXT-VAL 수용을 닫지 않는다. F-04 2-cycle 리허설(실자료)은 별도 OPEN.

### 2026-10-14 첫 사용 경험 개선 — Human 승인·bounded 구현 착수

- Human이 제품 추가 과제 검토 후 제안한 순서에 대해 “그렇다면, 그렇게 진행해보자”라고 승인했다.
  이번 첫 묶음은 **1 시작 안내, 2 보완 행동 안내, 3 관측 선택·근거 가독성**의 Dashboard 구현이다.
  **4 공간데이터 운영 연결은 상세 설계 후속**, **5 다음 회차 재사용은 기존 흐름 대조 후속**이며
  신규 운영 권위·권한 확대·호스트 활성화·실자료 접수·push/deploy 승인으로 해석하지 않는다.
- Git entry: `main` `956a825`, 추적 소스 변경 없음, 기존 미추적 UI PNG 11개 보존. checkpoint의
  이전 `2a1dab1`은 역사적 검증 기준이며 최신 소스와 같은 상태로 취급하지 않는다.
- Requirement IDs: REQ-UX-101, SDP-REQ-01/02/05/06. Owner: `apps/dashboard/`.
  Acceptance: scoped Core 기록만으로 다음 단계/담당 주체를 안내하고, 관측 선택의 구분과
  근거의 계층적 표시를 개선한다. 조회 실패/부분 페이지/알 수 없는 사유를 정직하게 표시한다.
- Contracts affected: 기존 wire/API/auth/calculation 계약 불변; 표시용 helper/component만 추가.
  References/adoption: 기존 Console tokens/components, Core clients, 날짜/수치 SSOT 재사용;
  reference repositories 직접 import나 새 외부 의존/서비스/데이터 도입 없음.
- Planned files: Site/Analysis 시작 안내, `AnalysisRequestPanel`과 표시 helper/component,
  대응 Dashboard test/E2E 및 본 원장/checkpoint. Material UI 판단·구현은 Design Specialist,
  통합/수용 증거 대조는 Build가 소유한다. 실제 변경 파일과 결과는 수신 후 아래 기록한다.
- Tests: 단위·페이지·타입·lint·격리 production build, 실제 로그인 desktop/mobile render,
  unknown/denied/unavailable/expired와 근거 펼침/접기·재조회. Live 복사 스택은 read-only;
  기존 영속 자료·권한·컨텍스트를 수정하거나 성공 화면을 위해 만료 창을 연장하지 않는다.
- Invariants: INV-020/024/040/051/053/060. 신고/봉인/검사/적합성/정확도/검토를 구분하고,
  없는 근거나 좌표·수치를 추정하지 않으며 조회 실패를 빈 자료로 바꾸지 않는다. Server authority,
  scope/tenant nondisclosure, immutable IDs/digests와 race/idempotency fencing을 유지한다.
- HIL/real-device assumptions: 없음. License/data implications: 신규 없음, 합성 read-only 검증만.
  Rollback: 이번 Dashboard/record delta만 역패치; 기존 journals/volumes/configuration/PNG 보존.
  EXT-VAL·실자료 두 주기·parser/운영/고객 수용·제품 slice 상태는 그대로 OPEN이다.

#### 4 공간데이터 운영 연결 — read-only 상세 설계 대조 (미구현)

- Native Plan이 Core/Processing/MCP 기존 계약·실행 경로를 read-only 대조했다. Build도 실제
  `platform_production.py`가 `spatial_data`를 전달하지 않음, `SpatialDataLocalAssemblyConfig`의
  storage/currentness factory 요구, `run_spatial_data_cleanup_once`의 운영 호출자 부재를 확인했다.
  이 검토는 실행 증거나 4의 구현/운영 수용 완료가 아니다; UI 1–3과 병렬인 설계만 수행했다.
- 재사용: native-grid 사각 DSM/RGB/RGBA 준비 primitive, Core grant/job/fence/receipt/download/audit,
  별도 Spatial Data worker 및 stdio 6-tool MCP·HTTP 소비 예제. 재투영/재표본화/새 포맷/공개 URL은 제외.
- 소스 공백: 보호된 production opt-in loader, 진짜 policy/runtime/activation/currentness와 현재
  requester identity 해석, 실제 봉인 매니페스트에 결속된 versioned storage factory, 보호 grant 공급,
  같은 journal owner 안에서의 유한 cleanup lifecycle. 단순 factory 인자 한 줄 추가로 닫지 않는다.
- 선행 결정: KSI 서명/검증키·권리 공급 custodian, opaque/OIDC requester의 배경 작업 권한 수명주기,
  자산/요청 및 확장 bounds/용도/위치/보관의 권리, versioned storage 보장과 운영 책임,
  선택한 API/MCP 소비 환경. 고객 관리자 grant UI·암묵적 동의·Analysis activation 재사용은 승인 없음.
- 후속 제안 순서: A 기본 OFF 운영 어댑터 → B 권리/저장소/회수·복구/cleanup 연결 → C 한 API/MCP
  실제 소비 경로 → Console 접점. 기존 wire/권한/identity를 유지하고 authentic-expired optional lane의
  replay/availability를 분리한다. 추가 Human 결정과 상세 실행 범위 확정 전 source 구현하지 않는다.
- Live signer/grant/configuration/TLS/kernel/launcher·host 검증과 고객 실자료 두 주기는 별도 게이트.
  비활성화 rollback은 새 주입/worker만 중지하고 원본·grant/revocation/job/receipt/audit를 보존한다.

#### 1–3 통합 수용 기준과 기준선

- 시작 안내: scoped Site가 확인된 뒤에만 노출; 작업구역/관측/분석의 읽기 실패는 확인 불가로,
  실제 빈 페이지는 해당 조회 범위의 빈 자료로 구분한다. 일부 자료/분석 성공만으로 모든 준비나
  검사/정량 적합성이 완료됐다고 표시하지 않는다. 열람자·모바일은 새 쓰기 권한을 얻지 않는다.
- 보완 안내: 알려진 사유의 한국어 설명·담당 주체·기존 허용 경로를 연결하고 unknown은 일반 안내와
  원문 technical code를 보존한다. 인증/권한/운영 만료에서 무의미한 재시도를 정상 해결책으로
  제시하지 않는다. Core blocker/limitation/evidence binding과 수치 억제는 바꾸지 않는다.
- 선택/근거: 두 관측의 날짜·revision·식별 가능 정보를 표시하되 자동선택/이름 추정 없음;
  모든 근거·digest·제한을 펼쳐 확인할 수 있고 로드된 부분 페이지를 전체라고 표시하지 않는다.
  분석 선택 전환/근거 재조회에서 이전 선택의 응답이 섞이지 않으며 접기 이후 재조회도 확인한다.
- Entry/same-state 근거: Dashboard803 단위, tsc exit0, lint0errors/기존 warning1은 이번 대화의
  `956a825` read-only 평가에서 실행됐다. 수정 후 별도 재검증 예정; 기존 전체 contract5484는
  2026-10-13 기록이며 이번 source 실행 결과로 승격하지 않는다.
- 병렬 Build 경계 점검: `uv run --no-sync python tools/check_core_module_boundaries.py` exit0(140records),
  Dashboard enum/transition/autonomy sync + physical product/archive boundary5files **49passed**.
  새 UI 행동/렌더 수용 증거는 아니며 Design Specialist 결과 수신 뒤 영향을 받은 UI를 검증한다.
- 4 설계의 기존 계약 대조: spatial-data authority/current-grants/permissions/storage/storage-supervision/
  downloads/cleanup7files **210passed/53warnings**(9.20s). Warning은 multi-threaded process의
  `os.fork` DeprecationWarning이며 숨기거나 운영 안전성 증거로 해석하지 않는다. 이 실행은 기존
  local fixture 계약의 증거이지 새 production adapter/storage provider/host 활성화 검증이 아니다.

#### 1–3 구현 접수·통합 보완·로컬 기술 완료 — 2026-10-14

- 변경 파일13개(Dashboard source/test만): Site `page.tsx`/`SiteStartGuidance.tsx`, Analysis
  `page.tsx`/`AnalysisStartGuide.tsx`/`AnalysisRequestPanel.tsx`, `lib/analysis-guidance.ts`,
  `test/{site-start-guidance,site-detail-start-guidance,analysis-start-guide,analysis-guidance,
  analysis-page,analysis-request-panel}.test.{ts,tsx}`, `analysis-e2e/analysis-workflow.spec.ts`.
  Core/API/schema/auth/worker/calculation·외부 의존은 변경하지 않았다. 미커밋·push/deploy 없음.
- 동작: 기본 현장 화면의 시작 안내는 실제 목록 수와 이력 continuation을 표시하고 실패는
  `확인 불가`로 구분한다. Analysis 안내는 기록 수를 적합성으로 승격하지 않는다. 관측은 촬영
  구간·revision·기존 epoch ID로 구분하고 선택 selector 전체를 펼칠 수 있다. 알려진 blocker의
  담당 주체·다음 행동·기존 read-only 경로와 unknown의 정직한 안내를 제공한다. 근거는 사람 언어
  요약/기술 상세로 구분하며 partial page·원문 code/digest·실패 평가와 숫자 억제 경계를 유지한다.
- Design Specialist 실제 실행 결과 접수: 처음 scoped6files40passed, 전체 **107files820passed**,
  tsc/build exit0, lint0errors/기존 warning1. 기존 격리 Analysis E2E의 normal/viewer-readonly/
  weekly-reuse/missing-vertical-reference/overlapping-current-nodata-cell **각1passed(5scenarios)**.
  viewer390 작업구역 조회에서 등록/archive control 부재 확인. 테스트의 초기 모호한 locator/text
  실패는 정렬 후 통과했으며 runtime 권한이나 assertion의 사실 대조를 완화하지 않았다.
- 실제 렌더: `/tmp/opencode/ksi-start-guidance-20261014/`의 Site/Analysis1440·390 PNG를 Design
  Specialist와 Build가 열어 소비했다. 접근성 audit0violations/contrast incomplete1(자동 확인 한계).
  첫 Analysis 캡처 이후 계산 결과 표의 keyboard scroll region만 추가했고 이후 audit/E2E 통과.
  실제 고객/iPhone/production 수용 증거는 아니다.
- Build 통합 발견·보완: unknown code `__proto__`/`constructor`/`toString`이 상속 속성을 알려진
  안내로 취급하지 않도록 own-property lookup; 접힌 근거의 `limitationCodes`도 summary에 보이도록
  유지. 신규4tests가 **RED4fail/26pass → 최종 전체824pass/107files**로 전환됐다. 서버 사유/기록
  identity·digest는 그대로이고 새 권한이나 파생 적합성 상태를 만들지 않았다.
- 보완 후 Build 직접 실행: `npm test` **824passed**, `npm run lint`0errors/기존 warning1,
  `npx tsc --noEmit --incremental false` exit0. 기존 `createAnalysisTsconfig`로 새 private run-local
  config/dist를 만들어 **isolated production build exit0**; 추적 `tsconfig.json` diff없음.
- 보완 후 normal 실제 inspected Analysis E2E를 `--trace on`으로 재실행 **1passed/28.4s**.
  inspected bytes·selector·report/API/UI 일치, 교차 조직404, 후속 실패 평가의 수치 억제·보완 요청과
  빈 worker queue를 대조했다. 이전 viewer/weekly/두 negative 결과는 변경 없는 권한/API/상태
  기계의 접수 증거로 재사용한다; 실제 고객 두 주기/새 호스트 chain을 뜻하지 않는다.
- 증거: `/tmp/opencode/ksi-start-guidance-20261014/integration/{production-build.log,build-input.json,
  final-source-receipt.json,render-receipt.json,final-render-*.jpeg}`. Build가 새 trace의 최종 시작/선택/
  보완 화면을 열어 확인했다(중간 skeleton frame은 loading 증거만). 최종13file source/test receipt
  SHA256 `b5bf9632051f9b4b83e3bc9dbedca90aa4ba4ad1f31e8964ce76acb698f6b907`;
  trace는 ignored Analysis run output에 유지하고 credentials 포함 가능성 때문에 Git에 올리지 않는다.
- 기존 live 복사 스택의 OIDC `/login?error=Configuration` 문제는 변경/재기동하지 않았다.
  격리 Playwright가 소유한8033/9031/3231 스택과 browser는 종료됐으며 현재 preview 링크로 광고하지
  않는다. 기존 미추적 PNG11개·영속 stack/grant/policy/원본 보존. 전체 Python Ruff의 기존 E5011건은
  이번 Dashboard-only 범위 밖으로 그대로 공개한다; Python 전체 suite/CI를 새 통과로 주장하지 않는다.
- 판정: **1–3 로컬 기술 결과 완료**, Human 사용 수용·제품 slice/EXT-VAL·parser/host·실자료 두 주기
  ·원격 CI·상용 출시/운영 수용은 별도 OPEN. 4는 read-only 상세 설계와 기존 계약 대조까지만이며,
  권리/서명 공급자·requester 수명주기·storage/consumer 환경 결정을 기다린다. 5 신규 구현 없음.

#### 4 운영 어댑터 A+B 구현 — 2026-10-14 (protected production seam, 기본 OFF)

- Human 조건: MCP/AI 우선(Codex CLI), KSI 운영자 권리 관리, 격리 VM 검증, 공개 실자료,
  승인 범위 내 에이전트 직접 실행. 이번 커밋은 **A(운영 어댑터)+B(권리/저장소/복구/cleanup)의
  로컬 기술 구현**이다. C의 Codex CLI 실제 연결·예제 workflow, VM parser/worker 실행, 공개 실자료
  수용, 고객/운영 수용은 별도 게이트로 남는다.
- 기본 OFF: `KSI_CORE_SPATIAL_DATA_CONFIG_FILE` 부재 시 레인 미장착 — 기존 운영 표면·저널·라우트가
  그대로다. 값이 있으면 정규화 절대 경로만 허용하고, 잘못된 형식은 부팅 실패다.
- `spatial_data_production.py`(신규, T5_NEW_MODULE): 보호 파일 로더(0600·무링크·비대체 체인·
  bounded·읽기 중 변경 감지), Ed25519 디태치 서명 검증, exact policy/runtime/activation 결속,
  worker 신원=등록된 SPATIAL_DATA_WORKER 정확 1명(조직 일치), revoked digest 모순 거부,
  **만료 authentic activation 부팅 허용**(보존 이력 replay, 새 작업은 기존 ACTIVATION/CURRENTNESS
  fail-closed), rights 파일(grants+revocations 쌍·현재 policy digest·onprem locus·부팅 시 해석 가능한
  beneficiary), production currentness 포트(opaque+OIDC boot-loaded 신원, is_current=정확 세대+유효+
  비revoked), S3 저장소 팩토리(감독 child에서 fresh client, s3v4·단일 시도·policy-bounded 데드라인),
  source key resolver(봉인 subject→manifest entry, digest/size 불일치 거부), cleanup loop(주기 실행·
  명시 stop, 기존 `run_spatial_data_cleanup_once` 재사용).
- `spatial_data_graph.py`/`platform_graph.py`: assembly `import_rights` 옵션 필드(기본 None) →
  정확 배선 후 멱등 공급·회수 적용. 기존 local/test 조립은 필드 기본값으로 동작 불변.
  `platform_production.py`: 검증(부수효과 이전)→조립 연결→`app.state.spatial_data_cleanup`+
  router shutdown stop. `runtime_config.py` env helper. `auth.py`/`oidc_subject_registry.py`에
  읽기 전용 `principal_by_id`(배경 작업용 신원 조회; 토큰 해석·원격 재인증이 아니다 — 토큰 폐기·
  subject REVOKED는 다음 Core 재기동에 반영).
- 검증(로컬 소프트웨어, 합성 자료): 신규 `test_spatial_data_production_adapter.py` 13건 — 부재=미장착·
  0644/서명/신원/revocation 모순 부팅 실패·회전 digest 중복 허용·만료 authentic 부팅+is_current False·
  정책/beneficiary 거부·부팅 후 rights 저널 provisioned/revoked 각 1·import 멱등+회수·currentness
  opaque/OIDC/무효·manifest key 정확 일치+불일치 거부·cleanup loop 실행/정지. 배치 결과:
  spatial-data 계열+신규 **222 passed**, production/auth/OIDC **190 passed**,
  platform http/replay/spatial http/normalization/boundary **66 passed**.
  repo-wide `ruff check .` **All checks passed**(기존 E501 1건 포함 정리), full mypy **762 files
  Success**, core module boundary **141 records exit0**(신규 모듈 inventory 등재).
- 경계: 이 증거는 A+B의 로컬 계약·회귀 증거다. 라이브 서명키/grant 발급·보호 구성 배치, 실제 S3
  버전·전체 체크섬·정확 버전 삭제의 운영 확인, VM parser→worker→consumer 체인, Codex CLI 실제
  연결, 공개 실자료 수용, 고객/운영 수용, 배포/CI는 **OPEN**이다. 테스트의 서명·정책·자료는 로컬
  생성물이며 발급 권위·제공자 보장·정확도 주장이 아니다. 1–3 UI의 Human/고객 수용도 별도다.
- Rollback: 새 env 부재로 레인을 내리고(기본값) cleanup loop를 중지하면 된다. 기존 저널·grant/
  revocation·job/receipt/audit·원본은 보존되며 삭제되지 않는다.
- 운영 문서: `docs/ops/SPATIAL_DATA_PRODUCTION_PROVISIONING.md`(DOCUMENT_STATUS 등재) — 보호 파일
  형식·검증 규칙·기본 OFF·cleanup·rollback·남은 게이트를 구현·계약 증거 기준으로 고정. 테스트
  키/구성은 형식 증거이며 운영 발급이 아니다. worker 신원 검사는 동일 Principal의 회전 digest
  중복을 허용한다(13번째 테스트로 고정).
- 최종 게이트: full contract `pytest tests/contract -q` **5497 passed·25 skipped·0 failed**(746.68s,
  10-13 기록 5484 대비 +13 = 신규 adapter). repo ruff 전체 green, full mypy 762, boundary 141.

#### 4 공간데이터 운영 연결 — 첫 로컬 수용 리허설 (Codex CLI·실 MinIO) — 2026-10-14

- 보호 레인 실부팅: 합성 재료 생성기(서명 activation·운영자 grant·명시적 token registry)로
  production factory(8061)에 `app.state.spatial_data` mount, grant 멱등 import 확인. 운영자
  카탈로그 200(20자산; 대상 DSM `ksa-v1-8430fcc…` MEASURED). 실 inspection 레인(인프로세스
  선례, 실제 MinIO 바이트)으로 현재 정책 요청 2건 `MEASURED`(2×2 EPSG:5186).
- **결함 발견·수정**: `SPATIAL_DATA_MCP_CLIENT`가 `KSI_CORE_PRINCIPAL_TOKENS_JSON`으로 scope
  배열과 함께 등록될 수 없었다(파서가 ANALYSIS_MCP_CLIENT만 허용) → `runtime_config._parse_principal_tokens`
  수정 + 계약 테스트, 런북에 등록 형식 명시. (커밋)
- **Codex CLI 실연결**: 0.160.1(ChatGPT auth)에 spatial-data MCP stdio 어댑터 구성 — initialize/
  tools 6종 확인, `tools/call`이 Core에 도달해 유한 예산의 typed 응답(`RESOURCE_LIMIT_EXCEEDED`)을
  정직하게 반환.
- **스토리지 보장 프로브(로컬 MinIO) 16/16 PASS**: 버전 ID·FULL_OBJECT SHA-256 HEAD 일치·정확 버전
  읽기·목록·서명된 `host;x-amz-checksum-mode` presigned GET 바이트/헤더 일치·정확 버전 삭제·삭제본
  불가·타 버전 생존·정리. 미서명 추가 헤더를 보내는 클라이언트는 MinIO가 400으로 거부(제품 전송은
  서명 헤더만 사용). 클라우드/고객 S3는 별도 OPEN.
- **차단(재현 정확)**: 10-12 사본 체인을 `tools/regenerate_external_validation_chain.py`로
  갱신(seq 24→25)한 뒤 AI 발견 라우트가 `CURRENTNESS_UNAVAILABLE`(503) — 페이지 투영이 각 후보를
  materialize할 때 구세대 정책에 묶인 오래된 보고서가 per-source currentness 재검사에서 실패하고,
  `CURRENTNESS_UNAVAILABLE`은 `_LIST_SUPPRESSED`가 아니어서 페이지 전체가 실패한다. 같은 실행에서
  갱신 레코드는 digest 일치로 resolve됐으나 reconcile 시점 `permits_selection(use="EVIDENCE")`가
  False였다. fail-closed(무음 성공 없음)이며 정확한 selection 상태 원인은 체인 재생성 검토 과제.
- 경계: **synthetic 로컬 증거**이며 bwrap containment·VM 체인·클라우드 S3·공개/고객 수용·배포/CI는
  OPEN. 상세 증거·rig: `docs/audit/SPATIAL_DATA_CODEX_LOCAL_ACCEPTANCE_2026-10-14.md`,
  `/tmp/opencode/ksi-sdata-codex-20261014/`. 초기 기록의 "체인 검토·억제 결정" 후보는 아래 후속에서
  수정·완주로 종결됐고, 남은 후보는 VM/샌드박스 체인과 클라우드/고객 S3·수용이다.
- **후속(같은 날): preflight 스냅샷 결함 수정 + Codex happy path 종단 완주.** 활성 selection이 없는
  후보에 대해 `public_snapshot_bounded`가 과거 보고서로 폴백하던 경로를 제거(비ACTIVE = 보고서 없음·
  PENDING) — 한 후보의 구세대 보고서가 비억제 `CURRENTNESS_UNAVAILABLE`로 목록 전체를 503으로 만들던
  결함과 카탈로그의 stale `MEASURED` 표시를 함께 교정. `require_current`의 최종 check-and-commit
  CURRENTNESS 계약은 불변(기존 withdrawal 테스트 유지). 신규 테스트 2건: 스냅샷 은닉
  (`test_bounded_inspection_without_active_selection_hides_stale_report`)·프리플라이트 분류
  (`test_source_withdrawal_classifies_listing_preflight_as_unmeasured`). 검증: 영향 스위트
  501+55+85 green, repo ruff green, full mypy **762 files**.
- **Codex CLI 종단(수정 빌드, 합성 복사·실 MinIO)**: 발견 200(대상 `ksa-v1-8430fcc…`
  `READ`+`PREPARE`, 혼합 세대 후보는 후보별 `SOURCE_NOT_MEASURED`로 억제) → 생성 201
  `sdj-v1-a9bb54c9…` QUEUED/NOT_READY → 조회 동일 → 취소 CANCELED(저널 `issued`→`state=CANCELED`).
  앞선 실행이 8061을 점유한 낡은 프로세스에 응답하던 문제는 rig 런처의 포트 정리로 수정하고 최종
  증거를 새 pid로 재확인했다. prepared/`COMPLETED` 절반은 여전히 샌드박스 준비 레인·호스트
  containment 게이트에 의존한다.

### 2026-10-14 공개 실자료 + VM 검증호스트 수용 — 발견→COMPLETED→소비 완주

- 범위: 공간데이터 제공 경로의 **첫 실자료 수용**. 실자료는 Cambridge Coastcare Floreat-f4
  DSM(181,498,053B)·정사영상(346,715,111B), CC BY 4.0, `0400` 보관. 격리 QEMU/virtio VM
  (Ubuntu 24.04 arm64), 실 MinIO, 실 Core, 실 Codex CLI, 실제 컨테인먼트 워커.
- 수용 중 **제품 결함 2건 발견·수정(커밋 d286c13)**: (1) 컨테인먼트 자식의 자체검증이 교차
  userns ns-stat 커널 규칙(6.8.0-142 실측, 동일 uid 포함 거부)과 `≠authority` 조항의 **양립
  불가**로 어떤 실제 launcher에서도 exit 2 → 요청 프레임 v2에 워커 자신의 ns inode를 실어
  자식이 수치 비교하고, 커널 관측은 부모가 유지; (2) `os.memfd_create`/`fcntl` seal 상수가
  없는 standalone CPython 빌드에서 스폰 전 `AttributeError` → libc `memfd_create` 폴백(동일
  CLOEXEC/sealing). 회귀 테스트 3건 포함, 공간계열 547 tests·ruff·mypy green.
- 수용 자재(합성·서명, 제품 정책 아님): 검사 정책 v17에서 실자료 **MEASURED**(report
  `sha256:18ef998a…`; 공개 subject 추가는 `--add-subject-file`, 커밋 f77298d), 공간 정책
  `d6f54928…`·grant rev2(CC BY 4.0 표기 유지). 스토리지 계약: 버킷 버전닝 비활성 →
  `input` 503 `INTEGRITY_MISMATCH` → 버전닝 활성 + 실바이트 재업로드(체크섬 일치, 버전
  `bf667e8e…`/`b1e368c8…`).
- **완주(실측)**: Codex MCP 발견→생성(`sdata-public-accept-final`, `sdj-v1-ca9b7b2f…`) →
  VM 워커(uid 10001·file-cap, TLS, 영속 네임스페이스: caps 0·NNP1·Seccomp2·mountinfo 고정·
  rlimits) → 181MB 실자료 다운로드 → 실제 크롭(2000×2000, EPSG:7850) → receipt 업로드 →
  **COMPLETED**(출력 `0fcb7fd7…`, 9,166,428B, window [1357,3357,3633,5633]) → HTTP 소비자
  다운로드(헤더/영수증 검증) → **독립 오라클 PASS 11/11**(원본 직접 윈도우 대조: 픽셀·마스크·
  유효수 4,000,000·변환·CRS·경계·바이트 동일). 디버그 반복 중 완료된 `sdj-v1-543dc281…`도
  동일 흐름. 실패 중간 시도(봉투/버전닝 이전)는 저널에 그대로 남긴다.
- 경계: **합성/검증호스트 수용**이며 클라우드·고객 S3, 고객/운영 수용, 배포/CI, 두 번째
  호스트/주기 재현, file-cap 런처 하네스의 배포 적합성·제품측 참고자료 검토는 OPEN. 감사:
  `docs/audit/SPATIAL_DATA_CODEX_LOCAL_ACCEPTANCE_2026-10-14.md`; 증거:
  `/tmp/opencode/ksi-sdata-codex-20261014/evidence/public-sample/`.

### 2026-10-14/15 F-03 사슬 — 측정(measurement) 컨테이너 실기동 개시 + 체크포인트 VALIDATED

- **범위**: Task 5번대 사슬의 후반부를 인프로세스 하네스가 아니라 **실제 measurement 컨테이너**로
  통과시키는 작업. VM2에 inspector + measurement 데몬 동시 기동(수용 카탈로그·서명 승인·격리
  프로파일), Core :8092 + MinIO :9100은 기존 F-03 rig 유지.
- **호스트 기동에서 드러난 제품 결함 4건(전부 수정·회귀 테스트·커밋)**:
  - `d3d3e3d` measurement 교차 바인딩이 `baseControlGroup == launcherCgroupPath`를 요구하나
    cgroup v2에서 불가능(데몬=슬라이스 서비스 자식, 슬라이스 내부 프로세스 금지) → inspector와
    동일한 "슬라이스 접미 + launcher는 base의 strict descendant" 규약으로 수정.
  - `33848af` 대체 context 세대로 발급된 구 pending 레코드가 큐 머리를 점유한 채 매 시도
    `CONTEXT_UNAVAILABLE` → pending은 자연키별 **최신 발급만** 유지(스토어 자체 이력만 사용,
    authority 재조회 없음 → 재기동 replay 계약 유지).
  - `35ac36e` 워크스페이스 tmpfs가 root 소유라 두 entrypoint의 소유자 검사(`/work`)가 실패,
    컨테이너가 control frame 없이 exit 2 → tmpfs 옵션에 `uid=<runtime uid>,gid=<runtime gid>` 추가.
  - `6dea5bd` create payload가 `/work`을 Mounts(tmpfs)와 legacy Tmpfs로 **이중 선언**하고 실제
    Engine에서는 Mounts가 legacy를 대체(TmpfsOptions에 uid/gid 불가, `invalid option: uid`)
    → legacy 단독으로 통일, inspect 검증은 입력 마운트 1건 기준으로 정렬(컴파일 보안 프로파일의
    `workspaceTmpfs.hostConfigField == "HostConfig.Tmpfs"`와 일치).
- **진단 경로(증거 보존)**: worker `measurement exchange unavailable` → 데몬
  `V2 container ended before its control frame` → inspect exit code 2 → 컨테이너 내부 traceback
  (`private workspace identity is invalid`) 확보를 위해 데몬 payload 그대로의 raw attach(101)
  + 동일 타이밍 재현 → CLI(`--tmpfs`) vs payload 비교로 Mounts 그림자 규명. 기록:
  `/tmp/opencode/ksi-inspector-host2/NOTES.md`.
- **체크포인트 VALIDATED(실 컨테이너)**: 2×2/0.1 m 합성 DSM(원점 200000/550000) 내부 3점·에폭별
  고도 100.0/100.2로 evidence 재봉인 → 새 context 세대(r17, seq 48) 승인 → worker가
  `CONTAINER_BOUND → CLEANUP_REQUIRED **BACKEND_COMPLETED** → CLEANED`. 두 subject 모두
  **VALIDATED**: `measuredCheckpointCount 3`, mean/mae/rmse/max = **0.0 m**, `factClass OBSERVED`,
  policy v14 `sha256:14292178…`(레코드: `…9acdf2332892e4db`, `…8d798056518f7119`).
- **남은 사슬**: 상대체적 분석(RELATIVE_VOLUME — 동일 measurement 이미지·데몬 경유) → Result/
  Evidence → 운영자 review. 합성/검증호스트 수용이며 클라우드·고객·배포 게이트는 여전히 OPEN.
- **경계(시험 자재 표기, 2026-10-15)**: 서명 권위 체인 로더는 `synthetic_test_only=true` 기록을
  거부하므로(`provider_loading`), 합성 F-03 자재는 체인에서 unmarked로 승인된다. 이는 테스트
  픽스처가 아니라 운영자 서명 자재의 정상 표기이며, "합성/검증호스트 수용" 라벨은 원장·감사
  기록이 담당한다. 제품 코드 변경 없음. 같은 날 큐 필터 보완(`ce3e185`): 거부된 claim이 권위가
  실제 해석한 세대를 학습해, pending이 발급 순서만으로 권위를 판단하지 않는다(재기동 replay
  계약 유지, 뮤테이션 검증 2건).

### 2026-10-15 parser→review 전 구간 완주 — 등록→실파서 검사→실측정 검증→ELIGIBLE→분석→검토 (v19 세대)

- **범위**: 같은 페어·같은 구역으로 등록부터 운영자 검토까지 **단일 체인**을 실제 컨테이너(파서·측정)로
  완주. 이전 세대의 개별 성공을 이어붙인 것이 아니라, v19 정책 세대 하나로 검사·체크포인트·매핑·
  분석·검토를 모두 새로 실행했다.
- **자재**: 신규 오더 `obs-work-00000014/00000015`(에폭 2026-10-09 03:00/04:00, DSM 100.0/100.2 +
  **RGB ortho**), 정책 v19(동일 규칙·주체, 7일 창) + r23 evidence contexts, evidence는 수정된 3점
  CSV(DSM 내부 좌표·에폭별 고도) 재봉인.
- **실행 결과(실측)**:
  - 검사: v19 2건 `reported`, 모든 outcome `MEASURED`(dsm 2×2 + ortho RGBA) — 실제 파서 컨테이너.
  - 체크포인트: v19 2건 `VALIDATED`(3/3, mean/mae/rmse/max = 0.0 m) — 실제 measurement 컨테이너.
  - 매핑: `sha256:08e15ba7…`(zone `wa-f03-flow-site-0002`, EPSG:5186) seq63 `PROVIDER_CONFIGURED`.
  - 결정: `external-use-decision-98a1e861…` verdict **ELIGIBLE**(USE_ELIGIBLE).
  - 분석: `analysis-v1-1e323d5b090d56fc1c5cfb8416c29105` 생성 202(QUEUED/EVALUATED, blockers 없음) →
    분석 워커 1회 실행 → **COMPLETED**. 결과 `report-35e0f171a4c7c4ce6a3c897bc80f8e3d`
    (digest `sha256:095fea9c…`), net/fill = **+0.008 m³**, cut 0, coverage 4/4, uncertaintyM3 null.
    **수치 검증**: Δ=0.2 m × 4셀 × 0.01 m² = 0.008 m³ — 실행 결과와 정확히 일치.
  - 검토: `arv2-8851133ce61a3dea…` ACKNOWLEDGED(reviewer f03-admin) + factual limitations 3건 명시.
  - 전 항목이 클린 코드 재기동 후에도 유지됨(최종 스윕 200/COMPLETED/ACKNOWLEDGED).
- **이번 단계의 원인 규명(제품 결함 아님 — fail-closed 정상 동작)**:
  - 검사 실패(TRANSIENT 반복)의 원인은 두 데몬 모두에서 관측된 VM systemd transient slice 생성
    **AMBIGUOUS**(야간 이후 1회성) → 데몬 래치(admission closed) → 이후 연결 즉시 종료(EPIPE).
    복구는 표준 절차(실패 시도 보존 → 스테이징/저널 정리 → 재기동)로 완결, 재발 없음.
  - 매핑 거부(`signed mapping admission was not applied`)는 `_binding_facts_match`의
    **모든 outcome MEASURED** 요구에 따른 정상 거부였다 — 구 valid 페어의 "ortho"는 회색조 복사본이라
    파서가 `UNSUPPORTED_RASTER`로 거부했고, 매핑은 오염된 패키지를 받지 않는다. 해결: 제출 계약이
    요구하는 **RGB ortho**(측정 가능)로 재등록.
- **리그 정비(재실행성)**: 프리플라이트(`f03-rig-preflight.sh`), 스냅샷 갱신, analysis activation
  갱신(키4+레지스트리, 7일 창), 카탈로그 권위·템플릿 창 갱신(`renew_catalog_authority.py` — 부팅
  리컨사일이 카탈로그 권위 창을 요구), 정책/컨텍스트 세대 스크립트. 함정 기록: 창 만료 시
  `/ready/external-authority` 503·부팅 리컨사일 차단(RECONCILIATION), 제출은 ortho 1개 필수,
  리뷰 라우트는 `/v2/sites/{site}/analyses/{id}/review-target`·`/reviews`.
- **경계**: 합성/검증호스트 수용이다. 고객 실자료 A–E·Terra 호환·현장/측량 수용·배포/클라우드
  게이트는 그대로 OPEN이며, 위 수치(0.008 m³)와 0.0 m 오차는 합성 입력의 계산 일치 증거이지
  현장 정확도 증명이 아니다.

### 2026-10-15 Task 5c 실호스트 강제 검증(1차) — `f105dfd`

- 도구: `tools/task5c_host_enforcement_verify.py`(승인 호스트의 launcher 사용자로 실행) — 실제 user manager/
  rootless Engine/cgroup v2에 대해 **27 PASS·0 FAIL**: `StartTransientUnit mode=fail` 중복 거부, 정확한
  ControlGroup 하위성, controllers(cpu/memory/pids)·신규 `usage_usec=0`, `CgroupParent`→시도 slice 매핑
  (`/proc/<pid>/cgroup` 실측), `cpu.weight=100`, `populated 0→1→0`, 정확 제거 전 안정 CPU 2회 동일,
  `StopUnit`+unit/cgroup 소멸, 능동 격리 프로브(uid 매핑·read-only rootfs 거부·네트워크 거부·`lo`만·
  /work 소유권).
- 프로토콜: 실제 measurement entrypoint로 캡처 프레임 실행 — 익명 스풀 ack(`SECONDARY_STAGED`)→
  `PRIMARY_MOUNT_VERIFIED`→타입드 `FAILED` 종료, stdout 완전 소비(클린 종료)·stderr 0.
- 감사: `docs/audit/EXTERNAL_INSPECTOR_ROOTLESS_PROFILE_VERIFICATION.md`. OPEN(정직 표기): `-k 'host_'`
  pytest 케이스 전환, 취소 지연 수치·고아 복구 훈련, 적대 입력 E2E — "unavailable is failure" 유지.

### 2026-10-15 주간 재사용(t1→t2) + 적대 입력 E2E + Task 5c pytest 전환

- **적대 입력 실호스트 E2E**: 계약이 요구하는 ortho 자리에 잘린 GeoTIFF(약 60% 절단)를 제출(order 17) → 실제
  샌드박스 파서가 **`REJECTED`/`MALFORMED_TIFF`** 타입드 판정을 기록하고 레인은 정상 완주(격리 유지·크래시
  없음). 같은 세대(v20)에서 정상 페어 dsm+ortho는 전부 `MEASURED`. in-process 40케이스(Task 5a)와 함께
  적대 입력이 실컨테이너 경로에서도 fail-closed임을 증명.
- **주간 재사용 t1→t2**: 동일 WorkArea/zone(0002)/rule/profile/template, 새 페어(18=04:00–04:30 DSM 100.2,
  19=05:00–05:30 DSM 100.4 + RGB ortho)로 fresh 입력 결속 admission — v23 단일 세대 → 검사 2× 전부
  `MEASURED` → 체크포인트 2× `VALIDATED`(3/3, 0.0m) → 매핑 `f446f34f…` seq76 → 결정 ELIGIBLE →
  `analysis-v1-c0294d58…` **COMPLETED**(`report-91ea5166…`, net **+0.008 m³** = 0.2m×4셀×0.01m², 수치 검증,
  `uncertaintyM3=null`) → 검토 `arv2-573a59e5…` ACKNOWLEDGED. 진단 계측 원복 후 클린 재기동에도 유지.
- **드러난 제품 규칙 2건(정상 동작, 리그 교훈)**: ① RELATIVE_VOLUME 정책 선택은 허용 주체가 **정확히 그 페어**
  여야 한다(추가 주체 포함 시 POLICY_UNAVAILABLE — pair-scoped authority). ② 분석 admission은 subject의
  **모든** terminal 사실이 현재 세대여야 한다(정책 회전 시 과거 사실의 정책/컨텍스트가 non-current가 되면
  `EVIDENCE_CONTEXT_UNAVAILABLE`) — 계약의 "새 페어는 fresh 입력 결속 admission"과 일치하며, 재사용은
  같은 구역/규칙/프로필을 재사용하되 페어별 새 주체·기록을 쓴다.
- **Task 5c pytest 전환**: `tests/contract/test_external_inspector_host_enforcement.py` 5케이스가 승인
  호스트에서 도구(`tools/task5c_host_enforcement_verify.py`)를 SSH로 구동해 조각별 증명을 단언. 호스트 미구성
  시 명시적 NOT_VERIFIED 사유로 skip(수용 아님). **결정적 선택 실주행: 6 passed**(5 host + import-boundary).
- 경계: 합성/검증호스트 수용 유지. 고객 실자료·현장 정확도·배포/클라우드/CI는 OPEN.

### 2026-10-15 전체 스위트 게이트 결과 — 1건의 선행(pre-existing) 실패

- 실행: `pytest tests/contract tests/replay` → **5788 passed · 1 failed · 25 skipped**(759s).
- 실패: `tests/replay/test_external_artifact_inspections_replay.py::test_replay_preserves_report_time_display_obligation_after_same_time_revocation`
  — 단일 재실행에서도 결정적 실패. **원인 커밋 판별: `55e5dc7`의 부모에서도 동일 실패**(이번·직전 세션 무관).
- 성격: 구설계 기대값(리포트가 기록된 뒤 같은 시각 리보크가 일어나도 현재 검사 스냅샷이 리포트를 노출)과
  현 스토어의 문서화된 설계(“비활성 세대의 리포트는 현재 검사가 아니라 이력 조회 전용, `public_snapshot_bounded`
  docstring”)가 충돌. 같은-시각 리보크의 표시 의무를 어떻게 해석할지의 **제품 결정 필요**:
  (a) 현 설계 유지 → 해당 테스트를 이력 조회/현재 억제 검증으로 개정, (b) 표시 의무 우선 → 동일-시각(및
  그 이전) 리보크가 기록 완료 리포트를 무효화하지 못하도록 투영 수정(append-order 중재). 변경 전 Human
  판단 또는 별도 검증 세션을 둔다 — 이번 세션에서는 임의로 어느 쪽도 택하지 않았다.

### 2026-10-15 후속 폐쇄 — replay 테스트 개정 + Task 5c 취소 지연 실측

- **선행 실패 해소(`8bd098c`)**: `test_replay_preserves_report_time_display_obligation_after_same_time_revocation`을
  승인된 stale-report 설계(a699f35, 스토어 docstring)에 맞춰 개정 — 현재 검사 스냅샷은 비활성 세대에 대해
  `INSPECTION_PENDING_POLICY`(리포트 없음)를 보고하고, **불변 이력**(레코드의 리포트·`display_required`·
  `historical_report` 조회)은 재기동 후에도 바이트 그대로 보존됨을 단언. 의무는 약화가 아니라 강화(이력 조회
  명시 단언 추가). replay 12 passed.
- **Task 5c 취소/지연 실측 추가**: `tools/task5c_host_enforcement_verify.py`에 P13(정확 Engine kill 드릴) —
  populated 1 → `POST /kill` 204 → **cgroup 소진 86 ms**(상한 15 s) → 정확 제거 → `StopUnit`. 호스트
  pytest 케이스 1건 추가, 결정적 선택 **7 passed**(host 6 + import-boundary). 감사 문서 갱신: 취소/지연 PASS,
  고아 복구는 사건 기반 실증 유지.
- **전체 스위트 재실행 결과(0 failed)**: `pytest tests/contract tests/replay` → **5789 passed · 0 failed · 31 skipped**(761s).
  직전 실행의 유일 실패였던 same-time revocation replay 케이스가 승인 설계 정렬(8bd098c)로 해소되어 게이트가 clean이다.
  skipped 31건은 환경 의존(호스트 미구성 NOT_VERIFIED·외부 경계) 표기다.

### 2026-10-15 보존 t1 재사용 실증 — 이전 세대 봉인 주체를 다음 회차 기준으로 사용 (seq 77 carry-forward)

- **배경(원인 규명)**: 앞선 재사용 시도 `analysis-v1-04f7d097…`(base=`f03-valid2-submission-4`, cur=`f03-valid3-submission-5`)가
  `BLOCKED/EVIDENCE_CONTEXT_UNAVAILABLE`이었던 원인은 엔진 제약이 아니라 **운영자 서명 자재의 선택**이었다 —
  각 세대 bump 스크립트가 `policyAuthorities/evidenceContexts.currentDigests`를 **새 페어만으로 교체**해,
  과거 사실(fact)의 정책 권위·컨텍스트가 non-current가 되었다. 코드 확인: `admit`은 자동 대체하지 않고
  `SUPERSEDED`는 명시 행위(이 리그 저널에 revoke/supersede 0건, 23개 세대 전부 ACTIVE), 컨텍스트 현재성은
  서명 스냅샷의 `currentDigests` 목록이 결정한다. 계약(첫 요청 계약 Weekly reuse)의 "이전에 검증된
  per-artifact evidence는 정책 조건이 유효한 동안 동일 artifact/digest로 참조 가능"과 일치.
- **carry-forward 자재(seq 77)**: `admit_carryforward_reuse.py` — 정책 권위 v19..v23을 currentDigests에,
  재사용 페어 두 주체의 **7개 컨텍스트**(Core 저널 issued 이벤트에서 바이트 추출·재검증: valid2-4×3,
  valid3-5×4)를 기존 v23 페어 컨텍스트와 함께 기록. `actions: []`(문서화된 no-op 델타; 매핑 5cdd348f는
  seq 73에서 이미 적용·유지). reload 200/PROVIDER_CONFIGURED, `/ready/external-authority` 200.
- **재사용 분석 완주**: 동일 selector(order 15 → order 16)로 새 분석 `analysis-v1-94d20026…` 생성 →
  **QUEUED**(blockers 없음; 직전 BLOCKED 해소) → 분석 워커 1회 → **COMPLETED**.
  결과 `report-0caec0bc…`(digest `sha256:1e3747cc…`), **net/fill +0.008 m³**(Δ0.2m×4셀×0.01m², 수치 검증),
  coverage 4/4, uncertaintyM3 null, limitations 0. 검토 `arv2-89b1766f…` ACKNOWLEDGED.
- **"참조"의 증명**: 실행 중 `external-artifact-inspections.jsonl`·`external-evidence-validations.jsonl`
  저널이 **무변화**(13:55 이후) — 새 검사·재검증 없이 기존 봉인 artifact/digest·검증 기록을 그대로
  참조했다. 청정 재기동 후에도 결과·검토·v23 체인(c0294d58 COMPLETED, 91ea5166, +0.008 m³, ACKNOWLEDGED) 유지.
- **경계**: 합성/검증호스트 수용. 세대 회전이 있는 실운영에서는 회전 시점 자재에 참조 유지 여부를
  선택하게 된다(미유지 시 fail-closed `EVIDENCE_CONTEXT_UNAVAILABLE` — 의도된 동작). 현장/고객 수용은
  여전히 외부 게이트.

### 2026-10-15 Task 5c 폐쇄 — 호스트 취소/고아 드릴 + UI 일치 재검증

- **드릴 도구(신규, `4024561`)**: `tools/task5c_host_lifecycle_drill.sh` — 자체 완결(런타임 venv로 드라이버·GeoTIFF
  입력 생성). **D1 취소**: 실제 시도가 `CONTAINER_BOUND`일 때 드라이버 SIGKILL(완전 피어 소실) → 데몬이
  `MONITOR_CANCELLED`로 정확 런타임만 kill → 컨테이너/slice/staging 정확 정리 → **durable `CLEANED`**
  (실측 0.18–1.04 s) → 재기동 없이 서빙 지속, 이후 새 시도 `COMPLETED`/`MEASURED`.
  **D2 고아 복구**: 시도 중 데몬 SIGKILL → 살아 있는 고아(컨테이너·`ksi-inspector-a*` slice·staging 2건) 실확인 →
  재기동 → `CLEANUP_REQUIRED(STARTUP_RECOVERY)` → 정확 제거 → slice 소멸 → staging 정리 → `CLEANED`
  (0.11–0.13 s) → 새 시도 `COMPLETED`/`MEASURED`. 저널 실기록 `/var/lib/ksi-external-runtime/launcher/journal/attempts.jsonl`
  (드릴 실행 2회분: 05:56–05:57Z 수동, 05:59–06:01Z 결정적 선택 실행).
- **결정적 선택 전환**: `tests/contract/test_external_inspector_host_enforcement.py`가 두 도구(P1–P13 + D1/D2)를
  SSH로 구동 — **9 passed · 258 deselected**(180s). 감사 문서: 적대 입력(실레인 `MALFORMED_TIFF`)·취소·고아 복구
  모두 PASS로 승격, OPEN 항목은 외부 경계만 남김.
- **UI 일치 재검증(Playwright, F-03 자재)**: 콘솔 스택을 현재 F-03 기록으로 갱신(provider seq 77 + core-data
  복사) 후 대화형 검증 — OIDC 로그인, **분석 시작 안내**(3개 작업구역·19개 관측 후보·7개 분석 기록), 작업구역
  선택→기준/현재 관측 목록 채움(에폭·revision 표기), **재사용 분석 상세**(report-0caec0bc·실행 완료) 열람
  전부 PASS. 함정 2건 기록: (a) 오래된 dev dist 캐시(`.next-ui-verification`)에서 하이드레이션이 정지해
  스켈레톤만 남는 현상 — 새 dist dir로 교체 시 해소(환경 아티팩트, 공식 E2E 하네스 2/2 PASS로 교차 확인),
  (b) F-03 주문의 `workAreaIds=[wa-0001]`(A구역)과 분석 영역 `wa-0002` 불일치 — UI는 데이터대로 정확히
  표시(합성 리그 정렬 차이, 제품 결함 아님).
- 경계: 합성/검증호스트. 수치(0.18–0.13 s, +0.008 m³)는 이 환경 실측이며 현장/고객 수용이 아니다.

### 2026-10-15 CI 재활성화·첫 실실행 + 로컬 배포 조립 검증(신규)

- **CI 재활성화**: 리포는 public(표준 러너 무료)이었고 Actions가 `enabled:false` 상태였다 — 계정 CLI(gh,
  workflow scope, 리포 소유자 계정)로 활성화하고 **PR #37**로 로컬 main 라인(50 commits)을 검증 라인에 올렸다.
- **첫 실행(run 38692198624)**: external-runtime 이미지 2종(inspector/measurement)과 dashboard job(npm ci·tsc·
  eslint·vitest·next build) **SUCCESS**, `gates`는 **mypy에서 실패** — 로컬이 ruff만 돌려 놓친 실제 오류:
  (a) `tools/task5c_host_enforcement_verify.py` P13 추가분의 `dict[str, Any]` 어노테이션 누락,
  (b) `tests/contract/test_external_inspector_systemd.py`의 의도적 `None` 포인터 인자. 단일 파일 mypy는
  픽스처 import 미해결이 replay 테스트의 None-narrowing 1건을 추가로 숨겼다(`d7f2098`에서 3건 모두 수정,
  전역 mypy 765 files green). **교훈**: CI가 로컬 절차 공백(전역 mypy 미실행)을 실제로 잡았다.
- **재실행(run 38692705171)**: mypy 통과 → full pytest 게이트 진행.
- **로컬 배포 조립 드라이런(신규 증거)**: `deploy/compose.yaml`+`compose.vm.yaml`을 **실빌드 이미지**로 조립
  (project `ksi-deploy-dryrun`; Caddy는 local_certs + 로컬 한정 포트 오버라이드 8180/8543). init-volumes 소유권 →
  MinIO → Core(healthy, `/ready`) → Dashboard → Caddy 기동, **`deploy/bin/smoke-vm.sh` 등가 검사 7종 PASS**
  (app `/api/health` ok · api `/ready` true · objects `/minio/health/ready` 200 · app `/api/auth/providers` ksi-oidc ·
  미인증 api 401 / app 404 · HSTS 헤더) — Caddy 로컬 CA로 **실제 TLS 검증**.
- **발견·수정된 실제 결함 1건**: compose 파일 기반 secret은 컨테이너에서 **plain bind mount**로 나타나 long
  syntax의 uid/gid/mode가 적용되지 않는다 — 대시보드(uid 10001)가 root:root 0400 시크릿을 읽지 못해
  `EACCES '/run/secrets/dashboard-session'`으로 기동 실패했다. 요건(호스트 파일 `chown 10001` + 0400)을
  `deploy/secrets/README.md`에 명문화(`3c819e5`)한 뒤 재기동으로 정상화. OIDC subject registry 로더의
  fail-closed 부팅 검증(principalId 충돌 거부·OCI 아님)도 실측했다.
- **"Terra 호환" 재확인**: 본 제품 문맥의 Terra는 **DJI Terra**(고객 필드PC 측광 소프트웨어)다 — ADR-KSI-037이
  vendor API 통합·비교 API·수출 호환의 '증명'을 명시적으로 금지하고, 실제 호환 표면은 **아티팩트 수용**
  (GeoTIFF DSM/ortho: CRS·transform·nodata·유효 픽셀)이며 실자료(공개 DSM 181MB)·검증호스트 체인·2주기/ortho
  크롭으로 실증됐다. 남는 것은 고객 파이프라인 실데이터(A–E)와 함께 오는 수용뿐이다.

### 2026-10-15 CI 게이트 결과와 타이밍 플레이크 1건 (`a4da2ae`)

- run 38692705171: mypy·Core 이미지 스모크·ruff·정규화 등 **10/11 단계 SUCCESS**, pytest 단계에서
  **6222 passed · 48 skipped · 1 failed**(17분 12초). 실패는 `test_external_analysis_worker_loop.py::`
  `test_run_once_joins_a_timed_out_measurement_renewal_before_the_next_core_call` — 재개 응답을
  의도적으로 **바이트 단위(0.015s/byte)로 스트리밍**하는 테스트라 로컬 실측으로도 호출 1.17s,
  `renew_finished.wait(timeout=1)`이 CI 러너에서 1초를 넘겼다. 상한은 행(hang) 방지용이므로 15초로
  완화(검증 대상 invariant — run_once 후 진행 중 재개 없음·inflight 0 — 불변). 로컬 19 passed.
- 대조: 로컬 `tests/contract tests/replay` = 5789 passed(다른 디렉터리 테스트는 CI가 추가로 수집 —
  CI 전체가 더 넓다). CI는 이 저장소에서 로컬이 놓친 절차 공백(mypy 3건·타이밍 상한)을 실측으로 잡았다.

### 2026-10-15 타이밍 플레이크 최종 정정 (`af812d4`) — 원인은 그레이스가 아니라 스트림 길이

- 1차 완화(상한 1s→15s, `a4da2ae`)는 **불충분**했다: 재실행(run 38694950073)에서도 같은 케이스가
  `wait(timeout=15)` 실패. 실측 결과 가짜 Core가 재개 응답 **전체 1720바이트를 15ms/byte로 스트리밍**
  = 최대 **25.8초** — 로컬에서는 클라이언트 중단 후 EPIPE가 빨라 ~1초에 끝나 통과하지만, CI 러너에서는
  스트림이 15초 한계를 넘겼다(플레이크의 실제 메커니즘).
- 최종 수정: 슬로우 창을 **의도한 만큼만** 유계로 — 첫 64바이트만 15ms 간격(≈0.96초, 클라이언트
  재개 타임아웃 40ms를 넘기기에 충분) 스트리밍하고 나머지는 즉시 기록. 그레이스(15초)는 행 방지용으로
  유지. 로컬 19 passed(13.0s).
- 절차 기록: 호스티드 러너에서만 재현되는 실패는 그레이스 확대가 아니라 **타이밍 구조 자체**(스트림
  길이·클라이언트 타임아웃)를 실측해 고쳐야 한다 — 이번 세션에서 CI가 로컬 대비 3건(mypy 3, 스트림 1)을
  실측으로 드러냈다.

### 2026-10-15 플레이크 최종 근본원인과 재설계 (`d5863a7`) — 단일 CPU 재현으로 확정

- 2차 수정(`af812d4`, 슬로우 창 유계화)도 CI에서 불변 실패 → **`taskset -c 0` + 부하로 로컬 결정적 재현**
  (16.8초 실패 ×3). 계측 결과: 실패 실행은 **측정 단계에 아예 도달하지 않았고**(fake measurement 미진입 →
  느린 재개 자체가 없음 → `renew_finished` 영원히 미설정 → 오해성 타임아웃). 진짜 취약점은
  `max_deadline_seconds=0.3` — 부하 걸린 호스티드 러너에서 **다운로드 단계가 0.3초를 넘기며** 실행 데드라인이
  먼저 소진되었다(클라이언트 타임아웃 0.04초도 같은 부류).
- 재설계: 실행 데드라인 0.3→**10초**(이 테스트가 검증하는 것은 데드라인이 아니라 재개 타임아웃), 클라이언트
  타임아웃 0.04→**1초**(다운로드는 러너 지터 내성, 재개는 1.44초 슬로우 창으로 여전히 타임아웃), 슬로우 창은
  유계(96바이트×15ms) 유지, `elapsed >= 1.0` 단언. **단일 CPU 경합 하 3회 연속 PASS** + 정상 2.6초.
  검증 대상(측정 중 타임아웃된 재개가 조인되고 활성 요청이 남지 않음)은 불변.
- 절차 교훈: 호스티드 전용 실패는 그레이스 확대(1차)·스트림 유계화(2차)로 끝나지 않았다 — **부하 조건을
  로컬에서 결정적으로 재현**(단일 CPU 고정)한 뒤에야 실제 분기(데드라인 소진)를 볼 수 있었고, 수정은
  실패 조건에서 반복 통과로 검증했다.

### 2026-10-15 두 번째 호스티드 플레이크 (`ef89ef4`) — 가짜 오브젝트 서버의 절단 처리를 재시도 가능으로

- run 38700446113(4차)에서 재개 테스트는 통과했고, 다른 부하 민감 케이스가 드러났다:
  `test_external_validation_runner_integration.py::test_runner_drives_actual_core_octet_source_through_real_uds_inspection_and_display[ortho-bytes!-False-True]`
  — 가짜 오브젝트 서버가 **PUT 연결 절단(b"owned upload ended before declared bytes")을 치명 assert로 처리**해
  서버 루프가 종료되고, 레인의 계약된 재시도(응답 드롭 시 재업로드)가 완료되지 못해 turn이 DEFERRED로 남았다.
- 수정: 연결 단위 절단을 `_AbandonedConnection`으로 분리해 `abandoned` 진단 목록에 기록하고 **서버는 남은
  연결 예산을 계속 서빙** — 정상 경로의 진짜 절단은 레인 결과(DEFERRED/미완료)로 그대로 드러난다(검증 대상 불변).
- 로컬 검증: 케이스 3종 통과 + 관련 스위트 29 passed + **단일 CPU 경합 3회 연속 통과** + 전역 mypy 765 green.
- 메모: CI가 처음으로 실제 작동하면서 "호스티드 러너에서만" 재현되는 부하 민감 케이스 2건(재개 타임아웃·업로드
  절단)이 순차적으로 드러났다 — 둘 다 제품 결함이 아니라 **테스트 하네스의 타이밍/장애 모델 결함**이었고,
  수정은 실패 조건을 로컬에서 재현(또는 구조적으로 제거)한 뒤 검증했다.

### 2026-10-15 CI 최종 GREEN (run 38703891076) + main 반영

- **PR 검증 라인 전체 성공**: gates(run 38703891076) = `pytest` **6223 passed · 48 skipped · 0 failed**(17:58)
  + `uv lock --check`·의존성 동기화·production runtime image digest gate·**Core 이미지 빌드+import smoke**·repository
  normalization·ruff·mypy(765) 전부 SUCCESS. dashboard job = tsc·eslint·**vitest 856 passed**·next build SUCCESS.
  external-runtime-images 2종(inspector/measurement) = 실제 빌드 + identity/EOF/`libexpat1 2.8.3-1~deb13u1` 핀 검증 SUCCESS.
- **main 반영**: 로컬 main(55+ 커밋)을 origin/main으로 푸시(956a825..238147f) → GitHub가 PR #37을 merged로 표시,
  **main 푸시 게이트 런 38706805068**이 이어서 실행(해당 런 로그는 후속 NOTED).
- 이로써 "④ CI(GitHub Actions disabled + 결제 실패)" 블로커는 **해소**: 리포가 public이라 표준 러너가 무료였고,
  Actions 활성화(계정 CLI)만으로 실실행이 가능했다. AMD64 에뮬레이션 우회는 CI 네이티브 amd64 빌드로 대체됐다.
- CI가 로컬 절차 공백을 실측으로 드러낸 3건: mypy 3오류(단일-파일 실행이 숨김), 재개 테스트의 0.3초 데드라인
  취약(단일 CPU 재현으로 확정), 가짜 오브젝트 서버의 연결 절단 치명 처리 — 모두 수정 후 이 런에서 green.

### 2026-10-15 운영자 콘솔 주기 완주 + 정합 검증 (라이브 F-03 리그, 합성 범위)

**목표**: "화면 안내만으로 다음 주기 완주"의 잔여 공백(합성 데이터 정합·UI 검토 단계)을 닫는다.

1. **라이브 리그에 OIDC 연결(추가형)**: F-03 Core(8092)를 캡처한 env 그대로 재기동하며
   `KSI_CORE_HUMAN_AUTH_MODE=DUAL` + 로컬 검증 issuer(9041)·registry만 추가(불투명 토큰 경로 불변,
   `/ready`·whoami 재확인). 대시보드는 동일 env에서 `CORE_API_BASE_URL=8092`로 3241에 기동 —
   **읽기 전용 사본(8041)이 아니라 라이브 리그 자체**를 콘솔이 보게 했다.
2. **합성 정합 쌍 등록(불변 기록 미수정)**: 기존 워크오더 전체가 WGS84 A구역(wa-0001)을 참조하는데
   합성 DSM 증거는 wa-0002(200000/550000, EPSG:5186)에 정렬돼 있어 UI 사이클이 성립하지 않았다.
   `register_ui_cycle_pair.py`(기존 리그 스크립트 계열)로 **orders 20/21을 wa-0002에 신규 등록**
   (submission/evidence/checkpoint CSV 포함). 정책 **v24**(신규 subject, 기존 currentness 보존,
   seq78) → VM 실검사 **dsm·ortho 모두 MEASURED** → 컨텍스트 **r28**(v24 바인딩, seq79, 기존 9개 보존)
   → 체크포인트 **VALIDATED ×2**(v24) → **ADMIT_MAPPING**(seq81, mappingDigest efebb88a…). 재-reload
   (seq80)로 검증 발급이 재시도·성공하는 동작(멱등 reconcile)도 실측.
3. **UI 주기 완주(Playwright)**: 로그인(OIDC) → 분석 시작 안내 → 작업구역에서 정합 존 선택 →
   **관측 후보 2건(13:00/14:00 KST = t1/t2)** 선택 → 콘솔에서 **분석 요청** → `analysis-v1-0184cb011…`
   생성(QUEUED) → 분석 워커 1회 실행 → **COMPLETED·EVALUATED·blockers 없음**, 결과
   `report-41f518868fe32802…`(net +0.008 m³) → 콘솔에서 목록·상세 확인(스크린샷 6장:
   `/tmp/opencode/ksi-f03-20261015/shots/`). 검토(ACKNOWLEDGE)는 Core API로 완료 —
   `arv2-e80ecbee…`(receiptDigest 4c0909f0…). **UI 검토 동작 부재는 갭으로 확인되어 UI 구현을
   디자인 담당에 위임**(진행 중).
4. **MCP(Codex) 정합 검증**: ksi-sdata 리그(8061)에서 실제 MCP stdio 세션(initialize→tools/list→
   `ksi_list_spatial_data_assets`) 실행 — 어댑터 6도구 열거·호출 정상(serverInfo ksi-spatial-data-mcp).
   **동일 principal(mcp token)·동일 경로에서 MCP 결과와 REST 결과가 정확히 동일**(둘 다 빈 페이지)
   — 권한 경계도 실측: MCP 클라이언트는 운영자 카탈로그(SPATIAL_DATA_READ 아님·SITES_READ)에서 403
   (설계 경계), 전용 `/spatial-data-assets`에서만 응답. 빈 결과의 원인은 카탈로그가 AI-ready
   (inspectionOutcome MEASURED) 상태가 아님(fail-closed) — 양수 데이터 경로는 검사 레인 재수립이
   선행조건. 리그의 AI egress **활성화 창이 2026-10-15T10:17:46Z에 만료**됨(재프로비저닝 필요).
   참고: 이번 검증을 위해 sdata 리그에 fresh grant(`sdata-parity-proof-1`, ~10-22)를 프로비저닝·
   재기동했다(백업 `rights.json.bak-parity`, 원본 보존).

**의미/한계**: 전부 합성 리그 실측이며 현장·고객 정확도가 아니다. 검토 단계의 UI 화면화가 끝나면
"화면만으로 완주" 주장의 증거가 닫힌다.

### 2026-10-15 Dashboard exact-result human-use review UI — 구현·라이브 확인 (synthetic F-03)

- `apps/dashboard/`에만 구현했다. 완료 결과 선택 시 Core V2의 현재 review target과 review 이력을
  조회하고, 최신 영수증이 결과 revision/digest와 **기준·현재 평가의 ID/revision/digest 모두** 일치할
  때만 `확인됨` 또는 `후속 필요`로 표시한다. 오래된 target은 `미검토`로 처리하면서 이전 review의
  reviewer/time과 expandable audit details는 과거 기록으로 남긴다.
- 결정 입력은 `SITES_WRITE`가 있을 때만 노출한다. 공백을 제외한 필수 의견을 1–1,000 Unicode code
  point로 검증하고, Core가 생성하는 영수증의 digest·comment·target identity와 한계 안내를 표시한다.
  Same-origin POST는 브라우저로부터 decision/comment만 받고, 서버가 매 쓰기 직전에 fresh target을
  조회해 서버 생성 idempotency key로 Core에 전달한다. Core/OpenAPI·권한·계산 계약은 변경하지 않았다.
- 회귀 테스트: 전체 Dashboard Vitest **871 passed / 113 files**, 변경 파일 ESLint, `npx tsc --noEmit`,
  `npm run build` 모두 PASS. 라이브 합성 F-03 (`localhost:3241` → Core `:8092`)에서
  `analysis-v1-0184cb0113a91e014a70edef6a61e44a`의 기존 `arv2-e80ecbee…`를 조회하고, OIDC `local-admin`
  으로 두 번째 `ACKNOWLEDGED` review를 POST해 **201**(`arv2-837140d222994cad…`, receipt digest
  `268dcddd…`) 받았다. 브라우저 request body는 decision/comment만 담고, 응답은 두 evaluation까지 포함한
  exact target을 반환했다. 새로고침 후 local-admin/time/comment가 Core에서 다시 조회되어 유지됨을 확인했다.
- OIDC `local-viewer`에서는 최신 상태를 읽을 수 있지만 radio/comment/submit은 노출되지 않고 담당자 안내만
  표시됐다. 모바일 390px에서 `documentElement.scrollWidth === 390`; 처음 발견한 expandable reviewRef의
  수평 overflow를 `break-all`로 수정하고 재확인했다. Chromium console error 0. desktop/mobile/viewer 캡처:
  `/tmp/opencode/ksi-f03-20261015/shots/analysis-review-*.png`.
- 범위/한계: 리그와 records는 전부 합성 자료이며 고객·정확도·현장/정산 수용 또는 HIL 증거가 아니다.
  Viewer의 Home이 부분 ledger unavailable을 표시했으나 본 분석 열람·검토는 정상 — 이 관련 없는 상태는
  변경하지 않았다. 변경은 미커밋이며 기존 `apps/dashboard/tsconfig.json` 수정과 11개 PNG를 보존했다.

### 2026-10-15 백업/복구 드릴 재실행 (`deploy/bin/smoke-backup-restore.sh`) — 합성 볼륨 범위

- 현재 스크립트 계열(backup-vm.sh → restore-check-vm.sh)을 자기완결 드릴로 재실행: 고유 이름의
  합성 docker volume 2개(저널 샘플·오브젝트 샘플) + 합성 키 매니페스트로 번들 생성 →
  격리 임시 볼륨 복원·검증("journals, objects, and keys.json") → **"synthetic backup/restore smoke
  passed"**. 번들 아카이브 3종(core-data.tgz·objects.tgz·signing-keys.tgz) 복원 성공.
- 한계(문서 정합): `docs/ops/VM_DEPLOYMENT_READINESS.md`의 유보를 그대로 유지한다 — 이 드릴은
  **합성 볼륨 범위의 도구 동작 증거**이며, 실제 운영 호스트의 복구/TLS/UDS/ACL/host 검증이나
  실데이터 복구 보장이 아니다(별도 승인·실호스트 필요).

### 2026-10-15 배포 준비성 결함 수정: 검증 워커가 부트 후 기동 불가 (`2780f8a`)

- **실측 증상**: VM 재부팅 후 `ksi-external-validation-worker.service`가
  `Failed to set up mount namespacing: /run/docker.sock: No such file or directory`(226/NAMESPACE)로
  기동 실패 — rootful 소켓 경로는 tmpfs(`/run`)라 부트마다 사라지는데, 유닛의
  `InaccessiblePaths=/var/run/docker.sock /run/docker.sock …`는 systemd가 **존재하는 경로**를 요구한다.
  그 결과 새 주문(20/21)의 검사·검증이 조용히 큐에 남아 있었다(검사 발급은 되지만 소비자가 없음).
- **수정**: 두 소켓 경로에 `-` 접두(`InaccessiblePaths=-/var/run/docker.sock -/run/docker.sock /run/user`)
  — 존재하면 마스킹, 없으면 무시. 템플릿 `manifest.sha256` 해시와 고정 계약 테스트 핀을 함께 갱신.
- **검증**: VM에서 `/run/docker.sock`를 제거한 **부트 상태 재현** 후 워커 기동 → `active` + 라이브
  Core(:8092) 폴링 실측(큐 소비 재개). VM의 `/etc/systemd/system`·`/usr/share/ksi-external-runtime/systemd`
  사본 동기화. 리포 계약 테스트(`test_host_assets_keep_validator_and_launcher_privileges_separate`) PASS.
- **교훈**: 이번 세션의 배포-실측 결함 2건(compose secret 소유권, 유닛 경로 존재 요구)은 모두
  **실제 기동을 시도해야만** 드러나는 류다 — 정적 검사·단위 테스트로는 잡히지 않는다.

### 2026-10-15 최종 CI GREEN (2건) — UI 검토 + 워커 부트 수정
- run 38720379295(5fe556d, UI 검토 단계): **success** — gates pytest **6223 passed·0 failed**, dashboard
  (tsc·eslint·vitest·build), external-runtime 이미지 2종 전부 SUCCESS.
- run 38721968214(dc71288, 워커 부트 수정+원장): **success** — gates pytest **6223 passed·0 failed**(12:13).
- 이로써 10-15 세션의 모든 내부 작업(운영자 콘솔 주기 완주·검토 UI·정합 쌍·MCP 정합·배포 실측 결함 2건
  수정·백업/복구 드릴)이 호스티드 CI까지 통과했다. 남은 것은 외부 게이트(고객 실자료 A–E·실호스트 배포·
  현장/측량 수용)와 P7-A2/Task3 결정.

### 2026-10-15 세 번째 호스티드 플레이크 + 하드닝 (`16d72a4`), 최종 GREEN
- docs-only 커밋(9eb4555) 런 38724342684에서 `test_external_display_publication.py::`
  `test_actual_core_retries_a_lost_seal_response_with_the_same_declaration`가
  `ProtocolDeadlineExceeded`(전역 wire deadline)로 1건 실패 — 헬퍼의 2초 데드라인이 **launch context의 wire
  예산**이 되어 private put·Core 선언/재시도·seal·모든 currentness 검사를 덮는 구조였다(호스티드 러너가
  중간에 초과). 단일 CPU 재현은 안 됐으나(로컬 충분히 빠름) 실패 서명·메커니즘이 명확해 30초로 완화(경계는
  유지, 주석에 근거 기록). 파일 17 passed + 부하 3연속 PASS.
- **재실행 결과**: 같은 런 재실행 = success(플레이크 확증), 하드닝 커밋(16d72a4) 런 38726675208 =
  **success**(pytest 6223 passed·0 failed, 12:03). main = 16d72a4, 호스티드 CI 전부 GREEN.

### 2026-10-15 백로그 폐쇄: 중복 활성 매핑 모호성 → 승인 단계 거부

- 백로그(2026-09-17) "Two active compatibility mappings for the same pair/zone/policy make the pair
  decision report VOLUME_AUTHORITY_UNAVAILABLE (ambiguity); admission should refuse a duplicate active
  mapping or the decision should name the ambiguity"의 **첫 해법**을 채택했다: 같은 (baseline, current,
  work area, policy) 범위에 두 번째 **활성** 매핑이 들어오면 `admit_mapping`이
  `DuplicateActiveMappingError`로 거부한다(같은 digest 재승인은 기존대로 멱등, **revoke 후 교체 승인**
  수명주기는 유지). 제공자 리로드 경로(`_apply_mapping_actions`)는 이 오류를 특정 사유 메시지로
  변환한다(기존의 모호한 503을 로그에서 진단 가능하게). 결정 시점 코드는 그대로 fail-closed 유지 —
  과거 저널의 모호 상태도 안전하게 남는다.
- 근거: `resolve_for_use`는 정확히 1개의 활성 매핑만 인정(`len(matches) != 1 → None`)하므로 2개 활성
  상태는 어떤 정상 흐름도 만들 수 없는 오류 상태였고, 거부가 그 상태의 발생 자체를 막는다.
- 검증: 계약 테스트 신규 1건(거부 + revoke 후 교체 승인) + 관련 스윕 332 passed(mapping/provider/
  authority) + 전역 mypy·ruff green. 라이브 리그 재기동 후 중복 승인 시도 거부·정상 리로드 무영향은
  후속 확인 항목으로 남긴다(콘솔 검증과의 간섭 회피를 위해 순차 실행).

### 2026-10-15 백로그 2건 완료: Home "검토 대기" 주의 소스 + 중복 매핑 거부 라이브 검증

- **Home 검토 대기 카드**(`c2d470c`): 돌아온 운영자가 완료 분석의 미검토 상태를 Home에서 바로 본다.
  정확 대상 일치 판정은 분석 상세와 공유 모듈(`lib/analysis-review.ts`)로 통일, 현장당 1건(ADR-025
  no-repeat, EXTERNAL_DECISION 다음 우선순위), 조회는 현장 3×분석 5로 유계·fail-soft(카드 하나가
  Home을 깨지 않음), 링크는 분석 상세 직행. `formatNumberKo`는 표시 정밀도에서 0으로 반올림되는
  음수를 `-0` 대신 `0`으로 렌더(백로그 2026-09-17 cosmetic).
  - 게이트: vitest **875**·tsc·eslint·next build PASS(독립 재실행). 전문가 라이브 확인에 더해
    **미검토 완료 분석을 실제로 만들어**(analysis-v1-bd3a5290…, 워커 1회) Home 카드·문구·링크 클릭
    → 분석 상세의 `미검토` 검토 섹션까지 **Playwright 전 항목 PASS**(스크린샷 independent-home-*).
- **중복 활성 매핑 거부 라이브 검증**: 코어를 새 코드로 재기동 후 같은 (pair, zone, policy) 범위의
  두 번째 매핑(다른 만기 창 → 다른 digest)을 ADMIT_MAPPING으로 제출 → 리로드가 **거부**(응답
  `BLOCKED`·sequence null, 매핑 미적용)되고 제공자가 fail-closed로 차단됨(차단 사유는 설계상 고정
  문자열 `RECONCILIATION`; API는 모호한 503 유지 — 보안 자세 그대로). 스냅샷 복원 후 리로드만으로
  **PROVIDER_CONFIGURED·seq 81 복구**, 프리플라이트 OK — 재기동 불필요.
- 남긴 상태: 라이브 리그에 **미검토 완료 분석 1건**을 의도적으로 남겨 운영자가 콘솔에서 실제 검토를
  해볼 수 있게 했다(Home 카드가 그 상태를 가리킨다).

### P7-A2 승인 + Task3 재개 rail — 2026-10-15

- **Human 결정(2026-10-15, 대화 Question)**: P7-A2 제안 **승인** — 게시 포트 없이(`ports: !override []`)
  사설 `internal` 네트워크를 유지한 채, 준비된 Docker 호스트에서 **소유 컨테이너의 사설 브리지 IP**로
  실제 TCP 증거를 만드는 강화된 Task3 시험 기준. 근거 문서: `2026-10-09-isolated-fresh-platform-verification.md`
  (sha256 `fba7776eb022ffb3…`) + 본 원장의 P7-A2 제안 절. 승인 범위 밖 효과 없음(런타임 외부 네트워킹·
  프록시·새 서비스·방화벽 변경 금지).
- **새 bounded rail**: 2026-10-15T14:22Z + 4h (실제 시작) (P7 원안의 4시간 안전 레일과 동일 규칙). 완료 못 하면
  실측 상태·보존 자원·다음 결정을 기록하고 replay하지 않는다.
- 보존 재료 확인: worktree `.worktrees/p7-fresh-verification-20261009`(4a0a08e, clean), scratch
  `p7-fresh-verification-20261009`(freeze/task1/task2 receipts, compose.override, 고립 venv), 후보 이미지
  3건(617c3b95b509/f1d42c1b8153/0dae50617e84), 소유 볼륨 2건(ksi-p7-34cc796826d6_ksi-data/_objects).
  프로젝트 이름 `ksi-p7-34cc796826d6` 유지 → 동일 소유 볼륨 재사용(A2 제안대로).

### P7-A2 실행 완료 — Task3 (게시 포트 없는 호스트→브리지 IP TCP) — 2026-10-15

- 승인 레일 2026-10-15T14:22Z 기준 당일 완주. 스크래치: `p7-fresh-verification-20261009`
  (`compose.a2.override.yaml`, `task3-a2-receipt.json`, `driver-a2-tcp.py`, TCP 영수증 2건,
  `trial-tokens-a2.json`; 만료된 시험 자격은 계획대로 현재 형식·TTL24h로 재생성, 원본은 `.pre-a2`).
- **병합 구성 실증**: 서비스 {init-volumes, core, minio}, 후보 이미지 617c3b95b509(동결), **게시 포트
  없음**(A2), 네트워크 internal, 소유 볼륨 ksi-p7-34cc796826d6_ksi-data/_objects 재사용(프로젝트명 유지).
- **증거(전부 실측)**: ①소유 스토리지 프로브로 버킷 생성·바이트 기록 sha256 `58f23e72…`·readback 일치
  ②Core 부팅 후 **호스트→사설 브리지 IP(172.29.0.3):8000 /ready 200**(게시 포트 없이) ③TCP 인가/테넌트/
  멱등/비노출 단언 **16/16 PASS**(401·whoami·site 201/UNMAPPED·viewer 200·중복 409 DUPLICATE_SITE_ID·
  viewer 403·foreign/nonexistent 404 동일 본문·foreign 목록 제외·/openapi.json 404·취득 라우트 404)
  ④재시작(동일 볼륨/자격/이미지) 후 재생 **15/15 PASS**(동일 신원·중복 409) + 실제 이미지 ID = 동결 후보
  ⑤재시작 후 스토리지 바이트 동일 sha256 ⑥정리: 소유 컨테이너 3건·네트워크만 제거, **볼륨·이미지·영수증
  보존**(down -v·prune 없음). 영수증: `task3-a2-receipt.json`.
- 의미·한계: 합성 시험이며 고객/현장/HIL 아님. "호스트→내부 IP 성공"은 완전한 외부-차단/커널 증명이 아니고
  공개 localhost 포트나 운영 네트워크를 검증한 것도 아니다(A2 제안 문구대로). 제품 Compose/Dockerfile/
  소스/정책 변경 없음 — A2 델타는 스크래치 오버레이에만 존재한다.

### 2026-10-16 degraded-boot 수용 완결 — 전체 팩토리 계약 + 라이브 재검증

- **계약 테스트 3건 신규**(`tests/contract/test_platform_core_production.py`): ①만료 스냅샷 → 팩토리
  전체 부팅+`/ready/external-authority` 503+로그 정확히 1줄+영수증 0 → 동일 키 재발급 스냅샷
  `reload_and_reconcile` → PROVIDER_CONFIGURED·200·영수증 1(무재기동) ②미래 staged 스냅샷(승인된
  카탈로그/워크플로 바인딩 포함) → 동일 경로로 부팅+503+로그 1줄+영수증 0 ③서명 훼손 → 팩토리 부팅
  거부(구조 게이트, cause `signature is invalid`). 게이트 로그 검증은 팩토리가 루트 핸들러를 교체해
  caplog가 볼 수 없으므로 제공자 로거에 직접 핸들러(`_GateLogs`)를 붙였다.
- **라이브 재검증**(복사 F-03 저널, 영수증 head seq 81; `degraded_window_check.py` CHECK0–5):
  staged 관리 액션 포함 미래 스냅샷(10-17) → 부팅·503·로그 1줄·**영수증 바이트 불변**(액션 미적용);
  서명 훼손 → 부팅 거부; `now+90s` 창 스냅샷 → 부팅 차단 후 **창이 열려도 같은 프로세스는 503 유지
  (자동 해제 없음)** — 이는 스펙 §3의 “창 개방 시 런타임 재평가 복구” 문구가 사실과 달랐음을 의미하여
  **정정**했다(복구는 명시적 reload만); 운영자 `POST /v1/operations/external-authority/reload`
  (ADMIN·동일 org) → 200 PROVIDER_CONFIGURED·seq 82·영수증 82; 재기동 멱등(중복 영수증 없음).
- 증거: `/tmp/opencode/ksi-f03-20261015/degraded_window_check.py`, `boot-window-phase*.log`,
  `boot-sig-negative.log`; 스펙 `docs/superpowers/specs/2026-10-15-external-authority-degraded-boot.md`
  §6에 전체 기록.

### 2026-10-16 P7 저장소 읽기 전용 영속성 재확인 + sdata 리그 정상 재구성·실제 Codex 양수 경로

- **P7 읽기 전용 영속성 재확인**(A2 보강): 보존 볼륨 `ksi-p7-34cc796826d6_ksi-objects`를 :ro로 조회해
  객체 원시 파일(xl.meta, 487B) sha256 `d8df8a72…`·mtime 2026-10-15T14:27:55Z가 MinIO 기동 전후 **바이트
  동일**임을 확인하고, **put 없는 get/head 전용 프로브**로 기대 해시 `58f23e72…` 일치(LastModified = 원
  기록 시각)를 실증 — A2 재시작 점검의 put-선행 약점을 폐쇄. 정리: 컨테이너 1·네트워크 제거, 볼륨·이미지
  보존. 영수증 `task3-a2-readonly-persistence.json`.
- **sdata 리그 정상 재구성**(10-15 parity 리그): 만료 3중(provider 스냅샷 seq31 창 종료·승인 material
  6h 창·spatial activation) → ①권위 레코드(카탈로그/정책/컨텍스트 2) 재봉인 + catalog.json 참조 갱신
  (admission digest가 record 참조와 무관함을 단언) ②정책 세대 **v18** 단일 ADMIT_POLICY(새 policy
  authority record 바인딩; v17 엔트리는 옛 digest로 해소 불가 — fail-closed 유지) ③검사 레인 재실행:
  rgb baseline/current(2×2)와 **floreat DSM 실바이트 181MB MEASURED(5150×8808, valid 40,448,677,
  EPSG:7850)** ④activation 재서명·MCP 권한 재바인딩(rev2).
- **실제 Codex 양수 경로**: Codex CLI 0.160.1 + ksi-spatial-data MCP stdio →
  `ksi_list_spatial_data_assets` → **assetCount 1**(`ksa-v1-3367fdc7…`, READ/PREPARE, bounds
  [382282.15,6467491.25,382539.65,6467931.65]) — 동일 principal REST 페이지와 **assetRef/operations/
  bounds/count 4/4 일치**. UI는 :8061로 미재지향(운영자 카탈로그 REST = 대시보드 소스 라우트 200,
  MEASURED 계열 확인) — 대시보드-8061 대조는 주장하지 않는다.
- **발견(제품 결정 후보, 코드 미변경)**: AI 자산 목록의 후보별 예산(`max_retained_policies`·스냅샷
  `max_records`)이 정책 `maxPendingRecords`(8)에 묶여, 한 subject의 보존 레코드/정책 세대가 이를 초과하면
  (여기서는 v18 승격으로 9세대) **페이지 전체가 503 RESOURCE_LIMIT_EXCEEDED** — remediation
  REDUCE_REQUEST는 limit와 무관해 도움 안 됨(8세대이던 직전까지 200). fail-closed는 유지되나 가용성
  결합이므로 10-14의 per-candidate 억제 패턴 확장 여부는 제품 결정으로 남긴다. 리그는 정책 예산
  (maxPendingRecords 8→64·envelope maxQueueDepth 8→128)으로 재료 수준에서 해소(권한 rev2 재바인딩).
- 증거: `/tmp/opencode/ksi-sdata-codex-20261016/evidence/`(SUMMARY·before/after-renewal·mcp-page-positive·
  codex-positive-discovery·parity), 리그 스크립트 `/tmp/opencode/ksi-f03-20261015/`
  (`renew_sdata_rig.py`·`admit_sdata_policy_v18.py`·`renew_sdata_rig_budgets.py`).
- CI: `7b4dd11`(전체 팩토리 degraded-boot 계약 테스트) run 38765206972 success.
- **10-16 추가: 제4 게이트(서명 키 창) 완결** — 스펙 §5-4의 남은 검증 항목 해소. 로더가 창 안 스냅샷의
  키를 `now`로 검증해 키 창이 발급~부팅 사이에 끝나면 **부팅 거부**가 되던 불일치(attach는 EXPIRED
  차단 설계)와, 반대로 키 시작 전 서명(`issuedAt < key.notBefore`)을 **통과시키던 구멍**을 함께 수정:
  키는 항상 **발급 시점**으로 검증(구조 규칙 — 선언된 사실상 불가능한 서명은 시간 게이트가 아님)하고,
  키 창 종료는 부팅 시간 게이트(`out_of_window`)에 포함 → **production 부팅+BLOCKED(EXPIRED)**·reload
  경로는 fatal 유지(키 만료 권위는 reconcile/영수증 금지). 계약 테스트 2건
  (`test_factory_boots_blocked_when_the_signing_key_window_ended`·
  `test_loader_rejects_a_snapshot_signed_before_its_key_window`), 라이브 스크래치
  CHECK1(key-ended 부팅 503·로그 1줄·영수증 불변)·CHECK2(allow_out_of_window=False 거부) 실측.
  증거 `keyended_live_check.py`·`boot-keyended.log`; 스펙 §2/§6과 런북 `docs/ops/DEV_EXTERNAL_RUNBOOK.md` §3a(네 게이트·명시 reload 복구·시작 로그 1줄) 갱신.

### 2026-10-16 후속: AI 목록 예산 분리·사유/복구 안내 (승인된 제품 결정 이행)

- **구현**: ①자산별 보존 이력 조회(검사 기록·정책 세대)의 예산을 대기-작업 노브(`max_pending_records`)에서
  **리스팅 스코프(`max_list_records`)** 로 분리(`source.py` 4개 지점 — 대기 노브는 큐/작업 입장만 지배).
  ②초과는 새 사유 **`RETAINED_HISTORY_LIMIT_EXCEEDED`**(503, remediation **`CONTACT_OPERATOR`**)로 표면화 —
  페이지 전면 `RESOURCE_LIMIT_EXCEEDED`+`REDUCE_REQUEST`(limit와 무관해 무의미)를 대체. ③안전한 거부 유지:
  부분 목록·후보별 조용한 숨김은 후속 설계로 보류(유한 예산·fail-closed 불변). ④계약: 사유 union 가산
  (`spatial_data.py`) + 재생성 스키마 3종(spatial-data/-worker/-ai).
- **검증**: 계약·디스커버리 테스트 2건 신규 — 회귀(pending=1에서도 이력 2세대 리스팅 200) / 초과 시 사유·
  복구 안내(CONTACT_OPERATOR, REDUCE_REQUEST 부재) + 스윕 **385 passed**, mypy 765·ruff green.
- **라이브 실증**: 리그를 **원래 수용 설정**(pending=8·envelope maxQueueDepth=8·정책 digest d6f54928 복귀)으로
  복원 → 9세대 subject에서 MCP 페이지 않았 **200·1건**, 실제 Codex CLI 양수·REST 파리티 4/4. 복원 중 원 digest
  회귀로 legacy rev1이 재유효해 rev3와 `AMBIGUOUS_GRANT` → 파일 경로로 rev1 회수(회수-교체 수명주기, fail-closed
  확인). 증거: `mcp-page-pending-budget-8.json`·`codex-positive-pending-budget-8.{txt,jsonl}`·
  `parity-pending-budget-8.json`(모두 `/tmp/opencode/ksi-sdata-codex-20261016/evidence/`).
- 남은 설계 과제(비승인): 부분 목록 제공 시 누락 사실·페이지 완전성·커서 규칙 설계.

### 2026-10-16 후속: 부분 목록 설계 승인·구현 (Option A: omission flag only)

- **승인**: 부분 목록 설계 3안 중 사용자 선택 — **Option A**(후보별 이력 초과는 조용한 스킵 +
  boolean 불완전 플래그, 카운트·ref 없음; 카탈로그 초과는 전면 503 유지; 커서는 admitted +
  omission 집합에 바인딩). fail-closed·유한 예산·비공개 불변.
- **구현**: ①`SpatialDataAssetPageV1`에 **`page_complete: StrictBool = True`** 가산(별칭
  `pageComplete`) + AI 스키마 재생성(가산만). ②`asset_discovery.py`: `omitted` 추적(grant 있는
  후보의 `RETAINED_HISTORY_LIMIT_EXCEEDED`만; grant 없는 후보는 invisible 유지 — revoked는
  ever-indexed 특성상 tracked 유지) → 일부 projectable이면 **200 + `pageComplete: False`**,
  projectable이 없으면 기존 typed 503 유지(OPERATOR remediation 보존) → 스냅샷이 admitted +
  omitted + complete를 바인딩(구 커서는 409 STALE) → 게이트 경로는 omitted 재투영(해소되면 STALE,
  유지되면 omission 지속; local-only, remote preflight 없음). 상세(`get`/`recheck_view`)는
  typed 거부 그대로. ③MCP 어댑터·대시보드 변경 없음(어댑터는 `SpatialDataAssetPageV1` 자체로
  검증하므로 통과; 대시보드는 catalog 경로만 소비).
- **검증**: 기존 wire pin 1건 갱신(`{"items","nextCursor","pageComplete"}`) + 신규 4건 —
  부분 페이지(200·1건·flag False·wire에 생략 신원/카운트 없음) / omission 변경 시 커서 STALE 409 /
  무grant over-budget는 invisible+complete 200 / 불완전 페이지 egress 게이트 200+ack 통과.
  discovery+AI계약 102 passed, egress/MCP 포함 215 passed, mypy·ruff·format green.
- **검증(확정)**: 공간계열 스윕 **1274 passed/0 failed** + 전체 contract
  **5568 passed·33 skipped·0 failed**(744s) → 커밋 **`717dc2c`** push 완료(origin/main).
- **라이브**: sdata 리그(:8061) 재검증은 OPEN(가동 중 리그는 구 코드 — 재기동이 수용 리그 보존에
  영향을 주므로 계약 증거를 우선하고 라이브 재실증은 별도 승인 후).
- **라이브 실증(10-16 승인 후 수행)**: sdata 리그(:8061)만 동일 데이터 디렉터리·동일 env로
  재기동(신 코드, 저널 보존) → `PROVIDER_CONFIGURED` 유지. REST 페이지 **200·1건** —
  키 `{"items","nextCursor","pageComplete"}`, `pageComplete: true`, 동일 자산
  (`ksa-v1-3367fdc7…`)·READ/PREPARE·bounds 4/4 일치. 상세 **200** 동일. MCP stdio→Core
  parity **PASS**(동일 principal·동일 페이지). Codex CLI LLM 호출은 401(클라우드 인증)로
  차단 — 외부 경계(진짜 차단, 우회 없음); MCP 경로는 stdio 직접 실증으로 대체. F-03 리그(:8092)
  untouched·PROVIDER_CONFIGURED. 증거: `/tmp/opencode/ksi-sdata-codex-20261016/evidence/`
  (`rest-partial-listing.json`·`mcp-parity-partial-listing.txt`; codex stderr에 401 기록).

### 2026-10-17 Human-approved Console UX 맥락·선택·위계 개선

- **승인·문제**: 사용자가 이름 대신 원시 ID가 산문에 노출되는 문제와 전체 화면 사용성을 개선하도록
  승인했고, 단순 문구 정리 후에도 남은 내부 UX 7개 항목을 확인한 뒤 “그렇다면 진행해보자”로
  계속 구현을 승인했다. `b4ca53d`·`581bcee`·`3d66d76`은 표시 정리이며 전체 UX 수용이 아니었다.
  당시 “외부 게이트만 남음”, “미리보기 현상은 앱 결함 아님”은 과장·원인 미확정으로 정정한다.
- **범위·불변식**: Dashboard의 실제 Site/WorkArea/작업명, genuine cycleNumber, 촬영 구간과 제출
  revision을 연결한다(SDP-REQ-01/02/04/05/06/07). INV-051/053/060/061을 보존: 이름은 표시일 뿐
  권한·계보·적합성·정확도를 만들지 않으며 서버 인가 범위의 기존 GET만 사용한다. Core/schema,
  계산, 원본, 외부 AI 동의, 장비·재구성 책임, native-grid 크롭 의미는 변경하지 않는다.
- **구현**: Home의 bounded 검토 대상에 보관 구역까지 현장별 이름을 연결; 작업 목록/상세·업무함에
  실제 대상 맥락과 on-demand 기술 참조; 받은 업무의 필터/페이지마다 bounded BFF 이름 보강;
  분석 선택·기준/현재 확인에서 작업명+촬영 구간+revision과 충돌 시 exact selector 구분;
  공간 자산의 파일/작업/구역/시점, 요청의 시각/원본 구분과 읽을 수 있는 기술 disclosure;
  generic 404를 미설정/빈 목록으로 추정하지 않고 수동 재조회 유지. 현장 헤더의 reportedAt는
  촬영 시각이 아닌 **외부 결과 보고**로 표시. 같은 이름의 Site는 실제 등록 시각/기술 참조 제공.
- **검증 상태(첫 통합 빌드)**: Dashboard 945/945, TypeScript, lint 0 errors(기존 역사 캡처 JS 경고
  1건), production standalone build 통과. 기존 Console E2E 4폭(390/768/1024/1440) 51 passed/
  5 intentional skipped, 기존 golden 수정 없음. F-03 실제 합성 리그에서 8경로×desktop/mobile
  16렌더에 가로 넘침·남은 busy·serious/critical axe 0. 홈→정확한 분석 상세 이동, t1/t2 선택·
  selector 공개, 자산 상세 이동을 실제 브라우저에서 확인(새 분석·검토 POST 없음).
- **렌더 후 보완·최종 확인 완료**: unique 작업 행의 불필요한 기술 줄, 기존 제출이 있는 작업의
  빈 신규 등록 폼 우선 노출, 긴 업무함 이름의 Site 잘림, 모바일 요청 상태의 후순위 노출을 관찰해
  같은 구현 단위에서 보완했다. 신규 등록은 비어 있는 작업·진행/재시도 중일 때 계속 펼치고,
  기존 제출이 있고 입력이 없는 경우에만 접는다. native disclosure를 키보드로 열어 등록 폼과
  작업 운영 정보에 실제로 도달했다(`task-disclosures-final.log`). 최종 모바일 업무함에서 버튼이
  본문을 좁히는 추가 결함을 발견해 **모바일 세로 배치**로 수정: 실제 본문 폭 324px, 버튼 top이
  본문 bottom 아래임을 측정하고 원본 PNG를 직접 확인했다(`inbox-final.log`, `simulated-inbox-mobile.png`).
- **최종 수용 범위**: 이번에 합의한 7개 내부 UX 영역의 구현과 관련 로컬 기능/렌더 확인을 마쳤다.
  전체 제품·고객 수용을 닫지 않는다. 최종 Dashboard **954/954 (124 files)**·TypeScript·build
  PASS, lint 0 errors(기존 경고 1 유지). 4폭 E2E 재실행 **51 passed/5 intentional skipped**;
  그 후 유일한 UI 변경인 업무함 모바일 배치는 해당 390px populated/긴 이름/페이지 상태에서
  직접 재검증했다(기존 무영향 증거 재사용). 최종 실행은 `.next-ux-verified` standalone, F-03
  Core :8092·OIDC :9041·Dashboard http://localhost:3241. 자동 생성 tsconfig 추가분만 제거해
  `3d66d76`의 원본 설정을 보존했다(`.next-ui-verification` 기존 항목은 불변).
  최종 source 해시는 `final-source-sha256.txt`, 이전 렌더 후 실패/보완도 증거 디렉터리에 보존한다.
  커밋 후 텍스트 검토성을 위해 이름 충돌 key의 literal NUL 1바이트를 `\u0000` 표기로 정규화했다.
  TypeScript AST 종류·식별자·literal 값이 동일함을 비교했고(`source-normalization.json`),
  954 테스트·TypeScript·해당 파일 lint를 다시 통과했다. UI 동작 델타가 없어 렌더 증거는 재사용한다.
- **증거·한계**: `/tmp/opencode/ksi-ux-context-20261017/`의 로그·스크립트·PNG.
  Native DOM 조회는 가능했지만 click UnknownVizError 및 focus 후 screenshot visibility failure;
  task-scoped Playwright로 기능/렌더 검증. 요청 populated/접근 회수 상태는 read-only loopback
  GET fixture, 긴 업무함/페이지 및 404 복구는 브라우저 GET fixture로 명시한 **합성 UI 상태**이며
  실제 Core 요청/출력/권한 수용으로 주장하지 않는다. fixture는 Core 쓰기·다운로드 없이 종료하고
  Dashboard를 F-03 Core(:8092)로 복귀했다. 고객 A–E·Terra·현장 정량/고객 수용·운영 배포는 별도.

### 2026-10-17 후속 — 독립 병렬 UI/UX 종합 검수 (분석/보고, 코드 수정 없음)

- **Human 요청**: 전반 UI/UX·실사용 흐름·화면 설계·불필요한 텍스트/요소를 최대한 독립 병렬 검수.
  사용자 후속 피드백은 텍스트 중심 Site 상세의 인지 부담과 시각적 공간 확인 부족이었다.
- **방법**: 현재 UI 소스 `c9d5629`와 같은 실행 환경에서 독립 A(디자인), B(기술/detector),
  C(task-pilot)를 병렬 수행하고 primary가 재현/원본/코드 대조. 최초 ux-scout는 실행 접근 제한으로
  과거 캡처만 읽어 현행 판정에서 제외하고, 별도 General로 A를 재수행했다. UI Pilot 전용 연결은
  없었으며 AI 브라우저 검수를 실제 사람/해당 도구의 검수로 가장하지 않았다.
- **검수 결과**: 통합 우선사항 **P1 4 / P2 7**, P0 미확정. 특히 `#site-aoi`의 실제 목적지 부재,
  EPSG:5186 구역 대체 미리보기를 WGS84로 읽는 클라이언트 결함, compact AOI 편집 경계 불일치,
  구역 등록을 계획 대비 진척 계산으로 설명하는 잘못된 의미를 확인했다. 시각 확인/결과 IA/목록 상태/
  선택 피드백/가용성·복구/선택값 공간/제목 구조는 후속 UX 개선 영역이다. **전체 UX 수용은 OPEN**.
- **검수 오탐도 정정**: 실제 다른 분석 선택은 URL을 갱신하며, fine pointer 38px 버튼은 채택 표준
  36px를 충족한다. 외부 이력 빈 화면에 분석 링크가 이미 있고, selector 기술 정보는 기본 닫힘이다.
  이미지 없음 placeholder와 기술 ID 자체는 확정 결함으로 취급하지 않았다.
- **범위**: B 18경로·20 responsive cells, 표본 axe serious/critical 0·가로 넘침0·대비·Tab/touch tap;
  C 첫 자료 폼/기존 작업 찾기/두 시점 분석·근거/모바일 인계; primary 실제 열람자 역할과 추가
  geometry/라우팅/역전시점/compact 확인. 요청 저장/업로드/계산/검토·승인 등 제품 데이터 변경은 하지 않음.
- **결론·한계**: 기술 기본기 개선이 업무 사용성 완료를 뜻하지 않는다. 실제 고객/실폰/SR/WAN·대용량/
  격리 쓰기 종단 수용은 미검증. 이번 요청은 검수 결과·수정 우선순위를 제시하며, 이 항목 자체가
  코드 수정·계약 변경·새 지도/미리보기 기능 구현·제품 전체 완료를 뜻하지 않는다.
- **정본 보고**: `docs/audit/CONSOLE_UI_UX_INDEPENDENT_AUDIT_2026-10-17.md`.
  원본 보고/스크립트/JSON/PNG는 `/tmp/opencode/ksi-ux-audit-20261017/`에 보존. 기존 데이터·포트·
  원본 자료·이전 미추적 PNG는 보존하고 검수용 브라우저는 소유 세션만 닫는다.

### 2026-10-17 후속 — Human 승인 U01–U11 개선 구현·로컬 수용

- **승인·소유**: Human "그래 개선 순서대로 해봐"에 따라 같은 감사의 U01–U11을 순서대로
  구현했다. Design Architect가 통합/실제 렌더 수용을 소유하고 General에 좌표/구역,
  Site 작업공간, 분석/복구 단위를 직접 위임했다. 새로운 제품 원장이나 승인 게이트는 만들지 않았다.
- **요구/경계**: SDP-REQ-01/02/04/05/06/07, INV-020/051/053/060/061. Dashboard만 변경.
  Core/API/schema/RBAC/계산/멱등성/보류 selector·원본·파생물/native-grid 크롭/AI 반출 동의는 불변.
  기존 proj4 정의·Leaflet·UI 토큰/라이선스만 재사용, 새 의존성·외부 영상 없음. HIL 불필요.
  롤백은 본 UI 변경 커밋과 goldens를 함께 되돌리는 방식; 기존 standalone 빌드도 보존했다.
- **U01–04**: 전체 Site AOI 없는 상태에서도 현재 등록 폼으로 연결; 기존 작업이 있는 UNMAPPED
  현장을 Home 초기 설정으로 재분류하지 않음. 선택적 AOI는 실제 작업 탭/anchor로 연결.
  알려진 CRS만 화면용 WGS84 변환; 미지원/구멍/비정상/과다/퇴화 기하는 추정하지 않음.
  대체 등록은 새 WGS84 범위+supersedes이며 이전 구역/CRS/계보는 불변. compact AOI/작업구역
  변경은 노트북 안내, 읽기 미리보기는 유지. 구역 설정이 계획 대비 진척을 증명한다는 문구 제거.
- **U05–07**: Site 기본 화면에 선택 구역의 실제 경계·인가된 검사 footprint·축/단위/축척과
  촬영 시점·자료 선택을 배치. 기본 구역은 실제 작업 결속→분석 결속→등록 시각 순;
  query가 우선하며 조회 범위 밖 명시 대상은 대체 표시 이유를 알린다. 선택 파일과
  표시 범위/촬영 구간/metadata deep link가 일치, 키보드·GET 선택·뒤로가기 확인.
  파일/구역 이름 충돌에만 실제 full identity로 구분. 작은 구역은 원본 좌표 평면을 우선하고
  배경지도는 별도 펼침. 큰 위성사진/정사영상으로 가장하지 않는다. 작업 승인만 보고 미제출을
  단정하던 목록 표현 제거; Core 분석과 외부 비교 이력은 별개 기록임을 명확화했다.
- **U08–11**: 명시 기준 선택을 현재 변경 시 보존, 구역 변경/미선택/시간 역전/겹침을 구체 안내;
  known-bad 새 조합은 버튼과 submit 양쪽에서 POST/새 key 생성 전 차단. 보류 요청 재시도는
  원래 key/selector 유지. 넓은 선택 공간과 전체 선택 확인 유지. 기존 분석/근거를 먼저 보여 주고
  새 폼은 직접 anchor로 이동; 미완료 시도 안내 유지. 등록 진입은 실제 capability/mode와 일치,
  Team 401/403/404/5xx의 안내/수동 복구와 복귀 제공; 중복 H1·상세 오류 문구의 대비 보완.
- **렌더 후 교정**: 첫 빌드 26렌더에서 촬영 시점이 긴 aside 아래로 묻히고 새 분석 폼이 결과보다
  먼저 노출되는 문제를 확인, 단일 구조 보정으로 해결. 실제 20cm 합성 구역의 수정 벡터가 CRS는
  맞아도 zoom18에서 폭0px로 남아 vector zoom26/배경 native zoom19 상한을 적용, 108×108px로
  표시되며 포인터 편집도 확인했다. 이는 표시 확대이지 원본 영상 해상도/계산의 변경이 아니다.
  마지막 혼합 조회 실패/좌표계 불일치 상태에서 두 문구가 부재/overlay를 과장해, 별도 기능 회귀로
  조건 분기를 수정하고 그 두 상태만 재검증했다(추가 시각 취향 수정 없음).
- **검증**: 최종 Dashboard **1045/1045 (133 files)**, TypeScript, 최종 standalone build 통과;
  ESLint 0 errors/기존 역사 캡처 JS warning1. Console E2E 4폭 **51 passed/5 intentional skipped**.
  Home golden은 승인된 큰 캐러셀/구조를 유지한 채 기존 작업 현장의 잘못된 초기 설정 제거와
  capability 진입을 반영; 4폭 원본/실제 이미지를 직접 대조 후 교체, 비교 임계값을 늘리지 않음.
  기존 default-Site 회귀는 실제 공간 선택·geometry로 대체, 권한 없는 등록 링크를 기대하던 회귀는
  기존 정본 capability 판정과 일치하도록 강화. 원본 이미지는 Git과 증거 goldens-before에 보존.
- **현재 증거**: 최종 구조 26 live 렌더 + empty/unknown/catalog-denied/unsupported 8 합성 상태에서
  가로 넘침·남은 busy·JS errors·serious/critical axe 0. 마지막 두 문구 분기의 영향 상태 4렌더를
  추가 확인하고, 바뀌지 않은 나머지 UI/E2E 증거는 재사용했다. 실제 역할 열람자, 키보드 자료 선택,
  뒤로가기, GET 구역 선택, client-only 도형 편집, synthesized-touch 44px 표본 확인. 실제 새 분석·
  업로드·검토·보관·구역 등록 저장은 실행하지 않음; 그런 Core 계약의 이전 검증을 새로 승격하지 않는다.
- **증거·환경**: `/tmp/opencode/ksi-ux-improve-20261017/` README, round1, render-checks,
  interactions/final-flow, states/state-guard, build/test/lint/E2E logs, PNG, source hashes.
  현재 http://localhost:3241 → `.next-ux-spatial` standalone → 직접 F-03 Core :8092/OIDC :9041.
  GET simulation proxy :8078 종료, use-fixture 제거. 소유 브라우저만 종료, 기존 미추적 PNG 보존.
- **완료 범위·남은 경계**: 승인 U01–U11의 내부 UI 개선 단위는 로컬 수용. 실고객 자료·Terra/정량·
  실제 사람/실폰/SR/WAN·대용량·운영 배포 수용은 별도 미검증/외부 경계다. 카탈로그는 여전히
  metadata-only이며 실제 정사영상 사진/전후 영상 비교를 새로 제공하지 않는다. 표시용 footprint는
  같은 CRS 단순 링만 겹친다; 미지원/불일치는 범위/단위 미확인 상태와 원본 metadata로 남긴다.

### 2026-10-18 — 실무 언어·자료 인식 후속 (Human 요청, 구현 중)

사용자는 F03·revision1 같은 표시가 코드처럼 보여 의미를 모르겠다고 피드백하고 전체 실무 사용성
개선을 요청했다. 앞선 U01–U11 수용은 이 후속 언어 문제까지 해결했다는 뜻이 아니었다.

```text
Requirement IDs: SDP-REQ-01/02/04/05/06/07; 이번 task의 사업무맥락/선택식별/원문보존/상태구분 검증
Owner module: apps/dashboard (primary Architect integration; data/analysis and work/registration General units)
Acceptance criteria: 자료 종류·촬영 시점·현재 상태·다음 행동을 코드 해석 없이 파악; 전체 파일명·등록 버전·정확한 selector를 찾을 수 있음; 충돌/결측/긴 이름·모바일·권한·보류 재시도 회귀 보존
Contracts affected: 없음. INV-020/051/053/060/061, 계산/원본/기하/멱등성/AI 동의/정확도 의미 보존
Reference assets: d2f5871 실제 Site/analysis/asset/task/inbox/queue 캡처, 현재 Native Review, 기존 토큰·컴포넌트
Adoption decisions: 종류+실제 촬영시점 우선; revision은 등록 버전(회차 아님); 파일명/ID/확인값은 상황별 상세; 등록·업로드·검사·분석 조건·사람 검토를 합치지 않음
Files to change: human-labels/operator-language; Site workspace/header/scope/workarea/home; asset/request/analysis; work detail/registration/inspection and tests
Tests: focused + full Dashboard unit/type/build/lint, 실제 desktop/mobile 흐름·collision/unknown/permission/input/disclosure 검증, 기존 E2E 보존
HIL or real-device assumptions: 없음; 합성 local rig와 Native/Playwright 증거를 고객/물리장비 수용으로 승격하지 않음
License/data implications: 기존 코드/스타일/자료만 재사용; 새 자산·외부 서비스·Core 데이터 변경 없음
Rollback: 후속 UI 커밋을 되돌림; 기존 d2f5871 빌드와 합성 원장/원본 보존
```

F03 이름들은 실제 synthetic 원장의 name 값이며 Site/WorkArea의 개명 API가 없다. 원장을
고치거나 regex로 이름을 지우지 않는다. 실무용 UI 표현과 자료 자체의 등록명을 구분하고,
파일명/버전/기술 식별자가 주 작업 언어를 대신하지 않게 한다. 새 가짜 현장명·동의·정확도는 만들지 않는다.

#### 2026-10-18 최종 수용 — 실무 언어 후속 완료 (local software/UI 범위)

- Site·등록 자료 목록/상세는 종류 + 실제 촬영 구간(연도 포함)으로 찾는다. 촬영 시점과 신고/등록/계산/결과 생성 시각을 섞지 않는다. 동일 표시가 겹칠 때만 초→등록 버전→전체 원문 식별자로 구분하며 목록/선택값을 병합하지 않는다. 원본 파일명·불변 ID·확인값·좌표/격자/제출자 입력/저장 파일 사실은 닫힌 `파일 정보`/`처리 상세`에서 확인할 수 있다.
- revision은 제출의 `등록 버전`, 구역은 `구역 버전`, 결과는 `결과 버전`, 평가는 `평가 버전`으로 구분했다. 등록 버전을 촬영/업무 회차로 바꾸지 않았다. 파일 제출 완료·파일 검사·분석 사용 조건·사람의 검토를 별개로 유지한다. 정확도/측량·정산 승인 의미는 승격하지 않는다.
- Home은 해야 할 일, 외부 작업 상세는 `관측 자료와 검사 확인`을 제목으로 삼고 실제 작업명을 `등록된 작업명`으로 보존했다. Site의 저장명/F03 값 자체는 그대로다. 메뉴는 `자료·시점`/`변화 분석`/`등록 자료`/`관측 작업`/`외부 비교 기록`; 준비 요청은 `구역 자료 준비`로 맞췄다. 현재 인가된 현장에 한해 검색·이동에서 자료/분석 목적지를 찾을 수 있으며 원문 ID 검색은 숨겨진 검색어로 유지한다.
- 마지막 원본/실제 렌더 비교에서 evidence 대상 단추의 React key가 사용자에게 보이는 구분을 대신할 수 없음을 발견했다. 서로 다른 제출 참조가 같은 버전/종류/파일명을 가질 때만 전체 참조를 단추에 추가했고, 파일명이 실제 다음 줄에 오도록 flex 방향을 수정했다. 5개 순수 충돌 테스트 + 1개 컴포넌트 회귀를 추가했다.
- 최종 Dashboard **136파일 1069/1069**, **TypeScript/standalone build 통과**, **ESLint 0 errors / 기존 warning 1**. 최종 Console E2E **51 passed / 5 intentional skips** (390/768/1024/1440). 문구 변경으로 깨진 문자열 기대값은 이름 원문·href·disabled·재시도/멱등성·선택 보존·0 POST 등 의미 검증을 보존하며 갱신했고, 허용 오차나 golden은 바꾸지 않았다.
- 실제 direct F03 합성 rig **30개 viewport cell**과 마지막 영향 범위 **작업 상세 2개 cell**을 캡처/직접 읽었다. Site/catalog 자료 선택, 키보드 Enter 상세 펼침, 검색 `사진`→등록 자료→구역 선택→정확한 파일, 선택 URL/back, 역순 비교 비활성화/프로그램 submit 0 POST 및 정상 쌍 활성화를 실제 입력으로 확인했다. 관련 overflow/busy/페이지 오류/serious-critical axe 없음. 마지막 field-only 수정 외 경로는 변경되지 않은 유효 증거를 재사용했다. 실제 등록/업로드/seal/분석 생성/검토/보관/기하 저장은 보내지 않았다.
- 증거: `/tmp/opencode/ksi-operator-language-20261018/` README·source-hashes·unit/types/build/lint·`e2e-accepted.log`·render-checks/interactions/field-confirm·PNG. 이전 Site `/tmp/opencode/ksi-ux-improve-20261017/site-final-live.png` 및 기존 asset 상세와 비교했다. Native는 HTTP200/스크립트 fetch 뒤 DOM이 loading shell에 머물고 visible-tab screenshot이 실패해 실제 full-screen 수용 증거로 쓰지 않았다. Playwright headless 실제 앱 렌더/입력이 근거이며, 이를 사람 연구나 물리 장비 증거로 표현하지 않는다.
- 현재 review는 detached `.next-operator-language` at `http://localhost:3241/sites/f03-flow-site?workAreaId=wa-f03-flow-site-0002`, direct Core8092/OIDC9041. 기존 `.next-ux-spatial` rollback 빌드 및 사용자 untracked PNG/.playwright-cli 보존. 새 공용 노출/영구 서비스/라이선스 자산/의존성/DB 쓰기 없음. Next가 추가한 선택 dist의 generated type include만 config에 반영했다.
- 범위 제한: direct F03 rig의 자료 준비 API는 현재 조회 불가라 준비 완료/receipt/download 성공 경로의 최신 live 전달은 미검증(SSR/logic 회귀 통과). 고객 Terra 원본/다중 시점 field/survey/정량·고객 수용, human study·실제 touch/SR/WAN, production host/TLS/IdP 및 기존 LLM401 외부 경계는 그대로다. 본 완료는 후속 UI 단위의 local 수용이며 플랫폼 전체/외부 경계 완료가 아니다. 현재 승인된 후속 UI 작업 중 남은 actionable 항목은 없다.

### 2026-10-18 — 실무형 합성 시연·자료 등록→비교→검토 흐름 (Human bounded 과제 local 검증 완료)

앞선 실무 언어 후속(1cbfef8a) 뒤 Human이 다음 계획을 묻고, 기존 F03 보존/별도 합성 시연 자료/
등록→시점 선택→두 시점 비교→결과 확인·검토의 업무 흐름 개선/최종 viewport·역할 검증 제안에
"그래해봐"로 승인했다. 이는 앞선 언어 단위의 미완료 재분류가 아닌 새 bounded UI·local demo 과제다.

```text
Requirement IDs: SDP-REQ-01/02/04/05/06/07, REQ-INT-101..104/REQ-OPS-102; INV-020/024/051/053/060/061
Owner module: apps/dashboard task journey + scripts local synthetic rehearsal (Core/measurement runtime는 기존 계약만 사용)
Acceptance criteria: 원장/고객 데이터 변경 없이 명확히 합성인 새 시연 현장과 두 촬영 시점; 실제 등록·검사·분석·사람 검토 경로; 현장/구역/현재 자료 맥락이 인가된 목록 검증 후 연결돼 반복 선택 최소화; 없는 준비·정확도를 주장하지 않음; 오류/재시도/권한/compact/read-only 보존; rendered desktop/mobile/operator/reviewer 확인
Contracts affected: wire/schema/calculation/authorization 변경 없음. Query는 표시 의도일 뿐이며 인가된 Core 응답에 존재하는 항목만 선택; frozen attempt와 명시 선택 우선. 합성 정책/bytes/계보는 격리된 test runtime에서만 사용
Reference assets: 1cbfef8a 실제 Site/등록/작업/분석 캡처와 현 소스, 기존 API/inspector/analysis integration tests·local rehearsal scripts
Adoption decisions: 기존 시각체계·컴포넌트·필수 work association 유지; 직접 구역 연결/명확한 다음 행동 우선; 중복 선택 카드 제거 후보; 범위 잃음과 일반 업로드 후 변화 분석 진입 부재를 실제 흐름에서 검증·수정
Files to change: scope/registration/field/analysis/catalog UI + tests; 새 scripts/rehearse_operator_journey.py + focused tests; 명시적 local-only synthetic notice + layout/tests; 기존 ledger/checkpoint
Tests: focused UI/helper/script tests; 실제 격리 Core HTTP 등록→봉인→parser→analysis→review; F03 hash 보존; Dashboard unit/type/build/lint/E2E; 실제 viewport와 keyboard/pointer/역할 확인
HIL or real-device assumptions: 없음. 합성 소프트웨어 시연이며 DJI Terra/고객 호환·현장 정확도·물리 기기 검증 아님
License/data implications: 기존 의존성/KSI 코드 + 새 합성 bytes, 새 외부 서비스/고객 자료/동의/AI 반출 없음; loopback 임시 Core8096, 기존 F03/IdP는 보존
Rollback: 후속 UI commit revert; review를 기존 1cbfef8a/8092로 복귀; 새 own8096만 중지(기존 원장/서버는 그대로)
```

관찰된 구체 문제: Site의 선택 구역이 등록/새 분석으로 전달되지 않고, 일반 외부 작업의 제출 후
V2 변화 분석 링크가 없으며 planning binding 때만 나타난다. 등록 시작 화면은 기본값이 유일한
방식인데 선택 카드와 form 제목을 중복한다. 반면 파일 폼은 이미 빈 목록에서 펼치고 유지된
등록이 있으면 접는 정상 패턴이므로 보존한다. 가설은 실제 새 시연 환경에서 재검증한다.

**완료 범위와 결과**

- 기존 F03 원장을 이름만 바꾸거나 alias하지 않았다. 새 `syn-demo-site-01` **시연 · 토공 현장**,
  **북측 절토구역**(0001)·**남측 성토구역**(0003), 실제 생성한 32×32m DSM/정사영상과
  **2026-10-05 / 10-12 촬영 시점**을 격리 Core8096/새 object bucket에 구성했다. source/derived,
  CRS·수직 기준·capture interval·불확실성·actor 계약을 그대로 썼다. 상시 local banner/생산자 선언이
  합성 시연임을 알리며, 실제 현장·Terra 호환·정확도·정산 승인 근거로 쓰지 않는다.
- 선택 구역을 등록·분석의 인가된 실제 목록과 대조해 전달한다. 중복·외부·보관 query는 일반 안내로
  복구하고, repeat template·기존 analysis deep link·frozen pending attempt·실제 사용자 선택을 덮지
  않는다. identity/name 길이 계약을 혼동하지 않으며, 같은 이름의 다른 구역을 합치지 않는다.
  Site 상단 분석/등록 자료 메뉴는 실제 화면으로 바로 연결한다. 등록 화면은 한 목적의 필수 이름·
  구역 form→실제 파일 폼 anchor로 연결되고, 취소·돌아가기에도 구역을 유지한다. 여러 구역 연결은
  기존 API대로 가능하되 단일 구역 catalog의 범위 제한을 조건부로 알린다.
- 제출이 존재할 때만 다음 자료 목록·변화 분석 행동을 안내한다. 목록 조회 실패를 0건으로
  오인하지 않으며, seal 응답이 확인되면 server stage/continuation만 새로 읽고 client 입력·동결
  재시도는 유지한다. 완료된 제출은 버튼을 잠그고 명시적 새 등록으로만 다음 시도를 시작한다.
  미리 준비된 metadata 후보 표시와 실제 검사·분석 admission은 구분한다.
- 실사용 과정의 한글 파일명 Core422를 확인했다. 기존 ASCII basename 계약(1–255자)을 넓히거나
  원본을 자동 개명하지 않고 선택 시점에 사유와 원본 보존/복사본 선택을 안내한다. 미해결 거절을
  파일 슬롯별로 유지해 다른 파일 재선택이 예전 파일을 조용히 제출하지 못하게 한다. 기존 등록
  참조의 hash/size 대조 이어하기, 불명확 응답의 같은 identity 재시도, 422의 명시적 새 시도는 보존했다.
- 조회 전용·compact·보관 구역에서 없는 mutation form으로 안내하지 않으며, 기존 시각체계와
  결과 우선 구조를 유지했다. 공간 작업공간이 행동을 소유할 때 하단 시작 안내는 건수만 표시한다.

**실제 업무/권한 검증**

- 새 격리 fixture에서 실제 HTTP 등록→grants→object PUT→봉인, 실제 parser inspection MEASURED,
  기존 서명·digest·정확한 sealed-subject 정책 admission, 실제 V2 worker 계산·사람 review를 확인했다.
  정책은 격리 harness의 **정상 서명 정책**이며 `syntheticTestOnly` escape flag를 이용하지 않았다.
  provider가 그 flag를 거절한다는 이유로 production code/검사/승인 경계를 약화하지 않았다.
- 실제 OIDC FIELD_OPERATOR UI에서 새 분석 `analysis-v1-b3f4047f3562e882b06529d35f2224ed` 생성,
  worker COMPLETED, 절토128/성토0/순변화−128m³, uncertainty=null,
  `PROVISIONAL_ACCURACY_UNVERIFIED` 확인. 실제 emulated-mobile Admin UI ACK review를 제출하고
  새로고침 후 exactly1개·reviewer `local-admin` 지속을 확인했다. 이는 확인 기록이지 기업 승인 아님.
- 실제 UI로 남측 work4와 work5를 만들고 각각 registration201/grants200/실제 2 PUT200/seal200을
  확인했다. 새 subject는 **INSPECTION_PENDING_POLICY**로 관리자 검사 설정 확인을 요청한다.
  자동 정책 승인이나 준비 완료를 꾸미지 않았다. work5는 잘못된 파일명 zero POST, 두 슬롯 모두
  해소 전 제출 차단, 확인된 seal 후 재클릭 zero POST, 새로고침 없이 다음 행동 갱신을 추가 확인했다.
  준비된 북측 두 시점의 분석 성공과 신규 남측 자료의 정책 대기를 서로 다른 상태로 검증했다.
- 실제 issuer 계정 admin/operator/viewer에 같은 org-a와 정확한 area scope를 확인했다. 첫 browser
  검증이 fixture registry의 placeholder WorkArea ID를 발견해 **새8096 설정만** 실제 ID로 고쳤다.
  Site 이름만 보이는 것을 데이터 통합 성공으로 취급하지 않았으며, 기존9041/다른 원장은 변경하지 않았다.
- 키보드 자료 선택/URL/back, 구역→등록→취소에서 반복 선택0, 직접 header 분석 이동,
  외부 구역 query 원문·존재 누출 없음, VIEWER create/review 없음, 390px laptop gate와 20개
  emulated-touch 44px 표본 확인. 네 폭의 최종18 route cells에서 overflow/잔여 busy/JS error 및
  serious-critical axe 위반0. actual image를 직접 읽어 baseline 대비 판단했다.

**회귀·환경·잔여 경계**

- Dashboard **1142/1142, 143 files**, TypeScript/standalone build 통과, ESLint0errors/기존warning1.
  4폭 Console E2E **51 passed/5 intentional compact skips**; golden/tolerance 변경 없음.
  새 seed Python **31/31 + ruff** 통과. raster 테스트는 자체 생성 bytes를 사용해 개인 `/tmp` receipt
  의존을 제거했다. seed는 loopback8096만 허용하고 이름 기준 archive를 하지 않는다.
- 실제 UI 분석/review 뒤 screenshot 전용 locator와 metadata 후보에 대한 테스트 가정이 각각
  실패했으나, 저장된 정확한 ID로 **read-only recovery**하여 중복 생성·업로드·review 없이 검증했다.
  Native는 명시적 focus 뒤에도 visible-tab screenshot이 실패했다. 실제 렌더/입력 증거는 headless
  Playwright이며, Native·사람 연구·물리 touch·screen reader 검증을 주장하지 않는다.
- 증거 `/tmp/opencode/ksi-practical-journey-20261018/ui/`: README, baseline/round1-readonly,
  failed-oidc-scope(실패 증거), **verified-render**, roles-keyboard, analysis-review/recover-review,
  registration-upload/recover-upload, **final-upload**, filename-render, unit/types/build/lint/E2E logs.
  `receipts/f03-final-preservation.json`으로 실제 후속 writes 이후에도 기존 F03 15/15 원장 hash 동일.
- 현재 review `http://localhost:3241/sites/syn-demo-site-01?workAreaId=wa-syn-demo-site-01-0001`,
  `.next-practical-journey-verified` standalone→Core8096/issuer9041. loopback 임시 프로세스이며
  worker loop는 12시간 한도다. `ui/serve.sh`/새 root `launch_core_8096.py`와
  `run_workers.sh {start|once|stop|status}`로 관리한다. 공용 노출·영구 service 설치 없음.
  이전1cbfef8a/8092 launch와 빌드는 보존했고 rollback 가능하다. 비밀키·tokens·raster bytes·개인
  런타임 설정은 Git에 추가하지 않았고, 사용자 기존 untracked PNG/.playwright-cli를 보존했다.
- 최종 독립 대조는 추가 UI/RBAC/정량 계약 문제 없이 seed의 no-op 전 mirror 쓰기와 잘못된 v2
  chmod/고정 template·journal 경로 문제를 발견했다. 승인된 원장→순수 계획→쓰기 순서로 고쳐
  기존 정책의 정확한 subject tuple/실제 유효기간/현재 authority·독립 policy mirror가 맞을 때만
  무변경 skip한다. 불일치·만료·회수는 reload 없이 거절하며 같은 version으로 새 창을 만들지 않는다.
  CLI의 template/core-data/provider 경로를 실제 사용하고, fresh 임시 fixture가 과거 v2 파일 없이
  0600 v5를 생성하는 execution-path 회귀를 추가했다. V2에 없는 `/result` 호출도 detail의 실제
  result 검사로 고쳐 빈 metrics를 성공으로 출력하지 못한다.
- 이전 잘못된 재실행이 만든 **비권위 policy mirror만** Core의 정확한 admitted v5/현재 signed
  authority와 typed seal/digest를 대조해 복원했다. 원장·정책 승인·snapshot sequence7·runtime는
  바꾸지 않았다(`receipts/policy-mirror-repair.json`). 수정된 실제 `finish_admit`를 현 fixture에
  read-only/행정 호출 금지 client로 실행해 정상 skip, **16개 설정·원장 bytes/mtime 무변경과
  runtime API0** 확인(`receipts/seed-noop-final.json`). 이는 전체 새 VM provisioning 검증을
  주장하지 않으며, fresh 정책 파일 실행은 별도 offline fixture로 검증했다.
- **현재 Human bounded UI·local demo 과제는 검증 완료**. 새 파일의 exact-subject 정책 승인 절차는
  기존 관리자 경계이며 자동화/정책관리 UI 추가는 이 과제에 포함하지 않는다. 고객 자료 A–E,
  실제 DJI Terra/field/survey·정량/고객 수용, production host/domain/TLS/IdP·실데이터 복구,
  현재 LLM401·준비파일 실제 전달의 기존 외부/미검증 경계는 그대로다. 이 local 완료는 플랫폼 전체,
  production 배포 또는 고객 정확도 수용 완료가 아니며 그 경계를 통과했다고 기록하지 않는다.

### 2026-10-18 — 현장 작업공간 메뉴·이동 재편 (Human 승인, local 검증 완료)

Human이 "현장 속 메뉴 구성 흐름 이동 등 사용 흐름"을 요청했고, 제안한 방향 — 공통 현장 틀을
유지하고 **현황 / 자료 / 분석·검토 / 작업**으로 역할을 분리하며 구역 관리·현장 전체 경계·상태를
**관리**로 빼는 안 — 에 "그렇게 해줘"로 승인했다. 앞선 실무 언어·시연 과제의 재분류가 아닌,
그 위에 얹는 새 bounded UI 과제다.

```text
Requirement IDs: REQ-UX-101, REQ-INT-101..104, REQ-OPS-102, SDP-REQ-01/05; INV-020/024/051/053/060/061 유지
Owner module: apps/dashboard Operator UX (Core/API/schema/RBAC/계산/반출 변경 없음)
Acceptance criteria: 다섯 영역이 실제 라우트로 바로 이어지고, 모든 현장 화면이 같은 현장 머리(이름+메뉴)를 유지한다; 이동에는 검증된 구역·자산 범위만 실린다; 외부 비교 기록은 분석·검토 안의 구분된 하위 목록으로 남는다; 구역·경계·상태 설정은 관리로 분리된다; 자료 상세에서 "이 자료를 현재 관측으로 선택"이 분석 요청 폼으로 이어지되 자동 실행하지 않는다
Contracts affected: 없음. 표시 의도 쿼리와 href만 변경; wire/schema/calculation/authorization 무변경
Reference assets: 1cbfef8a·a649d537 실제 캡처/소스, 기존 SITE_TABS·hrefWith·사이트 루트 섹션
Adoption decisions: 기존 시각체계·컴포넌트 유지; 탭 키를 overview/materials/analysis/work-orders/manage로 재정의하고 옛 키(observations·spatial-assets·external-results 등)는 normalizeSiteTab이 흡수; 관리 탭은 구분선으로 분리 표시
Files to change: lib/site-epochs.ts, lib/operator-journey.ts, SiteHeader.tsx, sites/[siteId]/page.tsx, analysis/page.tsx, spatial-assets/page.tsx, observations/page.tsx, nav/page-title.ts, console/context-palette.ts + 관련 unit/E2E
Tests: Dashboard 1144/1144(143 files), tsc·standalone build 통과, ESLint 0 errors/기존 warning 1, Console E2E 51 pass/5 intentional skip, 실제 :3241 신규 빌드 렌더·키보드·범위 확인
HIL or real-device assumptions: 없음. 합성 시연 환경의 소프트웨어 검증이며 물리 입력·사람 연구·현장 정확도 아님
License/data implications: 없음 (기존 합성 환경만 사용, 새 의존성·외부 서비스·고객 자료 없음)
Rollback: commit revert; 직전 `.next-practical-journey-verified` 빌드/서버로 복귀 가능
```

- **메뉴 재편**: 현장 머리 메뉴를 현황 · 자료 · 분석·검토 · 작업 · 관리로 바꿨다. 자료·분석·검토는
  `/spatial-assets`·`/analysis` 실제 라우트로 바로 가고, 현황은 루트 기본, 작업·관리는 루트 섹션이다.
  옛 깊은 URL(`?section=observations|spatial-assets|external-results|…`)은 normalize가 가장 가까운
  현재 영역으로 옮긴다 — 원문 키를 화면에 다시 노출하지 않는다. 관리 탭은 데스크톱 메뉴에서
  구분선으로 분리해 일상 업무와 설정이 섞이지 않게 했다.
- **공통 현장 틀**: 분석·검토, 자료, 외부 비교 기록 화면이 각자 만든 머리 대신 같은 현장 머리
  (현장명·등록 정보·메뉴·검증된 범위)를 쓴다. 그래서 화면을 옮겨도 현장·구역·다른 영역으로 가는
  길이 사라지지 않는다. 각 화면의 중복 사이트명 줄과 "현장으로 돌아가기" 버튼은 메뉴가 대신하므로
  뺐고, SiteHeader 안에서 이름이 h2와 상세 dl에 두 번 나오던 중복도 제거했다(이름은 h2가 소유).
  "최근 외부 비교 보고" 줄은 그 이력을 실제로 읽은 화면에만 둔다.
- **섹션 정리**: 루트의 작업 섹션은 관측 작업 목록만 남기고, 현장 전체 경계(선택 설정)와 현장 상태
  전이는 관리로 옮겼다. 관리에는 작업구역 목록·작업구역 관리·자료 보기·구역 자료 준비 링크가 함께
  있다. 외부 비교 기록은 분석·검토 섹션 안의 별도 카드로 옮겨, KSI 계산 결과와 출처가 다른 기록임을
  문구로 유지한 채 한 영역에서 찾을 수 있게 했다.
- **이동 의미**: 자료 상세에 "이 자료를 현재 관측으로 선택"을 추가했다(분석 요청 권한이 있을 때만).
  목적지는 `/analysis?workAreaId=…&currentWorkOrderId=…#new-analysis-request`이며 분석을 자동
  실행하지 않는다 — 후보 여부와 기준 관측 선택은 분석·검토 화면이 실제 목록으로 판정한다. 읽기
  전용 사용자에게는 이 버튼을 만들지 않는다.
- **검증**: Dashboard **1144/1144(143 files)**, `tsc --noEmit`, standalone build, ESLint
  0 errors/기존 warning 1, Console E2E **51 passed/5 intentional skipped**(golden/tolerance 무변경).
  실제 :3241 신규 빌드에서 1440/390 두 폭으로 현황·자료(상세)·분석·검토·작업·관리·외부 비교 기록을
  확인하고 이미지를 직접 읽었다: 메뉴 5개와 활성 표시, 자료→분석 링크가 같은 구역을 유지, 관리의
  `#site-aoi` 앵커, 외부 비교 기록의 분석·검토 활성, 키보드로 메뉴 이동 후에도 구역 유지, overflow/
  busy/JS error/serious·critical axe 0, 쓰기 시도 0(GET 가드). 범위·라벨 계약은 unit으로 고정했다
  (siteTabHref 5영역, 옛 키 정규화, 헤더 범위 누수 없음, 자료 상세 비교 진입은 권한 보유 시에만).
- **알려진 기존 실패(이 변경과 무관, 손대지 않음)**: `e2e/empty-organization.spec.ts` 4개 테스트는
  a649d537 시점에도 이미 낡아 있었다 — 페이지 제목 "현장 분석"/"현장 공간 자산"(정본은 변화 분석/
  등록 자료), `/field` 빈 상태 문구 "새 관측 작업을 시작할 수 있습니다."(정본은 관측 자료 등록),
  그리고 Home·/sites 등록 CTA를 기대하지만 로컬 빈 조직 계정은 registry-scoped 등록 모드에서
  DENIED로 해석된다. 통과를 위해 단언을 약화하지 않고 그대로 두고 여기에 기록한다. 등록 모드/시드
  판단이 필요한 별도 결정이다.
- **경계**: production/고객 자료/Terra 호환/현장 정확도/사람 연구 경계는 그대로다. 이 완료는
  로컬 UI 수용이며 플랫폼 전체 수용이 아니다. 증거는 `/tmp/opencode/ksi-site-ia-20261018/`.

**테일넷 공개(같은 날, Human 요청 "외부에서 볼 수 있게 켜줘봐")**

- Dashboard `https://dgx-spark-1.tailda9552.ts.net:10010`, issuer `…:10011`을 **tailnet-only**
  Tailscale Serve로 열었다(loopback 프로세스는 그대로). Dashboard는 `AUTH_URL`/issuer/공개 origin을
  테일넷으로 재기동했고, Core8096은 `KSI_CORE_OIDC_ISSUER`=테일넷 issuer + `JWKS`=127.0.0.1:9042로
  재기동했으며, 보호 registry의 subject issuer도 테일넷으로 갱신했다(0600 유지, 백업 보관).
  기존 localhost issuer(9041)는 **원래 구성으로 복원**해 F03 rollback 재료를 깨지 않았고, 합성
  배너는 LOCAL profile로 유지된다. worker loop는 새 12h 창으로 재시작했다.
- 실제 테일넷 origin에서 로그인→현황→자료→분석·검토 1440/390 두 폭을 확인했고 서버 액션 POST도
  통과했다. **공용 인터넷(Funnel)은 켜지 않았다** — 개발용 issuer의 테스트 계정으로 관리자 로그인이
  가능해 실제 IdP 결정 없이는 노출할 수 없다. 원격 파일 업로드는 브라우저가 loopback presigned
  URL로 직접 PUT하는 구조라 이 기기 밖에서 불가(조회·분석 요청·검토는 same-origin BFF라 동작).
  되돌리기 절차와 증거는 `/tmp/opencode/ksi-site-ia-20261018/README.md`에 있다.

### 2026-10-18 — UI/UX 심층 감사와 순차 개선 (Human 승인 "순차적으로 진행")

Human이 "전반적으로 개선 필요한 UI/UX를 심층 식별"을 요청해 실제 테일넷 빌드에서 22개 라우트 ×
1440/390 두 폭 + axe/오버플로/JS 오류/키보드/compact 게이트/폼 검증 프로브로 감사하고
(`docs/audit/UI_UX_DEEP_AUDIT_2026-10-18.md`), 이어 "순차적으로 진행" 승인으로 P1→P2→P3 순서대로
반영했다. 커밋 `918bcbbb`(문구·게이트·자료 요청 경로)와 `0558dea9`(legacy 묶음·큐/분석 카피·공통 틀).

- **실제 결함 수정**: ① "정제 정사영상" 같은 내부 용어가 운영자 화면에 그대로 노출(45곳) → 표시용
  정사영상으로 통일, ② 휴대폰 등록 안내가 raw 라우트 경로를 노출, ③ 변화 분석 요청만 compact에서
  게이트되지 않아 390px에서 생성 mutation 가능(다른 mutation은 모두 게이트), ④ 자료 상세가
  "구역 자료 준비에서 요청하세요"라고 안내하지만 Console에 생성 경로가 아예 없었음(계약에는
  `POST …/spatial-data-requests` 존재), ⑤ 작업 큐가 검사 대기/완료 작업을 "수집·전송·처리 중"으로
  표기, ⑥ 같은 날 분석 3건이 동일 제목이고 `계산 결과` 랜드마크가 중복(axe moderate), ⑦ legacy V1
  패널이 V2 경로와 같은 무게로 노출, ⑧ 구역 자료 준비·작업구역에 공통 현장 틀 없음, ⑨ 검색 팔레트가
  새 IA 미반영, ⑩ skip link가 포커스 시 레이아웃을 밀어냄.
- **추가한 것**: BFF `POST /api/sites/{id}/work-areas/{area}/spatial-data-requests`(모양 검증 +
  Idempotency-Key), 네이티브 사각형 순수 헬퍼(`nativeBoundsFromInspection` — 회전·비정상 격자는
  null), 권한 인지 자료 받기 요청 액션(Core typed 사유 한국어 매핑, 성공 시 잠금, 실패 시 같은 키로
  재시도), compact 게이트 id 2종(`ANALYSIS_REQUEST`, `SPATIAL_DATA_REQUEST`).
- **검증**: Dashboard **1166/1166 (146 files)**, tsc/standalone build 통과, ESLint 0 errors(기존
  warning 1), 테일넷 실제 화면에서 새 프레임·큐 문구·분석 제목(03:24/03:12/03:09)·팔레트 6항목·
  홈 폴백 문구 확인, 분석 페이지 axe serious/critical/moderate 0, 페이지 오류 0. 자료 받기 요청은
  실측 404(Core spatial-data 배선 없음)였고 **작업이 생성되지 않음**을 요청 목록으로 확인했다.
- **남은 일**: 등록 폼 이름 통일(카피 결정), 구역 자료 준비 자동 조회, 현장 목록 필터 행 정리,
  `/more` legacy 항목·홈 공백 등 P3, 그리고 **Core spatial-data 배선(권리·정책·활성화) 결정** —
  이 환경에서 자료 준비 API가 마운트되지 않은 것은 런타임 구성 사실이며 데이터 권리 결정이 필요하다.

**3단위 디자인 에이전트 통합 (같은 날, Human "여럿 디자인 에이전트 돌리면서 분석하고 개선")**

디자인 에이전트 3개를 동시에 돌려 ① 현장 작업공간 ② 작업/현장 실행 ③ 셸·홈·검색을 나눠
진단·수정·검증하게 하고, Build가 통합(빌드·실제 렌더·E2E·문서·커밋)을 맡았다. 결과:
등록 흐름 이름 통일, 구역 자료 준비 자동 조회, 검토 결정 문구 명확화, 분석 요약 분리,
현장 작업 상세의 V2 우선·V1 접기(raw 파일명은 `파일 정보 · 처리 상세`로), 큐 단계 어휘·모바일 행
스택, VIEWER 안내 정합, 받은 업무/팀 빈 상태 행동 추가, 현장 목록 필터 분리와 **조작 썸네일 제거**,
팔레트 접근성·범위 안내, 홈 폴백·닫는 안내, `/more` 장비 범위 정직 표기. 검증은 Dashboard
**1189/1189(147 files)**, tsc/build, ESLint 0 errors(기존 warning 1), 테일넷 실제 22셀에서
axe serious/critical/moderate 0·넘침 0·오류 0, 이미지 직접 판독, E2E 단언 2곳 갱신.

### 2026-10-19 — 권한·실행 결과 피드백 정리 (Human 승인, IN PROGRESS)

Human은 현장 등록 버튼 아래의 상시 권한 문구가 버튼 높이/정렬을 망가뜨린다고 지적했고,
제안한 상황별 피드백 기준 전체를 "그래 개선해줘 너의 권고대로"로 승인했다.

- Requirement IDs: REQ-UX-101, REQ-SEC-101; INV-040(실패/미확인≠성공), INV-060(조직·현장 범위),
  INV-061(새 권한/반출 없음). Core의 authorization과 기존 검사/영수증/미확정 재시도를 유지한다.
- Owner module: `apps/dashboard/` UI 표현/상태; Core/API/schema/RBAC 변경 없음.
- Acceptance criteria: 권한 버튼 높이가 정렬되고 클릭·키보드·터치로만 짧은 사유를 공개;
  등록 허용/권한 부족/확인 실패 구분; 단순 성공만 토스트; 입력·조회·미확정 실패는 해당 영역에 유지;
  보관·종료·취소는 명시적 확인 전 0 POST, 취소/Escape 0 POST, 확인 1회; compact 제한 유지.
- Contracts affected: UI feedback component props only; authoritative registration modes unchanged.
- Reference assets/adoption: 기존 ink-mono 토큰/`.btn`/ErrorState/ResponsiveActionBoundary ADOPT;
  기존 상시 권한 helper REPLACE; 원본 화면 `/tmp/opencode/ksi-permission-design-20261019/sites-current.png`.
- Files to change: shared ActionUnavailable/ToastProvider/ConfirmDialog, layout, registration permission
  projection and entry, Site/Field blocked actions, analysis/materials/ops/team/WorkArea consumers,
  focused tests, existing design guardrail. 범위별 파일 소유권을 worker prompts에 고정.
- Tests: focused component/API permission projection tests; 전체 Dashboard suite/type/lint/build;
  실제 새 빌드 desktop/mobile popover/modal/toast/inline recovery 렌더·키보드·레이아웃/axe 확인.
- HIL or real-device assumptions: 없음. 합성 로컬 권한·브라우저 시뮬레이션이며 물리 터치/SR 연구가 아님.
- License/data implications: 새 의존성/외부 asset/AI egress/데이터 권리 변경 없음; 합성 시연 원장 변경 금지.
- Rollback: 이번 UI 커밋만 revert, 이전 standalone 빌드 보관; Core/journal/registry 수정 없음.

Primary Architect가 통합/새 렌더 수용을 소유하며 General 3개가 공통 권한·피드백, 운영 소비자,
분석·자료 소비자를 분담한다. 기존 실제고객/Terra/정량/production/IdP 경계는 그대로다.

**로컬 수용 완료 — 2026-10-19 (위 IN PROGRESS를 대체)**

- 공통 `ActionUnavailable`(비모달 native popover, viewport clamp/flip/scroll 추적), `ToastProvider`
  (최신 1개, 6초, 닫기·hover/focus/숨김 탭 일시정지, 모바일 하단 nav 회피), `ConfirmDialog`
  (native dialog, 취소 기본 포커스, 고유 title/description, 중복 실행 방어)를 실제 화면에 통합했다.
- 현장 목록/빈 현장 온보딩/등록 직접 진입은 **allowed/denied/unavailable**로 구분한다. 기존
  bootstrap·legacy 모드 판정과 API/RBAC는 불변이다. 실제 목록 버튼·필터는 모두 **36px, top 66.5px**로
  맞아 원래 권한 helper의 56.5px 스택이 사라졌다. 실패는 재조회, 확정 거부는 문의로 안내한다.
- 현장 관리·작업 목록·작업구역·팀·분석/검토·자료 받기·legacy 비교 요청의 짧은 권한 사유를
  클릭형으로 정리했다. 직접 진입의 거부 페이지, 실제 조회 실패, 업무 종료 상태, 빈 상태,
  정량 한계/근거는 유지했다. 모바일 분석 검토는 계속 가능하고 laptop mutation gate는 그대로다.
- 주소 복사·팀 정보 저장·영수증 확인 공유·운영 저장·구역 등록/보관의 단순 성공은 토스트다.
  입력 오류·목록 실패·미확정 쓰기/같은 키 재시도·부분 대체 등록의 확인 실패는 지속 인라인이다.
  검토 기록은 onReviewed 검증/상태 갱신 전에 성공 토스트를 띄우지 않고 기존 durable 상태로 남겼다.
- 구역 보관·자료 준비 취소·업무 종료에 실행 전 확인을 붙였다. **업무 종료는 다시 열 수 있음**을
  명시했다(취소/중단/삭제로 혼동하지 않음). 실제 렌더에서 보관 실패가 큰 지도 위로 숨는 문제를
  추가 발견해 **해당 구역 카드 안의 1개 오류 + 보관 다시 시도(재확인)**로 고쳤다.
- 검증: Dashboard **1252/1252 (150 files)**, tsc/최종 standalone build 통과, lint 0 errors/기존 warning 1,
  기계 소스 detector `[]`. Operations Console + 새 feedback E2E **57 passed / 11 skipped**:
  기존 compact 5, 새 compact mutation 4, roster 실제 read403으로 save표면 없음 2. E2E의 조건/임계값은
  약화하지 않았다. Home golden 4장은 이전 Human 승인(default visual/한 줄 칩/하단 문장 제거)이
  아직 반영되지 않아 원본 Git 이미지를 보관·직접 비교 후 현재 승인된 화면으로 의도적으로 갱신했다.
  `empty-organization.spec.ts`의 기존 stale 기대는 이번에도 수정/완료 주장하지 않았다.
- 실제 새 빌드: tailnet `:10010` → loopback3241 `.next-feedback-final-20261019` → 기존 Core8096/issuer9042.
  현장/Field/관리/분석/보관 모달·인라인 실패·토스트 **13개 상태** + 실제 소스 기반 격리 컴포넌트
  harness **4개 상태**에서 axe serious/critical/moderate 0, 넘침 0, page error 0; 캡처 직접 판독.
  Enter/Escape/닫기/바깥 클릭·모달 취소 0 POST·확인 1회·같은 키 재시도·6초/위치/타깃을 확인했다.
  390px touch emulation의 열기/닫기/바깥 tap도 0 mutation, 44px 닫기 버튼으로 통과했다.
- 검증 경계: **실제 원장 쓰기는 모두 가로챘다**. 보관 성공/실패는 실제 전달된 페이지에서 모의
  응답, 팀 저장/업무 종료는 실제 Core의 registry-scope read403을 넓히지 않고 실제 소비자/공통
  컴포넌트를 기존 셸 안에 로드한 격리 harness(라우터 refresh stub + 모의 응답)로 검증했다.
  권한/IdP/registry/Core/journal/데이터 원본을 변경하지 않았다. 실고객/production/물리 터치/SR 수용이 아니다.
- 증거: `/tmp/opencode/ksi-permission-design-20261019/` README, verification-summary, checks,
  harness-checks, touch-emulation, source-hashes, logs/PNG. Native 첫 캡처는 visible-tab 제한으로 실패해
  Playwright headless를 썼다. 긴 모바일 full-page 캡처의 offscreen fixed skip-link 중간 노출은 캡처
  좌표 artifact(실제 rect y=-48.8px)였고, 최종 viewport 이미지를 별도로 판독했다.
  한 번의 재캡처 로그인 timeout은 성공한 기존 최종 검증을 대체하지 않으며 새 context에서 재현되지 않았다.
- 되돌리기: 현재3241만 중지하고 이전 `/tmp/opencode/ksi-site-ia-20261018/serve-tailnet.sh`를 실행하면
  보존된 `.next-site-ia`로 돌아간다. 새 launcher는 위 evidence 경로의 `serve-feedback.sh`다.
  본 UI 요청은 로컬 완료이며 기존 실제 고객/자료 준비/production/IdP 등 제품 경계는 그대로다.

### 2026-10-19 — 현장 목록 검색·정렬 일관성 + 기본 시각 표시 (Human 후속, IN PROGRESS)

Human annotation: 검색/검색 버튼의 높이와 라벨 방향이 정렬 선택과 불일치하며, 돋보기 입력만으로
간결하게 만들 수 있는지 질문했다. Home에는 시각 표시가 있는데 목록에서는 없는 이유도 지적했다.
기존 text-first 선택을 영구 금지로 취급하지 않고 이 피드백에 맞춰 조정한다.

- Requirement IDs: REQ-UX-101, REQ-SEC-101; INV-040(기본 장식≠관측 데이터), INV-060(기존 scoped
  목록만 조회), INV-061(새 권한·미디어 반출 없음). ADR-KSI-025 D3/D6 Home 구조/실제 근거 규칙은 유지.
- Owner module: Dashboard `/sites`, shared site controls/default visual; Core/API/RBAC 변경 없음.
- Acceptance criteria: 별도 검색 버튼 없이 magnifier 입력+Enter/300ms debounce; 한글 IME 중 미적용;
  검색·정렬 동일 높이/라벨 방식, filter/status/sort/q 보존·공유 URL·back/forward·빈 결과/초기화;
  compact에서도 검색 바로 접근; 카드/비교표 모두 같은 truthful 기본 표시와 현장 열기 1개 유지.
- Contracts affected: URL query 의미/권한/상태 분류는 불변; client interaction timing/표현만 변경.
- Reference assets/adoption: 기존 DefaultSiteVisual ADOPT(홈의 장식이며 실제 이미지가 아님);
  현재 Home은 image:null 경로로, 현장 목록의 실제 미리보기 resolver는 없으므로 연결/지원 주장 없음.
- Files to change: sites/page.tsx, SiteListSort 또는 통합 controls/helper/default visual, focused tests,
  E2E 검색·정렬·표시 검증, 기존 audit/ledger. General 한 명이 source 소유, primary가 통합/렌더 소유.
- Tests: URL/IME/debounce/경합/길고 중복인 현장명 단위 검사, 실제 390/768/1024/1440 렌더·입력·키보드,
  빈 결과·clear·scope 보존·back/forward·axe·overflow·전체 suite/type/build.
- HIL or real-device assumptions: 없음; headless emulation을 물리 터치/고객 수용으로 부르지 않음.
- License/data implications: 외부 사진/지도/새 의존성·실제 자료 접근 추가 없음, 원본·정량 의미 불변.
- Rollback: 이번 UI 변경만 revert; 현재 `.next-feedback-final-20261019` 보존.

증거 root `/tmp/opencode/ksi-sites-controls-20261019/`. Git baseline c5b125c0=origin/main, tracked clean.

**로컬 수용 완료 — 현장 목록 후속 (위 IN PROGRESS를 대체)**

- 검색의 별도 버튼·위 라벨을 제거하고 돋보기 입력 하나로 정리했다. 네이티브 정렬도 아이콘을
  선택 상자 **안**에 두고 sr 라벨을 유지한다. 실제 390/768에서는 둘 다 **44px**, 1024/1440에서는
  둘 다 **36px**이며 같은 top이다(이전 1024 검색44px/검색버튼36px의 8px 불일치 제거).
- 300ms 자동 검색은 replace로 히스토리를 도배하지 않으며 Enter·정렬·지우기는 명시적 push다.
  한글 조합 중 Enter/디바운스 미적용, 입력 중 정렬 시 최신 초안 동반, in-flight 응답의 타이핑
  덮어쓰기 방어, q-only back/forward의 포커스·타이머 복구, 느린 RSC 전 필터/초기화 클릭 의도에
  따른 예약 취소를 구현했다. 상태 칩은 **확정된 q**를 유지하며, 미확정 초안은 새 필터 선택을
  덮지 않고 취소한다. native GET/noscript fallback은 유지하며 API/검색 의미는 불변이다.
- compact 검색을 접힌 메뉴 밖으로 꺼냈다. 첫 렌더의 활성 조건에서는 초기화가 추가 줄을 만드는
  것을 발견해 마지막 단일 보완에서 compact 전체 초기화를 상태 필터 안에 유지했다(검색×는 q만
  지움). desktop 초기화는 같은 높이로 옆에 남겼다. 검색/정렬 상태는 현장 열기→뒤로가기에도 복원된다.
- 목록 카드(80×64/96×72)와 넓은 비교표(64×48)에 기존 `DefaultSiteVisual`을 재사용하고 **기본 이미지**
  작은 표식을 둔다. 이전 text-first 목록 선택을 이 Human 피드백으로 개정한 것이다. 가짜 지도·사진·
  측정점은 없으며 Home 자체는 수정하지 않았다. **현재 Home도 image:null인 기본 장식**이고, 이번 작업은
  실제 관측 미리보기·이미지 접근 계약을 추가한 것이 아니다. 등록된 정사영상이 없다고 단정하지 않는다.
- 단일 General이 source와 focused tests를, primary Architect가 E2E/통합/렌더를 소유했다. 공유파일
  동시 수정 없이 수정 session을 재사용했다. 기존 Site 조회/권한/이름·ID/상태/일반 action-column 계약,
  `<1024` mutation 제한·원본·정량 의미·data/AI-egress는 바뀌지 않았다(INV-040/060/061).
- 검증: Dashboard **1287/1287 (151 files)**, tsc/build 통과, lint 0err/기존warning1, 소스 detector `[]`.
  Console+feedback+새 Sites E2E **87 passed / 13 skipped**. 새 Sites만은 **30 passed / 2 compact chip-link
  skips**이며 검색+정렬 경합, 700ms 필터/초기화 지연, focused q-only 뒤로가기, IME 이벤트+Enter,
  빈 결과·clear·reset, 찾은 현장 열기→back의 조건 복원, 높이·44px clear target을 검증했다.
  기존 11skip과 stale empty-org 기대는 이전 한계 그대로이며 임계값/의미를 약화하지 않았다.
- 실제 최종 빌드 `.next-sites-controls-final-20261019`가 tailnet10010→3241→기존 Core8096/issuer9042에서
  실행 중이다. 390/768/1024/1440 × 기본/검색조건/빈 결과 **12 상태**에서 axe serious/critical/moderate0,
  overflow0, pageerror0, API mutation 시도0. 원본과 최신 캡처를 직접 판독했고 추가 visual polish는 하지 않았다.
  IME는 브라우저 이벤트 모의이며 물리 한국어 IME·touch·SR·고객/production 수용이 아니다.
- 증거 `/tmp/opencode/ksi-sites-controls-20261019/`: before/after PNG, before-metrics, checks,
  unit/type/lint/build/E2E logs, source-hashes, verification-summary. 직전 `.next-feedback-final-20261019`와
  `/tmp/opencode/ksi-permission-design-20261019/serve-feedback.sh`를 rollback으로 보존했다. 새 launcher는
  `serve-sites.sh`; Core/registry/issuer/worker/network 노출 설정 변경 없음. 본 요청은 로컬 UI 완료다.

### 2026-10-19 — 휴대폰 현장 목록 재구성 (Human 승인, IN PROGRESS)

Human은 작은 화면에 데스크톱 요소를 넣은 것이 억지스럽다고 지적했고, full-width 검색/
필터·정렬 disclosure/장식 이미지 생략 제안에 "한 번 개선해볼래"로 승인했다.

- Requirement IDs: REQ-UX-101/SEC-101; INV-040/060/061. 모바일은 찾기→현장 선택 우선;
  승인된 Home D6/미디어·권한·원본·정량·URL query 의미는 불변이다.
- Owner module: Dashboard `/sites` + SiteListControls. General 기존 source session 재사용,
  primary가 E2E/문서/빌드/렌더 수용 소유. Core/API/RBAC/schema 변경 없음.
- Acceptance criteria: <640px 검색 전체 너비44px; 건수+필터·정렬의 조용한 단일 펼침;
  펼치면 현장 상태/정렬을 고르고 최신 검색 초안과 Apply, 초기화/취소/뒤로가기 보호;
  phone 장식만 숨겨 카드 정보/현장 열기 전체 폭, >=640 기존 UI/기본 표시/Home 유지.
- Contracts affected: responsive disclosure/interaction presentation only. Debounce/IME/clear,
  q/group/status/sort·동일 키 복구·compact mutation gate/권한 경계 유지.
- Reference assets/adoption: f062f013 실제390/768 원본 재사용; existing native details/inputs/tokens ADOPT.
  기본 이미지 생략은 phone Site list 한정이며 Home 또는 실제 미리보기의 보편 금지가 아니다.
- Files to change: sites/page, SiteListControls 또는 작은 phone helper, focused tests,
  e2e/sites-controls·operations-console, 기존 README/design guardrail/audit/ledger.
- Tests: 선택만/Apply/초안/검색 ack 중 선택 유지/취소·초기화/히스토리/IME, 전체 suite/type/build;
  실제320/390/639/640/768/1024/1440 render·선택·44target·overflow/axe·Home 회귀.
- HIL or real-device assumptions: 없음; phone viewport/touch emulation ≠ 물리 touch/OS IME/SR.
- License/data implications: 기존 자산만, 새 dependency/외부 asset/자료 접근/egress 없음.
- Rollback: 직전 `.next-sites-controls-final-20261019`와 `serve-sites.sh` 보존, 이번 UI 변경만 revert.

증거 `/tmp/opencode/ksi-sites-phone-20261019/`; baseline main f062f013=origin/main, tracked clean.

**로컬 수용 완료 — 휴대폰 현장 목록 (위 IN PROGRESS를 대체)**

- <640px는 **전체 너비 검색 → 실제 건수/필터·정렬의 조용한 summary → 전체 폭 현장 카드**다.
  종전 상태 필터 바와 상시 정렬을 phone에서 분리/중복 노출하지 않는다. native details를 펼치면
  현장 상태/정렬 기준 두 선택과 적용·초기화가 나타난다. 모달·bottom sheet·새 의존성은 없다.
- 선택만 하면 URL/결과가 바뀌지 않고, 적용 시 **최신 검색 초안+선택 조건**을 함께 확정한다.
  검색-only ack가 미확정 필터 선택을 지우지 않으며, 닫으면 미적용 선택을 버린다. Apply/전체
  reset는 패널을 닫고 summary로 focus를 돌린다. clear는 q만, 전체 reset는 이미 `/sites`인 상태의
  미확정 초안도 즉시 비운다. 기존 IME/디바운스/느린 RSC/히스토리/legacy status 보호는 유지된다.
- 실제 브라우저에서 group Apply 후 서버 응답이 parent key를 바꿔 focus를 잃는 문제를 발견했다.
  키 리마운트를 없애고 **안정된 인스턴스+명시적인 group/status prop 동기화**로 고쳤다. 동일 q의
  외부 기준 이동도 초안을 URL에 맞추고 timer를 취소하며, q-only ack는 타이핑/미적용 선택을 보존한다.
  IME 중 phone Apply도 제출하지 않는다. 초기 hidden 중복 locator 오류는 테스트 대상을 visible로
  좁혀 진단했고, 실제 focus/URL/타이머 검증을 삭제하거나 약화하지 않았다.
- phone의 장식용 기본 이미지만 숨겨 gutter를 없앴다. 실제 390px에서 검색358px/44px,
  현장 열기332px/44px이며 320px에서도 검색288px/44px·열기262px/44px로 본문 폭을 쓴다.
  >=640px의 이미지·검색/정렬 구조와 Home D6는 그대로다. **768/1024/1440px 원본 vs 최신 PNG는
  픽셀 완전 동일**(동일 합성 원장/뷰포트/locale). 이미지 생략은 실제 미리보기의 보편 금지가 아니다.
- 최종 `.next-sites-phone-20261019`를 기존 tailnet10010→3241→Core8096/issuer9042에서 실행 중이다.
  source 변경은 Sites page/controls/NavLink와 focused tests뿐이며 Core/API/RBAC/schema/identity/media/
  원본/계산/data·AI-egress/1024 mutation gate는 불변이다(INV-040/060/061).
- 검증: Dashboard **1298/1298 (151 files)**, tsc/build 통과, lint 0err/기존warning1, source detector `[]`.
  Console+feedback+Sites E2E **88 passed / 16 skipped**(종전13skip+새 phone-only test의 nonphone3).
  새 phone 기능은 선택-only·닫기/재열기·검색 ack 중 선택 유지·초안 포함 적용·group 변경 후 focus·
  같은 URL reset·뒤로가기·IME·현장 열기 복원을 browser에서 확인했다. 기존 stale empty-org는 수정/
  완료 주장하지 않았다. Home 4폭 golden을 변경하지 않고 회귀 통과했다.
- 실제320/390/639/640/768/1024/1440 + phone 펼침/적용/빈 결과 **16 상태**에서 axe serious/critical/
  moderate0·가로 넘침0·pageerror0·API mutation 시도0. 캡처를 직접 판독하고 이전 모습과 비교했다.
  native details/tap/keyboard는 브라우저 에뮬레이션이며 물리 touch/OS 한국어 IME/SR·고객·production
  수용으로 부르지 않는다. 고객/자료 준비/production/IdP 등 기존 제품 외부 경계도 그대로다.
- 증거 `/tmp/opencode/ksi-sites-phone-20261019/`: before/after/panel/applied/empty PNG, checks,
  nonphone-comparison, verification-summary, source-hashes, unit/type/lint/build/E2E 로그.
  새 launcher `serve-phone.sh`; 되돌리기는 현재3241만 중지 후 보존한 직전
  `/tmp/opencode/ksi-sites-controls-20261019/serve-sites.sh`를 실행한다. 본 Human 요청은 로컬 UI 완료다.

### 2026-10-19 — Desktop 현장 카드/목록 보기 (Human 승인, IN PROGRESS)

Human은 desktop의 작고 애매한 기본 이미지가 이전보다 나쁘게 보인다고 지적하며 리스트 선호와
Home 같은 시각적 보기 선호를 함께 제안했다. 두 가지 보기(카드/목록), desktop 카드 기본·마지막
선택 유지·phone 유지 제안에 "그렇게 해보고 한 번 구성해봐"로 승인했다.

- Requirement IDs: REQ-UX-101/SEC-101, INV-040/060/061; Home ADR025 D3/D6와 미디어·원본·정량은 불변.
- Owner module: Dashboard `/sites` + owned site presentation/preference helpers. General 기존 source
  session 재사용, primary가 E2E/통합/실제 렌더 소유. Core/API/schema/RBAC 변경 없음.
- Acceptance criteria: >=1024 카드/목록 전환; 기본2열 넓은 typographic cover, 1건은 1열 폭만;
  목록은 장식 없는 dense 표·행 action1개; query/filter/sort/입력 초안 유지; 마지막 모드 기억,
  reload/현장 상세→back/저장 제한 graceful; <1024와 Home의 검증된 표현 유지.
- Contracts affected: presentation preference only. UI cookie 권고(검증된 cards/list 값만, Sites path,
  no IDs/query/auth/analytics; SSR 올바른 첫 화면/flash 방지). Core 계정 설정·새 endpoint 없음.
- Reference assets/adoption: 기존 Home neutral default/ink-mono ADOPT; 작은 desktop thumb REMOVE;
  실제 자료 source 없는 곳은 현장명 중심의 `기본 표지`, 사진/지도/previewUrl 지원을 꾸미지 않음.
- Files to change: sites/page, site gallery/view-mode/pref helpers, SiteListControls toolbar slot 등 최소
  연결, focused Page/helper tests, E2E/gallery/list/persistence, 기존 README/design guardrail/audit/ledger.
- Tests: 실제 여러/한 현장 2열·single bounded, 목록 비교/이미지 없음, 두 모드 search/sort/race,
  reload/SSR/cached-back/invalidpref/storageblocked; <1024/Home 회귀, axe/overflow/keyboard.
- HIL or real-device assumptions: 없음. headless/브라우저 emulation을 물리 touch/SR/고객 수용으로 부르지 않음.
- License/data implications: 외부 asset/dependency·미디어 접근·원본·계산·egress 없음; 선택한 표시 모드만 저장.
- Rollback: 직전 `.next-sites-phone-20261019` + `serve-phone.sh` 보존; 이번 UI 변경만 revert.

증거 `/tmp/opencode/ksi-sites-desktop-views-20261019/`; baseline f8617774=origin/main tracked clean.

**로컬 수용 완료 — Desktop 카드/목록 (위 IN PROGRESS를 대체)**

- >=1024px에 `카드 | 목록` 두 표현을 추가했다. 기본 카드는 실제 현장명을 크게 읽는 2열
  typographic cover(1024에서180px, 1280+200px)와 상태/갱신/다음 행동/열기다. 한 현장도
  한 열만 쓰며 실제398/498/578px(1024/1280/1440) 폭으로 확인했다. `기본 표지`는 관측 사진이나
  지리가 아니라 기존 중립 장식+등록 이름이다. 작은 이미지를 억지로 확대하거나 실제 preview를 꾸미지 않았다.
- 목록은 장식을 완전히 뺀 비교표이며, 현장명/상태/진행/갱신/다음 행동/열기1개를 유지한다.
  min762/합리적 열 폭으로 1024에서도 본문에 맞는다. 필터 결과 건수는 두 표현이 같은
  visible/total을 쓴다. 갤러리 h2/각 현장 h3로 탐색 가능하며 동일 이름의 기존 신원 disclosure도 유지했다.
- 전환은 클라이언트 로컬 상태만 바꿔 URL/검색 초안/디바운스/IME/정렬/필터를 건드리지 않는다.
  현재 보기만 DOM에 둔다. 보기 버튼은 type=button/aria-pressed, 클릭·Enter 뒤 focus 유지.
  보기 선택 후 현장 상세→bare URL back, 검색 후 전환, 새로고침 모두 검증했다.
- 기억은 **기능 쿠키 `ksi-sites-view=cards|list`** 하나만(Path=/sites, SameSite=Lax, 1년,
  HTTPS Secure). ID/query/auth/analytics 없고 사용자 선택 때만 쓴다. 서버가 첫 화면에 읽으며
  Client는 cached back의 최신 쿠키를 반영한다. 잘못된 값은 cards, 읽기/쓰기 차단은 현재 탭
  전환을 막지 않는다. JS 없는 첫 응답에는 dead toggle 대신 서버가 선택한 표현을 읽을 수 있다.
  Core 계정 설정·API·RBAC/schema/미디어·원본/계산·data/AI-egress 변경 없음(INV040/060/061).
- 발견/정정: list 모드 빈 검색 결과에 빈 표와 EmptyState가 중복될 수 있어 결과 panel은 null로
  유지하고 기존 EmptyState 하나만 남겼다. 쿠키 read getter SecurityError도 optional pref로 처리했다.
  카드에 누락된 filtered/total 건수를 복원했다. 브라우저 테스트의 0-total은 실제 데이터가 아니라
  streaming UI가 준비되기 전 count()였으며 default 카드 준비를 기다린 뒤 같은 강한 count 검증을 재실행했다.
- 검증: Dashboard **1319/1319 (152 files)**, tsc/build 통과, lint0err/기존warning1, source detector `[]`.
  Console+feedback+Sites+새 view-mode E2E **98 passed /22 skipped**(직전88/16 +새10/6), 마지막 전체
  동시 실행 로그까지 확인했다. 서버 첫 응답 list·잘못된 pref·차단 모의·입력 중 전환·query 유지·
  2열/1개 bounded·빈 결과 하나·단일 row action을 확인했다. Home 4폭 golden은 변경하지 않았다.
- 실제 preview `.next-sites-desktop-views-20261019`: tailnet10010→3241→기존 Core8096/issuer9042.
  390/768 및 1024/1280/1440의 card/list/filtered/empty **14 상태**에서 axe serious/critical/moderate0,
  overflow0/pageerror0/API mutation0. 기존 isolated E2E5현장과 실제 시연1현장의 렌더를 모두 직접 판독했다.
  phone390/tablet768 PNG는 직전과 **픽셀 완전 동일**; 전환/기억이 phone 표현을 강제하지 않는다.
- 증거 `/tmp/opencode/ksi-sites-desktop-views-20261019/`: before/card/list/filtered/empty/multiple
  PNG, checks/cookie flags, small-screen-comparison, source-hashes, verification-summary,
  unit/type/lint/build/E2E 로그. physical touch/OS IME/SR/고객·production·실제 미디어 수용 아님.
  기존 stale empty-org 및 다른 제품 외부 경계는 그대로다. 새 launcher `serve-views.sh`;
  직전 `/tmp/opencode/ksi-sites-phone-20261019/serve-phone.sh`와 phone build를 rollback으로 보존했다.
  이 Human UI 요청은 로컬 완료이며 전체 제품/고객 수용을 닫지 않는다.

### 2026-10-20 — 제품 정체성 보강과 개발 순서 정정 (Human 승인)

Human은 제품 정의가 "데이터 제공 + 고정 분석"으로 축소되었고, 개발 순서가 계약·게이트 완료
뒤에만 진행되는 방식이라 제품 관점의 목표가 약해졌다고 지적했다. 제품 방향의 대규모 재정의는
하지 않고, 이미 확정된 ADR-KSI-038/039를 근거로 표현과 실행 순서만 명확히 했다.

- **확정된 제품 정체성**: KSI Site Intelligence Platform은 드론·측량 장비·외부 소프트웨어
  등에서 생성된 현장 공간정보를 현장·구역·관측 시점에 연결하고, 데이터의 품질·사용 조건·버전·
  계보를 관리하여 사람과 소프트웨어, AI 에이전트가 공통 업무 계약으로 재사용하게 하는
  공간정보·분석 서비스 플랫폼이다. 자료의 유효성, 목적별 사용 적합성, 분석 결과의 재현
  가능성을 구분해 판정하며, 검토·외부 결과를 기존 기록에 연결하고 다음 관측(`t0→t1→t2`)의
  변경 영향을 추적해 반복적인 데이터 준비·검증·연동 비용을 줄인다. 첫 실증은 건설 토공의
  WorkArea별 반복 지형·체적 변화 검토다.
- **경계**: `Site Context` 등 미승인 최상위 용어와 별도 원장은 만들지 않는다. 기존 Site·
  WorkArea·Observation Epoch·revision·digest 매핑을 그대로 쓴다. `Site State와 Change`는
  관측 범위·시각·유효 조건·미확인 영역·최신성·변경 이력을 가진 버전화된 관측 기록이며
  실시간 디지털트윈이 아니다.
- **판정 3층**: 자료 유효성 / 목적별 사용 적합성 / 결과 재현 가능성. 정량 조건 미충족이
  허용된 열람·추출까지 일괄 차단하지 않으며 열람 가능이 정량 적합성을 뜻하지도 않는다.
- **핵심 동작은 반복 관측**: `t0→t1`은 등록 → 적합성 판정 → 분석 → 결과·근거 → 사람
  검토/재관측 연결, `t1→t2`는 새 자료 → 정의·비교 규칙 재사용 + 변경 영향 확인 → 새 쌍
  admission·재분석 → 결과 갱신. 재사용되는 것은 정의·규칙·연동 흐름이고 이전 쌍의 계산
  authority나 결과는 재사용하지 않는다. 일반 외부 분석 레이어 등록은 SDP-09 경계를 유지한다.
- **정본 반영 위치**: 제품 헌법 §제품 정체성, PRD §1.1/§1.1.2, 결정원장 §고객·가치,
  ADR-KSI-038 §D1/§D2, SDP-20260930 로드맵(신규 절). `product-state.md`의 Milestones/
  Current slice 섹션과 PHASE_REGISTRY status는 계약 해시로 고정되어 있어 **한 글자도 변경하지
  않았다**. `docs/00_READ_FIRST.md` 권위 순서와 불변식은 그대로다.
- **개발 순서 정정**: 필수 계약(권한·보안·조직/현장 범위·정량 의미·보관/반출·재현성)은
  생산 주장 전에 확정한다. 그러나 그 확정만으로 모든 고객 흐름·UX 검증이 기다릴 이유는 없다.
  격리·합성 환경에서 실제 종단 업무 흐름(`t0→t1→t2`와 UI/API/MCP 일관성)을 **병행 검증**하고
  그 결과는 로컬 소프트웨어 증거로만 기록한다. 제품 검증(상호운용성·반복 준비 시간·사람
  개입 감소)과 사업 검증(지불 의사·구매 전환)은 기술 수용과 분리된 트랙이다.
- **다음 실행 순서**(SDP 로드맵에 기록): ① 공간데이터 요청 경로의 권리·정책·Core 배선
  ② 목적별 적합성 판정과 허용된 조회의 분리 ③ `t0→t1→t2` 반복 갱신·변경 영향의 운영자/API
  일관 ④ 실제 고객 산출물·두 주기 반복 사용 ⑤ 유료 사용 의사·구매 전환. ①~③은 병행 검증
  가능하고 ④~⑤는 외부 입력과 고객이 필요하다. ①~③의 완료를 ④~⑤가 대신하지 않고, ④~⑤의
  미완이 ①~③의 사유가 되지 않는다.
- **검증**: `tests/contract/test_physical_site_product_boundary.py` +
  `tests/contract/test_repository_normalization.py` 46 passed, `tools/validate_repository_normalization.py`
  PASS(R0-R3 contract), `git diff --check` 통과. Dashboard 변경 없음(직전 작업 진입 용어 정리는
  별도 커밋 130174a8). 계약·스키마·RBAC·계산 수식·불변식 변경 없음.

### 2026-10-19 — Desktop 페이지·카드 비율·새 현장 카드 (Human 승인, IN PROGRESS)

Human은 카드4현장/목록10행 번호 pagination 권고를 승인하면서 폭에 맞는 카드 비율과
`+ 새 현장 추가` 형태의 같은 카드 진입을 요청했다. 화면에 억지로 맞추지 않고 자연스러운
스크롤을 남기는 앞선 권고를 보존한다.

- Requirement IDs: REQ-UX-101/SEC-101, INV-040/060/061. UI 표현/URL state만 변경하며 HomeD6,
  Core/API/schema/RBAC/미디어/원본/정량/data·AI-egress/1024 mutation gate는 불변.
- Owner module: Dashboard Sites desktop. General 기존 source session 재사용; primary가 E2E/통합/
  렌더 소유. phone/tablet은 앞서 승인된 단순 목록 유지(새 pagination은 desktop 두 보기만).
- Acceptance criteria: cards4실제현장/list10행, 번호/이전/다음/한page생략; URL page bookmark/
  reload/back·범위 clamp, criteria/mode reset1·q/status/group/sort 및 초안/IME 보호. 새 page는
  결과 시작으로 이동/키보드 문맥 제공. 실제 records와 utility count를 섞지 않는다.
- Cards: max 폭 제한·표지 aspect ratio로 과도한 가로 늘어남 방지, notebook2열/넓은 화면에서
  content-fit 추가열 가능. 본문/열기 행동을 자르지 않으며 기존 factual identity 그대로.
- Add tile: card-mode 마지막 page 끝에 별도 `새 현장 추가` control(현장건수/정렬/4실제record cap 제외).
  또래 row에 stretch하고 홀로 남으면 낮은 min-height로 긴 빈 공간을 만들지 않는다. 실제4record가
  꽉 찬 마지막 page에서는 utility만 추가 줄이 될 수 있으며 가짜 데이터 page를 만들지 않는다.
  상단 등록 버튼 유지, allowed/denied/unavailable는 기존 registration availability와 완전히 동일.
- Contracts affected: UI page query only, remembered mode cookie는 cards/list만 그대로. No new Core
  endpoint/grant or raw-preview workaround. 마지막 page control은 fake SiteView record가 아니다.
- Reference assets/adoption: 기존 neutral cover/native links/buttons/ActionUnavailable ADOPT;
  custom tile trigger가 필요하면 ordinary caller와 backwards-compatible. 외부 asset/dependency 없음.
- Files to change: page/view/renderers/query/paging/utility tile + 최소 controls/cancel 연결,
  ActionUnavailable optional presentation, focused tests, existing E2E/docs/ledger.
- Tests: math4/10/clamp, 실제5Site Card2pages, 10+List component fixture 필요 시 simulation 명시,
  scope/history/draft/reset/mode, tile3permission·denied0POST, width/ratio/44coarse targets,
  ordinarypopover·phone/tablet/Home regression, whole suite/type/build/axe/overflow.
- HIL/real-device assumptions: 없음; browser/touch/IME simulation은 physical/SR/customer 수용 아님.
- License/data implications: 기존 facts/owned assets만; 실제시연Core8096/registry/원본 수정 없음.
- Rollback: 직전 `.next-sites-desktop-views-20261019`/serve-views.sh와 UI commit 보존.

증거 `/tmp/opencode/ksi-sites-pagination-20261019/`; baseline7eb4a1c1=origin/main, tracked clean.

**로컬 수용 완료 — 페이지·비율·등록 카드 (위 IN PROGRESS를 대체)**

- Desktop 카드4실제현장/목록10행을 URL `page`로 나눈다. 번호·이전·다음·current aria 표시,
  첫/끝 비실행·한page 푸터 생략·큰 page 수 window/ellipsis를 구현했다. 잘못된 번호는 실제
  범위로 clamp해 가짜 빈 결과를 만들지 않는다. 검색/필터/정렬은1, 실제 모드 변경도1로 복귀;
  이미 활성인 보기 재클릭은 페이지를 건드리지 않는다. 상세→back/reload로 원래 page가 남는다.
- 번호 선택은 확정된 q/status/group/sort를 쓰며 미확정 검색을 취소·입력과 URL을 맞춘다.
  모드 전환은 반대로 미확정 검색/IME를 취소하지 않고 자동 적용을 이어간다. 실제 브라우저에서
  처음의 두 동작이 뒤섞이는 오류를 찾아 고쳤다. 같은 서버-cookie slice를 두 모드에 공용하지
  않고 **카드/목록의 행·page/meta/footer를 독립 계산**해4/10 경계와 blocked-cookie도 정확하다.
  모드 reset가 page를 제거할 때1회의 RSC 갱신은 허용하지만 새 Core endpoint/권한 변경은 없다.
- 카드 표지는16:7, grid는 왼쪽 정렬·최대920px(2열)/1350px(아주 넓은 화면3열)로 묶었다.
  실제 카드폭은 모든 검사 viewport에서480px 이하이며, 본문·열기 행동을 비율 때문에 자르지 않는다.
  푸터는 카드의 제한된 폭에 맞춰 가운데 정렬하고16px 간격을 줘 카드에 붙지 않게 했다.
- 마지막 card page에 점선 `+ 새 현장 추가` control을 넣었다. 실제 Site가 아니며 count/sort/page
  계산에서 제외한다. 또래 row 높이로 stretch하고 홀로 남으면 min160으로 긴 빈 공간을 줄인다.
  상단 등록 진입도 유지. allowed만 기존 /sites/new로, denied는 클릭 설명·Escape focus복귀만,
  unavailable는 별도 사유와 lookup retry다. RoleADMIN으로 bootstrap을 추론하지 않는다.
- 통합에서 발견한 Next server/client event boundary 오류는 pager를 client entry로 명시해 고쳤다.
  unit/import만으로 수용하지 않고 실제 SSR/browser 경로로 재검증했다. `5 /5`로 모호했던 단일
  마지막 record도 `5–5 /5`로 명시한다. custom trigger는 기존 ActionUnavailable의 ordinary
  동작을 바꾸지 않고 내용/겉모양만 선택적으로 확장했다.
- 검증: Dashboard **1351/1351 (152 files)**, tsc/최종 build 통과, lint0err/기존warning1,
  source detector `[]`. Console/feedback/Sites/views/pagination E2E **106 passed /30 skipped**
  (직전98/22+new paging8/8; desktop-only slots/기존 제한). 실제5Site 격리 fixture에서4+1 분할,
  page2 생성control/count 제외, scope/timer/reset/mode/reload/detail-back/clamp/권한거부0writes,
  ratio/폭과 footer 간격·가운데를 검증했다. 기존 stale empty-org 기대는 수정/완료 주장하지 않았다.
- 실제 preview1Site는 그대로 두었고 records를 추가하지 않았다. 최종 `.next-sites-pagination-verified-20261019`
  tailnet10010→3241→기존Core8096/issuer9042에서5폭(390/768/1024/1440/1920) **11상태**
  axe serious/critical/moderate0·넘침0·pageerror0·API mutation0. 권한거부 control은 실제 계정에서
  설명만 열었다. 실제 data가1page라 번호 푸터가 없는 것도 확인했다. phone390/tablet768 픽셀은
  직전과 완전 동일, Home golden 변경 없음.
- List10+ 경계는 별도23가상record actual-component browser fixture로10/10/3 및 back을 확인했다.
  실제 source +현재 CSS +기존 shell을 사용했지만 navigation stub/가상 data이므로 Core/고객
  종단 수용으로 부르지 않는다. 이 fixture3상태도 axe/넘침/error0, real Core writes0이다.
  캡처를 직접 읽고 마지막 footer 간격/정렬 보완 후 최종 렌더를 확인했다.
- Source는 Dashboard만; Core/API/schema/RBAC/registry/실제 data/원본/미디어/계산/AI-egress/
  1024 mutation gate 불변(INV040/060/061). Cookie는 mode만, page는 URL만. physical touch/
  OS IME/SR/고객/production 수용은 미검증이며 기존 외부 경계는 그대로다.
- 증거 `/tmp/opencode/ksi-sites-pagination-20261019/`: before/live/page1/page2/simulated-list
  PNG, live-checks/list-fixture-checks/small-screen-comparison/source-hashes/verification-summary,
  unit/type/lint/build/E2E logs. 새 launcher serve-pagination.sh; 직전
  `/tmp/opencode/ksi-sites-desktop-views-20261019/serve-views.sh`와 build를 rollback으로 보존했다.
  본 Human UI 요청은 로컬 완료다.

최종 추가 회귀: raw server `base`에 현재 page가 함께 전달되는 상태 칩도 criteria patch 시 page를
명시적으로 제거하도록 중앙 URL helper를 보완했다. 이를 위한 단위1건과 page2→전체 상태 칩의
실제 browser 회귀를 추가했다. 최종5spec 동시재검은106pass30skip, 1351unit/type/build 통과다.

### 2026-10-20 — 실행 중심 전환: 다음 작업의 정확한 경계 (읽기 전용 gap map, IN PROGRESS)

정본 보강(a24a8afe) 뒤 개발 중심을 실행 증명으로 옮기기 위해 세 빈칸의 실제 경계를
읽기 전용으로 대조했다. 코드·파일 수정은 없다.

- **자료 준비 경로(Console `자료 받기 요청` → 404)**: 코드가 아니라 **운영자 구성 부재**다.
  Dashboard BFF(`app/api/.../spatial-data-requests/route.ts`)·Core 라우터
  (`domains/external/delivery/api.py` PUBLIC_BASE)·job store·grant/현재성·다운로드/감사/cleanup·
  워커(`services/processing-controller/spatial_data_*`)·native-window primitive
  (`packages/geo-spatial/.../external_native_window.py`)·OpenAPI/스키마가 모두 트리에 있다. Core는
  `KSI_CORE_SPATIAL_DATA_CONFIG_FILE`이 없으면 **데이터 레인을 미장착**으로 둔다
  (`composition/runtime_config.py:_spatial_data_config_path_env`, `routes/external.py:33-83`,
  `platform_production.py:101-121,201-214`). 따라서 404는 "구현 없음"이 아니라 "보호 구성 부재"이며
  구성은 sealed policy/runtime/activation+Ed25519 서명, rights(grant/revocation) 파일, S3 저장소,
  `SPATIAL_DATA_WORKER` 신원 등 **운영자·고객 입력**이다(`docs/ops/SPATIAL_DATA_PRODUCTION_PROVISIONING.md`).
  2026-10-14 검증호스트 체인(공개 실자료 COMPLETED→다운로드→독립 오라클 PASS)은 이미 실증됐고,
  남은 것은 2차 호스트/주기 재현·고객·배포 게이트다.
- **열람 vs 정량 판정**: 이미 **분리되어 있다**. 정량 적합성은
  `domains/external/quantity/external_relative_volume_analysis.py`의 admission(REMEDIATION_REQUIRED/
  BLOCKED/ADMIT_PROVISIONAL/ADMIT_EVALUATED)과 `external_quantitative_authority.py`가 결정하고, 열람은
  `SITES_READ` 기반 카탈로그(`domains/external/ingress/spatial_asset_catalog.py`)·검사 사실/표시
  다운로드(`external_artifact_inspections.py`, `external_display_artifacts.py`)·grant 범위 READ
  (`domains/external/delivery/asset_discovery.py`, `source.py`, `jobs.py`)가 결정한다. 카탈로그는
  `analysisStatus=NOT_EVALUATED`를 항상 유지한다. 정량 실패는 **수치 회수만** 막고 허용된 열람은
  막지 않는다. 문제는 구현이 아니라 **양쪽을 한 자산에 대해 함께 고정하는 검증이 없다**는 점이다.
- **반복 관측 `t0→t1→t2`·변경 영향**: 재사용 증거는 이미 있다(FPC-09A/B/C/D: 세 시점 두 쌍, 공유
  `t1` 입력 digest, 쌍별 독립 authority, review→proposal→승인된 비실행 planning-only 후속 작업,
  replay 동일성). **부족한 것은 "새 관측이 기존 결과에 미치는 영향"의 자동 전파**다. 결과·계산·
  평가는 불변 가산 기록이므로 새 `t2`는 새 쌍 결과를 만들 뿐 `t0→t1` 결과를 갱신하지 않으며,
  현재 존재하는 영향 장치는 **적합성 투영**(후행 실패 평가가 일반 수치 회수를 막고 이력은 읽을 수
  있게 함)뿐이다. "superseded by new observation" 상태·차분·영향 기록은 없다. 이는 제품 결정이
  필요해(영향의 정의) 지금 임의로 만들지 않는다.
- **Human 결정 vs 지금 가능한 일**: GAP-02(실제 export 표본·권리), GAP-05(사용권·TTL·AI 동의 값),
  SDP-01(첫 구매자·표본), GAP-08(호스트/OIDC/사용자), GAP-09(요금·수용 기준)는 **외부 입력/결정**이고,
  GAP-03(부분 coverage/NoData 규칙 문구), GAP-04(자산/작업 모델·STAC/COG 채택), GAP-06(자원 상한
  수치)는 **제품 결정 + 이미 있는 강제 코드**. 요청 경로의 남은 차단요인은 입력이며, 열람·정량
  분리는 지금 고정할 수 있다.
- **다음 bounded task**: `tests/contract/test_read_vs_quantity_separation.py` 하나로 **합성 자산
  하나에 대해** (1) 카탈로그 열람 200 + `analysisStatus=NOT_EVALUATED`, (2) 검사 사실/표시 열람 200,
  (3) 정량 경로는 평가된 수치를 제시하지 않음(ADMIT_PROVISIONAL 또는 typed BLOCKED — 실제 기록값을
  그대로 단언), (4) grant READ는 통하고 PREPARE는 typed denial, (5) 실패 평가 주입 후 **수치만**
  막히고 (1)(2)는 유지됨을 함께 고정한다. 제품 코드·계약·권한 변경 없이 외부 입력 0으로 만들 수
  있고, RED가 나오면 경계 위반이므로 고치지 말고 보고한다.

**다음 bounded task 실행 — 열람/정량 3층 경계 고정 (2026-10-20)**

정본 보강으로 새로 확인한 제품 경계("열람 가능 ≠ 정량 적합")를 **한 자산에 대해 양쪽을 함께
고정하는 검증**으로 옮겼다. 제품 코드·계약·권한 변경 없음.

- `tests/contract/test_read_vs_quantity_separation.py` 신규(9 tests). 실제 Core 앱을 하나 mount하고
  생성된 봉인 DSM 쌍(독립 측정 checkpoint 없음)으로 다음을 함께 고정한다.
  1) 카탈로그 목록/상세 열람 200 + `analysisStatus=NOT_EVALUATED`(+ `dataAccess=NOT_AVAILABLE_FROM_CATALOG`,
     supportedActions=VIEW_METADATA만).
  2) 같은 바이트의 검사 사실/표시 열람이 SITES_READ로 200, 바이트 노출 없음, 없는 receipt 다운로드는
     비노출 404.
  3) 정량 경로는 평가된 수치를 제시하지 않는다 — V2 admission이 **ADMIT_PROVISIONAL**, suitability
     `PROVISIONAL_ACCURACY_UNVERIFIED`, execution `QUEUED`, 응답에 cut/fill/net 없음, evidence의 두
     epoch 모두 `UNASSESSED`/`CHECKPOINT_EVIDENCE_ABSENT`.
  4) 공간데이터 레인은 grant 하 READ가 200이지만 PREPARE capability 없음은 typed 403, grant 회수 후
     view는 `ACCESS_REVOKED`.
  5) 같은 바이트에 실패 평가를 주입하면 신규 작업이 **REMEDIATION_REQUIRED**로 전환되고 수치만
     억제되며 (1)(2) 열람은 계속 200(과거 잠정 기록도 조회 가능).
  6) 스키마가 `analysisStatus`를 `NOT_EVALUATED` 상수로 못 박는지 + **변이 증명**(열람 게이트가 정량
     적합성을 참조하도록 바꾸면 이 pin이 깨지는 것을 실제로 관측) + 모듈이 고객·현장 수용 주장이 아님을
     문서로 고정.
- **과정 중 발견한 기대 오류(제품 결함 아님)**: 공개 요청 경로(`select_current`)는 per-grant 사유를
  노출하지 않고 `GRANT_REQUIRED`로 닫는다(`domains/external/delivery/grants.py:404-424` — 비노출
  설계). `OUTPUT_OUTSIDE_GRANT`는 명시 grant 조회 경로(`require_current`, 같은 파일 :328)에서만
  나온다. 기존 저장소도 이 구분을 고정한다(`tests/contract/test_spatial_data_current_grants.py:103`).
  테스트 기대값이 공개 경로에 명시 grant 경로의 사유를 적용한 것이 원인이라, **공개 경로는
  `GRANT_REQUIRED`로, 명시 grant 표면은 `OUTPUT_OUTSIDE_GRANT`로 각각 고정**하도록 교정했다.
  제품 코드는 건드리지 않았다.
- 검증: 신규 모듈 9 passed; grant/권한/카탈로그/API 회귀 137 passed; AI·계약·catalog·cleanup·consumer
  회귀 452 passed; `ruff check` 통과, `ruff format` 적용 후 9 passed 재확인, `git diff --check` 통과.
- 증거 성격: **로컬 소프트웨어 경계 증명**이다. 고객/현장/생산 수용이 아니고, Terra 호환성·절대
  정확도·정산·승인을 증명하지 않는다. EXT-VAL·SDP-04/05/08·product-state 수용은 불변이다.

### 2026-10-20 — 반복 관측 "변경 영향 확인" 결정 (Human 승인, IN PROGRESS)

gap map으로 남은 빈칸 ③의 제품 결정이 Human에게 갔다. 결정: **중립 알림 + 새 결과 링크**,
표시는 **분석·검토 결과 화면 우선**(Home은 ADR-KSI-025 D6 구조를 건드리지 않는다).

- 허용: 이전 결과는 그대로 두고, "이 작업구역에 더 새 관측이 있습니다" 사실과 이동 링크만 추가.
  새 쌍의 결과가 아직 없으면 링크 없이 사실만 말하고 수치를 암시하지 않는다.
- 금지: 이전 기록에 "대체됨/구버전" 같은 **새 상태를 부여하지 않는다**(불변·가산 기록 원칙).
  새 관측이 있다는 사실이 **정량 적합성 판정을 바꾸지 않는다**(3층 판정 분리 유지).
  조직·현장 범위(INV-060 404-fold)와 계보(INV-051) 훼손 금지. Home 우선순위·한 현장 한 장 규칙 변경 금지.
- 형태: Core 쓰기 경로 없이 기존 Core 읽기(분석 목록/관측 후보)로 **읽기 시점 파생 투영**만 한다.
  "변경 영향"이라는 새 개념·엔드포인트·스키마를 만들지 않는다.
- Human 결정이 막지 않은 나머지: 라벨 문안(중립 알림 문구)과 세부 배치는 코드 형태를 바꾸지 않고
  strings로 조정 가능하다.

구현은 Dashboard 전용 파생 투영 + 분석·검토 결과 화면 한 줄 알림으로 한정하고, Core·계약·Home은
건드리지 않는다. 읽기 전용 파생이므로 불변 기록을 다시 쓰지 않는다.

**구현·검증 완료 — 반복 관측 중립 알림 (Human 결정 반영)**

- 구현: 신규 `apps/dashboard/src/lib/analysis-newer-observation.ts`(순수 helper `deriveNewerObservationNotice`
  + `findEpochCaptureEndedAt`)와 `AnalysisRequestPanel`의 `NewerObservationNotice` 한 줄 알림. 읽기 시점
  파생이며 Core 쓰기·저널·스키마·Home 변경이 없다.
- 판정 규칙: **이전 결과의 기준 관측 시각**은 Site 범위 관측 목록에서 찾고(작업구역 귀속 여부와 무관),
  **"더 새 관측" 후보**는 분석의 작업구역에 귀속된 관측만으로 제한한다 — "이 작업구역에 더 새 관측이
  있습니다"가 문장 그대로 참이도록. 엄격히 더 늦은 시각만, 동일 시각 제외. 결과가 실제로 로드된 새 분석에만
  링크를 건다(가짜 결과 링크 금지). 반환 타입에 적합성·수치·상태 필드가 없어 **4번째 판정 게이트가 되지
  않는다**. 이전 기록에 "대체됨/구버전" 같은 새 상태를 붙이지 않고 검토·수치·한계는 그대로 둔다.
- **실제 데이터에서 발견해 바로잡은 것**: F-03 실재사용 리그의 분석 기준 관측이 같은 작업구역에 귀속되어
  있지 않아(합성 리그의 귀속 특성) 엄격한 규칙으로는 알림이 뜨지 않았다. "이전 결과의 기준 시각"과
  "작업구역의 새 관측"을 서로 다른 목록에서 해석하도록 정정했고, 이 실측 형태를 회귀 테스트로 고정했다.
- 실제 검증(F-03 Core 8092 재사용 리그, 실브라우저): 이전 분석 카드에
  "이 작업구역에 더 새 관측이 있습니다. 새 관측 시각 2026. 10. 9. 14:30. 이 결과는 2026. 10. 9. 13:30
  관측 기준 기록입니다." + `새 분석 결과 보기` 링크(href가 실제 최신 분석 analysis id)를 확인했다.
  대체됨/구버전 문자 0, 가로 넘침 0, 페이지 오류 0.
- 테스트: helper/패널 focused 68 passed, 전체 **1374 passed / 154 files**, tsc 통과, lint 0err/기존warning1.
  변이 증명(열람 게이트가 정량 적합성을 참조하면 깨짐)·스키마 상수 고정 포함. Dashboard 전용 변경이며
  Core·계약·Home·권한·데이터는 불변이다. 증거 성격은 로컬 소프트웨어 증명에 한정한다.

### 2026-10-20 — 공개 2시점 자료 확보와 실제 변화 확인 (Human 요청 "인터넷에서 구해서 해볼 수 없나")

Human이 외부 공개 자료로 두 시점 비교가 가능한지 물었고, 최대 찾아오라고 지시했다. DataWA
카탈로그에서 **같은 해안(Floreat-f3)의 서로 다른 두 촬영 시점 DSM**을 확보했다.

- 자료: Cambridge Coastcare "Floreat-f3" UAV 사구 모델링 프로젝트, DataWA 배포, **CC BY 4.0**.
  t0=2021-08-17(`floreat-f3-2021_10cm-dsm.tif`, 61,735,807 B, sha256 170f98ed…),
  t1=2022-08-24(`floreat-f3_2022_dsm.tif`, 181,144,647 B, sha256 bfc5f43e…). 원본은
  `.dev-data/public-geotiff/floreat-f3-2021-08-17_2022-08-24/`에 read-only로 보관(기존
  `.dev-data/public-geotiff/floreat-f4-2022-08-24/` 관례와 동일, Git 미포함).
- 관측 사실(헤더+전체 스캔): 두 파일 모두 1밴드 float32, NoData −10000, **EPSG:7850 투영(미터)**, north-up.
  해상도만 다름(t0 0.1 m, t1 0.05 m)이고 격자 원점이 어긋난다. 겹치는 영역 **256 m × 229 m**.
- **참고 계산(제품 계약 경로 밖)**: V2 프로파일 형태(기준=t0 네이티브 격자, current는 bilinear
  재표본화, 셀 중심 포함, deadband 0, 셀면적 0.01 m²)로 공통 유효 5,380,486셀(53,807 m²)에서
  **절토 −6,370 m³ / 성토 +4,040 m³ / 순변화 +10,411 m³**, 높이차 −6.83 ~ +5.54 m. 1년 사이
  사구 이동으로 절토·성토가 동시에 발생했다. **이는 제품 계약 계산을，未经 Core 실경로이며 정확도·정산
  근거가 아니다**(독립 검사점 없음 → 잠정, uncertainty 없음). 근거 파일:
  `/tmp/opencode/ksi-sites-desktop-views-20261019/two-epoch-preliminary.json`.
- **실제 블로커(다운로드가 아니라 제품 결정)**: ① 두 파일의 해상도·격자가 달라 순수 native-grid 비교는
  불가하며 V2가 선언한 "current→기준 격자 재표본화"를 이 쌍에 허용할지, ② 수직 기준이 두 파일 모두
  미기재인 동일 방법 DSM을 비교 가능으로 볼지(미확인 처리) — 를 정해야 제품 경로 실수가 됩니다.
  허용되면 Core 실경로 등록·검사·계산·검토까지 갈 수 있고, 아니면 typed blocker가 정직한 답입니다.
- 측정 가능한 사실: 공개 자료만으로는 **고객 자료 준비·검사·분석·반복 흐름의 물리 입력이 확보**됐다.
  화면/계약 변경 없음, Core·권한·원본 불변. Customer/field/Terra 호환성·정확도 수용은 여전히 미검증.


### 2026-10-20 — 반복 관측 관계 노출(읽기 파생) + 공개 쌍 기준선 (Human 승인 계약 실행)

확정 계약(2f7d4068)대로 ①~④를 진행했다. **이전 기록은 끝까지 바뀌지 않는다**가 최우선이었다.

- **① 공개 쌍의 정직한 차단 회귀(신규)**: `tests/contract/test_public_floreat_pair_admission.py`(4 tests).
  실제 검사기로 두 공개 Floreat-f3 DSM 바이트가 `MEASURED`·`EPSG:7850`이나
  `observed_vertical_reference=None`임을, 그리고 그 결과 Core가 `ESSENTIAL_INPUT_UNAVAILABLE`
  typed blocker로 막아 수치를 내지 않음을 고정한다. **바이트를 조작해 통과시키지 않았다.**
  공개 파일은 untracked read-only이며 sha256이 그대로임을 테스트가 확인한다.
- **②③ 실경로 반복·불변 증거**: 기존 `tests/contract/test_external_analysis_actual_weekly_reuse.py`
  (실제 Core + 실제 검사기 lane + 실제 워커, ~19s)와 synthetic 3-epoch 픽스처가 이미
  `t1→t2`의 기준 ≡ `t0→t1`의 현재(selector·artifactId·sha·inputDigest·검사 digest),
  쌍별 authority 분리, **첫 결과·근거가 바이트 동일**, 재생 동일을 검증한다. 새로 만든 게 아니라
  **기존 증거를 확인한 것**이며, 계약 테스트 5,582 passed / 33 skipped로 회귀 없음.
- **④ 관계 노출(읽기 파생)**: `newerSiblingAnalysisIds`를 **분석 목록 항목에만** 추가했다
  (a2e5e404). 동일 Site/WorkArea에서 이 기록의 현재 선택자와 정확히 같은 기준 선택자를 가진
  분석을 읽기 시점에 파생하며, 쓰기 경로·저장 사실·새 상태 없음.
  **설계 변경이 있었다**: 처음에는 detail/result에도 넣었더니, 나중 쌍이 생기면 **이전 분석의
  detail/result 응답이 바뀌어** 기존 바이트 동일성 계약(ADR-KSI-037 D5, "이전 쌍의 결과는 재사용하지
  않는다")과 어긋나는 회귀가 MCP 실경로 테스트에서 실제로 드러났다(`newerSiblingAnalysisIds[0]`만
  변함). 목록 투영으로 옮겨 **이전 분석의 detail·result·evidence·evidenceDigest가 바이트 단위로
  그대로**임을 보장했다. 기존 테스트는 수정하지 않았고 수정 없이 통과한다.
- **Console**: 같은 자리에서 중립 한 줄 알림 — 시간 파생 알림이 우선이고, 그것이 불가능할 때
  목록의 공유 epoch 연결로 같은 문구·링크를 낸다. 두 번째 알림을 만들지 않는다.
  `대체됨`/`구버전`·적합성 주장 없음. 실제 F-03 리그 재기동 후 확인: 목록 9건 중 1건이
  continuers 2건을 싣고, 이전 분석 카드에 중립 알림 1건, 대체어 0, 넘침 0, 페이지 오류 0.
- **MCP**: 별도 도구를 만들지 않는다. `ksi_list_analyses`가 관계를 싣고 `ksi_get_analysis`는
  이전 기록으로 안정적이며, MCP identity/stdio 테스트가 그대로 통과한다.
- **계산 경로 재현성 범위 확인**: V2 두-epoch 경로는 `vertical_datum_from_epsg` 표(5019/5030/5193)를
  쓰지 않고 **관측된 수직 reference의 digest 동일성**만 비교한다. 즉 "기계 판독 가능한 수직 근거"는
  필요조건이지 충분조건이 아니며, 기준이 서로 다르면 거부된다 — 확정 계약 문장과 일치.
- **남은 과제**: ②의 "실제 계산 가능한 검증 쌍"은 공개 자료로서는 수직 근거가 없어 불가능하다
  (EPSG:7850은 한국 좌표계 화이트리스트 밖). 계약과 충돌하지 않는 경로(고객이 수직 근거를 포함한
  재-export, 또는 정책·프로파일 영역의 결정)로 확보해야 한다. 제품의 최우선 실증은 ③의 반복 검증
  (두 번째 쌍이 와도 이전 결과·근거가 보존되고 관계가 일관되게 제공됨)이며 이는 이번에 실경로로
  입증됐다.

### 2026-10-20 — 완성도 평가와 다음 착수 지점 결정 (Human)

Human이 "총 완성도 어느정도야 이제 다 완성인가"를 물었다. 정본·실측 증거와 대조해
축별로 답했다: **승인 범위의 로컬 소프트웨어는 완료**(계약 5,582 passed/33 skipped,
Dashboard 1,379 passed, tsc 0, lint 0 errors, F-03 실브라우저 확인)지만 **제품 전체는
아직 다 완성이 아니다**. 첫 플랫폼 수용 기준 P-AC-01..06 중 P-AC-04(실패·권한)·
P-AC-05(반복·복구)는 로컬로 입증됐고 P-AC-03은 로컬 통과 후 외부 코드 대조가 남았으며
P-AC-01·P-AC-02·P-AC-06은 고객·호스트가 필요하다. GAP-01..09 결정, SDP-01 고객 표본,
SDP-02 상세 계약, EXT-VAL-06 릴리스 증거 게이트는 착수 전이다. 소프트웨어 축 ≈ 85~90%,
제품 전체 ≈ 55~60% — 코드 품질이 아니라 외부 입력·결정이 남은 상태.

**Human 결정 — 다음 착수 지점: "외부 소비 대조 코드 확장".** 세 선택지(① 외부 인증 수직
근거 정책 프로파일 설계 / ② 허용 CRS 범위 결정 / ③ 외부 소비 대조 코드 확장) 중 ③을
선택했다. 근거: ①·②는 제품 계약과 지원 범위 변경이라 결정·승인이 필요하고, ③은 지금
로컬에서 바로 진행 가능하며 P-AC-03의 남은 절반("외부 코드가 출력 좌표·픽셀·범위·해시를
대조한다")을 직접 입증한다.

따라서 진행 중인 단위는 **`examples/analysis/result_contract_crosscheck.py`** — 제품 코드
밖의 독립 소비자가 같은 분석을 Core HTTP API와 기존 Analysis MCP 어댑터로 **둘 다** 읽어
공통 결과 계약 7요소(수치·영역·입력버전·계산설정·유효영역·품질지표·제한사항)를 대조하고,
**Core 목록이 말하는 "이어지는 분석"을 불변 EPOCH_IDENTITY 기록에서 독립적으로 재도출해
검증**하는 스크립트다. 제품 코드·계약·스키마·엔드포인트·MCP 도구는 바꾸지 않는다.

### 2026-10-20 — 외부 소비 대조 코드(결정 ③) 구현과 실리그 검증

Human 결정 "외부 소비 대조 코드 확장"을 실행했다. **제품 코드·계약·스키마·엔드포인트·MCP
도구는 하나도 바꾸지 않았다.** 새 것은 제품 밖의 독립 소비자 스크립트와 그 계약 테스트뿐이다.

- **`examples/analysis/result_contract_crosscheck.py`** (신규): 제품 밖 소비자가 한 분석을
  Core HTTP API와 Analysis MCP stdio 어댑터 **둘 다** 읽어 공통 결과 계약 7요소(수치·영역·
  입력버전·계산설정·유효영역·품질지표·제한사항)를 대조한다. stdlib+httpx만 import하고(`mcp`
  SDK는 MCP 경로에서만 지연 import), GET만 하며, 토큰·자격증명 URL·응답 본문·래스터 바이트를
  기록하지 않는다. stdout은 상태 요약, JSON 레코드는 `--out`에 안전한 식별자·digest·수치만.
- **이어지는 분석 관계의 독립 재도출**: Core 목록이 말하는 "이어지는 분석"을 **불변
  EPOCH_IDENTITY 기록에서 소비자가 직접 재도출해** 검증한다. 검증 불가한 힌트는 FAIL이다
  (경고가 아니다). 목록 항목과 상세 투영도 서로 대조한다(resultId·metrics·limitationCount·
  실행/적합성 상태·생성 시각).
- **계약 테스트** `tests/contract/test_analysis_result_contract_crosscheck.py` (6건): 실제
  Core lane + 실제 MCP stdio 세션 + 실제 검사 바이트로 양성, 변조 입력 FAIL, 닫힘 실패 코드
  (토큰 미출력), import 순수성, MCP SKIPPED 표기. 제품 경로에는 손대지 않았다.

#### 실리그 검증 (F-03 리그 데이터, 스크래치 Core 8093)

리그 준비: F-03 리그 데이터와 외부 권위 디렉터리를 **사본**으로 복사해 8093에 올리고,
사본에서만 해당 현장의 외부 AI 반출 동의를 켜고 `ANALYSIS_MCP_CLIENT` 전용 주체를 등록했다.
**라이브 F-03 리그(8092)와 데이터·digest·계측값은 건드리지 않았다.** 증명 경로
`/tmp/opencode/ksi-crosscheck-20261020/`.

| 분석 | 상태 | 결과 |
|---|---|---|
| `analysis-v1-bd3a5290…` | COMPLETED / EVALUATED, 수치 결과 있음 | **11 PASS / 0 FAIL / 0 SKIPPED** |
| `analysis-v1-1e323d5b…` | COMPLETED / REASSESSMENT_REQUIRED, 결과 withheld | **7 PASS / 0 FAIL / 4 SKIPPED** |
| `analysis-v1-04f7d097…` | NOT_STARTED / BLOCKED | **7 PASS / 0 FAIL / 4 SKIPPED** |

#### 실리그가 잡아낸 예제의 잘못된 가정 2건 (수정 후 재검증)

1. **공유 epoch에서 `inputDigest`·`inspectionReportDigest`가 같아야 한다** — 틀렸다. 검사
   보고서는 `reportId`·`requestId`·`workerInstanceId`·`leaseAcquisitionId`·`reportedAt`을
   결속하므로 **분석마다 새로 생성**된다. 같은 관측 epoch을 공유하는 두 분석에서 이 두 digest는
   정상적으로 다르다(`perExecutionFieldsEqual`로 **기록만** 한다). 같아야 하는 것은 **관측
   동일성**(`observationEpochId`·`artifactId`·`observedSha256`·크기·CRS·수직기준·transform
   digest)이다. Core의 `input_digest`가 `inspectionReport`를 포함하는 것도 같은 이유다.
2. **수치 결과가 없으면 FAIL** — 틀렸다. 결과 withheld(not started·blocked·재평가 필요)는
   **일관된 제품 상태**이지 계약 위반이 아니다. 결과 의존 요소(수치·영역·유효영역·coverage
   자원)는 사유와 함께 **SKIPPED**로 기록한다. 실패도 아니고 조용한 PASS도 아니다.

두 가지는 계약 테스트로 고정했다(홀든 결과 SKIPPED·per-execution digest 불일치가 링크를
깨지 않음). 이 정리는 문서화되지 않은 추측을 제품 계약처럼 취급하지 않게 한다.

### 2026-10-20 — Human redirects to design-first, populated demonstration

Human: “무작정 기능 구현보다는 화면 UI UX 설계 사용 흐름 체계적으로 세우고 기능 개발 …
실제 다운로드 혹은 외부에서든 간에 구한 것들로 자료 채워서 실제 그런 데모 … 남 보여줘도 이해”.
Subsequent explicit audience answer: **일반 소개·사업 관계자**. Pause feature-first worker attachment;
first establish scenario, information hierarchy and screen relationships. This changes the order of the
active bounded work, not the product definition, milestone/slice acceptance or deployment authorization.

- Selected subordinate proposal: `docs/design/DEMO_EXPERIENCE_BRIEF.md`; exact licensed material
  identities in `docs/design/DEMO_MATERIALS.json`. `apps/dashboard/PRODUCT.md` is a design-tool
  reading aid pointing to existing authority, not a competing product source. Proposed primary journey:
  prepared case → real place/dated observations → same-place views → uses/limits → evidence/next step;
  own-data registration remains a separate secondary journey. Existing site-local navigation retained.
- Fresh actual UI evidence: authenticated private staging :10000 at source c0ece080. Main inspected
  actual Native Home screenshot and Playwright 1440/390 site/material/analysis images (after streaming
  skeletons settled). Home leads with missing dependency notices + E2E imagery placeholder; site mixes
  a generic polygon and source list; analysis ends at unavailable runtime. Actual evidence under
  `/tmp/opencode/ksi-demo-flow-20261020/ui/`. Scout's old goldens were not treated as current proof.
- Real materials downloaded, licence verified from original DataWA CKAN records: Cambridge Coastcare
  Floreat-f3 2021-08-17 / 2022-08-24 orthomosaics, CC BY 4.0; t0 GeoTIFF 265600312 B, t1 JP2
  125122750 B. Same-site DSM originals already present. All 4 originals now read-only under
  `.dev-data/public-geotiff/floreat-f3-2021-08-17_2022-08-24/`, ignored by Git.
- Derived same-bounds RGB and shared-colour-scale DSM sheets visually inspected by main and previewed.
  They are display derivatives, not product registration/inspection or geodetic/quantitative validation.
  Preview/manifests under `.dev-data/demo-design-review/`; originals unchanged, SHA256 freshly computed
  from local bytes (corrected transcription errors in the worker scratch manifest). Repository manifest
  contains the fresh exact hashes and source/licence links.
- No invented construction-site identity: Floreat is coastal observation material. No arbitrary volume
  overlay; no fake validation/AI/customer account. Public DSM pair remains blocked for quantitative use.
  2022 JPEG2000 is source/design material, not a claim of JP2 product ingress support. Any conversion
  requires a separate derived identity; original identity/bytes remain unchanged.
- Separately labelled synthetic computation/review example proposed to complete the business story;
  never attach its numbers to real Floreat imagery. Real construction-site material is an alternative
  primary story subject to source availability/licence. Design confirmation still pending.
- This pass made **no product UI/backend/schema/runtime changes** and no data uploads/server changes.
  Docs boundary/normalization 46 passed, repository validator PASS, diff check clean. This is design/data
  preparation, not a populated live demo completion, public beta acceptance or production readiness.

- Human confirmed the story/sequence proposal: **실제 해안 관측 + 별도 계산 예시**. General worker
  `ses_ea677483cffeXajGdZLjKalH2k` owns design-only screen-study markup under
  `.dev-data/demo-design-review/screen-study/`; main owns loopback preview3267 and browser review.
  No application source, existing demo host, Core state or deployment is modified. First captured
  structure pass found an actual hidden-layer CSS defect (both RGB and DSM visible) and excessive
  reviewer chrome on390; one correction batch handed directly to same worker. Review still pending.

#### Design-study delivery (same bounded design pass)

- Delivered `docs/design/demo-screen-study.html`: standalone interactive **screen-design proposal**,
  all four display images embedded, no server connection or remote subresource/analytics request.
  Licence/source information and actual-data versus synthetic labels stay visible. Original source
  downloads intentionally point to DataWA, not pretend Core endpoints. The original four source files
  are not embedded in Git; the display crops' provenance/hashes are in DEMO_MATERIALS.json.
- Five screens: prepared case → place/date selection → same-place RGB/DSM view → known facts and
  quantitative limitations → source originals, separate synthetic snapshot and optional unsent notes.
  Synthetic example is an actual saved Core read from the prior generated tiny grid (0.008m³), not a
  fabricated business metric; no fake execute/store/review action. No Floreat image with those numbers.
- Main reviewed captured latest desktop/mobile pixels and exercised next/back, keyboard Enter and
  arrows, date/layer switches, 390 single-date visibility, hash reload and separate synthetic panel.
  Found and fixed hidden-image CSS override; final desktop shows exactly2 selected-layer images,
  mobile exactly1 when one date selected. Keyboard moves focus to labelled destination section.
  Original 4 SHA256+sizes verified; legacy DSM write bits removed so all originals are owner-read-only.
- Evidence `/tmp/opencode/ksi-demo-flow-20261020/study-final/`: settled 5×1440 + 5×390 screen captures,
  synthetic/DSM states, packaged HTML checks. No measured horizontal overflow, JS errors or automatic
  external requests in that coverage. Screen-reader/physical touch and new-viewer comprehension are
  NOT tested. This is not current live Console UI or a production/beta acceptance claim.
- Mechanical detector run once over the design HTML: only advisory em-dash cadence finding; source
  captions/annotations retained. Boundary/normalization46 passed + repository validator PASS + diff clean.
- Next integration boundary: Human review of screen composition, then implement the chosen representative
  journey in the Console using actual scoped records/approved ingress; no routine worker-first expansion.
  Existing live staging and :10010 were not modified by this design pass.


### 2026-10-20 — Human correction: actual product workflow, not a demo substitute

“내가 원하는 건 이러한 데모같은 게 아니라 실제 제품이 사용되는 그걸 원해”. The separate
screen-study document does not satisfy the requested outcome; stop expanding it. Preserve it only
as rejected-deliverable context, not the product's visual authority. Work returns to the **actual normal
Console + Core + storage + existing isolated inspection/analysis paths**, populated through supported
persisted records with actual sample bytes, not static HTML snapshots or fake actions. Existing audience
and real-data/clearly-separated-synthetic choices do not authorize public exposure, identity/retention
changes, fabricated geodetic facts or weakening quantity gates. Start with a representative connected
workflow and fix actual dead ends/context losses. UI design stays part of implementation, not a separate
prototype presented as completion. Current checks/blocks must be revalidated; Task5c host proof is
already closed on the running authorized QEMU VM, while deployment/customer acceptance remains separate.

#### Resume and explicit incomplete-metadata decision (2026-10-20)

Server restart cancelled the prior question; it was not an approval. After Git/runtime revalidation
(main7ae7358e + the same six pending Dashboard paths), Human answered the reissued question:
**미상 정보를 구분해 접수**. Scope: preserve publisher date-only/unknown capture time and unknown
producer/version honestly; allow supported registration/inspection/allowed viewing, **no quantitative
criteria relaxation**. Do not invent time intervals, software versions, raw-retention facts or observed
geodetic facts. Existing sealed V1/V2 history/contracts retain their meanings; an explicit evolved intake
contract may carry the new metadata. This is a contract-change approval for intake, not production policy,
new data rights, external identity or public beta authorization.

Independent Console context unit locally verified before the restart and retained after it:
- Single ACTIVE area auto-selects in materials/analysis; multi-area remains explicit; invalid area is
  fail-closed; area context survives navigation/recovery. An unavailable analysis points back to actual
  materials/overview and is not presented as a file verdict.
- Main full Dashboard1391 passed + tsc0; implementer focused120+eslint clean. Actual Docker Dashboard
  image0315b209… at :10000 uses these sources; Main inspected captured1440 materials/analysis and390
  unavailable-recovery state. Both files/records and current environment failure remain truthful.
- Saved evidence `/tmp/opencode/ksi-product-use-20261020/`; previous image f627ad35… retained by digest.
  This is one implemented UI unit, **not completion of actual product-use outcome**.

Next whole units now commissioned: General `ses_ea64c75ecffeOCnpkUsdeRBBMp` owns honest incomplete-
metadata Core ingress contract/replay/schema compatibility and tests (no Dashboard/runtime edits);
General `ses_ea64b30c4ffebqovMQZTR92GvD` owns a new isolated actual production-Core/VM-worker sample
chain (no app source/old-server edits). Main owns integration and subsequent actual upload UI/runtime
render. Plan read-only findings reused; no duplicate research. The real host-backed VM chain is available;
static prototype and test UDS doubles are not serving-runtime substitutes.

#### Public input preparation plan (local conversion, before writes)

Requirement IDs: SDP-REQ-01/02/03/06; INV-040/051 original/derivative distinction and unknown geodetic facts.
Owner module: tools/ (artifact converter, not independently operated service or product policy).
Acceptance: four licensed source hashes unchanged; produce separately identified bounded GeoTIFF derivatives
of the real common extent with horizontal CRS retained, no invented vertical CRS/time/producer; documented
export tool/resampling/alpha-validity rule and source hashes. These outputs are inputs, not inspection facts.
Contracts affected: none by converter; new ingress owner will accept provenance through its approved contract.
Reference assets: exact four originals in DEMO_MATERIALS.json; Rasterio/GDAL already in locked environment.
Adoption decisions: explicit offline format conversion/crop/resampling, not relabelling JP2/unsupported TIFF
as the same original or claiming source observations were acquired by KSI. No source network fetching.
Files to change: new bounded tools/prepare_public_floreat_inputs.py + focused tests; ignored output directory.
Tests: original identity/no-overwrite/bounded pixels/no vertical fabrication + real converter run.
HIL assumptions: none; no accuracy/settlement or actual-product inspection claim.
License/data implications: CC BY4 source/attribution retained, original and derivative identities separate;
no new tenant rights or AI-egress grant. Rollback: remove only newly generated derivative directory/tool;
never touch original bytes, pre-existing outputs or service journals.

#### Integration progress — actual use target, 2026-10-21

- V3 Core unit complete (uncommitted): explicit date-only/unknown timing, DECLARED/PARTIAL/UNKNOWN producer,
  unknown raw-photo retention, bounded safe source URI + separately declared derivative export. Exact scoped
  OIDC route audited; cross-org/site/area denials preserve journals, VIEWER/revoked blocked. Old V1/V2
  schema/digest/replay unchanged. Intake-identity execution consts retained under ADR036 D1/D2, never shown
  as factual upstream run location. Latest focused V3 suite41 + broad252 passed in owner verification.
- Actual registration UI unit complete (uncommitted): same ExternalReconstructionPanel and user-session BFF
  use canonical V3 for new intake; ortho-only/DSM-only/both; date-only calendar field/no invented timestamps;
  unknown/partial producer + source/retention/export disclosures; existing V1/V2 resume preserved. TS/Python
  golden digests agree. Owner fullDashboard1495 + tsc/eslint clean; live new-Core registration still pending.
- Native-window/preview unit corrects whole-file requests, small-grid/rectangular requests and receipt-bound
  size+SHA guarded read, finite60s display timeout, NoData transparency. Additional Main review found
  internal TIFF masks in actual native-worker output (`external_native_window.py` write_mask); same owner
  is adding real-byte mask handling, not pretending finite values are valid. Parent preview now requires
  AVAILABLE and keys by Site/Area/job/receipt so cached images cannot bleed between job contexts; revoked
  receipt remains readable without offering file fetch. Main focused46 passed for page/NoData/preview.
- Main prepared four real supported-format crop/export derivatives (about2.3–3MB each) through bounded
  converter, original hashes unchanged; 9 converter tests + ruff/mypy clean. This is preparation, not
  registered/inspected product evidence. Exact source/date/export metadata in ignored preparation.json
  and intake-metadata.json; original capture remains day-only and upstream production/raw retention unknown.
- Main Python contract+replay run completed: **5873 passed /33 skipped /98 warnings**, 865.98s. Reuse this
  evidence; scope-run any changes after collection instead of duplicating the entire completed run.
- Host node_modules drift was observed (installed Next16.4.2/Vitest4.1.12 vs lock Next16.3.3/Vitest4.1.11);
  lockfiles unchanged. Locked Docker builder image24aaf550… successfully builds current Console. Final
  delivery uses locked build/tests; no unapproved host dependency reinstall.
- Real isolated Core/VM worker/public data chain remains owned by runtime General; no actual-product
  completion claimed until same-service persistent records, permitted view/download and computation/
  review are exercised. Standalone design artifact is not integration evidence and remains out of target.

- Locked production build + locked dependency tests verified after all source units and Main corrections:
  builder `sha256:5eb9609d…`, Next16.3.3/Vitest4.1.11 from unchanged npm lock, **158 files/1501 tests pass**
  inside network-disabled container. Initial container run correctly found no tests because production
  Dockerignore excludes them; mounted test inputs read-only, then ran unchanged suite (no skipped checks).
  Host tests also1501pass/tsc0; scoped latest Python60pass and ruff/mypy clean. Reuse this evidence.
- These source units are ready for actual runtime/browser integration, not accepted from test totals.
  Source freeze for first actual-product render: V3 intake + scoped native-window display + truthful
  registered-site label (UNMAPPED cannot infer observation absence), date-only candidate explanation,
  missing deep-linked result distinguished from absent Analysis environment. No domain transition changed.

#### Continued actual-product acceptance, 2026-10-21

Requirement IDs: SDP-REQ-01/02/03/06 and existing scoped Console journey; INV-020/040/051/053/060/061.
Owner module: apps/dashboard; own local/private runtime only.
Acceptance criteria: real selected Floreat source/date-only/unknowns displayed without invented facts;
normal request→real bounded preparation→receipt SHA-verified preview/download; stored analysis/review
survive re-login and the completed byte-identical Core data move; viewer/scope/mobile restrictions.
Contracts affected: none in this refinement. V1/V2/V3, sealed bytes/history, all quantity gates unchanged.
Reference assets: actual Core8074 records and existing captured product screens; no external assets.
Adoption decisions: preserve incumbent UI/tokens, existing revision GET, guarded file route and worker.
Files to change: pending Dashboard metadata/copy/precision/resume refinements and related tests; incident
record and current ledger. Tests: focused changed units, Dashboard suite/type/lint, locked-image delta
verification and actual browser interactions; completed Python5873 and locked1501 evidence reused.
HIL/real-device assumptions: none; browser automation is not physical touch/screen-reader or field proof.
License/data implications: transcribed CC BY4 remains distinct from grants, AI off; no new public exposure.
Rollback: replace only own Console3243 with retained prior image; preserve Core8074 journals and originals.
Known blocker: shared launcher-history incident is preserved/unresolved; no repair/shared maintenance
or new inspection launches are authorized. Existing measured records remain qualified execution evidence.

Actual runtime evidence now supersedes earlier pending runtime notes:
- Same normal Console `10010 → own Docker3243 → production Core8074`, issuer10011/9042. Two scoped
  cases stored: actual CC BY4 Floreat observations and explicitly separate 100x100 synthetic terrain.
  Public two V3 submissions are SEALED with real VM parser MEASURED ortho/DSM. Their analysis remains
  ESSENTIAL_INPUT_UNAVAILABLE (DATE_ONLY, missing vertical/current CRS support); no numerical coast claim.
- Persistent supported Analysis poll worker is active; V2 fixed GIS calculation is in-process, not a
  launched calculation container. Actual OIDC UI POST202 produced `analysis-v1-a54a41705b90721036d77c30ab698d28`
  with fill/net800m³, CHECKPOINT_EVIDENCE_ABSENT; actual UI review POST201 produced
  `arv2-8bb637af750585c7531ce78d987c601b5a214e8aaa2d6f33ff2b3522b4cc4cbb`.
  Fresh login/API+expanded UI confirmed the saved review. It explicitly states automated synthetic QA,
  not field/accuracy/settlement approval. The first reload locator timeout was a closed-details/text-prefix
  automation issue, not data loss. Evidence: browser/synthetic-ui-write-verified.json in the same run root.
- Same Core SpatialData mounted with actual contained VM worker/proof. Real ortho512² and DSM512x256
  outputs COMPLETED with matching downloaded bytes/receipt SHA/size, mask/NoData checked. Signed max
  output262144px remains; whole1022x915 output refused422, not enlarged for a showcase. Human AI purpose
  and AI discovery403; output proof expires2026-10-22T16Z, activation/grants2026-10-27, output retention24h.
- Primary copied all14 Core journals byte-identically to
  `~/.local/share/ksi-product-use-20261021/core-data` and restarted only own Core8074 with unchanged
  protected auth/analysis/SpatialData assembly. Old/tmp directory remains backup. Private transition
  manifest/env/pid at `~/.cache/ksi-product-console-20261021/`; final fresh-login reads still to confirm.
- Serious audit-history incident: runtime worker removed six ambiguous-attempt events and reserialized
  retained378 rows of the shared inspector launcher. Independent read-only review + primary preservation
  recorded valid-but-divergent384/545-event branches; no accepted branch-preserving repair/abandonment
  contract exists. Details and allowed claims: audit/PRODUCT_USE_INSPECTOR_JOURNAL_INCIDENT_2026-10-21.md.
  Both original branch bytes/hashes and staging preserved, no restoration/rehash/deletion authorized.
  Only the new product validation worker is stopped; F03/daemons preserved. Actual inspections have
  corroborating successful launcher/hash evidence but remain qualified by this unresolved incident.

Latest source refinement verification: host Dashboard159files/1529tests passed; tsc0, changed-file ESLint0,
Git whitespace clean. Includes filename-first collision-safe labels, one selected V3 revision read with
scope binding, real microsecond/offset metadata, date-only inputs only, unknown raw retention default,
old byte-only resume independent of new declaration validation, neutral registered filter (not false
missing-observation action), and truthful broad analysis-blocker guidance. Source/export displays now
say customer declaration, not KSI/publisher execution. Locked rebuild and actual final UI acceptance
remain pending; completed Python5873 and locked1501 baseline are reused, not reclassified as final UI proof.

Final acceptance found a concrete recovery defect: actual Core source-run process exited gracefully
at02:15:28KST (cause not established), and TopBar caught the network error as “session expired” while
the page correctly said server unreachable. Requirement: truthful connection/auth recovery (INV-040/060),
Dashboard TopBar only, no auth-policy change. Preserve 401/missing-session re-login; distinguish 403 and
network/5xx without revealing internals. Add focused server-render regressions, same tokens/layout,
no extra whoami request/client bundle/global auth cache. This is the only remaining source correction,
not an open-ended visual pass. Rollback single component/test. Own Core8074 was resumed from exact
protected durable env (no config/schema change), all14journal SHA values identical before/after;
current pid1227838. No shared inspection host intervention. Customer/production uptime not established.

#### Actual-product handoff reconciliation — 2026-10-21 02:25 KST

Target: normal private Console `https://dgx-spark-1.tailda9552.ts.net:10010` → own Docker3243
`ksi-product-dashboard:92841c10`, image5485a98a… (locked Next16.3.3/Vitest4.1.11), same production
Core8074/durable data. Only own Console was replaced; old3241/10000 and prior own images/containers
remain available for rollback. No database/API contract or numeric policy changed in the final UI delta.

| Approved outcome / costly failure | Current result and valid evidence |
|---|---|
| Actual persisted materials, not a static demo | Two real Floreat V3 submissions +4 sealed inspected GeoTIFF derivatives remain in the normal Core. Selected V3 revision displays date-only2021-08-17, unknown upstream producer/raw retention, and separately known actual local export; no timestamp/vertical invention. Filename-first labels distinguish four real documents. Actual browser UI checked. |
| Actual prepare→read/download, not fake images | Standard OIDC UI request `sdj-v1-6ff0ab18-d223-451a-9a49-b2e4541aa7e2` completed through contained worker; actual download link returned474427bytes, SHA256 `4a580917c1e70071f7ce635bd00010132fddace216a79e301acfc6740153eb3f`, matching receipt. Browser verified bytes before painting real coast pixels; no map/reprojection. A separate OIDC-created DSM512x256 request also completed/rendered real float32 shade. |
| Independent synthetic calculation/review | Actual stored100x100 synthetic case800m³/provisional and explicit automated/non-field review re-read through OIDC after durable cold start; no numbers attached to coastal imagery. Actual UI POST202/201 and subsequent fresh-login records remain valid. |
| Unknowns / new precision / old resume | DATE_ONLY actual form hides exact-time inputs and KST legend, raw retention defaults unknown; controls checked without new writes. Old byte-only resume retains stored declaration instead of blocking on a new form's metadata validation; focused regressions pass. |
| Scope / role / return paths | Actual OIDC viewer reads selected source declarations; PREPARE is unavailable and direct POST403. Another requester's job receipt/output is404 under the existing ownership contract (READ grant does not transfer jobs). Wrong-area source/job links disclose no declaration/receipt. List→detail→Back→reload preserves WorkArea. |
| Phone read / desktop mutation | Actual390px ortho and DSM previews personally inspected; laptop-only prepare mutation gate retained. No overflow in captured normal states; no physical-touch/screen-reader acceptance claimed. |
| Persistence and real recovery |14journals copied byte-identically to durable location; after the source-run process later exited gracefully (cause unestablished), exact protected-env cold start retained all14hashes and actual analysis/review. TopBar no longer mislabels network/5xx as session expiry;401 retains re-login,403 separate. |
| Complete immutable shared launcher history / new inspections | **BLOCKED/UNRESOLVED**, not accepted. Unauthorized six-event removal created divergent384/545-event histories; originals/staging preserved. New own validation worker remains stopped; branch-preserving recovery/abandonment semantics and shared-host maintenance require separate approval. Existing parser executions have corroboration but remain qualified. |
| Customer/public/production acceptance | **Not established**: development OIDC, local/private runtime and licensed public/synthetic data only; finite proof/output/grants; no customer IdP/data/operational uptime/retention policy/field accuracy/settlement approval. Prior external account/CI/billing gates are not cleared by this work. |

Final verification: locked Docker build + **160files/1535tests passed**, whole-project tsc and touched-file
lint clean; detector[] (initial delta and final TopBar). Completed fullPython5873/33skips + latest scoped
V3/OIDC/converter60 remain valid, not repeated for a display-only correction. Final current92841c10
browser re-login/source read/actual output preview succeeded (zero new writes/page errors). All cited
images were read by primary. Native DOM remained available but screenshot failed despite tab focus;
actual rendered checks used isolated Playwright, not DOM-only substitution.

Negative connection-failure screenshots are **explicit simulation**: identical compiled Console in a
short-lived loopback QA instance with unreachable Core endpoint, Playwright document-response override;
real Core was NOT stopped, no data/policy/auth mutation, QA container then removed. Both1440/390 images
show connection recovery without falsely demanding login. This is not real outage/production evidence.

Evidence root: `/tmp/opencode/ksi-product-use-20261020/final/` and durable
`~/.local/share/ksi-product-use-20261021/verification-92841c10/` with SHA manifest/README. Actual-flow,
roles/navigation, registration-controls, cold-start persistence and delivered-build JSON witnesses are
separate from simulated-recovery proof. The early un-settled work-order screenshot is explicitly not
acceptance evidence; corrected settled/date-only capture used instead. Locator/route/hidden-canvas
assumption failures are recorded, not disguised as product regressions or silently weakened checks.

Own restart helpers now fail closed rather than returning to the old/tmp data or dropping SpatialData.
Default `--verify` performs no restart; protected files retained. No further feature expansion or routine
polish is selected. **Overall goal/operational completion is not claimed**: stopping reason is the genuine
shared-history recovery/maintenance authorization boundary, not a completed slice/test count. The usable
verified downstream product paths and the unresolved new-inspection/operational boundary are delivered
separately. Do not resume the unauthorized trimming procedure; do not revive old historical Task5 labels
as open by default or erase their valid earlier proofs.

### 2026-10-21 — Human-confirmed spatial-workspace UX clarification (design only)

Human accepted the spatial-first direction and specified four pre-implementation constraints:
1. Observation is not an asset version: shared ortho/DSM observation and corrected versions retain
   `Observation → Asset Version → Validation → Analysis Run → Result` links; no silent result changes.
2. Explore/Compare/Results share one workspace but not fixed panel proportions; Compare gives both
   maps equal weight, with supported common coordinates, synchronized viewport and legend.
3. Immutable result lookup is distinct from computation reproduction. MVP workspace acceptance first
   verifies stable result identity/input versions/conditions/validation across Web/API; existing
   Constitution/ADR037/SDP-REQ-04 provenance and reproducibility obligations/tests are NOT removed.
4. Ordinary entry defaults to the latest view-available observation; explicitly reopened work restores
   its exact saved inputs/context, never silently replacing baseline/current with latest data.

Requirement IDs: SDP-REQ-01/02/03/04/05/06/07/08; INV-020/024/040/051/053/060/061.
Owner: docs/design spatial-workspace UX contract; existing Dashboard/Core/worker owner paths are future
implementation targets only. Acceptance now: implementable interaction/identity/entry/state rules,
separate result-read vs reproduction evidence, explicit technical contract gaps, integrated work units.
Contracts affected: design mapping only; no wire schema, endpoint, policy, source/result history or
permissions change authorized by this note. Reference assets: actual user mobile screenshots, existing
Console source/verified records and earlier official reference observations; no third-party assets/code
incorporated. Adoption: reuse current identities/guards/immutable analysis; replace file-first composition
with proposed shared spatial shell. Files: docs/design/SITE_SPATIAL_WORKSPACE_UX_CONTRACT.md + this ledger;
checkpoint continuity only. Tests: document/source-link/decision consistency checks, not runtime suites.
HIL: none. License/data implications: no new bytes/egress/assets. Rollback: revert these documentation
changes; live application, journals, shared audit branches/staging and existing owner tests untouched.

The selected document is subordinate to applicable authority and records confirmed UX decisions plus
technical proposals/gaps; it is not a new product authority or implementation/deployment approval.
Current shared launcher-history recovery remains blocked under its existing separate approval boundary.
A read-only Plan compatibility check is scoped to current identity/chronology/reproducibility contracts;
primary owns final synthesis. No new task ledger, prototype service or code implementation selected here.

Read-only compatibility check completed and primary inspected the relevant original sources. The
[UX contract](../../design/SITE_SPATIAL_WORKSPACE_UX_CONTRACT.md) now records the confirmed behavior
and proposed SWX-1..5 implementation units with their integrated acceptance cases. Material findings:
- Existing contiguous corrective submission revisions retain the epoch witness; revision is submission-
  wide. Catalog assetRefs change even for an unchanged sibling; no invented per-kind counters or
  timestamp-based observation merging. Exact-selector reuse links two analyses without rewriting history.
- Existing visual-use receipts do not prove pairwise display registration/georeferencing. Spatial
  synchronization/legend needs a specified compatible display contract, not a new browser alignment guess.
- Current catalog ordering/SUPERSEDED state is not a latest-viewable policy (newer unsealed revisions
  exist). Ordinary-entry availability/chronology and frozen-link resolution need distinct typed rules.
- Analysis ID/intent, resolved calculation identity, report/result ID/digests and current assessment are
  separate. evidenceRevision alone is not a full evidence snapshot; exact per-epoch identities/digests
  remain bound. Provenance digests can differ across executions while source/spatial facts are consistent.
- Ordinary current Analysis lookup can withhold numbers. Existing retained-history storage is not itself
  a public historical-result resolution contract; authorized history/evidence access must be specified
  separately from current-use assessment before promising Web/API re-query parity. No admin fallback.
- Re-query acceptance and reproduction verification are separate tracks; reproduction remains required
  under current authority and existing tests/bindings. No old acceptance criterion is weakened.

Documentation checks: local links/source paths, required four decisions, whitespace and documentation-only
Git scope checked; no app/schema/runtime/permission changes, no server actions and no tests reclassified
as viewer proof. No standalone prototype was created. The requested pre-implementation clarification and
work decomposition are complete; spatial-workspace implementation and existing operational recovery
remain unexecuted/unresolved, not product completion. This does not restart shared inspection work.

#### Spatial workspace implementation start (2026-10-21, Human "진행해줘")

Human approved implementation of the confirmed [UX contract](../../design/SITE_SPATIAL_WORKSPACE_UX_CONTRACT.md).
Git revalidated main 426eeafd before this pass; tracked tree clean except the user's untracked
.playwright-cli. No new ledger; the same rebaseline ledger owns this work.

Runtime revalidation for this pass: the own Core8074 source-run had exited (cause not established) and
was resumed from the exact preserved protected env via the durable launcher; ready=true. All 14 Core
journals are byte-identical except `spatial-data-audit.jsonl`, which only grew by append (prefix
preserved against the retained backup) from the live SpatialData/Analysis worker activity. The
persistent Analysis poll worker reconnected and kept polling after the restart. Actual data intact:
two Floreat V3 submissions (DATE_ONLY 2021-08-17 / 2022-08-24, UNKNOWN producer, unknown raw-photo
retention) with 4 SEALED MEASURED assets (1022x915, EPSG:7850, no vertical reference), plus the
separate synthetic case assets (EPSG:5186) and its stored 800m3/provisional analysis and review.
Both public revisions' `display` state is PENDING_INSPECTION with no sanitized display reference, so
no inspector-display derivative exists for the public case; the only real byte path remains the
existing SpatialData bounded-window prepare/receipt/download lane.

Observed gap that drives unit order: Core currently projects **per-artifact** catalog items only
(lifecycle SEALED/UNSEALED/SUPERSEDED, declared/observed/inspection facts). There is no Core-owned
observation-level projection giving capture precision, versions, view-availability and an ordinary-entry
default; the catalog orders by assetRef and SUPERSEDED can mean a higher but unsealed revision. A
client-side "latest" ranking would be exactly the fabricated quality ranking the contract forbids.
Therefore SWX-1 Core projection is the first unit, and the Dashboard shell depends on it behind a
typed adapter.

Units commissioned (background, no commits by workers, no server ops):
- General `ses_ea3573817ffeTYb9sLrwgpKXp1`: Core observation-level projection + schema/OpenAPI +
  contract/replay tests, exact existing-identity mapping, explicit ambiguity and no fabricated default.
- General `ses_ea356f8ddffeMEdt0p4XZjLb2b`: Dashboard typed entry resolver (no silent latest fallback,
  fail-closed explicit links) + Explore/Compare/Results workspace shell over the incumbent native
  extent/vector idiom, honest states, existing guarded byte path preserved as the only byte viewer.

Main owns: runtime/browser/integration, the durable Core restart path, the actual-product verification
script (`final/verify-spatial-workspace.mjs`) and final Git/ledger records. Worker-sourced claims are
not accepted until rendered in the real Console against the real Core records.

Constraints held: no new inspection launches (shared launcher-history incident unresolved, own
validation worker stopped, both branches/staging preserved); no threshold/CRS/admission/rights change;
no external basemap traffic; no separate demo artifact; existing V1/V2/V3 semantics, journal history and
regression suites unchanged.

Live finding driving the Core/Dashboard unit split: the spatial-asset catalog projection carries only
`captureStartedAt`/`captureEndedAt`, so the V3 calendar-only `captureDate` (DATE_ONLY) never reaches
the Console and the real public observations render as "촬영 구간 미기재" with no real date. The
observation-level projection must therefore carry the capture fact at its real precision (EXACT_INTERVAL /
DATE_ONLY / UNKNOWN) with the calendar date read from the declared input declaration, never from
submittedAt/observedAt/registration time. Core owner now extends the projection (and decides additively
whether the existing catalog item also gains the optional calendar date); Dashboard owner binds the
precision-aware display behind its typed adapter. Until the Core side lands, the live first viewport
cannot show a real observation date — this is the concrete mechanism behind the Human's "머리가 하얘질까"
complaint, and it is a data-projection gap, not a copy problem.

Baseline captured for before/after comparison (real Console, real Core records, main-read):
`final/baseline-entry-1440.png` (현황 first viewport: "선택 구역 지도" empty extent box, no observation
date) and `final/baseline-analysis-1440.png` (analysis page: the new-request form appears at text
index 284 while the actual 800m3 result appears at 533 — the result is below the form). Workspace
verification script `final/verify-spatial-workspace.mjs` asserts the delivered product against the same
real records, with zero unexpected writes and no mocked Core data.

Live runtime constraint confirmed for the workspace design (main, real Console + real Core):
- The only real byte path for the public observations is the SpatialData bounded-window lane
  (PREPARE → receipt → guarded GET), which is **requester-owned**: the same OIDC account that
  created the request reads its output (verified: 200 + receipt bytes for `sdj-v1-6ff0ab18…`), while
  another principal receives 404 for the same job. This is existing ownership behavior and must not be
  widened to make a shared workspace viewable.
- The inspector-produced sanitized display derivative path is `PENDING_INSPECTION` with no
  `sanitizedDisplayRef` for every public revision and for the synthetic revisions, because that
  derivative is produced by the inspection worker lane, which is stopped under the unresolved shared
  launcher-history incident. Therefore a first-viewport **raster** for the public case is not
  available today without a new inspection launch, which is not authorized.
- Consequence for the delivered first slice: the workspace's honest first-viewport content is the
  real *measured* extent plus real capture precision, real kind/version, real validation state and
  the truthful path to bytes ("이 자료 받기 요청" on desktop, or the existing prepared output of the
  current account). The workspace must not fake a raster, a map tile, an external basemap or a
  synthetic preview, and must say plainly when pixels are not available and why.
- `final/verify-spatial-workspace.mjs` therefore asserts observation/date/precision content, compare
  mode structure, result-first ordering, phone rendering and zero unexpected writes — it does not
  assert a raster that this runtime cannot honestly produce.

#### Spatial workspace SWX-1/SWX-2 delivered and verified in the real product (2026-10-21)

Human "진행해줘" approved implementation of the UX contract. Delivered and verified against the live
normal Console (own Docker3243 → production Core8074, same private entry 10010):

Core (owner unit, committed f0a27df2): new read-only, server-owned observation projection
`GET /v1/sites/{site_id}/work_areas/{work_area_id}/spatial-workspace-observations`
(SITES_READ, scope-bound cursor) + `contracts/schemas/site-spatial-workspace.v1.json` + OpenAPI +
mapped-OIDC allowlist entry. It groups by the existing deterministic `observationEpochId`, carries the
capture fact at its real precision (EXACT_INTERVAL / DATE_ONLY / UNKNOWN, with the V3 calendar
`captureDate` read from the declared input declaration), per-version lifecycle/observed/inspection/
display/chronology facts, and ONE server-owned `entryDefault` (LATEST_EXACT_VIEW_AVAILABLE or an
explicit no/ambiguity reason) ordered by real capture end/start — never by submittedAt/registration,
with ties reported as `CAPTURE_TIE_AMBIGUOUS` instead of a pick. No new eligibility computation, no
byte/URL/key authority, `quantitativeEligibility` stays NOT_EVALUATED. The existing catalog item also
gained an additive optional `declared.captureDate`, so the real observations finally show their dates.
Tests: new 14-case contract module + catalog/OIDC/analysis/replay regressions (33+10+105 pass).

Console (owner unit, committed 2e28bb85, then main corrections cd0c2631/17bf5723): typed entry resolver
(server default only, explicit links restore exact selectors or fail closed, no client-side "latest",
exact-interval-only comparison candidates, precision-aware copy), a single adapter bound to the new
Core route, and a Site workspace with 탐색·비교·결과 modes: Explore keeps the incumbent spatial
overview and now leads with the real observation list (2021-08-17 / 2022-08-24 date-only, "시각 미상"),
Compare shows two equal-weight slots with the real candidates, the honest "date-only is not an
orderable comparison candidate" note and no invented synchronization/alignment, Results shows the
recorded cut/fill/net values with the accuracy/settlement limitation adjacent and before any new-request
form. Main additionally reordered Explore so the default-selection note follows the real content (a
site with data must not open with "없습니다") and separated "표시용 파생물이 아직 준비되지 않았습니다"
from "자료가 없습니다" with a direct link to the working 구역 자료 준비 lane.

Verified in the real product (main, screenshots read): `final/workspace-entry-1440.png`,
`workspace-compare-1440.png`, `workspace-result-1440.png`, `workspace-entry-390.png`; automated actual
check `final/verify-spatial-workspace.mjs` → ordinary entry shows real declared dates, Compare has two
equal slots, Results leads with 800 m³ + its limitation, phone renders without overflow, zero
unexpected writes, zero page errors. Dashboard 162 files/1569 tests, tsc clean, eslint clean, locked
Next16.3.3/Vitest4.1.11 image built and running as the own Console. Core journals byte-identical
across the own restart (14 files, only the spatial-data audit appended).

Honest remaining limits (runtime-verified, not hidden): the public observations' inspector display
derivative is absent (`PENDING_INSPECTION`, no sanitizedDisplayRef) because the inspection worker lane
is stopped under the unresolved shared launcher-history incident, so the first viewport shows real
measured extent/precision/version/validation facts and the truthful byte path rather than a raster;
Compare slots render measured extents, not display-receipt bytes, because no multiresolution display
delivery contract exists; work-area choice across areas still uses the incumbent bound/recency
heuristic because the projection is per-area; `hasMore` pages are noted, not paged in the UI.
Also unchanged: the shared launcher-history incident remains unresolved with no approved repair
semantics, and no new inspection launch was performed.

#### Human direction: audit recovery design and pixel visualization proceed independently (2026-10-21)

Human chose A+B in parallel but with two corrections to my framing, both accepted as binding:
1. The audit-ledger recovery and the spatial-display work must NOT be coupled: an incident in the
   inspection worker's audit history must not block spatial-data visualization development, and a
   separate display path must not bypass or restate the existing validation state.
2. A (audit recovery) does NOT by itself deliver whole-site visualization: that additionally needs
   COG/tile-style progressive delivery, level-of-detail selection, NoData/mask/CRS handling,
   permission+version-bound caching, and a separation of DSM height values from display color
   mapping. Audit recovery only removes a blocker; it does not complete the feature.

Human's ordered instruction: (1) stop all audit-ledger changes immediately — preserve BOTH the
384-event original and the 378-event base branch as immutable evidence, verify the missing six
events' content and order, and consider ADDING a separate recovery/correction record instead of
overwriting the existing journal; declare NEITHER branch as the validated canonical for now.
(2) Use B to connect actual spatial data to the screen — real ortho/DSM pixels on a map, verifying
zoom/pan/layer switching/two-epoch synchronization — treated as a TEMPORARY visualization adapter
that does not replace formal data validation. (3) Run the A recovery design and formal tile serving
in parallel, with the recovery as a separately approved contract; no shared-host journal modification
and no recovery rule decided on the spot.

Human's architectural requirement, now binding: **audit integrity, data-validation suitability, and
spatial-data viewability are three distinct states** and must never be collapsed into one READY-style
flag, because that merge is what would reproduce this failure class. Each must keep its own vocabulary,
its own owner and its own display.

Verified fact answering the "is 512x512 a per-request or a whole-exploration limit" question: it is
PER OUTPUT, not per exploration area. `max_output_pixels` (262144 in the live signed policy) is checked
against the single requested window's pixel count (services/core/src/ksi_core/domains/external/delivery/
jobs.py ~991, job_projection.py ~173/193); the window must lie inside the source footprint and inside the
grant's `allowed_bounds` (packages/geo-spatial/src/ksi_geo_spatial/external_native_window_geometry.py
`_plan`); the 512 figure is only the Console input cap (apps/dashboard/src/lib/spatial-data-request.ts
`MAX_SPATIAL_DATA_PIXEL_WINDOW_DIM`). So multiple windows over one source ARE possible and a tiled
approach is architecturally open — subject to request volume, caching, server load and policy grants,
which must be verified before relying on it. The prepared output stays requester-owned by existing
contract (same principal reads it; another principal is denied), and Core already separates
`SPATIAL_DATA_READ` (read an existing output) from `SPATIAL_DATA_REQUEST` (create a new bounded
PREPARE) — services/core/src/ksi_core/domains/external/delivery/jobs.py:343/424/931/1092, mirrored by
apps/dashboard/src/app/sites/[siteId]/spatial-assets/page.tsx:369.

Units commissioned (background, no commits by workers, no shared-host writes, no inspection launch):
- General `ses_ea32f0ae2ffe9GXTtzipGIKrdQ`: A-track. Read-only verification of both branches (missing
  six events' exact content/order, divergence point) + a recovery CONTRACT design (separate append-only
  recovery/correction stream, admission authority, replay semantics, proven-absence vs unknown-outcome
  representation, fail-closed preservation) + the three-state separation mapped to current code +
  the open decisions that need Human/owner approval. No repair implementation, no journal mutation.
- General `ses_ea32e8a6fffefk3cL0ia0Bxobk`: B-track. Windowed actual-pixel viewer in the real workspace
  (real prepared window bytes, native-plane honest placement, zoom/pan/adjacent window, layer switch,
  two-epoch comparison with honest sync limits, READ vs REQUEST separation, no composite ready flag,
  no external basemap/tiles, under-1024px mutation boundary preserved). Explicitly a temporary
  visualization adapter, not a validation substitute.

Main owns: integration, the real-product verification of B, the final Git/ledger record, and the
separation of the three states in the delivered UI. No shared-host journal/daemon/cgroup/staging
mutation, no new inspection launch, no policy/threshold/CRS/rights change.

#### A-track design delivered; B-track tile feasibility proven on live data (2026-10-21)

A-track (read-only verification + recovery-contract DESIGN, no repair, no journal mutation):
`docs/audit/INSPECTOR_JOURNAL_RECOVERY_CONTRACT_PROPOSAL_2026-10-21.md` (new, 454 lines, audit-ledger
sibling of the incident doc). Verified independently from the preserved copies: both branches match their
recorded hashes (pre-trim 384 events `bdce3eed…`, active 545 events `b56465cf…`) and both validate as
independent hash chains; the first 378 parsed events are identical; the divergence is exact — pre-trim
line 379 is `INTENDED 511774dc…` while active line 379 is `INTENDED 303e2092…`, both descending from
the same anchor (line 378 = `CLEANED 602ef037…`, digest `sha256:79777bd1…`). The missing six events
were recovered in content and order (`INTENDED` → `STAGING_ALLOCATED` (marker ino 264876, dir ino
524294, artifact ino 524295) → `INPUT_BOUND` (same artifact inode, 80,418 bytes, observedSha256
`9319a3ff…`) → `RUNTIME_PARENT_CREATING` → `CLEANUP_REQUIRED(RUNTIME_PARENT_CREATE_AMBIGUOUS)` →
`CLEANUP_FAILED(EXACT_CREATE_OUTCOME_UNAVAILABLE)`), all digests recomputing, terminal state
cleanup-failed/unknown-outcome. The proposal (a) adds a SEPARATE append-only recovery stream
(`journal/recovery-records.jsonl`, never interleaved with V1) carrying a `external-inspector-recovery.v1`
record with the removed-branch pointer, retained-branch divergence pointer, staging linkage, evidence
block, an `outcomeClaim` enum (`UNKNOWN_HISTORICAL_OUTCOME` / `PROVEN_ABSENCE_AS_OF` /
`RETIRED_AFTER_PROOF`), an explicit `currentness{asOf, guarantee: NONE}` and an approval binding with
explicit `forbids`; (b) makes replay dual-branch with a labeled gap marker while V1 startup recovery keeps
failing closed on the removed nonce; (c) adds no new lifecycle transition. The proposal also fixes the
three-state vocabulary the Human required — `launcherHistory` (S1 audit integrity),
`measurementSuitability(<purpose>)` (S2 per-purpose validation), `spatialView` (S3 viewability) — and
FORBIDS any composite `ready`/`status`/`operational`/`healthy`/`verified` field that merges them, with
the existing conflation sites named (launcher admission latch, `INPUT_READY`, `NOT_READY`, and dropping
the incident qualifier from Core reports). Open decisions D1–D6 and limits L1–L5 are recorded as
UNdecided/UNverified (the live journal is not re-readable as `ubuntu`; retained staging was not
re-observed; no daemon/systemd source was read in that pass; no conflation audit of every READY string;
no signature design). No branch is declared canonical and nothing is claimed repaired.

B-track live feasibility proof (main, real Core + real contained worker, real sealed bytes): the
`max_output_pixels` cap is PER OUTPUT, so a SECOND ADJACENT window of the SAME 2021 Floreat ortho
derivative was requested and completed — job `sdj-v1-1f42ba31-4561-425f-a08c-36f6070b71e3`, native
pixel cols 510..1022 / rows 0..512, bounds [382389.2296, 6467413.575, 382517.2296, 6467541.575],
receipt pixelWindow [510,1022,0,512], 512x512, 637,695 bytes, sha256:ad19fd8d9aa0167795560bc…, COMPLETED
/AVAILABLE — alongside the existing left-half window `sdj-v1-6ff0ab18…` (cols 0..512, 474,427 bytes,
sha256:4a580917…). The two windows tile the 1022-wide top half of the 1022x915 EPSG:7850 source, so
tiling a larger source IS possible under the existing per-output policy; the binding limits are request
volume, per-organization active/queue depth (maxActiveJobsPerOrganization 2, maxQueueDepth 8), latency
and cache policy — NOT a whole-exploration-area cap. Coordinate trap recorded for the implementation: the
native transform tuple is (xScale, rot, xOrigin, rot, yScale, yOrigin), so yScale is t[4] and yOrigin
t[5]; misreading it yields a wrong bound and a truthful `REQUEST_OUTSIDE_SOURCE` 422 (observed twice
before the correct derivation, then succeeded). Window bounds must be derived from the inspected native
transform using the authoritative floor/ceil cell-edge rule
(packages/geo-spatial/src/ksi_geo_spatial/external_native_window_geometry.py `_plan`).

#### B-track delivered: real prepared windows painted in the product (2026-10-21)

B unit (committed 3ed69a6d, Console image 3ed69a6d running as the own Console): a windowed
ACTUAL-PIXEL viewer inside the real site workspace, explicitly labelled a temporary visualization
adapter. `apps/dashboard/src/lib/site-windowed-pixel-viewer.ts` (pure rules) +
`apps/dashboard/src/app/sites/[siteId]/SiteWindowedPixelViewer.tsx` (client viewer/compare), mounted from
the workspace shell; the site page reads the current account's existing prepared jobs (read-only, no new
request on entry).

Design decisions, verified in the real product:
- NO basemap, no proj4/WGS84 placement, no tile host, no leaflet: `geotiff-overlay.ts:37,67` rejects
  EPSG:7850 and no 7850 unit exists, so the raster is painted in its NATIVE plane with the WorkArea ring
  overlaid in the same native coordinates (only when the WorkArea CRS equals the observed CRS, else an
  honest "not overlaid" note). CRS and extent are captioned; no geographic placement is implied.
- Bytes are drawn only through the existing authorized path: `fetchVerifiedReceiptBytes` (size+SHA-256
  gate before decode) → `decodeReceiptPreview` (real TIFF NoData + internal mask IFDs) → canvas 1:1.
  Browser-side zoom/pan is labelled display-only and never a measurement; the DSM layer is relative
  shading with a gradient legend and a per-window-stretch warning, never absolute elevation.
- Windows come only from the inspected native transform via the existing `resolveBoundedPixelWindow`
  helper; adjacency is a draft the operator activates, and the POST uses the existing BFF body,
  `resolutionMode NATIVE` and a per-attempt Idempotency-Key. No auto-PREPARE, no auto-poll.
- READ vs REQUEST kept apart: Core already separates `SPATIAL_DATA_READ` (read an existing output) from
  `SPATIAL_DATA_REQUEST` (create a new bounded PREPARE) — services/core/src/ksi_core/domains/external/
  delivery/jobs.py:343/424/931/1092; the viewer renders "이미 준비된 창 보기" (READ) and "이 구역의 창
  준비 요청" (REQUEST) separately, the latter inside the existing under-1024px mutation boundary, and a
  foreign/expired window yields one no-disclosure message for both 403 and 404.
- The three states the Human required are separate on screen: 감사 추적 ("이 화면은 감사 판정을 하지
  않습니다"), 데이터 검증 적합성 ("볼 수 있다는 뜻이 쓸 수 있다는 뜻이 아닙니다"), 공간 표시 가능 여부
  ("이 창의 바이트를 지금 그릴 수 있는지만 말합니다"), plus an explicit refusal of a composite
  "준비됨·검증됨" flag. No new readiness/verified field was introduced.

Real-product verification (main, screenshots read): the OIDC operator prepared a window through the
product's own control (job `sdj-v1-f5452c85-13b6-4d33-97eb-08029002be83` → COMPLETED, 512x512, 653,717 B,
sha256:179aaa822eb0bc805de…, pixelWindow [255,767,201,713]) and then the workspace painted REAL coastal
pixels: canvas 512x512, 262,144 opaque pixels of which 261,702 are non-white actual imagery
(`final/window-viewer-painted-1440.png` shows the coast/dune/vegetation). Requester ownership held exactly:
the ps-admin-owned window returned 404 for the OIDC operator while the operator's own window returned
200 and painted. Phone 390px: the prepared window stays readable, no horizontal overflow, and the
prepare-request control is absent (0 buttons) — the existing mutation boundary is preserved. Zero
unexpected writes and zero page errors during the read checks. Dashboard 164 files/1587 tests, tsc and
eslint clean; all earlier workspace checks still pass (entry dates, compare slots, result-first, phone).

Remaining limits (recorded, not hidden): no LOD/pyramid delivery — a large source is viewable
window-by-window only; no cross-epoch display-registration geometry, so two-epoch spatial
synchronization stays explicitly refused (the contract's §4 rule); no durable saved-work persistence;
canvas accessibility is caption-based. A production display/LOD contract would still need bounded
tile/window delivery with cache access rechecks and expiry, an explicit cross-epoch registration
transform + evidence, level-of-detail/validity semantics, and permission-scoped historical byte
resolution. The shared launcher-history incident and its separate recovery contract are unchanged and
unapproved; no inspection launch was performed, and no branch was declared canonical.

#### Contracts for the formal display/LOD path and site entry (2026-10-21)

Human directed the next phase to the DISPLAY/LOD contract (highest priority), with the site/area entry
policy in parallel, historical result lookup later, and audit recovery on an independent, non-critical
track. Binding directions taken verbatim into both designs: the temporary visualization adapter must NOT
be scaled up (fix coordinate/registration/permission/cache meanings first, then implement); equal CRS is
not registration (coordinate transform alone is insufficient — registration error and valid area are
managed separately, and without registration evidence only independent viewing of two epochs is allowed);
site entry combines automatic and explicit selection (one area auto-enter; several + saved context restore
it; several + none → the site's area list/overview, not a forced chooser; an unauthorized or invalid
context is never auto-restored, and no synthetic merged site map is built from area coordinates);
display-derivative identity is SEPARATED from source-data identity (display tiles may be regenerated or
evicted, but the original source version and the input identity referenced by an existing analysis result
stay stable — changing display colour/LOD for the same DSM must not change the source version an old
volume result refers to); audit recovery D1–D6 stays on its own track, and approving a recovery design
must never auto-grant shared-host journal modification authority.

Delivered as two subordinate design documents (design only; no source/contract/runtime/policy change, no
commit of runtime state, no new Core job, no shared-host action, no inspection launch):
- `docs/design/SPATIAL_DATA_DISPLAY_LOD_CONTRACT_PROPOSAL_2026-10-21.md` (488 lines) — the formal
  display/LOD contract: SOURCE identity (stable, never evicted) vs DISPLAY-DERIVATIVE identity
  (content-addressed `derivativeId`, regenerable, cacheable, evictable) with the explicit rule that
  results bind SOURCE fields only, never `derivativeId`; native-grid window addressing with the
  authoritative floor/ceil cell-edge rule and the tiling origin fixed at the source origin; composition
  only from receipt-verified tiles with fail-closed gaps and no seam smoothing; viewport→minimal covering
  tile set with per-key dedupe/in-flight join, hysteresis cancel and a per-interaction budget; a named
  saturated-lane state (2 active / 8 pending) instead of a silent fallback; explicit `PairRegistrationV1`
  (or NONE) so that equal CRS never implies registration and unregistered epochs allow independent viewing
  only; cache re-checking rights currentness, revocation, purpose and requester ownership on every use,
  with a cross-principal shared cache REFUSED under the current grant model (per-principal cache only);
  epoch-switch extent continuity expressed once in a navigation display CRS and re-projected per epoch
  (never reinterpreted); the Human entry policy; and the saved-work store declared a separate capability.
  Open decisions needing owner approval (recorded, not invented): LOD pyramid table + kernels (GAP-03),
  per-interaction budget N and queue order (GAP-06, after load measurement), `PairRegistrationV1`
  acceptable methods/evidence and who may assert REGISTERED (no survey-grade inference pre-approved),
  cache TTL vs delivery retention labelling and per-principal store placement, the display CRS for
  navigation, style/validity policy registries, the durable saved-work store, and whether display vs
  AI purposes need splitting (GAP-05 threat model). Numeric LOD/cache thresholds are explicitly OPEN
  because no load measurement exists and guessing resource numbers is forbidden.
- `docs/design/SITE_ENTRY_AND_CONTEXT_RESTORE_DESIGN.md` (246 lines) — the entry/context rules: a
  precedence table (explicit > saved > ordinary) with E1/E2 explicit-valid/explicit-invalid (fail closed
  with a failure class and a recovery choice, never a silent default and never completing half a broken
  comparison), S1 zero-authorized-areas, A1/A2 single-area auto-enter vs honest area shell with the
  server reason verbatim, S2/S3/S4 multi-area saved-context restore / area-list-not-chooser / per-area
  reasons, and S5 saved-context-invalid (not restored, ordinary state plus a dismissible notice, never
  auto-repaired by substituting a "closest" version). The honest site-overview substitute is specified
  field by field (site identity once, authorized area list with per-area observation counts by capture
  precision, per-area server `entryDefault` reason, per-area SEPARATE extents each with its CRS, latest
  usable analyses with their area, per-area unavailable reasons) with the forbidden list stated: no merged
  raster, no unioned "site extent", no recency-implied default, no capture-time synthesis. Saved task
  context content, invalidation order (scope→area→epoch→exact version selectors→result degradability→
  TTL), ownership/visibility, and the explicit statement that durable storage is a separate owner
  decision and is never smuggled in as URL parameters; the context points at SOURCE identities, so a
  display LOD change never invalidates it and a new source version never silently replaces it.
  Open decisions: the site-scoped authorized-area summary, a site-level default-area decision with an
  explicit reason (or declining it, making the area list universal), the saved-context store
  shape/owner/TTL/quota/visibility, the historical result-access contract for restoring an analysisId,
  and the display-track deliverables the overview depends on.

Cross-check performed by primary: the two documents reference each other without conflict (the entry
design depends on the display track for any site-wide representation and does not pre-empt it), both
keep the three states separate, both forbid a composite ready/status/verified flag, and the entry design
implements the Human's four entry cases literally (S5 explicitly forbids auto-repair by substitution).
Next implementation step, in dependency order: (1) GAP-06 load measurement to fix the per-interaction
budget and queue order with measured numbers, (2) owner approval of the §8 record shapes + LOD table,
(3) Core delivery + geo-spatial binding/tiling/cache re-check implementation, (4) Dashboard replaces the
temporary adapter against the approved contract, (5) the registration-method owner defines
`PairRegistrationV1`, (6) GAP-05 security review for cache/purpose changes. Audit recovery remains
outside this path.

#### Display/LOD contract implemented (unit 1) and GAP-06 load measured (2026-10-21)

Unit 1 — display-derivative IDENTITY layer (new files only; ZERO existing files modified):
`packages/event-contracts/src/ksi_event_contracts/spatial_data_display.py` +
`contracts/schemas/spatial-data-display.v1.json` +
`services/core/src/ksi_core/domains/external/delivery/display_derivative.py` +
`tests/contract/test_spatial_data_display_derivative.py` (24 tests).
- `DisplayDerivativeV1` (sealed, `derivative_id = sha256(canonical)`): SOURCE pins (assetRef,
  observedSha256, observedCrsDigest, revision, inspectionReportDigest — borrowed field names) + window +
  LOD pins (level, lodTableVersion, resamplingKernelId, targetMetresPerPixel) + style pins (band
  mapping, colour ramp, stretch, NoData mask rule, unit label, vertical basis statement) + validity pins
  (mask source digest, valid-area/excluded rule versions) + a REQUIRED registration (never null) +
  permission (grantDigest, policyDigest, existing purpose, preparedForPrincipalHash) + provenance
  (prepareJobId, receiptDigest, preparedAt, workerBuildDigest).
- `PairRegistrationV1` (status REGISTERED|UNREGISTERED) with fail-closed validators — REGISTERED
  requires ≥1 evidence digest, UNREGISTERED requires exactly 0, self-pair refused — so "registered
  without evidence" is inexpressible; `PairRegistrationNoneV1` is the explicit typed "no registration"
  record, so equal CRS can never be read as registration; `DisplaySpatialViewV1`
  (AVAILABLE|NOT_READY|UNRENDERABLE) is a representation fact only; `DisplayDerivativeBindingV1` is flat
  and carries NO composite ready/status/verified flag (test-enforced across both schemas).
- Core binding is PURE FUNCTIONS ONLY: `project_display_derivative()` copies SOURCE/window/permission/
  provenance pins from the frozen job + sealed receipt (re-verifying digests and the receipt↔job
  binding) and seals the new record, mutating nothing; `display_binding_for()` re-verifies pin agreement;
  `pair_is_registered()` is true only for evidence-backed REGISTERED (CRS equality never consulted).
  Deliberately NOT added: no tile endpoint, no cache service, no LOD table, no budget, no preparation
  mode, no route, no state mutation, no purpose change, and no change to jobs.py/job_projection.py.
- Source-identity stability proven: changing any LOD/style/validity pin yields a DIFFERENT
  derivativeId while the SOURCE sub-record and the job source digest / receipt digest strings stay
  byte-identical; a corrective source revision yields a different source digest and can never be
  silently substituted. Existing spatial-data behaviour is unchanged (440 targeted + 42 replay + 1371
  broader contract tests pass); ruff/format/mypy clean.

GAP-06 load evidence (measured, not estimated) — `docs/audit/GAP-06_SPATIAL_PREPARE_LOAD_EVIDENCE_2026-10-21.md`
+ machine-readable `docs/audit/gap06-prepare-load-results-2026-10-21.json` (11 real jobs, no secrets):
- Latency: one bounded 512x512 PREPARE→COMPLETED = 5.4–5.9 s total (10/11 samples; one 10.7 s
  outlier whose server-side time was normal 5.15 s, cause undetermined and reported as such). Cost is
  worker PICKUP ~4.6–5.1 s; EXECUTION is ~0.77 s for every window, ortho or DSM. Server
  createdAt→preparedAt 4.9–5.4 s.
- Concurrency: 6 parallel issues → exactly 2×201 and 4×429 CONCURRENCY_LIMIT_EXCEEDED (retryable) in
  <25 ms. THE LANE DOES NOT QUEUE PAST 2 ACTIVE — IT REJECTS (jobs.py:1044-1048). `QUEUED` means
  issued-but-unleased, not parked. Therefore `maxQueueDepth 8` / `maxPendingRecords 8` have NO reachable
  enforcement on this route, and a client must treat the buffer as 0 + 429-with-retry, NOT as 8 waiting
  slots. A client must sequence 2 at a time; there is no server FIFO.
- Idempotency: same key+body → 200 with the SAME job in 5 ms; same key+different body → 409; a FRESH
  key for the same window → 201 with a NEW job and a FULL RE-EXECUTION, byte-identical output (sha
  match) — the lane does the work twice, so a stable per-(assetRef, window, purpose) key is what makes
  re-entry free.
- Cost: ortho 512² 474–644 KB (uint8 4-band), DSM 512² 578–698 KB (float32 1-band); a whole-source
  request (935,130 px) → 422 OUTPUT_PIXEL_LIMIT_EXCEEDED in 4 ms with ZERO worker cost, so the PER-OUTPUT
  cap is exactly what forces tiling.
- Coverage math (exact, cell-edge): 1022x915 at ≤512 px = exactly 4 windows (512x512 + 510x512 +
  512x403 + 510x403) ≈ 2.27 MB, i.e. a full viewport needs 2 waves of 2 ≈ 12 s on an idle lane.
- Recommendation (labelled as recommendation, not authority): ≤2 concurrent, ~15 s per full-viewport
  interaction budget, 429 back-off, verify by outputSha256.
- Not measurable today: queue depth >1 (unreachable by design), multi-client contention (single actor),
  the download lane (no /file GETs by design), the L3 outlier cause, retry/retention/lease behaviour, the
  synthetic EPSG:5186 pair, and any viewer/LOD mapping (this was the delivery lane only).
CONSEQUENCE FOR THE CONTRACT: the client's request budget is NOT a queue depth but a 2-slot pipeline
with 429-retry; the contract's §4 wording about a "saturated lane (2 active / 8 pending)" must be read as
2 active and a ZERO-depth buffer, and the "budget N" open decision is now answered by measurement
(N=2 concurrent; 4 windows / 2 waves for a full 1022x915 cover). The LOD pyramid table (GAP-03), the
registration-method owner, the cache service/TTL, the durable saved-work store and the GAP-05 purpose
split remain open and unowned.

#### Display/LOD implementation units 1–2 delivered (identity + viewport/scheduler) (2026-10-21)

Unit 1 (identity layer) committed in 99d3cda1 — see the earlier entry for the contract names, the
pure-function Core binding, the source-identity stability proof and the no-composite-flag test.
Unit 2 (Console viewport→window resolution + scheduler + composition planner + cache) committed
d40f0bf7. New pure libs: apps/dashboard/src/lib/spatial-display-viewport.ts (viewport→window set),
spatial-display-scheduler.ts (≤2 concurrent, stable keys, 429 back-off, cancel-on-supersede),
spatial-display-composition.ts (receipt-verified assembly + gap states), spatial-display-cache.ts
(per-principal cache with rights re-check on every serve) + 4 test files (33 focused tests).
- Resolution guarantees: viewport ∩ source footprint (outside → typed NO_COVERAGE, never guessed);
  cell-exact pixel range using the same stable-index rule as Core's `_plan`; the split lines are fixed
  at the SOURCE ORIGIN (never viewport-snapped) so the same area always resolves to the same set;
  per-window `actualBounds` from integer indices. Measured 1022×915 at ≤512 resolves to EXACTLY
  (0,512,0,512), (512,1022,0,512), (0,512,512,915), (512,1022,512,915) — shared integer edges, pixel
  sum 935,130, each ≤262,144 px (otherwise OVER_PIXEL_CAP). One real bug was found and fixed during
  testing: split lines computed with `ceil(c0/maxDim)` collapsed when `c0` sat exactly on a multiple
  (full cover returned 1 window) — now `floor(c0/maxDim)*maxDim + maxDim`.
- Scheduler honours the MEASURED lane behaviour, not the contract's earlier queue wording: ≤2
  concurrent issues; an in-flight key is JOINED (no duplicate POST); a completed key replays from the
  cached result with no new PREPARE; the retryable 429 gets bounded back-off (1s·2^attempt ≤8s,
  maxRetries 3) with the named state "재시도 중(n/m) · 순차 처리 중"; a non-empty set shows
  "준비 중 A개 · 기다리는 창 B개 · 순차 처리 중"; queued keys outside the new set are abandoned while
  active ones finish and stay cached (pan-back is a cache hit). Stable keys are
  `stablePrepareKey(assetRef,[c0,c1,r0,r1],purpose)` and `stableIdempotencyKey` (`sdisp-v1-` + 32 hex,
  inside the BFF's allowed pattern). `yScale=t[4]`, `yOrigin=t[5]` throughout.
- Composition places ONLY receipt-verified windows (unverified → a `RECEIPT_MISMATCH` gap), reports
  overlaps as errors (never blends), and turns absent cover into explicit reasoned gaps; it is labelled
  "검증된 준비 창의 나란한 배치 — 이음새 보정·재표본화 없음" with the display-assembly-not-dataset
  note and `imageSmoothingEnabled=false`.
- Cache is per (stableKey, grant, policy, purpose, principalHash) and EVERY serve re-checks
  grant-live → not-revoked → purpose → same-principal → receipt-match, evicting on any failure; a
  foreign principal maps to the exact existing no-disclosure copy.
- Verification: Dashboard 168 files/1620 tests pass, tsc clean, eslint 0 errors (1 pre-existing warning
  in unrelated p4-cleanup-evidence). No product backend/contract/policy/worker change in this unit.
Remaining for the display path: the LOD pyramid table (GAP-03, no thresholds invented), the multi-window
PAINT (the resolver/scheduler/composition planner exist; the viewer still paints one window — the next
unit), a durable cache service + TTL-vs-retention labelling, the `PairRegistrationV1` method owner and
who may assert REGISTERED, the GAP-05 purpose split and cache threat model, and the durable saved-work
store. The audit-recovery track remains untouched by product code (verified: no product module imports
the recovery/incident artifacts), so approving the recovery design still grants no journal authority and
nothing on this path depends on it.

#### Display path unit 3 delivered: multi-window mosaic painted in the real product (2026-10-21)

Unit 3 (multi-window mosaic) committed 92c04a92; own Console image 92c04a92 running. New pure lib
`apps/dashboard/src/lib/spatial-display-mosaic.ts` + `apps/dashboard/src/app/sites/[siteId]/
SiteMosaicViewport.tsx` (embedded in the windowed layer view) + 23 new tests; full Dashboard
170 files/1643 tests, tsc and eslint clean.
- Composition claims: edge-exact side-by-side placement of INDEPENDENTLY receipted windows in the
  source's native plane. Paint offsets are computed from each receipt's own `pixelWindow`
  (`rc0-originC0`, `rr0-originR0`) with an integer bounds guard; a mismatched receipt is skipped, never
  stretched; `imageSmoothingEnabled=false` and `putImageData` only (no drawImage/alpha/filter). Overlaps
  are reported as errors and never blended; a missing window becomes an explicit gap with its reason
  (never interpolated). Labelled "검증된 준비 창의 나란한 배치 — 이음새 보정·재표본화 없음" plus the note
  that it is not one validated dataset and not accuracy/survey/settlement evidence, and that the viewport
  is display-only, not a measurement and not the calculation polygon.
- Interaction: mounting/panning/zooming re-resolve only, with ZERO network on entry; an explicit
  "이어 보기 채우기 (모자란 창 N개)" button gates every POST and GET. Missing windows go through the
  existing 2-slot scheduler with stable keys, 429 back-off and supersede; progress shows
  "그린 창 X / 전체 Y · 끝난 창부터 차례로 그립니다" plus the lane state
  "준비 중 A개 · 기다리는 창 B개 · 순차 처리 중" and a 대기 취소 affordance. Pan-back repaints from the
  cache with no new PREPARE.
- Cache/rights: bytes only via `fetchVerifiedReceiptBytes` (size+SHA gate) → `decodeReceiptPreview`;
  `MosaicPaintCache` re-checks the current receipt sha/size before every serve and evicts fail-closed
  (RECEIPT_CHANGED / RIGHTS_UNAVAILABLE, the latter reusing the existing no-disclosure copy); the cache is
  session-scoped and per-principal by construction, and a foreign owner token is refused and evicted.

Real-product verification (main, screenshot read — `final/mosaic-filled-1440.png`): the mosaic canvas
is exactly 1022×915 and painted 654,639 opaque / 654,250 non-white pixels of REAL coastal imagery.
Three previously prepared windows were reused, so the re-check issued ZERO new PREPAREs; the state line
read "그린 창 3 / 전체 4 · 끝난 창부터 차례로 그립니다 · EPSG:7850 네이티브 평면 1022 × 915 픽셀",
and the missing top-left window is shown as an explicit "그리지 않음" area with the reason, not filled.
The first fill attempt issued exactly 2 concurrent PREPAREs (the measured 2-slot limit) for the 3 missing
windows and showed the rest as "준비 중" — the measured lane behaviour, not a fictional queue.

Still open on this path (unchanged, unowned): the LOD pyramid table (GAP-03 — the resolver is level-0
native only), a durable cache service and the TTL-vs-retention labelling, the `PairRegistrationV1`
method owner and who may assert REGISTERED (so cross-epoch synchronized comparison stays refused), the
GAP-05 purpose split and cache threat model, and the durable saved-work store. Audit recovery remains
an independent, non-critical track with no product-code dependency.

#### Stage-1 direction: cache first, and the completion criterion is measured responsiveness (2026-10-21)

Human adopted the four decisions IN PRINCIPLE with a changed implementation order, and set a new
acceptance standard: the criterion is no longer "can we display the material" but "does it respond
naturally while the user zooms, pans and switches epochs", and the completion condition is the
MEASURED behaviour in the real product, not test counts.

Decisions adopted (principle only; no numbers or implementation fixed yet):
- LOD pyramid: tile-output size candidates 256px/512px (512 first, as the current cap), but the LOD
  SWITCH must be driven by the SCREEN's required map resolution compared with the source resolution
  (whole-site view → lower-resolution first; zoom in → higher), NOT by a fixed zoom-factor threshold;
  the actual switch thresholds come from a benchmark, not from a guess.
- Cache: a PERSISTENT display cache separated from the source, keeping content addressing, and the
  requester must not re-pay the ~12 s on every pan. Structure: browser map → permission check + tile
  lookup → persistent display cache (hit → immediate) → on miss → tile preparation job → verify →
  store → deliver.
- Registration ownership: the server-side spatial-information processing layer owns it; the UI only
  consumes the result. Owning the method ≠ performing registration: start by accepting and VERIFYING
  externally attested registration evidence; automated registration (GCP/feature-point/surface) is a
  separate later step. A registration record must carry the exact baseline/compared versions, the
  transform and CRS, the method and its evidence, the error/valid-area/suitability assessment, and the
  producer + method version. `REGISTERED` must NOT follow merely from a transform matrix existing: it
  requires the evidence and validation conditions for the INTENDED COMPARISON PURPOSE, so one
  registration may suffice for a visual side-by-side and not for a quantitative volume comparison.
- GAP-05: display use and AI egress are separated NOW. Display rights must not let anyone export the
  original GeoTIFF, an AI-training corpus, or unbounded material. Display-tile reads, original
  download, analysis execution, external AI processing and dataset export are DIFFERENT acts, and
  repeated tile reads can reconstruct substantial source information, so unlimited tile download under
  display rights needs its own risk assessment — while ordinary exploration must not be blocked by
  unnecessary approval steps: request limits and access policy are designed around ordinary exploration
  behaviour.

Implementation order changed to: (1) persistent display cache + request scheduler; (2) LOD pyramid and
continuous exploration; (3) registration-evidence acceptance and two-epoch comparison; (4) task-context
restore and historical result lookup. Audit recovery stays an independent track.

Stage-1 completion criteria are now MEASURED IN THE REAL PRODUCT, not test counts: cache hit rate, time
to first valid pixel, time to stabilise after a pan, 429 occurrence rate, and memory usage — with the
measurement method and a scripted pan/zoom run defined so successive runs are comparable, and numeric
targets left to the benchmark rather than invented here.

Also recorded as the design's hardest rule (Human): DATA INTEGRITY AND USER ACCESS RIGHT ARE SEPARATE.
A matching content hash does NOT mean the current requester may access it; a cache hit must still
verify access rights and apply the rights scope and expiry policy, in browser, CDN and server caches
alike. Until the persistent cache service exists, the existing 2-slot concurrency limit stays, tile
requests are deduplicated and off-screen requests are cancelled.

Units commissioned: persistent display cache DESIGN + measurement plan (cache keying incl. the rights
context, two-tier browser/session + persistent server cache, rights re-check on every hit, cold/hot
paths, the metric definitions, owners and open decisions) and, in parallel, the registration-ownership
/purpose-binding rules and the GAP-05 purpose taxonomy with the reassembly control and ordinary-
exploration protection.

#### Display path: the four decisions fixed (cache, registration, purpose split) (2026-10-21)

Two design documents committed with this entry, both subordinate to the display/LOD contract, the
Constitution/PRD §1.1.2, ADR-KSI-036/037/038 and the domain invariants; no source/contract/runtime/
policy change, no commit of runtime state, no new Core job, no shared-host action, no inspection launch.

`docs/design/SPATIAL_DISPLAY_PERSISTENT_CACHE_AND_MEASUREMENT_PLAN_2026-10-21.md` — persistent display
cache + measurement plan:
- The cached artifact is the display-derivative prepared bytes at a stated tile size; the anonymous-blob
  option is REJECTED. Content identity (`derivativeId`) stays SEPARATE from the CACHE KEY, because the
  key must additionally bind the rights context (principal/org scope, grant and policy revisions, and
  the activation-currency pin) — a hit may never cross a right boundary.
- Representation is whole-tile bytes (512px first, 256px a candidate SIZE, never a LOD threshold), and
  the seam-exactness guarantee is preserved by keeping the existing integer-edge placement.
- The T1 browser/session tier (today's `MosaicPaintCache` / `DisplayWindowCache`) is kept as a LATENCY
  optimization only and is never an authority: it re-validates before every paint. A T2 persistent server
  tier is added for durability; it is also not an authority. Eviction cascades downward only.
- EVERY hit runs an 8-step live re-check with the content hash checked LAST (grant live → not revoked →
  purpose → requester ownership → expiry/retention → policy/activation currency → … → hash). This is the
  Human's hard rule: a matching content hash does NOT mean the current requester may access it.
- Display ≠ original/AI/export: per-principal and per-purpose retrieval budgets are proposed; the numeric
  values are left to GAP-05 and the benchmark.
- Measurement plan: M1 cache hit rate, M2 time to first valid pixel, M3 time to stabilise after a pan,
  M4 429 occurrence rate, M5 memory usage — each with its definition, instrumentation that changes no
  product semantics, and a pass/fail FORM whose numeric targets are set by the benchmark rather than
  invented. A versioned R1–R5 reference exploration run (including a rights-flip pass) makes successive
  runs comparable. Open decisions O-1..O-8 (record names, currency token, T2 placement — with no
  deployment authorized, T1 freshness bound, retrieval budgets, tile-size evaluation, style/validity
  registries, purpose split) and the candid undecidables (TTL/eviction/quota numbers, the shared-cache
  threat model, LOD thresholds, any rights bypass — unspecifiable floor).

`docs/design/REGISTRATION_ACCEPTANCE_AND_PURPOSE_SPLIT_CONTRACT_2026-10-21.md` — registration ownership
+ GAP-05 purpose split:
- Registration ownership: the Core server-side spatial layer (delivery + ingress/inspection owners)
  produces and VERIFIES; event-contracts owns the shapes/validators; geo-spatial owns the math only;
  the Dashboard/MCP consume; the UI never computes or asserts registration. Owning the method is not
  performing it — Core performs no registration today.
- Acceptance starts at EXTERNAL_ATTESTATION: a record pinning both subject versions, the transform +
  CRS + units + frame, the method + producer + evidence manifest, error metrics with pinned definitions,
  the valid-area rule + geometry, and the comparison kind; 9 conjunctive Core checks with 9 typed
  `REFUSE_*` reasons; a bare matrix is refused and in-place edits are forbidden.
- Purpose binding: records are admitted per comparisonKind (VISUAL_SIDE_BY_SIDE < OVERLAY_ALIGNED <
  DIFFERENCE_COLOURING < QUANTITATIVE_VOLUME) with 5 per-kind verdicts; a missing or wrong-purpose
  registration yields INDEPENDENT VIEWING ONLY with mandatory wording and no composite flag.
- Automated registration is a separate future decision with 5 gates; nothing is admitted now.
- Purpose taxonomy (GAP-05, decided): DISPLAY_VIEW / ORIGINAL_DOWNLOAD / ANALYSIS_INPUT /
  AI_EGRESS (= the existing EXTERNAL_AI gate, intact) / DATASET_EXPORT, each with what it permits, what
  it must NOT permit, the operations granted, the outputs produced, the audit record left and the
  expiry/limits. No implicit escalation and no gate weakened.
- Reassembly control: a per-grant AGGREGATE tile-read budget (in source-pixel terms) plus separate
  display/download budgets, a rate/anti-scraping guard, and an append-only tile-read audit. The numeric
  factor F, the thresholds, the cache-hit weighting and the CDN/browser threat model are left to risk
  assessment rather than invented.
- Ordinary exploration protection: authorisation is per grant (not per tile), the budget is calibrated to
  normal pan/zoom, limit states are typed and recoverable, and there are no per-tile approval prompts.
- Contract changes: an ADDITIVE extension of the existing `PairRegistrationV1` (existing records keep
  parsing; older REGISTERED shapes cannot authorize a kind-bound comparison until re-attested) plus a
  new ComparisonKindV1, PairRegistrationVerdictV1, the new purpose members, DisplayTileReadAuditV1 and
  typed reasons, with the contract/Core split stated.

Cross-check by primary: both documents agree on the content-vs-rights separation, the no-composite-flag
rule, the three-state separation, the "leave numbers to the benchmark/risk assessment" discipline, and the
registration/purpose boundaries; the cache plan defers the purpose numbers to the GAP-05 taxonomy, so the
two are consistent rather than competing.

#### Stage-1 measurement corrects the stage-1 goal: the cost is preparation, not revisits (2026-10-21)

`docs/audit/SPATIAL_DISPLAY_CACHE_MEASUREMENT_EVIDENCE_2026-10-21.md` (+ machine-readable
`display-cache-measurement-results-2026-10-21.json`) measured the real product and CORRECTED the
premise the stage-1 plan was built on. Recorded here so no later work inherits the wrong expectation.

MEASURED stage attribution for one fresh full 1022×915 cover (n=4 windows, idle lane, real contained
worker): POST issue 0.030–0.052 s; pickup first-of-pair 4.6–5.1 s and second-of-pair 10.6–10.8 s
(the two "concurrent" slots are picked up on SERIAL ~5 s worker ticks, so a wave of 2 costs ~5 s +
~10.7 s, not 2×5 s in parallel); execution 0.5–1.0 s per window; byte GET 0.11–0.16 s per window
(TTFB-dominated); SHA-256 verify 0.0002–0.0003 s; decode ~3 ms warmed (PIL proxy, browser cost
INFERRED same order); paint ms-scale (numpy proxy, browser NOT MEASURED). Time to first valid pixel
≈ 5.8 s; all four windows painted ≈ 23.0 s.

TWO CORRECTIONS TO WHAT WE BELIEVED:
1. The full cover is **22.9–23.0 s, NOT ~12 s**. The earlier 12 s figure assumed parallel pickup; the
   worker serves the two slots on serial ~5 s ticks. The 12 s number is superseded for capacity
   reasoning.
2. **Re-visits are already fast**: with the windows prepared and readable by the same principal, a
   full 4-window re-GET + verify + decode costs 0.691 s, and a same-key + identical-body replay POST
   returns the SAME job in 7 ms with zero new work. A fresh page load / "이어 보기 채우기" for an
   already-prepared cover therefore costs ~0.7 s TODAY, not ~23 s, under stable-key discipline.

CONSEQUENCES FOR THE STAGE-1 PLAN (the Human's stage-1 goal is re-based on measurement, not on the
prior assumption):
- A persistent server cache (T2) removes NOTHING on per-visit latency — the bytes are already stored as
  owned outputs and a re-GET costs the same ~0.13 s/window either way. Its real, structural win is
  DURABILITY past the 24 h retention expiry, when a full re-preparation (~23 s) would otherwise have to
  be re-paid. It must not be justified on latency.
- The only sub-100 ms path is the session tier of decoded pixels (T1), and it already exists in-session
  (`MosaicPaintCache`); what is missing is a BOUND on it (it is currently an unbounded Map) plus
  cross-session durability, not speed.
- Therefore the real user-visible cost to attack is the FIRST payment — the ~23 s cold preparation per
  principal per retention window — and the levers are (a) not paying it again after retention expiry
  (durable cache), (b) not paying it for the same window twice (stable keys, already honoured), and
  (c) making the first payment feel immediate and continuous (progressive first-pixel delivery, which
  the mosaic already does) rather than making the first payment smaller by caching.
- 429 behaviour confirmed: a 3-wide issue yields 2×201 + 1×429 in 52 ms (wire `{reason, retryable:true}`);
  a deeper CLIENT queue changes nothing user-visible because the server has no queue, so the measured
  discipline stays: max 2 concurrent + bounded retry + named waiting states. The 1–4 s back-off is
  shorter than the ~5 s pickup tick, so a first retry typically re-429s once (harmless).
- Memory measured: decoded RGBA per window 1,048,576 B; the 1022×915 canvas 3,740,520 B; a full-cover
  session tier 7,934,824 B (~7.57 MiB); encoded bytes 2,265,338 B (~2.16 MiB). The unbounded
  `MosaicPaintCache` Map must get a cap (M5 target: T1 ≤16 slots with eviction).
- Irreducible floor: ~23 s per full cover per principal per retention window (~21–22 s pickup + ~2–4 s
  execution). NO cache design removes the first payment; a durable cache only prevents paying it twice.
Recommended M1–M5 targets (recommendations from THIS measurement, not authority): R2 revisit 100% T1 /
0 PREPAREs; warm time-to-first-pixel ≤1 s (T1 ≤100 ms) with cold ≈6 s report-only; cold stabilise
≤25 s; 429-by-construction 0 with FAILED-due-to-429 = 0; T1 ≤16 slots with eviction.
- Not measured (and why): browser paint / geotiff.js timing (no browser launched — proxies only),
  Console end-to-end page timings, post-retention and cross-session revisit, multi-actor contention,
  OIDC-principal reads (respected, not probed), and the GAP-06 L3 outlier cause.

#### Stage-1 package scoped by measurement; two owner decisions surfaced (2026-10-21)

`docs/design/SPATIAL_DISPLAY_FIRST_PAYMENT_REDUCTION_DESIGN_2026-10-21.md` (design only) re-based
stage 1 on the measured cost model instead of the earlier assumption.

ROOT CAUSE OF THE ~23 s FIRST PAYMENT (verified in code, not inferred): the worker's own loop, not the
Core's admission limit. services/processing-controller/src/ksi_processing_controller/spatial_data_runner.py
runs `run_once` (ONE bounded poll/launch), closes the sandbox, then `stop.wait(config.poll_interval_seconds)`
before the next poll — so the second window waits for the next ~5 s tick. The two "concurrent" Core slots
(2 active, fast retryable 429 beyond, jobs.py:1044-1048) are therefore served SERIALLY by this worker.

LEVER VERDICTS:
- Worker parallelism (P-A: N concurrent `run_once` per tick) is the only parallelism lever that moves
  the number (projected ceiling 6–8 s) and it is NOT viable inside the existing contract: it touches the
  worker, the containment/launcher model, the resource envelope (spatial_data_authority.py:32–77) and
  the signed policy. `maxActiveJobsPerOrganization` is ORGANIZATION-WIDE, so raising it widens every
  tenant; a per-principal/per-tenant cap would be a NEW contract field (event-contracts + Core
  delivery + policy owners). Deferred as S6, gated on multi-tenant load evidence.
- LOD overview is the CHEAPEST structural first-payment fix (one pickup cycle, ~5–6 s projected) but it
  is a NEW ARTIFACT KIND under the current contract, not a permitted window: the worker verifies an
  exact NATIVE crop (spatial_data_worker.py:264-275 against `max_output_pixels`/`max_output_bytes`),
  and any resampling is a new transformation needing its own kernel registry, containment proof, receipt
  binding and Core admission — all GAP-03 territory. The identity layer already supports it: the LOD/style/
  validity pins are part of `DisplayDerivativeV1`, so a coarse tile and a native tile of the same ground
  area are DIFFERENT derivatives by construction (different `derivativeId`). Deferred as S5, gated on
  the GAP-03 table + kernels + containment proof.
- Progressive delivery is viable TODAY (the mosaic already paints on arrival; first valid pixel
  ≈5.8 s measured) and is S1.
- The cache's real win is DURABILITY (surviving the 24 h retention expiry, when ~23 s would otherwise be
  re-paid), NOT per-visit latency — the T2 plan must not be justified on latency.

STAGE-1 PACKAGE (dependency order): S1 progressive-first-view discipline (centre-first issue order,
paint-on-verify, partial-cover labelling, off-screen drop with PINNED HYSTERESIS) → S2 T1 session-tier
conformance (rights-bearing key, re-validate before every paint, and a BOUND — `MosaicPaintCache` is
currently an unbounded Map, which the measurement flagged) → S3 T2 persistent tier for durability
(placement decision separate; NO deployment authorized) → S4 the versioned R1–R5 reference run and the
M1–M5 gauges → S5 the LOD-overview preparation path (the real first-payment cut; needs GAP-03) →
S6 worker parallelism/admission ONLY if S5 proves insufficient and multi-tenant evidence exists.
Measured basis for the acceptance form: cold first pixel ≈5.8 s, cold stabilise ≈23.0 s, warm revisit
≈0.691 s, T1 target ≤100 ms, 429 zero-by-construction with FAILED-due-to-429 = 0, session-tier memory
≈7.57 MiB for a full 1022×915 cover. Targets stay open until the benchmark sets them; no "instant"
first-payment claim is made (the floor is one pickup cycle).

TWO OWNER DECISIONS NOW SURFACED (neither can be taken by the implementation):
1. GAP-03 (S5): the LOD pyramid table, its level definition, the per-level thresholds as a function of
   viewport metres-per-pixel × device pixel ratio × source GSD, the kernel per data kind (mean for DSM
   elevation? nearest for masks?), the DSM-vs-ortho rule differences, the coarse-level valid-area/mask
   behaviour, and the containment proof for in-containment resampling — plus the table/version pin that
   enters `DisplayDerivativeV1`. No level/threshold/kernel may be invented.
2. The stage-1 ADMISSION question (S6): whether `maxActiveJobsPerOrganization` stays organization-wide
   (and at what value) or a per-principal/per-tenant cap is introduced, and what multi-tenant load
   evidence is required before either moves. `maxQueueDepth`/`maxPendingRecords` (8) were found to have
   NO reachable enforcement on this route, so the "queue depth" concept itself may need re-specification
   rather than a number.

A REAL PRODUCT DEFECT WAS ALSO FOUND AND IS BEING FIXED SEPARATELY: Core's job LIST included other
principals' jobs for an organization ADMIN (jobs.py:1102-1104) while the per-job READ denies a
non-requester admin with 404 (jobs.py:350-352). The list/read disagreement made the real Console list
windows it can never open and report them as "준비에 실패한 요청" — a false failure, since those jobs are
COMPLETED/AVAILABLE and simply belong to another principal. The byte path stays requester-bound; the fix
makes the projections coherent and is under way.

#### Stage-1 S1–S4 delivered; the list/read ownership defect fixed and verified (2026-10-21)

DEFECT FIX (committed 6664ba80) — the real product defect found during stage-1 verification. Core's job
LIST admitted another principal's jobs to an organization ADMIN (jobs.py list(), ~1101-1107) and the
single-job metadata read carried the same bypass, while the byte path was (and remains) strictly
requester-owned. The consequence in the real Console: the OIDC operator saw `ps-admin`'s prepared
windows in the list, could read their receipts/pixel windows, then got 404 on the byte GET — so the
mosaic painted 3 of 4 windows and reported the fourth as "준비에 실패한 요청" — a FALSE failure, since
those jobs are COMPLETED/AVAILABLE and simply belong to another principal. Resolution: fail-closed
requester-only visibility for list, read, cancel AND bytes (the same rule in each place), so the
projections agree and no foreign receipt metadata leaks; `cancel()` inherited the same bypass and was
closed with the same change; the byte path is unchanged and still re-proves requester ownership. A new
owner test covers list/read/download coherence, admin vs requester behaviour, cross-tenant denial,
revocation/expiry still honoured for the owner (and 404 for foreigners), and the unchanged
`max_list_records` budget. Sweep found no other `Role.ADMIN` bypass in the delivery owner; the
asset/evidence/audit paths are either coherent or a different class (org-scoped event tracks).
Re-verified in the real product after an own-Core restart (all 14 journal hashes unchanged): the false
"준비에 실패한 요청" claim is GONE, no foreign window is listed, missing windows read "아직 준비하지 않은
창이라 비워 둡니다. 빈칸을 메우거나 늘이지 않습니다", and the SAME account's own 4 windows compose to a
complete 1022×915 picture (884,413 opaque pixels) with ZERO new PREPAREs.
OWNER DECISION SURFACED: if operations genuinely needs admins to SEE other principals' jobs, that needs
an explicit, separately authorized admin-visibility path (new endpoint/permission + a Console
"not mine" vs "failed" distinction). It was deliberately NOT built; until then admin oversight of
foreign jobs is unavailable by design.

STAGE-1 S1–S4 (committed 6387567f, Console image 6387567f running):
- S1 progressive first view: windows are issued in VISIBILITY-CENTRALITY order (centre distance to the
  viewport centre, stable on ties — the server has no FIFO so the client sequences), each window is
  painted as soon as its bytes are receipt-verified, a PARTIAL cover is always labelled partial
  ("부분 보기 · 그린 창 n/전체 N · 나머지는 준비 중 (빈칸을 메우거나 늘이지 않음)"), and off-screen
  windows drop with PINNED HYSTERESIS (8 px edge gap) so a 1-px pan never discards an in-progress
  window and a just-left abutting window is kept as a pan-back halo.
- S2 T1 session tier: the browser tier now keys on the rights-bearing pins it can honestly hold
  (assetRef·purpose·observedCrsDigest), re-validates owner token → scope pins → grant live → not
  revoked → purpose allowed → sha/size on EVERY paint (a stale/foreign window is a MISS and is evicted),
  and is BOUND: `MOSAIC_T1_MAX_SLOTS = 12`, derived from the MEASURED 1,048,576 B per decoded window
  (~12 MiB) plus the ~3.6 MiB canvas, inside the evidence ceiling of ≤16 slots, with the working set
  being R1 (4) + R3 fringe (~8) so a pan-back to R1 hits. LRU eviction with a residency (M5) gauge. The
  Core-held pins (grantDigest, policyDigest, beneficiary, organization, revision, activation) are NOT
  fabricated by the Console — they land with the T2 tier; the Console derives its session facts from
  Core's live list responses.
- S4 reference run + gauges: a versioned R1–R5 sequence (R1 cold, R2 revisit, R3 pan walk, R4 zoom,
  R5 rights flip) and counters/marks for M1 hit rate, M2 time to first valid pixel, M3 stabilise after a
  pan, M4 429 rate and M5 memory, with `deriveM1M5` as a pure function and every numeric threshold
  left `TBD_BY_BENCHMARK` (measured basis cited: cold first pixel ≈5.8 s, cold stabilise ≈23 s, warm
  revisit ≈0.7 s, T1 target ≤100 ms). The gauges are collectable in-product but are NOT wired into the
  default path, so product behaviour is unchanged.
- Honest cold/warm reporting only from measured values; no "instant" or "latest" claim.
Verification: Dashboard 171 files/1657 tests, tsc clean, eslint 0 errors/warnings; Core 104 delivery
tests + 205 related + 67 current-grant/replay tests pass; ruff clean. Real-product measurement on the
delivered build: with the current account's own 4 windows already prepared, the full 1022×915 cover
composes in 1.1 s with 0 new PREPAREs, and during a genuine cold fill the UI showed "이어 보기 채우기
(모자란 창 4개)" then "부분 보기 · 그린 창 0/전체 4" and painted 3 of 4 within 1.1 s while the last window
continued preparing — progressive delivery confirmed in the real product.
NOT done (and not claimed): S5 the LOD-overview preparation path (needs the GAP-03 table, kernels and
containment proof), S6 worker parallelism/admission (needs the policy decision and multi-tenant
evidence), and the T2 persistent tier (placement decision separate, no deployment authorized).

### 2026-10-21 — Human shifts the active task to usability-first composition

Latest Human: “UI UX 그리고 사용성 중심으로 설계가 되어야하지 않을까 기능이나 이런건 이제 충분하니?”
then approved “그래 그렇게 구성해봐”. Pause new feature/LOD/cache/registration-contract development for
this bounded task. The approved outcome is the actual normal Console's readable first view and three
coherent tasks: see the Site's observations → inspect another capture/layer → understand result/limits.
No standalone demo, no new platform capability, no routine technical approval questions.

Requirement IDs: SDP-REQ-01/02/05/06/07; existing Site workspace journey; INV-020/024/040/051/053/060/061.
Owner module: apps/dashboard only. Acceptance: real authorized spatial content or one clear truthful
recovery action in the first viewport; compact Site identity and capture/layer controls; technical
window/coordinate/audit/processing details discoverable on demand, not walls before the task; compare
retains exact inputs/scope and does not fake registration; results show comparison context, quantities,
limits and a useful next step; Back/reload/mobile/keyboard and permission boundaries retained.
Contracts affected: none; no Core/worker/schema/authority/byte-access changes. Existing data and results
stay immutable; zero PREPARE/analysis writes on entry. Guarded GET of already available own outputs is a
normal read, not new preparation or validation. Reference assets: incumbent tokens/components and actual
before captures at /tmp/opencode/ksi-usability-first-20261021/{before-*,baseline.json} (6387567f image).
Primary personally inspected mobile Explore/Results and desktop Compare: empty geometry dominates;
mode tabs are added above duplicate navigation; actual viewer is buried behind technical scaffolding.
Adoption: preserve useful Console identity; replace first-view hierarchy, reuse existing guarded mosaic
and byte path; no external assets/dependencies/basemaps. Files: SiteHeader, Site workspace shell/overview/
compare/results, window viewer/mosaic presentation and focused tests as required; connected analysis route
only if necessary. Tests: focused UI/render/interaction tests, Dashboard suite/type/lint/locked build,
actual 390/1440 product flows with existing records; no repeat of unchanged Python suites.
HIL: none; automation ≠ physical touch/customer usability/field approval. License/data: existing CC BY4
attribution retained; no new egress or rights. Rollback: replace only own Console3243 with previous image.
Protected resources: ALL Core8074 journals and protected env/config; S3 objects; every other server;
shared inspector journal branches/staging/daemon/cgroup; all original assets. No host changes, no new jobs,
no recovery or policy changes. Core8074 currently ready/listening; no restart required for UI-only work.
Native desktop screenshot failed despite focus before restart; six settled first-view captures already
saved by isolated Playwright and remain valid. Reuse that evidence; do not repeat initial research.

Usability implementation review (not final acceptance): source60c063ce first unit built with unchanged
locked dependencies and172files/1663tests passed. Actual390px render proved the guarded pixel reads
worked (1022x915 canvas,884413opaque/883713nonwhite) but photo still started at y778 rather than y3552.5.
It therefore did NOT meet the first-viewport task outcome. Primary read the settled phone/desktop
captures: compacting some chrome left duplicated capture/layer text and three mosaic paragraphs before
the image; no visible capture selector; Compare repeated prompts with no actual selectable candidates;
Results had one lead/history but no actual compared-period context. Real browser also exposed React418
from invalid paragraph/block nesting. One coordinated correction batch was sent to the same UI owner.

Corrected source: capture date GET selector with exact existing assetRef/WorkArea; mosaic immediately
after controls, engineering text/window state/manual requests behind disclosure; no-options Compare one
reason plus same-scope exploration action; one bounded existing getAnalysis read for lead-result pair
context, validated Site/area/id; no inference of missing accuracy evidence from null volume uncertainty;
SSR nesting fixed. Primary additionally pinned the Explore layer into its normal GET navigation so a
DSM selection, changing observation, Back and reload refer to the same selected layer/version (Compare
pane-local toggles remain local and cannot rewrite frozen pair inputs). With no own prepared output and
no actual job, the display is a concise truthful state rather than a large apparently pending empty map.
Focused regressions + full hostDashboard173files/1673tests, tsc and changed-file ESLint passed. Final
locked image and actual confirmation are pending; no user task is accepted from these counts alone.
No Core/schema/policy/data/rights/worker changes and no PREPARE/analysis POST on entry were introduced.

Actual second-pass interaction checks on81f43151 and bounded-view19cd047b succeeded: visible real capture
selector2021/2022, selected DSM retained when changing capture, Back/reload exact scope, keyboard evidence
disclosure, viewer read-only state and no preparation control, saved synthetic800m3 result+explicit non-field
review still accessible. Zero API POST and zero browser errors. Bounded CSS keeps the same source pixel
buffer and native placement; it does not resample or create a new derivative. On19cd047b the phone photo
y443.5,height265 and desktop y399.5,height519.98 (before y3552.5 on phone).

An additional affected-layer check found a genuine presentation gap, not a reason to create more data:
the current account has a real prepared DSM512x256 crop, but it does not match the full-view tile grid.
The mosaic therefore displayed0/4 pending forever instead of showing the already readable crop. UI fix
reuses existing SpatialDataReceiptPreview (same guarded GET, full-size/SHA gate and NoData/mask decoder),
selecting an already prepared same-asset crop only when no matching mosaic tile is present. It explicitly
labels the output as an existing partial range, preserves relative DSM/vertical and per-window-stretch
limitations, and issues no new preparation. Ordinary job-detail preview remains explicit unless its new
presentation-only autoLoad option is supplied by the Site fallback; unmount/source-change cancels it.
No Core, endpoint, grant, policy, source bytes or quantitative contract changed. Added exact coverage/
revocation/foreign-asset selection regressions; retained integrity/ownership/no-POST assertions. Latest
host173files/1674tests/type/lint passed; final locked build and actual crop read still pending.

Final read-task exercise also caught a pre-existing dead-end: Core list `analysisHref` is an API path
(`/v2/sites/.../analyses/...`), but the result card and secondary overview action used it as a Console
href. Actual pointer navigation therefore landed on the frontend's nonexistent API-shaped page instead
of the record. UI links now construct the existing Console analysis route from the exact result ID and
WorkArea (no new endpoint or data transformation). Added a Core-shaped API-href fixture and retained
exact-target assertions; the final acceptance clicks through the real link and opens the saved review,
not just a direct API GET. This is closing the approved user flow, not a platform feature expansion.

#### Usability-first Site composition — actual delivered acceptance, 2026-10-21

Delivered frontend source35d2ded0, normal private Console10010→own Docker3243→UNCHANGED Core8074.
Only labelled own frontend container replaced; prior containers/images retained for rollback. No new
public route, dependency, source raster, inspection launch, policy, grant, shared host or backend change.
This closes the latest Human's bounded UI/UX composition request, NOT whole-platform/operational gates.
Feature/LOD/cache/new-contract work remains paused by the latest user direction.

| User task / previous obstacle | Delivered outcome and actual evidence |
|---|---|
| Enter Site and recognize the observation | Capture/layer controls and actual authorized pixels precede the empty geometry/diagnostic scaffold. Phone390x844 first image y443.5,height265 instead of baseline y3552.5; desktop1440x1000 image y399.5,height519.98, fitted to working viewport. Full own prepared ortho1022x915 paints884413 valid opaque pixels after guarded reads; no new preparation. |
| Change date and layer without losing context | Visible actual2021/2022 GET selector; date-only precision retained. Actual DSM switch then date change keeps available DSM source. Reload and Back retain exact assetRef/WorkArea; mode links preserve browse source, not just area. No client-side latest ranking. |
| Read an existing partial DSM | A real own512x256 crop paints131072 opaque pixels on the first view, explicitly labelled partial and relative shading. It is not mistaken for absent data or stretched into a full observation. No new jobs/source/LOD transformation. |
| Know why a comparison is unavailable and where to go | One typed no-candidate explanation and same-scope exploration link instead of multiple repeated warning/empty-slot cards. Detailed unsupported synchronization and date-only restrictions remain accessible; no registered pair/quantitative eligibility is invented. |
| Understand result and reach supporting evidence | One lead record shows actual baseline2026-10-06/current2026-10-13 capture intervals, WorkArea, Core-recorded800m3 synthetic result and its accuracy/use limits. Older records are expandable; null volume uncertainty no longer implies absent checkpoint evaluation. Actual click on '자료·근거와 검토 보기' reaches exact Console analysisID/area, then opens the persisted non-field automated review. |
| Access details without being forced to read them first | Source/extent/registration data, independent audit/validation/viewability explanations, receipt/window diagnostics and manual preparation remain in labelled disclosures. Keyboard Enter opens/closes evidence disclosure; information is not deleted or merged into a verified badge. |
| Viewer/mobile permissions and missing-output state | Real development OIDC viewer reads capture facts, gets a concise own-display-unavailable explanation instead of a blank map, and has no accessible preparation action. Existing phone/laptop mutation restriction, ownership/currentness/size/SHA checks and failure states preserved. |

Final current-build verification files (all `build=35d2ded0`, `ok=true`, zero API POSTs, zero page errors):
- usability-verification.json: actual first-pixel canvas/viewport checks390+1440, result/review lookup,
  results/compare renders and wrong-scope nondisclosure;
- task-flow-verification.json: real visible date control, DSM/date continuity, reload/Back, keyboard
  details, viewer read-only state and no horizontal overflow;
- stable-pixel-verification.json: fully painted actual ortho and partial DSM, not an early skeleton;
- evidence-link-verification.json: pointer clicks through result→exact UI record→expanded saved review,
  and older-history disclosure. A raw API read is not substituted for link functionality.

All final representative original images were read by primary, including shipped-ortho390/1440,
shipped-dsm390, after-results390/1440, after-compare390 and after-viewer390. Primary did not accept the
first unit from test counts; actual rendering exposed and corrected the y778 obstruction and hydration
error, and later actual task exercises closed the non-tile-crop and API-shaped evidence-link gaps.
Final locked Next16.3.3/Vitest4.1.11 Docker build and173files/1674tests passed; host tsc and touched-file
ESLint clean; mechanical detector[] on initial targets and changed affected components. Existing
Python/Core evidence reused because no backend code/contract changed; no unrelated suite repetition.

Evidence: /tmp/opencode/ksi-usability-first-20261021/ and durable
~/.local/share/ksi-product-use-20261021/verification-usability-35d2ded0/ (README + SHA manifest). Earlier
failed/stale captures are labelled separately and are not final acceptance. Native desktop screenshot
failed despite focus before restart; actual rendered evidence uses isolated Playwright, not DOM-only
substitution. This is pointer/keyboard/viewport automation, not physical touch/screen-reader/customer
usability research or field/accuracy/settlement acceptance. Existing shared audit incident and all
operational/production/customer/retention approval limits remain unchanged and independent.

No further routine feature expansion or preference-only polishing is selected for this task. The next
goal-relevant integrated outcome is delivered and verified: open real Site→see prepared observation→
change capture/layer→understand Compare restriction or result→follow exact result/evidence/review.

### 2026-10-21 — Human requests systematic UI/UX research, not another implementation pass

Human asked whether familiar competitor screens/interaction patterns should inform KSI, then explicitly
requested “UI UX 조사 등 체계적으로”. Current bounded task is research and design recommendations.
Git3f60abe7/main=origin revalidated; frontend35d2ded0 remains served, unchanged. No feature/LOD/cache/
contract/host-recovery work resumes through this request. Earlier usability implementation acceptance
remains valid for its bounded task; it is not end-user comprehension or category-familiarity proof.

Research delivered in [CONSOLE_SPATIAL_UX_RESEARCH_2026-10-21.md](../../audit/CONSOLE_SPATIAL_UX_RESEARCH_2026-10-21.md):
task questions/costly failures, T1–T9 workflow matrix, actual screen/interaction evidence, two-competitor
official-reference matrix, ranked findings with observation vs inference, alternative structures and
trade-offs, scoped design/user-study protocol and evidence/limitations. This is an audit artifact, not
a new task ledger, normative contract or implementation approval. Requirements SDP-REQ-01/02/05/06/07
and existing UX contract guide the analysis; INV-020/024/040/051/053/060/061 remain constraints only.

Primary performed actual read-only Home/Sites/Explore/Compare/Results/Materials desktop/mobile review,
settled follow-up, real Site-card entry and comparison recovery; reused same-build prior verified
date/layer/Back/reload/viewer/result/evidence/review proofs. An independent fresh-context assessment
and public-reference scout were used; primary read adopted original screens/sources and rejected
unsupported interpretations. Initial streaming captures are labelled, not accepted as loaded screens.
Native DOM connected but focused screenshot still failed visible-tab; isolated Playwright renders used.
Only own research tab/browser sessions were closed; no other user tabs or workers were managed.

Material observations: stacked areas/modes overlap semantically; Materials tab adds an intermediate
‘자료 열기’ gateway; pointer drag/wheel do not change the current image geometry while buttons do
(1022x915→512x459→1022x915); phone controls starty813.5/865.5 beneath the image/first viewport;
existing-output GET/decode uses ‘준비 중’ wording despite no new preparation. These do not prove user
confusion rates or policy violations. Current numeric limits/exact source bindings and partial-view/
no-own-output distinctions remain strengths. No fake aligned coast comparison or heatmap is proposed.

Priorities: F1 navigation/task structure, F2 map-control access and verified interaction behaviour,
F3 visual/calculate comparison meaning; then F4 loading semantics, F5 corrective-version clarity and
F6 result-to-evidence reading continuity. A task-surface plus one on-demand panel is a hypothesis to
compare against minimal incumbent refinement, not a mandatory always-open three-pane editor.
No permission, new source/inspection, export capability, quantitative condition or API change follows.

Evidence root /tmp/opencode/ksi-ux-research-20261021/; durable copy at
~/.local/share/ksi-product-use-20261021/ux-research-20261021/ with source/capture SHA manifest. New
walkthrough blocked zero product-write attempts and had zero page errors. Installed axe-core scans
of Explore1440/Results390 found no automated A/AA-tag violations, but Explore contrast4nodes remain
manual-review/incomplete; no overall accessibility claim. No code change means no full product suites,
build or deployment repeated. External reference images retained locally for research only, not
redistributed as licensed implementation assets. Actual customer participants=0; no competitor login,
human usability benchmark, physical touch/SR, field or production acceptance claimed.

The requested desk research/expert assessment is complete; a future design/implementation pass and
real participant study are explicitly not reported as completed. Next goal-relevant verification
would compare actual task access/comprehension while preserving exact WorkArea/source/result context.

### 2026-10-21 — Human approves improving the researched UI/UX

Latest Human “개선해줘” selects implementation of the preceding systematic research outcomes. This
supersedes the last research-only checkpoint for this bounded unit, not the product authority. Target
the actual normal Console, not an independent demo, new processing feature or new architecture contract.

Requirement IDs: SDP-REQ-01/02/05/06/07; existing Site workspace UX contract and research F1–F6.
Owner module: apps/dashboard, Site navigation/spatial workspace/viewer/connected record presentation.
Acceptance criteria: one legible primary spatial-task navigation, supporting Site areas remain reachable;
actual Materials/analysis records reachable without the extra gateway; capture/layer/exact-version/scope
continuity; working pointer/wheel plus button/keyboard alternatives for the existing native display,
controls visible with the image on390/1440, no automatic preparation/calculation; independent observation
viewing vs conditional pair display vs quantitative request clearly named; read/loading/missing/failed
states truthful; selected revision discoverable without hover; results keep original input/limits and
evidence/review route. Verify actual renders/tasks including permissions and Back/reload.
Contracts affected: none; existing Core selectors/routes, admission/chronology/registration, rights,
requester ownership, size/SHA, originals and <1024 write boundaries unchanged. No new source/derivative,
LOD/cache policy, basemap, analysis, report/export capability or data/AI grant. INV-020/024/040/051/053/
060/061 enforced by unchanged server/guarded-byte paths and new presentation/navigation regressions;
display gesture changes only display viewport, never WorkArea polygon or frozen analysis inputs.
Reference assets: research originals/current screenshots and official-source matrix; existing Console
tokens/components. Adoption decisions: refine incumbent identity; primary spatial task controls and
on-demand supporting Site navigation; map-adjacent controls, truthful loading, comparison disclosure;
no always-open3pane, borrowed brand assets or simulated heatmap. Existing route compatibility retained.
Files to change: SiteHeader/navigation href helper, Site workspace/Explore/Compare/Results, mosaic and
existing receipt viewer if shared interaction consistency requires; actual analysis record presentation
only if needed; related Dashboard tests. No global Home redesign, backend/schema/security/runtime files.
Tests: targeted navigation/SSR/gesture/loading/identity/permissions/no-POST tests, full Dashboard suite,
tsc/eslint, locked image build and actual normal-product390/1440 workflows. Existing unchanged backend
evidence reused. HIL/real-device assumptions: none; emulated pointer/touch not physical touch/SR/customer
usability acceptance. License/data implications: existing assets/CC BY attribution; no new egress/assets.
Rollback: replace only own labelled Console3243 image with retained35d2ded0; original Core8074 data/env,
S3, inspector journal branches/staging/worker/daemon/cgroups and all other services protected.
Gitf46cdf67 revalidated; tracked clean except user-owned.playwright-cli. Primary owns design, browser,
runtime, docs and Git; one General owner implements the cohesive UI unit with exclusive shared files.

First actual UI review, source3b318e6d: locked175files/1690tests/build/type/lint passed, but actual UX
acceptance did not. Primary read desktop/phone Explore, failed gesture, no-candidate Compare, Results
and viewer originals. Native-viewport zoom invalidated the match to the currently prepared full-view
tile windows; actual '+' turned all previously visible pixels into `표시 준비 필요`. This is not a
license to issue more preparation, weaken eligibility, mock pixels or accept tests as delivery. Phone
zoom-out/reset also wrapped to y790–834 behind the fixed bottom nav; the side-by-side mobile area/date
form reduced the capture dropdown to about90px. No-option Compare still exposed an oversized pair/
quantitative guidance block. The same implementer received one coordinated necessary correction batch.

Revised design hypothesis: ordinary display gestures/buttons crop/scale/translate the already verified
pixel buffer locally within a bounded viewport, without redefining the source cover/receipt or preparing
new tiles. Source dimensions and display zoom are separate facts; bytes/rights/currentness gates and
source-change cleanup remain. This is not a new derivative, LOD/cache policy, coordinate transformation,
measurement or server contract. Actual acceptance will inspect visible pixels plus view transform/state
and reset, not require changing the immutable source-buffer dimensions to prove a zoom occurred.

Valid first-unit actual outcomes preserved: direct Materials/Analysis and Header return to exact2022DSM,
reload and legacy section redirects, same-area/source comparison recovery, existing512x256 partial DSM,
synthetic800m3 result→exact record→saved non-field review, wrong-scope nondisclosure and real viewer
permissions, zero API POST/page errors. Those do not excuse the failed map task. Primary restored only
the owned frontend to35d2ded0 while correcting the regression; stopped3b318e6d container retained for
evidence/rollback. Core8074/issuer/journals/S3/worker/security/shared-host state unchanged.

Correction unit returned: one shared local display-view rule (zoom1/2/4, normalized pan/edge clamp/reset)
and44px SVG control strip now serve the already-guarded mosaic, single-window and partial receipt view.
Native source cover/receipt/grid remain fixed during gestures; display enlargement has a separate status.
Normal mobile date selection stacks full-width; version/precision caption avoids repeating the whole
capture/kind label; long area names have a labelled non-hover disclosure. No-candidate comparison folds
inapplicable pair/numeric guidance into a closed secondary disclosure; ready pair geometry is secondary.
Full host176files/1693tests/type/lint clean; new full-four-tile test checks preserved decoded paint with
no extra GET/POST during local zoom/pan/reset. Locked build and actual corrected render are pending;
these counts alone still do not establish the approved UX outcome.

Actual corrected8cecb0cb checks: all workspace/navigation/result/permission tasks passed. Keyboard zoom,
mouse drag, focus-intent wheel and reset retain source1022x915/884413opaque pixels and unchanged raw-buffer
hash1436974531; CSS image rectangle changes and the actual image remains visible. **Additional display
GET0 and API POST0** across gestures, not newly prepared tiles or replayed fixture images. Real phone-width
zoom/reset clicks, partial-DSM controls, Back/Forward and sticky-tool containment also passed.

Row compaction alone had not fixed the phone tool's vertical position in the previousfc0604ec render
(y823–867 behind fixed nav). Primary's tightly coupled finish uses existing mobile-bottom-nav clearance
for sticky tools contained strictly within the picture+tool section, not floating over unrelated record
details. Final measured phone tools y738–782, all7targets44x44 and unobstructed. The whole512x256 crop
now fits the default phone frame (322x161 display) rather than an implicit intrinsic-width clip; guarded
native buffer/SHA/relative-shading meaning unchanged. A focused regression covers fit/reset, image-section
containment and no extra GET/repaint. Current locked176files/1694tests/type/lint passed.

Explicit visual trade-off: mobile readable full-width capture control257px, visible revision/unknown
precision and long-name disclosure take more top space: first image y526/h288 versus earlier35d y443.5/
h265. The image still appears in the first viewport; a contained tool strip overlays its lower part so
all controls remain accessible instead of being behind global nav. This is not claimed as an image-y or
cold-performance improvement. Desktop image y391/h520 and all controls fit1440x1000. Category-familiar
interaction and source findability improve while retaining the monochrome identity and five Site areas.

Automated limited axe scans found no A/AA-tag violations but flagged a paragraph aria-label for manual
review. Primary removed the redundant prohibited paragraph name (visible native text/full-name disclosure
remain); the semantic-only final build and final current-build witnesses are the remaining closing step.

#### Researched spatial UI improvement — delivered acceptance, 2026-10-21

Final frontend **4595e1ea** is served by the normal private Console10010 → owned labelled Docker3243 →
unchanged Core8074. Only the owned frontend was replaced; retained prior containers/images allow rollback.
Core readiness/private login return200/ready. No backend, schema, worker, journal repair, source byte,
permission/policy/grant/retention/AI-egress, basemap, LOD/cache authority or deployment exposure change.

| Research issue / user task | Delivered actual outcome |
|---|---|
| F1 overlapping navigation and gateway | One primary `탐색 / 두 시점 보기 / 분석 결과` navigation. The five supporting Site areas remain in a labelled keyboard-operable menu. Registered materials and analysis records link directly to existing owner routes; legacy section links redirect compatibly. Real2022DSM→Materials/Analysis→Header return retains exact source/area. |
| F2 familiar display operation | Local CSS display zoom1/2/4/pan/reset on the already guarded buffer; mouse drag, focus-or-Ctrl wheel, keys and buttons share the rule. Actual zoom/drag/reset preserves1022x915 source hash1436974531 and884413 opaque pixels; the rendered rectangle changes, image stays visible. Additional display GET0 / API POST0 during gestures. No new preparation to make a pretty screen work. |
| F2 mobile control access | At390x844 all7buttons are44x44, y738–782, unobstructed above fixed bottom nav. Actual mobile-width button clicks work. Sticky containment is limited to picture+controls and was exercised when scrolling to technical details. Default partial DSM shows its whole512x256 buffer fitted322x161; actual partial zoom/reset works. |
| F3 meaning and recovery | No-candidate Floreat view has one typed reason and actual same-area/source exploration recovery. Inapplicable pair/analysis/preparation guidance is in a closed secondary disclosure. Existing chronology/registration/quantitative gates stay fail-closed; no synchronized/heatmap or fake coastal quantities. |
| F4 read vs prepare | Guarded GET/decode is `자료 읽는 중`; actual server preparation remains `준비 중`; missing own output/window is distinct from missing registered data and from failure. No merged verified/READY badge. Targeted state tests retained along with rights/SHA failure checks. |
| F5 original/version orientation | Full-width mobile capture selector257px, selected registered revision and unknown precision readable without hover; real date/layer, reload and browser Back/Forward retain exact2022 ortho/DSM identity. Unknown/date-only facts are not converted into full timestamps. |
| F6 result/evidence continuity | Actual synthetic800m3 record keeps10/6→10/13 inputs, limits and exact result/area link. Real click reaches saved non-field review; human target/opinion/limits precede technical refs. Synthetic quantities remain separate from real coastal imagery; review is not official approval. |
| Permission/recovery regression | Real viewer has metadata/own-output-unavailable state and no preparation capability. Explicit wrong scope exposes no substituted picture or800m3 result. Preserved size/SHA/currentness/ownership/phone write gates; no automatic API writes in any tested path. |

All final actual witnesses identify **build4595e1ea**, `ok=true`, zero intercepted write attempts and
zero browser errors: `workspace.json`, `records-permissions.json`, `input-accessibility.json` under
`/tmp/opencode/ksi-spatial-ux-improvement-20261021/`. Primary read latest actual default/zoomed phone,
desktop exploration, no-candidate comparison and affected partial/review captures; this is not code-only
or a separate demo. Failed3b review and fc phone-placement evidence are separately labelled, not final
acceptance. Temporary sticky DOM study was explicitly a layout experiment, not delivered-product proof.

Final locked Next16.3.3/Vitest4.1.11 build and **176files/1694tests** passed, host tsc/changed ESLint clean,
mechanical detector[] on changed surfaces. Limited final axe WCAG2/2.1 A/AA-tag scans at390 and1440:
zero automated violations and zero incomplete rules. The paragraph name was removed while native text
remains. These checks are not WCAG certification or physical SR/touch/customer usability research.

Visual identity/first-view trade-off described above remains explicit: the full-width date, readable
revision and long area orientation consume more top space on phone than35d, while actual imagery is
still in the first viewport and all controls are now available there. This is a task-access improvement,
not a claim of faster cold loading, a larger source, continuous map streaming or a new GIS analysis.
No public/customer beta, field accuracy/settlement, retention, shared inspector recovery or full-platform
completion gate is implied. Existing audit branches remain protected/unresolved and new inspection
worker remains stopped; neither is a dependency of these accepted display/navigation reads.

Durable evidence: `~/.local/share/ksi-product-use-20261021/ux-improvement-4595e1ea/`, README + SHA manifest.
This closes the latest approved researched UI/UX improvement unit. No concrete in-scope functional or
rendered blocker remains in the verified target conditions. Real participant comprehension, physical
touch/SR and unobserved datasets/device conditions remain separate unverified acceptance, not invented
success. Further feature/LOD/cache or general redesign work is not silently selected at this close.

### 2026-10-21 — Human questions whole-Console UX maturity and menu structure

Latest Human asks comparative level against other UX/competitors and points beyond Site entry to menu
structure. This is assessment, not a new implementation approval. Earlier4595e1ea completion is the
bounded researched Site task, NOT mature whole-product IA/customer usability. Previous global Home/nav
exclusion is a dated implementation boundary, not a permanent rejection of improving those surfaces.

Git7fc81eb6/main=origin revalidated. Reviewed current global/nav/more/palette/Work/Inbox source, current
static More/support renders and previously captured normal Home/Sites plus current4595 Site evidence.
Official Propeller navigation/home support image and prior DroneDeploy compare sources remain references,
not logged-in competitive testing. Newly fetched Propeller home original is SVG despite an extensionless
attachment; primary converted/read it and did not infer the UI from metadata. No code/build/ops changes.

Confirmed whole-IA gaps: mobile More occupies a primary tab for only an out-of-product Dock/Edge boundary
notice; desktop exposes the same legacy notice persistently. Work mixes observation records with entry
to assigned/shared Inbox and team controls, requiring users to learn internal distinctions. Site area's
`현황` plus spatial modes and `분석 결과` vs `분석·검토 기록` still need a product-wide naming/responsibility
model even after hiding the competing row. Palette current-Site routes are pathname-only and omit the
source/WorkArea context now preserved by Header (code evidence; not reproduced live in this pass).
Previous normal Home/Sites have large generic covers/registration-oriented summaries; those captures
are structure evidence, NOT proof of today's mutable data state. No arbitrary maturity %/SUS score or
unverified competitor superiority in accuracy/permissions is claimed.

Material runtime observation at22:18KST: owned frontend4595e1ea still running/health200, but Core8074
loopback readiness connection failed and no listener was present; Home rendered honest connection/error
state. Normal full-flow re-observation is blocked. Root cause/data state unknown; NO Core/service/journal/
credential/shared-host restart or repair attempted during an assessment question. Current static More/
support renders have this connection banner and are labelled accordingly. Earlier successful4595
witnesses remain historical as-of-run evidence, not current service availability. Native focus screenshot
again failed visible-tab; only own new tab closed and isolated Playwright used.

Assessment direction: functional early product with partially improved Site interactions; whole-Console
task/IA coherence is unfinished compared with published mature spatial-workspace patterns. Next design
unit should define global vs Site-local vs object-detail ownership and user-task labels together, then
consistent entry/return/search/support across connected screens, preserving Core scope/semantics and
legacy deep links. Not another isolated Site polish or automatic new global capability/index/schema.
Evidence /tmp/opencode/ksi-console-ia-assessment-20261021/; real customer participants still0.

### 2026-10-21 — Human approves whole-Console task/IA improvement

Latest Human “그렇다면 개선해봅시다” follows the whole-Console maturity/menu assessment, and explicitly
broadens this UI unit beyond the former Site-only boundary. Deliver actual Console global→Site→object
workflow coherence, not another isolated view polish or standalone demo. The change remains a UI/UX
improvement, not a new platform capability, global data authority/index, acquisition or production gate.

Requirement IDs: REQ-UX-101; SDP-REQ-01/02/05/06/07; accepted ADR-025/026 responsibilities under039;
existing research findings plus latest whole-IA assessment. Owner module: apps/dashboard. Acceptance:
clear global Home/Sites/업무 and supporting account/help, legacy Dock/Edge links retained but removed
from primary task priority; distinguish received assignments/shares from observation records without
changing Core meanings; coherent Site/record/task labels; Header/palette/direct links preserve exact
scoped navigation and frozen result inputs; current account/logout reachable on phone; Home/Sites use
actual meaningful facts/actions rather than large empty covers; search/filter/paging, roles and
unavailable states remain honest and usable; actual whole-product390/768/1024/1440 renders/flows.

Contracts affected: no API/schema/data/permission/retention change. ADR-025 D7 records the latest Human
Home visual-structure approval, superseding only D6's fixed empty/large-cover ratio; original D6 retained.
D1 priority/dedup, D2 manual mobile navigation/reduced-motion and D3 image rights/D4 update semantics
remain. INV-020/024/040/051/053/060/061 enforced by unchanged Core/guarded-byte paths, truthful metadata,
scope resolver/navigation tests and real no-write workflows. No SiteStatus semantics/accuracy/approval
inference, other-requester bytes, AI grant, unsupported new global search/index or derivative authority.

Reference assets: previous real4595 Site proofs, historical normal Home/Sites captures, current static
global-menu renders, official Propeller navigation/home and DroneDeploy compare originals. No repeat
generic research/new external assets. Adoption: preserve current mono/tokens and working spatial display;
global vs Site vs object responsibilities; task-first Home/Sites; labelled secondary account/help;
one shared allowlisted UI navigation context, no persistent browse journal. Files: nav/shell/palette/
SiteHeader and related owner pages/helpers; field/inbox/team presentation; Home/Sites presentation and
focused projections/tests; nearest README/reading-aid updates only where needed. No backend code/schema.
Tests: owner targeted/full Dashboard regressions, tsc/eslint, locked image build; real authorized
Home→Site→date/DSM→context-search→materials/result→review→workflow/account, old deep links and roles;
four Home viewport/state checks mandated by025. HIL: none; physical touch/SR/customer research unverified.
License/data: existing CC BY attribution, no new fonts/basemaps/image egress or thumbnail pipeline.
Rollback: prior owned frontend4595e1ea; retain images and old visual evidence.

Runtime prerequisite: own source-run Core8074 has no listener; bounded log tail shows graceful shutdown
at22:02, cause unknown, not an observed journal/parser failure. Primary may resume ONLY the existing
task-owned Core8074 with exact preserved env/config and durable core-data via its existing runner;
preflight snapshot/hash and no replacement/repair/permission widening. All durable journal contents,
S3/originals, external auth/activation, shared inspector branches/staging/daemon/cgroups and all other
processes protected. Do not start a worker/inspection/job or alter service/security settings. If replay/
configuration fails, preserve evidence and stop that path; no repair disguised as UI work. This is not
permission to recover the separate shared inspector audit incident. Main owns runtime/browser/docs/Git.

Two cohesive independent implementation owners will run with exclusive files: A navigation/work/account/
scoped-context; B Home/Sites task presentation. Shared labels/semantics contract: global `홈/현장/업무`,
supporting `계정·도움말` on existing/more; `받은 업무` vs `관측 작업` remain distinct; Site current `공간자료`,
`등록 자료`, `분석 기록·검토`, `현장 작업`, `현장 설정` (keys/routes unchanged), spatial results-mode is a
summary, not a competing history/review authority. A owns shared navigation constants/helpers; B reuses
paths/labels and cannot edit A files. Neither owns servers/browser/docs/commits/host operations. Primary
integrates and judges the rendered whole journey, not isolated child success or test counts.

#### Whole-Console integration review — 2026-10-21/22

Primary resumed only the existing owned8074 source runner after verifying exact preserved env/config
and no listener. All14 original journal byte prefixes were checked unchanged; no repair, new worker,
inspection, S3 or security setting change. Normal baseline4595 Home/Sites captured at390/768/1024/1440
after resumption, plus actual observation queue and Inbox. Runtime cause of earlier graceful shutdown
remains unknown; this does not establish production service management.

First integrated7f4d45b1 passed locked178files/1720tests/type/lint, and actual four-viewport Home/Sites,
view preference/search/Back and healthy whole journey checks. Primary read all4 Home originals, default
list, work/Inbox/account desktop/phone. The profile/scoped palette input is an ARIA combobox; an initial
test used textbox and was corrected without changing the product. Loading Inbox capture was retained
as loading evidence and later awaited to a settled state rather than called an empty/error result.

Selective independent Plan review of the approved scope found two material uncovered cases. They were
returned directly to the same unit owners and implemented, not dismissed because happy checks passed:
- A: bare analysis deep links can have a server-resolved WorkArea absent from URL. Header now exports
  its own allowlisted navigation hints; palette consumes them only for the matching currently authorized
  Site/path and missing fields. Explicit URL area is never overwritten; missing asset can be filled only
  from a matching Header area; explicit malformed/empty/duplicate asset presence is not backfilled.
  It is a UI navigation hint, never analysis selection or byte authority. Two-area/malformed/cross-site
  regressions and actual bare/area-only entry paths were checked. No extra API/provider/browse journal.
- B: failed list/target/review reads and bounded/truncated review coverage no longer become empty arrays
  followed by `확인 필요0곳`. Existing bounded reads now retain unknown Site IDs; current-target receipt
  matching remains unchanged. Known pending actions still display, incomplete counts/recovery stay
  unknown. Successful empty reads remain distinct. Nine fault/truncation/projection regressions cover
  this without writing real records or deliberately stopping the product Core for error screenshots.

New default dense table labels its existing ordinal SiteStatus visualization `관리 단계`, not dataset/
capture/processing/analysis progress. Canonical state/index/resolver unchanged. Primary also fixed the
new account unknown branch's invalid p/form nesting and kept team shortcut visibility consistent with
known Work navigation authority; logout remains available in unknown/expired state. Generated .next*/
test-results/playwright-report are excluded from the frontend build context, including test credentials.

Corrected source5063b515: locked179files/1738tests/type/lint passed. Normal private frontend updated;
actual `portfolio.json`, `whole-journey.json`, `roles-display-a11y.json` all build5063b515/oktrue/zero
intercepted product writes/page errors. Actual checks include four Home/Sites viewports, preference and
filter/Back, Home→its exact priority record, current2022DSM palette→materials/analysis→Header return,
bare-record server scope and area-only resolved-source parity, saved synthetic800m3→exact review,
observation vs received-work navigation, account/logout and secondary legacy boundary, external-results
history alias, wrong-scope nondisclosure, real viewer/phone logout and retained guarded display gestures
with no extra byte reads. Shared inspector history remains untouched and unresolved.

Limited axe checks: no automated A/AA-tag violations in Home390/account390/Sites1440/work1440. One Home
contrast incomplete rule was manually inspected: an aria-hidden decorative middle dot, not information,
state or required text. It is labelled as a reviewed non-text separator, not suppressed to fake an
unqualified checker pass. Physical touch/SR/customer comprehension still unverified.

Existing E2E regression cases were preserved and updated for legitimate labels/list default/direct
routes/disclosures/D7 visuals. Four old repository Home goldens copied before rebaseline; actual private
renders remain separate product proof. A task-local existing local-seed E2E run is pending, with
3230/8032/9030 preflight-free, fresh runtime directories, production credential env scrubbed, UV no-sync/
offline and no Tailscale configuration. It targets neither Core8074 nor S3. Initial runner used an
unexported CLI subpath and failed before starting any service; it was corrected to the already installed
project CLI. No dependency installation or check weakening. Regression results/golden review remain
to close before final acceptance; source/witnesses are in /tmp/opencode/ksi-console-ia-delivery-20261021/.

#### Whole-Console IA/UX — delivered acceptance, 2026-10-22

Latest Human-approved scope is the whole-Console navigation/task improvement, not only Site entry.
Final frontend **860eeced** is running on the existing private10010 → owned labelled Docker3243 →
owned8074 Core with the same preserved data/config. Actual readiness/private login return ready/200.
No new Core API/schema/index, numerical policy, permission, retention, source/derivative authority,
AI grant, external provider, worker/inspection/job, public exposure or customer production change.
The separate shared inspector audit incident was not repaired/rebased; branches/staging remain protected.

| Approved outcome | Implemented and verified result |
|---|---|
| Global responsibilities, not a legacy support tab | Primary Home/Sites/업무 and phone 계정. Actual account/role and existing logout work on phone; current-role help links remain bounded. Legacy Dock·Edge notice is secondary and its old route/return remain honest, not a future feature promise. |
| Work that people can distinguish | Observation records and received assignments/shares have named, active sibling navigation, with known-authority team entry. Organizational records are not relabeled personal tasks and Core statuses/counts are unchanged. |
| Meaningful Home entry | Actual Site, typed pending action, why, source-appropriate record time and exact working CTA precede any optional image. Large empty decorative cover removed. Priority/per-Site dedup/current-target matching/image access/update meaning preserved; no imagery or capture time invented. |
| Home failed/partial reads | Bounded/truncated/unavailable analysis-review reads retain unknown rather than0; successful empty and current reviewed cases remain distinct. One recovery notice + closed specific reasons keeps known actions usable; per-result numerical limits are still persistent near their value. Eleven fault-state regressions, plus actual isolated partial-capability renders reviewed in4 widths. |
| Sites used to find a place | Dense list default with compact optional cards, no empty/fictional cover. Existing user preference wins; actual search/sort/filter/pagination/draft-cancel/IME/duplicate-name/Back and creation permission checks preserved. Existing ordinal state bar is explicitly management stage, not dataset/analysis progress. |
| Coherent Site/object ownership | Five Site areas have consistent task labels and retained keys/deep routes. Result summary is distinct from original analysis record/review; external history stays a separate owner. Old external-results alias reaches that history, not KSI calculations. |
| Context across all entry types | Header/palette share allowed UI context, including server-resolved bare analysis link and area-only source resolution. Explicit area/asset/malformed/multi-value precedence is conservative; bridge must match current authorized Site/path. Actual2022DSM→palette/materials/analysis→Header roundtrip, bare and area-only paths and wrong-scope closure passed; two-area parity is separately regression-tested. No selector/input/authority substitution. |
| Preserve working real data experience | Existing guarded ortho/partial DSM display, local zoom/drag/reset and exact raw-buffer integrity remain. Actual display gestures add no byte reads or automatic PREPARE/calculation. Synthetic800m3 and stored non-field review remain exact and separate from real coastal imagery. Viewer sees truthful own-output availability without another actor's bytes or mutator shortcut. |

Final actual product witnesses all identify **860eeced**, `ok=true`, zero intercepted product-write
attempts and zero browser errors: `portfolio.json`, `whole-journey.json`, `roles-display-a11y.json`.
Primary personally read current4 Home widths390/768/1024/1440, dense Sites, work/Inbox, account/Viewer
and related context/material/result/review renders; changed workflows were exercised, not just paths
saved. Unknown/fault projection tests and isolated test-state images are labelled separately from
normal private-product data. Real participants=0; no competitor equivalence, physical touch/SR or
field/accuracy/settlement/production acceptance is claimed.

Final locked Next16.3.3/Vitest4.1.11 image build + **179files/1740tests** passed; host tsc/changed ESLint
clean; mechanical detector[]. Existing isolated local-seed browser regressions: **100passed,24expected
viewport/fixture skips,0failed** across4 specs/124cases. Tests retained exact one-card/filter/race/
scope/role/no-write assertions: failed preconditions were corrected to real nonempty group membership,
not skipped, relaxed, assigned a longer timeout or satisfied by changing fixture/product statuses.
All fixture3230/8032/9030 listeners were removed on teardown, and credential env was scrubbed; no
product8074/S3 or shared runtime was used. Four old repository Home goldens were preserved before
ADR025D7 rebaseline; primary read all4 new partial-state goldens and kept source-specific reasons
discoverable. Next's generated AGENTS change was Markdown heading depth only, not instruction content.

Limited final automated a11y checks found no A/AA-tag violations in Home390/account390/Sites1440/
work1440. One Home incomplete contrast rule is an aria-hidden decorative middle dot, manually inspected
and not a required text/state signal; it is recorded as such, not silently filtered to claim blanket
certification. Physical assistive/input-device and customer comprehension checks remain unverified.

Visual/task trade-off: Home no longer reserves a large empty image rectangle; real typed action and
Site identity are earlier. Dense list is the new-user default while saved gallery choice remains.
The supporting account/help route replaces the formerly unproductive primary More tab; legacy support
content is not deleted. Exact scope/rights/unknown semantics were chosen over blanket READY or a fake
map/gallery. The result is a coherent implemented improvement, not a claim of mature commercial UX.

Evidence root `/tmp/opencode/ksi-console-ia-delivery-20261021/`; durable copy
`~/.local/share/ksi-product-use-20261021/console-ia-delivery-860eeced/` with README + SHA manifest.
Core's original14 journal prefixes are rechecked; normal product runtime stays available and prior
owned frontend images remain for rollback. Only user-owned untracked.playwright-cli is excluded.
No concrete in-scope implementation or verified-target blocker remains. The approved whole-Console
IA/UX unit is complete; no further feature/LOD/cache work, new customer study or unrelated redesign
is silently selected. Future customer-comprehension/scale/device evidence remains separate, not invented.

### 2026-10-22 — Human reports loss of uploaded-data thumbnails at Site entry

Human: “왜 업로드한 자료 썸네일? 그게 없어졌어 현장 볼 때”. This corrects the prior interpretation
that text-first default/no image region was sufficient. Preserve visual recognition of actual data;
removing an empty decorative cover was not permission to remove meaningful preview access. Do not
turn this feedback into a universal preference for giant images or restore fake covers as real uploads.

Read-only current860eeced observation: /sites defaults to dense table, no img/canvas; card source has no
image region. Site bare/explicit2021 entry still draws actual Floreat pixels through the existing
guarded output path (initial captures are progressive loading, not missing uploads). Core8074 ready/
running, source-data deletion not observed. Existing catalog remains metadata-only and grants no bytes.

Requirement IDs: REQ-UX-101; SDP-REQ-01/03/06; latest visual-recognition feedback. Owner module:
apps/dashboard Site entry/list/card and bounded read-only preview presentation. Acceptance: real,
currently authorized prepared data visible as a thumbnail/preview on Site entry where available;
fresh-user cards/visual entry default, explicit saved list preference preserved; compact actual cue in
list/mobile; thumbnail click opens exact WorkArea/asset/date version; no decorative fake photo/full-Site
coverage/accuracy or invented latest capture; no available own output means honest preview-unavailable,
not missing registered data. Preserve search/sort/paging/draft/roles, existing Site viewer and no auto jobs.
Contracts affected: no Core API/schema, new derivative producer, persisted cache/thumbnail pipeline,
permission/grant/retention change. Reuse existing currently requester-owned COMPLETED/AVAILABLE prepared
output metadata and SAME guarded file GET+size/SHA/decoder. Catalog alone never authorizes bytes; don't
read raw sealed artifacts/object keys or borrow another requester's window for display. No PREPARE/
inspection/analysis POST or worker start merely to populate thumbnails. Bound metadata fanout/visible
page/decodes; no source/coordinate/WorkArea calculation changes. INV-020/024/040/051/053/060/061 preserved.
Reference assets: current observations /tmp/opencode/ksi-site-preview-feedback-20261022/; existing real
prepared-output preview/Mosaic decoder and source/date/version helpers, no new external assets.
Adoption: visual recognition restored with actual lawful pixels, no placeholder map/stock photo;
partial outputs labelled partial; viewer/denied/unavailable remain distinct. Files: Site list entry,
cards/dense/mobile, small bounded server-preview selector/client renderer and focused tests; existing
receipt renderer may gain a narrowly scoped thumbnail presentation only if needed. Home D3 image
authority is unchanged and not automatically broadened. No global redesign/LOD/producer or Core change.
Tests: metadata selection/budget/own-source/scope/no-output, guarded bytes/SHA/403/404/auto-write0,
card/list prefs/query/links, actual private default card/list/mobile and exact preview→Site transition,
type/lint/full Dashboard/locked image and related existing E2E. HIL: none; physical inputs/SR/customer
study separate. License/data: existing public-data attribution; no new egress/storage. Rollback:
owned frontend860eeced; preserve current UI/context work, journals/env/S3/inspector state and user files.

Additional read-only fact at this feedback: settled Site now paints3/4, not the older verification's4/4.
Existing own request detail identifies top-left job `sdj-v1-6ff0ab18-d223-451a-9a49-b2e4541aa7e2` as
COMPLETED / **RETENTION_EXPIRED**, while the other3 original grid jobs remain AVAILABLE. This is a
separate finite prepared-output lifecycle event, not upload deletion or authority to extend retention.
Current metadata observation is `current-window-availability.json`; first min-pixel captures were
progressive and must not be called full coverage. Preview selector must exclude expired outputs and
label any surviving partial window honestly. No re-preparation/TTL change/cache retention to force a
thumbnail. An always-available, cross-requester registered-asset thumbnail producer/access contract is
not silently created by this UI correction; report that capability limit if it remains necessary.

### 2026-10-22 — Human rejects the button-first spatial interaction

Human says the UI is still difficult and asks why the up/down/left/right and plus/minus buttons are
there, saying button operation is hard/unfamiliar. This corrects the prior focus on fitting all7buttons
into the viewport. They were fallback controls, not a reason to make people learn an unusual primary
interaction. Do not generalize this into a ban on every map zoom control; direct manipulation must be
the default and alternatives discoverable without dominating or obscuring actual data.

Requirement IDs: REQ-UX-101; SDP-REQ-01/02/05/06; latest direct-manipulation feedback. Owner module:
Dashboard shared prepared-pixel viewport (mosaic/single-window/receipt display). Acceptance: source
follows a desktop drag continuously at pointer speed; mouse/trackpad wheel over the picture zooms
without prerequisite focus/Ctrl or2x jumps and preserves the point under the pointer; familiar tested
touch pan/pinch where implemented; visible fit/reset/large-view affordance but no primary7-arrow/zoom
strip; focused keyboard alternative retained; concise truthful guidance. Page scroll outside the
picture and browser accessibility not globally disabled. Full/partial data, source/date/version,
rights/size/SHA, masks/NoData and frozen calculation/WorkArea untouched; every gesture/root control
uses already-lawfully decoded buffers and causes no file preparation, byte fetch burst or API writes.
Contracts affected: none; display geometry only, not geographic/measurement/flight coordinates or
new raster/LOD/producer authority. INV-020/024/040/051/053/060/061 preserved through source-bound
presentation and current Core guards. Reference assets: current860 viewport/UI evidence plus direct
feedback; existing installed interaction libraries/patterns only, no new font/icon/tile/remote assets.
Adoption: direct mouse/touch manipulation first, concise on-demand help and keyboard fallback; no
invented empty pixels, fake basemap, unimplemented gesture hints or hidden focusable viewer controls.
Files: display-view/gesture helper and shared viewport/control presentation; Mosaic/Windowed/Receipt
view integration and focused regressions. Home/global nav/list preview UI source ownership separate.
Tests: continuous drag BEFORE pointer-up,1:1 motion, anchored wheel from unfocused hover, clamp/reset/
pointercancel, automated touch/pinch if supported (not physical touch evidence), keyboard, no extra
GET/POST/polygon/input changes; actual private desktop/mobile renders and whole-flow regression.
HIL: none; physical touch/SR/customer testing remains separate. License/data: reuse current packages
after license compatibility check; no new egress/storage. Rollback: ownedfrontend860; preserve all
protected journals/env/S3/inspector state, byte-policy expiry and user files.

Independent owner A now exclusively owns shared interaction files while existing B continues Site
thumbnail/entry correction. B must not edit Mosaic/Windowed/Receipt/control/display-state modules;
A must not edit Sites/card/list/preview route/descriptor. Main integrates both current feedback units
and reviews actual combined renders. Retention-expired outputs stay unavailable; no jobs/TTL changes
to make the interaction or thumbnail look complete.

Current input baseline was measured on real860 data: unfocused wheel over the picture leaves rendered
width580.8 unchanged; after explicit zoom, dragging100CSSpx moves the image51.2CSSpx during the gesture
because the wide gray frame1134px was used instead of fitted picture580.8px. Existing code did update
during pointermove; the defect was normalization plus a hidden focus/Ctrl prerequisite, not total absence
of drag. A owns a shared direct viewport and source-bound tests; Main flagged fitted-anchor/pinch-centroid
geometry and overlay-button capture for correction before accepting actual renders.

B returned a standalone passive Site preview unit using the existing guarded prepared-output file BFF,
with default cards (saved list retained), compact row cues and exact source/area links. Primary source
review required explicit partial-window labels, DTO/job/receipt/site/area binding validation, metadata+
decode chain concurrency/abort bounds and accessible attribution. Successful descriptor caching was
removed; primary also removed same-Site shared in-flight lookup reuse so a new mount/session never
inherits another mount's abort or old current-rights result. A regression forces an old canceled lookup
to finish after a new mount and verifies fresh current metadata/no inherited bytes. Declared GSD is
labelled submitted, not measured. No persistent thumbnail/rights cache or source-byte authority added.
All representative prepared windows are labelled partial; absent preview is not absence of registered
data. A and B own separate files and have no permission to start jobs, change retention or recover the
shared inspector incident. Combined rendered acceptance remains pending, not established by unit counts.

Final-regression correction plan (same requirements/owner/invariants above): isolated four-spec run
returned98pass/24expectedskip/2fail. Both failures were the newly added assertion treating the seed
profile's unmounted spatial-data-requests route as a successful empty lookup. Original trace and Core
log show404 for that route and actual BFF200 `{available:false,reason:"unknown"}`; rendered cards
correctly say the preview could not be checked, not that data or output is absent. Keep the product
and fixture unchanged. Change only `e2e/sites-view-modes.spec.ts` to require the exact BFF unknown
response plus the same card's unknown explanation, no confirmed-empty copy and no fabricated canvas.
Preserve all124 cases, fixture/viewport skips and empty-success unit coverage. Rerun the existing
isolated suite with credential scrub/no-sync/offline, then confirm3230/8032/9030 teardown. No Core,
contract, license/data, HIL, security, retention or runtime change; rollback is this assertion diff.

Incomplete-rule follow-up found a real caption issue, not a clean accessibility certification:
same-build axe cannot resolve three photo-gradient contrast nodes. Primary read actual390/768/1024/
1440 renders and sampled text-free backgrounds over each actual text range. Conservative white-text
minimum contrast is2.38–4.14 for source/partial captions (date lines mostly exceed4.5); the gradient
is not reliable over bright imagery, and the `shrink-0` metadata line clips on phone. This affects
required source/partial/date recognition, so fix it rather than suppress the incomplete nodes.

Requirement IDs: REQ-UX-101, SDP-REQ-01/03/06 (same approved correction). Owner module: Dashboard
passive Site preview caption. Acceptance: source/partial/date/submitted precision stay readable on real
photo at all four target widths, contrast>=4.5:1, no clipped metadata or fake pixels; exact link,
permissions and no-auto-job behavior unchanged. Contracts affected: none. Reference assets: current
94925ba4 renders and `contrast-observations.json`/`contrast-samples.json`, not an unrelated visual style.
Adoption: use the existing solid `bg-accent`/`text-accent-on` pair for the compact caption instead of a photo-dependent
gradient, allow metadata to wrap; no new components/assets/fonts/dependencies or effects. Files to
change: SitePreviewThumb.tsx and its focused regression only. Tests: focused/full Dashboard, type/lint,
locked build, actual current card/list/phone/link and contrast/a11y check; unaffected direct-input and
whole-journey witnesses remain valid by unchanged-source comparison. HIL: none. License/data: no new
access/storage/egress. INV-020/024/040/051/053/060/061 enforcement unchanged through the same exact
guarded read/source labels; this is caption CSS only. Rollback: owned94925ba4 image/inverse CSS diff.
Wait for the active source-reading isolated regression to finish before editing its live source.
No new inspection/preparation worker, retention extension or shared-audit repair is authorized.

#### Combined feedback — delivered actual-target verification, 2026-10-22

Final code **bd40df2a** is running on the existing private10010 → task-owned labelled frontend3243 →
durable Core8074/issuer9042. Source commits: b0830257 (real visual entry/shared direct viewport),
94925ba4 (native SVG reset guard), bd40df2a (reliable caption contrast/wrapping and exact unknown-state
regression). Only the owned frontend was replaced; Core ready=true, private login200 and prior owned
images are retained for rollback. No product schema/API, source/accuracy authority, grant, retention,
AI egress, external tiles/CRS, worker, shared inspector repair or customer production change.

| Approved task outcome | Current implemented result / evidence |
|---|---|
| Recognize a Site from actual data | Fresh cards default, explicit saved list choice retained; actual guarded pixels on card/list/phone. Current decoded window510×512/259642opaque pixels displays452×254,54×42 and332×186 respectively. Synthetic Site never borrows coast imagery; viewer never borrows another requester's output. |
| Open the previewed observation | Click targets its exact workAreaId+assetRef. Partial window, date-only/unknown time, revision, submitted GSD and accessible attribution remain tied to that source; no whole-Site/accuracy/latest-capture inference. |
| Familiar direct manipulation | No primary7-arrow/+-strip. One shared fitted viewport for Mosaic/Single/Receipt, direct live mouse/pen/touch geometry, unfocused cursor-anchored wheel, on-demand help/focused keyboard and a small corner fit button. Actual60px drag moves image59.98px before mouseup (old100px moved51.2). Actual SVG-button reset works. |
| Preserve the data while exploring | Off-center wheel anchor stays within2CSSpx, source dimensions/hash unchanged, extra byte reads0 and automatic write attempts0. Existing partial/NoData/mask, rights/lifecycle, WorkArea and frozen calculation selectors remain separate from display transforms. |
| Read the preview information | Gradient's real2.38–4.14 contrast issue corrected with existing solid accent/on pair; all4actual widths390/768/1024/1440 have uncut text ranges. Sampled minimum8.45:1 (normal16.14). Real photographic cue remains visible; no new decorative asset. |
| Keep working product context | Final bd40 actual whole-journey checks preserve Home→exact priority record,2022DSM+WorkArea palette/Header roundtrip, search cancellation/focus, bare/area-only links, separate synthetic800m3 and saved non-field review, observation vs received work, account/logout, external-history alias and invalid-scope closure. |

Final actual `direct-input.json`, `previews.json`, `page-gestures.json`, `whole-journey.json`,
`contrast-observations.json` and `a11y-details.json` all identify bd40df2a,oktrue,zero intercepted
product-write attempts and zero browser errors. Primary personally opened final card/list/phone,
four-width captions, desktop wheel and phone pinch/fit, exact stored review and settled2022DSM
materials images. The first materials capture was a transition skeleton, not accepted settled evidence;
its replacement waits for actual registered-list/selected-data headings and2022 content before capture.
Older949 four-viewports and unaccepted b083 diagnostics remain labelled, never relabelled final.

Touch pan/pinch/double-tap2x, outside-image page scroll0→285 and native-selection keyboard handling
passed CDP input simulation. This is not physical touch, SR or real-customer research. Final limited
axe A/AA-tag checks: Sites0violations/0incomplete; settled Space0violations/one canvas-backed
contrast incomplete. Primary manually reviewed the actual missing-cell label: RGB78/83/89 on sampled
RGB250/250/250 is7.44:1. The original incomplete is retained, not suppressed into blanket compliance.

Final locked image build and **182files/1797tests** pass; host tsc/changed ESLint clean; mechanical
detector[]. Final four-spec existing isolated browser suite on committed bd40: **100passed,
24expected viewport/fixture skips,0failed**, no automatic golden updates. The original2failed
assertions and screenshots are preserved. Exact BFFunknown+same-card explanation/no-fake-canvas
replace the incorrect successful-empty assumption; successful-empty coverage remains in unit tests.
All124 cases, bounds/scope/rights/race/search/paging/no-write intent remain. Credentials scrubbed,
UV no-sync/offline, fresh seed state;3230/8032/9030 listeners absent after teardown. No product8074/S3
or protected shared runtime used by the fixture suite. All14original Core journal hash prefixes
rechecked intact; legitimate append-only current-state/audit events are not rewritten or truncated.

Evidence root `/tmp/opencode/ksi-visual-direct-entry-20261022/`; durable copy with original feedback,
input baseline, actual final witnesses, rejected/diagnostic states and SHA manifest:
`~/.local/share/ksi-product-use-20261021/visual-direct-entry-bd40df2a/`. This is verification evidence,
not a thumbnail serving cache or a source-byte grant. User-owned untracked.playwright-cli is untouched.

**Explicit remaining limits:** current prepared source is3/4 because the top-left job is retention-
expired, not because the uploaded artifact was deleted. No job is automatically recreated, TTL/grant
extended or another actor's pixels substituted. The real canonical sanitized-display references remain
null/pending in both Floreat submissions; an always-present/all-actor upload-thumbnail producer is
**not implemented or verified** by this correction. The separate shared inspector audit incident stays
unresolved/protected, its new worker stopped. Producer work/recovery is a genuine separate boundary,
not quietly authorized by UI feedback. Physical input/SR/customer studies, real customer IdP/data,
public production/TLS and field/settlement accuracy remain unverified/external as before.

The bounded UI correction is implemented and verified in the actual product within current output
availability; no further concrete UI defect remains from this review. This does not close the product
slice, certify mature commercial UX/competitor equivalence, establish stable preview production or
declare the whole platform/customer/field gates complete. Stop this refinement rather than silently
selecting a new producer, LOD/cache, unrelated redesign or shared-runtime repair.

### 2026-10-22 — Human asks for a composed thumbnail where no preview exists

Human: "표시할 미리보기 없다면 이전처럼, 구성되는 섬네일도 좋지 않나". Combined with the earlier
instruction that the Console must not show users everything difficult, and that usability carries the
product. This is a refinement of the SAME visual-entry correction, not a new product slice.

Interpretation fixed before implementation: "이전처럼" refers to the fact that a card always had a
recognisable tile, NOT to restoring the deleted `DefaultSiteVisual` (c343ee7b) — that one was a
`siteId`-hashed decorative SVG with no relation to the site, deleted in7f4d45b1 as fabricated cover.
INV-040 forbids mock/placeholder/static always-go, and a synthetic terrain drawing presented as a
site image would be a fabricated data claim. A composed thumbnail is therefore built ONLY from the
requester's own current records.

Read-only fact check against the real product (bd40df2a, own session, 10010): the work-area list
returns each ACTIVE area's real registered polygon, CRS and name for both `prod-sample-floreat-01`
(EPSG:7850,4-vertex ring) and `prod-sample-site-01` (EPSG:5186). The registered-asset catalog
(metadata only, `NOT_AVAILABLE_FROM_CATALOG`) lists real kind/capture/lifecycle facts for both sites
(Floreat ortho+DSM 2021-08-17 and 2022-08-24; synthetic ortho+DSM 2026-10-13/2026-10-06). So a
composed tile can be composed from real geometry plus real registered records without any new byte
path, producer, grant or cache.

Requirement IDs: REQ-UX-101; SDP-REQ-01/03/06; 2026-10-22 composed-thumbnail feedback. Owner module:
Dashboard Site entry visual tile (server-side composition + client presentation) and its focused
regression. Acceptance: (1) when a lawful prepared pixel preview exists it still wins and is
unchanged; (2) when it does not, the card still shows a composed, site-specific tile instead of an
empty box — the site's own real work-area boundary shape, in its real registered CRS, plus the real
registered-asset kinds and capture periods; (3) the tile is unmistakably NOT imagery: it says so in
visible copy and in the accessible name, claims no coverage/accuracy/completeness, and is never
described as a photo; (4) an empty/absent record set produces an honest plain state, not an invented
shape; (5) no new Core API/schema/producer/grant/retention/cache/byte path, no coordinate
reprojection, no external tile/basemap, no fake CRS, and no automatic job; (6) exact-area deep link
and the current permission/ownership/scope checks are unchanged; (7) the tile is legible at390 and
1440 and does not push the card's identity/action below the fold.
Contracts affected: none (read-only reuse of the existing work-area list and existing metadata-only
catalog; presentation only). INV-020/024/040/051/053/060/061 preserved: real geometry is drawn in its
own registered CRS without reprojection or unit claims, no accuracy or completeness claim, no
placeholder data, no cross-principal disclosure, no change to source/derivative authority, and
analysis/readiness/rights semantics stay separate. Reference assets: current bd40 real renders and
the read-only probes above; the existing `SiteNativeExtentSvg` native-plane projection rules and
`site-spatial.ts` ring/CRS/unit helpers are the adopted reference for drawing real boundaries
honestly. Adoption: reuse the incumbent native-plane projection and existing tokens, one composed
tile type shared by card/list/phone, no new component library, font, tile service or dependency.
Files: Site list visual tile composition + its presentation component and focused tests; the existing
preview BFF/route/decoder stay as they are unless the composition needs a bounded metadata read
(reuse `listWorkAreas`/catalog metadata only). Tests: composed-tile selection (real geometry +
real records), CRS/unit honesty, no-geometry/no-record honest empty state, real-pixel priority,
no-catalog-byte-access, exact deep link unchanged, existing preview/permission suites preserved,
full Dashboard + type/lint + locked image, and actual private renders at390/768/1024/1440 read by
Primary. HIL: none; physical touch/SR/customer study remain separate. License/data: no new egress
or storage; only current-session metadata already authorized for the visible site. Rollback: owned
frontend bd40df2a image plus the inverse of the composition diff; no data/journal/env/S3 change.

Stop rule: a composed tile may show only the site's own real registered geometry and real
registered-asset facts. If the honest composition cannot be drawn, the card shows the plain
unavailable state. Never fall back to decoration, seeded art, a stock coastline or any pixel that
is not the requester's currently permitted prepared output.

#### Composed thumbnail + first-screen declutter — delivered 2026-10-22

Human asked for the composed thumbnail where no preview exists, then asked to apply everything
discussed: "처음 보는 사람이 자료와 다음 행동부터 이해하도록, 화면을 덜어내는 방향으로" — first
screen = site, capture date, data and the main action; long ids, hashes, processing history and
technical settings behind on-demand disclosure; fewer duplicate titles/menus/explanations and bigger
actual data; operator language instead of internal system terms; **but decision-relevant limits
(부분 범위, 분석 불가, 정확도 미확인) stay visible next to the related action**. "사용성이 그런게
제일 중요하니까 제품은" and "사용자들이 봤을 때 너무 어렵고 불편한 내용까지 다 보여줄 필요 없어".

**Composed tile (real records only).** The deleted `DefaultSiteVisual` was a `siteId`-hashed
decorative SVG with no relation to the site (c343ee7b → deleted 7f4d45b1) and was NOT restored.
Instead the tile is composed from the requester's own records: the site's real registered ACTIVE
work-area boundary drawn in its own registered CRS (no reprojection, no basemap, no fake CRS, no
hillshade/photo styling) plus the real registered-asset kinds and capture periods (≤8 facts, honest
`외 N건`/`외 더 있음`/`N건 이상` when truncated). Visible copy and accessible name both say
**범위 도식 · 사진 아님**; the row cue carries a `도식` badge. The server aggregates in the sites
page with the same session (≤6 areas, ≤50 catalog items/area, ≤8 facts, ≤48 sites/render, 6
concurrent); a per-site failure (including 403/404) yields no descriptor, so the existing honest
empty/unknown copy remains. The client re-validates the descriptor and rebuilds the expected href
locally (`sanitizeSiteVisualTileDescriptor`), so a foreign/absolute/swapped URL cannot render.
**Real pixels still win**: the composed branch is reachable only when the preview lookup is
empty/unknown. No bytes, object keys, signed URLs, catalog `dataAccess`, automatic PREPARE/inspection,
new Core endpoint/schema/producer/grant/retention/cache, or cross-principal disclosure.

**First-screen declutter (site detail explore).** The side column now leads with the next action
instead of counters; 관측 작업/분석 결과/외부 비교 기록 counts, registered area name/date/CRS and
ids moved into a `구역 등록 정보·개수` disclosure. The shared `SiteAreaNextAction` /
`resolveSiteAreaNextAction` pair is used by BOTH the explore first screen and the overview column
so one area never proposes two different actions; on the explore screen the primary action appears
**above the picture** with the other entries behind a `다른 보기` disclosure. The always-visible
gesture hint was shortened. `SiteHeader` and `SiteExploreCanvas` were left alone on judgement:
they are already collapsed/quiet and their wording is test-pinned, and the `선택 중 · 등록 버전 N ·
날짜만 확인 · 시각 미상` line is the only place that precision fact appears.

**Defect found by actual rendering and fixed.** The first composed build left every card stuck at
"미리보기 불러오는 중": the composed descriptor was re-created on every render, so the preview
effect's dependency changed each time and the lookup restarted in a loop. Fixed by memoizing the
validated descriptor (`useMemo` over the raw technical object) and depending on presence rather than
identity. The jsdom suite could NOT reproduce it (the effect→render cycle does not close there), so
a referential-stability regression was added and verified to fail when the fix is reverted. A second
actual defect — the caption escaping the card and pushing site identity/action off-screen on
390px — was found in the real render and fixed by making the caption part of the figure's flow
(`flex flex-col`, diagram `flex-1 min-h-0`, caption `shrink-0`), with a regression asserting the
caption is not absolutely positioned.

**Evidence.** Actual private10010 → owned frontend3243 → durable Core8074/issuer9042. Final
locked build **ee3c5f4c→(current)** with **184files/1830tests** pass, host tsc and changed ESLint
clean, mechanical detector[]. Actual renders at390/768/1024/1440 were read by Primary: the Floreat
card keeps its real guarded pixels (510×512/259642opaque), the synthetic site shows the composed
range diagram with its real boundary and real registered-asset facts, the caption stays inside the
card at every width, the composed tile opens the exact work area scope
(`wa-prod-sample-site-01-0001`), the site detail first screen prints no work-area id, asset ref
or file name by default, and the next action is present on the first screen. Zero intercepted
product writes and zero browser errors in every actual run.

Final same-committed **68d3030a** existing isolated four-spec browser suite: **100passed, 24expected
viewport/fixture skips, 0failed** (4.2m) with the exact sourceRevision bound in the result JSON, no
automatic golden updates, credential-scrubbed/no-sync/offline seed profile and no 3230/8032/9030
listener left behind. It never touched product8074, S3 or the tailnet services. Durable evidence for
this unit: **165files** + SHA manifest at
`~/.local/share/ksi-product-use-20261021/visual-direct-entry-68d3030a/` (current verification/ and the
older 94925ba4 evidence kept separate so no build is relabelled).

**Still true after this work.** Real prepared pixels remain the primary visual; the composed tile is
a substitute for sites with no currently permitted output, never a photo claim. There is still **no
always-available all-actor upload-thumbnail producer** — that is a producer/retention decision, not
a UI one, and remains an explicit capability limit. The shared inspector audit incident stays
unresolved and protected; no worker was started. Physical touch/SR, real customer studies, customer
IdP/data, public production/TLS and field/settlement accuracy remain unverified/external.

#### Core storage-child defect and the composed tile's real extent — 2026-10-22

**What was found while verifying the UI work.** The real product stopped serving prepared
output bytes: every read of a prepared window returned 503. The data was healthy the whole
time — the bucket, the object, the credentials and the byte digest all matched. The cause was
in Core, not in the Console: the storage child was `os.fork()`ed out of the running ASGI
server. A forked child of a THREADED process inherits only the calling thread while the
parent's other threads keep holding their locks, and the child's own descriptor sweep races
the parent's threads. Under real load the child could not finish its SDK work, so the
request failed as `STORAGE_UNAVAILABLE` — a storage outage that was not one. The refusal was
also reported as a generic 503, which HID the real reason.

**The fix (Core, `services/core/src/ksi_core/domains/external/delivery/`).** The child is now
a FRESH interpreter (`exec`): it inherits no parent thread, no parent lock and no parent
descriptor. The work crosses the boundary as PLAIN DATA — an operation name plus its exact
parameters — never a callable, closure, SDK client or credential object; the child rebuilds its
own bounded client and refuses one that would exceed the policy (single attempt, SigV4,
timeouts within the deadline). The parent re-proves the child's answer, keeps capacity until
the OS confirms the reap, and treats a failure frame as TERMINAL so a caller never waits for
a reply that cannot arrive. The in-process `fork()` path is removed: the product had exactly
one caller and it now uses the exec child.

**Verified against the real product.** The same read that returned 503 now returns its
ACTUAL state: `RETENTION_EXPIRED` (410). The prepared output had genuinely expired on its
24-hour retention at 06:32 today; the defect was hiding that. Nothing was deleted, no
retention was extended, no output was re-prepared, no grant was widened. The composed tile
now carries the truth for such a site instead of a generic failure.

**Contract evidence.** `tests/contract/test_spatial_data_storage.py` (66 cases),
`test_spatial_data_storage_supervision.py` (7), `test_spatial_data_storage_threaded_parent.py`
(3) and `test_spatial_data_storage_types.py` all pass; the whole `tests/contract/` suite is
5675 passed / 33 skipped with 6 pre-existing `test_core_module_migration.py` failures that
reproduce identically on the unmodified tree (verified by stashing this change). ruff and mypy
are clean for the delivery package. The supervision tests were rewritten to the exec child
while keeping their INTENT: a real separate process, bounded framing, a stall killed within
the total deadline, and capacity released only after the OS confirms the reap.

**Composed tile, second step.** The composed tile drew only the work-area boundary, and every
sample boundary is a rectangle, so two different sites looked identical. It now ALSO draws the
extent an INSPECTED raster actually covers, taken from that raster's own measured transform,
in its own plane — real coverage, never an invented one, and nothing is drawn when the file
was not inspected or its extent is in a different plane. The work-area boundary stays the
outline; the file extent is the shaded area inside it. No reprojection, no basemap, no
invented coverage; the tile still says `범위 도식 · 사진 아님`.

**Scope held.** No Core API/schema/producer/grant/retention/AI-egress change, no new
dependency, no bytes beyond the existing guarded path, no dashboard/server change for the
Core fix, no change to the existing contract suite's intent, and the shared inspector
incident, journals, protected config and S3 objects were not touched. The owned Core was
restarted on the same durable data directory and the same preserved environment; all 14
journal prefixes were verified intact (only append) before and after.

#### Human-directed viewer-first workspace restructure — 2026-10-22 (P0 integration)

The current Human request supersedes the earlier checkpoint's “no new redesign” limit for this
bounded UI unit: simplify site navigation, give spatial data the primary workspace, make observation
selection immediate, and move repeated per-tile status to a legend/details. It does not approve
re-preparation, new retained previews, wider grants, worker/inspector recovery, reconstruction,
quantitative rule changes, or whole-platform/field acceptance. Existing PRODUCT.md's five-area
summary is subordinate and stale for this new navigation request; historical records stay intact.

Requirement IDs: Human P0 (menu/header, viewer proportions, observation selection, blank-map states),
SDP-REQ-01/02/03/05; INV-020/024/040/051/060/061.
Owner module: apps/dashboard (Console presentation only).
Acceptance criteria: four directly visible site sections; same-frame single/compare/results modes;
area/observation/layer rail; scoped immediate GET selection with no-JS fallback; native geometry or
verified pixels lead; conditional detail panel; no per-tile status overlay; unknown/denied/expired/
NoData and quantitative suitability remain distinct; 390/768/1024/1440 real renders and interaction
checks; existing four-spec isolated regressions, unit/type/lint and locked build preserved.
Contracts affected: no API/schema/data/admission change. One existing blocker-catalog guidance
sentence uses 관측 시점 instead of 촬영 시점; keys/owner/target unchanged and generated copy synced.
Reference assets: incumbent Console/components/tokens, actual before images under
/tmp/opencode/ksi-first-reader-20261022/layout-before-*.png, user's PIX4Dcloud/DroneDeploy/Propeller
layout observations (pattern references, not code/assets), isolated component images explicitly
labelled /tmp/opencode/ksi-workspace-unit-20261022/latest-*.png.
Adoption decisions: adapt the existing native viewer, GET forms and scoped navigation; no external
code/font/basemap. Correct delegated routing hypothesis: section=work-orders is an observation-work
record list, not WorkArea management. Label it 관측 작업 기록 and preserve its old URL; 작업구역 관리
must point at the actual /work-areas owner page. Four primary sections stay as requested.
Files to change: current Dashboard SiteHeader/Workspace/Explore/selection/legend/viewer files,
site-epochs/context labels, connected materials/work-area presentation, their tests and existing
operations-console E2E; this same ledger/checkpoint. No new task ledger.
Tests: full Dashboard Vitest, tsc, changed ESLint; blocker-catalog sync contract; locked image build;
existing isolated operations-console/sites-view-modes/sites-controls/sites-pagination specs; read-only
private Console journeys and multi-width renders. Component fixtures are not product acceptance.
HIL or real-device assumptions: none. Physical touch/native Korean IME/screen-reader acceptance is
not inferred from Chromium/CDP/jsdom; real pixels unavailable under current prepared-output retention.
License/data implications: unchanged CC BY attribution and synthetic labels, no new external assets,
bytes or egress. Geometry fallback uses inspected native file extent, not valid-pixel/accuracy claims.
Rollback: retain preceding owned frontend image/container cf985644; revert only this UI commit set.
Protected resources: all Core durable journals/config/credentials, S3, shared inspector incident and
all unrelated containers/ports. Only existing task-owned frontend3243/private10010 may be replaced
using its retained rollback. No Core restart or preparation/inspection/analysis issuance for this UI.

##### P0 integrated result — 01c74afd, 2026-10-22

- Four site sections are visible without a disclosure. Modes share the same workspace chrome;
  the desktop rail is260px; a selected-information panel occupies320px only on demand at wide
  widths. At1024px it is inline rather than squeezing the viewer to a narrow strip. Existing
  scope/URLs remain. `작업구역 관리` now opens actual `/work-areas`; observation work records retain
  `?section=work-orders` as `관측 작업 기록` under the 자료 context, not falsely as area management.
- The separate full-width recent-analysis card is gone; the area's next action lives in its
  selection rail. Observation and layer GET selections immediately navigate, including keyboard
  selection and browser Back/Forward. Important date-only/partial/accuracy limits stay visible;
  identifiers and coordinate diagnostics are on demand. Phone rail was reduced327px from484px
  after actual render review; tablet202px from389px, without hiding the observation selector.
- Actual expired/no-prepared-pixel state uses inspected native file extent and same-plane WorkArea
  geometry labelled `범위 도식 · 사진 아님`. It does not claim mask-valid coverage or accuracy.
  Execution-deadline expiry, retention expiry, cancellation, denied and unknown are distinct;
  a larger WorkArea does not enlarge the numbers labelled file extent. Valid-byte canvas rendering
  keeps its native ratio and verifier. Per-window map text/borders removed; status/recovery remain
  in legend and details. No diagnostic toggle is shipped without authoritative admin permission.
- Actual owned Console01c74afd: admin widths390/768/1024/1440/1920, wide/inline inspector, current
  blocked compare (date-only coastal records), exact separately synthetic800m3 results, materials,
  settings/actual WorkArea/legacy records and read-only-role390 personally rendered/read. The
  WorkArea transition capture was rejected and replaced with actual loaded form/list content;
  background map editing was not operated. No product writes/page errors. Main axe0violations and
  0incomplete after correcting the named viewer's semantic role. Native DOM worked but pointer and
  visible capture failed; repeatable actual Playwright used (not physical-device evidence).
- Final committed-lockfile image build +188files/1864tests pass; host tsc/changed ESLint clean;
  detector[]. Existing isolated four-spec regression on01c74afd:100pass/24expectedskips/code0;
  no test listeners left, no golden updates or permission/fixture/data changes. Initial4 failures
  were a new test's incorrect assumption that the empty-observation fixture must have a select;
  it now checks the no-candidate recovery and absence of invented selection, while the real
  populated journey exercises actual immediate date selection. Blocker-copy sync contract3pass.
- All14 protected journal byte prefixes and lengths remained unchanged; Core not restarted;
  S3/grants/retention/config/inspector incident untouched. Only owned frontend3243/private10010
  replaced; previous images/containers retained. Build context came from `git archive`, excluding
  unowned untracked pnpm manifests and user `.playwright-cli/`, both retained untouched.
- Worker isolation mistake: unrelated stash86adc2f8 was accidentally applied. Main compared the
  only introduced test file to the retained stash blob f9f95adc27f563e466df60a7a944e46dfa2ab54f,
  removed only that accidentally staged/worktree copy, and confirmed both original stash refs
  retained. No unrelated file was committed. Evidence records containment; no shared state repair.
- Durable evidence: `~/.local/share/ksi-product-use-20261021/workspace-layout-01c74afd/`, SHA manifest,
  real renders/interaction JSON, exact E2E/runtime provenance and protected-prefix check.

**Not whole-scope completion:** P0 structure has integrated evidence, not a completion claim for
P1 synchronised visual comparison, P2 expanded lineage/reuse UX, real pixel/physical-touch/SR or
platform/customer acceptance. All current prepared output pixels remain expired and were not
re-prepared. Fully JS-disabled browser integration is blocked by the existing hidden streamed
Suspense ancestor; only the selection form's SSR fallback is verified. Further original-goal gaps
must be considered separately from the completed structural unit; no product-state slice closes.

##### Next approved outcome — P1 independent pair/context/analysis journey (2026-10-22)

P0 handback is accepted as a bounded unit, not the whole Human P0/P1/P2 request. Read-only Plan
cross-check found independent implementation remains feasible even though current pixels expired.
Main continues without asking for routine reapproval or selecting another product-state task.

Requirement IDs: Human P1 and related P2 existing-record discoverability; SDP-REQ-01/02/03/05.
Owner module: Dashboard UI and additive pure navigation helpers; Core contracts unchanged.
Acceptance criteria: explicitly select two same-area exact material revisions for independent visual
inspection, including literal date-only/unknown precision; preserve pair/layers through modes,
relevant navigation/Back/reload; hand off exact submission/revision hints only when matching current
server analysis candidates; no approximation by WorkOrder alone; show actual existing eligibility/
blockers and open an exact recorded result; return context never changes frozen result inputs.
Contracts affected: no wire/schema/source/admission change. Keep old strict compare helpers and deep
URL semantics. Add separate explicit UI visual-pair intent; never manufacture displayReady/viewAvailable
or chronologyCandidate. Existing guarded requester-owned prepared outputs remain the only byte path.
Reference assets: current01c74afd workspace and P0 actual evidence; Constitution/ADR036/037/038/039,
existing workspace UX design, source AnalysisObservationOption exact selectors and immutable results.
Adoption decisions: independent side-by-side browsing; preserve literal precision and exact versions.
No synchronized spatial camera: established pair-display geometry is absent. The Human-directed
registration/purpose-split document is DESIGN ONLY (header), not an implemented authority path;
its stated evidence/purpose constraints and the incumbent fail-closed geometry rules are preserved.
PairRegistration shape/equal CRS/common grid/CSS transforms are not registration evidence. Do not
introduce sync, shared crosshairs, difference-colouring or any implied quantitative compatibility.
Files to change: Site workspace/page/compare/result/header context, analysis page/panel and additive
operator-journey/visual-intent helpers, focused Dashboard tests/E2E as needed. No Core/API/grants/
retention/registration/worker/inspector change, no separate ledger or redesign of Home/list.
Tests: existing strict-path negatives unchanged; date-only/unknown independent intent; foreign/repeated/
invalid fail-closed selection; exact layer revision; scope/mode/Back/reload; exact analysis candidate
matching; no deep-result/pending-attempt overwrite; browsing-vs-frozen inputs; no automatic POST;
full Vitest/type/lint/build/isolated regression and actual legal metadata/context journey.
HIL or real-device assumptions: none. Lawful fixture pixel checks explicitly simulated; real-pixel
comparison remains unavailable due expired outputs; physical/native-input acceptance absent.
License/data implications: no dependency/asset/egress/cache/producer; source attribution and per-user
rights unchanged. INV-020/024/040/051/053/060/061 enforced by distinct typed UI intent, exact matching,
existing guarded bytes, untouched quantitative chronology/compatibility and immutable results.
Rollback: revert P1 UI commit set to already verified01c74afd; retained frontend/runtime unchanged
until Main builds/reviews a new owned image. No shared-state restore/repair is authorized.

P1/P2 real verification preconditions revalidated (read-only, existing human-session BFF GETs):
Floreat `analysis-observations`200 returns0 candidates; the separate SYNTHETIC Site200 returns2.
Existing synthetic analysis `analysis-v1-a54a41705b90721036d77c30ab698d28`200 remains COMPLETED /
PROVISIONAL_ACCURACY_UNVERIFIED, cut0/fill800/net800m3, uncertainty null, result
`report-d12897aa3511adcaa7afdcd7e6b9efb4`, report digest
`sha256:bff0b46aecf16dfb026503b051a3b03fed90b59b88e93b51cafe8941e61edc39`.
Its exact input triples remain obs-work-00000001/ers-v1-5fe272105b7cc7adc910d7705fd6e62944c17201ac5394e4565bdf7cc5b5e3ed/rev1
and obs-work-00000002/ers-v1-a275552ba0056ad9012d30a49d0416f61af825ebd1ac630a8ca2061ef4d6ef3d/rev1.
Evidence GET200 returns19 typed items (two epoch identities, calculation identity, evaluations,
authority/source references, numeric result and limitation), evidenceRevision1. Witness:
`/tmp/opencode/ksi-workspace-journey-20261022/existing-reuse.json`. No product writes; not a new
calculation, reproduction, external-client or MCP execution proof. The MCP adapter's existing
local-stdio `ksi_get_analysis`/`ksi_get_analysis_result` share the same Core V2 detail route;
separate MCP identity, explicit Site AI-egress consent and ALLOWED response are still required.

P2 existing-record disclosure implementation plan (parallel, disjoint files):
Requirement IDs: Human P2 lineage/reuse discoverability; SDP-REQ-03/05/06, INV-020/024/040/051/060/061.
Owner: Dashboard analysis presentation. Main owns only new AnalysisRecordReuse.tsx and its focused
unit test while the P1 implementer owns analysis/page/panel and navigation. Main integrates after
that worker returns; no overlapping edits. Acceptance: selected authoritative AnalysisView supplies
its exact original input triples, request/result identity, evidence revision/digest and permissioned
Console permalink; calculation profile/runtime/WorkArea definition appear only from matching loaded
evidence pages (same analysisId+revision+digest), not fabricated or joined across revisions. The
main screen stays concise; technical details disclose on demand. Explain current suitability versus
immutable numeric record and that links do not grant access. API/MCP reference shows only existing
Core V2 paths and existing local-stdio query argument identities, with separate authentication and
AI-egress consent caveats; no endpoint/host/vendor/public support or connection activation claim.
Contracts/dependencies/licenses unchanged; no requests, clipboard credential, external URL, download
producer, registration or new computation. Tests cover exact binding, stale evidence refusal, no
result/no profile honesty, encoded local links, closed disclosure and absent write controls. No HIL;
actual synthetic metadata/evidence GET identity already revalidated, not calculation reproduction or
MCP execution. Rollback: remove this UI component/integration only. Broader saved-comparison storage,
registration geometry authority, grant budgets/tolerances remain separate decisions, not required to
expose already existing record lineage truthfully.

P1/P2 first integrated render — 9769724d (not final acceptance): locked191files/1899tests and
existing4spec100pass/24expectedskip, exit0/no test listeners. Owned frontend replaced only; Core
unchanged. Actual GET-only journey passed explicit coastal date-onlyA/B, URL-selected DSM through
reload/modes/BackForward, no-candidate analysis return, exact synthetic input draft, original frozen
800m3 inputs/report identity preserved, matching evidence/profile and permissioned record link,
repeated query refusal and plain-analysis axe0/0. No product POST/pageerror. First selector failure
was ambiguous getByLabel matching both select and labelled section; it now scopes to the rail.

Primary personally read actual390/768/1024/1440 comparison and analysis/reuse captures. Necessary
correction batch: compact the overly long comparison rail (tablet area was vertically centred in
a stretched grid row; phone viewer below the first viewport), retaining explicit A/B fields,
literal precision and visible unregistered limitation by the panes; detailed repeated explanation
moves on demand. Also exact-input analysis navigation must land at the request/conditions section,
not first scroll through history. Preserve read-only context return even where compact mutation
controls are hidden or no result exists. No authority/data/retention/grant change. Same General owns
only ExploreCanvas/WorkspaceCompare+focused tests; main owns Header/AnalysisRequestPanel+tests.
Final rendered confirmation and original-goal reconciliation follow this batch, not aesthetic churn.

Read-only final-direction review found two further source-confirmed handoff defects in the same
unit, not new scope: rail actions concatenated a second workAreaId, which the receiving visual
context parser correctly rejected; and the pair-specific CTA (as well as the header) omitted the
conditions anchor. Main now merges allowed context keys uniquely, cannot overwrite a fixed
analysisId, preserves the pair on the related materials action, and attaches the conditions anchor
only for exact-input draft handoff. Ordinary history/record links remain record links. Added tests
cover unique scope, fixed-record identity, array/foreign context refusal and the actual receiving
context parser. The review judged existing-record P2 disclosure adequate without new owner policy
or an MCP-host claim; no other substantive unblocked implementation unit was identified after the
planned composition/handoff corrections. This is advisory source review, not final rendered proof.

Compact-rail handback integrated: WorkArea row stays at the start across tablet columns; one tight
explicit A/B GET flow; long repeated concepts disclose near the panes, leaving literal identities
and no-registration status visible. Small-screen layers collapse but keep the same portal nodes.
Main replaced the worker's CSS-only closed-details exposure: hiding its summary on an engine that
lacks ::details-content could strand the controls, and its open state would disagree with visible
content. A small native SiteLayerDisclosure instead uses the actual responsive open attribute,
leaves its summary/heading reachable on every engine, is open by default on desktop/closed on phone,
and respects explicit user toggling. No new fetch/write/dependency or authority. Server/Client
props stay serializable ReactNode slots. Added desktop/phone/SSR fallback tests; main host193files/
1913tests, tsc and changed ESLint pass. Final committed-image/runtime verification still follows.
