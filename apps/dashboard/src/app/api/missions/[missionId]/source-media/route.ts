import { NextResponse, type NextRequest } from "next/server";

import { getSourceMediaBundle, registerSourceMedia } from "@/lib/core-api/source-media";
import { CoreApiError } from "@/lib/core-api/client";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/** 현재 번들 상태 — 등록된 적 없으면(404) 업로드 패널이 시작 상태로 그린다. */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ missionId: string }> },
) {
  try {
    await getSessionToken();
    const { missionId } = await params;
    const bundle = await getSourceMediaBundle(decodeURIComponent(missionId));
    return NextResponse.json(bundle);
  } catch (error) {
    if (error instanceof CoreApiError && error.status === 404) {
      return NextResponse.json(null, { status: 200 });
    }
    return coreApiErrorResponse(error);
  }
}

/**
 * 원본 사진 배치 등록 — presigned PUT URL 목록을 돌려준다(B1).
 *
 * 파일 바이트는 이 핸들러를 거치지 않는다 — 브라우저가 응답의 uploadUrl 로
 * 스토리지에 직접 PUT 한다(evidence/route.ts 와 동일 관습).
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ missionId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    // 세션을 본문 파싱보다 먼저 — 무인증+깨진 입력이 500 이 아니라 401 로 끊긴다.
    await getSessionToken();
    const { missionId } = await params;
    const input = (await request.json()) as { files: unknown };
    const result = await registerSourceMedia(
      decodeURIComponent(missionId),
      input.files as Parameters<typeof registerSourceMedia>[1],
    );
    return NextResponse.json(result, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
