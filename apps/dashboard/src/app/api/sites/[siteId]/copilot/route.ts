import { NextResponse, type NextRequest } from "next/server";

import {
  createSiteConversation,
  listSiteConversations,
} from "@/lib/core-api/copilot-conversations";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId } = await params;
    return NextResponse.json(await listSiteConversations(decodeURIComponent(siteId)));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { siteId } = await params;
    const input = (await request.json().catch(() => ({}))) as { workOrderId?: string };
    const conversation = await createSiteConversation(
      decodeURIComponent(siteId),
      input.workOrderId,
    );
    return NextResponse.json(conversation, { status: 201 });
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
