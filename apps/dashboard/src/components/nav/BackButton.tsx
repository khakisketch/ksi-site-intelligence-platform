"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { isChromelessPath } from "./chromeless-path";

/** 상단바의 맥락형 상위 화면 링크.
 *
 * router.back()은 사용자가 어디서 왔느냐에 따라 목적지가 바뀐다. Console의 상단바는
 * 브라우저 이력을 되감는 곳이 아니라 "지금 이 상세가 어느 작업공간에 속하는가"를
 * 알려 주는 자리로 쓴다. 그래서 최상위 화면에는 아무 것도 그리지 않고, 상세 화면에는
 * 항상 같은 부모 목록/현장으로 가는 링크만 둔다. 브라우저 자체의 뒤로가기는 그대로다.
 */
const TOP_LEVEL = new Set([
  "/",
  "/sites",
  "/field",
  "/more",
]);

export interface ParentNavigation {
  href: string;
  label: string;
}

export function resolveParentNavigation(pathname: string | null): ParentNavigation | null {
  if (!pathname || isChromelessPath(pathname) || TOP_LEVEL.has(pathname)) return null;

  if (pathname === "/sites/new") {
    // 등록·조사 Wizard는 자체 step back/unsaved draft 흐름을 소유한다. 상단 링크가
    // 작업 중인 입력을 아무 경고 없이 버리게 만들면 안 된다.
    return null;
  }

  const siteMatch = pathname.match(/^\/sites\/([^/]+)(?:\/.*)?\/?$/);
  if (siteMatch) return { href: `/sites/${siteMatch[1]}`, label: "현장" };
  if (/^\/field\/work-orders\/[^/]+\/?$/.test(pathname)) {
    return { href: "/field", label: "작업" };
  }
  if (pathname.startsWith("/coming-soon/")) return { href: "/more", label: "더보기" };

  return null;
}

export function isBackVisible(pathname: string | null): boolean {
  return resolveParentNavigation(pathname) !== null;
}

export function BackButton() {
  const pathname = usePathname();
  const parent = resolveParentNavigation(pathname);
  if (!parent) return null;

  return (
    <Link
      href={parent.href}
      aria-label={`${parent.label}으로 이동`}
      className="tap-target -ml-1 inline-flex flex-none items-center gap-1 rounded-md px-2 text-[12px] font-semibold text-ink-2 hover:bg-sunk hover:text-ink-1"
    >
      <svg
        aria-hidden="true"
        width="14"
        height="14"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      >
        <path d="M13 8H4M7.5 4.5 4 8l3.5 3.5" />
      </svg>
      {parent.label}
    </Link>
  );
}
