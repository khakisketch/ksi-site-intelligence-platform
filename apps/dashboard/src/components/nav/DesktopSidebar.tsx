"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { DESKTOP_NAV_GROUPS } from "./nav-items";

/** 사이드바에 띄울 실측 건수. 값이 없으면(집계 실패 포함) 배지를 아예 그리지 않는다 —
 *  0 과 "모름"은 다른 상태이고, 안전 화면에서 그 둘을 같게 보이면 안 된다. */
export interface NavCounts {
  [navKey: string]: { value: number; urgent?: boolean } | undefined;
}

// PRD §7.1 "모바일/태블릿 하단 메뉴" — 768(태블릿)도 하단 탭이어야 하므로 lg(1024) 이상에서만
// 사이드바를 보인다(md=768 을 쓰면 태블릿에서 본문 폭이 폰보다 좁아지는 결함 재발, CLAUDE.md 근거).
//
// 폭은 시안을 따른다: 1280+ 216px · 1024~1279 176px. 태블릿 가로에서 본문을 최대한
// 남기되 마스터·디테일이 유지되는 값이다.
export function DesktopSidebar({ counts }: { counts?: NavCounts }) {
  const pathname = usePathname();
  if (pathname === "/login") return null;

  return (
    <nav
      aria-label="주 메뉴"
      className="hidden bg-sidebar pt-[18px] pb-6 text-sidebar-text lg:flex lg:flex-col lg:overflow-y-auto"
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
              장식 문구라 216px 레일에서만 보인다. */}
          <span className="hidden font-mono text-[10.5px] tracking-[0.04em] text-sidebar-muted xl:block">
            SITE INTELLIGENCE
          </span>
        </span>
      </div>

      <div className="px-2.5">
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
                  <span className="min-w-0">{item.label}</span>
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
    </nav>
  );
}
