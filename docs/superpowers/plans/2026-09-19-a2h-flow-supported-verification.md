# A2H Flow — 지원 기능 우선 구현·검증 (Work Ledger)

Status: active. Owner: Build (session ses_f4b0d67ecffeTRX6ng4JxpnxYm); T2 resumed by Claude Code 2026-09-19.
Created: 2026-09-19. SSOT for task state — update the checklist here, do not duplicate state in chat.
Design baseline (frozen, read-only): `design-previews/site-analysis-workspace/` v8 + FINDINGS.md
"1차 기준안 확정" + "Build 핸드오프" sections. No layout/design changes in this workstream.

## Frozen directive (user, verbatim scope)

> 현재 프리뷰의 메뉴·레이아웃·표시 규칙을 1차 기준안으로 고정한다. 추가 디자인 개편이나 신규 기능
> 확대는 하지 않는다. 다음 작업은 A2H 선택 → 근거 확인 → 검토 기록 저장 → 보고서 포함 변경 →
> 발행본 유지의 연속 흐름을 구현·검증하는 것이다. 기존 Core에서 지원하는 기능과 합성 프리뷰만
> 제공하는 기능을 구분하고, 지원되지 않는 기능은 동작하는 것처럼 연결하지 않는다. 완료 근거는
> 초기 화면 캡처가 아니라 조작 과정과 저장·재조회·발행본 유지 검증 결과로 제시한다.

## Scope (supported-first)

- Wire READS that Core supports today into the A2H flow path.
- For writes with no server contract (zone review notes on internal results; report
  draft/publish/history; internal 보완-request linkage): DO NOT wire as if they exist.
  Render the existing honest unavailable state with a reason, or surface the contract gap
  as a finding. No client-side fakes, no invented endpoints.
- No new Core contracts in this workstream. No production-config changes. No stack changes
  (acceptance browser pass is running; leave it alone).

## Core vs preview (verified 2026-09-19 against dashboard lib)

| Preview behavior | Core status | Integration action |
|---|---|---|
| Work-area boundary/list | supported — `listWorkAreas/registerWorkArea/archiveWorkArea` | map zones to WorkArea |
| Zone net/cut/fill/area/threshold | supported — VolumeChangeReport | server values into panel/table |
| Diff raster + design conformance | supported — DiffRasterRef + design conformance | wire layers |
| External report value + review receipt | supported — `/v1/external-*-reports/{ref}/reviews` | external review records via this API |
| Events list/get/transition/evidence | supported — `events.ts` | event-kind review items via this model |
| Internal zone opinion save/re-query | NOT supported (no zone-result review API found) | new contract required; do not wire |
| Report draft/inclusion/publish/history/immutability | NOT supported (`recordReportExport` receipt only) | new contract required; do not wire |
| 자료/보완 request → status/reply | partial (external reobservation proposals only) | internal linkage needs contract |
| URL state (zone/comparison/source) | partial (tab/epoch params exist; zone param unverified) | deep link only after contract |

## Pre-flight rulings (Build, 2026-09-19)

- R1 — Work happens on a local feature branch from HEAD 9edc4a1 (e.g.
  `build/a2h-flow-supported`), single writer, sequential tasks. No push, no merge,
  no PR without explicit user authorization. Rationale: isolated work without touching
  main or the running acceptance pass. Cost if wrong: rework on a branch, visible and undoable.
- R2 — Pre-existing dirty files (`apps/dashboard/tsconfig.json` modified,
  `.claude/settings.local.json` untracked) are foreign: do not touch, do not include.
- R3 — Unfinished registry entries of session ses_f4d758… (design-task/developer/
  test-runner/reviewer dispatched) are another session's live children: do not assume,
  do not resume, do not collide. Fresh task identities in this session only.
- R4 — `product-state.md` untouched (slice closes only on evidence + user acceptance).
  This workstream is NOT part of EXT-VAL acceptance; slice membership goes to triage.
- R5 — No active goal (`get_goal` → null); no goal started (design-approval work needs none).

## Tasks

- [x] T1 Explore — current dashboard routes/components covering the A2H flow + Core
  endpoints; confirm gaps with file:line evidence. (read-only)
- [~] T2 Developer — implement supported-first wiring + explicit unsupported states;
  evidence per Acceptance format below. (increment 1 done: 현장 분석 탭; review/report tab ports open)
- [ ] T3 Test Runner — independent test execution on the exact reviewed revision.
- [ ] T4 Reviewer — defects and gaps vs this ledger (not producer reasoning).
- [ ] T5 design-task fidelity review — Mode: review, Allowed write paths: none;
  inputs: artifact v8 + diff + PNGs (1280×800 + 390×844 + 1024×768).
