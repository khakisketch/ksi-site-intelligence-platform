# 00 — Read First

## 문서 권위 순서

충돌 시 위 문서가 아래 문서보다 우선한다.

1. `docs/product/PRODUCT_CONSTITUTION.md`
2. `docs/product/FINAL_DECISION_LEDGER_v1.0.md`
3. `docs/product/MASTER_PRD_v3.0.md`
4. `contracts/`
5. Architecture Decision
6. Acceptance Criteria와 Traceability
7. Reference Adoption Matrix
8. 참고 저장소 코드·문서
9. 과거 Commit Message와 TODO

참고 저장소 코드가 Master PRD와 다르면 참고 코드를 따르지 않는다.

저장소의 현재 owner/purpose/runtime 구조는 `REPOSITORY_STRUCTURE.md`, 문서의
ACTIVE/HISTORICAL/SUPERSEDED 라우팅은 `docs/DOCUMENT_STATUS.md`가 소유한다. 두 문서는
제품 결정보다 아래의 repository-governance 정본이며 제품 의미나 현재 capability 상태를
독자적으로 바꾸지 않는다.

미디어 경로는 ADR-KSI-033에 따라 분리한다. `SD/저장매체 → 현장 PC → KSI 웹 업로드`는
managed/test 또는 별도 승인 source-media ingress이고, PSDK Liveview는 Manifold 로컬
acquisition/perception 입력, `EDGE_UPLINK`는 bounded EventBundle/EdgeBundle metadata다.
외부 첫 출시의 customer-owned reconstruction result path는 ADR-KSI-036 D6을 따른다.
중앙 지속 영상 수신은 핵심 제품 경로가 아니며 자동 원본 반출은 별도
`MEDIA_PULL`/`MEDIA_UPLOAD` HIL 전까지 목표 경로일 뿐이다.

API-first 토공 분석·통합 작업은 [ADR-KSI-037](architecture/ADR-KSI-037-api-first-earthwork-evidence-and-integration.md)와
그 [첫 요청 설계](design/API_FIRST_EARTHWORK_FIRST_REQUEST_CONTRACT.md)를 함께 읽는다.
첫 분석 사례의 완결 MVP는 WorkArea별 주간 2시점 관측 지형 물량 변화 검토다. API·향후 MCP·UI는
같은 계산·근거 기록을 조회하는 목표이며, 이 문서만으로 endpoint, MCP server, vendor,
자동 비행 또는 제품 상태 변경을 추정하지 않는다. 현재 slice와 다음 작업은
`superpowers/product-state.md`가 slice close에서만 갱신한다.

2026-09-30의 [ADR-KSI-038](architecture/ADR-KSI-038-spatial-data-and-analysis-platform.md)은
상위 제품 목표를 외부 에이전트·산업용 소프트웨어용 공간데이터·분석 기반으로 명확히 한다.
데이터 제공과 분석의 두 경로를 두며 첫 플랫폼 검증은 DSM·정사영상의 외부 구역 데이터
활용과 기존 분석 사례를 함께 입증한다. 제품 전체 범위·고객 해석은 038을, 기존 분석의
계산·권위·정확도·수용 계약은 037을 읽는다. [SDP-20260930](superpowers/plans/2026-09-30-spatial-data-platform-roadmap.md)이
장기 작업과 보완 결정을 연결한다. 2026-09-30 최초 문서/보류 기록은 역사적 단계이며,
후속 개발 재개와 현재 bounded rebaseline의 승인·진행은
[정본 원장](superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md)을 따른다.
이번 명시적 방향 개정에 따른 product-state Goal/계획 연결은 slice close나 완료 판정이 아니다.

2026-10-07의 [ADR-KSI-039](architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md)은
장기 제품 책임 경계다: 비행·자율 취득·전술 인지/제어·고객 production 재구성은 Site Intelligence의
장기 책임 밖이며, 취득·Edge 출처는 역사적 transitional implementation이다. P3에서
`archive/acquisition-2026/`으로 이동했고 현재 플랫폼 실행·지시 입구가 아니다.
Constitution·Decision Ledger·PRD와 ADR-KSI-037 D6/ADR-KSI-038 취득 조항의 책임 라우팅은 039가
supersede하고, 수치·원본·불변식·EXT-VAL·역사적 milestone 증거는 바꾸지 않는다.

`KSI Safety`는 별도 제품 구상이다. 드론 밖 센서까지 포함하는 다중센서 실시간 안전
운영 제품이며, 이 저장소의 Site Intelligence의 안전순찰 Mission을 흡수하거나 대체하지
않는다. 겹치는 현장 관측이 있다는 이유만으로 제품 책임이나 코드 모듈을 합치지 않는다.

