# KSI Site Intelligence Platform

KSI는 **물리적 현장의 관측을 사람·외부 에이전트·소프트웨어·로보틱스가 재사용하는
근거형 Site State와 Change로 바꾸는 기반**이다. 건설·토공 운영은 첫 시장이지 배타적
정체성이 아니다. 외부 산출물 등록·검사, 데이터 제공과 고정 분석이 현재 재사용 경로다. 고객의 에이전트와
산업용 소프트웨어가 공간데이터 처리·권한·계보·근거 관리를 매번 구축하는 부담을 줄인다.
시간·비용 절감은 실제 고객 사용으로 검증할 목표다.

제품에는 **공간데이터 제공**과 **서버 분석**의 두 경로가 있다. 첫 분석 사례는 WorkArea별
주간 두 시점 지형 변화다. 첫 플랫폼 검증은 DSM·정사영상으로 같은 현장의 분석 요청과
외부 코드용 구역 데이터 활용을 모두 입증한다. UI·선택한 MCP·외부 API 소비 코드는 같은
자산·작업·결과 기록을 사용한다. Point cloud·Mesh·외부 분석 레이어와 추가 클라이언트는
후속 계약·수용 대상이다. [제품 방향](docs/architecture/ADR-KSI-038-spatial-data-and-analysis-platform.md)과
[장기 계획·보완 과제](docs/superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md)는
목표를 정의하며, 전체 기능의 구현·지원 완료를 뜻하지 않는다.

첫 출시에서 KSI는 사진을 3D 지도로 재구성하는 자체 엔진이나 고객용 재구성 서비스를
운영하지 않는다. 장기적으로 비행·자율 취득·전술 인지/제어·고객 production 재구성은 제품 책임 밖이며
관련 출처는 역사적 transitional implementation으로 `archive/acquisition-2026/`에 보존된다
([ADR-KSI-039](docs/architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md)). 고객이 통제하는 현장 PC의 재구성 도구가 만든 결과를 등록·검증·분석해,
외부 시스템과 사람이 재사용할 수 있는 근거형 분석 기록을 제공한다.

```text
고객 관측/재구성 -> 산출물·시점·구역·버전 등록과 검사 -> Core 권한·용도별 적합성
        ├─ 데이터 경로: 자료 탐색 -> 지원하는 구역 데이터 준비 -> 외부 코드 활용
        └─ 분석 경로: 입력 admission -> 고정 분석 -> 결과·근거 조회
                 공통 API / 선택한 MCP / 최소 관리·근거 화면
```

RTK-equipped M4D와 고객 PC/DJI Terra는 초기 현장 검증·재구성 **입력 참조 흐름**이다.
이 문서는 Terra 라이선스·내보내기
호환성·자동 연동·정확도 또는 현장 수용을 주장하지 않는다. RTK FIX도 완성 지도나
물량의 정확도 보증이 아니다. 계약 정산·측량급 결과는 별도 수용 근거 없이는 제품
주장이 아니다. 정확한 책임 경계와 입력별 사용 제한은
[`ADR-KSI-036`](docs/architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md)를
따른다.

## Product components

| Product component | Source path | Responsibility |
|---|---|---|
| KSI Operations Console | `apps/dashboard/` | 사람의 의도, 업무 상태, blocker, 복구, 증거 표시 |
| KSI Site Intelligence Core | `services/core/` | Site/WorkArea/외부 WorkOrder·권한·등록·정책·결과·증거와 durable authority |
| Artifact Processing Worker | `services/processing-controller/` | 외부 산출물 검사·계측, 고정 Analysis, 구역 데이터 준비; Core가 권위를 소유 |
| Bounded MCP adapters | `services/analysis-mcp/`, `services/spatial-data-mcp/` | 같은 Core 기록의 고정 stdio 도구; 독립 권한·계산·스토리지 없음 |
| Shared product libraries | `packages/` | domain, contract binding, geo, change/BIM/defect 알고리즘; 선택적 코드 존재≠공개 포맷 지원 |

Gateway/Edge/비행계획/인지/managed 재구성 출처는 `archive/acquisition-2026/`의 **역사적
증거**이며 현재 제품 구성요소·실행 입구가 아니다. 이동/복원 기록과 잔여 차이는
[P5 통합 감사](docs/audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md)에 있다.

DJI Flight Controller는 안정화·모터·검증된 reactive avoidance·RTH를 계속 소유한다. Core나
LLM은 저수준 비행 좌표/명령을 만들거나 안전정책을 우회하지 않는다.

