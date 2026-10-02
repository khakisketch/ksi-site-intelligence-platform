# PG-20260920 — Product-guidance alignment

Status: active documentation-alignment record.  This record does not change the current
`EXT-VAL` slice, release state, or runtime behavior.

## Purpose

Make the approved external-reconstruction first-release direction discoverable to a
fresh Codex, OpenCode, or Claude session without changing managed processing history:
customer-controlled DJI Terra on a customer field PC is the initial MVP reconstruction
reference workflow; KSI receives derived results and turns eligible evidence into
comparison, relative-quantity, review, and re-observation workflow.  KSI is not a
proprietary photogrammetry engine or a customer production reconstruction service.

## Authorized 2026-09-20 direction extension

Human approval adds an API-first earthwork-evidence product direction. KSI records observations and
analysis results with source, time, coordinates, and calculation conditions so external systems can
verify and reuse them. The first complete target MVP is weekly per-WorkArea two-epoch observed-terrain
volume-change review; current-versus-design cut/fill needs actual customer design data and is a
conditional successor. This extension is a documentation decision only: no native execution goal is
active, and `docs/superpowers/product-state.md` remains bytewise unchanged at `EXT-VAL` until a
separate authorized slice close.

## Exact baseline and authority

- Baseline: branch `docs/product-guidance-20260920`, commit
  `9edc4a18e873e356f5cfea7d69437f1fb5e11acd`, clean at task start.
- Product authority: `docs/00_READ_FIRST.md` → Product Constitution → Final Decision
  Ledger → relevant Master PRD; ADR-KSI-036 is the accepted first-release responsibility
  boundary.
- State/ledger routing: `docs/superpowers/product-state.md` remains at `EXT-VAL` and names the
  product-slice ledger. This plan is the sole active checkout-task ledger for this alignment;
  it does not close or reprioritize the product slice. `.ksi/` and historical handoffs are
  evidence, not current task state.
- Client boundary: this repository guidance addresses fresh session routing.  It does not rewrite
  global Codex/OpenCode/Claude configuration or auto-memory; existing sessions and worktrees must
  re-read the active authority and revalidate Git.

## Required implementation-plan record

| Field | Decision |
|---|---|
| Requirement IDs | ADR-KSI-036 D1–D6 and ADR-KSI-037; INV-017/018/020/024/040/050/051/053/054/055/060/061 are preserved, not changed. |
| Owner module | Documentation authority and repository-entry guidance only. |
| Acceptance criteria | A fresh session can identify KSI's API-first role, weekly two-epoch MVP, its one selected/verified authenticated external agent/MCP workflow, evidence-rich Core-recorded result/blocker boundary, initial M4D/Terra input flow, managed-history boundary, authority/status routing, and limits without treating registration or RTK FIX as quantitative acceptance. |
| Contracts affected | None. No schema, API, runtime, ProcessingJob, or invariant implementation changes. |
| Reference assets | ADR-KSI-036, ADR-KSI-003, ADR-KSI-030 history, and active product documents. Reference repositories remain read-only and are not used as authority. |
| Adoption decisions | RETAIN ADR-KSI-036 input boundary; ADD ADR-KSI-037 and its target first-request design; REPLACE contradictory active MVP wording with scoped acquisition-roadmap wording; RETAIN managed NodeODM/source-authority rules and all historical evidence. |
| Files to change | Root guidance/readme, active product/architecture/routing documents, ADR-KSI-037, first-request design, this ledger, and the shared worktree checkpoint. |
| Tests | Markdown diff/path/link checks, focused direction scenarios, and existing repository normalization validation when available. |
| HIL or real-device assumptions | M4D is the company's initial field-validation equipment. No device, RTK, Terra export, accuracy, HIL, or field acceptance is asserted. |
| License/data implications | No Terra license, export compatibility, customer raw-data transfer, or vendor integration is approved or verified. Customer originals remain customer-side in the external first-release route. |
| Rollback | Revert only this documentation delta; it does not delete or mutate managed results, jobs, code, deployment, or customer data. |

## Tasks, dependencies, and acceptance

