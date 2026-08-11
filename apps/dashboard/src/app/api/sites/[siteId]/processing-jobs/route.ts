import { NextResponse, type NextRequest } from "next/server";

import { listSiteProcessingJobs } from "@/lib/core-api/comparison";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/**
 * 그 현장의 재구성 epoch 목록 — 비교 제출 화면이 후보를 다시 불러올 때 쓴다
 * (최초 목록은 서버 컴포넌트가 직접 조회해 넘긴다).
 * GET 이라 mutating 요청 전용 Origin 검사는 적용하지 않는다(kmz/route.ts 와 동일 관습).
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId } = await params;
    return NextResponse.json(await listSiteProcessingJobs(decodeURIComponent(siteId)));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
