import { sha256 } from "@noble/hashes/sha2.js";
import { bytesToHex, utf8ToBytes } from "@noble/hashes/utils.js";

export type ExternalArtifactKind = "ortho" | "dsm";

export type ExternalArtifactDeclaration = {
  artifactId: ExternalArtifactKind;
  kind: ExternalArtifactKind;
  fileName: string;
  format: "GeoTIFF";
  contentType: "application/octet-stream";
  declaredSha256: string;
  declaredSizeBytes: number;
  declaredCrs: string | null;
  declaredVerticalReference: null;
  declaredGsdM: null;
};

export type ExternalSubmissionCandidate = {
  contractVersion: "external-reconstruction-submission.v1";
  submissionId: string;
  revision: 1;
  organizationId: string;
  siteId: string;
  observationEpochId: string;
  submittedAt: string;
  submittedBy: string;
  executionResponsibility: "customer_operator";
  executionLocus: "customer_workstation";
  producerDeclaration: {
    softwareName: string;
    softwareVersion: string;
    buildIdentifier: null;
    producerRunIdentifier: null;
    configurationDigest: null;
    completedAt: null;
  };
  inputDeclaration: {
    rawMediaStoredByKsi: false;
    originalRetentionLocus: "customer_workstation";
    localInputManifestDigest: null;
    imageCount: null;
    captureStartedAt: string | null;
    captureEndedAt: string | null;
  };
  artifacts: ExternalArtifactDeclaration[];
  submissionDigest?: string;
};

/**
 * CRS declaration read from a GeoTIFF header (AX-3). Core strips surrounding
 * whitespace before it digests the submission, so only an already-trimmed text
 * keeps the dashboard digest and the Core digest identical.
 */
export function isDeclaredCrs(value: unknown): value is string | null {
  if (value === null) return true;
  if (typeof value !== "string" || value.length === 0 || value.length > 255 || value !== value.trim()) return false;
  assertUtf8SafeString(value);
  return true;
}

export function assertUtf8SafeString(value: string): void {
  try {
    encodeURIComponent(value);
  } catch {
    throw new TypeError("lone surrogate is not valid UTF-8");
  }
}

function validateJsonValue(value: unknown): void {
  if (typeof value === "string") {
    assertUtf8SafeString(value);
    return;
  }
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new TypeError("only safe integer JSON numbers are accepted");
    return;
  }
  if (value === null || typeof value === "boolean") return;
  if (Array.isArray(value)) {
    value.forEach(validateJsonValue);
    return;
  }
  if (typeof value !== "object") throw new TypeError("unsupported canonical JSON value");
  for (const [key, nested] of Object.entries(value)) {
    assertUtf8SafeString(key);
    validateJsonValue(nested);
  }
}

function sortCanonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortCanonical);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right, "en"))
        .map(([key, nested]) => [key, sortCanonical(nested)]),
    );
  }
  return value;
}

export function validateExternalSubmissionCandidate(candidate: ExternalSubmissionCandidate): void {
  validateJsonValue(candidate);
  assertUtf8SafeString(candidate.submissionId);
  if (candidate.revision !== 1 || !candidate.submissionId || !candidate.organizationId || !candidate.siteId) {
    throw new TypeError("external submission must have the fixed first-slice identity fields");
  }
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(candidate.submittedAt)) {
    throw new TypeError("submittedAt must be UTC at whole-second precision");
  }
  const { captureStartedAt, captureEndedAt } = candidate.inputDeclaration;
  if ((captureStartedAt === null) !== (captureEndedAt === null)) {
    throw new TypeError("capture interval must include both start and end");
  }
  if (captureStartedAt !== null && captureEndedAt !== null) {
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(captureStartedAt) ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(captureEndedAt) ||
      !Number.isFinite(Date.parse(captureStartedAt)) ||
      !Number.isFinite(Date.parse(captureEndedAt)) ||
      Date.parse(captureStartedAt) >= Date.parse(captureEndedAt)) {
      throw new TypeError("capture interval must be ordered UTC RFC3339");
    }
  }
  if (candidate.artifacts.filter((artifact) => artifact.kind === "ortho").length !== 1) {
    throw new TypeError("exactly one ortho artifact is required");
  }
  if (candidate.artifacts.length > 2 || new Set(candidate.artifacts.map((artifact) => artifact.kind)).size !== candidate.artifacts.length) {
    throw new TypeError("only one ortho and optional one dsm artifact are supported");
  }
}

