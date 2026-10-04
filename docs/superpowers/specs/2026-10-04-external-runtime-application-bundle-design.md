# Protected external-runtime application bundle design

Date: 2026-10-04
Status: Human selected **separately supplied Python + offline wheels** and approved the
presented direction for writing this spec. Written-spec review is pending. No implementation,
actual application bundle, interpreter provisioning, host installation or activation is approved
by the existence of this document. Preserve the previously selected inline execution method.

## 1. Purpose, responsibility and acceptance boundary

Prepare source/lock-bound, noneditable application artifacts for the three existing fixed host
programs, without copying an editable image/dev virtual environment or assuming host Python
compatibility. A separate explicitly supplied verifiedCPython3.12.15 remains necessary. The
bundle must be independently inspectable and fail closed before it becomes executable preparation.

Product direction is unchanged: inspect customer/exported DSM/orthophoto artifacts, perform
authorized analysis, and return results/evidence through existing Core/API and selected MCP
contracts. These tools connect deployment evidence; they neither reconstruct images nor create
Core policy, customer data rights, quantitative eligibility or execution authority.

After real bundle/configuration/authority/containment prerequisites and separate activation
approval are met, the first product execution target is deliberately small: **one expressly
permitted test DSM → actual Inspector and existing worker → durable inspection result in Core**.
Only after that passes connect two-epoch analysis and result/evidence queries. Static wheel
validation, generated tests and imports are not evidence that this live target ran.

Required packet:

- Requirement IDs: REQ-OPS-101, REQ-SEC-101; EXT-VAL-05/06/08 preparation only.
- Owner: artifact tools in`tools/`, additive contracts in`contracts/schemas/`, existing
  processing-controller package/entrypoints and deployment documentation. No new service.
- Invariants: INV-054 enforces distinct exact source/lock/build/artifact/runtime identities;
  INV-051/053/055/060 remain unchanged, with no lineage, quantity, policy or tenant grant.
- Contracts: new application-bundle and separate Python-binding records only. Existing canonical
  release-evidence v1, host-binding v1/v2, Core, operator configs and signed authority wires unchanged.
- Reference assets: current safe-file/strict JSON/manifest patterns, uv0.11.15, existing
  package metadata and systemd units. No reference-repository adoption or edit.
- Acceptance: correct frozen inputs produce a bounded offline bundle; substitutions, incomplete
  dependency closure, editable/path dependencies and unsupported runtime preparation block;
  original source/lock/images/helpers/evidence remain unchanged.
- Tests: small labeled synthetic wheels/records plus genuine source-wheel evidence when required
  prepared builder/wheelhouse/runtime inputs exist. Actual deployment acceptance stays separate.
- HIL/device: none. License/data: existing package licenses and supplied artifact license evidence;
  no customer bytes, public TIFF decoding, new data grant or automatic artifact acquisition.
- Rollback: retain prepared bundles and receipts; stop using the new tools. Never reinterpret a
  partial bundle as an older release or delete originals/installed application state.

## 2. Known environment and unresolved suppliers

All three console scripts belong to`ksi-processing-controller`. The Python requirement is
`>=3.12,<3.13`; dependencies include native cryptography/geospatial/numpy/scipy/Pillow components.
Their wheel tags alone do not establish a working host dynamic-library/interpreter closure.

Current environment-only observations: systemPython3.12.3; developerUV Python3.12.13 under
the user home; Linuxaarch64/glibc2.39. Neither is the required protectedCPython3.12.15 deployment
runtime. Service units useProtectHome and cannot rely on the developer home/checkout. Image
Python3.12.15/OCI provenance does not prove a compatible host executable.

The actual protected Python3.12.15 supplier/location/complete inventory, approved target runtime
observations, external wheelhouse and prepared build-backend closure must be supplied and checked.
Signing/Core/credential/configuration suppliers, publisher/target and durable private custodian
remain unassigned. Missing inputs are blockers, not placeholders to fill with invented authority.

## 3. Fixed release baseline, not moving main

Use four distinct identities in every preparation receipt:

1. **Deployment source commit:** fixed40lowercasehex selected for this candidate. Image config
   revision and application source/lock must genuinely refer to that commit.
2. **Build artifact identities:** exact source snapshot/uv.lock/workspace wheel bytes and original
   image index/manifest/config/archive/SBOM/scanner identities. Application wheels are not image IDs.
3. **Build toolchain identity:** prepared uv executable hash/version, explicit build-Python identity
   and prepared backend inventory. A builder Python is not the deployment interpreter.
