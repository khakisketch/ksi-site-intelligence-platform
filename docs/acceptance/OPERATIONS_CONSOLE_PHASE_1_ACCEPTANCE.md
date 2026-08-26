# Operations Console Phase 1 수용 기준

- Status: PASS — Phase 1 software UI/UX baseline
- Date: 2026-08-25
- Requirements: REQ-UX-101, REQ-WRK-101, REQ-COP-101/102, REQ-SEC-101
- Invariants: INV-002, INV-040/041, INV-050/051, INV-060/061
- Scope: Dashboard/Core의 실제 읽기 계약과 UX. HIL/Field capability 검증은 포함하지 않음.

## A. 제품 동선

| ID | Given | When | Then |
|---|---|---|---|
| UX-01 | 로그인한 다현장 책임자 | Home 진입 | 실제 원장 기준 `전체 N곳 · 확인 필요 M곳`과 현장당 한 개의 우선 사유를 본다 |
| UX-01a | 확인할 운영 안건이 1건 이상 | Home 진입 | 큰 시각 캐러셀에서 실제 우선 사유와 같은 현장의 근거 또는 정직한 이미지 부재 상태를 본다 |
| UX-01b | 확인할 운영 안건이 0건이고 등록 현장이 있음 | Home 진입 | 텍스트 빈 상태로 축소되지 않고 같은 큰 시각 영역에서 최근 현장을 선택하며, 0건이 정상·안전 보증이 아님을 본다 |
| UX-01c | `UNMAPPED` 현장이 있음 | Home 진입 | 큰 시각 영역 아래 `초기 설정이 필요한 현장` 카드에서 현장 범위 설정 또는 베이스라인 조사 계획으로 연결된다 |
| UX-01d | Home 시각 구조 변경 | 구현·검토 | 제품책임자 명시 승인, ADR 개정, 390/768/1024/1440 기준 이미지 및 projection·E2E 갱신이 모두 없으면 수용하지 않는다 |
| UX-02 | 확인이 필요한 현장 | Home 카드 선택 | 두 번 이내에 해당 현장 브리핑 또는 근거/결정 화면에 도달한다 |
| UX-03 | 현장 담당자 | `/sites/{siteId}` 진입 | 대상·상태·실제 최신 관측·기본 행동 및 다섯 현장 영역을 본다 |
| UX-04 | 현장 목록 | 390/768px에서 `/sites` 진입 | 가로 스크롤 표·기술 ID·World 단독 CTA 없이 이름·상태·다음 확인·현장 열기 순서의 카드로 읽는다 |
| UX-05 | 조직 전체 작업 | `/field` 진입 | 결정 필요·진행 중·완료를 현장명·필요 행동·갱신 시각으로 구분하며, WorkOrder가 없으면 중복 노트북·복구 카드 없는 단일 빈 상태를 본다 |
| UX-06 | 확인 항목 | `/events` 진입 | 데이터가 있으면 처리 필요·검토 중·정리됨으로 필터하고, 0건·필터 없음이면 필터보다 빈 상태를 먼저 보며 상세에서 근거→KSI 관측→사람 결정→이력을 본다 |

## B. 상태와 권한

| ID | 확인 | 합격 조건 |
|---|---|---|
| UX-07 | 빈/부분 실패 | 조회 실패를 0건·정상·가짜 카드로 바꾸지 않고 실패/알 수 없음과 복구를 표시한다 |
| UX-07a | 근거 요약 | 확인 항목 목록의 근거 건수는 삭제되지 않은 Core evidence와 일치하며, 상세 실패를 0건으로 표시하지 않는다 |
| UX-07b | 목록·수치 완전성 | Core의 요청당 pagination 상한을 제품 목록·검토 건수 상한으로 오해하지 않고 끝까지 읽으며, 후속 page 실패를 부분 성공으로 표시하지 않는다 |
| UX-08 | 모바일 행동 | 1024px 미만에는 승인·재관측 승인·Mission 발급·Site/장비 전이·수동 복구를 렌더하지 않는다. 일반 목록에서는 제한 안내를 반복하지 않고, 해당 행동의 deep link·작업 영역에 진입했을 때만 `노트북에서 계속` 이유를 표시한다 |
| UX-09 | 데스크톱 행동 | 1024px 이상에는 Core 권한이 있는 사용자에게만 같은 URL의 행동을 보인다 |
| UX-10 | 조직 격리 | 다른 조직 Site/Event/WorkOrder/ProcessingJob/Conversation은 동일한 404 또는 빈 결과로 보이며, HTTP request context 없는 workspace projection도 명시한 조직 밖의 Event·최신 분석을 섞거나 UI에 이름·근거를 누출하지 않는다 |
| UX-11 | legacy | `/missions`, `/assets`, `/world`, `/reports`, `/settings`, `/coming-soon/*` bookmark가 빈 화면이나 계약 ID 선택표로 끝나지 않는다 |

