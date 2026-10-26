import "server-only";

import { coreFetch } from "./client";

/**
 * 단일 자산의 제작·촬영·격자 출처 판독(V1) — 카탈로그 뒤에 있는
 * 이미 저장된 provenance와 검사 격자 상세만 읽는다. 바이트 저장·
 * 다운로드·분석 판정을 주지 않으며, 없는 사실은 null로 둔다.
 */
export type SpatialAssetProducerKnowledge = "DECLARED" | "PARTIAL" | "UNKNOWN";

export type SpatialAssetProducerProvenance = {
  factClass: "DECLARED";
  producerKnowledge: SpatialAssetProducerKnowledge;
  softwareName: string | null;
  softwareVersion: string | null;
  buildIdentifier: string | null;
  producerRunIdentifier: string | null;
  completedAt: string | null;
  sourceNote: string | null;
};

export type SpatialAssetCaptureProvenance = {
  factClass: "DECLARED";
  captureBasis: "EXACT_INTERVAL" | "DATE_ONLY" | "UNKNOWN";
  captureStartedAt: string | null;
  captureEndedAt: string | null;
  captureDate: string | null;
  rawMediaStoredByKsi: false;
  originalRetentionLocus: "customer_workstation" | "upstream_source" | "unknown";
  originalRetentionDetail: string | null;
  localInputManifestDigest: string | null;
  imageCount: number | null;
};

export type SpatialAssetRasterDetail = {
  factClass: "INSPECTED";
  sourceReportDigest: string;
  inspectorBuildDigest: string;
  bandCount: number;
  dtype: string;
  layout: string;
  nodataRepresentation: "NONE" | "FINITE" | "NAN" | "MASK";
  nodataValue: number | null;
  validPixelCount: number;
  horizontalUnits: string | null;
};

export type SpatialAssetDescription = {
  contractVersion: "spatial-asset-description.v1";
  assetRef: string;
  siteId: string;
  workAreaId: string;
  producer: SpatialAssetProducerProvenance;
  capture: SpatialAssetCaptureProvenance;
  raster: SpatialAssetRasterDetail | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isProducer(value: unknown): value is SpatialAssetProducerProvenance {
  if (!isRecord(value)) return false;
  return value.factClass === "DECLARED"
    && (value.producerKnowledge === "DECLARED" || value.producerKnowledge === "PARTIAL" || value.producerKnowledge === "UNKNOWN")
    && (value.softwareName === null || typeof value.softwareName === "string")
    && (value.softwareVersion === null || typeof value.softwareVersion === "string")
    && (value.buildIdentifier === null || typeof value.buildIdentifier === "string")
    && (value.producerRunIdentifier === null || typeof value.producerRunIdentifier === "string")
    && (value.completedAt === null || typeof value.completedAt === "string")
    && (value.sourceNote === null || typeof value.sourceNote === "string");
}

function isCapture(value: unknown): value is SpatialAssetCaptureProvenance {
  if (!isRecord(value)) return false;
  return value.factClass === "DECLARED"
    && (value.captureBasis === "EXACT_INTERVAL" || value.captureBasis === "DATE_ONLY" || value.captureBasis === "UNKNOWN")
    && (value.captureStartedAt === null || typeof value.captureStartedAt === "string")
    && (value.captureEndedAt === null || typeof value.captureEndedAt === "string")
    && (value.captureDate === null || typeof value.captureDate === "string")
    && value.rawMediaStoredByKsi === false
    && (value.originalRetentionLocus === "customer_workstation" || value.originalRetentionLocus === "upstream_source" || value.originalRetentionLocus === "unknown")
    && (value.originalRetentionDetail === null || typeof value.originalRetentionDetail === "string")
    && (value.localInputManifestDigest === null || typeof value.localInputManifestDigest === "string")
    && (value.imageCount === null || typeof value.imageCount === "number");
}

function isRaster(value: unknown): value is SpatialAssetRasterDetail {
  if (!isRecord(value)) return false;
  return value.factClass === "INSPECTED"
    && typeof value.sourceReportDigest === "string"
    && typeof value.inspectorBuildDigest === "string"
    && typeof value.bandCount === "number"
    && typeof value.dtype === "string"
    && typeof value.layout === "string"
    && (value.nodataRepresentation === "NONE" || value.nodataRepresentation === "FINITE" || value.nodataRepresentation === "NAN" || value.nodataRepresentation === "MASK")
    && (value.nodataValue === null || typeof value.nodataValue === "number")
    && typeof value.validPixelCount === "number"
    && (value.horizontalUnits === null || typeof value.horizontalUnits === "string");
}

function isDescription(value: unknown): value is SpatialAssetDescription {
  if (!isRecord(value)) return false;
  return value.contractVersion === "spatial-asset-description.v1"
    && typeof value.assetRef === "string"
    && typeof value.siteId === "string"
    && typeof value.workAreaId === "string"
    && isProducer(value.producer)
    && isCapture(value.capture)
    && (value.raster === null || isRaster(value.raster));
}

/** Metadata only. Core scope check failures surface as 404/403 through the shared handler. */
export async function getSpatialAssetDescription(
  siteId: string,
  workAreaId: string,
  assetRef: string,
): Promise<SpatialAssetDescription> {
  const view = await coreFetch<unknown>(
    `/v2/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/spatial-assets/${encodeURIComponent(assetRef)}`,
  );
  // 요청한 참조와 같은 자료의 판독일 때만 돌려준다 — 다른 자료의 출처를
  // 이 자리에 내놓지 않는다.
  if (!isDescription(view) || view.assetRef !== assetRef || view.siteId !== siteId || view.workAreaId !== workAreaId) {
    throw new Error("자료 출처 판독 응답 형식을 확인할 수 없습니다.");
  }
  return view;
}
