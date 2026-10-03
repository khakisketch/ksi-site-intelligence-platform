# Spatial Data V1 — local verification and remaining gates

Scope: rectangular **native-grid DSM/RGB/RGBA GeoTIFF derivatives**, not analysis,
reprojection, resampling, polygon masks, public URLs, Range, vendor compatibility,
survey accuracy or customer acceptance. Sources remain customer-owned external
reconstruction results. A crop cannot become managed raw/source authority.

## Evidence levels

| Evidence | What it establishes | What it does not establish |
| --- | --- | --- |
| Generated GeoTIFF inspection | Actual TIFF parser and raster measurement on owned small fixtures | Safe decode of arbitrary customer/public bytes on the current host |
| Mounted Core → worker → consumer | Durable source/grant/job binding, real loopback GET/PUT, separate framed child/native preparation, immutable observation, guarded download | A deployed provider, authenticated remote client topology or production namespace/image isolation |
| Independent generated consumer comparison | Original cell slice, affine/bounds/CRS, source/output SHA-256, NoData/masks and valid count | Checkpoint accuracy, settlement suitability or producer compatibility |
| Replay/rights negatives | Same IDs/receipts/bytes after participant journal re-open, revoked bytes denied while completed history remains | Cross-process operational recovery, backups or disaster recovery |
| Public verifier preflight | Rejects missing/replaced original, missing inspection/policy or disconnected signed configuration/proof | A configuration file alone does not prove a live child's containment |

The generated-only launcher is confined to `tests/contract/spatial_data_http_fixture.py`.
It does not satisfy production kernel proof. The real parent/sandbox supervision and
fixed preparation primitive run; test authorities/configuration never enter default
composition. Core's transport bridge is mounted ASGI in-process; object GET/PUT uses
an actual owned loopback listener. This is local software evidence, not remote end-to-end
or field evidence.

## Existing authority and opt-in wiring

Operators must independently supply current data rights, inspected exact sealed
source revisions, full immutable resource policy, current runtime/activation and
storage/currentness participants. No public grant editor/provisioning API is added.
Public licensing is not a tenant grant or AI consent. `GENERAL_DATA_USE` and
`EXTERNAL_AI` are distinct; AI use additionally needs the applicable current Site consent.

Core local assembly accepts an explicit `SpatialDataLocalAssemblyConfig` with
`build_storage`, `build_currentness` and optional **existing absolute `0700`
`spool_root`**. Download wiring verifies exact connected jobs/storage/policy/audit.
Without that root, file operations return a typed unavailable response, not bytes.
Production composition/environment has no automatically enabled data lane.

The distinct `ksi-spatial-data-worker` consumes only the dedicated internal API.
It requires operator-prepared signed configuration, separate refreshed `0600` token,
an existing protected `0700` workspace, pinned launcher/proof and actual observed
namespace/mount/UID/privilege/rlimit checks before raster decoding. No package,
account, container, directory, credentials or host trust is provisioned here.

## HTTP-only consumer example

`examples/spatial-data/native_window_client.py` imports no Core stores or test helpers.
Its request uses only returned existing asset identity and observed CRS digest:

```json
{
  "assetRef": "<Core-returned ksa-v1 reference>",
  "requestedBounds": [102.1, 183.9, 108.1, 193.9],
  "observedCrsDigest": "<Core-returned sha256 digest>",
  "resolutionMode": "NATIVE",
  "purpose": "GENERAL_DATA_USE"
}
```

Coordinates above belong to generated tests only. Use your inspected source and
authorized requested/expanded rectangle; they are not public-site coordinates.

```text
.venv/bin/python examples/spatial-data/native_window_client.py \
  --core-url https://your-existing-core.example \
  --site-id YOUR_SITE --work-area-id YOUR_AREA \
  --token-file /absolute/private/client.token \
  --request-file /absolute/request.json --idempotency-key YOUR_STABLE_KEY \
  --output-dir /absolute/existing-parent/new-private-output \
  --max-file-bytes YOUR_EXPLICIT_LIMIT --deadline-seconds YOUR_EXPLICIT_LIMIT
```

