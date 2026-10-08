## Round 4 — bounded heading, copy, and E2E query closure

Date: 2026-10-08  
Status: **PROVISIONAL pending matching host captures and post-edit E2E**. The source fixes and regressions are in place, but the post-edit rendered result is not available in this environment. Round 3’s source-bound Home baseline adoption remains accepted and unchanged.

### Scope and review basis

This round repairs only the three assigned defects. The existing design system, tokens, Home hierarchy and carousel, Sites table and single row action, five Site tabs, provenance/currentness, and strict V1 / provisional V2 semantics remain untouched. No route destination, access behavior, backend contract, permissions, data, or API was changed. The pinned `web-design-guidelines` file was used for semantic heading hierarchy, accessible error identification, and truthful copy. The installed Next.js `not-found` guidance was re-read: route-segment `notFound()` remains the existing Site access boundary.

A safe write/read/remove probe succeeded in this real folder and was removed. No copy, alternate app, server, or browser was launched.

### Frozen inputs and actual image review

- `p4-cleanup-evidence/t4-round3-render-v1/source-snapshot.json` SHA-256: `31411b527003454d35b607c2b56d05431c13b2bd913b9cdf9ebb9ae21d16b4aa`. It binds 353 source, test, E2E, configuration, script, and baseline files. All 353 matched before editing. Afterward, the only six mismatches are the six files listed in the changed-source table below; the other 347 still match.
- `p4-cleanup-evidence/t4-round3-render-v1/input-sha256.json` SHA-256: `136651879af655ec614946794064bd867df46f4db079a7855743bb793abd53e6`. All 35 entries (28 PNGs plus seven evidence files) match their manifest hashes. The capture ledger has 28 rows, zero page errors, and zero API failures.
- I opened all 28 actual PNGs with an image-capable viewer: `actual-analysis`, `actual-assets`, `denied-analysis`, `denied-assets`, `denied-observations`, `denied-site`, `site-analysis`, and `more-before`, each at 390, 768, and 1440 px; plus `site-workspace` at 390, 768, 1024, and 1440 px. The 28 names and hashes are bound by the manifest above.
- The accessible `actual-assets` images show the page title “현장 공간 자산”. The denied `denied-assets` images show the generic Site denial but no route H1. The visually inspected More images show a single supported “Dock·Edge 지원 범위” destination while the introductory line promises retired flight-mission, equipment-connection, and recovery screens. Analysis images show the correct visible typed unavailable message; the pre-edit browser E2E log records the strict global alert query finding the real main alert and Next’s separate route announcer.
- Exact pre-edit defect-render hashes: `denied-assets-390.png` `8cf9d1714ef9b81a6ca5d23164e2237a375a31cca9c28442b7444aa301ec1184`, `-768` `254db0ae3118604c8305f55842b70e4399b35c02d760c114aa119b4ba80a7e95`, `-1440` `15b2944cefb506ee9454fbeb2e9ef579f90cef05e5c9779c3314d573e3743867`; accessible asset 390 `63189c94b80bb324743fba2913e4a254ba135290df9ddf3abdd97a0c0ee11d2c`, 768 `9ade0c3bcc9566cc17725580c9d9d84d03ef8515303541da702b94e88de4956d`, 1440 `2ecbba876e0deed486ad9cb4b55b9f9d9e09650f87b890be61c35724f8486ae4`; More 390 `7221f00177182af23f1d02e3bc33b10dd12fd733bb74d0420405ad69e7521968`, 768 `92380e43dec81d38f8c02a4f6f4c23200abe5caa96e61f6da32fd253cb07aabb`, 1440 `b0dd5dbbc362abbed8af9bd1ba6005da26ba8bec2558747bafcd0dca8ac05550`. These are pre-edit render identities; post-edit visuals remain open.
- Round 3’s four adopted Home PNGs were a mechanical adoption of the exact current candidates after the explicit image review. They were not touched here, and Home implementation files remain unchanged.

### Fixed/open defect ledger

| Finding | Source change and regression coverage | Rendered status / closure criterion |
|---|---|---|
| `T4-ASSET-DENIAL-H1-06` | Added exact `/sites/{id}/spatial-assets` title resolution, including trailing slash, and changed only the accessible page’s visible title element from H1 to H2. This gives the shared shell the canonical H1 in both accessible and genuine Site-denial states while retaining the page title, styling, Site-first access, selectors, errors, catalog semantics, and generic non-disclosing denial copy. Added a route-title unit assertion and E2E checks for one canonical H1 and visible page H2 on the accessible fixture, and one canonical H1 plus generic denial H2 with no Site name on the denied fixture. | **Source fixed; rendered closure open.** The existing before captures show 0 H1 and three moderate `page-has-heading-one` findings on denied assets, versus one page H1 and no axe finding on accessible assets. Fresh matched renders must show the same single canonical H1 and visible H2 in both states; denial must remain generic. Existing Site and analysis one-H1 checks remain in E2E and their source is unchanged. |
| `T4-MORE-COPY-07` | Replaced only the retired introductory promise with “운영 지원 범위와 아직 실장비 검증 전인 기능을 안내합니다.” Existing card, role, destination, label, status badge, and navigation remain unchanged. Added E2E coverage for exactly one supported `/coming-soon/fleet` link and the current verification limitation, plus absence of the retired promise. | **Source fixed; rendered closure open.** Fresh More captures must show the corrected copy at all three widths and retain the existing single support destination and badge. |
| `T4-ANALYSIS-ALERT-QUERY-08` | Changed only the E2E locator to the main landmark’s alert. The test still requires exactly one alert in main, visibility, and the typed unavailable message. It retains the no-retry, no-fabricated-result, context, and genuine-Site-404 checks. Production alert semantics and Next’s route announcer are unchanged. | **Assertion corrected; post-edit browser verification open.** The pre-edit browser evidence shows one product error region plus the framework announcer; scoping to main removes the strict-mode ambiguity without weakening the product assertion. |

### Verification and exact changed source identity

