# ADR-KSI-039 — Physical Site Intelligence and acquisition separation

- Status: ACCEPTED — product responsibility boundary and current-vs-history routing
- Date: 2026-10-07
- Human approval: physical-site rebaseline foundation plan
  (`docs/superpowers/plans/2026-10-07-physical-site-rebaseline-foundation.md`),
  sequential task execution at `738b4a9`
- Implements: approved rebaseline spec
  (`docs/superpowers/specs/2026-10-07-physical-site-platform-rebaseline-design.md`)
  §2 responsibility boundary and §7 authority reconciliation (RB-01)
- Consumes (preserved, not rewritten): ADR-KSI-036 customer originals/identity,
  ADR-KSI-037 quantitative/calculation/authority semantics, ADR-KSI-038
  spatial-data direction and staged scope

## Context

KSI Site Intelligence converts fragmented observations of physical spaces into
evidence-bound Site State and Change that people, AI agents, software, and
robotics can reuse. Construction and earthwork are the first market, not the
platform's exclusive identity. Earlier authority kept a long-term Autonomous
Acquisition axis (flight, tactical perception/control, customer production
reconstruction) beside the platform core. That coupling lets readers mistake
historical acquisition evidence and future-compatible diagrams for current
product responsibility. This ADR draws the long-term boundary and routes
current documents to it without rewriting dated evidence.

## Decision

Flight, autonomous acquisition, tactical perception/control, and customer
production reconstruction are **outside long-term Site Intelligence
responsibility** — not postponed MVP work. Preserving their historical
contracts does not retain an active product roadmap or authorize their
execution. KSI Safety is not automatically assigned the removed capabilities;
no other product is modified.

## Current responsibility

| Owner | Responsibility |
| --- | --- |
| External collectors and producers | Capture, survey, sensing, reconstruction, export, and originals |
| KSI Core | Scoped identity, Site/WorkArea, observation/asset versions, permissions, admission, durable jobs, results, and evidence |
| KSI processing workers | Supported inspection, data preparation, and deterministic analysis under Core authority |
| API/MCP/SDK and Console | Access the same authoritative records; no independent computation or permission decisions |
| External consumers | Explanation, customer-specific analysis, and business integration |
| People and external execution systems | Official decisions, real-world operations, and equipment safety |

External collection is an input source, **not a platform runtime dependency**:
the platform never requires, operates, or guarantees any collector, aircraft,
reconstruction engine, or device link. Registration, file identity, supported
computability, accuracy evaluation, human review, and official issuance remain
separate states; missing facts are not inferred and eligibility is use-specific.

## Transitional implementation

Acquisition, Edge, flight-planning, and managed-reconstruction sources in the
repository are **retained transitional implementation** until a verified
successor move relocates them with full consumer, contract, replay, build, CI,
deployment, and rollback evidence. Diagrams and runtime tables that show
equipment topology describe that transitional implementation, not long-term
product ownership. No path moves, no contract/schema change, and no behavior
change follow from this ADR.

## Supersession scope

This ADR supersedes **product-responsibility routing only** — never past facts,
evidence meaning, or invariant IDs:

- Product Constitution §장기 관측·취득 축, acquisition profile, and Mission
  type passages: the Autonomous Acquisition axis is historical/transitional
  scope, not a current product axis.
- Final Decision Ledger acquisition-roadmap lines (DEC-005 long-term axis,
  DEC-007–026 acquisition/Mission/Edge applicability): preserved historical
  decisions with out-of-product long-term applicability.
- MASTER_PRD (MASTER PRD) DEC-005, DEC-007–026 applicability notes, and acquisition
  equipment/roadmap passages (§1.1, §1.2B): current platform responsibility
  replaces long-term flight roadmap/defaults; historical records stay under
  explicit historical headings.
- ADR-KSI-037 D6 "retains the approved Acquisition/Edge/autonomous roadmap"
  clause: superseded as product responsibility; D1–D5 calculation, authority,
  evidence, and repeated-use requirements remain fully effective.
- ADR-KSI-038 D6 "long-term Acquisition/Edge design and past implementation
  evidence are preserved" clause: preserved as historical evidence only, not
  as an automatic-execution precondition of platform validation.

Older ADRs keep their dated evidence and are annotated through this index and
routing pointers; their text is not rewritten. ADR-KSI-036 customer originals
and identity bindings, and ADR-KSI-037 quantitative semantics (strict V1,
provisional V2 evaluation rules, numerical meanings) are unchanged.

## Invariant applicability

INV-020, INV-024, INV-040, INV-050, INV-051, INV-053, INV-054, INV-055, INV-060, INV-061 stay effective in their applicable
platform, external-ingress, and analysis domains. Device, Mission Contract,
flight-envelope, coverage, and tactical-safety invariants keep their explicit
historical/managed scope: removal from current responsibility is not permission
to weaken them, and no software check promotes `NOT_VERIFIED` device behavior.

## Consequences and evidence limits

Active authority (Constitution, Decision Ledger, PRD, routing documents,
product-state, capability index, roadmap) links this boundary; historical
milestone rows and exact EXT-VAL acceptance are unchanged. Excluded future
work is marked out-of-product, never completed; unfinished customer,
operational, and field gates stay open. This ADR creates no endpoint, schema,
format/vendor support, reprojection, robot-safety claim, archive move, or
product-state transition.