| ID | Owner | Depends on | Deliverable and focused acceptance |
|---|---|---|---|
| PG-01 | Documentation writer | authority read | Root `AGENTS.md` routes to authority, ADR-KSI-036, status, shared checkpoint, and ledger; root `CLAUDE.md` imports it and keeps Claude-specific behavior. |
| PG-02 | Documentation writer | PG-01 | Product entry documents state the M4D → customer-PC Terra → submitted-derived-results → KSI analysis/re-observation flow and separate it from the managed/raw path. |
| PG-03 | Documentation writer | PG-02 | ADR-KSI-036 D6 and active PRD/Constitution/overview scope source/derived authority, input uses, RTK limits, settlement limits, and legacy managed rules. |
| PG-04 | Independent reviewer | PG-01–03 | Review changed source against the baseline and scenario matrix; no completion claim without it. |
| PG-05 | Documentation writer | Human-approved refined direction | Add ADR-KSI-037 and a subordinate first-request design that define the API-first earthwork evidence product, input/result semantics, and non-goals without asserting an implemented wire contract. |
| PG-06 | Documentation writer | PG-05 | Correct active authority/routing wording so API-first MVP does not silently retain autonomous execution, proprietary reconstruction, mandatory BIM, or managed raw processing as a first-release prerequisite. |
| PG-07 | Independent reviewer / Lead | PG-05–06 | Review the frozen documentation delta, then apply only the reviewed source paths; runtime, schema, deployment, and product-state remain outside this task. |
| PG-08 | Documentation writer | Human-authorized readpath audit | Align entry/read/resume routing, phase-index/status wording, and minimal legacy notices without changing product direction, runtime, global client configuration, or product-state values. |
| PG-09 | Independent reviewer / Lead | PG-08 | Review the new routing freeze: legacy bodies and YAML values remain preserved; links/diff/normalization pass before any application. |
| PG-10 | Documentation writer | PG-09 | Archive the six conventional legacy `.ai` state bodies behind non-authoritative compatibility stubs, clarify product-direction versus current-slice routing, narrow overview scope, and record an evidence-only runtime legacy boundary. |
| PG-11 | Independent reviewer / Lead | PG-10 | Verify exact archive recovery, routing/link integrity, unchanged product-state/runtime/contracts/invariants, and apply only the reviewed documentation delta. |
| PG-12 | Documentation writer | Human-approved implementation conditions | Amend ADR-KSI-037 and its selected first-request design with the fixed KSI GIS profile, provisional/remediation/blocked policy, immutable result/evaluation semantics, and exact owner/contract/acceptance boundary. Do not implement it, change `EXT-VAL`, or alter V1. |
| PG-13 | Independent reviewer / Lead | PG-12 | Freeze and independently review the narrow authority/design/ledger delta before any local application claim. |

## PG-12 implementation-conditions scope

