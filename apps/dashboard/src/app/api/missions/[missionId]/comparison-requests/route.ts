import { NextResponse, type NextRequest } from "next/server";

import { createComparisonRequest, listComparisonRequests } from "@/lib/core-api/comparison";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import type { ComparisonRequestCreateInput } from "@/lib/core-api/types";

/**
 * 비교 요청 제출 — "이 두 시점을 비교하라"는 사람의 지시(MISSIONS_ISSUE).
 *
 * 계산·결과 제출은 워커(PROCESSING_WORK)의 일이고 이 표면은 요청만 만든다.
 * 같은 조합의 재요청은 새 요청을 만들지 않고 기존 것을 돌려준다
 * (ALREADY_REQUESTED, 200) — 오류가 아니라 재사용이다.
 */
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
    const input = (await request.json()) as ComparisonRequestCreateInput;
    const result = await createComparisonRequest(decodeURIComponent(missionId), input);
    // 서버가 신규 생성(CREATED)과 재사용(ALREADY_REQUESTED)을 verdict 로 구분해
    // 주므로 여기서 상태코드를 다시 판단하지 않는다 — 화면이 verdict 를 읽는다.
    return NextResponse.json(result, {
      status: result.verdict === "CREATED" ? 201 : 200,
    });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

/** 그 임무의 비교 요청 이력(최신 먼저) — 새로고침 후 상태 복원. */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ missionId: string }> },
) {
  try {
    await getSessionToken();
    const { missionId } = await params;
    return NextResponse.json(await listComparisonRequests(decodeURIComponent(missionId)));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
