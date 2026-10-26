/**
 * 독립 마스크 계산(V3) 전용 BFF/화면 공용 계약이다.
 *
 * Core HTTP 계약(`external_masked_api.py`, `external_mask_input_api.py`,
 * `external_masked_calculation_api.py`)의 실제 와이어 모양 그대로만
 * 검증한다. 고정 V2 수치 클라이언트(`analysis.ts`)·차분 파일 클라이언트
 * (`delta-publications.ts`)와는 별개이며, V2 수치·적합성 판정을 절대
 * 건드리지 않는다. 격자·좌표·바이트는 어떤 경로로도 싣지 않는다 —
 * 화면이 격자를 지어내지 못하도록 요청에는 확인값·식별자·봉인 subject·
 * 선언 크기만 허용하고, 응답의 출처 메아리만 검증한다.
 *
 * 이 모듈은 브라우저·서버 공용이다. `server-only`를 걸지 않는다 —
 * `MaskedAnalysisPanel`(클라이언트 컴포넌트)과 BFF Route Handler가
 * 같은 타입·검증을 공유한다. 토큰·세션·Core 호출은 여기에 두지 않는다
 * (`masked-core.ts` — 서버 전용 — 가 얇은 전달을 맡는다).
 *
 * 원본 선택: V3 생성은 `sourceCalculationIdentityDigest`(현재 AP
 * assessment의 봉인 V2 계산 신원 확인값) + `maskChildId`만 받는다.
 * 대시보드는 이 값을 AP 요청 사전확인(`checkAnalysisReadiness` 응답의
 * `calculationIdentityDigest`)에서만 가져온다 — V2 수치 완료·검토
 * 대상이 전제 조건이 아니다(마스크는 값 없는 셀을 제외하므로). 사전확인이
 * 확인값을 주지 않으면 `마스크 입력 연결 전`으로만 둔다.
 * 마스크 바인딩 확인값은 클라이언트가 지어내지 않는다 — Core가
 * `bind_identity`에서 봉인 manifest로부터 직접 만든다.
 */

const digestPattern = /^sha256:[0-9a-f]{64}$/;
const opaqueIdPattern = /^[A-Za-z0-9_-]{1,128}$/;
const submissionRefPattern = /^ers-v1-[0-9a-f]{64}$/;
const reasonPattern = /^[A-Z][A-Z0-9_]{0,127}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function isDigest(value: unknown): value is string {
  return typeof value === "string" && digestPattern.test(value);
}

function isOpaqueId(value: unknown): value is string {
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

function isScopeId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 255;
}

function isBoundedText(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum;
}

function isPositiveInt(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function isNonNegativeInt(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

/**
 * 부호 있는 격자 오프셋 — Core 패딩 윈도우는 음수 오프셋을 쓴다(예: -1).
 * 정수·안전 범위만 본다. 1.5·NaN·문자열은 격자가 아니라서 버린다.
 */
function isSafeInt(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value);
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isNonNegativeFinite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const keys = Object.keys(value);
  return keys.length === expected.length && expected.every((key) => Object.hasOwn(value, key));
}

/** Core UTC 판정과 같은 기준 — 파싱 가능하고 UTC 오프셋을 명시한 시각만 받는다. */
export function isUtcIsoDateTime(value: unknown): value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > 64) return false;
  if (Number.isNaN(Date.parse(value))) return false;
  return /(Z|[+-]00:?(00)?)$/.test(value.trim());
}

/** BFF 진입점 입력 결함 — 400으로 닫는다. Core 호출 전에만 쓴다. */
export class MaskedRequestError extends Error {
  code: string | null = null;
  constructor(message: string) {
    super(message);
    this.name = "MaskedRequestError";
  }
}

/** 대상을 특정할 수 없음 — 404로 닫는다. 모르는·남의 기록을 구분해 알리지 않는다. */
export class MaskedNotFoundError extends Error {
  code: string | null = null;
  constructor(message = "마스크 기록을 찾을 수 없거나 접근할 수 없습니다.") {
    super(message);
    this.name = "MaskedNotFoundError";
  }
}

/** 현재성·펜스 거부 — 409로 닫는다. 수치 실패로 표현하지 않는다. */
export class MaskedConflictError extends Error {
  code: string | null = null;
  constructor(message: string) {
    super(message);
    this.name = "MaskedConflictError";
  }
}

/** 권한·범위 거부 — 403으로 닫는다. 모르는·남의 기록을 구분해 알리지 않는다. */
export class MaskedForbiddenError extends Error {
  code: string | null = null;
  constructor(message = "마스크 기록에 접근할 권한이 없습니다.") {
    super(message);
    this.name = "MaskedForbiddenError";
  }
}

/** 업스트림 시간 초과 — 503으로 닫는다. 수치 실패로 표현하지 않는다. */
export class MaskedUpstreamTimeoutError extends Error {
  code: string | null = null;
  constructor() {
    super("마스크 서버의 응답이 지연됩니다.");
    this.name = "MaskedUpstreamTimeoutError";
  }
}

/** BFF가 돌려준 Core 코드 — 화면은 메시지와 함께 접어 둔다(원문 노출 없음). */export function maskedErrorCode(error: unknown): string | null {
  if (
    error instanceof MaskedRequestError
    || error instanceof MaskedNotFoundError
    || error instanceof MaskedForbiddenError
    || error instanceof MaskedConflictError
    || error instanceof MaskedUpstreamTimeoutError
  ) {
    return error.code;
  }
  return null;
}

/**
 * Core 정규 JSON — `canonical_json_bytes`와 바이트 단위로 같은 규칙이다.
 * 키 정렬·최소 구분자·UTF-8·NaN 거부. subject 등 문자열·정수 페이로드에만
 * 쓰며, 짝 없는 surrogate·비유한 수는 거부한다.
 */
export function canonicalJsonString(value: Record<string, unknown>): string {
  const visit = (node: unknown): unknown => {
    if (node === null || typeof node === "string" || typeof node === "number" || typeof node === "boolean") {
      if (typeof node === "number" && !Number.isFinite(node)) {
        throw new MaskedRequestError("정규화할 수 없는 값입니다.");
      }
      if (typeof node === "string") {
        for (let index = 0; index < node.length; index += 1) {
          const code = node.charCodeAt(index);
          if (code >= 0xd800 && code <= 0xdfff) throw new MaskedRequestError("정규화할 수 없는 값입니다.");
        }
      }
      return node;
    }
    if (Array.isArray(node)) return node.map(visit);
    if (isRecord(node)) {
      const sorted: Record<string, unknown> = {};
      for (const key of Object.keys(node).sort()) sorted[key] = visit(node[key]);
      return sorted;
    }
    throw new MaskedRequestError("정규화할 수 없는 값입니다.");
  };
  return JSON.stringify(visit(value));
}

