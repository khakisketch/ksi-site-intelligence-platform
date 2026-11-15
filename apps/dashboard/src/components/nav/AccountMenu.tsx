"use client";

import Link from "next/link";

import { logout } from "@/app/login/actions";

import { useHeaderPopover } from "./use-header-popover";

/**
 * 계정 메뉴 — 이니셜 버튼 하나가 이름·역할·계정 화면·로그아웃을 연다.
 * 768px 이상에서는 레일 아래쪽(`placement="rail"`), 그보다 좁으면 상단바 오른쪽(`"header"`)에 둔다.
 * 두 자리 중 하나만 보이고 메뉴는 같다. 신원은 서버가 세션에서 읽어 넘긴다. 역할을 바꾸는 장치는 없다 —
 * 실제 역할은 httpOnly 쿠키의 토큰이 정하고 화면이 바꿀 수 있는 값이 아니다.
 */
export function AccountMenu({
  principalId,
  roleLabel,
  placement = "header",
}: {
  principalId: string;
  roleLabel: string;
  placement?: "header" | "rail";
}) {
  const { open, setOpen, rootRef, triggerRef } = useHeaderPopover();
  const initial = principalId.trim().charAt(0).toUpperCase() || "?";
  const rail = placement === "rail";
  const menuId = `account-menu-${placement}`;
  return (
    <div
      ref={rootRef}
      className={rail ? "relative mt-1 hidden flex-col border-t border-line pt-1 md:flex" : "relative flex-none md:hidden"}
      data-account-menu={placement}
    >
      {rail ? (
        <button
          ref={triggerRef}
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={menuId}
          aria-label={`계정 메뉴: ${principalId}`}
          data-tip={principalId}
          onClick={() => setOpen((value) => !value)}
          className="rail-link rail-account"
        >
          <span aria-hidden="true" className="grid size-6 flex-none place-items-center rounded-full bg-rail-active text-micro font-bold text-rail-active-ink">{initial}</span>
          <span className="rail-label min-w-0 text-left">
            <span className="block truncate text-caption font-semibold leading-4">{principalId}</span>
            <span className="block truncate text-micro leading-4 text-rail-muted">{roleLabel}</span>
          </span>
        </button>
      ) : (
        <button
          ref={triggerRef}
          type="button"
          aria-haspopup="menu"
          aria-expanded={open}
          aria-controls={menuId}
          aria-label={`계정 메뉴: ${principalId}`}
          onClick={() => setOpen((value) => !value)}
          className="tap-target grid size-9 place-items-center rounded-full bg-sunk text-caption font-bold text-ink-1 hover:bg-line"
        >
          {initial}
        </button>
      )}
      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label="계정"
          className={`absolute z-[60] w-[240px] rounded-lg border border-line bg-surface p-2 text-ink-1 shadow-xl ${
            rail ? "bottom-0 left-full ml-2" : "top-full right-0 mt-1.5"
          }`}
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
