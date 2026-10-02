# Analysis Calculation Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This packet has one assigned source writer; independent review happens after the writer is idle.

**Plan ID:** NX-20260921

**Goal:** Produce one durable, reconstructible, fixed-profile relative-volume calculation from two sealed external DSM GeoTIFF artifacts, while preserving the separate evidence-suitability history and without mounting a product API.

**Architecture:** The existing AP suitability store continues to establish the immutable `CalculationIdentityV2` and records evidence evaluations separately. New V2 contracts seal an execution authorization/attempt snapshot and a numeric result with full-zone coverage evidence. A new unmounted Processing callable verifies the exact bytes and bounded GeoTIFF structure, runs the approved baseline-native/bilinear/nearest/cell-centre calculation using the reusable GIS primitives, and returns only a sealed report or a typed failure. A separate Core execution journal owns issue, lease, renewal, report/failure, history and current projection; it never borrows V1 worker policy or mounts V1 routes.

**Tech Stack:** Python 3.12, Pydantic v2, canonical JSON SHA-256, Rasterio/GDAL, NumPy, PyProj, Core `DurableJournal`, pytest.

**Spec:** `docs/architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md` D3/D4; `docs/design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md` sections “Required request scope and frozen run conditions”, “Calculation profile”, “Outcomes, blockers, and retrieval”; `docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md`; AP-20260920 ledger.

## Required implementation record

- **Requirement IDs:** ADR-KSI-036 D1–D4/D6; ADR-KSI-037 D3/D4; first-request design calculation-profile, execution/resource, result/evidence, versioning/currentness and retrieval requirements; INV-017/020/024/040/051/053/054/055/060.
- **Owner module:** immutable wire contracts in `packages/event-contracts`; raster math in import-only `packages/change-detection`; bounded callable in `services/processing-controller`; durable authorization/job/result state in `services/core/src/ksi_core/domains/external/quantity`.
- **Acceptance criteria:** an authorized Core caller can issue a numeric execution only from a current AP admission with `ADMIT_PROVISIONAL` or `ADMIT_EVALUATED`; an internal worker with a current fence can consume actual sealed GeoTIFF bytes and produce the hand-checked cut/fill/net result plus an exact bounded reconstructible selected/common/unavailable/threshold mask record, counts, areas and bounds. The result binds input bytes/size/observed CRS/vertical references/affines, `CalculationIdentityV2`, sealed execution snapshot, policy and the exact admission/evaluation records consulted at launch. Its `numericResultIdentityDigest` seals numeric inputs/profile/metrics/witness independently of the report, attempt and admission envelopes, so later evidence only adds a consulted-evaluation relation without changing the calculation. Nonfinite values, byte/resource excess, stale lease, altered bytes, incomplete coverage, corruption and tampered journal records fail closed. A later evidence change suppresses ordinary current numeric publication until an AP reassessment is recorded; it neither recomputes nor rewrites the original numeric record.
- **Contracts affected:** add `external-relative-volume-calculation.v2.json` and `ksi_event_contracts.external_relative_volume_calculation`; retain existing V1 relative-volume request/launch/result contracts without schema or behavior changes. AP V2 identity/evaluation/admission schemas remain byte-compatible; the new calculation result refers to their sealed digests rather than extending their historical event shapes.
- **Reference assets:** `external_relative_volume_analysis.py` AP contracts/store; `dsm_diff.py` alignment primitive; `external_volume.py` full-zone/cell-centre coverage primitive; Processing `external_measurement_algorithms.py` byte, TIFF, memory and watchdog primitives; Core processing-job lease patterns. `references/` is not imported.
- **Adoption decisions:** reuse the existing GeoTIFF parser/inspection grammar and resource-envelope checks as callable primitives, not the V1 launch/daemon/container protocol. Reuse baseline-native affine, current bilinear elevation, nearest validity-mask and full-zone cell-centre rasterization semantics. `thresholdM = 0.0`, `minimumCommonValidFraction = 1.0`, `uncertaintyM3 = null`; no caller-selected calculation knob, auto-registration, accuracy threshold, RMSE-derived uncertainty or settlement claim. Use a separate sealed `AnalysisExecutionAuthorizationV2`/attempt snapshot with resource envelope digest and finite limits; resource changes do not alter `CalculationIdentityV2`, but the producing execution snapshot is immutable in a report.
- **Files to change:** new event-contract Python/schema files; a narrow public callable/result module under Processing; new Core execution store; narrow AP lookup/currentness seam only; Core module inventory; focused contract, worker and real-store/replay tests; this ledger. No V1 protocol/daemon/client/container/manifest/composition/routes/OpenAPI/dashboard/MCP/runtime deployment changes.
- **Tests:** test-first contract sealing and schema parity; real GeoTIFF integration with byte hashes/sizes/CRS/vertical references/affines; hand-derived 2×2 and unavailable-cell masks; resource, stale-fence, duplicate, tenant, restart, tamper and late-evidence replay cases. All commands use `/home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform/.opencode/artifacts/analysis-execution-20260921/run_worktree.py` with the main `.venv`; do not install or alter environments.
- **HIL or real-device assumptions:** none. Synthetic GeoTIFF bytes exercise software behavior only; no DJI Terra export support, RTK/GCP/absolute accuracy, HIL, field, settlement or customer acceptance is asserted.
- **License/data implications:** no external service, customer artifact, credential or vendor SDK is added. Rasterio/GDAL, NumPy, PyProj and project-owned existing source are already locked dependencies. Fixtures are synthetic.
- **Rollback:** do not rewrite/delete computation or journal evidence. A later policy decision can stop constructing the unmounted store/callable; immutable records remain historical and ordinary retrieval remains fail-closed.

