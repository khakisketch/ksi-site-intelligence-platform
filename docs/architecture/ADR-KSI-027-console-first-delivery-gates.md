# ADR-KSI-027 — Operations Console 우선 완성과 단계별 제품 게이트

- Status: Accepted
- Date: 2026-08-24
- Amended: 2026-08-26 — 대표자 결정으로 candidate adapter 선구현과 승인된 제한적
  장비 write를 Phase 3에 허용한다. 운영 활성화와 비행 제어 금지는 유지한다.
- Requirements: REQ-UX-101, REQ-WRK-101, REQ-COP-101/102, REQ-SEC-101
- Invariants: INV-002, INV-040/041, INV-050/051, INV-060/061
- Supersedes: Dashboard 구현 순서에 관한 이전 S3 MVP 가정

## Context

KSI는 드론 조종 화면이나 단순 지도·물량 조회 제품이 아니다. 현장 데이터를 바탕으로
`무엇이 달라졌는지 → 왜 중요한지 → 사용자가 무엇을 결정해야 하는지`를 근거와 함께
제시하고, 그 결정을 다음 조사와 업무로 잇는 현장 지능 제품이다.

그러나 장비가 아직 연결되지 않은 상태에서 DJI adapter, 자동 전송, 직접망, Dock 기능을
화면의 약속처럼 먼저 구현하면 실제 증거가 없는 제품 동선과 가짜 capability가 생긴다.
반대로 Console이 현장명·근거·결정으로 읽히지 않으면 장비가 연결된 뒤에도 운영자는
계약 ID, 파일, 장치 상태를 먼저 해석해야 한다.

## Decision

### D1 — 완료 순서는 Console → 합성 Staging/AI → HIL → 통합 → Field Pilot이다

| 단계 | 목적 | 지금 허용하는 산출물 | 완료 증거 | 금지 또는 보류 |
|---|---|---|---|---|
| Phase 0 | 제품·UX 정본 고정 | ADR, 용어, 상태·권한 matrix, acceptance | 정본 간 충돌 없음 | capability를 문서만으로 VERIFIED 처리 |
| Phase 1 | Operations Console 완성 | 실제 Core 읽기 projection, 현장·작업·확인 항목 UX, 반응형/접근성 회귀 | 390/768/1024/1440 Chromium + 계약 테스트 | 가짜 DJI·AI 결과·운영 write 우회 |
| Phase 2 | 합성 Cloud/AI Staging | 승인된 합성 데이터, OIDC/TLS/backup restore, 근거형 Copilot adapter | 조직 scope, egress, citation, restore 증거 | 고객 데이터·외부 production 배포 |
| Phase 3A | RC-first code/SDK 준비 | 다섯 path candidate adapter, fail-closed routing, HIL approval/evidence 도구 | 공식 SDK build·금지 API gate·기본 OFF·`NOT_VERIFIED` | 코드 존재를 장비 지원으로 해석 |
| Phase 3B | 승인된 제한적 HIL | read-only 관찰 후 승인 envelope에 고정된 DPK 설치·재시작과 합성 artifact 전송 | 기체·RC·Manifold·펌웨어·transport·원본 log/digest | 승인 범위 밖 device write, flight, camera/gimbal write |
| Phase 4 | 검증 기능 통합 | HIL 통과 capability만 사용한 계약·미디어·처리 흐름 | 경로별 idempotency·recovery·운영 UX | 미검증 adapter 기본 활성화 |
| Phase 5 | 단일 고객 유료 Pilot | FIELD-0a/0b/1/2, 두 epoch의 사람 승인 폐루프 | Mission→Media→Processing→Result lineage와 실증 | 다중 tenant 일반 출시 |

Phase는 기능 목록이 아니라 증거 등급이다. 앞 단계의 테스트 통과는 뒤 단계의 실제 장비
수용을 대체하지 않는다.

### D2 — 화면은 역할별로 분리한다

- **Home**은 다현장 책임자·경영진이 어느 현장을 살펴봐야 하는지 여는 포트폴리오 입구다.
- **현장 작업공간**은 현장 담당자가 근거를 읽고 판단·작업·보고서를 이어 가는 기본 공간이다.
- **Pilot 2 / RC Plus 2**는 비행과 Gateway 연결을 소유한다. KSI 업무 UI나 AI 판단 화면을
  표시하지 않는다.
- 모바일은 같은 Console의 읽기·확인·분석·Copilot 표현이며 운영 승인·Mission 발급·장비와
  복구 쓰기 행동은 노트북에서만 시작한다. 이는 UX 절차이고 Core RBAC의 대체물이 아니다.

### D3 — 실제 원장과 검증된 분석만 화면의 사실이다

`SiteWorkspaceView`와 Home projection은 Site, WorkOrder, Event, Processing의 기존 조직 범위
원장을 투영한다. 이미지·수치·상태·AI 답변을 비어 있는 자리를 채우기 위해 만들지 않는다.
부분 조회 실패는 `0건`이 아니라 실패/알 수 없음으로 표시한다.

### D4 — AI는 근거형 대화와 초안까지만 한다

현장 AI는 조직·현장 범위, `aiEgressAllowed`, allowlisted tool, citation 검증이 모두 충족될
때만 작동한다. AI는 재관측 초안을 만들 수 있지만 승인, Mission 발급, 비행 좌표 또는
기체 명령을 만들거나 실행할 수 없다.

## Consequences

- 구현 우선순위는 새 Dashboard 화면을 많이 만드는 것이 아니라 `현장명 → 근거 → 사람의
  결정 → 다음 작업`을 모든 핵심 route에서 끊기지 않게 만드는 일이다.
- Legacy URL과 수동 KMZ/SD/USB/folder ingest는 복구 경로로 유지한다. 새 IA에는 데이터
  migration이 없다.
- HIL 이전의 DJI capability는 모두 `NOT_VERIFIED`이며, 제품 UI에서 지원 또는 자동 실행처럼
  보이면 안 된다.
- 실제 외부 Cloud, IdP, 고객 데이터, 장비 write/DPK/credential/flight, commit/push/release는
  해당 별도 승인과 게이트 없이는 수행하지 않는다. Phase 3B의 장비 write 승인은
  session·device·DPK digest·허용 operation·만료시각을 묶은 envelope로 제한한다.

## Rollback

Phase 1 Dashboard 변경은 기존 URL·Core 원장·Mission Contract를 바꾸지 않는다. 이전
Dashboard 이미지로 복귀할 수 있으며, Copilot/briefing/Cloud adapter/Bridge/Dock은 각 feature
flag로 독립 비활성화한다. 활성 Mission Contract는 단순 네트워크 손실로 취소하지 않는다.
