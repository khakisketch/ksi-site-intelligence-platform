import type { SiteStatus } from "@/lib/core-api/types";

import type { NavIconName } from "./NavIcon";

/** 데스크톱 레일에 넘기는 최소 현장 요약 — AOI·권한·원장 값은 클라이언트로 보내지 않는다. */
export interface SidebarSite {
  siteId: string;
  name: string;
  status: SiteStatus;
}

export type SiteSection = "workspace" | "materials" | "work-orders" | "results";

export const SITE_CONTEXT_SECTIONS: readonly {
  key: SiteSection;
  label: string;
  icon: NavIconName;
}[] = [
  { key: "workspace", label: "작업공간", icon: "sites" },
  { key: "materials", label: "자료", icon: "layers" },
  { key: "work-orders", label: "관측 작업", icon: "work" },
  { key: "results", label: "결과", icon: "chart" },
];

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

/**
 * 현재 경로가 현장의 어느 상위 영역인지 판정한다. 상위 영역에 속하지 않는
 * 하위 화면(작업구역·외부 비교 기록 등)은 null로 두어 엉뚱한 탭을 켜지 않는다.
 */
export function resolveSiteSection(
  pathname: string,
  search: QueryReader | null | undefined,
): SiteSection | null {
  const match = SITE_PATH.exec(pathname);
  if (!match || !resolveSiteId(pathname)) return null;
  const rest = match[2] ?? "";
  if (rest === "" || rest === "/") {
    const section = search?.get("section") ?? null;
    if (section === "work-orders") return "work-orders";
    if (section === "manage") return null;
    return "workspace";
  }
  if (rest.startsWith("/spatial-assets") || rest.startsWith("/spatial-data-requests")) {
    return "materials";
  }
  if (rest.startsWith("/analysis")) return "results";
  return null;
}

/** 현장 이동 주소 — 새 현장으로 범위를 넘기지 않는다. 받는 화면이 자기 범위를 다시 정한다. */
export function siteSectionHref(siteId: string, section: SiteSection | null): string {
  const base = `/sites/${encodeURIComponent(siteId)}`;
  switch (section) {
    case "materials":
      return `${base}/spatial-assets`;
    case "work-orders":
      return `${base}?section=work-orders`;
    case "results":
      return `${base}/analysis`;
    case "workspace":
    default:
      return base;
  }
}

/** 현장을 바꿔도 같은 영역을 유지한다. 그 영역이 없는 하위 화면은 작업공간으로 돌아간다. */
export function siteSwitchHref(siteId: string, section: SiteSection | null): string {
  return siteSectionHref(siteId, section ?? "workspace");
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
