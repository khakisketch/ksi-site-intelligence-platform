# Spatial Data MCP V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A dedicated permissioned stdio client discovers granted DSM/ORTHO assets, prepares an exact native rectangle, resumes the durable Core job and gives an independently authenticated HTTP consumer a safe file reference.

**Architecture:** Core owns all authority, source/grant currentness and existing jobs/worker/downloads. Add a distinct AI principal, guarded metadata responses and grant-filtered data discovery without changing generic V1 history. A new local stdio process exposes six typed HTTP operations and no raster bytes, listener, calculation or credential provisioning.

**Tech Stack:** Existing Python3.12, FastAPI/Pydantic, HTTPX and installed official mcp2.2.0; current generated TIFF inspection/preparation harness; no new external dependency/version upgrade.

**Spec:** `docs/superpowers/specs/2026-10-06-spatial-data-mcp-v1-design.md`, Human-approved original snapshot204c90a/SHA7ef7a677 on2026-10-06 (“명세 승인, 구현 계획 작성”).

## Global Constraints

- Existing generic Spatial Data V1, Analysis V1/V2, Analysis MCP and Copilot permissions/history remain unchanged.
- Native-grid rectangular DSM/ORTHO only; no Range, reprojection/resampling, polygon mask, storage keys, bytes/base64 in MCP, remote listener, recipient-sharing or accuracy claims.
- `SPATIAL_DATA_MCP_CLIENT`: no role/device, nonempty immutable Site and WorkArea scopes; SPATIAL_DATA_READ/REQUEST only; eight exact route-method pairs.
- Core infers EXTERNAL_AI from identity; reject GENERAL_DATA_USE rather than rewrite it. Successful AI responses require `X-KSI-Spatial-Data-AI-Egress: ALLOWED`.
- Current AI consent and exact current READ grant protect metadata as well as bytes; exact frozen job grant cannot be resurrected by a replacement grant.
- Grant-filtered native source projection contains only spec§4 fields. Unknown vertical reference remains null/explicit limitation, not a universal raster-delivery denial.
- Owner-protected explicit config JSON and separate absolute0600 token file; no bearer environment/CLI/config/tool input, ambient proxy, redirect, public HTTP or TLS weakening.
- Finite owner-supplied limits; fixture limits are generated-test values, not production SLA or inherited Analysis quotas.
- Only generated owned TIFFs may be decoded in the approved local harness; customer exports, containment, deployed host, AI-host installation and customer acceptance remain separate.
- No dependency install/sync, live grant/consent/credential issuance, push/PR/deploy/signing/host changes. Existing checked-out main is the sole writer; preserve all retained worktrees.

## Review Focus

1. A token or consent revoked after handler construction but before metadata headers must yield no protected success (Task2 barrier tests).
2. Rights narrower than a pixel or two overlapping grants must not union bounds or advertise unauthorized preparation (Task3 discovery tests).
3. A valid DTO for the wrong asset/job/Site must be refused, including queued/no-receipt results (Task4 substitution tests).
4. Lost create response plus adapter/Core restart must preserve one job/key, not invent a retry identity (Task5 replay/SDK tests).
5. Compressed/duplicate/overlarge JSON, canceled reads and concurrent calls must not leak data, stderr exceptions or resource reservations (Task4 transport/stdout tests).

---

## Declaration and ownership

Status: HUMAN-APPROVED PLAN, subagent-driven execution selected; unchecked steps are not runtime evidence.
Approval2026-10-06: Human selected “계획 승인·단계별 에이전트” for d0aac56/SHAc9efd74e.
Reviewed plan body is preserved below; no new external-effect/install authorization.
Task ID: SDP-CLIENT-01-AI; parent ledger `2026-10-06-spatial-data-product-continuation.md`.
Base/integration target: main204c90a, one in-place writer; record actual execution base after documentation commit. No isolation needed absent a concurrent writer/user-checkout conflict.

```text
Requirement IDs: SDP-REQ-01/02/03/05/06/07/08; SDP-CLIENT-01-AI spec§1–9.
Owner module: Core external delivery/identity/composition; new services/spatial-data-mcp stdio lifecycle.
Acceptance criteria: spec§8 ten cases, mapped below; real generated SDK→HTTP→worker→receipt→consumer.
Contracts affected: additive discovery/MCP schemas, AI identity and ack; existing data-job shapes unchanged.
Reference assets: actual Core V1/source/grants/currentness/downloads; Analysis low-level MCP as reference only.
Adoption decisions: reuse exact authority/byte transport; no reference imports, second engine or Analysis widening.
Files to change: exact map and task files below; no visual UI, production activation or device implementation.
Tests: TDD scoped contracts, genuine generated parser/preparation HTTP, official SDK stdio, replay, independent full/static.
HIL or real-device assumptions: none for local software; hardware/vendor/customer/host acceptance not claimed.
License/data implications: explicit generated rights; projected attribution/provenance retained, no actual license verification inferred.
Rollback: disable new adapter/AI-discovery mount or task-owned revert; preserve all existing journals/results/grants/Analysis.
```

