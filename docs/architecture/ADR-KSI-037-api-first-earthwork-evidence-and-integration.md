# ADR-KSI-037 — API-first earthwork evidence and integration

> 2026-09-30 scope amendment: [ADR-KSI-038](ADR-KSI-038-spatial-data-and-analysis-platform.md)
> expands the overall product to spatial-data delivery and analysis for external applications.
> D1/D2 below retain the first analysis pilot's actors and acceptance; they are no longer the
> whole-platform boundary. Calculation, authority, evidence and repeated-use requirements remain
> effective. This amendment adds no runtime capability or implementation authorization.

- Status: ACCEPTED — product direction and first-request requirements only
- Date: 2026-09-20
- Human approval provenance: 2026-09-20 refined product direction and implementation-condition
  amendment
- Requirements: preserves REQ-INT-101..104, REQ-SEC-101, REQ-OPS-102; detailed first-request
  requirements are in `docs/design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md`.
- Invariants: preserves INV-017/018/020/024/040/050/051/053/054/055/060/061. No invariant,
  schema, runtime behavior, policy activation, or deployment is changed.
- Supersession: refines first-product positioning and MVP priority in the Product Constitution,
  Final Decision Ledger, and Master PRD. ADR-KSI-036 remains the external-reconstruction input
  boundary; managed NodeODM, ProcessingJob, source-authority, Edge, and autonomous-roadmap
  records remain intact in their applicable scopes.

## Context

Construction and earthwork operators need a result that another system can verify and reuse, not
only a map image or a one-off report. A numerical claim must retain where and when it was observed,
which input versions and coordinate/vertical transformations were used, which calculation profile
ran, what data was excluded, and what the number means. Customer systems should not need bespoke
scripts for each weekly reuse.

The first-release ingestion direction already places reconstruction on customer-controlled
equipment and KSI receives derived artifacts (ADR-KSI-036). The existing external quantitative V1
path deliberately requires independently measured checkpoint evidence. Its existing runtime
policy/contract remains unchanged and its persisted history is immutable. This amendment
supersedes only ADR-KSI-037's earlier external-engine and strict-checkpoint **target** for the
first API-first product loop with a distinct, not-yet-implemented Core policy version. It does not
imply that DJI Terra provides a comparison API or quantitative engine.

## Decision

### D1 — Product identity and actors

KSI is a service that provides site observations and analysis results with source, time,
coordinates, and calculation conditions so external systems can verify and reuse them. Its product
core is a durable API record: Core owns site/area/epoch/version mapping, scoped observation input
admission, reproducible jobs/results/evidence, permissions, and result retrieval; the processing
worker performs deterministic measurement under that authority.

The initial buyer/user is construction and earthwork operations. Integration customers include
digital-construction and smart-construction software partners. KSI performs the initial setup, then
the same weekly request should be reusable without a bespoke customer script. Reuse means the
approved WorkArea, configuration, compatibility rule, and workflow template; it never reuses an
old epoch pair's `mappingRecordDigest`, pair authority, admitted inputs, or calculation result.
Each new epoch pair receives fresh input-bound admission, pair authority, and result records.
Previously validated per-artifact evidence, including a `t1` checkpoint record, may be referenced
only for the exact same artifact/digest while its policy conditions remain valid; it cannot be
reassigned to different `t2` bytes.

### D2 — First complete MVP

The first complete MVP is a weekly, per-WorkArea, two-epoch **observed-terrain volume-change
review**. It requires an exact baseline/current pair, one explicitly selected and verified
authenticated external agent/MCP integration, and its example reusable workflow. That workflow must
return the same Core-recorded calculation record or actionable missing-data/blocker record as the API
and UI. This is a single verified MVP integration, not a claim that every agent/MCP client is
currently supported. Completed calculation is distinct from human review and result issuance. It
does not state that geometric change, volume increase/decrease,
net volume, or a design delta proves approved work, progress, settlement, quality acceptance,
survey acceptance, or field acceptance.

Current-versus-design remaining cut/fill is a separate conditional successor. It needs actual
customer design data and a distinct contract for a provenance-bound extracted design surface and
boundary. It is not a first-MVP promise.

### D3 — Input, reconstruction, BIM, and accuracy boundaries

An external reconstruction engine may produce inputs. Customer-controlled DJI Terra on a field PC
remains the initial reconstruction reference workflow under ADR-KSI-036 D6, but is neither a KSI
provider integration nor proof of a Terra comparison API, export compatibility, or accuracy.
KSI does not develop proprietary photogrammetry, SLAM, or 3D reconstruction. A customer Terra
reconstruction profile and KSI's quantitative measurement execution profile are distinct facts.

Customer BIM originals remain in customer authoring/editing/management tools. KSI may later accept
or emit a surface/boundary only with original/version, CRS, units, vertical reference, and transform
provenance. Inbound and outbound customer computation are supported directions, not simultaneous
MVP implementation promises. KSI is not a BIM editor, general 3D/BIM viewer, or general chatbot.

