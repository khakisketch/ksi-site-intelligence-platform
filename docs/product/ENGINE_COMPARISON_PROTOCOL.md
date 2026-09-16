# Engine Comparison Protocol (Static Research Only)

> Status: ACTIVE protocol only, subordinate to
> [ADR-KSI-036](../architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md).
> This file changes no frozen product authority
> (`docs/product/PRODUCT_CONSTITUTION.md`,
> `docs/product/FINAL_DECISION_LEDGER_v1.0.md`,
> `docs/product/MASTER_PRD_v3.0.md`,
> `docs/product/DOMAIN_INVARIANTS.md`), no registry, no contract, no runtime.
> Rank: below the frozen authorities above and below accepted ADRs and
> acceptance criteria (`docs/00_READ_FIRST.md` items 5-6), including
> ADR-KSI-036 and
> `docs/acceptance/EXTERNAL_PRODUCT_LOOP_STAGING_ACCEPTANCE.md`, and
> additionally subordinate to the named release plan
> `docs/superpowers/plans/2026-09-06-external-reconstruction-release.md`
> and the quantitative specification
> `docs/superpowers/specs/2026-09-09-external-quantitative-authority-v1.md`
> (implementation history per `docs/DOCUMENT_STATUS.md`, not items 5-6).
> Where this file conflicts with any of them, the frozen document, ADR, or
> acceptance/specification wins. It also changes
> no scope owned by `docs/product/MVP_SCOPE_AND_ENGINE_TRACKS.md`; that file
> remains the MVP/engine-track clarification and this protocol only consumes it.
> No new profile is issued, no Terra/Pix4D job is issuable, and no license fact
> is asserted here.
>
> Requirement IDs: REQ-WRK-101, REQ-INT-101/102/103/104 (civil processing,
> comparison, profiled execution).
> REQ-WRK-101 provenance: civil workload requirement reused from
> `docs/acceptance/CIVIL_PROCESSING_V1_ACCEPTANCE.md` (profiled-execution
> workload scope); ADR-KSI-036 itself lists REQ-INT-101/102/103/104,
> REQ-SEC-101, REQ-OPS-102, which apply to this protocol via the
> subordination above.
> Owner module: product protocol in `docs/product/` (non-runtime); measurement
> stays with `services/processing-controller/`, durable adjudication stays with
> `services/core/`.
> Reference assets: `docs/reference/ksi-terra/KSI_TERRA_ADOPTION_MATRIX.md`
> (`ODMRunner` ADOPT, `MetashapeRunner` REFERENCE_ONLY); no runtime import from
> `references/`.
> HIL / real-device assumptions: none executed by this protocol; any engine
> run needing device, field, or HIL evidence is a separate gate and is not
> performed here.
> License/data implications: ODM referenced as unmodified AGPL-3.0 container
> facts from existing acceptance only (see §4); Terra/Pix4D license facts are
> unresolved and recorded as `AWAITING-LICENSE` — no trial or commercial use
> is authorized by this file, and no installation or trial execution is
> performed under this protocol.
> Rollback: delete or supersede this single file; no runtime, contract, or
> registry state changes, so no migration or data rollback is needed.

## 1. Purpose and boundary (static research; no installation, no trials)

This protocol compares ODM, Terra, and Pix4D by **static research of
published documentation only**. No software is installed, no license is
activated, no trial is executed, and no sealed input is run through any
engine under this protocol. It produces comparability research notes only;
it does not issue a profile, authorize a vendor run, approve
survey/settlement accuracy, or change device capability state.

What this protocol does:

- Collects publicly documented engine facts into a versioned evidence
  table (§3), one row per engine/locus, with source, version, and date per
  fact.
- Maps those facts to the ADR-KSI-036 D5 undecided items (§5) so a future
  detailed specification can decide formats, semantic validation, and
  compatibility policy with contracts, validation, tests, and acceptance
  evidence.
- Retains the trial/commercial distinction as a research label (§6) without
  executing any trial.

What this protocol never does:

- No same-input execution, no worker measurement, no Core adjudication, no
  comparison verdict, and no cross-engine numeric delta is produced here.
  Per INV-053, engine/version mixing without a benchmarked compatibility
  mapping plus ADR is not comparison evidence; this protocol creates no
  such mapping.
- Until a registry entry plus ADR exists for a candidate, its research row
  stays `AWAITING-LICENSE` / `NOT_ISSUABLE` and no job for it can be issued
  (`UnknownProcessingProfileError` → `UNKNOWN_PROCESSING_PROFILE`).

Enforcing invariants (names; SSOT is `docs/product/DOMAIN_INVARIANTS.md`):

- **INV-024** — absolute accuracy only via sealed independent-checkpoint CSV
  re-sampled server-side; never a user-typed RMSE. Research records vendor
  accuracy statements as vendor claims with source, never as KSI findings.
