# Platform Core Assembly Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide an explicitly selected Core runtime for existing external registration, inspection, scoped history, Analysis and data delivery without acquisition stores, Mission signing keys, device configuration or flight mutation routes.

**Architecture:** Reuse the authoritative Site/WorkArea/WorkOrder and external graphs, journals and route implementations. Add a separate platform composition entrypoint rather than weakening or pretending the retained managed assembly is independent. Extract only exact shared serialization/config helpers; preserve the managed assembly and its historical data until reader/build/archive successor closure.

**Tech Stack:** Existing Python3.12, FastAPI, Pydantic, standard-library hashing, current OIDC/storage/worker contracts and uv lock. No new third-party library, interpreter, install, remote client, service activation or deployment.

**Spec:** [Human-approved Physical Site rebaseline](../specs/2026-10-07-physical-site-platform-rebaseline-design.md), SHA256`14ded50b47f2cb363f0ddf1c8edb00d85b147b3de358a38a266a5d63b388a97c`; ADR-KSI-039 and existing external wire contracts constrain this plan.

**Status:** DRAFT FOR WRITTEN REVIEW; not implementation authorization. Source baseline main`f12857c7f178967017458057d4fd59538ff091bd`; foundation Python, changed-file static and local package evidence is recorded, while the broad type-check gate remains unpassed. The Human-selected sequential developer/reviewer method is retained, not asked again.

## Global Constraints

- Preserve existing Site/WorkArea/WorkOrder/submission/revision/digest identities and persisted numerical, permission, consent, currentness and tenant-nondisclosure semantics. No journal migration or silent repair.
- INV-020/024/040/050/051/053/054/055/060/061 remain effective; registration, computability, accuracy evaluation, human review and issuance stay separate. Terrain change is not progress, settlement or robotic safety.
- External collection is an input source, not a runtime prerequisite. Flight, autonomous acquisition, tactical control and customer production reconstruction are outside long-term responsibility.
- No physical archive/removal in this plan. Protected/private/reference/HIL/local state and other worktrees remain untouched. Frozen disposition CSV is planning-only and predates extraction.
- Existing `assemble_app`, `create_app`, `build_production_app` and compatibility aliases retain their default behavior. The new factory is explicit; no Docker/Compose/server default switches or live migration.
- Strict V1 and provisional V2 calculations/evaluation meanings, native-grid rectangular DSM/RGB/RGBA delivery and no implicit reprojection/resampling/polygon masking/Range remain unchanged.
- No public schema expansion, universal Site State model, vendor/format/client support claim, new policy activation, credential provisioning, push/publication/deployment or UI edit. New material contracts return to Human review.
- Only task-owned generated test identities/fixtures and already-prepared local tools may be used. Real customer/operational acceptance remains separately open.

## Implementation contract (effective only after this plan is approved)

Requirement IDs: RB-03 runtime part, RB-04/05/06 preservation and RB-08/09 software evidence; unchanged SDP-REQ-01/02/04/06.
Owner module: neutral domain helpers; Core composition and existing Site/WorkOrder/external domains. Workers remain separately operated consumers.
Acceptance criteria: authenticated external-only factory, no flight imports/stores/routes/key/device prerequisites, same persisted identities/digests/results; actual generated mounted flow and restart/revocation checks, independent software verification.
Contracts affected: existing API paths and wire/journal models unchanged. The new opt-in profile rejects omitted/managed WorkOrder mode and does not mount excluded mutation routes; this profile decision is submitted for written review here.
Reference assets: actual KSI-owned source at the bound revision, existing generated fixtures and built local packages; no reference repository or customer sample import.
Adoption decisions: RETAIN stores/route implementations; EXTRACT exact bytes/config helpers; add explicit composition profile. No move/remove.
Files to change: Task1–4 lists below, module inventory and existing README; no root runtime/deploy switch or Console source ownership.
Tests: task-scoped negative/positive checks, actual generated HTTP/worker/replay, existing managed preservation, full configured Python/static/lock and supported artifact checks.
HIL or real-device assumptions: none; no customer/vendor/accuracy/host/robot safety acceptance claim.
License/data implications: no new third-party version or external sample; generated owned fixtures only, with existing egress/AI consent guards unchanged.
Rollback: new profile is additive; reviewed inverse task-owned commits with retained journals unchanged. Never reset/discard user work or run concurrent apps against the same journal directory.

