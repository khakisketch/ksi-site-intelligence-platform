import "server-only";

import { CoreApiError } from "./client";
import { coreApiBaseUrl } from "./env";
import { getSessionToken } from "./session";

/**
 * 분리된 차분 파일(delta-publication) 전용 Core 호출층이다.
 *
 * 고정 V2 수치 결과 클라이언트(`analysis.ts`)와는 별개이며, 수치 계산·적합성
 * 판정을 절대 건드리지 않는다. Core가 닫힌 계약으로 확정한 세 값(계산 신원·수치
 * 결과 신원·범위 근거 확인값)만을 출처로 보내고, 격자·좌표·바이트는 Core의
 * 신뢰 증언에서만 온다. 화면이 커버리지 해시나 격자를 지어내지 못하도록,
 * 이 모듈은 요청에 격자 필드를 싣지 않고 응답의 출처 메아리만 검증한다.
 */

/** Core 바이트 슬라이스 상한(서버 계약 `_MAX_SLICE`와 동일). */
export const DELTA_MAX_CHUNK_BYTES = 1024 * 1024;

/** 차분 파일 BFF 요청 본문 상한 — 세 확인값+식별자+수명만 오가므로 작게 둔다. */
export const DELTA_MAX_REQUEST_BODY_BYTES = 16_384;

/** BFF가 Core에서 받아들이는 JSON 응답 상한(base64 청크 + 외피 여유). */
export const DELTA_MAX_RESPONSE_JSON_BYTES = 2_097_152;

/** base64 청크 계약 상한(`DeltaPublicationBytesV1.contentBase64`와 동일). */
export const DELTA_MAX_BASE64_LENGTH = 1_398_104;

/** Core 업스트림 호출 제한 — 이 시간을 넘기면 503으로 닫는다. */
export const DELTA_UPSTREAM_TIMEOUT_MS = 20_000;

const digestPattern = /^sha256:[0-9a-f]{64}$/;
const opaqueIdPattern = /^[A-Za-z0-9_-]{1,128}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function isDigest(value: unknown): value is string {
  return typeof value === "string" && digestPattern.test(value);
}

/**
 * 불투명 식별자 — 경로·URL·권한이 될 수 없다. Core 저장소의 판정과 같은
 * 기준으로 BFF 진입점에서 먼저 거른다(스킴·상위경로·개행 거부).
 */
export function isOpaquePublicationId(value: unknown): value is string {
  if (typeof value !== "string" || opaqueIdPattern.test(value) !== true) return false;
  const lowered = value.toLowerCase();
  return !(
    value.includes("://")
    || value.startsWith("/")
    || value.startsWith("\\")
    || value.includes("..")
    || value.includes("\\")
    || value.includes("\n")
    || value.includes("\r")
    || lowered.startsWith("http:")
    || lowered.startsWith("https:")
    || lowered.startsWith("s3:")
    || lowered.startsWith("file:")
    || lowered.startsWith("cap:")
  );
}

export function isScopeId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 255;
}

/**
 * 서버가 발행한 수명 설정값 그대로만 받는다. 상한은 Core 정책이 409로
 * 판정하므로 BFF가 독자 상한을 지어내지 않는다.
 */
