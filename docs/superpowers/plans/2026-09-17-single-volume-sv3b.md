# SINGLE_VOLUME SV-3b Implementation Plan — review, reobservation proposal and team share

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** An operator can review a SINGLE_VOLUME result, propose reobservation of its WorkArea, approve the successor work order and share the result with a teammate — with the same durable, replay-verified guarantees as a relative-volume result, and without changing a single relative-volume byte.

**Architecture:** A sibling review receipt contract (`ExternalSingleVolumeResultReviewReceiptV1`) carries the single-volume request, report, authority and decision. The existing review store, journal file, review-ref domain and proposal service become family-aware through a discriminated receipt union keyed on `contractVersion`; relative events and digests stay byte-identical. The review source adapter dispatches by report-ref prefix to the relative or single ledger and their historical authority ports. The work-inbox share resolver dispatches the same way. The dashboard extracts its relative review/proposal/approval block into a shared component and mounts it for single results.

**Tech Stack:** Python 3.12, pydantic v2 (discriminated unions), FastAPI, `uv run --locked`; Next.js App Router, TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-09-17-single-volume-design.md` §8 ("Review/proposal") as amended by amendment 1 in `docs/superpowers/plans/2026-09-17-single-volume-sv3.md` (SV-3a). SV-3a outcome and follow-ups: end of that plan.

## Design decisions (made while planning, 2026-09-17)

1. **Sibling receipt, one store.** A single-volume review is a new contract (`external-single-volume-result-review-receipt.v1`) with its own authority model. It is recorded by the existing `ExternalResultReviewStore` in the existing `external-result-reviews.jsonl`, under a new event kind `external-single-volume-result-reviewed`. Relative events keep kind `external-result-reviewed` and their exact bytes. One store keeps one `reportRef → review` index, one `reviewRef` namespace and one startup verification path.
2. **Review ref domain unchanged.** `reviewRef = "err-v1-" + sha256(org \0 reportRef \0 reportDigest)`. Report refs are family-prefixed, so the namespaces cannot collide and relative review refs do not change.
3. **Proposal contract unchanged.** `ExternalReobservationProposalV1` already binds only refs and digests. The proposal service reads the same attribute paths from either receipt (`report.report_digest`, `decision.decision_digest`, `authority.zone_snapshot`, `authority.evidence_record_digests`, `authority.authorized_actor_ids`).
4. **Single historical use authority.** `ExternalSingleVolumeExecutionPort` gains `resolve_historical_for_use(...)`, mirroring the relative catalog method (delegates to `resolve_single_historical` with `issued_at = evaluated_at`).
5. **Shares.** `WorkInboxStore` gets a composite `report_resolver` that dispatches by prefix. New route `POST /v1/external-single-volume-reports/{report_ref}/shares`; the relative route is unchanged.
6. **Exact report routes check provenance** (SV-3a follow-up): both `GET /v1/external-relative-volume-reports/{ref}` and `GET /v1/external-single-volume-reports/{ref}` return 404 when the projector's `_provenance_intact` check fails, so an exact view never shows a report the history shows as unavailable.
7. **Work-order deep link** (SV-3a follow-up): `/field/work-orders/{id}?reportRef=` validates against the exact report for its family (`getExternalRelativeVolumeReport` or `getExternalSingleVolumeReport`) and the site-scoped exact projection (`getSiteExternalRelativeVolumeReport`, which already resolves both families), not against the site-latest summary.

## Global Constraints

- Relative-volume journal events (`external-result-reviewed`), review refs (`err-v1-`), proposal/approval contracts, sealed digests, relative routes and relative Korean copy stay byte-identical. Existing tests under `tests/contract/test_external_result_*`, `test_external_reobservation*`, `test_organization_work_roster_and_inbox.py`, `test_external_relative_volumes.py` and the dashboard relative review tests must pass unchanged, except where a task names an additive assertion.
- New contract versions: `external-single-volume-result-review-authority.v1`, `external-single-volume-result-review-receipt.v1`. Schemas `contracts/schemas/external-single-volume-result-review-receipt.v1.json` (the authority is embedded).
- New journal event kind: `external-single-volume-result-reviewed` (same file `external-result-reviews.jsonl`, same `version: 1`, same `eventDigest` rule, payload key `review`).
- Single factual limitations (exact order): `("SINGLE_VOLUME_IS_OPERATIONAL_ONLY", "ABSOLUTE_ACCURACY_NOT_CLAIMED", "NO_AUTOMATIC_REOBSERVATION_THRESHOLD")`.
- Report-ref prefixes: single `external-single-volume-report-`, relative `external-relative-volume-report-`. Dispatch only on these exact prefixes; any other ref takes the relative path (current behavior).
- New Core routes: `POST /v1/external-single-volume-reports/{report_ref}/reviews` (201, same error details as the relative route), `POST /v1/external-single-volume-reports/{report_ref}/shares` (201). `GET /v1/external-result-reviews/{review_ref}` returns either receipt.
- Dashboard single-volume copy: proposal target line "대상: 이 측정에 사용한 작업구역"; all other review/proposal/approval strings are the existing relative strings. The SV-3a text "단일 시점 결과 검토는 준비 중입니다." is removed everywhere.
- No numeric authority in the dashboard. No new dashboard page.
- Gates per task: targeted pytest / vitest. Before closing: `uv run --locked ruff check .`, `uv run --locked mypy packages services tests tools`, full pytest in bounded chunks (real exit codes), dashboard `npx tsc --noEmit`, `npm run lint`, `npm test`, `npm run build`.
- New Core modules (if any) go into `docs/audit/CORE_R1_MODULE_MIGRATION.json` as `T3_NEW_MODULE`, no alias shims.
- Commits end with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_018rRe93cBYrxioCcEB8TZQ6`

