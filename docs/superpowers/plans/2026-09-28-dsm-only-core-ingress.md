# FPC-03B — DSM 단독 제출물의 Core 등록·봉인 경로

**Plan ID:** FPC-03B-20260928. **상태:** B1/B2/B3 로컬 검증 완료; 독립 inspector·Terra·운영 호스트 수용은 별도 게이트. **근거 설계:** [ADR-KSI-036](../../architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md), [ADR-KSI-037](../../architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md), [첫 요청 계약](../../design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md), [FPC-03A](2026-09-28-dsm-only-ingress-contract.md). 현재 `EXT-VAL` slice를 닫거나 운영 정책을 활성화하지 않는다.

**Goal:** V1 이력과 등록 동작을 유지하면서 고객의 DSM 단독 V2 제출물을 Core에 등록·바이트 봉인하고, 기존 검사·Analysis가 같은 봉인 기록을 선택할 수 있게 한다.

**Architecture:** 새 제출물 버전은 기존 Core 원장·조직 범위·객체 해시 관측을 재사용한다. 원장 이벤트 봉투는 동일한 필드를 유지하고 제출 payload의 `contractVersion`으로 V1/V2를 구분한다. V1 manifest는 특정 제출 버전이 아니라 정확한 제출 digest와 관측 바이트를 결속하므로, V2 제출물에도 같은 manifest 형식을 사용하되 생성·replay에서 정확한 V2 payload를 검사한다. 한 제출 ID의 수정 revision에서는 제출 계약 버전을 바꾸지 않는다. HTTP에서는 기존 V1 POST를 그대로 두고 V2 전용 POST를 추가하며 기존 ref 조회·grant·seal을 공유한다. V2 등록/봉인도 형식 검사·정량 적합성/정확도 승격을 하지 않는다.

**Tech stack:** 기존 Pydantic v2, FastAPI, JSONL durable journal, digest-bound object storage, pytest/replay. 새 외부 의존성 없음.

| 필수 항목 | 결정 |
| --- | --- |
| Requirement IDs | REQ-INT-101..104, REQ-SEC-101; EXT-VAL-01/02/03/05/06의 Core ingress 관련 부분; ADR-KSI-037 첫 요청 입력. |
| Owner module | `packages/event-contracts` manifest factory, `services/core` 외부 등록 원장·라우트, `contracts/api` OpenAPI. |
| Acceptance criteria | V2 DSM-only 등록 → digest-bound grant → 실제 바이트 관측·봉인 → 동일 ref의 조회/원장 재생. V1 기존 이벤트/route/봉인 digest 의미 불변. 다른 조직 404, 위조 버전/digest·누락/불일치 바이트·혼합 버전 수정·오래된 revision은 거부. 봉인 기록은 검사/Analysis가 동일 DSM entry를 읽을 수 있다. |
| Contracts affected | Additive V2 POST operation; `external-reconstruction-submission.v2` 사용. Manifest v1 wire shape/digest 계산 변경 없음. 기존 V1 POST request schema 변경 없음. |
| Reference assets | V1 store/route/replay, FPC-03A parser, `tests/contract/test_external_reconstruction_api.py`, `tests/replay/test_external_reconstruction_replay.py`. Reference repos import 금지. |
| Adoption decisions | REUSE Core journal/opaque ref/object key/manifest format and inspect-on-seal hook; ADD version dispatch at exact trusted boundaries. Do not copy Core store or create a second authority. |
| Files to change | B1: `packages/event-contracts/src/ksi_event_contracts/external_reconstruction.py`, `services/core/src/ksi_core/domains/external/ingress/external_reconstruction.py`, owner contract/replay tests. B2: same Core route, `contracts/api/openapi-core.yaml`, API tests. Other owner files only after Lead scopes a separate task. |
| Tests | B1/B2 each RED→GREEN focused tests. V1/V2 contract/API/replay, auth/tenant, hostile input, dedup/concurrency and `test_api_contract_sync.py`; exact integrated checks after review. |
| HIL or real-device assumptions | 없음. 로컬 객체 바이트 시험은 독립 검사 호스트·Terra 실제 export·정확도·고객 수용 증거가 아니다. |
| License/data implications | 고객 실자료 없음. raw media 기본 반입 없음. 제공/AI 반출 권리는 별도 고객 승인. |
| Rollback | V2 POST 비활성/제거. V1 원장은 이전 방식으로 재생되고, 이미 봉인된 V2 기록은 삭제·변조하지 않는다. V2 기록이 존재하면 V2 해석 코드를 무단 제거하지 않는다. |

