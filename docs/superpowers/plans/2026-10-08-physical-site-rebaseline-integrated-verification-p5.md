# Physical Site rebaseline integrated verification — Implementation Plan (P5)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Preserve the already selected sequential execution method; independent final Reviewer/Test Runner remain required. Visual work remains design-workspace-owned.

**Status:** PROPOSAL FOR WRITTEN REVIEW — no P5 execution approval. P4 is still in rendered refinement/final verification. Execute only after P4 technical closure and Human review of this written plan; do not infer approval from the parent spec, goal mode, or this file's creation.

**Goal:** Establish a revision-bound RB-01..09 local cleanup baseline, preserving the existing first-flow contracts and clearly identifying what remains unverified or needs a successor plan.

**Architecture:** Verify the existing platform Core, independently operated inspection/Analysis/Spatial Data workers, and API/MCP consumers rather than create a second backend. Complete the archive/recovery audit, add only missing test-harness coverage, reconcile active routing documentation, and obtain independent integrated evidence. No new wire model, format, policy, transport, production activation, or product workflow is introduced.

**Tech Stack:** Existing Python 3.12 workspace/uv/pytest, FastAPI platform assembly, actual generated GeoTIFF inspection and bounded workers, official MCP SDK stdio, existing Next.js Console/Playwright. Use prepared dependencies only.

**Spec:** `docs/superpowers/specs/2026-10-07-physical-site-platform-rebaseline-design.md` (approved SHA256 `14ded50b47f2cb363f0ddf1c8edb00d85b147b3de358a38a266a5d63b388a97c`). Approval/progress authority: `docs/superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md`.

## Global Constraints

- “Flight, autonomous acquisition, tactical perception/control and customer production reconstruction are outside long-term Site Intelligence responsibility, not merely postponed MVP work.”
- “Registration, file identity, supported computability, accuracy evaluation, human review and official issuance remain separate.”
- “Existing V1 strict and V2 provisional/evaluation rules and numerical meanings remain unchanged. No implicit reprojection, co-registration, height adjustment or policy upgrade is introduced.”
- “An archive is not a runtime import path, executable default, production build context or implicit product support.”
- “No new dependencies or host installation are implied. Local target remains current main; do not push, publish, deploy, provision credentials/grants/policies, contact customers or operate equipment.”
- “Cleanup completion means a coherent, locally verified platform baseline. It does not mean customer acceptance, universal format/vendor support, quantitative accuracy, robotics safety or production readiness.”
- Retain INV-020/024/040/050/051/053/054/055/060/061. Preserve applicable signed-Mission/device constraints on historical contracts; never remount acquisition authority.
- Snapshot the actual P4 closure revision before execution. Planning observation: `main` `9a3bab1` + pending P4 output; that is NOT the final P5 execution base. One writer per file; foreign worktrees/private state remain untouched.
- Generated data and synthetic fixture grants are local checks only. Production/OIDC default empty scopes, tenant nondisclosure, consent/currentness, originals, exact source revisions/digests and native-grid rectangular Spatial Data V1 remain unchanged.
- New product gaps discovered by verification are recorded, not silently implemented. Repairs may correct a violated preserved contract; changed contracts, visual direction, grants/activation, dependencies and external effects return to their existing gates.

## Review Focus

1. A valid historical managed row must remain readable with its original meaning without becoming executable; absence of managed HTTP routes must not be called universal historical-result access (Task 2).
2. A router-only MCP fixture can pass while the real platform assembly fails; verify the actual factory and the same records/receipts through SDK and HTTP (Task 2).
3. Rights/consent revoked after preparation or during download must deny new use/bytes, preserve history, and never publish a partial successful derivative (Task 2).
4. A destination hash or inverse record omitted from a sampled archive audit can conceal lost source; visit all 194+57 recorded moves and prove the checker detects corrupt/missing/duplicate records (Task 1).
5. A stale installed editable, offline lock result or configuration-only Docker check can mask a broken fresh runtime; report exactly which environment/build was exercised and leave missing checks unverified (Task 3).

## Required implementation binding

