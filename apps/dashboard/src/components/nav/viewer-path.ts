import { normalizeSiteTab } from "@/lib/site-epochs";
import { resolveSiteId } from "./site-context";

export function isViewerPath(
  pathname: string | null | undefined,
  search?: string | null,
): boolean {
  if (!pathname) return false;
  const [path, query] = pathname.split("?", 2);
  if (!/^\/sites\/[^/]+\/?$/.test(path) || !resolveSiteId(path)) return false;
  const params = new URLSearchParams(query ?? search ?? "");
  const section = normalizeSiteTab(params.get("section") ?? params.get("tab"));
  return section === "space" && params.get("mode") !== "results";
}
