/**
 * 선택한 자산에 묶인 제출서 revision의 표시용 검증 — 순수 함수만 둔다.
 *
 * Core revision GET이 돌려주는 submission은 버전별 wire dict(v1 또는 v3)다.
 * 여기서 계약 버전을 확인하고, 선택한 자산·세션의 귀속(ref/revision/site/org/
 * epoch)과 표시할 선언값의 모양을 검증한 뒤에만 화면이 쓴다. 판정·측정·
 * 권한 판단은 하지 않으며, Core 원시 오류도 밖으로 내보내지 않는다.
 */

export interface RegistrationHistoryBindings {
  submissionRef: string;
  revision: number;
  siteId: string;
  organizationId: string;
  observationEpochId: string;
}

export interface ValidatedUpstreamSource {
  sourceUri: string | null;
  sourceSha256: string | null;
  licenceDeclaration: string | null;
  retrievalNote: string | null;
}

export interface ValidatedDerivativeExport {
  toolName: string;
  toolVersion: string;
  settingsDigest: string | null;
  exportedAt: string | null;
  exportNote: string | null;
}

export interface ValidatedRegistrationHistory {
  submissionRef: string;
  revision: number;
  state: "REGISTERED" | "SEALED";
  captureBasis: "EXACT_INTERVAL" | "DATE_ONLY" | "UNKNOWN";
  captureStartedAt: string | null;
  captureEndedAt: string | null;
  captureDate: string | null;
  producerKnowledge: "DECLARED" | "PARTIAL" | "UNKNOWN";
  softwareName: string | null;
  softwareVersion: string | null;
  sourceNote: string | null;
  originalRetentionLocus: "customer_workstation" | "upstream_source" | "unknown";
  originalRetentionDetail: string | null;
  upstreamSource: ValidatedUpstreamSource | null;
  derivativeExport: ValidatedDerivativeExport | null;
}

export type RegistrationHistoryResult =
  /** V3 제출서 — 읽은 그대로 표시한다. 구버전에는 아무것도 덧붙이지 않는다. */
  | { kind: "v3"; history: ValidatedRegistrationHistory }
  /** V1/V2 등 구버전 — 기존 표시 그대로 둔다. */
  | { kind: "legacy" }
  /** 조회 실패·귀속 불일치·모양 오류 — 파일 사실은 두고 사유 누설 없이 알린다. */
  | { kind: "unavailable" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function assertUtf8Safe(value: string): boolean {
  try {
    encodeURIComponent(value);
    return true;
  } catch {
    return false;
  }
}

/** 표시용 bounded text — 앞뒤 공백·빈 문자열·제어문자를 거부한다. */
function boundedText(value: unknown, maxLength: number): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || value.length === 0 || value.length > maxLength || value !== value.trim()) return null;
  if (!assertUtf8Safe(value)) return null;
  if ([...value].some((char) => char < " " || char === "\x7f")) return null;
  return value;
}

function awareTimestamp(value: unknown): string | null {
  // Core serializes real microseconds and explicit UTC offsets as well as Z.
  // A read projection must not require the UI builder's whole-second spelling.
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(value)) return null;
  return calendarDate(value.slice(0, 10)) && Number.isFinite(Date.parse(value)) ? value : null;
}

function timestampMicros(value: string): bigint {
  const fraction = /\.(\d+)(?:Z|[+-])/.exec(value)?.[1] ?? "";
  const remainder = Number(fraction.padEnd(6, "0").slice(3, 6));
  return BigInt(Date.parse(value)) * BigInt(1000) + BigInt(remainder);
}

function hex64(value: unknown): string | null {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value) ? value : null;
}

function sha256Digest(value: unknown): string | null {
  return typeof value === "string" && /^sha256:[0-9a-f]{64}$/.test(value) ? value : null;
}

/** 화면 링크용 http(s) — 자격증명·공백·제어문자를 거부한다. 자동 조회에는 쓰지 않는다. */
export function isDisplayableHttpUrl(value: unknown): value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > 1000 || value !== value.trim()) return false;
  if (!assertUtf8Safe(value)) return false;
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

