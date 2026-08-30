import { NextResponse, type NextRequest } from "next/server";

import { recordReportExport } from "@/lib/core-api/report-exports";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import type { ReportExportCreateInput } from "@/lib/core-api/types";

/**
 * 브라우저가 만들 PDF/CSV에 앞서 Core가 감사 스냅샷을 기록하는 same-origin BFF다.
 *
 * 이 라우트도 파일 바이트를 받거나 만들지 않는다. 세션·Origin 검사를 통과한
 * 입력만 Core에 중계하므로, 브라우저가 받은 `contentProducedByServer=false`는
 * "서버가 PDF/CSV를 보관했다"는 뜻으로 읽히면 안 된다.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }

  try {
    // 본문을 읽기 전에 세션부터 확인한다. 무인증 hostile JSON은 422/500이 아니라 401이다.
    await getSessionToken();
    const { siteId } = await params;
    const input = (await request.json()) as ReportExportCreateInput;
    const result = await recordReportExport(decodeURIComponent(siteId), input);
    return NextResponse.json(result, {
      status: result.verdict === "RECORDED" ? 201 : 200,
    });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
