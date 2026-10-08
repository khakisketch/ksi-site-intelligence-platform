# Whole-P4 engineering review — read-only (Task 5, first pass on frozen post-T4-Round2 package)

Reviewer: independent read-only subagent. No implementation, no live-repo mutation, no stack/browser operation, no installs, no spawned agents. All paths below are the immutable package `/tmp/opencode/p4-resume-20261008/whole-p4-review-v1/` (`source/<repo-path>`, `retired-baseline/<repo-path>`); the live repo was not read or touched.

## Diff range / revision reviewed

- BASE `89d4187` (P3 closure) → HEAD `9a3bab1ba710d0c8925cf3ae8bd8e301e425a9cf` + task-owned pending P4 (from `snapshot.json`: `base 89d4187`, `head 9a3bab1…`, `pending true`, `sourceState post-T4-round2`).
- `p4.diff` (tracked diff, 1,270,989 bytes, 209 files) + untracked-source additions inspected directly in `source/` (`tests/contract/test_core_dev_platform.py`, `apps/dashboard/e2e/p4-cleanup-capture.spec.ts`, `apps/dashboard/e2e/fixtures/site-workspace.ts`, `apps/dashboard/src/app/sites/new/SiteRegistrationOnlyWizard.tsx` — confirmed present in `source/` but absent from `p4.diff`).
- `snapshot.json` binds 520 current records (364 sha entries counted) + deleted-baseline byte recovery in `retired-baseline/`.
- Basis: P4 plan `source/docs/superpowers/plans/2026-10-08-operations-console-cleanup-p4.md` (approved SHA `c7fd91df…`), parent spec `…/specs/2026-10-07-physical-site-platform-rebaseline-design.md` (SHA `14ded50b…`), scope contract `source/docs/audit/P4_CONSOLE_CLEANUP_DECISIONS.md` (§1 PROFILE route inventory as RETIRE/KEEP authority, §7 test retirements, §8 OrthophotoOverlay correction).
- Evidence in package: `independent-python-receipt.md` (Test Runner `ses_ee453090`, FULL 6013 passed/30 skipped/0 failed, scoped 82/OIDC 74/Ruff/mypy clean, ambient 0002), `dashboard-commands.json` (tsc/eslint/vitest/build exit 0), `e2e.log` (63 pass/10 fail/15 skip across 4 projects), `capture-checks.json` (68 rows, all settled, `pageErrors []`, overflow 0, expected optional-workflow 404s recorded).
- KNOWN-OPEN design-owned closure (design run `a3547beb` in flight, final delta to be supplied to this same session before closure): analysis H1/title, duplicate denied H1, desktop CTA selector ambiguity, 4 Home baseline adjudications. Findings 1–4 below record their *engineering consequences* only; they are not fresh unknowns and no fix is implemented here. Baselines unmodified; no automatic refresh (verified: zero `update-snapshot` hits in `e2e.log`).

## Verified correct (sampled to file:line, no defect found)

