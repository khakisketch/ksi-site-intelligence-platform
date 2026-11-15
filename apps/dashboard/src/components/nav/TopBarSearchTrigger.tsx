"use client";

import { PALETTE_OPEN_EVENT } from "@/components/console/CommandPalette";

/* 상단바의 검색 트리거 — 헤더의 검색 입구(HeaderSearchTrigger)가 숨는 768px 미만에서만 보인다.
 * 390px 폭에 맞춘 작은 버튼이며 동작은 같다 — 같은 PALETTE_OPEN_EVENT 를 쏘아
 * ⌘K 팔레트를 연다. 새 데이터 읽기·API 없음. */
export function TopBarSearchTrigger() {
  return (
    <span className="inline-flex flex-none md:hidden">
      <button
        type="button"
        onClick={() => window.dispatchEvent(new CustomEvent(PALETTE_OPEN_EVENT))}
        aria-label="검색 · 이동"
        className="tap-target flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md border border-line-strong px-2.5 text-body font-semibold text-ink-2 hover:bg-sunk"
      >
        <svg
          aria-hidden="true"
          width="14"
          height="14"
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          className="flex-none"
        >
          <circle cx="7" cy="7" r="4.4" />
          <path d="M10.4 10.4 14 14" />
        </svg>
        <span aria-hidden="true">검색</span>
      </button>
    </span>
  );
}
