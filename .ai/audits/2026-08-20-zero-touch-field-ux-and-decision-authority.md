# KSI Zero-touch 현장 UX와 판단 권한 제안

- 상태: `DRAFT — 대표자 결정 대기`
- 작성일: 2026-08-20
- 목적: 파일 이관을 제거하고, 서버·LLM·Manifold·사람의 판단 권한과 DJI 통합
  우선순위를 확정한다.
- 정본 경계: 승인 전에는 PRODUCT_CONSTITUTION, Decision Ledger, ADR을 변경하지 않는다.

## 1. 권고 제품 정의

> KSI Site Intelligence는 현장 작업자가 필요한 업무를 한 번 선택하면 드론 데이터가
> 자동으로 수집·처리되고, 변화·공정·물량·점검 결과를 근거와 함께 질문할 수 있으며,
> 부족한 데이터의 재관측까지 승인할 수 있는 건설현장 공간 인텔리전스 제품이다.

정상 사용자 흐름에 `KMZ 다운로드`, `USB 연결`, `SD 카드 복사`, `사진 폴더 선택`,
`missionId 입력`은 없어야 한다. 이 기능들은 장애 복구와 개발 검증용 fallback이다.

```text
오늘 작업 선택
  → 준비상태 자동 확인
  → 조종사 비행 승인
  → DJI가 비행·촬영
  → 원본 자동 전송
  → 서버가 재구성·비교·계산
  → KSI Copilot이 근거와 함께 설명
  → 사람이 결과 또는 재관측 승인
```

## 2. 판단 권한

### 서버의 결정적 엔진

- 수백~수천 장 사진의 정합과 정사영상·점군·DSM·3D 생성
- 좌표계·수직기준·epoch 검증
- 시점 간 변화와 절토·성토·순체적 계산
- 설계 대비 공정·편차, coverage·불확실성, 다음 관측 대상 도출
- 원본부터 결과까지 lineage와 감사기록

숫자와 공간 상태의 SSOT다. LLM이나 Manifold가 대신 계산하지 않는다.

### KSI Copilot

- 비전문가 질문을 검증된 query tool 호출로 변환
- 변화·물량·공정·위험 후보를 현장 언어로 설명
- 보고서, 조치, 재관측 work order 초안 작성
- 근거 사진·지도 위치·epoch·단위·불확실성 링크 제공

LLM은 원시 사진을 보고 물량을 추측하지 않고 비행 좌표나 안전 명령을 만들지 않는다.
검증된 계산을 업무 의미로 바꾸는 주 인터페이스다.

### Manifold 3

- 비행 중 liveview/telemetry/perception의 저지연 처리
- 흐림·노출·가림·관측 누락·target loss 검출
- 서명된 범위 안의 즉시 재촬영, 짐벌·줌, next-best-view 후보
- 네트워크 단절 시 로컬 보존과 store-and-forward
- 짧은 위험 후보와 증거 생성

전체 현장 3D 재구성, 여러 날짜 비교, 총 물량·공정 계산, 대화형 보고서는 서버가
담당한다. Manifold는 **현장에서 다시 오지 않아도 되도록 촬영 품질과 즉시 행동을
닫는 장치**다.

### 사람

- 이륙, 현장 안전, 예외·수동 인계
- finding 확정과 담당자/기한 지정
- 재관측 승인
- 대외 보고, 기성·정산 등 계약성 숫자의 최종 승인

## 3. KSI에 맞는 Manifold 활용 순서

### 1순위 — Capture Quality Recovery

흔들림, 과·저노출, 중복도 부족, 가림, target loss를 비행 중 찾아 같은 sortie에서
다시 촬영한다. 가장 낮은 안전 위험으로 재방문과 처리 실패를 직접 줄인다.

### 2순위 — Adaptive Construction Inspection

사면, 흙막이, 외벽, 옹벽, 야적장, 장비·자재처럼 지정된 대상을 탐지하면 안전한
stand-off 거리에서 짐벌·줌 또는 추가 관측점을 선택해 근거를 보강한다.

### 3순위 — Safety Patrol Candidate

작업자·장비 근접, PPE, 통로폐색, 개구부 같은 후보를 추적하고 위치·시간·불확실성·
전후 증거를 만든다. 단일 프레임을 위험 확정으로 승격하지 않으며 사람에게 더 가까이
접근하지 않는다. 다중 시점·RiskField 검증과 사람의 업무 확정을 거친다.

### 서버에 남기는 기능

- 토공량과 공정률의 최종 계산
- 여러 날짜의 현장 변화 판단
- BIM/도면 대비 as-built
- 현장 전체 보고서와 LLM 질의

Manifold는 이 계산에 필요한 데이터가 부족한지를 현장에서 발견하고 보충한다.

## 4. 행동 기반 자율순찰

```text
Core: 무엇을 왜 관측할지 + 허용 비행공간 + 정책을 서명
  ↓
Manifold: 현재 장면을 인식하고 다음 안전한 관측 행동을 선택
  ↓ high-level intent
DJI Flight Controller: 안정화·저수준 비행·보호기능·RTH
  ↓
Manifold: 관측 품질/위험 후보/증거를 평가하고 임무를 계속 또는 복구
  ↓
Server: 여러 epoch를 처리·비교하고 다음 work order를 생성
  ↓
LLM: 결과를 설명하고 재관측 초안을 제안
  ↓
사람: 재관측과 업무 결과를 승인
```

