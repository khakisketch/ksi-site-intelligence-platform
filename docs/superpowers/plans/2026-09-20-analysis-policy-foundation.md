# Analysis Policy Foundation Implementation Plan

**Plan ID:** AP-20260920

**Goal:** Add Core-owned, durable V2 analysis suitability records that derive provisional,
evaluated, remediation-required, or blocked admission from sealed existing evidence, without
publishing a calculation or exposing a new API.

**Architecture:** `ksi_event_contracts.external_relative_volume_analysis` supplies sealed,
canonical calculation identity, per-epoch evaluation, and numeric-free admission contracts.
`ksi_core.domains.external.quantity.external_relative_volume_analysis` resolves real sealed
reconstruction/evidence/inspection/WorkArea facts, records linked immutable evaluation and
admission facts in one journal event, and rechecks local currentness before it returns a current
admission. The legacy V1 request, authority, worker, routes, and launch policy remain untouched.

**Tech stack:** Python 3.12, Pydantic v2, canonical JSON SHA-256 digests, Core JSONL
`DurableJournal`, pytest.

**Spec:** `docs/architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md` D3/D4;
`docs/design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md` headings “Required request scope and
frozen run conditions” and “Outcomes, blockers, and retrieval”; the V1 contracts remain the
compatibility baseline.

## Required implementation record

- **Requirement IDs:** ADR-KSI-037 D3/D4; design calculation profile, accuracy suitability,
  versioning/currentness, and compatibility; INV-017/020/024 (scoped authority, reproducible
  records, no implicit readiness), INV-040 (versioned run context), and INV-051/053/054/055/060
  (external-input and quantitative-claim boundaries).
- **Owner module:** `packages/event-contracts` (immutable contracts) and
  `services/core/src/ksi_core/domains/external/{ingress,quantity}` (durable authority).
- **Acceptance criteria:** An authorized, tenant-scoped caller receives only an immutable,
  numeric-free V2 admission derived from actual sealed inputs. Two independently-attested PASS
  evaluations permit `ADMIT_EVALUATED`; genuinely absent or non-independent measurements permit
  `ADMIT_PROVISIONAL` with explicit reasons; any FAIL or conflicting terminal facts gives
  `REMEDIATION_REQUIRED`; missing/unresolvable essential source/CRS/vertical/units/readiness/
  lineage/coverage facts gives `BLOCKED`; an old admission cannot masquerade as current after a
  relevant withdrawal or new terminal evidence. No arbitrary accuracy threshold or accuracy
  certification is created.
- **Contracts affected:** New additive `external-relative-volume-analysis.v2` schema and Python
  models. Existing `ExternalRelativeVolumeRequestV1` (1–64 evidence digests) and
  `MeasurementLaunchRequestV2` (0 or exactly 2 supplied evidence records) stay unchanged.
- **Reference assets:** Existing Core `ExternalEvidenceStore`,
  `ExternalEvidenceValidationStore`, external reconstruction/inspection stores, WorkArea
  authorities, `ExternalEvidenceMeasurementContextV1`, and their contract/replay tests;
  reference repositories are not adopted.
- **Adoption decisions:** ADOPT the existing validation context's exact criterion bounds and
  independent-attestation outcome; ADOPT actual terminal record projections including `REJECTED`
  records without a measurement payload; ADD one exact-scope projection rather than changing the
  legacy `validated_record_digests_for` or `terminal_records_for_evidence` semantics; do not add
  a second criteria engine or numeric defaults.
- **Files to change:** New event-contract Python/schema files; new Core quantity analysis store;
  narrow ingress validation/inspection currentness projections; the required Core module inventory
  entry; focused contract, real-store, and replay tests; this ledger. No `openapi-core.yaml`,
  composition, worker, V1 volume store, dashboard, facade, MCP, or activation file changes.
- **Tests:** Contract sealing/schema compatibility; status matrix on actual validation records;
  idempotency, isolation, immutable history/currentness, and replay/tamper/torn-tail tests. Run
  through `/home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform/.opencode/artifacts/analysis-policy-20260920/run_worktree.py` only.
- **HIL or real-device assumptions:** None. Tests use existing sealed software fixtures and do not
  claim DSM export, checkpoint collection, vendor compatibility, HIL, field accuracy, or customer
  acceptance.
- **License/data implications:** No external runtime, export, customer bytes, dependency, or
  credential change. Test fixtures remain synthetic.
- **Rollback:** Do not delete or mutate any record. A future authority change can stop wiring a
  new store; its immutable journal remains historical evidence.

## Global constraints

- The fixed V2 profile identity records baseline native grid, current bilinear elevation and
  nearest-mask resampling, cell-centre selection, 100% common coverage, zero threshold, absolute
  affine cell area, `current - baseline` cut/fill/net semantics, and `uncertaintyM3 = null`; this
  foundation records its identity but performs no numeric calculation.
