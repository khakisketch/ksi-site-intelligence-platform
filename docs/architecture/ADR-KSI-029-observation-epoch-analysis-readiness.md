# ADR-KSI-029 — Observation Epoch와 증거 기반 Analysis Readiness

- Status: Accepted
- Date: 2026-08-27
- Requirements: REQ-WRK-101, REQ-ACQ-102, REQ-INT-101/102/103, REQ-SEC-101
- Invariants: INV-001/002, INV-010/011/012, INV-017/018, INV-020, INV-040/041,
  INV-050/051, INV-060/061
- Related: ADR-KSI-019, ADR-KSI-023, ADR-KSI-026, ADR-KSI-027
- Supersedes: 없음. WorkOrder 및 Mission execution lifecycle의 기존 의미를 즉시 바꾸지 않는다.

## Context

제품의 첫 유료 workflow는 반복 관측에서 분석 가능한 데이터를 얻고, 그 결과를 다음
관측·사람 결정으로 닫는 일이다. CoverageReport는 임무 완료의 권위이고, SourceMedia,
ProcessingJob, SpatialModel은 각각 필요한 lineage를 이미 가진다. 그러나 이 증거들은
서로 다른 시간과 경로에서 도착한다. 따라서 ProcessingJob의 성공 또는 비행 종료
하나만으로 "분석 가능"을 말하면 coverage gap, 미디어 누락, capture-time 충돌, 품질
부족과 같은 중요한 실패를 숨길 수 있다.

`IN_FLIGHT` 같은 서버 추정 상태를 추가해 문제를 풀지 않는다. 서버가 확실히 아는 것은
Edge/Pilot의 receipt와 비행 후 수신한 증거이며, 실제 비행 상태·저수준 안전은 기존
DJI와 조종자 경계에 남는다.

## Decision

### D1 — Observation Epoch는 WorkOrder cycle의 분석 단위다

`ObservationEpoch`는 반복 비교·처리·분석에 쓰는 논리 단위다. MVP v1의 identity는
`workOrderId + cycleNumber`에서 결정적으로 도출하며, cardinality를 다음으로 고정한다.

```text
1 WorkOrder cycle → 1 Mission/Sortie → 1 SourceMediaBundle → 1 ProcessingJob
```

이는 "현실에서 추가 sortie가 절대 없다"는 주장이 아니다. v1의 자동 집계가 여러
sortie를 조용히 하나의 비교 기준으로 합치지 않는다는 범위 제약이다. 다중 sortie를
허용하려면 별도 epoch v2 계약, per-sortie coverage/quality, 시간 정책, 병합·누락
규칙과 HIL/Field evidence를 먼저 추가한다.

### D2 — AnalysisReadiness는 별도의 파생 projection이다

`AnalysisReadinessView`는 WorkOrder/Mission/Processing의 기존 원장을 대체하는 mutable
workflow state가 아니다. 다음의 결과와 이유를 함께 투영한다.

| 결과 | 대표 reason code |
|---|---|
| 아직 준비되지 않음 | `WAITING_COVERAGE`, `WAITING_MEDIA`, `WAITING_PROCESSING` |
| 증거 gap 또는 거부 | `COVERAGE_GAP`, `CAPTURE_QUALITY_GAP`, `INTEGRITY_GAP`, `CAPTURE_TIME_INCOMPLETE`, `TEMPORAL_POLICY_UNDECLARED`, `TEMPORAL_COHERENCE_GAP`, `PROCESSING_FAILED` |
| 준비됨 | `READY` |

실제 contract enum은 이 목록을 versioned·typed하게 고정한다. 새 이유가 생기면
unknown을 `READY`로 해석하지 않는다. `READY`에는 해당 evidence object ID, digest,
capture window, policy version과 projection version을 함께 표시한다.

### D3 — READY의 최소 증거는 모두 충족되어야 한다

v1에서 `READY`는 적어도 다음이 모두 참일 때만 가능하다.

1. 해당 Mission의 허용된 CoverageReport가 INV-010 완료 기준을 충족한다.
2. CaptureQualityReport가 존재하고 계약상 허용된 capture quality를 보고한다.
3. sealed SourceMediaBundle의 파일 수·digest·권리/lineage와 capture-time window가
   검증되어 있다.
4. WorkOrder cycle의 temporal policy가 선언되어 있고, capture window가 정책을 만족한다.
5. ProcessingJob이 성공했으며 INV-051의 source authority artifact를 가진다.
6. 해당 제품 분석이 별도의 재구성 품질 근거를 요구하면 그 policy-defined gate도 통과한다.

