# services/core

KSI Core: scoped identity, Site/WorkArea, external observations, policy, jobs, results, evidence and audit.

## P3 Task 5 — Core acquisition closure (archive boundary)

The managed acquisition set retired to `archive/acquisition-2026/` (git-tracked,
blob-identical moves; the archive is not a runtime import path, workspace member,
or test target): `domains/missions/**`, `capability/**`, `domains/edge_transport/**`,
`domains/observations/{events,equipment_states,equipment_support}.py`,
`identity/{signing_keys,device_attestation}.py`, `acquisition/**`,
`domains/workspace/**` (copilot + site workspace), the mission-coupled
`domains/{analytics/defect_candidates,design/{region_extraction_reports,report_exports}}.py`,
legacy composition (`assembly`, `base_graph`, `workspace_graph`, `analysis_graph`,
`capability_graph`, `production`, `production_config`) and their flat shims.
`composition/app_factory.py` stays as the shared factory (its managed
`capability.registry` import is lazy; calling it with managed stores fails
loudly). `composition/routes/*` stay importable (top-level-clean, lazy mounts
only). Core no longer depends on `ksi-mission-contracts`,
`ksi-mission-planning` or `ksi-equipment-intelligence` (dropped from
`services/core/pyproject.toml`; proven by
`tests/contract/test_acquisition_archive_boundary.py`). The normal boot is the
platform profile (`assemble_platform_app` / `build_platform_production_app`);
managed Core endpoints (`/v1/missions/*`, edge, events, equipment,
comparison/design-conformance/region-extraction, report-exports, copilot,
workspace) retire with the legacy assembly. Historical managed results stay
readable through the retained readers (`processing_jobs`, `artifact_manifest`,
`source_media`, `evidence`), pinned by `test_historical_managed_readers.py`.
Those readers do not mount managed ProcessingJob/artifact HTTP routes or enable new execution.
See the [P5 integrated audit](../../docs/audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md)
for exact SDK/HTTP/replay evidence and failed/unverified gates.

## Spatial data delivery (explicit local lane)

`ksi_core.domains.external.delivery` owns distinct scoped grants, exact inspected
source snapshots, durable preparation jobs/fences and guarded derivative access.
It does not reconstruct customer originals or grant analysis/accuracy eligibility.
`SpatialDataLocalAssemblyConfig` requires connected storage/currentness factories;
an optional existing protected `0700` `spool_root` enables full-hash private downloads.
No default production/environment activation is added. Every GET/HEAD rechecks fresh
credentials/current rights; Range and redirects are unsupported. Cleanup deletes only
exact owned derivative versions after capability/lease/retention expiry, keeping history.

See [local verification and external-consumer instructions](../../docs/ops/SPATIAL_DATA_LOCAL_VERIFICATION.md)
for generated-parser/worker/HTTP/replay evidence and open public/host/customer gates.
Generated MCP end-to-end parity, restart, replay, and rights-matrix evidence (local
software only) is recorded in
[SPATIAL_DATA_MCP_SOFTWARE_EVIDENCE](../../docs/ops/SPATIAL_DATA_MCP_SOFTWARE_EVIDENCE.md).

## Core R1 module routing (partial)

`KSI-CORE-R1-20260914` has relocated the reusable foundation and identity
implementations without changing their public behavior. Active canonical modules are
`ksi_core.foundation.{api_base,durable_journal,identifiers,leasing,metrics,observability,
retention,currentness}` and `ksi_core.identity.{auth,oidc}`. Their retained compatibility
aliases share types and globals. P3 archived signing/device and acquisition aliases;
those names are absent rather than resolved through the archive.

`docs/audit/CORE_R1_MODULE_MIGRATION.json` is the exhaustive old/active/planned map and
`tools/check_core_module_boundaries.py` validates it. Foundation imports stay protected;
the only recorded transitional domain dependencies are retention's runtime evidence verdict/
storage error and its type-only evidence/event annotations. They are narrow existing contracts,
not permission for a general foundation-to-domain dependency.

The R1 T2/T3 moves are historical path lineage; P3 subsequently archived missions, edge transport,
acquisition/capability and coupled workspace domains. Active external modules live under
`ksi_core.domains.external.{ingress,quantity,workflow,authority,delivery}`. Retained readers and
their explicitly listed aliases remain; archived aliases are not public entrypoints.
`ksi_core.domains.observations.epoch_identity.observation_epoch_id` owns the unchanged deterministic
external identity, and Site/ingress use neutral `ksi_event_contracts.site_frame` / `ksi_geo_core.aoi`.
`ksi_core.composition` owns ordered checks, routes, platform assembly and runtime configuration.
`ksi_core.app` aliases the shared factory; `app_assembly`, `assembly`, `production` and
`production_config` no longer exist. The inventory and archive boundary tests govern this distinction.

