"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { Fragment, Suspense } from "react";

import { isChromelessPath } from "./chromeless-path";
import { isViewerPath } from "./viewer-path";
import { DESKTOP_NAV_GROUPS } from "./nav-items";
import { NavIcon } from "./NavIcon";
import { SidebarSearchTrigger } from "./SidebarSearchTrigger";
import { SiteContextNav } from "./SiteContextNav";
import { resolveSiteId, siteMark, siteShortName, type SidebarSite } from "./site-context";

/** 사이드바에 띄울 실측 건수. 값이 없으면(집계 실패 포함) 배지를 아예 그리지 않는다 —
 *  0 과 "모름"은 다른 상태이고, 안전 화면에서 그 둘을 같게 보이면 안 된다. */
export interface NavCounts {
  [navKey: string]: { value: number; urgent?: boolean } | undefined;
}

/**
 * Viewer-first compact rail — 56px icon column used only on site 공간/자료.
 * The full labelled rail owns global navigation on every dense screen; this
 * variant keeps the same destinations and the current site visible without
 * spending a 176/232px text column on the canvas.
 */
function CompactSidebar({
  pathname,
  sites,
}: {
  pathname: string;
  sites: readonly SidebarSite[];
}) {
  const items = DESKTOP_NAV_GROUPS.flatMap((group) => group.items).filter((item) => item.key !== "more");
  const siteId = resolveSiteId(pathname);
  const currentSite = siteId ? sites.find((site) => site.siteId === siteId) ?? null : null;
  const active = (href: string) => href === "/" ? pathname === "/" : pathname.startsWith(href);

  return (
    <nav
      aria-label="주 메뉴"
      data-compact-rail="true"
      className="print:hidden hidden bg-sidebar py-3 text-sidebar-text lg:flex lg:flex-col lg:items-center lg:gap-1 lg:overflow-hidden"
    >
      <Link
        href="/"
        aria-label="KSI 홈"
        className="mb-3 grid size-7 flex-none place-items-center rounded-md bg-accent text-[10px] font-extrabold tracking-tight text-accent-on ring-1 ring-white/10"
      >
        KSI
      </Link>
      {items.map((item) => {
        const on = active(item.href);
        return (
          <Link
            key={item.key}
            href={item.href}
            title={item.label}
            aria-label={item.label}
            aria-current={on ? "page" : undefined}
            className={`tap-target grid size-9 flex-none place-items-center rounded-md transition-colors ${
              on ? "bg-sidebar-active text-sidebar-active-ink" : "text-sidebar-text hover:bg-sidebar-hover"
            }`}
          >
            <NavIcon name={item.icon} className="size-[18px]" />
          </Link>
        );
      })}
      {currentSite && (
        <div className="mt-1 flex w-full flex-col items-center gap-1 border-t border-white/10 pt-2">
          <Link
            href={`/sites/${encodeURIComponent(currentSite.siteId)}`}
            title={currentSite.name}
            aria-label={`현재 현장: ${siteShortName(currentSite.name)}`}
            className="tap-target grid size-9 place-items-center rounded-md bg-white/[0.07] text-[11px] font-bold text-sidebar-text hover:bg-sidebar-hover"
          >
            {siteMark(currentSite.name)}
          </Link>
          <span className="max-w-[52px] truncate text-[8.5px] leading-tight text-sidebar-muted" aria-hidden="true">
            {siteShortName(currentSite.name)}
          </span>
        </div>
      )}
      <div className="mt-auto flex flex-col items-center gap-1 pt-3">
        <Link
          href="/help"
          title="도움말"
          aria-label="도움말"
          className={`tap-target grid size-9 place-items-center rounded-md transition-colors ${
            pathname.startsWith("/help") ? "bg-sidebar-active text-sidebar-active-ink" : "text-sidebar-text hover:bg-sidebar-hover"
          }`}
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="size-[18px]">
            <circle cx="12" cy="12" r="9" />
            <path d="M9.5 9a2.5 2.5 0 0 1 5 .5c0 1.5-2.5 1.5-2.5 3.5M12 16.5v.5" />
          </svg>
        </Link>
        <Link
          href="/more"
          title="계정"
          aria-label="계정"
          className={`tap-target grid size-9 place-items-center rounded-md transition-colors ${
            pathname.startsWith("/more") ? "bg-sidebar-active text-sidebar-active-ink" : "text-sidebar-text hover:bg-sidebar-hover"
          }`}
        >
          <NavIcon name="more" className="size-[18px]" />
        </Link>
      </div>
    </nav>
  );
}

