import "server-only";

import { coreFetch } from "./client";
import type { AcquisitionProgressView } from "./types";

export function getAcquisitionProgress(workOrderId: string): Promise<AcquisitionProgressView> {
  return coreFetch<AcquisitionProgressView>(
    `/v1/observation-work-orders/${encodeURIComponent(workOrderId)}/acquisition-progress`,
  );
}
