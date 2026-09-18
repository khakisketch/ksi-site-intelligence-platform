# AX-4 External Decisions on Home Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** External volume results that wait for a person (review or approval) become a Home "확인이 필요한 현장" source, computed by Core from its ledgers.

**Architecture:** A read-only `pending_decisions` filter on the existing `ExternalResultReadProjector` (no journal) behind `GET /v1/external-decisions/pending`. The dashboard adds an `EXTERNAL_DECISION` attention kind ranked after unattended events and before WorkOrder decisions.

**Tech Stack:** Python 3 / FastAPI / pydantic (Core), Next.js + vitest (dashboard).

**Spec:** `docs/superpowers/specs/2026-09-17-ax-product-loop-design.md` §9; ADR-KSI-025 D1 (amended 2026-09-18).

## Global Constraints

- Pending is computed by Core only: `AWAITING_REVIEW` = `measurementStatus == "SUCCEEDED"`, metrics present, no review; `AWAITING_APPROVAL` = `proposalCount > approvedProposalCount`.
- One item per site; review before approval; then `reportedAt` ascending, then report ref.
- Rows with `HISTORICAL_SOURCE_UNAVAILABLE` are skipped, never guessed.
- `SITES_READ`, organization-scoped (INV-060). No new journal, no mutation.
- Home: one card per site, no-repeat rule unchanged; a failed pending call is stated, never shown as "nothing to decide".
- Volume text uses `formatNetVolumeM3` / `formatVolumeM3` (no `-0 m³`).

---

## File structure

- Modify `services/core/src/ksi_core/domains/external/workflow/external_result_projection_models.py` — two DTOs.
- Modify `services/core/src/ksi_core/domains/external/workflow/external_result_workflow_api.py` — `pending_decisions` on the projector and the route.
- Modify `contracts/api/openapi-core.yaml` — path and two schemas.
- Create `tests/contract/test_external_pending_decisions.py`.
- Create `apps/dashboard/src/lib/core-api/external-decisions.ts` — client and type.
- Modify `apps/dashboard/src/lib/home-operations.ts` — new attention kind and ranking.
- Modify `apps/dashboard/src/app/page.tsx` — fetch, card mapping, unavailable notice.
- Modify `apps/dashboard/test/home-operations.test.ts`.

### Task 1: Core pending projection

**Files:** projection models, `external_result_workflow_api.py` (projector), test file.

**Interfaces — Produces:**

```python
class ExternalPendingDecisionItem(CamelModel):
    site_id: str
    report_ref: str
    kind: ExternalResultKind
    stage: Literal["AWAITING_REVIEW", "AWAITING_APPROVAL"]
    reported_at: datetime
    net_m3: float
    uncertainty_m3: float | None
    work_area_id: str

class ExternalPendingDecisionsView(CamelModel):
    items: list[ExternalPendingDecisionItem]

ExternalResultReadProjector.pending_decisions(self, *, organization_id: str) -> ExternalPendingDecisionsView
```

- [ ] **Step 1: Write failing tests** in `tests/contract/test_external_pending_decisions.py`, reusing `_Harness`/`harness`, `_record_single`, `_record_second_relative` from `test_external_result_single_volume_projection.py` and `_review_and_approve` from `test_external_result_read_projection.py`:

```python
def test_reported_result_waits_for_review_then_leaves_after_review(harness):
    report = record_measurement(harness.graph)
    pending = harness.projector().pending_decisions(organization_id="org-a").items
    assert [(i.site_id, i.report_ref, i.stage) for i in pending] == [("site-a", report.report_id, "AWAITING_REVIEW")]
    assert pending[0].net_m3 == 4.0 and pending[0].kind == "EXTERNAL_RELATIVE_VOLUME"
    harness.graph.service.reviews.review(organization_id="org-a", report_ref=report.report_id, principal=_principal(), evaluated_at=_NOW)
    assert harness.projector().pending_decisions(organization_id="org-a").items == []

def test_unapproved_proposal_waits_for_approval_and_leaves_after_approval(harness): ...
    # review, create proposal -> AWAITING_APPROVAL; approve -> []

def test_one_item_per_site_review_before_approval_oldest_first(harness): ...
    # relative reviewed+proposed (approval wait) + single unreviewed -> single AWAITING_REVIEW chosen

def test_other_organization_sees_nothing(harness):
    record_measurement(harness.graph)
    assert harness.projector().pending_decisions(organization_id="org-b").items == []

def test_unavailable_historical_source_is_skipped_not_guessed(harness): ...
    # reuse the historical-unavailable setup from test_external_result_read_projection.py:178
```

