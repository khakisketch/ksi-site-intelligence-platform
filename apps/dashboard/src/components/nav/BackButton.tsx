"use client";

import { usePathname, useRouter } from "next/navigation";

import { isChromelessPath } from "./chromeless-path";

/** 상단바 뒤로가기(디자인 §0 "뒤로가기 스택 유지").
 *
 * **최상위 화면에서는 그리지 않는다.** 레일에서 한 번에 닿는 화면에 뒤로가기를 두면
 * 누를 곳이 하나 늘 뿐 갈 곳이 없다 — 브라우저 히스토리 상 이전 화면이 있더라도
 * 그건 "상위"가 아니라 "직전"이라, 계층 이동 버튼처럼 생긴 자리에 두면 어디로 갈지
 * 예측할 수 없다. 하위 경로(/sites/[id] · /missions/[id] 등)에서만 보인다.
 */
const TOP_LEVEL = new Set([
  "/",
  "/sites",
  "/missions",
  "/events",
  "/assets",
  "/world",
  "/reports",
  "/settings",
  "/more",
]);

export function isBackVisible(pathname: string | null): boolean {
  if (!pathname) return false;
  if (isChromelessPath(pathname)) return false;
  if (TOP_LEVEL.has(pathname)) return false;
  // /coming-soon/* 은 막다른 화면이라 되돌아갈 자리가 필요하다.
  return pathname.startsWith("/");
}

export function BackButton() {
  const pathname = usePathname();
  const router = useRouter();
  if (!isBackVisible(pathname)) return null;

  return (
    <button
      type="button"
      onClick={() => router.back()}
      className="tap-target flex flex-none items-center gap-1.5 rounded-md border border-line bg-surface px-2.5 text-[12px] font-semibold hover:bg-sunk"
    >
      <svg
        aria-hidden="true"
        width="12"
        height="12"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      >
        <path d="M13 8H4M7.5 4.5 4 8l3.5 3.5" />
      </svg>
      뒤로
    </button>
  );
}
