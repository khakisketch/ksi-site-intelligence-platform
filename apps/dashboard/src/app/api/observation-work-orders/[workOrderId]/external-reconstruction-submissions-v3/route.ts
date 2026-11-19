import { NextRequest, NextResponse } from "next/server";
import { CoreApiError, coreFetchWithToken } from "@/lib/core-api/client";
import { getExternalReconstructionContextWithToken, listExternalReconstructionSubmissionsWithToken, registerExternalReconstructionSubmissionV3WithToken } from "@/lib/core-api/external-reconstruction";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { getSessionToken } from "@/lib/core-api/session";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import type { ObservationWorkOrderView } from "@/lib/core-api/types";
import {
  ACCOUNT_CONTINUITY_MISMATCH,
  fetchCurrentContinuityIdentity,
  isSameContinuity,
  parseContinuityClaim,
} from "@/lib/core-api/work-order-continuity";
import { assertUtf8SafeString, canonicalSubmissionV3Digest, isDeclaredCrs, isPublisherCalendarDate, type ExternalArtifactDeclaration, type ExternalSubmissionCandidateV3, type ExternalV3CaptureBasis, type ExternalV3ProducerKnowledge, type ExternalV3RetentionLocus } from "@/lib/external-reconstruction-submission";
import { registrationInstantMicros } from "@/lib/registration-history";

const MAX_DECLARATION_BYTES = 1024 * 1024;

class PayloadTooLargeError extends Error {}

function errorResponse(error: unknown) {
  if (error instanceof PayloadTooLargeError) return NextResponse.json({ code: "EXTERNAL_RECONSTRUCTION_BODY_TOO_LARGE" }, { status: 413 });
  if (error instanceof CoreApiError) return NextResponse.json({ code: error.code, detail: error.serverMessage }, { status: error.status });
  return NextResponse.json({ code: "INVALID_EXTERNAL_RECONSTRUCTION_REQUEST" }, { status: 400 });
}

function correctionLineageChangedResponse() {
  return NextResponse.json({
    code: "CORRECTION_LINEAGE_CHANGED",
    message: "원자료·촬영·제작 정보가 기존 등록과 달라 실행 기록을 이어 붙이지 않았습니다. 수정 정보와 원자료를 확인해 주세요.",
  }, { status: 409, headers: { "Cache-Control": "private, no-store" } });
}

function boundedText(value: unknown): value is string {
  if (typeof value !== "string" || value.trim().length === 0 || value.length > 255 || value !== value.trim()) return false;
  assertUtf8SafeString(value);
  return true;
}

function nullableBoundedText(value: unknown, maxLength: number): value is string | null {
  if (value === null) return true;
  if (typeof value !== "string" || value.trim().length === 0 || value.length > maxLength || value !== value.trim()) return false;
  assertUtf8SafeString(value);
  return true;
}

function hasExactKeys(value: object, keys: readonly string[]): boolean {
  const actual = Object.keys(value);
  return actual.length === keys.length && actual.every((key) => keys.includes(key));
}

async function readBoundedJson(request: NextRequest): Promise<unknown> {
  const contentLength = request.headers.get("content-length");
  if (contentLength !== null) {
    if (!/^\d+$/.test(contentLength)) throw new TypeError("content length must be decimal");
    const declaredBytes = Number(contentLength);
    if (!Number.isSafeInteger(declaredBytes)) throw new TypeError("content length must be safe");
    if (declaredBytes > MAX_DECLARATION_BYTES) throw new PayloadTooLargeError();
  }
  if (!request.body) throw new TypeError("request body is required");

  const reader = request.body.getReader();
  const decoder = new TextDecoder("utf-8", { fatal: true });
  let totalBytes = 0;
  let text = "";
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      totalBytes += next.value.byteLength;
      if (totalBytes > MAX_DECLARATION_BYTES) {
        await reader.cancel();
        throw new PayloadTooLargeError();
      }
      text += decoder.decode(next.value, { stream: true });
    }
    text += decoder.decode();
  } finally {
    reader.releaseLock();
  }
  return JSON.parse(text);
}

