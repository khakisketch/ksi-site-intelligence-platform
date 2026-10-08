# Physical-site move decisions (current-revision manifest)

Current-revision move decision manifest for P3 (acquisition separation).
Base: current checkout HEAD `f3920e4f98e66ff1ff2afa3618d72e3573cb5518`. Every row binds the CURRENT HEAD git object and blob SHA256 as the move binding the Task 6 executor verifies; the frozen baseline hashes are reference only.

## Frozen record (historical, unchanged)

The frozen inventory `PHYSICAL_SITE_REBASELINE_DISPOSITION_DRAFT.csv` (SHA256 `89a9baf3b1f1a593bf65af02810595cea0f677a740ceb0fdf9f2e789071639e3`, baseline `72c526ba7b6d423443d9733d1189fccd8b47ada6`) remains the historical record of the 72c526b baseline. It is never edited by this plan; candidates may legitimately differ from it (foundation/P2 changed some files, e.g. mission-contracts signing/models), and the current blob hash above is authoritative for the move.

## Decisions

- MOVE: 194
- DEFER: 0
- RETAIN: 0

## Per-group decisions

| group | rows | decision | blockers (closed by) | consumers |
| --- | --- | --- | --- | --- |
| `edge/manifold-runtime` | 71 | MOVE | 73 ids (T6) | 1 files |
| `edge/msdk-field-bridge` | 2 | MOVE | 3 ids (T6) | 0 files |
| `edge/psdk-app` | 17 | MOVE | 19 ids (T6) | 1 files |
| `edge/psdk-tap` | 29 | MOVE | 31 ids (T6) | 1 files |
| `edge/root` | 5 | MOVE | 7 ids (T6) | 2 files |
| `packages/equipment-intelligence` | 7 | MOVE | 11 ids (T5, T6) | 3 files |
| `packages/mission-contracts` | 13 | MOVE | 24 ids (T5, T6) | 10 files |
| `packages/mission-planning` | 9 | MOVE | 13 ids (T5, T6) | 3 files |
| `packages/perception` | 13 | MOVE | 16 ids (T3, T6) | 5 files |
| `services/dji-gateway` | 28 | MOVE | 30 ids (T6) | 2 files |

## Blocker-id legend and lifecycle

- `T3:worker-managed-split` — closed by Task 3 (managed-only worker modules leave the package; the surviving lanes keep no acquisition imports).
- `T5:core-import-closure:<core-file>` — closed by Task 5 (the named Core file no longer imports the candidate package; neutral extraction or import swap recorded per file).
- `T5:core-dep-drop` — closed by Task 5 (the three package dependencies leave `services/core/pyproject.toml`).
- `T6:consumer-review:<path>` — closed by Task 6 pre-move checks (no live reference to the path outside the archive remains; referencing tools/tests/docs updated in the same batch).
- `T6:ci-docker-refs` — closed by Task 6 pre-move checks (Dockerfile COPY/ENTRYPOINT, CI cmake/ctest jobs, pin scripts repointed).
- `T6:docs-routing` — closed by Task 6 (routing notes in `REPOSITORY_STRUCTURE.md`/`DOCUMENT_STATUS.md` updated for the move).
T3–T5 blockers are emptied by those tasks and recorded in their commits; T6 blockers are emptied by the Task 6 pre-move verification before the executor runs.

## Executor contract (Task 6 — refined rule, Task 6 report)

The executor (`tools/execute_physical_site_moves.py`) applies the refined Task 6 rule: `is_executable(row)` holds when every blocker is a known vocabulary id, every T3/T5 id verifies as closed at the then-current HEAD against its recorded evidence (dep-drop absence, import-closure absence-or-clean, managed-split absence), every T6 id is closed by the Task 6 same-batch consumer/CI/deploy/docs edits (machine-checked by consumer resolution active-or-archive plus a live-reference scan over non-exempt HEAD files), and every consumer resolves active-or-archive. It re-verifies each row's `git_object`/`blob_sha256` against the then-current HEAD, performs git-tracked moves to the exact `destination` only after ALL rows validate (never partial moves), and records the inverse per move. Explicit scan exemptions (never silent): the manifest machinery files (decision/fixture data, never a build input), the P4-owned `apps/dashboard/` transitional paths, and docs/`*.md` historical mentions. A candidate missing at HEAD is a controlled finding (fail-closed with a clear reason) — rows are never silently skipped, and `DEFER` (file stays, no closure path) or `RETAIN` (evidence shows platform use) apply only with recorded evidence.

## Consumer evidence (verified at this base)

- Core import sites: 11 files with real `from`/`import` statements against the candidate packages (9 mission-contracts, 2 mission-planning, 2 equipment-intelligence; docstring-only mentions in `sites.py`/`auth.py`/`source_media.py` are not imports and carry no blocker).
- Worker: `ksi_perception` imported only by managed-only modules `runner.py:83` and `odm_masking.py:75` (leave in Task 3); `ksi_change_detection` users are retained lanes, not candidates.
- CI `edge-control-plane`/`edge-psdk-app-host`/`edge-psdk-tap`/`edge-manifold-target` jobs build the edge groups; `check_third_party_pins.sh` + `tools/edge/fetch_psdk.py` pin `PSDK_LOCK.yaml`.
- Build images: `Dockerfile.external-inspector` and `Dockerfile.external-measurement` COPY `packages/perception`; `Dockerfile.gateway` runs the gateway entrypoint; `edge/docker/manifold3-build.Dockerfile` is the CI build image referenced by the manifold-target job and `manifoldctl`.
- No active-tree Python module outside `services/dji-gateway` imports `ksi_dji_gateway`; `deploy/compose.yaml` names no gateway service.
