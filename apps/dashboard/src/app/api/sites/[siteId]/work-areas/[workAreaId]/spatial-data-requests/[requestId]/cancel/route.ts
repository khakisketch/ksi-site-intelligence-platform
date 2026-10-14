import { NextResponse, type NextRequest } from "next/server";

import { cancelSpatialDataRequest } from "@/lib/core-api/spatial-data-requests";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

const REQUEST_ID_PATTERN = /^sdj-v1-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string; requestId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    // Reject unauthenticated requests before decoding or forwarding path input.
    await getSessionToken();
    const { siteId, workAreaId, requestId } = await params;
    if (!REQUEST_ID_PATTERN.test(requestId)) {
      return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
    }
    return NextResponse.json(await cancelSpatialDataRequest(siteId, workAreaId, requestId));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
