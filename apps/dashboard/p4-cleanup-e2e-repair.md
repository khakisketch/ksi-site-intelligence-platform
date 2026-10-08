# P4 bounded E2E test-authoring repair

**Disposition:** the two reported E2E assertion-flow defects are corrected in the approved test file. The repair is not yet functionally verified by a fresh browser run; the independent runner must rerun the suite against the post-edit source.

## Scope and authority

- Requirement IDs: `T5-OBS-ALERT-QUERY-09`, `T5-WORKSPACE-RETURN-10`.
- Owner: `apps/dashboard/e2e/operations-console.spec.ts` only.
- Acceptance: keep typed error, heading, accessibility, and overflow assertions intact; scope alert checks to the product main region; return through the actual asset-page link before the unchanged Site navigation checks.
- Invariants affected: none in product/runtime code. This changes test assertions and navigation only.
- Files changed: `e2e/operations-console.spec.ts`; new report `p4-cleanup-e2e-repair.md`.
- No UI, source route, backend, API, data, authentication, configuration, baseline, or other E2E files were changed. No browser/server was launched and no dependency was installed.

Implementation packet: acceptance is the two specified flows reaching their assertions without weakening error, heading, CTA, or five-tab coverage. No product contract or domain invariant is changed. Evidence/reference inputs are the supplied T5 RED bundle and the existing rendered asset-page return link. Synthetic fixture data only; no HIL, customer data, or licensing implications. Rollback is limited to reverting the two local assertion-flow edits in the named E2E spec.

## Verified RED input

The supplied input manifest `p4-cleanup-evidence/t5-e2e-red-v1/input-sha256.json` has SHA-256 `5c9420b47ad44bfb9fa32dea1fe596b238a48966a40dc4fefaa4b5b13095e8a6`. All seven bound files matched their listed hashes before editing. The initial `e2e/operations-console.spec.ts` SHA-256 was `641d5a27d3f428345d992d78a18a2e5f60fbf783fe967682dcd0262dbbc94153`, matching the supplied findings record.

| Bound input | SHA-256 |
|---|---|
| `10-tsc.log` | `bcb1a61798abda8d8a3a775a1373725c955f1de0a18ef7e131bc06475bdc0f16` |
| `11-eslint.log` | `839cd2e6d5b7422b00ca3c87bc481991029e4006ef418011e635729f31ffaa26` |
| `12-vitest.log` | `c7323cf4b1a3ba0107257616efd36f139dbd9b781f643ff8c2a46cc1273646b0` |
| `13-build.log` | `81cd3d248f147edbde395ef48e775f930ef128678234b1f3daba959b09246d7b` |
| `20-e2e.log` | `1fc0fcda417537384f0f6935f64b123337f85963e9776fb6c2da8a3640185d59` |
| `21-e2e-json-summary.txt` | `0373c05f5922a3ab3c11ccb1c6b9f5e200136a2402297c54c3df0d0c91215d79` |
| `source-and-findings.json` | `03a0e57757ac2ba58a11933c49ed686f3688eef391800e59bfe48ebc8c7ab3b9` |

Independent runner `ses_ee3df17b2ffeY4zF1AdKMuolcq` reported **69 passed, 8 failed, 15 skipped** across the four named viewport projects (exit 1). The failures below occurred at all four widths. The supplied prior full checks were tsc, ESLint, build, and 762 Vitest tests across 100 files, all exit 0; those checks ran against the pre-repair source and are not post-edit evidence.

## Repairs

### T5-OBS-ALERT-QUERY-09 — observation alert query

At the observation-history destination, `page.getByRole("alert")` matched both the actual error region inside `main` and Next’s route announcer outside `main`. The strict-mode failure was confirmed in the supplied E2E log at the observation-history copy assertion. The analysis route assertions earlier in the same test already passed.

The test now uses `page.getByRole("main").getByRole("alert")`, asserts exactly one region, asserts it is visible, and retains the typed error-copy assertion. The existing observation H1/H2 checks and no-horizontal-overflow check remain. The E2E file’s same-class alert-query scan now finds only two alerts queries: the existing analysis query scoped to `main` (line 177) and the observation query scoped to `main` (line 189); there is no remaining unscoped alert query in this file.

### T5-WORKSPACE-RETURN-10 — Site tab checks after asset-route coverage

The test navigated to `/spatial-assets` to validate the accessible asset page, then incorrectly ran the workspace’s five-tab assertions while still on that detail route. The supplied failures show the mobile disclosure and desktop Site navigation were therefore absent. The product’s asset page already renders the real “현장으로 돌아가기” link to the workspace.

The test now asserts that this link is unique and visible, checks that its destination is exactly `siteHref`, clicks it, and waits for the workspace URL before running the existing five-tab assertions. This preserves actual route behavior and leaves all five tab labels, desktop navigation checks, mobile disclosure/interaction checks, subsequent work-order checks, external-result typed state, CTA assertions, and overflow checks in place. No Site header was added to the asset page, and no coverage was removed.

## Verification and exact post-edit state

- Targeted lint run: `./node_modules/.bin/eslint e2e/operations-console.spec.ts` — exit 0.
- Browser/E2E rerun: **not run here**. The supplied 69/8/15 result is pre-repair RED evidence; it must not be presented as a passing result for this repair. A fresh independent run is required to close both IDs.
- The Round 4 frozen source snapshot `p4-cleanup-evidence/t4-round4-render-v1/source-snapshot.json` (SHA-256 `4a66cec660015bd20262cbf6513ba7f136d6ddb7fc17cf5540deea615c1fa3bd`) binds 353 files. After this repair, the 352 files other than `e2e/operations-console.spec.ts` still match exactly (zero mismatches). The operations spec is the sole expected snapshot mismatch.
- Post-edit `e2e/operations-console.spec.ts` SHA-256: `20d8a4f4390a68de3bc9125e0e1a745adc28f7db1a47dfd57e8eec6474b4fda9`.
- The separate rendered design review remains [p4-cleanup-final-render-review.md](p4-cleanup-final-render-review.md), tied to the unchanged UI source and Round 4 captures. This test-only repair does not invalidate that visual review or claim a new render result.

## Remaining evidence

The outer owner should run the independent four-project E2E suite against the exact post-edit spec hash above and report its result separately. No additional visual capture is needed because the UI source and rendered states are unchanged. P5 remains unapproved and was not started.
