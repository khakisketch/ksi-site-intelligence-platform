import { NextResponse, type NextRequest } from "next/server";

import { transitionSite } from "@/lib/core-api/sites";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    // 세션을 본문 파싱·경로 디코딩보다 먼저 확인한다 — 그래야 무인증+깨진 입력도
    // 500이 아니라 401로 끊긴다(events/[eventKey]/transitions 와 같은 패턴).
    await getSessionToken();
    const { siteId } = await params;
    const input = await request.json();
    const site = await transitionSite(decodeURIComponent(siteId), input);
    return NextResponse.json({ site });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
