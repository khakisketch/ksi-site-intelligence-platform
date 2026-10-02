import { NextResponse, type NextRequest } from "next/server";

import { createAnalysis, type AnalysisSelector } from "@/lib/core-api/analysis";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

const submissionRefPattern = /^ers-v1-[0-9a-f]{64}$/;
const maxRequestBodyBytes = 16_384;

async function readBoundedBody(request: Request): Promise<{ body: string } | { tooLarge: true }> {
  const contentLength = request.headers.get("content-length");
  if (contentLength && /^\d+$/.test(contentLength) && Number(contentLength) > maxRequestBodyBytes) {
    return { tooLarge: true };
  }

  if (!request.body) return { body: "" };
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      totalBytes += value.byteLength;
      if (totalBytes > maxRequestBodyBytes) {
        await reader.cancel().catch(() => undefined);
        return { tooLarge: true };
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const bytes = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { body: new TextDecoder().decode(bytes) };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function isSelector(value: unknown): value is AnalysisSelector {
  if (!isRecord(value)) return false;
  const keys = Object.keys(value);
  return keys.length === 3
    && keys.includes("workOrderId")
    && keys.includes("submissionRef")
    && keys.includes("revision")
    && typeof value.workOrderId === "string"
    && value.workOrderId.length > 0
    && value.workOrderId.length <= 255
    && value.workOrderId === value.workOrderId.trim()
    && typeof value.submissionRef === "string"
    && submissionRefPattern.test(value.submissionRef)
    && typeof value.revision === "number"
    && Number.isSafeInteger(value.revision)
    && value.revision > 0;
}

function isCreateRequest(value: unknown): value is { baseline: AnalysisSelector; current: AnalysisSelector } {
  return isRecord(value)
    && Object.keys(value).length === 2
    && isSelector(value.baseline)
    && isSelector(value.current)
    && !(
      value.baseline.workOrderId === value.current.workOrderId
      && value.baseline.submissionRef === value.current.submissionRef
      && value.baseline.revision === value.current.revision
    );
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { siteId, workAreaId } = await params;
    const boundedBody = await readBoundedBody(request);
    if ("tooLarge" in boundedBody) {
      return NextResponse.json({ message: "분석 요청 본문이 너무 큽니다." }, { status: 413 });
    }
    const rawBody = boundedBody.body;
    const body: unknown = JSON.parse(rawBody);
    const idempotencyKey = request.headers.get("idempotency-key");
    if (
      !idempotencyKey
      || idempotencyKey.length > 255
      || idempotencyKey !== idempotencyKey.trim()
      || !/^[\x20-\x7e]+$/.test(idempotencyKey)
    ) {
      return NextResponse.json({ message: "요청 식별자가 올바르지 않습니다." }, { status: 400 });
    }
    if (!isCreateRequest(body)) {
      return NextResponse.json({ message: "분석 관측 선택 형식이 올바르지 않습니다." }, { status: 400 });
    }
    return NextResponse.json(
      await createAnalysis(decodeURIComponent(siteId), decodeURIComponent(workAreaId), body, idempotencyKey),
      { status: 202 },
    );
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