- [ ] T6 Evidence pack + close.

## Acceptance evidence format (initial screenshots forbidden)

1. Operation log (select → evidence → record → report-inclusion change)
2. Save → re-query result (same result after navigation/refresh)
3. Published immutability (rev 2 values + digests unchanged)
4. Total change +97.7 → +85.5 on A2H exclusion
5. Failure paths: save failure (no false completion, draft preserved), loading/missing/
   processing-failure states, external report value never flips to "verified" on new data.

## Progress

- 2026-09-19: ledger created; HEAD 9edc4a1 verified; checkpoint stale (says 6b6628b) —
  Git is source of truth.
- 2026-09-19: T1 audit performed by Build directly (read-only grep/glob; no product edits).
  Findings:
  - Site detail + tabs: `apps/dashboard/src/app/sites/[siteId]/page.tsx:307-313`
    (searchParams `{section?, tab?, epoch?}` — **no zone param**; gap (c) confirmed).
  - Zone values today: `components/site/ZoneVolumeBars.tsx:22`,
    `components/reports/VolumeChangeSummary.tsx:69`, consumed at
    `app/sites/[siteId]/page.tsx:535-553` and `app/reports/page.tsx:382-384`
    (`latestTotalNetM3`); report zone rows at `app/sites/[siteId]/report/page.tsx:159-161,250-251`.
  - Review saves exist ONLY for external results:
    `lib/core-api/external-result-workflow.ts:273,281,534`. **No internal zone
    review-note API** (gap (a) confirmed). Events model exists
    (`lib/core-api/events.ts`: listEvents/listAllEvents/getEvent/transitionEvent/
    registerEvidence/getEvidenceViewUrl) for event-kind items.
  - Report: `lib/core-api/report-exports.ts:15` (`recordReportExport` receipt only) +
    `components/reports/PrintReportButton.tsx:3` ("without publishing a new artifact").
    **No draft/inclusion/publish/history** (gap (b) confirmed).
  - No existing client-side fake review/report store to unwind — the v8 draft/publish/notes
    live only in untracked local-only `design-previews/` (gap (d): nothing to remove).
- R6 — `task` delegation failed twice with provider error "OpenCode's free tier can only
  be used from within OpenCode" (explore, identical contract, 2 attempts). Ruling: no worker
  dispatch in this session; T2–T5 parked, NOT attempted. Resume: any session with working
  dispatch reads this ledger + the FINDINGS handoff and continues at T2 with the brief below.
  Cost if wrong: none (no code changed; repo untouched except this ledger file).

## T2 brief (ready, not dispatched)

Objective: Implement supported-first A2H flow wiring in apps/dashboard on a local feature
branch from 9edc4a1; no push, no merge, no PR; leave `apps/dashboard/tsconfig.json`
(modified) and `.claude/settings.local.json` (untracked) untouched.
Allowed write paths: `apps/dashboard/src` (site detail, reports, events, work-areas,
external-results components + colocated tests only).
Forbidden shared files: `contracts/`, `services/`, `design-previews/`,
`docs/superpowers/product-state.md`, `.opencode/working-state.md`, the two dirty files above.
Acceptance criteria:
1. Zone panel/table numbers come from VolumeChangeReport server values (keep existing
   `latestTotalNetM3` rule — no second summation site).
2. Zone boundaries from `listWorkAreas`; diff raster via the existing DiffRasterRef path;
   external review receipts via the existing review API; event-kind review items via
   events transitions.
3. Internal zone opinion save: NOT wired — render the existing honest unavailable state
   with a reason. No fake.
4. Report draft/inclusion/publish/history: NOT wired — no fake publish; export path unchanged.
5. A2H evidence: operation log, server values shown, +97.7→+85.5 only if server-backed
   (else explicit gap), rev-2 immutability check method.
6. Failure states: loading/missing/processing-failure/save-failure (no false completion,
   draft preserved); external value never flips to verified on new data.
Targeted verification: dashboard gates (`npm test`, lint, `tsc --noEmit`, `next build`) +
new/updated component tests for touched surfaces; desktop 1280×800 + mobile 390×844 (+
tablet 1024×768 for map surfaces) PNG captures of touched screens for the T5 fidelity review.
Escalate if: a required read has no endpoint (record as gap, do not invent); anything needs
push/merge/deploy (stop and ask).