Invariant enforcement: INV020/024 via observed coordinates/declared timestamps/accuracy=false/unknown fields;
INV040 via no fixture imports/default-closed assembly; INV043/050 via exact grant/license digest/purpose/location/consent;
INV051/053 via unchanged source and quantitative authority; INV054/055 via unchanged worker/image/resource-policy bindings;
INV060 via scope/ownership404 and all source-area checks; INV061 via closed six-tool/eight-route boundary with no Copilot/flight elevation.

## File map (existing exact paths inspected at204c90a)

| Unit | Files and responsibility |
| --- | --- |
| Shared strict DTOs | NEW `packages/event-contracts/src/ksi_event_contracts/spatial_data_ai.py`; NEW `contracts/schemas/spatial-data-ai.v1.json`: safe metadata, file reference, MCP wrapper and AI-specific error |
| Identity | MODIFY `services/core/src/ksi_core/identity/auth.py` enum/record validation/permissions/allowlist; no edits to legacy alias `ksi_core/auth.py` |
| Grant/source seams | MODIFY `services/core/src/ksi_core/domains/external/delivery/{grants,source}.py`: explicit metadata grant selection and bounded source candidate access without geometry shortcuts/ADMIN |
| Bounded catalog seam | MODIFY `services/core/src/ksi_core/domains/external/ingress/spatial_asset_catalog.py`: optional item/serialized-byte budgets checked before candidate accumulation; old caller semantics unchanged |
| Durable job boundary | MODIFY same delivery `jobs.py`: AI-only gate before views/mutations and filter before page selection, preserve worker/replay/generic branches |
| Publication/audit | NEW same delivery `ai_egress.py`, `metadata_response.py`, `metadata_audit.py`: response-bound final checks and bounded append-only metadata access audit; old byte audit events unchanged |
| Additive AI error | MODIFY same delivery `errors.py`: separate `SpatialDataAiDomainError` carrying only the new closed reason union/status; old domain-error constructor and envelopes unchanged |
| Discovery | NEW same delivery `asset_discovery.py`, `asset_api.py`: native projection, filtered snapshot cursor and two routes |
| Existing API/byte ack | MODIFY same delivery `api.py`, `download_response.py`: fresh AI response publication and ack after byte authorization; no new download engine |
| Assembly/OpenAPI | MODIFY `services/core/src/ksi_core/composition/spatial_data_graph.py`, `composition/routes/external.py` and `contracts/api/openapi-core.yaml`: exact participants and additive route/model documentation |
| Dedicated adapter | NEW `services/spatial-data-mcp/{README.md,pyproject.toml,src/ksi_spatial_data_mcp/{__init__,config,tool_models,core_client,server}.py}`: independent local stdio lifecycle |
| Workspace metadata | MODIFY root `pyproject.toml`, `uv.lock`: additive workspace/leaf membership only, no third-party version/source/hash drift or installation |
| Tests/fixture | NEW `tests/contract/{spatial_data_mcp_fixture,test_spatial_data_ai_contracts,test_spatial_data_mcp_identity,test_spatial_data_ai_egress,test_spatial_data_asset_discovery,test_spatial_data_mcp_config,test_spatial_data_mcp_client,test_spatial_data_mcp_stdio,test_spatial_data_mcp_http_integration}.py`; NEW `tests/replay/test_spatial_data_mcp_replay.py` |
| Product example/docs | NEW `examples/spatial-data/mcp_native_window_workflow.py`; MODIFY `docs/ops/SPATIAL_DATA_LOCAL_VERIFICATION.md`, `services/core/README.md`, `REPOSITORY_STRUCTURE.md` service table; this plan/parent ledger/checkpoint |

Use nearest Core README (no delivery README exists), event-contracts README/pyproject and inspected Analysis README/entrypoint; no nested services/event-contracts agent rules found. Contract tests follow existing flat fixture imports. No source access to private .dev-data, provider credentials or reference repositories is required.

## Task 1: Add strict AI contracts and isolated identity

**Files:** new shared DTO/schema and `test_spatial_data_ai_contracts.py`, `test_spatial_data_mcp_identity.py`; modify canonical auth.py. Do not widen old permissions or change V1 job/request/receipt models.

