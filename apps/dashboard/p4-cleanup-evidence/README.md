# P4 evidence routing

Use the frozen, source-bound bundles below for review. A directory name alone does not establish
the revision, timing, authentication state, or product acceptance.

| Evidence | Meaning |
| --- | --- |
| `t4-inputs-v1/` | Initial immutable review input, including explicit earlier failures and state limits |
| `t4-round2-render-v1/` | Source-bound responsive, empty/error/loading, keyboard and motion states; Home candidates/diffs/retained references |
| `t4-round3-render-v1/` | Post-Round3 states and exact four-image mechanical Home adoption record |
| `t4-round4-render-v1/` | Final UI source and 18 actual-product captures reviewed in `../p4-cleanup-final-render-review.md` |
| `t5-e2e-red-v1/` | Independent 69-pass / 8-fail / 15-skip result before the final test-only correction; not a passing receipt |
| `t5-final-source-v1/` | Final verification snapshot; one E2E-file-only delta from the unchanged design-reviewed UI |

For the final asset-title and More-copy corrections, actual before states are
`t4-round3-render-v1/{actual-assets,denied-assets,more-before}-{390,768,1440}.png`; matching after
states are `t4-round4-render-v1/{actual-assets,denied-assets,more-after}-{390,768,1440}.png`.
Their source/input hashes and the design review identify what was inspected.

`before/` and `after/` are **rolling capture-output directories, not authoritative chronological
before/after evidence**. `e2e/p4-cleanup-capture.spec.ts` defaults its output phase label to `before`
when `P4_CAPTURE_PHASE` is unset; full E2E runs can therefore refresh that directory from current
source. Do not use these labels to claim a fresh pre-P4 capture or as a baseline-adoption authority.
Historical Home reference bytes are separately retained in the frozen Round2 bundle.

All captures use owned generated fixtures. The product host `http://localhost:3241/` is temporary
loopback serving on the development host, not a public deployment or customer workstation.
Design review, independent functional verification, Human acceptance and customer/operational
acceptance are separate. No auth state, cookie storage or browser trace is included here.
