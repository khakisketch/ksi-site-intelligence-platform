# SINGLE_VOLUME SV-3a Implementation Plan — read side, AX briefing, dashboard

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reported SINGLE_VOLUME measurement is visible end to end without any new page: Core projects it (work order, site latest, merged site history, exact report view, citation), the site briefing states the pile volume with its ± and base roughness, and the dashboard can request a single-volume decision, issue the measurement, watch it, and show the result with a kind badge.

**Architecture:** `ExternalResultReadProjector` gains an optional second family (`ExternalSingleVolumeStore`) and dispatches by report-ref prefix. Both ledgers expose the same newest-first sort key so the merged history is a pure merge and relative-only output stays byte-identical. The briefing projector gains one deterministic single-volume sentence branch. The dashboard adds BFF routes and panel branches beside the relative ones.

**Tech Stack:** Python 3.12, pydantic v2, FastAPI, `uv run --locked`; Next.js (App Router), TypeScript, vitest.

**Spec:** `docs/superpowers/specs/2026-09-17-single-volume-design.md` §8 (plus the amendment below). Earlier plans: `2026-09-17-single-volume-sv1.md`, `2026-09-17-single-volume-sv2.md`.

## Spec amendment (decided during SV-3 planning, 2026-09-17)

1. **Review and reobservation are NOT family-neutral today — split SV-3.** Spec §8 says the
   review and reobservation contracts are unchanged because "they bind a report ref and digest".
   That is true for `ExternalReobservationProposalV1` only. `ExternalResultReviewReceiptV1`
   embeds `ExternalRelativeVolumeRequestV1`, `ExternalRelativeVolumeReportV1`,
   `ExternalResultReviewAuthorityV1` (baseline + current bindings, relative execution policy) and
   `ExternalPairUseDecisionV1` (`use == "RELATIVE_VOLUME"` is validated). `ExternalResultReviewStore`,
   `ExternalResultReviewSourceV1`, `CoreExternalResultReviewSourceAdapter` and the proposal service
   read those fields directly. A single-volume review therefore needs a new sibling receipt contract
   with its own digest domain; widening the existing receipt would change sealed relative digests.
   - **SV-3a (this plan):** read side, briefing and dashboard. Single results show "검토 기능 준비 중"
     instead of a review button; no review/proposal/share mutation accepts a single report ref.
   - **SV-3b (next plan, `2026-09-17-single-volume-sv3b.md`, written after SV-3a closes):**
     `ExternalSingleVolumeResultReviewReceiptV1` + authority, family-tagged review journal events
     (relative events stay byte-identical), a family-dispatching review source adapter, proposal
     service reading family-neutral accessors, review/share routes and dashboard review path.
2. **Summary `kind` values keep the existing wire value.** The view already emits
   `kind: "EXTERNAL_RELATIVE_VOLUME"`. The new value is `"EXTERNAL_SINGLE_VOLUME"` (not the spec's
   `"RELATIVE_VOLUME" | "SINGLE_VOLUME"`).
3. **One merged site history route instead of a single-only one.** New
   `GET /v1/sites/{site_id}/external-volume-reports` returns both families. The existing
   `GET /v1/sites/{site_id}/external-relative-volume-reports` keeps returning relative results only
   (its name is a contract). The spec's BFF `sites/{id}/external-single-volume-reports` is replaced
   by `sites/{id}/external-volume-reports`. Site latest (`for_site`, workspace) uses the merged order.

## Global Constraints

