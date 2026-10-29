# KSI Site Intelligence repository structure

Status: canonical repository owner/purpose/runtime map for R0-R3. Product authority remains
[`docs/00_READ_FIRST.md`](docs/00_READ_FIRST.md). `.opencode/working-state.md`, when present,
identifies an active checkout task and its task ledger after Git revalidation; it does not
close/reprioritize a product slice. [`docs/superpowers/product-state.md`](docs/superpowers/product-state.md)
identifies the current product slice and slice ledger, from which work is selected only when no
active bounded checkout task exists. [`docs/goals/PHASE_REGISTRY.yaml`](docs/goals/PHASE_REGISTRY.yaml)
is a capability-track index, not a competing current-task or next-priority source.

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
Dashboard | platform Core | external workers | bounded MCP | reusable package
        |
        v
nearest README/agent rules -> actual manifest/entrypoint -> owner tests
        |
        v
targeted test -> broader software verification -> HIL/field gate when applicable
```

The resulting responsibility model is:

The additive external task handoff stays in Core (`domains/external/spatial_tasks.py`): bounded
orchestration references only. It reuses existing Site/WorkArea/WorkOrder and Analysis authority;
`services/analysis-mcp` is its scoped stdio adapter and `apps/dashboard` is the authenticated human
selector. Shared DTOs remain in `packages/event-contracts`; no separate task service, geometry
authority, computation engine or external-host configuration is introduced.

```text
Operator
  -> Console / bounded MCP / external API consumer
      -> platform Core: scoped Site/WorkArea, external observations, authority and journals
          -> independent inspection / measurement / Analysis / Spatial Data workers
              -> import-only algorithm/contract packages

