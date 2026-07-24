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
  _강제: CoverageReport 완료 게이트 (coverage-report 스키마·미구현)._
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

## 이벤트·증거

- **INV-030** Evidence Clip은 Candidate/High/Critical 전후 3/5/10초. 저장 실패는 숨기지 않고
  `EVIDENCE_DEGRADED`로 기록한다.
  _강제: mission-contract·event-bundle 스키마 const + Evidence Builder 테스트._
- **INV-031** Detector 결과를 Event로 직접 저장하지 않는다
  (Detection → Observation → Candidate → … 상태머신 경유).
  _강제: event-contracts 상태전이 검증 (P0-1/P0-6)._

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
  _강제: Dataset License Ledger (미구현, Scout 정책 계승)._
