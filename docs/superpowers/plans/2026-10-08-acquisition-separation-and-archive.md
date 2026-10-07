# Acquisition separation, worker split and source archive — implementation plan (P3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the normal Core boot/build/test/images cover only platform code plus bounded historical readers: split the processing worker's managed set out of the platform lanes, close the remaining acquisition-only package dependencies inside Core, and move the manifest-approved acquisition-only sources to `archive/acquisition-2026/` with per-path hashes and inverse procedures.

**Architecture:** Build on the P2 platform profile (`assemble_platform_app` / `build_platform_production_app`), which already runs without acquisition stores, Mission keys or flight routes. First convert the frozen disposition inventory into a current-revision move decision manifest (evidence per path, no moves). Then close consumers in dependency order: worker split → platform boot/CI switch → Core managed-module closure and dependency drop → physical moves with refreshed per-path bindings. Archived code stops being a runtime import path, a workspace member, a test/type/lint target and a Docker build input; historical managed-result readers stay inside the active boundary and old journals remain byte-identical.

**Tech Stack:** existing Python 3.12 / uv workspace / FastAPI / pytest / Ruff / mypy, existing standard-library tooling and C++ toolchain only for the bounded historical archive verification route. No new third-party dependency, interpreter, install, service or deployment.

**Spec:** [Human-approved Physical Site rebaseline](../specs/2026-10-07-physical-site-platform-rebaseline-design.md) SHA256`14ded50b47f2cb363f0ddf1c8edb00d85b147b3de358a38a266a5d63b388a97c` §6 disposition rules and §8 stage 3; [ADR-KSI-039](../../architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md); P2 deferred successor in [Platform Core assembly](2026-10-07-platform-core-assembly.md); frozen inventory [`PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv`](../audit/PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv) SHA256`89a9baf3b1f1a593bf65af02810595cea0f677a740ceb0fdf9f2e789071639e3` and its [companion report](../audit/PHYSICAL_SITE_REBASELINE_DISPOSITION.md).

**Status:** DRAFT FOR WRITTEN REVIEW; not implementation authorization. Base: main at the P2 closeout revision (code `26b3c5d`, docs through `d8be4d4`+). Discovery inputs: `.superpowers/sdd/2026-10-08-worker-archive-p3/notes.md`.

## Global Constraints

- The archive is **not** a runtime import path, an executable default, a workspace member, a production build context, a pytest/type/lint target or implicit product support. `archive/**` is added to the explicit exclusion lists of every global rule (root `pyproject.toml` `[tool.ruff] extend-exclude`, `.dockerignore`, CI paths); pytest `testpaths`/mypy targets must never reach it.
- No move/removal starts without a validated per-path manifest entry binding current path, git object/blob SHA256, owner, group decision, destination, consumers, contract/replay consequence, test/CI/build references and the exact inverse move. Files whose consumers cannot be closed stay in place (`DEFER`); no deadline forces a move.
- Protected inputs (`.ai/`, `references/`, credentials, keys, HIL raw state, other worktrees, `.dev-data` and local runtime state) are never read, copied into the archive or moved. Git history and prior evidence meaning are preserved; this plan never deletes, only relocates, and never rewrites old journal bytes, profile digests, registrations or numerical meanings.
- Platform behavior is unchanged except the documented boot/CI separation: the P2 platform profile keeps its exact contracts, fail-closed configuration, route set and tests. Strict V1 / provisional V2 meanings, INV-020/024/040/050/051/053/054/055/060/061 applicability and tenant/consent/currentness semantics stay effective.
- Historical managed results (old ProcessingJobs/artifacts/evidence/reports and their journals) remain readable through active readers; archived modules must not be importable to provide them. `tests/replay` evidence meaning is preserved; archived tests are explicitly separated, never silently skipped (RB-08).
- No new third-party dependency, version bump, install, network fetch, credential, policy activation, push, publication or deployment. One writer at a time in the current checkout; local task-owned commits at each task boundary; Primary reconciles ledger/checkpoint/product-state.
- The Console (`apps/dashboard/`) is NOT edited here; its acquisition screens may temporarily reference retired routes until the design-owned P4 Console cleanup, which is the next stage. This plan records that transitional state explicitly.
- Human written-plan review of this document is the execution gate. Ordinary reversible extraction within these contracts proceeds without per-task re-approval afterwards.

