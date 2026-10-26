# Evidence index

One row per verified batch. Raw files stay in the state/evidence directories; this index records
what was checked and what remains unverified.

| Date | Work | Evidence | Checks | Limits |
|---|---|---|---|---|
| 2026-10-26 | Console site-context rail | `~/.local/state/ksi-console-ia-20261025/site-context-nav-20261026/` | 2127 unit, tsc 0, lint 0, Docker build, production 1440/1024/390, axe 0 | Mobile switcher absent; real imagery expired |
| 2026-10-26 | Materials 3-pane/compact inspector/request dialog | `~/.local/state/ksi-console-ia-20261025/materials-desktop-fix-20261026/` | 2131 unit, tsc 0, lint 0, Docker build, production 1440/390, axe 0 | Desktop extent canvas initially absent; real pixels unavailable |
| 2026-10-26 | Expired extent canvas | same materials evidence dir; image `366cd850a234fb41161e09e51df71d73b14efc2c0bc1d1a7718a2ea720749019` | production 1440/390, axe 0 | EPSG:7850 unit unknown; no metric scale/accuracy claim |
| 2026-10-26 | Viewer-first site 공간/자료 | `~/.local/state/ksi-console-ia-20261025/viewer-first-20261026/`; image `9c21ecfcedd627fb5954a46a222e53aac813dfbfeb5aa59aa5d4107b8b806d11`; branch `viewer-first-20261026` | 2140 unit, tsc 0, lint 0, Docker build, production 1440/1024/390, axe 0 at 6 checks, client nav, site switcher, panel/inspector Escape+focus, request dialog, mobile sheets | Real imagery retention-expired; mobile site switcher absent; no metric/field/customer claim |

External/customer/field evidence is not implied by local UI verification.
