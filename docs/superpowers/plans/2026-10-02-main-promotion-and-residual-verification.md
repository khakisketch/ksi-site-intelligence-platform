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

- [x] Task 1: revalidate main HEAD/index/status and all 314 original hashes; preserve an archival
  WIP tree/commit and ignored byte snapshot before altering main.
- [x] Task 2: reconcile only the reviewed candidate delta, require main staged tree exactly equal
  candidate HEAD tree, fast-forward, and audit archived WIP plus unaffected refs/worktrees.
- [x] Task 3: reproduce private-bus failure in isolated library mode; trace cause without root
  bootstrap or host changes; minimal regression/fix with RED/GREEN evidence when appropriate.
- [x] Task 4: relevant and full prepared-environment verification with UV sync/network/download
  disabled; one independent final review of the bounded delta; integrate verified task commits.
- [ ] Task 5: record remaining clean-install/default-build/customer-input gates honestly, preserve
  evidence, and leave idle checkpoint. No customer/field acceptance or slice transition.

## Progress and evidence

Pre-flight: Task 1 preserves original tree consumed by Task 2; Task 2 requires exact candidate
tree, not a blind merge of dirty main. Task 3 must preserve the security checks verified by Task 4.
The throwaway Git probe established that an exact-target staged tree permits `merge --ff-only`
without reset/checkout/stash. Any drift from the original inventory stops promotion.

Tasks 1–2: preserved all 314 original WIP blobs in archive commit `0a56796c71acf6a3c9607ba2a1cd0ef565406c01`
(`archive/main-wip-before-promotion-20261002`) plus an ignored byte snapshot. Alternate index left
main untouched until preservation passed. Staged original tree, applied only the candidate delta,
required exact candidate tree, then fast-forwarded main to `1b18ace`. Main clean; archive/snapshot
314 hashes pass; unrelated refs and all existing worktree registrations unchanged. Evidence:
`.superpowers/sdd/2026-10-02-main-promotion-and-residual-verification/promotion.json`.

Task 3 diagnosis: original failure reproduced at acceptance of the valid single-link socket,
not at replacement. Real `stat %F` returned Korean `소켓` under ambient `ko_KR.utf8`, English
`socket` under C, with all numeric metadata equal. Bootstrap compares the localized value with
English `socket`; the neighboring ACL helper already fixes its locale. This is a bootstrap
locale bug, not a need to change host security or weaken the test. Extend the real socket test
to C and Korean locales before fixing only the identity command's locale. Unsupported locale
fallback on another host would not establish translated-output coverage there.

Task 4 first aggregate: mistakenly explicit `pytest tests/` omitted configured package/service
test paths (7958 passed, 5 failed, 121 skipped, 98 warnings, 750.45s). All five failures traced
to inherited shell umask0002 creating group-writable fixture directories; private path guards
correctly refused them. Re-run of both affected files under command-local umask077:54passed.
No product/test security guard weakened or host permission changed. Final aggregate must use
bare pytest (configured tests/packages/services) and private fixture umask077.

Independent bounded review: no Critical; original314 archive/snapshot and exact-tree main
promotion verified, unrelated refs/worktrees retained. I1 (locale fallback could silently lose
translated coverage) is addressed with a real-stat translation precondition: unavailable Korean
translation is explicitly NOT_VERIFIED, not falsely passed. C security coverage remains required;
both cases execute on this host. Minor recovery note: failed future promotion could leave staged
state; do not auto-reset, recover manually from archive. Success path here was clean.
Reviewer LANGUAGE concern requires empirical verification before adding another production change.

Task 4 second aggregate (correct configured test paths):8155passed/1failed/121skipped/98warnings,
756.11s. The remaining DPK packaging fixture also fails alone under umask077: the unchanged
vendor script creates DEBIAN with default directory permissions then calls dpkg-deb, which
rejects private0700 package-control directories. Command-local umask022 satisfies both private
path non-group-write guards and vendor packaging permissions:67tests across all affected files
pass5.72s. No vendor/source/guard edits. Final full run uses umask022, not077. These intermediate
red runs remain evidence; neither was claimed green.
LANGUAGE probe: real GNUstat with LC_ALL=C and LANGUAGE=ko/ko_KR/ko:en returns literal socket in
all three cases. No extra production variable needed; do not implement unsupported review advice.

## Final prepared-environment verification

On `1b18ace` plus only the two private-bus source/test changes and this ledger:
`umask 022; UV_NO_SYNC=1 UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never .venv/bin/python -m pytest -q`
→ **8156 passed, 121 skipped, 98 warnings, zero failures in756.62s**. This includes configured
tests/packages/services; both private-bus locale cases ran without a skip. Existing warnings
include jsonschema deprecations, IFC destructor warning and multi-threaded fork deprecations;
not fixed in this bounded task. Full log SHA256:
`19b8ece635eb98e8b49b4311c10ba58754c2725f7769cec36bd33eb2b93d066d`.

Post-review deployment suite52passed3.93s; Ruff clean; mypy956sources clean; Bashsyntax and
task diff check pass. The only product change relative to the previously reviewed baseline is
one command-scoped stat locale assignment; Dashboard/API/schema/worker sources are unchanged.
Prior965Dashboard tests, type/lint/webpack and5browser cases belong to that unchanged baseline;
no second browser or defaultTurbopack/clean-install success claimed here.

## Remaining gates and delivery boundary

- Clean-install and remote CI/default Turbopack are **unverified**; prepared dependencies were reused
  and this follow-up performed no install, fetch, push or deployment.
- Real systemd/rootless Docker/UDS containment, released image/provider/authority inputs and
  production parser compatibility remain separately gated. Only library-mode/private fixtures ran.
- No authorized real customer DSM/ORTHO, rights statement, Terra export evidence, vertical
  reference/checkpoints or two-cycle real reuse inputs were supplied. Do not inspect private intake
  directories, invent acceptance or substitute generated rasters for customer validation.
- The next customer check needs authorized two/three-epoch derivatives and provenance, same
  Site/WorkArea mapping, usage/retention/redistribution rights, and an approved contained execution
  target; quantitative evidence remains separate. No customer contact or policy activation occurred.
- EXT-VAL, product slice and real-device/customer/field acceptance are unchanged. Task-owned
  archival refs, worktrees and ignored preservation/test evidence are retained; no cleanup.

Final integration/closure evidence is appended after the verified local fast-forward and main check.
