# apps/dashboard

KSI Operations Console: Home, Sites and the five-area Site workspace
(현황 overview · 자료 materials · 분석·검토 analysis/review · 작업 work · 관리 manage).
관리 owns work-area setup, the optional site-wide boundary and site-state transitions;
external comparison records stay a distinct sub-list inside 분석·검토. P4 removed
Mission/flight/Edge/managed acquisition screens and actions; S3's older mission/event/fleet
scope is historical only. Auth, scoped external registration, work operations,
result/evidence and unavailable states remain.

P4 local technical evidence is in [`p4-cleanup-evidence/verification/receipt.md`](p4-cleanup-evidence/verification/receipt.md)
and the design-owned [`p4-cleanup-final-render-review.md`](p4-cleanup-final-render-review.md).
P5 reuses their unchanged source/capture hashes, not a new aesthetic judgment. The former evidence
stack at `http://localhost:3241/` (Core8041/Identity9041, host-loopback only) is no longer reachable
as of the P5 read-only check; it is not a live customer/demo link. No duplicate server was started.
Current approval/limitations: [task ledger](../../docs/superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md)
and [first-flow gap map](../../docs/audit/PHYSICAL_SITE_REBASELINE_INTEGRATED_VERIFICATION.md).

## Local development

1. Start the standard local stack:

   Commands below describe the existing workflow, not permission to install, alter Tailscale,
   register a persistent service or restart a live target. Use the already prepared toolchain;
   dependency installation is separately approved.

   ```bash
   cd apps/dashboard
   npm run dev
   ```

   This starts three loopback-only processes: KSI Local Identity, Core in OIDC
   mode, and the Operations Console. It also configures persistent, tailnet-only
   Tailscale Serve HTTP proxies for the Dashboard (`:3210`) and local Identity
   (`:9010`). Open the printed MagicDNS URL from any authorized tailnet device
   and continue with the default development operator. Role-specific accounts
   are available only under the advanced test control. The browser never asks a
   human to paste a Bearer token. The services are not bound to LAN or public network
   interfaces.

   The `KSI 로컬 인증 테스트` page is the development-only OIDC issuer, not an
   Operations Console product screen. Choose `기본 개발 계정으로 계속` for the
   normal path; the optional role controls exist only for RBAC checks and do not
   represent the production login experience.

   Core journals persist below `.dev-data/local-oidc-core`; local issuer keys
   and secrets persist below `.dev-data/local-identity`. Both are ignored by Git.

   If Tailscale is intentionally unavailable, use the explicit localhost rollback:

   ```bash
   npm run dev:local
   ```

   Tailscale Serve configuration survives the dev process. To remove only these
   two development endpoints without touching other Serve routes:

   ```bash
   tailscale serve --http=3210 off
   tailscale serve --http=9010 off
   ```

   On the KSI development host, the stack can be kept available across SSH
   disconnects and machine restarts with the repository-owned user service:

   ```bash
   systemctl --user enable --now \
     "$PWD/../../deploy/systemd/ksi-operations-console-dev.service"
   systemctl --user status ksi-operations-console-dev.service
   journalctl --user -u ksi-operations-console-dev.service -f
   ```

   When the service is enabled, edit the source normally; Next.js hot reload is
   already running. Do not launch a second `npm run dev` on the same ports. If
   the stack launcher or its environment changes, restart the service:

   ```bash
   systemctl --user restart ksi-operations-console-dev.service
   ```

   Roll back only the persistent dev stack with:

   ```bash
   systemctl --user disable --now ksi-operations-console-dev.service
   ```

2. To run only the Dashboard for a focused UI investigation, use:

   ```bash
   npm run dev:dashboard
   ```

   In that exceptional mode provide the Core and OIDC environment variables
   explicitly. It is not the supported integration test path.

## Operations Console validation

Run the component and production-build gates before handing off an authorized UI change:

