# Terrain-aware Pilot MVP acceptance

Status: planned acceptance procedure; all rows below are `NOT_RUN` or `NOT_VERIFIED` unless a
future evidence package names an executed result. Authority: [ADR-KSI-035](../architecture/ADR-KSI-035-terrain-aware-planning-and-pilot-execution.md) and the [design contract](../design/TERRAIN_AWARE_OBSERVATION_PLANNING_CONTRACT.md).

## Evidence rules

- Deterministic replay proves only the recorded software behavior.
- Pilot declaration, exported plan, device log, actual trajectory, and actual capture are separate
  evidence kinds. Unknown modification is not a negative finding.
- No result proves legal approval, collision-free operation, exact M4D/Pilot compatibility, or
  superiority to Pilot 2 without the corresponding evidence.
- No numeric safety or quality acceptance threshold is invented here. A threshold-bearing test is
  blocked until the evidence-backed closure record named in the design contract is accepted.

| ID | Requirement / invariant | Procedure and expected evidence | Current status | Maximum conclusion |
|---|---|---|---|---|
| TAP-01 | REQ-MSN-101, INV-002 | replay deterministic planning input to structured draft; verify LLM data cannot enter coordinates/approval | NOT_RUN | deterministic draft behavior only |
| TAP-02 | ADR-035 D2 | first-site fixture with no own DSM/BIM/site survey; retain lawful input provenance and explicit unknowns | NOT_RUN | no circular own-model prerequisite in tested planner |
| TAP-03 | INV-020 | terrain/known-structure fixture with irregular AOI, takeoff-to-site, transit and normal-return candidate segments; check CRS/vertical/freshness/uncertainty propagation | NOT_RUN | candidate-path semantics only |
| TAP-04 | ADR-035 D2 | missing, stale and contradictory terrain/structure cases return typed gaps, never zero elevation or safety success | NOT_RUN | degraded-evidence handling only |
| TAP-05 | REQ-MSN-104 | replay GSD/capture/coverage calculations; distinguish planned estimate from actual CoverageReport | NOT_RUN | planned-quality result only |
| TAP-06 | ADR-035 D1/D3 | record unchanged, edited and unknown-modification flows separately from an aborted flight outcome; no preflight return required for the manual profile | NOT_RUN | evidence relationship only; no Pilot-device proof |
| TAP-07 | ADR-035 D3 | missing final plan and missing device log retain raw registration/reconstruction eligibility where independent prerequisites hold, while suppressing dependent claims | NOT_RUN | claim-scoped gating only |
| TAP-08 | INV-017/018/051/053 | test independent quantitative eligibility blockers for integrity, CRS, vertical, profile, lineage, temporal and quality gaps | NOT_RUN | no quantitative claim without listed evidence |
| TAP-09 | INV-060 | cross-organization/site attempts for every eventual planning/evidence record return indistinguishable not-found behavior | NOT_RUN | isolation in tested implementation only |
| TAP-10 | INV-011/012/016 | autonomous-profile regression: manual exception cannot bypass signed artifact, digest, device or activation gates | NOT_RUN | future autonomous contract safety only |
| TAP-11 | REQ-ACQ-101/103 | approved propeller-off Pilot import/edit/export and original/log evidence procedure, using [FIELD-0a](../hil/FIELD_0A_CHECKLIST.md) where applicable | NOT_VERIFIED | import/export evidence only, never flight or capability activation |
| TAP-12 | REQ-UX-101 | Console shows original plan, declared/unknown final plan, actual evidence and claim gaps without presenting a file path as execution fact | NOT_RUN | UX projection only |

## Acceptance ladder

1. Contract/replay rows TAP-01 through TAP-10 require immutable fixtures and versioned expected
   reason codes; their tests must not contact devices or assert field support.
2. TAP-11 requires a separately approved, propeller-off physical session and owner-private raw
   evidence. A successful import/export does not establish trajectory, capture, HIL route, or
   flight acceptance.
3. Any flight, actual log/capture, Pilot compatibility, or operational safety statement requires
   separately authorized HIL/field procedure and evidence. It remains `NOT_VERIFIED` at this
   baseline.
4. Quantitative reporting additionally requires the independently evaluated eligibility path; a
   successful raw ingest/reconstruction is not an accuracy or settlement claim.