- A calculation identity includes exact input, WorkArea/revision, transforms, profile/config/
  algorithm digests, worker build, runtime image version and OCI digest, and dependency-lock digest.
- Currentness rechecks must happen while the local coordinator guard is held and must not perform
  remote I/O. Historical records retain their historical label and exact evaluation snapshot.
- A known failure or conflict outranks absence. Unresolvable/stale existing context is typed
  blocked/unavailable, never treated as absent evidence. Caller booleans cannot assert readiness;
  only a later worker can verify grid coverage.
- One compound journal event atomically cross-links the new evaluation revision and admission.
  Strict replay rejects missing keys, digest/cross-link/revision/idempotency violations and any
  interior corruption; existing partial-final-line torn-tail recovery is preserved.

---

### AP01: Baseline and contract test boundary

**Files:**
- Create: `packages/event-contracts/src/ksi_event_contracts/external_relative_volume_analysis.py`
- Create: `contracts/schemas/external-relative-volume-analysis.v2.json`
- Create: `tests/contract/test_external_relative_volume_analysis_contract.py`

**Produces:** Sealed `AnalysisPolicyV2`, `CalculationIdentityV2`, `EvaluationV1`, and
`AdmissionV2` models with canonical SHA-256 payloads and strict UTC/identifier/digest validation.
Their identity contains the required V2 profile/runtime provenance; an evaluation binds one epoch's
exact context, criterion, attestation, terminal record digests, and verdict. The admission binds
the calculation digest plus all evaluation revisions consulted and has no calculated volume fields.

- [x] Write focused failing contract tests for a valid canonical identity, invalid runtime/digest
  input, tampered calculated digest, and numeric data rejected from an admission.
- [x] Run the focused test and observe failure because the V2 contract module is absent.
- [x] Implement only immutable model validation, canonical payload/digest sealing, and schema
  parity needed by those tests.
- [x] Re-run focused contract/schema validation: RED `ModuleNotFoundError`; final GREEN
  `tests/contract/test_external_relative_volume_analysis_contract.py` (3 passed).

### AP02: Actual-store analysis suitability foundation

**Files:**
- Modify: `services/core/src/ksi_core/domains/external/ingress/external_evidence_validations.py`
- Create: `services/core/src/ksi_core/domains/external/quantity/external_relative_volume_analysis.py`
- Modify: `services/core/src/ksi_core/domains/external/ingress/external_artifact_inspections.py`
- Modify: `docs/audit/CORE_R1_MODULE_MIGRATION.json`
- Modify: `tests/contract/test_external_quantitative_production_flow.py`

**Consumes:** `ExternalEvidenceStore` sealed item/manifest snapshots;
`ExternalEvidenceValidationStore` exact-scope terminal records and local-current guard;
`ExternalEvidenceMeasurementContextV1` criterion bounds and attestation; actual reconstruction,
inspection, and WorkArea authority ports.

**Produces:** `ExternalRelativeVolumeAnalysisStore.assess_and_record(principal, request, now)` and
tenant-scoped current/historical retrieval. A returned current admission is derived only while
real dependencies are locally current; history returns a historical record and never grants current
suitability.

- [x] Write failing real-store integration tests for two independently-attested PASS records,
  absent/non-independent records, `REJECTED` without a payload, a PASS+FAIL conflict, and an
  essential-fact block. Each test must name the incorrect classification it prevents and assert
  resulting disposition/reasons, evaluation bindings, and absence of numeric output.
- [x] Run these tests and observe failure because the narrow exact-scope projection and analysis
  store do not exist.
- [x] Add an internal exact-scope terminal projection that includes every actual terminal record
  for the matched sealed subject/evidence/DSM/context, including payload-less rejections, without
  altering existing legacy projections.
- [x] Implement minimal dependency-resolution, all-facts adjudication, compound journal event,
  per-calculation evaluation revisions, idempotent retry, principal organization plus site-action
  permission scope, and guarded
  local-current recheck. Preserve `REMEDIATION_REQUIRED` priority over otherwise absent evidence;
  turn unresolvable/stale essential contexts into `BLOCKED` with typed reasons.
- [x] Extend the same real-store tests for cross-tenant non-disclosure, context withdrawal/revocation
  between initial resolution and guarded return, and adding a later terminal fact: the former
  admission stays immutable history and current lookup reclassifies/rejects it.
- [x] Run focused Core tests through the isolated launcher: 25 passed (one existing
  Starlette/httpx deprecation warning); Core boundary checker and migration tests: 47 passed.

### AP03: Replay, independent review, and integrated validation

**Files:**
- Modify: the AP02 test files only as needed for replay fixture helpers.

