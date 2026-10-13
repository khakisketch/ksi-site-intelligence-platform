# Dashboard Experience Improvements — Work Ledger

Status: approved work items; code execution owned by the user in Codex/Claude Code sessions
(owner directive 2026-09-17). This ledger is the SSOT for task state — update the checklist here,
do not duplicate state in chat.
Created: 2026-09-17 by Build (session ses_f5571c6d7ffeJQIpTb0goaMxUF).

## Source evidence

- Visual audit 2026-09-17: 27 captures (desktop-1440 ×19, mobile-390 ×8) taken from the isolated
  Playwright e2e stack (synthetic seed; Identity+Core+Dashboard on :3230) and reviewed by design-task
  against `design-system/ksi-operations-console/MASTER.md` and `pages/operations-console.md`.
  Captures + `manifest.log`: `.dev-data/visual-audit-20260917/` (machine-local, git-ignored).
  These are synthetic-stack captures — not staging, vendor, HIL, or field acceptance evidence.
- Run2 rehearsal UX defect: `docs/audit/EXTERNAL_PRODUCT_LOOP_FIXTURE_RUN_2026-09-17.md`
  §"Observed UX gap (backlog)".
- Requirement anchor: REQ-UX-101 / `docs/architecture/03_DASHBOARD_UX_GOALS.md` where the external
  flow is involved.

## Concurrent work reconciliation (important)

- The repository advanced while the audit ran (HEAD c127ae7 → c6e1031d; a concurrent owner session
  shipped the AX product loop AX-1/AX-2 and a router fix). Captures approximate that moving
  revision — re-verify every item at current HEAD before changing code.
- A5 overlap: AX-1 `deriveExternalWorkOrderStage`
  (`docs/superpowers/specs/2026-09-17-ax-product-loop-design.md` §4.3) targets the same
  next-action-consistency problem. Verify first; if covered, close A5 with evidence and do not
  re-implement.
- Planned AX slices touch files in this ledger: AX-3 upload auto-recognition (A3/C3 input area),
  AX-4 triage (F01/F12 events), AX-6 report draft (F10 reports). Sequence ledger items after the
  relevant AX slice or coordinate; one writer per file.
- Separate run3 backlog in `docs/superpowers/product-state.md` (duplicate mapping ambiguity, Home
  external-briefing attention, "-0 m³" cosmetic) is not part of this ledger.

## Boundary and guardrails

- Owner module: `apps/dashboard` only. A narrowly additive Core **read** is allowed only where a
  required state cannot be verified today (see A5). Anything beyond a read needs a separate reviewed
  plan; never invent client-side state.
- Reuse existing tokens/components. No new palette, font, theme, hero/marketing pattern, decorative
  imagery, or test-only colour (MASTER prohibited patterns).
- Verify-first items: **F02, F03, F06, F19** plus the A3 fixture caveat. Reproduce live before
  changing code; if not reproducible, mark false-positive here with the method used and close.
- One writer at a time per item. Keep diffs minimal and local to the item.
- UI changes require independent verification (test-runner) and a design fidelity review (design-task,
  `Mode: review`) against fresh 1440/390 PNGs before being marked done.
- Do not regress the Protect list below.

## Audit summary (traceability)

