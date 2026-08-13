import { NextResponse, type NextRequest } from "next/server";

import { getDesignProgress } from "@/lib/core-api/design";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/**
 * 구역별 계획 대비 진척(M4-C) — **저장된 값이 아니라 파생값**이다.
 *
 * 200 이 항상 성공을 뜻하지 않는다 — 응답의 `progress`/`detail` 중 하나는 항상
 * 채워진다(`getDesignProgress` 참조). 화면이 그 구분으로 분기한다.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId } = await params;
    const designSurfaceId = request.nextUrl.searchParams.get("design_surface_id");
    if (!designSurfaceId) {
      return NextResponse.json(
        { message: "design_surface_id 쿼리 파라미터가 필요합니다." },
        { status: 400 },
      );
    }
    return NextResponse.json(
      await getDesignProgress(decodeURIComponent(siteId), designSurfaceId),
    );
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
