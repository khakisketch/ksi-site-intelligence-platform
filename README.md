# KSI Site Intelligence Platform

KSI는 건설 현장을 반복 관측해 **시공간 상태·변화·진척·물량**으로 만들고, 부족한 증거를
다음 관측 계획으로 연결하는 Site Intelligence 제품이다.

```text
관측 계획 -> 현장 원본 수집 -> 봉인/계보 -> 3D·변화·설계대비 처리
        -> 사람이 검토할 상태/증거 -> 부족한 구역 재관측
```

## Product components

| Product component | Source path | Responsibility |
|---|---|---|
| KSI Operations Console | `apps/dashboard/` | 사람의 의도, 업무 상태, blocker, 복구, 증거 표시 |
| KSI Site Intelligence Core | `services/core/` | Site/Mission/정책/증거와 durable authority |
| DJI Capability Gateway | `services/dji-gateway/` | 장비·provider별 capability/transport adapter와 receipt |
| Artifact Processing Worker | `services/processing-controller/` | 원본 처리 job lease와 계측 orchestration |
| Manifold Edge | `edge/psdk-app/`, `edge/manifold-runtime/` | 로컬 수집·인지·world model·위험·전술 판단 |
| Shared product libraries | `packages/` | domain, contract binding, planning, geo, perception, change/BIM/defect 알고리즘 |

DJI Flight Controller는 안정화·모터·검증된 reactive avoidance·RTH를 계속 소유한다. Core나
LLM은 저수준 비행 좌표/명령을 만들거나 안전정책을 우회하지 않는다.

PSDK Liveview는 Manifold 로컬 acquisition/perception 입력이고 `EDGE_UPLINK`는 bounded
metadata다. 현재 원본은 SD/storage -> field PC -> KSI web upload로 들어오며, 자동
`MEDIA_PULL`/`MEDIA_UPLOAD`는 별도 HIL/실기 증거 전까지 목표 capability다.

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

- 제품 결정: FROZEN
- PRD 모호성: CLOSED
- 실기 Parameter: HIL/Field 검증 후 Versioned Safety Profile로 관리
- 공식 저장소명: `ksi-site-intelligence-platform`