| Field | Decision |
|---|---|
| Requirement IDs | ADR-KSI-037 D1–D7; REQ-INT-101..104, REQ-SEC-101, REQ-OPS-102; preserve INV-017/018/020/024/040/050/051/053/054/055/060/061. |
| Owner modules | `services/core/src/ksi_core/domains/external/quantity/{external_use_evaluator.py,external_relative_volumes.py}` owns authorization/admission/evidence applicability and durable current/historical projections; `services/processing-controller/src/ksi_processing_controller/{external_measurement_protocol.py,external_measurement_algorithms.py}` owns the Core-bound launch and fixed calculation; `packages/event-contracts/src/ksi_event_contracts/external_relative_volume.py` owns wire models; `packages/change-detection/src/ksi_change_detection/{dsm_diff.py,external_volume.py}` owns import-only math; `apps/dashboard/` only presents/requests; future MCP is a thin authenticated client of the same Analysis facade/API. |
| Contracts affected | Additive versioned analysis request/result/evaluation and worker-launch contracts are required. Existing `ExternalRelativeVolume*V1`, evidence records, schemas, routes, replay, and worker transport stay strict and replayable; the facade must not reinterpret them as provisional. |
| Fixed target profile | Design-only `KSI-GIS-RELATIVE-VOLUME-V2`: exact baseline native north-up affine grid/resolution, current elevation bilinear and valid-mask nearest resampling, cell-centre WorkArea mask, declared NoData/mask unavailable, unmasked non-finite input failure, 100% common-valid coverage, 0.0 m deadband, absolute-affine-determinant area integration, no automatic registration/bias/shift/scale/rotation. Core freezes executable/build, runtime image version/OCI digest, dependency-lock, algorithm/config/profile, transforms/grid/masks in each run. `d=current-baseline`; positive `d` sums to fill, negative magnitude to cut, and net is fill-cut; selected/common/unavailable/threshold-excluded raster counts and areas are distinct from polygon geometry. |
| Policy outcomes | Valid computability plus absent independent checkpoint evaluation → provisional number with null uncertainty and limitation. Failed or unresolved conflicting evaluation for either DSM → remediation, no normal current number. Essential coordinate/vertical/unit/readiness/lineage or common-area failure → blocked, no number. V1 strict checkpoint policy remains unchanged. |
| Version semantics | Numeric calculation and evaluation are separate immutable records. A new evaluation may update current suitability but never rewrite a calculation. Recalculate only for input bytes, WorkArea/version, transforms, worker executable/build, runtime image version/OCI digest, dependency-lock digest, or algorithm/config/profile (including mathematical rules) change. Core checks applicable terminal evidence at admission and publication/current retrieval; historical tuple retrieval remains explicit and labelled. |
| Focused acceptance | Web registration → selected Codex MCP create/poll/retrieve → API and limited evidence map show identical IDs/restrictions → next epoch reuses configuration with fresh pair admission. Cover no checkpoint, missing essential condition, failed checkpoint, conflicting evidence, queued/publication race, historical immutability, and replay. Add focused coverage beside `tests/contract/test_external_relative_volume_s3_capabilities.py`, `tests/contract/test_external_measurement_protocol.py`, `tests/contract/test_external_volume_app_mount.py`, and `tests/replay/test_external_quantitative_authority_replay.py`; retain `packages/change-detection/tests/test_external_volume.py` for arithmetic. Its 28 existing passing tests on 2026-09-20 do not prove V2 policy, Core/worker integration, MCP, map, replay, deployment, or field acceptance. |
| HIL/license/data/rollback | No device/HIL/Terra-export/license/customer-data/accuracy acceptance is created. No production policy is activated. This scope is only reusable-path good/bad regression evidence; it neither closes `EXT-VAL` nor alters the 2026-09-18 owner decision that defers the EXT-VAL-06 staging/release-host evidence gate. Rollback is a later approved authority change; no historical input/result/evaluation is deleted or rewritten. |

## PG-10/11 legacy separation scope

- Requirement IDs: ADR-KSI-037 D1-D7; documentation routing only.
- Owner: repository documentation. No runtime owner changes.
- Acceptance: the complete six legacy `.ai` bodies remain recoverable under a dated archive;
  conventional paths cannot act as current goals; ADR-KSI-037 remains strategic direction while
  product-state remains the unchanged current slice; runtime candidates are classified without a
  deletion, disabled-state, or implementation claim.
- Contracts/invariants: none changed. Preserve INV-017/018/020/024/040/050/051/053/054/055/060/061,
  persisted ProcessingJob/Copilot records, replay compatibility, and all runtime contracts.
- Files: `.ai` compatibility stubs/README, dated archive mapping and bodies, routing/overview docs,
  evidence-only legacy-boundary audit, and this ledger.
- Validation: exact legacy-body preservation, active local links, `git diff --check`, repository
  normalization, product-state hash, and absence of runtime/schema/invariant changes.
- HIL/device assumptions: none; no field or client acceptance claim.
- License/data implications: archive preserves provenance; NodeODM/AGPL and customer-data decisions
  remain unchanged.
- Rollback: restore the archived bodies to their conventional paths and remove the compatibility
  stubs/mapping; no runtime or persisted data migration is involved.

## PG-08 routing audit scope