**Produces:** Strict replay evidence that a rehashed journal cannot substitute an evaluation,
admission, revision sequence, cross-link, idempotency fingerprint, or terminal record. A truncated
final record is treated using existing torn-tail recovery rules; any non-tail corruption fails.

- [x] Write failing replay tests for a substituted/rehashed evaluation digest, mismatched admission
  evaluation revision, duplicate idempotency key with a changed request, and torn-tail recovery.
- [x] Run those replay tests and observe the missing/rejected replay invariants.
- [x] Implement the smallest strict event validation and deterministic replay logic that satisfies
  the tests.
- [x] Run focused contract/Core/replay tests and the authorized baseline through the isolated
  launcher. The eight baseline paths now report 135 passed because this packet adds two tests;
  no full suite was run.
- [x] Freeze for independent review after final `git status`, `git diff --check`, targeted static
  checks, core-boundary validation, and changed-file SHA-256 capture. No commit, push, merge, or
  activation occurred.

## Independent-review correction record

- [x] Validate a compound event against the locked replay projection before append; allocate or
  reuse evaluation revisions only under that same final lock. Regression covers a reused request
  ID with a distinct idempotency key, restart, and simultaneous preflights at distinct assessment
  times.
- [x] Snapshot issued, leased, terminal, and unresolvable matching checkpoint lifecycle state.
  Pending or context-unavailable evidence is `UNAVAILABLE`/`BLOCKED`; only a genuinely empty
  matching scope is provisional.
- [x] Restrict north-up/no-shear affine enforcement to the baseline and preserve the current
  affine for future bilinear/nearest resampling.
- [x] Bind both DSM artifact IDs, sealed epoch subjects, selected WorkArea snapshot, per-epoch
  observed CRS, vertical reference, unit, affine, and their canonical digests in the identity.
- [x] Define the JSON Schema as sealed wire records: canonical digests are required and timestamp
  wire values use UTC `Z` or `+00:00`; contract tests cover missing digests and non-UTC offsets.
- [x] Preserve per-fact local currentness: a current rejected terminal fact remains
  `REMEDIATION_REQUIRED` when another fact is pending or unavailable, while withdrawal of that
  rejected fact itself remains `UNAVAILABLE`/`BLOCKED`.
- [x] Derive each vertical unit from the parser-observed exact vertical EPSG CRS axis using local
  `pyproj`; accept only a single metre axis with matching observed basis and record its
  `OBSERVED_VERTICAL_CRS_AXIS` provenance. Free-text, nonvertical, ambiguous, and foot axes block.

## Plan self-review

- ADR-037's V2 profile/provenance and immutable calculation/evaluation/currentness boundaries map
  to AP01 and AP02; numeric execution, API/MCP/UI, and activation are explicitly out of scope.
- The design's failure-over-absence, missing-essential blocker, additive compatibility, and
  currentness-before-publication rules map to AP02/AP03.
- No unapproved threshold, RMSE-derived volume uncertainty, or accuracy certification appears.
- No placeholder implementation step remains; implementation work is test-first and preserves
  existing journal evidence.

## Local integration milestone — 2026-09-20

AP01–AP03 implementation is locally complete for this bounded foundation; the product slice
and its customer acceptance remain open and unchanged.

- Independent final review: PASS, no findings, frozen v3 source (10 owned paths).
- Independent verification: 328 tests passed; targeted Ruff/mypy, 143-record Core boundary
  inventory, and diff checks passed. One existing Starlette/httpx deprecation warning remains.
- Lead applied only the 10 reviewed paths into the main working checkout at
  `9edc4a18e873e356f5cfea7d69437f1fb5e11acd`; 2,082 other baseline files remained byte-identical,
  including prior document work and foreign Dashboard/A2H WIP.
- Integrated verification: nine analysis/compatibility paths, 140 tests passed; imports asserted
  from the main checkout; Core boundary and `git diff --check` passed.
- Evidence directory: `.opencode/artifacts/analysis-policy-20260920/` contains
  `review-freeze-v3.json`, `review-result-v3.md`, `verification-v3.md`, `application-v3.json`,
  and `integrated-pytest.txt`. These are local ignored artifacts, not remote CI evidence.
- This factual milestone appendix is the only post-review ledger addition; runtime, contracts,
  schema and tests remain byte-identical to the reviewed v3 freeze.
- No numeric worker, public route, Analysis facade, UI/MCP connection or production activation
  is supplied by this packet. No commit, push, deployment, device/HIL or customer acceptance.
- Next implementation boundary: fixed-profile numeric worker and result contract, then the
  shared Analysis request/status/result path and Codex integration; reuse this Core policy.
  A worker must still verify actual common grid coverage before publishing any numbers.
