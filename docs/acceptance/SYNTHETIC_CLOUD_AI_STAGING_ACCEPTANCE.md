# Synthetic Cloud/AI Staging 수용 기준

- Status: PASS — Phase 2 synthetic-only software staging
- Date: 2026-08-25
- Requirements: REQ-COP-101/102, REQ-SEC-101
- Invariants: INV-002, INV-040/041, INV-050/051, INV-060/061
- Scope: 합성 OIDC 조직, HTTPS Tailnet ingress, S3-compatible evidence, grounded Copilot,
  backup/isolated restore. 고객 Cloud, 실제 외부 모델, DJI/HIL은 포함하지 않음.

## 합격 기준과 결과

| ID | 합격 조건 | 2026-08-25 증거 |
|---|---|---|
| STG-01 | 기존 개발 stack과 분리된 production-equivalent Dashboard/Core profile | 별도 Compose project, 5개 전용 named volume, loopback bind와 Tailscale HTTPS Serve `:10000`~`:10003` |
| STG-02 | 사람 인증은 OIDC Authorization Code + PKCE이고 브라우저 token 표면이 없음 | Local Identity 합성 조직 로그인, Dashboard `EXTERNAL_VM`, Core OIDC 검증, `/api/auth/session` 404 |
| STG-03 | 증거 metadata가 실제 object bytes와 digest에 연결되고 browser가 public presigned GET을 사용 | MinIO에 1x1 PNG와 SHA-256 등록, Event 상세에서 `naturalWidth > 0` |
| STG-04 | Site별 opt-in 전에는 AI egress가 거부됨 | 5개 합성 Site 중 `e2e-site-workspace`만 허용, review Site는 대화 UI 대신 미동의 상태 |
| STG-05 | AI 답변은 tool 결과와 same-site citation 검증 후에만 저장·표시 | local OpenAI-compatible fixture가 `site_snapshot`을 호출하고 검증된 workspace citation을 표시 |
| STG-06 | provider 실패와 허위 citation이 fail-closed | 503은 `PROVIDER_UNAVAILABLE`, cross-site citation은 근거 부족 `BLOCKED`; Mission·승인·비행 명령 없음 |
| STG-07 | secret은 파일로만 공급하고 state 일부 손실 시 조용히 재생성하지 않음 | owner-only env/secret, partial signing-key set 기동 거부, synthetic key volume 분리 |
| STG-08 | journal/object/signing key 백업을 격리 volume에 실제 복원 | SHA-256 3종 확인 후 journal/object/`keys.json` 존재 확인 |
| STG-09 | 390/768/1024/1440 제품 흐름이 TLS·OIDC·overflow·접근성 계약을 유지 | Phase 2 전용 Chromium 12/12, external 전체 suite 46 passed/22 intentional skipped |

## 실행 증거

- Console: `https://dgx-spark-1.tailda9552.ts.net:10000`
- Identity: `https://dgx-spark-1.tailda9552.ts.net:10001`
- Core: `https://dgx-spark-1.tailda9552.ts.net:10002`
- Object API: `https://dgx-spark-1.tailda9552.ts.net:10003`
- Backup bundle:
  `.dev-data/phase2-synthetic-staging/backups/ksi-vm-20260825T124618Z`
- Dashboard: `58 files / 527 tests`, ESLint, TypeScript, production build, npm audit 0.
- Contract: synthetic staging/fixture 12 tests, Bash syntax and Compose resolution.
- Repository: full Python `3858 passed, 23 skipped, 3 xfailed`; Ruff; full Mypy
  `389 source files`; `uv lock --check` and `git diff --check`.

## 정직한 한계

이 PASS는 DGX Spark 한 노드의 Tailnet 한정 합성 software staging 수용이다. 특정 Cloud
사업자, public DNS/ACME, 실제 기업 IdP, secret manager, off-host backup 보관, 고객 데이터,
실제 외부 AI provider의 위탁·국외 이전·보존 조건은 승인하지 않는다. 해당 항목은
`docs/security/CLOUD_PROVIDER_DUE_DILIGENCE.md`가 OPEN인 동안 금지다.

DJI `WAYLINE_DELIVERY`, `EDGE_DOWNLINK`, `EDGE_UPLINK`, `MEDIA_PULL`, `MEDIA_UPLOAD`은 이
Staging과 연결되지 않았고 모두 `NOT_VERIFIED`다. Phase 3은 별도 승인된 물리 장비 read-only
세션과 capability별 원시 증거가 있어야 시작한다.
