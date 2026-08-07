# KSI Site Intelligence Platform — Final Decision Ledger v1.0

- 상태: APPROVED / FROZEN
- 승인일: 2026-07-24
- 적용 PRD: MASTER_PRD v3.0
- 개정: 2026-08-07 §고객·가치 우선순위 (ADR-KSI-016, 대표자 확정) — 동결 문서의
  개정이므로 근거 ADR 없이 이 줄을 바꾸지 않는다

## 명칭·시장

- 플랫폼: KSI Site Intelligence Platform
- 제품: KSI Site Intelligence
- 저장소: `ksi-site-intelligence-platform`
- 첫 Vertical: 건설현장 안전·공간관리
- 확장: 산업중립 Core + Industry Solution Packs

## 고객·가치

- 구매자: 건설사
- 실사용자: 현장소장·안전관리자
- 우선순위: 시계열 공간 이해 > 공정·변화·물량 > 설계 대비 시공 상태 > 구조물점검
  (2026-08-07 개정, ADR-KSI-016 D2 — 자율 안전순찰은 KSI Safety 제품 축으로 이동)
- UX: 통합 기본 + 제한된 전문가 모드

## 하드웨어·자율성

- MVP: Matrice 4D + RC Plus 2 + Manifold 3
- RC Plus 2가 이착륙·수동인계
- Manifold가 비행 중 인지·탐색·재관찰·우회·복귀
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
