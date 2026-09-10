import { NextResponse, type NextRequest } from "next/server";

import { listSiteExternalRelativeVolumeHistory } from "@/lib/core-api/external-result-workflow";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

const reportRef = /^external-relative-volume-report-[0-9a-f]{32}$/;

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId } = await params;
    const after = request.nextUrl.searchParams.get("after") ?? undefined;
    const limit = request.nextUrl.searchParams.get("limit") ?? undefined;
    if (after !== undefined && !reportRef.test(after)) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
    const parsedLimit = limit === undefined ? undefined : Number(limit);
    if (parsedLimit !== undefined && (!Number.isInteger(parsedLimit) || parsedLimit < 1 || parsedLimit > 50)) {
      return NextResponse.json({ code: "INVALID_REPORT_HISTORY_PAGE" }, { status: 400 });
    }
    return NextResponse.json(await listSiteExternalRelativeVolumeHistory(siteId, { after, limit: parsedLimit }));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
