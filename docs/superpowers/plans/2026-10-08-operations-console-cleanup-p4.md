# KSI Operations Console cleanup — implementation plan (P4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Visual work is design-workspace-owned**: the OpenDesign local execution performs the Console source edits and the rendered review; Build coordinates, verifies functionally and owns Git.

**Goal:** Bring the KSI Operations Console in line with the post-P3 platform: retire every screen, route, navigation entry and API proxy that points at archived acquisition functionality, keep the platform surfaces (auth, sites, observations/changes/analysis, spatial assets, work orders, external results, reports) fully working against the platform Core, and record design-owned rendered review evidence (RB-07).

**Architecture:** The P3 archive removed the acquisition Core endpoints (missions, capability, edge/events, equipment, copilot/workspace, managed processing, comparison/design-conformance/region requests, report-exports). The Console (`apps/dashboard/`, Next.js) still ships screens/proxies for them. This plan retires those surfaces inside the existing Console (no new visual direction, brand/tokens preserved) and verifies the surviving flows against the real platform server.

**Tech Stack:** existing Next.js app (`apps/dashboard/`), existing npm lock and CI dashboard job (tsc/eslint/vitest/next build); OpenDesign local execution on the existing "KSI Operations Console" project (`6edb22d8-bd56-43df-9e13-521a30700925`, `resolvedDir=/home/ksi/Desktop/KSI-Projects/KSI-Site-Intelligence-Platform/apps/dashboard`, scenario plugin `od-code-migration`); Playwright for functional flow checks. No new dependency, no backend change, no deployment.

**Spec:** [Human-approved Physical Site rebaseline](../specs/2026-10-07-physical-site-platform-rebaseline-design.md) §8 stage 4 + RB-07; ADR-KSI-039; P3 plan deferred successor; dashboard-local rules in `apps/dashboard/AGENTS.md` (**read `node_modules/next/dist/docs/` before editing any dashboard code** — this Next.js version differs from training data).

**Status:** DRAFT FOR WRITTEN REVIEW; not implementation authorization. Base: main `89d4187` (P3 technical closure). Discovery inputs recorded below.

## Global Constraints

- Platform behavior preserved: auth (login/OIDC), sites, work areas, observation work orders, external result surfaces (relative-volume/single-volume reports, reviews, proposals), spatial-asset catalog, data/analysis screens, reports. No backend/API contract change; the Console only consumes the existing platform routes.
- No new visual direction: keep the approved brand/tokens/components; this is route/navigation/action cleanup, not a restyle. Substantial layout improvements, if any, must be driven by observed user-task friction and are design-workspace decisions with their own evidence.
- One writer per file: the design run owns `apps/dashboard/**` edits; Build does not patch Console visuals. Build owns functional verification, browser checks and Git.
- Retired routes must 404 (or redirect to a surviving surface) and leave no dead links in nav, home briefing, command palette or reports; no hidden "coming soon" pointing at archived features without an explicit label.
- Design-owned rendered review is required before completion: a review run distinct from the generator, fed with the actual rendered states (390/768/1440 + empty/error/loading + keyboard/focus + accessibility + motion), returning a defect list (what/where/impact/desired), tracked fixed/open with render evidence. Tests/build green alone do not prove design quality.
- Evidence is local-only: no customer data, no credentials; generated/owned fixtures only. No push/publish/deploy; no new dependency; no host/OD-container changes.
- Human written-plan review of this document is the execution gate; afterwards the established sequential method continues (design run → functional verification → rendered review → independent closure).

## Review Focus