This is not a dry run: POST issues a real job using existing rights. Retry the same
key/body to retrieve the original durable ID; changed bodies conflict. The parent of
the output directory must already exist and have a non-substitutable protected chain.
Token files must be regular, single-link, owner `0600`; symlink ancestors are refused.
No token is accepted in an environment variable or printed in errors.

The consumer rejects redirects/compressed data, bounded malformed/duplicate/nonfinite
JSON, receipt digest mismatch, changed length/output digest and unsafe file responses.
It keeps an incomplete private file unpublished, verifies complete bytes, then creates
the safe job-ID filename without overwriting any existing caller file. It does not
interpret TIFF bytes or assess accuracy. HTTP phase timeouts and chunk elapsed checks
are not hard arbitrary-I/O deadlines; stream failures must be retried as a fresh full
GET, never Range. Already delivered copies cannot be recalled by revocation.

## Public Floreat preflight / limited HTTP experiment

Cambridge Coastcare, Floreat-f4, declared capture 2022-08-24, via DataWA, CC BY 4.0:

| Kind | Original bytes | Full SHA-256 |
| --- | ---: | --- |
| DSM | 181498053 | `28eb3bea0e0ef58db7fa9f00b383bf7b50e6348103d80767a5ad362c0c37a7e2` |
| ORTHO | 346715111 | `b25bbfa56cd8cf90eca43bcb5539de4cbccfaa2744421c5f949ca1038b27cb66` |