function isFabricatedUnknownLabel(value: string): boolean {
  return value.toLowerCase() === "unknown";
}

function isSafeHttpReference(value: unknown): boolean {
  if (typeof value !== "string" || value.length === 0 || value.length > 1000 || value !== value.trim()) return false;
  assertUtf8SafeString(value);
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

type V3Body = {
  submissionId: string; expectedEpochId: string; submittedAt: string;
  correctionOf?: { submissionRef: string; revision: number };
  producerKnowledge: ExternalV3ProducerKnowledge; softwareName: string | null; softwareVersion: string | null; sourceNote: string | null;
  captureBasis: ExternalV3CaptureBasis; captureStartedAt: string | null; captureEndedAt: string | null; captureDate: string | null;
  originalRetentionLocus: ExternalV3RetentionLocus; originalRetentionDetail: string | null;
  upstreamSource: { sourceUri: string; sourceSha256: string | null; licenceDeclaration: string | null; retrievalNote: string | null } | null;
  derivativeExport: { toolName: string; toolVersion: string; settingsDigest: string | null; exportedAt: string | null; exportNote: string | null } | null;
  artifacts: ExternalArtifactDeclaration[];
};

function parseUpstreamSource(value: unknown): V3Body["upstreamSource"] {
  if (value === null) return null;
  if (!value || typeof value !== "object" || !hasExactKeys(value, ["sourceUri", "sourceSha256", "licenceDeclaration", "retrievalNote"])) {
    throw new TypeError("upstream source must carry the exact versioned fields");
  }
  const source = value as Record<string, unknown>;
  // Never echo the supplied URI: generic rejection only.
  if (!isSafeHttpReference(source.sourceUri)) throw new TypeError("upstream source must be a safe http(s) reference");
  if (source.sourceSha256 !== null && (typeof source.sourceSha256 !== "string" || !/^[0-9a-f]{64}$/.test(source.sourceSha256))) {
    throw new TypeError("upstream source sha must be 64 lowercase hex or null");
  }
  if (!nullableBoundedText(source.licenceDeclaration, 1000) || !nullableBoundedText(source.retrievalNote, 1000)) {
    throw new TypeError("upstream licence and retrieval notes must be null or bounded text");
  }
  return {
    sourceUri: (source.sourceUri as string).trim(),
    sourceSha256: source.sourceSha256 as string | null,
    licenceDeclaration: source.licenceDeclaration as string | null,
    retrievalNote: source.retrievalNote as string | null,
  };
}

function parseDerivativeExport(value: unknown): V3Body["derivativeExport"] {
  if (value === null) return null;
  if (!value || typeof value !== "object" || !hasExactKeys(value, ["toolName", "toolVersion", "settingsDigest", "exportedAt", "exportNote"])) {
    throw new TypeError("derivative export must carry the exact versioned fields");
  }
  const block = value as Record<string, unknown>;
  if (!boundedText(block.toolName) || !boundedText(block.toolVersion) || isFabricatedUnknownLabel(block.toolName as string)) {
    throw new TypeError("derivative export requires an honest tool name and version");
  }
  if (block.settingsDigest !== null && (typeof block.settingsDigest !== "string" || !/^sha256:[0-9a-f]{64}$/.test(block.settingsDigest))) {
    throw new TypeError("export settings digest must be a sha256 digest or null");
  }
  if (block.exportedAt !== null && (typeof block.exportedAt !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(block.exportedAt) || !Number.isFinite(Date.parse(block.exportedAt)))) {
    throw new TypeError("exportedAt must be whole UTC seconds or null");
  }
  if (!nullableBoundedText(block.exportNote, 1000)) throw new TypeError("export note must be null or bounded text");
  return {
    toolName: (block.toolName as string).trim(),
    toolVersion: (block.toolVersion as string).trim(),
    settingsDigest: block.settingsDigest as string | null,
    exportedAt: block.exportedAt as string | null,
    exportNote: block.exportNote as string | null,
  };
}

function parseBody(value: unknown): V3Body {
  if (!value || typeof value !== "object") throw new TypeError("body must be an object");
  const body = value as Record<string, unknown>;
  const declarationKeys = ["submissionId", "expectedEpochId", "submittedAt", "producerKnowledge", "softwareName", "softwareVersion", "sourceNote", "captureBasis", "captureStartedAt", "captureEndedAt", "captureDate", "originalRetentionLocus", "originalRetentionDetail", "upstreamSource", "derivativeExport", "artifacts"] as const;
  const correctionOf = body.correctionOf;
  if (
    !hasExactKeys(body, correctionOf === undefined ? declarationKeys : [...declarationKeys, "correctionOf"])
    || !boundedText(body.submissionId)
    || !boundedText(body.expectedEpochId)
    || typeof body.submittedAt !== "string"
    || !Array.isArray(body.artifacts)
  ) {
    throw new TypeError("required V3 declaration fields are missing");
  }
  let parsedCorrection: V3Body["correctionOf"];
  if (correctionOf !== undefined) {
    const correction = correctionOf && typeof correctionOf === "object"
      ? correctionOf as Record<string, unknown>
      : null;
    if (
      !correction
      || !hasExactKeys(correction, ["submissionRef", "revision"])
      || typeof correction.submissionRef !== "string"
      || !/^ers-v1-[0-9a-f]{64}$/.test(correction.submissionRef)
      || !Number.isSafeInteger(correction.revision)
      || (correction.revision as number) < 1
      || (correction.revision as number) >= Number.MAX_SAFE_INTEGER
    ) {
      throw new TypeError("correctionOf must identify one valid prior revision");
    }
    parsedCorrection = { submissionRef: correction.submissionRef as string, revision: correction.revision as number };
  }
  assertUtf8SafeString(body.submittedAt);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(body.submittedAt)) throw new TypeError("submittedAt must use whole UTC seconds");

  const producerKnowledge = body.producerKnowledge;
  if (producerKnowledge !== "DECLARED" && producerKnowledge !== "PARTIAL" && producerKnowledge !== "UNKNOWN") {
    throw new TypeError("producerKnowledge must be DECLARED, PARTIAL, or UNKNOWN");
  }
  const softwareName = body.softwareName;
  const softwareVersion = body.softwareVersion;
  if (softwareName !== null && !boundedText(softwareName)) throw new TypeError("softwareName must be null or bounded text");
  if (softwareVersion !== null && !boundedText(softwareVersion)) throw new TypeError("softwareVersion must be null or bounded text");
  if (producerKnowledge === "UNKNOWN") {
    if (softwareName !== null || softwareVersion !== null) throw new TypeError("unknown producer must not carry software name/version");
  } else if (producerKnowledge === "PARTIAL") {
    if (softwareName === null || softwareVersion !== null || isFabricatedUnknownLabel(softwareName as string)) {
      throw new TypeError("partial producer keeps the known software name with a null version");
    }
  } else if (softwareName === null || softwareVersion === null || isFabricatedUnknownLabel(softwareName as string) || isFabricatedUnknownLabel(softwareVersion as string)) {
    throw new TypeError("declared producer requires an honest software name and version");
  }
  if (!nullableBoundedText(body.sourceNote, 1000)) throw new TypeError("sourceNote must be null or bounded text");

  const captureBasis = body.captureBasis;
  if (captureBasis !== "EXACT_INTERVAL" && captureBasis !== "DATE_ONLY" && captureBasis !== "UNKNOWN") {
    throw new TypeError("captureBasis must be EXACT_INTERVAL, DATE_ONLY, or UNKNOWN");
  }
  const captureStartedAt = body.captureStartedAt;
  const captureEndedAt = body.captureEndedAt;
  const captureDate = body.captureDate;
  const wholeUtc = (item: unknown): item is string =>
    typeof item === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(item) && Number.isFinite(Date.parse(item));
  if (captureBasis === "EXACT_INTERVAL") {
    const startedAt = registrationInstantMicros(captureStartedAt);
    const endedAt = registrationInstantMicros(captureEndedAt);
    if (captureDate !== null || startedAt === null || endedAt === null
      || (parsedCorrection ? false : (!wholeUtc(captureStartedAt) || !wholeUtc(captureEndedAt)))
      || startedAt >= endedAt) {
      throw new TypeError("EXACT_INTERVAL requires an ordered timezone-aware pair and no calendar date");
    }
  } else if (captureBasis === "DATE_ONLY") {
    if (!isPublisherCalendarDate(captureDate) || captureStartedAt !== null || captureEndedAt !== null) {
      throw new TypeError("DATE_ONLY requires a calendar date and no timestamps");
    }
  } else if (captureDate !== null || captureStartedAt !== null || captureEndedAt !== null) {
    throw new TypeError("UNKNOWN capture must not carry any date or timestamps");
  }

  const originalRetentionLocus = body.originalRetentionLocus;
  if (originalRetentionLocus !== "customer_workstation" && originalRetentionLocus !== "upstream_source" && originalRetentionLocus !== "unknown") {
    throw new TypeError("original retention locus must be declared");
  }
  if (!nullableBoundedText(body.originalRetentionDetail, 1000)) throw new TypeError("original retention detail must be null or bounded text");

  const upstreamSource = parseUpstreamSource(body.upstreamSource);
  const derivativeExport = parseDerivativeExport(body.derivativeExport);

  const artifacts = body.artifacts as ExternalArtifactDeclaration[];
  const artifactKeys = ["artifactId", "kind", "fileName", "format", "contentType", "declaredSha256", "declaredSizeBytes", "declaredCrs", "declaredVerticalReference", "declaredGsdM"] as const;
  const kinds = artifacts.map((item) => item?.kind);
  if (
    artifacts.length < 1 || artifacts.length > 8 ||
    !artifacts.every((item) => item && typeof item === "object" && hasExactKeys(item, artifactKeys) && (item.kind === "ortho" || item.kind === "dsm") && item.artifactId === item.kind && boundedText(item.fileName) && typeof item.declaredSha256 === "string" && /^[a-f0-9]{64}$/.test(item.declaredSha256) && Number.isSafeInteger(item.declaredSizeBytes) && item.declaredSizeBytes > 0 && item.format === "GeoTIFF" && item.contentType === "application/octet-stream" && isDeclaredCrs(item.declaredCrs) && item.declaredVerticalReference === null && item.declaredGsdM === null) ||
    kinds.filter((kind) => kind === "ortho").length > 1 || kinds.filter((kind) => kind === "dsm").length > 1 ||
    (!kinds.includes("ortho") && !kinds.includes("dsm")) ||
    new Set(artifacts.map((item) => item.artifactId)).size !== artifacts.length
  ) throw new TypeError("V3 artifacts require an ortho or a dsm, at most one each");
  return {
    submissionId: (body.submissionId as string).trim(), expectedEpochId: (body.expectedEpochId as string).trim(), submittedAt: body.submittedAt,
    ...(parsedCorrection ? { correctionOf: parsedCorrection } : {}),
    producerKnowledge, softwareName: softwareName as string | null, softwareVersion: softwareVersion as string | null, sourceNote: body.sourceNote as string | null,
    captureBasis, captureStartedAt: captureStartedAt as string | null, captureEndedAt: captureEndedAt as string | null, captureDate: captureDate as string | null,
    originalRetentionLocus, originalRetentionDetail: body.originalRetentionDetail as string | null,
    upstreamSource, derivativeExport, artifacts,
  };
}

