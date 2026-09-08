# KSI Site Intelligence repository structure

Status: canonical repository owner/purpose/runtime map for R0-R3. Product authority remains
[`docs/00_READ_FIRST.md`](docs/00_READ_FIRST.md); current execution status remains
[`docs/goals/PHASE_REGISTRY.yaml`](docs/goals/PHASE_REGISTRY.yaml) and the goal ledger.

The service-versus-package placement is normalized: independently operated processes live in
`services/`, while import-only algorithms and adapters live in `packages/`. The earlier `PARTIAL`
finding and proposed target remain historical evidence in the
[`naming and ownership audit`](docs/audit/REPOSITORY_NAMING_AND_OWNERSHIP_AUDIT_R0_R2.md); the executed
path lineage is the [`R3 migration manifest`](docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json).
Product-facing aliases such as the physical `apps/dashboard/` path for KSI Operations Console are
intentionally retained because they do not blur the runtime boundary.

The classification vocabulary is fixed: `RETAIN`, `CONSOLIDATE`, `ARCHIVE`, `REMOVE`. A runtime
directory is never removed or merged by R0-R2. Exact cleanup actions and rollback are in the
[`R0-R2 cleanup manifest`](docs/audit/REPOSITORY_CLEANUP_MANIFEST_R0_R2.json).
For `RETAIN`, `REQUIRED_REPOSITORY_PATHS` means a clean checkout must contain the source, while
`OPTIONAL_LOCAL_PATHS` means the path is protected if present but its absence in a clean clone is valid.
R3 path moves never rewrite that historical record; the migration manifest resolves its old paths to
the current destinations and records cleanup/rollback evidence.

## How an agent enters the repository

The agent first resolves **why the product permits the work**, then **which contract constrains it**,
then **which owner module may implement it**. Similar filenames or convenient import locations are not
an ownership signal.

```text
AGENTS.md / CLAUDE.md
        |
        v
00_READ_FIRST -> Constitution -> Decision Ledger -> relevant PRD section
        |
        v
Domain invariant -> contract/schema -> acceptance/replay criteria
        |
        v
REPOSITORY_STRUCTURE (owner path) + DOCUMENT_STATUS (current vs history)
        |
        v
Dashboard | Core | Gateway | Edge | Processing | reusable package
        |
        v
nearest README/agent rules -> actual manifest/entrypoint -> owner tests
        |
        v
targeted test -> broader software verification -> HIL/field gate when applicable
```

The resulting responsibility model is:

```text
Operator
  -> Dashboard: intent and evidence presentation
      -> Core: durable authority, policy, Mission and journals
          -> DJI Gateway: exact external capability/transport ports
          -> Processing Controller: artifact measurement orchestration
              -> import-only algorithm/model packages

DJI Flight Controller: stabilization, verified reactive avoidance and RTH
Manifold Edge: local acquisition, perception, world model, risk and tactical decisions
Core: signed Mission Contract and workflow; never low-level flight control
```

PSDK Liveview stays on the Manifold acquisition/perception path. `EDGE_UPLINK` carries bounded
observations/telemetry/events, while original source media uses the current SD/storage -> field PC ->
web path or a separately gated target `MEDIA_PULL`/`MEDIA_UPLOAD` adapter.

`KSI Safety` is a separate multi-sensor real-time safety operations product concept. It does not
absorb the Site Intelligence safety-patrol Mission type, and this repository must not create a
`safety/` product module merely because the two products overlap in construction-site observations.
The canonical distinction remains Product Constitution §제품 정체성 and ADR-KSI-016 D2.

## Terrain-aware planning routing (design-only)