- **Retirement authority respected.** Retired route dirs (`missions/`, `events/`, `world/`, `reports/`, `assets/`, `settings/`, `hil/`) absent from `source/`; KEEP proxies present (`api/observation-work-orders/`, `api/sites/`). Stale-import grep over `source/apps/dashboard/src` finds only benign hits: `home-external-decision.ts:2` imports `phase34-labels` (pure KEEP labels, §3d) and two `/api/events` mentions in `types.ts` comments (see Minor-3). No surviving screen imports a retired lib/proxy.
- **Fn-level retirements applied.** `observation-work-orders.ts` retains only mounted calls incl. `listReobservationDrafts` GET (`:144-151`); approve/`POST reobservation-drafts` fns gone. `sites.ts` has no `spatial-model` fn; `cached.ts` has no event/mission helpers. `sites/page.tsx` shows no mission/event badge reads (only site-status `StateBadge`).
- **Auth/session/RBAC/tenant preserved.** `proxy.ts` has no P4 diff; the `resolve-session.ts` diff removes only comments — the non-`OPERATOR` device-token guard is intact (`source/…/resolve-session.ts:26-34`). `field-session.ts` classification unchanged. Denied-site nondisclosure holds: `not-found.tsx:8-9` generic copy, empty-org E2E asserts zero name disclosure (passes). `nav-counts.ts` fails to *unshown*, never to 0 (INV-040). OIDC stack binds `127.0.0.1` hardcoded, secrets `0600`, S3 all-or-nothing (`run-local-oidc-stack.mjs:91-96`).
- **Seed/dev-stack scope.** `seed_operations_console.py:34-40` grants exactly the five literal E2E sites; `:69-78` refuses non-empty ledgers (fail-closed mix prevention); `:218-231` sole executable fixture is the `EXTERNAL_RECONSTRUCTION` APPROVED/OPEN order; four managed records are historical read-only with non-evidence status reasons (`:213`). No Mission/ProcessingJob fabrication. S3 flags accepted-but-ignored with compatibility comment (`:58-62`).
- **Storage fail-closed.** `source/scripts/run_core_dev.py:111-131` `_UnavailableEvidenceStorage` raises `EvidenceStorageError` on all five ops before any network/S3; S3 constructed only when both flags present (`:289-292`). New `test_core_dev_platform.py` cases read in full (`:105-319`): opt-in scope asserts exact 5 sites / 5 orders / 1 external APPROVED with empty mission/processing-job ids / OPEN ops / exact work-area id; default+empty-org assert `{"sites": []}` + 404s (INV-060); 6-case retired-route absence control uses a generated ADMIN and asserts whoami/sites 200 with each retired read+mutation 404 — a genuine non-vacuous replacement for the retired TS mirrors, not mock-only. Byte-recovery SHAs for the two retired sync tests match the receipt (`c850916b…`, `bae937eb…`).
- **Orthophoto §8 correction validated against baseline bytes.** `retired-baseline/…/map/OrthophotoOverlay.tsx` docstring names `/api/processing-jobs/{jobId}/artifacts/{artifactId}/download` (dead managed route) — retirement is correct cleanup. Current source has zero `OrthophotoOverlay` references; the surviving sanitized path goes through the mounted display-artifact download (`external-reconstruction.ts:113`, `ExternalSanitizedOrthophotoInner.tsx:45-56`) with explicit no-numeric-claim copy (`ExternalSanitizedOrthophoto.tsx:38`).
- **Access-first error separation (T4-ANALYSIS-ROUTE-02 fix present).** `analysis/page.tsx:23-32`, `observations/page.tsx:35-41`, site detail `:60-69`, work-order detail `:28-34` all resolve the scoped Site first; only Site-404 calls `notFound()`; child 404/403 yield typed unavailable/permission states. `changes/`, `progress/`, `report/` are deliberate redirect stubs to surviving surfaces (decision §6 permits 404-or-redirect).
- **Fail-closed work detail.** Historical orders render the no-external-flow notice and hide ops/registration panels (`work-orders/[workOrderId]/page.tsx:87-89,91-106`); `UNVERIFIED` execution mode discloses no managed/equipment state (`:87`).
- **E2E honesty preserved.** Real populated/empty/history/currentness/focus tests intact; skips are conditional in code (external-base-URL, coarse-pointer, phase2) with reasons, not hidden fixture gaps. `p4-cleanup-capture.spec.ts` asserts retired URLs 404-or-redirect and keeps the bodyless-HIL-404 special case explicit (`:64-80`); `site-workspace.ts` fixture declares its non-evidence bounds (`:1-7`).
- **Home typed-unavailability (INV-040/RB-09).** `page.tsx:125-133` shows `—` (never fabricated counts) plus explicit cannot-infer warnings; `recentUpdateView` disclaims safety meaning (`:71`).

