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

## Current status — 2026-10-04 approved development follow-up

**Subsequent Human continuation:** the Human requested all follow-up development improvements,
selected **Grype original JSON direct support** rather than a scanner envelope producer, and
approved the detailed two-image Python/native-consumer design and both written specs:
[Python repair](../specs/2026-10-03-external-runtime-python-repair-design.md)
and [native Grype evidence](../specs/2026-10-03-grype-native-evidence-design.md).
The Human approved [image repair](2026-10-03-external-runtime-python-repair.md)
and [native consumer](2026-10-03-grype-native-evidence.md) plans for inline implementation. They preserve local implementation,
independent verification and the actual external approval boundaries.
The earlier B2 producer recommendation below is historical investigation, not the selected
implementation route. Implemented native parsing preserves raw reports and extends the strict runtime
consumer with versioned native-profile verification; no fabricated `scanner` fields. Application
bundle tooling remains a separate design/verification unit. These design decisions supply no
signing/credential/registry/release-security/host authority.

Static installation is complete. New actual images from clean source16084bf contain fixedPython3.12.15
and unchanged prior OS repairs. Same-tool/DB scans report179matches, Critical0/High59 per image.
The confirmed Python tarfile advisory is absent and actual bytes match upstreamfixedversion.
Security disposition and release-evidence
acceptance remain incomplete. Applications have not been activated; actual containment, public
TIFF processing and quantitative-result verification have not run. The final Result section below
is the **earlier static-installation stage**, not the current image/scanner status.

