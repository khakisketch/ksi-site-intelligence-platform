# KSI 제품 방향·UX·아키텍처 재정렬 제안

- 상태: `SUPERSEDED DRAFT — 2026-08-20 zero-touch UX 제안으로 대체`
- 대체 문서: `.ai/audits/2026-08-20-zero-touch-field-ux-and-decision-authority.md`
- 작성일: 2026-08-20
- 목적: DJI가 이미 잘하는 기본 매핑 비행을 중복 개발하지 않고, KSI가 고객에게
  값을 만드는 현장 인텔리전스와 재관측 폐루프에 집중하도록 제품 범위를 재편한다.
- 변경 경계: 이 문서는 제안서다. 승인 전에는 제품 헌법, ADR, 계약, API, 소스의
  정본을 변경하지 않는다.

> 이 초안은 DJI Cloud API/FlightHub 2와 최신 Manifold 3 PSDK의 경로·미디어
> 전달 능력을 충분히 반영하지 못했고, 수동 파일 반입을 MVP 기본 UX로 두었다.
> 수동 KMZ/SD/USB는 검증·장애 복구용 fallback으로만 유지한다. 아래 내용은
> 결정 근거의 이력으로 보존하되 신규 구현의 기준으로 사용하지 않는다.

## 1. 권고 결론

KSI를 **드론 비행계획 제품**으로 판매하지 않는다. KSI는 다음 질문에 답하는
**건설현장 관측·분석·조치 제품**으로 만든다.

> 무엇이 얼마나 바뀌었고, 공정과 물량은 어떤 상태이며, 어디가 확인되지 않았고,
> 다음에는 무엇을 다시 촬영해야 하는가?

V1에서는 경로의 기하, 고도, 비행 실행, 장애물 회피, RTH를 DJI Pilot 2와 Flight
Controller가 담당한다. KSI는 관측 목적·대상·품질조건을 만들고, 촬영 데이터를
자동으로 수집·정합·분석하며, 결과와 재관측 필요성을 사용자에게 돌려준다.

따라서 **기본 비행경로는 RC Plus 2의 DJI Pilot 2에서 만든다.** 현재 KSI의
AOI→격자/perimeter→KMZ 생성기는 삭제하지 않고 다음 용도로 낮춘다.

1. DJI Pilot 2에 경로를 만들기 어려운 경우의 호환·fallback
2. 계약·KMZ 결정성·회귀 테스트 fixture
3. 향후 검증된 DJI Cloud 연동의 입력 adapter

KSI Dashboard의 기본 CTA에서는 “서버가 경로 생성”을 제거한다. 사용자는 KSI에서
**관측 요청**을 만들고, Pilot 2에서 경로를 만든 뒤, KSI가 실제 수행 결과와 원본
사진을 연결한다. KSI가 생성하지 않은 비행을 KSI가 발급한 좌표인 것처럼 기록하지
않는다.

## 2. 고객과 첫 번째 유료 가치

### 주 사용자

- 현장소장, 공무·공정·품질 담당자: 드론 조종법보다 현장 변화와 조치가 중요하다.
- 드론 운영자: 안전한 비행 수행과 촬영 품질 확보가 중요하다.
- 본사/발주처: 검증 가능한 시점별 보고서와 근거가 중요하다.

### 첫 번째 상용 쐐기

1. **시계열 공정·변화·물량**: 같은 현장을 반복 촬영해 변화 구역, 상대 물량,
   진행 상태를 근거와 신뢰도와 함께 제공한다.
2. **현장 점검**: 사용자가 지정한 구조물·구역의 관측 결과와 발견·조치를 관리한다.
3. **재관측 폐루프**: 가림, 누락, 낮은 신뢰도 영역을 찾아 다음 관측 요청을 만든다.

“실시간 종합 안전관리”는 별도 센서와 운영체계가 필요한 더 큰 제품이다. V1의
안전 기능은 **드론 기반 점검 임무와 증거/조치 관리**로 한정하고, 다중 센서 실시간
관제 제품으로 확장하지 않는다.

## 3. 기능 투자 결정

