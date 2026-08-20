# KSI Site Intelligence Platform 개발 상태 종합 감사

- 날짜: 2026-08-19
- 감사 유형: 제품 정본·구현·검증·활성 작업 교차 감사
- 감사가 만든 변경: 이 보고서 1개만 추가. 감사 전부터 존재한 dirty worktree는 그대로 보존
- 용도: 진단 스냅샷. 최신 active handoff가 아니며, 기존 `.ai/goal.md` 등은 별도 동기화 필요
- 현재 HEAD: `02c1ad5`
- 현재 브랜치: `fix/kmz-official-sample-fidelity`

## 감사 계약

```text
Requirement IDs: DEVEX-PLATFORM-STATE-AUDIT-2026-08-19
Owner module: repository-wide read-only assessment
Acceptance criteria: 현재 목적·완료/부분완료/미착수·근거·위험·우선순위가 문서/코드/테스트와 연결됨
Contracts affected: 없음
Reference assets: 제품 정본, acceptance traceability, ADR, phase/risk ledgers, reference adoption 기록
Adoption decisions: REFERENCE_ONLY
Files to change: 이 감사 보고서 1개
Tests: 기존 게이트와 CI 정의 확인, 비파괴 검증 실행
HIL or real-device assumptions: 실장비 결과를 재현했다고 간주하지 않음
License/data implications: 없음
Rollback: 이 감사 보고서 제거
```

도메인 불변식은 변경하지 않았다. 이 감사는 `INV-001`~`INV-052`의 현재 강제 지점과
미완 경계를 분류한다.

## 1. 결론

이 저장소는 데모 스캐폴딩 수준이 아니다. 제품 정의, 제어 경계, 계약, Core 폐루프,
공간 처리, Dashboard와 상당한 네거티브 테스트가 이미 구현돼 있다. 현재 소프트웨어의
가장 정확한 등급은 다음과 같다.

| 영역 | 현재 등급 | 판단 |
|---|---|---|
| 제품 정의·아키텍처 | 강함 / 동결됨 | 두 축 폐루프와 제어권이 정본 문서와 불변식으로 고정됨 |
| Core·Backend 폐루프 | Software Backend Ready, 비운영 | 발급→배포→수집 등록→처리→공간모델→재관측 초안 경로와 E2E가 존재. 실기 운용 등급 아님 |
| 공간 처리·설계 대비 | Software Backend Ready, live 재검증 필요 | CRS/수직기준, DSM 차분, 설계 적합성, 구역 진척과 리포트 구현 |
| Dashboard | 기능적으로 성숙 | 39 test files / 419 tests, lint와 production build 통과. 단일 통합 지도 UX는 미완 |
| Edge/Manifold 소프트웨어 | 부분 Edge Ready / Shadow | native pipeline·store-forward·risk·evidence·control plane은 있으나 생산 데몬/실기 배선이 미완 |
| DJI/PSDK/HIL | Not Verified | DPK 기동, USB bulk, frame-telemetry p95, 계약 거부, Pilot 2 수용성 미확정 |
| Field/Product readiness | 미달 | 실제 M4D 종단 폐루프 Field Proven 0건 |

따라서 “코드가 거의 없다”가 문제가 아니다. 가장 큰 문제는 잘 만들어진 소프트웨어
조각을 실제 M4D·RC Plus 2·Manifold 3 경로에서 증명하고, 신뢰 경계의 마지막 구멍을
닫는 것이다.

## 2. 사용자가 만들고자 하는 제품

정본 정의는 다음과 같다.

> 반복 비행 데이터를 자동 수집·정합·비교해 현장의 상태·변화·물량을 시계열로 답하고,
> 부족한 데이터의 재수집을 스스로 계획하는 폐루프 현장 공간 인텔리전스 플랫폼.

제품은 두 축이다.

