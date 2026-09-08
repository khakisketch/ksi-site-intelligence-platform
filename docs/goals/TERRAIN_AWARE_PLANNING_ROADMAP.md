# Terrain-aware planning successor roadmap

Authority: [ADR-KSI-035](../architecture/ADR-KSI-035-terrain-aware-planning-and-pilot-execution.md),
[design contract](../design/TERRAIN_AWARE_OBSERVATION_PLANNING_CONTRACT.md), and
[acceptance](../acceptance/TERRAIN_AWARE_PILOT_MVP_ACCEPTANCE.md).

Goal `terrain-aware-planning-design-baseline` is completed for this documentation baseline only;
see the [review evidence](../audit/TERRAIN_AWARE_PLANNING_DESIGN_BASELINE_REVIEW.md).
Future goals `terrain-aware-planning-software` and
`terrain-aware-planning-field-acceptance` are `proposed`; neither is authorization to start
runtime/device work. Design approval is not runtime implementation or field acceptance.
The existing `aol-3-terrain-aware-planning` capability track is retained as prior, broader
terrain-aware work; this roadmap scopes a Pilot-default evidence model and does not close, replace,
or relabel that goal's software or physical gates.

## Shared execution rules

Every packet uses a clean separate worktree, preserves unrelated WIP, follows TDD, and returns
changed files, tests actually run/results, unresolved risks, and deviations. Workers must stop for
schema/OpenAPI changes not in their packet, supplier/license selection, threshold or optimization
selection without a closure record, customer data, device access, external side effects, conflicts,
or required Human authorization. A worker is followed by an independent reviewer; changed workers
are re-reviewed. The Lead performs integrated validation. Run at most two or three independent
writers, with no overlapping files, and run an integration review after combined changes.

### WP-0: authority and common contract closure

- Objective: own and freeze both shared interfaces before parallel work: versioned
  `PlanningInputSnapshot` (including mode/input lineage and degraded-evidence semantics) and
  `StructuredPlanDraft`/`PlannedArtifact` output plus the evidence-handoff envelope consumed by
  postflight records. Turn ADR-035 design vocabulary into an approved, versioned implementation
  contract only after the source/threshold closure record is accepted.
- Owned modules: `contracts/`, `packages/mission-contracts/`, `services/core/` contract adapters,
  `tests/contract/`, `tests/replay/` selected by the approved packet.
- Forbidden scope: device adapters, flight commands, Dashboard UI, customer data, vendor bytes,
  autonomous activation, and changing existing wire behavior in place.
- Worktree policy/dependencies: one dedicated worktree; starts after WP-R research closure.
- Required skills: `superpowers:brainstorming`, `superpowers:test-driven-development`,
  `superpowers:verification-before-completion`.
- Validation: focused contract round-trip/replay for the frozen input/output/evidence-handoff
  interfaces, profile separation, unknown evidence and organization isolation; `git diff --check`.
- Return/stop: publish the exact frozen interface/version ownership and additive migration/rollback;
  stop if a profile cannot be represented additively or a signed-autonomous gate would weaken.

### WP-R: geodata, threshold and objective evidence closure

- Objective: produce an approval-ready `TerrainPlanningSourceAdoptionRecord` and
  `TerrainPlanningBenchmarkDecision` for Human decision. The former must name exact layer/version,
  access method, terms decision, representative lawful sample, decoding/CRS/vertical/nodata results,
  freshness/coverage/uncertainty limits, rejected candidates and new input-snapshot version on
  supplier switch. The latter must define benchmark fixtures and reviewable metric baselines for
  coverage gaps, GSD distribution, known-constraint violations, ingress/transit/normal-return
  feasibility, path length/time estimates and pilot edits before any acceptance threshold is chosen.
- Owned modules: documentation/evidence record only, under a new approved docs path.
- Forbidden scope: selecting/procuring a supplier, accepting a license, downloading proprietary
  data, runtime code/schema changes, customer data and device actions.
- Worktree policy/dependencies: one documentation worktree; may run before WP-0 but closes before
  WP-0/WP-1 implementation.
- Required skills: `deep-research-work:deep-research` and
  `superpowers:verification-before-completion`.
- Validation: primary-source links resolve; exact source version/date/terms/access are captured;
  lawful sample decoding and CRS/vertical/nodata checks are reproducible; each proposed metric has
  fixture evidence; and every numerical/optimization conclusion is evidence-backed or unresolved.
- Return/stop: return both records, alternatives, residual uncertainty and decision questions; stop
  when primary-source/terms/access/sample evidence is unavailable rather than guessing. The Human
  must explicitly approve or reject each record before WP-0/WP-1/WP-2 runtime implementation.

### WP-1: terrain and known-structure input adapter

- Objective: implement approved provenance-aware terrain/structure input snapshots and typed
  degraded-evidence results without making terrain a first-site prerequisite.
- Owned modules: approved `packages/geo-spatial/` and its tests only.
- Forbidden scope: waypoint generation, Core issuance behavior, device/API integration, source
  selection changes, safety claims and UI.
