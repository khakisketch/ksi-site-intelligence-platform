import { NextResponse, type NextRequest } from "next/server";

import { sealCheckpointValidation } from "@/lib/core-api/checkpoint-validations";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

/** Seal the upload; a trusted worker recomputes digest, size, and DSM residuals. */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ validationId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { validationId } = await params;
    return NextResponse.json(await sealCheckpointValidation(decodeURIComponent(validationId)), {
      status: 201,
    });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
