import { NextResponse, type NextRequest } from "next/server";

import {
  getConversation,
  sendConversationMessage,
} from "@/lib/core-api/copilot-conversations";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ conversationId: string }> },
) {
  try {
    await getSessionToken();
    const { conversationId } = await params;
    return NextResponse.json(await getConversation(decodeURIComponent(conversationId)));
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ conversationId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { conversationId } = await params;
    const input = (await request.json()) as { clientMessageId: string; question: string };
    return NextResponse.json(
      await sendConversationMessage(decodeURIComponent(conversationId), input),
    );
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
