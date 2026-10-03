# External runtime Python repair implementation plan

> For agentic workers: use `executing-plans` for local implementation. Steps use checkbox tracking.

**Goal:** Repair affected Python in both contained images with source and real-image evidence.
**Architecture:** Keep existing two-stage image builds and dedicated rootless verification route;
replace only the selected Python base pin and repair strict stale regression expectations.
**Tech stack:** existing Docker, Python3.12, uv0.11.15, pinned private Syft/Grype/DB.
**Spec:** [approved design](../specs/2026-10-03-external-runtime-python-repair-design.md).
**State:** written spec approved by Human; this written implementation plan awaits review.

## Global constraints and implementation packet
- Requirements: REQ-OPS-101, REQ-SEC-101; EXT-VAL-05/08 preparation only.
- Owner: the two root Dockerfiles and existing packaging/security tests; no other image upgrades.
- Acceptance: both real ARM64 images contain Python3.12.15 and fixed tarfile; current OS fixes,
  Python dependency lock, distinct users/commands/contexts preserved; actual scans reported in full.
- Invariants: INV-054 exact source/image/SBOM/scanner binding; preserve INV-051/053/055/060 by
  no managed identity, Core policy, quantitative or tenant-authority mutation.
- Contracts affected: no runtime wire changes; newly signed image/profile identities remain external.
- Reference assets/adoption: KSI Dockerfiles/tests and official Python/Debian artifacts only.
- Files to change: both Dockerfiles, the two tests named below, this ledger and outcome docs.
- Tests: strict source pins plus actual archive/package/SBOM/scan evidence and owner regressions.
- HIL/real device: none; no public raster/container entrypoint execution or functional containment claim.
- License/data: preserve acquired originals and tool notices; public package downloads only.
- Rollback: retain prior source/images/tags/archives; only task-owned local commits, no prune/reset.
- Python exact reference: `python:3.12.15-slim@sha256:29113dcae7aad06daa8e95260fa09f27d62be33b9687ea3774f771d601a02256`.
- Preserve spec's20261003 snapshot and package versions, uv digest, lockfile, users and commands.
- No host OS/tool installation, key/credential/policy provisioning, registry push, deploy or activation.

## Review focus
- Tag/index/config confusion: M1 verifies original immutable bytes and ARM64 config, not tag only.
- Builder-only repair: M1 test checks both FROM lines and M2 checks final actual archived Python.
- New base regresses OS fixes: M2 compares actual exact Debian pins and same-DB findings.
- Stale tests pass by weakening assertions: M1 requires exact snapshot/OpenSSL/current packaging.
- New image mistakenly accepted for execution: M3 explicitly preserves signed-profile/host gates.

### M1 — Strict source repair
**Files:** modify `Dockerfile.external-inspector`, `Dockerfile.external-measurement`,
`tests/contract/test_external_runtime_image_packaging.py`,
`tests/contract/test_external_runtime_image_security_pins.py`.
**Interfaces:** consumes approved exact pin/current OS package set; produces clean committed image source.
- [ ] Retain raw official selected index/platform/config JSON outside Git, hash bytes and check
  index29113dca…, ARM64/v8 manifest18d23907…, config architecture/os/PYTHON_VERSION3.12.15.
  Refuse mismatching bytes or unavailable selected identity; never guess/pick another digest.
- [ ] In existing packaging test, set `_PINNED_PYTHON` to the exact spec reference and require
  exactly two matching FROM lines per file, one builder and one final; expect distinct existing
  users/commands/copies. Set both existing tests' snapshot to20261003 and OpenSSLdeb13u3;
  retain cryptography50.0.1 and all old negative/context assertions.
- [ ] Run RED: `UV_NO_SYNC=1 UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never .venv/bin/python -m pytest -q tests/contract/test_external_runtime_image_packaging.py tests/contract/test_external_runtime_image_security_pins.py`.
  Desired Python pin must fail before Dockerfile repair; earlier stale snapshot failures are recorded separately.
- [ ] Replace both FROM pins in both Dockerfiles; correct the comment about unchanged Python,
  preserving every other approved OS/runtime setting. No lockfile or dependency changes.
- [ ] Run the same command GREEN plus `tests/contract/test_runtime_image_pins.py` and
  `tests/contract/test_release_evidence.py`; require zero failures, inspect scope/index and commit.

### M2 — Actual source-frozen images and security evidence
**Files:** create additive ignored private evidence under the existing contained-runtime artifact
root and new dedicated build workspace; no tracked image/report binaries.
**Interfaces:** consumes M1 clean source, selected base identity and original tool/DB/archive receipts;
produces actual archive hashes, final configs, SBOMs, raw scans and comparison receipts.
- [ ] Revalidate existing rootless target `unix:///run/user/994/docker.sock`, actual inspector UID,
  dormant application state and task-private tooling/DB bytes. Do not query/reconfigure rootful
  Docker, restart the daemon or run bootstrap. If prerequisites changed, stop that operation.
- [ ] Freeze allowlisted tracked build inputs from clean source using the existing clean-Git-tree
  method. Use a fresh explicit private Docker context/config and additive source-versioned tags.
- [ ] Build inspector then measurement from that exact context, without build-time secrets or
  parser execution; preserve complete logs and actual inspected image/config/source labels.
- [ ] Export both archives and verify raw index/platform/config/layer hashes using the established
  OCI verification method. Read regular tarfile.py bytes without filesystem extraction; compare
  to official v3.12.15, retain its hash. Confirm actual Python version and exact ten OS pins.
- [ ] Run Syft1.54.0 and Grype0.120.0 on those exact archives with unchanged retained DB;
  retain raw originals, DB before/after hashes and all match/severity/fix-state counts.
- [ ] Require CVE-2026-82049 absent for the corrected Python binary, preserve all other findings;
  compare actual non-Debian dependencies/OS inventory and old image IDs. No High0 rule or waiver.

### M3 — Review, local integration and truthful handoff
**Files:** existing contained-runtime plan/task ledger and `docs/ops/SPATIAL_DATA_LOCAL_VERIFICATION.md`.
**Interfaces:** consumes M1/M2 actual evidence; produces verified task-owned source integration only.
- [ ] Run both packaging/security tests, runtime pins, release/deployment tests and relevant
  inspector/measurement owner regressions. Preserve counts/warnings and explicit unrun gates.
- [ ] Read-only review of task diff and actual evidence; fix only scoped findings, rerun affected
  checks. No standing reviewer loop or unrelated dependency work.
- [ ] Record source/base/image/archive/SBOM/scan identities and limitations, commit owned docs.
- [ ] Recheck clean local main target and task diff; fast-forward authorized task commits and rerun
  affected source contracts on actual main. Retain all workspaces/evidence; no push/cleanup.
- [ ] Report corrected images separately from release/security/host/authority/customer acceptance.

Self-review: spec requirements route to M1 exact source, M2 actual bytes/scans, M3 integration
and limitations. Every Review focus line has its named verification step; no invented authority.
