# Spatial Asset Catalog V1 Implementation Plan

> **For agentic workers:** Implement the bounded tasks below with red/green tests. KSI policy forbids an unapproved commit, PR, merge, deployment, or credential change; skill commit steps do not apply.

**Plan ID:** SDP-CATALOG-20260930  
**Goal:** Let an authorized external client discover sealed customer spatial artifacts and their observed identity without granting data-byte access or analysis eligibility.  
**Architecture:** Core projects its existing WorkOrder, external submission, manifest, and inspection authority into one bounded read model. The new API uses existing principal, Site, and WorkArea grants; it creates no new asset authority, object URL, or separate persistence.  
**Tech Stack:** FastAPI, Pydantic, journal-backed Core stores, pytest contract/replay tests.  
**Spec:** `docs/architecture/ADR-KSI-038-spatial-data-and-analysis-platform.md`; `docs/product/MASTER_PRD_v3.0.md` SDP-REQ-01/02/06; `docs/superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md` SDP-02/03.

The roadmap's full SDP-02 contract awaits customer samples. CAT-01 is the subset
whose identity and read authority already exist in the sealed ingress graph. It
does not decide raster compatibility, delivery rights, area semantics, or a
production data-preparation profile. Those remain SDP-DATA-01 gates.

## Global Constraints

- Source reconstruction remains customer-owned per ADR-KSI-036. Registering/sealing a file does not assert spatial correctness, quantitative eligibility, accuracy, or permission to distribute bytes.
- Reuse the existing `Site`, `WorkArea`, `ObservationWorkOrder`, `submissionRef`, revision, and observed manifest digest. Do not create an independent mutable asset identity.
- Every client read must enforce principal organization, Site grant, WorkArea grant, and `SITES_READ` or the established scoped Analysis client read permission. A foreign resource must not disclose existence.
- Every item must label customer-declared metadata separately from KSI-observed facts and inspection facts. Missing facts stay absent/unknown.
- List page size is at most 50 and structured responses are at most 512 KiB. Continuation must not allow a caller to bypass current grants or retrieve another Site.
- Do not expose internal object keys, storage capabilities, upload URLs, or customer `submissionId` in this catalog.
- Preserve INV-020, INV-024, INV-040, INV-051, INV-053, INV-060, INV-061 and existing Analysis V1/V2 behavior.

## Review Focus

- A user with Site access but only one WorkArea grant sees only assets unambiguously bound to that WorkArea.
- A foreign Site or a later revoked grant cannot retrieve a prior page or detail from a saved link/cursor.
- A declared hash/CRS must never be displayed as an observed hash/CRS when inspection is absent.
- An unsealed or superseded submission must not advertise byte delivery or analysis readiness.
- A large number of WorkOrders/revisions and malformed pagination input must remain bounded and deterministic.

---

### Task SDP-CAT-01: Core catalog read contract and projection