/** 봉인 subject의 정규 확인값 — Core `canonical_digest()`와 같은 값이다. */
export async function canonicalSubjectDigest(subject: MaskedSealedSubject): Promise<string> {
  const wire = canonicalJsonString(subject as unknown as Record<string, unknown>);
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(wire));
  return `sha256:${[...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

/** 클라이언트가 원시 바이트 해시를 계산한다 — TIFF를 복호화하지 않는다. */
export async function sha256HexOfBytes(bytes: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", bytes as unknown as ArrayBuffer);
  return `sha256:${[...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

/**
 * 마스크 파일 1차 가드 — 이름·종류·크기만 본다. 픽셀을 읽거나 격자 진실을
 * 선언하지 않으며, 실제 검사는 Core 관찰 보고서가 판정한다.
 * 예산은 서버 설정에서만 오며, 없으면 선택 자체를 막는다(기본값 발명 금지).
 */
export function validateMaskFile(file: File, budgetBytes: number | null): string | null {
  if (budgetBytes === null || !Number.isSafeInteger(budgetBytes) || budgetBytes <= 0) {
    return "마스크 업로드 예산이 설정되지 않았습니다. 관리자에게 서버 업로드 예산 설정을 요청하세요.";
  }
  const lowerName = file.name.toLowerCase();
  const tiffName = lowerName.endsWith(".tif") || lowerName.endsWith(".tiff");
  const tiffType = file.type === "image/tiff" || file.type === "image/x-tiff" || file.type === "";
  if (!tiffName || !tiffType) {
    return "마스크는 uint8 단일 밴드 TIFF 파일(.tif/.tiff)만 선택할 수 있습니다.";
  }
  if (file.size <= 0 || file.size > budgetBytes) {
    return `마스크 파일 크기는 0보다 크고 ${budgetBytes}바이트 이하여야 합니다.`;
  }
  return null;
}

/** 봉인 외부 subject — Core 기록에서 그대로 가져온 7개 키만 받는다. */
export type MaskedSealedSubject = {
  organizationId: string;
  siteId: string;
  workOrderId: string;
  submissionId: string;
  revision: number;
  submissionDigest: string;
  manifestDigest: string;
};

const subjectKeys = [
  "organizationId",
  "siteId",
  "workOrderId",
  "submissionId",
  "revision",
  "submissionDigest",
  "manifestDigest",
] as const;

export function isMaskedSealedSubject(value: unknown): value is MaskedSealedSubject {
  if (!isRecord(value) || !hasExactKeys(value, subjectKeys)) return false;
  return (
    isBoundedText(value.organizationId, 255)
    && isBoundedText(value.siteId, 255)
    && isBoundedText(value.workOrderId, 255)
    && isBoundedText(value.submissionId, 255)
    && isPositiveInt(value.revision)
    && isDigest(value.submissionDigest)
    && isDigest(value.manifestDigest)
  );
}

/** 마스크 자식 선언 — Core `MaskChildDeclarationV1` 와이어 그대로다. */
export type MaskChildDeclarationWire = {
  contractVersion: "external-mask-child-declaration.v1";
  declarationId: string;
  organizationId: string;
  siteId: string;
  workAreaId: string;
  childKind: "MASK_CHILD";
  maskChildId: string;
  maskArtifactId: string;
  parentSubject: MaskedSealedSubject;
  targetBaselineSubject: MaskedSealedSubject;
  targetBaselineDsmArtifactId: string;
  declaredSha256: string;
  declaredSizeBytes: number;
  declarationDigest: string | null;
};

const declarationKeys = [
  "contractVersion",
  "declarationId",
  "organizationId",
  "siteId",
  "workAreaId",
  "childKind",
  "maskChildId",
  "maskArtifactId",
  "parentSubject",
  "targetBaselineSubject",
  "targetBaselineDsmArtifactId",
  "declaredSha256",
  "declaredSizeBytes",
  "declarationDigest",
] as const;

/** BFF가 Core에 보내기 전, 선언 와이어를 닫힌 형태로 검증한다. */
export function parseMaskChildDeclaration(body: unknown): MaskChildDeclarationWire {
  if (!isRecord(body) || !hasExactKeys(body, declarationKeys)) {
    throw new MaskedRequestError("마스크 입력 요청 형식이 올바르지 않습니다.");
  }
  if (
    body.contractVersion !== "external-mask-child-declaration.v1"
    || body.childKind !== "MASK_CHILD"
    || !isBoundedText(body.declarationId, 255)
    || !isScopeId(body.organizationId)
    || !isScopeId(body.siteId)
    || !isScopeId(body.workAreaId)
    || !isOpaqueId(body.maskChildId)
    || !isOpaqueId(body.maskArtifactId)
    || !isOpaqueId(body.targetBaselineDsmArtifactId)
    || !isDigest(body.declaredSha256)
    || !isPositiveInt(body.declaredSizeBytes)
    || !(body.declarationDigest === null || isDigest(body.declarationDigest))
    || !isMaskedSealedSubject(body.parentSubject)
    || !isMaskedSealedSubject(body.targetBaselineSubject)
  ) {
    throw new MaskedRequestError("마스크 입력 요청 형식이 올바르지 않습니다.");
  }
  const parent = body.parentSubject as MaskedSealedSubject;
  const baseline = body.targetBaselineSubject as MaskedSealedSubject;
  if (
    parent.organizationId !== body.organizationId
    || parent.siteId !== body.siteId
    || baseline.organizationId !== body.organizationId
    || baseline.siteId !== body.siteId
  ) {
    throw new MaskedRequestError("마스크 선언 subject가 요청 범위를 벗어났습니다.");
  }
  // 부모 subject는 기준·현재 어느 쪽에 속해도 된다 — 진짜 봉인 subject이며
  // 정확한 기준선 앵커에 묶이기만 하면 된다. 서로 다름을 요구하지 않는다
  // (승인된 P2 권한에 그런 규칙이 없다).
  return body as unknown as MaskChildDeclarationWire;
}

/** Core 관찰 manifest — Core `MaskObservedManifestV1` 와이어 그대로다. */
export type MaskObservedManifestWire = {
  contractVersion: "external-mask-observed-manifest.v1";
  organizationId: string;
  siteId: string;
  workAreaId: string;
  childKind: "MASK_CHILD";
  maskChildId: string;
  maskArtifactId: string;
  subject: MaskedSealedSubject;
  parentSubjectDigest: string;
  targetBaselineDsmArtifactId: string;
  targetBaselineSubjectDigest: string;
  observedSha256: string;
  observedSizeBytes: number;
  observedInspectionReportDigest: string;
  inspectionProfileDigest: string;
  rows: number;
  columns: number;
  transform: [number, number, number, number, number, number];
  transformDigest: string;
  observedCrsIdentifier: string;
  observedCrsDigest: string;
  dtype: "UINT8";
  bandCount: 1;
  retainValue: 0;
  excludeValue: 1;
  nodataRepresentation: "NONE";
  bounds: [number, number, number, number];
  manifestDigest: string | null;
};

const manifestKeys = [
  "contractVersion",
  "organizationId",
  "siteId",
  "workAreaId",
  "childKind",
  "maskChildId",
  "maskArtifactId",
  "subject",
  "parentSubjectDigest",
  "targetBaselineDsmArtifactId",
  "targetBaselineSubjectDigest",
  "observedSha256",
  "observedSizeBytes",
  "observedInspectionReportDigest",
  "inspectionProfileDigest",
  "rows",
  "columns",
  "transform",
  "transformDigest",
  "observedCrsIdentifier",
  "observedCrsDigest",
  "dtype",
  "bandCount",
  "retainValue",
  "excludeValue",
  "nodataRepresentation",
  "bounds",
  "manifestDigest",
] as const;

function isAffine(value: unknown): value is [number, number, number, number, number, number] {
  return Array.isArray(value)
    && value.length === 6
    && value.every((item) => typeof item === "number" && Number.isFinite(item));
}

function isBounds(value: unknown): value is [number, number, number, number] {
  return Array.isArray(value)
    && value.length === 4
    && value.every((item) => typeof item === "number" && Number.isFinite(item));
}

function isManifestShape(value: unknown): value is MaskObservedManifestWire {
  if (!isRecord(value) || !hasExactKeys(value, manifestKeys)) return false;
  if (
    value.contractVersion !== "external-mask-observed-manifest.v1"
    || value.childKind !== "MASK_CHILD"
    || !isScopeId(value.organizationId)
    || !isScopeId(value.siteId)
    || !isScopeId(value.workAreaId)
    || !isOpaqueId(value.maskChildId)
    || !isOpaqueId(value.maskArtifactId)
    || !isMaskedSealedSubject(value.subject)
    || !isDigest(value.parentSubjectDigest)
    || !isOpaqueId(value.targetBaselineDsmArtifactId)
    || !isDigest(value.targetBaselineSubjectDigest)
    || !isDigest(value.observedSha256)
    || !isPositiveInt(value.observedSizeBytes)
    || !isDigest(value.observedInspectionReportDigest)
    || !isDigest(value.inspectionProfileDigest)
    || !isPositiveInt(value.rows)
    || !isPositiveInt(value.columns)
    || !isAffine(value.transform)
    || !isDigest(value.transformDigest)
    || !isBoundedText(value.observedCrsIdentifier, 255)
    || !isDigest(value.observedCrsDigest)
    || value.dtype !== "UINT8"
    || value.bandCount !== 1
    || value.retainValue !== 0
    || value.excludeValue !== 1
    || value.nodataRepresentation !== "NONE"
    || !isBounds(value.bounds)
    || !(value.manifestDigest === null || isDigest(value.manifestDigest))
  ) {
    return false;
  }
  return true;
}

/** 자식 화면 — 선언 의도 + 봉인 manifest(있을 때만 검사 완료). */
export type MaskChildViewWire = {
  declaration: MaskChildDeclarationWire;
  manifest: MaskObservedManifestWire | null;
};

const childViewKeys = ["declaration", "manifest"] as const;

export function parseMaskChildView(
  value: unknown,
  scope: { siteId: string; workAreaId: string; maskChildId: string },
): MaskChildViewWire {
  if (!isRecord(value) || !hasExactKeys(value, childViewKeys)) {
    throw new Error("마스크 입력 응답 형식을 확인할 수 없습니다.");
  }
  let declaration: MaskChildDeclarationWire;
  try {
    declaration = parseMaskChildDeclaration(value.declaration);
  } catch {
    throw new Error("마스크 입력 응답 형식을 확인할 수 없습니다.");
  }
  const manifest = value.manifest === null ? null : isManifestShape(value.manifest) ? value.manifest : null;
  if (value.manifest !== null && manifest === null) {
    throw new Error("마스크 입력 응답 형식을 확인할 수 없습니다.");
  }
  if (
    declaration.siteId !== scope.siteId
    || declaration.workAreaId !== scope.workAreaId
    || declaration.maskChildId !== scope.maskChildId
  ) {
    throw new Error("마스크 입력 응답의 요청 범위를 확인할 수 없습니다.");
  }
  if (manifest !== null && (manifest.maskChildId !== scope.maskChildId || manifest.siteId !== scope.siteId || manifest.workAreaId !== scope.workAreaId)) {
    throw new Error("마스크 입력 응답의 요청 범위를 확인할 수 없습니다.");
  }
  return { declaration, manifest };
}

/** 업로드 부여 요청 — Core `MaskUploadGrantRequestV1` 와이어 그대로다. */
export type MaskUploadGrantRequestWire = {
  maskArtifactId: string;
  subjectDigest: string;
  declaredSha256: string;
  declaredSizeBytes: number;
  ttlSeconds?: number;
};

const grantRequestRequiredKeys = ["maskArtifactId", "subjectDigest", "declaredSha256", "declaredSizeBytes"] as const;

export function parseMaskUploadGrantRequest(body: unknown): MaskUploadGrantRequestWire {
  if (!isRecord(body)) {
    throw new MaskedRequestError("업로드 부여 요청 형식이 올바르지 않습니다.");
  }
  const keys = Object.keys(body);
  const hasTtl = Object.hasOwn(body, "ttlSeconds");
  if (
    keys.length !== (hasTtl ? 5 : 4)
    || !grantRequestRequiredKeys.every((key) => Object.hasOwn(body, key))
    || (hasTtl && !grantRequestRequiredKeys.includes("ttlSeconds" as never))
  ) {
    if (hasTtl && keys.length === 5 && keys.includes("ttlSeconds")) {
      // ttlSeconds가 있는 5키 형태 — 아래에서 값을 검증한다.
    } else {
      throw new MaskedRequestError("업로드 부여 요청 형식이 올바르지 않습니다.");
    }
  }
  if (
    !isOpaqueId(body.maskArtifactId)
    || !isDigest(body.subjectDigest)
    || !isDigest(body.declaredSha256)
    || !isPositiveInt(body.declaredSizeBytes)
  ) {
    throw new MaskedRequestError("업로드 부여 요청 형식이 올바르지 않습니다.");
  }
  if (hasTtl) {
    const ttl = body.ttlSeconds;
    if (typeof ttl !== "number" || !Number.isSafeInteger(ttl) || ttl < 1 || ttl > 24 * 3600) {
      throw new MaskedRequestError("업로드 부여 요청 형식이 올바르지 않습니다.");
    }
    return {
      maskArtifactId: body.maskArtifactId,
      subjectDigest: body.subjectDigest,
      declaredSha256: body.declaredSha256,
      declaredSizeBytes: body.declaredSizeBytes,
      ttlSeconds: ttl,
    };
  }
  return {
    maskArtifactId: body.maskArtifactId,
    subjectDigest: body.subjectDigest,
    declaredSha256: body.declaredSha256,
    declaredSizeBytes: body.declaredSizeBytes,
  };
}

/** 업로드 부여·봉인 화면 — Core 와이어 그대로다. */
export type MaskUploadGrantViewWire = {
  grantId: string;
  maskChildId: string;
  maskArtifactId: string;
  expiresAt: string;
};

export type MaskUploadSealViewWire = {
  maskChildId: string;
  maskArtifactId: string;
  observedSha256: string;
  observedSizeBytes: number;
};

const grantViewKeys = ["grantId", "maskChildId", "maskArtifactId", "expiresAt"] as const;
const sealViewKeys = ["maskChildId", "maskArtifactId", "observedSha256", "observedSizeBytes"] as const;

export function parseMaskUploadGrantView(
  value: unknown,
  scope: { maskChildId: string; maskArtifactId: string },
): MaskUploadGrantViewWire {
  if (!isRecord(value) || !hasExactKeys(value, grantViewKeys)) {
    throw new Error("마스크 입력 응답 형식을 확인할 수 없습니다.");
  }
  if (
    !isBoundedText(value.grantId, 255)
    || value.maskChildId !== scope.maskChildId
    || value.maskArtifactId !== scope.maskArtifactId
    || !isUtcIsoDateTime(value.expiresAt)
  ) {
    throw new Error("마스크 입력 응답의 요청 범위를 확인할 수 없습니다.");
  }
  return value as unknown as MaskUploadGrantViewWire;
}

export function parseMaskUploadSealView(
  value: unknown,
  scope: { maskChildId: string; maskArtifactId: string; declaredSha256: string; declaredSizeBytes: number },
): MaskUploadSealViewWire {
  if (!isRecord(value) || !hasExactKeys(value, sealViewKeys)) {
    throw new Error("마스크 입력 응답 형식을 확인할 수 없습니다.");
  }
  if (
    value.maskChildId !== scope.maskChildId
    || value.maskArtifactId !== scope.maskArtifactId
    || value.observedSha256 !== scope.declaredSha256
    || value.observedSizeBytes !== scope.declaredSizeBytes
  ) {
    throw new Error("마스크 입력 응답의 요청 범위를 확인할 수 없습니다.");
  }
  if (!isDigest(value.observedSha256) || !isPositiveInt(value.observedSizeBytes)) {
    throw new Error("마스크 입력 응답 형식을 확인할 수 없습니다.");
  }
  return value as unknown as MaskUploadSealViewWire;
}

/**
 * V3 계산 생성 — Core `MaskedCalculationCreateRequestV1` 와이어 그대로다.
 * 봉인된 원본 계산 신원 확인값 + 마스크 자식만 싣는다. 마스크 바인딩
 * 확인값은 클라이언트가 지어내지 않으며, Core가 봉인 manifest로부터 만든다.
 */
export type MaskedCalculationCreateWire = {
  maskedCalculationId: string;
  sourceCalculationIdentityDigest: string;
  maskChildId: string;
  requestId: string;
  idempotencyKey: string;
};

const createKeys = [
  "maskedCalculationId",
  "sourceCalculationIdentityDigest",
  "maskChildId",
  "requestId",
  "idempotencyKey",
] as const;

export function parseMaskedCalculationCreate(body: unknown): MaskedCalculationCreateWire {
  if (!isRecord(body) || !hasExactKeys(body, createKeys)) {
    throw new MaskedRequestError("마스크 계산 요청 형식이 올바르지 않습니다.");
  }
  if (
    !isOpaqueId(body.maskedCalculationId)
    || !isDigest(body.sourceCalculationIdentityDigest)
    || !isOpaqueId(body.maskChildId)
    || !isOpaqueId(body.requestId)
    || !isBoundedText(body.idempotencyKey, 255)
  ) {
    throw new MaskedRequestError("마스크 계산 요청 형식이 올바르지 않습니다.");
  }
  return body as unknown as MaskedCalculationCreateWire;
}

/** V3 승인 — Core `MaskedAdmissionV3` 와이어 그대로다(수치 없음). */
export type MaskedAdmissionWire = {
  contractVersion: "external-masked-execution-admission.v3";
  admissionId: string;
  organizationId: string;
  siteId: string;
  workAreaId: string;
  maskedCalculationIdentityDigest: string;
  sourceCalculationIdentityDigest: string;
  maskBindingDigest: string;
  maskedProfileDigest: string;
  areaDefinitionDigest: string;
  policyDigest: string;
  runtimeDigest: string;
  resourceEnvelopeDigest: string;
  activationDigest: string;
  scopeDigest: string;
  aiEgressDigest: string;
  disposition: "ADMIT_PROVISIONAL" | "ADMIT_EVALUATED" | "REMEDIATION_REQUIRED" | "BLOCKED";
  reasonCodes: string[];
  assessedAt: string;
  admissionDigest: string | null;
};

const admissionKeys = [
  "contractVersion",
  "admissionId",
  "organizationId",
  "siteId",
  "workAreaId",
  "maskedCalculationIdentityDigest",
  "sourceCalculationIdentityDigest",
  "maskBindingDigest",
  "maskedProfileDigest",
  "areaDefinitionDigest",
  "policyDigest",
  "runtimeDigest",
  "resourceEnvelopeDigest",
  "activationDigest",
  "scopeDigest",
  "aiEgressDigest",
  "disposition",
  "reasonCodes",
  "assessedAt",
  "admissionDigest",
] as const;

function isAdmissionShape(value: unknown): value is MaskedAdmissionWire {
  if (!isRecord(value) || !hasExactKeys(value, admissionKeys)) return false;
  if (
    value.contractVersion !== "external-masked-execution-admission.v3"
    || !isBoundedText(value.admissionId, 255)
    || !isScopeId(value.organizationId)
    || !isScopeId(value.siteId)
    || !isScopeId(value.workAreaId)
    || !isDigest(value.maskedCalculationIdentityDigest)
    || !isDigest(value.sourceCalculationIdentityDigest)
    || !isDigest(value.maskBindingDigest)
    || !isDigest(value.maskedProfileDigest)
    || !isDigest(value.areaDefinitionDigest)
    || !isDigest(value.policyDigest)
    || !isDigest(value.runtimeDigest)
    || !isDigest(value.resourceEnvelopeDigest)
    || !isDigest(value.activationDigest)
    || !isDigest(value.scopeDigest)
    || !isDigest(value.aiEgressDigest)
    || (value.disposition !== "ADMIT_PROVISIONAL"
      && value.disposition !== "ADMIT_EVALUATED"
      && value.disposition !== "REMEDIATION_REQUIRED"
      && value.disposition !== "BLOCKED")
    || !Array.isArray(value.reasonCodes)
    || value.reasonCodes.length < 1
    || value.reasonCodes.length > 64
    || !value.reasonCodes.every((code): code is string => typeof code === "string" && reasonPattern.test(code))
    || !isUtcIsoDateTime(value.assessedAt)
    || !(value.admissionDigest === null || isDigest(value.admissionDigest))
  ) {
    return false;
  }
  return true;
}

/** 현재−기준 델타(단위: metre). V2 잎을 그대로 재사용하며 확장하지 않는다. */
export type MaskedVolumeMetricsWire = {
  cutM3: number;
  fillM3: number;
  netM3: number;
  thresholdM: number;
  uncertaintyM3: null;
};

const metricsKeys = ["cutM3", "fillM3", "netM3", "thresholdM", "uncertaintyM3"] as const;

function isMetricsShape(value: unknown): value is MaskedVolumeMetricsWire {
  if (!isRecord(value) || !hasExactKeys(value, metricsKeys)) return false;
  if (!isNonNegativeFinite(value.cutM3) || !isNonNegativeFinite(value.fillM3) || !isFiniteNumber(value.netM3)) return false;
  if (value.thresholdM !== 0 || value.uncertaintyM3 !== null) return false;
  if (!isClose(value.netM3 as number, (value.fillM3 as number) - (value.cutM3 as number))) return false;
  return true;
}

const FLOAT_REL_TOLERANCE = 1e-12;
const FLOAT_ABS_TOLERANCE = 1e-12;

function isClose(actual: number, want: number): boolean {
  return Math.abs(actual - want) <= Math.max(FLOAT_REL_TOLERANCE * Math.max(Math.abs(actual), Math.abs(want)), FLOAT_ABS_TOLERANCE);
}

function decodeCanonicalBase64(input: string): Uint8Array {
  if (input.length === 0 || input.length % 4 !== 0) {
    throw new Error("mask bits are not canonical base64");
  }
  const binary = atob(input);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  let out = "";
  for (let index = 0; index < bytes.length; index += 3) {
    const a = bytes[index]!;
    const b = index + 1 < bytes.length ? bytes[index + 1]! : 0;
    const c = index + 2 < bytes.length ? bytes[index + 2]! : 0;
    out += alphabet[a >> 2];
    out += alphabet[((a & 3) << 4) | (b >> 4)];
    out += index + 1 < bytes.length ? alphabet[((b & 15) << 2) | (c >> 6)] : "=";
    out += index + 2 < bytes.length ? alphabet[c & 63] : "=";
  }
  if (out !== input) throw new Error("mask bits are not canonical base64");
  return bytes;
}

function countBits(bytes: Uint8Array): number {
  let total = 0;
  for (const byte of bytes) {
    let rest = byte;
    while (rest !== 0) {
      total += rest & 1;
      rest >>= 1;
    }
  }
  return total;
}

/** 손실 없는 범위 근거 — Core `MaskedCoverageWitnessV3` 와이어 그대로다. */
export type MaskedCoverageWire = {
  contractVersion: "external-masked-volume-coverage-witness.v3";
  rows: number;
  columns: number;
  rowOffset: number;
  columnOffset: number;
  originalSelectedMaskB64: string;
  maskExcludedMaskB64: string;
  effectiveSelectedMaskB64: string;
  commonValidMaskB64: string;
  unavailableMaskB64: string;
  originalSelectedCellCount: number;
  maskExcludedCellCount: number;
  effectiveSelectedCellCount: number;
  commonValidCellCount: number;
  unavailableCellCount: number;
  cellAreaM2: number;
  originalSelectedAreaM2: number;
  effectiveSelectedAreaM2: number;
  commonValidAreaM2: number;
  bounds: [number, number, number, number];
  coverageWitnessDigest: string | null;
};

const coverageKeys = [
  "contractVersion",
  "rows",
  "columns",
  "rowOffset",
  "columnOffset",
  "originalSelectedMaskB64",
  "maskExcludedMaskB64",
  "effectiveSelectedMaskB64",
  "commonValidMaskB64",
  "unavailableMaskB64",
  "originalSelectedCellCount",
  "maskExcludedCellCount",
  "effectiveSelectedCellCount",
  "commonValidCellCount",
  "unavailableCellCount",
  "cellAreaM2",
  "originalSelectedAreaM2",
  "effectiveSelectedAreaM2",
  "commonValidAreaM2",
  "bounds",
  "coverageWitnessDigest",
] as const;

function isCoverageShape(value: unknown): value is MaskedCoverageWire {
  if (!isRecord(value) || !hasExactKeys(value, coverageKeys)) return false;
  if (value.contractVersion !== "external-masked-volume-coverage-witness.v3") return false;
  if (!isPositiveInt(value.rows) || !isPositiveInt(value.columns)) return false;
  const rows = value.rows as number;
  const columns = value.columns as number;
  if (!isSafeInt(value.rowOffset) || !isSafeInt(value.columnOffset)) return false;
  const counts = [
    value.originalSelectedCellCount,
    value.maskExcludedCellCount,
    value.effectiveSelectedCellCount,
    value.commonValidCellCount,
    value.unavailableCellCount,
  ];
  if (!counts.every(isNonNegativeInt)) return false;
  const [original, , effective, common, unavailable] = counts as [number, number, number, number, number];
  // 마스크 비트는 정식 base64이며 행렬 크기와 바이트 길이가 맞물려야 한다.
  // 화면이 격자를 연산하지는 않지만, 개수가 비트와 어긋난 응답은 버린다.
  let decoded: Uint8Array[];
  try {
    decoded = [
      value.originalSelectedMaskB64,
      value.maskExcludedMaskB64,
      value.effectiveSelectedMaskB64,
      value.commonValidMaskB64,
      value.unavailableMaskB64,
    ].map((item) => {
      if (typeof item !== "string") throw new Error("mask bits are not canonical base64");
      return decodeCanonicalBase64(item);
    });
  } catch {
    return false;
  }
  const expectedBytes = Math.ceil((rows * columns) / 8);
  if (!decoded.every((bytes) => bytes.length === expectedBytes)) return false;
  if (decoded.map(countBits).join(",") !== counts.join(",")) return false;
  // effective = original − excluded, common ⊆ effective, unavailable = effective − common.
  // V3 성공은 0이 아닌 유효 구역 + 100% 공통 유효 + 0 unavailable이다.
  const [originalBits, excludedBits, effectiveBits, commonBits, unavailableBits] = decoded as [Uint8Array, Uint8Array, Uint8Array, Uint8Array, Uint8Array];
  for (let index = 0; index < expectedBytes; index += 1) {
    const sel = originalBits[index]!;
    if ((excludedBits[index]! & ~sel) !== 0) return false;
    if (effectiveBits[index]! !== (sel & ~excludedBits[index]!)) return false;
    if ((commonBits[index]! & ~effectiveBits[index]!) !== 0) return false;
    if (unavailableBits[index]! !== (effectiveBits[index]! & ~commonBits[index]!)) return false;
  }
  if (effective === 0 || unavailable !== 0 || common !== effective) return false;
  if (!isFiniteNumber(value.cellAreaM2) || (value.cellAreaM2 as number) <= 0) return false;
  const cellArea = value.cellAreaM2 as number;
  const areas: Array<[unknown, number]> = [
    [value.originalSelectedAreaM2, original * cellArea],
    [value.effectiveSelectedAreaM2, effective * cellArea],
    [value.commonValidAreaM2, common * cellArea],
  ];
  if (!areas.every(([actual, want]) => isNonNegativeFinite(actual) && isClose(actual as number, want))) return false;
  if (!isBounds(value.bounds)) return false;
  const [left, bottom, right, top] = value.bounds as [number, number, number, number];
  if (!(left < right && bottom < top)) return false;
  if (!(value.coverageWitnessDigest === null || isDigest(value.coverageWitnessDigest))) return false;
  return true;
}

/**
 * 마스크를 씌우지 않았을 때와의 차이 — Core `MaskedVolumeImpactV3` 그대로다.
 * 원본 구역에 값 없는 셀이 있었다면 제외 영역의 원래 수치는 알 수 없으므로
 * 전부 null이다 — 0을 지어내지 않는다.
 */
export type MaskedImpactWire = {
  unmaskedImpactKnown: boolean;
  excludedCellCount: number;
  unmaskedCutM3: number | null;
  unmaskedFillM3: number | null;
  unmaskedNetM3: number | null;
  excludedCutM3: number | null;
  excludedFillM3: number | null;
  excludedNetM3: number | null;
};

const impactKeys = [
  "unmaskedImpactKnown",
  "excludedCellCount",
  "unmaskedCutM3",
  "unmaskedFillM3",
  "unmaskedNetM3",
  "excludedCutM3",
  "excludedFillM3",
  "excludedNetM3",
] as const;

function isImpactShape(value: unknown, excludedCellCount: number): value is MaskedImpactWire {
  if (!isRecord(value) || !hasExactKeys(value, impactKeys)) return false;
  if (typeof value.unmaskedImpactKnown !== "boolean") return false;
  if (!isNonNegativeInt(value.excludedCellCount) || value.excludedCellCount !== excludedCellCount) return false;
  const volumes = [
    value.unmaskedCutM3,
    value.unmaskedFillM3,
    value.unmaskedNetM3,
    value.excludedCutM3,
    value.excludedFillM3,
    value.excludedNetM3,
  ];
  if (value.unmaskedImpactKnown !== true) {
    return volumes.every((item) => item === null);
  }
  const finite = volumes.filter((item): item is number => typeof item === "number");
  if (finite.length !== volumes.length || !finite.every((item) => Number.isFinite(item))) return false;
  const [unmaskedCut, unmaskedFill, unmaskedNet, excludedCut, excludedFill, excludedNet] = finite as [number, number, number, number, number, number];
  if (unmaskedCut < 0 || unmaskedFill < 0 || excludedCut < 0 || excludedFill < 0) return false;
  if (!isClose(unmaskedNet, unmaskedFill - unmaskedCut)) return false;
  if (!isClose(excludedNet, excludedFill - excludedCut)) return false;
  return true;
}

/** 봉인된 V3 수치 내용 — V2 수치 신원을 결과 키로 재사용하지 않는다. */
export type MaskedNumericResultWire = {
  contractVersion: "external-masked-volume-numeric-result.v3";
  maskedCalculationIdentityDigest: string;
  maskedProfileDigest: string;
  maskBindingDigest: string;
  metrics: MaskedVolumeMetricsWire;
  coverage: MaskedCoverageWire;
  impact: MaskedImpactWire;
  numericResultIdentityDigest: string | null;
};

const numericResultKeys = [
  "contractVersion",
  "maskedCalculationIdentityDigest",
  "maskedProfileDigest",
  "maskBindingDigest",
  "metrics",
  "coverage",
  "impact",
  "numericResultIdentityDigest",
] as const;

function isNumericResultShape(value: unknown): value is MaskedNumericResultWire {
  if (!isRecord(value) || !hasExactKeys(value, numericResultKeys)) return false;
  if (value.contractVersion !== "external-masked-volume-numeric-result.v3") return false;
  if (
    !isDigest(value.maskedCalculationIdentityDigest)
    || !isDigest(value.maskedProfileDigest)
    || !isDigest(value.maskBindingDigest)
    || !(value.numericResultIdentityDigest === null || isDigest(value.numericResultIdentityDigest))
  ) {
    return false;
  }
  if (!isMetricsShape(value.metrics) || !isCoverageShape(value.coverage)) return false;
  return isImpactShape(value.impact, (value.coverage as MaskedCoverageWire).maskExcludedCellCount);
}

/** V3 수치 보고서 — Core `MaskedVolumeCalculationReportV3` 와이어 그대로다. */
export type MaskedVolumeReportWire = {
  contractVersion: "external-masked-volume-calculation-report.v3";
  reportId: string;
  maskedCalculationIdentityDigest: string;
  numericResult: MaskedNumericResultWire;
  numericResultIdentityDigest: string;
  computedAt: string;
  reportedAt: string;
  reportDigest: string | null;
};

const reportKeys = [
  "contractVersion",
  "reportId",
  "maskedCalculationIdentityDigest",
  "numericResult",
  "numericResultIdentityDigest",
  "computedAt",
  "reportedAt",
  "reportDigest",
] as const;

function isReportShape(value: unknown): value is MaskedVolumeReportWire {
  if (!isRecord(value) || !hasExactKeys(value, reportKeys)) return false;
  if (value.contractVersion !== "external-masked-volume-calculation-report.v3") return false;
  if (
    !isBoundedText(value.reportId, 255)
    || !isDigest(value.maskedCalculationIdentityDigest)
    || !isDigest(value.numericResultIdentityDigest)
    || !isUtcIsoDateTime(value.computedAt)
    || !isUtcIsoDateTime(value.reportedAt)
    || !(value.reportDigest === null || isDigest(value.reportDigest))
    || !isNumericResultShape(value.numericResult)
  ) {
    return false;
  }
  const numeric = value.numericResult as MaskedNumericResultWire;
  if (
    numeric.maskedCalculationIdentityDigest !== value.maskedCalculationIdentityDigest
    || numeric.numericResultIdentityDigest !== value.numericResultIdentityDigest
  ) {
    return false;
  }
  if (Date.parse(value.computedAt as string) > Date.parse(value.reportedAt as string)) return false;
  return true;
}

export type MaskedExecutionStatus = "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELED";

export type MaskedDisposition =
  | "AVAILABLE"
  | "REASSESSMENT_REQUIRED"
  | "PENDING"
  | "FAILED"
  | "CANCELED"
  | "EXECUTION_DEADLINE_EXPIRED"
  | "EXECUTION_RETRY_EXHAUSTED";

/** V3 생성 응답 — Core `MaskedCalculationCreatedViewV1` 그대로다. */
export type MaskedCalculationCreatedWire = {
  requestId: string;
  maskedCalculationIdentityDigest: string;
  status: MaskedExecutionStatus;
  admission: MaskedAdmissionWire;
};

const createdKeys = ["requestId", "maskedCalculationIdentityDigest", "status", "admission"] as const;

function isExecutionStatus(value: unknown): value is MaskedExecutionStatus {
  return value === "QUEUED" || value === "RUNNING" || value === "COMPLETED" || value === "FAILED" || value === "CANCELED";
}

export function parseMaskedCalculationCreated(
  value: unknown,
  scope: { siteId: string; workAreaId: string },
): MaskedCalculationCreatedWire {
  if (!isRecord(value) || !hasExactKeys(value, createdKeys)) {
    throw new Error("마스크 계산 응답 형식을 확인할 수 없습니다.");
  }
  if (
    !isOpaqueId(value.requestId)
    || !isDigest(value.maskedCalculationIdentityDigest)
    || !isExecutionStatus(value.status)
    || !isAdmissionShape(value.admission)
  ) {
    throw new Error("마스크 계산 응답 형식을 확인할 수 없습니다.");
  }
  const admission = value.admission as MaskedAdmissionWire;
  if (
    admission.siteId !== scope.siteId
    || admission.workAreaId !== scope.workAreaId
    || admission.maskedCalculationIdentityDigest !== value.maskedCalculationIdentityDigest
  ) {
    throw new Error("마스크 계산 응답의 요청 범위를 확인할 수 없습니다.");
  }
  return value as unknown as MaskedCalculationCreatedWire;
}

/** V3 현재 화면 — Core `MaskedCalculationDetailViewV1` 그대로다. */
export type MaskedCalculationDetailWire = {
  requestId: string;
  organizationId: string;
  siteId: string;
  workAreaId: string;
  maskedCalculationIdentityDigest: string;
  status: MaskedExecutionStatus;
  disposition: MaskedDisposition;
  admission: MaskedAdmissionWire | null;
  report: MaskedVolumeReportWire | null;
};

const detailKeys = [
  "requestId",
  "organizationId",
  "siteId",
  "workAreaId",
  "maskedCalculationIdentityDigest",
  "status",
  "disposition",
  "admission",
  "report",
] as const;

function isDisposition(value: unknown): value is MaskedDisposition {
  return (
    value === "AVAILABLE"
    || value === "REASSESSMENT_REQUIRED"
    || value === "PENDING"
    || value === "FAILED"
    || value === "CANCELED"
    || value === "EXECUTION_DEADLINE_EXPIRED"
    || value === "EXECUTION_RETRY_EXHAUSTED"
  );
}

export function parseMaskedCalculationDetail(
  value: unknown,
  scope: { siteId: string; workAreaId: string; requestId: string },
): MaskedCalculationDetailWire {
  if (!isRecord(value) || !hasExactKeys(value, detailKeys)) {
    throw new Error("마스크 계산 응답 형식을 확인할 수 없습니다.");
  }
  if (
    value.requestId !== scope.requestId
    || !isScopeId(value.organizationId)
    || value.siteId !== scope.siteId
    || value.workAreaId !== scope.workAreaId
    || !isDigest(value.maskedCalculationIdentityDigest)
    || !isExecutionStatus(value.status)
    || !isDisposition(value.disposition)
  ) {
    throw new Error("마스크 계산 응답의 요청 범위를 확인할 수 없습니다.");
  }
  const admission = value.admission === null ? null : isAdmissionShape(value.admission) ? value.admission : null;
  if (value.admission !== null && admission === null) {
    throw new Error("마스크 계산 응답 형식을 확인할 수 없습니다.");
  }
  const report = value.report === null ? null : isReportShape(value.report) ? value.report : null;
  if (value.report !== null && report === null) {
    throw new Error("마스크 계산 응답 형식을 확인할 수 없습니다.");
  }
  // AVAILABLE일 때만 수치 보고서를 싣는다 — 내보내기 상태는 수치 표시에 관여하지 않는다.
  if (value.disposition === "AVAILABLE" && report === null) {
    throw new Error("마스크 계산 응답 형식을 확인할 수 없습니다.");
  }
  if (value.disposition !== "AVAILABLE" && report !== null) {
    throw new Error("마스크 계산 응답 형식을 확인할 수 없습니다.");
  }
  // AVAILABLE은 봉인 완료를 뜻하므로 세 확인값이 모두 있어야 한다(구조적
  // 확인만 하며 해시를 재계산하지 않는다 — 봉인 판정은 Core의 몫이다).
  // isReportShape 자체는 와이어 일반형을 허용하므로 여기서만 닫는다.
  if (value.disposition === "AVAILABLE" && report !== null) {
    if (
      report.reportDigest === null
      || report.numericResult.numericResultIdentityDigest === null
      || report.numericResult.coverage.coverageWitnessDigest === null
    ) {
      throw new Error("마스크 계산 응답 형식을 확인할 수 없습니다.");
    }
  }
  if (admission !== null) {
    if (
      admission.siteId !== scope.siteId
      || admission.workAreaId !== scope.workAreaId
      || admission.maskedCalculationIdentityDigest !== value.maskedCalculationIdentityDigest
    ) {
      throw new Error("마스크 계산 응답의 요청 범위를 확인할 수 없습니다.");
    }
  }
  if (report !== null && report.maskedCalculationIdentityDigest !== value.maskedCalculationIdentityDigest) {
    throw new Error("마스크 계산 응답의 요청 범위를 확인할 수 없습니다.");
  }
  return value as unknown as MaskedCalculationDetailWire;
}

/** V3 변경 취소 응답 — Core `MaskedCalculationMutationViewV1` 그대로다. */
export type MaskedCalculationMutationWire = {
  requestId: string;
  status: MaskedExecutionStatus;
  attempt: unknown;
};

const mutationKeys = ["requestId", "status", "attempt"] as const;

export function parseMaskedCalculationMutation(
  value: unknown,
  scope: { requestId: string },
): MaskedCalculationMutationWire {
  if (!isRecord(value) || !hasExactKeys(value, mutationKeys)) {
    throw new Error("마스크 계산 응답 형식을 확인할 수 없습니다.");
  }
  if (value.requestId !== scope.requestId || !isExecutionStatus(value.status)) {
    throw new Error("마스크 계산 응답의 요청 범위를 확인할 수 없습니다.");
  }
  // attempt는 워커 펜스 내부 구조이므로 존재만 확인하고 해석하지 않는다.
  return value as unknown as MaskedCalculationMutationWire;
}

/**
 * 늦은 발행 인계 — Core `MaskedDeltaSourceRefV1` 그대로다. 부모가 기존
 * 내보내기 패널을 이 세 확인값+자식으로 compose한다. 발행 경로는 부모 소유이며,
 * 완료된 마스크 시도를 읽기 권한으로 빌려 쓰지 않는다.
 */
export type MaskedDeltaSourceRefWire = {
  sourceCalculationIdentityDigest: string;
  sourceNumericResultIdentityDigest: string;
  sourceCoverageWitnessDigest: string;
  maskChildId: string;
};

const deltaRefKeys = [
  "sourceCalculationIdentityDigest",
  "sourceNumericResultIdentityDigest",
  "sourceCoverageWitnessDigest",
  "maskChildId",
] as const;

export function parseMaskedDeltaSourceRef(value: unknown): MaskedDeltaSourceRefWire {
  if (!isRecord(value) || !hasExactKeys(value, deltaRefKeys)) {
    throw new MaskedRequestError("마스크 인계 참조 형식이 올바르지 않습니다.");
  }
  if (
    !isDigest(value.sourceCalculationIdentityDigest)
    || !isDigest(value.sourceNumericResultIdentityDigest)
    || !isDigest(value.sourceCoverageWitnessDigest)
    || !isOpaqueId(value.maskChildId)
  ) {
    throw new MaskedRequestError("마스크 인계 참조 형식이 올바르지 않습니다.");
  }
  return value as unknown as MaskedDeltaSourceRefWire;
}

/** BFF가 화살표 선택자(관측 선택 삼중항) 형태를 최소 검증한다 — 정확도 판정 아님. */
export function isAnalysisSelectorShape(value: unknown): value is { workOrderId: string; submissionRef: string; revision: number } {
  if (!isRecord(value) || !hasExactKeys(value, ["workOrderId", "submissionRef", "revision"])) return false;
  return (
    isBoundedText(value.workOrderId, 255)
    && typeof value.submissionRef === "string"
    && submissionRefPattern.test(value.submissionRef)
    && isPositiveInt(value.revision)
  );
}

function isAbortError(error: unknown): boolean {
  return (error instanceof DOMException && error.name === "AbortError")
    || (error instanceof Error && error.name === "AbortError");
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
        throw new Error("마스크 서버 응답이 너무 큽니다.");
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

/** BFF가 Core에서 받아들이는 JSON 응답 상한. */
export const MASKED_MAX_RESPONSE_JSON_BYTES = 2_097_152;

/** Core 업스트림 호출 제한 — 이 시간을 넘기면 503으로 닫는다. */
export const MASKED_UPSTREAM_TIMEOUT_MS = 20_000;

function errorFromText(text: string, fallback: string): { message: string; code: string | null } {
  if (text.length === 0) return { message: fallback, code: null };
  try {
    const body = JSON.parse(text) as Record<string, unknown>;
    const message = typeof body.message === "string" && body.message.length > 0 ? body.message : fallback;
    const code = typeof body.code === "string" && body.code.length > 0 ? body.code : null;
    return { message, code };
  } catch {
    return { message: fallback, code: null };
  }
}

function throwForStatus(status: number, text: string, fallback: string): never {
  const { message, code } = errorFromText(text, fallback);
  // 원본 맥락 미연결은 타임아웃이 아니라 typed 대기로만 둔다.
  if (status === 400 || status === 413 || status === 415 || status === 422) {
    const error = new MaskedRequestError(message);
    error.code = code;
    throw error;
  }
  if (status === 401) throw new Error("세션이 만료되었습니다. 다시 로그인하세요.");
  if (status === 403) {
    const error = new MaskedForbiddenError(message);
    error.code = code;
    throw error;
  }
  if (status === 404) {
    const error = new MaskedNotFoundError(message);
    error.code = code;
    throw error;
  }
  if (status === 409) {
    const error = new MaskedConflictError(message);
    error.code = code;
    throw error;
  }
  if (isAbortError(new Error()) || status === 503 || status === 408) throw new MaskedUpstreamTimeoutError();
  const error = new Error(message);
  throw error;
}

async function bffJson(method: "GET" | "POST", path: string, options: { body?: unknown; signal?: AbortSignal } = {}): Promise<unknown> {
  if (options.signal?.aborted === true) throw new MaskedUpstreamTimeoutError();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), MASKED_UPSTREAM_TIMEOUT_MS);
  const onAbort = () => controller.abort();
  options.signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const response = await fetch(path, {
      method,
      headers: options.body !== undefined ? { "content-type": "application/json" } : undefined,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
      cache: "no-store",
    });
    const text = await readBoundedText(response, MASKED_MAX_RESPONSE_JSON_BYTES);
    if (!response.ok) {
      throwForStatus(response.status, text, "마스크 입력 요청 형식이 올바르지 않습니다.");
    }
    if (text.length === 0) return null;
    try {
      return JSON.parse(text) as unknown;
    } catch {
      throw new Error("마스크 계산 응답 형식을 확인할 수 없습니다.");
    }
  } catch (error) {
    if (
      error instanceof MaskedRequestError
      || error instanceof MaskedNotFoundError
      || error instanceof MaskedForbiddenError
      || error instanceof MaskedConflictError
    ) {
      throw error;
    }
    if (isAbortError(error) || controller.signal.aborted) throw new MaskedUpstreamTimeoutError();
    throw error;
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", onAbort);
  }
}

