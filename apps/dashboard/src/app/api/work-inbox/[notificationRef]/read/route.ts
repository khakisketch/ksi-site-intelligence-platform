import { NextResponse, type NextRequest } from "next/server";

import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { markWorkInboxItemRead } from "@/lib/core-api/work-collaboration";

export async function POST(request: NextRequest, { params }: { params: Promise<{ notificationRef: string }> }) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  try {
    await getSessionToken();
    const { notificationRef } = await params;
    return NextResponse.json(await markWorkInboxItemRead(
      notificationRef,
      request.headers.get("idempotency-key")?.trim() ?? "",
    ));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