Native Grype parser/strict consumer source6678e3b/c34fc8a has byte/config equality tests, but
actual Docker29 `.Id` is an OCIindex whereas Grype identifies the config. The approved design's
assumption of direct equality is false on this target. Actual reports reject the hostindex;
no ID reinterpretation or invented hostbinding was applied. A separately reviewed verified
index/platform/config-link contract is required for full native release binding here. Image repair
and standalone consumer verification are distinct from this unresolved integration blocker.
See [actual evidence](../../ops/SPATIAL_DATA_LOCAL_VERIFICATION.md#python-repair-and-native-scanner-consumer--2026-10-04).

Independent review and one Important repair pass are complete. Actual-main full Python at
e3c3d27 with command-localumask022:8239passed/121skipped/98warnings/zero failures772.62s.
Intermediate0002/077 fixture and SDKdirectory failures remain disclosed in the local evidence;
no production/SDK gate was relaxed. Python repair and narrow native parsing are locally integrated,
not a full runtime release. The Human selected verified-linkv2 design;
[written spec](../specs/2026-10-04-external-runtime-oci-scanner-link-design.md) was approved by
the Human's “continue” after its written-review handoff. The
[implementation plan](2026-10-04-external-runtime-oci-scanner-link.md) awaits review; this is not
an implemented schema/tool or permission to generate real release/signing inputs.

The preceding review follow-up changed documentation only. Its repository baseline was
`dbbee981a73a17a5f55aa3db405f7235d312445d`; its then-inspected image source was
`81f69883b59f53a2a015faea8fd4caa6d8cb34e3`, and installed templates remain bound to
`928436f68ea271eaf4045112ab2a03bb590bbbeb`. That review used retained preparation
observations, not a fresh host/daemon revalidation. No code/image/host change,
new tool installation, key/credential provisioning, registry publication or activation is approved
by that documentation amendment. Later approved development is recorded above; Task3's B1–B8
review map remains historical context, not proof that its inputs or deployment gates exist.

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

### Task 3 follow-up: Resolve actual blockers through existing contracts

**Scope:** identify and document the real route first; execute a repair, evidence producer or
release operation only within its separately confirmed authority. This is not authorization to
manufacture missing inputs. Roles below are contract responsibilities, **not assigned people**;
the Human must identify the actual release/security reviewer, publisher, signing authority, Core
operator and evidence custodian. No production signing/issuance pipeline was established by this
read-only investigation.

There are two distinct gates, not a circular install condition: **offline release/security/input
review** precedes protected bundle installation; **live lifecycle verification** follows actual
daemon/socket/ACL preparation and consumes fresh host proof. T3-B is a decision-gated work outline,
not a code-ready implementation plan or approval; missing producer/bundle designs need the bounded
implementation packet before implementation. T3-C is conditional on genuine input acceptance.

**Contract/code anchors:**
- Release aggregation: `tools/build_release_evidence.py`, `docs/ops/RELEASE_EVIDENCE.md`.
- Host consumption: `deploy/bin/external-runtime-stage.sh` functions
  `require_release_evidence`, `verify_artifact_binding`, `verify_product_image_binding`;
  `contracts/schemas/external-runtime-host-binding.v1.json`.
- Application entrypoints: `[project.scripts]` in `services/processing-controller/pyproject.toml`;
  assembly/startup requirements in `services/processing-controller/README.md` and
  `deploy/external-runtime/README.md`. Console scripts exist; an installed protected bundle does not.
- Signed inspector contract: `contracts/schemas/inspector-execution-manifest.v1.json` plus
  `packages/event-contracts/src/ksi_event_contracts/inspector_execution_manifest.py`.
- Runtime artifact consumers under `services/processing-controller/src/ksi_processing_controller/`:
  `external_inspector_operator_config.py`, `external_measurement_operator_config.py`,
  `external_inspector_catalog.py`, `external_inspector_docker.py`,
  `external_inspector_host_proof.py`, `external_validation_worker_config.py`.
  Config versions respectively remain `external-inspector-operator-config.v1`,
  `external-measurement-operator-config.v2`, and `external-validation-worker-config.v1`.
- Mounted Core authority: `services/core/src/ksi_core/domains/external/authority/` modules
  `external_authority_preflight.py`, `provider_loading.py`, `external_result_workflow_config.py`.

| Blocker / current state | Required output and exact destination/contract | Generator / supplier and approval | Completion evidence |
| --- | --- | --- | --- |
| B1 Security disposition: scans exist, residual findings not accepted | Image-bound finding decisions under `docs/ops/RELEASE_EVIDENCE.md` and the security gate in `docs/ops/EXTERNAL_VM_DEPENDENCY_BASELINE.md`; Python candidate below is separate from Debian `wont-fix`/`not-fixed` | Security/release reviewer decides applicability and disposition; engineering repairs only after Python/base scope approval | Official advisory, image/package binding, reachability limitations and authorized disposition; repaired image rescan when changed. No suppression or inferred waiver |
| B2 Scanner evidence/tool authenticity: genuine raw outputs and retained bundles exist; accepted producer/signature verification absent | Runtime scanner JSON must contain nonempty `scanner.name` and `scanner.schemaVersion`, with exact bytes/hash/type bound in host `runtimeProducts[].scanner`; original Grype report remains unchanged | Release tooling owner locates an accepted producer, otherwise proposes a separately approved producer contract/implementation; reviewer approves tool verification method. Additional verifier installation is not currently authorized | Producer provenance to actual tool/version/DB/image/raw output and all findings, successful independent authenticity verification, then existing strict artifact consumer accepts the genuine output |
| B3 Release identity: two local image/SBOM/scan pairs exist, canonical release/host record incomplete | Example paths `/etc/ksi-external-runtime/release-evidence.json` and `/etc/ksi-external-runtime/host-binding.json` from `deploy/.env.external-reconstruction.example`; canonical Core/Dashboard product evidence plus separate inspector/measurement `runtimeProducts` | Release operator uses existing aggregator; publisher supplies genuine registry promotion/digests only with explicit target authorization (not granted). Host observations are supplied by the deployment operator, not invented by the aggregator | Clean exact source, canonical record hash, actual Docker IDs/RepoDigests and artifact hashes/lengths match; all canonical external pins retained, three candidate dependency observations match. Current local OCI digests are not registry publication |
| B4 Application bundle/protected configuration: absent at preparation observation | Executables `/usr/local/lib/ksi-external-runtime/bin/ksi-external-inspector-daemon`, `ksi-external-measurement-daemon`, `ksi-external-validation-worker`; configs `/etc/ksi-external-runtime/external-inspector-daemon-config.json`, `external-measurement-daemon-config.json`, `external-validation-worker-config.json`; separate `validator-core.token` there | Processing release owner packages the existing console scripts/dependencies from the selected clean source; deployment operator installs reviewed immutable bytes after offline release/security review, before live lifecycle verification. Credential issuer supplies the token separately; no token creation authority is delegated | Source/dependency/file hashes and protected ancestry, exact runtime-identity readability and ownership/modes, config loader and startup-artifact validation. Bootstrap installs templates, **not** this bundle; a bundle packaging/install producer still needs a bounded plan |
| B5 Signed execution/OCI-pair/revocation/trust: not supplied/verified | Manifest/revocation files at each protected config's `production.catalog.manifestPath`/`revocationPath`, digest pin `expectedRevocationSha256`; trusted public keys at `production.trustRoot.publicKeys`; offline proof at `production.ociPairs.proofPath` with `expectedSha256` | Actual authorized signer supplies signed profiles, trust and current revocation state; release operator derives OCI proof from preserved raw manifest/config bytes. Signer identity and issuance route must be supplied, never a generated test key | Inspector `validate_operator_startup_artifacts` / measurement `validate_measurement_operator_startup_artifacts` verify actual signature/revocation/profile/pair; Engine resolves the same real image. Config-selected artifact paths are **not yet assigned**; do not invent filenames or an empty revocation grant |
| B6 Core policy/worker authority: operator roots and genuine inputs absent | One existing `/etc/ksi-external-runtime/operator` or `/var/lib/ksi-external-runtime/operator`, containing `workflow.json`, `provider.json`, `secrets/`, `signing/`; mounted `/run/ksi-operator`; fixed authority journal `/var/lib/ksi/data/external-quantitative-authority.jsonl`. Worker HTTPS origin, UUID, endpoints/profile and separate private token use existing worker config contract | Core/catalog/key authority supplies genuinely authorized current records and scoped worker identity; operator places protected files. No inferred organization, catalog approval, resource limits or credentials | UID10001 validate-only plus detached `CONFIG_VALIDATED`, then actual Core attachment/currentness `PROVIDER_CONFIGURED`; request-level admission/lease remain separate. Neither readiness status grants data use or quantitative eligibility |
| B7 Host containment: metadata/negative blocking only, not functional proof | Existing user units/slices, `/run/ksi-external-runtime/launcher/inspection.sock` and `measurement.sock`, fresh live helper peer proof, actual procfs/UID-map/cgroup/FD/container facts | Root/deployment operator performs only the separately gated application/socket/ACL sequence; runtime obtains facts from the host. No bootstrap replay, staging mutation or saved positive-proof substitution | Startup host proof, live `OBSERVED_SERVER_PEER_CREDENTIAL` for both lanes/untrusted denial, actual child security/resource checks and cleanup evidence under the existing sandbox contract; normal-input success alone is insufficient |
| B8 Evidence retention: local originals exist, release archive/custodian undecided | Existing release contract's byte-bound originals, not a new envelope or Git binary store. `/tmp/opencode/…` and ignored `.opencode/artifacts/…` remain local preparation locations | Human names custodian and approved durable private destination/retention; release operator makes verified additive copies. No external upload or deletion authorization follows | Restorable original tools/checksums/bundles, DB, source context, image archives/blobs, raw SBOM/scans and reports retain hashes/provenance; canonical release and host records bind the chosen deployment combination |

#### T3-A — Read-only investigation result (completed)

- [x] Revalidate clean task/main baseline and inspect existing release, host and configuration consumers.
- [x] Check official Python advisory against retained image bytes without running either runtime.
- [x] Distinguish evidence producer absence, registry identity prerequisites, protected bundle absence,
  authority-supplier unknowns and actual host verification; preserve historical results.

**Python finding:** [PSF security announcement](https://mail.python.org/archives/list/security-announce@python.org/message/EFJWGAZJA56AKSBR2WHMHQZO7RRLZPRH)
and the [PSF CNA record](https://cveawg.mitre.org/api/cve/CVE-2026-82049) confirm
`CVE-2026-82049`: crafted TAR hard-link-to-symlink interactions affect `tarfile` data/tar extraction
filters. The CNA record updated 2026-10-02 lists `3.12.0 <= version < 3.12.15` as affected;
[Python 3.12.15](https://www.python.org/downloads/release/python-31215/) is the reported fixed
3.12 release, **not an approved replacement image pin**. Both preserved repaired archives were
rehashed against their receipts, and their `usr/local/lib/python3.12/tarfile.py` bytes equal
upstream `v3.12.14/Lib/tarfile.py` (SHA256
`41a9f1930e5285455b4b0db2b9394247cce312c3fa1ef586a58e66c0100668d5`). This establishes
affected component/version presence, not actual exploitation. Searches of processing-controller
and reusable package Python code found no direct `tarfile`, `extractall` or `shutil.unpack_archive`
calls; that is **not** a complete transitive-dependency/dynamic-call reachability assessment or waiver.
Private CNA/upstream snapshots and per-image bindings:
`.opencode/artifacts/contained-runtime-preparation-20261003/task3-analysis/python-applicability.json`.
CNA snapshot SHA256 `a5394b33bdf54db1c338a32114672dec3771c77ecc0cdac116f38623cc4729d6`.

**Scanner route:** the aggregator accepts a nonempty JSON object and records its bytes; it does
not produce a scanner report, verify a tool signature or decide findings. The runtime host gate
additionally requires the two scanner identity fields. Focused searches in `tools/`, `scripts/`,
`.github/`, relevant ops docs and contract tests found **no accepted production producer** for
that runtime envelope. Test fixtures with `scanner.name="test"` are not production evidence.
The baseline's Syft/Trivy command examples are scanner invocation guidance, not proof that their
raw outputs satisfy this stricter contract. Replacing Grype or adding fields by hand is not a fix.
An explicit, reviewed producer/provenance contract is required if an existing accepted producer
cannot be supplied; its format/schema/version and ownership must be agreed before implementation.
Retained Sigstore bundles/checksum equality still do not constitute signature verification.

**Security criterion:** release evidence explicitly delegates security acceptance to review;
the dependency baseline blocks unapproved High findings for external customer data. No inspected
consumer implements a universal `High == 0` threshold. Do not impose that threshold, classify all
residuals as Debian-unfixed, or infer approval from a parser accepting JSON. The reviewer must
identify the applicable local-public-test/customer-release decision and authorized disposition;
until supplied, activation remains blocked.

#### T3-B — Bounded remediation and release inputs (not executed)

- [ ] B1: obtain the Python/base applicability/repair decision. If approved, change only the agreed
  base/Python pins, preserve OS repairs/lockfile/entrypoints/users/context boundaries, and verify
  exact replacement image versions, regressions and same-tool/same-DB scan comparison. New Python
  or parser/image identities require newly authorized profiles; old signatures cannot be relabeled.
- [ ] B2: locate a genuinely accepted scanner producer or approve its bounded contract/implementation.
  A new producer must test rejection of substituted image/DB/raw bytes and malformed/unknown schema,
  preserve every finding and raw output, then pass existing strict host artifact checks. Separately
  verify official tool signatures using an approved method/identity policy; retain actual results.
- [ ] B3/B8: select the release source and deployment combination, actual publisher/target, and durable
  private archive/custodian. The lifecycle requires canonical/host source SHA equal to clean `HEAD`;
  do not submit the old image-source SHA as a fabricated current release. Reconcile any docs-only
  source difference explicitly through the release review. Generate canonical evidence with the
  existing aggregator only after genuine Core/Dashboard inputs exist; produce separate observed
  runtime host binding. Registry effects need their own authorization. Preserve all prior evidence.
- [ ] B4: approve a source-frozen application-bundle packaging/install packet using the existing
  scripts and locked dependencies; name its immutable bundle inventory/hash and rollback before
  installation. Do not install a checkout `.venv` or let editable source/ambient paths supply code.
- [ ] B5/B6: obtain the actual signer/Core/credential suppliers and authorized immutable materials;
  choose protected config-referenced artifact paths using those inputs. Validate under the real
  runtime identities. Neither a test issuer nor a manually synthesized catalog is an alternative.

Relevant prepared-dependency local contract checks (source verification only, not release/host proof):

```bash
UV_NO_SYNC=1 UV_OFFLINE=1 UV_PYTHON_DOWNLOADS=never .venv/bin/python -m pytest -q \
  tests/contract/test_release_evidence.py \
  tests/contract/test_runtime_image_pins.py \
  tests/contract/test_external_runtime_deployment_contract.py \
  tests/contract/test_external_inspector_operator_artifacts.py \
  tests/contract/test_external_inspector_catalog.py \
  tests/contract/test_external_measurement_operator_config.py \
  tests/contract/test_external_validation_worker_config.py
```

Expected: zero failures; report actual counts/skips. A future implementation must name exact owned
files, tests and RED/GREEN assertions in its bounded packet before code changes. Missing producer,
registry, signer or archive decisions are explicit dependencies, not details an executor may guess.

Follow-up verification on `dbbee981a73a17a5f55aa3db405f7235d312445d` plus these documentation-only
changes: the exact command above returned **146 passed in 6.88s**; private log
`.opencode/artifacts/contained-runtime-preparation-20261003/task3-analysis/contract-tests.log`.
This is not a new image scan, live host check, runtime activation or full-suite result.

#### T3-C — Gated activation and one admitted inspection (not executed)

- [ ] After B1–B6/B8 inputs are genuinely accepted, refresh host facts without bootstrap replay;
  install only the reviewed bundle/configs under the existing installation authorization. Follow
  the README's user socket/service and root ACL sequence, proving both actual daemon startups and
  fresh peer/denial results. Saved helper JSON/metadata or old PID values are not admission evidence.
- [ ] Resolve selected OCI **platform manifest** and config from raw verified bytes; reconcile actual
  Engine identity through `FileLocalOciPairResolver` and runtime checks. An index or Syft synthetic
  Docker manifest is not interchangeable with the signed platform manifest/config pair.
- [ ] Obtain the required genuine candidate/Core release and deployment authorization before
  lifecycle `verify/start`: `verify` itself runs disposable validation containers and is not a
  read-only file check. Follow `deploy/external-runtime/README.md`; leave `ksi-phase2-staging` alone.
- [ ] For the first raster only after actual existing host/child enforcement checks pass, have Core
  authorize one sealed public input under the real tenant/policy and scoped worker identity. Use
  the existing inspection request → worker lease/input → `inspection.sock` → fixed inspector child
  → Core result route. Do not launch a host parser/test launcher or fake the request/lease.
- [ ] Retain request/input digest, current policy/profile/manifest binding, observed child controls
  and resource/cleanup results, exact returned report digest and Core journal/reload confirmation.
  Acceptance for this step is one real admitted inspection with a durably retrievable result.
  It is not full hostile-input containment, measurement accuracy, Terra/customer/field acceptance
  or a Spatial Data execution authorization. Keep unknown vertical datum/accuracy and quantitative
  claims blocked. Native-window preparation/pixel-mask comparison require their own verified route.

Dependencies: T3-A informs T3-B; release/artifact/authority acceptance in T3-B precedes T3-C.
Security review and producer discovery may proceed independently; neither unlocks activation alone.
Stop at an unresolved material supplier/approval, record it, and continue independent authorized
preparation only. Rollback preserves originals/evidence and predecessors; no automatic key rotation,
policy alteration, image pruning, broad reset or staging shutdown is permitted.

## Evidence and state

Private task ledger: `.opencode/artifacts/contained-runtime-preparation-20261003/progress.md`.
Source baseline: `928436f68ea271eaf4045112ab2a03bb590bbbeb` on the existing isolated
`integration/readiness-20261002` worktree; local-main target initially equal and clean.
The current EXT-VAL product slice and human acceptance state are unchanged.

## Result — static-installation stage only (before image/scanner continuation)

Historical result for source `928436f68ea271eaf4045112ab2a03bb590bbbeb`; see Current status and
Observed security-repair evidence above for the subsequent builds/scans and remaining blockers.

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
  At that static-installation stage no credential/key provisioning, scanner installation, synthetic
  authority or TIFF decode ran. Later approved task-private scanner installation/builds/scans are
  recorded above; credential/key provisioning, synthetic authority and public TIFF decode remain unrun.

Minor audit limitations of the private one-shot installer remain recorded in its task ledger:
terse assertion diagnostics, partial predecessor metadata, named-tree hash rather than live-HEAD
binding, and one parent stat following an already verified root-only chain. None is represented as
application release evidence; the established application activation gates remain mandatory.
