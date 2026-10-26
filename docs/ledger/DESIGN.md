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
  no global top bar/site header at `lg+`, toolbar-owned layer toggle, a collapsible
  layer panel + on-demand inspector. The global menu defaults labelled; the user explicitly
  expands/collapses it (remembered across routes), not a forced route-dependent56px rail.
  Open panels reserve real columns instead of obscuring the spatial stage. The layer panel
  **starts closed** (not forced) and the closed toggle keeps the current site visible. 업무·결과·검토
  and site management keep their top bar and list/form density, with the same menu preference.
- Materials: docked catalog (224–300px) opens from the toolbar, stage, on-demand compact
  inspector; details collapsed; request form in a native dialog. At 1024–1279 the toolbar hides
  the explanatory line/redundant "보기 방식" label to stay one row.
- Mobile site header keeps the site name, status and tabs and adds a compact **현장 변경** sheet;
  changing sites preserves the current section (workspace/materials/results/work-orders).
  The integration candidate uses native modality and closes on desktop resize or context loss.
- Expired/unprepared stage: real registered extent + actual prepared-window bounds; no fake pixels.
  The site workspace now uses the same extent canvas.
- Unknown units/rights/retention/accuracy remain explicit.
- Home and site list keep a consistent 16:9 neutral cover when no prepared preview exists. The
  cover is explicitly not imagery; it is not a synthetic landscape and makes no extent/accuracy
  claim. Real prepared pixels replace it whenever available.
- Home status/count and `받은 업무함` share one centered line box. Empty-preview site cards do
  not repeat a separate status row; the gallery count appears once and the duplicate visual
  heading is screen-reader-only. The viewer's descriptive purpose line is not shown when the
  visible controls already explain the mode.
- No legacy tabs, duplicate ledgers or design-board-as-product.

## Decided — 2026-10-26

- **Viewer-first / Canvas-centric / Minimal GIS** for site **공간** and **자료** exploration.
  Comparison: [`../design/CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html`](../design/CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html);
  full screen: [`../design/CONSOLE_VIEWER_FIRST_2026-10-26.html`](../design/CONSOLE_VIEWER_FIRST_2026-10-26.html).
- Scope A chosen: 공간/자료 are viewer-first; 업무/결과/검토 stay list/form-first with reduced chrome.
- Implemented on branch `viewer-first-20261026` (product commit `6fe28675`) and deployed as
  `ksi-product-dashboard:viewer-first-20261026`
  `sha256:5cb96229db0297351290e29b9159ae05958fd72dba6d6eda409dd1874bbb55bb`.
- Later follow-through is a **locally verified, non-deployed** candidate on
  `integration/viewer-first-20261026`: remembered menu choice, non-overlapping panels, native mobile
  sheet, SIE P1 integration and capture precision/identity repair. See the existing Console work
  entry and evidence index; the production image above is unchanged and still has the older shell.

## Open design decisions

- Home/global `내 업무/검토` split (ADR-025/026 approval).
- Theme setting (deferred).

Superseded boards were consolidated here and in `CONSOLE_CURRENT_SPEC.md`; working-tree copies
were removed on 2026-10-26 (Git history only). No archive is kept.
