import { NextResponse, type NextRequest } from "next/server";

import { issueMissionPlan } from "@/lib/core-api/mission-plans";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function POST(request: NextRequest) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    // 세션을 본문 파싱보다 먼저 확인한다 — 그래야 무인증+깨진 JSON 요청도 500이
    // 아니라 401로 끊긴다(독립 재검토 P2-A).
    await getSessionToken();
    const input = await request.json();
    const plan = await issueMissionPlan(input);
    return NextResponse.json(plan, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
