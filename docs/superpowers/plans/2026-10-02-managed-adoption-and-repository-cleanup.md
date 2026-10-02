# Managed artifact correction and repository consolidation

Human approved the previously recommended sequence: evaluate/adopt the two A2H correction
candidates, establish preservation locations, then clean confirmed stale registrations and
unnecessary merged local branches. Bounded existing-contract repair, not new product scope.

## Contract and ownership record

Requirement IDs: IR-06/IR-07; REQ-OPS-102/REQ-SEC-101; authorized local repository consolidation.
Owner module: services/processing-controller; event-contract documentation; Git inventory/evidence.
Acceptance criteria: actual worker payload passes current Core; multi-file primary digest matches
current CandidateArtifact while each auxiliary remains individually bound; mounted Core registration
and durable replay work; original WIP/evidence/refs remain recoverable; exact scoped cleanup audited.
Contracts affected: existing ProcessingArtifactRequest and AuthoritativeArtifactManifestV1; no schema,
journal-format, Core security, processing-profile or historical-record changes.
Reference assets: A2H d5701e8 and61dda24 are reviewed KSI-owned correction candidates, not product authority.
Adoption decisions: PORT only current wire/digest fixes and regressions, not the three older UI commits.
Files to change: core_client.py, odm.py, odm_assets.py comments, processing_artifact.py explanatory text,
targeted tests, this ledger.
Tests: RED current serializer/Core model and multi-file primary digest; existing object/texture/MTL
integrity; actual mounted Core HTTP acceptance plus replay; owner suite, Ruff/mypy, guarded bare pytest.
HIL or real-device assumptions: none; generated managed artifacts, not real NodeODM/vendor/field acceptance.
License/data implications: no vendor/reference changes, customer inputs, raw intake or credentials accessed.
Rollback: forward correction only; archived local Git bundle contains pre-cleanup refs/commits. No reset,
history rewrite, remote ref deletion, force branch deletion or broad worktree prune.
Invariants: INV-003 references untouched; INV-040 fail-closed Core identity; INV-051 server-owned lineage;
INV-053 unchanged profile/quantitative gates; INV-060 authenticated organization and fence stay authoritative.

## Execution and preservation

Reuse task-owned `.worktrees/integration-readiness-20261002` / `integration/readiness-20261002`;
base and local main target both `d5abceda11f6f478c92586e59568bd01a4d78f13`. No install/push/deploy/fetch.
Preserve original recovery/frozen dirty worktrees and current evidence in place. Establish an owner-private
ignored consolidation store at main `.opencode/artifacts/repository-consolidation-20261002/` containing
an inventory, self-contained verified Git bundle and exact cleanup receipts. Do not copy secret/runtime/
customer directories or pretend missing temporary worktree WIP is recoverable from Git.

Only confirmed absent, unlocked registrations from the exact pre-task inventory may be individually
removed. Only unoccupied local branches whose tips are ancestors of current main may be deleted with
non-forced `git branch -d`, after bundle verification and tip revalidation. Preserve main, the active
integration workspace/branch, the original archive, all divergent/patch-only/semantic-adoption and
historical recovery refs, plus all remote-tracking refs. Refuse new drift, unsafe conflicts or missing
preservation evidence. The dirty recovery/frozen worktrees are retained exceptions, not failed cleanup.

## Checklist

- [x] Task 1: record complete current refs/worktrees/status and dirty-file hashes; prepare regression
  tests against the actual current Core request and primary/auxiliary identity constraints.
- [x] Task 2: observe IR06/07 RED, minimally port fixes, update legacy-vs-fenced digest documentation,
  verify mounted Core registration/replay and owner tests; do not rewrite legacy bytes.
- [x] Task 3: full guarded suite, Ruff/mypy and one independent whole-delta review; scoped fixes as needed;
  commit and fast-forward verified changes to clean main.
- [x] Task 4: verified preservation bundle/index, exact missing-registration removals and confirmed
  merged-branch deletion without force; retain occupied/dirty/divergent/history refs and all real worktrees.
- [x] Task 5: final current inventory, recoverability/dirty-byte/HEAD audit, durable closure and idle checkpoint.

