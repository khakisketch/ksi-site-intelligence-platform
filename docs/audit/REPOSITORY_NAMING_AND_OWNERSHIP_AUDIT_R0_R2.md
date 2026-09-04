# Repository naming and ownership audit — R0-R2

Status: `PARTIAL`, evidence date 2026-09-04. This is a current-structure audit and R3 proposal, not
authority to rename runtime paths.

## Verdict

The monorepo has a sound first-level engineering split (`apps`, `services`, `edge`, `packages`,
`contracts`, `tests`), and the three principal control boundaries are visible. It is not yet fully
self-explanatory as a product repository. Several directory names describe implementation type or
history instead of the KSI product responsibility, and `services/` mixes deployable processes with
import-only libraries. The honest rating is therefore `PARTIAL`, not “normalized”.

## Product responsibility model

```text
KSI Operations Console                       apps/dashboard
  presents intent, state, blockers, evidence
                 |
                 v
KSI Site Intelligence Core                  services/core
  identity, Site, policy, Mission, durable journals, adjudication
          |                         |
          v                         v
DJI Capability Gateway              Artifact Processing Worker
services/dji-gateway                services/processing-controller
exact provider/transport ports      work leases and measurement orchestration
          |                         |
          v                         v
Manifold Edge                       change/BIM/defect/perception libraries
edge/psdk-app + manifold-runtime    current services/* leaves + packages/*
local acquisition/perception/risk

DJI Flight Controller remains outside KSI source ownership for stabilization,
verified reactive avoidance, motor control, and RTH.
```

## Current structure evidence

| Current path | Human product name | What it is | Discoverability | R0-R2 |
|---|---|---|---|---|
| `apps/dashboard/` | KSI Operations Console | Deployable Next.js application | Name is generic | RETAIN + alias in README |
| `services/core/` | KSI Site Intelligence Core | Deployable HTTP control plane | `core` is generic but ownership is coherent | RETAIN |
| `services/dji-gateway/` | DJI Capability Gateway | Deployable adapter/route process | Mostly clear; “capability” is implicit | RETAIN |
| `services/processing-controller/` | Artifact Processing Worker | Deployable polling worker | Directory and executable use different nouns | RETAIN; R3 naming candidate |
| `services/change-detection/` | Change and volume algorithms | Import-only Python package | Misleadingly looks deployable | RETAIN; R3 move candidate |
| `services/bim-integration/` | IFC reference/geometry library | Import-only Python package | Misleadingly looks deployable | RETAIN; R3 move candidate |
| `services/defect-detection/` | Defect model adapter library | Import-only/extra-gated package | Misleadingly looks deployable | RETAIN; R3 move candidate |
| `edge/psdk-app/` | Production Manifold composition | Native deployable target | Clear after reading parent index | RETAIN |
| `edge/manifold-runtime/` | Reusable native Edge runtime | Linked native library/tests | Could be mistaken for a second production app | RETAIN; document distinction |
| `edge/psdk-tap/` | PSDK HIL capture probe | Diagnostic binary | `tap` is specialist language | RETAIN; document distinction |
| `contracts/` | Wire/schema authority | JSON Schema and API/HIL contracts | Clear only when contrasted with packages | RETAIN |
| `packages/event-contracts/` | Executable Event contract models | Python types/validation | Overlaps `contracts/` in name | RETAIN; document distinction |
| `packages/mission-contracts/` | Mission verification/runtime helpers | Python package plus bounded CLIs | “contracts” understates executables | RETAIN; R3 naming review |
| `.ksi/` | Durable machine goal/risk ledger | Helper-owned state | Hidden and acronym-only | RETAIN; explain at root |
| `.ai/` | Human/session continuity | Goal, plan, handoff, audits | Name does not reveal non-authority status | RETAIN as evidence only |
| `design/`, `design-system/`, `docs/design/` | Prototype / adopted UI rules / implementation design contracts | Three different artifact classes | Names alone are ambiguous | CONSOLIDATE via indexes; R3 docs move review |
| `scripts/`, `tools/` | Repo orchestration / artifact tools | Developer entry scripts versus validators/converters | Boundary was undocumented | CONSOLIDATE via indexes |

Evidence: root `pyproject.toml` workspace members, each child `pyproject.toml`, console-script entries,
Dockerfiles, CMake targets, imports, and `.github/workflows/ci.yml`. Only Core, DJI Gateway,
Processing Worker, Operations Console, and native `ksi_psdk_app` have current product process/target
entry evidence. The change/BIM/defect directories are packages consumed by the worker/tools/tests, not
independently deployed services in the current repository.

## Naming and placement rules

1. A directory under `services/` should correspond to an independently started product process or a
   separately deployable unit. Import-only logic belongs under `packages/` unless an accepted ADR says
   why process extraction is imminent.
2. Directory README titles use the human product name first and put internal executable/package names
   second. `dashboard`, `core`, and `tap` may not be the only explanation.
3. `contracts/` owns language-neutral wire/schema authority. `packages/*-contracts/` owns executable
   language bindings and verification code; it must not become requirement authority.
4. `scripts/` orchestrates repository, development, build, or operator workflows. `tools/` validates,
   converts, imports, exports, or generates a bounded artifact. Runtime business logic belongs in neither.
5. `design/` is executable prototype source, `design-system/` is adopted UI constraints, and
   `docs/design/` is currently implementation design-contract prose, not visual design.
6. `.ksi/` is the durable helper-owned ledger. `.ai/` is session continuity/evidence and must not override
   product or phase authority.
7. A name similarity is never deletion evidence. Import, entrypoint, build, test, CI, data migration, and
   rollback evidence are all required before a runtime move.

## Proposed target structure for R3 review

This target preserves conventional monorepo categories while making product responsibility explicit.
It is a proposal; current paths remain canonical until a separate R3 approval and migration.

```text
apps/
  operations-console/             # from apps/dashboard
services/
  site-intelligence-core/         # from services/core, or retain core with product README
  dji-capability-gateway/          # from services/dji-gateway
  processing-worker/              # from services/processing-controller
packages/
  domain/
  event-contracts/                # executable bindings; wire schemas remain contracts/
  mission-contracts/
  mission-planning/
  geo-core/
  geo-spatial/
  equipment-intelligence/
  perception/
  change-detection/               # from services/change-detection
  bim-integration/                # from services/bim-integration
  defect-detection/               # from services/defect-detection
edge/
  psdk-app/                       # sole production Manifold composition
  manifold-runtime/               # reusable native runtime
  psdk-tap/                       # diagnostic/HIL probe
contracts/                        # language-neutral API/schema/HIL authority
docs/
  product/ architecture/ acceptance/ hil/ ops/ audit/ archive/
design/                           # executable prototypes only
design-system/                    # adopted UI constraints only
scripts/                          # repository/build/operator orchestration
tools/                            # bounded validators/converters/generators
```

The highest-value R3 correction is moving the three import-only `services/*` leaves into `packages/`.
Renaming `dashboard`, `core`, or gateway paths has lower architectural value and much wider deployment,
Docker, import, CI, and documentation churn; clear product READMEs may be the better long-term answer.

## R3 entry gate

R3 may begin only with an approved ownership boundary and an exact before/after inventory covering:

- Python workspace/package and import graph;
- Docker/Compose and console-script entrypoints;
- CMake/native linkage where applicable;
- CI jobs, contract/replay/golden tests, docs links, deployment names, and rollback compatibility;
- no change to Mission, capability, HIL, customer-data, or device authority.

Until then, the current runtime paths are `RETAIN` and their reachability is recorded in the cleanup
manifest.
