// Viewer-first shell paths — a deliberate exception to the uniform console rail.
//
// The product decided on 2026-10-26 (console design decision A) that site
// **공간** and **자료** exploration use a canvas-first, minimal-chrome surface.
// 업무·결과·검토 and the management sub-screens keep the dense list/form shell.
//
// This predicate is the single source for that boundary. It is consumed by:
// - root layout (SSR body class),
// - ShellLayoutMode (client navigation reconciliation),
// - DesktopSidebar (compact icon rail),
// - CSS (hide the global top bar / site header only on viewer paths).
//
// Query-dependent exclusions are part of the contract: `/sites/{id}` is the
// workspace viewer by default, but `?section=work-orders`, `?section=manage`,
// `?section=results`, and the workspace's `?mode=results` review are dense
// management/review screens and must keep the normal shell.

const SITE_PATH = /^\/sites\/([^/]+)(\/.*)?$/;

/** Sections that render the site workspace (viewer) rather than a dense tab. */
const VIEWER_SECTIONS = new Set(["workspace", "overview", "observations"]);

export function isViewerPath(
  pathname: string | null | undefined,
  search?: string | null,
): boolean {
  if (!pathname) return false;
  // Callers normally pass pathname and search separately. Accept a combined
  // path as well so URL-level checks cannot silently classify a management
  // screen as a viewer screen.
  const queryIndex = pathname.indexOf("?");
  const effectivePath = queryIndex === -1 ? pathname : pathname.slice(0, queryIndex);
  const effectiveSearch = queryIndex === -1
    ? search
    : `${pathname.slice(queryIndex)}${search ? `&${search.replace(/^\?/, "")}` : ""}`;
  const match = SITE_PATH.exec(effectivePath);
  if (!match) return false;
  const rawSiteId = match[1]!;
  let siteId: string;
  try {
    siteId = decodeURIComponent(rawSiteId);
  } catch {
    return false;
  }
  if (!siteId || siteId === "new") return false;

  const rest = match[2] ?? "";
  if (rest === "/spatial-assets" || rest === "/spatial-assets/") return true;
  if (rest !== "" && rest !== "/") return false;

  let params: URLSearchParams;
  try {
    params = new URLSearchParams(effectiveSearch ?? "");
  } catch {
    return false;
  }
  const section = params.get("section") ?? params.get("tab");
  if (section && !VIEWER_SECTIONS.has(section)) return false;
  // The workspace's result-review mode is a dense review screen. Compare and
  // single-epoch exploration stay in the viewer.
  if (params.get("mode") === "results") return false;
  return true;
}