- Relative-volume journals, report ids, contract models and sealed digests stay byte-identical. Existing route responses change only additively (the four new nullable metric keys); no existing key changes value or disappears. Every existing test under `tests/contract/test_external_result_*`, `test_external_relative_volumes.py`, `test_site_workspace*` must pass unchanged.
- Single report ref prefix: `external-single-volume-report-`. Relative: `external-relative-volume-report-`. Dispatch only on these exact prefixes; anything else resolves as the relative family (current behavior).
- Summary kind literals: `"EXTERNAL_RELATIVE_VOLUME"`, `"EXTERNAL_SINGLE_VOLUME"`.
- Citation for a single result: `object_type="EXTERNAL_SINGLE_VOLUME_REPORT"`, label `"{site_name} 외부 단일 시점 체적 결과"`, `source_path="/v1/external-single-volume-reports/{quote(ref)}"`, citation id prefix `external-single-volume-report:`.
- Briefing sentence (single): `"{zone} 적치물 체적 {fill} (±{uncertainty}, 기저면 거칠기 {roughness} m)."` with `fill`/`uncertainty` formatted by the existing `_m3`, roughness `f"{value:.2f}"`; when `uncertainty_m3 is None` the parenthesis reads `(불확도 미산정, 기저면 거칠기 {roughness} m)`. The product never shows a single volume without its ± or the explicit "미산정".
- Single results never enter the relative net-change delta (`_previous_net` filters by kind).
- No new dashboard page. No numeric authority in the dashboard: it displays Core values only.
- Gates per task: targeted pytest / vitest. Before closing: `uv run --locked ruff check .`, `uv run --locked mypy packages services tests tools`, full pytest in bounded chunks (read real exit codes), dashboard `npx tsc --noEmit`, `npm run lint`, `npm test`, `npm run build`.
- New Core modules (if any) go into `docs/audit/CORE_R1_MODULE_MIGRATION.json` as `T3_NEW_MODULE`. This plan adds none.
- Commits end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## File map

| File | Change |
|---|---|
| `services/core/src/ksi_core/domains/external/quantity/external_relative_volumes.py` | `ExternalVolumeLedger.report_index_for_site` (new); `report_refs_for_site` derived from it |
| `services/core/src/ksi_core/domains/external/workflow/external_result_projection_models.py` | `kind` literal, nullable baseline fields, optional single metric fields |
| `services/core/src/ksi_core/domains/external/workflow/external_result_workflow_api.py` | projector single family; merged history; `kinds` filter; single report route; merged history route |
| `services/core/src/ksi_core/composition/external_graph.py`, `composition/routes/external.py`, `composition/assembly.py` | pass the single store to the projector/router/briefing |
| `services/core/src/ksi_core/domains/external/workflow/external_result_briefings.py` | single sentence branch; bind single report listener; kind filter in `_previous_net` |
| `contracts/api/openapi-core.yaml` | two GET paths; summary schema changes |
| `tests/contract/test_external_result_single_volume_projection.py` | new |
| `tests/contract/test_external_result_briefings.py`, `test_external_quantitative_production_flow.py`, route coverage / `test_api_contract_sync.py` | extended |
| `apps/dashboard/src/lib/core-api/types.ts`, `external-result-workflow.ts`, `external-reconstruction.ts` | types + client functions |
| `apps/dashboard/src/app/api/...` | 5 new BFF route files (Task 4) |
| `apps/dashboard/src/app/field/ExternalEvidencePanel.tsx`, `ExternalResultWorkflowPanel.tsx` | decision slot, issue/poll/show single |
| `apps/dashboard/src/app/sites/[siteId]/observations/page.tsx`, `ExternalObservationHistory.tsx`, `[reportRef]/page.tsx` | merged history, kind badge, single row |
| `apps/dashboard/test/*.test.ts(x)` | new/extended vitest |

---

### Task 1: Core projection of single-volume results

**Files:**
- Modify: `services/core/src/ksi_core/domains/external/quantity/external_relative_volumes.py` (near `report_refs_for_site`, ~line 1767)
- Modify: `services/core/src/ksi_core/domains/external/workflow/external_result_projection_models.py`
- Modify: `services/core/src/ksi_core/domains/external/workflow/external_result_workflow_api.py` (`ExternalResultReadProjector`)
- Create: `tests/contract/test_external_result_single_volume_projection.py`

