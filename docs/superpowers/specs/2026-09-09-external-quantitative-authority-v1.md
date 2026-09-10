# External quantitative authority v1

Status: Human-approved first-release direction on 2026-09-09; implemented
locally and awaiting correction-round independent review.

## Purpose and authority

This specification closes ADR-KSI-036 D5 only for the first-release external
relative-volume path. It implements REQ-INT-101 through REQ-INT-104,
REQ-SEC-101 and REQ-OPS-102 while preserving INV-017, INV-018, INV-020,
INV-024, INV-040, INV-051, INV-053 and INV-060.

An external result remains external derived evidence. It never receives a
managed ProcessingJob, source-bundle authority, or `ksi-odm-civil-v1` identity.
This specification permits an INV-053 analogue only for one exact immutable
external evidence profile and one exact ordered pair. It makes no survey-grade,
settlement, absolute-accuracy, producer-wide, vendor-wide, or field claim.

## First-release compatibility rule

The automatic compatibility rule is deliberately narrow:

- both DSM subjects have complete `MEASURED` inspection outcomes produced by
  the same immutable `external-geotiff-profile.v1` grammar digest and the exact
  parser/inspector build admitted by the active validation policy;
- both subjects carry the same non-null observed horizontal CRS digest and the
  same non-null observed vertical-reference digest;
- capture intervals are present, UTC, ordered, non-overlapping, and baseline
  precedes current;
- both subjects have independently measured, Core-validated checkpoint
  evidence bound to their exact DSM bytes; user-entered RMSE is never accepted;
- the selected WorkArea revision, polygon digest, CRS digest, and analysis
  vertical-reference digest exactly match the authority record;
- every numeric resource limit and quantitative threshold comes from the
  already admitted, digest-bound validation and execution policies. This
  specification supplies no implicit default and no client override;
- the policy pre-authorizes a stable `compatibilityRuleDigest` from a
  `CompatibilityRuleDescriptorV1`. The descriptor declares only the invariant
  predicates: one exact external profile/parser build for both subjects, equal
  observed CRS and vertical references, independently measured checkpoints for
  each epoch, ordered non-overlapping capture intervals, and exact WorkArea
  matching. It is constructible before any inspection, evidence, subject,
  organization, site, observed value, capture timestamp, or WorkArea revision
  exists. It contains no result-specific values, evidence digest,
  validation-policy digest, execution-policy digest, actor, authority record,
  decision, or self-reference;
- the resulting `mappingRecordDigest` is the canonical digest of the complete
  compatibility authority record. It binds the descriptor digest to the exact
  ordered subjects, organization/site scope, observed profile/parser/CRS/
  vertical values, capture intervals, independent evidence records, WorkArea
  snapshot, and admitted validation-policy digest. Decisions, execution and
  historical use bind this complete record digest only. Equal profile labels or
  filenames are irrelevant.

Cross-profile, cross-parser-build, cross-CRS, cross-vertical-reference, missing
checkpoint, overlapping/unknown capture-time, or absent-policy comparisons are
blocked. A future benchmark-backed cross-profile mapping requires a new
Product Authority decision and a new immutable record; it is not supported by
v1.

## Two-stage durable authority lifecycle

Core owns two append-only records because a use-decision identity does not
exist until after compatibility is resolved.

Stage one is a compatibility authorization. Policy admission is of the stable
rule descriptor, before inspection/evidence exists. A later mapping binds one
organization and site, ordered baseline/current subjects, exact WorkArea
snapshot, observed profile/parser/CRS/vertical values, sealed capture
intervals, independently measured evidence records, validation policy, validity
interval, the independently computable descriptor digest, and canonical full
mapping-record digest. The validation policy's `compatibilityMappingDigests`
contains the rule digest; it never contains a result-specific or full record
digest that depends on the policy. It contains no `decisionId`,
`decisionDigest`, actor permission, execution threshold or resource limit.
`ExternalUseEvaluator.request_pair()` resolves only a complete mapping and then
creates the immutable use decision through its existing idempotent flow.

Stage two is an execution authorization snapshot. After the decision exists and
before a volume request is issued, the runtime provider independently reloads
the decision and active compatibility record, validates their exact binding,
then appends one snapshot containing that decision ID/digest, current WorkOrder,
authorized actors, execution policy and its explicit limits, issue-time
validity, the compatibility digest and a canonical historical-authority digest.
The snapshot is idempotent for identical input and conflicts on substitution.
No pre-decision template or reserved decision ID is introduced.

