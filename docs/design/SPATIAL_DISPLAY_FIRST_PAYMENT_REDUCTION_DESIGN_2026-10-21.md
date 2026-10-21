# First-payment reduction on the spatial display path — design + feasibility (not implemented)

Date: 2026-10-21. Base: main `df9a86e7`.
Status: **DESIGN ONLY, Human-directed bounded unit.** No source/contract/runtime/policy/worker
change, no commits, no servers, no new Core jobs, no shared-host action, no inspection launch,
no ledger/`.opencode` edits, no dashboard work. Nothing here authorizes implementation; each
viable item names its owner and approval dependency (§5). This document is subordinate to all
product authority and changes none of it.

## Authority and precedence

Constitution → Decision Ledger → PRD §1.1.2 → `contracts/` → ADR-KSI-036/037/038/039 →
display/LOD proposal (`docs/design/SPATIAL_DATA_DISPLAY_LOD_CONTRACT_PROPOSAL_2026-10-21.md`) →
persistent-cache + measurement plan
(`docs/design/SPATIAL_DISPLAY_PERSISTENT_CACHE_AND_MEASUREMENT_PLAN_2026-10-21.md`, cited as
"cache plan") → registration/purpose-split contract
(`docs/design/REGISTRATION_ACCEPTANCE_AND_PURPOSE_SPLIT_CONTRACT_2026-10-21.md`, cited as
"purpose-split contract") → this document. Normative invariants:
`docs/product/DOMAIN_INVARIANTS.md` (INV-020/024/040/050/051/053/054/055/060/061 in scope).

## Measured facts (evidence, not proposal)

From `docs/audit/SPATIAL_DISPLAY_CACHE_MEASUREMENT_EVIDENCE_2026-10-21.md` (n=4 fresh windows,
idle lane, same 1022×915 fixture as GAP-06) and
`docs/audit/GAP-06_SPATIAL_PREPARE_LOAD_EVIDENCE_2026-10-21.md`:

- Fresh full 1022×915 cover (4 windows) = **~23 s wall** (issue wave → 4th COMPLETED,
  client-observed 22.9 s). This **supersedes** the ~12 s figure in the cache plan §0.2 and
  the LOD proposal §4, which assumed parallel pickup.
- Attribution (MEASURED): POST issue 0.03–0.05 s; WORKER PICKUP first-of-pair 4.6–5.1 s,
  second-of-pair 10.6–10.8 s; execution 0.5–1.0 s/window; byte GET 0.11–0.16 s/window;
  decode ~3 ms (PIL proxy); paint ms-scale (numpy proxy).
- Re-visits are already fast: full re-GET+verify+decode of prepared windows = **0.691 s**;
  same-key + identical-body replay POST = **200, 7 ms, same job**. The user's cost is the
  FIRST payment, not revisits.
- T2 byte tier removes nothing on per-visit latency (bytes already stored as owned outputs);
  its win is **durability past the 24 h `retentionSeconds` cleanup**. The only sub-100 ms
  path is the session tier of decoded pixels, which already exists (`MosaicPaintCache`).
- 3-wide issue → 2×201 + 1×429 in 52 ms; the server has NO queue, so a deeper client queue
  changes nothing user-visible.
- The ~5 s serial tick is the WORKER's own loop:
  `services/processing-controller/src/ksi_processing_controller/spatial_data_runner.py:67–92`
  performs one `run_once` (ONE bounded poll/launch), closes the sandbox, then
  `stop.wait(config.poll_interval_seconds)` before the next poll.
- The Core admission limit is `maxActiveJobsPerOrganization` (2 in the live signed policy),
  enforced at `services/core/src/ksi_core/domains/external/delivery/jobs.py:1044–1048`
  (fast retryable 429); the sweep at `:860–865` is unreachable on this route while the
  cap is 2. Signed policy carries `maxActiveJobsPerOrganization` 2, `maxQueueDepth` 8,
  `maxPendingRecords` 8, `maxDeadlineSeconds` 600, `leaseSeconds` 60.

Human's stage-1 goal (binding): make the FIRST PAYMENT feel natural — measured in the real
product (hit rate, time to first valid pixel, stabilise time, 429 rate, memory), not test
counts. A persistent cache was chosen as the stage-1 item, but measurement shows its real
win is DURABILITY (surviving retention expiry) rather than latency, so this unit designs
the honest stage-1 package around the FIRST payment while keeping the cache's durability win.

