# External Reconstruction Ingress API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Human authorization forbids commits and external side effects.

**Goal:** Implement and verify authenticated external reconstruction registration, digest-bound upload, server-observed sealing and durable recovery, without original photo upload.

**Architecture:** Core owns the external submission stream and byte manifest, independently from managed ProcessingJob/source lineage. Existing storage ports issue checksum-bound capabilities and observe objects outside the journal lock. Registration freezes an authenticated WorkOrder cycle witness; replay uses that witness, never the latest WorkOrder projection.

**Tech Stack:** Existing Python 3.12, FastAPI, Pydantic, DurableJournal and S3EvidenceStorage; locked dependencies only.

**Spec:** `docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md` D1–D5; `docs/superpowers/plans/2026-09-06-external-reconstruction-release.md` Slice 2; accepted external reconstruction v1 contracts.

## Global Constraints

- Originals stay on customer equipment. Exactly one ortho is required; DSM and other allowed outputs are optional.
- Registration and byte sealing do not establish semantic validity, source authority, accuracy or quantitative eligibility.
- Authenticated Principal and scoped WorkOrder establish organization/site/cycle authority; body fields never grant access.
- Preserve existing managed ProcessingJob, source-media, processing-profile and analysis-readiness behavior.
- No commits, staging, push, merge, deployment, credentials, customer data, device actions or reference-repository edits.
- Preserve original main WIP and all unrelated changes in the assigned feature worktree.
- Use only `/tmp/ksi-flight-planning-design.wdFlvL/worktree` for writes. One code writer; Lead owns plan/goal/evidence files.
- INV-051/053: separate external identity and no managed/quantitative authority promotion. INV-060: tenant-scoped access with non-disclosing 404. INV-024: no inferred accuracy. INV-002: no flight output.

## Requirement and acceptance matrix

| ID | Acceptance evidence |
| --- | --- |
| EXT-API-01 / REQ-INT-101/102/103/104 | Ortho-only sealed declaration registers over authenticated API without raw bundle/job/profile. Optional DSM round-trips. |
| EXT-API-02 / REQ-SEC-101 | Principal org, WorkOrder site, cycle and actor match; tenant B gets same 404 as absent; viewer/device/worker writes denied. |
| EXT-API-03 | Revision 1 first, contiguous corrections, identical retry stable, conflict 409, old-cycle correction uses frozen witness, new cycle needs new stream. |
| EXT-API-04 | Digest-bound grants, actual HTTP PUT of synthetic bytes, server HEAD verifies exact key/hash/size/type, failures never seal and retry succeeds. |
| EXT-API-05 / REQ-OPS-102 | Real journal close/reopen returns identical submission/manifest; malformed, forged, out-of-order events fail closed; append failure cannot publish state. |
| EXT-API-06 | create_app partial dependencies/auth fail closed; shared dev/production assembly wires routes only with valid storage; OpenAPI and hostile-route inventories conform. |
| EXT-API-07 | Independent task review, integrated review and Lead verification; goal/evidence docs distinguish local acceptance from deployment and product release. |

## Implementation packet

Requirement IDs: EXT-API-01–07 plus linked product IDs above.
Owner module: services/core, durable external reconstruction ingress.
Contracts affected: additive Core OpenAPI; accepted submission/manifest schemas remain unchanged.
Reference assets: REUSE DurableJournal, authorization/scope helpers, ObservationWorkOrderStore, observation_epoch_id, digest-bound storage and observation ports; REFERENCE_ONLY managed ProcessingJob patterns. No reference runtime imports.
Adoption decisions: no independent EpochStore, no duplicate upload backend, no managed job reuse.
HIL or real-device assumptions: none. Local S3-shaped HTTP fixture is not real S3 signature interoperability, deployment or field acceptance.
License/data implications: synthetic local bytes only, existing dependencies, no vendor selection or customer originals.
Rollback: disable external-store assembly and preserve its journal; withdraw only owned uncommitted changes after checking ownership. Never delete or relabel historic evidence.

### Task 1: Implement the coupled ingress state machine and mounted API

**Files (sole implementation writer):**
- Create `services/core/src/ksi_core/external_reconstruction.py`: frozen durable records, revision store, strict replay and route mounting, following existing owner-module convention.
- Modify `services/core/src/ksi_core/app.py`: optional store, dependency table/provided/protected surface, runtime-checkable storage port validation and mounting.
- Modify `services/core/src/ksi_core/app_assembly.py`: lifecycle-managed `external-reconstruction.jsonl`, construct after WorkOrder store when storage exists, pass to create_app.
- Modify `contracts/api/openapi-core.yaml`: five routes and request/response/error schemas.
- Create `tests/contract/test_external_reconstruction_api.py`, `tests/replay/test_external_reconstruction_replay.py`, `tests/e2e/test_external_reconstruction_upload_flow.py`.
- Modify required route/assembly inventories: `tests/contract/test_api_contract_sync.py`, `test_hostile_input_route_coverage.py`, `test_validation_error_rendering.py`, `test_dev_assembly.py`, `test_production_assembly.py`.
- Other files are outside ownership; report a concrete required expansion before writing them.

