# Physical Site Rebaseline Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align active product authority, establish a verified file-level disposition inventory, and detach Site spatial types and external epoch identity from acquisition without moving runtime sources yet.

**Architecture:** Reuse the current repository and authoritative Core records. First extract shared value/contract types and a deterministic identity helper into existing neutral owners, preserving legacy imports and serialized meanings. Platform-only assembly, historical readers and physical archive are the next dependent workstream, not silently executable tasks in this foundation plan.

**Tech Stack:** Existing Python3.12, Pydantic, standard-library CSV/hash/Git tooling, pytest and current workspace lock. No new third-party library, installation, host configuration or network service.

**Spec:** [2026-10-07-physical-site-platform-rebaseline-design.md](../specs/2026-10-07-physical-site-platform-rebaseline-design.md), Human-approved at commit72c526b, SHA256`14ded50b47f2cb363f0ddf1c8edb00d85b147b3de358a38a266a5d63b388a97c`.

## Global Constraints

- Existing repository/current main72c526ba7b6d423443d9733d1189fccd8b47ada6; one writer. Preserve foreign worktrees, private state and reference submodules.
- Flight/acquisition/customer production reconstruction are outside long-term responsibility. Their code remains current transitional implementation until a verified successor move.
- Preserve identity, source/revision/digest bindings, grants/consent/currentness, history/replay and strict V1/V2 mathematical/evaluation semantics.
- No new endpoint, universal Site State model, format/vendor support, reprojection or robot-safety claim.
- `archive/acquisition-2026/` is outside live workspace globs. No move/removal in this plan; candidates are not action authorization.
- Keep existing historical normalization manifests/evidence. New boundary records supersede routing, not past facts or invariant IDs.
- No push/publish/deploy, signing/grant/policy activation, credentials, customer contact, equipment or shared-environment install.
- Written-plan review and execution-method selection remain required. Approved session goal does not bypass this gate.

## Review Focus

1. A current product document pointing to an obsolete flight completion requirement must label it historical and name the current boundary: Task1 authority-routing tests.
2. A stale, duplicate or escaping manifest path must fail before any move: Task2 hostile manifest tests.
3. Site input accepted/rejected differently after type extraction must be caught: Task3 pre-extraction wire/schema and geometry vectors.
4. A generated epoch ID changing after import relocation must not invalidate old external records: Task3 fixed literal epoch vector and replay.
5. A neutral import still eagerly loading acquisition/flight must fail in a fresh process, not be hidden by loaded test modules: Task3 subprocess import denial and Task4 independent regression.

## Scope decomposition and acceptance mapping

The approved spec covers coupled documentation, Core, worker/build and visual work. This first plan is a
working, independently testable foundation slice. It completes RB-01 and the inventory/authority part
of RB-02; it contributes to RB-03/04/05/08/09 but does not close them. RB-06/07 and physical moves await
the source-bound successor plan. The whole cleanup goal remains open after foundation completion.

Successor planning uses this inventory and actual import closure for platform-only assembly, worker
dependency separation, scoped historical readers, archive/build/CI and Console. Do not fill unknown
historical compatibility with permissive readers or claim an untouched legacy assembly is platform-only.

## File structure and ownership

| Owner | Files and responsibility |
| --- | --- |
| Product authority | New ADR039; Constitution/Decision Ledger/PRD; active routing/roadmap applicability |
| Repository inventory | `docs/audit/PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv` frozen baseline, new validator and tests |
| Spatial contract | New `ksi_event_contracts/site_frame.py`; legacy SiteFrame re-export, unchanged fields/config |
| Geometry library | New `ksi_geo_core/aoi.py`; exact legacy geometry module alias |
| Observation identity | New Core `domains/observations/epoch_identity.py`; unchanged deterministic function |
| Core consumers | Site imports and external reconstruction imports only; do not redesign Site/WorkOrder journals |

## Task 1: Product authority and current-versus-history routing

