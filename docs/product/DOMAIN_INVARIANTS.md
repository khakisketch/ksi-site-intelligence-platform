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
  ④ 요약이 자체 모순인지(전 구역 100% 인데 미관찰 Cell 존재) ⑤ 칸 총수<2 인데
  비율이 0과 1 사이(산술적 불가능, 2026-08-18) ⑥ 발급된 임무·site 일치인지 ⑦
  accessibleGeneralRatio 가 발급 경로의 plannedCoverageRatio(이상적 조건 상한)를
  초과하지 않는지(2026-08-18)를 검사한다. **재생은 ①~⑤만 재검사한다** — ⑥⑦(임무
  대조)은 수신 시점의 게이트이고, 이미 받은 기록을 나중에 부정하지 않는다(임무
  원장이 따로 회전·보관 정책을 타므로 재생 시점에 없을 수 있다). 발급 전 사전
  점검은 `mission_plans` 소관.
  **미완**: Cell 분류(위험구역/자산/일반)를 서버가 갖고 있지 않아 요약 비율 자체를
  재계산하지는 못한다 — 기체 보고를 검증하되 재현하지는 않는다. 칸을 충분히
  만들고 비율을 계획 안쪽으로 조작하면 여전히 통과한다(2026-08-18 설계 문서
  "닫지 못하는 것" 참조) — 이 계획이 막는 건 산술적으로 불가능한 주장뿐이다._
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

- **INV-016** 최종 비행 산출물(`FlightArtifact`)은 검증된 원본 바이트, source,
  revision, SHA-256 digest와 Mission Contract 결속을 함께 가진다. 같은 Mission Intent의
  KMZ라도 바이트 또는 실행 의미가 바뀌면 기존 계약을 재사용하지 않으며, 새 revision의
  검증·digest 결속·서명을 거쳐야 한다. Core가 경로 compiler를 독점할 필요는 없지만,
  **어느 compiler가 만든 최종 산출물을 승인했는지**의 권위는 Core에 있다.
  _강제: FlightArtifact ingest/generation validator + Mission Contract binding +
  contract/replay test. 현재 KSI_WPML의 짝 발급은 후보 경로이며, Pilot 2 export
  ingest와 revision binding은 ADR-KSI-028 범위의 구현 게이트다._

- **INV-017** `AnalysisReadiness`는 사용자가 직접 설정하는 상태가 아니라, 허용된
  CoverageReport, CaptureQualityReport, SourceMedia 무결성·capture-time window,
  temporal policy, Processing/원본 산출물 계보에서 **결정적으로 파생**된다. Processing
  성공 하나만으로 분석 가능이라고 주장하지 않으며, 부족한 증거는 `READY` 대신 typed
  reason code로 보인다.
  _강제: Core readiness projection의 evidence join·fail-closed reason-code 검사,
  ordering replay 및 Dashboard projection test (ADR-KSI-029). 구현 전에는 UI/API가
  이 상태를 완료 사실처럼 표시하지 않는다._

