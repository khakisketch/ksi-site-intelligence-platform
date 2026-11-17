/**
 * 측정 선·단면 계약의 화면용 타입과 방어적 가드.
 *
 * 원본은 `contracts/schemas/measurement-feature.v1.json`, `surface-profile.v1.json`,
 * `surface-profile-job.v1.json`이다. 이 파일은 계약을 대체하지 않으며, 화면이 쓰는 모양만
 * 손으로 옮기고 형식이 어긋난 응답은 표시하지 않는다(INV-040: 가짜 값 대신 정직한 불가).
 * `server-only`가 아니므로 서버·클라이언트 양쪽이 import한다.
 */

export const SAMPLE_INVALID_REASONS = ["OUTSIDE_SURFACE", "INSUFFICIENT_NEIGHBORS", "NODATA"] as const;
export type SampleInvalidReason = (typeof SAMPLE_INVALID_REASONS)[number];

export interface ProfileSample {
  index: number;
  /** 선 시작점(A)에서 선을 따라 잰 평면 거리(m). */
  distanceM: number;
  x: number;
  y: number;
  /** 읽을 수 없는 지점은 null이며, 이유가 항상 함께 있다. 0이나 이웃 값으로 채우지 않는다. */
  elevationM: number | null;
  invalidReason: SampleInvalidReason | null;
}

export interface MeasurementLine {
  crs: string;
  vertices: [number, number][];
}

export interface MeasurementFeatureRef {
  featureId: string;
  revision: number;
  lineDigest: string;
}

export interface MeasurementFeatureRevision {
  featureId: string;
  siteId: string;
  workAreaId: string;
  revision: number;
  name: string;
  kind: "LINE";
  line: MeasurementLine;
  lineDigest: string;
  createdAt: string;
}

export interface MeasurementFeatureList {
  features: MeasurementFeatureRevision[];
}

export const PROFILE_EXECUTION_STATES = ["QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELED", "EXPIRED"] as const;
export type ProfileExecutionState = (typeof PROFILE_EXECUTION_STATES)[number];

export const PROFILE_AVAILABILITIES = [
  "NOT_READY",
  "AVAILABLE",
  "ACCESS_REVOKED",
  "ACCESS_EXPIRED",
  "RETENTION_EXPIRED",
  "UNAVAILABLE",
] as const;
export type ProfileAvailability = (typeof PROFILE_AVAILABILITIES)[number];

export interface SurfaceProfileJobView {
  jobId: string;
  assetRef: string;
  siteId: string;
  workAreaId: string;
  feature: MeasurementFeatureRef;
  createdAt: string;
  executionState: ProfileExecutionState;
  availability: ProfileAvailability;
  reason: string | null;
}

export interface SurfaceProfileJobPage {
  items: SurfaceProfileJobView[];
}

export interface SurfaceProfileResult {
  assetRef: string;
  lineDigest: string;
  feature: MeasurementFeatureRef | null;
  horizontalCrs: string;
  lineLengthM: number;
  sampleSpacingM: number;
  samples: ProfileSample[];
  validCount: number;
  unknownCount: number;
  minimumM: number | null;
  maximumM: number | null;
}

export interface SurfaceProfileResultView {
  job: SurfaceProfileJobView;
  result: SurfaceProfileResult;
}

export const JOB_ID_PATTERN = /^spj-[0-9a-f]{32}$/;
export const FEATURE_ID_PATTERN = /^mf-[0-9a-f]{32}$/;
export const ASSET_REF_PATTERN = /^ksa-v1-[0-9a-f]{64}$/;
const DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;
const CRS_PATTERN = /^EPSG:[1-9][0-9]{0,5}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function isFeatureRef(value: unknown): value is MeasurementFeatureRef {
  return isRecord(value)
    && typeof value.featureId === "string" && FEATURE_ID_PATTERN.test(value.featureId)
    && Number.isSafeInteger(value.revision) && (value.revision as number) >= 1
    && typeof value.lineDigest === "string" && DIGEST_PATTERN.test(value.lineDigest);
}

function isLine(value: unknown): value is MeasurementLine {
  return isRecord(value)
    && typeof value.crs === "string" && CRS_PATTERN.test(value.crs)
    && Array.isArray(value.vertices) && value.vertices.length >= 2 && value.vertices.length <= 256
    && value.vertices.every((vertex) => Array.isArray(vertex) && vertex.length === 2 && vertex.every(isFiniteNumber));
}

