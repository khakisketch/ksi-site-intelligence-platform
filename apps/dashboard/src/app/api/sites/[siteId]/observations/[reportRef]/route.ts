import { NextResponse, type NextRequest } from "next/server";

import { getSiteExternalRelativeVolumeReport } from "@/lib/core-api/external-result-workflow";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { isExternalRelativeVolumeReportReference } from "@/lib/external-relative-volume-references";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ siteId: string; reportRef: string }> },
) {
  try {
    await getSessionToken();
    const { siteId, reportRef } = await params;
    if (!isExternalRelativeVolumeReportReference(reportRef)) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
    return NextResponse.json(await getSiteExternalRelativeVolumeReport(siteId, reportRef));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