**Interfaces:**
- Consume existing `_spatial_data.{SpatialDataModel,AssetRef,Digest,Bounds,Coordinate,Text,UtcTimestamp}` and `spatial_data.{JobId,Transform,SpatialDataJobViewV1,SpatialDataReasonV1}`.
- Produce `SpatialDataAssetViewV1`, `SpatialDataAssetPageV1`, `SpatialDataFileReferenceV1`, `SpatialDataMcpJobViewV1`, `SpatialDataAiErrorV1`, `SpatialDataMcpErrorV1` in spatial_data_ai.py.
- Identity exposes new `PrincipalKind.SPATIAL_DATA_MCP_CLIENT` through unchanged `principal_permissions`, registry validation and route-bound `require_principal`.

Exact projection fields (camelCase aliases): assetRef/siteId/workAreaId/workOrderId/epochId/submissionRef/revision/artifactKind/lifecycleState;
observedSha256/observedSizeBytes/inspectionReportDigest/inspectorBuildDigest;
observedCrsIdentifier/observedCrsDigest/observedCrsUnits/observedVerticalReference;
transform/resolution/bandCount/dtype/permittedBounds;
captureStartedAt/captureEndedAt/producerProcessedAt/declarationRecordedAt/timestampProvenance;
permittedOperations/restrictions/attribution/modificationNotice/accuracyAssessed/analysisStatus.
Use V1 source/receipt types/semantics; lifecycle SEALED|SUPERSEDED; timestampProvenance=SUBMISSION_DECLARATION;
accuracyAssessed is strict false, analysisStatus=NOT_EVALUATED; nullable declared times/vertical;
unique READ/PREPARE, restrictions use closed existing reason codes. No full source dimensions/extent/nodata payload required by this projection.
Page items max200, nextCursor null or strict nonempty≤2048chars. Runtime policy may impose smaller limits.
AI-specific error envelope has safe fixed message/retryable/remediation and reason existing SpatialDataReasonV1
or `SPATIAL_DATA_CURSOR_STALE`; do not extend old V1 reason enum/journal.
File descriptor fields exactly spec§5, canonical existing scope/job `/file` route; wrapper `{job,fileReference}`.
MCP-only error model `{code,remediation}` is closed, remediation uses existing bounded safe values;
code is the union of Task4's exact adapter codes and AI/Core reasons. Output-schema generation
advertises object-root success-or-error alternatives, not an arbitrary JSON result. HTTP success
response models never include the MCP error alternative; HTTP errors use SpatialDataAiErrorV1.

- [x] Step1 — Write RED tests: `test_ai_models_schema_concordance` asserts closed shapes and V1 output immutability; `test_file_reference_matches_authorized_job` rejects descriptor scope/digest/size/path mismatches and descriptor on non-AVAILABLE; `test_ai_identity_exact_routes` asserts exactly existing six data routes plus two discovery GETs, no Analysis/catalog/internal/global/flight routes; `test_ai_identity_requires_explicit_scope` rejects null/empty/mutable/bad path/role/device.
- [x] Step2 — Run `.venv/bin/python -m pytest tests/contract/test_spatial_data_ai_contracts.py tests/contract/test_spatial_data_mcp_identity.py -q`; expect new DTO/identity assertion failure before implementation, not malformed fixture failure. Preserve genuine RED output.
- [x] Step3 — Implement the six DTOs and isolated enum/validation/permission/allowlist branch. Validate reference-derived cross-field facts with the same native V1 source/receipt semantics; schema arrays/booleans/nonfinite/unknown fields match model acceptance. Add generated schema using existing `models_json_schema` pattern (schema generator can be test-local; do not hand-edit a contradictory schema).
- [x] Step4 — Run new tests plus `tests/contract/test_spatial_data_permissions.py tests/contract/test_analysis_mcp_identity.py tests/contract/test_spatial_data_contracts.py`; expect pass, old permissions/routes unchanged. Scope/schema cases include booleans/numeric strings, bounds reversal, traversal/controls, wrong revision/asset/job/digest and false accuracy claims.
- [x] Step5 — Review exact diff/index and local commit only Task1 files after scoped/static checks; record command/results in this ledger. No activation/provisioning.

## Task 2: Enforce current AI metadata rights at the actual response boundary

**Files:** new ai_egress.py/metadata_response.py/metadata_audit.py and `test_spatial_data_ai_egress.py`; modify errors.py/grants.py/source.py/jobs.py/api.py/download_response.py/spatial_data_graph.py. Sequential single writer across these files.

