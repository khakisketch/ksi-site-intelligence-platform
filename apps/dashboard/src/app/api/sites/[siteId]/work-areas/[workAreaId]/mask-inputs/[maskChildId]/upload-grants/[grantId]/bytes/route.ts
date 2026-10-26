import { NextResponse, type NextRequest } from "next/server";

import { MaskedRequestError, parseMaskUploadSealView } from "@/lib/core-api/masked-analysis";
import { coreMaskUploadBytes } from "@/lib/core-api/masked-core";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import { resolveMaskUploadConfig } from "@/lib/mask-upload-config";

function isScopeId(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 255;
}

function isOpaqueId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(value) && !value.includes("..");
}

/**
 * 원시 바이트 업로드 BFF — `application/octet-stream`만 받는다.
 * BFF는 바이트를 해석·저장·복호화하지 않고 Core에 그대로 싣는다. 섭취
 * 상한은 서버 설정(`KSI_DASHBOARD_MASK_UPLOAD_BUDGET_BYTES`)이며,
 * Core 자원 외피 상한이 최종이다. 설정이 없으면 업로드를 막는다.
 * Core가 봉인한 관찰 값(확인값·크기)을 선언 값과 대조해 되돌려준다.
 */
export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string; maskChildId: string; grantId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    await getSessionToken();
    const {
      siteId: rawSiteId,
      workAreaId: rawWorkAreaId,
      maskChildId: rawMaskChildId,
      grantId: rawGrantId,
    } = await params;
    const siteId = decodeURIComponent(rawSiteId);
    const workAreaId = decodeURIComponent(rawWorkAreaId);
    const maskChildId = decodeURIComponent(rawMaskChildId);
    const grantId = decodeURIComponent(rawGrantId);
    if (!isScopeId(siteId) || !isScopeId(workAreaId) || !isOpaqueId(maskChildId) || !isOpaqueId(grantId)) {
      return NextResponse.json({ message: "마스크 식별자가 올바르지 않습니다." }, { status: 400 });
    }
    if (request.headers.get("content-type")?.split(";")[0]?.trim() !== "application/octet-stream") {
      return NextResponse.json({ message: "마스크 원시 바이트만 업로드할 수 있습니다." }, { status: 415 });
    }
    const config = resolveMaskUploadConfig();
    if (!config) {
      return NextResponse.json({ message: "마스크 업로드 예산이 설정되지 않았습니다. 관리자에게 서버 업로드 예산 설정을 요청하세요." }, { status: 503 });
    }
    const declaredSha256 = request.headers.get("x-masked-declared-sha256");
    const declaredSizeRaw = request.headers.get("x-masked-declared-size-bytes");
    const maskArtifactId = request.headers.get("x-masked-artifact-id");
    if (
      !declaredSha256
      || !/^sha256:[0-9a-f]{64}$/.test(declaredSha256)
      || !declaredSizeRaw
      || !/^[1-9]\d*$/.test(declaredSizeRaw)
      || !maskArtifactId
      || !isOpaqueId(maskArtifactId)
    ) {
      return NextResponse.json({ message: "파일 확인 정보(확인값·크기·자료 식별자)가 올바르지 않습니다." }, { status: 400 });
    }
    const declaredSizeBytes = Number(declaredSizeRaw);
    if (!Number.isSafeInteger(declaredSizeBytes) || declaredSizeBytes > config.uploadBudgetBytes) {
      return NextResponse.json({ message: `마스크 파일 크기는 ${config.uploadBudgetBytes}바이트 이하여야 합니다.` }, { status: 413 });
    }
    if (!request.body) {
      return NextResponse.json({ message: "업로드할 바이트가 없습니다." }, { status: 400 });
    }
    const contentLengthRaw = request.headers.get("content-length");
    const byteLength = contentLengthRaw && /^\d+$/.test(contentLengthRaw) ? Number(contentLengthRaw) : null;
    if (byteLength !== null && byteLength !== declaredSizeBytes) {
      return NextResponse.json({ message: "전송 크기가 선언 값과 다릅니다." }, { status: 400 });
    }
    const view = await coreMaskUploadBytes<unknown>(
      `/v3/sites/${encodeURIComponent(siteId)}/work-areas/${encodeURIComponent(workAreaId)}/mask-children/${encodeURIComponent(maskChildId)}/upload-grants/${encodeURIComponent(grantId)}/bytes`,
      { stream: request.body, byteLength, budgetBytes: config.uploadBudgetBytes },
    );
    try {
      return NextResponse.json(
        parseMaskUploadSealView(view, { maskChildId, maskArtifactId, declaredSha256, declaredSizeBytes }),
        { status: 201 },
      );
    } catch {
      return NextResponse.json({ message: "마스크 입력 응답 형식을 확인할 수 없습니다." }, { status: 502 });
    }
  } catch (error) {
    if (error instanceof MaskedRequestError) {
      return NextResponse.json({ message: error.message }, { status: 400 });
    }
    return coreApiErrorResponse(error);
  }
}
