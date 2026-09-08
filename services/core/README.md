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