| Check | Result |
|---|---|
| Frozen source and input integrity | Passed before edits: 353/353 source hashes and 35/35 input hashes matched. All 28 captured PNGs opened. |
| TypeScript `tsc --noEmit --pretty false` | Passed after edits. |
| ESLint on the six changed source/test files | Passed after edits. |
| Focused Vitest (`page-title` and spatial-assets page tests) | Could not start: installed Rolldown lacks `@rolldown/binding-wasm32-wasi`. No installation or workaround was attempted. |
| Post-edit E2E, full Vitest/build, and rendered capture review | Not run here. The supplied host results (69 passed / 4 failed / 15 skipped E2E; host typecheck, eslint, Vitest 761 tests / 100 files, and build passed) predate this Round 4 edit. They are not evidence that these changes pass. |

The six changed-file SHAs below bind the post-edit state. The change-set digest is SHA-256 over sorted `path<TAB>fileSHA\n` rows: `87ababc8428515c90686388a61ef536c964d0c5cceb7310b34c6e08964bad35f`.

| File | SHA-256 |
|---|---|
| `src/components/nav/page-title.ts` | `beb5443a2a270975d2f2ea4474f99ba2ba6d9ee4c0194528cb9e128933b12acf` |
| `src/app/sites/[siteId]/spatial-assets/page.tsx` | `e3226b1acabf40a3a5576bf8b16ccfd3e176f78e576d53a9f741435f6ca23faa` |
| `src/app/more/page.tsx` | `1942809e919f9806f631c6231c2e840d45773ee56d1ec8e1436fd89aa7e30893` |
| `test/page-title.test.ts` | `408c0a0f3f43587863a408e9dd00f573674654f2181d510d514324b2a15c3e9b` |
| `e2e/operations-console.spec.ts` | `641d5a27d3f428345d992d78a18a2e5f60fbf783fe967682dcd0262dbbc94153` |
| `e2e/empty-organization.spec.ts` | `3db6f9ce5e26d29dbd7b7a6dd823f369a9e0ac6bbcc4f99c7993f51dcb452e91` |

### Required fresh host captures

Capture against the exact six-file hash set above, using the existing product host only:

- Accessible `/sites/e2e-site-workspace/spatial-assets`: 390, 768, and 1440 px.
- Denied `/sites/e2e-site-workspace/spatial-assets`: 390, 768, and 1440 px.
- `/more`: 390, 768, and 1440 px.

This is nine images. The shell component was not structurally changed; its route mapping only adds the exact spatial-assets route. Keep the existing Site and analysis one-H1 E2E assertions green. Do not refresh or mask Home baselines. Final design closure requires review of those matching images and post-edit host E2E results; full host checks remain the outer verification responsibility.

---

## Round 3 — source-bound rendered adjudication and semantic/action cleanup

Date: 2026-10-08  
Status: **PROVISIONAL for the seven edited files** — the Round 2 render bundle was opened and is valid for the pre-edit source; this environment cannot capture the updated application. The heading and CTA source changes below need the specified changed-source renders from Outer Build before visual closure. Home is adjudicated separately because none of its rendering files changed.

### Review basis and source/image integrity

- Used the bundled `web-design-guidelines` pinned snapshot (`.od-skills/web-design-guidelines-f3cc56cce8/references/guidelines.md`), focusing on semantic heading hierarchy, keyboard access, navigation/action clarity, and truthful settled states. Existing brand/tokens and the accepted Home/Sites/Site workspace composition remain locked.
- Re-read Dashboard/shared project guidance and installed Next.js `not-found` file-convention guidance. `notFound()` is segment-scoped; the Site segment keeps its existing generic, non-disclosing message and return link.
- The real-folder write/read/remove probe passed (`.p4-round3-access-probe`); the probe was removed. No copy, alternate app, or runtime was used.
- Frozen render source snapshot: `p4-cleanup-evidence/t4-round2-render-v1/source-snapshot.json`, SHA-256 `a81dd1fb8e66e9ae6bdf8ae615b23201457d4a980824d1ddeb99691370085224`; it binds 353 required source/test/E2E/config files. The prior host states all 353 matched before and after capture. After these Round 3 edits, a local comparison finds exactly seven changed paths (listed below); the other 346 still match. No Home screen implementation file is among the seven.
- Frozen image/input manifest: `p4-cleanup-evidence/t4-round2-render-v1/input-sha256.json`, SHA-256 `47c3779950937466f5279119e0d558cc122fb288ddcf087c239a8b749a89ef5f`. All 84 listed entries, including all 80 PNGs, still match the manifest. All 68 settled state images were opened with an image-capable viewer: 36 primary route views at 390/768/1440; eight real keyboard first-Tab/Enter states at 390/768/1024/1440; six carousel-next normal/reduced-motion states at 390/768/1440; twelve empty/denied states at 390/768/1440; and three lower-page external-work states. I also opened all twelve Home candidate, difference, and retained-reference PNGs. The 80 PNG hashes were checked against the frozen manifest; no evidence file was overwritten.
- The settled-state images show: actual analysis is an honest typed unavailable state but has no shell H1; actual observations has one shell H1, a visible H2, and a settled retryable error; foreign Site denial copy is generic and contains no Site name; Home shows the approved count line, two-candidate carousel, setup action, recent updates, and explicit unavailable-source warnings. Keyboard images show the skip link is first at all four widths, Enter focuses main, and lower-page focus geometry does not cover content. The lower-page locator-focused images are geometry evidence only, not first-Tab evidence.
- `capture-checks.json` records 68 settled rows with zero page errors and zero horizontal overflow. It reports `actual-analysis` with 0 H1 and three `page-has-heading-one` moderate findings, `denied-site` with 2 H1 at all three widths, and `site-workspace` with two visible `새 관측 시작` links at desktop 1440 (header + observations section). These line up with the actual opened images and the ten host E2E failures: four Home comparisons, four missing analysis H1 assertions, and two strict desktop CTA queries. Host reports tsc, eslint, full Vitest (761 tests/100 files), and build passed on the pre-Round-3 source; the pre-edit four-project E2E was 63 passed / 10 failed / 15 skipped.

### Screen and state review