---

## File map

| File | Change |
|---|---|
| `packages/event-contracts/src/ksi_event_contracts/external_single_volume_result_review.py` | new: authority, receipt, union, wire helpers |
| `contracts/schemas/external-single-volume-result-review-receipt.v1.json` | new schema |
| `tests/contract/test_external_single_volume_result_review_contracts.py` | new |
| `services/core/src/ksi_core/domains/external/workflow/external_result_reviews.py` | family-aware store, sources |
| `services/core/src/ksi_core/domains/external/workflow/external_result_review_sources.py` | prefix-dispatching adapter |
| `services/core/src/ksi_core/domains/external/quantity/external_quantitative_authority.py` | `ExternalSingleVolumeExecutionPort.resolve_historical_for_use` |
| `services/core/src/ksi_core/domains/external/quantity/external_single_volume_use_history.py` | new: single historical use port protocol + closed default |
| `services/core/src/ksi_core/composition/external_graph.py`, `composition/workspace_graph.py`, `composition/routes/external.py` | wiring |
| `services/core/src/ksi_core/domains/external/workflow/external_reobservation_proposals.py` | union receipt |
| `services/core/src/ksi_core/domains/external/workflow/external_result_workflow_api.py` | single review join, review route, provenance on exact routes |
| `services/core/src/ksi_core/domains/sites/work_inbox.py` | single share route |
| `services/core/src/ksi_core/domains/sites/external_report_resolver.py` | new: composite resolver |
| `contracts/api/openapi-core.yaml` | routes/schemas |
| `tests/contract/test_external_single_volume_result_reviews.py` | new |
| `tests/contract/test_external_quantitative_production_flow.py`, `test_external_result_single_volume_projection.py`, `test_external_result_briefings.py`, `test_organization_work_roster_and_inbox.py`, `test_hostile_input_route_coverage.py`, `test_api_contract_sync.py` | extended |
| `apps/dashboard/src/lib/core-api/*.ts`, `src/app/api/**` | types, client, BFF |
| `apps/dashboard/src/components/external-results/ExternalResultReviewActions.tsx` | new shared component |
| `apps/dashboard/src/app/field/ExternalResultWorkflowPanel.tsx`, `.../[reportRef]/ExternalReportFollowupTrace.tsx`, `.../[reportRef]/page.tsx`, `src/components/external-results/TeamReportShare.tsx`, `src/app/field/work-orders/[workOrderId]/page.tsx` | single review/proposal/share |

---

### Task 1: Single-volume review receipt contract

**Files:**
- Create: `packages/event-contracts/src/ksi_event_contracts/external_single_volume_result_review.py`
- Create: `contracts/schemas/external-single-volume-result-review-receipt.v1.json`
- Create: `tests/contract/test_external_single_volume_result_review_contracts.py`

**Interfaces:**
- Consumes: `ExternalSingleVolumeDecisionV1`, `ExternalSingleVolumeExecutionPolicyV1`, `ExternalSingleVolumeRequestV1`, `ExternalSingleVolumeReportV1` (`ksi_event_contracts.external_single_volume`); `ExternalVolumeInputBindingV1`, `ExternalVolumeZoneSnapshotV1` (`external_relative_volume`); `ExternalResultReviewReceiptV1` and the private helpers `_FrozenResultReviewModel`, `_BoundedText`, `_digest`, `_require_utc`, `_require_utc_wire` (`external_result_review`).
- Produces:
  - `ExternalSingleVolumeResultReviewAuthorityV1` — fields exactly the camelCase keys of `ExternalSingleVolumeExecutionAuthority.snapshot_payload()` (services/core/.../external_single_volumes.py:280) plus `contract_version` and `authority_digest`; `sealed()`, `canonical_digest()`, `is_active_at(at)`.
  - `ExternalSingleVolumeResultReviewReceiptV1` — `review_ref, organization_id, site_id, source_work_order_id, report_ref, request: ExternalSingleVolumeRequestV1, report: ExternalSingleVolumeReportV1, authority: ExternalSingleVolumeResultReviewAuthorityV1, decision: ExternalSingleVolumeDecisionV1, factual_limitations, reviewed_at, review_digest`; `sealed()`, `canonical_digest()`.
  - `SINGLE_VOLUME_REVIEW_FACTUAL_LIMITATIONS: tuple[str, str, str]`.
  - `ExternalResultReviewReceipt = Annotated[ExternalResultReviewReceiptV1 | ExternalSingleVolumeResultReviewReceiptV1, Field(discriminator="contract_version")]`.
  - `parse_external_result_review_receipt(raw: object) -> ExternalResultReviewReceiptV1 | ExternalSingleVolumeResultReviewReceiptV1` (a module-level `TypeAdapter`).
  - `external_single_volume_result_review_receipt_wire_dict(receipt) -> dict[str, Any]` (sealed, `by_alias=True, mode="json", exclude_none=False`).

