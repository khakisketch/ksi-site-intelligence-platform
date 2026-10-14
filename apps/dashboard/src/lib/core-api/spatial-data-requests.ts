import "server-only";

import { coreFetch, coreFetchBinary } from "./client";
import type { SpatialDataJobView, SpatialDataRequestPage } from "./spatial-data-types";
export type {
  SpatialDataAvailability,
  SpatialDataBounds,
  SpatialDataExecutionState,
  SpatialDataJobView,
  SpatialDataReceipt,
  SpatialDataRequestPage,
} from "./spatial-data-types";
export { isSpatialDataAvailability, isSpatialDataExecutionState } from "./spatial-data-types";

function requestsPath(siteId: string, workAreaId: string): string {
  return `/v1/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/spatial-data-requests`;
}

/** Read one bounded page; Core remains the scope and cursor authority. */
export function listSpatialDataRequests(
  siteId: string,
  workAreaId: string,
  options: { limit: number; cursor?: string },
): Promise<SpatialDataRequestPage> {
  return coreFetch<SpatialDataRequestPage>(requestsPath(siteId, workAreaId), {
    query: { limit: options.limit, cursor: options.cursor },
  });
}

/** Re-read the exact request through Core's current Site/WorkArea scope check. */
export function getSpatialDataRequest(
  siteId: string,
  workAreaId: string,
  requestId: string,
): Promise<SpatialDataJobView> {
  return coreFetch<SpatialDataJobView>(`${requestsPath(siteId, workAreaId)}/${encodeURIComponent(requestId)}`);
}

/** Cancel only through Core; its state machine remains authoritative. */
export function cancelSpatialDataRequest(
  siteId: string,
  workAreaId: string,
  requestId: string,
): Promise<SpatialDataJobView> {
  return coreFetch<SpatialDataJobView>(
    `${requestsPath(siteId, workAreaId)}/${encodeURIComponent(requestId)}/cancel`,
    { method: "POST" },
  );
}

/** Exact authorized output bytes; no storage key or signed URL reaches the browser. */
export function downloadSpatialDataRequestFile(
  siteId: string,
  workAreaId: string,
  requestId: string,
) {
  return coreFetchBinary(
    `${requestsPath(siteId, workAreaId)}/${encodeURIComponent(requestId)}/file`,
  );
}