| Screen/state | Rendered result and impact | Round 3 decision |
|---|---|---|
| Home, 390/768/1024/1440 | Current candidates preserve the approved reading order: count line, source-unavailable warnings, two decision candidates in the carousel, initial setup, recent updates. At 390 the bottom navigation overlaps the scrolled page as designed and the card remains readable; tablet and desktop keep the same sequence with the carousel layout adapting to width. No invented zero-pending or normality claim appears. | Accept exact current candidates as the visual oracle for the already-approved Home source projection; authorize mechanical refresh of only these four existing Home baselines. No mask or threshold change. |
| Site workspace, 390/768/1024/1440 | Five tabs and contextual section remain. Mobile/tablet have one in-card `새 관측 시작`; desktop showed the same destination twice, once as a dark header button and once as a secondary section action in the same viewport. That duplicate adds no distinct intent and caused strict locator ambiguity. | Remove only the redundant header instance on the observations tab. Keep the in-card action on all widths and the header action on other tabs where no duplicate panel action exists. |
| Direct analysis, 390/768/1440 | Site context and the typed “이 환경에서는 현장 분석 기능을 사용할 수 없습니다.” error are honest and do not fabricate empty data. The screenshots show the visible H2 but zero document H1. | Add only the recognized `/sites/{siteId}/analysis` route title to the existing canonical shell-title resolver; retain the visible page H2 and unknown-route fail-closed behavior. |
| Denied Site and denied analysis, 390/768/1440 | Site denial stays generic and contains no foreign Site name. The Site route had a hidden shell H1 plus visible denial H1; analysis denial had only the visible generic H1 because the route title was missing. | Keep one shell H1 for each recognized route and change the visible denial heading to H2, with the same text and styling. Assert both direct denial paths remain non-disclosing. |
| Actual observations / assets, 390/768/1440 | Observations has a settled retryable error, one H1 and visible page H2. Spatial assets shows the actual work-area selector/Core metadata message with no invented values. | Preserved; observation heading is already single-level in the frozen source. |
| Sites, field, external work, historical work, and empty states | The desktop Sites comparison and single row action remain; five Site tabs remain. Work statuses and numeric counts are actual fixture values; external-work lower states explicitly show unavailable optional comparison history and unconfigured single-volume measurement. Empty Sites retains a real registration action. Historical work remains read-only and identifies its absent registration flow. | Preserved; no data, workflow, role, endpoint, or backend changes. |
| Keyboard / carousel motion | Real first Tab focuses the skip link at all four widths; Enter reaches main. Normal and reduced-motion captures both advance to the actual second candidate. The lower-work focus shots have explicit locator-focus provenance and show no obstruction. | Closed from the exact frozen source renders and host assertion results. No new keyboard styling or assertion relaxation. |

### Concrete defect ledger and source changes

| Stable ID | Severity | Finding → desired result | Round 3 change / state |
|---|---|---|---|
| `T4-ANALYSIS-H1-03` | P2 | Direct analysis has 0 H1 and three axe heading-one findings, despite the visible page title. Keep the visible H2 and provide the existing canonical shell H1 for this recognized route only. | Added `/sites/{siteId}/analysis` to `resolvePageTitle`; added exact and trailing-slash unit cases. The route E2E now requires exactly one main H1 named `현장 분석`, while retaining the visible H2 and typed unavailable assertions. **Source fixed; post-edit image/E2E pending.** |
| `T4-DENIED-H1-04` | P2 | Denied Site renders two H1s, while denied analysis renders its H1 from a different source. Keep one canonical route H1, visible generic denial copy, no foreign Site identity, and the current return link. | Changed only the denial heading element from H1 to H2; existing visual classes/copy/action are unchanged. The empty-organization E2E now checks one H1 plus the visible H2 on both `/sites/{id}` and `/sites/{id}/analysis`, and checks that the Site name remains absent. **Source fixed; post-edit image/E2E pending.** |
| `T4-SITE-CTA-QUERY-05` | P2 | The desktop observations tab presented the same destination in the header and its own observation-history panel. Preserve a clear direct action without duplicate navigation. | The header action is suppressed only on the observations tab, where that tab's in-card action is present; the in-card link remains for mobile/tablet/desktop and other-tab header behavior remains. E2E scopes the link to the titled observation panel and asserts exactly one visible link and the exact destination. **Source fixed; post-edit image/E2E pending.** |
| `T4-SKIP-01` | P2 | Earlier first-Tab regression and lower-page obstruction. | **Closed from frozen changed-source capture plus host results:** all four first-Tab/Enter cases passed; lower-page focused-link images show it stays in the content column without covering work content. Round 3 does not change skip behavior. |
| `T4-ANALYSIS-ROUTE-02` | P1 | Optional analysis child 404 must not be mistaken for Site denial or an empty successful analysis. | **Closed from frozen capture and host route evidence:** accessible Site context plus typed unavailable state; no fabricated numeric results or retry for expected local child 404. Foreign Site denial remains generic. No graph configuration, permission, or API changed. |
| `T4-OBS-H1-01` / `T4-OBS-SETTLED-01` | P2 | One H1 and a settled observation-history state. | **Closed from frozen capture:** one H1, visible H2, honest retryable settled error at all three widths. No further change. |
| `T4-OPTIONAL-WORKFLOW-01` | P2 | Optional lower-work reads must not present unavailable as empty/success. | **Closed from frozen settled captures:** comparison history shows typed unavailable/retry; single-volume section explicitly states configuration is absent. No workflow configuration/API change. |
| `T4-HOME-BASELINE-01` | P2 | Historical baselines no longer match current product content, leaving four E2E diffs. Decide against exact actual renders rather than masking or raising threshold. | **Adjudicated:** accept the exact candidates below and authorize mechanical refresh of those four baselines only. Home source hashes listed below remain identical; no Round 3 Home source edit occurred. |

### Home baseline decision — per-width image identity

Each candidate is the exact current Playwright actual from the frozen 353-file source snapshot. The retained image is historical; the diff image helps identify the change. The existing `article span.num/white` mask and `maxDiffPixels: 3500` threshold are unchanged. Candidate images visibly preserve the approved information hierarchy and truthful warning language; differences are the retired third attention card/older copy versus two actual decision candidates plus current warnings/setup language, not a broken layout. **Adopt the candidate as oracle at each width and permit Outer Build to mechanically refresh only the corresponding Home baseline.**