Write the elided bodies out fully from the referenced helpers.

- [ ] **Step 2: Run** `uv run pytest -q tests/contract/test_external_pending_decisions.py` — expect `AttributeError: pending_decisions`.
- [ ] **Step 3: Implement** in the projector:

```python
def pending_decisions(self, *, organization_id: str) -> ExternalPendingDecisionsView:
    chosen: list[tuple[int, datetime, str, ExternalPendingDecisionItem]] = []
    for site in self._workflow.sites.list_scoped(organization_id):
        best = None
        for report_ref in self._report_index(site.site_id, organization_id=organization_id):
            projection = self._for_report_ref(report_ref, organization_id=organization_id)
            result = projection.result
            if projection.state is not ExternalResultProjectionState.AVAILABLE or result is None or result.metrics is None:
                continue
            if result.measurement_status == "SUCCEEDED" and result.review_ref is None:
                rank, stage = 0, "AWAITING_REVIEW"
            elif result.proposal_count > result.approved_proposal_count:
                rank, stage = 1, "AWAITING_APPROVAL"
            else:
                continue
            key = (rank, result.reported_at, report_ref)
            if best is None or key < best[:3]:
                best = (*key, ExternalPendingDecisionItem(site_id=site.site_id, report_ref=report_ref, kind=result.kind, stage=stage, reported_at=result.reported_at, net_m3=result.metrics.net_m3, uncertainty_m3=result.metrics.uncertainty_m3, work_area_id=result.work_area_id))
        if best is not None:
            chosen.append(best)
    return ExternalPendingDecisionsView(items=[entry[3] for entry in sorted(chosen, key=lambda e: e[:3])])
```

- [ ] **Step 4: Run** the test file — PASS.
- [ ] **Step 5: Commit** `feat(core): project external results awaiting a human decision (AX-4)`.

### Task 2: Core route and OpenAPI

**Files:** `external_result_workflow_api.py` (router), `contracts/api/openapi-core.yaml`, test file.

**Interfaces — Consumes:** `pending_decisions`. **Produces:** `GET /v1/external-decisions/pending` → `ExternalPendingDecisionsView` (camelCase JSON: `siteId, reportRef, kind, stage, reportedAt, netM3, uncertaintyM3, workAreaId`).

- [ ] **Step 1: Failing test** using `_http_client(harness)` from the single-volume projection test:

```python
def test_pending_route_is_authenticated_and_organization_scoped(harness):
    report = record_measurement(harness.graph)
    with _http_client(harness) as client:
        assert client.get("/v1/external-decisions/pending").status_code == 401
        mine = client.get("/v1/external-decisions/pending", headers={"Authorization": f"Bearer {_TOKEN}"})
        assert mine.status_code == 200, mine.text
        assert [(i["siteId"], i["reportRef"], i["stage"]) for i in mine.json()["items"]] == [("site-a", report.report_id, "AWAITING_REVIEW")]
        other = client.get("/v1/external-decisions/pending", headers={"Authorization": "Bearer other-org-fixture"})
        assert other.json() == {"items": []}
```

- [ ] **Step 2: Run** — expect 404.
- [ ] **Step 3: Implement** the route inside `build_external_result_workflow_router`:

