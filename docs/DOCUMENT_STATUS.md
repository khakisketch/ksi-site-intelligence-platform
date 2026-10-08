# Document status and replacement index

Status: active repository-document routing index (2026-09-30). This index changes document routing;
it does not change product decisions or current capability state.

## Active authority and state

| Family | Status | Canonical path |
|---|---|---|
| Product definition | ACTIVE | [`product/PRODUCT_CONSTITUTION.md`](product/PRODUCT_CONSTITUTION.md) |
| Durable decisions | ACTIVE | [`product/FINAL_DECISION_LEDGER_v1.0.md`](product/FINAL_DECISION_LEDGER_v1.0.md) and accepted ADRs |
| Product requirements | ACTIVE | [`product/MASTER_PRD_v3.0.md`](product/MASTER_PRD_v3.0.md) |
| Spatial-data and analysis platform direction | ACTIVE (accepted direction; planning only) | [ADR-KSI-038](architecture/ADR-KSI-038-spatial-data-and-analysis-platform.md), PRD §1.1.2 and [SDP-20260930](superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md). Data delivery and analysis are two product paths; DSM/ortho external reuse plus the existing analysis case are the first platform validation target. Detailed data-access contracts remain to be specified; no capability/release claim or implementation authorization. |
| Physical Site Intelligence boundary | ACTIVE | [ADR-KSI-039](architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md) — flight/autonomous acquisition/tactical perception/customer production reconstruction are outside long-term responsibility; acquisition sources are retained transitional implementation. Supersedes acquisition product-responsibility routing in Constitution/Ledger/PRD/ADR037-D6/ADR038-acquisition clauses; dated evidence, invariants, EXT-VAL, and milestone history unchanged |
| API-first earthwork evidence direction | ACTIVE (first analysis use case under ADR-KSI-038) | [ADR-KSI-037](architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md) and [first-request design](design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md). Weekly WorkArea two-epoch observed-terrain volume-change acceptance and calculation/authority semantics remain in force. This is not the entire platform completion boundary. No endpoint, vendor support, automated execution, or `EXT-VAL` state transition follows from the design. |
| Terrain-aware Pilot planning design | ACTIVE DESIGN | [`architecture/ADR-KSI-035-terrain-aware-planning-and-pilot-execution.md`](architecture/ADR-KSI-035-terrain-aware-planning-and-pilot-execution.md), [`design/TERRAIN_AWARE_OBSERVATION_PLANNING_CONTRACT.md`](design/TERRAIN_AWARE_OBSERVATION_PLANNING_CONTRACT.md), [`acceptance/TERRAIN_AWARE_PILOT_MVP_ACCEPTANCE.md`](acceptance/TERRAIN_AWARE_PILOT_MVP_ACCEPTANCE.md) and [`goals/TERRAIN_AWARE_PLANNING_ROADMAP.md`](goals/TERRAIN_AWARE_PLANNING_ROADMAP.md) — design approved; runtime/physical acceptance not verified |
| Domain invariants | ACTIVE | [`product/DOMAIN_INVARIANTS.md`](product/DOMAIN_INVARIANTS.md) |
| Customer-owned reconstruction | ACTIVE (direction; implementation in progress) | [ADR-KSI-036](architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md) D1–D6, [release plan](superpowers/plans/2026-09-06-external-reconstruction-release.md), and local [Slice 2 API evidence](audit/EXTERNAL_RECONSTRUCTION_INGRESS_API_VERIFICATION.md). Initial MVP reference workflow: RTK-equipped M4D capture → customer-controlled field PC/DJI Terra reconstruction → KSI derived-artifact/evidence registration, inspection, compatible analysis, and workflow. KSI does not operate a proprietary/customer production reconstruction service; originals stay customer-side. The bounded API returns an opaque `submissionRef` for revision routes; raw customer IDs remain durable identity, not route segments. Semantic validation, external-comparison compatibility, Console, customer export compatibility, retention/resource deployment, remote CI/deployment, vendor license/integration acceptance, RTK/map accuracy, and field acceptance remain separate release work. |
| Runtime/API contracts | ACTIVE | [`../contracts/`](../contracts/) |
| Capability-track index | ACTIVE INDEX | [`goals/PHASE_REGISTRY.yaml`](goals/PHASE_REGISTRY.yaml) — capability-track/status index and historical route; it does not select the current task or next priority |
| Active checkout task resume | ACTIVE ROUTING | `.opencode/working-state.md` when present and its named task ledger — resumes a current Human-assigned bounded task after Git revalidation; it does not close/reprioritize product slice |
| Current product slice | ACTIVE | [`superpowers/product-state.md`](superpowers/product-state.md) — Goal/Milestone/slice/Backlog SSOT and its named slice ledger; normal updates at slice close. The explicit 2026-09-30 Human direction amendment updates Goal/planning links only, not slice status or acceptance. Select work only when no active bounded checkout task exists and current user authorization permits it. |
| Durable goal/risk state | RETIRED (archived) | [`archive/ksi-legacy-2026/`](archive/ksi-legacy-2026/) (archived: `goals.json`, `ledger.jsonl`, `state.json`, `.gitignore`, `goals.lock`; external helper `ksi-goals.py` retired, not archived); product slice is now `superpowers/product-state.md` + named slice ledger, while an active checkout task uses its checkpoint + named task ledger |
| Repository structure | ACTIVE | [`../REPOSITORY_STRUCTURE.md`](../REPOSITORY_STRUCTURE.md) |
| Service/package placement decision | ACTIVE | [`architecture/ADR-KSI-034-service-package-runtime-boundary.md`](architecture/ADR-KSI-034-service-package-runtime-boundary.md) and [`audit/REPOSITORY_MIGRATION_MANIFEST_R3.json`](audit/REPOSITORY_MIGRATION_MANIFEST_R3.json) |
| HIL route index | ACTIVE | [`hil/README.md`](hil/README.md) |
| External-loop product clarification | ACTIVE (subordinate to product authority and ADR-KSI-036/037/038) | [`product/MVP_SCOPE_AND_ENGINE_TRACKS.md`](product/MVP_SCOPE_AND_ENGINE_TRACKS.md), [`product/ENGINE_COMPARISON_PROTOCOL.md`](product/ENGINE_COMPARISON_PROTOCOL.md) — engine/analysis scope does not exhaust the platform; historical release-plan priority cannot override the current product direction. |
| External-loop ops verification | ACTIVE (verification only; no code/contract change) | [`ops/DEV_EXTERNAL_RUNBOOK.md`](ops/DEV_EXTERNAL_RUNBOOK.md), [`ops/BROWSER_E2E_CHECKLIST.md`](ops/BROWSER_E2E_CHECKLIST.md), [`audit/EXTERNAL_PRODUCT_LOOP_BROWSER_PASS_2026-09-17.md`](audit/EXTERNAL_PRODUCT_LOOP_BROWSER_PASS_2026-09-17.md), [`audit/EXTERNAL_PRODUCT_LOOP_FIXTURE_RUN_2026-09-17.md`](audit/EXTERNAL_PRODUCT_LOOP_FIXTURE_RUN_2026-09-17.md) |

