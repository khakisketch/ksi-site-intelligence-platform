# External inspector Docker-sandbox amendment plan

> **Historical authority — 2026-09-07:** Human approved the semantic amendment
> and local code/test execution. At that point, commits, deployments, daemon
> provisioning, container execution, host-backed synthetic runs, host changes,
> and customer-data handling were outside the approval.

**Goal:** Implement the approved narrow launcher/rootless-daemon replacement
for Task 4's bwrap-only route.

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

**Current authority — 2026-09-08:** the Human explicitly authorized commits,
pushes, deployments, container execution, and required provisioning for this
work. This supersedes the 2026-09-07 operational restriction above. It does not
supply customer data, customer-data handling authority, quantitative authority,
compatibility evidence, physical/HIL evidence, field acceptance, or a release
claim. Each operational result must still record the exact target and evidence.

Tasks 1–4 require the approved amendment semantics and local code/tests. The
current operational authority permits the later synthetic host work once its
code and independent review prerequisites are met; it does not permit an
unsandboxed fallback or weaken any admission fence.

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

### Task 4A: Durable launcher attempts and fixed runtime controls

**Prerequisite and boundary:** Start only after Task 3 is idle and its actual
diff has an independent reviewer PASS. This is processing-controller-local
implementation work. It creates neither a Core route nor a client-selected
runtime, policy limit, image, bind, environment, or Docker privilege. The
parser continues to receive sealed bytes only.

**Requirement IDs and invariants:** REQ-INT-101–104, REQ-SEC-101, and
REQ-OPS-102; enforce INV-024 by recording no accuracy claim, INV-051 by keeping
sanitized output a derivative, INV-053 by producing no quantitative-use
authority, and INV-060 by carrying only the server-derived sealed subject and
fence through the attempt. A bad binding, stale fence, unavailable controller,
unknown profile, or uncertain cleanup fails closed.

**Owner, contracts, and adoption decisions:** `services/processing-controller/`
owns the local attempt journal, staging, launcher protocol, and runtime adapter.
Core continues to own policy, identity, tenant scope, fence, report acceptance,
and eligibility. The closed local journal is append-only canonical UTC JSON with
an event digest, `flock`, and `fsync`; it imports no Core runtime module. Its
records are not a replacement Core journal or an external API contract. The
immutable local protocol and security-profile digests must equal their existing
execution-manifest fields, and the policy grammar digest must equal the local
backend profile digest. Do not introduce capacity values, a new approval gate,
or a zero-overrun timing assertion. The concrete runtime has one pinned Engine
API 1.44 protocol and one operator-configured rootless socket; it has no Docker
CLI, API-version negotiation, image pull/build/tag/list route, label search, or
caller-selected daemon operation. A direct systemd D-Bus client is limited to
the configured launcher identity's user manager and the one durably registered
attempt slice. Raw cgroupfs directory creation and a dummy process scope are
not alternate implementations.

**Reference assets, data, and license:** Read the approved sandbox amendment,
the external validation design, and
`docs/superpowers/specs/2026-09-08-external-geotiff-profile-v1.md` before
implementation. Do not import reference-repository runtime code. Use synthetic
bytes only; source, SBOM, image, and license evidence remain verified inputs to
admission rather than claims made by this task.

**Files:**
- Modify: `services/processing-controller/src/ksi_processing_controller/external_inspector_launcher.py`;
  `services/processing-controller/src/ksi_processing_controller/external_inspector_staging.py`
  created by Task 3.
- Create: `services/processing-controller/src/ksi_processing_controller/external_inspector_attempts.py`;
  `services/processing-controller/src/ksi_processing_controller/external_inspector_runtime.py`;
  `services/processing-controller/src/ksi_processing_controller/external_inspector_container_protocol.py`;
  `services/processing-controller/src/ksi_processing_controller/external_inspector_catalog.py` for
  read-only signed catalog/trust/revocation and exact local OCI-pair proof;
  `services/processing-controller/src/ksi_processing_controller/external_inspector_docker.py` for
  the concrete AF_UNIX Engine API 1.44 adapter; and
  `services/processing-controller/src/ksi_processing_controller/external_inspector_systemd.py` for
  the narrow user-manager transient-slice and cgroup-v2 verifier.
- Create `services/processing-controller/src/ksi_processing_controller/external_inspector_daemon.py`
  only as the production assembly/entrypoint: it consumes explicit operator
  configuration, validates the systemd-activated AF_UNIX listener exactly once,
  and constructs the closed launcher. It does not provision a user, socket,
  daemon, base slice, or policy.
- Modify `services/processing-controller/pyproject.toml` and `uv.lock` when a
  new direct signing or D-Bus import is required; declare it directly and lock
  it, never rely on a transitive dependency. Add only the matching
  `external-inspector` script entrypoint. Task 5b, not Task 4A, owns deploy
  units and operator installation documentation.
- Modify the existing byte-boundary and launcher tests where a concrete
  descriptor/daemon seam is exercised; create
  `tests/contract/test_external_inspector_docker.py`,
  `tests/contract/test_external_inspector_container_protocol.py`,
  `tests/contract/test_external_inspector_runtime_controls.py`, and
  `tests/replay/test_external_inspector_attempt_replay.py`. Create a focused
  daemon test only if the production assembly cannot be covered by those
  contract tests. Host-backed cases remain named `test_host_*`.