| Invariants | Enforcement in this slice |
| --- | --- |
| INV-020/024 | Preserve SiteFrame/AOI and exact inspection/coordinate/evaluation records; Task4 negative compatibility/accuracy paths do not turn declarations/RTK into measured accuracy. |
| INV-040 | Missing auth/storage/participants/authority is a closed configuration or typed blocker, never a mock-success/default-go graph (Tasks2–4). |
| INV-050/051/053 | Exact payload/lineage/digests, native input profiles and existing use/egress evaluators; retain managed source-authority regressions without promoting external declarations or derived serving bytes (Tasks1/4). |
| INV-054/055 | Image/managed ProcessingJob contracts unchanged and remain regression gates; no deployment manifest rewrite or replacement resource policy. Existing external Analysis/data resource admission stays Core-owned (Task4). |
| INV-060/061 | Same authenticated scoped store/route guards; cross-tenant404, human operations and per-Site AI egress checks. No Copilot/arbitrary query/storage key/approval/flight tool added (Tasks2–4). |

## Review Focus

1. A platform boot without a Mission key/device file must succeed only with its actual auth/storage prerequisites; missing auth/storage/OIDC trust must still fail before journals or clients open (Task3).
2. A retained managed WorkOrder must remain readable under its existing grants but cannot gain a new acquisition mutation through the platform profile, including omitted/default execution mode and schedule paths (Task2).
3. Empty/partial external policy, Analysis activation or data wiring must not make registration look quantitatively eligible or mount an unauthenticated/half-configured worker API (Tasks2–3).
4. Reusing an old result after restart or permission/consent/currentness loss must preserve historical numerical/evidence records while denying fresh unauthorized metadata/bytes and mutations (Task4).
5. A fresh-process import/boot that still imports acquisition, mission planning/signing, capability/device or Copilot runtime fails independence even if HTTP tests passed in a polluted interpreter (Tasks1–4).

## Actual source coupling and disposition

| Source at baseline | Observed dependency / handling |
| --- | --- |
| `composition/assembly.py:95–168,242–325` | Mandatory Mission key; eagerly builds base/workspace/capability/managed Analysis graphs. RETAIN; new platform assembly must not import/call it. |
| `composition/base_graph.py:69–159` | Always opens Mission/Edge/source/managed job journals. RETAIN; use existing Site/WorkArea constructors directly, not this graph with dummy values. |
| `composition/production.py:120–130,216–243` | Requires Mission key directory/device attestation, then loads both. RETAIN entrypoint; separate platform production factory. |
| `composition/production_config.py:12–30` | Pure auth/path helpers coexist with eager Mission/Edge imports and `assembly.cli_optional_positive`. EXTRACT only shared exact pure helpers. |
| `domains/sites/observation_work_orders.py:2132–2139,2247–2370` | Existing request defaults MANAGED_ACQUISITION; one router combines schedules, external creation, execution and operations. RETAIN journals/default; add explicit restricted routing mode. |
| `composition/external_graph.py:204–309` | Reusable external registration/inspection graph; empty policy remains pending. REUSE same callbacks/currentness and complete-work-order graph, no substitute stores. |
| `composition/spatial_data_graph.py:89–160` | Existing explicit local policy/runtime/activation and exact participants. REUSE when supplied; no new production data configuration fallback. |
| `composition/workspace_graph.py:10–14,91–155` | Eager acquisition, readiness and mixed SiteWorkspace/Copilot. RETAIN; do not require it in new backend profile or change its UI. Console cleanup is a later design-owned plan. |
| `mission-contracts/signing.py:30–52` | Shared `canonical_payload_bytes` removes only top-level `signature`, wraps JSON errors; digest includes `sha256:`. EXTRACT exact helpers, not signer/key lifecycle. |
| `domains/artifacts/{artifact_manifest,source_media}.py`, `domains/processing/processing_jobs.py`, `domains/design/report_exports.py` | Consume those exact helpers; reader-related neutral imports can change mechanically, without moving runtime or rewriting history. |
| `processing-controller/pyproject.toml:28–57`, root `Dockerfile:29–41` | One worker package includes managed entrypoints/perception; image installs all workspace packages. P3 build/worker/history/archive work, NOT closed by P2 runtime imports. |

Source snapshot SHA256s for load-bearing inputs (full commit above binds the remaining files):

