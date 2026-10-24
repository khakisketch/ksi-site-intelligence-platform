"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";

import { isChromelessPath } from "./chromeless-path";

const CONSOLE_BODY_CLASSES = [
  "lg:grid",
  "lg:h-screen",
  "lg:grid-cols-[176px_1fr]",
  "lg:overflow-hidden",
  "xl:grid-cols-[232px_1fr]",
] as const;

/**
 * Root layouts survive App Router navigation, including a session-expiry
 * redirect to /login. Reconcile the body grid with the live pathname so the
 * chromeless login card never inherits the console's 176px sidebar column.
 *
 * The console shell is deliberately uniform: every authenticated desktop
 * screen keeps the full labelled rail and the global top bar. There is no
 * path-based compact mode; the previous 64px workbench rail made the same
 * product look like a different app on workspace/materials.
 */
export function ShellLayoutMode() {
  const pathname = usePathname();

  useEffect(() => {
    const chromeless = isChromelessPath(pathname);
    document.body.classList.add("min-h-full");
    for (const className of CONSOLE_BODY_CLASSES) {
      document.body.classList.toggle(className, !chromeless);
    }
  }, [pathname]);

  return null;
}

/** Hide server-rendered shell fragments when a preserved layout reaches login. */
export function ShellOnly({ children }: { children: React.ReactNode }) {
  return isChromelessPath(usePathname()) ? null : children;
}

const VIEWPORT_BASE =
  "flex min-h-full flex-col lg:col-start-2 lg:row-start-1 lg:min-h-0 lg:overflow-hidden";
const MAIN_BASE =
  "flex-1 pb-[var(--mobile-bottom-nav-clearance)] lg:min-h-0 lg:overflow-y-auto lg:pb-0";

export function ShellViewport({ children }: { children: React.ReactNode }) {
  return <div className={VIEWPORT_BASE}>{children}</div>;
}

export function ShellMain({ children }: { children: React.ReactNode }) {
  return (
    <main
      id="main-content"
      tabIndex={-1}
      className={MAIN_BASE}
    >
      {children}
    </main>
  );
}
