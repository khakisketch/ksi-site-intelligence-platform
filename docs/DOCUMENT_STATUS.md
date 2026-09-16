# Document status and replacement index

Status: active repository-document routing index (2026-09-04). This index changes document routing;
it does not change product decisions or current capability state.

## Active authority and state

| Family | Status | Canonical path |
|---|---|---|
| Product definition | ACTIVE | [`product/PRODUCT_CONSTITUTION.md`](product/PRODUCT_CONSTITUTION.md) |
| Durable decisions | ACTIVE | [`product/FINAL_DECISION_LEDGER_v1.0.md`](product/FINAL_DECISION_LEDGER_v1.0.md) and accepted ADRs |
| Product requirements | ACTIVE | [`product/MASTER_PRD_v3.0.md`](product/MASTER_PRD_v3.0.md) |
| Terrain-aware Pilot planning design | ACTIVE DESIGN | [`architecture/ADR-KSI-035-terrain-aware-planning-and-pilot-execution.md`](architecture/ADR-KSI-035-terrain-aware-planning-and-pilot-execution.md), [`design/TERRAIN_AWARE_OBSERVATION_PLANNING_CONTRACT.md`](design/TERRAIN_AWARE_OBSERVATION_PLANNING_CONTRACT.md), [`acceptance/TERRAIN_AWARE_PILOT_MVP_ACCEPTANCE.md`](acceptance/TERRAIN_AWARE_PILOT_MVP_ACCEPTANCE.md) and [`goals/TERRAIN_AWARE_PLANNING_ROADMAP.md`](goals/TERRAIN_AWARE_PLANNING_ROADMAP.md) — design approved; runtime/physical acceptance not verified |
| Domain invariants | ACTIVE | [`product/DOMAIN_INVARIANTS.md`](product/DOMAIN_INVARIANTS.md) |
| Customer-owned reconstruction | ACTIVE (direction; implementation in progress) | [ADR-KSI-036](architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md), [release plan](superpowers/plans/2026-09-06-external-reconstruction-release.md), and local [Slice 2 API evidence](audit/EXTERNAL_RECONSTRUCTION_INGRESS_API_VERIFICATION.md). The bounded API returns an opaque `submissionRef` for revision routes; raw customer IDs remain durable identity, not route segments. Originals stay with customer. Semantic validation, external-comparison compatibility, Console, customer export compatibility, retention/resource deployment, remote CI/deployment, vendor acceptance, and field acceptance remain separate release work. |
| Runtime/API contracts | ACTIVE | [`../contracts/`](../contracts/) |
| Current phase state | ACTIVE | [`goals/PHASE_REGISTRY.yaml`](goals/PHASE_REGISTRY.yaml) |
| Current product state | ACTIVE | [`superpowers/product-state.md`](superpowers/product-state.md) — current Goal/Milestone/slice/Backlog SSOT (updated only at slice close) |
| Durable goal/risk state | RETIRED (archived) | [`archive/ksi-legacy-2026/`](archive/ksi-legacy-2026/) (archived: `goals.json`, `ledger.jsonl`, `state.json`, `.gitignore`, `goals.lock`; external helper `ksi-goals.py` retired, not archived); replaced by `superpowers/product-state.md` + plans ledger |
| Repository structure | ACTIVE | [`../REPOSITORY_STRUCTURE.md`](../REPOSITORY_STRUCTURE.md) |
| Service/package placement decision | ACTIVE | [`architecture/ADR-KSI-034-service-package-runtime-boundary.md`](architecture/ADR-KSI-034-service-package-runtime-boundary.md) and [`audit/REPOSITORY_MIGRATION_MANIFEST_R3.json`](audit/REPOSITORY_MIGRATION_MANIFEST_R3.json) |
| HIL route index | ACTIVE | [`hil/README.md`](hil/README.md) |
| External-loop product clarification | ACTIVE (subordinate to ADR-KSI-036; changes no frozen authority) | [`product/MVP_SCOPE_AND_ENGINE_TRACKS.md`](product/MVP_SCOPE_AND_ENGINE_TRACKS.md), [`product/ENGINE_COMPARISON_PROTOCOL.md`](product/ENGINE_COMPARISON_PROTOCOL.md) |
| External-loop ops verification | ACTIVE (verification only; no code/contract change) | [`ops/DEV_EXTERNAL_RUNBOOK.md`](ops/DEV_EXTERNAL_RUNBOOK.md), [`ops/BROWSER_E2E_CHECKLIST.md`](ops/BROWSER_E2E_CHECKLIST.md), [`audit/EXTERNAL_PRODUCT_LOOP_BROWSER_PASS_2026-09-17.md`](audit/EXTERNAL_PRODUCT_LOOP_BROWSER_PASS_2026-09-17.md), [`audit/EXTERNAL_PRODUCT_LOOP_FIXTURE_RUN_2026-09-17.md`](audit/EXTERNAL_PRODUCT_LOOP_FIXTURE_RUN_2026-09-17.md) |

