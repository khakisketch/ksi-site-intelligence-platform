"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { MOBILE_TAB_ITEMS } from "./nav-items";

export function MobileBottomNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="하단 메뉴"
      className="fixed inset-x-0 bottom-0 z-20 flex border-t border-black/10 bg-background lg:hidden dark:border-white/10"
    >
      {MOBILE_TAB_ITEMS.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link
            key={item.key}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 py-1.5 text-xs break-keep ${
              active ? "text-foreground font-medium" : "text-foreground/60"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