**Interfaces:**
- `SpatialDataSourceResolver.require_ai_scope(site_id:str,work_area_id:str,principal:Principal)->WorkArea`: genuine scope+current consent before enumeration, no exposed source.
- `SpatialDataGrantAuthorizer.select_metadata_current(*,source:SpatialDataSourceV1,principal:Principal,policy:SpatialDataPolicyV1,now:datetime)->SpatialDataGrantV1`: exactly one current EXTERNAL_AI+READ beneficiary/source grant, policy/location/CRS/license-digest binding; no native pixel expansion for metadata itself.
- `SpatialDataJobStore.require_ai_metadata(*,job_id:str,principal:Principal,now:datetime)->SpatialDataJobViewV1`: scoped owner/EXTERNAL_AI, `_lane`, locally current exact source/frozen grant via READ, explicit grant equality, then existing view; no mutation merely to label denial.
- `SpatialDataMetadataAuditStore(journal:DurableJournal,*,policy:SpatialDataPolicyV1)`; `append(*,principal:Principal,site_id:str,work_area_id:str,operation:str,payload_digest:str|None,reason:SpatialDataReasonV1|None,now:datetime)->None` records only permitted operation, scope/identity, digest, time and safe reason. No body/URL/token/raw cursor/idempotency key/file path. Events use new private `spatial-data-metadata-audit.v1` journal, not old byte-session events.
- `SpatialDataAiEgress(jobs,sources,grants,audit,clock)` verifies exact same coordinator/participants; `prepare_job_response(*,credentials:SpatialDataCredentialCurrentness,site_id:str,work_area_id:str,view:SpatialDataJobViewV1,status:int,operation:str)->Response` returns guarded pre-header metadata response. Discovery/page preparation is added by Task3.
- `SpatialDataAiDomainError(reason:SpatialDataAiReasonV1,status_code:int,retryable:bool=False)` in errors.py supports the new closed reason union defined beside AI DTOs; catch/serialize it explicitly on AI paths, never through the old V1 error model. Shared old domain refusals still map to unchanged typed reason values.

For audit, operation is a validated literal LIST_ASSETS/GET_ASSET/CREATE_JOB/LIST_JOBS/GET_JOB/CANCEL_JOB,
not free text. Sequence/event digest/UTC-time plus typed reason/payload digest obey replay; event count
is capped by policy.max_pending_records*max_list_records and serialized audit projection by
max_snapshot_bytes, event by max_json_bytes. This separate journal does not imply remote archival.
`metadata_response.SpatialDataAiMetadataResponse` owns bounded ASGI pre-header refresh/recheck/audit;
`ai_egress` owns the typed authorization closures; neither accepts caller-produced Principal authority.
Use AI-specific error envelope on new identity routes so cursor stale/snapshot conflict can be typed
without modifying SpatialDataReasonV1. Existing byte errors and generic errors remain V1.

- [x] Step1 — RED tests `test_revoked_ai_metadata_denied_but_generic_history_survives`, `test_ai_general_job_and_purpose_header_downgrade_refused`, `test_replacement_grant_cannot_resurrect_job`, `test_cancel_checks_ai_read_before_append`, `test_consent_or_token_revoked_between_handler_and_headers`, `test_audit_seal_or_limit_refuses_metadata`. Assert no success ack, protected JSON, duplicate job/cancel event or forged generic read; test unknown/foreign paths return identical404.
- [x] Step2 — Run `.venv/bin/python -m pytest tests/contract/test_spatial_data_ai_egress.py -q`; expect failing AI authorization/response assertions.
- [x] Step3 — Permit new kind in exact data source/grant/job scope helpers while preserving all old-kind branches. Reject non-AI purpose early on issuance and require READ plus PREPARE on new AI jobs/retries. Gate get/cancel/file even when retention/availability makes bytes unavailable; AI metadata validity is independent of completed file availability. AI filter predicate in `jobs.list` executes before slicing/cursor and never swallows dependency/resource failures as empty success. Unknown or denied direct reads return safe errors only.
- [x] Step4 — Implement final metadata response: refresh request credential off coordinator locks; then guarded local source/grant/consent/lane recheck and bounded serialization/audit append; repeat after audit immediately before response headers. Never hold coordinator during remote auth or awaited ASGI sends. Compare exact protected projection digests if state changed; fail409/refuse rather than send stale metadata. Acknowledgment appears only on this successful AI response; generic routes keep existing JSONResponse behavior. Existing download ASGI response adds AI ack only after `prepared.authorize`, continues current chunk authorization and never adds ack to error responses.
- [x] Step5 — GREEN new tests plus `test_spatial_data_jobs.py test_spatial_data_api.py test_spatial_data_current_grants.py test_spatial_data_real_credential_audit.py test_spatial_data_asgi_stream.py test_spatial_data_assembly.py`; assert legacy grant-revoked history, leases/fences/cleanup/download audit and no-spool/default-closed assembly remain unchanged. Barrier test covers revocation after initial/audit checks and before header send; disclose remaining in-process handoff/revocation window, never claim recall of sent bytes.
- [x] Step6 — Local commit Task2 source/tests after scoped/static pass. New private audit replay checks exact sealed digest/sequence/limits; unavailable/sealed/corrupt history is fail-closed, not truncated. No new public audit/provisioning endpoint.

