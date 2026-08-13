import { NextResponse, type NextRequest } from "next/server";

import { setProgressBaseline } from "@/lib/core-api/design";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/**
 * 이 리포트를 "원지형 기준"으로 지정한다(M4-C) — 계획 물량이 여기서 나온다.
 *
 * 덮어쓸 수 있다 — 잘못 지정하는 일이 실제로 있고, 이전 지정도 원장에 남아
 * 되짚어진다.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ missionId: string; designConformanceId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { missionId, designConformanceId } = await params;
    const body = (await request.json()) as { designSurfaceId: string };
    const result = await setProgressBaseline(
      decodeURIComponent(missionId),
      decodeURIComponent(designConformanceId),
      body.designSurfaceId,
    );
    return NextResponse.json(result, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
