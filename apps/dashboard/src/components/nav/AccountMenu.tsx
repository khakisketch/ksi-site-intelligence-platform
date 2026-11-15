"use client";

import Link from "next/link";

import { logout } from "@/app/login/actions";

import { useHeaderPopover } from "./use-header-popover";

/**
 * 헤더의 계정 메뉴 — 이니셜 버튼 하나가 이름·역할·계정 화면·로그아웃을 연다.
 * 신원은 서버(TopBar)가 세션에서 읽어 넘긴다. 역할을 바꾸는 장치는 없다 —
 * 실제 역할은 httpOnly 쿠키의 토큰이 정하고 화면이 바꿀 수 있는 값이 아니다.
 */
export function AccountMenu({ principalId, roleLabel }: { principalId: string; roleLabel: string }) {
  const { open, setOpen, rootRef, triggerRef } = useHeaderPopover();
  const initial = principalId.trim().charAt(0).toUpperCase() || "?";
  return (
    <div ref={rootRef} className="relative flex-none" data-account-menu="true">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="account-menu"
        aria-label={`계정 메뉴: ${principalId}`}
        onClick={() => setOpen((value) => !value)}
        className="tap-target grid size-9 place-items-center rounded-full bg-sunk text-caption font-bold text-ink-1 hover:bg-line"
      >
        {initial}
      </button>
      {open && (
        <div
          id="account-menu"
          role="menu"
          aria-label="계정"
          className="absolute top-full right-0 z-[60] mt-1.5 w-[240px] rounded-lg border border-line bg-surface p-2 text-ink-1 shadow-xl"
        >
          <div className="px-2 py-1.5">
            <p className="truncate text-body font-semibold" title={principalId}>{principalId}</p>
            <p className="text-micro text-ink-muted">{roleLabel}</p>
          </div>
          <Link
            role="menuitem"
            href="/more"
            className="tap-target flex items-center rounded-md px-2 text-body hover:bg-sunk"
            onClick={() => setOpen(false)}
          >
            계정·도움 안내
          </Link>
          <form action={logout}>
            <button
              type="submit"
              role="menuitem"
              className="tap-target flex w-full items-center rounded-md px-2 text-left text-body text-ink-2 hover:bg-sunk"
            >
              로그아웃
            </button>
          </form>
        </div>
      )}
    </div>
  );
}
