# Current

Operational routing only. Product authority follows [`../00_READ_FIRST.md`](../00_READ_FIRST.md);
this file cannot change decisions, slice scope, or acceptance.

## Current product slice

[`../superpowers/product-state.md`](../superpowers/product-state.md) owns the slice and its acceptance
criteria. Current slice remains `EXT-VAL`: external reconstruction artifact inspection and per-use
suitability assessment. This routing summary does not revise its pinned acceptance text. Customer,
field, and external validation acceptance remain unverified.

## Active work

| Work | Status / next | Owner record |
|---|---|---|
| Spatial platform / engine rebaseline | Active; continue only within the approved bounded task and revalidate its current evidence | [Rebaseline ledger](../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md) |
| Console follow-through | Local/source evidence exists; release is blocked by unresolved cross-account session behavior and separate host/customer gates. Do not treat prior deployed or synthetic snapshots as current acceptance. | [Console work ledger](work/2026-10-26-console.md) |
| Console design | Current design direction only; implementation and deployment status are owned by the source-bound work ledger | [Current spec](../design/CONSOLE_CURRENT_SPEC.md) |

## Persistent release boundaries

- Local software checks and synthetic data do not establish customer, field, quantitative, or deployment acceptance.
- The delayed cross-account response/session race remains unresolved in the recorded synthetic tests; release and rollback claims remain unverified. See the Console work ledger for the reproduction and limits.
- External AI-host configuration, signing, deployment-host containment, permitted customer data/rights, and independent customer acceptance remain separate gates.
- Third-party map tile requests can disclose viewed area and client IP; the existing product decision in [`../product/BETA_PROGRAM.md`](../product/BETA_PROGRAM.md) governs. This ledger does not authorize a provider or consent change.

Update this page only when active routing, work status, or a persistent release boundary changes. Put detailed evidence and history in the owning work record; do not copy test counts or stale handoff instructions here.
