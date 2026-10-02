# FPC-04B — 완료 후 평가 변경의 현행 적합성 검증

**Plan ID:** FPC-04B-20260929. **상태:** Task A 로컬 검증 완료; FPC-04 전체·고객 수용 미완. **Spec:** [첫 요청 계약](../../design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md)의 Accuracy evidence/Outcomes/Acceptance boundary. **Goal:** 이미 기록된 V2 잠정 계산 뒤 동일 DSM에 실패 평가가 들어와도 원장 결과가 바뀌지 않고, 현행 API는 수치를 숨기며 새 분석 요청은 실패 이유를 명시하는지 확인한다.

**Architecture:** FPC-03B의 DSM-only Core HTTP/GIS worker fixture를 사용한다. 완료 이후 기존 Core evidence-validation 경로로 현재 DSM에 실패 평가를 기록한다. AP/NX 역사 기록과 현행 읽기, 새 Analysis 요청을 각각 관측하며 파사드에 새 판정 로직을 추가하지 않는다. 생산 코드 결손이 드러나면 테스트에서 우회하지 않고 별도 수정 범위를 정한다.

**Tech stack:** FastAPI/TestClient, 실제 로컬 GIS worker, Core JSONL journals, pytest. 새 외부 의존성 없음.

| 필수 항목 | 결정 |
| --- | --- |
| Requirement IDs | REQ-INT-101..104, EXT-VAL-03/04/05, FPC-04; INV-017/018/040/050/051/053/054/055/060/061의 정확한 입력 결속·이력 불변·현행 조회 차단. |
| Owner module | 시험 fixture `tests/contract/analysis_api_local_fixture.py`, HTTP 통합 시험 `tests/contract/test_external_analysis_http_integration.py`. 생산 결손은 별도 task. |
| Acceptance criteria | 합성 DSM 두 시점의 잠정 결과 `COMPLETED`/stable report를 확인한 후 현재 DSM의 Core `REJECTED` 평가 추가. 동일 Analysis 조회는 실행 이력 `COMPLETED`를 보존하되 `REASSESSMENT_REQUIRED` 또는 근거 있는 더 구체적 부적합 상태로 수치를 숨긴다. 새 key 요청은 `NOT_STARTED + REMEDIATION_REQUIRED`와 실패 근거를 반환한다. 원래 NX report/evaluation snapshot은 불변이고 replay 후에도 같다. |
| Contracts affected | 기본적으로 없음; 기존 V2 AP/NX와 Analysis API 계약을 검사한다. Contract gap이면 멈추고 보고. |
| Reference assets | FPC-03B/B3 실제 워커 통합 시험, FPC-04A 실패 평가 helper, Core `ExternalRelativeVolumeAnalysisStore.get_current_for_read`, `ExternalRelativeVolumeCalculationStore.get_current`. |
| Adoption decisions | REUSE Core 평가·현재성·원장 및 고정 GIS worker. 기존 결과를 덮어쓰지 않는다. |
| Files to change | 지정된 두 시험 파일만; 다른 파일 필요 시 Lead에게 보고. |
| Tests | 완료 후 실패 평가에 대한 RED→GREEN; focused HTTP/AP/NX/replay, Ruff/diff-check. 평가가 없던 기존 잠정 경로와 V1 기본 fixture 회귀. |
| HIL or real-device assumptions | 합성 GeoTIFF/checkpoint/inspection; 독립 검사 운영 호스트·Terra·측량 정확도 증거가 아니다. |
| License/data implications | 고객 자료 없음, 반출 없음. |
| Rollback | 추가 fixture/test 제거; 생산 이력 변경 없음. |

## Task A — 후행 실패 평가와 이전 결과

- [ ] 완료된 V2 HTTP 분석의 결과 ID/report digest와 AP/NX 역사 record를 확보한 뒤, 같은 현재 DSM 바이트에 Core evidence-validation의 실패 평가를 붙이는 테스트를 작성해 RED를 확인한다.
- [ ] fixture가 필요하면 시험 전용 평가 추가 메서드만 두고, 기존 V1/V2 fixture 기본 경로와 실 GIS worker 경로를 유지한다. 평가에는 `_validate_evidence(..., checkpoint_count=1)`을 사용하며 Core `REJECTED`를 확인한다.
- [ ] 동일 ID의 detail/result/evidence 조회에서 `COMPLETED` 이력은 유지되고 현행 수치가 `null`인지, 새 key의 요청에서는 `REMEDIATION_REQUIRED`와 현재 epoch `FAIL`이 보이는지 검증한다. NX 원장 역사 report digest는 처음 값과 같아야 한다. 재시작/replay 후에도 동일하게 검사한다.
- [ ] HTTP/worker/replay focused tests, Ruff/diff-check를 실행한다. 실제 계약 위반이 확인되면 테스트만 녹색으로 만들기 위한 workaround 없이 정지·보고한다.

검토 초점: 현행 조회가 오래된 숫자를 노출하는지, 후행 실패가 근거 부재로 강등되는지, 과거 원장 report/evaluation snapshot을 덮어쓰는지, 새 요청이 이전 계산 authority를 재사용하는지, 재시작 뒤 판단이 달라지는지. 이 단위는 현재 epoch 후행 실패만 다루며 baseline 실패·상충·통과 평가는 FPC-04 전체 매트릭스에 남는다.

커밋·PR·배포·권한 변경 없음. Task A 검증은 FPC-04/EXT-VAL 전체 수용이 아니다.

## Task A 로컬 근거 — 2026-09-29

V2 DSM-only의 실제 GIS 워커 잠정 결과를 만든 뒤 동일한 현재 DSM에 기존 Core 경로로 합성 checkpoint 평가 실패를 추가했다. 기존 AP 평가 스냅샷과 NX report digest는 변하지 않았고, 동일 Analysis의 현재 detail/result/evidence는 실행 `COMPLETED`를 유지하면서 수치를 숨겼다. 새 key의 Analysis는 `NOT_STARTED + REMEDIATION_REQUIRED`와 현재 epoch `FAIL`을 반환했다. 원장 replay 뒤에도 같은 판단을 확인했다. 별도 시나리오에서는 평가가 없는 V2 잠정 수치가 재시작 뒤 detail/result/evidence/alias에서 유지되는지 확인했고 V1도 회귀 검사했다.

첫 독립 검토에서 V2의 기존 무평가 replay 검증을 새 후행 실패 검증이 대체한 coverage 회귀를 찾아 `CHANGES_REQUIRED`였다. 두 V2 사례를 분리한 [최종 고정 diff·해시](../../../.opencode/artifacts/first-product-completion-20260928/v2-late-evaluation-review-r2.json)는 재검토 **PASS**였고 정확한 두 파일을 통합했다. 통합 후 HTTP/AP/NX/replay **37 passed**, Ruff·`git diff --check` 통과(기존 pytest 임시 디렉터리 청소 경고 12건). 실제 Terra/독립 inspector/현장 정확도·고객 수용 증거는 아니다.
