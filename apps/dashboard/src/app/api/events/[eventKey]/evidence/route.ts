import { NextResponse, type NextRequest } from "next/server";

import { registerEvidence } from "@/lib/core-api/events";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/**
 * 증거 업로드 등록 — presigned PUT URL 을 돌려준다(ADR-KSI-010 §1).
 *
 * 파일 바이트는 이 핸들러를 **거치지 않는다**. 브라우저가 받은 URL 로 스토리지에
 * 직접 PUT 한다 — Next 서버가 대용량 업로드 프록시가 되면 같은 프로세스가 처리하는
 * 안전 화면(트리아지)의 응답이 함께 늘어진다.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ eventKey: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    // 세션을 본문 파싱·경로 디코딩보다 먼저 — 무인증+깨진 입력이 500 이 아니라 401 로 끊긴다.
    await getSessionToken();
    const { eventKey } = await params;
    const input = await request.json();
    const result = await registerEvidence(decodeURIComponent(eventKey), input);
    return NextResponse.json(result, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
