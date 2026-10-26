import { NextResponse, type NextRequest } from "next/server";

import { getSpatialAssetDescription } from "@/lib/core-api/spatial-asset-description";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

const assetRefPattern = /^ksa-v1-[0-9a-f]{64}$/;

/**
 * 단일 자료 출처 판독 BFF — 카탈로그 뒤의 provenance·격자 상세를 그대로
 * 옮긴다. 바이트·다운로드·분석 판정을 주지 않으며, 모르는 참조는
 * 404로 닫는다(존재 여부를 단정하지 않는다).
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string; assetRef: string }> },
) {
  try {
    await getSessionToken();
    const { siteId, workAreaId, assetRef } = await params;
    const decodedAssetRef = decodeURIComponent(assetRef);
    if (!assetRefPattern.test(decodedAssetRef)) {
      return NextResponse.json({ message: "대상을 찾을 수 없습니다." }, { status: 404 });
    }
    return NextResponse.json(
      await getSpatialAssetDescription(decodeURIComponent(siteId), decodeURIComponent(workAreaId), decodedAssetRef),
    );
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
