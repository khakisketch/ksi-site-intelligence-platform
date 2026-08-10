import { NextResponse, type NextRequest } from "next/server";

import { getProcessingJobArtifacts } from "@/lib/core-api/phase34";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/**
 * 처리 작업 상태 조회 — 업로드 패널이 QUEUED/RUNNING 동안 주기 폴링한다.
 * GET 이라 mutating 요청 전용 Origin 검사는 적용하지 않는다(kmz/route.ts 와 동일 관습).
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> },
) {
  try {
    await getSessionToken();
    const { jobId } = await params;
    const result = await getProcessingJobArtifacts(decodeURIComponent(jobId));
    return NextResponse.json(result);
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
