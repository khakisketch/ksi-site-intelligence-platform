# External Quantitative Authority V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide the durable, production-safe Core authority that permits only an exact same-profile external DSM pair to enter the existing relative-volume workflow.

**Architecture:** Add a two-stage append-only authority catalog: compatibility is admitted before a decision, while an exact execution snapshot is appended only after the existing evaluator creates that decision and before a request is issued. The catalog implements the existing mapping, execution and independent historical-use ports; an explicit configuration/builder boundary injects it into the common assembly and never creates authority facts.

**Tech Stack:** Python 3.12, Pydantic v2 contracts, `DurableJournal`, canonical JSON digests, existing FastAPI/Core assembly and pytest contract/replay tests.

**Spec:** `docs/superpowers/specs/2026-09-09-external-quantitative-authority-v1.md`

## Global Constraints

- Requirements: REQ-INT-101..104, REQ-SEC-101, REQ-OPS-102.
- Invariants: INV-017/018/020/024/040/051/053/060.
- External evidence never receives a managed profile, ProcessingJob, source bundle or accuracy claim.
- V1 accepts only the exact same immutable external profile/build/CRS/vertical rule; cross-profile mapping is unsupported.
- Numeric limits and thresholds must be present in admitted digest-bound policies; no defaults or client overrides.
- No host, credential, customer-data, deployment, Git publication or device action is part of this plan.
- No commit step is executed without separate Human authorization.

---

### Task 1: Durable authority lifecycle and ports

**Files:**
- Create: `services/core/src/ksi_core/external_quantitative_authority.py`
- Modify: `services/core/src/ksi_core/external_use_decisions.py`
- Test: `tests/contract/test_external_quantitative_authority.py`
- Modify: `tests/contract/test_external_use_decisions.py`
- Test: `tests/replay/test_external_quantitative_authority_replay.py`

**Interfaces:**
- Consumes: existing `ExternalRelativeVolumeAuthorityPort`, `ExternalRelativeVolumeExecutionAuthorityPort`, `ExternalRelativeVolumeHistoricalUseAuthorityPort`, `ExternalAuthorityCurrentnessCoordinator`, reconstruction/inspection/policy/evidence/WorkArea participants, and an exact private current-decision resolver on `ExternalUseDecisionStore`.
- Produces: `ExternalQuantitativeAuthorityCatalog` implementing all three existing ports; compatibility `admit_mapping(record, actor, now)` / `revoke_mapping(mapping_digest, actor, now)` and post-decision `activate_execution(decision_ref, principal, current_work_order_id, now)` / `revoke_execution(authority_digest, actor, now)` methods.

- [ ] Write failing tests for exact positive same-profile records and every subject/order/org/site/WorkOrder/zone/CRS/vertical/profile/build/evidence/actor/time substitution.
- [ ] Write failing tests showing mapping admission occurs without a decision, then execution activation fails before the decision and succeeds only after the exact existing decision is present.
- [ ] Write a failing decision-store test for resolving one recorded pair by principal organization, current WorkOrder and decision ID without a caller-supplied site or mapping scan; reject pending, single-use, wrong organization and wrong WorkOrder records.
- [ ] Write failing tests for idempotent retry, conflict, both revocations, revoked-before-use, restart replay, execution-before-decision and malformed journal chronology/digest.
- [ ] Implement separate closed immutable compatibility and execution snapshot models with canonical digest validation; reject synthetic or managed-profile aliases.
- [ ] Add `CompatibilityRuleDescriptorV1` and its callable, pre-inspection
  constructor/digest. It declares the stable profile/parser equality, observed
  CRS/vertical equality, independent measured checkpoints, ordered
  non-overlapping capture intervals, and exact WorkArea-match predicates, while
  excluding organization, site, subjects, inspected values, capture values,
  WorkArea revision, evidence, validation/execution policy, actor and authority
  digests. Pre-authorize only this `compatibilityRuleDigest`; construct a full
  `mappingRecordDigest` later from exact subjects, observations, WorkArea,
  evidence and admitted validation policy. Recompute both and use only the full
  record digest in decisions/execution/history.
- [ ] Implement only the private exact decision resolver required above; keep public routes, schemas, decision identity and idempotency unchanged.
- [ ] Implement append-before-publish mapping activation/revocation and post-decision execution activation/revocation under the shared currentness coordinator.
- [ ] Implement current mapping/execution resolution and independent event-time historical resolution without consulting current roles or recreating a missing snapshot.
- [ ] Run `uv run --frozen --no-sync pytest -q tests/contract/test_external_quantitative_authority.py tests/replay/test_external_quantitative_authority_replay.py` and require all pass.

### Task 2: Production configuration and common assembly

**Files:**
- Create: `services/core/src/ksi_core/external_result_workflow_config.py`
- Modify: `services/core/src/ksi_core/app_assembly.py`
- Modify: `services/core/src/ksi_core/external_result_workflow_assembly.py`
- Modify: `scripts/run_core_dev.py`
- Test: `tests/contract/test_external_result_workflow_config.py`
- Modify: `tests/contract/test_external_workflow_common_assembly.py`
- Modify: `tests/contract/test_core_app_assembly.py`
- Modify: `tests/contract/test_dev_assembly.py`

