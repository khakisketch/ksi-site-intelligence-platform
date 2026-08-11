import { NextResponse, type NextRequest } from "next/server";

import { getComparisonRequest } from "@/lib/core-api/comparison";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/**
 * 비교 요청 상태 조회 — 제출 패널이 QUEUED/RUNNING 동안 주기 폴링한다
 * (processing-jobs/[jobId]/route.ts 와 같은 자리·같은 관습).
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ requestId: string }> },
) {
  try {
    await getSessionToken();
    const { requestId } = await params;
    return NextResponse.json(await getComparisonRequest(decodeURIComponent(requestId)));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