The approved terrain-aware Pilot-default design is routed by
[`ADR-KSI-035`](docs/architecture/ADR-KSI-035-terrain-aware-planning-and-pilot-execution.md), its
[design contract](docs/design/TERRAIN_AWARE_OBSERVATION_PLANNING_CONTRACT.md),
[acceptance](docs/acceptance/TERRAIN_AWARE_PILOT_MVP_ACCEPTANCE.md), and
[successor roadmap](docs/goals/TERRAIN_AWARE_PLANNING_ROADMAP.md). These documents define future
ownership and evidence boundaries only; they do not create a runtime module, alter existing wire
contracts, establish Pilot/device support, or change the `NOT_VERIFIED` HIL/field state.

## Authority and current/target separation

| Concern | Canonical owner | Runtime? | Classification |
|---|---|---:|---|
| Product definition and durable decision | `docs/product/`, `docs/architecture/ADR-*` | No | RETAIN |
| Domain/API/HIL contract | `contracts/` | Runtime input | RETAIN |
| Current phase and durable goal state | `docs/goals/PHASE_REGISTRY.yaml`, `.ksi/` | No | RETAIN |
| Session continuity and audit snapshots | `.ai/`, dated handoffs/audits | No | RETAIN as evidence, never product authority |
| Current source-media ingress | SD/storage → field PC → KSI web upload | Operational path | RETAIN |
| Target automated source-media ingress | separately gated `MEDIA_PULL` → `MEDIA_UPLOAD` adapter | Target runtime | RETAIN gated; do not activate |
| Local acquisition video | PSDK Liveview inside Manifold acquisition/perception | Edge runtime input | RETAIN |
| Continuous central video | not a core product path | No | REMOVE from product assumptions |

## Top-level directories

`Runtime` means product code or a required runtime input, not merely a command that can be executed.
Ignored local state is listed so later cleanup does not mistake private evidence or credentials for
trash.

| Path | Owner | Purpose | Runtime | R0-R2 decision |
|---|---|---|---|---|
| `.agents/` | Agent tooling | Local agent configuration | No | RETAIN |
| `.ai/` | Repository governance | Current/previous goal, plan, handoff, audit snapshots | No | RETAIN; evidence only |
| `.claude/` | Local agent tooling | Local sessions/worktrees/plugins | No | RETAIN local; outside product source |
| `.codex/` | Local agent tooling | Local Codex configuration | No | RETAIN local |
| `.dev-data/` | Development operator | Ignored local Core/OIDC state and keys | Local runtime state | RETAIN; never archive to Git |
| `.github/` | Platform/CI | CI workflows | Build/verification | RETAIN |
| `.ksi/` | Goal governance | Durable goal/risk ledger and state | No | RETAIN; helper-owned |
| `.venv/` | Python toolchain | Reproducible local environment from `uv.lock` | No | RETAIN local; regenerated only by operator choice |
| `apps/` | Dashboard | User-facing applications | Yes | RETAIN |
| `cmake/` | Edge | Cross-build toolchains | Build/runtime delivery | RETAIN |
| `contracts/` | Cross-domain contract owners | JSON Schema, API, conformance and HIL schemas | Runtime input | RETAIN |
| `data/` | Geo/Data | Licensed/provenanced runtime data such as KNGeoid | Runtime input | RETAIN |
| `deploy/` | Operations | Compose, container, service and backup configuration | Runtime delivery | RETAIN |
| `design/` | Product design | Executable/synthetic design prototypes and studies | No | CONSOLIDATE prototypes here |
| `design-system/` | Dashboard/Product design | Durable adopted UI constraints | No | CONSOLIDATE design guardrails here |
| `docs/` | Product/architecture/operations owners | Authority, ADR, acceptance, HIL, audit and archive documents | No | CONSOLIDATE documents by subject |
| `download/` | Field evidence owner | Ignored raw device/media intake | Private evidence | RETAIN in place; do not inspect/move/delete |
| `edge/` | Manifold/Edge | Native acquisition, perception, local mission and transport seams | Yes | RETAIN; R3 audit only |
| `hil_raw_logs/` | HIL evidence owner | Ignored raw HIL originals | Private evidence | RETAIN in place; immutable for R0-R2 |
| `models/` | Model operator | Ignored fetched model/runtime artifacts | Runtime input | RETAIN local; registry stays in `docs/models/` |
| `packages/` | Domain/library owners | Reusable typed domain, geometry, contracts and algorithms | Yes | RETAIN; R3 package boundary current |
| `references/` | Reference governance | Pinned read-only reference repositories | No product runtime | RETAIN read-only; direct import forbidden |
| `scripts/` | Developer/operations tooling | Repository and device workflow entry scripts | Build/ops | RETAIN |
| `services/` | Core/Gateway/Processing owners | Independently deployed or operated services/workers | Yes | RETAIN; deployable units only |
| `templates/` | Repository governance | Agent/task templates | No | RETAIN |
| `tests/` | Quality owners | Contract, golden, replay, HIL-software and E2E verification | No | RETAIN |
| `tools/` | Domain/quality owners | Offline conversion, validation, HIL and audit tools | No direct product runtime | RETAIN |