```text
Site Intelligence Core (WHAT / WHY)
  공간·시간 상태, 설계 대비, 변화·공정·물량, 불확실성, Mission Planning
                         ↕ signed/data contracts
Autonomous Acquisition (HOW)
  Manifold Runtime, perception, local world model, viewpoint/path, mission execution
```

Core는 무엇을 왜 볼지 정하고, Manifold는 현장에서 어떻게 볼지 정한다. DJI Flight
Controller는 저수준 안정화·검증된 회피·RTH를 소유한다. 서버나 LLM이 프레임별 비행
좌표를 만들면 제품 헌법 위반이다.

근거:

- `docs/product/PRODUCT_CONSTITUTION.md:19-98`
- `docs/product/FINAL_DECISION_LEDGER_v1.0.md:18-75`
- `docs/product/MASTER_PRD_v3.0.md:68-154, 573-619, 1575-1760`
- `docs/product/DOMAIN_INVARIANTS.md:10-231`

## 3. 현재 무엇을 하고 있었는가

### 3.1 최신 정본 상태

`python3 ~/.claude/scripts/ksi-goals.py report` 기준:

- 지금 쓸 수 있는 goal: 45개
- 전체 goal 96개: completed 67, in_progress 8, blocked 3, proposed 12,
  abandoned 5, false_positive_complete 1
- risk 91개: resolved 73, open 10, regressed 2, accepted 6

현재 in-progress의 중심은 다음이다.

1. `autonomous-acquisition-closed-loop`: 실제 M4D 종단 폐루프 1회 완주
2. `field-0a-kmz-acceptance`: Pilot 2 KMZ 수용성 + M4D 카메라 실측
3. `aol-1-spatial-model-lifecycle`: 공간모델 촬영시각·최신도 완결
4. `aol-1-capture-auto-ingest`: 기체 촬영물의 사람 손 없는 ingest
5. `aol-2-reobservation-planning-depth`: 변화량 기반 재관측 촬영계획 완결
6. `aol-3-terrain-aware-planning`: DSM 기반 경로계획의 실제 발급 배선
7. Phase 3/4의 하드웨어 또는 다중 결함 잔여

### 3.2 현재 브랜치의 실제 작업

현재 브랜치는 `fix/kmz-official-sample-fidelity`이고, 감사 시작 시 수정 9개와 미추적
파일 3개가 있었다. 이 변경은 다음을 수행한다.

- M4D WPML 기체/페이로드 값을 현재 공식 표에 맞춘다.
- DJI PSDK의 핀된 공식 KMZ 샘플과 요소·상대 순서를 지속 비교하는 테스트를 추가한다.
- `createTime/updateTime`을 현재 시각이 아니라 계약의 안정된 시각에서 만들어 KMZ digest
  재현성을 보존한다.
- Pilot 2 실기에서 기종값/페이로드값과 WPML 1.0.2/1.0.3을 가를 A/B/C 킷을 만든다.
- 공식 샘플 정합과 M4D 실기 수용성을 같은 주장으로 섞지 않는다.

집중 테스트 93건과 전체 Python 회귀가 통과했다. 이 변경의 다음 단계는 추가 코드가
아니라 `FIELD-0a` 실기 세션이다.

## 4. 잘 구현된 부분

### 4.1 제품 거버넌스와 정직성

- 권위 순서가 `Constitution → Decision Ledger → PRD → contracts → ADR → acceptance`
  로 명확하다.
- 모든 핵심 안전결정이 `INV-xxx`와 강제 지점으로 연결된다.
- 소프트웨어 완료, Backend Ready, Edge Ready, HIL Proven, Field Proven을 분리한다.
- mock/import/unit test만으로 실기 준비 완료를 주장하지 않는다.
- reference repository 직접 import를 CI에서 차단한다.

이 부분은 AI 에이전트가 과잉 완료 선언을 하기 어려운 구조로 잘 설계돼 있다.

### 4.2 Mission Contract와 임무 거버넌스

