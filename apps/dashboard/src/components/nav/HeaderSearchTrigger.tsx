"use client";

import { PALETTE_OPEN_EVENT } from "@/components/console/CommandPalette";
import { useCommandModifierLabel } from "@/components/console/command-modifier";

/**
 * 데스크톱 헤더의 검색 입구 — 입력칸처럼 보이지만 누르면 ⌘K 팔레트를 연다.
 * 단축키만 두면 그 기능이 있는 줄 아는 사람만 쓰므로 단축키 힌트를 함께 보인다.
 * 좁은 화면은 TopBarSearchTrigger(아이콘 버튼)가 같은 이벤트를 쏜다.
 */
export function HeaderSearchTrigger() {
  const commandModifier = useCommandModifierLabel();
  return (
    <button
      type="button"
      onClick={() => window.dispatchEvent(new CustomEvent(PALETTE_OPEN_EVENT))}
      aria-label="검색 · 이동"
      className="tap-target hidden w-11 items-center justify-center gap-2 rounded-md border border-line-strong bg-surface px-2.5 text-left text-body text-ink-muted transition-colors hover:bg-sunk md:flex lg:w-[260px] lg:justify-start"
    >
      <svg aria-hidden="true" width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" className="flex-none">
        <circle cx="7" cy="7" r="4.4" />
        <path d="M10.4 10.4 14 14" />
      </svg>
      <span className="hidden flex-1 truncate lg:block">검색 · 이동</span>
      <kbd className="tabular hidden flex-none lg:block rounded border border-line px-1 font-mono text-micro">{commandModifier}K</kbd>
    </button>
  );
}