// PRD §7.1 "모바일/태블릿 하단 메뉴" — 768(태블릿)도 하단 탭이어야 하므로 lg(1024) 이상에서만
// 사이드바를 보인다(md=768 을 쓰면 태블릿에서 본문 폭이 폰보다 좁아지는 결함 재발, CLAUDE.md 근거).
//
// 폭은 시안을 따른다: 1280+ 232px · 1024~1279 176px(Console v2 §0). 태블릿 가로에서 본문을 최대한
// 남기되 마스터·디테일이 유지되는 값이다.
export function DesktopSidebar({
  counts,
  sites = [],
  userBlock,
}: {
  counts?: NavCounts;
  /** 현재 현장 블록·전환기에 쓰는 최소 현장 요약. 서버(layout)가 넘긴다. */
  sites?: readonly SidebarSite[];
  /** 레일 하단 사용자 블록. 세션을 읽는 **서버** 컴포넌트라 여기서 import 하지 않고
   *  layout.tsx 가 넘긴다 — 클라이언트 컴포넌트 안에 서버 컴포넌트를 중첩할 수 없다. */
  userBlock?: React.ReactNode;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  // 셸을 벗는 로그인 화면에는 레일 자체가 없다 — 판정은 layout.tsx 와
  // 같은 술어를 쓴다(둘이 갈리면 그리드 트랙만 남고 레일이 사라진다).
  if (isChromelessPath(pathname)) return null;
  if (isViewerPath(pathname, searchParams?.toString())) {
    return <CompactSidebar pathname={pathname} sites={sites} />;
  }
  return (
    <nav
      aria-label="주 메뉴"
      className="print:hidden hidden bg-sidebar pt-[18px] pb-2.5 text-sidebar-text lg:flex lg:flex-col lg:overflow-hidden"
    >
      <div className="flex items-center gap-[9px] px-[18px] pb-[22px]">
        <span
          aria-hidden="true"
          className="grid size-[26px] flex-none place-items-center rounded-md bg-accent text-[12px] font-extrabold tracking-tight text-accent-on ring-1 ring-white/10"
        >
          KSI
        </span>
        <span className="min-w-0">
          <span className="block text-[13.5px] leading-tight font-bold tracking-tight">
            현장 지능
          </span>
          {/* 176px 레일(1024~1279)에서는 두 줄로 접혀 브랜드 블록이 위아래로 벌어진다.
              장식 문구라 232px 레일에서만 보인다. */}
          <span className="hidden font-mono text-[10.5px] tracking-[0.04em] text-sidebar-muted xl:block">
            SITE INTELLIGENCE
          </span>
        </span>
      </div>

      <div className="px-3 pb-3">
        <SidebarSearchTrigger />
      </div>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2.5">
        {DESKTOP_NAV_GROUPS.map((group) => (
          <div key={group.key} className={group.key === "account" ? "mt-auto border-t border-white/10 pt-3 pb-2" : undefined}>
            {group.key === "account" && <Link href="/help" aria-current={pathname.startsWith("/help") ? "page" : undefined} className={`tap-target flex items-center gap-2.5 rounded-md px-2 text-[13px] hover:bg-sidebar-hover ${pathname.startsWith("/help") ? "bg-sidebar-active font-semibold text-sidebar-active-ink" : ""}`}>
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="size-[17px]"><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 0 1 5 .5c0 1.5-2.5 1.5-2.5 3.5M12 16.5v.5" /></svg>
              도움말
            </Link>}
            {group.label && (
              // tracking 0.1em 은 라틴 대문자용이다 — 한글에 그대로 걸면 자모가 흩어져
              // 오히려 읽기 나빠진다. uppercase 는 라틴 라벨이 섞일 때를 위해 남긴다.
              <div className="px-2 pt-3.5 pb-1.5 text-[10.5px] font-bold tracking-[0.02em] text-sidebar-muted uppercase">
                {group.label}
              </div>
            )}
            {group.items.map((item) => {
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              const count = counts?.[item.key];
              return (
                <Fragment key={item.key}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={`tap-target flex items-center justify-between gap-2 rounded-md p-2 text-[13px] break-keep transition-colors ${
                      active
                        ? "bg-sidebar-active font-semibold text-sidebar-active-ink"
                        : "hover:bg-sidebar-hover"
                    } ${
                      // 활성일 때는 muted 를 걸지 않는다 — Tailwind 는 클래스 문자열 순서가 아니라
                      // 생성된 CSS 순서로 이기므로, 준비 중 항목에 들어가 있으면 활성 배경 위에
                      // muted 텍스트가 얹혀 대비가 무너진다.
                      item.implemented || active ? "" : "text-sidebar-muted"
                    }`}
                  >
                    <span className="flex min-w-0 items-center gap-2.5">
                      <NavIcon name={item.icon} className="size-[17px] flex-none" />
                      <span>{item.label}</span>
                    </span>
                    {count && (
                      <span
                        className={`tabular rounded-full px-1.5 py-px text-[11px] ${
                          count.urgent
                            ? "bg-crit font-bold text-white"
                            : "bg-white/[0.13] text-sidebar-text"
                        }`}
                      >
                        {count.value}
                      </span>
                    )}
                  </Link>
                  {item.key === "sites" && (
                    <Suspense fallback={null}>
                      <SiteContextNav key={pathname} sites={sites} />
                    </Suspense>
                  )}
                </Fragment>
              );
            })}
          </div>
        ))}
      </div>

      {userBlock}
    </nav>
  );
}
