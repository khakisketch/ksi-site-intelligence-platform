# R3 Service and Package Boundary Implementation Plan

> **For future agents:** Follow the repository authority order and execute this plan task by task.
> Do not commit, push, deploy, touch credentials, or perform device actions without new Human approval.

**Goal:** Move three import-only processing libraries from `services/` to `packages/`, permanently
record the runtime placement rule for people and AI agents, preserve historical path lineage and the
existing WIP, and remove only verified regenerable local output and stale registered worktrees.

**Architecture:** Distribution/import names stay stable while physical package roots move. Canonical
routing lives in `REPOSITORY_STRUCTURE.md`; root AI instruction files point to it and state the
service-versus-package decision rule. A versioned R3 migration manifest lets the validator reconcile
historical R0-R2 evidence with current paths. No product/API/HIL behavior changes.

**Tech stack:** Python 3.12, uv workspace, pytest, Ruff, mypy, JSON Schema, Docker/Compose, Markdown.

**Approved design:**
`docs/superpowers/specs/2026-09-04-r3-service-package-boundary-design.md`

## Required implementation plan

```text
Requirement IDs:
  R3-STR-001, R3-DOC-001, R3-REACH-001, R3-LINEAGE-001,
  R3-CLN-001, R3-WIP-001; existing REQ-PROD-001 and REQ-OPS-101
Owner module:
  Repository governance and Processing library owners
Acceptance criteria:
  services has only independently operated units; all three leaves exist under packages;
  imports/distribution names remain stable; R0-R2 paths have explicit migration lineage;
  AI routing and nearest README guidance are current; approved generated/stale state is absent;
  targeted and integrated verification passes; protected/WIP state is preserved
Contracts affected:
  No product wire/API schema changes; one repository-migration evidence schema is added
Reference assets:
  None; references remain read-only and are not imported
Adoption decisions:
  CONSOLIDATE three import-only libraries; REMOVE verified generated state/stale worktrees;
  RETAIN deployable services, protected data/evidence/toolchains, package names and behavior;
  no new ARCHIVE action
Files to change:
  Three directory moves; pyproject.toml; uv.lock; AGENTS.md; CLAUDE.md;
  REPOSITORY_STRUCTURE.md; services/README.md; packages/README.md; three package READMEs;
  active source/contract/model/path references; ADR, document index, migration manifest/schema;
  normalization validator and contract tests
Tests:
  Red/green repository normalization contract; moved package owner tests; relevant Core/worker/tool
  contract tests; uv locked sync; Ruff; mypy; full pytest; reference import; runtime image pins;
  Docker/Compose config/check; links and diff checks
HIL or real-device assumptions:
  None; no device/HIL execution and no status promotion
License/data implications:
  MixerCSeg/VMamba vendored licenses move byte-for-byte with defect package; IfcOpenShell,
  SciPy/raster/geo dependency declarations remain; models/customer/HIL/licensed data are untouched
Rollback:
  Reverse exact directory mappings and R3-owned path edits; regenerate lock; regenerate deleted
  build/dependency output; recreate worktrees from recorded SHAs; never reset unrelated WIP
```

### Task 1: Freeze evidence and write the approved architecture record

**Files:**

- Add: `docs/superpowers/specs/2026-09-04-r3-service-package-boundary-design.md`
- Add: `docs/superpowers/plans/2026-09-04-r3-service-package-boundary.md`
- Later add: `docs/architecture/ADR-KSI-034-service-package-runtime-boundary.md`

**Steps:**

1. Record HEAD, branch, tracked/untracked counts and hashes in the approved design.
2. Confirm all three source directories are clean relative to the pre-existing WIP.
3. Confirm no forbidden external action is included.
4. Re-read the required implementation plan above before code changes.

### Task 2: RED — encode the current-path contract before moving code

**Files:**

- Modify: `tests/contract/test_repository_normalization.py`

**Break the test must catch:** an import-only processing package is added back under `services/`, or a
canonical R3 package is absent from `packages/`.

**Steps:**

1. Add a table-driven test with literal before/after mappings.
2. Assert each destination is a package project (`pyproject.toml` exists) and each old source is absent.
3. Run:

   ```bash
   uv run --locked pytest -q tests/contract/test_repository_normalization.py -k r3_package_boundary
   ```

4. Confirm it fails by assertion because the approved destinations do not exist yet.

### Task 3: GREEN — move the three clean library trees

**Files:**

- Move: `services/change-detection/` -> `packages/change-detection/`
- Move: `services/bim-integration/` -> `packages/bim-integration/`
- Move: `services/defect-detection/` -> `packages/defect-detection/`

**Steps:**

1. Recheck all three source paths have no Git status entries.
2. Move each complete tree, including package-local tests, type markers, notices, and licenses.
3. Run the RED test again and confirm it passes.
4. Check `git status --short` shows renames/add-delete pairs only for the three clean source trees.

### Task 4: RED/GREEN — add machine-readable migration lineage

**Files:**

- Modify: `tests/contract/test_repository_normalization.py`
- Add: `contracts/schemas/repository-migration-manifest.v1.json`
- Add: `docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json`
- Modify: `tools/validate_repository_normalization.py`

**Break the test must catch:** an R0-R2 historical path disappears without an explicit mapping to an
existing canonical destination, or the current structure regresses.

**Steps:**

1. Add a test that runs the real validator and requires an R3 migration check.
2. Run it before implementation and observe the expected missing-manifest/mapping failure.
3. Add a strict JSON Schema and R3 manifest with exact move, cleanup, protected path, rollback, and
   verification records.
4. Teach the validator to accept a missing historical source only through a validated mapping whose
   destination exists. Keep `_check_manifest_paths` backward compatible for existing unit tests.
