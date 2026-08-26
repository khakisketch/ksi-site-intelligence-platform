import "server-only";

import { coreFetch } from "./client";
import type { AcquisitionDeploymentProfileV1, AcquisitionReadinessView } from "./types";

export function getAcquisitionProfile(siteId: string): Promise<AcquisitionDeploymentProfileV1> {
  return coreFetch<AcquisitionDeploymentProfileV1>(
    `/v1/sites/${encodeURIComponent(siteId)}/acquisition-profile`,
  );
}

export function getAcquisitionReadiness(siteId: string): Promise<AcquisitionReadinessView> {
  return coreFetch<AcquisitionReadinessView>(
    `/v1/sites/${encodeURIComponent(siteId)}/acquisition-readiness`,
  );
}
