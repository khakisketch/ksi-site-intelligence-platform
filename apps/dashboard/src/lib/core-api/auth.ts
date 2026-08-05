import "server-only";

import { CoreApiError, coreFetch, coreFetchWithToken } from "./client";
import type { WhoAmIResponse } from "./types";

export async function whoAmI(): Promise<WhoAmIResponse> {
  return coreFetch<WhoAmIResponse>("/v1/auth/whoami");
}

/** 로그인 화면에서 사용자가 입력한 토큰이 유효한지 확인한다 — 무효면 null(세션 미생성). */
export async function verifyToken(token: string): Promise<WhoAmIResponse | null> {
  let principal: WhoAmIResponse;
  try {
    principal = await coreFetchWithToken<WhoAmIResponse>("/v1/auth/whoami", token);
  } catch (error) {
    // 401(부재/형식오류/미지 토큰, auth.py _unauthorized())만 "무효 토큰"이다. 5xx 등
    // 그 외 상태는 Core 자체 장애이지 사용자 입력 문제가 아니다 — "유효하지 않은
    // 토큰"으로 오표기하지 않고 그대로 던져 login()의 네트워크 예외 처리로 보낸다
    // (독립 재검토 2차 P3-3).
    if (error instanceof CoreApiError && error.status === 401) return null;
    throw error;
  }
  // EDGE_DEVICE 토큰은 대시보드 로그인으로 승격시키지 않는다 — 사람 UI 로 흘러들면
  // role 이 없어 모든 화면이 403 이 되고 TopBar 에 raw "EDGE_DEVICE" 가 노출된다
  // (독립 재검토 P2-E). "무효 토큰"과 동일한 일반 메시지로 처리해 존재 여부를 흘리지
  // 않는다(edge_sync.py 열거 오라클 방지 관습과 동일).
  if (principal.kind !== "OPERATOR") return null;
  return principal;
}
