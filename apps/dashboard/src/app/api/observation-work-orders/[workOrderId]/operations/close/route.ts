import { NextResponse, type NextRequest } from "next/server";

import { closeObservationWorkOrder } from "@/lib/core-api/observation-work-orders";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ workOrderId: string }> },
) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  try {
    await getSessionToken();
    const { workOrderId } = await params;
    const body = await request.json();
    return NextResponse.json(await closeObservationWorkOrder(
      workOrderId,
      body.expectedOperationsRevision,
      body.note,
      request.headers.get("idempotency-key")?.trim() ?? "",
    ));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