function maskInputsPath(siteId: string, workAreaId: string, maskChildId?: string): string {
  const base = `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/mask-inputs`;
  return maskChildId === undefined ? base : `${base}/${encodeURIComponent(maskChildId)}`;
}

function maskedAnalysesPath(siteId: string, workAreaId: string, requestId?: string): string {
  const base = `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/masked-analyses`;
  return requestId === undefined ? base : `${base}/${encodeURIComponent(requestId)}`;
}

/**
 * 마스크 자식 선언 — 검증된 선언 와이어만 BFF에 싣는다. 호출은 명시적
 * 사용자 동작에서만 일어나며, 마운트 시 자동 요청을 만들지 않는다.
 */
export async function declareMaskChild(
  siteId: string,
  workAreaId: string,
  input: MaskChildDeclarationWire,
  options: { signal?: AbortSignal } = {},
): Promise<MaskChildViewWire> {
  const parsed = parseMaskChildDeclaration(input);
  const value = await bffJson("POST", maskInputsPath(siteId, workAreaId), { body: parsed, signal: options.signal });
  return parseMaskChildView(value, { siteId, workAreaId, maskChildId: parsed.maskChildId });
}

/**
 * 자식 상태 조회 — 선언·업로드·검사 상태를 명시적 새로고침으로만 읽는다.
 * manifest가 없으면 검사 대기 중이며, 자동 폴링하지 않는다.
 */
