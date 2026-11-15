"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import { isChromelessPath } from "./chromeless-path";
import { MOBILE_TAB_ITEMS, projectMobileTabItems } from "./nav-items";
import { NavIcon } from "./NavIcon";
import { resolveProjectSection, resolveSiteId } from "./site-context";

export function MobileBottomNav() {
  const pathname = usePathname();
  const search = useSearchParams();
  if (isChromelessPath(pathname)) return null;
  // 프로젝트 안에서는 공간·자료·분석·작업, 밖에서는 홈·프로젝트·작업·계정(ADR-KSI-043).
  const siteId = resolveSiteId(pathname);
  const projectSection = siteId ? resolveProjectSection(pathname, search) : null;
  const items = siteId ? projectMobileTabItems(siteId) : MOBILE_TAB_ITEMS;

  return (
    <nav
      aria-label="하단 메뉴"
      className="print:hidden fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-surface pb-[var(--mobile-bottom-nav-safe-area)] md:hidden"
    >
      {/* 비활성 라벨에 --ink-muted(#878D94)를 쓰면 흰 배경에서 명도비 3.35:1 로 AA 미달이다
          (하위호환 text-foreground/60 은 합성색 ≈4.89:1 로 통과했었다 — 토큰 이관이 대비를
          역행시킨 자리). 12px 라벨이고 이 제품의 1급 기기가 태블릿이라 여기서 물러설 수 없다.
          --ink-2(#4E5359)는 ≈7.5:1. muted 는 '읽지 않아도 되는 보조 정보'용이지 내비게이션용이 아니다. */}
      {items.map((item) => {
        const active = item.key.startsWith("project-")
          ? item.key === `project-${projectSection}`
          : item.href === "/" ? pathname === "/" : item.key === "sites" ? pathname === "/sites" || pathname === "/sites/new" : pathname.startsWith(item.href)
          || (item.key === "more" && (pathname === "/help" || pathname.startsWith("/coming-soon/")));
        return (
          <Link
            key={item.key}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-[var(--mobile-bottom-nav-row-height)] flex-1 flex-col items-center justify-center gap-0.5 py-1 text-micro break-keep ${ active ? "text-accent-text font-semibold" : "text-ink-2" }`}
          >
            <NavIcon name={item.icon} className="size-5" />
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
