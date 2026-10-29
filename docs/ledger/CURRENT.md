# Current

Updated: 2026-10-29. Entry point for the current product/work state.

## Authority

Conflict precedence (not a reading sequence): [`../00_READ_FIRST.md`](../00_READ_FIRST.md) → Constitution → Final Decision
Ledger → PRD → relevant contracts → accepted ADR → acceptance → this ledger. The ledger never
overrides those files.

## Product slice

[`../superpowers/product-state.md`](../superpowers/product-state.md) remains the slice SSOT.
Current state is unchanged by this ledger: platform/engine work is active; customer/field/EXT-VAL
acceptance remains external and unverified.

## Active work

The Human requested the current in-progress development snapshot be uploaded to GitHub `main` now
so work can continue on another computer. This is a source handoff, not a claim that the outstanding
local security and verification work is complete; preserve the unresolved findings below and the
original worktrees/stash. It does not authorize deployment or customer/host access. External product
acceptance is not an additional gate for this source handoff. Verify Git and the linked work entry
for the actual commit, push and any material not transferred.

| Work | Owner | Status | Evidence / next |
|---|---|---|---|
| Console desktop-first UX | Build | Viewer-first previously deployed; later usability, retry and disclosure improvements are included in this in-progress source handoff, not thereby deployed | [2026-10-29 UX follow-through](work/2026-10-26-console.md#2026-10-29-ux-assessment-follow-through--local-candidate) — 56px viewer rail, real extents, source-bound synthetic desktop/mobile renders and recovery checks; actual user/device and external-host acceptance remain unverified. |
| First-release Console follow-through | Build | First-use and recovery have scoped synthetic verification, not customer acceptance; a reproduced cross-account session race blocks release | [2026-10-29 handoff follow-through](work/2026-10-26-console.md#2026-10-29-development-handoff-follow-through--still-blocked): an offline Dashboard snapshot passed **3,533 unit tests**, lint and typecheck. Five unowned local diagnostic files appeared afterward and caused a later local lint failure; they are excluded from this handoff. The later Webpack-alternative build/package passes with local test fonts, while default Turbopack failed in that no-server font fixture; browser checks were not rerun. Backend **7,003 passed / 55 skipped** remains an earlier separate snapshot, not a final-candidate result. The title diagnostic previously reproduced an empty-title interval and is currently skipped pending an isolated runner. The HTTP-delayed session race remains unresolved; its new Core authority is unmounted. The default-off registration stop is a local recovery aid, not a verified fleet-wide rollback procedure. Current isolated parser→review, prepared host, permitted customer inputs/rights, selected external consumer, signing and deployment authorization remain separate boundaries. |
| Engine + Console integration | Build | P1 + P2 local integration, Dashboard package relocation and Docker target-image proof verified at their recorded snapshots; activation/customer/signing gates blocked; not deployed by the source handoff | [`work/2026-10-26-console.md`](work/2026-10-26-console.md) + [owning SIE plan](../superpowers/plans/2026-10-25-spatial-intelligence-engine-integration.md#docker-target-image-proof--2026-10-27-local-only) — the earlier candidate checkpoint was `d20379cd`; original main's uncommitted work remains preserved. Console mask→V3→separate delta and recorded Linux ARM64 package proofs do not imply signing, host or customer acceptance. |
| Spatial engine integration | Build | Active; separate original-main uncommitted work remains on its original machine | [`../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md`](../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md) — do not assume a clone transfers that working tree or duplicate its ledger |
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
- A/B/C workspace/materials layout comparison is ready for Human selection:
  [`comparison`](../design/CONSOLE_LAYOUT_CHOICES_20261027.html) /
  [`scope`](../design/CONSOLE_LAYOUT_CHOICES_20261027.md). Not selected or applied;
  no change to the governing design, production routes or theme setting.
- Prior research-backed comparison remains available:
  [`interactive A/B/C`](../design/CONSOLE_LAYOUT_RESEARCH_20261027.html) /
  [`evidence and adopt/reject matrix`](../design/CONSOLE_LAYOUT_RESEARCH_20261027.md).
  Original comparison preserved; no layout selected/applied. Competitor research limits
  (especially Angelswing guide access) and prototype-only verification are explicit.
- Latest comparison incorporates the Human's visual-first feedback: keep A's list width,
  remove repeated preview text/default facts and the lower two-date table, separate global
  toast/bell notifications from material badges/popovers, and reserve blocking dialogs for
  session decisions. [`media-first prototype`](../design/CONSOLE_MEDIA_FIRST_20261027.html) /
  [`scope and evidence`](../design/CONSOLE_MEDIA_FIRST_20261027.md), local8858. Both prior
  comparisons preserved; this is not production application or product acceptance.
- P2 independent masks/new profile and separate delta publication are approved and locally verified.
  New policy/runtime signing, deployment-host containment, permitted retained data and customer
  quantitative acceptance remain external activation/acceptance gates, not reasons to stop local work.
- External task handoff now has local existing-area/observed-change implementation and generated
  verification. Actual external AI-host configuration, public/TLS deployment, customer data/accuracy
  and new external grant provisioning are not performed. The selection geometry remains limited to
  registered boundaries (the background-tile question is separate below); an on-demand grid and
  evidence-bound V2 location view show exact coverage.
  Detailed evidence and the bounded task-link lifetime remain in the Console work entry.
- Third-party basemap egress remains the existing [G4 product decision](../product/BETA_PROGRAM.md).
  Source inspection of the current candidate identifies direct OpenStreetMap tile URLs in the
  WorkArea selector and V2 coverage location map as well as the existing AOI and sanitized-orthophoto
  maps. A browser tile request can expose its viewed tile area and client IP to that provider; AI
  egress consent does not itself establish permission for third-party maps. The synthetic browser
  verification blocked non-loopback requests and did not resolve this customer/privacy decision.
  No provider, consent or route was changed by this observation.
- Legacy use-decision retries had a separate cross-account duplicate-record risk in locally tested
  OPAQUE mode. A separate same-screen continuity guard now blocks an account/organization change
  before the Core mutation and preserves the original request; scoped OIDC still refuses the legacy
  decision POST. Existing authorized result reads and reviews are not thereby closed. Other callers,
  new requests and drafts lost on navigation remain outside this UI guard; see the
  [account-continuity follow-up](work/2026-10-26-console.md#account-continuity-follow-up--2026-10-28-local-only).
- Site-detail tabs use a neutral title to avoid displaying a previous account's Site name; different
  Site tabs can no longer be identified by title alone. The observed client-transition empty-title
  interval remains unresolved. In a generated two-account browser test, an actual HTTP archive response
  deliberately delayed by a loopback forwarding proxy restored the older A session after B had been
  established; the continuity probe then reached the A record rather than returning an account mismatch.
  A separate source-inventoried, network-none synthetic OIDC Authorization Code + PKCE fixture
  also reproduced A→B→A after a delayed response; it used one Dashboard process and no refresh.
  A proxy-only cookie-stripping control confirmed the response-cookie role but is **not a product fix**:
  blindly suppressing cookies breaks the independently required refresh-token rotation path. No
  production or uninstrumented-network behavior is claimed. A bounded synthetic WorkArea rollback
  test reproduced a hidden pending record and duplicate POST. A later local guarded-Core test
  refused the duplicate while preserving the original; actual release binaries, deployment of the
  stop, Site-registration rollback and the operational recovery procedure remain unverified.
  These are distinct from scoped input-preservation tests and block release/rollback; see the
  [UX follow-through](work/2026-10-26-console.md#2026-10-29-ux-assessment-follow-through--local-candidate).

## Next

1. Complete the ledger migration for the platform/engine stream when it closes.
2. Revisit Home/global IA only with explicit approval and required evidence.
3. Revalidate this development handoff before deployment; the Human separately requested upload of
   the in-progress source. Do not restart the older shared runtime to test this candidate.
   The `.opencode/working-state.md` pointer was absent in this worktree on 2026-10-29; use this
   ledger and its linked work entries rather than assuming a missing local pointer transferred.
4. P2 local implementation and generated-byte/replay/Console verification are complete at the owning
   SIE plan's scope. Further activation/customer acceptance needs genuine signing, host containment,
   signed release and permitted data/consumer inputs; synthetic success does not supply
   those gates. Same-platform Dashboard packaging/relocation and the pinned Docker
   Node22.18-Alpine image proof are verified in the SIE follow-ups; full-platform
   production portability, signing and customer acceptance are not thereby established.
