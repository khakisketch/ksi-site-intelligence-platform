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