/** `datetime-local` has no zone. This form explicitly labels input as Asia/Seoul. */
export function seoulDateTimeLocalToUtc(value: string): string | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value);
  if (!match) return null;
  const [, year, month, day, hour, minute, second = "00"] = match;
  const localMillis = Date.UTC(
    Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute), Number(second),
  );
  const roundTrip = new Date(localMillis);
  if (
    roundTrip.getUTCFullYear() !== Number(year) ||
    roundTrip.getUTCMonth() !== Number(month) - 1 ||
    roundTrip.getUTCDate() !== Number(day) ||
    roundTrip.getUTCHours() !== Number(hour) ||
    roundTrip.getUTCMinutes() !== Number(minute) ||
    roundTrip.getUTCSeconds() !== Number(second)
  ) return null;
  return new Date(localMillis - 9 * 60 * 60 * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
}

export function canonicalSubmissionDigest(candidate: ExternalSubmissionCandidate): string {
  validateExternalSubmissionCandidate(candidate);
  const canonicalCandidate = { ...candidate };
  delete canonicalCandidate.submissionDigest;
  const canonical = sortCanonical({
    ...canonicalCandidate,
    artifacts: [...candidate.artifacts].sort((left, right) => left.artifactId.localeCompare(right.artifactId)),
  });
  return `sha256:${bytesToHex(sha256(utf8ToBytes(JSON.stringify(canonical))))}`;
}

export function sealExternalSubmission(candidate: ExternalSubmissionCandidate): ExternalSubmissionCandidate {
  return { ...candidate, submissionDigest: canonicalSubmissionDigest(candidate) };
}

/**
 * V3 missing-info intake (Human-approved; ADR-KSI-036 D4/D5).
 *
 * New declarations only — V1/V2 builders, routes, digests, and sealed records
 * above are byte-identical and untouched. The wire shape below mirrors
 * contracts/schemas/external-reconstruction-submission.v3.json and the Core
 * parse_external_reconstruction_submission_v3 exact-keys check: every nested
 * object carries all of its fields with explicit nulls, so the canonical
 * digest matches Python V3.digest_for_wire byte-for-byte.
 *
 * Unknowns stay explicit nulls under a declared basis/knowledge — never a
 * midnight timestamp, a "촬영시각없음" invention, or a literal "unknown"
 * version string. Producer PARTIAL keeps a known name with a null version.
 */
export type ExternalV3ProducerKnowledge = "DECLARED" | "PARTIAL" | "UNKNOWN";
export type ExternalV3CaptureBasis = "EXACT_INTERVAL" | "DATE_ONLY" | "UNKNOWN";
export type ExternalV3RetentionLocus = "customer_workstation" | "upstream_source" | "unknown";

export type ExternalV3ProducerDeclaration = {
  producerKnowledge: ExternalV3ProducerKnowledge;
  softwareName: string | null;
  softwareVersion: string | null;
  buildIdentifier: null;
  producerRunIdentifier: null;
  configurationDigest: null;
  completedAt: null;
  sourceNote: string | null;
};

export type ExternalV3UpstreamSource = {
  sourceUri: string;
  sourceSha256: string | null;
  licenceDeclaration: string | null;
  retrievalNote: string | null;
};

export type ExternalV3DerivativeExport = {
  toolName: string;
  toolVersion: string;
  settingsDigest: string | null;
  exportedAt: string | null;
  exportNote: string | null;
};

export type ExternalV3InputDeclaration = {
  rawMediaStoredByKsi: false;
  originalRetentionLocus: ExternalV3RetentionLocus;
  originalRetentionDetail: string | null;
  localInputManifestDigest: null;
  imageCount: null;
  captureStartedAt: string | null;
  captureEndedAt: string | null;
  captureDate: string | null;
  captureBasis: ExternalV3CaptureBasis;
  upstreamSource: ExternalV3UpstreamSource | null;
  derivativeExport: ExternalV3DerivativeExport | null;
};