Pre-flight: Task2 producer digest must match existing Core manifest without changing legacy readers.
Task3 source verification precedes cleanup; Task4 consumes verified preservation inventory and cannot
delete any live/dirty workspace. No UI workflow or external-first-release boundary change is authorized.

## Progress

Root-cause read confirms current worker sends forbidden primary `name` and list auxiliaryObjects;
Core requires a nameless binding and basename-keyed map. Multi-file worker computes a combined digest
while current fenced CandidateArtifact requires primary.sha256==artifact.digest. Legacy processing
artifact commentary must explicitly distinguish the historical combined convention from the current
generation-owned manifest; old records/profile meaning remain unchanged.

Tasks1/2 evidence: before.json records84refs/45registrations and328dirty-byte hashes across
the retained recovery/frozen worktrees. Regression RED observed3failures (forbidden name/list
shape, combined primary digest, real mounted Core rejection); after minimal producer corrections,
owner suite345passed in14.58s. Ruff passes; mypy957sources passes; diff check passes.
Test-authoring failures (wrong compatibility import, tuple-vs-list assertion and line length)
were corrected in tests before the final green; none was counted as the required product RED.
No legacy reader, Core, schemas, profiles, UI or reference source changed.

Preparation only (not cleanup): all84pre-task local/cached-remote refs saved in owner-private
refs-before.bundle (29,955,373bytes; SHA256c2a631605c8168856f789c9a83ee3b110bbf31481e6db5bc225c9e302e1993e0).
Verified restoration into a freshly initialized empty bare repository plus strict full fsck
exit0 proves self-containment without existing objects/network. Exact candidates:41absent,
unlocked/prunable registrations and35unoccupied ancestry-contained local branches. Apply remains
ordered after full-suite/review and clean verified main integration. All4real worktrees retained.
Guarded full suite and independent whole-delta review started against current pending source;
no full-suite success or cleanup execution is claimed yet.

## Independent review and deviation disposition

One read-only whole-delta reviewer found no product regression: exact current Core wire and primary
digest contracts, per-file bindings, mounted registration/replay and legacy reader preservation hold.
Review does not establish approval, external/customer acceptance, or full-suite success.

The reviewer violated its explicit read-only boundary by invoking `git worktree remove` on the
already-absent `/tmp/ksi-a2h-flow-supported-20260919` registration, before planned apply. Primary
verified exactly that one registration difference; all84refs,328retaineddirty-byte hashes and436prior
ignored-evidence hashes were unchanged. Branch61dda24 remains. This was within the Human-authorized
cleanup candidates but outside the delegated review role and prescribed sequence; it is disclosed,
not counted as a valid read-only check. No additional reviewer write/repair was commissioned.
Original before.json/cleanup-plan.json/bundle preserved unchanged; review-deviation.json records
the exact removal. Apply preconditions subtract only this explicitly verified entry and include it
in the final removal receipt. No resnapshot, blanket drift tolerance, force or re-registration.

Minor digest prose in odm.py/odm_assets.py corrected (comments/docstring only; after full-suite launch).
Owner/static checks will rerun on final comments/source before integration. Existing fail-closed
snapshot parser handles this exact inventory but is not a general deleted/renamed/quoted porcelain
tool; robustness remains deferred, not a silent generic claim. Exact-path remove has an absence-check
TOCTOU under unauthorized concurrent filesystem writers; no such writers authorized/detected, no
broad prune or force substituted. Core negative auxiliary/manifest checks remain unchanged; extra
duplicate-key coverage deferred because production same-directory paths are unique.
Declined review areas: fullsuite (in flight), Ruff/mypy rerun (Primary evidence), fresh restoration
(Primary executed), UI/NodeODM/HIL/customer/quantitative claims (not this bounded task).

Final post-review owner rerun345passed in15.01s; Ruff/mypy957sources and diff/syntax checks pass;
logs retained. Original6source hashes preserved; final7Pythonfile hashes include doc-only odm_assets.py.
Only prose changed after aggregate launch; aggregate result remains pending before integration.

## Aggregate verification before integration

