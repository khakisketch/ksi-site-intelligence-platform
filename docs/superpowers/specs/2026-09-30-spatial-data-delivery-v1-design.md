# Spatial Data Delivery V1 — native-grid preparation and authorized download

- Spec ID: SDP-DATA-01
- Status: HUMAN APPROVED on 2026-09-30 by the explicit reply “승인” to this written contract; implementation plan still requires review.
- Date: 2026-09-30
- Purpose: let an authorized external program select an existing spatial asset, request a bounded native-grid rectangle, and retrieve the resulting GeoTIFF and its exact spatial receipt without copying Core authority into clients.
- Scope: local software development first. No commit, push, deployment, credentials, customer contact, Terra compatibility or release authorization.
- Authority: [Constitution](../../product/PRODUCT_CONSTITUTION.md), [ADR-KSI-036](../../architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md), [ADR-KSI-037](../../architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md), [ADR-KSI-038](../../architecture/ADR-KSI-038-spatial-data-and-analysis-platform.md), PRD §1.1.2 SDP-REQ-01/02/03/05/06/07/08.
- Product slice remains EXT-VAL; this task does not close or reprioritize it.

## 1. Agreed intent and boundaries

The Human requested continuation from the read-only catalog, then acquisition of usable public samples and design of the delivery contract. The selected direction is Core admission, a distinct worker preparing the result, and current permission checks at authenticated download. The existing native-grid primitive is reused, not made into a public capability by itself.

V1 exports DSM or RGB/RGBA orthophoto rectangles at the inspected source grid and resolution. It does not resample, reproject, adjust height, polygon-mask, create tiles, export raw photos, or perform analysis. Request and actual expanded pixel-edge output bounds are different facts. DTM/vector/mesh/point-cloud/camera bundles and new resolutions require successor contracts. An unknown height reference remains explicitly unknown and restricts dependent uses, not ordinary unmodified data delivery by itself.

Approval of this spec permits preparation of the implementation plan, not automatic implementation or production activation. Written plan review is the next gate. This architectural approval does not claim an implemented contract or deployed code.

## 2. Existing evidence and reuse decisions

| Existing asset | Decision | Boundary |
| --- | --- | --- |
| `SpatialAssetCatalog` and `spatial-asset-catalog.v1` | ADOPT identities and scoped resolution | Existing `ksa-v1-` assetRef is retained; metadata permission is not byte permission. No changed V1 supported-actions claim. |
| `prepare_external_native_window()` and `NativeWindowReceiptV1` | ADOPT primitive and pixel rule | Worker-only import. Requires a genuine byte-bound MEASURED report; the acquisition header probe cannot substitute for it. |
| `DurableJournal` | ADOPT durability/recovery behavior | New data-job and access-grant domains, not analysis or managed ProcessingJob state. |
| Analysis lease/client/object-stream/activation patterns | REFERENCE_ONLY pending exact plan | No borrowed credential, activation record, purpose, policy, DSM-only capability issuer, or report identity. Extract only domain-independent helpers if separately justified. |
| `EvidenceStorage.get_bytes()` / display presigned GET | REFERENCE_ONLY | Whole-object buffering and display-only grants do not implement this download contract. A bounded immutable-object read adapter is required. |
| `references/` repositories | REFERENCE_ONLY | No direct runtime imports or submodule edits. |

Owner placement: contracts in `packages/event-contracts/` and `contracts/`; durable authority and HTTP in `services/core/`; polling, isolated raster processing and output upload in `services/processing-controller/`; raster math in `packages/geo-spatial/`. No new independently deployed service. Dashboard and MCP adapters are successor tasks after the common HTTP flow is verified.

### Public sample profile, not customer acceptance

