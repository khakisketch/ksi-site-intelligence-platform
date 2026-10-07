# Physical Site Intelligence — project rebaseline design

Date: 2026-10-07
Status: WRITTEN SPEC FOR HUMAN REVIEW; not an approved implementation plan
Task: [rebaseline ledger](../plans/2026-10-07-agent-first-platform-rebaseline.md)
Baseline: local main `b27e5d94b04d11e155e41d8df94c70519808a976`, current checkout, one writer.
Human authority: long-term acquisition exclusion; Physical Site Intelligence definition;
project cleanup before continuing long-term local development. Written-spec review remains open.

## 1. Purpose and scope

KSI Site Intelligence converts fragmented observations of physical spaces into evidence-bound
Site State and Change that people, AI agents, software and robotics can reuse. Construction and
earthwork are the first market, not the platform's exclusive identity. Its durable assets are
time-linked observations, state/change/evidence records and stable authorized interfaces, not
an aircraft, a chat UI or a single analysis algorithm.

This slice aligns product authority and repository ownership, removes acquisition from the normal
platform assembly and preserves useful verified capabilities. It does NOT rewrite the entire product,
implement every future data format, or create a universal Site State engine in the cleanup phase.
Use the existing repository and selected current checkout; no new repository or broad worktree cleanup.

## 2. Responsibility boundary

| Owner | Responsibility |
| --- | --- |
| External collectors and producers | Capture, survey, sensing, reconstruction, export and originals |
| KSI Core | Scoped identity, Site/WorkArea, observation/asset versions, permissions, admission, durable jobs, results and evidence |
| KSI processing workers | Supported inspection, data preparation and deterministic analysis under Core authority |
| API/MCP/SDK and Console | Access the same authoritative records; no independent computation or permission decisions |
| External consumers | Explanation, customer-specific analysis and business integration |
| People and external execution systems | Official decisions, real-world operations and equipment safety |

Flight, autonomous acquisition, tactical perception/control and customer production reconstruction
are outside long-term Site Intelligence responsibility, not merely postponed MVP work. Preserving
their historical contracts does not retain an active product roadmap or authorize their execution.
KSI Safety is not automatically assigned the removed capabilities; no other product is modified.

External agents are the primary agent integration. An embedded general chatbot, arbitrary GIS/code
execution, raw SQL, storage keys and executable flight commands are not new platform requirements.

## 3. State and trust semantics

Conceptual flow: external data → registered observation → use-specific inspection/eligibility →
evidence-bound State/Change → consumers → missing-data/work request → new external observation.
These names describe product concepts; cleanup alone creates no new wire type or endpoint.

Site State is a versioned, observation-bound projection, not an unqualified claim about the present.
Every exposed claim carries its observed time, area, exact inputs/revisions/digests, producer versus
measured facts, computation/policy/evaluation references, valid/excluded extent and limitations.
Absent, old, ambiguous or conflicting evidence remains explicit. A stale-data judgment requires a
defined policy; no universal freshness threshold is invented by this spec.

Registration, file identity, supported computability, accuracy evaluation, human review and official
issuance remain separate. Missing facts are not inferred; eligibility is use-specific. Missing DSM
must not deny an otherwise supported ortho use. A failed accuracy evaluation is not treated as absent.
Ground Truth Layer means traceable reality evidence, not absolute truth, settlement certification,
survey acceptance, operational safety or a robot-navigation guarantee.

Change in observed terrain is not automatically construction progress, approved cut/fill work or
payment quantity. Existing V1 strict and V2 provisional/evaluation rules and numerical meanings remain
unchanged. No implicit reprojection, co-registration, height adjustment or policy upgrade is introduced.

## 4. Target product skeleton and first useful experience

Retain a small core: identity and authorization; Site/WorkArea; submitted observations and asset
catalog; inspection/evidence/eligibility; data jobs and delivery; fixed analysis jobs/results;
durable history/recovery; API and bounded MCP adapters; necessary management/evidence Console.
Workers keep their independently operated lifecycle; import-only algorithms remain packages.

