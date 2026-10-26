# Console current spec — desktop-first

Status: current Console design direction (2026-10-26). Subordinate to the product authority chain,
ADR-KSI-025/026 and contracts. This spec does not create endpoints, permissions, storage or a new
site/queue authority.

## One screen model

- Desktop-first 1440×900. The site is the object; the current site's spatial state is the hero.
- Global rail: 홈 · 현장 · 업무 · 계정/도움말. When inside a site, only the current site expands
  under 현장: 작업공간 · 자료 · 관측 작업 · 결과, with a site switcher that preserves the section.
- The site header owns site name, status and settings. Section navigation lives in the rail on
  desktop; the header tabs remain only below `lg` where the rail is absent.
- 자료 at ≥1280px: persistent catalog · spatial stage · selected-material inspector. The catalog
  is not a drawer on desktop.
- Inspector: title, status, four key facts and the next action first. Provenance, history and
  inspection detail collapse under `상세 정보`. Preparation requests open in a native dialog.
- Expired/unprepared stage: show the registered extent, work area/file bounds, actual prepared
  window and dimensions. Never show a fake image or empty poster box.
- `/field` remains the organization work record. The global `내 업무` projection and `검토` queue
  are not implemented; do not relabel `/field` as personal work.

## Current implementation

- Site context rail and switcher: `1b8ed545`.
- Desktop materials 3-pane, compact inspector, request dialog: `589490ca`.
- Expired extent canvas (`SiteMosaicAbsentCanvas`): `49d19a3d`.
- Visual reference: [`CONSOLE_DESKTOP_FIRST_2026-10-26.html`](CONSOLE_DESKTOP_FIRST_2026-10-26.html).
- Audit/evidence: [`CONSOLE_USABILITY_IA_AUDIT_2026-10-26.md`](CONSOLE_USABILITY_IA_AUDIT_2026-10-26.md).

## Invariants

- Real records only. No synthetic fallback image, no invented counts, no claimed accuracy or
  quantitative suitability. Unknown CRS units/retention/rights stay explicit.
- The extent canvas draws file/work-area geometry and actual prepared-window bounds; it is not a
  map, photo or pixel preview.
- Global queues are projections of the site ledger; no duplicate store or new workflow authority.
- No legacy tabs, duplicated site navigation, design-board-in-product or dead prototype
  instructions in active paths.

## Open / next

- Apply the same extent canvas to the site workspace stage.
- Mobile site switcher (desktop rail pattern is not available below `lg`).
- Home structure and global `내 업무/검토` split remain gated by ADR-025 D6/D7 and explicit
  product-owner approval; 4-viewport and projection/E2E evidence required.
- Theme selection is deferred to a future `설정 > 화면 테마` decision; no palette change now.
- Real Floreat imagery remains retention-expired; genuine thumbnail/field/customer acceptance
  remains unverified.

## Superseded design material

Archived at [`../archive/console-design-2026-10/`](../archive/console-design-2026-10/). Those
boards are provenance, not active instructions.
