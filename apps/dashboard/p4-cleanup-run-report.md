# P4 Operations Console cleanup — run report

Date: 2026-10-08  
Scope: Dashboard-only execution of [`../../docs/audit/P4_CONSOLE_CLEANUP_DECISIONS.md`](../../docs/audit/P4_CONSOLE_CLEANUP_DECISIONS.md) under the approved P4 plan. No backend, contract, archive, other-app, dependency, credential, customer-data, or Git-commit changes were made.

## Preflight and source boundary

- The real-folder write probe `.od-probe-20261008T090306Z-2` was created, verified, and removed in the actual Dashboard checkout. Probe SHA-256: `ffa56c3d70e5617b78d6b66a7b66786108905161252cd7e7e5c81c98c962cb81`. No detached copy was used.
- Read `apps/dashboard/AGENTS.md`, the parent repository instructions, and the installed Next.js 16.3.3 guide at `node_modules/next/dist/docs/` before editing. Followed the app's current Next conventions; left the generated AGENTS block and TypeScript configuration untouched.
- `node_modules` already existed, so no install was attempted. The working tree contains Dashboard changes and an unrelated pre-existing untracked `../../.claude/`; that external path was not touched.

## Disposition results

| Contract rows | Applied disposition |
|---|---|
| §3a Navigation | `/events`, `/missions`, and `/settings` acquisition-era entries removed. Home, sites, field work, and the static fleet support-scope entry remain. `/more` continues to derive its entries from the shared navigation, so the palette and mobile menu inherit the same surviving destinations. |
| §3b Routes | Retired route trees removed: events, missions, assets, reports, world, HIL pilot bridge, site AI/design/survey creation, and field mission detail. Home, sites, site workspace, field work, and work-order detail were repointed to mounted platform calls. Site progress and changes/report legacy paths now redirect to surviving spatial-assets/site surfaces. |
| §3c API proxies | Removed proxies for checkpoint validation, comparison, copilot, events, mission plans/missions, processing jobs, design progress/surfaces, site copilot, and retired report exports. Kept auth, site, work-order, external-result, roster, inbox, and health routes. |
| §3d Core API and helpers | Removed unmounted acquisition, mission, event, copilot, managed processing, design, checkpoint, comparison, and report-export clients/helpers. Removed the unmounted `sites.ts` spatial-model function and retired work-order mutation functions; retained mounted draft reads and external proposal operations. Kept `siteAutonomyGate.ts` because `SiteTransitionActions` still imports it; removed unused `surveyEntryPreset.ts` after the survey route retired. |
| §3e Components and surviving calls | Removed managed-era event, mission, acquisition, copilot, checkpoint, design-conformance, diff-map, and report-export components. Site/work-order screens now use mounted site/work-area/analysis/observation/external-result APIs; stale acquisition readiness/progress and site-briefing calls were removed. External observation links now lead to the surviving observations history. |
| Fixture and tests | Removed acquisition-era seed data and updated the platform console smoke coverage and focused unit tests to the surviving site/work-order/external-result flows. Retired route assertions remain in the P4 capture/e2e spec. |

The final source grep found no active KEEP-screen calls to the retired Core endpoints and no retired URL links in `src` navigation/page code. Remaining retired-path text is in the deliberate `/hil/*` 404 guard, pure legacy DTO documentation in `src/lib/core-api/types.ts`, and an old comment in `src/components/map/AoiPolygonMapInner.tsx`; none is a live call or link. `PrintReportButton` remains because the surviving observation report detail imports it.

## Verification and evidence limits

