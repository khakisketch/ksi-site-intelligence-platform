import { NextResponse, type NextRequest } from "next/server";

import { createMeasurementFeatureWithToken } from "@/lib/core-api/measurement";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { parseCreateLineBody } from "@/lib/measurement-line";

const IDEMPOTENCY_KEY = /^[\x21-\x7e]{1,255}$/;

/**
 * 측정 선 저장. 형식이 맞지 않으면 Core에 보내지 않는다. 구역 범위와 쓰기 권한은 Core가 현재 권한으로 다시 확인하며,
 * 본문의 구역이 주소의 구역과 다르면 어느 쪽도 믿지 않고 거부한다.
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
    const body = parseCreateLineBody(await request.json());
    const area = decodeURIComponent(workAreaId);
    if (body === null || body.workAreaId !== area) {
      return NextResponse.json({ message: "요청 형식이 올바르지 않습니다.", code: "INVALID" }, { status: 422 });
    }
    const revision = await createMeasurementFeatureWithToken(decodeURIComponent(siteId), area, body, key, token);
    return NextResponse.json({ revision }, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