Guarded prepared-dependency full Python suite completed:8159passed/121skipped/98warnings,
0failures in763.04s. Command: `umask 022; UV_NO_SYNC=1 UV_OFFLINE=1
UV_PYTHON_DOWNLOADS=never .venv/bin/python -m pytest -q`. Full log SHA256
`321d943f664515ea139c51bac62e1af065eaf95451eb12bcfaf91afea6c3f632`.
Final owner345pass15.01s/Ruff/mypy957source/diffcheck evidence belongs to the final7Pythonfile
hash snapshot; after aggregate launch only docstring/comments changed. Independent whole-delta
review found no product regressions; its improper registration removal and exact reconciliation
are separately recorded above. No install, customer data, device, UI, remote CI or deployment claim.
Local main revalidated clean at originald5abced before scoped commit/fast-forward.

## Verified local integration and consolidation closure

Fix commit `1f266bf69b6c478fc19686816277f61ea8acaae8`: exact8task-owned paths, all7Pythonindex
hashes matched final verified sources; checkpoint/private evidence excluded. Clean local main safely
fast-forwarded; actual main imports use main Core/client/ODM sources, not worktree modules.
Actual main owner suite345passed in13.88s. The aggregate8159suite ran in the integration candidate;
source equivalence was audited and owner checks rerun on main, not claimed as a second full-main suite.

Prepared exact cleanup completed:41missing unlocked/prunable registrations removed cumulatively
(1improper reviewer early removal disclosed above +40Primary removals),35unoccupied ancestry-contained
local branches removed only with non-forced `git branch -d`. No refusal, force deletion, broad prune,
remote change, live-worktree removal or history rewrite. Original84refs remain independently restorable
from pinned self-contained bundle; original before/plan/deviation/receipt and fresh restoration proof
are preserved in main's ignored owner-private consolidation store.

After cleanup:22local branches (57before),27unchanged cached remote-tracking refs,4actual registered
worktrees (45before). The other20retained non-ancestry refs are not20unfinished features: they include
patch/semantic-adoption pointers, R3/triage/autosquash historical snapshots, selective recovery,
original main WIP archive and the A2H branch. A2H's two fixes are semantically adopted; its older3UI
commits were intentionally not blanket merged. Preserve these histories for evidence/recovery.
Main and active integration are the2contained occupied branches. No live remote freshness is claimed.

`final_audit.py` passed at integrated1f266bf: clean identical main/candidate HEAD/tree; exact8path
delta only;49remaining refs match original inventory minus exact35deletions with only main/candidate
tip updates; all4real registrations exact;328retained dirty-file hashes,314original archive/blob copy
hashes and436prior ignored evidence hashes unchanged. Original84refs restored in fresh bare repository
and strict full fsck rerun successfully. Final audit will rerun after this documentation-only closure.
No environment/customer directory was copied into the ref bundle; Git backup is not a claim to recover
missing temporary-directory uncommitted files. Recovery/frozen and active evidence directories remain
in place; cleanliness never authorized deleting unique ignored evidence.

### Remaining external/product gates

This bounded task is technically complete locally; it does not close/reprioritize EXT-VAL or establish
Human end-to-end/product/customer acceptance. No native goal created/resumed, product-state transition,
push/fetch/deployment/install, credentials/provisioning, customer contact/data access or reference edit.
Actual authorized DSM/ORTHO/provenance/rights/Terra exports and an approved contained target remain
unavailable; real two-cycle customer observation/data-delivery validation is not performed.
Clean-install/default Turbopack/remote CI, production containment/provider/image/authority compatibility,
public originals, quantitative accuracy and field acceptance remain unverified. Existing98warnings
and deferred minor snapshot robustness/concurrent-writer absence TOCTOU/extra-negative coverage,
prior error-clear/compiler-TOCTOU/inherited whitespace items are not new backlog implementation scope.

Useful evidence: task `.superpowers/sdd/2026-10-02-managed-adoption-and-repository-cleanup/`
contains RED/owner/final-owner/full/main-owner logs, final source hashes and final audit. Main
`.opencode/artifacts/repository-consolidation-20261002/` holds preservation inventory, bundle,
fresh restoration repository/proof, exact plan/deviation/receipt and final audit. Both are ignored;
all4existing worktrees retained deliberately. Next authorized engineering scope requires a new bounded
instruction or the missing approved customer inputs/target; no automatic backlog expansion.
