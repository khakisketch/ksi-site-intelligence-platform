# MVP Scope and Engine Tracks (Subordinate to ADR-KSI-036)

> Status: ACTIVE clarification for MVP scope, explicitly subordinate to
> [ADR-KSI-036](../architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md)
> (ACCEPTED 2026-09-06). This file changes no frozen product authority:
> `docs/product/PRODUCT_CONSTITUTION.md`,
> `docs/product/FINAL_DECISION_LEDGER_v1.0.md`,
> `docs/product/MASTER_PRD_v3.0.md`, and
> `docs/product/DOMAIN_INVARIANTS.md` remain the product authority in the
> order fixed by `docs/00_READ_FIRST.md`. Routing is owned by
> `REPOSITORY_STRUCTURE.md` and `docs/DOCUMENT_STATUS.md`; current phase
> state is owned by `docs/goals/PHASE_REGISTRY.yaml` and `.ksi/`.
> Rank: this file sits **below** the frozen product authorities above and
> **below** accepted ADRs and acceptance criteria (`docs/00_READ_FIRST.md`
> items 5-6), including ADR-KSI-036 and
> `docs/acceptance/EXTERNAL_PRODUCT_LOOP_STAGING_ACCEPTANCE.md`, and
> additionally subordinate to the named release plan
> `docs/superpowers/plans/2026-09-06-external-reconstruction-release.md`
> and the quantitative specification
> `docs/superpowers/specs/2026-09-09-external-quantitative-authority-v1.md`
> (implementation history per `docs/DOCUMENT_STATUS.md`, not items 5-6).
> Where this file conflicts with any of them, the frozen document, ADR, or
> acceptance/specification wins. Indexing/routing of this file in
> `docs/DOCUMENT_STATUS.md` or `docs/goals/PHASE_REGISTRY.yaml` is owned
> by the Primary, not by this edit.
> Any pre-ADR-036 text describing KSI-server reconstruction as the
> first-release route, or a vendor-cloud route operated by KSI as the
> Terra evaluation route, is **historical residue**, not scope.
> This file issues no new normative profile ID and claims no KSI-operated
> vendor-cloud run.

## 1. MVP range (what is in, what is not)

- MVP is the civil-operations closed loop only: repeat observation →
  capture-quality supplement → two-epoch change/progress/relative quantity →
  evidence-grounded query → human-approved re-observation.
- First paid job is progress/relative-quantity management on repeated
  observation (ADR-KSI-022). Contract settlement and survey-grade accuracy
  are out of MVP claims.
- Surveying (licensed survey acceptance, cadastral/procurement use) is a
  **separated** concern. MVP produces operations-relative quantities plus an
  optional independent-checkpoint error bound as operations evidence; it does
  not approve survey-grade or settlement acceptance.
- Security posture for MVP in frozen terms only: vendor-cloud execution
  without site egress consent is refused at creation (`EGRESS_NOT_ALLOWED`,
  INV-050), and there is no remote deployment/release authorization
  (`docs/acceptance/CIVIL_PROCESSING_V1_ACCEPTANCE.md`); automatic source
  offload stays OFF/`NOT_VERIFIED` before physical HIL
  (`FINAL_DECISION_LEDGER_v1.0.md`). No new security mode is defined here.

## 2. First-release responsibility boundary (ADR-KSI-036 D1)

- **First release: customer runs reconstruction on equipment the customer
  owns or controls; KSI registers, verifies, and analyzes exported
  artifacts.** The split, per ADR-KSI-036 D1, is:
  ```text
  Customer: select/license/run reconstruction software and export results
  KSI: register submitted facts -> verify evidence/provenance -> analyze only eligible results
  KSI-managed NodeODM: test/demonstration scope, not the first-release route
  ```
- **KSI-managed NodeODM is test/demonstration only.** ADR-KSI-030 profiles
  and their completed results remain historically meaningful and immutable;
  they must not be relabeled as customer-operated results and they are not
  the first-release route. No KSI-server reconstruction run is the
  first-release route.
