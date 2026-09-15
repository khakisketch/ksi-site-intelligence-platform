# Engine Comparison Protocol (Same-Input, 3-Engine)

> Status: ACTIVE protocol only. This file changes no frozen product authority
> (`docs/product/PRODUCT_CONSTITUTION.md`,
> `docs/product/FINAL_DECISION_LEDGER_v1.0.md`,
> `docs/product/MASTER_PRD_v3.0.md`,
> `docs/product/DOMAIN_INVARIANTS.md`), no registry, no contract, no runtime.
> Rank: below the frozen authorities above and below accepted ADRs and
> acceptance criteria (`docs/00_READ_FIRST.md` items 5-6). Where this file
> conflicts with any of them, the frozen document or ADR wins. It also changes
> no scope owned by `docs/product/MVP_SCOPE_AND_ENGINE_TRACKS.md`; that file
> remains the MVP/engine-track clarification and this protocol only consumes it.
> No new profile is issued, no Terra/Pix4D job is issuable, and no license fact
> is asserted here.
>
> Requirement IDs: REQ-WRK-101, REQ-INT-101/102/103/104 (civil processing,
> comparison, profiled execution).
> Owner module: product protocol in `docs/product/` (non-runtime); measurement
> stays with `services/processing-controller/`, durable adjudication stays with
> `services/core/`.
> Reference assets: `docs/reference/ksi-terra/KSI_TERRA_ADOPTION_MATRIX.md`
> (`ODMRunner` ADOPT, `MetashapeRunner` REFERENCE_ONLY); no runtime import from
> `references/`.
> HIL / real-device assumptions: none executed by this protocol; any engine
> run needing device, field, or HIL evidence is a separate gate.
> License/data implications: ODM consumed as unmodified AGPL-3.0 container
> over REST (see acceptance deployment gate); Terra/Pix4D license facts are
> unresolved and recorded as `AWAITING-LICENSE` — no trial or commercial use
> is authorized by this file.
> Rollback: delete or supersede this single file; no runtime, contract, or
> registry state changes, so no migration or data rollback is needed.

## 1. Purpose and boundary

This protocol defines how ODM, Terra, and Pix4D are compared on the **same
sealed input** without claiming any Terra or Pix4D result. It produces
comparability evidence only; it does not issue a profile, authorize a vendor
run, approve survey/settlement accuracy, or change device capability state.

Enforcing invariants (names; SSOT is `docs/product/DOMAIN_INVARIANTS.md`):

- **INV-024** — absolute accuracy only via sealed independent-checkpoint CSV
  re-sampled server-side; never a user-typed RMSE.
- **INV-050** — vendor-cloud execution only with site egress consent,
  refused at creation (`EGRESS_NOT_ALLOWED`).
- **INV-051** — Point Cloud is source SSOT; derived products never back
  success or measurement authority.
- **INV-053** — quantitative comparison only on same
  `processingProfileDigest` plus matching Analysis Readiness, CRS, vertical
  reference, source lineage, and (for design) same design-surface
  revision/normalization digest; anything else is a typed blocker, and
  engine/version mixing without a benchmarked compatibility mapping is not
  comparison evidence.
- **INV-054** — product-owned external runtime images are exact
  version + OCI digest pinned.
- **INV-055** — every ProcessingJob passes Core-owned versioned
  resource-policy admission with a journaled snapshot.
- **INV-060** — all compared bytes, jobs, and surfaces stay
  organization-isolated.

## 2. Same-input 3-engine method

Engines: **ODM** (MVP production track), **Terra** (candidate, two execution
loci: local / online), **Pix4D** (candidate). "3-engine" means three vendors;
Terra is scored in two loci rows, so the evidence table has four rows.

Same-input rules (all engines, every run):

1. Identical sealed `SourceMediaBundle` digest(s) for the epoch(s) under
   comparison; identical CRS, vertical reference, design-surface revision and
   normalization digest where design conformance is scored.
2. Identical sealed independent-checkpoint CSV digest where accuracy is
   scored (optional input; when absent, accuracy is `NOT_EVALUATED`, never
   zero or estimated).
3. One run per engine per input; each engine runs under its own issued
   profile ID/digest. Cross-engine numeric deltas are **technical overlap
   signals only** unless a benchmarked cross-engine compatibility mapping
   plus ADR exists — per INV-053, same-`processingProfileDigest` is the only
   v1 automatic compatibility, so ODM-vs-Terra and ODM-vs-Pix4D deltas never
   satisfy the comparison preflight by themselves.
