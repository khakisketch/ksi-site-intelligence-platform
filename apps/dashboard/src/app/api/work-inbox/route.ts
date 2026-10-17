import { NextResponse, type NextRequest } from "next/server";

import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { listWorkInbox } from "@/lib/core-api/work-collaboration";
import { resolveWorkInboxContext } from "@/lib/work-inbox-context";

export async function GET(request: NextRequest) {
  try {
    await getSessionToken();
    const after = request.nextUrl.searchParams.get("after") ?? undefined;
    const unreadOnly = request.nextUrl.searchParams.get("unreadOnly") === "true";
    const inbox = await listWorkInbox({ unreadOnly, after });
    // 돌려주는 이 페이지 항목에만 맥락 이름을 덧씌운다(추가 필드, 기존 계약 유지).
    // 확인 실패는 빈 맥락으로 접고 목록 자체는 깨뜨리지 않는다.
    const contextByRef = await resolveWorkInboxContext(inbox.items).catch(() => ({}));
    return NextResponse.json({ ...inbox, contextByRef });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