- [x] **Step 1: Write failing tests** (reuse the synthetic builders in `tests/contract/test_external_single_volume_contracts.py`; move any you need into `tests/contract/external_single_volume_contract_fixture.py` and import them from both files — no copies):
  1. `test_receipt_seals_and_round_trips` — a receipt built from a sealed request, report, authority and ELIGIBLE decision seals; `model_validate(wire)` equals it; `review_digest == canonical_digest()`.
  2. `test_receipt_rejects_each_broken_binding` — parametrized: request target ≠ authority target; request evidence digests ≠ authority; validation policy digest mismatch; zone snapshot mismatch; execution policy digest mismatch; report request id/digest mismatch; `payload.target_dsm_digest != request.target.observed_sha256`; `payload.zone_snapshot_digest` mismatch; payload policy/algorithm/config digest mismatch; decision not ELIGIBLE; decision subject ≠ `request.target.subject`; decision `inspection_report_digest` ≠ target's; decision evidence ≠ request's; decision zone ≠ `request.zone_snapshot.to_zone_reference()`; decision mapping digest ≠ authority's; `source_work_order_id != request.current_work_order_id`; wrong factual limitations; each raises `ValidationError`.
  3. `test_union_dispatches_on_contract_version` — `parse_external_result_review_receipt` returns the relative class for a relative wire dict (use `test_external_result_review_proposals.py` builders) and the single class for a single wire dict; an unknown `contractVersion` raises.
  4. `test_relative_receipt_digest_is_unchanged` — pin the relative receipt digest from the existing relative fixture as a literal computed before this change.
  5. `test_schema_accepts_wire_and_rejects_extra_keys` — Draft 2020-12 validation of the wire dict against the new schema; an added top-level key fails (pattern: `test_external_single_volume_contracts.py` ~line 216).
- [x] **Step 2: Run** `uv run --locked pytest tests/contract/test_external_single_volume_result_review_contracts.py -q` → FAIL (module missing).
- [x] **Step 3: Implement.** Authority validator mirrors `ExternalResultReviewAuthorityV1._binds_full_authority` with `target` in place of `baseline/current` and `target_rmse_m` in place of the two RMSE fields:

```python
class ExternalSingleVolumeResultReviewAuthorityV1(_FrozenResultReviewModel):
    contract_version: Literal["external-single-volume-result-review-authority.v1"] = (
        "external-single-volume-result-review-authority.v1"
    )
    organization_id: _BoundedText
    site_id: _BoundedText
    current_work_order_id: _BoundedText
    decision_id: _BoundedText
    decision_digest: Digest
    compatibility_mapping_digest: Digest
    target: ExternalVolumeInputBindingV1
    evidence_record_digests: tuple[Digest, ...] = Field(min_length=1, max_length=1)
    validation_policy_digest: Digest
    zone_snapshot: ExternalVolumeZoneSnapshotV1
    execution_policy: ExternalSingleVolumeExecutionPolicyV1
    authorized_actor_ids: tuple[_BoundedText, ...] = Field(min_length=1, max_length=64)
    valid_from: datetime
    valid_until: datetime
    historical_authority_digest: Digest
    target_rmse_m: StrictFloat | None = Field(default=None, ge=0.0, le=1e300)
    maximum_zone_cell_count: StrictInt = Field(ge=1, le=100_000_000)
    maximum_zone_area_m2: StrictFloat = Field(gt=0.0, le=1e300)
    synthetic_test_only: StrictBool
    authority_digest: Digest | None = None
```

  Receipt validator: the checks listed in Step 1 test 2, in that order, each raising `ValueError` with a short message; decision checks require `decision.use == "SINGLE_VOLUME"` and `decision.verdict is DecisionVerdict.ELIGIBLE`. Export everything in `__all__`. Write the JSON schema by hand in the style of `contracts/schemas/external-result-review-receipt.v1.json` (`additionalProperties: false`, `$ref`s to the existing single-volume schemas where that file does so for relative ones).
- [x] **Step 4: Run** the Step 2 command plus `uv run --locked pytest tests/contract/test_external_single_volume_contracts.py tests/contract/test_external_result_review_proposals.py -q` → PASS; `uv run --locked mypy packages/event-contracts tests/contract/test_external_single_volume_result_review_contracts.py`.
- [x] **Step 5: Commit** `feat(contracts): single-volume result review receipt (SV-3b)`

---

### Task 2: Family-aware review store and source adapter

**Files:**
- Create: `services/core/src/ksi_core/domains/external/quantity/external_single_volume_use_history.py`
- Modify: `services/core/src/ksi_core/domains/external/quantity/external_quantitative_authority.py` (`ExternalSingleVolumeExecutionPort`, ~line 2621)
- Modify: `services/core/src/ksi_core/domains/external/workflow/external_result_reviews.py`
- Modify: `services/core/src/ksi_core/domains/external/workflow/external_result_review_sources.py`
- Modify: `services/core/src/ksi_core/composition/external_graph.py` (~line 319, `ExternalResultReviewStore(... CoreExternalResultReviewSourceAdapter(...))`)
- Modify: `docs/audit/CORE_R1_MODULE_MIGRATION.json` (register the new module)
- Test: create `tests/contract/test_external_single_volume_result_reviews.py`

