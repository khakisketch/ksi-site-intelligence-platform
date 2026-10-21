# Site entry and context-restoration rules (subordinate design)

Date: 2026-10-21. Baseline: main `3568f5b2`.
Track: Site/WorkArea entry and context restoration. Parallel track: display/LOD contract (separate owner; referenced here only as a dependency).

**Status:** Design proposal only. No source, contract, runtime, policy, endpoint, or storage change is made or authorized by this document. All wire/storage additions below are explicitly marked **PROPOSED** and require Core + Console owner approval with contract and replay tests before implementation. Nothing here weakens any permission, scope, or quantity gate.

**Subordinate to:** `SITE_SPATIAL_WORKSPACE_UX_CONTRACT.md` (§3 entry/restoration, §4 modes, §7 prerequisites), the rebaseline task ledger workspace-delivery sections, ADRs KSI-036/037/038/039, the Constitution/Decision Ledger/PRD, and the three-state separation (audit integrity vs validation suitability vs viewability — never merged).

**Verified starting facts (read, not re-described):**

- The Core observation projection is **per WorkArea**: `GET /v1/sites/{site_id}/work-areas/{work_area_id}/spatial-workspace-observations` (`services/core/src/ksi_core/domains/external/ingress/site_spatial_workspace.py:506`). Its `entryDefault` is **per area**, grouping by `observationEpochId` and selecting one server-owned default observation with an explicit reason (`LATEST_EXACT_VIEW_AVAILABLE` / `NO_OBSERVATIONS` / `NO_VIEW_AVAILABLE_OBSERVATION` / `NO_EXACT_CAPTURE_CANDIDATE` / `CAPTURE_TIE_AMBIGUOUS`) — contract `packages/event-contracts/src/ksi_event_contracts/site_spatial_workspace.py:59-64`, logic `site_spatial_workspace.py:376-450`.
- The Console never computes its own "latest": `resolveOrdinaryEntry` uses only the server `entryDefault` (`apps/dashboard/src/lib/site-workspace-entry.ts:152-189`), and the server-facts adapter copies `entryDefault` verbatim (`apps/dashboard/src/app/sites/[siteId]/site-workspace-server-facts.ts:101-124`).
- The Console's **area choice today is an incumbent bound/recency heuristic**, not a server decision: `resolveSelectedWorkAreaId` prefers work-order-bound areas, then analysis-bound areas, then most-recently-created (`apps/dashboard/src/app/sites/[siteId]/site-spatial.ts:40-62`). The projection names no site-level area — this is the remaining gap this design addresses.
- Only the **selected** area's projection is read; facts carry only that area's observations (`page.tsx:149-154`, `:168-189`; `site-workspace-server-facts.ts:146-155`). Fallback to `pickFootprintAsset` when no server default exists is explicitly marked transitional, not a default (`page.tsx:238-254`).
- Explicit intent (observation / comparison / result) restores exactly or fails closed — never silently defaults (`site-workspace-entry.ts:252-369`; `page.tsx:286-323`).

---

## 1. Decision table for site entry

### 1.1 Inputs (all evaluated in this order)

| # | Input | Values | Owner of the fact |
|---|---|---|---|
| I1 | Explicit intent present? | none / observation-link / comparison-link / result-link | Console URL parse (`page.tsx:220-232,279-298`); resolution in `site-workspace-entry.ts` |
| I2 | Saved task context present? | none / present (see §3) | **PROPOSED** durable store (does not exist today); browser URL/local draft is NOT a saved context |
| I3 | Number of **authorized** (ACTIVE + permitted) WorkAreas | 0 / 1 / N>1 | Console from `listWorkAreas` filtered ACTIVE (`page.tsx:119-120`) intersected with scope; authorization rechecked per read |
| I4 | Validity of the I1/I2 target | valid / invalid-unauthorized / invalid-stale (see §1.3) | Rechecked at entry: scope membership + projection facts + permission result |
| I5 | Server default for the chosen area | `LATEST_EXACT_VIEW_AVAILABLE` (+epoch/asset) / other explicit reason / `NO_PROJECTION` (unread/denied) | Core `entryDefault` verbatim (`site-workspace-entry.ts:101-114`) |

