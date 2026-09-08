# External GeoTIFF profile v1 implementation supplement

> **Status:** Lead-adopted implementation supplement (2026-09-08), following
> independent review and the Human authorization to continue product work on
> 2026-09-08. Parser/runtime implementation: **NOT_IMPLEMENTED**. Producer
> compatibility, accuracy, host enforcement, deployment and release acceptance:
> **NOT_VERIFIED**.


**Requirement IDs:** REQ-INT-101, REQ-INT-102, REQ-INT-103, REQ-INT-104,
REQ-SEC-101, REQ-OPS-102.

**Owner module:** `services/processing-controller/` owns sealed-byte parsing and
sanitization.  `services/core/` remains the policy, tenancy, evidence and
per-use decision owner.  `packages/event-contracts/` remains import-only
contract authority.

**Invariants and enforcement:** INV-024: no RMSE/accuracy output; INV-051:
external results remain derived observed evidence; INV-053: a measured raster is
not an external-readiness or quantitative-eligibility decision; INV-060:
server-derived sealed capability, Core scope and no untrusted-path access.

**Acceptance criteria:** accept only the exact grammar in
[external-geotiff-profile.v1](../specs/2026-09-08-external-geotiff-profile-v1.md),
produce complete per-artifact report-first measurements, issue no unsafe display
derivative, fail closed on all parser/resource/runtime faults, and leave all
positive use decisions with Core.  A local pass is not a compatibility,
deployment, HIL, field, release, or customer-data acceptance claim.

**Contracts affected:** no wire/schema change.  Bind the existing
`ExternalValidationPolicyV1.grammarDigest` and execution-manifest
`backendProfileDigest` to the same canonical profile JSON digest, then bind that
to manifest-derived `parserBuildDigest`/
`inspectorBuildDigest`; use existing `RasterMeasurementsV1`, inspection report,
and display receipt contracts.

**Reference assets/adoption:** Product direction is ADR-KSI-036; adopt only its
external-derived evidence route.  Use the existing external-artifact-validation
design and sandbox amendment as the inherited contract/security design.  Do not
import from `references/` or infer support from a GDAL build, a demo raster, or a
vendor document.

**Files to change:** planned production ownership is
`services/processing-controller/src/ksi_processing_controller/external_geotiff_inspector.py`,
`external_sanitized_raster.py`, the existing launcher/worker, and narrowly owned
contract/replay tests.  This plan itself changes no runtime file.  A future
canonical profile implementation is internal parser policy, not a customer wire
schema.

**Tests:** synthetic GeoTIFF bytes produced by test fixtures; malformed and
hostile byte mutations; exact report/replay tests; production parser invocation
only through the launcher sandbox.  Unit tests may exercise pure profile,
framing and state decisions, but no host parser fallback is permitted.

**HIL/real-device assumptions:** none.  Synthetic host-backed container tests
are operational evidence only and run sequentially after provisioned rootless
identity/daemon/controller proof.  No DJI, field, customer export or accuracy
assumption is made.

**License/data implications:** tests use generated synthetic rasters only.  Do
not retain customer bytes outside existing sealed stores, ship producer metadata,
or activate an unreviewed grid/plugin/data license.

**Rollback:** admission-off; retain immutable evidence; exact recorded attempt
cleanup only; no unsandboxed parse, broad container cleanup, privilege widening,
or contract backfill.

## Preconditions

Tasks 1, 1b and 2 of the sandbox amendment are the current local prerequisite.
The profile must receive independent review and Lead adoption before any positive
parser implementation.  Active policy must carry finite sealed
`ResourceEnvelopeV1`, a current authority record, an exact grammar digest and a
manifest binding.  Missing or mismatched values return a typed unavailable or
rejected result; no development default becomes an operational limit.

The parser process can start only after the launcher has sealed the bytes into
its private file, verified size/digest/current fence, and passed a fixed
read-only bind through the launcher-only UDS protocol.  Worker, Core and parser
receive no daemon credential.  The host-specific identity, rootless daemon,
socket authorization and controller enforcement remain Task 5b/5c work from the
sandbox amendment.

## Task 3 — sealed handoff and parser profile

### 3.1 Freeze the internal profile and bindings

