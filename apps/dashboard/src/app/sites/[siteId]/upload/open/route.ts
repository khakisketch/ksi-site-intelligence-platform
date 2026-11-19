import { NextResponse, type NextRequest } from "next/server";

import { siteDataHref } from "@/components/nav/site-context";
import { listSpatialAssets } from "@/lib/core-api/spatial-assets";
import { locateUploadedAsset, parseUploadedArtifact } from "@/lib/uploaded-asset-locator";

/**
 * 한 화면 올리기의 완료 화면에서 방금 올린 자료의 상세로 보낸다.
 * 찾지 못하거나 읽지 못하면 같은 구역의 자료 목록으로 보내며, 다른 자료를 대신 고르지 않는다.
 */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  const { siteId } = await params;
  const target = parseUploadedArtifact(request.nextUrl.searchParams);
  let href = siteDataHref(siteId, { workAreaId: target?.workAreaId });
  if (target) {
    try {
      const found = await locateUploadedAsset(siteId, target, (cursor) =>
        listSpatialAssets(siteId, target.workAreaId, cursor
          ? { limit: 50, cursor, order: "capture-desc" }
          : { limit: 50, order: "capture-desc" }));
      if (found) href = `${siteDataHref(siteId, { workAreaId: target.workAreaId, assetRef: found.assetRef, cursor: found.cursor })}#section-inspector`;
    } catch {
      // 목록으로 보낸다. 자료 화면이 권한·장애를 다시 판단해 보여 준다.
    }
  }
  // 상대 주소로 보내 앞단 프록시의 호스트를 추측하지 않는다.
  return new NextResponse(null, { status: 303, headers: { Location: href, "Cache-Control": "private, no-store" } });
}
