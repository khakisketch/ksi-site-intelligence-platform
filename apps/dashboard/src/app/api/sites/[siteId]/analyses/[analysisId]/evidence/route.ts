import { NextResponse, type NextRequest } from "next/server";

import { getAnalysisEvidence } from "@/lib/core-api/analysis";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function GET(request: NextRequest, { params }: { params: Promise<{ siteId: string; analysisId: string }> }) {
  try {
    await getSessionToken();
    const query = new URL(request.url).searchParams;
    const limits = query.getAll("limit");
    const cursors = query.getAll("cursor");
    const rawLimit = limits[0] ?? "32";
    const limit = /^(?:[1-9]|[12][0-9]|3[0-2])$/.test(rawLimit) ? Number(rawLimit) : null;
    const cursor = cursors[0];
    if (
      limits.length > 1
      || cursors.length > 1
      || limit === null
      || cursor !== undefined && !/^[A-Za-z0-9_-]{1,512}$/.test(cursor)
    ) {
      return NextResponse.json({ message: "페이지 요청 형식이 올바르지 않습니다." }, { status: 400 });
    }
    const { siteId, analysisId } = await params;
    return NextResponse.json(
      await getAnalysisEvidence(decodeURIComponent(siteId), decodeURIComponent(analysisId), { limit, cursor }),
    );
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