Cambridge Coastcare's Floreat-f4, capture date declared 2022-08-24, provides [DSM](https://catalogue.data.wa.gov.au/dataset/floreat-f4-raster-dsm-geotiff-aug-2022) and [orthomosaic](https://catalogue.data.wa.gov.au/dataset/floreat-f4-orthomosaic-aug-2022), both CC BY 4.0. Original files were downloaded and full SHA-256/byte size checked:

| Source | Bytes / SHA-256 | Header observation |
| --- | --- | --- |
| DSM | 181498053 / `28eb3bea0e0ef58db7fa9f00b383bf7b50e6348103d80767a5ad362c0c37a7e2` | EPSG:7850, 5150×8808, float32, one band, 0.05m, NoData -10000 |
| ORTHO | 346715111 / `b25bbfa56cd8cf90eca43bcb5539de4cbccfaa2744421c5f949ca1038b27cb66` | EPSG:7850, 10298×17615, uint8 RGBA, 0.025m, alpha mask |

The publisher's ORTHO description says 2cm; its affine reports 2.5cm. Preserve both rather than silently repairing the declaration. The grids have different origins and dimensions; do not claim pixel-for-pixel coincidence. Vertical reference, independent accuracy, full-file inspection acceptance, processor provenance verification and actual customer suitability remain unknown.

Acquisition evidence is `.opencode/artifacts/spatial-public-sample-20260930/sample-evidence.md`; temporary bytes and catalogue/probe JSON are in `/tmp/opencode/ksi-spatial-public-sample-20260930/`. These ignored/temporary paths are local evidence, not required runtime files. Source pages, byte hashes and profile above allow reacquisition. Include attribution and modification notices with exported receipts; public licensing does not automatically create a tenant grant or AI consent. No training or external AI transmission is part of this task.

## 3. Distinct authority, rights and activation

### Principals and permissions (proposed additive names)

- `SPATIAL_DATA_WORKER` receives only `SPATIAL_DATA_WORK`; no Site browse, analysis, ingress, flight or managed-processing authority.
- `SPATIAL_DATA_CLIENT` receives `SPATIAL_DATA_READ` and `SPATIAL_DATA_REQUEST` with explicit nonempty Site/WorkArea scopes. Existing Analysis MCP clients do not inherit either permission.
- Operator ADMIN/FIELD_OPERATOR may receive both permissions; VIEWER receives read only. A role permission is necessary but never sufficient for preparation or bytes: each requires a current exact data grant. Job-history visibility is separately scoped below, so permission withdrawal can be explained without returning bytes.
- Worker runtime activation binds organization, principal, instance, fixed preparation profile, runtime/build/image/lock digests, transport origins and policy digest. It is a new data-worker activation, not an Analysis activation or a ProcessingJob.
- Production wiring stays off unless all dependencies and independently authorized activation material are present. Local assembly must explicitly inject isolated test authority. No accounts, secrets or signatures are provisioned by this task.

### Data grant contract

Core retains append-only grants supplied through a trusted owner-controlled provisioning port. V1 adds no user-facing grant editor or grant-approval API. A grant binds `grantId`, revision/digest, organization, beneficiary principal, exact assetRef, Site/WorkArea, allowed bbox and observed CRS digest, preparation/read operations, allowed use purposes, processing location, license/provenance evidence digest, attribution text, UTC validity interval and finite data policy digest. Missing evidence or an unknown right denies access. ADMIN cannot self-grant merely by requesting a job.

Purposes are `GENERAL_DATA_USE` and `EXTERNAL_AI`. Both require explicit rights; EXTERNAL_AI additionally requires the applicable Site AI-egress consent and grant purpose. Request headers, text prompts and public data labels cannot establish these facts. Core cannot detect a consumer concealing its eventual use or control a downloaded copy; the API enforces declared-purpose admission and authorized transport, not remote usage policing.

