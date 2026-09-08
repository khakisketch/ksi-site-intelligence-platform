# Terrain-aware observation planning design contract

Status: APPROVED design baseline (2026-09-06). This document defines intended semantic records;
it is **not** an implemented API, schema, wire contract, DJI compatibility claim, or field result.
Authority: [ADR-KSI-035](../architecture/ADR-KSI-035-terrain-aware-planning-and-pilot-execution.md).

## Profiles and boundaries

| Design profile | KSI responsibility | Pilot/device responsibility | Non-negotiable boundary |
|---|---|---|---|
| `PILOT_MANUAL_EXECUTION` | deterministic proposal, validation result, original-plan evidence, postflight assessment | import, optional exception edit, final approval, execution | no edited-plan preflight return; no KSI claim that an unknown edit was authorized |
| `AUTONOMOUS_EXECUTION` | future validated final artifact, signed binding and policy | future device activation/execution only after receipt | INV-011/012/016 remain strict; manual exception cannot supply this path |

Neither profile grants Core frame-by-frame control (INV-001), lets an LLM generate coordinates or
approval (INV-002), replaces DJI FC avoidance/RTH, or exposes cross-organization evidence
(INV-060). These labels must become explicit versioned values only in a separately approved
contract change.

## Eventual additive records

The names below are design names, deliberately not endpoint paths or existing model names.

| Record | Required content | Produces/links | Unknown or failure semantics |
|---|---|---|---|
| `PlanningInputSnapshot` | organization/site/AOI, aircraft/camera profile, target GSD, front/side overlap intent, altitude constraints, operator takeoff point, orientation, safety-policy references, terrain/structure/transit evidence, CRS/vertical reference, provenance/freshness/uncertainty | immutable planner input digest | unavailable/stale/conflicting input is typed; never zero-filled or treated as safety proof |
| `StructuredPlanDraft` | deterministic planner/version, geometry and capture proposal, validation findings, planned-quality estimates, assumptions and exclusions | draft ID, snapshot digest, artifacts | draft quality is not executable validation, operational safety, or actual coverage |
| `PlannedArtifact` | exact bytes, format, digest, source, generated revision and draft link | KSI original-plan evidence | no Pilot import/device acceptance implied |
| `PilotFinalPlanObservation` | optional declared unchanged/edited/unknown modification state, supplied bytes/export/digest if any, edit reason and actor time | observation linked to original plan | absent export or unknown modification remains unknown; declaration is not device proof |
| `PilotFlightOutcomeObservation` | optional declared `ABORTED`/other outcome, outcome reason and actor time | distinct flight-outcome observation | outcome is not modification truth and is not a device receipt |
| `ActualFlightObservation` | optional device log/trajectory receipt, receipt verifier/version, time span and scope | actual-path evidence | no receipt means no actual-trajectory claim; a plan is never substituted |
| `CaptureObservation` | registered source media, integrity/capture-time/lineage facts and quality/coverage reports when present | analysis inputs | missing media/report blocks only claims that need it |
| `ClaimScopedAssessment` | evaluated claim, exact evidence IDs/digests, rule/profile versions, pass/gap/unknown reasons | observation, coverage, analysis or quantitative eligibility statement | cannot authorize past flight or infer omitted evidence |

All links are organization and Site scoped. Exact bytes are retained only where policy permits;
otherwise a digest plus lawful storage reference and retention state must make the limitation
visible. Actor declaration, server receipt, and device receipt are distinct evidence kinds.

## Planning inputs and degraded evidence

The intended planner accepts a first-site minimum of a lawful AOI, observation requirement,
available camera facts and an explicit operating envelope. It may consume public geodata and
operator-provided takeoff/transit/known-structure facts. Own DSM/BIM/point cloud/site visit data is
optional refinement, never a hidden precondition. GNSS facts are not an obstacle map.

Initial mapping records `mode=INITIAL` and has no prior-KSI-result prerequisite. Repeat observation
records `mode=REPEAT` and links only versioned prior KSI results actually used (or a typed absence).
Partial reobservation records `mode=PARTIAL_REOBSERVATION`, the triggering change/coverage/quality
evidence and its versioned source region. AOI/region geometry must be supplied by an authenticated
operator or a versioned deterministic KSI calculation; an LLM may request a draft but cannot supply
executable geometry. Each mode keeps its input lineage rather than silently inheriting an unstated
prior model or analysis result.

Aircraft/camera profile, target GSD, front/side overlap intent, altitude constraints, operator
takeoff point, orientation and safety-policy references must be explicit input fields or typed
unknowns. This contract selects no numeric default for them. If takeoff/corridor evidence is absent
or critical terrain/structure evidence is unresolved, the outcome is a reviewable draft with a
typed gap, never an executable or safety-approved artifact.

Terrain and known-structure evidence needs source identity, license/terms decision, acquisition
time or publication version, spatial/vertical reference, resolution/coverage, uncertainty and
applicability to the AOI/transit. The absence of any such field must make the relevant candidate
plan validation `UNKNOWN` or `GAP`; it must not generate an assurance. A future source-selection
record must separately justify legality, access, freshness, vertical handling, coverage, failure
behavior and retention. It has no approved supplier today.