**Resolution precedence (normative): explicit intent > saved context > ordinary entry.** This preserves UX contract §3 ("explicit result/work/context before ordinary entry"). A saved context never overrides an explicit link carried in the same navigation; ordinary entry never overrides either.

### 1.2 Decision table

"Resulting state" names the exact UI contract; "what the user sees" is the observable requirement.

| Case | I1 explicit | I2 saved | I3 areas | I4/I5 | Resulting state | What the user sees |
|---|---|---|---|---|---|---|
| E1 explicit-valid | present | any (ignored) | any | target valid + authorized | **Restore exactly** in the indicated mode/area/versions | The named observation / two-version comparison / result with original selectors, area, mode. No substitution, no "newer available" auto-switch (offer as separate explicit action only) |
| E2 explicit-invalid | present | any (ignored) | any | target unauthorized, unknown, unavailable, or cross-area | **Fail closed + recovery choice** | Truthful headline naming the failure class (malformed / foreign-work-area / unknown-observation / unknown-asset / unavailable / unknown-result / identical-selectors / cross-area-comparison — `site-workspace-entry.ts:191-207`), the reason it cannot be shown (rights changed, retention changed, revision superseded), and an explicit recovery choice: area list (case S3/S4) or retry. **Never** silently fall back to a default or to "the other side" of a broken comparison |
| S1 no-areas | none | none or invalid | 0 | — | **No-area site state** | Site identity + "no authorized WorkAreas for this account" + who to contact / registration path if permitted. Not an empty map, not "no data". Unknown vs denied reads stay distinct (areas read failure ≠ empty list) |
| A1 single-area auto-enter | none | none or invalid | 1 | I5 = `LATEST_EXACT_VIEW_AVAILABLE` | **Auto-enter the one area, server default observation** | Explore mode in the single area with the server-default observation/version. Area identity shown as fact ("Site has one work area: …"), not as a choice the user made |
| A2 single-area, no server default | none | none or invalid | 1 | I5 = other reason / `NO_PROJECTION` | **Enter area shell, honest state panel** | Area shell with the server's reason verbatim (no observations / none view-available / none exactly orderable / tie-ambiguous / projection unreadable-or-denied). Date-only/unknown observations remain browsable in a labelled group; pending-representation versions are labelled with exact version + pending state (`newerRevisionPending`), never "no data" |
| S2 multi-area + valid saved context | none | present + valid | N>1 | saved area authorized, saved selectors still resolve, I5 of saved area consulted for *display* only | **Restore saved context** | The saved area/mode/observation/version/viewport exactly (see §3). A newer server default does NOT displace it; offer "newer version available — open as new comparison" only as an explicit action |
| S3 multi-area, no (valid) saved context | none | none or invalid | N>1 | — | **Site area list / overview (NOT a chooser)** | Site identity + the authorized area list with per-area facts (see §2) + the legitimate next action per area. No "which area?" modal, no forced chooser screen, no auto-entered area implied to be "the site". If the user then picks an area, ordinary entry within that area follows A1/A2 rules (server `entryDefault` of that area) |
| S4 multi-area, all areas view-unavailable | none | none or invalid | N>1 | every area's I5 ∈ {`NO_OBSERVATIONS`, `NO_VIEW_AVAILABLE_OBSERVATION`, `NO_EXACT_CAPTURE_CANDIDATE`, `CAPTURE_TIE_AMBIGUOUS`, `NO_PROJECTION`} | **Overview with per-area reasons, no merged picture** | Same S3 list; each row carries its own server reason. Forbidden: merging extents/rasters into one synthetic site map to "fill" the empty overview (see §2) |
| S5 saved-context-invalid | none | present + invalid | any ≥1 | unauthorized (area revoked, rights changed) or stale (area/epoch/version gone, comparison leg broken, retention expired) | **Do NOT restore; fall back to A1/A2/S3 + truthful notice** | The ordinary-entry state the user would have seen without the context, plus a dismissible notice naming the invalidation class and the stored context's age/area (never its bytes). Never auto-repair by substituting a "closest" version |

Notes:

