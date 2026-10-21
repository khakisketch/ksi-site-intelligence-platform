# Persistent display cache + measurement plan — design (not implemented)

Date: 2026-10-21. Base: main `88fbf266`.
Status: **PROPOSAL, Human-directed design.** No source/contract/runtime/policy/worker
change, no commits, no servers, no new Core jobs, no shared-host actions, no ledger/
`.opencode` edits. Nothing here authorizes implementation; owner approval and separate
contracts/tests are required before any code.

Why `docs/design/` and not `docs/audit/`: per repo routing (`REPOSITORY_STRUCTURE.md`,
`docs/DOCUMENT_STATUS.md`), this is the product-facing display-path design governing
cache identity, tiers, rights re-checks, scheduler integration and the measurement plan
that will fix its numbers — not an audit-ledger preservation/recovery record.

## Authority and precedence

Constitution → Decision Ledger → PRD §1.1.2 (SDP-REQ-01..08) → `contracts/` →
ADR-KSI-036/037/038/039 → this proposal (subordinate). It changes none of them.
Normative invariants: `docs/product/DOMAIN_INVARIANTS.md`
(INV-020/024/040/050/051/053/054/055/060/061 in scope).
Direct parent: the display/LOD contract proposal
`docs/design/SPATIAL_DATA_DISPLAY_LOD_CONTRACT_PROPOSAL_2026-10-21.md`
(§2 two identities, §3 addressing, §4 request behaviour, §6 permission+cache,
§8 contract surface, §9 acceptance). This document designs **only** its highest-priority
slice — persistent display cache + request scheduler first — plus the measurement plan
that sets its numbers. It does not redesign LOD pyramids, registration evidence,
epoch comparison, task-context restore, or historical lookup; those follow in the
Human's stated order (§0).

Human's binding direction (translated — implemented exactly):

- The four decisions are ADOPTED in principle; the implementation order is changed to:
  **(1) persistent display cache + request scheduler FIRST; (2) LOD pyramid and
  continuous exploration next; (3) registration-evidence acceptance and two-epoch
  comparison next; (4) task-context restore and historical result lookup last.**
  Audit recovery stays an independent track.
- LOD selection must be based on the **screen's required map resolution compared
  against the source resolution** (whole-site view → lower-resolution tiles first;
  zoom in → higher resolution), NOT a fixed zoom-factor threshold. 256px/512px are
  candidate **tile output sizes**, not LOD switch thresholds; start with 512px (the
  current cap) and let the benchmark decide.
- Cache structure: browser map → permission check + tile lookup → **PERSISTENT
  DISPLAY CACHE (hit → immediate)** → on miss → tile preparation job → verify →
  store → deliver.
- CRITICAL RULE: **data integrity and user access rights are separate.** A matching
  content hash does NOT mean the current requester may access it. Every cache hit
  must re-verify access rights, apply the rights scope and the expiry policy — for
  browser, CDN and server caches alike. Display-map rights must NOT imply original
  GeoTIFF, AI-training-corpus, or unbounded-download rights; display-tile reads,
  original download, analysis execution, external AI processing and dataset export
  are DIFFERENT acts, and repeated tile requests can reconstruct substantial source
  information, so unbounded tile retrieval under display rights needs its own risk
  assessment — while normal exploration must not be blocked by unnecessary approval
  steps (limits and policy must be designed around ordinary exploration behaviour).
- Until the cache service exists: respect the existing concurrency limit, deduplicate
  tile requests, cancel off-screen requests.
- Completion criteria are NOT test counts but **measured in the real product**:
  cache hit rate, time to first valid pixel, time to stabilise after a pan,
  429 occurrence rate, memory usage.

## 0. Established facts (verified in code, not re-derived)

1. The spatial-data lane is a bounded native-window PREPARE job: Core issues a job
   bound to a sealed+inspected subject, a grant, an activation and a signed policy;
   a contained worker crops the EXACT native grid; the result is a receipt with
   `outputSha256/outputSizeBytes/pixelWindow/actualBounds/observedCrsIdentifier`
   (`packages/event-contracts/src/ksi_event_contracts/spatial_data.py:352–367`), and
   the browser reads it through a same-session guarded GET with a size+SHA gate
   before decode (`apps/dashboard/src/lib/spatial-data-preview.ts:29–53`).