**Acceptance criteria:** A successful local attempt has one sealed input, one
verified runtime-parent slice, one verified runtime ID, one current fence, one
bounded cleanup disposition, and no result accepted before exact cleanup reaches
`CLEANED`. The journal order is `INTENDED` → `STAGING_ALLOCATED` → `INPUT_BOUND`
→ `RUNTIME_PARENT_BOUND` → `CONTAINER_BOUND` → `CLEANUP_REQUIRED` → `CLEANED`,
with `STAGING_OWNERSHIP_UNCERTAIN` and `CLEANUP_FAILED` retaining active recovery
evidence. Recovery may inspect only a durably recorded deterministic name,
never a label search or a broad daemon inventory. Every measured resource fact
is explicitly local test or host evidence; unavailable host resolution or kill
latency remains an unavailable or incomplete result until Task 5c measures it.

- [ ] **Step 1: Write RED attempt-state and replay tests.**

  Cover the complete local event state machine. `INTENDED` binds the nonce,
  input digest, operation, container name, owner, execution-manifest and
  parser-build digests, OCI configuration and manifest digests,
  backend/security/resource/protocol digests, and the verified private staging
  root's device, inode, mode, UID and GID. It also binds the deterministic
  staging-directory name, fixed `artifact` leaf, provisional and committed
  sibling marker names, and a fresh allocation nonce. It additionally binds
  the operator-configured base user-slice unit name and the deterministic,
  attempt-derived child slice unit name; no recovery derives either from a
  current default. After the existing binding digest is computed, `INTENDED`
  derives and stores the exact systemd `Description`
  `ksi-external-inspector-attempt.v1:<bindingDigest>`. The description is a
  derived marker, not an input to the binding digest, so it cannot introduce a
  digest cycle. Its canonical marker
  payload has a fixed v1 shape and exact recorded length and SHA-256 over the
  version, attempt nonce, binding digest, staging name, owner, and allocation
  nonce.

  `STAGING_ALLOCATED` is durable before the first input byte. It binds the
  allocation receipt: marker, directory, and empty-artifact identities. Only
  `INPUT_BOUND` may add the sealed size, SHA-256, and reader-mapping witness,
  and it must prove the same staged inode recorded by `STAGING_ALLOCATED`.
  `RUNTIME_PARENT_BOUND` is durable before Docker create. It binds the exact
  transient slice unit `Id`, derived `Description`, configured `Slice`,
  resolved `ControlGroup`, D-Bus object path and `InvocationID`, the verified
  cgroup-v2 directory device/inode identity, the required `cpu`, `memory`, and
  `pids` controllers, `populated=0`, and the real initial `cpu.stat`
  `usage_usec` baseline in `CPU_USEC`. It never invents a zero baseline.
  `CONTAINER_BOUND` binds only the exact runtime-verified container ID and its
  recorded parent slice identity. `CLEANUP_REQUIRED` records only bounded
  cleanup disposition and output metadata, never a response-owned descriptor
  or an anonymous-spool recovery target;
  `CLEANUP_FAILED` stays active recovery evidence; `CLEANED` is written only
  after exact container removal, exact transient-slice disappearance, and
  exact staging-inode cleanup. It may precede closure of a response-owned
  anonymous output descriptor, which is not a sandbox resource or a durable
  artifact. Assert that a duplicate
  closed nonce is retired and that an aborted deterministic staging name leaves
  an observable failure record.

  Add replay cases for every allocation syscall and journal-event boundary:
  after durable `INTENDED` but before the provisional marker, after the
  provisional marker, after the committed marker,
  after directory creation, after the empty artifact, after
  `STAGING_ALLOCATED`, during input write, after seal, and during cleanup.
  Include substitution attempts that must retain rather than delete, exact
  absence, and retry behavior. Retain the existing crashes before parent-slice
  create, after transient-slice creation before durable
  `RUNTIME_PARENT_BOUND`, after parent binding before Docker create, after
  Docker create before returned ID, and after ID before cleanup; an absent recorded
  container; mismatched owner/nonce/image/config/profile; stale trust or
  revocation; unknown profile; and malformed or reordered digest event. A
  recovery path may resolve only the recorded name, prove exact
  owner/nonce/image/config/profile, bind the returned ID, then kill/remove that
  ID. It must never list or delete containers by label. Add a pre-parent
  recovery matrix: name-only resolution never authorizes adoption or stop. Before
  the first `RUNTIME_PARENT_BOUND` receipt, an `INPUT_BOUND` attempt may adopt
  only after comparing current child observations with durable `INTENDED` facts:
  the derived description marker, unit `Id`/name, and configured base `Slice`.
  It must then observe a fresh strict-descendant `ControlGroup`, D-Bus object
  path/`InvocationID`, cgroup-v2 directory device/inode/controller facts,
  `populated=0`, and a real CPU baseline. It durably records those observed
  `InvocationID`, cgroup device/inode, and CPU-baseline facts in the first
  `RUNTIME_PARENT_BOUND` receipt exactly once. Only after that receipt exists
  may later mutations match stored child identity. Tests distinguish a
  same-name recreation or changed invocation that mismatches a recorded receipt
  from an observed identity change during first-time validation; before a
  receipt, recovery never assumes a historical `InvocationID`. A foreign
  marker, missing base, non-cgroup directory, non-empty group, or any mismatch
  stays retained, records `CLEANUP_FAILED`, and closes admission without
  `StopUnit`.

  Add output-spool tests for the `SANITIZE` path. Before `EXECUTE`, reserve the
  manifest's full `maxOutputBytes` aggregate budget and allocate only an
  anonymous descriptor-relative `O_TMPFILE|O_RDWR|O_CLOEXEC` file under the
  verified private operator spool root. It must be a regular, owner/mode and
  device-verified file with link count zero; it is never linked, inherited,
  mounted, passed to the container, named, substituted by `memfd`, or buffered
  in memory. Test the closed states `OPEN` → `SEALED` → `RESPONSE_OWNED` →
  `CLOSED`/`ABORTED`, bounded count/hash/fsync/seal/rewind, full-budget release
  exactly once, crash close/unlink behavior, and no replay recovery target.
  `INSPECT` has no output candidate.

