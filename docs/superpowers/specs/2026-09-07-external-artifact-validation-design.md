# External artifact validation design

Date: 2026-09-07
Status: **APPROVED D5 detailed design — approved by the Human on 2026-09-07; implementation still requires separate Human approval of an executable plan.**
Approval provenance: the Human approved this complete design in the current turn; the pre-annotation full-document SHA-256 is `bc0267d4095895bcb99042cf277129cf3a2b6300f43c1f82a914aa7056f13c25`. This approval does not approve a policy, threshold, compatibility mapping, invariant amendment, deployment, customer data, or release.

## Decision boundary

This document responds to [ADR-KSI-036 D4/D5](../../architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md) and slice 3 of the [external reconstruction release plan](../plans/2026-09-06-external-reconstruction-release.md). It is documentation only: it neither implements code nor changes contracts, schemas, invariants, policy, deployment, or customer data.

The accepted direction is that customers operate reconstruction, KSI registers derived artifacts, the processing worker measures supplied bytes, and Core owns durable versioned decisions for a stated use. The Human approved this D5 design on 2026-09-07. It specifies the missing contracts, policy, security, and acceptance work; approval of this design is not approval of any policy, threshold, compatibility mapping, implementation, deployment, customer data, or release.

### Authority, requirements, and acceptance

