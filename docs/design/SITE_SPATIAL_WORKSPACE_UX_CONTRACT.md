# Site spatial workspace — UX contract and implementation units

Date: 2026-10-21. Source baseline: `f2b738bc`.

**Status:** Human-confirmed UX decisions, documented before implementation. Technical projections,
storage and display-delivery mechanisms below are proposals requiring owner contracts and tests.
This is not a claim of an implemented viewer, approved new endpoint, production readiness or accuracy.

## 1. Authority, goal and boundaries

Selected by the existing [rebaseline task ledger](../superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md).
Subordinate to [Read First](../00_READ_FIRST.md), the
[Constitution](../product/PRODUCT_CONSTITUTION.md), Decision Ledger, PRD §1.1.2,
applicable contracts, ADR-KSI-036/037/038/039 and the
[first-request contract](API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md). It does not change them.

Requirements: SDP-REQ-01..08. Invariants: INV-020/024/040/051/053/060/061.

**Job:** a person opens a Site, understands its actual observations spatially, compares the intended
versions in a fixed WorkArea, and follows a result to its conditions/evidence or an external consumer.
The primary audience includes the previously confirmed general/business first viewer; operators and
integration developers need deeper evidence without forcing it into that first view.

The original user complaint was “머리가 하얘질까 뭘 해야 할지 모르겠어”: duplicated headings,
an empty-looking outline, technical state summaries and competing links came before recognizable
site content and a meaningful next action. Removing words alone does not resolve that problem.

**Outcome:** enter → recognize observation and scope → explore → compare → understand result/limits
→ revisit the same result externally. Upload and validation support that workflow, not replace it.

Costly failures to prevent:
- A corrected upload silently changes an old analysis or an explicitly resumed comparison.
- A recent upload is described as the latest capture, or unknown dates become fictitious timestamps.
- Matching bounding boxes, a common grid or a convincing image imply proven co-registration/accuracy.
- A changed viewport quietly becomes the calculation area; an old result is shown under new inputs.
- A cache, thumbnail or shared URL bypasses current scope/rights or transfers another actor's job.
- A successful result GET is called proof of calculation reproduction.

Non-goals: photogrammetry/capture, 3D/BIM editing, arbitrary new analyses, global Home redesign,
new customer/public deployment, weakened gates, shared-host recovery or a standalone demo artifact.
Preserve the incumbent Console identity and global navigation; change task hierarchy, not the brand.

## 2. Observation, versions and evidence are different objects

Use this conceptual relationship, not a second identity database:

```text
Site / WorkArea
  Observation
    ortho asset version(s) ─┐
    DSM asset version(s) ───┼─ exact-byte inspections / evaluations / use decisions
                           └─ input-bound admission
  Analysis run / calculation identity
    exact baseline + current inputs / WorkArea definition / calculation conditions
    immutable result + frozen evidence references
    separate current-use assessment and human review records
```

“Validation” is a family of distinct records, not one green `verified` flag. Per-file inspection,
checkpoint evaluation, pair compatibility, admission, accuracy evidence and human review retain their
own subjects and meanings. An analysis references the appropriate records; it does not consume a
floating “latest validation”.

### Display rules

- Organize browsing around **observations**. Inside one observation, show its available ortho/DSM and
  their selected versions. Same date alone never proves that two assets belong to one observation.
- Use explicit Core epoch/relationship information. The existing continuation relation is an earlier
  run's current input reused as a later run's baseline with the **same exact selector**, Site and
  WorkArea. Distinct WorkOrders are not merged into one observation from dates or upload proximity.
- Display capture date/interval separately from export, registration and inspection dates.
- A correction creates a separately identified submission/artifact version and evidence. “Replace”
  must not mean overwriting submitted bytes or repointing an old result.
- Current registration supports contiguous corrective revisions while preserving the first revision's
  epoch/cycle witness. A version change keeps that observation only through this supported binding;
  it does not reinterpret a different capture/WorkOrder as the same observation.