## Task 3: Add current grant-filtered source discovery with snapshot pagination

**Files:** new asset_discovery.py/asset_api.py and `test_spatial_data_asset_discovery.py`; modify source.py/grants.py, ingress/spatial_asset_catalog.py, composition/spatial_data_graph.py/routes/external.py, openapi-core.yaml; extend ai_egress.py and metadata_response.py.

**Interfaces:**
- `SpatialDataSourceResolver.candidates(*,site_id:str,work_area_id:str,principal:Principal)->tuple[SpatialAssetCatalogItemV1,...]`: bounded authentic existing catalog candidates, data scope not SITES_READ; no ADMIN stand-in; reuse catalog budgets.
- `SpatialAssetCatalog.items(site_id,work_area_id,principal,*,max_items:int|None=None,max_bytes:int|None=None)` adds explicit finite accumulation checks for this lane; callers omitting new optional budgets retain existing behavior. Resolver passes policy.max_list_records/max_snapshot_bytes.
- `SpatialDataSourceResolver.resolve_candidate(*,candidate:SpatialAssetCatalogItemV1,principal:Principal)->SpatialDataSourceV1` avoids repeating the whole catalog for every page item. Candidate is only a hint; re-resolve exact scoped revision/manifest/report from genuine stores, use existing `_build`/`require_current`, not DTO equality as authority.
- `SpatialDataAssetDiscovery(sources,grants,jobs,*,clock)`; `get(*,site_id:str,work_area_id:str,asset_ref:str,principal:Principal,now:datetime)->SpatialDataAssetViewV1`; `list(*,site_id:str,work_area_id:str,principal:Principal,limit:int,cursor:str|None,now:datetime)->SpatialDataAssetPageV1`.
- `build_spatial_data_asset_router(*,discovery:SpatialDataAssetDiscovery,egress:SpatialDataAiEgress,clock)->APIRouter` exposes only two spec§4 GET routes under new AI identity, READ permission.
- Add `prepare_asset_response` / `prepare_asset_page_response` / `prepare_job_page_response` to egress using same request credentials/final audit and typed view/page contracts; no generic publication callback that could skip authorization.

- [x] Step1 — RED tests `test_discovery_filters_before_page_and_does_not_leak_counts`, `test_cursor_scope_and_current_projection_staleness`, `test_read_only_grant_and_subpixel_bounds_do_not_advertise_prepare`, `test_ambiguous_grants_are_not_unioned`, `test_ortho_unknown_vertical_and_superseded_exact_asset`, `test_catalog_budget_failure_is_not_empty_success`, `test_discovery_mount_requires_exact_graph`, `test_discovery_ack_rechecked_at_send`.
- [x] Step2 — Run `.venv/bin/python -m pytest tests/contract/test_spatial_data_asset_discovery.py -q`; expect missing route/projection/assertion failures, with real generated Core sources/grants.
- [x] Step3 — Implement projection solely from authentic current source and unique metadata grant. Bounds=`intersection(grant.allowed_bounds,measured source affine extent)`; omit empty intersection, unmeasured/unsupported/ungranted/ambiguous list assets. Detail unknown/foreign/ungranted404; current ambiguity403 with AMBIGUOUS_GRANT and no payload. Never parse TIFF in Core or fake raster request over whole source to authorize metadata. READ-only grant remains listed, PREPARE absent. PREPARE advertisement requires permit operation, current lane and at least one whole native cell within authorized bounds; no guarantee that an arbitrary rectangle/masked sample succeeds.
- [x] Step4 — Implement scoped beneficiary index lookup (not global grant scan), bound examined grant versions by policy.max_list_records and candidate/source snapshots by existing catalog budgets plus policy.max_snapshot_bytes/max_json_bytes/max_pending_records. No new policy defaults. Page limit≤min(200,policy.max_list_records), default1; cap candidate work before materialization. Resolve remote inspection-authority preflight outside guarded final publication. Propagate dependency/representation503 rather than mask it as denied/empty.
- [x] Step5 — Implement opaque strict cursor `{scope,snapshot,last}`: scope hashes org/principal/Site/area, snapshot hashes sorted permitted projection IDs/digests and relevant current grant/consent bindings, last is the filtered assetRef/jobId. Bind checks every page; changed snapshot409/SPATIAL_DATA_CURSOR_STALE. Invalid encoding/shape/scope422; no token/coordinate/grant ID in raw cursor. No HMAC authority assertion; a cursor never grants access. AI job-list variant shares snapshot/currentness rules without modifying generic V1 cursor semantics.
- [x] Step6 — GREEN new discovery tests plus `test_spatial_data_source.py test_spatial_data_catalog_adoption.py test_spatial_data_catalog_prerequisites.py test_spatial_data_api.py test_spatial_data_assembly.py`; verify exact OpenAPI/model/schema aliases/bounds and no conflicting leaf schemas. Add discovery/egress/audit exact participant checks and mount only via existing opt-in graph; missing graph means routes absent, partial/wrong graph refused. Generic catalog and old data/Analysis APIs unchanged.
- [x] Step7 — Local commit Task3 files after scoped/static pass. No policy/activation/production config changes. Record closed versus future customer-load limits in ledger, not as measured performance.