- 계약은 versioned/signed/digest/TTL 경계를 갖고 발급과 저장이 분리돼 있다.
- 소비자는 malformed, unsigned, tampered, wrong-schema, expired/revoked 후보를 거부한다.
- 실패한 후보가 기존 active contract를 교체하지 못한다.
- 활성 상태 디렉터리의 소유권·symlink·권한까지 검사한다.
- Mission Contract와 KMZ를 이원 산출물로 유지해 DJI 파일의 무서명 한계를 보완한다.
- 임무 타입×현장 상태 게이트와 100/100/95 coverage 정책을 발급 전 단계에서 검사한다.

관련 코드:

- `packages/mission-contracts/src/ksi_mission_contracts/consumer.py`
- `packages/mission-contracts/src/ksi_mission_contracts/edge_activation.py`
- `services/core/src/ksi_core/mission_issuance.py`
- `services/core/src/ksi_core/mission_plans.py`
- `packages/domain/src/ksi_domain/mission_gating.py`

### 4.3 Core 폐루프와 처리 파이프라인

- Site/Mission/Execution/Source Media/Processing/Artifact/Spatial Model/Reobservation이
  개별 도메인으로 분리돼 있다.
- source/derived 산출물 계보와 봉인된 source bundle digest를 강제한다.
- egress가 허용되지 않은 site의 vendor-cloud 처리 작업은 생성 시점에 거부된다.
- 처리 실패가 원본 손실이나 거짓 성공으로 바뀌지 않는다.
- real NodeODM+MinIO+Core 왕복 테스트가 별도 계약으로 존재한다.
- DSM 차분, 변화 영역, 설계 적합성, 구역 진척, 리포트까지 Core 가치축이 연결돼 있다.

현재 E2E의 재구성 워커는 test double을 쓰지만 실 NodeODM 경로는 별도 live contract로
분리한 판단이 좋다. 다만 이번 감사에서는 live 환경변수가 없어 8건 모두 skip되어,
과거 2026-08-09 근거를 현재 재검증한 것은 아니다.

### 4.4 공간·불확실성 경계

- CRS, vertical datum, unit, timestamp, uncertainty가 계약에 반영돼 있다.
- 외삽·telemetry gap·지평선 위 ray를 typed failure로 거부한다.
- 다중 viewpoint와 calibrated pose 근거 없이 localization을 CONFIRMED로 올리지 않는다.
- IFC `IfcMapConversion`, `IfcRigidOperation`, `TargetCRS.MapUnit`과 project-unit fallback을
  분리해 mm 1000배 오류를 회귀 테스트로 고정했다.
- RTK fix와 checkpoint RMSE를 다른 주장으로 구분한다.

### 4.5 Dashboard

- BFF route가 session/origin/error translation을 공통 경계로 사용한다.
- 제품 상태를 단순 mock online 상태로 과장하지 않는다.
- 사이트 등록, 임무, 이벤트, evidence, source upload, processing, design conformance,
  progress, report, field session 등 실제 업무 흐름이 존재한다.
- 이번 감사에서 39 test files / 419 tests, ESLint, Next production build가 통과했다.

### 4.6 Native Edge의 구조

- control plane, command authorization, activation, KMZ sidecar, calibrated projection,
  risk, evidence builder, SQLite store-forward가 분리돼 있다.
- `pipeline.cpp`는 inference→tracking/world→projection→risk→evidence→sync 흐름을 가진다.
- PSDK tap은 raw ingress만 소유하고 판단 로직과 분리돼 있다.
- SQLite가 없을 때 완전한 native gate를 조용히 통과시키지 않고 configure에서 실패한다.

이는 좋은 구조지만 아직 production daemon/HIL 완료를 뜻하지 않는다.

### 4.7 현재 KMZ 변경

- 공식 샘플의 요소 존재 여부와 공유 요소 상대 순서를 테스트로 고정했다.
- 우리만 있는 요소와 샘플에만 있는 요소 모두 이유가 없으면 실패한다.
- 고정 zip timestamp와 stable contract timestamp로 byte determinism을 보존한다.
- A/B/C 킷이 한 현장 세션에서 기종 프로파일과 namespace 가설을 가르도록 구성됐다.
- 코드와 체크리스트가 “샘플 정합 ≠ Pilot 2 수용”을 반복해서 명시한다.