| 분류 | 기능 | 결정 |
|---|---|---|
| 집중 | 사진 자동 수집·업로드·처리 시작 | 현장 UX의 최우선 병목으로 투자 |
| 집중 | capture epoch, 좌표계, 촬영시각, artifact lineage | 비교 결과의 신뢰 기반으로 강화 |
| 집중 | 정사영상·점군·DSM 저장과 제공 | 분석 가능한 실제 산출물로 완성 |
| 집중 | 시점 간 변화·공정·상대 물량 | 첫 상용 가치로 고도화 |
| 집중 | 설계 대비 현황과 점검 finding | 건설 도메인 차별화 |
| 집중 | 관측 완전성·불확실성·재관측 추천 | KSI가 소유할 핵심 폐루프 |
| 집중 | 보고서·승인·조치·감사 이력 | 의사결정 제품으로 완성 |
| 유지/축소 | KSI AOI→격자/perimeter→KMZ | 기본 UX에서 제거, fallback/검증 자산으로 유지 |
| 유지/보류 | Manifold capture/telemetry/store-forward | 선택 장비 계층으로 실증 후 확장 |
| 보류 | Manifold 능동 시점·짐벌·줌·경로 수정 | 정적 폐루프 가치와 실기 안전 근거 이후 투자 |
| 보류 | DJI Cloud 자동 경로 배포·사진 회수 | M4D/Pilot 2 실지원과 API 권한 확인 후 adapter 추가 |
| 제외 | KSI 저수준 비행제어·RTH·일반 장애물 회피 | DJI 책임과 중복하므로 개발하지 않음 |
| 제외 | RC Plus 2 전용 MSDK 앱 | 승인된 ADR-KSI-017 경계 유지 |
| 제외 | 범용 드론 fleet/Dock/타 산업 팩 | 첫 건설 현장 유료 가치 전에는 개발하지 않음 |
| 제외 | 데이터 기반 없는 LLM 보고서·자연어 데모 | 근거 데이터 계층 완성 전에는 개발하지 않음 |
| 제외 | 범용 3D 뷰어와 정면 경쟁 | 검증된 오픈소스/상용 viewer를 조립 |

“제외”는 기존 안전 게이트나 계보 코드를 삭제한다는 뜻이 아니다. 신규 제품 투자를
중단한다는 뜻이며, 기존 검증 자산은 rollback과 안전을 위해 보존한다.

## 4. 사용자 경험

### 정보 구조

상위 내비게이션을 사용자의 일 중심으로 줄인다.

```text
오늘                 현장                  발견·조치             보고서
할 일 / 처리 중       상태 / 시점 / 변화     점검 결과 / 담당 / 상태   공유 / 반출
```

장비, 계약, artifact, processing job, provider 설정은 기본 내비게이션에서 빼고
관리자 또는 “세부 정보”에 둔다.

### 현장 상세가 제품의 홈이다

한 화면에서 다음만 먼저 보여준다.

1. 현재 현장 상태와 마지막 관측 시점
2. 최신 변화·공정·물량·점검 요약
3. 신뢰도, 누락 영역, 처리 실패
4. 지금 해야 할 단 하나의 주요 행동

상태별 주요 CTA는 다음과 같다.

| 상태 | 주요 CTA |
|---|---|
| 기준 데이터 없음 | `첫 관측 준비` |
| 촬영 대기 | `DJI Pilot 2 비행 준비 확인` |
| 촬영 완료, 원본 없음 | `촬영 가져오기` |
| 처리 중 | `처리 상태 보기` |
| 결과 검토 필요 | `결과 검토` |
| 재관측 필요 | `재관측 승인` |
| 최신 상태 | `새 관측 요청` |

### 새 관측 흐름

기존 “대상→목적→조사 수준→서버 경로 검토→전송”을 다음으로 바꾼다.

1. **무엇을 확인합니까?** 기준면, 공정/변화, 물량, 구조물 점검, 재관측
2. **어디를 어느 품질로 봅니까?** 대상 구역과 요구 해상도·중복도·시한
3. **Pilot 2에서 비행 준비**: KSI가 AOI/target/checklist를 제공하고, 운영자가
   Pilot 2에서 실제 경로·고도·카메라를 확정
