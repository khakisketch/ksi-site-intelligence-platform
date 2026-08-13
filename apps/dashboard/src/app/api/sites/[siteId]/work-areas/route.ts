import { NextResponse, type NextRequest } from "next/server";

import { listWorkAreas, registerWorkArea } from "@/lib/core-api/workAreas";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import type { WorkAreaRegisterInput } from "@/lib/core-api/types";

/**
 * 작업구역 등록 — **기하는 이 순간 굳는다**(M4-C).
 *
 * 고치려면 `supersedes` 로 새 구역을 등록한다 — 이 라우트에 PATCH 가 없는 이유가
 * 그것이다(design-surfaces 라우트에 "수정" 이 없는 것과 같은 이유).
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
    const input = (await request.json()) as WorkAreaRegisterInput;
    const result = await registerWorkArea(decodeURIComponent(siteId), input);
    return NextResponse.json(result, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

/** 그 현장의 작업구역 목록 — 기본은 고를 수 있는 것(ACTIVE)만. */
export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId } = await params;
    const includeArchived = request.nextUrl.searchParams.get("include_archived") === "true";
    return NextResponse.json(
      await listWorkAreas(decodeURIComponent(siteId), { includeArchived }),
    );
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