어느 입력이 아직 없거나 충돌하면 projection은 latest-known evidence를 보존한 채
not-ready reason을 반환한다. Edge의 CaptureQualityReport는 중요한 입력이지만, 그것만으로
Core가 최종 분석 준비를 확정하지 않는다.

### D4 — temporal policy는 명시적이며 보수적으로 해석한다

v1 WorkOrder의 versioned policy는 적어도 허용 가능한 capture window span을 표현한다.
기존 Schedule에는 이 필드를 묵시적으로 상속시키지 않는다. 향후 비교 대상 epoch 사이의
최대 간격·동일 현장 기준이 필요한 분석은 그 분석 policy가 추가로 선언한다.

- policy가 없으면 `TEMPORAL_POLICY_UNDECLARED`다;
- capture time이 unavailable/conflict면 `CAPTURE_TIME_INCOMPLETE`다;
- span을 넘거나 sortie가 v1 cardinality를 넘으면 `TEMPORAL_COHERENCE_GAP`이다.

processing 완료 시각은 capture time의 대체값이 아니다. 원본 미디어 bytes, EXIF/XMP 등
검증된 capture-time lineage를 우선하며, native container는 변환하지 않는다.

### D5 — Edge의 역할은 provisional capture evidence와 제한된 recovery다

Manifold는 서명된 Capture Policy 안에서 관측·품질 판단을 내고, 필요한 evidence를
CaptureQualityReport로 올린다. 재촬영은 `same pose → bounded gimbal adjustment →
preauthorized viewpoint` 순서로 제한되며, 새 좌표·경로·안전명령을 LLM이나 Core가
즉흥 생성하지 않는다. 이 ADR은 비행 제어·짐벌 실행 권한을 열지 않는다.

### D6 — WorkOrder lifecycle와 Dashboard는 단계적으로 바꾼다

ADR-KSI-026 D8의 `REVIEW_READY` lifecycle 의미는 이 ADR만으로 변경하지 않는다.
먼저 AnalysisReadiness를 additive shadow projection으로 노출하고, 기존 처리·검토
전이와의 불일치를 replay 및 운영 검토로 확인한다. 그 뒤에만 사람에게 보이는 gating
문구나 lifecycle 변화를 별도 승인으로 승격한다.

Dashboard는 Pilot 2가 아니라 Operations Console의 Site/WorkOrder에 readiness와 evidence
gap을 표시한다. `READY`가 아니면 "분석 불가"라는 모호한 경고 대신, 어떤 evidence가
부족한지와 가능한 다음 사람 행동을 표시한다.

## Consequences

- "한 번의 비행"은 단일 sortie를 우선하는 v1 제품 범위이며, 결과는 분석 가능 또는
  명시적 gap으로 판정된다. 무조건 성공을 약속하는 표현이 아니다.
- 기존 capture-time, SourceMediaBundle, ProcessingJob lineage를 재구현하지 않고
  readiness projection의 입력으로 재사용한다.
- 새 CaptureQualityReport store/API와 readiness projection은 Core의 조직·site scope를
  따라야 하며, Dashboard가 추측으로 상태를 만들면 안 된다.
- 정확도·reconstruction quality가 아직 검증되지 않은 경우 `READY`가 그것을 상용
  정확도 주장으로 승격하지 않는다. INV-024와 equipment support evidence는 독립으로 유지한다.

## Acceptance and rollback

- Acceptance: contract round-trip, organization/site isolation, evidence 순서가 뒤바뀐
  replay, 각 reason code, policy 미선언/시간 충돌/미디어 누락/coverage gap/processing
  실패, Dashboard READY/GAPS projection을 검증한다.
- HIL/Field: actual PSDK media, Pilot 2 execution, CaptureQuality producer와
  multi-sortie acceptance는 별도 HIL/Field gate다. mock 또는 unit test만으로
  capability를 VERIFIED로 승격하지 않는다.
- Rollback: readiness는 additive shadow projection으로 먼저 배포한다. projection/UI를
  독립 feature flag로 끌 수 있으며, 기존 WorkOrder·CoverageReport·Processing 원장은
  변경하거나 삭제하지 않는다.

## 2026-09-06 ADR-KSI-035 scope amendment

The current `AnalysisReadiness` implementation remains its existing global fail-closed projection;
this amendment does not claim it already evaluates every dependent claim separately. ADR-KSI-035
requires a future additive `ClaimScopedAssessment`: missing Pilot final-plan or actual-flight
evidence then blocks only claims that require those facts, while raw registration/reconstruction
may proceed when their own ingress, integrity and processing prerequisites hold. INV-020/024/051/053
eligibility remains independent, and no postflight assessment retroactively authorizes flight.
