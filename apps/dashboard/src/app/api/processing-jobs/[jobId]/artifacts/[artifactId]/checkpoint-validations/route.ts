import { NextResponse, type NextRequest } from "next/server";

import { registerCheckpointValidation } from "@/lib/core-api/checkpoint-validations";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import type { CheckpointValidationRegisterInput } from "@/lib/core-api/types";

/**
 * Register a CSV claim only. File bytes deliberately bypass this proxy and go
 * from the browser to Core's presigned object URL.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ jobId: string; artifactId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { jobId, artifactId } = await params;
    const input = (await request.json()) as CheckpointValidationRegisterInput;
    return NextResponse.json(
      await registerCheckpointValidation(
        decodeURIComponent(jobId),
        decodeURIComponent(artifactId),
        input,
      ),
      { status: 201 },
    );
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
