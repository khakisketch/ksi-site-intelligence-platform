import { NextResponse, type NextRequest } from "next/server";

import { getSurfaceProfileResult } from "@/lib/core-api/measurement";
import { JOB_ID_PATTERN } from "@/lib/core-api/measurement-types";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string; jobId: string }> },
) {
  try {
    const token = await getSessionToken();
    const { siteId, workAreaId, jobId } = await params;
    if (!JOB_ID_PATTERN.test(jobId)) return NextResponse.json({ code: "INVALID_REQUEST" }, { status: 400 });
    const view = await getSurfaceProfileResult(siteId, workAreaId, jobId, token);
    if (view.job.jobId !== jobId || view.job.siteId !== siteId || view.job.workAreaId !== workAreaId
      || view.job.executionState !== "COMPLETED" || view.job.availability !== "AVAILABLE"
      || !view.result.resultDigest || view.result.assetRef !== view.job.assetRef
      || view.result.feature?.featureId !== view.job.feature.featureId
      || view.result.feature.revision !== view.job.feature.revision
      || view.result.lineDigest !== view.job.feature.lineDigest
      || view.result.feature.lineDigest !== view.job.feature.lineDigest) {
      return NextResponse.json({ code: "INVALID_CORE_RESPONSE" }, { status: 502 });
    }
    return NextResponse.json(view, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
