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
  56px icon rail, no global top bar/site header at `lg+`, full-bleed stage with a collapsible
  floating layer panel + on-demand inspector, toolbar-owned layer toggle. The layer panel
  **starts closed** (not forced) and the closed toggle keeps the current site visible. 업무·결과·검토
  and site management keep the labelled rail and list/form density.
- Materials: floating catalog (300px) opens from the toolbar, stage, on-demand compact
  inspector; details collapsed; request form in a native dialog. At 1024–1279 the toolbar hides
  the explanatory line/redundant "보기 방식" label to stay one row.
- Expired/unprepared stage: real registered extent + actual prepared-window bounds; no fake pixels.
  The site workspace now uses the same extent canvas.
- Unknown units/rights/retention/accuracy remain explicit.
- Home and site list keep a consistent 16:9 neutral cover when no prepared preview exists. The
  cover is explicitly not imagery; it is not a synthetic landscape and makes no extent/accuracy
  claim. Real prepared pixels replace it whenever available.
- No legacy tabs, duplicate ledgers or design-board-as-product.

## Decided — 2026-10-26

- **Viewer-first / Canvas-centric / Minimal GIS** for site **공간** and **자료** exploration.
  Comparison: [`../design/CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html`](../design/CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html);
  full screen: [`../design/CONSOLE_VIEWER_FIRST_2026-10-26.html`](../design/CONSOLE_VIEWER_FIRST_2026-10-26.html).
- Scope A chosen: 공간/자료 are viewer-first; 업무/결과/검토 stay list/form-first with reduced chrome.
- Implemented on branch `viewer-first-20261026` (product commit `41dc234f`) and deployed as
  `ksi-product-dashboard:viewer-first-20261026`
  `sha256:2866c73a1c8ab78e80c6d73811d87d87e1ae4057e786f87695c87a5b6a8a6bff`.

## Open design decisions

- Mobile site switcher.
- Home/global `내 업무/검토` split (ADR-025/026 approval).
- Theme setting (deferred).

Superseded boards were consolidated here and in `CONSOLE_CURRENT_SPEC.md`; working-tree copies
were removed on 2026-10-26 (Git history only). No archive is kept.
