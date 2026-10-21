# Spatial display cache measurement evidence (measured 2026-10-21)

Bounded MEASUREMENT unit for the persistent-display-cache + scheduler-first
direction (`docs/design/SPATIAL_DISPLAY_PERSISTENT_CACHE_AND_MEASUREMENT_PLAN_2026-10-21.md`,
metrics M1–M5, reference run R1–R5). No product source/contract/runtime/policy/
worker change, no commits, no new Core jobs beyond 4 bounded windows of the
already-granted asset, no shared-host action, no inspection launch, no
policy/activation/grant change. Machine-readable artifact:
`docs/audit/display-cache-measurement-results-2026-10-21.json` (assembled from
the raw run files, not hand-transcribed).

- Lane: own Core `http://127.0.0.1:8074` (production factory), real contained worker.
- Window: 2026-10-21 ~07:00–07:15 UTC. Lane healthy throughout; no strain observed.
- Actor: `ps-admin` (file-read token, never printed); purpose `GENERAL_DATA_USE`.
- Asset: `ksa-v1-1ad55465…` (2021 Floreat ortho, 1022×915, EPSG:7850, 0.25 m, north-up).
- Cover: 4 bounded windows TL `[0,512,0,512]`, TR `[510,1022,0,512]`,
  BL `[0,512,403,915]`, BR `[510,1022,403,915]` (cell-edge exact, same as GAP-06).
- New jobs this run (all COMPLETED, requester-owned): `sdj-v1-5d50fdf1…` (TL),
  `sdj-v1-be08737d…` (TR), `sdj-v1-e5ecfbaa…` (BL), `sdj-v1-39b9fdd3…` (BR).
  Output SHAs are byte-identical to the GAP-06 receipts for the same windows
  (content-addressable re-execution confirmed a third time).
- Method note (candid): browser stages were NOT instrumented — no browser
  automation was launched. Stages (a)–(c) and receipts are real Core-lane
  timestamps (the same lane the Console BFF uses); (d) decode is a PIL/TIFF
  proxy for the browser's `geotiff.js` path
  (`spatial-data-preview.ts:230–300`); (e) paint/compose is a numpy proxy for
  `placeWindowPixels` (`spatial-display-mosaic.ts:184–213`) + canvas
  `putImageData` (`SiteMosaicViewport.tsx:446`). Everything browser-side is
  labelled INFERRED; everything lane-side is labelled MEASURED.

## 1. Stage attribution — one full 1022×915 cover, fresh keys (MEASURED lane-side)

Wave 1 issued 3 parallel (TL, TR, BL); wave 2 issued BL-retry + BR after a slot
freed. n=4 windows, idle lane.

| window | (a) POST issue | client→RUNNING | client→COMPLETED | server createdAt→preparedAt | bytes |
|---|---|---|---|---|---|
| TL | 0.038 s, 201 | 5.110 s | 5.617 s | 4.945 s | 474427 |
| TR | 0.049 s, 201 | 10.684 s | 11.697 s | 10.752 s | 637695 |
| BR | 0.030 s, 201 | 4.618 s | 5.639 s | 4.850 s | 626704 |
| BL | 0.048 s, 201 | 10.696 s | 11.202 s | 10.641 s | 526512 |

Derived split per window (MEASURED components, arithmetic joins labelled):

- (a) POST issue: 0.030–0.052 s (n=5 fresh 201s: 0.038/0.049/0.052-429/0.048/0.030).
- (b) queue/pickup wait: first-of-pair 4.6–5.1 s, second-of-pair 10.6–10.8 s.
  The two "concurrent" actives are picked up on SERIAL ~5 s worker ticks —
  the pair costs ~5 s + ~10.7 s, not 2×~5 s in parallel. Execution per window
  ≈ 0.5–1.0 s (client COMPLETED − RUNNING: TL 0.51, TR 1.01, BR 1.02, BL 0.51).
- (c) byte GET + SHA verify (re-visit path, §2): GET 0.11–0.16 s per window
  (TTFB ~0.10–0.14 s + transfer ~0.02 s for 474–638 KB); SHA-256 verify
  0.0002–0.0003 s. Transfer dominates (TTFB ≈ 99% of the re-read cost).
- (d) decode: PIL TIFF→RGBA proxy 0.003 s warmed (0.034 s cold-start outlier,
  first decode only). Browser `geotiff.js` cost INFERRED same order (ms).