export function isDeltaLifetimeSeconds(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

export type DeltaPublicationSource = {
  sourceCalculationIdentityDigest: string;
  sourceNumericResultIdentityDigest: string;
  sourceCoverageWitnessDigest: string;
};

export type DeltaPublicationRequest = DeltaPublicationSource & {
  publicationId: string;
  lifetimeSeconds: number;
};

/** Core `Status` 리터럴 — 의도·상세 공용. */
export const DELTA_STATUSES = ["PENDING", "PUBLISHED", "REVOKED", "CANCELED", "FAILED"] as const;
export type DeltaPublicationStatus = (typeof DELTA_STATUSES)[number];

/** Core가 허용하는 출처 계약 버전 — V2 수치 보고 또는 V3 마스크 신원. */
export const DELTA_SOURCE_CONTRACT_VERSIONS = [
  "external-relative-volume-calculation-report.v2",
  "external-masked-volume-calculation-identity.v3",
] as const;

export type DeltaPublicationIntent = {
  publicationId: string;
  organizationId: string;
  siteId: string;
  workAreaId: string;
  sourceContractVersion: (typeof DELTA_SOURCE_CONTRACT_VERSIONS)[number];
  outputId: string;
  uploadFenceId: string;
  sourceCalculationIdentityDigest: string;
  sourceNumericResultIdentityDigest: string;
  sourceCoverageWitnessDigest: string;
  gridRows: number;
  gridColumns: number;
  issuedAt: string;
  expiresAt: string;
  policyDigest: string;
  status: DeltaPublicationStatus;
  leaseGeneration: number;
  leaseHolderPrincipalId: string | null;
  leaseHolderInstanceId: string | null;
  leaseIssuedAt: string | null;
  leaseExpiresAt: string | null;
};

export type DeltaPublicationDescriptor = {
  publicationId: string;
  organizationId: string;
  siteId: string;
  workAreaId: string;
  sourceContractVersion: (typeof DELTA_SOURCE_CONTRACT_VERSIONS)[number];
  sourceCalculationIdentityDigest: string;
  sourceNumericResultIdentityDigest: string;
  sourceCoverageWitnessDigest: string;
  deltaSign: "CURRENT_MINUS_BASELINE";
  gridRows: number;
  gridColumns: number;
  transform: [number, number, number, number, number, number];
  transformDigest: string;
  gridCrsIdentifier: string;
  gridCrsDigest: string;
  bounds: [number, number, number, number];
  verticalUnit: "metre";
  dtype: "FLOAT64";
  outputId: string;
  outputSha256: string;
  outputSizeBytes: number;
  issuedAt: string;
  expiresAt: string;
  publicationPolicyDigest: string;
  publicationDigest: string | null;
};

export type DeltaPublicationDetail = {
  publicationId: string;
  organizationId: string;
  siteId: string;
  workAreaId: string;
  outputId: string;
  issuedAt: string;
  expiresAt: string;
  policyDigest: string;
  status: DeltaPublicationStatus;
  reason: string | null;
  descriptor: DeltaPublicationDescriptor;
};

export type DeltaPublicationBytes = {
  publicationId: string;
  offset: number;
  contentBase64: string;
};

/** BFF 진입점 입력 결함 — 400으로 닫는다. Core 호출 전에만 쓴다. */
export class DeltaPublicationRequestError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DeltaPublicationRequestError";
  }
}

/** 업스트림 시간 초과 — 503으로 닫는다. 수치 실패로 표현하지 않는다. */
export class DeltaUpstreamTimeoutError extends Error {
  constructor() {
    super("차분 파일 서버의 응답이 지연됩니다.");
    this.name = "DeltaUpstreamTimeoutError";
  }
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.length && expected.every((key) => Object.hasOwn(value, key));
}