Removed root-only generated directories (`Testing/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`,
`.playwright-mcp/`) are recorded in the cleanup manifest. They may be regenerated by their tools but
must not be tracked or treated as product evidence. Module-local ignored build outputs remain under
their owner until an explicit cleanup task removes them.

## Applications and services

| Path | Owner/purpose | Runtime | Dependency boundary | Decision |
|---|---|---:|---|---|
| `apps/dashboard/` | Dashboard — KSI Operations Console | Yes | Core HTTP/API contracts; no device authority | RETAIN |
| `services/core/` | Core — identity, site, Mission, policy, evidence and durable journals | Yes | Owns authority/state; imports reusable packages, never DJI SDK | RETAIN |
| `services/dji-gateway/` | Gateway — exact capability ports, route selection and receipts | Yes | Owns transport adapters, not product intelligence or flight control | RETAIN |
| `services/processing-controller/` | Processing — job workers, artifact measurement/upload | Yes | Reads Core work; workers measure, Core adjudicates | RETAIN |

A new `services/` child must have its own independently managed listener, daemon/polling loop,
health/readiness boundary, deployment configuration, or separately started worker entrypoint. Import
cost or algorithm complexity alone is not a service boundary.

## Edge modules

| Path | Owner/purpose | Runtime | Current status boundary | Decision |
|---|---|---:|---|---|
| `edge/psdk-app/` | Native `ksi_psdk_app`, PSDK acquisition and separately gated companions | Yes | Production Edge entry; capability remains evidence-gated | RETAIN |
| `edge/manifold-runtime/` | Native bounded queues, perception/risk/store-forward/control-plane library | Yes | Linked by approved Edge builds; no direct DJI flight command | RETAIN; no merge in R0-R2 |
| `edge/psdk-tap/` | Raw Liveview/telemetry HIL capture probe | Diagnostic only | Not product authority or production support | RETAIN |
| `edge/msdk-field-bridge/` | Conditional pre/postflight bridge candidate | Candidate | No SDK artifact/HIL support; flight actions forbidden | RETAIN gated |
| `edge/psdk-platform/` | PSDK build/platform integration | Build | Supports native Edge compilation | RETAIN |
| `edge/third_party/` | Pinned vendor provenance plus ignored fetched SDK | Build input | Lock file tracked; vendor tree ignored/read-only | RETAIN |
| `edge/docker/` | Manifold cross-build image definitions | Build | CI/toolchain only | RETAIN |

## Packages

