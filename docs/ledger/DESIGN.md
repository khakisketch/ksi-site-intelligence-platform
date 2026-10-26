# Design index

Current Console design: [`../design/CONSOLE_CURRENT_SPEC.md`](../design/CONSOLE_CURRENT_SPEC.md).
Visual reference: [`../design/CONSOLE_DESKTOP_FIRST_2026-10-26.html`](../design/CONSOLE_DESKTOP_FIRST_2026-10-26.html).

## Decisions in force

- Desktop-first 1440; the site is the object; the spatial stage is the hero.
- Global rail: current site only expands; its sections are 작업공간/자료/관측 작업/결과; the site
  switcher preserves the section.
- Materials: persistent catalog at ≥1280, stage, compact inspector; details collapsed; request
  form in a native dialog.
- Expired/unprepared stage: real registered extent + actual prepared-window bounds; no fake pixels.
- Unknown units/rights/retention/accuracy remain explicit.
- No legacy tabs, duplicate ledgers or design-board-as-product.

## Open design decisions

- Site workspace extent canvas/compact chrome.
- Mobile site switcher.
- Home/global `내 업무/검토` split (ADR-025/026 approval).
- Theme setting (deferred).

Superseded boards were consolidated here and in `CONSOLE_CURRENT_SPEC.md`; working-tree copies
were removed on 2026-10-26 (Git history only). No archive is kept.
