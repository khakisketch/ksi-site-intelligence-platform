import { NextResponse, type NextRequest } from "next/server";

import { getExternalReconstructionContext } from "@/lib/core-api/external-reconstruction";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/**
 * 한 화면 올리기가 방금 만든 작업의 관측 시점(expectedEpochId)을 읽는다.
 * 권한·범위는 Core가 판단하고, 화면에는 등록에 필요한 식별자만 돌려준다.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ workOrderId: string }> },
) {
  try {
    await getSessionToken();
    const { workOrderId } = await params;
    const context = await getExternalReconstructionContext(workOrderId);
    const response = NextResponse.json({
      workOrderId: context.workOrderId,
      siteId: context.siteId,
      expectedEpochId: context.expectedEpochId,
      executionMode: context.executionMode,
    });
    response.headers.set("Cache-Control", "private, no-store");
    return response;
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