2. `max_output_pixels` is PER OUTPUT
   (`services/core/src/ksi_core/domains/external/delivery/jobs.py:991`,
   `job_projection.py:173,193`). Binding limits are request volume,
   `maxActiveJobsPerOrganization` 2, the EFFECTIVE request buffer (measured: zero —
   a 3rd parallel issue is a fast retryable 429, and `maxQueueDepth`/`maxPendingRecords`
   8 are unreachable on this route), latency and cache policy — NOT an
   exploration-area cap. Measured 2026-10-21
   (`docs/audit/GAP-06_SPATIAL_PREPARE_LOAD_EVIDENCE_2026-10-21.md` +
   `docs/audit/gap06-prepare-load-results-2026-10-21.json`): one 512×512 window
   5.4–5.9 s total (pickup ~4.6–5.1 s, exec ~0.77 s); 2 concurrent accepted, 3rd
   rejected `429 CONCURRENCY_LIMIT_EXCEEDED` retryable in 3–25 ms
   (`jobs.py:1044–1048`); full 1022×915 cover = 4 windows = 2 waves ≈ 12 s;
   ~15 s per-interaction budget recommended. Same body + same idempotency key =
   `200` same job in ~5 ms (`jobs.py:920–929`); fresh key + identical window =
   full re-execution, byte-identical output (dedup is the client's key discipline).
3. Window geometry is the authoritative native-grid rule:
   `packages/geo-spatial/src/ksi_geo_spatial/external_native_window_geometry.py`
   `_plan` (floor/ceil to exact native cell edges `:73–76`, must sit inside the
   source footprint `:69–72,77–85`).
4. Rights already bind a window's admissibility: `SpatialDataGrantV1` carries
   `asset_ref`, `site_id`, `work_area_id`, `allowed_bounds`,
   `observed_crs_digest`, `operations` (PREPARE/READ), `purposes`
   (GENERAL_DATA_USE/EXTERNAL_AI), `valid_from/valid_until`, `policy_digest`,
   `attribution`, `license_provenance_digest`
   (`packages/event-contracts/src/ksi_event_contracts/spatial_data_authority.py:85–108`),
   plus `SpatialDataRevocationV1` (`:128–136`). Reads are requester-owned: the same
   principal reads its own output; another principal is denied (404/403) —
   `services/core/src/ksi_core/domains/external/delivery/downloads.py:100–106,246–256`.
   The display contract builds on this grant/revocation model; no parallel rights
   system is proposed.
5. The display-derivative identity records exist as schema (no authority):
   `packages/event-contracts/src/ksi_event_contracts/spatial_data_display.py`
   (`DisplayDerivativeV1` content-addressed `:190–208`, `DisplayPermissionV1`
   `:172–179`, `DisplayProvenanceV1` `:181–188`, `DisplaySpatialViewV1`
   `:220–225` — representation fact ONLY), and the pure Core-side projection over
   existing jobs (`services/core/src/ksi_core/domains/external/delivery/display_derivative.py`
   — computes/verifies identity, adds no endpoint, cache, LOD table or mode).
6. The Console display path exists as pure functions + session-scoped stores:
   viewport resolution (`apps/dashboard/src/lib/spatial-display-viewport.ts`),
   2-slot scheduler (`spatial-display-scheduler.ts:204–211`, max concurrent 2,
   dedupe `stablePrepareKey` `:99–106`, idempotency `:112–120`, off-screen queue
   drop `:225–254`, bounded 429 retry `:325–343`), composition
   (`spatial-display-composition.ts`), mosaic + `MosaicPaintCache`
   (`spatial-display-mosaic.ts:311–361`), rights-recheck cache
   (`spatial-display-cache.ts:73–115`), mosaic viewport
   (`apps/dashboard/src/app/sites/[siteId]/SiteMosaicViewport.tsx`) on top of the
   temporary windowed viewer (`SiteWindowedPixelViewer.tsx:575`).
7. The three states stay separate: audit integrity / data-validation suitability /
   spatial viewability. No composite ready/status/verified flag.

## 1. Cache identity & keying (normative design)

### 1.1 Which artifact is cached — decision

**The cached artifact is a display derivative's prepared bytes: the current
native-window output at a stated tile size.** It is NOT the original GeoTIFF, NOT
a sealed source, and NOT an analysis result. Concretely: for a tile key (below),
the value is the exact bytes whose `outputSha256/outputSizeBytes` the receipt
already vouches for, plus the receipt pins needed to re-verify them. This follows
the parent contract §2: display derivatives are regenerable, cacheable, evictable;
source versions and old-result bindings are never touched by display caching.

Why not cache "the current native-window output" as an anonymous blob: without
the LOD/style/validity pins there is no way to tell two same-window renders apart
(DSM stretch v3 vs v4 look identical in a key of `(assetRef, window)` but are
different provenance), and without the permission pins there is no way to enforce
§3. The anonymous-blob option is therefore REJECTED. The stored value MUST carry
its full `DisplayDerivativeV1` pins (at minimum: source pins, window pins,
lod/style/validity pins, registration pin, permission pins, provenance pins);
whether the value embeds the bytes or points at the existing owned-output object
is a storage-representation choice (§1.4), but the pins travel with every entry.

### 1.2 `derivativeId` vs cache key — separate by construction

- `derivativeId` = `sha256(canonical(all display pins))`
  (`spatial_data_display.py:190–208`, projection in `display_derivative.py:71–127`).
  It names **content identity**: "this exact rendered tile". It deliberately
  contains `preparedForPrincipalHash` (a hash, not an authority) so two principals'
  identical renders do not share an id — per-principal addressing is structural,
  not a filter applied later.
- The **cache key** = `(derivativeId, grantDigest, policyDigest, purpose,
  preparedForPrincipalHash, activationCurrency)` — i.e. content identity PLUS the
  live rights binding. The `derivativeId` already embeds most of these pins, and
  the key repeats them explicitly so that (a) lookup never matches across a rights
  boundary even if a digest collides or a pin is recomputed, and (b) a grant or
  policy rotation changes the key WITHOUT changing the `derivativeId` (the pixels
  are the same; the permission to serve them is not). This mirrors the existing
  Console slot (`spatial-display-cache.ts:58–66` joins stableKey + grant +
  policy + purpose + principal hash) and the parent contract §6
  (`derivativeId, grantDigest, policyDigest, purpose`).

CRITICAL RULE restated as a keying invariant: **a content-hash match is a
necessary condition for serving, never a sufficient one.** Lookup is a two-step
predicate — `keyMatch AND rightsRecheckPass(now)` — and the second step runs
against live Core state on EVERY hit (§3). Any implementation that short-circuits
the second step on hash equality violates INV-060 and this design.

### 1.3 Cache key derivation (normative fields)

```text
DisplayCacheKeyV1 {
  content: { derivativeId }                       // pins §1.1: source + window + lod
                                                   //   + style + validity + registration
                                                   //   + permission + provenance
  rights:  { grantDigest, policyDigest, purpose,   // explicit repeats for boundary safety
             preparedForPrincipalHash,
             beneficiaryPrincipalId, organizationId,  // scope: never match across principals
             allowedBoundsDigest, observedCrsDigest }
  currency:{ grantRevision, policyRevision,        // rotation changes the key, not the pixels
             activationDigest | activationEpoch }  // worker/policy currency pin (owner to fix)
  scope:   { tileSize, lodTableVersion, kernelId } // 512px start; LOD rule owned by stage 2
}
```

Notes:

- `beneficiaryPrincipalId/organizationId` are part of the key even though only
  their hash appears in `derivativeId`: key comparison happens before any hash
  disclosure, so cross-principal probing returns "no such entry" rather than
  "hash mismatch" (cf. `downloads.py:102–106` NOT_FOUND discipline and
  `spatial-display-cache.ts:85–88` FOREIGN_PRINCIPAL handling).
- `activationDigest/epoch`: the preparation ran under a specific activation and
  policy revision (`grants.py` authorizer checks policy digest `:314`,
  processing location `:318–319`). A re-activation must not silently keep serving
  bytes prepared under a revoked execution context; the owner fixes the exact
  currency token (activation digest vs policy revision vs epoch counter) — §6
  open decision O-4.
- No token, no session id, no raw principal id in the key — hashes and digests
  only (INV-060/061; the Console cache already stores hashes, never identities).

### 1.4 Storage representation — whole tile bytes, and why

**Store whole tile bytes per key** (one cache value = one tile's verified output
bytes, ≤512×512 px, ≤ policy `max_output_bytes`), not whole-window
(pre-composed viewport) images and not sub-tile fragments.

Reasons:

- The lane's atomic unit IS the ≤512×512 window (per-output cap `jobs.py:991`;
  GAP-06 measured 474–698 KB per tile). Caching at the same granularity means a
  hit replaces exactly one PREPARE, a miss costs exactly one PREPARE, and the
  scheduler's 2-slot accounting stays exact (§4).
