import { NextResponse, type NextRequest } from "next/server";

import { getExternalRelativeVolumeReport } from "@/lib/core-api/external-result-workflow";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { isExternalRelativeVolumeReportReference } from "@/lib/external-relative-volume-references";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ reportRef: string }> },
) {
  try {
    await getSessionToken();
    const { reportRef: value } = await params;
    if (!isExternalRelativeVolumeReportReference(value)) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
    return NextResponse.json(await getExternalRelativeVolumeReport(value));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
