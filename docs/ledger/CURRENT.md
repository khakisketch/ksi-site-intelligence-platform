# Current

Updated: 2026-10-27. Entry point for the current product/work state.

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
| Engine + Console integration | Build | P1 + P2 local integration and Dashboard package relocation verified; activation/customer/target-image gates blocked; not deployed or merged to main | [`work/2026-10-26-console.md`](work/2026-10-26-console.md) + [owning SIE plan](../superpowers/plans/2026-10-25-spatial-intelligence-engine-integration.md#dashboard-standalone-package-follow-up--2026-10-27) — actual Console mask→V3→separate delta retained; default Turbopack/Webpack builds and external-path package startup/static/auth-denial checks pass; UI2425/type/lint; Linux ARM64/Node24 proof only, no Docker/host/customer acceptance inferred |
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
- Real Floreat imagery is retention-expired; quantitative/field/customer acceptance unverified.
- Theme selection deferred to a future `설정 > 화면 테마` decision; no palette change.
- P2 independent masks/new profile and separate delta publication are approved and locally verified.
  New policy/runtime signing, deployment-host containment, permitted retained data and customer
  quantitative acceptance remain external activation/acceptance gates, not reasons to stop local work.

## Next

1. Complete the ledger migration for the platform/engine stream when it closes.
2. Revisit Home/global IA only with explicit approval and required evidence.
3. Verify the existing isolated integration candidate before any main merge/deployment; original
   main changes remain protected. Do not restart the older shared runtime to test this candidate.
4. P2 local implementation and generated-byte/replay/Console verification are complete at the owning
   SIE plan's scope. Further activation/customer acceptance needs genuine signing, host containment,
   target-image/signed release and permitted data/consumer inputs; synthetic success does not supply
   those gates. Same-platform Dashboard packaging/relocation is now verified in the SIE follow-up;
   Docker Node22 Alpine and full-platform/production portability are not thereby established.
