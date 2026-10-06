# Spatial Data MCP V1 — scoped AI discovery and native preparation

Spec ID: SDP-CLIENT-01-AI
Status: HUMAN-APPROVED detailed contract; implementation plan review pending, no runtime activation.
Approval: Human selected “명세 승인, 구현 계획 작성” for commit204c90a on2026-10-06.
Approved proposal SHA256: `7ef7a677b20b04e5407796bd1a1266b8e31dac2d762fcddbd0e65b560e7c9c93`.
The proposed-language body below is the reviewed contract, preserved without semantic edits.
Date: 2026-10-06
Human direction: selected “전용 로컬 데이터 MCP (추천)” from the rendered architecture question.
Approved direction: dedicated local stdio adapter, explicit Core AI identity/consent boundary,
small state/evidence/result references, authenticated HTTP file delivery; no remote/install/deploy.
Scope ledger: `../plans/2026-10-06-spatial-data-product-continuation.md`.
Baseline: main `ee12062b6d780c5c4f5b9b92eaa3c8056beb1e83`; V1 delivery and Analysis remain intact.

## 1. Intent, authority and success

An authorized external agent should find a permitted DSM/orthophoto asset in one supplied
Site/WorkArea, request a native-grid rectangle, poll the durable job and hand the same Core
receipt/file reference to a permissioned external program. On the next observation it selects
a new exact asset revision while reusing the allowed WorkArea and request template. An MCP
tool never reconstructs, calculates a volume, invents rights or stores a second job authority.

Authority: Constitution → Decision Ledger → PRD §1.1.2 SDP-REQ-01/02/03/05/06/07/08;
ADR036/037/038; Human-approved SDP-DATA-01
`2026-09-30-spatial-data-delivery-v1-design.md`. Existing quantitative V1/V2, source identity,
historical records and EXT-VAL acceptance remain unchanged. This is the client/AI boundary
successor, not a replacement crop/analysis implementation or product-wide completion claim.

Local acceptance: real authenticated mounted HTTP and official SDK stdio calls expose the
same asset/job/receipt IDs, strict typed restrictions and no raw secrets; a separate HTTP
consumer obtains exact generated crop bytes with fresh current rights. Revocation, cross-tenant,
purpose downgrade and restart cases must fail closed. Real host/client/customer acceptance is separate.

## 2. Reuse and alternatives

| Existing asset | Decision | Constraint |
| --- | --- | --- |
| Core Spatial Data V1 jobs/grants/source/worker/download/audit | ADOPT | Same native-grid request, durable ID/fence, receipt and guarded file transport; no second engine |
| SpatialAssetCatalog opaque assetRef and bounded source enumeration | ADOPT internally | Existing metadata catalog HTTP permission/VIEW_METADATA contract stays unchanged |
| Analysis MCP SDK stdio framing and closed typed HTTP patterns | REFERENCE_ONLY | No Analysis credential, permission, activation, response limit or egress acknowledgment inherited |
| HTTP-only native_window_client | ADOPT exact-byte consumer concept | Client receives no internal stores, output key, upload grant or worker capability |
| Existing trusted principal registry/currentness coordination | ADOPT | New identity is explicit operator-provisioned authority, never client input |
| References repositories | REFERENCE_ONLY | No runtime imports or reference edits |

Separate adapter is recommended over widening Analysis MCP because data-job authority and AI
metadata eligibility differ. A Console-only successor would not prove external agent reuse.
Remote MCP expands deployment/auth/shared-resource scope and is excluded from this first contract.

## 3. Explicit identity and egress rule

Proposed additive principal kind: `SPATIAL_DATA_MCP_CLIENT`. It has no role/device and requires
nonempty explicit Site and WorkArea scopes. Its fixed permissions are SPATIAL_DATA_READ and
SPATIAL_DATA_REQUEST only; no SITES_READ, Analysis, worker, grant provisioning or flight permission.
Its exact route allowlist is the six existing public data route-method pairs plus the two
new scoped data-discovery GETs below. Old principal kinds and their allowlists remain identical.

