import { NextResponse, type NextRequest } from "next/server";

import { listOrganizationWorkRoster } from "@/lib/core-api/work-collaboration";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function GET(request: NextRequest) {
  try {
    await getSessionToken();
    const search = request.nextUrl.searchParams.get("search") ?? "";
    const includeInactive = request.nextUrl.searchParams.get("includeInactive") === "true";
    return NextResponse.json(await listOrganizationWorkRoster({ includeInactive, search }));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