```bash
npm test
npm run lint
npx tsc --noEmit
npm run build
```

The browser suite starts an isolated local Identity/Core/Dashboard stack and
checks the `390`, `768`, `1024`, and `1440` px layouts, OIDC sign-in, primary
navigation, horizontal overflow, touch targets, reduced motion, and serious or
critical axe-core findings:

```bash
npm run test:e2e
```

To repeat the same non-mutating checks against an already running tailnet-only
development stack, set its origin explicitly:

```bash
KSI_DASHBOARD_E2E_BASE_URL=http://<magic-dns-name>:3210 npm run test:e2e
```

Playwright state is isolated in a run-scoped `test-results/runtime-*`
directory; it does not reuse or overwrite the normal local OIDC journals. The
current fixture seed writes five owned synthetic Sites/WorkAreas through real stores;
four managed-mode WorkOrders are explicitly historical/non-executable and one external
WorkOrder is APPROVED/OPEN. E2E-only OIDC mapping grants these exact fixture resources;
the normal and empty-organization accounts do not inherit those grants. It creates no Mission,
device receipt, ProcessingJob/result or Event. Scoped-OIDC Site creation is the F-01
capability bootstrap (server-issued `siteId`, `SITE_BOOTSTRAP` via the protected registry;
[ADR-KSI-040](../../docs/architecture/ADR-KSI-040-site-bootstrap-and-grant-ownership.md)):
the fixture accounts do not carry that capability, so this suite does not exercise it —
actual-auth acceptance evidence is recorded in the
[task ledger](../../docs/superpowers/plans/2026-10-07-agent-first-platform-rebaseline.md).
The `/sites/new` flow resolves its registration mode from Core's `whoami` registry
metadata (`getSiteRegistrationMode`): legacy opaque accounts keep the client `siteId`
form, mapped accounts use the bootstrap form. Missing optional Analysis/workflow
configuration and real storage bytes remain honest unavailable states, not successful first-flow evidence.
Visual snapshots and fixture data are not HIL evidence and never change a DJI
capability from `NOT_VERIFIED`.

Built with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app)
(Next.js App Router, TypeScript, Tailwind v4).

## 피드백 기본형 (ActionUnavailable · ToastProvider · ConfirmDialog)

소리 없이 막힌 화면을 만들지 않기 위한 세 가지 기본형이다.
`src/components/ui/` 에 있으며, 용도를 바꾸지 않는다:

- `ActionUnavailable({ label, description, retry? })` — 권한이 없어 눌 수 없는
  동작의 사유를 **클릭해야 열리는 비모달 팝오버**로 보여준다. 상시 문구·title
  툴팁·disabled 고정을 쓰지 않으며, `retry` 는 `router.refresh()` 읽기만 한다.
  현장 등록 진입(`src/app/sites/RegisterSiteAction.tsx`)이 쓰는 형태다.
- `ToastProvider` + `useToast()` — 단순 성공 한 마디만 띄운다. 최신 1개·최소
  6초 유지·호버/포커스/숨김 탭에서 일시정지·`알림 닫기` 버튼·포커스 탈취 없음.
  `layout.tsx` 가 앱 전체에 깔아 두므로 호출부는 `notify(message)` 만 쓴다.
- `ConfirmDialog({ open, title, description, confirmLabel, onConfirm, onCancel, pending? })`
  — 되돌리기 어려운 변경이나 작업 흐름을 멈추는 중요 결정용 모달(네이티브 `<dialog>`, 기본 포커스 취소,
  확인 라벨은 동작 명시). 취소·배경 클릭은 절대 실행하지 않으며, `pending`
  동안 중복 실행을 막는다.

검증·복구는 각 화면의 인라인 상태가 맡고, 토스트·모달로 대신하지 않는다.
권한 부족과 권한 확인 실패는 구분한다. 직접 진입한 권한 거부 페이지·조회 실패·처리 상태·
정량 근거의 한계는 화면에 유지하며, 짧은 실행 불가 사유만 팝오버로 옮긴다.