type TrustedV3RunFacts = {
  producer: Pick<ExternalSubmissionCandidateV3["producerDeclaration"], "buildIdentifier" | "producerRunIdentifier" | "configurationDigest" | "completedAt">;
  input: Pick<ExternalSubmissionCandidateV3["inputDeclaration"], "localInputManifestDigest" | "imageCount">;
  declaration: {
    producerKnowledge: ExternalV3ProducerKnowledge; softwareName: string | null; softwareVersion: string | null; sourceNote: string | null;
    captureBasis: ExternalV3CaptureBasis; captureStartedAt: string | null; captureEndedAt: string | null; captureDate: string | null;
    upstreamSource: V3Body["upstreamSource"];
  };
};

function trustedV3RunFacts(value: Record<string, unknown>): TrustedV3RunFacts | null {
  const producer = value.producerDeclaration;
  const input = value.inputDeclaration;
  if (!producer || typeof producer !== "object" || !input || typeof input !== "object") return null;
  const p = producer as Record<string, unknown>;
  const i = input as Record<string, unknown>;
  const nullableText = (item: unknown): item is string | null => item === null || typeof item === "string";
  if (
    (p.producerKnowledge !== "DECLARED" && p.producerKnowledge !== "PARTIAL" && p.producerKnowledge !== "UNKNOWN")
    || !nullableText(p.softwareName) || !nullableText(p.softwareVersion) || !nullableText(p.sourceNote)
    || !nullableText(p.buildIdentifier) || !nullableText(p.producerRunIdentifier) || !nullableText(p.configurationDigest) || !nullableText(p.completedAt)
    || (p.completedAt !== null && registrationInstantMicros(p.completedAt) === null)
    || !nullableText(i.localInputManifestDigest)
    || (i.localInputManifestDigest !== null && !/^sha256:[0-9a-f]{64}$/.test(i.localInputManifestDigest))
    || (i.imageCount !== null && (!Number.isSafeInteger(i.imageCount) || (i.imageCount as number) < 1 || (i.imageCount as number) > 10_000_000))
    || (i.captureBasis !== "EXACT_INTERVAL" && i.captureBasis !== "DATE_ONLY" && i.captureBasis !== "UNKNOWN")
    || !nullableText(i.captureStartedAt) || !nullableText(i.captureEndedAt) || !nullableText(i.captureDate)
  ) return null;
  const startedAt = registrationInstantMicros(i.captureStartedAt);
  const endedAt = registrationInstantMicros(i.captureEndedAt);
  if (i.captureBasis === "EXACT_INTERVAL") {
    if (i.captureDate !== null || startedAt === null || endedAt === null || startedAt >= endedAt) return null;
  } else if (i.captureBasis === "DATE_ONLY") {
    if (!isPublisherCalendarDate(i.captureDate) || i.captureStartedAt !== null || i.captureEndedAt !== null) return null;
  } else if (i.captureDate !== null || i.captureStartedAt !== null || i.captureEndedAt !== null) {
    return null;
  }
  const upstream = i.upstreamSource;
  let upstreamSource: V3Body["upstreamSource"];
  try {
    upstreamSource = upstream === null ? null : parseUpstreamSource(upstream);
  } catch {
    return null;
  }
  return {
    producer: {
      buildIdentifier: p.buildIdentifier,
      producerRunIdentifier: p.producerRunIdentifier,
      configurationDigest: p.configurationDigest,
      completedAt: p.completedAt,
    },
    input: { localInputManifestDigest: i.localInputManifestDigest, imageCount: i.imageCount as number | null },
    declaration: {
      producerKnowledge: p.producerKnowledge,
      softwareName: p.softwareName,
      softwareVersion: p.softwareVersion,
      sourceNote: p.sourceNote,
      captureBasis: i.captureBasis,
      captureStartedAt: i.captureStartedAt,
      captureEndedAt: i.captureEndedAt,
      captureDate: i.captureDate,
      upstreamSource,
    },
  };
}

