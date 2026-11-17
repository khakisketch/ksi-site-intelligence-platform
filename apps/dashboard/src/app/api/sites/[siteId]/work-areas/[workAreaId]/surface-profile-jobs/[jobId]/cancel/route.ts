import { NextResponse, type NextRequest } from "next/server";

import { cancelSurfaceProfileJobWithToken } from "@/lib/core-api/measurement";
import { JOB_ID_PATTERN } from "@/lib/core-api/measurement-types";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/** 진행 중인 단면 작업을 취소한다. 이미 끝난 작업의 결과를 지우지는 않는다(Core가 상태를 다시 확인한다). */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string; jobId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    const token = await getSessionToken();
    const { siteId, workAreaId, jobId } = await params;
    if (!JOB_ID_PATTERN.test(jobId)) {
      return NextResponse.json({ message: "요청 형식이 올바르지 않습니다." }, { status: 400 });
    }
    const job = await cancelSurfaceProfileJobWithToken(decodeURIComponent(siteId), decodeURIComponent(workAreaId), jobId, token);
    return NextResponse.json({ job });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
