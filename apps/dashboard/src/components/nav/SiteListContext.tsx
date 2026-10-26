"use client";

import { createContext, useContext, type ReactNode } from "react";

import type { SidebarSite } from "./site-context";

/**
 * The root layout already reads the minimal site summaries for the desktop
 * rail. Viewer panels (site switcher + section links) live deep inside the
 * page tree, so pass that same server snapshot through a client context
 * instead of re-fetching it in every page.
 *
 * Only siteId/name/status are carried — the same minimal summary the rail
 * receives. AOI, permissions, and ledger values never enter this context.
 */
const SiteListContext = createContext<readonly SidebarSite[]>([]);

export function SiteListProvider({
  sites,
  children,
}: {
  sites: readonly SidebarSite[];
  children: ReactNode;
}) {
  return <SiteListContext.Provider value={sites}>{children}</SiteListContext.Provider>;
}

export function useSidebarSites(): readonly SidebarSite[] {
  return useContext(SiteListContext);
}
