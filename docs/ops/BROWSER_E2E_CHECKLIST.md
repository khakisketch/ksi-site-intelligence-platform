# Browser E2E Checklist — Submit / Inspect / Quantity / Review-Followup

> Read-only verification checklist. No code changes. This file traces existing
> dashboard screens to Core API clients with file-line pointers, states
> typed-blocker display behavior (including `EGRESS_NOT_ALLOWED`), and lists
> missing links for a full browser run plus online / local / offline variant notes.
> Do not paste secrets, tokens, cookies, or presigned URLs into check results.

## 0. Scope and entry point

- Operator UX owner: `apps/dashboard/` (displays intent; no device authority).
- Mission page assembles three civil panels
  (`CheckpointValidationPanel`, `ComparisonSubmitPanel`,
  `DesignConformancePanel`):
  `apps/dashboard/src/app/missions/[missionId]/page.tsx:311-337`.
  The same page also mounts `SourceUploadPanel` (photo upload /
  reconstruction issuance — the `EGRESS_NOT_ALLOWED` originating surface,
  see §5): `page.tsx:297-308` inside a `ResponsiveActionBoundary`.
  Review-followup lives on the events routes, not the mission page —
  queue `apps/dashboard/src/app/events/page.tsx`, detail
  `apps/dashboard/src/app/events/[eventKey]/page.tsx` (see §4).
- Existing browser specs (do not duplicate; extend only with Build approval):
  `apps/dashboard/e2e/operations-console.spec.ts`,
  `apps/dashboard/e2e/phase2-staging.spec.ts`,
  `apps/dashboard/e2e/auth-cookie-isolation.spec.ts`,
  `apps/dashboard/e2e/empty-organization.spec.ts`.
- BFF contract shape for all browser mutations:
  `{ code, message, detail, reasonCode }` via
  `apps/dashboard/src/lib/core-api/route-handler-util.ts:19-28`,
  consumed by `readableApiError` in
  `apps/dashboard/src/lib/core-api/labels.ts:416-423`.

## 1. Submit — two-epoch comparison request (W2)

Screen: `apps/dashboard/src/components/missions/ComparisonSubmitPanel.tsx`

| Step | What to verify in browser | Wiring pointer |
| --- | --- | --- |
| 1.1 | Epoch dropdowns list only SUCCEEDED jobs; "comparison (later)" limited to this mission's jobs | `selectableEpochs` in `apps/dashboard/src/lib/comparison-submit.ts:51-64`; `currentMissionEpochs` in `apps/dashboard/src/lib/comparison-submit.ts:77-82`; used at `ComparisonSubmitPanel.tsx:109-115` |
| 1.2 | Artifact badges (point-cloud / DSM presence) match selected epochs | `ComparisonSubmitPanel.tsx:44-65`, rendered at `:334`, `:357` |
| 1.3 | Zone confirm is explicit; editing polygon clears confirm; unconfirmed submit skips volume | `ComparisonSubmitPanel.tsx:369-412`; payload builder `comparisonRequestInput` in `apps/dashboard/src/lib/comparison-submit.ts:149-162` |
| 1.4 | Preflight runs on exact submit payload; submit stays blocked until `compatible: true` | `ComparisonSubmitPanel.tsx:132-147`, effect `:151-207`; gate `canSubmitCivilComparison` in `apps/dashboard/src/lib/comparison-submit.ts:225-231` |
| 1.5 | Preflight blocker shows `role=alert` with code + message + next action + evidence detail | `ComparisonSubmitPanel.tsx:464-474`; guidance map in `apps/dashboard/src/lib/comparison-submit.ts:174-222` |
| 1.6 | Submit POSTs BFF then polls; SUCCEEDED links to `/reports?missionId=`; FAILED shows detail; same-combination resubmit reuses request | `handleSubmit` at `ComparisonSubmitPanel.tsx:226-252`; polling at `:214-224`; terminal check `isTerminalComparisonStatus` in `apps/dashboard/src/lib/comparison-submit.ts:25-27`; result block `:496-542` |
| 1.7 | No-permission path shows MISSIONS_ISSUE notice, not the form | `ComparisonSubmitPanel.tsx:254-265` |

