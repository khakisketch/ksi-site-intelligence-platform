# External Artifact Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fail-closed, durable inspection and per-use decisions for sealed customer-owned reconstruction artifacts without representing them as managed processing, source authority, or automatically eligible quantitative results.

**Architecture:** Immutable contract models and schemas bind exact sealed artifacts, evidence, policy snapshots, measurements, and decisions. Core owns scope, journals, queue/replay, leases/fences, policy selection, evidence validation, and decisions; processing-controller only streams exact server-authorized bytes and reports measurements/rejections. The existing external-reconstruction journal remains the registration/seal authority.

**Tech Stack:** Python 3.12, Pydantic v2, JSON Schema Draft 2020-12, FastAPI, existing Core durable journals/evidence storage, `httpx`, `rasterio`, NumPy, and the locked `uv` workspace.

**Spec:** `docs/superpowers/specs/2026-09-07-external-artifact-validation-design.md` (Human-approved D5 design only).

## Global Constraints

- Requirements: REQ-INT-101/102/103/104, REQ-SEC-101, REQ-OPS-102; traceability EXT-VAL-01..08.
- Invariants: INV-024 rejects absolute RMSE without independently validated checkpoints; INV-051 keeps external outputs derived-only; INV-053 blocks quantitative use until authority approves external readiness/compatibility; INV-060 scopes from Principal/server records and returns cross-org resources as 404.
- Keep external validation separate from `ProcessingJob`, `ArtifactRef`, managed profile/source bundle, source-media authority, managed checkpoint records, and Analysis Readiness.
- Contracts use strict UTC, closed enums, bounded collections, `extra="forbid"`, frozen models, and canonical SHA-256 digests excluding only their own digest field.
- Worker receives only server-derived sealed keys/capabilities; it streams/hashes bytes in a private workspace; it follows no path/URL/sidecar/archive/CRS grid and logs no untrusted metadata.
- Do not choose resource, retry, concurrency, byte/pixel, timing, uncertainty, RMSE, or compatibility values. An active policy must carry finite configured values and its exact digest; no default active policy exists.
- No dashboard/planner, deployment, customer data, credential, device, HIL, field, commit, push, or release work. A future UI only presents fact class/restrictions and requests intent.

## Required implementation-plan record

| Field | Decision |
|---|---|
| Requirement IDs | REQ-INT-101..104, REQ-SEC-101, REQ-OPS-102; EXT-VAL-01..08. |
| Owner module | Contracts: `packages/event-contracts`/`contracts/schemas`; authority: `services/core`; byte measurement: `services/processing-controller`. |
| Acceptance criteria | Strict schema/model parity; scoped durable replay/fences; bounded GeoTIFF/COG measurements; evidence-specific lifecycle; immutable decisions; synthetic Core-worker E2E. |
| Contracts affected | Additive schemas/models and `contracts/api/openapi-core.yaml`; existing external-reconstruction v1 stays unchanged. |
| Reference assets | REUSE external reconstruction, Core lease/store/router, checkpoint validator, `core_client.py`, runner. `references/repos/**` is REFERENCE_ONLY. |
| Adoption decisions | ADD separate policy/inspection/evidence/decision records and worker ports; REUSE opaque `submissionRef`, evidence-storage port, scope helpers, journal, and fence convention. |
| Tests | Contract/schema/API/replay/hostile-input/runner/E2E tests listed below; synthetic fixtures only. |
| HIL assumptions | None. Local tests do not establish vendor compatibility, capacity, storage interoperability, HIL, or field acceptance. |
| License/data | Parser supply-chain, export/license, customer retention, and real data need separate approval. |
| Rollback | Authorized gate disables enqueue/claim/new decisions or makes routes read-only; append-only records stay intact. |

## Task 0: Authority and operational-policy gates

**Files:**
- Modify: an approved ADR or `docs/product/DOMAIN_INVARIANTS.md` only when Product Authority explicitly directs it.
- Forbidden: policy configuration, deployment, customer data, `.ksi/`, dashboard, and code that treats an unresolved gate as enabled.

**Interfaces:**
- Consumes: D5 design, requirements, INV-024/051/053/060.
- Produces: an authority record naming approver, version, effective interval, evidence reference, and rollback owner; otherwise a typed unresolved gate.

- [ ] **Step 1: Record the unapproved decisions without choosing values.**

```text
GATE-EXT-READINESS: INV-053 external-evidence-profile treatment.
GATE-QUANTITATIVE: trust, uncertainty, checkpoint, benchmark rules/thresholds.
GATE-COMPATIBILITY: exact cross-profile mapping and benchmark evidence.
GATE-PARSER-OPS: grammar/build review, finite envelope, retention/revocation, capacity.
```

- [ ] **Step 2: Confirm authority has not already approved them.**

Run: `rg -n "external equivalent readiness|GeoTIFF/COG grammar|compatibility mapping|independent checkpoint" docs/product docs/architecture docs/superpowers/specs/2026-09-07-external-artifact-validation-design.md`

Expected: named gates, not an approved threshold/mapping/invariant change.

- [ ] **Step 3: Stop and obtain an authority record before production activation/release.**

Expected: isolated tests may admit explicitly `synthetic_test_only` policy mechanics through `FakePolicyAuthorityPort`; production assembly has no authority record and remains blocked. Product Authority, not an implementation worker, decides production policy values.

- [ ] **Step 4: Request review; stop before policy activation or release.**

| ID | Tasks | Outcome |
|---|---|---|
| EXT-VAL-01 | 4, 8 | actual sealed derived bytes format and spatial metadata inspection |
| EXT-VAL-02 | 1, 3–6, 8 | customer declarations separated from measured facts |
| EXT-VAL-03 | 1, 2, 5–6, 8 | versioned Core per-use display comparison height volume decisions with evidence-bound positive and negative paths |
| EXT-VAL-04 | 6, 8 | explicit remediation without blanket raw-upload or DSM absence denial |
| EXT-VAL-05 | 2–5, 7–8 | bounded resources transient retry fencing tenant isolation and restart replay |
| EXT-VAL-06 | 3, 5–8 | mounted Core and processing-controller workflow without managed identity impersonation |
| EXT-VAL-07 | 1–8 | reviewed detailed plan contracts tests independent and integrated verification |
| EXT-VAL-08 | 8 | durable docs goal evidence and local versus release acceptance boundaries |

### Task 1: Immutable contract and schema family

**Files:**
- Create: `packages/event-contracts/src/ksi_event_contracts/external_artifact_validation.py`, `packages/event-contracts/src/ksi_event_contracts/external_evidence.py`, `packages/event-contracts/src/ksi_event_contracts/external_display_artifact.py`
- Create: `contracts/schemas/external-artifact-inspection-request.v1.json`, `external-artifact-inspection-report.v1.json`, `external-evidence-declaration.v1.json`, `external-evidence-manifest.v1.json`, `external-evidence-validation-request.v1.json`, `external-evidence-record.v1.json`, `external-validation-policy.v1.json`, `external-use-decision.v1.json`
- Create: `contracts/schemas/external-pair-use-decision.v1.json`, `contracts/schemas/external-sanitized-display-artifact.v1.json`
- Create: `tests/support/external_artifact_validation_fixtures.py`
- Test: `tests/contract/test_external_artifact_validation_contracts.py`

**Interfaces:**
- Consumes: sealed `ExternalReconstructionSubmissionV1`/`ManifestV1`, `ProcessingArtifactKind`, `VerticalReference`, canonical JSON.
- Produces: `ExternalArtifactInspectionRequestV1`, `ExternalArtifactInspectionReportV1`, `ExternalEvidenceDeclarationV1`, `ExternalEvidenceManifestV1`, `ExternalEvidenceValidationRequestV1`, `ExternalEvidenceRecordV1`, `ExternalValidationPolicyV1`, `ExternalUseDecisionV1`, `ExternalPairUseDecisionV1`, and `*_wire_dict(model) -> dict[str, Any]`.

**Exact model catalogue:**

| Model | Required fields and invariant |
|---|---|
| `SealedExternalSubjectV1` | `organizationId`, `siteId`, `workOrderId`, `submissionId`, positive `revision`, `submissionDigest`, `manifestDigest`; every digest is `sha256:<64 lowercase hex>`. |
| `ExternalArtifactInspectionRequestV1` | opaque `requestId`, subject, `inspectionPolicyId/version/digest`, aware `issuedAt`, `idempotencyKey`; no client resource values. |
| `ExternalArtifactInspectionReportV1` | request/subject/policy/inspector-build digests, `measurementPayload`, `measurementPayloadDigest`; envelope fence/worker/time is excluded from payload digest. |
| `ExternalEvidenceDeclarationV1` | opaque `evidenceId`, exact subject, target DSM `artifactId` and observed SHA-256, declared content digest/type; independence is `DECLARED` only. |
| `ExternalEvidenceManifestV1` | opaque manifest ID, evidence ID, exact declaration/subject/DSM digests, observed object digest/size/content type, server key, observed time. |
| `ExternalEvidenceValidationRequestV1` / `RecordV1` | opaque request ID plus exact evidence-manifest/DSM/policy digests; worker measurement payload and Core `VALIDATED|REJECTED` result are distinct fields. |
| `ExternalValidationPolicyV1` | opaque ID, positive version, digest, status, parser-build/grammar/resource-envelope digests, rule IDs and compatibility-mapping digests; `ACTIVE` requires all finite envelope fields and an authority-record digest. |
| `SanitizedDisplayDeclarationV1` / `ReceiptV1` | opaque display ID/request ID, exact source subject/report/policy/inspector-build digests, declared and Core-observed derivative SHA-256/size/type, opaque `sanitizedDisplayRef`; no URL/object key in journal/public wire. |
| `ExternalUseDecisionV1` | opaque ID, one subject, `DISPLAY|HEIGHT`, policy/report/evidence/display-receipt digests, `ELIGIBLE|RESTRICTED|BLOCKED`, reason/remediation tuples. |
| `ExternalPairUseDecisionV1` | ordered baseline/current subjects, `VISUAL_COMPARISON|RELATIVE_VOLUME`, policy and named baseline/current report digests. It preserves the bounded ordered `evidenceRecordDigests` collection for `RELATIVE_VOLUME`; Core resolves every member as a validated external-evidence record, never a display receipt. It also has nullable named `baselineSanitizedDisplayReceiptDigest` and `currentSanitizedDisplayReceiptDigest`: both are required for non-`BLOCKED` `VISUAL_COMPARISON`, both are forbidden for `RELATIVE_VOLUME`. Volume additionally requires opaque zone ID, positive revision, zone-definition digest, observed CRS and vertical-reference digests. |

The shared fixture module creates an in-memory `FakeStorage`, fixed aware `NOW`, SHA-256 of `b"ortho"`, `b"dsm"`, and UTF-8 checkpoint bytes `checkpoint_id,easting_m,northing_m,elevation_m\np1,0.5,1.5,10.0\np2,1.5,1.5,10.0\np3,0.5,0.5,10.0\n`; it creates a 2×2 EPSG:3857 GTiff with affine `(1,0,0,0,-1,2)`, explicit synthetic vertical-reference evidence, one valid masked-nodata variant, one unmasked-NaN variant, a malformed TIFF header, a VRT, and a zip archive. Test policies have small finite values labelled `synthetic_test_only`; production assembly has no authority record and therefore cannot select them.

