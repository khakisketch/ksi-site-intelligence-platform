import { NextRequest, NextResponse } from "next/server";

import { CoreApiError } from "@/lib/core-api/client";
import { declareExternalEvidence, listExternalEvidence } from "@/lib/core-api/external-reconstruction";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { getSessionToken } from "@/lib/core-api/session";

const ref = /^ers-v1-[0-9a-f]{64}$/;
function revisionOf(params: { workOrderId: string; submissionRef: string; revision: string }): number | null {
  const value = Number(params.revision);
  return /^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$/.test(params.workOrderId) && ref.test(params.submissionRef) && Number.isSafeInteger(value) && value >= 1 && String(value) === params.revision ? value : null;
}
function key(request: Request): string | null { const value = request.headers.get("idempotency-key")?.trim(); return value && value.length <= 255 ? value : null; }
function intent(value: unknown): { targetDsmArtifactId: string; declaredContentDigest: string; declaredContentType: string; independenceBasis: string } | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  if (Object.keys(raw).length !== 4 || !Object.keys(raw).every((name) => ["targetDsmArtifactId", "declaredContentDigest", "declaredContentType", "independenceBasis"].includes(name))) return null;
  return typeof raw.targetDsmArtifactId === "string" && raw.targetDsmArtifactId.length >= 1 && raw.targetDsmArtifactId.length <= 255 && /^sha256:[0-9a-f]{64}$/.test(String(raw.declaredContentDigest)) && typeof raw.declaredContentType === "string" && raw.declaredContentType.trim().length >= 1 && raw.declaredContentType.trim().length <= 255 && typeof raw.independenceBasis === "string" && raw.independenceBasis.trim().length >= 1 && raw.independenceBasis.trim().length <= 1000 ? raw as { targetDsmArtifactId: string; declaredContentDigest: string; declaredContentType: string; independenceBasis: string } : null;
}
function errorResponse(error: unknown) { return error instanceof CoreApiError ? NextResponse.json({ code: error.code }, { status: error.status }) : null; }
export async function GET(_request: Request, context: { params: Promise<{ workOrderId: string; submissionRef: string; revision: string }> }) {
  await getSessionToken(); const params = await context.params; const revision = revisionOf(params);
  if (revision === null) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
  try { return NextResponse.json({ items: await listExternalEvidence(params.workOrderId, params.submissionRef, revision) }); } catch (error) { const response = errorResponse(error); if (response) return response; throw error; }
}
export async function POST(request: NextRequest, context: { params: Promise<{ workOrderId: string; submissionRef: string; revision: string }> }) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  await getSessionToken(); const params = await context.params; const revision = revisionOf(params); const idempotencyKey = key(request); const body = intent(await request.json().catch(() => null));
  if (revision === null) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
  if (!idempotencyKey || !body) return NextResponse.json({ code: "INVALID_EVIDENCE_INTENT" }, { status: 400 });
  try { return NextResponse.json(await declareExternalEvidence(params.workOrderId, params.submissionRef, revision, body, idempotencyKey), { status: 201 }); } catch (error) { const response = errorResponse(error); if (response) return response; throw error; }
}
