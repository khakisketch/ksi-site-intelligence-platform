# ADR-KSI-026 — 현장 작업공간과 근거형 AX 계약

- Status: Accepted
- Date: 2026-08-23
- Requirements: REQ-UX-101, REQ-WRK-101, REQ-COP-101/102, REQ-SEC-101
- Invariants: INV-002, INV-040/041, INV-050/051, INV-060/061

## Context

공간 결과·보고서·비행 이력은 모두 한 현장에 귀속되는데도 전역 메뉴에 각각 노출되어,
사용자는 계약 ID나 Mission을 먼저 골라야 했다. 또한 내부 `Event` 용어와 장비 식별자가
사용자 판단보다 앞섰고, Copilot은 일회성 질의 표면만 있어 대화·근거·실패를 감사 가능한
업무 기록으로 남기지 못했다.

KSI의 사용자 경험 정의는 다음과 같다.

> KSI는 현장 데이터를 AI가 읽어 무엇이 달라졌고, 왜 중요한지, 지금 무엇을 결정해야
> 하는지를 근거와 함께 제시하고, 사용자의 결정을 다음 관측과 업무로 연결한다.

## Decision

1. 전역 메뉴는 `홈 · 현장 · 작업 · 확인 항목` 네 가지로 제한한다. 비행 임무와 장비
   연결·복구는 `운영 지원`에 둔다.
2. 공간 결과·변화·상대 물량·확인 항목·WorkOrder·조사 이력·보고서는
   `/sites/{siteId}` 현장 작업공간이 소유한다. 작업공간은 `브리핑 · 현장 데이터 ·
   확인 항목 · 작업·조사 · 보고서` 다섯 영역이다.
3. 고객 화면에서는 `Event`를 `확인 항목`으로 부른다. 내부 계약명과 `/events` URL은
   바꾸지 않는다.
4. Home은 다현장 경영 브리핑, 현장 작업공간은 현장 담당자의 근거 검토, Pilot 2는
   드론 운영을 소유한다. Operations Console에 비행 조종 UI를 추가하지 않는다.
5. `SiteWorkspaceView`는 기존 Site·WorkOrder·Event·Processing 원장을 투영할 뿐 없는
   분석·장비 사실을 만들지 않는다.
6. `SiteBriefing`과 `CopilotConversation/Message`는 조직·현장 범위의 append-only
   기록이다. 답변은 citation 검증 뒤 한 번에 저장하며 검증 전 토큰은 표시하지 않는다.
7. 외부 AI는 기본 OFF이고 현장의 별도 `aiEgressAllowed=true` 없이는 호출하지 않는다.
   원본 사진·presigned URL·임의 object key·Raw SQL·승인·Mission·비행 명령은 모델
   표면에 제공하지 않는다.
8. `REVIEW_READY` WorkOrder 전이는 먼저 원장에 확정한다. 브리핑 생성은 후속 projection이며
   실패해도 WorkOrder를 되돌리지 않고 `BLOCKED` 브리핑으로 기록한다. 같은 workspace
   watermark의 완료 브리핑은 재생성하지 않는다.
9. 기존 `/missions`, `/assets`, `/world`, `/reports`, `/settings`, `/coming-soon/*` 링크는
   유지한다. 새 IA는 데이터 migration 없이 Dashboard 이미지 rollback이 가능해야 한다.

## Consequences

- 사용자는 현장명과 필요한 판단으로 시작하며 기술 식별자는 접힌 전문가 정보에서만 본다.
- AI가 꺼져도 기존 현장 데이터·작업·보고서·사람 승인은 그대로 작동한다.
- 다현장 전사 AI는 현장 AI의 근거 정확도와 조직 격리를 검증한 뒤 별도 결정으로 연다.
- UI나 AI 소프트웨어 검증은 DJI capability, zero-touch 또는 closed-loop Field 등급의
  증거가 아니다. 장비 기능은 HIL 전까지 `NOT_VERIFIED`다.
