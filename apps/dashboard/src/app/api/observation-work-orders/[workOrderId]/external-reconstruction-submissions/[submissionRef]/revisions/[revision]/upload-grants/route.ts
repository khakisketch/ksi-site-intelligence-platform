import { NextRequest, NextResponse } from "next/server";
import { CoreApiError } from "@/lib/core-api/client";
import { requestExternalReconstructionUploadGrants } from "@/lib/core-api/external-reconstruction";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { getSessionToken } from "@/lib/core-api/session";
export async function POST(request: NextRequest, context: { params: Promise<{ workOrderId: string; submissionRef: string; revision: string }> }) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  await getSessionToken();
  const { workOrderId, submissionRef, revision } = await context.params;
  try { return NextResponse.json({ grants: await requestExternalReconstructionUploadGrants(workOrderId, submissionRef, Number(revision)) }); }
  catch (error) { if (error instanceof CoreApiError) return NextResponse.json({ code: error.code }, { status: error.status }); throw error; }
}
