import { NextResponse, type NextRequest } from "next/server";

import { approveExternalReobservationProposal } from "@/lib/core-api/external-result-workflow";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

const proposalRef = /^erop-v1-[0-9a-f]{64}$/;
const exactKeys = (value: Record<string, unknown>, keys: readonly string[]) =>
  Object.keys(value).length === keys.length && Object.keys(value).every((key) => keys.includes(key));

export async function POST(request: NextRequest) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  try {
    await getSessionToken();
    const idempotencyKey = request.headers.get("idempotency-key")?.trim();
    const value = await request.json().catch(() => null);
    if (
      !idempotencyKey ||
      idempotencyKey.length > 255 ||
      !value ||
      typeof value !== "object" ||
      Array.isArray(value) ||
      !exactKeys(value as Record<string, unknown>, ["proposalRef", "expectedVersion"]) ||
      typeof (value as { proposalRef?: unknown }).proposalRef !== "string" ||
      !proposalRef.test((value as { proposalRef: string }).proposalRef) ||
      typeof (value as { expectedVersion?: unknown }).expectedVersion !== "number" ||
      !Number.isSafeInteger((value as { expectedVersion: number }).expectedVersion) ||
      (value as { expectedVersion: number }).expectedVersion < 1
    ) {
      return NextResponse.json({ code: "INVALID_EXTERNAL_REOBSERVATION_APPROVAL_INTENT" }, { status: 400 });
    }
    const body = value as { proposalRef: string; expectedVersion: number };
    return NextResponse.json(await approveExternalReobservationProposal(body.proposalRef, body.expectedVersion, idempotencyKey));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
