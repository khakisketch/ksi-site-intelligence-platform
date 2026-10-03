# Contained runtime preparation implementation plan

> For agentic workers: use `executing-plans` for this bounded operator task.

**Goal:** Prepare the existing dedicated rootless inspector route without bypassing
release, signed execution, policy, or containment gates.

**Architecture:** Reuse `deploy/external-runtime/` and the processing-controller
daemon/configuration loaders. Static preparation is distinct from application activation.
Core remains the policy and tenant authority; no alternative public TIFF parser is introduced.

**Tech stack:** existing Bash/Python, systemd user units, rootless Docker, cgroup v2.

**Spec:** `deploy/external-runtime/README.md`, existing inspector sandbox amendment selected
by the current EXT-VAL ledger, and ADR-KSI-036. The Human on 2026-10-03 selected dedicated
runtime installation/configuration/start preparation. That supersedes the older no-host-work
restriction only for this bounded task; it does not supply missing release/signing authority.

## Global constraints and task record

- Requirements: EXT-VAL-01/05/06/08, REQ-OPS-101/102, REQ-SEC-101.
- Owner: deployment templates and processing-controller launcher assembly.
- Acceptance: source-bound prepared static bundle; exact observed prerequisites; no application
  activation unless actual release, signed configuration and host enforcement evidence pass.
- Contracts affected: none. Reuse existing configuration/execution/host-binding contracts.
- Reference assets/adoption: existing preflight, bootstrap, socket helper, daemon loaders and tests;
  reuse only KSI-owned code. No reference-submodule edits or imports.
- Files: this plan, private task evidence/checkpoint, a create-once root-owned template release,
  and the exact installed dormant socket helper if its predecessor is identified and preserved.
- Invariants: INV-054 source/image/SBOM/scanner binding remains mandatory; INV-055 Core admission
  remains authoritative; INV-051/053 external bytes do not become managed/quantitative authority;
  INV-060 no customer/foreign-tenant data or credential access.
- Tests: existing deployment, inspector host proof, listener identity, catalog, operator artifacts,
  measurement configuration and release-evidence tests. Prepared dependencies only, offline/no sync.
- HIL/real-device assumptions: none; actual containment and customer/field acceptance remain distinct.
- License/data: acquired CC BY4 public originals remain private/ignored and unopened by raster code.
- No scanner/tool installation, credential/key generation, customer data, public exposure, push,
  staging restart, rootful daemon operation, bootstrap replay, or test-authority promotion.
- Rollback: preserve predecessor helper bytes/hash/mode before replacement; retain both template
  releases. No service/ACL activation, account/subordinate-map changes, or automatic rollback execution.

## Approved continuation — local images and OS security repair

The Human subsequently approved task-private Syft/Grype/DB downloads and source-frozen local
rootless image builds/SBOM/scans, then explicitly selected **image security repair** after both
baseline images reported 253 matches (7 Critical, 87 High). These approvals supersede the earlier
no-scanner-install restriction only for this bounded preparation. They do not authorize host OS,
staging, signing-key/policy changes, registry push, application activation, or public TIFF decoding.

### Required implementation packet

- Requirement IDs: REQ-OPS-101, REQ-SEC-101; EXT-VAL-05/08 preparation, not acceptance.
- Owner module: root `Dockerfile.external-inspector` / `Dockerfile.external-measurement`.
- Acceptance criteria: preserved baseline; actual source-bound rebuilt images and SBOM show the
  selected corrected OS versions; same-tool/same-DB scans no longer match the targeted fixed
  Critical/High OS findings. Report every remaining finding; do not equate improvement with release.
- Contracts affected: none; strict release/scanner/host/execution admission remains unchanged.
- Reference assets: existing Dockerfiles, locked workspace dependencies and runtime pin tests;
  official Debian security tracker and ARM64 snapshot package indices.
- Adoption decisions: PORT official OS fixes into both final stages; unchanged base-image/uv pins,
  Python lockfile, distinct non-root users, fixed commands and Docker context allowlists.