| Project | Current actual candidate SHA-256 | Difference image SHA-256 | Retained historical baseline SHA-256 | Decision |
|---|---|---|---|---|
| `mobile-390` | `04b064bc2dd902208d23f9aaca24b486fb3f874f67e7294c562ccd13f967da0b` | `a094dfa84df709b716f4c627be33783bc5f2af3b46ff61012a72e2cc934e37c1` | `3df02e0dd0bdf83c8478027a97a4d126ad389a00b8cca107585907ce1ecd13dd` | Adopt candidate; refresh allowed. |
| `tablet-768` | `f970995af32880c86f18d84d41f635541baa2e7f9596c016e861dbb81aafc8e9` | `056a789a9febced0bf185c4c4d0db7cf85261cc3c7fc12c4ce4d36516f37a31b` | `2818ec4c614ca4974303ed5cee864a2744bf9567cd7f5ad2823dfb05f1acf846` | Adopt candidate; refresh allowed. |
| `desktop-1024` | `988b4cfb0cb3104b57df395f51ee3a9a7d077a7f4f0788cf1f9044a3d7b006a1` | `4888a2228206322439264d9bd0635c2bcb156f87475195326c2222a22347e82d` | `901998b372882453be521107052864e8612828ba03b50504a1c7c46a51139d59` | Adopt candidate; refresh allowed. |
| `desktop-1440` | `d7eb77d41b425b808ce0b23fe8b748cec2d5ff9b903c811f5a5312936ab91630` | `88e61a2b7d1450ddb8fc81c910f2fc1c6ab580bb706fbbf66510f675065cd5c3` | `6610663fa5a47c6cfa56e1fb83939a65ed9b3530feb2000ef5fa44607015d665` | Adopt candidate; refresh allowed. |

The Home rendering files `src/app/page.tsx` (`bdaa45763d187b3387ccb2159487390a7526dd114ffa69784250cce13c00fb3f`), `HomeAttentionCarousel.tsx` (`a73628c29442b58a5596db9dca43074619a410e279d17576cb97a00a2c0562ea`), `HomeRecentUpdates.tsx` (`1ca1cb8b3cb8a15a401e5b719496deccd472fe2ed6b0b24ac81a07b9f3749ae6`), `HomeSituationList.tsx` (`59321eeb0637acadffc2fc029480549d8418dfd8b879395a804d036e4f76228`), `globals.css` (`0cab25cb895182296a0fdc565ce4445565bab3502e20cffe21b736c5fe300b47`), and the Home state derivation modules (`home-external-decision.ts` `259ec9aa17f4ef6e50bffd5dfc505edc5bdbb3342d2f01db553501f2fe2af60e`; `home-operations.ts` `19e95e5d28eb35e15d2c1369dfff527d472ddcb950f2d5b97a8caaee29128c41`; `operator-next-action.ts` `934c7dd902e05e03374957ce3f281b696e2e77c4cfbb466df8631048d2befe0c`) are unchanged from the frozen snapshot. The only shared resolver change adds an exact analysis route pattern; `/` still resolves to `홈`. Thus the four reviewed candidates remain valid for Home, despite the unrelated Site-route source edits. No Home baseline file was changed here.

### Round 3 verification and exact changed-source identity

| Check | Round 3 result |
|---|---|
| Dashboard `tsc --noEmit --pretty false` | Passed after Round 3 changes (exit 0). |
| ESLint on the seven edited source/test files | Passed after Round 3 changes (exit 0). |
| Focused Vitest (`test/page-title.test.ts`, `test/site-not-found.test.tsx`) | Could not start: the installed Rolldown binding `@rolldown/binding-wasm32-wasi` is missing. No dependency installation or workaround was attempted. |
| Host full tests/build and four-project E2E | Host supplied results apply to the pre-Round-3 source only: typecheck/eslint/build passed; Vitest 761/100 files passed; E2E 63 passed / 10 failed / 15 skipped. Do not treat those as post-edit validation. |
| Round 3 source render / browser flow | Not run here. The host application remains the only valid render target. No replacement server/browser was started. |
| Frozen evidence integrity | Input manifest SHA remains `47c3779950937466f5279119e0d558cc122fb288ddcf087c239a8b749a89ef5f`; all 84 entries verify. No Home baseline was modified. |

The Round 3 source-set digest is `3add6b6e35b67170b0d8c96b6c675b2893339d43815174d5f0da9b6b0bf75c15`, defined as SHA-256 over the seven sorted `path\0file-sha256\n` records below. Outer Build should capture these exact changed-source hashes, then return the rendered states for review:

| File | SHA-256 |
|---|---|
| `e2e/empty-organization.spec.ts` | `559894bb445e278ce88d1c06ec85d2fc211cefcf40a8d5634b91949a4ab3e013` |
| `e2e/operations-console.spec.ts` | `13340a3006038c68d1f8ce5bc4e16b40ba79570e0ad3bc6d7ccaa9494673a501` |
| `src/app/sites/[siteId]/SiteHeader.tsx` | `34a9992432b80c6a8a893613b9eb691275a2ad956c3f367cbef792777065c077` |
| `src/app/sites/[siteId]/not-found.tsx` | `fff2c5e2b61ae9936badf138994232135ff87d2712c92644a68d15cfd90d54fe` |
| `src/components/nav/page-title.ts` | `4ba7a1f6f87d6146edf0cd9ff9f4740ff39d144a94f86f4da02a5f52536ffb34` |
| `test/page-title.test.ts` | `d01419a7e14663acdc01507dc83bd34a51fbc85c6ded200e18273256cc23a3bc` |
| `test/site-not-found.test.tsx` | `7824d6e6c3f5d55b41c1aded979b37234ed476b2a997ec81fc525b50964af7f2` |

Minimum changed-source capture set: direct accessible analysis `/sites/e2e-site-workspace/analysis` at 390/768/1440; foreign/denied Site `/sites/e2e-site-workspace` at 390/768/1440; foreign/denied analysis at 390/768/1440, under the empty-organization account; and the default Site observations tab at 390/768/1024/1440 to verify exactly one `새 관측 시작` action at the in-card location and no duplicate header instance. Confirm one H1 and zero heading-one axe violations on each denial/analysis state, visible generic denial copy, no Site name disclosure, and the existing observation destination. Home recapture is not required for this patch because the enumerated Home rendering source hashes are unchanged; the four frozen candidates above are the approved baseline targets. Outer Build still owns its independent source/contract checks and post-edit E2E run.