## Task 4: Implement the closed local stdio adapter

**Files:** dedicated adapter package files, root pyproject.toml/uv.lock, new `test_spatial_data_mcp_config.py`, `test_spatial_data_mcp_client.py`, `test_spatial_data_mcp_stdio.py`, fixture module. No edits to services/analysis-mcp.

**Interfaces:**
- `AdapterConfig.from_file(path:Path)->AdapterConfig`; `read_token()->str`; config fields coreOrigin/tokenFile and required positive finite maxRequestBytes/maxStructuredResponseBytes/maxConcurrentCalls/maxIdentifierBytes/maxCursorBytes/maxTokenBytes/maxConfigBytes/connectTimeoutSeconds/readTimeoutSeconds/poolTimeoutSeconds/callDeadlineSeconds. No secret/credential contents in config; fixed parsing representation ceilings are not runtime quotas.
- `tool_models.py`: closed `ScopeArguments(siteId,workAreaId)`, `ListArguments(+limit,cursor)`, `AssetArguments(+assetRef)`, `JobArguments(+jobId)`, `CreateArguments(+assetRef,requestedBounds,observedCrsDigest,idempotencyKey)`; literal six-name maps `TOOL_ARGUMENT_MODELS` and `TOOL_RESULT_MODELS` exactly spec§6.
- `CoreSpatialDataClient(config:AdapterConfig)`; `async invoke(name:str,arguments:dict[str,Any]|None)->dict[str,Any]`; `CoreAdapterError(code:str)` only closed safe codes.
- `server.build_server(client:CoreSpatialDataClient)->Server[dict[str,Any]]`; `main()->None` starts stdio using required `--config=/absolute/protected.json`, no listener/host setting writes.

Config boot parser has a fixed65536B representation ceiling before owner maxConfigBytes is known;
then verifies actual bytes fit that supplied limit. Token representation ceiling4096B (plus one CRLF),
identifier255UTF8B and cursor2048UTF8B match established wire limits, not operational defaults.
Request byte count includes actual method/body/header-value inputs, not just a reserialized body.
If an owner frame limit cannot fit even the safe error envelope, close the call/session with a safe
stderr code rather than exceed the configured limit or output partial JSON.