| Relative path | SHA256 |
| --- | --- |
| `services/core/src/ksi_core/composition/assembly.py` | `ba0e7512f31d7e40bc0f7e281f1c90663556f7f53e1595ce9ce4a2b820664bcd` |
| `services/core/src/ksi_core/composition/base_graph.py` | `003b271601d102fe1f11abb1317e018e3369de10ebfd169d7aafb88d91e55a76` |
| `services/core/src/ksi_core/composition/app_factory.py` | `71099898582d810299de77ca67aad1875424b0a2b6ff6ca195a90362552051b7` |
| `services/core/src/ksi_core/composition/production.py` | `a144b08f1b65b70bacd0f411eb99a6667c86927138955c66379b3e623a5df5d5` |
| `services/core/src/ksi_core/composition/production_config.py` | `fbdeb9112b87118f5ba4413d8108ea017ac1f5de8ea1238141e2e580b576b4dd` |
| `services/core/src/ksi_core/composition/external_graph.py` | `b4bc88a4e3fd7439a989b81d9c8cc131267d6221f9585199861b8851f9dd796c` |
| `services/core/src/ksi_core/composition/spatial_data_graph.py` | `4721b6a58710718d7c583a9217582381d180098a8bfe64443637e4285b08c9d0` |
| `services/core/src/ksi_core/domains/sites/observation_work_orders.py` | `5fdf2a958275aed863f80dde777bde35521730fa3224b220240c71d40a7f3ba5` |
| `packages/mission-contracts/src/ksi_mission_contracts/signing.py` | `2c0d6bcdf272b1b8baf55e6fbe023dbd09429d038c9b6fd42d43a54304837085` |

## File structure and ownership

- Neutral bytes: new `packages/domain/src/ksi_domain/signed_payload.py`; old signer re-exports exact helper objects.
- Platform composition: new `services/core/src/ksi_core/composition/{platform_graph,platform_app,platform_assembly,platform_production}.py`; only new profile wiring/lifecycle, no domain journals owned here.
- Shared pure config: new `services/core/src/ksi_core/composition/runtime_config.py` and `services/core/src/ksi_core/foundation/config_values.py`; old paths retain exact re-exports.
- Restricted work routing: existing `services/core/src/ksi_core/domains/sites/observation_work_orders.py`; add opt-in routing mode, not a second WorkOrder model/store.
- Verification: new `tests/contract/test_neutral_signed_payload.py`, `test_platform_core_assembly.py`, `test_platform_core_production.py`, `test_platform_core_http_integration.py`, `tests/replay/test_platform_core_replay.py`.
- Documentation/inventory: existing Core/domain READMEs, `docs/audit/CORE_R1_MODULE_MIGRATION.json`, this task's canonical ledger. Root lock changes only if actual existing workspace edges require them; no dependency versions change.

## Task 1: Exact neutral serialization helpers

**Files:** Create `packages/domain/src/ksi_domain/signed_payload.py`, `tests/contract/test_neutral_signed_payload.py`. Modify `packages/mission-contracts/src/ksi_mission_contracts/signing.py`, Core canonical `domains/artifacts/{artifact_manifest,source_media}.py`, `domains/processing/processing_jobs.py`, `domains/design/report_exports.py`, domain README.

**Interfaces:** `canonical_payload_bytes(contract: Mapping[str, Any]) -> bytes`, `sha256_digest(payload: bytes) -> str`, same as current signer. Legacy signer re-exports the same function objects. No key/sign/verify implementation moves.

- [ ] Capture baseline payload/digest/error vectors and write tests: only top-level `signature` is omitted, nested signature and every other field retained; Unicode/non-ASCII ordering and `sha256:` prefix match literal bytes; NaN/Infinity/lone surrogate/set failures retain exact wrapper/error type; input mapping is unchanged. Assert new neutral import under a deny-hook for mission/acquisition and exact legacy helper identity.

  Named byte oracle `test_signature_removal_is_top_level_only`:
  `assert canonical_payload_bytes({"signature": {"keyId": "ignored"}, "text": "현장", "nested": {"signature": "keep"}}) == '{"nested":{"signature":"keep"},"text":"현장"}'.encode("utf-8")`.
