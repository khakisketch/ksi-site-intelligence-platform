# AX Product Loop — design (2026-09-17)

Status: approved direction (owner approved the feature list and priority on 2026-09-17);
detailed decisions below were made by the implementer and are recorded for review.
Rank: below `PRODUCT_CONSTITUTION`, `FINAL_DECISION_LEDGER`, `MASTER_PRD`,
`DOMAIN_INVARIANTS`, ADR-KSI-022/025/026/036. This document changes no frozen authority.

## 1. Goal

The Product Constitution defines KSI as an AX product: AI reads site data and presents
what changed, why it matters and what to decide, with verified evidence, and connects the
decision to the next observation. Today the AX surface is one chat page with four tools;
every other screen shows facts and raw codes. This program turns the existing external
product loop (register → inspect → decide → volume → review → proposal) into an
AI-first workflow where the product acts first and the human decides.

Non-negotiable boundaries (unchanged): AI never computes numbers, never issues, approves
or plans a Mission, never emits flight coordinates, and never answers without a citation.
Every AI output is either deterministic from Core ledgers or an LLM answer whose citations
were verified by Core (ADR-KSI-026 D6/D7). External AI stays OFF unless the site opted in.

## 2. Principles

1. **Deterministic first.** Wherever Core already holds the facts, the product composes
   the guidance itself (no model call, no egress, works with AI OFF). The LLM is an
   optional layer on top, never the only path.
2. **Same catalog everywhere.** Reason and remediation codes are explained by one
   versioned catalog under `contracts/`; Core and Dashboard consume the same data.
3. **Append-only records.** Briefings, drafts and AI answers are journaled with the
   source watermark they were derived from; nothing is regenerated silently.
4. **Human decision stays explicit.** AI may pre-fill and propose; the human action
   (approve, review, register) remains a separate, permission-checked mutation.

## 3. Sub-projects

| id | name | value | authority touched |
|---|---|---|---|
| AX-1 | Blocker guide and next-action consistency | The operator sees why a decision is blocked, what to do and where, in Korean; the work-order stage reflects the real external loop state | none (presentation + catalog contract) |
| AX-2 | External result briefing | A briefing (what changed / why / decide) is recorded automatically when a relative-volume report, review or approval lands, and surfaced on the site workspace, work order and Home | `SiteBriefing` record (existing contract), new listener on external stores |
| AX-3 | Upload auto-recognition | GeoTIFF headers pre-fill kind, CRS, size and capture time in the registration form | none (client-side) |
| AX-4 | Change and defect triage | Change regions and defect candidates are ranked into "today's few" with evidence | new read projection |
| AX-5 | Proactive re-observation proposal | Low coverage or high uncertainty creates a proposal draft for human approval | uses existing proposal service |
| AX-6 | Report draft | Weekly/monthly narrative plus quantity table from ledgers, editable, exportable | uses existing report export |
| AX-7 | Numeric Q&A | Copilot tools for external volume history and decisions; answers cite reports only | copilot tool allowlist |

This design details AX-1 and AX-2 (first implementation plan). AX-3..AX-7 get their own
short designs when their turn comes; their boundaries above are binding already.

## 4. AX-1 Blocker guide and next-action consistency

### 4.1 Catalog contract

`contracts/catalogs/external-use-blockers.v1.json`:

```json
{
  "contractVersion": "external-use-blockers.v1",
  "reasons": {
    "EVIDENCE_INDEPENDENCE_UNATTESTED": {
      "title": "체크포인트 증거에 독립성 확인이 없습니다",
      "explanation": "…", "owner": "ADMIN", "target": "EVIDENCE"
    }
  },
  "remediations": {
    "ATTEST_INDEPENDENT_EVIDENCE": {
      "step": "독립 측량자의 확인이 담긴 증거 컨텍스트를 등록한 뒤 다시 판정하세요",
      "owner": "ADMIN", "target": "EVIDENCE"
    }
  }
}
```

- `owner` ∈ `OPERATOR | ADMIN | CUSTOMER`; `target` ∈ `SUBJECT | INSPECTION | DISPLAY |
  POLICY | EVIDENCE | MAPPING | ZONE | HEIGHT | GENERAL` and maps to a panel anchor.