**Interfaces:**
- Consume `ExternalReconstructionSubmissionV1` with valid non-null submissionDigest; reject unsealed/stale declarations rather than manufacturing a digest.
- Consume `ExternalReconstructionManifestV1.from_submission(...)` and wire serializers; Core additionally checks observed content type.
- Consume `ObservationWorkOrderStore.get(work_order_id, organization_id=...)` and canonical `observation_epoch_id(work_order)`.
- Consume `DigestBoundEvidenceStorage.presigned_put_bound_digest(object_key, content_type=..., content_digest=..., ttl=...)` and `ObjectStorageObservationPort.observe_object(key)`.
- Produce `ExternalReconstructionStore` register/list/get/upload-bindings/seal operations and `mount_external_reconstruction(...)`; exact internal types may follow local style without changing these semantics.
- Produce `external_reconstruction_store` optional create_app argument, requiring site_store, observation_work_order_store, evidence_storage, auth and both specialized storage ports.

**Routes:**
```text
POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions
GET  /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions
GET  /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}
POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/upload-grants
POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/seal
```

Writes use SITES_WRITE and human authority, reads SITES_READ. Every route resolves scoped WorkOrder before revealing a submission. submittedBy equals Principal actor. Mismatched body scope is rejected; cross-tenant paths return the same absent-resource response. Use existing typed error conventions: conflicts 409, bad declarations 422, unavailable storage 503; missing or unverifiable/mismatched object observations are typed non-success and leave REGISTERED.

Final integration correction: contract-valid customer submissionId is not a URL segment. Every revision view must expose required opaque submissionRef, `ers-v1-` plus64lowerhex, derived from canonical JSON version/organizationId/workOrderId/submissionId. Use validated contract values without new Unicode normalization. Clients use the returned ref in the three revision routes; no raw-ID compatibility route on this undeployed surface. Replay derives a (WorkOrder,ref)->originalID index, checking collisions fail closed before live append and during replay. Journals and object keys retain original IDs, preserving existing records. Registration/list/detail/retry/restart must return stable refs. Test slash, route-suffix-like IDs, dots, percent, Korean, distinct a/b versus a%2Fb, tenant-separated refs and unknown-ref404 across actual grant/PUT/seal/restart. Existing auth, journal ordering and revision semantics remain unchanged.

Review clarification: organization/site scope violations may use the generic404 refusal, but must do so identically before inspecting whether an external record exists. Structural/digest/actor declaration errors remain422. A forged-scope retry cannot select a different refusal based on foreign-record existence.

**State and concurrency contract:**

First revision freezes organization/site/workOrderId/workOrderVersion/cycleNumber/derived epoch/submissionId plus server registeredAt/registeredBy and canonical declaration. Existing streams retain this witness when WorkOrder cycle advances. Same revision+digest retries return the original receipt; different content conflicts. New revisions are contiguous and match frozen stream scope. A new cycle requires a new submissionId. Only latest unsealed revision can get grants or newly seal; older unsealed revisions are superseded. Sealed historical revisions remain readable and seal retries return their identical manifest. No arbitrary WorkOrder status or expiry admission restriction is added.

Actor clarification: registeredAt/registeredBy are immutable provenance of each individual revision, not an exclusive-owner permission on the stream. Another same-organization human with SITES_WRITE may create the next revision with submittedBy=self. Replay requires that revision's submittedBy==registeredBy, not equality to revision1's actor. The frozen cross-revision witness is organization/site/WorkOrder/version/cycle/epoch; earlier revisions retain their original actor/time.

Generate safe keys from a versioned full canonical tuple (org/site/workOrder/cycle/epoch/submission/revision/artifact), hashing untrusted identifiers rather than embedding raw path segments. Persist bindings; strict replay checks versioned derivation. Contract byte hashes are bare lowerhex; storage uses `sha256:` prefix. Existing ALLOWED_CONTENT_TYPES remains unchanged; application/octet-stream supports this byte-ingress step without implying raster validation.

Append durable event before publishing memory state under RLock. Do not hold the external-store lock over presigning or HEAD. Snapshot current revision, observe outside lock, recheck head/digest/state before atomic seal. A concurrent correction invalidates stale observations. Registration persists independently of grant failure; upload-grants retries refresh capability without new registration. Do not journal URLs. Reject grant after seal. Seal proves point-in-time byte observation, not perpetual object immutability.

Replay validates complete strict events: self digests, exact artifact sets and bindings, frozen scope and derived epoch, contiguous revisions, legal transitions, manifest declaration/observation equality including content type. Reject unknown events/fields, conflicting duplicates, gaps, seal-before-registration and forged events. Replay has no dependency on current WorkOrder store. Record observed WorkOrder snapshot; do not claim cross-journal global linearizability.

