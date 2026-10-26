# Current

Updated: 2026-10-26. Entry point for the current product/work state.

## Authority

Read in order: [`../00_READ_FIRST.md`](../00_READ_FIRST.md) → Constitution → Final Decision
Ledger → PRD → relevant contracts → accepted ADR → acceptance → this ledger. The ledger never
overrides those files.

## Product slice

[`../superpowers/product-state.md`](../superpowers/product-state.md) remains the slice SSOT.
Current state is unchanged by this ledger: platform/engine work is active; customer/field/EXT-VAL
acceptance remains external and unverified.

## Active work

| Work | Owner | Status | Evidence / next |
|---|---|---|---|
| Console desktop-first UX | Build | Verified increment | [`work/2026-10-26-console.md`](work/2026-10-26-console.md) — site-context rail, materials 3-pane, compact inspector, request dialog, expired extent canvas |
| Spatial engine integration | Build | Active, separate uncommitted stream | [`../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md`](../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md) — do not duplicate here until close |
| Ledger/document consolidation | Build | Active | This directory; legacy console boards archive only |

## Current design

[`../design/CONSOLE_CURRENT_SPEC.md`](../design/CONSOLE_CURRENT_SPEC.md) and
[`../design/CONSOLE_DESKTOP_FIRST_2026-10-26.html`](../design/CONSOLE_DESKTOP_FIRST_2026-10-26.html).
Desktop-first, site-centric, real extents, no fake imagery, no duplicate work authority.

## Open decisions / limits

- Viewer-first adoption: **A decided** (2026-10-26) — 공간/자료 viewer-first; 업무/결과/검토
  list/form-first. Implementation pending. See [`DESIGN.md`](DESIGN.md).
- Home structure and global `내 업무/검토` split: ADR-025 D6/D7 / ADR-026 approval and evidence
  required; not implemented.
- Site workspace extent canvas: next visual slice; not yet enabled there.
- Mobile site switcher: not implemented; header tabs remain below `lg`.
- Real Floreat imagery is retention-expired; quantitative/field/customer acceptance unverified.
- Theme selection deferred to a future `설정 > 화면 테마` decision; no palette change.

## Next

1. Apply the extent canvas and compact chrome to the site workspace.
2. Complete the ledger migration for the platform/engine stream when it closes.
3. Revisit Home/global IA only with explicit approval and required evidence.