function isPositiveInt(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

const requestKeys = [
  "publicationId",
  "sourceCalculationIdentityDigest",
  "sourceNumericResultIdentityDigest",
  "sourceCoverageWitnessDigest",
  "lifetimeSeconds",
] as const;

/**
 * BFF가 Core에 보내기 전, 정확히 세 출처 확인값+불투명 식별자+수명만
 * 허용한다. 격자·좌표·크기·정책·권한 필드는 어떤 경로로도 실을 수 없다.
 */
export function parseDeltaPublicationRequest(body: unknown): DeltaPublicationRequest {
  if (!isRecord(body) || !hasExactKeys(body, requestKeys)) {
    throw new DeltaPublicationRequestError("차분 파일 요청 형식이 올바르지 않습니다.");
  }
  if (!isOpaquePublicationId(body.publicationId)) {
    throw new DeltaPublicationRequestError("차분 파일 식별자 형식이 올바르지 않습니다.");
  }
  const source: DeltaPublicationSource = {
    sourceCalculationIdentityDigest: "",
    sourceNumericResultIdentityDigest: "",
    sourceCoverageWitnessDigest: "",
  };
  for (const key of [
    "sourceCalculationIdentityDigest",
    "sourceNumericResultIdentityDigest",
    "sourceCoverageWitnessDigest",
  ] as const) {
    if (!isDigest(body[key])) {
      throw new DeltaPublicationRequestError("출처 확인값 형식이 올바르지 않습니다.");
    }
    source[key] = body[key];
  }
  if (!isDeltaLifetimeSeconds(body.lifetimeSeconds)) {
    throw new DeltaPublicationRequestError("유효 기한 형식이 올바르지 않습니다.");
  }
  return { ...source, publicationId: body.publicationId, lifetimeSeconds: body.lifetimeSeconds };
}

function isSourceEcho(value: Record<string, unknown>): value is Record<string, unknown> & DeltaPublicationSource {
  return isDigest(value.sourceCalculationIdentityDigest)
    && isDigest(value.sourceNumericResultIdentityDigest)
    && isDigest(value.sourceCoverageWitnessDigest);
}

function isStatusLiteral(value: unknown): value is DeltaPublicationStatus {
  return typeof value === "string" && (DELTA_STATUSES as readonly string[]).includes(value);
}

function isSourceContractVersion(
  value: unknown,
): value is (typeof DELTA_SOURCE_CONTRACT_VERSIONS)[number] {
  return typeof value === "string" && (DELTA_SOURCE_CONTRACT_VERSIONS as readonly string[]).includes(value);
}

function isTextId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 255;
}

/** Core `_require_utc`와 같은 기준 — 파싱 가능하고 UTC 오프셋을 명시한 시각만 받는다. */
function isUtcIsoDateTime(value: unknown): value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > 64) return false;
  if (Number.isNaN(Date.parse(value))) return false;
  return /(Z|[+-]00:?(00)?)$/.test(value.trim());
}

function isFiniteFloatArray(value: unknown, length: number): value is number[] {
  return Array.isArray(value)
    && value.length === length
    && value.every((item) => typeof item === "number" && Number.isFinite(item));
}

/**
 * 서술자 격자의 유한·정합성 — Core `DeltaRasterPublicationV1`이 강제하는 것과
 * 같은 조건이다. 바이트를 읽거나 격자를 연산하지 않고, 서술자가 적어 낸
 * 여섯 수·네 경계·행열이 서로 맞물리는지만 본다.
 */
function isConsistentNativeGrid(value: {
  transform: unknown;
  bounds: unknown;
  gridRows: unknown;
  gridColumns: unknown;
}): boolean {
  if (
    !isFiniteFloatArray(value.transform, 6)
    || !isFiniteFloatArray(value.bounds, 4)
    || !isPositiveInt(value.gridRows)
    || !isPositiveInt(value.gridColumns)
  ) {
    return false;
  }
  const [a, b, c, d, e, f] = value.transform as [number, number, number, number, number, number];
  const [left, bottom, right, top] = value.bounds as [number, number, number, number];
  if (b !== 0 || d !== 0 || !(a > 0) || !(e < 0)) return false;
  if (!(left < right && bottom < top)) return false;
  const expected: [number, number, number, number] = [c, f + e * value.gridRows, c + a * value.gridColumns, f];
  const actual: [number, number, number, number] = [left, bottom, right, top];
  return actual.every((item, index) => {
    const want = expected[index]!;
    return Math.abs(item - want) <= Math.max(1e-12 * Math.max(Math.abs(item), Math.abs(want)), 1e-12);
  });
}

function isOrderedInterval(issuedAt: string, expiresAt: string): boolean {
  return Date.parse(expiresAt) > Date.parse(issuedAt);
}

