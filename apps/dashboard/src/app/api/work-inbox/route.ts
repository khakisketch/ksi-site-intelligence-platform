import { NextResponse, type NextRequest } from "next/server";

import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { listWorkInbox } from "@/lib/core-api/work-collaboration";

export async function GET(request: NextRequest) {
  try {
    await getSessionToken();
    const after = request.nextUrl.searchParams.get("after") ?? undefined;
    const unreadOnly = request.nextUrl.searchParams.get("unreadOnly") === "true";
    return NextResponse.json(await listWorkInbox({ unreadOnly, after }));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