function hasTrustedRunFacts(facts: TrustedV3RunFacts): boolean {
  return Object.values(facts.producer).some((value) => value !== null)
    || Object.values(facts.input).some((value) => value !== null);
}

function sameUpstreamSource(left: V3Body["upstreamSource"], right: V3Body["upstreamSource"]): boolean {
  if (left === null || right === null) return left === right;
  return left.sourceUri === right.sourceUri
    && left.sourceSha256 === right.sourceSha256
    && left.licenceDeclaration === right.licenceDeclaration
    && left.retrievalNote === right.retrievalNote;
}

function sameReconstructionSource(body: V3Body, prior: TrustedV3RunFacts["declaration"]): boolean {
  const sameInstant = (left: string | null, right: string | null) => {
    if (left === null || right === null) return left === right;
    const leftMicros = registrationInstantMicros(left);
    const rightMicros = registrationInstantMicros(right);
    return leftMicros !== null && leftMicros === rightMicros;
  };
  return body.producerKnowledge === prior.producerKnowledge
    && body.softwareName === prior.softwareName
    && body.softwareVersion === prior.softwareVersion
    && body.sourceNote === prior.sourceNote
    && body.captureBasis === prior.captureBasis
    && body.captureDate === prior.captureDate
    && sameInstant(body.captureStartedAt, prior.captureStartedAt)
    && sameInstant(body.captureEndedAt, prior.captureEndedAt)
    && sameUpstreamSource(body.upstreamSource, prior.upstreamSource);
}