### Candidate evidence matrix (not an adoption decision)

| Candidate | What the official source supports | Explicit limit before any use |
|---|---|---|
| [VWorld WebGL 3D map API](https://www.data.go.kr/data/3073144/openapi.do) | nationwide JS/WebGL/Cesium-facing visualization/API catalogue entry | visualization does not establish raw geometry export, caching/redistribution terms, height completeness, freshness, obstacle fidelity, or KSI account availability |
| [NGII product-family brochure](https://www.ngii.go.kr/lib/file/pr_01.pdf) | historical existence of elevation products | not current layer coverage, resolution entitlement, download/API or license proof; exact current catalogue/layer and terms remain required |
| [Copernicus DEM collection](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM) | a DSM collection with 2011–2015 acquisition and older infill | contextual terrain evidence, not a live construction-obstacle map; actual returned version, coverage and acquisition details are required |
| [Copernicus DEM API documentation](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM.html) | endpoint behavior, including authorized CCM access for COPERNICUS_30 and an unspecified-instance default of COPERNICUS_90 | eligibility and exact instance must be proved; a 90m response or upsampling must never be labelled requested 30m evidence |
| [DJI geospatial FAQ](https://enterprise-insights.dji.com/blog/geospatial-solutions-faq) and [PSDK waypoint tutorial](https://developer.dji.com/doc/payload-sdk-tutorial/en/function-set/advanced-function/waypoint-mission.html) | terrain-following and API concepts exist in DJI materials | neither proves M4D/RC/current-firmware support, KSI path authorization, safety, or superiority to Pilot 2 |

The Copernicus [candidate license artifact](https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Data/DEM/resources/license/License-COPDEM-30.pdf)
may be reviewed in the source-adoption record; no agent accepts it on behalf of the Human. A dated
view-service change is not generalized to all raw-data distribution paths. Imagery or a generic
building catalogue never establishes current building height, temporary structures, or airspace
restrictions.

## Validation and claim separation

| Question | Evidence required | What a positive result does **not** prove |
|---|---|---|
| Draft quality | deterministic geometry/camera/coverage calculations and assumptions | DJI importability, flight safety, actual capture or completion |
| Executable artifact validation | format/structure/scope validation appropriate to the profile | Pilot/device acceptance or actual execution |
| Operational safety | applicable pilot, regulatory, site, weather and device procedures | derivation from map/terrain data alone |
| Actual observation | device receipts, logs, media, quality and coverage evidence as applicable | quantitative-analysis eligibility without its own evidence |
| Quantitative eligibility | INV-017/018 plus INV-020/024/051/053 requirements | survey-grade/contract-settlement accuracy |

The current `AnalysisReadiness` projection remains deterministic and fail-closed, but it is not
already the planned per-claim assessment interface. A future `ClaimScopedAssessment` consumes its
evidence/reason state with the additional claim-specific rule. A missing final plan or actual log
does not prohibit raw media registration or reconstruction merely by being missing; it prevents
only path/claim assertions that depend on it. Missing CRS, vertical reference, profile, lineage,
integrity or independent-checkpoint evidence remains a typed blocker for the relevant quantitative
claim.

## Current gap matrix

| Surface | Observed status | This design does not claim |
|---|---|---|
| AOI/camera/coverage/WPML candidate planning | partially existing software | terrain/structure/transit integration or Pilot acceptance |
| terrain grid/profile helpers | existing isolated software asset | a Core input source, waypoint wiring, safety validation or device execution |
| KSI planned artifact | candidate/fallback evidence | field-compatible default or actual flight |
| Pilot final-plan, flight-log and capture relationship | not implemented as this additive contract | edit detection, device receipts or actual trajectory |
| analysis readiness/epoch | existing global evidence-derived projection | the planned per-claim assessment semantics, global observation acceptance, field quality, or hardware support |
| claim-scoped assessment | not implemented as this additive contract | that current readiness already adjudicates every dependent claim separately |

## Research and threshold closure gate

Before runtime work selects a source, threshold, or optimization objective, a reviewable closure
record must state the decision question, candidate primary sources, version/date, terms and
permitted use, spatial/vertical semantics, empirical or official supporting evidence, residual
uncertainty, rejected alternatives, owner, and acceptance test. It must also record a representative
lawful sample and decoding/CRS/vertical/nodata checks; a supplier switch must produce a new input
snapshot/version. The record must separately propose, review and approve benchmark metrics
(coverage gaps, GSD distribution, known-constraint violations, ingress/transit/normal-return
feasibility, path length/time estimates and pilot edits) before it chooses acceptance thresholds.
A worker may investigate and prepare that record but may not choose a supplier or invent numerical
safety/quality value.

See the [successor roadmap](../goals/TERRAIN_AWARE_PLANNING_ROADMAP.md) for ownership and
validation gates and the [acceptance matrix](../acceptance/TERRAIN_AWARE_PILOT_MVP_ACCEPTANCE.md)
for evidence that remains NOT_RUN/NOT_VERIFIED.