Core derives external-AI purpose from this authenticated identity. A caller header/tool text
cannot select general data use. POST must carry EXTERNAL_AI; GENERAL_DATA_USE is refused rather
than silently rewritten. Creation retains original V1 payload/idempotency semantics.

For AI metadata and bytes, Core requires all of:

1. Fresh authenticated organization/principal, exact Site/WorkArea and source WorkOrder binding.
2. Current Site `aiEgressAllowed=true`, with dependency failure denying access.
3. Exact current data grant benefiting that principal and source asset, allowing EXTERNAL_AI
   and READ, with valid license/provenance evidence, processing location and validity interval.
4. Additional PREPARE operation for issuance; native pixel-expanded bounds inside the grant.
5. Current measured source, policy/runtime/activation dependencies where V1 requires them.

This spec proposes that a current EXTERNAL_AI+READ data grant authorizes only the explicitly
listed metadata projection for its exact asset. It creates no general metadata sharing right.
This is a new reviewed AI-use boundary, not a claim that generic V1 grants already implement it.

Apply the AI gate to discovery, create/retry, list/status/receipt, cancel response and file
GET/HEAD. Check consent and identity immediately before publishing metadata; existing download
currentness repeats before headers and each chunk. Core returns a distinct acknowledgment
`X-KSI-Spatial-Data-AI-Egress: ALLOWED` only after this gate passes for the new AI principal.
The adapter refuses any successful response without it. It is an attestation of this response's
authorization check, not a credential, standing permission or independent accuracy proof.

Generic V1 history deliberately survives grant expiry/revocation; preserve that behavior for
operators/generic data clients. AI reads are stricter: deny the entire source/receipt payload
if current AI rights/consent lapse. Return a safe typed refusal, not stale metadata or a partially
redacted old receipt. Do not silently change historical execution state or delete the receipt.
Job reads use the job's exact frozen grant revision/digest and source binding: a newly issued
grant cannot resurrect access to an old revoked job. Discovery of a new grant remains a separate
current asset projection, and new issuance requires its own request/key under existing V1 rules.
For this principal, accessing a GENERAL_DATA_USE job is a generic non-disclosing404 even if
someone supplies its ID; metadata/bytes cannot be moved into AI use by a request header.

No account/token/consent/grant editor or provisioning API is added. Tests explicitly inject
generated principals/grants; default production assembly remains closed without existing
independently authorized data dependencies. Config files do not approve those dependencies.

## 4. Grant-aware discovery without widening the metadata catalog

Proposed additive routes:

- `GET /v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-assets`
- `GET /v1/sites/{site_id}/work-areas/{work_area_id}/spatial-data-assets/{asset_ref}`

Mount only with the complete existing data graph. Internally resolve authentic sealed sources
and current beneficiary grants; never create an ADMIN Principal or bypass owner methods.
Accept only inspected native DSM/ORTHO sources under the V1 profile. Unsupported/unsealed/
unmeasured sources are not preparation-ready. Exact superseded sealed assets remain addressable
only if current grants explicitly bind them; no latest substitution.

List results only after scope and current AI+READ grant filtering. Counts/cursors never reveal
ungranted assets. A grant that lacks PREPARE may expose permitted metadata and READ without
advertising preparation. Require exactly one applicable current AI READ grant per discovered
asset: omit ambiguous assets from listing, never union their rectangles. An otherwise scoped
direct detail with ambiguous current grants returns AMBIGUOUS_GRANT without a source payload.
Foreign/unknown/ungranted detail has the same404. Missing scope or consent is checked before
enumeration and before source-specific details. No unbounded scan of all tenants or grant history.

Strict new response family: `SpatialDataAssetViewV1` / `SpatialDataAssetPageV1`, frozen camelCase
models, forbid extras/nonfinite values, exact asset/digest formats. Project only:

- assetRef, Site/WorkArea, WorkOrder/Epoch, submissionRef/revision/artifact kind;
- SEALED/SUPERSEDED lifecycle, observed byte digest/size and exact inspection/report bindings;
- observed CRS identifier/digest/units, known vertical reference or explicit null;
- native grid affine/resolution and band/dtype facts required to select an exact pixel crop;
- `permittedBounds`: the exact grant rectangle intersected with inspected source extent;
- declared capture/processing timestamps labelled DECLARED, not inspector observations;
- currently permitted READ/PREPARE actions, safe restrictions and attribution/modification terms;
- accuracyAssessed=false, analysisStatus=NOT_EVALUATED and no generalized suitability claim.