## Findings

### Important-1 — Missing analysis-destination title/H1 (KNOWN-OPEN, design-owned; engineering consequence recorded)
- `source/apps/dashboard/src/components/nav/page-title.ts:19-37`: no entries for `/sites/[id]/{analysis,spatial-assets,progress,report}` → `resolvePageTitle` returns `""` → shell emits no H1 on the analysis destination. `analysis/page.tsx:57` renders only an H2. Confirmed by `capture-checks.json` `actual-analysis` `h1Count 0` + `page-has-heading-one/moderate` at all 3 widths, and 4 E2E failures (`e2e.log`, `operations-console.spec.ts:155/164`, all projects).
- Requirement/contract effect: surviving KEEP route loses accessible page position; RB-07 review focus (keyboard/focus/a11y) blocked on this screen until fixed.
- Recommended bounded fix/test (design run `a3547beb`, verify in final delta): add `analysis → 현장 분석` (and `spatial-assets`) patterns to `page-title.ts`; keep page-body H2; existing `operations-console.spec.ts:164-167` assertions become the regression test. Do not touch backend or grants. Not implemented here.

### Important-2 — Duplicate desktop "새 관측 시작" CTA breaks strict-mode selection (KNOWN-OPEN CTA-selector refinement)
- `SiteHeader.tsx:81-90` (header `primaryAction` via `resolveSiteOperatorNextAction`, correct mounted-only logic in `operator-next-action.ts:19-52`) and `sites/[siteId]/page.tsx:105` (observations-section link, same href) render two identical accessible names on the default desktop workspace. Confirmed by `capture-checks.json` `site-workspace@1440.newObservationLinks` (2 entries) and 2 E2E failures (`operations-console.spec.ts:242/275`, desktop-1024/1440, strict-mode violation quoted in `e2e.log`).
- Effect: user sees two identical CTAs; test cannot disambiguate. No wrong navigation (both hrefs identical and mounted) — functional impact is ambiguity, not breakage.
- Bounded fix/test: either scope the E2E selector (header vs section) or disambiguate labels visually; design owns the CTA decision, final delta to confirm. Mobile/tablet unaffected (single disclosure path, passing).

### Important-3 — Four Home screenshot baselines vs P4 content (awaiting explicit adjudication; P4 cannot close on current package)
- `e2e.log` `operations-console.spec.ts:84/110` `home.png` failures on all 4 projects. The spec already masks volatile timestamps (`article span.num`) and allows 3,500px font-AA drift — failure above that threshold is genuine content drift from retired-surface removal, i.e. expected. Handling is correct (no auto-refresh, baselines untouched), but closure requires the stated exact-render adjudication: fresh captures at 390/768/1024/1440 from the final revision + human decision to adopt.
- Also note `denied-analysis` rows show `h1Count 1` while `actual-analysis` shows 0: the denied path gets the shell H1 via a different title branch — consistent with Important-1's root cause, same fix.

### Important-4 — Duplicate H1 on denied-Site path (KNOWN-OPEN; nondisclosure content itself is correct)
- `capture-checks.json` `denied-site` `h1Count 2` at 390/768/1440: shell "현장 상세" (title regex matches the path before `notFound()` renders) + `not-found.tsx:8` "현장을 찾을 수 없습니다". Content is INV-060-correct (empty-org test asserting zero name disclosure passes). Defect is markup-level heading duplication on both genuine and denied 404s.
- Bounded fix: design heading pass (final delta); suggest asserting single-H1 on the denied capture alongside the existing nondisclosure assertions.

### Minor-1 — Unreachable `data` section config + stale `/more` copy
- `coming-soon/[section]/page.tsx`: `SECTION_BLURB`/`AVAILABLE_NEXT_ACTION` carry a `data` key that can never render (`NAV_ITEMS` mounts only `fleet`; anything else `notFound()`s). Dead config, zero user impact.
- `more/page.tsx:9` copy ("비행 임무·장비 연결·복구…") still names retired acquisition surfaces though the only overflow item is fleet. Bounded fix: trim to the surviving fleet/support scope; drop dead `data` keys.