External capture and reconstruction: customer responsibility, not platform runtime dependency
Gateway / Edge / signed Mission and managed reconstruction: archived historical contracts only
```

ADR-KSI-037 places the API-first Site/WorkArea/Epoch/result/evidence record at the product core.
The former acquisition topology is retained transitional implementation under
[`ADR-KSI-039`](docs/architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md),
not long-term product responsibility and not an automatic flight or robot-execution prerequisite
for the weekly two-epoch MVP. P3 relocated that source to `archive/acquisition-2026/`;
P4 removed its Console routes. Original move records and P5's two post-move hash discrepancies are
in the [integrated audit](docs/audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md).

In historical acquisition contracts PSDK Liveview stays on the Manifold acquisition/perception path. `EDGE_UPLINK` carries bounded
observations/telemetry/events. For the ADR-KSI-036 D6 external first-release route, a customer field
PC reconstructs M4D captures with DJI Terra as the initial reference workflow and KSI receives
derived artifacts/evidence; originals remain customer-side. The SD/storage -> field PC -> web raw
path is retained managed/test or separately authorized source-media scope, with a separately gated
target `MEDIA_PULL`/`MEDIA_UPLOAD` adapter. This routing does not verify a vendor tool, RTK/map
accuracy, field acceptance, or alter Edge/acquisition authority.

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
| Active checkout task resume | `.opencode/working-state.md` when present and its named task ledger | No | RETAIN; Git revalidate; does not close/reprioritize product slice |
| Current product slice | `docs/superpowers/product-state.md` and its named slice ledger | No | RETAIN; select only when no active bounded checkout task exists |
| Capability-track index | `docs/goals/PHASE_REGISTRY.yaml` | No | RETAIN; not current task selection |
| Session continuity and audit snapshots | `.ai/`, `.ksi/`, dated handoffs/audits | No | RETAIN as historical evidence, never current state or product authority |
| External first-release result ingress | M4D → customer field PC/Terra → KSI derived artifacts/evidence | Product direction | RETAIN; license/export/accuracy acceptance separate |
| Managed/test source-media ingress | SD/storage → field PC → former KSI web upload | Historical path | Preserved contracts/readers; no mounted managed producer |
| Former automated source-media target | separately gated `MEDIA_PULL` → `MEDIA_UPLOAD` adapter | Historical target | Out-of-product; do not activate |
| Local acquisition video | PSDK Liveview inside former Manifold acquisition/perception | Historical Edge input | Archived evidence, not current platform ownership |
| Continuous central video | not a core product path | No | REMOVE from product assumptions |
| Long-term product boundary | `docs/architecture/ADR-KSI-039-*` | No | RETAIN; flight/autonomous acquisition/tactical perception/customer production reconstruction are out-of-product; acquisition sources are retained transitional implementation until a verified successor move |

## Top-level directories

`Runtime` means product code or a required runtime input, not merely a command that can be executed.
Ignored local state is listed so later cleanup does not mistake private evidence or credentials for
trash.

| Path | Owner | Purpose | Runtime | R0-R2 decision |
|---|---|---|---|---|
| `.agents/` | Agent tooling | Local agent configuration | No | RETAIN |
| `.ai/` | Repository governance | Historical session handoffs and audit snapshots | No | RETAIN; evidence only, not current state |
| `.claude/` | Local agent tooling | Local sessions/worktrees/plugins | No | RETAIN local; outside product source |
| `.codex/` | Local agent tooling | Local Codex configuration | No | RETAIN local |
| `.dev-data/` | Development operator | Ignored local Core/OIDC state and keys | Local runtime state | RETAIN; never archive to Git |
| `.github/` | Platform/CI | CI workflows | Build/verification | RETAIN |
| `archive/acquisition-2026/` | P3 acquisition separation archive | Acquisition-only sources moved per `docs/audit/PHYSICAL_SITE_MOVE_DECISIONS_v1.csv`; two post-move adaptations recorded append-only in `docs/audit/PHYSICAL_SITE_MOVE_ADAPTATIONS_v1.json` (strict gate binds them to the reviewed commit) | No — historical, never runtime/build/test input | ARCHIVED; the single bounded exception is the `workflow_dispatch`-only historical verification route |
| `.ksi/` | Legacy goal governance | Retired helper-era goal/risk state | No | RETAIN as archive/evidence; product slice is `docs/superpowers/product-state.md` + named slice ledger, while an active checkout task uses its checkpoint + named task ledger |
| `.venv/` | Python toolchain | Reproducible local environment from `uv.lock` | No | RETAIN local; regenerated only by operator choice |
| `apps/` | Dashboard | User-facing applications | Yes | RETAIN |
| Former `cmake/` | Historical Edge | Cross-build toolchain moved to `archive/acquisition-2026/cmake/` | No — historical | Archived by P3; R0-R2 decision retained as provenance |
| `contracts/` | Cross-domain contract owners | JSON Schema, API, conformance and HIL schemas | Runtime input | RETAIN |
| `data/` | Geo/Data | Licensed/provenanced runtime data such as KNGeoid | Runtime input | RETAIN |
| `deploy/` | Operations | Compose, container, service and backup configuration | Runtime delivery | RETAIN |
| `design/` | Product design | Executable/synthetic design prototypes and studies | No | CONSOLIDATE prototypes here |
| `design-system/` | Dashboard/Product design | Durable adopted UI constraints | No | CONSOLIDATE design guardrails here |
| `docs/` | Product/architecture/operations owners | Authority, ADR, acceptance, HIL, audit and archive documents | No | CONSOLIDATE documents by subject |
| `download/` | Field evidence owner | Ignored raw device/media intake | Private evidence | RETAIN in place; do not inspect/move/delete |
| `edge/` | Manifold/Edge (P3 Task 6: tracked sources archived) | Native acquisition, perception, local mission and transport seams | No — historical | ARCHIVED (P3 Task 6 → `archive/acquisition-2026/edge/`, historical; R3 audit record stands) |
| `hil_raw_logs/` | HIL evidence owner | Ignored raw HIL originals | Private evidence | RETAIN in place; immutable for R0-R2 |
| `models/` | Model operator | Ignored fetched model/runtime artifacts | Runtime input | RETAIN local; registry stays in `docs/models/` |
| `packages/` | Domain/library owners | Reusable typed domain, geometry, contracts and algorithms | Yes | RETAIN; R3 package boundary current |
| `references/` | Reference governance | Pinned read-only reference repositories | No product runtime | RETAIN read-only; direct import forbidden |
| `scripts/` | Developer/operations tooling | Repository and device workflow entry scripts | Build/ops | RETAIN |
| `services/` | Core/Processing/MCP owners | Independently operated services/workers and source-run adapters | Yes | RETAIN; lifecycle/entrypoint boundary required |
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
| `services/core/` | Core — identity, Site/WorkArea, external WorkOrder, policy, results, evidence and durable journals | Yes | Platform-only factory; no Mission/device signing/managed assembly aliases | RETAIN |
| Former `services/dji-gateway/` | Historical Gateway capability ports and receipts | No — historical | Not a current owner, transport or instruction entry | ARCHIVED (P3 Task 6 → `archive/acquisition-2026/services/dji-gateway/`, historical) |
| `services/processing-controller/` | Processing — job workers, artifact measurement/upload | Yes | Reads Core work; workers measure, Core adjudicates | RETAIN |
| `services/spatial-data-mcp/` | Bounded local stdio MCP adapter — six fixed tools over one configured Core origin | No (source-run adapter; no listener/deployment) | Reads Core AI delivery only; owns no bytes, grants, credentials, or device authority | RETAIN |
| `services/analysis-mcp/` | Bounded local stdio Analysis adapter —17 fixed tools over Core, including readiness, optional delta publication and same-task human selection/resume | No (source-run adapter; no listener/deployment) | Same fixed V2 result/evidence records; no independent computation, geometry, grants or authority | RETAIN |

A new `services/` child must have its own independently managed listener, daemon/polling loop,
health/readiness boundary, deployment configuration, or separately started worker entrypoint. Import
cost or algorithm complexity alone is not a service boundary.

### Core R1 partial source routing

`services/core/src/ksi_core` is being relocated in reviewed slices; this is a Python package
ownership change, not a new service or runtime boundary. T1 canonically locates shared mechanics at
`ksi_core.foundation` and identity at `ksi_core.identity`, while their legacy root module paths are
explicit aliases to the same modules. The exhaustive active/planned map is
[`docs/audit/CORE_R1_MODULE_MIGRATION.json`](docs/audit/CORE_R1_MODULE_MIGRATION.json), checked by
[`tools/check_core_module_boundaries.py`](tools/check_core_module_boundaries.py).

The earlier R1 moves placed domains under `ksi_core.domains` and external modules under
`ksi_core.domains.external.{ingress,quantity,workflow,authority}`. P3 then archived the acquisition,
capability, managed assembly/production, signing/device and affected shims; the current inventory
records them as archived, not aliases. `ksi_core.app` still aliases the shared factory, while
`app_assembly`, `assembly`, `production` and `production_config` are absent. Active public assembly
is `ksi_core.composition.platform_assembly.assemble_platform_app`; production factory is
`ksi_core.composition.platform_production.build_platform_production_app`.
Retained `processing_jobs`/`artifact_manifest`/`source_media`/`evidence` readers remain in active
ownership for historical records, not mounted managed job/artifact HTTP or new execution.
See `services/core/README.md` and the integrated audit; no archive runtime import is allowed.

## Edge modules

| Path | Owner/purpose | Runtime | Current status boundary | Decision |
|---|---|---:|---|---|
| `edge/psdk-app/` | Native `ksi_psdk_app`, PSDK acquisition and separately gated companions | No — historical | Production Edge entry; capability remains evidence-gated | ARCHIVED (P3 Task 6 → `archive/acquisition-2026/edge/psdk-app/`) |
| `edge/manifold-runtime/` | Native bounded queues, perception/risk/store-forward/control-plane library | No — historical | Linked by approved Edge builds; no direct DJI flight command | ARCHIVED (P3 Task 6 → `archive/acquisition-2026/edge/manifold-runtime/`) |
| `edge/psdk-tap/` | Raw Liveview/telemetry HIL capture probe | No — historical | Not product authority or production support | ARCHIVED (P3 Task 6 → `archive/acquisition-2026/edge/psdk-tap/`) |
| `edge/msdk-field-bridge/` | Conditional pre/postflight bridge candidate | No — historical | No SDK artifact/HIL support; flight actions forbidden | ARCHIVED (P3 Task 6 → `archive/acquisition-2026/edge/msdk-field-bridge/`) |
| `edge/psdk-platform/` | PSDK build/platform integration | No — historical | Supports native Edge compilation | ARCHIVED (P3 Task 6 → `archive/acquisition-2026/edge/psdk-platform/psdk_platform.cmake`) |
| `edge/third_party/` | Pinned vendor provenance plus ignored fetched SDK | No — historical | Lock file tracked; vendor tree ignored/read-only | ARCHIVED (P3 Task 6 → `archive/acquisition-2026/edge/third_party/PSDK_LOCK.yaml`) |
| `edge/docker/` | Manifold cross-build image definitions | No — historical | CI/toolchain only | ARCHIVED (P3 Task 6 → `archive/acquisition-2026/edge/docker/manifold3-build.Dockerfile`) |

## Packages

| Path | Owner/purpose | Runtime | Primary reachability | Decision |
|---|---|---:|---|---|
| `packages/domain/` | Stable domain enums/value objects and mission/capability gating | Yes | Core, contracts, planning, processing | RETAIN |
| `packages/event-contracts/` | Observation/Event/Processing typed contracts | Yes | Core, processing and analysis services | RETAIN |
| `packages/mission-contracts/` | Signed Mission/dispatch/activation verification | No — historical | Core and Edge activation companions | ARCHIVED (P3 Task 6 → `archive/acquisition-2026/packages/mission-contracts/`) |
| `packages/mission-planning/` | Deterministic coverage/geometry/WPML planning | No — historical | Core Mission planning | ARCHIVED (P3 Task 6 → `archive/acquisition-2026/packages/mission-planning/`) |
| `packages/geo-core/` | Sensor-time projection, uncertainty and local geometry | Yes | Mission planning/perception | RETAIN |
| `packages/geo-spatial/` | CRS, raster and vertical-reference operations | Yes | Core/change/processing | RETAIN; not merged with geo-core in R0-R2 |
| `packages/perception/` | Recorded/offline model evaluation and reusable perception logic | No — historical | Processing tests/workers; not production Edge runtime | ARCHIVED (P3 Task 6 → `archive/acquisition-2026/packages/perception/`) |
| `packages/equipment-intelligence/` | Kinematic state, CPA/TTC and RiskField algorithms | No — historical | Core evaluation | ARCHIVED (P3 Task 6 → `archive/acquisition-2026/packages/equipment-intelligence/`) |
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