```python
@router.get("/v1/external-decisions/pending", response_model=ExternalPendingDecisionsView)
def pending_decisions(principal: Principal = read_dependency) -> ExternalPendingDecisionsView:
    return projector.pending_decisions(organization_id=principal.organization_id)
```

  Document the path in `openapi-core.yaml` next to `/v1/sites/{site_id}/external-volume-reports` (tag `external-result-workflow`, `security: bearerAuth`, 200 → `$ref: '#/components/schemas/ExternalPendingDecisionsView'`) and add both component schemas with exactly the implemented fields.
- [ ] **Step 4: Run** the new test file plus `tests/contract/test_api_contract_sync.py` — PASS.
- [ ] **Step 5: Commit** `feat(core): serve pending external decisions for Home (AX-4)`.

### Task 3: Dashboard client and attention ranking

**Files:** create `src/lib/core-api/external-decisions.ts`; modify `src/lib/home-operations.ts`; test `test/home-operations.test.ts`.

**Interfaces — Produces:**

```ts
export interface ExternalPendingDecision { siteId: string; reportRef: string; kind: "EXTERNAL_RELATIVE_VOLUME" | "EXTERNAL_SINGLE_VOLUME"; stage: "AWAITING_REVIEW" | "AWAITING_APPROVAL"; reportedAt: string; netM3: number; uncertaintyM3: number | null; workAreaId: string }
export function listExternalPendingDecisions(): Promise<{ items: ExternalPendingDecision[] }>
// HomeAttentionSource gains:
| { kind: "EXTERNAL_DECISION"; key: string; siteId: string; observedAt: string; decision: ExternalPendingDecision }
// selectHomeAttentionSources input gains: externalDecisions?: readonly ExternalPendingDecision[]
```

- [ ] **Step 1: Failing tests**: (a) an unattended event outranks an external decision for another site, and the decision outranks a `REVIEW_READY` WorkOrder; (b) a site with both an external decision and a WorkOrder decision yields one `EXTERNAL_DECISION` card; (c) no `externalDecisions` keeps today's output unchanged.
- [ ] **Step 2: Run** `npx vitest run test/home-operations.test.ts` — FAIL.
- [ ] **Step 3: Implement**: the client via `coreFetch<{ items: ExternalPendingDecision[] }>("/v1/external-decisions/pending")`; in `selectHomeAttentionSources` insert `...(input.externalDecisions ?? []).map((decision) => ({ kind: "EXTERNAL_DECISION" as const, key: `external-decision:${decision.reportRef}`, siteId: decision.siteId, observedAt: decision.reportedAt, decision }))` between the event and WorkOrder candidates (keep Core order).
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat(dashboard): rank external decisions in Home attention (AX-4)`.

### Task 4: Home card, failure notice, visual check

**Files:** `src/app/page.tsx`; test `test/home-operations.test.ts` or a new pure mapping test if the mapper is exported.

- [ ] **Step 1: Failing test** for the card mapping (export the mapper if needed): label `검토 대기` / `승인 대기`; title `순 체적 +12.5 m³ · ±3 m³` or `… · 오차한계 미산출`; href `/sites/{siteId}/observations/{reportRef}`; actionLabel `결과와 근거 보기`; zero net renders `0 m³`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**: add `settle(listExternalPendingDecisions())` to the Home `Promise.all`; pass `externalDecisions`; map `EXTERNAL_DECISION` cards; when the call fails show `외부 결과의 결정 대기 여부를 불러오지 못했습니다. 확인할 결과가 없다는 뜻이 아닙니다.` and mark the portfolio incomplete like `operationsUnavailable`.
- [ ] **Step 4: Run** full dashboard gate: `npx vitest run`, `npx tsc --noEmit`, `npm run lint`, `npm run build`; then a local preview capture of Home cards (desktop/mobile) with fixture data.
- [ ] **Step 5: Commit** `feat(dashboard): show external decision cards on Home (AX-4)`.

### Task 5: Evidence and close-out

- [ ] Run `uv run ruff check .`, `uv run mypy` (repo config), `uv run pytest -q tests/contract` and the dashboard gate; record results in the EXT-VAL ledger with the unverified boundary (no live-stack Home pass unless the stack is up).
- [ ] Commit `docs(plan): record AX-4 execution evidence`.
