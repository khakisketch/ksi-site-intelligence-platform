# API-first earthwork first-request contract

> Status: approved product design; subordinate to ADR-KSI-037 and ADR-KSI-036. This is a target
> requirement, not an implemented wire schema, public API, MCP server, vendor adapter, or customer
> integration claim.

> Scope since 2026-09-30: this is the first **analysis use case** under
> [ADR-KSI-038](../architecture/ADR-KSI-038-spatial-data-and-analysis-platform.md).
> The platform's separate spatial-data access path needs its own detailed contract; it does not
> inherit earthwork accuracy prerequisites or coverage Range limits by default. The calculation
> and acceptance requirements below remain unchanged.

## Purpose

Define the smallest reusable weekly request for a per-WorkArea, two-epoch observed-terrain
volume-change review. The request produces one reproducible Core-recorded calculation record when its
admitted inputs and gates pass, or returns actionable missing-data/blocker information. The MVP
includes one explicitly selected and verified authenticated external agent/MCP client plus its example
reusable workflow; it returns this same record or blocker as UI/API, without claiming universal
client support. It does not calculate progress, settlement, quality, survey acceptance, or field
acceptance.

## Request identity and authority

| Concern | Required target behavior |
|---|---|
| Caller | Authenticated tenant principal with the required Site/WorkArea permission. An MCP caller is a future product-API principal, never an implicit Copilot authority. |
| Idempotency | Client supplies one idempotency identity. Same scoped payload returns the same request/result; a changed payload is a typed conflict. |
| Authoritative calculation record | Core creates or resolves the authoritative Core-recorded request/result record. The Analysis facade only resolves versions and exposes create/poll/retrieve operations; it does not decide admission, accuracy, or calculation. UI, API, and the selected verified external agent/MCP workflow use the same stable result ID and revision. A completed calculation is not thereby reviewed or human-issued. |
| Producer and route | The first request is Core-recorded/admitted execution by the KSI GIS measurement worker and the exact Core-selected `KSI-GIS-RELATIVE-VOLUME-V2` profile. Terra/Pix4D reconstruct submitted artifacts only. A customer independently computed analysis result is a separate future provenance-bound import route, outside this contract; an agent proposal is not a calculation record. |
| Privileged changes and issuance | A human gates an official-baseline change and result issuance. An ordinary permissioned request may reuse an already approved fixed WorkArea/mapping/profile without a new human gate. A result review is not enterprise approval. |

## Required request scope and frozen run conditions

| Field group | Required condition |
|---|---|
| Site and area | Site ID, WorkArea ID, immutable WorkArea revision and polygon/boundary digest. |
| Epoch pair | Ordered baseline/current Observation Epoch identities and capture intervals; baseline precedes current and intervals do not overlap. |
| Input artifacts | The V2 target volume route: one supported DSM/terrain artifact for each epoch plus the WorkArea. Exact artifact/region IDs and observed byte digests are required; producer identity/version/provenance declarations remain separate from measured facts. An orthophoto may be spatial evidence but is not the volume source. Raw photos are not required. The final Terra sample/profile has not been validated. |
| Quantitative profile | Exact worker executable/build, runtime image version/OCI digest, dependency-lock digest, algorithm/config/profile digests, and `KSI-GIS-RELATIVE-VOLUME-V2` are frozen in launch and result provenance. The target grid is the baseline DSM's observed north-up affine grid/native resolution; current elevations use bilinear resampling and their valid mask uses nearest-neighbour resampling. WorkArea inclusion is cell-centre (`all_touched=false`); declared NoData/raster-mask values are unavailable, while unmasked non-finite values fail input validation; full-zone common valid coverage is 100%; deadband is `0.0 m`; cell area is the absolute affine determinant. The profile applies no automatic shift, bias, scale, rotation, or co-registration. The caller never supplies these knobs. |
| Coordinates | Observed horizontal CRS, vertical reference, units, and each coordinate/vertical transform version/digest. |
| Comparable area | Exact common valid bounds and excluded bounds/masks for both epochs; output never implies a value outside their admitted common area. |
| Accuracy evidence | A checkpoint evaluation is bound to exact evidence/DSM bytes, its policy, metrics, scope, and criterion outcome. With all computability conditions valid, absent independent checkpoint evaluation produces a provisional operational number with `uncertaintyM3 = null`; it never asserts absolute accuracy. Passed evaluations are returned as exact evaluation evidence but do not certify volume accuracy. A failed evaluation or unresolved conflict for either DSM is remediation-required and suppresses ordinary numeric publication. V1's strict checkpoint policy remains unchanged. |
| Policy and limits | Exact active policy/compatibility/mapping/execution authority identities and finite resource limits; callers cannot override them. |
| Weekly reuse | Reuse only the approved WorkArea, configuration, compatibility rule, and workflow template. A new epoch pair gets fresh input-bound admission, pair authority, and result records; it never reuses an earlier pair's `mappingRecordDigest`, pair authority, admitted inputs, or result. Previously validated per-artifact evidence, including a `t1` checkpoint record, may be referenced only for the exact same artifact/digest while policy conditions remain valid; it cannot be reassigned to different `t2` bytes. |