const intentKeys = [
  "publicationId",
  "organizationId",
  "siteId",
  "workAreaId",
  "sourceContractVersion",
  "outputId",
  "uploadFenceId",
  "sourceCalculationIdentityDigest",
  "sourceNumericResultIdentityDigest",
  "sourceCoverageWitnessDigest",
  "gridRows",
  "gridColumns",
  "issuedAt",
  "expiresAt",
  "policyDigest",
  "status",
  "leaseGeneration",
  "leaseHolderPrincipalId",
  "leaseHolderInstanceId",
  "leaseIssuedAt",
  "leaseExpiresAt",
] as const;

function isNullableTextId(value: unknown): value is string | null {
  return value === null || isTextId(value);
}

function isNullableUtc(value: unknown): value is string | null {
  return value === null || isUtcIsoDateTime(value);
}

function isIntentShape(value: unknown): value is DeltaPublicationIntent {
  if (!isRecord(value) || !hasExactKeys(value, intentKeys) || !isSourceEcho(value)) return false;
  if (
    !isOpaquePublicationId(value.publicationId)
    || !isTextId(value.organizationId)
    || !isScopeId(value.siteId)
    || !isScopeId(value.workAreaId)
    || !isSourceContractVersion(value.sourceContractVersion)
    || !isTextId(value.outputId)
    || !isTextId(value.uploadFenceId)
    || !isPositiveInt(value.gridRows)
    || !isPositiveInt(value.gridColumns)
    || !isUtcIsoDateTime(value.issuedAt)
    || !isUtcIsoDateTime(value.expiresAt)
    || !isOrderedInterval(value.issuedAt, value.expiresAt)
    || !isDigest(value.policyDigest)
    || !isStatusLiteral(value.status)
    || typeof value.leaseGeneration !== "number" || !Number.isSafeInteger(value.leaseGeneration)
    || value.leaseGeneration < 0
    || !isNullableTextId(value.leaseHolderPrincipalId)
    || !isNullableTextId(value.leaseHolderInstanceId)
    || !isNullableUtc(value.leaseIssuedAt)
    || !isNullableUtc(value.leaseExpiresAt)
  ) {
    return false;
  }
  return true;
}

const descriptorKeys = [
  "contractVersion",
  "publicationId",
  "organizationId",
  "siteId",
  "workAreaId",
  "sourceContractVersion",
  "sourceCalculationIdentityDigest",
  "sourceNumericResultIdentityDigest",
  "sourceCoverageWitnessDigest",
  "deltaSign",
  "gridRows",
  "gridColumns",
  "transform",
  "transformDigest",
  "gridCrsIdentifier",
  "gridCrsDigest",
  "bounds",
  "verticalUnit",
  "dtype",
  "outputId",
  "outputSha256",
  "outputSizeBytes",
  "issuedAt",
  "expiresAt",
  "publicationPolicyDigest",
  "publicationDigest",
] as const;

function isDescriptorShape(value: unknown): value is DeltaPublicationDescriptor {
  if (!isRecord(value) || !hasExactKeys(value, descriptorKeys) || !isSourceEcho(value)) return false;
  if (
    value.contractVersion !== "external-masked-volume-delta-publication.v1"
    || !isOpaquePublicationId(value.publicationId)
    || !isTextId(value.organizationId)
    || !isScopeId(value.siteId)
    || !isScopeId(value.workAreaId)
    || !isSourceContractVersion(value.sourceContractVersion)
    || value.deltaSign !== "CURRENT_MINUS_BASELINE"
    || !isPositiveInt(value.gridRows)
    || !isPositiveInt(value.gridColumns)
    || !isConsistentNativeGrid({ transform: value.transform, bounds: value.bounds, gridRows: value.gridRows, gridColumns: value.gridColumns })
    || !isDigest(value.transformDigest)
    || !isTextId(value.gridCrsIdentifier)
    || !isDigest(value.gridCrsDigest)
    || value.verticalUnit !== "metre"
    || value.dtype !== "FLOAT64"
    || !isTextId(value.outputId)
    || !isDigest(value.outputSha256)
    || !isPositiveInt(value.outputSizeBytes)
    || !isUtcIsoDateTime(value.issuedAt)
    || !isUtcIsoDateTime(value.expiresAt)
    || !isOrderedInterval(value.issuedAt, value.expiresAt)
    || !isDigest(value.publicationPolicyDigest)
    || !(value.publicationDigest === null || isDigest(value.publicationDigest))
  ) {
    return false;
  }
  return true;
}