## Global constraints

- The fixed profile is exact: baseline native north-up affine; current elevation `BILINEAR`; current validity mask `NEAREST`; WorkArea cell-centre selection; selected-zone common coverage denominator 100%; threshold 0.0 m; cell area `abs(a*e-b*d)`; `delta=current-baseline`; `cut=-sum(delta<0)*area`; `fill=sum(delta>0)*area`; `net=fill-cut`; `uncertaintyM3=null`.
- Before TIFF parse/allocation, verify finite resource limits and observed byte size/hash through owned immutable descriptors; never hash a mutable pathname then reopen it. Before worker publication, verify every numeric result is finite and every mask/count/area/bounds relation is exact.
- The coverage witness contains a bounded, lossless binary representation (row-major bitset plus dimensions, baseline affine and selected-window origin) of selected, common-valid, unavailable and threshold-excluded cells, with its own digest; hashes alone are insufficient. A full 100% profile has `unavailable = 0`; with the fixed 0.0 m threshold, `thresholdExcluded = 0` even when exact-zero deltas contribute to neither cut nor fill.
- Core’s local currentness guard performs no remote I/O and does not invent a `Principal`. AP suitability is indexed by `calculationIdentityDigest`; normal execution/retrieval uses the latest locally-current admission. If evidence has changed but no newer durable AP assessment exists, return `REASSESSMENT_REQUIRED`, not the former number.
- A new execution attempt is fenced by worker identity, acquisition ID, generation and expiry. Report/failure/retrieval validate the current fence and all cross-links before append; all journal records are fully semantic-validated before append and during replay. A stale worker cannot publish. Duplicate issue of the same calculation identity reuses one job even when its evaluation evidence later changes.
- Later evidence failure or withdrawal preserves the historical numerical result and both original/consulted evaluation records with labels, but ordinary current result lookup suppresses numbers. A newly assessed compatible admission may be linked to the same numerical computation without recalculating DSM pixels.
- No commit, push, merge, deployment, credentials, device action or native goal is part of this plan.

---

### NX01: V2 numeric contracts and fixed-profile worker callable

**Files:**
- Create: `packages/event-contracts/src/ksi_event_contracts/external_relative_volume_calculation.py`
- Create: `contracts/schemas/external-relative-volume-calculation.v2.json`
- Create: `services/processing-controller/src/ksi_processing_controller/external_analysis_measurement.py`
- Modify: `packages/change-detection/src/ksi_change_detection/external_volume.py` only if an existing internal return shape cannot expose exact masks without changing V1 behavior
- Create: `tests/contract/test_external_relative_volume_calculation_contract.py`
- Create: `tests/contract/test_external_analysis_measurement.py`

