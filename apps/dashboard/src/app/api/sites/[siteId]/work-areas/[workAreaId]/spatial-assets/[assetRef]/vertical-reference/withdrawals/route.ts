import { NextResponse, type NextRequest } from "next/server";

import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { ASSET_REF_PATTERN } from "@/lib/core-api/measurement-types";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { withdrawVerticalReferenceWithToken } from "@/lib/core-api/vertical-reference";
import { parseWithdrawBody } from "@/lib/core-api/vertical-reference-types";

const IDEMPOTENCY_KEY = /^[\x21-\x7e]{1,255}$/;

/**
 * 수직 기준 선언의 쓰기. 형식이 맞지 않으면 Core에 보내지 않는다.
 * 범위(조직·현장·구역)와 자료 사실은 Core가 현재 권한으로 다시 확인하며, 여기서는 아무것도 추정하지 않는다.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string; assetRef: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    const token = await getSessionToken();
    const { siteId, workAreaId, assetRef } = await params;
    const key = request.headers.get("idempotency-key");
    if (!ASSET_REF_PATTERN.test(assetRef) || key === null || !IDEMPOTENCY_KEY.test(key)) {
      return NextResponse.json({ message: "요청 형식이 올바르지 않습니다." }, { status: 400 });
    }
    const body = parseWithdrawBody(await request.json());
    if (body === null) {
      return NextResponse.json({ message: "요청 형식이 올바르지 않습니다.", code: "INVALID" }, { status: 422 });
    }
    const record = await withdrawVerticalReferenceWithToken(
      decodeURIComponent(siteId),
      decodeURIComponent(workAreaId),
      assetRef,
      body,
      key,
      token,
    );
    return NextResponse.json({ declaration: record }, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