function candidateFromTrustedContext(
  body: V3Body,
  values: { organizationId: string; siteId: string; principalId: string; observationEpochId: string; revision?: number },
  trustedRunFacts?: TrustedV3RunFacts,
): ExternalSubmissionCandidateV3 {
  return {
    contractVersion: "external-reconstruction-submission.v3", submissionId: body.submissionId, revision: values.revision ?? 1,
    organizationId: values.organizationId, siteId: values.siteId, observationEpochId: values.observationEpochId,
    submittedAt: body.submittedAt, submittedBy: values.principalId,
    executionResponsibility: "customer_operator", executionLocus: "customer_workstation",
    producerDeclaration: {
      producerKnowledge: body.producerKnowledge, softwareName: body.softwareName, softwareVersion: body.softwareVersion,
      ...trustedRunFacts?.producer,
      buildIdentifier: trustedRunFacts?.producer.buildIdentifier ?? null,
      producerRunIdentifier: trustedRunFacts?.producer.producerRunIdentifier ?? null,
      configurationDigest: trustedRunFacts?.producer.configurationDigest ?? null,
      completedAt: trustedRunFacts?.producer.completedAt ?? null,
      sourceNote: body.sourceNote,
    },
    inputDeclaration: {
      rawMediaStoredByKsi: false, originalRetentionLocus: body.originalRetentionLocus, originalRetentionDetail: body.originalRetentionDetail,
      localInputManifestDigest: trustedRunFacts?.input.localInputManifestDigest ?? null,
      imageCount: trustedRunFacts?.input.imageCount ?? null,
      captureStartedAt: body.captureStartedAt, captureEndedAt: body.captureEndedAt, captureDate: body.captureDate, captureBasis: body.captureBasis,
      upstreamSource: body.upstreamSource, derivativeExport: body.derivativeExport,
    },
    artifacts: body.artifacts,
  };
}

