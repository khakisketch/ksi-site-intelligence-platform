import "server-only";

import { whoAmI } from "@/lib/core-api/auth";
import { CoreApiError } from "@/lib/core-api/client";
import { MissingSessionError } from "@/lib/core-api/session";
import type { WhoAmIResponse } from "@/lib/core-api/types";

import { classifyFieldSessionFailure, type FieldSessionFailure, type FieldSessionVerdict } from "./field-session";

export type FieldSession =
  | { kind: "ready"; principal: WhoAmIResponse }
  | { kind: "blocked"; verdict: FieldSessionVerdict };

/**
 * 예외를 화면이 아는 사유로 좁힌다.
 *
 * `MissingSessionError` 는 쿠키가 아예 없다는 뜻이라 Core 를 부르지도 않은 상태다 —
 * 401 과 구분해야 "세션이 만료되었습니다"를 첫 방문자에게 띄우지 않는다.
 * 그 외 예외(fetch 실패 등)는 Core 에 닿지 못한 것으로 본다 — 상태코드가 없다는
 * 사실 자체가 응답이 없었다는 뜻이다.
 */
function toFailure(error: unknown): FieldSessionFailure {
  if (error instanceof MissingSessionError) return { kind: "no-session" };
  if (error instanceof CoreApiError) return { kind: "api", status: error.status };
  return { kind: "unreachable" };
}

/** 현장 화면 진입 판정 — 이 함수가 성공해야만 임무 데이터를 조회한다. */
export async function resolveFieldSession(): Promise<FieldSession> {
  let principal: WhoAmIResponse;
  try {
    principal = await whoAmI();
  } catch (error) {
    return { kind: "blocked", verdict: classifyFieldSessionFailure(toFailure(error)) };
  }

  // 장비 토큰이 사람 화면에 흘러들면 role 이 없어 모든 조회가 403 이 되고, 화면은
  // 원인 없이 비어 보인다. 로그인 경로가 이미 막고 있지만(auth.ts verifyToken),
  // 쿠키는 그 경로를 거치지 않고도 존재할 수 있다 — 여기서 한 번 더 끊고 사람에게
  // 할 일(다시 로그인)을 준다.
  if (principal.kind !== "OPERATOR") {
    return {
      kind: "blocked",
      verdict: {
        kind: "login",
        notice: "사람 계정이 아닌 토큰으로 로그인돼 있습니다. 본인 토큰으로 다시 로그인하세요.",
      },
    };
  }

  return { kind: "ready", principal };
}