Core clients (via BFF, browser never calls Core directly):

- `POST /v1/missions/{missionId}/comparison-preflight` — `apps/dashboard/src/lib/core-api/comparison.ts:71-79`, BFF `apps/dashboard/src/app/api/missions/[missionId]/comparison-preflight/route.ts:12` (same-payload note).
- `POST /v1/missions/{missionId}/comparison-requests` (`ALREADY_REQUESTED` = reuse, not error) — `apps/dashboard/src/lib/core-api/comparison.ts:56-64`, BFF `apps/dashboard/src/app/api/missions/[missionId]/comparison-requests/route.ts`.
- `GET /v1/sites/{siteId}/processing-jobs` (epoch input) — `apps/dashboard/src/lib/core-api/comparison.ts:29-37`.
- `GET /v1/comparison-policy` (display-only fixed thresholds) — `apps/dashboard/src/lib/core-api/comparison.ts:45-47`, rendered at `ComparisonSubmitPanel.tsx:415-442`.
- `GET /v1/missions/{missionId}/comparison-requests`, `GET /v1/comparison-requests/{requestId}` (history / poll restore) — `apps/dashboard/src/lib/core-api/comparison.ts:82-97`, BFF `apps/dashboard/src/app/api/comparison-requests/[requestId]/route.ts`.

## 2. Inspection — independent checkpoint CSV validation (M4-F, optional)

Screen: `apps/dashboard/src/components/missions/CheckpointValidationPanel.tsx`

| Step | What to verify in browser | Wiring pointer |
| --- | --- | --- |
| 2.1 | DSM-epoch dropdown lists only SUCCEEDED jobs with a `dsm` artifact | `selectableCheckpointEpochs` at `CheckpointValidationPanel.tsx:30-46`, used at `:117` |
| 2.2 | Client guards: epoch + file required; `.csv` only; 1 byte–5 MiB; CRS + vertical datum/basis + independence basis + attestation checkbox | `CheckpointValidationPanel.tsx:152-169`, `MAX_CSV_BYTES` at `:20`, format hint at `:308-310` |
| 2.3 | Register → browser PUTs bytes to Core-issued URL (Dashboard never stores raw bytes) → seal; no RMSE input anywhere | `CheckpointValidationPanel.tsx:186-222`; clients `registerCheckpointValidation` / `sealCheckpointValidation` in `apps/dashboard/src/lib/core-api/checkpoint-validations.ts:24-45`; BFF `apps/dashboard/src/app/api/processing-jobs/[jobId]/artifacts/[artifactId]/checkpoint-validations/route.ts` and `apps/dashboard/src/app/api/checkpoint-validations/[validationId]/seal/route.ts` |
| 2.4 | Poll only while `SEALED`; terminal `VALIDATED` / `REJECTED` stop polling | `shouldPollCheckpointValidation` / `isTerminalCheckpointValidation` at `CheckpointValidationPanel.tsx:48-54`, polling at `:140-150` |
| 2.5 | History shows status badge + observed metrics (count/RMSE/MAE/max) or rejection reason + next action; read-only mode shows notice, form hidden | `CheckpointValidationPanel.tsx:379-414`; `statusAppearance` at `:56-69`; `checkpointNextAction` at `:71-84`; read-only at `:253-257`; permission gate `SITES_WRITE` at `:259-263` with `mutationAllowed` at `:138` |

Core clients:

- `GET /v1/processing-jobs/{jobId}/checkpoint-validations` (per-epoch history; page assembles with per-job catch so one failure does not take down the mission page) — `apps/dashboard/src/lib/core-api/checkpoint-validations.ts:15-21`, BFF `apps/dashboard/src/app/api/processing-jobs/[jobId]/checkpoint-validations/route.ts`, assembled at `apps/dashboard/src/app/missions/[missionId]/page.tsx:193-201`.
- `GET /v1/checkpoint-validations/{validationId}` (SEALED poll projection) — `apps/dashboard/src/lib/core-api/checkpoint-validations.ts:48-54`, BFF `apps/dashboard/src/app/api/checkpoint-validations/[validationId]/route.ts`.

