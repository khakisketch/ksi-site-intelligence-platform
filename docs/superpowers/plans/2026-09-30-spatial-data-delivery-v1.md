# Spatial Data Delivery V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` for native execution or `subagent-driven-development` if the Human chooses delegation. Steps use checkboxes; no implementation before this written plan is approved. Do not commit without separate authorization.

**Goal:** prepare native-grid DSM/ORTHO rectangles from existing scoped spatial assets and deliver exact bytes through currently authorized Core downloads.
**Architecture:** Core owns explicit rights, frozen source/policy identity, durable jobs, leases, output acceptance and download currentness. A distinct Processing Controller worker performs isolated raster preparation using the existing import-only primitive. An immutable-version storage adapter and guarded ASGI response prevent whole-object buffering or public presigned delivery.
**Tech Stack:** existing Python 3.12 workspace, Pydantic contracts, FastAPI/Starlette, DurableJournal, rasterio/GDAL and boto3 optional storage adapter; no dependency upgrades.
**Spec:** [Human-approved Spatial Data Delivery V1](../specs/2026-09-30-spatial-data-delivery-v1-design.md), approved by “승인” on 2026-09-30.
**Task/Status:** SDP-DATA-01; PLAN AWAITING HUMAN REVIEW AND EXECUTION-METHOD SELECTION. No implementation task is done.

## Global Constraints

- Native-grid DSM float32/float64, one band; ORTHO RGB/RGBA uint8 only. No resampling, reprojection, polygon mask, height adjustment, tile, raw-photo or other-kind export.
- Current catalog V1 remains `NOT_AVAILABLE_FROM_CATALOG` / `VIEW_METADATA`; no existing Analysis MCP/worker, Processing worker or Copilot authority expansion.
- Actual pixel-expanded bounds, not only requested bounds, must fit the explicit grant bbox. CRS digests match exactly; missing vertical reference/accuracy stays unknown.
- Only exact sealed bytes with an applicable MEASURED inspection are admitted. Public header probes and fixture assertions cannot substitute for full inspection.
- Core organization comes from Principal; foreign scope is identical `404`. Rights, purpose/AI consent and execution location are independently enforced.
- Rights, policy and activation are explicit injected authority; no production defaults, grant editor, account/credential/key provisioning or deployment.
- Full policy snapshots have positive finite limits; no operational numerical envelope inferred from two public files. Local fixture/experiment policies are not production approval.
- New output storage requires trustworthy full-object SHA-256 and an immutable version ID. No `get_bytes()`, unversioned fallback, ETag-as-SHA or public redirect.
- Full spool hash before response bytes; fresh authorization immediately before headers and each bounded chunk; no Range, cache or conversion. Already delivered/in-flight authorized bytes cannot be recalled.
- Cancel, lease expiry, deadline, retries, upload-orphan cleanup and retention are durable and bounded. Old analysis/managed/ingress history is immutable.
- No commits, push, PR, deployment, secrets, customer contact or worktree cleanup. Preserve main/candidate WIP; implementation uses a revalidated isolated worktree without committing the shared checkpoint.
- EXT-VAL and product-state acceptance remain open. Local software, public-file experiments, customer Terra compatibility, remote CI, host proof and customer two-cycle acceptance are separate evidence.

## Review Focus

1. A rectangle is authorized continuously but expanded output leaks neighboring pixels: exact edge and subpixel tests in Task 2 must deny it.
2. Permission disappears after spooling or during transfer: Task 7 uses recorded ASGI events, not buffered TestClient alone, to prove pre-header refusal and truncated streams.
3. Old upload/report arrives after cancel or fence takeover: Tasks 3/4/7 must reject publication and clean exact owned versions only after capability expiry.
4. Storage returns multipart/composite checksum, `VersionId="null"`, or a substituted version: Task 4 must refuse rather than equate ETag/composite digest to whole-file SHA-256.
5. Historical/superseded assets or grants change while a request is retried: Tasks 2/3/5 retain exact identity, history visibility and conflict semantics without latest-version substitution.

---

## Required implementation declaration

Requirement IDs: SDP-REQ-01/02/03/05/06/07/08; local acceptance spec §8.1–6.
Owner modules: Core `domains/external/delivery/` (new domain package, not service), Processing Controller, event contracts and geo-spatial library.
Acceptance: scoped authenticated HTTP → dedicated worker → accepted derivative → independently verified download, including replay, revocation and cleanup negatives.
Contracts affected: three additive spatial-data schemas below, additive OpenAPI/auth permissions; existing catalog/Analysis/WorkArea meaning unchanged.
Reference assets/adoption: catalog identity, DurableJournal and native-window math ADOPT; generic external byte transport ADOPT via its public interfaces; Analysis authority/lease pattern REFERENCE_ONLY, no authority reuse; references repositories read-only.
Files to change/tests: exact ownership per task below. Foundation/currentness and old evidence ports remain unchanged.
HIL/device assumptions: none for local data path; no flight, Terra or actual host isolation proof inferred.
License/data implications: CC BY 4.0 public samples retain Cambridge Coastcare attribution and modification notice; no training or external AI transfer. A tenant grant remains necessary.
Rollback: disable only new local wiring/activation, preserve receipts/audit and existing WIP; owned orphan cleanup only. No reset or whole-file restore.

## Contract and interface decisions shared by tasks

All new models derive from `_CamelModel`, are frozen/revalidated, forbid extras/nonfinite values, use camelCase wire aliases and strict bounded fields. Text IDs are UTF-8, 1–255 characters; assetRef matches `^ksa-v1-[0-9a-f]{64}$`; digests match `^sha256:[0-9a-f]{64}$`; UTC timestamps are timezone-aware UTC; sizes/counts reject bool/coerced strings. Bounds are exactly four finite int/float coordinates (not bool/string), ordered with positive extent. Canonical digest preimages omit only the model's own digest/signature. Local test builders live in `tests/contract/spatial_data_fixture.py`; no production module imports it.

Existing nested contracts retain their own hash conventions. NativeWindowReceiptV1 uses bare lowercase hex source/output SHA-256; the Task 6 adapter normalizes those two byte hashes once to prefixed digests for the new receipt and validates them, without changing the primitive or existing inspector payloads. Source declarations and measured facts remain separate.

