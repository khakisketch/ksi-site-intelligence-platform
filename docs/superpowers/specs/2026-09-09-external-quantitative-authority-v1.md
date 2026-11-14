# External quantitative authority v1

Human-approved strict first-release contract under ADR-KSI-036 D5. External-derived evidence never acquires managed reconstruction authority.

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

Core admits the rule before any comparison, then binds the exact ordered subjects, WorkArea, policy and evidence into an immutable mapping. Execution and historical use consume the complete mapping digest. A cross-profile mapping requires separate Product Authority approval and benchmark evidence.