**Interfaces:**
- Consumes: Task 1 contract; `ExternalSingleVolumeStore.preflight_current_report_ref / guard_current_report_ref / resolve_historical_report_ref` (inherited from `ExternalVolumeLedger`, external_relative_volumes.py:2365-2480); `ExternalUseDecisionStore.resolve_historical_single_volume(...)` (external_use_decisions.py:658); `ResolvedSingleVolumeReport` (external_single_volumes.py:349).
- Produces:
  - `ExternalSingleVolumeHistoricalUseAuthorityPort` (Protocol) with `resolve_historical_for_use(*, historical_authority_digest, decision_id, decision_digest, evaluated_at) -> ExternalSingleVolumeExecutionAuthority | None`; `ClosedExternalSingleVolumeUseHistory`.
  - `ExternalSingleVolumeExecutionPort.resolve_historical_for_use(...)` (same signature; delegates to `self._catalog.resolve_single_historical(..., issued_at=evaluated_at, now=evaluated_at)`).
  - `ExternalSingleVolumeResultReviewSourceV1` (frozen dataclass: `report_ref, request, report, authority: ExternalSingleVolumeResultReviewAuthorityV1, decision: ExternalSingleVolumeDecisionV1`).
  - `ExternalResultReviewSource = ExternalResultReviewSourceV1 | ExternalSingleVolumeResultReviewSourceV1`; `AnyExternalResultReviewReceipt = ExternalResultReviewReceiptV1 | ExternalSingleVolumeResultReviewReceiptV1`. Every store/port method that took or returned the relative types now takes/returns these unions (`review`, `get_scoped`, `get_for_report`, `list_scoped`, `resolve_historical`, `verify_historical`, `local_source_matches`, `preflight_current_source`, `local_source_is_current`, listener type).
  - `CoreExternalResultReviewSourceAdapter(*, volume_store, decisions, historical_use_authority, coordinator, single_volume_store: ExternalSingleVolumeStore | None = None, single_historical_use_authority: ExternalSingleVolumeHistoricalUseAuthorityPort | None = None)`; both single arguments must be given together (else `ValueError`); `uses_single_volume_store(store) -> bool`.

- [x] **Step 1: Failing tests** (build the relative loop graph with `external_product_loop_fixture` plus the SV-3a single fixture `tests/contract/external_single_volume_fixture.py`; give the single authority port a `resolve_historical_for_use` that mirrors `resolve_historical`):
  1. `test_single_report_review_is_durable_and_idempotent` — report a single measurement; `reviews.review(...)` returns a sealed `ExternalSingleVolumeResultReviewReceiptV1`, `review_ref` starts with `err-v1-`; a second call returns the same receipt; the journal line has `"kind": "external-single-volume-result-reviewed"`.
  2. `test_relative_review_bytes_are_unchanged` — record a relative review with a store that has the single family configured and one without; the two journal files are byte-identical.
  3. `test_single_review_replays_and_verifies_historically` — close, reopen; `get_for_report` returns the same receipt; `verify_historical(review_ref, review_digest, evaluated_at=reviewed_at)` returns it; revoking the single execution before `reviewed_at` makes it `None`.
  4. `test_single_review_is_closed_without_authority` — actor not in `authorized_actor_ids`, expired authority, missing decision, or no single store configured → `RuntimeError("EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE")`.
  5. `test_replay_rejects_kind_and_receipt_mismatch` — a journal line with kind `external-single-volume-result-reviewed` carrying a relative receipt (with a valid `eventDigest`) raises `ExternalResultReviewRecoveryError`, and vice versa.
  6. `test_adapter_requires_both_single_arguments` — `ValueError`.
- [x] **Step 2: Run** `uv run --locked pytest tests/contract/test_external_single_volume_result_reviews.py -q` → FAIL.
- [x] **Step 3: Implement.**
  - Store: `_KIND_BY_CONTRACT = {"external-result-review-receipt.v1": "external-result-reviewed", "external-single-volume-result-review-receipt.v1": "external-single-volume-result-reviewed"}`; `_apply` accepts both kinds and parses with `parse_external_result_review_receipt`, then requires `_KIND_BY_CONTRACT[receipt.contract_version] == raw["kind"]`; `_receipt` builds the class matching the source type (single uses `SINGLE_VOLUME_REVIEW_FACTUAL_LIMITATIONS`); `review` writes the kind for the receipt's contract and the wire dict from the matching `*_wire_dict` helper. Relative path untouched byte-for-byte.
  - Adapter: `_is_single(report_ref) = self._single_volumes is not None and report_ref.startswith("external-single-volume-report-")`. Single `_join` uses `decisions.resolve_historical_single_volume(...)` and `ExternalSingleVolumeResultReviewAuthorityV1.model_validate(authority.snapshot_payload()).sealed()`; `_history_permits` uses the single history port; `is_current` rebuilds `ExternalSingleVolumeExecutionAuthority` from the receipt authority the same way `_execution_authority` does for relative, and guards through `single_volume_store.guard_current_report_ref`. A single-typed source reaching the relative branch (or the reverse) returns `None`/`False`.
  - Graph: pass `single_volume_store=external_single_volume.store` and `single_historical_use_authority=runtime.single_execution` when `external_single_volume is not None`.