```text
Requirement IDs: RB-01..09; preserve EXT-VAL and SDP-REQ targets without closing their acceptance.
Owner module: tools/tests (verification), Core/worker/MCP existing owners, routing docs; no new service.
Acceptance criteria: per-RB matrix below, actual revision/source hashes, independent checks, explicit limits.
Contracts affected: none changed; existing ingress, V1/V2 quantity, Spatial Data V1, identity/currentness preserved.
Reference assets: approved spec/ADR-KSI-036/037/038/039; P2/P3 receipts; P4 final source/render evidence.
Adoption decisions: reuse existing real-byte/SDK/replay fixtures; no runtime references/ or archive/ imports.
Files to change: explicitly named per task; production fixes only for demonstrated in-scope regressions.
Tests: task-scoped RED→GREEN for new tooling/coverage; existing checks rerun as verification, not fake RED.
HIL or real-device assumptions: none; no device operation or operational/customer acceptance implied.
License/data implications: generated owned fixtures; no new vendor source, customer export or data rights.
Rollback: reviewed inverse of task-owned P5 commits; read-only audit never moves source/data; no reset/clean.
```

## File map and dependency order

| Task | Owned outputs / purpose | Depends on |
| --- | --- | --- |
| 1 | `tools/verify_physical_site_archive.py`, `tests/contract/test_physical_site_archive_verification.py`: read-only complete-record integrity/recovery checker | P3 manifests, P4 closure base |
| 2 | `tests/contract/test_platform_core_http_integration.py`, existing Analysis MCP/Spatial Data/replay tests: actual-platform consumer preservation proof | Task 1 boundary findings |
| 3 | `docs/audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md`: build/lock/worker/runtime evidence and explicit missing gates | Tasks 1–2 |
| 4 | Active routing/readme/status/roadmap summaries listed below: reconcile actual current owners without changing historical approvals | Tasks 1–3 + P4 final evidence |
| 5 | Same audit + parent ledger/product-state/checkpoint: independent integrated receipt, local cleanup status and successor gap map | Tasks 1–4 |

No extra move manifest, archive rewrite, service, broad refactor, duplicated goal registry or competing product-state is introduced.

### Task 1: Complete archive integrity and recovery evidence (RB-02/08/09)

**Files:** Create the checker/test files above. Read, do not modify, `docs/audit/PHYSICAL_SITE_MOVE_EXECUTION_v1.json`, `PHYSICAL_SITE_MOVE_EXECUTION_EXTRAS_v1.json`, `PHYSICAL_SITE_MOVE_DECISIONS_v1.csv`, the frozen disposition CSV, and `tools/{execute_physical_site_moves,check_physical_site_disposition}.py`.

**Interfaces:** `verify_archive_records(root: Path, execution: Path, extras: Path) -> dict[str, object]` returns `recordsChecked`, `failures` and per-record source/destination/hash findings; CLI takes `--root`, `--execution`, `--extras`, emits JSON to stdout, exits 0 only with no failures. No apply mode, source writes, network or recovery execution. Task 3 consumes its saved JSON/hash.

- [ ] Write `test_visits_every_record`, `test_missing_or_changed_destination_fails`, `test_duplicate_or_escaping_destination_fails`, `test_wrong_git_blob_or_inverse_fails`, and `test_does_not_mutate_checkout`. Use a tiny disposable Git fixture; corrupt its final record so an early sample cannot pass. Assert each record is visited, failures are explicit, and source/destination/HEAD bytes remain unchanged.
- [ ] Run `uv run --no-sync pytest -q tests/contract/test_physical_site_archive_verification.py`; observe the missing-checker/behavior failure before implementation.
- [ ] Implement the read-only function/CLI: canonical relative paths confined to root, no symlink traversal, unique destinations, baseline Git blob SHA256 and actual destination SHA256, exact source/destination inverse pair, missing records fail closed. Reuse existing Git/blob primitives where appropriate; never execute the recorded inverse strings.
- [ ] Rerun that test file; require all controls green. Run the checker against the two tracked execution records; require **251 checked (194+57)** with no omission, or report the actual discrepancy without rewriting evidence to match.
- [ ] Run the existing disposition and archive boundary/normalization tests. Reconstruct one recorded blob per moved group in an owned disposable fixture and compare SHA256; never restore into the real checkout or open live journals.
- [ ] Commit only the checker/tests after the actual results are recorded; preserve frozen manifests and approval hashes.