export type ExternalSubmissionCandidateV3 = {
  contractVersion: "external-reconstruction-submission.v3";
  submissionId: string;
  revision: 1;
  organizationId: string;
  siteId: string;
  observationEpochId: string;
  submittedAt: string;
  submittedBy: string;
  executionResponsibility: "customer_operator";
  executionLocus: "customer_workstation";
  producerDeclaration: ExternalV3ProducerDeclaration;
  inputDeclaration: ExternalV3InputDeclaration;
  artifacts: ExternalArtifactDeclaration[];
  submissionDigest?: string;
};

const V3_PRODUCER_KEYS = ["producerKnowledge", "softwareName", "softwareVersion", "buildIdentifier", "producerRunIdentifier", "configurationDigest", "completedAt", "sourceNote"] as const;
const V3_INPUT_KEYS = ["rawMediaStoredByKsi", "originalRetentionLocus", "originalRetentionDetail", "localInputManifestDigest", "imageCount", "captureStartedAt", "captureEndedAt", "captureDate", "captureBasis", "upstreamSource", "derivativeExport"] as const;
const V3_UPSTREAM_KEYS = ["sourceUri", "sourceSha256", "licenceDeclaration", "retrievalNote"] as const;
const V3_EXPORT_KEYS = ["toolName", "toolVersion", "settingsDigest", "exportedAt", "exportNote"] as const;

/** Python _BoundedText strips; the UI contract below requires the trimmed form so the digest stays stable. */
function requireTrimmedText(value: unknown, maxLength: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maxLength && value === value.trim()
    && (assertUtf8SafeString(value), true);
}

function requireNullableTrimmedText(value: unknown, maxLength: number): value is string | null {
  return value === null || requireTrimmedText(value, maxLength);
}

function isWholeUtcSeconds(value: unknown): value is string {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value) && Number.isFinite(Date.parse(value));
}

/** Calendar date only — no timezone conversion is ever applied to this value. */
export function isPublisherCalendarDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const [year, month, day] = value.split("-").map(Number);
  const probe = new Date(Date.UTC(year!, month! - 1, day!));
  return probe.getUTCFullYear() === year && probe.getUTCMonth() === month! - 1 && probe.getUTCDate() === day;
}

function isFabricatedUnknownLabel(value: string): boolean {
  return value.trim().toLowerCase() === "unknown";
}

function isSafeHttpReference(value: unknown): value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > 1000 || value !== value.trim()) return false;
  try {
    assertUtf8SafeString(value);
  } catch {
    return false;
  }
  if ([...value].some((char) => char <= " " || char === "\x7f")) return false;
  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    return false;
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
  if (parsed.username !== "" || parsed.password !== "") return false;
  return parsed.hostname.length > 0;
}

function validateV3Producer(declaration: ExternalV3ProducerDeclaration): void {
  if (!declaration || typeof declaration !== "object" || !hasExactV3Keys(declaration, V3_PRODUCER_KEYS)) {
    throw new TypeError("V3 producer declaration must carry the exact versioned fields");
  }
  const { producerKnowledge, softwareName, softwareVersion, sourceNote } = declaration;
  if (producerKnowledge !== "DECLARED" && producerKnowledge !== "PARTIAL" && producerKnowledge !== "UNKNOWN") {
    throw new TypeError("producerKnowledge must be DECLARED, PARTIAL, or UNKNOWN");
  }
  if (declaration.buildIdentifier !== null || declaration.producerRunIdentifier !== null || declaration.configurationDigest !== null || declaration.completedAt !== null) {
    throw new TypeError("console declarations never set producer build, run, digest, or completion facts");
  }
  if (!requireNullableTrimmedText(sourceNote, 1000)) throw new TypeError("sourceNote must be null or bounded text");
  if (producerKnowledge === "UNKNOWN") {
    if (softwareName !== null || softwareVersion !== null) throw new TypeError("unknown producer must not carry software name/version");
  } else if (producerKnowledge === "PARTIAL") {
    if (!requireTrimmedText(softwareName, 255) || softwareVersion !== null) {
      throw new TypeError("partial producer keeps the known software name with a null version");
    }
    if (isFabricatedUnknownLabel(softwareName)) throw new TypeError("softwareName must not be the fabricated label 'unknown'");
  } else {
    if (!requireTrimmedText(softwareName, 255) || !requireTrimmedText(softwareVersion, 255)) {
      throw new TypeError("declared producer requires software name and version");
    }
    if (isFabricatedUnknownLabel(softwareName) || isFabricatedUnknownLabel(softwareVersion)) {
      throw new TypeError("producer fields must not be the fabricated label 'unknown'");
    }
  }
}