## Superseded or historical families

| Path/family | Status | Replacement / allowed use |
|---|---|---|
| `architecture/02_SERVICE_BLUEPRINT_AND_UX.md` | SUPERSEDED | ADR-KSI-024/025/026 and `architecture/05_OPERATIONS_CONSOLE_PHASE_1_STANDARD.md`; historical UX seed only |
| `architecture/ARCHITECTURE_DECISIONS_BASELINE_v2.0.md` | SUPERSEDED | `architecture/ARCHITECTURE_DECISIONS_v3.0.md` plus accepted ADR-KSI files |
| `acceptance/REQUIREMENTS_TRACEABILITY_BASELINE_v2.0.csv` | SUPERSEDED | `acceptance/REQUIREMENTS_TRACEABILITY_v3.0.csv` |
| `goals/HANDOFF_2026-08-09.md` | HISTORICAL | `.ai/handoff.md`, `superpowers/product-state.md` + plans ledger, and Phase Registry for current state |
| `goals/REMAINING_WORK_PLAN.md` dated tables | HISTORICAL SNAPSHOT | Its own header delegates current status to `superpowers/product-state.md` + plans ledger and Phase Registry |
| `.ai/audits/*`, `docs/audit/*` | EVIDENCE | Audit-time findings only; no product or current-state authority |
| `.ai/mvp-*`, `.ai/*` previous sections | HISTORICAL | Current top section plus authoritative product/state documents |
| `docs/superpowers/plans/*`, `docs/superpowers/specs/*` | IMPLEMENTATION HISTORY | Requirements/ADR/current goal plan control new work |
| `references/**` | REFERENCE ONLY | Adoption matrix and KSI-owned code/contracts control product behavior |
| `docs/archive/**` | ARCHIVED | May be used only as provenance/evidence; never canonical |

The current repository naming/ownership assessment is
[`audit/REPOSITORY_NAMING_AND_OWNERSHIP_AUDIT_R0_R2.md`](audit/REPOSITORY_NAMING_AND_OWNERSHIP_AUDIT_R0_R2.md).
Its `PARTIAL` verdict and proposed R3 paths are historical audit guidance. The executed
service/package slice is current only through `REPOSITORY_STRUCTURE.md`, ADR-KSI-034, and the R3
migration manifest; other proposed renames remain unapproved.

An active document may link a historical artifact to explain provenance, but it must label the link
as historical/evidence and name the active replacement. Product Constitution, Final Decision Ledger,
Master PRD, Phase Registry, and active HIL indexes must never delegate authority to an archived or
superseded file.

## Current and target media path

The canonical split is ADR-KSI-033:

- CURRENT: `SD/storage -> field PC -> KSI web upload`.
- TARGET, gated: exact `MEDIA_PULL` then `MEDIA_UPLOAD` adapter after physical evidence.
- LOCAL ONLY: PSDK Liveview as Manifold acquisition/perception input.
- NOT CORE: continuous central Liveview/video reception.
- METADATA: `EDGE_UPLINK` transports bounded EventBundle/EdgeBundle metadata, not source-media bytes.