## Round 2 — settled-input review and bounded fixes

Date: 2026-10-08  
Status: **PROVISIONAL** — the frozen captures below are genuine renders of the exact pre-edit source snapshot, but no browser render of this round's changed source is available here. Visual acceptance and baseline adoption remain open until Outer Build provides the specified exact-source captures and they are reviewed.

### Review basis and integrity

- Applied the bundled `web-design-guidelines` skill using its pinned `references/guidelines.md`; this round followed Accessibility, Focus States, Navigation & State, Touch & Interaction, and Content & Copy. Existing brand, `globals.css` tokens, Home hierarchy/carousel, Sites comparison table and single row action, and all five Site tabs remain the visual contract.
- Re-read Dashboard `AGENTS.md`, shared `../../AGENTS.md`, and installed Next 16.3 guidance at `node_modules/next/dist/docs/01-app/03-api-reference/04-functions/not-found.md`. The relevant contract is that `notFound()` terminates its segment; it must only be used after the Site lookup itself returns 404.
- Real-source write/read/remove probe passed in this Dashboard folder; the probe file was removed. No managed copy or substitute app was used.
- Frozen source snapshot `p4-cleanup-evidence/t4-post-v1/source-snapshot.json` SHA-256: `9920c59caf8b89ac19fd47708377de0d6cd8995b72db79ea8fb01f056e50e049`. It records HEAD `9a3bab1ba710d0c8925cf3ae8bd8e301e425a9cf`, pending source, and 237 required UI/E2E file hashes; all 237 matched the live folder before this round's patch.
- Frozen input manifest `p4-cleanup-evidence/t4-post-v1/input-sha256.json` SHA-256: `a6a9db87c9832dee48bd2dddab09b8a0cd8dbe4f58a931be25588a1c40e2b104`. All 63 manifest entries matched before edits. The manifest and captures were not changed.
- Opened and visually reviewed all 59 unique PNGs with the image viewer: the 12 primary states (`home`, `sites`, `site-workspace`, `site-analysis`, `site-assets`, `actual-analysis`, `actual-assets`, `actual-observations`, `site-external-error`, `field`, `external-work`, `historical-work`) at 390/768/1440; `external-work-bottom` at 390/768/1440; `keyboard-first-tab` and `keyboard-skip-geometry` at 390/768/1024/1440; and `empty-home`, `empty-sites`, `empty-field`, and `denied-site` at 390/768/1440. `keyboard-skip-geometry` is locator-focused geometry evidence only; it does not establish first-Tab order.
- `capture-checks.json` contains 59/59 settled rows, zero page errors, zero recorded accessibility findings, and zero horizontal-overflow rows. Its six 404 API failures are the expected unconfigured optional relative/single-volume workflow reads, not successful empty results. It also records two H1s on the observation-history route at each width. These are observations of the pre-edit render, not a post-edit result.

### Screen and state review

| Screen/state | Rendered result and impact | Round 2 disposition |
|---|---|---|
| Home, 390/768/1440 | The count line, source warnings, two decision-candidate carousel cards, initial-setup region, and recent updates remain legible. Warnings do not imply zero pending external decisions. Home source and data hierarchy were untouched. | Preserved. No current-source screenshot set for the four historical baselines; no baseline adoption. |
| Sites, 390/768/1440 | Five scoped sites are visible. Mobile cards remain readable; desktop keeps the comparison table and single row action. Captures record no horizontal overflow. | Preserved. |
| Site workspace and five tabs, 390/768/1440 | The gateway keeps Site context and its analysis entry; the five destinations remain observations, analysis, spatial assets, work orders, and external results. | Preserved; added actual analysis-destination coverage in E2E. |
| Analysis gateway, 390/768/1440 | The gateway is readable and links to the real analysis destination. | Preserved. |
| Direct analysis destination, 390/768/1440 | Before this patch, the actual page showed generic “Site not found” even though Site access was valid. Source evidence showed Site and work-area reads succeed while optional analysis child routes return 404; the page grouped them in one `Promise.all`, so a child 404 incorrectly became Site absence. | Fixed in source, pending changed-source render. Site lookup now completes first; only its 404 calls `notFound()`. Child 404 produces a labeled unavailable state with verified Site context, no result panel/numeric claim, and no futile retry. 403 is permission copy without retry; transient errors preserve retry/Retry-After. |
| Observation history, 390/768/1440 | The settled view is a real retryable load error, not a skeleton or empty-result claim. It retains the Site name, page content, cross-destination links, and one retry action. The capture metadata reports two H1s: the shell's canonical H1 plus the page's visible H1. | Settled-state gap closed. Visible title changed to H2 without changing its styling; exact-source render remains pending. |
| Spatial assets destination, 390/768/1440 | Actual Core metadata and work-area selection guidance are shown; no asset measurements are fabricated. | Preserved. |
| External-results panel, 390/768/1440 | Typed load error and history action remain visible; no zero-pending assertion is made. | Preserved. |
| Work queue, 390/768/1440 | The rendered fixture separates 2 decision-needed, 2 in-progress, 0 operations-review, and 1 completed records. The external reconstruction is in progress. | Preserved; values retain their existing source meaning. |
| External work detail and lower scroll, 390/768/1440 | Registration/operations content remains present; mutation controls stay laptop-gated. The comparison list shows an unavailable read, and single-volume measurement explicitly says the local environment is not configured. It does not claim no requests exist. The focused skip link is visible over lower-page content in the 390/768 captures. | Workflow state is correctly represented; no API/config change. Skip-link placement fix is in this round, but no changed-source lower-scroll render is available. |
| Historical work detail, 390/768/1440 | Labeled historical record remains readable, exposes no managed mutation controls, and states that no current external-registration flow exists for that historical record. | Preserved. |
| Keyboard first Tab and skip geometry | At 390/768, the first Tab reaches the skip link. At 1024/1440, first Tab reaches sidebar search instead. Separate locator-focus geometry shows the link fits within main width, but is not evidence of keyboard order. | Fixed in source by placing the link first in the main-column shell flow before TopBar and DesktopSidebar in DOM order. Existing real first-Tab, main-bound geometry, and Enter-to-main assertions remain unchanged. Exact-width post-edit renders required. |
| Empty Home/Sites/Work and foreign Site denial, 390/768/1440 | Empty states remain honest. Empty Sites has one real registration action; the foreign Site remains generic and discloses no Site name. | Preserved; no scope expansion. |

