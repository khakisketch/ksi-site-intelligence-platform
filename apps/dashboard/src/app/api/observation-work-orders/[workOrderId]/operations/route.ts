import { NextResponse, type NextRequest } from "next/server";

import { getObservationWorkOrderOperations } from "@/lib/core-api/observation-work-orders";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ workOrderId: string }> },
) {
  try {
    await getSessionToken();
    const { workOrderId } = await params;
    return NextResponse.json(await getObservationWorkOrderOperations(workOrderId));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
