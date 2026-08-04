import { NextResponse, type NextRequest } from "next/server";

import { getEvidenceViewUrl } from "@/lib/core-api/events";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/**
 * 증거 열람 URL 발급. 짧은 수명(분 단위)이라 **볼 때마다** 새로 받는다 —
 * 상세 응답에 URL 을 미리 실어두면 그 응답 자체가 유효기간 있는 인가가 된다.
 *
 * 폐기된 증거는 Core 가 410 을 준다(404 아님) — "없음"과 "정책대로 폐기됨"은
 * 다른 사실이고, 그 구분은 화면까지 그대로 전달돼야 한다.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ eventKey: string; artifactId: string }> },
) {
  try {
    await getSessionToken();
    const { eventKey, artifactId } = await params;
    const result = await getEvidenceViewUrl(
      decodeURIComponent(eventKey),
      decodeURIComponent(artifactId),
    );
    return NextResponse.json(result);
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
