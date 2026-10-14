export const SPATIAL_DATA_EXECUTION_STATES = [
  "QUEUED",
  "RUNNING",
  "COMPLETED",
  "FAILED",
  "CANCELED",
  "EXPIRED",
] as const;

export type SpatialDataExecutionState = (typeof SPATIAL_DATA_EXECUTION_STATES)[number];

export const SPATIAL_DATA_AVAILABILITIES = [
  "NOT_READY",
  "AVAILABLE",
  "ACCESS_REVOKED",
  "ACCESS_EXPIRED",
  "RETENTION_EXPIRED",
  "UNAVAILABLE",
] as const;

export type SpatialDataAvailability = (typeof SPATIAL_DATA_AVAILABILITIES)[number];

export function isSpatialDataExecutionState(value: unknown): value is SpatialDataExecutionState {
  return typeof value === "string" && SPATIAL_DATA_EXECUTION_STATES.some((state) => state === value);
}

export function isSpatialDataAvailability(value: unknown): value is SpatialDataAvailability {
  return typeof value === "string" && SPATIAL_DATA_AVAILABILITIES.some((availability) => availability === value);
}

export type SpatialDataBounds = [number, number, number, number];

/** The displayed subset of Core's immutable SpatialDataReceiptV1. */
export interface SpatialDataReceipt {
  jobId: string;
  receiptDigest?: string | null;
  artifactKind: "dsm" | "ortho";
  outputSizeBytes: number;
  outputSha256: string;
  requestedBounds: SpatialDataBounds;
  actualBounds: SpatialDataBounds;
  pixelWindow: [number, number, number, number];
  width: number;
  height: number;
  observedCrsIdentifier: string;
  observedCrsDigest: string;
  accuracyAssessed: false;
  attribution: string;
  modificationNotice: string;
  limitations: string[];
  preparedAt: string;
}

export interface SpatialDataJobView {
  jobId: string;
  assetRef: string;
  siteId: string;
  workAreaId: string;
  createdAt: string;
  executionState: SpatialDataExecutionState;
  availability: SpatialDataAvailability;
  reason?: string | null;
  remediation?: string[];
  receipt?: SpatialDataReceipt | null;
}

export interface SpatialDataRequestPage {
  items: SpatialDataJobView[];
  nextCursor: string | null;
}
