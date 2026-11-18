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

/**
 * 프로젝트 안의 업무 섹션(ADR-KSI-043). 레일과 모바일 하단 탭이 같은 목록을 쓴다.
 * "자료"는 독립 화면(`/sites/{id}/data`)이다. 공간 뷰어 안의 자료 패널(`?panel=materials`)은
 * 뷰어에서 볼 관측을 고르는 보조 패널로 남고, 그 주소도 자료 섹션으로 읽는다.
 */
export type ProjectSection = "space" | "data" | "analysis";
export const PROJECT_SECTIONS: ReadonlyArray<{ key: ProjectSection; label: string; icon: NavIconName }> = [
  { key: "space", label: "공간", icon: "sites" },
  { key: "data", label: "자료", icon: "layers" },
  { key: "analysis", label: "분석", icon: "chart" },
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
    case "measurements":
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

/** 현재 위치가 프로젝트의 어느 업무 섹션인지. 설정(`section=manage`)이나 프로젝트 밖이면 null. */
export function resolveProjectSection(
  pathname: string,
  search: QueryReader | null | undefined,
): ProjectSection | null {
  const route = SITE_PATH.exec(pathname)?.[2]?.split("/")[1] ?? "";
  if ((route === "data" || route === "upload") && resolveSiteId(pathname)) return "data";
  const section = resolveSiteSection(pathname, search);
  if (section === "analysis") return "analysis";
  if (section !== "space") return null;
  const panel = search?.get("panel");
  return route === "" && (panel === "materials" || panel === "intake") ? "data" : "space";
}

export function projectSectionHref(siteId: string, section: ProjectSection | null): string {
  const base = `/sites/${encodeURIComponent(siteId)}`;
  if (section === "analysis") return `${base}/analysis`;
  if (section === "data") return `${base}/data`;
  return base;
}

/** 자료 섹션의 한 장면 — 구역·선택 자료·검색 조건·페이지를 주소에 남긴다. 값이 없는 조건은 싣지 않는다. */
export interface SiteDataScope {
  workAreaId?: string | null;
  assetRef?: string | null;
  q?: string;
  kind?: string;
  state?: string;
  cursor?: string | null;
  /** 하단 서랍(등록 진행)을 열어 둔다. */
  progress?: boolean;
}

export function siteDataHref(siteId: string, scope: SiteDataScope = {}): string {
  const query = new URLSearchParams();
  if (scope.workAreaId) query.set("workAreaId", scope.workAreaId);
  if (scope.assetRef) query.set("assetRef", scope.assetRef);
  if (scope.q) query.set("q", scope.q);
  if (scope.kind) query.set("kind", scope.kind);
  if (scope.state) query.set("state", scope.state);
  if (scope.cursor) query.set("cursor", scope.cursor);
  if (scope.progress) query.set("progress", "1");
  const text = query.toString();
  return `/sites/${encodeURIComponent(siteId)}/data${text ? `?${text}` : ""}`;
}

/** 한 화면 올리기. 구역을 알면 그 구역으로 열고, 모르면 화면이 첫 구역을 고른다. */
export function siteUploadHref(sitePath: string, workAreaId?: string | null): string {
  return `${sitePath}/upload${workAreaId ? `?workAreaId=${encodeURIComponent(workAreaId)}` : ""}`;
}

/** 다른 프로젝트로 전환할 때 지금 보던 섹션을 유지한다. 섹션을 모르면 공간으로 간다. */
export function projectSwitchHref(siteId: string, section: ProjectSection | null): string {
  return projectSectionHref(siteId, section);
}
