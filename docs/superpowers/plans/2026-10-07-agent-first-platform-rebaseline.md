# Agent-first platform rebaseline — discovery ledger

Date: 2026-10-07
Status: Foundation reviewed/independently checked with broad type gate open; P2 written-review pending
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