### Concrete defect ledger

| Stable ID | Severity | Defect and desired result | Revision and evidence status |
|---|---|---|---|
| `T4-SKIP-01` | P2 | First Tab bypassed the skip link at desktop widths; on the lower work captures the focused link also covered content. Make it first in keyboard order and keep it in the content column without covering navigation or page content. | Moved the existing anchor ahead of TopBar and sidebar in DOM order; desktop content/sidebar grid placement is explicit. Kept the existing first-Tab, link-to-main bounds, Enter-to-main, and route-focus checks. Source check passes; changed-source render at 390/768/1024/1440 is still required. |
| `T4-ANALYSIS-ROUTE-02` | P1 | A child analysis API 404 was treated as Site absence, hiding a valid Site and incorrectly presenting generic denial. Preserve foreign-Site nondisclosure while showing a typed unavailable/error state for optional child reads. | Split Site access from child reads in `src/app/sites/[siteId]/analysis/page.tsx`. Added page-component tests for valid Site + child 404, Site 404 before child calls/no name disclosure, no fabricated numeric results, and transient retry. Added actual gateway-to-analysis E2E assertions for Site context, unavailable copy, no zero-results claim, and no retry for the local 404. Test execution is pending: local Vitest could not start (see checks). Changed-source render at 390/768/1440 and real foreign-Site denial capture remain required. |
| `T4-OBS-H1-01` | P2 | Settled observation captures contain two H1s at all three widths (shell canonical H1 plus visible title). Keep one document H1 and retain the visible title. | Changed the visible observation title to H2 while preserving existing text and classes. Added actual-route E2E assertions for one H1, visible H2, and the settled typed error. Changed-source render required. |
| `T4-OBS-SETTLED-01` | P2 | Prior evidence lacked a settled observation destination. | Closed as an input gap: all three frozen `actual-observations` images are settled and show the real retryable error; 59-row capture metadata confirms settled state, 0 page errors, and 0 overflow. The H1 correction is separately tracked above and awaits changed-source renders. |
| `T4-OPTIONAL-WORKFLOW-01` | P2 | Prior lower-page evidence had not settled optional workflow reads. | Closed as a product-state question, not an API change: new bottom-scroll captures show unavailable comparison history and explicit single-volume configuration absence. Six recorded 404s match the unconfigured optional workflow. Keep typed unavailable states; never convert these to zero/empty success or add local graph configuration. |
| `T4-HOME-BASELINE-01` | P2 | Four retained Home images are historical and differ from current source/data projection; no fresh post-edit Home renders are available. | No baseline refreshed or adopted. Require exact-current-source Home captures at 390/768/1024/1440, review them against the retained images, then decide. |

The earlier empty-Sites registration CTA, foreign-Site H1, historical read-only selector, Site-action test, and Home projection changes remain supported by the new captured states. This round did not alter their source. Site create/update, team, and pending-workflow endpoints remain unavailable under the intentionally narrow OIDC scope and are later-slice constraints, not grounds to add grants here.

### Verification and changed-source identity

| Check | Round 2 result |
|---|---|
| Dashboard `tsc --noEmit --pretty false` | Passed after this round's edits. |
| ESLint on the five changed source/test files | Passed after this round's edits. |
| `git diff --check` | Passed after this round's edits. |
| Focused Vitest `test/analysis-page.test.tsx` | Could not start: installed Rolldown has no native binding (`@rolldown/binding-wasm32-wasi`). No install or workaround was attempted; the added tests are unverified here. |
| Changed-source browser E2E, Next build, and rendered screenshots | Not run here. No runtime was launched. Prior host tsc/eslint/Vitest/build and 45/16/15 E2E results predate these edits and do not verify this round. |

Exact SHA-256 values for the changed files that Outer Build must bind its next captures to:

| File | SHA-256 |
|---|---|
| `src/app/layout.tsx` | `4857f55552d8a1f95e08661a465ea77305fac44a4b403a136bd4a835e8c66195` |
| `src/app/sites/[siteId]/analysis/page.tsx` | `46707bf8364325d5ac22db67432e81ee9cc634f5381f35ddfa9008ee127f7bb2` |
| `src/app/sites/[siteId]/observations/page.tsx` | `0cbb3f6cafd97534bd0f66fae3d60e8f34dde45b1b192698bd55150a0cfa4e1b` |
| `test/analysis-page.test.tsx` | `158b44f613b6e8be8f24a91b21bcec78ca380020ef69cd56679bc9944c856126` |
| `e2e/operations-console.spec.ts` | `6bce0beccdac0b9575be18b662e07e6625717f6326f394be1fe758c6c3e0d0a4` |

### Before/after limits and required next captures

The frozen 59 images are genuine pre-edit renders bound to the 237-file snapshot above. No matching after images exist for this round; no source-only or static-check claim is rendered closure. Outer Build should capture the exact changed hashes above at: (1) keyboard first-Tab and focused-link geometry on Home at 390/768/1024/1440, including Enter-to-main; (2) direct analysis reached from its Site gateway at 390/768/1440, plus foreign-Site 404 nondisclosure at those widths; (3) observation history at 390/768/1440; (4) external-work lower scroll at 390/768/1440; and (5) Home at 390/768/1024/1440 for the baseline decision. Keep all screenshot baselines unchanged until those captures are visually reviewed against the exact source. The existing host remains the only product render target; sandbox loopback availability was not assumed.

### Round 1 report (historical; superseded where Round 2 above differs)

Date: 2026-10-08  
Status: **PROVISIONAL** — pre-edit product captures were reviewed, but this sandbox could not render the edited sources against the host application. Outer Build must provide changed-source captures before visual acceptance.

## Scope and review basis

Reviewed the existing Dashboard source directly. Preserved the existing brand, global tokens, Home hierarchy/carousel, desktop Sites comparison table, one row action, and five Site workspace tabs. No backend, permission, endpoint, numerical meaning, or evidence/currentness contract was changed. The local optional external-result workflow remains unavailable; this review does not imply there are zero pending results.