`A → B → C` waypoint를 버리는 것이 아니라 안전한 backbone으로 사용한다. B에서
추가 관측이 필요할 때만 계약 범위 안의 `B'`, `B''`를 선택하고 다시 backbone으로
복귀한다. 이 구조가 DJI 기본 waypoint 위에 KSI가 더하는 제품 가치다.

## 5. DJI 통합 결정

| 후보 | 현장 UX | KSI 차별화 | 결정 |
|---|---|---|---|
| Pilot 2 + FlightHub 2/Cloud API | Pilot 유지, cloud 경로·media 자동화 가능 | 분석·Copilot 집중 | **첫 Spike** |
| PSDK + Manifold 3 | 품질복구·원본 회수·offline·active view | Acquisition 해자 | **선택적 핵심** |
| MSDK Field App | 한 앱에서 작업·비행·media 가능 | UX 완전 통제 | **Cloud/PSDK 실패 시** |
| 수동 KMZ + SD/USB | 구현됨 | 없음 | **복구용만** |

권고 목표는 `Pilot 2 + Cloud integration + KSI Server/Copilot`을 기본으로 하고,
`PSDK + Manifold 3`를 active acquisition에 붙이는 것이다. MSDK는 두 경로만으로
zero-touch UX가 성립하지 않을 때 추가한다.

## 6. 확인된 capability와 불확실성

- MSDK V5는 M4D/4TD + RC Plus 2를 지원하고 KMZ mission, camera/gimbal, media
  download API를 제공한다.
- 최신 PSDK는 M4D/4TD Pilot 조합에서 Manifold 3 basic/advanced capability를
  지원한다. camera media, gimbal, liveview/perception, flight control, MOP, cloud
  WebSocket, custom network가 열려 있다.
- Manifold 앱은 `.dpk`로 패키징해 Pilot 2 또는 FlightHub 2에서 설치·관리할 수 있고,
  DJI Ecosystem Products Catalogue를 통한 상용 배포 경로가 있다. 소비자 앱스토어가
  아니라 심사·유통되는 enterprise catalogue에 가깝다.
- Pilot-to-Cloud는 wayline library, media auto/manual upload, WebView를 제공한다.
- FlightHub 2는 M4D series, route/media/model sync, OpenAPI/FlightHub Sync와 cloud
  reconstruction을 제공한다고 명시한다.
- 그러나 Cloud API product support 표와 release note의 M4D Pilot-to-Cloud 범위가
  완전히 일치하지 않는다. RC Plus 2 standalone에서 전체 조합은 `NOT_VERIFIED`다.
- MSDK와 Pilot 2 동시 실행 안정성도 `NOT_VERIFIED`다.
- 위 API 조각을 조합한 KSI 행동 기반 순찰은 기술적으로 설계 가능하지만, 현재 KSI의
  실기 수행 증거는 0회이므로 `HIL/Field Proven`이 아니다.

## 7. 채택 게이트

### Cloud gate

- Pilot 2에서 KSI 작업을 열 수 있음
- KSI wayline이 파일 조작 없이 보임
- 착륙 후 원본이 자동 업로드됨
- site/work order/flight/media lineage가 보존됨

모두 통과하면 MSDK를 만들지 않는다.

### Edge gate

- Manifold가 품질 실패 또는 누락을 탐지
- 계약 범위 내 재관측으로 실제 결과가 개선됨
- manual override와 DJI 보호기능이 유지됨
- offline recovery가 데이터 손실 없이 동작

통과한 기능만 상용 옵션으로 만든다.

### MSDK gate

- Cloud가 필요한 현장 UX를 제공하지 못함
- PSDK + Pilot UX로도 zero-touch가 불가능함
- MSDK가 Pilot 2보다 적은 조작으로 안전 필수 기능을 제공함

세 조건을 모두 만족할 때만 MSDK를 제품 범위에 넣는다.

## 8. 시장과 차별화

DroneDeploy, OpenSpace, DJI FlightHub 2도 자동 capture, processing, progress/AI와
대화형 분석을 제공한다. 따라서 3D 생성이나 챗봇 자체는 충분한 해자가 아니다.

KSI의 차별점은 한국 건설현장 좌표·수직기준, 반복 epoch의 신뢰 가능한 변화·물량·
공정, 설계 대비, uncertainty/lineage, 그리고 답변에서 실제 적응형 재관측까지 닫는
폐루프다.

## 9. 바로 다음 작업

1. 프로펠러 제거 상태에서 FlightHub 2/Pilot-to-Cloud route+media 경로를 확인한다.
2. Manifold PSDK로 원본 JPEG 한 장 download+hash+upload를 확인한다.
3. 녹화영상 또는 simulator로 `B → 후보 → 안전한 B' 관측 → B 복귀` 상태기를 HIL한다.
4. 결과에 따라 Cloud adapter와 PSDK active observation의 경계를 확정한다.
5. 그 다음에만 생산 adapter와 Grounded KSI Copilot을 구현한다.

기존 Mission Contract, safety gate, lineage, 수동 recovery path는 삭제하지 않는다.