4. **Verification code identity:** verifier Git commit and actual tool-file hashes plus commands,
   outcomes and timestamps. A later verification/docs revision is not image-source revision.

The existing lifecycle still executes from an exact clean checkout of the selected deployment
source. Its source equality check is not weakened, replaced or pointed at a movingmain checkout.
Standalone artifact verification may separately use a recorded newer verifier with the fixed
expected deployment source, without creating a new release record. Runtime/build input changes
require an explicitly new candidate; ordinary evidence/doc updates do not move the old baseline.
This spec selects no actual future candidate commit or registry/signing/release approval.

## 4. Outputs and separation of phases

### 4.1 Offline application bundle

A newly created, private, versioned directory contains only:

```text
manifest.json
uv.lock
requirements.txt
wheels/<canonical wheel filenames>
```

No interpreter, copiedvenv, checkout, source-tree path, credential/config/signature, socket,
customer raster, image layer, installed helper or mutable`current` symlink is included.
Do not overwrite an existing destination. The builder owns only its new task-scoped output
and temporary work directories; it cannot clean another plan's workspace or existing evidence.

`manifest.json` has exactly schemaVersion`external-runtime-application-bundle.v1`, source,
target, buildToolchain, files, distributions and entrypoints. Nested records reject unknown fields.
Source binds gitCommitSha, original uv.lock hash/length and a canonical frozen build-input
inventory hash. Each file binds relative safe path, lowercaseSHA256, positive integer bytes and
kind (`lock`, `requirements`, `workspace-wheel`, `external-wheel`). No descriptor trusts a
self-declared config/image ID. The caller must provide an independently reviewed manifest hash
to the verifier; self-generated hashes are byte identities, not authenticity approval.
Exact source fields are`gitCommitSha`, `uvLockSha256`, `uvLockBytes` and
`buildInputInventorySha256`. Target fields are`implementation`, `pythonVersion`, `os`,
`architecture`, `libcFamily`, `libcVersion` and`platformTag`; the last two are explicit selected
target facts, never guessed from the builder. Until the corresponding runtime is supplied and
re-proved, they remain declared preparation requirements, not an actual host observation.
Build toolchain fields are`uvVersion`, `uvSha256`, `buildPythonVersion`, `buildPythonSha256`
and`backendInventorySha256`. The manifest inventory excludesmanifest.json itself to avoid a
self-hash cycle; its independently supplied expected hash protects those records.

Target is the initial explicitCPython3.12.15/LinuxARM64/GNU profile. Distributions record normalized
name, exact version, kind, wheel filename/hash and allowed wheel tags. External wheel bytes must
match the relevant immutable uv.lock entries; workspace wheels must be built from the frozen
source and have no editable or direct-path runtime dependency. The standard dependency resolver,
not a home-made marker evaluator, must prove complete target-specific closure offline.
The current KSI workspace build profile is purePython`py3-none-any` wheels only. A supplied
buildPython from the supported3.12 family may build those source wheels after its explicit
toolchain/backend checks; that does not turn it into deploymentPython3.12.15. A KSI member that
needs a native/source build or undeclared package data is an explicit unsupported-profile blocker,
not a reason to compile it against the developer host. External native wheels use the separately
recorded target ABI and still require real runtime preparation before executable acceptance.

Exactly three application entrypoints are accepted, with their existing module:function mapping:

| Executable | Fixed mapping |
| --- | --- |
| ksi-external-inspector-daemon | ksi_processing_controller.external_inspector_daemon:main |
| ksi-external-measurement-daemon | ksi_processing_controller.external_measurement_daemon:main |
| ksi-external-validation-worker | ksi_processing_controller.external_validation_worker:main |

Other existing package entrypoints may remain in wheel metadata, but this release preparation
does not install/promote them as global host executables or add the Spatial Data launcher lane.

### 4.2 Separately supplied Python binding

