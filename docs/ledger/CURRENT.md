# Current

Updated: 2026-10-26. Entry point for the current product/work state.

## Authority

Conflict precedence (not a reading sequence): [`../00_READ_FIRST.md`](../00_READ_FIRST.md) → Constitution → Final Decision
Ledger → PRD → relevant contracts → accepted ADR → acceptance → this ledger. The ledger never
overrides those files.

## Product slice

[`../superpowers/product-state.md`](../superpowers/product-state.md) remains the slice SSOT.
Current state is unchanged by this ledger: platform/engine work is active; customer/field/EXT-VAL
acceptance remains external and unverified.

## Active work

| Work | Owner | Status | Evidence / next |
|---|---|---|---|
| Console desktop-first UX | Build | Viewer-first deployed | [`work/2026-10-26-console.md`](work/2026-10-26-console.md) — 56px viewer rail, full-bleed site 공간/자료, collapsible layer/inspector, visual site covers, real extents; dense 업무/결과/검토 retained |
| Spatial engine integration | Build | Active, separate uncommitted stream | [`../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md`](../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md) — do not duplicate here until close |
| Ledger/document consolidation | Build | Active | This directory; legacy console boards deleted after consolidation |

## Current design

[`../design/CONSOLE_CURRENT_SPEC.md`](../design/CONSOLE_CURRENT_SPEC.md) and
[`../design/CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html`](../design/CONSOLE_VIEWER_FIRST_COMPARISON_2026-10-26.html).
Desktop-first, site-centric, viewer-first for site 공간/자료, list/form-first for 업무/결과/검토,
real extents, consistent neutral site covers when no prepared preview, no fake imagery, no
duplicate work authority.

## Open decisions / limits

- Viewer-first scope A is **implemented and deployed** for site 공간/자료; 업무/결과/검토 stay
  list/form-first. See [`DESIGN.md`](DESIGN.md).
- Home structure and global `내 업무/검토` split: ADR-025 D6/D7 / ADR-026 approval and evidence
  required; not implemented.
- Mobile site switcher: not implemented; header tabs remain below `lg`.
- Real Floreat imagery is retention-expired; quantitative/field/customer acceptance unverified.
- Theme selection deferred to a future `설정 > 화면 테마` decision; no palette change.

## Next

1. Add the mobile site switcher and close remaining mobile viewer gaps.
2. Complete the ledger migration for the platform/engine stream when it closes.
3. Revisit Home/global IA only with explicit approval and required evidence.
