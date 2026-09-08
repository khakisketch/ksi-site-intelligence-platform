# Terrain-aware observation planning — design baseline implementation

> For agentic workers: use `superpowers:subagent-driven-development`; Human authorization overrides automatic commits and external actions.

**Goal:** Record the approved KSI-generated/Pilot-operated, terrain-aware orthomapping product decision, align authoritative documents, and hand off gated implementation work packages. This goal does not implement flight software or accept an MVP.

**Architecture:** KSI owns deterministic preflight observation planning; the pilot owns exceptional edits and final execution approval. Core preserves original planning and postflight evidence separately; future PSDK/autonomous execution keeps its strict activation contracts.

**Tech Stack:** Existing Markdown/YAML/CSV authority and acceptance documents; existing Python contract tests for regression evidence only.

**Spec:** The Human-approved decisions reproduced below are the execution input. ADR-KSI-035 becomes their canonical repository record after this task, not an assertion of runtime support.

## Approved decisions / global constraints

- Default: Site/AOI/observation requirement -> deterministic KSI server planner -> validation -> DJI-compatible artifact -> download -> Pilot 2 import -> pilot review/exception edits -> pilot final approval -> flight -> postflight evidence and quality assessment.
- Pilot-native creation from scratch is not the default. No edited-artifact preflight return to KSI is required in this manual Pilot profile. Postflight assessment is not retroactive flight authorization.
- Orthomapping includes initial mapping, repeat observation and partial reobservation. Terrain-aware planning, known structures, takeoff-to-site/transit/normal-return paths are in the target; it is NOT restricted to a fixed-altitude MVP. Oblique/close inspection, real-time obstacle avoidance and DJI emergency RTH replacement are excluded.
- First-site planning uses lawfully available maps/data and operator-provided facts; a prior site survey, own DSM/point cloud or BIM is NOT a prerequisite. Later observations improve future plans. Missing/stale data is explicit, not zero elevation or proof of safety. GNSS positioning facts do not constitute an obstacle map.
- Preserve KSI planned artifact, pilot final plan, actual flight log and actual capture evidence separately; bytes, versions, timestamps, provenance and edit reason link them. Unknown modification is not false; an exported final plan is not actual trajectory; declarations are not device receipts.
- Missing evidence limits only dependent claims. Permit ingestion/reconstruction subject to their own requirements; quantitative analysis still needs its own integrity/CRS/vertical/profile/lineage/quality evidence. Overall observation acceptance is distinct from individual analysis availability.
- LLM never creates executable coordinates or approvals. Future PSDK signing/digest/device/activation gates remain intact. No claim of legal approval, collision-free operation, exact M4D compatibility or superiority to Pilot 2 without the respective evidence.
- Customer-side reconstruction programs, CAD/BIM progress redesign and automatic media transfer are outside this decision. Preserve existing runtime APIs/behavior and history; document design-versus-implementation gaps explicitly.
- No runtime code, schemas/OpenAPI wire behavior, tests, vendor/reference bytes, credentials, device actions, commits, pushes, PR changes, merges or deployments in this documentation task.

## Task 1: Align authority, design, acceptance and successor work

**Owner:** Documentation worker; one writer for the connected authority set.

**Requirement IDs:** REQ-MSN-101/104, REQ-ACQ-101, REQ-UX-101 and relevant REQ-INT-102/103; preserve existing identifiers and explicitly scope any amendments. Invariants touched in design: INV-016 and observational readiness INV-017/018; preserve INV-001/002, autonomous INV-011/012, INV-020/024, INV-051/053/060.

**Owned files:** New ADR `docs/architecture/ADR-KSI-035-terrain-aware-planning-and-pilot-execution.md`; new `docs/design/TERRAIN_AWARE_OBSERVATION_PLANNING_CONTRACT.md`; new `docs/acceptance/TERRAIN_AWARE_PILOT_MVP_ACCEPTANCE.md`; relevant existing text in product Constitution/Decision Ledger/PRD/Domain Invariants, active architecture ADRs 019/022/023/027/028/029 and architecture index/overview/boundaries as necessary for direct contradictions; docs/00_READ_FIRST.md, docs/DOCUMENT_STATUS.md, docs/hil/FIELD_0A_CHECKLIST.md, docs/hil/README.md, docs/goals/PHASE_REGISTRY.yaml, docs/acceptance/REQUIREMENTS_TRACEABILITY_v3.0.csv, REPOSITORY_STRUCTURE.md, AGENTS.md and CLAUDE.md. New successor roadmap `docs/goals/TERRAIN_AWARE_PLANNING_ROADMAP.md`. Only change directly affected passages; retain original decisions as scoped history. Lead owns this execution plan, scratch ledger and goal-helper updates.