export async function getMaskChild(
  siteId: string,
  workAreaId: string,
  maskChildId: string,
  options: { signal?: AbortSignal } = {},
): Promise<MaskChildViewWire> {
  if (!isOpaqueId(maskChildId)) {
    throw new MaskedRequestError("마스크 식별자 형식이 올바르지 않습니다.");
  }
  const value = await bffJson("GET", maskInputsPath(siteId, workAreaId, maskChildId), { signal: options.signal });
  return parseMaskChildView(value, { siteId, workAreaId, maskChildId });
}

/**
 * 업로드 부여 — 선언과 같은 artifact·subject·선언 값을 메아리한다.
 * 부여는 id·만료만 돌려주며 객체 키·경로·URL을 절대 싣지 않는다.
 */
export async function requestMaskUploadGrant(
  siteId: string,
  workAreaId: string,
  maskChildId: string,
  input: MaskUploadGrantRequestWire,
  options: { signal?: AbortSignal } = {},
): Promise<MaskUploadGrantViewWire> {
  const parsed = parseMaskUploadGrantRequest(input);
  const value = await bffJson(
    "POST",
    `${maskInputsPath(siteId, workAreaId, maskChildId)}/upload-grants`,
    { body: parsed, signal: options.signal },
  );
  return parseMaskUploadGrantView(value, { maskChildId, maskArtifactId: parsed.maskArtifactId });
}