**Cross-task construction catalogue:** `PolicySelection(status: PolicySelectionStatus, policy: ExternalValidationPolicyV1 | None, reason: str | None)`; `PolicyReceipt(policy_id: str, version: int, policy_digest: Digest, status: PolicyStatus)`; `PolicyAuthorityPort.resolve(authority_record_digest: Digest, now: datetime) -> PolicyAuthorityRecord | None`, where record fields are digest, scope, active interval, and `synthetic_test_only`; `InspectionIssueResult(verdict: str, request: ExternalArtifactInspectionRequestV1 | None)`; `ArtifactInspectionOutcomeV1(artifact_id: str, observed_sha256: Digest, outcome: ArtifactOutcome, reason: str | None, measurements: RasterMeasurementsV1 | None)`; `ResourceEnvelopeV1` finite positive byte/pixel/block/decompressed/CPU/memory/workspace/output limits; `ExternalArtifactInputV1(entry_id: str, kind: ProcessingArtifactKind, observed_sha256: Digest, observed_size_bytes: int, content_type: str, download_url: str, required_headers: dict[str, str])`; `ExternalInspectionInputResponse(request: ExternalArtifactInspectionRequestV1, policy: ExternalValidationPolicyV1, artifacts: list[ExternalArtifactInputV1])`; `ExternalInspectionFailureV1(reason: str, detail: str | None)`; `InspectionLeaseResult(verdict: str, fence: LeaseFence | None, expires_at: datetime | None)`; `InspectionReportResult(verdict: str, report: ExternalArtifactInspectionReportV1 | None)`; `EvidenceReceipt(evidence_id: str, evidence_ref: str, manifest_digest: Digest | None, state: EvidenceState)`; `EvidenceUploadGrant(evidence_ref: str, upload_url: str, expires_at: datetime, required_headers: dict[str, str])`; `EvidenceIssueResult(verdict: str, request: ExternalEvidenceValidationRequestV1 | None)`; and `EvidenceRecordResult(verdict: str, record: ExternalEvidenceRecordV1 | None)`. Core owns all except worker-produced `ArtifactInspectionOutcomeV1` and `ExternalEvidenceMeasurementPayloadV1`.

- [ ] **Step 1: Write failing contract tests.**

```python
def test_report_payload_digest_excludes_only_its_own_digest() -> None:
    report = _report().sealed()
    assert report.measurement_payload_digest == report.measurement_payload_canonical_digest()
    assert report.fact_class == "OBSERVED"

def test_extra_field_or_naive_time_is_rejected() -> None:
    with pytest.raises(ValidationError): ExternalValidationPolicyV1.model_validate({**_policy(), "extra": True})
    with pytest.raises(ValidationError): ExternalArtifactInspectionRequestV1.model_validate({**_request(), "issuedAt": "2026-09-07T00:00:00"})
```

- [ ] **Step 2: Verify RED.**

Run: `uv run --locked pytest tests/contract/test_external_artifact_validation_contracts.py -q`

Expected: FAIL at missing contracts.

- [ ] **Step 3: Implement exact models and schemas.**

```python
class ExternalArtifactInspectionReportV1(_FrozenExternalModel):
    request_id: _BoundedText
    sealed_manifest_digest: Digest
    inspector_build_digest: Digest
    measurement_payload: ExternalInspectionMeasurementPayloadV1
    measurement_payload_digest: Digest | None = None
```

Require one outcome (`MEASURED`, `NOT_APPLICABLE`, typed `REJECTED`) per manifest entry; bind entry ID and observed SHA-256. Reports cannot carry managed identity/profile/source fields. Policy requires parser build/resource-envelope digests and finite limits when `ACTIVE`; models reject supplied independent-evidence rule satisfaction by declared/observed facts.

- [ ] **Step 4: Add relational tests.**

```python
def test_volume_binds_ordered_pair_and_exact_zone() -> None:
    value = ExternalPairUseDecisionV1.model_validate(_pair(use="RELATIVE_VOLUME"))
    assert value.baseline_subject_digest != value.current_subject_digest
    assert value.zone_definition_digest.startswith("sha256:")
```

- [ ] **Step 5: Verify GREEN and request review.**

Run: `uv run --locked pytest tests/contract/test_external_artifact_validation_contracts.py tests/contract/test_external_reconstruction_contracts.py -q`

Expected: PASS; stale digests, extra fields, unknown enums, nonfinite values, duplicate outcomes, and managed-field promotion fail.

### Task 1A: Correct the ordered pair display-receipt contract before any decision persistence

**Files:**
- Modify: `packages/event-contracts/src/ksi_event_contracts/external_artifact_validation.py`
- Modify: `contracts/schemas/external-pair-use-decision.v1.json`
- Modify: `tests/contract/test_external_artifact_validation_contracts.py`

**Interfaces:**
- Consumes: sealed `SealedExternalSubjectV1`, `ExternalArtifactInspectionReportV1`, `SanitizedDisplayReceiptV1`, `ExternalValidationPolicyV1`, and `DecisionVerdict` from Task 1.
- Produces: the corrected additive `ExternalPairUseDecisionV1` and schema wire shape. `baselineSanitizedDisplayReceiptDigest: Digest | None` and `currentSanitizedDisplayReceiptDigest: Digest | None` are ordered named fields; the existing bounded `evidenceRecordDigests: tuple[Digest, ...]` remains in the pair model and schema for `RELATIVE_VOLUME` quantitative evidence.

**Invariant enforcement:** INV-053 is enforced by retaining named policy/report/receipt bindings for a non-`BLOCKED` visual decision; the contract cannot promote a receipt to quantitative evidence. INV-051 is enforced by preserving external derived-object references rather than adding managed artifact identity. No assertion of INV-024 accuracy is possible in this pair contract.

This is a v1 contract correction before a decision store or public decision routes exist. There is no persisted pair-decision history to migrate, rewrite, or backfill. The task must not add such a store as a shortcut for validating the schema, nor discard legitimate `RELATIVE_VOLUME` evidence bindings to make display validation simpler.

- [ ] **Step 1: Write the failing contract and schema-parity tests.**

```python
def test_nonblocked_visual_pair_requires_two_named_display_receipts() -> None:
    decision = _pair_decision(use="VISUAL_COMPARISON", verdict="ELIGIBLE")
    assert decision.baseline_sanitized_display_receipt_digest
    assert decision.current_sanitized_display_receipt_digest

    raw = external_pair_use_decision_wire_dict(decision)
    raw["currentSanitizedDisplayReceiptDigest"] = None
    with pytest.raises(ValidationError, match="currentSanitizedDisplayReceiptDigest"):
        ExternalPairUseDecisionV1.model_validate(raw)

def test_volume_forbids_display_receipts_but_preserves_quantitative_evidence_records() -> None:
    raw = external_pair_use_decision_wire_dict(_pair_decision(use="RELATIVE_VOLUME"))
    raw["baselineSanitizedDisplayReceiptDigest"] = _digest("d")
    with pytest.raises(ValidationError, match="RELATIVE_VOLUME"):
        ExternalPairUseDecisionV1.model_validate(raw)
    volume = ExternalPairUseDecisionV1.model_validate(_pair(use="RELATIVE_VOLUME"))
    assert volume.evidence_record_digests == (_validated_evidence_record_digest(),)
```

- [ ] **Step 2: Verify RED.**

Run: `uv run --locked pytest tests/contract/test_external_artifact_validation_contracts.py -q`

Expected: FAIL because the current pair model permits the old evidence-record collection and has no ordered display-receipt fields.

- [ ] **Step 3: Make the smallest contract/schema correction.**

```python
class ExternalPairUseDecisionV1(_FrozenExternalModel):
    baseline_sanitized_display_receipt_digest: Digest | None = None
    current_sanitized_display_receipt_digest: Digest | None = None

    @model_validator(mode="after")
    def _binds_ordered_pair_and_use_specific_inputs(self) -> ExternalPairUseDecisionV1:
        # First verify the exact ordered subject, policy, and named report bindings.
        if self.use == "VISUAL_COMPARISON" and self.verdict is not DecisionVerdict.BLOCKED:
            if self.baseline_sanitized_display_receipt_digest is None or self.current_sanitized_display_receipt_digest is None:
                raise ValueError("non-BLOCKED VISUAL_COMPARISON requires both named display receipts")
        if self.use == "RELATIVE_VOLUME" and (
            self.baseline_sanitized_display_receipt_digest is not None
            or self.current_sanitized_display_receipt_digest is not None
        ):
            raise ValueError("RELATIVE_VOLUME must not carry display receipts")
        return self
```

The model rejects missing and use-invalid receipt slots. The later Core evaluator rejects receipt/report/policy/subject substitution by resolving each named digest to the exact sealed object in its scoped stores. For `RELATIVE_VOLUME` it resolves every `evidenceRecordDigest` to a validated record bound to its exact subject, observed DSM, and policy; a digest resolving to a `SanitizedDisplayReceiptV1`, another subject, another DSM, a revoked record, or another policy is rejected. Pair decisions bind their named inspection reports separately. The contract has no access to those stores and must not pretend to do that lookup. It never derives a measurement or treats a display receipt as quantitative evidence.

- [ ] **Step 4: Verify GREEN and request independent review.**

Run: `uv run --locked pytest tests/contract/test_external_artifact_validation_contracts.py tests/contract/test_external_reconstruction_contracts.py -q`

Expected: PASS; both named receipt slots bind their ordered subject/report/policy chain, `BLOCKED` may keep them null, non-`BLOCKED` visual comparison needs both, volume rejects both receipt fields while retaining real evidence-record digests, and the schema has no compatibility alias that can reinterpret a display receipt as evidence.

### Task 2: Core policy registry, never a default policy

**Files:**
- Create: `services/core/src/ksi_core/external_validation_policy.py`
- Test: `tests/contract/test_external_validation_policy.py`, `tests/replay/test_external_validation_policy_replay.py`

**Interfaces:**
- Consumes: `ExternalValidationPolicyV1`, `DurableJournal`.
- Produces: `ExternalValidationPolicyRegistry`, `select_for_inspection(subject) -> PolicySelection`, `select_for_use(use, subjects) -> PolicySelection`, `admit(policy, actor, now) -> PolicyReceipt`, `revoke(policy_id, version, actor, now) -> PolicyReceipt`.

- [ ] **Step 1: Write failing policy selection/revocation tests.**

```python
def test_no_policy_is_visible_pending_not_a_job() -> None:
    assert ExternalValidationPolicyRegistry(_journal()).select_for_inspection(_subject()).status == "INSPECTION_PENDING_POLICY"

def test_revocation_blocks_future_selection_not_history() -> None:
    registry, receipt = _active_registry()
    registry.revoke(receipt.policy_id, receipt.version, actor="authority", now=NOW)
    assert registry.resolve(receipt.policy_digest).status == "REVOKED"
```

- [ ] **Step 2: Verify RED.**

Run: `uv run --locked pytest tests/contract/test_external_validation_policy.py tests/replay/test_external_validation_policy_replay.py -q`

Expected: FAIL at missing registry.

- [ ] **Step 3: Implement append-only, exact-field events.**

```python
def select_for_inspection(self, subject: SealedExternalSubjectV1) -> PolicySelection:
    matches = [p for p in self._policies.values() if p.status is PolicyStatus.ACTIVE and p.applies_to(subject)]
    return PolicySelection.pending() if not matches else PolicySelection.selected(exactly_one(matches))
```

Persist admitted/revoked/superseded events with canonical digest. Duplicate version+different canonical body conflicts. `admit` must first resolve the supplied authority-record digest in an injected `PolicyAuthorityPort`; if absent, inactive, expired, or not scoped to that policy it returns `POLICY_AUTHORITY_UNRESOLVED` and writes no event. Production assembly supplies a port with no records until the authorized authority path exists; tests use `FakePolicyAuthorityPort` and label its records `synthetic_test_only`. Do not mount policy administration until Task 0 authorizes permission/audit semantics.

