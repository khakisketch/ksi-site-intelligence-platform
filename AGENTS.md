# KSI Site Intelligence Agent Instructions

KSI connects physical-site observations to reusable spatial data and evidence-based analysis. Customers own original data and reconstruction execution; KSI owns registration, inspection, permitted use, and evidence for submitted derived outputs. Flight, autonomous acquisition, tactical control, and customer production reconstruction are outside current product responsibility (ADR-KSI-036/038/039).

## Start here

- Product identity, authority order, and supersessions: [`docs/00_READ_FIRST.md`](docs/00_READ_FIRST.md).
- Current repository ownership/runtime map: [`REPOSITORY_STRUCTURE.md`](REPOSITORY_STRUCTURE.md).
- Active vs historical document routing: [`docs/DOCUMENT_STATUS.md`](docs/DOCUMENT_STATUS.md).
- Current bounded work: check `.opencode/working-state.md` when present; otherwise use [`docs/ledger/CURRENT.md`](docs/ledger/CURRENT.md) and its explicitly named work ledger.
- Product slice, only when no active bounded task exists: [`docs/superpowers/product-state.md`](docs/superpowers/product-state.md) and its named slice ledger.
- Console direction: [`docs/design/CONSOLE_CURRENT_SPEC.md`](docs/design/CONSOLE_CURRENT_SPEC.md).

Read only the relevant owner README, contract, entrypoint, and tests for the task. Revalidate Git and source-bound evidence; cached memory and historical plans are not authority. Do not duplicate current status across documents.

## Rules

- Follow the product authority precedence in `docs/00_READ_FIRST.md`; supporting designs, ledgers, and prototypes cannot change product decisions or acceptance.
- Enforce affected invariants in `docs/product/DOMAIN_INVARIANTS.md` and contracts. Accepted direction alone does not authorize an endpoint, runtime permission, deployment, or product acceptance.
- `REPOSITORY_STRUCTURE.md` owns current source/runtime responsibility; independently operated lifecycles belong in `services/`, import-only reusable code in `packages/`.
- Preserve `docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json`. Do not import runtime code from `references/` or modify reference repositories unless the task explicitly says `UPDATE_REFERENCE_PIN`.
- Treat `archive/acquisition-2026/`, `.ksi/`, retired harness records, and dated plans as historical unless current authority explicitly selects them. Do not restore retired roles, routes, or workflows.
- Do not claim accuracy, settlement suitability, vendor/field support, deployment, or customer acceptance from registration, RTK FIX, mocks, imports, or software tests alone. Keep unknowns explicit; use contract/replay tests and real-device/HIL gates where applicable.
- Never let an LLM emit executable flight coordinates or bypass safety policy. Retained historical control boundaries remain in their accepted contracts; they do not activate those routes.