- **INV-018** Observation Epoch에 들어가는 SourceMedia의 capture window는 WorkOrder
  cycle의 명시된 temporal policy를 만족해야 한다. 정책이 없거나 시간·무결성 증거가
  없거나 범위를 넘으면 epoch를 조용히 합치지 않고 분석 준비도에 그 이유를 남긴다.
  MVP v1은 `1 WorkOrder cycle → 1 Mission/Sortie → 1 SourceMediaBundle → 1
  ProcessingJob`만 허용하며, 다중 sortie epoch는 별도 계약·현장 증거 없이는 열지
  않는다.
  _강제: WorkOrder temporal policy + sealed SourceMediaBundle capture window 대조 +
  epoch/replay test (ADR-KSI-029)._

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
  _강제: ① `ArtifactAccuracy` 검사점 게이트(`packages/event-contracts/.../processing_artifact.py`
  + 계약 문서 `processing-artifact.v1.3.json` 의 `allOf` 페어링 규칙) — `rmse` 는 GCP
  피팅 잔차로 의미가 고정되고, 절대 RMSE 주장은 `checkpointCount`·`checkpointRmseM`
  쌍으로만 표현된다. 한쪽만 실리거나 잔차가 0 이하이면 등록 표면 422·journal 재생
  실패·스키마 검증 실패 **세 곳에서** 막힌다(요청 모델이 계약 모델을 그대로 쓴다 —
  요청 전용 사본을 두면 정본과 갈라진다). ② 리포트 오차한계 정직성
  (`dsm_diff._uncertainty_m3`, `VolumeChangeReport.uncertaintyM3/Note`) — 양쪽 epoch 모두
  검증된 RMSE 가 있을 때만 값을 내고 없으면 null+사유. ③ 그 값의 배선
  (2026-08-18) — Core 의 `checkpoint_rmse_of` 가 산출물 원장에서 `checkpointRmseM`
  **만** 꺼내(`accuracy.rmse` 는 절대 꺼내지 않는다) 비교 입력으로 전달하고, 워커가
  `ArtifactSource.rmse_m` 으로 계산에 넘긴다. 배선 전에는 워커가 늘 None 을 넘겨
  ②의 계산 경로가 **존재하면서도 한 번도 실행된 적이 없었다**. 돌연변이 검증으로
  양방향 고정: 배선을 끊으면 오차한계가 사라지고, 피팅 잔차를 흘리면 계약 테스트가
  잡는다.
  **미완**: (a) 서버는 산출물 바이트를 읽지 않으므로 신고된 검사점 수·잔차의 진위는
  확인 불가다(귀속이지 관측이 아니다) — 정확히는 "그 경로를 잇지 않았다"이지 원리적
  불가가 아니다(설계면 검증은 워커가 바이트를 열어 재고 Core 가 각인하는 기성 패턴을
  이미 쓴다). 현장 측량 검사점 대조는 실장비 작업이다. (b) 배선은 이어졌으나(위 ③)
  **실제로 검사점을 신고하는 생산자가 아직 없다** — ODM 워커는 `accuracy` 키 자체를
  보내지 않으므로 현 파이프라인의 `uncertaintyM3` 는 여전히 전부 null 이다. 값이
  생기려면 검사점 리포트를 내는 엔진(Pix4D 등)이 붙거나 현장 측량 검사점이 등록돼야
  한다. (c) RTK fix 상태는 기체에서는
  이미 구독·사용된다(`edge/psdk-app` 의 `OnRtkPositionInfo`, 이륙 게이트) — 없는 것은
  그 상태를 사진·텔레메트리에 붙여 Core 까지 올리는 경로이고, 실기 사진 없이는 필드
  확정이 불가하다. (d) 이 항목의 옛 이름이던 "Spatial Quality Report" 는 아직
  `packages/geo-core/.../uncertainty.py` 가 위임 대상으로 지목한다 — 그 위임의 실제
  소유자가 위 ①②라는 것을 코드 주석으로 잇는 작업이 남아 있다._
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
  _강제: 코드리뷰 게이트 + `tests/contract/test_production_profile_gate.py` — 두 운영
  진입점의 import closure 를 subprocess 로 떠서 ①mock/dev/placeholder 모듈 부재
  ②references·scripts·tests 경로 모듈 유입 없음 ③closure 전체 소스에 dev 토큰 리터럴
  없음을 고정한다(세 검사 모두 Core·워커 양쪽에 적용). Core 는 `build_production_app()`
  을 실제 호출하고, 워커는 `runner` import 까지만 한다(`main()` 은 폴링 루프라 돌아오지
  않는다).
  **미완**: ①모듈 단위 검사라 정상 라이브러리 안의 가짜 클래스(예: `httpx.MockTransport`)는
  잡지 못한다 — 그 축은 코드리뷰 게이트 몫이다. ②워커의 지연 import 서브트리
  (`_load_dynamic_object_detector_from_env` 아래 torch/transformers)는 closure 에 들어오지
  않는다 — 모듈 단위 게이트의 구조적 한계다. ③`packages/mission-contracts` 의 Edge console
  script 3건은 이 게이트 밖이다(현재 위반 없음을 실측했으나 회귀 감시는 없다).
  ④Edge C++ 의 static always-go 축은 별개다._
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

## 재구성·처리 파이프라인

- **INV-050** 처리 작업(Processing Job — 3D 재구성 등)은 실행 위치와 그 현장의
  데이터 반출 허용이 일치할 때만 생성된다(fail-closed). 벤더 클라우드(예: DJI
  FlightHub 2, 상용 SaaS 엔진)에서 실행하는 작업인데 그 현장의 반출 허용이
  참이 아니면 작업 생성 자체를 거부한다 — 실행 후 사후 통제가 아니라 생성
  시점 게이트다.
  _강제: `services/core/src/ksi_core/processing_jobs.py` `ProcessingJobStore.issue()`
  — `dataResidency.egressAllowed` 가 거짓인 현장에 벤더 클라우드 실행을 발급
  요청하면 생성 자체를 `EGRESS_NOT_ALLOWED` 로 거부(재생도 동일 판정 재현).
  `tests/contract/test_processing_jobs.py::test_vendor_cloud_refused_when_site_has_not_declared_egress`
  / `::test_vendor_cloud_refused_when_site_declared_egress_false` /
  `::test_vendor_cloud_allowed_when_site_declared_egress_true` /
  `::test_onprem_execution_is_unaffected_by_egress_declaration`
  (ADR-KSI-012 D1·D3, ADR-KSI-013)._
