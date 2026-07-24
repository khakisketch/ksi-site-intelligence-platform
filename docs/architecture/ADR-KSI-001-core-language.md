# ADR-KSI-001 — KSI Core 서버 언어: Python (FastAPI)

- 상태: ACCEPTED (2026-07-25, 대표자 확정)
- 관련: MASTER_PRD v3.0 §19.1 ("Core API: TypeScript 기반 별도 서비스 권장" — SHOULD 이탈)

## 맥락

PRD 19.1은 TypeScript를 권장하나, 같은 날 승인된 재사용 감사는 기존 FastAPI 파이프라인을
"KSI Core의 기반으로 적극 재사용"으로 판단해 두 문서가 충돌했다. 대표자 지시: 레거시 관성이
아니라 최종 제품에 가장 완전한 방향으로 기술 판단할 것.

## 결정

KSI Core는 **Python 3.12 + FastAPI + Pydantic v2 + PostgreSQL/PostGIS**로 구현한다.

## 근거 (레거시 관성 아님)

1. **역할 적합성**: Core의 실체는 지리공간·워크플로 control plane이다 — PostGIS, MapVersion,
   CoverageReport, Mission Contract 서명·발급, Store-and-Forward 동기화, ProcessingJob
   오케스트레이션. 과거 FastAPI를 쓰던 이유(서버 중앙 추론)는 Manifold 3 도입으로 소멸했고,
   추론이 빠진 Core의 병목은 언어가 아니라 DB·스토리지 I/O다. FastAPI(asyncpg)는 이
   워크로드에 충분하며 TypeScript로 얻는 성능 이점이 없다.
2. **지리공간 생태계**: pyproj·shapely·rasterio·GeoAlchemy2 등 좌표계·수직기준·래스터 처리의
   사실상 표준이 Python에 있다. TS 진영(turf.js)은 CRS/수직기준 수준의 처리가 빈약하다.
3. **계약 공유**: Processing worker들(ODM·변화탐지·map compiler·dataset builder)은 Python이
   불가피하다. Core도 Python이면 Pydantic contracts 패키지 하나를 Core+Processing+Replay가
   공유하고, Dashboard(TS)와는 JSON Schema/OpenAPI codegen으로 연결된다 — 계약 SSOT는
   `contracts/schemas/`로 유지.
4. **하드 안전 루프와 무관**: PRD 9.1의 "Python을 하드 안전 루프에 쓰지 않는다"는 Edge 원칙은
   유지된다. Core는 비행 중 필수 제어경로가 아니다 (INV-001).

## 결과

- `services/core`는 FastAPI 앱으로 구현, Next.js Dashboard는 BFF로 유지 (DEC-003).
- PRD §19.1의 SHOULD 이탈은 본 ADR로 기록한다. 문서 권위 순서상 Master PRD 본문과 충돌하는
  구현 결정이므로, PRD 차기 개정 시 §19.1에 본 ADR을 반영한다.