`ksi_core.composition.{platform_graph,platform_app,
platform_assembly}` provides the explicit external-only profile: only Site/WorkArea/roster/
WorkOrder stores plus the existing external graphs, mounted through `assemble_platform_app`
with no Mission key, device, acquisition, flight or managed-processing state. The existing
observation router gains only the opt-in `external_only` flag, which omits the four managed
mutation routes and rejects omitted/managed execution modes with `422
EXTERNAL_RECONSTRUCTION_REQUIRED`. Retained historical WorkOrders keep their original execution modes.
`ksi_core.composition.platform_production.build_platform_production_app` boots that
profile from environment configuration with only a data directory, S3 endpoint/bucket
and principal digest/OIDC inputs — no Mission signing key directory or device
attestation file — validating every required fact before opening journals or clients.
Platform-profile verification runs the real generated flow against that factory:
`tests/contract/test_platform_core_http_integration.py` drives generated-TIFF
inspection, the Analysis worker, and region-data receipt end to end, and
`tests/replay/test_platform_core_replay.py` proves restart/replay with retained
managed rows and revocation distinctions. No new result schema, identity, grant,
calculation, or producer adapter is introduced for either file.
The shared pure env helpers live neutrally in `ksi_core.composition.runtime_config`
and `ksi_core.foundation.config_values`; no legacy production/assembly shim is present.

### Historical acquisition behavior (not current APIs or rollout instructions)

The following dated description retains the original device/flight authority meanings only.
Its code and managed assembly are archived; these routes, settings and producers are not mounted
by the current platform factory. Never import or activate archive code to satisfy a platform request.

Core는 장비별 SDK 코드를 소유하지 않는다. 장비 배치·연결 정책은
`ksi_core/acquisition/`의 profile/readiness store와 `coordination` 원장·API로
분리하고, 실제 연결 선택과
전송은 `services/dji-gateway`가 소유한다. `GATEWAY_DEVICE`와 `EDGE_DEVICE`는 별도
Principal이며 서로의 ingest 권한을 공유하지 않는다.

readiness projection은 항상 fail-closed 상태를 보여주지만 신규 Mission 발급에 이를
강제하는 `KSI_CORE_ACQUISITION_ISSUE_GATE_ENABLED`는 기본 OFF다. 실장비 capability
receipt와 기존 Site profile migration이 끝난 뒤에만 `true`로 rollout한다.

승인된 WorkOrder는 `(organizationId, workOrderId, cycleNumber)`로 멱등한
`AcquisitionRun`을 만든다. Run은 Mission 연결과 capability별 Gateway operation
receipt만 소유한다. 실제 activation, 원본 봉인·검증, Processing 상태는 각각 기존
MissionExecution·SourceMedia·ProcessingJob 원장이 계속 권위이며
`GET /v1/observation-work-orders/{id}/acquisition-progress`가 이를 합쳐 보여준다.

## Customer-owned external reconstruction ingress

The current platform's `POST /v1/sites/{site_id}/observation-work-orders` requires explicit
`EXTERNAL_RECONSTRUCTION`; omitted/`MANAGED_ACQUISITION` requests return422
`EXTERNAL_RECONSTRUCTION_REQUIRED`. An external request creates an
already-approved customer artifact registration request with no schedule and no
acquisition callback. The request requires `Idempotency-Key`; Core journals its
hash and normalized request fingerprint, never the raw key. Retrying the same
request returns the current WorkOrder without a second create event; reusing the
key for another request is a conflict. Historical managed rows remain readable and non-executable.

ADR-KSI-036's bounded ingress requires the platform assembly's durable journal and evidence-storage
port. The current dev runner supplies a fail-closed unavailable port when S3 is not configured;
mounted routes do not imply usable uploads or successful byte seal. The five-route flow is:

1. `POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions` registers
   an authenticated customer declaration and returns a server-issued `submissionRef`.
2. `GET` on that collection lists scoped revisions with their `submissionRef` values.
3. `GET .../{submission_ref}/revisions/{revision}` reads one declaration and, if sealed, its
   observed manifest.
4. `POST .../{submission_ref}/revisions/{revision}/upload-grants` issues a refreshed digest-bound
   direct-upload capability for the latest unsealed revision.
5. `POST .../{submission_ref}/revisions/{revision}/seal` compares server-observed object key,
   checksum, size, and content type with that revision's declaration and records the point-in-time
   manifest.

`submissionRef` is an opaque, server-returned `ers-v1-` plus 64-lowercase-hex value. Clients must
use the returned reference rather than calculating it or constructing a URL from the customer
`submissionId`. The raw customer ID remains the durable declaration, journal, and object-key
identity; existing journals derive a stable public ref when replayed without migration.