| Model / module in `packages/event-contracts/src/ksi_event_contracts/` | Exact content / responsibility |
| --- | --- |
| `SpatialDataRequestV1`, `SpatialDataPurposeV1`, `SpatialDataExecutionStateV1`, `SpatialDataAvailabilityV1` / `spatial_data.py` | Request fields `{assetRef, requestedBounds, observedCrsDigest, resolutionMode:"NATIVE", purpose:GENERAL_DATA_USE|EXTERNAL_AI}`; state sets copied from spec §5. |
| `SpatialDataSourceV1` / `spatial_data.py` | assetRef, Site/WorkArea/WorkOrder/epoch/submissionRef/revision/artifact/kind; exact `SealedExternalSubjectV1`, observed SHA/size, `ArtifactInspectionOutcomeV1`, report/inspector digests; area identity/boundary digest and declaration timestamps/observed CRS units. No object key or URL. |
| `SpatialDataPolicyV1` / `spatial_data_authority.py` | policyId/revision/digest, `ResourceEnvelopeV1`; maxOutputPixels/maxOutputBytes, streamChunkBytes/maxStreamBytes/streamDeadlineSeconds, maxActiveJobsPerOrganization/maxActiveDownloadsPerOrganization, maxPendingRecords/maxListRecords/maxSnapshotBytes/maxJsonBytes/maxIdempotencyKeyBytes, leaseSeconds/maxAttempts, min/maxRetryBackoffSeconds, retentionSeconds, maxCleanupAttempts/cleanupDeadlineSeconds. All explicit, positive finite; no defaults for numbers. |
| `SpatialDataGrantV1`, `SpatialDataRevocationV1` / `spatial_data_authority.py` | spec §3 exact fields; operations PREPARE/READ, purpose set, processing location reuses existing `ExecutionLocus` wire values (`site_onprem`, `ksi_server_gpu`, `customer_workstation`, `vendor_cloud`), UTC bounds, license/provenance digest and attribution; monotonic exact revision revocation. Both canonical digest-bound; the grant, actual worker location and Site data-residency policy must agree. |
| `SpatialDataRuntimeV1`, `SpatialDataActivationV1` / `spatial_data_authority.py` | fixed `ksi-native-window.v1`, executable/build/runtime-image/version/OCI/lock digests; organization, worker principal/instance, profile/policy/runtime digests, trusted endpoint origins and UTC interval. Distinct authority from Analysis. |
| `SpatialDataFrozenJobV1`, `SpatialDataAttemptV1`, `SpatialDataJobViewV1`, `SpatialDataPageV1` / `spatial_data.py` | job ID `sdj-v1-<uuid>`, requester/scope/body/source/full grant-policy-runtime snapshots, key hash/fingerprint and UTC creation/deadline; attempt number/fence/worker/instance/acquisition-key hash/lease; public status contains immutable IDs + separate current availability, reason/remediation, optional receipt and bounded cursor/list. Private snapshots excluded from public view. |
| `SpatialDataReceiptV1` / `spatial_data.py` | job/source/request/profile/runtime/policy/grant digests; exact NativeWindowReceiptV1 facts including output SHA/size, request/actual bounds/grid/masks/NoData; UTC preparation/capture/producer timestamps with declaration provenance; vertical unknown limitation; attribution/modification notice; `accuracyAssessed:false`. No storage location, token, source tags or accuracy number. |
| `SpatialDataSourceCapabilityV1`, `SpatialDataUploadCapabilityV1`, worker lease/renew/input/output-upload/complete/failure models / `spatial_data_worker.py` | Capabilities bind artifact/receipt digest, observed SHA/size, credential-free HTTP(S) URL, required headers and UTC expiry; no arbitrary header forwarding. Input contains one source capability and exact attempt/frozen-job/runtime; upload declaration binds receipt/hash/size/content type; report references upload declaration digest, not caller object key/version; failure typed reason/retryable classification. Required GET headers `X-Spatial-Data-Worker-Instance-Id` and `X-Spatial-Data-Attempt-Digest`. |
| `SpatialDataErrorV1` / `spatial_data.py` | `{reason,message,retryable,remediation}`; typed safe reasons map per spec §7; never exception traceback or object path. |

These schemas are additive: `contracts/schemas/spatial-data.v1.json`, `spatial-data-authority.v1.json`, `spatial-data-worker.v1.json`. Each is Draft202012 with `$defs` for its module's exported models; check exact model-generated refs/aliases/constraints against fixtures. Do not hand-maintain a second permissive field set.

## Task 1 — Strict transport, rights and policy contracts

**Files:** create the three event-contract modules and three schemas above; create `tests/contract/spatial_data_fixture.py`, `tests/contract/test_spatial_data_contracts.py`. Existing `_base.py` unchanged.
**Consumes:** existing `_CamelModel`, sealed subject/inspection/resource contracts, `ProcessingArtifactKind` and canonical JSON helpers.
**Produces:** models above; `.canonical_digest() -> str` on grant/policy/runtime/activation/frozen job/attempt/receipt; `.is_current_at(now: datetime) -> bool` on grant/activation. Fixture `make_policy(**overrides)`, `make_grant(**overrides)`, `make_request(**overrides)` provide explicit valid small local inputs.

- [ ] Step 1: write `test_strict_request_and_policy` and parametrized schema/model rejection tests for extras, wrong assetRef, bool/string/nonfinite bounds, naive time, changed digest, absent budgets, unsupported kind/purpose, invalid cross-field limits. Assert `request.resolution_mode == "NATIVE"` and both schema/model reject the same mutations.
  Core assertions: `assert make_request().resolution_mode == "NATIVE"`; `with pytest.raises(ValidationError): make_request(requested_bounds=(True, 0, 1, 1))`; `with pytest.raises(ValidationError): make_policy(stream_chunk_bytes=0)`.
