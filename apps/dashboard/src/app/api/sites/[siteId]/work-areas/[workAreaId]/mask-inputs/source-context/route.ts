import { NextResponse, type NextRequest } from "next/server";

import { parseMaskedSourceContext } from "@/lib/core-api/masked-analysis";
import { coreMaskJson } from "@/lib/core-api/masked-core";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

function isScopeId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 255;
}

const digestPattern = /^sha256:[0-9a-f]{64}$/;

/**
 * 원본 맥락 조회 BFF — 읽기 전용 GET을 Core에 그대로 전달한다.
 * Core `mask-source-context`의 snake 쿼리를 그대로 싣는다. 봉인 subject
 * 사본·기준 DSM artifact·두 프로필 확인값·명시적 원시 상한·원본 승인
 * 상태를 그대로 되돌리며, 격자·권한 필드를 만들지 않는다. 생성·의도·
 * 작업을 만들지 않으며, 모르는·남의 원본은 Core가 404로 닫는다.
 * 승인되지 않은 원본·비활성 레인은 Core가 409 사유로 닫는다(수치 실패 아님).
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId: rawSiteId, workAreaId: rawWorkAreaId } = await params;
    const siteId = decodeURIComponent(rawSiteId);
    const workAreaId = decodeURIComponent(rawWorkAreaId);
    const sourceCalculationIdentityDigest = request.nextUrl.searchParams.get("source_calculation_identity_digest");
    if (!isScopeId(siteId) || !isScopeId(workAreaId)) {
      return NextResponse.json({ message: "현장 또는 작업구역 식별자가 올바르지 않습니다." }, { status: 400 });
    }
    if (!sourceCalculationIdentityDigest || !digestPattern.test(sourceCalculationIdentityDigest)) {
      return NextResponse.json({ message: "원본 계산 신원 확인값 형식이 올바르지 않습니다." }, { status: 400 });
    }
    const view = await coreMaskJson<unknown>(
      "GET",
      `/v3/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/mask-source-context?source_calculation_identity_digest=${encodeURIComponent(sourceCalculationIdentityDigest)}`,
    );
    try {
      return NextResponse.json(
        parseMaskedSourceContext(view, { siteId, workAreaId, sourceCalculationIdentityDigest }),
      );
    } catch {
      return NextResponse.json({ message: "원본 맥락 응답 형식을 확인할 수 없습니다." }, { status: 502 });
    }
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
