# MVP Scope and Engine Tracks (Active Clarification)

> Status: ACTIVE clarification for MVP scope. This file fixes Codex-era
> confusion about MVP range, Terra profiles, engine tracks, and the
> point-cloud principle. It changes no frozen document:
> `docs/product/PRODUCT_CONSTITUTION.md`,
> `docs/product/FINAL_DECISION_LEDGER_v1.0.md`,
> `docs/product/MASTER_PRD_v3.0.md`, and
> `docs/product/DOMAIN_INVARIANTS.md` remain the product authority in the
> order fixed by `docs/00_READ_FIRST.md`. Routing is owned by
> `REPOSITORY_STRUCTURE.md` and `docs/DOCUMENT_STATUS.md`; current phase
> state is owned by `docs/goals/PHASE_REGISTRY.yaml` and `.ksi/`.
> Rank: this file sits **below** the frozen product authorities above and
> below accepted ADRs and acceptance criteria (`docs/00_READ_FIRST.md`
> items 5-6). Where this file conflicts with any of them, the frozen
> document or ADR wins. Indexing/routing of this file in
> `docs/DOCUMENT_STATUS.md` or `docs/goals/PHASE_REGISTRY.yaml` is owned
> by the Primary, not by this edit.
> Any Codex-drafted profile/track text that conflicts with this file is
> **historical residue**, not scope.

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

## 2. Canonical MVP path (SD-PC-Web, same digest, Core adjudication, Console review)

- **SD-PC-Web path.** The current normal source-media ingress is
  `SD/storage → field PC → KSI web upload` (ADR-KSI-033). PSDK Liveview is
  Manifold-local acquisition/perception input; `EDGE_UPLINK` carries bounded
  EventBundle/EdgeBundle metadata only. Automatic source offload
  (`MEDIA_PULL`/`MEDIA_UPLOAD`) is a separately gated target capability,
  `NOT_VERIFIED`/OFF before physical HIL.
- **Same-digest comparison.** Quantitative comparison (time-series, earthwork,
  stockpile, design conformance) is allowed only when both epochs share the
  same `processingProfileDigest` plus matching Analysis Readiness, CRS,
  vertical reference, source lineage, and (for design) the same design-surface
  revision/normalization digest. Anything unknown or mismatched returns a
  typed blocker, never an estimated number.
- **Core adjudication.** Processing workers measure (bytes, digests,
  dimensions, DSM sampling); Core adjudicates durable state (SourceMedia
  seal, ProcessingJob issue/success, comparison verdicts, checkpoint
  `VALIDATED`). Worker verdicts never overwrite the ledger.
- **Console review.** The human surface is the single responsive KSI
  Operations Console (`apps/dashboard/`). RC Plus 2 / Pilot 2 stays
  flight-only. Blockers, lineage gaps, and evidence limits are shown, not
  hidden.

## 3. Engine tracks (ODM production; Terra candidates; adapter set open)

ODM is the MVP production track. The two Terra names below are **candidate
evaluation labels, not issuable profile IDs**: the code registry issues only
`ksi-odm-civil-v1` and any unknown ID raises `UnknownProcessingProfileError`
(`services/core/src/ksi_core/processing_profiles.py`; issuance gate
`services/core/src/ksi_core/processing_jobs.py` refuses it as
`UNKNOWN_PROCESSING_PROFILE` — "Core registry에서 발급된 값만 쓴다").
No Terra evaluation job can be issued until a registry entry plus ADR exist.

| Track | Label / profile | Disposition |
|---|---|---|
| ODM civil | `ksi-odm-civil-v1` — `opendronemap/nodeodm@sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2` (NodeODM 2.2.4 / ODM 3.5.6; `dsm=true`, `dtm=true`, `pc-quality=medium`, dynamic-object masking OFF; registry `services/core/src/ksi_core/processing_profiles.py::ksi_odm_civil_v1`) | **RETAIN** — immutable MVP production profile; never rewrite history by editing it |
| Terra local (candidate) | "Terra local" evaluation label | **EVALUATE** — offline/local candidate; no issuable profile ID, no preflight fixture, no replay coverage; trial-vs-commercial license split unresolved, so no production comparison or commercial claim |
| Terra online (candidate) | "Terra online" evaluation label | **EVALUATE** — vendor-cloud candidate; same issuance and license limits as Terra local |

