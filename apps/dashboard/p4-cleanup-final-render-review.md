# P4 final rendered design review

**Review disposition: visual design review passed for the exact Round 4 source snapshot and all 18 supplied actual-product captures.** I found no remaining design-owned visual defect in the requested P4 slice. This is a read-only design judgment; the independent functional TestRunner receipt is still pending and is not implied by this review.

Reviewed 2026-10-08. This report is the only file created or changed for this review. The prior `p4-cleanup-render-review.md` remains unchanged.

## Bound evidence

- Source snapshot: `p4-cleanup-evidence/t4-round4-render-v1/source-snapshot.json`, SHA-256 `4a66cec660015bd20262cbf6513ba7f136d6ddb7fc17cf5540deea615c1fa3bd`. It binds 353 required source, test, E2E, lock/config, script, and baseline files to head `9a3bab1ba710d0c8925cf3ae8bd8e301e425a9cf`, phase `post-T4-round4-source`. All 353 current file hashes matched at review start and again after visual inspection (0 mismatches).
- Render input manifest: `p4-cleanup-evidence/t4-round4-render-v1/input-sha256.json`, SHA-256 `f67e28d2f236dcbf296358467e637ff3318d578b230a5ab19cb8ec3c95ac30e3`. Its 22 entries (18 PNGs plus the snapshot, capture checks, capture script, and Round 4 pre-final report) all matched their manifest hashes (0 mismatches).
- Exact six-file Round 4 source set digest: `87ababc8428515c90686388a61ef536c964d0c5cceb7310b34c6e08964bad35f`.
- The product screenshots are the supplied settled captures from the real host at `http://localhost:3241/`; I opened and visually inspected every PNG listed below. Capture checks report 18 settled states, one H1 per state, zero axe violations, zero horizontal overflow, and no page, API, or console errors. The real fixture login was restored. These capture facts establish visual evidence for these states only.
- Review standard: the project-pinned [Web Interface Guidelines](.od-skills/web-design-guidelines-f3cc56cce8/references/guidelines.md). I applied its rules for semantic heading order, truthful state copy, accessible links and controls, visible content, responsive layout, and non-overflowing content.

The following six source files constitute the exact Round 4 source set; the SHA-256 values are recorded here so this design disposition remains tied to the reviewed implementation.

| Source file | SHA-256 |
|---|---|
| `src/components/nav/page-title.ts` | `beb5443a2a270975d2f2ea4474f99ba2ba6d9ee4c0194528cb9e128933b12acf` |
| `src/app/sites/[siteId]/spatial-assets/page.tsx` | `e3226b1acabf40a3a5576bf8b16ccfd3e176f78e576d53a9f741435f6ca23faa` |
| `src/app/more/page.tsx` | `1942809e919f9806f631c6231c2e840d45773ee56d1ec8e1436fd89aa7e30893` |
| `test/page-title.test.ts` | `408c0a0f3f43587863a408e9dd00f573674654f2181d510d514324b2a15c3e9b` |
| `e2e/operations-console.spec.ts` | `641d5a27d3f428345d992d78a18a2e5f60fbf783fe967682dcd0262dbbc94153` |
| `e2e/empty-organization.spec.ts` | `3db6f9ce5e26d29dbd7b7a6dd823f369a9e0ac6bbcc4f99c7993f51dcb452e91` |

## Defect-to-render disposition

