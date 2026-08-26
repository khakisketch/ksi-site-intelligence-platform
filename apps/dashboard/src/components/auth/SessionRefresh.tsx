"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";

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
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (pathname === "/login") return;
    let stopped = false;
    async function refresh() {
      const response = await requestRefresh();
      if (!stopped && response?.status === 401) {
        router.replace(`/login?notice=oidc-session-expired&next=${encodeURIComponent(pathname)}`);
      }
    }
    const interval = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    return () => {
      stopped = true;
      window.clearInterval(interval);
    };
  }, [pathname, router]);

  return null;
}