A protected`external-runtime-python-binding.v1` record describes the existing interpreter,
runtime inventory and target observations. Required fields bind the absolute interpreter path,
its lowercaseSHA256/length, version3.12.15, implementationCPython, LinuxARM64/GNU platform,
an immutable runtime-root file inventory hash and observed native-library/ABI inventory hash.
Inventory entries identify regular files by safe absolute path/hash/length; symlink targets,
if necessary for a legitimate runtime, must be explicitly resolved into the protected inventory,
not followed through caller-controlled aliases. Group/other-writable or home/developer-checkout
runtime roots are not deployment inputs.
Runtime bindings are current-operator-owned0400/0600 regular files. Deployment interpreter and
runtime/library inventory files must be root-owned, readable as needed and not writable by group
or other; executable files must be root-executable. Accept only the explicitly supplied root
under`/usr/local/lib/ksi-external-runtime/python/` or`/opt/ksi-external-runtime/python/`, with
root-owned nonwritable ancestors. These records describe already provisioned state; the tools
do not create those roots or require a supplier to reveal a signing/credential secret.

The caller supplies the independently reviewed binding hash. The tool rechecks ownership,
permissions, safe ancestor chain, full inventory and actual interpreter file before any probe.
Do not download/provision Python, install system packages or discover a fallback usingPATH.
Missing/mismatched/protected-ownership/ABI evidence blocks executable preparation. The original
binding is read-only; the verifier creates no public key, signature, authority or provider policy.

An actual runtime probe uses only the verified explicit interpreter, fixed local probe code,
isolated/clean environment and a finite timeout. It checks the real version/architecture/ABI and
required native imports in a new private preparation environment from verified wheels. It never
opens a raster, listener, Core client or Docker/userbus endpoint. Imports/native closure alone
still do not establish systemd sandbox or contained Inspector execution acceptance.

### 4.3 Installation preparation only

Preparation produces a new private tree/receipt and an exact operator installation inventory;
it does not copy into`/usr/local`, switch an active release, run root operations or touch units.
It uses noneditable verified wheels and the explicit verified interpreter only. It must not
relocate an editablevenv or claim uv`--relocatable` makes native binaries/interpreter portable.

The future operator inventory preserves global executable paths under
`/usr/local/lib/ksi-external-runtime/bin/`, existing fixed arguments and separate identities.
Any wrapper must replace itself with the fixed interpreter/program (`exec`, no intermediate
child PID), preserve inherited activationFDs/LISTEN_PID/LISTEN_FDS for both daemons, and work
with the validator's cleared environment withoutPATH/PYTHONPATH/user-site/developer checkout.
It may not wrap the daemons in a different container topology, weaken sandbox settings or change
the already installed socket ACL helper. A private preparation success is not a successful global
installation or a claim that service activation descriptors were actually exercised on the host.

## 5. Builder, verifier and input rules

Expected owned files:

- tools/build_external_runtime_application_bundle.py — frozen-source offline artifact creation.
- tools/verify_external_runtime_application_bundle.py — bounded static bundle verification and
  separately opt-in preparation with explicit Python binding. Default verification executes no app.
- contracts/schemas/external-runtime-application-bundle.v1.json.
- contracts/schemas/external-runtime-python-binding.v1.json.
- tests/support/external_application_bundle_fixture.py and focused contract tests; deployment
  README/local evidence/spec/plan/task ledger updates. No application entrypoint/API/UI changes.

Builder inputs: exact clean selected-source checkout/commit, explicit prepared uv executable and
buildPython/backend identities, preexisting external wheelhouse, and new private destination.
Source snapshot is derived from Git-tree allowlisted package/service manifests and source plus
rootpyproject/uv.lock, not `git add .`, Docker-layer extraction or an uncontrolled directory copy.
Exclude reference repos, keys/env/configs/localdata/.venv/cache/test/customer inputs. Validate
module dependencies against the actual workspace and restrict to the processing-controller closure.

Use prepared uv0.11.15 offline/no-Python-download/no-source-build-fallback behavior. `uv export`
must use its supported locked/noneditable/no-dev/package flags; rootlock bytes are checked
before/after. `uv build` has no`--locked` flag on this prepared version: the source/lock snapshot
and no-build-isolation/prepared-backend checks enforce the builder boundary. Do not invent a flag,
silently resolve a new lock or install a backend merely because its manifest lists one.

External packages use supplied wheels only, exact lock hashes and complete offline resolution.
No sdist, editable wheel, path dependency, extra index/network request or unpinned dependency may
recover a missing input. A build toolchain authenticity/license receipt is separate from a hash
match, as with existing Syft/Grype evidence; unresolved authenticity remains explicitly unverified.