## T2 increment 1 — 현장 분석 탭 (Claude Code, 2026-09-19)

Branch `build/a2h-flow-supported` from 9edc4a1 (local only). Worker dispatch not needed: executed directly.

Verified facts that shape the increment:
- `ZoneVolumeDelta.zoneId` == `WorkArea.workAreaId` (`services/core/.../domains/sites/work_areas.py:101-108`),
  and WorkArea polygons are WGS84 GeoJSON (`lib/work-areas.ts polygonToVertices`) → zone boundaries drawable.
- Epoch capture windows exist (`SiteProcessingJobSummary.captureWindow`) → baseline/current labels are server facts.
- NOT in Core: zone total area vs calculated range (W11), measured-range polygon (hatch), internal zone review,
  report inclusion/draft/publish. → v8 "구역의 N%에서 계산", hatch, 의견 저장, 보고서 포함 are NOT rendered as working.

Scope (this increment only):
1. `src/lib/site-analysis.ts` (pure, tested): join latest VolumeChangeReport zones × WorkAreas × epochs →
   zone rows (name, ring, net/cut/fill/area/threshold/uncertainty), comparison labels from capture windows,
   unmapped-zone and missing-epoch states. Total = server `latestTotalNetM3` only.
2. `src/components/site-analysis/*` (client): Leaflet map (OSM base + AOI + zone boundaries + net chips),
   zone list ↔ map selection parity, zone panel (값 · 계산 기준 · 사용 자료). Unsupported actions render a
   disabled state with the missing-contract reason (no fake save).
3. Site page: add `analysis` tab "현장 분석" first + default landing (v8 baseline); volume fetched for it.
   Old tabs stay reachable this increment; 4-tab consolidation is a later increment (recorded, not done).
Out of increment: 설계 대비/적치량 modes, review/report tab ports, URL zone param.

### T2 increment 1 — result (2026-09-19, Claude Code)

Isolation correction: the acceptance `next dev` on 127.0.0.1:3320 (`KSI_DASHBOARD_DIST_DIR=.next-accept`)
serves the MAIN working tree, so branch edits there were hot-reloading into it. Work moved to worktree
`/tmp/ksi-a2h-flow-supported-20260919` (branch `build/a2h-flow-supported`); main tree restored to 9edc4a1
(+ pre-existing tsconfig.json M, this ledger ??). Exposure window ≈ 22:50–22:57 KST, uncommitted source only.

Commits (local, not pushed): 56225c5 feat (analysis tab), 783b29f test (e2e landing), 2dc64db fix
(work-area read failure ≠ unlinked zones).

Evidence (run on 2dc64db unless noted):
- `npx vitest run` → 122 files / 934 tests passed; `tsc --noEmit` clean; `eslint` clean; `next build`
  (distDir .next-a2h) compiled.
- New unit tests `test/site-analysis.test.ts` (10): server total only (97.7, no re-sum), zone↔work-area join,
  unmapped/unreadable zones kept, 404 vs failure vs epoch-list failure, zero-zone report ≠ not computed,
  capture window never guessed, work-area read failure labelled, gap table present.
- Playwright `e2e/operations-console.spec.ts` on a fresh local OIDC+Core stack (3230/8032/9030, run on
  783b29f): new landing assertions (분석 종류 group + 구역별 결과) PASS on mobile-390/tablet-768/desktop-1024/
  desktop-1440. 3 tests × 4 projects fail — the SAME 3 fail on unmodified 9edc4a1 (baseline worktree run,
  desktop-1440: home.png screenshot diff, briefing copy at L252, work detail "분석 준비" at L358) → pre-existing.
- Render/interaction harness (real `SiteAnalysisWorkspace` + real compiled CSS, Core-shaped synthetic payloads
  through `buildSiteAnalysis` — NOT a real Core response): `.dev-data/a2h-t2-harness/` (16 PNG + scripts).
  Operation log: map click A2H → panel "+12.2 m³ · 증가 18.4 · 감소 6.2 · 계산 면적 188 m²" → 사용 자료 확인 opens
  baseline/current capture windows → 의견 남기기/보완 요청 disabled with reason (forced click: no textarea, no
  "기록됨") → 전체 보기 → list click A2H → identical panel (parity true) → re-click on map deselects.
  Mobile 390: bottom sheet 390×625, scrollWidth 390 (no horizontal scroll). 0 page/console errors.

