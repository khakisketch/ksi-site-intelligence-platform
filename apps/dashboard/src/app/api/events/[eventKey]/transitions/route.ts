import { NextResponse, type NextRequest } from "next/server";

import { transitionEvent } from "@/lib/core-api/events";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ eventKey: string }> },
) {
  try {
    const { eventKey } = await params;
    const input = await request.json();
    const result = await transitionEvent(decodeURIComponent(eventKey), input);
    return NextResponse.json(result);
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