const detailKeys = [
  "publicationId",
  "organizationId",
  "siteId",
  "workAreaId",
  "outputId",
  "issuedAt",
  "expiresAt",
  "policyDigest",
  "status",
  "reason",
  "descriptor",
] as const;

function isDetailShape(value: unknown): value is DeltaPublicationDetail {
  if (!isRecord(value) || !hasExactKeys(value, detailKeys)) return false;
  if (
    !isOpaquePublicationId(value.publicationId)
    || !isTextId(value.organizationId)
    || !isScopeId(value.siteId)
    || !isScopeId(value.workAreaId)
    || !isTextId(value.outputId)
    || !isUtcIsoDateTime(value.issuedAt)
    || !isUtcIsoDateTime(value.expiresAt)
    || !isOrderedInterval(value.issuedAt, value.expiresAt)
    || !isDigest(value.policyDigest)
    || !isStatusLiteral(value.status)
    || !(value.reason === null || (typeof value.reason === "string" && value.reason.length <= 255))
    || !isDescriptorShape(value.descriptor)
  ) {
    return false;
  }
  // 최상위와 서술자는 같은 기록의 같은 발행이어야 한다 — 조직·범위·식별자·
  // 출력물·정책·발행 시각이 하나라도 어긋나면 모르는 응답으로 버린다.
  const descriptor = value.descriptor;
  return descriptor.organizationId === value.organizationId
    && descriptor.siteId === value.siteId
    && descriptor.workAreaId === value.workAreaId
    && descriptor.publicationId === value.publicationId
    && descriptor.outputId === value.outputId
    && descriptor.issuedAt === value.issuedAt
    && descriptor.expiresAt === value.expiresAt
    && descriptor.publicationPolicyDigest === value.policyDigest;
}

/**
 * Core 응답의 범위·출처 메아리를 닫힌 형태로 검증한다. 현장·구역·식별자·
 * 세 출처 확인값 중 하나라도 요청과 다르면 모르는 응답으로 버린다.
 * 수치 상태는 이 판정에 관여하지 않는다.
 */
export function parseDeltaPublicationIntent(
  value: unknown,
  scope: { siteId: string; workAreaId: string; publicationId: string; source: DeltaPublicationSource },
): DeltaPublicationIntent {
  if (!isIntentShape(value)) {
    throw new Error("차분 파일 응답 형식을 확인할 수 없습니다.");
  }
  if (
    value.siteId !== scope.siteId
    || value.workAreaId !== scope.workAreaId
    || value.publicationId !== scope.publicationId
    || value.sourceCalculationIdentityDigest !== scope.source.sourceCalculationIdentityDigest
    || value.sourceNumericResultIdentityDigest !== scope.source.sourceNumericResultIdentityDigest
    || value.sourceCoverageWitnessDigest !== scope.source.sourceCoverageWitnessDigest
  ) {
    throw new Error("차분 파일 응답의 요청 범위를 확인할 수 없습니다.");
  }
  return value;
}