- Revision is **submission-wide**, not an independent ortho/DSM counter. An unchanged sibling artifact
  receives a different catalog `assetRef` in another revision even when its byte hash is unchanged.
  Label the submission revision and actual file change honestly; do not freely mix sibling revisions.
- An old result always opens with its original selectors, artifact identities, conditions and evidence.
  A newer version may be offered as **“새 버전으로 새 비교”**, never silently substituted.

Example: observation O1 has ortho A and DSM D1; corrected DSM D2 later becomes available. Run R1 stays
bound to D1. Browsing may select D2 as the current viewable version after rechecking its conditions;
reopening R1 still shows D1. Selecting D2 for calculation creates/resolves a new input-bound run.
O1/A/D1/D2/R1 here are explanatory names, not proposed wire IDs.

### Existing identity mapping

| Concept | Reuse / boundary |
|---|---|
| Observation | Existing `observationEpochId` (external identity derives from organization/WorkOrder/cycle) and exact-selector continuation relations; not a date bucket |
| Asset version | Exact external submission selector (`workOrderId`, server-issued `submissionRef`, `revision`), artifact identity and sealed byte digest; catalog `assetRef` identifies the selected asset projection |
| Validation | Existing inspection/evaluation/use/admission records with exact subject, revision/digest and policy bindings |
| Analysis run | `analysisId` is a durable selector intent; separately resolved calculation/execution identity may be reused/deduplicated. Do not assume one UI session or `analysisId` equals one new calculation. |
| Result | `resultId`/report ID, result revision and immutable `reportDigest`/numeric identity; exact per-epoch evaluation identities and evidence digests are distinct from current-use projection. `evidenceRevision` alone is not a complete snapshot identity. |

The owner must verify this mapping against current models before adding a projection. Do not add
`ObservationVersion`/`AssetVersion` tables or new IDs merely because the conceptual diagram uses them.

## 3. Entry and restoration contract

Resolution priority is **explicit result/work/context before ordinary entry**:

| Entry | Required behavior |
|---|---|
| Exact result link | Restore that result's actual inputs and WorkArea. Never rerun or select latest on open. |
| Explicitly reopened saved comparison/analysis work | Restore its exact baseline/current versions and saved spatial context; recheck permissions/current availability without rewriting intent. |
| Explicit observation/version link | Resolve exactly the named authorized objects. A malformed, unavailable or foreign reference produces recovery choices, not a silent latest fallback. |
| Ordinary Site entry, no explicit work/input intent | Start in Explore with the latest **view-available** observation in the authorized Site/scope. Do not automatically resume an old comparison or choose the latest quantitatively eligible input instead. |

“Latest view-available” means a read/representation decision, not quantitative suitability:
- Order by declared/known capture information at its real precision, not `submittedAt`.
- Date-only remains date-only; unknown capture time is not synthesized from registration/export time.
- Unknown-date observations remain discoverable in a separate labelled group.
- If capture information cannot identify one latest candidate, show the ambiguity and candidates;
  do not invent an ordering or merge observations.
- Within an observation, prefer an available ortho for visual orientation, otherwise an available DSM.
  Both use the same spatial navigation. No fake orthophoto is generated from DSM.
- The displayed footprint may cover only part of a Site. Say which observation/area is shown;
  do not imply complete or current real-world Site coverage.
- A newer version awaiting inspection/representation must not be mistaken for absent data. If an
  earlier version is offered for viewing, label its exact version and the newer version's state.
- Do not jump to newer data while the person is exploring. Offer an explicit update indication.

The current catalog sorts by `assetRef`; its `SUPERSEDED` flag can mean a higher registered but
unsealed revision exists. Neither ordering nor that flag is an authoritative latest-viewable decision.

The authoritative latest/version-availability projection is an implementation prerequisite, not an
existing API asserted by this document. Pagination, equal-date candidates, supersession and unreadable
new versions need explicit tests; a front-end sort of an incomplete page is not an adequate authority.

### State separation

