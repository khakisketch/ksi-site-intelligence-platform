# Spatial-data Codex local acceptance — 2026-10-14 (synthetic)

- Status: LOCAL SOFTWARE EVIDENCE only. Synthetic copied data, local MinIO
  (`127.0.0.1:9100`), no customer data, no public sample, no bwrap sandbox,
  no deploy/CI. The parser-sandbox containment gate and customer acceptance
  remain OPEN.
- Related: [ADR-KSI-036 D6](../architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md),
  [rebaseline ledger](../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md)
  (2026-10-14 item-4 section), [provisioning runbook](../ops/SPATIAL_DATA_PRODUCTION_PROVISIONING.md).
- Rig (transient): `/tmp/opencode/ksi-sdata-codex-20261014/` — scripts, logs,
  evidence (`SUMMARY.md`); data copy `~/.cache/ksi-sdata-20261014/`.

## What was exercised and passed

- Protected lane boot: an owner-private generated config + rights file
  (Ed25519-signed activation, one operator grant) mounted
  `app.state.spatial_data` on the production factory (port 8061); the grant was
  imported idempotently into `spatial-data-grants.jsonl`.
- Operator read path: site 200 (`aiEgressAllowed=true`), spatial-asset catalog
  200 with 20 page-1 assets; the target DSM `ksa-v1-8430fcc…` shows `MEASURED`.
- Real inspection lane (documented in-process precedent, actual MinIO bytes):
  both current-policy requests executed `COMPLETED`, `MEASURED` 2×2 EPSG:5186.
- Codex CLI (0.160.1, ChatGPT auth) with the spatial-data MCP stdio adapter:
  initialize + `tools/list` (six tools), and a `tools/call` that reached Core
  and returned Core's typed finite-budget response (`RESOURCE_LIMIT_EXCEEDED`).
- Storage guarantees probe against local MinIO: **16/16 checks passed** —
  non-null version IDs, FULL_OBJECT SHA-256 echo and match on HEAD,
  exact-version read, version listing, presigned GET signed for
  `host;x-amz-checksum-mode` returning exact bytes and checksum header,
  exact-version delete, deleted version unreadable, other version survives,
  cleanup. A naive client sending extra unsigned headers is refused by MinIO
  (`400` "headers present which were not signed"), so consumers must send
  exactly the signed headers — the product transport already does.
  This closes only the local S3-compatible half of the storage gate; a cloud or
  customer-host S3 remains separate.

## Found and fixed (this session)

- The production token env could not register the documented
  `SPATIAL_DATA_MCP_CLIENT` kind with its required explicit scopes: the parser
  rejected `allowedSiteIds`/`allowedWorkAreaIds` for any kind other than
  `ANALYSIS_MCP_CLIENT`, making the AI client unreachable in production
  configuration. Fixed in `ksi_core.composition.runtime_config`
  (`_parse_principal_tokens` now accepts both MCP client kinds) with a locked
  adapter test; the runbook documents the registration shape.
- The AI discovery preflight could surface a non-current inspection report.
  Root cause: after the copied 10-12 chain renewal, candidates whose subject is
  no longer permitted by the active record get a non-ACTIVE selection; the
  preflight snapshot treated "no active selection" as "any retained record" and
  returned an old report bound to an expired policy. Delivery then failed that
  one candidate in `require_current`, and `CURRENTNESS_UNAVAILABLE` (not in
  `_LIST_SUPPRESSED`) escalated a single stale candidate into a whole-listing
  `503`; the operator catalog could also show a stale `MEASURED` as the current
  inspection. Fixed in
  `ExternalArtifactInspectionStore.public_snapshot_bounded`: without an active
  selection it returns the pending state and no report. The candidate is then
  classified per-candidate `SOURCE_NOT_MEASURED` (suppressed; `unready` when
  granted, invisible otherwise), the catalog projects the current pending
  state, and the historical report stays retrievable via
  `historical_report`/retained lookups. `require_current`'s pinned
  `CURRENTNESS_UNAVAILABLE` contract for the final check-and-commit is
  unchanged.
  Locked by two tests: store-level withdrawn-authority snapshot hiding
  (`test_bounded_inspection_without_active_selection_hides_stale_report`) and
  source-level preflight classification
  (`test_source_withdrawal_classifies_listing_preflight_as_unmeasured`), with
  the pinned final-recheck currentness test still green.
- Process lesson: two "fixed build" acceptance runs silently served a stale
  process that still held port 8061 (readiness was answered by the old build).
  The rig launcher now frees the acceptance port before spawning; the final
  evidence below was verified against the new process id.