- Files to change: the two Dockerfiles and this plan; later local-verification outcome documentation.
- Tests: actual old-image SBOM/scanner RED then rebuilt-image GREEN, existing release/pin/deployment
  contract tests, same-DB before/after scan and archive/source/config/layer identity verification.
- HIL or real-device assumptions: none; no hostile raster/service execution or field acceptance.
- License/data implications: retain scanner Apache-2.0 notices/provenance; public package metadata
  download only, no source/customer/raster uploads. Sigstore bundle retained but not verified.
- Rollback: new tags/build directories only; preserve old images and scan reports. Revert task-owned
  Dockerfile commit if needed, never reset user work or prune the daemon.
- Invariants: INV-054 enforced through unchanged exact base/uv pins plus clean-source/archive/SBOM/
  scan binding; INV-055/060 and INV-051/053 preserved by no Core/policy/data/activation changes.

### Repair checklist

- [x] S1 Observe actual baseline RED for selected OS findings and corrected-version requirements.
- [x] S2 Pin 20261003T000000Z in both final stages and explicitly upgrade only affected OS packages;
  run existing contracts, commit source and freeze exact clean Git-tree context.
- [x] S3 Rebuild/export under task-specific rootless context, generate SBOM/scans using same DB,
  verify real package versions and targeted finding removal; preserve all residual matches.
- [x] S4 Independent read-only whole-change review; record findings/limitations, verified local
  integration and activation blockers. Keep product slice unchanged.

Hypothesis: the 20260911 snapshot and selectively upgraded expat/OpenSSL leave vulnerable base OS
packages in both final stages. Installing official corrected versions from the later fixed snapshot
should remove their fixed Critical/High matches without changing product code or Python dependencies.
The earlier metadata probe is unsigned local evidence; actual APT builds must verify repository
signatures and package integrity normally. No `trusted=yes`, allow-unauthenticated or scanner ignores.

Pre-flight interfaces: clean Git tree -> local build revision/config/OCI layers -> archive -> Syft
source -> unchanged Grype DB -> real scan findings. Docker-save/Syft manifest transformations and
local repository digests are not registry publication; preserve each identity separately. Raw Grype
JSON lacks the host gate's `scanner.name/schemaVersion` envelope; no invented envelope or host proof.

### Observed security-repair evidence

- Clean repair source: `81f69883b59f53a2a015faea8fd4caa6d8cb34e3`; its build-context archive SHA-256
  is `bc1dde84d084365f4e36f06075f5e3d7991b455ce7734070a4755e744185b0d1`.
  Of 592 archived files only the two Dockerfiles differ from baseline `17a9e59`.
- Both ARM64 builds succeeded on the existing dedicated rootless daemon using a fresh explicit
  task context. APT completed without signature error or bypass flags and installed the corrected
  packages; quiet build logs do not retain verbose InRelease/signature-verification lines.
  distinct non-root identities and fixed entrypoints remain unchanged. No application was run.
- Syft 1.54.0 / Grype 0.120.0, DB v6.1.10 built `2026-10-03T06:31:58Z`; actual DB SHA-256 before
  and after repaired scans: `053403d879610c96cccd011456cd053a3311131f084557132492cf076778e224`.
  Repeated baseline scans reproduced their exact matches on the same retained DB/provider metadata.
- Per image: 253 -> 185 matches, Critical 7 -> 0, High 87 -> 60, Medium 88 -> 67,
  Low 25 -> 12, Negligible 46 unchanged; distinct vulnerability IDs 133 -> 93.
- Actual SBOM versions for all nine targeted packages corrected; non-Debian package identities
  unchanged and no Debian packages removed. Four real evidence tests observed RED4 -> GREEN4.
  Existing contracts 177 passed; broader owner regressions 584 passed with two generated-fixture
  `NotGeoreferencedWarning`s. This is not a new full-suite or real raster/containment acceptance run.
