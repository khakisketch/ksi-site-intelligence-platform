import { handlers } from "@/auth";
import type { NextRequest } from "next/server";

export async function GET(request: NextRequest): Promise<Response> {
  // Auth.js의 encrypted HttpOnly JWT는 서버 BFF만 읽는다. session callback이 가진
  // Core access token을 브라우저 JavaScript에 직렬화하는 표면은 열지 않는다.
  if (new URL(request.url).pathname.endsWith("/session")) {
    return new Response(null, { status: 404 });
  }
  return handlers.GET(request);
}

export const POST = handlers.POST;
