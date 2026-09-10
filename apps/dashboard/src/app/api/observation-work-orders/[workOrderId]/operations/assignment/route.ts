import { NextResponse, type NextRequest } from "next/server";

import { assignObservationWorkOrderToMe } from "@/lib/core-api/observation-work-orders";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ workOrderId: string }> },
) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  try {
    await getSessionToken();
    const { workOrderId } = await params;
    const body: unknown = await request.json();
    if (!isAssignmentInput(body)) {
      return NextResponse.json({ message: "담당 지정 요청 형식이 올바르지 않습니다." }, { status: 400 });
    }
    return NextResponse.json(await assignObservationWorkOrderToMe(
      workOrderId,
      body.expectedOperationsRevision,
      body.action,
      request.headers.get("idempotency-key")?.trim() ?? "",
      body.action === "ASSIGN_TO_MEMBER" ? body.assigneePrincipalId : undefined,
    ));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

type AssignmentInput = {
  expectedOperationsRevision: number;
  action: "ASSIGN_TO_ME" | "CLEAR" | "ASSIGN_TO_MEMBER";
  assigneePrincipalId?: string;
};

function isAssignmentInput(value: unknown): value is AssignmentInput {
  if (!value || typeof value !== "object") return false;
  const body = value as Record<string, unknown>;
  if (!Number.isInteger(body.expectedOperationsRevision) || (body.expectedOperationsRevision as number) < 0) return false;
  if (body.action !== "ASSIGN_TO_ME" && body.action !== "CLEAR" && body.action !== "ASSIGN_TO_MEMBER") return false;
  if (body.action === "ASSIGN_TO_MEMBER") {
    return typeof body.assigneePrincipalId === "string" && body.assigneePrincipalId.trim().length > 0 && body.assigneePrincipalId.length <= 255;
  }
  return body.assigneePrincipalId === undefined;
}
