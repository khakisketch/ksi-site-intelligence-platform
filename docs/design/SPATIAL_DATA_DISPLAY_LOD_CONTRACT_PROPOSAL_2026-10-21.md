# Spatial-data display/LOD contract — proposal (not implemented)

Date: 2026-10-21. Base: main `3568f5b2`.
Status: **PROPOSAL, Human-directed design.** No source/contract/runtime/worker/policy change,
no commits, no servers, no new Core jobs, no shared-host actions, no inspection launch.
Nothing here authorizes implementation; owner approval and separate contracts/tests are required
before any code.

Why `docs/design/` and not `docs/audit/`: per repo routing (`REPOSITORY_STRUCTURE.md`,
`docs/DOCUMENT_STATUS.md`), this is a product-facing data-display contract proposal governing
the future display path's identities, addressing, LOD, registration evidence, permission/cache
and entry semantics — not an audit-ledger preservation/recovery record. The sibling audit-recovery
proposal (`docs/audit/INSPECTOR_JOURNAL_RECOVERY_CONTRACT_PROPOSAL_2026-10-21.md`) is the
audit-track document; this document contains no audit-recovery content and grants no
shared-host journal authority. Audit recovery D1–D6 stays on its independent track with
separate approval.

## Authority and precedence

Constitution → Decision Ledger → PRD §1.1.2 (SDP-REQ-01..08) → `contracts/` →
ADR-KSI-036/037/038/039 → this proposal (subordinate). It changes none of them.
Normative invariants: `docs/product/DOMAIN_INVARIANTS.md`
(INV-020/024/040/050/051/053/054/055/060/061 in scope).
Prior art this proposal builds on:
[SITE_SPATIAL_WORKSPACE_UX_CONTRACT.md](SITE_SPATIAL_WORKSPACE_UX_CONTRACT.md) (§4, §6, §7),
[ADR-KSI-037](../architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md) D3/D5
(common-grid-is-not-registration rule),
[ADR-KSI-038](../architecture/ADR-KSI-038-spatial-data-and-analysis-platform.md) D4
(three-layer verdict separation), production provisioning
[SPATIAL_DATA_PRODUCTION_PROVISIONING.md](../ops/SPATIAL_DATA_PRODUCTION_PROVISIONING.md) (§9, §9.x),
roadmap GAP-01..10
[2026-09-30-spatial-data-platform-roadmap](../superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md),
rebaseline workspace/UX and actual-use evidence sections
[2026-10-07-agent-first-platform-rebalance](../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md),
and the audit proposal §4 three-state vocabulary.

Human's binding direction (implemented exactly): the next development centre is the
DISPLAY/LOD CONTRACT, not audit recovery; the temporary visualization adapter must NOT be
scaled up — first fix the meanings of coordinate, registration, permission and cache in a
formal contract, then implement; audit recovery is explicitly OUT of the critical path.
Priorities: display/LOD contract = highest; site/area entry = in parallel with it;
historical result lookup = later; audit recovery = independent track.

## 0. Established facts (verified in code, not re-derived)

1. The spatial-data lane is a bounded native-window PREPARE job: Core issues a job bound to a
   sealed+inspected subject, a grant, an activation and a signed policy; a contained worker
   crops the EXACT native grid; the result is a receipt with
   `outputSha256/outputSizeBytes/pixelWindow/actualBounds/observedCrsIdentifier`
   (`packages/event-contracts/src/ksi_event_contracts/spatial_data.py:352–367`), and the
   browser reads it through a same-session guarded GET with a size+SHA gate before decode
   (`apps/dashboard/src/lib/spatial-data-preview.ts:29–53`, `apps/dashboard/src/lib/site-windowed-pixel-viewer.ts:16–27`).
2. `max_output_pixels` is PER OUTPUT: `services/core/src/ksi_core/domains/external/delivery/jobs.py:991`,
   `job_projection.py:173,193` — verified live: two adjacent windows of the same
   1022×915 EPSG:7850 source completed side by side
   (jobs `sdj-v1-1f42ba31…` cols 510-1022 and `sdj-v1-6ff0ab18…` cols 0-512).
   Binding limits are request volume, `maxActiveJobsPerOrganization` 2, the EFFECTIVE request
   buffer (measured: zero — a 3rd parallel issue is a fast retryable 429, and
   `maxQueueDepth`/`maxPendingRecords` 8 are unreachable on this route), latency and cache
   policy — NOT an exploration-area cap.