## 3. Quantity — design-to-existing remaining volume (M4-A)

Screen: `apps/dashboard/src/components/design/DesignConformancePanel.tsx`

| Step | What to verify in browser | Wiring pointer |
| --- | --- | --- |
| 3.1 | Design-surface dropdown lists only `VERIFIED` surfaces | `conformanceReadySurfaces` via `apps/dashboard/src/lib/design-conformance.ts` (imported at `DesignConformancePanel.tsx:19`); empty path links to `/sites/{siteId}/design` at `:420-430` |
| 3.2 | Current-terrain dropdown lists only this mission's DSM jobs | `designComparableJobs` (same import `:19`), used at `:302`; empty path at `:431-435` |
| 3.3 | Zone is mandatory: registered work-area(s) (recommended) or drawn polygon with explicit confirm; zone-scope badge states "selected-zone only" | `DesignConformancePanel.tsx:484-606`; submit guard `zoneReady`/`canSubmit` at `:389-394`; errors at `:348`, `:354-356` |
| 3.4 | Submit POSTs BFF; same-combination resubmit reuses request; poll is list-then-find (no single-request GET on Core); SUCCEEDED triggers `router.refresh()` to load report | `handleSubmit` at `DesignConformancePanel.tsx:341-386`; polling at `:321-339`; in-progress/failure at `:621-652` |
| 3.5 | Report shows zone cut/fill/net, threshold, policy version, vertical datum + basis, non-settlement disclaimer, heatmap from stored diff raster, plus progress-baseline + change-area links | `ConformanceResult` at `DesignConformancePanel.tsx:167-270`; uncertainty text via `describeVolumeUncertainty` from `apps/dashboard/src/lib/core-api/phase34-labels.ts` (import `:12-16`); heatmap `DiffHeatmapOverlay` at `:235-239` |
| 3.6 | No-permission path shows MISSIONS_ISSUE notice | `DesignConformancePanel.tsx:416-419` |

Core clients:

- `GET /v1/sites/{siteId}/design-surfaces` (unfiltered; panel filters to VERIFIED) — `apps/dashboard/src/lib/core-api/design.ts:33-37`.
- `POST /v1/missions/{missionId}/design-conformance-requests` (`ALREADY_REQUESTED` = reuse) — `apps/dashboard/src/lib/core-api/design.ts:80-88`, BFF `apps/dashboard/src/app/api/missions/[missionId]/design-conformance-requests/route.ts`.
- `GET /v1/missions/{missionId}/design-conformance-requests` (history + poll) — `apps/dashboard/src/lib/core-api/design.ts:96-102`.
- `GET /v1/missions/{missionId}/design-conformance` (404 = "not yet computed") — `apps/dashboard/src/lib/core-api/design.ts:110-118`.
- `GET …/diff-raster` (map must use this stored raster; browser never re-diffs) — `apps/dashboard/src/lib/core-api/design.ts:127-134`, BFF `apps/dashboard/src/app/api/missions/[missionId]/design-conformance/[designConformanceId]/diff-raster/route.ts`.
- `POST …/progress-baseline` (explicit "original terrain" designation; overwritable) — `apps/dashboard/src/lib/core-api/design.ts:143-152`, BFF `…/progress-baseline/route.ts`, button at `DesignConformancePanel.tsx:98-165`.

## 4. Review-followup — confirm/dismiss/assign + evidence (triage)

Screens: `apps/dashboard/src/app/events/[eventKey]/page.tsx`,
`apps/dashboard/src/app/events/[eventKey]/EventActions.tsx`,
`apps/dashboard/src/app/events/[eventKey]/EvidencePanel.tsx`,
queue `apps/dashboard/src/app/events/page.tsx`