- Every referenced OCI blob in four baseline/repaired archives was hashed; selected ARM64 manifest,
  raw config and rootfs layers bind the actual SBOM and scanner image identity. OCI index, platform
  manifest, config ID and Syft's synthetic Docker manifest are separate recorded identities.
- Remaining High60 includes Debian `wont-fix`/`not-fixed` records and a Python 3.12.14 binary match
  with a reported fix. None is suppressed or accepted; Python/base-image changes are outside this
  approved OS-pin repair. Official applicability/severity/release review remains necessary.
- Private reports/tests/build logs are preserved in `.opencode/artifacts/contained-runtime-preparation-20261003/`
  under `image-build-17a9e59` and `image-build-81f6988`. Tool/DB/image archives remain in the approved
  task-private `/tmp/opencode/ksi-runtime-verification-20261003-17a9e59/` and dedicated build homes.
  These are local evidence locations, not Git-delivered binaries or durable external release archives.
- Older `b2c714e` and baseline local image tags retain their exact original IDs. Docker PID3090 is
  unchanged; both application sockets disabled and services inactive; no running containers.
  Release/scanner envelope, protected application bundles, signed execution/OCI-pair/trust inputs,
  actual containment and Core policy/worker authority remain unsupplied/unverified.

### Independent review and disposition

Read-only reviewer `ses_efe89d21affe9Ch5pQ85vDUd8L` checked the committed source range, pending
outcome docs and actual private reports/logs. No blocking code defect was found in the narrow
OS repair. Its two Important items are **remaining activation/release risks**, not authorization
to expand this repair: fixed-state High Python `CVE-2026-82049` and incompatible raw scanner
envelope. Primary separately confirmed both against actual reports. Source integration is separate
from release/data-plane integration: the latter remains blocked, and no `verify/start` was run.

The documentation now says exactly what the quiet APT log proves (completed without signature
error/bypass flags), rather than claiming independently logged signature verification. No image
rebuild is required for this evidence-wording correction. Review minors retained: old-tag
preservation and new-image identity appear in separate cross-referenced evidence files; some
historical source references use short hashes while full identities are available in the receipts.

Rulings on the review's declined-to-judge list:

1. Residual exploitability and `wont-fix`/`not-fixed` correctness remain unverified, not waived;
   cost if wrong: release stays blocked pending official/contextual security review.
2. Snapshot/finding removal is verified; independent complete CVE-to-version tracker review is
   not claimed for all pins. Cost if wrong: corrected-version evidence must be re-evaluated before release.
3. Rootless metadata is not functional containment. Cost if wrong: no public raster execution is admitted.
4. Retained Sigstore bundles are not verified signatures. Cost if wrong: tool authenticity needs
   independent verification before any security release acceptance.
5. Release/host/execution/customer acceptance remains absent. Cost if wrong: no activation or
   quantitative/customer claim follows from local source integration or the scanner result.

The verified source commit `81f69883b59f53a2a015faea8fd4caa6d8cb34e3` was locally fast-forwarded
into clean `main` after target/source/index checks. On actual main, the broader owner regression
command passed **584 tests, 2 generated-fixture warnings in 24.69s**; log
`image-build-81f6988/main-owner-regressions.log` is retained in the private task evidence.
The subsequent outcome-doc changes alter no image/build inputs. Existing task-owned worktree and
private evidence are retained for this still-blocked runtime task. No push or cleanup occurred.

## Review focus

- Installed template drift: do not overwrite an unknown bundle; create a new immutable release path.
- Older helper protocol: identify the predecessor in Git; back it up before replacing only that file.
- Source mismatch or substitution: pin clean HEAD and every copied file hash, reject symlinked or
  writable target ancestry, recheck after copy and before replacement.
- Static installation confused with activation: no enable/start/reload/ACL operation in this task's
  static preparation; dormant services must remain dormant.
- Absent release/authority inputs: do not generate placeholder manifests, trust roots, policy values,
  credentials or synthetic inspection reports to unlock public data.

## Tasks