- The adapter set stays **open** per `MASTER_PRD_v3.0.md` (provider adapter:
  Terra, ODM/Pix4D, or own pipeline) and the Terra adoption matrix
  (`ODMRunner` ADOPT, `MetashapeRunner` REFERENCE_ONLY). New engines,
  versions, preprocessing, or masking require a new profile plus benchmarked
  compatibility mapping and validation (ledger); engine/version mixing
  without it is not comparison evidence. This file closes no track set.
- **Terra online evaluation-route proposal (not a default).** Treating Online
  as the Terra evaluation route is a proposal only: it requires a defined
  consent-record owner/schema/journal binding plus a registry entry and ADR
  **before** any issuance. Until then, execution is bounded by the existing
  gate: a vendor-cloud job on a site without
  `dataResidency.egressAllowed=true` is refused at creation (`EGRESS_NOT_ALLOWED`).
- Trial/commercial split: Terra trial runs and commercial runs are recorded
  separately; trial evidence never backs a commercial accuracy or quantity claim.
- DJI Terra remains separately licensed Windows/NVIDIA software used only
  through a provider adapter; Terra evaluation does not change the
  `services/core/` ← `services/processing-controller/` ← `packages/`
  ownership boundary.

## 4. Point-cloud principle (SSOT)

- **Point Cloud is the source SSOT.** Mesh, 3D Tiles, orthophoto, DSM/DTM
  derivatives are serving layers derived from it.
- Every reconstruction artifact carries `lineage.authority: source | derived`
  anchored by Core to the sealed bundle digest. `RUNNING → SUCCEEDED`
  requires at least one `authority=source` artifact; derived-only success is
  refused. Derived products never substitute for source authority in
  measurement or completion evidence.

## 5. Enforcing invariants (names)

- **INV-050** — vendor-cloud execution only with site egress consent (creation-time gate).
- **INV-051** — source/derived lineage; Point Cloud SSOT; derived cannot back success.
- **INV-053** — same-profile/same-lineage/same-CRS comparison preflight with typed blockers.
- **INV-055** — Core-owned versioned resource-policy admission with journaled snapshot.
- **INV-024** — RTK Fix is not absolute accuracy; absolute RMSE only via sealed independent-checkpoint CSV re-sampling, never user-typed RMSE.
- **INV-060** — organization isolation via authenticated principal; cross-org reads/writes (including existence) refused.

## 6. Codex residue (historical, not scope)

- Any Codex-generated text asserting Terra profiles as production, inventing
  extra engine tracks, equating trial with commercial evidence, routing source
  bytes over `EDGE_UPLINK`/central Liveview, or overriding frozen decisions is
  **historical residue**. Where such text survives in audits, `.ai/` notes, or
  superseded plans, it is evidence of past confusion, superseded by this file
  plus the frozen authorities above.
- Terra license facts (trial vs. commercial terms, DJI enterprise terms)
  remain unverified here; if a production Terra claim is needed, escalate for
  license evidence instead of extending this file.

## References (all paths exist at write time)

- `docs/product/PRODUCT_CONSTITUTION.md`
- `docs/product/FINAL_DECISION_LEDGER_v1.0.md`
- `docs/product/MASTER_PRD_v3.0.md`
- `docs/product/DOMAIN_INVARIANTS.md`
- `docs/DOCUMENT_STATUS.md`
- `REPOSITORY_STRUCTURE.md`
- `docs/goals/PHASE_REGISTRY.yaml`
- `contracts/`
- `services/core/`
- `services/processing-controller/`
- `apps/dashboard/`
- `docs/reference/ksi-terra/KSI_TERRA_ADOPTION_MATRIX.md`
- `docs/acceptance/CIVIL_PROCESSING_V1_ACCEPTANCE.md`
- `services/core/src/ksi_core/processing_profiles.py` (issued-profile registry; sole v1 entry `ksi_odm_civil_v1`)
