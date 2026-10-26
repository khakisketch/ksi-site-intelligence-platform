import { NextResponse, type NextRequest } from "next/server";

import {
  MaskedRequestError,
  parseMaskUploadGrantRequest,
  parseMaskUploadGrantView,
} from "@/lib/core-api/masked-analysis";
import { coreMaskJson } from "@/lib/core-api/masked-core";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

const MAX_BODY_BYTES = 65_536;

function isScopeId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 255;
}

function isOpaqueId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value);
}

async function readBoundedJson(request: Request): Promise<unknown> {
  const contentLength = request.headers.get("content-length");
  if (contentLength && /^\d+$/.test(contentLength) && Number(contentLength) > MAX_BODY_BYTES) {
    throw new MaskedRequestError("업로드 부여 요청 본문이 너무 큽니다.");
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
        throw new MaskedRequestError("업로드 부여 요청 본문이 너무 큽니다.");
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
 * 업로드 부여 BFF — 선언과 같은 artifact·subject·선언 값의 메아리만 받는다.
 * Core가 부여 id·만료를 만들며, 객체 키·경로·URL은 절대 내려오지 않는다.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string; maskChildId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const { siteId: rawSiteId, workAreaId: rawWorkAreaId, maskChildId: rawMaskChildId } = await params;
    const siteId = decodeURIComponent(rawSiteId);
    const workAreaId = decodeURIComponent(rawWorkAreaId);
    const maskChildId = decodeURIComponent(rawMaskChildId);
    if (!isScopeId(siteId) || !isScopeId(workAreaId) || !isOpaqueId(maskChildId)) {
      return NextResponse.json({ message: "마스크 식별자가 올바르지 않습니다." }, { status: 400 });
    }
    const body = await readBoundedJson(request);
    const input = parseMaskUploadGrantRequest(body);
    const view = await coreMaskJson<unknown>(
      "POST",
      `/v3/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/mask-children/${encodeURIComponent(maskChildId)}/upload-grants`,
      input,
    );
    try {
      return NextResponse.json(
        parseMaskUploadGrantView(view, { maskChildId, maskArtifactId: input.maskArtifactId }),
        { status: 201 },
      );
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
