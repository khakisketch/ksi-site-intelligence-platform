# ADR-KSI-006 — 온보드 앱 기동·임무 활성화 트리거 (목표 설계, 실기 검증 대기)

- 상태: PROPOSED (2026-07-29, 목표 아키텍처로 기록 — Track A 실기 검증 전까지 미확정)
- 관련: ADR-KSI-005(연결 아키텍처), track-a(DJI Hardware Capability Spike), track-b(Perception
  Vertical Slice — "Frame source를 PSDK Live View로 교체")

## 맥락

Mission Contract 수신(인터넷 가용 시 아무 때나, 시동과 무관)과 "비행 중 인식·판단
루프의 실제 시작"은 서로 다른 이벤트다. 지금까지 이 둘을 구분하지 않고 논의해왔는데,
운용 편의(사람이 앱을 수동으로 켜야 하는가)를 결정하려면 명시적으로 나눠야 한다.

## 조사 결과

- **앱 자동 기동은 DJI 공식 문서로 확인됨**: Pilot 2 > Manifold 3 > Application
  Management > "Set as Auto-start on Boot" — 전원 인가 시 앱이 자동 실행된다
  (앱 1개만 지정 가능, 후설정이 우선).
- **PSDK FC Data Subscription 시스템이 존재함**: `DjiFcSubscription_Init` +
  `DjiFcSubscription_SubscribeTopic`으로 기체가 푸시하는 실시간 상태 데이터를
  콜백으로 구독 가능(공식 문서 확인).
- **미확인**: 이 구독 topic 안에 "지상/이륙중/공중/착륙중" 상태를 나타내는 정확한
  topic 이름·enum·지연(latency)은 원문서(JS 렌더링, 이번 조사에서 열람 실패)로
  확인하지 못했다. 여기서 추측하지 않는다(CLAUDE.md "Unknown facts and unverified
  DJI behavior must remain explicit").

## 목표 설계 (Track A 실기 검증 후 확정)

```
전원 인가(E-Port) → 앱 Auto-start on Boot → 대기 상태(perception loop idle)
                                              ↓ FC 구독: 이륙/공중 상태 감지
                              보유 중인 유효 Mission Contract 로드 → 루프 시작
                                              ↓ FC 구독: 착륙 상태 감지
                                    루프 정지 → 결과 확정(journal seal)
```

이 설계가 성립하면 운용자가 앱을 수동으로 켜는 조작이 사라진다 — 전원 인가가
곧 준비 상태 진입이고, 실제 이착륙이 곧 시작·종료 트리거가 된다.

**검증 항목(신규 스코프 아님 — track-a의 기존 "Frame-Telemetry 시간차 p95≤50ms
실측" 스파이크에 편승)**:

1. FC 구독 topic 중 비행 상태를 나타내는 정확한 topic·enum 식별
2. 상태 전이(지상→공중, 공중→지상) 감지 지연 실측
3. Auto-start on Boot 설정된 앱이 실제로 전원 인가 시 몇 초 내 기동하는지 실측
4. 위 셋 중 하나라도 신뢰도가 기준 미달이면 fallback으로 매뉴얼의 공식 수동
   경로(Pilot 2 카메라뷰에서 앱 아이콘 탭)를 유지 — 제품 동작을 막지 않고
   "시작 조작이 자동이냐 원탭이냐"의 차이로만 남는다.

## 결과

- 온보드 프로덕션 서비스(현재 `recorded_pipeline` CLI는 오프라인 개발·테스트용
  진입점이며, 이 자동 기동·FC 구독 기반 활성화를 감싸는 실제 온타깃 서비스는
  아직 없다)는 track-b의 "Frame source를 PSDK Live View로 교체" 작업과 함께
  구현한다 — 하드웨어·PSDK 접근 없이는 검증 불가능한 미확인 DJI 동작에 기반하므로
  지금 맹목적으로 코드를 먼저 짜지 않는다.
- 본 ADR은 §검증 항목이 실기로 확인되는 시점에 ACCEPTED로 갱신하고, fallback이
  채택되면 그 사실과 이유를 함께 기록한다.