**Interfaces:**
- Consumes: owner-protected absolute config/catalog paths, injected catalog and validation-policy authority ports, a coordinator-bound evidence-context-authority factory, the common assembly's tracked journal opener, existing queue policy and input capability issuer, Task 1 catalog, and the common assembly's existing `WorkAreaStore` participant.
- Produces: `load_external_result_workflow_config(path, *, participants, input_capability_issuer) -> ExternalResultWorkflowAssemblyConfig` and a builder whose mapping, post-decision execution and history objects share one coordinator/catalog.

- [ ] Write failing tests for absent, relative, symlinked, group/other-readable, oversized, malformed and unknown-field configuration and catalog inputs.
- [ ] Write failing tests showing configuration data cannot set measured facts, policy status, client scope, managed profile identities or implicit thresholds.
- [ ] Add a domain-separated immutable catalog-authority record and port that bind the exact canonical catalog body, organization, administration actors and validity interval; the catalog contains only the authority-record digest and cannot self-approve.
- [ ] Require every production execution policy's `authorityRecordDigest` to equal the resolved catalog-authority record digest; leave the existing validation-policy `PolicyAuthorityRecord` semantics unchanged.
- [ ] Define one strict catalog admission-body serializer that omits only its own top-level and contained catalog-authority references; bind that body in the authority record, insert the sealed authority digest into every omitted reference, and reject any other exclusion or mismatch.
- [ ] Write the strict loader and builder; retain the current explicit-injection default for development callers.
- [ ] Extend the private mapping-factory call with a tracked absolute-path journal opener so the configured authority journal uses the assembly's existing ownership, failure cleanup and `DevAssembly.close()` lifecycle; reject an untracked direct open.
- [ ] Carry an explicit validation-policy authority port and `build_evidence_context_authority(coordinator)` factory through the workflow assembly config into the existing registry/store constructors; the factory must return a port sharing the exact assembly coordinator, absent dependencies retain default-closed behavior, and the production loader rejects missing/mismatched dependencies.
- [ ] Extend the private mapping-factory call with `work_areas=work_area_store`; require the production participant validator to use that exact shared store and reject a different instance.
- [ ] Verify common assembly rejects participant/coordinator mismatches before replay and exposes the positive workflow only after mapping admission, exact decision creation and execution snapshot activation.
- [ ] Verify restart rebuilds the same participants and routes and a revoked record cannot issue new work.
- [ ] Run `uv run --frozen --no-sync pytest -q tests/contract/test_external_result_workflow_config.py tests/contract/test_external_workflow_common_assembly.py tests/contract/test_dev_assembly.py` and require all pass.

### Task 3: Integrated release flow and documentation

**Files:**
- Modify: `services/core/README.md`
- Modify: `docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md`
- Modify: `docs/superpowers/plans/2026-09-06-external-reconstruction-release.md`
- Create: `tests/contract/test_external_quantitative_production_flow.py`

**Interfaces:**
- Consumes: Tasks 1–2 and the existing external reconstruction, inspection, evidence, decision, volume, review, proposal and successor APIs.
- Produces: one restartable exact-pair production-assembly proof with no synthetic authority provider.

- [ ] Build an owned local fixture with a real production-assembly participant
  graph, a pre-authorized rule descriptor, and admitted catalog/policy/evidence
  records; label only storage and customer bytes synthetic, never the authority
  provider. Do not reuse a test-only seeded authority provider, monkeypatch, or
  private reconstruction helper.
- [ ] Exercise register/seal → inspection/evidence acceptance → relative-volume request/report → result review → proposal → explicit approval → planning-only successor.
- [ ] Restart Core between authority activation and request, and again before review; verify journal prefix/digests and historical resolution remain exact.
- [ ] Add negative integration cases for cross-profile, revoked-before-use, tenant substitution, stale WorkArea and missing checkpoint evidence.
- [ ] Document the exact supported V1 rule, configuration requirements, rollback and remaining host/customer/HIL gates.
- [ ] Run the new production-flow test plus the existing external workflow, API contract sync and replay selections; require all pass.
- [ ] Run focused Ruff, strict mypy, `git diff --check`, manifest/hash preservation and an independent reviewer gate before integration.

## Correction-round hardening

Independent review requires fresh currentness rather than relying on admission
time validation. Resolve the external catalog/policy/evidence sources before
the shared coordinator guard, then recheck exact local retained snapshots at
mapping admission/use, execution activation/issue, and final guarded use. The
catalog requires an exact coordinator-bound currentness factory that validates
the retained catalog body/digest, scope, status, and time. Historical replay
continues to evaluate event time only.

Bind the actual eligible `RELATIVE_VOLUME` decision's UTC `decidedAt` to an
execution snapshot and reject a decision later than activation at runtime and
replay. Protect the configured authority journal at the config/tracked-opener
boundary: reject unsafe existing type/owner/mode/link/parent/replacement and
securely create only missing owner-private nodes. Add integrated regressions
for WorkArea supersession, policy/context/catalog revocation, mutation after
resolution, guard-time closure, activation chronology, replay chronology and
journal safety.

## Implementation handoff

Use the existing `/tmp/ksi-external-product-loop-20260909` goal mapping and a single writer in `/tmp/ksi-external-quantitative-authority-20260909`. Preserve the original Desktop WIP and every accepted 60-file hash until reviewed integration. The Lead owns integration and the final local verification. Host bootstrap and product deployment are excluded.