- [x] **Step 1: Add failing contract/API tests and run them before implementation.** Use real authentication and scoped Site/WorkOrder fixtures from owner tests. Decisive assertions include:
  ```python
  assert registered.json()["submission"]["submissionDigest"] == submitted["submissionDigest"]
  assert repeated.json() == registered.json()
  assert foreign.status_code == absent.status_code == 404
  assert conflict.status_code == 409
  ```
  Also test ortho-only/DSM, actor/body-scope mismatch, all denied principal kinds, revisions and post-cycle correction, supersession, simultaneous identical/conflicting registration, stale observation races and failed append. Adapt envelope assertions to the documented response model, without weakening the requirement.
- [x] **Step 2: Implement minimal store and routes to pass those tests.** Transition ordering is:
  ```text
  scope snapshot -> locked validate revision -> append registration -> publish
  locked snapshot -> storage observation without lock -> locked recheck -> append seal -> publish
  ```
  Add failure tests for missing object, wrong key/digest/size/content type, absent trusted checksum, storage exception and retry; no failure appends a seal.
- [x] **Step 3: Add replay tests before implementing strict replay handling.** Close/reopen actual DurableJournal; assert exact receipts/digests and historical witness after cycle advance. Feed forged complete registration/seal events and prove constructor fails closed. Cover unknown event, extra field, key tamper, epoch tamper, gap, conflicting duplicate and mismatched manifest.
- [x] **Step 4: Wire real assembly and OpenAPI.** Add failing dependency/auth/production route tests, then implement wiring and update route inventories with executed hostile-input proofs. Dev without storage remains valid and external routes absent; unsupported storage rejects assembly. Production shared assembly mounts this feature with its existing S3 adapter.
- [x] **Step 5: Add actual local HTTP byte-flow test.** ThreadingHTTPServer on loopback/ephemeral port receives real PUT bytes through real S3EvidenceStorage presigned URLs, checks checksum/content-type headers and computes SHA256, then serves S3 HEAD checksum/size/type. Core TestClient registers, issues grant, seals after PUT, closes/reopens journals and reads identical manifest. Wrong bytes and pre-upload sealing fail; valid retry succeeds. This is explicitly a bounded S3-shaped fixture, not full AWS signing validation.
- [x] **Step 6: Run focused tests and regressions; self-review.**
  ```bash
  env PYTHONPATH=services/core/src:packages/event-contracts/src:packages/domain/src /tmp/ksi-audited-r3-rewrite.flLDBs/worktree/.venv/bin/python -m pytest tests/contract/test_external_reconstruction_contracts.py tests/contract/test_external_reconstruction_api.py tests/replay/test_external_reconstruction_replay.py tests/e2e/test_external_reconstruction_upload_flow.py tests/contract/test_api_contract_sync.py tests/contract/test_hostile_input_route_coverage.py tests/contract/test_validation_error_rendering.py tests/contract/test_dev_assembly.py tests/contract/test_production_assembly.py -q
  git diff --check
  ```
  Assert ksi_core and external contract imports resolve to THIS worktree. Do not modify the older venv or trust its editable paths. Run installed Ruff and targeted mypy on changed Python files; report exact commands/results, environmental limits and RED/GREEN evidence. Do not commit. Return changed files, concerns, deviations and stop conditions encountered.

### Task 2: Independent acceptance and durable handoff

**Files:** Lead owns this plan and `.ksi/` through helper only. After code review, a documentation worker owns `docs/audit/EXTERNAL_RECONSTRUCTION_INGRESS_API_VERIFICATION.md`, relevant routing/status links in `docs/00_READ_FIRST.md`, `docs/DOCUMENT_STATUS.md`, ADR036 and release plan, plus `services/core/README.md`. No product behavior or historical managed evidence rewrite.

Final integration documentation correction additionally owns only the external-reconstruction paragraph in `docs/product/FINAL_DECISION_LEDGER_v1.0.md`: replace its stale NOT_IMPLEMENTED runtime assertion with a pointer to bounded API audit/current goal, preserving broader release limits. Document returned submissionRef usage and corrected verification results in the existing owned docs. No unrelated ledger/terrain-policy edits.

**Interfaces:** Consume Task 1 accepted diff, task-review verdict and actual test output. Produce requirement-to-test evidence matrix and accurately scoped runtime status.

- [x] Independently review Task 1 spec and quality, including authorization, input bounds, concurrency, replay, storage checks and assembly. Fix via same worker; after two unsuccessful correction rounds Lead adjudicates without silently accepting load-bearing defects.
- [x] Independently verify multi-check evidence, including actual HTTP bytes/restart and import paths. Review integrated code/contracts/docs after documentation is ready.
- [x] Lead inspects accepted diff and reruns narrow meaningful integrated suite; verify original main WIP hashes unchanged.
- [x] Record exact tested revision/worktree, commands, counts, failures/skips and local-only boundaries. Add child goal through ksi-goals.py; complete only with independent PASS and actual full API evidence. Broad product-release goal remains in progress.

## Preflight coverage

Task 1 covers EXT-API-01–06 and preserves the accepted contract slice. Task 2 covers EXT-API-07 and verifies every Task 1 requirement. Their only shared interface is accepted code/test evidence; writers are sequential and documentation ownership does not overlap code ownership. No additional Human decision is needed for this approved API scope.
