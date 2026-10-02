# Main Integration Readiness Review Plan

> **For agentic workers:** This is a read-only review, not implementation authorization. Use requesting-code-review and dispatching-parallel-agents for independent bounded reviews. Do not merge, stage, commit, prune, delete, fetch, install, deploy, or change product files.

**Goal:** Account for every current main WIP file, local/remote-tracking branch and worktree registration, then identify blockers and a safe proposed committed integration baseline.

**Architecture:** Main working bytes, Git graph and preserved recovery/candidate evidence are independent evidence sources. Classify graph containment separately from patch equivalence and semantic adoption. Primary owns the review record; helpers are read-only.

**Tech Stack:** Git, Python evidence inventories, existing Python/dashboard owner checks.

**Spec:** User request on 2026-10-02 to review all branches/worktrees and uncommitted integration state; applicable repository AGENTS.md and original task ledgers.

## Global Constraints
- Preserve main WIP, index, HEAD, all refs and permanent recovery/candidate evidence.
- No new product scope, native execution goal, code fixes or actual integration authorized here.
- Remote-tracking refs are cached observations, not freshly fetched remote state.
- Existing private-bus/host/provider/public-original/customer gates remain explicit.
- Do not record credentials, private customer data, environment values or sensitive output.
- Review records may be created in this recovery checkout; checkpoint records the bounded task without reprioritizing EXT-VAL.

## Review Focus
- main's tested working bytes are not the committed HEAD; a fresh worktree from HEAD omits WIP.
- identical branch tips or Git patch IDs do not establish product acceptance or safe deletion.
- missing temporary worktree directories may have lost uncommitted bytes; refs preserve only commits.
- previous test output applies only to its frozen source/environment, not arbitrary future commits.
- delivery source freeze covers a subset of the aggregate WIP; all additional files need explicit ownership/review.

## Tasks
- [x] Snapshot all main ordinary changed files, local/remote-tracking refs, worktrees, HEAD and empty/nonempty indexes; classify every path by owner and previous integration provenance.
- [x] Review Core/Analysis/catalog/currentness and combined authority boundaries against owner contracts and tests; follow-up seats covered new critical-source remainders.
- [x] Review Delivery/worker/native/storage/API/contracts and existing independent-review evidence; explicitly separate actual main from hypothetical recovery overwrite.
- [x] Review Dashboard/MCP/deployment/consumer/example/tooling compatibility and source-to-test evidence; fresh UI unit/type/lint, browser/build not rerun.
- [x] Review documentation/governance and product/runtime/acceptance claims; large historical ledgers/archives context/provenance reviewed, not every historical word reaccepted.
- [x] Audit branch-exclusive patches including old feature and recovery/autosquash refs; propose retain/adopt/history dispositions without changing refs.
- [x] Reproduce relevant findings with bounded local checks where safe, independently verify helper findings, and distinguish fresh checks from historical logs.
- [x] Audit complete coverage accounting and unchanged original bytes/HEAD/index/refs, summarize blockers and propose ordered integration commits; no merge readiness claim beyond actual evidence.

## Deliverables
- `.opencode/artifacts/main-integration-review-20261002/inventory.json`: per-file digest/owner/provenance and complete refs/worktree matrix.
- Companion review results and check logs in the same directory, with exact source references and unverified work.
- Final review and proposed integration sequence in this ledger and chat. Execution requires a separate authorized integration task.

## Review outcome
**Integration readiness: requires follow-up repairs, not blanket merge.** Inventory314 main ordinary changed files (105 modified/209 untracked); all files assigned/hash-snapshotted.55 local branches +27 cached remote-tracking refs =82 explicitly dispositioned references.44 worktree registrations =3existing/41missing. No fetch/merge/cleanup performed.

Fresh actual-main full under child umask022: **8138 passed, only inherited private-bus1failed,121skipped,93warnings**,758.45s. Dashboard **957 tests in126files**, lint and no-emission/nonincremental tsc pass. CI-equivalent Python Ruff passes; Core boundary inventory173 and diff checks pass. **Broad CI mypy fails/stops** on affine untyped import plus mixed helper module names, unlike the previous four-source gate. Explicit184changedPython lint also sees one app-owned import-order issue outside normal CI;68files have pre-existing/wider formatting debt.

### Required follow-up before declaring the aggregate baseline merge-ready
| ID | Finding | Current evidence |
|---|---|---|
| IR-01 | Dotted organization rejected by owned data key gate | actual validator,503 on supported `org.example` |
| IR-02 | Revoked queued job poisons mixed healthy worker pending poll | real synthetic journals:403 poll, healthy direct lease succeeds |
| IR-03 | Standalone Analysis worker schema has15broken OpenAPI-style ref targets | model-valid nonempty response fails `PointerToNowhere` |
| IR-04 | Aggregate CI mypy cannot finish | duplicate fixture module + affine typing gap; further errors unknown |
| IR-05 | tsconfig WIP includes generated per-run type directories | actual tracked diff/includes; preserve evidence, normalize compiler scope |
| IR-08 | OpenAPI publication has5duplicate YAML keys | values identical; strict loader rejects, standard parser hides duplicates |

