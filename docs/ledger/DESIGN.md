# Design index

Current Console design: [`../design/CONSOLE_CURRENT_SPEC.md`](../design/CONSOLE_CURRENT_SPEC.md).
Visual reference: [`../design/CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html`](../design/CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html),
[`../design/CONSOLE_VIEWER_FIRST_2026-10-26.html`](../design/CONSOLE_VIEWER_FIRST_2026-10-26.html)
and the prior dense board [`../design/CONSOLE_DESKTOP_FIRST_2026-10-26.html`](../design/CONSOLE_DESKTOP_FIRST_2026-10-26.html).

## Decisions in force

- Desktop-first 1440; the site is the object; the spatial stage is the hero.
- Global rail: current site only expands; its sections are 작업공간/자료/관측 작업/결과; the site
  switcher preserves the section.
- **Viewer-first / Canvas-centric / Minimal GIS** for site **공간** and **자료** exploration:
  56px icon rail, no global top bar/site header at `lg+`, floating layer panel + on-demand
  inspector, toolbar-owned layer toggle. 업무·결과·검토 and site management keep the labelled
  rail and list/form density.
- Materials: floating catalog at `lg+` (open by default at `xl`), stage, on-demand compact
  inspector; details collapsed; request form in a native dialog. At 1024–1279 the catalog
  defaults closed and the explanatory purpose line/redundant "보기 방식" label are hidden so the
  toolbar stays one row.
- Expired/unprepared stage: real registered extent + actual prepared-window bounds; no fake pixels.
  The site workspace now uses the same extent canvas.
- Unknown units/rights/retention/accuracy remain explicit.
- No legacy tabs, duplicate ledgers or design-board-as-product.

## Decided — 2026-10-26

- **Viewer-first / Canvas-centric / Minimal GIS** for site **공간** and **자료** exploration.
  Comparison: [`../design/CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html`](../design/CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html);
  full screen: [`../design/CONSOLE_VIEWER_FIRST_2026-10-26.html`](../design/CONSOLE_VIEWER_FIRST_2026-10-26.html).
- Scope A chosen: 공간/자료 are viewer-first; 업무/결과/검토 stay list/form-first with reduced chrome.
- Implemented on branch `viewer-first-20261026` (product commit `946409c7` after the final
  canvas-first default) and deployed as `ksi-product-dashboard:viewer-first-20261026`
  `sha256:bc8c2d938a0c63ff1d25a65ce8d6ee7a35319ed75f63eb33acdc9d9f41d5a779`.

## Open design decisions

- Mobile site switcher.
- Home/global `내 업무/검토` split (ADR-025/026 approval).
- Theme setting (deferred).

Superseded boards were consolidated here and in `CONSOLE_CURRENT_SPEC.md`; working-tree copies
were removed on 2026-10-26 (Git history only). No archive is kept.