**Interfaces:**
- Consumes: `ExternalSingleVolumeStore.resolve_historical_report_ref(ref, *, organization_id, now)` → `ResolvedVolumeReport[ExternalSingleVolumeRequestV1, ExternalSingleVolumeExecutionAuthority, ExternalSingleVolumeReportV1] | None`; `ExternalSingleVolumeStore.list_for_work_order`, `.coordinator` (SV-2).
- Produces:
  - `ExternalVolumeLedger.report_index_for_site(site_id: str, *, organization_id: str) -> tuple[ReportIndexEntry, ...]` where `ReportIndexEntry = tuple[datetime, datetime, str]` = `(sort_time, reported_at, report_id)`, newest first. `report_refs_for_site` returns `tuple(entry[2] for entry in ...)` (identical output).
  - `ExternalResultSummaryView.kind: Literal["EXTERNAL_RELATIVE_VOLUME", "EXTERNAL_SINGLE_VOLUME"]`; `baseline_work_order_id: str | None`; `baseline_captured_from/to: datetime | None`.
  - `ExternalResultMetricsView` optional `base_roughness_m: float | None = None`, `boundary_cell_count: int | None = None`, `boundary_sample_count: int | None = None`, `boundary_valid_fraction: float | None = None`.
  - `ExternalResultReadProjector(..., single_volumes: ExternalSingleVolumeStore | None = None)`; `uses_exact_graph(..., single_volumes=None)`; `history_for_site(..., kinds: frozenset[str] | None = None)`; `for_site` merged; `single_volumes` read-only property.

- [ ] **Step 1: Write the failing tests** in `tests/contract/test_external_result_single_volume_projection.py`. Build the relative graph with `external_product_loop_fixture.build_graph` (as `tests/contract/test_external_result_workflow_api.py` does) and a single store with the helpers of `tests/contract/test_external_single_volumes.py` (`_store`, `_issue_and_claim`, `_payload`, `_principal`) sharing the graph's coordinator. Move the helpers you need into a new `tests/contract/external_single_volume_fixture.py` module (import it from both test files; do not copy). Tests:
  1. `test_single_report_projects_as_single_kind` — report one single measurement; `projector.report_for_site(site, ref, organization_id=org)` is `AVAILABLE`, `result.kind == "EXTERNAL_SINGLE_VOLUME"`, `baseline_work_order_id is None`, `baseline_captured_from is None`, `current_captured_from == request.target.captured_from`, `metrics.base_roughness_m == payload.metrics.base_roughness_m`, `review_ref is None`, `proposal_count == 0`.
  2. `test_relative_history_is_unchanged_by_single_reports` — with one relative and one single report, `history_for_site(..., kinds=frozenset({"EXTERNAL_RELATIVE_VOLUME"}))` equals the output of a projector built without `single_volumes` (compare `model_dump(mode="json")`).
  3. `test_merged_history_orders_both_families_newest_first_and_pages` — two relative + one single with interleaved capture times; merged `history_for_site(limit=2)` order equals sorting all `(sort_time, reported_at, ref)` descending; `next_cursor` continues to the third; a cursor of a foreign org raises `LookupError`.
  4. `test_single_report_with_unavailable_authority_is_truthful` — make the single authority port's `resolve_historical` return `None`; the row is `HISTORICAL_SOURCE_UNAVAILABLE` and `for_site` does not fall back to an older relative report.
  5. `test_for_work_order_includes_single_results` — the work order of the single report projects the single result.
  6. `test_citation_for_single_result` — `citation_for(...)` returns `object_type == "EXTERNAL_SINGLE_VOLUME_REPORT"`, `source_path == "/v1/external-single-volume-reports/" + quote(ref, safe="")`, `captured_from == iso_utc(target.captured_from)`, `captured_to == iso_utc(target.captured_to)`, label ends with `외부 단일 시점 체적 결과`.
  7. `test_projector_rejects_single_store_on_another_coordinator` — `ValueError`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run --locked pytest tests/contract/test_external_result_single_volume_projection.py -q`
Expected: FAIL (`TypeError: ... unexpected keyword argument 'single_volumes'`).

- [ ] **Step 3: Implement the ledger index**

```python
# external_relative_volumes.py, inside ExternalVolumeLedger
    def report_index_for_site(
        self, site_id: str, *, organization_id: str
    ) -> tuple[tuple[datetime, datetime, str], ...]:
        """Newest-first ``(sort_time, reported_at, report_id)`` keys, no request ledger."""

        with self._lock:
            records = [
                record
                for record in self._records.values()
                if record.authority.organization_id == organization_id
                and record.authority.site_id == site_id
                and record.report is not None
            ]
        return tuple(
            sorted(
                (
                    (self._report_sort_time(record), record.report.reported_at, record.report.report_id)
                    for record in records
                    if record.report is not None
                ),
                reverse=True,
            )
        )

    def report_refs_for_site(self, site_id: str, *, organization_id: str) -> tuple[str, ...]:
        # keep the existing docstring
        return tuple(
            entry[2] for entry in self.report_index_for_site(site_id, organization_id=organization_id)
        )
