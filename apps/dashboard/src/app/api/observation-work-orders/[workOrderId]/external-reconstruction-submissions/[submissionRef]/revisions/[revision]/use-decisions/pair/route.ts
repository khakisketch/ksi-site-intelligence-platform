import { NextRequest, NextResponse } from "next/server";
import { CoreApiError } from "@/lib/core-api/client";
import { requestExternalPairUseDecision } from "@/lib/core-api/external-reconstruction";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { getSessionToken } from "@/lib/core-api/session";

const workOrder = /^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$/;
const submission = /^ers-v1-[0-9a-f]{64}$/;
const safeRevision = (value: string) => Number.isSafeInteger(Number(value)) && Number(value) >= 1 && String(Number(value)) === value ? Number(value) : null;
export async function POST(request: NextRequest, context: { params: Promise<{ workOrderId: string; submissionRef: string; revision: string }> }) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  await getSessionToken(); const params = await context.params; const revision = safeRevision(params.revision); const idempotencyKey = request.headers.get("idempotency-key")?.trim(); const value = await request.json().catch(() => null);
  if (!workOrder.test(params.workOrderId) || !submission.test(params.submissionRef) || revision === null) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
  if (!idempotencyKey || idempotencyKey.length > 255 || !value || typeof value !== "object" || Array.isArray(value)) return NextResponse.json({ code: "INVALID_EXTERNAL_PAIR_INTENT" }, { status: 400 });
  const body = value as Record<string, unknown>; const allowed = ["use", "baselineWorkOrderId", "baselineSubmissionRef", "baselineRevision", "zoneId"];
  if (Object.keys(body).some((name) => !allowed.includes(name)) || (body.use !== "VISUAL_COMPARISON" && body.use !== "RELATIVE_VOLUME") || typeof body.baselineWorkOrderId !== "string" || !workOrder.test(body.baselineWorkOrderId) || typeof body.baselineSubmissionRef !== "string" || !submission.test(body.baselineSubmissionRef) || typeof body.baselineRevision !== "number" || !Number.isSafeInteger(body.baselineRevision) || body.baselineRevision < 1 || (body.zoneId !== undefined && body.zoneId !== null && (typeof body.zoneId !== "string" || body.zoneId.trim().length < 1 || body.zoneId.trim().length > 255))) return NextResponse.json({ code: "INVALID_EXTERNAL_PAIR_INTENT" }, { status: 400 });
  try { return NextResponse.json(await requestExternalPairUseDecision(params.workOrderId, params.submissionRef, revision, body as { use: "VISUAL_COMPARISON" | "RELATIVE_VOLUME"; baselineWorkOrderId: string; baselineSubmissionRef: string; baselineRevision: number; zoneId?: string | null }, idempotencyKey), { status: 201 }); } catch (error) { if (error instanceof CoreApiError) return NextResponse.json({ code: error.code }, { status: error.status }); throw error; }
}
