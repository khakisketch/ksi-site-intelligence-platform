# GAP-06 load evidence: bounded native-window PREPARE budget (measured 2026-10-21)

Evidence for the display/LOD contract's open decision #2 (per-interaction PREPARE
budget N and queue ordering) and acceptance criteria 2-3. This is measurement
evidence, not a design contract: it states observed numbers, not policy.

- Lane: own Core `http://127.0.0.1:8074` (production factory), real contained worker.
- Window: 2026-10-21 05:50:19Z-05:51:28Z (~69 s total, modest load, lane healthy throughout).
- Actor: local `ps-admin` credential (file-read, never printed); purpose `GENERAL_DATA_USE`.
- Site/area: `prod-sample-floreat-01` / `wa-prod-sample-floreat-01-0001`.
- Sources (all `SEALED`/`MEASURED`, 1022x915, EPSG:7850, 0.25 m, north-up, same grid):
  `ksa-v1-1ad55465…` (2021 ortho), `ksa-v1-3434d3f2…` (2021 DSM),
  `ksa-v1-3a1e2a08…` (2022 ortho), `ksa-v1-46ae5e28…` (2022 DSM).
  Transform `[0.25, 0.0, 382261.7296, 0.0, -0.25, 6467541.575]`
  (`services/core/.../spatial-assets` inspection receipt; `packages/geo-spatial/src/ksi_geo_spatial/external_native_window_geometry.py:60-94` is the cell-edge rule).
- Signed live policy `~/.cache/ksi-product-use-20261020/spatial-delivery/spatial-core-config.json`:
  `maxOutputPixels 262144`, `maxOutputBytes 8388608`, `maxActiveJobsPerOrganization 2`,
  `maxPendingRecords 8`, `maxQueueDepth 8` (envelope), `leaseSeconds 60`, `maxRetries 3`,
  digest `sha256:6837f65f…`. Enforcement on the PREPARE route is
  `services/core/src/ksi_core/domains/external/delivery/jobs.py:1044-1048` (429 past 2 active)
  and `:860-865` (sweep past 8 active); pixel cap at `:990-992` (422).
- Machine-readable artifact: `docs/audit/gap06-prepare-load-results-2026-10-21.json`
  (11 new jobs, poll 0.25 s; keys are random `gap06-<tag>-<8hex>`, no secrets).
- New jobs this run (all `COMPLETED`, requester-owned): `sdj-v1-70c6c3d8…`,
  `0e33bd17…`, `679e2ad4…`, `bbea9816…`, `78bb011b…`, `f1f46ee0…`, `2f43fa8e…`,
  `62f1a239…`, `6d023bbe…`, `909c5980…`, `aafe379a…` (full ids in the JSON).

## 1. Latency: one bounded 512x512 PREPARE -> COMPLETED (n=10 idle-lane samples)

Sequential issues (L1-L8) plus 2 burst-accepted jobs (C2, C5) and 1 fresh-key dup (I3).
`q` = issue -> first-observed RUNNING; `exec` = RUNNING -> COMPLETED (0.25 s poll
granularity); `total` = issue -> COMPLETED; `srv` = server `createdAt` -> `preparedAt`.

| job | asset-window (cols x rows) | q (s) | exec (s) | total (s) | srv (s) | bytes |
|---|---|---|---|---|---|---|
| L1 | o21 0-512x0-512 | 4.60 | 0.77 | 5.37 | 4.87 | 474427 |
| L2 | o21 510-1022x0-512 | 5.09 | 0.78 | 5.87 | 5.25 | 637695 |
| L3 | o21 0-512x403-915 | 4.85 | 5.87* | 10.72* | 5.15 | 526512 |
| L4 | o21 510-1022x403-915 | 4.87 | 0.78 | 5.65 | 5.18 | 626704 |
| L5 | d21 0-512x0-512 | 5.12 | 0.77 | 5.90 | 5.33 | 577639 |
| L6 | d21 510-1022x403-915 | 4.87 | 0.77 | 5.64 | 5.21 | 664582 |
| L7 | o22 255-767x201-713 | 5.12 | 0.77 | 5.89 | 5.36 | 644023 |
| L8 | d22 255-767x201-713 | 4.86 | 0.77 | 5.63 | 5.21 | 698270 |
| C2 | o22 510-1022x0-512 | 5.17 | 0.77 | 5.94 | - | 641250 |
| I3 | o21 0-512x0-512 (dup) | - | - | 5.88 | - | 474427 (sha-identical to L1) |
| C5 | d22 0-512x0-512 (queued behind C2) | 10.77 | 0.78 | 11.55 | - | 599041 |

* L3 is a single unexplained outlier: server-side `createdAt->preparedAt` is normal
(5.15 s) but the client poll observed COMPLETED 10.72 s after issue. Cause not
determined (1 of 11; no journal forensics performed on the live lane). All other
samples: total 5.37-5.94 s. Dominant cost is worker pickup (~4.6-5.1 s tick), not
execution (~0.77 s for every 512x512 window, ortho or DSM).

## 2. Concurrency: 6 parallel PREPAREs (burst at t=0, offsets 0.045-0.093 s)