## Superseded or historical families

| Path/family | Status | Replacement / allowed use |
|---|---|---|
| `architecture/02_SERVICE_BLUEPRINT_AND_UX.md` | SUPERSEDED | ADR-KSI-024/025/026 and `architecture/05_OPERATIONS_CONSOLE_PHASE_1_STANDARD.md`; historical UX seed only |
| `architecture/ARCHITECTURE_DECISIONS_BASELINE_v2.0.md` | SUPERSEDED | `architecture/ARCHITECTURE_DECISIONS_v3.0.md` plus accepted ADR-KSI files |
| `acceptance/REQUIREMENTS_TRACEABILITY_BASELINE_v2.0.csv` | SUPERSEDED | `acceptance/REQUIREMENTS_TRACEABILITY_v3.0.csv` |
| `goals/HANDOFF_2026-08-09.md` | HISTORICAL | For current product slice use `superpowers/product-state.md` + its named slice ledger; for an active checkout task use its checkpoint + named task ledger. `.ai/handoff.md` is historical evidence only. |
| `goals/REMAINING_WORK_PLAN.md` dated tables | HISTORICAL SNAPSHOT | Its header delegates current routing to the product-state/named slice ledger and, when present, checkpoint/named task ledger; it does not select work. |
| `.ai/audits/*`, `.ksi/*`, `docs/audit/*` | EVIDENCE | Audit-time or retired-helper findings only; no product or current-state authority |
| `.ai/mvp-*`, `.ai/*` previous sections | HISTORICAL | Authoritative product/state documents and their named plan ledger; no `.ai/` record supplies current state |
| `docs/superpowers/plans/*`, `docs/superpowers/specs/*` | DATED IMPLEMENTATION HISTORY by default | A plan/spec is active only when current authority, the active checkout task ledger, or `product-state.md`'s named slice ledger explicitly names it; approved design documents remain active design only and never runtime/field proof |
| `references/**` | REFERENCE ONLY | Adoption matrix and KSI-owned code/contracts control product behavior |
| `docs/archive/**` | ARCHIVED | May be used only as provenance/evidence; never canonical |
| `archive/acquisition-2026/**` | ARCHIVED (P3 Task 6) | Acquisition-only sources moved blob-identical per `audit/PHYSICAL_SITE_MOVE_DECISIONS_v1.csv`; historical evidence only — never a runtime import path, workspace member, production build context, or pytest/mypy/ruff target. The single bounded exception is the `workflow_dispatch`-only `.github/workflows/historical-archive.yml` verification route (not product support). |

The current repository naming/ownership assessment is
[`audit/REPOSITORY_NAMING_AND_OWNERSHIP_AUDIT_R0_R2.md`](audit/REPOSITORY_NAMING_AND_OWNERSHIP_AUDIT_R0_R2.md).
Its `PARTIAL` verdict and proposed R3 paths are historical audit guidance. The executed
service/package slice is current only through `REPOSITORY_STRUCTURE.md`, ADR-KSI-034, and the R3
migration manifest; other proposed renames remain unapproved.

An active document may link a historical artifact to explain provenance, but it must label the link
as historical/evidence and name the active replacement. Product Constitution, Final Decision Ledger,
Master PRD, Phase Registry, and active HIL indexes must never delegate authority to an archived or
superseded file.

## External results and source-media paths

ADR-KSI-036 D6 controls the external first-release result path; ADR-KSI-033 controls the retained
source-media and Edge transport distinction:

- EXTERNAL FIRST RELEASE: `M4D capture -> customer field PC/DJI Terra -> KSI derived artifacts and bounded evidence`; customer originals remain customer-side.
- MANAGED/TEST SOURCE MEDIA: `SD/storage -> field PC -> KSI web upload`.
- TARGET, gated: exact `MEDIA_PULL` then `MEDIA_UPLOAD` adapter after physical evidence.
- LOCAL ONLY: PSDK Liveview as Manifold acquisition/perception input.
- NOT CORE: continuous central Liveview/video reception.
- METADATA: `EDGE_UPLINK` transports bounded EventBundle/EdgeBundle metadata, not source-media bytes.

Neither path verifies a Terra license/export, RTK-derived map accuracy, quantitative eligibility, or
settlement/survey acceptance by itself.