Exact authorization uses an acyclic canonical chain: a versioned/domain-separated authorized policy-body digest excludes exactly `policyDigest` and `authorityRecordDigest`; the authority record binds that body digest and all scope/actor/use/interval/synthetic fields, excluding only its own digest; the final policy digest includes that finalized authority-record digest. Recompute every link during admission, selection, and replay. Replay resolves the trusted immutable record at the historical event time, not merely the embedded snapshot; current selection separately checks current availability/interval and exact snapshot agreement. Every policy-version field is a strict positive integer (never boolean/float). Use selection requires one subject for INSPECTION/DISPLAY/HEIGHT and two distinct ordered subjects for VISUAL_COMPARISON/RELATIVE_VOLUME.

- [ ] **Step 4: Add replay hardening and verify GREEN.**

```python
def test_replay_refuses_active_policy_with_unlimited_envelope(tmp_path: Path) -> None:
    with pytest.raises(ExternalValidationPolicyRecoveryError): ExternalValidationPolicyRegistry(_forged_journal(tmp_path))
```

Run: `uv run --locked pytest tests/contract/test_external_validation_policy.py tests/replay/test_external_validation_policy_replay.py -q`

Expected: PASS; no valid active policy is implicit.

### Task 3: Inspection issue/queue/lease/replay in Core

**Files:**
- Create: `services/core/src/ksi_core/external_artifact_inspections.py`, `services/core/src/ksi_core/external_display_artifacts.py`
- Modify: `services/core/src/ksi_core/external_reconstruction.py` only to expose a read-only sealed-revision snapshot for reconciliation and call the issued callback after its existing seal event commits, outside the ingress lock. Existing seal event/history remains unchanged.
- Modify: `services/core/src/ksi_core/app_assembly.py`
- Test: `tests/contract/test_external_artifact_inspections.py`, `tests/contract/test_external_display_artifacts.py`, `tests/replay/test_external_artifact_inspections_replay.py`, `tests/replay/test_external_display_artifacts_replay.py`
- Shared test support if needed: `tests/support/external_artifact_inspection_fixtures.py` for synthetic sealed revisions, exact authority chains, storage and clocks; never imported by production modules.

**Interfaces:**
- Consumes: sealed revision, registry, journal, existing `LeaseFence` convention.
- Produces: `issue_after_seal(subject, now)`, `reconcile_sealed(now)`, `list_pending(limit)`, `claim(request_id, fence, now)`, `input_for(request_id, fence)`, `heartbeat(request_id, fence, now)`, `record_report(request_id, fence, report, now)`, `record_incomplete_failure(request_id, fence, failure, now)`.

**Exact store/event interfaces:**

| Call or event | Exact signature or required event fields |
|---|---|
| issue | `issue_after_seal(subject: SealedExternalSubjectV1, now: datetime) -> InspectionIssueResult` |
| reconciliation | `reconcile_sealed(now: datetime) -> int` scans every sealed revision and calls issue using the selected policy only. |
| worker operations | `list_pending(limit: int) -> tuple[PendingExternalInspection, ...]`; `claim(request_id: str, fence: LeaseFence, now: datetime) -> InspectionLeaseResult`; `input_for(request_id: str, fence: LeaseFence) -> ExternalInspectionInputResponse`; `heartbeat(request_id: str, fence: LeaseFence, now: datetime) -> InspectionLeaseResult`. |
| finalization | `record_report(request_id: str, fence: LeaseFence, report: ExternalArtifactInspectionReportV1, now: datetime) -> InspectionReportResult`; `record_incomplete_failure(request_id: str, fence: LeaseFence, failure: ExternalInspectionFailureV1, now: datetime) -> InspectionReportResult`. |
| issue event | `kind`, integer `version`, `eventDigest`, `issuedAt`, `request`, `subject`, `policyDigest`, `naturalKey`; event digest covers all except itself. |
| claim/heartbeat event | `kind`, `version`, `eventDigest`, `requestId`, `workerInstanceId`, `leaseAcquisitionId`, positive `leaseGeneration`, aware `leaseExpiresAt`. |
| terminal event | `kind`, `version`, `eventDigest`, `requestId`, subject/policy/payload digests, exact fence, aware `recordedAt`; report events include no raw payload bytes beyond the contract wire record. |
| display events | `external-display-artifact-issued` carries `version`, `eventDigest`, request/display IDs, exact source subject/report/policy/build digests, declared derivative digest/size/type and fence; `external-display-artifact-sealed` carries the same bindings plus Core-observed digest/size/type and aware seal time. Both are immutable and exclude only `eventDigest` from their canonical digest. |

- [ ] **Step 1: Write failing state/fence tests.**

```python
def test_reconcile_issues_once_after_policy_arrives() -> None:
    store, registry = _stores(active=False)
    assert store.issue_after_seal(_sealed(), now=NOW).verdict == "INSPECTION_PENDING_POLICY"
    registry.admit(_finite_policy(), actor="authority", now=NOW)
    assert (store.reconcile_sealed(now=NOW), store.reconcile_sealed(now=NOW)) == (1, 0)

def test_stale_fence_cannot_finalize() -> None:
    store, old, new = _expired_then_reclaimed_store()
    assert store.record_report(_REQUEST, old, _report(), now=NOW).verdict == "LEASE_FENCE_REJECTED"
    assert store.record_report(_REQUEST, new, _report(), now=NOW).verdict == "REPORTED"
```

- [ ] **Step 2: Verify RED.**

Run: `uv run --locked pytest tests/contract/test_external_artifact_inspections.py tests/contract/test_external_display_artifacts.py tests/replay/test_external_artifact_inspections_replay.py tests/replay/test_external_display_artifacts_replay.py -q`

Expected: FAIL at missing store.

- [ ] **Step 3: Implement separate journal/natural key/fenced transitions.**

```python
natural_key = (subject.work_order_id, subject.submission_id, subject.revision, policy.policy_digest)
with self._lock:
    if existing := self._requests_by_natural_key.get(natural_key): return InspectionIssueResult.idempotent(existing)
    self._append_and_apply(issue_event(subject, policy, now))
```

Pin policy at issue; list queued plus expired-running FIFO. Retain an acquisition ID only across retries of the same still-live claim request. Every post-expiry or requeued execution claim uses a fresh acquisition ID and receives the next Core-assigned generation. Replay reconstructs all accepted acquisition IDs per request and rejects reuse of any previously accepted ID; pending discovery does not expose old acquisition IDs. Require worker ID/positive generation for input, heartbeat, report, rejection. Artifact parser/resource rejection is terminal only for that entry in a complete report. Only manifest digest, subject scope, or sealed-byte identity failure invalidates a request. Pre-examination exhaustion is `INSPECTION_FAILED_INCOMPLETE`; retry exhaustion is never success.

**Report/display crash recovery:** inspection evidence becomes immutable `REPORTED`, while its display phase is separately `NOT_REQUIRED` or `QUEUED -> RUNNING -> SEALED | RETRY_EXHAUSTED`. Applying the committed report deterministically enables display work only for the pinned display-capable policy and measured ortho. Retain the active aggregate fence after report acceptance until required display work terminates. Queue/input/report transport projections carry `phase`/`nextAction` and the accepted report when resuming DISPLAY. Pending discovery includes claimable reported requests with unfinished display work; a new generation may resume display without recomputing or replacing the report. A current fence authorizes each display mutation but is not derivative identity: takeover may refresh the same digest-bound declaration grant and seal exact uploaded bytes. Grant before accepted report is forbidden. Display retry exhaustion preserves the report and no receipt, leaving DISPLAY_SANITIZATION_GAP. No third worker lane or new service is introduced.

Tests additionally cover crash after report/before grant, crash after upload/before seal, exact lost-response replay, stale versus successor fence, active/expired/sealed/exhausted pending visibility, and out-of-order display events. Each journal remains append-only; cross-store coordination must avoid lock-order inversion and must not claim cross-journal atomic publication.

**Display mutation coordination:** an inspection-owned closure guard holds the inspection lock, samples fresh authoritative commit time after acquiring it, rechecks active exact fence, absolute deadline, accepted report and pinned DISPLAY policy, and invokes a commit callback that acquires the display lock, re-fetches bindings/terminal state and appends. The only nested order is inspection -> display; no display-locked code calls back into inspection. Grant capability creation and HEAD stay outside both locks. Seal snapshots its declaration, performs HEAD without either lock, then enters the guard and rechecks the same declaration plus observed hash/size/type before appending. Method-entry time cannot authorize a lease that expired during HEAD. The append is the lease/takeover linearization point; the final successful policy selection is the authorization boundary for an overlapping revocation, without holding the policy registry lock or claiming cross-journal atomicity. Test real-store takeover ordering, expiry during HEAD, policy revocation, failure mutation fencing, response loss, and absence of lock inversion.

**Historical display obligation (Task 3 narrow dependency amendment):** Task 3 may add only the read-only `historical_use_permitted(policy_digest, *, use, subjects, at) -> bool` to `services/core/src/ksi_core/external_validation_policy.py`, with regression tests in its already-owned Task 3 tests. It resolves the exact retained policy/authority snapshot, validates their immutable digest binding and subject/use arity, and evaluates `authority.permits_selection(..., now=at)`. It does not use current status, current authority-port availability, competing entries or later lifecycle timestamps, and cannot authorize execution. Live report append and replay derive `displayRequired` identically from exact measured ORTHO plus this pinned capability at the Core report event's `recordedAt`; reject a persisted boolean that differs. Runtime display-store presence does not affect the obligation. A missing display journal can be reconstructed from that obligation after revocation; current unique DISPLAY selection still gates worker claims/mutations. Test both boolean tamper directions, same-timestamp later revocation, later backdated competing admission, missing journal and absent runtime. No global historical selector or lifecycle timestamp retrofit: those would retroactively invalidate accepted history. Review the narrow delta against the saved pre-amendment policy module and rerun Tasks 1–2 regressions as well as Task 3.

**Explicit retry semantics:** Core recognizes `TRANSIENT_IMMEDIATE_RETRY_V1` as eligible-immediately behavior only when the exact pinned, authority-bound policy names it. Missing/unknown rules do not requeue. A closed transient-failure set is distinct from terminal scope/manifest/byte identity or parser/resource failures. Retry events bind one-based total `attemptCount`, typed failure, exact policy digest, recognized rule ID and `nextEligibleAt = recordedAt`; replay preserves that time. `max_retry_attempts` bounds additional leased attempts after the initial attempt across this request, including display takeovers; same live-acquisition transport retries do not consume an attempt. The absolute request deadline is `issuedAt + max_deadline_seconds`, never reset by heartbeat or takeover. Count/deadline exhaustion is typed and terminal, never success; an existing report is preserved. Synthetic fixtures alone enable this rule for local tests. No exponential backoff, overload protection, numeric timing policy or production capacity is inferred; nonzero schedules require a later explicit policy contract.

- [ ] **Step 4: Add idempotency/replay test and verify GREEN.**

```python
def test_exact_report_retry_deduplicates_but_changed_payload_is_rejected() -> None:
    store, fence = _claimed_store()
    assert store.record_report(_REQUEST, fence, _report("a"), now=NOW).verdict == "REPORTED"
    assert store.record_report(_REQUEST, fence, _report("b"), now=NOW).verdict == "PAYLOAD_DIVERGENCE"
```

Run: `uv run --locked pytest tests/contract/test_external_artifact_inspections.py tests/contract/test_external_display_artifacts.py tests/replay/test_external_artifact_inspections_replay.py tests/replay/test_external_display_artifacts_replay.py tests/replay/test_external_reconstruction_replay.py -q`

Expected: PASS; crash/race/reconcile cannot make competing work or rewrite history.

### Task 4: Bounded GeoTIFF/COG inspection worker

**Approved sandbox amendment — 2026-09-07:** The Human approved the [sandbox design](../specs/2026-09-07-external-inspector-docker-sandbox-amendment.md) and [local change-set plan](2026-09-07-external-inspector-docker-sandbox-amendment.md). They replace only the bwrap-runner requirement below, which is retained as historical design context. All other Task 4 behavior and acceptance requirements remain. No automatic fallback, daemon provisioning, container execution, host-backed test, runtime activation or production policy is authorized by local implementation approval.

