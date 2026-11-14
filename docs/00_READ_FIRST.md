# 제품 및 개발 기준

충돌 시 이 문서의 범위 판단, [제품 헌법](product/PRODUCT_CONSTITUTION.md), [확정 결정](product/FINAL_DECISION_LEDGER_v1.0.md), [제품 요구사항](product/MASTER_PRD_v3.0.md), [계약](../contracts/), 관련 ADR과 수락 기준 순으로 확인한다. 참고 저장소나 구현 계획은 제품 권한을 만들지 않는다.

[ADR-KSI-039](architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md)는 036/037/038과 이전 제품 문서의 취득 책임 조항을 대체한다. 외부 파생 산출물의 제공과 분석은 계속 적용한다. 비행·자율 취득·전술 인지 및 제어·고객 생산 재구성은 제품 책임 밖이다.

- [런타임과 소스 소유권](../REPOSITORY_STRUCTURE.md), [도메인 불변식](product/DOMAIN_INVARIANTS.md)
- [현재 작업과 출시 제한](ledger/CURRENT.md), [제품 검증 범위](superpowers/product-state.md)
- [현장 메뉴 결정](architecture/ADR-KSI-042-site-navigation-space-analysis.md), [콘솔 계약](design/CONSOLE_CURRENT_SPEC.md), [배포 절차](../deploy/README.md)

검증은 작업 경계에 맞춰 계약·리플레이·실제 렌더를 실행한다. 콘솔 변경은 390/768/1440px에서 사용 흐름과 오류·빈 상태·권한 거부를 확인한다. 장비·호스트·고객 수락은 각각 해당 환경에서 확인한다.