Safe readers use descriptor-relative no-follow regular-file access, bounded reads, strictUTF8/
duplicate/nonfinite JSON and before/after descriptor/entry/hash stability. Wheel inspection reads
only bounded standard metadata; it never imports/extracts wheel code during static verification.
ZIP entry names, member types, canonical filenames, metadata identities, entrypoints and RECORD
bindings must agree. Reject traversal, duplicate/conflicting names/records, symlink/special entries,
oversized central directories or metadata and inconsistent name/version/tags/hash/length.
Static RECORD checks establish canonical inventory, field/size/digest syntax and actual hashes
of the metadata that was read; unread executable/native payloads remain bound by the entire
original wheel hash, not a claim that every uncompressed RECORD payload was independently read.
Static verification decompresses bounded metadata only. It does not extract/import native code.

Resource ceilings for this initial preparation profile: total bundle1GiB,256wheel files,
eachwheel256MiB, eachJSON/metadata1MiB, ZIP central directory16MiB and65536entries per wheel,
aggregate262144ZIP entries. Inspect central-directory bounds before allocation by an advanced ZIP
reader; decompressed metadata is bounded independently. Reuse validated file identities/metadata
without hiding conflicting references, and enforce aggregate file/entry/read/probe budgets as
well as per-file limits. No layer/raster decompression or executable import in static verification.
Declared expanded installation contents are bounded to4GiB across the bundle before preparation.
Probe processes have a15second wall deadline and bounded output64KiB; timeout/nonzero/malformed
output blocks and reaps the owned process group. Preparation uses a new private directory only;
failed cleanup is an explicit retained-state blocker, not permission to prune arbitrary paths.
Runtime inventory is limited to8192files/1GiB and16ancestor steps per input; any tree walk/read
consumes a whole-request budget. Native ABI inventory is bounded to512regular-library entries.
These local preparation bounds are not a containment proof for customer raster processing.
Any future profile exceeding a bound needs an explicit reviewed change, not an automatic retry.

Success stages are distinct: BUNDLE_BYTES_VERIFIED, RUNTIME_BINDING_VERIFIED and
INSTALLATION_PREPARED. Report only the stage actually exercised. All evidence failures return
nonzero with safe typed codes; no private paths, inventory contents, token/config bytes or source
payloads in normal diagnostics. A partial record or previous success cannot act as current authority.

## 6. Verification and completion evidence

Test-first source work must exercise real readers/build/verification orchestration against small
labeled artifacts. Mutations recompute outer manifest hashes when testing inner inconsistencies,
so tests do not merely prove an outer hash comparison. Cover at least:

- source/lock/toolchain/manifest/wheel substitution; wrong or incomplete selected closure;
- duplicate/unknown fields, bool/fractional sizes, path/symlink/special/change races and stale pins;
- editable/direct-path/sdist/native-tag mismatches and wrong fixed entrypoint mappings;
- ZIP central-directory, metadata decompression, per-file and aggregate work bounds; shared
  metadata reuse must remain bounded and validate every incoming identity;
- missing/wrong-version/ABI/interpreter inventory and wrong Python-binding hash/ownership;
- nonzero tool/probe exit with plausible stdout, timeout, failure cleanup and no fallback;
- preparation wrapper PID/FD/clean-environment behavior, without claiming mocks prove hostactivation;
- existing release/host/source/authority contracts and untouchedimages/locks/configs/helpers.

Run related and full prepared source regressions, changed-file lint/type/shell checks, one
independent read-only whole-unit review and authorized safe local integration. Keep every original
archive/report/ref/worktree. Genuine bundle/runtime preparation evidence is recorded only when
its actual supplied inputs ran; do not substitute generated wheels for an absent release bundle.
No new installation/acquisition/push/registry/service activation/public-raster run is implicit.

## 7. Next actual execution gate

Before the first permittedDSM probe, require genuine protected application/runtime artifacts,
their release/security disposition, exact source/image/bundle association, actual operator configs,
signed inspection/catalog/execution/revocation/trust inputs, currentCore/policy, scoped worker
credentials, real UDS peer/socket/host observations and approved containment/activation route.
The selected DSM must have explicit test-use authorization and immutable byte/profile evidence.
Do not manufacture these inputs to make a green scenario or execute public TIFFs on the ordinary
host/generated-only test launcher. Missing inputs remain blockers after source tooling is complete.

Observe the actual worker request and actualInspector/container lane, exact DSM download/hash,
bound response and authenticated Core acceptance/read-after-restart or replay. Record failed
paths separately; a service health page, success toast, archive proof or unit fixture is not this
acceptance. The subsequent two-epoch analysis and API/MCP result/evidence queries are a later
authorized product step, not automatic scope expansion from this bundle spec.
