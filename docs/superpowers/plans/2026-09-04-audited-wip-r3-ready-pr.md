# Audited WIP Integration and R3 Ready PR Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to
> implement this plan task-by-task. Only one writer may own the integration worktree at a time.

**Goal:** Reassemble the audited WIP as responsibility-owned commits, keep R3 as the final three
repository-boundary commits, push one integration branch, and open a Ready PR only after remote CI
passes.

**Architecture:** The Human-owned `main` worktree remains untouched. The existing isolated candidate
first records exact pre-R3 and R3 snapshot commits, then a new integration branch is rebuilt from the
approved base with semantic hunk ownership and per-commit verification. Only the final integration
branch is pushed; snapshot history remains local recovery evidence.

**Tech Stack:** Git worktrees/index, uv, pytest, Ruff, mypy, npm/Vitest/Playwright, CMake/CTest,
Docker static checks, GitHub CLI.

**Spec:** `docs/audit/WIP_CHANGESET_AND_R3_PR_PREPARATION_2026-09-04.md`

## Execution-ruling amendment (2026-09-05; controls task ordering)

The original Task 8-after-Task-7 order would create a fourth commit after the intended final R3
triplet. Therefore Task 8's current-state/audit content is executed immediately after Task 6 and
before Task 7. At that point it records only pre-R3 truth: exact base `41d9f55`, completed pre-R3
commits `6f4b768..7f9801f`, final pre-R3 tree `2cc35c2`, Task 6 document/history reviews PASS, and
local-only snapshots `ca723d41`/`b23ee101`. Its next step is the R3 triplet. The R3 lineage commit,
not this state commit, owns final Phase Registry repository-normalization status. This amendment does
not change product scope, R3 content, or acceptance gates.

The remaining order is Tasks 1-6, Task 8 (pre-R3 state evidence), Task 7 (the final three R3 commits),
Task 9, then Task 10. Any wording below that says Task 8 consumes completed R3 history or makes R3
current is superseded by this amendment.

## Global Constraints

- Base is exactly `41d9f55270581d9660664f6c23c65ab0d7af0a4a`; source branch is `main` and
  its index remains empty.
- Candidate starts with 201 staged pre-R3 paths and 144 unstaged/untracked R3 paths.
- Final branch is `integration/audited-wip-r3`; only it may be pushed.
- Final delivery is one PR targeting `main`; intermediate snapshot branches are never pushed.
- No reset/clean of the Human source worktree; no merge, release, deploy, credential, device, HIL,
  field, or reference-submodule action.
- R3 changes repository placement only. Stable distributions/imports remain
  `ksi-change-detection`/`ksi_change_detection`, `ksi-bim-integration`/`ksi_bim_integration`, and
  `ksi-defect-detection`/`ksi_defect_detection`.
- Preserve `INV-003` with the no-reference-import gate and `INV-054` with runtime image pin checks.
- `.ai/` and `.ksi/` are RETAIN evidence; `.ksi` is never hand-edited.
- A failed or non-started remote check keeps the PR Draft and the goal incomplete.

## Required Implementation Plan

```text
Requirement IDs:
  WIP-CAP-AUTH, WIP-MISSION-ATOMICITY, WIP-PROCESSING-FENCE, WIP-CIVIL-READINESS,
  WIP-HIL1R-SOFTWARE, WIP-REPO-R0-R2, WIP-REPO-R3, WIP-STATE-META, WIP-AUDIT-META,
  R3-STR-001, R3-DOC-001, R3-REACH-001, R3-LINEAGE-001, R3-WIP-001, REQ-OPS-101
Owner module:
  release integration; each product hunk retains the owner recorded in REPOSITORY_STRUCTURE.md
Acceptance criteria:
  exact snapshot preservation; responsibility-pure commits; local gates pass; independent review
  returns GO_FOR_PR; one remote Ready PR has all required checks passing
Contracts affected:
  existing WIP Core/OpenAPI/HIL contracts and R3 repository conformance only; no new semantics
Reference assets:
  source WIP, pre-R3/R3 candidate, WIP audit, R3 manifest and ADR-KSI-034
Adoption decisions:
  RETAIN all audited WIP; SPLIT by responsibility; MOVE only approved R3 roots; RETAIN AI/KSI state
Files to change:
  no new product implementation; Git history and current evidence documents only
Tests:
  per-owner contract tests; Dashboard checks; HIL host checks; R3 consumers; full Python/static suite;
  remote required checks
HIL or real-device assumptions:
  none; HIL_ROUTE_1 remains BLOCKED_HARDWARE_TOPOLOGY and PEER_TOPOLOGY remains UNRESOLVED
License/data implications:
  vendored license bytes stay unchanged; private/ignored SDK, model, customer and HIL data are untracked
Rollback:
  retain local snapshot branch; delete or abandon only the final integration branch/PR before merge;
  never clean the source WIP
```

