import { NextResponse, type NextRequest } from "next/server";

import { getExternalSingleVolumeRequest } from "@/lib/core-api/external-result-workflow";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { isExternalSingleVolumeRequestReference } from "@/lib/external-single-volume-references";

const workOrderRef = /^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$/;

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ workOrderId: string; requestRef: string }> },
) {
  try {
    await getSessionToken();
    const value = await params;
    if (!workOrderRef.test(value.workOrderId) || !isExternalSingleVolumeRequestReference(value.requestRef)) {
      return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
    }
    return NextResponse.json(await getExternalSingleVolumeRequest(value.workOrderId, value.requestRef));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
