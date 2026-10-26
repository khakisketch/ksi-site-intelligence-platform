import { NextResponse, type NextRequest } from "next/server";

import { parseMaskedCalculationDetail } from "@/lib/core-api/masked-analysis";
import { coreMaskJson } from "@/lib/core-api/masked-core";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

function isScopeId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 255;
}

function isOpaqueId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value);
}

/**
 * V3 화면 조회 BFF — 명시적 새로고침으로만 읽으며 폴링하지 않는다.
 * 수치 보고서는 `AVAILABLE`일 때만 오며, 내보내기 상태는 수치 표시에
 * 관여하지 않는다(발행 실패가 수치 표시를 바꾸지 않는다).
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string; requestId: string }> },
) {
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
      "GET",
      `/v3/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/masked-calculations/${encodeURIComponent(requestId)}`,
    );
    try {
      return NextResponse.json(parseMaskedCalculationDetail(view, { siteId, workAreaId, requestId }));
    } catch {
      return NextResponse.json({ message: "마스크 계산 응답 형식을 확인할 수 없습니다." }, { status: 502 });
    }
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