**Files:**
- Create: `services/processing-controller/src/ksi_processing_controller/external_geotiff_inspector.py`, `services/processing-controller/src/ksi_processing_controller/external_artifact_inspection_worker.py`
- Create: `services/processing-controller/src/ksi_processing_controller/external_sanitized_raster.py`
- Test: `tests/contract/test_external_geotiff_inspector.py`, `tests/contract/test_external_artifact_inspection_worker.py`, `tests/contract/test_external_sanitized_raster.py`

**Interfaces:**
- Consumes: `ExternalInspectionInputResponse`, policy envelope, server capability, `httpx.Client`, workspace.
- Produces: `sanitize_display_raster(input_path: Path, upload_target: EvidenceUploadGrant) -> SanitizedDisplayOutput`; the sanitizer uses the same enforced sandbox and resource envelope as inspection.
- Produces: `SandboxedInspectorRunner.inspect(input_path: Path, expected: SealedByteBindingV1, envelope: ResourceEnvelopeV1) -> ArtifactInspectionOutcomeV1`; `inspect_sealed_artifact(input: ExternalArtifactInputV1, policy: ExternalValidationPolicyV1, client: httpx.Client, workspace: Path) -> ArtifactInspectionOutcomeV1`; `run_external_artifact_inspection(candidate: PendingExternalInspection, *, core: ExternalInspectionCoreClient, http_client: httpx.Client, work_dir: Path) -> None`.

Worker transport types and narrow client protocols are initially defined in the owned external inspection worker module and consumed by Task 7's HTTP adapter. They mirror the Core wire fields without importing `ksi_core` runtime modules or adding a Core service dependency. Shared immutable domain contracts remain in `ksi_event_contracts`; Core ownership in the catalogue denotes issuance/authority, not a worker-to-Core Python import.

Worker sequencing is report-first: inspect/prepare locally, submit the report, use the Core-accepted report digest for display grant/upload/seal. On a DISPLAY-phase takeover, consume the retained accepted report and resume only deterministic sanitization/upload/seal; never rewrite the inspection. HTTP adapters and the external runner preserve the phase projection and current fence on every retry.

- [ ] **Step 1: Write failing byte-boundary tests.**

```python
def test_masked_nan_measures_coverage_but_unmasked_nan_rejects(tmp_path: Path) -> None:
    assert _inspect(_masked_nan(tmp_path)).outcome == "MEASURED"
    assert _inspect(_unmasked_nan(tmp_path)).reason == "UNMASKED_NONFINITE_SAMPLE"

def test_optional_bad_dsm_does_not_reject_ortho(tmp_path: Path) -> None:
    assert _inspect_all(_valid_ortho_and_bad_dsm(tmp_path)).outcomes == {"ortho": "MEASURED", "dsm": "REJECTED"}
```

- [ ] **Step 2: Verify RED.**

Run: `uv run --locked pytest tests/contract/test_external_geotiff_inspector.py tests/contract/test_external_artifact_inspection_worker.py tests/contract/test_external_sanitized_raster.py -q`

Expected: FAIL at missing worker.

- [ ] **Step 3: Stream/check exact bytes, then require the Linux sandbox before parsing.**

```python
path, sha256, size = _stream_exact_capability(input, client, workspace, policy.resource_envelope)
if (sha256, size) != (input.observed_sha256, input.observed_size_bytes): raise SealedByteIdentityMismatch()
return sandbox.inspect(path, SealedByteBindingV1(sha256, size), policy.resource_envelope)
```

On Linux, `SandboxedInspectorRunner` starts a dedicated tiny launcher process before the parser process; the launcher sets `RLIMIT_AS`, `RLIMIT_CPU`, and `RLIMIT_FSIZE`, then execs `bwrap` with an unshared network namespace, read-only bind of the downloaded file, empty temporary directory, and only the pinned GDAL/PROJ runtime read-only. It passes a read-only pinned `proj.db` but no grids except the policy allowlist, sets `PROJ_NETWORK=OFF` and `GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR`, and enforces parent timeout/output-byte caps. Before opening, child code uses the pinned installed GDAL API verified in Task 4's environment check to allow only `GTiff`; it rejects VRT/remote VSI names before decoder use. It scans every raster block/mask under byte/pixel/block/decompressed limits, records finite valid coverage, and rejects unmasked nonfinite samples. Parent cleanup removes the per-attempt directory after every result. If Linux, `bwrap`, limits, pinned runtime, or isolated launch cannot be enforced, return typed `INSPECTOR_SANDBOX_UNAVAILABLE`; never parse unsandboxed or promise cross-platform behavior.

Allow only policy-named GeoTIFF-family grammar/build and content-type/signature hints. Reject malformed offsets/layout, unsupported compression/layout, archives/sidecars/external references, unsafe CRS/vertical resolution, missing/ambiguous georeference, and envelope breach. Report measured transform/footprint/CRS/vertical/bands/layout/nodata/valid coverage.

For the positive DISPLAY mechanical path, Core owns `ExternalDisplayArtifactStore.request_grant(request_id: str, fence: LeaseFence, declared_sha256: Digest, declared_size_bytes: int, content_type: str, now: datetime) -> EvidenceUploadGrant` and `seal(request_id: str, fence: LeaseFence, display_id: str, storage: ObjectStorageObservationPort, now: datetime) -> SanitizedDisplayReceiptV1`. Core issues a distinct server-assigned digest-bound grant, trusted-HEAD validates and rechecks exact derivative hash/size/type, then appends an immutable receipt linking exact inspected source, policy/build, and derivative hash. The worker may write only the permitted sanitized bytes to that grant; Core returns opaque `sanitizedDisplayRef`, never an object key/URL or undocumented write path.

- [ ] **Step 4: Add no-network/incomplete tests and verify GREEN.**

```python
def test_preinspection_exhaustion_creates_no_unexamined_outcome(tmp_path: Path) -> None:
    with pytest.raises(RequestIncompleteResourceFailure): _inspect_all(_oversize_then_unexamined(tmp_path))

@pytest.mark.parametrize("payload", [_vrt_bytes(), _zip_bytes(), _sidecar_reference_tiff(), _decompression_bomb_tiff()])
def test_sandbox_rejects_unsafe_input_without_http_egress(payload: bytes) -> None:
    assert _inspect_bytes(payload, http_canary=_failing_canary()).reason in {"UNSUPPORTED_RASTER", "RESOURCE_LIMIT_EXCEEDED"}

```

Run: `uv run --locked pytest tests/contract/test_external_geotiff_inspector.py tests/contract/test_external_artifact_inspection_worker.py tests/contract/test_external_sanitized_raster.py -q`

Expected: PASS; synthetic inspection only, not vendor/parser acceptance.

### Task 5: Separate evidence ledger and worker/Core validation

**Files:**
- Create: `services/core/src/ksi_core/external_evidence.py`, `services/processing-controller/src/ksi_processing_controller/external_evidence_validator.py`
- Modify: `services/core/src/ksi_core/app.py`, `services/core/src/ksi_core/app_assembly.py`, `contracts/api/openapi-core.yaml`
- Test: `tests/contract/test_external_evidence_api.py`, `tests/replay/test_external_evidence_replay.py`, `tests/contract/test_external_evidence_validator.py`, `tests/contract/test_hostile_input_route_coverage.py`, `tests/contract/test_api_contract_sync.py`

**Interfaces:**
- Consumes: the sealed revision's actual DSM entry, `DigestBoundEvidenceStorage`, a human declaration intent, selected policy, and a worker fence.
- Produces: public human `declare/list/upload-grant/seal` views, private evidence-ledger operations, and worker `validate_external_evidence(candidate: PendingExternalEvidenceValidation, *, core: ExternalEvidenceCoreClient, http_client: httpx.Client, work_dir: Path) -> None`.

**Invariant enforcement:** INV-060 is enforced by principal-derived scope and 404 non-disclosure on every evidence ref lookup. INV-051 is enforced by a separate external evidence ledger, never `ProcessingJob`, `ArtifactRef`, source-media, or managed-checkpoint state. INV-024 is enforced because a human declaration has no RMSE/measurement/verdict field; INV-053 is enforced because declaration/seal produces no eligibility.

**Public identity and scope:** on declaration Core mints a durable internal `evidenceId` and a replay-derivable, server-issued public `evidenceRef` matching `^eev-v1-[0-9a-f]{64}$`. The public ref is the only evidence path segment, just as the pre-existing external revision surface uses returned `submissionRef`; the raw/internal evidence ID is never a client-selected route identity. `evidenceRef` is derived from the persisted scoped stream identity with the same canonical opaque-reference convention used for `submissionRef`, not from a caller-supplied object key or a random response-only alias. Existing journals without evidence entries need no ref migration because no evidence route exists before this task.

**Exact human routes and request boundary:** all routes resolve organization, site, WorkOrder, submission revision, subject, target DSM observation, and clock time from the authenticated Principal and Core state. A foreign or absent WorkOrder, revision, submission ref, or evidence ref is `404`; `SITES_READ` is required for list and `SITES_WRITE` plus a human principal for mutation.

| Route | Request → response | Server-derived facts and forbidden caller fields |
|---|---|---|
| `POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/evidence` | `ExternalEvidenceDeclarationIntentV1`, required `Idempotency-Key` → `201 ExternalEvidenceView` | Body contains only `targetDsmArtifactId`, `declaredContentDigest`, `declaredContentType`, `independenceBasis`. Core verifies the target is the sealed revision's DSM entry and derives `evidenceId`, `evidenceRef`, subject, subject digest, target observed DSM SHA-256, `DECLARED`, and `declaredAt`. Reject body `organizationId`, site/work-order/submission/revision/subject fields, evidence IDs/refs, observed values, time, object key, manifest/record/policy/measurement/verdict/digest fields. |
| `GET .../evidence` | none → `ExternalEvidenceListResponse(items)` | Returns only the scoped revision's opaque refs and facts already durably occurred. `ExternalEvidenceView` exposes `evidenceRef`, declared content digest/type and declared independence basis/time, lifecycle state, then only after seal Core-observed object digest/size/type/time; only after terminal validation it exposes `VALIDATED` or typed `REJECTED` state/reason/time and the ADR-KSI-031-approved aggregate `measuredCheckpointCount`, `meanErrorM`, `maeM`, `rmseM` from the sealed measurement payload. It never returns raw checkpoint coordinates/CSV, `serverObjectKey`, internal IDs, worker/fence identity, presigned URLs, or a future/absent measurement or verdict. |
| `POST .../evidence/{evidence_ref}/upload-grant` | required `Idempotency-Key`, no body → `ExternalEvidenceUploadGrantResponse` | Core derives the private key and issues a digest-bound PUT capability from the already declared content digest/type. Response is `evidenceRef`, `uploadUrl`, `expiresAt`, and `requiredHeaders`; it exposes no object key. No grant after seal. |
| `POST .../evidence/{evidence_ref}/seal` | required `Idempotency-Key`, no body → `ExternalEvidenceView` | Core reads storage and derives observed object digest/size/type, manifest identity/digest, and `observedAt`; a mismatch or unavailable observation publishes no manifest. Caller cannot provide an observation, timestamp, measurement, or verdict. |

`ExternalEvidenceDeclarationIntentV1` is a Core API request model rather than a public copy of `ExternalEvidenceDeclarationV1`. Core alone constructs the immutable declaration contract. `ExternalEvidenceManifestV1.serverObjectKey` remains a private ledger/worker field and must be excluded from every human route schema, response serializer, log, and journal view. The declaration records a customer statement about already-existing customer evidence only; it does not upload raw reconstruction media, create a managed checkpoint record, issue a `ProcessingJob`, or state measurement/trust/eligibility. The read view is deliberately different: after the worker/Core terminal transition it presents the approved aggregate metrics and typed rejection that actually occurred, while never exposing coordinates, raw bytes, internal identity, worker identity, or an unoccurred future fact.