| Finding | Rendered review and user impact | Disposition |
|---|---|---|
| T4-ASSET-DENIAL-H1-06 | The accessible spatial-assets page shows a coherent shell H1 and visible page H2, with its site context, explanation, selector, action, and supporting navigation visible at 390, 768, and 1440 widths. The actual denied route uses the same one-H1 hierarchy and a generic H2/error explanation plus return link; it does not expose the foreign site name. No clipping, overlap, or horizontal overflow is visible. | **Fixed in the reviewed render.** The accessible and denied states now share a stable page hierarchy while keeping denial copy generic. See the six `actual-assets-*` and `denied-assets-*` captures below. Relevant source: `src/components/nav/page-title.ts:34` and `src/app/sites/[siteId]/spatial-assets/page.tsx` (page heading is rendered as H2). |
| T4-MORE-COPY-07 | At all three widths, More presents “운영 지원 범위와 아직 실장비 검증 전인 기능을 안내합니다.” The only visible destination is the existing “Dock·Edge 지원 범위” link, with its “실장비 검증 전” status. The retired flight/connection/recovery promise is absent. Copy remains readable and the list fits without overflow. | **Fixed in the reviewed render.** The copy accurately describes the support destination and the device-validation limitation without claiming an available capability. See `more-after-*`. Relevant source: `src/app/more/page.tsx:14-16`. |
| T4-ANALYSIS-ALERT-QUERY-08 | Actual analysis captures show the valid site context, one visible typed unavailable alert, and no fabricated empty result, invented number, or retry promise. The Next route announcer remains outside the main error region as intended. | **Design/render fixed; independent functional receipt pending.** Visual review passes at all three widths. Whether the scoped E2E assertion passes belongs to the independent TestRunner, which is still checking; this report does not claim that result. Relevant assertion: `e2e/operations-console.spec.ts:177`. |
| T4-ANALYSIS-H1-03 | Current actual-analysis captures at 390, 768, and 1440 show one canonical H1 with the visible page title as H2 and valid site context. | **Fixed and reconfirmed.** No hidden or unrelated heading is used. See `actual-analysis-*`; title mapping at `src/components/nav/page-title.ts:33`. |
| T4-DENIED-H1-04 | Current denied-site and denied-analysis captures at all three widths show one canonical H1, visible generic H2 denial copy, and no foreign site name. | **Fixed and reconfirmed.** See `denied-site-*` and `denied-analysis-*`. |
| T4-SITE-CTA-QUERY-05 | Round 3 actual Site-workspace captures were previously reviewed at 390, 768, 1024, and 1440. They show the existing in-card “새 관측 시작” link as the unique visible link for that exact intent, with its expected destination. The relevant Site CTA source was not changed in Round 4. | **Previously fixed; valid unchanged-source render binding reused.** Exact Round 3 image hashes are listed below. No selector weakening or removal of the visible action was used. |
| T4-SKIP-01 | The earlier real keyboard-action captures showed first-tab skip-link focus and Enter navigation to main content at all four project widths; the lower-scroll external-work skip-link focus does not cover content after the prior layout correction. | **Previously fixed; unchanged source and accepted Round 2 render binding reused.** This is not a Round 4 change, so it was not recaptured. |
| T4-ANALYSIS-ROUTE-02 | Earlier actual gateway-click captures showed the accessible Site context and honest typed unavailability; the foreign-analysis denial remained generic. | **Previously fixed; unchanged source and accepted Round 2/3 render binding reused.** No optional Core capability, grant, or activation behavior was introduced. |
| Home baseline | The Round 3 review accepted the exact current Home candidate images and the outer owner mechanically adopted those image bytes. All four Home comparisons passed in the supplied post-Round-3 host E2E evidence. No Home source, baseline, mask, or threshold changed in Round 4. | **Previously adjudicated and unchanged.** No new baseline adoption or threshold/mask adjustment is requested. |

## Round 4 PNG access receipt

All 18 PNGs below were opened and visually reviewed. Hashes are SHA-256 from the matching Round 4 input manifest.