Revocation is monotonic and targets an exact grant revision. A new grant does not resurrect an old job's permission automatically. Grant expiry/revocation, current principal scope, processing-location policy and required AI consent are checked at admission, lease/input issuance, completion acceptance and each download. Loss of any currentness dependency fails closed. An expired activation closes the data lane without altering existing catalog/analysis behavior. Denial of a new job creates no preparation record; failure/revocation of an admitted job remains visible through its scoped history.

## 4. Request, frozen binding and geometry

Proposed public base: `/v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-requests`.

`POST` requires `Idempotency-Key` and the strict body `{assetRef, requestedBounds, observedCrsDigest, resolutionMode: "NATIVE", purpose}`. Bounds are four finite numeric values `[xmin,ymin,xmax,ymax]` with positive dimensions. Unknown fields, caller-supplied organization/policy/worker/URL/object key/output path or resampling knobs are rejected. The source must resolve through the existing scoped catalog to exactly one sealed artifact and a current permitted MEASURED inspection.

Freeze: authenticated organization/requester, Site/WorkArea and area revision/boundary digest, assetRef/epoch/submissionRef/revision/artifact ID, observed source bytes/hash, manifest/report/inspector digests, full measured raster facts, exact request, selected grant snapshot, full data-policy snapshot, purpose, preparation profile and runtime identity. Use canonical digests, not customer file names, as bindings. A data job identity is new; the spatial asset identity is not.

Implementation clarification after repository inspection: existing WorkArea geometry changes create a new WorkArea ID and there is no numeric revision field. Its revision binding is the immutable ID plus a canonical digest of `{workAreaId, siteId, crs, polygon, createdAt, supersedes}`; mutable name/status are excluded. Do not fabricate a revision number or change the existing WorkArea schema.

The requested rectangle must be inside the inspected source extent. V1 refuses arbitrary polygons and silent clipping. The actual pixel-aligned rectangle must also lie within the authorized grant bbox; authorizing only the continuous requested bbox would leak neighboring cells. A WorkArea is attribution and principal scope, not proof that a rectangular crop is inside its polygon; explicit grant bbox authority is required. Archived WorkArea history and superseded sealed submission revisions may be requested only by their exact asset identity and a grant for that identity; no latest-version substitution.

Reuse the primitive's north-up affine rule, `a > 0`, `e < 0`: columns `[floor((xmin-c)/a), ceil((xmax-c)/a))`, rows `[floor((ymax-f)/e), ceil((ymin-f)/e))`. Exact pixel edges add no next cell. No rotated/skewed grids, CRS changes, height shifts or fabricated valid coverage. All-invalid windows fail; partially invalid windows preserve masks/NoData and report valid counts. A known nonfinite unmasked sample is a source failure, not zero elevation.

Idempotency scope is `(organization, requester principal, Site, WorkArea, hash(key))`. Store normalized request fingerprint, never the raw key. Same key/body resolves the original durable job, including after restart; a changed body is `409`. Retrying still checks current permissions. A changed grant or policy does not silently create a new job under the old key; new issuance requires a new key. Authentication precedes lookup and scoping precedes error details.

## 5. Durable jobs, worker fences and output acceptance

Execution states: `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELED`, `EXPIRED`. Availability is a separate projection: `NOT_READY`, `AVAILABLE`, `ACCESS_REVOKED`, `ACCESS_EXPIRED`, `RETENTION_EXPIRED`, `UNAVAILABLE`. A completed historical preparation can therefore remain completed but no longer downloadable.