| State | Examples / lifetime |
|---|---|
| Browse context | Site, area, observation, selected asset/version, layer, display CRS, viewport, mode; navigable/shareable typed references where safe |
| Comparison draft | Exact baseline/current selectors and selected WorkArea, plus display context; saving/resuming requires an explicit supported persistence mechanism |
| Submitted intent/run | Existing immutable/fenced request inputs and idempotency semantics; changing browse controls does not mutate it |
| Result view | Result/report identity, original inputs/conditions/evidence; current availability shown separately |

URLs must not contain tokens, signed object URLs, arbitrary object keys or raster bytes. Reload/Back
restores intent, then resolves current permissions. Revocation/expiry shows a truthful unavailable state;
it does not delete history or automatically replace an input. A browser URL/local draft alone is not
evidence of durable cross-device saved-work storage; that capability must be specified if introduced.
Current general-overview helpers can fall back from unknown area/asset hints; do not reuse that behavior
unchanged for an explicit saved-work/result link. Its resolution must preserve intent or fail closed.

## 4. One workspace, adaptive task modes

These are working modes inside the Site workspace, not three disconnected tools or another global
navigation layer. Existing material registration/history/management routes remain reachable and keep
their semantics. Exact route/component boundaries are implementation discretion if the context holds.

| Mode | Dominant structure | Information/action |
|---|---|---|
| Explore | One large spatial canvas; optional details panel | Actual observation, date precision, layer, extent; select area or inspect source/version |
| Compare | Two equal-weight maps; details panel collapsed by default | Baseline/current observation and version on each map; shared navigation and consistent legend; selected fixed WorkArea |
| Results | Map and result/evidence content sized to the task, not a permanently fixed sidebar | Existing calculation values, coverage/limitations, immutable inputs and review; external result reference |

Compare structure:

```text
Site / selected WorkArea                 Explore · Compare · Results
Baseline observation + version          Current observation + version
┌─────────────────────────────┬─────────────────────────────┐
│          baseline map       │          current map        │
│                             │                            │
└─────────────────────────────┴─────────────────────────────┘
Shared range / scale / legend             Conditions → request analysis
```

This is a structural specification, not a rendered wireframe or implemented screen.

### Common interaction rules

- Pan/zoom either comparison map to the same verified display-coordinate extent and scale in both.
  Same grid/CRS is not a declaration of field co-registration or accuracy. Never silently shift/rotate
  or vertically correct an input to make the images appear aligned.
- Pairwise spatial-display registration is a required contract condition, not a browser inference.
  Existing `VISUAL_COMPARISON` decisions check inspection/display facts but do not establish this pair
  registration; an existing sanitized-display receipt alone has no display-georeferencing transform.
  Specify the bound geometry, transform/evidence, renderer, units and scale semantics before enabling
  synchronization. This remains distinct from quantitative/field-accuracy eligibility.
- If the supported spatial mapping/common display plane cannot be established, retain individual
  viewing and explain why synchronized spatial comparison is unavailable. No guessed WGS84 placement.
- For comparable DSM display, share the supported unit, color scale and NoData semantics. Independent
  auto-stretches must not masquerade as an elevation change. Unknown vertical basis/unit receives
  explicit relative-display wording rather than an absolute-metres legend.
- The viewport is **not** the calculation polygon. Select an existing fixed WorkArea explicitly;
  new geometry/definition requires the normal permissioned versioned workflow.
- Choosing another baseline/current or asset version changes the comparison draft, not the opened run.
- Render analytic coverage from its authoritative witness. A cut/fill heatmap needs a supported,
  result-bound spatial output; never silently promote browser raster arithmetic to a Core result.
- Retain original timestamps, versions and important limitations near the relevant content. Move
  detailed digests/processing diagnostics behind disclosure, not the evidence needed for a decision.

### Responsive/input behavior

- Desktop: Compare keeps map areas equal; source/details may open temporarily without turning one
  map into a thumbnail. Results can give more room to evidence when that is the active task.