Do not expose raw submissionId, filename, customer free-text tags, full source footprint unrelated
to the grant, internal object key, token, capability, worker/source URL or confidential policy.
Grid origin is a coordinate fact, not permission to sample outside permittedBounds. A caller must
still obtain V1 admission for its actual expanded crop. Missing vertical reference is reported
unknown; it does not invent a height or categorically deny unmodified raster delivery.

Pagination uses stable assetRef order, caller-supplied positive bounded limit and opaque cursor.
Bind cursor to organization/principal/Site/area, source and relevant grant/consent projection
snapshot. Recheck authorization every page; changed relevant snapshot returns a typed stale
cursor conflict and requires restarting listing. No stale cursor bypass or client sorting oracle.
Reuse existing finite catalog backend budgets plus explicit data-policy list/snapshot/JSON limits.
Overage is an explicit refusal, never a truncated success or an unlimited enumeration helper.

## 5. Existing job semantics and exact file reference

Public data create/list/status/cancel/file routes keep V1 shapes and IDs. Only the dedicated
AI principal gains the extra gates above. Worker authority, lease/fence/report validation,
geometry, retry, retention and cleanup stay owned by current V1 participants.

For AI job listing, filter scoped owned EXTERNAL_AI jobs and currently export-permitted metadata
before pagination. An empty authorized page does not disclose denied jobs. Direct retrieval of
a denied known job returns the same safe refusal without leaking its receipt/source. Cancellation
for AI clients requires current AI metadata permission and existing request/ownership authority;
an operator retains the existing cancellation/diagnostic path if AI consent is revoked.

The MCP result reference is a strict STRUCTURED descriptor, not a new public URL/capability:
`{referenceVersion:"spatial-data-file-reference.v1",siteId,workAreaId,jobId,method:"GET",
relativePath,outputSha256,outputSizeBytes,authenticationRequired:true,rangeSupported:false}`.
The canonical relativePath is the existing Core file route instantiated from the authorized
response's validated scope/returned job ID. No arbitrary origin/query/header/token, mutable
path, storage key or untrusted filename. Expose it only for
COMPLETED+AVAILABLE under a current AI READ grant, with digest/size taken from the same receipt.

The dedicated adapter derives this descriptor deterministically from the authorized Core view
and the canonical existing file route; it cannot assert AVAILABLE absent from that view. Typed
model validation and exact route/value tests are mandatory. It is not advertised as an MCP
ResourceLink or read_resource: stdio clients do not automatically authenticate an HTTP URL.

Define `SpatialDataFileReferenceV1` for that strict descriptor and `SpatialDataMcpJobViewV1`
as `{job: SpatialDataJobViewV1, fileReference: SpatialDataFileReferenceV1|null}`. Only the get
tool returns this wrapper; create/cancel return the original V1 job model. This is an adapter
projection, not a change to the Core V1 view schema or a second availability decision.

A separate permissioned external consumer composes the relative path with its configured exact
Core origin and reads an independently supplied matching credential. Core must recheck that
credential's own rights; the descriptor does not transfer the creator's grant or job ownership.
V1 permits only the owner principal or scoped operator administration to view/download the job.
The first example uses the same pre-authorized requester principal outside MCP, with no credential
value passed in tool arguments/results. Recipient-sharing/credential delegation is excluded.

Use existing no-redirect/no-cache/no-Range full-spool integrity and chunk-currentness transport.
MCP tools transfer no raster bytes, base64 blobs, arbitrary filesystem output, credentials or
signed storage link. No promise to recall downloaded copies or detect undeclared eventual use.

## 6. Local stdio adapter and fixed tools

Owner: independently started `services/spatial-data-mcp/` (runtime lifecycle, not a library).
Core keeps HTTP/authority in `services/core/src/ksi_core/domains/external/delivery/`; strict shapes in
event-contracts/contracts. No new raster worker or standalone policy/calculation service.
No changes to Analysis MCP entrypoint/tool set, existing Copilot INV061 allowlist or device APIs.