---

## 1. WORKER PARALLELISM — options, assessment, verdict

### 1.1 What the code does today (verified, not re-derived)

- Runner loop (`spatial_data_runner.py:67–92`): each turn calls
  `run_once(core, sandbox, …)` from
  `services/processing-controller/src/ksi_processing_controller/spatial_data_worker.py:278–305`,
  which does `core.pending(limit=1)`, validates the frozen job digest, checks
  `heartbeat_interval_millis / 1000 < job.policy.lease_seconds / 3` (`:300–304`), leases
  exactly one job (`:305`), then runs source-stage → `sandbox.prepare` → receipt-verify →
  upload. Back in the runner, the sandbox is closed (`:89`) and the loop sleeps
  `poll_interval_seconds` (`:92`) before the next poll.
- Lease model (`jobs.py:1339–1398`): one lease per job, fenced by
  `(worker_principal_id, worker_instance_id, acquisition_key_hash)`; re-lease by a
  different holder while `now < old.lease_until` is `FENCE_CONFLICT` (`:1364–1371`).
  Lease length is `lease_seconds` (60 s live); the worker config requires
  `heartbeat_interval_millis / 1000 < lease_seconds / 3`
  (`spatial_data_worker_config.py:270`) and
  `request_timeout_seconds ≤ lease_seconds / 2` (`:269`).
- Authority pinning: the runner builds ONE `SpatialDataSandbox` around ONE
  `PinnedSpatialDataLauncher` verified against the signed policy+runtime digests
  (`spatial_data_runner.py:39–46`), and re-verifies material plus config equality every
  turn (`current_authority`, `:48–52`). A failed reap/pending late launch stops polling
  rather than replacing the owner (`:87–88`).
- Admission: at most 2 actives per organization (`jobs.py:1044–1048`); the Core-side
  `lease()` itself places NO count limit — the 2-slot shape is enforced at ISSUE time,
  not at lease time.

### 1.2 Candidate options

**Option P-A — N concurrent `run_once` leases inside one tick (one process, N sandboxes).**
The worker polls `pending(limit=N)`, leases up to N jobs, and runs N preparations
concurrently, each in its own sandbox instance + its own owner-private workspace
(`TemporaryDirectory(prefix=".ksi-data-", dir=workspace_root)` per `run_once`,
`spatial_data_worker.py:326`; `require_owner_private_directory`, `:319–321`).

Assessment against owner contracts:

- Admission: still capped at 2 actives per organization unless the policy changes —
  P-A alone CANNOT serve more than 2 concurrent jobs on the live lane. It only converts
  serial pickup (~5 s + ~10.7 s) into parallel pickup (~5 s + exec overlap).
- Resource envelope (`packages/event-contracts/src/ksi_event_contracts/spatial_data_authority.py:32–77`):
  the envelope (`max_input_bytes/max_streamed_bytes/max_output_bytes/max_pixels`,
  `max_deadline_seconds`) plus the derived floor `required = 2 * env.max_input_bytes +
  max_output_bytes * (…)` (`:77`) is sized per preparation. N concurrent preparations
  need N× the proven workspace/memory/byte budget or a re-proven shared envelope —
  a resource-owner decision with replay/load evidence, not an implementation detail.
- Containment (`spatial_data_sandbox.py`, `spatial_data_launcher`): the launcher requires
  owner-pinned namespace/mount proof and rechecks kernel process state before sending a
  job. N concurrent children need N independent containment proofs, N namespace/mount
  observations, and N private workspaces with no shared writable parent beyond the
  owner-private root. The current single-`SpatialDataSandbox`-per-turn structure
  (`spatial_data_runner.py:41–46,89`) does not provide this; adding it is a
  containment-owner change with its own verification evidence.
- Lease/heartbeat: N concurrent guards each need `heartbeat < lease_seconds / 3`
  (`spatial_data_worker.py:300–304`); heartbeats must stay per-attempt fenced
  (`FENCE_CONFLICT`, `jobs.py:1364–1371`) so one stalled preparation cannot fence or
  starve another's lease.
- Authority pinning: all N preparations must run under the SAME pinned
  policy/runtime/worker-instance authority (`current_authority`,
  `spatial_data_runner.py:48–52`; `instance_id != activation.worker_instance_id →
  ACTIVATION_UNAVAILABLE`, `jobs.py:1351–1352`). Any design that relaxes the pinning
  (different policy per lane, unpinned second sandbox) makes the worker a different,
  less-bound owner — explicitly FORBIDDEN by this unit's constraints.