## Review Focus

1. An archived module must be unimportable: a fresh-process import of every platform entry surface (Core platform app, worker platform lanes, tools) must succeed under a deny-hook for archive paths and archived acquisition packages, and fail loudly if any active module still imports them (Tasks 3–6).
2. Old managed results stay readable after their producers are archived: retained fixture journals (managed ProcessingJob/artifact/report) remain listable/readable on the platform profile with unchanged bytes, grants and tenant isolation (Task 2, re-checked Task 7).
3. Worker lanes keep their exact fail-closed semantics after the split: every surviving entrypoint (`ksi-external-*`, `ksi-spatial-data-worker`, region-extraction lane) still refuses missing/malformed config, token, lease, currentness or identity, with its existing tests green; the retired managed entrypoint leaves no dangling Dockerfile/CI reference (Task 3).
4. Global gates cannot silently stop covering active code or accidentally cover the archive: `ruff check .`/mypy/pytest/lock/Docker contexts are verified to include exactly the active tree after the switch, with a positive + negative check (archive file touched/imported must fail; active file must be checked) (Tasks 4–6).
5. Moves are reversible and fail-closed: an interrupted or hostile move run leaves the tree unchanged (dry-run/fail-closed batch tool), every executed move's inverse is recorded and one inverted path is exercised on a disposable fixture (Task 6).

## Actual coupling at this base (from discovery, verified)

| Surface | Observed coupling |
| --- | --- |
| Frozen inventory | 2378 rows: 1447 RECONCILE, 362 RETAIN, 293 RECONCILE_DOCUMENT, 194 ARCHIVE_CANDIDATE, 82 PROTECT (.ai 77, references 5) |
| Candidates by group | edge/manifold-runtime 71; edge/psdk-tap 29; services/dji-gateway 28; edge/psdk-app 17; packages/mission-contracts 13; packages/perception 13; packages/mission-planning 9; packages/equipment-intelligence 7; edge/msdk-field-bridge 2; edge root 5 — destinations `archive/acquisition-2026/<path>` |
| Core imports of candidate packages (12 files) | production_config (risk_policy/runtime_profile), capability/runtime_api (parse_mission_contract), identity/signing_keys (KeyRegistry), observations/events+equipment_states (equipment-intelligence), edge_transport/edge_dispatch (dispatch/models/risk/runtime_profile), design/region_extraction_reports (FlightEnvelope + mission-planning geometry alias), missions/{issuance,plans,records,atomicity} (signing/models/planning) |
| Worker imports | `ksi_perception` only `runner.py:83` (managed dynamic-object masking); `ksi_change_detection` in comparison/design-conformance/region-extraction/external-analysis/measurement lanes (retained named use; region extraction is an active platform lane) |
| Core pyproject | declares ksi-mission-contracts, ksi-mission-planning, ksi-equipment-intelligence (to close) |
| Build/CI | gates job: lock, sync, image digest, `docker build .` + `import ksi_core.production` smoke (legacy factory), normalization, `ruff check .`, mypy `packages services tests tools`, `pytest -q`; jobs: external-runtime-images (inspector+measurement incl. `packages/perception` COPY), dashboard, edge-control-plane (manifold C++/ctest/ASan), edge-psdk-app-host |
| Workspace/exclusions | members `packages/*` `services/*`; `ruff extend-exclude` references/edge/apps; pytest `testpaths` tests/packages/services; `.dockerignore` excludes references/edge/apps but NOT `archive/`; root/worker/gateway Dockerfiles use `COPY . .` |

## File structure and ownership