3. Window geometry is the authoritative native-grid rule:
   `packages/geo-spatial/src/ksi_geo_spatial/external_native_window_geometry.py`
   `_plan` (floor/ceil to exact native cell edges `:73–76`, must sit inside the source
   footprint `:69–72,77–85`); the transform tuple is
   `(xScale, rot, xOrigin, rot, yScale, yOrigin)` — `yScale` is `t[4]`, `yOrigin` `t[5]` (`:89`).
4. Rights already bind a window's admissibility: `SpatialDataGrantV1` carries `asset_ref`,
   `site_id`, `work_area_id`, `allowed_bounds`, `observed_crs_digest`, `operations`
   (PREPARE/READ), `purposes` (GENERAL_DATA_USE/EXTERNAL_AI), `valid_from/valid_until`,
   `policy_digest`, `attribution`, `license_provenance_digest`
   (`packages/event-contracts/src/ksi_event_contracts/spatial_data_authority.py:85–108`),
   plus `SpatialDataRevocationV1` (`:128–136`). The display contract builds on this
   grant/revocation model; no parallel rights system is proposed.
5. The read path is requester-owned: the same principal reads its own output; another
   principal is denied (404/403) — do NOT widen this. Cache re-checks must preserve it.
6. The sanitized-display derivative lane (inspection-worker produced) is STOPPED under the
   unresolved shared launcher-history incident: do not depend on it, do not restart it, do
   not treat any new display path as a validation substitute.
7. The three states stay separate: audit integrity / data-validation suitability /
   spatial viewability (audit proposal §4). No composite ready/status/verified flag.
8. The incumbent is the temporary windowed viewer
   (`apps/dashboard/src/app/sites/[siteId]/SiteWindowedPixelViewer.tsx:575`,
   `apps/dashboard/src/lib/site-windowed-pixel-viewer.ts`, label `:30–34`).
   It is explicitly a temporary adapter — the behaviour to REPLACE, not to scale.

## 1. Scope & non-goals

The contract governs:

- (a) Display-derivative identity vs source identity (stable source reference, regenerable
      display artifact with exact parameters).
- (b) Display addressing: source-CRS native grid, integer pixel windows, LOD selection rule.
- (c) Level-of-detail selection and recording (same viewport → same tiles).
- (d) Valid-area/NoData/mask semantics on screen (valid vs threshold-excluded vs unavailable,
      cf. ADR-KSI-037 D5 `unavailable = selected − common-valid`).
- (e) Registration evidence required before cross-epoch spatial comparison (and the
      independent-viewing-only fallback).
- (f) Permission+cache binding of every display byte (grant/revocation/validity/purpose
      re-check on every use; requester ownership preserved through caching).
- (g) Epoch-switch extent continuity (same spatial extent preserved WITHOUT reinterpreting
      one epoch's extent as another's) and the Human's site-entry policy.

It explicitly does NOT:

- Create any new eligibility judgement, accuracy claim, survey-grade registration inference,
  or basemap/third-party tile egress (no external tile fetching by default; the UX contract
  §7 already states no basemap is required for the MVP).
- Change the three-layer verdict model (validity / purpose-suitability / reproducibility,
  ADR-KSI-038 D4) or the audit proposal's three-state separation — the display contract only
  reads those states, never merges them.
- Weaken any quantity/CRS/vertical/registration gate
  (INV-020/024/051/053; ADR-KSI-037 D3/D5; vertical-reference `ESSENTIAL_INPUT_UNAVAILABLE`
  behaviour recorded on the roadmap 2026-10-20 note).
- Contain any audit-recovery content (independent track; approval here grants no journal
  modification authority).

Four Human questions this contract must answer — where each is answered:
(a) tile-edge exactness → §3; (b) zoom/pan request duplication/explosion → §4;
(c) same-extent epoch switch → §7; (d) rights-expiry cache blocking → §6.

## 2. The two identities (normative)