The previous goal's bounded local completion remains historical. This new broad review found follow-up requirements; neither a green whole suite, a clean CI baseline, nor release/customer/slice acceptance is asserted.

Details, file:line references, reviewer corrections, test gaps and severity rulings:
`.opencode/artifacts/main-integration-review-20261002/findings.md`.

### Branch/worktree disposition
- main and cached origin/main retained at9edc4a1; main working bytes are newer than their commits.
-25local+19remote contained references and10local equal alternate pointers need no merge; no deletion authorized. Canonical main/originmain are retained separately.
- Seven patch-equivalent references need no merge; five divergent references are semantically adopted/evolved (including inspector-runtime all20paths present,4identical/16evolved).
- Twelve local R3/triage/pre-autosquash/recovery snapshots preserved as historical evidence, not merged as unfinished features.
- Delivery recovery branch15commits preserved; main already contains selective/reconciled task bytes. Do not overwrite Analysis/catalog/governance/shared test surfaces with the less-complete recovery tree.
- `build/a2h-flow-supported` retained: actual managed wire-shape and multi-file digest/binding defects reproduced (IR-06/07), not customer-owned first-release blockers. Two fix candidates `d5701e8/61dda24` require separate approved adoption and current contract/doc reconciliation; three older UI commits are not automatically wanted.
- Existing three worktrees retained;41missing directories are stale registrations, with committed refs preserved but no proof that original uncommitted bytes survive. Neither prune nor branch deletion occurred.
- Exact ref coverage/dispositions: `ref-dispositions.json`; runtime adoption: `inspector-runtime-adoption.json`; all registrations: `inventory.json`.

## Proposed subsequent execution sequence — not executed or authorized by this review
1. **Preserve and select the integration set.** Revalidate this inventory before any operation; carry main's exact314ordinary WIP bytes plus independently approved task-owned repair deltas into a persistent integration context. Preserve both ledgers, original recovery commits, candidate and ignored audit evidence. Identify which archives/plans are committed documentation versus machine-local evidence. Exclude `.opencode/.worktrees/.superpowers/.dev-data`, secrets, fetched SDK/runtime assets and generated test output.
2. **Repair IR01–05 and IR08 with their original-symptom tests first.** Align key encoding without widening arbitrary paths; isolate per-record pending ineligibility without bypassing lane currentness; regenerate a self-contained worker schema and test nonempty reference traversal/deduplicated OpenAPI; unify test-helper module conventions, settle affine typing without hidden suppression/install; normalize durable tsconfig and prevent per-run include accumulation. Source fixes are a separate bounded task; this request did not authorize them.
3. **Verify the repaired aggregate.** Same actual CI Python Ruff/mypy/pytest plus contract/replay/source/rights/storage/worker/HTTP gates, all dashboard unit/type/lint, a source-safe isolated production build and new-page browser/auth/state verification where authorized. Record the unchanged private-bus workstation gate separately; do not convert a known failure into green or omit the broad mypy command. Determine new generated compiler-output scope cannot mask clean-source behavior.
4. **Make coherent local integration commits only when approved.** Separate governance/archive/authority documentation from runtime sets where independently testable. Contracts/model/Core/worker/API/test changes are coupled: do not split into broken intermediate checkpoints merely for directory-based commit labels. Shared OpenAPI, manifests, entrypoints and test guards must include both Analysis and Delivery. Inspect index/diff/exact bytes for every commit. Preserve original source branch provenance even if integration is content-based rather than a blanket merge.
5. **Promote the verified committed baseline to main safely.** main is currently dirty; do not assume any merge/checkout/reset is safe even when candidate hashes agree. Decide explicit WIP preservation/reconciliation and main pointer advancement as part of the authorized integration task. Verify final committed tree, clean/product-WIP state as agreed, parent history and original user bytes. No push/automatic deployment inferred.
6. **Only then branch for the next agreed task from the new main commit.** Review-only completion does not authorize next product scope or close EXT-VAL. Keep external host/provider/public/customer gates open. Branch/worktree cleanup is optional and separate; never remove unique managed fixes or preserved evidence from this review.

## Coverage limits
Every314path,82ref and44registration is accounted for; this is not a complete line-by-line security audit of every historical/unchanged body. New critical runtime remainders received focused full-read follow-ups. Tracked source review used hunks+enclosing callers/validation, schemas/OpenAPI structural+conformance evidence, large old plans authority/evidence sections and archives hash/banner/stub provenance. All93changedPython test/helper paths were indexed and the complete bare suite ran, but not every test body was manually read. npm lock metadata was checked, not an online dependency vulnerability audit. Current build/browser/design acceptance, remote freshness/CI, clean installs and external/customer gates remain unverified.

## Final preservation evidence
`preservation_audit.py` freshly passed: all314main working-file hashes/status unchanged, main HEAD9edc4a1 and recoveryHEAD838ed80 unchanged, both indexes empty, all82ref heads and44worktree registrations unchanged. Previous candidate100/credential repair/guard, original main-ledger prefix and215other baseline files preserved. New review artifacts and this ledger/checkpoint are intentionally recovery-local and uncommitted; no native goal created/resumed, no product/slice state changed.
