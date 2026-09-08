# External inspector Docker-sandbox amendment plan

> **For agentic workers:** Human approved semantic and local code/test execution
> on 2026-09-07. Use subagent-driven-development with independent task review.
> No commit, deployment, daemon provisioning, container execution, host-backed
> synthetic run, host change, or customer-data handling is authorized.

**Goal:** Implement the approved narrow launcher/rootless-daemon replacement
for Task 4's bwrap-only route. Host provisioning and execution remain separately
approval-gated.

**Architecture:** A processing-controller-local UDS launcher under a distinct
OS identity alone controls a dedicated rootless daemon. The trusted worker
supplies pinned Core policy/envelope; launcher validates binding and local signed
manifest, then fixes runtime choices. Core retains current policy/fence authority;
worker and parser never receive Docker access.

**Tech stack:** Python 3.12, `ResourceEnvelopeV1`,
`ExternalValidationPolicyV1`, UDS, signed OCI evidence, rootless Docker, cgroup
v2/systemd.

**Spec:** [approved amendment](../specs/2026-09-07-external-inspector-docker-sandbox-amendment.md).

**Documentation review — 2026-09-07:** Independent reviewer PASS after two
writer correction rounds and a bounded Lead adjudication of the local-versus-host
gate and terminal outcome literal. Lead inspected both documents and validated
relative links and whitespace. This accepts the proposed document's consistency,
not Human adoption, implementation, runtime enforcement or full-goal completion.

## Required record and global fences

- **Status:** APPROVED for local implementation. Only the original Task 4
  sandbox-runner requirement is superseded; all other requirements remain.
- **Requirements/invariants:** REQ-INT-101–104, REQ-SEC-101, REQ-OPS-102;
  INV-024/051/053/060 remain fail-closed.
- **Ownership/contracts:** processing-controller measures; Core owns identity,
  policy, journals, fences, and eligibility. Additive contracts only. No client
  socket, image, URL, path, env, or flags.
- **Assets/data/license/HIL:** diagnostic is feasibility only; source/SBOM/image
  and license evidence are gates; synthetic-only; no HIL claim.
- **Rollback:** admission-off and exact attempt-registry cleanup; no unsandboxed
  parse or broad daemon cleanup.

Tasks 1–4 require Human approval of amendment semantics and local code/tests;
pure serialization/unit work may proceed only under that approval. Actual
container execution, resource-exhaustion checks, and host operations require a
separate scoped synthetic-run approval. Identity/daemon/UDS provisioning and
signed image/profile evidence are separately authorized. Denial leaves bwrap.

This supplements existing Task 4 and replaces only its bwrap-runner paragraph.
All inherited behavior and acceptance remains required: full GeoTIFF/COG scan
and nodata, per-artifact/incomplete outcomes, report-first/display takeover,
display grant/seal, sanitizer, and original tests
`test_external_geotiff_inspector.py`,
`test_external_artifact_inspection_worker.py`, and
`test_external_sanitized_raster.py`.

Tasks 1–4 are sequential: writer idle and reviewer PASS for the implementation
and pure/local-test slice before the next task. This initial PASS explicitly
leaves real container/control enforcement `NOT_VERIFIED`; it does not require
host provisioning and does not block Task 5b. Every test requiring a Docker
daemon or provisioned identity is named `test_host_*` and is excluded from this
initial gate with `-k 'not host_'`. No skip, mock or excluded case counts as host
acceptance. Task 5c is the decisive real-enforcement gate before integration.
Task 5a authoring may parallel documentation in disjoint worktrees; shared-host
runs are sequential, with provisioning 5b before verification 5c and never two
host mutators. Integration review precedes Task 6. Results are local, not release.

### Task 1: Freeze execution contract

**Local result — 2026-09-07:** Implemented; independent specification and quality
review PASS after one correction round. Reviewer and Lead each ran the 101-test
contract selection below successfully. Ruff/mypy passed. JSON Schema is the
structural gate; the exported conformance parser additionally enforces canonical
ordering and body/signature digest equality. This is not cryptographic trust,
container enforcement, host acceptance, or full-goal completion evidence.