- Shared entry is root `AGENTS.md`; root `CLAUDE.md` imports it with Claude-specific behavior.
  Static configuration evidence observed: Codex/Claude SessionStart and OpenCode reference the
  same KSI-Opencode-Harness continuity hook/plugin. It reads bounded checkpoint/product-state
  Goal/Slice/Acceptance/Ledger context as untrusted and requires Git revalidation; it does not
  automatically load full product authority. No root/global override or project OpenCode config
  was found; the global OpenCode `mobbin-design` rule concerns new UI only. This documents routing,
  not client loading or live acceptance; no global config/memory was changed.
  Read-only hook evidence for root and `apps/dashboard` is recorded in main-worktree
  `.opencode/artifacts/product-guidance-20260920/continuity-hook-routing-check.json`: both resolve
  the root and current PG-08/09/EXT-VAL context, but output clipping means original authority files
  still require explicit read. This verifies helper output only, not live client loading or obedience.
  After main-checkpoint compaction, the bounded root/dashboard helper output had no clipping and
  retained the task ledger, slice ledger, and all `EXT-VAL-01`–`08` context; see
  `.opencode/artifacts/product-guidance-20260920/continuity-hook-routing-check-compact.json`.
  This remains helper-only evidence, not live-client loading or obedience.
- Session resume is project guidance → checkpoint (when present) → product-state → the applicable
  task or slice ledger → Git revalidation. Checkpoint identifies an active checkout task and task
  ledger; a Human-assigned bounded task persists without closing/reprioritizing product slice.
  Product-state identifies product slice and slice ledger; choose from it only if no active bounded
  checkout task exists. Product authority is an applicable-task precedence order:
  `00_READ_FIRST → Constitution → Final Decision Ledger → relevant PRD → contract/schema →
  relevant accepted ADR → acceptance`; supporting design is read only when explicitly selected by
  an ADR/higher authority and retains declared subordination.
- `PHASE_REGISTRY.yaml` is a capability-track/status index. It does not select current task or
  next priority. `.ai/` and `.ksi/` are historical context/evidence; their old next actions do
  not supply external authorization. `plans/` and `specs/` are active only when explicitly named
  by current authority, the active checkout task ledger, or product-state's named slice ledger;
  active design is target design, never runtime proof.
- This audit changes only routing prose/header comments. Product-state values, PHASE_REGISTRY YAML
  body values, runtime/contracts, global settings/memory, and archived bodies are out of scope.
  Other worktrees/sessions, including the dirty A2H worktree, are not synchronized or cleaned by
  this task and must explicitly reread/adopt reviewed routing while preserving their WIP.
  Claude auto-memory still indexes historical NodeODM local-stack material; the root cached-memory
  non-authority guard remains the routing control, and this task does not purge client caches.

## PG-05/06 requirement and invariant scope

| Concern | Documentation decision |
|---|---|
| Product target | KSI is an API-first site-observation evidence service. It returns source/time/coordinate/calculation-condition-bound results so external systems can verify and reuse them. MCP is an intended access surface for validated tools, not a current implementation claim. |
| First complete MVP | Weekly, per-WorkArea, two-epoch observed-terrain volume-change review plus one selected/verified authenticated external agent/MCP client and reusable example workflow returning the same result/blocker record as UI/API. Other clients are not implied. Current-vs-design remaining cut/fill is a conditional successor that needs real customer design data. |
| Evidence semantics | No geometric change, net volume, or design delta proves approved work, progress, settlement, quality acceptance, survey acceptance, or field acceptance. Intake, compatibility, accuracy evidence, calculation, review, privileged baseline change, and result issuance remain distinct states. |
| First-request requirements | Site/area/epoch/version scope; current external V1's two supported DSM/terrain inputs plus WorkArea (ortho optional evidence, never volume source); artifact/region/profile/CRS/vertical/transform versions; common valid/excluded bounds; producer provenance; idempotency, tenant permission, stable result IDs, typed blockers, polling, result retrieval, reproducible result/evidence binding, and tenant-scoped evidence references. Results expose inspection/admission/quality statuses and limitations with exact derived inputs, checkpoint/inspection validation, masks/exclusions, and supporting evidence; raw photos are not required. UI/API/selected agent-MCP workflow must resolve the same record and restrictions. |
| Result classes | The first-request record is Core-recorded/admitted execution, with actual external-engine producer/profile provenance when used. Customer independently computed-result import is a separate future provenance-bound route; an agent proposal is not a calculation record. Result review is not an enterprise-approval workflow; only privileged official-baseline changes and result issuance have human gates, while permissioned reuse follows an already approved WorkArea/configuration/compatibility rule/template and gets fresh pair-bound admission/evidence. |
| Invariants | Preserve INV-017/018/020/024/040/050/051/053/054/055/060/061 and all enforcement. No invariant text, runtime behavior, schema, policy, or authority activation changes. |
| Explicit exclusions | Proprietary photogrammetry/SLAM/3D reconstruction; BIM editor/general viewer/general chatbot; all-project automatic progress; automatic robot/flight execution; webhook delivery in MVP; any vendor/client topology or field-acceptance promise. |
| Validation | Documentation link/path/diff checks, repository normalization, focused scenario matrix, and independent review. No customer sample, Terra API/export, MCP server, vendor license, deployment, HIL, or field evidence is created. |