| id | screen(s) | issue (one line) | sev | batch |
|---|---|---|---|---|
| F01 | events d+m | Overdue row shows full blue bar that reads as "complete" | H | A |
| F02 | site-observations d | 404 loses site context and exit paths | H | A |
| F03 | work-order d+m | Stacked duplicate notices; English file/date inputs | H | A |
| F04 | mission-detail d | Identifier/hash lead; dead KMZ control | H | A |
| F05 | event-detail d | Evidence row leads with fixture internals | M | B |
| F06 | mobile shell | Bottom nav appears to occlude scrolling content | M | C |
| F07 | site-data d | Double-negative empty table + faint footnote | M | B |
| F08 | sites d | Row crams two actions; wrapped CTA label | M | B |
| F09 | cross-screen | 4 date formats, inconsistent counts | M | B |
| F10 | reports d+m | Cards lack state/next-action/time | M | B |
| F11 | site tabs | External stub repeats verbatim; sparse tabs 70% empty | M | B |
| F12 | events d | Right half wasted on placeholder with one item | M | B |
| F13 | observations/new d | Path selection shown by border only | M | C |
| F14 | site-design d | English file control; raw script path; no disabled reason | M | C |
| F15 | home d+m | Hero covered by unavailable box; double pagination | M | B |
| F16 | sites-new d | Machine ID first; disabled `다음` without reason | M | C |
| F17 | field-new d | Five rows repeat identical sentence; small `선택` targets | L | C |
| F18 | field d | Competing top actions; adjacent ambers scan as one | L | C |
| F19 | site-data/mission d | Possible fold clipping; stats/hash wrap | L | B |
| F20 | events/field badges | Severity vs stage distinguished by hue only | L | B |

## Execution protocol

1. Reproduce (verify-first items) or attach code evidence; record method in the checklist.
2. Implement smallest change; reuse existing primitives.
3. Gates: `cd apps/dashboard && npm test && npm run lint && npx tsc --noEmit && npm run build`;
   shell/layout/mobile items also `npm run test:e2e`.
4. Independent verification (test-runner) + design fidelity review (design-task) on fresh PNGs.
5. Update the status checklist with commit + evidence pointers.

### Reproduce the captures (recipe)

- From `apps/dashboard`: write a temporary Playwright spec under `e2e/` that logs in (flow in
  `e2e/operations-console.spec.ts:19-37`), navigates each route, waits for `[aria-busy="true"]` to
  clear, and captures `page.screenshot({ fullPage: true, animations: "disabled" })`; run
  `npx playwright test <temp>.spec.ts --project=desktop-1440 --project=mobile-390` (webServer
  auto-starts the isolated stack; ~30 s). Delete the temp spec after. Route list and per-capture
  status: `.dev-data/visual-audit-20260917/manifest.log`.
- For F06/F19 use a live viewport check (scroll a long page at 390/1440 in a real browser) because
  fullPage captures can misplace fixed elements and fold regions.

## Batch A — State honesty (misreading prevention)

### A1 — [F01] SLA breach bar reads as completion (High)

