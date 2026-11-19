import { NextResponse, type NextRequest } from "next/server";

import { issueSurfaceProfileJobWithToken, requestAssetHeightDecisionWithToken } from "@/lib/core-api/measurement";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { parseProfileRequestBody } from "@/lib/measurement-requests";

// 한 요청이 Core에 두 번 쓴다(판정, 작업). 키를 파생하므로 원래 키는 두 접미사가 붙어도 255자 안이어야 한다.
const IDEMPOTENCY_KEY = /^[\x21-\x7e]{1,240}$/;

/**
 * 날짜(자료)별 단면 요청. 브라우저는 자료와 저장된 선 개정만 말한다. 높이 판정은 Core가 자료 참조로 내리고,
 * 판정이 막히면 작업을 만들지 않고 사유를 그대로 돌려준다. 같은 키로 다시 보내도 판정과 작업이 중복되지 않는다.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    const token = await getSessionToken();
    const { siteId, workAreaId } = await params;
    const key = request.headers.get("idempotency-key");
    if (key === null || !IDEMPOTENCY_KEY.test(key)) {
      return NextResponse.json({ message: "요청 형식이 올바르지 않습니다." }, { status: 400 });
    }
    const body = parseProfileRequestBody(await request.json());
    if (body === null) {
      return NextResponse.json({ message: "요청 형식이 올바르지 않습니다.", code: "INVALID" }, { status: 422 });
    }
    const site = decodeURIComponent(siteId);
    const area = decodeURIComponent(workAreaId);
    const decision = await requestAssetHeightDecisionWithToken(site, area, body.assetRef, `${key}:height`, token);
    if (decision.verdict !== "ELIGIBLE") {
      return NextResponse.json(
        { message: "높이를 읽을 수 있는 자료로 확인되지 않아 단면을 요청하지 않았습니다.", code: "HEIGHT_NOT_ELIGIBLE", decision: { verdict: decision.verdict, reasons: decision.reasons, remediations: decision.remediations } },
        { status: 409 },
      );
    }
    const job = await issueSurfaceProfileJobWithToken(
      site,
      area,
      {
        assetRef: body.assetRef,
        feature: body.feature,
        heightDecisionId: decision.decisionId,
        ...(body.sampleSpacingM !== undefined ? { sampleSpacingM: body.sampleSpacingM } : {}),
      },
      `${key}:job`,
      token,
    );
    return NextResponse.json({ job });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
