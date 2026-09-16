# RETIRED — `.ksi/` legacy goal/risk ledger

Retirement date: 2026-09-17.

Reason: `docs/superpowers/product-state.md` + the plans ledger under
`docs/superpowers/plans/` are the single memory (SSOT) for Goal, Milestones,
current slice/acceptance, and Backlog. This directory preserves the legacy
`.ksi/` ledger as historical evidence only; it is not current-state authority.

Inventory (durable artifacts): `goals.json`, `ledger.jsonl`.
Also preserved from the move: `.gitignore`, `goals.lock` (empty lock file), `state.json`.

Do NOT use the external helper `~/.claude/scripts/ksi-goals.py` — it recreates
`.ksi/` and would revive the retired ledger. Record new state only in
`docs/superpowers/product-state.md` (at slice close) and the plans ledger.