Write RED contract tests that reject a missing/changed grammar digest, a backend
profile whose digest is not byte-for-byte equal to it, a parser/inspector build
mismatch, unbounded envelope,
caller-selected parser setting, or a profile rule not in the closed v1 set.
Implement one canonical profile-body serializer and digest verifier local to the
processing-controller parser boundary.  It must compare the current Core policy,
signed manifest and sealed request before any parser process starts.  Do not add
fields to `RasterMeasurementsV1` or reinterpret a report as eligibility.  Tests
must cover `canonical_json_bytes` UTF-8/sorted-key/finite-JSON behavior, equal
digest on object-key reorder, and changed digest on every positional-array
reorder; build digest contains the profile binding but is not equal to it.

### 3.2 Enforce byte sealing before parse

Write `test_external_inspector_byte_boundary.py` RED cases for source-count and
digest mismatch, symlink/hardlink/inode substitution, source replacement during
staging, non-regular input, failed fixed-UID read, caller path/mount/env/image
injection, output overflow, deadline/fence revocation and no host GDAL preflight.
Implement launcher-owned exclusive staging with a recheck immediately before
create.  The only permitted parser input is the fixed read-only in-container
path.  The parser sees no sidecar, socket, workspace, customer directory,
network, credential, writable filesystem, plugin/PAM state, remote VSI or
unapproved grid.

### 3.3 Parse and measure the exact v1 grammar

Write `test_external_geotiff_inspector.py` from generated bytes before the
implementation.  Cover both endian forms and classic/BigTIFF; positive stripped,
tiled and valid COG forms; accepted compression/predictor combinations; JPEG
RGB/YCbCr exposure; RGB; binary-alpha RGBA; each DSM nodata model; internal
masks; valid and invalid overview chains;
finite/nonfinite sample scan; affine/CRS/compound-vertical observations; cap,
truncation and cancellation paths.  Add negative corpus mutations for every
rejected model: extra image/IFD, external sidecar/reference, VRT/VSI,
GCP/RPC/geolocation, zero/overlap offsets, invalid block count, unsupported
compression/predictor/sample/layout, conflict/identity/singular transform,
ambiguous CRS, invalid DSM axis, and malformed COG order.

The COG corpus specifically varies non-square/non-16-divisible/oversize tiles,
missing image or mask overview levels, logical overview dimensions
`ceil(previous / f)` for one `f` in 2 through 10, with strictly decreasing logical
overview dimensions,
directory/IFD order from base image and base mask through all image overview
IFDs (largest to smallest), then all mask overview IFDs (largest to smallest),
image payload block order smallest overview->larger overview->base with
within-level row-major offsets, and invalid final tile size.  It also varies
`LAYOUT`, `BLOCK_LEADER`, `BLOCK_TRAILER`, `BLOCK_ORDER`, `KNOWN_INCOMPATIBLE_EDITION`,
and mask interleave with declared leader/trailer facts.  CRS tests require offline
Rasterio/Pyproj horizontal EPSG identity and equivalence; identifier `EPSG:{code}`;
exact Pyproj WKT2_2019 serialization and UTF-8/no-newline digest; signed-manifest
package/GDAL/PROJ identity; and the exact five binary64 `.17g` pixel-edge WKT
points with signed zero rendered `0`; plus explicit helper-format outputs for
`-0.0`, `0.0`, `0.1`, and `1.2345678901234567`.  The vertical-absent DSM
case is `MEASURED` with a null vertical observation; only Core use-decision tests
block dependent uses.

Implement full structural validation before permissive backend open, then read
all base/mask/overview blocks under the injected limits.  Produce only existing
typed `MEASURED`, `NOT_APPLICABLE` or `REJECTED` outcomes with safe reasons and
existing measurements.  A DSM with no vertical component is measured
structurally with `observedVerticalReference: null`; it is not marked
HEIGHT-ready.  No partial scan, caught decoder exception or cap breach may
produce a positive report.  Cancellation/fence loss is request-incomplete and
submits no partial report; it is never represented as an unimplemented
per-artifact outcome.