- [x] **Step 4: Run** Step 2 plus `uv run --locked pytest tests/contract/test_external_result_review_proposals.py tests/contract/test_external_result_workflow_api.py tests/contract/test_external_quantitative_authority.py tests/contract/test_api_contract_sync.py -q`; `uv run --locked mypy services/core tests/contract/test_external_single_volume_result_reviews.py`.
- [x] **Step 5: Commit** `feat(core): family-aware result review store and source (SV-3b)`

---

### Task 3: Proposals, projection, review route and integrated lifecycle

**Files:**
- Modify: `services/core/src/ksi_core/domains/external/workflow/external_reobservation_proposals.py`
- Modify: `services/core/src/ksi_core/domains/external/workflow/external_result_workflow_api.py`
- Modify: `contracts/api/openapi-core.yaml`
- Test: `tests/contract/test_external_single_volume_result_reviews.py` (extend), `tests/contract/test_external_result_single_volume_projection.py` (extend), `tests/contract/test_external_result_briefings.py` (extend), `tests/contract/test_external_quantitative_production_flow.py` (extend), `tests/contract/test_api_contract_sync.py`

**Interfaces:**
- Consumes: Task 2 unions and store.
- Produces:
  - Proposal store/service/authority port accept `AnyExternalResultReviewReceipt` (annotations; `ExternalReobservationProposalStore.create` re-validates with `parse_external_result_review_receipt(review_wire)`).
  - `ExternalSingleVolumeReportView(request, report, execution_policy, review: ExternalSingleVolumeResultReviewReceiptV1 | None = None, proposals: list[ExternalReobservationProposalView] = [])` (additive fields).
  - `ExternalResultReviewView.review: ExternalResultReviewReceiptV1 | ExternalSingleVolumeResultReviewReceiptV1` (discriminated on `contractVersion`).
  - `POST /v1/external-single-volume-reports/{report_ref}/reviews` → `ExternalResultReviewView` 201; errors identical to the relative route (`HUMAN_REVIEW_REQUIRED` 403, `EXTERNAL_WORKFLOW_CLOSED` 409, `EXTERNAL_RESULT_REVIEW_SOURCE_UNAVAILABLE` 409, `EXTERNAL_RESULT_REVIEW_STORAGE_UNAVAILABLE` 503, `INVALID_EXTERNAL_RESULT_REVIEW_INTENT` 422). One private `_review_report(report_ref, principal, resolver)` function serves both routes (no copied handler).
  - Single summaries carry `review_ref/review_digest/reviewed_at/proposal_count/approved_proposal_count` computed by one shared `_review_join(report_ref, request, report, authority, organization_id)` helper used by both families.
  - Both exact report GET routes return 404 (their existing detail) when `_provenance_intact(...)` is false.