function validateV3UpstreamSource(value: ExternalV3UpstreamSource | null): void {
  if (value === null) return;
  if (!value || typeof value !== "object" || !hasExactV3Keys(value, V3_UPSTREAM_KEYS)) {
    throw new TypeError("upstream source must carry the exact versioned fields");
  }
  // Never echo the supplied value: rejection keeps the generic reason only.
  if (!isSafeHttpReference(value.sourceUri)) throw new TypeError("upstream source must be a safe http(s) reference");
  if (value.sourceSha256 !== null && (typeof value.sourceSha256 !== "string" || !/^[0-9a-f]{64}$/.test(value.sourceSha256))) {
    throw new TypeError("upstream source sha must be 64 lowercase hex or null");
  }
  if (!requireNullableTrimmedText(value.licenceDeclaration, 1000) || !requireNullableTrimmedText(value.retrievalNote, 1000)) {
    throw new TypeError("upstream licence and retrieval notes must be null or bounded text");
  }
}

function validateV3DerivativeExport(value: ExternalV3DerivativeExport | null): void {
  if (value === null) return;
  if (!value || typeof value !== "object" || !hasExactV3Keys(value, V3_EXPORT_KEYS)) {
    throw new TypeError("derivative export must carry the exact versioned fields");
  }
  if (!requireTrimmedText(value.toolName, 255) || !requireTrimmedText(value.toolVersion, 255)) {
    throw new TypeError("derivative export requires tool name and version");
  }
  if (isFabricatedUnknownLabel(value.toolName)) throw new TypeError("export tool must not be the fabricated label 'unknown'");
  if (value.settingsDigest !== null && (typeof value.settingsDigest !== "string" || !/^sha256:[0-9a-f]{64}$/.test(value.settingsDigest))) {
    throw new TypeError("export settings digest must be a sha256 digest or null");
  }
  if (value.exportedAt !== null && !isWholeUtcSeconds(value.exportedAt)) {
    throw new TypeError("exportedAt must be whole UTC seconds or null");
  }
  if (!requireNullableTrimmedText(value.exportNote, 1000)) throw new TypeError("export note must be null or bounded text");
}

function validateV3Input(declaration: ExternalV3InputDeclaration): void {
  if (!declaration || typeof declaration !== "object" || !hasExactV3Keys(declaration, V3_INPUT_KEYS)) {
    throw new TypeError("V3 input declaration must carry the exact versioned fields");
  }
  if ((declaration.rawMediaStoredByKsi as unknown) !== false) throw new TypeError("rawMediaStoredByKsi must be the boolean false");
  if (declaration.originalRetentionLocus !== "customer_workstation" && declaration.originalRetentionLocus !== "upstream_source" && declaration.originalRetentionLocus !== "unknown") {
    throw new TypeError("original retention locus must be declared");
  }
  if (!requireNullableTrimmedText(declaration.originalRetentionDetail, 1000)) {
    throw new TypeError("original retention detail must be null or bounded text");
  }
  if (declaration.localInputManifestDigest !== null || declaration.imageCount !== null) {
    throw new TypeError("console declarations never set manifest digest or image count facts");
  }
  const { captureBasis, captureStartedAt, captureEndedAt, captureDate } = declaration;
  if (captureBasis === "EXACT_INTERVAL") {
    if (captureDate !== null || !isWholeUtcSeconds(captureStartedAt) || !isWholeUtcSeconds(captureEndedAt) || Date.parse(captureStartedAt) >= Date.parse(captureEndedAt)) {
      throw new TypeError("EXACT_INTERVAL requires an ordered UTC pair and no calendar date");
    }
  } else if (captureBasis === "DATE_ONLY") {
    // No midnight invention: timestamps stay null, the calendar date stands alone.
    if (!isPublisherCalendarDate(captureDate) || captureStartedAt !== null || captureEndedAt !== null) {
      throw new TypeError("DATE_ONLY requires a calendar date and no timestamps");
    }
  } else if (captureBasis === "UNKNOWN") {
    if (captureDate !== null || captureStartedAt !== null || captureEndedAt !== null) {
      throw new TypeError("UNKNOWN capture must not carry any date or timestamps");
    }
  } else {
    throw new TypeError("captureBasis must be EXACT_INTERVAL, DATE_ONLY, or UNKNOWN");
  }
  validateV3UpstreamSource(declaration.upstreamSource);
  validateV3DerivativeExport(declaration.derivativeExport);
}

