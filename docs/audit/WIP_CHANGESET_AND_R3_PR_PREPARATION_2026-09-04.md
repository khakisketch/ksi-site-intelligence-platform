# WIP change-set audit and R3 PR preparation

Status: `HISTORICAL_PREPARATION_EVIDENCE / LOCAL_SNAPSHOT / EXECUTION_ROUTED_BY_COPIED_PLAN`
Evidence date: 2026-09-04
Repository HEAD: `41d9f55270581d9660664f6c23c65ab0d7af0a4a`
Preparation branch: `prep/r3-service-package-boundary`
Preparation worktree: `/tmp/ksi-r3-pr-candidate.7Y1ovt/worktree`

> Integration note (2026-09-05): This is dated preparation evidence. Its candidate paths, counts,
> snapshots, and recorded results remain historical facts, not current execution state. Current
> execution is governed by the copied implementation plan's preflight ruling: current-state evidence
> is committed before R3, then R3 is the final move, lineage, and enforcement triplet. Do not infer
> push, deployment, remote CI, device/HIL, field acceptance, or current authority from this candidate.

This document is delivery evidence, not product authority. Product and repository decisions remain
controlled by `docs/00_READ_FIRST.md`, the product authority chain, `REPOSITORY_STRUCTURE.md`,
`docs/DOCUMENT_STATUS.md`, ADR-KSI-034, and the R3 migration manifest.

## Result

The complete Git-visible WIP was audited by responsibility. No pre-existing WIP was deleted,
discarded, committed, pushed, deployed, or sent to a remote. The R3 delta was reconstructed exactly
in an isolated worktree and is reviewable independently as the unstaged/untracked layer above a
staged pre-R3 prerequisite snapshot.

R3 is not honestly committable directly on clean `main`: it depends on 201 pre-R3 changed paths that
contain product work and R0-R2 repository governance. Those prerequisite changes must first become an
approved commit stack or an approved base branch. R3 can then be committed without bundling the other
responsibilities.

## Source preservation evidence

| Check | Result |
|---|---|
| Source branch / HEAD | `main` / `41d9f55270581d9660664f6c23c65ab0d7af0a4a` |
| Source index | empty; SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| Tracked files with working-tree changes | 167 |
| Untracked files at the reconstruction freeze, after adding the audit plan | 165 |
| Tracked binary diff SHA-256 | `1c5d4f29d6e9a99c4b1a9ebc0347bb122c0b5395fdaac743b34716a8c603e6ae` |
| Source mutation by this task | this audit, its implementation plan, and the Document Status link only |

The source fingerprint changed from the pre-audit status only because the two audit documents and
their routing link were intentionally added. Existing product code, data, ignored paths, and the
source index were not changed by reconstruction.

## Responsibility-owned change sets

Every Git-visible path belongs primarily to one of these sets. A file named in the shared-file
section must be split by hunk; its filename alone is not a safe staging boundary.

| ID | Owner and purpose | Primary roots | Dependency | Required narrow verification before commit |
|---|---|---|---|---|
| `WIP-CAP-AUTH` | Core durable capability authority, activation, replay, runtime projection and API | `services/core/src/ksi_core/capability/`, `packages/domain/`, capability contract tests | product authority and contracts | capability authority, activation, runtime projection/API/transport contract tests |
| `WIP-MISSION-ATOMICITY` | Core Mission issuance OCC, commit guards and durable records | Core acquisition, sites, mission issuance/records/work orders, `mission_atomicity.py` | `WIP-CAP-AUTH` where activation is consumed | mission issuance atomicity, acquisition coordination and Mission record tests |
| `WIP-PROCESSING-FENCE` | Processing lease, attempt workspace, artifact manifest and publication fencing | Core processing/artifact modules and `services/processing-controller/` | Mission/source-media contracts | processing job, worker, source-media, region/design/comparison contract tests |
| `WIP-CIVIL-READINESS` | Core civil-readiness read model, OpenAPI projection and Operator Dashboard | `civil_readiness.py`, Dashboard site components/client/tests, acceptance docs | preceding Core/processing semantics | Core civil-readiness/API sync plus Dashboard unit and operations-console E2E tests |
| `WIP-HIL1R-SOFTWARE` | Gateway/Edge PSDK companion, peer receiver, runner, schemas, CI and deploy wiring | `services/dji-gateway/`, `edge/psdk-app/`, `contracts/hil/`, `docs/hil/`, HIL tools | capability runtime contract | Gateway/Edge route tests and HIL schema checks; physical HIL remains separate |
| `WIP-REPO-R0-R2` | Repository responsibility routing, document status, cleanup decisions and archived evidence | repository/document READMEs, ADR-KSI-033, cleanup manifest/schema, `docs/archive/` | none; governance base for R3 | repository-normalization gate without R3 migration requirement |
| `WIP-REPO-R3` | Move three import-only libraries from `services/` to `packages/` and enforce placement | exact allowlist below | approved `WIP-REPO-R0-R2` base and all touched consumer hunks | R3 normalization, moved-package consumers, lock, lint/type/static gates, full pytest |
| `WIP-STATE-META` | Current agent/goal/phase evidence | `.ai/`, `.ksi/`, Phase Registry state hunks | commit last or separately | state helper/ledger validation; no hand-edited durable ledger updates |
| `WIP-AUDIT-META` | This audit and preparation plan | this file and `docs/superpowers/plans/2026-09-04-audited-wip-r3-ready-pr.md` | evidence only | link/path review |

### Shared files requiring hunk-level staging

The following files mix responsibilities or state and must not be staged as whole-file shortcuts:

- Core/API composition: `services/core/src/ksi_core/app.py`, `app_assembly.py`,
  `contracts/api/openapi-core.yaml`.