Applied the selected bundled `web-design-guidelines` skill and its pinned `references/guidelines.md` (Accessibility, Focus States, Navigation & State, Touch & Interaction, Content & Copy). The review kept the established visual system and assessed hierarchy, truthful copy, action visibility, keyboard focus, and semantic headings; it did not score against a new design direction.

## Source and input integrity

- Dashboard real-source write/read/remove probe: `.od-probe-20261008-t4-review` succeeded in this checkout and was removed. No managed copy was used.
- Frozen source snapshot: `p4-cleanup-evidence/t4-inputs-v1/source-snapshot.json`, SHA-256 `55b276216eb2bf56d5e85d61047fafacab03060ff3309e30f4ea8ee2f42f07b5`; recorded HEAD `9a3bab1ba710d0c8925cf3ae8bd8e301e425a9cf`, 240 required-source hashes, all matched before edits.
- Frozen image manifest: `input-sha256.json`, SHA-256 `03ea566206d774c861c83a60aca31af76e22dd37db52236707175aefa254f72b`; all 88 manifest entries matched before edits.
- All 67 supplied PNGs were opened with an image-capable viewer. The 36 primary captures were `home`, `sites`, `site-analysis`, `site-assets`, `site-observations`, `actual-analysis`, `actual-assets`, `actual-observations`, `site-external-error`, `field`, `external-work`, and `historical-work`, each at 390, 768, and 1440 px. The 21 state captures were `keyboard-skip`, `loading-sites`, `external-work-bottom`, `empty-home`, `empty-sites`, `empty-field`, and `denied-site` at the supplied widths. The six motion captures were `carousel-next-no-preference` and `carousel-next-reduce` at 390, 768, and 1440 px. The four historical comparisons were `retained-baselines/home-mobile-390.png`, `home-tablet-768.png`, `home-desktop-1024.png`, and `home-desktop-1440.png`.

## Screen and state findings

| Screen/state | Rendered evidence and user impact | Disposition |
|---|---|---|
| Home, 390/768/1440 | Existing hierarchy is present: count line, typed source warnings, attention carousel, initial-setup area, and recent updates. The warnings accurately avoid guessing counts or claiming there are no external decisions. No Home source/style change. | Preserved; confirm only with changed-source captures. |
| Sites populated, 390/768/1440 | Mobile/tablet cards and desktop comparison table remain readable; desktop has one `현장 열기` row action. No clipping or horizontal overflow in evidence. | Preserved. |
| Site workspace and tabs, 390/768/1440 | Workspace tabs and selected-section content remain visible with responsive navigation. The direct analysis tab capture is distinct from the `/analysis` destination below. | Preserved; do not infer direct-route coverage from the tab shell. |
| Spatial assets destination, 390/768/1440 | Actual destination shows its work-area selector and Core metadata explanation; no fabricated asset values. | Preserved. |
| Observation history destination, 390/768/1440 | Supplied captures show loading skeletons rather than a settled list, so content density and final unavailable/empty state cannot be judged. | Open: obtain settled capture. |
| Direct analysis destination, 390/768/1440 | `/sites/e2e-site-workspace/analysis` renders the generic access-denied/not-found state in all three images, not the analysis screen. The copy does not disclose the Site name. Capture evidence records one `page-has-heading-one` moderate finding per width. | Heading semantics fixed locally; access/result discrepancy remains open and must not be addressed by widening grants. |
| External-results panel, 390/768/1440 | Typed failure with retry and history link is visible; it does not claim a zero-pending result. | Preserved. |
| Work queue, 390/768/1440 | Two decision candidates, two in-progress records, zero operations-review rows, and one completed row are legible. The external order appears in progress. | Preserved. |
| External work detail and bottom scroll, 390/768/1440 | Registration and operations modules are visible on desktop; smaller widths clearly gate mutation actions to laptop-sized screens. The lower page shows optional workflow reads, but screenshots retain loading copy and do not prove their final typed-unavailable state. | Preserve laptop gating and no-success claims; obtain settled lower-page capture. |
| Historical work detail, 390/768/1440 | Correct historical title/status and the explicit absence of a current external-registration flow are visible. No managed execution or mutation controls are shown. | Preserved; test now selects the labeled historic fixture. |
| Empty Home / Sites / Work, 390/768/1440 | Home and Work show truthful empty states. Empty Sites exposed unsupported KMZ/DJI Pilot and second-survey instructions; desktop duplicated the registration CTA, while mobile had no direct registration link. | Corrected with existing tokens/components and one direct, permission-gated registration action. |
| Foreign/denied Site, 390/768/1440 | Generic denial message and return-to-list action are visible, with no foreign Site name. | Added a semantic H1 without changing visual styling or disclosure behavior. |
| Keyboard skip, 390/768/1440 | Focus reaches the skip link and then main content. At desktop widths the fixed link overlapped the sidebar brand. | Moved the link into the main flow only while focused; geometry assertion added. Post-edit rendering is still required. |
| Loading Sites, 390/768/1440 | Actual navigation under CDP throttling shows the existing skeleton; no fabricated list rows. | Preserved. |
| Carousel next, normal/reduced motion, all widths | Enter moved to the second card in all six recorded cases; screenshots show the same destination and layout under both motion preferences. | Preserved. |
| Historical Home baselines, four widths | Old images show three attention cards and older copy/layout without current typed-unavailable warnings. They do not represent the reviewed current data projection. | Do not adopt or overwrite. See baseline decision below. |

Evidence discrepancy: `capture-live-review-v1.json` contains 36 rows, zero page errors, and no width-overflow rows. Its stored `a11y` arrays contain **three moderate `page-has-heading-one` findings** on the direct analysis route (one per width), despite the upstream note saying zero axe violations. The same evidence records two H1s on observation-history and both work-detail routes at all three widths. This report follows the actual JSON/image evidence rather than repeating the conflicting summary. Work-detail duplication was fixed; the direct analysis not-found heading was fixed. Observation-history heading duplication was not edited because its capture is still skeleton/loading and must be reviewed in a settled state.

## Defect ledger and changes

