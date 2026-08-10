import { NextResponse, type NextRequest } from "next/server";

import { issueProcessingJob } from "@/lib/core-api/processing-jobs";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import type { ProcessingJobIssueInput } from "@/lib/core-api/types";

/**
 * 재구성 처리 작업 발급(B2) — 입력(장수·digest)은 봉인된 번들이 정한다.
 * 같은 사양의 재요청은 ``ALREADY_ISSUED`` 로 기존 작업을 재사용한다(오류 아님).
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ missionId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { missionId } = await params;
    const spec = (await request.json()) as ProcessingJobIssueInput;
    const result = await issueProcessingJob(decodeURIComponent(missionId), spec);
    return NextResponse.json(result, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