- New decision artifacts: `docs/audit/PHYSICAL_SITE_MOVE_DECISIONS_v1.csv` + `docs/audit/PHYSICAL_SITE_MOVE_DECISIONS.md` (current-revision bindings + per-path decisions).
- New tooling: `tools/prepare_physical_site_moves.py` (fail-closed decision/manifest builder reusing `tools/check_physical_site_disposition.py` primitives) and `tools/execute_physical_site_moves.py` (dry-run default, fail-closed batch executor with inverse records); tests `tests/contract/test_physical_site_move_tooling.py`.
- New boundary tests: `tests/contract/test_acquisition_archive_boundary.py` (deny-hook import isolation, build-input exclusions), additions to existing reader/replay suites for historical readability.
- Destination tree: `archive/acquisition-2026/<original path>` (git-tracked moves; no content edits inside moved files).
- Modified existing: root `pyproject.toml` (rule exclusions only), `.dockerignore`, `Dockerfile`, `Dockerfile.worker`/`Dockerfile.gateway` (retire or repoint per decision), `deploy/compose*.yaml` + `deploy/README.md` + `deploy/gateway.config.example.json` (archived-service cleanup), `tests/contract/test_deploy_env_contract.py` (platform env alignment), `.github/workflows/ci.yml` (+ new `historical-archive.yml` for the bounded C++/PSDK verification route), `services/core/pyproject.toml`, `services/core/src/ksi_core/**` (closure edits + moves), `services/processing-controller/**`, `docs/audit/CORE_R1_MODULE_MIGRATION.json`, READMEs, `docs/DOCUMENT_STATUS.md`/`REPOSITORY_STRUCTURE.md` routing notes, canonical ledger/checkpoint (Primary only).
- No edits: `apps/dashboard/**` (P4), contracts/schemas, old journals/data, protected/private state, other worktrees.

## Task 1: Current-revision move decision manifest (no moves)

**Files:** Create `tools/prepare_physical_site_moves.py`, `tests/contract/test_physical_site_move_tooling.py`, `docs/audit/PHYSICAL_SITE_MOVE_DECISIONS_v1.csv`, `docs/audit/PHYSICAL_SITE_MOVE_DECISIONS.md`. Modify none.

**Interfaces:** `build_move_decisions(frozen_csv: Path, repo: Path) -> tuple[MoveDecision, ...]`; `MoveDecision` frozen dataclass `(path, git_object, blob_sha256, group, decision: Literal["MOVE","DEFER","RETAIN"], destination: str | None, blockers: tuple[str, ...], consumers: tuple[str, ...])`; CLI `python tools/prepare_physical_site_moves.py --frozen <csv> --out-csv <csv> --out-md <md>` exits 1 on any inconsistency (missing path, hash mismatch, unknown group), never writes partial output. `MOVE` means a closure path exists in this plan (blockers listed, emptied by Tasks 3–5 before execution); `DEFER` means no closure path and the file stays; the executor refuses any row with a non-empty `blockers` tuple.

- [ ] Write failing tests: every frozen candidate resolved against current `git ls-tree`/blob hashes; unknown/missing paths produce controlled findings; decision vocabulary enforced; the 194 candidates keep exact `archive/acquisition-2026/<path>` destinations; the four package groups start as `MOVE` rows with their recorded blockers (Core 12 import sites / worker module split / CI-Docker references); protected rows are metadata-only and never traversed.
- [ ] Run `.venv/bin/python -m pytest tests/contract/test_physical_site_move_tooling.py -q`; expect intended RED (missing tool).
- [ ] Implement the tool by reusing `check_physical_site_disposition.py` primitives (no import of the old CSV constants beyond the frozen hash); derive `consumers` from actual grep/import evidence for the recorded import sites (Core 12 files, worker modules, CI/Docker/deploy references); every `MOVE` carries the exact blocker ids that later tasks must close.
- [ ] Run tests green; generate the committed decision CSV/MD at this base and independently spot-check ten rows of different groups against actual blobs.
- [ ] Review/commit `feat: add current-revision acquisition move decisions`.

## Task 2: Historical managed-result readers verified and pinned

