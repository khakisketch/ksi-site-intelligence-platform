# KSI Site Intelligence Platform

KSI는 **외부에서 생성한 현장 공간데이터를 등록·검사·구조화하고, 필요한 데이터와
재현 가능한 분석 결과를 API·MCP로 제공하는 데이터·분석 기반**이다. 고객의 에이전트와
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
운영하지 않는다. 고객이 통제하는 현장 PC의 재구성 도구가 만든 결과를 등록·검증·분석해,
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
| KSI Site Intelligence Core | `services/core/` | Site/Mission/정책/증거와 durable authority |
| DJI Capability Gateway | `services/dji-gateway/` | 장비·provider별 capability/transport adapter와 receipt |
| Artifact Processing Worker | `services/processing-controller/` | 제출 산출물 검사·계측과 managed/test processing orchestration |
| Manifold Edge | `edge/psdk-app/`, `edge/manifold-runtime/` | 로컬 수집·인지·world model·위험·전술 판단 |
| Shared product libraries | `packages/` | domain, contract binding, planning, geo, perception, change/BIM/defect 알고리즘 |

DJI Flight Controller는 안정화·모터·검증된 reactive avoidance·RTH를 계속 소유한다. Core나
LLM은 저수준 비행 좌표/명령을 만들거나 안전정책을 우회하지 않는다.

PSDK Liveview는 Manifold 로컬 acquisition/perception 입력이고 `EDGE_UPLINK`는 bounded
metadata다. 외부 첫 출시 경로의 원본 사진은 고객 장비에 남고, KSI에는 필요한 파생
산출물과 provenance/품질 근거만 등록한다. SD/storage -> field PC -> KSI web raw ingress는
기존 managed/test 또는 별도 승인 경로로만 해석하며, 자동 `MEDIA_PULL`/`MEDIA_UPLOAD`는
별도 HIL/실기 증거 전까지 목표 capability다.

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
   `docs/architecture/00_SYSTEM_OVERVIEW.md`(두-폐루프 원칙 + 현재 도달점),
   실행 우선순위(P0~P3)는 `docs/architecture/ADR-KSI-018` 참조
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

- 2026-09-30: 플랫폼 방향·문서·장기 계획 반영. 사용자 지시로 개발은 보류 중이며 재개 기록은 `.opencode/working-state.md`와 그 named ledger를 따른다.
- 기존 분석 API·MCP·운영 후보의 로컬 근거는 [FPO 원장](docs/superpowers/plans/2026-09-30-first-pilot-operational-runtime.md)에 있다. 실자료·운영 호스트·고객 두 주기 수용과 새 데이터 제공 경로의 제품 검증은 별도 미완 항목이다.
- 제품 권위: `docs/00_READ_FIRST.md`의 active hierarchy와 accepted ADRs
- 과거 PRD 모호성 기록: CLOSED (현재 작업·우선순위 상태를 뜻하지 않음)
- 실기 Parameter: HIL/Field 검증 후 Versioned Safety Profile로 관리
- 공식 저장소명: `ksi-site-intelligence-platform`