- **S2 validity is rechecked on every restore** (I4): area still ACTIVE + authorized, epoch still registered, each referenced `assetRef`/`submissionRef`/`revision` still resolvable, comparison legs still two distinct display-ready chronology candidates, rights (`SITES_READ` + area scope + `SPATIAL_DATA_READ` for bytes) still held. Any failure → S5.
- **E2 vs S5 wording differs deliberately:** E2 says "the link you followed cannot be shown"; S5 says "your saved work could not be reopened". Both offer the same recovery surface (area list), but S5 must not delete the saved context (it may become valid again after a transient outage — see §3.4 deletion rules).
- **Zero authorized areas (S1) short-circuits everything except E1/E2 handling:** an explicit link into an unauthorized area is E2 (foreign-work-area), not S1, so the user learns the link target exists-but-is-unavailable rather than "site has no areas".
- **Client-side "latest" ranking is forbidden in all cases.** Only `LATEST_EXACT_VIEW_AVAILABLE` from the server may select an observation. The incumbent `resolveSelectedWorkAreaId` recency/binding heuristic (`site-spatial.ts:52-61`) must be retired for workspace entry once the site-level area decision (§6.1) exists; until then it is a **transitional Console concern** and its output must be labelled transitional (as `transitionalSelection` already does at `page.tsx:254`), never presented as a server default.

### 1.3 Invalid/stale taxonomy (shared by E2 and S5)

| Class | Meaning | Example trigger |
|---|---|---|
| `foreign-work-area` | Target area not in `authorizedWorkAreaIds` | Rights revoked, area archived, wrong account |
| `unknown-observation` / `unknown-asset` | Epoch or exact version no longer resolves | Corrective revision chain moved, retention expired, cross-site link |
| `unavailable` | Resolves but not display-ready / not chronology-eligible | Receipt unsealed, inspection failed, capture precision only date-only for a comparison leg |
| `cross-area-comparison` | Two legs span different areas | Saved comparison whose area binding changed |
| `identical-selectors` | Both legs identical | Corrupt/degraded saved draft |
| `unknown-result` | Analysis/result identity no longer authorized | Result retention/permission change |

---

## 2. What a site-level overview may show (no synthetic site map)

### 2.1 The honest substitute for "see the site as one picture"

When no legitimate whole-site spatial representation exists (the normal case until the display/LOD track delivers a site-wide product — see dependency note), the overview is a **site identity header + authorized area list + per-area evidence facts**. The user's mental model is "this site has N work areas; here is what each one actually holds", never "here is the site".

Required content per site overview:

1. **Site identity once** (name, status, site-level AOI state: set/unset — the site AOI is a *selection setting*, not spatial data; `page.tsx:404-408`).
2. **Authorized area list**, one row per ACTIVE authorized area the caller may see: disambiguated area name (`disambiguatedAreaNames`, `site-spatial.ts:239-257`), area status, and per-area:
   - observation count and capture-precision breakdown (N exact-interval / N date-only / N unknown) from that area's projection facts;
   - the area's **server** `entryDefault` reason + (if `LATEST_EXACT_VIEW_AVAILABLE`) the default epoch id at real precision — shown as "entry observation for this area", never as "latest capture on this site";
   - per-area **separate** extents (WorkArea polygon where `selectableGeometry` is non-null; inspected raster footprints where available) drawn as **distinct labelled items in a list or on a neutral plane**, each tagged with its area and CRS.
3. **Latest usable analysis records with their area** (existing `analysesForArea` binding, `site-spatial.ts:294-300`): analysis id, its WorkArea, baseline/current selectors at real precision, result state. No cross-area "latest analysis" headline.
4. **Per-area unavailable reasons** where applicable (S4): the server reason verbatim; pending-representation versions named with exact version + pending state.

### 2.2 Forbidden substitutes (normative)