## Completed Codex CLI chain (after both fixes)

Real client, real Core, synthetic copied data, local MinIO:

- Discovery (`ksi_list_spatial_data_assets`, limit 8): page `200` with the
  target `ksa-v1-8430fcc…` (`permittedOperations` `["READ","PREPARE"]`,
  `permittedBounds` `[200000, 549999.8, 200000.2, 550000]`); the other
  mixed-generation candidates are suppressed per-candidate as
  `SOURCE_NOT_MEASURED` instead of failing the page.
- Create (`ksi_create_spatial_data_request`, idempotency key
  `sdata-acc-codex-1`): `201` job `sdj-v1-a9bb54c9…`, `executionState`
  `QUEUED`, `availability` `NOT_READY` — an honest not-yet-prepared state, no
  fabricated receipt.
- Status (`ksi_get_spatial_data_request`): same job, `QUEUED`/`NOT_READY`.
- Cancel (`ksi_cancel_spatial_data_request`): `CANCELED`/`NOT_READY`; the Core
  journal shows `spatial-data-job.issued.v1` → `spatial-data-job.state.v1`
  (`CANCELED`) for that exact job.

## Boundaries and next steps

- The sandboxed parser (`bwrap`) containment, the VM verification host chain,
  a cloud/customer S3, public-sample acceptance, customer/operational
  acceptance, and deploy/CI remain OPEN and are not implied by this evidence.
  The prepared/`COMPLETED` half of the flow still requires the sandboxed
  preparation lane and its host containment proof.
- Next bounded candidates: run the same chain on the VM verification host
  (sandboxed parser plus a real preparation launcher), then re-check the
  storage guarantees against a cloud/customer S3 provider.

## VM verification-host + public-sample acceptance (2026-10-14, later — supersedes the prepared/COMPLETED-open bullet above for this host)

Real public data (Cambridge Coastcare Floreat-f4 DSM/ortho, CC BY 4.0, retained
read-only under `.dev-data/public-geotiff/floreat-f4-2022-08-24/`), an isolated
QEMU/virtio VM (Ubuntu 24.04 arm64), the real MinIO, the real Core, the real
Codex CLI and a genuinely contained worker.

### Product defects found by the acceptance (fixed, `d286c13`)

1. **The contained child's containment self-check was unsatisfiable.** The child
   check compared its namespaces against the authority's by stat'ing
   `/proc/<authority>/ns/*`; the kernel denies that across user namespaces to a
   zero-capability caller (verified on 6.8.0-142, including same-uid), while the
   required `child != authority` clause forces the worker into different
   namespaces. Every real launcher therefore died at exit 2 and no receipt was
   possible. The sandbox request frame (now `spatial-data-sandbox-request.v2`)
   carries the worker's own namespace inodes; the child compares numerically and
   the privileged parent keeps the kernel observation.
2. **Interpreter builds without `os.memfd_create`/`fcntl` seal constants** (this
   uv standalone CPython) died with `AttributeError` before spawning; the sealed
   proof descriptor now falls back to libc `memfd_create` with identical
   CLOEXEC and sealing flags. Regression tests: numeric authority inequality and
   fail-closed edges, the v2 frame contents, sealed-descriptor write rejection.

### Acceptance-envelope minting (KSI acceptance material, not product policy)

- The pinned inspection envelope (20 MB / 2 M px) could not measure the real
  artifacts; a renewed KSI-signed acceptance manifest/envelope (500 MB input,
  4 GB memory, 250 M px, 1 GB samples, 3600 s deadline) reached MEASURED on the
  real bytes (policy v17, report `sha256:18ef998a…`); `--add-subject-file`
  (`f77298d`) added the public subject to the chain.
- Spatial material re-minted for the public asset (policy `d6f54928…`), grant
  revision 2, CC BY 4.0 attribution retained; earlier acceptance material is
  preserved under `protected/history/`.
- Storage contract: the acceptance bucket had versioning disabled, so
  `versioned_head_identity` failed and `input` returned 503
  `INTEGRITY_MISMATCH`. Versioning was enabled and the two artifacts
  re-uploaded with full-object SHA-256 (versions `bf667e8e…`/`b1e368c8…`,
  checksums equal to the pinned originals).
- Observation-date boundary: the sealed public submission's declared capture
  window (`2026-10-10T10:00Z`–`10:30Z`) is a synthetic placeholder copied from
  the earlier acceptance material, not the Floreat-f4 source date
  (2022-08-24). Declared observation metadata in this rig must not be read as
  truthful public acquisition history; correcting it would require a new
  immutable submission revision and is not part of this acceptance.