async function registerCandidateWithRecovery(
  workOrderId: string,
  token: string,
  candidate: ExternalSubmissionCandidateV3,
  expectedSubmissionRef: string | null,
): Promise<NextResponse> {
  try {
    return NextResponse.json(await registerExternalReconstructionSubmissionV3WithToken(workOrderId, candidate, token), { status: 201 });
  } catch (registerError) {
    // HTTP errors are definitive Core responses. Only transport errors need a
    // readback to establish whether the immutable registration was recorded.
    if (registerError instanceof CoreApiError) return errorResponse(registerError);
    try {
      const recoveredList = await listExternalReconstructionSubmissionsWithToken(workOrderId, token);
      const recovered = recoveredList.find((item) => item.submission.submissionId === candidate.submissionId
        && item.submission.revision === candidate.revision
        && item.submission.submissionDigest === candidate.submissionDigest
        && (expectedSubmissionRef === null || item.submissionRef === expectedSubmissionRef));
      if (recovered) return NextResponse.json(recovered);
    } catch {
      // A failed recovery read cannot establish whether Core accepted the revision.
    }
    const unknown = NextResponse.json({ code: "EXTERNAL_RECONSTRUCTION_RESULT_UNKNOWN" }, { status: 503 });
    unknown.headers.set("Cache-Control", "private, no-store");
    return unknown;
  }
}

