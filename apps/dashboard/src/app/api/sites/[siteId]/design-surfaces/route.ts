import { NextResponse, type NextRequest } from "next/server";

import { listDesignSurfaces, registerDesignSurface } from "@/lib/core-api/design";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import type { DesignSurfaceRegisterInput } from "@/lib/core-api/types";

/**
 * 설계 기준면 등록 — 선언(주장)을 기록하고 presigned PUT 을 발급받는다.
 *
 * 201 은 "파일이 좋다"가 아니라 "어디에 올리면 되는지 정해졌다"는 뜻이다.
 * 파일 바이트는 이 라우트를 통과하지 않는다 — 브라우저가 응답의 uploadUrl 로
 * 스토리지에 직접 PUT 한다(ADR-KSI-010 §1).
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { siteId } = await params;
    const input = (await request.json()) as DesignSurfaceRegisterInput;
    const result = await registerDesignSurface(decodeURIComponent(siteId), input);
    // 같은 선언의 재전송도 REGISTERED(멱등 재발급)로 돌아온다 — 여기서 상태코드를
    // 다시 판단하지 않고 화면이 verdict 를 읽는다(comparison-requests 와 같은 규약).
    return NextResponse.json(result, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

/** 그 현장의 설계면 목록 — 선언·관측·상태·거부 사유를 그대로 넘긴다. */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId } = await params;
    return NextResponse.json(await listDesignSurfaces(decodeURIComponent(siteId)));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