**Files:** Create `packages/event-contracts/src/ksi_event_contracts/inspector_execution_manifest.py`;
create `contracts/schemas/inspector-execution-manifest.v1.json` and
`tests/contract/test_inspector_execution_manifest.py`.

- [ ] RED: closed additive manifest tests for exact image/source/build/SBOM/
  protocol/backend/security digests, fixed env/grids/UID, finite ceilings, and
  `parserBuildDigest = inspectorBuildDigest = SHA-256(canonical body excluding
  signature/self digest)` with detached signature and no self cycle.
- [ ] Minimal immutable canonical/signature model; derive the two equal build
  digests from the body, bind canonical envelope, and reject absent/unlimited/
  mismatched/caller-substituted profiles.
- [ ] Keep existing external-artifact models and policy/report schemas unchanged.
  Use separate frozen body, detached Ed25519 signature, and envelope models;
  canonical identity covers only the body. Pure signature-verifier port has no
  default implementation; real cryptography/trust/revocation belongs to the
  later launcher. Contract acceptance is not signature authenticity or runtime
  enforcement evidence.
- [ ] Add schema-parity plus policy/report build-digest mismatch tests; do not
  change the policy schema for this semantic equality.
- [ ] Run `uv run --locked pytest tests/contract/test_inspector_execution_manifest.py tests/contract/test_external_validation_policy.py tests/contract/test_external_artifact_validation_contracts.py -q`.

### Task 2: Build launcher-only UDS protocol

**Current local status — 2026-09-07:** FINAL INTEGRATED LOCAL PASS after
independent Task 2 review and fresh combined integration review. Task 2's five
owned files reject exponent overflow and non-finite JSON, cancel upload
cooperatively on current-authority loss without resetting the absolute deadline,
reject explicit-null terminal wire variants, fail closed after late post-return
deadline checks including catalog/verifier admission, release a late SANITIZE
output reservation, and close a late-returned byte source before launch. The
Task 2 selection passed 40 tests; Ruff and three-source mypy passed; the
combined Task 1 + 1b + 2 selection passed 184 tests. The final combined review
is recorded in
`.superpowers/sdd/2026-09-07-external-inspector-docker-sandbox-amendment/integration-review.md`.
This is local byte-only evidence only: no host/container/identity/key/parser-profile,
deployment, HIL, customer-data, compatibility, or release gate is satisfied.
Detailed evidence and historical handoff are in
`.superpowers/sdd/2026-09-07-external-inspector-docker-sandbox-amendment/`.

**Prerequisite discovered during implementation:** First complete Task 1b below.
Core currently returns DISPLAY input with an empty artifact tuple; a successor
worker cannot re-read the sealed original for deterministic sanitization.

**Files:** Create `services/processing-controller/src/ksi_processing_controller/external_inspector_launcher.py`,
`external_inspector_protocol.py`, `external_artifact_inspection_worker.py`;
create `tests/contract/test_external_inspector_launcher.py`,
`tests/contract/test_external_artifact_inspection_worker.py`.

- [ ] RED: capped framing, fixed verbs, `SO_PEERCRED`, trusted record/current
  fence, canonical DTO digest, rejected runtime inputs, and pre-launch caps.
- [ ] Implement `InspectorLaunchRequestV1`/`InspectorLaunchResultV1` only.
  Trust existing Core fenced input/heartbeat adapter; add no Core route/port.
  Resolve signed manifest from read-only catalog, verify trust-root/catalog
  identity/revocation at startup, and clamp pinned envelope to hard ceilings.
- [ ] Run `uv run --locked pytest tests/contract/test_external_inspector_launcher.py tests/contract/test_external_artifact_inspection_worker.py -k 'not host_' -q`.

### Task 3: Enforce sealed-byte handoff