After receiving a grant, the client directly HTTP `PUT`s every artifact to its returned `uploadUrl`
with every `requiredHeaders` value unchanged, including the signed `Content-Type` and base64
`x-amz-checksum-sha256`. That direct storage transfer is required before seal but is not a sixth
Core API route.

Registration requires a valid, non-null client `submissionDigest`; Core rejects stale or unsealed
declarations rather than creating a digest. The server observes derived bytes at seal time, but
registration and sealing are neither semantic raster validation nor accuracy, raw-source authority,
managed `ProcessingJob`/profile identity, analysis eligibility, or flight acceptance. Originals stay
customer-side; ortho-only registration is permitted and DSM is optional, with missing evidence
restricting only dependent claims.

Writes require a human `SITES_WRITE` principal and reads require `SITES_READ`. The principal and
scoped WorkOrder establish organization, site, cycle, and actor authority; body fields cannot do so,
and cross-tenant resources are absent. Revision 1 freezes its stream witness. Corrections are
contiguous new revisions, identical digest retries return the original receipt, conflicts return
`409`, and sealed revisions remain immutable. Each revision retains its own authenticated actor
provenance. Only the latest unsealed revision can receive refreshed grants or be newly sealed.

Grant URLs are never journaled and an already-issued capability is not revoked by this feature.
Seal is a point-in-time observation, not object-lock or perpetual immutability. The local loopback
test uses boto3 presigning plus HTTP PUT/HEAD as software evidence only; it does not establish
AWS/MinIO authorization interoperability. The durable journal digest is an integrity binding, not
an unkeyed claim of tamper authentication.

The wire contract is [`contracts/api/openapi-core.yaml`](../../contracts/api/openapi-core.yaml) and
the submission/manifest schemas it references. Exact local evidence, test commands, and remaining
gates are in the [external ingress verification audit](../../docs/audit/EXTERNAL_RECONSTRUCTION_INGRESS_API_VERIFICATION.md).

## External artifact inspection and sanitized display

When durable external reconstruction, policy, inspection, display, WorkOrder, and evidence-storage
dependencies are assembled together, Core mounts a scoped worker plane at
`/v1/internal/external-validation/inspections`. `PROCESSING_WORK` workers list and lease work, read
lease-gated inspection input, renew/report/incomplete-failure attempts, and declare/seal one
sanitized display derivative. Source download capabilities and required headers appear only in that
lease-gated worker input; Core never journals those capabilities or exposes source object keys.

`GET .../revisions/{revision}/inspection` requires `SITES_READ` and returns only occurred
registration, seal, inspection, report, and display receipt facts. It does not issue or schedule
inspection work, make a use/eligibility decision, or make an accuracy claim. The matching scoped
`GET .../display-artifacts/{sanitized_display_ref}/download` creates a short-lived derivative
capability only after rechecking the current exact report, receipt, and policy binding. Missing,
foreign, stale, or revoked resources are a non-disclosing `404`; storage failure is `503` without a
partial capability. These routes remain absent from a storage-less assembly.

## External quantitative relative-volume authority (V1)

The quantitative workflow is default-closed. It is assembled only when Core receives an explicit
`ExternalResultWorkflowAssemblyConfig` built from an owner-protected, absolute configuration path,
an approved catalog path, and an injected `ExternalQuantitativeCatalogAuthorityPort`. Configuration
names paths only; it cannot select a subject, organization, WorkArea, actor, policy, numeric limit,
or authority record.

V1 accepts one ordered pair only when both DSMs have the exact
`external-geotiff-profile.v1` grammar and inspector build, matching observed CRS and vertical
reference digests, non-overlapping ordered capture intervals, independently validated checkpoint
evidence, and one exact active WorkArea snapshot. The validation policy pre-authorizes a
`compatibilityRuleDigest` for those facts. Core then records a separate full
`mappingRecordDigest`, which also binds the exact validation-policy digest; decisions, execution
snapshots, and historical use bind that full record digest. Cross-profile, managed-profile,
cross-CRS, cross-vertical, missing-checkpoint, stale-WorkArea, absent-policy, or mismatched actor
inputs remain unavailable.

`compatibilityRuleDigest` is pre-inspection identity only: the fixed external profile/parser,
equal observed CRS/vertical references, independent checkpoint evidence for each epoch, ordered
non-overlapping capture intervals, and exact WorkArea matching. It contains no subject,
inspection, observed value, capture value, WorkArea revision, evidence, policy, result, or
authority digest. The later `mappingRecordDigest` retains every one of those exact bindings.

For Core-only composition, a configured common assembly exposes the exact built mapping participant
at `app.state.external_relative_volume_mapping_authority`; it is `None` when the workflow is not
injected. This is not an HTTP authority surface, creates no second catalog, and cannot admit,
activate, or issue work by itself.