| Check | Result |
|---|---|
| `npx tsc --noEmit` | The wrapper attempted registry resolution in this environment and could not complete. Equivalent existing local binary `./node_modules/.bin/tsc --noEmit --pretty false` passed with exit 0. |
| `npx eslint .` | Wrapper could not complete registry resolution. Equivalent existing local binary `./node_modules/.bin/eslint .` passed with exit 0 (10.5 s). |
| `npm test` | Not green: existing Vitest startup fails before collecting tests because `@rolldown/binding-wasm32-wasi` is absent. No dependency install or test weakening was attempted. |
| `npx next build` | Not green: installed SWC binary is incompatible with this runtime (`__res_init` missing; WASM fallbacks absent). The build exited before application compilation. |
| Before/after browser captures at 390/768/1440 | Not produced. The local browser harness could not reach the required listener in this execution environment, and there was no verified existing server. No screenshots or live data were fabricated. |
| Core endpoint and call-site grep | Completed for `src/lib/core-api`, API proxies, and surviving app/components. No active retired endpoint call surfaced. |

Thus source-level cleanup and local type/lint checks are evidenced, while unit-test, build, and rendered-flow acceptance remain open. The screenshots section is intentionally empty: there are no capture files to cite.

## §6 handoff questions — resolutions used

1. **Retired URL targets:** use deliberate 404s when the route tree is removed; retain redirects only for the existing changes/progress/report paths that have a named surviving site destination.
2. **Progress copy:** no new typed-empty state was introduced; the route redirects to the existing spatial-assets surface.
3. **`surveyEntryPreset.ts`:** removed because its only screen caller retired.
4. **`siteAutonomyGate.ts`:** retained because the surviving `SiteTransitionActions` imports it.

## Open blockers

- The outer test runner must rerun the requested four checks in its configured environment; Vitest dependency resolution and SWC compatibility are environment blockers here, not passing checks.
- The outer functional runner must capture before/after states at 390/768/1440 and exercise the surviving flows and retired-route responses against the approved fixture setup. This report does not claim browser, screen-reader, device, customer, field, product-accuracy, or operational acceptance.
- A design-owned rendered review remains a distinct follow-on and must use those actual captures before visual-quality closure.

## Refinement round

The P4 retirement work above remains in place. This round restores the three approved KEEP/REPOINT surfaces and updates only their directly affected expectations:

| Screen / test scope | Restored structure | Retired-source strips and repoints |
|---|---|---|
| Home (`src/app/page.tsx`) | Restored the approved attention carousel, situation list, recent updates, and initial-setup area hierarchy, including the `전체 N곳 · 확인 필요 M곳` status line. The Home attention and recent-site projections remain site-deduplicated. | Removed event/evidence-preview and briefing reads; the Home projections now use sites, external pending decisions, work orders/operations, and operator next-action data. The unattended headline uses the surviving unread work inbox and reports unavailable when that read fails. `home-operations.ts` selectors are based on surviving inputs only. |
| Sites list (`src/app/sites/page.tsx`) | Restored the desktop comparison table, filters, responsive list, and F08 single `현장 열기` row action. | Removed mission/event-derived badge cells and their retired calls. |
| Site detail (`src/app/sites/[siteId]/page.tsx`) | Restored a tabbed site workspace with five surviving platform tabs: observations, analysis, spatial assets, work orders, and external results. | Removed briefing, event/review, mission, design, progress, and survey sections and calls. Observations, analysis, spatial assets, work orders, and external-result history point to their surviving mounted surfaces; work-area, work-order, AOI/state, and external-history reads use mounted APIs. `site-epochs.ts` normalizes legacy tab names to surviving tabs. |
| Direct expectations | Updated the Site tab, table/F08, retired `/field/M-1` back-button, chromeless, and accessibility-shell expectations; deleted the evidence-panel wiring test for the retired subject. | Source-level checks also assert that retired site event/mission feeds are absent. |

| Refinement validation | Result |
|---|---|
| `./node_modules/.bin/tsc --noEmit` | Passed (exit 0). |
| `./node_modules/.bin/eslint .` | Passed (exit 0). |
| Focused Vitest run for the updated Home, site, shell, and tab tests | Could not start: the installed Rolldown dependency cannot load its WASI binding. No dependency was installed and no test was weakened to mask the environment failure. |
| `git diff --check` | Passed before the report append; rerun after this update. |

