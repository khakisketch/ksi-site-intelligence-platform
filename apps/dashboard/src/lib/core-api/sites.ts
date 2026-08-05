import "server-only";

import { coreFetch } from "./client";
import type { AoiVertex, SiteFrame, SiteStatus, SiteView } from "./types";

export async function listSites(): Promise<SiteView[]> {
  const body = await coreFetch<{ sites: SiteView[] }>("/v1/sites");
  return body.sites;
}

export async function getSite(siteId: string): Promise<SiteView> {
  return coreFetch<SiteView>(`/v1/sites/${encodeURIComponent(siteId)}`);
}

export interface RegisterSiteInput {
  siteId: string;
  name: string;
  siteFrame: SiteFrame;
  /** 선택 — 생략하면 등록 후 setSiteAoi 로 나중에 설정한다(UNMAPPED 상태에서만). */
  aoi?: { vertices: AoiVertex[] };
}

export async function registerSite(input: RegisterSiteInput): Promise<SiteView> {
  const body = await coreFetch<{ site: SiteView }>("/v1/sites", {
    method: "POST",
    body: input,
  });
  return body.site;
}

export interface SetSiteAoiInput {
  aoi: { vertices: AoiVertex[] };
  /** 등록된 현장의 것과 정확 일치해야 한다(SITE_FRAME_MISMATCH). */
  siteFrame: SiteFrame;
}

/** UNMAPPED 상태의 현장에만 AOI 를 설정·교체한다(그 외 상태는 409 AOI_LOCKED). */
export async function setSiteAoi(siteId: string, input: SetSiteAoiInput): Promise<SiteView> {
  const body = await coreFetch<{ site: SiteView }>(
    `/v1/sites/${encodeURIComponent(siteId)}/aoi`,
    { method: "PUT", body: input },
  );
  return body.site;
}

export interface TransitionSiteInput {
  targetStatus: SiteStatus;
  evidence: string;
  reason: string;
}

export async function transitionSite(siteId: string, input: TransitionSiteInput): Promise<SiteView> {
  const body = await coreFetch<{ site: SiteView }>(
    `/v1/sites/${encodeURIComponent(siteId)}/transitions`,
    { method: "POST", body: input },
  );
  return body.site;
}