**Interfaces:**
- Consumes: sealed `CalculationIdentityV2`, `AdmissionV2`, existing `ResourceEnvelopeV1`, and actual primary/secondary GeoTIFF byte sources.
- Produces: `AnalysisExecutionAuthorizationV2.sealed()`, `AnalysisExecutionAttemptV2.sealed()`, `RelativeVolumeCoverageWitnessV2`, `RelativeVolumeCalculationReportV2.sealed()`, `RelativeVolumeCalculationFailureV2.sealed()`, and `measure_external_relative_volume_v2(...) -> RelativeVolumeCalculationReportV2 | RelativeVolumeCalculationFailureV2`.

- [ ] **Step 1: Write failing contract tests.** Name the break: changing a number without resealing, substituting an execution resource snapshot, omitting a lossless coverage mask, permitting a nonfinite metric, or binding a result to a different AP admission must be rejected. Use a hand-written valid payload with a 2×2 witness:

  ```python
  witness = RelativeVolumeCoverageWitnessV2(
      rows=2, columns=2, row_offset=0, column_offset=0,
      selected_mask_b64="8A==", common_valid_mask_b64="8A==",
      unavailable_mask_b64="AA==", threshold_excluded_mask_b64="AA==",
      selected_cell_count=4, common_valid_cell_count=4,
      unavailable_cell_count=0, threshold_excluded_cell_count=0,
      selected_area_m2=4.0, common_valid_area_m2=4.0,
      bounds=(200000.0, 549998.0, 200002.0, 550000.0),
  ).sealed()
  assert report.metrics.fill_m3 == 4.0
  ```

- [ ] **Step 2: Run the focused contract test and observe RED.**

  Run: `PYTHONDONTWRITEBYTECODE=1 /home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform/.venv/bin/python /home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform/.opencode/artifacts/analysis-execution-20260921/run_worktree.py pytest -p no:cacheprovider -q tests/contract/test_external_relative_volume_calculation_contract.py`

  Expected: import failure for `external_relative_volume_calculation`; record the actual failure in this ledger.

- [ ] **Step 3: Implement immutable contract models and schema parity.** Define strict finite `StrictFloat`/count/area/bitset validators, canonical digests, UTC timestamps, resource envelope digest binding, CalculationIdentity/AP admission/evaluation cross-links, worker fence tuple, and report/failure exclusivity. Encode masks as canonical base64 big-endian row-major bitsets with exactly `ceil(rows*columns/8)` bytes and zero padding bits; recompute their digest and counts from bytes. Seal `numericResultIdentityDigest` from numeric inputs/profile/metrics/witness only; keep it separate from the report digest and all attempt/admission/evaluation envelopes. `AnalysisExecutionAuthorizationV2` freezes the Core-selected resource envelope and launch/runtime authority; `AnalysisExecutionAttemptV2` binds exactly one authorization plus fence. Do not import Rasterio or Core into the contracts package.

- [ ] **Step 4: Re-run the focused contract test and observe GREEN.**

  Run the Step 2 command. Expected: PASS; a changed metric/digest/mask/resource/admission test is rejected by real Pydantic model validation.

- [ ] **Step 5: Write failing worker integration tests with real GeoTIFF bytes.** Name the breaks: swapping current bytes, treating missing data as zero, using a nonzero threshold, accepting a partial zone, or using the wrong difference sign must fail or produce the wrong expected behavior. Create 2×2 `EPSG:5186` GeoTIFFs with a compound vertical CRS whose parser-observed reference is `EPSG:5773`/`EGM96 height`; baseline 100 m and current `[101, 99; 100, 100]` produces fill=1, cut=1, net=0, selected/common=4. A current NoData cell yields typed `INSUFFICIENT_COMMON_VALID_COVERAGE` and no report.

- [ ] **Step 6: Run focused worker test and observe RED.**

  Run: launcher command from Step 2 with `tests/contract/test_external_analysis_measurement.py`.

  Expected: import failure for the callable; record the actual failure in this ledger.

