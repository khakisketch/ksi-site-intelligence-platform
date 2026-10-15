import { randomUUID } from "node:crypto";

import { NextResponse, type NextRequest } from "next/server";

import {
  createAnalysisReview,
  getAnalysisReviewTarget,
  listAnalysisReviews,
  type AnalysisReviewDecision,
} from "@/lib/core-api/analysis";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

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

function isReviewInput(value: unknown): value is { decision: AnalysisReviewDecision; comment: string } {
  if (!isRecord(value)) return false;
  const keys = Object.keys(value);
  if (keys.length !== 2 || !keys.includes("decision") || !keys.includes("comment")) return false;
  if (value.decision !== "ACKNOWLEDGED" && value.decision !== "NEEDS_FOLLOW_UP") return false;
  if (typeof value.comment !== "string") return false;
  const comment = value.comment.trim();
  const length = [...comment].length;
  return length >= 1 && length <= 1_000;
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ siteId: string; analysisId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId, analysisId } = await params;
    const scopedSiteId = decodeURIComponent(siteId);
    const scopedAnalysisId = decodeURIComponent(analysisId);
    const [target, page] = await Promise.all([
      getAnalysisReviewTarget(scopedSiteId, scopedAnalysisId),
      listAnalysisReviews(scopedSiteId, scopedAnalysisId, { limit: 50 }),
    ]);
    return NextResponse.json({ target, items: page.items, nextCursor: page.nextCursor });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; analysisId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { siteId, analysisId } = await params;
    const boundedBody = await readBoundedBody(request);
    if ("tooLarge" in boundedBody) {
      return NextResponse.json({ message: "검토 요청 본문이 너무 큽니다." }, { status: 413 });
    }
    const body: unknown = JSON.parse(boundedBody.body);
    if (!isReviewInput(body)) {
      return NextResponse.json({ message: "결정과 1~1,000자의 검토 의견을 입력하세요." }, { status: 400 });
    }

    const scopedSiteId = decodeURIComponent(siteId);
    const scopedAnalysisId = decodeURIComponent(analysisId);
    // Do not accept a browser-supplied target: resolve the exact current target for every write.
    const target = await getAnalysisReviewTarget(scopedSiteId, scopedAnalysisId);
    const receipt = await createAnalysisReview(
      scopedSiteId,
      scopedAnalysisId,
      target,
      { decision: body.decision, comment: body.comment.trim() },
      `analysis-review-${randomUUID()}`,
    );
    return NextResponse.json(receipt, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
