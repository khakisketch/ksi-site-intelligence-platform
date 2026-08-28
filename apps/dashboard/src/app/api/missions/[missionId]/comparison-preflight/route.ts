import { NextResponse, type NextRequest } from "next/server";

import { preflightComparisonRequest } from "@/lib/core-api/comparison";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import type { ComparisonRequestCreateInput } from "@/lib/core-api/types";

/**
 * Civil comparison's fail-closed preflight proxy.
 *
 * The browser sends exactly the same selection payload it will later submit;
 * Core remains the sole authority for profile/readiness/lineage compatibility.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ missionId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ detail: "CROSS_SITE_REQUEST_FORBIDDEN" }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { missionId } = await params;
    const input = (await request.json()) as ComparisonRequestCreateInput;
    return NextResponse.json(
      await preflightComparisonRequest(decodeURIComponent(missionId), input),
    );
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