```

- [ ] **Step 4: Implement the models** — in `external_result_projection_models.py`:

```python
ExternalResultKind = Literal["EXTERNAL_RELATIVE_VOLUME", "EXTERNAL_SINGLE_VOLUME"]

class ExternalResultMetricsView(CamelModel):
    ...  # existing fields unchanged
    base_roughness_m: float | None = None
    boundary_cell_count: int | None = None
    boundary_sample_count: int | None = None
    boundary_valid_fraction: float | None = None

class ExternalResultSummaryView(CamelModel):
    kind: ExternalResultKind = "EXTERNAL_RELATIVE_VOLUME"
    ...
    baseline_work_order_id: str | None
    ...
    baseline_captured_from: datetime | None
    baseline_captured_to: datetime | None
```

Add `ExternalResultKind` to `__all__`. The relative metrics dump has no single keys, so the new fields stay `None`; check that `CamelModel` serializes `None` fields (existing responses then gain four `null` keys — acceptable additive change; `test_api_contract_sync.py` is updated in Task 2).

- [ ] **Step 5: Implement the projector**
  - Constructor: accept `single_volumes`; if given, require `single_volumes.coordinator is workflow.coordinator`, else `ValueError("external result projection requires the exact durable volume graph")`.
  - `_SINGLE_PREFIX = "external-single-volume-report-"`; `_for_report_ref` → `self._for_single_report_ref(...)` when `self._single_volumes is not None and report_ref.startswith(_SINGLE_PREFIX)`; an unknown single ref with no single store returns `HISTORICAL_SOURCE_UNAVAILABLE` only when it is actually retained — keep the current relative path for all other refs.
  - `_for_single_report_ref`: resolve; apply the same integrity checks as the relative path (`request_digest`, `report_digest`, zone definition digest, policy digest, org, `request.current_work_order_id == authority.current_work_order_id`, report↔request id/digest); build the summary with `kind="EXTERNAL_SINGLE_VOLUME"`, `baseline_*=None`, `current_captured_*=request.target.captured_*`, `metrics=ExternalResultMetricsView.model_validate(report.payload.metrics.model_dump(by_alias=True, mode="json"))`, policy view from `authority.execution_policy`, `review_ref=review_digest=reviewed_at=None`, `proposal_count=approved_proposal_count=0`.
  - `_report_index(site_id, organization_id, kinds)`: relative entries from `self._volumes.report_index_for_site` (kind relative), single entries from the single store when present; filter by `kinds`; `sorted(..., reverse=True)` on the `(sort_time, reported_at, ref)` tuple; return the refs. `for_site`, `history_for_site`, `report_for_site` use it (`for_site`/`report_for_site` with `kinds=None`).
  - `for_work_order`: add single candidates (`record.report is not None`) with key `(record.request.target.captured_to, report.reported_at, report.report_id)` and pick the max across both families.
  - `citation_for`: branch on `result.kind`; single uses the constants in Global Constraints and `captured_from=iso_utc(result.current_captured_from)`. The relative branch is unchanged (it dereferences `baseline_captured_from`, which is non-null for relative).

- [ ] **Step 6: Run tests** — the new file plus the unchanged neighbors:

Run: `uv run --locked pytest tests/contract/test_external_result_single_volume_projection.py tests/contract/test_external_result_workflow_api.py tests/contract/test_external_relative_volumes.py tests/contract/test_external_single_volumes.py tests/contract/test_external_result_briefings.py -q`
Expected: all PASS. Then `uv run --locked mypy services/core tests/contract/test_external_result_single_volume_projection.py tests/contract/external_single_volume_fixture.py`.

- [ ] **Step 7: Commit** `feat(core): project single-volume results with merged site history (SV-3)`

---

### Task 2: Core routes and graph wiring

**Files:**
- Modify: `external_result_workflow_api.py` (`build_external_result_workflow_router`)
- Modify: `composition/external_graph.py` (`complete_external_graph`), `composition/routes/external.py`, `composition/assembly.py` (only where the projector/router is built)
- Modify: `contracts/api/openapi-core.yaml`
- Test: extend `tests/contract/test_external_result_single_volume_projection.py`; the hostile-body/route-coverage test that SV-2 Task 4 extended (find with `grep -rln "single-volume-requests" tests/contract`); `tests/contract/test_api_contract_sync.py`; `tests/contract/test_external_quantitative_production_flow.py`

**Interfaces:**
- Consumes: Task 1 projector API; `ExternalSingleVolumeWiring.store` (SV-2, on `ExternalPreWorkOrderGraph.single_volume`).
- Produces:
  - `build_external_result_workflow_router(volumes, service, *, single_volumes: ExternalSingleVolumeStore | None = None, clock=None)`.
  - `GET /v1/sites/{site_id}/external-volume-reports?after&limit` → `ExternalResultHistoryView` (both families); 404 detail `EXTERNAL_VOLUME_REPORT_NOT_FOUND`.
  - `GET /v1/external-single-volume-reports/{report_ref}` → `ExternalSingleVolumeReportView(request: ExternalSingleVolumeRequestV1, report: ExternalSingleVolumeReportV1, execution_policy: ExternalSingleVolumeExecutionPolicyV1)`; 404 detail `EXTERNAL_SINGLE_VOLUME_REPORT_NOT_FOUND`. Mounted only when `single_volumes` is not `None`.
  - Existing `/v1/sites/{site_id}/external-relative-volume-reports` calls `history_for_site(..., kinds=frozenset({"EXTERNAL_RELATIVE_VOLUME"}))`.
  - `/v1/sites/{site_id}/observations/{report_ref}` resolves both families (it already goes through `report_for_site`).
  - `app.state.external_result_read_projector.single_volumes is app.state.external_single_volume_store` when single volume is configured.

- [ ] **Step 1: Failing tests**
  1. HTTP test on a TestClient app built like `test_external_result_workflow_api.py` plus the single store: merged history route lists both families; relative route lists only relative; single report route returns 200 with the sealed request/report for the owner org and 404 for another org (`Authorization: Bearer other-org-fixture` pattern) and for a relative ref.
  2. In `test_external_quantitative_production_flow.py::test_signed_provider_drives_complete_external_relative_volume_lifecycle` after the single report is accepted (~line 2280): `GET /v1/sites/{site}/external-volume-reports` contains the single ref with `result.kind == "EXTERNAL_SINGLE_VOLUME"`; `GET /v1/external-single-volume-reports/{ref}` is 200; after the restart block, the same two reads still succeed with identical `reportDigest`.
  3. Route coverage test lists the two new GET paths; `test_api_contract_sync.py` passes after the OpenAPI edit.
- [ ] **Step 2: Run** `uv run --locked pytest tests/contract/test_external_result_single_volume_projection.py tests/contract/test_external_quantitative_production_flow.py tests/contract/test_api_contract_sync.py -q` → FAIL.
- [ ] **Step 3: Implement.** Router: require `single_volumes.coordinator is service.coordinator` when given; build the projector with it. `complete_external_graph`: pass `single_volumes=pre_work_order.single_volume.store if pre_work_order.single_volume is not None else None`. `routes/external.py`: the fallback projector and `uses_exact_graph` receive `external_single_volume.store` when present, and the router call passes it. `assembly.py`: no behavior change beyond forwarding. OpenAPI: add both paths (tags `external-result-workflow`), add `ExternalSingleVolumeReportView` schema, make the three baseline summary fields nullable, add the four optional metric fields and the `kind` enum.
- [ ] **Step 4: Run** the Step 2 command plus `tests/contract -k "route or assembly or workspace"` → PASS.
- [ ] **Step 5: Commit** `feat(core): single-volume report and merged history routes (SV-3)`

---

### Task 3: AX briefing for single-volume results

**Files:**
- Modify: `services/core/src/ksi_core/domains/external/workflow/external_result_briefings.py`
- Modify: `services/core/src/ksi_core/composition/assembly.py` (~line 266, where `ExternalResultBriefingProjector` is bound)
- Test: `tests/contract/test_external_result_briefings.py`

**Interfaces:**
- Consumes: Task 1 `result.kind`, single metric fields; `ExternalSingleVolumeStore.bind_report_listener` (inherited from `ExternalVolumeLedger`, line 1142).
- Produces: `ExternalResultBriefingProjector.bind(*, volumes, reviews, service, single_volumes=None)`.

- [ ] **Step 1: Failing tests** (reuse the existing briefing test harness):
  1. `test_single_volume_report_briefing_sentence` — after a single report and `flush()`, latest briefing `what_changed == "{zone} 적치물 체적 1,234.5 m³ (±12.3 m³, 기저면 거칠기 0.08 m)."` for metrics `fill_m3=1234.5`, `uncertainty_m3=12.3`, `base_roughness_m=0.08`; `why_it_matters == "단일 시점 측정입니다. 같은 구역의 다음 측정과 비교할 수 있습니다."`; `decision_prompt == "결과와 근거를 검토하세요."`; first citation `object_type == "external-single-volume-report"`, `source_path == f"/v1/external-single-volume-reports/{ref}"`, `captured_from == target.captured_from.isoformat()`; watermark `external-report:{digest}:REPORTED`.
  2. `test_single_volume_unknown_uncertainty_sentence` — `uncertainty_m3=None` → `"(불확도 미산정, 기저면 거칠기 0.08 m)"`.
  3. `test_single_results_do_not_feed_relative_delta` — relative report after a single report in the same WorkArea still says "이 구역의 첫 결과입니다…".
  4. Existing relative briefing tests pass unchanged.
- [ ] **Step 2: Run** `uv run --locked pytest tests/contract/test_external_result_briefings.py -q` → new tests FAIL.
- [ ] **Step 3: Implement.**
  - `bind`: when `single_volumes` is given, `single_volumes.bind_report_listener(self.on_report)`.
  - `_project_report`: `binding = getattr(record.request, "current", None) or record.request.target`; use `binding.subject`.
  - `_record`: if `result.kind == "EXTERNAL_SINGLE_VOLUME"`, build `what_changed` with the Global Constraints sentence, `why_it_matters` as in test 1, citation `object_type="external-single-volume-report"`, label `f"{zone} 단일 시점 체적 보고서"`, `source_path=f"/v1/external-single-volume-reports/{report_ref}"`, `captured_from=result.current_captured_from.isoformat()`; the `site-observation` citation is shared. The `REVIEWED`/`APPROVED` stages cannot occur for single results in SV-3a.
  - `_previous_net`: add `and item.result.kind == "EXTERNAL_RELATIVE_VOLUME"` (and only run it for relative results).
  - `assembly.py`: pass `single_volumes=` the wired single store (or `None`).
- [ ] **Step 4: Run** the Step 2 command and `tests/contract/test_external_quantitative_production_flow.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(core): deterministic single-volume site briefing (SV-3)`

---

### Task 4: Dashboard Core client and BFF routes

**Files:**
- Modify: `apps/dashboard/src/lib/core-api/types.ts` (`ExternalResultSummaryView`, `ExternalResultMetricsView`)
- Modify: `apps/dashboard/src/lib/core-api/external-reconstruction.ts` (single-volume decision)
- Modify: `apps/dashboard/src/lib/core-api/external-result-workflow.ts`
- Create (BFF, copy the validation style of `relative-volume-requests/route.ts`):
  - `src/app/api/observation-work-orders/[workOrderId]/external-reconstruction-submissions/[submissionRef]/revisions/[revision]/use-decisions/single-volume/route.ts` (POST)
  - `src/app/api/observation-work-orders/[workOrderId]/single-volume-requests/route.ts` (GET, POST)
  - `src/app/api/observation-work-orders/[workOrderId]/single-volume-requests/[requestRef]/route.ts` (GET)
  - `src/app/api/external-single-volume-reports/[reportRef]/route.ts` (GET)
  - `src/app/api/sites/[siteId]/external-volume-reports/route.ts` (GET)
- Test: `apps/dashboard/test/external-single-volume-routes.test.ts` (pattern: `test/external-result-workflow-route.test.ts`)

**Interfaces:**
- Produces (TypeScript):
  - `ExternalResultSummaryView.kind: "EXTERNAL_RELATIVE_VOLUME" | "EXTERNAL_SINGLE_VOLUME"`; `baselineWorkOrderId`, `baselineCapturedFrom`, `baselineCapturedTo`: `string | null`.
  - `ExternalResultMetricsView` optional `baseRoughnessM?: number | null; boundaryCellCount?: number | null; boundarySampleCount?: number | null; boundaryValidFraction?: number | null`.
  - `requestExternalSingleVolumeDecision(workOrderId, submissionRef, revision, zoneId: string, idempotencyKey): Promise<{ decision: ExternalUseDecision }>` → Core `.../use-decisions/single-volume` body `{ zoneId }`.
  - `issueExternalSingleVolume(workOrderId, decisionRef, idempotencyKey)`, `listExternalSingleVolumeRequests(workOrderId)`, `getExternalSingleVolumeRequest(workOrderId, requestRef)` — same response types as the relative functions (`ExternalRelativeVolumeMutation`, `ExternalRelativeVolumeRequestView`; Core reuses those schemas).
  - `getExternalSingleVolumeReport(reportRef): Promise<ExternalSingleVolumeReportView>`.
  - `listSiteExternalVolumeHistory(siteId, { after, limit })`; type aliases `ExternalVolumeHistoryItem = ExternalRelativeVolumeHistoryItem`.

- [ ] **Step 1: Failing vitest** — for each route: cross-site POST → 403 `CROSS_SITE_REQUEST`; malformed ids/refs → 404 or 400 (`INVALID_EXTERNAL_SINGLE_VOLUME_INTENT` for a body other than exactly `{ decisionRef }` / `{ zoneId }`); a missing idempotency key → 400; a Core `CoreApiError(409, ...)` is passed through; the happy path forwards the exact Core path and body (mock `coreFetch`). The single report ref pattern is `/^external-single-volume-report-[0-9a-f]{32}$/` (`ExternalVolumeLedger` builds `_KIND_PREFIX + "-report-" + sha256(...)[:32]`, ~line 2228). `StateBadge` is exported from `src/components/ui/StatusBadge.tsx`.
- [ ] **Step 2: Run** `cd apps/dashboard && npx vitest run test/external-single-volume-routes.test.ts` → FAIL.
- [ ] **Step 3: Implement** the client functions and routes.
- [ ] **Step 4: Run** the Step 2 command, then `npx tsc --noEmit` (fix every consumer that now sees nullable baseline fields — `ExternalObservationHistory.tsx`, `[reportRef]/page.tsx`, `ExternalResultWorkflowPanel.tsx`; for relative rows keep behavior, guard only the type).
- [ ] **Step 5: Commit** `feat(dashboard): single-volume Core client and BFF routes (SV-3)`

---

### Task 5: Dashboard decision, issue and result views

**Files:**
- Modify: `apps/dashboard/src/app/field/ExternalEvidencePanel.tsx` (decision slot, around lines 500-560)
- Modify: `apps/dashboard/src/app/field/ExternalResultWorkflowPanel.tsx` (issue, poll, show)
- Modify: `apps/dashboard/src/app/sites/[siteId]/observations/page.tsx`, `ExternalObservationHistory.tsx`, `[reportRef]/page.tsx`
- Modify (only if a new reason is missing): run `uv run --locked python tools/sync_external_use_blockers.py` and verify `apps/dashboard/src/lib/external-use-blockers.generated.json` has copy for every SV-1 single-volume reason/remediation
- Test: extend `test/external-evidence-panel-correction.test.tsx`, `test/external-result-workflow-panel.test.tsx`; create `test/external-observation-history-kinds.test.tsx`

**Interfaces:**
- Consumes: Task 4 routes and types.
- Produces: `ExternalEvidencePanel` prop `onSingleVolumeDecisionChange?: (decision: Decision | null) => void` (mirrors `onRelativeVolumeDecisionChange`); `ExternalResultWorkflowPanel` prop `singleVolumeDecision?: Decision | null`.

- [ ] **Step 1: Failing vitest**
  1. Evidence panel: a "단일 시점 체적" decision button appears; without a WorkArea it shows "단일 시점 체적 작업구역을 선택하세요."; without DSM "DSM이 없어 이 결정을 요청할 수 없습니다."; it never shows a baseline selector for this use; it POSTs to `.../use-decisions/single-volume` with body `{ zoneId }` and an idempotency key reused on retry; a BLOCKED decision renders the generated blocker copy.
  2. Workflow panel: with an ELIGIBLE single decision the "단일 시점 체적 측정 요청" button POSTs `/api/observation-work-orders/{id}/single-volume-requests` `{ decisionRef }`; the request list polls `.../single-volume-requests/{ref}`; a SUCCEEDED request fetches `/api/external-single-volume-reports/{ref}` and shows 체적 (`fillM3`), `±uncertaintyM3` or "불확도 미산정", 기저면 거칠기, 경계 유효 비율; no review button — text "단일 시점 결과 검토는 준비 중입니다." instead.
  3. History: the page loads `listSiteExternalVolumeHistory`; each row shows a `StateBadge` "상대 물량" or "단일 시점 체적"; a single row shows 체적/±/거칠기 and no baseline range, no "이 범위로 새 관측"; `NetTrend` and `compatibilityKey` use relative rows only; the unavailable-row copy is unchanged.
  4. Detail page renders a single projection with the same single row.
- [ ] **Step 2: Run** `npx vitest run test/external-evidence-panel-correction.test.tsx test/external-result-workflow-panel.test.tsx test/external-observation-history-kinds.test.tsx` → FAIL.
- [ ] **Step 3: Implement.** Reuse the existing `decisionIntent`, try-key and abort patterns; add `"SINGLE_VOLUME"` to the use union; `pair` stays `VISUAL_COMPARISON | RELATIVE_VOLUME`; the single-volume branch posts `{ zoneId: zone }` to `${root}/single-volume`. Reuse `StateBadge` from `@/components/ui/StatusBadge`. Keep every Korean relative-volume string unchanged.
- [ ] **Step 4: Full dashboard gates**

Run (in `apps/dashboard`): `npx tsc --noEmit && npm run lint && npm test && npm run build`
Expected: all exit 0 (read each exit code).

- [ ] **Step 5: Commit** `feat(dashboard): single-volume decision, measurement and history views (SV-3)`

---

### Task 6: Gates, evidence and close-out

- [ ] `uv run --locked ruff check .` → clean.
- [ ] `uv run --locked mypy packages services tests tools` → Success.
- [ ] Full pytest in bounded chunks as in SV-2 (tests/contract external families, non-external, packages+services, other dirs); record passed/skipped/failed per chunk and the aggregate; 0 failed.
- [ ] Dashboard gates from Task 5 Step 4 re-run on the final commit.
- [ ] Live check (standing approval for local dev infra): start the local stack, open a work order with a sealed DSM + validated checkpoint evidence if the local data has one, and confirm the decision slot, issue button and history badge render. If no local single-volume-capable data exists, record that explicitly — the end-to-end rehearsal belongs to SV-4.
- [ ] Append an "Execution outcome" section to this ledger with commits and evidence; update `.opencode/working-state.md` (Next = SV-3b plan). `docs/superpowers/product-state.md` is not touched (SV-4 closes the slice).
- [ ] Push only with owner approval after gates pass.

## Self-review notes

- Spec §8 coverage: projection kind/nullable baseline/metrics ✔ (T1); prefix dispatch ✔ (T1); merged history ✔ (T1/T2, amended route); citation ✔ (T1); review/proposal → SV-3b (amendment 1); briefing sentence ✔ (T3); dashboard decision slot ✔, BFF routes ✔ (reviews/shares → SV-3b), panel issue ✔, history badge ✔, blocker copy ✔ (T4/T5); no new page ✔.
- Names used across tasks: `single_volumes` (Python kwarg), `report_index_for_site`, `ExternalResultKind`, `listSiteExternalVolumeHistory`, `requestExternalSingleVolumeDecision`, `issueExternalSingleVolume`, `getExternalSingleVolumeReport`.
