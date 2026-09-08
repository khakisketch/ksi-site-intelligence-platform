# KSI Site Intelligence Agent Instructions

## Authority

Read in this order:

1. `docs/00_READ_FIRST.md`
2. `docs/product/PRODUCT_CONSTITUTION.md`
3. `docs/product/FINAL_DECISION_LEDGER_v1.0.md`
4. `docs/product/MASTER_PRD_v3.0.md` and relevant section
5. Relevant contract/schema
6. Acceptance criteria
7. Reference adoption matrix
8. Reference code

Domain invariants (INV-xxx) are canonical in `docs/product/DOMAIN_INVARIANTS.md`.
Every implementation task must state which invariants it touches and how they are enforced.

## Repository routing

After reading product authority, use these two routing documents before locating or changing code:

1. `REPOSITORY_STRUCTURE.md` — responsibility, canonical path, runtime boundary and R0-R3 decision
2. `docs/DOCUMENT_STATUS.md` — active authority/current-state documents versus historical evidence

These files route work; they do not override product authority or contracts. Route by responsibility:

| Responsibility | Canonical path | Boundary |
|---|---|---|
| Operator UX | `apps/dashboard/` | Displays and requests intent; owns no device authority |
| Durable product authority and workflow | `services/core/` | Owns identity, policy, Mission, evidence and journals |
| DJI capability and transport adapters | `services/dji-gateway/` | Exposes verified ports/receipts; owns no product intelligence |
| Local acquisition, perception and tactical safety | `edge/psdk-app/`, `edge/manifold-runtime/` | Manifold/local only; Flight Controller keeps low-level authority |
| Measurement worker | `services/processing-controller/` | Independently operated worker; measures artifacts while Core adjudicates durable state |
| Reusable domain and algorithm code | `packages/` | Import-only code, including change/BIM/defect processing libraries, through explicit package/contract boundaries |
| Contract and conformance authority | `contracts/`, `tests/contract/`, `tests/replay/` | Schema and replay verification, not product requirements |
| Phase/goal state | `docs/goals/PHASE_REGISTRY.yaml`, `.ksi/` | Current status; update `.ksi/` only through its helper |

### Terrain-aware planning route (design-only)

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

## Control boundaries

- Manifold owns tactical perception, tracking, local world model, risk, active perception and local mission decisions.
- DJI Flight Controller owns stabilization, low-level flight, verified reactive avoidance and RTH.
- Core owns signed Mission Contract, policy, map/model versions and workflow.
- LLM must not emit executable flight coordinates or bypass safety policy.
- Server loss must not invalidate a locally valid Mission Contract.

## Quality

Do not claim completion from mocks, imports or unit tests alone.
Use contract tests, replay tests and real-device/HIL gates where applicable.
Unknown facts and unverified DJI behavior must remain explicit.
