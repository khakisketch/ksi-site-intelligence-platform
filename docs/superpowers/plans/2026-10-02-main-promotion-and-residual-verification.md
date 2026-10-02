# Main promotion and residual verification

## Authorized outcome and constraints

Human approved the recommended sequence: preserve and reconcile dirty main, promote the
reviewed local candidate, investigate the remaining private-bus failure, and assess the
remaining reproducibility/customer-input gates. No push, deployment, installation, host
provisioning, reference edits, customer contact, or branch/worktree cleanup. EXT-VAL stays open.
Source baseline: `36330c51a3d9973d6ffa37b4409dad286cabe79f`; main base:
`9edc4a18e873e356f5cfea7d69437f1fb5e11acd`. Execute inline in the existing task-owned
`integration/readiness-20261002` worktree; local integration target is main.

Requirement IDs: bounded main promotion; existing external-runtime private-socket contract.
Owner module: repository integration; tests/contract and deploy/bin if root cause requires it.
Acceptance criteria: original 314 WIP bytes recoverable; no unrelated work changed; exact-tree
fast-forward; reproduce and explain private-bus failure; relevant and aggregate checks reported.
Contracts affected: no product/wire contract change intended; private socket single-link,
owner/mode/type and before/after identity checks must remain fail-closed.
Reference assets: prior readiness ledger and immutable original inventory, reference-only.
Adoption decisions: reuse reviewed baseline; no historical branch sweep or reference import.
Files to change: this ledger/checkpoint; main task-owned candidate delta; narrowly identified
private-bus test or bootstrap only after root-cause evidence.
Tests: preservation/tree audits, private-bus RED/GREEN, deployment contract suite, Ruff/mypy,
guarded full Python suite; existing Dashboard verification only if integrated source differs.
HIL or real-device assumptions: none; no device, host containment, or field acceptance claim.
License/data implications: no customer data inspected; real authorized inputs are a separate gate.
Rollback: preserve original WIP in an explicit task-owned archival Git commit and ignored byte
snapshot; do not reset main or rewrite history. A future rollback uses reviewed forward changes.
Invariants: INV-003 (references untouched); INV-050/051/053/060 preserved by exact baseline
integration, no change to residency, lineage, eligibility, or organization authority.

## Checklist

- [ ] Task 1: revalidate main HEAD/index/status and all 314 original hashes; preserve an archival
  WIP tree/commit and ignored byte snapshot before altering main.
- [ ] Task 2: reconcile only the reviewed candidate delta, require main staged tree exactly equal
  candidate HEAD tree, fast-forward, and audit archived WIP plus unaffected refs/worktrees.
- [ ] Task 3: reproduce private-bus failure in isolated library mode; trace cause without root
  bootstrap or host changes; minimal regression/fix with RED/GREEN evidence when appropriate.
- [ ] Task 4: relevant and full prepared-environment verification with UV sync/network/download
  disabled; one independent final review of the bounded delta; integrate verified task commits.
- [ ] Task 5: record remaining clean-install/default-build/customer-input gates honestly, preserve
  evidence, and leave idle checkpoint. No customer/field acceptance or slice transition.

## Progress and evidence

Pre-flight: Task 1 preserves original tree consumed by Task 2; Task 2 requires exact candidate
tree, not a blind merge of dirty main. Task 3 must preserve the security checks verified by Task 4.
The throwaway Git probe established that an exact-target staged tree permits `merge --ff-only`
without reset/checkout/stash. Any drift from the original inventory stops promotion.
