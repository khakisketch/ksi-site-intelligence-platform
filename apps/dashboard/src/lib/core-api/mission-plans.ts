import "server-only";

import { coreFetch } from "./client";
import type { MissionPlanRequest, MissionPlanResponse } from "./types";

export async function issueMissionPlan(input: MissionPlanRequest): Promise<MissionPlanResponse> {
  return coreFetch<MissionPlanResponse>("/v1/missions/plans", {
    method: "POST",
    body: input,
  });
}