- [ ] Step 2: run `.venv/bin/python -m pytest tests/contract/test_spatial_data_contracts.py -q`; confirm failure from missing new contracts, not environment errors.
- [ ] Step 3: implement only the strict models, canonical digest validation and schemas. Policy validates `streamChunkBytes <= min(maxOutputBytes,maxStreamBytes)`, `leaseSeconds <= envelope.maxDeadlineSeconds`, max-output within envelope and staging/spool workspace bounds; grant UTC end > start and nonempty bounded operations/purposes/evidence; no implicit numeric defaults.
- [ ] Step 4: rerun that command and `.venv/bin/ruff check packages/event-contracts/src/ksi_event_contracts/spatial_data*.py tests/contract/spatial_data_fixture.py tests/contract/test_spatial_data_contracts.py`; require zero failures/errors.
- [ ] Step 5: record exact delta/hash and check results in this ledger, leave commit unchecked/unperformed. Contract-only milestone is not a working data service.

## Task 2 — Exact source resolution, pure geometry and durable grants

**Files:** create `packages/geo-spatial/src/ksi_geo_spatial/external_native_window_geometry.py`; modify only geometry/error delegates in `external_native_window.py`; create Core `domains/external/delivery/__init__.py`, `source.py`, `grants.py`; create `tests/contract/test_spatial_data_source_and_grants.py`, `tests/contract/test_external_native_window_geometry.py`, `tests/replay/test_spatial_data_grants_replay.py`.
**Consumes:** Task 1 contracts; existing scoped catalog `.items(site_id,work_area_id,principal)`, reconstruction `resolve_sealed_subject()`, inspection `public_snapshot_bounded()`, WorkArea immutable polygon and shared currentness coordinator.
**Produces:** `plan_external_native_window(*, requested_bounds: tuple[float,float,float,float], measurements: RasterMeasurementsV1, requested_crs_digest: str) -> NativeWindowGeometryV1` with pixelWindow/actualBounds/transform; error `NativeWindowError.reason` re-exported by old module. `SpatialDataSourceResolver.resolve(*, site_id:str, work_area_id:str, asset_ref:str, principal:Principal) -> SpatialDataSourceV1`. `SpatialDataGrantStore(journal:DurableJournal, *, coordinator)` with `provision(grant:SpatialDataGrantV1) -> None`, `revoke(revocation:SpatialDataRevocationV1) -> None`, `require_current(*, grant_id:str, revision:int, source:SpatialDataSourceV1, principal:Principal, purpose:SpatialDataPurposeV1, geometry:NativeWindowGeometryV1, operation:str, policy:SpatialDataPolicyV1, now:datetime) -> SpatialDataGrantV1`; `select_current` takes the same keyword arguments except grant_id/revision and requires exactly one matching grant for first admission. Trusted provisioning only, no router.

- [ ] Step 1: write tests for unauthorized expanded edge cells, exact-cell/subpixel/large-origin edges, rotated/unrepresentable grids, absent/REJECTED/unsealed inspection, cross-tenant invisibility, archived and superseded exact assets, grant revocation/replay and name/status-independent WorkArea digest.
  Geometry fixture: transform `(1,0,0,0,-1,10)`, size 10×10 and request `(0.1,8.1,0.9,8.9)` yield `assert geometry.pixel_window == (0,1,1,2)` and `assert geometry.actual_bounds == (0,8,1,9)`; grant bbox equal to the continuous request must fail `OUTPUT_OUTSIDE_GRANT`, whereas pixel-aligned grant `(0,8,1,9)` passes.
- [ ] Step 2: run `.venv/bin/python -m pytest tests/contract/test_external_native_window_geometry.py tests/contract/test_spatial_data_source_and_grants.py tests/replay/test_spatial_data_grants_replay.py -q`; confirm red missing interfaces.
- [ ] Step 3: move existing `_native_window`/`_stable_pixel_index` arithmetic without semantic edits into the pure module, retaining old error imports/delegation. Validate finite/ordered bounds and exact CRS before planning. Resolve authentic report/outcome against sealed bytes, never reconstruct MEASURED from public raster metadata. Freeze area boundary digest from spec's six fields; no fabricated numeric WorkArea revision.
- [ ] Step 4: implement durable grant provisioning/revocation under coordinator then local lock; require both requested and actual output bounds inside grant and source. Reject ambiguous applicable grants (explicit typed denial), absent location/rights and EXTERNAL_AI without `SiteRecord.ai_egress_allowed`; replay verifies historical digest/snapshots, not today's expiry.
- [ ] Step 5: run new tests plus `.venv/bin/python -m pytest tests/contract/test_external_native_window.py tests/contract/test_spatial_asset_catalog.py -q`; geometry adoption must preserve all original boundary tests. Record evidence, no commit.

## Task 3 — Frozen job, leases, concurrency and cleanup obligations

**Files:** create Core delivery `jobs.py`, `job_events.py`, `job_projection.py`, `storage_types.py`; create `tests/contract/test_spatial_data_jobs.py`, `tests/replay/test_spatial_data_jobs_replay.py`.
**Consumes:** Task 1 snapshots, Task 2 exact source/grants/geometry and the same coordinator as ingress/inspection/area; DurableJournal.
**Produces:** `SpatialDataJobStore(journal, *, grants, sources, policy, runtime, activation, coordinator)`; methods `issue(*, site_id:str,work_area_id:str,request:SpatialDataRequestV1,principal:Principal,idempotency_key:str,now:datetime) -> SpatialDataJobViewV1`, `get(*,job_id:str,principal:Principal,now:datetime) -> SpatialDataJobViewV1`, `list(*,site_id:str,work_area_id:str,principal:Principal,cursor:str|None,limit:int,now:datetime) -> SpatialDataPageV1`, `cancel(*,job_id:str,principal:Principal,now:datetime) -> SpatialDataJobViewV1`, `pending(*,worker:Principal,limit:int,now:datetime) -> tuple[SpatialDataFrozenJobV1,...]`, `lease(*,job_id:str,worker:Principal,instance_id:str,acquisition_id:str,now:datetime) -> SpatialDataAttemptV1`, `renew(*,job_id:str,worker:Principal,attempt:SpatialDataAttemptV1,now:datetime) -> SpatialDataAttemptV1`, `worker_input(*,job_id:str,worker:Principal,attempt:SpatialDataAttemptV1,now:datetime) -> SpatialDataFrozenJobV1`, `reserve_output(*,job_id:str,worker:Principal,attempt:SpatialDataAttemptV1,receipt:SpatialDataReceiptV1,expires_at:datetime,now:datetime) -> SpatialDataOutputTarget`, `complete(*,job_id:str,worker:Principal,attempt:SpatialDataAttemptV1,upload_digest:str,observation:SpatialDataObjectObservation,now:datetime) -> SpatialDataJobViewV1`, `fail(*,job_id:str,worker:Principal,attempt:SpatialDataAttemptV1,reason:str,now:datetime) -> SpatialDataJobViewV1`. Invalid operations raise `SpatialDataDomainError(reason,status_code,retryable)` mapped to Task 1 error envelope.

