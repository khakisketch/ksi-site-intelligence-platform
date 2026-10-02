# FPC-04A — V2 DSM의 알려진 실패 근거 차단 검증

**Plan ID:** FPC-04A-20260929. **상태:** Task A 로컬 검증 완료; FPC-04 전체·고객 수용 미완. **Spec:** [첫 요청 계약](../../design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md), 특히 Accuracy evidence/Acceptance boundary. **Goal:** DSM-only V2에서 검사점 평가 부재와 알려진 평가 실패가 동일한 잠정 상태로 합쳐지지 않음을 실제 Core Analysis HTTP 경로로 검증한다.

**Architecture:** 기존 [FPC-03B](2026-09-28-dsm-only-core-ingress.md)의 시험 전용 fixture가 봉인한 DSM에 기존 Core evidence-validation 경로로 실패 평가를 추가한다. Analysis 파사드의 새 판정이나 새 계산 엔진을 만들지 않는다. 알려진 실패가 `NOT_STARTED + REMEDIATION_REQUIRED`, 구조화된 사유, `result=null`을 만들고 워커 작업을 생성하지 않는지 확인한다. 합성 평가와 합성 inspection은 운영 정확도 근거가 아니다.

**Tech stack:** 기존 FastAPI/TestClient, Core journals, pytest. 새 의존성 없음.

| 필수 항목 | 결정 |
| --- | --- |
| Requirement IDs | REQ-INT-101..104, EXT-VAL-03/04, FPC-04; INV-017/018/040/050/051/053/054/055/060/061 중 입력 결속·평가 분리·이력 불변. |
| Owner module | `tests/contract/analysis_api_local_fixture.py` 시험 setup, `tests/contract/test_external_analysis_http_integration.py` HTTP 판정 시험. 생산 소유자는 결손 확인 뒤 별도 범위 지정. |
| Acceptance criteria | 동일한 V2 DSM-only fixture에서 평가 없음은 기존 잠정 수치 시험 유지; 현재 epoch의 실패한 checkpoint evaluation이 있으면 새 Analysis 요청은 `NOT_STARTED + REMEDIATION_REQUIRED`, 숫자 `null`, 코드가 있는 blocker, 계산 job 부재. 동일 결과 조회·replay가 역사적 판정을 보존. V1 fixture 기본 동작 불변. |
| Contracts affected | 없음. 기존 Core V2 admission과 Analysis API 계약을 시험한다. |
| Reference assets | FPC-03B/B3 fixture/test, `test_external_quantitative_production_flow.py`의 `_validate_evidence(..., checkpoint_count=1)`. Reference repos 사용 없음. |
| Adoption decisions | REUSE Core evidence validation, assessment, facade, worker queue. 시험 fixture option만 추가. 생산 결손 발견 시 우회하지 않고 보고. |
| Files to change | `tests/contract/analysis_api_local_fixture.py`, `tests/contract/test_external_analysis_http_integration.py`만. |
| Tests | 실패 평가 option 없는 RED 시험 → 최소 fixture 확장 → V1/V2 HTTP/replay focused suite, Ruff/diff-check. 검사점 부재 잠정 결과와 평가 실패 보완 상태를 같은 파일에서 대조. |
| HIL or real-device assumptions | 없음. 합성 checkpoint/inspection/GeoTIFF는 독립 검사 호스트·Terra·측량 정확도 수용 아님. |
| License/data implications | 고객 데이터 없음; AI 반출·고객 승인은 범위 밖. |
| Rollback | 시험 fixture option/시험 제거. 기존 V1/V2 Core 기록 변경 없음. |

## Task A — 실패 평가 HTTP 경로

- [ ] V2 fixture에 `failed_checkpoint_current: bool = False` 옵션을 요청하는 새 시험을 작성해 부재로 인한 RED를 확인한다. `v2_dsm_only=False`와의 조합은 명시적으로 거절한다.
- [ ] Core의 기존 `_validate_evidence`를 현재 DSM subject에만 `checkpoint_count=1`로 호출한다. 실패가 실제 `REJECTED` terminal record인지 확인하고, synthetic-only 범위를 주석에 명시한다.
- [ ] Analysis POST 응답과 detail/result/evidence 조회의 `NOT_STARTED`, `REMEDIATION_REQUIRED`, `result=null`, 실패 사유 코드를 확인한다. Worker claim/run은 결과를 만들지 않아야 한다. 같은 idempotency key 재시도·원장 replay가 과거 판단을 지키는지도 확인한다.
- [ ] `uv run --package ksi-core pytest -q tests/contract/test_external_analysis_http_integration.py tests/contract/test_external_analysis_api.py tests/replay/test_external_analysis_api_replay.py` 및 Ruff/diff-check. 생산 코드 결손이 드러나면 이 task를 멈추고 변경 없이 Lead에게 정확한 실패를 보고한다.

검토 초점: 실패 평가가 임시적 증거 부재로 취급되는지, 첫 시점 실패가 누락되는지, 현재 epoch만 검사하는 오류가 있는지, 재시도에서 같은 분석 ID가 다른 판정으로 바뀌는지, 기존 잠정 결과까지 수정되는지. 이 단위에서 검사 대상은 현재 epoch 하나이며 다른 경우는 후속 FPC-04 증거로 남긴다.

커밋·PR·배포·운영 권한 변경은 승인 범위에 포함되지 않는다. FPC-04/`EXT-VAL` 전체 수용으로 판정하지 않는다.

## Task A 로컬 근거 — 2026-09-29

fixture 옵션 부재로 실패한 RED 뒤, V2 현재 DSM에 기존 Core evidence-validation 경로의 합성 checkpoint 1개를 연결했다. Core는 `REJECTED / CHECKPOINT_COUNT_OUT_OF_RANGE`를 기록했고 Analysis HTTP는 `NOT_STARTED + REMEDIATION_REQUIRED`, 수치 `null`, 구조화된 blocker와 baseline `UNASSESSED`/current `FAIL` 평가를 반환했다. worker 작업은 발행되지 않았고 동일 키 재시도·원장 replay에서 같은 Analysis ID와 차단 판단이 유지됐다. 무평가 V2의 잠정 수치 및 V1 기본 fixture는 그대로 시험했다.

[두 파일의 고정 diff·해시](../../../.opencode/artifacts/first-product-completion-20260928/v2-failed-evidence-review.json)는 독립 검토 **PASS**였고, 그대로 현재 작업본에 통합했다. 통합 후 지정 HTTP/API/replay 시험 **33 passed**, 두 파일 Ruff와 `git diff --check` 통과(기존 pytest 임시 디렉터리 청소 경고 12건). 합성 checkpoint/inspection 증거이며 실제 검사자·Terra·현장 정확도를 입증하지 않는다. Baseline 실패, 상충, 뒤늦은 평가의 현행 적합성 변경 등 FPC-04 전체 매트릭스는 별도 확인이 필요하다.
