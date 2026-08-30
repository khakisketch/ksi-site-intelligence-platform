# Civil Operations R1 — runtime와 처리 admission 수용기준

- Status: SOFTWARE_PASS — EXTERNAL_RELEASE_GATED
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
| RT-01 | Production-owned Dockerfile/Compose external images use exact version plus multi-arch OCI digest; tag-only and `latest` are rejected. | Static image-pin gate, Dockerfile/Compose contract tests, resolved version/digest ledger. | PASS |
| RT-02 | A release candidate can bind source SHA, built image digests, SBOM and scanner output without committing credentials or customer data. | Create-once local envelope/schema/tool plus dirty-tree, exact-source-tree, symlink/path-swap, malformed/oversized input and cleanup-failure tests. | SOFTWARE_PASS |
| RP-01 | `ksi-civil-pilot-r1` has a deterministic canonical digest and is available through an authenticated read-only Core registry. | Contract/schema/API tests; unauthenticated refusal. | PASS |
| RP-02 | Core derives file count, per-file bytes, bundle bytes, total megapixels and same-organization active jobs from server records; the client cannot submit policy/limits/override. | Per-limit store/API tests, hostile JSON 422, organization isolation. | PASS |
| RP-03 | A new ProcessingJob binds the exact resource-policy snapshot/digest; replay rejects half bindings, forged digests and records violating their own snapshot while preserving pre-policy history as legacy. | Replay and mutation tests. | PASS |
| RP-04 | An idempotent retry of the same active job returns its existing immutable record even if the current policy would now refuse a new job. | Policy-change retry regression. | PASS |
| UX-01 | The existing Mission upload/processing card shows the server policy and actionable typed refusal without a new global menu or duplicated hardcoded limits. | Vitest, ESLint, TypeScript, build and four-viewport browser regression. | PASS |
| OP-01 | Existing metrics/logging expose bounded processing admission and transition outcomes without raw filenames, coordinates, imagery or unbounded identifier labels. | Observability contract tests and metric-label review. | PASS |
| HY-01 | No raw imagery, LandXML, GeoTIFF, checkpoint coordinates, credentials, SBOM output or built image archive enters Git. | Lock/diff/hygiene/large-file/secret scans. | PASS |

## Software evidence — 2026-08-30

- Functional commits: `89c2fea`, `273ab64`, `ddd1c8c`, `427dec8`, `5f22f5e`, `04cb68a`.
- Python: `4215 passed, 24 skipped`; Ruff lint passed; Mypy passed `441` source files;
  `uv lock --check` passed. The skips are explicit environment-dependent tests, not unexpected failures.
- Release/runtime contracts: `43 passed`; runtime image pin scanner returned `OK`; the release envelope
  derives a clean source SHA and scans runtime references from that exact committed tree.
- Dashboard: Vitest `62 files / 566 tests`, ESLint, `tsc --noEmit` and Next.js 16.3.3 production build
  passed. Playwright passed `62` with `14` intentional external-staging skips at
  390/768/1024/1440, including policy visibility, typed recovery, overflow, keyboard/focus and
  accessibility checks.
- Repository: hygiene, no-reference-import, reference-pin, DJI third-party checksum, runtime-pin and
  `git diff --check` gates passed. No release SBOM/scanner output or product image archive was created
  or committed during this software verification.

RT-02의 `SOFTWARE_PASS`는 생성 도구와 fail-closed 계약이 준비됐다는 뜻이다. 실제 KSI product
image를 build해 SBOM/scanner bytes와 연결한 release envelope, registry promotion 기록, 서명,
WORM/remote anchor 및 vulnerability approval은 아직 생성·승인되지 않았다. 로컬 SHA-256 sidecar는
authenticity signature나 tamper-proof storage가 아니다.

## External gates kept separate

- GitHub Actions jobs must actually start after the owner resolves account payment/spending limits.
- The delivered commit must build the real KSI product images, produce and review their CycloneDX and
  scanner artifacts, bind them with `tools/build_release_evidence.py`, sign/anchor the result and verify
  the promoted registry digests. None of those external release facts is inferred from the tool tests.
- Actual public DNS/ACME, external IdP, managed secrets, off-host restore and Cloud due diligence remain
  required before customer data deployment.
- Korean same-site two-epoch imagery, LandXML and independent reference remain the civil field gate.
- FIELD-0a and every DJI/Manifold capability remain `BLOCKED`/`NOT_VERIFIED`/OFF until their own
  physical evidence is collected.

## Rollback

Disable new resource-policy admission issuance and leave existing jobs/results read-only. Roll back
runtime bytes only to a previously verified digest, never a floating tag. Preserve all originals,
jobs, artifacts, design surfaces, comparisons and reports; do not relax `INV-053` to restore service.