## C. AI 정직성

| ID | 확인 | 합격 조건 |
|---|---|---|
| AX-01 | briefing | 변화·중요성·결정 제안·citation·불확실성·watermark는 same-site 검증 결과에서만 온다 |
| AX-01a | citation 이동 | 허용된 same-site Core resource만 Console 내부 route로 열고, 임의 source path는 링크로 렌더하지 않는다 |
| AX-02 | conversation | `clientMessageId` 재전송은 중복 답변을 만들지 않고, 답변은 citation 검증 후에만 저장·표시된다 |
| AX-03 | fail closed | egress opt-in 없음, provider 오류, 모르는 tool, 다른 현장 citation, 근거 부족은 저장된 BLOCKED 답변과 복구 안내가 된다 |
| AX-04 | 사람 경계 | AI가 재관측 초안을 만들 수는 있어도 승인, Mission 발급, 비행 좌표·명령을 호출하거나 노출하지 않는다 |

## D. 검증 명령과 증거

1. Dashboard Vitest: next-action, navigation, responsive action matrix, site/work/event presenter,
   AI conversation failure/replay.
2. Dashboard lint, TypeScript, production build.
3. Playwright/Chromium: 390/768/1024/1440, local OIDC 로그인, keyboard/focus, 44px coarse target,
   horizontal page overflow 0, reduced motion, axe critical/serious 0, Home Visual Contract 기준 이미지.
4. Core contract: HTTP 및 request-context-free organization scope, 501건 이상 pagination,
   workspace partial failure, OIDC/device regression, citation/tool validation and stored conversation
   replay.

각 실행 결과는 software UX evidence다. DJI `WAYLINE_DELIVERY`, `EDGE_DOWNLINK`, `EDGE_UPLINK`,
`MEDIA_PULL`, `MEDIA_UPLOAD`은 이 문서의 통과와 무관하게 HIL 증거 전까지 `NOT_VERIFIED`다.

## E. 2026-08-25 수용 결과

- **판정:** PASS. Phase 1 Console software UI/UX 기준선은 완료되었다. 이는 제품이 더 이상
  개선되지 않는다는 뜻이 아니라, 위 A~D의 기능·정직성·반응형·접근성 게이트를 현재 코드와
  합성 원장에서 통과했다는 뜻이다.
- **합성 populated 원장:** 실제 `SiteStore`, `WorkAreaStore`, `ObservationWorkOrderStore`,
  `EventStore`와 허용된 상태 전이를 사용해 5개 현장, 승인 대기·승인됨·결과 준비·완료 WorkOrder,
  FINDING 1건과 등록 evidence metadata 1건을 구성했다. Mission, processing result, report ref,
  spatial model, 실제 이미지 bytes는 만들지 않았고 evidence 열람 404는 명시적인 부분 실패 UI로
  검증했다.
- **empty 조직:** 별도 `org-local-empty` OIDC 관리자로 Home·Work·Items의 단일 행동형 빈 상태와
  조직 격리를 검증했다.
- **브라우저 자동화:** Chromium 390/768/1024/1440에서 `54 passed, 2 skipped`다. 두 skip은
  desktop에서 coarse-pointer 전용 44px 검사를 적용하지 않는 의도적 viewport skip이다. OIDC,
  populated/empty/부분 실패, keyboard focus, reduced motion, horizontal overflow 0, axe
  critical/serious 0과 Home 기준 이미지를 포함한다.
- **실제 Tailnet 제품 검토:** 로그인 복구 후 Home, Sites, Work, Items, Site detail을 직접 검토했다.
  렌더링·내비게이션·가로 overflow·console warning/error가 정상이고 Site detail의 `다음 행동`은
  `KSI 현장 브리핑`보다 먼저 나타난다. 이 durable 개발 원장은 3개 초기 현장의 empty 상태이며,
  populated 시각 검토는 위 격리 E2E 원장으로 수행했다.
- **정적·회귀 게이트:** Dashboard `58 files / 527 tests`, ESLint, TypeScript, production build;
  전체 Python `3848 passed, 23 skipped, 3 xfailed`; Ruff와 Mypy `388 source files`가 통과했다.
- **비수용 범위:** 외부 고객 Cloud/실제 IdP, production deployment, device write, DPK/credential,
  비행, DJI adapter/HIL/FIELD 증거는 수용하지 않았다. 다섯 DJI capability는 계속
  `NOT_VERIFIED`다.
