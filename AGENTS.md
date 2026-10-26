# KSI Site Intelligence Agent Instructions

물리적 현장 관측을 공간데이터와 근거형 분석으로 연결하는 플랫폼이다. 고객은 원본·재구성
실행을 소유하고 KSI는 제출된 파생 산출물의 등록·검사·허용된 활용과 근거를 소유한다.
비행·자율 취득·전술 제어는 현행 제품 책임 밖이다(ADR-KSI-036/038/039).

## Task-relevant knowledge map

| Question | Existing entry point | Responsibility |
|---|---|---|
| Current product identity and scope | `docs/00_READ_FIRST.md` | Accepted direction and supersession routes; detailed authorities below |
| User work and screen responsibilities | `docs/design/CONSOLE_CURRENT_SPEC.md` + `docs/ledger/DESIGN.md` | Current subordinate Console direction and source-bound implementation evidence |
| System and data ownership | `REPOSITORY_STRUCTURE.md` + relevant owner README/contracts | Core durable authority, worker measurement, Dashboard intent, bounded API/MCP adapters |
| Current work, evidence and blockers | `docs/ledger/CURRENT.md` | Existing operational index and named work files; no duplicate task ledger |
| Product slice and remaining product scope | `docs/superpowers/product-state.md` | Current slice unchanged; old milestone/progress history linked separately |

This is a topic map, not a required reading sequence or new authority. Read the relevant sections
and reconcile implementation claims with working changes and source-bound evidence. Execution owners
return durable fact/evidence changes; Build integrates shared summaries. No ledger churn for edits
that change no product fact, and no checkpoint creates another next-goal authority.

## Product authority precedence

For conflicts, use this precedence, not a required reading sequence:

1. `docs/00_READ_FIRST.md`
2. `docs/product/PRODUCT_CONSTITUTION.md`
3. `docs/product/FINAL_DECISION_LEDGER_v1.0.md`
4. `docs/product/MASTER_PRD_v3.0.md` and relevant section
5. Relevant contract/schema
6. Relevant accepted ADR
7. Acceptance criteria
8. Reference adoption matrix
9. Reference code

Domain invariants are owned by `docs/product/DOMAIN_INVARIANTS.md`; identify and enforce the affected
ones. Supporting designs keep their declared subordination; a prototype or ledger creates no product
authority. The accepted supersessions and detailed boundary explanations live in `docs/00_READ_FIRST.md`.

## Product boundaries and work selection

Use the task-relevant accepted decisions linked by `docs/00_READ_FIRST.md`: ADR-KSI-036 for
customer-owned reconstruction/result ingress, ADR-KSI-037 and its selected first-request contract
for earthwork analysis, ADR-KSI-038 for platform/data reuse, ADR-KSI-039 for acquisition separation.
Registration, RTK FIX or software checks establish neither quantitative/settlement accuracy nor
vendor/field support. Accepted direction alone creates no endpoint, runtime permission or product acceptance.

`docs/ledger/CURRENT.md` and its named work files own active operational routing; the ledger does
not override product authority. `.opencode/working-state.md` is only a short pointer. Resume the
current Human-assigned bounded task after Git/evidence revalidation without closing or reprioritizing
the product slice. Select from `docs/superpowers/product-state.md` only when no active bounded task
exists and current user authorization permits it. `docs/goals/PHASE_REGISTRY.yaml` is a capability
index, not another current-task or priority source. Cached memory and session summaries are context,
not evidence of current authority/readiness.

## Source ownership and historical material

`REPOSITORY_STRUCTURE.md` owns current source/runtime responsibility; `docs/DOCUMENT_STATUS.md`
distinguishes active authority from history. Use the selected owner's README, contracts, entrypoint,
dependency manifest and tests as relevant. A directory name or diagram is not runtime proof.
Independently operated lifecycles belong in `services/`; import-only reusable code belongs in `packages/`.
Preserve `docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json`; do not recreate the retired change-detection,
BIM or defect service paths or move similarly named modules without approved scope and dependency,
build/CI/replay/deployment/rollback evidence.

`archive/acquisition-2026/`, `.ksi/`, retired harness roles/recipes and the old terrain-aware planning
route are historical, not runtime imports, build input, current support or task selection. Their
current routing and exceptions remain in `docs/DOCUMENT_STATUS.md`; preserve retained signed/digest/
device/activation boundaries. Managed NodeODM/ProcessingJob evidence stays managed/test, not customer
production evidence. Global Native execution/verification responsibilities apply; do not restore old seats or workflows.

## Reference repositories

- `references/repos/ksi-platform`
- `references/repos/ksi-terra`
- `references/repos/ksi-scout`

They are read-only reference implementations, not product authority.

Never import runtime code directly from `references/`.
Never modify a reference submodule unless the task explicitly says `UPDATE_REFERENCE_PIN`.

## Change context and verification

Keep decisions proportional to the task: affected requirements/invariants, owner, contracts,
acceptance and verification; include reference adoption/license/data rights, device assumptions and
rollback when relevant. No fixed report form or mandatory planning stop. Verify with existing owner,
contract/replay tests and actual outcome evidence; do not add a process just to complete a template.

## Control boundaries (retained historical acquisition contracts)

These constraints retain their original safety meaning; they do not mount Mission/device/Edge
routes or assign current product work to the archive. Current platform ownership is in `REPOSITORY_STRUCTURE.md`.

- Manifold owns tactical perception, tracking, local world model, risk, active perception and local mission decisions.
- DJI Flight Controller owns stabilization, low-level flight, verified reactive avoidance and RTH.
- Core owns signed Mission Contract, policy, map/model versions and workflow.
- LLM must not emit executable flight coordinates or bypass safety policy.
- Server loss must not invalidate a locally valid Mission Contract.

## Quality

Do not claim completion from mocks, imports or unit tests alone.
Use contract tests, replay tests and real-device/HIL gates where applicable.
Unknown facts and unverified DJI behavior must remain explicit.
