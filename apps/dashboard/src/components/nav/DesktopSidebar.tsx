"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { DESKTOP_NAV_ITEMS } from "./nav-items";

// PRD §7.1 "모바일/태블릿 하단 메뉴" — 768(태블릿)도 하단 탭이어야 하므로 lg(1024) 이상에서만
// 사이드바를 보인다(md=768 을 쓰면 태블릿에서 본문 폭이 폰보다 좁아지는 결함 재발, CLAUDE.md 근거).
export function DesktopSidebar() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="주 메뉴"
      className="hidden lg:flex lg:w-56 lg:flex-col lg:gap-1 lg:border-r lg:border-black/10 lg:p-3 dark:border-white/10"
    >
      {DESKTOP_NAV_ITEMS.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link
            key={item.key}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-11 items-center rounded-md px-3 text-sm break-keep transition-colors ${
              active
                ? "bg-foreground text-background font-medium"
                : "text-foreground/80 hover:bg-foreground/10"
            } ${!item.implemented ? "opacity-60" : ""}`}
          >
            {item.label}
            {!item.implemented && <span className="ml-auto text-xs">준비 중</span>}
          </Link>
        );
      })}
    </nav>
  );
}
