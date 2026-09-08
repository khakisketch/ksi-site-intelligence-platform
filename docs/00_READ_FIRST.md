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

미디어 경로는 ADR-KSI-033에 따라 분리한다. 현재 정상 원본 ingress는
`SD/저장매체 → 현장 PC → KSI 웹 업로드`, PSDK Liveview는 Manifold 로컬
acquisition/perception 입력, `EDGE_UPLINK`는 bounded EventBundle/EdgeBundle metadata다.
중앙 지속 영상 수신은 핵심 제품 경로가 아니며 자동 원본 반출은 별도
`MEDIA_PULL`/`MEDIA_UPLOAD` HIL 전까지 목표 경로일 뿐이다.

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