- [ ] **Step 7: Implement the minimal unmounted worker callable.** Snapshot both trusted byte sources to owned anonymous descriptors before hashing/parsing; use only the resulting `/proc/self/fd` paths so hash/parse/report share the same immutable bytes. Reuse `verify_owned_secondary_fd`, preflight TIFF/memory checks, parser/inspection facts, watchdog and the existing alignment implementation. Verify both byte digests/sizes and exact observed CRS/vertical/affine facts match the sealed identity before pixel allocation. Calculate full baseline grid using the fixed policy only; derive masks before metrics, reject zone coverage below 1.0, and emit no uncertainty. Serialize a bounded witness and sealed report; map expected validation/resource/cancellation faults to sealed typed failure, never a partial numeric result.

- [ ] **Step 8: Re-run worker and package regression tests and observe GREEN.**

  Run launcher command with `tests/contract/test_external_analysis_measurement.py packages/change-detection/tests/test_external_volume.py packages/change-detection/tests/test_dsm_diff_worker.py`.

  Expected: all pass; report the count and any pre-existing warning.

### NX02: Durable Core execution, attempt fencing and AP currentness witness

**Files:**
- Create: `services/core/src/ksi_core/domains/external/quantity/external_relative_volume_calculations.py`
- Modify: `services/core/src/ksi_core/domains/external/quantity/external_relative_volume_analysis.py`
- Modify: `docs/audit/CORE_R1_MODULE_MIGRATION.json`
- Modify: `tests/contract/test_external_quantitative_production_flow.py`
- Create: `tests/contract/test_external_relative_volume_calculations_contract.py`

**Interfaces:**
- Consumes: `ExternalRelativeVolumeAnalysisStore`, sealed V2 calculation contracts, `DurableJournal`, `ExternalAuthorityCurrentnessCoordinator`, and real Core evidence/reconstruction/inspection/WorkArea stores.
- Produces: `ExternalRelativeVolumeCalculationStore.issue(...)`, `.acquire_lease(...)`, `.renew_lease(...)`, `.input_for_worker(...)`, `.record_report(...)`, `.record_failure(...)`, `.get_history_for_principal(...)`, and `.get_current_for_principal(...)`.

- [ ] **Step 1: Write failing real-store tests.** Name the breaks: a worker using another organization’s identity, a stale/acquisition-mismatched fence, an idempotent duplicate, a report linked to an unconsulted admission, or a completed result returned after evidence changes must not publish normal numbers. Exercise two real AP assessments for one identity: issue and complete once; record a new AP evaluation without numerical re-execution; retrieve the same numerical report with its original and newer consulted-evaluation references. Then create a rejection/withdrawal and assert history remains immutable while `get_current_for_principal` returns `REASSESSMENT_REQUIRED`/suppressed numeric output.

- [ ] **Step 2: Run Core focused tests and observe RED.**

  Run launcher command with `tests/contract/test_external_relative_volume_calculations_contract.py tests/contract/test_external_quantitative_production_flow.py`.

  Expected: import failure for `external_relative_volume_calculations`; record the actual failure in this ledger.

- [ ] **Step 3: Add the narrow AP lookup/currentness seam.** Add an internal method returning the latest durable assessment matching `calculationIdentityDigest`, its exact request/evaluations, and a guarded currentness witness; it must inspect local stores only while guarded, never synthesize a Principal, query remote resources or silently reclassify evidence. Return typed `REASSESSMENT_REQUIRED` when no latest record survives the witness.

- [ ] **Step 4: Implement the Core execution journal/store.** Under one store lock and shared coordinator, validate principal organization and required site action; authorize only current `ADMIT_PROVISIONAL`/`ADMIT_EVALUATED` AP records; build a sealed Core-selected authorization/attempt resource envelope; assign monotonically fenced leases; append only replay-equivalent validated events. Store report/failure immutable history keyed by calculation identity and request idempotency. A report may be recorded after AP change only with its original launch evidence, but current retrieval runs the AP witness and suppresses the ordinary numeric view if a newer/rejected/unavailable condition exists. Link a later compatible durable AP revision to the prior report as `consultedAfterCompletion`, never invoke the worker again.

- [ ] **Step 5: Re-run focused Core tests and observe GREEN.**

  Run Step 2 command. Expected: PASS, with local real-store behavior proving permission, lease and evidence-currentness enforcement.

### NX03: Replay/integration proof and packet validation

**Files:**
- Modify: `tests/contract/test_external_quantitative_production_flow.py` only for replay helpers required by NX02.
- Modify: `docs/superpowers/plans/2026-09-21-analysis-calculation-execution.md` with actual RED/GREEN commands, results, review freeze and validation evidence.