4. **비행 연결**: Pilot export 또는 수행 기록의 digest를 관측 요청에 연결
5. **촬영 가져오기**: PC 연결/SD 폴더 감지 후 사진을 자동 분류·업로드·봉인
6. **자동 처리**: reconstruction과 분석 진행률, 실패 이유, 재시도를 한곳에서 표시
7. **결과 검토**: 변화·물량·finding·누락을 승인하고 필요하면 재관측 요청 생성

고급 좌표계, enum, payloadSubEnumValue, checksum, contract digest는 오류 진단이나
감사 시에만 펼쳐 보여준다. 모든 비동기 단계는 `대기/진행/성공/실패/재시도` 상태와
실행 가능한 복구 행동을 갖는다.

## 5. 축소 아키텍처

```text
사용자
  │
  ▼
KSI Dashboard ── 관측 요청 / 결과 검토 / 승인 / 보고서
  │
  ▼
KSI Core ─────── 현장·epoch·계보·workflow·정책·finding
  │
  ├── DJI Mission Adapter
  │     ├─ V1: AOI/checklist 제공 + Pilot export/수행 기록 연결
  │     └─ Later: 검증된 Cloud API 자동 전달
  │
  ├── Capture Connector
  │     ├─ V1: PC MTP/SD 폴더 감지·자동 업로드
  │     ├─ Optional: Pilot/DJI Cloud 회수
  │     └─ Optional: Manifold store-forward
  │
  ├── Processing ── ODM/provider adapter → 원본 산출물 저장
  │
  └── Intelligence ── 변화 / 공정 / 물량 / 설계대비 / 점검 / 완전성
                       │
                       └─ 재관측 권고 → 사람 승인 → Pilot 2

DJI Pilot 2 + Flight Controller
  └─ 경로·고도·비행·회피·RTH·촬영 실행

Manifold 3 (선택 계층)
  └─ 우선: 캡처 품질·telemetry·store-forward
     이후: 실기 증명 후 tracking·active view·local decision
```

이 구조는 DJI 연결 방식이 수동 파일, Cloud API, Manifold 중 무엇으로 바뀌어도
사용자 흐름을 바꾸지 않는다. 연결 기술은 adapter이고, 제품의 중심은 관측 요청과
결과다.

## 6. 계약과 기존 구현의 처리

- 기존 `Mission Contract v1.3`, dispatch, attestation, RiskField 검증은 KSI가
  실제로 통제하는 Edge 실행 경로의 안전 계약으로 보존한다.
- Pilot 2가 만든 경로에는 별도 `FlightPlanReference` 또는 동등한 실행 기록을 두어
  provider, export digest, aircraft/device, 수행 시각, 원본 번들을 연결한다.
- 상위 개념으로 `ObservationRequest`를 둔다. 여기에는 목적, target, 요구 품질,
  due time, 승인 상태를 담되 실행 가능한 비행 좌표를 넣지 않는다.
- `ObservationRequest → FlightPlanReference → SourceMediaBundle → ProcessingJob →
  SpatialModel/Analysis → ReobservationRecommendation` 계보가 끊기지 않아야 한다.
- 기존 `SurveyWizard`와 mission planning API는 즉시 삭제하지 않는다. 새 흐름을
  feature flag 또는 병렬 route로 넣고, 실제 현장 성공 후 기존 기본 경로를 내린다.

## 7. 구현 순서

### P0 — 제품 계약 확정

- 이 제안을 대표자가 승인한 뒤 PRODUCT_CONSTITUTION, decision ledger,
  ADR-KSI-016/017, PRD 용어를 같은 결정으로 정렬한다.
- “mission/flight plan/survey/observation” 용어와 책임을 하나의 glossary로 고정한다.

### P1 — 촬영 가져오기 UX

- PC의 지정 폴더 또는 연결 장치에서 JPEG를 감지하는 로컬 transfer agent를 만든다.
- 현장/관측 요청 후보를 EXIF 시간·기체·폴더 manifest로 제안하고 사용자가 확정한다.
- 업로드, bundle seal, processing start를 한 번의 흐름으로 묶는다.
- 원본 삭제는 하지 않으며 중복 업로드는 digest로 차단한다.

### P2 — 관측 중심 Dashboard

- 현장 상세를 단일 작업 홈으로 재편한다.
- `SurveyWizard`를 `ObservationRequest` 흐름으로 교체하고 Pilot 2를 기본 실행 방식으로
  둔다.
