import { NextResponse, type NextRequest } from "next/server";

import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { updateOrganizationWorkRosterMember, type UpdateOrganizationWorkRosterMemberInput } from "@/lib/core-api/work-collaboration";

export async function PUT(request: NextRequest, { params }: { params: Promise<{ principalId: string }> }) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  try {
    await getSessionToken();
    const input: unknown = await request.json();
    if (!isRosterInput(input)) return NextResponse.json({ message: "팀원 정보 형식이 올바르지 않습니다." }, { status: 400 });
    const { principalId } = await params;
    if (!principalId.trim()) return NextResponse.json({ message: "팀원 식별자가 필요합니다." }, { status: 400 });
    return NextResponse.json(await updateOrganizationWorkRosterMember(
      principalId,
      input,
      request.headers.get("idempotency-key")?.trim() ?? "",
    ));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

function isRosterInput(value: unknown): value is UpdateOrganizationWorkRosterMemberInput {
  if (!value || typeof value !== "object") return false;
  const input = value as Record<string, unknown>;
  return Number.isInteger(input.expectedRevision) && (input.expectedRevision as number) >= 0
    && typeof input.displayName === "string" && input.displayName.trim().length > 0 && input.displayName.length <= 120
    && (input.roleHint === "ADMIN" || input.roleHint === "FIELD_OPERATOR" || input.roleHint === "VIEWER")
    && (input.status === "ACTIVE" || input.status === "INACTIVE");
}