- **No merged/aligned raster**: never mosaic, stitch, reproject-guess, or co-display two areas' rasters/tiles on one plane as if they were one site image.
- **No combined geometry pretending to be one site**: never union WorkArea polygons or footprint rings into a "site extent". Per-area extents stay separate list items; a neutral index plane (numbered slots, not ground coordinates) is the only permitted shared visual until the display track provides a legitimate site-wide representation.
- **No area ranking that looks like "latest"**: never sort areas by capture time, `submittedAt`, recency of creation, or observation count to imply one area is current. Area order is stable administrative order (name/workAreaId), and any "entry observation" label is per-area server-owned.
- **No default area implied by recency**: the incumbent `byRecency` fallback (`site-spatial.ts:52-55`) must not surface in the overview as a highlighted/pre-selected area.
- **No capture-time synthesis**: date-only stays date-only; unknown stays "cannot be determined" (`workspaceCaptureLine`, `site-workspace-entry.ts:422-441`). Unknown-date observations are listed in a separate labelled group, never interleaved by `submittedAt`.

### 2.3 Dependency on the display/LOD track

This section specifies the overview **without** a site-wide legitimate spatial representation. If the parallel display/LOD track later delivers a server-owned site-wide representation (registered mosaic, declared site CRS/LOD contract, recheckable byte authority), the overview may show it **only** under that track's contract: bound geometry/transform/evidence, renderer/units/scale semantics, and explicit pair/site registration. Until then, §2.1 is the complete permitted overview. The display track owns tiles/LOD/registration; this track owns entry/selection/restoration and must not pre-empt it.

---

## 3. Saved task context

### 3.1 Problem statement

Today there is **no durable cross-device saved-work store**: `operator-journey.ts` carries area/current hints; a browser URL/local draft is explicitly "not evidence of durable cross-device saved-work storage" (UX contract §3). Saved context is therefore a **new capability**, and this section specifies its content and rules. **Durable storage itself is a separate owner decision** (backend store, API, retention, quota — not specified here and not smuggled in as URL parameters, which must never carry tokens, byte URLs, object keys, or raster bytes).

### 3.2 Exact content (all source identities, no bytes)

A saved context record contains **only** these fields:

| Field | Type | Notes |
|---|---|---|
| `contextId` | server-issued opaque id | **Identity of the stored context, not the asset identity** (see §3.3). Never derived from asset hashes |
| `siteId` | exact site id | Scope anchor |
| `workAreaId` | exact area id | Comparisons are single-area; cross-area legs are rejected at save and at restore |
| `mode` | `explore` \| `compare` \| `results` | Working mode (UX contract §4) |
| `observationEpochId` (+ `observationEpochIdBaseline/Current` for compare) | exact epoch identities | Grouping key; never a date bucket |
| `baselineSelector`, `currentSelector` (compare/results) | `{ workOrderId, submissionRef, revision }` exact submission selectors | The **source** truth (cf. `WorkspaceAnalysisSelector`, `site-workspace-entry.ts:89-93`). `assetRef`/`artifactId` recorded alongside as the resolved view version, but selectors are authoritative on re-resolution |
| `viewAssetRef(s)` | resolved display version(s) at save time | Used only to detect "newer version exists" offers; never to override selectors at restore |
| `analysisId` (results mode) | exact result intent | Resolved via existing historical-access path when that contract exists; otherwise restore degrades to compare/explore with notice (never a different result) |
| `displayState` | `{ layer, crs, viewportExtent, scale/legend settings }` | **Re-derived display preference, not truth.** Viewport extent stored as plain numbers in the display CRS for convenience re-framing only (see §5). Layer choice limited to ortho/DSM availability |
| `savedAt`, `savedBy` (principal), `schemaVersion` | bookkeeping | For invalidation messaging and migration |

Explicitly **excluded**: raster bytes, signed URLs, object keys, tokens, inspection digests as authority, quantitative eligibility verdicts, cross-area mosaics.

### 3.3 Identity rule

- The **stored context identity** (`contextId`) identifies the *reminder*, not the *data*. It grants nothing, proves nothing about the assets, and is never shown as evidence.
- The **asset/source identities** (epoch id, submission selectors, `assetRef`, digests) identify the *data* and are the only thing a restore resolves against.
- The **analysis/result identities** (`analysisId`, report/reportDigest) identify the *calculation*; restoring a result re-resolves them through the authorized historical-access path, never from cached numbers in the context.

### 3.4 Invalidation rules (checked at every restore, in order)

