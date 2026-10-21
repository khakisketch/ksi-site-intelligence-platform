# Registration ownership/acceptance (`PairRegistrationV1`) and GAP-05 display/AI-egress purpose split — design decision

Date: 2026-10-21. Base: main `88fbf266`.
Status: **DESIGN ONLY, Human-directed.** No source/contract/runtime/policy/worker change,
no commits, no servers, no new Core jobs, no ledger/`.opencode` edits, no dashboard work.
Nothing here authorizes implementation; owner approval and separate contracts/tests are
required before any code.

## Authority and precedence

Constitution → Decision Ledger → PRD §1.1.2 (SDP-REQ-05/06) → `contracts/` →
ADR-KSI-036/037/038/039 → display/LOD proposal
(`docs/design/SPATIAL_DATA_DISPLAY_LOD_CONTRACT_PROPOSAL_2026-10-21.md`, cited below as
"display proposal") → this document (subordinate). It changes none of them.
Normative invariants: `docs/product/DOMAIN_INVARIANTS.md`
(INV-020/024/040/050/051/053/054/055/060/061 in scope).
GAP references are to the roadmap gap list
(`docs/superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md`, GAP-01..10);
GAP-03 (registration/resampling semantics), GAP-05 (display/cache/AI-egress threat model),
GAP-06 (load/budget evidence) are in scope.

Human's binding direction (implemented exactly, translated):

1. Registration ownership: the server-side spatial-information processing layer owns
   registration; the UI only CONSUMES the registration result. But OWNING the
   registration method and PERFORMING registration are different things. Start by
   ACCEPTING and VERIFYING externally attested registration evidence; additional
   methods (GCP, feature-point, surface matching) may be added later as separate decisions.
2. The registration record must provide at least: exact versions of baseline and
   compared material; transform and CRS used; registration method and its evidence;
   error / valid-area / suitability assessment; producer and method version.
3. `REGISTERED` must NOT be allowed merely because a transform matrix exists: it
   requires the evidence and validation conditions needed FOR THE INTENDED COMPARISON
   PURPOSE. A registration record is bound to a purpose/comparison kind; the same
   registration may suffice for one purpose and not for another.
4. Automated registration is a SEPARATE later step, not part of this decision.
5. GAP-05 (decided now): display use and AI egress are clearly separated. Holding
   map-display rights must NOT let a user export the original GeoTIFF, an AI-training
   corpus, or unbounded downloads. Display-tile reads, original download, analysis
   execution, external AI processing, and dataset export are DIFFERENT acts. Repeated
   tile reads can reconstruct substantial source information, so unlimited tile download
   under display rights requires its own risk assessment — while a user exploring
   normally must not be blocked by unnecessary approval steps.

## 0. Established facts (verified in code, not re-derived)

1. `PairRegistrationV1` / `PairRegistrationNoneV1` / `DisplayDerivativeV1` already exist
   in the tree: `packages/event-contracts/src/ksi_event_contracts/spatial_data_display.py:114–218`.
   Fail-closed validators are implemented: REGISTERED requires non-empty
   `evidence_digests` (`:144–154`); UNREGISTERED must carry none; a derivative's
   registration must include its own source (`:210–217`); `pair_is_registered()` in
   `services/core/src/ksi_core/domains/external/delivery/display_derivative.py:180–191`
   returns true ONLY for an evidence-backed REGISTERED record and never consults CRS.
2. The current purpose model is exactly two values —
   `SpatialDataPurposeV1.GENERAL_DATA_USE / EXTERNAL_AI`
   (`packages/event-contracts/src/ksi_event_contracts/spatial_data.py:135–137`,
   re-exported through `spatial_data_authority.py:99–101` as the `purposes` field of
   `SpatialDataGrantV1`). Permission reuses them today:
   `DisplayPermissionV1.purpose: SpatialDataPurposeV1` (`spatial_data_display.py:172–179`),
   projected as `purpose=job.request.purpose`
   (`display_derivative.py:106–111`) and re-verified on binding (`:164–165`).
3. Purpose is already enforced at the Core delivery boundary:
   `grants.py:258–259` (only the two known purposes pass `_check_context`),
   `grants.py:316–317` (`purpose not in grant.purposes or operation not in
   grant.operations` → `PERMISSION_DENIED`), `grants.py:277–278`
   (EXTERNAL_AI additionally requires `site.ai_egress_allowed is True`, else
   `AI_EGRESS_DENIED`), `grants.py:500` (AI metadata selector requires
   `EXTERNAL_AI+READ`), `jobs.py:384,732,934–942` (AI job views/snapshots refuse
   non-EXTERNAL_AI purposes). The AI-egress send-time gate re-proves current rights
   (`ai_egress.py:130–180` and `_prepare` recheck/audit `:335–375`).
4. The display/LOD proposal records the normative rules this document builds on:
   §2 (two identities), §5 (registration gate + independent-viewing-only fallback +
   mandatory wording), §6 (per-principal per-purpose cache, rights re-check on every
   use, shared cache refused under the current grant model), §8 (open decisions incl.
   item 3 registration methods, item 8 purpose split). The display proposal's §8
   line 394 explicitly left the purpose question open pending GAP-05 review —
   **this document is that review's display-path decision; it does not implement it.**