**Files:** Create `docs/architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md`,
`tests/contract/test_physical_site_product_boundary.py`. Modify `docs/product/PRODUCT_CONSTITUTION.md`,
`docs/product/FINAL_DECISION_LEDGER_v1.0.md`, `docs/product/MASTER_PRD_v3.0.md`,
`docs/product/DOMAIN_INVARIANTS.md`, `docs/00_READ_FIRST.md`, `docs/DOCUMENT_STATUS.md`,
`docs/README.md`, `docs/architecture/00_SYSTEM_OVERVIEW.md`, `README.md`, `AGENTS.md`,
`REPOSITORY_STRUCTURE.md`, `docs/superpowers/product-state.md`, `docs/goals/PHASE_REGISTRY.yaml`,
`docs/superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md`.

**Interfaces:** Consumes approved spec/user decision and preserved ADR036/037/038. Produces one accepted
ADR039 boundary and routing to it; current runtime tables distinguish retained transitional implementation
from target responsibility. No public contract or code change. INV-020/024/040/050/051/053/054/055/060/061
stay effective in their applicable domains; device/Mission invariants retain explicit historical scope.

- [ ] Write `test_current_authority_excludes_long_term_acquisition`, `test_external_collection_is_not_a_platform_runtime_dependency_claim`, `test_historical_decisions_have_explicit_supersession`, and `test_open_acceptance_is_not_relabelled_done`. Assert ADR039 links resolve; its current responsibility section names external collection and KSI state/evidence; Constitution and PRD link it. Compare unchanged EXT-VAL acceptance and historical milestone evidence against the base revision.
- [ ] Run `.venv/bin/python -m pytest tests/contract/test_physical_site_product_boundary.py -q`; expect failure because ADR039/current boundary does not exist, not environment/import errors.
- [ ] Write ADR039: supersede acquisition product responsibilities in Constitution, Decision Ledger, PRD and ADR037 D6/ADR038 preserved-acquisition clauses only. Preserve ADR036 customer originals/identity and ADR037 quantitative semantics; annotate older ADRs through new index/supersession routing without rewriting their dated evidence. Link all active authority to the new boundary.
- [ ] Replace current long-term flight roadmap/defaults with platform responsibility; retain historical records under explicit historical headings. Mark excluded future tasks out-of-product, never completed; retain unfinished customer/ops gates. Do not archive physical documents in this task, and do not invent a schema status enum that PHASE_REGISTRY consumers reject.
- [ ] Run the new tests plus `.venv/bin/python -m pytest tests/contract/test_repository_normalization.py -q` and `.venv/bin/python tools/validate_repository_normalization.py`; expect exit0. Any old gate requiring preserved source remains intact because no paths moved.
- [ ] Review/index only task-owned documents/tests; commit `docs: align physical site product responsibility` and record actual commands/revision in the task ledger.

## Task 2: Verified baseline disposition and fail-closed inventory tooling

**Files:** Existing planning-only `docs/audit/PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv`;
create `docs/audit/PHYSICAL_SITE_REBASELINE_DISPOSITION.md`,
`tools/check_physical_site_disposition.py`, `tests/contract/test_physical_site_disposition.py`.

**Interfaces:** CSV columns are exactly `path,baselineCommit,gitMode,gitObject,sha256,proposedDisposition,proposedDestination,requiredBeforeAction`.
Baseline is72c526ba7b6d423443d9733d1189fccd8b47ada6,2378tracked items;194archive candidates.
Allowed labels: PROTECT/RECONCILE/RETAIN/RECONCILE_DOCUMENT/ARCHIVE_CANDIDATE.
Produce `validate_disposition_manifest(root: Path, manifest: Path) -> list[str]`; CLI
`python tools/check_physical_site_disposition.py --manifest docs/audit/PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv`
returns0 only when all checks pass,1 with safe path/reason findings otherwise. It never executes moves.