1. No dead ends: after cleanup, every nav entry, home card, command-palette item and report link resolves to a surviving screen; retired URLs return 404/redirect deliberately (Playwright asserts both directions).
2. Surviving flows still work end-to-end against the real platform server: login → sites list → site workspace (observations, changes/analysis, spatial assets) → reports; work-order and external-result surfaces render real data with auth, and revoked/missing data shows typed empty/error states (not blank or stale).
3. Mobile/desktop integrity: 390px bottom nav + scroll depth, 768/1440 layouts, keyboard focus order and skip behavior unchanged for surviving screens.
4. Brand/tokens preserved: no accidental restyle; typography/color/spacing tokens unchanged except where a retired screen's removal requires layout flow fixes (design-reviewed).
5. Design-review evidence covers the actual rendered product (not prototypes): before/after captures at the target viewports, defect list with fixed/open status, and a review run that demonstrably read the real screens.

## Discovery at this base (verified)

- Nav (`src/components/nav/nav-items.ts`): primary 홈 `/`, 현장 `/sites`, 작업 `/field`, 확인 항목 `/events`; support 비행 임무 이력 `/missions`, 장비 연결·지원 상태 `/settings`, Dock·Edge 지원 범위 `/coming-soon/fleet`; mobile adds 더보기 `/more`.
- Screens/route dirs: `missions/**`, `field/**` (readiness, copilot, team, inbox, missions; work-orders = platform anchor), `hil/**`, `world/**`, `events/**`, `sites/[siteId]/{ai,progress,surveys,design}` (mixed), `coming-soon/**`, `reports/**`, `sites/**` (platform), `login`, `settings`, `more`, `portfolio`.
- API proxies (`src/app/api/*`): retire `checkpoint-validations`, `comparison-requests`, `copilot`, `events`, `mission-plans`, `missions`, `processing-jobs`; keep `auth`, `health`, `sites`, `observation-work-orders`, `organization-work-roster`, `work-inbox`, `external-relative-volume-reports`, `external-reobservation-proposals`, `external-result-reviews`, `external-single-volume-reports`.
- Lib modules referencing retired endpoints (48 files total, incl.): `lib/core-api/{copilot,copilot-conversations,missions,mission-plans,processing-jobs,processing-resource-policies,region-extraction,comparison,design,acquisition-connectivity,acquisition-coordination,phase34,report-exports,source-media}.ts`, `lib/design-conformance.ts`, `lib/processing-resource-policy.ts`, report/map/design/missions components (`components/reports/ReportExportControls.tsx`, `components/map/*Diff*`, `components/design/DesignConformancePanel.tsx`, `components/missions/ComparisonSubmitPanel.tsx`, `site/ReobsSuggestions.tsx`), `app/field/**` cards/panels, `app/sites/[siteId]/{ai,report,changes,design}/**`.
- Dashboard CI job: `npm ci` → tsc → eslint → vitest (pure logic) → `next build`; e2e fixture `apps/dashboard/e2e/fixtures/seed_operations_console.py` imports archived modules (P4-owned).
- Design workspace: OpenDesign project "KSI Operations Console" bound to the real folder; previous run status `failed` (stale snapshot `89128fb1…`); no active context (use explicit project id).

## File structure and ownership

- Design-owned (OpenDesign run): all `apps/dashboard/**` source edits (screens, routes, proxies, components, lib, nav, tests, e2e fixture) + `apps/dashboard/README` if needed.
- Build-owned: this plan's decision table (committed under `docs/audit/` as needed), functional verification scripts/evidence, Git commits, ledger/checkpoint/product-state.
- No edits: platform backend, contracts, archive, other apps.

## Task 1: Decision inventory and scope contract (Build; mostly complete via discovery)

**Files:** Create `docs/audit/P4_CONSOLE_CLEANUP_DECISIONS.md` (per-screen/route/nav/proxy disposition: KEEP / RETIRE / REPOINT with reason and the surviving replacement). No app edits.

- [ ] Finalize the disposition table from the discovery above (every nav item, route dir, API proxy, lib module, component with retired references): KEEP (platform), RETIRE (archived backend), REPOINT (e.g., 작업 `/field` → a surviving work-order-centric surface; 확인 항목 `/events` → a surviving review surface if one exists, else retire).
- [ ] Verify each KEEP screen's API calls against the platform route set (grep the actual endpoints; no KEEP screen may depend on a retired route).
- [ ] Commit the decision doc; carry it as the design run's scope contract.

