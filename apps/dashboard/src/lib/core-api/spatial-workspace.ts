import "server-only";

import { coreFetch } from "./client";

/**
 * SWX-1 읽기 전용 프로젝션 (`GET
 * /v1/sites/{siteId}/work-areas/{workAreaId}/spatial-workspace-observations`,
 * SITES_READ). Core 소유 형상(`site_spatial_workspace` 계약)의 Dashboard 읽기
 * 전용 옮김이다 — 판정·재계산을 하지 않으며, 서버가 준 문자열·불리언을 그대로
 * 둔다. `limit`은 1–50(Core 검증), `cursor`는 scope-bound opaque 값으로 그대로
 * 전달한다(해석·조작하지 않는다).
 */

export type SpatialWorkspaceCapturePrecision = "EXACT_INTERVAL" | "DATE_ONLY" | "UNKNOWN";

export interface SpatialWorkspaceCapture {
  factClass: "DECLARED_CAPTURE";
  precision: string;
  captureStartedAt: string | null;
  captureEndedAt: string | null;
  /** DATE_ONLY 달력 날짜(`YYYY-MM-DD`). 없으면 null — 유도하지 않는다. */
  captureDate: string | null;
}

export interface SpatialWorkspaceVersion {
  assetRef: string;
  submissionRef: string;
  revision: number;
  artifactId: string;
  kind: string;
  lifecycleState: "UNSEALED" | "SEALED" | "SUPERSEDED";
  capture: SpatialWorkspaceCapture;
  declaredCrs: string | null;
  declaredVerticalReferencePresent: boolean;
  declaredGsdM: number | null;
  submittedAt: string;
  observedSha256: string | null;
  observedSizeBytes: number | null;
  observedAt: string | null;
  inspectionState: string;
  inspectionOutcome: "MEASURED" | "NOT_APPLICABLE" | "REJECTED" | null;
  inspectionReason: string | null;
  inspectedRasterAvailable: boolean;
  displayState: "SEALED" | "NOT_SEALED" | "NOT_CONFIGURED";
  displayReady: boolean;
  chronology: string;
  chronologyCandidate: boolean;
  quantitativeEligibility: "NOT_EVALUATED";
}

export interface SpatialWorkspaceObservation {
  observationEpochId: string;
  workOrderId: string;
  capture: SpatialWorkspaceCapture;
  captureSourcesAgree: boolean;
  versions: SpatialWorkspaceVersion[];
  viewAvailable: boolean;
  viewUnavailableReason: string | null;
  viewAssetRef: string | null;
  newerRevisionPending: boolean;
  newerRevisionState: string | null;
  chronologyCandidate: boolean;
  hasSealedVersion: boolean;
}

export type SpatialWorkspaceEntryReason =
  | "LATEST_EXACT_VIEW_AVAILABLE"
  | "NO_OBSERVATIONS"
  | "NO_VIEW_AVAILABLE_OBSERVATION"
  | "NO_EXACT_CAPTURE_CANDIDATE"
  | "CAPTURE_TIE_AMBIGUOUS";

export interface SpatialWorkspaceEntryDefault {
  observationEpochId: string | null;
  viewAssetRef: string | null;
  /** 서버가 정한 이유 코드 — 화면은 한국어로 옮기되 코드를 감추지 않는다. */
  reason: SpatialWorkspaceEntryReason;
  /** 서버 설명(영문) — 화면은 펼침에 원문 그대로 둔다. */
  detail: string;
  tiedObservationEpochIds: string[];
}

export interface SpatialWorkspacePage {
  contractVersion: "site-spatial-workspace-page.v1";
  siteId: string;
  workAreaId: string;
  scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY";
  scopeNote: string;
  observations: SpatialWorkspaceObservation[];
  entryDefault: SpatialWorkspaceEntryDefault;
  nextCursor: string | null;
  hasMore: boolean;
}

function workspacePath(siteId: string, workAreaId: string): string {
  return `/v1/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/spatial-workspace-observations`;
}

/**
 * 구역의 관측 프로젝션 한 페이지. `entryDefault`는 Core가 전체 범위에서
 * 계산하므로 페이지가 잘려도 서버 결정을 그대로 쓴다. SITES_READ 세션으로
 * 읽으며, 바이트 권한을 만들지 않는다.
 */
export function listSpatialWorkspaceObservations(
  siteId: string,
  workAreaId: string,
  options: { limit?: number; cursor?: string } = {},
): Promise<SpatialWorkspacePage> {
  return coreFetch<SpatialWorkspacePage>(workspacePath(siteId, workAreaId), {
    query: { limit: options.limit ?? 50, cursor: options.cursor },
  });
}