- [ ] Write tests `test_exact_baseline_coverage_and_hashes`, `test_duplicate_missing_and_unknown_rows_are_refused`, `test_absolute_and_parent_paths_are_refused`, `test_candidate_requires_archive_destination_and_condition`, `test_protected_gitlinks_are_not_traversed`, `test_stale_object_or_digest_is_refused`. Assert every baseline Git entry appears once, protected objects have no delivered content hash, normal files bind Git object and SHA256, and no candidate equals current-path execution approval.
- [ ] Run `.venv/bin/python -m pytest tests/contract/test_physical_site_disposition.py -q`; expect missing-validator failure.
- [ ] Implement validator with stdlib CSV/path/hash and read-only Git object lookup. Compare against frozen Git objects, not edited working files after legitimate tasks. Reject duplicate headers/rows, wrong labels/modes/object types, malformed hashes, path traversal and inconsistent archive destinations. Read protected rows' metadata only; never dereference submodules, local credentials or symlink targets. Preserve symlink bytes as link text. Exit with findings instead of partial success.
- [ ] Document inventory provenance and planning-only meaning. Record each candidate group's consumer/CI/test/restore evidence and unresolved mixed responsibility in the companion report. No generic RECONCILE row permits deletion. A later actionable manifest must bind the then-current source revision/hash, full consumer closure and inverse move, because this baseline predates extraction edits.
- [ ] Run validator/new tests and `git diff --check`; expect exit0 and2378unique rows. Exercise a copied hostile fixture manifest, not edits to the real baseline CSV. Do not rewrite old R0/R3 manifests to manufacture coverage.
- [ ] Commit `test: guard physical site disposition inventory`; record new tool evidence separately from initial planning-time CSV validation.

## Task 3: Neutral Site spatial types and external observation identity

**Files:** Create `packages/event-contracts/src/ksi_event_contracts/site_frame.py`,
`packages/geo-core/src/ksi_geo_core/aoi.py`,
`services/core/src/ksi_core/domains/observations/epoch_identity.py`,
`tests/contract/test_physical_site_neutral_primitives.py`.
Modify `packages/mission-contracts/src/ksi_mission_contracts/models.py`,
`packages/mission-planning/src/ksi_mission_planning/geometry.py`, `packages/geo-core/pyproject.toml`,
`services/core/pyproject.toml`, `uv.lock`,
`services/core/src/ksi_core/domains/sites/sites.py`,
`services/core/src/ksi_core/acquisition/analysis_readiness.py`,
`services/core/src/ksi_core/domains/external/ingress/external_reconstruction.py`,
`docs/audit/CORE_R1_MODULE_MIGRATION.json`, package/Core READMEs.

**Interfaces:** Neutral `SiteFrame` retains `crs: str`, `vertical_datum: str`, `unit: Literal['meter']`,
`transform_version: str`, exact aliases/extra-forbid/config/validation. Legacy models re-export the
same class. `ksi_geo_core.aoi` owns existing `GeoPoint`, `AreaOfInterest` and their geometry helpers;
legacy geometry becomes an exact module alias. Preserve all existing signatures/methods/constants.
Neutral `observation_epoch_id(work_order: ObservationWorkOrder) -> str` retains
`obs-epoch-` plus first24hex of SHA256 of UTF8`organization_id + NUL + work_order_id + NUL + cycle_number`.
It introduces no new epoch journal. Old readiness re-exports this same function.

- [ ] Capture pre-extraction SiteFrame/AOI wire and schema outputs and hand-defined valid/invalid geometry vectors; write tests for exact re-export identity, serialization/schema parity, finite/bounded/degenerate polygons, and immutable external epoch IDs. Assert unchanged limits:256vertices,10000m extent,80degree absolute latitude, existing1e-6 tolerances. Preserve current error/validation semantics, not merely positive examples.
- [ ] Add a fixed epoch literal calculated independently from the above recipe, two distinct cycles/tenants and a retained external reconstruction replay vector. Add fresh-process tests importing neutral Site types and external ingress while denying acquisition imports; ensure failure occurs before extraction for the intended dependencies.
- [ ] Run `.venv/bin/python -m pytest tests/contract/test_physical_site_neutral_primitives.py -q`; expect missing neutral owners/import-denial failures.
- [ ] Move SiteFrame definition and full AOI implementation mechanically to neutral owners, preserve legacy class/module identity aliases, and change only Site/external ingress consumer imports. Move epoch helper without altering bytes. Add direct workspace dependencies `ksi-geo-core` to Core and existing `pydantic>=2.7` to geo-core; leave old acquisition dependencies for successor closure. Update module inventory with the new Core epoch module and explicit ownership.
- [ ] Refresh lock offline using the prepared existing tooling, keeping third-party versions unchanged; no sync/install or shared `.venv` mutation. If offline cache cannot resolve unchanged dependencies, report the environment blocker and continue safe documentation verification rather than downloading implicitly.
- [ ] Run new tests plus existing Site, reconstruction, readiness and module-inventory tests: `.venv/bin/python -m pytest tests/contract/test_physical_site_neutral_primitives.py tests/contract/test_sites_api.py tests/contract/test_external_reconstruction_api.py tests/contract/test_external_reconstruction_contracts.py tests/contract/test_analysis_readiness.py tests/contract/test_core_module_migration.py -q`. Run relevant geometry/signature regressions identified by actual import usages, Ruff and mypy on changed active modules; expect no new failures. No mathematical rewrite or compatibility-policy change.
- [ ] Commit `refactor: detach site primitives from acquisition`; record exact changed files, frozen checks and preserved serialized vectors.