**Files:** Modify only if evidence shows a gap: read-path wiring under `services/core/src/ksi_core/domains/**`/routes for managed artifacts/evidence/reports. Create `tests/contract/test_historical_managed_readers.py`; extend an existing reader suite only when it already owns the named read path. The platform profile (`assemble_platform_app`) must list/read retained fixture managed results without importing acquisition packages.

**Interfaces:** none new; existing stores/routes only.

- [ ] Identify from actual code which managed results the active boundary must read (managed ProcessingArtifacts/site artifact listing, evidence, old reports) and which routes serve them on the platform profile; capture the finding in the decision companion.
- [ ] Write failing tests with retained fixture journals (managed-mode ProcessingJob/artifact records): platform app lists/reads them with exact bytes/grants/tenant isolation; a fresh-process deny-hook for `ksi_mission_contracts`/`ksi_mission_planning`/`ksi_equipment_intelligence`/`ksi_dji_gateway` proves the read path has no acquisition imports.
- [ ] If a read path is missing on the platform profile, add the minimal read-only wiring (no managed mutation/execution surface, no dummy stores); otherwise record "already covered by `<existing test>`" with evidence and add only the missing platform-profile case.
- [ ] Run the new/affected reader tests plus `tests/replay` results/history suites; record exact results.
- [ ] Review/commit `test: pin historical managed-result readers on the platform profile`.

## Task 3: Processing-controller platform/managed split

**Files:** Modify `services/processing-controller/pyproject.toml`, `src/ksi_processing_controller/**`, `README.md`, `Dockerfile.worker` (retire or repoint per decision), `deploy/compose.yaml` worker service, `.github/workflows/ci.yml` only for references this task changes. Move managed modules + their tests per Task 1 decisions.

**Interfaces:** Surviving entrypoints keep exact names/behavior: `ksi-external-inspector-daemon`, `ksi-external-inspector-entrypoint`, `ksi-external-measurement-entrypoint`, `ksi-external-measurement-daemon`, `ksi-external-validation-worker`, `ksi-external-analysis-worker`, `ksi-spatial-data-worker`. Managed-only modules (per import/entrypoint/test evidence: `runner`, `worker`, `odm`, `odm_assets`, `http_node_odm`, `workspace`, `capture_time`, `odm_masking`, and any others proven managed-only) leave the package; `comparison_worker`, `design_conformance_worker`, `design_surface_verifier`, `region_extraction_worker`, `measure`, `landxml`, `gsd`, `checkpoint_validator`, `core_client`, `observability` keep-or-move only per recorded evidence (`ksi_change_detection` stays for the external/region lanes).

- [ ] Build the per-module classification table (module → imports, tests, entrypoints, Docker/CI references, decision) as the Task 1 decision rows; every `MOVE` lists the exact consumers being removed in this task.
- [ ] Write failing boundary tests first: fresh-process deny-hook for `ksi_core.acquisition`/mission packages proves the surviving platform lanes import no managed module; each surviving entrypoint still fails closed on missing/malformed config/token (existing suites stay green).
- [ ] Move managed modules/tests per manifest; repoint `Dockerfile.worker`/`deploy/compose.yaml` worker service/CI so no dangling entrypoint reference remains; drop `ksi-perception` (and any other managed-only dependency) from the worker package; keep `ksi-change-detection`/`ksi-geo-spatial`/domain/event-contracts for the platform lanes. If the default managed worker service retires from `deploy/compose.yaml`, the external lanes' own compose files (`deploy/compose.external-reconstruction.yaml`) remain the operator path and are left functional.
- [ ] Run the full processing-controller contract suites plus the worker entrypoint tests; `ruff`/mypy on the package; `tools/check_core_module_boundaries.py` if the inventory covers the package.
- [ ] Review/commit `refactor: split managed reconstruction out of the platform worker`.

## Task 4: Platform boot / CI / build switch