**Implementation preflight — 2026-09-07:** Positive GeoTIFF/COG parsing requires
an explicit immutable grammar/profile specification for supported structures,
compression, masks/nodata/overviews, COG conformance and CRS/vertical resolution.
No profile values or producer compatibility were approved by the sandbox
amendment. Complete Task 2's byte-only boundary, then obtain profile review before
positive parser implementation. Do not treat installed GDAL or fake parser ports
as that approval or as full-scan evidence; a narrower Task 3 split is not adopted.

**Files:** Modify `external_inspector_launcher.py`; create `external_geotiff_inspector.py`;
create `tests/contract/test_external_inspector_byte_boundary.py`,
`tests/contract/test_external_geotiff_inspector.py`.

- [ ] RED: count/hash/magic hints; private fixed bind; symlink/hardlink/TOCTOU
  rejection; UID-mapping failure; no host GDAL preflight.
- [ ] Implement private staging and fixed signed runtime. Parse only in
  container; prohibit network, credentials, plugin/PAM, remote VSI, unapproved
  grids, workspace/socket/customer mounts.
- [ ] Run `uv run --locked pytest tests/contract/test_external_inspector_byte_boundary.py tests/contract/test_external_geotiff_inspector.py -k 'not host_' -q`. Host-dependent byte/UID/mount cases remain `NOT_VERIFIED` until Task 5c.

### Task 4: Enforce controls, cleanup, report binding

**Files:** Modify `external_inspector_launcher.py`, `external_artifact_inspection_worker.py`;
create `external_sanitized_raster.py`,
`tests/contract/test_external_inspector_runtime_controls.py`,
`tests/replay/test_external_inspector_attempt_replay.py`,
`tests/contract/test_external_sanitized_raster.py`.

- [ ] Author separate pure decision/cleanup-state tests and `test_host_*` cases
  for actual cgroup-v2/systemd CPU/memory/PID delegation, output/tmpfs/log
  caps, timeout, exact ID/owner cleanup, stale fence, cleanup closure, replay
  inspector-build binding, and crashes before create, after create-before-ID,
  and after-ID-before-cleanup.
- [ ] Typed unavailable/rejection outcomes; verify controllers, registry-only
  kill/remove, durable intent/nonce/known-name records before create, exact
  name-owner-profile startup recovery, and no label-wide reconciliation.
- [ ] Run `uv run --locked pytest tests/contract/test_external_inspector_runtime_controls.py tests/replay/test_external_inspector_attempt_replay.py tests/contract/test_external_sanitized_raster.py -k 'not host_' -q`. Record only the implementation/pure-test review result; actual enforcement remains `NOT_VERIFIED` for Task 5c.

### Task 5a: Security-test authoring

**Files:** Create `tests/contract/test_external_inspector_adversarial_inputs.py`.

- [ ] Author synthetic hostile TIFF/archive/sidecar/VSI/decompression, network
  canary, mount, parser-output, path/credential leak, and Docker-denial tests.
  This code/test authoring may parallel documentation; do not run shared-host
  cases without scoped synthetic-run approval.

### Task 5b: Separately authorized launcher provisioning

**Files:** Proposed only after operational authority: create
`services/processing-controller/deploy/external-inspector-launcher.service`,
`services/processing-controller/deploy/external-inspector-launcher.socket`; modify
`services/processing-controller/README.md`.

- [ ] Provision dedicated UID, rootless socket/systemd units, read-only signed
  catalog/trust-root/revocation source, and hard ceilings only with explicit
  authority; document install, health, rollback, and no-Docker worker/Core fence.
- [ ] Verify socket ownership, startup catalog fail-closure, and delegation on
  synthetic bytes. This is outside code approval and activates neither policy
  nor customer-data processing.

### Task 5c: Authorized operational verification

**Files:** Create `docs/audit/EXTERNAL_INSPECTOR_ROOTLESS_PROFILE_VERIFICATION.md`
only after Tasks 5b and scoped synthetic-run approval; otherwise no change.