export function parseDeltaPublicationDetail(
  value: unknown,
  scope: { siteId: string; workAreaId: string; publicationId: string; source: DeltaPublicationSource },
): DeltaPublicationDetail {
  if (!isDetailShape(value)) {
    throw new Error("차분 파일 응답 형식을 확인할 수 없습니다.");
  }
  if (
    value.siteId !== scope.siteId
    || value.workAreaId !== scope.workAreaId
    || value.publicationId !== scope.publicationId
    || value.descriptor.siteId !== scope.siteId
    || value.descriptor.workAreaId !== scope.workAreaId
    || value.descriptor.publicationId !== scope.publicationId
    || value.descriptor.sourceCalculationIdentityDigest !== scope.source.sourceCalculationIdentityDigest
    || value.descriptor.sourceNumericResultIdentityDigest !== scope.source.sourceNumericResultIdentityDigest
    || value.descriptor.sourceCoverageWitnessDigest !== scope.source.sourceCoverageWitnessDigest
  ) {
    throw new Error("차분 파일 응답의 요청 범위를 확인할 수 없습니다.");
  }
  return value;
}

const BYTES_KEYS = ["publicationId", "offset", "contentBase64"] as const;

const BASE64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

function base64Value(code: number): number {
  if (code >= 65 && code <= 90) return code - 65;
  if (code >= 97 && code <= 122) return code - 71;
  if (code >= 48 && code <= 57) return code + 4;
  if (code === 43) return 62;
  if (code === 47) return 63;
  return -1;
}

function encodeCanonicalBase64(bytes: Uint8Array): string {
  let out = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i]!;
    const b = i + 1 < bytes.length ? bytes[i + 1]! : 0;
    const c = i + 2 < bytes.length ? bytes[i + 2]! : 0;
    out += BASE64_ALPHABET[a >> 2];
    out += BASE64_ALPHABET[((a & 3) << 4) | (b >> 4)];
    out += i + 1 < bytes.length ? BASE64_ALPHABET[((b & 15) << 2) | (c >> 6)] : "=";
    out += i + 2 < bytes.length ? BASE64_ALPHABET[c & 63] : "=";
  }
  return out;
}

/**
 * 정식(canonical) base64만 복원한다 — 문자 집합·패딩 위치·길이뿐 아니라
 * 패딩 양자의 미사용 비트까지 검증한다. 복원 뒤 정식으로 다시 부호화해
 * 입력과 바이트 단위로 대조하므로, 비정식 패딩 비트는 통과하지 못한다.
 */
export function decodeCanonicalBase64Chunk(input: string): Uint8Array {
  if (
    input.length === 0
    || input.length > DELTA_MAX_BASE64_LENGTH
    || input.length % 4 !== 0
  ) {
    throw new DeltaPublicationRequestError("차분 파일 조각 형식이 올바르지 않습니다.");
  }
  const codes: number[] = [];
  let padding = 0;
  for (let i = 0; i < input.length; i += 1) {
    const code = input.charCodeAt(i);
    if (code === 61) {
      padding += 1;
      codes.push(-1);
      continue;
    }
    if (padding > 0 || base64Value(code) < 0) {
      throw new DeltaPublicationRequestError("차분 파일 조각 형식이 올바르지 않습니다.");
    }
    codes.push(base64Value(code));
  }
  if (padding > 2) {
    throw new DeltaPublicationRequestError("차분 파일 조각 형식이 올바르지 않습니다.");
  }
  const out: number[] = [];
  for (let i = 0; i < codes.length; i += 4) {
    const a = codes[i]!;
    const b = codes[i + 1]!;
    const c = codes[i + 2]!;
    const d = codes[i + 3]!;
    if (a < 0 || b < 0) {
      throw new DeltaPublicationRequestError("차분 파일 조각 형식이 올바르지 않습니다.");
    }
    out.push((a << 2) | (b >> 4));
    if (c >= 0) {
      out.push(((b & 15) << 4) | (c >> 2));
      if (d >= 0) out.push(((c & 3) << 6) | d);
    } else if (d >= 0) {
      throw new DeltaPublicationRequestError("차분 파일 조각 형식이 올바르지 않습니다.");
    }
  }
  const bytes = new Uint8Array(out);
  if (encodeCanonicalBase64(bytes) !== input) {
    throw new DeltaPublicationRequestError("차분 파일 조각 형식이 올바르지 않습니다.");
  }
  return bytes;
}