function calendarDate(value: unknown): string | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const [year, month, day] = value.split("-").map(Number);
  if (!Number.isSafeInteger(year) || !Number.isSafeInteger(month) || !Number.isSafeInteger(day)) return null;
  if (year! < 1) return null;
  const probe = new Date(0);
  probe.setUTCFullYear(year!, month! - 1, day!);
  probe.setUTCHours(0, 0, 0, 0);
  return probe.getUTCFullYear() === year && probe.getUTCMonth() === month! - 1 && probe.getUTCDate() === day
    ? value
    : null;
}

function notUnknownLabel(value: string): boolean {
  return value.trim().toLowerCase() !== "unknown";
}

function validUpstream(value: unknown): ValidatedUpstreamSource | "invalid" | null {
  if (value === null) return null;
  if (!isRecord(value)) return null;
  const sourceUri = isDisplayableHttpUrl(value.sourceUri) ? value.sourceUri : null;
  const sourceSha256 = value.sourceSha256 === null ? null : hex64(value.sourceSha256);
  const licenceDeclaration = value.licenceDeclaration === null ? null : boundedText(value.licenceDeclaration, 1000);
  const retrievalNote = value.retrievalNote === null ? null : boundedText(value.retrievalNote, 1000);
  if (value.sourceSha256 !== null && sourceSha256 === null) return "invalid";
  if (value.licenceDeclaration !== null && licenceDeclaration === null) return "invalid";
  if (value.retrievalNote !== null && retrievalNote === null) return "invalid";
  if (sourceUri === null && sourceSha256 === null && licenceDeclaration === null && retrievalNote === null) return null;
  return { sourceUri, sourceSha256, licenceDeclaration, retrievalNote };
}

function validExport(value: unknown): ValidatedDerivativeExport | "invalid" | null {
  if (value === null) return null;
  if (!isRecord(value)) return null;
  const toolName = boundedText(value.toolName, 255);
  const toolVersion = boundedText(value.toolVersion, 255);
  if (toolName === null || toolVersion === null || !notUnknownLabel(toolName)) return "invalid";
  const settingsDigest = value.settingsDigest === null ? null : sha256Digest(value.settingsDigest);
  const exportedAt = value.exportedAt === null ? null : awareTimestamp(value.exportedAt);
  const exportNote = value.exportNote === null ? null : boundedText(value.exportNote, 1000);
  if (value.settingsDigest !== null && settingsDigest === null) return "invalid";
  if (value.exportedAt !== null && exportedAt === null) return "invalid";
  if (value.exportNote !== null && exportNote === null) return "invalid";
  return { toolName, toolVersion, settingsDigest, exportedAt, exportNote };
}

/**
 * revision GET 1건의 원문을 선택 자산·세션 귀속과 대조해 표시용으로 굳힌다.
 * V3가 아니면 legacy, 조회 실패·불일치·모양 오류는 unavailable이다.
 */
