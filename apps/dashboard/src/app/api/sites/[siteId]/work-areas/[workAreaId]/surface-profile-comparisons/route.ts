import { NextResponse, type NextRequest } from "next/server";

import {
  getSurfaceProfileComparisonWithToken,
  requestSurfaceProfileComparisonWithToken,
} from "@/lib/core-api/measurement";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { JOB_ID_PATTERN } from "@/lib/core-api/measurement-types";

const IDEMPOTENCY_KEY = /^[\x21-\x7e]{1,240}$/;

function isPairBody(value: unknown): value is { baselineJobId: string; currentJobId: string } {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const body = value as Record<string, unknown>;
  return Object.keys(body).length === 2
    && Object.keys(body).every((key) => key === "baselineJobId" || key === "currentJobId")
    && typeof body.baselineJobId === "string" && JOB_ID_PATTERN.test(body.baselineJobId)
    && typeof body.currentJobId === "string" && JOB_ID_PATTERN.test(body.currentJobId)
    && body.baselineJobId !== body.currentJobId;
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string }> },
) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  try {
    const token = await getSessionToken();
    const key = request.headers.get("idempotency-key");
    if (key === null || !IDEMPOTENCY_KEY.test(key)) {
      return NextResponse.json({ code: "INVALID_REQUEST" }, { status: 400 });
    }
    const body: unknown = await request.json().catch(() => null);
    if (!isPairBody(body)) return NextResponse.json({ code: "INVALID_REQUEST" }, { status: 422 });
    const { siteId, workAreaId } = await params;
    const comparison = await requestSurfaceProfileComparisonWithToken(
      decodeURIComponent(siteId),
      decodeURIComponent(workAreaId),
      body,
      key,
      token,
    );
    return NextResponse.json(comparison);
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string }> },
) {
  try {
    const token = await getSessionToken();
    const { siteId, workAreaId } = await params;
    const query = request.nextUrl.searchParams;
    const baselineJobId = query.get("baseline_job_id");
    const currentJobId = query.get("current_job_id");
    const decisionId = query.get("decision_id");
    if (baselineJobId === null || !JOB_ID_PATTERN.test(baselineJobId)
      || currentJobId === null || !JOB_ID_PATTERN.test(currentJobId) || baselineJobId === currentJobId
      || decisionId === null || decisionId.length === 0 || decisionId.length > 255) {
      return NextResponse.json({ code: "INVALID_REQUEST" }, { status: 400 });
    }
    const comparison = await getSurfaceProfileComparisonWithToken(
      decodeURIComponent(siteId),
      decodeURIComponent(workAreaId),
      { baselineJobId, currentJobId, decisionId },
      token,
    );
    return NextResponse.json(comparison);
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