- [ ] Step1 — RED test config private files/origin/header/limits and real HTTP framing cases. Generated fixture config uses request8192B/response131072B/concurrency2/identifier255B/cursor2048B/token4096B/config16384B/connect2s/read2s/pool1s/call5s; values are required, strict, finite and tests-only. Fail absent/unknown config fields, zero/NaN/bool limits, unsafe parent/symlink/hardlink/non-owner0600 files, changed-during-read stats, duplicate JSON and bearer in config/env/argv/tool args. Legitimate token replacement between calls re-reads safely.
- [ ] Step2 — Run `.venv/bin/python -m pytest tests/contract/test_spatial_data_mcp_config.py tests/contract/test_spatial_data_mcp_client.py tests/contract/test_spatial_data_mcp_stdio.py -q` with only new package source path prepended by test fixture (explicit actual repo path); expect genuine missing/new behavior RED. Existing SDK/dependencies already installed, no sync.
- [ ] Step3 — Implement config and argument models. Accept exact HTTPS origin or literal-loopback HTTP, reject userinfo/path/query/fragment/controls; use no environment proxy/redirect and verified TLS. Safe identifiers use existing path-safe pattern and config byte limits; cursor/idempotency key are bounded unchanged values, not authority or auto-generated keys. Validate canonical assetRef/jobId/digest and bounds before transport; only create supplies purpose=EXTERNAL_AI/resolutionMode=NATIVE in existing V1 body.
- [ ] Step4 — Implement async client fixed method/path map. Stream bounded identity-encoded JSON; reject unsupported Content-Type/Content-Encoding, duplicate/nonfinite/deep-invalid JSON, chunk/count overage, redirect/unacknowledged response and all model-valid wrong scope/job/asset IDs. Error codes: UNKNOWN_TOOL, INVALID_TOOL_ARGUMENTS, CONFIGURATION_UNAVAILABLE, CORE_UNAVAILABLE, CORE_TIMEOUT, CORE_RESPONSE_TOO_LARGE, INVALID_CORE_RESPONSE, AI_EGRESS_UNACKNOWLEDGED, CONCURRENCY_LIMIT_EXCEEDED plus recognized shared reason values; raw response strings/exceptions never reflected. Refusal retains known reason/remediation only from validated closed error model.
- [ ] Step5 — Implement exact GET wrapper/reference from typed COMPLETED+AVAILABLE receipt; never follow descriptor or retrieve bytes inside adapter. Every list item scope and returned cursor count are validated. Close clients/streams/semaphore slots on success/error/timeout/cancellation; deadline includes queued work. Do not issue new create after lost response or transform identity.
- [ ] Step6 — Implement official installed SDKv2 callbacks/input-output schemas and explicit structured CallToolResult. Reads annotated read-only, create/cancel mutations, idempotent hint true, no arbitrary open-world tool/resources. Final MCP payload bound covers both structured JSON and the actually serialized frame (duplicated text and protocol overhead included); if too large safe is_error refusal, never truncated stdout. Advertised output schemas accept success contract or closed error envelope exactly, including legitimate is_error calls in real ClientSession. stdout exclusively protocol; startup errors/cancellation expose safe stderr code without tracebacks/values.
- [ ] Step7 — Add ksi-spatial-data-mcp0.0.1 Python>=3.12,<3.13 manifest/console script; same existing mcp2.2.0/HTTPX/Pydantic/event-contract dependency constraints. Add root workspace source/dev leaf metadata. `uv lock --offline` may update metadata only; assert unchanged third-party package versions/origins/hashes against prechange TOML. If cache unavailable do not install/use network/upgrade or hand-forge lock; record exact blocker and continue tests via explicit source import. Use fixture source path for subprocess, not editable installation of new package into shared .venv.
- [ ] Step8 — GREEN config/client/stdio tests: six exact names/schemas; partial/truncated/duplicate/compressed/infinite JSON; wrong-scope queued result and swapped receipts; token rotation/expiry; origin/proxy/redirect; finite concurrency/deadline/cancel cleanup; stdout/stderr secret-marker absence; no raster/resource/download tools. Run old `test_analysis_mcp_stdio.py` unchanged as regression. Commit Task4 after scoped/static checks; installation/customer host remains excluded.

## Task 5: Prove generated end-to-end parity, restart and external consumption

**Files:** new `spatial_data_mcp_fixture.py`, `test_spatial_data_mcp_http_integration.py`, `tests/replay/test_spatial_data_mcp_replay.py`, example `mcp_native_window_workflow.py`; adapter README/Core README/ops evidence/REPOSITORY_STRUCTURE entry. Minimal existing fixture edits only if necessary to add explicit new identity inputs; no weakening original generated/synthetic boundaries.

**Interfaces:** fixture exposes a context-managed real loopback Core ASGI listener, owned generated object HTTP server, distinct existing data worker launcher, generated AI and generic principal/grants, private config/token paths, clock mutation and participant restart. Compose existing `spatial_data_http_fixture.HttpLane`/source/journal helpers and current genuine generated TIFF inspector; Model-only source fixtures are not end-to-end evidence. Export receipt is the Core record, not a mock successful MCP body.

- [ ] Step1 — RED `test_sdk_discovery_prepare_receipt_http_consumer_parity` parameterized DSM/RGB/RGBA and masks/NoData: ClientSession initializes actual new stdio server, discovers exact asset, creates job, real generated worker prepares bytes, get returns same V1 job as HTTP and exact file descriptor. Separate HTTP-only native_window_client authenticates as same authorized requester and verifies digest/size/native pixel array/affine/mask/CRS against hand-sliced source. Use actual loopback HTTP for this test; preserve path.query (existing mounted_transport helper drops query and is unsuitable for pagination evidence).
- [ ] Step2 — RED `test_lost_response_and_restart_preserve_job` / `test_next_observation_gets_new_source_and_result` / `test_std_io_scope_revocation_and_rights_negative_matrix`. Replay after issued/completed/canceled states with actual journal stores; same body+key same ID and one issuance, altered body409, new epoch/revision fresh asset/job/receipt, no latest substitution. Establish expected comparisons before implementation instead of accepting fixtures as truth.
- [ ] Step3 — Implement fixture/example glue only; fix genuine runtime failures in owning Tasks1–4, not by changing expected protected outcomes. Example accepts caller-supplied scope/key/config/local output target, never token arguments, remote refs or DB/store access. A distinct SDK client invocation requests once, polls a finite caller budget, persists only safe IDs/receipt/reference; user credential remains separate. Optional download delegates existing guarded native consumer and never overwrites/publishes partial files. No automatic install/start of shared production/customer services.
- [ ] Step4 — GREEN run integration/replay plus existing `test_spatial_data_http_integration.py test_spatial_data_consumer.py tests/replay/test_spatial_data_delivery_replay.py test_analysis_mcp_actual_inspection.py`. Negative matrix consent revoked before each of eight HTTP pairs/six tools, exact grant expiry/revoke/replacement, wrong organization/Site/area/WorkOrder, READ-only/ambiguous grants, purpose/header downgrade, missing ack, worker source mismatch, byte midstream revoke and refusal without partial file. Verify metadata audit/replay and no downloaded bytes in SDK output.
- [ ] Step5 — Complete docs with exact console entrypoint/config/tool workflow and generated evidence command/revision, source/digest parity, software-versus-host/customer scope. No tool configuration installation, signed authority issuance or universal Codex/Claude/ChatGPT claim. Record sample/rights/cost/containment acceptance still open; do not rewrite product-state slice as done. Commit Task5 only with demonstrated local checks; runtime changes invalidate earlier frozen checks and require final review.

