import { NextRequest, NextResponse } from "next/server";
import { whoAmI } from "@/lib/core-api/auth";
import { CoreApiError } from "@/lib/core-api/client";
import { getExternalReconstructionContext, listExternalReconstructionSubmissions, registerExternalReconstructionSubmission } from "@/lib/core-api/external-reconstruction";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { getObservationWorkOrder } from "@/lib/core-api/observation-work-orders";
import { getSessionToken } from "@/lib/core-api/session";
import { assertUtf8SafeString, canonicalSubmissionDigest, isDeclaredCrs, type ExternalArtifactDeclaration, type ExternalSubmissionCandidate } from "@/lib/external-reconstruction-submission";

const MAX_DECLARATION_BYTES = 1024 * 1024;

class PayloadTooLargeError extends Error {}

function errorResponse(error: unknown) {
  if (error instanceof PayloadTooLargeError) return NextResponse.json({ code: "EXTERNAL_RECONSTRUCTION_BODY_TOO_LARGE" }, { status: 413 });
  if (error instanceof CoreApiError) return NextResponse.json({ code: error.code, detail: error.serverMessage }, { status: error.status });
  return NextResponse.json({ code: "INVALID_EXTERNAL_RECONSTRUCTION_REQUEST" }, { status: 400 });
}

function boundedText(value: unknown): value is string {
  if (typeof value !== "string" || value.trim().length === 0 || value.length > 255) return false;
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

function parseBody(value: unknown): { submissionId: string; expectedEpochId: string; submittedAt: string; softwareName: string; softwareVersion: string; captureStartedAt: string | null; captureEndedAt: string | null; artifacts: ExternalArtifactDeclaration[] } {
  if (!value || typeof value !== "object") throw new TypeError("body must be an object");
  const body = value as Record<string, unknown>;
  const declarationKeys = ["submissionId", "expectedEpochId", "submittedAt", "softwareName", "softwareVersion", "captureStartedAt", "captureEndedAt", "artifacts"] as const;
  if (!hasExactKeys(body, declarationKeys) || !boundedText(body.submissionId) || !boundedText(body.expectedEpochId) || !boundedText(body.softwareName) || !boundedText(body.softwareVersion) || typeof body.submittedAt !== "string" || !Array.isArray(body.artifacts)) throw new TypeError("required declaration fields are missing");
  assertUtf8SafeString(body.submittedAt);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(body.submittedAt)) throw new TypeError("submittedAt must use whole UTC seconds");
  const captureStartedAt = body.captureStartedAt;
  const captureEndedAt = body.captureEndedAt;
  if ((captureStartedAt === null) !== (captureEndedAt === null) ||
    (captureStartedAt !== null && (typeof captureStartedAt !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(captureStartedAt) || !Number.isFinite(Date.parse(captureStartedAt)))) ||
    (captureEndedAt !== null && (typeof captureEndedAt !== "string" || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(captureEndedAt) || !Number.isFinite(Date.parse(captureEndedAt)))) ||
    (typeof captureStartedAt === "string" && typeof captureEndedAt === "string" && Date.parse(captureStartedAt) >= Date.parse(captureEndedAt))) {
    throw new TypeError("capture interval must be an ordered UTC RFC3339 pair");
  }
  const artifacts = body.artifacts as ExternalArtifactDeclaration[];
  const artifactKeys = ["artifactId", "kind", "fileName", "format", "contentType", "declaredSha256", "declaredSizeBytes", "declaredCrs", "declaredVerticalReference", "declaredGsdM"] as const;
  if (artifacts.length < 1 || artifacts.length > 2 || !artifacts.every((item) => item && typeof item === "object" && hasExactKeys(item, artifactKeys) && (item.kind === "ortho" || item.kind === "dsm") && item.artifactId === item.kind && boundedText(item.fileName) && typeof item.declaredSha256 === "string" && /^[a-f0-9]{64}$/.test(item.declaredSha256) && Number.isSafeInteger(item.declaredSizeBytes) && item.declaredSizeBytes > 0 && item.format === "GeoTIFF" && item.contentType === "application/octet-stream" && isDeclaredCrs(item.declaredCrs) && item.declaredVerticalReference === null && item.declaredGsdM === null) || artifacts.filter((item) => item.kind === "ortho").length !== 1 || new Set(artifacts.map((item) => item.kind)).size !== artifacts.length) throw new TypeError("invalid artifact declaration");
  return { submissionId: body.submissionId.trim(), expectedEpochId: body.expectedEpochId.trim(), submittedAt: body.submittedAt, softwareName: body.softwareName.trim(), softwareVersion: body.softwareVersion.trim(), captureStartedAt, captureEndedAt, artifacts };
}