- **INV-051** 재구성 산출물은 원본(raw capture를 직접 처리한 결과)인지 파생
  (원본에서 재생성한 서빙 계층)인지 계보를 반드시 지니며, 파생 산출물을 원본의
  권위로 대체해 측정·완료 판정 근거로 쓰지 않는다. Point Cloud가 원본 SSOT이고
  Mesh/3D Tiles/정사영상이 파생 서빙 계층이라는 원칙(ADR-KSI-003)을 실제 처리
  엔진(ODM 등)의 산출물에도 동일하게 적용한다.
  _강제: `services/core/src/ksi_core/processing_jobs.py` `ProcessingArtifact.lineage`
  (`authority: source|derived` + `derivedFrom`, 요청이 아니라 Core가 봉인된 번들의
  `sourceBundleDigest`로 채움) + `assert_succeeded_is_backed()` — RUNNING→SUCCEEDED
  전이는 `authority=source` 산출물이 최소 1건 등록돼 있어야 통과(파생물만으로는
  거부, live·재생 동일 판정). `services/processing-controller`의 ODM 어댑터
  (`ksi_processing_controller.odm_assets`)가 Point Cloud=원본/Mesh·정사영상·
  DSM·DTM=파생으로 매핑. `tests/contract/test_processing_jobs.py::test_succeeded_is_refused_without_any_artifact`
  / `::test_replay_refuses_success_whose_artifact_record_was_deleted` /
  `::test_lineage_anchor_comes_from_the_sealed_bundle` /
  `::test_replay_refuses_artifact_with_forged_lineage_anchor`
  (ADR-KSI-003, ADR-KSI-012 D1)._

## 임무 발급·현장 생애주기

- **INV-052** "먼저 매핑, 그 다음 사전지도 기반 자율"은 임무 발급 자체가
  강제한다 — `AUTONOMOUS_PATROL`처럼 사전지도(World Model) 기반 자율을
  전제하는 임무 타입은 현장이 검증된 최신 모델을 가진 상태(`PROVISIONAL_
  AUTONOMY`·`PATROL_READY`·`PATROL_ACTIVE`)에서만 발급된다. `UNMAPPED`
  현장에는 발급되지 않으며, `MODEL_STALE`(모델이 낡음)에서도 발급되지 않는다
  — 상태머신이 `MODEL_STALE → PATROL_READY` 직행 간선을 두지 않아 품질
  재검증을 우회할 수 없게 한 것(`ksi_domain.enums`)과 동일 원칙을 임무 발급
  시점에도 적용한다. `SUSPENDED` 현장에는 임무 타입과 무관하게 어떤 임무도
  발급되지 않는다. 등록되지 않은 현장 ID로는 발급되지 않는다(`UNKNOWN_SITE`).
  8개 임무 타입 전체의 허용 현장상태 표와 각 결정의 근거(문서 인용 vs. 보수적
  추론 구분 포함)는 `packages/domain/src/ksi_domain/mission_gating.py`
  모듈 docstring이 SSOT다 — 여기 복제하지 않는다. 특히 `INCIDENT_SURVEY`
  (사고조사)를 `SUSPENDED`를 제외한 전 상태에서 허용한 결정은 문서 문언이
  아니라 FINAL_DECISION_LEDGER "미매핑 공간은 제한속도·거리·행동으로
  탐색"(DEC-013)으로부터의 추론이다 — 대표자 재검토 대상으로 남는다.
  _강제: `ksi_domain.mission_gating.assert_mission_type_allowed_at_site_status`
  + `ksi_core.mission_records.precheck_issuance`(`MISSION_TYPE_SITE_STATUS_
  MISMATCH` verdict, 409) — 짝 발급(`mission_plans.py`)과 계약 단독 발급
  (`mission_issuance.py`) 두 경로 모두 이 한 함수를 거친다(ADR-KSI-014).
  대시보드 새 현장조사 Wizard는 이 표를 미러링해 발급 불가 목적을 사유와
  함께 비활성으로 미리 보여준다(서버 409를 마지막 단계에서 만나지 않게,
  ADR-KSI-011과 동일 원칙) — `apps/dashboard/src/lib/core-api/
  missionSiteGate.ts`._

## 조직·Copilot 경계

- **INV-060** 인증된 조직 밖의 Site·Mission·Artifact·WorkOrder·Conversation은
  읽기·쓰기뿐 아니라 존재 여부도 노출하지 않는다. `organizationId`는 요청 body가
  아니라 인증 Principal과 서버 원장에서 유도한다. Edge 장비는 등록 조직과 배정
  Site/Mission 범위를 동시에 통과해야 한다.
  _강제: Core authorization scope helper + 모든 신규 저장소 조회 + cross-organization
  contract tests. 범위 불일치는 403이 아니라 동일한 404로 접는다._

- **INV-061** Copilot은 allowlist된 typed query와 재관측 **초안** 도구만 사용할 수
  있다. Raw SQL·임의 Object Storage key·Mission issue·승인·Flight Command는 도구
  표면에 존재하지 않으며, 외부 LLM 반출은 현장 정책이 명시적으로 허용할 때만 한다.
  _강제: tool registry 구조 테스트 + data-egress policy gate + approval endpoint의
  사람 Principal/권한 검사. INV-002의 비행좌표 금지를 함께 적용한다._
