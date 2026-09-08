# R3 Service and Package Boundary Design

Date: 2026-09-04
Status: APPROVED by Human (`A` staged normalization)
Scope: repository placement, reachability, documentation, and regenerable local cleanup only

## Outcome

The repository will make the physical directory boundary match the actual runtime responsibility:

- `services/` contains independently started deployable processes or polling workers;
- `packages/` contains import-only KSI-owned libraries and algorithms;
- public Python distribution/import names remain stable;
- product, Mission, device, customer-data, and HIL behavior does not change;
- human and AI routing is recorded in `AGENTS.md`, `CLAUDE.md`,
  `REPOSITORY_STRUCTURE.md`, parent/module READMEs, an accepted ADR, and executable checks.

This is the approved high-value part of the R3 proposal. Path renames for `apps/dashboard`,
`services/core`, `services/dji-gateway`, and `services/processing-controller` are deliberately not
included: their current paths are conventional enough, while renaming them would create broad
deployment and WIP churn without improving the service-versus-library boundary.

## Requirements

| ID | Requirement | Evidence |
|---|---|---|
| `R3-STR-001` | `services/` contains deployable units; the three import-only processing libraries live in `packages/`. | Current tree, structure contract test |
| `R3-DOC-001` | A human or AI can determine owner, runtime kind, dependencies, tests, and forbidden responsibilities before editing a module. | Agent rules, canonical structure, nearest README |
| `R3-REACH-001` | Package imports, workspace resolution, lockfile, Docker/Compose assembly, CI, and owner tests remain reachable after the move. | Lock and verification commands |
| `R3-LINEAGE-001` | R0-R2 historical paths remain interpretable without rewriting historical evidence. | R3 migration manifest and validator |
| `R3-CLN-001` | Only verified, ignored, reproducible artifacts and clean/reachable stale worktrees are removed. | Cleanup inventory and post-cleanup checks |
| `R3-WIP-001` | Pre-existing user WIP, protected data, secrets, models, HIL evidence, SDKs, and references are preserved. | Baseline fingerprint and protected-path audit |

Existing product requirements touched only at their repository boundary:

- `REQ-PROD-001`: the repository and product identity remain unchanged.
- `REQ-OPS-101`: runtime manifests and locked workspace assembly remain valid.

## Authority and invariants

Read and apply in this order:

1. `docs/00_READ_FIRST.md`
2. `docs/product/PRODUCT_CONSTITUTION.md`
3. `docs/product/FINAL_DECISION_LEDGER_v1.0.md`
4. `docs/product/MASTER_PRD_v3.0.md` §24 and Appendix B
5. `docs/product/DOMAIN_INVARIANTS.md`
6. `REPOSITORY_STRUCTURE.md` and `docs/DOCUMENT_STATUS.md`

Touched invariants:

- `INV-003`: no direct runtime import or dependency from `references/repos/`; enforced by the
  existing reference-import gate and unchanged package provenance.
- `INV-054`: production/runtime manifests retain exact external image pins; enforced by the
  runtime-image-pin test and Docker/Compose checks.

No Mission, capability, media-ingress, device-authority, customer-data, or HIL invariant is changed.
Physical HIL and field status therefore remain exactly as recorded before R3.

## Approved target

```text
apps/
  dashboard/                    # KSI Operations Console; path retained
services/                       # independently started/deployed units only
  core/
  dji-gateway/
  processing-controller/
packages/                       # import-only reusable code
  domain/
  event-contracts/
  mission-contracts/
  mission-planning/
  geo-core/
  geo-spatial/
  equipment-intelligence/
  perception/
  change-detection/             # moved from services/
  bim-integration/              # moved from services/
  defect-detection/             # moved from services/
  test-vectors/
edge/                           # Manifold/native local runtime and diagnostics
contracts/                      # language-neutral API/schema/HIL authority
tests/                          # contract/replay/golden/HIL-software/E2E evidence
```

Exact moves:

| Before | After | Stable distribution/import |
|---|---|---|
| `services/change-detection/` | `packages/change-detection/` | `ksi-change-detection` / `ksi_change_detection` |
| `services/bim-integration/` | `packages/bim-integration/` | `ksi-bim-integration` / `ksi_bim_integration` |
| `services/defect-detection/` | `packages/defect-detection/` | `ksi-defect-detection` / `ksi_defect_detection` |

