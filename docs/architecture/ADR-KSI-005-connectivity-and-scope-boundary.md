# ADR-KSI-005 — 연결 아키텍처 확정 + 스코프 경계 재확인 (실기 검증 후)

- 상태: ACCEPTED (2026-07-29, 대표자 확정 — Manifold 3 실기 도착·M4D 장착 검증 세션)
- 관련: ADR-KSI-004(DJI 연동 이원화), FINAL_DECISION_LEDGER_v1.0 §하드웨어·자율성·사건과증거,
  CLAUDE.md Control boundaries, INV-001/002

## 맥락

Manifold 3 실기 입수 후 다음이 실측으로 확인됐다:

- Manifold 3의 물리 포트는 E-Port(호환 기체 전용, 24V 급전)와 USB-C(호스트, PD 겸용)
  둘뿐이며 Wi-Fi/이더넷 잭이 내장되어 있지 않다(공식 매뉴얼 v1.2 §1.1).
- USB-C는 컴퓨터 직결을 지원하지 않는다(호스트끼리 마주 물림) — 벤치 개발 접근은
  USB-C 이더넷 어댑터를 경유해야 한다.
- M4D 장착 시 E-Port가 급전을 전담하고, USB-C는 완전히 별개로 비어 있다(실기
  검증: E-Port 장착 상태에서 스마트폰을 USB-C에 연결 → 정상 인식). 매뉴얼의
  "Connect Manifold 3 to aircraft, then connect USB drive to USB-C port" 절차와
  일치.
- DJI Cloud API 아키텍처는 드론이 서드파티 클라우드에 직접 붙을 수 없고 게이트웨이
  (RC/Dock)를 경유하는 구조다 — ADR-KSI-004가 이미 Cloud API를 Phase 5로 미룬
  결정과 일치하며, 본 ADR은 그 대안으로 PSDK-only 단계의 자체 연결 경로를 정한다.

이 결과로 두 갈래 논의가 있었다: ① 비행 중 Manifold ↔ Core 연결을 무엇으로
할 것인가, ② 그 연결로 무엇을 태울 것인가(범위). 아래에 확정한다.

## 결정 1 — 연결 물리 계층

| 국면 | 경로 | 비고 |
|---|---|---|
| 벤치 개발 | USB-C 이더넷 어댑터 → 공유기 | SSH 인계·환경 인벤토리·B2 검증용. 프로덕션 경로 아님 |
| 실비행 | **USB-C 테더링 지원 LTE 포켓 라우터**(국내 데이터 유심/eSIM) | 상시 부착. E-Port와 독립이라 상시 유지 가능(실기 검증 완료) |
| 현장 임시 재지시 | 운용자 스마트폰 USB 테더링 | 라우터 없이도 즉석 계약 갱신 가능 |

Wi-Fi 상시 링크는 채택하지 않는다 — 순찰이 이동을 전제하는 이상 AP 반경 제약이
"상시"라는 요구 자체와 맞지 않는다.

**정정(2026-07-29, 같은 세션 내 재확인)**: 최초 조사에서 DJI Cellular Dongle 2를
불채택으로 판단했으나, 이는 M4D+Dock 3 매뉴얼(§6.3, RC↔기체 OcuSync 링크 보강
용도의 "Enhanced Transmission" 절)만 읽고 내린 **불완전한 결론이었다**. PSDK 개발자
문서(`payload-sdk-tutorial/.../advanced-function/access-internet.html`)는 자바스크립트
렌더링 SPA라 최초 조사에서 못 읽었는데, 이후 raw JS 청크에서 원문을 직접 추출해
확인한 결과, **같은 Enhanced Transmission 모듈(=Cellular Dongle 2)이 별개의 두
기능을 제공한다**:

1. RC↔기체 OcuSync 링크 보강(Dock 매뉴얼 §6.3 — FlightHub2 Remote Debugging으로 활성화)
2. **Manifold 3 페이로드 네트워크 접근**(공식 문서 인용) — "By default, the payload
   network access function is enabled and no additional operations are required
   (this depends on the Enhanced Transmission module being installed on the
   aircraft and the 4G network function being normal). Supports Matrice 400,
   Matrice 4TD/4D, Matrice 4T/4E aircraft." 게다가 "This function is currently
   supported only by Manifold 3" — DJI가 이 기능을 Manifold 전용으로 설계했다.

**결론(정정): Cellular Dongle 2 + SIM을 M4D에 장착하면 Manifold 3가 E-Port를 통해
자동으로 인터넷에 접속된다 — Dock/FlightHub2 무관, 설정 불필요.** 이는 서드파티
USB-C LTE 라우터 대비 ① DJI 공식 지원 ② Manifold의 유일한 USB-C 포트를 점유하지
않음 ③ 별도 마운트 설계 불필요라는 이점이 있어 **상시 LTE 경로의 1순위 후보로
재채택**한다. 남은 미확인 사항(국내 통신사 서비스 지원·유심 인식·실제 처리량)은
실기 SSH 확보 후 `ip addr`/`ping`/`curl`로 실측 검증한다 — 문서상 지원과 현장 실측은
별개다(green≠작동). 서드파티 USB-C LTE 라우터는 Cellular Dongle 2의 지역/통신사
제약이 실측에서 문제로 확인될 경우의 대안으로 격하한다(폐기 아님).