**Human-mutation idempotency and replay:** declaration, grant, and seal all require a non-empty `Idempotency-Key`. Core durably binds `(principalId, organizationId, operation, workOrderId, submissionRef, revision, evidenceRef-or-declarationNaturalKey, canonicalRequestBodyDigest, idempotencyKey)` before returning a mutation result. The declaration natural key is the server-derived subject/target observed DSM plus the exact declared digest/type/independence basis; concurrent or restart-replayed identical declarations, even with distinct keys, resolve to one `evidenceRef` and one declaration event. Reusing a key with a changed operation/scope/body returns `409 IDEMPOTENCY_KEY_CONFLICT` and writes nothing.

Grant events persist the evidence identity, expected declared digest/type, idempotency binding, issue time, and expiration metadata but never a presigned URL or headers. A same-key retry before the recorded expiration re-signs an equivalent capability for the remaining lifetime and returns that fresh URL with the original `expiresAt`; it never replays a stale URL. After expiry it returns typed `IDEMPOTENT_GRANT_EXPIRED` with no URL, and the caller must use a new key to request a fresh capability for the same `evidenceRef`. This makes stale-URL replay explicit without creating another declaration or evidence identity. Seal replay returns the original immutable observed manifest/view and original observation time; concurrent seals serialize through the evidence store/journal, and a changed key/body conflicts rather than creating a second terminal record.

**Exact store interfaces:** `declare_intent(intent: ExternalEvidenceDeclarationIntentV1, *, work_order_id: str, submission_ref: str, revision: int, principal: Principal, idempotency_key: str, now: datetime) -> EvidenceReceipt`; `list_scoped(*, work_order_id: str, submission_ref: str, revision: int, principal: Principal) -> tuple[ExternalEvidenceView, ...]`; `upload_grant(evidence_ref: str, *, work_order_id: str, submission_ref: str, revision: int, principal: Principal, idempotency_key: str, storage: DigestBoundEvidenceStorage, now: datetime) -> EvidenceUploadGrant`; `seal(evidence_ref: str, *, work_order_id: str, submission_ref: str, revision: int, principal: Principal, idempotency_key: str, storage: ObjectStorageObservationPort, now: datetime) -> EvidenceReceipt`; `issue_validation(evidence_id: str, policy: ExternalValidationPolicyV1, now: datetime) -> EvidenceIssueResult`; `record_measurement(validation_id: str, fence: LeaseFence, payload: ExternalEvidenceMeasurementPayloadV1, now: datetime) -> EvidenceRecordResult`. Only the first four accept human route input, and none accepts a caller-constructed `ExternalEvidenceDeclarationV1`. Events are `external-evidence-declared`, `-grant-issued`, `-sealed`, `-validation-issued`, `-validation-claimed`, `-measurement-reported`, `-validated`, `-rejected`, `-revoked`; each has integer version, exact scope/digest bindings, idempotency binding for human mutations, fence when worker-written, aware time, and an `eventDigest` excluding only itself.

- [ ] **Step 1: Write failing one-way/role tests.**

```python
def test_human_declaration_derives_subject_dsm_observation_and_time(client: TestClient) -> None:
    receipt = _declare_evidence(client, targetDsmArtifactId="dsm-1")
    assert receipt["evidenceRef"].startswith("eev-v1-")
    assert receipt["targetDsmObservedSha256"] == _DSM_SHA
    assert receipt["declaredAt"] == NOW.isoformat()
    assert "serverObjectKey" not in receipt

def test_evidence_binds_exact_dsm_without_changing_submission_manifest(client: TestClient) -> None:
    _seal_evidence(client, evidence_ref=_declare_evidence(client)["evidenceRef"])
    assert _submission_manifest(client) == _manifest_before

def test_human_cannot_supply_scope_observation_key_measurement_or_verdict(client: TestClient) -> None:
    body = _evidence_declaration_intent()
    assert client.post(_evidence_url(), json={**body, "subject": _foreign_subject()}).status_code == 422
    assert client.post(_evidence_url(), json={**body, "serverObjectKey": "caller/key"}).status_code == 422
    assert client.post(_evidence_url(), json={**body, "coreVerdict": "VALIDATED"}).status_code == 422

def test_scoped_view_shows_only_occurred_terminal_facts_and_approved_aggregates(client: TestClient) -> None:
    declared = _declare_evidence(client)
    assert "measurement" not in _evidence_view(client, declared["evidenceRef"])
    validated = _validated_evidence_view(client, declared["evidenceRef"])
    assert validated["aggregateMetrics"] == {"measuredCheckpointCount": 3, "meanErrorM": 0.1, "maeM": 0.1, "rmseM": 0.1}
    assert {"coordinates", "serverObjectKey", "evidenceId", "workerInstanceId"}.isdisjoint(validated)

def test_evidence_ref_is_replay_stable_and_never_accepts_the_internal_id(client: TestClient) -> None:
    declared = _declare_evidence(client)
    assert _replayed_evidence_ref(declared["evidenceRef"]) == declared["evidenceRef"]
    assert _seal_evidence(client, evidence_ref=_internal_evidence_id(declared)).status_code == 404

def test_evidence_mutations_are_durable_idempotent_across_restart_and_concurrency(client: TestClient) -> None:
    first = _declare_evidence(client, key="declare-1")
    assert _declare_evidence(_restarted_client(), key="declare-1") == first
    assert _declare_evidence_concurrently(key_a="declare-2", key_b="declare-3") == {first["evidenceRef"]}
    assert _declare_evidence(client, key="declare-1", declaredContentType="text/csv").status_code == 409

def test_grant_and_seal_define_expiry_and_exact_retry_behavior(client: TestClient) -> None:
    evidence = _declare_evidence(client, key="declare-1")
    grant = _evidence_upload_grant(client, evidence["evidenceRef"], key="grant-1")
    replayed = _restarted_client().post(_grant_url(evidence), headers={"Idempotency-Key": "grant-1"}).json()
    assert replayed["expiresAt"] == grant["expiresAt"] and replayed["uploadUrl"]
    assert _fake_storage().presign_calls_for(evidence["evidenceRef"]) == 2
    assert _advance_beyond(grant["expiresAt"], _restarted_client()).post(_grant_url(evidence), headers={"Idempotency-Key": "grant-1"}).json()["verdict"] == "IDEMPOTENT_GRANT_EXPIRED"
    assert _seal_evidence(client, evidence_ref=evidence["evidenceRef"], key="seal-1") == _seal_evidence(_restarted_client(), evidence_ref=evidence["evidenceRef"], key="seal-1")

def test_customer_cannot_submit_measurement_and_worker_needs_fence() -> None:
    assert _customer_measurement().status_code == 403
    assert _worker_measurement(headers={}).status_code == 409
```

- [ ] **Step 2: Verify RED.**

Run: `uv run --locked pytest tests/contract/test_external_evidence_api.py tests/replay/test_external_evidence_replay.py tests/contract/test_external_evidence_validator.py -q`

Expected: FAIL at missing routes/store.

- [ ] **Step 3: Implement scoped `DECLARED→SEALED_BYTE_OBSERVED→VALIDATION_QUEUED→MEASURED→VALIDATED|REJECTED`.**

```python
grant = storage.presigned_put_bound_digest(evidence_key, content_type=declaration.content_type, content_digest=declaration.declared_digest, ttl=DEFAULT_UPLOAD_TTL)
```

Use a distinct private evidence key/manifest and one-way link to the exact submission manifest+DSM digest; never reuse reconstruction-artifact grants. The public upload-grant response serializes the `DigestBoundUploadCapability` URL and required headers, never its key. Worker reads sealed evidence/DSM and writes fenced metrics; Core independently checks scope, target digests, policy, arithmetic, and result consistency. Claimed independence remains declared until a separate trust policy adjudicates it.

- [ ] **Step 4: Test revocation and verify GREEN.**

```python
def test_revocation_stops_new_validation_but_preserves_validated_record() -> None:
    store, record = _validated_evidence(); store.revoke(record.evidence_id, actor="authority", now=NOW)
    assert store.issue_validation(record.evidence_id, _policy()).verdict == "EVIDENCE_REVOKED"
    assert store.get_record(record.evidence_id).state == "VALIDATED"
```

Run: `uv run --locked pytest tests/contract/test_external_evidence_api.py tests/replay/test_external_evidence_replay.py tests/contract/test_external_evidence_validator.py -q`

Expected: PASS; human declarations can only express existing customer facts, opaque route identities do not disclose internal IDs or keys, and a customer declaration cannot become a measurement, trusted result, or eligibility verdict.

### Task 6: Per-use Core decision store and scoped intent/read API

**Files:**
- Create: `services/core/src/ksi_core/external_use_decisions.py`
- Modify: `services/core/src/ksi_core/external_display_artifacts.py`, `services/core/src/ksi_core/external_reconstruction.py`, `services/core/src/ksi_core/app.py`, `services/core/src/ksi_core/app_assembly.py`, `contracts/api/openapi-core.yaml`
- Test: `tests/contract/test_external_use_decisions.py`, `tests/contract/test_external_use_decisions_api.py`, `tests/replay/test_external_use_decisions_replay.py`, `tests/contract/test_external_display_artifacts.py`, `tests/contract/test_hostile_input_route_coverage.py`, `tests/contract/test_api_contract_sync.py`

**Interfaces:**
- Consumes: sealed revision/report, selected policy, sealed display receipt, validated external evidence records, opaque pair/zone refs, and scoped WorkOrder. `HEIGHT` remains an unresolved product definition. `RELATIVE_VOLUME` eligibility retains its already approved operational semantics in PRD §15.4.1 and ADR-KSI-030/031, but this task creates no external request/result, measurement worker, or WorkArea mapping.
- Produces: `request_single(subject, use, idempotency_key, principal, now) -> ExternalUseDecisionV1`, `request_pair(baseline, current, use, zone, idempotency_key, principal, now) -> ExternalPairUseDecisionV1`, `get_scoped(decision_id, organization_id, site_id)`, and a separate scoped display-download view; all routes are under returned `{submission_ref}/revisions/{revision}`.

**Invariant enforcement:** INV-060 is enforced by the exact revision lookup before receipt read or capability issue and 404 for foreign resources. INV-051 keeps display bytes and all external evidence in the external derived-artifact lane. INV-053 requires the selected current policy and exact compatibility bindings before a non-`BLOCKED` eligibility decision. INV-024 keeps absolute-accuracy claims closed. This task emits neither a HEIGHT value nor a relative-volume result.

**Exact decision interfaces:** `request_single(subject: SealedExternalSubjectV1, use: Literal["DISPLAY", "HEIGHT"], idempotency_key: str, principal: Principal, now: datetime) -> ExternalUseDecisionV1`; `request_pair(baseline: SealedExternalSubjectV1, current: SealedExternalSubjectV1, use: Literal["VISUAL_COMPARISON", "RELATIVE_VOLUME"], zone: SealedZoneReferenceV1 | None, idempotency_key: str, principal: Principal, now: datetime) -> ExternalPairUseDecisionV1`; `get_scoped(decision_id: str, organization_id: str, site_id: str) -> ExternalUseDecisionV1 | ExternalPairUseDecisionV1 | None`. `SealedZoneReferenceV1` is `(zone_id: str, revision: int, definition_digest: Digest, observed_crs_digest: Digest, observed_vertical_reference_digest: Digest)` and is required exactly for `RELATIVE_VOLUME`.