| Step | What to verify in browser | Wiring pointer |
| --- | --- | --- |
| 4.1 | Queue tiles/filters use triage SSOT (`isUnattended`, `groupForTriage`, `REVIEW_QUEUES`); row shows triage label | `apps/dashboard/src/app/events/page.tsx:101-112`, `:267-285`, `:341-344`; `apps/dashboard/src/lib/core-api/triage.ts:9-27`, `:136-189`; nav badge `apps/dashboard/src/components/nav/nav-counts.ts:8-39` |
| 4.2 | Detail shows severity/status/triage badges, confirmation actor/ts, journal history (transitions + evidence register/tombstone), expert block | `apps/dashboard/src/app/events/[eventKey]/page.tsx:42-55` (confirmation scan), `:84-91` (journal kinds), `:182-211` (badges + triage gate), `:220-280` (evidence + history) |
| 4.3 | Actions hidden by server transition tables: confirm only from `FINDING`; dismiss hidden when final or `UNRESOLVED`; assign only when `CONFIRMED_EVENT` + triage `NONE`; reason required for confirm/dismiss; every transition carries `expectedBundleDigest` (409 `STALE_EVENT_VIEW` on drift) | `apps/dashboard/src/app/events/[eventKey]/EventActions.tsx:14-24`, `:52-64`, `:89-136`, `:138-166`; submit at `:66-83` via `useMutation` (`apps/dashboard/src/hooks/useMutation.ts`); BFF `apps/dashboard/src/app/api/events/[eventKey]/transitions/route.ts` |
| 4.4 | Evidence register → browser PUT to presigned URL; view URL short-lived; tombstoned = 410 "disposed", not "missing" | `apps/dashboard/src/lib/core-api/events.ts:81-99`; labels `DUPLICATE_ARTIFACT` / `ALREADY_TOMBSTONED` / `CONTENT_DIGEST_MISMATCH` in `apps/dashboard/src/lib/core-api/labels.ts:302-307`; BFF `apps/dashboard/src/app/api/events/[eventKey]/evidence/route.ts`, `…/evidence/[artifactId]/route.ts` |
| 4.5 | `EVENTS_TRIAGE` permission gates action panel + upload; others still see evidence/history | `apps/dashboard/src/app/events/[eventKey]/page.tsx:177-178`, `:207-218`, `:242-252` |

## 5. Typed-blocker display behavior (INV-053 and verdict codes)

- Civil preflight reasons are a closed Core set, never recomputed in clients:
  `apps/dashboard/src/lib/core-api/types.ts:813-824`
  (`ANALYSIS_NOT_READY`, `PROCESSING_PROFILE_UNKNOWN/MISMATCH`,
  `SOURCE_LINEAGE_GAP`, `CRS_MISMATCH`, `VERTICAL_REFERENCE_MISMATCH`,
  `DESIGN_SURFACE_NOT_VERIFIED`, `DESIGN_NORMALIZATION_MISMATCH`).
- `civilBlockerGuidance` preserves `code` separately so an unknown server reason
  renders a fail-closed generic blocker, never a false green state:
  `apps/dashboard/src/lib/comparison-submit.ts:170-222`.
- Malformed/absent blocked reasons and transport failures map to
  `PREFLIGHT_UNAVAILABLE` blockers, never an unexplained disabled button:
  `ComparisonSubmitPanel.tsx:166-207`.
- Readiness projection (`PAIR_BLOCKED` → `차단 · {code}`) reuses the same
  guidance map without recomputing the decision:
  `apps/dashboard/src/lib/civil-readiness.ts:58-67`.
- Verdict → Korean copy SSOT: `API_ERROR_MESSAGE` in
  `apps/dashboard/src/lib/core-api/labels.ts:285-372`; lookup with status
  fallbacks (401/403/404/503) + server-message last resort in
  `humanizeApiError` at `:374-387`.
- Browser-facing failure shape differs by layer (`verdict` on success,
  `{code, message, detail, reasonCode}` on BFF errors, `{message}`-only on
  origin guard); `readableApiError` priority is known-code copy → server
  message → raw detail → fallback:
  `apps/dashboard/src/lib/core-api/labels.ts:389-423`.
