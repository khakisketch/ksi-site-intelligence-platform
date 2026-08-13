import { NextResponse, type NextRequest } from "next/server";

import { archiveWorkArea } from "@/lib/core-api/workAreas";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/**
 * 작업구역 보관 — **삭제가 아니다.** 이 구역으로 낸 리포트들이 zoneId 로 이 id 를
 * 들고 있어, 지우면 그 리포트들이 무슨 범위였는지를 잃는다(M4-C).
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { siteId, workAreaId } = await params;
    const result = await archiveWorkArea(
      decodeURIComponent(siteId),
      decodeURIComponent(workAreaId),
    );
    return NextResponse.json(result);
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