**Option P-B — bounded worker-side window set (claim up to K pendings per tick, run sequentially).**
The worker leases up to K jobs per tick but prepares them one at a time in the existing
single sandbox (no concurrency inside containment).

Assessment: containment/resource impact is minimal (same sandbox discipline, same peak
footprint), but the user-visible win is ALSO minimal — sequential execution still pays
~5 s pickup per window plus K× exec, i.e. it smooths polling, not latency. It does not
change the 2-active admission cap and does not need a policy change, but it also does not
move the ~23 s number materially. Only value: fewer idle ticks when the lane is shared.

**Option P-C — rely on the Core-side lease (no worker change; "the lane already allows 2 actives").**
Correct as far as it goes — Core CAN hold 2 RUNNING jobs — but the measured serialization
is in the WORKER's poll loop, not in Core's lease. P-C changes nothing and the ~23 s
stands. It is the honest baseline, not a lever.

### 1.3 What a change here touches, and whose approval it needs

| Change | Touches | Owner / approval |
|---|---|---|
| Any N>1 concurrent preparation (P-A) | `spatial_data_runner.py` loop, `spatial_data_worker.py run_once`, `spatial_data_sandbox.py` + launcher, worker config (`poll_interval_seconds`, `heartbeat_interval_millis`), resource envelope values | Worker owner + containment/security owner (new containment proof per child) + policy owner (envelope re-proof). Independent review recommended (high-impact runtime change). |
| Raising `maxActiveJobsPerOrganization` above 2 | Signed delivery policy value; enforcement at `jobs.py:1044–1048` unchanged in shape | Policy owner + Core delivery owner. Multi-tenant impact sign-off required (see §1.4). |
| Per-principal or per-tenant cap instead of organization-wide | NEW policy field(s) + admission predicate in `jobs.py` + schema in `packages/event-contracts` | Event-contracts owner (schema) + Core delivery owner (enforcement) + policy owner (rollout). This is a CONTRACT change, not a tuning knob. |
| Shortening `poll_interval_seconds` | Worker config bound (`poll_interval_seconds ≤ resource_envelope.max_deadline_seconds`, `spatial_data_worker_config.py:271`) | Worker owner; bounded win (shortening the ~5 s tick helps only the idle-poll floor; under P-B the floor is still one poll per window). |

### 1.4 The organization-wide limit, stated plainly

`maxActiveJobsPerOrganization` is an **ORGANIZATION-wide** limit: raising it from 2 to N
gives every tenant's principals N concurrent slots against the same worker pool and the
same resource envelope. It widens aggregate load, noisy-neighbour exposure, and the
containment concurrency surface for ALL tenants at once — it is not a per-team speedup.
If the owner prefers not to widen the organization-wide limit, the alternative is a
**per-principal (or per-tenant) cap alongside the organization cap**: e.g. keep
`maxActiveJobsPerOrganization` as the global backstop and add
`maxActiveJobsPerPrincipal` (or per-tenant) so one site's first-payment burst cannot
consume the whole organization lane. That alternative is a new signed-policy field with
its own admission check — a contract + Core change requiring event-contracts, Core
delivery, and policy-owner approval — and its numbers must come from multi-tenant load
evidence that does not exist today (GAP-06 was single-actor).

### 1.5 Verdict — worker parallelism

- **P-C (no change): viable today, wins nothing.** Baseline for measurement.
- **P-B (bounded window set, sequential): viable WITHOUT policy/contract change, but
  NOT a first-payment fix** — worth at most one idle-tick saving per window. May be
  proposed as worker hygiene, never as the stage-1 lever.
- **P-A (true concurrent preparation): the only parallelism lever that moves the ~23 s,
  and it is NOT viable inside the existing contract.** It needs worker + containment +
  resource-envelope changes AND (to exceed 2 concurrent) a policy decision on the
  organization-wide limit or a new per-principal/per-tenant cap. Ceiling even if fully
  approved: pickup serialization (~21–22 s of the ~23 s) collapses to ~5–6 s + overlapped
  exec — cold cover ≈ 6–8 s on an idle lane, NOT sub-second. No implementation is
  authorized by this document.

---