export async function POST(request: NextRequest, context: { params: Promise<{ workOrderId: string }> }) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  // 동결된 시도의 계정 연속성 비교값(있으면) — 서버가 확인한 두 식별자의
  // 비교값일 뿐 자격 증명이나 인가가 아니다. 호출자가 헤더를 생략하면 기존
  // 동작을 그대로 유지하므로, 헤더 없음이 보호를 의미하지 않는다.
  const continuity = parseContinuityClaim(request);
  if (continuity.status === "invalid") {
    return NextResponse.json(
      { message: "계정 연속성 확인값이 올바르지 않습니다. 화면을 새로고침한 뒤 다시 시도하세요.", code: "INVALID_CONTINUITY_CLAIM" },
      { status: 400 },
    );
  }
  // 같은 요청의 토큰 하나로 연속성 검사·맥락 읽기·Core 변이를 잇는다. 토큰을
  // 두 번 읽으면 검사와 변이 사이 세션 교체(TOCTOU)가 생긴다. 호출자 입력
  // (헤더·본문)의 principal은 인가 사실로 쓰지 않고, 현재 신원은 항상 이
  // 토큰의 서버 상태로 확인한다. 자격·토큰 원문은 로그·응답에 싣지 않는다.
  let token: string;
  try {
    token = await getSessionToken();
  } catch (error) {
    return continuity.status === "present" ? coreApiErrorResponse(error) : errorResponse(error);
  }
  try {
    const { workOrderId } = await context.params;
    const body = parseBody(await readBoundedJson(request));
    let current;
    try {
      current = await fetchCurrentContinuityIdentity(token);
    } catch (error) {
      return continuity.status === "present" ? coreApiErrorResponse(error) : errorResponse(error);
    }
    if (continuity.status === "present" && !isSameContinuity(current, continuity)) {
      // 모호한 A 요청 뒤 B 세션/조직의 같은 동결 재시도 — Core 변이를 내지 않고
      // 원래 식별자·내용을 살리는 안내로 끊는다. 이는 중복 방지 가드이며 Core의
      // 권한·범위·actor 멱등 보장을 대신하지 않는다.
      const blocked = NextResponse.json(
        {
          message:
            "계정이 바뀌어 같은 산출물 등록 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 원래 계정으로 다시 로그인한 뒤 이 화면에서 같은 파일과 신고로 다시 시도하세요. 기록에서 원래 요청의 등록이 이미 있는지 먼저 확인하세요. 새로고침하면 입력과 요청이 사라집니다.",
          code: ACCOUNT_CONTINUITY_MISMATCH,
        },
        { status: 409 },
      );
      blocked.headers.set("Cache-Control", "private, no-store");
      return blocked;
    }
    // 작업 원장 읽기를 별도 lib에 두지 않고 같은 토큰으로 직접 잇는다 —
    // 읽기에 다른 토큰이 들어가면 범위 확인과 변이의 주체가 갈라진다.
    // (observation-work-orders.ts는 이 작업 범위 밖이라 그 파일은 건드리지 않는다.)
    const [workOrder, externalContext, existing] = await Promise.all([
      coreFetchWithToken<ObservationWorkOrderView>(`/v1/observation-work-orders/${encodeURIComponent(workOrderId)}`, token),
      getExternalReconstructionContextWithToken(workOrderId, token),
      listExternalReconstructionSubmissionsWithToken(workOrderId, token),
    ]);
    const principal = { principalId: current.principalId, organizationId: current.organizationId };
    if (workOrder.organizationId !== principal.organizationId || workOrder.siteId !== externalContext.siteId || workOrder.workOrderId !== workOrderId || externalContext.workOrderId !== workOrderId) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
    if (externalContext.cycleNumber !== workOrder.cycleNumber || externalContext.workOrderVersion !== workOrder.version || externalContext.executionMode !== workOrder.executionMode) return NextResponse.json({ code: "STALE_ATTEMPT" }, { status: 409 });
    if (body.correctionOf) {
      const target = existing.find((item) => item.submissionRef === body.correctionOf!.submissionRef
        && item.submission.submissionId === body.submissionId
        && item.submission.revision === body.correctionOf!.revision);
      const targetSubmission = target?.submission as unknown as Record<string, unknown> | undefined;
      const targetEpochId = targetSubmission?.observationEpochId;
      if (!target || target.state !== "SEALED"
        || targetSubmission?.contractVersion !== "external-reconstruction-submission.v3"
        || typeof targetEpochId !== "string"
        || targetEpochId !== body.expectedEpochId) {
        return NextResponse.json({ code: "INVALID_CORRECTION_TARGET" }, { status: 409 });
      }
      const priorRunFacts = trustedV3RunFacts(targetSubmission);
      if (!priorRunFacts) return NextResponse.json({ code: "INVALID_CORRECTION_TARGET" }, { status: 409 });
      if (hasTrustedRunFacts(priorRunFacts) && !sameReconstructionSource(body, priorRunFacts.declaration)) {
        return correctionLineageChangedResponse();
      }

      const stream = existing.filter((item) => item.submission.submissionId === body.submissionId);
      if (stream.some((item) => item.submissionRef !== body.correctionOf!.submissionRef
        || (item.submission as unknown as Record<string, unknown>).contractVersion !== "external-reconstruction-submission.v3")) {
        return NextResponse.json({ code: "INVALID_CORRECTION_TARGET" }, { status: 409 });
      }
      const latest = stream.reduce((current, item) => item.submission.revision > current.submission.revision ? item : current, target);
      const nextRevision = body.correctionOf.revision + 1;
      const candidate = candidateFromTrustedContext(body, {
        organizationId: principal.organizationId,
        siteId: workOrder.siteId,
        principalId: principal.principalId,
        observationEpochId: targetEpochId,
        revision: nextRevision,
      }, priorRunFacts);
      candidate.submissionDigest = canonicalSubmissionV3Digest(candidate);

      // A repeated correction POST may arrive after its response was lost. Return
      // that immutable revision only when the complete canonical declaration matches.
      const alreadyRegistered = stream.find((item) => item.submission.revision === nextRevision);
      if (alreadyRegistered?.submission.submissionDigest === candidate.submissionDigest) {
        return NextResponse.json(alreadyRegistered);
      }
      if (latest.submission.revision > nextRevision) {
        return NextResponse.json({ code: "STALE_CORRECTION_TARGET" }, { status: 409 });
      }
      if (alreadyRegistered) {
        return NextResponse.json({ code: "CORRECTION_CONFLICT" }, { status: 409 });
      }
      if (latest.submission.revision !== body.correctionOf.revision || latest.state !== "SEALED") {
        return NextResponse.json({ code: "STALE_CORRECTION_TARGET" }, { status: 409 });
      }
      if (externalContext.expectedEpochId !== targetEpochId) {
        return NextResponse.json({ code: "STALE_ATTEMPT" }, { status: 409 });
      }
      return registerCandidateWithRecovery(workOrderId, token, candidate, body.correctionOf.submissionRef);
    }

    const prior = existing.find((item) => item.submission.submissionId === body.submissionId && item.submission.revision === 1);
    if (prior) {
      const priorEpochId = (prior.submission as { observationEpochId?: unknown }).observationEpochId;
      if (typeof priorEpochId !== "string") return NextResponse.json({ code: "CONFLICT" }, { status: 409 });
      const resumedCandidate = candidateFromTrustedContext(body, { organizationId: principal.organizationId, siteId: workOrder.siteId, principalId: principal.principalId, observationEpochId: priorEpochId });
      resumedCandidate.submissionDigest = canonicalSubmissionV3Digest(resumedCandidate);
      return prior.submission.submissionDigest === resumedCandidate.submissionDigest ? NextResponse.json(prior) : NextResponse.json({ code: "CONFLICT" }, { status: 409 });
    }
    const currentEpochId = externalContext.expectedEpochId;
    if (!currentEpochId || body.expectedEpochId !== currentEpochId) return NextResponse.json({ code: "STALE_ATTEMPT" }, { status: 409 });
    const candidate = candidateFromTrustedContext(body, { organizationId: principal.organizationId, siteId: workOrder.siteId, principalId: principal.principalId, observationEpochId: currentEpochId });
    candidate.submissionDigest = canonicalSubmissionV3Digest(candidate);
    return registerCandidateWithRecovery(workOrderId, token, candidate, null);
  } catch (error) { return errorResponse(error); }
}