/**
 * 원시 바이트 업로드 — 파일을 그대로 BFF에 싣는다. 브라우저는 바이트를
 * 읽어 해시만 미리 계산하고, TIFF를 복호화하지 않는다. Core가 봉인한
 * 관찰 값을 선언 값과 대조해 되돌려준다.
 */
export async function uploadMaskBytes(
  siteId: string,
  workAreaId: string,
  maskChildId: string,
  grantId: string,
  file: File,
  expected: { maskArtifactId: string; declaredSha256: string; declaredSizeBytes: number },
  options: { signal?: AbortSignal; timeoutMs?: number } = {},
): Promise<MaskUploadSealViewWire> {
  if (!isOpaqueId(maskChildId) || !isBoundedText(grantId, 128)) {
    throw new MaskedRequestError("마스크 식별자 형식이 올바르지 않습니다.");
  }
  if (file.size !== expected.declaredSizeBytes) {
    throw new MaskedRequestError("선택한 파일 크기가 선언 값과 다릅니다. 파일을 다시 선택하세요.");
  }
  if (
    !isOpaqueId(expected.maskArtifactId)
    || !isDigest(expected.declaredSha256)
    || !isPositiveInt(expected.declaredSizeBytes)
  ) {
    throw new MaskedRequestError("업로드 파일 확인 정보가 올바르지 않습니다.");
  }
  const timeoutMs = options.timeoutMs ?? MASKED_UPSTREAM_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const onAbort = () => controller.abort();
  options.signal?.addEventListener("abort", onAbort, { once: true });
  try {
    const response = await fetch(
      `${maskInputsPath(siteId, workAreaId, maskChildId)}/upload-grants/${encodeURIComponent(grantId)}/bytes`,
      {
        method: "POST",
        headers: {
          "content-type": "application/octet-stream",
          "x-masked-artifact-id": expected.maskArtifactId,
          "x-masked-declared-sha256": expected.declaredSha256,
          "x-masked-declared-size-bytes": String(expected.declaredSizeBytes),
        },
        body: file,
        signal: controller.signal,
        cache: "no-store",
      },
    );
    const text = await readBoundedText(response, MASKED_MAX_RESPONSE_JSON_BYTES);
    if (!response.ok) {
      throwForStatus(response.status, text, "마스크 파일 형식이 올바르지 않습니다.");
    }
    let value: unknown;
    try {
      value = JSON.parse(text) as unknown;
    } catch {
      throw new Error("마스크 입력 응답 형식을 확인할 수 없습니다.");
    }
    return parseMaskUploadSealView(value, { maskChildId, ...expected });
  } catch (error) {
    if (
      error instanceof MaskedRequestError
      || error instanceof MaskedNotFoundError
      || error instanceof MaskedForbiddenError
      || error instanceof MaskedConflictError
    ) {
      throw error;
    }
    if (isAbortError(error) || controller.signal.aborted) throw new MaskedUpstreamTimeoutError();
    throw error;
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", onAbort);
  }
}