## B1 — Core store와 manifest의 versioned 제출물 결속

**독립 결과물:** V2 모델을 등록·봉인·재생할 수 있는 기존 Core 저장 경로. HTTP 경로는 아직 추가하지 않는다.

1. V2 단독 DSM의 register→grant→seal→reopen, 동일 재시도, V1 이력 회귀, 혼합 버전 수정/위조 V2 wire·digest/바이트 불일치 음성 replay 시험을 먼저 작성하고 의도한 RED를 확인한다.
2. 기존 원장 이벤트의 exact field/digest/version 검사를 유지하면서 제출 payload의 V1/V2 파서를 구분한다. V2는 FPC-03A의 완전 wire parser를 사용한다. 새 이벤트 형식이나 별도 원장을 만들지 않는다.
3. `ExternalReconstructionManifestV1.from_submission()`이 봉인된 V1 또는 V2 제출의 정확한 digest·scope·artifact set을 결속하게 하고, 기존 V1 wire serialization 경로는 그대로 유지한다.
4. focused contract/replay/Ruff/diff-check 결과와 변경 경로·남은 위험을 보고한다. Core V2 HTTP 배선 또는 운영 호스트 변경이 필요하면 멈춘다.

## B2 — V2 전용 등록 API와 동일 조회/봉인

**선행:** B1 독립 검토·통합. **독립 결과물:** 기존 V1 POST를 유지하고 V2 POST만 추가하며 반환된 ref로 기존 조회·grant·seal을 수행한다.

1. 인증/조직/WorkOrder/시점/캡처 구간·멱등/중복 수정·관측 실패·V1 회귀 API 시험을 먼저 작성한다.
2. V2 요청을 완전 wire parser에 전달하는 별도 POST를 만들고 기존 Core store·권한·workflow guard를 호출한다. `contracts/api/openapi-core.yaml`에 별도 V2 요청 스키마를 명시한다.
3. `test_api_contract_sync.py`와 focused API/replay를 실행한다. 이후 Core→검사·Analysis 선택자가 동일 sealed DSM을 해석하는 B3 검증을 따로 진행한다.

## B1 로컬 근거 — 2026-09-28

작업 트리 `feat/dsm-only-ingress-contract-20260928`에서 TDD RED를 확인했다. V2 manifest factory 1건, V2 등록/replay 5건이 기존 V1 전용 파싱에서 실패했다. 기존 이벤트 봉투와 manifest v1 wire를 유지하면서 payload 버전별 해석·동일 스트림 버전 고정을 구현했다. [네 파일의 고정 diff·해시](../../../.opencode/artifacts/first-product-completion-20260928/dsm-core-ingress-b1-review.json)에 대한 독립 보안/replay 검토는 **PASS**였다. 검토한 해시 그대로 현재 작업본에 통합했다.

통합 후 `uv run --package ksi-core pytest -q tests/contract/test_external_reconstruction_contracts.py tests/contract/test_external_reconstruction_api.py tests/replay/test_external_reconstruction_replay.py` → **118 passed** (이전 ACL 임시 디렉터리 청소 경고 12건). 네 소유 파일 Ruff와 `git diff --check` 통과. V2 HTTP route, 독립 검사 호스트, Terra 실자료·정량 적합성은 이 근거에 포함되지 않는다.

## B2 로컬 근거 — 2026-09-29

