import { NextResponse, type NextRequest } from "next/server";

import { reviseMeasurementFeatureWithToken } from "@/lib/core-api/measurement";
import { FEATURE_ID_PATTERN } from "@/lib/core-api/measurement-types";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { parseReviseLineBody } from "@/lib/measurement-line";

const IDEMPOTENCY_KEY = /^[\x21-\x7e]{1,255}$/;

/** 측정 선 고치기(새 개정). 본 개정 번호를 싣지 않으면 다른 사람의 편집을 덮어쓸 수 있어 형식 단계에서 거부한다. */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string; featureId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    const token = await getSessionToken();
    const { siteId, workAreaId, featureId } = await params;
    const key = request.headers.get("idempotency-key");
    if (!FEATURE_ID_PATTERN.test(featureId) || key === null || !IDEMPOTENCY_KEY.test(key)) {
      return NextResponse.json({ message: "요청 형식이 올바르지 않습니다." }, { status: 400 });
    }
    const body = parseReviseLineBody(await request.json());
    if (body === null) {
      return NextResponse.json({ message: "요청 형식이 올바르지 않습니다.", code: "INVALID" }, { status: 422 });
    }
    const revision = await reviseMeasurementFeatureWithToken(
      decodeURIComponent(siteId), decodeURIComponent(workAreaId), featureId, body, key, token,
    );
    return NextResponse.json({ revision }, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
