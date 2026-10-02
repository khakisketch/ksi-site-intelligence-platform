import "server-only";

import { coreFetch } from "./client";

export type SpatialAssetKind =
  | "point_cloud"
  | "camera_poses"
  | "ortho"
  | "dsm"
  | "dtm"
  | "mesh"
  | "tiles_3d"
  | "report";

export interface SpatialAssetDeclaredFacts {
  factClass: "DECLARED";
  fileName: string;
  format: string;
  contentType: string;
  sha256: string;
  sizeBytes: number;
  crs: string | null;
  verticalReference: { datum: string; basis: string; source: "USER_DECLARED" } | null;
  gsdM: number | null;
  submittedAt: string;
  producerCompletedAt: string | null;
  captureStartedAt: string | null;
  captureEndedAt: string | null;
}

export interface SpatialAssetObservedFacts {
  factClass: "OBSERVED";
  manifestDigest: string;
  observedAt: string;
  sha256: string;
  sizeBytes: number;
  contentType: string;
}

export interface SpatialAssetInspectedRasterFacts {
  factClass: "INSPECTED";
  sourceReportDigest: string;
  inspectorBuildDigest: string;
  observedCrsIdentifier: string;
  observedCrsWkt: string | null;
  observedCrsDigest: string;
  observedVerticalReference: { identifier: string; basis: string } | null;
  transform: [number, number, number, number, number, number];
  footprintWkt: string;
  footprintDigest: string;
  width: number;
  height: number;
}

export interface SpatialAssetInspection {
  state: string;
  reportDigest: string | null;
  outcome: "MEASURED" | "NOT_APPLICABLE" | "REJECTED" | null;
  reason: string | null;
  inspectorBuildDigest: string | null;
  raster: SpatialAssetInspectedRasterFacts | null;
}

export interface SpatialAssetCatalogItem {
  assetRef: string;
  siteId: string;
  workAreaId: string;
  workOrderId: string;
  observationEpochId: string;
  submissionRef: string;
  revision: number;
  artifactId: string;
  kind: SpatialAssetKind;
  lifecycleState: "UNSEALED" | "SEALED" | "SUPERSEDED";
  declared: SpatialAssetDeclaredFacts;
  observed: SpatialAssetObservedFacts | null;
  inspection: SpatialAssetInspection;
  dataAccess: "NOT_AVAILABLE_FROM_CATALOG";
  analysisStatus: "NOT_EVALUATED";
  supportedActions: ["VIEW_METADATA"];
}

export interface SpatialAssetCatalogPage {
  contractVersion: "spatial-asset-catalog-page.v1";
  siteId: string;
  workAreaId: string;
  scopePolicy: "SINGLE_WORK_AREA_WORK_ORDERS_ONLY";
  scopeNote: string;
  assets: SpatialAssetCatalogItem[];
  nextCursor: string | null;
  hasMore: boolean;
}

export type SpatialAssetCatalogDetail = SpatialAssetCatalogItem;

function catalogPath(siteId: string, workAreaId: string): string {
  return `/v1/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/spatial-assets`;
}

/** Metadata only. Every page and detail lookup goes through Core's current scope check. */
export function listSpatialAssets(
  siteId: string,
  workAreaId: string,
  options: { limit: 50; cursor?: string },
): Promise<SpatialAssetCatalogPage> {
  return coreFetch<SpatialAssetCatalogPage>(catalogPath(siteId, workAreaId), {
    query: { limit: options.limit, cursor: options.cursor },
  });
}

/** Fetch an exact opaque catalog ref; it grants no access to artifact bytes. */
export function getSpatialAsset(
  siteId: string,
  workAreaId: string,
  assetRef: string,
): Promise<SpatialAssetCatalogDetail> {
  return coreFetch<SpatialAssetCatalogDetail>(`${catalogPath(siteId, workAreaId)}/${encodeURIComponent(assetRef)}`);
}
