"use client";

import { PALETTE_OPEN_EVENT } from "@/components/console/CommandPalette";

/* 상단바의 검색 트리거 — 사이드바가 숨는 lg 미만에서만 보인다.
 *
 * 사이드바 트리거(SidebarSearchTrigger)를 그대로 재사용하지 않는 이유는 그 버튼이
 * 어두운 레일 위에 그려지는 전제(흰 투명 배경·밝은 글자)라, 밝은 상단바에서는
 * 대비가 무너지고 390px 폭에서 글자까지 담기 좁기 때문이다. 동작은 같다 —
 * 같은 PALETTE_OPEN_EVENT 를 쏘아 ⌘K 팔레트를 연다. 새 데이터 읽기·API 없음. */
export function TopBarSearchTrigger() {
  return (
    <span className="inline-flex flex-none lg:hidden">
      <button
        type="button"
        onClick={() => window.dispatchEvent(new CustomEvent(PALETTE_OPEN_EVENT))}
        aria-label="검색 · 이동"
        className="tap-target flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-md border border-line-strong px-2.5 text-[13px] font-semibold text-ink-2 hover:bg-sunk"
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