function candidateFromTrustedContext(body: ReturnType<typeof parseBody>, values: { organizationId: string; siteId: string; principalId: string; observationEpochId: string }): ExternalSubmissionCandidate {
  return {
    contractVersion: "external-reconstruction-submission.v1", submissionId: body.submissionId, revision: 1,
    organizationId: values.organizationId, siteId: values.siteId, observationEpochId: values.observationEpochId,
    submittedAt: body.submittedAt, submittedBy: values.principalId,
    executionResponsibility: "customer_operator", executionLocus: "customer_workstation",
    producerDeclaration: { softwareName: body.softwareName, softwareVersion: body.softwareVersion, buildIdentifier: null, producerRunIdentifier: null, configurationDigest: null, completedAt: null },
    inputDeclaration: { rawMediaStoredByKsi: false, originalRetentionLocus: "customer_workstation", localInputManifestDigest: null, imageCount: null, captureStartedAt: body.captureStartedAt, captureEndedAt: body.captureEndedAt },
    artifacts: body.artifacts,
  };
}
export async function GET(_: NextRequest, context: { params: Promise<{ workOrderId: string }> }) {
  try { await getSessionToken(); const { workOrderId } = await context.params; return NextResponse.json({ submissions: await listExternalReconstructionSubmissions(workOrderId) }); } catch (error) { return errorResponse(error); }
}
export async function POST(request: NextRequest, context: { params: Promise<{ workOrderId: string }> }) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  try {
    await getSessionToken();
    const { workOrderId } = await context.params;
    const body = parseBody(await readBoundedJson(request));
    const [principal, workOrder, externalContext] = await Promise.all([whoAmI(), getObservationWorkOrder(workOrderId), getExternalReconstructionContext(workOrderId)]);
    if (workOrder.organizationId !== principal.organizationId || workOrder.siteId !== externalContext.siteId || workOrder.workOrderId !== workOrderId || externalContext.workOrderId !== workOrderId) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
    if (externalContext.cycleNumber !== workOrder.cycleNumber || externalContext.workOrderVersion !== workOrder.version || externalContext.executionMode !== workOrder.executionMode) return NextResponse.json({ code: "STALE_ATTEMPT" }, { status: 409 });
    const existing = await listExternalReconstructionSubmissions(workOrderId);
    const prior = existing.find((item) => item.submission.submissionId === body.submissionId && item.submission.revision === 1);
    if (prior) {
      const priorEpochId = prior.submission.observationEpochId;
      if (typeof priorEpochId !== "string") return NextResponse.json({ code: "CONFLICT" }, { status: 409 });
      const resumedCandidate = candidateFromTrustedContext(body, { organizationId: principal.organizationId, siteId: workOrder.siteId, principalId: principal.principalId, observationEpochId: priorEpochId });
      resumedCandidate.submissionDigest = canonicalSubmissionDigest(resumedCandidate);
      return prior.submission.submissionDigest === resumedCandidate.submissionDigest ? NextResponse.json(prior) : NextResponse.json({ code: "CONFLICT" }, { status: 409 });
    }
    const currentEpochId = externalContext.expectedEpochId;
    if (!currentEpochId || body.expectedEpochId !== currentEpochId) return NextResponse.json({ code: "STALE_ATTEMPT" }, { status: 409 });
    const candidate = candidateFromTrustedContext(body, { organizationId: principal.organizationId, siteId: workOrder.siteId, principalId: principal.principalId, observationEpochId: currentEpochId });
    candidate.submissionDigest = canonicalSubmissionDigest(candidate);
    try { return NextResponse.json(await registerExternalReconstructionSubmission(workOrderId, candidate), { status: 201 }); }
    catch (error) { const recovered = (await listExternalReconstructionSubmissions(workOrderId)).find((item) => item.submission.submissionId === candidate.submissionId && item.submission.revision === 1 && item.submission.submissionDigest === candidate.submissionDigest); if (recovered) return NextResponse.json(recovered); throw error; }
  } catch (error) { return errorResponse(error); }
}