Principle (normative): **SEPARATE the display-derivative identity from the
source-spatial-data identity.** Display tiles may be regenerated or evicted from cache;
the original data version and the input identity referenced by an existing analysis result
stay stable. Changing display colour/LOD for the same DSM must NEVER change the source
version an old volume result refers to (UX contract §2 correction example: R1 stays bound
to D1 even after D2 appears).

### SOURCE identity (stable, never evicted by display needs)

The sealed+inspected artifact version as known to Core today; borrowed entirely from
existing contracts, no new identifier:

| Field | Source contract |
|---|---|
| `assetRef` (submission/ref/revision/artifact projection) | `spatial_asset_catalog.py`, UX contract §2 table |
| submission selector: `workOrderId`, server-issued `submissionRef`, `revision` | ADR-KSI-036 (opaque `ers-v1-` ref; raw customer ID stays declaration/journal/object-key identity) |
| sealed byte digest + `RasterMeasurementsV1` (grid, transform, CRS, NoData, sizes) | `external_artifact_validation.py:290–292`, `spatial_data.py:291–292` |
| `observed_crs_digest` (+ identifier, units, vertical reference where known) | same; INV-020 |
| inspection/evaluation/use-decision record identities | audit proposal §4 S2 row |
| analysis input binding (`analysisId` intent vs execution identity, per-epoch evaluation identities, `reportDigest`) | UX contract §2 table |

An old result ALWAYS opens with its original selectors/identities/conditions/evidence
(UX contract §2 rule). A newer version is offered as "새 버전으로 새 비교", never
silently substituted.

### DISPLAY-DERIVATIVE identity (regenerable, cacheable, evictable)

A display derivative is a pure function of (SOURCE identity + display parameters +
validity policy version). Proposed shape (NEW record, see §8 — owner approval required):

```text
DisplayDerivativeV1 {
  source: { assetRef, byteDigest, observedCrsDigest, revision, inspectionRef }
  window: { pixelWindow (c0,c1,r0,r1 half-open col/row), actualBounds, gridTransform }
  lod: { level, nativeScaleDenominator or targetMetresPerPixel, resamplingKernel }
  style: { bandMapping | colourRampId + version, stretchId + version, noDataMaskRule,
           unitLabelId, verticalBasisStatementId }
  validity: { maskSourceDigest, validAreaRuleVersion, excludedRuleVersion }
  registrationRef: PairRegistrationRef | NONE   // §5; NONE => independent viewing only
  permission: { grantDigest, policyDigest, purpose, preparedForPrincipalHash }
  provenance: { prepareJobId, receiptDigest, preparedAt, workerBuildDigest }
  derivativeId: sha256(canonical(all above))    // content-addressed; see "new identifier" below
}
```

Borrowed vs new:

- Borrowed: `assetRef`, manifest/byte digest, `observed_crs_digest`, grant
  (`grant_digest`, `policy_digest`), receipt fields
  (`outputSha256/outputSizeBytes/pixelWindow/actualBounds/observedCrsIdentifier`),
  `SpatialDataRevocationV1`.
- Genuinely NEW and justified: (1) `derivativeId` — no existing identifier names "this
  exact rendered tile at this LOD/style/validity"; job IDs are request-scoped and receipts
  do not record LOD/style. Content-addressing makes regeneration idempotent and eviction
  safe. (2) `PairRegistrationRef` (or explicit NONE) — no existing record asserts
  display-pair co-registration (the UX contract §4 already observes that
  `VISUAL_COMPARISON` checks and a sanitized-display receipt establish no such geometry).
  (3) `style/validity` version pins — colour/validity policy versions have no current
  registry; without pins, two identical-looking tiles are indistinguishable in provenance.

Invalidation/eviction rules:

- Derivatives are NEVER authoritative: any change to source bytes, revision, CRS digest,
  mask-rule version, style version, grant/revocation state, or registration record
  INVALIDATES (not mutates) affected derivatives — they are re-derived or dropped.
- Eviction (LRU/size/TTL) of a derivative never touches the source version, the sealed
  bytes, or any analysis input reference. Re-derivation after eviction reproduces the same
  `derivativeId` only if ALL pinned inputs are unchanged; otherwise it yields a new ID.
- An existing analysis result's referenced source version is immutable under display
  changes by construction: results bind SOURCE fields only, never `derivativeId`.

