import { NextResponse, type NextRequest } from "next/server";

import { archiveWorkAreaWithToken } from "@/lib/core-api/workAreas";
import { ACCOUNT_CONTINUITY_MISMATCH, fetchCurrentContinuityIdentity, isSameContinuity, parseContinuityClaim } from "@/lib/core-api/work-order-continuity";
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
    // 지문은 권한이 아니라 화면과 요청의 계정 연속성 비교값이다.
    // 헤더 없는 기존 호출은 계속 Core 권한 검사만 적용한다.
    const token = await getSessionToken();
    const continuity = parseContinuityClaim(request);
    if (continuity.status === "invalid") {
      return NextResponse.json({ message: "계정 연속성 확인값이 올바르지 않습니다.", code: "INVALID_CONTINUITY_CLAIM" }, { status: 400 });
    }
    if (continuity.status === "present") {
      const current = await fetchCurrentContinuityIdentity(token);
      if (!isSameContinuity(current, continuity)) {
        return NextResponse.json({
          message: "계정이 바뀌어 이번 보관 요청을 Core에 보내지 않았습니다. 이전 요청의 결과는 별도로 목록에서 확인하세요.",
          code: ACCOUNT_CONTINUITY_MISMATCH,
        }, { status: 409, headers: { "Cache-Control": "private, no-store" } });
      }
    }
    const { siteId, workAreaId } = await params;
    const result = await archiveWorkAreaWithToken(
      decodeURIComponent(siteId),
      decodeURIComponent(workAreaId),
      token,
    );
    return NextResponse.json(result);
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
