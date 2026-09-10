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
  declaredCrs: null;
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