### Task 1: Observe the existing dedicated runtime

- [x] Revalidate clean task branch and local-main integration target.
- [x] Run existing root preflight into a fresh private ledger; inspect fixed runtime metadata only.
- [x] Read dedicated rootless Engine metadata, unit state, template/helper hashes, not credentials.
- [x] Record image/source uncertainty and distinguish unreadable paths from absent paths.

Expected: observations, not application readiness or permission to parse data.

### Task 2: Prepare current source-bound static resources

- [x] Run relevant existing contract tests; require zero failures before installation.
- [x] Prepare exactly the bootstrap's twelve required template files and canonical checksum list
  from clean `928436f68ea271eaf4045112ab2a03bb590bbbeb`; independent read-only review.
- [x] Create a new root-owned release under `/usr/share/ksi-external-runtime/releases/<source SHA>/`
  without changing the older template tree or user units.
- [x] Preserve the known predecessor helper in a create-once root-private backup; replace only
  `/usr/local/lib/ksi-external-runtime/bin/ksi-external-runtime-socket-acl` with reviewed exact bytes.
- [x] Verify ownership/mode, required file hashes and unchanged dormant unit/daemon state.

Expected: current static prerequisite installed; no functional contained runtime claim.

### Task 3: Respect application activation gates

- [x] Check actual application bundle and protected configuration availability (absent).
- [ ] Require exact image/source/SBOM/scanner and signed execution/OCI-pair/revocation evidence.
- [ ] Install/start daemons only if those inputs genuinely exist and the established host checks pass.
  Otherwise record this task as blocked, with exact missing inputs; no fallback or placeholder.
- [x] Keep public inspection/preparation/independent pixel-mask comparison explicitly unrun until
  its own approved and verified execution route is available.

## Evidence and state

Private task ledger: `.opencode/artifacts/contained-runtime-preparation-20261003/progress.md`.
Source baseline: `928436f68ea271eaf4045112ab2a03bb590bbbeb` on the existing isolated
`integration/readiness-20261002` worktree; local-main target initially equal and clean.
The current EXT-VAL product slice and human acceptance state are unchanged.

## Result — static preparation verified; application activation blocked

- Existing relevant tests:159passed7.67s. Four operator admission regressions observed RED,
  then operator plus same suite:163passed7.60s; prepared dependencies, offline/no sync.
- Independent review verified source/predecessor/template identity and bounded scope. Important
  operator findings were fixed before root application: root-owned reviewed script snapshot,
  shared bootstrap lock, inactive+disabled/static admission and actual account UID resolution.
- Actual root copy/hash/mode, all twelve installed files, predecessor backup and unchanged old
  template/user-unit state verified. Existing rootless daemon unchanged; no application activated.
- Root receipt: `/var/lib/ksi-external-runtime-preflight/static-install-20261003-928436f.json`;
  SHA-256 `10d97bc00cd94add128b45e9da6330d646cefe9846f88d70e0d859d5623a4259`.
- Backup: `/var/lib/ksi-external-runtime-preflight/helper-backup-20261003-928436f/`.
- Installed static checksum-list SHA-256:
  `5d1e95e25ac5eeaa6a4f419a1bee7884ab6483e0a49d59857ba73edcdd03bb35`.
  The list is reordered, content-equivalent to the source list, not its original file hash.
- Installed helper's actual negative proof command returned1/no positive JSON with absent
  application sockets. This proves blocking, not functional parsing or host containment.
- Task3 remains blocked: configured application binaries/configs absent; current immutable
  image/SBOM/scanner/host and signed execution/OCI-pair/revocation/trust inputs not supplied.
  No credential/key provisioning, scanner installation, synthetic authority or TIFF decode ran.

Minor audit limitations of the private one-shot installer remain recorded in its task ledger:
terse assertion diagnostics, partial predecessor metadata, named-tree hash rather than live-HEAD
binding, and one parent stat following an already verified root-only chain. None is represented as
application release evidence; the established application activation gates remain mandatory.
