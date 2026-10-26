# Evidence index

One row per verified batch. Raw files stay in the state/evidence directories; this index records
what was checked and what remains unverified.

| Date | Work | Evidence | Checks | Limits |
|---|---|---|---|---|
| 2026-10-26 | Console site-context rail | `~/.local/state/ksi-console-ia-20261025/site-context-nav-20261026/` | 2127 unit, tsc 0, lint 0, Docker build, production 1440/1024/390, axe 0 | Mobile switcher absent; real imagery expired |
| 2026-10-26 | Materials 3-pane/compact inspector/request dialog | `~/.local/state/ksi-console-ia-20261025/materials-desktop-fix-20261026/` | 2131 unit, tsc 0, lint 0, Docker build, production 1440/390, axe 0 | Desktop extent canvas initially absent; real pixels unavailable |
| 2026-10-26 | Expired extent canvas | same materials evidence dir; image `366cd850a234fb41161e09e51df71d73b14efc2c0bc1d1a7718a2ea720749019` | production 1440/390, axe 0 | EPSG:7850 unit unknown; no metric scale/accuracy claim |
| 2026-10-26 | Viewer-first site 공간/자료 | `~/.local/state/ksi-console-ia-20261025/viewer-first-20261026/`; image `8efc8dc2eb56746ef062068a48c93bf0a3915cca0a0b3a75f9514279323a4a50`; branch `viewer-first-20261026` | 2142 unit, tsc 0, lint 0, Docker build, production 1440/1024/390, axe 0 at home/sites/materials/workspace, client nav, desktop+mobile site switcher section preservation, collapsible panel/inspector Escape+focus, request dialog, mobile sheets; visual covers on home/site cards, canvas-first default | Real imagery retention-expired; no metric/field/customer claim |

External/customer/field evidence is not implied by local UI verification.
