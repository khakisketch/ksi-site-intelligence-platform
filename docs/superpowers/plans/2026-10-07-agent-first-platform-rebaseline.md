# Agent-first platform rebaseline — discovery ledger

Date: 2026-10-07
Status: written spec approved; foundation implementation plan prepared for Human review; execution NOT approved
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
- [ ] Human reviews written foundation plan and selects execution method.
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