- Whole-window (viewport-composed) caching would key on viewport floats: every
  1-px pan would miss, the ~12 s would be paid again, and seam-exactness would
  depend on the cache rather than on integer cell edges. Tile-granular caching
  preserves the parent contract §3 guarantee (adjacent tiles share exact cell
  edge `c1`; `actualBounds` come from receipts, never re-rounded) because
  composition still assembles verified tiles edge-to-edge
  (`spatial-display-composition.ts:88–120`, `spatial-display-mosaic.ts:184–213`).
- Sub-tile fragments would multiply keys, complicate the SHA gate (receipts vouch
  for whole outputs), and buy nothing: 512px tiles are already small.

Consequence for seam-exactness: the cache MUST NOT store composed windows,
blended seams, resampled overviews, or reprojected bytes. Every cached value
decodes to exactly one receipt-verified native tile at its stated LOD; screen
assembly remains display assembly (label
`spatial-display-composition.ts:50–52`), never a new measurement.

LOD/threshold note (Human direction, normative for stage 2): the tile OUTPUT
SIZE starts at 512px (today's cap; `spatial-display-viewport.ts:165–166, DISPLAY_WINDOW_MAX_PIXELS`).
256px is a candidate output size for the benchmark to evaluate, NOT a second LOD
level with a fixed zoom threshold. The LOD selection rule itself (which level
for which screen resolution) is stage 2 work and MUST be a function
`level = f(viewportMetresPerPixel, devicePixelRatio, sourceGSD)` against a
pinned table — screen-required resolution vs source resolution — never a fixed
zoom factor. This design only requires that whatever the rule resolves to is
pinned in the key (`lodTableVersion, kernelId, targetMetresPerPixel`) so the
same (viewport, source, table) always resolves to the same tiles.

## 2. Two-tier cache (normative design)

| Tier | What it holds | Who owns eviction | TTL / retention | Authority |
|---|---|---|---|---|
| **T1 — browser/session tier** (today's `MosaicPaintCache` + `DisplayWindowCache`, to be kept as this tier) | Decoded tile pixels for the current session only, keyed per §1.3, owner-token-gated (`spatial-display-mosaic.ts:311–348`) with rights re-check (`spatial-display-cache.ts:84–115`) | Console (session code): LRU/size cap + explicit `evict/clear` on rights failure | Session lifetime only; NO independent TTL — expiry is decided by re-check, not by clock | **Latency optimization, never authority.** A T1 hit that cannot re-validate against T2/live rights is a miss. |
| **T2 — persistent server tier** (NEW operational component, §6) | Whole tile bytes + full pins (§1.1) per §1.3 key, per-principal and per-purpose | Core delivery ownership (retention/cleanup loop; existing `retention_seconds` + cleanup semantics apply to the underlying owned outputs) | `retention_seconds` (delivery policy) AND an HTTP/cache TTL, labelled as DISTINCT values (parent §6); numeric TTLs are benchmark-set, not invented here (§7) | **Durability + cross-session hits**, still not authority: every serve re-checks §3 against live grant/revocation/policy state. |

Tier interaction (normative):

1. T1 is keyed by the SAME `DisplayCacheKeyV1` as T2 (today's `stablePrepareKey`
   of `(assetRef, pixelWindow, purpose)` is EXTENDED with the §1.3 rights and
   currency pins — the current key is rights-blind at lookup except via the
   separate `serve` re-check, which this design folds into the key itself).
2. A T1 hit MUST be re-validated before painting: re-check §3 against the
   freshest rights facts the Console legitimately holds (session grant state from
   Core responses + receipt pins). If any check fails or the facts are stale
   beyond the owner-fixed freshness bound, the T1 slot is dropped and the request
   falls through to T2 — a T1 hit never paints on its own authority.
3. A T2 hit returns bytes that still pass the existing size+SHA gate before
   decode (`spatial-data-preview.ts:29–53`); the gate is unchanged.
4. T1 stores decoded pixels (paint-ready); T2 stores encoded bytes (verifiable).
   The asymmetry is intentional: T1 optimizes paint latency, T2 optimizes
   re-verification and cross-session reuse.
5. Eviction cascades down, never up: T2 eviction (LRU/size/TTL/rights change)
   does not touch sealed sources, receipts, or analysis bindings (parent §2);
   T1 eviction never affects T2. Re-derivation after T2 eviction reproduces the
   same `derivativeId` iff all pins are unchanged, else a new id.

What this design REPLACES vs keeps: it KEEPS both existing Console stores as the
T1 tier (their fail-closed `serve` semantics are correct) and ADDS the missing T2
persistent server tier. The current gap — pan-back within a session hits T1, but
any reload, second device, or second session re-pays the full ~12 s — is exactly
what T2 closes.

## 3. Rights on every hit (normative re-check sequence)

The persistent tier adds NO independent authority. Every serve — T1 paint or T2
delivery — executes this sequence against LIVE Core state at serve time `now`,
in this order (order matters: cheap structural checks first, scope checks before
existence-disclosing checks, per `grants.py:215–329` and `downloads.py:100–106`
discipline):

| # | Check (live, at `now`) | Source of truth | On failure |
|---|---|---|---|
| 1 | Key scope match: `beneficiaryPrincipalId + organizationId + purpose` in the key equal the requester | Key fields vs authenticated principal (`grants.py:359–366` asset-key equality; mismatch → NOT_FOUND, never a distinguished error) | Drop slot, return NOT_FOUND wording (`spatial-display-cache.ts:53–55` FOREIGN_PRINCIPAL copy). No existence disclosure. |
| 2 | Grant live: `grant.is_current_at(now)` (`spatial_data_authority.py:123–125`) at the key's `grantDigest + grantRevision` | Core grant store (`grants.py:312–313`) | Drop slot, stop serving (fail-closed); UI shows truthful expiry state (parent §6; copy `spatial-display-cache.ts:50` GRANT_EXPIRED). |
| 3 | Not revoked: no matching `SpatialDataRevocationV1` (`:128–136`; `grants.py:310–311`) | Core revocation index | Drop slot, stop serving; truthful revocation state (`:51` REVOKED copy). |
| 4 | Purpose still authorizes: `purpose ∈ grant.purposes ∩ {GENERAL_DATA_USE, EXTERNAL_AI}` for this use (`grants.py:258–259,316`) | Grant + authorizer | Drop slot, PURPOSE_MISMATCH (`:52`); never silently substitute the other purpose. |
| 5 | Requester ownership: serving principal IS the principal the bytes were prepared for (`preparedForPrincipalHash` match; `downloads.py:102–106,251–255`) | Frozen job's `requester_principal_id` vs current principal | Drop slot, FOREIGN_PRINCIPAL wording (indistinguishable from absent). |
| 6 | Expiry/retention: `retention_seconds` not elapsed for the underlying owned output; HTTP/cache TTL labelled separately | Delivery retention/cleanup (existing policy) + new cache TTL (§6 O-4) | Treat as miss → re-derive path; never serve stale bytes as current. |
| 7 | Policy/activation currency: `policyDigest` still the live policy (`grants.py:314–315`); activation currency pin still current | Core policy + activation records | Treat as miss (re-resolve rights, possibly new key revision); never serve under a superseded policy. |
| 8 | Receipt integrity: stored `outputSha256/outputSizeBytes` still equal the sealed receipt's (`display_derivative.py:158–170` binding re-verification) | Sealed receipt | Drop slot, RECEIPT_CHANGED (`spatial-display-cache.ts:55`); never paint. |

Why a content-hash match is insufficient (the Human's CRITICAL RULE, stated as
design rationale): the hash answers "are these the bytes I expect?" — a DATA
INTEGRITY question. It cannot answer "may THIS requester receive them NOW, for
THIS purpose, under a LIVE grant?" — an ACCESS question whose inputs (validity
window, revocation bit, purpose set, ownership, policy revision) all change
independently of the bytes. Hash equality across a revocation, an expiry, a
purpose change, or a principal boundary is the expected case, not an edge case —
so the hash is checked LAST (step 8), after every rights check has passed.

### 3.1 The Human's risk note — display vs original/AI/export (decision + control)

DECIDED (normative, implements the binding direction):

- Display-tile READs under a map-display grant authorize NOTHING ELSE. Original
  GeoTIFF download, analysis execution (PREPARE for compute), external AI
  processing (`EXTERNAL_AI` purpose + `site.ai_egress_allowed`, `grants.py:277`),
  and dataset export are DIFFERENT acts requiring their own operations/purposes/
  grants. No cache hit, no derivative, no `derivativeId` may be presented as, or
  converted into, any of those acts. The Console MUST NOT offer "download
  original", "send to AI", or "export" affordances on the basis of display-tile
  possession; those paths re-enter their own grant flows from scratch.
- Repeated tile retrieval under display rights CAN reconstruct substantial
  source information (a full-cover walk replays the whole source through ≤512px
  tiles — GAP-06 measured 4 tiles ≈ 2.16 MiB for one 1022×915 ortho). Unbounded
  tile retrieval is therefore a SEPARATE risk decision from per-tile display
  rights. The control this design proposes (owner approval required, §6 O-6):
  **per-principal, per-purpose, per-source retrieval budgets** — a rolling byte/window
  quota (e.g. N× source size per period; numbers benchmark-set, §7) plus
  anomaly-gated throttling (systematic full-cover enumeration patterns), with
  NORMAL EXPLORATION (pan/zoom/revisit within a viewport neighbourhood) always
  inside the budget and never gated by approval steps. Exceeding the budget does
  NOT widen rights — it pauses tile serving with a truthful
  rate/quota state and a cancel/retry affordance, exactly like the existing
  429 lane-copy discipline (`spatial-display-scheduler.ts:122–129`).
- What REMAINS a risk-assessment decision (not decided here): the numeric budget,
  the period, the enumeration-detection rule, and whether any role (e.g. auditor
  export) needs a distinct purpose value — GAP-05 threat-model review owns these.

## 4. Cold/hot path & scheduler integration (normative)

Target flow (the Human's structure, with the rights checks made explicit):

```text
browser map
  → resolve viewport to minimal tile set (viewport lib; source-origin tiling, §1.4)
  → permission check (live grant/purpose/scope pre-check — never cached authority)
  → T1 lookup (session tier): hit + re-validated → PAINT immediately
  → T2 lookup (PERSISTENT DISPLAY CACHE): hit + §3 re-check pass → verify (size+SHA gate) → PAINT immediately
  → on miss: tile preparation job (scheduler, ≤2 concurrent) → receipt verify → T2 store → T1 store → deliver
```

Hot path (all hits): no PREPARE is issued, no 429 is possible, no worker cost.
The scheduler's `ensure()` still runs (so covering sets stay joined/deduped) but
issues zero jobs; pan-back within retention is a pure cache replay (parent
acceptance §9.2: replay of the gesture from cache issues zero new PREPAREs).

Miss path (what a miss costs): exactly one bounded PREPARE per missing tile at
the lane's measured price (~5.4–5.9 s per 512×512 tile, §0.2), sequenced by the
scheduler at most 2-at-a-time with bounded 429 back-off
(`spatial-display-scheduler.ts:182–367`). A full-cover cold visit therefore still
costs ~12 s in 2 waves — the cache does not change the lane price, it stops
re-paying it.

Scheduler integration rules (until the cache service exists AND after — the
discipline is identical, only the hit rate changes):

1. **Cache first, scheduler second.** For each covering tile: T1 → T2 → only then
   `scheduler.ensure(missing)`. The scheduler key becomes the full §1.3 cache key
   (extending today's `stablePrepareKey` of `(assetRef, pixelWindow, purpose)`
   with the rights/currency pins) so identical tiles JOIN and never double-issue.
2. **Respect the 2-slot lane.** `maxConcurrent = 2` stays
   (`spatial-display-scheduler.ts:204–211`); the 429 path stays bounded-retry
   (`:325–343`). The cache REDUCES pressure on the lane; it never authorizes a
   third concurrent issue.
3. **Deduplicate + cancel.** In-flight keys JOIN (`:256–260`); queued keys for
   tiles that left the viewport (+ small hysteresis margin, owner to fix —
   parent §4 proposes 0.5 viewport) are dropped from the queue (`:225–234`);
   already-issued actives run to completion and populate the cache (a finished
   tile is a future pan-back hit — never abort completed work).
4. **Cold first visit stays tolerable via progressive first-pixel delivery:**
   issue order = centre/visible tiles first (client-sequenced, GAP-06 §"Queue
   ordering"), paint each tile the moment its bytes verify (progressive cover
   with named "preparing N" placeholders per `mosaicWaitingCopy` /
   `saturatedLaneCopy` — never a blank site, never a synthetic fill, INV-040),
   and record time-to-first-valid-pixel as the cold-path metric (§5).

## 5. Measurement plan — the completion criteria (normative method, benchmark-set numbers)

Stage 1 is DONE when the REAL product (real Core lane + contained worker +
real Console, never mocks alone) shows the cache working. Numeric PASS
thresholds are NOT invented here — the benchmark below SETS them, and the first
benchmark run records baselines. What is normative here is the metric
DEFINITIONS, the INSTRUMENTATION discipline, and the PASS/FAIL FORM of each
criterion.

### 5.1 Metrics (all measured on the real lane)

| # | Metric | Definition (exact) | How to instrument (no product-semantics change) | Pass/fail form |
|---|---|---|---|---|
| M1 | **Cache hit rate** | `served-from-T1-or-T2 tiles / total tiles requested` per scripted run (§5.3), reported separately for T1, T2, and overall; a "request" is one covering-tile need, a "hit" is a paint with zero new PREPARE | Console counters at the lookup points (§4 flow): `t1_hit, t2_hit, miss→prepare` per tile key; T2 hits corroborated by Core-side serve logs (no new job id for that key). Read-only counters + log joins; no request/response mutation. | PASS when the second identical run (§5.3 R2) reaches the benchmark-set overall rate AND zero new PREPAREs are issued (parent §9.2). Target numbers TBD by benchmark — NOT invented here. |
| M2 | **Time to first valid pixel (TTFP)** | Milliseconds from viewport-commit (user's pan/zoom settles to a covering set) to the first tile PAINTED with receipt-verified bytes (size+SHA gate passed) | Console performance marks: `viewportCommit → firstPaintVerified`; measured separately for cold (all-miss), warm (all-hit), mixed. Marks only; no behaviour change. | PASS when warm TTFP ≤ benchmark-set bound on the reference fixture; cold TTFP reported (informative — bounds the lane, not the cache). Numbers TBD. |
| M3 | **Time to stabilise after a pan** | Milliseconds from viewport-commit to full covering set resolved: every tile either painted-verified or an explicit named gap (`NOT_REQUESTED/PREPARE_FAILED/RECEIPT_MISMATCH/RIGHTS_UNAVAILABLE` — `spatial-display-composition.ts:29–36`) with no pending scheduler entries | Scheduler snapshot listener (`snapshot()` `:266–290`: active/queued/retrying empty) + composition plan `seamless/gaps` joined per interaction. Observation only. | PASS when a scripted pan sequence (§5.3) stabilises within the benchmark-set bound on an idle lane, with no silent fallbacks. Numbers TBD (≈15 s interaction budget per GAP-06 is the starting hypothesis, not the criterion). |
| M4 | **429 occurrence rate** | `429 CONCURRENCY_LIMIT_EXCEEDED responses / total PREPARE issues` per run, plus `retryable-429 → eventual success` vs `→ FAILED` split | Count at the issue boundary (`DisplayPrepareIssueError` `:67–77`, `isRetryableLaneError` `:80–86`); Core-side 429 log join. Counters only. | PASS when the scripted exploration run (§5.3) issues within the 2-slot discipline: 429s are rare (only under genuine contention), always bounded-retry, never user-visible as errors; FAILED-due-to-429 = 0. Numeric bound TBD. |
| M5 | **Memory usage** | Browser tier: T1 byte residency (slots × tile bytes) + peak JS heap delta over the scripted run; server tier: T2 byte residency per principal/purpose | Console: `MosaicPaintCache.size` + slot byte sums sampled per interaction; `performance.memory` (where available) as corroboration. Server: store residency gauges. Gauges only; caps enforced by existing eviction, not by the measurer. | PASS when the full scripted run completes with T1 under its owner-fixed cap (eviction, not crash, handles overflow) and T2 growth is bounded per principal/purpose (no cross-principal accumulation). Cap numbers TBD (§7). |

Additional invariant checks (every run, fail-closed): §3 re-check blocking
(revoke/expire → next request stops serving, parent §9.4); seam exactness
(shared cell-edge equality + `actualBounds` abutment, parent §9.1); three-state
separation (no composite flag); no synthetic fill (INV-040).

### 5.2 Instrumentation discipline

- Counters, marks, gauges and log joins ONLY. No change to request/response
  bodies, grant checks, receipt gates, scheduler ordering, or lane concurrency.
- Every metric names its lane conditions (idle vs shared, worker pickup jitter,
  the L3-type outlier policy: report, don't delete — GAP-06 §48* recorded 1/11).
- Numbers are reported with the fixture identity (source size/CRS/transform,
  tile size, viewport sequence version) so runs are comparable.

### 5.3 The reference exploration run ("good exploration")

A versioned scripted pan/zoom sequence executed identically for baseline and
candidate builds (sequence version pinned with the results):

1. **R1 — cold cover:** open the reference site/area (1022×915 fixture or
   production sample) at whole-site extent; wait for full stabilisation (M3).
   Expectation: all misses, ~2 waves, establishes the cold baseline.
2. **R2 — identical revisit:** reload/re-enter the SAME viewport. Expectation:
   ~100% hit rate (M1), zero new PREPAREs, warm TTFP (M2).
3. **R3 — pan walk:** four adjacent-viewport pans (each overlapping R1 by ~50%),
   settling each before the next. Expectation: overlapping tiles hit, new fringe
   tiles miss-then-prepare; stabilisation per pan (M3); pan-back to R1 viewport =
   hits only.
4. **R4 — zoom in/out:** whole-site → 2× zoom on centre → back out, same centre.
   Expectation (stage 1, single tile size): same tiles re-served at 512px; the
   resolution-vs-source LOD behaviour is stage 2 and is NOT scored here — R4 in
   stage 1 only checks that zoom does not duplicate, leak, or destabilise.
5. **R5 — rights flip (separate pass):** revoke (or expire) the grant, re-request
   the R1 viewport. Expectation: zero tiles served from either tier; truthful
   revocation/expiry UI; other principals unaffected.

Each run logs M1–M5 + the invariant checks with the sequence version and lane
conditions. Baselines are recorded BEFORE the cache ships (today's session-tier
only) so the improvement is measured, not asserted.

## 6. Contract surface + owners (proposed — names are proposals)

### 6.1 New/extended records

| Record | Fields (minimal) | Owner module (proposed) |
|---|---|---|
| `DisplayCacheKeyV1` (NEW) | §1.3 shape: `derivativeId; grantDigest, policyDigest, purpose, preparedForPrincipalHash, beneficiaryPrincipalId, organizationId, allowedBoundsDigest, observedCrsDigest; grantRevision, policyRevision, activationDigest-or-epoch; tileSize, lodTableVersion, kernelId` | `packages/event-contracts` (schema) + Core delivery (binding/currency semantics) + `packages/geo-spatial` (window/LOD pins) |
| `DisplayCacheEntryV1` (NEW) | `cacheKey (§1.3), derivativeId, outputSha256, outputSizeBytes, storedAt, lastRightsRecheckAt, serveCount?, evictionClass?` (no tokens, no raw identities) | Core delivery (rights re-check + retention) + cache holder (storage) |
| `DisplayCacheStatsV1` (NEW, measurement-only) | `t1Hits, t2Hits, misses, preparesIssued, r429Count, ttfpMs, stabiliseMs, residencyBytes` per run + `sequenceVersion + laneConditions` | Console (client counters) + Core (serve-side join); owned as test/benchmark telemetry, never product authority |
| `DisplayDerivativeV1` etc. (EXISTING, reused) | Unchanged — `spatial_data_display.py:66–208`; cache references, never mutates | `packages/event-contracts` (existing owner) |
| Retrieval budget policy (EXTENDED policy, values TBD) | `perPrincipalPurposeByteQuota, quotaPeriod, enumerationThrottle` — new FIELDS on the existing signed policy or a referenced budget record (owner decides) | Core delivery/policy owners + GAP-05 review (§3.1) |

Extended (not new): grant `operations` gains no value — display reads reuse
`READ`, preparation reuses `PREPARE`; no new purpose is proposed (GAP-05 review
decides, parent §8.8).

### 6.2 Who changes what

- **Core change:** T2 store + §3 serve-time re-check sequence + key binding +
  retention/cleanup ownership + retrieval-budget enforcement + serve-side
  counters for M1/M4 corroboration. No new PREPARE mode, no LOD table, no
  endpoint invented here (wire shape stays "bounded GETs keyed by tile pins
  returning verified bytes or typed failures" — parent §8; claiming a path
  exists is forbidden).
- **Console change:** §1.3 key extension, T1-as-tier-1 conformance (same key,
  re-validate-before-paint), cache-first scheduler wiring (§4 rules 1–4),
  progressive first-pixel delivery, M1–M5 client instrumentation, scripted-run
  harness (§5.3).
- **Worker change:** NONE. The contained worker keeps cropping exact native
  windows; it knows nothing of tiles-as-cache, LOD, or rights (rights stay
  Core-side; integrity stays receipt-side).
- **CDN/browser cache rules under the current grant model:** any shared or
  edge cache (CDN, shared browser cache, proxy) MUST NOT serve display bytes
  across principals or purposes. Until a threat-model-approved shared design
  exists (parent §6 refusal stands), cacheable responses carry
  `Cache-Control: private, no-store`-equivalent semantics (cf. `api.py:46–58`
  — current delivery responses already send `private, no-store`) and any edge
  caching is per-requester-keyed or disabled. A cache hit at ANY layer executes
  §3; a layer that cannot execute §3 MUST NOT cache.

### 6.3 The persistent tier as a new operational component

The T2 tier is a NEW operational component with its own lifecycle: it holds
bytes durably, enforces per-principal/purpose isolation, runs retention/cleanup,
and serves reads under §3. That implies EITHER (a) a Core-owned store inside the
Core deployment boundary (same process/host, Core delivery owns lifecycle), OR
(b) a separately deployed display-cache service fronted by Core authorization
(Core still owns the §3 decision; the service holds bytes only). BOTH shapes
keep authorization inside Core delivery; neither creates shared-cache authority,
a new PREPARE mode, or a new deployment — and this design AUTHORIZES NEITHER:
the owner boundary choice and any deployment shape need separate owner approval
with dependency/build/CI/replay/deployment/rollback evidence (per repo routing;
no `services/` consolidation by name).

### 6.4 Open decisions requiring owner approval

- **O-1.** `DisplayCacheKeyV1` / `DisplayCacheEntryV1` / `DisplayCacheStatsV1`
  exact names, fields, and schema owner sign-off.
- **O-2.** Activation-currency token (activation digest vs policy revision vs
  epoch counter) in the key (§1.3).
- **O-3.** T2 placement: Core-owned store vs separate service (§6.3); store
  technology; cleanup-loop ownership; `retention_seconds` vs HTTP/cache TTL
  labelling and numeric values (benchmark-set).
- **O-4.** T1 freshness bound: how stale a T1 slot's rights facts may be before
  fall-through to T2 is mandatory.
- **O-5.** Retrieval budgets: quota fields, numbers, period, enumeration rule
  (§3.1) — joint with GAP-05 threat-model review.
- **O-6.** Tile output size evaluation method: how the benchmark compares 512px
  vs 256px (and any other candidate) so the decision is measured, not argued.
- **O-7.** Style/validity registries (colour-ramp/stretch/mask-rule version
  pins — new micro-registry or reuse of profile digests; parent §8.6).
- **O-8.** Whether any `PURPOSE` split between human viewing and EXTERNAL_AI
  display use is needed (GAP-05 review; parent §8.8).

## 7. What could NOT be specified (candid)

- **TTL/eviction numbers** (T1 cap, T2 size/TTL, quota periods): no load profile
  exists beyond the single-actor GAP-06 lane run. GAP-06 forbids guessing
  resource numbers (ADR-KSI-038 D4); the §5 benchmark sets them. Any number in
  an implementation PR that cites this design as its source is mis-citing it.
- **The shared-cache threat model**: refused under the current grant model
  (parent §6; §6.2 CDN rule). A future shared design needs a new threat model +
  independent security review (GAP-05) — not specified, not implied, not
  pre-approved.
- **LOD thresholds and kernels**: stage 2. Screen-resolution-vs-source-resolution
  is the mandated METHOD (§1.4); every numeric threshold, table version, and
  kernel choice awaits the benchmark + GAP-03 owner determination.
- **Any assumption that a cache hit may bypass a right**: explicitly UNSPECIFIABLE
  as a relaxation — §3 is the floor, not the opening bid. No performance result
  weakens it; if re-checks prove too slow, the fix is faster checks (e.g. local
  revocation-index replica with a freshness bound, owner-approved), never skipped
  checks.
- **Cross-epoch, saved-context, and historical-lookup semantics**: later stages
  in the Human's order; this design's keys are single-epoch and carry the
  registration pin opaquely without interpreting it.
- **The L3-type 10.7 s outlier** (GAP-06 §48*): unexplained single-sample
  pickup anomaly; the measurement plan (§5.2) requires reporting outliers, not
  deleting them, until a cause is found.

---

## Handoff summary (for the parent session)

- File created:
  `docs/design/SPATIAL_DISPLAY_PERSISTENT_CACHE_AND_MEASUREMENT_PLAN_2026-10-21.md`
  (this document). No other file touched; no commits; no servers; no new Core jobs.
- Cache keying/rights decisions: cached artifact = display-derivative prepared
  bytes at stated tile size (§1.1); `derivativeId` (content identity) vs cache key
  (content + explicit rights/currency repeats) kept separate (§1.2); normative
  `DisplayCacheKeyV1` fields incl. principal/org scope and activation currency
  (§1.3); whole-tile-bytes representation preserving seam-exactness (§1.4);
  LOD-by-screen-vs-source-resolution mandated as method with 512px start and
  benchmark-set sizes (§1.4); 8-step live re-check on EVERY hit with hash LAST
  (§3); display ≠ original/AI/export with per-principal/purpose retrieval budgets
  as the proposed control and numerics left to GAP-05 + benchmark (§3.1).
- Two-tier design: T1 session tier kept (latency only, re-validate-before-paint);
  T2 persistent server tier added (durability + cross-session, still not
  authority); same key both tiers; eviction cascades down only (§2).
- Measurement plan with metric definitions: M1 hit rate, M2 time-to-first-valid-pixel,
  M3 time-to-stabilise-after-pan, M4 429 rate, M5 memory — each with exact
  definition, no-semantics-change instrumentation, and pass/fail FORM with
  numeric targets explicitly marked to-be-set-by-benchmark (§5.1–5.2); versioned
  5-phase reference exploration run R1–R5 incl. rights-flip pass (§5.3).
- Open decisions: O-1..O-8 (§6.4) — record names/fields, currency token, T2
  placement + TTL labelling (notes NO new deployment authorized, §6.3),
  T1 freshness bound, retrieval budgets, tile-size evaluation method, style/
  validity registries, purpose split.
- Remains undecidable today: TTL/eviction/quota numbers (no load profile);
  shared-cache threat model (refused under current grants); LOD thresholds/
  kernels (stage 2 + GAP-03); any rights-bypass relaxation (unspecifiable —
  §3 is the floor); cross-epoch/saved-context/historical semantics (later
  stages); the GAP-06 L3 outlier cause (§7).