- Requirements: REQ-INT-101 through REQ-INT-104, REQ-SEC-101, REQ-OPS-102.
- Invariants: INV-024, INV-051, INV-053, INV-060.
- Product authority: [Constitution](../../product/PRODUCT_CONSTITUTION.md), [decision ledger](../../product/FINAL_DECISION_LEDGER_v1.0.md), [Master PRD](../../product/MASTER_PRD_v3.0.md), and [invariants](../../product/DOMAIN_INVARIANTS.md).
- Routing authority: [repository structure](../../../REPOSITORY_STRUCTURE.md) and [document status](../../DOCUMENT_STATUS.md). Core owns identity, policy, journal, and decisions; processing-controller measures bounded input; event-contracts is import-only.
- Existing ingress is prerequisite only: [Core ingress documentation](../../../services/core/README.md#customer-owned-external-reconstruction-ingress) and [local ingress verification](../../audit/EXTERNAL_RECONSTRUCTION_INGRESS_API_VERIFICATION.md).

A future implementation must inspect sealed external revisions without turning them into a managed ProcessingJob, ArtifactRef, source bundle, source-media authority, or managed profile. It must persist immutable evidence and decisions per exact revision/use, separate the four uses below, and fail closed for parser, tenant, queue, lease, or replay faults. Missing approved trust, accuracy, or compatibility policy remains an explicit release blocker.

### Explicit non-goals

- This does not select a vendor, approve export compatibility or licenses, require a workstation client/signer, transfer raw photos, deploy, or accept customer data.
- A signature or hash binds a declaration or bytes to a key; it does **not** prove capture truth, input completeness, CRS/vertical truth, accuracy, or compatibility. No new workstation signer/client is required or approved.
- No contract-settlement, survey-grade, absolute accuracy/RMSE, progress percentage, or measured-change claim is proposed.
- No numerical accuracy, byte/pixel, timeout, retry, concurrency, or resource threshold is invented.

## Architecture and fact authority

~~~text
authenticated human -> Core register/seal -> sealed external revision
                                           -> Core idempotently queues inspection
processing-controller <- leased Core input <- Core
processing-controller -> measured report/rejection (fenced write) -> Core journal
authenticated human -> Core requests one use or exact pair/zone use
Core -> evaluates immutable evidence + policy snapshot -> durable decision
Console -> displays evidence/restrictions; never infers eligibility
~~~

| Class | Examples | Authority and limit |
|---|---|---|
| Declared | producer/version, asserted CRS or vertical reference, capture window, local-input digest | Customer statement only; cannot prove bytes, capture truth, accuracy, or compatibility. |
| Observed | sealed key/digest/size/content type; raster metadata, footprint, bands, nodata, layout | Server/worker measurement of exact sealed bytes. Successful parsing states only that specified parser checks succeeded. |
| Independently substantiated | approved policy, trusted evidence record, checkpoint-validation result, benchmark/compatibility record | Core versions supporting evidence. Policy specifies acceptable evidence; it cannot create missing evidence. |

An inspection report labels every fact with that class and binds observed facts to manifest entry SHA-256 and inspector build digest. Its canonical, deterministic `measurementPayload` contains only exact input bindings, parser/policy build identities, per-artifact outcomes, and measured/rejection facts; `measurementPayloadDigest` covers that payload. The separate report envelope contains request/report IDs, attempt/execution time, worker identity, and lease fence and is not included in that digest. An exact transport retry has the same request, fence-valid attempt semantics, and payload digest and is deduplicated; a recomputation with different inputs, parser build, or policy must issue a new request rather than overwrite a prior payload. The report is evidence for Core, not an eligibility decision. UI must not flatten the classes into “verified capture” or “accurate reconstruction.”

## Proposed immutable contracts and identities

The existing external identity stays authoritative: organization, site, frozen observation epoch, raw submission ID, positive revision, returned opaque submission ref, submission digest, and sealed manifest digest. New IDs are server-generated/opaque, never filename/path/URL or a mutable latest reference. Public addressing remains returned submissionRef, never raw customer ID.

| Proposed additive contract | Required binding | Purpose and forbidden meaning |
|---|---|---|
| ExternalArtifactInspectionRequestV1 | request ID; exact sealed revision and both digests; inspection-policy ID/version/digest; idempotency key | Durable work intent, never a managed job or client-selected resource limit. |
| ExternalArtifactInspectionReportV1 | report/request IDs; exact digest pair; inspector build digest; deterministic measurementPayloadDigest; per-artifact outcomes | Byte measurement, never producer truth or eligibility. |
| ExternalEvidenceDeclarationV1 / ExternalEvidenceManifestV1 | separate evidence ID and manifest ID; exact target DSM subject, manifest entry, and digest; server-scoped key; declaration/observed digest pair | Additive evidence ledger one-way linked to the unchanged submission manifest; never an artifact-grant extension or source authority. |
| ExternalEvidenceValidationRequestV1 / ExternalEvidenceRecordV1 | validation request ID plus exact evidence-manifest and DSM digests; worker measurement payload; Core validation result | Bounded validation lifecycle and outcome for checkpoint/trust/benchmark evidence, never customer-supplied measured numbers. |
| ExternalValidationPolicyV1 | policy ID/version/digest; grammar/parser build; resource-envelope digest; trust and compatibility rules; status | Core policy registry. Missing, inactive, or unvalidated policy cannot admit a positive quantitative decision. |
| ExternalUseDecisionV1 | decision ID; one exact subject; use; policy snapshot; ordered report/evidence digests; verdict/restrictions | Core decision for one use, never mutable in place. |
| ExternalPairUseDecisionV1 | ordered baseline/current; use; policy/evidence digests; volume zone ID/revision/digest | Core pair decision, not a broad site/producer/epoch approval. |

The contract family uses strict UTC timestamps, closed enums, bounded collections, no undeclared fields, and canonical JSON digests excluding only their own digest field. The scope tuple repeats in durable events and is checked against the sealed revision before transition/replay. Reports identify artifacts by manifest entry ID and observed SHA-256, not filename lookup. A complete revision report contains one outcome for every sealed artifact: `MEASURED`, `NOT_APPLICABLE`, or typed `REJECTED`, each with its own evidence/reason. A bad optional DSM produces a DSM outcome and blocks only dependent uses; a usable ortho can still support display. Only manifest-digest, subject-scope, or sealed-byte trust failure invalidates the whole revision report. Declared or observed facts cannot satisfy an independently-substantiated policy rule.

DISPLAY and HEIGHT have one revision subject. VISUAL_COMPARISON and RELATIVE_VOLUME have ordered baseline/current subjects. Volume also binds a sealed zone-definition digest plus zone CRS/vertical declaration and observation. Same subject/use/policy/idempotency key returns the original receipt; same key with different canonical input conflicts. Correction, new policy, or new evidence produces another inspection/decision; old records remain immutable.

## Per-use semantics

Verdicts are ELIGIBLE, RESTRICTED, or BLOCKED with stable typed reasons. Restricted is not a hidden quantitative pass. No client may substitute zero, “validated,” or an accuracy number.

| Use | Scope | Positive semantic, if policy/evidence allow | Minimum proposed prerequisite | Example blocker |
|---|---|---|---|---|
| DISPLAY | one revision | Georeferenced **sanitized map path** to inspected ortho, limited to parser-observed footprint and CRS. | Sealed ortho; safe GeoTIFF/COG parse; observed georeference/transform/footprint; sanitization policy; tenant scope. | ORTHO_MISSING, GEOREFERENCE_MISSING, DISPLAY_SANITIZATION_GAP. |
| VISUAL_COMPARISON | ordered pair | Common-area spatial visual comparison of sanitized orthos; **not measured change**, quantity, progress, or accuracy. | Both display paths; compatible observed CRS and registration/transform evidence; policy-defined common-area/temporal evidence. | PAIR_CRS_MISMATCH, COMMON_AREA_EMPTY, REGISTRATION_EVIDENCE_GAP. |
| HEIGHT | one revision | Operational DSM surface elevation at valid coverage, always with explicit observed vertical reference and uncertainty/unknown state; never survey elevation. | Parsed sealed DSM; observed CRS/vertical reference; finite in-coverage non-nodata query; approved external-evidence/uncertainty policy and required independent evidence. | DSM_MISSING, DSM_VERTICAL_REFERENCE_UNKNOWN, DSM_NODATA, UNCERTAINTY_EVIDENCE_GAP. |
| RELATIVE_VOLUME | ordered pair plus zone | Operational relative quantity in exactly one sealed zone, with CRS, vertical reference, uncertainty, and limitations; never settlement/survey quantity. | Both DSM paths; pair compatibility; common valid coverage; sealed zone; approved compatibility plus checkpoint/uncertainty evidence. | PAIR_PROFILE_MISMATCH, VERTICAL_REFERENCE_MISMATCH, CHECKPOINT_EVIDENCE_GAP, COMPATIBILITY_MAPPING_MISSING. |

“GeoTIFF/COG first” permits only GeoTIFF-family bytes after an approved policy names the exact grammar and parser build; COG is preferred for display/streaming layout. It is not blanket producer compatibility. Point cloud, DTM, mesh, archives, and vendor packages need separate contract/security/acceptance decisions.

Ortho-only registration remains valid. Missing DSM limits HEIGHT and RELATIVE_VOLUME only; it does not prevent inspected display or non-quantitative visual comparison. **The absence of a raw upload to KSI is not** a global failure or permanent quantitative ban. Separately, unknown or missing originals retained by the customer can block only a dependent source-lineage policy; they do not invalidate unrelated inspected ortho uses.

### Restrictions and remediation

Every decision returns a typed reason plus a permitted remediation, never a request to edit server-observed facts. DISPLAY may direct the customer to submit a newly sealed export with supported georeferencing or wait for an approved sanitization policy; it must not invite manual CRS assignment. VISUAL_COMPARISON may request a newly inspected pair with valid common-area/registration evidence, not label visual overlap as measured change. HEIGHT may request an independently re-exported DSM with explicit vertical reference, valid coverage, and policy-required uncertainty evidence; it cannot derive height from ortho. RELATIVE_VOLUME may request a new exact zone, compatible inspected pair, approved compatibility mapping, and required independent checkpoint/uncertainty evidence; it must not reuse an unrelated zone or manually supplied quantity. A missing policy, trust rule, resource envelope, benchmark mapping, or invariant clarification is remediated by the authorized policy/product process, not by customer metadata or a client retry.

## INV-053 preservation and external readiness

INV-053 requires quantitative comparison to have compatible Analysis Readiness, versioned processing profile, CRS, vertical reference, and original source lineage; automatic compatibility currently means matching processingProfileDigest. External registration must not imitate managed identities or silently waive these conditions.

This design has two layers:

1. ExternalArtifactInspectionReportV1 is external evidence only. It cannot call itself Analysis Readiness, Processing Profile, source-bundle digest, or source authority.
2. Before HEIGHT or RELATIVE_VOLUME release, Product Authority must approve a precise invariant/ADR clarification for an **external equivalent readiness evidence profile**: coverage/capture/temporal/media/provenance evidence; immutable external profile ID/digest; CRS and vertical compatibility; source-lineage meaning; and its relation to existing Analysis Readiness without changing managed records. The approval must say whether it is a permitted INV-053 processing-profile analogue or INV-053 is amended.

This is an authority decision, not an implementation waiver. The policy registry is non-vacuous: it retains reviewable versioned evidence requirements and compatibility mappings so Core can make a positive decision when clarification, policy, evidence, and acceptance all exist. Synthetic policies prove ingestion/evaluation/idempotency/replay mechanics only; they do not prove compatibility, thresholds, capture truth, or release accuracy.

After authority approval, equality of immutable external-evidence-profile digest may be the only proposed automatic compatibility. Cross-profile use needs explicit versioned benchmark-backed mapping, bound by digest to permitted use, producer/engine/version/configuration evidence, and its evidence record. Labels, hashes, and signatures are insufficient.

INV-024 remains: no absolute RMSE without independently validated checkpoints. Producer-entered RMSE, RTK assertion, hash, or signature is insufficient. If policy needs checkpoints, the worker reads sealed DSM plus independently sourced sealed checkpoint evidence and Core records validation. This design sets no threshold. INV-051 remains because external DSM/ortho stays derived, never source authority. INV-060 remains because Core derives scope from Principal/server records and cross-tenant responses are non-disclosing.

## Queue, leases, retry, replay, and reconciliation

Core owns durable queue state; processing-controller executes one leased inspection. It follows the existing QUEUED plus lease-expired RUNNING pattern, Core-issued acquisition/generation fences, and fenced worker writes, but never reuses managed ProcessingJob state.

~~~text
SEALED --no selected policy--> INSPECTION_PENDING_POLICY (visible; no fabricated job)
SEALED --selected policy--> INSPECTION_QUEUED -> INSPECTION_RUNNING -> INSPECTION_REPORTED
                                |                      -> usable Core evidence
                                +-> artifact parser/resource failure -> ARTIFACT_REJECTED in complete report
                                +-> request identity failure -> INSPECTION_FAILED_INCOMPLETE
                                +-> retryable queued attempt (bounded durable retry)
expired lease -> claimable queue work
~~~

- Existing seal events remain unchanged. After seal, Core writes a separate durable inspection-issue event keyed by the sealed subject and a selected inspection-policy digest; it does not claim a cross-journal atomic seal/enqueue transaction. If no approved policy is selectable, Core exposes INSPECTION_PENDING_POLICY and creates no job. Startup and periodic reconciliation scan sealed revisions, including historical sealed revisions, and issue the same request once a policy is selectable.
- Natural key is sealed subject tuple plus inspection-policy digest. A Core uniqueness lock plus idempotent issue operation prevents seal notifications, races, crash/restart, and reconciliation from creating competing work. Policy selection is pinned at issue; a later policy creates a new request rather than modifying the issued request.
- Claim retry retains acquisition ID; Core returns positive generation and worker identity. Input read, heartbeat, report, rejection, and transition carry the fence. Stale/wrong worker is rejected; expiry never permits stale completion.
- Artifact parser or artifact-scoped resource rejection is terminal only for that artifact: it is ARTIFACT_REJECTED in an otherwise complete INSPECTION_REPORTED revision report, so a malformed optional DSM cannot reject a valid ortho. Only MANIFEST_DIGEST_MISMATCH, SUBJECT_SCOPE_MISMATCH, or SEALED_BYTE_IDENTITY_MISMATCH invalidate the complete report. Request-wide resource exhaustion before every artifact is examined is INSPECTION_FAILED_INCOMPLETE: it fabricates no outcome for unexamined artifacts; any previously completed artifact evidence is usable only after a separately durable Core validation. Storage/network/service failure is retryable only under Core’s versioned retry/resource policy. Attempt count, typed failure, next time, and policy digest are journaled. Exhaustion is INSPECTION_RETRY_EXHAUSTED, never success.
- Identical input, inspector build, and policy produce the same measurementPayloadDigest. Core accepts one fenced payload, deduplicates an exact retry, rejects a divergent payload for that issued request, and replay verifies scope/digest/fence/order/payload digest. A permitted recomputation is separately issued and never replaces history.
- Use-decision idempotency is separate, keyed by subject/use/policy/ordered evidence digests. Core, never worker, evaluates eligibility.

## Routes, tenant boundary, and byte security

| Intent | Proposed surface | Guard |
|---|---|---|
| Read inspection/decision | scoped revision GET inspection and GET use-decisions | SITES_READ; scoped WorkOrder/org from Principal; cross-tenant same as absent. |
| Request decision | scoped revision POST use-decisions | Human SITES_WRITE; body requests use and opaque pair/zone refs only, never policy, scope, observed facts, or verdict. |
| Worker work plane | internal list/claim/input/heartbeat/report/reject | processing-controller principal only; human/dashboard/device/engine principals cannot claim/submit facts. |
| Policy/evidence admin | separate controlled Core authority route | Future policy-admin permission/audit; customer route cannot activate policy. |

Every mutation has an idempotency key scoped to Principal, organization, operation, and canonical body. Do not disclose raw IDs, filenames, keys, parser internals, URLs, credentials, or other tenant policy/evidence identity.

### External evidence lifecycle and permission matrix

1. An authenticated human with SITES_WRITE registers a revision; producer attestation remains declared even if signed. The original submission manifest stays immutable.
2. An authenticated human or separately authorized evidence administrator creates an ExternalEvidenceDeclarationV1 naming the exact target DSM subject, submission manifest entry, and observed DSM digest. Its claimed independence/source is still declared. Core derives scope, assigns an evidence-specific server key, and issues an additive digest-bound evidence upload grant; the existing reconstruction-artifact grant is not falsely reused for checkpoints or other evidence.
3. Core seals observed evidence bytes into a separate ExternalEvidenceManifestV1. The lifecycle is DECLARED -> SEALED_BYTE_OBSERVED -> VALIDATION_QUEUED -> MEASURED -> Core VALIDATED or REJECTED. Evidence manifests reference the submission manifest one-way; they never modify it.
4. The processing-controller worker reads exact sealed evidence CSV plus exact sealed DSM, computes the defined metrics, and writes a fenced measurement payload. Core independently checks scope, target DSM and evidence manifests/digests, policy binding, and arithmetic/result consistency before deriving VALIDATED or REJECTED. Customer/evidence-admin admission cannot set measured or trusted verdicts, and no administered number substitutes for worker measurement.
5. Any assertion that evidence is independent remains an assertion until a separate approved source-trust policy adjudicates it and binds that adjudication to the evidence record. This design invents no trust or accuracy rule and requires no client.
6. Policy/evidence revocation or supersession prevents future reuse and new execution, causing later evaluation to return a typed restriction/blocker. It does not rewrite the submitted declaration, either manifest, previous measurement/report, prior decision, or managed history.

| Principal | Allowed actions | Forbidden actions |
|---|---|---|
| Authenticated human | Register, upload/seal own-scope revision and separately declared evidence; request/read decisions with SITES_WRITE/SITES_READ. | Set policy, worker outcome, measured/trusted result, scope, or verdict. |
| Policy/evidence administrator | Admit/revoke/supersede policy or separately declared evidence under future audited authority. | Treat attestation as independent proof, invent measured numbers, or alter sealed bytes/historical decision payloads. |
| Processing-controller worker | Claim, read leased exact input, heartbeat, submit fenced measurement/rejection. | Activate policy, decide eligibility, or write human/customer declarations. |
| Dashboard/device/reconstruction-engine principals | Read only where separately authorized. | Claim inspection, submit observed facts, or bypass scoped human/Core flow. |

Worker fetches only server-derived sealed keys with scoped capabilities, streams bytes, verifies observed digest/size, and uses private per-request workspace. It never follows artifact URLs/paths, archives, sidecars, remote datasets, executable metadata, or CRS network grids. Parser requires allow-listed content type/signature as hints, then approved GeoTIFF/COG grammar and pinned parser build. It rejects malformed offsets/layout, unsupported compression/layout, external references, missing/ambiguous georeference, unsafe CRS/vertical resolution, and budget exhaustion. Policy-supported declared/masked nodata, including NaN, is recorded with valid coverage and can restrict only uses requiring affected coverage; unmasked non-finite sample values are rejected. Sanitized display access is policy-gated and strips unneeded producer metadata. Untrusted payload is not echoed to logs/events/UI.

Proposed resource policy fields include declared/observed bytes, streamed bytes, TIFF directories/entries, dimensions/pixels/bands, tiles/strips/overviews, decompressed/sample bytes, geometry vertices, CPU, memory, workspace, tenant concurrency, queue depth, lease duration, retry budget, and derivative bytes. Active ExternalValidationPolicyV1 must have explicit configured, validated envelope plus digest. Missing, malformed, or unlimited values reject with RESOURCE_POLICY_UNAVAILABLE; no implicit unlimited default exists. Benchmark and operations review choose values and prove deployed capacity separately.

## Future ownership and test matrix

| Owner | Proposed future modules | Responsibility |
|---|---|---|
| packages/event-contracts and contracts/schemas | external_artifact_validation.py, external_evidence.py, additive schemas | Immutable models/digests only; no storage, authorization, queue, or eligibility. |
| services/core | external_artifact_inspections.py, external_validation_policy.py, external_use_decisions.py | Scope/auth, journal/replay, enqueue/reconcile, leases/fences, policy registry, decisions, opaque routes. No raster parse or managed-job coercion. |
| services/processing-controller | external_artifact_inspection_worker.py, external_geotiff_inspector.py, client protocol | Safe byte measurement/report/rejection. No policy activation or eligibility. |
| apps/dashboard | future external-result presentation | Shows fact class, decision, restriction; requests intent only. |

Future tests cover: strict contract/schema and non-promotion; tenant/principal matrix; post-seal issue/reconciliation (including no-policy pending and historical sealed revision); competing lease/expiry/stale fence/replay tamper; malformed/risky raster/no-network parsing; all per-use blockers; policy immutability/mapping exactness; and synthetic Core-to-worker E2E. Decisive scenarios include: an exact report retry deduplicates while changed payload needs a new issue; rejected DSM leaves eligible ortho display available; request-wide incomplete exhaustion emits no unexamined outcome; masked NaN/nodata reports valid coverage while unmasked non-finite values reject; signed attestation remains declared; a separately sealed external evidence manifest binds one-way to exact DSM without managed checkpoint API or artifact-grant reuse; worker-calculated evidence metrics are required before Core validation; revocation blocks future execution/decisions but preserves history; and no policy creates a visible pending state rather than a job. Synthetic fixtures cannot be called producer compatibility, accuracy benchmark, deployed capacity, customer-data, remote-CI, HIL, field, or release acceptance.

## Rollback and explicit release gates

| Gate | Required before | Evidence required | Does not establish |
|---|---|---|---|
| Specification acceptance | Any implementation | Human approval of this D5 design and separately approved executable plan. | Parser support, deployment, or quantitative eligibility. |
| Inspection/display enablement | Inspection worker or DISPLAY release | Approved GeoTIFF/COG parser/security review, configured validated resource envelope, and local contract/replay/security evidence. | Producer compatibility, capture truth, HEIGHT, or RELATIVE_VOLUME. |
| Positive quantitative eligibility | HEIGHT or RELATIVE_VOLUME decision can be ELIGIBLE | INV-053 external-readiness authority, approved trust and quantitative policy, exact independent evidence, and approved compatibility mapping where required. | Contract settlement, survey accuracy, vendor acceptance, or production release. |
| Production acceptance | Production customer route | Authorized real-data, vendor/export compatibility, license, deployment/operations, retention, and Human release evidence. | Field/HIL acceptance unless separately evidenced. |

Rollout is additive: inspection/evidence persistence, DISPLAY, non-quantitative VISUAL_COMPARISON, then quantitative uses only at their own gate. Parser enablement never enables quantitative eligibility. Synthetic mechanics prove no whole-goal completion.

Rollback disables enqueue/claim/new decisions or returns routes read-only. It never deletes/re-writes sealed submissions, reports, policies, decisions, managed jobs, source bundles, or historical results; it never bypasses blockers, exposes unsanitized map, or backfills policy onto old decision.

Before their applicable gate, Human/Product Authority must decide: INV-053 external-readiness clarification; GeoTIFF/COG grammar/parser supply-chain/security review; policy registry governance/revocation/retention; independent checkpoint/uncertainty and benchmark evidence; configured validated resource envelope and deployed operations evidence; customer data/license/compatibility/real-data acceptance. Approval of this design approves none by implication.
