import { SITE_STATUSES } from "@/lib/core-api/types";
import type { SidebarSite } from "./site-context";

/** Reject an incomplete response rather than inventing an empty or partial list. */
export function parseShellSites(value: unknown): SidebarSite[] | null {
  if (!Array.isArray(value)) return null;
  const sites: SidebarSite[] = [];
  const ids = new Set<string>();
  for (const item of value) {
    if (!item || typeof item !== "object") return null;
    const { siteId, name, status } = item as Record<string, unknown>;
    if (typeof siteId !== "string" || !siteId.trim() || typeof name !== "string" || !name.trim()
      || typeof status !== "string" || !SITE_STATUSES.includes(status as SidebarSite["status"]) || ids.has(siteId)) return null;
    ids.add(siteId);
    sites.push({ siteId, name, status: status as SidebarSite["status"] });
  }
  return sites;
}
