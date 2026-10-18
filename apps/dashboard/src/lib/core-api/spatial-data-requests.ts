import "server-only";

import { coreFetch, coreFetchBinary } from "./client";
import type { SpatialDataBounds, SpatialDataJobView, SpatialDataRequestPage } from "./spatial-data-types";
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

/** Console이 만들 수 있는 요청 본문 — Core가 엄격 스키마로 다시 검증한다. */
export interface SpatialDataRequestInput {
  assetRef: string;
  requestedBounds: SpatialDataBounds;
  observedCrsDigest: string;
  resolutionMode: "NATIVE";
  purpose: "GENERAL_DATA_USE" | "EXTERNAL_AI";
}

/**
 * 정확한 네이티브 사각형에 대한 준비 요청을 만든다.
 *
 * Core는 현재 명시된 권리(grant)·정책·활성화를 확인한 뒤에만 작업을 만든다 —
 * 이 함수는 그 판단을 대신하지 않는다. 같은 Idempotency-Key의 재시도는 같은
 * 작업으로 돌아온다(같은 요청을 두 번 만들지 않는다).
 */
export function createSpatialDataRequest(
  siteId: string,
  workAreaId: string,
  input: SpatialDataRequestInput,
  idempotencyKey: string,
): Promise<SpatialDataJobView> {
  return coreFetch<SpatialDataJobView>(requestsPath(siteId, workAreaId), {
    method: "POST",
    body: input,
    headers: { "Idempotency-Key": idempotencyKey },
  });
}