First experience: create Site/WorkArea → register two supported DSM observations → select area →
check compatibility → retrieve change, valid extent, provenance and limitations or actionable blockers.
Then reuse the area for the next epoch. API-first architecture supports the same record in Web and
one selected external agent workflow; a finished Web is not a reason to create a second agent backend.
`get_site_change(site, area, t1, t2)` is illustrative intent, not a new approved endpoint name.
Input selection must be deterministic and recorded; ambiguity cannot silently choose a source.

DSM/ortho native-grid Spatial Data V1 and existing Analysis V2 are reuse baselines, not redevelopment
tasks. DTM, point clouds, mesh, CAD/BIM, photographs/video, survey and sensor inputs are long-term
format/use-specific contracts, not automatic first-release support. Keep useful optional geometry
and conversion code where justified by actual consumers; do not remove it because it is not earthwork.

## 5. Evidence of current coupling

- `services/core/pyproject.toml` depends on mission-contracts, mission-planning and equipment-intelligence.
- `services/core/src/ksi_core/composition/workspace_graph.py` assembles acquisition connectivity,
  coordination, capture quality and managed readiness alongside external workspace features.
- `services/core/src/ksi_core/domains/external/ingress/spatial_asset_catalog.py` uses scoped WorkOrders
  and exact WorkArea bindings. WorkOrder also anchors external submission identity and history.
- `services/processing-controller/` contains managed reconstruction as well as external inspection,
  Analysis and Spatial Data worker lanes. Perception imports occur in managed runner/masking code.
- Root workspace membership, module inventories, tests, CI, scripts and deploy manifests participate
  in repository structure. Moving a directory without reconciling these is not completed cleanup.

Preserve identities and current API behavior during extraction. Split platform workflow from acquisition
mechanics; do not simply rename Mission into Observation or change existing serialized enum meanings.
Any unavoidable public contract break needs a versioned migration decision before its implementation.

## 6. Disposition rules

| Category | Target handling |
| --- | --- |
| Platform foundation and existing data/analysis lanes | RETAIN, minimal compatible extraction |
| Mixed domain, contracts, workflow, assembly and UI | SPLIT by actual dependencies, preserving platform consumers |
| Acquisition-only Edge/DJI/flight/planning/live perception | ARCHIVE after dependent edges are removed |
| Managed reconstruction | ARCHIVE as managed/test historical scope; retain needed historical readers |
| Optional spatial algorithms and BIM conversion | RETAIN only with named use; otherwise separately documented archive |
| Redundant unreferenced generated/tracked content | REMOVE only after ownership, references and recovery are proved |
| Private state, credentials, originals and foreign worktrees | PROTECT in place; never copy into tracked archive |

Default acquisition source archive: `archive/acquisition-2026/`, outside existing `packages/*` and
`services/*` workspace globs. This is a proposed destination; a file-level manifest chooses exact moves.
An archive is not a runtime import path, executable default, production build context or implicit
product support. Global discovery/type/lint/test/build rules must explicitly separate it. Historical
checks retain an explicit, bounded verification route and their original evidence meaning.

The manifest records each path's owner, purpose, classification, baseline SHA/hash, destination,
consumers, contract/replay consequences, test and deploy/CI references and restore procedure.
No move/removal begins without that file/group entry. Git history alone does not justify deleting
an active reference, private artifact or required historical reader.

Platform history remains tenant-scoped and retrievable with its original labels. Keep necessary
compatibility readers inside the active ownership boundary without importing the archive or mounting
acquisition mutation/dispatch routes. The detailed plan must identify the exact replay/import closure
and tests; if it cannot preserve it, the affected move waits while independent cleanup proceeds.

## 7. Authority and document reconciliation

Introduce a new product-boundary ADR, then align Constitution, Decision Ledger and PRD with it.
Do not erase prior approval provenance or reinterpret historical completion. Add explicit supersession
scope for acquisition decisions; retain numerical, identity, safety and provenance history.

Update `README.md`, `docs/00_READ_FIRST.md`, `docs/README.md`, `docs/DOCUMENT_STATUS.md`,
`docs/architecture/00_SYSTEM_OVERVIEW.md`, `REPOSITORY_STRUCTURE.md` and repository agent routing.
Replace active acquisition topology and product completion obligations with platform ownership.
Move obsolete standalone design documents to `docs/archive/` only after inbound links are reconciled;
mixed documents keep valid portions and label superseded sections with the current replacement.

