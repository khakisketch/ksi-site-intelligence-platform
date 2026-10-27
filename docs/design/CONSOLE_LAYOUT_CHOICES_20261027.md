# 현장 상세 레이아웃 선택지 — A/B/C 비교 (2026-10-27)

 companion to [`CONSOLE_LAYOUT_CHOICES_20261027.html`](CONSOLE_LAYOUT_CHOICES_20261027.html).
 Ordinary, NON-PRODUCTION design comparison extension. Governing design
 (`CONSOLE_CURRENT_SPEC.md`, ledger `DESIGN.md`, product authority chain) remains in force.
 No final layout selected. No production route, contract, token, or ledger change.

## Scope

- User asked to **see actual A/B/C layouts before selecting**: the reported pain is
  unreadable lists, hidden lists, and dispersed area/observation selection.
- Prototypes cover **현장 상세 (workspace/space) + 자료 (materials)** only.
  No production route changes; no 업무/결과/검토 recomposition.
- Shared neutral KSI identity across all three variants; light/dark toggle is
  **review-only** (no theme-setting change).
- Choice control records **local browser preference only** — not conversation
  history, not product approval.
- State chooser (empty / loading / error / expiry) is **illustrative**, not live state.
- Global Home / Work / Results controls disclose **outside comparison scope**.

## Three choices and tradeoffs

- **A · 탐색 목록형** — left visible date/asset catalog + center preview.
  Strength: catalog always visible, matches "목록은 어디에" expectation; date/asset
  selection is one glance. Cost: center preview narrower at constrained widths;
  mobile required a row-visibility fix (resolved in artifact).
- **B · 공간·시간선형** — wide preview with lower date strip + table.
  Strength: spatial hero is largest; timeline strip keeps date context while preview
  dominates. Cost: catalog becomes a bottom strip/table — list readability depends on
  that strip; hidden-list concern shifts downward rather than disappearing.
- **C · 목록·상세형** — wide master table + selected preview.
  Strength: densest list-first reading; closest to 업무/결과 table grammar.
  Cost: preview is subordinate; file/date collision in the master row required a fix
  (resolved in artifact).

All three share the same two independent image panes, selection/filter/search,
detail/Escape behavior, and full linked public-image source + CC BY acknowledgments.

## Controls / how to review

- Open `CONSOLE_LAYOUT_CHOICES_20261027.html` standalone, or via the same-origin
  preview server `http://127.0.0.1:8856/preview.html` (port is **preview only**).
- Top-level: A/B/C switcher, 현장 상세/자료 surface switch, state chooser
  (empty/loading/error/expiry), light/dark review toggle, choice (local preference).
- In-pane: local selection buttons, filter/search (incl. no-match + reset), detail
  open/Escape with focus return, two independent image panes.
- Suggested pass: A → B → C on 현장 상세, then repeat on 자료; try search no-match,
  Escape from detail, and one composed state per variant before deciding.

## Data origin and limits

- Linked public-image crops only (existing KSI design-only crops, unchanged):
  `apps/dashboard/public/design-preview/spatial/ortho-2021.webp`,
  `ortho-2022.webp`, `dsm-2021.webp`, `dsm-2022.webp` (+ `.json` sidecars).
  Source/CC BY acknowledgments are linked in full inside the artifact.
- Rights: CC BY 4.0 · Cambridge Coastcare / DataWA (see
  `/tmp/opencode/ksi-layout-choices-20261027/source-assets.json`).
- **ALL examples are explicitly NOT registered data**: no API calls, no real
  operations, no recovered Floreat pixels, no numeric suitability claims.
  Coastal Floreat-f3 observations are layout stand-ins, not construction-site evidence.

## Verification and its limits

Per `/tmp/opencode/ksi-layout-choices-20261027/verification.json`:

- 30 width/layout/surface checks: 1440, 1280, 1024, 768, 390 × A/B/C ×
  현장 상세/자료 — no overflow, one active frame, images ready.
- JS errors: 0. axe WCAG scans on 3 desktop variants: 0 violations.
- Interaction checks covered: cross-variant/surface selection persistence,
  no-match search + reset, inspector Escape + focus return, independent A/B
  preview, composed empty/loading/error/expiry states, choice-dialog Escape.
- Reviewer narrow verdict: **ship at comparison-artifact scope** after resolving
  mobile A row visibility and C file/date collision (both resolved in artifact).
- Limits: **physical touch and screen-reader testing not performed**; all
  interactions are illustrative local UI only — no Core requests or record writes.

## No-production-change record

- This companion and its comparison HTML change **no production application**
  routes, tokens, contracts, registered records or behavior. Existing design ledgers
  may link this artifact without selecting a design or granting acceptance.
- No new global visual world, product theme or design-system tokens are introduced.
- Incumbent authorities preserved: `docs/00_READ_FIRST.md` precedence chain,
  Constitution / Decision Ledger / PRD / contracts / ADRs (incl. KSI-036/038/039
  acquisition separation), `CONSOLE_CURRENT_SPEC.md` viewer-first direction,
  ledger `DESIGN.md` decisions, `apps/dashboard/PRODUCT.md` reading-aid status.

## Pending user decision

- No layout selected. Awaiting user selection among A/B/C after visual review.
- Alternatives below are **explicitly user-pinned** (held open for the user),
  not a recommendation pretending one was selected.

## Direction contract (development-only)

1. **Problem.** Before selecting a 현장 상세 composition, the user needs to see
   and compare three real arrangements of the same catalog/preview/selection work.
2. **Non-goals.** No registration, computation, accuracy, settlement, acquisition,
   flight, or production-permission change; no theme-setting or ledger decision.
3. **Alternatives (user-pinned, none selected).** A left-catalog/center-preview ·
   B wide-preview/lower-strip · C master-table/selected-preview — all held open.
4. **Data contract.** Public linked crops only, fully attributed; everything
   labelled non-registered; no pixels recovered, no numbers claimed.
5. **Review contract.** Standalone-or-preview-server artifact; local-only controls;
   composed states illustrative; choice is a browser preference, not approval.
6. **Exit.** User picks a direction (or requests revision); only then does any
   production design/implementation task begin under governing authorities.
