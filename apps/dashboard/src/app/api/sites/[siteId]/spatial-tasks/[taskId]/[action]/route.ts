import { NextResponse, type NextRequest } from "next/server";
import { getSpatialTaskOptions, spatialTaskAction } from "@/lib/core-api/spatial-tasks";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

type Context = { params: Promise<{ siteId: string; taskId: string; action: string }> };

export async function GET(request: NextRequest, { params }: Context) {
  try {
    await getSessionToken();
    const { siteId, taskId, action } = await params;
    if (action !== "options") return NextResponse.json({ message: "지원하지 않는 작업입니다." }, { status: 404 });
    const raw = request.nextUrl.searchParams.get("offset") ?? "0";
    if (!/^\d{1,3}$/.test(raw) || Number(raw) > 500) return NextResponse.json({ message: "목록 위치가 올바르지 않습니다." }, { status: 400 });
    return NextResponse.json(await getSpatialTaskOptions(siteId, taskId, Number(raw)), { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) { return coreApiErrorResponse(error); }
}

export async function POST(request: NextRequest, { params }: Context) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  try {
    await getSessionToken();
    const { siteId, taskId, action } = await params;
    if (action !== "selection" && action !== "readiness" && action !== "run") return NextResponse.json({ message: "지원하지 않는 작업입니다." }, { status: 404 });
    // Bound chunked bodies as well as Content-Length. Core owns strict DTO validation.
    const reader = request.body?.getReader();
    const chunks: Uint8Array[] = [];
    let bytes = 0;
    if (reader) {
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          bytes += value.byteLength;
          if (bytes > 8192) {
            await reader.cancel();
            return NextResponse.json({ message: "선택 요청이 너무 큽니다." }, { status: 413 });
          }
          chunks.push(value);
        }
      } finally { reader.releaseLock(); }
    }
    const joined = new Uint8Array(bytes);
    let offset = 0;
    for (const chunk of chunks) { joined.set(chunk, offset); offset += chunk.byteLength; }
    const result = await spatialTaskAction(siteId, taskId, action, JSON.parse(new TextDecoder().decode(joined)));
    return NextResponse.json(result, { headers: { "Cache-Control": "private, no-store" } });
  } catch (error) { return coreApiErrorResponse(error); }
}
