# KSI Site Intelligence — 도메인 불변식 (정본)

> 이 문서가 도메인 불변식의 SSOT다. `AGENTS.md`, `CLAUDE.md`, `docs/00_READ_FIRST.md`는
> 이 문서를 참조한다. 근거: PRODUCT_CONSTITUTION, FINAL_DECISION_LEDGER v1.0, MASTER_PRD v3.0
> (동결), 참고 레포 감사(2026-07-24). 변경은 대표자 승인 필요.

각 불변식은 `강제 지점`(코드·게이트에서 어디가 막는가)을 가진다. 강제 지점이 "미구현"이면
해당 기능 구현 시 테스트가 함께 생겨야 한다.

## 제어 경계

- **INV-001** 서버(Core/Dashboard)는 프레임별(10Hz 이상) 위치·속도·자세 명령을 전송하지 않는다.
  비행 중 실시간 판단은 Manifold Edge 소유, 저수준 안전은 DJI Flight Controller 소유.
  _강제: 아키텍처 리뷰 + edge command 계약(TTL/authorization) 테스트._
- **INV-002** LLM은 실행 가능한 비행좌표·안전제어 명령을 생성하지 않는다. LLM 출력이
  Flight Command로 직접 연결되는 경로를 만들지 않는다.
  _강제: 코드리뷰 게이트 + command 발행 경로에 LLM 산출물 타입 유입 금지._
- **INV-003** `references/repos/` 직접 runtime import·의존 금지 (읽기 전용 참고).
  _강제: `scripts/check_no_reference_imports.sh` (import/manifest/symlink/dirty 4중), CI 상시._

## 임무·커버리지

- **INV-010** 임무 완료 기준: 필수 위험구역 100% · 필수 자산/표면 100% · 접근가능 일반영역
  ≥95%. 경로 완료 ≠ 임무 완료. 모든 미관찰 Cell은 원인코드와 후속처리를 가진다.
  **완료 판정의 권위는 비행 후 CoverageReport 하나다** — 발급 시점의
  `plannedCoverageRatio` 는 스와스 가정 하의 계획 추정치이고 완료 근거가 아니다
  (MASTER_PRD §15.5). 서버가 계획값으로 완료를 주장하면 실제 관찰(가림·접근불가·
  배터리 한계·이벤트 분기 공백)이 기록에서 사라진다.
  _강제: `ksi_core.coverage_reports` — 비행 후 보고 수신 시 ① COMPLETED 주장이
  요약 비율로 뒷받침되는지 ② 사유 없는 미관찰 Cell 이 없는지 ③ 관찰 증거가 있는지
  ④ 요약이 자체 모순인지(전 구역 100% 인데 미관찰 Cell 존재) ⑤ 발급된 임무·site
  일치인지를 검사한다. **재생은 ①~④만 재검사한다** — ⑤(임무 대조)는 수신 시점의
  게이트이고, 이미 받은 기록을 나중에 부정하지 않는다(임무 원장이 따로 회전·보관
  정책을 타므로 재생 시점에 없을 수 있다). 발급 전 사전 점검은 `mission_plans` 소관.
  **미완**: Cell 분류(위험구역/자산/일반)를 서버가 갖고 있지 않아 요약 비율 자체를
  재계산하지는 못한다 — 기체 보고를 검증하되 재현하지는 않는다._
- **INV-011** Mission Contract는 Versioned·Signed 실행계약이다. 미서명·digest 불일치·
  schemaVersion 불일치·TTL 만료 계약은 거부된다.
  _강제: `ksi_mission_contracts` 서명 검증 (ADR-KSI-002, P0-1 테스트)._
- **INV-012** 서버통신 단절 중에는 유효 Mission Contract + 안전조건 유지 시에만 임무를
  계속한다. RC Command Link 단절은 DJI Flight Controller 정책을 따른다.
  _강제: HIL 시나리오 (REQ-EDGE-101/102, 하드웨어 게이트)._
- **INV-013** 배터리 귀환은 예상귀환 에너지 + 현장 Reserve(기본 30%)이며, DJI의 더 보수적인
  보호판단을 무시할 수 없다.
  _강제: mission-contract 스키마 const + HIL (REQ-SAFE-101)._

## 인지·공간

- **INV-014** 비행 봉투의 `maxAltitudeM` 은 규제 상한(150m — 항공안전법 일반
  비행제한 고도)을 넘을 수 없다. 서버 고정 안전상수이며 요청·현장설정으로 완화되지
  않는다. 예외 승인 운용이 필요하면 상수 자체를 대표자 결정으로 고친다.
  _강제: `FlightEnvelope` 모델 검증 (ADR-KSI-011 D1, `_ABSOLUTE_MAX_ALTITUDE_M`)._
- **INV-015** 매핑 계열 임무(lawnmower)는 진행방향 촬영 간격 없이 발급되지 않는다.
  스캔선 끝점만 촬영하면 전방 겹침이 0 이라 정사영상·3D 재구성이 성립하지 않는다.
  간격은 카메라 스펙(`route.camera`)으로 **서버가 계산**하는 것이 정본 경로이고,
  중복도 하한(전방 0.6·측면 0.5)을 강제한다. 직접 지정 경로에서는 진행방향 간격이
  측면 간격 이하여야 하고 측면 간격이 고도×1.5 를 넘을 수 없다 — 그 상한은 물리적
  불가능의 증명이 아니라 정책값이다(ADR-KSI-011 D2·D3).
  _강제: `mission_plans.build_mission_plan` 422 + `coverage.lawnmower_route`
  (ADR-KSI-011 D2)._

