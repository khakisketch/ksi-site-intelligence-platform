import { NextResponse, type NextRequest } from "next/server";

import { declareMissionExecutionTransition } from "@/lib/core-api/missions";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import type { MissionExecutionTransitionInput } from "@/lib/core-api/missions";

/**
 * 임무 실행 상태 선언 — 지금은 현장 화면의 [수동 이관 신고]가 유일한 호출부다
 * (자동 전달이 확인되지 않을 때 `DISPATCHED` 를 사람이 선언한다). 신규 서버 API가
 * 아니라 이미 있던 mission_execution.py 전이 엔드포인트를 그대로 감싼다.
 *
 * 권한·허용 전이 판정은 전부 Core 가 한다(MISSIONS_ISSUE, 상태별 허용표) — 이
 * 라우트는 세션·출처만 앞단에서 끊는다(다른 mutating 라우트와 같은 패턴).
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
    const input = (await request.json()) as MissionExecutionTransitionInput;
    const view = await declareMissionExecutionTransition(decodeURIComponent(missionId), input);
    return NextResponse.json(view);
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