5. ADR-KSI-037 D3 (common-grid-is-not-registration; profile "performs no automatic
   horizontal shift … A common grid is not evidence that the two observations are
   spatially registered"), D5 (typed `unavailable = selected − common-valid`,
   no silent correction), D7 (evidence/provenance binding) and the first-request
   contract (§"Required request scope", "Accuracy evidence") already fix: the caller
   never supplies registration knobs; the V2 target grid is the baseline observed
   grid; checkpoint evidence is bound to exact bytes. This document adds no new
   quantitative gate and weakens none.

---

# PART A — REGISTRATION: ownership, acceptance, purpose binding

## A1. Ownership statement (normative)

**Owner (produces and verifies registration records): the server-side
spatial-information processing layer — Core.**

Concretely, in current repo routing:

| Role | Owner module | Responsibility |
|---|---|---|
| Schema owner | `packages/event-contracts/` (`spatial_data_display.py`) | Record shapes, enums, fail-closed validators. Owns NOTHING about acceptance. |
| Verifier / adjudicator | `services/core/` — external delivery + ingress/inspection owners (`domains/external/delivery/`, quantity/ingress owners for evidence semantics) | ACCEPTS or REFUSES externally attested evidence; binds the record to exact subject versions; enforces purpose binding; emits typed failure reasons. The ONLY authority that may mark a pair REGISTERED-for-a-purpose. |
| Transform math | `packages/geo-spatial/` | Transform application/consistency mathematics (import-only library). Computes nothing authoritative on its own; Core invokes it during verification. |
| Consumer | `apps/dashboard/` (display path), `services/analysis-mcp/` + `services/spatial-data-mcp/` (bounded adapters over Core) | CONSUME the Core-verified record (or explicit NONE) and render the per-purpose verdict. Never compute, adjust, infer, or assert registration. |
| Non-owner | UI / MCP / worker | A worker may PREPARE bytes; it may not assert registration. An MCP adapter may DISPLAY a verdict; it may not upgrade one. |

**Boundary (normative): the UI never computes or asserts registration.**

1. The UI reads exactly one of: a Core-sealed purpose-bound REGISTERED record, or
   an explicit NONE/UNREGISTERED record. There is no third state and no missing field.
2. The UI performs no coordinate fitting, no shift estimation, no error-metric
   computation, no CRS guessing, no "close enough" upgrade. Equal CRS, equal grid,
   or visual alignment on screen is never registration evidence
   (display proposal §5; `pair_is_registered` never consults CRS).
3. Owning the registration METHOD is a Core product decision; PERFORMING a
   registration computation is an execution act. Today Core performs NO registration
   computation — it only accepts-and-verifies external attestation (§A2). When a
   future method is approved (§A4), the performing actor (Core worker or attested
   external tool) is named in that method's own decision; the UI remains a consumer
   in all cases.

## A2. Acceptance path for EXTERNALLY ATTESTED registration evidence

