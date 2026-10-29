import { NextResponse, type NextRequest } from "next/server";

import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { updateOrganizationWorkRosterMemberWithToken, type UpdateOrganizationWorkRosterMemberInput } from "@/lib/core-api/work-collaboration";
import {
  ACCOUNT_CONTINUITY_MISMATCH,
  fetchCurrentContinuityIdentity,
  isSameContinuity,
  parseContinuityClaim,
} from "@/lib/core-api/work-order-continuity";

export async function PUT(request: NextRequest, { params }: { params: Promise<{ principalId: string }> }) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  // 같은 요청의 토큰 하나로 연속성 검사와 하위 변이를 잇는다. 토큰을 두 번
  // 읽으면 검사와 Core 변이 사이 세션 교체(TOCTOU)가 생긴다. 호출자 입력(헤더·본문)의
  // principal은 인가 사실로 쓰지 않고, 현재 신원은 항상 이 토큰의 서버 상태로
  // 확인한다. 자격·토큰 원문은 로그·응답에 싣지 않는다.
  let token: string;
  try {
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
    let current;
    try {
      current = await fetchCurrentContinuityIdentity(token);
    } catch (error) {
      return coreApiErrorResponse(error);
    }
    if (!isSameContinuity(current, continuity)) {
      // 모호한 A 요청 뒤 B 세션/조직의 같은 키 재시도 — Core 변이를 내지 않고
      // 원래 키·내용을 살리는 안내로 끊는다. 이는 중복 방지 가드이며 Core의
      // 권한·범위·actor 멱등 보장을 대신하지 않는다.
      const blocked = NextResponse.json(
        {
          message:
            "계정이 바뀌어 같은 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 입력과 요청은 이 화면에 그대로 있습니다. 원래 계정으로 다시 로그인한 뒤 이 화면에서 같은 요청으로 다시 시도하세요. 먼저 팀원 목록을 다시 불러와 원래 요청이 이미 반영됐는지 확인하세요. 새로고침하면 입력과 요청이 사라집니다.",
          code: ACCOUNT_CONTINUITY_MISMATCH,
        },
        { status: 409 },
      );
      blocked.headers.set("Cache-Control", "private, no-store");
      return blocked;
    }
  }
  try {
    const input: unknown = await request.json();
    if (!isRosterInput(input)) return NextResponse.json({ message: "팀원 정보 형식이 올바르지 않습니다." }, { status: 400 });
    const { principalId } = await params;
    if (!principalId.trim()) return NextResponse.json({ message: "팀원 식별자가 필요합니다." }, { status: 400 });
    return NextResponse.json(await updateOrganizationWorkRosterMemberWithToken(
      principalId,
      input,
      request.headers.get("idempotency-key")?.trim() ?? "",
      token,
    ));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

function isRosterInput(value: unknown): value is UpdateOrganizationWorkRosterMemberInput {
  if (!value || typeof value !== "object") return false;
  const input = value as Record<string, unknown>;
  return Number.isInteger(input.expectedRevision) && (input.expectedRevision as number) >= 0
    && typeof input.displayName === "string" && input.displayName.trim().length > 0 && input.displayName.length <= 120
    && (input.roleHint === "ADMIN" || input.roleHint === "FIELD_OPERATOR" || input.roleHint === "VIEWER")
    && (input.status === "ACTIVE" || input.status === "INACTIVE");
}