/**
 * 원본 맥락 — Core `MaskSourceContextViewV1` 와이어 그대로다(10개 닫힌 키).
 * 봉인 subject 사본 + 기준 DSM artifact + 두 프로필 확인값 + 명시적 원시
 * 상한 + 원본 승인 상태. 격자·권한 필드는 절대 싣지 않는다.
 */
export type MaskedSourceContext = {
  sourceCalculationIdentityDigest: string;
  baselineSubject: MaskedSealedSubject;
  currentSubject: MaskedSealedSubject;
  baselineDsmArtifactId: string;
  maskedProfileDigest: string;
  inspectionProfileDigest: string;
  maxMaskBytes: number;
  maxMaskPixels: number;
  sourceDisposition: "ADMIT_PROVISIONAL" | "ADMIT_EVALUATED";
  assessedAt: string;
};

const sourceContextKeys = [
  "sourceCalculationIdentityDigest",
  "baselineSubject",
  "currentSubject",
  "baselineDsmArtifactId",
  "maskedProfileDigest",
  "inspectionProfileDigest",
  "maxMaskBytes",
  "maxMaskPixels",
  "sourceDisposition",
  "assessedAt",
] as const;

export function parseMaskedSourceContext(
  value: unknown,
  scope: { siteId: string; workAreaId: string; sourceCalculationIdentityDigest: string },
): MaskedSourceContext {
  if (!isRecord(value) || !hasExactKeys(value, sourceContextKeys)) {
    throw new Error("원본 맥락 응답 형식을 확인할 수 없습니다.");
  }
  if (
    value.sourceCalculationIdentityDigest !== scope.sourceCalculationIdentityDigest
    || !isOpaqueId(value.baselineDsmArtifactId)
    || !isDigest(value.maskedProfileDigest)
    || !isDigest(value.inspectionProfileDigest)
    || !isPositiveInt(value.maxMaskBytes)
    || !isPositiveInt(value.maxMaskPixels)
    || (value.sourceDisposition !== "ADMIT_PROVISIONAL" && value.sourceDisposition !== "ADMIT_EVALUATED")
    || !isUtcIsoDateTime(value.assessedAt)
    || !isMaskedSealedSubject(value.baselineSubject)
    || !isMaskedSealedSubject(value.currentSubject)
  ) {
    throw new Error("원본 맥락 응답의 요청 범위를 확인할 수 없습니다.");
  }
  // 봉인 subject는 요청 현장에 묶여야 하며 같은 조직이어야 한다.
  // 구역은 Core 쿼리·호출자가 이미 묶었으므로 subject에서 추론하지 않는다.
  // 부모 subject는 기준·현재 어느 쪽에 속해도 된다(서로 다름을 요구하지 않는다).
  const baseline = value.baselineSubject as MaskedSealedSubject;
  const current = value.currentSubject as MaskedSealedSubject;
  if (
    baseline.siteId !== scope.siteId
    || current.siteId !== scope.siteId
    || baseline.organizationId !== current.organizationId
  ) {
    throw new Error("원본 맥락 응답의 요청 범위를 확인할 수 없습니다.");
  }
  return value as unknown as MaskedSourceContext;
}