- [DSM catalogue](https://catalogue.data.wa.gov.au/dataset/floreat-f4-raster-dsm-geotiff-aug-2022)
- [ORTHO catalogue](https://catalogue.data.wa.gov.au/dataset/floreat-f4-orthomosaic-aug-2022)
- [License](https://creativecommons.org/licenses/by/4.0/)

Retain attribution and crop modification notice. Publisher ORTHO resolution is **2 cm**;
previous affine probe observed **2.5 cm**. These are different facts, not a correction.
Vertical reference, independent accuracy and processor provenance remain unknown.
The previous hash/header acquisition is not a full accepted inspection.

`tools/verify_spatial_data_public_sample.py` accepts:

```text
.venv/bin/python tools/verify_spatial_data_public_sample.py \
  --manifest /absolute/public-sample-manifest.json \
  --core-url https://your-existing-core.example \
  --token-file /absolute/private/client.token \
  --policy-file /absolute/sealed-data-policy.json \
  --output-dir /absolute/existing-parent/new-private-output
```

Manifest shape (no embedded credential, arbitrary object endpoint or executable code):

```json
{
  "version": "spatial-data-public-sample.v1",
  "kind": "dsm",
  "sourceFile": "/absolute/pinned-original.tif",
  "sourceSnapshotFile": "/absolute/preinspected-source-snapshot.json",
  "workerConfigFile": "/absolute/private/existing-signed-worker-config.json",
  "requestedBounds": ["xmin", "ymin", "xmax", "ymax"],
  "idempotencyKey": "your-fixed-experiment-key"
}
```

Replace bounds with four finite numbers from the inspected source; placeholders
are intentionally invalid. `sourceSnapshotFile` is the owner-exported, fully sealed
`SpatialDataSourceV1` for a source already inspected through the pinned production
inspector path, **not** something this tool creates or admits. Its full measured outcome,
byte identity and source digest must validate. Core separately rechecks current
inspection/rights when the corresponding `assetRef` is requested. Worker config must
match Core/policy; existing signed activation, protected launcher/proof and expiry are
rechecked for consistency. A snapshot/configuration cannot grant authority or prove
live kernel containment; production worker checks still apply.

Missing originals or inspection/isolation material returns exit **2**, safe typed
`status: blocked`, and does not create output or start transport. It never replaces an
original with a small generated TIFF or directly decodes a public original in this process.
With existing prerequisites it can request the fixed rectangle and verify HTTP output
hash/size and exact source/policy/runtime/CRS/vertical/receipt binding, returning exit **0**
and `status: byte_receipt_verified`. That status is deliberately **not** full public
sample acceptance: `publicPixelMaskComparison` is NOT_RUN, worker peak RSS/CPU/workspace
is NOT_MEASURED, and host/customer acceptance is false. Full original/output independent
pixel/mask comparison and inspector/preparation resource measurements still require an
operator-approved isolated consumer and real host acceptance. Do not run this command
on a public sample until those prerequisites have been independently reviewed.

Observed here: original temporary files are absent, no positive production containment
material is available, and no public-file preparation/decoding or network experiment was
performed. Public acceptance remains open, not inferred from generated tests.

### 2026-10-03 — public original acquisition (latest availability evidence)

The Human approved downloading both official public development originals (528,213,164 bytes
total). They are now retained on this server under the canonical main checkout's ignored
`.dev-data/public-geotiff/floreat-f4-2022-08-24/`, not in temporary worktree storage or Git.
The DSM and ORTHO match both exact size/SHA-256 pins in the table above and pass the existing
`original_identity` checks. Originals are read-only `0400` within an owner-private `0700`
dataset directory. `ACQUISITION.json`, `catalogue-provenance.json`, `ATTRIBUTION.txt`,
`LICENSE_CAPTURE.json` and `IDENTITY_VERIFICATION.json` retain source/rights/identity evidence.
Cambridge Coastcare and catalogue author Meg Anklesaria are credited. Catalogue and official
CC BY4 deed/legal code were checked; the optional local plain-text license copy was unavailable
with HTTP403, so the official license link is retained, not an invented downloaded legal copy.

Acquisition follows only the catalogue's exact registered DataWA S3 object delegation. Expiring
download queries are not stored in dataset records. This is a separate public-source acquisition
probe, **not** permission to enable redirects in the product consumer or worker.

The old missing-original availability observation above is superseded, but none of its inspection
or host gates is closed. The existing preflight now stops at `INSPECTION_UNAVAILABLE` for each
acquired original before policy/token/HTTP transport. No TIFF/GDAL decoding, crop, resampling,
derived output, analysis or runtime provisioning was performed. Declared capture2022-08-24,
EPSG:7850 and Pix4D production are catalogue statements, not new measured facts. Vertical datum,
independent accuracy, DJI Terra compatibility, accepted inspection/containment and customer
two-cycle acceptance remain unverified. This single-epoch public pair does not supply `t0,t1,t2`.

### 2026-10-03 — contained runtime static preparation (not activation)

The Human separately authorized preparing the existing dedicated runtime, including installation
and eventual start only after its existing gates pass. Read-only operator preflight and dedicated
rootless Engine observations confirmed that the private user daemon is running with cgroup v2;
this is not parser containment acceptance. Existing inspector/measurement images have older
`b2c714e` tags, no source-revision label, and no verified current release binding.

The twelve existing deployment templates were prepared byte-exact from Git tree
`928436f68ea271eaf4045112ab2a03bb590bbbeb`, independently reviewed, and installed into a new
root-owned versioned directory under `/usr/share/ksi-external-runtime/releases/<source SHA>/systemd`.
The installed checksum list is content-equivalent to the source list with canonical reordered
entries; its SHA-256 is `5d1e95e25ac5eeaa6a4f419a1bee7884ab6483e0a49d59857ba73edcdd03bb35`.
The older template tree and installed user units were preserved unchanged.

Only the dormant root-owned socket helper was updated to the existing reviewed server-peer-receipt
implementation. Its identified predecessor bytes were retained in a create-once root-private
backup. Application sockets remain disabled, daemon/ACL units remain static, all remain inactive,
and the existing private Docker daemon retains its process identity. The installed helper's real
negative verification exits 1 and emits no positive proof while the application sockets are absent.
No bootstrap, service start/reload/enable, ACL mutation, account/map change or staging operation ran.

Relevant deployment/host-proof/listener/catalog/operator/release tests plus four task-private
operator safety regressions passed **163**. The operator fixes were observed RED→GREEN; actual
root-owned copy/hash/mode, backup, old-tree preservation and dormant-state checks passed separately.
The private ledger and root receipts are linked in the
[bounded preparation plan](../superpowers/plans/2026-10-03-contained-runtime-preparation.md).

**Still blocked:** application daemon/worker bundles and protected configurations are absent at
their configured paths. Current source/image/SBOM/scanner/host binding, signed execution manifest,
OCI-pair/revocation/trust configuration and subsequent Core policy/worker authority have not been
supplied and verified. Static files create none of those approvals. Public inspection, preparation,
pixel/mask comparison, analysis, actual host containment and customer acceptance remain unrun.

### 2026-10-03 — source-bound local image security repair (not release)

The Human then approved task-private verification tools/DB and local rootless builds, followed by
the two images' OS-package security repair. The original images and scans remain preserved. From
clean source `81f69883b59f53a2a015faea8fd4caa6d8cb34e3`, both Dockerfiles now use the fixed
20261003 Debian snapshot and corrected gzip, glibc, PCRE2, SQLite, OpenSSL and Perl versions.
Base-image/uv digests, `uv.lock`, non-root users and fixed entrypoints are unchanged. Both actual
ARM64 builds and exports succeeded; no application container or raster parser was started.
APT completed with normal signature checks and no bypass flags or signature errors; the quiet
build logs do not retain verbose InRelease verification lines.

| Same-tool / same-DB result per image | Before | After |
| --- | ---: | ---: |
| Total package/advisory matches | 253 | 185 |
| Critical | 7 | 0 |
| High | 87 | 60 |
| Medium | 88 | 67 |
| Low | 25 | 12 |
| Negligible | 46 | 46 |

These are scanner matches, not demonstrated exploitability or unique CVE counts. Syft1.54.0 and
Grype0.120.0 official archives/checksums/licenses were retained; Sigstore bundles were not verified.
DB v6.1.10 built2026-10-03T06:31:58Z remained byte-identical during repaired scans, and repeated
baseline scans reproduced the original matches. Actual SBOM versions prove the nine targeted OS
packages changed, while non-Debian package identities and package inventory were preserved.
Real old/new evidence tests observed **4 failures -> 4 passes**; owner regressions **584 passed,
2 generated-fixture warnings**. The earlier full suite belongs to its earlier source state.

| Role | Locally observed OCI index digest (not registry publication) |
| --- | --- |
| Inspector | `sha256:b6017a896a9c18194116f1caceca99f088e2f5c11ddc1b48f52a5faed815499f` |
| Measurement | `sha256:89c3a6ef6415fdc5094b3234ac558bea6a0ed81f5ac077dedf64ce65a8bccc98` |

All referenced OCI blobs/configs/layers and actual SBOM/scanner image identities were compared.
Docker-save/Syft's synthetic manifest is **not** the local OCI index digest; both are recorded
separately. Raw Grype JSON also lacks the existing host gate's scanner envelope. No placeholder
envelope, signed input, host binding or release approval was created from these observations.

**Still blocked:** High60 per image remains, including Debian `wont-fix`/`not-fixed` entries and a
Python3.12.14 binary advisory with a reported fix. No finding was ignored or waived. Security
applicability/release review, compliant release/host evidence, actual protected application bundles,
signed execution/OCI-pair/revocation/trust configuration, Core policy and worker authority remain
required. The application sockets remain disabled/services inactive and older tags retain their
original identities. Public inspection, crop/pixel-mask comparison and analysis remain **NOT_RUN**;
no customer, accuracy, Terra, deployment or field acceptance follows from this repair. Evidence and
remaining gates are recorded in the [existing preparation plan](../superpowers/plans/2026-10-03-contained-runtime-preparation.md).
An independent read-only review found no blocking OS-repair code defect; the residual Python
advisory and missing compliant scanner/release evidence remain activation blockers, not waivers.

### Task 3 blocker-resolution follow-up — documentation/read-only analysis

The [preparation plan's Task 3 follow-up](../superpowers/plans/2026-10-03-contained-runtime-preparation.md#task-3-follow-up-resolve-actual-blockers-through-existing-contracts)
now separates security disposition, scanner producer/tool authenticity, canonical release/registry
identity, protected application packaging/configuration, signed execution/Core authority, actual
containment and durable evidence custody. It names existing consumers/paths, supplier roles, required
approvals and completion evidence without claiming the unknown suppliers or inputs exist.

Official PSF CNA data for `CVE-2026-82049` lists Python3.12 versions below3.12.15 as affected.
Both retained repaired image archives contain `tarfile.py` byte-identical to upstream3.12.14;
component/version presence is confirmed, complete dependency reachability and exploitability are not.
This is not a waiver or authorization to change the base image. The existing release aggregator
records supplied scanner bytes but does not generate the strict runtime scanner envelope; no
accepted production producer was found in the inspected tooling/CI/ops paths. Test fixtures and
manually added fields cannot supply it. Sigstore verification and actual release/security review
remain pending, with no invented universal `High == 0` rule.

This follow-up did not change code, images, host configuration or authority inputs, and did not
re-observe live host state. The proposed gated endpoint is one genuinely Core-admitted, sealed
input processed by the real inspector and durably returned to Core, not full containment safety,
quantitative accuracy, customer acceptance or Spatial Data execution acceptance. It remains unrun.

### Python repair and native scanner consumer — 2026-10-04

After the Human approved both written specs/plans and inline implementation, the two runtime
Dockerfiles were repaired at source `16084bfa6c8bdde6123511ea11660852707e6760` to official
Python3.12.15 index `sha256:29113dcae7aad06daa8e95260fa09f27d62be33b9687ea3774f771d601a02256`.
Both actual ARM64 builds/exports succeeded from the exact clean592-file allowed context;
only the two Dockerfiles differ from prior built source81f6988. Existing20261003 snapshots,
all ten exact OS pins, uv/lockfile/dependencies, users and fixed entrypoints were preserved.
Raw official base index/platform/config bytes and every archived OCI blob were hash-verified.
Each final image's `tarfile.py` matches upstreamv3.12.15, SHA256
`f0891b6936a39e5a41bd857fc149191fbe30ca84e5958f203682e76e218ff2a4`.
No image entrypoint, public TIFF or service was executed.

| Same-tool/same-DB matches per image | Prior OS repair | Python repair |
| --- | ---: | ---: |
| Total | 185 | 179 |
| Critical | 0 | 0 |
| High | 60 | 59 |
| Medium | 67 | 63 |
| Low | 12 | 11 |
| Negligible | 46 | 46 |

The retained Syft1.54.0/Grype0.120.0 binaries were rehashed to their acquisition receipts.
DB SHA256 `053403d879610c96cccd011456cd053a3311131f084557132492cf076778e224` stayed identical.
Six Python package/advisory matches disappeared, including `CVE-2026-82049`; none were added.
Remaining fix states are fixed13/wont-fix112/not-fixed54 per image. Inventory and all non-Debian
identities except the intentionally changed Python binary were unchanged. **High59 is not waived**;
tool Sigstore authenticity and security/release disposition remain unverified.

| Role | Local OCI index (`docker image inspect .Id`) | Actual config (Grype `imageID`) |
| --- | --- | --- |
| Inspector | `sha256:8183a062b1bc4b49bb7d16d9c3a2c9075e089d901a01553c82cb31aeea4c7252` | `sha256:e0887275556f3eff7e8bf258c3d9c186d1b80ae0c9f2924f623728ff51284382` |
| Measurement | `sha256:8586f18203c95e1dacbb80b4d9eb1fa0aebf146969a127d73f6b8fb0c99d1b59` | `sha256:8bd386effecf84db49e4f943b41bc5bcc7e9a43e043cba084f3e8489dadf6d67` |

Platform manifests are inspector
`sha256:cd63a7201c291594cb8cb742158f6dc6b4d50f0cc69759268de3adcd1c045918` and measurement
`sha256:8ce68012901dd750b8ac87eec3d7a7cdcaa3aa89ba5988993a7dd5f1a6f3ec8d`.
All21 OCI blobs/15 layers per archive were checked; these identities are not interchangeable
and local RepoDigests are not registry publication evidence.

Native consumer source `6678e3b19e33f46ad3f0b2676937c0f6cf71de1a` and strict-stage integration
`c34fc8a` preserve the original report bytes. Grype0.120.0/DBv6.1.10 profile, findings structure,
safe-file identity, byte count/SHA256 and exact expected image ID are checked. Legacy envelopes
remain compatible; there is no report-schema fabrication, security decision or new authority input.
Verification: parser37RED→GREEN; stage native2RED→GREEN with legacy still valid; related source
contracts147passed9.55s, Ruff/mypy/shell syntax clean. Actual Python evidence4RED→GREEN, combined
Python/OS evidence8passed0.13s. Full regression results are recorded separately after completion.

One independent read-only branch review confirmed the source/image boundaries and the real
index/config integration blocker. Its ten-pin coverage gap and legacy annotation false-positive
were repaired in `c3ee4b7`: mutation tests now reject deletion/version substitution of any ten
OS pins in either Dockerfile (also correcting the prior whitespace-token regex), while incidental
legacy `source` notes no longer trigger native classification. Grype-shaped source/descriptor
still cannot fall back. Review-fix evidence35RED→GREEN; related source/API/permission checks
242passed14.59s, Ruff/mypy/shell syntax clean. Legacy in-report binding and generic Core/Dashboard
multi-read behavior remain explicitly unchanged, not new hardening claims.

The first full Python run at c34fc8a with inherited umask0002 produced8193passed/5failed/121skipped,
98warnings771.60s. All five failures were `UNSAFE_DIRECTORY`/`CONFIG_FILE` in four Analysis-pilot
fixture paths and one external-analysis fixture: default mkdir created group-writable0775 parents.
Without any product change or gate relaxation, command-local umask077 rerun of both affected
files passed54tests5.37s. The original failed log is retained; a final full run is still required
and will be reported with its actual revision/command/result, not inferred from this scoped rerun.

Final actual-main verification at `e3c3d27c63c6338a95b7a19532d4b7498ee73d78` ran the complete
`.venv/bin/python -m pytest -q` with prepared dependencies, offline/no-sync/no-download settings
and command-local umask022: **8239passed,121skipped,98warnings,zero failures in772.62s**.
The interim main run with umask077 had8238passed/1SDKpackagingfailure: vendored `build_dpk.sh`
created a0700 `DEBIAN` directory, which `dpkg-deb` rejects (requires0755..0775). A separate local,
never-installed package fixture proved0700exit2/0755exit0; C locale alone did not resolve it.
With umask022, both authority directory gates and actual SDK package test passed (67scopedchecks),
then the full suite above passed. No product/reference/SDK code or host permission policy changed.
All failed/interim logs remain retained alongside `follow-up-main-full-python-umask022.log`.
This is full local source regression evidence, not release, containment or field acceptance.

The Human selected a new v2 archive/index/platform/config-link design after this actual binding
defect was found. Its [written spec](../superpowers/specs/2026-10-04-external-runtime-oci-scanner-link-design.md)
is pending review; no v2 schema/verifier/consumer has been implemented. Protected application bundle
packaging remains a separate design unit. Prior source/profile identities are never relabeled as
current release evidence, and required real authority suppliers/inputs remain unresolved.

**Discovered contract blocker:** the approved design assumed the host-observed Docker ID was
the scan config ID. That is false on this actual containerd store: explicit platform inspection
also gives a manifest, not a config. Four unchanged real reports (prior/new, both roles) pass the
standalone verifier and strict artifact function when supplied their independently archive-verified
config ID, and reject the actual Docker index, swapped IDs or wrong hash. This proves parser
compatibility and fail-closed behavior, **not actual full release binding**. Do not supply that config
ID as a fabricated host observation. A verified index/platform/config link requires a new reviewed
security contract; native runtime release support on this actual target remains blocked.

Receipts are retained in `.opencode/artifacts/contained-runtime-preparation-20261003/`:
`image-build-16084bf/` (source, builds, archives/OCI/SBOM/scans/comparison), and `task3-analysis/`
(pin/image RED→GREEN, scanner checks, raw-report checks). Private image archives are under
`/tmp/opencode/ksi-runtime-verification-20261004-16084bf/`, and the rootless build copy under
`/var/lib/ksi-external-runtime/launcher/build-evidence-20261004-16084bf/`. Earlier archives/reports,
images/tags, original public files and workspaces were retained. Application bundles/signing/Core
credentials, registry promotion, tool verification, genuine host containment, public-file analysis
and customer/field/accuracy acceptance remain open; no push or activation occurred.

## Run local checks (no network or public binaries required)

```text
.venv/bin/python -m pytest tests/contract/test_spatial_data_http_integration.py tests/replay/test_spatial_data_delivery_replay.py -q
.venv/bin/python -m pytest tests/contract/test_spatial_data_consumer.py tests/contract/test_spatial_data_public_verifier.py -q
.venv/bin/python -m pytest tests/contract/test_spatial_data*.py tests/replay/test_spatial_data*.py tests/contract/test_external_native_window*.py -q
```

Recorded gate outputs and exact unchanged baseline failure IDs live in
`.opencode/artifacts/spatial-data-delivery-recovery-20261001/`; the active task ledger is
`docs/superpowers/plans/2026-09-30-spatial-data-delivery-v1.md`. Check actual current Git
and ledger before reusing counts. Full regressions retain the private-bus positive
socket precondition failure and nine absent pinned official PSDK KMZ cases; these are
not weakened or claimed passing.

## Operations / rollback gates still open

- Actual host/image/namespace/UID separation, SDK envelope and immutable-provider compatibility.
- Cross-process restart, transport interruption, deployment/backup/retention/archive operation.
- Audit projection is finite; terminal slots are reserved before admission, and exhausted
  history fails closed. No unapproved implicit eviction, rotation or archival exists.
- Cleanup tracks exact owned upload keys/versions, starts only after capabilities/leases and
  accepted retention expire, and durably retires acknowledged deletion. Exhausted failures
  remain visible through trusted owner diagnostics and retain capacity; sources/evidence are
  never enumerated or deleted. ASGI handed-off counts do not prove client receipt.
- Actual public-file full inspection, isolated pixel/mask comparisons and peak resource evidence.
- Customer Terra exports/rights, two real survey cycles, independent reuse and human acceptance.
- MCP/Console parity, OIDC/Analysis integration and remote CI are separate gates; no new
  client/vendor compatibility claim follows from local fixtures.

Rollback stops this worker and disables only its opt-in data assembly/activation.
Keep sources, old analysis/managed journals, completed job/receipt/audit history and
recovery evidence. Use only exact owned derivative cleanup; never reset main or restore
whole shared files over unrelated work. No push, deploy, install or credential provisioning
is authorized by this runbook.