- [ ] Run `.venv/bin/python -m pytest tests/contract/test_neutral_signed_payload.py -q`; missing new module/isolation is intended RED. Owner-independent literal tests may already pass and are controls.
- [ ] Mechanically relocate those two functions into the neutral module using existing `ksi_domain.canonical_json`; replace only consumer imports and legacy definitions with re-exports. Keep all signing/key behavior and existing managed result digests unchanged.
- [ ] Run `.venv/bin/python -m pytest tests/contract/test_neutral_signed_payload.py tests/contract/test_contract_signing.py tests/contract/test_mission_contract_roundtrip.py tests/contract/test_source_media.py tests/contract/test_processing_jobs.py tests/contract/test_report_exports.py -q`; record exact results, Ruff/mypy changed modules. No selection is substituted for later full verification.
- [ ] Review/commit only owned files as `refactor: share exact payload digest helpers outside flight`.

## Task 2: Explicit platform graph and restricted routes

**Files:** Create `composition/{platform_graph,platform_app,platform_assembly}.py`, `tests/contract/test_platform_core_assembly.py`; modify canonical `domains/sites/observation_work_orders.py`, Core module inventory and README. Existing external graph/route helpers are reused; change their implementation only for a demonstrated exact-participant defect, with separate RED and scope record.

**Interfaces:** Add `external_only: bool = False` to `build_observation_work_order_router` (existing `store`, `on_approved` unchanged). New `assemble_platform_app(data_dir: Path, *, journal: Callable[[str], DurableJournal], opened: list[Any], auth_registry: AuthRegistry, human_auth_mode: HumanAuthMode = HumanAuthMode.OPAQUE, oidc_verifier: OidcVerifier | None = None, evidence_storage: EvidenceStorage, external_result_workflow: ExternalResultWorkflowAssemblyConfig | None = None, external_analysis_local_graph: ExternalAnalysisLocalGraphConfig | None = None, analysis_activation: AnalysisActivationV1 | None = None, spatial_data: SpatialDataLocalAssemblyConfig | None = None, expose_docs: bool = False) -> FastAPI`.

Internal interfaces: `build_platform_graph(*, data_dir: Path, journal: Callable[[str], DurableJournal], opened: list[Any], evidence_storage: EvidenceStorage, external_result_workflow: ExternalResultWorkflowAssemblyConfig | None = None, external_analysis_local_graph: ExternalAnalysisLocalGraphConfig | None = None, analysis_activation: AnalysisActivationV1 | None = None, spatial_data: SpatialDataLocalAssemblyConfig | None = None) -> PlatformGraph`; `create_platform_app(*, graph: PlatformGraph, auth_registry: AuthRegistry, human_auth_mode: HumanAuthMode = HumanAuthMode.OPAQUE, oidc_verifier: OidcVerifier | None = None, expose_docs: bool = False) -> FastAPI`.
`PlatformGraph` is a frozen dataclass containing exact `sites: SiteStore`, `work_areas: WorkAreaStore`, `work_orders: ObservationWorkOrderStore`, `roster: OrganizationWorkRosterStore`, `inbox: WorkInboxStore`, `external: ExternalPreWorkOrderGraph`, `workflow: ExternalCompletedGraph`, `analysis: ExternalAnalysisWiring | None`, `data: SpatialDataWiring | None`, `coordinator: ExternalAuthorityCurrentnessCoordinator`, `storage: EvidenceStorage`. Existing participant classes are imported from their canonical owners; no new substitute interfaces or parallel journals.

- [ ] Write tests for boot/route inventory with fresh-process denial of acquisition, Mission/planning, capability/device, Copilot and legacy assembly imports; constructor spies must prove no managed/flight journal is opened. Auth/storage are required, empty policy yields pending inspection/closed quantitative use, incomplete data/Analysis participants raise before protected routes are mounted.
- [ ] Add profile tests: authenticated scoped explicit `EXTERNAL_RECONSTRUCTION` create retains Idempotency-Key behavior; omitted/explicit managed mode is rejected with422`EXTERNAL_RECONSTRUCTION_REQUIRED` after ordinary resource-scope checks, never silently converted. Restricted profile omits managed schedule, approve, execution advance and managed reobservation mutation routes; external administrative operations and approved external-result follow-up remain existing behavior. Cross-tenant/WorkArea requests remain non-disclosing404. Legacy router with default flag preserves all existing tests/defaults.

  Route-selection oracle for the new flag: retain existing scoped WorkOrder list/detail, operations assignment/due-date/close/reopen and historical schedule/draft GETs; omit POST schedule-create, generic WorkOrder `/approve`, generic `/reobservation-drafts` create and `/v1/reobservation-drafts/{draft_id}/approve`. External-result proposal/approval routes remain supplied by `mount_external_routes`, not the generic managed approval callback. Managed rows stay visible as historical records, but operations reject rows which lack existing external-operation binding. `/health`, `/ready`, `/metrics` retain the current bounded unauthenticated meanings; `/capabilities`, device/runtime, managed processing and flight routes are absent. No new public endpoint or inferred compatibility route.