- **INV-050** — vendor-cloud execution only with site egress consent,
  refused at creation (`EGRESS_NOT_ALLOWED`). Research notes execution
  locus as documented capability, not as an authorized KSI route.
- **INV-051** — Point Cloud is source SSOT within managed reconstruction;
  derived products never back success or measurement authority; external
  imports cannot forge source authority.
- **INV-053** — quantitative comparison only on the admitted compatibility
  rule (managed same-`processingProfileDigest` path, or the narrow external
  V1 rule in the quantitative specification); anything else is a typed
  blocker. This protocol grants no eligibility.
- **INV-054** — product-owned external runtime images are exact
  version + OCI digest pinned. Research pins document versions, not images
  for candidates.
- **INV-055** — every ProcessingJob passes Core-owned versioned
  resource-policy admission with a journaled snapshot. Research cost inputs
  (§2 axis 7) are admission-input facts, not approvals.
- **INV-060** — all researched bytes, jobs, and surfaces stay
  organization-isolated where applicable; published-document research uses
  no customer data.

## 2. Seven research axes (documentation facts only)

Every engine/locus row is researched on exactly these seven axes. Each cell
holds a documented fact plus its source, or `NOT_DOCUMENTED` /
`AWAITING-LICENSE` / `NOT_EVALUATED` — never an estimate or a measured
result.

1. **License model, including offline activation and trial limits.**
   Documented license tiers, activation model (offline-capable or
   account/cloud-bound where documented), trial limits (time, feature,
   export, watermark, commercial-use exclusion), and attribution or
   distribution constraints, each with source.
2. **Export formats: LAS/LAZ, GeoTIFF DSM/DTM/ortho, mesh, 3D Tiles.**
   Which product formats the vendor documents as exportable, including
   point-cloud (LAS/LAZ), elevation (GeoTIFF DSM/DTM), orthophoto, mesh,
   and tiled 3D (3D Tiles) where documented, plus any documented
   format-specific limits.
3. **CRS and vertical metadata handling.** How the vendor documents CRS
   selection, vertical reference handling, geoid support, and whether
   CRS/vertical metadata is embedded in exports or recorded alongside
   them, each with source.
4. **Reproducibility and parameter export.** Whether processing parameters,
   presets, or project settings can be exported, versioned, and re-applied
   as documented (parameter files, CLI flags, project archives), and what
   identifiers (software version, build, profile digest equivalent) the
   vendor documents for re-identifying a run.
5. **Local-vs-cloud execution and data residency.** Documented execution
   loci (local workstation, private server, vendor cloud), what leaves the
   operator's equipment in each locus per documentation, and any documented
   residency or egress controls. This axis records documented capability
   only; it authorizes no KSI-operated vendor-cloud route.
6. **Automation and CLI.** Documented command-line, scripting, or API
   automation surface (commands, batch modes, exit codes where
   documented), and any documented headless/offline automation limits.
7. **Cost inputs.** Documented pricing inputs relevant to future admission
   modelling (license tier inputs, seat/node limits, processing caps,
   credit or subscription inputs where documented). Research records inputs
   only; admission pass remains an operations boundary owned by INV-055 and
   is not processing success, cost finality, accuracy, or a
   data-distribution approval.

## 3. Evidence table template (source + version + date per fact)

Copy this template once per engine/locus row. Fill one row per fact; leave
unverifiable cells as `NOT_DOCUMENTED` or `AWAITING-LICENSE` with the
reason. Do not merge trial and commercial facts into one cell.

| Axis (§2) | Fact (≤ 2 sentences) | Source (title + publisher) | Doc version | Access date (UTC) | Research status |
|---|---|---|---|---|---|
| 1 license model | | | | | `CONFIRMED` / `NOT_DOCUMENTED` / `AWAITING-LICENSE` |
| 1 offline activation | | | | | as above |
| 1 trial limits | | | | | as above; trial/commercial kept separate per §6 |
| 2 LAS/LAZ export | | | | | as above |
| 2 GeoTIFF DSM/DTM export | | | | | as above |
| 2 ortho export | | | | | as above |
| 2 mesh export | | | | | as above |
| 2 3D Tiles export | | | | | as above |
| 3 CRS handling | | | | | as above |
| 3 vertical handling | | | | | as above |
| 4 parameter export | | | | | as above |
| 5 execution loci | | | | | as above |
| 5 data residency | | | | | as above |
| 6 automation/CLI | | | | | as above |
| 7 cost inputs | | | | | as above |

Rules:

- Every non-empty fact cites its exact source document, that document's
  version, and the UTC access date. Undated or unversioned vendor pages are
  cited with `version: UNDATED_PAGE` plus access date, never silently
  treated as versioned manuals.
- `AWAITING-LICENSE` means the underlying license fact is unresolved, so no
  use (trial or commercial) is authorized by this file.
- Empty cells are forbidden from becoming zeros, metrics, or verdicts.

## 4. ODM reference facts (published-record row, not a new run)