Proposed fixed tools:

| Tool | Arguments | Authoritative response |
| --- | --- | --- |
| ksi_list_spatial_data_assets | Site,WorkArea,limit,cursor | New grant-filtered page |
| ksi_get_spatial_data_asset | Site,WorkArea,assetRef | Exact granted asset projection |
| ksi_create_spatial_data_request | Site,WorkArea,assetRef,requestedBounds,observedCrsDigest,idempotencyKey | V1 job; adapter supplies NATIVE/EXTERNAL_AI, no policy/transform knobs |
| ksi_list_spatial_data_requests | Site,WorkArea,limit,cursor | V1 page after AI filtering |
| ksi_get_spatial_data_request | Site,WorkArea,jobId | SpatialDataMcpJobViewV1: exact V1 job plus optional file reference |
| ksi_cancel_spatial_data_request | Site,WorkArea,jobId | Existing V1 idempotent cancellation result |

Reads are read-only, create/cancel are mutations even though idempotent. Annotations describe
behavior, not authorization or automatic approval. No tool that polls forever; callers invoke
get again with the same ID, never recreate after timeout using a different key automatically.
Unknown tool, malformed IDs/bounds/cursor or caller-supplied purpose/organization/URL/headers
fail before transport. Each result schema matches the actual structured result, no arbitrary JSON.
Validate response scope against the actual call: Site/WorkArea on every item/view, jobId on get/
cancel, assetRef on create/detail. A model-valid but substituted response fails before any MCP
result/reference is emitted; identifiers are never silently corrected to make it fit.

Use existing locked mcp==2.2.0 only if its actual installed API passes the SDK handshake tests;
no automatic install/upgrade or FastMCP wrapper migration. Current official v2 docs consulted:
`https://py.sdk.modelcontextprotocol.io/v2/whats-new` and `/v2/migration` on2026-10-06 via Context7.
Constructor callbacks, typed tool schemas and explicit structured CallToolResult/is_error are
the v2 pattern. Exceptions must be sanitized explicitly; upstream examples printing str(exc)
are NOT adopted. stdout is reserved for MCP frames; safe diagnostics use stderr without body,
token, URI query, input values or protected path. Cancellation does not print a traceback.

Configuration is an explicit owner-protected JSON file plus a separate absolute0600 token file;
no bearer in environment/command arguments/config/tool parameters. Re-read the token before each
HTTP call; reject symlink ancestors, non-owner/hard-linked/changed files and unbounded contents.
Exact Core origin is HTTPS, except literal loopback HTTP for tests/local software verification.
Reject userinfo/query/fragment/base path, ambient proxy and redirects; TLS stays verified.
No account creation, credential renewal/signing agent, server installation or AI host config write.

Finite explicit adapter limits: request/structured-response bytes, connect/read/pool/overall call
deadline, concurrent in-flight calls, cursor/identifier bytes. Choose concrete fixture values in
tests and require owner-supplied positive finite values for real use; no inferred production quota
from Analysis512KiB/coverage64KiB limits. A canceled/timeout call closes response/session resources.
No response truncation, compressed-body ambiguity, duplicate/nonfinite JSON or oversized stdout.

## 7. Security, errors and compatibility

401 is generic authentication refusal; foreign/missing scope/unknown asset/job404 identical;
in-scope AI consent/right refusal403 without denied payload; stale cursor/idempotency409;
strict request422; finite concurrency429; dependency/currentness/audit unavailable503.
Adapter errors are a closed safe code envelope with is_error=true. Never forward raw Core
response/HTTP exception/body/path. Preserve valid existing V1 reason/remediation meaning.

An EXTERNAL_AI grant expiring during a long file transfer closes chunk emission through current
V1 checks. For metadata, reauth/consent/current READ check immediately before response; already
sent metadata cannot be recalled. Job/receipt digest signatures are integrity/identity facts,
not grant approval, license verification by themselves or accuracy certificates.

