import { NextResponse, type NextRequest } from "next/server";

import {
  MaskedRequestError,
  parseMaskedCalculationCreate,
  parseMaskedCalculationCreated,
} from "@/lib/core-api/masked-analysis";
import { coreMaskJson } from "@/lib/core-api/masked-core";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

const MAX_BODY_BYTES = 65_536;

function isScopeId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 255;
}

async function readBoundedJson(request: Request): Promise<unknown> {
  const contentLength = request.headers.get("content-length");
  if (contentLength && /^\d+$/.test(contentLength) && Number(contentLength) > MAX_BODY_BYTES) {
    throw new MaskedRequestError("마스크 계산 요청 본문이 너무 큽니다.");
  }
  if (!request.body) return undefined;
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      totalBytes += value.byteLength;
      if (totalBytes > MAX_BODY_BYTES) {
        await reader.cancel().catch(() => undefined);
        throw new MaskedRequestError("마스크 계산 요청 본문이 너무 큽니다.");
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
  return JSON.parse(new TextDecoder().decode(bytes)) as unknown;
}

/**
 * V3 계산 생성 BFF — 봉인된 원본 계산 신원 확인값 + 마스크 자식만 받는다.
 * 마스크 바인딩 확인값은 클라이언트가 지어내지 않으며, Core가 봉인
 * manifest로부터 직접 만든다. V2 수치 완료는 전제 조건이 아니다.
 */
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
    const body = await readBoundedJson(request);
    const input = parseMaskedCalculationCreate(body);
    const view = await coreMaskJson<unknown>(
      "POST",
      `/v3/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/masked-calculations`,
      input,
    );
    try {
      return NextResponse.json(parseMaskedCalculationCreated(view, { siteId, workAreaId }), { status: 202 });
    } catch {
      return NextResponse.json({ message: "마스크 계산 응답 형식을 확인할 수 없습니다." }, { status: 502 });
    }
  } catch (error) {
    if (error instanceof MaskedRequestError) {
      const tooLarge = error.message.includes("너무 큽니다");
      return NextResponse.json({ message: error.message }, { status: tooLarge ? 413 : 400 });
    }
    if (error instanceof SyntaxError) {
      return NextResponse.json({ message: "요청 형식이 올바르지 않습니다." }, { status: 400 });
    }
    return coreApiErrorResponse(error);
  }
}