- Phone: Explore uses one canvas and a bottom information sheet. Compare uses equal-height maps
  with persistent baseline/current labels and shared controls; information can open over them and
  close back to the same view. Do not hide which side/version the user is inspecting.
- Preserve current below-1024 mutation restrictions. Viewing an existing representation is not
  implemented by silently issuing an otherwise forbidden PREPARE/analysis POST.
- Provide keyboard-operable date/layer/area selection and map controls, clear focus when panels
  open/close, textual layer/legend labels and an accessible non-map path to selected facts.
- Keep Site identity once in compact workspace chrome. Do not recreate the current repeated title,
  selector card and explanation stack above the first useful observation.

## 5. Purpose-specific states, not one trust badge

Persistently show selected observation/version, layer and footprint. Show a concise relevant-use
message when it affects the current task, with details available on demand:

> 자료 열람 가능 · 체적 비교 제한 — 수직 기준을 확인할 수 없습니다. `제한 근거 확인`

| Condition | User outcome |
|---|---|
| Metadata/representation loading | Named loading state; no apparent blank Site or empty-data claim |
| No registered observation | Registration guidance if permitted; otherwise contact/request path |
| Data exists but representation pending/failed/unsupported | Keep metadata/history visible, identify the actual state and permitted recovery; not “no data” |
| No supported display CRS | Explain original-plane viewing vs map-placement limit; no invented coordinates |
| View available, quantitative input blocked | Keep exploration; show the applicable blocker beside calculation action |
| Date-only/unknown chronology | Browse honestly; chronological calculation conditions still fail closed |
| Revoked/expired access or representation retention | Recheck and stop unavailable byte access; preserve historical record where authorized |
| New asset version/validation exists | Offer explicit newer-version/new-comparison path; preserve old result |
| Running/failed analysis | Durable request identity and status/recovery, not zero numerical result |
| Completed provisional result | Values and limitations together; review is not accuracy/settlement approval |
| Network failure vs authentication failure | Existing truthful recovery distinction; not every failure is session expiry |

## 6. Result lookup is not calculation reproduction

**Workspace MVP acceptance A — consistent re-query:** Web and an authenticated external API consumer
resolve the same immutable result/report, exact input versions, frozen calculation conditions and
bound validation/evidence. Display the current-use assessment separately: it may legitimately change
with policy/evidence/rights. Do not demand equality of an entire dynamic JSON response or mutate the
old immutable result to make its current status look identical.

**Current API gap:** ordinary Analysis retrieval consults currentness and may withhold numbers.
Historical calculations are retained internally, but that is not an unconditional historical Web/API
resolution contract. Specify authorized historical result/evidence access separately from current-use
assessment before claiming acceptance A. Do not bypass the public guards with admin credentials or an
internal-store reader. An inaccessible history remains an explicit blocked/unavailable view, not a
substituted latest result. Exact result/report identities and per-epoch evaluation digests are required;
the current maximum evaluation revision exposed as `evidenceRevision` is not a global snapshot token.

**Separate verification B — reproduction:** prove calculation behavior against the declared tolerance
using exact inputs and WorkArea, transforms/resampling, masks/NoData, profile/algorithm/parameters,
worker build, runtime identity and lock bindings. Record its evidence separately. A successful GET,
available provenance fields or matching display screenshots do not establish reproduction.
Repeated executions can have different inspection/input-report identities and execution metadata;
consistent exact source/byte/spatial facts and the declared numerical tolerance are the proof target,
not a blanket claim that every provenance digest must match across different executions.

Separating these acceptance scopes does **not** remove existing Constitution/SDP-REQ-04/ADR037
reproducibility requirements, weaken current V1/V2 semantics or skip/replace owner contract/replay/
calculation regression tests. These provenance bindings must continue to be produced and preserved
even before a broader reproduction verification is complete. Do not add “재현 검증 완료” UI from A.

## 7. Current implementation evidence and prerequisites

At source baseline `f2b738bc`:
- `SiteSpatialOverview.tsx` primarily displays WorkArea/asset extent geometry, not full spatial raster
  browsing. The current native outline is not the proposed map experience.