For a common-valid, deadband-counted cell, `d = current - baseline` in metres and `A` is the
absolute affine-determinant cell area in m². `fillM3 = Σ(d × A)` where `d > 0`; `cutM3 = -Σ(d × A)`
where `d < 0`; `netM3 = fillM3 - cutM3`. The result carries separate rasterized counts and areas for
selected WorkArea cells, common-valid cells, unavailable selected cells, and threshold-excluded
common-valid cells. At the zero V2 deadband, zero-difference cells are computed (but add to neither
cut nor fill) and threshold-excluded cells are zero. `zoneAreaM2` is selected-cell count × `A`; it
is distinct from any optional continuous geometric polygon area.

## Outcomes, blockers, and retrieval

| Outcome | Required content |
|---|---|
| Provisional recorded analysis result | Stable result ID/revision/digest; ordered epoch and area bindings; normative cut, fill, and net volume in cubic metres (m³); `PROVISIONAL_ACCURACY_UNVERIFIED`; `uncertaintyM3 = null`; inspection/admission/quality statuses and limitations; selected/common-valid/unavailable/threshold-excluded rasterized counts, bounds and areas; profile/CRS/transform/provenance/policy/evaluation plus executable/runtime/lock identity bindings; calculation timestamp and reproducibility references. It provides tenant-scoped retrievable references to exact derived inputs, inspection/checkpoint validation, masks/exclusions, and supporting evidence; digests alone are insufficient. Unavailable area is not reported as zero. Completion is distinct from review and issuance. |
| Evaluated recorded analysis result | The same immutable calculation content, with exact passed evaluation revision(s), metrics/scope/criterion outcome, and `uncertaintyM3 = null`. It remains an operational result, never a volume-accuracy certificate, settlement, survey, quality, progress, or completion decision. |
| Remediation required | Stable request ID; failed or conflicting evaluation identity/reason and required remediation; no normal numeric result. A prior calculation remains retrievable only as a historical result with its original evaluation snapshot, never silently replaced. |
| Missing-data request | Area, requested data, reason, and status only. No invented coordinate, quantity, confidence, approval, or remediation claim. |
| Typed blocker | Machine-readable reason for permission, scope, idempotency, input seal, profile, CRS/vertical/transform, capture ordering, common area, evidence, compatibility, policy, resource, or transient availability failure. |
| Retrieval | Poll the authoritative request/result record first. Webhooks are a later contract and are not implied by polling. |

Core re-evaluates evidence applicability at admission and immediately before normal result
publication/current retrieval. A terminal failed or conflicting evaluation for either artifact is
never dropped from that evaluation set merely because a matching checkpoint is absent. The existing
`ExternalRelativeVolumeRequestV1` permits one to 64 evidence digests. The existing
`MeasurementLaunchRequestV2` permits no supplied evidence records or exactly two ordered records
when supplied, while active Core relative-volume policy/admission requires validated independently
attested evidence for both epochs. V2 needs additive versioned contracts and replay coverage because
those existing surfaces lack evaluation revisions, suitability projection, and unavailable-versus-
threshold-excluded result semantics; a facade-side boolean or compatibility shim is insufficient.

## UI, API, and MCP parity

The minimum UI shows intake, provenance/evidence, frozen conditions, inspection/admission/quality
statuses and limitations, errors/permissions, and the same recorded analysis result served to external
API callers. Its map is limited evidence: source/derived overlay access plus WorkArea, common-valid,
unavailable, and threshold-excluded boundaries; it is not a generic GIS/BIM editor. The selected
verified external agent/MCP workflow invokes an authenticated product API to create, poll, and
retrieve the same record, evidence references, and restrictions. It may not recompute, silently
select an engine, infer a number, or write a review, privileged baseline change, or issuance. An LLM
can coordinate validated reads and requests but cannot estimate numerical truth.

## Acceptance boundary

The intended acceptance requires an actual customer sample in one area with an initial `t0→t1` pair
that successfully records a provisional numeric result and a subsequent `t1→t2` observation reusing
the existing WorkArea/mapping/template that does the same. It requires the positive provisional
case with no checkpoint evaluation, a passed-evaluation case, and negative cases for missing
essential coordinate/vertical/unit/common-area conditions, a failed
checkpoint evaluation, and conflicting evaluations; it also proves that a later evaluation changes
current suitability without rewriting the historical result/evaluation snapshot. UI, API, map, and
the selected verified Codex MCP workflow must resolve the same result/blocker record, evidence
references, restrictions, and IDs; numbers must be reproducible; and the recorded
setup/preparation baseline can be compared with repeated effort. This is a target acceptance matrix:
the existing schemas do not yet express V2 suitability/evaluation revisions or unavailable-versus-
threshold-excluded geometry, so contract work is required before implementation. Customer-approved
reference data and thresholds are required before any quantitative-accuracy acceptance. This document
does not establish any of those facts. It also establishes no Terra API/export support, client
topology, field accuracy, survey/settlement use, deployment, or automatic flight/robot execution.