## 2. LOD AS THE FIRST-PAYMENT FIX — design and verdict

### 2.1 The idea (why it matters more than parallelism)

With the LOD contract's screen-resolution-driven selection, a whole-site view does NOT
need 4 native 512px windows. A coarse overview (e.g. whole 1022×915 extent downsampled
≈2× → ~511×458 px ≈ 234 kpx, UNDER the 262144 px `max_output_pixels` cap,
`jobs.py:990–992`) could satisfy the first view in **ONE preparation** instead of four —
cutting the first payment from ~23 s toward one pickup cycle (~5–6 s) with NO worker
concurrency change and NO policy change. A zoomed view then requests only the
high-resolution native windows actually visible. This is the structurally cheapest
first-payment lever on the table.

### 2.2 How the first view is produced under the EXISTING contract

- "The whole site" at coarse level = the viewport's native-grid bounds computed EXACTLY
  as today (requested bounds → `plan_external_native_window` floor/ceil to exact native
  cell edges, `packages/geo-spatial/src/ksi_geo_spatial/external_native_window_geometry.py:60–94`),
  expanded ONCE to cell edges, then mapped to the FIXED tiling origin at the chosen LOD
  level (LOD proposal §3–§4). Same (viewport, source, table-version) MUST resolve to the
  same tile set — determinism is a correctness requirement, not an optimization.
- The LOD/style/validity pins are ALREADY part of `DisplayDerivativeV1`
  (`packages/event-contracts/src/ksi_event_contracts/spatial_data_display.py:84–112`
  `DisplayLodV1/DisplayStyleV1/DisplayValidityV1`, bound into `derivativeId` at
  `:190–208`). A coarse tile and a native tile of the same ground area are DIFFERENT
  derivatives by construction (different `lod` pins → different `derivativeId`) — the
  identity layer already supports this; nothing new is needed there.
- The display derivative stays a pure function of (source + parameters), per
  `spatial_data_display.py:12–15` and LOD proposal §2. The overview must record its full
  pins: source pins, window pins, `lod` (level + `lod_table_version` + `resampling_kernel_id`
  + `target_metres_per_pixel`), style/validity pins, registration pin (or explicit NONE),
  permission pins, provenance pins.

### 2.3 Is a downsampled overview a permitted window or a new artifact kind?

**Under the EXISTING contract it is a NEW ARTIFACT KIND (or a new preparation mode),
not a permitted window.** Reasons, cited:

- The worker's contract is to crop the EXACT native grid: `sandbox.prepare` output is
  verified by `_receipt_matches` (`spatial_data_worker.py:264–275`), which requires
  `receipt.width * receipt.height <= job.policy.max_output_pixels` AND
  `receipt.output_size_bytes <= job.policy.max_output_bytes` for a NATIVE crop. Any
  resampling (mean/nearest/kernel) inside containment is a NEW transformation requiring
  its own contract, profile digest, and evidence — ADR-KSI-037 D5 forbids silent
  correction/resampling, and the LOD proposal §3–§4 claims only edge-to-edge placement
  of verified native rectangles, explicitly NOT resampling.
- Therefore the "one coarse tile for the whole site" needs: (a) a pinned kernel
  registry (which kernel for ortho vs DSM vs masks), (b) a preparation path that applies
  it under containment with receipt binding, and (c) a Core admission for that path.
  All three are GAP-03 territory.

### 2.4 What needs the still-open GAP-03 LOD table

Everything numeric and semantic about the pyramid: level definitions (is level k
`2^k × 2^k` aggregation per LOD proposal §4, or another factor?), per-level thresholds
as a function `level = f(viewportMetresPerPixel, devicePixelRatio, sourceGSD)` against a
PINNED table version, kernel per data kind (mean for DSM elevation? nearest for masks?
— owner decision, LOD proposal §8-item-1), DSM-vs-ortho rule differences, and the
valid-area/mask behaviour at coarse levels. The METHOD (screen-required resolution vs
source resolution, never a fixed zoom factor) is already decided by Human direction and
restated in the cache plan §1.4 — but every number, kernel, and table row awaits GAP-03
owner determination plus benchmark evidence. **No LOD level, threshold, or kernel may be
implemented from this document.**

### 2.5 Honest labelling (normative for any future LOD first view)