## 5. 중요 개선 지점

### P0 — 새 기능보다 먼저 닫아야 하는 것

#### 5.1 FIELD-0a 실기 수용성

현재 최우선이다. 비행하지 않고 프로펠러를 제거한 상태에서 수행한다.

1. KMZ A/B/C를 Pilot 2에 import하고 성공/거부 원문을 기록한다.
2. Pilot 2가 직접 export한 KMZ를 회수한다.
3. M4D 광각 원본 사진 1장을 지상 촬영해 EXIF/XMP를 회수한다.
4. 초점거리·센서·해상도와 촬영시각/시간대/GPS 시각을 기록한다.

세션 전에 현재 체크리스트의 준비물 문구도 바로잡아야 한다.
`docs/hil/FIELD_0A_CHECKLIST.md:20`은 “KMZ 2개”라고 쓰지만 실제 표와 절차는 A/B/C
3개를 사용한다. 현장 반출 파일 누락을 막기 위해 “3개”로 고친 뒤 세션을 시작한다.

또한 현재 generator는 `payloadSubEnumValue`를 지원하지만 Core의 mission-plan 요청 모델은
이를 별도 입력으로 노출하지 않아 기본값 `0`만 흐른다. FIELD-0a에서 Pilot 2 export 값이
0이 아니면 `mission_plans.py`의 요청/배선까지 함께 수정해야 한다.

이 한 세션이 다음 세 항목의 입력이다.

- high open risk `mapping-camera-constants-are-not-m4d`
- medium open risk `kmz-real-device-acceptance-still-unverified`
- `aol-1-spatial-model-lifecycle`의 촬영시각 설계

#### 5.2 RiskField 신뢰 경계

Core가 등록된 실제 bytes, digest, validity, entity, geometry를 읽는 것은 좋은 개선이다.
그러나 최신 원장은 `critical-event-riskfield-evidence-gate-presence-only`를 다시
`regressed`로 판정한다. 이유는 형식적으로 자기정합적인 가짜 RiskField를 권한 있는
FIELD_OPERATOR가 만들고 확정까지 할 수 있기 때문이다.

남은 구멍:

- 업로드 주체와 확정 주체의 권한 분리 부족
- 장비별 비대칭 서명 없음
- trusted policy/calibration registry 대조 부족
- validity 폭과 entity 상위집합 제한 부족
- degenerate geometry와 실질 uncertainty 검증 부족
- content digest의 후속 재검증 소비자 부족
- Edge pipeline→store-forward→Core transport를 상시 구동하는 production daemon 없음

현장 CRITICAL 지원을 주장하기 전에 설계·구현·HIL이 필요하다.

#### 5.3 Mission Contract rollback의 정본 순서

rollback high-water와 mission-id laundering 방어는 크게 좋아졌다. 그러나
`mission-contract-no-issuance-ordering-field`는 최신 원장에서 `regressed`다.
Mission Contract v1.2에 `issuedAt/revision/supersedes` 같은 명시적 순서 필드가 없고,
현재 방어가 `validity.notBefore`와 로컬 high-water에 의존하기 때문이다.

이는 단순 patch가 아니라 계약 vNext 제품 결정이다. 실제 비행 실행 개방 전에 결정해야 한다.

#### 5.4 mapping coverage의 과잉 주장 가능성

accepted high risk `mapping-coverage-claim-unbounded`가 남아 있다. 현재 서버는 보고의
산술 모순과 발급 계획 상한은 검사하지만, hazard/asset/general cell을 독립 재구성하거나
사진측량 충분성을 재계산하지 못한다. 원장에는 40ha/사진 10장/ratio 1.0도 통과 가능한
사례가 기록돼 있다.

