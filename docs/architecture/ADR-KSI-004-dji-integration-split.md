# ADR-KSI-004 — DJI 연동 이원화: PSDK 우선, Cloud API는 Dock 단계 재개

- 상태: ACCEPTED (2026-07-29, 대표자 확정) → **부분 갱신 (2026-08-14, 대표자 확정)**
- 관련: MASTER_PRD §1.2.C, §20.2(Profile A/B), §28(R7 위험), FINAL_DECISION_LEDGER §하드웨어자율성,
  ADR-KSI-005(연결 아키텍처 갱신), 신규 ADR-KSI-XXX(현장 운용 UX 경계)

## 2026-08-14 갱신 — Cloud API "Dock 전용" 전제가 깨졌다

원래 결정(§결정 2)은 Cloud API를 Dock/Fleet 단계(Phase 5)로 통째로 미뤘다. 그
근거는 "Cloud API = 지상 운영 경로 = Dock 운용의 일부"라는 이해였는데, 이번 재조사로
**Cloud API에는 Dock 없이 Pilot 2 단독으로 쓰는 별도 갈래(`pilot-feature-set`)가
있음**이 확인됐다 — Wayline Management를 포함해, Dock 아닌 Pilot 2/RC Plus 조합으로
서드파티 서버와 직접 통신하는 경로가 DJI 문서에 명시돼 있다.

**현재 상태 — 확인된 것과 미확인인 것을 가른다:**

- ✅ 확인(대표자 실기 확인, 2026-08-14): 조종기(RC Plus 2) 브라우저로 사내 대시보드
  접속 가능. Pilot 2에 서드파티 클라우드 연결 메뉴 존재.
- ⚠ 미확인: 우리 기체(M4D)가 Pilot Cloud 경로에서 실제로 지원되는지. DJI 지원
  기종 표는 M4D를 Dock 쪽에만 적어두는데, 별도 기능 문서는 M4D/4TD가
  Pilot-to-Cloud Live Flight Controls를 지원한다고 적어 **서로 어긋난다** — 문서
  대조만으로 단정할 수 없다.
- ⚠ 미확인(정정 필요했던 항목): 반대 방향(서버 → 매니폴드로 명령을 내려보내는
  MOP 양방향 폐루프)까지 M4D + Manifold 3 조합에서 되는지는 공개 문서로 단정할
  수 없다 — Cloud API의 MOP WebSocket 지원을 명시적으로 추가한 대상은 Matrice
  400이다. 매니폴드 → 서버 단방향 업링크(`DjiCloudApi_SendDataByWebSocket`, PSDK
  전용)는 별개로 문서에 명시돼 있고 이건 M4D/Manifold 3 조합에서 근거가 있다.

**결정 (부분 수정):**

1. **Cloud API 중 "Dock 전용" 기능(Dock 운용·HMS·함대관리)은 여전히 Phase 5로
   연기한다 — 원래 결정 유지.**
2. **Cloud API 중 Pilot 2 경로(경로 파일 자동 배포, 매니폴드→서버 실시간
   업링크)는 조기 채택 후보로 연다** — Dock 확보나 §28 R7 스파이크를 기다리지
   않는다. 대신 위 미확인 두 가지를 실기로 먼저 확인하는 것이 관문이다(Phase 3,
   현장 운용 UX 계획 참조).
3. **서버 → 매니폴드 하향 명령은 이 조기 채택에서 제외한다.** 되는지 문서로
   확정할 수 없는 채로 설계에 넣지 않는다 — 실기로 확인된 뒤 별도 결정.
4. `services/dji-gateway`(빈 골격)에 최소 접속점만 먼저 만들어 위 미확인 항목을
   확인한다 — 전체 규약 구현이 아니라 "붙는지 본다" 수준. 확인 결과에 따라
   본 ADR을 다시 갱신한다.

원래 §맥락·§결과의 논지(둘은 대체재가 아니다, PSDK와 Cloud API는 책임이 다른
경로다)는 그대로 유효하다 — 다만 "Cloud API 전체 = Dock 단계"라는 등식만 틀렸다.

---

## 맥락

DJI 연동에는 책임이 다른 두 경로가 있다.

- **PSDK (Manifold ↔ 기체)**: 기체 위 실시간 경로 — Live View 프레임·텔레메트리
  수신, Edge 인식·로컬 판단. 제품 차별화(Edge 자율성)가 사는 곳.
- **Cloud API (플랫폼 ↔ RC/Dock)**: 지상 운영 경로 — Wayline 임무 배포, Dock 운용,
  기체 상태(HMS)·미디어 동기화, 함대 관리.

둘은 대체재가 아니다. 특히 DJI 문서상 "Dock 3 + M4D 제3자 Payload 미지원"[PRD R7]
이므로 Dock 운용(Profile B)에서는 Manifold 탑재 자체가 불가할 수 있고, 그 경우
Cloud API가 유일한 플랫폼-기체 통신 경로가 된다.

## 결정

1. **MVP(Profile A, Edge-first)는 PSDK 경로만 사용한다.** RC Plus 2 운영자가
   이착륙을 담당하고, Manifold이 인식·판단하며, 안전 이벤트는 DJI 어느 쪽에도
   의존하지 않는 **자체 Edge→Core 멱등 동기화 채널**(offline_sync 계약)로 올린다.
2. **DJI Cloud API Gateway 구현은 연기한다 — 취소가 아니다.** Dock/Fleet 단계
   (Phase 5, Profile B) 진입 시 재개하며, 그 시점의 관문은 Dock 3 + M4D 조합의
   Capability Spike(제3자 payload 제약 실검증)다.
3. `services/dji-gateway`는 빈 골격으로 유지한다(경계 예약). Cloud API app key
   등록 등 행정 절차도 함께 연기한다. PSDK 접근권 신청은 연기 대상이 아니라
   최우선 행정 항목이다.

## 결과

- 하드웨어 확보 전 선행 개발은 Cloud API가 아니라 Edge→Core ingest(Core 서버측
  배선)에 투입한다.
- Profile B 진입 시 이 ADR을 재개 조건과 함께 갱신한다 — Cloud API 없이 Dock
  운용을 설계하는 우회, 또는 Cloud API 없이 함대 관리를 자체 구현하는 중복은
  이 ADR 위반이다.
