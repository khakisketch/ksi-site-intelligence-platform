import { NextResponse, type NextRequest } from "next/server";

import { getCheckpointValidation } from "@/lib/core-api/checkpoint-validations";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/** One immutable validation projection, used while a sealed CSV is measured. */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ validationId: string }> },
) {
  try {
    await getSessionToken();
    const { validationId } = await params;
    return NextResponse.json(await getCheckpointValidation(decodeURIComponent(validationId)));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
