import { NextResponse, type NextRequest } from "next/server";

import {
  createSpatialDataRequest,
  type SpatialDataRequestInput,
} from "@/lib/core-api/spatial-data-requests";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import type { SpatialDataBounds } from "@/lib/core-api/spatial-data-types";

const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;
const ASSET_REF_PATTERN = /^ksa-v1-[0-9a-f]{64}$/;
const DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;

/**
 * Console이 만드는 자료 준비 요청의 얇은 통로.
 *
 * 경계·용도는 여기서 모양만 확인하고, 권리(grant)·정책·활성화·네이티브 격자
 * 검증은 Core가 그대로 소유한다. 이 라우트는 어떤 판단도 대신하지 않는다.
 */
function readRequestInput(value: unknown): SpatialDataRequestInput | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const bounds = record.requestedBounds;
  if (
    typeof record.assetRef !== "string"
    || !ASSET_REF_PATTERN.test(record.assetRef)
    || typeof record.observedCrsDigest !== "string"
    || !DIGEST_PATTERN.test(record.observedCrsDigest)
    || record.resolutionMode !== "NATIVE"
    || (record.purpose !== "GENERAL_DATA_USE" && record.purpose !== "EXTERNAL_AI")
    || !Array.isArray(bounds)
    || bounds.length !== 4
    || !bounds.every((entry) => typeof entry === "number" && Number.isFinite(entry))
  ) {
    return null;
  }
  return {
    assetRef: record.assetRef,
    observedCrsDigest: record.observedCrsDigest,
    resolutionMode: "NATIVE",
    purpose: record.purpose,
    requestedBounds: bounds as SpatialDataBounds,
  };
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ siteId: string; workAreaId: string }> },
) {
  if (isCrossSiteMutation(request)) {
    return NextResponse.json({ message: "요청 출처가 올바르지 않습니다." }, { status: 403 });
  }
  try {
    // Reject unauthenticated requests before decoding or forwarding path input.
    await getSessionToken();
    const idempotencyKey = request.headers.get("idempotency-key") ?? "";
    if (!IDEMPOTENCY_KEY_PATTERN.test(idempotencyKey)) {
      return NextResponse.json({ message: "요청 식별자(Idempotency-Key)가 필요합니다." }, { status: 422 });
    }
    const body: unknown = await request.json().catch(() => null);
    const input = readRequestInput(body);
    if (input === null) {
      return NextResponse.json({ message: "자료 요청 형식이 올바르지 않습니다." }, { status: 422 });
    }
    const { siteId, workAreaId } = await params;
    return NextResponse.json(
      await createSpatialDataRequest(siteId, workAreaId, input, idempotencyKey),
    );
  } catch (error) {
    return coreApiErrorResponse(error);
  }
}
