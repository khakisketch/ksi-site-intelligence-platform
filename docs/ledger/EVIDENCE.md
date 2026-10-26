# Evidence index

One row per verified batch. Raw files stay in the state/evidence directories; this index records
what was checked and what remains unverified.

| Date | Work | Evidence | Checks | Limits |
|---|---|---|---|---|
| 2026-10-26 | Console site-context rail | `~/.local/state/ksi-console-ia-20261025/site-context-nav-20261026/` | 2127 unit, tsc 0, lint 0, Docker build, production 1440/1024/390, axe 0 | Mobile switcher absent; real imagery expired |
| 2026-10-26 | Materials 3-pane/compact inspector/request dialog | `~/.local/state/ksi-console-ia-20261025/materials-desktop-fix-20261026/` | 2131 unit, tsc 0, lint 0, Docker build, production 1440/390, axe 0 | Desktop extent canvas initially absent; real pixels unavailable |
| 2026-10-26 | Expired extent canvas | same materials evidence dir; image `366cd850a234fb41161e09e51df71d73b14efc2c0bc1d1a7718a2ea720749019` | production 1440/390, axe 0 | EPSG:7850 unit unknown; no metric scale/accuracy claim |
| 2026-10-26 | Viewer-first site 공간/자료 | `~/.local/state/ksi-console-ia-20261025/viewer-first-20261026/`; image `5cb96229db0297351290e29b9159ae05958fd72dba6d6eda409dd1874bbb55bb`; branch `viewer-first-20261026` | 2142 unit, tsc 0, lint 0, Docker build, production 1440/1024/390, axe 0 at home/sites/materials/workspace, client nav, desktop+mobile site switcher section preservation, collapsible panel/inspector Escape+focus, request dialog, mobile sheets; visual covers on home/site cards, canvas-first default | Real imagery retention-expired; no metric/field/customer claim |
| 2026-10-26 | Combined SIE/viewer integration and UX hardening | `~/.local/state/ksi-console-ia-20261025/integration-20261026/`; isolated `integration/viewer-first-20261026` | backend406, fixture/boundary38, locked UI2225/218files +lint/build/types; actual two-cycle UI/Core/worker synthetic E2E, immutable first result, viewer403;1440/1024/768/390,19Console+7analysis axe scans0 (incomplete retained); native modality/keyboard/resize/site switch, menu preference/reload, real panel-column nonoverlap; capture precision red→green regressions; original main/deployed image preserved | Not deployed/main-merged/customer/field/OS acceptance; preparation-record positive-pixel lane unavailable in fixture; delta/mask contracts still unresolved; no physical screen reader/touch test |

External/customer/field evidence is not implied by local UI verification.