| Transition | Required behavior |
| --- | --- |
| admission → QUEUED | Current rights/inspection/policy, exact frozen inputs and atomic organization concurrency reservation; fsync before response. |
| QUEUED → RUNNING | Dedicated worker/activation, immutable instance and acquisition key; monotonic attempt number and fence digest; finite lease/deadline. Repeated acquisition returns the same live attempt. |
| RUNNING renewal/input | Exact current worker/instance/fence; current rights/inspection/policy; no capability beyond lease, grant, activation or job deadline. |
| lease expiry | Next eligible lease receives a new fence. Old reports, upload grants and renewals cannot publish; retry allowance counts durably. |
| transient failure → QUEUED | Only policy-allowlisted transport failures, within attempt/deadline budget. Terminal format/geometry/hash/right failures do not retry indefinitely. |
| RUNNING → COMPLETED | Current fence and gates, exact upload receipt, observed output checksum/size/type, request/grid/source/policy/runtime-bound preparation receipt; atomically accept one result. |
| cancel → CANCELED | Requester with request permission and still-visible scope may cancel own job; scoped ADMIN may cancel others. Cancellation is idempotent and fences work immediately. No cancel of completed bytes as an implicit deletion. |
| deadline → EXPIRED / unrecoverable failure → FAILED | Store typed reason and cleanup obligation; no downloadable partial result. |

Proposed internal base: `/v1/internal/spatial-data-jobs`. Worker-only operations are bounded pending list, lease, renew, input, output-upload grant, completion and failure. GET input requires instance and attempt digest headers. Input resolves one exact object, not a caller URL; an internal short-lived source capability is lease-bound and never journaled or returned publicly. Such storage capabilities have bounded expiry, not instant revocation; an isolated worker may finish a bounded private read but cannot publish after revocation.

Worker copies and rehashes exact source bytes before raster decoding, uses the existing offline primitive in an isolated no-network child with memory/CPU/wall/workspace caps, and writes only a private candidate. Parent handles trusted-origin transport; arbitrary URLs, remote VRT references, shell commands and code evaluation are forbidden. Production process isolation, image pins and activation are separate verified gates, never inferred from a Python timeout.

Core determines a private output key from organization/job/attempt; uploads are exact checksum/size/content-type bound. Completion includes the preparation receipt plus output version observation. Core checks binding and storage observation, not GDAL decoding or raster arithmetic. A checksum-less or mutable-unversioned store cannot enable this lane. A worker receipt is a measured software fact, not independent accuracy or product acceptance.

Output acceptance after cancellation, lost lease, superseded fence, changed inspected source, expired/revoked grant/activation or policy withdrawal fails closed. Repeating an identical accepted report is idempotent; changing its digest is a conflict. Validate complete bindings on replay without applying today's policy to rewrite yesterday's records; current access remains separately evaluated.

## 6. Public retrieval and current download authorization

Proposed operations at the public base: `GET` paged list; `GET /{request_id}` status/receipt; `POST /{request_id}/cancel`; `GET /{request_id}/file`; `HEAD /{request_id}/file`. Status responses contain the same durable IDs for every future client, typed reason/remediation and current availability, not storage keys or capabilities. History requires current `SPATIAL_DATA_READ`, organization and Site/WorkArea scope plus job ownership; scoped ADMIN may inspect within organization. Revoked/expired data grants do not hide history from an otherwise authorized original requester, but never authorize bytes or further processing. Explicit recipient-sharing is deferred.

The receipt is structured JSON obtained from status, paired with one GeoTIFF file. It records exact source identity/revision/digests, request and actual bounds, pixel window, affine transform, measured CRS/digest, optional known vertical reference with unknown-state limitation, bands/dtype/mask/NoData, valid count, original observed resolution, profile/runtime/policy/grant digests, output SHA-256/size, preparation time, declared capture/processing time provenance, license/attribution and modification notice. `accuracyAssessed` is false; analysis/review are not implied. The file has a server-generated safe filename, not an untrusted submitted name. Never copy arbitrary source tags into the output.

### Bounded exact-byte delivery

Use a new immutable-version storage-read port and private spool, not `get_bytes()` or a public presigned redirect. Its adapter supplies incremental bounded reads, exact version and expected size; downloads fail if version pinning/checksum observation is unavailable. Rehash the whole selected output into a private spool before any response body; mismatch deletes the spool and returns no bytes. Reserve policy-bounded disk/concurrency and release on every exit.

