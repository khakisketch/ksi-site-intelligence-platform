# F-04 review persistence — chain regeneration evidence (synthetic)

Date: 2026-10-13 (KST). Scope: copy stack only (issuer 9051 / Core 8051 / Console 3251).
Stage-1 (9041/8041/3241) and the original F-03 material were not touched.

## Result

Regenerated the F-03-generation authority chain with current windows and drove it
end-to-end to a Console review whose persistence was verified:

1. Policy authority record R' -> policy `external-geotiff-v1@11`
   (`policyDigest sha256:a3e5c231…`), evidence contexts x2 (`policyDigest` v11),
   catalog authority `C'''` (`sha256:6cf290b6…`), snapshot seq 25 (ADMIT_POLICY) + boot.
2. Inspection lane x2 -> MEASURED (policy v11; reports `66ef0aae…` / `cb9305bb…`).
3. Checkpoint lane x2 -> VALIDATED evidence records `c976a7d6…` / `22f6bbf6…`
   (one REJECTED TRANSIENT record `23094d16…` retained; order-13 retried under a new
   context generation r2 — the UDS fixture serves one exchange per instance).
4. Mapping re-admitted: `9619bbcde3499cca565d6f0ee2e9a460c48685993519c2acc72da6d9eb7899f6`
   (executionPolicyRef = C'''); superseded mappings revoked by signed REVOKE_MAPPING.
5. Pair decision ELIGIBLE (`external-use-decision-e6be189e…`) -> relative-volume request
   `external-relative-volume-69b1a106e13bc9d0c6956b84c7ef491d` -> measurement lane
   COMPLETED.
6. Report: `external-relative-volume-report-ae2d5e6498201b7fd1d1dc2363132e0a`
   (`sha256:da0337c2…`; net 0.0 m3, common-valid 4/4 = 100%, uncertainty ±0 m3).
7. Console review write (OIDC principal mapped to `f03-admin`): 201 Created.
   Review `err-v1-0894a51a25920ad68296d5f2eca455923c1e048f874172fffee628b4305620a3`
   (`sha256:9015c31c…`), reviewedAt 2026-10-13T04:37:20Z.
8. Persistence: visible after page reload AND after a full copy-stack restart
   (Core journal replay). Screenshots below.

## Screenshots

- `review-before-restart.png` — report + review line after page reload.
- `review-after-core-restart.png` — same review line after `relaunch.sh` (Core restart).
- `observations-page.png` — the site observations surface shows the same review.

## Gates discovered and how they were handled (synthetic prep)

- A context introduced by a reload issues its validation work on the FOLLOWING reload
  (boot differs); seq 27 bump reload was used.
- The checkpoint UDS fixture is single-use per instance; the second request in one run
  became a terminal REJECTED(TRANSIENT) record. Honest retry = new context generation.
- `gen_f03_provider.py` fabricated the catalog execution envelope digest
  (`digest("f03-synthetic-resource-envelope")`) vs the real validation envelope
  (`c5dca416…`) -> `_policy_matches` could never pass. Copy catalog fixed.
- Same generator's `algorithmBuildDigest=digest("volume-algorithm")` cannot equal any
  real measurement manifest body digest (PREPARE_V2 requires equality) -> bound to
  `_manifest_for_resource_envelope(c5dca416…)` = `sha256:1d061713…`. Catalog binding is
  computed at Core boot, so each catalog round required a restart + mapping re-admission.
- Console review flow was blocked for OIDC-scoped operators by the auth allowlist
  (403 on the single-request GET and the review POST). Human-approved extension
  (commit b4a3905) added the 4 routes; handler authority unchanged.
- Work orders 12/13 carry `workAreaIds=["wa-…-0001"]` while the analyzed zone is
  `wa-…-0002`; scoped operators get 404 for the report/history. For this copy-stack
  verification the Console account was unscoped (v2 registry null scope). Real
  materials must keep work-order areas and the analysis zone consistent.

## Boundaries

Synthetic only. Parser sandbox -> VALIDATED acceptance, real A–E materials, the
verification host, and customer/EXT-VAL acceptance remain OPEN. The lane drivers and
one-off prep scripts used for this run live in `/tmp/opencode/ksi-f04-review-20261013/`
(transient; summarised above), and the chain-renewal tool promoted from this work is
`tools/regenerate_external_validation_chain.py`. The canonical record with exact digests
is the rebaseline ledger entry ("F-03 체인 재생성 — Console 검토 지속성 로컬 폐쇄").