- [ ] **Step 2: Run the RED selections.**

  Run: `uv run --locked pytest tests/contract/test_external_inspector_runtime_controls.py tests/replay/test_external_inspector_attempt_replay.py -k 'not host_' -q`

  Expected: FAIL because the durable state machine and exact recovery adapter
  do not yet exist.

- [ ] **Step 3: Implement canonical attempt persistence and exact staging
  binding.**

  `external_inspector_attempts.py` appends a canonical, closed event object
  while holding an advisory exclusive `flock`, flushes and `fsync`s each record,
  and verifies the prior chain and event digest before reopening. It accepts only
  aware UTC timestamps and finite fixed manifest values.

  The launcher writes and fsyncs `INTENDED` before allocation. It then verifies
  the recorded private root through its retained directory descriptor and uses
  only descriptor-relative names. Under that root descriptor it creates the
  provisional marker with `O_CREAT|O_EXCL|O_NOFOLLOW`, mode `0600`; writes the
  exact canonical marker payload; and fsyncs it. It creates the committed
  sibling only by a non-replacing hard link, fsyncs the root, unlinks the
  provisional name, and fsyncs the root again. It creates the deterministic
  staging directory with mode `0700`, opens that directory with
  `O_DIRECTORY|O_NOFOLLOW`, and creates its fixed `artifact` leaf with
  `O_CREAT|O_EXCL|O_NOFOLLOW`, mode `0600`. It fsyncs the empty artifact, the
  staging directory, and the root. The receipt records the marker, directory,
  and empty-file identities; the launcher appends and fsyncs
  `STAGING_ALLOCATED` before accepting any streamed byte.

  `external_inspector_staging.py` supplies the sealed identity and reader
  witness from Task 3; it neither converts UIDs arithmetically nor exposes a
  host path to the worker. `INPUT_BOUND` follows a same-inode recheck and adds
  only the sealed size, SHA-256, and reader witness. The launcher records an
  observable failure if an exact registered allocation cannot be closed.

  Recovery first re-verifies the recorded root descriptor identity and uses the
  recorded names only. All allocation names absent is clean. A provisional-only
  marker is unlinked only when its expected prefix, owner, mode, link count,
  and absence of both the committed marker and staging directory are exact. If
  both markers exist, they must be the same inode, have the full recorded hash,
  and have link count two. A committed-only marker proves the named directory
  allocation; an absent directory permits exact marker removal. When that
  directory exists, recovery captures the directory and optional-artifact
  identities, reconstructs the allocation receipt only when it is complete,
  then performs exact cleanup. An unknown marker, symlink, wrong type, owner or
  link count, unexpected child, or recorded-identity mismatch is retained and
  records `STAGING_OWNERSHIP_UNCERTAIN` plus `CLEANUP_FAILED`; admission closes.
  Recovery never deletes from a pathname proof alone.

  Exact staging cleanup checks the recorded artifact identity through the
  retained directory descriptor, unlinks that artifact, fsyncs the staging
  directory and root, checks the recorded directory identity, removes the now
  empty directory, and fsyncs the root. It then unlinks only the exact committed
  marker, fsyncs the root, and only then writes durable `CLEANED`.