Reconcile product-state, named roadmap and capability registry: acquisition-only future work becomes
historical/out-of-product, not falsely completed. Preserve previous evidence and open EXT-VAL/customer/
operational gates; new cleanup acceptance is separate. Preserve invariant IDs and explicitly map
platform, historical managed and acquisition applicability rather than deleting safety rules globally.

## 8. Staged execution boundaries

1. Authority/document reconciliation and file-level disposition manifest; no runtime move yet.
2. One platform-only assembly and worker dependency slice, using current fixed APIs and storage ports.
3. Acquisition-only sources and build/CI/deploy/tooling archive; close all live dependency edges.
4. Console route/navigation/action cleanup while retaining data/analysis/evidence/auth behavior.
5. Integrated independent verification, repository routing cleanup and next-development baseline.

Each slice gets tested, inspectable changes and a task-owned local commit before the next. Detailed
implementation plan must name files, contracts, touched invariants and observable tests per stage.
No new dependencies or host installation are implied. Local target remains current main; do not push,
publish, deploy, provision credentials/grants/policies, contact customers or operate equipment.

Visual source changes belong to the connected design workspace's local execution, with verified
source access and rendered review. Preserve approved brand/tokens; removing excluded actions is not
a new visual identity. Build owns nonvisual contracts, functional verification and Git. If that design
path is unavailable, record the UI stage blocked and continue safe independent nonvisual stages.

## 9. Acceptance and verification

| ID | Required cleanup evidence |
| --- | --- |
| RB-01 | Active authority consistently defines Physical Site Intelligence; acquisition is outside long-term scope |
| RB-02 | Complete disposition manifest, resolved links and no authoritative delegation to archived instructions |
| RB-03 | Platform assembly starts and uses data/analysis without acquisition stores, flight routes or acquisition-only package dependencies |
| RB-04 | Registration/inspection/catalog/data delivery/Analysis/MCP preserve scoped identity, grants, consent, source bindings and typed failures |
| RB-05 | Existing result/history and journal replay remain usable; V1/V2 and prior numeric/profile semantics do not change |
| RB-06 | Restart, idempotency, rights/consent revocation, tenant non-disclosure and bounded worker cleanup remain enforced |
| RB-07 | Changed Console flow works against the actual product, including auth reload, mobile and relevant empty/error states; design-owned render review recorded |
| RB-08 | Updated lock/build/package/inventory/CI checks cover active code; no hidden skips or archive-based runtime imports |
| RB-09 | Independent integrated revision checks, task-owned Git state and docs/checkpoint evidence reconcile |

Retain INV-020/024/040/050/051/053/054/055/060/061. Existing device/signed-Mission invariants continue
to constrain preserved legacy contracts; removal from current responsibility is not permission to
weaken them. Relevant contract/replay/HTTP/worker/MCP/static/build checks are chosen from actual
changes; historical full-suite numbers are not a substitute for checks on the integrated revision.
Separate archived tests from active tests transparently; reducing scope is not a pass of omitted tests.

## 10. Recovery and limits of completion

Record source/build baselines before moves; restore only task-owned paths through a reviewed inverse
change, not reset/clean operations. Archive manifests and compatibility readers permit reconstruction
without changing old journal bytes, profile digests or submitted artifacts. No destructive data migration.

Cleanup completion means a coherent, locally verified platform baseline. It does not mean customer
acceptance, universal format/vendor support, quantitative accuracy, robotics safety or production readiness.
Actual permitted customer t0/t1/t2 exports/rights, independent use and selected operational environment
remain absent. Continue approved local engineering where possible, but report those real blockers.
Future contracts such as generalized Site State, new formats, feeds, external result registration and
remote agent topology get their own scoped design/plan; long-term autonomy does not approve them by default.

## 11. Review handoff

Human review of this written spec is required before implementation planning. Recommended execution
after written-plan approval: sequential developer tasks with independent final verification; one writer
per shared file, design-owned UI. A new session goal can coordinate authorized long-running work only
after explicit agreement; the previous unmet goal remains closed. Stop reports must give usable outcome,
revision/check evidence, why work stopped, open acceptance/blockers, responsible party and next action.
