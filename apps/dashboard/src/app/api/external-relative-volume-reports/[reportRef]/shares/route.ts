import { NextResponse, type NextRequest } from "next/server";

import { createExternalRelativeVolumeReportShare } from "@/lib/core-api/work-collaboration";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function POST(request: NextRequest, { params }: { params: Promise<{ reportRef: string }> }) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  try {
    await getSessionToken();
    const body: unknown = await request.json();
    if (!body || typeof body !== "object" || typeof (body as Record<string, unknown>).recipientPrincipalId !== "string" || !(body as Record<string, string>).recipientPrincipalId.trim()) {
      return NextResponse.json({ message: "공유할 팀원을 선택하세요." }, { status: 400 });
    }
    const { reportRef } = await params;
    return NextResponse.json(await createExternalRelativeVolumeReportShare(
      reportRef,
      (body as { recipientPrincipalId: string }).recipientPrincipalId,
      request.headers.get("idempotency-key")?.trim() ?? "",
    ), { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