- A coarse overview is labelled as a stated-LOD display assembly, e.g.
  "개요 보기 · LOD k (원본 대비 1/N) · [lod_table_version] — 정밀 판독용이 아님".
  It is NEVER labelled complete, native, or measurement-grade.
- Zooming past the overview's stated resolution MUST show the named waiting state for
  the native windows (existing `mosaicWaitingCopy(plan, "preparing")`,
  `apps/dashboard/src/lib/spatial-display-mosaic.ts:83–91`), never a stretched upscale
  presented as data (INV-040: no synthetic fill).
- The three states stay separate: `DisplaySpatialViewV1` (`AVAILABLE | NOT_READY |
  UNRENDERABLE`, `spatial_data_display.py:220–225`) is a representation fact only; it
  never restates validation suitability or audit integrity. No composite
  ready/status/verified flag is introduced (constraint).

### 2.6 Verdict — LOD as the first-payment fix

- **Design-viable, contract-blocked.** The identity layer (`DisplayDerivativeV1` + LOD
  pins) and the labelling discipline already exist; the preparation path (resampling
  under containment + kernel registry + GAP-03 table) does NOT. Needs event-contracts
  owner (kernel/table schema), Core delivery owner (admission + receipt binding), worker
  owner (contained resampling), and GAP-03 owner sign-off.
- **Biggest honest first-payment win IF approved:** whole-site first view in ~1 pickup
  cycle (~5–6 s measured basis) instead of ~23 s, with zero concurrency or policy change.
  Still NOT sub-second — no "instant" claim is available for the first payment.

---

## 3. PROGRESSIVE DELIVERY — how the ~23 s should FEEL

The mosaic ALREADY paints windows as they arrive (first valid pixel ≈ 5.8 s on a fresh
cover: first COMPLETED 5.62 s + re-fetch pipeline ~0.14 s). This lever needs no contract
change — it is presentation + measurement discipline.

### 3.1 What the operator sees (uses existing states only)

- Cell states are the existing `MosaicCellPhase = "waiting" | "painted" | "gap"`
  (`spatial-display-mosaic.ts:59`) with the existing named waiting copy
  (`mosaicWaitingCopy`, `:83–91`) and typed gaps (`DisplayGapReason`,
  `spatial-display-composition.ts:29–36`). No new state is introduced.
- Issue order = centre/visible tiles first (client-sequenced; there is no server FIFO —
  GAP-06 §"Queue ordering"). Each tile paints the moment its bytes pass the size+SHA
  gate (`spatial-data-preview.ts:29–53`); already-issued actives run to completion even
  if the viewport moved (cache plan §4-rule-3: a finished tile is a future pan-back hit).
- Progress copy rule: **a partial cover is ALWAYS labelled partial** — e.g.
  "부분 보기 · 2/4 창 그림 · 나머지는 준비 중 (빈칸을 메우거나 늘이지 않음)".
  A partial mosaic is NEVER labelled complete, and waiting cells are NEVER filled with
  stretched neighbours, low-res placeholders presented as data, or synthetic fills
  (INV-040). Off-screen queue drop keeps its hysteresis margin (owner to fix; LOD
  proposal §4 proposes 0.5 viewport) so a small pan does not thrash the queue.

### 3.2 Stabilise time as a measured metric

- M3 (time to stabilise after a pan) is reported per the cache plan §5.1: viewport-commit
  → full covering set resolved (every tile painted-verified or an explicit named gap,
  scheduler snapshot empty). Cold full cover target: MEASURED 22.9–23 s baseline; any
  improvement claim needs a re-run of the R1–R5 reference sequence (§5.3 below), not a
  code-diff argument.
- First-valid-pixel (M2) cold stays ≈ 6 s report-only (bounds the lane, not the cache);
  warm ≤ 1 s measured path exists today (0.691 s re-fetch) with a ≤ 100 ms benchmark
  target for the T1 path (INFERRED — needs browser-heap evidence, §5.3).

---

## 4. DURABILITY — the persistent cache's real scope (no new design, restated for this package)

The cache plan (`docs/design/SPATIAL_DISPLAY_PERSISTENT_CACHE_AND_MEASUREMENT_PLAN_2026-10-21.md`)
is the authority for cache shape; this unit restates ONLY the scope the stage-1 package
depends on, because measurement re-anchored its justification from latency to durability:

- **Cached artifact:** a display derivative's prepared bytes at a stated tile size + its
  full `DisplayDerivativeV1` pins (cache plan §1.1); whole-tile-bytes representation
  preserving seam-exactness (§1.4). No composed viewports, no blended seams, no
  resampled overviews in the cache.