- `spatial-data-preview.ts` and the receipt preview support guarded bounded actual output bytes,
  hash/size checks and raster validity; they are a useful foundation, not a multiresolution map server.
- Current requests/receipts are finite and requester-bound. A viewer's metadata READ or a shared
  workspace URL must not transfer another requester's prepared file or create a new byte permission.
- `operator-journey.ts` carries some area/current hints. It does not establish the complete saved
  two-version/viewport context contract proposed here.
- Existing analysis selectors, results and evidence are reusable. The display must bind to their exact
  records rather than calculate its own authoritative quantity.

Prerequisites to specify before implementation of the affected seam:
1. Observation/version/current-display-candidate projection and precise latest/ambiguity semantics.
2. Permissioned, bounded spatial display delivery: coordinate/affine/footprint binding, level-of-detail,
   explicit pair-display registration, validity, provenance, cache access rechecks, expiry/retention
   and resource bounds. Reuse/adapt owner paths where compatible; no invented public tile endpoint
   or unrestricted cache.
3. Typed browse/comparison/result restoration and, if needed, durable saved-work persistence.
4. Result-linked spatial layers/coverage, without claiming a difference raster endpoint already exists.
5. Permission-scoped historical result/evidence resolution distinct from current-use assessment;
   preserve existing retained calculations without exposing a raw internal-store interface.

External basemap traffic is not required for the MVP; imagery/native spatial exploration must not
automatically add third-party location disclosure. No new projection support or analysis CRS allowlist
is inferred from selecting a map library.

## 8. Integrated implementation units (proposed, not executed)

| Unit | Cohesive deliverable / owners | Acceptance and dependency |
|---|---|---|
| SWX-1 Identity and entry | Core-owned observation/version/availability projection + Dashboard typed selection/entry resolution; retain existing identities | Contract cases for shared observation, submission-wide corrections, exact frozen links, ordinary latest entry and ambiguity; specify/conformance-check any necessary wire changes before relying on them |
| SWX-2 First connected spatial view | Existing Core delivery/worker + shared Dashboard spatial shell, dates/layers/area selection | One actual authorized Site/asset through real bounded representation → interactive map → reload/re-login; no separate demo. Depends on SWX-1 and display-delivery contract |
| SWX-3 Equal-map comparison | Same shell, two exact inputs, synchronized spatial range/legend, comparison context | Real two-observation path; invalid spatial pairing and unknown chronology stay truthful; new version cannot mutate reopened work. Depends on SWX-1/2 |
| SWX-4 Result and evidence continuity | Existing analysis request/status/result/review + map coverage + authorized historical result/evidence resolution + authenticated external re-query | Same area/two versions into actual run, immutable Web/API result parity, current-use status separate; no browser quantity authority. Depends on exact identity and historical-access contract; integrate with SWX-3 |
| SWX-5 Workflow acceptance | Cross-owner implementation integration in the actual Console | Back/reload/new-login, corrected version, expiry/revocation, empty/failure, desktop/phone/input tests and actual rendered task access; preserves existing regression suites |

Do not split delivery into “viewer done” and “trust platform later”. SWX-2 is an early integrated
vertical slice, not product completion; SWX-3/4/5 close the intended task. Independent work may proceed
in parallel only with explicit shared-file/browser ownership and compatible contracts.

Owner routes to inspect before edits: `apps/dashboard/src/app/sites/[siteId]/`, existing geo/display
and journey libraries/tests; Core external ingress/delivery/quantity and epoch/identity owners;
processing-controller display/preparation workers; event-contracts and contract/replay tests. This
document does not authorize repository moves, another independently operated service or SDK invention.

## 9. Acceptance scenarios for the delivered workspace

These SWX cases refine UI acceptance, not replace product acceptance or existing tests:

1. **Ordinary entry:** a later registered but older capture does not displace the latest view-available
   observation; chronological ambiguity and date-only/unknown values are labelled honestly.
