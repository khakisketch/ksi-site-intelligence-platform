import { NextResponse, type NextRequest } from "next/server";

import { issueMissionPlan } from "@/lib/core-api/mission-plans";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";

export async function POST(request: NextRequest) {
  try {
    const input = await request.json();
    const plan = await issueMissionPlan(input);
    return NextResponse.json(plan, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