- **Key with rights context:** `DisplayCacheKeyV1` = content (`derivativeId`) + explicit
  rights repeats (`grantDigest, policyDigest, purpose, preparedForPrincipalHash,
  beneficiaryPrincipalId, organizationId, allowedBoundsDigest, observedCrsDigest`) +
  currency (`grantRevision, policyRevision, activationDigest-or-epoch`) + scope
  (`tileSize, lodTableVersion, kernelId`) (cache plan §1.3). Content-hash match is
  necessary, never sufficient.
- **8-step live re-check with the hash LAST** (cache plan §3): scope → grant-live →
  not-revoked → purpose → requester-ownership → expiry/retention → policy/activation
  currency → receipt integrity. Any failure is fail-closed with the existing truthful
  copy (`GRANT_EXPIRED`, `REVOKED`, `PURPOSE_MISMATCH`, `FOREIGN_PRINCIPAL`,
  `RECEIPT_CHANGED` per `spatial-display-cache.ts:50–55`).
- **Per-principal/per-purpose budgets + append-only tile-read audit** (purpose-split
  contract §B7–§B8): tile reads meter against a display budget in source-pixel/byte
  terms; display/download budgets never pool; every tile GET writes the audit row
  (grant digest, derivative id, window, principal hash, timestamp). Numeric F,
  rate numbers, harvesting threshold, and cache-hit counting weight are OPEN —
  GAP-05 risk assessment with real exploration traces (purpose-split §B10-item-3).
- **Operational component:** EITHER a Core-owned store inside the Core deployment
  boundary OR a separately deployed display-cache service fronted by Core authorization
  (Core always owns the §3 decision). The cache plan §6.3 authorizes NEITHER — the
  placement + technology + cleanup-loop ownership + `retention_seconds`-vs-HTTP-TTL
  labelling need separate owner approval with dependency/build/CI/replay/deployment/
  rollback evidence. **This document authorizes no deployment.**

---

## 5. STAGE-1 PACKAGE + MEASURED ACCEPTANCE

### 5.1 The concrete set of changes for stage 1, in dependency order

Ordered so each item is useful even if later items are refused. Every item needs its
listed approval; numeric targets in §5.2 are to-be-set-by-benchmark unless a measured
basis is cited.

| # | Item | Owner | Approval dependency | Moves which number |
|---|---|---|---|---|
| S1 | **Progressive-first-view discipline** (centre-first issue order, paint-on-verify, partial-cover labelling per §3.1, off-screen drop with pinned hysteresis) using EXISTING states/copy only | Dashboard (consumer) | Dashboard owner; no contract/policy change | M2 cold ≈ 6 s reported honestly; M3 measured, not yet reduced |
| S2 | **T1 session tier conformance** (key extension to §1.3 pins, re-validate-before-paint, LRU/size cap + `evict/clear` on rights failure, M5 gauge) — keeps `MosaicPaintCache` + rights-recheck cache, adds the missing cap | Dashboard (consumer) + event-contracts (key schema sign-off) | Event-contracts owner for key fields; dashboard owner for eviction behaviour. Cap NUMBER by benchmark (§5.2-M5), not invented here | M2 warm toward ≤ 100 ms (benchmark target); M5 bounded |
| S3 | **T2 persistent tier for durability** (cache plan §2-T2 + §3 re-check + §6.2 Core/Console split), scoped to post-retention survival | Core delivery (store + serve-time §3 + retention/cleanup + budgets) + event-contracts (record schemas) + dashboard (cache-first wiring) | O-1..O-8 of the cache plan §6.4; GAP-05 review for budgets (§B10); placement decision (§4 above). NO deployment authorized by this document | Post-retention revisit avoids re-paying ~23 s (durability win); per-visit latency UNCHANGED (~0.7 s re-fetch path) |
| S4 | **Reference-run harness + M1–M5 instrumentation** (counters/marks/gauges only, no semantics change; versioned R1–R5 sequence) | Dashboard (client marks) + Core (serve-side log joins) | Owner agreement on sequence version + lane-condition labelling | Makes every other claim falsifiable |
| S5 | **LOD-overview preparation path** (kernel registry + GAP-03 table + contained resampling + receipt binding, §2) — the actual first-payment reduction | Event-contracts + Core delivery + worker + GAP-03 owner | GAP-03 table/kernels; containment proof for resampling; profile-digest binding. Largest approval surface; scheduled AFTER S1–S4 deliver honesty | Cold whole-site first view ~5–6 s (measured-basis projection, NOT a criterion until re-measured) |
| S6 | **Worker parallelism (P-A) and/or admission re-tuning** (raise org-wide cap or add per-principal cap, §1) — ONLY if S5 proves insufficient AND multi-tenant evidence exists | Worker + containment + policy + Core delivery | Full §1.3 approval table + multi-tenant load evidence | Cold cover 6–8 s ceiling (measured-basis projection) |

