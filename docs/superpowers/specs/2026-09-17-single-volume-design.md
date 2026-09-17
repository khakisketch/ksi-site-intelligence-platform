# Single-epoch stockpile volume (SINGLE_VOLUME) — design (2026-09-17)

Status: approved direction (owner chose "분석 대상 확장" as the next investment and
approved the structure on 2026-09-17: automatic boundary base surface, same evidence rigor
as relative volume, WorkArea reuse, a new decision type parallel to RELATIVE_VOLUME).
Rank: below `PRODUCT_CONSTITUTION`, `FINAL_DECISION_LEDGER`, `MASTER_PRD`,
`DOMAIN_INVARIANTS`, ADR-KSI-022/025/026/036 and the sealed external contracts. This
document changes no frozen authority and extends no sealed contract; it adds a new
contract family beside the relative-volume family.

## 1. Goal

Today the external loop can only answer "how much changed between two sealed DSMs".
The most common customer question on a construction or aggregate site is "how much
material is in this pile right now", which needs one DSM, not two. This program adds a
single-epoch volume measurement that reuses every proven part of the relative-volume
loop — sealed subjects, inspection, independent checkpoint evidence, catalog admission,
Core-minted requests, worker leasing, read projection, review and reobservation — and
adds exactly one new algorithm: a base surface derived from the zone boundary.

Product-facing name: **단일 시점 체적** (label in the field: 적치물 체적). Internal use
code: `SINGLE_VOLUME`.

## 2. Decisions already made (do not reopen)

| Question | Decision |
|---|---|
| Base surface | Automatic: interpolated from the DSM elevation along the WorkArea boundary. No extra customer input, no base DSM upload in V1. |
| Evidence rigor | Identical to relative volume: one Core-validated checkpoint evidence record for the epoch, with `independent_attestation` in its sealed context. |
| Zone | Existing ACTIVE `WorkArea` of the site, snapshotted into `ExternalVolumeZoneSnapshotV1` exactly as relative volume does. |
| Approach | New decision/request/report family (`external-single-volume-*.v1`) parallel to RELATIVE_VOLUME. Shared pure code (volume math, DSM reading, leasing, fences, enums) is reused by import; sealed contracts are never extended. |

## 3. Non-goals (V1)

- No user-drawn base plane, no "lowest point" base, no base DSM from another epoch
  (that is RELATIVE_VOLUME).
- No density/tonnage conversion. Output is m³ with a bounded uncertainty.
- No change to `ExternalRelativeVolume*` contracts, journals or schemas.
- No LLM involvement in numbers; the AX briefing sentence is deterministic.

## 4. Algorithm (packages/change-detection)

New import-only module `ksi_change_detection/external_single_volume.py`. It depends on
numpy, rasterio and scipy (all already dependencies of the package; the processing
worker already imports `ksi_change_detection` for `measure_external_volume_zone`).

### 4.1 `derive_boundary_base_surface(dsm, valid, transform, crs, cell_area_m2, polygon, zone_id, *, minimum_boundary_valid_fraction, maximum_zone_grid_cells)`

1. **Zone mask.** Rasterize the zone polygon on the DSM grid with the same helper and
   the same `maximum_zone_grid_cells` ceiling `measure_external_volume_zone` uses. Reason
   codes reused: `ZONE_OUTSIDE_DSM`, `ZONE_TOO_LARGE`, `ZONE_POLYGON_INVALID`.
2. **Boundary cells.** A zone cell is a boundary cell when at least one of its four
   neighbours is outside the mask (numpy shift comparison; no scipy.ndimage). The
   boundary ring is deterministic for a given mask.
3. **Boundary samples.** Boundary cells whose DSM value is valid. Require
   `boundary_valid_fraction = valid_boundary / boundary_cells ≥ minimum_boundary_valid_fraction`
   (policy) and at least 3 non-collinear samples; otherwise fail with
   `BOUNDARY_SAMPLES_INSUFFICIENT`.
