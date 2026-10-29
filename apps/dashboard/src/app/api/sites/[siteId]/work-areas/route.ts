import { NextResponse, type NextRequest } from "next/server";

import { listWorkAreas, registerWorkAreaWithToken } from "@/lib/core-api/workAreas";
import {
  ACCOUNT_CONTINUITY_MISMATCH,
  fetchCurrentContinuityIdentity,
  isSameContinuity,
  parseContinuityClaim,
} from "@/lib/core-api/work-order-continuity";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import type { WorkAreaRegisterInput } from "@/lib/core-api/types";

/**
 * 작업구역 등록 — **기하는 이 순간 굳는다**(M4-C).
 *
 * 고치려면 `supersedes` 로 새 구역을 등록한다 — 이 라우트에 PATCH 가 없는 이유가
 * 그것이다(design-surfaces 라우트에 "수정" 이 없는 것과 같은 이유).
 *
 * 계정 연속성 가드(선택적): 명시적 재전송이 `x-ksi-continuity-fingerprint` 를
 * 싣고 오면, 같은 요청의 세션 토큰 하나로 현재 신원을 확인해 다르면 Core 호출
 * 없이 409로 끊는다. 작업구역 등록에는 멱등 키가 없어 같은 계정의 재전송도 새
 * 구역을 만든다 — 이 가드는 중복 생성을 막지 않고, 다른 계정·조직의 조용한
 * 재전송만 막는 usability guard다. Core 권한·범위 판단이 아니다.
 * 헤더가 없으면 기존 계약 그대로 Core에 닿는다(가드 보호 밖).
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    // 같은 요청의 토큰 하나로 연속성 검사와 변이를 잇는다. 토큰을 두 번
    // 읽으면 검사와 Core 생성 사이 세션 교체가 생긴다.
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
        // 모호한 첫 요청(A) 뒤 B 세션/조직의 같은 내용 재전송 — Core 생성을 내지
        // 않고 원래 요청·입력을 살리는 안내로 끊는다. 중복 방지 가드이며 Core의
        // 권한·범위·actor 멱등 보증을 대신하지 않는다.
        const blocked = NextResponse.json(
          {
            message:
              "계정이 바뀌어 같은 요청을 다시 보내지 않았습니다. 원래 계정으로 다시 로그인한 뒤 이 화면에서 목록을 먼저 확인하세요. 입력과 요청은 그대로 있습니다.",
            code: ACCOUNT_CONTINUITY_MISMATCH,
          },
          { status: 409 },
        );
        blocked.headers.set("Cache-Control", "private, no-store");
        return blocked;
      }
    }
    const { siteId } = await params;
    const input = (await request.json()) as WorkAreaRegisterInput;
    const result = await registerWorkAreaWithToken(decodeURIComponent(siteId), input, token);
    return NextResponse.json(result, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

/** 그 현장의 작업구역 목록 — 기본은 고를 수 있는 것(ACTIVE)만. */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId } = await params;
    const includeArchived = request.nextUrl.searchParams.get("include_archived") === "true";
    return NextResponse.json(
      await listWorkAreas(decodeURIComponent(siteId), { includeArchived }),
    );
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