Explicitly NOT in stage 1: any rights-bypass relaxation (§3 is the floor); any shared
cross-principal cache (refused under the current grant model, cache plan §6.2-CDN rule);
any new endpoint presented as existing; any composite ready/status/verified flag.

### 5.2 Acceptance form (M1–M5, R1–R5)

Method reuses the cache plan §5.3 reference exploration run idea (versioned pan/zoom
sequence; baseline recorded BEFORE the candidate ships):

- **R1 — cold cover:** whole-site extent on the 1022×915 fixture (or production sample);
  wait for full stabilisation. Establishes the cold baseline.
- **R2 — identical revisit:** reload/re-enter the same viewport. Expectation: ~100% hit
  rate, zero new PREPAREs.
- **R3 — pan walk:** four adjacent-viewport pans (~50% overlap each), settling each;
  pan back to R1. Expectation: overlapping tiles hit, fringe tiles miss-then-prepare.
- **R4 — zoom in/out:** whole-site → 2× centre zoom → back out. Stage-1 expectation:
  same tiles re-served, no duplication/leak/destabilisation (resolution-vs-source LOD
  behaviour is S5/stage-2, NOT scored here).
- **R5 — rights flip:** revoke/expire the grant, re-request R1. Expectation: zero tiles
  from either tier; truthful revocation/expiry UI; other principals unaffected.

| Metric | Definition (cache plan §5.1, unchanged) | Pass form (numbers: MEASURED basis or TBD-by-benchmark) |
|---|---|---|
| M1 hit rate | served-from-T1-or-T2 / requested tiles per run (T1, T2, overall split); zero new PREPAREs on R2 | PASS when R2 reaches the benchmark-set rate with zero new PREPAREs. Basis: re-fetch path already pays zero new PREPAREs within retention (MEASURED). |
| M2 time to first valid pixel | viewport-commit → first painted receipt-verified tile | Warm (all-hit) ≤ 1 s PASS on measured basis (0.691 s re-fetch MEASURED; T1 ≤ 100 ms is a BENCHMARK TARGET, needs browser evidence). Cold ≈ 6 s REPORT-ONLY (first COMPLETED 5.62 s + ~0.14 s pipeline MEASURED) — bounds the lane, not the cache. |
| M3 time to stabilise | viewport-commit → covering set resolved (painted-verified or explicit named gap, scheduler empty) | Cold full cover ≤ 25 s PASS on measured basis (22.9 s MEASURED idle lane; 25 s adds pickup jitter headroom). Warm ≤ 1 s (BENCHMARK TARGET). No silent fallbacks. |
| M4 429 rate | 429s / PREPARE issues per run; retryable→success vs →FAILED split | PASS when R1–R4 under 2-slot discipline issue zero construction-429s; contention 429s bounded-retry to success; FAILED-due-to-429 = 0 (MEASURED behaviour: 33% under 3-wide contention, 0 FAILED). |
| M5 memory | Browser: T1 residency + heap delta; server: T2 residency per principal/purpose | PASS when the scripted run completes with T1 under its owner-fixed cap (eviction, not crash) and T2 bounded per principal/purpose. Cap numbers TBD-by-benchmark (basis: full cover ≈ 7.57 MiB session / 2.16 MiB transfer MEASURED — INFERRED heap ceiling, needs browser measurement). |

Every run logs M1–M5 + lane conditions + fixture identity + sequence version, and the
three-state separation + seam-exactness + no-synthetic-fill invariant checks
(cache plan §5.1 footer). The L3-type 10.7 s outlier class (GAP-06) is REPORTED, not
deleted, until a cause is found.

---

## 6. WHAT IS NOT VIABLE / NOT CLAIMED (candid)