**Interfaces:**
- Consumes: NX01 report/failure serialization and NX02 journal events.
- Produces: replay-safe history/current projections and a frozen reviewable packet.

- [ ] **Step 1: Write failing replay/race tests.** Name the breaks: modified/rehashed report metrics, changed mask digest/count, replaced execution authorization/envelope, duplicate event request with changed identity, stale lease publication, interior journal tampering, and a torn final record. Use a barrier around issue/lease or report only where real store locking needs concurrency; assert actual durable state, not mocked calls.

- [ ] **Step 2: Run replay tests and observe RED.**

  Run launcher command with the focused NX01/NX02 test files and `tests/replay/test_external_quantitative_authority_replay.py`.

  Expected: one or more missing replay/fence rules fail; record the exact RED behavior.

- [ ] **Step 3: Implement only missing strict replay and fence validation.** Validate exact event keys, event digest, report/failure digest, authorization/attempt/identity/admission/evaluation cross-links, revision/idempotency/lease progression and tenant constraints during dry-run and stateful replay. Preserve existing final-line torn-tail behavior; reject any complete interior corruption.

- [ ] **Step 4: Re-run focused integration tests and observe GREEN.**

  Run launcher command with all NX contract/worker/Core tests, AP contract tests, existing external volume package tests, and `tests/replay/test_external_quantitative_authority_replay.py`. Expected: all pass.

- [ ] **Step 5: Run static/boundary checks and prepare independent-review freeze.**

  Run `git diff --check`; Ruff on every owned Python path; mypy on new/modified source modules through the launcher; `python3 tools/check_core_module_boundaries.py`; and the agreed focused baseline. Capture exact source status, changed-file hashes, patch digest, commands and results under `.opencode/artifacts/analysis-execution-20260921/`. Do not commit or run deployment/device/full-suite checks.

## Plan self-review

- Fixed numeric semantics, full-zone coverage, reconstructible mask evidence and no-uncertainty rule map to NX01.
- Separate numeric identity/evidence-evaluation history, resource/attempt snapshot, local currentness witness, lease fencing and late-evidence behavior map to NX02.
- Byte/resource validation, deterministic replay, race, tamper and torn-tail cases map to NX01/NX03.
- No V1 worker lifecycle/public composition/API/MCP, custom reconstruction, vendor API, accuracy certification or product-slice transition appears in the plan.
- The AP V2 journal format is not rewritten; new records reference its sealed canonical identities. All later task signatures match objects introduced in NX01.

## Execution authorization

The Human authorized “다음 진행” after the approved product direction and first Core foundation. The Lead assigned this bounded packet and will approve this ledger before implementation. Execution remains isolated to this worktree, uses test-first steps, and stops before any external side effect.

## Execution evidence — 2026-09-21

**NX01 RED/GREEN.** Contract RED was `ModuleNotFoundError` for
`ksi_event_contracts.external_relative_volume_calculation`; schema parity then
RED for the absent schema. The new contract test passed **5** cases after the
models/schema were added. Worker RED was the absent
`ksi_processing_controller.external_analysis_measurement` callable. The real
GeoTIFF worker then passed **9** cases, including 2×2 hand arithmetic,
canonical `8A==` masks, byte substitution, NoData/nonfinite refusal,
CRS/vertical/affine mismatches, a rotated current grid, full outside-zone
denominator, combined snapshots/workspace, V2 zone-memory, geometry vertices
before rasterization, and report-output ceilings. A six-vertex WorkArea under
a cap of five deliberately RED-produced a report before the vertex guard; it
is GREEN after the pre-rasterization cap.

**NX02/NX03 RED/GREEN.** The initial Core import and `record_report` paths
were absent and RED. The connected real-store test uses one AP-derived
identity, a Core-issued/renewed fenced attempt, actual in-memory GeoTIFF bytes
written to local files, and the exact worker report/failure. It verifies stale
publication/input refusal, lease renewal, tenant concurrency, queue depth,
retry/deadline ceilings, principal-scoped history, current/historical split,
and journal replay. A deterministic two-thread barrier RED exposed final-lock
duplicate issue failure; the final lock now returns the existing identity.
Review audit additionally found that a reassessment-required view exposed its
old report through `view.record`; status projection now strips the nested
numeric report while explicit history retains it. A resealed, rehashed shorter
lease event is rejected during replay; issue, lease, renewal, report, failure,
and consulted-admission cross-links now validate only locally derivable
historical facts.

