"use client";

import { PALETTE_OPEN_EVENT } from "@/components/console/CommandPalette";
import { useCommandModifierLabel } from "@/components/console/command-modifier";

/** 레일 상단의 검색 트리거 — 누르면 ⌘K 팔레트를 연다.
 *
 * 버튼이 따로 있는 이유: 단축키만 두면 그 기능이 있는 줄 아는 사람만 쓴다. 우측
 * `⌘K` 칩이 단축키를 **가르치는** 자리이기도 하다(디자인 §0). */
export function SidebarSearchTrigger() {
  const commandModifier = useCommandModifierLabel();

  return (
    <button
      type="button"
      onClick={() => window.dispatchEvent(new CustomEvent(PALETTE_OPEN_EVENT))}
      className="tap-target flex w-full items-center gap-2 rounded-md border border-white/[0.13] bg-white/[0.05] px-2.5 text-left text-[12.5px] text-sidebar-muted transition-colors hover:bg-white/10 hover:text-sidebar-text"
    >
      <svg
        aria-hidden="true"
        width="13"
        height="13"
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        className="flex-none"
      >
        <circle cx="7" cy="7" r="4.4" />
        <path d="M10.4 10.4 14 14" />
      </svg>
      <span className="flex-1 truncate">검색 · 이동</span>
      {/* 실제 OS의 수식키 하나만 적는다 — 둘 다 적으면 폭이 늘어 레일에서 잘리고,
          실제 동작은 두 키를 모두 지원한다(shortcuts.ts). */}
      <kbd className="tabular flex-none rounded border border-white/[0.16] px-1 font-mono text-[10.5px]">
        {commandModifier}K
      </kbd>
    </button>
  );
}