4. Workers measure (bytes, digests, dimensions, DSM sampling); Core
   adjudicates (seal, job issue/success, comparison verdicts, checkpoint
   `VALIDATED`). Worker verdicts never overwrite the ledger.
5. No engine run rewrites another engine's history: profiles are immutable;
   a new engine, version, preprocessing, or masking choice requires a new
   profile plus validation (ledger rule carried by
   `docs/product/MVP_SCOPE_AND_ENGINE_TRACKS.md`).

Until a registry entry plus ADR exists for a candidate, its rows stay
`AWAITING-LICENSE` / `NOT_ISSUABLE` and no job for it can be issued
(`UnknownProcessingProfileError` → `UNKNOWN_PROCESSING_PROFILE`).

## 3. Seven comparison axes

Every engine/locus row is scored on exactly these seven axes. A missing input
yields a typed blocker or `NOT_EVALUATED`, never an estimate.

1. **Accuracy (server-computed only).** Independent-checkpoint CSV is sealed
   per DSM; the Processing Controller reads the sealed CSV bytes and the DSM
   bytes, re-checks both digests and CRS, and computes per-point
   mean/MAE/RMSE/max server-side. Out-of-range or nodata points are typed
   rejections, not partial statistics. Only Core-`VALIDATED` results may
   inform an operational uncertainty note (INV-024 ②③④ wiring); client-typed
   RMSE is refused at three layers and never accepted.
2. **Artifacts (CRS-vertical-format).** Required set per profile
   (v1 ODM: point cloud = source authority, DSM/DTM = derived serving
   layers, plus orthophoto/mesh/report as emitted); each artifact records
   CRS, vertical reference, format, digest, and source/derived lineage
   anchored to the sealed bundle digest. CRS or vertical mismatch blocks
   comparison (`CRS_MISMATCH`, `VERTICAL_REFERENCE_MISMATCH`).
3. **Reproducibility (digest).** Profile ID + profile digest, OCI image +
   digest, preprocessing/model lineage, source bundle digest(s), artifact
   digests, and journal snapshot must fully re-identify the run. Re-runs
   with identical digests must reproduce identical comparison verdicts;
   anything floating (`latest`, undigested image) is rejected per INV-054.
4. **Operability.** Standard runbook outcome on the same input: issue →
   lease → run → heartbeat → `SUCCEEDED` with required artifacts, plus
   failure-mode honesty (typed errors, no mock/static always-go, no silent
   fallback). Human touchpoints, poll/retry behavior, and log/digest
   auditability are recorded; production profile gate (INV-040) applies.
5. **Execution-egress.** Execution locus (KSI server/GPU, local/offline,
   vendor cloud) versus the site's `dataResidency.egressAllowed`: a
   vendor-cloud candidate on a site without explicit egress consent is
   refused at creation (`EGRESS_NOT_ALLOWED`, INV-050). The locus of every
   run is recorded; post-hoc egress approval never retro-authorizes a run.
6. **License (trial-commercial split).** Every candidate run records its
   license basis (license ID, tier, trial-vs-commercial flag, attribution and
   distribution constraints). Trial runs and commercial runs are recorded
   separately (see §5). Unverified license facts stay `AWAITING-LICENSE`.
7. **Cost (admission inputs).** Resource-policy admission inputs bound at
   issuance: sealed-byte counts, megapixels, active-job counts, policy
   version/snapshot/digest (INV-055). Admission pass is an operations
   boundary only — it is not processing success, cost finality, accuracy, or
   a data-distribution approval. Measured runtime/egress/compute observables
   may be recorded alongside, but client-supplied caps or overrides are
   refused.

## 4. ODM baseline (the only completed row)

- Pinned image:
  `opendronemap/nodeodm@sha256:cb07d06e21fd6189cfad287c6fedfa0b72568100355635cd9035cb86eed42ee2`
  (NodeODM 2.2.4 / ODM 3.5.6; `dsm=true`, `dtm=true`, `pc-quality=medium`,
  dynamic-object masking OFF).
- Registry pointer (sole v1 issued entry, immutable):
  `services/core/src/ksi_core/processing_profiles.py::ksi_odm_civil_v1`
  (`KSI_ODM_CIVIL_V1_ID = "ksi-odm-civil-v1"`); deploy pin mirror:
  `deploy/compose.yaml`; issuance gate:
  `services/core/src/ksi_core/processing_jobs.py` (`UNKNOWN_PROCESSING_PROFILE`
  for anything unregistered).
