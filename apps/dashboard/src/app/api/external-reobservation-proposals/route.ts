import { NextResponse, type NextRequest } from "next/server";

import { createExternalReobservationProposal } from "@/lib/core-api/external-result-workflow";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { isExternalRelativeVolumeReportReference } from "@/lib/external-relative-volume-references";
import { isExternalSingleVolumeReportReference } from "@/lib/external-single-volume-references";

const safeRef = /^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$/;
const isEitherFamilyReportRef = (value: unknown): value is string =>
  isExternalRelativeVolumeReportReference(value) || isExternalSingleVolumeReportReference(value);
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
      !exactKeys(value as Record<string, unknown>, ["reportRef", "targetWorkAreaIds", "reason"]) ||
      !isEitherFamilyReportRef((value as { reportRef?: unknown }).reportRef) ||
      !Array.isArray((value as { targetWorkAreaIds?: unknown }).targetWorkAreaIds) ||
      (value as { targetWorkAreaIds: unknown[] }).targetWorkAreaIds.length !== 1 ||
      typeof (value as { targetWorkAreaIds: unknown[] }).targetWorkAreaIds[0] !== "string" ||
      !safeRef.test((value as { targetWorkAreaIds: string[] }).targetWorkAreaIds[0]) ||
      ((value as { reason?: unknown }).reason !== null &&
        (typeof (value as { reason?: unknown }).reason !== "string" ||
          !(value as { reason: string }).reason.trim() ||
          (value as { reason: string }).reason.length > 1000))
    ) {
      return NextResponse.json({ code: "INVALID_EXTERNAL_REOBSERVATION_PROPOSAL_INTENT" }, { status: 400 });
    }
    const body = value as { reportRef: string; targetWorkAreaIds: [string]; reason: string | null };
    return NextResponse.json(await createExternalReobservationProposal({ ...body, reason: body.reason?.trim() ?? null }, idempotencyKey), { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
