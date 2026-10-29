import { NextRequest, NextResponse } from "next/server";
import { CoreApiError } from "@/lib/core-api/client";
import { sealExternalReconstructionSubmissionWithToken } from "@/lib/core-api/external-reconstruction";
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

export async function POST(request: NextRequest, context: { params: Promise<{ workOrderId: string; submissionRef: string; revision: string }> }) {
  if (isCrossSiteMutation(request)) return NextResponse.json({ code: "CROSS_SITE_REQUEST" }, { status: 403 });
  // 동결된 시도의 계정 연속성 비교값(있으면) — 서버가 확인한 두 식별자의
  // 비교값일 뿐 자격 증명이나 인가가 아니다. 호출자가 헤더를 생략하면 기존
  // 동작을 그대로 유지하므로, 헤더 없음이 보호를 의미하지 않는다.
  const continuity = parseContinuityClaim(request);
  if (continuity.status === "invalid") {
    return NextResponse.json(
      { message: "계정 연속성 확인값이 올바르지 않습니다. 화면을 새로고침한 뒤 다시 시도하세요.", code: "INVALID_CONTINUITY_CLAIM" },
      { status: 400 },
    );
  }
  // 같은 요청의 토큰 하나로 연속성 검사와 Core 봉인을 잇는다. 토큰을 두 번
  // 읽으면 검사와 봉인 사이 세션 교체(TOCTOU)가 생긴다. 호출자 입력(헤더·본문)의
  // principal은 인가 사실로 쓰지 않고, 현재 신원은 항상 이 토큰의 서버 상태로
  // 확인한다. 자격·토큰 원문은 로그·응답에 싣지 않는다.
  let token: string;
  try {
    token = await getSessionToken();
  } catch (error) {
    return coreApiErrorResponse(error);
  }
  if (continuity.status === "present") {
    let current;
    try {
      current = await fetchCurrentContinuityIdentity(token);
    } catch (error) {
      return coreApiErrorResponse(error);
    }
    if (!isSameContinuity(current, continuity)) {
      // 모호한 A 요청 뒤 B 세션/조직의 같은 봉인 재시도 — Core 봉인을 내지 않고
      // 원래 식별자·내용을 살리는 안내로 끊는다. 이는 중복 방지 가드이며 Core의
      // 권한·범위·actor 멱등 보장을 대신하지 않는다.
      const blocked = NextResponse.json(
        {
          message:
            "계정이 바뀌어 같은 봉인 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 원래 계정으로 다시 로그인한 뒤 이 화면에서 같은 파일과 신고로 다시 시도하세요. 기록에서 원래 개정의 봉인이 이미 있는지 먼저 확인하세요. 새로고침하면 입력과 요청이 사라집니다.",
          code: ACCOUNT_CONTINUITY_MISMATCH,
        },
        { status: 409 },
      );
      blocked.headers.set("Cache-Control", "private, no-store");
      return blocked;
    }
  }
  const { workOrderId, submissionRef, revision } = await context.params;
  const revisionNumber = Number(revision);
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$/.test(workOrderId) || !ref.test(submissionRef) || !Number.isSafeInteger(revisionNumber) || revisionNumber < 1 || String(revisionNumber) !== revision) {
    return NextResponse.json({ code: "NOT_FOUND" }, { status: 404 });
  }
  try { return NextResponse.json(await sealExternalReconstructionSubmissionWithToken(workOrderId, submissionRef, revisionNumber, token)); }
  catch (error) { if (error instanceof CoreApiError) return NextResponse.json({ code: error.code }, { status: error.status }); throw error; }
}