## Scenario matrix for PG-04

| Question | Required answer source |
|---|---|
| What is KSI? | Constitution/README/PRD: evidence-and-workflow platform, not reconstruction engine. |
| Who reconstructs and where do originals stay? | ADR-KSI-036 D6: customer-controlled field PC/Terra; customer side. |
| Which artifacts support which uses? | ADR-KSI-036 D4/D6 and active product docs: ortho registration/viewing, DSM-dependent current external-V1 height/relative quantity, point cloud/DTM function-specific, mesh visualization. |
| Does RTK FIX prove map accuracy or settlement? | No; checkpoint/compatibility/field acceptance remains separate. |
| What happens to NodeODM/ProcessingJob/point-cloud SSOT? | Managed/test/demo history and safeguards remain intact; no runtime removal is implied. |
| Which documents hold current state? | `product-state.md` and this ledger; historical `.ksi/` is not current state. |
| What completes the new MVP target? | A numeric `t0→t1` result and `t1→t2` result in one WorkArea under the same reusable rules but fresh pair-bound `mappingRecordDigest`/authority/input admission, plus a negative typed-blocker case. Previously validated evidence may be referenced only for the identical artifact/digest while policy conditions remain valid, never reassigned to new `t2` bytes; no accuracy/field acceptance without separately agreed reference evidence. |
| What must the selected agent/MCP workflow return? | The same tenant-scoped Core-recorded result/blocker record, inspection/admission/quality limitations, exact input/validation/mask/evidence references, and restrictions as UI/API. |

## Review record