## Task 2: Console cleanup execution (design workspace, OpenDesign local run)

**Files:** `apps/dashboard/**` per the decision table; the run report + source diff.

- [ ] Preflight: verify inner file access to the real folder (write probe) and record it; confirm the run reads `apps/dashboard/AGENTS.md` + the version-specific Next.js docs; use the explicit scenario plugin; state the preserved brand/tokens and the target viewports/states in the brief.
- [ ] Execute the cleanup: retire the decided screens/routes/proxies/lib modules; repoint or remove nav/palette/home links; keep surviving flows intact; no restyle beyond what removal requires; run the dashboard's own checks (`tsc`, `eslint`, `vitest`, `next build`).
- [ ] Produce the run report (what changed per decision row, before/after captures at 390/768/1440 for changed screens, any friction-driven layout decisions) + the source diff for review.

## Task 3: Functional verification (Build)

**Files:** verification scripts/evidence only.

- [ ] Run the dashboard CI equivalents locally (`npm ci` only if node_modules missing; `npx tsc --noEmit`, `npx eslint .`, `npm test`, `npx next build`) and record counts.
- [ ] Serve the platform Core (P2 platform profile with generated fixtures) + the dashboard dev server; Playwright flow at 390/768/1440: login → sites → site workspace (observations, changes/analysis, spatial assets) → reports; work-order detail; external-result surfaces; assert retired routes 404/redirect and no dead links in nav/home/palette; capture console/network failures; save before/after screenshots.
- [ ] Verify persistence/reload behavior for the changed flows (auth reload, direct URL entry to surviving screens).
- [ ] Record exact commands/results and any blocker honestly (no customer/operational claim).

## Task 4: Design-owned rendered review (OpenDesign local run, review skill ≠ generator)

**Files:** review report + evidence (screenshots); fixes applied by the design run; Build re-verifies affected checks.

- [ ] Feed the review run the ACTUAL rendered states from Task 3 (target viewports + empty/error/loading + keyboard/focus + a11y + motion states) and the decision table; require a concrete defect list (what/where/impact/desired) and a verdict per surviving screen.
- [ ] Apply the accepted fixes in the Console; track defect → fix → render evidence → fixed/open; re-run Task 3's affected checks after any fix.

## Task 5: Independent closure and reconciliation (Primary + independent agents)

- [ ] Fresh whole-P4 review (read-only) over the Console diff; independent test-runner re-runs the dashboard checks + the Playwright flow on the final revision; record revision/hashes/commands/results.
- [ ] RB-07 evidence bundle: product link (tailnet-only/temporary label if local), before/after screenshots at target viewports, design preview/review links, defect list fixed/open.
- [ ] Reconcile ledger/checkpoint/product-state; report the P4 technical level; P5 whole verification follows.

## Deferred successor and rollback

P5 proves whole RB-01..09 and selects remaining first-user-flow gaps; real customer/operational acceptance stays external. Rollback is a reviewed inverse of the Console commits (design-run changes are ordinary source edits); no backend/archive/data change is involved. If the design workspace is unavailable or lacks write access to the real folder, record the UI stage blocked with the exact probe evidence and continue independent nonvisual work (no substitute Build-side visual patches).

## Self-review / approval gate

RB mapping: RB-07 → Tasks 2–5 (changed Console flow + rendered review); RB-04/06 preserved (surviving flows verified in Task 3); RB-08 untouched. Review Focus 1–5 each have owner tasks and assertions. Discovery rows are evidence-backed at base `89d4187`. Human written-plan review is the execution gate; after approval the design-run → verification → rendered-review → independent-closure sequence continues without per-step re-approval.
