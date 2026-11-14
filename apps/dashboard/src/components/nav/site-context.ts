import { normalizeSiteTab, SITE_TABS, type SiteTabKey } from "@/lib/site-epochs";
import type { SiteStatus } from "@/lib/core-api/types";

import type { NavIconName } from "./NavIcon";

/** 데스크톱 레일에 넘기는 최소 현장 요약 — AOI·권한·원장 값은 클라이언트로 보내지 않는다. */
export interface SidebarSite {
  siteId: string;
  name: string;
  status: SiteStatus;
}

export type SiteSection = SiteTabKey;
export const SITE_CONTEXT_SECTIONS = SITE_TABS.map<{ key: SiteSection; label: string; icon: NavIconName }>((tab) => ({
  ...tab,
  icon: tab.key === "space" ? "sites" : "chart",
}));

const SITE_PATH = /^\/sites\/([^/]+)(\/.*)?$/;

/** `/sites/{siteId}` 경로에서 사람이 읽는 siteId를 꺼낸다. 등록 화면(`/sites/new`)은 제외한다. */
export function resolveSiteId(pathname: string): string | null {
  const match = SITE_PATH.exec(pathname);
  if (!match) return null;
  const raw = match[1]!;
  let siteId: string;
  try {
    siteId = decodeURIComponent(raw);
  } catch {
    return null;
  }
  if (!siteId || siteId === "new") return null;
  return siteId;
}

type QueryReader = { get(name: string): string | null };

export function resolveSiteSection(
  pathname: string,
  search: QueryReader | null | undefined,
): SiteSection | null {
  const match = SITE_PATH.exec(pathname);
  if (!match || !resolveSiteId(pathname)) return null;
  const route = match[2]?.split("/")[1] ?? "";
  switch (route) {
    case "": {
      const section = normalizeSiteTab(search?.get("section") ?? search?.get("tab"));
      if (section === "manage") return null;
      return section === "analysis" || search?.get("mode") === "results" ? "analysis" : "space";
    }
    case "spatial-assets":
    case "spatial-data-requests":
    case "work-areas": return "space";
    case "analysis":
    case "observations": return "analysis";
    default: return null;
  }
}

export function siteSectionHref(siteId: string, section: SiteSection | null): string {
  const base = `/sites/${encodeURIComponent(siteId)}`;
  return section === "analysis" ? `${base}/analysis` : base;
}

export function siteSettingsHref(siteId: string): string {
  return `${siteSectionHref(siteId, "space")}?section=manage`;
}

export function siteSwitchHref(siteId: string, section: SiteSection | null): string {
  return siteSectionHref(siteId, section);
}

/** 라이선스·합성 표기는 상태줄과 상세 머리가 이미 말한다 — 좁은 레일에서는 이름만 남긴다. */
export function siteShortName(name: string): string {
  const trimmed = name.trim();
  const match = /^(.*?)(\s*\([^()]+\))$/.exec(trimmed);
  const short = (match?.[1] ?? trimmed).trim();
  return short || trimmed || "현장";
}

/** 레일의 작은 사이트 표식 — 이름 첫 글자만 쓴다. 새 이미지·색을 만들지 않는다. */
export function siteMark(name: string): string {
  return siteShortName(name).slice(0, 1) || "현";
}
