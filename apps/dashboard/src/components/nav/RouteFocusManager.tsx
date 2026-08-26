"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

/**
 * Client navigation keeps the browser focus on the link that initiated the
 * transition. Sighted users can infer that the page changed, but a screen
 * reader may continue reading the old navigation context. Move focus to the
 * canonical main landmark after a pathname change, without stealing focus on
 * the first hydration or changing scroll position.
 */
export function RouteFocusManager() {
  const pathname = usePathname();
  const previousPathname = useRef(pathname);

  useEffect(() => {
    if (previousPathname.current === pathname) return;
    previousPathname.current = pathname;

    const frame = window.requestAnimationFrame(() => {
      document.getElementById("main-content")?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [pathname]);

  return null;
}