## Task 4: Integrated foundation verification and successor handoff

**Files:** Task ledger `2026-10-07-agent-first-platform-rebaseline.md`, disposition companion report,
existing product-state only for approved scope linkage (not acceptance closure), ignored checkpoint.
No new product code owned by this task.

**Interfaces:** Consume Task1 boundary, Task2 fail-closed baseline tool and Task3 neutral primitives.
Produce a revision-bound foundation result and a concrete successor contract/context; do not change
the goal into a document-only goal or mark the entire cleanup complete.

- [ ] Independent test-runner verifies integrated revision: related authority/disposition/primitives tests, external history and OIDC scope (`test_external_result_history.py`, `test_oidc_external_history_scope.py`), existing data/MCP and actual-inspection Analysis suites, affected replay, full active Python suite, static checks and offline lock check. Record passed/skipped/warnings and actual command lines; keep unchanged prior build evidence clearly historical.
- [ ] Verify source and installed-package closure where the already-authorized isolated build environment supports changed packages; otherwise explicitly record missing build evidence. Do not install into shared environments or configure an AI host. Platform-only runtime/host acceptance remains future, regardless of successful imports.
- [ ] Record successor coupling: signing/digest helpers shared by managed artifacts, legacy result readers, monolithic app factory/routes, SiteWorkspace/Copilot mixed state, production key/device prerequisites, worker managed entrypoints, global tests/CI and Docker contexts. Build the next detailed plan from actual files, not a guessed decoder or blanket path removal.
- [ ] Reconcile task-owned index/commits, manifests, checkpoint and current goal. Report foundation outcome and open RB-03..09; preserve full customer/ops gates. No UI/browser/design completion claim in this nonvisual slice.

## Successor queue — planned direction, not executable steps in this plan

| Order | Scope to detail against foundation revision | Observable bar |
| --- | --- | --- |
| P2 | Split Core app/production composition, neutral digest helpers and external-only WorkOrder admission; keep existing external records/API and scoped historical reads | No acquisition store/signing/device prerequisite or flight mutation route; no unexpected input identity change |
| P3 | Split worker/package dependencies; reviewed active historical decoder closure; archive only manifest-approved sources; update lock/Docker/CI/tests | No active archive imports; data/Analysis workers usable; historical access/replay proven |
| P4 | Design-owned Console cleanup using actual product source/states and preserved brand | Actual auth/API flow, reload/persistence and rendered desktop/mobile/keyboard/error review |
| P5 | Whole-cleanup independent verification and first-workflow remaining-gap selection | RB-01..09 actual evidence; no fake customer/vendor/accuracy/operations completion |

New public contract breaks, changes to legacy numeric/policy meaning or unsupported visual direction
return to Human decision. Ordinary reversible extraction within the approved contracts does not.

## Self-review and execution handoff

Review Focus1..5 map to Tasks1/2/3/4. Interfaces match existing source signatures; first slice has no
destructive action or UI write. Deferred spec coverage is explicit above, rather than hidden as completed.
Recommended method: sequential developer task + fresh reviewer, Primary integrates, independent
test-runner checks the final revision. Written-plan Human review/method selection is pending.