1. **Scope/permission**: site/area not visible to the current principal, or `SITES_READ` / area scope / `SPATIAL_DATA_READ` no longer held → `foreign-work-area`, do not restore.
2. **Area binding**: area archived/deleted or (for compare) legs now span areas → invalid.
3. **Observation/epoch**: referenced epoch id no longer registered for the area → `unknown-observation`.
4. **Version selectors**: exact `{submissionRef, revision}` no longer resolvable, or resolved version no longer `displayReady` / no longer chronology-eligible (for compare legs) → `unavailable`. A superseding corrective revision does **not** auto-replace; it triggers the "newer version available" offer only.
5. **Result**: `analysisId` no longer authorized/resolvable → restore degrades to the comparison/explore half that still resolves (selectors intact) with an explicit notice; never a different result.
6. **Expiry**: owner-defined TTL (open decision, §6.3) elapsed → expired; the record is tombstoned, not silently reinterpreted.

Deletion/retention: user-initiated delete removes the record; expiry tombstones it (restores then report "expired" per S5 rather than resurrecting); revocation of the *underlying data* never deletes the *record* (history preserved, restore reports truthfully).

### 3.5 Ownership / visibility

- A saved context is owned by its saving principal (user), visible only to that principal by default. Sharing, team workspaces, or org-wide defaults are **not** introduced here (open decision, §6.3).
- Saving and restoring recheck the same gates as browsing: no saved context bypasses scope, permission, retention, or requester-ownership rules (costly-failure class in UX contract §1: "cache/shared URL bypasses current scope/rights").
- Reads of the store return only records whose referenced site/area the caller is currently authorized for (fail-closed listing: unauthorized records are omitted, not error-surfaced with metadata).

### 3.6 Coexistence with source-vs-display-derivative separation

- A saved context points at **source identities** (epoch + submission selectors). Display tiles/LOD/colour are **regenerable derivatives**: re-derived at restore from current display delivery under current rules, never persisted as truth.
- Restoring a context re-resolves selectors → re-derives display. A display change (new LOD, new colour ramp, new tile backend) therefore **never invalidates, rewrites, or versions** the saved context; the context's `displayState.viewportExtent` is a framing hint re-applied to freshly derived tiles.
- Conversely a **new source version never silently replaces** the restored context's selectors (correction rule, UX contract §2). The UI may offer "open these selectors with the newer revision as a new comparison" — a new draft, not a mutation.

---

## 4. Source vs display identity (entry/restore scope only)

Normative principle (unchanged, restated only as it affects this track): **display tiles and derivatives are regenerable and cacheable; the source data version and the input identity referenced by an analysis result stay stable.**

Consequences for entry and restore:

1. A restore resolves **source identities first** (epoch, selectors, result ids). Display readiness (`displayReady`, `viewAssetRef`) gates *whether* the resolved source can be shown, never *which* source is shown.
2. A change in display delivery or LOD **must not invalidate or rewrite** a restored context (see §3.6).
3. A new source version (corrective revision, re-inspection, new receipt) **must not silently replace** a restored context's selectors (see §3.4 rule 4).
4. Cache/byte access is always rechecked at restore time under the current principal; a previously viewable version that is now retention-expired or permission-revoked reports `unavailable`, preserving history where authorized but stopping byte access.

---

## 5. Epoch-switch extent continuity

When the user switches observation epoch within one WorkArea (explore re-view or compare-leg change), the viewport extent is carried as a **display-convenience re-framing**, under these rules:

1. **Carry the extent numbers, not the ground meaning.** The new epoch's view re-applies the previous viewport rectangle (in the shared display-coordinate plane already established for that area session) so the user keeps their place. This carry **implies no registration, no co-alignment, and no "same ground" claim** between the two epochs.
2. **CRS/plane guard:** if the two epochs' display planes differ (different declared/observed CRS per `sameDisplayPlane`, `site-spatial.ts:97-100`), do not re-apply the rectangle; reset to the new epoch's full footprint and say so.
3. **Required UI wording:**
   - Plain re-view (explore epoch switch): "표시 범위 유지 — 두 관측이 정합된다는 뜻이 아닙니다" (extent kept for reference; the two observations are not claimed to be registered).
   - Comparison leg change: additionally label each map with its own epoch + version + capture precision, keep the shared-navigation note ("같은 화면 범위, 정합 아님" — same screen extent, not co-registration), and never silently shift/rotate/vertically-correct an input to force visual alignment (UX contract §4).