## 현장 목록 검색·정렬

`SiteListControls`는 돋보기 검색 입력과 네이티브 정렬을 같은 높이로 둔다.
입력은 300ms 후 URL에 적용하고 Enter는 즉시 적용한다. 한글 조합 중에는 적용하지 않으며,
640px 이상에서 정렬 변경은 입력 중인 검색어도 함께 확정한다. 검색어 지우기는 q만,
초기화는 모든 조건을 되돌린다. 태블릿의 전체 초기화는 상태 필터 안에 둔다.
조건 이동·초기화·뒤로가기는 대기 중 검색을 취소해 이전 타이머가 새 URL을 덮지 않게 한다.

640px 미만 휴대폰 폭에서는 검색만 전체 너비로 두고, 건수 옆 `필터·정렬`을 펼쳐 두 조건을
고른 뒤 적용한다. 적용은 최신 검색 초안을 함께 사용하고, 선택만 하거나 닫으면 조건을 바꾸지
않는다. 이 구간의 현장 카드에서는 장식용 기본 이미지만 생략하며 정보와 열기 행동이 전체 폭을
쓴다. 640px 이상과 Home 시각 영역은 기존 구성을 유지한다.

태블릿 목록의 작은 `SiteListVisual`은 Home과 같은 **기본 장식**이며 실제 현장 사진이나 지도는 아니다.
현재 Site 목록에 지원되는 실제 관측 이미지 미리보기 경로가 없어 `기본 이미지`로 표시한다.
실제 썸네일을 지원하려면 별도의 scoped 등록 근거 경로가 필요하며, raw 바이트나 임의 URL로
대체하지 않는다. 이 UI 변경은 미디어 접근 권한을 추가하지 않는다.

1024px 이상에서는 `카드 | 목록`을 전환한다. 기본 카드는 현장명이 크게 읽히는 2열 기본 표지이며,
1건만 있어도 한 열의 폭을 유지한다. 목록은 장식 없는 비교표다. 두 보기는 같은 scoped 자료를 쓰며,
전환은 로컬 표현 상태만 바꿔 검색·정렬·미확정 검색 초안을 건드리지 않는다.

마지막 선택은 `ksi-sites-view=cards|list` 기능 쿠키에만 기억한다(`Path=/sites`, `SameSite=Lax`,
1년, HTTPS에서 `Secure`). ID·검색어·계정·권한·추적값은 저장하지 않고 Core 설정 API도 없다.
서버가 첫 화면에 읽으며, 저장이 제한돼도 현재 탭 전환은 동작한다. 실제 관측 이미지 지원을
추가한 것은 아니며 표지에 `기본 표지`로 구분한다. 휴대폰·태블릿·Home 구성은 유지한다.

Desktop은 실제 현장 카드 4개/목록 10행씩 나누고 URL `page`로 번호·이전·다음을 제공한다.
잘못된 번호는 실제 범위로 보정하며 한 페이지면 푸터를 숨긴다. 검색·필터·정렬 또는 보기 변경은
1페이지로 돌아가되 검색 초안/IME와 충돌하지 않는다. 번호 이동은 확정 검색 조건을 사용하고
대기 초안을 취소·동기화한다. 현장 상세 왕복은 URL의 원래 페이지를 복원한다.

카드는 최대 폭을 제한한 2열/아주 넓은 화면 3열이며 표지는 16:7 비율로 폭을 따른다.
마지막 카드 페이지에는 `새 현장 추가` 유틸리티를 둔다(현장 건수·정렬·페이지 수 제외).
상단 등록 버튼과 동일한 allowed/denied/unavailable 판정을 사용하며, 거부·미확인은 클릭형
안내일 뿐 권한이나 등록 API를 우회하지 않는다. Phone/tablet은 기존 전체 목록을 유지한다.