export function isFeatureRevision(value: unknown): value is MeasurementFeatureRevision {
  return isRecord(value)
    && typeof value.featureId === "string" && FEATURE_ID_PATTERN.test(value.featureId)
    && typeof value.siteId === "string" && typeof value.workAreaId === "string"
    && Number.isSafeInteger(value.revision) && (value.revision as number) >= 1
    && typeof value.name === "string" && value.name.length > 0
    && value.kind === "LINE"
    && isLine(value.line)
    && typeof value.lineDigest === "string" && DIGEST_PATTERN.test(value.lineDigest)
    && typeof value.createdAt === "string";
}

export function isFeatureList(value: unknown): value is MeasurementFeatureList {
  return isRecord(value) && Array.isArray(value.features) && value.features.every(isFeatureRevision);
}

export function isJobView(value: unknown): value is SurfaceProfileJobView {
  return isRecord(value)
    && typeof value.jobId === "string" && JOB_ID_PATTERN.test(value.jobId)
    && typeof value.assetRef === "string" && ASSET_REF_PATTERN.test(value.assetRef)
    && typeof value.siteId === "string" && typeof value.workAreaId === "string"
    && isFeatureRef(value.feature)
    && typeof value.createdAt === "string"
    && (PROFILE_EXECUTION_STATES as readonly unknown[]).includes(value.executionState)
    && (PROFILE_AVAILABILITIES as readonly unknown[]).includes(value.availability)
    && (value.reason === undefined || value.reason === null || typeof value.reason === "string");
}

export function isJobPage(value: unknown): value is SurfaceProfileJobPage {
  return isRecord(value) && Array.isArray(value.items) && value.items.every(isJobView);
}

function isSample(value: unknown): value is ProfileSample {
  if (!isRecord(value)) return false;
  if (!Number.isSafeInteger(value.index) || (value.index as number) < 0) return false;
  if (!isFiniteNumber(value.distanceM) || value.distanceM < 0) return false;
  if (!isFiniteNumber(value.x) || !isFiniteNumber(value.y)) return false;
  const hasHeight = value.elevationM !== null && value.elevationM !== undefined;
  const hasReason = value.invalidReason !== null && value.invalidReason !== undefined;
  // 높이와 이유 중 정확히 하나만 있다. 둘 다 있거나 둘 다 없으면 계약 위반이다.
  if (hasHeight === hasReason) return false;
  if (hasHeight) return isFiniteNumber(value.elevationM);
  return (SAMPLE_INVALID_REASONS as readonly unknown[]).includes(value.invalidReason);
}

export function isProfileResult(value: unknown): value is SurfaceProfileResult {
  if (!isRecord(value)) return false;
  if (typeof value.assetRef !== "string" || !ASSET_REF_PATTERN.test(value.assetRef)) return false;
  if (typeof value.lineDigest !== "string" || !DIGEST_PATTERN.test(value.lineDigest)) return false;
  if (value.feature !== null && value.feature !== undefined && !isFeatureRef(value.feature)) return false;
  if (typeof value.horizontalCrs !== "string" || !CRS_PATTERN.test(value.horizontalCrs)) return false;
  if (!isFiniteNumber(value.lineLengthM) || value.lineLengthM <= 0) return false;
  if (!isFiniteNumber(value.sampleSpacingM) || value.sampleSpacingM <= 0) return false;
  const samples = value.samples;
  if (!Array.isArray(samples) || samples.length < 2 || samples.length > 5000 || !samples.every(isSample)) return false;
  const rows = samples as ProfileSample[];
  // 지점 번호는 0부터 이어지고, 거리는 0에서 시작해 엄격히 늘어난다.
  if (rows.some((row, position) => row.index !== position)) return false;
  if (rows[0]!.distanceM !== 0) return false;
  for (let position = 1; position < rows.length; position += 1) {
    if (!(rows[position]!.distanceM > rows[position - 1]!.distanceM)) return false;
  }
  const known = rows.filter((row) => row.elevationM !== null).length;
  if (value.validCount !== known || value.unknownCount !== rows.length - known) return false;
  return true;
}

export function isProfileResultView(value: unknown): value is SurfaceProfileResultView {
  return isRecord(value) && isJobView(value.job) && isProfileResult(value.result);
}