### Task 2: Preserve actual-platform flow, history, API/MCP parity and recovery (RB-03/04/05/06)

**Files:** Modify `tests/contract/test_platform_core_http_integration.py` for missing full-assembly SDK parity tests; reuse `tests/contract/test_analysis_mcp_actual_inspection.py`, `spatial_data_mcp_fixture.py`, `test_spatial_data_mcp_http_integration.py`, `test_historical_managed_readers.py`, and `tests/replay/test_platform_core_replay.py` as evidence/helper inputs, not copied runtime code. Extend the replay test only if a required preserved case lacks coverage.

**Interfaces:** Existing `assemble_platform_app(data_dir, *, journal, opened, auth_registry, evidence_storage, external_result_workflow, external_analysis_local_graph, spatial_data, …) -> FastAPI`; generated `_PlatformFlowContext` and current register/seal/inspection/worker helpers remain test-only. Produce revision-bound SDK/HTTP IDs, selectors/digests, result/receipt comparisons and restart records for Task 3. No new public API.

- [ ] Rerun existing platform assembly/HTTP/replay, historical reader and Analysis MCP real-inspection tests; record counts/commands. Verify factory identity explicitly: Analysis fixture already imports `assemble_platform_app as assemble_app`; the Spatial Data SDK fixture instead constructs `_FastAPI()` and mounts routers independently. These are different evidence levels, not a reason to replace the existing lower-level tests.
- [ ] Add `test_platform_analysis_sdk_matches_http_record` and `test_platform_spatial_sdk_matches_http_receipt` to the platform integration file. Use the genuine platform app, generated-only scoped SDK identity/consent, real inspected source bytes and bounded workers. Assert SDK/API same IDs/revisions/digests, no raw keys/URLs/bytes in SDK results, no acquisition journals/routes/imports; data consumer checks pixels/CRS/transform/NoData/output hash against the independent existing oracle.
- [ ] Run the new tests before completing their test-harness wiring; observe the missing integrated path rather than weakening assertions or substituting success responses. Implement only the necessary generated fixture wiring, using platform assembly participants/storage/currentness; do not reuse the router-only app as proof of full assembly.
- [ ] Run both new tests plus the existing SDK/HTTP negative matrices. Require genuine foreign-tenant nondisclosure, missing AI consent denial, revoked metadata/new-use/bytes denial, and cancelled/interrupted output cleanup; history remains readable only under its original authorization. Add a targeted negative test only for any uncovered preserved seam.
- [ ] Run `uv run --no-sync pytest -q tests/contract/test_platform_core_assembly.py tests/contract/test_platform_core_http_integration.py tests/contract/test_historical_managed_readers.py tests/contract/test_analysis_mcp_actual_inspection.py tests/contract/test_spatial_data_mcp_http_integration.py tests/replay/test_platform_core_replay.py tests/replay/test_spatial_data_mcp_replay.py`.
- [ ] Record same-Site/area t0→t1 and t1→t2 reuse, deterministic selectors, pinned per-fixture numerical oracles and V1/V2 distinctions. The existing standard cut1/fill5/net+4/uncertainty±5 m³ oracle is NOT the separate platform 0.1 m cell oracle. Preserve both, do not normalize their numbers to each other.
- [ ] Commit task-owned test/harness coverage. A production defect requires a reproduced regression test and a narrow preserved-contract fix; a new contract or required live activation is a blocker/next-plan decision, not implicit execution authority.

### Task 3: Verify active package/build/runtime boundaries and classify orphaned lanes (RB-03/08)

**Files:** Create/update the integrated audit above; inspect `pyproject.toml`, `uv.lock`, Core/worker dependency manifests, `.dockerignore`, active Dockerfiles/Compose/CI, `test_acquisition_archive_boundary.py`, `test_platform_boot_switch.py`, and Core module inventory. No dependency sync/install, Docker build/start, CI dispatch or registry action is authorized by this proposal.

**Interfaces:** Consume Task 1 complete hash report and Task 2 actual factory/consumer receipts. Produce separate `passed`, `failed`, `unverified` gate rows with exact revision, command/exit/count/environment. No environment failure is converted into product readiness.

