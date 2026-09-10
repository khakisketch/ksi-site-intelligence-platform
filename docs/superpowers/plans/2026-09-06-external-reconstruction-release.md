# Customer-owned reconstruction release implementation plan

> Execution: Lead coordinates bounded workers and independent review under AGENTS.md.
> Human authorization: customer-owned originals, customer-operated reconstruction, KSI-held
> derived outputs, evidence-dependent claims; explicit instruction to implement on 2026-09-06.

**Goal:** Complete the customer-workstation/Pilot-default first-release product, not merely an
import schema. Repository goal: `pilot-default-external-reconstruction-release` (in progress).

**Architecture:** Customer reconstructs; Core owns submission identity, durable evidence and
claim decisions; processing-controller measures supplied bytes; import-only event-contracts
defines the boundary; Console presents evidence and requests intent. No forged managed job,
source authority, profile identity or actual-flight evidence. Originals need not leave the customer.

**Stack:** Existing Python 3.12/Pydantic contracts, JSON Schema Draft 2020-12, Core journal,
processing worker and Operations Console; reuse locked dependencies and owner paths.

## Sequence and parallelism

1. Typed external submission and byte-observation manifest, tests and schema conformance.
2. Authenticated Core registration, immutable revisions, derived-byte upload/sealing and replay.
3. Worker file inspection and versioned per-use evidence/compatibility decisions. Missing raw
   upload alone must not be a permanent quantitative blocker. Independently verified checkpoint
   evidence, common reference/registration and compatible processing remain claim prerequisites.
4. Connect external epochs to visual comparison, eligible height/relative-volume analysis,
   plan/quantity/operator-evidence progress, grounded reports/LLM and reobservation.
5. Console upload/status/results and customer handoff, retention/export/deletion and resource
   bounds; synthetic end-to-end then separately authorized real customer-data acceptance.
6. Integrate approved terrain-aware planner and Pilot provenance track; device acceptance,
   deployment, remote CI and Human release decision remain separate evidence gates.

Steps 1→2→3→4 are dependent. UI and planner work may run alongside later backend work only
after their contracts are stable, with separate worktrees and disjoint ownership. No standing
agent team. Each executable slice gets exact files/tests before implementation. This document
does not pretend later release tasks already have verified implementation or acceptance.

## Slice 1: executable specification and task packet

- Requirement IDs: ADR-KSI-036; REQ-INT-101/102/103/104, REQ-SEC-101, REQ-OPS-102.
- Owner module: `packages/event-contracts` (import-only); schemas in `contracts/schemas`.
- Invariants: INV-051/053 preserved by rejecting managed/source/profile impersonation and
  granting no quantitative eligibility; INV-060 represented by explicit scope bindings (actual
  authorization is future Core work); INV-024 no inferred accuracy; INV-002 no flight output.
- Reference assets/adoption: REUSE `_CamelModel`, `ProcessingArtifactKind`, `VerticalReference`
  and domain canonical JSON; REFERENCE_ONLY existing managed tests; no reference repo import.
- Contracts affected: two new v1 contracts only; existing ProcessingJob/Artifact unchanged.
- Files: `packages/event-contracts/src/ksi_event_contracts/external_reconstruction.py`,
  `contracts/schemas/external-reconstruction-submission.v1.json`,
  `contracts/schemas/external-reconstruction-manifest.v1.json`,
  `tests/contract/test_external_reconstruction_contracts.py`.
- HIL assumptions: none for contract tests; tests do not establish DJI or field acceptance.
- License/data: no vendor SDK/license selection, network fetch, original bytes, local raw
  paths, credentials or customer datasets. Generated synthetic metadata tests only.
- Rollback: withdraw the four additive uncommitted files after checking task ownership;
  no historical managed state, schema or evidence rewrite.

### Submission

`ExternalReconstructionSubmissionV1`: fixed contractVersion, submissionId, positive revision,
organizationId/siteId/observationEpochId, timezone-aware submittedAt, submittedBy,
executionResponsibility=`customer_operator`, executionLocus=`customer_workstation`,
producerDeclaration, inputDeclaration, artifacts, submissionDigest.

