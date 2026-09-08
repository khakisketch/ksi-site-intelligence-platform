# ADR-KSI-035 — Terrain-aware observation planning and Pilot execution

- Status: ACCEPTED — design decision only
- Date: 2026-09-06
- Human approval provenance: 2026-09-06 approved decision record and
  `docs/superpowers/plans/2026-09-06-terrain-aware-planning-design-baseline.md`
- Requirements: REQ-MSN-101/104, REQ-ACQ-101, REQ-UX-101, REQ-INT-102/103
- Invariants: preserves INV-001/002, INV-011/012, INV-020/024, INV-051/053/060;
  scopes the future application of INV-016 and the claim boundaries of INV-017/018.
- Runtime status: existing fixed-altitude planning is partially present; this decision's
  terrain-aware planning, profile records, and postflight interfaces are NOT_IMPLEMENTED.
- Physical acceptance: NOT_VERIFIED. No Pilot 2 import/edit/export, aircraft, RC, firmware,
  execution, log, or capture evidence is asserted here.

## Context

KSI already has deterministic AOI/camera/coverage/WPML planning and a Core-generated
candidate artifact. It does not yet wire terrain or known-structure inputs into that path,
does not have the additive records defined below, and has no physical proof that a particular
artifact is accepted or flown by Pilot 2/M4D. Treating an own DSM, BIM, site survey, or prior
visit as the prerequisite for a first mapping flight would make first-site observation circular.

The Human-approved product default is therefore a deterministic KSI plan that a Pilot imports,
reviews, may exceptionally edit, and personally approves for flight. This is a planning and
evidence decision, not a grant of device authority or a statement that an edited file is safe.

## Decision

### D1 — Default Pilot observation profile

For initial mapping, repeat observation, and bounded partial reobservation, the intended default
flow is:

```text
Site/AOI + observation requirement + available evidence
  -> deterministic KSI server planner -> validation -> DJI-compatible draft artifact
  -> operator download -> Pilot 2 import -> pilot review / exception edit
  -> pilot final approval -> flight -> postflight evidence -> claim-scoped assessment
```

Pilot-native scratch planning is permitted but is not the product default. KSI owns the
deterministic **how to observe** proposal (coverage geometry, capture intent, terrain/known-
structure-aware candidate path and transit intent); it does not own live aircraft control,
reactive avoidance, emergency RTH, takeoff authorization, or a pilot's final execution decision.
The DJI Flight Controller, Pilot, and local Edge boundaries in INV-001/011/012 remain unchanged.

The profile labels `PILOT_MANUAL_EXECUTION` and `AUTONOMOUS_EXECUTION` in this ADR are design
vocabulary, not implemented enums or API values. An implementation must keep their records,
validation rules, and activation paths separate. A manual exception must never be used to
downgrade the signed/digest/device/activation requirements for future autonomous execution.

### D2 — First-site and terrain evidence

The planner may use lawfully available public data and operator-provided facts for a first site.
KSI-owned DSM/point cloud, BIM, a prior survey, or an earlier visit is not required. Later
observations may improve subsequent plans. Every terrain, structure, takeoff, transit, return,
coordinate, vertical-reference, freshness, uncertainty, and provenance input must be recorded;
missing, stale, contradictory, or low-confidence input is explicit. It is never silently treated
as zero elevation, a clear obstacle map, legal approval, collision-free proof, or a safety margin.

The target plan covers terrain-aware orthomapping and known structures across takeoff-to-site,
transit, survey, normal return, initial/repeat/partial AOIs, and irregular boundaries. Oblique or
close inspection, reactive obstacle control, and replacing DJI emergency RTH are excluded.
No numeric safety, quality, supplier, or optimization threshold is selected by this ADR.

### D3 — Distinct immutable evidence facts

KSI must preserve the following as separate facts, linked by IDs, exact bytes where available,
SHA-256 digest, provenance, timestamps, actor/receipt kind, organization/site scope, and version:

1. KSI planning input snapshot and KSI planned artifact;
2. pilot final-plan declaration or exported artifact, if supplied;
3. actual device flight log/trajectory receipt, if supplied and verified; and
4. actual capture/media facts, if registered and integrity-checked.

An unknown modification is `UNKNOWN`, not `false`; a pilot declaration is not a device receipt;
an exported final plan is not an actual trajectory; and a final-plan artifact does not establish
capture completeness. Postflight assessment observes evidence and cannot retroactively authorize
the flight.

### D4 — Scoped artifact and readiness authority

For a future KSI-authorized or autonomous execution profile, changed executable bytes/semantics
require the INV-016 validator, new revision/digest, binding, signature, and applicable device
activation proof before dispatch. This strict path is not weakened.

For `PILOT_MANUAL_EXECUTION`, a pilot may edit and execute without returning the edited artifact
to KSI before flight. KSI must not label that unreturned edit as the prior signed artifact or
claim it was KSI-authorized. If it is later supplied, its state remains declared/observed/unknown
until the applicable future validation is performed. This is the only scope change to the former
universal preflight-rebind reading of INV-016.

The existing INV-017/018 enforcement remains the current global fail-closed `AnalysisReadiness`
projection and is not changed by this ADR. A future additive `ClaimScopedAssessment` must gate only
the claim that depends on missing final-plan/log/capture evidence; it must not turn that evidence
gap into a global observation-acceptance veto. Raw registration or reconstruction may then proceed
when their own ingress/processing prerequisites hold, while quantitative comparison still requires
its independent integrity, CRS, vertical reference, processing profile, lineage, and quality
evidence under INV-020/024/051/053.

### D5 — Current implementation boundary and successor authority

Existing terrain functions and fixed-altitude artifact generation are reference assets only for
the successor work; no claim is made that they compose a terrain-aware plan. The implementation
gap matrix, document interfaces, candidate-source selection record, acceptance evidence and
successor packets are in:

- [planning design contract](../design/TERRAIN_AWARE_OBSERVATION_PLANNING_CONTRACT.md);
- [Pilot MVP acceptance](../acceptance/TERRAIN_AWARE_PILOT_MVP_ACCEPTANCE.md); and
- [successor roadmap](../goals/TERRAIN_AWARE_PLANNING_ROADMAP.md).

Public primary-source research is candidate evidence only. Dataset/supplier licensing, coverage
or safety thresholds, and planning optimization objectives require their own evidence-backed
closure record before a runtime worker selects or implements them.

## Scoped amendments to active records

- ADR-KSI-019's optional-refinement and first-site anti-circularity rule remains; its old
  "FIELD-0 before new feature" sequencing does not forbid this approved design baseline or the
  separately gated successor packets.
- ADR-KSI-022/023/027's historical zero-touch/manual-recovery framing is scoped: the approved
  Pilot download/import/edit profile is a normal planning path, while automatic originals and
  capability routes remain separately `NOT_VERIFIED`/OFF.
- ADR-KSI-028's candidate compiler and rebind rules remain for KSI-authorized final artifacts;
  D4 is scoped by D4 above for a pilot-only final decision not returned preflight.
- ADR-KSI-029's current readiness projection remains global fail-closed. A future additive
  claim-scoped assessment will gate only dependent claims and is not a blanket veto of
  independently admissible raw registration or reconstruction.

## Consequences and rollback

This ADR does not change a runtime API, schema, OpenAPI behavior, hardware route, field status,
customer reconstruction engine, CAD/BIM workflow, or automatic-media design. Successor work is
additive and must use separate worktrees and review gates. Rollback is withdrawal of the future
profile/feature flags and preservation of original evidence records; no existing contract or raw
evidence is rewritten or deleted.