**Focused validation (all through the source-pinning launcher unless noted):**

- `pytest -p no:cacheprovider -q tests/contract/test_external_relative_volume_calculation_contract.py tests/contract/test_external_analysis_measurement.py tests/contract/test_external_analysis_execution_integration.py tests/contract/test_external_relative_volume_analysis_contract.py tests/contract/test_external_quantitative_production_flow.py::test_analysis_policy_assessment_uses_real_sealed_core_stores packages/change-detection/tests/test_external_volume.py packages/change-detection/tests/test_dsm_diff_worker.py` — **60 passed**, one pre-existing Starlette/httpx deprecation warning.
- `ruff check` over all six owned source modules and four owned/modified focused tests — **passed**.
- launcher `mypy` over the six owned source modules — **Success: no issues found in 6 source files**.

**Scope/review notes.** The plan's proposed standalone
`test_external_relative_volume_calculations_contract.py` and
`tests/replay/test_external_quantitative_authority_replay.py` were not added:
their real Core/replay assertions are concentrated in
`test_external_analysis_execution_integration.py` and the existing real-store
`test_analysis_policy_assessment_uses_real_sealed_core_stores` test. The
21-line change to `external_measurement_algorithms.py` is the conservative
fixed-profile zone-memory preflight shared by the unmounted V2 worker; the
existing V1 DSM diff worker regression is in the 60-pass focused command.
Synthetic GeoTIFF fixtures demonstrate local software behavior only. No Terra
export, RTK/GCP, absolute accuracy, OS/container enforcement, deployment,
route/MCP activation, commit, or external action was performed.

**Review freeze.** Candidate source state is frozen as
`/home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform/.opencode/artifacts/analysis-execution-20260921/review-freeze-v2.json`
with patch SHA-256 recorded there; the freeze script verified the protected
main baseline's **2092** files remained unchanged. Independent review remains
required before any integration claim.

## Correction round 1 — review v2 findings

**Scope and invariants.** This correction remains within the same 13-path NX
packet.  It enforces INV-EXT-ANALYSIS provenance and currentness at the Core
append/replay boundary, preserves V1 and AP identity journals, and adds no
public route, MCP, daemon, reconstruction, or deployment behavior.

**RED evidence.** The real Core/AP store test first submitted a fully resealed
report whose calculation identity and worker fence were correct but whose
numeric `profileDigest` was different from the immutable admitted profile.
Before the correction it was accepted by `record_report` (**1 failed, 7
passed** in the contract-plus-connected test command).  The initial
base64-alias test likewise showed that `8B==` was accepted after the stale
witness digest was cleared.  Duplicate issue regression coverage uses the
same completed record after both a remediation-required evaluation and a
withdrawn/unavailable context; original and new idempotency keys returned the
old report before the I1 status projection.

**Implemented correction.** Every `issue` return path remains a nonnumeric
status projection.  Core now requires a non-null canonical report/failure
seal, and uses one local predicate during both live append and journal replay
to bind a report to the admitted calculation's sealed profile, native north-up
baseline affine determinant, coverage-window bounds and nonnegative offsets,
plus its Core-selected `maxPixels` and serialized `maxOutputBytes` envelope.
It does not reopen pixels or recalculate numerical output.  The contract mask
decoder now rejects noncanonical base64 re-encodings; coverage/numeric nested
`contractVersion` fields are `Literal` values matching the JSON schema.

**GREEN evidence.**

- The source-pinned contract test passed **7** cases after clearing unrelated
  digest fields in the nested-version fixtures.
- The connected Core/AP test passed after exercising wrong profile, wrong
  cell-area, wrong affine-derived bounds, `maxPixels`, unsealed report,
  unsealed failure, currentness suppression, and an independently resealed
  and rehashed wrong-profile report event rejected during restart replay.
- The focused packet command from the NX03 section passed **62** cases in
  **2.96s**, with only the pre-existing Starlette/httpx deprecation warning.
