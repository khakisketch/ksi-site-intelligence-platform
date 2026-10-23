"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

import { isChromelessPath } from "./chromeless-path";
import { isFocusModePath } from "./focus-mode-path";

const CONSOLE_BODY_CLASSES = [
  "lg:grid",
  "lg:h-screen",
  "lg:grid-cols-[176px_1fr]",
  "lg:overflow-hidden",
  "xl:grid-cols-[232px_1fr]",
] as const;

/** 집중 모드에서는 같은 셸 골격을 두고 레일 폭만 64px로 좁힌다. */
const FOCUS_BODY_CLASSES = ["lg:grid-cols-[64px_minmax(0,1fr)]"] as const;

/**
 * Root layouts survive App Router navigation, including a session-expiry
 * redirect to /login. Reconcile the body grid with the live pathname so the
 * chromeless login card never inherits the console's 176px sidebar column.
 *
 * Focus-mode workbench routes keep the same shell skeleton with a compact
 * 64px rail; leaving the route restores the normal 176/232px columns.
 */
export function ShellLayoutMode() {
  const pathname = usePathname();

  useEffect(() => {
    const chromeless = isChromelessPath(pathname);
    const focus = isFocusModePath(pathname);
    document.body.classList.add("min-h-full");
    for (const className of CONSOLE_BODY_CLASSES) {
      // 집중 모드에서는 폭 클래스만 끈다 — grid·h-screen·overflow 골격은 둔다.
      const isWidthClass =
        className === "lg:grid-cols-[176px_1fr]" || className === "xl:grid-cols-[232px_1fr]";
      document.body.classList.toggle(className, !chromeless && !(focus && isWidthClass));
    }
    for (const className of FOCUS_BODY_CLASSES) {
      document.body.classList.toggle(className, !chromeless && focus);
    }
  }, [pathname]);

  return null;
}

/** Hide server-rendered shell fragments when a preserved layout reaches login. */
export function ShellOnly({ children }: { children: React.ReactNode }) {
  return isChromelessPath(usePathname()) ? null : children;
}

/**
 * 집중 모드의 루트 뷰포트·본문 래퍼 — SSR 첫 페인트는 layout.tsx 가 같은
 * 분기로 고르고, 클라이언트 네비게이션 사이는 여기서 같은 술어로 맞춘다.
 * 집중이 아니면 예전 클래스 문자열 그대로라 다른 경로·로그인은 그대로다.
 */
const VIEWPORT_BASE =
  "flex min-h-full flex-col lg:col-start-2 lg:row-start-1 lg:min-h-0 lg:overflow-hidden";
const MAIN_BASE =
  "flex-1 pb-[var(--mobile-bottom-nav-clearance)] lg:min-h-0 lg:overflow-y-auto lg:pb-0";

export function ShellViewport({ children }: { children: React.ReactNode }) {
  // 모바일은 min-h-dvh 로 두어 키 큰 내용(인증 실패 안내 등)이 잘리지 않고
  // 그대로 스크롤된다. 데스크톱에서만 h-dvh 로 묶어 무대가 내 스크롤을 갖는다.
  const focus = isFocusModePath(usePathname());
  return (
    <div
      className={
        focus
          ? "flex min-h-dvh flex-col lg:col-start-2 lg:row-start-1 lg:h-dvh lg:min-h-0 lg:overflow-hidden"
          : VIEWPORT_BASE
      }
    >
      {children}
    </div>
  );
}

export function ShellMain({ children }: { children: React.ReactNode }) {
  const focus = isFocusModePath(usePathname());
  return (
    <main
      id="main-content"
      tabIndex={-1}
      className={
        focus
          ? "flex min-h-0 flex-1 flex-col pb-[var(--mobile-bottom-nav-clearance)] lg:min-h-0 lg:overflow-y-auto lg:pb-0"
          : MAIN_BASE
      }
    >
      {children}
    </main>
  );
}

/** A preserved root layout must restore the healthy bar after leaving a viewer. */
export function NormalShellTopBar({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  return isChromelessPath(path) || isFocusModePath(path) ? null : children;
}
