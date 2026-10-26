import { NextResponse, type NextRequest } from "next/server";

import {
  DeltaPublicationRequestError,
  DeltaUpstreamTimeoutError,
  isScopeId,
  parseDeltaPublicationRequest,
  requestDeltaPublication,
  DELTA_MAX_REQUEST_BODY_BYTES,
} from "@/lib/core-api/delta-publications";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

async function readBoundedBody(request: Request): Promise<{ body: string } | { tooLarge: true }> {
  const contentLength = request.headers.get("content-length");
  if (contentLength && /^\d+$/.test(contentLength) && Number(contentLength) > DELTA_MAX_REQUEST_BODY_BYTES) {
    return { tooLarge: true };
  }
  if (!request.body) return { body: "" };
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      totalBytes += value.byteLength;
      if (totalBytes > DELTA_MAX_REQUEST_BODY_BYTES) {
        await reader.cancel().catch(() => undefined);
        return { tooLarge: true };
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return { body: new TextDecoder().decode(bytes) };
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { siteId: rawSiteId, workAreaId: rawWorkAreaId } = await params;
    const siteId = decodeURIComponent(rawSiteId);
    const workAreaId = decodeURIComponent(rawWorkAreaId);
    if (!isScopeId(siteId) || !isScopeId(workAreaId)) {
      return NextResponse.json({ message: "현장 또는 작업구역 식별자가 올바르지 않습니다." }, { status: 400 });
    }
    const boundedBody = await readBoundedBody(request);
    if ("tooLarge" in boundedBody) {
      return NextResponse.json({ message: "차분 파일 요청 본문이 너무 큽니다." }, { status: 413 });
    }
    const body: unknown = JSON.parse(boundedBody.body);
    const input = parseDeltaPublicationRequest(body);
    return NextResponse.json(await requestDeltaPublication(siteId, workAreaId, input), { status: 202 });
  } catch (error) {
    if (error instanceof DeltaPublicationRequestError) {
      return NextResponse.json({ message: error.message }, { status: 400 });
    }
    if (error instanceof DeltaUpstreamTimeoutError) {
      return NextResponse.json(
        { message: "차분 파일 서버의 응답이 지연됩니다. 수치 결과에는 영향이 없으며, 잠시 후 상태를 확인하세요." },
        { status: 503 },
      );
    }
    return coreApiErrorResponse(error);
  }
}
