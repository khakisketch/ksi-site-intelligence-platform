import { NextResponse, type NextRequest } from "next/server";

import { parseMaskChildView } from "@/lib/core-api/masked-analysis";
import { coreMaskJson } from "@/lib/core-api/masked-core";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";

function isScopeId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 255;
}

function isOpaqueId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value);
}

/**
 * 마스크 자식 상태 조회 BFF — 선언·업로드·검사 상태를 명시적 새로고침으로만
 * 읽는다. `manifest`가 없으면 검사 대기 중이며, BFF는 폴링하지 않는다.
 * 모르는·남의 기록은 Core가 404로 닫는다.
 */
export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string; maskChildId: string }> },
) {
  try {
    await getSessionToken();
    const { siteId: rawSiteId, workAreaId: rawWorkAreaId, maskChildId: rawMaskChildId } = await params;
    const siteId = decodeURIComponent(rawSiteId);
    const workAreaId = decodeURIComponent(rawWorkAreaId);
    const maskChildId = decodeURIComponent(rawMaskChildId);
    if (!isScopeId(siteId) || !isScopeId(workAreaId) || !isOpaqueId(maskChildId)) {
      return NextResponse.json({ message: "마스크 식별자가 올바르지 않습니다." }, { status: 400 });
    }
    const view = await coreMaskJson<unknown>(
      "GET",
      `/v3/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/mask-children/${encodeURIComponent(maskChildId)}`,
    );
    try {
      return NextResponse.json(parseMaskChildView(view, { siteId, workAreaId, maskChildId }));
    } catch {
      return NextResponse.json({ message: "마스크 입력 응답 형식을 확인할 수 없습니다." }, { status: 502 });
    }
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
