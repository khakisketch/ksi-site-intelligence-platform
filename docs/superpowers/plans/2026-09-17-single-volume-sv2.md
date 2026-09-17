# SINGLE_VOLUME SV-2 Implementation Plan — execution store, routes, worker

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An ELIGIBLE `SINGLE_VOLUME` decision can be activated, issued as a sealed request, leased by a processing worker, measured with the boundary-base algorithm, and reported back to Core with a fenced, sealed report — on the real assembled graph, replayable after restart.

**Architecture:** The relative-volume ledger is refactored into a family-neutral base (`ExternalVolumeLedger`) with family hooks; `ExternalRelativeVolumeStore` keeps byte-identical journal kinds and messages, and `ExternalSingleVolumeStore` is a second family. The quantitative catalog gains a single-volume execution lifecycle. The worker gains a `SINGLE_VOLUME` operation that reuses the hardened two-input sandbox transport.

**Tech Stack:** Python 3.12, pydantic v2, FastAPI, numpy/rasterio/scipy, `uv run --locked`.

**Spec:** `docs/superpowers/specs/2026-09-17-single-volume-design.md` §7 (plus the amendment below). SV-1 plan: `docs/superpowers/plans/2026-09-17-single-volume-sv1.md`.

## Spec amendment (decided during SV-2 planning)

1. **Two sealed worker inputs, not one.** The measurement sandbox transport
   (`external_measurement_docker_backend.py`, `external_measurement_container_entrypoint.py`)
   always mounts a primary input read-only and spools a secondary input with an
   exact size/SHA check. Loosening that to one input would change the hardened
   container protocol. `SINGLE_VOLUME` therefore launches with
   `inputs = (TARGET_DSM, CHECKPOINT_CSV)`: the primary is the target DSM, the
   secondary is the exact sealed checkpoint CSV of the one bound evidence record.
   The worker verifies the CSV bytes against their sealed identity (the same
   staging check every launch gets) and uses the record's validated RMSE for the
   uncertainty bound. Spec §7.3's "1- or 2-tuple" is replaced by this.
2. **Shared ledger instead of a copied store.** Spec §7.1 proposed moving helpers
   to a common module and mirroring the store. Instead the store body becomes a
   generic base class; only family hooks differ. Relative journal kinds, request
   ids, report ids and recovery messages stay byte-identical.

## Global Constraints

- Never change relative-volume journal kind strings, request/report id prefixes, contract models or recovery error text.
- Single-volume journal kinds: `external-single-volume-issued`, `-idempotency-bound`, `-leased`, `-reported`, `-failed`; request id prefix `external-single-volume-`; report id prefix `external-single-volume-report-`; natural fingerprint domain `external-single-volume-issue.v1`.
- Catalog journal kinds: `external-quantitative-single-execution-activated`, `external-quantitative-single-execution-revoked`; execution identity domain `ksi.external-quantitative-single-execution.v1`.
- Workflow config: optional `singleExecutionTemplates` (list of ≤ 1). When absent, the catalog admission body and its digest are unchanged.
- Worker operation string `SINGLE_VOLUME`; lane `single-volume`; aggregate `metricType` `SINGLE_VOLUME_AGGREGATE_V2`; Core internal base path `/v1/internal/external-validation/single-volumes`.
- New Core modules are registered in `docs/audit/CORE_R1_MODULE_MIGRATION.json` as `T3_NEW_MODULE`, no alias shims.
- Uncertainty: `measured_area_m2 × hypot(base_roughness_m, target_rmse_m)` when the target RMSE is known, else `None`.
- Gates per task: targeted pytest; before closing: `ruff check .`, `mypy packages services tests tools`, full `pytest` (read the real exit code).
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

### Task 1: Family-neutral volume ledger (no behavior change)

**Files:** Modify `services/core/src/ksi_core/domains/external/quantity/external_relative_volumes.py`.

**Interfaces produced:**
- `ExternalVolumeRecord[RequestT, AuthorityT, ReportT]` (frozen generic dataclass; fields unchanged). `ExternalRelativeVolumeRecord` is the relative parametrization (type alias usable in annotations).
- `ExternalVolumeResult[...]`, `ResolvedVolumeReport[...]` likewise; `ExternalRelativeVolumeResult`, `ResolvedRelativeVolumeReport` kept as names.
- `ExternalVolumeLedger(Generic[RequestT, AuthorityT, ReportT, PayloadT])` holding every current store method. Family hooks (abstract):
  - class attrs `_LABEL` (e.g. `"relative-volume"`), `_KIND_PREFIX` (`"external-relative-volume"`), `_REPORT_ID_PREFIX`;
  - `_authority_from_snapshot(raw)`, `_request_from_wire(raw)`, `_request_wire(request)`, `_report_from_wire(raw)`, `_report_wire(report)`, `_build_report(**fields)`;
  - `_natural_fingerprint(*, organization_id, current_work_order_id, authority)` (static), `_request_id(natural)` (static);
  - `_build_request(authority, *, request_id, current_work_order_id, issued_at, idempotency_key)`;
  - `_inputs_binding_error(request, authority) -> str | None` (DSM + evidence equality);
  - `_primary_site_id(authority)`, `_report_sort_time(record)`;
  - `_measurement_payload_error(record, payload)`.