- Evidence: `events-desktop-1440.png`, `events-mobile-390.png` — row "22일째 미조치", full blue bar.
- Problem: `apps/dashboard/src/app/events/DwellBar.tsx` fills toward breach by design ("차오를수록
  나쁨"), but at/over target the full fill reads as done while the label says overdue. Keep the
  intent, remove the completion ambiguity.
- Files: `apps/dashboard/src/app/events/DwellBar.tsx`, `apps/dashboard/src/app/events/page.tsx`.
- Acceptance: breached rows are never confusable with completion — explicit breach treatment
  (marker/shape/label, severity colour) distinct from a progress fill; verified at 1440 and 390 on
  the fixture row; `미조치` count semantics unchanged.
- Verify: component test for state→visual mapping; re-capture events at both widths; design review.

### A2 — [F02] Site observations 404 loses context (High) [VERIFY]

- Evidence: `site-observations-desktop-1440.png` — generic "현장을 찾을 수 없습니다" render
  (`apps/dashboard/src/app/sites/[siteId]/not-found.tsx`) with no site name and no exit.
- Reproduce: live stack — open `/sites/e2e-site-workspace/observations`; log the Core response for
  the site and which branch produced the 404. If the site resolves (capture/build artifact), close
  as false-positive with method.
- Files: `apps/dashboard/src/app/sites/[siteId]/observations/page.tsx`,
  `apps/dashboard/src/app/sites/[siteId]/not-found.tsx`.
- Acceptance: when a site cannot be resolved, the screen keeps requested context (name when known;
  ID only in expert detail) and offers exits (site list / back). If the real failure is an
  API/permission state rather than a missing site, render the correct honest non-404 state.

### A3 — [F03] Work-order stacked notices + non-Korean native inputs (High) [VERIFY]

- Evidence: `work-order-desktop-1440.png`, `work-order-mobile-390.png` — two beige notices under
  `작업 실행 정보 확인 필요`; `Choose File / No file chosen`; `mm/dd/yyyy`.
- Reproduce: live stack work-order page. The `합성 E2E 상태 전이…` banner is fixture text — do not
  chase it. Determine which real conditions render duplicate notices, and list every native control
  that exposes browser-locale English.
- Files: `apps/dashboard/src/app/field/work-orders/[workOrderId]/page.tsx` (notice stack),
  `apps/dashboard/src/app/field/ExternalReconstructionPanel.tsx:464-465`, sibling file inputs
  (`ExternalEvidencePanel.tsx:659`, `components/missions/SourceUploadPanel.tsx:397`,
  `components/missions/CheckpointValidationPanel.tsx:299`,
  `app/events/[eventKey]/EvidencePanel.tsx:125`, `app/sites/[siteId]/design/DesignSurfacePanel.tsx:509`),
  date controls (locate during reproduce).
- Acceptance: one calm notice per condition (no duplicates); file controls present Korean-consistent
  UI (styled trigger, hidden native input; no user-facing English browser chrome); dates use the
  shared Korean datetime pattern.

### A4 — [F04] Mission detail: identifier-first + dead KMZ control (High)

- Evidence: `mission-detail-desktop-1440.png`.
- Files: `apps/dashboard/src/app/missions/[missionId]/page.tsx`,
  `apps/dashboard/src/components/missions/KmzDownloadButton.tsx`.
- Acceptance: scoped question/title leads; SHA/ID demoted to the collapsed expert row; KMZ control
  disabled or removed with an inline reason when no KMZ exists (keep the slot — see comment at
  `apps/dashboard/src/app/field/[missionId]/page.tsx:45` — but make absence explicit).

### A5 — [Backlog] Source work order keeps "외부 산출물 등록 준비" after review + successor approval (High) [VERIFY semantics]

- Evidence: `docs/audit/EXTERNAL_PRODUCT_LOOP_FIXTURE_RUN_2026-09-17.md` §Observed UX gap;
  `apps/dashboard/src/app/field/work-orders/[workOrderId]/page.tsx:119-143`;
  `apps/dashboard/src/app/field/work-order-stage.ts:24-33`; `apps/dashboard/src/app/field/work-queue.ts:109`.
- Reproduce: the run2 state (source WO after review recorded + successor approved). Determine which
  Core-reported fact distinguishes it today (`operations.workflowStatus`, successor linkage). The fix
  must derive from a Core fact — never a UI guess.
- NOTE (2026-09-17): AX-1 shipped `deriveExternalWorkOrderStage` for exactly this case — first verify
  at current HEAD (source WO after review + successor approval); if the stage derives REVIEW/PROPOSE/
  DONE correctly, close A5 with evidence; only fix if still wrong.
- Acceptance: after review and successor approval, the source page's primary card does not present
  registration as the current next action; it states the completed/successor state and links to the
  successor. Without review, current behaviour is unchanged. If Core exposes no usable fact, record
  that gap and stop.

## Batch B — Consistency & completion

### B1 — [F09] Date/count format SSOT (M)

- Files: `apps/dashboard/src/lib/datetime.ts` and the callers on sites/events/event-detail/
  work-order/reports surfaces.
- Acceptance: one Korean datetime pattern and one count pattern applied everywhere; the four observed
  variants (`2026. 8. 25. 09:40` / `2026.8.25.` / `2026.8.25.09:40` / `mm/dd/yyyy`) collapse to one;
  grep-audit for remaining variants.

### B2 — [F05] Event-detail evidence row hierarchy (M)

- Files: `apps/dashboard/src/app/events/[eventKey]/EvidencePanel.tsx`.
- Acceptance: evidence title/time/status first; filename and fixture content-type move to a muted
  expert subline.

### B3 — [F07] Civil readiness empty table (M)

- Files: `apps/dashboard/src/components/site/CivilReadinessCard.tsx`.
- Acceptance: empty state is one line stating what is missing + the single next step; no
  double-negative headers over an empty table; footnote contrast addressed.

### B4 — [F08] Sites table density (M)

- Files: `apps/dashboard/src/app/sites/page.tsx`, `apps/dashboard/src/app/PortfolioTable.tsx`.
- Acceptance: one row action (`현장 열기`); contextual CTA moves to the site header; no wrapped button
  label at 1440; headers no longer crowd.

### B5 — [F10] Reports picker cards (M)

- Files: `apps/dashboard/src/app/reports/page.tsx`.
- Acceptance: each card shows state → next action → truthful time → open link, or a disabled reason;
  no repeated identical subtitle.

### B6 — [F11] Duplicated external stub across site tabs (M)

- Files: `apps/dashboard/src/components/external-results/ExternalSiteResultSummary.tsx`,
  site tabs (`apps/dashboard/src/app/sites/[siteId]/page.tsx:423` plus progress/changes/reports).
- Acceptance: stub lives in one canonical tab; other tabs link to it; sparse tabs collapse empty
  vertical rhythm.

### B7 — [F15] Home hero overlay + double pagination (M)

- Files: `apps/dashboard/src/app/page.tsx`, `apps/dashboard/src/app/HomeAttentionCarousel.tsx`.
- Acceptance: the unavailable notice no longer covers the evidence area as a large white box (corner
  badge pattern); single pagination signal; site/question/action keep first position at 1440 and 390.

### B8 — [F12] Events desktop right pane (M)

- Files: `apps/dashboard/src/app/events/page.tsx`.
- Acceptance: with a single queue item on desktop, its detail is shown (or the hint collapses to a
  slim strip); no half-screen placeholder.

### B9 — [F19] Fold/wrap check (L) [VERIFY]

- Files: `apps/dashboard/src/app/sites/[siteId]/page.tsx` (data section), mission-detail stat block.
- Acceptance: live viewport confirms nothing is clipped; long policy/hash strings wrap or collapse.
  If capture artifact, close with method.

### B10 — [F20] Badge shape separation (L)

- Files: `apps/dashboard/src/components/ui/StatusBadge.tsx` and events/field usage.
- Acceptance: severity vs stage not distinguishable by hue alone at a glance (shape/position
  separation); existing text labels preserved.

## Batch C — Mobile & compact ergonomics

### C1 — [F06] Bottom nav occlusion (M) [VERIFY]

- Files: `apps/dashboard/src/components/nav/MobileBottomNav.tsx`, `apps/dashboard/src/app/layout.tsx:108`,
  page scroll containers.
- Reproduce: live 390 viewport scroll on long pages (fullPage captures can misplace fixed elements).
- Acceptance: last content is not occluded; bottom padding equals nav height + safe area; verify on
  home/sites/field/work-order.
  2026-10-13 closed after reproduction and fix. At 390×844 with zero safe inset, the live shell had
  57px navigation over 64px reserved space and no overlap. Simulating a 34px device inset exposed
  the defect on Home: nav grew to 91px while main stayed at 64px, covering the last text by 11px.
  `globals.css` now shares the nav-row (56px), divider (1px), and safe-area tokens between
  `MobileBottomNav` and `layout.tsx`; main clearance equals the actual nav height. A mobile E2E
  checks Home, Sites, Field, and WorkOrder with a 34px inset. Live 390×844 checks passed on all four;
  1440px confirms the bottom nav remains hidden and main padding is zero. The old Home snapshot
  (last captured before the 2026-10-12 unavailable-lane notice) was refreshed to current UI.
  Gates: Vitest 798, ESLint/tsc/build clean; mobile Playwright 2/2 passed. Screenshots:
  `/tmp/opencode/ksi-f04-review-20261013/evidence/c1-home-mobile-390-{top,safe-area-sim}.png` and
  `c1-work-order-desktop-1440.png`. Independent Design Specialist review: pass, no blockers.
  No domain invariants, API contracts, or device assumptions changed; safe-area behavior was simulated,
  not tested on a physical iPhone.

### C2 — [F13] observations/new path selection (M)

- Files: `apps/dashboard/src/app/sites/[siteId]/observations/new/page.tsx`.
- Acceptance: explicit selected state (label/check, not border only); form heading scoped to the
  selected path.

### C3 — [F14] Design surface upload (M)

- Files: `apps/dashboard/src/app/sites/[siteId]/design/DesignSurfacePanel.tsx` (+ the A3 input pattern).
- Acceptance: Korean controls; converter script path demoted to help text; disabled submit names its
  reason inline.

### C4 — [F16] sites/new step form (M)

- Files: `apps/dashboard/src/app/sites/new/page.tsx` (+ wizard components).
- Acceptance: `현장 이름` leads; ID rules collapsed to help text; disabled `다음` names what blocks it;
  step rail legible.

### C5 — [F17] field/new repeated copy (L)

- Files: `apps/dashboard/src/app/field/new/page.tsx`.
- Acceptance: rows differentiated (state/next action) or repeated sentence removed; `선택` meets
  button target size.

### C6 — [F18] Field top strip hierarchy (L)

- Files: `apps/dashboard/src/app/field/page.tsx`.
- Acceptance: one primary action (`새 관측 시작`), other two demoted; adjacent badge text contrast AA.

## Protect list (must not regress)

- Shell: persistent desktop sidebar + 5-tab mobile nav; no marketing hero/CTA/gradients.
- Honest unavailable wording: `대표 이미지 없음`, `AI 브리핑은 아직 사용하지 않습니다`,
  `노트북에서 계속`, `아직 비행 보고가 도착하지 않았습니다`, `토목 준비 상태 확인 불가`.
- Compact summary strips on field/events; user vocabulary (`확인 항목`, `새 조사`, `현장 등록`,
  `현장 열기`, `확정·오탐`) with technical terms demoted to expert rows.
- Mobile table→card conversion with no horizontal overflow; status text (not colour alone).

## Known unknowns (from the audit)

Dialogs/dropdown/validation/search; hover/focus/keyboard order; skeleton vs spinner; error toasts
(401/403/404/409/422/503); long names and 256-vertex boundary performance; real data volumes; real
evidence images; touch-target measurement and axe numbers across roles; `ResponsiveActionBoundary`
copy beyond the work-order mobile case.

## Status checklist

- [x] A1 [F01] SLA breach bar — owner: Claude — breached track now uses a distinct
  striped fill + tinted track (`bg-crit-bg`), never a solid "complete-looking" bar;
  `test/dwell-bar.test.tsx` (breached vs in-progress vs settled); full dashboard
  gates green.
- [ ] A2 [F02] observations 404 context (verify-first) — owner: —
  2026-10-06 bounded subcase: the existing Site not-found paragraph no longer claims a scoped404
  proves deletion/nonexistence; exact title/layout/Site-list exit retained. Real component RED→GREEN,
  actual authenticated scoped404 at1440/390 and exit→`/sites`200, independent966tests/lint/types/build
  verified in [consumer hardening Task4](2026-10-06-consumer-hardening.md). Seeded Site is present but
  dev OIDC allowedSiteIds/WorkAreaIds are empty; do not close positive history-availability/context
  acceptance as a false-positive without a properly scoped fixture. No production grants changed.
  Follow-up Task5 reproduces fully mounted Core with exact scoped FIELD_OPERATOR: Site/WorkAreas200
  but V1 history403 (not in reviewed route allowlist). Bounded page repair preserves the exact
  existing success header/exits on dependent failure, uses nonretryable permission guidance, and
  resolves Site before history so a child403 cannot mask Site404 or child404 assert Site absence.
  Page RED5/GREEN7 and actual1440/390 browser recheck recorded in the same Task5 ledger; independent
  129files/973tests/lint/types/build passed and generated tracked config restored/type-rechecked.
  Broader authorized history availability stays open; no route/grant expansion.
- [ ] A3 [F03] work-order notices + native inputs (verify-first) — owner: —
  2026-10-13 implemented locally (선구현): native file controls replaced with the shared
  `components/ui/FilePickerField` — styled Korean trigger (`파일 선택`) + sr-only input, no browser
  locale chrome (applied to `ExternalReconstructionPanel` ortho/DSM and `ExternalEvidencePanel`
  checkpoint CSV); the three `datetime-local` controls gained a shared Korean echo
  (`선택: 2026. 10. 15. 14:30` via `formatKoreanDateTime`, operations due + capture start/end).
  Notice-stack half is **not reproducible at current HEAD**: live DOM check at the work-order page
  (1440) shows 0 beige notices and no duplicate notice; the 2026-09-17 captures include the fixture
  banner state the plan says not to chase. Dev gates: vitest 792 (+4 `test/file-picker-field.test.tsx`),
  tsc/eslint/build 0; live check `fileTriggers=2 emptyLabels=2 nativeVisibleInputs=0` + datetime echo;
  capture `/tmp/opencode/ksi-f04-review-20261013/evidence/a3-korean-file-picker.png`. Independent
  test-runner + design fidelity review still pending before [x].
- [x] A4 [F04] mission detail hierarchy/KMZ — owner: Claude — scoped title
  (`MISSION_TYPE_LABEL`) now leads; missionId + KMZ SHA-256 moved into a collapsed
  "전문가 정보" `<details>`; the no-KMZ state is a non-button notice labelled
  "KMZ 다운로드 불가" instead of a disabled-looking clickable span;
  `test/kmz-download-button.test.tsx`; full dashboard gates green. Design-fidelity
  re-capture at 1440/390 not yet run (needs the live e2e stack — batch with the
  verify-first items).
- [x] A5 [backlog] source WO next action after successor (verify-first) — owner:
  Claude — verified at current HEAD with real run3 evidence (not a re-audit): the
  run3 browser pass (`docs/audit/EXTERNAL_PRODUCT_LOOP_FIXTURE_RUN_2026-09-17.md`
  §run3) shows the exact scenario — after review the card reads "재관측 필요 여부
  결정", after successor approval it reads "후속 관측 계획됨" naming the successor
  work order (`.dev-data/visual-audit-20260917/` is unrelated; see
  `.dev-data/a2-fix/run3/shot-wo-after-review.png` and `shot-wo-after-approve.png`).
  `deriveExternalWorkOrderStage` (AX-1) already covers this. No further change.
- [ ] B1 [F09] date/count SSOT — owner: — (deferred: 15 files use raw
  `toLocaleDate/String` outside `lib/datetime.ts`; needs a per-file audit, not
  a mechanical sweep — see note below)
  2026-10-13 implemented locally (선구현): number formatting consolidated into `lib/number-format.ts`
  (`formatNumberKo` moved from `phase34-labels` + `formatSignificantKo`/`formatCountKo`/`formatBytesKo`);
  `phase34-labels` re-exports `formatNumberKo` so existing importers stay. Fifteen raw `toLocaleString`
  sites (header recognition, reconstruction upload/hash text, analysis panel, spatial assets, geotiff
  overlay, workflow report metrics) now use the SSOT, and the spatial-assets observation time renders
  through `formatKoreanDateTime`. Grep-audit: `toLocaleString|toLocaleDateString|toLocaleTimeString`
  outside the two SSOT modules = **0**; the audit variants `2026.8.25.`/`2026.8.25.09:40` are absent at
  current HEAD (`page.tsx` already formats via the SSOT); the remaining manual date construction is the
  `datetime-local` input value (widget format, not display). Dev gates: vitest 798 (+6
  `test/number-format.test.ts`), tsc/eslint 0. Independent review pending (batch).
- [x] B2 [F05] event evidence hierarchy — owner: Claude — row now leads with a
  human evidence kind (사진/동영상/파일 증거) + status badge + time; artifact
  id and raw MIME moved to a muted subline; `test/event-evidence-panel-hierarchy.test.tsx`.
- [x] B3 [F07] civil readiness empty state — owner: Claude — the
  projection-unavailable detail collapsed from two stacked negative sentences
  to one line naming what's missing plus one next step; footnote weight
  bumped for legibility; `test/civil-readiness.test.ts` updated.
- [x] B4 [F08] sites table density — owner: Claude — the row/card action
  column no longer duplicates the site's contextual CTA next to "현장 열기";
  `SiteHeader.tsx` already shows that CTA on the site detail page, so the row
  now carries one action; `test/sites-table-row-action.test.ts`.
- [ ] B5 [F10] reports picker facts — owner: — (sequence after AX-6 report draft)
- [x] B6 [F11] external stub consolidation — owner: Claude —
  `ExternalSiteResultSummary` was rendered verbatim in the briefing, data and
  reports tabs of `[siteId]/page.tsx` (three of the site's own tabs, not the
  separate print `/report` route, which legitimately needs it standalone);
  now lives only in the data tab, the other two link to it;
  `test/site-external-summary-single-tab.test.ts`.
- [x] B7 [F15] home hero/pagination — owner: Claude — the unavailable-image
  notice moved from a full-bleed centred card to a small corner badge, so the
  schematic background stays visible; the redundant "N / M" text counter next
  to the already-interactive dot pagination is gone;
  `test/home-attention-carousel.test.tsx`.
- [ ] B8 [F12] events desktop pane — owner: — (sequence after AX-4 triage)
- [ ] B9 [F19] fold/wrap check (verify-first) — owner: —
- [x] B10 [F20] badge separation — owner: Claude — event row's status badge
  (observation→…→confirmed/dismissed lifecycle) was `StatusBadge` (attribute
  shape) same as severity; now `StateBadge` (progress shape), matching
  triage; `test/event-row-badge-shape.test.ts`.
- [ ] C1 [F06] mobile nav occlusion (verify-first) — owner: —
- [x] C2 [F13] observations/new selection — owner: Claude — the selected path
  card now shows an explicit "✓ 선택됨" label and a thicker border, not colour
  alone; the scoped "외부 산출물 작업" heading already existed once selected;
  `test/observation-path-selection.test.tsx`.
- [ ] C3 [F14] design upload localization — owner: — (sequence with A3/AX-3 input pattern)
  2026-10-13: **obsolete at current HEAD** — the `sites/[siteId]/design` route and
  `DesignSurfacePanel.tsx` no longer exist (P4 console cleanup removed the retired acquisition
  design route; `grep -rn 'type="file"' apps/dashboard/src/app/sites` returns nothing). Nothing to
  localize; close as not-applicable with this method when the batch review runs.
- [x] C4 [F16] sites/new form — owner: Claude — fixed
  `SiteRegistrationOnlyWizard.tsx`, the component the `/sites/new` route
  actually renders (`SiteRegistrationWizard.tsx` is unreachable dead code kept
  only as an aircraft/camera-value test fixture — untouched). 현장 이름 now
  leads before the machine 현장 ID; `WizardShell` gained an optional
  `nextDisabledReason` prop, and step 0 names the first unmet requirement
  when 다음 is disabled. `test/site-registration-only-wizard-step0.test.ts`,
  `test/wizard-shell-next-disabled-reason.test.tsx`. Step-rail legibility not
  addressed — needs the live re-capture to assess.
- [x] C5 [F17] field/new copy — owner: Claude — each site row now shows its
  own `SITE_STATUS_LABEL` status badge instead of the identical boilerplate
  sentence; "선택" affordance bumped to 13px/bold with a chevron;
  `test/field-new-site-rows.test.tsx`.
- [x] C6 [F18] field top strip — owner: Claude — "새 관측 시작" is now the one
  `btn-primary`; "받은 업무"/"팀 관리" demoted to text links;
  `test/field-top-strip-hierarchy.test.ts`. The "adjacent amber badges scan as
  one" half of F18 is not resolved here — could not locate two amber-toned
  badges rendered adjacently in the current source (WorkQueueOperationsNotices'
  overdue/due-soon pills are mutually exclusive); needs the live re-capture to
  confirm or close.
