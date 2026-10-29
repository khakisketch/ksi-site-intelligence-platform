"use client";

import { useAccountDisplayLock } from "@/components/nav/AccountDisplayBoundary";
import { useEffect } from "react";
import { usePathname } from "next/navigation";

const REFRESH_INTERVAL_MS = 10 * 60 * 1000;
let browserRefresh: Promise<Response | null> | null = null;

function requestRefresh(): Promise<Response | null> {
  browserRefresh ??= fetch("/api/auth/refresh", { method: "POST" })
    .catch(() => null)
    .finally(() => {
      browserRefresh = null;
    });
  return browserRefresh;
}

export function SessionRefresh() {
  const accountDisplay = useAccountDisplayLock();
  const pathname = usePathname();

  useEffect(() => {
    if (pathname === "/login") return;
    let stopped = false;
    async function refresh() {
      const response = await requestRefresh();
      if (!stopped && response?.status === 401) {
        // Preserve any in-progress subtree; let the user sign in in a new tab.
        accountDisplay?.invalidate();
      }
    }
    const interval = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    return () => {
      stopped = true;
      window.clearInterval(interval);
    };
  }, [accountDisplay, pathname]);

  return null;
}