FIELD-0a 카메라 실측과 FIELD-1 실제 사진을 얻은 뒤, capture evidence와 coverage cell
분류를 연결해야 한다. 그 전에는 coverage ratio를 photogrammetric completeness로
표시하면 안 된다.

### P1 — Backend Ready를 실제 운용 경계까지 연결

#### 5.5 `.ai/` 활성 작업 상태 드리프트

`.ai/goal.md`, `plan.md`, `task-state.md`, `handoff.md`는 여전히 2026-08-14의 Mission
Contract/RiskField/IFC 안전 게이트 작업을 중심으로 한다. 최신 goal-ledger는 FIELD-0a,
AOL-1/2/3과 KMZ fidelity를 가리킨다.

이 상태에서는 새 Codex 세션이 오래된 handoff를 최신 목표로 오인할 수 있다. 현재 브랜치
정리 시 `.ai/`를 최신 milestone로 갱신하거나, active artifact와 historical handoff를
구분하는 파일 규약이 필요하다.

#### 5.6 AOL 반증 항목 3개

- `aol-1-spatial-model-lifecycle`: `registeredAt`은 처리 등록 시각이지 촬영 시각이 아니다.
  또한 site 기본 조회가 아닌 별도 `/spatial-model` 응답에만 있다.
- `aol-2-reobservation-planning-depth`: 고도·중복도는 조정되지만 capture interval이
  계획 응답과 UI에 없다. 발급 시 암묵 재계산될 뿐이다.
- `aol-3-terrain-aware-planning`: TerrainGrid와 고도 profile 순수 함수는 검증됐지만
  Core DTM 조회와 WPML/KMZ 발급 소비자가 없다. Unit 2~5도 미착수다.

FIELD-0a의 사진 시각/카메라 결과를 받은 뒤 G1을 먼저 닫고, G5, G6 순서로 진행하는 것이
의존성에 맞다.

#### 5.7 Manifold production assembly

코드 조각은 충분하지만 상시 운용 경계가 없다.

- RiskField evidence chain production daemon 조립
- non-root Python 3.12 runtime provisioning 결정
- dispatch sync/activate 자동 기동
- device key provisioning과 서명
- DPK 안에서 Mission Contract rejection HIL
- USB bulk/frame-telemetry p95 실측

native code 존재를 `Edge Ready`나 `HIL Proven`으로 승격하면 안 된다.

### P2 — 제품 사용성 및 유지보수

#### 5.8 단일 지도 UX

지난 현장, 현재, 변화 영역, 재확인, 다음 비행이 여러 화면에 흩어져 있다. 지도
컴포넌트가 각자 `MapContainer`와 `fitBounds`를 소유해 한 지도에 겹치기 어렵다.
새 Core API보다 레이어/컨테이너 분리가 선행 과제다.

FIELD-0a 이전에는 신규 기능을 늘리지 않는 동결을 지키고, 하드웨어 세션이 늦어질 때
다음 사용자 가치 과제로 고려한다.

#### 5.9 Phase 4와 Phase 5

- Phase 4: 균열은 구현됐지만 박락·부식·백화·철근 노출 등 다중 결함은 데이터/모델
  결정과 라이선스가 필요하다. 지금 추측 개발하지 않는다.
- Phase 5: Dock/Fleet/타 산업 pack은 첫 유료 건설 현장과 Dock capability 결정 전까지
  의도적으로 BLOCKED다.

#### 5.10 의존성·경고 부채

전체 Python 테스트에서 446 warnings가 발생했다. 즉시 제품 blocker는 아니지만 다음
업그레이드 전에 정리가 필요하다.

- Starlette TestClient의 httpx 경로 deprecation
- `jsonschema.RefResolver` 제거 예정
- legacy TorchScript ONNX exporter
- Pytest class-scoped instance fixture 제거 예정
- Torch/MMCV/timm AMP·import deprecation
- ifcopenshell destructor unraisable warning