- Worktree policy/dependencies: separate writer worktree after WP-0 and WP-R; consumes and
  implements against the WP-0-frozen input interface but cannot edit that interface or its adapter.
  It may run in parallel with WP-2/WP-3.
- Required skills: `superpowers:test-driven-development`,
  `superpowers:verification-before-completion`.
- Validation: unit/contract cases for first-site absence, stale/conflicting evidence, CRS/vertical
  metadata, lineage and organization scope; `git diff --check`.
- Return/stop: report data semantics/limitations; stop for unapproved vertical conversion or
  license/data access assumptions.

### WP-2: deterministic terrain-aware planner

- Objective: wire approved inputs into deterministic draft planning for terrain, known structures,
  irregular AOIs and takeoff/transit/normal-return candidate segments.
- Owned modules: `packages/mission-planning/` and its focused tests only.
- Forbidden scope: Core API/schema changes, Pilot/device execution, reactive avoidance/RTH,
  supplier/threshold selection and UI.
- Worktree policy/dependencies: separate worktree after WP-0/WP-R; consumes WP-0's frozen input
  and output interfaces and cannot edit them. It may run in parallel with WP-1/WP-3.
- Required skills: `superpowers:test-driven-development`,
  `superpowers:systematic-debugging`, `superpowers:verification-before-completion`.
- Validation: deterministic replay for first-site, irregular AOI, missing/stale inputs, planned
  GSD/coverage distinction and no fixed-altitude-only regression; package-focused tests.
- Return/stop: identify unsupported terrain/structure situations as typed gaps; stop if safety or
  hardware behavior would need to be inferred.

### WP-3: Core planning and postflight evidence records

- Objective: add approved immutable original-plan, pilot-final-plan observation, actual-log and
  capture evidence records plus claim-scoped assessment.
- Owned modules: `services/core/`, `packages/mission-contracts/` adapters approved in WP-0, and
  focused contract/replay tests.
- Forbidden scope: automatic media transfer, actual device receipt fabrication, retroactive flight
  authorization, Dashboard UI, and autonomous activation changes.
- Worktree policy/dependencies: separate worktree after WP-0; consumes WP-0's frozen
  input/output/evidence-handoff interfaces and may run parallel with WP-1/WP-2 only if no shared
  contract files are edited.
- Required skills: `superpowers:test-driven-development`,
  `superpowers:verification-before-completion`.
- Validation: changed/unknown/absent Pilot evidence, no-preflight-return manual flow, claim-scoped
  readiness, cross-organization isolation and autonomous regression tests.
- Return/stop: document migrations/dual readers; stop if a manual flow could bind as autonomous or
  if an existing final artifact must be rewritten.

### WP-4: Console evidence projection

- Objective: present plan/evidence distinctions and typed claim gaps in Operations Console after
  APIs are stable.
- Owned modules: `apps/dashboard/` and its tests only.
- Forbidden scope: new planner/Core contracts, flight approval/control, synthetic evidence and
  mobile operational writes.
- Worktree policy/dependencies: separate worktree after WP-3 APIs/replay tests pass; no parallel
  Dashboard writer.
- Required skills: `superpowers:brainstorming`, `superpowers:test-driven-development`,
  `vercel:react-best-practices`, `superpowers:verification-before-completion`.
- Validation: focused UI/unit tests plus TypeScript/lint and browser scenarios for unknown versus
  false, evidence gaps and organization isolation.
- Return/stop: report actual browser evidence; stop if UI would represent declaration as device
  receipt or change the approved one-primary-action boundary.

### WP-5: Pilot/HIL and field evidence

- Objective: run only separately Human-approved propeller-off then field procedures to collect
  import/edit/export/log/capture evidence and evaluate TAP-11 onward.
- Owned modules: approved HIL tooling/procedures and private evidence store only.
- Forbidden scope: unapproved device write/flight, credentials, public/raw evidence, production
  activation and using a successful import as a flight/safety conclusion.
- Worktree policy/dependencies: one operator-owned physical session with explicit Human
  authorization; no concurrent code writer. An early, separately authorized propeller-off
  import/export compatibility session may occur after WP-0's evidence vocabulary is reviewed; it
  is not required to wait for WP-3/WP-4 and cannot promote field acceptance or unblock runtime
  contracts by itself.
- Required skills: `superpowers:verification-before-completion`.
- Validation: approved FIELD checklist/audit commands, exact session attestations and evidence
  hashes; no result beyond the procedure's stated maximum conclusion.
- Return/stop: record PASS/FAIL/BLOCKED with redacted evidence references; stop on missing approval,
  unsafe condition, absent device receipt or scope change.

## Sequencing gate

`WP-R -> WP-0(freeze shared input/output/evidence-handoff interfaces) -> (WP-1, WP-2, WP-3)`;
the three workers consume but cannot alter those interfaces, then integrate before `WP-4`. An early
propeller-off slice of WP-5 may run after reviewed WP-0 vocabulary under separate Human approval;
the complete field path follows integrated software and never establishes that integration by
itself. Each packet needs task review; integration review is mandatory before the Lead validates
the next dependency. Customer reconstruction engines, CAD/BIM progress redesign, automatic media
transfer, and production autonomous execution remain separate workstreams.
