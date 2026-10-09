# KSI Site Intelligence Agent Instructions

## Product authority precedence

For product-decision conflicts, read in this order. This is a product-authority precedence list;
it does not replace the session checkpoint/product-state/ledger/Git revalidation route below.

Read in this order:

1. `docs/00_READ_FIRST.md`
2. `docs/product/PRODUCT_CONSTITUTION.md`
3. `docs/product/FINAL_DECISION_LEDGER_v1.0.md`
4. `docs/product/MASTER_PRD_v3.0.md` and relevant section
5. Relevant contract/schema
6. Relevant accepted ADR
7. Acceptance criteria
8. Reference adoption matrix
9. Reference code

Domain invariants (INV-xxx) are canonical in `docs/product/DOMAIN_INVARIANTS.md`.
Every implementation task must state which invariants it touches and how they are enforced.
Read a supporting design document only when an accepted ADR or higher authority explicitly selects it;
the design keeps its declared subordination and is not a same-rank authority source.

## First-release product-direction routing

For work that touches capture, reconstruction, spatial artifacts, or analysis, read
`docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md` after the
authority sequence. It is the accepted first-release responsibility boundary: the customer
controls reconstruction on its equipment and KSI registers, verifies, and analyzes exported
derived artifacts. It does not authorize a proprietary KSI photogrammetry engine, a customer
production reconstruction service, a vendor integration, or a claim that registration, RTK FIX,
or a software check establishes quantitative or settlement accuracy.

The shared worktree checkpoint `.opencode/working-state.md`, when present, identifies the active
checkout task and its task ledger; revalidate Git before relying on it. A current Human-assigned
bounded task persists without closing or reprioritizing the product slice. Separately,
`docs/superpowers/product-state.md` identifies the current product slice and its slice ledger.
Only when no active bounded checkout task exists may work selection begin from product-state.
`docs/goals/PHASE_REGISTRY.yaml` is a capability-track index, not a competing current-task or
next-priority source.
Historical `.ksi/` records and managed NodeODM/ProcessingJob evidence remain historical or
managed/test scope unless the applicable authority says otherwise.
Tool auto-memory, session summaries, and handoffs are context only: re-read current product
authority and revalidate Git before deriving product direction, authorization, or readiness from
cached memory.

For API-first earthwork evidence, external-system integration, future MCP access, or first-request
design, also read `docs/architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md`
and `docs/design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md`. They set product-direction and
target requirements only; they create no endpoint, MCP server, client topology, vendor support,
runtime authorization, or product-state transition.

For the long-term product boundary, read
`docs/architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md`:
flight, autonomous acquisition, tactical perception/control, and customer production
reconstruction are outside long-term Site Intelligence responsibility, and their sources are
retained transitional implementation until a verified successor move. It supersedes acquisition
product-responsibility routing in the Constitution/Ledger/PRD and ADR-KSI-037 D6/ADR-KSI-038
acquisition clauses without changing quantitative semantics, originals, invariants, EXT-VAL,
or milestone history.

For platform identity, spatial-data delivery, external application reuse, or long-term scope, also
read `docs/architecture/ADR-KSI-038-spatial-data-and-analysis-platform.md` and its selected roadmap
`docs/superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md`. ADR-KSI-038 places data access
and analysis under the platform goal; ADR-KSI-037 remains the first analysis use-case contract.
Read target capability and verified implementation separately. Resume authority still comes from
the current user instruction and the revalidated checkpoint/named task ledger.

## Repository routing

After reading product authority, use these two routing documents before locating or changing code:

1. `REPOSITORY_STRUCTURE.md` — responsibility, canonical path, runtime boundary and R0-R3 decision
2. `docs/DOCUMENT_STATUS.md` — active authority/current-state documents versus historical evidence

These files route work; they do not override product authority or contracts. Route by responsibility:

