import "server-only";

import { NextResponse } from "next/server";

import { humanizeApiError } from "./labels";
import { CoreApiError } from "./client";
import { MissingSessionError } from "./session";

/** Route Handler 공통 에러 응답 — Core API 에러를 사람 말로 번역해 그대로 전달한다. */
export function coreApiErrorResponse(error: unknown): NextResponse {
  if (error instanceof MissingSessionError) {
    // 세션 쿠키 부재 — Core 를 호출하지 않고 여기서 401 로 끊는다(risk
    // dashboard-unauthenticated-signing-proxy 해소 지점 — 고정 ADMIN 토큰 대행 제거).
    return NextResponse.json(
      { message: "세션이 만료되었습니다. 다시 로그인하세요.", code: "MISSING_SESSION" },
      { status: 401 },
    );
  }
  if (error instanceof CoreApiError) {
    return NextResponse.json(
      {
        message: humanizeApiError(error.code, error.status, error.serverMessage),
        code: error.code,
        detail: error.serverMessage,
      },
      { status: error.status },
    );
  }
  if (error instanceof SyntaxError || error instanceof URIError) {
    // 요청 본문 JSON 파싱·경로 세그먼트 디코딩 실패 — 호출자 입력 결함이니 500이 아니라
    // 400이다(독립 재검토 P2-A. 세션 검증을 먼저 통과했다는 전제 — 그 앞단은
    // MissingSessionError 로 이미 401 처리된다).
    return NextResponse.json({ message: "요청 형식이 올바르지 않습니다." }, { status: 400 });
  }
  console.error(error);
  return NextResponse.json({ message: "요청을 처리하지 못했습니다." }, { status: 500 });
}