## 3. Tile/window addressing & edge exactness

Addressing rule (normative):

1. All display windows are addressed in the SOURCE's observed CRS native grid
   (INV-020; `_plan` north-up-only gate `:62`). No WGS84-guessed placement
   (UX contract §4: "No guessed WGS84 placement").
2. A window is the half-open integer pixel rectangle `(c0, c1, r0, r1)` = columns then
   rows, with `actualBounds` and grid `transform` derived EXACTLY as
   `external_native_window_geometry.py:73–94` computes them (floor/ceil to exact native
   cell edges; request must be fully inside the source footprint).
3. Adjacent windows join without gaps or overlaps **iff** they partition the integer pixel
   range contiguously: window A `(c0,c1,·,·)` and window B `(c1,c2,·,·)` share the exact
   cell edge `c1` — guaranteed by the floor/ceil-to-cell-edge rule plus the stable-index
   computation (`_stable_pixel_index`, binary search on representable affine edges
   `:97–119`). The DISPLAY path must additionally guarantee (new, to be owned):
   - (i) the tiling origin is the SOURCE grid origin `(c, f)` from the sealed
         measurements, never a viewport-snapped origin — otherwise two sessions tile the
         same area with different seams;
   - (ii) tile boundaries are pixel indices, and `actualBounds` shown/compared are the
         receipt's `actualBounds`, never re-rounded viewport floats;
   - (iii) a tile is only composable if its receipt's `pixelWindow/actualBounds/sha/size`
         verify (the existing preview gate); a failed tile leaves an explicit gap state,
         never a stretched neighbour (fail-closed, INV-040).
4. LOD selection (to be owned; proposed rule): integer-pyramid levels where level 0 = native
   cells, level k aggregates `2^k × 2^k` native cells by a PINNED kernel (e.g. mean for
   DSM elevation, nearest for masks — kernel choice is an owner decision, §8). Level choice
   is a pure function `level = f(viewportMetresPerPixel, devicePixelRatio, sourceGSD)` with
   a recorded threshold table; the same (viewport, source, table-version) MUST resolve to
   the same tile set. The chosen `lod` (level + table version + kernel id) is recorded in
   the derivative identity (§2) and in the session's browse context (UX contract §3).

What is claimed / not claimed about composition: adjacent prepared windows may be
placed edge-to-edge on screen as independent verified rectangles sharing exact cell
edges; that placement is DISPLAY assembly, not a new measurement, not resampling, and
not registration evidence. No smoothing across seams, no hidden overlap blending, no
reprojection — any of those would be a new transformation requiring its own contract,
profile digest and evidence (ADR-KSI-037 D5 forbids silent correction).

## 4. Request behaviour under zoom/pan

Viewport → window resolution (normative behaviour, wire shape in §8):

1. A viewport resolves to the MINIMAL covering set of same-level tiles on the fixed
   tiling origin (§3): compute the native-grid bounds of the viewport, expand by the
   floor/ceil rule ONCE to cell edges, then partition — never issue one PREPARE per
   pointer-move sample.
2. Deduplication: in-flight and cached requests are keyed by
   `(assetRef, pixelWindow, lod, styleVersion, validityVersion)` (= `derivativeId`
   inputs). An identical key in flight is JOINED, not re-issued (idempotency key reuse,
   SDP-REQ-07). Overlapping-but-unequal viewports do not cancel each other's covering
   tiles; only tiles fully outside the new viewport become cancellation candidates.
3. Cancellation: tiles that leave the viewport (plus a small hysteresis margin, owner to
   fix — proposed 0.5 viewport) are cancelled via the existing job cancel path; tiles
   still covering any visible pixel run to completion. Pan-back within the retention
   window MUST be a cache hit, not a new PREPARE.