Producer declaration: bounded softwareName/softwareVersion, nullable buildIdentifier,
producerRunIdentifier, configurationDigest, completedAt. Input declaration:
rawMediaStoredByKsi=false, originalRetentionLocus=customer_workstation, nullable
localInputManifestDigest/imageCount/captureStartedAt/captureEndedAt. Capture times either
both unknown or an ordered aware pair. These are declarations, never KSI-observed facts.

Each artifact: artifactId, kind, safe basename fileName, bounded format/content type,
declaredSha256, positive declaredSizeBytes, nullable declaredCrs/declaredVerticalReference/
declaredGsdM. Vertical source if present must be USER_DECLARED. Require exactly one ortho;
DSM and other existing kinds optional, at most one per kind for this bounded v1 package.
Ortho-only registration must work: DSM absence restricts height/volume, not registration.
No implicit CRS, datum, GSD, accuracy, source bundle, job, processing profile or client object key.

### Server-observed manifest

`ExternalReconstructionManifestV1`: fixed contractVersion, manifestId, submissionId,
submissionRevision/submissionDigest, organizationId/siteId/observationEpochId, aware observedAt,
observedByService, entries, manifestDigest. Entries: artifactId/kind, safe relative objectKey,
observedSha256/observedSizeBytes/observedContentType. This records byte identity only, not
format validity, declared CRS truth, source completeness, accuracy or quantitative eligibility.

Factory binds exact submission scope/revision/digest and exact artifact IDs/kinds; observed
hash and size must match declarations. Caller scope must be checked rather than silently
discarded. Both records sort artifacts/entries deterministically and verify canonical sha256
digests excluding their digest field. Extra fields forbidden; bounded strings and collection,
positive strict integers, finite numbers, aware ordered times; reject path traversal and URLs.

Wire convention refinement from repository review: record/configuration digests retain
`sha256:<64 lowercase hex>`; byte-specific `declaredSha256`/`observedSha256` use bare 64 lowercase
hex, matching existing object-observation fields. `contentType` belongs to the explicitly declared
artifact type; the observed counterpart is `observedContentType`. Do not confuse their authority.
Sealed records and nested owned models must reject mutation; serializers/factories revalidate
unchecked model copies and must never silently replace a supplied stale digest.

### TDD and acceptance

1. Write new focused tests; demonstrate failure before implementation.
2. Implement the minimal contracts and schemas. Test schema/model round trips, null metadata,
   ortho-only acceptance, optional outputs, duplicate/unsafe/forged fields, scope substitution,
   reordered digest equivalence, content tampering, invalid time and declared/observed mismatch.
3. Run the new suite plus `tests/contract/test_processing_contracts.py` regression and targeted
   Ruff. Schema can express structural constraints; relational/digest checks are authoritative
   model checks and must have explicit tests, not misleading schema-only acceptance claims.
4. Independent read-only reviewer, fix findings via same worker, Lead inspects and reruns.

Validation interpreter: `/tmp/ksi-audited-r3-rewrite.flLDBs/worktree/.venv/bin/python` with
`PYTHONPATH` explicitly pointing to THIS worktree's `packages/event-contracts/src` and
`packages/domain/src`; assert imported module paths before running. Do not alter the prior
worktree's virtual environment or claim its editable imports test these changes.

## Remaining release gates

Contract completion is not an upload API or product release. Real uploads/storage/replay,
tenant isolation, file-validation/resource limits, evidence-specific analysis, customer UX,
retention/backup/export, real-data calibration, terrain/flight provenance, device acceptance,
remote CI and authorized deployment must each have their own recorded evidence.

## Slice 2: implemented Core registration and byte sealing (local evidence)

Slice 2's bounded Core API now has local software evidence in the
[external ingress verification audit](../../audit/EXTERNAL_RECONSTRUCTION_INGRESS_API_VERIFICATION.md).
This records registration, revision, grant, seal, replay, and assembly behavior only. It does not
complete the subsequent slices or the `pilot-default-external-reconstruction-release` goal; the
remaining release gates above continue to apply.

Registration, list, and detail views return the opaque server-issued `submissionRef`. Clients must
consume that returned reference for detail, upload-grant, and seal routes; they must not construct
those URLs from a customer `submissionId`. The raw customer ID remains the declaration, journal, and
object-key identity, and existing journals derive their stable public reference on replay without a
migration.