export function validateRegistrationHistory(
  record: unknown,
  expected: RegistrationHistoryBindings,
): RegistrationHistoryResult {
  if (!isRecord(record)) return { kind: "unavailable" };
  if (record.submissionRef !== expected.submissionRef) return { kind: "unavailable" };
  if (record.state !== "REGISTERED" && record.state !== "SEALED") return { kind: "unavailable" };
  if (!isRecord(record.submission)) return { kind: "unavailable" };
  const submission = record.submission;
  if (submission.contractVersion !== "external-reconstruction-submission.v3") return { kind: "legacy" };
  if (submission.revision !== expected.revision) return { kind: "unavailable" };
  if (submission.siteId !== expected.siteId) return { kind: "unavailable" };
  if (submission.organizationId !== expected.organizationId) return { kind: "unavailable" };
  if (submission.observationEpochId !== expected.observationEpochId) return { kind: "unavailable" };
  if (typeof submission.submissionId !== "string" || submission.submissionId.length < 1 || submission.submissionId.length > 255) {
    return { kind: "unavailable" };
  }

  const producer = submission.producerDeclaration;
  if (!isRecord(producer)) return { kind: "unavailable" };
  if (producer.producerKnowledge !== "DECLARED" && producer.producerKnowledge !== "PARTIAL" && producer.producerKnowledge !== "UNKNOWN") {
    return { kind: "unavailable" };
  }
  const softwareName = producer.softwareName === null ? null : boundedText(producer.softwareName, 255);
  const softwareVersion = producer.softwareVersion === null ? null : boundedText(producer.softwareVersion, 255);
  const sourceNote = producer.sourceNote === null ? null : boundedText(producer.sourceNote, 1000);
  if (producer.softwareName !== null && softwareName === null) return { kind: "unavailable" };
  if (producer.softwareVersion !== null && softwareVersion === null) return { kind: "unavailable" };
  if (producer.sourceNote !== null && sourceNote === null) return { kind: "unavailable" };

  const input = submission.inputDeclaration;
  if (!isRecord(input)) return { kind: "unavailable" };
  if (input.rawMediaStoredByKsi !== false) return { kind: "unavailable" };
  if (input.originalRetentionLocus !== "customer_workstation"
    && input.originalRetentionLocus !== "upstream_source"
    && input.originalRetentionLocus !== "unknown") {
    return { kind: "unavailable" };
  }
  const originalRetentionDetail = input.originalRetentionDetail === null ? null : boundedText(input.originalRetentionDetail, 1000);
  if (input.originalRetentionDetail !== null && originalRetentionDetail === null) return { kind: "unavailable" };
  if (input.captureBasis !== "EXACT_INTERVAL" && input.captureBasis !== "DATE_ONLY" && input.captureBasis !== "UNKNOWN") {
    return { kind: "unavailable" };
  }
  const captureStartedAt = input.captureStartedAt === null ? null : awareTimestamp(input.captureStartedAt);
  const captureEndedAt = input.captureEndedAt === null ? null : awareTimestamp(input.captureEndedAt);
  const captureDate = input.captureDate === null ? null : calendarDate(input.captureDate);
  if (input.captureStartedAt !== null && captureStartedAt === null) return { kind: "unavailable" };
  if (input.captureEndedAt !== null && captureEndedAt === null) return { kind: "unavailable" };
  if (input.captureDate !== null && captureDate === null) return { kind: "unavailable" };
  if (producer.producerKnowledge === "UNKNOWN" && (softwareName !== null || softwareVersion !== null)) return { kind: "unavailable" };
  if (producer.producerKnowledge === "PARTIAL" && (softwareName === null || softwareVersion !== null)) return { kind: "unavailable" };
  if (producer.producerKnowledge === "DECLARED" && (softwareName === null || softwareVersion === null)) return { kind: "unavailable" };
  if ((softwareName && !notUnknownLabel(softwareName)) || (softwareVersion && !notUnknownLabel(softwareVersion))) return { kind: "unavailable" };
  if (input.captureBasis === "DATE_ONLY" && (captureDate === null || captureStartedAt !== null || captureEndedAt !== null)) return { kind: "unavailable" };
  if (input.captureBasis === "UNKNOWN" && (captureDate !== null || captureStartedAt !== null || captureEndedAt !== null)) return { kind: "unavailable" };
  if (input.captureBasis === "EXACT_INTERVAL" && (captureDate !== null || captureStartedAt === null || captureEndedAt === null || timestampMicros(captureEndedAt) <= timestampMicros(captureStartedAt))) return { kind: "unavailable" };
  const upstreamSource = validUpstream(input.upstreamSource);
  const derivativeExport = validExport(input.derivativeExport);
  if (upstreamSource === "invalid" || derivativeExport === "invalid") return { kind: "unavailable" };

  return {
    kind: "v3",
    history: {
      submissionRef: expected.submissionRef,
      revision: expected.revision,
      state: record.state,
      captureBasis: input.captureBasis,
      captureStartedAt,
      captureEndedAt,
      captureDate,
      producerKnowledge: producer.producerKnowledge,
      softwareName,
      softwareVersion,
      sourceNote,
      originalRetentionLocus: input.originalRetentionLocus,
      originalRetentionDetail,
      upstreamSource,
      derivativeExport,
    },
  };
}
