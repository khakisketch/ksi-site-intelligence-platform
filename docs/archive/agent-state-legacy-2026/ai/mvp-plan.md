> HISTORICAL / NOT CURRENT: This preserved record is context only. Read `docs/00_READ_FIRST.md`,
> `docs/superpowers/product-state.md`, and its named ledger; revalidate Git. No old next action here
> supplies external authorization.

# KSI MVP implementation plan (2026-08-20, zero-touch UX)

## 제품 명제

현장 작업자는 “이번 주 토공량 확인”, “A동 외벽 점검”, “지난주 대비 공정 변화”처럼
업무를 선택한다. 시스템은 관측 준비, 경로 전달, 촬영 회수, 처리, 분석을 연결하고,
사용자는 결과와 근거를 검토하거나 재관측을 승인한다. 정상 흐름에서 파일과 기술
식별자는 보이지 않는다.

## 판단 권한

| 판단 | 권위 주체 | LLM 역할 |
|---|---|---|
| 사진 정합, DSM/점군, 좌표변환, 절·성토량, 변화량 | 서버의 결정적 공간 계산기 | 결과 조회·설명만 |
| 여러 epoch의 공정·변화·불확실성·관측 누락 | 서버 Intelligence + versioned model/rules | 근거를 묶어 질문에 답하고 초안 제안 |
| 흐림·과노출·가림·target loss·즉시 재촬영 필요 | Manifold Edge | 없음 |
| 짐벌/줌/국소 next-best-view | Manifold Edge, 서명 계약 범위 안 | 좌표·명령 생성 금지 |
| 저수준 회피·자세·RTH | DJI Flight Controller | 없음 |
| 이륙·예외·재관측·finding·대외/계약성 보고 | 사람 | 권고·요약·문서 초안 |

LLM은 제품의 주 인터페이스가 될 수 있지만 수치의 계산 엔진이나 안전 권위가 아니다.
모든 수치 답변은 `값 + 단위 + 대상 구역 + 촬영 시점 + 정확도/불확실성 + 근거 링크`를
반환해야 한다. 근거가 없으면 답을 추정하지 않고 부족한 데이터와 필요한 재관측을
말한다.

## SDK/Cloud 선택 순서

### 1순위 — DJI FlightHub 2 또는 Pilot-to-Cloud adapter

Pilot 2를 유지하면서 cloud wayline library, media auto upload, third-party WebView,
FlightHub Sync/OpenAPI로 KSI를 연결한다. 가장 적은 현장 학습과 가장 낮은 비행 UI
책임으로 무파일 UX를 만들 수 있으므로 먼저 검증한다.

M4D + RC Plus 2의 세부 지원표가 DJI 문서 사이에서 일치하지 않으므로 실제 장비에서
아래 다섯 항목이 모두 성공해야 채택한다.

1. Pilot 2에서 KSI workspace 로그인/작업 열기
2. 서버의 KMZ가 케이블 없이 wayline library에 나타남
3. 운영자가 Pilot 2에서 검토하고 실행
4. 착륙 후 원본 JPEG가 자동으로 object storage에 업로드
5. media가 site/work order/flight와 결정적으로 연결됨

### 2순위 — PSDK + Manifold 3

Cloud 경로의 장비 제한과 무관하게 Manifold가 KSI 서버에서 작업을 받고, camera media를
다운로드해 store-and-forward할 수 있는지 검증한다. PSDK는 M4D에서 camera/gimbal,
liveview/perception, flight control, media management를 Manifold 3와 함께 제공한다.

Manifold를 도입하는 제품 이유는 다음에 한정한다.

- 비행 중 캡처 품질 검사와 즉시 재촬영으로 재방문을 줄임
- target tracking과 가림 복구, 제한된 active view
- 통신 단절 중 계약 범위 내 계속 수행과 로컬 보존
- 원본·증거의 자동 회수와 서명된 store-and-forward

전체 현장 재구성, multi-epoch 변화, 물량, 공정, 보고서, LLM은 서버에 둔다.

### 3순위 — 얇은 MSDK Field App

Cloud와 PSDK만으로 무파일 왕복 또는 현장 작업 UI가 성립하지 않을 때 도입한다.
범위는 작업 수신, 기존 KMZ 전달/상태 관찰, 착륙 후 media 전송, 안전 필수 화면이다.
KSI route editor, DJI 저수준 제어, Pilot 2 전체 복제는 만들지 않는다.

MSDK/Pilot 2 동시 실행과 화면 전환이 실기에서 안전하고 안정적인지 먼저 검증한다.
실패하면 MSDK 경로를 채택하지 않는다.

## Milestone Z0 — Zero-touch Integration Spike