### Completed chain (real Codex CLI → real Core → real VM worker)

- Codex MCP discovery → create (`sdata-public-accept-final`) →
  `sdj-v1-ca9b7b2f…` QUEUED.
- VM worker (uid 10001, file-cap interpreter, TLS to Core, MinIO through a
  VM-local forwarder) downloaded the sealed 181,498,053-byte DSM; the pinned
  launcher joined the persistent namespaces; the child ran with uid/gid 10001,
  all capability sets 0, NoNewPrivs 1, Seccomp 2, pinned mountinfo and envelope
  rlimits; the real native-window crop ran (2000×2000, EPSG:7850); the receipt
  was uploaded → **COMPLETED** (output `sha256:0fcb7fd7…`, 9,166,428 bytes,
  window `[1357,3357,3633,5633]`).
- An HTTP-only consumer downloaded with receipt/header verification and an
  independent oracle (direct rasterio window read of the original) returned
  **PASS 11/11**: pixel arrays equal, nodata/mask and valid count (4,000,000),
  transform/resolution/CRS, bounds, and byte identity.
- Smoke result `sdj-v1-543dc281…` completed the same flow during debugging;
  failed intermediate attempts (pre-envelope / pre-versioning) remain in the
  journal honestly. Evidence: `evidence/public-sample/` in the rig.

### Host/harness notes and remaining uncertainty

- The sandbox harness (holder/launcher/proof, file-cap interpreter, staged
  byte-identical runtime) is operator material under
  `/tmp/opencode/ksi-sdata-vm-sandbox/`; suitability for deployed hosts remains
  a separate operator gate, and a product-side reference review of that
  material has not happened.
- The 9p passthrough share denies uid 10001, so the contained runtime is a
  staged copy; mountinfo pinning is stable only while the VM mount table is
  unchanged.
- Still OPEN: cloud/customer S3, customer/operational acceptance, deploy/CI,
  re-running the chain on a second host/cycle.

### Grant lifecycle on the same rig (2026-10-14, after the acceptance)

Ran against the rig Core (:8061) that issued the accepted job, restarting it
between rights imports. The revocation is append-only (recorded once in the
grants journal with its exact digest; re-sealing produces a new digest and is
refused with `REPORT_CONFLICT`), so rev2 stays revoked permanently and the
only recovery is a new revision. Evidence: `evidence/public-sample/lifecycle/`.

- Baseline: requester (MCP) file download 200, `sha256:0fcb7fd7…`,
  9,166,428 bytes (exact match).
- Revoked rev2 (revocation journaled, `f70fad4d…`, reason `OWNER_REVOKED`):
  new AI create **403 `GRANT_REQUIRED`** (`REQUEST_NEW_GRANT`); requester
  status **403 `ACCESS_REVOKED`**; requester bytes **403**; operator status
  stayed **200 COMPLETED** with `availability: ACCESS_REVOKED` (frozen
  historic visibility, no bytes) and operator bytes **404** (contract:
  byte authority is the requester, never admin sharing).
- Recovery under rev3 (`sha256:7fa50b5d…`, imported while rev2 stays
  revoked): new create **201** (`sdj-v1-d9825d25…`, canceled), replay of the
  revoked-window idempotency key now **201** (denials are not journaled as
  idempotent outcomes), and the rev2-issued COMPLETED job's bytes remain
  **403 `ACCESS_REVOKED`** by design — revocation is not retroactively
  recoverable per job.
- Retention: the rig policy keeps outputs for 3600 s, so the accepted job's
  availability now reads `RETENTION_EXPIRED` (honest lifecycle; the
  acceptance-time download was inside the window).
- The rig now runs on grant rev3 (rev2 revoked) and the console request
  surface renders the frozen/denied states from the same Core.

### Second cycle on the same rig + worker clock-skew fix (2026-10-14 late)

A second request cycle ran end-to-end on the same rig and Core data dir
(no journal resets): `sdj-v1-dbdb2f13-e0d7-418e-89c3-db670129a851` (bounds
`[382430,6467680,382530,6467780]`, grant rev3) → VM worker → **COMPLETED**
(`sha256:6bac8aa7…`, 8,658,999 bytes, window `[2957,4957,3033,5033]`,
2000×2000, EPSG:7850, availability `AVAILABLE`) → requester download matched
receipt size/hash → independent oracle **PASS 11/11**. This crop contains
NoData (valid 3,903,511 of 4,000,000 pixels), unlike the first acceptance
crop, and the oracle still confirms exact pixel-array equality, the declared
nodata value and the NoData-derived valid count. The oracle compares pixel
arrays, the declared nodata and derived counts — not dataset masks/alpha
arrays directly; an RGBA/alpha comparison remains an ortho-path item.