The test package has one explicit synthetic-only callable conformance core.  It
generates and mutates bytes and may call pure structural/profile functions, but
cannot reach production decoding.  A production-reachability guard proves that
all real Rasterio/GDAL/Pyproj decode/open calls require the signed parser
container invocation path; no injected runner, test mode, environment flag or
local fallback reaches a host decoder.  Host enforcement cases are named
`test_host_*` and execute only after the provisioned rootless runtime exists.

**Local Task 3 gate:**

```bash
uv run --locked pytest tests/contract/test_external_inspector_byte_boundary.py tests/contract/test_external_geotiff_inspector.py -k 'not host_' -q
uv run --locked ruff check services/processing-controller/src/ksi_processing_controller tests/contract
uv run --locked mypy services/processing-controller/src/ksi_processing_controller tests/contract
```

An independent reviewer must inspect the actual diff and targeted evidence while
the writer is idle.  The gate proves no real mount, UID, cgroup, network or
container enforcement.

## Task 4 — sanitizer, runtime binding and recovery

### 4.1 Bind complete report and exact attempt state

Extend the existing launcher/worker only after Task 3 review.  Write RED tests
for report digest/build binding, stale policy/fence/deadline after parser return,
bounded output decode, cancellation, crash before create, after create before
ID persistence and after ID before cleanup.  Persist intent/nonce/known name/
owner/profile digest before create and reconcile only that exact record.  An
unknown or mismatched runtime state closes admission; labels never authorize a
broad cleanup.

### 4.2 Produce deterministic display artifacts

Write `test_external_sanitized_raster.py` from synthetic measured ORTHOs.  Prove
deterministic re-runs, source/destination hash binding, exact preservation of
valid RGB, zeroing of invalid RGB, CRS, affine, footprint and validity semantics,
fixed output options, metadata stripping, reopen/full-scan, and no receipt on
write/reopen/compare/hash failure.
Cover RGBA and mask inputs without silently converting their validity meaning;
the output is always RGB3 plus an internal binary mask, even all-valid input.
Verify alpha removal, full-resolution no-resampling, average color overview
rebuild, nearest binary-mask overview rebuild, `GEOTIFF_VERSION=1.1`,
`STATISTICS=NO`, fixed COG facts and exact reopen comparisons.  Do not sanitize
DSM, reproject, color-correct, repair, crop or derive a display from an
incomplete report.

### 4.3 Test pure runtime-control decisions and replay

Write `test_external_inspector_runtime_controls.py` and
`tests/replay/test_external_inspector_attempt_replay.py` for finite ceiling
clamping, timeout/output/log/tmpfs decision paths, stale-fence closure, exact
owner/name/profile recovery, cleanup failure admission closure and immutable
attempt replay.  Pure tests may use an injected runner protocol.  Tests that
exercise an actual daemon, bind, controller, UID map, no-network setting or
resource limit are named `test_host_*`; they must not be replaced by mocks and
are excluded from this local gate.

**Local Task 4 gate:**

```bash
uv run --locked pytest tests/contract/test_external_inspector_runtime_controls.py tests/replay/test_external_inspector_attempt_replay.py tests/contract/test_external_sanitized_raster.py -k 'not host_' -q
git diff --check
```

Run independent review again because Task 4 changes the execution condition and
the sanitizer/report binding.

## Inherited operational and adversarial gates

Task 5a authors the synthetic hostile input suite: decompression and TIFF
structure attacks, sidecar/VSI attempts, parser-output abuse, path/credential
leak, no-network canary, mount and cancellation/orphan recovery.  It has no
customer bytes and does not itself prove a host boundary.

Task 5b provisions the separately reviewed rootless identity, user systemd
daemon/socket, signed catalog/trust material, and cgroup-v2 delegation.  It may
not give Core/worker/parser Docker access or activate customer processing.
Task 5c runs the `test_host_*` selection serially on synthetic bytes and records
actual socket ownership, UID/read-only bind, controller, no-network, timeout,
resource, hostile-input and exact-cleanup evidence.  Unavailable, skipped,
mocked or uncollected tests are `NOT_VERIFIED`, not PASS.

Task 6 is an integration review across contracts, Core fences, launcher,
parser, sanitizer, replay and hostile/host evidence.  The Lead reruns the
narrowest meaningful union after the final integrated diff and separates local
test success from remote CI, deployment, policy activation, compatibility,
customer-data acceptance, HIL, field acceptance and release.