**Exact pair evaluation inputs:** Core resolves ordered baseline/current subject records, their exact sealed inspection reports, one current selected policy, and each named sealed display receipt. For a non-`BLOCKED` `VISUAL_COMPARISON`, it verifies all of the following before it writes a decision: each receipt exists and is sealed; `receipt.sourceSubjectDigest` equals its named pair subject digest; `receipt.sourceReportDigest` equals its named inspection-report digest; both receipt `policyDigest` values equal the selected decision policy digest; each receipt is visible in the same scoped revision; neither receipt nor revision is revoked; and policy availability remains current at the decision time. It then persists the ordered `baselineSanitizedDisplayReceiptDigest` and `currentSanitizedDisplayReceiptDigest` with an empty evidence-record collection. `RELATIVE_VOLUME` resolves no display receipt and rejects either supplied or inferred display-receipt digest. It preserves ordered `evidenceRecordDigests`, and before decision/replay Core verifies every one is a currently valid `ExternalEvidenceRecordV1` for its exact subject, observed DSM, and policy; an unknown, revoked, reordered, cross-subject, cross-DSM, cross-policy, or display-receipt digest is a typed blocker. Pair decisions bind their named inspection reports separately.

**Future relative-volume technical packet — not Task 6–8 implementation:** PRD §15.4.1 and ADR-KSI-030/031 already approve the relative-volume operation, units, vertical-reference handling, and uncertainty semantics. A later bounded technical packet must define the external request/result contracts, measurement worker, and WorkArea mapping. It must require an exact match between `decision.zone` and the WorkArea snapshot for zone ID, revision, geometry, CRS, and vertical reference, plus request/result/replay digest binding. It must keep external analysis outside `ProcessingJob` and `ArtifactRef` workflows. This is not a new Human product-approval gate and must not be designed or implemented by this change set.

**Scoped display download interface:** `get_scoped_display_download(*, work_order_id: str, submission_ref: str, revision: int, sanitized_display_ref: str, principal: Principal, storage: EvidenceStorage) -> ExternalSanitizedDisplayDownloadResponse | None`. The route is `GET /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/display-artifacts/{sanitized_display_ref}/download`, requires `SITES_READ`, and returns exactly `sanitizedDisplayRef`, `receiptDigest`, `observedDerivativeSha256`, `observedDerivativeSizeBytes`, `observedDerivativeContentType`, `downloadUrl`, `expiresAt`, and `requiredHeaders` from the short-lived storage capability. It never returns an object key, declaration key, server manifest field, source upload URL, worker identity, or a managed `ArtifactRef`.

Before creating the capability, Core resolves the authenticated tenant and exact revision, requires the referenced receipt to be sealed and bound to that revision, rejects absent/foreign/revoked receipts as `404`, and applies the current display policy/revocation condition as applicable. It captures only the exact receipt/revision/policy identity under its store lock, releases that lock before calling storage presign, then reacquires the lock and re-resolves the same scoped revision, receipt digest, sealed state, current policy, and revocation immediately before handing the capability to the response. Any revoke, supersede, replacement/substitution, policy closure, or revision mismatch during presign discards the capability and returns the normal typed non-disclosure result; it must never return a capability for the pre-check candidate. Storage/presign failure is a typed `503` that returns no partial capability. A receipt's historic existence does not make a download currently available after its policy/revocation gate closes. The route is display delivery only: it never evaluates or persists a use decision or changes the storage capability itself.

- [ ] **Step 1: Write failing semantics/idempotency/scope tests.**

```python
def test_rejected_dsm_keeps_ortho_display_decision_visible() -> None:
    outcome = _decide(_report(ortho="MEASURED", dsm="REJECTED"))
    assert outcome.height.verdict == "BLOCKED"
    assert outcome.display.verdict == "ELIGIBLE"

def test_same_key_changed_pair_conflicts_and_foreign_read_is_404(client: TestClient) -> None:
    assert _post_pair(client, key="k", current="rev-2").status_code == 201
    assert _post_pair(client, key="k", current="rev-3").status_code == 409
    assert _foreign_get(client).status_code == 404

def test_display_download_is_scoped_receipt_bound_and_never_leaks_a_key(client: TestClient) -> None:
    response = _download_display(client, ref=_sealed_display_ref())
    assert response.status_code == 200
    assert set(response.json()) >= {"sanitizedDisplayRef", "receiptDigest", "downloadUrl", "requiredHeaders"}
    assert "objectKey" not in response.json()
    assert _download_display(client, ref=_foreign_display_ref()).status_code == 404

def test_pair_receipts_and_volume_evidence_have_distinct_ordered_bindings() -> None:
    assert _request_visual_pair(_baseline_receipt(), _current_receipt()).verdict == "ELIGIBLE"
    assert _request_visual_pair(_baseline_receipt(), None).reason_codes == ("DISPLAY_RECEIPT_BINDING_INVALID",)
    assert _request_visual_pair(_current_receipt(), _baseline_receipt()).reason_codes == ("DISPLAY_RECEIPT_BINDING_INVALID",)
    assert _request_volume(evidence=(_baseline_evidence(), _current_evidence())).verdict == "ELIGIBLE"
    assert _request_volume(evidence=(_current_evidence(), _baseline_evidence())).reason_codes == ("EVIDENCE_RECORD_BINDING_INVALID",)
    assert _request_volume(evidence=(_baseline_display_receipt_digest(),)).reason_codes == ("EVIDENCE_RECORD_BINDING_INVALID",)

def test_display_download_rechecks_after_presign_mutation(client: TestClient) -> None:
    for mutation in (_revoke_receipt_during_presign, _supersede_receipt_during_presign, _substitute_receipt_during_presign):
        response = _download_display_with_presign_hook(client, mutation)
        assert response.status_code == 404
        assert "downloadUrl" not in response.json()
    assert _download_display_with_presign_hook(client, _storage_failure).status_code == 503
```

- [ ] **Step 2: Verify RED.**

Run: `uv run --locked pytest tests/contract/test_external_use_decisions.py tests/contract/test_external_use_decisions_api.py tests/replay/test_external_use_decisions_replay.py -q`

Expected: FAIL at missing decision surface.

- [ ] **Step 3: Implement durable eligibility-only evaluation.**

Bind a one-subject decision to subject/use/policy/allowed sealed references. DISPLAY requires a policy-gated sanitized path; VISUAL_COMPARISON remains non-quantitative and binds its two ordered receipt digests; HEIGHT is blocked pending its product definition and never derives a numeric value; RELATIVE_VOLUME binds the ordered pair plus exact sealed zone CRS/vertical/geometry, rejects display receipts, and preserves ordered validated evidence records. Body cannot supply scope, policy, observed facts, verdict, keys, receipt digests, or IDs. The Core evaluator, not the contract body's values, resolves and verifies every digest chain described above. A non-`BLOCKED` `RELATIVE_VOLUME` decision records eligibility only; it cannot enqueue, calculate, or expose a numerical result.

- [ ] **Step 4: Test quantitative gate and verify GREEN.**

```python
def test_cross_profile_volume_without_mapping_is_blocked() -> None:
    assert _request_volume(mapping=None).reason_codes == ("COMPATIBILITY_MAPPING_MISSING",)

def test_synthetic_authority_policy_exercises_volume_eligibility_without_a_numeric_result() -> None:
    policy = _synthetic_authority_policy(checkpoint_rule="required", compatibility_mapping="exact-test-map")
    assert _request_volume(policy=policy, evidence=_two_measured_checkpoint_sets(), mapping="exact-test-map").verdict == "ELIGIBLE"
    assert _request_height(policy=policy).verdict == "BLOCKED"

def test_visual_pair_rejects_substituted_receipt_report_policy_or_subject() -> None:
    for tampered in (_wrong_subject_receipt(), _wrong_report_receipt(), _revoked_receipt(), _old_policy_receipt()):
        assert _request_visual_pair(receipt=tampered).reason_codes == ("DISPLAY_RECEIPT_BINDING_INVALID",)

def test_pair_decision_replay_rejects_missing_reordered_or_substituted_evidence_records() -> None:
    journal = _pair_decision_journal_with_ordered_validated_records()
    assert _replay_pair_decision(journal).verdict == "ELIGIBLE"
    for forged in (_missing_volume_record(journal), _reordered_volume_records(journal), _receipt_as_volume_record(journal), _substituted_volume_record(journal)):
        with pytest.raises(ExternalUseDecisionRecoveryError):
            _replay_pair_decision(forged)
```

Run: `uv run --locked pytest tests/contract/test_external_use_decisions.py tests/contract/test_external_use_decisions_api.py tests/replay/test_external_use_decisions_replay.py tests/contract/test_external_display_artifacts.py tests/contract/test_hostile_input_route_coverage.py tests/contract/test_api_contract_sync.py -q`

Expected: PASS; synthetic policy/evidence exercises eligibility mechanics only. Display delivery is receipt-bound and revocation-aware, while the default production registry without authority stays typed and numeric-free. HEIGHT remains an unresolved product definition. Relative-volume request/result, measurement-worker, and WorkArea-mapping implementation remain in the separate future technical packet.

### Task 7: Separate external-only worker, Core client, and mounted work plane

**Files:**
- Create: `services/processing-controller/src/ksi_processing_controller/external_validation_runner.py`
- Modify: `services/processing-controller/src/ksi_processing_controller/core_client.py`, `services/processing-controller/pyproject.toml`, `services/core/src/ksi_core/app.py`, `services/core/src/ksi_core/app_assembly.py`, `contracts/api/openapi-core.yaml`
- Test: `tests/contract/test_external_validation_core_client.py`, `tests/contract/test_external_validation_runner.py`, `tests/contract/test_runner.py`, `tests/contract/test_external_artifact_inspections_api.py`, `tests/contract/test_external_evidence_api.py`, `tests/contract/test_external_use_decisions_api.py`, `tests/contract/test_dev_assembly.py`, `tests/contract/test_production_assembly.py`, `tests/contract/test_api_contract_sync.py`, `tests/contract/test_hostile_input_route_coverage.py`

**Interfaces:**
- Consumes: inspection/evidence Core routes, `LeaseHandle`, processing-worker principal.
- Produces: narrow `ExternalInspectionCoreClient`/`ExternalEvidenceCoreClient`, `PendingExternalInspection(request_id: str, issued_at: datetime)`, `PendingExternalEvidenceValidation(validation_id: str, issued_at: datetime)`, the explicit routes in the table below, and `ksi-external-validation-worker = "ksi_processing_controller.external_validation_runner:main"`.

**Invariant enforcement:** INV-060 is enforced by distinct human `SITES_*` and worker `PROCESSING_WORK` surfaces, per-resource fences, and 404 non-disclosure. INV-051/053 are enforced by the separate inspection and evidence lanes and absence of managed job/artifact routes. The mounted worker reports observed bytes or typed failure only; it cannot publish a HEIGHT value, a relative-volume result, or manufacture quantitative authority.

- [ ] **Step 1: Write failing fence/fairness/assembly tests.**

```python
def test_external_report_uses_its_own_fence() -> None:
    core = _client(); core.acquire_external_inspection_lease("ext-1"); core.submit_external_inspection_report("ext-1", _report())
    assert _last_headers()["X-KSI-Lease-Generation"] == "1"

def test_existing_managed_runner_order_is_unchanged() -> None:
    assert inspect.getsource(run_pending_batch) == _managed_runner_source_before

def test_external_runner_reset_is_advisory_and_alternates_after_success() -> None:
    core = _external_pending(inspections=2, evidence=2)
    assert _new_external_runner().preferred_kind == "INSPECTION"
    _run_two_rounds(core)
    assert core.claimed == ["inspection-1", "evidence-1"]

def test_external_runner_handles_empty_busy_network_and_expired_takeover() -> None:
    assert _run_round(_external_pending(inspections=0, evidence=1)).claimed == ["evidence-1"]
    assert _run_round(_busy_inspection_then_evidence()).claimed == ["evidence-1"]
    assert _run_round(_network_failure()).claimed == []
    assert _run_round(_expired_inspection_takeover()).claimed == ["inspection-expired"]
```