Private frozen dataclasses in `storage_types.py`: `SpatialDataObjectObservation(object_key:str,version_id:str,size_bytes:int,sha256:str,content_type:str)` and `SpatialDataOutputTarget(object_key:str,job_id:str,attempt_digest:str,receipt_digest:str,expires_at:datetime)`. Job-store tests use these types without any storage adapter or Task 4 dependency. Unknown/missing/null version, malformed hash and nonpositive sizes are rejected at construction.

- [ ] Step 1: write tests `test_same_scoped_key_survives_restart`, `test_changed_payload_conflicts`, `test_quota_reservation_is_atomic`, `test_cancel_and_takeover_reject_late_completion`, `test_revoked_grant_preserves_history_not_bytes`; assert same job ID, changed body 409, one simultaneous slot, higher takeover fence, rejected stale output and current ACCESS_REVOKED while execution history is immutable.
  Key assertions: `assert replayed.job_id == issued.job_id`; `assert takeover.attempt_number == first.attempt_number + 1`; `assert revoked.execution_state == "COMPLETED" and revoked.availability == "ACCESS_REVOKED"`. Synchronize threads at admission to prove the single-slot fixture admits exactly one job.
- [ ] Step 2: run `.venv/bin/python -m pytest tests/contract/test_spatial_data_jobs.py tests/replay/test_spatial_data_jobs_replay.py -q`; confirm red missing store.
- [ ] Step 3: implement append-before-projection events, scoped key SHA/fingerprint, finite indexed list/snapshot budgets, all six execution states and separate availability. Coordinator→store lock ordering only; no remote I/O under it. Frozen job/source/grant/policy/runtime digest checks are identical live/replay.
- [ ] Step 4: implement attempt acquisition idempotency, monotonically increasing fence, deadlines and durable max-attempt budget/backoff; allowlist only transient transport retry. Reserve exact owned output key/expiry and cleanup obligation before any signing I/O. Completed report retries with identical digest are idempotent; different receipt conflicts. Cancel completed/failed/expired jobs returns terminal conflict rather than erasing output/history.
- [ ] Step 5: rerun tests; add journal failure, tampered snapshots/transitions, quota restart, capability-expiry orphan and full typed-terminal failure matrices. Record passing evidence, no commit; pending/lease behavior alone is not a mounted service.

## Task 4 — Distinct auth/activation and bounded versioned storage

**Files:** modify narrowly `services/core/src/ksi_core/identity/auth.py`, `tests/contract/test_auth.py`, `tests/contract/test_oidc_route_scope.py`; create Core delivery `activation.py`, `storage.py`, `storage_s3.py`, `credential_currentness.py`; create `tests/contract/test_spatial_data_authority.py`, `tests/contract/test_spatial_data_storage.py`.
**Consumes:** Task 1 activation/runtime/policy contracts; existing AuthRegistry/OIDC verification and S3 client's checked API; Task 3 owned output targets.
**Produces:** additive principal/permission sets from spec. Public helper `resolve_bearer_principal(request:Request,token:str,*,now:datetime) -> Principal` factored from `_resolve_principal` without changing existing mode semantics. `SpatialDataCredentialCurrentness(request, token:str, expected_principal_id:str, expected_organization_id:str)` exposes `resolve(now:datetime) -> Principal`; raw token stays ephemeral/request-local, never in snapshots/logs/journals. `verify_spatial_data_activation(*,payload:SpatialDataActivationV1,signature:bytes,trusted_public_key:bytes,policy:SpatialDataPolicyV1,runtime:SpatialDataRuntimeV1,now:datetime) -> SpatialDataActivationV1` verifies Ed25519 canonical payload, distinct signature domain `ksi-spatial-data-activation.v1`, exact bindings and currentness; no key creation.

Import Task 3 `SpatialDataObjectObservation`/`SpatialDataOutputTarget`; do not create duplicate dataclasses. `SpatialDataStoragePort` in `storage.py` defines `observe_owned_output(target:SpatialDataOutputTarget) -> SpatialDataObjectObservation`, `open_version(observation:SpatialDataObjectObservation,*,chunk_bytes:int,deadline:datetime) -> ContextManager[Iterator[bytes]]`, `issue_source_get(source:SpatialDataSourceV1,attempt:SpatialDataAttemptV1,*,expires_at:datetime) -> SpatialDataSourceCapabilityV1`, `issue_output_put(target:SpatialDataOutputTarget,*,sha256:str,size_bytes:int,content_type:str,expires_at:datetime) -> SpatialDataUploadCapabilityV1`, `list_owned_versions(target:SpatialDataOutputTarget,*,limit:int) -> tuple[SpatialDataObjectObservation,...]`, `delete_owned_version(target:SpatialDataOutputTarget,version_id:str) -> None`. Capability models are Task 1 worker models and remain private transport. Adapter `SpatialDataS3Storage(*,client,bucket:str,source_key_resolver:Callable[[SpatialDataSourceV1],str],clock)` supplies them; source keys are resolved from the exact sealed reconstruction, never from public fields. No changes to old EvidenceStorage API.

- [ ] Step 1: write permissions/scope/activation-negative tests: Analysis/Processing/Edge principals get no data authority; new clients cannot call old APIs; operator allowlist includes only six data route-method pairs; new worker has singleton work permission, no role/device; wrong-org/key/domain/runtime/policy/expiry signature fails. Reauthentication proves changed/expired opaque and remapped OIDC scopes are detected.
  Assert `principal_permissions(data_worker) == frozenset({Permission.SPATIAL_DATA_WORK})` and `Permission.SPATIAL_DATA_REQUEST not in principal_permissions(analysis_client)`; wrong-domain signature must raise verification failure, never construct a usable activation.