역사적 취득 계약에서 PSDK Liveview는 Manifold 로컬 acquisition/perception 입력이고 `EDGE_UPLINK`는 bounded
metadata다. 외부 첫 출시 경로의 원본 사진은 고객 장비에 남고, KSI에는 필요한 파생
산출물과 provenance/품질 근거만 등록한다. SD/storage -> field PC -> KSI web raw ingress는
역사적 managed/test 또는 별도 승인 경로로만 해석한다. `MEDIA_PULL`/`MEDIA_UPLOAD`는
이 플랫폼의 현행 개발 후보가 아니며 보존된 취득 계약의 실기 미검증 capability다.

`KSI Safety`는 드론 밖 센서까지 포함하는 별도 다중센서 실시간 안전 운영 제품 구상이다.
그 구상이 이 저장소의 Site Intelligence 안전순찰 Mission 유형을 흡수하거나 대체하지는
않는다. 두 제품이 일부 현장 관측을 공유해도 제품 책임과 코드 모듈은 근거 없이 합치지 않는다.

## Repository navigation

코드 책임·실행 경계·현재 경로는 [`REPOSITORY_STRUCTURE.md`](REPOSITORY_STRUCTURE.md), 현재
문서와 역사적 증거의 구분은 [`docs/DOCUMENT_STATUS.md`](docs/DOCUMENT_STATUS.md)를 따른다.
서비스/패키지 판정과 R3 이동은
[`ADR-KSI-034`](docs/architecture/ADR-KSI-034-service-package-runtime-boundary.md)와
[`R3 migration manifest`](docs/audit/REPOSITORY_MIGRATION_MANIFEST_R3.json)에 기록돼 있다.
각 상위 코드 디렉터리와 이동된 패키지의 `README.md`가 제품명, 책임, 비책임, 소비자와
검증 명령을 설명한다.

## Authoritative Documents

1. `docs/product/PRODUCT_CONSTITUTION.md`
2. `docs/product/FINAL_DECISION_LEDGER_v1.0.md`
3. `docs/product/MASTER_PRD_v3.0.md`
4. `contracts/`
5. Architecture/Acceptance 문서 — 전체 구성 한 장 개요는
   `docs/architecture/00_SYSTEM_OVERVIEW.md`(현행 플랫폼 + 분리된 역사적 취득 그림),
   과거 취득 우선순위(P0~P3)는 ADR-KSI-018의 역사적 기록이며 현재 작업을 선택하지 않는다
6. Reference Adoption 문서
7. Pinned reference repositories

에이전트는 루트 `AGENTS.md`/`CLAUDE.md`를 읽고 위 authority 순서, invariant, contract,
acceptance를 대조한 뒤 담당 모듈의 README/manifest/entrypoint/tests를 확인한다. 구조 문서는
탐색을 돕지만 제품 정본을 대체하지 않는다.

## Reference repositories

- KSI Platform
- KSI-Terra
- KSI-Scout

세 저장소는 읽기 전용 참고 구현이며 Runtime Dependency가 아니다.

## Product status

- 2026-09-30의 최초 문서/보류 기록과 후속 개발 재개는 역사적 단계다. 현재 bounded rebaseline은 [정본 원장](docs/superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md)에 기록돼 있다. P4는 로컬 기술 마감, P5는 서면 승인된 통합 검증이며 실제 진행은 `.opencode/working-state.md`와 원장을 대조한다.
- [P5 통합 감사](docs/audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md)는 로컬 성공·실패·미검증을 분리한다. 아카이브 두 파일의 후속 수정, 전체 타입 오류, 혼합 base Compose와 새 환경/이미지/고객 수용은 열린 조건이다. 전체 정돈·배포 완료를 주장하지 않는다.
- 기존 분석 API·MCP·운영 후보의 로컬 근거는 [FPO 원장](docs/superpowers/plans/2026-09-30-first-pilot-operational-runtime.md)에 있다. 실자료·운영 호스트·고객 두 주기 수용과 새 데이터 제공 경로의 제품 검증은 별도 미완 항목이다.
- 제품 권위: `docs/00_READ_FIRST.md`의 active hierarchy와 accepted ADRs
- 과거 PRD 모호성 기록: CLOSED (현재 작업·우선순위 상태를 뜻하지 않음)
- 실기 Parameter: HIL/Field 검증 후 Versioned Safety Profile로 관리
- 공식 저장소명: `ksi-site-intelligence-platform`