This is the ONLY registration intake this decision authorizes: a surveyor (or the
surveyor's registration tool) asserts a registration OUTSIDE KSI; Core VERIFIES the
assertion against the two sealed subjects and either admits it (purpose-bound) or
refuses it with typed reasons. Core performs no fitting.

### A2.1 The evidence record shape (proposed extension — see §A5 for exact deltas)

The external asserter provides, and Core seals, a record containing AT LEAST the
Human-required fields. Field names below are proposals; owner approval required:

```text
PairRegistrationV1 (extended; all fields required unless marked optional):
  subjects:                       # exact versions of baseline AND compared material
    baseline: { assetRef, revision, observedSha256, observedCrsDigest,
                inspectionReportDigest }
    current:  { assetRef, revision, observedSha256, observedCrsDigest,
                inspectionReportDigest }
  transform:                      # the transform and CRS used
    transformModelId              # e.g. AFFINE_2D / SIMILARITY_2D / TRANSLATION_2D (closed enum)
    transformModelVersion
    parameters                    # in stated units, fixed parameter order per model id
    parameterUnits                # closed enum: METRE and/or PIXEL, per model id
    sourceFrame                   # which subject grid the parameters are expressed in
    targetCrsDigest               # CRS the registered comparison is valid in
    targetVerticalBasisId | null  # where known; null means "no vertical claim"
  method:                         # the registration method and its evidence
    methodId                      # closed registry: EXTERNAL_ATTESTATION only, today
    methodVersion
    producerKind                  # SURVEYOR_ATTESTED | TOOL_ATTESTED (closed; see open decisions)
    producerId                    # named producer (person/org + tool id/version where applicable)
    producedAt
    evidenceDigests[]             # non-empty iff REGISTERED; digests of the attestation pack
    evidenceManifestDigest        # digest of the manifest listing evidence files + their roles
  quality:                        # error / valid-area / suitability assessment
    errorMetrics[]                # each: { metricId (closed enum), value, unit, definitionVersion,
                                  #          sampleCount, sampleGeometryRef }
    validAreaRuleVersion          # versioned rule id; the rule itself lives in the owner registry
    validAreaGeometryDigest       # digest of the valid-area geometry the metrics apply to
    suitabilityClaim              # NONE by default; per-purpose verdicts live in §A3, not here
  binding:                        # purpose/comparison-kind binding (§A3)
    comparisonKind                # closed enum, e.g. VISUAL_SIDE_BY_SIDE / OVERLAY_ALIGNED /
                                  # DIFFERENCE_COLOURING / QUANTITATIVE_VOLUME (initial set)
    status                        # REGISTERED | UNREGISTERED (existing enum, unchanged)
```

What the asserter states IN the evidence pack (referenced by `evidenceDigests`, not
inlined): the tool name/version, the control used (GCP list with CRS and residuals,
tie-point set, or surface-match report — WHICHEVER the method used; the method's own
decision fixes the required contents), the error metric DEFINITIONS (e.g. RMSE of
independent check points vs fit residuals — definition version pinned per metric),
the valid-area polygon, and the producer signature/identity binding. Core verifies
the pack's digests and consistency; Core does not re-survey the ground.

Units/frames rule: transform parameters are interpreted ONLY in the stated
`parameterUnits` and `sourceFrame`. A parameter tuple without units/frame is refused
(`REFUSE_MISSING_FRAME`). Pixel-unit parameters additionally pin the exact subject
grid (revision + transform digest) they were measured in; metre-unit parameters pin
the CRS digest.

### A2.2 How Core VERIFIES (normative check list)

On intake, Core runs ALL of the following against the two CURRENT sealed subjects
(resolved through genuine sealed-inspection authority, as `grants.py:175–181,260–265`
requires for sources — a synthetic/model-valid source alone is not admission evidence).
Checks are conjunctive; the first failure refuses the record. Order is fixed for
deterministic failure reasons:

1. **Subject binding:** both `subjects.*` pins (assetRef, revision, byte digest, CRS
   digest, inspection digest) match the sealed subjects byte-for-byte. Mismatch →
   `REFUSE_SUBJECT_DRIFT` (re-attestation against the new revision required; the old
   record is NOT mutated).
2. **Distinctness:** baseline ≠ current (already enforced today,
   `spatial_data_display.py:146–147`). Same asset → `REFUSE_SAME_SUBJECT`.
3. **CRS/frame consistency:** `targetCrsDigest` is compatible with both subjects'
   observed CRS facts per INV-020/ADR-KSI-037 D3; `sourceFrame` names one of the two
   subject grids; pixel-unit parameters reference the named grid's exact revision.
   Otherwise → `REFUSE_CRS_FRAME_MISMATCH`. (Equal CRS alone still proves nothing —
   this check is necessary but never sufficient.)
4. **Transform well-formedness:** `transformModelId` is a known closed-enum value;
   parameter count/order/units match the model id and version; finite values only;
   affine determinants non-degenerate. Otherwise → `REFUSE_MALFORMED_TRANSFORM`.
   A bare matrix with no method/evidence/purpose binding is refused HERE even if the
   numbers are well-formed → `REFUSE_UNATTESTED_TRANSFORM`. **A transform matrix
   alone is never REGISTERED.**
5. **Error-metric sanity:** every metric has a known `metricId` + pinned
   `definitionVersion`; units match the metric; `sampleCount ≥ method minimum`
   (method minimums are set per-method, §A4; for EXTERNAL_ATTESTATION the minimum is
   an owner decision, §A5-open); check-point metrics must be INDEPENDENT of fit
   points where the method claims independence (asserter declares the split; Core
   verifies the declaration is present and the digests differ). Otherwise →
   `REFUSE_ERROR_METRICS_INSUFFICIENT`.
6. **Valid-area rule:** `validAreaRuleVersion` names a versioned rule in the owner
   registry; `validAreaGeometryDigest` resolves to a geometry; the geometry lies
   within the intersection of the two subjects' footprints. Otherwise →
   `REFUSE_VALID_AREA_UNKNOWN` / `REFUSE_VALID_AREA_OUTSIDE_SUBJECTS`.
7. **Evidence digest binding:** every digest in `evidenceDigests` + the
   `evidenceManifestDigest` resolves to Core-held (or Core-retrievable, policy-bound)
   bytes; recomputed digests match. Unresolvable or mismatched →
   `REFUSE_EVIDENCE_UNRESOLVED`. Empty evidence with status REGISTERED is refused at
   construction (existing validator, `spatial_data_display.py:148–150`).
8. **Producer/method authority:** `methodId == EXTERNAL_ATTESTATION` (the ONLY value
   admitted today); `producerKind` is a currently authorized kind; `methodVersion`
   is a known version. Unknown method/version/producer-kind →
   `REFUSE_METHOD_NOT_ADMITTED`. (Who counts as an authorized producer is an owner
   decision, §A5-open — Core enforces the ALLOW-LIST, it does not invent it.)
9. **Purpose binding present:** `comparisonKind` is a known closed-enum value
   (§A3). Missing or unknown → `REFUSE_PURPOSE_UNBOUND`. A record that passes
   checks 1–8 but names no purpose is still refused: **there is no purpose-free
   REGISTERED.**

### A2.3 What Core must REFUSE (non-exhaustive, normative)

- A transform matrix with no evidence (`REFUSE_UNATTESTED_TRANSFORM`).
- Evidence whose digests do not resolve or recompute (`REFUSE_EVIDENCE_UNRESOLVED`).
- Error metrics without pinned definitions, or fit residuals presented as
  independent-check accuracy (`REFUSE_ERROR_METRICS_INSUFFICIENT`).
- A valid-area claim outside either subject footprint
  (`REFUSE_VALID_AREA_OUTSIDE_SUBJECTS`).
- Attestation against a different revision/bytes than the sealed subjects
  (`REFUSE_SUBJECT_DRIFT`) — including "same file re-exported with a new tag".
- Any method other than EXTERNAL_ATTESTATION (`REFUSE_METHOD_NOT_ADMITTED`):
  GCP / feature-point / surface-matching / automated methods each need their own
  decision (§A4) before Core admits them.
- Any record without a `comparisonKind` (`REFUSE_PURPOSE_UNBOUND`).
- Any request to EDIT an admitted record in place: records are immutable; a new
  attestation supersedes (new digest), never mutates.

All refusals are typed reasons, never silent fallbacks, never numbers, never
optimistic defaults (INV-040; ADR-KSI-037 D5).

## A3. PURPOSE-BOUND registration (normative)

### A3.1 The rule

A registration record is admitted **for a stated comparison kind**. The same
geometric fact may satisfy a weak purpose and fail a strong one:

```text
initial comparisonKind set (closed; owner approves; extensions are new decisions):
  VISUAL_SIDE_BY_SIDE   # independent viewing with shared navigation aids only
  OVERLAY_ALIGNED       # synchronized pan/zoom, shared crosshair, flicker/wipe
  DIFFERENCE_COLOURING  # per-pixel difference rendering on screen
  QUANTITATIVE_VOLUME   # numeric cut/fill publication (analysis path, not display)
```

Strength ordering (normative): `VISUAL_SIDE_BY_SIDE < OVERLAY_ALIGNED <
DIFFERENCE_COLOURING < QUANTITATIVE_VOLUME`. Admission for kind K does NOT imply
admission for any stronger kind. Admission for a stronger kind implies the weaker
display kinds ONLY where the verdict table says so (§A3.2) — never automatically
for QUANTITATIVE_VOLUME, which the analysis admission path re-decides under its own
profile/policy gates (first-request contract; ADR-KSI-037 D3).

Tolerance policy per kind (numeric thresholds: OPEN, §A5 — e.g. "OVERLAY_ALIGNED
requires RMSE ≤ X m over the valid area with N independent checks" is an owner
decision with real data; this document fixes the STRUCTURE, not the numbers):

```text
per-kind admission = method admitted for kind AND error metrics satisfy kind policy
                     AND valid area covers the comparison extent AND evidence resolves
```

### A3.2 Status/verdict vocabulary per purpose (no composite flag)

The three states stay separate (display proposal §0.7; audit proposal §4). For each
requested comparison kind, Core emits EXACTLY one typed verdict; the UI renders the
verdict's mandatory wording. No `ready/verified/status` roll-up exists.

| Requested kind | Verdict | Meaning | UI consequence |
|---|---|---|---|
| any | `REGISTERED_FOR_KIND` | Admitted record for this kind exists and is current | The kind's affordances enabled |
| any | `NONE_INDEPENDENT_ONLY` | No record, or record is NONE/UNREGISTERED | Independent viewing only (§A3.3) |
| any | `WRONG_KIND_INSUFFICIENT` | A REGISTERED record exists but for a weaker kind (or kind policy unmet) | Independent viewing only + truthful "stronger comparison needs stronger evidence" state; the weaker kind's affordances stay as admitted |
| any | `RECORD_STALE_SUBJECT_DRIFT` | Record exists but a subject revision/bytes changed | Independent viewing only until re-attestation |
| any | `RECORD_REVOKED_OR_EXPIRED` | Rights/evidence binding lapsed | Independent viewing only; history preserved where authorized |

`QUANTITATIVE_VOLUME` additionally NEVER reads a display verdict as input: the
analysis admission path performs its own checks (profile/CRS/vertical/evidence
gates). A display `REGISTERED_FOR_KIND` for `DIFFERENCE_COLOURING` is not
quantitative eligibility.

### A3.3 Missing or wrong-purpose registration → independent viewing only

Unchanged from display proposal §5, restated normatively here because purpose
binding sharpens it: when the verdict for the REQUESTED kind is anything other than
`REGISTERED_FOR_KIND`, ONLY independent viewing of the two epochs is allowed
(side-by-side maps with SEPARATE navigation state, labelled "독립 보기 — 정합 근거
없음"). Synchronized pan/zoom, shared crosshairs, difference colouring, or any
"same-pixel" language is FORBIDDEN. Mandatory wording (display proposal §5) is
reused, with the kind-specific suffix: "…이 비교 방식에 대한 정합 근거가 없습니다.
각각 독립 보기로 탐색하세요."

## A4. AUTO-REGISTRATION as a separate future decision (not now)

Automated registration (any KSI-performed fitting: feature-point, surface matching,
ICP, mutual-information, or learned methods) is EXPLICITLY OUT of this decision. No
method is proposed, no method is admitted, no worker performs fitting, no UI triggers
it. `methodId` admits exactly one value today (`EXTERNAL_ATTESTATION`).

Before auto-registration may be introduced, ALL of the following must hold (gates,
not a plan):

1. A dedicated method decision names the algorithm, its version pin, its input
   requirements, its error-metric definitions, its valid-area rule, and its
   per-kind tolerance policy — approved by the spatial + quantity owners.
2. The performing actor is named (which worker, which profile digest, which
   execution locus) and its outputs are evidence packs satisfying §A2.1 (the
   machine is an asserter like any other; its outputs pass §A2.2 checks 1–9).
3. Replay/contract coverage exists proving a bare-matrix output can never construct
   a REGISTERED record (the §A2.2 check-4/9 validators plus kind policy).
4. INV-053 review: the method's accuracy claims are bounded, provisional-only
   language is fixed, and no settlement/acceptance semantics attach.
5. GAP-03 (resampling/registration semantics) and the applicable GAP-06 load
   evidence for the worker lane are closed for the method's cost class.

Until then, any proposal to "just run an alignment" is refused by this document.

## A5. Contract additions proposed (names, fields, enums, validators; owners)

### A5.1 What is a CONTRACT change vs a CORE change

| Change | Layer | Owner |
|---|---|---|
| Extended `PairRegistrationV1` shape + `ComparisonKindV1` enum + per-kind verdict enum + new validators | contract | `packages/event-contracts` |
| Verification checks §A2.2, verdict emission §A3.2, refusal reasons, allow-lists (methods, producers, metric ids, valid-area rules, kind policies) | Core | `services/core` (external delivery + ingress/inspection owners) |
| Transform-model math used inside checks | library | `packages/geo-spatial` (import-only; no authority) |
| Rendering of verdicts + independent-only fallback | consumer | `apps/dashboard` (reads Core verdicts; asserts nothing) |

### A5.2 Migration / backward compatibility (EXTEND, never replace)

`PairRegistrationV1` / `PairRegistrationNoneV1` exist in the tree
(`spatial_data_display.py:126–167`) with live validators and a Core consumer
(`display_derivative.py:180–191`). The proposal EXTENDS them:

1. **Additive fields only.** New required-by-design fields (`subjects` pins,
   `transformModelId/version`, `parameterUnits`, `sourceFrame`, `targetCrsDigest`,
   `methodVersion`, `producerKind/Id`, `evidenceManifestDigest`, `errorMetrics[]`
   with definitions, `validAreaGeometryDigest`, `comparisonKind`) are added as a
   versioned extension: existing records WITHOUT the new fields continue to
   validate (pydantic defaults / optional-on-read), but Core treats a record
   lacking `comparisonKind` as `REFUSE_PURPOSE_UNBOUND` for any REGISTERED claim —
   i.e. old REGISTERED-shaped records keep parsing, but CANNOT newly authorize a
   kind-bound comparison until re-attested with purpose binding. No silent upgrade.
2. **No field is removed or re-typed.** `baseline_asset_ref`,
   `current_asset_ref`, `method_id`, `transform_parameters`,
   `valid_area_rule_version`, `registration_error_metres`, `status`,
   `evidence_digests` keep their names/types/validators. New structure is added
   AROUND them (`transform_parameters` becomes the parameter tuple OF the named
   `transformModelId`; `registration_error_metres` becomes one entry of
   `errorMetrics[]` with an explicit definition version rather than a bare float).
3. **`PairRegistrationNoneV1` is unchanged.** NONE stays the explicit marker.
4. **`DisplayDerivativeV1.registration` union is unchanged in shape**
   (`PairRegistrationV1 | PairRegistrationNoneV1`); the per-kind verdict is a NEW
   Core-projected record (`PairRegistrationVerdictV1 { registrationDigest,
   comparisonKind, verdict, decidedAt, policyVersions }`), not a mutation of the
   derivative. Existing derivatives stay valid; only new kind-bound comparisons
   require verdicts.
5. **Validators extend, never relax:** the existing fail-closed validators
   (REGISTERED⇒non-empty evidence; UNREGISTERED⇒no evidence; distinct subjects;
   registration-must-include-source) stay byte-for-byte. New validators ADD:
   purpose-present, model-id-known, units/frame-present, metric-definitions-pinned,
   evidence-manifest-resolves.

### A5.3 Open decisions needing owner approval

1. Authorized producer kinds and attestation sources: which surveyors/tools may
   attest, and how producer identity is bound (signature vs named declaration).
2. Admitted `transformModelId` set and per-model parameter order/units.
3. `comparisonKind` initial set and strength ordering confirmation.
4. Per-kind tolerance policy (numeric thresholds, minimum independent-check counts).
5. Valid-area rule registry: who owns rule versions, geometry storage, and digest binding.
6. Error-metric closed enum + definition versions (RMSE-of-checks vs residuals,
   CE/LE conventions, units).
7. Whether `QUANTITATIVE_VOLUME` verdicts may ever be pre-computed for display or
   must always be re-decided at analysis admission (recommended: always re-decided).
8. Retention/audit lifetime of superseded records and their evidence packs.

---

# PART B — GAP-05: purpose split for the display path

## B6. Current purpose model and the precise GAP

**As it exists:** two purposes, `GENERAL_DATA_USE` / `EXTERNAL_AI`
(`spatial_data.py:135–137`), carried on grants (`spatial_data_authority.py:99–101`)
and requests (`spatial_data.py:163`), enforced at `_check_context` (`grants.py:258`),
`_check_grant` (`grants.py:316–317`), the AI metadata selector (`grants.py:500`),
AI job snapshot paths (`jobs.py:384,732,942`), and the AI-egress gate with
`site.ai_egress_allowed` (`grants.py:277–278`; `select_metadata_current`
`grants.py:481–482`). Display permission reuses the same two values
(`DisplayPermissionV1.purpose`, `spatial_data_display.py:177`; projected from the
job's purpose, `display_derivative.py:109`, re-verified `:165`).

**The GAP (exact):** today NOTHING distinguishes —

- (a) display-tile reads (bounded native-window PREPARE + same-session guarded GET,
  `jobs.py` route; preview gate `site-windowed-pixel-viewer.ts:16–27`),
- (b) original download (full-hash private spool byte authorization,
  `downloads.py:1,72+`; `max_active_downloads_per_organization` policy),
- (c) analysis execution (measurement launch under a quantitative profile),
- (d) external AI processing (EXTERNAL_AI metadata/job responses, `ai_egress.py`),
- (e) dataset export (bulk/cross-asset extraction for training or redistribution) —

beyond the two coarse purposes. Consequences: a grant with `GENERAL_DATA_USE` that
authorizes viewing ALSO authorizes, in principle, unbounded repeated reads whose
aggregate reconstructs the source; and there is no purpose value that means
"display only, no original, no AI, no export". The display proposal §8-item-8 left
exactly this open. **This document decides the taxonomy (design); implementation
needs the open decisions in §B10.**

## B7. Proposed PURPOSE taxonomy for the display path

New purpose values are PROPOSED (names need owner approval). They SUBDIVIDE
`GENERAL_DATA_USE`; `EXTERNAL_AI` keeps its existing gate intact and is never a
side effect of any display purpose. Operations stay `PREPARE`/`READ` (no new
operation is proposed — the purpose, not the operation, carries the distinction;
whether a future `TILE_READ` operation is needed is an open decision, §B10).

| Purpose (proposed) | Permits | Must NOT permit | Operations granted | Outputs / artifacts it can produce | Audit it must leave | Expiry / limits |
|---|---|---|---|---|---|---|
| `DISPLAY_VIEW` (tile-read) | Bounded native-window PREPARE + same-session guarded tile GET at display LOD, for the grant's bounds, while the grant is current | Original-byte download; AI metadata/job responses; analysis launch; export; cross-asset bulk reads; any byte use after revocation/expiry | `PREPARE`, `READ` | `DisplayDerivativeV1` identities + transient tile bytes only; tile bytes are NOT originals and carry display LOD/style pins | Per-tile-read audit row: grant digest, derivative id, window, principal hash, timestamp (aggregatable for budget, §B8) | Grant validity; per-grant tile-read budget + rate limit (§B8); retention per existing `retention_seconds` (no second TTL invented) |
| `ORIGINAL_DOWNLOAD` | Full-resolution original-asset byte download through the private-spool guarded path | Display-LOD substitution (no downsample presented as original); AI training-corpus redistribution rights; post-expiry reads | `READ` (scoped to the download spool path; never PREPARE-for-display) | Original bytes with size+SHA gate; license/provenance digest bound | Per-download audit row (existing download audit + license-provenance digest) | Grant validity; `max_active_downloads_per_organization`; explicit per-grant download count where policy requires |
| `ANALYSIS_INPUT` | Use of admitted bytes as input to a named quantitative profile under Core admission | Any numeric publication without the profile's gates; reuse of one pair's authority for another pair | `PREPARE`, `READ` (scoped to the analysis job) | Frozen job + receipt + result record (Core-recorded, never UI-computed) | Job/receipt/result digests bound to grant + profile | Grant + policy + profile validity; resource limits per policy |
| `AI_EGRESS` (= existing `EXTERNAL_AI`, renamed for clarity; value mapping decided by owners) | AI metadata/job/asset responses through the guarded AI-egress path ONLY, with `site.ai_egress_allowed` + explicit consent | ANY AI use as a side effect of display/download/analysis rights; training-corpus bulk extraction without a distinct AI grant | `READ` | Metadata/job/asset views and pages (`ai_egress.py` responses); never raw tile/original bytes beyond what the AI path explicitly authorizes | `MetadataAuditOperationV1` rows + payload digests (existing `_prepare` audit) | Grant validity + `ai_egress_allowed` + explicit consent; revoked/expired ⇒ refuse |
| `DATASET_EXPORT` | Bounded, explicitly approved bulk extraction for a named external use (distinct grant per export) | Any export under display/download/analysis/AI rights; standing/open-ended bulk rights | `READ` (export-scoped) | Export manifest + bytes with license/provenance binding | Per-export audit with approver identity + license digest | One-shot or short-lived grant; explicit approver; count/size caps (numbers OPEN, §B10) |

Rules binding the taxonomy (normative):

1. **No implicit escalation:** holding `DISPLAY_VIEW` never implies
   `ORIGINAL_DOWNLOAD`, `ANALYSIS_INPUT`, `AI_EGRESS`, or `DATASET_EXPORT`.
   Each requires its own grant (or its own purpose entry on a multi-purpose grant
   issued through the same explicit approval as today — `grant.purposes` already
   supports tuples, `spatial_data_authority.py:99–101`; multi-purpose grants do not
   weaken the AI consent gate).
2. **AI-egress gate intact:** `AI_EGRESS` (= `EXTERNAL_AI`) still requires
   `site.ai_egress_allowed is True` (`grants.py:277–278,481–482`) and the existing
   explicit-consent + send-time recheck (`ai_egress.py`). Display rights NEVER satisfy
   it. This document proposes NO change to AI consent semantics.
3. **Existing gates unchanged:** no permission, consent, egress, quota, expiry, or
   output gate is weakened. The taxonomy only ADDS distinctions; every current
   `PERMISSION_DENIED / AI_EGRESS_DENIED / ACCESS_REVOKED / ACCESS_EXPIRED /
   GRANT_REQUIRED` behaviour is preserved.
4. **Three states separate:** purpose authorization is a rights fact; it never
   restates validation suitability or audit integrity. No composite flag.

## B8. THE REASSEMBLY RISK and the proposed control

**The risk (Human-named, adopted):** repeated `DISPLAY_VIEW` tile reads at chosen
windows/LODs can reconstruct substantial source information — effectively an
unbounded download through the display door. Unlimited tile download under display
rights is therefore NOT authorized by this document; it requires its own risk
assessment.

**Proposed control (structure decided; numbers OPEN):**

1. **Per-grant tile-read budget:** each grant carries (or references, via policy) a
   bounded display-read allowance expressed in aggregate source-pixel (or byte)
   terms, not in request counts — e.g. "this grant's `DISPLAY_VIEW` reads may cover
   at most F× the grant's `allowed_bounds` area at native resolution" where F is
   set by risk assessment. Exhaustion ⇒ typed `DISPLAY_BUDGET_EXHAUSTED` (fail
   closed; re-grant, not override).
2. **Distinct read budget for display purposes:** tile reads meter against the
   display budget ONLY; original downloads meter against download quotas; the two
   budgets never pool. A principal with both rights spends from each independently.
3. **Rate limit + anti-scraping/aggregation guard:** per-principal sliding-window
   rate limit on tile GETs (detect systematic full-coverage harvesting: sequential
   full-extent tiling at native LOD across short windows); on pattern match, typed
   `DISPLAY_RATE_LIMITED` (retryable, bounded back-off — same client contract as the
   existing retryable 429 lane behaviour, display proposal §4) with audit flag. The
   guard is a PATTERN control, not a per-tile approval (see §B9).
4. **Audit trail of tile reads:** every tile GET writes the §B7 audit row
   (grant digest, derivative id, window, principal hash, timestamp) into an
   append-only store the budget guard reads. Audit rows are the budget's source of
   truth; cache hits for the same derivative/window count per the owner-approved
   counting rule (recommended: cache HIT re-serves count at reduced weight — exact
   weight OPEN, §B10 — because a re-served tile discloses no NEW information but
   confirms possession).

**Remains a SEPARATE risk-assessment decision (explicitly NOT invented here):**

- The numeric budget F (coverage multiple), the sliding-window rate numbers, and
  the aggregation/harvesting threshold.
- The cache-hit counting weight.
- The CDN/browser-cache threat model: whether any display byte may rest in a
  shared or client-persistent cache, with what TTL/label, and under whose
  authority — the display proposal §6 per-principal rule stands until a new threat
  model + independent security review (GAP-05) replaces it.
- Whether systematic-harvesting detection needs anything beyond rate+budget
  (e.g. device/session attestation) — threat-model input, not assumed.

## B9. Ordinary-exploration protection (normative)

A normal exploration session — panning/zooming over a site at display resolution,
revisiting tiles within the retention window (cache hits), resolving the minimal
covering tile set per viewport (display proposal §4) — **MUST NOT trigger per-tile
approval prompts, consent dialogs, or manual re-authorization.** The design achieves
this while keeping the §B8 aggregate control:

1. Authorization is per-GRANT (checked once per session/request scope, as today),
   NOT per tile: tiles check the live grant + budget REMAINING, never a human.
2. The budget F is calibrated (by the risk assessment, §B8/§B10) around ORDINARY
   exploration behaviour: covering a site's display extent a small number of times
   at display LOD must consume a SMALL fraction of F. Only systematic harvesting
   (full-extent native-LOD sweeps, repeated full re-covers) approaches exhaustion.
3. Hitting a limit is a typed, truthful, recoverable state
   (`DISPLAY_BUDGET_EXHAUSTED` / `DISPLAY_RATE_LIMITED` with retry/back-off and
   re-grant path), never a silent block, never a synthetic low-res fill presented
   as data (INV-040), never an accusation rendered to the user.
4. Cache hits within the retention window SHOULD NOT issue new PREPAREs (display
   proposal §4 dedupe) and count at reduced weight (§B8.4), so pan-back exploration
   is cheap by construction.

If measurement shows ordinary sessions exhausting F, F is wrong — not the user.
The budget numbers are validated against real exploration traces before enforcement
is turned on (GAP-06 class evidence).

## B10. Contract surface, owners, open decisions; what could NOT be specified

**Contract surface proposed (names are proposals; no code changed):**

| Record / change | Fields (minimal) | Owner |
|---|---|---|
| `SpatialDataPurposeV1` extended values (`DISPLAY_VIEW`, `ORIGINAL_DOWNLOAD`, `ANALYSIS_INPUT`, `AI_EGRESS`, `DATASET_EXPORT`) — subdivision of `GENERAL_DATA_USE`; `EXTERNAL_AI` retained/mapped | enum members + mapping note | `packages/event-contracts` |
| Grant carries display-read budget reference (policy link, not a number in the grant) | `displayBudgetPolicyDigest` (proposed) on grant or policy | `packages/event-contracts` (schema) + Core delivery (enforcement) |
| `DisplayTileReadAuditV1` (append-only row: grant digest, derivative id, window, principal hash, timestamp) | audit schema | Core delivery (existing audit stores pattern) |
| `DISPLAY_BUDGET_EXHAUSTED` / `DISPLAY_RATE_LIMITED` typed reasons | error taxonomy | Core delivery |
| `PairRegistrationVerdictV1` (per-kind verdict, §A5.2.4) | projected record | Core (projection) + `packages/event-contracts` (schema) |
| `ComparisonKindV1` closed enum | enum | `packages/event-contracts` + spatial/quantity owners (membership) |

Core vs contract split is the same as §A5.1: shapes/validators in
`packages/event-contracts`; allow-lists, budgets, verdicts, refusals in
`services/core`; math in `packages/geo-spatial`; consumption in `apps/dashboard`
and the MCP adapters. No new endpoint, method, or response schema is presented as
existing; any future display-read wire shape stays SHAPE-ONLY until its own
contract (display proposal §8 rule reused).

**Open decisions (owner approval required):**

1. Purpose names/values and the `EXTERNAL_AI`→`AI_EGRESS` mapping (rename vs alias).
2. Whether a new `TILE_READ` operation is needed or `READ`+purpose suffices.
3. Numeric display budget F, rate numbers, harvesting threshold, cache-hit weight —
   set ONLY after the GAP-05 risk assessment with real exploration traces.
4. CDN/browser-cache threat model + TTL/labels + store placement (per-principal
   rule stands until replaced by reviewed model).
5. Acceptable attestation sources / who may attest / producer-identity binding.
6. Per-kind tolerance policy numbers for registration (§A5.3).
7. Multi-purpose grant issuance policy: when one grant may carry display+download
   (or must they always be separate grants?).
8. Export approval workflow and approver roles for `DATASET_EXPORT`.

**What could NOT be specified (and why):** numeric budgets/thresholds (no
exploration-trace measurement exists — GAP-06 forbids guessing resource numbers,
ADR-KSI-038 D4); the CDN/browser threat model (needs the GAP-05 security review
this design calls for but does not constitute); acceptable attestation sources
(needs real surveyor/tool evidence + owner decision; inventing a list here would
risk weakening INV-053); the registration method list beyond EXTERNAL_ATTESTATION
(future customer evidence + GAP-03). Each is marked OPEN above rather than invented.

---

## Handoff summary (for the parent session)

- **File created:**
  `docs/design/REGISTRATION_ACCEPTANCE_AND_PURPOSE_SPLIT_CONTRACT_2026-10-21.md`
  (this document). Design only: no source/contract/runtime/policy/worker changes,
  no commits, no servers, no new Core jobs, no ledger/`.opencode` edits, no dashboard work.
- **Registration ownership (§A1):** server-side spatial-information processing
  layer (Core delivery + ingress/inspection owners) produces and verifies
  registration records; `packages/event-contracts` owns shapes/validators;
  `packages/geo-spatial` owns math only; Dashboard/MCP adapters CONSUME verdicts;
  UI never computes or asserts registration. Owning the method ≠ performing
  registration; today Core performs NO registration computation.
- **Acceptance (§A2):** EXTERNAL_ATTESTATION only. Record shape fixed
  (subjects pins / transform+CRS+units+frame / method+producer+evidence manifest /
  error metrics with pinned definitions / valid-area rule+geometry / comparisonKind).
  Core verifies in 9 conjunctive checks (subject binding, distinctness, CRS/frame,
  well-formedness + anti-bare-matrix, metric sanity, valid-area, evidence digests,
  method allow-list, purpose present) with 9 typed `REFUSE_*` reasons; in-place
  edits forbidden.
- **Purpose binding (§A3):** records admitted per `comparisonKind`
  (`VISUAL_SIDE_BY_SIDE < OVERLAY_ALIGNED < DIFFERENCE_COLOURING <
  QUANTITATIVE_VOLUME`); per-kind verdicts (`REGISTERED_FOR_KIND`,
  `NONE_INDEPENDENT_ONLY`, `WRONG_KIND_INSUFFICIENT`, `RECORD_STALE_SUBJECT_DRIFT`,
  `RECORD_REVOKED_OR_EXPIRED`); missing/wrong-purpose ⇒ independent viewing only
  with mandatory wording. No composite flag; three states stay separate.
- **Auto-registration (§A4):** separate future decision with 5 gates; nothing
  proposed or admitted now; `methodId` admits one value.
- **Purpose taxonomy (§B7):** `DISPLAY_VIEW` / `ORIGINAL_DOWNLOAD` /
  `ANALYSIS_INPUT` / `AI_EGRESS` (= existing `EXTERNAL_AI`, gate intact) /
  `DATASET_EXPORT`, each with permits / must-not / operations / outputs / audit /
  expiry. No implicit escalation; AI egress never a side effect of display rights;
  no existing gate weakened.
- **Reassembly control (§B8):** per-grant aggregate tile-read budget (source-pixel
  terms) + distinct display/download budgets + rate/anti-scraping guard +
  append-only tile-read audit; numeric F, thresholds, cache-hit weight, and the
  CDN/browser threat model are SEPARATE risk-assessment decisions (numbers not invented).
- **Ordinary exploration (§B9):** per-grant (not per-tile) authorization; budget
  calibrated so normal pan/zoom consumes a small fraction; limits are typed,
  truthful, recoverable states — never per-tile prompts, silent blocks, or fake fills.
- **Contract changes proposed (§A5/§B10):** EXTEND `PairRegistrationV1` additively
  (existing records keep parsing; old REGISTERED shapes cannot authorize kind-bound
  comparison until re-attested); new `ComparisonKindV1`, `PairRegistrationVerdictV1`,
  purpose enum members, `DisplayTileReadAuditV1`, two typed reasons.
  Contract = shapes/validators; Core = checks/verdicts/refusals/budgets.
- **Open decisions:** §A5.3 items 1–8 (producers, models, kinds, tolerances,
  valid-area registry, metric enum, quantitative re-decision, retention) + §B10
  items 1–8 (purpose names, TILE_READ op, budget numbers, cache threat model,
  attestation sources, kind tolerances, multi-purpose policy, export workflow).
- **Candid undecidables today:** numeric display budgets and harvesting thresholds
  (no exploration-trace measurement); CDN/browser-cache threat model (needs GAP-05
  security review); acceptable attestation sources (needs real surveyor evidence);
  per-kind tolerance numbers (needs owner policy + data); auto-registration method
  (needs its own 5-gate decision). None invented; all marked OPEN with the evidence
  each needs.
