import { NextResponse, type NextRequest } from "next/server";

import {
  createObservationWorkOrder,
  listObservationWorkOrders,
  type CreateObservationWorkOrderInput,
} from "@/lib/core-api/observation-work-orders";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/** 현장 안에서 새 관측 작업 초안을 만들거나 현재 원장을 읽는다. */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId } = await params;
    return NextResponse.json({
      workOrders: await listObservationWorkOrders(decodeURIComponent(siteId)),
    });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { siteId } = await params;
    const input = (await request.json()) as CreateObservationWorkOrderInput;
    const idempotencyKey = request.headers.get("idempotency-key") ?? undefined;
    return NextResponse.json(
      await createObservationWorkOrder(decodeURIComponent(siteId), input, idempotencyKey),
      { status: 201 },
    );
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