- Coverage rule: every reason literal the evaluator can emit and every remediation in
  `ExternalUseEvaluator._remediation` must exist in the catalog. The evaluator exposes
  `PAIR_REASON_REMEDIATIONS` (module constant) so the test does not parse source text.
- Dashboard consumes a generated copy `apps/dashboard/src/lib/external-use-blockers.generated.json`;
  `tools/sync_external_use_blockers.py` copies it and a contract test asserts byte equality.
  Unknown codes at runtime fall back to a generic Korean message plus the raw code in
  expert details; they never crash the panel.

### 4.2 Dashboard blocker card

In `ExternalResultWorkflowPanel` (and the evidence panel where single decisions render),
a BLOCKED decision renders a card: title (reason), explanation, "지금 할 일" (remediation
step), owner badge, and a link/anchor to the target panel. ELIGIBLE keeps the current
compact line. Raw codes move under the existing expert details.

### 4.3 Next-action consistency

`presentWorkOrder(status, executionMode)` cannot see the external loop. Add
`deriveExternalWorkOrderStage(input)` (pure, tested) with input
`{ sealedSubmissions, inspectionReported, latestDecisionVerdict, latestReport, reviewed,
approvedProposal, workflowClosed }` returning
`REGISTER | AWAIT_INSPECTION | DECIDE | AWAIT_RESULT | REVIEW | PROPOSE | DONE | CLOSED`
with label, detail, action label and href anchor. The work-order page and the queue labels
use it for external orders; managed orders are unchanged. The page already loads the
context, submissions, workspace external result and exact report, so no new API is
needed; the review/proposal facts come from `ExternalResultSummaryView`
(`reviewRef`, `approvedProposalCount`).

## 5. AX-2 External result briefing

### 5.1 Record

Reuse `SiteBriefing` (schema 1.0). New briefings are deterministic:

- **Trigger A — report recorded** (`ExternalRelativeVolumeStore.record_observed_report`
  success): `whatChanged` = zone name/id, epochs, net/cut/fill m³ and coverage;
  `whyItMatters` = comparison with the previous AVAILABLE report of the same zone
  (delta of net m³) or "첫 결과"; plus uncertainty bound; `decisionPrompt` = "결과와
  근거를 검토하세요"; `uncertainty` = the report's uncertainty note and bound;
  `citations` = `/v1/external-relative-volume-reports/{ref}` and
  `/v1/sites/{siteId}/observations/{ref}`; `sourceWatermark` =
  `external-report:{reportDigest}:REPORTED`; `status` = READY.
- **Trigger B — review recorded**: same facts, `decisionPrompt` = "재관측이 필요하면
  제안을 만드세요"; watermark suffix `REVIEWED`.
- **Trigger C — proposal approved**: `decisionPrompt` = "후속 작업 {successorId}에 산출물을
  등록하세요"; watermark suffix `APPROVED`.
- Idempotent: the store skips a record whose latest briefing for the site already has the
  same watermark. Failures are logged and never roll back the source mutation (ADR-026 D8).
- Numbers are copied from the sealed report; the projector never computes new quantities
  beyond the delta between two retained net values, which is presentation arithmetic.

### 5.2 Wiring

- `SiteBriefingStore` is created whenever the site store exists (today only with the
  copilot). `SiteBriefingService` (LLM refresh) stays copilot-gated. The workspace router
  mounts `GET /v1/sites/{siteId}/briefings/latest` with the store alone and
  `POST …/refresh` only with the service.
- New `GET /v1/site-briefings/latest?limit=` returns the latest briefing per site for the
  principal's organization (Home portfolio).
- `ExternalResultBriefingProjector` (domains/external/workflow) binds to a new
  `bind_report_listener` on the volume store and to the proposal service's review/approve
  paths (post-commit callbacks, exceptions logged).

### 5.3 Surfaces

- Site workspace briefing card: unchanged layout; the "AI 사용 전" empty state applies only
  when no briefing exists; the "KSI AI에서 질문" action shows only when `aiEgressAllowed`.
