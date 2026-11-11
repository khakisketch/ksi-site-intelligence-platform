# 플랫폼 책임 전환 수락 조건

고객 원본·재구성 및 비행·전술 제어는 [ADR-KSI-039](../../architecture/ADR-KSI-039-physical-site-intelligence-and-acquisition-separation.md)의 책임 경계를 따른다. 외부 소프트웨어와 에이전트는 범위가 제한된 API/MCP를 사용한다.

- 이관은 승인된 경로·개정·해시와 롤백을 결속한다. V1/V2 의미, 조직·구역 권한, AI 반출, 원본/revision/digest, 저널 재생, 불변 결과와 수치 호환성, 유한 자원을 보존한다.
- [R3 이관 매니페스트](../../audit/REPOSITORY_MIGRATION_MANIFEST_R3.json)와 취득 아카이브는 고정 검증 입력이다. 민감 자료나 자격 증명을 검증 산출물에 포함하지 않는다.
- 외부 AI 호스트의 보호 입력, 서명, 격리, 복구, 고객 원본 사용권 및 독립 수락을 실환경별로 검증한다. 변경 가능 작업은 [현재 원장](../../ledger/CURRENT.md)을 따른다.
