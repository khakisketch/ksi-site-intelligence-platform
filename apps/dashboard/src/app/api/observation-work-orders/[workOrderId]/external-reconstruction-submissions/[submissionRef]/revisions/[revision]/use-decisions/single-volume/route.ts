import { NextResponse, type NextRequest } from "next/server";

import { requestExternalSingleVolumeDecision } from "@/lib/core-api/external-reconstruction";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

const workOrderRef = /^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$/;
const submissionRef = /^ers-v1-[0-9a-f]{64}$/;
const exactKeys = (value: Record<string, unknown>, keys: readonly string[]) =>
  Object.keys(value).length === keys.length && Object.keys(value).every((key) => keys.includes(key));

function safeRevision(value: string): number | null {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 1 && String(parsed) === value ? parsed : null;
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ workOrderId: string; submissionRef: string; revision: string }> },
) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  try {
    await getSessionToken();
    const value = await params;
    const revision = safeRevision(value.revision);
    if (!workOrderRef.test(value.workOrderId) || !submissionRef.test(value.submissionRef) || revision === null) {
      return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
    }
    const idempotencyKey = request.headers.get("idempotency-key")?.trim();
    const body = await request.json().catch(() => null);
    if (
      !idempotencyKey ||
      idempotencyKey.length > 255 ||
      !body ||
      typeof body !== "object" ||
      Array.isArray(body) ||
      !exactKeys(body as Record<string, unknown>, ["zoneId"]) ||
      typeof (body as { zoneId?: unknown }).zoneId !== "string" ||
      (body as { zoneId: string }).zoneId.length < 1 ||
      (body as { zoneId: string }).zoneId.length > 255
    ) {
      return NextResponse.json({ code: "INVALID_EXTERNAL_SINGLE_VOLUME_INTENT" }, { status: 400 });
    }
    const result = await requestExternalSingleVolumeDecision(
      value.workOrderId,
      value.submissionRef,
      revision,
      (body as { zoneId: string }).zoneId,
      idempotencyKey,
    );
    return NextResponse.json(result, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