**Files:** Modify `Dockerfile` (CMD → platform production factory), `.dockerignore` (+`archive/`), `deploy/compose.yaml` (core service: drop Mission signing-key/device-attestation mounts once the platform boot no longer requires them; keep ledger/data mounts), root `pyproject.toml` (`ruff extend-exclude` +`archive/**`; mypy excludes if needed), `.github/workflows/ci.yml` (image smoke → platform import; keep every other gate), create `tests/contract/test_platform_boot_switch.py`, align `tests/contract/test_deploy_env_contract.py` and `deploy/README.md` env documentation with the platform factory's required env.

**Interfaces:** `ksi_core.production.build_production_app` remains importable at this task (retires in Task 5); the Docker image CMD becomes exactly `["/app/.venv/bin/uvicorn", "ksi_core.composition.platform_production:build_platform_production_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]` (module/attribute per the P2 Task 3 factory, verified against actual source before the switch). No route/contract change.

- [ ] Write/adjust tests first: `tests/contract/test_platform_boot_switch.py` asserts the Dockerfile CMD references the platform factory, `archive/` is excluded in `.dockerignore`/ruff config, and the composed core service no longer mounts Mission signing keys/device attestation (config-as-data, fail-closed on re-introduction).
- [ ] Switch the Dockerfile CMD and the CI smoke import (`import ksi_core.composition.platform_production`); keep the existing locked build/run steps (read-only, no network) intact; verify locally-runnable equivalents where the Docker daemon is unavailable and record the limitation honestly.
- [ ] Run the CI-equivalent local gates (`ruff check .`, mypy targets, pytest scoped) to prove the exclusion changes did not narrow active coverage: touch-check that a deliberate archive file is skipped while an active file is checked; re-run `tests/contract/test_production_assembly.py`/`test_dev_assembly.py` equivalents that stay relevant and record which are superseded by the platform suites.
- [ ] Review/commit `build: boot the platform profile and separate archive inputs`.

## Task 5: Core managed-module closure and package dependency drop

**Files:** Modify/move within `services/core/src/ksi_core/**` per decision rows (missions domain, `capability/`, `edge_transport/`, equipment observations, managed composition: `composition/{assembly,base_graph,workspace_graph,production}.py` and their managed route modules, `production_config.py`, `identity/signing_keys.py`, plus the per-file evidence set); `services/core/pyproject.toml` (drop the three deps); `docs/audit/CORE_R1_MODULE_MIGRATION.json`, `services/core/README.md`, affected tests.

**Interfaces:** The P2 platform surfaces keep exact signatures/behavior. `design/region_extraction_reports.py` keeps working with an exact neutral replacement for `FlightEnvelope` (extract to the smallest existing neutral owner per foundation precedent, with literal-vector tests) — or the import is removed if evidence shows it unused. `mission_atomicity`/`mission_records` switch to `ksi_domain.signed_payload` if they survive at all (their objects were already re-exported).

- [ ] For each of the 12 recorded import sites, record the closure decision (move with consumer removal / neutral extraction / import swap) with the exact consumer evidence; write RED tests for the neutral extraction(s) and boundary tests that the platform app imports no acquisition package.
- [ ] Execute the moves/extractions; retire the legacy managed composition and their route mounting; drop the three Core dependencies; update the module inventory; keep readers (ProcessingJob/artifact/evidence stores) that carry no acquisition imports exactly as they are.
- [ ] Run: platform assembly/regression suites, historical reader tests, `tests/contract/test_core_module_migration.py`, `tools/check_core_module_boundaries.py`, scoped mypy/Ruff on the package; record exact results.
- [ ] Review/commit `refactor: close Core acquisition dependencies onto the archive boundary`.

## Task 6: Physical moves, CI historical route, lock and docs

**Files:** Create `tools/execute_physical_site_moves.py`; extend `tests/contract/test_physical_site_move_tooling.py` with executor/dry-run/inverse cases. Execute moves for every `MOVE` row (edge groups, `services/dji-gateway`, the four packages, worker/managed modules, Core managed modules) into `archive/acquisition-2026/`; modify `.github/workflows/ci.yml` and add `historical-archive.yml`; refresh `uv.lock` offline; `docs/DOCUMENT_STATUS.md`, `REPOSITORY_STRUCTURE.md`, `docs/00_READ_FIRST.md` routing notes; `deploy/compose*.yaml`/`deploy/README.md` for archived services (gateway/copilot/managed worker defs per decision); tests/tools that referenced moved paths per manifest.