/**
 * 검사 상태 — Core `MaskInspectionStatusViewV1` 와이어 그대로다(7개 닫힌 키).
 * 봉인 manifest가 있으면 COMPLETED가 이기며, terminal 실패는 사유를 싣는다.
 * manifest 판단은 이 화면이 아니라 Core 파생 상태가 한다.
 */
export type MaskInspectionStatus = "PENDING" | "RUNNING" | "COMPLETED" | "REJECTED" | "FAILED";

export type MaskInspectionReason =
  | "MASK_NODATA_REJECTED"
  | "MASK_BYTES_MISMATCH"
  | "MASK_RESOURCE_EXCEEDED"
  | "MASK_INSPECTION_FAILED";

export type MaskInspectionStatusWire = {
  maskChildId: string;
  siteId: string;
  workAreaId: string;
  status: MaskInspectionStatus;
  reasonCode: MaskInspectionReason | null;
  checkedAt: string;
  manifestDigest: string | null;
};

const inspectionStatusKeys = [
  "maskChildId",
  "siteId",
  "workAreaId",
  "status",
  "reasonCode",
  "checkedAt",
  "manifestDigest",
] as const;

const inspectionReasons: ReadonlySet<string> = new Set([
  "MASK_NODATA_REJECTED",
  "MASK_BYTES_MISMATCH",
  "MASK_RESOURCE_EXCEEDED",
  "MASK_INSPECTION_FAILED",
]);

function isInspectionStatus(value: unknown): value is MaskInspectionStatus {
  return (
    value === "PENDING"
    || value === "RUNNING"
    || value === "COMPLETED"
    || value === "REJECTED"
    || value === "FAILED"
  );
}

export function parseMaskInspectionStatusView(
  value: unknown,
  scope: { siteId: string; workAreaId: string; maskChildId: string },
): MaskInspectionStatusWire {
  if (!isRecord(value) || !hasExactKeys(value, inspectionStatusKeys)) {
    throw new Error("마스크 검사 응답 형식을 확인할 수 없습니다.");
  }
  if (
    value.maskChildId !== scope.maskChildId
    || value.siteId !== scope.siteId
    || value.workAreaId !== scope.workAreaId
    || !isInspectionStatus(value.status)
    || !isUtcIsoDateTime(value.checkedAt)
  ) {
    throw new Error("마스크 검사 응답의 요청 범위를 확인할 수 없습니다.");
  }
  const terminal = value.status === "REJECTED" || value.status === "FAILED";
  const reason = value.reasonCode;
  if (terminal) {
    if (typeof reason !== "string" || !inspectionReasons.has(reason)) {
      throw new Error("마스크 검사 응답 형식을 확인할 수 없습니다.");
    }
  } else if (reason !== null) {
    throw new Error("마스크 검사 응답 형식을 확인할 수 없습니다.");
  }
  // COMPLETED는 봉인 manifest 확인값을 묶어야 하며, 그 외는 묶지 않는다.
  if (value.status === "COMPLETED") {
    if (!isDigest(value.manifestDigest)) {
      throw new Error("마스크 검사 응답 형식을 확인할 수 없습니다.");
    }
  } else if (value.manifestDigest !== null) {
    throw new Error("마스크 검사 응답 형식을 확인할 수 없습니다.");
  }
  return value as unknown as MaskInspectionStatusWire;
}

/** 닫힌 검사 실패 사유를 사람 말로 옮긴다 — 원문 코드는 접어 둔다. */
export function maskInspectionReasonMessage(reason: MaskInspectionReason): string {
  switch (reason) {
    case "MASK_NODATA_REJECTED":
      return "NoData가 있는 마스크는 사용할 수 없습니다. NoData 없이 새 파일을 등록하세요.";
    case "MASK_BYTES_MISMATCH":
      return "마스크의 파일 형식·내용 또는 기준 격자 조건을 확인하지 못했습니다. 0/1 단일 밴드, NoData 없음, 기준 격자 일치를 확인하고 새 파일로 등록하세요.";
    case "MASK_RESOURCE_EXCEEDED":
      return "마스크가 자원 상한을 넘었습니다. 파일을 줄이고 새 자식으로 다시 등록하세요.";
    case "MASK_INSPECTION_FAILED":
      return "마스크 검사가 실패했습니다. 상태를 다시 확인하거나 새 자식으로 다시 등록하세요.";
  }
}

/**
 * 검사 상태 조회 — 명시적 새로고침·복원에서만 호출하는 읽기 전용 GET이다.
 * 자식 조회와 독립적으로 병렬 호출하며 폴링하지 않는다.
 */