The first attempt failed with `FENCE_CONFLICT` and led to a real defect fix
(`246e954`): `acquired_at` is stamped by the Core clock, and both the client
attempt check and the lease guard required the worker clock to be at or past
it, so any negative clock skew (the VM ran 13 ms behind the Core; the
acceptance had passed on skew in the other direction) fenced a fresh lease
before any Core call. Only expiry bounds are locally checkable; the Core
refuses any use past its own lease/deadline/grant bounds. Regression tests
pin both directions (behind clock accepted, past-expiry refused) and the
fixed worker runtime was re-staged byte-identical into the VM
(`1c501e35…`/`fbe29708…`). Diagnostic attempts (2 lease-only probes and one
attempt-exhausted job `sdj-v1-5e8cf748…` → FAILED `LEASE_EXPIRED`) remain in
the journal honestly. Evidence: `evidence/public-sample/cycle2/`.

### Ortho (RGBA) extraction path on the same rig (2026-10-14 late)

The public orthophoto (`floreat-f4-2022_transparent_mosaic.tif`, 346,715,111
bytes, 10298×17615 RGBA, 0.025 m, EPSG:7850) was MEASURED under the same v17
inspection report. A dedicated grant was minted for the ortho asset
(`sdata-public-accept-ortho-1` rev 1, `cf20d42c…`, same beneficiary, bounds,
operations, purposes and policy; rev2 stays revoked and rev3 stays current
for the DSM asset) and two request cycles completed:

- `sdj-v1-93ea4f26…`: bounds `[382400,6467700,382475,6467775]` → COMPLETED
  (`sha256:ec113d69…`, 21,941,326 bytes, 3001×3000, 4-band uint8, window
  `[4712,7713,6265,9265]`) — a fully opaque window.
- `sdj-v1-5fb7bc78…`: bounds `[382282.2,6467700,382306,6467722]` → COMPLETED
  (`sha256:38316bc7…`, 685,914 bytes, 953×880, window `[0,953,8385,9265]`) —
  contains the mosaic's transparent edge (377,288 of 837,760 pixels alpha 0).

Both downloads matched their receipts, and the independent RGBA oracle
(`verify_public_oracle_rgba.py`) returned **PASS 16/16** each: exact
four-band pixel-array equality, **dataset masks compared directly**
(`read_masks`), alpha-band equality, alpha-mask equality, alpha counts, and
transparency presence mirroring the source window, plus transform origin,
resolution, CRS, bounds and byte identity. This closes the dataset-mask/alpha
comparison gap noted for the earlier DSM oracle (whose stronger checks were
pixel-array equality, the declared nodata value and NoData-derived counts).
Evidence: `evidence/public-sample/cycle2/`.

### Second host reproduction (2026-10-14 late)

A second verification host was built from a clean copy of the VM image
(`noble2.img`, standalone qcow2 convert) with **full re-provisioning**: the
sandbox tree was wiped and `provision_sandbox.sh` re-staged the runtime from
the repo (picking up the clock-skew fix), started a new holder and re-installed
the launcher/python-cap; the TLS/MinIO forwarders were reinstalled. The proof
was re-minted from the new live holder (user/mnt/net ns `4026532289/348/290`,
mountinfo `61f1a29d…`, launcher `0c76f563…`) bound to the public policy
(`d6f54928…`)/runtime (`3b1a84bb…`) material.

- New request `sdj-v1-cb73aba7…` (the original acceptance window
  `[382350,6467650,382450,6467750]`, grant rev3) → VM2 worker → **COMPLETED**
  (`sha256:0fcb7fd7…`, 9,166,428 bytes, window `[1357,3357,3633,5633]`).
- The downloaded output is **byte-identical** (`cmp`) to the first acceptance
  output (`sdj-v1-ca9b7b2f…`) and the oracle returned **PASS 11/11**: same
  input bytes + same window + same code reproduce the same output on a second,
  freshly provisioned machine.

Two provisioning-order findings (recorded in runbook §9.1): the CA overlay
must be applied to the **staged** venv's certifi (provision→install_net order
otherwise leaves the staged copy CA-less and the worker reports
`CORE_UNAVAILABLE`), and every mount must happen **before** the holder starts
or the proof is minted — the certifi bind mount propagated into the holder's
shared mount peer group and changed the pinned mountinfo sha after
provisioning. Evidence: `evidence/public-sample/host2/`.