**Owner:** one `worker` in `/tmp/ksi-first-product-candidate-20260929`; Lead integrates exact reviewed files into main.  
**Dependencies:** current sealed ingress/WorkOrder/auth/inspection graph; synthetic test fixtures only.  
**Files:** new focused Core catalog module in `services/core/src/ksi_core/domains/external/ingress/`; `services/core/src/ksi_core/composition/routes/external.py`; a dedicated API contract model in `packages/event-contracts/src/ksi_event_contracts/`; `contracts/api/openapi-core.yaml`; focused `tests/contract/` and `tests/replay/` files; Core README only if needed for route documentation. The scoped customer OIDC route allowlist in `services/core/src/ksi_core/identity/auth.py` and `tests/contract/test_oidc_route_scope.py` are included because the new GET routes otherwise reject mapped customers before resource-grant checks. Add only the exact catalog GET templates; keep the MCP allowlist closed.  
**Review correction ownership:** `services/core/src/ksi_core/domains/sites/observation_work_orders.py`, `services/core/src/ksi_core/domains/external/ingress/external_reconstruction.py`, and `services/core/src/ksi_core/domains/external/ingress/external_artifact_inspections.py` may receive narrow bounded snapshot/cardinality methods to prevent a catalog request from performing unbounded source work. The matching owner tests may change. Existing store API behavior and journals must remain compatible.  
**Review correction 2 ownership:** `services/core/src/ksi_core/domains/external/ingress/external_validation_policy.py` and focused policy tests may receive a bounded inspection-policy selection method for this catalog read. Preserve the existing unbounded policy-selection semantics for other callers, the journal, and mutation authority. Catalog overage remains an explicit refusal.  
**Acceptance:** GET Site-scoped list and exact asset detail; stable asset reference composed from existing opaque submissionRef/revision/artifact ID; bounded pagination **and a finite backend enumeration/inspection work budget that fails explicitly on overage**; explicit declaration/observed/inspection states and supported actions, including the available observed raster footprint/CRS/transform/dimensions and separately labeled producer completion time; no binary capability; tenant and WorkArea denial; replay returns same immutable observed identity. The contract may use an opaque server-issued page token, but each request rechecks grants.  
**Validation:** start with failing contract cases for unsealed/sealed, missing inspection, cross-tenant, WorkArea, page bounds/cursor tamper, response size; then implement and run those tests plus relevant existing ingress/inspection/Analysis selector tests.  
**Stop:** if the existing WorkOrder-to-WorkArea relationship or inspection projection cannot safely represent a single-asset fact, return the exact ambiguity to Lead; do not invent eligibility.

### Task SDP-DATA-01: DSM and orthophoto area delivery contract

**Owner:** Lead design and later bounded worker implementation, after CAT-01 integration.  
**Dependencies:** representative authorized DSM and orthophoto exports, request footprint/output examples, rights and baseline sizes for final production limits. Synthetic fixtures can prove software behavior but cannot close customer compatibility.  
**Deliverable:** choose exact supported GeoTIFF profile, area CRS/bounds and edge behavior, output grid/NoData, fixed resource budget, durable job/idempotency and authorized byte delivery/revocation contract. Record the contract and tests before implementation.  
**Stop:** do not label Terra export support, operational performance, or rights as verified from synthetic rasters.

### Task SDP-CLIENT-01: API and one MCP client consumption

**Owner:** bounded MCP/integration worker after DATA-01.  
**Deliverable:** selected MCP client sees same Core asset/job/result IDs and limitations; external sample program reads output bytes and coordinates without internal paths. Client enforces no policy itself.  
**Validation:** contract plus end-to-end synthetic raster/data and existing Analysis V2 ID comparison.

### Task SDP-UX-01: Minimal data status and remediation UI

**Owner:** bounded Dashboard worker after CAT-01/DATA-01.  
**Deliverable:** user can find an asset, see declaration versus observed/inspection status, request supported area data, and understand a refusal; it reads Core facts.  
**Validation:** focused component/browser flow, no fabricated eligibility.

### Task SDP-CAT-UI-01: Read-only catalog visibility in Dashboard

**Owner:** one bounded `worker` in the existing isolated candidate worktree, after CAT-01 integration. **Dependency:** existing scoped catalog GET contract. This is the metadata-only subset of SDP-UX-01; it does not depend on DATA-01 or implement preparation/delivery.

**Requirement IDs:** SDP-REQ-01/02/05/06, ADR-KSI-038 D2/D4; preserve INV-020/040/051/053/060/061. **Owner module:** `apps/dashboard/`, reading Core only. **Acceptance:** a signed-in operator can select one WorkArea, page through its catalog (50 max), open exact asset detail, and see customer declaration, byte observation, inspection state and measured raster facts with distinct labels. Missing inspection, unsealed/superseded, no data access, and no analysis eligibility remain explicit. A revoked/foreign scope fails closed; a saved cursor/detail never bypasses Core. No new byte link or agent capability.