경고를 무조건 숨기지 말고, 소유 모듈·업그레이드 조건·허용 baseline을 문서화한다.

#### 5.11 native 개발 환경 재현성

이번 호스트에는 SQLite3 개발 헤더가 없어 fresh `KSI_REQUIRE_SQLITE=ON` configure가
fail-closed로 중단됐다. 기존 non-SQLite build의 6개 ctest는 통과했지만 WAL/store-forward
분기를 검증한 근거가 아니다.

개발 bootstrap 또는 dev container에 SQLite header 준비 절차를 명시해 로컬과 CI의
native gate 의미를 맞출 필요가 있다.

## 6. 열린 위험 우선순위

### High

- open: `mapping-camera-constants-are-not-m4d`
- accepted: `mapping-coverage-claim-unbounded`

### Medium open

- `dji-pilot-cloud-wayline-support-conflicting-docs`
- `kmz-real-device-acceptance-still-unverified`
- `mission-contract-rejection-not-hil-verified`
- `mission-dispatch-cli-python312-runtime-provisioning-undecided`
- `riskfield-evidence-daemon-not-assembled`
- `riskfield-provenance-no-device-signature`

### Regressed

- `critical-event-riskfield-evidence-gate-presence-only`
- `mission-contract-no-issuance-ordering-field`

### Low open

- `coverage-reconciliation-not-in-print-or-csv`
- `patrol-backbone-capture-cadence-hardware-unvalidated`
- `perception-pipeline-production-status-undecided`

## 7. 권장 실행 순서

### Milestone A — 현재 브랜치 종료 조건

1. 현재 KMZ diff의 acceptance review
2. `FIELD-0a` 세션 수행: import A/B/C, Pilot 2 export KMZ, M4D 원본 사진
3. 실측 결과에 따라 generator/camera defaults만 수정
4. Python/Dashboard/repo gates 재실행
5. `.ai/`를 최신 goal/handoff로 동기화

실기 결과 전에는 `field-0a-kmz-acceptance`를 완료로 바꾸지 않는다.

### Milestone B — 신뢰 경계 하드닝

1. RiskField producer/approver 권한 분리와 device signature 설계
2. production evidence daemon 조립
3. Mission Contract vNext ordering 결정
4. mapping coverage evidence 재구성 설계

이 범위는 auth/contract/data trust boundary이므로 strict plan과 security review가 필요하다.

### Milestone C — FIELD-0 지상 통합

1. Manifold 전원·네트워크 확보
2. DPK 설치/기동과 USB bulk probe
3. 미서명·만료·rollback Mission Contract 실제 거부
4. frame-telemetry p95와 store-forward sync 실측
5. production daemon/runtime provisioning 검증

### Milestone D — FIELD-1 첫 실제 매핑

1. GCP/checkpoint가 붙은 M4D 실제 사진 수집
2. 실제 ingest→NodeODM→MinIO→Core→공간모델 종단
3. capture time 기반 freshness 검증
4. coverage와 사진측량 충분성 대조
5. 실제 map/model artifact의 provenance 확인

### Milestone E — FIELD-2 폐루프

1. 1회차 변화/진척 분석
2. 재관측 계획 생성과 운영자 승인
3. 2회차 실제 재관측
4. offline store-and-forward와 복구 동기화
5. 전체 Evidence/Action lineage 검증

이 단계가 끝나야 제품 정의의 Observe→Understand→Decide→Re-observe 폐루프를 Field
Proven으로 주장할 수 있다.

## 8. 이번 감사의 실제 검증

### 통과

아래 수치는 과거 문서 인용이 아니라 **2026-08-19 이번 감사 세션에서 직접 실행한 결과**다.
터미널 출력은 별도 raw log 파일로 영속화하지 않았다.

