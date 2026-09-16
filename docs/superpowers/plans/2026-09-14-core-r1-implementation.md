# KSI-CORE-R1-20260914 Core relocation plan

## Approved scope

- **Requirement IDs:** KSI-CORE-R1-20260914 T0/T1; ADR-KSI-036 boundaries.
- **Owner module:** `services/core`.
- **Invariants:** preserve INV-017, INV-018, INV-020, INV-024, INV-040, INV-051,
  INV-053, INV-060, and INV-061. T1 directly protects production import closure
  (INV-040), organization-bound `Principal` identity (INV-060), and shared
  journal/coordinator globals.
- **Contracts affected:** Python module paths only. Public API, JSONL events and
  digests, journal filenames, defaults, locking, errors and authority meanings do
  not change.
- **Reference/adoption:** retain and extract existing KSI-owned Core code. Reference
  repositories remain read-only and are not imported.

This document is an approved implementation reference, not a status ledger. Current
status and subsequent assignments are owned only by the
[external product-loop task record](/home/ksi/.codex/work-state/ksi-external-product-loop.md).

## Ownership map and compatibility

T1 relocates foundation modules to `ksi_core.foundation`: `api_base`,
`durable_journal`, `identifiers`, `leasing`, `metrics`, `observability`,
`retention`, and `currentness` (from `external_authority_currentness`). It relocates
identity modules to `ksi_core.identity`: `auth`, `oidc`, `signing_keys`, and
`device_attestation`. Every legacy path remains an explicit module-object alias to
its canonical target. The aliases preserve imports in either order, shared mutable
globals and old pickle lookup without rewriting class/function metadata.

The complete tracked-module inventory in
`docs/audit/CORE_R1_MODULE_MIGRATION.json` is the deterministic routing map. It
records active canonical paths separately from later planned targets: sites,
missions, edge transport, artifacts, processing, analytics, design, observations,
workspace, external ingress/quantity/workflow/authority, acquisition, capability,
and future composition. It does not authorize names-only consolidation or a new
runtime/service.

## Ordered delivery

1. **T0/T1 (this slice):** inventory and checker; relocate foundation and identity
   with explicit legacy aliases and behavior-preserving contract/replay coverage.
2. **T2 (managed):** relocate managed domains only after T1 aliases and import
   closure are accepted.
3. **T3 (external):** relocate external ingress, quantity, workflow, and authority
   only with the existing ADR-KSI-036 registration/verification/eligibility boundary
   intact.
4. **T4 (worker):** retain independent measurement-worker ownership; Core remains
   the durable adjudicator.
5. **T5 (composition):** split app/app-assembly internals into ordered checks,
   route groups, domain assembly, and validated runtime configuration. Root
   `app.py`, `app_assembly.py`, and `production.py` remain thin public entrypoints
   with their signatures preserved.
6. **T6 (Dashboard):** consume stable Core contracts only; Dashboard receives no
   device authority.
7. **T7 (local integration):** exercise the assembled local flow. Remote CI,
   deployment, owner, HIL, and field acceptance remain separate external gates.

First-release product flow remains: registration/seal -> actual inspection/display ->
independent checkpoint/per-use decision -> relative volume -> human review/proposal/
approval -> planning-only successor. Existing functions are not absent merely because
complete worker E2E is still pending. No new DI library or service locator is in
scope. Two writer slots plus independent review and verification apply; all evidence
for this plan is local and does not represent remote CI.

## Acceptance and validation

The checker rejects incomplete/duplicate maps and prohibited new boundary imports
while tolerating recorded legacy cross-domain cycles. Tests must prove canonical and
legacy module-object identity in both import orders, legacy monkeypatch propagation,
representative old-pickle lookup, journal single-writer append/replay behavior, and
`Principal`/`Permission` identity. Run focused contract/replay tests, static checks,
and the production import-closure guard. Do not run HIL, hardware, host services,
remote CI, or the full suite for this slice.

## Assumptions, data, and rollback

No HIL or real-device assumption is made. Only repository-owned code and test fixtures
are used; no customer data, credentials, vendor selection, or license decision is
introduced. On explicit authorization only, rollback restores this slice's exact
source preimages and removes its new files; journals, runtime state, and unrelated WIP
are preserved.
