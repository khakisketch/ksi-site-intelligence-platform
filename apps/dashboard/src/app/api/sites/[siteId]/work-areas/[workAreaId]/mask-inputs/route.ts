import { NextResponse, type NextRequest } from "next/server";

import {
  parseMaskChildDeclaration,
  parseMaskChildView,
} from "@/lib/core-api/masked-analysis";
import { coreMaskJson } from "@/lib/core-api/masked-core";
import { MaskedRequestError } from "@/lib/core-api/masked-analysis";
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
    throw new MaskedRequestError("마스크 입력 요청 본문이 너무 큽니다.");
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
        throw new MaskedRequestError("마스크 입력 요청 본문이 너무 큽니다.");
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
 * 마스크 자식 선언 BFF — Core `MaskChildDeclarationV1` 와이어를 닫힌
 * 형태로 검증한 뒤 Core에 그대로 전달한다. 선언 subject·기준선은
 * 부모가 Core 기록에서 내려준 봉인 subject 그대로만 받으며, 화면·BFF가
 * 격자·CRS·검사 진실을 지어내지 않는다. 종류 판정·현재성·활성화는
 * Core가 소유한다.
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
    const input = parseMaskChildDeclaration(body);
    if (input.siteId !== siteId || input.workAreaId !== workAreaId) {
      return NextResponse.json({ message: "마스크 선언이 요청 범위를 벗어났습니다." }, { status: 400 });
    }
    const view = await coreMaskJson<unknown>(
      "POST",
      `/v3/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/mask-children`,
      input,
    );
    try {
      return NextResponse.json(parseMaskChildView(view, { siteId, workAreaId, maskChildId: input.maskChildId }), { status: 201 });
    } catch {
      return NextResponse.json({ message: "마스크 입력 응답 형식을 확인할 수 없습니다." }, { status: 502 });
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