- [ ] Step 2: write versioned-store stub tests for VersionId request/response equality, checksum FULL_OBJECT SHA-256 (base64→32 bytes), rejection of COMPOSITE/ETag/null version, bounded `.read(chunk_bytes)`/EOF and close on error, no body read at HEAD; exact checksum/type/Content-Length signed PUT. Test stale upload creates an owned orphan but cannot change pinned accepted version.
- [ ] Step 3: run `.venv/bin/python -m pytest tests/contract/test_spatial_data_authority.py tests/contract/test_spatial_data_storage.py -q`; confirm red new interfaces.
- [ ] Step 4: implement additive auth kinds/permissions and exact client route allowlists, shared resolver preserving old auth tests, activation verifier and separate S3 port with explicit connect/read/request deadlines, whole-file SHA requirements and exact version GET/delete. No SDK automatic multipart uploads, broad bucket enumeration or unbounded `Body.read()`.
- [ ] Step 5: run new tests plus `.venv/bin/python -m pytest tests/contract/test_auth.py tests/contract/test_oidc_auth.py tests/contract/test_oidc_route_scope.py tests/contract/test_analysis_resource_scope.py tests/contract/test_analysis_write_scope.py -q`; record results, no credential provisioning/commit. SDK stubs do not establish storage-provider compatibility.

## Task 5 — Mounted local Core API and worker transport

**Files:** create Core delivery `api.py`, `worker_api.py`, `capabilities.py`; create `services/core/src/ksi_core/composition/spatial_data_graph.py`; modify optional arguments/route mounts only in `composition/{app_factory.py,assembly.py,routes/external.py}`; modify `contracts/api/openapi-core.yaml`, `tests/contract/test_api_contract_sync.py`, `tests/contract/test_hostile_input_route_coverage.py`; create `tests/contract/test_spatial_data_api.py`, `tests/contract/test_spatial_data_worker_api.py`, `tests/contract/test_spatial_data_assembly.py`.
**Consumes:** Tasks 1–4 stores, exact existing Core participants and new storage/currentness/activation ports.
**Produces:** `build_spatial_data_router(*,jobs,grants,sources,downloads,clock) -> APIRouter`; `build_spatial_data_worker_router(*,jobs,storage,activation,clock) -> APIRouter`; `SpatialDataLocalGraphConfig` full injected material and `SpatialDataWiring` exact stores/ports; `build_spatial_data_wiring(*,journal,config,reconstruction,inspections,sites,work_areas,work_orders,coordinator,storage,currentness) -> SpatialDataWiring`. `downloads` remains an explicit unavailable port until Task 7, never fake bytes.

Public paths: base from spec GET(list)/POST(issue), `/{request_id}` GET(status), `/{request_id}/cancel` POST, `/{request_id}/file` GET/HEAD. Worker paths: `/v1/internal/spatial-data-jobs` GET(pending), `/{job_id}/lease` POST, `/renew` POST, `/input` GET, `/output-upload` POST, `/complete` POST, `/failure` POST. Require exact worker instance/fence on every mutation/input; client sees no capability/key/version.

- [ ] Step 1: write mounted tests for same-key 201/200 retries, exact-asset archived history, scoped owner/admin history, revoked grants vs retained metadata, EXTERNAL_AI denied independently of generic egress, caller policy/organization/URL injection 422, identical foreign-job/source 404 and dedicated-worker refusal of other lanes.
  Assert `(first.status_code,retry.status_code) == (201,200)` and `first.json()["jobId"] == retry.json()["jobId"]`; a cross-organization GET/HEAD returns `404` with the same error envelope as an unknown ID. Worker upload/complete responses contain no public storage key.
- [ ] Step 2: run `.venv/bin/python -m pytest tests/contract/test_spatial_data_api.py tests/contract/test_spatial_data_worker_api.py tests/contract/test_spatial_data_assembly.py -q`; confirm red routes/wiring.
- [ ] Step 3: implement public/worker projections and strict error map, capability expiry `min(lease,grant,activation,job deadline)` with post-I/O currentness repeat. Output reservation must be journaled before URL issuance; observed version is Core-resolved during completion, not worker-supplied.
- [ ] Step 4: add opt-in local wiring with exact participant/coordinator identity checks. Partial injected wiring is an explicit assembly error; absent wiring mounts no data route. `composition/production.py` and production config do not synthesize a graph or accept new automatic activation. Extend OpenAPI/route-sync with explicit new local graph fixtures, without weakening any existing route/security checks.
- [ ] Step 5: run new tests plus `.venv/bin/python -m pytest tests/contract/test_api_contract_sync.py tests/contract/test_hostile_input_route_coverage.py tests/contract/test_dev_assembly.py tests/contract/test_production_assembly.py -q`; assert production paths/old catalog unchanged and absent data wiring closed. Record evidence, no commit.

## Task 6 — Isolated native preparation worker and client

**Files:** create Processing Controller `spatial_data_core_client.py`, `spatial_data_worker.py`, `spatial_data_worker_config.py`, `spatial_data_sandbox.py`, `spatial_data_entrypoint.py`, `spatial_data_runner.py`; modify its `pyproject.toml` only for `ksi-spatial-data-worker` entrypoint and existing-lock metadata if required; create `tests/contract/test_spatial_data_worker.py`, `test_spatial_data_sandbox.py`, `test_spatial_data_worker_config.py`. Append bounded local instructions to owner README in this task.
**Consumes:** Task 5 authenticated worker endpoints, Task 4 activation, Task 2 primitive/geometry, existing `ExternalObjectHttpByteSource.open_bound_bytes()/put_bound_bytes()` and trusted transport policy public interfaces. Parent Core-client HTTP bearer never propagates to object endpoints or child.
**Produces:** `SpatialDataCoreClient` mirrors Task 5 worker operations with typed responses/deadlines. `SpatialDataSandboxPort.prepare(*,job:SpatialDataFrozenJobV1,source_path:Path,output_parent:Path,is_current:Callable[[],bool]) -> SpatialDataReceiptV1`; `run_once(*,core:SpatialDataCoreClient,sandbox:SpatialDataSandboxPort,transport_policy,worker_instance_id:str,clock) -> bool`; runner reads explicit owner-protected config and separate 0600 token file, no environment/default credentials.

