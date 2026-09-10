import { NextResponse, type NextRequest } from "next/server";

import { getExternalReobservationProposal } from "@/lib/core-api/external-result-workflow";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

const proposalRef = /^erop-v1-[0-9a-f]{64}$/;

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ proposalRef: string }> },
) {
  try {
    await getSessionToken();
    const { proposalRef: value } = await params;
    if (!proposalRef.test(value)) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
    return NextResponse.json(await getExternalReobservationProposal(value));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