Invariants: INV020 coordinate/time/unknown facts explicit; INV024 no accuracy/settlement claims;
INV040 production default-closed/no generated fallback; INV043 attribution/rights; INV050 Core
purpose/location/consent checks before use; INV051 derived lineage unchanged; INV053 V1/V2
quantitative eligibility unchanged; INV054/055 existing pinned runtime/finite policies preserved;
INV060 organization/all relevant source scope and404 non-disclosure; INV061 no Copilot/tool
authority escalation, arbitrary GIS/SQL/storage/flight access or undeclared AI transmission.

## 8. Observable acceptance and negative matrix

1. Strict model/schema/OpenAPI/advertised MCP input-output concordance; unknown fields/types,
   malformed/nonfinite geometry, stale cursor and oversized/duplicate/compressed JSON rejected.
2. New principal validation/route allowlist exact; old Analysis/generic data/worker/operator
   permissions byte-for-byte equivalent in tests; no ADMIN fallback or general-purpose token.
3. Genuine generated GeoTIFF ingress/inspection, explicit generated grant/activation and
   currentness participant → Core discovery → actual SDK stdio create/get → existing distinct
   worker → same receipt → separate HTTP consumer verifies source slice/affine/mask/hash.
4. No granted asset yields empty scoped list; unknown/foreign/ungranted detail equivalent404;
   all relevant WorkArea requirements enforced. Filter before pagination; caps before enumeration.
5. EXTERNAL_AI consent/rights withdrawn before discovery/create/list/status/receipt/cancel/file:
   no protected payload or bytes, no misleading successful egress acknowledgment. Old generic
   completed history remains available to its otherwise authorized requester.
6. GENERAL_DATA_USE job and purpose/header downgrade denied for new AI principal; operator and
   Analysis credentials cannot impersonate it. Missing/wrong AI acknowledgment fails adapter.
7. Grant/license/processing-location/source/policy/currentness mismatch, grant ambiguity, partial
   pixel authorization, unmeasured source or missing source scope cannot advertise preparation.
8. Same scoped key/body gives same job after stdio/client/participant restart; changed body409;
   lost response does not generate a new key or job. New observation binds new asset/source,
   not an earlier receipt. SDK client conformance is not an installed host/customer claim.
9. File reference has exact scope/job route/digest/size, no secret/capability/origin or raw bytes.
   Following it with unrelated/no credential fails; revocation before headers/midstream keeps
   existing V1 behavior. Consumer publishes no partial or overwritten local file.
   Model-valid wrong Site/area/job/asset responses and misleading file-reference values are refused.
10. Independent reviewer and test-runner verify frozen scoped/replay/full/static/package/stdio
    checks; real server/API changed-flow and reload evidence where applicable. No visual change
    or browser-only screenshot can stand in for authenticated stdio/HTTP parity.

## 9. Exclusions, sequencing and rollback

No reprojection/resampling/polygon mask/Range/tiles, point-cloud/mesh/external-layer contract,
webhook/feed/resync, recipient sharing, arbitrary SDK/remote MCP host support or provider export
guarantee. These remain future detailed contracts, not undisclosed defaults.
No actual customer3epoch/rights/accuracy/host/signer/backup/customer acceptance or price/SLA
claim. Public sample acquisition is not inspected/accepted bytes. Tests decode generated owned
TIFFs through the existing genuine parser and permitted local harness only.

After Human written-spec approval, write an exact implementation plan and select execution:
contracts → principal/Core AI metadata guard → grant-aware discovery → adapter → SDK/HTTP
integration/restart/negative tests → independent verification/owned commit. Live grants/consent,
installation/client configuration, push/deploy remain separately authorized.

Rollback disables only new adapter and new AI/discovery route activation. Preserve all generic
V1 jobs/grants/receipts/audit/worker and Analysis history/semantics. Additive principal routes
fail closed when new wiring is absent; no rewriting old events or erasing denied-use evidence.

## Written-spec review gate

Passed on2026-10-06: Human approved the exact299line proposal above at commit204c90a/SHA7ef7a677
and requested implementation planning. New principal/metadata-right/routes/tools/reference and
resource configuration are approved design, not implemented wire/runtime evidence. The next
implementation-plan review and execution-method gate remains. Nothing in this file enables real
data egress, installation, credential/grant issuance or production activation.
