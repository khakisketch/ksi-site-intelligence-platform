import "server-only";

import { coreFetch } from "./client";
import type { MissionRecordResponse } from "./types";

export async function listMissions(siteId?: string): Promise<MissionRecordResponse[]> {
  return coreFetch<MissionRecordResponse[]>("/v1/missions", { query: { siteId } });
}

export async function getMission(missionId: string): Promise<MissionRecordResponse> {
  return coreFetch<MissionRecordResponse>(`/v1/missions/${encodeURIComponent(missionId)}`);
}
