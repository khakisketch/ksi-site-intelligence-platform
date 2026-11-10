# Operational ledger

`.opencode/working-state.md`, when present, resumes a Human-assigned checkout task through its named
task ledger. Otherwise [`CURRENT.md`](CURRENT.md) routes active operational work. Product-slice scope
lives in [`../superpowers/product-state.md`](../superpowers/product-state.md). These records cannot
change product decisions, contracts, or acceptance authority.

## Ownership

- Product decisions and requirements: `docs/product/` and accepted ADRs.
- Contracts and invariants: `contracts/` and `docs/product/DOMAIN_INVARIANTS.md`.
- Active checkout task: `.opencode/working-state.md` when present plus its named ledger; otherwise use `CURRENT.md` and its named owner record.
- Product slice: `../superpowers/product-state.md` and its named slice ledger.
- Console design: `../design/CONSOLE_CURRENT_SPEC.md` (authoritative subordinate design).
- Verification evidence: the owning work ledger and source-bound evidence; historical local paths are provenance, not live evidence.

Do not repeat current status across indexes. Update the owning record, then update `CURRENT.md` only when routing or active status changes. Close completed work only when its evidence and remaining limits are reconciled. Archive material only when provenance is valuable and its references are updated; otherwise remove it.