Architecture review resolved that there is no independent mutable Epoch store. The canonical
`acquisition.analysis_readiness.observation_epoch_id(work_order)` derives identity from organization,
work-order ID and cycle. First registration freezes that witness. Later corrections, grants,
seal, reads and replay must retain it even after the WorkOrder advances to a new cycle.

Implemented ownership is `services/core/src/ksi_core/external_reconstruction.py`, assembly in
`services/core/src/ksi_core/app.py` and `app_assembly.py`, and API authority
`contracts/api/openapi-core.yaml`. The focused evidence lives in the external-reconstruction API,
replay, loopback E2E, API-conformance, hostile-route, validation-error, dev-assembly, and
production-assembly tests. The [verification audit](../../audit/EXTERNAL_RECONSTRUCTION_INGRESS_API_VERIFICATION.md)
records their local evidence and the independent Task 1 review. Final integration review and the
helper-managed goal decision remain separate Lead gates; later release slices remain in progress.

API group: `/v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions`.
Registration/list/detail plus revision-specific `upload-grants` and `seal`; the latter three use
the returned `{submission_ref}`, never a raw customer ID. `SITES_WRITE` is required for human
writes and `SITES_READ` for reads. Principal and scoped WorkOrder, never body fields, establish
authority. Wrong-tenant resources remain indistinguishable from absent resources. The client PUTs
each artifact directly to its granted `uploadUrl`, preserving every `requiredHeaders` value
unchanged, before requesting seal; that storage PUT is not a sixth Core API route.

Internal state is REGISTERED→SEALED only. Record separate server `registeredAt`/`registeredBy`;
submittedAt and producer fields remain declarations. Bind submittedBy to authenticated actor.
First revision 1, contiguous corrections, same identity+digest idempotent, conflicting payload
409, no stream migration between epochs. Already sealed revisions are immutable; corrections
are new revisions. New-cycle reconstruction has a new stream ID. Historical replay validates the
frozen witness without depending on the current WorkOrder projection or cross-journal order.

Keys are server-generated from a canonical full org/site/work-order/cycle/epoch/submission/
revision/artifact tuple, never raw user-provided path segments, and persisted with registration.
Require digest-bound PUT and trustworthy object checksum observation. Do not journal URLs.
Check exact observed key/hash/size/content type before sealing. Missing object, unavailable
checksum or storage failure does not publish a manifest. Retry can refresh a grant before seal;
no new grant after seal. No claim of permanent byte immutability without storage evidence.

Tests must cover tenant non-disclosure, denied viewer/device/engine worker writes, first versus
historical cycle binding, concurrent/idempotent revisions, superseded unsealed revisions,
storage failure/retry, observed-byte mismatches, forged or out-of-order journal events,
restart/replay equivalence, partial assembly refusal and production route wiring. These tests
remain software evidence; no semantic raster validity or analysis eligibility comes from sealing.

## Quantitative V1 authority follow-on

The approved follow-on is [external quantitative authority V1](2026-09-09-external-quantitative-authority-v1.md).
It is not an implicit extension of registration or sealing. Its first-release rule admits only one
exact ordered external DSM pair under `external-geotiff-profile.v1`, exact observed CRS/vertical
references, ordered capture times, independently validated checkpoint evidence, an exact WorkArea,
and explicit digest-bound validation/execution policies.

The validation policy pre-authorizes the independent compatibility-rule digest. A durable full
mapping-record digest then binds the rule to that exact policy; decisions and historical execution
never use the rule digest alone. Catalog authority records bind a strict self-reference-free
admission body, and configuration remains path-only and default-closed. Disabling workflow
injection stops new issuance while retaining all historical authority/evidence records.

The local Core production-flow proof uses the common assembly and its exact configured mapping
participant, exercises activation-boundary and review-boundary restarts, and verifies unchanged
authority/successor journals on read-only/idempotent paths. Its worker observations and retained
external authority records are test fixtures; it is not evidence of deployed authority
provisioning, real raster/checkpoint measurement execution, customer export compatibility, or
operator acceptance.

This local implementation still needs independent review and does not satisfy customer-export
compatibility, authority-record provisioning, host hardening, backup/restore, owner operation,
deployment, HIL, or field acceptance.