4. **Synchronized comparison** (two equal maps, shared pan/zoom) is enabled only when the display track's **pairwise spatial-display registration** precondition is met (UX contract §4: bound geometry/transform/evidence, renderer/units/scale). Otherwise each map keeps independent navigation with an explicit "why sync is unavailable" note. This design does not specify that registration; it specifies the fallback.
5. **Viewport ≠ calculation polygon**, restated: carrying or changing the viewport never alters the selected WorkArea, the comparison selectors, or any run polygon (UX contract §1 costly failure).

---

## 6. Contract surface + owners

### 6.1 What the Core would need to expose (PROPOSED — requires owner approval)

| # | Proposed surface | Why | Shape (proposal, not a claim) |
|---|---|---|---|
| C1 | **Site-scoped authorized-area summary** | Entry needs per-area facts without N× per-area reads and without client ranking | Per site, for each ACTIVE area the caller may see: `workAreaId`, disambiguated name, status, observation counts by capture precision, that area's existing `entryDefault` reason (+ epoch/asset when `LATEST_EXACT_VIEW_AVAILABLE`). Read-only projection; grants no bytes; same permission/scope gates as the per-area route |
| C2 | **Site-level default-area decision with explicit reason** (only if owners accept any auto-area at all) | Human policy (a)–(d) needs a server-owned answer to "which area, if any" so the Console stops using the recency heuristic | `{ areaId \| null, reason: SINGLE_AREA / SAVED_CONTEXT_HIT / NO_SAVED_CONTEXT_SHOW_LIST / ZERO_AREAS / NO_VALID_SAVED_CONTEXT / ... , savedContextId? }`. The saved-context lookup backing `SAVED_CONTEXT_HIT` lives behind the same store decision (§6.3). If owners decline C2, S3 (area list) becomes the universal multi-area entry and the Console retires the heuristic with no replacement |
| C3 | **Saved-context CRUD + revalidation** (only if the store decision lands in Core) | §3 needs durable cross-device storage with permission-aware reads | Opaque `contextId` records with the §3.2 schema; restore-time revalidation against current epoch/version/permission facts; TTL/tombstone semantics. Alternatively owned by another service — placement is an open decision |

All three are **proposals**. No endpoint is claimed to exist. Each needs: contract-schema review, permission/scope/retention proof, pagination/bound tests, replay/contract tests, and explicit reconciliation with ADR-036 (customer-owned reconstruction; Core registers/verifies/analyzes) and ADR-038/039 (platform/data boundaries).

### 6.2 What stays a Console concern (no Core change)

- URL parsing and mode/scope plumbing (`parseWorkspaceMode`, `parseScopeId`, `parseWorkspaceScopeId`).
- Pure resolution against server facts: `resolveOrdinaryEntry`, `resolveExplicitObservation/Comparison/Result`, `splitCompareCandidates`, `representativeFacts` (`site-workspace-entry.ts`) — extended with a saved-context resolver of identical shape (exact-match or fail-closed).
- Server-facts adaptation per area (`site-workspace-server-facts.ts` + `page.tsx` orchestration), transitional labelling, recovery-choice rendering (`SiteWorkspaceShell`, entry/compare/results panels), epoch-switch extent carry (§5), and all honest-state wording.
- Owner modules: `apps/dashboard/src/lib/site-workspace-entry.ts`, `apps/dashboard/src/app/sites/[siteId]/site-workspace-server-facts.ts`, `apps/dashboard/src/app/sites/[siteId]/page.tsx`, `apps/dashboard/src/app/sites/[siteId]/SiteWorkspaceShell.tsx` (+ compare/results/entry panels), `apps/dashboard/src/app/sites/[siteId]/site-spatial.ts` (heuristic to retire).

### 6.3 Open decisions requiring owner approval

