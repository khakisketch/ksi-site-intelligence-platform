import { NextResponse, type NextRequest } from "next/server";

import {
  issueExternalSingleVolume,
  listExternalSingleVolumeRequests,
} from "@/lib/core-api/external-result-workflow";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

const workOrderRef = /^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$/;
const decisionRef = /^external-use-decision-[0-9a-f]{32}$/;
const exactKeys = (value: Record<string, unknown>, keys: readonly string[]) =>
  Object.keys(value).length === keys.length && Object.keys(value).every((key) => keys.includes(key));

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ workOrderId: string }> },
) {
  try {
    await getSessionToken();
    const { workOrderId } = await params;
    if (!workOrderRef.test(workOrderId)) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
    return NextResponse.json({ items: await listExternalSingleVolumeRequests(workOrderId) });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ workOrderId: string }> },
) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  try {
    await getSessionToken();
    const { workOrderId } = await params;
    const idempotencyKey = request.headers.get("idempotency-key")?.trim();
    const value = await request.json().catch(() => null);
    if (
      !workOrderRef.test(workOrderId) ||
      !idempotencyKey ||
      idempotencyKey.length > 255 ||
      !value ||
      typeof value !== "object" ||
      Array.isArray(value) ||
      !exactKeys(value as Record<string, unknown>, ["decisionRef"]) ||
      typeof (value as { decisionRef?: unknown }).decisionRef !== "string" ||
      !decisionRef.test((value as { decisionRef: string }).decisionRef)
    ) {
      return NextResponse.json({ code: "INVALID_EXTERNAL_SINGLE_VOLUME_INTENT" }, { status: 400 });
    }
    const result = await issueExternalSingleVolume(workOrderId, (value as { decisionRef: string }).decisionRef, idempotencyKey);
    return NextResponse.json(result, { status: result.verdict === "ISSUED" ? 201 : 200 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