- Integration automation/state: `.github/workflows/ci.yml`, `docs/goals/PHASE_REGISTRY.yaml`.
- Repository routing: `AGENTS.md`, `CLAUDE.md`, `README.md`, `REPOSITORY_STRUCTURE.md`,
  `docs/DOCUMENT_STATUS.md`, `docs/WORKSPACE_LAYOUT_AND_QUERY_GUIDE.md`,
  `docs/architecture/04_SOURCE_CODE_BOUNDARIES.md`.
- R3 enforcement: `tools/validate_repository_normalization.py`,
  `tests/contract/test_repository_normalization.py`.

## Exact R3 separation

The pre-R3 baseline was reconstructed by reversing only the R3 FileChange operations and the three
approved moves. It matched all recorded pre-R3 facts exactly:

| Evidence | Expected | Reconstructed |
|---|---:|---:|
| Tracked changed paths | 101 | 101 |
| Untracked porcelain entries | 59 | 59 |
| Tracked diff SHA-256 | `b72b78f3865877987d3031061fcea688d119ad6ae38f5a7cb1b5148747815dce` | exact match |
| Index diff SHA-256 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | exact match |
| Porcelain SHA-256 | `c759c2d083ea49039e56eacde920944fc9d5940b10dbc032c5085f7654598d94` | exact match |

The verified baseline is staged only in the isolated index: 201 prerequisite paths. The current R3
overlay contains exactly 144 changed or untracked paths; comparison against the reconstructed R3
event allowlist produced zero unexpected and zero missing paths.

The durable R3 allowlist is:

1. Complete source removal and byte-preserving destination placement for
   `services/{bim-integration,change-detection,defect-detection}/**` to the corresponding
   `packages/**` roots.
2. R3 documents and machine-readable lineage:
   `docs/architecture/ADR-KSI-034-service-package-runtime-boundary.md`,
   `docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json`,
   `contracts/schemas/repository-migration-manifest.v1.json`, and the R3 spec/plan.
3. Package/service READMEs and exact repository-routing hunks in the shared files above.
4. Workspace/consumer path-only changes in `pyproject.toml`, `uv.lock`,
   `packages/geo-spatial/pyproject.toml`, three event-contract comments, two Core comments, and
   `tests/contract/test_region_extraction_worker.py`.
5. R3-only validator and normalization-test hunks.

No product behavior, device authority, contract semantics, deployment, or physical acceptance is
part of R3. `INV-003` and `INV-054` are preserved by keeping Core adjudication and safety boundaries
unchanged.

## Local verification evidence

The candidate was installed from its locked workspace. The lock now resolves the three moved
distributions from `packages/` and all 15 workspace distributions installed successfully.

| Verification | Result |
|---|---|
| R3 and primary consumer tests | `172 passed, 12 skipped`; PASS |
| Ruff | PASS |
| mypy | PASS across 472 source files |
| `uv lock --check` | PASS |
| reference-import gate | PASS |
| runtime-image-pin gate | PASS |
| three Dockerfile static checks and Compose example resolution | PASS; no image build/deploy |
| Full pytest | `4587 passed, 119 skipped, 8 warnings`; PASS |
| Cache-safe candidate R3 normalization gate | PASS |

The first full run reported 9 failures only because the ignored PSDK checkout was deliberately not
copied into the clean worktree. The repository-owned `tools/edge/fetch_psdk.py` restored PSDK 3.16.0
at commit `9af08536df36`; the official KMZ sample hash matched
`195b1a751e13822c6ac66a7eb272fb9942d348bce4f25cbd7853ab1a3b239c5e`, its focused tests passed
`10/10`, and the full suite then passed. This is clean-environment setup evidence, not an R3 fix.

The candidate's final normalization command intentionally omitted `--check-local-cleanup`. That
option asserts that protected operator-local paths such as `.dev-data`, `download`, `models`, and
`hil_raw_logs` exist, while the isolation plan forbids copying them. The option remains meaningful
for the source operational worktree; the candidate used the R3 structure/migration gate only.

## Recommended commit and PR order

1. Commit `WIP-CAP-AUTH` after its dedicated review.
2. Commit `WIP-MISSION-ATOMICITY`.
3. Commit `WIP-PROCESSING-FENCE`.
4. Commit `WIP-CIVIL-READINESS` across Core/API/Dashboard with its acceptance evidence.
5. Commit `WIP-HIL1R-SOFTWARE`; retain `BLOCKED_HARDWARE_TOPOLOGY` and do not claim physical HIL.
6. Commit `WIP-REPO-R0-R2` repository governance and cleanup lineage.
7. Rebase the isolated R3 delta onto that approved base and commit it as one reviewable PR, preferably
   as three commits: boundary/lineage, byte-preserving moves and lock/path updates, then enforcement
   and tests.
8. Commit current state/evidence metadata separately and only through the owning helper where
   required.

Actual commit creation, push, PR creation, remote CI, deployment, HIL, field acceptance, and Human
acceptance are all still `NOT_PERFORMED`. They require separate Human authorization.

## Independent review

A separate read-only reviewer inspected both worktrees, the cached/unstaged split, plan, audit, R3
specification, and migration manifest. The verdict was `GO_FOR_COMMIT_AUTHORIZATION`, with no
Critical or Important findings. The sole Minor limitation was that the reviewer did not independently
rerun the recorded test commands; those commands were run and their output inspected by the Lead.

## Rollback and retention

- Keep the source worktree untouched; its empty index is the recovery boundary.
- Keep the external candidate until the Human accepts or rejects the proposed commit stack.
- If rejected, remove only the exact linked worktree through `git worktree remove` and its temporary
  parent after confirming it contains no unique edits.
- The ignored PSDK checkout is reproducible from the lock/provenance tool and must never be committed.
