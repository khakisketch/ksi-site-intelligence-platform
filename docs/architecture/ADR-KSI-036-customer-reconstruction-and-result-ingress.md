# ADR-KSI-036 — Customer reconstruction and result ingress

- Status: ACCEPTED — product direction only
- Date: 2026-09-06
- Human approval provenance: 2026-09-06 explicit first-release decision
- Requirements: REQ-INT-101/102/103/104, REQ-SEC-101, REQ-OPS-102
- Invariants: preserves INV-051, INV-053, and INV-060; no invariant or schema is changed.
- Runtime status: the bounded Core registration and byte-seal API has local software evidence in
  the [verification audit](../audit/EXTERNAL_RECONSTRUCTION_INGRESS_API_VERIFICATION.md). This ADR
  remains product direction, not a vendor/export compatibility decision, deployment, or release.
  Public revision addressing uses server-issued opaque `submissionRef`; it does not repurpose the
  customer declaration ID as a URL segment or change raw journal/object-key identity.

## Context

ADR-KSI-030 selected an immutable KSI-managed NodeODM profile for the then-defined managed
civil-processing path. That profile and its completed results remain historically meaningful;
they must not be relabeled, rewritten, or used to imply a customer-operated engine.

For the first release, customers normally run reconstruction software on equipment they own or
control. KSI's product role is to register, verify, and analyze exported artifacts. KSI-server
reconstruction is retained only for testing and demonstration. This direction does not select a
vendor, promise provider compatibility, approve a license, or establish an external software
guarantee.

## Decision

### D1 — First-release responsibility boundary

The default responsibility split is:

```text
Customer: select/license/run reconstruction software and export results
KSI: register submitted facts -> verify evidence/provenance -> analyze only eligible results
KSI-managed NodeODM: test/demonstration scope, not the first-release default
```

Registration records what was supplied. Verification determines whether supplied facts and their
evidence are credible for a stated use. Quantitative eligibility is a later, stricter decision.
These states are distinct; a registered export is neither verified nor quantitatively eligible by
default. KSI does not represent an unverified artifact as a KSI reconstruction result.

### D2 — Authority, provenance, and immutable historical records

An external import must not forge a successful `ProcessingJob`, sealed raw bundle,
source-authority point cloud, source-media authority, or an existing KSI-managed profile identity.
It is a separately identified externally produced result with its asserted and verified facts kept
distinct. A customer export cannot inherit a KSI profile digest, engine identity, or lineage merely
because its filenames or product labels resemble one.

Existing managed NodeODM profile snapshots, their `ProcessingJob` records, source bundles, and
results remain immutable. ADR-KSI-030 continues to describe that managed/test scope; this ADR
controls the new first-release product direction without rewriting prior history.

### D3 — Fail-closed claim boundaries

Unknown or unverified provenance, CRS, vertical reference, processing quality, source lineage, or
compatibility restricts every dependent claim. KSI must expose the gap rather than infer values,
equivalence, coverage, accuracy, or suitability. INV-051 still prevents derivative artifacts from
becoming source authority. INV-053 still blocks time-series, earthwork, stockpile, or design
comparison unless all required evidence is known and compatible. INV-060 still scopes all imported
facts and evidence to the authenticated organization and prevents cross-organization disclosure.

This ADR creates no blanket BIM prerequisite. It also authorizes no unsupported progress percentage,
contract-settlement quantity, survey-grade, absolute-accuracy, or RMSE claim. Processing success,
an export label, or registration alone establishes none of those claims.

### D4 — Customer-owned originals and first-release outputs

The subsequent Human decision on 2026-09-06 confirms that original photos stay on customer
equipment. Normal first-release result registration must not require uploading every original.
KSI retains submitted derived outputs and bounded provenance/quality metadata. Original backup,
availability for customer-side reprocessing and any separately authorized evidence transfer must
be explicit operational responsibilities, not an implied KSI backup service.

An ortho-only package can be registered for later validation and viewing. DSM supports eligible
height/relative-volume uses; point cloud and DTM are function-dependent additions; mesh is optional
visualization. Missing DSM does not prevent registering an ortho. Neither raw-upload absence nor
missing evidence for one claim may permanently block unrelated uses. A local manifest or checksum
does not prove raw-byte possession, input completeness or reconstruction accuracy.

The approved implementation is tracked in the
[release plan](../superpowers/plans/2026-09-06-external-reconstruction-release.md). Its first
slice separates producer declarations from server-observed derived bytes. Registration and byte
identity do not grant comparison eligibility. Subsequent validation must define versioned external
evidence/compatibility policy rather than impersonate a managed profile or remove its safeguards.
The local Core API evidence is recorded separately in the
[verification audit](../audit/EXTERNAL_RECONSTRUCTION_INGRESS_API_VERIFICATION.md); it does not
decide this ADR's remaining product, compatibility, deployment, or acceptance work.

### D5 — Remaining detailed specifications

The following are intentionally not decided here and require a future detailed specification with
contracts, validation, compatibility policy, security review, tests, and acceptance evidence:

- accepted file formats and actual producer export compatibility;
- semantic validation and provenance/trust verification evidence beyond byte identity;
- engine/version/profile compatibility and quantitative-comparison policy.

Until then, no runtime path may treat an external result as eligible by default or backfill absent
facts. This ADR does not change schemas, ProcessingJob state transitions, sealed-bundle semantics,
Analysis Readiness, or any invariant enforcement.

## Consequences and rollback

Future implementation is additive and must preserve the managed and external identities, with
typed restrictions for unknown evidence. It requires a separate approved detailed specification;
no vendor integration, license decision, server deployment, or data-transfer assumption is approved
by this ADR. Rollback withdraws this future direction and any future feature flags without rewriting
registered evidence, managed profiles, sealed bundles, or historical results.