- **Register, verify, and analyze are distinct states.** Registration records
  what was supplied. Verification determines whether supplied facts and
  their evidence are credible for a stated use. Quantitative eligibility is a
  later, stricter decision governed by the quantitative specification.
  A registered export is **neither verified nor quantitatively eligible** by
  registration alone. KSI does not represent an unverified artifact as a KSI
  reconstruction result (ADR-KSI-036 D1).

## 3. Customer-owned originals and first-release package (ADR-KSI-036 D4)

- **Original photos stay on customer equipment.** Normal first-release
  result registration must not require uploading every original. KSI retains
  submitted derived outputs and bounded provenance/quality metadata.
  Original backup, availability for customer-side reprocessing, and any
  separately authorized evidence transfer are explicit operational
  responsibilities, not an implied KSI backup service.
- **First-release package composition:**
  - ortho-only packages are registrable for later validation and viewing;
    missing DSM does not prevent registering an ortho;
  - DSM supports eligible height/relative-volume uses under the quantitative
    specification;
  - point cloud and DTM are function-dependent additions;
  - mesh is optional visualization.
- Neither raw-upload absence nor missing evidence for one claim permanently
  blocks unrelated uses. A local manifest or checksum does not prove
  raw-byte possession, input completeness, or reconstruction accuracy
  (ADR-KSI-036 D4).

## 4. Managed-vs-external authority distinction (ADR-KSI-036 D2; INV-051)

- An external import is a separately identified externally produced result
  with asserted and verified facts kept distinct. It must not forge a
  successful `ProcessingJob`, sealed raw bundle, source-authority point
  cloud, source-media authority, or an existing KSI-managed profile
  identity. A customer export cannot inherit a KSI profile digest, engine
  identity, or lineage merely because filenames or product labels resemble
  one.
- INV-051 still prevents derivative artifacts from becoming source
  authority. Existing managed NodeODM profile snapshots, their
  `ProcessingJob` records, source bundles, and results remain immutable;
  ADR-KSI-030 continues to describe that managed/test scope while ADR-KSI-036
  controls the first-release product direction without rewriting history.

## 5. Fail-closed claim boundaries (ADR-KSI-036 D3)

- Unknown or unverified provenance, CRS, vertical reference, processing
  quality, source lineage, or compatibility restricts every dependent claim.
  KSI must expose the gap rather than infer values, equivalence, coverage,
  accuracy, or suitability.
- INV-053 still blocks time-series, earthwork, stockpile, or design
  comparison unless all required evidence is known and compatible. INV-060
  still scopes all imported facts and evidence to the authenticated
  organization and prevents cross-organization disclosure.
- This file creates no blanket BIM prerequisite and authorizes no
  unsupported progress percentage, contract-settlement quantity,
  survey-grade, absolute-accuracy, or RMSE claim. Processing success, an
  export label, or registration alone establishes none of those claims.

## 6. Engine-track note (no new normative IDs; no KSI-operated vendor-cloud route)

- The code registry issues only `ksi-odm-civil-v1`; any unknown ID raises
  `UnknownProcessingProfileError`
  (`services/core/src/ksi_core/processing_profiles.py`; issuance gate
  `services/core/src/ksi_core/processing_jobs.py` refuses it as
  `UNKNOWN_PROCESSING_PROFILE`). This file issues no new normative profile
  ID. Terra and Pix4D names, where they appear in comparison research, are
  research labels only, not issuable profile IDs; no Terra or Pix4D job can
  be issued until a registry entry plus ADR exist.
- No vendor-cloud run operated by KSI is claimed here as a first-release or
  evaluation route. Any future vendor-cloud consideration stays bounded by
  the existing creation-time gate (refused without
  `dataResidency.egressAllowed=true`, `EGRESS_NOT_ALLOWED`) and by a
  required consent-record owner/schema/journal binding plus registry entry
  and ADR before any issuance. Engine comparison method itself is owned by
  `docs/product/ENGINE_COMPARISON_PROTOCOL.md` as static research only
  (no installation, no trial execution).