---

### Task 1: Freeze evidence and create exact snapshots

**Files:** Source and candidate Git state; no content edits.

**Interfaces:**
- Consumes: source `main`, candidate `prep/r3-service-package-boundary`.
- Produces: two local snapshot commits and their recorded SHAs.

- [ ] Confirm source HEAD/base and empty index; confirm candidate 201/144 split.
- [ ] Confirm candidate is a linked worktree and its ignored PSDK checkout is not staged.
- [ ] Commit the current candidate index as `wip(snapshot): preserve pre-r3 prerequisite tree`.
- [ ] Stage the remaining R3 overlay and commit `wip(snapshot): preserve isolated r3 delta`.
- [ ] Record both SHAs and verify no ignored/private path entered either commit.

### Task 2: Create integration branch and commit R0-R2 governance

**Files:** Repository/parent READMEs, Document Status, ADR-KSI-033, cleanup schema/manifest,
normalization validator/test R0-R2 hunks, archive evidence, `.gitignore`.

**Interfaces:**
- Consumes: pre-R3 snapshot delta.
- Produces: `docs(repo): establish responsibility and document routing`.

- [ ] Create `integration/audited-wip-r3` at the exact base and apply the pre-R3 snapshot with
  `cherry-pick -n`, then unstage without changing the worktree.
- [ ] Stage only `WIP-REPO-R0-R2`; exclude R3 placement, product behavior and state-meta hunks.
- [ ] Run repository-normalization tests and validator without requiring candidate-local protected data.
- [ ] Inspect staged diff and commit with the exact subject above.

### Task 3: Commit Core capability and Mission authority

**Files:** Core capability/domain/auth/app composition and tests; Mission acquisition/site/issuance/
records/work-order modules and tests; only matching OpenAPI/app hunks.

**Interfaces:**
- Consumes: R0-R2 governance and existing domain contracts.
- Produces: capability authority first, then atomic Mission issuance.

- [ ] Stage/test/commit `WIP-CAP-AUTH` as `feat(core): add durable capability authority`.
- [ ] Stage/test/commit `WIP-MISSION-ATOMICITY` as `fix(core): make mission issuance atomic`.
- [ ] Verify no Processing, Civil, HIL or R3 hunk entered either commit.
- [ ] Fix all Critical/Important task-review findings test-first. While later WIP overlaps shared
  files, use owner-targeted `fixup!` commits; autosquash them into these two commits only after the
  pre-R3 worktree is clean and before R3 is applied.

### Task 4: Commit Processing fencing and Civil readiness

**Files:** Core processing/artifact/source modules, Processing Controller, civil-readiness Core/API,
Dashboard component/client/tests and acceptance evidence.

**Interfaces:**
- Consumes: Core authority and Mission state.
- Produces: attempt-scoped publication fencing and read-only Site readiness projection.

- [ ] Stage/test/commit `WIP-PROCESSING-FENCE` as
  `fix(processing): fence attempts and artifact publication`.
- [ ] Stage/test/commit `WIP-CIVIL-READINESS` as
  `feat(console): expose civil readiness evidence`.
- [ ] Run focused Python tests and Dashboard civil-readiness Vitest; verify the projection stays
  read-only and does not claim field acceptance.

### Task 5: Commit HIL-1R software route

**Files:** DJI Gateway runtime seam, Edge PSDK companion/peer, HIL schemas/docs/tools, related CI and
contract tests.

**Interfaces:**
- Consumes: capability runtime contracts.
- Produces: `feat(edge): assemble capability runtime software route`.

- [ ] Stage only `WIP-HIL1R-SOFTWARE` plus its CI hunk.
- [ ] Run Gateway, transport, PSDK boundary, hostile-input, fetch-tool and HIL evidence tests.
- [ ] Run host companion/peer CMake/CTest and sanitizer checks using `/tmp` build paths.
- [ ] Commit and confirm physical/topology status remains blocked/unresolved.