## Task 6: Independent closeout against the approved contract

**Files:** plan/parent ledger/checkpoint and any strictly scoped repairs identified by review; no repeated baseline browser/deployment tasks. Primary owns Git/integration; reviewer read-only; test-runner executes final commands independently.

- [ ] Step1 — Freeze exact required source/schema/test/docs SHA256 and HEAD/pending diff. Primary self-audit spec§1–9 and acceptance items1–10: contract/identity T1, rights/currentness/audit T2, native discovery/cursors T3, finite SDK/HTTP projection T4, real generated parity/reuse T5; exclusions/rollback T6. Classify no evidence as unverified, not pass.
- [ ] Step2 — Dispatch bounded read-only reviewer with exact spec/plan/frozen files and security focus; require concrete findings (scope/purpose/downgrade/currentness/audit/metadata leakage/stdio). Fix all required defects, retain known optional/unrelated backlog separately. No extra automatic per-edit reviewers or parallel shared-file writers.
- [ ] Step3 — Independent test-runner runs exact declared new scoped tests, existing full Spatial Data/MCP scoped set and replay, actual bare `.venv/bin/python -m pytest -q` with process-local022 umask, `.venv/bin/ruff check` and `ruff format --check` on changed Python, scoped `.venv/bin/mypy` including source and tests, `git diff --check`, `uv lock --check --offline`. Record exact argv/exit/log hashes/warnings/skips and before/after freeze, session ID. A wrapper must print/retain real results and stop on hash/path mismatch, no discovery retries or invented filenames.
- [ ] Step4 — Package verification uses manifest parsing/console target/source closure now; wheel/sdist build with Hatchling and import/SDK smoke from exact built artifact is REQUIRED before package-distribution readiness. Shared .venv lacks Hatchling as observed2026-10-06. Use an already available authorized backend environment if verified; do not install/sync opportunistically. If absent record build-readiness blocker and request scoped environment preparation; continue independent runtime checks and do not claim package/customer installation acceptance.
- [ ] Step5 — Real API/stdio changed-flow is the T5 loopback listener, actual auth, byte-consumer persistence and journal restart, not browser screenshots/MockTransport alone. No UI delta, so no new visual design/browser review needed here; any subsequently added visual work returns to design workspace. Recheck affected tests after each repair and rerun independent closeout on final frozen state.
- [ ] Step6 — Inspect task-owned index/diff, commit verified source/docs locally excluding checkpoint/tmp tokens/logs/generated samples; retain unrelated worktrees. Record current usable level, revision, original command evidence, open customer/export/license/host/cost/build gates and next authorized action. SDP-CLIENT-01-AI local software can close only to proven scope; no whole goal/product EXT-VAL/P-AC closure or push/deploy.

## Execution gate and environment evidence

Installed metadata observed2026-10-06: mcp2.2.0, HTTPX0.28.1, Pydantic2.13.4, mypy2.3.0;
Server constructor and Tool/CallToolResult fields match low-level v2 reference. No new SDK handshake
or data-MCP test run exists yet. Official SDK docs were consulted in predecessor spec stage;
uv current lock-mode/preference docs via Context7 confirm lock updates are not environment sync.
Hatchling is absent in shared .venv; no installation was attempted. Missing builder is a package
artifact verification boundary, not permission to narrow the requested functionality.

Recommended method: **Native** sequential execution with one independent whole-change reviewer
and independent final test-runner. Tasks2–4 share source/grant/job/publication interfaces; one writer
reduces authority drift and avoids redundant context cost. Independent security/result checks remain.
Human review passed: selected subagent-driven execution on2026-10-06 for the full plan atd0aac56.
Use fresh sequential developer and task reviewer per stage, then whole-change reviewer/test-runner.
Primary retains Git/checkpoint/integration ownership; helpers do not spawn helpers. Prior long-term
local development mandate is preserved; this gate does not authorize external effects or installation.
