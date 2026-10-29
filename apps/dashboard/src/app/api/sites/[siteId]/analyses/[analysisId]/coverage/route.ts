import { NextResponse, type NextRequest } from "next/server";
import { getAnalysisCoverage } from "@/lib/core-api/analysis-coverage";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function GET(request: NextRequest, { params }: { params: Promise<{ siteId: string; analysisId: string }> }) {
  try {
    await getSessionToken();
    if (new URL(request.url).search || request.headers.has("range")) {
      return NextResponse.json({ message: "계산 범위는 화면의 범위 보기에서 확인하세요." }, { status: 400, headers: { "Cache-Control": "private, no-store" } });
    }
    const { siteId, analysisId } = await params;
    const value = await getAnalysisCoverage(decodeURIComponent(siteId), decodeURIComponent(analysisId), request.signal);
    return NextResponse.json(value, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    const response = coreApiErrorResponse(error);
    response.headers.set("Cache-Control", "private, no-store");
    return response;
  }
}
