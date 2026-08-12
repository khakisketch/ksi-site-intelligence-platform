import { NextResponse, type NextRequest } from "next/server";

import { sealDesignSurface } from "@/lib/core-api/design";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/**
 * 설계면 봉인 — **업로드를 마쳤다는 클라이언트의 주장**을 원장에 기록한다.
 *
 * Core 는 여기서 스토리지 바이트를 한 번도 읽지 않는다. 그래서 이 호출의 성공은
 * "파일이 거기 있다"도 "파일이 선언과 같다"도 뜻하지 않는다 — 검증은 워커가
 * 파일을 열어 재고 Core 가 대조하는 별도 단계다(design_surfaces 모듈 docstring).
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; designSurfaceId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { siteId, designSurfaceId } = await params;
    const result = await sealDesignSurface(
      decodeURIComponent(siteId),
      decodeURIComponent(designSurfaceId),
    );
    return NextResponse.json(result, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