- [ ] Run prepared-toolchain checks: `uv lock --offline --check`, `uv run --no-sync ruff check .`, `uv run --no-sync python tools/check_core_module_boundaries.py`, `uv run --no-sync python tools/check_runtime_image_pins.py`, `uv run --no-sync python tools/validate_repository_normalization.py` (also `--check-r3-migration`), frozen disposition validation and relevant boundary tests. Expected: exit0 with nonempty scoped coverage; compare any failure to a bounded unchanged-base control.
- [ ] Run broad `uv run --no-sync mypy packages services tests tools` and changed-file scoped mypy. Compare diagnostics to the recorded pre-P3 baseline (109 errors/14 files); report actual new/pre-existing findings, never call a failing broad command green.
- [ ] Run the external validation/Analysis/Spatial Data entrypoint/config/recovery tests selected from their actual `[project.scripts]` and imports. Verify supported factory imports under an archive/acquisition deny hook with an allowed positive control. Use no live token/config/journal, new listener identity, container or installed dependency.
- [ ] Trace remaining `comparison_worker`, `design_conformance_worker`, checkpoint and LandXML consumers/entrypoints/tests. Classify exact uses as active external/platform, retained import-only historical utility, or unsupported/unwired. Keep useful source with named consumers; do not delete/archive additional files or revive a producer because of their names. Record a separately gated move proposal only if needed.
- [ ] Report fresh dependency resolution, dangling installed editables, Core/external images, CI and host checks independently. P3's offline cached environment and P4's local dev build do not prove a fresh locked image. If a prepared authorized environment is missing, leave those rows **UNVERIFIED** with the exact blocker/owner; recommend a separate scoped build-environment decision, no automatic install/pull/daemon start.
- [ ] Commit the evidence report without secrets/full private output. Test logs may remain task-scoped; durable report retains source/command/result/hash/limits.

### Task 4: Reconcile actual active routing and first-flow gaps (RB-01/02/07/09)

**Files:** Narrow corrections in `README.md`, `REPOSITORY_STRUCTURE.md`, `AGENTS.md`, `docs/{00_READ_FIRST,README,DOCUMENT_STATUS,WORKSPACE_LAYOUT_AND_QUERY_GUIDE}.md`, `docs/architecture/00_SYSTEM_OVERVIEW.md`, `services/core/README.md`, `services/processing-controller/README.md`, `apps/dashboard/README.md`, `docs/superpowers/product-state.md`, `docs/superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md`, `docs/goals/PHASE_REGISTRY.yaml`, and the integrated audit. No historical milestone/approval rewrite.

**Interfaces:** Consume final P4 source/render/independent verification snapshot and Tasks 1–3 evidence. Produce a current-owner/link table and first-flow capability matrix, distinguishing desired behavior, actual implementation, local checks, external acceptance and next approval.

- [ ] Identify exact stale active statements, then correct only their routing/status: acquisition paths are archived/out-of-product, not active canonical owners; Core has no legacy assembly/device signing aliases; retained readers do not imply mounted managed job/artifact HTTP access. Keep explicit historical links and recovery records.
- [ ] Validate changed local Markdown/YAML links and existing product-boundary/normalization gates; no authoritative instruction points into the archive. Existing approved brand/current five-tab Console structure and historical product evidence remain intact.
- [ ] Bind actual P4 product URL/start commands/source/design project and approved tokens in the existing Product binding. Verify the final P4 design review includes actual changed renders, source hashes and fixed/open defects. Missing rendered review remains blocked; do not substitute Build aesthetic approval or an artifact preview for actual login/API/save/reload evidence.
- [ ] Map the first experience: Site/WorkArea creation → two DSM registrations → area/compatibility → evidence-bound result/blockers → next observation reusing area. Record UI/API/SDK coverage and remaining gaps separately. Known P4 local limitations include scoped-OIDC Site mutations/team/pending endpoints, absent optional workflow/Analysis graph configuration and unavailable real storage bytes. Do not broaden grants, activate runtime policy or add endpoints to close the matrix.
- [ ] Record permitted customer t0/t1/t2 rights, selected external consumer/host, actual operating environment and customer acceptance as missing external inputs where still absent. Propose only the smallest next implementation plan supported by verified gaps; no new format/general Site State/feed/remote transport development.
- [ ] Commit reviewed doc-only corrections and the gap map; product slice/EXT-VAL/customer acceptance stay OPEN.