| State | Width | Image | SHA-256 |
|---|---:|---|---|
| Actual spatial assets | 390 | `actual-assets-390.png` | `079a420c67c96d29066872c91d046d62fbca6a124cb6810bf00bfde9c8fbe5a0` |
| Actual spatial assets | 768 | `actual-assets-768.png` | `c69d34e937c8edd57a267bce6b7a85fe4897a22516ca386608e6d3915fe9755b` |
| Actual spatial assets | 1440 | `actual-assets-1440.png` | `78ff6f2d095d58d9b65f7cb8a8621c4f4eaa72d72ea52a8b8772673ebcd7f3d1` |
| Denied spatial assets | 390 | `denied-assets-390.png` | `bc1e674582abdc74925f9491c3b9e4e26145b1897515c2215eed47fbc6ed7f27` |
| Denied spatial assets | 768 | `denied-assets-768.png` | `fe1c1dd586e834a300286349726fddab60e9f5f421df8af7ad7d53cebe6600d7` |
| Denied spatial assets | 1440 | `denied-assets-1440.png` | `617f654b72583b0e80b54c19dee7bdfbc64b8f4089895c572b6bfdaf4ae6b44a` |
| More | 390 | `more-after-390.png` | `1eba4c92fd25923da2f3486805ea85fb9ddf6bffd355f12a8981735b8b15f2e1` |
| More | 768 | `more-after-768.png` | `b5f993c314181d5a37cd02fdac63559991202ac8efa4d49d530e86eb8a2c7186` |
| More | 1440 | `more-after-1440.png` | `07716e6c684b59639e44ed8526b5a26b1c99567644de10a018cafd3654494ba6` |
| Actual analysis | 390 | `actual-analysis-390.png` | `875729af3a508371c903e508da09fbdad0b6146687720a9f2691959d7420f2f3` |
| Actual analysis | 768 | `actual-analysis-768.png` | `532f5aa4e96d3b1b51ff0aa3cb9a6c0fcfd2d6f36ef00952792d2c7f6f8339dd` |
| Actual analysis | 1440 | `actual-analysis-1440.png` | `b3250835e4fe20388d0d0ef1ae5253dc7a629b997c2092a7f2fe51ad2b94b56f` |
| Denied analysis | 390 | `denied-analysis-390.png` | `e6d1544b38977752fe91d64ba29f415cf70fe05b8ba1f86bfa2cac1929b29faa` |
| Denied analysis | 768 | `denied-analysis-768.png` | `b278978d97ecce2b946e7e82ac5ac8de4e61c7ecc9e8a35773e6a29f45d0042a` |
| Denied analysis | 1440 | `denied-analysis-1440.png` | `f1dfda1bb4f52846037855e1a0bb51bdc3b0cb0b157f34bd958edf57917b7993` |
| Denied Site | 390 | `denied-site-390.png` | `65befb72b8ddf566278b156b500b7feeccef7597d6c20eb7d948d0041631bc82` |
| Denied Site | 768 | `denied-site-768.png` | `9b16d0c4cbae5992eb825e2fe473c3e62284cdeec5f913a28e986433b27550c7` |
| Denied Site | 1440 | `denied-site-1440.png` | `28c4fd50b9c5137d8b79b214c10d6a536403f9a736f7853c7334573913200007` |

## Reused unchanged render bindings

Round 3 rendered evidence remains applicable only to files and states not changed in Round 4. The relevant image bundle is `p4-cleanup-evidence/t4-round3-render-v1/` (bound to source snapshot SHA `31411b527003454d35b607c2b56d05431c13b2bd913b9cdf9ebb9ae21d16b4aa` and input manifest SHA `136651879af655ec614946794064bd867df46f4db079a7855743bb793abd53e6`). The Round 3 Site-workspace images reviewed for the unique in-card CTA are:

| Image | SHA-256 |
|---|---|
| `site-workspace-390.png` | `f42f92776271375bc5394a3f3368bb86a68f66761ef9795dbfa0cabf0201fb59` |
| `site-workspace-768.png` | `a2067567715cbc5573653df00f2c0c996169aa214e520cb10d58647cc5052279` |
| `site-workspace-1024.png` | `c0174374f1780c904b2dcaa77c4ff3fce53b43ed5e1ecc44f7324f3fa5517d1b` |
| `site-workspace-1440.png` | `2b5069cb756bcf4499de7db0a6aaa414709cb6a679cb2566bbea2650113ee896` |

Round 2 bundle `p4-cleanup-evidence/t4-round2-render-v1/` remains the bound before evidence for the previously reviewed keyboard-first-tab/Enter flow, empty/loading/error states, reduced-motion states, and lower-page skip-link focus. Round 3 reviewed the complete 28-image set, including the unchanged observation and denial states. These prior findings are carried forward only where their source inputs remain unchanged.

## Remaining status and links

- **Design-owned residual defects:** none found in the requested Round 4 render scope.
- **Independent functional verification:** pending the outer TestRunner receipt. In particular, the scoped analysis alert assertion is visually supported here but is not marked functionally passed by this report.
- **Not established by this review:** human acceptance, P5 work, customer-data correctness, product measurement accuracy, external byte display, or production readiness.
- Product evidence host: [http://localhost:3241/](http://localhost:3241/) — temporary loopback service on the DGX host; it is not a customer workstation or public deployment.
- Design context only: [http://localhost:7456/](http://localhost:7456/) — not the product evidence host.
- Round 4 captures: `p4-cleanup-evidence/t4-round4-render-v1/`. Prior Round 3 captures: `p4-cleanup-evidence/t4-round3-render-v1/`.

No application source, tests, configuration, baselines, or prior review report were edited during this report-only review.