1. **Changing `maxActiveJobsPerOrganization` organization-wide as a "quick fix."**
   NOT viable inside this unit: it widens concurrency for every tenant ( §1.4), needs
   policy-owner + multi-tenant sign-off, and still leaves serial worker pickup unless
   P-A ships with it. No number is proposed here.
2. **Any re-preparation of a window whose source changed, served from cache.**
   NOT viable: subject drift refuses with `REFUSE_SUBJECT_DRIFT`-class semantics
   (purpose-split §A2.2-check-1); a new revision needs re-attestation/re-preparation,
   never a cache hit.
3. **Any caching that skips a rights re-check (hash-equality-as-authority).**
   NOT viable, not specifiable as a relaxation: the 8-step §3 sequence with hash LAST
   is the floor. If re-checks prove slow, the fix is faster checks (e.g. owner-approved
   local revocation-index replica with a freshness bound, cache plan O-4) — never
   skipped checks.
4. **Any "instant" first-payment claim.** NOT claimed: even the full S1–S6 package has a
   measured floor of one pickup cycle (~5–6 s) for a cold view on an idle lane; the
   honest stage-1 story is "first pixels ≈ 6 s, full cover ≈ 23 s → (S5) ≈ 6–8 s,
   revisits ≈ 0.7 s → ms, post-retention revisit without re-paying ~23 s".
5. **Shared cross-principal/edge caching, whole-source single requests, deeper client
   queues as a latency fix.** Refused or unreachable: shared cache refused under current
   grants (cache plan §6.2); whole-source single request is `422
   OUTPUT_PIXEL_LIMIT_EXCEEDED` in 4 ms by design (`jobs.py:990–992`, GAP-06 §4);
   server has no queue so deeper client queues only convert immediate-429-then-backoff
   into deferred-issue (measurement §4).
6. **Unmeasurable today:** multi-actor contention for the 2 slots; post-retention
   cross-session re-GET (needs 24 h wait / second device); in-browser `geotiff.js`
   decode and `putImageData` paint costs (proxies only); the L3-type pickup outlier
   cause (1/11 GAP-06, 0/4 this run); any numeric quota/TTL/cap/threshold (no load
   profile beyond single-actor runs — ADR-KSI-038 D4 forbids guessing).

---

## Handoff (for the parent session)

- **File created:** `docs/design/SPATIAL_DISPLAY_FIRST_PAYMENT_REDUCTION_DESIGN_2026-10-21.md`
  (this document). No other file touched; no commits; no servers; no new Core jobs.
- **Lever verdicts:** P-C baseline only; P-B viable but not a fix; P-A moves ~23 s →
  6–8 s ceiling but NOT viable inside existing contract (needs worker + containment +
  envelope + policy decision; org-wide widening affects every tenant — §1). LOD overview
  is the cheapest structural fix (~23 s → ~5–6 s, no concurrency/policy change) but
  contract-blocked: a downsampled overview is a NEW artifact kind needing kernel
  registry + GAP-03 table + contained resampling (§2). Progressive delivery is viable
  TODAY with existing states/copy — honesty lever, not a latency lever (§3). Durability
  (T2) survives retention expiry; removes nothing on per-visit latency (§4).
- **Recommended stage-1 package in dependency order:** S1 progressive discipline →
  S2 T1 conformance + cap → S3 T2 durability (placement decision separate, no
  deployment authorized) → S4 R1–R5 harness + M1–M5 gauges → S5 LOD-overview path
  (the real first-payment cut, largest approval surface) → S6 parallelism/admission
  only if S5 proves insufficient with multi-tenant evidence (§5.1).
- **Acceptance form:** R1–R5 reference runs + M1–M5 table with measured bases
  (M2 cold ≈ 6 s report-only; M3 cold ≤ 25 s; M4 zero FAILED-due-to-429; M1 R2 zero new
  PREPAREs) and benchmark targets explicitly marked TBD (M2 T1 ≤ 100 ms, M3 warm
  ≤ 1 s, all caps/quotas) (§5.2).
- **Candid undecidables:** org-wide vs per-principal cap numbers; all LOD table/kernel/
  threshold rows (GAP-03); budget F / rate / harvesting-threshold / hit-weight numbers
  (GAP-05 + traces); shared-cache threat model; multi-actor contention; post-retention
  behaviour; in-browser paint/decode costs; L3 outlier cause (§6-item-6).