- Pinned image fact (from existing acceptance, no new execution):
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
- Under ADR-KSI-036, KSI-managed NodeODM is test/demonstration scope, not
  the first-release route; the facts above remain historical reference and
  are not relabeled as customer-operated results.

## 5. Candidate research rows and mapping to ADR-KSI-036 D5 undecided items

| Row | Engine / locus | Profile | Research status | Results |
|---|---|---|---|---|
| T-local | Terra local (offline/local research label) | No issuable profile ID; registry entry + ADR required | **AWAITING-LICENSE** (`NOT_ISSUABLE`) | None — documentation facts only, no run, no metric, no artifact |
| T-cloud | Terra cloud (vendor-cloud research label) | No issuable profile ID; registry entry + ADR + consent-record owner/schema/journal binding required; `EGRESS_NOT_ALLOWED` gate applies | **AWAITING-LICENSE** (`NOT_ISSUABLE`) | None — documentation facts only, no run, no metric, no artifact |
| P | Pix4D (research label) | No issuable profile ID; registry entry + ADR required | **AWAITING-LICENSE** (`NOT_ISSUABLE`) | None — documentation facts only, no run, no metric, no artifact |

Explicit mapping to the ADR-KSI-036 D5 undecided items (these remain
undecided; research informs but does not close them):

- **Accepted file formats and actual producer export compatibility** ← §2
  axis 2 (export formats) plus axis 3 (CRS/vertical metadata). Requires a
  future detailed specification with contracts, validation, compatibility
  policy, security review, tests, and acceptance evidence.
- **Semantic validation and provenance/trust verification evidence beyond
  byte identity** ← §2 axes 3–4 (CRS/vertical handling,
  reproducibility/parameter export). Requires the same future
  specification track.
- **Engine/version/profile compatibility and quantitative-comparison
  policy** ← §2 axes 4–5 (reproducibility, execution loci) constrained by
  INV-053. The only closed quantitative rule is the narrow external
  relative-volume V1 rule in
  `docs/superpowers/specs/2026-09-09-external-quantitative-authority-v1.md`;
  this protocol adds no cross-engine mapping.

## 6. Trial/commercial distinction (retained without trial execution)

Terra trial facts and commercial facts are recorded in separate table rows
when license documentation allows research at all. **Trial evidence never
backs a commercial accuracy or quantity claim, and trial results are never
promotable to commercial evidence.** No trial is installed or executed
under this protocol; the distinction is a documentation label only. DJI
Terra remains separately licensed Windows/NVIDIA software usable only
through a provider adapter; research does not change the
`services/core/` ← `services/processing-controller/` ← `packages/`
ownership boundary.

## 7. Recording rule and escalation

- Each engine/locus row records all seven axes with a sourced fact or a
  typed `NOT_DOCUMENTED` / `AWAITING-LICENSE` / `NOT_EVALUATED`; empty cells
  are forbidden from becoming zeros.
- Foreign-CRS or preservation-derivative fixtures cited from existing
  records are labelled as technical benchmarks only and never as Korean
  civil quantity or field acceptance.
- Every quantitative statement about existing records is labelled
  operational relative quantity until the separate field-acceptance gate
  (Korean LandXML, two same-site epochs, independent reference, recorded
  CRS/vertical/lineage/limits) is met elsewhere.
- Escalate to Build when: Terra or Pix4D license facts (trial vs. commercial
  terms, enterprise terms, offline activation, distribution constraints)
  become blocking; when this protocol would need a frozen-doc edit, a Phase
  Registry / `.ksi/` edit, a contract edit, or a new profile/registry/adapter
  change; or when any candidate consideration needs egress consent, device,
  field, or HIL scope.

## 8. Residual open questions (not decided here)

- Accepted file formats and actual producer export compatibility
  (ADR-KSI-036 D5 undecided).
- Semantic validation and provenance/trust verification evidence beyond
  byte identity (ADR-KSI-036 D5 undecided).
- Engine/version/profile compatibility and quantitative-comparison policy
  beyond the narrow external relative-volume V1 rule (ADR-KSI-036 D5
  undecided).
- Vendor license facts (trial vs. commercial terms, offline activation,
  enterprise/distribution terms) stay `AWAITING-LICENSE` until versioned
  vendor evidence is recorded in the §3 table.

## References (all paths exist at write time)

- `docs/product/PRODUCT_CONSTITUTION.md`
- `docs/product/FINAL_DECISION_LEDGER_v1.0.md`
- `docs/product/MASTER_PRD_v3.0.md`
- `docs/product/DOMAIN_INVARIANTS.md`
- `docs/product/MVP_SCOPE_AND_ENGINE_TRACKS.md`
- `docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md`
- `docs/acceptance/EXTERNAL_PRODUCT_LOOP_STAGING_ACCEPTANCE.md`
- `docs/superpowers/plans/2026-09-06-external-reconstruction-release.md`
- `docs/superpowers/specs/2026-09-09-external-quantitative-authority-v1.md`
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