- [ ] **Step 4: Write RED fixed-runtime and CPU-accounting tests.**

  Test that runtime construction accepts only signed container UID/GID and
  fixed environment from the verified manifest; one read-only bind at
  `/input/artifact.tif`; the verified OCI image/configuration; and no network,
  socket, credential, extra mount, supplementary group, capability, writable
  root, or new privilege. Cover bounded tmpfs, memory/swap, PID, rate, log, and
  output settings without choosing a new numeric default.

  Exercise `max_cpu_seconds` conversion to one proven integer aggregate-counter
  unit. The conversion, counter unit, and comparison must be unambiguous and a
  zero budget is rejected. Require a fresh baseline, including a nonzero
  baseline case, and an observed cgroup controller before create. The counter
  must cover the complete process tree, be monotonic and nonnegative, and the
  monitor and final check
  must both compare `consumed = current_counter - baseline_counter` in that
  same unit. A counter read failure, rollback below baseline, negative value,
  or unit ambiguity makes the request incomplete and requires exact cleanup.
  During execution kill when consumed CPU exceeds the bound; an exact-boundary
  final value is accepted only when every other terminal fence, deadline, and
  cleanup condition succeeds. After the whole process tree exits, but before
  accepting output, Docker removal, or stopping the registered slice, read
  stable final usage. Test a
  nonzero baseline, exact boundary, descendant CPU use, counter rollback, and
  monitor/final consistency. Wall deadline and CPU rate remain independent
  controls.

  Add closed adapter tests for the only permitted runtime assembly. The signed
  catalog must verify the Ed25519 trust/revocation decision and exact local OCI
  configuration plus manifest pair before create; the selected local image must
  expose the matching `RepoDigest` pair and no image-declared volumes. The
  Engine transport sends only API 1.44 requests over the verified rootless
  AF_UNIX socket. It attaches before start and bounds Docker multiplexed
  stdout, inspector output, stderr, and private spool independently; it never
  obtains results from `docker logs`.

  Test the direct user-manager call
  `StartTransientUnit(attemptSlice, "fail", properties, [])` with exactly the
  recorded attempt slice. Its properties include `Description`,
  `CPUAccounting=true`, `MemoryAccounting=true`, `TasksAccounting=true`,
  `StopWhenUnneeded=false`, and `CollectMode=inactive-or-failed`. Resolve the
  returned `ControlGroup`, require it to be a strict descendant of the base
  slice's resolved `ControlGroup`, retain its D-Bus unit identity when exposed,
  open and retain that exact cgroup directory, require cgroup v2 and the
  `cpu`, `memory`, and `pids` controllers, and read the real initial `cpu.stat`
  `usage_usec` as `CPU_USEC`. Reject reused unit names, a missing/foreign
  manager, controller loss, inode mismatch, or any unknown child. Do not
  approximate the signed CPU quota/period as a systemd property: Docker/runc
  alone applies the exact per-container controls.

  Test that Docker `HostConfig.CgroupParent` receives the exact slice *unit
  name*, never a cgroup filesystem path. After start, the container remains
  before `EXECUTE` until its exact returned ID, init PID `0::` cgroup, and sole
  `docker-<full-ID>.scope` child are proven under that attempt slice. Verify the
  exact `cpu.max`, `memory.max`, `memory.swap.max`, and `pids.max` facts in that
  scope; no-swap requires both the Engine memory-swap request and
  `memory.swap.max=0` proof. Test failures at every point as unavailable or
  incomplete with registered cleanup, not as a best-effort continuation.

  Test the private output spool as a response handoff, not an artifact sink.
  `SANITIZE` reserves the entire signed `maxOutputBytes` before `EXECUTE` and
  retains that reservation through the one close path. The launcher alone
  creates the descriptor-relative anonymous `O_TMPFILE|O_RDWR|O_CLOEXEC` file
  below its verified private spool root, verifies a regular file and configured
  owner/mode/device plus `nlink=0`, and keeps its descriptor private. The
  container cannot inherit, mount, link, name, reopen, or receive this
  descriptor. Test aggregate reservation exhaustion, write/count/hash bounds,
  `fsync`, seal, rewind, response ownership, abort, duplicate close, and close
  failure. A close failure halts daemon admission; it does not retry the
  descriptor or change a prior `CLEANED` record.

  Add closed inner-protocol framing tests: each frame is a fixed big-endian
  32-bit length followed by bounded canonical JSON. The handshake is complete
  only through `PREPARE`, `MOUNT_VERIFIED`, `EXECUTE`, and either
  `COMPLETED` with raw exact EOF or `FAILED` with a closed reason and no output.
  `PREPARE` is exactly the canonical object
  `{protocolVersion:"inspector-container.v1", frame:"PREPARE", attemptNonce,
  outerCanonicalInputDigest, operation, sealedByteBinding:SealedByteBindingV1,
  policy:ExternalValidationPolicyV1,
  executionManifestBody:InspectorExecutionManifestBodyV1,
  executionManifestDigest, prepareDigest}`. `prepareDigest` is canonical over
  this body excluding itself. The container strictly recomputes nested active
  policy/policy digest, resource envelope/resource-envelope digest, and manifest
  body digest; requires the manifest digest to equal
  `policy.parserBuildDigest` and the matching resource envelope; checks compiled
  grammar, backend, security, and inner-protocol digests exactly; and applies
  policy envelope parser limits, requires sealed bytes to fit both policy and
  hard ceilings, and applies the same closed effective-overlap rule for the
  sanitizer. The outer digest is opaque launcher correlation only: omitted
  scope/fence/request facts prevent container recomputation. No caller content
  type or artifact-kind field exists in this DTO.

  `MOUNT_VERIFIED` echoes nonce, outer digest, prepare digest, artifact ID, and
  measured size/hash. `EXECUTE` echoes nonce, outer digest, prepare digest, and
  operation only after host/fence/trust checks. Every terminal frame echoes the
  same bindings; `COMPLETED` supplies an exact output header followed by raw EOF,
  while `FAILED` supplies a closed reason and no output. The 4A fixed
  DTO/framing/state and fake-entrypoint tests are consumed by the future 4B
  semantic entrypoint; 4B does not redefine framing. Add adversarial altered
  digest, opaque-outer mismatch, automatic-kind ambiguity, server-kind mismatch,
  and SANITIZE-DSM rejection cases at their owning task.