- KMZ focused: `93 passed`
- Full Python: `3588 passed, 23 skipped, 3 xfailed`
- Ruff: pass
- mypy: `340 source files`, pass
- Dashboard Vitest: `39 files / 419 tests`, pass
- Dashboard ESLint: pass
- Dashboard Next production build: pass
- PSDK-independent C logic: `2/2` ctest pass
- Existing native non-SQLite build: `6/6` ctest pass
- `uv lock --check`: pass
- `git diff --check`: pass
- no-reference-import guard: pass
- repository hygiene: pass

주요 실행 명령:

```bash
ulimit -n 8192 && uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked mypy packages services tests tools
cd apps/dashboard && npm test && npx eslint . && npx next build
cmake -S edge/psdk-tap -B /tmp/ksi-audit-psdk-build -DKSI_PSDK_TAP_LOGIC_TESTS_ONLY=ON
cmake --build /tmp/ksi-audit-psdk-build -j
ctest --test-dir /tmp/ksi-audit-psdk-build --output-on-failure
uv lock --check
git diff --check
bash scripts/check_no_reference_imports.sh
bash scripts/check_repo_hygiene.sh
```

### 통과 주장 불가

- Fresh native Edge with `KSI_REQUIRE_SQLITE=ON`: host에 SQLite3 development header가 없어
  configure 실패. fail-closed 동작 확인, 전체 native gate 미검증.
- Live NodeODM/MinIO/Core: `KSI_NODEODM_URL`, real image path와 S3 env가 없어 8 tests skipped.
  과거 원장 근거는 있으나 이번 턴에서 current live regression을 재확인하지 않음.
- HIL/실기: 실행하지 않음. Pilot 2, M4D, Manifold, DPK, USB bulk, camera, telemetry,
  battery, RTH, flight capability에 대한 새 지원 주장은 없음.

## 9. 최종 판단

가장 잘된 점은 “좋은 아키텍처 문서”가 아니라 실제 계약과 네거티브 테스트가 제어 경계를
강제한다는 것이다. 가장 위험한 점은 Backend Ready 범위가 넓어져 사람이 Product Ready로
착각하기 쉽다는 것이다.

지금 추가 기능을 넓히는 것보다 `FIELD-0a → trust hardening → FIELD-0 → FIELD-1 →
FIELD-2` 순서로 실제 폐루프의 증거를 쌓는 것이 제품 가치와 안전 모두에 맞다.

## 10. 감사 후 Codex 구현 follow-up

감사에서 식별한 로컬 개선 중 안전한 소프트웨어 범위를 후속 milestone으로 구현했다.

- `DroneProfileParams.payloadSubEnumValue`를 Core 요청 모델과 `build_kmz` 호출에 배선하고,
  HTTP 계획 발급 → `waylines.wpml`까지 값이 보존되는 계약 테스트를 추가했다.
- FIELD-0a 체크리스트를 A/B/C 세 KMZ 기준으로 정합화하고, 공식 샘플 fidelity 테스트와
  OpenAPI 요청 문서를 동기화했다.
- AOL-2 재관측 초안에 `captureIntervalM`을 추가했다. 값은 임의 기본값이 아니라 선택된
  고도·최종 전방 중복도·카메라 footprint에서 `compute_grid_spacing`으로 계산된다.
- Dashboard Core 타입·재관측 프리셋·Survey Wizard가 이 서버 계산 간격을 표시해, 제안이
  UI에서 사라지거나 임의값으로 대체되지 않게 했다.
- `.ai/goal.md`, `.ai/plan.md`, `.ai/task-state.md`, `.ai/handoff.md`에 현재 milestone,
  검증 수치, HIL/생산자/스키마 차단을 동기화했다.

후속 검증: Python `3589 passed, 23 skipped, 3 xfailed`, full mypy 340 source files,
ruff, Dashboard `39 files / 419 tests`·ESLint·Next build, native ctest `6/6`, PSDK tap
`17 + 8`, API contract/hygiene gates가 통과했다. 이 수치는 소프트웨어 게이트이며
Pilot 2/M4D/Manifold HIL 또는 RiskField producer/device-signature readiness를 의미하지 않는다.