- [ ] Run `.venv/bin/python -m pytest tests/contract/test_platform_core_assembly.py -q`; expect intended missing factory/profile failures.
- [ ] Build only Site/WorkArea/roster/WorkOrder and existing external graphs, exact shared currentness authority and optional explicitly supplied Analysis/data wiring. Keep original journal filenames/callback ordering/locks. Mount existing auth, sites, areas, external APIs, scoped external history and operations; no managed processing, raw source, Mission/flight/Edge, device/capability, Copilot or plan compiler routes. Preserve pending/blocked semantics; no synthetic authority or dummy store for a missing participant.
- [ ] New profile `platform_app` consumes the completed graph and calls existing route builders; no second domain computation or permission implementation. Use existing validation error handler and runtime surfaces with explicit absent legacy state. Keep legacy factory/table/error ordering intact. Verify graph callback identity, state and close/partial-boot cleanup, and register new modules in inventory.
- [ ] Run `.venv/bin/python -m pytest tests/contract/test_platform_core_assembly.py tests/contract/test_observation_work_orders.py tests/contract/test_observation_work_order_operations.py tests/contract/test_external_reconstruction_api.py tests/contract/test_external_result_history.py tests/contract/test_oidc_external_history_scope.py tests/contract/test_core_module_migration.py tests/contract/test_core_app_assembly.py tests/contract/test_external_workflow_common_assembly.py tests/contract/test_api_contract_sync.py -q`. Ruff/mypy current owned modules; review/commit as `feat: assemble explicit external-only platform Core`.

## Task 3: Platform production boot without flight credentials

**Files:** Create `composition/{runtime_config,platform_production}.py`, `foundation/config_values.py`, `tests/contract/test_platform_core_production.py`. Modify existing `composition/{production_config,assembly}.py` for exact helper re-exports only, module inventory/Core README.

**Interfaces:** Move exact `cli_optional_positive(value: int, *, name: str) -> int | None` to neutral foundation. Move pure `_require_env`, `_require_dir`, `_optional_positive_env`, `_human_auth_config_env`, `_parse_principal_tokens`, `_expose_docs_env`, `_external_authority_paths_env`, `_analysis_activation_paths_env` with their constants/type checks to neutral runtime config. Preserve old imports/function identity. Add `build_platform_production_app() -> FastAPI` in `composition.platform_production`.

- [ ] Capture existing pure config/error vectors (no reading live environment/secrets); write tests for malformed/absent auth/storage/data-dir, OIDC subject trust/algorithm/collision, partial signed Analysis configuration and external provider bindings. Validate all required facts before creating S3 clients or opening journals; no default trust, dev tokens or signing bootstrap.
- [ ] Write fresh-process tests denying flight/acquisition/legacy composition and injecting only generated owner-protected config. New boot requires existing data directory, S3 endpoint/bucket and principal digest/OIDC configuration, but neither Mission signing directory nor device-attestation file. Incomplete/expired authority retains current historical-read versus new-use gating, not fail-open activation.
- [ ] Run `.venv/bin/python -m pytest tests/contract/test_platform_core_production.py -q`; expect missing new factory/helpers, not network/credential errors.
- [ ] Extract pure helpers mechanically and wire new production factory to Task2. Reuse existing storage, principal/OIDC verification, explicit external authority and signed Analysis loaders; no new data-production config format (data wiring remains explicit Task2 local injection). Close opened journals on every failure; keep original production factory and Docker/Compose defaults unchanged.
- [ ] Run `.venv/bin/python -m pytest tests/contract/test_platform_core_production.py tests/contract/test_production_assembly.py tests/contract/test_oidc_auth.py tests/contract/test_external_authority_provider_contract.py tests/contract/test_external_result_workflow_config.py tests/contract/test_core_module_migration.py -q`. Verify legacy signatures/errors/defaults unchanged; no environment/credential mutation or actual deployment. Review/commit `feat: add fail-closed platform Core production entrypoint`.