4. **Base surface.** `scipy.interpolate.LinearNDInterpolator` over the boundary samples
   (x, y in the DSM's projected CRS, z in metres) evaluated on every zone cell. Zone cells
   that fall outside the Delaunay hull of the samples (possible when a stretch of
   boundary is nodata) are marked invalid — unknown, not zero. scipy's Delaunay is
   deterministic for identical input order; samples are ordered by (row, col).
5. **Base roughness.** `base_roughness_m` = RMS residual of the boundary samples against
   their least-squares plane. It bounds how non-planar the ground under the pile is and
   is the base-surface term of the uncertainty. Reported, never hidden.
6. **Result.** `BoundaryBaseSurface(base_m, valid, boundary_cell_count, boundary_sample_count,
   boundary_valid_fraction, base_roughness_m)`.

### 4.2 `measure_single_volume_zone(...)`

Builds `DiffResult(diff_m = dsm − base, valid = dsm_valid & base_valid, transform, crs,
cell_area_m2)` and calls the existing `measure_external_volume_zone` with
`baseline_rmse_m = base_roughness_m`, `current_rmse_m = dsm_rmse_m`. So:

- `fill_m3` = material above the base (the pile), `cut_m3` = below the base (a pit),
  `net_m3 = fill − cut`, `measured_area_m2`, `common_valid_fraction` — same semantics and
  the same `threshold_m` dead band as relative volume.
- `uncertainty_m3 = measured_area_m2 × hypot(dsm_rmse_m, base_roughness_m)` — the same
  RSS-area bound, with the base roughness standing in for the missing second epoch.
  Method literal: `SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1`. Base method literal:
  `BOUNDARY_LINEAR_INTERPOLATION_V1`.

`ExternalSingleVolumeMetricsV1` = the relative metric fields plus `baseRoughnessM`,
`boundaryCellCount`, `boundarySampleCount`, `boundaryValidFraction`.

Tests (package level, synthetic rasters): flat ground + box pile → fill = box volume,
cut = 0, roughness ≈ 0; sloped plane ground + pile → same fill within one cell area
tolerance (plane is reproduced exactly by linear interpolation); pit → cut; nodata stretch
along boundary → cells outside hull invalid, fraction gate fails when below policy;
`ZONE_TOO_LARGE` and `ZONE_OUTSIDE_DSM` reuse; determinism (same input → identical
digest of outputs).

## 5. Contracts (packages/event-contracts + contracts/schemas)

New module `ksi_event_contracts/external_single_volume.py`; each model is frozen, sealed
with a canonical digest exactly like its relative counterpart, and has a JSON schema under
`contracts/schemas/` plus a wire-dict helper.

| Model | contractVersion | Shape |
|---|---|---|
| `ExternalSingleVolumeDecisionV1` | `external-single-volume-decision.v1` | `decisionId`, `subject`, `subjectDigest`, `use: "SINGLE_VOLUME"`, `policyDigest?`, `inspectionReportDigest?`, `evidenceRecordDigests` (0 or 1), `zone?: SealedZoneReferenceV1`, `compatibilityMappingDigest?`, `verdict`, `reasons`, `remediations`, `decidedAt`, `decisionDigest`. Validator: subject digest binds; ALLOWED requires policy, inspection report, exactly one evidence digest, zone and mapping. |
| `ExternalSingleVolumeExecutionPolicyV1` | `external-single-volume-execution-policy.v1` | Relative policy fields with `uncertaintyMethod: "SINGLE_EPOCH_BOUNDARY_BASE_RSS_AREA_BOUND_V1"`, `baseSurfaceMethod: "BOUNDARY_LINEAR_INTERPOLATION_V1"`, `minimumBoundaryValidFraction (0 < x ≤ 1)`. |
| `ExternalSingleVolumeRequestV1` | `external-single-volume-request.v1` | `requestId`, `currentWorkOrderId`, `decisionId`, `decisionDigest`, `target: ExternalVolumeInputBindingV1`, `evidenceRecordDigests` (exactly 1), `validationPolicyDigest`, `executionPolicyDigest`, `zoneSnapshot`, `issuedAt`, `idempotencyKey`, `requestDigest`. Validator: evidence digest count 1, zone CRS equals target CRS, `target.subject.work_order_id == currentWorkOrderId`. |
| `ExternalSingleVolumeMeasurementPayloadV1` | `external-single-volume-measurement-payload.v1` | `requestDigest`, `metrics: ExternalSingleVolumeMetricsV1`, observed DSM CRS/vertical digests, `algorithmBuildDigest`, `configDigest`, `uncertaintyNote`. |
| `ExternalSingleVolumeReportV1` | `external-single-volume-report.v1` | Mirrors the relative report: `reportId`, `requestId`, `requestDigest`, `payload`, `verdict`, `reasons`, `reportedAt`, `reportDigest`. |

`ExternalVolumeZoneSnapshotV1`, `ExternalVolumeInputBindingV1`, `SealedZoneReferenceV1`
are reused unchanged (their digests are independent of the enclosing family).

Contract tests: schema ↔ model round trip for each, digest stability fixtures under
`tests/contract/fixtures/external-single-volume/`, and the `contracts/schemas` index test.

## 6. Core authority (services/core, quantity domain)

### 6.1 Catalog record

`ExternalSingleVolumeCompatibilityRecord` in a new module
`external_single_volume_authority.py`: `organization_id`, `site_id`, `target:
ExternalVolumeInputBindingV1`, `zone_snapshot`, `evidence_record_digests` (exactly 1),
`execution_policy_ref`, `valid_from/valid_until`, rule descriptor, `mapping_digest`.
Validators: zone CRS = target CRS, evidence digest present, validity ordered.

It is admitted into the **same** `ExternalQuantitativeAuthorityCatalog` (one journal, one
coordinator) through new journal kinds:

- `external-quantitative-single-mapping-activated` / `-revoked`
- `external-quantitative-single-execution-activated` / `-revoked`

Replay of existing journals is unaffected (unknown kinds never existed before; the
catalog's strict replay only has to learn the four new kinds). Dispatch inside the catalog
is by kind; the single records live in their own index keyed by `(site_id, zone
definition digest, target subject digest)`.

`ExternalQuantitativeAuthorityParticipants` gains `single_current_snapshot` /
`single_locally_current`, checking the same facts as the pair version for one binding:
WorkArea ACTIVE + polygon + CRS match the snapshot, manifest DSM entry, MEASURED
inspection report, CRS/vertical consistency, one evidence record whose sealed context
carries `independent_attestation`, active validation policy permitting
`SINGLE_VOLUME` for the subject.

### 6.2 Execution template

The catalog admission body gains an optional `singleExecutionTemplates` list (≤ 1). Its
absence keeps the current body digest for every already-signed catalog. When present it
carries an `ExternalSingleVolumeExecutionPolicyV1` and the same actor/validity/cell/area
limits as the relative template. `activate_single_execution(mapping_digest, ...)` mints
an `ExternalSingleVolumeExecutionAuthority` (Section 7) and journals the activation.

### 6.3 Provider actions

Signed administration actions `ADMIT_SINGLE_MAPPING` (payload `mapping`) and
`REVOKE_SINGLE_MAPPING` (payload `mappingDigest`), rank 1 like the pair actions, applied
by `_apply_mapping_actions` with the same administrator-actor check.

### 6.4 Decisions

`external_use_decisions.py`: `DecisionCandidate` gains `ExternalSingleVolumeDecisionV1`;
`_candidate_from_wire` dispatches on the new contractVersion; `_scope_and_operation`
returns `("SINGLE_VOLUME", "single-volume")`; `ExternalDecisionIntent` gains
`zone_id` for the single-volume shape (payload rejects DISPLAY/HEIGHT with a zone and
SINGLE_VOLUME without one). New joins `resolve_current_single_volume_for_issue` and
`resolve_historical_single_volume`, mirroring the pair joins.

### 6.5 Evaluator

`ExternalUseEvaluator.request_single_volume(subject, zone_id, principal,
idempotency_key, now)` and route `POST …/use-decisions/single-volume` with body
`{ "zoneId" }`. Snapshot order: policy → sealed subject → MEASURED inspection report →
evidence record (Core-validated, attested) → zone (ACTIVE WorkArea) → single mapping
(current, bound to subject + zone + evidence). Reasons reused verbatim:
`SUBJECT_NOT_SEALED`, `POLICY_UNAVAILABLE`, `INSPECTION_REPORT_BINDING_INVALID`,
`VOLUME_ZONE_BINDING_INVALID`, `EVIDENCE_RECORD_BINDING_INVALID`,
`EVIDENCE_INDEPENDENCE_UNATTESTED`. One new reason:
`SINGLE_VOLUME_MAPPING_UNAVAILABLE` → remediation `AUTHORIZE_SINGLE_VOLUME_MAPPING`,
both added to `contracts/catalogs/external-use-blockers.v1.json` (the blocker contract
test enforces coverage).

## 7. Core execution store and worker seam

### 7.1 Shared queue code

Pure helpers currently private to `external_relative_volumes.py` that the single store
needs unchanged — `_digest`, `_event_digest`, `_require_utc`, `_raw_journal_string`,
`ExternalRelativeVolumeQueuePolicy` (re-exported; renamed alias
`ExternalVolumeQueuePolicy`), status/verdict enums, lease-fence checks — move to
`external_volume_queue_common.py`. `external_relative_volumes.py` re-exports every moved
name, so no caller or test changes. This is the only refactor of existing code in the
program.

### 7.2 `ExternalSingleVolumeStore` (`external_single_volumes.py`)

Mirrors the relative store one-to-one with a single `target` binding and one evidence
digest:

- `ExternalSingleVolumeExecutionAuthority` (snapshot/from_snapshot strict round trip,
  `historical_authority_digest`, `target_rmse_m`, limits) and the port protocol
  `resolve_for_issue / guard_current / resolve_historical`.
- Journal kinds `external-single-volume-issued/claimed/reported/failed/…` with request id
  prefix `external-single-volume-`; the natural fingerprint domain is
  `external-single-volume-issue.v1`.
- `issue`, `list_pending`, `claim`, `worker_input`, `confirm_worker_launch_material`,
  `record_observed_report`, `report_refs_for_site`, `resolve_historical_report_ref`,
  replay recovery, per-organization active-request bound.
- Routes: `POST/GET /v1/observation-work-orders/{id}/single-volume-requests[/{ref}]`,
  `/v1/internal/external-validation/single-volumes/{pending,claim,input,result}`,
  `GET /v1/external-single-volume-reports/{ref}`.

Launch material: `SingleVolumeWorkerLaunchMaterial(validation_policy, evidence_record)`
and a `SingleVolumeWorkerLaunchMaterialResolver` in the same preflight/`material_remains_current`
shape. S3 input capability: `ExternalSingleVolumeS3InputCapabilityIssuer` issuing one
read capability (target DSM) instead of two.

Composition: `external_graph.py` builds the single store beside the relative store from
the same catalog instance (`build_runtime` returns both runtimes);
`routes/external.py` mounts the single routers; `assembly_validation.py` gains the
parallel rules (store bound to the coordinator, resolver present when the store is).

### 7.3 Worker (services/processing-controller)

- `MeasurementLaunchRequestV2.operation` gains `"SINGLE_VOLUME"`; `inputs` becomes a
  1- or 2-tuple (`_single_volume_bindings` requires exactly one input with role
  `TARGET_DSM` bound to `request.target`; the secondary-spool ceiling applies only when a
  secondary input exists). `single_volume_request`, `single_volume_execution_policy`,
  `single_volume_evidence_record` fields follow the volume ones.
- Core client: `_SINGLE_VOLUME_BASE = "/v1/internal/external-validation/single-volumes"`;
  `MeasurementOperationV2` and every operation branch (`list_pending`, `claim`,
  `current_input`, `submit_result`) gain the single case.
- Algorithms: `measure_single_volume_aggregate(request, ...)` reads the one DSM with the
  existing `inspect_primary_dsm` + `_read_valid_dsm` path, applies the memory ceiling with
  `_maximum_zone_grid_cells`, calls `measure_single_volume_zone`, emits
  `metricType: "SINGLE_VOLUME_AGGREGATE_V2"`. Watchdog and result sealing unchanged.
- Container protocol/result: accept the new metric type; `external_measurement_result`
  operation literal gains `SINGLE_VOLUME`.
- Lanes/runner: `ExternalLane.SINGLE_VOLUME = "single-volume"` polled by the same
  validation worker with its own operation string.

## 8. Read side, AX and dashboard

- `external_result_workflow_api.py`: `ExternalResultProjectionView.result` gains
  `kind: "RELATIVE_VOLUME" | "SINGLE_VOLUME"` (default RELATIVE_VOLUME for wire
  compatibility); for single results `baseline_work_order_id` and `baseline_captured_*`
  are null and `metrics` carries the extra single fields. `_for_report_ref` dispatches on
  the report-ref prefix. Site history merges both stores' report refs by `reported_at`.
  Citation `object_type: "EXTERNAL_SINGLE_VOLUME_REPORT"`, label "외부 단일 시점 체적 결과",
  source path `/v1/external-single-volume-reports/{ref}`.
- Review/proposal: `CoreExternalResultReviewSourceAdapter` accepts both stores and joins
  by prefix; the review and reobservation contracts are unchanged (they bind a report ref
  and digest, not a family).
- AX briefing (`SiteBriefing`): one deterministic sentence branch for a single result:
  "{zone} 적치물 체적 {fill} m³ (±{uncertainty} m³, 기저면 거칠기 {roughness} m)".
- Dashboard: `ExternalEvidencePanel` gains a "단일 시점 체적" decision (existing WorkArea
  selector, no baseline choice); BFF routes `use-decisions/single-volume`,
  `single-volume-requests[/{ref}]`, `external-single-volume-reports/{ref}` (+ reviews,
  shares), `sites/{id}/external-single-volume-reports`; `ExternalResultWorkflowPanel`
  issues a single request from a single decision; the site data tab shows merged history
  with a kind `StateBadge`; blocker copy for the new reason/remediation. No new page.

## 9. Testing and acceptance

- Package: algorithm tests (Section 4).
- Contract: schema/digest tests for the five models; blocker catalog coverage.
- Core: catalog replay with the four new kinds (`tests/replay/test_external_quantitative_authority_replay.py`
  extended, plus a new single-volume store replay test); decision store replay with the
  third candidate; evaluator single-volume positive path and one negative path per reason;
  store issue/claim/report/fence/recovery tests mirroring `test_external_relative_volumes.py`;
  assembly validation rules; provider action tests.
- Worker: protocol validators, client branches, `measure_single_volume_aggregate` with
  synthetic sealed GeoTIFFs, container round trip.
- Integrated: `test_external_quantitative_production_flow.py` gains a single-volume path
  (admit single mapping → decision → issue → worker → report → projection → review →
  proposal → successor work order) on the real durable graph.
- Dashboard: vitest for the new decision slot, panel issue path, history badge and BFF
  routes; full gates (`tsc`, `eslint`, `vitest`, `next build`).
- Rehearsal: the local in-process playbook (memory `local-rehearsal-playbook`) run once
  end-to-end for SINGLE_VOLUME with real sealed GeoTIFF bytes.

Acceptance: an operator can, on an existing site with one sealed DSM, a validated attested
checkpoint CSV and an ACTIVE WorkArea, request a single-volume decision, issue the
measurement, watch the worker report, see the pile volume with uncertainty and base
roughness in the site data tab and the briefing, review it and propose reobservation —
with every step replayable from journals.

## 10. Decomposition and order

| Sub-project | Scope | Done when |
|---|---|---|
| SV-1 Contracts + algorithm + Core authority/decision | Sections 4, 5, 6 | Contract/package/Core tests green; a SINGLE_VOLUME decision can be ALLOWED on the real graph. |
| SV-2 Execution store + routes + worker | Section 7 | Issue → claim → worker → report round trip in-process with synthetic GeoTIFFs. |
| SV-3 Projection + review + AX + dashboard | Section 8 | Result visible and reviewable in the dashboard; briefing sentence; gates green. |
| SV-4 Integrated flow + replay + rehearsal + docs | Section 9 | Production-flow test and rehearsal evidence recorded; ledger and product-state updated. |

Each sub-project has its own implementation plan under `docs/superpowers/plans/` and
its own commits; SV-1 starts first because everything else depends on the contracts.

## 11. Risks

- **Concave zones / boundary gaps.** Cells outside the sample hull are invalid, not
  zero; the `common_valid_fraction` gate then blocks a misleading number. Documented in
  the uncertainty note.
- **Roughness as a proxy.** A curved ground surface under a pile is a real bias that
  roughness only bounds; the report says so in `uncertaintyNote`, and the product never
  presents the number without its ±.
- **Protocol 1-tuple change.** Loosening `inputs` touches every launch-request validator;
  guarded by the existing checkpoint/relative test suites which must stay green
  unchanged.
- **Catalog body digest.** Adding an optional key must not alter existing digests; a
  test pins a signed relative-only catalog digest before and after.