- `CoreApiError` captures `code` (verdict or `detail`-embedded `CODE`,
  `CODE — msg`, `CODE: msg`), `serverMessage`, `reasonCode`, and
  `retryAfterSeconds`: `apps/dashboard/src/lib/core-api/client.ts:26-75`.
  BFF forwards all four: `route-handler-util.ts:19-28`.
- `RESOURCE_LIMIT_EXCEEDED` appends a stable `reasonCode` next action
  (never the raw policy): `processingResourceLimitNextAction` in
  `apps/dashboard/src/lib/processing-resource-policy.ts:44-60`,
  composed in `SourceUploadPanel.tsx:303-313`.
- `EGRESS_NOT_ALLOWED` (vendor-cloud processing blocked by site policy):
  copy `"이 현장은 데이터 반출이 허용되지 않아 벤더 클라우드 처리를 만들 수 없습니다."`
  at `apps/dashboard/src/lib/core-api/labels.ts:330`, grouped there under the
  source-media / processing-jobs verdicts (`labels.ts:323`).
  Originating browser surface is the photo-upload / reconstruction issuance
  path: `handleIssue` in
  `apps/dashboard/src/components/missions/SourceUploadPanel.tsx:294-328`.
  Layer note: the browser never calls Core directly — it `fetch`es the BFF
  (`SourceUploadPanel.tsx:298`,
  `POST /api/missions/{missionId}/processing-jobs`); the BFF route calls the
  server-only helper `issueProcessingJob`
  (`apps/dashboard/src/lib/core-api/processing-jobs.ts:16-24`, `server-only`
  module) in
  `apps/dashboard/src/app/api/missions/[missionId]/processing-jobs/route.ts:24`
  and maps Core errors via `coreApiErrorResponse` (`route.ts:27` →
  `route-handler-util.ts:19-28`). The browser renders the BFF failure with
  `readableApiError` (`SourceUploadPanel.tsx:308`) into the panel error block
  at `SourceUploadPanel.tsx:380-384`.
  Browser check: trigger issuance on a no-egress site, assert the Korean copy
  appears in that error block, assert no raw `EGRESS_NOT_ALLOWED`
  string and no internal journal/storage wording is shown.
  Query note: that error block is a plain `<p>` with no `role` — locate it by
  text match on the Korean copy, not by `role=alert`.
  The three civil panels (§§1–3) share the generic
  `humanizeApiError`/`readableApiError` path (`labels.ts:374-423`), so their
  `role=alert` blocks (`ComparisonSubmitPanel.tsx:289-296`,
  `DesignConformancePanel.tsx:407-414`,
  `CheckpointValidationPanel.tsx:265-269`) would render this copy
  renders-if-returned — reachability there is not claimed; verify only the
  originating surface end-to-end.

## 6. Missing links for full browser verification (gaps)

1. Live preflight matrix: automated specs do not cover each INV-053 reason +
   unknown-reason + `PREFLIGHT_UNAVAILABLE` rendering in `ComparisonSubmitPanel.tsx:464-479`.
   Needs seeded pair states per `types.ts:813-824` plus one unmapped reason.
2. `EGRESS_NOT_ALLOWED` end-to-end on the originating surface: no existing e2e
   asserts the Korean copy at `labels.ts:330` via the BFF error path. Needs a
   no-egress site fixture driving reconstruction issuance
   (`SourceUploadPanel.tsx:294-328`, error block `:380-384` — plain `<p>`,
   assert by text match) and a negative assertion on raw code
   display.
3. Checkpoint happy path in a real browser: register → presigned PUT → seal →
   `SEALED` poll → `VALIDATED`/`REJECTED` history at
   `CheckpointValidationPanel.tsx:186-222`, `:379-414`. File input + crypto
   (`sha256Hex` at `:90-95`) + storage PUT make this the highest live-run value.
