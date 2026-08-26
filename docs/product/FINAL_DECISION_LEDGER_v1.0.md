# KSI Site Intelligence Platform — Final Decision Ledger v1.0

- 상태: APPROVED / FROZEN
- 승인일: 2026-07-24
- 적용 PRD: MASTER_PRD v3.0
- 개정: 2026-08-07 §고객·가치 (ADR-KSI-016) · 2026-08-08 오기 정정 + 선형
  순위 폐기·2축 구조 전환(대표자 확정) · 2026-08-20 공정·상대 물량 첫 상품과
  zero-touch/Copilot 결정(ADR-KSI-022) · 2026-08-21 RC-first Connected Edge와
  선택형 Manifold 직접망 결정(ADR-KSI-023) · 하나의 반응형 Operations Console과
  Pilot 2 비행 전용 화면 경계(ADR-KSI-024) · 근거 중심 다현장 Home과 최근 업데이트
  구조(ADR-KSI-025) · 현장 작업공간과 근거형 AX 계약(ADR-KSI-026) — 동결 문서의 개정이므로 근거 ADR 없이
  이 줄을 바꾸지 않는다

## 명칭·시장

- 플랫폼: KSI Site Intelligence Platform
- 제품: KSI Site Intelligence
- 저장소: `ksi-site-intelligence-platform`
- 첫 Vertical: 건설현장 안전·공간관리
- 확장: 산업중립 Core + Industry Solution Packs

## 고객·가치

- 구매자: 건설사
- 실사용자: 현장소장·안전관리자
- 제품 구조: **Site Intelligence Core(WHAT/WHY) ↔ Autonomous Acquisition(HOW)의
  폐루프** (2026-08-08 개정, ADR-KSI-016 D2). 선형 가치 순위는 폐기했다 —
  플랫폼 기술·분석 기능·임무 유형이 한 목록에 섞여 있어 줄 세우기 자체가 분류
  오류였다. 자율 안전순찰·구조물 점검은 Acquisition 축의 **임무 유형**이며
  서로 순위를 두지 않는다(정본: `ksi_domain.enums.MissionType`).
  전 개정본의 "자율 안전순찰은 KSI Safety 제품 축으로 이동"은 오기였다 —
  이 제품의 범위에 그대로 있다.
- UX: 현장 노트북·컴퓨터의 하나의 반응형 KSI Operations Console + 제한된 전문가 모드.
  모바일은 같은 Web에서 확인 항목·분석·Copilot을 우선하고 임무·재관측·장비 행동은
  노트북으로 안내한다. Home은 다현장 구매자·운영 책임자에게 실제 근거가 있는 확인 현장과
  최근 결과만 브리핑하고, 공간 결과·보고서·조사 이력은 각 현장이 소유한다. RC Plus 2/Pilot
  2에는 KSI 업무 UI를 표시하지 않는다.
- IA/AX: 전역 메뉴는 홈·현장·작업·확인 항목이며, 변화·물량·공간 결과·보고서·조사
  이력은 현장 작업공간이 소유한다. 현장 AI는 저장형 대화와 검증된 citation으로만 답하고,
  외부 반출은 Site별 별도 동의가 없으면 fail-closed한다(ADR-KSI-026).
- 첫 유료 업무: 반복 관측 기반 공정·상대 물량 관리
- 정상 전달: RC Plus 2/Pilot 2가 비행·인터넷 gateway, Manifold 3가 로컬 Edge다.
  사람의 KSI 업무는 Operations Console이 담당한다.
  RC 인터넷은 새 임무 발급 전 필수이고 Manifold SIM은 선택 Add-on이다. USB·SD·
  수동 KMZ는 복구 전용이다(ADR-KSI-023).
- 배치: 정책형 하이브리드(KSI Cloud 제어면 + 현장별 데이터 실행 위치)
- Copilot: 외부 LLM 공급자 중립 adapter, 근거 조회·설명·재관측 초안 전용

## 하드웨어·자율성

- MVP: Matrice 4D + RC Plus 2 + Manifold 3
- RC Plus 2가 Pilot 2 이착륙·수동인계와 지상 인터넷 gateway를 담당한다
- Manifold가 인터넷과 무관하게 비행 중 인지·탐색·재관찰·우회·복귀를 담당한다
- Gateway(RC/Dock)와 Edge(Manifold)는 별도 장치 신원·최소권한을 사용한다
- Manifold SIM 직접망은 전송용 Connectivity Add-on이며 Edge 지능의 조건이 아니다
- Mission Contract 사전 1회 승인
- 현장정책 승인 후 정기임무 자동실행
- 미매핑 공간은 제한속도·거리·행동으로 탐색
- 반개방 공간은 사전 매핑된 안전회랑만

## 안전·완료

- 위험구역 100%, 필수자산·표면 100%, 일반 접근영역 95%
- 서버통신 단절: 유효계약과 안전조건이 유지되면 계속
- RC Link Lost: DJI Flight Controller 정책
- 배터리: 현장별 설정, 기본 예상귀환 + 30% Reserve
- Unknown obstacle: 정지·재관찰·후퇴·확인 후 우회

## 사건·증거

- Critical: Edge 후보 1초, 로컬경보 2초, 서버알림 5초
- High: 10초 이내 확인·알림
- Medium: 최대 30초 재관찰·재검증
- Candidate Clip: 전후 3초
- High Clip: 전후 5초
- Critical Clip: 전후 10초
- 불확실성을 포함해도 위험이 유지될 때만 Confirmed

## 지도·데이터

- 매 비행 Map Delta
- 변화 시 부분재스캔
- 기본 전체갱신 주 1회, 빠른 변화단계 주 2~3회, 안정단계 2~4주
- 일반 Candidate 30일
- 순찰 원본 90일
- Confirmed Event 3년
- Telemetry·Mission 1년
- 감사·조치 3년
- 공간산출물 계약기간 + 90일

## 장비·모델

- 공개데이터와 자체데이터로 범용지원 확대
- 지원단계: DATASET_AVAILABLE → BASELINE_DETECTION → FIELD_VALIDATED → GEO_VALIDATED → RISK_VALIDATED → PRODUCTION_SUPPORTED
- Production Supported만 공식 상용지원

## 사용자 결정권·정확도

- 비행 중 촬영 품질 보충은 서명된 계약과 Capture Policy 범위 안에서 Manifold가 수행
- 범위·비용이 증가하는 재관측은 사용자가 승인
- LLM은 비행 좌표·안전 명령·승인을 생성하지 않음
- MVP 물량은 운영관리용 시점 간 상대값이며 계약 정산·측량급으로 표시하지 않음