Requirement IDs:
  ADR-KSI-016 D1/D4/D5, ADR-KSI-017 재검토, UX-001/003/004,
  INV-001/002/010/020/024/040/041/050/051/052
Owner module:
  DJI Gateway, Field UX, Edge Runtime, Core media/mission adapters
Acceptance criteria:
  위 Cloud 5항목 증명; 실패 시 정확한 capability/error 기록;
  PSDK camera media 한 장 download+hash+upload 증명;
  사용자 파일 조작 0회와 작업 선택 후 수동 단계 수 계측
Contracts affected:
  신규 WorkOrder/CaptureTransfer 후보; 기존 Mission Contract는 보존
Reference assets:
  현재 KMZ kit, ingest fallback, SourceMediaBundle, DJI 공식 Cloud/MSDK/PSDK sample
Adoption decisions:
  DJI basic flight/Pilot 2 우선 채택; adapter를 통한 전송; 중복 flight UI 금지
Files to change:
  Spike 결과 전에는 생산 SDK 코드 없음; 결과 후 한 adapter만 선택
Tests:
  contract/replay/idempotency/offline retry; 실제 M4D+RC Plus 2 장비 acceptance
HIL or real-device assumptions:
  Cloud 세부 기능, MSDK coexistence, PSDK media 경로는 현재 NOT_VERIFIED
License/data implications:
  원본/GPS/자격증명 비커밋; site egress 정책 선확인; DJI SDK/서비스 약관 검토
Rollback:
  기존 Pilot 2 수동 KMZ와 `ingest_watch --mission-id`를 fallback으로 유지

## Milestone Z1 — One-job Field UX

- `오늘 작업`에서 한 항목과 한 개의 primary CTA만 표시한다.
- 상태는 `비행 준비 → 촬영 중 → 기체 저장 → 전송 중/대기 → 처리 중 → 결과 준비`로
  표현하고, 실패 시 원인과 다음 행동을 함께 보여준다.
- 비행 중 조종 화면은 DJI Pilot 2를 우선하며 KSI 상세 분석은 착륙 후 보여준다.
- 44px 이상 터치, 야외 고대비, 장갑 사용, 불안정 네트워크와 background retry를
  수용한다.

## Milestone Z2 — Grounded KSI Copilot

- 첫 질문 세트: “지난주 대비 어디가 바뀌었나?”, “A구역 절토/성토량은?”,
  “계획 대비 늦은 구역은?”, “근거 사진과 지도에서 보여줘”, “다시 찍어야 할 곳은?”
- LLM은 typed query tools만 사용하고 raw DB 임의 질의나 직접 산식을 하지 않는다.
- 답변의 모든 주장에 epoch, geometry, artifact/model version, uncertainty와 source link를
  붙인다.
- 계산 불가·시점 충돌·좌표계 불일치·정확도 부족은 답변 대신 명시적 blocked 상태다.
- 재관측은 draft work order까지만 만들고 사람이 승인한다.

## Milestone Z3 — Active Acquisition

- Z0/Z1/Z2의 실제 현장 KPI가 선 뒤에만 Manifold active perception을 연다.
- blur/coverage/occlusion부터 시작해 gimbal/zoom, target recovery, 제한된 local
  replan 순으로 확장한다.
- DJI 보호기능과 signed Mission Contract 밖의 행동은 언제나 거부한다.

## MVP 성공 지표

- 정상 작업에서 USB/SD/수동 파일 선택: `0회`
- 작업 선택에서 비행 준비까지 사용자 입력: 목표 `3회 이하`
- 착륙에서 업로드 시작까지: 사용자 행동 `0회`
- 결과 질문이 근거 링크와 함께 응답되는 비율
- 첫 비행 capture completeness와 재방문 감소율
- 처리 실패 시 현장 사용자가 지원 전화 없이 복구한 비율

## 현재 판정

- 공간 계산·계보·재관측 소프트웨어: 상당 부분 존재하나 실제 현장 데이터 검증 필요
- CLI 폴더 ingest: `Software PASS`, 정상 UX가 아닌 fallback
- Cloud/FlightHub 2 zero-touch: `NOT_VERIFIED`
- PSDK/Manifold camera media·active perception: 공식 capability 존재, KSI 실기 `NOT_VERIFIED`
- MSDK Field App: 공식 M4D 지원, KSI 구현·coexistence `NOT_VERIFIED`
- Observation Work Order/5단계 Field UX: software implemented; live Mission/Gateway wiring pending
- Provider-neutral DJI Gateway: software implemented, concrete provider·capability evidence absent
- Capture-quality action authorizer: native software implemented, live PSDK action wiring absent
- KSI Copilot: typed-tool/citation/draft orchestration implemented; production model/query backend absent
- Organization isolation: new WorkOrder/Copilot surface implemented; legacy stores still require migration