4. Budget per interaction (MEASURED — GAP-06 load evidence, 2026-10-21): the lane
   accepts at most **2 concurrent** preparations; a third parallel issue is rejected
   with a fast, RETRYABLE `429 CONCURRENCY_LIMIT_EXCEEDED` and is **not parked**.
   The effective request buffer is therefore **ZERO** — `maxQueueDepth`/
   `maxPendingRecords` (8) have no reachable enforcement on this route — and there is
   no server FIFO, so the CLIENT must sequence at most 2 at a time. A full 1022x915
   cover at ≤512 px needs exactly 4 windows (512x512, 510x512, 512x403, 510x403) =
   2 waves ≈ 12 s on an idle lane; a ~15 s per-interaction budget is the measured
   recommendation. The client MUST issue at most 2 concurrently, dedupe by the stable
   (assetRef, pixelWindow, purpose) key, back off and retry the retryable 429 with
   bounded attempts, and render the covering set progressively with explicit
   "준비 중인 창 N개" placeholders. Numbers above are measured, not placeholders.
5. Concurrency/saturation UX (measured, superseding the earlier assumption of an
   8-deep queue): when the lane is saturated the UI MUST show a named state per
   tile-group ("창 2개 준비 중 · 다음 창은 순차 처리됩니다") with cancel affordance —
   never a blank Site, never a silent latest-fallback, never a synthetic low-res fill
   presented as data (INV-040; UX contract §5), and never a claim that windows are
   "waiting in a queue" when the server actually rejects them. A below-1024 viewport
   restriction is preserved: viewing an existing representation must not silently
   issue an otherwise-forbidden PREPARE/analysis POST (UX contract §4 responsive rule).
6. Demosaic/seam claim: screen composition of adjacent verified windows is allowed as
   edge-exact placement only (§3). The UI must label it as such (proposed wording:
   "검증된 준비 창의 나란한 배치 — 이음새 보정·재표본화 없음"). Any seam-hiding filter
   is forbidden without a new approved profile.

## 5. Registration & cross-epoch comparison

The ADR-KSI-037 D5 rule is absolute and repeated here normatively:
**"A common grid is not evidence that the two observations are spatially registered;
the recorded transform/evidence states that limitation."**
Equal CRS alone does NOT make pixel-wise comparison valid. Coordinate transformation
alone is not enough — registration error and valid-area must be managed separately.

Required evidence for spatial comparison (beyond equal CRS):

- An explicit pair transform/registration record with its OWN identity and status —
  proposed `PairRegistrationV1 { baselineAssetRef, currentAssetRef, methodId+version,
  transformParameters, validAreaRule, errorMetricsOrNull, status: REGISTERED | UNREGISTERED,
  evidenceDigests[] }` (NEW; owner to approve, §8). Acceptable methods/evidence are an
  owner decision (GAP-03); this contract does NOT invent a survey-grade inference.
- Compatibility preconditions inherited from INV-053/ADR-KSI-037 D3: both epochs'
  Analysis Readiness known, same versioned profile where quantitative, CRS + vertical
  reference known and compatible, source lineage known, common valid area computable.
  Any gap → typed blocker, no number, no optimistic fallback.

States when registration is absent (normative UI rule):

- ONLY independent viewing of the two epochs is allowed (side-by-side maps with SEPARATE
  navigation state clearly labelled "독립 보기 — 정합 근거 없음").
- Synchronized pan/zoom, shared crosshairs, difference colouring, or any "same-pixel"
  language is FORBIDDEN. The UI must not present unregistered epochs as quantitative
  comparison — proposed mandatory wording: "두 시점의 좌표계는 같으나 정합 근거가 없어
  같은 픽셀 비교를 표시하지 않습니다. 각각 독립 보기로 탐색하세요."
- This is distinct from "same CRS / common grid" (a regridding fact, e.g. the V2 current→
  baseline bilinear resample) vs "registered" (a claim about the real world with error
  bounds). The V2 profile's own text is the model: it "performs no automatic horizontal
  shift … A common grid is not evidence that the two observations are spatially
  registered" (ADR-KSI-037 D5).

## 6. Permission + cache

Every display byte access is bound by the existing grant/revocation/validity model —
the cache adds NO independent authority:

- Cache-key MUST include the rights binding: `(derivativeId, grantDigest, policyDigest,
  purpose)`. A cache entry is addressable only with a live grant check.