export function parseDeltaPublicationBytes(
  value: unknown,
  scope: { publicationId: string; offset: number; length: number },
): DeltaPublicationBytes {
  if (!isRecord(value) || !hasExactKeys(value, BYTES_KEYS)) {
    throw new Error("차분 파일 응답 형식을 확인할 수 없습니다.");
  }
  if (
    value.publicationId !== scope.publicationId
    || value.offset !== scope.offset
    || typeof value.contentBase64 !== "string"
  ) {
    throw new Error("차분 파일 응답 형식을 확인할 수 없습니다.");
  }
  const decoded = (() => {
    try {
      return decodeCanonicalBase64Chunk(value.contentBase64);
    } catch {
      // 복원 실패는 Core 응답의 결함이지 브라우저 요청의 결함이 아니다.
      throw new Error("차분 파일 응답 형식을 확인할 수 없습니다.");
    }
  })();
  // 복원 바이트가 요청 길이를 넘으면 잘라 쓰지 않고 버린다 — 조각 경계가
  // 어긋난 응답을 이어 붙이지 않는다.
  if (decoded.length === 0 || decoded.length > scope.length) {
    throw new Error("차분 파일 응답 형식을 확인할 수 없습니다.");
  }
  return { publicationId: value.publicationId, offset: value.offset, contentBase64: value.contentBase64 };
}

export type DeltaAvailability =
  | "PENDING"
  | "AVAILABLE"
  | "EXPIRED"
  | "UNAVAILABLE";

/**
 * 화면 상태 판정의 단일 진실 공급원. 만료가 먼저 이긴다 — 게시된 상세를
 * 들고 있어도 유효 기한이 지났으면 만료됨으로만 본다. 수치 결과 상태는
 * 읽지 않는다.
 *
 * - 만료 시각이 유한하고 현재가 그 이후면 만료됨(상세 유무와 무관).
 * - 상세가 `PUBLISHED`이고 서술자가 있으면 사용 가능.
 * - 상세가 있으나 상태가 다르면(취소·실패·회수 등) 사용 불가.
 * - 상세가 없으면(404) 준비 상태를 확정할 수 없음 — 호출자는 이를
 *   '준비 중'이라 단정하지 않고 만료 시각까지만 다시 확인한다.
 */
export function classifyDeltaAvailability(input: {
  detailStatus: string | null;
  hasDescriptor: boolean;
  expiresAtMs: number | null;
  nowMs: number;
}): DeltaAvailability {
  if (
    input.expiresAtMs !== null
    && Number.isFinite(input.expiresAtMs)
    && input.nowMs >= input.expiresAtMs
  ) {
    return "EXPIRED";
  }
  if (input.detailStatus === "PUBLISHED" && input.hasDescriptor) return "AVAILABLE";
  if (input.detailStatus !== null) return "UNAVAILABLE";
  return "PENDING";
}

function buildCoreUrl(path: string, query?: Record<string, string | number | undefined>): string {
  const url = new URL(path, `${coreApiBaseUrl()}/`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }
  }
  return url.toString();
}