Dock 3는 여전히 불요하다(ADR-KSI-004 유지) — RC Plus 2 운용자의 이착륙 모델로
제품이 완전히 성립하며, 상시 LTE 확보로 Dock 없이도 "복귀 후 자동 업로드"가
"비행 중 실시간 업로드"로 자연 승격된다(§결정 2 참조).

## 결정 2 — 실시간 데이터 스코프 (텔레메트리 스트림 vs 인시던트 push)

**채택 — 비행 중 EventBundle push.** 기존 edge-sync는 저장 후 전달(store-and-forward,
fsync 내구 + 멱등 재전송)로 이미 설계되어 있다. 링크가 상시면 이 설계가 코드 변경
없이 그대로 "거의 실시간"이 된다 — 새 채널이 아니라 기존 채널의 자연스러운 개선.

**제외 — 드론 위치 텔레메트리 스트림 및 라이브 지도(드론 위치·감지 객체 위치
실시간 표시).** 사유:

1. 실시간 영상 관제 니즈는 RC Plus 2의 네이티브 RTMP 출력으로 이미 충족된다 —
   우리가 재구현할 이유가 없다(엔지니어링 비용 0인 대안이 이미 존재).
2. 신뢰성 프로파일 불일치 — 텔레메트리 스트림은 "링크가 지금 살아있어야 의미
   있는" 기능이라 LTE 불안정성이 곧 기능 품질 저하로 드러난다. 반면 EventBundle
   push는 유실 없이 지연만 발생하므로 불안정한 링크 위에서도 정확성이 보존된다
   (green≠작동 원칙 — 불안정한 컴포넌트 위에 신뢰성이 요구되는 기능을 얹지 않는다).
3. 감지 객체의 실세계 좌표 추정은 드론 자세·짐벌 각도·지형 모델을 요구하는
   별도 기하 계산이며, **정확도를 실측 검증한 적이 없다** — 검증 전 지도 핀
   노출은 틀린 정보를 "파악됐다"고 제시하는 것과 같다.

사후 안전관리(블랙박스) 가치는 유실되지 않는다 — 각 EventBundle은 발생 시점의
위치·자세 계보(RunContext lineage)를 이미 포함하므로, 실시간 스트림 없이도
"언제 어디서 감지됐나"는 사후에 정확히 복원된다.

이 스코프는 **P2 백로그로 보류**하며, 재개 조건은: ① 감지 객체 실좌표 정확도를
실측 좌표 대조로 검증, ② 매핑 산출물(포인트 클라우드/메시) 파이프라인이 갖춰져
좌표 변환 계산이 자연스럽게 재사용 가능한 시점.

## 결정 3 — 회피 경계 재확인 (하드웨어 도착 계기 재확인, 결정 자체는 기존 유지)

FINAL_DECISION_LEDGER §하드웨어·자율성의 "Manifold가 비행 중 인지·탐색·재관찰·
**우회**·복귀"는 **미션/전술 레벨 재경로 요청**(ActionIntent 발행 — 예: 위험
후보 구역을 피해 다른 관찰 지점으로)을 뜻하며, **저수준 반응형 충돌회피의
재구현을 뜻하지 않는다.** 그 경계는 CLAUDE.md Control boundaries에 이미 명시:

> DJI Flight Controller owns stabilization, low-level flight, **verified reactive
> avoidance** and RTH. Manifold owns tactical perception... **local mission
> decisions**.

즉 Manifold는 "저기 위험하니 그 구역 임무를 재조정하자"를 결정하고 서명된
ActionIntent로 요청할 뿐, "지금 앞에 장애물이 있으니 즉시 꺾어라"는 M4D FC의
검증된 영역이며 우리가 중복 구현하지 않는다. 실기 확보를 계기로 이 경계가
개발 범위에서 혼선 없이 지켜지도록 본 ADR에 재확인해 못박는다.

## 결과

- 하드웨어 구매 목록: USB-C 이더넷 어댑터(벤치, 즉시) + **DJI Cellular Dongle 2 +
  나노유심**(실비행 전, 1순위 — 정정 결과 반영). 국내 통신사 서비스 지원이 실측에서
  막히면 USB-C 테더링 LTE 포켓 라우터를 대안으로 조달한다.
- Core/UI 개발 범위에서 "라이브 위치 대시보드"는 로드맵에서 제거하고, "인시던트
  피드(비행 중 실시간 가능)"만 근시일 스코프에 포함한다.
- 향후 "왜 라이브 지도가 없냐"는 재논의는 본 ADR의 재개 조건 충족 여부로 판정한다.