- [x] **Step 1: Failing tests**
  1. Proposal service on a single review: create proposal for the report's WorkArea → sealed proposal with `report_ref` = single ref and `zone_digest` = single zone definition digest; approve → successor work order with an external reobservation binding; `verify_external_reobservation_graph` passes after restart; a proposal for another WorkArea → `EXTERNAL_REOBSERVATION_TARGET_NOT_REPORT_ZONE`.
  2. Projection: after review + proposal + approval, the single summary has `review_ref` set, `proposal_count == 1`, `approved_proposal_count == 1`; `for_work_order(successor)` projects the single result through the binding.
  3. HTTP: single review route 201 for an operator, 403 for a service principal, 404/409 for another org's ref; the relative review route with a single ref still returns the same non-2xx it returns today (pin the status); `GET /v1/external-result-reviews/{ref}` returns the single receipt with `contractVersion` `external-single-volume-result-review-receipt.v1`; `GET /v1/external-single-volume-reports/{ref}` includes `review` and `proposals`; `POST /v1/external-reobservation-proposals` with a single `reportRef` returns 201.
  4. Provenance: with a record whose retained report digest is tampered (monkeypatch the store's resolved triple as `test_external_result_single_volume_projection.py` does for unavailable authority), both exact report routes return 404.
  5. Briefing: a single review produces a `REVIEWED` briefing whose `decision_prompt` is "재관측이 필요하면 제안을 만들고 승인하세요." and whose first citation is the single report.
  6. Production flow (`test_signed_provider_drives_complete_external_relative_volume_lifecycle`, after the single report is accepted): review over HTTP → proposal → approval → successor work order; after restart the single review and proposal still resolve and `verify_external_reobservation_graph` passes.
  7. `test_api_contract_sync.py` passes with the new path and schema changes.
- [x] **Step 2: Run** `uv run --locked pytest tests/contract/test_external_single_volume_result_reviews.py tests/contract/test_external_result_single_volume_projection.py tests/contract/test_external_result_briefings.py -q` → FAIL.
- [x] **Step 3: Implement** (Interfaces above). OpenAPI: add the review path, make `ExternalResultReviewView.review` a `oneOf` with discriminator `contractVersion`, add `ExternalSingleVolumeResultReviewReceiptV1` and its authority schema, extend `ExternalSingleVolumeReportView`.
- [x] **Step 4: Run** Step 2 plus `uv run --locked pytest tests/contract/test_external_quantitative_production_flow.py -q` (timeout 600000 ms), `uv run --locked pytest tests/contract -q -k "reobservation or result_review or workflow_api or contract_sync or workspace"`; ruff; mypy on changed files.
- [x] **Step 5: Commit** `feat(core): single-volume review, proposal and approval lifecycle (SV-3b)`

---

### Task 4: Team share for single-volume results

**Files:**
- Create: `services/core/src/ksi_core/domains/sites/external_report_resolver.py`
- Modify: `services/core/src/ksi_core/domains/sites/work_inbox.py` (router, ~line 666)
- Modify: `services/core/src/ksi_core/composition/workspace_graph.py` (~line 58) and the caller that passes `external_relative_volume_store` into it (`composition/assembly.py`), plus the `uses_exact_dependencies(report_resolver=...)` call in `composition/routes/identity_work.py` (~line 78)
- Modify: `contracts/api/openapi-core.yaml`, `docs/audit/CORE_R1_MODULE_MIGRATION.json`
- Test: `tests/contract/test_organization_work_roster_and_inbox.py`; add the new POST path to `tests/contract/test_hostile_input_route_coverage.py`

**Interfaces:**
- Produces: `ExternalVolumeReportResolver(*, relative, single=None)` with `resolve_historical_report_ref(report_ref, *, organization_id, now=None)` dispatching on the single prefix (single only when `single` is set; otherwise relative, i.e. today's behavior); `uses(relative, single) -> bool`. `POST /v1/external-single-volume-reports/{report_ref}/shares` → `ExternalReportShare` 201 via the same `share_report` call as the relative route (one shared handler function).

- [x] **Step 1: Failing tests** — sharing a single report creates an inbox item for the recipient with `target.kind == "EXTERNAL_REPORT"`, `report_ref` = single ref and the report's `site_id`; replay keeps it; sharing another org's single ref → 404; the relative share route with a single ref keeps its current status (pin it); relative share journal bytes unchanged when the resolver is the composite (compare with a relative-only store).
- [x] **Step 2: Run** the work-inbox tests → FAIL.
- [x] **Step 3: Implement**; the workspace graph builds `ExternalVolumeReportResolver(relative=external_relative_volume_store, single=external_single_volume_store)` (the single store reaches the workspace graph as a new keyword argument, `None` when unconfigured).
- [x] **Step 4: Run** the work-inbox tests, `tests/contract/test_api_contract_sync.py`, `-k "workspace or inbox or assembly"`; ruff; mypy.
- [x] **Step 5: Commit** `feat(core): share single-volume results with teammates (SV-3b)`

---

### Task 5: Dashboard client, BFF and deep-link validation

**Files:**
- Modify: `apps/dashboard/src/lib/core-api/external-result-workflow.ts`, `src/lib/core-api/work-collaboration.ts`, `src/lib/core-api/types.ts` (only if review types live there)
- Create: `apps/dashboard/src/app/api/external-single-volume-reports/[reportRef]/reviews/route.ts`, `.../[reportRef]/shares/route.ts` (copy the relative routes' validation; use `isExternalSingleVolumeReportReference`)
- Modify: `apps/dashboard/src/app/api/external-reobservation-proposals/route.ts` (accept either report prefix, each with its exact `[0-9a-f]{32}` suffix)
- Modify: `apps/dashboard/src/app/field/work-orders/[workOrderId]/page.tsx` (~lines 75-100)
- Test: `apps/dashboard/test/external-single-volume-routes.test.ts` (extend), `test/external-result-workflow-route.test.ts` (proposal body), new `test/work-order-report-deep-link.test.tsx`

**Interfaces:**
- Produces (TS): `ExternalSingleVolumeResultReview` type (mirror of the Core receipt), `ExternalAnyResultReview = ExternalResultReview | ExternalSingleVolumeResultReview` discriminated on `contractVersion`; `reviewExternalSingleVolumeReport(reportRef)`; `shareExternalSingleVolumeReport(reportRef, recipientPrincipalId, idempotencyKey)`; `ExternalSingleVolumeReportView` gains `review` and `proposals`.
- Deep link: accepted when `reportRef` matches either prefix, the family's exact report has `request.currentWorkOrderId === workOrderId` and `report.reportId === reportRef`, and `getSiteExternalRelativeVolumeReport(siteId, reportRef)` is `AVAILABLE` with the same `reportDigest`. The notice copy for failures is unchanged.

- [x] **Step 1: Failing vitest** — both new BFF routes (also add the new POST routes to the hostile-input coverage list in Task 3/4 Core tests only; the dashboard has no such list) (cross-site 403, missing key 400, bad ref 404, forwarding, Core error passthrough); proposal BFF accepts a single ref and still rejects other prefixes; deep link: a relative report that is not the site-latest is accepted; a single report is accepted; a digest mismatch is rejected with the existing notice.
- [x] **Step 2: Run** `cd apps/dashboard && npx vitest run test/external-single-volume-routes.test.ts test/external-result-workflow-route.test.ts` (+ deep-link test) → FAIL.
- [x] **Step 3: Implement.**
- [x] **Step 4: Run** Step 2, `npx tsc --noEmit`, `npm run lint`; from repo root `uv run --locked pytest tests/contract/test_api_contract_sync.py -q`.
- [x] **Step 5: Commit** `feat(dashboard): single-volume review and share client, exact deep links (SV-3b)`

---

### Task 6: Extract the shared review/proposal/approval component (refactor only)

**Files:**
- Create: `apps/dashboard/src/components/external-results/ExternalResultReviewActions.tsx`
- Modify: `apps/dashboard/src/app/field/ExternalResultWorkflowPanel.tsx` (review, proposal and approval state + handlers ~lines 640-1080, rendering ~1120-1145)
- Test: existing `test/external-result-workflow-panel.test.tsx`, `test/external-result-workflow-correction.test.tsx` must pass **unchanged**; add `test/external-result-review-actions.test.tsx` for the component in isolation

**Interfaces:**
- Produces: `ExternalResultReviewActions` props: `{ reportRef: string; reviewPath: string; review: ExternalAnyResultReview | null; proposals: ExternalReobservationProposalView[]; targetLabel: string; newIntentAllowed: boolean; hasReviewPermission: boolean; canApprovePermission: boolean; onReviewed(review): void; onProposal(view): void; onApproved(view): void; renderReviewDetail?(review): ReactNode }`. It owns the frozen idempotency attempts, busy state, abort handling and all existing Korean strings for these three actions.

- [x] **Step 1:** Write the component test (review click posts to `reviewPath` with a frozen key reused on retry; proposal posts `{ reportRef, targetWorkAreaIds, reason }`; approval posts `{ proposalRef, expectedVersion }`; `targetLabel` is rendered).
- [x] **Step 2:** Run it → FAIL.
- [x] **Step 3:** Move the logic without behavior change; the relative panel passes `reviewPath = /api/external-relative-volume-reports/{ref}/reviews`, `targetLabel = "대상: 이 비교에 사용한 작업구역"`, `renderReviewDetail = ReviewAuditDetail`.
- [x] **Step 4:** Run the new test and the two existing panel test files (unchanged, must pass), `npx tsc --noEmit`, `npm run lint`.
- [x] **Step 5: Commit** `refactor(dashboard): shared external result review actions (SV-3b)`

---

### Task 7: Single-volume review, proposal, approval and share in the UI

**Files:**
- Modify: `apps/dashboard/src/app/field/ExternalResultWorkflowPanel.tsx` (`SingleVolumeWorkflow`)
- Modify: `apps/dashboard/src/components/external-results/SingleVolumeResult.tsx` (review audit detail for single, if the detail lives there)
- Modify: `apps/dashboard/src/app/sites/[siteId]/observations/[reportRef]/ExternalReportFollowupTrace.tsx`, `.../[reportRef]/page.tsx`
- Modify: `apps/dashboard/src/components/external-results/TeamReportShare.tsx` (share path by report prefix)
- Test: `test/external-result-workflow-panel.test.tsx`, `test/external-report-followup-trace.test.tsx`, `test/team-report-share.test.tsx`, `test/external-observation-history-kinds.test.tsx`

**Interfaces:**
- Consumes: Task 5 client/BFF, Task 6 component.

- [x] **Step 1: Failing vitest**
  1. Workflow panel: a SUCCEEDED single report shows `ExternalResultReviewActions` with `reviewPath = /api/external-single-volume-reports/{ref}/reviews` and "대상: 이 측정에 사용한 작업구역"; after review the proposal and approval path works and "후속 작업 보기" links to the successor; "단일 시점 결과 검토는 준비 중입니다." is absent everywhere (`grep` in the test via rendered text).
  2. Single review audit detail shows the target capture window and `targetRmseM` (or "미기록"), never baseline fields.
  3. Followup trace: for a single result with a review and an approved proposal, the review/proposal/successor steps render with the existing copy.
  4. Detail page: `TeamReportShare` renders for a single result and posts to `/api/external-single-volume-reports/{ref}/shares`; the share receipt check accepts the single ref.
- [x] **Step 2: Run** those test files → FAIL.
- [x] **Step 3: Implement.** Remove the "준비 중" constant and every branch that rendered it.
- [x] **Step 4: Full dashboard gates**: `npx tsc --noEmit && npm run lint && npm test && npm run build` (read each exit code).
- [x] **Step 5: Commit** `feat(dashboard): single-volume review, proposal and share (SV-3b)`

---

### Task 8: Gates, evidence and close-out

- [x] `uv run --locked ruff check .` → clean; `uv run --locked mypy packages services tests tools` → Success.
- [x] Full pytest in bounded chunks (as in SV-3a: `tests/contract` in 30-file chunks, `packages services`, remaining `tests/*` dirs); record passed/skipped/failed per chunk and the aggregate; 0 failed.
- [x] Dashboard gates from Task 7 Step 4 on the final commit.
- [x] Live check: not run — no local deployment has a single execution template with a sealed DSM and attested checkpoint evidence; recorded in the Execution outcome below (rehearsal belongs to SV-4).
- [x] Append "Execution outcome" to this plan; update `.opencode/working-state.md` (Next = SV-4). `docs/superpowers/product-state.md` is not touched.
- [ ] Merge/push only with owner approval.

## Self-review notes

- Spec §8 review/proposal coverage: review contract ✔ (T1), store/source ✔ (T2), proposal/approval + projection + route ✔ (T3), dashboard review/proposal ✔ (T5-T7). Shares (spec §8 BFF `external-single-volume-reports/{ref}` + shares) ✔ (T4, T5, T7). SV-3a follow-ups: regression that relative mutation routes reject single refs ✔ (T3, T4); provenance on exact routes ✔ (T3); deep link ✔ (T5); single briefing prompt now truthful because review exists ✔ (T3 test 5); neutral type names — covered by the `ExternalAnyResultReview` union (T5); remaining hygiene items stay in the SV-3a follow-up list.
- Names used across tasks: `ExternalSingleVolumeResultReviewReceiptV1`, `ExternalSingleVolumeResultReviewAuthorityV1`, `parse_external_result_review_receipt`, `SINGLE_VOLUME_REVIEW_FACTUAL_LIMITATIONS`, `ExternalSingleVolumeResultReviewSourceV1`, `AnyExternalResultReviewReceipt`, `ExternalSingleVolumeHistoricalUseAuthorityPort`, `resolve_historical_for_use`, `ExternalVolumeReportResolver`, `ExternalResultReviewActions`, `ExternalAnyResultReview`, `reviewExternalSingleVolumeReport`, `shareExternalSingleVolumeReport`.

---

## Execution outcome (2026-09-18, OpenCode Build)

Continuation note: Tasks 1-5 were executed and committed by a previous Claude session on this branch; its ledger checkboxes were never updated. This session resumed at the interrupted Task 6 (uncommitted shared-component extraction), completed Tasks 6-8, and independently re-verified the branch with fresh test-runner and reviewer sessions.

Base: main `9cb94f6` (this plan). Branch `feat/single-volume-sv3b`, final HEAD `b88edd4`; not pushed. Merge/push awaits owner approval.

Commits:
- Task 1 `3a1b12e` receipt contract; Task 2 `924033a` family-aware store/source; Task 3 `c60205f` + `99b620d`; Task 4 `a021d41` + `472bf8e`; Task 5 `4048ea8` (previous session).
- Task 6 `67c7315` shared review-actions component (resumed from the interrupted state).
- Task 7 `42a49ce` single-volume review/proposal/approval/share UI.
- Task 7 review fixes `b8745ac` (blocker: single detail scope binding; major: reload abort/selection guard).
- Task 8 `b88edd4` mypy test annotation.

Evidence (independent runs, real exit codes):
- @67c7315: targeted vitest 3 files 40/40; tsc 0; lint 0. Reviewer: no blocker; accepted minors (generic component interface, render-phase proposal sync).
- @42a49ce: targeted 50/50; full dashboard 118 files 889/889; tsc 0; lint 0; next build 0. Reviewer found the blocker + major above.
- @b8745ac: targeted 44/44; full dashboard 896/896; tsc 0; lint 0; build 0; reviewer confirmed both findings CONFIRMED-FIXED.
- Backend @b8745ac + @b88edd4: ruff 0; mypy Success 819 files (b88edd4 repaired the one error mypy found at b8745ac, `tests/contract/test_external_result_read_projection.py:68`); contract combined 6029 passed / 112 skipped / 0 failed (K1-K7 @b8745ac + K8-K12 @b88edd4); tests non-contract 575 / 9 skipped; packages+services 193 / 0; this-run aggregate 2814 passed / 11 skipped / 0 failed.
- Dashboard final gates @b8745ac: tsc 0, lint 0, 896/896, build 0 (27 static pages). `b88edd4` changes only a Python test file, so the dashboard tree is identical to that verified revision.

Decisions:
- Task 6 interface drift kept: `targetWorkAreaId`, `reviewReason`, generic `TReview`, AbortSignal on approval — the single mount needs family wording and abort-aware navigation.
- Single `reviewReason` is "단일 시점 결과 검토 기록은 노트북 이상의 화면에서 진행합니다." — deliberate exception to "all other strings are the existing relative strings" because "비교 결과" is false for a one-epoch measurement; routed to the SV-4 copy review.
- Commit trailer is `Co-Authored-By: Claude Opus 5` only; no Claude-Session link (owner decision).
- K1-K7 contract chunks were not re-run at `b88edd4`; the only changed file belongs to K11, which was re-run.

Boundaries (not verified):
- No visual approval: the delegated design fidelity review returned BLOCKED-no-render (no preview/browser permission, no local single-volume data). Source-level hierarchy deltas (single report detail `h4` vs relative `h3`; summary CTA `btn` vs `btn-primary`) remain unreviewed in pixels. Escalated to the owner.
- Live check not run: no local deployment has a single execution template with a sealed DSM and attested checkpoint evidence; the end-to-end rehearsal belongs to SV-4.
- No real S3/MinIO, container worker or HIL run.

Follow-ups (not blocking; candidates for the product-state backlog at SV-4 close):
- Low: `selectedRefRef`/`selectionGenerationRef` mirrors update one render after `selectRequest`; a reload invoked in the same tick is dropped (fail-closed, retry needed). Prefer a synchronous ref update.
- Test gaps: unmount-during-reload, same-ref reselect reload race, REPORT_BINDING_CHANGED error UI, `reportId` mismatch on the detail page, single share idempotency/unresolved retry, single approval abort.
- SV-4 copy review list: single reviewReason; "대상: 이 측정에 사용한 작업구역"; "대상 촬영 …" / "대상 독립 검사점 RMSE:" / "미기록"; detail subcopy "한 시점 관측으로 측정한 보관 체적 결과입니다."; summary/history review-status copy; `미기록` vs `기록 없음`; the hierarchy deltas above.