Activation and revocation of compatibility authorization are separate journal
events. Revocation blocks new decisions. Revocation before stage-two snapshot
also blocks new execution; revocation after a valid issue does not rewrite its
history. Execution snapshots have their own explicit expiry/revocation event.
Historical resolution replays both lifecycles and returns a snapshot only when
the compatibility and execution authorities were active at the exact decision
and issue/use timestamps. It does not infer history from current state, current
roles, retained reports or a deterministic recreation of a missing event.

Configuration cannot activate authority. Production configuration supplies
only owner-protected absolute paths to the journal and an approved catalog
input plus the existing storage/capability dependencies. Missing, malformed,
unknown-field, mutable, unsigned/unapproved, synthetic, or participant-mismatched
input leaves the workflow absent or closed before routes become positive.

Catalog approval uses a dedicated, injected
`ExternalQuantitativeCatalogAuthorityPort`. Its domain-separated immutable
record binds the exact canonical catalog-body digest, organization, authorized
administration actors and validity interval. The catalog file carries only the
record digest; it cannot carry, create or self-approve the trusted record. The
port is therefore the trust boundary and must return the exact currently valid
record before any mapping or execution template is admitted. The existing
`PolicyAuthorityRecord` remains limited to validation-policy bodies and sealed
subjects; its meaning is not widened to authorize quantitative thresholds.
Every production execution policy's `authorityRecordDigest` binds this catalog
approval record, and an unavailable or mismatched port fails closed.

The catalog authority record avoids self-referential hashing through one exact
canonical admission-body serializer. It omits only the top-level catalog
`authorityRecordDigest` and the catalog approval references in contained
mapping templates and execution policies. The authority record approves that
admission-body digest. Its sealed digest is then inserted into every omitted
reference before the final catalog is validated and used. The loader rejects
extra omissions, mismatched references, or a catalog whose recomputed
admission-body digest differs; arbitrary field exclusion is not permitted.

## Assembly and failure behavior

`services/core` provides one explicit production workflow builder. It returns
the existing `ExternalResultWorkflowAssemblyConfig` and therefore preserves the
current application graph, coordinator identity, queue policy and byte issuer.
The development assembly remains closed unless the caller explicitly injects a
workflow config. Dashboard and customer routes never select policy, mapping,
threshold, actor, organization, subject, WorkArea or authority digests.

Startup replay rejects malformed shape, digest mismatch, impossible chronology,
duplicate identity with different bytes, revocation before activation,
execution-before-decision, execution-after-compatibility-revocation, unknown
participants, or a managed-profile alias. Runtime currentness checks occur
under the existing shared coordinator. I/O or authority uncertainty returns the
existing typed blocked/unavailable result and appends no positive decision,
execution snapshot or request.

Fresh authority use is deliberately separate from historical replay. Before an
admission, mapping use, activation, or issue operation, Core resolves the
catalog, policy, and evidence sources outside the coordinator guard. It then
rechecks the exact retained catalog approval, policy, evidence records, sealed
capture bindings, and active WorkArea locally under that shared coordinator
before it appends or returns positive authority. The catalog currentness source
is factory-bound to the exact coordinator and verifies immutable record body
and digest, organization, membership/status, and time; an unavailable or
mismatched local projection closes the operation. A final guarded execution
use repeats only the local checks. Historical resolution instead uses the
event-time lifecycle and does not apply present-time revocation.

Execution activation stores the exact existing eligible `RELATIVE_VOLUME`
decision identity and its UTC `decidedAt`. Both runtime activation and replay
require that timestamp to be at or before `activatedAt`; absent, malformed,
non-UTC, ineligible, or later decisions are rejected.

The configured authority journal is a protected replay boundary. Existing
journal, lock, and retained segment files must be single-link regular files
owned by the effective owner/group with mode `0600`; symlinks, hard links,
special files, replacements, and non-sticky group/other-writable ancestors are
rejected. Missing primary and lock nodes are securely created before the
existing tracked opener runs, then revalidated. The generic `DurableJournal`
remains unchanged.

## Acceptance

Local acceptance requires default-closed configuration tests, one exact
same-profile positive pair, every substitution and cross-profile negative,
compatibility activation/revocation, post-decision execution snapshot,
restart/replay, revoked-before-use history rejection,
tenant non-disclosure, hostile configuration, common `assemble_app` positive
assembly, and the existing request-to-review-to-successor flow.

Local acceptance is not deployment or product release. Dedicated cross-UID
rootless execution, signed OCI image/SBOM evidence, actual customer export
compatibility, owner operation, backup/restore, deployment, HIL and field
acceptance remain separate evidence gates.

## Rollback

Disable production authority injection and new enqueue/issue operations. Retain
all immutable submissions, inspection reports, evidence validations, decisions,
authority lifecycle events, measurement reports, reviews and WorkOrders. Never
rewrite managed records, broaden compatibility, or delete customer data as a
rollback shortcut.
