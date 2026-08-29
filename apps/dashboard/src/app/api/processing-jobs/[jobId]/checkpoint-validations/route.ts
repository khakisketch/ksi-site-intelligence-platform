import { NextResponse, type NextRequest } from "next/server";

import { listCheckpointValidations } from "@/lib/core-api/checkpoint-validations";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/** Existing validation history for one processing epoch. */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ jobId: string }> },
) {
  try {
    await getSessionToken();
    const { jobId } = await params;
    return NextResponse.json(await listCheckpointValidations(decodeURIComponent(jobId)));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
