import { NextResponse, type NextRequest } from "next/server";

import { getExternalResultReview } from "@/lib/core-api/external-result-workflow";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

const reviewRef = /^err-v1-[0-9a-f]{64}$/;

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ reviewRef: string }> },
) {
  try {
    await getSessionToken();
    const { reviewRef: value } = await params;
    if (!reviewRef.test(value)) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
    return NextResponse.json(await getExternalResultReview(value));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