**Contracts affected:** no Core wire/schema change; typed client mirrors `spatial-asset-catalog.v1` response only. **Reference assets/adoption:** existing observations/analysis pages, `coreFetch`, Core catalog contract; REFERENCE_ONLY for reference repos. **Files:** new `apps/dashboard/src/lib/core-api/spatial-assets.ts`, new scoped page under `apps/dashboard/src/app/sites/[siteId]/spatial-assets/`, a small link from the existing observations page, and focused tests. Avoid changing global navigation or unrelated styles. **Tests:** start with failing page/client cases for selection, pagination/detail, declaration versus inspection, 404/403/503, and no bytes; then focused Vitest, TypeScript, ESLint/build as the changed surface warrants. **HIL/real-device:** none. **License/data:** synthetic metadata only; no customer export or data rights asserted. **Rollback:** remove only the new Dashboard page/client/link and tests, retaining Core catalog and prior WIP.

**Authorization/status:** 2026-09-30 user requested continued development and remaining-work assessment. Commit, deployment, host/credential mutation and customer contact remain separate gates. The current EXT-VAL slice is not closed by this Dashboard subset.

## Current authority and release boundary

**Review checkpoint (2026-09-30):** First candidate freeze is
`.opencode/artifacts/spatial-catalog-20260930/review-freeze.json` with
`review.patch`. Independent security/contract review returned
**CHANGES_REQUIRED**: backend source/inspection work was unbounded, and the
projection omitted available observed raster extent/CRS and producer
completion time. The same worker is correcting these in SDP-CAT-01. The first
candidate is not integrated or accepted. Formatter-only changes in two
pre-existing files are also being removed. Review and focused checks must be
repeated on the corrected exact file hashes.

Second freeze `review2-freeze.json` and `review2.patch` in the same artifact
directory received **CHANGES_REQUIRED** for one remaining bounded-work issue:
inspection-policy selection scans all policies before the new per-subject
inspection cap. The same task and worker own this correction; no candidate has
been integrated into main.

**SDP-CAT-01 local software checkpoint:** third freeze `review3-freeze.json`
and `review3.patch` received independent **PASS** on exact 17 path hashes and
the pre-existing WIP baseline. Lead copied only those 17 files to main after
verifying before/after hashes; `integration.json` records the integrated set.
On the integrated source, catalog/OIDC/policy/WorkOrder/reconstruction/inspection
contract and replay tests: **125 passed**; OpenAPI sync: **36 passed**; related
Analysis/ingress/inspector contract tests: **78 passed**; Ruff on changed Python
files and scoped `git diff --check`: pass. No commit, remote CI, host/customer
acceptance, or data-byte delivery was performed. The exact subject retains a
64-policy lifetime cap; a Site has 256 WorkOrders and 2,048 revisions per
catalog request, with 256 submissions/WorkOrder and 128 inspections/subject.
Excess returns 503 rather than a partial success. These are first-pilot
software limits and need workload measurement before production sizing.

The user's 2026-09-30 instruction resumed software development. This does not authorize commit, push, PR, merge, deployment, host/credential changes, or customer contact. `EXT-VAL` remains the current product slice; this task is an explicitly assigned bounded platform task and does not close or reorder that slice. Local synthetic tests are software evidence; customer export, OIDC, Tailnet host, two real cycles, and customer acceptance remain separate gates.

**SDP-CAT-UI-01 local software checkpoint:** independent review of the first
five-file candidate required correction of the Core artifact-kind wire values
and archived WorkArea history. The corrected five files received **PASS** on
`.opencode/artifacts/spatial-catalog-ui-20260930/review2-freeze.json` and were
copied byte-exact into main. A narrow follow-up stopped imprecise JavaScript
numbers from being displayed as exact byte sizes; review3 **PASS** and
`integration3.json` record the final two-file delta and hashes. On integrated
source, focused Dashboard tests **11 passed**, TypeScript and touched-path
ESLint passed, and `next build` generated `/sites/[siteId]/spatial-assets`.
The page uses Core's current scoped read on every list/detail request and
labels declared, observed and inspected facts separately. It offers no data
download or analysis eligibility claim. Evidence is in the same artifact
directory's `verification.json`; browser/customer/host acceptance is absent.
