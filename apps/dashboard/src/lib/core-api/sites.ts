import "server-only";

import { coreFetch } from "./client";
import type { SiteFrame, SiteStatus, SiteView } from "./types";

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
}

export async function registerSite(input: RegisterSiteInput): Promise<SiteView> {
  const body = await coreFetch<{ site: SiteView }>("/v1/sites", {
    method: "POST",
    body: input,
  });
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
