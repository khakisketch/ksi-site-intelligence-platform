# FPC-09A — 세 시점 주간 비교의 로컬 재사용 검증

**Plan ID:** FPC-09A-20260929. **상태:** Task A 로컬 검증 완료; FPC-09 고객 반복 업무 수용 미완. **Spec:** [ADR-KSI-037 D1](../../architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md), [첫 요청 계약 Weekly reuse](../../design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md), [완성 로드맵 FPC-09](2026-09-28-first-product-completion-roadmap.md). **Goal:** 같은 Site/WorkArea·고정 정책에서 V2 DSM-only `t0→t1`, 이어 `t1→t2`의 Core HTTP→GIS worker→결과·근거가 매번 새 입력 쌍에 결속되는지 시험한다.

**Architecture:** 기존 FPC-03B/B3 테스트 전용 로컬 fixture에 선택적 세 번째 DSM epoch만 추가한다. `t1`은 첫 비교의 current와 둘째 비교의 baseline에서 정확히 같은 봉인된 revision·DSM digest·input digest를 참조한다. 두 Analysis는 새 key와 pair-specific AP/NX identity/result를 가지며 WorkArea definition과 고정 profile은 재사용한다. 생산 파사드·계산·권한 로직을 시험용으로 바꾸지 않는다.

**Tech stack:** 기존 Core FastAPI, loopback object bytes, `ExternalAnalysisCoreClient` 및 실제 GIS `run_once`, pytest. 새 의존성 없음.

| 필수 항목 | 결정 |
| --- | --- |
| Requirement IDs | REQ-INT-101..104, FPC-09 선행 소프트웨어 근거, EXT-VAL-03/05. INV-017/018/040/051/053/060: WorkArea/epoch 정확한 결속, 시간 순서, mock-free 생산 경계, lineage, 조직 격리. |
| Owner module | 시험 fixture `tests/contract/analysis_api_local_fixture.py`; 새 통합 시험 `tests/contract/test_external_analysis_weekly_reuse.py`. 생산 결손이면 별도 task. |
| Acceptance criteria | DSM-only V2 세 시점 t0<t1<t2 등록·봉인·합성 inspection. 두 HTTP Analysis 요청과 실제 worker 실행 모두 `COMPLETED + PROVISIONAL_ACCURACY_UNVERIFIED`, 수치·근거 저장. 첫 current selector/input digest가 둘째 baseline과 동일. 동일 Site/WorkArea definition·policy/runtime profile, 서로 다른 Analysis ID, AP admission/계산 identity/result/report digest와 각각의 current input digest. 첫 결과 재조회·replay 불변; 둘째 자료가 첫 결과에 섞이지 않음. 잘못된 두 번째 key/pair 재사용은 기존 멱등 충돌 또는 별도 결과로만 처리. |
| Contracts affected | 없음; Core V2/Analysis 기존 wire를 검증. `mappingRecordDigest`가 현재 V2 경로에 없으면 임의로 만들지 않고 calculation identity/admission digest를 검증하며 별도 목표 gap으로 기록. |
| Reference assets | FPC-03B/B3 fixture/실 HTTP 워커 시험, FPC-04B history/replay 시험, `test_external_analysis_execution_integration.py` loopback GeoTIFF. Reference repos 불사용. |
| Adoption decisions | REUSE Core WorkArea, V2 ingress, Analysis API, fixed GIS worker, AP/NX durable stores. 세 시점 테스트 설정만 추가. |
| Files to change | `tests/contract/analysis_api_local_fixture.py`, 새 `tests/contract/test_external_analysis_weekly_reuse.py`만. 필요한 생산 코드 또는 기존 통합 시험 변경이 드러나면 멈춰 Lead에게 보고. |
| Tests | 세 epoch option 부재 RED → fixture/HTTP worker test GREEN → 기존 V1/V2 suite 및 replay, Ruff/diff-check. Fresh t2 byte digest, two identities/results, shared t1 input, restart. |
| HIL or real-device assumptions | 합성 GeoTIFF·합성 inspection; 독립 inspector·Terra·고객 현장 정확도/반복 업무 증거가 아니다. |
| License/data implications | 고객 자료/외부 전송 없음. |
| Rollback | 테스트 fixture option/새 파일 제거; 생산 이력 변경 없음. |