- **INV-020** 모든 세계좌표·Geometry는 CRS, 수직기준, unit, timestamp, uncertainty를 가진다.
  CRS·수직기준이 다른 산출물을 직접 비교·병합하지 않는다.
  _강제: 계약 모델 필수 필드 + contract test (P0-1, Stage C WorldEntity)._
- **INV-021** 위치 불확실성을 포함해도 위험조건이 유지될 때만 Confirmed로 승격한다.
  불확실성이 크면 SUSPECTED/UNVERIFIABLE로 유지한다.
  _강제: geo-core 불확실성 전파 + 이벤트 승격 로직 테스트 (P0-4/P0-6)._
- **INV-022** 단일 프레임으로 사건을 확정하지 않는다 (temporal 누적 필수).
  _강제: Replay 재현 테스트 (P0-6)._
- **INV-023** Geo 투영은 외삽하지 않는다. 텔레메트리 gap 초과·지평선 위 광선 등 신뢰 불가
  조건에서는 결과 대신 typed 실패(사유 포함)를 반환한다 (fail-closed).
  _강제: InterpolationResult/ProjectionResult 타입 + 골든 테스트 (P0-2/P0-4)._
- **INV-024** RTK Fix는 정확도 신호이지 절대정확도 검증이 아니다. 독립 checkpoint 없이
  절대 RMSE를 표시하지 않는다.
  _강제: Spatial Quality Report 로직 (Terra 정직성 계승, 미구현)._
- **INV-025** `WorldEntity.uncertainty.localization_state = CONFIRMED`는
  관측 집합 전체가 `CALIBRATED_POSE` 시점 증거를 가지며, 서로 다른 보정
  Camera Pose 참조가 2개 이상일 때만 허용한다.

  `SPATIAL_BIN`, `UNKNOWN`, 미선언 시점 증거는 공분산·관측 수와 무관하게
  CONFIRMED 승격 근거가 될 수 없으며 결과를 최대 `LIKELY`로 제한한다.
  증거 등급과 식별자 형식이 충돌하면 fail-closed로 거부한다.

  서로 다른 Pose ID는 필요조건일 뿐 실제 기하적 기선을 증명하지 않는다.
  Production 승격 전에는 Calibration Registry 해석과 최소 baseline 검증을
  추가로 통과해야 한다.

  _강제: `ViewpointEvidenceKind`, Observation 시점 증거 검증,
  `assemble_world_entity()` localization gate,
  `tests/replay/test_world_entity_assembly.py`.
  HIL 추가 강제: Camera Pose Registry 해석 + 실제 baseline 검증._

## 이벤트·증거

- **INV-030** Evidence Clip은 Candidate/High/Critical 전후 3/5/10초. 저장 실패는 숨기지 않고
  `EVIDENCE_DEGRADED`로 기록한다.
  _강제: mission-contract·event-bundle 스키마 const + Evidence Builder 테스트._
- **INV-031** Detector 결과를 Event로 직접 저장하지 않는다
  (Detection → Observation → WorldEntity/Candidate → … 상태머신 경유).

  Detection의 분류 Class를 상수값으로 대체하거나 중간 단계에서 버리지 않는다.
  원시 모델 Class는 Versioned Ontology를 통해 Canonical Entity Class로 변환되고,
  Observation·WorldEntity 계보를 따라 보존되어야 한다.

  동일 Track에서 서로 충돌하는 Canonical Class는 fail-closed로 거부하며,
  Event Type은 WorldEntity Class와 호환될 때만 생성한다. Class 불일치가
  Person 등 더 강한 의미로 fallback되어서는 안 된다.

  _강제: event-contracts 상태전이 검증 (P0-1/P0-6) + Detector Adapter ontology
  mapping, class-aware Tracker, Observation class lineage, WorldEntity assembly
  conflict gate, Event/Class compatibility test (F13, 2026-07-27)._

## 데이터·모델·정직성

- **INV-040** Production에서 mock/placeholder/static always-go 금지. 외부 의존 실패는
  데모 데이터로 가리지 않고 fail-closed로 정직하게 드러낸다.
  _강제: 코드리뷰 게이트 + production profile 테스트 (미구현)._
- **INV-041** `CapabilityVerificationState`(VERIFIED/SPIKE_REQUIRED/BLOCKED — 장비기능 검증)와
  `EquipmentSupportLevel`(DATASET_AVAILABLE→…→PRODUCTION_SUPPORTED — 장비 지원단계)은 별개
  개념이며, PRODUCTION_SUPPORTED만 상용 안전지원으로 표시한다. 미검증 기능은 UX에 노출하지
  않는다.
  _강제: Capability Registry 노출 규칙 테스트 (P0-5)._
- **INV-042** 서명되지 않았거나 버전이 불일치하는 Model Pack·Edge Map Package를 실행하지
  않는다. 모든 결과는 Mission/Model/Policy/Calibration Version 계보를 가진다.
  _강제: event-bundle lineage 필수 필드 (P0-1) + Edge 로더 (미구현)._
- **INV-043** NC·권리불명 데이터는 상용 학습에서 제외한다. Dataset/Model은 라이선스·출처
  계보를 Registry에 고정한다.
  _강제: `docs/models/MODEL_REGISTRY.yaml`(revision·sha256 계보 SSOT) +
  `ksi_perception.registry`(digest 대조·BLOCKED 계보 거부·잉여파일 거부) +
  `tests/contract/test_model_registry.py`. Dataset 쪽 Ledger 는 자체 학습 데이터
  확보 시 확장(MODEL-B1-001 production_gate)._