- What a cache entry MUST re-check on EVERY use (hit or serve):
  1. grant still exists and `is_current_at(now)` (`spatial_data_authority.py:123–125`);
  2. no matching `SpatialDataRevocationV1` has arrived (`:128–136`);
  3. `purpose` still authorizes the use (GENERAL_DATA_USE vs EXTERNAL_AI are distinct);
  4. requester ownership: the serving principal is the SAME principal the bytes were
     prepared for — another principal is denied 404/403 exactly as the live read path
     (INV-060; do not fold scope mismatch into a distinguishable error).
  Failure of any check → the cached tile MUST stop being served (fail-closed); the UI
  shows the truthful revocation/expiry state per UX contract §5 and preserves history
  where authorized — it never substitutes a newer version.
- Retention/expiry: prepared-output retention follows the existing policy
  (`retention_seconds`, cleanup loop that deletes only owned output versions, provisioning
  §5) — the display contract adds no second TTL; the delivery `retention_seconds` and the
  HTTP/cache TTL are distinct values and must be labelled as such (open decision §8).

Shared cache across principals: **NOT possible under the current grant model.**
Grants bind `beneficiary_principal_id` + `organization_id` + `allowed_bounds` + purpose
(`spatial_data_authority.py:85–108`), and reads are requester-owned (§0.5). A shared tile
cache would either leak bytes across principals (INV-060 violation) or require re-granting
authority the cache does not have. Implication for the design: the cache is
**per-principal (and per-purpose)**; cross-principal deduplication is limited to the
SEALED SOURCE bytes (already Core-held), never to prepared display bytes. Any future
shared-cache proposal needs a new threat model + independent security review (GAP-05)
and is explicitly out of this contract.

## 7. Epoch switch & site entry

### Extent continuity across an epoch switch (normative)

- The viewport's spatial extent is expressed ONCE in a display CRS chosen for navigation
  (owner to fix; WGS84 placement only where a supported transform exists — otherwise
  original-plane viewing per UX contract §4/§5).
- Switching epoch RE-PROJECTS that extent into the new epoch's native grid through the
  floor/ceil rule (§3) and re-resolves tiles there. The old epoch's `actualBounds` are
  NEVER reinterpreted as the new epoch's bounds; non-overlapping ranges yield an explicit
  "이 시점에 해당 범위의 관측 없음" state, never a stretched or shifted image.
- The comparison draft (baseline/current selectors + WorkArea + display context, UX
  contract §3) survives the switch; the calculation polygon does not move with the
  viewport (UX contract §4: "The viewport is not the calculation polygon").

### Site-entry policy (Human-specified, normative)

1. One area → auto-enter that area.
2. Several areas + a SAVED task context → restore that context (exact selectors + saved
   spatial context; recheck permissions/current availability without rewriting intent —
   UX contract §3 resolution priority).
3. Several areas + NO saved context → show the site's area list/overview (NOT a forced
   chooser modal).
4. An unauthorized or no-longer-valid context is NOT auto-restored → fall back to (1)/(3)
   with a truthful "저장된 작업 맥락을 사용할 수 없음(권한/만료)" state; never silently
   substitute the latest.
5. If there is NO legitimate spatial data for the whole site, do NOT merge area
   coordinates into a synthetic site map — show the honest empty/recovery state (UX
   contract §5 "No registered observation" row; INV-040).

### Where a SAVED task context lives (design only)

A durable saved-work store (cross-device resumable comparison drafts / result links per
UX contract §3) does NOT exist as an продукт capability today — the rebaseline ledger
and UX contract §7 both list typed browse/comparison/result restoration and durable
saved-work persistence as prerequisites needing owner contracts. This contract therefore
specifies only the RESOLUTION SEMANTICS above and the serializable context shape
(`{ siteId, workAreaId, baselineRef, currentRef, pixelWindow-or-viewport, lod, layer,
contextVersion }` for URLs/local drafts, never tokens/keys/bytes — UX contract §3 URL
rule). The durable store itself is a separate capability with its own approval; nothing
here creates it.

## 8. Contract surface (proposed — names, fields, owners, open decisions)

Proposed NEW records (exact names are proposals; owner modules must approve):