A2H acceptance format vs reality (supported-first):
1. Operation log — select→evidence: DONE (harness). record / report-inclusion change: NOT WIRED (no contract).
2. Save→re-query: NOT POSSIBLE — no internal zone review API (gap a).
3. Published immutability (rev 2): NOT POSSIBLE — no report draft/publish/history API (gap b).
4. +97.7 → +85.5 on A2H exclusion: NOT SERVER-BACKED — Core has no report-inclusion contract; the screen shows
   only the server total. Explicit gap, not faked.
5. Failure paths: loading (skeleton), not-computed (404), read failure, epoch-list failure, work-area failure,
   no-epoch — rendered and unit-tested; save failure N/A (no save path exists).

Not verified / open:
- Real Core data round: local OIDC stack mounts no processing-job store without object storage, and volume
  replay needs a comparison-request lease fence → a real two-epoch report on a live Core was NOT exercised.
  Needs MinIO-backed stack + comparison request fixture (or the owner's real orthophoto round).
- T3 independent test run, T4 review, T5 fidelity review: not done (single session; no independent reviewer).
- Deviations from v8 (all honest-gap driven): no "구역의 N%에서 계산" chip line / coverage bar (W11), no
  measured-range hatch, OSM base instead of orthophoto, 설계 대비/적치량 modes disabled with reason, condition
  chips static (no epoch picker), old tabs still present (4-tab consolidation = later increment).

### Real-Core round (2026-09-19~20, Claude Code) — in progress

Data: public ODM sample Bellus (122 JPEG, one 2015-07-31 flight), split odd/even into two epochs
covering the same footprint → volume change measures reconstruction noise, NOT site activity.
Stack (all local, own ports, no acceptance-stack contact): MinIO `ksi-minio-a2h` 127.0.0.1:19100,
NodeODM `ksi-nodeodm-a2h` 127.0.0.1:13000, issuer 9052 / Core 8052 (DUAL + S3) / dashboard 3252 from the
worktree. Driver scripts + logs: `.dev-data/a2h-real/` (seed.py, ui_actions.mjs, drive_jobs.py,
drive_compare.py, run_core_a2h.py, watchdog.sh).
- Seed via product stores: site + AOI, 3 work areas (wa-site-a2h-real-bellus-0001..3), 2 missions,
  61+61 photos uploaded through Core presigned PUT and sealed.
- Human actions through the real OIDC login (local-admin, org-local-pilot) via dashboard BFF routes.
- Worker credential: local wrapper adds one PROCESSING_WORKER provisioned for org-local-pilot (INV-060);
  stock dev runner only has a `legacy`-org worker which cannot see OIDC-org jobs.

Finding F1 (fixed, d5701e8): worker `register_artifact` sent `primaryObject.name` and a list for
`auxiliaryObjects`; Core (since e46d40b, 2026-09-05) requires a nameless binding and a basename-keyed
dict → every real reconstruction failed artifact registration with 422. MockTransport tests only
checked the envelope. New contract test validates the worker payload against Core's
ProcessingArtifactRequest. Full contract suite: 6021 passed (KMZ fidelity test needs the PSDK sample
that exists only in the main checkout — env-only, passes on main).
Finding F2 (backlog, not fixed): OpenSfM on the odd-photo subset is nondeterministic; one run produced
~1000 km outliers → ODM planned 7,060,900 DEM tiles (~days). Nothing in worker/Core bounds a
reconstruction's extent against the site AOI before DEM generation. Cancel → job FAILED correctly.
Finding F3 (fixed, 61dda24): multi-file mesh digest = combined obj+mtl+texture hash, but Core's
AuthoritativeArtifactManifestV1 (normative, WORKER_LEASE_IDENTITY_CONTRACT) requires artifact digest ==
primary object sha256 → every mesh registration ARTIFACT_CONTRACT_VIOLATION. Worker now uses the primary
digest; texture/mtl integrity tests moved to the per-file bindings. DECISION FLAGGED FOR OWNER REVIEW
(reverses the 2026-08-08 combined-digest choice; local branch only).
Result: both epochs SUCCEEDED on the real path (epoch-a-pj3, epoch-b-pj3; ODM → MinIO → Core artifacts).
Capture window = INCOMPLETE — correct: Bellus EXIF has no GPS time and no OffsetTimeOriginal (INV-020 no guess).
F2 recurrence: 2 of 5 ODM runs on half-overlap subsets produced outlier clouds (180,184 / 7,060,900 DEM
tiles); local watchdog cancelled; jobs FAILED honestly.
BLOCKED at comparison: preflight ANALYSIS_NOT_READY "Mission에 연결된 AcquisitionRun이 없다". Quantitative
comparison requires the acquisition chain (gateway operation receipt → AcquisitionRun → COMPLETED
CoverageReport → acceptable CaptureQualityReport). Imported public photos have no such evidence; creating
it would mean synthesizing field/device evidence → owner decision required.

Owner decision (2026-09-20): complete the round with SYNTHETIC acquisition evidence, clearly labelled.
- Gate 1 (AcquisitionRun/coverage/capture-quality): `.dev-data/a2h-real/seed_acquisition.py` writes a
  work order + AcquisitionRun + COMPLETED CoverageReport + ACCEPTED CaptureQualityReport per mission,
  actor `a2h-real-round-SYNTHETIC-acquisition`. No drone flew, no gateway reported.
- Gate 2 (capture-time window, INV-020): the 2015 Bellus EXIF has no GPS time and no OffsetTimeOriginal,
  so Core refused to guess — correct. `seed_tz_epochs.py` copies each photo with OffsetTimeOriginal
  -04:00 DECLARED (piexif rewrites only the EXIF segment; pixels and the original timestamps untouched).
  Worker now reads VERIFIED capture time (18:25:05Z). The declaration is synthetic: nobody verified the
  camera clock.
Neither may be cited as field/HIL/acceptance evidence. Photos, reconstruction, DSM and the volume
computation remain real.

F2 quantified (2026-09-20): odd/even 61-photo epochs made OpenSfM unstable — 4 of 7 runs produced outlier
clouds (DEM tile plans 2,793 / 50,820 / 180,184 / 4,753,065 / 7,060,900 vs 4–12 tiles when healthy).
Local watchdog (`watchdog.sh`, cancel above 200 planned tiles) now catches them in ~5 min; jobs FAILED
honestly every time. Epochs E/F therefore use all 122 photos each (max overlap); same-flight photos mean
the change value is reconstruction noise by construction.
Root cause (2026-09-20, engine logs): this dataset always splits into partial reconstructions (3-5 even
on healthy runs). When ODM's merge misaligns a partial against GPS, the merged cloud carries outliers
tens to thousands of km away; the split itself is constant, the misalignment is nondeterministic —
using all 122 photos did NOT remove it (950,040-tile plan on the first E run).
Product backlog (two items, neither fixed here):
 - the `ksi-odm-civil-v1` profile sets no `pc-filter`/`auto-boundary`/`boundary`, so outliers survive
   into DEM generation;
 - nothing in worker/Core bounds a reconstruction's extent against the site AOI before that stage, so a
   pathological run can burn days of engine time before anyone notices.

Real-round outcome (2026-09-20): reconstruction chain PROVEN, volume computation BLOCKED by CRS policy.
- Epochs G/H (122 photos each, declared -04:00): both ProcessingJobs SUCCEEDED; capture window recorded
  COMPLETE 2015-07-31T18:25:05Z–18:36:46Z from real EXIF through the real worker.
- Readiness gates passed in order (each one a correct product refusal until satisfied):
  AcquisitionRun → COMPLETED CoverageReport → ACCEPTED CaptureQualityReport → verified capture window →
  WorkOrder temporal policy (max capture span; declarable only at work-order creation, no relink path,
  so missions had to be recreated) → latest ProcessingJob SUCCEEDED (my runner had issued a spare QUEUED
  job; ran it). Comparison request CREATED: mission-a2h-real-epoch-h-cmp1.
- BLOCKED at the comparison worker: `ksi_geo_spatial.crs.assert_supported_project_crs` allows only
  EPSG:5179/5185/5186/5187/5188 (Korean national CRS, guarding against Bessel-era mixing). ODM produced
  EPSG:32617 (Ohio UTM) because the public photos carry no ground control; the normal operating path
  supplies a GCP file whose CRS drives the output. Not pursued: synthesizing GCPs would place Ohio
  imagery on Korean coordinates — that is falsifying the observation location, beyond the owner's
  "synthetic acquisition evidence" approval.
- Dashboard on this real Core (`.dev-data/a2h-real/captures-real/`): the analysis tab renders the site,
  its two real epochs and three work areas, and says "이 시점에는 아직 계산된 비교가 없습니다" — no invented
  values, 0 console/page errors, desktop + mobile.
Open question for the owner (product): with no GCP file, ODM's default output CRS is UTM, which this
whitelist rejects at change-detection — so a domestic flight without ground control would fail the same
way. Is GCP-backed capture a hard product precondition for quantitative comparison, or is a reprojection
path intended? (m2-e2e recorded volumes in EPSG:32617 on 2026-08-10, before this check existed.)
