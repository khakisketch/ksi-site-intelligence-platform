import { NextResponse, type NextRequest } from "next/server";

import {
  createObservationWorkOrderWithToken,
  listObservationWorkOrders,
  type CreateObservationWorkOrderInput,
} from "@/lib/core-api/observation-work-orders";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import {
  ACCOUNT_CONTINUITY_MISMATCH,
  fetchCurrentContinuityIdentity,
  isSameContinuity,
  parseContinuityClaim,
} from "@/lib/core-api/work-order-continuity";

/** 현장 안에서 새 관측 작업 초안을 만들거나 현재 원장을 읽는다. */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId } = await params;
    return NextResponse.json({
      workOrders: await listObservationWorkOrders(decodeURIComponent(siteId)),
    });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    // 같은 요청의 토큰 하나로 연속성 검사와 하위 변이를 잇는다. 토큰을 두 번
    // 읽으면 검사와 Core 생성 사이 세션 교체가 생긴다. 호출자 입력(헤더·본문)의
    // principal은 인가 사실로 쓰지 않고, 현재 신원은 항상 이 토큰의 서버 상태로
    // 확인한다. 자격·토큰 원문은 로그·응답에 싣지 않는다.
    const token = await getSessionToken();
    const continuity = parseContinuityClaim(request);
    if (continuity.status === "invalid") {
      return NextResponse.json(
        { message: "계정 연속성 확인값이 올바르지 않습니다. 화면을 새로고침한 뒤 다시 시도하세요.", code: "INVALID_CONTINUITY_CLAIM" },
        { status: 400 },
      );
    }
    if (continuity.status === "present") {
      let current;
      try {
        current = await fetchCurrentContinuityIdentity(token);
      } catch (error) {
        return coreApiErrorResponse(error);
      }
      if (!isSameContinuity(current, continuity)) {
        // 모호한 A 요청 뒤 B 세션/조직의 같은 키 재시도 — Core 생성을 내지 않고
        // 원래 키·내용을 살리는 안내로 끊는다. 이는 중복 방지 가드이며 Core의
        // 권한·범위·actor 멱등 보장을 대신하지 않는다.
        const blocked = NextResponse.json(
          {
            message:
              "계정이 바뀌어 같은 요청을 다시 보내지 않았습니다. 원래 계정으로 다시 로그인한 뒤 이 화면에서 같은 요청으로 다시 시도하세요. 입력과 요청은 그대로 있습니다. 작업 목록에서 원래 요청의 작업이 이미 만들어졌는지 먼저 확인하세요.",
            code: ACCOUNT_CONTINUITY_MISMATCH,
          },
          { status: 409 },
        );
        blocked.headers.set("Cache-Control", "private, no-store");
        return blocked;
      }
    }
    const { siteId } = await params;
    const input = (await request.json()) as CreateObservationWorkOrderInput;
    const idempotencyKey = request.headers.get("idempotency-key") ?? undefined;
    return NextResponse.json(
      await createObservationWorkOrderWithToken(decodeURIComponent(siteId), input, idempotencyKey, token),
      { status: 201 },
    );
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
