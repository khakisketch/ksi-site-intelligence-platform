import "server-only";

import { NextResponse } from "next/server";

import { humanizeApiError } from "./labels";
import { CoreApiError } from "./client";

/** Route Handler 공통 에러 응답 — Core API 에러를 사람 말로 번역해 그대로 전달한다. */
export function coreApiErrorResponse(error: unknown): NextResponse {
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
  console.error(error);
  return NextResponse.json({ message: "요청을 처리하지 못했습니다." }, { status: 500 });
}