- (e) paint: numpy 1022×915 RGBA compose 0.91 ms (proxy for row-copy
  `placeWindowPixels`); canvas `putImageData` INFERRED ms-scale. NOT MEASURED
  in a browser.
- Time to first valid pixel (fresh cover): first window COMPLETED at 5.62 s +
  re-fetch pipeline ~0.14 s → ≈ 5.8 s to first paintable pixels (paint itself
  unmeasured, ms-scale proxy). All-4 painted ≈ 22.9 + 0.14 ≈ 23.0 s.
- CORRECTION to the brief: the "~12 s full cover" assumed parallel pickup.
  MEASURED full-cover wall (issue wave 1 → 4th COMPLETED, client-observed) =
  **22.9 s**, because the worker serves the 2 slots on serial ~5 s ticks
  (wave-of-2 ≈ 11.6 s; GAP-06's own C5 sample showed the same 10.77 s queue).
  The 12 s figure is superseded by this run for capacity reasoning.

## 2. Re-visit cost — windows already prepared, same principal (MEASURED, zero new jobs)

Two full re-read passes over the 4 GAP-06 cover jobs (ps-admin-owned, COMPLETED):

- Per window: GET 0.124–0.156 s, SHA verify 0.0002–0.0003 s with match=true,
  decode 0.003 s warmed. Run 1 vs run 2 identical within noise (no warm-up effect
  beyond first-decode import).
- 4-window re-fetch + verify + decode total: **0.691 s** (MEASURED, incl. 4 GETs).
- Same-key + identical-body replay POST (GAP-06 L1 key): **200, 7 ms, same job**
  — re-entry is free; no new work.
- What "이어 보기 채우기" / fresh page load costs TODAY for an already-prepared
  cover (same principal, live grant, within 24 h retention): ~0.7 s of
  re-GET (`cache: "no-store"` in `spatial-data-preview.ts`, and Core serves
  `Cache-Control: private, no-store` even on 200 byte delivery —
  `download_response.py:28`, `api.py:46–49`) + re-decode + re-paint, ZERO PREPAREs.
- What a persistent cache can realistically remove: a T1 decoded-pixel tier
  removes the ~0.7 s re-fetch/re-decode per full revisit (paint-ready slots,
  ~1 ms compose); a T2 byte tier removes NOTHING vs today's re-GET on latency
  (~0.13 s/window either way — bytes are already stored as owned outputs) and
  its real win is durability past the 24 h `retentionSeconds` cleanup, when
  re-preparation (~23 s) would otherwise be re-paid. The "12 s per reload"
  framing is wrong under stable-key discipline: reloads cost ~0.7 s, not ~23 s.
- Floor that remains: the actual preparation time (§1: ~23 s full cover) is
  paid once per retention window per principal regardless of any cache.

## 3. Cache-hit feasibility conclusion

- Pessimistic browser-cache case (re-read bytes, re-verify, re-decode):
  MEASURED ~0.14 s/window, DOMINATED by transfer TTFB (~0.11 s of it); SHA
  (~0.3 ms) and decode (~3 ms) are noise. Server-side byte store without
  re-prepare costs the same as today's re-GET — no latency win, only a
  durability win.
- Optimistic session-tier case (T1 decoded RGBA, rights re-checked): compose
  0.91 ms MEASURED proxy → full revisit paintable in low ms. This is the only
  sub-100 ms path and it already exists in-session (`MosaicPaintCache`); the
  missing piece is purely cross-session durability (T2), not speed.
- Recommendation (from measurement, not authority): T1 first, T2 for
  retention-survival; do not justify T2 on per-visit latency.

## 4. 429 rate and concurrency (MEASURED + code)

- 3-wide parallel issue on an idle lane: 2× 201 (38/49 ms) + 1× 429 in 52 ms
  → 33% 429 under 3-wide contention (n=3 issues, 1 run; consistent with GAP-06
  4/6 rejected). Wire shape is `{reason, retryable: true}` (`api.py:40–44`,
  `jobs.py:1044–1048`); my raw script read `code/retryable` top-level keys and
  recorded nulls — corrected here from code + GAP-06, no lane re-probe needed.
- Client behaviour per `spatial-display-scheduler.ts:182–367`: at most 2
  concurrent issues, same-key join, bounded 429 retry (default 1 s/2 s/4 s…
  max 3 retries), named "준비 중/순차 처리" states, off-screen queue drop.
  Observed discipline works: the 429'd BL retried in wave 2 completed normally;
  FAILED-due-to-429 = 0.
- A deeper client-side queue would NOT change user-visible time — the server
  has no queue (3rd issue is rejected, never parked), so queueing only converts
  immediate-429-then-backoff into deferred-issue; the serial ~5 s tick floor
  (§1) is unchanged. This directly supports the stage-1 goal: keep maxConcurrent
  2, retry bounded, show named waiting states. Note: default backoff (1–4 s) is
  shorter than the ~5 s pickup tick, so a first retry typically re-429s once
  before a slot frees — harmless but worth knowing when tuning (recommendation,
  not finding).

## 5. Memory (MEASURED proxy + arithmetic from code)

- Decoded RGBA per window: 512×512×4 = **1,048,576 B** (MEASURED `nbytes` ×4 windows).
- Composed 1022×915 RGBA canvas: **3,740,520 B** (MEASURED numpy buffer).
- Session tier holding full cover (4 decoded slots + canvas): **7,934,824 B
  ≈ 7.57 MiB** (MEASURED sum). Encoded transfer/store bytes full cover:
  **2,265,338 B ≈ 2.16 MiB** (MEASURED receipt sum).
- Code fact: `MosaicPaintCache` (`spatial-display-mosaic.ts:311–361`) is an
  unbounded `Map` — no LRU, no size cap; eviction is manual. Per-cover
  residency ~7.6 MiB means a dozen retained covers fit comfortably in a tab,
  but nothing enforces that bound. Practical ceiling for a session tier at this
  size: INFERRED (no browser heap measurement this run) — needs a cap + M5 gauge.

## 6. What a cache cannot fix (the irreducible floor)

Even a perfect cache never removes the first payment, and the first payment is
**~23 s per full 1022×915 cover per principal per retention window**, of which
~21–22 s is worker pickup (serial ~5 s ticks under the 2-slot lane) and ~2–4 s
is execution. Specifically persistent across any cache design: first-slot pickup
4.6–5.1 s; second-slot pickup 10.6–10.8 s; per-window exec 0.5–1.0 s. Any
stage-1 plan promising a cold full cover faster than ~23 s on this lane is
inconsistent with measurement. The cache's honest value: (i) pan-back/revisit
within session ≈ ms (T1, already exists); (ii) revisit within retention ≈ 0.7 s
re-fetch, reducible to ms by T1, unaffected by T2; (iii) post-retention revisit
avoids re-paying ~23 s (T2's only structural win).

## 7. Recommended M1–M5 targets (recommendations from THIS measurement, not authority)

- M1 hit rate: identical revisit (R2) → 100% T1 hits, 0 new PREPAREs
  (achievable in-session today; cross-session needs T2).
- M2 time-to-first-valid-pixel: warm full-cover revisit ≤ 1 s (MEASURED 0.7 s
  re-fetch path; T1 path should be ≤ 100 ms); cold first pixel ≈ 6 s
  report-only (bounds the lane, not the cache).
- M3 time-to-stabilise after pan: cold full cover ≤ 25 s idle lane (MEASURED
  22.9 s); warm ≤ 1 s; no silent fallbacks.
- M4 429 rate: scripted R1–R4 under 2-slot discipline → 0 429s by construction;
  any contention 429 bounded-retries to success; FAILED-due-to-429 = 0.
- M5 memory: T1 cap ≤ 16 slots (~16 MiB decoded @512 px) with eviction-not-crash;
  T2 growth bounded per principal/purpose; exact numbers owner-fixed after
  multi-cover runs. All numeric bounds need owner approval before becoming criteria.

## 8. What could NOT be measured (and why)

- Browser paint timing (`putImageData`/`drawImage`, `createImageBitmap`): no
  browser automation launched (bounded unit, no new runtime); ms-scale proxy only.
- In-browser `geotiff.js` decode cost: PIL proxy only; same-order INFERRED.
- Console end-to-end page timings (fresh page load, "이어 보기 채우기"
  interaction): the real Console UI was not driven; lane + code-path evidence only.
- Post-retention (24 h) re-visit and cross-session same-principal re-GET:
  would need a 24 h wait / second device — not done.
- Multi-actor contention for the 2 slots; OIDC-principal (`local-admin`)
  reads — ownership differences respected, not probed (their windows return
  404/403 to ps-admin per `downloads.py:100–106`; verified in code, not by probe).
- Download-lane concurrency (`maxActiveDownloadsPerOrganization 4`): untouched.
- The L3-type pickup outlier class (GAP-06 §48*): not observed this run
  (4/4 normal); cause still open.