- `ExternalRelativeVolumeStore(ExternalVolumeLedger[...])` implements the hooks with today's exact code.
- `build_volume_router(store, *, family: VolumeRouterFamily, ...)` where `VolumeRouterFamily` carries the public/internal path segments, tag, report input model, worker-input view factory; `build_external_relative_volume_router` becomes a thin wrapper with identical paths and models.

- [ ] Step 1: Record a baseline: `uv run --locked pytest tests/contract/test_external_relative_volumes.py tests/contract/test_external_relative_volume_s3_capabilities.py tests/contract/test_external_quantitative_production_flow.py tests/contract/test_external_product_loop*.py tests -k "relative_volume or reobservation or result_review" -q` → all pass.
- [ ] Step 2: Refactor per the interface list; every string literal that names the family is produced from `_LABEL`/`_KIND_PREFIX` so the relative output is byte-identical.
- [ ] Step 3: Re-run the Step 1 command and `mypy packages services tests tools`; both unchanged/green.
- [ ] Step 4: Commit `refactor(core): family-neutral external volume ledger (SV-2)`.

### Task 2: Single-volume execution authority and store

**Files:** Create `services/core/src/ksi_core/domains/external/quantity/external_single_volumes.py`; test `tests/contract/test_external_single_volumes.py`; inventory entry.

**Interfaces produced:**
- `ExternalSingleVolumeExecutionAuthority` (frozen dataclass): `organization_id, site_id, current_work_order_id, decision_id, decision_digest, compatibility_mapping_digest, target: ExternalVolumeInputBindingV1, evidence_record_digests: tuple[str] (len 1), validation_policy_digest, zone_snapshot, execution_policy: ExternalSingleVolumeExecutionPolicyV1, authorized_actor_ids, valid_from, valid_until, historical_authority_digest, target_rmse_m: float | None, maximum_zone_cell_count, maximum_zone_area_m2, synthetic_test_only`; `is_current_at`, `snapshot_payload`, `from_snapshot` (strict, same canonical-type rules as relative).
- `ExternalSingleVolumeExecutionAuthorityPort` (Protocol: `currentness_coordinator`, `resolve_for_issue`, `guard_current`, `resolve_historical`).
- `ExternalSingleVolumeObservedReportInput(payload: ExternalSingleVolumeMeasurementPayloadV1, computed_at)`.
- `ExternalSingleVolumeStore(ExternalVolumeLedger[ExternalSingleVolumeRequestV1, ExternalSingleVolumeExecutionAuthority, ExternalSingleVolumeReportV1, ExternalSingleVolumeMeasurementPayloadV1])`.
  - `_measurement_payload_error`: request/decision/target DSM/zone/execution policy/build/config digests; threshold equality; `common_valid_fraction ≥ minimum_common_valid_fraction`; `boundary_valid_fraction ≥ minimum_boundary_valid_fraction`; zone cell/area limits; uncertainty equals `measured_area × hypot(base_roughness, target_rmse)` or is `None` iff `target_rmse_m is None`.
- `SingleVolumeWorkerLaunchMaterial(validation_policy, evidence_record: ExternalEvidenceRecordV1, evidence_context_digest)` and `SingleVolumeWorkerLaunchMaterialResolver` (`preflight`, `material_remains_current`) using use `SINGLE_VOLUME` and subject `(target.subject,)`.
- `ExternalSingleVolumeInputCapability` = the relative capability model; `ExternalSingleVolumeWorkerInputView(request, execution_policy, validation_policy, evidence_record, inputs: (TARGET_DSM, CHECKPOINT_CSV))`.
- `build_external_single_volume_router(store, *, input_capability_issuer, execution_activator, work_orders, clock)` with paths `/v1/observation-work-orders/{work_order_id}/single-volume-requests[/{request_ref}]` and `/v1/internal/external-validation/single-volumes[/{request_ref}/lease|heartbeat|input|report|incomplete-failure]`.

- [ ] Step 1: Tests (mirroring the relative test helpers): authority snapshot round trip and strictness; issue → ALREADY_ISSUED retry → IDEMPOTENCY_CONFLICT; claim/heartbeat/fence denial; report accepted with the exact uncertainty; report rejected for wrong uncertainty, boundary fraction below policy, wrong target digest; incomplete failure; replay after restart reproduces records; forged issued event → recovery error; router issue + worker lease/report over HTTP with a fake capability issuer.
- [ ] Step 2: Implement; run tests green.
- [ ] Step 3: Commit `feat(core): single-volume execution ledger and routes (SV-2)`.

### Task 3: Catalog single-volume execution lifecycle and config

**Files:** Modify `external_quantitative_authority.py`, `authority/external_result_workflow_config.py`; tests in `test_external_quantitative_authority.py`, replay test, workflow config test.