| Record | Fields (minimal) | Owner module (proposed) |
|---|---|---|
| `DisplayDerivativeV1` | §2 shape; `derivativeId = sha256(canonical)` | `packages/event-contracts` (schema) + Core delivery (binding) + `packages/geo-spatial` (geometry rules) |
| `PairRegistrationV1` (+ explicit `NONE`) | `baselineAssetRef, currentAssetRef, methodId+version, transformParameters, validAreaRuleVersion, errorMetricsOrNull, status, evidenceDigests[]` | Core quantity/ingress owners (evidence semantics) + `packages/geo-spatial` (transform math); status enum owned with INV-053 gate owners |
| `DisplayTileSetV1` (viewport resolution) | `viewportBounds, displayCrs, lod, tileKeys[derivativeId…], budgetDecision, omittedTiles[]+reasons` | Dashboard (resolution algorithm) + Core delivery (budget/policy facts) |
| `DisplayCacheEntryV1` | `derivativeId, grantDigest, policyDigest, purpose, preparedForPrincipalHash, storedAt, lastRightsRecheckAt` | Core delivery (rights re-check) + Dashboard/service cache holder |

Extended (not new): grant `operations` gains no new value — display reads reuse `READ`;
derivative preparation reuses `PREPARE`. No new purpose is proposed (GAP-05 review decides
whether display-vs-AI needs one).

Wire/API surface — SHAPE ONLY, no invented endpoints: future display reads would be
bounded GETs keyed by `(assetRef, pixelWindow, lod, styleVersion)` returning either verified
bytes (with `outputSha256/size` gate before decode, as today) or typed failures
(`NOT_READY → WAIT_FOR_COMPLETION`, preview kinds `UNSUPPORTED/BAD_RECEIPT/TOO_LARGE/
TIMEOUT/CANCELLED` — audit proposal §4 S3). No endpoint path, method, or response schema
presented here exists; claiming otherwise is forbidden.

Existing owner modules to inspect before edits (no change authorized here):
`services/core/src/ksi_core/domains/external/delivery/jobs.py`,
`…/delivery/job_projection.py`, `packages/event-contracts/src/ksi_event_contracts/spatial_data.py`,
`spatial_data_authority.py`, `spatial_data_worker.py`,
`packages/geo-spatial/src/ksi_geo_spatial/external_native_window_geometry.py`,
`services/processing-controller` display/preparation workers,
`apps/dashboard/src/app/sites/[siteId]/`, `…/lib/site-windowed-pixel-viewer.ts`,
`…/lib/spatial-data-preview.ts`, `…/lib/spatial-data-request.ts`.

Exact open decisions needing owner approval:

1. LOD pyramid table (levels, thresholds, kernels for DSM vs ortho vs masks) — GAP-03.
2. Per-interaction PREPARE budget N and ordering — **ANSWERED BY MEASUREMENT** (GAP-06 evidence
   2026-10-21): 2 concurrent, 2 waves for a full 1022×915 cover (4 windows), ~15 s per interaction,
   client-sequenced (the server has no FIFO and no usable queue depth). Remaining sub-question: the
   exact client-visible back-off schedule.
3. `PairRegistrationV1` acceptable methods/evidence and who may assert REGISTERED — needs
   spatial + quantity owners; NO survey-grade inference is pre-approved.
4. Display-cache TTL vs delivery `retention_seconds` labelling and per-principal store
   placement (memory/disk/service) with cleanup-loop ownership.
5. Display CRS for navigation where epochs differ; original-plane fallback wording.
6. Style/validity policy registries (colour-ramp/stretch/mask-rule version pins) — new
   micro-registry or reuse of profile digests?
7. Durable saved-work store — separate capability, separate approval (§7).
8. Whether any `PURPOSE` split between human viewing and EXTERNAL_AI display use is
   needed — GAP-05 threat-model review.

What could NOT be specified faithfully (and why): numeric LOD thresholds and cache sizes
(no load measurement exists — GAP-06 forbids guessing resource numbers, ADR-KSI-038 D4);
the registration method list (depends on future customer evidence and GAP-03 determination,
and any choice here would risk weakening INV-053); the saved-work persistence schema
(no durable store exists); shared-cache feasibility beyond the §6 refusal (would need a
new threat model). Each is marked OPEN above rather than invented.

## 9. Acceptance (for the future implementation)

Testable criteria (all against real bounded native-window lanes, never mocks alone):