- [ ] Step 1: write red tests for exact native DSM/ORTHO, wrong source SHA/metadata/grid, partial/all-invalid pixels, exceeded byte/pixel/workspace limits, lease loss mid-download/prepare/upload, explicit cancellation, child timeout/crash and cleanup. Assert zero completion report/partial file in every failure, no public source tags, correct modification/attribution receipt and accuracy false.
  Assert `receipt.accuracy_assessed is False`, `receipt.output_sha256 == "sha256:" + hashlib.sha256(output.read_bytes()).hexdigest()` and `core.completed_reports == []` after forced lease loss. Test memory-safe reads separately; fixture `.read_bytes()` is restricted to small test output.
- [ ] Step 2: run `.venv/bin/python -m pytest tests/contract/test_spatial_data_worker.py tests/contract/test_spatial_data_sandbox.py tests/contract/test_spatial_data_worker_config.py -q`; confirm missing interfaces.
- [ ] Step 3: implement trusted-origin bounded staging/rehash, fixed-profile child request/receipt framing, native primitive invocation, bounded renewal/currentness, output grant→exact PUT→Core completion. Use finite control JSON and typed receipt, never child stdout logs as a report. Repeat observed output SHA/size before upload; only transient allowlisted failures retry.
- [ ] Step 4: implement no-network sandbox with explicit launcher-supplied network namespace/containment proof and rlimits/process-group wall timeout; production refuses absent proof. Local fake sandbox exists only in tests; real local experiment uses verified isolation or records blocked status, never silently runs untrusted raster in Core/privileged parent. Close child/transport/private workspace in every exit, validate config/activation/token before polling and on renewal.
- [ ] Step 5: run new tests plus `.venv/bin/python -m pytest tests/contract/test_external_native_window.py tests/contract/test_external_artifact_inspections.py tests/contract/test_external_analysis_worker_loop.py tests/contract/test_production_profile_gate.py -q`; scoped Ruff/format checks and child isolation tests must pass. Record software versus host-isolation evidence, no commit/install/deploy.

## Task 7 — Guarded downloads, durable audit and orphan/retention cleanup

**Files:** create Core delivery `downloads.py`, `download_response.py`, `audit.py`, `cleanup.py`; wire Task 5 download port; create `tests/contract/test_spatial_data_downloads.py`, `test_spatial_data_asgi_stream.py`, `test_spatial_data_cleanup.py`, `tests/replay/test_spatial_data_audit_replay.py`. No old evidence retention changes.
**Consumes:** Task 3 job/output/obligation state, Task 4 pinned storage/fresh credential resolver, Task 5 router and injected currentness, explicit data policy and per-org disk/concurrency reservations.
**Produces:** `SpatialDataDownloadService.prepare(*,job_id:str,principal:Principal,credentials:SpatialDataCredentialCurrentness,now:datetime) -> SpatialDataPreparedDownload`; private spool context with exact digest/length/policy/session, `authorize(now)->Principal`, `iter_chunks()->Iterator[bytes]`, `close()`. `SpatialDataDownloadResponse(prepared,*,head_only:bool=False)` is a custom guarded ASGI Response, checks authorization/audit before http.response.start and each body send. `SpatialDataAuditStore.append(event)` requires fsync; `run_spatial_data_cleanup_once(*,jobs,storage,audit,now) -> int` resumes durably reserved exact targets/versions within cleanup limits.

- [ ] Step 1: write ASGI recorder tests for deny-before-headers after spool, revoke/remap during transfer, blocked-send deadline, disconnected client, audit append failure and unchanged Content-Length on interruption. Assert no success `http.response.start` before last preheader authorization, no completion event/trailing successful EOF after interruption, and spool/quota released on BaseException.
  Before-header denial: `assert not any(m["type"] == "http.response.start" and m["status"] == 200 for m in messages)`. Midstream denial: `assert received_bytes < expected_size` and `assert not any(m["type"] == "http.response.body" and m.get("more_body") is False for m in messages)`; no completed audit is recorded.
- [ ] Step 2: write HEAD/Range/cache/integrity tests: foreign scope remains 404 before 416; all Range forms refused; HEAD currentness with empty body and correct headers; no redirect/cache/conversion; mutated/short/long/wrong-version output yields no body. Cleanup tests cover capability still live, cancel/takeover/stale-version uploads, accepted output protection, retention expiry, delete failure/restart and no source-key deletion.
- [ ] Step 3: run `.venv/bin/python -m pytest tests/contract/test_spatial_data_downloads.py tests/contract/test_spatial_data_asgi_stream.py tests/contract/test_spatial_data_cleanup.py tests/replay/test_spatial_data_audit_replay.py -q`; confirm red new services.
- [ ] Step 4: implement bounded full-hash spool before response, current authorization outside locks during I/O then repeated under coordinator, audit start persisted before bytes; guarded ASGI send path with explicit stream deadline/backpressure/disconnect and finally cleanup. Headers: safe server filename, `private, no-store`, `nosniff`, exact length, output digest; no generator-only preheader check or FileResponse implicit Range behavior. Sent-byte audit means bytes handed to ASGI send, not proof received by client.
- [ ] Step 5: implement cleanup only after upload-capability expiry, with durable ownership/fence/retention checks and version-bound delete. Bounded owned-key enumeration/pagination fails visibly if budget exceeded; accepted pinned versions survive orphan cleanup; stale additional versions never become downloadable. Retry deletion within policy, terminal cleanup degradation visible.
- [ ] Step 6: rerun all Task 7 suites plus Tasks 3/4/5 suites, scoped Ruff/format checks; require raw ASGI tests and replay evidence as well as TestClient behavior. Record results, no commit; bounded in-flight exposure remains explicitly documented.

## Task 8 — Mounted consumer, public-file experiments and regression audit