| Responsibility | Canonical path | Boundary |
|---|---|---|
| Operator UX | `apps/dashboard/` | Displays and requests intent; owns no device authority |
| Durable product authority and workflow | `services/core/` | Owns identity, Site/WorkArea, external WorkOrder, policy, results, evidence and journals; platform assembly only |
| API/MCP consumers | `services/analysis-mcp/`, `services/spatial-data-mcp/` | Bounded source-run stdio adapters over Core; no independent authority or byte store |
| Retired DJI/Edge/managed acquisition sources | `archive/acquisition-2026/` | Historical evidence only, not a current owner or instruction entry; never runtime import/build input |
| Measurement worker | `services/processing-controller/` | Independently operated worker; measures artifacts while Core adjudicates durable state |
| Reusable domain and algorithm code | `packages/` | Import-only code, including change/BIM/defect processing libraries, through explicit package/contract boundaries |
| Contract and conformance authority | `contracts/`, `tests/contract/`, `tests/replay/` | Schema and replay verification, not product requirements |
| Active checkout task | `.opencode/working-state.md` when present + its task ledger | Resume the current Human-assigned bounded task after Git revalidation; does not close/reprioritize a product slice |
| Product slice | `docs/superpowers/product-state.md` + its named slice ledger | Current Goal/Milestone/slice/Backlog; select from it only when no active bounded checkout task exists; update at slice close (`.ksi/` retired archive) |
| Capability-track index | `docs/goals/PHASE_REGISTRY.yaml` | Track/status routing only; not current task or next-priority selection |

### Terrain-aware planning route (historical design, out-of-product)

ADR-KSI-039 excludes acquisition execution from current platform work. The following is the
preserved design/evidence route, not authorization to select or resume a runtime task.

For terrain-aware observation planning, read
`docs/architecture/ADR-KSI-035-terrain-aware-planning-and-pilot-execution.md`,
`docs/design/TERRAIN_AWARE_OBSERVATION_PLANNING_CONTRACT.md`,
`docs/acceptance/TERRAIN_AWARE_PILOT_MVP_ACCEPTANCE.md`, and
`docs/goals/TERRAIN_AWARE_PLANNING_ROADMAP.md` before selecting runtime work. They record an
approved design baseline only; no terrain-aware runtime, Pilot/device compatibility, HIL, or field
acceptance is implied. Preserve the future autonomous profile's signed/digest/device/activation
requirements and do not treat the Pilot-manual exception as an implemented wire contract.

### Runtime placement test

Place a module in `services/` only when it has an independently operated lifecycle: an HTTP listener,
daemon/polling loop, health/readiness boundary, deployment configuration, or separately started worker
entrypoint. Place code in `packages/` when another KSI module imports it and it has no independent
operational lifecycle, even when it performs substantial processing.

The approved R3 mapping is recorded in
`docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json`; its current destinations are canonical. Do not
recreate `services/change-detection`, `services/bim-integration`, or `services/defect-detection`.
Do not consolidate any other similarly named runtime modules from names alone. A new move requires an
approved scope plus dependency, build, CI, replay, deployment, and rollback evidence.

After selecting an owner path, read its nearest `README.md` and any nested `AGENTS.md`/`CLAUDE.md`, then
inspect its actual entrypoint and dependency manifest (`pyproject.toml`, `package.json`, `CMakeLists.txt`,
Dockerfile/Compose) plus owner tests. A directory name or architecture diagram alone is not runtime proof.

## Reference repositories

- `references/repos/ksi-platform`
- `references/repos/ksi-terra`
- `references/repos/ksi-scout`

They are read-only reference implementations, not product authority.

Never import runtime code directly from `references/`.
Never modify a reference submodule unless the task explicitly says `UPDATE_REFERENCE_PIN`.

## Required implementation plan

Before code changes, state:

```text
Requirement IDs:
Owner module:
Acceptance criteria:
Contracts affected:
Reference assets:
Adoption decisions:
Files to change:
Tests:
HIL or real-device assumptions:
License/data implications:
Rollback:
```

## Control boundaries (retained historical acquisition contracts)

These constraints retain their original safety meaning; they do not mount Mission/device/Edge
routes or assign current product work to the archive. Current platform ownership is the table above.

- Manifold owns tactical perception, tracking, local world model, risk, active perception and local mission decisions.
- DJI Flight Controller owns stabilization, low-level flight, verified reactive avoidance and RTH.
- Core owns signed Mission Contract, policy, map/model versions and workflow.
- LLM must not emit executable flight coordinates or bypass safety policy.
- Server loss must not invalidate a locally valid Mission Contract.

## Quality

Do not claim completion from mocks, imports or unit tests alone.
Use contract tests, replay tests and real-device/HIL gates where applicable.
Unknown facts and unverified DJI behavior must remain explicit.