1. **Seam exactness:** two adjacent prepared windows of one source compose edge-to-edge
   with zero gap/overlap at every LOD; a test asserts shared cell-edge equality from
   receipts (`pixelWindow` contiguity + `actualBounds` abutment) and rendered-pixel
   comparison on a reference fixture.
2. **No duplicate requests:** a scripted zoom/pan gesture sequence issues exactly one
   PREPARE per distinct `(assetRef, pixelWindow, lod, style)` key; in-flight joins are
   logged; replay of the gesture from cache issues zero new PREPAREs.
3. **Budget behaviour (measured):** the lane admits 2 concurrent preparations and
   rejects a third with a retryable 429 (no queue). An interaction exceeding the
   2-slot budget shows named "준비 중인 창 N개" states with cancel, retries the
   retryable rejection with bounded back-off, and never claims a server-side wait
   queue; no silent fallback, no blank site, no synthetic fill.
4. **Cache re-check blocking:** after grant revocation or expiry, cached tiles for that
   grant stop serving on next use (test: revoke → re-request same tile → 404/403 +
   truthful UI state; other principal's tiles unaffected).
5. **Registration refusal:** two same-CRS epochs with `PairRegistrationV1 = NONE` allow
   independent viewing only; any synchronized-compare affordance is absent/disabled with
   the mandatory wording (§5); a test asserts no shared-crosshair/difference path exists.
6. **Epoch-switch extent continuity:** switching epoch preserves the display extent and
   re-resolves native tiles; non-overlap yields the explicit no-observation state, never
   a stretched image; the calculation polygon is byte-identical before/after.
7. **Entry policy:** one-area auto-enter; multi-area + saved context restores; multi-area
   without context shows area list/overview (no forced chooser); invalid context is not
   restored; a site with no legitimate data shows no synthetic merged map.
8. **Three-state separation:** audit-integrity, per-purpose suitability, and viewability
   are rendered with distinct vocabularies (audit proposal §4.3–4.4 word lists); no test
   may pass with a single composite flag, and no green display state implies quantitative
   eligibility.
9. **Source/result stability:** changing display colour/LOD for a DSM leaves the source
   version referenced by an old volume result byte-identical (result re-query returns the
   original selectors/evidence); correction creates a new submission version with distinct
   inputs for any new run.

Real customer/field acceptance still needed beyond these: an actual customer DSM/ortho
pair with rights and licences (GAP-01/02), a second host/cycle rerun, OIDC/operator-host
evidence, and business acceptance (payment/operations) — per roadmap P-AC-01..06 and
GAP-08/09. Local software evidence must never be presented as customer/field acceptance.

---

## Handoff summary (for the parent session)

- File created: `docs/design/SPATIAL_DATA_DISPLAY_LOD_CONTRACT_PROPOSAL_2026-10-21.md` (this document).
- Key decisions: two-identity split (stable SOURCE vs content-addressed regenerable
  DISPLAY-DERIVATIVE, §2); native-grid integer-window addressing with source-origin tiling
  + receipt-verified composition only (§3); viewport→tile resolution with dedupe/cancel/budget
  + saturated-lane UX (§4); explicit `PairRegistrationV1`-or-NONE gate with independent-viewing-only
  fallback and mandatory wording (§5); per-principal cache with rights re-check on every use,
  shared cache refused under current grant model (§6); Human entry policy + extent continuity
  without reinterpretation + saved-store-as-separate-capability (§7).
- Exact open decisions: §8 items 1–8 (LOD table/kernels; budget N; registration methods;
  cache TTL labelling/placement; display CRS; style/validity registries; saved-work store;
  purpose split).
- Implementation prerequisites (dependency order): (i) owner approval of §8 records +
  LOD table (GAP-03) and budget numbers after load measurement (GAP-06); (ii) Core
  delivery + geo-spatial owners implement derivative binding/tiling origin/cache re-check;
  (iii) Dashboard replaces the temporary adapter against the approved contract;
  (iv) registration-evidence owner defines `PairRegistrationV1` methods; (v) security
  review for any cache/purpose change (GAP-05). Audit recovery stays independent throughout.
- Remains undecidable today: numeric LOD/cache thresholds (no measurements); registration
  method list (future evidence); saved-work persistence (no store); any shared-cache design
  (threat model missing) — all marked OPEN, none invented.