- Accepted `201`: 2 (C2 o22, C5 d22). Rejected `429 CONCURRENCY_LIMIT_EXCEEDED`
  (`retryable: true`): 4 (C1, C3, C4, C6) — in 0.003-0.025 s, zero worker cost.
- The lane does NOT queue beyond 2 active at issue time: the 3rd+ concurrent
  PREPARE is rejected, not parked (`jobs.py:1044-1048`). `QUEUED` means
  issued-but-unleased; C5 (issued while C2 ran) waited 10.77 s ~= C2's full cycle
  plus the next ~5 s worker pickup tick, then completed normally.
- Drain wall for the 2 accepted: 11.6 s from burst start.
- `maxQueueDepth 8` / `maxPendingRecords 8`: no enforcement path was reachable on
  this route — issuance caps active at 2 first, so the sweep at `jobs.py:860-865`
  (`RESOURCE_LIMIT_EXCEEDED` past 8) cannot trigger while the cap is 2. A client
  must treat "queue depth" as 0 buffer + `429`-with-retry, not as 8 waiting slots.

## 3. Idempotency / duplicates

- Same `Idempotency-Key` + identical body (L1 replay): `200`, same `jobId`, 5 ms,
  no new work (`jobs.py:920-929`, `api.py:228-247` 201-vs-200).
- Same key + different bounds: `409 IDEMPOTENCY_CONFLICT`, no job (`jobs.py:961-962`).
- Fresh key + identical window (I3 vs L1): `201` new job, full re-execution
  (~5.9 s), byte-identical output (`outputSha256` equal, 474427 B). The lane does
  the work twice; de-duplication is the client's key discipline, with
  `outputSha256` as a content-level backstop.

## 4. Output cost per 512x512 window; whole-source rejection

- Ortho (uint8, 4-band): 474427-644023 B per 512x512 window (content-dependent;
  same window is bit-deterministic: L1 == I3 == historic `sdj-v1-6ff0ab18…`
  474427 B). DSM (float32, 1-band): 577639-698270 B. Download lane untouched
  (bytes from receipts; no `/file` GETs performed).
- Exact full-viewport cover of the 1022x915 source at <=512 px (cell-edge exact):
  4 windows — 512x512 (262144 px) + 510x512 (261120) + 512x403 (206336) +
  510x403 (205530) = 935130 px. Measured o21 cover (L1-L4): 2265338 B (~2.16 MiB).
- Whole-source single request (935130 px > 262144 cap): `422
  OUTPUT_PIXEL_LIMIT_EXCEEDED` in 4 ms, no job, zero worker cost (`jobs.py:990-992`).
  The per-output cap — not bytes, retries, or queue — is what stops whole-source
  reads, so tiling is mandatory, not optional.

## Implications for open decision #2 and acceptance criteria 2-3

- Budget N: the lane sustains exactly 2 concurrent PREPAREs per organization; a
  3rd concurrent issue is a fast `429`, never a waiting slot. A full 1022x915
  viewport needs exactly 4 windows (2 waves of 2). Measured wave cost ~6 s on an
  idle lane, so full-cover wall time ~= 12 s plus 429-retry pacing when the lane
  is shared.
- Queue ordering: there is no server-side FIFO beyond the 2 active slots — order
  is whatever the client issues first plus ~5 s pickup ticks. A client that wants
  ordering (e.g. center tile first) must sequence its own issues 2-at-a-time.
- Cache/idempotency: stable keys per (assetRef, window, purpose) make re-entry
  free (5 ms replay); anything else re-pays ~6 s per window. `outputSha256`
  equality across keys proves content-addressable dedup is viable client-side.

## Measured (client-usable) vs recommended (opinion, not authority)

Measured: single-window total 5.4-5.9 s (10/11; 1 outlier 10.7 s); exec ~0.8 s;
pickup ~5 s; 2 concurrent max; 429-retryable beyond; replay 5 ms; conflict 409;
whole-source 422 in 4 ms; 4 windows / ~2.2 MiB per full ortho viewport.
Recommended (not policy): per interaction issue at most 2 concurrent PREPAREs;
budget ~15 s per full-viewport cover (2 waves + pickup jitter + one 429 retry);
key windows stably so viewport re-entry hits `200` replays; back off (not spin)
on `429`; verify cover completeness by `outputSha256`, never by assuming order.

## Not measured (and why)

- Steady-state queue deeper than 1: unreachable — the lane 429s instead of
  queueing. Multi-client contention for the 2 slots: single-actor run only.
- Download-lane concurrency (`maxActiveDownloadsPerOrganization 4`): no `/file`
  GETs by design (kept load to PREPARE only).
- L3 10.7 s outlier cause: would need live journal/worker forensics — out of scope.
- Retry path (`maxRetries 3`), retention/expiry (24 h), lease renewal (60 s):
  no forced failures, no 24 h wait.
- Synthetic EPSG:5186 pair: skipped to keep load modest; same code path
  (`_plan` + cap + 2-active) governs it, but no bytes measured.
- Display/LOD mapping itself (tile pyramid, LOD selection, mask/NoData rendering):
  delivery-lane only; no viewer work done.
