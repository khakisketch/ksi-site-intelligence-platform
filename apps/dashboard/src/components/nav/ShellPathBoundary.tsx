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