The processing controller continues to import `ksi_change_detection` by distribution name. The BIM
library remains a converter/tool and test dependency. The defect package remains optional/model-gated;
moving it does not activate a model or make it a deployed service.

## Placement rule for future work

A module belongs in `services/` only when it has its own independently managed runtime lifecycle such
as an HTTP listener, daemon/polling loop, health/readiness boundary, deployment configuration, or
separately operated worker entrypoint. A module imported by another KSI module, with no independently
operated lifecycle, belongs in `packages/` even when it performs substantial processing.

Directory names are not proof. Before adding or moving a module, an agent must inspect its nearest
README, manifest, entrypoint, consumers, Docker/Compose references, CI paths, and owner tests.

## Agent and human entry flow

```text
AGENTS.md / CLAUDE.md
  -> product authority and relevant invariant/contract
  -> REPOSITORY_STRUCTURE.md + DOCUMENT_STATUS.md
  -> owner directory README
  -> module README
  -> manifest + actual entrypoint/consumer
  -> owner tests and broader boundary gates
```

Each moved package README records: responsibility, non-responsibilities, runtime kind, consumers,
dependency direction, authority/contracts, tests, optional dependencies, license/data implications,
and rollback path. The canonical current path is owned by `REPOSITORY_STRUCTURE.md`; dated audits and
plans remain evidence rather than current routing authority.

## Historical lineage

`docs/audit/REPOSITORY_CLEANUP_MANIFEST_R0_R2.json` and dated plans/audits are not rewritten to pretend
the old path never existed. A new R3 migration manifest maps each old path to its canonical new path.
The repository validator accepts a missing historical source only when the mapping is explicit and
the destination exists. This preserves evidence while preventing silent deletion.

## Cleanup boundary

Remove only the exact, verified classes below after relevant processes are stopped:

- Dashboard `.next*`, `node_modules`, test results, and local compiler caches;
- Edge module `build*` output;
- executable design prototype `dist`, `node_modules`, and test output;
- generated design HTML/screens/studies whose generator remains canonical;
- Python `__pycache__`, `.pyc`, and `.pyo` below product source/test/tool roots;
- four registered `.claude/worktrees/wf_5416fafa-d7d-{1,2,4,5}` entries that are clean, have no
  process, and point to commits reachable from `main`.

Protected and untouched: `.venv`, `.dev-data`, `download`, `hil_raw_logs`, `models`, licensed geoid
source, `edge/third_party/psdk`, secrets/machine configuration, `.ksi`, `.ai`, and `references`.

Generated files are not archived as evidence. They are rebuilt from their tracked manifests or
generators. Removed worktrees can be recreated at their recorded commit; the `probe` branch is not
deleted.

## Baseline WIP contract

Before implementation the main worktree was:

```text
HEAD: 41d9f55270581d9660664f6c23c65ab0d7af0a4a
branch: main
tracked changes: 101
untracked porcelain entries: 59
working diff sha256: b72b78f3865877987d3031061fcea688d119ad6ae38f5a7cb1b5148747815dce
index diff sha256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
porcelain status sha256: c759c2d083ea49039e56eacde920944fc9d5940b10dbc032c5085f7654598d94
```

The three move-source directories had no pre-existing tracked or untracked changes. Existing changes
outside the approved file set remain Human-owned WIP. No reset, checkout, commit, merge, push, release,
deployment, credential change, device action, or reference update is authorized.

## Error handling and rollback

- Stop if any move-source directory becomes dirty before the move.
- Stop if an old worktree becomes dirty, gains an untracked file, is no longer reachable from `main`,
  or has an active process.
- If workspace resolution fails, restore the three paths and regenerate `uv.lock` from the restored
  manifests; do not weaken dependencies or remove packages.
- If a path-specific runtime edge is discovered, update the plan before continuing.
- Restore code by reversing the three path moves and only the R3-owned path/document changes.
- Recreate generated output from lockfiles/build commands; recreate stale worktrees with their recorded
  commit SHA when needed.

## Verification model

Targeted package tests run first, then workspace lint/type checking and the complete Python suite.
Structure/migration, reference-import, runtime-image, Docker/Compose, link, and diff checks cover the
non-Python boundaries. Software GREEN cannot change physical HIL, remote CI, deployment, or Human field
acceptance status.