async function readBoundedText(response: Response, maxBytes: number): Promise<string> {
  if (!response.body) return "";
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel().catch(() => undefined);
        throw new Error("차분 파일 서버 응답이 너무 큽니다.");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

function coreErrorFromText(status: number, text: string, contentType: string | null): CoreApiError {
  if (contentType?.includes("application/json") === true && text.length > 0) {
    try {
      return new CoreApiError(status, JSON.parse(text) as unknown);
    } catch {
      return new CoreApiError(status, { detail: text.slice(0, 500) });
    }
  }
  return new CoreApiError(status, text.length > 0 ? { detail: text.slice(0, 500) } : undefined);
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError"
    || error instanceof Error && error.name === "AbortError";
}

async function coreJson<T>(method: "GET" | "POST", path: string, options: {
  query?: Record<string, string | number | undefined>;
  body?: unknown;
  signal?: AbortSignal;
} = {}): Promise<T> {
  if (options.signal?.aborted === true) throw new DeltaUpstreamTimeoutError();
  const token = await getSessionToken();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DELTA_UPSTREAM_TIMEOUT_MS);
  const onAbort = () => controller.abort();
  options.signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const response = await fetch(buildCoreUrl(path, options.query), {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(options.body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
      cache: "no-store",
    });
    const text = await readBoundedText(response, DELTA_MAX_RESPONSE_JSON_BYTES);
    if (!response.ok) {
      throw coreErrorFromText(response.status, text, response.headers.get("content-type"));
    }
    if (text.length === 0) return undefined as T;
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new Error("차분 파일 응답 형식을 확인할 수 없습니다.");
    }
  } catch (error) {
    if (isAbortError(error) || controller.signal.aborted) throw new DeltaUpstreamTimeoutError();
    throw error;
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", onAbort);
  }
}

/**
 * 내보내기 준비 요청 — 출처는 정확히 세 확인값뿐이다. 격자·좌표·바이트·정책을
 * 함께 보내지 않으며, 수치 결과 조회도 하지 않는다.
 */
export async function requestDeltaPublication(
  siteId: string,
  workAreaId: string,
  input: DeltaPublicationRequest,
  options: { signal?: AbortSignal } = {},
): Promise<DeltaPublicationIntent> {
  const path = `/v1/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/delta-publications`;
  const value = await coreJson<unknown>( "POST", path, {
    body: {
      publicationId: input.publicationId,
      sourceCalculationIdentityDigest: input.sourceCalculationIdentityDigest,
      sourceNumericResultIdentityDigest: input.sourceNumericResultIdentityDigest,
      sourceCoverageWitnessDigest: input.sourceCoverageWitnessDigest,
      lifetimeSeconds: input.lifetimeSeconds,
    },
    signal: options.signal,
  });
  return parseDeltaPublicationIntent(value, {
    siteId,
    workAreaId,
    publicationId: input.publicationId,
    source: input,
  });
}

/** 게시된 차분 파일 상세를 읽는다 — 바이트가 아니라 서술자+상태만 온다. */
export async function getDeltaPublication(
  siteId: string,
  workAreaId: string,
  publicationId: string,
  source: DeltaPublicationSource,
  options: { signal?: AbortSignal } = {},
): Promise<DeltaPublicationDetail> {
  const path = `/v1/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/delta-publications/${encodeURIComponent(publicationId)}`;
  const value = await coreJson<unknown>("GET", path, { signal: options.signal });
  return parseDeltaPublicationDetail(value, { siteId, workAreaId, publicationId, source });
}

export function parseDeltaChunkRange(offset: unknown, length: unknown): { offset: number; length: number } {
  if (
    typeof offset !== "number" || !Number.isSafeInteger(offset) || offset < 0
    || typeof length !== "number" || !Number.isSafeInteger(length)
    || length <= 0 || length > DELTA_MAX_CHUNK_BYTES
  ) {
    throw new DeltaPublicationRequestError("차분 파일 조각 요청 범위가 올바르지 않습니다.");
  }
  return { offset, length };
}

/** 1MiB 이하 한 조각을 읽는다 — 브라우저는 이 조각들로만 파일을 조립한다. */
export async function readDeltaPublicationBytes(
  siteId: string,
  workAreaId: string,
  publicationId: string,
  range: { offset: number; length: number },
  options: { signal?: AbortSignal } = {},
): Promise<DeltaPublicationBytes> {
  const path = `/v1/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/delta-publications/${encodeURIComponent(publicationId)}/bytes`;
  const value = await coreJson<unknown>("GET", path, {
    query: { offset: range.offset, length: range.length },
    signal: options.signal,
  });
  return parseDeltaPublicationBytes(value, { publicationId, ...range });
}