### Task 5: Independent integrated closure and successor handoff (RB-09, whole matrix)

**Files:** Integrated audit, parent rebaseline ledger, `docs/superpowers/product-state.md`, `.opencode/working-state.md` (never committed). Consume Task 4 gap map and all actual source/evidence hashes.

- [ ] Freeze actual integrated HEAD/pending task-owned file hashes; dispatch one read-only whole-P5 Reviewer over the plan/spec, actual diff, preserved contracts and concrete evidence gaps. Independently cover actual factory/consumer/recovery/security boundaries; no aesthetic re-review replacing design ownership.
- [ ] Adjudicate findings by user impact and approved contracts. Reproduce required repair tests RED→GREEN, reverify affected checks, and preserve each defect→revision→check fixed/open chain in the parent ledger. Out-of-scope/material changes remain separate decisions.
- [ ] Test Runner independently runs full active Python under ambient umask (`uv run --no-sync pytest -q -p no:cacheprovider`), Task 1/2/gate sets, scoped/broad type comparison, and final Dashboard tsc/eslint/Vitest/build plus four-viewpoint authenticated Console E2E when its source/target is affected. Record runner session ID, commands/results, tested source state and any mutation. Reuse unchanged P4 evidence only with matching required-file hashes and explicit scope.
- [ ] Complete the RB table below using real evidence; no blank row, hidden skip or guessed PASS. If a required runtime/build/access gate remains unverified, report partial local verification and the blocker rather than closing that criterion or the goal.
- [ ] Inspect index/diff, commit only task-owned changes on the recorded local target; no checkpoint/secret/unrelated change or push/deploy. Reconcile actual commit, report hashes, task ledger/product-state/checkpoint; preserve foreign/dirty workspaces.
- [ ] Present local usable level, evidence, remaining customer/build/approval blockers with owners, and the smallest proposed successor plan. Preserve the chosen sequential method; wait for its written-plan review before new execution. Neither goal completion nor cleanup acceptance closes EXT-VAL/customer/operational acceptance.

## RB completion matrix

| Criterion | Required evidence / owner | Plan task |
| --- | --- | --- |
| RB-01 | ADR-KSI-039/current authority and active routing agree; historical decisions preserved | 4/5 |
| RB-02 | All move records/destinations/inverses verified; no active delegation to archived instructions; resolved changed links | 1/4/5 |
| RB-03 | Actual platform factory + generated inspection/Analysis/data flow; no acquisition stores/routes/package imports; active worker lifecycle | 2/3 |
| RB-04 | Same SDK/API identity/source/digest/consent/currentness and typed errors; no fake bytes/empty success | 2/4 |
| RB-05 | Retained historical reader/replay proof; correct HTTP limits; immutable V1/V2/numeric/profile meanings | 2/4 |
| RB-06 | Restart/idempotency/tenant/rights/consent/revocation/cancellation/worker cleanup negative evidence | 2/3 |
| RB-07 | P4 actual auth/reload/mobile/error/empty flow + source-bound design-owned render review | 4/5 |
| RB-08 | Active lock/package/inventory/static/build/CI scope; archive excluded explicitly; missing fresh-runtime/image gates stay unverified | 1/3/5 |
| RB-09 | Independent checks on integrated source, task-owned Git and durable records match; human acceptance/external delivery separate | 5 |

## Plan self-review and handoff

- Spec §§1–3/6/10 are preserved constraints; §§4/5/8/9 map to Tasks 1–5 and RB table; §7 maps to Task 4. No gap is converted into new runtime authority.
- Shared interfaces: Task 1 report → Task 3 evidence; Task 2 actual platform flow → Tasks 3/4 gap map; P4 final snapshot + Task 4 → Task 5. Tests consume existing contracts, not a newly invented endpoint/type.
- Review-focus five cases have named checks/owner tasks. Verification-only steps do not fabricate a failing test for unchanged behavior. New checker/harness behavior retains RED→GREEN.
- Open execution gates: final P4 technical closure; Human written P5 plan review; separately scoped fresh environment/image/CI authorization if required. Approval state is separate from planning progress and evidence.
- Recommended default: retain the existing sequential method, execute local Tasks 1–5 after written approval, and report fresh image/CI/customer gates truthfully rather than install/activate/deploy implicitly.