Reauthenticate the credential and re-evaluate grant/scope/purpose/retention immediately before headers, and before each authorized bounded chunk. Currentness uses a dedicated fresh-check port, not the original request's frozen Principal. The maximum chunk byte count and stream wall time come from data policy. If revocation or currentness failure occurs after headers, terminate the stream and audit interruption; do not manufacture a JSON success or zero-length complete file. An already authorized/in-flight chunk and bytes already delivered cannot be recalled; this bounded exposure is explicitly part of the contract.

`Cache-Control: private, no-store`, `X-Content-Type-Options: nosniff`, exact Content-Length and output digest accompany delivery. No application/shared-CDN cache, redirect, content negotiation conversion or compression changing bytes. V1 rejects any Range request with `416` after authentication/scope checks; HEAD follows the same gates with no content transfer. Range/tiles/resumable sharing need a separate approved contract. Audit admission, denied access, stream start/end/interruption and delivered-byte count without tokens, signed URLs or private keys. Persist the start audit before bytes; journal failure fails closed.

## 7. Policies, cleanup and failure model

A mandatory versioned data policy supplies positive finite input bytes/pixels/bands, output bytes/pixels, memory/workspace, CPU/wall deadline, stream chunk/byte/time caps, per-organization preparation/download concurrency, pending/list/snapshot budgets, lease duration, maximum attempts, retry backoff bounds, retention and cleanup retry/deadline limits. Cross-field validation requires a chunk no larger than the output/stream budget, lease no longer than the job deadline, and workspace sufficient for source staging, candidate and download spool reservations. Callers cannot set or override these values.

This contract fixes no production numerical envelope from a two-file probe. Absence of a fully specified reviewed policy disables issuance. Synthetic tests use explicit small fixture policies; the public-sample experiment uses a separately recorded bounded local policy. Measure full inspector/preparation peak memory, workspace, CPU, output bytes and concurrency before selecting an operational policy revision. No throughput, price, quota or SLA promise follows from public-file size.

Before issuing any upload capability, durably register its exact owned output key, attempt and capability expiry as a cleanup obligation. Bind observed versions when storage reports them; an unobserved upload target remains a tracked obligation, not an unowned orphan. Cleanup starts only after the upload capability can no longer create/replace bytes, and removes only versions under that exact owned target. Orphan attempts and failed/canceled/expired jobs are never published. Cleanup operates only on this lane's exact owned keys/versions; it cannot enumerate/delete existing evidence or source artifacts. Lease/fence/retention checks prevent deletion of accepted live output. Revocation closes access first; retention removes derived bytes and leaves immutable job/receipt/audit history. Restart resumes unfinished cleanup; deletion failures remain visible and bounded, not silently marked deleted. Retention source obligations and backup responsibility remain operational gates.

Error envelope contains `reason`, safe `message`, `retryable` and allowed remediation, without secret paths or cross-tenant identities. Required classes: permission/rights/AI-egress/location denial; source unsealed/not measured/profile unsupported; bbox/grid/CRS/vertical mismatch; all-invalid/nonfinite source; input/output/workspace/concurrency limits; idempotency/fence/lease/report conflict; deadline/cancel; storage/integrity/currentness/audit unavailable. Authentication is generic `401`; unavailable scope/foreign resource is identical `404`; in-scope permission denial is `403`; changed idempotency/fence is `409`; strict body is `422`; concurrency is `429`; temporary unavailable dependencies are `503`. Worker terminal failures preserve exact typed primitive reason rather than exposing Python tracebacks.

## 8. Invariants and acceptance evidence

