# Civil Operations R1 — runtime와 처리 admission 수용기준

- Status: IN_PROGRESS
- Date opened: 2026-08-30
- Authority: ADR-KSI-032; PRODUCT_CONSTITUTION; FINAL_DECISION_LEDGER v1.0
- Requirements: REQ-OPS-101/102, REQ-WRK-101, REQ-INT-104, REQ-SEC-101, REQ-UX-101
- Invariants: INV-040/050/053/054/055/060

이 문서는 기존 `CIVIL_PROCESSING_V1_ACCEPTANCE.md`의 처리·정량 비교 수용을 대체하지
않는다. 같은 workflow를 고객 pilot 환경에서 재현 가능하고 자원 초과에 fail-closed하게
조립하는 운영 increment다. software PASS는 외부 Cloud, 고객 데이터, 국내 현장 정확도,
FIELD-0a 또는 DJI capability PASS가 아니다.

## Acceptance matrix

| ID | Criterion | Evidence | Status |
|---|---|---|---|
| RT-01 | Production-owned Dockerfile/Compose external images use exact version plus multi-arch OCI digest; tag-only and `latest` are rejected. | Static image-pin gate, Dockerfile/Compose contract tests, resolved version/digest ledger. | IN_PROGRESS |
| RT-02 | A release candidate can bind source SHA, built image digests, SBOM and scanner output without committing credentials or customer data. | Release-manifest tool/workflow contract and negative tests. | PLANNED |
| RP-01 | `ksi-civil-pilot-r1` has a deterministic canonical digest and is available through an authenticated read-only Core registry. | Contract/schema/API tests; unauthenticated refusal. | IN_PROGRESS |
| RP-02 | Core derives file count, per-file bytes, bundle bytes, total megapixels and same-organization active jobs from server records; the client cannot submit policy/limits/override. | Per-limit store/API tests, hostile JSON 422, organization isolation. | IN_PROGRESS |
| RP-03 | A new ProcessingJob binds the exact resource-policy snapshot/digest; replay rejects half bindings, forged digests and records violating their own snapshot while preserving pre-policy history as legacy. | Replay and mutation tests. | IN_PROGRESS |
| RP-04 | An idempotent retry of the same active job returns its existing immutable record even if the current policy would now refuse a new job. | Policy-change retry regression. | IN_PROGRESS |
| UX-01 | The existing Mission upload/processing card shows the server policy and actionable typed refusal without a new global menu or duplicated hardcoded limits. | Vitest, ESLint, TypeScript, build and four-viewport browser regression. | PLANNED |
| OP-01 | Existing metrics/logging expose bounded processing admission and transition outcomes without raw filenames, coordinates, imagery or unbounded identifier labels. | Observability contract tests and metric-label review. | PLANNED |
| HY-01 | No raw imagery, LandXML, GeoTIFF, checkpoint coordinates, credentials, SBOM output or built image archive enters Git. | Lock/diff/hygiene/large-file/secret scans. | PLANNED |

## External gates kept separate

- GitHub Actions jobs must actually start after the owner resolves account payment/spending limits.
- Actual public DNS/ACME, external IdP, managed secrets, off-host restore and Cloud due diligence remain
  required before customer data deployment.
- Korean same-site two-epoch imagery, LandXML and independent reference remain the civil field gate.
- FIELD-0a and every DJI/Manifold capability remain `BLOCKED`/`NOT_VERIFIED`/OFF until their own
  physical evidence is collected.

## Rollback

Disable new resource-policy admission issuance and leave existing jobs/results read-only. Roll back
runtime bytes only to a previously verified digest, never a floating tag. Preserve all originals,
jobs, artifacts, design surfaces, comparisons and reports; do not relax `INV-053` to restore service.
