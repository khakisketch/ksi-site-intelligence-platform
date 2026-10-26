# Console current spec — desktop-first

Status: current Console design direction (2026-10-26). Subordinate to the product authority chain,
ADR-KSI-025/026 and contracts. This spec does not create endpoints, permissions, storage or a new
site/queue authority.

## One screen model

- Desktop-first 1440×900. The site is the object; the current site's spatial state is the hero.
- Global rail: 홈 · 현장 · 업무 · 계정/도움말. When inside a site, only the current site expands
  under 현장: 작업공간 · 자료 · 관측 작업 · 결과, with a site switcher that preserves the section.
- **Viewer-first** for site 공간 and 자료 at `lg+`: no global top bar or site header;
  spatial stage fills the available work surface. The global menu defaults labelled, with an
  explicit expand/collapse control and a remembered choice across routes (no forced 56px rail).
  Layer panel and inspector start closed. Opening either reserves a bounded column, never covers
  the canvas. With compact global navigation, the layer panel also exposes site/section navigation.
- **Dense-first** for 업무 · 결과 · 검토 and site management (`?section=manage`,
  `?section=work-orders`, `?section=results`, `?mode=results`, analysis/observations/work-area
  routes): top bar, site header, table/form density; the same user-controlled 176/232px or56px menu.
- Home and site list use a consistent 16:9 neutral cover when no prepared preview exists. The
  cover is explicitly not imagery and makes no extent/accuracy claim; real pixels replace it
  when available.
- The site header owns site name, status and settings on dense screens; viewer screens use the
  expanded global site's context, or the layer-panel site navigation when the global menu is compact.
  Header tabs remain below `lg`. A compact **현장 변경** native modal sheet changes sites while
  preserving the active section, containing keyboard focus and releasing it on cancel/desktop resize.
- 자료: docked catalog (224–300px) and on-demand selected-material inspector (224–332px). Both start
  closed; the toolbar toggle opens them, and the canvas keeps the full width until the user
  asks for a panel.
- Inspector: title, status, four key facts and the next action first. Provenance, history and
  inspection detail collapse under `상세 정보`. Preparation requests open in a native dialog.
- Expired/unprepared stage: show the registered extent, work area/file bounds, actual prepared
  window and dimensions. Never show a fake image or empty poster box. Site workspace uses the
  same extent canvas.
- `/field` remains the organization work record. The global `내 업무` projection and `검토` queue
  are not implemented; do not relabel `/field` as personal work.

## Current implementation

- Site context rail and switcher: `1b8ed545`.
- Desktop materials 3-pane, compact inspector, request dialog: `589490ca`.
- Expired extent canvas (`SiteMosaicAbsentCanvas`): `49d19a3d`.
- Viewer-first site 공간/자료: branch `viewer-first-20261026`, product commit `6fe28675`;
  production image `ksi-product-dashboard:viewer-first-20261026`
  `sha256:5cb96229db0297351290e29b9159ae05958fd72dba6d6eda409dd1874bbb55bb`.
- Visual site covers (`SiteVisualPlaceholder`), collapsible viewer panels, and mobile site
  switcher.
- **Integration candidate, not deployed:** branch `integration/viewer-first-20261026` carries
  existing SIE readiness/provenance/results plus user-controlled navigation, non-overlapping docked
  panels and native mobile site-change modality. The deployed image above remains the prior UI.
  Current combined evidence: `/tmp/opencode/ksi-integration-20261026/`; see Console work entry.
- Visual reference: [`CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html`](CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html)
  and [`CONSOLE_VIEWER_FIRST_2026-10-26.html`](CONSOLE_VIEWER_FIRST_2026-10-26.html); prior
  desktop board [`CONSOLE_DESKTOP_FIRST_2026-10-26.html`](CONSOLE_DESKTOP_FIRST_2026-10-26.html).
- Audit/evidence: [`CONSOLE_USABILITY_IA_AUDIT_2026-10-26.md`](CONSOLE_USABILITY_IA_AUDIT_2026-10-26.md)
  and `~/.local/state/ksi-console-ia-20261025/viewer-first-20261026/`.

## Invariants

- Real records only. No synthetic fallback image, no invented counts, no claimed accuracy or
  quantitative suitability. Unknown CRS units/retention/rights stay explicit.
- The extent canvas draws file/work-area geometry and actual prepared-window bounds; it is not a
  map, photo or pixel preview.
- Global queues are projections of the site ledger; no duplicate store or new workflow authority.
- No legacy tabs, duplicated site navigation, design-board-in-product or dead prototype
  instructions in active paths.

## Open / next

- Viewer-first direction **A implemented** for site 공간/자료; 업무/결과/검토 remain list/form-first.
  Comparison: [`CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html`](CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html).
- Home structure and global `내 업무/검토` split remain gated by ADR-025 D6/D7 and explicit
  product-owner approval; 4-viewport and projection/E2E evidence required.
- Theme selection is deferred to a future `설정 > 화면 테마` decision; no palette change now.
- Real Floreat imagery remains retention-expired; genuine thumbnail/field/customer acceptance
  remains unverified.

## Superseded design material

Earlier console boards were consolidated into this spec and `docs/ledger/DESIGN.md`; their working
tree copies were removed on 2026-10-26. They remain recoverable from Git history only and are not
active instructions.