- [ ] **Step 5: Implement fixed runtime admission, catalog rechecks, and exact
  cleanup.**

  The launcher validates the signed catalog, Ed25519 signature, revocation
  state, exact local OCI configuration/manifest and `RepoDigest` proof,
  manifest/profile/security/protocol bindings, and the sealed input before
  admission. Recheck the same catalog/trust and all binding facts after upload
  and immediately before create. Pass only the admitted manifest to the backend.
  Missing OCI evidence, an image volume, or an unverified local image is an
  unavailable attempt, never a pull or an inferred catalog fact.

  After `INPUT_BOUND`, use the deterministic base/attempt slice names and
  derived description marker already persisted in `INTENDED`, call the
  user-manager D-Bus `StartTransientUnit` with mode `fail`, and resolve the
  exact `Id`, `Description`, `Slice`, `ControlGroup`, object path, and
  `InvocationID`. Verify the marker and base slice, a fresh strict-descendant
  cgroup-v2 directory with exact device/inode/controllers and `populated=0`,
  retain its descriptor, read its non-assumed CPU baseline, then append and
  fsync `RUNTIME_PARENT_BOUND`. Only then may the AF_UNIX Engine API 1.44
  adapter create the deterministic container. It verifies the returned ID
  before appending `CONTAINER_BOUND`, attaches the bounded multiplexed streams
  before start, starts it, and permits `EXECUTE` only after the exact child
  scope and fixed controls are observed. All execution input comes from Task 3's live
  borrowed input capability: a daemon-visible candidate may be derived from
  `/proc/<launcherPID>/fd/N` only after real daemon proof. It must never use
  `/proc/self/fd` or the original staging path as a fallback. Before parse,
  exact mounted read-only identity and digest must be verified; otherwise the
  attempt is unavailable. Task 5c supplies the host proof for proc access,
  canonicalization, user-namespace mapping, and the read-only mount.

  The launcher serializes only the fixed `PREPARE` DTO and requires the
  container's canonical `prepareDigest` recomputation. It carries
  `outerCanonicalInputDigest` strictly as opaque correlation, rejects an altered
  nested policy/envelope/manifest/profile digest, and accepts no caller kind or
  content-type claim. `MOUNT_VERIFIED`, `EXECUTE`, `COMPLETED`, and `FAILED`
  must echo the exact nonce/outer/prepare bindings before the outer launcher
  accepts the fixed outcome mapping or raw exact EOF.

  Before `SANITIZE` `EXECUTE`, the launcher reserves the full signed output
  budget and creates its anonymous private spool under the configured root.
  It bounds bytes while hashing, fsyncs, seals, and rewinds the descriptor; no
  spool descriptor, inode, or path enters an attempt record or recovery input.
  After sandbox cleanup reaches `CLEANED`, it may expose the descriptor only as
  a one-shot UDS response stream. The response owner reads and rehashes it,
  releases the aggregate reservation, and closes it exactly once. Crash or
  abort closes the anonymous file; descriptor close failure closes daemon
  admission without retrying it or rewriting `CLEANED`.

  The runtime adapter reports only the bounded CPU budget, real baseline,
  consumed and final counter values in `CPU_USEC`, threshold disposition, and
  measured kill latency. On every normal, CPU-budget, cancellation, deadline,
  or unavailable terminal path after a staging or runtime resource is
  registered, it appends and fsyncs `CLEANUP_REQUIRED` before the first cleanup
  mutation. On CPU budget, cancellation, or deadline it kills only the exact
  registered ID. It waits for process exit, requires `populated=0`, then reads
  a stable final aggregate CPU value and enforces the final budget before Docker
  removal. It next removes only that exact ID, stops only the exact transient
  slice, verifies the unit/cgroup disappearance, then performs exact
  staged-inode cleanup and writes durable `CLEANED`. A reused name,
  unknown descendant, remove/stop failure, cgroup path retention, controller
  uncertainty, or failed staging cleanup writes `CLEANUP_FAILED`, retains the
  recorded evidence, and closes admission. No path uses a broad scan, label
  reconciliation, or a best-effort cleanup. A completed response is held until
  `CLEANED` is durable. The code documents actual host timer/controller
  resolution and kill latency as Task 5c evidence rather than claiming an
  unmeasured tolerance.

  Pre-`RUNTIME_PARENT_BOUND` recovery never stops a unit merely because its
  name matches. It may adopt only an `INPUT_BOUND` attempt by validating current
  child observations against `INTENDED`: exact derived description marker, unit
  `Id`/name, configured base `Slice`, a fresh strict-descendant control group,
  current D-Bus object path/`InvocationID`, cgroup-v2 directory
  device/inode/controller facts, `populated=0`, and a real CPU baseline. It
  durably writes the first `RUNTIME_PARENT_BOUND` receipt with the observed
  invocation, cgroup device/inode, and baseline before exact registered cleanup.
  Every later controller or cleanup mutation rechecks the marker, base
  `ControlGroup`, cgroup device/inode, and `InvocationID` against that receipt;
  a recreated/foreign unit is never stopped and instead remains evidence under
  `CLEANUP_FAILED`.

  The daemon factory accepts every host path, UID/GID, socket identity, base
  slice, catalog/trust location, cgroup root, spool root, capacity value, and
  monitor cadence as explicit operator configuration. Missing configuration,
  an inherited environment default, a second listener, an unexpected PID/FD
  type/owner/mode, or a mismatch with the fixed protocol/API literal prevents
  production assembly. Task 4A development and its local tests use controlled
  seams and perform no provisioning, container execution, or user-manager host
  operation. The resulting factory performs its narrow I/O only after Task 5b
  configuration and Task 5c host proof.

