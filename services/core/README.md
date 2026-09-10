# services/core

KSI Core: identity, site, Mission Contract, event workflow, map/model registry and audit.

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

`POST /v1/sites/{site_id}/observation-work-orders` defaults to a managed
`MANAGED_ACQUISITION` WorkOrder. Supplying `EXTERNAL_RECONSTRUCTION` creates an
already-approved customer artifact registration request with no schedule and no
acquisition callback. The request requires `Idempotency-Key`; Core journals its
hash and normalized request fingerprint, never the raw key. Retrying the same
request returns the current WorkOrder without a second create event; reusing the
key for another request is a conflict. Managed callers may also supply a key and
receive the same retry protection.

ADR-KSI-036's bounded ingress is available only when the shared assembly supplies the durable
journal and supported evidence storage. Storage-less development assembly deliberately has no
external-reconstruction routes: it cannot safely issue a digest-bound upload capability or make a
server object observation. The five-route flow is:

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