2. **Correction:** D1 result remains unchanged after D2 registration/validation; a new comparison
   explicitly selecting D2 has distinct bound inputs and the appropriate calculation identity.
3. **Explicit resume:** open a saved comparison or result after newer uploads; exact original inputs,
   area and context return. An unavailable input is explained, never replaced silently.
4. **Explore → Compare → Results → Back:** same selected area, two exact versions, supported spatial
   extent and layer context; viewport changes never alter the run polygon.
5. **Compare:** equal map emphasis at actual desktop/phone viewports, consistent scales/legend and
   valid/excluded regions; unsupported common display mapping is not faked.
6. **No data vs cannot display:** registration guidance only for real absence; pending/failure/denied
   data retains the correct recovery path and permitted metadata.
7. **Rights lifecycle:** actor/org/Site/WorkArea limits, byte access/cache, revocation/expiry and
   requester ownership enforced. Mobile reading creates no hidden mutation.
8. **Same result externally:** authorized external consumer and Web resolve the exact immutable
   result/inputs/conditions/evidence. Dynamic current-use differences are explained. This passes A,
   not automatically reproduction verification B.
9. **Understandable entry:** a first viewer can identify Site, selected capture, available layer,
   visible area and the next useful action without reading processing jargon. The first viewport
   contains useful authorized spatial content or an explicit state/recovery—not a misleading blank box.

Use existing actual Floreat date-only/unknown-vertical observations for viewing/blocked-calculation
cases, and a clearly separate supported synthetic case for numeric workflows. Never attach synthetic
quantities to real coastal imagery or call either customer/field acceptance. A correction fixture and
additional reproducibility checks need separately identified evidence, not rewritten existing records.

## 10. Unchanged operational boundary

The [shared inspection-history incident](../audit/PRODUCT_USE_INSPECTOR_JOURNAL_INCIDENT_2026-10-21.md)
remains unresolved. No journal repair, branch rewriting, direct cleanup, new inspection launch,
shared-host maintenance, new rights, production/customer activation or retention-policy approval is
created here. Current local proof/output validity cannot be assumed permanent from past receipts.

This document completes the requested pre-implementation UX clarification and work decomposition.
It does not complete the spatial-workspace implementation, the platform goal or operational acceptance.

## Appendix — source mapping checked at the baseline

These are implementation observations, not new product authority:

- [Epoch identity](../../services/core/src/ksi_core/domains/observations/epoch_identity.py): deterministic
  organization/WorkOrder/cycle identity, not a timestamp group or mutable Epoch journal.
- [External ingress](../../services/core/src/ksi_core/domains/external/ingress/external_reconstruction.py):
  first revision's epoch/cycle witness retained across contiguous revisions.
- [Asset catalog](../../services/core/src/ksi_core/domains/external/ingress/spatial_asset_catalog.py):
  `assetRef` binds submission/ref/revision/artifact; current ordering/lifecycle is not latest-view policy.
- [Use evaluator](../../services/core/src/ksi_core/domains/external/quantity/external_use_evaluator.py)
  and [display receipt](../../packages/event-contracts/src/ksi_event_contracts/external_display_artifact.py):
  visual-use receipt validation does not itself establish pair display-registration geometry.
- [Analysis facade](../../services/core/src/ksi_core/domains/external/quantity/external_analysis_api.py)
  and [calculation store](../../services/core/src/ksi_core/domains/external/quantity/external_relative_volume_calculations.py):
  public intent/result/evidence/currentness identities are distinct; current result exposure and
  authorized retained-history access must not be conflated.
- [Overview scope helpers](../../apps/dashboard/src/app/sites/[siteId]/site-spatial.ts): ordinary
  fallback selection is not an adequate resolver for explicit frozen-work deep links.

Prior actual image/source observations are retained in the task ledger. User-provided competitor/example
images are reference concepts, not KSI data or transferable runtime assets. This contract introduces no
new visual demo and makes no fresh rendered/runtime verification claim.
