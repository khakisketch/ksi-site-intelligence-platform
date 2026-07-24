# Architecture Decisions v3.0 — Final Supplement

## ADR-F001 — Edge-first control

비행 중 인지·추적·위험판단·관측점·로컬 경로는 Manifold가 소유한다. Core의 프레임별 제어는 금지한다.

## ADR-F002 — Flight Controller authority

DJI Flight Controller가 자세·모터·기본 장애물 회피·RTH·RC Link Lost의 최종 소유자다.

## ADR-F003 — Mission Contract

사용자는 임무 전 Versioned·Signed Mission Contract를 한 번 승인한다. 현장 정책 승인 후 정기 임무 자동 실행을 지원한다.

## ADR-F004 — Offline autonomy

서버 통신 단절 중에도 계약과 안전조건이 유효하면 임무를 계속한다. RC Command Link 단절은 DJI 정책을 따른다.

## ADR-F005 — Coverage completion

완료조건은 필수 위험구역 100%, 필수 자산·표면 100%, 접근가능 일반영역 95% 이상이다.

## ADR-F006 — Battery

예상귀환 에너지 + 현장 Reserve를 사용하고 기본 Reserve는 30%다. DJI 보호판단이 우선한다.

## ADR-F007 — Event evidence

Critical/High/Medium SLO와 Candidate/High/Critical 전후 3/5/10초 Evidence 정책을 적용한다.

## ADR-F008 — Cross-industry platform

공통 Site Intelligence Core를 유지하고 산업별 Solution Pack으로 확장한다.

## ADR-F009 — Reference repositories

KSI Platform, KSI-Terra, KSI-Scout는 읽기 전용 Submodule이며 직접 Runtime Import를 금지한다.