**Files:** create `tests/contract/spatial_data_http_fixture.py`, `tests/contract/test_spatial_data_http_integration.py`, `tests/replay/test_spatial_data_delivery_replay.py`; create `tools/verify_spatial_data_public_sample.py`, `examples/spatial-data/native_window_client.py`, `docs/ops/SPATIAL_DATA_LOCAL_VERIFICATION.md`. Update Core/Processing READMEs and this ledger with actual observed results/limits only. Do not alter product-state/slice status.
**Consumes:** Tasks 1–7 common HTTP flow and genuine existing inspector lane; licensed Floreat originals/hashes from spec. Consumer imports no Core stores or workspace fixture helpers, only HTTP/JSON and local file metadata comparison.
**Produces:** opt-in verifier CLI `--manifest PATH --core-url URL --token-file PATH --policy-file PATH --output-dir PATH` plus explicit pre-inspected sealed asset references; verifies file hashes/license metadata and requests fixed finite native rectangles. Missing files, authority, inspection or isolation returns typed nonzero blocked result, not synthetic replacement. Core owns grants/authority; CLI cannot mint them.

- [ ] Step 1: write failing mounted integration/replay tests with small real synthetic GeoTIFFs, local loopback transports and explicit test authority. Assert POST→lease/prepare/accept→status→GET bytes, independent affine/pixel/source/output hash/NoData checks, same IDs after restart and all receipt/rights/error parity. No fabricated MEASURED report: run actual parser/inspection code for fixtures.
  Assert `file_response.status_code == 200`, `len(file_response.content) == receipt["outputSizeBytes"]`, `"sha256:" + hashlib.sha256(file_response.content).hexdigest() == receipt["outputSha256"]`; independently opened output affine/bounds/mask equal the receipt and expected source pixel slice. Mounted fixture remains local software evidence, not host or customer proof.
- [ ] Step 2: run `.venv/bin/python -m pytest tests/contract/test_spatial_data_http_integration.py tests/replay/test_spatial_data_delivery_replay.py -q`; confirm absent client/harness or flow failure before implementing harness/client.
- [ ] Step 3: implement HTTP-only consumer and opt-in public-file verification. Full originals must run through existing pinned inspector/containment path before source admission; the internal function's “synthetic” name alone is not evidence of production containment. Record a profile rejection without changing parser policy to make this sample pass. Retain ORTHO declared 2cm versus observed 2.5cm and unknown height reference.
- [ ] Step 4: run mounted suites and `.venv/bin/python -m pytest tests/contract/test_spatial_data*.py tests/contract/test_external_native_window*.py tests/replay/test_spatial_data*.py -q`; inspect count/skips/failures. Then run prior inspector/ingress/catalog/auth/Analysis regression and contract-sync suites named above, scoped Ruff/format and `git diff --check`. Run broader tests only after freezing exact delta; no count copied from Codex.
- [ ] Step 5: execute public verifier only with approved explicit local grants/policy and verified containment already available; do not install host/credentials to unblock it. Record full-file inspection/preparation, output checks, peak RSS/workspace/CPU/elapsed/output bytes and policy in `.opencode/artifacts/spatial-data-delivery-20260930/`. If blocked, keep that acceptance item open. No network prerequisite in ordinary CI.
- [ ] Step 6: independent read-only security/code review of frozen delta and evidence, then integrate exact reviewed files after rechecking main baseline. This reviewer is authorized only by the chosen execution workflow; no parallel writers. Publish remaining limitations and checkpoint, no commit/deploy/release or customer acceptance claim.

## Coverage and handoff audit

| Spec sections | Owning tasks |
| --- | --- |
| §1/2 scope, public sample, boundaries | T1/T2/T8; no MCP/UI successor hidden in this plan |
| §3 rights/principal/activation | T1/T2/T4/T5; provisioning/production/AI-use policing remain explicit exclusions |
| §4 exact identities, geometry, idempotency | T1/T2/T3/T5; no new spatial asset ID or WorkArea numeric revision |
| §5 durable worker/report/recovery | T3/T4/T5/T6/T7 |
| §6 receipt, authenticated download | T1/T4/T5/T7/T8; revoked history remains visible, bytes denied |
| §7 resource/audit/cleanup/errors | T1/T3/T4/T5/T6/T7/T8; numeric operational policy remains a measured acceptance gate |
| §8 invariants/acceptance, §9 rollback | Every task's constraints/tests; T8 integration and final evidence audit |

Self-review: model/signature/task dependencies align; T3 owns storage-observation/target value types, T4 adds I/O, and no Task 3 test requires a future adapter. Core performs no raster I/O; worker never imports Core stores. Five Review Focus inputs have explicit owning tests. No placeholder decisions or silently approved production values.

Execution recommendation: **Native**, one primary implementer and a final independent read-only review; tightly coupled job/grant/storage interfaces and dirty WIP favor serialized ownership. The Human may instead choose subagent-driven task-by-task work in isolated worktrees. Do not spawn agents until the execution method permits it. In either approach, checkpoint at semantic milestones and record real red/green evidence before ticking task steps.

## Current verified baseline and approvals

- [x] Human approved written spec on 2026-09-30; WorkArea digest clarification reflects existing immutable-ID behavior, not a schema change.
- [x] Plan grounded in current code and inline self-reviewed.
- [ ] Human reviews this written plan and selects/approves execution method.
- [ ] Tasks 1–8 implemented and verified; no task currently completed.

Design baseline/evidence: `.opencode/artifacts/spatial-data-delivery-design-20260930/` (2,203 unchanged pre-existing files in prior design task). Planning baseline: `.opencode/artifacts/spatial-data-delivery-plan-20260930/` (2,205 files before plan edits; HEAD 9edc4a18e873). Public sample local acquisition evidence: `.opencode/artifacts/spatial-public-sample-20260930/sample-evidence.md`; temporary originals are not committed or required runtime files.

Observed toolchain during planning: FastAPI 0.140.0, Starlette 1.3.1, Pydantic 2.13.4, boto3/botocore 1.43.63. Local StreamingResponse source sends response.start before iterating; local S3 model exposes VersionId and ChecksumType FULL_OBJECT/COMPOSITE. Current documentation was queried for those two boundaries; revalidate lock/runtime at implementation. No product tests or sample inspection were run in this planning task.

Next: Human plan review + method; then `using-git-worktrees` and selected execution skill, preserve main/candidate bytes, begin Task 1 red tests. No native execution goal created.

## 2026-10-02 approved recovery and selective integration — latest execution state