4. Quantity report rendering: `VERIFIED`-only filter, mandatory-zone guard,
   `router.refresh()` report load, heatmap-from-stored-raster, and
   progress-baseline designation at `DesignConformancePanel.tsx:321-339`,
   `:654-662`, `:235-239`, `:98-165`. No e2e covers this panel.
5. Review-followup transitions: confirm-from-`FINDING`, dismiss-hidden states,
   assign-gated-on-`CONFIRMED_EVENT`+`NONE`, reason-required, and 409
   `STALE_EVENT_VIEW` (`EventActions.tsx:52-83`; label at `labels.ts:290`).
   Needs two-tab staleness run.
6. `RESOURCE_LIMIT_EXCEEDED` + `reasonCode` next-action composition in
   `SourceUploadPanel.tsx:303-313` with per-`reasonCode` copy from
   `processing-resource-policy.ts:44-60`.
7. Permission-gated rendering matrix: `MISSIONS_ISSUE` (submit §1.7 / quantity
   §3.6), `SITES_WRITE` (inspection §2.5), `EVENTS_TRIAGE` (review §4.5).
8. Cross-links after success: comparison → `/reports?missionId=`
   (`ComparisonSubmitPanel.tsx:520-525`); quantity → progress/changes links
   (`DesignConformancePanel.tsx:243-267`); mission → site/design/work-areas
   links. Assert hrefs resolve, not just render.

## 7. Online / local / offline variant notes

- Online (full Core + storage + worker): run §§1–4 happy paths to terminal
  states; assert polling stops (`isTerminalComparisonStatus`,
  `isTerminalCheckpointValidation`, design poll at
  `DesignConformancePanel.tsx:317-339`); assert `ALREADY_REQUESTED` reuse on
  identical resubmit (§§1.6, 3.4).
- Local (Core reachable, workers/storage degraded): assert fail-closed copy —
  `PREFLIGHT_UNAVAILABLE` (§1.4), `STORE_UNAVAILABLE` / `EVIDENCE_STORAGE_UNAVAILABLE`
  (`labels.ts:299`, `:308`), `503` + `Retry-After` countdown via
  `CoreApiError.retryAfterSeconds` (`client.ts:45-50`; `ErrorState` countdown),
  `POLICY_READ_FAILED`/`CURRENT_POLICY_UNDECLARED/UNKNOWN`
  (`processing-resource-policy.ts:7-26`) blocking new issuance while history
  stays readable (`page.tsx:180-185` pattern).
- Offline / unreachable Core (browser run against stopped Core): assert every
  surface shows fallback copy, never a raw stack or empty disabled button —
  comparison preflight catch (`ComparisonSubmitPanel.tsx:193-204`), submit catch
  (`:247-248`), quantity catch (`DesignConformancePanel.tsx:381-382`),
  inspection catch (`CheckpointValidationPanel.tsx:225-226`), report 404-as-empty
  (`reports/page.tsx:33-57`), mission-page section isolation
  (`app/missions/[missionId]/page.tsx:121-186`). Record which sections stayed
  readable vs. blocked; that split is the offline result.
- Auth/session variants (all networks): `MISSING_SESSION` 401 before Core is
  hit (`route-handler-util.ts:11-18`); 401/403 copy via `humanizeApiError`
  (`labels.ts:380-381`); cookie-isolation spec must stay green
  (`e2e/auth-cookie-isolation.spec.ts`).

## 8. Run record (fill in by hand — no secrets)

- Date / build / branch:
- Core URL origin (host only, no token):
- Site / mission / event IDs used:
- Variants run (online / local-degraded / offline):
- Gaps closed (map to §6 numbers) / still open:
- Typed blockers observed (codes only, e.g. `CRS_MISMATCH`, `EGRESS_NOT_ALLOWED`):
- Screenshots / logs (local paths only):

## 9. Escalations (stop and return to Build)

- Any dashboard source change looks required — this checklist authorizes
  verification only (`docs/ops/BROWSER_E2E_CHECKLIST.md` is the sole writable path).
- A live browser run, seeded fixture, or credential is needed.
- A cited path/line has drifted, a verdict code is unmapped, or an unknown
  blocker renders as green/silent.
