"use client";

import { usePathname } from "next/navigation";

import { useSidebarSites } from "./SiteListContext";
import { resolveSiteId, siteMark, siteShortName } from "./site-context";

/**
 * The closed layer-panel trigger keeps the current site visible without the
 * full site header. It reads the same minimal site summaries as the rail.
 * Only rendered inside the viewer desktop placement, so dense screens never
 * pay for another navigation hook.
 */
export function ViewerSiteBadge({ fallback = "현장" }: { fallback?: string }) {
  const pathname = usePathname() ?? "";
  const sites = useSidebarSites();
  const siteId = resolveSiteId(pathname);
  const current = siteId ? sites.find((site) => site.siteId === siteId) ?? null : null;
  if (!current) return <span className="min-w-0 truncate">{fallback}</span>;
  return (
    <>
      <span
        aria-hidden="true"
        className="grid size-5 flex-none place-items-center rounded bg-sidebar text-[9px] font-bold text-sidebar-text"
      >
        {siteMark(current.name)}
      </span>
      <span className="min-w-0 truncate">{siteShortName(current.name)}</span>
    </>
  );
}
