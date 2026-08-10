import { NextResponse, type NextRequest } from "next/server";

import { sealSourceMedia } from "@/lib/core-api/source-media";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/** 원본 사진 번들 봉인 — 이후 추가 등록은 BUNDLE_SEALED 로 거부된다. */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ missionId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { missionId } = await params;
    const result = await sealSourceMedia(decodeURIComponent(missionId));
    return NextResponse.json(result, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