**Interfaces produced:**
- `ExternalQuantitativeSingleExecutionTemplate(execution_policy: ExternalSingleVolumeExecutionPolicyV1, authorized_actor_ids, valid_from, valid_until, maximum_zone_cell_count, maximum_zone_area_m2)`.
- Catalog ctor kwarg `single_execution_template_resolver: Callable[[ExternalSingleVolumeCompatibilityRecord, datetime], ExternalQuantitativeSingleExecutionTemplate | None] | None`.
- `activate_single_execution(*, decision_ref, principal, current_work_order_id, now) -> ExternalSingleVolumeExecutionAuthority | None` (decision via `resolve_current_single_volume_for_issue`, mapping current, template current, `target_rmse_m` from the snapshot's VALIDATED evidence RMSE).
- `revoke_single_execution(authority_digest, *, actor, now) -> bool`.
- `single_execution_port` property → adapter implementing `ExternalSingleVolumeExecutionAuthorityPort` (`resolve_for_issue`, `guard_current`, `resolve_historical`).
- `bind_decision_store` additionally requires `resolve_current_single_volume_for_issue`/`resolve_historical_single_volume` and verifies retained single executions.
- Config: `_parse_catalog` accepts optional `singleExecutionTemplates` (≤ 1); `_catalog_admission_body` includes it only when present; `ExternalRelativeVolumeRuntimeAuthorities` gains `single_execution`, `activate_single_execution` (optional, default `None`).

- [ ] Step 1: Tests: activation after decision → issue resolves → guard current → revoke closes; replay rejects single execution without its durable decision; catalog body digest for a relative-only catalog unchanged (pin the digest computed before the change); config with `singleExecutionTemplates` parses and binds the resolver.
- [ ] Step 2: Implement; tests green. Commit `feat(core): single-volume execution activation in the quantitative catalog (SV-2)`.

### Task 4: S3 input capabilities and composition

**Files:** Create `external_single_volume_s3_capabilities.py`; modify `composition/external_graph.py`, `composition/routes/external.py`, `composition/assembly_validation.py`, `external_result_workflow_assembly.py`, `contracts/api/openapi-core.yaml`, route coverage tests.

- `ExternalSingleVolumeS3InputCapabilityIssuer(reconstruction, evidence, storage, signing_clock)` → `(TARGET_DSM, CHECKPOINT_CSV)` capabilities for the exact running lease; CSV resolved from the sealed evidence item whose manifest digest equals the bound record's `evidence_manifest_digest`.
- `app.state.external_single_volume_store`; router mounted beside the relative router; assembly validation: store and resolver share the coordinator.
- [ ] Tests: issuer returns both capabilities only for the active lease and exact sealed bytes; assembly exposes the store; hostile-body route coverage lists the new POST routes; `test_api_contract_sync.py` passes with the new OpenAPI paths.
- [ ] Commit `feat(core): single-volume capabilities, assembly and API (SV-2)`.

### Task 5: Worker `SINGLE_VOLUME` operation

**Files (processing-controller):** `external_measurement_protocol.py`, `external_measurement_result.py`, `external_measurement_container_protocol.py`, `external_measurement_container_entrypoint.py`, `external_measurement_algorithms.py`, `external_measurement_core_client.py`, `external_measurement_attempts.py`, `external_validation_lanes.py`, `external_validation_runner.py`, `external_validation_worker.py`; tests under `services/processing-controller/tests/`.

- Protocol: operation literal adds `SINGLE_VOLUME`; fields `single_volume_request`, `single_volume_execution_policy`; `_single_volume_bindings` requires roles `(TARGET_DSM, CHECKPOINT_CSV)`, primary bound to `request.target`, one sealed evidence record in `volume_evidence_records` bound to the target and policy; `request_id` / `execution_manifest_digest` cover the new operation.
- Result: `SingleVolumeAggregateV2(metric_type="SINGLE_VOLUME_AGGREGATE_V2", zone_id, metrics: ExternalSingleVolumeMetricsV1)`.
- Entrypoint: for `SINGLE_VOLUME`, the secondary is a CSV (checkpoint memory preflight is not needed; size ceiling applies), then `measure_single_volume_aggregate(request, primary, envelope, watchdog)`.
- Algorithm: read primary DSM (`_read_valid_dsm`), memory ceiling, `measure_single_volume_zone(...)` with `dsm_rmse_m` from the one VALIDATED evidence record.
- Core client: `_SINGLE_VOLUME_BASE`; all operation branches; `_single_volume_launch`, `_single_volume_payload`.
- Lanes/runner/worker: `ExternalLane.SINGLE_VOLUME = "single-volume"`.
- [ ] Tests: protocol accepts the exact launch and rejects role/binding changes; algorithm on a synthetic sealed GeoTIFF gives the box volume; core client maps input/report bodies; lane polls the new base.
- [ ] Commit `feat(worker): SINGLE_VOLUME measurement operation (SV-2)`.

### Task 6: Integrated proof and gates

- [ ] Extend the signed-provider lifecycle test: config with `singleExecutionTemplates`; after the HTTP decision, `POST /single-volume-requests` issues (activation happens in the router), the store is claimed, the worker input route returns both capabilities, a report computed with `measure_single_volume_zone` is accepted, and the report survives restart through `resolve_historical_report_ref`.
- [ ] Full gates with real exit codes; update checkpoint; commit and push.