- Ruff over every owned Python path and `git diff --check` passed.  The
  source-pinned mypy command over the six owned source modules reported
  `Success: no issues found in 6 source files`; Core boundaries reported
  `Core R1 module boundaries OK: 144 inventory records`.

**Freeze/rollback.** The v3 freeze is generated only after this ledger edit by
the existing protected-baseline script.  It records the exact changed paths
and patch digest for independent re-review.  Rollback remains additive:
disable construction of the unmounted callable/store in a later authorized
change without rewriting durable historical calculations or AP records.

## Correction round 2 — v3 affine-window review regression

**RED evidence.** The existing connected worker→Core test was changed to
write actual 0.1 m compound-CRS GeoTIFF bytes.  Its WorkArea extends 0.01 m
over the top-left raster edge, leaving only unselected padding outside the
grid.  The worker produced a valid full-selected-cell report with
`rowOffset=-1`, `columnOffset=-1`, and selected mask `BmA=`; prior Core logic
returned `None` from `record_report` (**1 failed**, existing Starlette/httpx
warning).  That failure exposed both the unsupported negative-offset guard
and the regrouped affine arithmetic.

**Implemented correction.** The Core predicate no longer rejects negative
window offsets.  It now reproduces the producer's north-up operation order:
first compose the local origin as `Affine.translation` does, then derive
`array_bounds` edges from that local affine.  Equality remains exact; no
epsilon or relaxed geometry comparison was added.  The Core import boundary
remains unchanged: the scalar operation is equivalent to the producer's
already accepted Rasterio operation, while Core still performs no raster I/O.

**Positive crop proof.** The same real integration flow registers a second
work area whose selected cells begin at positive row/column offset 1.  The
actual worker reports a right bound of `200000.30000000002`, explicitly not
`200000.3`; Core persists the report and a fresh store replays it unchanged.
The first top-left case independently proves that unselected outside-grid
padding does not reduce the fixed profile's selected-cell coverage.

**GREEN evidence.** The affected connected integration test passed after the
minimal Core change.  The focused packet matrix passed **62** cases in
**2.87s** with only the pre-existing Starlette/httpx warning.  Ruff and
`git diff --check` passed; source-pinned mypy again reported no issues in six
source modules, and Core boundaries reported 144 inventory records.  The
existing wrong-bounds negative regression remains in the real Core/AP test.


## Lead integration milestone — 2026-09-21

**Local packet status: implemented, independently reviewed, and applied to main WIP.**
The original plan checkboxes above describe the planned sequence; the execution and
review records below/above establish actual completion, substitutions and limits.
They do not mark the EXT-VAL product slice or user acceptance complete.

- Frozen v4: `review-freeze-v4.json`, patch SHA-256
  `6e86eaebd5457842a927db29f77c48a575baa50c4259680218c4225825794172`.
- Independent task review and integration review: **PASS** (`task-review-v4.md`,
  `review-result-v4.md`). Original suppression/sealing/profile findings and the
  subsequent fractional-grid/padding regression are closed.
- Independent validation: initial compatibility matrix **390 passed**; final affected
  matrix **64 passed**; Ruff, mypy (6 source modules), source boundary check (144
  records), and diff check passed. One existing Starlette/httpx warning remains.
- Lead applied exactly the 13 frozen paths after checking before/after hashes and
  the protected 2,092-file main baseline. Unrelated WIP was preserved. Application
  evidence: `application-v4.json`.
- Main-origin launcher then ran the same seven affected test files: **64 passed**,
  one existing warning, 4.76 seconds. All four module origins resolved to main.
  Main boundary check (144 records) and `git diff --check` passed.
- Evidence directory: `.opencode/artifacts/analysis-execution-20260921/`;
  final main test log: `integrated-pytest-v4.log`. This factual milestone appendix
  is the only post-review documentation addition; reviewed runtime hashes remain exact.

**Next boundary:** select a bounded runtime/Analysis API integration packet before
mounting this callable/store, then expose the same request/status/result through MCP.
No API/MCP/UI, signed production transport or deployment was added here. Terra export
compatibility, field/metrological accuracy and customer end-to-end acceptance remain
unverified. Product-state/EXT-VAL is unchanged. No commit, push, merge, deployment,
credential or device action was performed.