Open items remain the outer test runner's Vitest execution and actual 390/768/1440 captures of the refined screens. The original report's build, browser, and rendered-review limitations remain unchanged. This source refinement does not claim visual closure, device/screen-reader acceptance, or product/field/customer acceptance.

## Functional recovery round — generated OIDC fixture flow

### Source access and scope

- Repeated the real-folder write probe in this Dashboard checkout (`.od-probe-20261008-functional-recovery-01`), read it back successfully, and removed it. No copy or alternate checkout was used.
- Re-read the Dashboard-local and parent instructions and installed Next.js route/metadata guidance before editing. The existing `generateMetadata` in `src/app/sites/[siteId]/page.tsx` uses cached `getSite` and `siteDetailDocumentTitle`; it preserves the expected site-name document title and was left unchanged.
- This round changed only the Dashboard fixture, local-stack wrapper, E2E specs, and this report. The Core runner implementation, contract tests, screenshot baselines, server state, and credentials were not changed.

### Root cause and bounded fixture correction

The local-admin account resolves to `org-local-pilot`, whose default explicit site/area grants are empty. Empty site/work-order reads and site 404 are the intended scoped behavior. The approved generated-seed Core mode grants only the five named E2E sites and matching `wa-{site}-0001` work areas to that organization; the Dashboard wrapper now passes `--oidc-operations-console-e2e` only when `--seed-operations-console-e2e` is present. Ordinary local/staging invocation does not receive this opt-in. No default grants, product permissions, authentication behavior, or token handling were changed.

The fixture still seeds five synthetic sites and areas. It retains exactly four managed-mode work orders, labeled `E2E 과거 읽기 전용`, solely for historical read-only and fail-closed coverage. It creates exactly one additional `EXTERNAL_RECONSTRUCTION` order named `E2E 외부 산출물 등록` with an explicit unique idempotency key. The store creates its `APPROVED` state and `OPEN` operations record atomically; the fixture does not invoke managed approval/status transitions for it and does not create a mission, processing job, report reference, or claimed measurement result.

### Dashboard E2E contract updates

- `e2e/operations-console.spec.ts` checks Home’s two decision cards because only the awaiting-approval and review-ready historical records are actionable. It checks the four historical labels, the external order in field and site workspace, site document title, reload persistence, external registration/operations UI, and mobile laptop-required behavior. It retains the no-managed-controls and no-fabricated-success assertions.
- External-result history accepts either its typed unavailable state or typed empty response; the local workflow is not configured, so this does not infer a zero-pending result.
- `e2e/empty-organization.spec.ts` verifies the typed no-work state, its single site next action, absence of retired event/mission/filter controls, and intentional `/events` 404.
- `e2e/p4-cleanup-capture.spec.ts` records the disabled `/hil/pilot-bridge` response as a bodyless 404, including status/path/body-byte count and whether browser navigation rejected it. Surviving screens still require a visible, nonempty main region; other retired paths require a 404 or redirect. Screenshot baselines were not changed and the capture suite was not launched here.

### Verification and remaining evidence

| Check | Result |
|---|---|
| `./node_modules/.bin/tsc --noEmit --pretty false` | Passed (exit 0). |
| `./node_modules/.bin/eslint .` | Passed (exit 0). |
| `node --check scripts/run-local-oidc-stack.mjs` | Passed (exit 0). |
| Python AST parse of `e2e/fixtures/seed_operations_console.py` | Not run: neither `python` nor `python3` is available in this shell, and no repository virtual-environment interpreter was present at the checked locations. |
| `git diff --check` | Passed (exit 0). |
| Browser E2E, signed-OIDC assembly test, actual-server captures | Not run here; this turn did not launch or replace the host-owned runtime. The outer Build runner owns the Core runner and contract test, and host loopback availability is not assumed. |

Dashboard TypeScript/lint/JavaScript syntax and diff-whitespace checks passed. Fixture execution, signed-OIDC authorization assembly, live 390/768/1440 captures, screenshot comparison, and end-to-end UI acceptance remain unverified. This report makes no auth/customer/product/field/accuracy/operations or visual-closure claim.
