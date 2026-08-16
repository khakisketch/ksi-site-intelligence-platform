"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isChromelessPath } from "./chromeless-path";
import { MOBILE_TAB_ITEMS } from "./nav-items";

export function MobileBottomNav() {
  const pathname = usePathname();
  // /login 과 같은 사유로 /field/* 에서도 숨긴다 — 현장 화면은 하단 탭이 아니라
  // 화면 안의 큰 버튼으로 이동한다(layout.tsx 의 isChromelessPath 와 같은 술어).
  if (isChromelessPath(pathname)) return null;

  return (
    <nav
      aria-label="하단 메뉴"
      className="print:hidden fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] lg:hidden"
    >
      {/* 비활성 라벨에 --ink-muted(#878D94)를 쓰면 흰 배경에서 명도비 3.35:1 로 AA 미달이다
          (하위호환 text-foreground/60 은 합성색 ≈4.89:1 로 통과했었다 — 토큰 이관이 대비를
          역행시킨 자리). 12px 라벨이고 이 제품의 1급 기기가 태블릿이라 여기서 물러설 수 없다.
          --ink-2(#4E5359)는 ≈7.5:1. muted 는 '읽지 않아도 되는 보조 정보'용이지 내비게이션용이 아니다. */}
      {MOBILE_TAB_ITEMS.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link
            key={item.key}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 py-1.5 text-xs break-keep ${ active ? "text-ink-1 font-medium" : "text-ink-2" }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