- [ ] Record non-secret daemon/socket, UID mapping, delegated-controller, and
  measured-enforcement evidence. Unavailable is failure. Run Task 4 and 5a
  host-backed checks sequentially on the approved synthetic host.
- [ ] Run the decisive host selection: `uv run --locked pytest tests/contract/test_external_inspector_runtime_controls.py tests/contract/test_external_inspector_byte_boundary.py tests/contract/test_external_geotiff_inspector.py tests/contract/test_external_artifact_inspection_worker.py tests/contract/test_external_sanitized_raster.py tests/contract/test_external_inspector_adversarial_inputs.py tests/replay/test_external_inspector_attempt_replay.py -k 'host_' -q`. Collection must include real controller enforcement, UID/RO bind, no-network, hostile-input, cancellation and orphan-recovery cases; no collected tests, unavailable runtime, skips or incomplete coverage do not pass. Only actual successful execution can close the host-enforcement gate.

### Task 6: Integration/release-boundary review

**Files:** No implementation files; review accepted combined diff and evidence.

- [ ] Review authority/tenant fences, untrusted input, Docker/mount/credential
  exposure, signature binding, cleanup scope, and all four invariants.
- [ ] Lead runs the union below plus `git diff --check`; integration reviewer
  reconciles Task 5 evidence. Record local result separately from activation,
  compatibility, deployment, HIL, customer acceptance, and release.

## Planned validation

### Task 1b prerequisite: Restore fenced DISPLAY source input

**Local result — 2026-09-07:** Implemented with independent Spec/Quality PASS
after one test-evidence correction round. Four-suite contract/replay selection:
43 passed independently; Lead combined Task 1 + 1b selection: 144 passed.
Ruff/mypy passed. These synthetic-storage checks are not external-storage,
container, host, deployment, or customer acceptance.

**Files:** Modify only `services/core/src/ksi_core/external_artifact_inspections.py`
and `tests/contract/test_external_artifact_inspections.py`.

- [ ] RED: a successor DISPLAY lease receives the same sealed artifact identity,
  kind, digest, size and content type as INSPECT plus a fresh read-only source GET
  capability; retained report remains exact and is never recomputed.
- [ ] Reuse the existing sealed-artifact projection for both phases. Preserve
  the current policy/fence/deadline/unfinished-display checks before storage I/O;
  presign outside locks, then recheck fresh time, report/state, policy, fence,
  deadline and display status before returning any capability.
- [ ] Test predecessor rejection/no mint, policy revocation/supersession/no mint,
  expiry/takeover/revocation during presign/no returned capability, finished
  display/no mint, storage failure, and unchanged accepted report/history.
- [ ] Run `uv run --locked pytest tests/contract/test_external_artifact_inspections.py tests/contract/test_external_display_artifacts.py tests/replay/test_external_artifact_inspections_replay.py tests/replay/test_external_display_artifacts_replay.py -q`; independent review then Lead integrated check before Task 2.

This fixes an existing approved resume requirement; no new principal, API route,
schema, journal format, display upload grant, policy or customer-data action.
Sequence: Task 1 -> Task 1b -> Task 2 -> Task 3 -> Task 4.

After approval, in the assigned worktree only:

```bash
uv run --locked pytest tests/contract/test_inspector_execution_manifest.py tests/contract/test_external_inspector_launcher.py tests/contract/test_external_inspector_byte_boundary.py tests/contract/test_external_inspector_runtime_controls.py tests/contract/test_external_inspector_adversarial_inputs.py tests/replay/test_external_inspector_attempt_replay.py -q
uv run --locked pytest tests/contract/test_external_geotiff_inspector.py tests/contract/test_external_artifact_inspection_worker.py tests/contract/test_external_sanitized_raster.py -q
git diff --check
```

The tasks cover immutable authority, local authorization, byte/parser containment,
enforced limits/cleanup, and hostile/operational evidence. Numeric production
limits, profile compatibility, capacity, accuracy, and vendor support remain
separate authorities.
