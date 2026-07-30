import { NextResponse, type NextRequest } from "next/server";

import { registerSite } from "@/lib/core-api/sites";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";

export async function POST(request: NextRequest) {
  try {
    const input = await request.json();
    const site = await registerSite(input);
    return NextResponse.json({ site }, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
