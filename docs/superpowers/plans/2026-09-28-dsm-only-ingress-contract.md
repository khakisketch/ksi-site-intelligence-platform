# FPC-03A — DSM 단독 등록 계약의 첫 증분

**Plan ID:** FPC-03A-20260928. **상태:** 계약 증분 로컬 검증 완료; Core 등록 배선·slice 수용 미완. 이 계획은 [첫 제품 로드맵](2026-09-28-first-product-completion-roadmap.md)의 FPC-03/04에 속하며 `EXT-VAL` slice를 닫지 않는다. [현황 감사](../../audit/FIRST_PRODUCT_GAP_AUDIT_2026-09-28.md)가 발견한 V1 정사영상 필수와 첫 V2 요청의 DSM 단독 입력 충돌만 다룬다.

| 필수 항목 | 결정 |
| --- | --- |
| Requirement IDs | REQ-INT-101/102/103/104; 첫 요청 계약 `Input artifacts`; EXT-VAL-01/02/03의 입력 계약 부분. INV-020/024/051/053/060을 유지한다. |
| Owner module | `packages/event-contracts` 계약, `contracts/schemas` 스키마, `tests/contract` 적합성 시험. |
| Acceptance criteria | 별도 `external-reconstruction-submission.v2` 계약이 DSM 하나·정사영상 0/1을 허용하고 DSM 없는 입력/중복 종류·ID/위조 digest를 거부한다. JSON Schema는 구조 검사이고 전체 wire 검증은 필수 키·중복 ID·canonical digest를 검사하는 명시적 파서를 사용한다. 기존 V1은 정사영상 필수와 기존 digest를 그대로 유지한다. 선언은 관측 사실·정량 적합성으로 승격되지 않는다. |
| Contracts affected | Additive submission V2 model and schema only. Manifest/ingress API/원장 V2 배선은 후속 작업이며 이 증분만으로 DSM-only 등록 가능하다고 주장하지 않는다. |
| Reference assets | V1 모델·스키마/계약 시험 REUSE. `references/repos/**`는 읽기 전용 참고이며 직접 import 없음. |
| Adoption decisions | V1 필수 조건을 완화하지 않는다. V2는 기존 안전한 artifact declaration과 canonical digest 규칙을 재사용하되 자체 contractVersion으로 구별한다. |
| Files to change | `packages/event-contracts/src/ksi_event_contracts/external_reconstruction.py`, `contracts/schemas/external-reconstruction-submission.v2.json`, 관련 `tests/contract/test_external_reconstruction_contracts.py` 또는 실제 소유 시험 파일. 다른 런타임 파일은 이 task에서 금지. |
| Tests | 새 V2 양성/음성 schema-model parity, digest 순서·tamper, V1 회귀. 먼저 실패 시험을 실행하고 최소 구현 뒤 focused pytest + `git diff --check`. |
| HIL or real-device assumptions | 없음. 합성 계약 시험은 Terra 호환성, 실제 파일 검사, host isolation, 현장 정확도를 입증하지 않는다. |
| License/data implications | 고객 파일을 사용하지 않는다. 외부 엔진 재사용/라이선스 변경 없음. |
| Rollback | additive V2 파일/참조만 제거하면 V1 기능과 저장 이력은 그대로. 실제 라우트 활성화 없음. |

**FPC-03A-1 (worker 소유):** 정확한 기존 모델/시험 파일을 확인하고 V2 양성·음성 계약 시험을 먼저 작성한다. V1 정사영상 필수/기존 digest 회귀도 고정한다. 시험이 새 기능 부재로 실패하는 것을 확인한다.

**FPC-03A-2 (동일 worker):** V2 모델과 스키마를 최소 구현하고 집중 시험을 통과시킨다. V1 바이트/계약 의미 변경, Core 라우트 변경, 정책 활성화, 배포는 금지한다. 변경 경로·실행 시험·남은 위험을 Lead에 보고한다.

## 실행 근거

2026-09-28 전용 worktree `feat/dsm-only-ingress-contract-20260928`에서 TDD로 구현했다. 첫 독립 검토는 JSON Schema가 서로 다른 종류 간 중복 `artifactId`를 거부하지 못하는 문제를, 두 번째 검토는 새 wire 파서가 필수 `submissionDigest` 없이 자료를 받는 문제를 발견했다. 동일 작업자가 각각 수정했고, 세 번째 독립 검토는 [고정 diff·해시](../../../.opencode/artifacts/first-product-completion-20260928/dsm-contract-review.json)에 **PASS**를 냈다. 원래 작업본에 검토한 세 파일의 해시를 대조해 통합했다.

통합 후 로컬 검사: `uv run pytest -q tests/contract/test_external_reconstruction_contracts.py tests/contract/test_external_reconstruction_api.py tests/replay/test_external_reconstruction_replay.py` → **111 passed**. `uv run pytest -q tests/contract/test_api_contract_sync.py` → **36 passed**. 두 pytest 실행에 각각 기존 임시 디렉터리 청소 경고 12건이 있었다. `uv run ruff check packages/event-contracts/src/ksi_event_contracts/external_reconstruction.py tests/contract/test_external_reconstruction_contracts.py` 및 `git diff --check` 통과. V1 봉인 digest 회귀도 집중 시험에 포함됐다. 이 근거는 미커밋 작업본의 로컬 검증이며 CI·배포·실자료/현장 수용이 아니다.

**후속 의존:** Core 등록/봉인 원장·manifest V2 결속과 검사/Analysis 선택자 배선은 별도 bounded task 및 보안·replay 검토가 필요하다. FPC-03A 통과가 EXT-VAL-01..08 완료를 의미하지 않는다.