**Interfaces:** `tools/execute_physical_site_moves.py --manifest <decision-csv> [--apply]` (dry-run default) verifies each blob hash, performs git-tracked moves atomically per run, writes the inverse record; a hostile/malformed manifest leaves the tree unchanged.

- [ ] RED first: tool tests (dry-run performs no change; hash mismatch refuses the whole batch; inverse record round-trips on a disposable fixture); boundary test that a fresh pytest/mypy/ruff/Docker context cannot see `archive/` while active paths stay covered.
- [ ] Execute moves per row; keep journal/data paths untouched; update every listed consumer reference in the same commit batch per group; retire or repoint CI edge jobs; update deployed-service definitions (`deploy/compose.yaml`, `deploy/compose.vm.yaml`, `deploy/compose.external-reconstruction.yaml`, `deploy/compose.copilot.yaml`, `deploy/README.md`, `deploy/gateway.config.example.json`) so no compose/service refers to an archived image, entrypoint or mount; keep the retained external-runtime image builds green (adjust their COPY lists to surviving paths only).
- [ ] Refresh the lock offline; run lock check, normalization/validator gates, module inventory, frozen-CSV validator (unchanged CSV bytes), full scoped suites for moved groups.
- [ ] Record the transition state for Console (`apps/dashboard` acquisition screens pending P4) in the companion/README.
- [ ] Review/commit per group, message `chore: archive acquisition-only sources` (one commit per group for reviewability).

## Task 7: Independent closure and reconciliation

**Files:** canonical ledger, disposition companion, product-state linkage, checkpoint (Primary). No product code.

**Interfaces:** none new.

- [ ] Fresh whole-P3 review (read-only, separate session) over the full diff; independent test-runner executes the full configured Python suite, Ruff/mypy, offline lock, inventory/disposition/normalization gates, Docker-context checks (or recorded equivalents), and the retained image-build checks; record revision/hashes/commands/passed/skipped/warnings.
- [ ] Verify RB mapping: RB-03 package-dependency closure, RB-05 history/replay, RB-08 build/lock/CI separation and no hidden skips; RB-04/06/09 evidence unchanged; RB-07 remains P4.
- [ ] Reconcile ledger/checkpoint/product-state; report the P3 technical level with open gates (P4 Console, P5 whole verification, real customer/operational acceptance).

## Deferred successor and rollback

P4 owns the Console/UI source cleanup and its design-owned rendered review (the dashboard's acquisition screens may reference retired routes until then; this is recorded, not silently fixed here). P5 proves whole RB-01..09 and selects the remaining approved first-user-flow gaps; real customer t0/t1/t2 exports/rights and the operational environment remain external acceptance blockers.

Rollback is per-move inversion from the recorded manifest (reversible git moves) plus reviewed inverse commits for closure edits; no reset/clean, no history rewrite, no journal migration. Interrupted runs leave the tree unchanged (fail-closed batch). The runtime switch (Task 4) rolls back by reverting the Dockerfile CMD to the retained legacy factory until Task 5 retires it.

## Self-review / approval gate

Requirement mapping: RB-03 package-dependency closure→Tasks 3–6; RB-05 readers/replay→Tasks 2/7; RB-08 build/CI/lock/no-hidden-skips→Tasks 4/6/7; RB-04/06 platform semantics→preserved and re-checked in Tasks 2/5/7; RB-07→P4 (explicitly deferred, not claimed). Review Focus 1–5 each have owner tasks and negative tests. Producer/consumer interfaces match the recorded actual coupling. New proposed names are explicitly new; no placeholder steps. Human written-plan review and method selection remain the gate; after approval the already-selected sequential developer/reviewer/independent-runner method continues.