- [ ] **Step 6: Run local validation and request independent review.**

  Run: `uv run --locked pytest tests/contract/test_external_inspector_launcher.py tests/contract/test_external_inspector_byte_boundary.py tests/contract/test_external_inspector_docker.py tests/contract/test_external_inspector_container_protocol.py tests/contract/test_external_inspector_runtime_controls.py tests/replay/test_external_inspector_attempt_replay.py -k 'not host_' -q`

  Run: `uv run --locked ruff check services/processing-controller/src/ksi_processing_controller/external_inspector_launcher.py services/processing-controller/src/ksi_processing_controller/external_inspector_attempts.py services/processing-controller/src/ksi_processing_controller/external_inspector_runtime.py services/processing-controller/src/ksi_processing_controller/external_inspector_container_protocol.py services/processing-controller/src/ksi_processing_controller/external_inspector_catalog.py services/processing-controller/src/ksi_processing_controller/external_inspector_docker.py services/processing-controller/src/ksi_processing_controller/external_inspector_systemd.py services/processing-controller/src/ksi_processing_controller/external_inspector_daemon.py tests/contract/test_external_inspector_docker.py tests/contract/test_external_inspector_container_protocol.py tests/contract/test_external_inspector_runtime_controls.py tests/replay/test_external_inspector_attempt_replay.py`

  Run: `git diff --check`

  Record the exact local result, then obtain an independent read-only review
  before Task 4B. Do not represent `-k 'not host_'` as host enforcement.

**HIL, data, and rollback:** Tests use synthetic sealed bytes only. No customer
data, host acceptance, deployment, compatibility, HIL, field, or release result
is claimed. Rollback is admission-off, retaining the immutable local attempt
history and doing only exact registered cleanup; never parse unsandboxed or
widen daemon access.

### Task 4B: Deterministic sanitizer and report/output binding

**Prerequisite and boundary:** Begin only after Task 4A receives independent
review PASS. It consumes the Task 3 scanner and Task 4A admitted manifest; it
does not reopen Task 3 grammar decisions. Task 7 owns HTTP submit, display
grant, upload, and seal under existing Core contracts. This task creates no new
Core route, schema, policy, storage grant, or network submission path.

**Requirement IDs and invariants:** REQ-INT-101–104, REQ-SEC-101, and
REQ-OPS-102 apply. The sanitizer records a derivative receipt candidate only,
so INV-051 remains intact. It makes no accuracy or quantitative eligibility
claim (INV-024/053), and it uses the sealed, server-derived subject/fence only
(INV-060).

**Reference assets, data, and license:** Read the Task 3 reviewed scanner and
the fixed GeoTIFF profile before changing sanitizer code. Do not change profile
grammar, use customer bytes, or derive producer compatibility, license, or
accuracy evidence from synthetic output.

**Owner, contracts, and adoption decisions:** The processing-controller owns
the deterministic local inspection/sanitization computation and attempt-scoped
sink. The closed GeoTIFF profile is the source of scanner and sanitizer rules:
the 4B semantic entrypoint consumes the closed 4A frame and classifies only raw
RGB/RGBA uint8 as ORTHO or one-band Float32/Float64 as DSM. Ambiguous or
unsupported samples are rejected; only ORTHO is eligible for SANITIZE and DSM
is rejected for that operation. The report assembler compares returned band
count and dtype with the exact server-declared artifact kind. A mismatch is the
existing `REJECTED` / `UNSUPPORTED_RASTER` result and discards measurements.
The scanner and sanitizer never publish bytes or a receipt on a failure. A pure
report assembler has exactly one outcome for each sealed artifact and returns
no partial report for cancellation, fence loss, or runtime failure. Task 7
independently repeats this consistency check before retaining a `MEASURED`
outcome; this is a downstream requirement, not a new route, schema, reason, or
approval gate.

