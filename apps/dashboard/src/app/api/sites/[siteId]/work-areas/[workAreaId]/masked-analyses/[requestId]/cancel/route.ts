import { NextResponse, type NextRequest } from "next/server";

import { parseMaskedCalculationMutation } from "@/lib/core-api/masked-analysis";
import { coreMaskJson } from "@/lib/core-api/masked-core";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

function isScopeId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 255;
}

function isOpaqueId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value);
}

/**
 * V3 변경 취소 BFF — 명시적 사용자 동작에서만 호출한다.
 * 수치 표시는 취소와 무관하게 마지막으로 검증된 화면을 그대로 둔다.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string; requestId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { siteId: rawSiteId, workAreaId: rawWorkAreaId, requestId: rawRequestId } = await params;
    const siteId = decodeURIComponent(rawSiteId);
    const workAreaId = decodeURIComponent(rawWorkAreaId);
    const requestId = decodeURIComponent(rawRequestId);
    if (!isScopeId(siteId) || !isScopeId(workAreaId) || !isOpaqueId(requestId)) {
      return NextResponse.json({ message: "마스크 계산 식별자가 올바르지 않습니다." }, { status: 400 });
    }
    const view = await coreMaskJson<unknown>(
      "POST",
      `/v3/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/masked-calculations/${encodeURIComponent(requestId)}/cancel`,
    );
    try {
      return NextResponse.json(parseMaskedCalculationMutation(view, { requestId }));
    } catch {
      return NextResponse.json({ message: "마스크 계산 응답 형식을 확인할 수 없습니다." }, { status: 502 });
    }
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