## Task A — 세 시점 Core→worker 연속 요청

- [ ] 새 시험에서 선택적 t2 fixture selector를 요구해 RED를 확인한다. 기존 두 시점/V1 기본 경로는 그대로 유지한다.
- [ ] 같은 WorkArea에 V2 DSM-only t2를 새 WorkOrder·새 capture interval로 V2 HTTP 등록·반환 ref 조회/grant/바이트 업로드/seal하고, 기존 합성 Core inspection을 붙인다. t1의 기존 selector·DSM 바이트를 재등록하지 않는다.
- [ ] 동일 Core HTTP/loopback 객체 서버와 실제 GIS worker로 두 요청을 차례로 완료시키고, API detail/result/evidence의 IDs, input digest, profile/WorkArea digest, cut/fill/net 및 잠정 제한을 확인한다. 두 번째 요청은 반드시 t1→t2이며 첫 결과와 계산 authority를 재사용하지 않아야 한다.
- [ ] 두 Analysis를 journal replay 후 재조회해 같은 결과 ID·digest·근거를 확인한다. 같은 idempotency key에 바뀐 pair를 넣는 음성 경로도 확인한다. focused tests, Ruff/diff-check 실행. 생산 코드 결손이면 우회하지 않고 멈춘다.

검토 초점: `t1` 재등록으로 생기는 가짜 재사용, 새 pair에 이전 calculation authority를 쓰는 경우, 첫 결과가 둘째 실행으로 바뀌는 경우, capture interval 역전, replay 뒤 input digest가 달라지는 경우. 이 task는 FPC-04..08 전체 선행 수용이나 FPC-09 고객 반복 업무 수용을 대체하지 않는다.

커밋·PR·배포·고객 자료·자격증명 변경 없음.

## Task A 로컬 근거 — 2026-09-29

세 번째 V2 DSM-only 관측을 별도 WorkOrder에서 HTTP 등록·조회·바이트 업로드·봉인하고, 합성 검사 기록을 연결했다. 같은 Core HTTP/실제 GIS worker 경로에서 `t0→t1`, `t1→t2`가 각각 잠정 수치로 완료됐다. `t1` selector/DSM sha256/input digest가 두 분석에서 같고, WorkArea definition·정책·런타임은 재사용됐다. 서로 다른 admission/계산 identity/요청 ID/결과 ID/report digest, 같은 key에 다른 pair의 409, 첫 결과 불변, 두 결과의 replay 동일성도 확인했다.

첫 독립 검토는 fixture가 t1/t2 검사 시각을 미래로 기록하고 기본 두 시점 fixture까지 바꾸는 문제로 `CHANGES_REQUIRED`였다. 세 시점에서는 HTTP 봉인·정책 승인 뒤 실제 시각의 합성 검사를 10초 임대보다 긴 11초 간격으로 수행하고, 캡처→봉인→검사→요청 순서를 검사했다. 기본 V1/V2 두 시점 시각은 원래대로 유지한다. [수정된 두 파일의 고정 diff·해시](../../../.opencode/artifacts/first-product-completion-20260928/three-epoch-weekly-review-r2.json)는 독립 재검토 **PASS**였고 현재 작업본에 그대로 통합했다. 통합 HTTP/AP/NX/replay **40 passed**, Ruff·`git diff --check` 통과(기존 pytest 임시 디렉터리 청소 경고 12건).

이 근거는 합성 DSM·합성 inspection의 로컬 소프트웨어 검증이다. FPC-04..08 선행 수용, 실제 Terra 자료, 독립 검사 운영 호스트, 고객의 두 주기 업무/준비 시간, UI·Codex MCP 동등성을 입증하지 않으므로 FPC-09 전체는 미수용이다. 현재 V2 Analysis에는 V1 external quantitative mapping의 `mappingRecordDigest`와 동일한 필드가 없으며, 이 시험은 실제 존재하는 pair-bound admission/calculation identity로 분리를 검사했다. 별도 durable mapping/template 요구는 FPC-09 전체 수용에서 판단한다.