**Files:**
- Modify: `services/processing-controller/src/ksi_processing_controller/external_geotiff_inspector.py`;
  `services/processing-controller/src/ksi_processing_controller/external_artifact_inspection_worker.py`;
  `services/processing-controller/src/ksi_processing_controller/external_inspector_launcher.py`;
  `services/processing-controller/src/ksi_processing_controller/external_inspector_protocol.py`.
- Create: `services/processing-controller/src/ksi_processing_controller/external_sanitized_raster.py` and
  `services/processing-controller/src/ksi_processing_controller/external_inspector_container_entrypoint.py`.
- Modify/Create tests: `tests/contract/test_external_geotiff_inspector.py`,
  `tests/contract/test_external_artifact_inspection_worker.py`, and
  `tests/contract/test_external_sanitized_raster.py`.

**Acceptance criteria:** SANITIZE uses the fixed profile to produce RGB3 with a
binary internal mask and deterministically remeasures it. `finish` may produce
only a private, verified candidate after the completed header's exact size and
SHA-256 are confirmed. It exposes neither bytes nor a receipt. Before any
handoff, recheck that the retained report and sealed-byte binding are still the
same immutable records and recheck current policy, build, fence, and authority
facts. Loss after hashing but before handoff aborts the candidate. Task 7 alone
may use the retained private candidate for the existing display grant, upload,
and seal flow. The remeasurement proves
full-resolution valid RGB equivalence, validity-mask equivalence, dimensions,
CRS, affine transform, footprint, and fixed COG facts. Failure leaves no output
bytes or receipt.

- [ ] **Step 1: Write RED sanitizer and no-partial-publication tests.**

  Add fixtures for a valid RGB ORTHO with a binary alpha/mask boundary, invalid
  pixels, a valid DSM, and malformed scanner output. Assert that only the ORTHO
  can start SANITIZE; alpha becomes the binary internal mask; invalid RGB is
  zeroed; valid RGB is exact; and the fixed profile uses no full-resolution
  transformation. Test deterministic repeat output, stripped producer metadata,
  reopened COG/profile checks, and failure on a changed valid pixel, mask, CRS,
  affine, footprint, dimensions, overview chain, or output digest.

  Model an attempt-scoped transactional sink with
  `begin(binding, deadline)`, `write(chunk)`, `finish(header)`, and `abort()`.
  `finish` accepts only the completed header's exact size and SHA-256 and
  returns a private verified candidate, never exposed bytes or a receipt. Test
  a fresh retained-report, sealed-byte, policy, build, fence, and authority
  recheck immediately before handoff. Assert that a short stream, an extra byte,
  hash mismatch, cancellation, fence loss before or after hashing, scanner
  rejection, authority loss, or cleanup failure calls `abort()` and exposes no
  bytes or receipt.

- [ ] **Step 2: Run the RED selections.**

  Run: `uv run --locked pytest tests/contract/test_external_geotiff_inspector.py tests/contract/test_external_artifact_inspection_worker.py tests/contract/test_external_sanitized_raster.py -k 'not host_' -q`

  Expected: FAIL because deterministic sanitizer output verification and the
  transactional sink are not yet implemented.

- [ ] **Step 3: Implement the fixed container entrypoint and sanitizer.**

  `external_inspector_container_entrypoint.py` accepts only the admitted
  manifest and fixed operation protocol from Task 4A. For an ORTHO, the
  sanitizer writes pixel-interleaved RGB3 plus one-bit internal mask, 512-pixel
  tiles, DEFLATE, standard predictor, a single thread, no sparse blocks,
  `BIGTIFF=IF_SAFER`, GeoTIFF 1.1, no statistics, and fresh average-color /
  nearest-mask overviews. It strips producer metadata and preserves only the
  profile-required GeoKeys and validity information. It performs no crop,
  reprojection, resampling, color conversion, stretch, repair, or coordinate
  transform.

  Reopen the candidate with the Task 3 scanner and compare all profile-required
  facts before emitting a bounded completed header. The caller sends the stream
  to the transactional sink only after Task 4A has reached durable `CLEANED`.
  The sink retains the verified candidate privately until the immediate pre-
  handoff recheck succeeds. The implementation must not infer a display grant,
  publish a receipt, or call Core; Task 7 owns the existing grant/upload/seal
  handoff.

- [ ] **Step 4: Implement complete per-artifact report assembly.**

  Assemble a pure report over sorted sealed bindings under the current fence and
  one admitted build. Recheck current fence and binding after each inspection
  return and once more before returning. Emit exactly one per-artifact outcome:
  structural/profile/cap failures become that artifact's typed `REJECTED`
  outcome under the GeoTIFF profile's failure semantics; request cancellation,
  stale fence, deadline, runtime unavailability, or a pre-examination failure
  makes the request incomplete and emits no invented outcome for unexamined
  artifacts. An optional bad DSM must not erase a measured ORTHO result. Keep
  the assembly and worker/client seam local and injectable for Task 7; do not
  submit, grant, upload, or seal here.

