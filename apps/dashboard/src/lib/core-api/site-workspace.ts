import "server-only";

import { coreFetch } from "./client";
import type { SiteBriefing, SiteWorkspaceView } from "./types";

export async function getSiteWorkspace(siteId: string): Promise<SiteWorkspaceView> {
  return coreFetch<SiteWorkspaceView>(
    `/v1/sites/${encodeURIComponent(siteId)}/workspace`,
  );
}

/** 404는 아직 생성된 브리핑이 없다는 정상 초기 상태다. 호출부가 구분해 표현한다. */
export async function getLatestSiteBriefing(siteId: string): Promise<SiteBriefing> {
  return coreFetch<SiteBriefing>(
    `/v1/sites/${encodeURIComponent(siteId)}/briefings/latest`,
  );
}

export async function refreshSiteBriefing(siteId: string): Promise<SiteBriefing> {
  return coreFetch<SiteBriefing>(
    `/v1/sites/${encodeURIComponent(siteId)}/briefings/refresh`,
    { method: "POST" },
  );
}