| Path | Owner/purpose | Runtime | Primary reachability | Decision |
|---|---|---:|---|---|
| `packages/domain/` | Stable domain enums/value objects and mission/capability gating | Yes | Core, contracts, planning, processing | RETAIN |
| `packages/event-contracts/` | Observation/Event/Processing typed contracts | Yes | Core, processing and analysis services | RETAIN |
| `packages/mission-contracts/` | Signed Mission/dispatch/activation verification | Yes | Core and Edge activation companions | RETAIN |
| `packages/mission-planning/` | Deterministic coverage/geometry/WPML planning | Yes | Core Mission planning | RETAIN |
| `packages/geo-core/` | Sensor-time projection, uncertainty and local geometry | Yes | Mission planning/perception | RETAIN |
| `packages/geo-spatial/` | CRS, raster and vertical-reference operations | Yes | Core/change/processing | RETAIN; not merged with geo-core in R0-R2 |
| `packages/perception/` | Recorded/offline model evaluation and reusable perception logic | Evaluation/worker | Processing tests/workers; not production Edge runtime | RETAIN isolated |
| `packages/equipment-intelligence/` | Kinematic state, CPA/TTC and RiskField algorithms | Yes | Core evaluation | RETAIN |
| `packages/change-detection/` | Raster/point-cloud change, conformance, region and volume algorithms | Import-only | Processing worker and tests | RETAIN; moved by R3 |
| `packages/bim-integration/` | IFC georeferencing and reference-model geometry | Import-only | Conversion tool and tests | RETAIN; moved by R3 |
| `packages/defect-detection/` | Extra-gated model adapter and deterministic defect post-processing | Import-only/optional model | Model tool, optional CI and tests | RETAIN; moved by R3 |
| `packages/test-vectors/` | Shared golden/conformance vectors | Test input | Contract/replay/native tests | RETAIN |

## Non-runtime assets and generated output

| Asset class | Canonical location | Decision |
|---|---|---|
| Durable audit report | `docs/audit/` | CONSOLIDATE |
| Superseded/unreferenced UI audit capture | `docs/archive/ui-audit/<set>/` | ARCHIVE with hash/index |
| Active design prototype source | `design/<prototype>/` | RETAIN |
| Adopted design rules/tokens | `design-system/<surface>/` and application source | CONSOLIDATE; application source wins |
| Generated prototype screens/studies/build | below prototype owner, ignored | REMOVE/rebuild as needed; never authority |
| Python/CTest/browser caches | ignored below their owner | REMOVE/rebuild as needed |
| HIL originals/customer media/secrets | owner-private ignored store | RETAIN; never move into docs/archive |

## Verification ownership

| Path | Owner/purpose | Maximum conclusion |
|---|---|---|
| `tests/contract/` | Schema, authority, API, safety-gate, and integration contracts | Software contract conformance |
| `tests/replay/` | Deterministic observation-to-state/change replay | Recorded-input behavioral conformance |
| `tests/golden/` | Stable numeric and serialization vectors | Exact regression for the recorded vector set |
| `tests/hil/` | HIL evidence-tool software tests | Tool correctness, never physical capability support |
| `tests/e2e/` | Cross-module software flows | Assembled software behavior in the tested environment |

Tests inherit the same owner boundaries as runtime code. A unit, contract, replay, or browser pass
cannot promote `NOT_VERIFIED` device behavior; physical HIL/field evidence remains a separate gate.

## R3 status and remaining boundary

The Human-approved R3 service/package slice moved these three clean import-only projects without
renaming their distributions or Python imports:

- `services/change-detection/` -> `packages/change-detection/`;
- `services/bim-integration/` -> `packages/bim-integration/`;
- `services/defect-detection/` -> `packages/defect-detection/`.

ADR-KSI-034 and the migration manifest own the decision and historical path mapping. No compatibility
directory or symlink remains under `services/`.

Other similarly named or adjacent modules are still separate and are not authorized for consolidation:

- `edge/psdk-app` ↔ `edge/manifold-runtime` ↔ `edge/psdk-tap`;
- `packages/geo-core` ↔ `packages/geo-spatial`;
- `services/core/ksi_core/change_detection.py` ↔ `packages/change-detection`;
- `services/core/ksi_core/mission_plans.py` ↔ `packages/mission-planning`;
- `services/processing-controller` ↔ change/BIM/defect/perception leaf packages.

Any later deletion, merger, or rename requires a new approved scope with an exact import graph and
before/after build, test, CI, deployment and rollback evidence. Current separate ownership is retained
until that proof exists.