| Stable ID | Severity | Finding and desired result | Disposition / files |
|---|---|---|---|
| `T4-EMPTY-SITES-01` | P1 | First-run Sites screen taught an unverified KMZ/DJI flight and analysis sequence. Desktop duplicated the registration action; mobile presented no direct action. Keep only supported registration/workspace guidance and one real permission-gated CTA on every width. | Fixed in `src/app/sites/SiteOnboarding.tsx` and `src/app/sites/page.tsx`; added empty-organization behavior assertions. |
| `T4-SKIP-01` | P2 | Focused skip link covered desktop sidebar branding. Keep it visible and keyboard-operable without covering the brand or content. | Fixed in `src/app/layout.tsx` and `src/app/globals.css`; added main-bound geometry assertions. Provisional pending rendered review. |
| `T4-H1-01` | P2 | Work details had the shell's screen-title H1 plus a second H1 for the work order. Maintain one document H1 and retain the work order as the visible next-level heading. | Fixed H1→H2 in `src/app/field/work-orders/[workOrderId]/page.tsx`; E2E asserts one H1 and the named H2. |
| `T4-DENIED-HEADING-01` | P2 | Segment denial state had no H1, matching the three moderate findings on the direct analysis route. Keep generic non-disclosing denial copy with a semantic page heading. | Fixed H2→H1 in `src/app/sites/[siteId]/not-found.tsx`; added a no-site-name E2E assertion. |
| `T4-EMPTY-ROLE-01` | P3 | E2E expected an EmptyState paragraph title to be a heading. Preserve content and verify the actual rendered role/text. | Test selector corrected in `e2e/empty-organization.spec.ts`; title, description, single action, and retired-control assertions remain. |
| `T4-SITE-ACTION-01` | P2 | E2E expected a removed “다음 행동” section instead of the surviving observation action. Preserve the real destination and all tab/context/reload checks. | Test now verifies `새 관측 시작` links to `/sites/{siteId}/observations/new`; unavailable/empty text uses its rendered text role in `e2e/operations-console.spec.ts`. |
| `T4-HISTORIC-READONLY-01` | P1 | E2E selected the first work-order row and incorrectly expected known MANAGED history to be UNVERIFIED. Select the labeled historic record; verify its actual status, disclosure, and absence of mutation/registration controls. | Test corrected in `e2e/operations-console.spec.ts`; unknown/mismatched-context fail-closed coverage remains untouched. |
| `T4-ANALYSIS-ROUTE-02` | P1 / scope gate | Direct analysis route renders the generic denial state while the Site workspace tab itself renders. Confirm intended route availability from the correct authorized source evidence. | Open. No grant, permission, or API change made. |
| `T4-OBS-SETTLED-01` | P2 | Direct observation-history capture is still skeleton/loading. Final list/error/empty state remains unreviewed. | Open; requires a settled actual-host capture. |
| `T4-OPTIONAL-WORKFLOW-01` | P2 | External work lower-page captures show loading strings for optional endpoints that are not configured locally; they do not prove the final typed unavailable state. | Open; preserve unavailable semantics and obtain settled captures. No API/config changes. |

## Baseline decision and before/after limits

**Decision: keep all four Home screenshot baselines unchanged and do not use them as the current visual oracle.** Their three-card content and old copy differ from the approved two-candidate projection and the current truthful source-unavailable warnings. The supplied current captures support the preserved structure, but they are pre-edit and source-bound to the T2c snapshot; they cannot validate the source edits in this review. Outer Build may mechanically regenerate only after it captures the exact changed source and adjudicates those differences. No baselines were modified here.

The host evidence supplied for the prior T2c run reports 45 passing, 16 failing, and 15 skipped E2E cases across four width projects. The 16 failures were reported as four repeated contract-query families, not evidence of a broken data path. The selector changes above target the three described query families; the Home visual mismatch remains intentionally unresolved until actual post-edit review. No browser/E2E or host-server test was run in this sandbox, and no substitute runtime was launched.

## Verification and exact post-edit source hashes

| Check | Result |
|---|---|
| `./node_modules/.bin/tsc --noEmit --pretty false` | Passed (exit 0). |
| `./node_modules/.bin/eslint .` | Passed (exit 0). |
| `git diff --check` | Passed (exit 0). |
| Site-onboarding retired-copy search | Passed: no DJI Pilot, KMZ, initial mapping-flight, or “second survey” instruction remains in `SiteOnboarding.tsx`. |
| Vitest / browser E2E / actual host screenshots after edit | Not run here. No host runtime was launched; visual changes remain provisional until outer Build supplies new captures. |

Hashes below identify the exact changed source/test files for the required post-edit capture and review:

| File | SHA-256 |
|---|---|
| `src/app/field/work-orders/[workOrderId]/page.tsx` | `f9a6e854f9c0718cd4afbb7c2d1af9efcd6c03252870ee5357bb1ecb7cc699b1` |
| `src/app/sites/[siteId]/not-found.tsx` | `68152698ab59838e35028dd63e3c385e3c4e8ba688b54fc56ae5f9b464354c39` |
| `src/app/sites/SiteOnboarding.tsx` | `760c9a45731b13c82376be52525821ee30b5f9e14029864c55b9713d0f21f481` |
| `src/app/sites/page.tsx` | `c90155fc8bdad768e55bb9852e0c245e76d2657350ee10383c20ef6fe4a2cf20` |
| `src/app/layout.tsx` | `34f350f6c8649baf01ec3f223aaaec14bbe642b2131afa43bd1588520ac8db7a` |
| `src/app/globals.css` | `0cab25cb895182296a0fdc565ce4445565bab3502e20cffe21b736c5fe300b47` |
| `e2e/empty-organization.spec.ts` | `27fb9eefa41408ce0357b2a1a080f7c961f754339be8bfb6042b09f4cb32351c` |
| `e2e/operations-console.spec.ts` | `e7c4d01e8df92a2a50feb06f3ac810337b25805a14fed0b87ebd52f3fd2eb470` |

Required follow-up actual-host states: empty Sites at 390/768/1440; keyboard skip focus at 390/768/1024/1440; foreign-Site denial at 390/768/1440; external and historical work details at 390/768/1440; direct analysis, spatial-assets, and observation-history destinations at all three widths; and the external-work lower page after optional reads settle. Compare those captures against the hashes above. Do not treat type/lint or E2E selector success as visual closure.