The earlier status/unchecked steps above are the preserved planning-time record, not the
latest runtime state. The Human approved permanent native recovery on 2026-10-01, local
milestone commits, continuous completion, and conditional selective integration. This
append preserves the entire original main planning document; no unrelated WIP is committed.

Canonical detailed execution/rulings ledger and durable evidence are in the preserved
`.worktrees/spatial-data-delivery-recovery-20261001/` checkout under this same task-ledger
path and `.opencode/artifacts/spatial-data-delivery-recovery-20261001/`. Its branch is
`feat/spatial-data-delivery-recovery-20261001`, latest implementation/repair commit `c1ab254`.

- T1–T7 local software implemented and verified with observed RED→GREEN and real journal,
  contract/replay/negative/scoped/static/full checks. T8 generated TIFFs pass the genuine
  inspector, distinct child's native preparation, actual loopback GET/PUT, Core acceptance
  and HTTP-only consumer; pixels/masks/NoData/affine/bounds/CRS/hashes/restart/rights checked.
- Independent whole-branch read-only review of `9edc4a1..2850619` completed; its Important
  real-credential denial audit/status issue reproduced in nine cases and fixed RED→GREEN
  in `c1ab254`. Two minors remain deferred (global download cap naming and trusted UUID regex).
- Recovery full: **7781 passed, same 10 failed, 127 skipped, 92 warnings**. Corrected frozen
  combined candidate full: **8123 passed, same 10 failed, 127 skipped, 93 warnings**. Exact
  failure IDs remain the private-bus positive precondition and nine absent pinned official
  PSDK KMZ cases. Not a green whole suite; no tests/security checks weakened.
- Main received only the context-checked task patch: **78 new files +19 existing-file edits**.
  All candidate100 task bytes equal main; the initial post-application audit found all216
  unrelated baseline files unchanged, HEAD `9edc4a18e873` and empty index preserved, no
  unexpected paths. Existing main Analysis/OIDC/V2/catalog/policy and legacy local-report
  semantics were explicitly preserved. This execution-state append is the only subsequent
  planned baseline-document change; original bytes must remain an exact prefix.
- Actual main `-I` imports resolve Core/Processing/contracts/MCP from main. Main task Ruff,
  89-file formatting (two inherited owner-test styles excluded), inventory173, four-source
  mypy and diff checks passed. Main combined data/Analysis/MCP/OIDC/catalog/owner/contract
  regression: **1585 passed, 48 warnings**, 363.67s. Exact argv/output is retained in recovery.
- Actual-main whole-suite result: **8138 passed, 1 inherited private-bus failure, 121 skipped,
  93 warnings**, 771.41s after the bounded context/environment repair below. Final task audit
  records local technical completion, not a green whole suite or product acceptance.
- Actual main public CLI returned exit2 / `PUBLIC_ORIGINAL_UNAVAILABLE`, created no output.
  Floreat full originals/isolated decode/pixel comparison/resources remain BLOCKED. Actual
  host/image/namespace/UID/SDK/provider acceptance, cross-process operations/backup/deployment,
  customer Terra exports/rights/two survey cycles/independent reuse, remote CI and customer
  acceptance remain UNVERIFIED. No production data activation/policy was provisioned.
- No push, Git merge/main commit, deployment, dependency installation, credential provisioning,
  customer contact, reference edits or destructive cleanup. Recovery/candidate evidence is
  retained. EXT-VAL/product-state/slice acceptance are unchanged; software evidence is not
  product acceptance. See `docs/ops/SPATIAL_DATA_LOCAL_VERIFICATION.md` for usage/rollback.

### Actual-main full-envelope correction
- First actual main full: **8136 passed, 3 failed, 121 skipped, 93 warnings**, 772.55s.
  Main already has local vendored PSDK/official samples unlike the isolated candidate; no
  acquisition/update/install was performed. Recovery's missing-KMZ failures cannot be assumed
  on main. Remaining failures were existing private-bus, DPK under test-child umask077, and
  dev assembly in new `.worktrees` build context. No extra failure was silently waived.
- Vendor build uses ordinary mkdir for DEBIAN; child-local umask022 resolves packaging without
  editing vendor/scripts/fixtures or loosening protected-directory/credential checks: **43 passed**.
- Existing production scanner observed RED with six new nested worktree paths. Minimal
  `.dockerignore` worktree/agent-evidence exclusions restore its boundary; actual production
  profile/DPK/official-sample gate: **32 passed**, 11.78s. Same guard bytes in recovery,
  candidate and main, separately recorded by `main-integration-build-context-fix.json`.
  Original task100 source freeze/patch preserved; this is an additional build-context repair,
  not a source-authority or deployment change. Corrected main full under022 completed:
  **8138 passed, 1 failed, 121 skipped, 93 warnings**, 771.41s; sole failure is existing
  `test_private_bus_rejects_hard_link_and_detects_substitution`. No new failures remain.

### Local technical closure / open acceptance
- Same final umask022 combined data/Analysis/MCP/OIDC/catalog/owner/contract gate:
  **1585 passed, 48 warnings**, 363.63s. Existing local official-KMZ cases pass on main;
  missing-asset failures remain only in isolated recovery/candidate envelopes.
- Minimal guard committed alone in recovery as `838ed80691489471b1d6914b5ad2f14014efbe11`.
  Main HEAD/index/WIP remain uncommitted and preserved. Frozen candidate100 task bytes,
  separate guard, main ledger original prefix and other215 baseline files verified; no
  unexpected new paths. Full audit: recovery evidence `final-completion-audit.json`.
- Authorized T2–T8 local engineering/review/selective integration is technically complete.
  Public originals/isolated pixels/resources, actual host/image/namespace/provider/SDK,
  deployment/backup/cross-process operations, customer Terra/rights/two survey cycles/
  independent use, remote CI and customer acceptance remain OPEN/UNVERIFIED. Product-state
  and EXT-VAL acceptance unchanged. No next-slice authorization inferred.
- No push/deploy/install/credential provisioning/customer contact/reference edits/cleanup.
  Recovery/candidate/SDD evidence retained. Two review minors and 52 rulings/costs remain in
  the detailed recovery ledger and its final-rulings-and-deferred-minors.json audit.