**Contracts:** Write design-level input/output/provenance and degraded-evidence semantics, not a fictitious implemented API. Additive eventual interfaces: planning input snapshot, structured draft + validation, planned artifact, postflight final/log/captures and claim-scoped assessment. Profile distinction must prevent a manual exception from weakening autonomous execution or reusing a mismatched contract.

**Reference assets/adoption:** REFERENCE_ONLY: existing mission-planning geometry/camera/coverage/terrain/WPML, Core mission_plans/flight_artifacts/analysis_readiness and FIELD-0a. No reference runtime imports. Lead will provide primary-source data-research notes; incorporate as candidate evidence, not supplier selection or license approval.

**Steps:**
- [x] Read authority, nearest instructions and current contract/acceptance surfaces. Create ADR with Human approval provenance dated 2026-09-06 and statuses design approved, runtime not implemented/partially existing, physical acceptance not verified.
- [x] Align active authorities and scope conflicting old statements (compiler candidate-only, universal preflight rebind, manual KMZ recovery-only, Core HOW exclusion, universal all-or-nothing readiness). Do not overwrite autonomous historical evidence.
- [x] Define document interfaces, immutable evidence relationships, failure/unknown handling, and current code gaps. Distinguish draft quality, executable artifact validation, operational safety and actual data quality.
- [x] Create acceptance matrix for deterministic replay; first site without own DSM; terrain/structures/irregular AOI/transit; missing/stale inputs; GSD/coverage; Pilot unchanged/edited/aborted flow; missing final/log; independent quantitative eligibility; organization isolation; autonomous regressions. Every unexecuted gate remains NOT_RUN/NOT_VERIFIED. No fabricated numeric safety/quality thresholds.
- [x] Create successor work packets with objective, owned modules, forbidden scope, worktree policy, dependencies, skills, test commands, return/stop conditions. Sequence authority/common contracts before independent geodata/planner/postflight workers; Console after APIs; max 2-3 writers on separate worktrees; independent task review then integration review and Lead validation. Supplier selection, thresholds and optimization objectives require evidence-backed design closure before runtime implementation, not worker guesswork.
- [x] Route AI entrypoints to ADR/design/acceptance/roadmap; update Phase Registry with separate design/software/physical states. Document remaining customer-data/model/field decisions separately.
- [x] Validate Markdown local links for changed documents, YAML/CSV structure, requirement references and `git diff --check`. Run available existing relevant document/contract tests without weakening assertions. Report baseline failures or missing dependencies separately. No full hardware suite necessary for docs.

**HIL assumptions:** Exact aircraft/RC/Pilot/firmware import/edit/export/log evidence is absent. No device probing or field action authorized. Prepare acceptance procedures only.

**License/data:** Only public primary-source documentation is researched. No proprietary dataset ingestion, license acceptance, purchases, credentials or customer data.

**Rollback:** Isolated uncommitted documentation diff; preserve original source/main and PR18. No migration or destructive reset. Revert only reviewed task changes if Human later requests.

## Task 2: Independent review and Lead gate

- [x] Documentation worker stops and returns changed files, actual validation, risks and deviations.
- [x] Independent reviewer checks specification and quality, changed links/statuses, contradictory active authority and unchanged execution boundaries. Reviewer cannot edit; capture status before/after. At most two correction rounds before Lead adjudication per AGENTS.
- [x] Whole-diff integration review after task PASS; Lead inspects all diff and reruns meaningful local validation.
- [x] Locate the existing goal helper; update only through its supported worktree-scoped operations. If unavailable, do not hand-edit `.ksi`; record the limitation and use native session goal plus Phase Registry/roadmap.
- [x] Record completed documentation evidence separately from NOT_IMPLEMENTED/NOT_VERIFIED software/device gates. Preserve worktree and no-commit state for handoff.

## Validation commands

Baseline/targeted regression (using an existing compatible environment if available):
`pytest tests/contract/test_repository_normalization.py tests/contract/test_mission_planning.py tests/contract/test_mission_plans.py tests/contract/test_flight_artifacts.py tests/contract/test_analysis_readiness.py -q`

Also run `git diff --check`, YAML/CSV parsing, changed-file local-link resolution and explicit changed-file scope inspection. Report the exact interpreter/environment used. No test result proves Pilot compatibility or field acceptance.
