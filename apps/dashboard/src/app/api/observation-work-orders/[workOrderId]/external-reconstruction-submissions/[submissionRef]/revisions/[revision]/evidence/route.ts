import { NextRequest, NextResponse } from "next/server";

import { CoreApiError } from "@/lib/core-api/client";
import { declareExternalEvidenceWithToken, listExternalEvidence } from "@/lib/core-api/external-reconstruction";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import {
  ACCOUNT_CONTINUITY_MISMATCH,
  fetchCurrentContinuityIdentity,
  isSameContinuity,
  parseContinuityClaim,
} from "@/lib/core-api/work-order-continuity";

const ref = /^ers-v1-[0-9a-f]{64}$/;
function revisionOf(params: { workOrderId: string; submissionRef: string; revision: string }): number | null {
  const value = Number(params.revision);
  return /^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$/.test(params.workOrderId) && ref.test(params.submissionRef) && Number.isSafeInteger(value) && value >= 1 && String(value) === params.revision ? value : null;
}
function key(request: Request): string | null { const value = request.headers.get("idempotency-key")?.trim(); return value && value.length <= 255 ? value : null; }
function intent(value: unknown): { targetDsmArtifactId: string; declaredContentDigest: string; declaredContentType: string; independenceBasis: string } | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  if (Object.keys(raw).length !== 4 || !Object.keys(raw).every((name) => ["targetDsmArtifactId", "declaredContentDigest", "declaredContentType", "independenceBasis"].includes(name))) return null;
  return typeof raw.targetDsmArtifactId === "string" && raw.targetDsmArtifactId.length >= 1 && raw.targetDsmArtifactId.length <= 255 && /^sha256:[0-9a-f]{64}$/.test(String(raw.declaredContentDigest)) && typeof raw.declaredContentType === "string" && raw.declaredContentType.trim().length >= 1 && raw.declaredContentType.trim().length <= 255 && typeof raw.independenceBasis === "string" && raw.independenceBasis.trim().length >= 1 && raw.independenceBasis.trim().length <= 1000 ? raw as { targetDsmArtifactId: string; declaredContentDigest: string; declaredContentType: string; independenceBasis: string } : null;
}
function errorResponse(error: unknown) { return error instanceof CoreApiError ? NextResponse.json({ code: error.code }, { status: error.status }) : null; }
export async function GET(_request: Request, context: { params: Promise<{ workOrderId: string; submissionRef: string; revision: string }> }) {
  await getSessionToken(); const params = await context.params; const revision = revisionOf(params);
  if (revision === null) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
  try { return NextResponse.json({ items: await listExternalEvidence(params.workOrderId, params.submissionRef, revision) }); } catch (error) { const response = errorResponse(error); if (response) return response; throw error; }
}
export async function POST(request: NextRequest, context: { params: Promise<{ workOrderId: string; submissionRef: string; revision: string }> }) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  // 같은 요청의 토큰 하나로 연속성 검사와 하위 변이를 잇는다. 토큰을 두 번
  // 읽으면 검사와 Core 선언 사이 세션 교체(TOCTOU)가 생긴다. 호출자 입력(헤더·본문)의
  // principal은 인가 사실로 쓰지 않고, 현재 신원은 항상 이 토큰의 서버 상태로
  // 확인한다. 자격·토큰 원문은 로그·응답에 싣지 않는다.
  let token: string;
  try {
    token = await getSessionToken();
  } catch (error) {
    return coreApiErrorResponse(error);
  }
  const continuity = parseContinuityClaim(request);
  if (continuity.status === "invalid") {
    return NextResponse.json(
      { message: "계정 연속성 확인값이 올바르지 않습니다. 화면을 새로고침한 뒤 다시 시도하세요.", code: "INVALID_CONTINUITY_CLAIM" },
      { status: 400 },
    );
  }
  if (continuity.status === "present") {
    let current;
    try {
      current = await fetchCurrentContinuityIdentity(token);
    } catch (error) {
      return coreApiErrorResponse(error);
    }
    if (!isSameContinuity(current, continuity)) {
      // 모호한 A 요청 뒤 B 세션/조직의 같은 키 재시도 — Core 선언을 내지 않고
      // 원래 키·내용을 살리는 안내로 끊는다. 이는 중복 방지 가드이며 Core의
      // 권한·범위·actor 멱등 보장을 대신하지 않는다.
      const blocked = NextResponse.json(
        {
          message:
            "계정이 바뀌어 같은 증거 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 원래 계정으로 다시 로그인한 뒤 이 화면에서 같은 파일과 선언으로 다시 시도하세요. 기록에서 원래 요청의 증거가 이미 있는지 먼저 확인하세요. 새로고침하면 입력과 요청이 사라집니다.",
          code: ACCOUNT_CONTINUITY_MISMATCH,
        },
        { status: 409 },
      );
      blocked.headers.set("Cache-Control", "private, no-store");
      return blocked;
    }
  }
  const params = await context.params; const revision = revisionOf(params); const idempotencyKey = key(request); const body = intent(await request.json().catch(() => null));
  if (revision === null) return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
  if (!idempotencyKey || !body) return NextResponse.json({ code: "INVALID_EVIDENCE_INTENT" }, { status: 400 });
  try { return NextResponse.json(await declareExternalEvidenceWithToken(params.workOrderId, params.submissionRef, revision, body, idempotencyKey, token), { status: 201 }); } catch (error) { const response = errorResponse(error); if (response) return response; throw error; }
}
