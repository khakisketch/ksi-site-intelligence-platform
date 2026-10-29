import { NextResponse } from "next/server";
import { getSpatialTask } from "@/lib/core-api/spatial-tasks";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function GET(_request: Request, { params }: { params: Promise<{ siteId: string; taskId: string }> }) {
  try {
    await getSessionToken();
    const { siteId, taskId } = await params;
    return NextResponse.json(await getSpatialTask(siteId, taskId), { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