- Trial/commercial split is recorded, not executed: Terra trial runs and
  commercial runs would be recorded separately; trial evidence never backs a
  commercial accuracy or quantity claim. This file authorizes no trial run.
- DJI Terra remains separately licensed Windows/NVIDIA software usable only
  through a provider adapter; this note does not change the
  `services/core/` ← `services/processing-controller/` ← `packages/`
  ownership boundary.

## 7. Point-cloud principle (SSOT; managed scope)

- **Within managed reconstruction, Point Cloud is the source SSOT.** Mesh,
  3D Tiles, orthophoto, DSM/DTM derivatives are serving layers derived
  from it.
- Every managed reconstruction artifact carries `lineage.authority:
  source | derived` anchored by Core to the sealed bundle digest.
  `RUNNING → SUCCEEDED` requires at least one `authority=source` artifact;
  derived-only success is refused. Derived products never substitute for
  source authority in measurement or completion evidence.
- External imports never gain managed source authority by registration;
  §4 governs.

## 8. Enforcing invariants (names)

- **INV-050** — vendor-cloud execution only with site egress consent (creation-time gate).
- **INV-051** — source/derived lineage; managed Point Cloud SSOT; derived
  cannot back success; external imports cannot forge source authority.
- **INV-053** — same-profile/same-lineage/same-CRS comparison preflight
  with typed blockers; external quantitative eligibility additionally
  requires the quantitative specification rule.
- **INV-055** — Core-owned versioned resource-policy admission with journaled snapshot.
- **INV-024** — RTK Fix is not absolute accuracy; absolute RMSE only via sealed independent-checkpoint CSV re-sampling, never user-typed RMSE.
- **INV-060** — organization isolation via authenticated principal; cross-org reads/writes (including existence) refused.

## 9. Residual open questions (not decided here)

- Accepted file formats and actual producer export compatibility
  (ADR-KSI-036 D5 undecided; owned by a future detailed specification).
- Semantic validation and provenance/trust verification evidence beyond
  byte identity (ADR-KSI-036 D5 undecided).
- Engine/version/profile compatibility and quantitative-comparison policy
  (ADR-KSI-036 D5 undecided; narrow V1 rule only in the quantitative
  specification).
- Terra license facts (trial vs. commercial terms, DJI enterprise terms,
  offline activation limits) remain unverified here; engine research records
  them as `AWAITING-LICENSE` per the comparison protocol. If a production
  Terra claim is needed, escalate for license evidence instead of extending
  this file.

## References (all paths exist at write time)

- `docs/product/PRODUCT_CONSTITUTION.md`
- `docs/product/FINAL_DECISION_LEDGER_v1.0.md`
- `docs/product/MASTER_PRD_v3.0.md`
- `docs/product/DOMAIN_INVARIANTS.md`
- `docs/DOCUMENT_STATUS.md`
- `REPOSITORY_STRUCTURE.md`
- `docs/goals/PHASE_REGISTRY.yaml`
- `docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md`
- `docs/acceptance/EXTERNAL_PRODUCT_LOOP_STAGING_ACCEPTANCE.md`
- `docs/superpowers/plans/2026-09-06-external-reconstruction-release.md`
- `docs/superpowers/specs/2026-09-09-external-quantitative-authority-v1.md`
- `contracts/`
- `services/core/`
- `services/processing-controller/`
- `apps/dashboard/`
- `docs/reference/ksi-terra/KSI_TERRA_ADOPTION_MATRIX.md`
- `docs/acceptance/CIVIL_PROCESSING_V1_ACCEPTANCE.md`
- `services/core/src/ksi_core/processing_profiles.py` (issued-profile registry; sole v1 entry `"ksi-odm-civil-v1"`; factory `ksi_odm_civil_v1()`)