- Work-order page: a compact briefing card when the latest site briefing cites a report of
  this work order.
- Home: `selectHomeRecentUpdates` gains `RESULT_READY` entries from external briefings
  (report recorded) using the new latest-per-site endpoint; attention cards are unchanged.

## 6. Testing

- Python contract tests: catalog coverage and sync; briefing projector (each trigger,
  idempotency, delta vs previous report, listener failure isolation); router for latest
  per site with organization isolation (INV-060); replay of briefing journal unchanged.
- Dashboard vitest: blocker card rendering for known/unknown codes; stage derivation for
  every stage; Home recent updates with external briefings.
- Local browser pass on the rehearsal stack after implementation (rerun of stages
  4A.4–4A.7) recorded in the audit.

## 7. Out of scope here

LLM-generated briefings for external results (possible later via `SiteBriefingService`
once the copilot tools expose external reports), notifications outside the app, guest
sharing, 3D viewers. No contract schema of a sealed record changes.

## 8. AX-3 Upload auto-recognition (short design, approved 2026-09-18)

Client-side only; no Core, contract schema or authority change.

- On file selection the browser reads only the GeoTIFF header (`geotiff` `fromBlob`
  range reads) in parallel with the existing SHA-256 hash
  (`apps/dashboard/src/lib/geo/geotiff-header.ts`).
- **Declared (customer declaration, EXT-VAL-02):** the embedded EPSG becomes the editable
  per-artifact `declaredCrs` (the contract already allows bounded text; the BFF accepts
  `null` or an already-trimmed string ≤255 so the dashboard digest matches Core, which
  strips whitespace). The TIFF Software tag fills the producer name/version **only when
  those fields are empty**.
- **Reference only:** size, pixel size, and the TIFF DateTime. Band layout (1 float band →
  DSM, 3–4 × 8-bit → ortho) drives a slot-mismatch warning; the file is never moved.
  An unreadable header warns; Core inspection still decides the format.
- **Deviations from the §3 row:** capture time is not pre-filled — the TIFF DateTime is a
  single instant whose meaning varies by producer (ODM 3.5.6 writes the photo date with an
  offset; other tools write the file time) and the form needs a start/end interval. GSD is
  not declared because dashboard canonical JSON accepts only safe integers.
- Resuming an already registered declaration shows header facts but no CRS field; resume
  never re-sends the declaration.

## 9. AX-4 External decisions on Home (short design, approved 2026-09-18)

Re-scoped by the owner on 2026-09-18 from "change and defect triage": no production
producer posts defect candidates, and change detection exists only on the managed path.
The Home attention area (ADR-KSI-025 D1) instead gains the external results that actually
wait for a person. ADR-KSI-025 D1 is amended accordingly.

**Core (read-only, no journal).** `GET /v1/external-decisions/pending` (`SITES_READ`,
organization-scoped, INV-060) filters the existing `ExternalResultReadProjector` summaries
across the organization's sites:

- `AWAITING_REVIEW` — `measurementStatus == "SUCCEEDED"`, metrics present, no review.
- `AWAITING_APPROVAL` — `proposalCount > approvedProposalCount`.

One item per site: the longest-waiting pending result (`reportedAt` ascending, ties by
report ref); review waits rank before approval waits. Rows whose historical source is
unavailable are skipped, never guessed. Each item carries site id, report ref, kind, stage,
`reportedAt`, net m³, uncertainty m³ (nullable) and the work area id. Relative and single
volume families are both included.

**Dashboard Home.** A new attention kind `EXTERNAL_DECISION` is inserted after unattended
events and before WorkOrder decisions; the one-card-per-site and no-repeat rules stay.
The card shows the stage (`검토 대기` / `승인 대기`), the value with its uncertainty, the
work area name when known, and links to the site observation report. If the pending call
fails, Home shows the other sources and states that external decisions could not be read;
it never implies there is nothing to decide.

**Out of scope.** Change/defect triage (until a production producer exists), notifications,
ranking by value magnitude.