- [ ] **Step 5: Run local validation and request independent review.**

  Run: `uv run --locked pytest tests/contract/test_external_inspector_launcher.py tests/contract/test_external_inspector_byte_boundary.py tests/contract/test_external_inspector_runtime_controls.py tests/contract/test_external_geotiff_inspector.py tests/contract/test_external_artifact_inspection_worker.py tests/contract/test_external_sanitized_raster.py tests/replay/test_external_inspector_attempt_replay.py -k 'not host_' -q`

  Run: `git diff --check`

  Independently review the complete Task 4A+4B diff before Task 5a or Task 5b.
  The reviewer must check crash windows, exact cleanup, replay, unknown profile,
  stale trust, limits, cancellation, no output before cleanup, sanitizer
  determinism, metadata stripping, and full-resolution equivalence. Host tests
  remain separately named `test_host_*`; a fake host result is not acceptance.

**HIL, data, and rollback:** This remains synthetic parser/worker evidence.
Customer artifacts, actual rootless enforcement, accuracy, compatibility,
quantitative use, HIL, field acceptance, and release remain unverified. Rollback
turns admission off, aborts only the current transactional sink, and performs
only the exact Task 4A registered cleanup.

### Task 5a: Security-test authoring

**Files:** Create `tests/contract/test_external_inspector_adversarial_inputs.py`.

- [ ] Author synthetic hostile TIFF/archive/sidecar/VSI/decompression, network
  canary, mount, parser-output, path/credential leak, and Docker-denial tests.
  This code/test authoring may parallel documentation. Run shared-host cases
  only after Task 4's reviewed implementation and the documented host target
  have been selected under the current operational authority.

### Task 5b: Launcher provisioning

**Files:** The current 2026-09-08 operational authority permits this only after
the Task 4 implementation/review prerequisites: create
`services/processing-controller/deploy/external-inspector-launcher.service`,
`services/processing-controller/deploy/external-inspector-launcher.socket`; modify
`services/processing-controller/README.md`.

- [ ] Under the current operational authority, provision a dedicated UID,
  rootless socket/systemd units, a read-only signed catalog/trust-root/revocation
  source, and existing hard ceilings; document install, health, rollback, and
  the no-Docker worker/Core fence.
- [ ] Provision one fixed base user slice (for example `ksi-inspector.slice`)
  in that dedicated UID's user manager. The rootless Docker service and launcher
  run in the same manager; the base slice delegates the required CPU, memory,
  and PID controllers. Record its configured unit name, resolved `ControlGroup`,
  cgroup root, daemon socket identity, and operator-owned capacity/cadence
  configuration without inventing defaults. Do not pre-create attempt slices or
  alter their per-container quotas here.
- [ ] Verify socket ownership, startup catalog fail-closure, base-slice
  delegation, and the systemd-activated listener shape on synthetic bytes. This
  activates neither policy nor customer-data processing.

### Task 5c: Authorized operational verification

**Files:** Create `docs/audit/EXTERNAL_INSPECTOR_ROOTLESS_PROFILE_VERIFICATION.md`
only after Tasks 5b and the reviewed host-test scope; otherwise no change.

- [ ] Record non-secret daemon/socket, UID mapping, delegated-controller, and
  measured-enforcement evidence. Specifically prove user-manager
  `StartTransientUnit(..., "fail", ...)`, exact child `ControlGroup` descent,
  retained cgroup identity/controllers/initial non-assumed `usage_usec`, exact
  Engine API 1.44 `CgroupParent` slice-unit mapping, init-PID scope identity,
  fixed scope controls, bounded attach plus anonymous-spool/response-close
  behavior, `populated=0`, stable final CPU before exact Docker removal, exact
  `StopUnit`, and unit/cgroup disappearance before staging cleanup. Unavailable
  is failure. Run Task 4 and 5a host-backed checks sequentially on the approved
  synthetic host.
- [ ] Run the decisive host selection: `uv run --locked pytest tests/contract/test_external_inspector_docker.py tests/contract/test_external_inspector_runtime_controls.py tests/contract/test_external_inspector_byte_boundary.py tests/contract/test_external_geotiff_inspector.py tests/contract/test_external_artifact_inspection_worker.py tests/contract/test_external_sanitized_raster.py tests/contract/test_external_inspector_adversarial_inputs.py tests/replay/test_external_inspector_attempt_replay.py -k 'host_' -q`. Collection must include real controller enforcement, UID/RO bind, no-network, hostile-input, cancellation and orphan-recovery cases; no collected tests, unavailable runtime, skips or incomplete coverage do not pass. Only actual successful execution can close the host-enforcement gate.

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

Under the current authority, in the assigned worktree only:

```bash
uv run --locked pytest tests/contract/test_inspector_execution_manifest.py tests/contract/test_external_inspector_launcher.py tests/contract/test_external_inspector_byte_boundary.py tests/contract/test_external_inspector_runtime_controls.py tests/contract/test_external_inspector_adversarial_inputs.py tests/replay/test_external_inspector_attempt_replay.py -q
uv run --locked pytest tests/contract/test_external_geotiff_inspector.py tests/contract/test_external_artifact_inspection_worker.py tests/contract/test_external_sanitized_raster.py -q
git diff --check
```

The tasks cover immutable authority, local authorization, byte/parser containment,
enforced limits/cleanup, and hostile/operational evidence. Numeric production
limits, profile compatibility, capacity, accuracy, and vendor support remain
separate authorities.
