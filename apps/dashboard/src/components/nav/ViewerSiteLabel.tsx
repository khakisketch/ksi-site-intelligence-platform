"use client";

import { usePathname } from "next/navigation";

import { useSidebarSites } from "./SiteListContext";
import { resolveSiteId, siteMark, siteShortName } from "./site-context";

/**
 * Compact current-site identity for the closed viewer layer toggle. The full
 * site switcher lives in the layer panel; this keeps the site obvious when the
 * user chooses the full-canvas state. Hidden below xl so the compact toolbar
 * keeps its one-row layout.
 */
export function ViewerSiteLabel() {
  const pathname = usePathname() ?? "";
  const sites = useSidebarSites();
  const siteId = resolveSiteId(pathname);
  const current = siteId ? sites.find((site) => site.siteId === siteId) ?? null : null;
  if (!current) return null;
  return (
    <span className="hidden min-w-0 items-center gap-1.5 xl:flex" aria-hidden="true">
      <span className="grid size-5 flex-none place-items-center rounded bg-sidebar text-[9px] font-bold text-sidebar-text">
        {siteMark(current.name)}
      </span>
      <span className="max-w-[190px] truncate text-[11.5px] font-semibold text-ink-2" title={current.name}>
        {siteShortName(current.name)}
      </span>
    </span>
  );
}
