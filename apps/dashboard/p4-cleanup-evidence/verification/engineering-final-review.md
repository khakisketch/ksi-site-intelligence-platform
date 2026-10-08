# Whole-P4 final-delta engineering review (narrow, read-only)

Basis: prior report `whole-p4-review-v1/reviewer-report.md` + frozen packet `whole-p4-final-delta-v1` (`input-sha256.json` 87 files; `source-delta.json` 14 changed: 9 src/test, 4 Home PNG, 1 design report; 505 unchanged/still-deleted; final source bound by `evidence/t5-final-source-v1/source-snapshot.json` SHA `8256911c…`, 353 files). Live repo, browsers, tests, Git, agents untouched. Only this file written (outside input manifest). No aesthetic approval authority.

## Prior findings — closed by actual source/hash/evidence

- **Important-1 (analysis H1) CLOSED.** `page-title.ts:33-34` adds exact `analysis→현장 분석`, `spatial-assets→현장 공간 자산` patterns; unknown routes still fail closed (`:39`). Unit tests only add assertions (`page-title.test.ts` hunk). Correction accepted: spatial-assets already had its own H1, so title-map absence alone was never the whole proof — now both shell and page ownership are exact.
- **Important-4 (denied H1) CLOSED.** `not-found.tsx:8` H1→H2 (same text/classes/link); shell H1 owns each recognized route. `site-not-found.test.tsx` asserts level-2 + no-deletion-claim + exit link. Denied-analysis H1 came from the generic segment not-found, not an alternative branch — recorded as corrected. `empty-organization.spec.ts` hunk adds denied-analysis H1/H2 + nondisclosure (zero name) assertions on both denial paths.
- **Important-2 (desktop CTA) CLOSED.** `SiteHeader.tsx:264-266` nulls the header instance only on the `observations` tab (in-card action retained all widths; header action kept on other tabs; mobile unaffected — span was `lg:flex`-only). E2E repair scopes the CTA to the in-card panel + asserts global count 1 with unchanged href (`operations-console.spec.ts:80-85` hunk); then exercises the real asset return link (exact href + click + URL) before unchanged 5-tab checks (`:87-97`). No production UI edit beyond the header dedup.
- **Important-3 (Home baselines) CLOSED as ruled.** `baseline-adoption.json`: 4 exact candidates mechanically transferred (adopted SHAs match `source-delta.json` after-SHAs: `04b064bc…/f970995a…/988b4cfb…/d7eb77d4…`), mask/threshold unchanged (3500), inverse references preserved. Within approved brand/layout cleanup; no new Human gate invented; Human acceptance stays open/separate.
- **Minor-1 split honored.** Visible `/more` copy fixed (`more/page.tsx:15-17`, retired flight promise removed; E2E asserts its absence + exact fleet link). Unreachable coming-soon `data` keys + epoch helpers + retired types + progress metadata remain deferred backlog — correctly untouched (no opportunistic sweep in delta).
- **Prior Declined (Vitest count) CLOSED.** `actual-762-vitest.log`: 100 files / 762 passed, exit 0 — actual log, not inferred. (E2E-spec repair postdates it but cannot affect unit totals.)

## Test-repair contract soundness (fca2bf41, spec SHA `20d8a4f4…`)

- RED was real (69/8, T5-OBS-ALERT-QUERY-09 + T5-WORKSPACE-RETURN-10 ×4 widths, preserved in `t5-e2e-red-v1`); pre-repair 69/8 is not treated as pass.
- Repair is 9-added/1-replaced assertion lines, test-only: main-scoped alert count 1/visible/typed copy (announcer untouched, no `.first()`, no retry/zero-claim weakening); real return-link navigation precedes unchanged workspace checks. Same-class scan: no unscoped `alert` remains in spec (only `:177/:189` main-scoped). No skip/mask/threshold removals (15 skips: 2 coarse-pointer, 1 capture-width, 12 phase2-flag — explicit, unchanged).
- `p4-cleanup-e2e-repair.md` (SHA `4fd80863…` verified on disk) preserves RED + post-run limits; final report `p4-cleanup-final-render-review.md` (SHA `5635f47b…` verified) binds 18 PNG / 22 inputs / 353 source with 0 residual design findings.

## New findings in delta: none

No new Critical/Important/Minor. No runtime, permission, catalog, storage, token, or backend edit in any hunk. Review Focus 1–5: no dead ends introduced (return links exact, retired URLs still 404/redirect per capture spec); typed empty/error states retained verbatim; shell/nav/keyboard order untouched except the single dedup; tokens/brand untouched; evidence routes to frozen bundles per `evidence-routing.md` (rolling `before/` folders correctly disclaimed).

## Remaining gaps (functional receipt only)

- Final FRESH independent receipt `ses_ee3cff067` (`/tmp/opencode/p4-final-dashboard-verify-v2/receipt.md`) **not yet arrived** (checked — absent). Prior Python receipt (6013/30/0, 6 SHAs) reused as unchanged scope, correctly not rerun. Primary must bind same-file SHAs before technical closure; this review approves no test run.
- Human product acceptance remains OPEN and separate; not Whole-P5, customer accuracy, storage bytes, or release.