function hasExactV3Keys(value: object, keys: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && actual.every((key) => keys.includes(key));
}

export function validateExternalSubmissionV3Candidate(candidate: ExternalSubmissionCandidateV3): void {
  validateJsonValue(candidate);
  if (candidate.contractVersion !== "external-reconstruction-submission.v3") throw new TypeError("contractVersion must be external-reconstruction-submission.v3");
  assertUtf8SafeString(candidate.submissionId);
  if (candidate.revision !== 1 || !candidate.submissionId || !candidate.organizationId || !candidate.siteId || !candidate.observationEpochId) {
    throw new TypeError("external V3 submission must have the fixed first-slice identity fields");
  }
  if (!isWholeUtcSeconds(candidate.submittedAt)) throw new TypeError("submittedAt must be UTC at whole-second precision");
  validateV3Producer(candidate.producerDeclaration);
  validateV3Input(candidate.inputDeclaration);
  const artifacts = candidate.artifacts;
  if (!Array.isArray(artifacts) || artifacts.length < 1 || artifacts.length > 8) {
    throw new TypeError("V3 requires one to eight artifacts");
  }
  const kinds = artifacts.map((artifact) => artifact.kind);
  if (!kinds.every((kind) => kind === "ortho" || kind === "dsm")) throw new TypeError("V3 artifacts must be ortho or dsm");
  if (kinds.filter((kind) => kind === "ortho").length > 1 || kinds.filter((kind) => kind === "dsm").length > 1) {
    throw new TypeError("V3 allows at most one ortho and at most one dsm");
  }
  if (!kinds.includes("ortho") && !kinds.includes("dsm")) throw new TypeError("V3 requires an ortho or a dsm artifact");
  if (new Set(artifacts.map((artifact) => artifact.artifactId)).size !== artifacts.length) {
    throw new TypeError("artifactId values must be unique");
  }
  for (const artifact of artifacts) {
    if (!artifact || typeof artifact !== "object" || artifact.artifactId !== artifact.kind || !requireTrimmedText(artifact.fileName, 255)) {
      throw new TypeError("V3 artifact must bind one kind to its file");
    }
    if (typeof artifact.declaredSha256 !== "string" || !/^[0-9a-f]{64}$/.test(artifact.declaredSha256) || !Number.isSafeInteger(artifact.declaredSizeBytes) || artifact.declaredSizeBytes <= 0) {
      throw new TypeError("V3 artifact digest and size must be exact");
    }
    if (artifact.format !== "GeoTIFF" || artifact.contentType !== "application/octet-stream" || !isDeclaredCrs(artifact.declaredCrs) || artifact.declaredVerticalReference !== null || artifact.declaredGsdM !== null) {
      throw new TypeError("V3 artifact carries declared bytes only, never measured facts");
    }
  }
}

/** Code-point key order matches Python json.dumps(sort_keys=True); V1 keeps its own comparator untouched. */
function sortCanonicalV3(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortCanonicalV3);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
        .map(([key, nested]) => [key, sortCanonicalV3(nested)]),
    );
  }
  return value;
}

export function canonicalSubmissionV3Digest(candidate: ExternalSubmissionCandidateV3): string {
  validateExternalSubmissionV3Candidate(candidate);
  const canonicalCandidate = { ...candidate };
  delete canonicalCandidate.submissionDigest;
  const canonical = sortCanonicalV3({
    ...canonicalCandidate,
    artifacts: [...candidate.artifacts].sort((left, right) => (left.artifactId < right.artifactId ? -1 : left.artifactId > right.artifactId ? 1 : 0)),
  });
  return `sha256:${bytesToHex(sha256(utf8ToBytes(JSON.stringify(canonical))))}`;
}