- 내부 기술 객체는 세부 정보로 내려 사용자에게 작업 상태와 복구 행동을 우선한다.

### P3 — 첫 유료 결과

- 실제 M4D 사진으로 원본→재구성→artifact 저장→공간모델 제공을 완주한다.
- 두 epoch의 변화와 상대 물량을 신뢰도·accuracy 제한과 함께 제공한다.
- PDF/공유 보고서와 발견·조치 workflow를 연결한다.

### P4 — 재관측 폐루프

- 누락/가림/낮은 신뢰도 영역을 target으로 만들고 사람이 승인한다.
- Pilot 2에서 2회차 비행을 수행한 뒤 개선된 coverage와 lineage를 증명한다.

### P5 — Manifold 선택 고도화

- capture quality, telemetry, store-forward의 현장 효익부터 측정한다.
- 그 효익이 입증된 경우에만 짐벌/줌/next-best-view와 제한적 local replanning을
  안전 envelope 안에서 개발한다.

## 8. 성공 지표와 중단 기준

- 비행 종료→검토 가능한 결과까지 걸린 시간
- 원본 수집에 필요한 수동 파일 작업 횟수
- 완전한 capture epoch 비율과 처리 성공률
- 검증된 두 시점 사이 변화·물량 결과의 제공률과 오차 한계 표시율
- 첫 비행에서의 관측 완전성, 재비행 횟수, 재관측 후 개선율
- finding 생성→담당자 지정→조치 완료 시간

Pilot 2보다 나은 경로를 만든다는 지표는 V1 제품 KPI로 두지 않는다. Manifold 기능도
위 지표 중 하나를 실제로 개선하지 못하면 추가 투자를 중단한다.

## 9. 구현 계획 입력값

```text
Requirement IDs:
  ADR-KSI-016 D1/D4/D5, ADR-KSI-017, REQ-MSN-101,
  INV-010/011/020/024/040/041/050/051/052
Owner module:
  Product/Architecture, Dashboard, Core workflow, Capture Connector,
  Processing Controller, Intelligence
Acceptance criteria:
  Pilot 2가 V1 경로/비행 owner로 명확히 표시됨;
  한 개의 관측 중심 사용자 흐름;
  원본 가져오기→처리→결과→재관측 종단 흐름;
  미검증 DJI/Manifold 능력을 지원 상태로 표시하지 않음
Contracts affected:
  신규 ObservationRequest 및 FlightPlanReference 후보;
  기존 Mission Contract/dispatch는 Edge 안전 경로에 유지
Reference assets:
  현재 SurveyWizard, SourceUploadPanel, Site detail, mission-planning,
  ADR-KSI-016/017, DJI Pilot 2 FIELD-0a 증거
Adoption decisions:
  DJI basic waypoint/flight/avoidance/RTH 채택;
  ODM/provider 및 viewer는 adapter로 채택;
  KSI는 분석·계보·재관측을 자체 개발
Files to change:
  승인 후 권위 문서→계약/schema→Core workflow→Dashboard→transfer agent 순서로 확정
Tests:
  contract/replay, upload idempotency, capture-time/lineage, Dashboard E2E,
  실제 M4D FIELD-1/2
HIL or real-device assumptions:
  Pilot 2 경로 작성과 M4D 촬영은 운영자 수행;
  Cloud 자동화와 Manifold 능동 제어는 NOT_VERIFIED
License/data implications:
  DJI API 권한은 확인 전 의존하지 않음;
  원본 사진/GPS/개인키는 비커밋 보안 경로;
  ODM/viewer 라이선스와 SBOM 유지
Rollback:
  새 관측 흐름은 기존 SurveyWizard와 병렬 배포;
  검증 전 기존 계약·KMZ 생성·수동 import 경로 삭제 금지
```

## 10. 지금 결정할 한 문장

> KSI V1은 DJI Pilot 2가 실제 비행경로와 비행을 담당하고, KSI가 관측 목적,
> 데이터 자동 수집, 시계열 현장 분석, 결과 승인과 재관측 폐루프를 담당하는
> 건설현장 인텔리전스 제품으로 개발한다.
