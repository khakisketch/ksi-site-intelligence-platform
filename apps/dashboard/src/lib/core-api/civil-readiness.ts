import "server-only";

import { coreFetch } from "./client";
import type { CivilReadinessView } from "./types";

/**
 * Site-level, read-only orientation for the civil workflow.
 *
 * The response never replaces the exact comparison/design-request preflight;
 * it only makes the latest evidence posture legible before an operator enters
 * those existing flows.
 */
export function getCivilReadiness(siteId: string): Promise<CivilReadinessView> {
  return coreFetch<CivilReadinessView>(
    `/v1/sites/${encodeURIComponent(siteId)}/civil-readiness`,
  );
}