## Task 4: Actual generated flow, history and independent closure

**Files:** Create `tests/contract/test_platform_core_http_integration.py`, `tests/replay/test_platform_core_replay.py`; update Core README and canonical task ledger/ignored checkpoint. No worker algorithm or visual source changes.

**Interfaces:** Use Task2/3 new factory and existing wire/API/MCP/worker interfaces. No new result schema, identity, grant, calculation or producer adapter.

- [ ] Add tests that run existing generated TIFF inspection and fixed Analysis/data worker transport against the new mounted app: scoped Site/WorkArea/external WorkOrder → two sealed derived revisions → actual inspection → existing Analysis result/blocker and region-data receipt → same-area next observation. Freeze returned IDs/digests/extent/limitations and existing hand-oracle pixels/numerical meanings; do not replace actual parser/worker flow with a mock-success store. Existing fixture factories are inputs, not proof the new profile was used.
- [ ] Add restart/replay tests with external V1/V2 reports/reviews/follow-up and retained managed WorkOrder rows: external history remains readable under exact grants; managed rows are not rewritten or made executable. Revoke permission/AI consent/currentness and assert history versus fresh metadata/bytes/new-use distinctions match existing contracts, including tenant-hidden pagination/cursors. Corrupt/unknown journal records still fail closed; never invent a permissive legacy decoder.
- [ ] Run `.venv/bin/python -m pytest tests/contract/test_platform_core_http_integration.py tests/replay/test_platform_core_replay.py -q` against Task2 app and assert its actual factory/route identity. These verification-only tests may already be GREEN; missing factories/profile tests were RED in Tasks2–3. Add bounded negative controls for wrong profile, extra journal open, stale grant and changed input digest to prove the integration assertions reject those cases; do not invent a product defect or a test-only missing hook to manufacture RED. Run affected current API/Analysis/data/MCP and old managed/signature/replay tests; actual app.route/OpenAPI inventory has no flight or managed processing mutation surface. Package/build separation remains P3.
- [ ] Fresh reviewer checks whole P2 diff; independent test-runner executes current scoped/full configured Python suite, Ruff/mypy, offline lock, inventory/disposition gates and available offline artifact closure. Record exact revision/hashes/commands/passed/skipped/warnings and which real flow/outputs were exercised. Existing build/test tools only; no shared environment install, host setup, live credentials or deployment.
- [ ] Commit owned verified integration/docs, reconcile current task state and report P2 technical runtime level with open gates. Do not close whole rebaseline/product acceptance.

## Deferred successor and rollback

P3 still must separate processing-controller managed dependencies/entrypoints, retain active strict historical managed-result readers without flight imports, bind each physical archive move to then-current SHA/content/consumers/contracts/CI/build and inverse move, and validate lock/images/CI. P4 owns actual Console source/brand/states and separate rendered review; this backend plan neither changes nor approves a new visual direction. P5 proves whole RB-01..09 and selects remaining approved first-user gaps, preserving real-data/rights/operations acceptance.

Rollback is an explicit switch back to the retained managed factory plus reviewed inverse task-owned code commits; there is no source move or journal migration. Never run both writers against overlapping journal directories; close the previous app first. Keep exact old state/results/keys protected, do not bootstrap replacements. Runtime switch is operator work requiring its selected target authorization; the local test command is not deployment authority.

## Self-review / approval gate

Requirement mapping: RB-03 runtime part→Tasks1–3 (acquisition-only package dependency closure still P3); RB-04 scoped registration/inspection/data/Analysis/API-MCP semantics→Tasks2–4; RB-05 exact old digests/numerical/history/replay→Tasks1/4; RB-06 restart/idempotency/revocation/tenant guards→Tasks2–4 with unchanged worker cleanup regressions; RB-08/09 module/software/revision evidence→Task4. RB-01 and inventory part of RB-02 consume foundation, not repeated authority changes. Complete managed historical-reader, move-manifest and worker/build/CI closure remains P3; RB-07 changed Console/rendered evidence remains P4. This scope does not close those deferred requirements.
Review Focus1–5 each has explicit negative tests; producer/consumer interfaces and names agree. Source paths/functions above were read at the bound baseline. New filenames are proposed only. Public managed-mode rejection in the new opt-in profile and omitted schedule/flight routes are explicit review decisions, not inferred runtime changes. Preserve the already-selected sequential method; wait for this written-plan review before P2 implementation.