### Minor-2 — Dead managed-era epoch helpers retained in `site-epochs.ts`
- `toSiteEpochs`/`resolveEpochId`/`findEpoch`/`ambiguousEpochDays` (and the `SiteProcessingJobSummary` import) have zero callers post-P4 (verified by grep); the file stays only for `SITE_TABS`/`normalizeSiteTab` (used, incl. retired-tab remapping `:115-119`). Harmless (tsc/eslint clean) but invites future misuse of processing-job-era semantics. Bounded fix: delete dead helpers or annotate retained-for-P5; keep tab exports.

### Minor-3 — Dead retired-route types/comments in `types.ts`
- `EvidenceUploadResponse`/`EvidenceViewResponse` (`:223-237`, comment-anchored to retired `/api/events/*`) and the `/v1/processing-jobs/…/download` response (`:1216`) have zero code references. No runtime effect. Bounded fix: remove or mark `/** @retired P4 */`.

### Minor-4 — Copy-paste metadata on redirect stub
- `sites/[siteId]/progress/page.tsx:3` titles `"공간 자산 · KSI"` (redirects to `spatial-assets`, so invisible). Trivial; correct the title when touching the file.

## Declined to judge (with rationale)

- **Vitest "761/100" count.** `dashboard-commands.json` records exit codes only (all 0); no per-suite counts exist in the package, and the 364 snapshot hashes bind file bytes, not test totals. The exit-0 claim is accepted as stated; the count itself is unverified from package evidence. Python-side counts are independently receipted (6013/30/0).
- **Rendered visual quality beyond settled-state metadata.** Pixels were not inspected (no image channel used); `capture-checks.json` text metadata (settled/pageErrors/overflow/a11y IDs/mainText) is genuine evidence of state, not of design quality. Design owns rendered quality; its review (`p4-cleanup-render-review.md`, PROVISIONAL Round 2, changed-source renders pending) plus the in-flight Round 3 are the deciding inputs.
- **Post-package live drift.** Anything committed after the package snapshot (including Round 3 edits) is outside this review by instruction; the final delta arrives separately to this same session.
- **P5-scoped limitations as defects.** Narrow OIDC Site-mutation/team/pending-workflow scope, unconfigured local analysis graph, and single-volume absence are recorded P5-planning constraints with typed UI states — not permission to broaden grants and not P4 defects.

## Missing / unverified access

- Final design delta (run `a3547beb` heading/nav-title/CTA-selector refinement) + its bound source SHAs and changed-source renders (390/768/1440 + empty/error/keyboard states).
- Independent dashboard test-runner rerun on the final revision (tsc/eslint/vitest/build + Playwright), session id + commands + results.
- Live-repo state beyond the frozen package; product URL/preview links (none exercised — correctly, per read-only implementing instructions).
- E2E skip-by-name breakdown (log records only the total 15; skip predicates were verified in spec code, outcomes not re-executed here).

## Close-out statement

On the frozen post-T4-Round2 package, the P4 retirement is engineering-sound: no wrongly retired mounted consumer, no stale dead link/action/API call, no auth/RBAC/tenant regression, no fabricated empty/numeric/ready state, no historical-meaning drift, no storage bypass, no fixture/E2E concealment, no production security change, and the §8 orthophoto correction is baseline-byte-validated. Four Important items remain, all already-known design-owned closure (H1/title, CTA selector, denied-H1 markup, Home baseline adjudication) with bounded fixes identified; four Minor cleanups are optional. **This is not a P4-closure approval**: closure additionally requires the final design delta, its render evidence on the exact final revision, the independent dashboard-runner receipt, and Human acceptance. I hold no approval authority.
