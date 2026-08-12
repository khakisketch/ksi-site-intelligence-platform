import { NextResponse, type NextRequest } from "next/server";

import { getDiffRasterView } from "@/lib/core-api/design";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/**
 * 차분 래스터의 단기 열람 URL — 히트맵이 마운트 시점에 직접 부른다.
 *
 * presigned URL 은 수명이 분 단위라 서버 컴포넌트가 미리 발급해 prop 으로
 * 넘기면 클라이언트가 쓸 때 이미 만료돼 있을 수 있다(정사영상 오버레이와 같은
 * 이유). 바이트 자체는 이 라우트를 통과하지 않는다 — 브라우저가 스토리지에서
 * 직접 받는다.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ missionId: string; designConformanceId: string }> },
) {
  try {
    await getSessionToken();
    const { missionId, designConformanceId } = await params;
    return NextResponse.json(
      await getDiffRasterView(
        decodeURIComponent(missionId),
        decodeURIComponent(designConformanceId),
      ),
    );
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