- Existing acceptance (software only, not field acceptance):
  `docs/acceptance/CIVIL_PROCESSING_V1_ACCEPTANCE.md` (status
  `SOFTWARE_PASS / PRODUCT_E2E_PARTIAL / FIELD_NOT_EVALUATED`; matrix CP-01…
  HY-01; foreign-CRS benchmark caveat; AGPL source-offer deployment gate) and
  the non-sensitive digest record
  `docs/acceptance/CIVIL_TWO_EPOCH_BENCHMARK_2026-08-29.json`
  (`BENCHMARK_PASS`, `scope: NON_PRODUCTION_FOREIGN_CRS_BENCHMARK_ONLY`,
  `fieldAcceptance: NOT_EVALUATED`,
  `productQuantitativeComparisonExecutable: false`; Madeira mean absolute DSM
  delta `1.99291 m` is a finite technical overlap signal only, not accuracy,
  change, cut/fill, or progress evidence).

## 5. Candidate rows (no results claimed)

| Row | Engine / locus | Profile | Status | Results |
|---|---|---|---|---|
| T-local | Terra local (offline/local candidate) | No issuable profile ID; registry entry + ADR required | **AWAITING-LICENSE** (`NOT_ISSUABLE`) | None — no run, no metric, no artifact |
| T-online | Terra online (vendor-cloud candidate) | No issuable profile ID; registry entry + ADR + consent-record owner/schema/journal binding required; `EGRESS_NOT_ALLOWED` gate applies | **AWAITING-LICENSE** (`NOT_ISSUABLE`) | None — no run, no metric, no artifact |
| P | Pix4D (candidate) | No issuable profile ID; registry entry + ADR required | **AWAITING-LICENSE** (`NOT_ISSUABLE`) | None — no run, no metric, no artifact |

Trial/commercial split: Terra trial runs and commercial runs are recorded
separately when license facts allow runs at all. **Trial evidence never backs
a commercial accuracy or quantity claim, and trial results are never
promotable to commercial evidence.** DJI Terra remains separately licensed
Windows/NVIDIA software used only through a provider adapter; evaluation does
not change the `services/core/` ← `services/processing-controller/` ←
`packages/` ownership boundary.

## 6. Recording rule and escalation

- Each engine/locus row records all seven axes with digests or a typed
  blocker/`NOT_EVALUATED`; empty cells are forbidden from becoming zeros.
- Foreign-CRS or preservation-derivative fixtures are labelled as technical
  benchmarks only and never as Korean civil quantity or field acceptance.
- Every result is labelled operational relative quantity until the separate
  field-acceptance gate (Korean LandXML, two same-site epochs, independent
  reference, recorded CRS/vertical/lineage/limits) is met elsewhere.
- Escalate to Build when: Terra or Pix4D license facts (trial vs. commercial
  terms, enterprise terms, distribution/AGPL-equivalent constraints) become
  blocking; when this protocol would need a frozen-doc edit, a Phase Registry
  / `.ksi/` edit, a contract edit, or a new profile/registry/adapter change;
  or when a candidate run needs egress consent, device, field, or HIL scope.

## References (all paths exist at write time)

- `docs/product/PRODUCT_CONSTITUTION.md`
- `docs/product/FINAL_DECISION_LEDGER_v1.0.md`
- `docs/product/MASTER_PRD_v3.0.md`
- `docs/product/DOMAIN_INVARIANTS.md`
- `docs/product/MVP_SCOPE_AND_ENGINE_TRACKS.md`
- `REPOSITORY_STRUCTURE.md`
- `docs/DOCUMENT_STATUS.md`
- `docs/goals/PHASE_REGISTRY.yaml`
- `contracts/`
- `services/core/src/ksi_core/processing_profiles.py`
- `services/core/src/ksi_core/processing_jobs.py`
- `services/processing-controller/`
- `apps/dashboard/`
- `deploy/compose.yaml`
- `docs/reference/ksi-terra/KSI_TERRA_ADOPTION_MATRIX.md`
- `docs/acceptance/CIVIL_PROCESSING_V1_ACCEPTANCE.md`
- `docs/acceptance/CIVIL_TWO_EPOCH_BENCHMARK_2026-08-29.json`