- [ ] **Step 2: Verify RED.**

Run: `uv run --locked pytest tests/contract/test_external_validation_core_client.py tests/contract/test_external_validation_runner.py tests/contract/test_runner.py tests/contract/test_external_artifact_inspections_api.py -q`

Expected: FAIL at absent methods/routes.

- [ ] **Step 3: Add narrow protocols and external-only runner.**

```python
class ExternalInspectionCoreClient(Protocol):
    def list_pending_external_inspections(self, *, limit: int = 50) -> list[PendingExternalInspection]: ...
    def acquire_external_inspection_lease(self, request_id: str) -> LeaseHandle | None: ...
    def get_external_inspection_input(self, request_id: str) -> ExternalInspectionInputResponse: ...
    def submit_external_inspection_report(self, request_id: str, report: ExternalArtifactInspectionReportV1) -> None: ...
```

Reuse `(work_kind, resource_id)` and `_required_fence_headers`, never managed-job leases. Leave `runner.run_pending_batch` unchanged and retain its current managed-order regression tests. `external_validation_runner` starts with local advisory `preferred_kind="INSPECTION"`; each poll lists the inspection and evidence lanes, attempts only the selected lane through its kind-specific lease endpoint, flips preference only after a successful claim, and tries the other lane if selected lane is empty/busy. Network/Core failure ends that poll without flip. The cursor resets on process restart; fairness is deterministic only across repeated polls in one process when both lanes are claimable, and correctness/replay depend only on durable queues, leases, and results—not the advisory cursor. This separate entrypoint runs in the existing processing-controller service boundary; adding it is not a deployment action.

| Route | Request → response | Role/fence | Journal event |
|---|---|---|---|
| `GET /v1/internal/external-validation/inspections` | none → `ExternalInspectionPendingListResponse(items)` | `PROCESSING_WORK`; no fence | none |
| `POST /v1/internal/external-validation/inspections/{request_id}/lease` | none → `ExternalInspectionLeaseResponse` | processing worker; worker ID/acquisition ID/generation | `external-inspection-claimed` |
| `GET /v1/internal/external-validation/inspections/{request_id}/input` | none → `ExternalInspectionInputResponse` | processing worker; all three fence headers | none |
| `POST /v1/internal/external-validation/inspections/{request_id}/heartbeat` | none → lease response | processing worker; all fence headers | `external-inspection-heartbeat` |
| `POST /v1/internal/external-validation/inspections/{request_id}/report` | `ExternalArtifactInspectionReportV1` → report response | processing worker; all fence headers | `external-inspection-reported` |
| `POST /v1/internal/external-validation/inspections/{request_id}/incomplete-failure` | `ExternalInspectionFailureRequest(reason, detail)` → report response | processing worker; all fence headers | `external-inspection-incomplete-failed` |
| `POST /v1/internal/external-validation/inspections/{request_id}/display-artifacts/upload-grants` | `SanitizedDisplayDeclarationV1` → `EvidenceUploadGrant` | processing worker; all fence headers | `external-display-artifact-issued` |
| `POST /v1/internal/external-validation/inspections/{request_id}/display-artifacts/{display_id}/seal` | no body → `SanitizedDisplayReceiptV1` | processing worker; all fence headers | `external-display-artifact-sealed` |
| `GET /v1/internal/external-validation/evidence-validations` | none → `ExternalEvidencePendingListResponse(items)` | `PROCESSING_WORK`; no fence | none |
| `POST /v1/internal/external-validation/evidence-validations/{validation_id}/lease`, `/heartbeat`, `/report`, `/reject` | none/`ExternalEvidenceMeasurementPayloadV1`/`ExternalEvidenceRejectRequest` → typed lease/record responses | processing worker; all fence headers except initial lease | `external-evidence-validation-claimed`, `-heartbeat`, `-measurement-reported`, `-rejected` |
| `GET /v1/internal/external-validation/evidence-validations/{validation_id}/input` | none → `ExternalEvidenceValidationInputResponse` | processing worker; all fence headers | none |
| `GET /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/inspection` | none → `ExternalArtifactInspectionView` | `SITES_READ`; no fence | none |
| `POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/evidence` | `ExternalEvidenceDeclarationIntentV1` + `Idempotency-Key` → `ExternalEvidenceView` | human `SITES_WRITE`; no fence | `external-evidence-declared` |
| `GET /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/evidence` | none → `ExternalEvidenceListResponse` | `SITES_READ`; no fence | none |
| `POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/evidence/{evidence_ref}/upload-grant` | `Idempotency-Key`, no body → `ExternalEvidenceUploadGrantResponse` | human `SITES_WRITE`; no fence | `external-evidence-grant-issued` |
| `POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/evidence/{evidence_ref}/seal` | `Idempotency-Key`, no body → `ExternalEvidenceView` | human `SITES_WRITE`; no fence | `external-evidence-sealed` |
| `GET /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/display-artifacts/{sanitized_display_ref}/download` | none → `ExternalSanitizedDisplayDownloadResponse` | `SITES_READ`; no fence | none |
| `GET /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/use-decisions` | none → `ExternalUseDecisionListResponse` | `SITES_READ`; no fence | none |
| `POST /v1/observation-work-orders/{work_order_id}/external-reconstruction-submissions/{submission_ref}/revisions/{revision}/use-decisions` | `ExternalUseDecisionIntentRequest` → single/pair decision receipt | human `SITES_WRITE`; `Idempotency-Key`; no fence | `external-use-decision-requested`, `external-use-decision-recorded` |

Every route identity is opaque; foreign/missing resources are 404; mutation idempotency is `(principalId, organizationId, operation, canonicalBody, idempotencyKey)`. `submission_ref`, `evidence_ref`, and `sanitized_display_ref` use their server-issued reference forms, never a raw customer or storage identity. `ExternalInspectionInputResponse.artifacts` carry manifest-entry ID, `sha256:<64 lowercase hex>`, positive size, content type, `downloadUrl`, and required download headers. Human evidence declaration accepts neither object key nor observed fields; its grant serializes `uploadUrl`, `expiresAt`, and `requiredHeaders` directly from `DigestBoundUploadCapability`; callers never construct keys or URLs. The display-download response serializes only its opaque ref, sealed receipt digest, Core-observed hash/size/type, expiration, and the exact short-lived GET capability URL/headers; public routes do not serialize `serverObjectKey`.

- [ ] **Step 4: Add route security/nonstarvation tests and verify GREEN.**

```python
def test_human_cannot_claim_and_foreign_worker_gets_404(client: TestClient) -> None:
    assert _claim(client, principal="operator").status_code == 403
    assert _foreign_input(client, principal="worker-org-a").status_code == 404

def test_display_grant_requires_headers_and_seal_rejects_wrong_hash_or_stale_fence() -> None:
    grant = _display_grant(_active_fence())
    assert grant.required_headers
    assert _seal_display(_wrong_hash(), _active_fence()).verdict == "DISPLAY_DIGEST_MISMATCH"
    assert _seal_display(_correct_hash(), _stale_fence()).verdict == "LEASE_FENCE_REJECTED"

def test_evidence_and_display_public_routes_are_scoped_and_fail_closed(client: TestClient) -> None:
    evidence = _declare_evidence(client)
    assert _evidence_upload_grant(client, evidence["evidenceRef"]).json()["requiredHeaders"]
    assert _foreign_evidence_list(client).status_code == 404
    assert _download_revoked_display(client).status_code == 404
```

Run: `uv run --locked pytest tests/contract/test_external_validation_core_client.py tests/contract/test_external_validation_runner.py tests/contract/test_runner.py tests/contract/test_external_artifact_inspections_api.py tests/contract/test_external_evidence_api.py tests/contract/test_external_use_decisions_api.py tests/contract/test_dev_assembly.py tests/contract/test_production_assembly.py tests/contract/test_api_contract_sync.py tests/contract/test_core_client.py -q`

Expected: PASS; only durable assembly mounts the surface; managed runner behavior is unchanged, external local-cursor conditional fairness is tested, private worker display grants/seals are fenced and hash-checked, and human evidence/display routes are scoped, opaque, object-key-free, and fail closed on revocation/storage failure.

### Task 8: Integrated evidence, documentation, and explicit release inventory

**Files:**
- Create: `tests/e2e/test_external_artifact_validation_flow.py`, `docs/audit/EXTERNAL_ARTIFACT_VALIDATION_LOCAL_VERIFICATION.md`
- Modify: `docs/acceptance/REQUIREMENTS_TRACEABILITY_v3.0.csv`, `services/core/README.md`, `services/processing-controller/README.md`
- Do not create dashboard implementation; document the future handoff in the Core README only.

**Interfaces:**
- Consumes: Tasks 1–7 and synthetic object storage.
- Produces: one local verification record separating software PASS from pending policy/parser/ops/data/release/HIL/field gates and a UI handoff note.

**Invariant enforcement:** The E2E covers INV-060 tenant non-disclosure, INV-051 external-only workflow separation, INV-053 policy/receipt-gated eligibility, and INV-024's absence of unverified absolute-accuracy output. It records synthetic mechanics only and cannot turn those invariants into vendor, field, or numerical-claim acceptance.

- [ ] **Step 1: Write failing mounted eligibility-only full-flow tests.**

```python
def test_synthetic_authority_policy_exercises_mounted_eligibility_without_numeric_outputs(client: TestClient, storage: FakeStorage) -> None:
    baseline, current = _register_and_seal_pair_pending_policy(client, storage)
    _admit_subject_scoped_synthetic_inspection_policy(client, baseline, current)
    _reconcile_inspect_and_seal_sanitized_pair(client, storage, baseline, current)
    _declare_upload_grant_and_seal_existing_checkpoint_evidence(client, storage, baseline)
    _declare_upload_grant_and_seal_existing_checkpoint_evidence(client, storage, current)
    _worker_measure_three_independent_checkpoints_and_vertical_evidence(client, storage, baseline)
    _worker_measure_three_independent_checkpoints_and_vertical_evidence(client, storage, current)
    _admit_subject_scoped_synthetic_quantitative_policy_and_exact_mapping(client, baseline, current)
    assert _decide(client, current, "DISPLAY")["verdict"] == "ELIGIBLE"
    assert _decide_pair(client, baseline, current, "VISUAL_COMPARISON")["verdict"] == "ELIGIBLE"
    assert _decide(client, current, "HEIGHT")["verdict"] == "BLOCKED"
    volume_decision = _decide_pair(client, baseline, current, "RELATIVE_VOLUME", zone=_sealed_zone())
    assert volume_decision["verdict"] == "ELIGIBLE"

def test_no_policy_pending_and_display_policy_ortho_only_are_separate_cases(client: TestClient) -> None:
    no_policy_subject = _register_and_seal(client, _ortho_only())
    assert _inspection(no_policy_subject)["state"] == "INSPECTION_PENDING_POLICY"
    display_subject = no_policy_subject
    _admit_synthetic_display_only_policy(client, subject=display_subject)
    _reconcile_inspect_and_seal_sanitized_ortho(client, display_subject)
    assert _decide(client, display_subject, "DISPLAY")["verdict"] == "ELIGIBLE"
    assert _decide(client, display_subject, "HEIGHT")["verdict"] == "BLOCKED"
    assert _default_production_registry_height(client, display_subject)["verdict"] == "BLOCKED"

def test_human_evidence_and_display_download_stay_separate_from_decision_evaluation(client: TestClient) -> None:
    subject = _register_and_seal(client, _with_dsm())
    evidence = _declare_upload_grant_and_seal_existing_checkpoint_evidence(client, subject)
    assert evidence["state"] == "SEALED_BYTE_OBSERVED"
    display = _reconcile_inspect_and_seal_sanitized_ortho(client, subject)
    download = _download_display(client, subject, display["sanitizedDisplayRef"])
    assert "objectKey" not in download
    assert _list_use_decisions(client, subject) == []
```