5. Update current required/forbidden structure paths and success wording to R0-R3.
6. Run the focused normalization tests to GREEN.

### Task 5: Synchronize workspace and active path references

**Files:**

- Modify: `pyproject.toml`
- Regenerate: `uv.lock`
- Modify: `docs/models/MODEL_REGISTRY.yaml`
- Modify: `contracts/api/openapi-core.yaml`
- Modify: active source comments/docstrings returned by a path search

**Steps:**

1. Change only path-specific Ruff/mypy exclusions and human-readable current-path references.
2. Keep project names, imports, versions, dependency declarations, extras, and licenses unchanged.
3. Run `uv lock --offline` when the local cache permits; otherwise run normal `uv lock` without
   upgrading unrelated dependencies and inspect the lock diff.
4. Run `uv sync --locked --all-packages`.
5. Search all active/non-historical files for old paths; classify every remaining match as historical
   evidence or a defect.

### Task 6: Permanently route humans and AI agents

**Files:**

- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`
- Modify: `REPOSITORY_STRUCTURE.md`
- Modify: `services/README.md`
- Modify: `packages/README.md`
- Add: `packages/change-detection/README.md`
- Add: `packages/bim-integration/README.md`
- Add: `packages/defect-detection/README.md`
- Add: `docs/architecture/ADR-KSI-034-service-package-runtime-boundary.md`
- Modify: `docs/architecture/04_SOURCE_CODE_BOUNDARIES.md`
- Modify: `docs/DOCUMENT_STATUS.md`

**Steps:**

1. State the observable service-versus-package lifecycle test in both root agent instruction files.
2. Update the canonical current tree and mark this R3 placement slice complete while retaining other
   explicitly deferred R3 candidates.
3. Make `services/README.md` list deployable units only and `packages/README.md` list all import-only
   libraries.
4. Give each moved package a responsibility/non-responsibility, consumer, dependency, test, license,
   and authority guide.
5. Record the accepted decision and consequences in ADR-KSI-034; route current documents to it.
6. Do not rewrite dated audit/plan/ledger prose that describes the historical source path; rely on the
   migration manifest for lineage.

### Task 7: Run targeted reachability checks before cleanup

**Commands:**

```bash
uv run --locked pytest -q \
  packages/change-detection/tests \
  tests/contract/test_change_detection.py \
  tests/contract/test_ifc_reference_model.py \
  tests/contract/test_convert_ifc_design_surface.py \
  tests/contract/test_defect_model_registry.py \
  tests/contract/test_defect_postprocess.py \
  tests/contract/test_mixercseg_detector.py \
  tests/contract/test_comparison_worker.py \
  tests/contract/test_repository_normalization.py
uv run --locked ruff check packages/change-detection packages/bim-integration \
  packages/defect-detection tests/contract/test_repository_normalization.py \
  tools/validate_repository_normalization.py
uv run --locked mypy packages services tests tools
```

Inspect full output and resolve any regression before cleanup.

### Task 8: Safely remove verified local generated state

**Exact classes:** Dashboard `.next*`, dependency tree and caches; Edge `build*`; design prototype
dependencies/build/test output; generated design render output; Python bytecode caches.

**Steps:**

1. Re-resolve the active Dashboard stack PIDs and verify executable/cwd are inside this repository.
2. Send `SIGTERM` to the stack owner, wait briefly, and verify no matching child remains. Do not kill
   unrelated Node/Python/container processes.
3. Recheck every removal target is ignored and not tracked.
4. Remove only explicit validated directories/files; prune Python caches only below selected product
   roots and exclude `.venv`, references, data, downloads, HIL evidence, models, and SDKs.
5. Recheck target absence and protected-path presence.

### Task 9: Safely remove stale registered worktrees

**Exact worktrees and rollback commits:**

- `.claude/worktrees/wf_5416fafa-d7d-1` -> `dbe4f46f85d6e6dace1dc49c7e00eaa1e28ee2b4`
- `.claude/worktrees/wf_5416fafa-d7d-2` -> `2aeefeb8723d958ef3a4ef4c74c7fd2d3c186f0d`
- `.claude/worktrees/wf_5416fafa-d7d-4` -> `370458df7ebdca5d3f458061fba9031d318f7219`
- `.claude/worktrees/wf_5416fafa-d7d-5` -> `370458df7ebdca5d3f458061fba9031d318f7219`

**Steps:**

1. For every exact path, recheck clean status, no untracked entries, expected SHA, ancestry from main,
   and no process using the path.
2. Remove using `git worktree remove <exact-path>`; do not use recursive filesystem deletion.
3. Run `git worktree prune --dry-run` if supported, then `git worktree list --porcelain`.
4. Keep the `probe` branch and all commits.

### Task 10: Integrated verification and independent review

**Commands:**

```bash
uv sync --locked --all-packages
uv run --locked python tools/validate_repository_normalization.py --check-local-cleanup
uv run --locked bash scripts/check_no_reference_imports.sh
uv run --locked python tools/check_runtime_image_pins.py
uv run --locked ruff check .
uv run --locked mypy packages services tests tools
uv run --locked pytest -q
docker compose -f deploy/compose.yaml config --quiet
docker build --check -f Dockerfile .
docker build --check -f Dockerfile.gateway .
docker build --check -f Dockerfile.worker .
git diff --check
```

1. Update the R3 manifest verification records only with commands actually run and their results.
2. Request a read-only independent review against this plan and design.
3. Fix every Critical/Important finding, rerun the narrowest affected checks, then rerun the final
   integrated gate.
4. Audit all requirements against current filesystem, Git, and command evidence.
5. Report implementation, local verification, commit state, remote CI/deployment, and HIL/field/Human
   acceptance separately. Do not claim remote or physical completion.