V2 POST가 없어서 등록·권한·workflow 신규 시험 5건이 404로 실패하는 RED를 확인했다. 기존 V1 POST를 유지하고 별도 V2 POST가 FPC-03A의 완전 wire parser 및 기존 WorkOrder/권한/guard/Core store를 사용하게 했다. 반환된 opaque ref로 기존 GET·grant·seal 경로를 사용한다. [세 파일의 고정 diff·해시](../../../.opencode/artifacts/first-product-completion-20260928/dsm-core-ingress-b2-review.json)는 독립 인증·조직 경계/계약 검토에서 **PASS**였고, 그대로 현재 작업본에 통합했다.

통합 후 `uv run --package ksi-core pytest -q tests/contract/test_external_reconstruction_contracts.py tests/contract/test_external_reconstruction_api.py tests/replay/test_external_reconstruction_replay.py tests/contract/test_api_contract_sync.py` → **160 passed** (이전 pytest 임시 디렉터리 청소 경고 12건). 관련 다섯 Python 파일 Ruff와 `git diff --check` 통과. API 시험의 객체 저장소는 관측 port의 시험 대역이며 실제 S3·독립 inspector·Terra 수용 증거가 아니다.

## B3 — 검사·Analysis 결속 확인

**선행:** B2. 첫 단위는 테스트 전용 로컬 fixture가 V2 DSM-only 두 시점을 **V2 HTTP 등록 → 반환 ref 조회/grant → 실제 합성 GeoTIFF 바이트를 시험 객체 저장소에 둠 → Core seal**로 만든다. 기존 V1 fixture는 그대로 유지한다. 같은 봉인 기록을 Core inspection request/report·Analysis selector가 참조하는지, Core HTTP로 Analysis를 요청하고 실제 GIS 워커 `run_once`가 잠정 수치를 저장한 뒤 API result/evidence가 같은 결과를 반환하는지 검증한다. 전용 route 누락, 정사영상 강제, 봉인/검사 digest 불일치, 숫자 우회가 있으면 실패해야 한다. 소유 파일은 `tests/contract/analysis_api_local_fixture.py`, `tests/contract/test_external_analysis_http_integration.py`로 제한한다. 생산 코드 결손이 나오면 이 단위를 멈추고 해당 소유 모듈의 bounded correction을 별도로 정한다. 여기서 inspection report는 합성 시험 helper가 기록하므로 **독립 inspector가 실제 파일을 읽은 증거가 아니다**. 독립 검사 호스트와 Terra 실자료 수용은 FPC-12/10 게이트로 남긴다.

커밋·PR·배포·권한/credential 변경은 이 계획에 포함되지 않는다.

## B3 로컬 근거 — 2026-09-29

V2 DSM-only 두 시점을 V2 HTTP POST로 등록하고 반환 ref 조회·grant·합성 GeoTIFF 바이트 저장·공용 seal로 봉인하는 테스트 전용 fixture를 추가했다. 기존 V1 fixture는 기본값으로 유지했다. 두 경로를 매개변수화한 Core HTTP→Analysis selector→실제 GIS 워커 `run_once`→result/evidence·원장 replay 통합 시험이 V2의 `COMPLETED + PROVISIONAL_ACCURACY_UNVERIFIED` 및 동일 결과를 확인했다. [두 파일의 고정 diff·해시](../../../.opencode/artifacts/first-product-completion-20260928/dsm-core-ingress-b3-review.json)는 독립 검토 **PASS**였고, 그대로 현재 작업본에 통합했다.

통합 후 HTTP/실행/API/replay 시험 **74 passed**, 두 소유 Python 파일 Ruff 및 `git diff --check` 통과(이전 pytest 임시 디렉터리 청소 경고 12건). 검사 보고서는 합성 helper가 기록하므로 독립 inspector의 파일 판독, 실제 Terra export, S3 PUT, 현장 정확도 수용 증거가 아니다. FPC-03/`EXT-VAL` 전체 완료로 판정하지 않는다.