export function sealExternalSubmissionV3(candidate: ExternalSubmissionCandidateV3): ExternalSubmissionCandidateV3 {
  return { ...candidate, submissionDigest: canonicalSubmissionV3Digest(candidate) };
}

export type V3MetadataForm = {
  producerKnowledge: ExternalV3ProducerKnowledge;
  softwareName: string;
  softwareVersion: string;
  sourceNote: string;
  captureBasis: ExternalV3CaptureBasis;
  captureDateLocal: string;
  upstreamUri: string;
  upstreamSha: string;
  exportToolName: string;
  exportToolVersion: string;
  exportSettingsDigest: string;
  exportedAtLocal: string;
  exportNote: string;
};

/**
 * 제출 전 클라이언트 안내용. BFF·Core가 다시 검증하므로 여기는 문구만 둔다.
 * 값 자체(특히 URI)는 오류 문구에 그대로 두지 않는다.
 */
export function describeV3MetadataIssue(input: V3MetadataForm): string | null {
  const name = input.softwareName.trim();
  const version = input.softwareVersion.trim();
  if (input.producerKnowledge === "UNKNOWN") {
    if (name !== "" || version !== "") return "재구성 소프트웨어를 미상으로 선택하면 이름과 버전을 비워 두세요.";
  } else if (input.producerKnowledge === "PARTIAL") {
    if (name === "") return "이름만 아는 경우 소프트웨어 이름을 입력하세요.";
    if (version !== "") return "이름만 아는 경우 버전을 비워 두세요.";
    if (isFabricatedUnknownLabel(name)) return "소프트웨어 이름에 'unknown'이라고 쓰지 마세요. 미상이면 미상을 선택하세요.";
  } else {
    if (name === "" || version === "") return "재구성 소프트웨어 이름과 버전을 입력하거나, 미상 방식을 선택하세요.";
    if (isFabricatedUnknownLabel(name) || isFabricatedUnknownLabel(version)) return "소프트웨어 이름·버전에 'unknown'이라고 쓰지 마세요. 미상이면 미상을 선택하세요.";
  }
  if (input.sourceNote.trim().length > 1000) return "출처 기록은 1,000자 이내로 입력하세요.";
  if (input.captureBasis === "DATE_ONLY" && !isPublisherCalendarDate(input.captureDateLocal)) {
    return "촬영 날짜만 아는 경우 YYYY-MM-DD 형식의 날짜를 입력하세요.";
  }
  const uri = input.upstreamUri.trim();
  if (uri !== "") {
    if (!isSafeHttpReference(uri)) return "공개 출처 주소가 올바르지 않습니다. http(s) 주소를 그대로 입력하세요.";
    const sha = input.upstreamSha.trim();
    if (sha !== "" && !/^[0-9a-f]{64}$/.test(sha)) return "원본 확인값은 64자리 소문자 16진수이거나 비워 두세요.";
  }
  const toolName = input.exportToolName.trim();
  const toolVersion = input.exportToolVersion.trim();
  if (toolName !== "" || toolVersion !== "" || input.exportSettingsDigest.trim() !== "" || input.exportedAtLocal !== "" || input.exportNote.trim() !== "") {
    if (toolName === "" || toolVersion === "") return "내보내기 도구를 적으면 이름과 버전을 함께 입력하세요.";
    if (isFabricatedUnknownLabel(toolName)) return "내보내기 도구 이름에 'unknown'이라고 쓰지 마세요. 모르면 비워 두세요.";
    const digest = input.exportSettingsDigest.trim();
    if (digest !== "" && !/^sha256:[0-9a-f]{64}$/.test(digest)) return "내보내기 설정 확인값은 sha256: 뒤 64자리 소문자 16진수이거나 비워 두세요.";
    if (input.exportedAtLocal !== "" && seoulDateTimeLocalToUtc(input.exportedAtLocal) === null) {
      return "내보내기 시각을 입력하면 한국 표준시로 읽을 수 있는 값이어야 합니다.";
    }
  }
  return null;
}
