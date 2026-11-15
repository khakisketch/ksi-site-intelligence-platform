"use client";

import { useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";

import { isChromelessPath } from "./chromeless-path";
import { isViewerPath } from "./viewer-path";
import { useDesktopNavCollapsed } from "./desktop-nav-preference";

const CONSOLE_BODY_CLASSES = [
  "md:grid",
  "md:h-screen",
  "md:grid-cols-[56px_1fr]",
  "lg:grid-cols-[188px_1fr]",
  "md:grid-rows-[auto_minmax(0,1fr)]",
  "md:overflow-hidden",
] as const;

/**
 * Root layouts survive App Router navigation, including a session-expiry
 * redirect to /login. Reconcile the body grid with the live pathname so the
 * chromeless login card never inherits the console's rail column.
 *
 * The global header spans both columns (row 1); the rail and the viewport share
 * row 2 (ADR-KSI-043). The viewer-first paths (site 공간/자료) keep the main from
 * scrolling and hide only the site header at lg+; the exception is owned by
 * `viewer-path.ts` and is toggled here because layouts survive client navigation.
 */
export function ShellLayoutMode() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const navCollapsed = useDesktopNavCollapsed();

  useEffect(() => {
    const chromeless = isChromelessPath(pathname);
    const viewer = !chromeless && isViewerPath(pathname, searchParams?.toString());
    document.body.classList.add("min-h-full");
    for (const className of CONSOLE_BODY_CLASSES) {
      document.body.classList.toggle(className, !chromeless);
    }
    document.body.classList.toggle("viewer-shell", viewer);
    document.body.classList.toggle("desktop-nav-collapsed", !chromeless && navCollapsed);
  }, [pathname, searchParams, navCollapsed]);

  return null;
}

/** Hide server-rendered shell fragments when a preserved layout reaches login. */
export function ShellOnly({ children }: { children: React.ReactNode }) {
  return isChromelessPath(usePathname()) ? null : children;
}

const VIEWPORT_BASE =
  "flex min-h-full flex-col md:col-start-2 md:row-start-2 md:min-h-0 md:overflow-hidden";
const MAIN_BASE =
  "flex-1 pb-[var(--mobile-bottom-nav-clearance)] md:min-h-0 md:overflow-y-auto md:pb-0";

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
