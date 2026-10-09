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