- Review round 1 inspected the immutable v1 freeze and returned `CHANGES_REQUIRED` for two
  material documentation ambiguities (customer desktop Terra versus KSI provider adapters and
  the stale 2026-09-04 overview snapshot presented as current state) plus one minor completeness
  finding (INV-024 absent from ADR-KSI-036's preservation list). The Lead separately requested
  the DSM wording clarification so it could not be read as a permanent point-cloud ban.
- This correction round scopes provider adapters to separately authorized KSI-managed execution,
  labels the overview and autonomy table as a 2026-09-04 snapshot, adds INV-024 without changing
  its rule, and limits DSM wording to the current external V1 measurement route. It adds no
  runtime, policy, vendor, license, client-memory, or product-state change. The v1 freeze remains
  untouched; independent re-review must use a new Lead freeze.
- Focused recheck after the corrections: `git diff --check`, repository normalization R0-R3, local
  changed-path checks, and the documentation scenario matrix. Re-review remains required.
- Review round 2 returned `CHANGES_REQUIRED`: complete MVP must include one selected/verified
  authenticated external agent/MCP workflow; result evidence must be retrievable with explicit
  statuses/limitations; first-request execution must remain Core-recorded; existing design-progress
  contracts must be preserved as a conditional successor; and PRD §25 must be a roadmap rather than
  current work order. This correction changes documentation only and requires a new exact freeze.
- Post-review terminology/binding correction: `Core-recorded` names calculation records, while
  `issuance` remains the human-gated publication action. Weekly reuse is limited to approved
  WorkArea/configuration/compatibility/template rules; every new epoch pair requires fresh
  pair-bound admission, authority, and result records. Previously validated per-artifact evidence
  may be referenced only for the identical bytes while its policy conditions remain valid.
- Routing review returned `CHANGES_REQUIRED`: distinguish active checkout task/task ledger from
  product slice/slice ledger; keep accepted ADRs above only supporting designs; add root pointers
  outside Dashboard's managed Next block and the prototype's local rules; and label unavailable
  historical `.superpowers/sdd` paths instead of presenting them as current acceptance evidence.
  The correction preserves product-state, runtime/contracts, historical reported results, and
  Dashboard's managed block bytes.
- Routing re-review identified five remaining unqualified product-state work-selection phrases.
  They now limit product-state to product slice/Backlog/named slice ledger and product-level
  next-work selection only when no active bounded checkout task exists; an active task resumes via
  the Git-revalidated checkpoint and named task ledger. YAML values, product-state, runtime, and
  historical bodies remain unchanged.

## Evidence and limits

Planned evidence is documentation consistency plus repository normalization only.  It cannot
prove DJI client availability, Terra licensing/export compatibility, a field workflow, RTK
accuracy, quantitative eligibility, customer acceptance, deployment, or release readiness.
Cached client memory and pre-existing session summaries are not verified by this work and do not
become product authority, current readiness, or authorization.

## Prior ADR-KSI-036 alignment verification and application — 2026-09-20

This evidence applies only to the earlier 16-path ADR-KSI-036 guidance freeze. The subsequent
ADR-KSI-037 direction extension above changes the source delta and requires a new freeze, focused
validation, and independent review before any application claim.

- PG-01–PG-03: documentation changes applied; PG-04: independent re-review PASS, no remaining findings.
- Reviewed baseline/HEAD: `9edc4a18e873e356f5cfea7d69437f1fb5e11acd`.
  Reviewed tracked diff SHA-256: `781ddbcc273906b2bcacb994c023257d1c5e470fa0faa736e39e0b10330d6794`.
  Exact 16-path review freeze: `.opencode/artifacts/product-guidance-20260920/review-freeze-v2.json`
  in the main worktree (local evidence, not a clean-checkout prerequisite).
- Independent review verified all frozen hashes and unchanged before/after Git status; diff check,
  repository normalization, 58 local Markdown targets, and focused product/routing scenarios passed.
- Lead applied the exact reviewed 16 Markdown files to the main worktree after matching every
  destination to its captured baseline. No Git merge, index write, commit, push, or runtime mutation.
- Post-application `git diff --check` and `.venv/bin/python tools/validate_repository_normalization.py`
  passed. Protected Dashboard tsconfig and the existing A2H plan were preserved byte-for-byte.
  Product-state and domain invariants remain unchanged; EXT-VAL acceptance is not closed.
- This final factual evidence entry follows the reviewed source freeze. No product-direction or
  policy text changed after review. Client live-session reloading and user acceptance are not proved;
  existing sessions and other worktrees must re-read/adopt the updated authority explicitly.


## PG-07 final review and local application — 2026-09-20

- PG-05/06 documentation target is recorded; PG-07 independent final review PASS with no
  remaining findings after two bounded correction rounds. This closes the documentation work,
  not the current product slice or customer acceptance.
- Exact source evidence: `.opencode/artifacts/product-guidance-20260920/pivot-review-freeze-v3.json`
  and `pivot-review-result.md` in the main worktree. The freeze binds 18 document hashes to HEAD
  `9edc4a18e873e356f5cfea7d69437f1fb5e11acd`; the incremental patch hash is
  `7ca19384ce1a64bb1c9c4b27343d1fa1a5ecec819d102505afc13582f8f9f342`.
- Independent review verified hashes, unchanged Git state, diff check, repository normalization,
  63 local links, calculation/publication terminology, and exact-pair evidence bindings.
- Lead applied the 13-path incremental documentation delta to main only after every pre-pivot
  file matched its baseline. All 18 reviewed document bodies then matched the freeze; 2,065
  other baseline files, including Dashboard tsconfig, the A2H plan, invariants, and product-state,
  remained byte-for-byte unchanged. The original documentation bodies are retained in local
  `pre-pivot/` evidence. No index write, commit, merge, push, deployment, or runtime change.
- Post-application `git diff --check` and `.venv/bin/python tools/validate_repository_normalization.py`
  PASS. This factual evidence appendix follows the review freeze; no product requirement changed
  after review. Main and isolated source retain identical document bodies including this appendix.
- Approved strategic target: weekly WorkArea observed-volume review with one verified external
  agent/MCP example workflow, reusable configuration, fresh per-pair authority, and shared evidence.
  Product-state remains EXT-VAL under the slice-close policy; promote the strategic goal and
  next-work inventory at its authorized close. Client/engine selection, real customer samples,
  numeric acceptance, MCP interoperability, deployment and field acceptance remain unproved.


## PG-09 final routing review and local application — 2026-09-20

- PG-08/09 documentation routing work is locally complete. Independent final review PASS with no
  remaining findings; this does not close EXT-VAL or establish customer/client acceptance.
- Exact source: `.opencode/artifacts/product-guidance-20260920/routing-review-freeze-v3.json`;
  verdict: `routing-review-result-v3.md` in the same local evidence directory. The freeze binds
  35 document hashes to HEAD `9edc4a18e873e356f5cfea7d69437f1fb5e11acd`.
- Lead applied only the 24-path incremental routing delta after rechecking all 2,078 main baseline
  hashes. All 35 reviewed bodies matched after application; the other 2,054 baseline files,
  including Dashboard tsconfig, A2H plan, product-state, invariants and runtime, were preserved.
- Independent checks: exact source hashes/status/diff/patch, 76 local links, seven historical
  bodies, nested local rules, YAML semantic values, and focused routing clauses passed.
  Post-application diff check and repository normalization passed in main.
- Historical `.ai`/`.ksi` records remain preserved; obsolete current-state references were retired.
  Missing historical machine-local audit reports are explicitly unavailable, not recovered evidence.
- This factual appendix follows the reviewed freeze; no product/policy requirement changes after
  review. Main and isolated source remain identical. No commit, index write, push, merge, deployment,
  global configuration/memory edit, or other-worktree synchronization was performed.
- Shared helper checks are local output evidence only. Live Codex/OpenCode/Claude sessions and other
  worktrees still need to reread/adopt the current authority; three-client behavior is not verified.

## PG-11 legacy separation review and local application — 2026-09-20

- Independent review PASS with no blocking findings. Exact evidence is
  `.opencode/artifacts/product-guidance-20260920/legacy-separation-freeze-v1.json` and
  `legacy-separation-review-result-v1.md` in the main worktree.
- The six conventional `.ai` state bodies were preserved byte-for-byte under
  `docs/archive/agent-state-legacy-2026/ai/`; their original paths now contain only
  non-authoritative compatibility routing. Existing `.ai/audits/**` evidence remains in place.
- Lead applied only the 16 reviewed documentation paths. Product-state, runtime, contracts,
  invariants, configuration, Git index, and unrelated WIP were unchanged.
- Independent checks covered 16 frozen hashes, 50 local links, exact archive recovery,
  diff check, repository normalization, and product-state preservation. Post-application
  diff check and normalization also passed.
- Runtime retirement remains separate work: managed NodeODM, BIM/design progress, Copilot,
  Edge/device paths, persisted records, and replay surfaces were classified but not disabled or
  deleted. No implementation, deployment, HIL, client loading, or customer acceptance is claimed.

## PG-13 implementation-conditions review and local application — 2026-09-20

- PG-12/13 documentation refinement is locally complete. Independent review PASS after two
  bounded correction rounds; no remaining findings. Exact evidence under
  `.opencode/artifacts/product-guidance-20260920/`: `implementation-conditions-review-freeze-v3.json`,
  `implementation-conditions-review-result-v3.md`, and `implementation-conditions-application.json`.
- Five reviewed document bodies were applied after all 2,087 main baseline hashes matched;
  the other 2,082 baseline files, including runtime, schemas, invariants, product-state and
  foreign WIP, remained unchanged. Post-application diff check and repository normalization passed.
- Existing arithmetic test: `.venv/bin/python -m pytest packages/change-detection/tests/test_external_volume.py -q`
  passed 28 tests. This does not verify the new policy, full worker/Core path, UI/MCP or field accuracy.
- The ignored comparison HTML received wording corrections for MCP create/poll/retrieve and
  no failed-evidence bypass; static text checks passed, not browser or remote-device acceptance.
- This factual appendix follows the frozen review. No runtime/schema policy was activated,
  no EXT-VAL slice was closed, and no commit, push, deployment or device action was performed.
