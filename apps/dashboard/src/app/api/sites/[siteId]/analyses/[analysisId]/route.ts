import { NextResponse, type NextRequest } from "next/server";

import { getAnalysis } from "@/lib/core-api/analysis";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function GET(_request: NextRequest, { params }: { params: Promise<{ siteId: string; analysisId: string }> }) {
  try {
    await getSessionToken();
    const { siteId, analysisId } = await params;
    return NextResponse.json(await getAnalysis(decodeURIComponent(siteId), decodeURIComponent(analysisId)));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
