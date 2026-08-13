import { headers } from "next/headers";
import Link from "next/link";

import { logout } from "@/app/login/actions";
import { whoAmI } from "@/lib/core-api/auth";
import { ROLE_LABEL } from "@/lib/core-api/labels";
import { PATHNAME_HEADER } from "@/lib/core-api/session-cookie";
import { SEOUL_TIME_ZONE } from "@/lib/datetime";

import { PageTitle } from "./PageTitle";
import { resolvePageTitle } from "./page-title";

function todayLabel(): { date: string; weekday: string } {
  const now = new Date();
  return {
    date: new Intl.DateTimeFormat("ko-KR", { dateStyle: "long", timeZone: SEOUL_TIME_ZONE }).format(
      now,
    ),
    weekday: new Intl.DateTimeFormat("ko-KR", {
      weekday: "long",
      timeZone: SEOUL_TIME_ZONE,
    }).format(now),
  };
}

function TopBarFrame({ title, children }: { title: string; children: React.ReactNode }) {
  const { date, weekday } = todayLabel();
  return (
    <header className="print:hidden flex shrink-0 flex-wrap items-center gap-x-3.5 gap-y-2 border-b border-line bg-surface px-4 py-2.5 sm:px-5">
      <PageTitle fallback={title} />
      <span className="hidden items-center gap-1.5 rounded-md border border-line-strong px-2.5 py-1 text-[13px] text-ink-2 sm:inline-flex">
        <strong className="font-semibold text-ink-1">{date}</strong>
        {weekday}
      </span>
      <span className="flex-1" />
      {children}
    </header>
  );
}

export async function TopBar() {
  const headerStore = await headers();
  const currentPathname = headerStore.get(PATHNAME_HEADER);
  const onLoginPage = currentPathname === "/login";
  const title = resolvePageTitle(currentPathname);

  let principal;
  try {
    principal = await whoAmI();
  } catch {
    // 로그인 화면 자체에서는 "다시 로그인하세요" 문구가 중복이니 숨긴다. 그 외
    // 화면에서는 조용히 숨기지 않는다 — proxy.ts 는 쿠키 "존재"만 보고 페이지 접근을
    // 허용하므로, 무효/만료 토큰을 쥔 사용자가 로그아웃 버튼도 없이 갇히는 데드락을
    // 막아야 한다(독립 재검토 1차 P1-A). /login 은 이제 세션 유무와 무관하게 항상
    // 도달 가능하다(proxy.ts 참조) — 그냥 링크로 충분하다.
    if (onLoginPage) return null;
    // UX 목표 §5 "401 — 재로그인 유도(원래 화면으로 복귀 가능해야 함)" — x-pathname 이
    // 이미 손에 있으니 next 로 실어 재로그인 후 원래 화면에 복귀시킨다(독립 재검토 2차 P3-1).
    const loginHref = currentPathname
      ? `/login?next=${encodeURIComponent(currentPathname)}`
      : "/login";
    return (
      <TopBarFrame title={title}>
        <span className="rounded-md bg-high-bg px-2.5 py-1 text-[13px] break-keep text-high-ink">
          세션이 만료되었습니다.
        </span>
        <Link
          href={loginHref}
          className="tap-target flex items-center rounded-md border border-line-strong px-3 text-[13px] font-semibold hover:bg-sunk"
        >
          다시 로그인
        </Link>
      </TopBarFrame>
    );
  }

  const roleLabel = principal.role ? ROLE_LABEL[principal.role] : principal.kind;
  const initial = principal.principalId.trim().charAt(0).toUpperCase() || "?";

  return (
    <TopBarFrame title={title}>
      <span className="hidden text-[13px] break-keep text-ink-2 sm:inline">
        {principal.principalId} · {roleLabel}
      </span>
      <span
        aria-hidden="true"
        className="grid size-[30px] flex-none place-items-center rounded-full border border-line bg-accent-tint text-[12px] font-bold text-accent-ink"
      >
        {initial}
      </span>
      <form action={logout}>
        <button
          type="submit"
          className="tap-target flex items-center rounded-md px-2 text-[13px] text-ink-2 hover:bg-sunk hover:text-ink-1"
        >
          로그아웃
        </button>
      </form>
    </TopBarFrame>
  );
}
