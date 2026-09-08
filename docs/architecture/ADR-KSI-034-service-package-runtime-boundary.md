# ADR-KSI-034 — Service and import-only package runtime boundary

- Status: ACCEPTED
- Decision date: 2026-09-04
- Human decision: staged R3 option `A`
- Scope: repository placement and reachability; no product capability change

## Context

`services/` contained three Python projects with no independent listener, daemon, polling loop,
health/readiness boundary, deployment unit, or operator lifecycle. They were imported by the actual
Processing Worker, tools, CI, and tests. The directory name therefore suggested deployable services to
people and coding agents even though the manifests and consumers proved import-only library behavior.

This ambiguity caused two risks: new agents could place more libraries under `services/`, and future
cleanup could mistake reachable algorithm/model code for unused service stubs. R0-R2 documented the
problem but intentionally deferred runtime movement until exact reachability and rollback were approved.

## Decision

1. `services/` contains independently operated processes only. A service must have observable
   lifecycle evidence: its own listener, daemon/polling loop, health/readiness boundary, deployment
   configuration, or separately started worker entrypoint.
2. Import-only KSI-owned code lives in `packages/`, regardless of algorithm complexity or compute cost.
3. Move the following trees while preserving distribution names, imports, behavior, tests, licenses,
   extras, and dependency direction:
   - `services/change-detection` -> `packages/change-detection`;
   - `services/bim-integration` -> `packages/bim-integration`;
   - `services/defect-detection` -> `packages/defect-detection`.
4. Do not leave compatibility directories or symlinks under `services/`. Workspace distribution names
   provide compatibility and the R3 migration manifest provides historical path lineage.
5. Root agent rules, the canonical structure document, parent/module READMEs, and an executable
   repository contract all record this placement rule.

## Responsibility after the move

- Core retains durable request/result, policy, Mission, evidence, and journal authority.
- `services/processing-controller` retains the independent polling/lease worker lifecycle.
- `packages/change-detection` measures change, conformance, regions, and volume.
- `packages/bim-integration` interprets supported IFC reference geometry for bounded conversion.
- `packages/defect-detection` verifies/adapts an optional model and post-processes candidates; it is not
  automatically active or production-supported.
- Contracts stay in `contracts/` and executable wire models stay in `packages/event-contracts`.

## Alternatives

- **Keep the mixed placement and document it:** rejected because the physical tree would continue to
  contradict the documented runtime model.
- **Rename every application and service path at once:** rejected for this slice because it adds broad
  Docker, deployment, CI, documentation, and pre-existing WIP churn without improving the key boundary.
- **Leave forwarding symlinks under services:** rejected because agents and glob-based tooling would
  continue to discover duplicate canonical locations.
- **Merge algorithms into the Processing Worker:** rejected because reusable calculations and the
  independently operated orchestration lifecycle have different dependencies and responsibilities.

## Consequences and enforcement

- The root uv workspace already discovers both `packages/*` and `services/*`; only editable lock paths
  change.
- Python imports and package names do not change, so callers need no source-level import migration.
- Historical R0-R2 evidence is not rewritten. The validated
  `docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json` resolves old paths to current paths.
- `tests/contract/test_repository_normalization.py` fails if an old service path returns, a destination
  package disappears, or migration lineage becomes invalid.
- `AGENTS.md` and `CLAUDE.md` require entrypoint/manifest/consumer/test evidence instead of inferring
  ownership from a name.
- `INV-003` and `INV-054` remain enforced; Mission, device, media, customer-data, HIL, deployment, and
  field status are unchanged.

## Rollback

Reverse the three exact directory moves, restore only R3-owned path references, and regenerate the
lockfile. Do not reset or overwrite unrelated Human WIP. Deleted generated outputs are reconstructed
from tracked lockfiles/build commands; removed worktrees are recreated from the SHAs recorded in the
implementation plan.
