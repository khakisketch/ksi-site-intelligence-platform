import { NextRequest, NextResponse } from "next/server";
import { CoreApiError } from "@/lib/core-api/client";
import { requestExternalSingleUseDecisionWithToken } from "@/lib/core-api/external-reconstruction";
import { isCrossSiteMutation } from "@/lib/core-api/origin-guard";
import { coreApiErrorResponse } from "@/lib/core-api/route-handler-util";
import { getSessionToken } from "@/lib/core-api/session";
import {
  ACCOUNT_CONTINUITY_MISMATCH,
  fetchCurrentContinuityIdentity,
  isSameContinuity,
  parseContinuityClaim,
} from "@/lib/core-api/work-order-continuity";
const ref=/^ers-v1-[0-9a-f]{64}$/;
export async function POST(request:NextRequest,context:{params:Promise<{workOrderId:string;submissionRef:string;revision:string}>}) {
  if(isCrossSiteMutation(request))return NextResponse.json({code:"CROSS_SITE_REQUEST"},{status:403});
  // 같은 요청의 토큰 하나로 연속성 검사와 하위 변이를 잇는다. 토큰을 두 번
  // 읽으면 검사와 Core 결정 사이 세션 교체(TOCTOU)가 생긴다. 호출자 입력(헤더·본문)의
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
      // 모호한 A 요청 뒤 B 세션/조직의 같은 키 재시도 — Core 결정을 내지 않고
      // 원래 키·내용을 살리는 안내로 끊는다. 이는 중복 방지 가드이며 Core의
      // 권한·범위·actor 멱등 보장을 대신하지 않는다.
      const blocked = NextResponse.json(
        {
          message:
            "계정이 바뀌어 같은 확인 요청을 다시 보내지 않았습니다. 이전 요청이 처리되었는지는 알 수 없습니다. 원래 계정으로 다시 로그인한 뒤 이 화면에서 같은 요청으로 다시 시도하세요. 기록에서 원래 요청의 판정이 이미 있는지 먼저 확인하세요. 새로고침하면 입력과 요청이 사라집니다.",
          code: ACCOUNT_CONTINUITY_MISMATCH,
        },
        { status: 409 },
      );
      blocked.headers.set("Cache-Control", "private, no-store");
      return blocked;
    }
  }
  const p=await context.params,r=Number(p.revision),k=request.headers.get("idempotency-key")?.trim(),b=await request.json().catch(()=>null);if(!/^[A-Za-z0-9][A-Za-z0-9_-]{0,254}$/.test(p.workOrderId)||!ref.test(p.submissionRef)||!Number.isSafeInteger(r)||r<1||String(r)!==p.revision)return NextResponse.json({code:"NOT_FOUND"},{status:404});if(!k||k.length>255||!b||typeof b!=="object"||Object.keys(b as object).length!==1||((b as {use?:unknown}).use!=="DISPLAY"&&(b as {use?:unknown}).use!=="HEIGHT"))return NextResponse.json({code:"INVALID_EXTERNAL_USE_INTENT"},{status:400});try{return NextResponse.json(await requestExternalSingleUseDecisionWithToken(p.workOrderId,p.submissionRef,r,(b as {use:"DISPLAY"|"HEIGHT"}).use,k,token),{status:201});}catch(e){if(e instanceof CoreApiError)return NextResponse.json({code:e.code},{status:e.status});throw e;}}
