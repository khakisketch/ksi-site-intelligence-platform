import { NextResponse, type NextRequest } from "next/server";

import { reviewExternalSingleVolumeReport } from "@/lib/core-api/external-result-workflow";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { isExternalSingleVolumeReportReference } from "@/lib/external-single-volume-references";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ reportRef: string }> },
) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  try {
    await getSessionToken();
    const { reportRef: value } = await params;
    if (!isExternalSingleVolumeReportReference(value) || (await request.text()).trim()) {
      return NextResponse.json({ code: "INVALID_EXTERNAL_RESULT_REVIEW_INTENT" }, { status: 400 });
    }
    return NextResponse.json(await reviewExternalSingleVolumeReport(value), { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
