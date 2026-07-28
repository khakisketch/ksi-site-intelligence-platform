# ADR-KSI-004 — DJI 연동 이원화: PSDK 우선, Cloud API는 Dock 단계 재개

- 상태: ACCEPTED (2026-07-29, 대표자 확정)
- 관련: MASTER_PRD §1.2.C, §20.2(Profile A/B), §28(R7 위험), FINAL_DECISION_LEDGER §하드웨어자율성

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
