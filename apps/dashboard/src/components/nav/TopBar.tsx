import { headers } from "next/headers";
import Link from "next/link";
import { Suspense } from "react";

import { whoAmI } from "@/lib/core-api/auth";
import { CoreApiError } from "@/lib/core-api/client";
import { MissingSessionError } from "@/lib/core-api/session";
import { ROLE_LABEL } from "@/lib/core-api/labels";
import { PATHNAME_HEADER, RETURN_TO_HEADER, SEARCH_HEADER } from "@/lib/core-api/session-cookie";

import { AccountMenu } from "./AccountMenu";
import { BackButton } from "./BackButton";
import { HeaderSearchTrigger } from "./HeaderSearchTrigger";
import { PageTitle } from "./PageTitle";
import { ProjectSwitcher } from "./ProjectSwitcher";
import { TopBarSearchTrigger } from "./TopBarSearchTrigger";
import { resolvePageTitle } from "./page-title";

function TopBarFrame({
  title,
  children,
  sessionState = "ok",
}: {
  title: string;
  children?: React.ReactNode;
  /** 만료·확인 실패는 복구 동작이라 프로젝트 전환 같은 정상 도구를 숨긴다 — CSS와 테스트가 이 값을 본다. */
  sessionState?: "ok" | "expired" | "unknown";
}) {
  return (
    <header
      data-shell-topbar="true"
      data-session-state={sessionState}
      // 전역 헤더(ADR-KSI-043) — 768px 이상에서는 레일과 본문 위를 가로질러 한 줄로 놓인다.
      // 팝오버(프로젝트 전환·계정)가 레일과 본문 위에 뜨도록 768px 이상에서만 레일(z-50)보다 한 층 위에 둔다.
      // 좁은 화면에서는 위치·층을 주지 않아 하단 시트(고정 배치)가 헤더 위를 덮는다.
      className="print:hidden flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-surface px-4 py-2.5 sm:px-5 md:relative md:z-[55] md:col-span-2 md:row-start-1 md:min-h-12 md:flex-nowrap md:px-3 md:py-0"
    >
      <Link
        href="/"
        aria-label="KSI Site Intelligence 홈"
        className="hidden flex-none items-center gap-2 text-body font-bold tracking-tight md:flex"
      >
        <span aria-hidden="true" className="grid size-6 place-items-center rounded-md bg-accent text-micro font-extrabold text-accent-on">KSI</span>
        <span className="hidden lg:inline">Site Intelligence</span>
      </Link>
      {sessionState !== "expired" && (
        <span className="hidden md:block">
          <Suspense fallback={null}>
            <ProjectSwitcher />
          </Suspense>
        </span>
      )}
      <BackButton />
      <PageTitle fallback={title} />
      <span className="flex-1" />
      {children}
    </header>
  );
}

export async function TopBar() {
  const headerStore = await headers();
  const currentPathname = headerStore.get(PATHNAME_HEADER);
  const onLoginPage = currentPathname === "/login";
  const title = resolvePageTitle(currentPathname, new URLSearchParams(headerStore.get(SEARCH_HEADER) ?? ""));

  // 신원·역할·로그아웃은 헤더의 계정 메뉴(AccountMenu)가 갖는다(ADR-KSI-043).
  // 세션 만료를 알리는 자리도 이 헤더다(아래 catch). 만료·거절·확인 실패에서는 정상
  // 도구(프로젝트 전환·검색·계정)를 그리지 않고 복구 안내만 둔다.
  let principal: Awaited<ReturnType<typeof whoAmI>>;
  try {
    principal = await whoAmI();
  } catch (error) {
    // 로그인 화면 자체에서는 "다시 로그인하세요" 문구가 중복이니 숨긴다. 그 외
    // 화면에서는 조용히 숨기지 않는다 — proxy.ts 는 쿠키 "존재"만 보고 페이지 접근을
    // 허용하므로, 무효/만료 토큰을 쥔 사용자가 로그아웃 버튼도 없이 갇히는 데드락을
    // 막아야 한다(독립 재검토 1차 P1-A). /login 은 이제 세션 유무와 무관하게 항상
    // 도달 가능하다(proxy.ts 참조) — 그냥 링크로 충분하다.
    if (onLoginPage) return null;
    const expired = error instanceof MissingSessionError || (error instanceof CoreApiError && error.status === 401);
    const denied = error instanceof CoreApiError && error.status === 403;
    if (!expired && !denied) {
      return <TopBarFrame title={title} sessionState="unknown">
        <span role="status" className="rounded-md bg-sunk px-2.5 py-1 text-body break-keep text-ink-2">
          서버 연결을 확인하지 못했습니다. 잠시 후 다시 시도하세요.
        </span>
      </TopBarFrame>;
    }
    // UX 목표 §5 "401 — 재로그인 유도(원래 화면으로 복귀 가능해야 함)" —
    // 복귀 주소(경로+쿼리)를 next 로 실어 재로그인 후 원래 화면에 복귀시킨다
    // (독립 재검토 2차 P3-1). 비교 쌍·구역 선택 쿼리를 잃지 않는다. 값은
    // 로그인 동작의 safeNextPath 가 살균하므로 외부·비정상 복귀를 만들지
    // 않으며, 헤더가 없으면 기존 경로 폴백을 쓴다.
    const returnTo = headerStore.get(RETURN_TO_HEADER) ?? currentPathname;
    const loginHref = returnTo
      ? `/login?next=${encodeURIComponent(returnTo)}`
      : "/login";
    return (
      <TopBarFrame title={title} sessionState="expired">
        <span className="rounded-md bg-high-bg px-2.5 py-1 text-body break-keep text-high-ink">
          {denied ? "이 계정의 접근 권한을 확인하세요." : "세션이 만료되었습니다."}
        </span>
        <Link
          href={loginHref}
          className="tap-target flex min-h-11 items-center rounded-md border border-line-strong px-3 text-body font-semibold hover:bg-sunk"
        >
          {denied ? "다른 계정으로 로그인" : "다시 로그인"}
        </Link>
      </TopBarFrame>
    );
  }

  // 세션이 살아 있는 정상 분기 — 사이드바가 숨는 lg 미만에서는 상단바가
  // 팔레트의 유일한 터치 입구다(⌘K 단축키가 없는 터치 기기를 위해).
  // 만료 분기에는 두지 않는다 — 검색 결과가 있어도 만료 세션에서는 열 수 없다.
  // 모든 인증 화면이 같은 상단바를 쓴다 — 작업공간·자료에서만 사라지던
  // 경로별 예외는 제품 셸의 일관성을 깨서 제거했다.
  return (
    <TopBarFrame title={title}>
      <HeaderSearchTrigger />
      <TopBarSearchTrigger />
      <AccountMenu
        principalId={principal.principalId}
        roleLabel={principal.role ? ROLE_LABEL[principal.role] : principal.kind}
      />
    </TopBarFrame>
  );
}
