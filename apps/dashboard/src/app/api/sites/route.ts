import { NextResponse, type NextRequest } from "next/server";

import { registerSiteWithToken } from "@/lib/core-api/sites";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import {
  ACCOUNT_CONTINUITY_MISMATCH,
  fetchCurrentContinuityIdentity,
  isSameContinuity,
  parseContinuityClaim,
} from "@/lib/core-api/work-order-continuity";

export async function POST(request: NextRequest) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  // 같은 요청의 토큰 하나로 연속성 검사와 하위 변이를 잇는다. 토큰을 두 번
  // 읽으면 검사와 Core 변이 사이 세션 교체(TOCTOU)가 생긴다. 호출자 입력
  // (헤더·본문)의 principal은 인가 사실로 쓰지 않고, 현재 신원은 항상 이
  // 토큰의 서버 상태로 확인한다. 자격·토큰 원문은 로그·응답에 싣지 않는다.
  let token: string;
  try {
    // 세션을 본문 파싱보다 먼저 확인한다 — 그래야 무인증+깨진 JSON 요청도 500이
    // 아니라 401로 끊긴다(독립 재검토 P2-A).
    token = await getSessionToken();
  } catch (error) {
    return coreApiErrorResponse(error);
  }
  const continuity = parseContinuityClaim(request);
  if (continuity.status === "invalid") {
    return NextResponse.json(
      { message: "계정 연속성 확인값이 올바르지 않습니다. 화면을 새로고침한 뒤 다시 시도하세요.", code: "INVALID_CONTINUITY_CLAIM" },
      { status: 400 },
    );
  }
  if (continuity.status === "present") {
    // Core bootstrap 멱등 namespace는 (organizationId, actor, requestKey)다.
    // 응답 유실 뒤 계정이 바뀌면 같은 키 재시도가 별도 현장을 만든다 — Core
    // POST 없이 여기서 끊는다. 헤더 없는 호출자는 이전 계약 그대로 두며
    // 보호하지 않는다고 명시한다(아래 else 없음 = 통과).
    let current;
    try {
      current = await fetchCurrentContinuityIdentity(token);
    } catch (error) {
      return coreApiErrorResponse(error);
    }
    if (!isSameContinuity(current, continuity)) {
      const blocked = NextResponse.json(
        {
          message:
            "계정이 바뀌어 같은 현장 등록 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 원래 계정으로 다시 로그인한 뒤 같은 요청으로 다시 시도하세요.",
          code: ACCOUNT_CONTINUITY_MISMATCH,
        },
        { status: 409 },
      );
      blocked.headers.set("Cache-Control", "private, no-store");
      return blocked;
    }
  }
  try {
    const input = await request.json();
    const site = await registerSiteWithToken(input, token);
    return NextResponse.json({ site }, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