| Invariant | Enforcement required by this design |
| --- | --- |
| INV-020 | Observed CRS/grid/units and timestamp provenance are explicit; missing vertical/uncertainty stays unknown; no implicit transforms/comparison. |
| INV-024 | No RMSE, settlement, survey or absolute-accuracy claim; receipt always says accuracy not assessed. |
| INV-040 | Missing production authority/storage/inspection is closed; tests/fixtures never enter production fallback. |
| INV-043 | Source/license/attribution/modification chain is retained; no training authorized. |
| INV-050 | Current rights and execution-location/egress checked before preparation, not only at delivery. |
| INV-051 | Crop is a separate derivative tied to exact external input; cannot impersonate raw authority or successful managed ProcessingJob. |
| INV-053 | Delivery is not quantitative eligibility; existing V1/V2 analysis admission unchanged. |
| INV-054/055 | Exact runtime/image identity and immutable Core-owned finite policy; no caller override or managed-policy reinterpretation. |
| INV-060 | Organization from principal; scoped grants/queries/storage/worker fences; identical foreign-resource 404. |
| INV-061 | Existing Copilot allowlist unchanged; external AI purpose needs separate consent, no arbitrary code/SQL/storage access. |

Local acceptance requires all of the following, not imports or happy-path unit tests alone:

1. Schema/model/OpenAPI concordance, strict hostile inputs, no old-client/worker privilege widening; production composition stays closed without exact data dependencies.
2. Core/store contract and replay tests for frozen identities, scoped idempotency, concurrent quota reservation, lease takeover, cancellation, late reports, revoked/expired rights and immutable history.
3. Mounted local HTTP → distinct worker → private output → Core acceptance → external consumer flow; source/upload/output substitution and all failure cleanups exercised.
4. Download tests for reauthentication/scope loss, revoke between spool and headers, revoke midstream, missing audit/currentness, cross-tenant file/HEAD/Range, version substitution, no redirect/cache and bounded workspace/concurrency.
5. Public Floreat DSM/ORTHO pass the actual inspector before being used as measured sources; crop bytes, masks, affine, pixel window, bounds and hashes checked by an independent consumer. Failure is recorded, never bypassed by manufacturing a MEASURED report. Preserve the declared/observed ORTHO resolution discrepancy and unknown vertical reference.
6. Tests never depend on network or commit large sample binaries. Use small synthetic fixtures in CI; full licensed files are an explicit opt-in local experiment, including negative results and measured resources.

MCP/Console parity, customer Terra samples/use rights, OIDC, host/image/containment/backup verification, remote CI, two actual survey cycles and customer independent reuse/acceptance remain separate gates. This spec and local tests cannot close SDP-04/05/08 or the pilot.

## 9. Implementation decomposition and rollback

After written-spec approval, one task ledger will define exact files/interfaces/tests and ordered reviewable tasks: (1) strict event contracts and rights/policy models; (2) durable grant/job/lease/fence state and replay; (3) scoped public/worker routers with activation/default-closed assembly; (4) isolated worker and immutable output staging; (5) bounded authenticated download and cleanup; (6) mounted consumer/public-sample verification. Later MCP and Dashboard adapters use this verified common contract, not parallel calculations.

Do not edit Foundation behavior or refactor analysis/ingress broadly. Any extracted helper needs explicit dependency and regression evidence in the plan. Execute natively unless the Human chooses delegation; no concurrent writers in this dirty worktree. Preserve existing candidate worktree until its source is revalidated; do not assume it includes new main files.

Rollback: stop worker and disable only new data-lane assembly/activation, close new issuance/download, retain source catalogs and old analysis/managed journals. Clean only new owned orphan outputs through the bounded cleanup mechanism. Do not reset the worktree, erase audit/receipts, migrate old records, or restore whole files over pre-existing edits.

## Review gate

The approved decisions are native-grid DSM/ORTHO only, exact explicit grants and distinct worker authority, private preparation plus authenticated rechecked downloads, no public presigned URL/Range, and production disabled until a reviewed resource policy and isolation/activation exist. Written-contract approval is recorded above; review the [implementation plan](../plans/2026-09-30-spatial-data-delivery-v1.md) before execution. Remaining field/deployment gates are intentionally not guessed or described as completed.