## 작업 전 질문

- Requirement ID가 무엇인가?
- 수용기준은 무엇인가?
- Core, Edge, Processing, Dashboard, DJI Gateway 중 누가 소유하는가?
- 기존 저장소에서 참고할 자산은 무엇인가?
- ADOPT, EXTRACT, PORT, REFERENCE_ONLY, REPLACE, REMOVE 중 무엇인가?
- 라이선스·데이터 권리가 확인됐는가?
- 실제 장비 Spike가 필요한가?

## 구현 금지

- Reference repository에서 직접 import
- 서버 프레임별 비행제어
- LLM의 비행좌표 생성
- Production mock fallback
- RTK Fix를 절대정확도라고 표시
- 단일 프레임 즉시 위반 확정
- 미검증 장비를 상용지원으로 표시

전체 도메인 불변식(강제 지점 포함)의 정본은 `docs/product/DOMAIN_INVARIANTS.md`다.

## 2026-09-06 terrain-aware planning route

[ADR-KSI-035](architecture/ADR-KSI-035-terrain-aware-planning-and-pilot-execution.md) is the
approved design baseline for deterministic KSI planning and Pilot-default execution. Read its
[design contract](design/TERRAIN_AWARE_OBSERVATION_PLANNING_CONTRACT.md),
[acceptance](acceptance/TERRAIN_AWARE_PILOT_MVP_ACCEPTANCE.md), and
[successor roadmap](goals/TERRAIN_AWARE_PLANNING_ROADMAP.md) before planning related runtime
work. The approval is not evidence of runtime support, DJI/Pilot compatibility, or field safety.

## 2026-09-06 customer reconstruction direction

[ADR-KSI-036](architecture/ADR-KSI-036-customer-reconstruction-and-result-ingress.md) is the
accepted first-release product direction: customers reconstruct on their own equipment and KSI
registers, verifies, and analyzes exported artifacts. Its bounded Core registration and byte-seal
API has local software evidence; see the [ingress verification audit](audit/EXTERNAL_RECONSTRUCTION_INGRESS_API_VERIFICATION.md).
That evidence is not vendor/export compatibility, a license approval, deployment, or product
release. ADR-KSI-030's managed NodeODM profile and historical results remain immutable managed/test
scope; do not weaken INV-051/053/060 or infer quantitative eligibility from registration.

Registration and list/detail responses return the server-issued opaque `submissionRef` for a
revision. Clients use that returned `ers-v1-` plus 64-lowercase-hex reference on the three revision
routes; they must not construct a route from the customer `submissionId`. The raw customer ID remains
the declaration, journal, and object-key identity.

The subsequent Human decision keeps originals on customer equipment; normal first-release
registration does not require full raw upload. KSI holds submitted derived outputs and evidence.
Ortho-only registration is allowed; missing DSM or other evidence restricts dependent claims,
not every use. Read ADR-KSI-036 D4/D5 and the
[active release implementation plan](superpowers/plans/2026-09-06-external-reconstruction-release.md).
The 2026-09-20 D6 clarification makes customer-controlled DJI Terra on the field PC the initial
MVP reconstruction **reference workflow** with RTK-equipped Matrice 4D as the initial
field-validation equipment. It does not verify a Terra license or export, create a KSI provider
integration, or establish RTK/map/settlement accuracy. KSI is an artifact-inspection,
compatible-comparison, relative-quantity/evidence, workflow, and re-observation product; it is
not a proprietary photogrammetry engine or a customer production reconstruction service.

The earlier SD/PC/raw-upload and KSI-managed NodeODM description remains existing managed/test
implementation and historical evidence, not the approved customer-workstation first-release
target. Preserve managed source-authority and ProcessingJob rules; do not infer their removal.

## P3 acquisition separation (Task 6, 2026-10-08)

Acquisition-only sources (edge native trees, `services/dji-gateway`, the
mission/perception/equipment packages, their tests and edge tooling) moved
blob-identical to `archive/acquisition-2026/` per
`docs/audit/PHYSICAL_SITE_MOVE_DECISIONS_v1.csv`. The archive is historical
evidence only — never a runtime import path, workspace member, production
build context, or pytest/mypy/ruff target. The design-owned P4 Console cleanup
is now technically closed locally (`7f44d11`); its current Home/Sites/five-tab
workspace no longer mounts acquisition screens/actions. P5's approved
[integrated audit](audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md) separates
local evidence, the two historical post-move adaptations, and open runtime/customer gates.
Archived instructions are provenance only; the root `AGENTS.md` governs current work.