### Task 6: Prove pre-R3 reconstruction plus reviewed corrections

**Files:** Git tree only.

**Interfaces:**
- Consumes: Tasks 2-5 commits plus remaining pre-R3 evidence hunks.
- Produces: the audited pre-R3 tree plus only independently reviewed corrective deltas before R3
  application.

- [ ] Assign any remaining pre-R3 path/hunk to its audited owner; do not create a miscellaneous dump.
- [ ] Commit only when it belongs to an existing responsibility; otherwise stop as a plan defect.
- [ ] Compare the resulting tree with the pre-R3 snapshot; every non-empty delta must be a recorded,
  tested and independently reviewed correction. Reject any unexplained delta.
- [ ] With a clean pre-R3 worktree, autosquash owner-targeted fixups and reverify the final commit
  order before applying R3.

### Task 7: Split R3 into move, lineage and enforcement commits (final three commits)

**Files:** Three old/new roots, workspace/lock consumers, ADR-KSI-034, migration schema/manifest,
repository routing hunks, validator/test R3 hunks.

**Interfaces:**
- Consumes: a tree identical to pre-R3 snapshot, committed pre-R3 evidence, and the R3 snapshot delta.
- Produces: the final three responsibility-pure R3 commits; the lineage commit owns final Phase Registry status.

- [ ] Apply the R3 snapshot with `cherry-pick -n` and unstage without changing the worktree.
- [ ] Commit byte-preserving moves/workspace/lock/path consumers as
  `refactor(repo): move import-only processing libraries`.
- [ ] Commit ADR/schema/manifest/routing lineage and final Phase Registry repository-normalization status as
  `docs(repo): record service-package migration lineage`.
- [ ] Commit validator/contract enforcement as
  `test(repo): enforce service-package boundary`.
- [ ] Require the 144-path allowlist to have zero unexpected and zero missing paths.
- [ ] Run the moved-package/consumer and R3 normalization gates.

### Task 8: Commit current evidence and state (pre-R3 by ruling)

**Files:** `.ai/`, helper-generated `.ksi/`, pre-R3 Phase Registry state, WIP audit and this plan.

**Interfaces:**
- Consumes: completed local pre-R3 integration history and Task 6 document/history reviews.
- Produces: `chore(governance): record audited integration evidence` before R3.

- [ ] Copy the two audit-plan files from the source worktree into the integration worktree.
- [ ] Update `.ai` current sections with pre-R3 evidence and R3-next steps; preserve prior R0-R2 material.
- [ ] Restore existing helper-generated `.ksi` bytes and pre-R3 Phase Registry exactly from `ca723d41`; do not hand-edit or invent capability state.
- [ ] Validate links/state formats, inspect staged diff, and commit.

### Task 9: Run final local gates and independent review

**Files:** Entire integration branch; read-only review artifacts.

**Interfaces:**
- Consumes: Tasks 2-6, pre-R3 Task 8, and final R3 Task 7 commits.
- Produces: `GO_FOR_PR` or a reviewed fix commit.

- [ ] Run lock, Ruff, mypy, full pytest, reference/pin, three Dockerfile static and Compose checks.
- [ ] Run Dashboard install/lint/type/test/build/E2E and host HIL checks.
- [ ] Remove only generated candidate caches and run the cache-safe normalization gate last.
- [ ] Verify source index/HEAD preservation, final commit order and absence of snapshot commits.
- [ ] Dispatch a most-capable read-only final reviewer; fix all Critical/Important findings and re-review.

### Task 10: Push one branch and create a Ready PR

**Files:** GitHub branch/PR state only; no merge.

**Interfaces:**
- Consumes: locally verified/reviewed final branch.
- Produces: one Ready PR to `main` with required checks passing.

- [ ] Confirm the remote final branch does not already exist; push only
  `integration/audited-wip-r3` without force.
- [ ] Create a Draft PR titled
  `feat: integrate audited runtime WIP and R3 repository boundary`.
- [ ] Include commit/change-set table, verification evidence and separate local/remote/deploy/HIL/field
  status axes in the body.
- [ ] Watch all required checks. Application failures get additive owner-scoped fix commits; external
  runner/billing failures remain `BLOCKED_EXTERNAL` and keep the PR Draft.
- [ ] After all required checks pass, convert the PR to Ready. Do not merge.