First register/seal exact subjects without a policy; this creates visible pending-policy state, not a job. Human test calls declare only existing checkpoint bytes and request a digest-bound grant under an opaque evidence ref; Core, not the request, derives scope, observed DSM, object observation, and time. Then admit subject-scoped synthetic inspection/display/evidence-measurement policy, reconcile, and run the workers. Only after their measurements exist, construct the synthetic external-readiness-profile, exact subject-scope source-trust adjudication, three-checkpoint uncertainty, explicit vertical-reference, and baseline/current compatibility-mapping records and admit the quantitative policy referencing their digests. The flow proves a `RELATIVE_VOLUME` eligibility decision only; it does not create an external request/result, WorkArea mapping, measurement worker, or numerical output. No authority record references an unborn subject or future measurement. Every numeric fixture value is labelled `synthetic_test_only`; these fixtures prove positive eligibility mechanics only, never production trust, threshold, capture truth, compatibility, or release eligibility.

- [ ] **Step 2: Verify RED.**

Run: `uv run --locked pytest tests/e2e/test_external_artifact_validation_flow.py -q`

Expected: FAIL before all wiring exists. Synthetic test authority is fixture-only, not production configuration; this does not establish eligibility/release.

- [ ] **Step 3: Document evidence limits and rollback.**

```markdown
| Local contract/replay/E2E | deterministic synthetic software mechanics | vendor compatibility, capacity, real data, remote CI, deployment, HIL, field, release |
```

Document state machines, role matrix, opaque-reference boundary (`submissionRef`, `evidenceRef`, `sanitizedDisplayRef`), no-raw-upload implication, server-derived human declaration facts, occurred-only aggregate read views, no client measurement/verdict/object key, durable idempotency/expired-grant behavior, current-policy/revocation-gated display download, runner fairness, and authorized rollback. State explicitly that eligibility does not create a HEIGHT value or user flow. Record that approved relative-volume cut/fill/net, units, vertical-reference, and uncertainty semantics are retained while its external request/result, measurement worker, and WorkArea mapping are deferred to the stated future technical packet; remaining trust, compatibility, data, deployment, and field gates still apply. Rollback disables enqueue/claim/new decisions or makes routes read-only; it does not delete/mutate/backfill/bypass sealed history.

- [ ] **Step 4: Run locked integrated validation; use the stated fallback only if locked `uv` cannot run.**

Run: `uv run --locked pytest tests/contract/test_external_artifact_validation_contracts.py tests/contract/test_external_validation_policy.py tests/contract/test_external_artifact_inspections.py tests/contract/test_external_display_artifacts.py tests/contract/test_external_geotiff_inspector.py tests/contract/test_external_artifact_inspection_worker.py tests/contract/test_external_sanitized_raster.py tests/contract/test_external_evidence_api.py tests/contract/test_external_evidence_validator.py tests/contract/test_external_use_decisions.py tests/contract/test_external_use_decisions_api.py tests/contract/test_external_validation_core_client.py tests/contract/test_external_validation_runner.py tests/contract/test_external_artifact_inspections_api.py tests/contract/test_external_reconstruction_contracts.py tests/contract/test_external_reconstruction_api.py tests/contract/test_runner.py tests/contract/test_core_client.py tests/contract/test_api_contract_sync.py tests/contract/test_dev_assembly.py tests/contract/test_production_assembly.py tests/contract/test_hostile_input_route_coverage.py tests/replay/test_external_validation_policy_replay.py tests/replay/test_external_artifact_inspections_replay.py tests/replay/test_external_display_artifacts_replay.py tests/replay/test_external_evidence_replay.py tests/replay/test_external_use_decisions_replay.py tests/replay/test_external_reconstruction_replay.py tests/e2e/test_external_artifact_validation_flow.py tests/e2e/test_external_reconstruction_upload_flow.py -q`

Expected: PASS in the locked workspace. It establishes only synthetic software mechanics: external analysis never becomes `ProcessingJob` or `ArtifactRef`; public evidence/display paths never disclose server object keys; and `RELATIVE_VOLUME` ends at eligibility, without an external numerical result. If `uv run --locked` cannot start, record its exact failure and run only this diagnostic (not tests): `uv run --locked python -c "import ksi_core, ksi_processing_controller, ksi_event_contracts; print(ksi_core.__file__); print(ksi_processing_controller.__file__); print(ksi_event_contracts.__file__)"`. Do not substitute another worktree/venv, install, alter lockfiles, or call unavailable validation a pass.

- [ ] **Step 5: Check ownership/docs and request independent review plus Lead integration gate.**

Run: `git diff --check && rg -n "EXT-VAL-0[1-8]|ExternalArtifactInspection|ExternalEvidence|ExternalUseDecision" docs/acceptance/REQUIREMENTS_TRACEABILITY_v3.0.csv services/core/README.md services/processing-controller/README.md docs/audit/EXTERNAL_ARTIFACT_VALIDATION_LOCAL_VERIFICATION.md && git status --short && /home/ksi/Desktop/KSI-Projects/ksi-claude-harness/plugins/ksi-harness/scripts/ksi-goals.py --dir /tmp/ksi-flight-planning-design.wdFlvL/worktree status`

Expected: no whitespace errors; only task-owned changes; helper-reported goal evidence remains in-progress until the `.ksi` helper is separately authorized to record accepted completion; no synthetic test authorizes policy, capacity, data, remote CI, deployment, HIL, field, or release.

## Execution order and gates

1. Task 4A/4B's reviewed parser/runtime boundary and its separately measured host enforcement prerequisite precede Tasks 5–8. Task 1A corrects the pair contract before Task 6 persists any decision or mounts any use-decision route; it requires its own independent review.
2. One writer in the shared worktree executes Tasks 5→8 only after their prerequisites are accepted, with independent review after each idle writer diff. Reviewers do not edit.
3. Only after Tasks 1A–2 stabilize signatures may the Lead use disjoint worktrees for Core and worker work; each has a reviewer, followed by an integrated Core/worker/OpenAPI review and Lead’s narrowest integrated validation.
4. Task 5 mounts scoped human evidence declaration/list/grant/seal before the worker-only validation lane. Task 6's display delivery is receipt-bound and read-only; it neither creates a decision nor exposes a storage key. Task 7 must expose each route in OpenAPI and production assembly only after the owning Core tests pass.
5. External analysis remains outside managed `ProcessingJob` and `ArtifactRef` workflows at every task boundary. Do not adapt managed job routes, managed artifact download routes, source-media authority, profile identity, checkpoint storage, or `AnalysisReadiness` to make these tasks fit.
6. Valid review findings return to the owning writer and repeat that task’s review. No commit, push, merge, publish, deploy, policy activation, credential change, customer-data access, or device/HIL operation without Human authorization.
7. Release sequence is additive inspection/evidence persistence, gated DISPLAY, non-quantitative VISUAL_COMPARISON, and relative-volume eligibility after trust, compatibility, parser/security, resource/operations, data/license, deployment, and field evidence. Any external relative-volume request/result remains the separate future technical packet. HEIGHT remains pending its separate product definition. Synthetic all-blocked or happy-path mechanics do not complete the goal.

## Acceptance boundaries

| Axis | Needed conclusion |
|---|---|
| Local software | Recorded contract/schema, Core API, replay/fence, worker boundary, fair-runner, and synthetic E2E PASS. |
| Quantitative eligibility | Approved INV-053 treatment, policy governance/trust/thresholds, exact evidence, and mapping. |
| Numerical product claim | HEIGHT definition, units, uncertainty presentation, user flow, and acceptance remain a separate Human decision. Relative volume uses the approved ADR-KSI-030/031 and PRD §15.4.1 operation; external mapping still needs the stated trust, compatibility, data, deployment, and field evidence. |
| Parser/operations | Approved grammar/build/supply-chain; configured finite envelope and capacity evidence. |
| Production/data | Human-approved customer data, license/retention, export compatibility, deployment, remote CI, and release evidence. |
| HIL/field | Not established by this work; only a separately scoped physical route could produce it. |

Plan status: Human approved execution on 2026-09-07 and requested implementation by change set with independent review. This authorizes the scoped local implementation and verification, not production policy activation, release, deployment, customer data, or device actions. Accuracy thresholds, producer compatibility, and external-readiness authority remain their explicit separate gates.

### Local implementation checkpoint — 2026-09-07

| Change set | Current evidence |
|---|---|
| Task 1 contracts/schemas | Independent Spec/Quality PASS after correction; Lead combined ingress/new contract check: 71 passed. |
| Task 2 policy registry | Independent Spec/Quality PASS after correction; 31 targeted tests; Lead Tasks 1+2 combined check: 102 passed, Ruff/mypy clean. |
| Task 3 inspection/display stores | Task-level and bounded Tasks 1–3 integration PASS after corrections. Lead final combined contract/policy/inspection/ingress/replay: 197 passed; dev/production assembly: 59 passed; Ruff/mypy clean. Independent integration reviewer reproduced both corrected boundaries and passed nine focused cases. Local slice only, not whole-goal or parser acceptance. |
| Tasks 4–8 | Not implemented/accepted by this checkpoint. Human-approved existing-image Docker diagnostic completed: both pinned images exposed the requested basic controls; worker image passed a tiny synthetic GeoTIFF/COG roundtrip. Neither image declares volumes; diagnostic containers were removed. Worker image PATH lookup did not find bwrap, and the previously observed host bwrap namespace failure is not resolved. This is candidate feasibility evidence, not approval to replace Task 4's backend or parser/security acceptance. |

These are uncommitted local changes in the assigned worktree, not remote CI, deployment, policy activation, parser acceptance, full-goal completion, or release evidence. The per-task execution ledger and review snapshots are in `.superpowers/sdd/2026-09-07-external-artifact-validation/`; the repository goal remains in progress.

### Approved diagnostic checkpoint — 2026-09-07

Independent evidence guardian: PASS for the bounded diagnostic claim only. `bwrap: null` is a PATH lookup result, not a filesystem-wide absence proof. Resource values are observed configuration, not stress-test evidence; noexec is a requested mount option, not an execution-denial test. Task 4 and production acceptance remain unverified.

Human approved only the previously requested ephemeral diagnostic. Two runs used existing immutable image IDs, `--pull never`, `--network none`, `--read-only`, dropped capabilities, no-new-privileges, non-root UID/GID, finite cgroup limits and a small noexec tmpfs. No host workspace/customer-data/socket mount, image build/download, deployment or host security change was performed. Both processes exited zero and the labeled-container inventory was empty afterward.

Observed: effective capabilities zero; no-new-privileges set; seccomp mode 2; only loopback; reserved test-address connection failed with ENETUNREACH; root write failed with EROFS; requested CPU/memory/PID limits visible. Existing worker raster libraries roundtripped a synthetic 16×16 GeoTIFF and COG. These observations do not establish sandbox escape resistance, hostile-raster handling, resource-exhaustion behavior, producer compatibility or supply-chain acceptance. Numeric limits were diagnostic fixtures, not approved operational policy. The worker image PATH lookup did not find bwrap; Task 4 remains unimplemented and its original sandbox mechanism unverified here.

Exact commands, source and raw outputs: `.superpowers/sdd/2026-09-07-external-artifact-validation/sandbox-diagnostic-{commands.txt,base.py,worker.py,results.json}`. Next decision is a separately reviewed Task 4 backend amendment or a validated environment for the existing bwrap design; diagnostic approval does not authorize a Docker-daemon production trust boundary.
