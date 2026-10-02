import { NextResponse, type NextRequest } from "next/server";

import { listAnalysisObservations } from "@/lib/core-api/analysis";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function GET(_request: NextRequest, { params }: { params: Promise<{ siteId: string }> }) {
  try {
    await getSessionToken();
    const { siteId } = await params;
    return NextResponse.json({ items: await listAnalysisObservations(decodeURIComponent(siteId)) });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
