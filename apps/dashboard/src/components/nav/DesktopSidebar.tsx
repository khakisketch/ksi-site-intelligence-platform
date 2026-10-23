"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isChromelessPath } from "./chromeless-path";
import { isFocusModePath } from "./focus-mode-path";
import { DESKTOP_NAV_GROUPS } from "./nav-items";
import { NavIcon } from "./NavIcon";
import { SidebarSearchTrigger } from "./SidebarSearchTrigger";

/** 사이드바에 띄울 실측 건수. 값이 없으면(집계 실패 포함) 배지를 아예 그리지 않는다 —
 *  0 과 "모름"은 다른 상태이고, 안전 화면에서 그 둘을 같게 보이면 안 된다. */
export interface NavCounts {
  [navKey: string]: { value: number; urgent?: boolean } | undefined;
}

// PRD §7.1 "모바일/태블릿 하단 메뉴" — 768(태블릿)도 하단 탭이어야 하므로 lg(1024) 이상에서만
// 사이드바를 보인다(md=768 을 쓰면 태블릿에서 본문 폭이 폰보다 좁아지는 결함 재발, CLAUDE.md 근거).
//
// 폭은 시안을 따른다: 1280+ 232px · 1024~1279 176px(Console v2 §0). 태블릿 가로에서 본문을 최대한
// 남기되 마스터·디테일이 유지되는 값이다.
export function DesktopSidebar({
  counts,
  userBlock,
}: {
  counts?: NavCounts;
  /** 레일 하단 사용자 블록. 세션을 읽는 **서버** 컴포넌트라 여기서 import 하지 않고
   *  layout.tsx 가 넘긴다 — 클라이언트 컴포넌트 안에 서버 컴포넌트를 중첩할 수 없다. */
  userBlock?: React.ReactNode;
}) {
  const pathname = usePathname();
  // 셸을 벗는 로그인 화면에는 레일 자체가 없다 — 판정은 layout.tsx 와
  // 같은 술어를 쓴다(둘이 갈리면 그리드 트랙만 남고 레일이 사라진다).
  if (isChromelessPath(pathname)) return null;
  // 집중 모드(자료 작업환경·디자인 예시)에서는 같은 항목·같은 권한으로
  // 64px 아이콘 레일만 둔다. 전역 내비 권한을 복제하지 않으며, 사용자·
  // 로그아웃은 기존 서버 블록을 그대로 싣는다.
  if (isFocusModePath(pathname)) {
    return (
      <nav
        aria-label="주 메뉴"
        className="print:hidden hidden w-full flex-col items-center gap-1 bg-sidebar pt-3 pb-2.5 text-sidebar-text lg:flex"
      >
        <Link
          href="/"
          aria-label="KSI 홈"
          title="KSI 홈"
          className="tap-target grid size-9 flex-none place-items-center rounded-md bg-accent text-[12px] font-extrabold tracking-tight text-accent-on ring-1 ring-white/10"
        >
          <span aria-hidden="true">KSI</span>
        </Link>
        <SidebarSearchTrigger compact />
        <div className="flex min-w-0 flex-1 flex-col items-center gap-1 overflow-y-auto">
          {DESKTOP_NAV_GROUPS.flatMap((group) => group.items).map((item) => {
            const active =
              item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const count = counts?.[item.key];
            return (
              <Link
                key={item.key}
                href={item.href}
                aria-label={item.label}
                title={item.label}
                aria-current={active ? "page" : undefined}
                className={`tap-target relative flex w-14 flex-col items-center gap-0.5 rounded-md px-1 py-2 text-[10px] leading-tight break-keep transition-colors ${
                  active
                    ? "bg-sidebar-active font-semibold text-sidebar-active-ink"
                    : "hover:bg-sidebar-hover"
                } ${item.implemented || active ? "" : "text-sidebar-muted"}`}
              >
                <NavIcon name={item.icon} className="size-5 flex-none" />
                <span className="max-w-full truncate">{item.label}</span>
                {count && (
                  <span
                    className={`tabular rounded-full px-1 text-[10px] leading-tight ${
                      count.urgent
                        ? "bg-crit font-bold text-white"
                        : "bg-white/[0.13] text-sidebar-text"
                    }`}
                  >
                    {count.value}
                  </span>
                )}
              </Link>
            );
          })}
        </div>
        {userBlock && (
          <details className="relative flex-none">
            <summary
              aria-label="계정"
              title="계정"
              className="tap-target flex size-11 cursor-pointer list-none items-center justify-center rounded-md transition-colors hover:bg-sidebar-hover [&::-webkit-details-marker]:hidden"
            >
              <span
                aria-hidden="true"
                className="grid size-7 place-items-center rounded-full bg-sidebar-active text-[11px] font-bold text-sidebar-active-ink"
              >
                계
              </span>
            </summary>
            <div className="absolute bottom-0 left-full z-40 ml-2 w-64 rounded-lg bg-sidebar p-1 text-sidebar-text shadow-xl ring-1 ring-white/10">
              {userBlock}
            </div>
          </details>
        )}
      </nav>
    );
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

      <div className="min-h-0 flex-1 overflow-y-auto px-2.5">
        {DESKTOP_NAV_GROUPS.map((group) => (
          <div key={group.key}>
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
                <Link
                  key={item.key}
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
              );
            })}
          </div>
        ))}
      </div>

      {userBlock}
    </nav>
  );
}