KSI's first API-first measurement execution is its existing GIS measurement worker, under a
Core-selected fixed profile. Terra/Pix4D may reconstruct the submitted terrain artifacts, but are
not KSI's measurement engine. The selected worker is not metrological truth by itself.

The new policy version separates computability, accuracy evidence, and human review. If all
computability conditions pass and there is no independent checkpoint evaluation for one or both
exact DSM bytes, it may record a **provisional** operational volume with accuracy unverified and
`uncertaintyM3 = null`. A checkpoint attachment alone never changes that state. An evaluation must
bind its exact evidence bytes, DSM digest, policy, metrics, scope, and criterion outcome.

A failed evaluation or unresolved conflicting evaluation for either DSM has priority over absent
evidence: Core returns **remediation required** and does not publish a normal provisional number.
Missing vertical reference, units, a required transform, compatible CRS/readiness/lineage, or a
common valid area is **blocked** and returns no numeric result. These rules never treat a known
failure as merely "accuracy unknown". Independently measured checkpoints support positional
accuracy evidence; they do not automatically certify a volume, settlement, survey, quality, or
completion claim.

### D4 — One authoritative result record across API, MCP, and UI

The product API is the canonical integration surface. A thin Analysis facade resolves frozen
inputs and versions, creates and polls analysis requests, and translates stored results and
blockers into product language. It owns neither a second calculation engine nor a second
authorization/policy decision. Core owns authorization, policy selection, admission, durable
request/result/evaluation records, and workflow; the independently operated measurement worker
performs the fixed calculation. UI and MCP call the same create, poll, and retrieve path and never
recompute a number or decide accuracy. This ADR creates no implemented MCP server, public route,
client topology, webhook, or tool authorization.

The MVP includes one explicitly selected, verified authenticated external agent/MCP client and its
example adapter/workflow template. It must preserve tenant scope, idempotency, source/provenance
bindings, typed failures, evidence/restriction visibility, and the stable analysis-result ID. Other
client support topologies are not implied and are verified individually. Existing Copilot remains query/draft-only under
INV-061: an MCP analysis request is a separate future authenticated product API target and cannot
bypass Copilot's allowed-tool list or turn a read-only tool into write authority.

### D5 — First-request and result semantics

The first-request design fixes the required scope, input/run conditions, typed blockers, output,
and result lookup. The new target volume route admits a WorkArea and two supported DSM/terrain
artifacts; an orthophoto is optional spatial evidence, not the volume source.
At minimum it binds WorkArea and revision, ordered epoch versions, artifacts and
regions, producer provenance, one fixed quantitative execution backend/version/profile,
horizontal/vertical CRS and transforms, common valid/excluded bounds, and increase/decrease/net
meaning. It requires tenant permission, idempotency, stable result identity, reproducibility
bindings, polling, inspection/admission/quality status and limitations, and tenant-scoped retrievable
references to exact derived inputs, inspection/checkpoint validation, masks/exclusions, and supporting
evidence. Input digests alone are insufficient; raw photos are not required by this route. Webhooks
are a later extension.

The first fixed profile is a new, Core-selected **KSI-GIS-RELATIVE-VOLUME-V2** target. It freezes
the baseline DSM's observed north-up affine grid and native resolution as the run's target grid;
the current DSM elevation is bilinearly resampled to that grid and its validity mask is resampled
nearest-neighbour. It uses only cells valid in both DSMs; declared NoData and raster-masked samples
are unavailable rather than zero, while an unmasked non-finite sample is an input failure. The WorkArea is rasterized by cell centre
(`all_touched=false`); its full selected cell count is the coverage denominator. The profile
requires 100% common valid coverage for this first MVP, uses a zero-metre deadband
(`abs(delta) >= 0.0`), and integrates each signed elevation delta with the absolute affine
determinant cell area. It returns cut, fill, and net with their meanings.

The result separately records unavailable cells/area and cells computed but excluded by the
deadband. Under the zero deadband the latter is zero; unchanged zero-delta cells remain computed,
not excluded. The exact transforms, baseline-grid resolution, masks, bounds, profile/config and
algorithm digests are frozen into the run. The profile performs no automatic horizontal shift,
vertical bias removal, scaling, rotation, or other co-registration correction. A common grid is
not evidence that the two observations are spatially registered; the recorded transform/evidence
state states that limitation.

For every selected WorkArea cell, the normative elevation difference is `d = current - baseline`
in metres. `fillM3 = Σ(d × A)` for common-valid, deadband-counted `d > 0`; `cutM3 =
-Σ(d × A)` for corresponding `d < 0`; and `netM3 = fillM3 - cutM3`, where `A` is the absolute
affine-determinant cell area in m². The output records rasterized selected, common-valid,
unavailable (`selected - common-valid`), and threshold-excluded (`common-valid` with
`abs(d) < thresholdM`) cell counts and areas separately. At the V2 zero deadband, a zero-difference cell is
computed and neither cut nor fill; it is not threshold-excluded. `zoneAreaM2` is selected-cell
count × `A`, not continuous polygon geometry; any separately exposed geometric polygon area is
labelled a different value.