export async function getMaskInspectionStatus(
  siteId: string,
  workAreaId: string,
  maskChildId: string,
  options: { signal?: AbortSignal } = {},
): Promise<MaskInspectionStatusWire> {
  if (!isOpaqueId(maskChildId)) {
    throw new MaskedRequestError("마스크 식별자 형식이 올바르지 않습니다.");
  }
  const value = await bffJson(
    "GET",
    `${maskInputsPath(siteId, workAreaId, maskChildId)}/inspection-status`,
    { signal: options.signal },
  );
  return parseMaskInspectionStatusView(value, { siteId, workAreaId, maskChildId });
}

/**
 * 원본 맥락 조회 — 명시적 사용자 동작에서만 호출하는 읽기 전용 GET이다.
 * Core `mask-source-context`의 snake 쿼리를 그대로 싣는다. 자동 POST·
 * 폴링을 만들지 않는다.
 */
export async function getMaskSourceContext(
  siteId: string,
  workAreaId: string,
  sourceCalculationIdentityDigest: string,
  options: { signal?: AbortSignal } = {},
): Promise<MaskedSourceContext> {
  if (!isDigest(sourceCalculationIdentityDigest)) {
    throw new MaskedRequestError("원본 계산 신원 확인값 형식이 올바르지 않습니다.");
  }
  const path = `/api/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/mask-inputs/source-context?source_calculation_identity_digest=${encodeURIComponent(sourceCalculationIdentityDigest)}`;
  const value = await bffJson("GET", path, { signal: options.signal });
  return parseMaskedSourceContext(value, { siteId, workAreaId, sourceCalculationIdentityDigest });
}

/**
 * V3 계산 생성 — 봉인된 원본 계산 신원 확인값 + 마스크 자식만 싣는다.
 * 호출은 명시적 사용자 동작에서만 일어나며, 마운트 시 자동 요청을 만들지 않는다.
 */
export async function createMaskedCalculation(
  siteId: string,
  workAreaId: string,
  input: MaskedCalculationCreateWire,
  options: { signal?: AbortSignal } = {},
): Promise<MaskedCalculationCreatedWire> {
  const parsed = parseMaskedCalculationCreate(input);
  const value = await bffJson("POST", maskedAnalysesPath(siteId, workAreaId), { body: parsed, signal: options.signal });
  return parseMaskedCalculationCreated(value, { siteId, workAreaId });
}

/** V3 화면 조회 — 명시적 새로고침으로만 읽으며 폴링하지 않는다. */
export async function getMaskedCalculation(
  siteId: string,
  workAreaId: string,
  requestId: string,
  options: { signal?: AbortSignal } = {},
): Promise<MaskedCalculationDetailWire> {
  if (!isOpaqueId(requestId)) {
    throw new MaskedRequestError("마스크 계산 식별자 형식이 올바르지 않습니다.");
  }
  const value = await bffJson("GET", maskedAnalysesPath(siteId, workAreaId, requestId), { signal: options.signal });
  return parseMaskedCalculationDetail(value, { siteId, workAreaId, requestId });
}

/** V3 변경 취소 — 명시적 사용자 동작에서만 호출한다. */
export async function cancelMaskedCalculation(
  siteId: string,
  workAreaId: string,
  requestId: string,
  options: { signal?: AbortSignal } = {},
): Promise<MaskedCalculationMutationWire> {
  if (!isOpaqueId(requestId)) {
    throw new MaskedRequestError("마스크 계산 식별자 형식이 올바르지 않습니다.");
  }
  const value = await bffJson("POST", `${maskedAnalysesPath(siteId, workAreaId, requestId)}/cancel`, { signal: options.signal });
  return parseMaskedCalculationMutation(value, { requestId });
}

/**
 * Totally bounded workflow continuity — opaque ids only, never authority.
 *
 * 페이지 새로고침·이동 뒤에도 사용자가 자신의 V3 결과를 되찾을 수 있게,
 * 마지막 현재 작업의 불투명 식별자(`maskChildId`, `requestId`)만
 * sessionStorage에 둔다. 저장되는 것은 키(범위 바인딩)와 불투명 id뿐이다 —
 * 원시 파일·파일명·세션 토큰·URL·격자·작업 내용을 절대 싣지 않는다.
 * 캐시는 권한이 아니다: 복원 읽기는 항상 Core GET으로 현재성을 다시
 * 확인하고, 범위·출처 메아리가 어긋나면 버린다.
 */

export type MaskedContinuityScope = {
  organizationId: string;
  principalId: string;
  siteId: string;
  workAreaId: string;
  sourceCalculationIdentityDigest: string;
};

export type MaskedContinuityRecord = {
  version: 1;
  scope: MaskedContinuityScope;
  maskChildId: string;
  requestId: string | null;
};

const CONTINUITY_KEY_PREFIX = "ksi.masked.continuity.v1:";
const CONTINUITY_MAX_RAW_BYTES = 2_048;
const continuityScopeKeys = [
  "organizationId",
  "principalId",
  "siteId",
  "workAreaId",
  "sourceCalculationIdentityDigest",
] as const;
const continuityRecordKeys = ["version", "scope", "maskChildId", "requestId"] as const;

function isContinuityScope(value: unknown): value is MaskedContinuityScope {
  if (!isRecord(value) || !hasExactKeys(value, continuityScopeKeys)) return false;
  return (
    isScopeId(value.organizationId)
    && isBoundedText(value.principalId, 255)
    && isScopeId(value.siteId)
    && isScopeId(value.workAreaId)
    && isDigest(value.sourceCalculationIdentityDigest)
  );
}

/** 범위당 안정 키 — 사용자·조직·현장·구역·원본이 다르면 키가 다르다. */
export function maskedContinuityKey(scope: MaskedContinuityScope): string {
  if (!isContinuityScope(scope)) {
    throw new MaskedRequestError("마스크 작업 범위가 올바르지 않습니다.");
  }
  return [
    CONTINUITY_KEY_PREFIX,
    encodeURIComponent(scope.organizationId),
    encodeURIComponent(scope.principalId),
    encodeURIComponent(scope.siteId),
    encodeURIComponent(scope.workAreaId),
    encodeURIComponent(scope.sourceCalculationIdentityDigest),
  ].join(":");
}

function continuityStorage(): Storage | null {
  try {
    if (typeof sessionStorage === "undefined") return null;
    return sessionStorage;
  } catch {
    return null;
  }
}

function isContinuityRecord(value: unknown, scope: MaskedContinuityScope): value is MaskedContinuityRecord {
  if (!isRecord(value) || !hasExactKeys(value, continuityRecordKeys)) return false;
  if (value.version !== 1) return false;
  if (!isContinuityScope(value.scope)) return false;
  const inner = value.scope;
  if (
    inner.organizationId !== scope.organizationId
    || inner.principalId !== scope.principalId
    || inner.siteId !== scope.siteId
    || inner.workAreaId !== scope.workAreaId
    || inner.sourceCalculationIdentityDigest !== scope.sourceCalculationIdentityDigest
  ) {
    return false;
  }
  if (!isOpaqueId(value.maskChildId)) return false;
  if (!(value.requestId === null || isOpaqueId(value.requestId))) return false;
  return true;
}

/**
 * 저장된 작업을 읽는다(읽기 전용 — Core 호출 없음). 형식이 어긋나거나
 * 크기를 넘거나 범위와 다르면 지우고 null을 둔다. 없으면 null이다.
 */
export function readMaskedContinuity(scope: MaskedContinuityScope): MaskedContinuityRecord | null {
  let key: string;
  try {
    key = maskedContinuityKey(scope);
  } catch {
    return null;
  }
  const storage = continuityStorage();
  if (!storage) return null;
  let raw: string | null = null;
  try {
    raw = storage.getItem(key);
  } catch {
    return null;
  }
  if (raw === null) return null;
  if (raw.length === 0 || raw.length > CONTINUITY_MAX_RAW_BYTES) {
    try {
      storage.removeItem(key);
    } catch {
      // 지우지 못해도 읽지는 않는다.
    }
    return null;
  }
  let value: unknown = null;
  try {
    value = JSON.parse(raw) as unknown;
  } catch {
    value = null;
  }
  if (!isContinuityRecord(value, scope)) {
    try {
      storage.removeItem(key);
    } catch {
      // 지우지 못해도 읽지는 않는다.
    }
    return null;
  }
  return value;
}

/**
 * Core 수락 뒤에만 저장한다(선언·생성 응답을 받은 뒤 호출). 불투명 id와
 * 범위 키만 싣는다. 저장에 실패하면 false를 둔다(조용히 성공으로 두지 않는다).
 */
export function writeMaskedContinuity(
  scope: MaskedContinuityScope,
  workflow: { maskChildId: string; requestId: string | null },
): boolean {
  let key: string;
  try {
    key = maskedContinuityKey(scope);
  } catch {
    return false;
  }
  if (!isOpaqueId(workflow.maskChildId) || !(workflow.requestId === null || isOpaqueId(workflow.requestId))) {
    return false;
  }
  const storage = continuityStorage();
  if (!storage) return false;
  const record: MaskedContinuityRecord = { version: 1, scope, ...workflow };
  try {
    storage.setItem(key, JSON.stringify(record));
    return storage.getItem(key) === JSON.stringify(record);
  } catch {
    return false;
  }
}

/** 저장된 작업을 지운다(읽지 않는다). */
export function clearMaskedContinuity(scope: MaskedContinuityScope): void {
  let key: string;
  try {
    key = maskedContinuityKey(scope);
  } catch {
    return;
  }
  try {
    continuityStorage()?.removeItem(key);
  } catch {
    // 지우지 못해도 다음 읽기가 버린다.
  }
}