An injected catalog-authority record binds a strict admission-body digest. The only omitted
self-references are the catalog envelope's authority digest and the matching contained execution
policy authority digest; the resolved sealed digest must be reinserted identically before the
catalog is used. The configured authority journal is opened by the common assembly and therefore
shares its journal ownership, failure cleanup, and development-assembly close lifecycle.

Rollback disables this explicit workflow injection and new volume issuance. It retains sealed
submissions, inspections, checkpoint validations, use decisions, authority lifecycle events,
requests, reports, reviews, and WorkOrders. Local tests do not establish customer export
compatibility, authority provisioning, backup/restore, signed OCI/SBOM evidence, deployment,
owner operation, HIL, or field acceptance.

## Scoped retained volume history

`GET /v1/sites/{site_id}/external-volume-reports` is the single audited retained
history route available to scoped customer OIDC operators with `SITES_READ`.
Each request checks the authenticated organization and Site, the exact retained
report zone, and every WorkArea assigned to the current source WorkOrder and
(for relative volume) the baseline source WorkOrder. Missing or unprovable source
bindings are hidden; granting only one of a source's multiple areas is insufficient.
An inaccessible Site or cursor returns the same generic `404`. An accessible Site
with no readable reports returns `200` with empty `items` and no `nextCursor`.

Filtering precedes pagination (`limit` 1–50, default 20). A cursor must itself
remain readable under current grants; hidden/unavailable rows never become cursor
or placeholder references. The reader skips entries preceding a valid cursor,
stops at a page plus one readable lookahead, and holds the coordinator only for
one row's local checks and joins. Retained-index enumeration and sparse invisible
histories still need real cardinality/latency measurements before capacity claims.

Archiving a WorkArea does not erase granted retained history or grant permission
for new execution. Proposal/approval counts describe visible proposals: the
existing durable proposal contract requires the exact report-zone target.
This historical read does not grant artifact downloads, quantitative eligibility,
review, approval, issuance, or flight authority; numerical policies and historical
records are unchanged. Existing V2 analysis and revision-bound review contracts
are separate and unchanged.

The separately audited exact detail GETs are
`/v1/sites/{site_id}/observations/{report_ref}`,
`/v1/external-relative-volume-reports/{report_ref}`, and
`/v1/external-single-volume-reports/{report_ref}`. They reuse the same all-source
scope rule, with a generic `404` for hidden/unverifiable reports. Site-less details
derive the Site from the exact retained witness and verify its zone and real Core
orders before returning original request/report/policy/review bodies. Inline
proposals must match the report, decision, zone, source, and review identity and
their complete target set must be granted. Historical review inconsistencies are
hidden from restricted callers; unrestricted historical semantics remain intact.
Archived grants still permit retained reads, not new execution. Family-list aliases,
pending decisions, direct proposal/review reads, and V1 review/proposal mutations
remain closed; no new permissions or live account mappings are created.

## Spatial asset metadata catalog (V1 local software)

`GET /v1/sites/{site_id}/work-areas/{work_area_id}/spatial-assets` lists up to 50
external reconstruction artifact revisions per page. The companion
`GET .../spatial-assets/{asset_ref}` reads one exact asset. Both require
`SITES_READ` and recheck organization, Site, and WorkArea grants on each request;
the exact GET templates are available to scoped customer OIDC operators. The
Analysis MCP client is not granted these routes. Foreign or revoked scope is a
non-disclosing `404`.

This is a read-only projection of existing WorkOrder, submission revision,
observed manifest, and inspection records. Customer declaration, Core's
point-in-time byte observation, and inspector-measured raster geometry are
separate fields. `assetRef` is a server-derived opaque reference; storage object
keys and download URLs are not returned. `dataAccess` is
`NOT_AVAILABLE_FROM_CATALOG`, and `analysisStatus` is `NOT_EVALUATED` even for a
measured raster. A WorkOrder spanning multiple WorkAreas has no per-artifact
area binding and is omitted from this WorkArea catalog; register an exact
single-WorkArea observation for this view rather than inferring coverage.

The response is capped at 512 KiB. Core also refuses the catalog with `503`
before returning a partial list when its bounded source budget is exceeded:
256 WorkOrders per Site, 2,048 revisions per request, 256 submissions per
WorkOrder, 128 inspection attempts per sealed subject, and 64 retained
policies per sealed subject. These are current software limits, not measured
customer capacity. The exact contract is in `contracts/api/openapi-core.yaml`
and `contracts/schemas/spatial-asset-catalog.v1.json`. Local verification is
recorded in `docs/superpowers/plans/2026-09-30-spatial-asset-catalog-v1.md`.