The V2 calculation payload does not derive a volume uncertainty from checkpoint RMSE. It records
`uncertaintyM3 = null`: with no evaluation it carries an accuracy-unverified limitation, and with
passed exact-byte evaluations it carries the evaluation identities and their stated criterion result.
Neither is a volume-accuracy certification. Each calculation identity additionally records the exact
worker executable/build, runtime image version and OCI digest, dependency-lock digest, and
algorithm/config/profile digests in launch and result provenance. A change to any of those
executable/runtime identities, as well as an input, WorkArea/version, transform, or mathematical
profile change, creates a new calculation identity. Checkpoint metrics remain separate evaluation evidence.
A future model-based uncertainty method requires its own approved profile and criterion, rather
than mutating the meaning of this result. V1 execution policy and its strict checkpoint gate remain
unchanged. This decision does not delete the existing raster arithmetic or authorize proprietary
reconstruction/SLAM.

Intake success, comparison compatibility, accuracy evidence, quantitative execution, human result
review, privileged official-baseline change, and result issuance are distinct states. The first
request creates only a Core-recorded calculation record: it records the selected KSI worker build
and profile provenance. A customer independently computed analysis result is a separate future
provenance-bound import route, outside this MVP. An agent proposal is not a calculation record.
Result-level review supports use and explanation; it is not an enterprise approval workflow.

Calculation results and checkpoint evaluations are immutable, separate records. Every response
binds the exact calculation result revision/digest and the evaluation revision(s) consulted at
that time. Adding a later evaluation creates a new evaluation revision, never rewrites the numeric
calculation. Recalculation occurs only when admitted input bytes, WorkArea/version, transforms,
worker executable/build, runtime image version/OCI digest, dependency-lock digest, or
algorithm/config/profile (including mathematical rules) change. A later failed or conflicting evaluation changes the current
suitability projection to remediation-required and suppresses ordinary numeric retrieval; the
earlier result and its original evaluation snapshot remain tenant-retrievable as historical,
properly labelled evidence.

Core evaluates this evidence state when admitting work and again before publishing a completed
result or serving the current ordinary result. Thus a failed/conflicting evaluation that arrives
while a request is queued or running cannot be collapsed into absent evidence at publication.
This requires additive, versioned request/result/evaluation contracts. The present
`ExternalRelativeVolumeRequestV1` permits one to 64 evidence digests; the existing
`MeasurementLaunchRequestV2` permits no supplied evidence records or exactly two ordered records
when they are supplied. The active Core relative-volume admission/authority path currently requires
one validated, independently attested record per epoch before its worker launch. These surfaces lack
evaluation revisions, a current suitability projection, and unavailable-versus-threshold-excluded
result semantics, so a facade cannot reinterpret them as the V2 provisional policy.
Only a privileged change to an official baseline and result issuance have explicit human gates;
ordinary permissioned requests may reuse an already approved fixed WorkArea/mapping/profile.

Missing-data requests name only the area, needed data, reason, and status. They do not invent
coordinates, numbers, or an approval. An LLM may orchestrate validated tools but may not estimate
numerical truth or replace the recorded computation.

### D6 — Acquisition and safety scope

KSI retains site observation and the approved Acquisition/Edge/autonomous roadmap, but automatic
robot or flight execution is outside this MVP.

> 2026-10-07 routing note (dated evidence above is preserved): the roadmap-retention
> clause is superseded as product responsibility by
> [ADR-KSI-039](ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md) —
> long-term acquisition is out-of-product. D1–D5 calculation, authority, evidence,
> and repeated-use requirements remain fully effective. This direction does not revoke Mission Contract,
Flight Controller, Manifold, or tactical-safety authority; it changes product priority and must not
be read as device support, execution authorization, or field acceptance.

### D7 — Egress and rollback

Egress controls apply to extracted surfaces, boundaries, and derived results as well as source
media. No client adapter, automation, or partner support is enabled merely by documenting it.

Rollback is documentation-only: remove this direction through a future approved authority change.
Do not delete or rewrite external submissions, managed results, journals, profiles, source bundles,
work areas, or historical evidence.

## Consequences and evidence limits

The active product documents must present the API-first evidence service and the weekly two-epoch
earthwork loop as the MVP, while retaining managed processing and autonomy as scoped historical or
future work. The current `EXT-VAL` product-state slice remains unchanged; promotion of this
strategic goal into current state or next-work inventory occurs only at an authorized slice close.

This ADR has no sample two-epoch run, subsequent-epoch reuse, customer-system calculation,
UI/API/MCP identity proof, engine/vendor compatibility, client-topology verification, deployment,
HIL, or field-acceptance evidence. Those are future acceptance work, not facts created by this
decision.
