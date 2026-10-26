# Project ledger

Status: active operational ledger index (2026-10-26). This is the single entry point for
"what is current, what is being worked on, what was verified, and what is next." It is not a
second product authority.

## What lives where

| Concern | Canonical owner | Ledger role |
|---|---|---|
| Product definition, decisions, requirements | `docs/product/`, accepted ADRs | Link only; never copy or re-decide |
| Contracts and invariants | `contracts/`, `docs/product/DOMAIN_INVARIANTS.md` | Link only |
| Current product slice | `docs/superpowers/product-state.md` + named slice ledger | Summarize status in one line and link |
| Active work unit | `docs/ledger/work/<date>-<slug>.md` | Owns goal, decisions, evidence, limits, next |
| Current Console design | `docs/design/CONSOLE_CURRENT_SPEC.md` | Index and design decisions |
| Evidence | `docs/ledger/EVIDENCE.md` + external evidence paths | One row per batch; no raw dumps |
| Historical/superseded material | `docs/archive/` (temporary) | Delete after migration and reference check |

## Entry files

- [`CURRENT.md`](CURRENT.md) — the only file a new session needs to read for current state.
- [`AUTHORITY.md`](AUTHORITY.md) — authority index.
- [`DECISIONS.md`](DECISIONS.md) — accepted ADR index.
- [`DESIGN.md`](DESIGN.md) — current Console design and design decisions.
- [`EVIDENCE.md`](EVIDENCE.md) — verification evidence index.
- [`WORK.md`](WORK.md) — active/closed work index.
- [`work/`](work/) — one file per work unit.

## Rules

1. **One current entry point.** Update `CURRENT.md` when a work unit changes state. Keep it short
   (target ≤120 lines); details belong in the work file.
2. **Authority is not duplicated.** Product decisions, ADRs, contracts, invariants and the current
   product slice stay in their canonical files. The ledger links to them. A ledger entry cannot
   approve a product/contract change.
3. **One owner per work unit.** Each active work file names its owner, goal, scope, status,
   evidence and next outcome. Do not create a parallel narrative in `.opencode/working-state.md`;
   that checkpoint is a pointer to this ledger and the active work file.
4. **Evidence is indexed, not pasted.** Record the exact path, date, commit/image digest, checks
   and limits. Raw captures/logs stay in their state/evidence directories.
5. **Design has one current spec.** `DESIGN.md` points to `CONSOLE_CURRENT_SPEC.md`; superseded
   boards are archive only and may not drive implementation.
6. **Closeout.** When a work unit is verified: update `CURRENT.md`, write a one-line entry in
   `work/closed/INDEX.md`, and move the detailed file to `work/closed/YYYY-MM/`. Keep the line
   only if it still explains a decision or live dependency.
7. **Archive is temporary.** `docs/archive/` is a migration staging area, not a second docs tree.
   Once content is reflected in the ledger/authority/design/evidence and no link points to it,
   delete it. Do not keep a permanent copy of every draft.
8. **No duplicate ledgers.** `product-state.md` remains the slice SSOT; the rebaseline plan remains
   its own work ledger until that workstream closes. This ledger summarizes and links them, then
   absorbs their current state at closeout.

## Migration sequence

1. **Now:** establish this ledger and use the Console workstream as the pilot.
2. **Now:** replace the long `.opencode/working-state.md` narrative with a pointer; the Console
   details live in `work/2026-10-26-console.md`.
3. **When the platform/engine workstream closes:** split the 7.9k-line rebaseline ledger into a
   short current entry here plus a dated history/evidence index; delete redundant prose after all
   references are updated.
4. **At product-slice close:** trim `product-state.md` to current Goal/Milestones/Next + history
   pointer; remove superseded backlog narratives.
5. **After each close:** delete archived design boards/drafts with no live references. Keep
   durable ADRs, contracts, invariants and evidence digests.
