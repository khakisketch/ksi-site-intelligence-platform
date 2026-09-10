import { NextResponse } from "next/server";

import { CoreApiError } from "@/lib/core-api/client";
import { getExternalSanitizedDisplayDownload } from "@/lib/core-api/external-reconstruction";
import { getSessionToken } from "@/lib/core-api/session";

const submissionRefPattern = /^ers-v1-[0-9a-f]{64}$/;
const displayRefPattern = /^sda-v1-[A-Za-z0-9][A-Za-z0-9_-]{0,247}$/;

function validParams(workOrderId: string, submissionRef: string, revision: string, sanitizedDisplayRef: string): number | null {
  const parsedRevision = Number(revision);
  if (
    !/^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$/.test(workOrderId) ||
    !submissionRefPattern.test(submissionRef) ||
    !displayRefPattern.test(sanitizedDisplayRef) ||
    !Number.isSafeInteger(parsedRevision) ||
    parsedRevision < 1 ||
    String(parsedRevision) !== revision
  ) return null;
  return parsedRevision;
}

export async function GET(_request: Request, context: { params: Promise<{ workOrderId: string; submissionRef: string; revision: string; sanitizedDisplayRef: string }> }) {
  await getSessionToken();
  const { workOrderId, submissionRef, revision, sanitizedDisplayRef } = await context.params;
  const parsedRevision = validParams(workOrderId, submissionRef, revision, sanitizedDisplayRef);
  if (parsedRevision === null) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
  try {
    return NextResponse.json(await getExternalSanitizedDisplayDownload(workOrderId, submissionRef, parsedRevision, sanitizedDisplayRef));
  } catch (error) {
    if (error instanceof CoreApiError) return NextResponse.json({ code: error.code }, { status: error.status });
    throw error;
  }
}