1. **C1/C2/C3 placement and shape** — Core vs another service; exact reason enums; pagination/bounds; whether C2 exists at all.
2. **Saved-context store**: owner service, schema versioning, TTL, quota, per-principal vs shared visibility, audit of save/delete. Until decided, S2/S5 cannot be implemented; S3 is the multi-area entry.
3. **Historical result/evidence access** for `analysisId` restore (UX contract §6 gap): authorized historical resolution distinct from current-use assessment. Until specified, result-mode restore degrades per §3.4 rule 5.
4. **Display/LOD contract** (parallel track): site-wide representation, pairwise display registration, tile byte authority. This design blocks on it only for §2.3 and §5 rule 4; everything else proceeds.
5. **Audit-recovery interplay**: whether restores or saves emit journal/audit records; independent track, no assumption here.

### 6.4 What could NOT be specified faithfully (and why)

- **Server-side saved-context lookup semantics** (match key: user+site vs user+site+device; last-used vs pinned): no store, principal-session, or device model was in scope to verify against — inventing one would exceed this design's authority.
- **Site-level default-area tie-breaking beyond (a)–(d)**: e.g. two areas each with a valid server default and a valid saved context each. The honest answer is "show the list with per-area defaults" (S3 enriched), not a deeper ranking — any finer rule would be client ranking by another name.
- **Exact viewport-extent wire type**: stored as display-CRS numbers per §3.2, but the canonical display CRS/plane per area belongs to the display track; this design fixes only the no-registration-implied rule.
- **Real customer/field acceptance**: Floreat date-only/unknown-vertical fixtures cover viewing/blocked-calculation honesty; no synthetic quantities on real coastal imagery; customer acceptance stays an explicit later gate (UX contract §9).

---

## 7. Acceptance (testable criteria for the future implementation)

Entry policy:

- [ ] **A1**: site with one authorized area and a server `LATEST_EXACT_VIEW_AVAILABLE` enters that area/observation automatically; area shown as fact, not choice.
- [ ] **S2**: site with several areas + a valid saved context restores that exact area/mode/selectors/viewport; newer server defaults do not displace it.
- [ ] **S3**: site with several areas + no (valid) saved context shows the site area list/overview — no chooser modal, no auto-entered area, no recency-implied default.
- [ ] **E2/S5**: unauthorized or stale explicit/saved targets are never restored and never silently replaced; the UI shows the failure class + recovery choice (area list).
- [ ] **S1**: zero authorized areas shows the no-area state (not an empty map, not "no data"); denied-vs-empty reads stay distinct.
- [ ] **S4**: all areas without a view-available observation show per-area server reasons; no merged site map is rendered.

Overview honesty:

- [ ] No test or fixture can produce a merged/aligned cross-area raster, a unioned "site extent" geometry, or an area ordering presented as "latest" from client-side data. Area order is administrative; per-area defaults are server-quoted.
- [ ] Date-only/unknown capture is labelled at real precision; unknown-date observations sit in a separate group.

Restore fidelity:

- [ ] Restored contexts resolve **source identities** (epoch + exact selectors + result ids); display LOD/colour/backend changes do not alter, invalidate, or rewrite the stored context (re-run restore after a display-only change → identical selectors).
- [ ] A new source version (corrective revision) does not silently replace a restored context (re-run restore after D2 registration → still D1 with a "new version available" offer, per UX contract correction case).
- [ ] The server default is never replaced by a client-side ranking: unit tests assert `resolveOrdinaryEntry` (and its saved-context successor) return `no-server-default` rather than a sorted pick for every non-`LATEST_EXACT_VIEW_AVAILABLE` reason, and integration tests assert the retired recency heuristic has no workspace-entry call path.

Display-track boundary:

- [ ] Epoch-switch tests assert extent carry without registration claims (wording + no silent shift/rotate/vertical correction; CRS-mismatch reset).
- [ ] Tests assert viewport changes never mutate WorkArea selection, comparison selectors, or run polygons.

Remaining for real customer/field acceptance (not closed here): actual-site entry with genuine multi-area registrations, permission-revocation and retention-expiry drills against the real Core, saved-context cross-device restore on separate hardware, accessibility/keyboard and phone-viewport review of the area list and recovery choices, and the display/LOD track's own acceptance (site-wide representation, pair registration) before §2.3 can be exercised.
